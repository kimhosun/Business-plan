#!/usr/bin/env python3
"""backend/rfp.py — RFP(제안요청서/공고) 업로드 → 본문 텍스트 추출.

`extract_rfp_text(src)`
   - `.pdf`  → PyMuPDF(fitz)로 페이지 텍스트를 잇는다.
   - `.hwpx` → hwpx2yaml.py extract 로 문단 텍스트를 잇는다(한컴 COM 불필요).
   - `.hwp`  → hwp2hwpx.py convert(한컴 COM) 후 위와 동일.
   추출본은 컨텍스트 예산을 위해 MAX_CHARS 로 자른다.

추출한 RFP 본문은 store 에 저장되고, 각 절 편집 화면의 '작성 프롬프트' 아래에
참조용으로 표시된다(절 자동작성 기능은 제거됨).
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import yaml

from . import pipeline

# 컨텍스트 예산(글자수). 환경변수 RFP_MAX_CHARS 로 조정.
try:
    MAX_CHARS = int(os.environ.get("RFP_MAX_CHARS", "48000"))
except ValueError:
    MAX_CHARS = 48000


# ── 텍스트 추출 ──────────────────────────────────────────────────────────────
def _pdf_text(path: Path) -> str:
    """PDF → 텍스트(PyMuPDF). 미설치/실패 시 pdfplumber 로 폴백."""
    try:
        import fitz  # PyMuPDF

        parts: list[str] = []
        with fitz.open(str(path)) as doc:
            for page in doc:
                parts.append(page.get_text("text"))
        return "\n".join(parts).strip()
    except Exception:  # noqa: BLE001 - fitz 실패 시 pdfplumber
        import pdfplumber

        parts = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        return "\n".join(parts).strip()


def _hwpx_text(hwpx: Path) -> str:
    """hwpx → 문단 텍스트(hwpx2yaml.py extract 재사용). COM 불필요."""
    tmp = Path(tempfile.mkdtemp(prefix="rfp_yaml_"))
    try:
        pipeline.extract(hwpx, tmp)
        texts: list[str] = []
        for f in sorted(tmp.glob("section_*.yaml")):
            if f.name == "_manifest.yaml":
                continue
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            for n in data.get("nodes", []):
                t = (n.get("text") or "").strip()
                if t:
                    texts.append(t)
        return "\n".join(texts).strip()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def extract_rfp_text(src: str | Path) -> str:
    """RFP 파일(.pdf/.hwpx/.hwp)에서 본문 텍스트를 뽑아 MAX_CHARS 로 자른다."""
    src = Path(src)
    suffix = src.suffix.lower()
    if suffix == ".pdf":
        text = _pdf_text(src)
    elif suffix == ".hwpx":
        text = _hwpx_text(src)
    elif suffix == ".hwp":
        tmp_dir = Path(tempfile.mkdtemp(prefix="rfp_conv_"))
        try:
            hwpx = tmp_dir / "rfp.hwpx"
            pipeline.convert(src, hwpx)
            text = _hwpx_text(hwpx)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        raise ValueError(f"지원하지 않는 RFP 형식입니다: {suffix or '(확장자 없음)'} (.pdf/.hwpx/.hwp)")

    text = text or ""
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    return text

