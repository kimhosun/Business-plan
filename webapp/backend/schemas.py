#!/usr/bin/env python3
"""backend/schemas.py — REST API(ARCHITECTURE) 요청/응답 pydantic 모델.

계약을 따르되 permissive 하게(추가 필드 허용, 대부분 optional/기본값) 둔다.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    # 알 수 없는 키가 와도 거부하지 않음(프론트/AI 변화에 관대)
    model_config = ConfigDict(extra="allow")


# ── 요청 바디 ────────────────────────────────────────────────────────────────
class CreateProject(_Base):
    """POST /api/projects (JSON 바디). multipart file 업로드는 라우트에서 처리."""
    use_default: bool = True
    name: str | None = None


class TemplateBody(_Base):
    """PUT .../template — {template:{...}}"""
    template: dict[str, Any] = Field(default_factory=dict)


class GenerateBody(_Base):
    """POST .../template/generate — {description}"""
    description: str = ""


class PromptsBody(_Base):
    """PUT .../prompts — 문체 스타일 3원천 + 구성.

    style_skill(② 스킬 제공)·style_extra(③ 추가)·structure 를 받는다. ①(기존 한글파일
    요구)은 guidelines 로 이미 전달되므로 별도 저장하지 않는다. 저장 시 style 은
    style_skill + style_extra 를 합쳐 만든다(기존 작성 파이프라인 호환). 구버전 {style}
    호출도 그대로 받는다.
    """
    style: str | None = None          # 구버전 호환(있으면 style_skill 로 취급)
    style_skill: str | None = None
    style_extra: str | None = None
    structure: str = ""
    guidelines: list[str] | None = None


class InputBody(_Base):
    """PUT .../input — {input}"""
    input: str = ""


class OverviewBody(_Base):
    """PUT .../overview — {data} (제반사항: 구조화 입력).

    data = {institutions:[{role,name,type,duty}], period, periods:[{year,range}],
            funding:[{org,year,amount}], goal}
    (구버전 {text} 자유입력도 관대하게 받되, 현재 프론트는 data 로 보낸다.)
    """
    data: dict[str, Any] | None = None
    text: str | None = None
    # True 면 저장 직후 문서 표(표지·요약문·편성도·연구비)에 즉시 반영(doc_fill).
    apply: bool = False


class ChatBody(_Base):
    """POST .../chat — {message, apply, skills, use_skills}

    apply=True(기본)면 모델이 낸 draft 를 그 절의 input.md 에 그대로 반영한다.
    skills 를 주면 자동 선택 대신 그 slug 들을 강제로 적용하고,
    use_skills=False 면 스킬을 아예 붙이지 않는다.
    """
    message: str = ""
    apply: bool = True
    skills: list[str] | None = None
    use_skills: bool = True


class SkillBody(_Base):
    """POST /api/skills — 스킬 저장(신규/수정).

    slug 가 있으면 그 스킬을 덮어쓰고, 없으면 name 으로 새로 만든다.
    scope: auto(관련 있을 때만) | always(항상) | off(사용 안 함)
    """
    slug: str = ""
    name: str = ""
    description: str = ""
    body: str = ""
    triggers: list[str] | str | None = None
    scope: str = "auto"


class SkillImportBody(_Base):
    """POST /api/skills/import — {keys:[".claude/skills 폴더명", ...]}"""
    keys: list[str] = Field(default_factory=list)
    scope: str = "auto"


class SkillMatchBody(_Base):
    """POST /api/skills/match — {query, context} 로 어떤 스킬이 붙을지 미리보기."""
    query: str = ""
    context: str = ""


# ── 응답 모델 ────────────────────────────────────────────────────────────────
class ProjectInfo(_Base):
    """GET /api/projects 목록 항목."""
    id: str
    name: str = ""
    created: str = ""


class ProjectCreated(_Base):
    pid: str


class NodeDetail(_Base):
    """GET .../nodes/{nid} 응답."""
    id: str
    label: str = ""
    title: str = ""
    guidelines: list[str] = Field(default_factory=list)
    template: dict[str, Any] = Field(default_factory=dict)
    prompts: dict[str, Any] = Field(default_factory=dict)
    input: str = ""
    result: list[dict[str, Any]] = Field(default_factory=list)
    chat: list[dict[str, Any]] = Field(default_factory=list)
    node_count: int = 0


class ConvertRow(_Base):
    path: str
    before: str = ""
    after: str = ""
    marker: str = ""


class ConvertResult(_Base):
    """POST .../convert 응답."""
    result: list[ConvertRow] = Field(default_factory=list)


class BuildResult(_Base):
    """POST .../build 응답."""
    download: str = ""
    preview: str = ""


class ConvertOutput(_Base):
    """pipeline/파이프라인 변환 산출(=result.yaml 항목)."""
    path: str
    marker: str = ""
    text: str = ""
