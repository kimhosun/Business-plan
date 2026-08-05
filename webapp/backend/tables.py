#!/usr/bin/env python3
"""backend/tables.py — 절 안의 표를 '엑셀형 그리드'로 읽고/쓰고/엑셀 왕복한다.

8장(연구개발비)처럼 표 중심 절을 위해, hwpx 표를 행×열 셀 그리드로 노출한다.
셀 편집은 곧바로 yaml/section_*.yaml 의 해당 cell_para 노드(text)에 반영되고,
[hwpx 빌드] 시 yaml2hwpx 오버레이로 **최종 hwpx 의 표 셀**로 나온다.

좌표계는 hwpx-yaml 파이프라인과 동일:
  표 path = sX/pY/tZ , 셀 문단 path = sX/pY/tZ/rR/cC/pW
한 셀에 문단이 여러 개면 그 셀 값은 문단 text 들을 줄바꿈으로 이어 보이고,
저장 시 줄 단위로 각 문단에 되돌려 쓴다(문단 수 유지).
"""
from __future__ import annotations

import copy
import itertools
import shutil
import sys
from pathlib import Path
from typing import Any

from . import config, pipeline, store

# 구조 편집(행/열)은 python-hwpx 표 API 로는 불가 → OWPML XML 을 직접 조작한다.
if str(config.SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(config.SKILL_SCRIPTS))
import hwpx_common as _H  # noqa: E402  (skill 공유 모듈)
from lxml import etree  # noqa: E402

_NS = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _q(e) -> str:
    return etree.QName(e).localname


def _trs(el):
    return [c for c in el if _q(c) == "tr"]


def _tcs(tr):
    return [c for c in tr if _q(c) == "tc"]


def _addr(tc):
    a = tc.find(f"{_NS}cellAddr")
    return (int(a.get("colAddr")), int(a.get("rowAddr"))) if a is not None else (0, 0)


def _span(tc):
    s = tc.find(f"{_NS}cellSpan")
    return (int(s.get("colSpan", 1)), int(s.get("rowSpan", 1))) if s is not None else (1, 1)


_ID_SEED = itertools.count(970000001)


def _regen_ids(node) -> None:
    for c in node.iter():
        if c.get("id") is not None:
            c.set("id", str(next(_ID_SEED)))


def _blank_text(tc) -> None:
    for t in tc.iter(f"{_NS}t"):
        t.text = ""


def _sidx_of(table_path: str) -> int:
    return int(table_path.split("/")[0][1:])


# ── 그리드 조립 ──────────────────────────────────────────────────────────────
def _cells_of_table(index: dict[str, dict], tpath: str) -> list[dict]:
    """table path 아래 cell_para 들을 (row,col) 셀로 묶어 그리드 셀 목록 반환."""
    prefix = tpath + "/"
    by_cell: dict[tuple[int, int], list[dict]] = {}
    for p, n in index.items():
        if not p.startswith(prefix) or n.get("kind") != "cell_para":
            continue
        key = (int(n.get("row", 0)), int(n.get("col", 0)))
        by_cell.setdefault(key, []).append(n)

    cells: list[dict] = []
    for (r, c), paras in sorted(by_cell.items()):
        paras.sort(key=lambda n: n.get("path", ""))          # p0, p1, …
        span = paras[0].get("span") or [1, 1]
        text = "\n".join((pp.get("text") or "") for pp in paras)
        cells.append({
            "row": r,
            "col": c,
            "rowspan": int(span[0]) if span else 1,
            "colspan": int(span[1]) if len(span) > 1 else 1,
            "paths": [pp.get("path") for pp in paras],
            "text": text,
        })
    return cells


def tables_for(pid: str, nid: str) -> dict:
    """절 nid 의 모든 표를 그리드로. {nid, has_tables, tables:[{path,rows,cols,cells}]}"""
    node = store.node_by_id(pid, nid) or {}
    table_paths = list(node.get("table_paths", []) or [])
    index = pipeline._all_nodes_by_path(pid)

    tables: list[dict] = []
    for i, tp in enumerate(table_paths):
        tnode = index.get(tp, {})
        tables.append({
            "index": i,
            "path": tp,
            "rows": int(tnode.get("rows", 0) or 0),
            "cols": int(tnode.get("cols", 0) or 0),
            "cells": _cells_of_table(index, tp),
        })
    return {
        "nid": nid,
        "label": node.get("label", ""),
        "title": node.get("title", ""),
        "has_tables": bool(tables),
        "table_count": len(tables),
        "tables": tables,
    }


# ── 저장(그리드 → yaml) ──────────────────────────────────────────────────────
def _spread(text: str, paths: list[str]) -> list[dict]:
    """셀 값(줄바꿈 포함)을 셀의 문단 path 들에 줄 단위로 분배."""
    if not paths:
        return []
    lines = (text or "").split("\n")
    out: list[dict] = []
    n = len(paths)
    for i, p in enumerate(paths):
        if i < n - 1:
            val = lines[i] if i < len(lines) else ""
        else:  # 마지막 문단: 남은 줄을 합쳐 담아 내용 손실 방지
            val = "\n".join(lines[i:]) if i < len(lines) else ""
        out.append({"path": p, "text": val})   # marker 생략 → 기존 마커 보존
    return out


def save_cells(pid: str, nid: str, cells: list[dict]) -> dict:
    """cells = [{paths:[...], text}] (변경된 셀만). yaml 에 반영하고 통계 반환."""
    result: list[dict] = []
    for cell in cells or []:
        paths = cell.get("paths") or ([cell["path"]] if cell.get("path") else [])
        result.extend(_spread(cell.get("text", ""), paths))
    stats = pipeline.merge_result_into_yaml(pid, result)
    stats["cells"] = len(cells or [])
    return stats


# ── 엑셀 내보내기/가져오기 ────────────────────────────────────────────────────
def to_xlsx(pid: str, nid: str, out_path: Path) -> Path:
    """절의 표들을 .xlsx 로. 표마다 시트 1개, 셀 위치 그대로. 병합 셀 반영."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    data = tables_for(pid, nid)
    wb = Workbook()
    wb.remove(wb.active)
    header_fill = PatternFill("solid", fgColor="E8EEF7")
    bold = Font(bold=True)
    wrap = Alignment(wrap_text=True, vertical="center")

    for t in data["tables"]:
        title = f"{data['label'] or nid}_표{t['index'] + 1}"[:31]
        ws = wb.create_sheet(title=title)
        for cell in t["cells"]:
            r, c = cell["row"] + 1, cell["col"] + 1
            wc = ws.cell(row=r, column=c, value=cell["text"])
            wc.alignment = wrap
            if cell["row"] == 0:
                wc.font = bold
                wc.fill = header_fill
            rs, cs = cell.get("rowspan", 1), cell.get("colspan", 1)
            if rs > 1 or cs > 1:
                ws.merge_cells(start_row=r, start_column=c,
                               end_row=r + rs - 1, end_column=c + cs - 1)
        # 열 폭 살짝 넓게
        for col in range(1, (t["cols"] or 1) + 1):
            ws.column_dimensions[get_column_letter(col)].width = 16
    if not data["tables"]:
        wb.create_sheet(title="빈표")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))
    return out_path


def from_xlsx(pid: str, nid: str, xlsx_path: Path) -> dict:
    """업로드된 .xlsx 를 위치 기준으로 그리드에 되읽어 저장한다.
    시트는 순서(index)로, 셀은 (row+1,col+1) 위치로 매칭한다."""
    from openpyxl import load_workbook

    wb = load_workbook(str(xlsx_path), data_only=True)
    sheets = wb.worksheets
    data = tables_for(pid, nid)

    edits: list[dict] = []
    for t in data["tables"]:
        if t["index"] >= len(sheets):
            break
        ws = sheets[t["index"]]
        for cell in t["cells"]:
            v = ws.cell(row=cell["row"] + 1, column=cell["col"] + 1).value
            new = "" if v is None else str(v)
            if new != cell["text"]:
                edits.append({"paths": cell["paths"], "text": new})
    stats = save_cells(pid, nid, edits)
    stats["imported_sheets"] = min(len(sheets), len(data["tables"]))
    return stats


# ── 구조 편집(행/열 추가·삭제) ────────────────────────────────────────────────
# 편집은 프로젝트의 base(source.hwpx)를 진화시킨다:
#   1) 현재 yaml 텍스트를 base 에 얹어(restore) 최신 상태 hwpx 를 만든다
#   2) 그 hwpx 의 표 XML 을 조작(행/열)한다
#   3) base 를 교체하고 yaml 을 재추출해 좌표계를 다시 맞춘다
def _base_path(pid: str) -> Path:
    return store.project_dir(pid) / "source.hwpx"


def _apply_structural(pid: str, table_path: str, mutate) -> dict:
    base = _base_path(pid)
    ydir = store.yaml_dir(pid)
    outd = store.output_dir(pid)
    outd.mkdir(parents=True, exist_ok=True)
    tmp = outd / "_struct.hwpx"
    # 롤백 백업(구조편집 실패 시 프로젝트 원상복구)
    bak_base = outd / "_bak_source.hwpx"
    bak_yaml = outd / "_bak_yaml"
    shutil.copy(str(base), str(bak_base))
    if bak_yaml.exists():
        shutil.rmtree(str(bak_yaml))
    shutil.copytree(str(ydir), str(bak_yaml))
    try:
        pipeline.restore(str(base), str(ydir), str(tmp))   # 1) 현재 텍스트 반영
        doc = _H.open_hwpx(str(tmp))                        # 2) 표 XML 조작
        tbl = _H.resolve_table(doc, table_path)
        info = mutate(tbl)
        doc.sections[_sidx_of(table_path)].mark_dirty()
        _H.save_hwpx(doc, str(tmp))
        shutil.copy(str(tmp), str(base))                   # 3) base 교체 + yaml 재추출
        pipeline.extract(str(base), str(ydir))             # (그리드 검증도 겸함)
        return info or {}
    except Exception as exc:  # noqa: BLE001 - 실패하면 원상복구
        shutil.copy(str(bak_base), str(base))
        if ydir.exists():
            shutil.rmtree(str(ydir))
        shutil.copytree(str(bak_yaml), str(ydir))
        raise RuntimeError(
            f"구조 편집 실패(원상복구됨): 병합셀이 많은 표는 이 위치에서 행/열 변경이 "
            f"어려울 수 있습니다. ({type(exc).__name__})"
        ) from exc


def _row_owner_tr(el, row: int):
    """논리 행 row 를 '시작'으로 갖는 tr(행 삽입/삭제의 기준)."""
    for tr in _trs(el):
        cells = _tcs(tr)
        if cells and min(_addr(c)[1] for c in cells) == row:
            return tr
    trs = _trs(el)
    return trs[row] if 0 <= row < len(trs) else (trs[-1] if trs else None)


def add_row(pid: str, nid: str, table_path: str, after_row: int) -> dict:
    """논리 행 after_row 아래에 행 하나 삽입(세로병합 인지).
    - 삽입선을 가로지르는 세로병합 셀 → rowSpan +1
    - after_row 에서 끝나는 셀만 새 행에 복제(서식 유지, 텍스트 비움)
    - after_row 아래 행들은 rowAddr +1"""
    def mutate(tbl):
        el = tbl.element
        at = after_row
        ins = at + 1
        trs = _trs(el)

        def _owner(row):
            for tr in trs:
                cs = _tcs(tr)
                if cs and min(_addr(c)[1] for c in cs) == row:
                    return tr
            return None

        anchor_tr = _owner(ins)          # 삽입 위치(옛 at+1) 앞에 새 tr
        owner_at = _owner(at)
        clones = []
        for tr in trs:
            for tc in _tcs(tr):
                col, row = _addr(tc)
                csp, rsp = _span(tc)
                bot = row + rsp - 1
                if row <= at and bot >= ins:            # 삽입선 가로지름 → 확장
                    sp = tc.find(f"{_NS}cellSpan")
                    sp.set("rowSpan", str(rsp + 1))
                elif row >= ins:                        # 아래로 밀기
                    a = tc.find(f"{_NS}cellAddr")
                    a.set("rowAddr", str(row + 1))
                if bot == at:                           # at 에서 끝나는 셀 → 새 행 복제
                    clones.append(tc)

        new_tr = etree.Element(f"{_NS}tr")
        for tc in sorted(clones, key=lambda t: _addr(t)[0]):
            nc = copy.deepcopy(tc)
            _regen_ids(nc)
            nc.find(f"{_NS}cellAddr").set("rowAddr", str(ins))
            sp = nc.find(f"{_NS}cellSpan")
            if sp is not None:
                sp.set("rowSpan", "1")
            _blank_text(nc)
            new_tr.append(nc)
        if anchor_tr is not None:
            anchor_tr.addprevious(new_tr)
        elif owner_at is not None:
            owner_at.addnext(new_tr)
        elif trs:
            trs[-1].addnext(new_tr)
        else:
            el.append(new_tr)
        el.set("rowCnt", str(int(el.get("rowCnt", "0")) + 1))
        return {"rows": int(el.get("rowCnt"))}
    return _apply_structural(pid, table_path, mutate)


def delete_row(pid: str, nid: str, table_path: str, row: int) -> dict:
    """논리 행 row 삭제(세로병합 인지). 가로지르는 셀은 rowSpan -1, 그 행 전용 셀은 제거."""
    def mutate(tbl):
        el = tbl.element
        for tr in list(_trs(el)):
            for tc in list(_tcs(tr)):
                col, r = _addr(tc)
                csp, rsp = _span(tc)
                bot = r + rsp - 1
                if r == row and rsp == 1:               # 이 행 전용 셀 → 제거
                    tr.remove(tc)
                elif r < row <= bot:                    # 가로지름 → 축소
                    tc.find(f"{_NS}cellSpan").set("rowSpan", str(rsp - 1))
                elif r == row and rsp > 1:              # 이 행에서 시작+아래로 → 축소+한칸 아래
                    tc.find(f"{_NS}cellSpan").set("rowSpan", str(rsp - 1))
                    tc.find(f"{_NS}cellAddr").set("rowAddr", str(row + 1))
                elif r > row:                           # 위로 당기기
                    tc.find(f"{_NS}cellAddr").set("rowAddr", str(r - 1))
            if not _tcs(tr):
                el.remove(tr)
        el.set("rowCnt", str(max(0, int(el.get("rowCnt", "1")) - 1)))
        return {"rows": int(el.get("rowCnt"))}
    return _apply_structural(pid, table_path, mutate)


def _tc_at(tr, col: int):
    for tc in _tcs(tr):
        c = _addr(tc)[0]
        cs = _span(tc)[0]
        if c <= col < c + cs:
            return tc
    return None


def add_col(pid: str, nid: str, table_path: str, after_col: int) -> dict:
    """열 하나 삽입(가로병합 인지). 삽입선을 가로지르는 가로병합 셀은 colSpan +1,
    after_col 에서 끝나는 셀만 새 열에 복제."""
    def mutate(tbl):
        el = tbl.element
        at = after_col
        ins = at + 1
        for tr in _trs(el):
            clones = []
            for tc in _tcs(tr):
                col = _addr(tc)[0]
                csp = _span(tc)[0]
                right = col + csp - 1
                if col <= at and right >= ins:          # 가로지름 → 확장
                    tc.find(f"{_NS}cellSpan").set("colSpan", str(csp + 1))
                elif col >= ins:                        # 오른쪽으로 밀기
                    tc.find(f"{_NS}cellAddr").set("colAddr", str(col + 1))
                if right == at:                         # at 에서 끝나는 셀 → 복제
                    clones.append(tc)
            for tc in clones:
                nc = copy.deepcopy(tc)
                _regen_ids(nc)
                nc.find(f"{_NS}cellAddr").set("colAddr", str(ins))
                sp = nc.find(f"{_NS}cellSpan")
                if sp is not None:
                    sp.set("colSpan", "1")
                _blank_text(nc)
                tc.addnext(nc)
        el.set("colCnt", str(int(el.get("colCnt", "0")) + 1))
        return {"cols": int(el.get("colCnt"))}
    return _apply_structural(pid, table_path, mutate)


def delete_col(pid: str, nid: str, table_path: str, col: int) -> dict:
    """열 col 삭제(가로병합 인지)."""
    def mutate(tbl):
        el = tbl.element
        for tr in _trs(el):
            for tc in list(_tcs(tr)):
                c = _addr(tc)[0]
                csp = _span(tc)[0]
                right = c + csp - 1
                if c == col and csp == 1:
                    tr.remove(tc)
                elif c < col <= right:
                    tc.find(f"{_NS}cellSpan").set("colSpan", str(csp - 1))
                elif c == col and csp > 1:
                    tc.find(f"{_NS}cellSpan").set("colSpan", str(csp - 1))
                    tc.find(f"{_NS}cellAddr").set("colAddr", str(col + 1))
                elif c > col:
                    tc.find(f"{_NS}cellAddr").set("colAddr", str(c - 1))
        el.set("colCnt", str(max(0, int(el.get("colCnt", "1")) - 1)))
        return {"cols": int(el.get("colCnt"))}
    return _apply_structural(pid, table_path, mutate)


# ── 수식(합계 등) 사이드카 ────────────────────────────────────────────────────
# 셀 수식(=SUM(...), =A1+B1 …)은 프런트가 계산해 '값'을 hwpx 에 쓰고,
# 원본 수식은 여기(node/formulas.json)에 보관해 다시 열 때 편집할 수 있게 한다.
import json as _json


def _formulas_path(pid: str, nid: str) -> Path:
    return store.node_dir(pid, nid) / "formulas.json"


def get_formulas(pid: str, nid: str) -> dict:
    p = _formulas_path(pid, nid)
    try:
        return _json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_formulas(pid: str, nid: str, formulas: dict) -> dict:
    p = _formulas_path(pid, nid)
    p.parent.mkdir(parents=True, exist_ok=True)
    # 빈 값은 제거해 깔끔하게 유지
    clean = {k: v for k, v in (formulas or {}).items() if str(v or "").strip()}
    p.write_text(_json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"count": len(clean)}
