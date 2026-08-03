#!/usr/bin/env python3
"""Validate split chapter files, references, anchors, and exact reassembly."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "연구개발계획서.md"
PARTS_DIR = ROOT / "연구개발계획서_장별"
MANIFEST = PARTS_DIR / "_복원_매니페스트.json"
BODY_BEGIN = "<!--@hwp-document-begin-->"
BODY_END = "<!--@hwp-document-end-->"
SOURCE_BEGIN = "<!--@hwp-source-begin-->\n"
SOURCE_END = "<!--@hwp-source-end-->"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    master = MASTER.read_text(encoding="utf-8")
    body_at = master.index(BODY_BEGIN) + len(BODY_BEGIN)
    body_end = master.index(BODY_END, body_at)
    original_body = master[body_at:body_end]

    errors: list[str] = []
    warnings: list[str] = []
    fragments: list[str] = []
    total_refs = 0
    all_top_nodes: list[str] = []

    if sha256_text(master) != manifest["source_sha256"]:
        warnings.append("master hash differs from generation-time source")
    if sha256_text(original_body) != manifest["source_body_sha256"]:
        warnings.append("master body hash differs from generation-time source")

    for item in manifest["parts"]:
        path = PARTS_DIR / item["filename"]
        if not path.exists():
            errors.append(f"{item['filename']}: missing file")
            continue
        text = path.read_text(encoding="utf-8")
        if text.count(SOURCE_BEGIN.strip()) != 1 or text.count(SOURCE_END) != 1:
            errors.append(f"{item['filename']}: invalid source marker count")
            continue
        begin = text.index(SOURCE_BEGIN) + len(SOURCE_BEGIN)
        end = text.index(SOURCE_END, begin)
        fragment = text[begin:end]
        fragments.append(fragment)

        top_nodes = re.findall(
            r"(?m)^<!--@hwp node=(S\d+\.P\d{4}) pid=", fragment
        )
        all_top_nodes.extend(top_nodes)
        if len(top_nodes) != item["top_level_nodes"]:
            errors.append(
                f"{item['filename']}: top-level anchors {len(top_nodes)} != "
                f"{item['top_level_nodes']}"
            )
        if sha256_text(fragment) != item["fragment_sha256"]:
            warnings.append(f"{item['filename']}: source content was edited")

        start_node = item.get("start_node")
        if start_node and f"<!--@hwp node={start_node} " not in fragment:
            errors.append(f"{item['filename']}: missing start anchor {start_node}")
        end_node = item.get("end_node_exclusive")
        if end_node and f"<!--@hwp node={end_node} " in fragment:
            errors.append(f"{item['filename']}: contains next range anchor {end_node}")

        if "## 국내 규정·지침·가이드라인 참조" not in text[end:]:
            errors.append(f"{item['filename']}: missing regulatory reference section")
        links = re.findall(r"\]\((https://[^)]+)\)", text[end:])
        total_refs += len(links)
        if len(links) < item["reference_count"]:
            errors.append(
                f"{item['filename']}: official links {len(links)} < "
                f"{item['reference_count']}"
            )
        nonofficial = [
            link
            for link in links
            if not any(
                domain in link
                for domain in (
                    "law.go.kr",
                    "motir.go.kr",
                    "kistep.re.kr",
                    "iris.go.kr",
                    "keit.re.kr",
                    "rcms.go.kr",
                    "zeus.go.kr",
                )
            )
        ]
        if nonofficial:
            warnings.append(
                f"{item['filename']}: review non-whitelisted domains: {nonofficial}"
            )

    merged_body = "".join(fragments)
    if len(fragments) == len(manifest["parts"]):
        if sha256_text(merged_body) != manifest["source_body_sha256"]:
            warnings.append("combined source body differs from the original after edits")
    if len(all_top_nodes) != len(set(all_top_nodes)):
        duplicates = sorted(
            node for node in set(all_top_nodes) if all_top_nodes.count(node) > 1
        )
        errors.append(f"duplicate top-level anchors: {duplicates}")

    s2_nodes = [
        int(node.rsplit("P", 1)[1])
        for node in all_top_nodes
        if node.startswith("S2.P")
    ]
    expected_s2 = list(range(805))
    if sorted(s2_nodes) != expected_s2:
        missing = sorted(set(expected_s2) - set(s2_nodes))
        extra = sorted(set(s2_nodes) - set(expected_s2))
        errors.append(f"S2 top-level coverage mismatch; missing={missing}, extra={extra}")

    report = {
        "status": "ok" if not errors else "error",
        "parts": len(fragments),
        "official_links": total_refs,
        "top_level_anchors": len(all_top_nodes),
        "s2_top_level_anchors": len(s2_nodes),
        "exact_original_body": sha256_text(merged_body)
        == manifest["source_body_sha256"],
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
