#!/usr/bin/env python3
"""Claude 연동 서비스 (backend/claude_service.py).

두 개의 순수 함수를 노출한다(ARCHITECTURE.md 참조):

- generate_template(description, default_template, sample_texts) -> dict
    설명(description)을 반영한 hwpx-yaml-template/1.0 템플릿 dict를 만든다.
    기본 템플릿(default_template)을 시드로 사용한다.

- chat_write(context, history, message) -> dict
    절의 양식(template)·지침(guidelines)·문체/구성(prompts)·현재 작성본(input)을
    맥락으로 삼아 사용자의 채팅 지시에 답하고, 본문 초안(draft)을 다시 쓴다.
    반환은 {"reply": str, "draft": str|None}.

- convert_input(input_text, template, prompts, targets) -> list[dict]
    사용자 입력을 요청한 문체/구성으로 다시 쓰고 len(targets)개 세그먼트로
    나눠 각 target 경로(path)에 매핑한다. 반환은
    [{"path", "marker", "text"}] 리스트이며 template의 레벨1 마커/번호를 적용한다.

동작 규칙
---------
호출 경로는 3단계로 폴백한다.

1. **anthropic SDK** — 환경변수 ANTHROPIC_API_KEY 가 있을 때.
2. **claude 실행파일(Claude Code CLI)** — API 키가 없어도 이미 로그인된
   자격증명(~/.claude/.credentials.json)으로 동작한다. `claude -p --output-format json`
   헤드리스 모드를 subprocess 로 부른다. 경로 탐색 순서는 `_find_cli()` 참조.
3. **결정론적 스텁** — 위 둘 다 안 되거나 어떤 오류든 났을 때.

모델은 ANTHROPIC_MODEL(기본 "claude-opus-5"), CLI 경로는 CLAUDE_CLI_PATH,
CLI 타임아웃은 CLAUDE_CLI_TIMEOUT(초, 기본 300)로 덮어쓸 수 있다.
FastAPI에 의존하지 않는 순수 모듈이다.

스텁 동작
---------
- generate_template -> default_template(있으면) 아니면 최소 번호식 템플릿.
- convert_input -> 입력을 비어있지 않은 문단/줄로 분할, targets 순서대로 i번째
  세그먼트(부족하면 "")를 text로 배정하고 template.py의 apply_to_nodes로 마커
  재계산. targets 길이를 넘겨 쓰지 않는다.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
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
_DEFAULT_MODEL = "claude-opus-5"


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


# ── claude 실행파일(Claude Code CLI) 경로 ────────────────────────────────────
# API 키 없이도 이미 로그인된 자격증명으로 호출된다. VS Code 확장에 동봉된
# native-binary 를 포함해 흔한 설치 위치를 순서대로 찾는다.
_CLI_GLOBS = (
    "~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe",
    "~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude",
    "~/.vscode-insiders/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe",
    "~/.local/bin/claude.exe",
    "~/.local/bin/claude",
    "~/AppData/Roaming/npm/claude.cmd",
)

# 문서 작성만 시키므로 파일/셸 도구는 모두 막는다(시스템 프롬프트도 교체).
_CLI_DISALLOWED_TOOLS = (
    "Bash Edit Write Read Glob Grep WebFetch WebSearch Task NotebookEdit "
    "TodoWrite Agent Artifact"
)


@lru_cache(maxsize=1)
def _find_cli() -> str | None:
    """claude 실행파일 경로. 못 찾거나 CLAUDE_DISABLE_CLI 가 켜져 있으면 None."""
    if os.environ.get("CLAUDE_DISABLE_CLI"):
        return None
    override = os.environ.get("CLAUDE_CLI_PATH")
    if override and Path(override).exists():
        return override
    found = shutil.which("claude")
    if found:
        return found
    for pattern in _CLI_GLOBS:
        # 확장 버전이 여러 개면 최신(사전순 마지막)을 쓴다.
        matches = sorted(glob.glob(os.path.expanduser(pattern)))
        if matches:
            return matches[-1]
    return None


def _cli_text(
    system: str, prompt: str, *, schema: dict | None = None, model: str | None = None
) -> str:
    """claude -p 헤드리스 호출. 최종 응답 텍스트(result)를 반환한다.

    시스템 프롬프트를 --system-prompt 로 **교체**하고 도구를 막아, 대화형
    Claude Code 가 아니라 단순 텍스트 생성기로 쓴다.
    """
    cli = _find_cli()
    if not cli:
        raise RuntimeError("claude 실행파일을 찾지 못했습니다.")

    argv = [
        cli, "-p",
        "--system-prompt", system,
        "--model", model or os.environ.get("ANTHROPIC_MODEL", _DEFAULT_MODEL),
        "--output-format", "json",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--disallowed-tools", _CLI_DISALLOWED_TOOLS,
    ]
    if schema:
        argv += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    # 응답이 너무 오래 걸리면 CLAUDE_EFFORT=medium/low 로 낮춰 쓴다(품질↔지연 트레이드오프).
    effort = os.environ.get("CLAUDE_EFFORT")
    if effort:
        argv += ["--effort", effort]

    try:
        timeout = float(os.environ.get("CLAUDE_CLI_TIMEOUT", "300"))
    except ValueError:
        timeout = 300.0

    proc = subprocess.run(
        argv,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        # 저장소 밖에서 돌려 CLAUDE.md/훅 자동 탐색을 타지 않게 한다.
        cwd=tempfile.gettempdir(),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude CLI 종료코드 {proc.returncode}: {(proc.stderr or '').strip()[:300]}"
        )
    data = json.loads(proc.stdout)
    if data.get("is_error") or data.get("subtype") not in (None, "success"):
        raise RuntimeError(f"claude CLI 오류: {str(data.get('result'))[:300]}")
    return str(data.get("result") or "")


def _flatten_history(messages: list[dict]) -> str:
    """CLI 는 단일 프롬프트만 받으므로 대화 이력을 하나의 텍스트로 편다."""
    if len(messages) == 1:
        return messages[0].get("content", "")
    lines = []
    for m in messages[:-1]:
        who = "사용자" if m.get("role") == "user" else "당신(이전 답변)"
        lines.append(f"[{who}]\n{m.get('content', '')}")
    lines.append(f"[사용자 — 이번 요청]\n{messages[-1].get('content', '')}")
    return "\n\n".join(lines)


def _ask(
    system: str,
    messages: list[dict],
    *,
    max_tokens: int,
    schema: dict | None = None,
) -> str:
    """API 키가 있으면 SDK, 없으면 claude 실행파일로 물어 텍스트를 받는다.

    둘 다 불가하거나 실패하면 예외를 올린다(호출부가 스텁으로 폴백).
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        client, model = _client_and_model()
        if client is not None:
            return _messages_text(client, model, system, messages, max_tokens)
    return _cli_text(system, _flatten_history(messages), schema=schema)


def _client_and_model():
    """anthropic 클라이언트와 모델명을 반환. 실패 시 (None, model)."""
    model = os.environ.get("ANTHROPIC_MODEL", _DEFAULT_MODEL)
    try:
        from anthropic import Anthropic  # type: ignore

        return Anthropic(), model
    except Exception:  # noqa: BLE001
        return None, model


def _messages_text(
    client, model: str, system: str, messages: list[dict], max_tokens: int
) -> str:
    """대화 이력(messages)을 그대로 넘겨 호출하고 text 블록을 이어붙여 반환."""
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
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
    description: str, default_template: dict, sample_texts: list[str]
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
    raw = _ask(_TEMPLATE_SYSTEM, [{"role": "user", "content": user}], max_tokens=2000)
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
    raw = _ask(
        _CONVERT_SYSTEM, [{"role": "user", "content": user}], max_tokens=8000,
        schema={"type": "array", "items": {"type": "string"}},
    )
    parsed = json.loads(_extract_fenced(raw, ("json",)))
    if not isinstance(parsed, list):
        raise ValueError("변환 파싱 실패: list 아님")
    segments = ["" if s is None else str(s) for s in parsed]
    # apply_markers가 targets 길이에 맞춰 자르거나 ''로 채운다.
    return _apply_markers(segments, list(targets), template)


# ── 채팅(입력 패널 하단) ─────────────────────────────────────────────────────
_CHAT_SYSTEM = (
    "당신은 정부 R&D 연구개발계획서의 한 절(節)을 사용자와 대화하며 작성하는 집필자다. "
    "사용자는 채팅으로 재료·지시를 주고, 당신은 그 절의 본문 초안을 통째로 다시 써 준다.\n"
    "규칙\n"
    "1) 아래 [양식 템플릿]의 번호/마커 규칙과 [작성요령]·[문체]·[구성]을 반드시 따른다.\n"
    "2) [현재 작성본]이 있으면 처음부터 새로 쓰지 말고 지시한 부분만 고쳐 전체를 다시 낸다.\n"
    "3) 개조식·정량 표기를 기본으로 하며 근거 없는 수치를 지어내지 않는다. "
    "값이 필요하면 draft 안에 [○○ 확인 필요] 같은 자리표시로 남기고 reply 에서 물어본다.\n"
    "4) 출력은 ```json 코드펜스 안의 JSON 객체 하나뿐이다. 키는 두 개:\n"
    '   {"reply": "사용자에게 할 짧은 한국어 답변", '
    '"draft": "절 본문 전체(줄바꿈 포함). 본문을 고칠 필요가 없으면 null"}\n'
    "5) draft 에는 절 제목이나 설명을 넣지 않는다. 본문 문단만 넣는다."
)

# 채팅 이력이 길어져도 컨텍스트를 넘기지 않도록 최근 N개만 모델에 넘긴다.
_CHAT_HISTORY_LIMIT = 20


def _chat_context_block(context: dict) -> str:
    """절 맥락(제목·작성요령·양식·문체·구성·현재 작성본)을 시스템 프롬프트 꼬리로."""
    context = context or {}
    prompts = context.get("prompts") or {}
    guides = [g for g in (context.get("guidelines") or []) if g][:12]
    template = context.get("template") or {}
    try:
        tpl_yaml = yaml.safe_dump(template, allow_unicode=True, sort_keys=False)
    except Exception:  # noqa: BLE001
        tpl_yaml = ""
    label = (context.get("label") or "").strip()
    title = (context.get("title") or "").strip()
    current = (context.get("input") or "").strip()

    return (
        f"\n\n[대상 절]\n{label} {title}".rstrip()
        + f"\n\n[작성요령]\n{chr(10).join('- ' + g for g in guides) or '(없음)'}"
        + f"\n\n[양식 템플릿]\n```yaml\n{tpl_yaml}```"
        + f"\n\n[문체]\n{prompts.get('style') or '(지정 없음)'}"
        + f"\n\n[구성]\n{prompts.get('structure') or '(지정 없음)'}"
        + f"\n\n[현재 작성본]\n{current or '(비어 있음)'}"
    )


def _stub_chat_write(
    context: dict, history: list[dict], message: str, reason: str = ""
) -> dict:
    """키가 없을 때의 결정론적 대체 — 지시문을 본문 문단으로 정리해 이어붙인다.

    template 의 레벨1 마커/번호를 적용해 실제 변환 결과와 모양을 맞춘다.
    """
    text = (message or "").strip()
    if not text:
        return {"reply": "작성할 내용을 입력해 주세요.", "draft": None}

    segments = _split_segments(text)
    nodes = _apply_markers(segments, [f"stub/{i}" for i in range(len(segments))],
                           (context or {}).get("template") or {})
    lines = [f"{n['marker']} {n['text']}".strip() for n in nodes if n["text"]]
    current = ((context or {}).get("input") or "").strip()
    draft = (current + "\n" + "\n".join(lines)).strip() if current else "\n".join(lines)
    why = f" (사유: {reason})" if reason else ""
    return {
        "reply": "(스텁 모드) Claude 호출이 되지 않아 입력을 양식 마커에만 맞춰 "
                 f"본문에 반영했습니다.{why}",
        "draft": draft,
    }


_CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "사용자에게 할 짧은 한국어 답변"},
        "draft": {"type": ["string", "null"], "description": "절 본문 전체(고칠 필요 없으면 null)"},
    },
    "required": ["reply", "draft"],
    "additionalProperties": False,
}


def _claude_chat_write(context: dict, history: list[dict], message: str) -> dict:
    msgs: list[dict] = []
    for turn in (history or [])[-_CHAT_HISTORY_LIMIT:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": message})
    # Claude 는 user 로 시작하는 대화만 받는다.
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)

    raw = _ask(
        _CHAT_SYSTEM + _chat_context_block(context), msgs,
        max_tokens=16000, schema=_CHAT_SCHEMA,
    )
    try:
        parsed = json.loads(_extract_fenced(raw, ("json",)))
    except Exception:  # noqa: BLE001 - JSON 이 아니면 전체를 답변으로 취급
        return {"reply": raw.strip(), "draft": None}
    if not isinstance(parsed, dict):
        return {"reply": raw.strip(), "draft": None}
    draft = parsed.get("draft")
    return {
        "reply": str(parsed.get("reply") or "").strip(),
        "draft": None if draft is None else str(draft),
    }


# ── 공개 API ─────────────────────────────────────────────────────────────────
def generate_template(
    description: str,
    default_template: dict | None,
    sample_texts: list[str] | None,
) -> dict:
    """설명을 반영한 hwpx-yaml-template/1.0 템플릿 dict를 반환한다.

    API 키 → claude 실행파일 → 스텁 순으로 폴백한다.
    """
    default_template = default_template if isinstance(default_template, dict) else {}
    sample_texts = list(sample_texts or [])

    try:
        return _claude_generate_template(description, default_template, sample_texts)
    except Exception:  # noqa: BLE001 - 어떤 오류든 스텁 폴백
        return _stub_generate_template(description, default_template, sample_texts)


def convert_input(
    input_text: str,
    template: dict | None,
    prompts: dict | None,
    targets: list[str] | None,
) -> list[dict]:
    """사용자 입력을 재작성·분할해 targets에 매핑한 [{path,marker,text}] 반환.

    API 키 → claude 실행파일 → 스텁 순으로 폴백한다.
    반환 길이는 항상 len(targets)와 같다.
    """
    template = template if isinstance(template, dict) else {}
    prompts = prompts if isinstance(prompts, dict) else {}
    targets = list(targets or [])
    if not targets:
        return []

    try:
        return _claude_convert_input(input_text, template, prompts, targets)
    except Exception:  # noqa: BLE001 - 어떤 오류든 스텁 폴백
        return _stub_convert_input(input_text, template, prompts, targets)


def chat_write(
    context: dict | None,
    history: list[dict] | None,
    message: str,
) -> dict:
    """채팅 지시를 받아 {"reply", "draft"} 를 반환한다.

    context = {label,title,guidelines,template,prompts,input}
    history = [{"role": "user"|"assistant", "content": str}, ...]
    API 키 → claude 실행파일 → 스텁 순으로 폴백한다.
    """
    context = context if isinstance(context, dict) else {}
    history = list(history or [])
    message = (message or "").strip()
    if not message:
        return {"reply": "작성할 내용을 입력해 주세요.", "draft": None}

    try:
        return _claude_chat_write(context, history, message)
    except Exception as exc:  # noqa: BLE001 - 어떤 오류든 스텁 폴백(사유는 답변에 남긴다)
        return _stub_chat_write(context, history, message, reason=str(exc)[:200])


# ── 자체 테스트(__main__): 항상 스텁 모드로 실행 ─────────────────────────────
def _selftest() -> int:
    # 실호출 경로(API 키·claude 실행파일)를 타지 않도록 둘 다 차단
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ["CLAUDE_DISABLE_CLI"] = "1"
    _find_cli.cache_clear()
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

        # 5) chat_write — 스텁이 현재 작성본 뒤에 마커를 붙여 이어쓰는지
        chat = chat_write(
            {"template": marker_seed, "input": "□ 기존 문단"},
            [{"role": "user", "content": "이전 지시"}],
            "새 문단 하나\n\n새 문단 둘",
        )

        print("== generate_template (빈 시드 → 최소 템플릿) ==")
        print(json.dumps(tpl_empty, ensure_ascii=False, indent=2))
        print("\n== generate_template (마커식 시드 반환) ==")
        print(json.dumps(tpl_seed, ensure_ascii=False, indent=2))
        print("\n== convert_input (번호식, 3 targets) ==")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("\n== convert_input (세그먼트 부족 → '' 채움, 마커식) ==")
        print(json.dumps(short, ensure_ascii=False, indent=2))
        print("\n== chat_write (스텁: 현재 작성본에 이어쓰기) ==")
        print(json.dumps(chat, ensure_ascii=False, indent=2))

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
        ok &= (chat["draft"] or "").startswith("□ 기존 문단")
        ok &= "□ 새 문단 둘" in (chat["draft"] or "")

        print("\nSELF-TEST:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        os.environ.pop("CLAUDE_DISABLE_CLI", None)
        _find_cli.cache_clear()
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved


if __name__ == "__main__":
    sys.exit(_selftest())
