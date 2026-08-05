#!/usr/bin/env python3
"""hwpx-yaml-roundtrip 공유 모듈 (freeze).

4개 CLI(hwp2hwpx / hwpx2yaml / yaml2hwpx / template)가 이 모듈의 함수만 사용해
좌표계(path)·마커·읽기/쓰기 규칙을 일치시킨다. 계약은 references/schema.md 참조.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Iterator

# python-hwpx가 열 때 찍는 masterPage/history/version fallback 경고를 억제한다.
# (무해한 fallback이며 왕복 무손실은 별도 검증됨. WARNING 레벨이라 ERROR로 올려 차단.)
logging.getLogger("hwpx").setLevel(logging.ERROR)

from hwpx import HwpxDocument

# ── 선두 마커 감지 ────────────────────────────────────────────────────────────
# 우선순위: 다단계 번호(1.2.3) → 괄호번호((1)) → 원문자(①) → 한글표지(가.) → 기호(□○-)
_MARKER_ALTS = [
    r"\d+(?:\.\d+)+\.?",          # 1.1  1.2.3  1.1.
    r"\d+\.",                      # 1.  2.
    r"\d+\)",                      # 1)  2)
    r"\(\d+\)",                    # (1) (2)
    r"[가-힣]\.",                  # 가. 나.
    r"[가-힣]\)",                  # 가) 나)
    r"[①-⑳]",                     # 원숫자
    r"[ⓐ-ⓩ]",                     # 원문자
    r"[❶-❿]",
    r"[□■○●◇◆△▲▽▼◈∙·•※*\-]",   # 기호
]
MARKER_RE = re.compile(r"^\s*(" + "|".join(_MARKER_ALTS) + r")\s+")


def detect_marker(text: str) -> tuple[str, str]:
    """선두 마커와 나머지 본문을 분리한다. 마커가 없으면 ("", 원문)."""
    if not text:
        return "", ""
    m = MARKER_RE.match(text)
    if m:
        return m.group(1), text[m.end():]
    return "", text


def infer_level(marker: str, style, in_cell: bool) -> int:
    """마커/스타일로 개요 레벨을 추정한다. 확신이 없으면 1."""
    if marker:
        if re.fullmatch(r"\d+(?:\.\d+)+\.?", marker):
            return marker.count(".") + (0 if marker.endswith(".") else 1)
        if re.fullmatch(r"\d+\.", marker):
            return 1
        if marker in "□■":
            return 1
        if marker in "○●◇◆":
            return 2
        if marker in "-∙·•":
            return 3
    return 1


# ── 파일/저장 ────────────────────────────────────────────────────────────────
def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def open_hwpx(path) -> HwpxDocument:
    return HwpxDocument.open(str(path))


def save_hwpx(doc: HwpxDocument, path) -> None:
    """deprecated .save() 경고를 피해 저장한다."""
    path = str(path)
    if hasattr(doc, "save_to_path"):
        doc.save_to_path(path)
    elif hasattr(doc, "to_bytes"):
        Path(path).write_bytes(doc.to_bytes())
    else:  # 최후: deprecated save
        doc.save(path)


# ── 노드 추출(DFS) ───────────────────────────────────────────────────────────
def _para_node(para, path: str, in_cell: bool, *, row=None, col=None, span=None) -> dict:
    raw = para.text or ""
    marker, rest = detect_marker(raw)
    node = {
        "path": path,
        "kind": "cell_para" if in_cell else "para",
        "level": infer_level(marker, para.style_id_ref, in_cell),
        "marker": marker,
        "text": rest,
        "style": _int(para.style_id_ref),
        "para_pr": _int(para.para_pr_id_ref),
        "char_pr": _int(para.char_pr_id_ref),
    }
    if in_cell:
        node["row"] = row
        node["col"] = col
        node["span"] = list(span) if span else [1, 1]
    return node


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def _emit_para(para, path: str, in_cell: bool, **cellkw) -> Iterator[dict]:
    yield _para_node(para, path, in_cell, **cellkw)
    for ti, table in enumerate(para.tables):
        tpath = f"{path}/t{ti}"
        yield {"path": tpath, "kind": "table",
               "rows": table.row_count, "cols": table.column_count}
        yield from _emit_table_cells(table, tpath)


def _emit_table_cells(table, tpath: str) -> Iterator[dict]:
    # 병합 셀 dedup은 결정론적인 앵커 주소(arow,acol)로 한다.
    # (lxml proxy의 id()는 호출마다 불안정해 과다/과소 방출을 유발함)
    seen: set[tuple[int, int]] = set()
    for r in range(table.row_count):
        for c in range(table.column_count):
            cell = table.cell(r, c)
            addr = getattr(cell, "address", (r, c)) or (r, c)
            arow, acol = int(addr[0]), int(addr[1])
            key = (arow, acol)
            if key in seen:      # 병합 셀은 앵커에서 1회만
                continue
            seen.add(key)
            span = getattr(cell, "span", (1, 1)) or (1, 1)
            for cpi, cpara in enumerate(cell.paragraphs):
                yield from _emit_para(
                    cpara, f"{tpath}/r{arow}/c{acol}/p{cpi}", True,
                    row=arow, col=acol, span=span,
                )


def iter_section_nodes(section, sidx: int) -> Iterator[dict]:
    for pi, para in enumerate(section.paragraphs):
        yield from _emit_para(para, f"s{sidx}/p{pi}", False)


# ── path 해석(오버레이용) ─────────────────────────────────────────────────────
_SEG = re.compile(r"[a-z](\d+)")


def _idx(seg: str) -> int:
    m = _SEG.fullmatch(seg)
    if not m:
        raise ValueError(f"bad path segment: {seg!r}")
    return int(m.group(1))


def _cell_by_addr(table, arow: int, acol: int):
    """앵커 좌표로 셀을 찾는다(병합 대비)."""
    cell = table.cell(arow, acol)
    return cell


def resolve_para(doc: HwpxDocument, path: str):
    """path(s0/p1/t0/r0/c0/p0)로 문단 객체를 해석한다."""
    parts = path.split("/")
    sidx = _idx(parts[0])
    para = list(doc.sections[sidx].paragraphs)[_idx(parts[1])]
    i = 2
    while i < len(parts):
        ti = _idx(parts[i]); i += 1
        table = list(para.tables)[ti]
        arow = _idx(parts[i]); i += 1
        acol = _idx(parts[i]); i += 1
        cell = _cell_by_addr(table, arow, acol)
        cpi = _idx(parts[i]); i += 1
        para = list(cell.paragraphs)[cpi]
    return para


def resolve_table(doc: HwpxDocument, path: str):
    """tXXX로 끝나는 path의 표 객체를 해석한다."""
    parts = path.split("/")
    sidx = _idx(parts[0])
    para = list(doc.sections[sidx].paragraphs)[_idx(parts[1])]
    table = None
    i = 2
    while i < len(parts):
        ti = _idx(parts[i]); i += 1
        table = list(para.tables)[ti]
        if i >= len(parts):
            return table
        arow = _idx(parts[i]); i += 1
        acol = _idx(parts[i]); i += 1
        cell = _cell_by_addr(table, arow, acol)
        cpi = _idx(parts[i]); i += 1
        para = list(cell.paragraphs)[cpi]
    return table


# ── 쓰기 ─────────────────────────────────────────────────────────────────────
def compose(marker: str, text: str) -> str:
    marker = (marker or "").strip()
    text = text or ""
    return f"{marker} {text}" if marker else text


def write_para(para, marker: str, text: str) -> None:
    """marker+text를 첫 run의 서식(charPr)을 보존하며 기록한다."""
    para.text = compose(marker, text)
