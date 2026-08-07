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

from . import claude_service, config, pipeline, presets, regulations, rfp, store, tables
from .schemas import (
    ChatBody,
    GenerateBody,
    InputBody,
    PromptsBody,
    RfpAutofillBody,
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
        # 변환도 산문을 본문 필드(문단)에만 쓴다 — 표 셀은 그리드 편집 전용.
        targets = pipeline.body_paths(pid, node.get("node_paths", []) or [])
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


# ── RFP(제안요청서/공고) 업로드 → 절 자동작성 ────────────────────────────────
@app.get("/api/projects/{pid}/rfp")
async def get_rfp(pid: str):
    """업로드된 RFP 메타(파일명·글자수·업로드시각)와 기본 대상 절 목록."""
    _require_project(pid)
    meta = store.rfp_meta(pid) or {}
    return {"meta": meta, "sections": rfp.TARGET_SECTIONS}


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
    return {"filename": filename, "chars": meta.get("chars", len(text)), "sections": rfp.TARGET_SECTIONS}


@app.post("/api/projects/{pid}/rfp/autofill")
def autofill_rfp(pid: str, body: RfpAutofillBody):
    """업로드된 RFP 로 지정 절들을 병렬 자동작성해 input.md 에 채운다.

    body {sections?, apply} · apply 면 yaml 병합까지. → {results:[{nid,title,ok,chars,applied,error}]}

    절마다 Claude 초안을 동시에 생성하므로 sync 라우트(스레드풀)로 둔다.
    """
    _require_project(pid)
    text = store.read_rfp_text(pid)
    if not text.strip():
        raise HTTPException(status_code=400, detail="먼저 RFP 를 업로드하세요.")
    try:
        results = rfp.autofill(
            pid, text, sections=body.sections, apply_yaml=bool(body.apply)
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"자동작성 실패: {exc}") from exc
    ok = sum(1 for r in results if r.get("ok"))
    return {"results": results, "ok_count": ok, "total": len(results)}


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
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
