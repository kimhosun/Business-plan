#!/usr/bin/env python3
"""backend/rfp.py — RFP(제안요청서/공고) 업로드 → 절(節) 자동작성.

두 단계로 나뉜다.

1. **텍스트 추출** `extract_rfp_text(src)`
   - `.pdf`  → PyMuPDF(fitz)로 페이지 텍스트를 잇는다.
   - `.hwpx` → hwpx2yaml.py extract 로 문단 텍스트를 잇는다(한컴 COM 불필요).
   - `.hwp`  → hwp2hwpx.py convert(한컴 COM) 후 위와 동일.
   추출본은 컨텍스트 예산을 위해 MAX_CHARS 로 자른다.

2. **자동작성** `autofill(pid, rfp_text, sections, apply_yaml)`
   지정 절들에 대해 참조 프리셋 문체·구성으로 Claude 초안을 **병렬** 생성해
   각 절 input.md 에 채운다. apply_yaml=True 면 초안을 결정론적으로 나눠
   yaml/section_*.yaml 에도 병합한다(빌드 즉시 반영).

   병렬성: 초안 생성(claude_service.draft_from_rfp)은 절마다 독립이라
   ThreadPoolExecutor 로 동시에 돌린다("충분한 에이전트"). 다만 yaml 병합은
   section_*.yaml 을 공유·갱신하므로 **순차**로 처리해 경합을 막는다.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from . import claude_service, pipeline

# 사용자 요청 기본 대상 절(트리 nid). 4-2는 기대효과, 5-5는 사회적 가치.
# 2-2는 '기본 제안(baseline)'으로 작성한다(_SPECIAL_NOTE 참조).
TARGET_SECTIONS = [
    "1-1", "1-2", "2-1", "2-2", "4-1", "4-2", "5-1", "5-2", "5-3", "5-5",
]

# 절별 추가 지시(초안 생성 시 요청 꼬리에 덧붙임).
_SPECIAL_NOTE = {
    "2-2": (
        "이 절(2-2 연차별/단계별 개발목표·개발내용)은 RFP를 바탕으로 한 "
        "'기본 제안(baseline)'이다. 확정된 값이 없어도 합리적인 단계별·차년도 "
        "개발목표와 개발내용·범위를 제안형으로 구체 작성하라."
    ),
}

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


# ── 자동작성 ─────────────────────────────────────────────────────────────────
def _context_for(pid: str, nid: str) -> dict | None:
    """절 nid 의 초안 생성 컨텍스트(양식·프롬프트·작성요령·node_paths)."""
    from . import store  # 지연 임포트(순환 방지)

    node = store.node_by_id(pid, nid)
    if node is None:
        return None
    detail = store.read_node(pid, nid)  # 기본 template/prompts 생성 보장
    # 산문은 '본문 필드(문단)'에만 쓴다 — 표 셀(cell_para)은 대상에서 제외.
    body = pipeline.body_paths(pid, node.get("node_paths", []) or [])
    return {
        "nid": nid,
        "label": detail.get("label", ""),
        "title": detail.get("title", ""),
        "guidelines": detail.get("guidelines") or [],
        "template": detail.get("template") or {},
        "prompts": detail.get("prompts") or {},
        "node_paths": body,
        "note": _SPECIAL_NOTE.get(nid, ""),
    }


def _max_workers(n: int) -> int:
    # 웹 조사가 켜지면 절마다 여러 번 검색·열람하므로 동시 실행을 낮춰 과부하/레이트리밋을
    # 피한다(기본 3). 조사 없이 쓰면 더 높여도 된다(기본 5). RFP_AUTOFILL_WORKERS 로 덮어씀.
    default = 3 if claude_service._rfp_research_enabled() else 5  # noqa: SLF001
    try:
        env = int(os.environ.get("RFP_AUTOFILL_WORKERS", str(default)))
    except ValueError:
        env = default
    return max(1, min(env, n or 1))


def autofill(
    pid: str,
    rfp_text: str,
    sections: list[str] | None = None,
    apply_yaml: bool = False,
) -> list[dict]:
    """지정 절들을 RFP 근거로 자동작성해 input.md 에 채운다.

    반환: [{nid,title,ok,chars,applied,error}] (요청 sections 순서).
    - 초안 생성은 병렬(ThreadPoolExecutor), yaml 병합은 순차(경합 방지).
    """
    from . import store  # 지연 임포트(순환 방지)

    sections = list(sections or TARGET_SECTIONS)

    # 1) 컨텍스트 수집(순차; read_node 가 절별 기본파일을 만든다).
    contexts: dict[str, dict] = {}
    results: dict[str, dict] = {}
    for nid in sections:
        ctx = _context_for(pid, nid)
        if ctx is None:
            results[nid] = {
                "nid": nid, "title": "", "ok": False, "chars": 0,
                "applied": False, "error": "절을 찾을 수 없음",
            }
        else:
            contexts[nid] = ctx

    # CLI 경로 탐색 캐시를 병렬 진입 전에 1회 워밍(선택적).
    try:
        claude_service._find_cli()  # noqa: SLF001
    except Exception:  # noqa: BLE001
        pass

    # 2) 초안 생성(병렬) — input.md 저장까지. 절 디렉터리는 서로 독립이라 안전.
    def _draft(nid: str) -> tuple[str, str, str]:
        ctx = contexts[nid]
        try:
            draft = claude_service.draft_from_rfp(ctx, rfp_text)
        except Exception as exc:  # noqa: BLE001 - 개별 실패 격리
            return nid, "", str(exc)[:200]
        store.write_input(pid, nid, draft)
        return nid, draft, ""

    drafts: dict[str, str] = {}
    if contexts:
        with ThreadPoolExecutor(max_workers=_max_workers(len(contexts))) as pool:
            for nid, draft, err in pool.map(_draft, list(contexts.keys())):
                ctx = contexts[nid]
                if err:
                    results[nid] = {
                        "nid": nid, "title": ctx["title"], "ok": False, "chars": 0,
                        "applied": False, "error": err,
                    }
                else:
                    drafts[nid] = draft
                    results[nid] = {
                        "nid": nid, "title": ctx["title"],
                        "ok": bool(draft.strip()), "chars": len(draft),
                        "applied": False, "error": "",
                    }

    # 3) yaml 병합(순차) — section_*.yaml 공유 갱신이라 동시 쓰기 금지.
    if apply_yaml:
        for nid, draft in drafts.items():
            ctx = contexts[nid]
            if not draft.strip() or not ctx["node_paths"]:
                continue
            try:
                # 조사·작성한 초안 전체가 유실 없이 문서에 반영되도록 packed 매핑 사용.
                result = claude_service.segment_input_packed(
                    draft, ctx["template"], ctx["node_paths"]
                )
                store.write_result(pid, nid, result)
                pipeline.merge_result_into_yaml(pid, result)
                results[nid]["applied"] = True
            except Exception as exc:  # noqa: BLE001 - 병합 실패는 초안 자체엔 영향 없음
                results[nid]["error"] = f"yaml 병합 실패: {str(exc)[:150]}"

    return [results[nid] for nid in sections if nid in results]
