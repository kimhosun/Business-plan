#!/usr/bin/env python3
"""hwpx-yaml-roundtrip 템플릿 엔진 (template.py).

레벨별 번호/마커 규칙(template.yaml, schema hwpx-yaml-template/1.0)을 읽어
각 YAML 섹션 파일의 노드 'marker' 필드를 재계산한다. 계약은
references/schema.md 및 프롬프트의 apply_to_nodes CONTRACT를 참조.

CLI:
  python template.py apply --yaml-dir <dir> --template <template.yaml>
  python template.py selftest
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

_LEVEL_KEY_RE = re.compile(r"level(\d+)")


# ── 레벨별 포맷 선택 ──────────────────────────────────────────────────────────
def pick_level_format(tpl: dict, level: int, key: str):
    """key('numbering'|'markers') 섹션에서 주어진 레벨의 포맷 문자열을 고른다.

    level{N} 키가 없으면 정의된 가장 깊은 레벨을 재사용한다. 정의가 아예
    없으면 None.
    """
    section = tpl.get(key) or {}
    defined: dict[int, str] = {}
    for k, v in section.items():
        m = _LEVEL_KEY_RE.fullmatch(str(k))
        if m:
            defined[int(m.group(1))] = v
    if not defined:
        return None
    if level in defined:
        return defined[level]
    return defined[max(defined)]  # 정의된 가장 깊은 레벨 재사용


def _format_number(tpl: dict, level: int, counters: dict) -> str:
    """번호식 마커 문자열을 만든다. {n}=현재레벨, {p}=상위누적, {P}=전체누적."""
    fmt = pick_level_format(tpl, level, "numbering")
    if fmt is None:
        return ""
    n = counters.get(level, 0)
    p = ".".join(str(counters.get(k, 0)) for k in range(1, level))
    big_p = ".".join(str(counters.get(k, 0)) for k in range(1, level + 1))
    return str(fmt).format(n=n, p=p, P=big_p)


def _set_marker(node: dict, new_marker, strip: bool) -> int:
    """node['marker']를 갱신한다. 변경되면 1, 아니면 0 반환."""
    new_marker = new_marker or ""
    old = node.get("marker", "")
    if strip:
        node["marker"] = new_marker
        return 1 if new_marker != old else 0
    # strip_existing=false: 비어있을 때만 채운다
    if old == "":
        node["marker"] = new_marker
        return 1 if new_marker != "" else 0
    return 0


# ── 핵심: apply_to_nodes (CONTRACT) ──────────────────────────────────────────
def apply_to_nodes(nodes: list[dict], tpl: dict) -> int:
    """nodes 각 노드의 'marker'를 tpl 규칙대로 제자리 갱신한다.

    반환값은 변경된 노드 수(호출부는 무시해도 됨 — 계약상 mutate-in-place).
    """
    strip = tpl.get("strip_existing", True)
    use_numbering = bool(tpl.get("numbering"))
    use_markers = (not use_numbering) and bool(tpl.get("markers"))

    table_cfg = tpl.get("table") or {}
    header_rows = table_cfg.get("header_rows", 0) or 0
    header_marker = table_cfg.get("header_marker", "")
    cell_bullet = table_cfg.get("cell_bullet", "")
    apply_to_cells = bool(table_cfg.get("apply_to_cells", False))

    counters: dict[int, int] = {}
    changed = 0

    for node in nodes:
        kind = node.get("kind")

        if kind == "table":
            continue  # 표 컨테이너는 마커 없음

        # 셀 문단인데 레벨 규칙 미적용 → 표 양식(header/cell)만 적용
        if kind == "cell_para" and not apply_to_cells:
            row = node.get("row", 0) or 0
            new_marker = header_marker if row < header_rows else cell_bullet
            changed += _set_marker(node, new_marker, strip)
            continue

        # 여기부터 para, 또는 apply_to_cells인 cell_para
        level = node.get("level", 1) or 1

        if use_numbering:
            # 카운터는 para에서만 전진. cell_para는 apply_to_cells일 때만.
            advance = (kind == "para") or (kind == "cell_para" and apply_to_cells)
            if advance:
                counters[level] = counters.get(level, 0) + 1
                for lv in list(counters):  # 더 깊은 레벨 리셋
                    if lv > level:
                        counters[lv] = 0
            new_marker = _format_number(tpl, level, counters)
            changed += _set_marker(node, new_marker, strip)
        elif use_markers:
            new_marker = pick_level_format(tpl, level, "markers") or ""
            changed += _set_marker(node, new_marker, strip)
        # numbering/markers 둘 다 없으면 para 마커는 손대지 않음

    return changed


# ── CLI: apply ───────────────────────────────────────────────────────────────
def _dump_yaml(data, path):
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(
            data, fh, allow_unicode=True, sort_keys=False, default_flow_style=False
        )


def cmd_apply(yaml_dir: str, template_path: str) -> int:
    with open(template_path, "r", encoding="utf-8") as fh:
        tpl = yaml.safe_load(fh)

    files = sorted(
        p for p in Path(yaml_dir).glob("section_*.yaml") if p.name != "_manifest.yaml"
    )
    if not files:
        print(f"no section_*.yaml found in {yaml_dir}")
        return 0

    total = 0
    for fp in files:
        with open(fp, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        n = apply_to_nodes(data.get("nodes", []), tpl)
        _dump_yaml(data, fp)
        total += n
        print(f"  {fp.name}: {n} markers changed")

    print(f"{total} nodes had markers changed across {len(files)} file(s)")
    return total


# ── CLI: selftest ────────────────────────────────────────────────────────────
def cmd_selftest() -> int:
    scratch = (
        "C:/Users/KIMHOSUN/AppData/Local/Temp/claude/"
        "c--Users-KIMHOSUN-20260602---------R1/"
        "76751b4f-3180-49b6-b1f4-47f6516ced67/scratchpad"
    )
    tpl_path = os.path.join(scratch, "tpl_num.yaml")

    tpl = {
        "schema": "hwpx-yaml-template/1.0",
        "numbering": {"level1": "{n}.", "level2": "{p}.{n}", "level3": "{p}.{n}"},
        "strip_existing": True,
        "table": {
            "header_rows": 1,
            "header_marker": "■",
            "cell_bullet": "-",
            "apply_to_cells": False,
        },
    }
    os.makedirs(scratch, exist_ok=True)
    _dump_yaml(tpl, tpl_path)

    # 인메모리 노드: para L1,L1,L2,L3,L1 + table + cell_paras(header/body)
    nodes = [
        {"path": "s0/p0", "kind": "para", "level": 1, "marker": "", "text": "A"},
        {"path": "s0/p1", "kind": "para", "level": 1, "marker": "old", "text": "B"},
        {"path": "s0/p2", "kind": "para", "level": 2, "marker": "", "text": "B-a"},
        {"path": "s0/p3", "kind": "para", "level": 3, "marker": "", "text": "B-a-i"},
        {"path": "s0/p4", "kind": "para", "level": 1, "marker": "", "text": "C"},
        {"path": "s0/p5/t0", "kind": "table", "rows": 2, "cols": 1},
        {"path": "s0/p5/t0/r0/c0/p0", "kind": "cell_para", "row": 0, "col": 0,
         "span": [1, 1], "level": 1, "marker": "", "text": "hdr"},
        {"path": "s0/p5/t0/r1/c0/p0", "kind": "cell_para", "row": 1, "col": 0,
         "span": [1, 1], "level": 1, "marker": "", "text": "body"},
    ]

    changed = apply_to_nodes(nodes, tpl)
    markers = [(n["path"], n.get("marker")) for n in nodes if n["kind"] != "table"]
    print("markers:", markers)
    print("changed:", changed)

    # 검증
    by_path = {n["path"]: n for n in nodes}
    ok = True
    checks = [
        ("s0/p0", "1."),      # L1 첫번째
        ("s0/p1", "2."),      # L1 두번째 (기존 old 교체)
        ("s0/p2", "2.1"),     # L2 under '2'
        ("s0/p3", "2.1.1"),   # L3 under '2.1'
        ("s0/p4", "3."),      # L1 세번째
        ("s0/p5/t0/r0/c0/p0", "■"),   # 헤더 셀
        ("s0/p5/t0/r1/c0/p0", "-"),   # 본문 셀
    ]
    for path, expect in checks:
        got = by_path[path].get("marker")
        if got != expect:
            ok = False
            print(f"  FAIL {path}: expected {expect!r}, got {got!r}")

    # CLI 을 yaml_selftest 사본에 실행(있을 때만)
    src_dir = os.path.join(scratch, "yaml_selftest")
    if os.path.isdir(src_dir):
        import shutil
        copy_dir = os.path.join(scratch, "yaml_selftest_tplcopy")
        if os.path.isdir(copy_dir):
            shutil.rmtree(copy_dir)
        shutil.copytree(src_dir, copy_dir)
        print(f"[CLI] running apply on copy: {copy_dir}")
        try:
            cmd_apply(copy_dir, tpl_path)
        except Exception as exc:  # noqa: BLE001
            print(f"  CLI apply error: {exc}")

    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# ── entry ────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="hwpx-yaml template engine")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_apply = sub.add_parser("apply", help="rewrite marker fields in YAML sections")
    ap_apply.add_argument("--yaml-dir", required=True)
    ap_apply.add_argument("--template", required=True)

    sub.add_parser("selftest", help="run built-in self-test")

    args = ap.parse_args(argv)
    if args.cmd == "apply":
        cmd_apply(args.yaml_dir, args.template)
        return 0
    if args.cmd == "selftest":
        return cmd_selftest()
    return 2


if __name__ == "__main__":
    sys.exit(main())
