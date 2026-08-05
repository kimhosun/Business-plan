#!/usr/bin/env python3
"""Claude 연동 서비스 (backend/claude_service.py).

두 개의 순수 함수를 노출한다(ARCHITECTURE.md 참조):

- generate_template(description, default_template, sample_texts) -> dict
    설명(description)을 반영한 hwpx-yaml-template/1.0 템플릿 dict를 만든다.
    기본 템플릿(default_template)을 시드로 사용한다.

- convert_input(input_text, template, prompts, targets) -> list[dict]
    사용자 입력을 요청한 문체/구성으로 다시 쓰고 len(targets)개 세그먼트로
    나눠 각 target 경로(path)에 매핑한다. 반환은
    [{"path", "marker", "text"}] 리스트이며 template의 레벨1 마커/번호를 적용한다.

동작 규칙
---------
- 환경변수 ANTHROPIC_API_KEY 가 있으면 anthropic SDK로 Claude를 호출한다.
  모델은 ANTHROPIC_MODEL(기본 "claude-sonnet-5").
- 키가 없거나 어떤 오류든 발생하면 **결정론적 스텁**으로 폴백한다.
- FastAPI에 의존하지 않는 순수 모듈이다.

스텁 동작
---------
- generate_template -> default_template(있으면) 아니면 최소 번호식 템플릿.
- convert_input -> 입력을 비어있지 않은 문단/줄로 분할, targets 순서대로 i번째
  세그먼트(부족하면 "")를 text로 배정하고 template.py의 apply_to_nodes로 마커
  재계산. targets 길이를 넘겨 쓰지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# ── 스킬 CLI(template.py)의 apply_to_nodes 재사용 ────────────────────────────
# claude_service.py: webapp/backend/  → 저장소 루트는 parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / ".claude" / "skills" / "hwpx-yaml-roundtrip" / "scripts"

try:  # config.py가 SKILL_SCRIPTS 상수를 제공하면 우선 사용
    from . import config as _config  # type: ignore

    _sd = getattr(_config, "SKILL_SCRIPTS", None)
    if _sd:
        _SCRIPTS_DIR = Path(_sd)
except Exception:  # noqa: BLE001 - config는 선택적
    pass

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

try:
    from template import apply_to_nodes as _apply_to_nodes  # type: ignore
except Exception:  # noqa: BLE001 - 임포트 실패 시 로컬 최소구현으로 폴백
    _apply_to_nodes = None


# ── 기본 상수 ────────────────────────────────────────────────────────────────
_TEMPLATE_SCHEMA = "hwpx-yaml-template/1.0"
_DEFAULT_MODEL = "claude-sonnet-5"


def _minimal_template() -> dict:
    """비어있는 시드를 위한 최소 번호식 템플릿."""
    return {
        "schema": _TEMPLATE_SCHEMA,
        "numbering": {"level1": "{n}.", "level2": "{p}.{n}", "level3": "{p}.{n}"},
        "strip_existing": True,
        "table": {
            "header_rows": 1,
            "header_marker": "",
            "cell_bullet": "",
            "apply_to_cells": False,
        },
    }


# ── 마커 적용(스텁·실호출 공용) ──────────────────────────────────────────────
def _local_apply_to_nodes(nodes: list[dict], tpl: dict) -> None:
    """template.py를 임포트하지 못했을 때의 최소 대체 구현(레벨1만).

    numbering이 있으면 level1 포맷으로 순번, 없고 markers가 있으면 level1 마커,
    둘 다 없으면 마커를 건드리지 않는다. para/cell_para만 대상.
    """
    tpl = tpl or {}
    numbering = (tpl.get("numbering") or {}).get("level1")
    marker = (tpl.get("markers") or {}).get("level1")
    strip = tpl.get("strip_existing", True)
    counter = 0
    for node in nodes:
        if node.get("kind") == "table":
            continue
        if numbering:
            counter += 1
            new = str(numbering).format(n=counter, p=str(counter), P=str(counter))
        elif marker:
            new = str(marker)
        else:
            continue
        if strip or not node.get("marker"):
            node["marker"] = new


def _apply_markers(
    segments: list[str], targets: list[str], template: dict | None
) -> list[dict]:
    """세그먼트를 targets에 매핑하고 template의 레벨1 마커/번호를 계산한다.

    target당 노드 1개(kind=para, level=1)를 만들어 apply_to_nodes에 통과시킨다.
    세그먼트가 부족하면 ""로 채운다. targets 길이를 넘겨 쓰지 않는다.
    """
    nodes: list[dict] = []
    for i, path in enumerate(targets):
        text = segments[i] if i < len(segments) else ""
        nodes.append(
            {"path": path, "kind": "para", "level": 1, "marker": "", "text": text}
        )

    apply = _apply_to_nodes or _local_apply_to_nodes
    try:
        apply(nodes, template or {})
    except Exception:  # noqa: BLE001 - 마커 계산 실패해도 text는 보존
        pass

    return [
        {
            "path": n["path"],
            "marker": n.get("marker", "") or "",
            "text": n.get("text", "") or "",
        }
        for n in nodes
    ]


def _split_segments(input_text: str) -> list[str]:
    """입력을 비어있지 않은 문단/줄로 분할한다.

    빈 줄 기준 문단 분할을 우선하고, 문단이 1개뿐이면 줄 단위로 폴백한다.
    """
    text = input_text or ""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) <= 1:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if len(lines) > len(paras):
            return lines
    return paras


# ── 스텁 구현 ────────────────────────────────────────────────────────────────
def _stub_generate_template(
    description: str, default_template: dict | None, sample_texts: list[str]
) -> dict:
    if isinstance(default_template, dict) and default_template:
        return dict(default_template)
    return _minimal_template()


def _stub_convert_input(
    input_text: str, template: dict | None, prompts: dict | None, targets: list[str]
) -> list[dict]:
    segments = _split_segments(input_text)
    return _apply_markers(segments, list(targets or []), template)


# ── Claude 실호출 헬퍼 ───────────────────────────────────────────────────────
def _extract_fenced(text: str, langs: tuple[str, ...]) -> str:
    """```yaml / ```json 등 코드펜스를 벗겨 내용만 반환. 없으면 원문 반환."""
    if not text:
        return ""
    m = re.search(r"```(?:" + "|".join(langs) + r")?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


def _client_and_model():
    """anthropic 클라이언트와 모델명을 반환. 실패 시 (None, model)."""
    model = os.environ.get("ANTHROPIC_MODEL", _DEFAULT_MODEL)
    try:
        from anthropic import Anthropic  # type: ignore

        return Anthropic(), model
    except Exception:  # noqa: BLE001
        return None, model


def _message_text(client, model: str, system: str, user: str, max_tokens: int) -> str:
    """Claude 메시지 호출 후 text 블록을 이어붙여 반환."""
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "".join(parts)


_TEMPLATE_SYSTEM = (
    "당신은 hwpx-yaml-roundtrip 파이프라인의 번호/마커 템플릿을 만드는 도우미다. "
    "schema 'hwpx-yaml-template/1.0' 을 정확히 따르는 YAML 하나만 출력한다.\n"
    "키: schema, numbering{level1,level2,level3}(번호식, 우선), "
    "markers{level1,level2,level3}(고정 기호, numbering 없을 때), strip_existing(bool), "
    "table{header_rows,header_marker,cell_bullet,apply_to_cells}. "
    "numbering 토큰: {n}=현재레벨, {p}=상위누적, {P}=조상전체. "
    "설명과 무관한 텍스트나 코드펜스 밖 주석 없이 YAML 본문만 낸다."
)


def _claude_generate_template(
    client, model: str, description: str, default_template: dict, sample_texts: list[str]
) -> dict:
    seed = yaml.safe_dump(
        default_template or _minimal_template(),
        allow_unicode=True,
        sort_keys=False,
    )
    samples = "\n".join(f"- {s}" for s in (sample_texts or [])[:8])
    user = (
        f"[설명]\n{description or '(없음)'}\n\n"
        f"[시드 템플릿]\n```yaml\n{seed}```\n\n"
        f"[예시 본문(마커/구성 참고)]\n{samples or '(없음)'}\n\n"
        "위 설명을 반영해 hwpx-yaml-template/1.0 템플릿 YAML을 출력하라."
    )
    raw = _message_text(client, model, _TEMPLATE_SYSTEM, user, max_tokens=2000)
    parsed = yaml.safe_load(_extract_fenced(raw, ("yaml", "yml")))
    if not isinstance(parsed, dict):
        raise ValueError("템플릿 파싱 실패: dict 아님")
    schema = str(parsed.get("schema", ""))
    if not schema.startswith("hwpx-yaml-template"):
        parsed["schema"] = _TEMPLATE_SCHEMA
    return parsed


_CONVERT_SYSTEM = (
    "당신은 정부 R&D 연구개발계획서 절을 지정된 문체·구성으로 다시 쓰는 편집자다. "
    "사용자 입력을 요청한 스타일/구조로 재작성하고 정확히 N개의 세그먼트로 나눈다. "
    "출력은 길이 N의 JSON 문자열 배열 하나뿐이다(마커/번호는 넣지 말 것 — "
    "번호는 후처리로 붙는다). 코드펜스 밖 설명 금지."
)


def _claude_convert_input(
    client,
    model: str,
    input_text: str,
    template: dict,
    prompts: dict,
    targets: list[str],
) -> list[dict]:
    n = len(targets)
    prompts = prompts or {}
    style = prompts.get("style", "")
    structure = prompts.get("structure", "")
    guides = prompts.get("guidelines", []) or []
    guide_txt = "\n".join(f"- {g}" for g in guides[:12])
    user = (
        f"[문체(style)]\n{style or '(지정 없음)'}\n\n"
        f"[구성(structure)]\n{structure or '(지정 없음)'}\n\n"
        f"[작성요령]\n{guide_txt or '(없음)'}\n\n"
        f"[사용자 입력]\n{input_text or '(비어있음)'}\n\n"
        f"위 입력을 지정 문체/구성으로 재작성하고 정확히 {n}개의 세그먼트로 나눠 "
        f"길이 {n}의 JSON 문자열 배열로만 출력하라."
    )
    raw = _message_text(client, model, _CONVERT_SYSTEM, user, max_tokens=8000)
    parsed = json.loads(_extract_fenced(raw, ("json",)))
    if not isinstance(parsed, list):
        raise ValueError("변환 파싱 실패: list 아님")
    segments = ["" if s is None else str(s) for s in parsed]
    # apply_markers가 targets 길이에 맞춰 자르거나 ''로 채운다.
    return _apply_markers(segments, list(targets), template)


# ── 공개 API ─────────────────────────────────────────────────────────────────
def generate_template(
    description: str,
    default_template: dict | None,
    sample_texts: list[str] | None,
) -> dict:
    """설명을 반영한 hwpx-yaml-template/1.0 템플릿 dict를 반환한다.

    ANTHROPIC_API_KEY가 있으면 Claude로 생성하고, 없거나 오류면 스텁으로 폴백한다.
    """
    default_template = default_template if isinstance(default_template, dict) else {}
    sample_texts = list(sample_texts or [])

    if os.environ.get("ANTHROPIC_API_KEY"):
        client, model = _client_and_model()
        if client is not None:
            try:
                return _claude_generate_template(
                    client, model, description, default_template, sample_texts
                )
            except Exception:  # noqa: BLE001 - 어떤 오류든 스텁 폴백
                pass
    return _stub_generate_template(description, default_template, sample_texts)


def convert_input(
    input_text: str,
    template: dict | None,
    prompts: dict | None,
    targets: list[str] | None,
) -> list[dict]:
    """사용자 입력을 재작성·분할해 targets에 매핑한 [{path,marker,text}] 반환.

    ANTHROPIC_API_KEY가 있으면 Claude로 변환하고, 없거나 오류면 스텁으로 폴백한다.
    반환 길이는 항상 len(targets)와 같다.
    """
    template = template if isinstance(template, dict) else {}
    prompts = prompts if isinstance(prompts, dict) else {}
    targets = list(targets or [])
    if not targets:
        return []

    if os.environ.get("ANTHROPIC_API_KEY"):
        client, model = _client_and_model()
        if client is not None:
            try:
                return _claude_convert_input(
                    client, model, input_text, template, prompts, targets
                )
            except Exception:  # noqa: BLE001 - 어떤 오류든 스텁 폴백
                pass
    return _stub_convert_input(input_text, template, prompts, targets)


# ── 자체 테스트(__main__): 항상 스텁 모드로 실행 ─────────────────────────────
def _selftest() -> int:
    # 실호출 경로를 타지 않도록 키를 잠시 제거
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        # 1) generate_template — 빈 시드 → 최소 템플릿
        tpl_empty = generate_template("개조식 번호식 템플릿", {}, ["□ 개요", "○ 세부"])
        # 2) generate_template — 마커식 시드는 그대로 반환
        marker_seed = {
            "schema": _TEMPLATE_SCHEMA,
            "markers": {"level1": "□", "level2": "○", "level3": "-"},
            "strip_existing": True,
        }
        tpl_seed = generate_template("", marker_seed, [])

        # 3) convert_input — 번호식 템플릿, 3개 target
        targets = ["s0/p1", "s0/p2", "s0/p3"]
        num_tpl = _minimal_template()
        input_text = "첫째 문단 내용\n\n둘째 문단 내용\n\n셋째 문단 내용"
        result = convert_input(input_text, num_tpl, {"style": "개조식"}, targets)

        # 4) convert_input — 세그먼트가 target보다 적을 때 ''로 채우는지
        short = convert_input("한 줄뿐", marker_seed, {}, ["a", "b"])

        print("== generate_template (빈 시드 → 최소 템플릿) ==")
        print(json.dumps(tpl_empty, ensure_ascii=False, indent=2))
        print("\n== generate_template (마커식 시드 반환) ==")
        print(json.dumps(tpl_seed, ensure_ascii=False, indent=2))
        print("\n== convert_input (번호식, 3 targets) ==")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("\n== convert_input (세그먼트 부족 → '' 채움, 마커식) ==")
        print(json.dumps(short, ensure_ascii=False, indent=2))

        ok = True
        ok &= tpl_empty.get("schema") == _TEMPLATE_SCHEMA
        ok &= tpl_seed.get("markers", {}).get("level1") == "□"
        ok &= len(result) == len(targets)
        ok &= [r["path"] for r in result] == targets
        ok &= [r["marker"] for r in result] == ["1.", "2.", "3."]
        ok &= [r["text"] for r in result] == [
            "첫째 문단 내용",
            "둘째 문단 내용",
            "셋째 문단 내용",
        ]
        ok &= len(short) == 2
        ok &= short[0]["text"] == "한 줄뿐" and short[1]["text"] == ""
        ok &= short[0]["marker"] == "□" and short[1]["marker"] == "□"

        print("\nSELF-TEST:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved


if __name__ == "__main__":
    sys.exit(_selftest())
