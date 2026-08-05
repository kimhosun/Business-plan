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

from . import claude_service, config, pipeline, presets, regulations, store, tables
from .schemas import (
    ChatBody,
    GenerateBody,
    InputBody,
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


@app.get("/api/projects/{pid}/tree")
async def get_tree(pid: str):
    _require_project(pid)
    return store.load_tree(pid)


# ── 노드 ──────────────────────────────────────────────────────────────────────
@app.get("/api/projects/{pid}/nodes/{nid}")
async def get_node(pid: str, nid: str):
    _require_project(pid)
    try:
        return store.read_node(pid, nid)
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
    prompts = {"style": body.style or "", "structure": body.structure or ""}
    if body.guidelines is not None:
        prompts["guidelines"] = body.guidelines
    saved = store.write_prompts(pid, nid, prompts)
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
            "label": detail.get("label", ""),
            "title": detail.get("title", ""),
            "guidelines": detail.get("guidelines") or [],
            "template": detail.get("template") or {},
            "prompts": detail.get("prompts") or {},
            "input": detail.get("input") or "",
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
        targets = list(node.get("node_paths", []) or [])
        template = detail.get("template") or {}
        prompts = detail.get("prompts") or {}
        input_text = detail.get("input") or ""

        # 병합 전 현재 yaml 본문(before) 스냅샷
        before_index = pipeline._all_nodes_by_path(pid)

        result = claude_service.convert_input(input_text, template, prompts, targets)

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


# ── 빌드/다운로드 ─────────────────────────────────────────────────────────────
@app.post("/api/projects/{pid}/build")
async def build_project(pid: str):
    """yaml → final.hwpx(+preview.pdf). → {download,preview}"""
    meta = _require_project(pid)
    try:
        source_hwpx = meta.get("source_hwpx") or str(store.project_dir(pid) / "source.hwpx")
        out_dir = store.output_dir(pid)
        out_dir.mkdir(parents=True, exist_ok=True)
        final_hwpx = out_dir / "final.hwpx"

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
        return {"download": download_url, "preview": preview_url}
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
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
