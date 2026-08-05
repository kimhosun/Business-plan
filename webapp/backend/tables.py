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

from pathlib import Path
from typing import Any

from . import pipeline, store


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
