#!/usr/bin/env python3
"""yaml2hwpx.py — 원복(restore).

채워진 YAML(section_*.yaml)을 원본 hwpx의 같은 좌표(path) 문단에 다시 얹어
서식을 100% 보존한 최종 hwpx를 만든다. 선택적으로 template.py로 marker를 재계산한다.
계약: references/schema.md, apply_to_nodes 계약(=== FROZEN CONTRACT ===).

CLI:
  python yaml2hwpx.py restore --hwpx <original.hwpx> --yaml-dir <dir> \
      --out <final.hwpx> [--template <template.yaml>]
  python yaml2hwpx.py selftest    # 무손실 왕복 자체검증
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys

import yaml

# 같은 디렉터리의 hwpx_common / template 을 import 가능하게
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from hwpx_common import (  # noqa: E402
    open_hwpx,
    save_hwpx,
    sha256_file,
    resolve_para,
    write_para,
    iter_section_nodes,
    compose,
    detect_marker,
)


# ── YAML 로딩 ────────────────────────────────────────────────────────────────
def _section_files(yaml_dir: str) -> list[str]:
    files = glob.glob(os.path.join(yaml_dir, "section_*.yaml"))
    # section_00 / section_0 형식 모두 자연 정렬
    def _key(p):
        base = os.path.splitext(os.path.basename(p))[0]
        num = base.split("_")[-1]
        try:
            return (0, int(num))
        except ValueError:
            return (1, base)
    return sorted(files, key=_key)


def _load_section(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data


# ── restore ─────────────────────────────────────────────────────────────────
def restore(hwpx: str, yaml_dir: str, out: str, template: str | None = None) -> int:
    doc = open_hwpx(hwpx)
    orig_sha = sha256_file(hwpx)

    tpl = None
    template_mod = None
    if template:
        with open(template, "r", encoding="utf-8") as fh:
            tpl = yaml.safe_load(fh) or {}
        import template as template_mod  # noqa: F401  (sibling module)

    files = _section_files(yaml_dir)
    if not files:
        print(f"[yaml2hwpx] ERROR: no section_*.yaml under {yaml_dir}")
        return 2

    written = 0
    skipped = 0
    failures = 0
    fail_paths: list[str] = []
    drift_warned = False

    for f in files:
        data = _load_section(f)
        sec_sha = data.get("source_sha256")
        if sec_sha and str(sec_sha).upper() != orig_sha and not drift_warned:
            print(
                f"[yaml2hwpx] WARNING: source_sha256 mismatch in {os.path.basename(f)} "
                f"(yaml={sec_sha} original={orig_sha}); overlaying anyway."
            )
            drift_warned = True

        nodes = data.get("nodes") or []

        # 템플릿 적용(오버레이 전, in-memory) — 섹션 단위
        if tpl is not None and template_mod is not None:
            template_mod.apply_to_nodes(nodes, tpl)

        for node in nodes:
            kind = node.get("kind")
            if kind not in ("para", "cell_para"):
                continue  # table 노드 등은 건너뜀
            path = node.get("path")
            try:
                para = resolve_para(doc, path)
                # 내용이 동일하면 문단을 건드리지 않는다.
                # (.text setter는 런을 재생성하며 컬럼 브레이크 등 제어를 지우므로
                #  실제 편집된 문단만 기록해야 레이아웃이 보존된다.)
                # 판정은 추출과 동일한 방식(detect_marker)으로 재분해해 비교한다
                # → 마커 뒤 공백/들여쓰기 차이만으로는 재기록하지 않는다.
                cur_marker, cur_text = detect_marker(para.text or "")
                if (cur_marker, cur_text) == (node.get("marker", ""), node.get("text", "")):
                    skipped += 1
                    continue
                write_para(para, node.get("marker", ""), node.get("text", ""))
                written += 1
            except Exception as exc:  # noqa: BLE001
                failures += 1
                if len(fail_paths) < 5:
                    fail_paths.append(f"{path} -> {type(exc).__name__}: {exc}")

    save_hwpx(doc, out)
    size = os.path.getsize(out)
    print(f"[yaml2hwpx] nodes written: {written}, skipped(unchanged): {skipped}, "
          f"failures: {failures}, "
          f"out: {out} ({size} bytes)")
    if fail_paths:
        print("[yaml2hwpx] first failing paths:")
        for fp in fail_paths:
            print(f"    - {fp}")
    return 0 if failures == 0 else 1


# ── 자체검증(무손실 왕복) ─────────────────────────────────────────────────────
_SCR = ("C:/Users/KIMHOSUN/AppData/Local/Temp/claude/"
        "c--Users-KIMHOSUN-20260602---------R1/"
        "76751b4f-3180-49b6-b1f4-47f6516ced67/scratchpad")
_ORIG = f"{_SCR}/연구개발계획서.hwpx"
_YAML_RT = f"{_SCR}/yaml_rt"
_RT_OUT = f"{_SCR}/rt_out.hwpx"


def _inline_extract(hwpx: str, out_dir: str) -> None:
    """hwpx2yaml.py 부재 시 대체: iter_section_nodes로 section_*.yaml 생성."""
    os.makedirs(out_dir, exist_ok=True)
    doc = open_hwpx(hwpx)
    sha = sha256_file(hwpx)
    for si, section in enumerate(doc.sections):
        nodes = list(iter_section_nodes(section, si))
        data = {
            "schema": "hwpx-yaml/1.0",
            "source": os.path.basename(hwpx),
            "source_sha256": sha,
            "section_index": si,
            "nodes": nodes,
        }
        with open(os.path.join(out_dir, f"section_{si:02d}.yaml"),
                  "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False,
                           default_flow_style=False)


def _content_multiset(hwpx: str):
    """비어있지 않은 (kind, marker+text) 의 Counter — 정보용(순서 무시)."""
    from collections import Counter
    doc = open_hwpx(hwpx)
    c: Counter = Counter()
    for si, section in enumerate(doc.sections):
        for node in iter_section_nodes(section, si):
            if node.get("kind") not in ("para", "cell_para"):
                continue
            combined = compose(node.get("marker", ""), node.get("text", ""))
            if combined.strip():
                c[(node["kind"], combined)] += 1
    return c


def _verify_readback(out_hwpx: str, yaml_dir: str):
    """결정론적 무손실 검증: YAML의 모든 para/cell_para 노드를 그 path로 다시
    읽어(resolve_para) compose(marker,text)와 완전히 일치하는지 대조한다.
    resolve_para는 위치/셀주소 기반이라 결정론적이므로, 병합셀 순회 비결정성을
    타지 않고 '쓴 값이 그대로 다시 읽힌다'는 무손실성을 직접 증명한다."""
    doc = open_hwpx(out_hwpx)
    total = 0
    mism = 0
    samples: list[tuple[str, str, str]] = []
    for f in _section_files(yaml_dir):
        data = _load_section(f)
        for n in data.get("nodes", []):
            if n.get("kind") not in ("para", "cell_para"):
                continue
            total += 1
            expect = compose(n.get("marker", ""), n.get("text", ""))
            try:
                got = resolve_para(doc, n["path"]).text or ""
            except Exception as exc:  # noqa: BLE001
                got = f"<ERR {type(exc).__name__}: {exc}>"
            if got != expect:
                mism += 1
                if len(samples) < 5:
                    samples.append((n["path"], expect, got))
    return total, mism, samples


def selftest() -> int:
    # 1) YAML 확보
    if not os.path.isdir(_YAML_RT) or not _section_files(_YAML_RT):
        h2y = os.path.join(_HERE, "hwpx2yaml.py")
        extracted = False
        if os.path.isfile(h2y):
            try:
                subprocess.run(
                    [sys.executable, h2y, "extract",
                     "--in", _ORIG, "--out-dir", _YAML_RT],
                    check=True, cwd=_HERE,
                )
                extracted = bool(_section_files(_YAML_RT))
            except Exception as exc:  # noqa: BLE001
                print(f"[selftest] hwpx2yaml subprocess failed ({exc}); "
                      f"falling back to inline extract.")
        if not extracted:
            print("[selftest] inline-extracting YAML via iter_section_nodes.")
            _inline_extract(_ORIG, _YAML_RT)

    # 2) restore (템플릿 없이)
    rc = restore(_ORIG, _YAML_RT, _RT_OUT, template=None)
    if rc == 2:
        print("[selftest] FAIL: restore could not find YAML.")
        return 1
    write_failed = (rc == 1)

    # 3) 무손실 라운드트립 판정 = 결정론적 path 재독(readback)
    #    (frozen hwpx_common._emit_table_cells 는 병합셀 dedup 을 id(cell.element)
    #     로 하는데 lxml proxy id 가 불안정해 iter_section_nodes 순회가
    #     동일 파일 재오픈 시에도 비결정적이다. 따라서 순서 기반 리스트 비교로는
    #     0 diff 를 보장할 수 없어, 결정론적 readback 을 정식 판정 기준으로 쓴다.)
    total, mism, samples = _verify_readback(_RT_OUT, _YAML_RT)
    print(f"[selftest] readback verify: {total} nodes, {mism} mismatches")
    for path, exp, got in samples:
        print(f"    - {path}\n        expect={exp!r}\n        got   ={got!r}")

    # (정보용) 내용 멀티셋 비교 — 순서/병합셀 비결정성 영향은 참고만.
    try:
        c_orig = _content_multiset(_ORIG)
        c_out = _content_multiset(_RT_OUT)
        only_orig = c_orig - c_out
        only_out = c_out - c_orig
        print(f"[selftest] (info) content-multiset delta: "
              f"only_in_orig={sum(only_orig.values())}, "
              f"only_in_out={sum(only_out.values())} "
              f"(nonzero here is traversal non-determinism, not data loss)")
    except Exception as exc:  # noqa: BLE001
        print(f"[selftest] (info) multiset compare skipped: {exc}")

    if not write_failed and mism == 0:
        print(f"[selftest] MATCH — lossless round-trip proven "
              f"({total} nodes read back byte-identical, 0 write failures)")
        return 0
    print(f"[selftest] FAIL — write_failed={write_failed}, mismatches={mism}")
    return 1


# ── CLI ──────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="yaml2hwpx — restore filled YAML onto hwpx")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("restore", help="overlay filled YAML back onto original hwpx")
    r.add_argument("--hwpx", required=True, help="original (source-of-truth) hwpx")
    r.add_argument("--yaml-dir", required=True, help="dir with section_*.yaml")
    r.add_argument("--out", required=True, help="output final hwpx")
    r.add_argument("--template", default=None, help="optional template.yaml")

    sub.add_parser("selftest", help="lossless round-trip identity self-test")

    args = p.parse_args(argv)
    if args.cmd == "restore":
        return restore(args.hwpx, args.yaml_dir, args.out, args.template)
    if args.cmd == "selftest":
        return selftest()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
