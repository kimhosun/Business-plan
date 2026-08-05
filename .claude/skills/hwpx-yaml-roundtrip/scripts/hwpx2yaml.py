#!/usr/bin/env python3
"""hwpx2yaml — hwpx를 섹션별 YAML(schema hwpx-yaml/1.0)로 추출한다.

계약(references/schema.md, hwpx_common.py)에 엄격히 맞춘다. 좌표계·마커·노드
스키마는 모두 hwpx_common의 공개 함수만 사용해 생성한다.

CLI:
    python hwpx2yaml.py extract --in <hwpx> --out-dir <dir>
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

from hwpx_common import iter_section_nodes, open_hwpx, sha256_file

SCHEMA = "hwpx-yaml/1.0"


def _dump(obj: dict, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(
            obj, fh, allow_unicode=True, sort_keys=False, default_flow_style=False
        )


def extract(in_path: str, out_dir: str) -> tuple[int, int]:
    in_path = str(in_path)
    src_name = os.path.basename(in_path)
    src_sha = sha256_file(in_path)

    doc = open_hwpx(in_path)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    sections_meta: list[dict] = []
    total_nodes = 0

    for si, section in enumerate(doc.sections):
        nodes = list(iter_section_nodes(section, si))
        total_nodes += len(nodes)

        file_name = f"section_{si:02d}.yaml"
        _dump(
            {
                "schema": SCHEMA,
                "source": src_name,
                "source_sha256": src_sha,
                "section_index": si,
                "nodes": nodes,
            },
            out / file_name,
        )

        sections_meta.append(
            {
                "index": si,
                "part_name": getattr(section, "part_name", "") or "",
                "file": file_name,
                "node_count": len(nodes),
            }
        )

    _dump(
        {
            "schema": SCHEMA,
            "source": src_name,
            "source_sha256": src_sha,
            "sections": sections_meta,
        },
        out / "_manifest.yaml",
    )

    return len(sections_meta), total_nodes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hwpx2yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ex = sub.add_parser("extract", help="hwpx를 섹션별 YAML로 추출")
    p_ex.add_argument("--in", dest="in_path", required=True, help="입력 hwpx 경로")
    p_ex.add_argument("--out-dir", dest="out_dir", required=True, help="출력 디렉터리")

    args = parser.parse_args(argv)

    if args.cmd == "extract":
        n_sections, n_nodes = extract(args.in_path, args.out_dir)
        print(f"sections: {n_sections}, total nodes: {n_nodes}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
