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
    """PUT .../prompts — {style, structure}"""
    style: str = ""
    structure: str = ""
    guidelines: list[str] | None = None


class InputBody(_Base):
    """PUT .../input — {input}"""
    input: str = ""


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
