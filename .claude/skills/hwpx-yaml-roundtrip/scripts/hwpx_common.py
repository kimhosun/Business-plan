#!/usr/bin/env python3
"""hwpx-yaml-roundtrip 공유 모듈 (freeze).

4개 CLI(hwp2hwpx / hwpx2yaml / yaml2hwpx / template)가 이 모듈의 함수만 사용해
좌표계(path)·마커·읽기/쓰기 규칙을 일치시킨다. 계약은 references/schema.md 참조.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import unicodedata
import zipfile
from collections import Counter
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


def charpr_heights(hwpx_path) -> dict[int, int]:
    """header.xml 의 charPr id → height(글자높이, pt×100) 맵. 실패 시 {}."""
    heights: dict[int, int] = {}
    try:
        with zipfile.ZipFile(str(hwpx_path)) as z:
            names = [n for n in z.namelist() if n.lower().endswith("header.xml")]
            for nm in names:
                xml = z.read(nm).decode("utf-8", "replace")
                for tag in re.finditer(r"<[A-Za-z0-9]*:?charPr\b[^>]*>", xml):
                    t = tag.group(0)
                    idm = re.search(r'\bid="(\d+)"', t)
                    hm = re.search(r'\bheight="(\d+)"', t)
                    if idm and hm:
                        heights[int(idm.group(1))] = int(hm.group(1))
    except Exception:  # noqa: BLE001 - 헤더 파싱 실패는 폰트 보정만 비활성
        return {}
    return heights


# 이 값(pt×100) 미만 글자높이는 '숨김/간격용' 문단으로 보고, 본문을 채우면 본문 크기로 올린다.
TINY_CHARPR_THRESHOLD = 900  # 9pt


def pick_body_charpr(doc, heights: dict[int, int],
                     tiny_threshold: int = TINY_CHARPR_THRESHOLD):
    """본문(정상 크기) 문단에서 가장 흔한 charPr id 를 고른다. 없으면 None."""
    if not heights:
        return None
    c: Counter = Counter()
    for si, section in enumerate(doc.sections):
        for node in iter_section_nodes(section, si):
            if node.get("kind") not in ("para", "cell_para"):
                continue
            if not (node.get("text") or "").strip():
                continue
            cp = node.get("char_pr")
            try:
                h = heights.get(int(cp))
            except (TypeError, ValueError):
                h = None
            if h is not None and h >= tiny_threshold:
                c[int(cp)] += 1
    return c.most_common(1)[0][0] if c else None


def write_para(para, marker: str, text: str, *,
               body_charpr=None, heights: dict[int, int] | None = None,
               tiny_threshold: int = TINY_CHARPR_THRESHOLD) -> None:
    """marker+text 를 첫 run 의 서식(charPr)을 보존하며 기록한다.

    body_charpr/heights 가 주어지고, 대상 문단의 글자높이가 tiny_threshold 미만
    (원본 템플릿의 1pt·4pt 간격용 빈 문단 등)인데 실제 본문을 채우는 경우에는,
    보이지 않는 초소형 글씨로 렌더되지 않도록 charPr 를 본문 크기로 올린다.
    빈 본문이거나 이미 정상 크기면 건드리지 않는다(왕복 무손실 불변).
    """
    composed = compose(marker, text)
    para.text = composed
    if composed.strip() and body_charpr is not None and heights:
        cur = para.char_pr_id_ref
        try:
            h = heights.get(int(cur)) if cur is not None else None
        except (TypeError, ValueError):
            h = None
        if h is not None and h < tiny_threshold:
            para.char_pr_id_ref = body_charpr


# ── 전역 글꼴/크기 적용(후처리) ───────────────────────────────────────────────
# 최종 hwpx 의 "본문 텍스트=지정글꼴 12pt, 표 셀 텍스트=지정글꼴 8pt" 를 전 구간에
# 강제한다. header.xml 에 두 개의 charPr(본문/셀)을 새로 만들고, 각 section*.xml 의
# 텍스트가 있는 run 의 charPrIDRef 를 표 셀 안이면 셀용, 아니면 본문용으로 바꾼다.
# 빈 run(간격용 빈 문단 등)은 건드리지 않아 레이아웃이 부풀지 않는다. 순수 문자열
# 치환이라 python-hwpx 가 쓴 XML 을 최소 변경으로 손대며(prefix hh:/hp: 유지), 다른
# 바이트는 그대로 둔다.
_FONT_SCRIPTS = [
    ("hangul", "HANGUL"), ("latin", "LATIN"), ("hanja", "HANJA"),
    ("japanese", "JAPANESE"), ("other", "OTHER"), ("symbol", "SYMBOL"),
    ("user", "USER"),
]


def _font_ids_by_lang(header_xml: str, face: str) -> dict[str, str]:
    """fontfaces 각 언어그룹에서 face(예: '돋움')의 font id 를 찾아 {LANG: id}."""
    out: dict[str, str] = {}
    for blk in re.finditer(
        r'<hh:fontface\s+lang="([A-Z]+)"[^>]*>(.*?)</hh:fontface>', header_xml, re.S
    ):
        lang = blk.group(1)
        fm = re.search(rf'<hh:font\s+id="(\d+)"\s+face="{re.escape(face)}"', blk.group(2))
        if fm:
            out[lang] = fm.group(1)
    return out


def _clone_charpr(base: str, new_id: str, height: int, dotum: dict[str, str]) -> str:
    """기준 charPr 문자열을 복제해 id·height 를 바꾸고 fontRef 를 지정 글꼴로 교체."""
    s = re.sub(r'(<hh:charPr\s+id=")\d+(")', rf"\g<1>{new_id}\g<2>", base, count=1)
    s = re.sub(r'(<hh:charPr\b[^>]*?\bheight=")\d+(")', rf"\g<1>{height}\g<2>", s, count=1)

    def _fix_ref(m: "re.Match") -> str:
        tag = m.group(0)
        for attr, lang in _FONT_SCRIPTS:
            if lang in dotum:
                tag = re.sub(rf'{attr}="\d+"', f'{attr}="{dotum[lang]}"', tag)
        return tag

    return re.sub(r"<hh:fontRef\b[^>]*/>", _fix_ref, s, count=1)


def _augment_header(header_xml: str, face: str, body_h: int, cell_h: int):
    """본문/셀용 charPr 두 개를 charProperties 에 추가하고 (header, body_id, cell_id)."""
    dotum = _font_ids_by_lang(header_xml, face)
    if not dotum:
        return header_xml, None, None  # 해당 글꼴이 문서에 없음
    ids = [int(i) for i in re.findall(r'<hh:charPr\s+id="(\d+)"', header_xml)]
    if not ids:
        return header_xml, None, None
    base_id = 0 if 0 in ids else ids[0]
    bm = re.search(rf'<hh:charPr\s+id="{base_id}"[^>]*>.*?</hh:charPr>', header_xml, re.S)
    if not bm:
        return header_xml, None, None
    body_id, cell_id = str(max(ids) + 1), str(max(ids) + 2)
    body_cp = _clone_charpr(bm.group(0), body_id, body_h, dotum)
    cell_cp = _clone_charpr(bm.group(0), cell_id, cell_h, dotum)
    header_xml = header_xml.replace(
        "</hh:charProperties>", body_cp + cell_cp + "</hh:charProperties>", 1
    )
    header_xml = re.sub(
        r'<hh:charProperties itemCnt="(\d+)">',
        lambda m: f'<hh:charProperties itemCnt="{int(m.group(1)) + 2}">',
        header_xml, count=1,
    )
    return header_xml, body_id, cell_id


def _tc_spans(x: str) -> list[tuple[int, int]]:
    """표 셀(<hp:tc>…</hp:tc>) 최상위 구간 [(start,end)] — 중첩표도 이 구간에 포함."""
    spans: list[tuple[int, int]] = []
    depth = 0
    start: int | None = None
    for m in re.finditer(r"<hp:tc\b[^>]*>|</hp:tc>", x):
        tok = m.group(0)
        if tok.startswith("</hp:tc"):
            depth -= 1
            if depth <= 0 and start is not None:
                spans.append((start, m.end()))
                start = None
                depth = 0
        elif tok.endswith("/>"):
            continue  # 자기완결(빈 셀) — 중첩 아님
        else:
            if depth == 0:
                start = m.start()
            depth += 1
    return spans


def _rewrite_section_runs(x: str, body_id: str, cell_id: str) -> tuple[str, int]:
    """텍스트가 있는 run 의 charPrIDRef 를 본문/셀용으로 치환. (xml, 변경 run 수)."""
    spans = _tc_spans(x)

    def _in_cell(pos: int) -> bool:
        for s, e in spans:
            if s <= pos < e:
                return True
            if s > pos:
                break
        return False

    changed = 0

    def _repl(m: "re.Match") -> str:
        nonlocal changed
        attrs, body = m.group(1), m.group(2)
        if 'charPrIDRef="' not in attrs:
            return m.group(0)
        texts = re.findall(r"<hp:t\b[^>]*>(.*?)</hp:t>", body, re.S)
        if not any(t.strip() for t in texts):
            return m.group(0)  # 빈 run(간격용) 은 그대로 — 레이아웃 보존
        tid = cell_id if _in_cell(m.start()) else body_id
        new_attrs = re.sub(r'charPrIDRef="\d+"', f'charPrIDRef="{tid}"', attrs, count=1)
        changed += 1
        return f"<hp:run{new_attrs}>{body}</hp:run>"

    x2 = re.sub(r"<hp:run\b([^>]*)>(.*?)</hp:run>", _repl, x, flags=re.S)
    return x2, changed


def apply_fonts(hwpx_path, *, face: str = "돋움",
                body_pt: int = 12, cell_pt: int = 8) -> dict:
    """최종 hwpx 에 '본문 텍스트=face body_pt, 표 셀 텍스트=face cell_pt' 를 전역 적용.

    반환: {ok, body_charpr, cell_charpr, runs_changed, reason?}. 실패해도 예외를
    던지지 않고 ok=False 로 알린다(폰트 적용 실패가 빌드 전체를 막지 않게).
    """
    path = str(hwpx_path)
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            blobs = {zi.filename: z.read(zi.filename) for zi in infos}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"open: {exc}"}

    hdr_name = next((n for n in blobs if n.endswith("header.xml")), None)
    if not hdr_name:
        return {"ok": False, "reason": "no header.xml"}
    header = blobs[hdr_name].decode("utf-8")
    header2, body_id, cell_id = _augment_header(header, face, body_pt * 100, cell_pt * 100)
    if body_id is None:
        return {"ok": False, "reason": f"font '{face}' or base charPr not found"}
    blobs[hdr_name] = header2.encode("utf-8")

    runs_changed = 0
    for name in list(blobs):
        if re.search(r"section\d+\.xml$", name):
            sx = blobs[name].decode("utf-8")
            sx2, n = _rewrite_section_runs(sx, body_id, cell_id)
            blobs[name] = sx2.encode("utf-8")
            runs_changed += n

    tmp = path + ".tmpfont"
    try:
        with zipfile.ZipFile(tmp, "w") as zf:
            for zi in infos:  # 순서·압축방식(mimetype=stored) 보존
                zf.writestr(zi, blobs[zi.filename])
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001
        try:
            os.path.exists(tmp) and os.remove(tmp)
        except OSError:
            pass
        return {"ok": False, "reason": f"write: {exc}"}
    return {"ok": True, "body_charpr": body_id, "cell_charpr": cell_id,
            "runs_changed": runs_changed}


# ── 표 레이아웃: 셀 글자 가로 가운데정렬 + 표 폭을 용지(본문영역) 폭에 맞춤 ──────
# 최종 hwpx 의 모든 표에 대해:
#   (1) 셀 안 문단 정렬을 CENTER 로 (header.xml 에 center paraPr 추가 후 tc 안 <hp:p>
#       의 paraPrIDRef 를 그것으로 치환). 세로정렬은 원본 subList vertAlign 을 따름.
#   (2) 표 폭을 본문영역 폭(pagePr.width - margin.left - right - gutter)에 맞춤
#       — 표 <hp:sz width> 를 본문폭으로, 모든 <hp:cellSz width> 를 같은 비율로 스케일.
# 순수 문자열 치환(폰트 적용과 동일 방식). 실패해도 예외 없이 ok=False.
def _tbl_spans(x: str) -> list[tuple[int, int]]:
    """최상위 표(<hp:tbl>…</hp:tbl>) 구간(중첩표는 이 구간에 포함)."""
    spans: list[tuple[int, int]] = []
    depth = 0
    start: int | None = None
    for m in re.finditer(r"<hp:tbl\b[^>]*>|</hp:tbl>", x):
        tok = m.group(0)
        if tok.startswith("</hp:tbl"):
            depth -= 1
            if depth <= 0 and start is not None:
                spans.append((start, m.end()))
                start, depth = None, 0
        elif tok.endswith("/>"):
            continue
        else:
            if depth == 0:
                start = m.start()
            depth += 1
    return spans


def _augment_header_center(header_xml: str):
    """base paraPr 를 복제해 가로 CENTER paraPr 를 추가하고 (header, center_id)."""
    ids = [int(i) for i in re.findall(r'<hh:paraPr\s+id="(\d+)"', header_xml)]
    if not ids:
        return header_xml, None
    base_id = 0 if 0 in ids else ids[0]
    bm = re.search(rf'<hh:paraPr\s+id="{base_id}"[^>]*>.*?</hh:paraPr>', header_xml, re.S)
    if not bm:
        return header_xml, None
    cid = str(max(ids) + 1)
    block = re.sub(r'(<hh:paraPr\s+id=")\d+(")', rf"\g<1>{cid}\g<2>", bm.group(0), count=1)
    if re.search(r"<hh:align\b[^>]*/>", block):
        block = re.sub(r'(<hh:align\b[^>]*\bhorizontal=")[A-Z_]+(")',
                       r"\g<1>CENTER\g<2>", block, count=1)
    else:  # align 요소가 없으면 추가
        block = block.replace(">", '><hh:align horizontal="CENTER" vertical="BASELINE"/>', 1)
    header_xml = header_xml.replace("</hh:paraProperties>", block + "</hh:paraProperties>", 1)
    header_xml = re.sub(
        r'<hh:paraProperties itemCnt="(\d+)">',
        lambda m: f'<hh:paraProperties itemCnt="{int(m.group(1)) + 1}">',
        header_xml, count=1,
    )
    return header_xml, cid


# 개조식 불릿·번호로 시작하는 셀 문단(예: '◦ …', '- …', '① …', '(1) …')은
# 좌측 정렬 본문이므로 가운데정렬에서 제외한다. 짧은 라벨·숫자·머리행은 계속 가운데.
_CELL_BULLET_LEAD = re.compile(
    r"^\s*(?:"
    r"[①-⑳ⓐ-ⓩ❶-❿]"                                # 원문자
    r"|[□■▢▣○●◇◆◈△▲▽▼∙·•◦∘⁃▪▫▶▷►◁◀‣※]"           # 기호 불릿(※ 포함)
    r"|[-–—]\s"                                     # 하이픈 불릿(뒤 공백 필수: 음수는 제외)
    r"|\d+[.)]\s|\(\d+\)\s|[가-힣][.)]\s"           # 1. 1) (1) 가.
    r")"
)
_CELL_PROSE_MINLEN = 40  # 이보다 길면 라벨이 아니라 산문으로 보고 가운데정렬 제외


def _center_cells(x: str, center_id: str) -> tuple[str, int]:
    """표 셀(<hp:tc>) 안 <hp:p> 의 paraPrIDRef 를 center paraPr 로 치환.
    단, 개조식 불릿/번호로 시작하거나 긴 산문 셀은 원래 정렬(좌측)을 보존한다."""
    spans = _tc_spans(x)
    changed = 0

    def _in_cell(pos: int) -> bool:
        for s, e in spans:
            if s <= pos < e:
                return True
            if s > pos:
                break
        return False

    def _repl(m: "re.Match") -> str:
        nonlocal changed
        if not _in_cell(m.start()):
            return m.group(0)
        if 'paraPrIDRef="' not in m.group(0):
            return m.group(0)
        lead = _leading_text(x, m.end())
        if lead:
            if _CELL_BULLET_LEAD.match(lead) or len(lead.strip()) > _CELL_PROSE_MINLEN:
                return m.group(0)  # 불릿/산문 셀 → 좌측 정렬 유지
        changed += 1
        return re.sub(r'paraPrIDRef="\d+"', f'paraPrIDRef="{center_id}"', m.group(0), count=1)

    x2 = re.sub(r"<hp:p\b[^>]*>", _repl, x)
    return x2, changed


def _text_width(section_xml: str) -> int | None:
    pp = re.search(r'<hp:pagePr\b[^>]*\bwidth="(\d+)"', section_xml)
    mg = re.search(r"<hp:margin\b[^>]*/>", section_xml)
    if not pp or not mg:
        return None
    W = int(pp.group(1))

    def g(attr: str) -> int:
        m = re.search(rf'\b{attr}="(\d+)"', mg.group(0))
        return int(m.group(1)) if m else 0

    tw = W - g("left") - g("right") - g("gutter")
    return tw if tw > 0 else None


def _fit_tables(x: str, text_width: int) -> tuple[str, int]:
    """각 표 폭을 text_width 로 맞추고 cellSz 폭을 같은 비율로 스케일."""
    spans = _tbl_spans(x)
    out = x
    changed = 0
    for s, e in reversed(spans):          # 뒤에서부터(인덱스 보존)
        seg = x[s:e]
        szm = re.search(r'<hp:sz\s+width="(\d+)"', seg)
        if not szm:
            continue
        cur = int(szm.group(1))
        if cur <= 0:
            continue
        f = text_width / cur
        if abs(f - 1.0) < 0.002:          # 이미 거의 맞음
            continue
        seg = seg[:szm.start()] + \
            re.sub(r'width="\d+"', f'width="{text_width}"', seg[szm.start():szm.end()], 1) + \
            seg[szm.end():]
        seg = re.sub(
            r'(<hp:cellSz\s+width=")(\d+)(")',
            lambda m: m.group(1) + str(max(1, round(int(m.group(2)) * f))) + m.group(3),
            seg,
        )
        out = out[:s] + seg + out[e:]
        changed += 1
    return out, changed


def apply_table_layout(hwpx_path, *, center: bool = True, fit_width: bool = True) -> dict:
    """최종 hwpx 의 모든 표에 '셀 가로 가운데정렬 + 표 폭 본문영역 맞춤' 적용."""
    path = str(hwpx_path)
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            blobs = {zi.filename: z.read(zi.filename) for zi in infos}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"open: {exc}"}

    center_id = None
    if center:
        hdr_name = next((n for n in blobs if n.endswith("header.xml")), None)
        if hdr_name:
            header2, center_id = _augment_header_center(blobs[hdr_name].decode("utf-8"))
            if center_id is not None:
                blobs[hdr_name] = header2.encode("utf-8")

    cells_centered = tables_fit = 0
    for name in list(blobs):
        if not re.search(r"section\d+\.xml$", name):
            continue
        sx = blobs[name].decode("utf-8")
        if center and center_id is not None:
            sx, n = _center_cells(sx, center_id)
            cells_centered += n
        if fit_width:
            tw = _text_width(sx)
            if tw:
                sx, m = _fit_tables(sx, tw)
                tables_fit += m
        blobs[name] = sx.encode("utf-8")

    tmp = path + ".tmptbl"
    try:
        with zipfile.ZipFile(tmp, "w") as zf:
            for zi in infos:
                zf.writestr(zi, blobs[zi.filename])
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001
        try:
            os.path.exists(tmp) and os.remove(tmp)
        except OSError:
            pass
        return {"ok": False, "reason": f"write: {exc}"}
    return {"ok": True, "center_parapr": center_id,
            "cells_centered": cells_centered, "tables_fit": tables_fit}


# ── 출처(인용) 취합 → 문서 맨 끝 '참고자료' 목록 ─────────────────────────────
# 본문 곳곳의 인라인 출처 (출처: 기관, 2024)·(기관, 2024) 와 각 절 끝의 [출처] 목록을
# 모아, 중복 제거 후 문서 맨 끝(마지막 섹션 끝)에 '출처 및 참고자료' 목록으로 붙인다.
# 인라인 출처는 문장에서 제거하고, [출처] 블록 문단은 비운다. python-hwpx 로 수행.
# 명시 키워드는 '출처/Source'만(템플릿의 "(참고…)" 오탐 방지). 그 외에는
# 이름+콤마+연도가 있는 괄호만 인용으로 본다.
_CIT_INLINE = re.compile(
    r"\(\s*(?:출처|Source|source)\s*[:：]?\s*([^()]+?)\s*\)"                # (출처: …)
    r"|\(\s*([^()]*?[가-힣A-Za-z][^()]*?,\s*(?:19|20)\d{2}[^()]*?)\s*\)"    # (기관, 2024)
)
_CIT_BLOCK = re.compile(r"\[\s*출처\s*\]\s*(.*)$", re.S)
_URL_RE = re.compile(r"https?://\S+")


def _norm_source(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s.strip(" .,;·-—")


def _split_sources(tail: str) -> list[str]:
    """[출처] 뒤 문자열을 개별 출처로 분리(줄바꿈/·/;/, 및 URL 경계)."""
    parts = re.split(r"[\n;·]|(?<=\S),(?=\s*(?:[가-힣A-Za-z]|https?))", tail)
    out = []
    for p in parts:
        p = _norm_source(p)
        if p and p not in ("-", "—"):
            out.append(p)
    return out


def collect_sources(hwpx_path, *, heading: str = "출처 및 참고자료",
                    strip_inline: bool = True) -> dict:
    """본문 인용/출처를 모아 문서 맨 끝에 참고자료 목록으로 추가. 예외 없이 dict 반환."""
    path = str(hwpx_path)
    try:
        doc = open_hwpx(path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"open: {exc}"}

    sources: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        n = _norm_source(raw)
        if n and n.lower() not in seen:
            seen.add(n.lower())
            sources.append(n)

    def _walk(paras):
        for p in paras:
            yield p
            for t in p.tables:
                done = set()
                for r in range(t.row_count):
                    for c in range(t.column_count):
                        cell = t.cell(r, c)
                        addr = getattr(cell, "address", (r, c)) or (r, c)
                        key = (int(addr[0]), int(addr[1]))
                        if key in done:
                            continue
                        done.add(key)
                        yield from _walk(cell.paragraphs)

    changed = 0
    for sec in doc.sections:
        for para in _walk(sec.paragraphs):
            txt = para.text or ""
            if not txt.strip():
                continue
            # 1) [출처] 블록 문단 → 통째로 취합 후 비움
            bm = _CIT_BLOCK.search(txt)
            if bm:
                for s in _split_sources(bm.group(1)):
                    _add(s)
                head = txt[:bm.start()].rstrip()
                if strip_inline and head != txt:
                    para.text = head
                    changed += 1
                continue
            # 2) 인라인 (출처…)·(기관, 연도) 취합 후 문장에서 제거
            found = _CIT_INLINE.findall(txt)
            if not found:
                continue
            for g1, g2 in found:
                _add(g1 or g2)
            if strip_inline:
                new = _CIT_INLINE.sub("", txt)
                new = re.sub(r"\s+([,.·])", r"\1", new)     # 괄호 제거로 생긴 공백 정리
                new = re.sub(r"[ \t]{2,}", " ", new).strip()
                if new != txt:
                    para.text = new
                    changed += 1

    if not sources:
        return {"ok": True, "sources": 0, "changed": 0, "reason": "no sources"}

    sec = doc.sections[-1]
    sec.add_paragraph().text = ""
    sec.add_paragraph().text = f"□ {heading}"
    for i, s in enumerate(sources, 1):
        sec.add_paragraph().text = f"{i}. {s}"

    try:
        save_hwpx(doc, path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"save: {exc}"}
    return {"ok": True, "sources": len(sources), "changed": changed}


# ── 개조식 내어쓰기(hanging indent) 후처리 ───────────────────────────────────
# 문단 앞의 도형/번호 마커(□·○·-···※·1.·(1)·가.·① 등) 폭만큼 둘째 줄 이하를
# 들여써(내어쓰기), 마커 뒤 본문에 줄맞춤한다. 본문 문단(표 셀 제외)에만 적용.
#
# HWPX 여백은 <hp:switch> 로 char-unit(hp:case)·HWPUNIT(hp:default) 두 갈래를
# 갖고, 이 문서는 DEFAULT=2×CASE 규약을 쓴다. 마커 폭 em(HWPUNIT)을 계산해
# CASE intent=-em, DEFAULT intent=-2em 으로 두면 문서의 기존 내어쓰기 문단
# (예: '※ …' paraPr 의 -1800/-3600)과 동일한 표기가 된다. left(왼쪽 여백)는 원본
# 값을 유지해 단계 들여쓰기를 보존한다.
_HANG_PREFIX = re.compile(
    r"^(\s*(?:"
    r"\d+(?:\.\d+)+\.?|\d+\.|\d+\)|\(\d+\)|"      # 1.1  1.  1)  (1)
    r"[가-힣][.)]|"                               # 가. 나)
    r"[①-⑳ⓐ-ⓩ❶-❿]|"                            # 원문자
    r"[ㅁㅇㆍ]|"                                   # 한글 자모 불릿(ㅁ=□·ㅇ=○ 대용)
    r"[□■▢▣○●◇◆◈△▲▽▼∙·•◦∘⁃※▪▫▶▷►◁◀‣*]|"       # 기호 불릿
    r"[oO]|[-–—]"                                  # o 불릿 / 하이픈
    r")\s+)"
)


def _prefix_em(prefix: str, body_pt: int) -> int:
    """마커 프리픽스의 폭을 em-HWPUNIT 로. 전각=body_pt*100, 반각=body_pt*50.

    한글(CJK) 문서이므로 East_Asian_Width 가 'A'(Ambiguous, 예: □·○··)인 기호도
    전각으로 본다(전각 렌더). W/F/A → 전각, 그 외(Na/H/N, 공백·라틴 등) → 반각.
    """
    full = body_pt * 100
    half = body_pt * 50
    w = 0
    for ch in prefix:
        w += full if unicodedata.east_asian_width(ch) in ("W", "F", "A") else half
    return w


def _fetch_parapr(header_xml: str, pid: str, cache: dict) -> str | None:
    if pid in cache:
        return cache[pid]
    m = re.search(rf'<hh:paraPr id="{pid}"[^>]*>.*?</hh:paraPr>', header_xml, re.S)
    if not m:
        m = re.search(rf'<hh:paraPr id="{pid}"[^>]*/>', header_xml)
    cache[pid] = m.group(0) if m else None
    return cache[pid]


def _clone_parapr_hang(base: str, new_id: str, em: int) -> str:
    """paraPr 를 복제해 id 를 바꾸고 두 margin 갈래의 intent 를 내어쓰기로 설정.

    CASE(첫 margin) intent=-em, DEFAULT(둘째 margin) intent=-2*em. left 는 원본 유지.
    """
    s = re.sub(r'(<hh:paraPr\s+id=")\d+(")', rf"\g<1>{new_id}\g<2>", base, count=1)
    n_margins = len(re.findall(r"<hh:margin>", s))
    # margin 이 둘이면 [case=-em, default=-2em], 하나면 default 로 간주(-2em).
    vals = [-em, -2 * em] if n_margins >= 2 else [-2 * em]
    counter = {"i": 0}

    def _one_margin(m: "re.Match") -> str:
        blk = m.group(0)
        v = vals[min(counter["i"], len(vals) - 1)]
        counter["i"] += 1
        return re.sub(r'(<hc:intent value=")-?\d+(")', rf"\g<1>{v}\g<2>", blk, count=1)

    return re.sub(r"<hh:margin>.*?</hh:margin>", _one_margin, s, flags=re.S)


def _leading_text(x: str, pos: int) -> str:
    """<hp:p> 시작(pos) 이후, 중첩 구조(표·다음 문단) 이전까지의 본문 텍스트."""
    bound = len(x)
    for tok in ("<hp:tbl", "<hp:p ", "<hp:p>", "</hp:p>"):
        j = x.find(tok, pos)
        if j != -1:
            bound = min(bound, j)
    seg = x[pos:bound]
    return "".join(re.findall(r"<hp:t[^>]*>(.*?)</hp:t>", seg, re.S))


def apply_hanging_indent(hwpx_path, *, body_pt: int = 12) -> dict:
    """본문 개조식 문단에 마커 폭 기준 내어쓰기(hanging indent)를 적용한다.

    표 셀 안 문단은 제외한다. 반환 {ok, paras_changed, parapr_added, reason?}.
    """
    path = str(hwpx_path)
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            blobs = {zi.filename: z.read(zi.filename) for zi in infos}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"open: {exc}"}

    hdr_name = next((n for n in blobs if n.endswith("header.xml")), None)
    if not hdr_name:
        return {"ok": False, "reason": "no header.xml"}
    header = blobs[hdr_name].decode("utf-8")
    ids = [int(i) for i in re.findall(r'<hh:paraPr id="(\d+)"', header)]
    if not ids:
        return {"ok": False, "reason": "no paraPr"}
    next_id = [max(ids) + 1]
    base_cache: dict = {}
    dedup: dict = {}
    new_paraprs: list[str] = []
    paras_changed = 0

    for name in list(blobs):
        if not re.search(r"section\d+\.xml$", name):
            continue
        x = blobs[name].decode("utf-8")
        spans = _tc_spans(x)

        def _in_cell(p: int) -> bool:
            for s, e in spans:
                if s <= p < e:
                    return True
                if s > p:
                    break
            return False

        def _repl(m: "re.Match") -> str:
            nonlocal paras_changed
            attrs = m.group(1)
            if _in_cell(m.start()):
                return m.group(0)
            pp = re.search(r'paraPrIDRef="(\d+)"', attrs)
            if not pp:
                return m.group(0)
            lead = _leading_text(x, m.end())
            # 다중행 문단(개조식 여러 항목이 줄바꿈으로 한 문단에 묶임): 단일 마커
            # 내어쓰기가 부적합하다. 특히 템플릿 슬롯에서 물려받은 과도한 내어쓰기
            # (예: paraPr intent -20129) 때문에 ○/- 줄이 밀려 보이는 문제가 있으므로,
            # 이런 문단의 첫줄 내어쓰기를 0 으로 정규화한다(줄 내 들여쓰기는 본문
            # 선행 공백으로 유지). 단일행 개조식 문단은 아래 기존 로직대로 처리.
            p_close = x.find("</hp:p>", m.end())
            region = x[m.end(): p_close if p_close != -1 else len(x)]
            multiline = ("\n" in lead) or ("\r" in lead) or ("<hp:lineBreak" in region)
            if multiline:
                base = _fetch_parapr(header, pp.group(1), base_cache)
                if base and any(
                    abs(int(v)) > 4000
                    for v in re.findall(r'<hc:intent value="(-?\d+)"', base)
                ):
                    key = (pp.group(1), 0)
                    nid = dedup.get(key)
                    if nid is None:
                        nid = str(next_id[0])
                        next_id[0] += 1
                        new_paraprs.append(_clone_parapr_hang(base, nid, 0))
                        dedup[key] = nid
                    paras_changed += 1
                    new_attrs = re.sub(
                        r'paraPrIDRef="\d+"', f'paraPrIDRef="{nid}"', attrs, count=1
                    )
                    return f"<hp:p{new_attrs}>"
                return m.group(0)
            pm = _HANG_PREFIX.match(lead)
            if not pm:
                return m.group(0)
            em = _prefix_em(pm.group(1), body_pt)
            if em <= 0:
                return m.group(0)
            key = (pp.group(1), em)
            nid = dedup.get(key)
            if nid is None:
                base = _fetch_parapr(header, pp.group(1), base_cache)
                if not base:
                    return m.group(0)
                nid = str(next_id[0])
                next_id[0] += 1
                new_paraprs.append(_clone_parapr_hang(base, nid, em))
                dedup[key] = nid
            paras_changed += 1
            new_attrs = re.sub(r'paraPrIDRef="\d+"', f'paraPrIDRef="{nid}"', attrs, count=1)
            return f"<hp:p{new_attrs}>"

        blobs[name] = re.sub(r"<hp:p\b([^>]*)>", _repl, x).encode("utf-8")

    if not new_paraprs:
        return {"ok": True, "paras_changed": 0, "parapr_added": 0}

    add = "".join(new_paraprs)
    header = header.replace("</hh:paraProperties>", add + "</hh:paraProperties>", 1)
    header = re.sub(
        r'<hh:paraProperties itemCnt="(\d+)">',
        lambda m: f'<hh:paraProperties itemCnt="{int(m.group(1)) + len(new_paraprs)}">',
        header, count=1,
    )
    blobs[hdr_name] = header.encode("utf-8")

    tmp = path + ".tmphang"
    try:
        with zipfile.ZipFile(tmp, "w") as zf:
            for zi in infos:
                zf.writestr(zi, blobs[zi.filename])
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001
        try:
            os.path.exists(tmp) and os.remove(tmp)
        except OSError:
            pass
        return {"ok": False, "reason": f"write: {exc}"}
    return {"ok": True, "paras_changed": paras_changed, "parapr_added": len(new_paraprs)}


# ── 마크다운 표(| a | b |) → 실제 HWPX 표 변환(후처리) ────────────────────────
# 자동작성 초안이 텍스트로 만든 파이프 표(| 구분 | 값 | …)를, 본문 문단을 쪼개
# 실제 표(<hp:tbl>)로 바꾼다. python-hwpx 의 add_table/set_cell_text 로 유효한 표를
# 만들고, 그 문단 위치에 lxml 로 끼워 넣는다. 표를 이미 품은 문단은 건드리지 않는다.
_MD_ROW = re.compile(r"^\s*\|.*\|\s*$")


def _md_parse_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _md_is_sep(cells: list[str]) -> bool:
    return bool(cells) and all(
        re.fullmatch(r":?-{2,}:?", c.strip() or "-") for c in cells if c.strip()
    ) and any(set(c.strip()) <= set(":-") and c.strip() for c in cells)


def _md_blocks(text: str):
    """텍스트를 [('text',str) | ('table',[[cell,…],…])] 블록으로 나눈다."""
    lines = text.split("\n")
    blocks: list = []
    i, n = 0, len(lines)
    while i < n:
        if _MD_ROW.match(lines[i]) and lines[i].count("|") >= 2:
            rows = []
            while i < n and _MD_ROW.match(lines[i]) and lines[i].count("|") >= 2:
                cells = _md_parse_row(lines[i])
                i += 1
                if _md_is_sep(cells):
                    continue
                rows.append(cells)
            if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                blocks.append(("table", rows))
            else:  # 표로 보기 어려우면 원문 텍스트로 되돌림
                raw = "\n".join("| " + " | ".join(r) + " |" for r in rows)
                blocks.append(("text", raw))
        else:
            start = i
            while i < n and not (_MD_ROW.match(lines[i]) and lines[i].count("|") >= 2):
                i += 1
            blocks.append(("text", "\n".join(lines[start:i])))
    # 인접 text 블록 병합
    merged: list = []
    for kind, payload in blocks:
        if kind == "text" and merged and merged[-1][0] == "text":
            merged[-1] = ("text", merged[-1][1] + "\n" + payload)
        else:
            merged.append((kind, payload))
    return merged


def _p_text_el(p) -> str:
    return "".join(t.text or "" for t in p.iter() if t.tag.endswith("}t"))


def _has_table_el(p) -> bool:
    return any(e.tag.endswith("}tbl") for e in p.iter())


def _host_para_of(tbl_el):
    el = tbl_el
    while el is not None and not el.tag.endswith("}p"):
        el = el.getparent()
    return el


def apply_markdown_tables(hwpx_path, *, max_rows: int = 200, max_cols: int = 20) -> dict:
    """본문 문단 안의 마크다운 표를 실제 HWPX 표로 변환한다.

    표를 이미 품은 문단·표 셀 내부는 제외한다. 반환 {ok, tables, reason?}.
    """
    try:
        doc = open_hwpx(hwpx_path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"open: {exc}"}

    made = 0
    try:
        for si, sec in enumerate(doc.sections):
            secel = sec.element
            # 섹션 직속 <hp:p> 만(표 셀 내부 문단 제외). 리스트 스냅샷 후 변형.
            for p in [c for c in list(secel) if c.tag.endswith("}p")]:
                if _has_table_el(p):
                    continue
                text = _p_text_el(p)
                if text.count("|") < 4:
                    continue
                blocks = _md_blocks(text)
                if not any(b[0] == "table" for b in blocks):
                    continue
                pp = p.get("paraPrIDRef")
                new_els: list = []
                for kind, payload in blocks:
                    if kind == "text":
                        # 각 줄을 별도 문단으로(개조식 한 항목=한 문단 → 내어쓰기 정상 적용).
                        for line in payload.split("\n"):
                            if not line.strip():
                                continue
                            np = doc.add_paragraph(
                                line, section_index=si,
                                para_pr_id_ref=pp, inherit_style=True,
                            )
                            new_els.append(np.element)
                    else:
                        rows = payload[:max_rows]
                        nc = min(max(len(r) for r in rows), max_cols)
                        tbl = doc.add_table(len(rows), nc, section_index=si)
                        for r, row in enumerate(rows):
                            for c in range(nc):
                                val = row[c] if c < len(row) else ""
                                try:
                                    tbl.set_cell_text(r, c, val)
                                except Exception:  # noqa: BLE001
                                    pass
                        hp = _host_para_of(tbl.element)
                        if hp is not None:
                            new_els.append(hp)
                        made += 1
                # 원 문단 자리에 순서대로 삽입 후 원 문단 제거.
                anchor = p
                for el in new_els:
                    if el.getparent() is not None:
                        el.getparent().remove(el)
                    anchor.addnext(el)
                    anchor = el
                secel.remove(p)
        save_hwpx(doc, hwpx_path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"convert: {exc}"}
    return {"ok": True, "tables": made}
