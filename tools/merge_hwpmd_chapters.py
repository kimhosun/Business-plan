#!/usr/bin/env python3
"""Reassemble split HWP Markdown source regions into the master container."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MASTER = ROOT / "연구개발계획서.md"
DEFAULT_PARTS = ROOT / "연구개발계획서_장별"
DEFAULT_OUTPUT = ROOT / "연구개발계획서_장별_병합.md"
BODY_BEGIN = "<!--@hwp-document-begin-->"
BODY_END = "<!--@hwp-document-end-->"
SOURCE_BEGIN = "<!--@hwp-source-begin-->"
SOURCE_END = "<!--@hwp-source-end-->"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def extract_source(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    begin_token = SOURCE_BEGIN + "\n"
    if text.count(SOURCE_BEGIN) != 1 or text.count(SOURCE_END) != 1:
        raise ValueError(f"{path.name}: source markers must occur exactly once")
    begin = text.index(begin_token) + len(begin_token)
    end = text.index(SOURCE_END, begin)
    return text[begin:end]


def validate_fragment(item: dict, fragment: str, allow_anchor_changes: bool) -> None:
    start_node = item.get("start_node")
    end_node = item.get("end_node_exclusive")
    if start_node and f"<!--@hwp node={start_node} " not in fragment:
        raise ValueError(f"{item['filename']}: missing start anchor {start_node}")
    if end_node and f"<!--@hwp node={end_node} " in fragment:
        raise ValueError(
            f"{item['filename']}: contains next part anchor {end_node}; boundary was crossed"
        )
    top_nodes = re.findall(
        r"(?m)^<!--@hwp node=(S\d+\.P\d{4}) pid=", fragment
    )
    expected_count = item.get("top_level_nodes")
    if not allow_anchor_changes and expected_count is not None and len(top_nodes) != expected_count:
        raise ValueError(
            f"{item['filename']}: top-level anchor count {len(top_nodes)} != {expected_count}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge chapter hwp-source regions into the self-contained master Markdown."
    )
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--parts-dir", type=Path, default=DEFAULT_PARTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--allow-anchor-changes",
        action="store_true",
        help="allow changed top-level anchor counts (not recommended for format restoration)",
    )
    args = parser.parse_args()

    manifest_path = args.parts_dir / "_복원_매니페스트.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    master = args.master.read_text(encoding="utf-8")
    if master.count(BODY_BEGIN) != 1 or master.count(BODY_END) != 1:
        raise ValueError("master must contain exactly one document body")
    begin = master.index(BODY_BEGIN) + len(BODY_BEGIN)
    end = master.index(BODY_END, begin)

    fragments: list[str] = []
    for item in manifest["parts"]:
        fragment = extract_source(args.parts_dir / item["filename"])
        validate_fragment(item, fragment, args.allow_anchor_changes)
        fragments.append(fragment)
    merged_body = "".join(fragments)
    merged = master[:begin] + merged_body + master[end:]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(merged, encoding="utf-8", newline="")
    print(f"merged {len(fragments)} parts -> {args.out}")
    print(f"merged body sha256: {sha256_text(merged_body)}")
    if sha256_text(merged_body) == manifest["source_body_sha256"]:
        print("body is byte-for-byte identical to the original UTF-8 Markdown body")
    else:
        print("body differs from original as expected after edits; anchors were validated")


if __name__ == "__main__":
    main()
