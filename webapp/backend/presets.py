#!/usr/bin/env python3
"""절별 '작성 프롬프트' 프리셋 — 참조 사업계획서 문체·구성(rnd-write-*) 연동.

rnd-proposal-writer/references/_지침/지침.json(공통원칙 §0~§9 + 절별 지침)을
단일 원천으로, 각 트리 절(nid)에 맞는 문체(style)/구성(structure)/체크리스트를 조립한다.
- style     : 어떻게 쓰는가(개조식 종결·마커 계층·정량화·약어).
              절별 문체(_프롬프트 도출, prompt_styles.json) + 공통 문체 원칙(§1·§2·§3·§5).
- structure : 무엇을 어떤 골격으로(역할·표준골격·변형·체크리스트) = 절별 지침 directives/checklist
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import config

_GUIDE_JSON = (
    config.ROOT_DIR
    / ".claude" / "skills" / "rnd-proposal-writer"
    / "references" / "_지침" / "지침.json"
)

# 절별 문체(문체 스타일) — _프롬프트 폴더의 절별 '문체·형식 규칙'에서 도출.
_PROMPT_STYLES_JSON = Path(__file__).resolve().parent / "prompt_styles.json"

# 트리 nid ↔ 지침 파일이 1:1이 아닌 경우 보정(문서 목차 vs rnd-write 분류 차이)
_OVERRIDES = {
    "3-3": "3-2",   # 기술개발팀 편성도 → 절_3-2 추진체계·팀편성도
    "5-5": "5-3",   # 사회적 가치 창출 → 절_5-3 표준화·사회적가치
}

# style 로 묶을 공통원칙 절(문체 계열), structure 앞에 붙일 공통원칙 절(구성 계열)
_STYLE_SECTIONS = {"§1", "§2", "§3", "§5"}
_STRUCT_SECTIONS = {"§4", "§7"}

# 지침 JSON 의 skill 이 비어있는 절 보정(파일 토큰 → rnd-write 스킬명)
_SKILL_BY_TOKEN = {
    "1-1": "rnd-write-1-1-overview", "1-2": "rnd-write-1-2-market",
    "1-3": "rnd-write-1-3-ip", "2-1": "rnd-write-2-1-goal",
    "2-2": "rnd-write-2-2-annual", "2-3": "rnd-write-2-3-schedule",
    "3-1": "rnd-write-3-1-strategy", "3-2": "rnd-write-3-2-system-team",
    "3-4": "rnd-write-3-4-jobs", "3-5": "rnd-write-3-5-demo",
    "4": "rnd-write-4-utilization", "5-1": "rnd-write-5-1-market-record",
    "5-2": "rnd-write-5-2-bm-ip", "5-3": "rnd-write-5-3-value",
    "5-4": "rnd-write-5-4-econ", "6": "rnd-write-6-safety-security",
    "7": "rnd-write-7-org", "8": "rnd-write-8-budget",
    "요약문": "rnd-write-summary",
}


def _token_of(fn: str | None) -> str:
    if not fn:
        return ""
    m = re.match(r"절_([^_]+)_", fn)
    return m.group(1) if m else ""


def _clean(text: str) -> str:
    """마크다운 강조/코드표기를 걷어 텍스트에어리어에 읽기 좋게."""
    if not text:
        return ""
    text = re.sub(r"[*`]+", "", text)
    return text.strip()


@lru_cache(maxsize=1)
def _guide() -> dict:
    try:
        return json.loads(_GUIDE_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _file_keys() -> tuple[str, ...]:
    files = _guide().get("files", {})
    return tuple(k for k in files if k.startswith("절_"))


def _file_for(nid: str) -> str | None:
    key = _OVERRIDES.get(nid, nid)
    keys = _file_keys()
    for fn in keys:                       # 정확 매칭: 절_{key}_
        if fn.startswith(f"절_{key}_"):
            return fn
    chap = key.split("-")[0]              # 장 단위 폴백: 절_{chapter}_
    for fn in keys:
        if fn.startswith(f"절_{chap}_"):
            return fn
    return None


def file_for(nid: str) -> str | None:
    """절 nid 에 대응하는 지침 원본 md 파일명(없으면 None). regulations 와 공용."""
    return _file_for(nid)


def skill_for(nid: str) -> str:
    """절 nid 의 rnd-write-* 스킬명(지침에 비어 있으면 토큰 매핑으로 보정)."""
    fn = _file_for(nid)
    node = _guide().get("files", {}).get(fn, {}) if fn else {}
    return node.get("skill", "") or _SKILL_BY_TOKEN.get(_token_of(fn), "")


@lru_cache(maxsize=1)
def _prompt_styles() -> dict:
    """절별 문체 스타일(_프롬프트 도출) 맵. {nid: style_text}."""
    try:
        data = json.loads(_PROMPT_STYLES_JSON.read_text(encoding="utf-8"))
        return data.get("styles", {}) or {}
    except Exception:
        return {}


def _section_style(nid: str) -> str:
    """절 nid 의 문체 스타일(없으면 빈 문자열). _OVERRIDES 보정 포함."""
    styles = _prompt_styles()
    if nid in styles:
        return styles[nid]
    alt = _OVERRIDES.get(nid)
    return styles.get(alt, "") if alt else ""


@lru_cache(maxsize=1)
def _common_style() -> str:
    secs = _guide().get("common_principles", {}).get("sections", [])
    lines = [
        f"- ({s['id']} {_clean(s['title'])}) {_clean(s['summary'])}"
        for s in secs if s.get("id") in _STYLE_SECTIONS
    ]
    head = "참조 3문서(D1 장문·D3 상세·D11 단문) 어투를 모방하되 내용은 새로 작성."
    return head + "\n" + "\n".join(lines)


def _style_for(nid: str) -> str:
    """절 nid 의 문체 스타일: 절별 문체(있으면) + 공통 문체 원칙 결합."""
    common = _common_style()
    sec = _section_style(nid)
    if not sec:
        return common
    return f"[이 절 문체·형식]\n{sec}\n\n[공통 문체 원칙]\n{common}"


@lru_cache(maxsize=1)
def _common_struct_prefix() -> str:
    secs = _guide().get("common_principles", {}).get("sections", [])
    lines = [
        f"- ({s['id']} {_clean(s['title'])}) {_clean(s['summary'])}"
        for s in secs if s.get("id") in _STRUCT_SECTIONS
    ]
    return "\n".join(lines)


def preset_for(nid: str) -> dict:
    """절 nid 의 프리셋. 지침을 못 찾으면 빈 프리셋(있는 정보만) 반환."""
    fn = _file_for(nid)
    files = _guide().get("files", {})
    node = files.get(fn, {}) if fn else {}

    token = _token_of(fn)
    role = _clean(node.get("role", "")) or _clean(node.get("title", ""))
    skill = node.get("skill", "") or _SKILL_BY_TOKEN.get(token, "")

    directives: list[str] = []
    for d in (node.get("directives") or []):
        if isinstance(d, dict):
            txt = _clean(d.get("text", ""))
            sec = _clean(d.get("section", ""))
            if txt:
                directives.append(f"({sec}) {txt}" if sec else txt)
        else:
            directives.append(_clean(str(d)))
    checklist = [_clean(c if isinstance(c, str) else c.get("text", ""))
                 for c in (node.get("checklist") or [])]

    # style: 절별 문체(_프롬프트 도출) + 공통 문체 원칙
    style = _style_for(nid)

    # structure: 역할 + 공통 구성원칙 + 절별 지침 + 체크리스트
    parts: list[str] = []
    if role:
        parts.append(f"[역할] {role}")
    common_pre = _common_struct_prefix()
    if common_pre:
        parts.append("[공통 구성원칙]\n" + common_pre)
    if directives:
        parts.append("[이 절 골격·지침]\n" + "\n".join(f"- {d}" for d in directives[:12]))
    if checklist:
        parts.append("[체크리스트]\n" + "\n".join(f"- {c}" for c in checklist[:10]))
    structure = "\n\n".join(parts)

    return {
        "skill": skill,
        "source": fn or "",
        "role": role,
        "style": style,
        "structure": structure,
        "checklist": checklist,
    }


if __name__ == "__main__":  # 스모크: 몇 개 절 프리셋 출력
    import sys
    for nid in (sys.argv[1:] or ["1-1", "2-1", "3-3", "5-5", "8-1"]):
        p = preset_for(nid)
        print(f"\n===== {nid}  (skill={p['skill']}, src={p['source']}) =====")
        print("[style]\n" + p["style"][:400])
        print("[structure]\n" + p["structure"][:500])
