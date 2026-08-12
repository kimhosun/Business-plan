#!/usr/bin/env python3
"""backend/main.py — FastAPI 앱 + REST 라우트 + 정적 프론트 마운트.

ARCHITECTURE.md 의 REST API 계약을 정확히 구현하며, 실제 작업은
store / pipeline / claude_service 로 위임한다. 프론트(webapp/frontend)는
'/' 에 StaticFiles(html=True) 로 서빙한다.

구동:  cd webapp && uvicorn backend.main:app --reload  → http://127.0.0.1:8000
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import claude_service, config, doc_fill, pipeline, presets, regulations, rfp, store, tables
from .schemas import (
    ChatBody,
    GenerateBody,
    InputBody,
    OverviewBody,
    PromptsBody,
    TemplateBody,
)

app = FastAPI(title="연구개발계획서 웹서비스", version="1.0")

# 개발용 CORS 전체 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = config.WEBAPP_DIR / "frontend"


# ── 공용 헬퍼 ────────────────────────────────────────────────────────────────
def _require_project(pid: str) -> dict:
    meta = store.project_meta(pid)
    if not meta:
        raise HTTPException(status_code=404, detail=f"project not found: {pid}")
    return meta


def _node_or_404(pid: str, nid: str) -> dict:
    node = store.node_by_id(pid, nid)
    if node is None:
        raise HTTPException(status_code=404, detail=f"node not found: {pid}/{nid}")
    return node


def _sample_texts(pid: str, node: dict, limit: int = 8) -> list[str]:
    """해당 노드 node_paths 의 현재 yaml 본문 텍스트 일부(양식 생성 참고용)."""
    index = pipeline._all_nodes_by_path(pid)
    out: list[str] = []
    for p in node.get("node_paths", []) or []:
        yn = index.get(p) or {}
        txt = (yn.get("text") or "").strip()
        if txt:
            out.append(txt)
        if len(out) >= limit:
            break
    return out


# ── 프로젝트 ──────────────────────────────────────────────────────────────────
@app.post("/api/projects")
async def create_project(request: Request):
    """JSON {use_default:true[,name]} 또는 multipart file(.hwp/.hwpx). → {pid}"""
    ctype = request.headers.get("content-type", "")
    try:
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if upload is None or not getattr(upload, "filename", ""):
                raise HTTPException(status_code=400, detail="multipart 'file' 필드가 필요합니다.")
            name = form.get("name") or Path(upload.filename).stem
            suffix = Path(upload.filename).suffix or ".hwp"
            tmp = Path(tempfile.mkdtemp(prefix="rnd_upload_")) / f"source{suffix}"
            with open(tmp, "wb") as fh:
                shutil.copyfileobj(upload.file, fh)
            try:
                pid = store.new_project(name, tmp)
            finally:
                shutil.rmtree(tmp.parent, ignore_errors=True)
        else:
            try:
                body = await request.json()
            except Exception:
                body = {}
            use_default = bool(body.get("use_default", True))
            name = body.get("name")
            if not use_default and body.get("source_path"):
                src = Path(body["source_path"])
            else:
                src = config.DEFAULT_HWP
            if not Path(src).exists():
                raise HTTPException(status_code=400, detail=f"원본 문서를 찾을 수 없습니다: {src}")
            pid = store.new_project(name, src)
        return {"pid": pid}
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"프로젝트 생성 실패: {exc}") from exc


@app.get("/api/projects")
async def list_projects():
    return store.list_projects()


@app.delete("/api/projects/{pid}")
async def delete_project(pid: str):
    """프로젝트와 그 파일 전체를 삭제한다. → {deleted: pid}"""
    _require_project(pid)
    if not store.delete_project(pid):
        raise HTTPException(status_code=500, detail="프로젝트 삭제에 실패했습니다.")
    return {"deleted": pid}


@app.get("/api/projects/{pid}/tree")
async def get_tree(pid: str):
    _require_project(pid)
    return store.load_tree(pid)


# ── 노드 ──────────────────────────────────────────────────────────────────────
@app.get("/api/projects/{pid}/nodes/{nid}")
async def get_node(pid: str, nid: str):
    _require_project(pid)
    try:
        detail = store.read_node(pid, nid)
        # 이 절에서 제반사항 중 특히 반영할 항목 안내(UI 표기용)
        if isinstance(detail, dict):
            detail["overview_focus"] = claude_service.overview_focus(nid)
        return detail
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"노드 조회 실패: {exc}") from exc


@app.put("/api/projects/{pid}/nodes/{nid}/template")
async def put_template(pid: str, nid: str, body: TemplateBody):
    _require_project(pid)
    _node_or_404(pid, nid)
    tpl = store.write_template(pid, nid, body.template or {})
    return {"template": tpl}


@app.post("/api/projects/{pid}/nodes/{nid}/template/generate")
def generate_template(pid: str, nid: str, body: GenerateBody):
    _require_project(pid)
    node = _node_or_404(pid, nid)
    try:
        detail = store.read_node(pid, nid)
        default_template = detail.get("template") or {}
        samples = _sample_texts(pid, node)
        tpl = claude_service.generate_template(body.description, default_template, samples)
        store.write_template(pid, nid, tpl)
        return {"template": tpl}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"양식 생성 실패: {exc}") from exc


@app.put("/api/projects/{pid}/nodes/{nid}/prompts")
async def put_prompts(pid: str, nid: str, body: PromptsBody):
    _require_project(pid)
    _node_or_404(pid, nid)
    # 사용자 소유는 ③(style_extra)·structure 뿐. ②(스킬 제공)·합본 style 은 저장하지 않고
    # read 시 현재 프리셋에서 파생한다(presets 원천 갱신이 모든 절에 즉시 반영되게).
    prompts = {"style_extra": body.style_extra or "", "structure": body.structure or ""}
    if body.guidelines is not None:
        prompts["guidelines"] = body.guidelines
    saved = store.write_prompts(pid, nid, prompts)
    # 응답엔 파생 필드(②·합본)를 채워 준다(프런트 즉시 표시용).
    skill = presets.preset_for(nid).get("style", "")
    saved["style_skill"] = skill
    saved["style"] = presets.combine_style(skill, saved.get("style_extra", "") or "")
    return {"prompts": saved}


@app.get("/api/presets/{nid}")
async def get_preset(nid: str):
    """절 nid 의 참조 사업계획서(rnd-write-*) 문체·구성 프리셋."""
    return presets.preset_for(nid)


@app.get("/api/reg-status")
async def reg_status():
    """절별 법령·규정 데이터셋 상태(기준일·건수). UI 기준일 표시용."""
    data = regulations._regdata()
    secs = data.get("sections", {}) or {}
    return {
        "as_of": data.get("as_of", ""),
        "business": data.get("business", ""),
        "disclaimer": data.get("disclaimer", ""),
        "common_count": len(data.get("common", []) or []),
        "section_count": len(secs),
        "law_count": sum(len(s.get("regulations", []) or []) for s in secs.values()),
    }


@app.get("/api/regulations/{nid}")
async def get_regulation(nid: str):
    """절 nid 에 적용되는 작성 규정(구조화 JSON) + 원본 확인 경로."""
    return regulations.regulation_for(nid)


@app.get("/api/projects/{pid}/nodes/{nid}/regulations.pdf")
async def regulations_pdf(pid: str, nid: str):
    """이 절을 쓸 때 적용할 규정을 한 장의 PDF 로. 브라우저에서 바로 열린다."""
    meta = _require_project(pid)
    node = _node_or_404(pid, nid)
    try:
        reg = regulations.regulation_for(nid, node)
        ctx = {
            "source_hwpx": meta.get("source_hwpx")
            or str(store.project_dir(pid) / "source.hwpx"),
            "yaml_dir": str(store.yaml_dir(pid)),
            "node_dir": str(store.node_dir(pid, nid)),
            "node_paths": list(node.get("node_paths", []) or []),
        }
        out = store.output_dir(pid) / f"regulations_{nid}.pdf"
        regulations.build_pdf(reg, out, ctx)
    except RuntimeError as exc:  # 한글 폰트 없음 등
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"규정 PDF 생성 실패: {exc}") from exc
    return FileResponse(
        str(out),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="regulations_{nid}.pdf"'},
    )


@app.get("/api/projects/{pid}/nodes/{nid}/tables")
async def get_tables(pid: str, nid: str):
    """절 nid 의 표를 엑셀형 그리드로. (8장 등 표 중심 절의 입력 탭용)"""
    _require_project(pid)
    _node_or_404(pid, nid)
    return tables.tables_for(pid, nid)


@app.put("/api/projects/{pid}/nodes/{nid}/tables")
async def put_tables(pid: str, nid: str, body: dict = Body(...)):
    """그리드 편집(변경 셀만) 저장 → yaml 반영. body {cells:[{paths,text}]}."""
    _require_project(pid)
    _node_or_404(pid, nid)
    cells = (body or {}).get("cells") or []
    stats = tables.save_cells(pid, nid, cells)
    return stats


@app.get("/api/projects/{pid}/nodes/{nid}/tables.xlsx")
async def get_tables_xlsx(pid: str, nid: str):
    """절의 표들을 .xlsx 로 내려받기(표마다 시트 1개)."""
    _require_project(pid)
    _node_or_404(pid, nid)
    out = store.output_dir(pid) / f"tables_{nid}.xlsx"
    tables.to_xlsx(pid, nid, out)
    return FileResponse(
        str(out),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"tables_{nid}.xlsx",
    )


@app.post("/api/projects/{pid}/nodes/{nid}/tables/import-xlsx")
async def import_tables_xlsx(pid: str, nid: str, file: UploadFile = File(...)):
    """업로드한 .xlsx 를 위치 기준으로 그리드에 되읽어 저장."""
    _require_project(pid)
    _node_or_404(pid, nid)
    tmp = store.output_dir(pid) / f"_import_{nid}.xlsx"
    tmp.write_bytes(await file.read())
    try:
        stats = tables.from_xlsx(pid, nid, tmp)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"엑셀 읽기 실패: {exc}") from exc
    return stats


@app.post("/api/projects/{pid}/nodes/{nid}/tables/structure")
async def tables_structure(pid: str, nid: str, body: dict = Body(...)):
    """행/열 추가·삭제. body {op:'add_row'|'del_row'|'add_col'|'del_col',
    table_path, index}. 실패 시 원상복구(400)."""
    _require_project(pid)
    _node_or_404(pid, nid)
    op = (body or {}).get("op")
    tp = (body or {}).get("table_path")
    idx = int((body or {}).get("index", 0))
    if not tp or op not in ("add_row", "del_row", "add_col", "del_col"):
        raise HTTPException(status_code=400, detail="op/table_path 가 올바르지 않습니다.")
    fn = {"add_row": tables.add_row, "del_row": tables.delete_row,
          "add_col": tables.add_col, "del_col": tables.delete_col}[op]
    try:
        info = fn(pid, nid, tp, idx)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"구조 편집 실패: {exc}") from exc
    return {"ok": True, **(info or {})}


@app.get("/api/projects/{pid}/nodes/{nid}/tables/formulas")
async def get_table_formulas(pid: str, nid: str):
    _require_project(pid)
    _node_or_404(pid, nid)
    return {"formulas": tables.get_formulas(pid, nid)}


@app.put("/api/projects/{pid}/nodes/{nid}/tables/formulas")
async def put_table_formulas(pid: str, nid: str, body: dict = Body(...)):
    _require_project(pid)
    _node_or_404(pid, nid)
    return tables.save_formulas(pid, nid, (body or {}).get("formulas") or {})


@app.put("/api/projects/{pid}/nodes/{nid}/input")
async def put_input(pid: str, nid: str, body: InputBody):
    _require_project(pid)
    _node_or_404(pid, nid)
    store.write_input(pid, nid, body.input or "")
    return {"input": body.input or ""}


@app.post("/api/projects/{pid}/nodes/{nid}/chat")
def chat_node(pid: str, nid: str, body: ChatBody):
    """작성 채팅 한 턴. Claude 가 답변(reply)과 본문 초안(draft)을 낸다.

    apply=True 면 draft 를 input.md 에 반영해 갱신된 input 을 함께 돌려준다.
    → {reply, draft, input, chat}

    claude 실행파일(subprocess) 경로가 수십 초 블로킹이라 sync 라우트로 둔다
    (FastAPI 가 스레드풀에서 실행 → 이벤트 루프를 막지 않음).
    """
    _require_project(pid)
    _node_or_404(pid, nid)
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message 가 비어 있습니다.")
    try:
        detail = store.read_node(pid, nid)
        context = {
            "nid": nid,  # 동향·시장 절이면 참조 이미지(+웹조사)를 붙이는 판단에 쓴다
            "label": detail.get("label", ""),
            "title": detail.get("title", ""),
            "guidelines": detail.get("guidelines") or [],
            "template": detail.get("template") or {},
            "prompts": detail.get("prompts") or {},
            "input": detail.get("input") or "",
            "rfp": store.read_rfp_text(pid),  # 업로드된 RFP 를 작성 근거로 반영
            "overview": store.read_overview(pid),  # 제반사항(공통 정보)을 최우선 근거로
        }
        history = detail.get("chat") or []

        result = claude_service.chat_write(context, history, message)
        reply = result.get("reply") or ""
        draft = result.get("draft")

        store.append_chat(pid, nid, "user", message)
        chat = store.append_chat(pid, nid, "assistant", reply)

        input_text = context["input"]
        if body.apply and draft is not None:
            input_text = store.write_input(pid, nid, draft)

        return {"reply": reply, "draft": draft, "input": input_text, "chat": chat}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"채팅 실패: {exc}") from exc


@app.delete("/api/projects/{pid}/nodes/{nid}/chat")
async def clear_chat(pid: str, nid: str):
    """작성 채팅 이력 초기화(입력 본문은 그대로 둔다)."""
    _require_project(pid)
    _node_or_404(pid, nid)
    return {"chat": store.clear_chat(pid, nid)}


@app.post("/api/projects/{pid}/nodes/{nid}/convert")
def convert_node(pid: str, nid: str):
    """Claude 변환 → result.yaml 저장 + yaml/ 병합 → {result:[{path,before,after,marker}]}"""
    _require_project(pid)
    node = _node_or_404(pid, nid)
    try:
        detail = store.read_node(pid, nid)
        # 변환도 산문을 본문 필드(문단)에만 쓴다 — 표 셀은 그리드 편집 전용.
        targets = pipeline.body_paths(pid, node.get("node_paths", []) or [])
        template = detail.get("template") or {}
        prompts = detail.get("prompts") or {}
        input_text = detail.get("input") or ""
        rfp_text = store.read_rfp_text(pid)  # 업로드된 RFP 를 변환 근거로 반영
        overview_text = store.read_overview(pid)  # 제반사항(공통 정보)을 최우선 근거로

        # 병합 전 현재 yaml 본문(before) 스냅샷
        before_index = pipeline._all_nodes_by_path(pid)

        result = claude_service.convert_input(
            input_text, template, prompts, targets,
            rfp_text=rfp_text, nid=nid, overview_text=overview_text,
        )

        store.write_result(pid, nid, result)
        pipeline.merge_result_into_yaml(pid, result)

        rows = []
        for r in result:
            p = r.get("path", "")
            before = (before_index.get(p, {}) or {}).get("text") or ""
            rows.append(
                {
                    "path": p,
                    "before": before,
                    "after": r.get("text", "") or "",
                    "marker": r.get("marker", "") or "",
                }
            )
        return {"result": rows}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"변환 실패: {exc}") from exc


# ── RFP(제안요청서/공고) 업로드 → 절 자동작성 ────────────────────────────────
@app.get("/api/projects/{pid}/rfp")
async def get_rfp(pid: str):
    """업로드된 RFP 메타(파일명·글자수·업로드시각)와 추출 본문 텍스트.

    각 절 편집 화면의 '작성 프롬프트' 아래에 참조용으로 표시하기 위해 text 도 함께 준다.
    """
    _require_project(pid)
    meta = store.rfp_meta(pid) or {}
    text = store.read_rfp_text(pid) if meta.get("filename") else ""
    return {"meta": meta, "text": text}


@app.post("/api/projects/{pid}/rfp")
def upload_rfp(pid: str, file: UploadFile = File(...)):
    """RFP 파일(.pdf/.hwpx/.hwp) 업로드 → 텍스트 추출·저장. → {filename,chars,sections}

    .hwp 는 한컴 COM 변환이 필요해 수십 초 걸릴 수 있어 sync 라우트로 둔다
    (FastAPI 가 스레드풀에서 실행 → 이벤트 루프를 막지 않음).
    """
    _require_project(pid)
    filename = getattr(file, "filename", "") or ""
    if not filename:
        raise HTTPException(status_code=400, detail="파일이 필요합니다.")
    suffix = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".hwpx", ".hwp"):
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 형식입니다: {suffix or '(없음)'} (.pdf/.hwpx/.hwp 만)",
        )
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    try:
        src = store.save_rfp(pid, filename, data)
        text = rfp.extract_rfp_text(src)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"RFP 추출 실패: {exc}") from exc
    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="RFP 에서 텍스트를 찾지 못했습니다(스캔 이미지 PDF 등일 수 있습니다).",
        )
    meta = store.write_rfp_text(pid, text, {"filename": filename, "ext": suffix})
    # RFP 내용으로 표지 상단 항목(기관·사업명·공고번호)을 자동 추출해 빈 칸만 채운다(best-effort).
    cover_filled = _autofill_cover_from_rfp(pid, text)
    return {
        "filename": filename, "chars": meta.get("chars", len(text)),
        "text": text, "cover_filled": cover_filled,
    }


def _autofill_cover_from_rfp(pid: str, rfp_text: str) -> list[str]:
    """RFP 에서 추출한 표지 항목을 overview.cover 의 **빈 칸에만** 채워 저장. 채운 키 목록 반환.

    사용자가 이미 입력한 값은 덮지 않는다. LLM 미가용·실패는 조용히 건너뛴다(업로드는 성공 유지)."""
    try:
        fields = claude_service.cover_autofill_rfp(rfp_text)
    except Exception:  # noqa: BLE001
        return []
    if not fields:
        return []
    ov = store.read_overview_data(pid)
    cover = dict(ov.get("cover") or {})
    filled: list[str] = []
    for k, v in fields.items():
        if v and not str(cover.get(k) or "").strip():
            cover[k] = v
            filled.append(k)
    if filled:
        ov["cover"] = cover
        store.write_overview_data(pid, ov)
    return filled


# ── 제반사항(프로젝트 공통 자유입력) — 전체 작성 참고 ────────────────────────
@app.get("/api/projects/{pid}/overview")
async def get_overview(pid: str):
    """전체 절 작성에 공통 참고하는 '제반사항'(구조화 data + LLM용 직렬화 text)."""
    _require_project(pid)
    data = store.read_overview_data(pid)
    text = store.read_overview(pid)
    return {"data": data, "text": text, "chars": len(text)}


@app.put("/api/projects/{pid}/overview")
async def put_overview(pid: str, body: OverviewBody):
    """제반사항(구조화) 저장. 이후 이 프로젝트의 모든 절 변환·작성 채팅에 참고로 투입된다.

    body.apply=True(저장 버튼)면 저장 직후 문서 표(표지·요약문·편성도·연구비)에 즉시 반영한다."""
    _require_project(pid)
    data = body.data if isinstance(body.data, dict) else {}
    saved = store.write_overview_data(pid, data)
    text = store.read_overview(pid)
    applied = None
    if getattr(body, "apply", False):
        try:
            applied = doc_fill.apply(pid)
        except Exception as exc:  # noqa: BLE001 - 반영 실패가 저장을 막지 않게
            applied = {"error": str(exc)[:200]}
    return {"data": saved, "text": text, "chars": len(text), "applied": applied}


@app.post("/api/projects/{pid}/budget/sync-stages")
def budget_sync_stages(pid: str):
    """8-1 지원·부담계획 표를 제반사항 단계 수에 맞춰 재구성(단계 블록 복제) 후 채운다.

    구조편집(순수복원→표 XML 조작→재추출)이라 수십 초 걸릴 수 있어 별도 버튼으로 호출한다."""
    _require_project(pid)
    rebuilt = None
    try:
        rebuilt = _sync_budget_stages(pid)
    except Exception as exc:  # noqa: BLE001 - 실패 시 원상복구됨(_apply_structural)
        raise HTTPException(status_code=500, detail=f"8.1 표 재구성 실패: {exc}") from exc
    applied = doc_fill.apply(pid)
    return {"rebuilt": rebuilt, "applied": applied}


def _sync_budget_stages(pid: str) -> dict:
    """8-1 지원·부담계획 표를 제반사항 periods 의 '단계 × 연차' 구조로 재구성한다.

    단계별 연차 수를 그대로 반영(연차2 이후에도 비율행 생성)한다."""
    from collections import defaultdict
    ov = store.read_overview_data(pid)
    by_stage: dict[str, int] = defaultdict(int)
    for p in (ov.get("periods") or []):
        by_stage[(p.get("stage") or "").strip() or "1"] += 1
    if not by_stage:
        return {"changed": False, "reason": "연차 없음"}
    stages_sorted = sorted(by_stage.keys(),
                           key=lambda s: int(s) if s.isdigit() else 999)
    counts = [by_stage[s] for s in stages_sorted]
    index = pipeline._all_nodes_by_path(pid)
    tpath = doc_fill._find_table(index, "기관부담연구개발비", "비율(A/E)", "현금(A)")
    if not tpath:
        return {"changed": False, "reason": "8-1 표 없음"}
    info = tables.rebuild_budget_stages(pid, tpath, counts)
    return {"changed": True, "stages": len(counts), "years": counts, **(info or {})}


@app.post("/api/projects/{pid}/budget/sync-detail")
def budget_sync_detail(pid: str):
    """8-3 비목별 세부표 개수를 참여기관 수에 맞춰 복제/제거 후 연구개발비 총액을 채운다.

    구조편집(순수복원→문단 복제→재추출)이라 수십 초 걸릴 수 있어 별도 버튼으로 호출한다."""
    _require_project(pid)
    rebuilt = None
    try:
        rebuilt = _sync_budget_detail(pid)
    except Exception as exc:  # noqa: BLE001 - 실패 시 원상복구됨(_apply_structural_doc)
        raise HTTPException(status_code=500, detail=f"8장 세부표 재구성 실패: {exc}") from exc
    applied = doc_fill.apply(pid)
    return {"rebuilt": rebuilt, "applied": applied}


def _sync_budget_detail(pid: str) -> dict:
    """8-3 세부표(수정인건비+간접비 비율 시그니처) 개수 = 참여기관 수(name 있는 것)."""
    ov = store.read_overview_data(pid)
    n = len([i for i in (ov.get("institutions") or []) if (i.get("name") or "").strip()])
    if n <= 0:
        return {"changed": False, "reason": "참여기관 없음"}
    index = pipeline._all_nodes_by_path(pid)
    paths = doc_fill._find_tables(index, "수정인건비", "간접비 비율", "연구개발비 총액")
    if not paths:
        return {"changed": False, "reason": "세부표 없음"}
    if len(paths) == n:
        return {"changed": False, "reason": "이미 일치", "count": n}
    info = tables.rebuild_budget_detail(pid, n, paths)
    return {"changed": True, "institutions": n, **(info or {})}


# ── 표지 자동채움: RFP 추출 / 기술분류 AI 제안 ───────────────────────────────
@app.post("/api/projects/{pid}/cover/autofill-rfp")
def cover_autofill_rfp(pid: str):
    """업로드된 RFP 에서 표지 상단 항목(중앙행정기관·전문기관·세부/내역사업명·공고번호) 추출."""
    _require_project(pid)
    rfp_text = store.read_rfp_text(pid)
    if not (rfp_text or "").strip():
        raise HTTPException(status_code=400, detail="RFP 가 업로드되지 않았습니다. 먼저 RFP 를 올려 주세요.")
    fields = claude_service.cover_autofill_rfp(rfp_text)
    return {"fields": fields}


@app.post("/api/projects/{pid}/cover/classify")
def cover_classify(pid: str):
    """과제 내용(표지/요약문 입력 + RFP 요지)으로 산업기술·국가과학기술 분류를 AI 제안."""
    _require_project(pid)
    ov = store.read_overview_data(pid)
    cov = ov.get("cover") or {}
    sm = ov.get("summary") or {}
    parts = [
        cov.get("title_ko") or "", cov.get("master_title_ko") or "",
        sm.get("goal_final") or "",
        " ".join((g.get("text") or "") for g in (sm.get("goals") or [])),
        store.read_overview(pid),
    ]
    rfp_text = store.read_rfp_text(pid)
    if rfp_text:
        parts.append("[RFP 요지]\n" + rfp_text[:4000])
    context = "\n".join(p for p in parts if (p or "").strip())
    if not context.strip():
        raise HTTPException(status_code=400,
                            detail="분류 근거가 없습니다. 과제명·목표를 먼저 입력하거나 RFP 를 올려 주세요.")
    fields = claude_service.cover_classify(context)
    return {"fields": fields}


@app.post("/api/projects/{pid}/summary/suggest")
def suggest_summary(pid: str):
    """요약문 '연구개발 목표 및 내용'(최종목표+연차별 목표·개발내용)을 AI 로 제안."""
    _require_project(pid)
    ov = store.read_overview_data(pid)
    cov = ov.get("cover") or {}
    years = [(p.get("year") or "").strip() for p in (ov.get("periods") or [])
             if (p.get("year") or "").strip()]
    parts = [cov.get("title_ko") or "", cov.get("master_title_ko") or "", store.read_overview(pid)]
    rfp_text = store.read_rfp_text(pid)
    if rfp_text:
        parts.append("[RFP]\n" + rfp_text[:6000])
    context = "\n".join(p for p in parts if (p or "").strip())
    if not context.strip():
        raise HTTPException(status_code=400,
                            detail="근거가 없습니다. 과제명을 입력하거나 RFP 를 올려 주세요.")
    return claude_service.summary_suggest(context, years)


@app.post("/api/projects/{pid}/cover/translate")
def cover_translate(pid: str, body: dict = Body(...)):
    """한국어 과제명 → 영어 제목(총괄과제명/과제명 영문 자동채움용)."""
    _require_project(pid)
    text = str((body or {}).get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="번역할 텍스트가 없습니다.")
    return {"en": claude_service.translate_title_ko_en(text)}


# ── 빌드/다운로드 ─────────────────────────────────────────────────────────────
def _iter_tree_nodes(tree: list[dict]):
    """트리를 깊이우선으로 순회(장·절 모두)."""
    for node in tree or []:
        yield node
        yield from _iter_tree_nodes(node.get("children") or [])


def _flush_pending_inputs(pid: str) -> int:
    """입력(input.md)만 채우고 아직 문서(yaml)에 반영하지 않은 절을 빌드 직전 자동 반영한다.

    result.yaml 이 이미 있는 절(=이미 변환/반영됨)은 건드리지 않는다. 초안 전체가
    유실 없이 들어가도록 segment_input_packed 를 쓴다. 반영한 절 수를 반환.
    """
    flushed = 0
    for node in _iter_tree_nodes(store.load_tree(pid)):
        nid = node.get("id")
        # 산문은 본문 필드(문단)에만 — 표 셀은 그리드 편집 전용이라 제외.
        node_paths = pipeline.body_paths(pid, node.get("node_paths", []) or [])
        if not nid or not node_paths:
            continue
        try:
            detail = store.read_node(pid, nid)
        except Exception:  # noqa: BLE001
            continue
        input_text = (detail.get("input") or "").strip()
        already = detail.get("result") or []
        if not input_text or already:
            continue
        try:
            result = claude_service.segment_input_packed(
                detail.get("input") or "", detail.get("template") or {}, node_paths
            )
            if result:
                store.write_result(pid, nid, result)
                pipeline.merge_result_into_yaml(pid, result)
                flushed += 1
        except Exception:  # noqa: BLE001 - 한 절 실패가 빌드 전체를 막지 않게
            continue
    return flushed


@app.post("/api/projects/{pid}/build")
async def build_project(pid: str):
    """yaml → final.hwpx(+preview.pdf). → {download,preview,flushed}

    빌드 직전, 입력만 채우고 아직 문서에 반영 안 한 절을 자동 반영한다(사용자가 절마다
    ④ 변환을 누르지 않아도 RFP 자동작성·채팅 초안이 최종 문서에 들어가도록).
    """
    meta = _require_project(pid)
    try:
        source_hwpx = meta.get("source_hwpx") or str(store.project_dir(pid) / "source.hwpx")
        out_dir = store.output_dir(pid)
        out_dir.mkdir(parents=True, exist_ok=True)
        final_hwpx = out_dir / "final.hwpx"

        flushed = _flush_pending_inputs(pid)
        doc_fill.apply(pid)  # 제반사항 → 표지·요약문·편성도 표 셀 자동 채움
        pipeline.restore(source_hwpx, store.yaml_dir(pid), final_hwpx)

        preview_url = ""
        pdf_ok = False
        try:
            pipeline.hwpx_to_pdf(final_hwpx, out_dir / "preview.pdf")
            pdf_ok = True
        except Exception:  # noqa: BLE001 - PDF 는 베스트에포트(한컴 COM 미가용 등)
            pdf_ok = False

        download_url = f"/api/projects/{pid}/download"
        if pdf_ok:
            preview_url = f"/api/projects/{pid}/preview.pdf"
        return {"download": download_url, "preview": preview_url, "flushed": flushed}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"빌드 실패: {exc}") from exc


@app.get("/api/projects/{pid}/download")
async def download_final(pid: str):
    _require_project(pid)
    final_hwpx = store.output_dir(pid) / "final.hwpx"
    if not final_hwpx.exists():
        raise HTTPException(status_code=404, detail="빌드 산출물(final.hwpx)이 없습니다. 먼저 빌드하세요.")
    return FileResponse(
        str(final_hwpx),
        media_type="application/octet-stream",
        filename="연구개발계획서.hwpx",
    )


@app.get("/api/projects/{pid}/nodes/{nid}/section.hwpx")
def download_section_hwpx(pid: str, nid: str):
    """④ 변환 패널에서 호출: 현재 YAML 상태(해당 절 변환분 포함)를 hwpx 로 즉시 복원해 다운로드.
    문서는 전체 오버레이라 산출물은 현 YAML을 반영한 전체 문서 hwpx 다(해당 절 변환분 포함)."""
    meta = _require_project(pid)
    _node_or_404(pid, nid)
    try:
        source_hwpx = meta.get("source_hwpx") or str(store.project_dir(pid) / "source.hwpx")
        out_dir = store.output_dir(pid)
        out_dir.mkdir(parents=True, exist_ok=True)
        final_hwpx = out_dir / "final.hwpx"
        _flush_pending_inputs(pid)
        doc_fill.apply(pid)  # 제반사항 → 표지·요약문·편성도 표 셀 자동 채움
        pipeline.restore(source_hwpx, store.yaml_dir(pid), final_hwpx)
        return FileResponse(
            str(final_hwpx),
            media_type="application/octet-stream",
            filename="연구개발계획서.hwpx",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"hwpx 변환 실패: {exc}") from exc


@app.get("/api/projects/{pid}/preview.pdf")
async def preview_pdf(pid: str):
    _require_project(pid)
    pdf = store.output_dir(pid) / "preview.pdf"
    if not pdf.exists():
        raise HTTPException(status_code=404, detail="미리보기(preview.pdf)가 없습니다.")
    return FileResponse(str(pdf), media_type="application/pdf", filename="preview.pdf")


# ── 헬스체크(선택) ────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return JSONResponse({"ok": True})


# ── 정적 프론트 마운트('/' 는 항상 마지막) ────────────────────────────────────
class _NoCacheStatic(StaticFiles):
    """프론트 정적 파일(index.html/app.js/styles.css)을 매번 재검증하게 한다.

    배포(코드 갱신) 후 브라우저가 옛 app.js/index.html 을 캐시해 새 DOM 과 어긋나면
    '노드 로드 실패' 같은 예외가 난다. no-store 로 캐시를 막아 항상 최신을 받게 한다.
    """

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        return resp


if FRONTEND_DIR.exists():
    app.mount("/", _NoCacheStatic(directory=str(FRONTEND_DIR), html=True), name="frontend")
