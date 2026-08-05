#!/usr/bin/env python3
"""연구개발계획서 YAML(hwpx-yaml/1.0)에서 좌측 메뉴용 헤딩 트리를 추출한다.

문서 목차(예: "1. 필요성", "1-1. ...", "8-3. ...")를 파싱해
2단계(장/절) 트리를 만들고, 각 메뉴 항목이 담당하는 노드 범위(node_paths)와
그 구간의 ※ 작성요령(guidelines)을 함께 수집한다. 이 범위가 편집·변환·hwpx 반영의 단위다.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

import yaml

# 장: "1. 제목"  /  절: " 1-1. 제목"  (선두 공백 허용)
_CHAP = re.compile(r"^\s*(\d+)\.\s*(\S.*)$")
_SEC = re.compile(r"^\s*(\d+)-(\d+)\.\s*(\S.*)$")
_GUIDE = re.compile(r"^\s*※")


def _load_sections(yaml_dir: str) -> list[dict]:
    out = []
    for f in sorted(os.listdir(yaml_dir)):
        if f.startswith("section_") and f.endswith(".yaml"):
            with open(os.path.join(yaml_dir, f), encoding="utf-8") as fh:
                out.append(yaml.safe_load(fh))
    return out


def _flat_nodes(sections: list[dict]) -> list[dict]:
    flat: list[dict] = []
    for d in sections:
        for n in d.get("nodes", []):
            flat.append(n)
    return flat


def _heading_of(node: dict) -> tuple[str, str, int, str] | None:
    """(num, title, level, kind) 반환. 헤딩이 아니면 None."""
    if node.get("kind") != "para":
        return None
    text = (node.get("marker", "") + " " + (node.get("text") or "")).strip()
    m = _SEC.match(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}", m.group(3).strip(), 2, "sec"
    m = _CHAP.match(text)
    if m:
        # "8-3" 형태가 아닌 순수 "8." 만 장으로
        return m.group(1), m.group(2).strip(), 1, "chap"
    return None


def build_tree(yaml_dir: str) -> list[dict]:
    sections = _load_sections(yaml_dir)
    flat = _flat_nodes(sections)

    # 1) 헤딩 위치 수집
    heads: list[dict] = []
    for idx, node in enumerate(flat):
        h = _heading_of(node)
        if h:
            num, title, level, kind = h
            heads.append({"idx": idx, "num": num, "title": title,
                          "level": level, "path": node["path"]})

    # 2) 각 헤딩의 담당 범위 = 다음 헤딩(같거나 상위 레벨) 전까지
    for i, h in enumerate(heads):
        end = len(flat)
        for j in range(i + 1, len(heads)):
            if heads[j]["level"] <= h["level"]:
                end = heads[j]["idx"]
                break
        span = flat[h["idx"] + 1: end]
        h["node_paths"] = [n["path"] for n in span
                           if n["kind"] in ("para", "cell_para")]
        h["table_paths"] = [n["path"] for n in span if n["kind"] == "table"]
        h["guidelines"] = [
            (n.get("text") or "").strip()
            for n in span
            if n["kind"] in ("para", "cell_para")
            and _GUIDE.match((n.get("marker", "") + " " + (n.get("text") or "")))
        ]
        h["content_count"] = len(h["node_paths"])

    # 3) 같은 num 이 여러 번(목차 + 본문) 나오면 담당 콘텐츠가 가장 많은 것만 채택(=본문)
    best: dict[str, dict] = {}
    for h in heads:
        cur = best.get(h["num"])
        if cur is None or h["content_count"] > cur["content_count"]:
            best[h["num"]] = h

    # 4) num 순서로 정렬해 2단계 트리 구성
    def sort_key(num: str):
        parts = [int(x) for x in num.split("-")]
        return parts + [0] * (2 - len(parts))

    chapters: dict[str, dict] = {}
    for num in sorted(best, key=sort_key):
        h = best[num]
        node = {
            "id": num,                      # "1", "1-1"
            "label": num.replace("-", "."),  # 화면표시: "1", "1.1"
            "num": num,
            "title": h["title"],
            "level": h["level"],
            "path": h["path"],
            "node_paths": h["node_paths"],
            "table_paths": h["table_paths"],
            "guidelines": h["guidelines"],
            "children": [],
        }
        if h["level"] == 1:
            chapters[num] = node
        else:
            parent = num.split("-")[0]
            if parent in chapters:
                chapters[parent]["children"].append(node)
            else:  # 부모 장이 없으면 최상위로
                chapters[num] = node

    return [chapters[k] for k in sorted(chapters, key=sort_key)]


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaml-dir", required=True)
    ap.add_argument("--out", help="tree.json 저장 경로(미지정 시 stdout)")
    a = ap.parse_args()
    tree = build_tree(a.yaml_dir)
    text = json.dumps(tree, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        n_chap = len(tree)
        n_sec = sum(len(c["children"]) for c in tree)
        print(f"tree.json written: {n_chap} chapters, {n_sec} sections -> {a.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
