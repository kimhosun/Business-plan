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


# 본문이 이미 선두 마커(□ ○ ㅇ - · < 1. (1) ① 등)를 달고 있는지 판정.
# LLM/입력이 마커를 본문에 포함했는데 template 마커까지 덧대면 "□ ㅇ ..." 같은
# 이중 마커가 생기므로, 이런 경우 template 적용을 건너뛴다(=본문 마커를 신뢰).
_LEADING_MARK_ALTS = [
    r"\d+(?:\.\d+)+\.?", r"\d+\.", r"\d+\)", r"\(\d+\)",
    r"[가-힣]\.", r"[가-힣]\)",
    r"[①-⑳ⓐ-ⓩ❶-❿]",
    r"[ㅇㆍ]",                         # 한글 자모 불릿
    r"[□■○●◇◆◈△▲▽▼∙·•◦∘⁃]",         # 기호 불릿
    r"[oO]",                          # 라틴 o 불릿
    r"[-–—]", r"[*※]",
]
_LEADING_MARK_RE = re.compile(r"^\s*(?:" + "|".join(_LEADING_MARK_ALTS) + r")\s+")


def _has_leading_marker(text: str) -> bool:
    return bool(text) and bool(_LEADING_MARK_RE.match(text))


def _apply_markers(
    segments: list[str], targets: list[str], template: dict | None
) -> list[dict]:
    """세그먼트를 targets에 매핑한다. 본문에 마커가 없을 때만 template 마커를 붙인다.

    target당 노드 1개(kind=para, level=1)를 만든다. 세그먼트가 부족하면 ""로 채운다.
    본문(세그먼트) 중 하나라도 이미 선두 마커를 달고 있으면(개조식 □/○/- 등),
    template 을 적용하지 않고 본문 마커를 그대로 살린다 — 그렇지 않으면 "□ ㅇ …"
    같은 이중 마커가 생긴다. 마커가 전혀 없는 순수 본문일 때만 template 이 마커를 부여한다.
    """
    texts = [segments[i] if i < len(segments) else "" for i in range(len(targets))]
    nodes: list[dict] = [
        {"path": path, "kind": "para", "level": 1, "marker": "", "text": text}
        for path, text in zip(targets, texts)
    ]

    # 본문에 선두 마커가 이미 있으면 template 마커를 덧대지 않는다(이중 마커 방지).
    if not any(_has_leading_marker(t) for t in texts):
        apply = _apply_to_nodes or _local_apply_to_nodes
        try:
            apply(nodes, template or {})
        except Exception:  # noqa: BLE001 - 마커 계산 실패해도 text는 보존
            pass

    # 그림/차트 세그먼트(```chart… · ![](…))에는 마커를 붙이지 않는다 —
    # "□ ```chart" 처럼 되면 그림 변환(apply_markdown_images)의 펜스/이미지 감지가 깨진다.
    for n in nodes:
        first = next((ln for ln in (n.get("text") or "").splitlines() if ln.strip()), "")
        if first.lstrip().startswith("```") or re.match(r"^\s*!\[.*\]\(", first):
            n["marker"] = ""

    return [
        {
            "path": n["path"],
            "marker": n.get("marker", "") or "",
            "text": n.get("text", "") or "",
        }
        for n in nodes
    ]


def _split_plain(text: str) -> list[str]:
    """빈 줄 기준 문단 분할을 우선하고, 문단이 1개뿐이면 줄 단위로 폴백한다."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) <= 1:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if len(lines) > len(paras):
            return lines
    return paras


_FENCE_OPEN_RE = re.compile(r"^\s*```")
_FENCE_CLOSE_RE = re.compile(r"^\s*```\s*$")


def _split_segments(input_text: str) -> list[str]:
    """입력을 비어있지 않은 문단/줄로 분할한다.

    ```…``` 코드펜스 블록(예: ```chart)은 한 세그먼트로 원자 보존해, 문단/줄 분할이나
    packed 매핑이 여러 문단으로 쪼개 그림 변환을 깨뜨리지 않게 한다. 펜스 밖 텍스트는
    기존 규칙(_split_plain)대로 나눈다.
    """
    text = input_text or ""
    if "```" not in text:
        return _split_plain(text)
    lines = text.split("\n")
    segs: list[str] = []
    buf: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        if _FENCE_OPEN_RE.match(lines[i]):
            j = i + 1
            while j < n and not _FENCE_CLOSE_RE.match(lines[j]):
                j += 1
            if j < n:  # 닫힌 펜스 [i..j] — 통째로 한 세그먼트
                if buf:
                    segs.extend(_split_plain("\n".join(buf))); buf = []
                block = "\n".join(lines[i:j + 1]).strip()
                if block:
                    segs.append(block)
                i = j + 1
                continue
        buf.append(lines[i]); i += 1
    if buf:
        segs.extend(_split_plain("\n".join(buf)))
    return [s for s in segs if s.strip()]


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


def _unwrap_fence(text: str) -> str:
    """출력 '전체'를 감싼 바깥 코드펜스만 벗긴다(내부 ```chart 블록은 보존).

    본문(비펜스 출력)에 ```chart 블록이 섞이므로, _extract_fenced 로 중간을 잘라내지
    않도록 첫 줄이 ```lang, 마지막 줄이 ``` 일 때만 그 두 줄을 제거한다.
    """
    s = (text or "").strip()
    if not s.startswith("```"):
        return s
    lines = s.split("\n")
    if len(lines) >= 2 and re.fullmatch(r"```[\w-]*", lines[0].strip()) \
            and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return s


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

# 파일/셸/에이전트 도구는 항상 막는다(시스템 프롬프트도 교체해 순수 생성기로 사용).
_CLI_BLOCK_ALWAYS = [
    "Bash", "Edit", "Write", "Read", "Glob", "Grep",
    "Task", "NotebookEdit", "TodoWrite", "Agent", "Artifact",
]
# 웹 조사 도구 — 기본은 막지만, allow_tools 로 명시하면 인터넷 조사에 열어 준다.
_CLI_WEB_TOOLS = ["WebSearch", "WebFetch"]

# 기본(조사 비활성) 차단 목록: 파일/셸 + 웹 전부.
_CLI_DISALLOWED_TOOLS = " ".join(_CLI_BLOCK_ALWAYS + _CLI_WEB_TOOLS)


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
    system: str,
    prompt: str,
    *,
    schema: dict | None = None,
    model: str | None = None,
    allow_tools: tuple[str, ...] | None = None,
    timeout: float | None = None,
) -> str:
    """claude -p 헤드리스 호출. 최종 응답 텍스트(result)를 반환한다.

    시스템 프롬프트를 --system-prompt 로 **교체**하고 도구를 막아, 대화형
    Claude Code 가 아니라 단순 텍스트 생성기로 쓴다.

    allow_tools 를 주면(예: WebSearch/WebFetch) 그 도구만 --allowed-tools 로 미리
    승인해 헤드리스에서도 프롬프트 없이 쓰게 하고, 차단 목록에서는 뺀다. 나머지
    파일/셸/에이전트 도구는 계속 막는다. 웹 조사는 시간이 더 걸리므로 timeout 을
    넉넉히 넘길 수 있다.
    """
    cli = _find_cli()
    if not cli:
        raise RuntimeError("claude 실행파일을 찾지 못했습니다.")

    allow = [t for t in (allow_tools or []) if t]
    # 허용 도구는 차단 목록에서 제외(파일/셸/에이전트 + 허용 안 한 웹은 계속 차단).
    disallowed = _CLI_BLOCK_ALWAYS + [t for t in _CLI_WEB_TOOLS if t not in allow]

    argv = [
        cli, "-p",
        "--system-prompt", system,
        "--model", model or os.environ.get("ANTHROPIC_MODEL", _DEFAULT_MODEL),
        "--output-format", "json",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--disallowed-tools", " ".join(disallowed),
    ]
    if allow:
        argv += ["--allowed-tools", " ".join(allow)]
    if schema:
        argv += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    # 응답이 너무 오래 걸리면 CLAUDE_EFFORT=medium/low 로 낮춰 쓴다(품질↔지연 트레이드오프).
    effort = os.environ.get("CLAUDE_EFFORT")
    if effort:
        argv += ["--effort", effort]

    if timeout is None:
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
    allow_tools: tuple[str, ...] | None = None,
    timeout: float | None = None,
) -> str:
    """API 키가 있으면 SDK, 없으면 claude 실행파일로 물어 텍스트를 받는다.

    allow_tools 에 웹 조사 도구(WebSearch/WebFetch)를 주면 CLI 는 그 도구를 열고,
    SDK 경로는 서버측 web_search 도구를 붙여 인터넷 조사를 하게 한다.
    둘 다 불가하거나 실패하면 예외를 올린다(호출부가 스텁으로 폴백).
    """
    web = bool(allow_tools)
    if os.environ.get("ANTHROPIC_API_KEY"):
        client, model = _client_and_model()
        if client is not None:
            return _messages_text(
                client, model, system, messages, max_tokens, web_search=web
            )
    return _cli_text(
        system, _flatten_history(messages),
        schema=schema, allow_tools=allow_tools, timeout=timeout,
    )


def _client_and_model():
    """anthropic 클라이언트와 모델명을 반환. 실패 시 (None, model)."""
    model = os.environ.get("ANTHROPIC_MODEL", _DEFAULT_MODEL)
    try:
        from anthropic import Anthropic  # type: ignore

        return Anthropic(), model
    except Exception:  # noqa: BLE001
        return None, model


def _messages_text(
    client, model: str, system: str, messages: list[dict], max_tokens: int,
    *, web_search: bool = False,
) -> str:
    """대화 이력(messages)을 그대로 넘겨 호출하고 text 블록을 이어붙여 반환.

    web_search=True 면 Anthropic 서버측 web_search 도구를 붙여 인터넷 조사를 시킨다
    (검색·인용은 서버에서 처리되고 최종 text 블록에 조사 반영 결과가 담긴다).
    """
    base: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }

    def _run(kwargs: dict) -> str:
        resp = client.messages.create(**kwargs)
        return "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )

    if not web_search:
        return _run(base)

    def _int_env(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, str(default)))
        except ValueError:
            return default

    # web_search 는 페이지 URL·요지만 준다. 참조 이미지의 '직접 이미지 URL'(.jpg/.png)을
    # 얻으려면 web_fetch 로 출처 페이지를 열어 <img> 주소를 뽑아야 한다.
    search = {
        "type": "web_search_20250305", "name": "web_search",
        "max_uses": _int_env("WEB_SEARCH_MAX_USES", 8),
    }
    fetch = {
        "type": "web_fetch_20250910", "name": "web_fetch",
        "max_uses": _int_env("WEB_FETCH_MAX_USES", 5),
    }
    # search+fetch → (fetch/beta 미지원) search만 → (도구 미지원) 도구 없이, 단계적 폴백.
    attempts = [
        {**base, "tools": [search, fetch],
         "extra_headers": {"anthropic-beta": "web-fetch-2025-09-10"}},
        {**base, "tools": [search]},
        base,
    ]
    last: Exception | None = None
    for kw in attempts:
        try:
            return _run(kw)
        except Exception as exc:  # noqa: BLE001 - 도구/베타 미지원 시 단계적 폴백
            last = exc
    raise last if last else RuntimeError("web 호출 실패")


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


# 확인 필요 구간 마킹 규약(변환/채팅 공용). 빌드가 이 마커 구간을 글자색 빨강으로 바꾸고
# 마커는 제거한다(HWPX_VERIFY_MARKS). 값 텍스트만 감싸고 선두 마커·문단 전체는 감싸지 않는다.
_VERIFY_MARK_RULE = (
    "사람이 검증해야 하는 값(제반사항·RFP·입력에 근거가 없는 실적 수치·기관 고유명사·"
    "특허/등록번호·인명·날짜·금액·비율 등)은 지어내지 말고 그 값 부분만 "
    "[[확인]]…[[/확인]] 로 감싼다(예: 매출 [[확인]]○○억원[[/확인]], "
    "[[확인]]△△△ 확인 필요[[/확인]]). 마커는 값 텍스트에만 붙이고 선두 개조식 마커나 "
    "문단 전체를 감싸지 않는다. 근거가 확실한 값에는 마커를 붙이지 않는다."
)

_CONVERT_SYSTEM = (
    "당신은 정부 R&D 연구개발계획서 한 절(節)을 작성하는 편집자다. "
    "아래 [제반사항]·[RFP 원문]·[사용자 입력]을 근거로, 지정된 [문체]·[구성]·[작성요령]에 맞춰 "
    "이 절 본문을 작성한다.\n"
    "규칙\n"
    "1) **[제반사항]이 있으면 최우선 확정 정보로 반영한다** — 참여기관(주관/공동)·기관형태·"
    "기관별 역할·연구기간·기관별 정부출연금·주요 연구목표 중 **이 절과 관련되는 항목을 골라** 녹이고, "
    "**RFP 와 상충하면 제반사항을 따른다**(사용자의 전략·수정). 제반사항 블록 끝의 '※ 이 절에 반영' "
    "안내가 있으면 그 항목을 우선 활용하고, 이 절과 무관한 항목은 억지로 넣지 않는다.\n"
    "2) 이어 **RFP 를 근거로 반영한다** — 이 절 주제에 해당하는 RFP 의 배경·목표·요건·범위·수치를 "
    "녹인다. 사용자 입력이 비었거나 부족하면 제반사항·RFP 근거로 이 절을 구체적으로 작성한다"
    "(빈 입력이라고 빈 결과를 내지 말 것).\n"
    "3) [문체]·[구성]·[작성요령]을 반드시 따른다(개조식·정량 표기 등).\n"
    "4) " + _VERIFY_MARK_RULE + "\n"
    "5) 정확히 N개의 세그먼트로 나눈다. 출력은 길이 N 의 JSON 문자열 배열 하나뿐이다"
    "(마커/번호는 넣지 말 것 — 번호는 후처리로 붙는다. 단 [[확인]]…[[/확인]] 는 예외로 유지). "
    "코드펜스 밖 설명 금지."
)

# 변환 시 RFP 원문 컨텍스트 예산(글자수).
try:
    _CONVERT_RFP_MAX = int(os.environ.get("CONVERT_RFP_MAX_CHARS", "30000"))
except ValueError:
    _CONVERT_RFP_MAX = 30000

# 제반사항(과제 공통 정보) 컨텍스트 예산(글자수).
try:
    _OVERVIEW_MAX = int(os.environ.get("OVERVIEW_MAX_CHARS", "8000"))
except ValueError:
    _OVERVIEW_MAX = 8000


# 제반사항 4항목 → 반영 대상 장/절 매핑(사용자 지정: 연구내용→1·2장, 참여기관→2·3·5·7·8장 …).
# (설명, 반영 대상 '장' 집합, 추가로 반영할 개별 '절' 집합)
_OVERVIEW_ASPECTS = (
    ("주요 연구목표·내용(RFP 와 다른 전략 포함)",
     {"1", "2", "4"}, {"5-1", "5-5"}),
    ("참여기관(주관/공동)·기관형태(비영리·대/중/소기업)·기관별 역할·담당 연구내용",
     {"2", "3", "5", "7", "8"}, {"1-3", "6-1", "6-2"}),
    ("연구기간(단계·연차)",
     {"3", "7", "8"}, {"2-3"}),
    ("연구기관별·연차별 정부출연금",
     {"8"}, {"5-4", "3-4"}),
)


def _chapter_of(nid: str) -> str:
    m = re.match(r"\s*(\d+)", str(nid or ""))
    return m.group(1) if m else ""


def _overview_focus(nid: str) -> str:
    """이 절(nid)에서 제반사항 중 특히 반영할 항목 안내(절별 활용 매핑)."""
    n = (nid or "").strip()
    ch = _chapter_of(n)
    picks = [label for (label, chaps, secs) in _OVERVIEW_ASPECTS
             if (ch and ch in chaps) or n in secs]
    if not picks:
        return ("※ 이 절에 반영: 제반사항 중 이 절과 직접 관련되는 항목만 (무관하면 억지로 넣지 않음).")
    body = "; ".join(f"{i + 1}) {p}" for i, p in enumerate(picks))
    return ("※ 이 절에 반영: 제반사항 중 특히 다음을 우선 활용한다 — " + body
            + ". 나머지 항목은 이 절과 무관하면 넣지 않는다.")


def overview_focus(nid: str) -> str:
    """절 상세(get_node) 응답에 실어 UI 에 표기하기 위한 공개 래퍼."""
    return _overview_focus(nid)


def _overview_block(overview_text: str, nid: str = "") -> str:
    """제반사항 텍스트를 프롬프트용 [제반사항] 블록으로. 예산 초과분은 절단.

    nid 를 주면 그 절에서 특히 반영할 항목 안내(_overview_focus)를 블록 끝에 덧붙인다.
    """
    ov = (overview_text or "").strip()
    if len(ov) > _OVERVIEW_MAX:
        ov = ov[:_OVERVIEW_MAX]
    block = (
        "[제반사항(과제 공통 정보 — 참여기관·기관형태·역할·연구기간·기관별 정부출연금·주요 "
        f"연구목표. RFP 와 상충하면 이것을 우선)]\n{ov or '(입력 없음)'}"
    )
    if ov and nid:
        block += "\n" + _overview_focus(nid)
    return block


def _claude_convert_input(
    input_text: str,
    template: dict,
    prompts: dict,
    targets: list[str],
    rfp_text: str = "",
    nid: str = "",
    overview_text: str = "",
) -> list[dict]:
    n = len(targets)
    prompts = prompts or {}
    style = prompts.get("style", "")
    structure = prompts.get("structure", "")
    guides = prompts.get("guidelines", []) or []
    guide_txt = "\n".join(f"- {g}" for g in guides[:12])
    rfp = (rfp_text or "").strip()
    if len(rfp) > _CONVERT_RFP_MAX:
        rfp = rfp[:_CONVERT_RFP_MAX]
    want_img = _wants_reference_images(nid)
    img_note = (
        "\n\n[참조 이미지] 이 절은 동향·시장 절이다. 서술한 대상(단지·기업·기술·비용 등)의 실제 "
        "이미지를 조사해, 관련 세그먼트 텍스트 끝에 줄바꿈으로 '![제목](직접 이미지 URL)' 한 줄과 "
        "다음 줄 '출처: 매체/기관(연도), URL' 을 덧붙여라(새 도표를 그리지 말고 자료의 이미지를 "
        f"가져온다). 세그먼트 개수는 정확히 {n}개로 유지한다."
        if want_img else ""
    )
    user = (
        f"{_overview_block(overview_text, nid)}\n\n"
        f"[RFP 원문]\n{rfp or '(업로드된 RFP 없음)'}\n\n"
        f"[문체(style)]\n{style or '(지정 없음)'}\n\n"
        f"[구성(structure)]\n{structure or '(지정 없음)'}\n\n"
        f"[작성요령]\n{guide_txt or '(없음)'}\n\n"
        f"[사용자 입력]\n{input_text or '(비어있음)'}\n\n"
        f"위 [제반사항]·[RFP 원문]·[사용자 입력]을 근거로(상충 시 제반사항 우선) 이 절을 지정 "
        f"문체/구성/작성요령에 맞춰 작성하고, 정확히 {n}개의 세그먼트로 나눠 길이 {n}의 "
        f"JSON 문자열 배열로만 출력하라."
        + img_note
    )
    raw = _ask(
        _CONVERT_SYSTEM + (_REF_IMAGE_GUIDE if want_img else ""),
        [{"role": "user", "content": user}],
        max_tokens=12000 if want_img else 8000,
        schema={"type": "array", "items": {"type": "string"}},
        allow_tools=_RFP_RESEARCH_TOOLS if want_img else None,
        timeout=_research_timeout() if want_img else None,
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
    "1-0) [제반사항]이 있으면 참여기관·기관형태·역할·연구기간·기관별 정부출연금·주요 연구목표 중 "
    "이 절과 관련되는 항목(블록 끝 '※ 이 절에 반영' 안내 우선)을 확정 정보로 최우선 반영하고, "
    "RFP 와 상충하면 제반사항을 따른다(무관한 항목은 넣지 않는다).\n"
    "1-1) [RFP 원문]이 있으면 이 절 주제에 해당하는 RFP 의 배경·목표·요건·범위·수치를 "
    "근거로 반영한다(사용자 지시가 없어도 제반사항·RFP 기반으로 이 절을 구체화한다).\n"
    "2) [현재 작성본]이 있으면 처음부터 새로 쓰지 말고 지시한 부분만 고쳐 전체를 다시 낸다.\n"
    "3) 개조식·정량 표기를 기본으로 하며 근거 없는 수치를 지어내지 않는다. "
    + _VERIFY_MARK_RULE + " 그리고 reply 에서 무엇을 확인해야 하는지 물어본다.\n"
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
    rfp = (context.get("rfp") or "").strip()
    if len(rfp) > _CONVERT_RFP_MAX:
        rfp = rfp[:_CONVERT_RFP_MAX]
    overview = context.get("overview") or ""
    # 스킬 보관함(backend/skills.py)에서 이 질문과 관련되어 고른 지침들.
    # 순수 모듈로 두기 위해 여기서는 이미 고른 것을 렌더만 한다.
    skills = [s for s in (context.get("skills") or []) if (s or {}).get("body")]

    return (
        f"\n\n[대상 절]\n{label} {title}".rstrip()
        + f"\n\n{_overview_block(overview, context.get('nid'))}"
        + f"\n\n[RFP 원문]\n{rfp or '(업로드된 RFP 없음)'}"
        + f"\n\n[작성요령]\n{chr(10).join('- ' + g for g in guides) or '(없음)'}"
        + f"\n\n[양식 템플릿]\n```yaml\n{tpl_yaml}```"
        + f"\n\n[문체]\n{prompts.get('style') or '(지정 없음)'}"
        + f"\n\n[구성]\n{prompts.get('structure') or '(지정 없음)'}"
        + _skills_block(skills)
        + f"\n\n[현재 작성본]\n{current or '(비어 있음)'}"
    )


def _skills_block(skills: list[dict]) -> str:
    """저장된 스킬(작성 지침) 중 이 질문에 관련된 것들을 프롬프트 블록으로."""
    if not skills:
        return ""
    out = [
        "\n\n[적용 스킬]\n"
        "아래는 사용자가 보관함에 저장해 둔 작성 지침 중 이번 요청과 관련된 것이다. "
        "[작성요령]·[양식 템플릿]과 충돌하지 않는 범위에서 그대로 따른다."
    ]
    for skill in skills:
        name = (skill.get("name") or skill.get("slug") or "스킬").strip()
        desc = (skill.get("description") or "").strip()
        out.append(f"\n\n### 스킬: {name}" + (f"\n({desc})" if desc else "")
                   + "\n" + (skill.get("body") or "").strip())
    return "".join(out)


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

    want_img = _wants_reference_images((context or {}).get("nid"))
    raw = _ask(
        _CHAT_SYSTEM + _chat_context_block(context)
        + (_REF_IMAGE_GUIDE if want_img else ""),
        msgs,
        max_tokens=16000, schema=_CHAT_SCHEMA,
        allow_tools=_RFP_RESEARCH_TOOLS if want_img else None,
        timeout=_research_timeout() if want_img else None,
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


# ── RFP 기반 절 자동작성 ─────────────────────────────────────────────────────
# RFP(공고·제안요청서) 원문을 근거로 한 절(節)의 본문 초안을 통째로 쓴다.
# chat_write 와 달리 대화 없이 1회 생성이며, 반환은 초안 텍스트(str) 하나다.
#
# 기본은 '인터넷 조사 후 정량 작성' 모드다: WebSearch/WebFetch 로 시장·기술·표준·정책
# 수치를 실제로 조사해 (출처, 연도)와 함께 반영한다. RFP_DISABLE_RESEARCH 를 설정하면
# 조사 없이(수치는 자리표시) 쓰는 예전 방식으로 되돌린다.
_RFP_RESEARCH_TOOLS = ("WebSearch", "WebFetch")


def _rfp_research_enabled() -> bool:
    return os.environ.get("RFP_DISABLE_RESEARCH", "").strip() == ""


def _research_timeout() -> float:
    # 웹 조사는 여러 번 검색·열람하므로 기본 CLI 타임아웃(300s)보다 넉넉히.
    try:
        return float(os.environ.get("CLAUDE_RESEARCH_TIMEOUT", "600"))
    except ValueError:
        return 600.0


# 조사 활성(기본): 먼저 인터넷을 조사해 근거·수치를 확보하고 출처와 함께 작성.
_RFP_SYSTEM_RESEARCH = (
    "당신은 정부 R&D 연구개발계획서(사업계획서)의 한 절(節)을 작성하는 전문 집필자다. "
    "지어내지 말고 '조사해서' 쓴다 — 먼저 WebSearch/WebFetch 로 인터넷을 조사해 근거·수치를 "
    "확보한 뒤, [RFP 원문]과 조사 결과를 종합해 지정된 [문체]·[구성]·[작성요령]·[양식 템플릿]에 "
    "맞춰 이 절의 본문을 작성한다.\n"
    "조사 지침\n"
    "- 이 절 주제에 필요한 최신 정량 근거를 실제로 검색한다: 국내·외 시장규모·성장률(CAGR)·전망, "
    "기술수준·핵심 플레이어·경쟁사, 관련 특허 동향·국제표준(IEC/ISO 등)·인증·선급, 정책·법령·"
    "유사 국책과제 실적 등 그 절에 해당하는 항목을 우선 조사한다.\n"
    "- 정부·공공기관·표준화기구·전문 시장조사기관·학술/산업 보고서 등 신뢰할 수 있는 출처를 "
    "우선하고, 필요하면 WebFetch 로 원문을 확인한다. 여러 출처로 교차 확인한다.\n"
    "작성 규칙\n"
    "1) RFP 요건과 '조사로 확인한 사실'에 근거해 이 절 주제만 쓴다(다른 절 내용 금지).\n"
    "2) 개조식·정량 표기를 기본으로 하고, 핵심 수치에는 (출처, 연도)를 괄호로 간단히 병기한다. "
    "예: '글로벌 부유식 해상풍력 시장 2030년 약 XX억달러 전망(기관명, 2024)'.\n"
    "3) 수치는 조사로 확인된 값만 쓴다. 끝내 근거를 못 찾은 값만 [○○ 확인 필요]로 남기고, "
    "임의로 지어내지 않는다.\n"
    "4) [양식 템플릿]의 번호/마커 계층(□/○/- 또는 1./1.1 등)에 맞춘 개조식 문단으로 쓴다.\n"
    "5) 절 제목·머리말·조사 로그·해설은 넣지 않는다. 본문 개조식 문단을 먼저 쓰고, 검토용으로 "
    "맨 끝에만 '[출처]' 한 줄 뒤 참고한 출처 목록(매체/기관명 + URL)을 붙일 수 있다"
    "(제출 전 사용자가 다듬는다). 코드펜스로 감싸지 않는다."
)

# 조사 비활성(RFP_DISABLE_RESEARCH): 웹 없이 RFP 근거로만, 없는 수치는 자리표시.
_RFP_SYSTEM_NORESEARCH = (
    "당신은 정부 R&D 연구개발계획서(사업계획서)의 한 절(節)을 작성하는 전문 집필자다. "
    "아래 [RFP 원문](공고·제안요청서)에서 이 절에 필요한 배경·요건·목표·범위를 읽어, "
    "지정된 [문체]·[구성]·[작성요령]·[양식 템플릿]에 맞춰 이 절의 본문만 작성한다.\n"
    "규칙\n"
    "1) 반드시 RFP 내용에 근거해 이 절의 주제만 쓴다. 다른 절의 내용은 넣지 않는다.\n"
    "2) 개조식(짧은 개조식 종결)·정량 표기를 기본으로 하되, RFP에 없는 구체 수치는 "
    "지어내지 말고 [○○ 확인 필요] 같은 자리표시로 남긴다.\n"
    "3) [양식 템플릿]의 번호/마커 계층(□/○/- 또는 1./1.1 등)에 맞춘 개조식 문단으로 쓴다.\n"
    "4) 절 제목·머리말·해설 없이 본문 문단만 출력한다. 코드펜스로 감싸지 않는다."
)

# 그림·차트 자동삽입 지침 — 파이프라인(apply_markdown_images)이 아래 마커를 실제
# HWPX 그림개체로 바꾼다. draft 안에 그대로 쓰면 된다(코드펜스 밖 본문 흐름 속에).
_CHART_GUIDE = (
    "\n그림·도표(자동 변환)\n"
    "- 정량 데이터(시장규모·성장률·연도별 추이·구성비 등)는 표뿐 아니라 '차트'로도 넣을 수 있다. "
    "본문 흐름 안에 아래처럼 ```chart 펜스 블록을 그대로 쓰면 파이프라인이 실제 그래프 그림으로 "
    "바꿔 넣는다(그 아래에 <그림 N> 캡션·출처도 자동 생성):\n"
    "```chart\n"
    "type: bar        # bar|barh|line|pie\n"
    "title: 국내 부유식 해상풍력 시장 규모 (억원)\n"
    "x: [2023, 2024, 2025, 2030]\n"
    "y: [120, 180, 260, 900]\n"
    "ylabel: 억원\n"
    "source: 한국에너지공단(2025)\n"
    "```\n"
    "- 값은 (조사/RFP로) 확인한 실제 수치만 넣는다. 근거가 없으면 차트를 만들지 않는다. "
    "다계열은 series: {계열명: [값,…]} 로, 원그래프는 type: pie 로 쓴다."
)
_IMAGE_GUIDE = (
    "\n- 조사 중 이 절에 꼭 맞는 그림/도표(개념도·사진·그래프)를 찾으면, 직접 열리는 이미지 URL을 "
    "한 줄로 넣고 바로 다음 줄에 출처를 적는다(파이프라인이 내려받아 그림으로 삽입한다):\n"
    "![부유식 해상풍력 개념도](https://example.org/figure.png)\n"
    "출처: 기관명(연도)\n"
    "  URL은 실제 이미지 파일(.png/.jpg/.gif 등)로 직접 열리는 것만, 확실할 때만 넣는다"
    "(웹페이지·검색결과 링크는 넣지 않는다)."
)

# 참조 이미지(뉴스·보도자료·참고문헌에서 '가져온' 실제 이미지) 삽입 지침.
# 철회된 _CHART_GUIDE(도표 자동생성)와 달리 새 그림을 그리지 않고, 서술에서 언급한
# 대상(단지·기업·기술·비용 등)의 '실제' 이미지를 조사해 제목·출처와 함께 본문에 끼운다.
# 동향·시장 성격 절(_wants_reference_images)의 작성 경로에만 붙는다.
_REF_IMAGE_GUIDE = (
    "\n참조 이미지(실제 자료에서 가져오기 — 새로 그리지 말 것)\n"
    "- 이 절 서술에서 특정 대상을 언급하면(예: 특정 해상풍력 단지·기업·설비·기술, 또는 "
    "건설단가·시장규모 같은 수치), 그 내용과 직접 관련된 '실제 이미지'를 WebSearch/WebFetch 로 "
    "조사해 해당 서술 바로 아래에 끼운다. 도표를 새로 그리지 말고, 뉴스·보도자료·참고문헌·"
    "기관 보고서에 실린 사진·그래프·개념도를 그대로 가져온다.\n"
    "- 예: 국외 기술 동향에서 'Seagreen 해상풍력'을 서술했으면 그 단지 사진을, 건설비를 언급했으면 "
    "해상풍력 건설단가 그래프 이미지를 찾아 넣는다.\n"
    "- 형식(본문 흐름 속에 한 줄씩, 관련 서술 바로 아래):\n"
    "![그림 제목(무엇인지 알 수 있게)](직접 열리는 이미지 URL)\n"
    "출처: 매체/기관명(연도), 원문 URL\n"
    "- URL 은 실제 이미지 파일(.png/.jpg/.jpeg/.gif 등)로 직접 열리는 것만 넣는다"
    "(웹페이지·검색결과·썸네일 링크 금지). 확실치 않으면 그 이미지는 넣지 않는다"
    "(존재하지 않는 URL 을 지어내지 않는다).\n"
    "- 방법: web_search 로 관련 기사·보도자료·위키 페이지를 찾은 뒤, 그 페이지를 web_fetch(또는 "
    "WebFetch)로 실제로 열어 본문 안 사진/그래프의 '이미지 주소'(<img> 의 src, 보통 .jpg/.png 로 끝남)를 "
    "그대로 복사해 넣는다. 위키피디아/위키미디어 커먼즈(upload.wikimedia.org)의 직접 이미지 URL 도 좋다. "
    "검색만으로 직접 이미지 URL 이 확인되지 않으면 그 그림은 넣지 않는다."
)


def _reference_image_nids() -> set[str]:
    """참조 이미지를 붙일 '동향·시장' 성격 절의 nid 집합. IMAGE_SECTIONS 로 재정의."""
    raw = os.environ.get("IMAGE_SECTIONS", "").strip()
    if raw:
        return {t.strip() for t in raw.replace(",", " ").split() if t.strip()}
    return {"1-2", "5-1"}


def _wants_reference_images(nid: str | None) -> bool:
    """이 절이 참조 이미지 삽입(+웹조사) 대상인지."""
    return bool(nid) and str(nid).strip() in _reference_image_nids()


def _rfp_context_block(context: dict) -> str:
    """절 맥락(제목·작성요령·양식·문체·구성)을 시스템 프롬프트 꼬리로. RFP 원문 제외."""
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
    return (
        f"\n\n[대상 절]\n{label} {title}".rstrip()
        + f"\n\n[작성요령]\n{chr(10).join('- ' + g for g in guides) or '(없음)'}"
        + f"\n\n[양식 템플릿]\n```yaml\n{tpl_yaml}```"
        + f"\n\n[문체]\n{prompts.get('style') or '(지정 없음)'}"
        + f"\n\n[구성]\n{prompts.get('structure') or '(지정 없음)'}"
    )


def _stub_draft_from_rfp(context: dict, rfp_text: str, reason: str = "") -> str:
    """키/CLI 실패 시 결정론적 대체 — RFP 발췌를 양식 마커에 맞춰 개조식으로 정리."""
    template = (context or {}).get("template") or {}
    segs = _split_segments(rfp_text)[:8]
    nodes = _apply_markers(segs, [f"stub/{i}" for i in range(len(segs))], template)
    lines = [f"{n['marker']} {n['text']}".strip() for n in nodes if n["text"]]
    why = f" : {reason}" if reason else ""
    head = f"[스텁 모드 — Claude 호출 실패로 RFP 발췌만 정리했습니다{why}]"
    return head + "\n" + "\n".join(lines)


def _claude_draft_from_rfp(context: dict, rfp_text: str) -> str:
    note = (context or {}).get("note") or ""
    research = _rfp_research_enabled()
    system = (_RFP_SYSTEM_RESEARCH + _CHART_GUIDE + _IMAGE_GUIDE) if research \
        else (_RFP_SYSTEM_NORESEARCH + _CHART_GUIDE)
    ask_text = (
        "먼저 이 절 주제의 최신 시장·기술·표준·정책 수치를 인터넷으로 조사한 뒤, "
        "조사한 근거와 (출처, 연도)를 반영해 정량적으로 작성하라."
        if research
        else "위 RFP를 근거로 이 절의 본문을 지정 문체·구성·양식에 맞춰 작성하라."
    )
    user = (
        f"[RFP 원문]\n{rfp_text}\n\n"
        f"[요청]\n{ask_text}"
        + (f"\n{note}" if note else "")
    )
    raw = _ask(
        system + _rfp_context_block(context),
        [{"role": "user", "content": user}],
        max_tokens=16000,
        allow_tools=_RFP_RESEARCH_TOOLS if research else None,
        timeout=_research_timeout() if research else None,
    )
    # 모델이 실수로 전체를 코드펜스로 씌우면 바깥 펜스만 벗긴다(내부 ```chart 는 보존).
    body = _unwrap_fence(raw)
    return body or raw.strip()


def draft_from_rfp(context: dict | None, rfp_text: str) -> str:
    """RFP 원문을 근거로 한 절의 본문 초안(str)을 반환한다.

    context = {label,title,guidelines,template,prompts,note}
    API 키 → claude 실행파일 → 스텁 순으로 폴백한다.
    """
    context = context if isinstance(context, dict) else {}
    rfp_text = (rfp_text or "").strip()
    if not rfp_text:
        return ""
    try:
        return _claude_draft_from_rfp(context, rfp_text)
    except Exception as exc:  # noqa: BLE001 - 어떤 오류든 스텁 폴백
        return _stub_draft_from_rfp(context, rfp_text, reason=str(exc)[:200])


def segment_input(
    input_text: str,
    template: dict | None,
    prompts: dict | None,
    targets: list[str] | None,
) -> list[dict]:
    """LLM 없이 입력 텍스트를 targets 에 결정론적으로 매핑한 [{path,marker,text}].

    이미 완성된 초안(draft)을 추가 LLM 호출 없이 yaml 병합용으로 나눌 때 쓴다.
    convert_input 과 달리 문체 재작성을 하지 않는다(_stub_convert_input 과 동일 로직).
    """
    template = template if isinstance(template, dict) else {}
    prompts = prompts if isinstance(prompts, dict) else {}
    targets = list(targets or [])
    if not targets:
        return []
    return _stub_convert_input(input_text, template, prompts, targets)


def segment_input_packed(
    input_text: str,
    template: dict | None,
    targets: list[str] | None,
) -> list[dict]:
    """초안 전체를 targets 슬롯에 **유실 없이** 매핑한 [{path,marker,text}].

    segment_input(계약: 항상 len(targets), 초과분 버림·부족분 공백)과 달리, 문서를
    자동 반영할 때 내용이 잘리거나 원본 슬롯이 빈값으로 지워지는 것을 막는다.

    - 세그먼트 수 > 슬롯 수: 앞 슬롯을 채우고 **마지막 슬롯에 나머지를 합쳐** 담는다(버림 없음).
    - 세그먼트 수 ≤ 슬롯 수: 앞에서부터 채우고, **남는 슬롯은 결과에 넣지 않아** 원본 문단을
      건드리지 않는다(placeholder 유지, 빈값 덮어쓰기 없음).

    문서 템플릿의 문단 슬롯 수가 적은 절(예: 5-3=1칸)에서도 조사·작성한 본문 전체가
    최소한 한 문단으로라도 반영되게 하는 게 목적이다.
    """
    template = template if isinstance(template, dict) else {}
    targets = list(targets or [])
    if not targets:
        return []
    segments = _split_segments(input_text)
    if not segments:
        return []
    nt = len(targets)
    if len(segments) > nt:
        used = segments[: nt - 1] + ["\n".join(segments[nt - 1:])] if nt >= 1 else []
        tgt = targets
    else:
        used = segments
        tgt = targets[: len(segments)]
    # used 와 tgt 는 길이가 같으므로 _apply_markers 가 공백 패딩 없이 1:1 매핑한다.
    return _apply_markers(used, tgt, template)


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
    rfp_text: str = "",
    nid: str = "",
    overview_text: str = "",
) -> list[dict]:
    """[제반사항]+[RFP 원문]+[사용자 입력]을 근거로 이 절을 작성·분할해 targets에 매핑한 반환.

    API 키 → claude 실행파일 → 스텁 순으로 폴백한다. 반환 길이는 항상 len(targets)와 같다.
    nid 가 동향·시장 절(_wants_reference_images)이면 웹조사로 참조 이미지를 함께 끼운다.
    overview_text(제반사항)는 RFP 와 상충 시 우선하는 공통 정보로 투입한다.
    """
    template = template if isinstance(template, dict) else {}
    prompts = prompts if isinstance(prompts, dict) else {}
    targets = list(targets or [])
    if not targets:
        return []

    try:
        return _claude_convert_input(
            input_text, template, prompts, targets,
            rfp_text=rfp_text, nid=nid, overview_text=overview_text,
        )
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


# ── 표지 자동채움: RFP 추출 / 기술분류 제안 ──────────────────────────────────
def _parse_json_obj(raw: str) -> dict:
    """LLM 출력에서 JSON 객체를 뽑아 dict 로. 실패하면 {}."""
    try:
        obj = json.loads(_extract_fenced(raw or "", ("json",)))
        return obj if isinstance(obj, dict) else {}
    except Exception:  # noqa: BLE001
        # 본문 어딘가의 {...} 블록을 관대하게 시도
        m = re.search(r"\{.*\}", raw or "", re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
                return obj if isinstance(obj, dict) else {}
            except Exception:  # noqa: BLE001
                return {}
        return {}


_COVER_RFP_SYSTEM = (
    "당신은 정부 R&D 공고문/품목 설명(RFP)에서 '사업계획서 표지' 항목을 추출하는 도우미다. "
    "아래 RFP 원문에서 다음 값을 찾아 **JSON 객체 하나만** 출력한다.\n"
    "- gov_dept: 중앙행정기관명(예: 산업통상자원부)\n"
    "- agency: 전문기관명(예: 한국산업기술기획평가원·한국에너지기술평가원·KEIT·KETEP)\n"
    "- sub_biz: 세부사업명(명시 없으면 사업명·분야·미션 등 사업을 가리키는 가장 가까운 명칭)\n"
    "- detail_biz: 내역사업명\n"
    "- notice_no: 공고번호 또는 관리번호(예: 제2026-000호, 2026-3차-○○-01)\n"
    "- title_ko: 과제명(국문) — RFP 의 과제명·품목명\n"
    "- task_no: 연구개발 과제번호(관리번호와 별개로 명시된 경우)\n"
    "- ind_class1: 산업기술분류(대/중/소분류 중 가장 구체적인 명칭, 예: 조선/해양시스템)\n"
    "- ind_class2: 산업기술분류 2순위(있을 때)\n"
    "규칙: RFP 원문에 있거나 명확히 대응하는 값만 넣는다. 근거 없는 값은 그 키를 빈 문자열(\"\")로 두거나 "
    "생략한다(창작 금지). 코드펜스 밖 설명 없이 JSON 만 출력."
)

_COVER_RFP_KEYS = (
    "gov_dept", "agency", "sub_biz", "detail_biz", "notice_no",
    "title_ko", "task_no", "ind_class1", "ind_class2",
)


def cover_autofill_rfp(rfp_text: str) -> dict:
    """RFP 원문에서 표지 상단 항목(gov_dept·agency·sub_biz·detail_biz·notice_no)을 추출."""
    text = (rfp_text or "").strip()
    if not text:
        return {}
    user = f"[RFP 원문]\n{text[:_CONVERT_RFP_MAX]}\n\n위에서 표지 항목을 JSON 으로 추출하라."
    try:
        raw = _ask(_COVER_RFP_SYSTEM, [{"role": "user", "content": user}], max_tokens=800)
    except Exception:  # noqa: BLE001
        return {}
    obj = _parse_json_obj(raw)
    return {k: str(obj.get(k, "") or "").strip() for k in _COVER_RFP_KEYS
            if str(obj.get(k, "") or "").strip()}


_COVER_CLASS_SYSTEM = (
    "당신은 국가 R&D 과제의 '기술분류'를 정하는 전문가다. 아래 [과제 내용]을 근거로 "
    "(1) 산업통상자원부·KEIT의 **산업기술분류표**와 (2) **국가과학기술표준분류표**의 소분류를 "
    "각각 1~3순위로 제안한다.\n"
    "- 산업기술분류표: 대분류(기계·소재, 전기·전자, 정보통신, 화학공정, 바이오·의료, "
    "에너지·자원, 조선·해양, 건설·교통, 지식서비스 등) → 중분류 → 소분류 체계. 과제에 가장 "
    "부합하는 **소분류 명칭**을 쓴다(예: 조선/해양시스템, 해양플랜트, 자율운항시스템).\n"
    "- 국가과학기술표준분류표: 대분류(기계, 재료, 화학, 전기/전자, 정보/통신, 에너지/자원, "
    "건설/교통, 조선/해양, 환경 등) → 중분류 → 소분류 체계. 과제에 맞는 **소분류 명칭**을 쓴다.\n"
    "규칙: 두 공식 분류표에 실제 존재하는 표준 명칭을 사용한다(임의 창작 금지, 애매하면 상위 "
    "중분류 명칭). RFP 에 이미 명시된 산업기술분류가 있으면 그것을 1순위로 존중한다. 각 분류의 "
    "1~3순위 비율(%) 합=100. 2·3순위가 불확실하면 비운다.\n"
    "출력은 **JSON 객체 하나만**:\n"
    '{"ind_class1","ind_pct1","ind_class2","ind_pct2","ind_class3","ind_pct3",'
    '"nat_class1","nat_pct1","nat_class2","nat_pct2","nat_class3","nat_pct3"}\n'
    "비율은 '60%' 처럼 %를 포함. 코드펜스 밖 설명 없이 JSON 만 출력."
)

_COVER_CLASS_KEYS = (
    "ind_class1", "ind_pct1", "ind_class2", "ind_pct2", "ind_class3", "ind_pct3",
    "nat_class1", "nat_pct1", "nat_class2", "nat_pct2", "nat_class3", "nat_pct3",
)


def cover_classify(context_text: str) -> dict:
    """과제 내용(제목·목표·RFP 요지)으로 산업기술/국가과학기술 분류 1~3순위를 제안.

    두 공식 분류표에 대한 모델 지식으로 제안한다(웹 조사는 지연·불안정해 사용하지 않음)."""
    ctx = (context_text or "").strip()
    if not ctx:
        return {}
    user = (
        f"[과제 내용]\n{ctx[:6000]}\n\n"
        "위 과제 목표·내용에 맞는 산업기술분류·국가과학기술표준분류 소분류를 1~3순위로 JSON 제안하라."
    )
    try:
        raw = _ask(_COVER_CLASS_SYSTEM, [{"role": "user", "content": user}], max_tokens=1200)
    except Exception:  # noqa: BLE001
        return {}
    obj = _parse_json_obj(raw)
    return {k: str(obj.get(k, "") or "").strip() for k in _COVER_CLASS_KEYS
            if str(obj.get(k, "") or "").strip()}


_SUMMARY_SUGGEST_SYSTEM = (
    "당신은 정부 R&D 연구개발계획서 '요약문'의 [연구개발 목표 및 내용]을 작성하는 편집자다. "
    "아래 [과제 내용](과제명·RFP·제반사항 등)을 근거로 (1) 최종목표, (2) 각 연차별 목표, "
    "(3) 각 연차별 개발내용을 제안한다.\n"
    "규칙: 연차 라벨(year)은 아래 [연차 목록]의 문자열을 **글자 그대로(단계 표기 포함) 복사**해 쓴다. "
    "임의로 줄이거나 바꾸지 말 것(예: 목록이 '1단계 1차년도'면 그대로, '1차년도'로 축약 금지). "
    "goals·contents 는 [연차 목록]의 **모든 연차를 목록 순서대로 하나씩** 담는다. 각 목표·내용은 "
    "개조식으로 간결하게(1~3줄), RFP·과제 내용에 부합하게 작성한다. 근거 없는 구체 수치는 지어내지 "
    "말고 '[○○ 확인 필요]' 로 남긴다.\n"
    "출력은 **JSON 객체 하나만**: "
    '{"goal_final": "...", "goals": [{"year":"<연차 목록의 라벨 그대로>","text":"..."}, ...], '
    '"contents": [{"year":"<연차 목록의 라벨 그대로>","text":"..."}, ...]}. 코드펜스 밖 설명 금지.'
)


def summary_suggest(context_text: str, years: list[str] | None = None) -> dict:
    """과제 내용으로 요약문 '연구개발 목표 및 내용'(최종목표+연차별 목표·개발내용)을 제안."""
    ctx = (context_text or "").strip()
    if not ctx:
        return {}
    yl = ", ".join(y for y in (years or []) if y) or "(연차 미정)"
    user = (
        f"[연차 목록]\n{yl}\n\n[과제 내용]\n{ctx[:6000]}\n\n"
        "위 근거로 최종목표·연차별 목표·연차별 개발내용을 JSON 으로 제안하라."
    )
    try:
        raw = _ask(_SUMMARY_SUGGEST_SYSTEM, [{"role": "user", "content": user}], max_tokens=2000)
    except Exception:  # noqa: BLE001
        return {}
    obj = _parse_json_obj(raw)
    if not isinstance(obj, dict):
        return {}

    def _norm(lst) -> list[dict]:
        out = []
        for it in (lst or []):
            if isinstance(it, dict):
                y = str(it.get("year", "") or "").strip()
                t = str(it.get("text", "") or "").strip()
                if t:
                    out.append({"year": y, "text": t})
        return out

    yrs = [y for y in (years or []) if y]

    def _align(lst) -> list[dict]:
        """모델이 연차 라벨을 축약/변형해도 프런트·저장 키(=전체 라벨)에 맞춘다.
        개수가 [연차 목록]과 같으면 **순서대로 매핑**(가장 신뢰), 아니면 정확일치→유일한 접미사일치."""
        items = _norm(lst)
        if not yrs:
            return items
        if len(items) == len(yrs):
            return [{"year": yrs[i], "text": items[i]["text"]} for i in range(len(items))]
        out = []
        for it in items:
            y = it["year"]
            match = y if y in yrs else None
            if match is None:
                cands = [c for c in yrs if c == y or c.endswith(" " + y) or c.endswith(y)]
                if len(cands) == 1:
                    match = cands[0]
            out.append({"year": match or y, "text": it["text"]})
        return out

    return {
        "goal_final": str(obj.get("goal_final", "") or "").strip(),
        "goals": _align(obj.get("goals")),
        "contents": _align(obj.get("contents")),
    }


_TRANSLATE_TITLE_SYSTEM = (
    "당신은 정부 R&D 연구개발과제명을 한국어→영어로 옮기는 전문 번역가다. "
    "주어진 한국어 과제명을 학술·공식 제안서에 어울리는 자연스러운 영어 제목으로 번역한다. "
    "규칙: 영어 제목 '한 줄'만 출력(따옴표·설명·코드펜스·마침표 없이). 제목 형식(Title Case) 권장, "
    "고유명사·약어는 관용 표기를 따른다."
)


def translate_title_ko_en(text: str) -> str:
    """한국어 연구개발과제명 → 영어 제목 한 줄. 실패·미가용 시 빈 문자열."""
    t = (text or "").strip()
    if not t:
        return ""
    try:
        raw = _ask(_TRANSLATE_TITLE_SYSTEM, [{"role": "user", "content": t}], max_tokens=200)
    except Exception:  # noqa: BLE001
        return ""
    line = _unwrap_fence(raw or "").strip().strip('"').strip("'")
    return line.splitlines()[0].strip() if line else ""


_TABLE_AI_SYSTEM = (
    "당신은 정부 R&D 연구개발계획서의 '표 한 개'를 채우는 편집자다. 주어진 표의 "
    "**빈 칸(empty_cells 목록)만** 채운다.\n"
    "규칙: (1) 헤더·이미 값이 있는 칸·합계/비율 칸은 절대 바꾸지 않는다. "
    "(2) empty_cells 에 없는 좌표는 출력하지 않는다. "
    "(3) 근거 없는 구체 수치·금액은 지어내지 말고 '[확인 필요]' 로 남긴다. "
    "(4) 각 값은 그 칸의 행/열 머리글 의미에 맞게 간결히. 표 성격상 채울 내용이 없으면 그 칸은 생략.\n"
    "출력은 **JSON 객체 하나만**: {\"cells\": [{\"row\": <정수>, \"col\": <정수>, \"text\": \"...\"}, ...]}. "
    "코드펜스 밖 설명 금지."
)


def table_ai_fill(context_text: str, grid_text: str, empty_cells: list[dict],
                  instruction: str) -> list[dict]:
    """표의 빈 칸만 채울 값 목록 [{row,col,text}] 을 제안한다(실패·미가용 시 []).

    empty_cells = [{row,col}] (채워도 되는 좌표). 모델이 그 밖의 좌표를 내면 호출부(main)에서
    폐기한다(여기서도 좌표 집합으로 1차 필터). instruction 은 사용자의 자연어 지시."""
    allow = {(int(c.get("row")), int(c.get("col"))) for c in (empty_cells or [])
             if c.get("row") is not None and c.get("col") is not None}
    if not allow:
        return []
    ec = ", ".join(f"(r{r},c{c})" for r, c in sorted(allow))
    user = (
        f"[과제 배경]\n{(context_text or '')[:5000]}\n\n"
        f"[표 현재 내용 — 행\t열: 값]\n{(grid_text or '')[:6000]}\n\n"
        f"[채울 빈 칸 좌표]\n{ec}\n\n"
        f"[지시]\n{(instruction or '').strip() or '표 성격에 맞게 빈 칸을 채워라.'}\n\n"
        "위 빈 칸만 채운 JSON 을 제안하라."
    )
    try:
        raw = _ask(_TABLE_AI_SYSTEM, [{"role": "user", "content": user}], max_tokens=2000)
    except Exception:  # noqa: BLE001
        return []
    obj = _parse_json_obj(raw)
    out: list[dict] = []
    for c in (obj.get("cells") if isinstance(obj, dict) else None) or []:
        try:
            r, col = int(c.get("row")), int(c.get("col"))
        except Exception:  # noqa: BLE001
            continue
        t = str(c.get("text", "") or "").strip()
        if t and (r, col) in allow:
            out.append({"row": r, "col": col, "text": t})
    return out


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
