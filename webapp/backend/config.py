#!/usr/bin/env python3
"""backend/config.py — 경로/상수 (ARCHITECTURE '모듈 책임' + '파일 저장 구조').

모든 경로는 pathlib.Path. DATA_DIR/PROJECTS_DIR는 import 시 생성한다.
"""
from __future__ import annotations

from pathlib import Path

# 저장소 루트 (webapp/ 의 상위)
ROOT_DIR = Path(__file__).resolve().parents[2]

# webapp/
WEBAPP_DIR = ROOT_DIR / "webapp"

# webapp/data (프로젝트 파일 저장 루트)
DATA_DIR = WEBAPP_DIR / "data"
PROJECTS_DIR = DATA_DIR / "projects"

# 재사용 파이프라인 CLI 디렉터리
SKILL_SCRIPTS = ROOT_DIR / ".claude" / "skills" / "hwpx-yaml-roundtrip" / "scripts"

# 기본 원본 문서(.hwp) — use_default 시 사용
DEFAULT_HWP = ROOT_DIR / "연구개발계획서.hwp"

# 서브프로세스로 파이썬 CLI 를 부를 때 쓰는 인터프리터
PYTHON = "python"

# 저장 디렉터리 보장
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
