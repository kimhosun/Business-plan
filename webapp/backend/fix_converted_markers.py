#!/usr/bin/env python3
"""기존 변환 데이터의 '이중 마커' 정리 (일회성/반복安全 마이그레이션).

배경: 과거 convert 는 본문(text)에 이미 개조식 마커(□·ㅇ·-·< > 캡션 등)가 있는데도
template 기본 마커('□')를 marker 필드에 따로 붙여, 원복 시 "□ ㅇ …" 같은 이중 마커가
찍혔다. claude_service._apply_markers 를 고쳐 향후 변환은 깨끗하지만, 이미 저장된
프로젝트 yaml 에는 잘못된 marker 가 남아 있다.

이 스크립트는 **변환된 노드에 한해**(각 절 result.yaml 에 기록된 path) marker 필드가
군더더기일 때만 "" 로 지운다 — 본문이 스스로 마커/캡션을 달고 있는 경우. 순수 본문
(마커 없는 문장)에 붙은 template 마커는 의도된 것이므로 건드리지 않는다.

- 변환 안 된 원본 노드는 절대 손대지 않는다(result.yaml path 로 게이팅) → 원본 마커 보존.
- 멱등: 이미 marker="" 인 노드는 다시 바꾸지 않는다.

CLI:
  python -m webapp.backend.fix_converted_markers            # 전체 프로젝트 정리
  python -m webapp.backend.fix_converted_markers --dry-run  # 변경 건수만 출력
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from . import config

# 본문이 스스로 선두 마커/캡션을 달고 있는지 — 이 경우 marker 필드의 template '□' 는 군더더기.
# 불릿(□ ○ ㅇ - · o …) + 그림/표 캡션(< 제목 >). 「 『 【 등 내용 괄호는 제외(본문일 수 있음).
_SELF_MARK_ALTS = [
    r"\d+(?:\.\d+)+\.?", r"\d+\.", r"\d+\)", r"\(\d+\)",
    r"[가-힣]\.", r"[가-힣]\)",
    r"[①-⑳ⓐ-ⓩ❶-❿]",
    r"[ㅇㆍ]", r"[□■○●◇◆◈△▲▽▼∙·•◦∘⁃]", r"[oO]",
    r"[-–—]", r"[*※]",
]
_SELF_MARK_RE = re.compile(r"^\s*(?:" + "|".join(_SELF_MARK_ALTS) + r")\s+")
_CAPTION_RE = re.compile(r"^\s*[<＜]")


def _is_self_formatted(text: str) -> bool:
    return bool(text) and bool(_SELF_MARK_RE.match(text) or _CAPTION_RE.match(text))


def _converted_paths(project_dir: Path) -> set[str]:
    """프로젝트의 모든 절 result.yaml 에 기록된 변환 대상 path 집합."""
    paths: set[str] = set()
    for rf in project_dir.glob("nodes/*/result.yaml"):
        try:
            rows = yaml.safe_load(rf.read_text(encoding="utf-8")) or []
        except Exception:  # noqa: BLE001
            continue
        for r in rows:
            if isinstance(r, dict) and r.get("path"):
                paths.add(r["path"])
    return paths


def fix_project(project_dir: Path, *, dry_run: bool = False) -> int:
    """한 프로젝트의 section_*.yaml 에서 변환 노드의 군더더기 marker 를 정리. 변경 건수 반환."""
    converted = _converted_paths(project_dir)
    if not converted:
        return 0
    yaml_dir = project_dir / "yaml"
    changed = 0
    for f in sorted(yaml_dir.glob("section_*.yaml")):
        if f.name == "_manifest.yaml":
            continue
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        dirty = False
        for n in data.get("nodes", []):
            if n.get("kind") not in ("para", "cell_para"):
                continue
            if n.get("path") not in converted:
                continue
            if (n.get("marker") or "") and _is_self_formatted(n.get("text") or ""):
                if not dry_run:
                    n["marker"] = ""
                dirty = True
                changed += 1
        if dirty and not dry_run:
            with open(f, "w", encoding="utf-8") as fh:
                yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False,
                               default_flow_style=False)
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description="기존 변환 데이터의 이중 마커 정리")
    ap.add_argument("--dry-run", action="store_true", help="변경 건수만 출력")
    a = ap.parse_args()

    total = 0
    for pd in sorted(config.PROJECTS_DIR.glob("*")):
        if not pd.is_dir():
            continue
        c = fix_project(pd, dry_run=a.dry_run)
        if c:
            print(f"  {pd.name}: {c} markers cleaned")
        total += c
    verb = "would clean" if a.dry_run else "cleaned"
    print(f"{verb} {total} spurious markers across projects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
