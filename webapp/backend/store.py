#!/usr/bin/env python3
"""backend/store.py — 프로젝트/노드 파일 CRUD (ARCHITECTURE '파일 저장 구조').

저장 레이아웃:
  data/projects/<pid>/
    project.json           # {id,name,source_hwpx,source_sha256,created}
    source.hwpx            # 서식 원천
    yaml/section_*.yaml    # 추출본(+_manifest.yaml). 변환결과가 여기 병합됨
    tree.json              # build_tree 결과(좌측 메뉴)
    nodes/<nid>/
      template.yaml        # hwpx-yaml-template/1.0
      prompts.json         # {style,structure,guidelines}
      input.md             # 사용자 원문
      result.yaml          # [{path,marker,text}]
      chat.json            # 작성 채팅 이력 [{role,content,at}]
    output/final.hwpx, output/preview.pdf

파일 IO 는 모두 UTF-8. YAML 은 allow_unicode=True, sort_keys=False.
template/result = YAML, prompts/project/tree = JSON.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import config, pipeline, presets
from .tree import build_tree


# ── 저수준 IO ────────────────────────────────────────────────────────────────
def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(
            data, fh, allow_unicode=True, sort_keys=False, default_flow_style=False
        )


def _read_text(path: Path, default: str = "") -> str:
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else "", encoding="utf-8")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 경로 헬퍼 ────────────────────────────────────────────────────────────────
def project_dir(pid: str) -> Path:
    return config.PROJECTS_DIR / pid


def yaml_dir(pid: str) -> Path:
    return project_dir(pid) / "yaml"


def nodes_dir(pid: str) -> Path:
    return project_dir(pid) / "nodes"


def node_dir(pid: str, nid: str) -> Path:
    return nodes_dir(pid) / nid


def output_dir(pid: str) -> Path:
    return project_dir(pid) / "output"


def rfp_dir(pid: str) -> Path:
    return project_dir(pid) / "rfp"


def _project_json(pid: str) -> Path:
    return project_dir(pid) / "project.json"


def _tree_json(pid: str) -> Path:
    return project_dir(pid) / "tree.json"


# ── 프로젝트 생성/목록 ────────────────────────────────────────────────────────
def new_project(name: str | None, source_hwp_path: str | Path) -> str:
    """원본(.hwp/.hwpx)에서 프로젝트를 생성한다.

    저장 → convert(source.hwpx) → extract(yaml/) → build_tree(tree.json) →
    project.json 기록. 생성된 pid(uuid hex 8) 반환.
    """
    src = Path(source_hwp_path)
    if not src.exists():
        raise FileNotFoundError(f"source not found: {src}")

    pid = uuid.uuid4().hex[:8]
    pdir = project_dir(pid)
    pdir.mkdir(parents=True, exist_ok=True)

    # 1) 원본 → source.hwpx (이미 hwpx면 복사, hwp면 COM 변환)
    source_hwpx = pdir / "source.hwpx"
    pipeline.convert(src, source_hwpx)

    # 2) 추출 → yaml/
    ydir = yaml_dir(pid)
    pipeline.extract(source_hwpx, ydir)

    # 3) 트리 → tree.json
    tree = build_tree(str(ydir))
    _write_json(_tree_json(pid), tree)

    # 4) project.json
    _write_json(
        _project_json(pid),
        {
            "id": pid,
            "name": name or src.stem,
            "source_hwpx": str(source_hwpx),
            "source_sha256": _sha256(source_hwpx),
            "created": _now(),
        },
    )
    return pid


def list_projects() -> list[dict]:
    """[{id,name,created}] (created 역순)."""
    out: list[dict] = []
    if not config.PROJECTS_DIR.exists():
        return out
    for pdir in config.PROJECTS_DIR.iterdir():
        if not pdir.is_dir():
            continue
        meta = _read_json(pdir / "project.json")
        if not meta:
            continue
        out.append(
            {
                "id": meta.get("id", pdir.name),
                "name": meta.get("name", pdir.name),
                "created": meta.get("created", ""),
            }
        )
    out.sort(key=lambda m: m.get("created", ""), reverse=True)
    return out


def project_meta(pid: str) -> dict | None:
    return _read_json(_project_json(pid))


def delete_project(pid: str) -> bool:
    """프로젝트 디렉터리 전체(yaml·nodes·output·rfp 등)를 삭제한다.

    pid 검증: PROJECTS_DIR 하위의 실제 디렉터리만 지운다(경로 탈출 방지).
    """
    pdir = project_dir(pid)
    try:
        # PROJECTS_DIR 바로 아래의 디렉터리인지 확인(../ 등 경로 조작 차단)
        pdir.resolve().relative_to(config.PROJECTS_DIR.resolve())
    except (ValueError, OSError):
        return False
    if not pdir.is_dir():
        return False
    shutil.rmtree(pdir, ignore_errors=True)
    return not pdir.exists()


# ── 트리 접근 ────────────────────────────────────────────────────────────────
def load_tree(pid: str) -> list[dict]:
    return _read_json(_tree_json(pid), default=[]) or []


def _find_in_tree(tree: list[dict], nid: str) -> dict | None:
    for node in tree:
        if node.get("id") == nid:
            return node
        child = _find_in_tree(node.get("children", []) or [], nid)
        if child is not None:
            return child
    return None


def node_by_id(tree_or_pid: Any, nid: str) -> dict | None:
    """트리(list) 또는 pid(str) 로 노드를 찾는다.

    ARCHITECTURE 는 node_by_id(tree,nid), 태스크는 node_by_id(pid,nid) 를 요구하므로
    둘 다 허용한다.
    """
    tree = load_tree(tree_or_pid) if isinstance(tree_or_pid, str) else tree_or_pid
    return _find_in_tree(tree or [], nid)


# ── 노드 파일 경로 ────────────────────────────────────────────────────────────
def _template_path(pid: str, nid: str) -> Path:
    return node_dir(pid, nid) / "template.yaml"


def _prompts_path(pid: str, nid: str) -> Path:
    return node_dir(pid, nid) / "prompts.json"


def _input_path(pid: str, nid: str) -> Path:
    return node_dir(pid, nid) / "input.md"


def _result_path(pid: str, nid: str) -> Path:
    return node_dir(pid, nid) / "result.yaml"


def _chat_path(pid: str, nid: str) -> Path:
    return node_dir(pid, nid) / "chat.json"


# ── 노드 읽기(기본값 생성) ────────────────────────────────────────────────────
def read_node(pid: str, nid: str) -> dict:
    """노드 상세를 반환. 없는 값은 기본값을 만들어 저장한 뒤 반환한다.

    반환 dict 키: id,label,title,guidelines,template,prompts,input,result,node_count
    """
    node = node_by_id(pid, nid)
    if node is None:
        raise KeyError(f"node not found: pid={pid}, nid={nid}")

    guidelines = list(node.get("guidelines", []) or [])
    node_paths = list(node.get("node_paths", []) or [])

    # template.yaml — 없으면 hwpx 추출 기본 템플릿
    tpath = _template_path(pid, nid)
    template = _read_yaml(tpath)
    if template is None:
        template = pipeline.default_template_from_hwpx(pid, nid)
        _write_yaml(tpath, template)

    # prompts.json — 없으면 참조 사업계획서(rnd-write-*) 문체·구성 프리셋으로 프리필
    ppath = _prompts_path(pid, nid)
    prompts = _read_json(ppath)
    preset = presets.preset_for(nid)
    if prompts is None:
        prompts = {
            "style": preset.get("style", ""),
            "structure": preset.get("structure", ""),
            "guidelines": guidelines,
            "preset_skill": preset.get("skill", ""),
        }
        _write_json(ppath, prompts)

    # input.md — 없으면 ""
    ipath = _input_path(pid, nid)
    input_text = _read_text(ipath) if ipath.exists() else ""

    # result.yaml — 없으면 []
    rpath = _result_path(pid, nid)
    result = _read_yaml(rpath)
    if result is None:
        result = []

    return {
        "id": node.get("id", nid),
        "label": node.get("label", ""),
        "title": node.get("title", ""),
        "guidelines": guidelines,
        "template": template,
        "prompts": prompts,
        "input": input_text,
        "result": result,
        "chat": read_chat(pid, nid),
        "node_count": len(node_paths),
        "preset": preset,
    }


def read_chat(pid: str, nid: str) -> list[dict]:
    """작성 채팅 이력 [{role, content, at}] (없으면 [])."""
    return _read_json(_chat_path(pid, nid), default=[]) or []


# ── 노드 쓰기 ────────────────────────────────────────────────────────────────
def write_template(pid: str, nid: str, template: dict) -> dict:
    _write_yaml(_template_path(pid, nid), template)
    return template


def write_prompts(pid: str, nid: str, prompts: dict) -> dict:
    """prompts 저장. guidelines 가 없으면 트리 노드의 가이드로 보완."""
    prompts = dict(prompts or {})
    if "guidelines" not in prompts:
        node = node_by_id(pid, nid)
        prompts["guidelines"] = list((node or {}).get("guidelines", []) or [])
    _write_json(_prompts_path(pid, nid), prompts)
    return prompts


def write_input(pid: str, nid: str, input_text: str) -> str:
    _write_text(_input_path(pid, nid), input_text or "")
    return input_text or ""


def write_result(pid: str, nid: str, result: list[dict]) -> list[dict]:
    _write_yaml(_result_path(pid, nid), result or [])
    return result or []


def append_chat(pid: str, nid: str, role: str, content: str) -> list[dict]:
    """채팅 한 턴을 이력 끝에 붙이고 전체 이력을 반환."""
    chat = read_chat(pid, nid)
    chat.append({"role": role, "content": content or "", "at": _now()})
    _write_json(_chat_path(pid, nid), chat)
    return chat


def clear_chat(pid: str, nid: str) -> list[dict]:
    _write_json(_chat_path(pid, nid), [])
    return []


# ── RFP(제안요청서/공고) 저장 ─────────────────────────────────────────────────
def _rfp_source_path(pid: str, ext: str) -> Path:
    return rfp_dir(pid) / f"source{ext or ''}"


def _rfp_text_path(pid: str) -> Path:
    return rfp_dir(pid) / "rfp.txt"


def _rfp_meta_path(pid: str) -> Path:
    return rfp_dir(pid) / "meta.json"


def save_rfp(pid: str, filename: str, data: bytes) -> Path:
    """업로드한 RFP 원본 바이트를 rfp/source.<ext> 로 저장하고 경로를 반환."""
    ext = Path(filename or "").suffix.lower() or ".bin"
    d = rfp_dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    # 이전 원본(확장자 다른 경우)은 정리해 하나만 유지
    for old in d.glob("source.*"):
        try:
            old.unlink()
        except OSError:
            pass
    dst = _rfp_source_path(pid, ext)
    dst.write_bytes(data or b"")
    return dst


def write_rfp_text(pid: str, text: str, meta: dict) -> dict:
    """추출한 RFP 텍스트와 메타(파일명·글자수·업로드시각)를 저장하고 메타를 반환."""
    _write_text(_rfp_text_path(pid), text or "")
    meta = dict(meta or {})
    meta.setdefault("uploaded", _now())
    meta["chars"] = len(text or "")
    _write_json(_rfp_meta_path(pid), meta)
    return meta


def read_rfp_text(pid: str) -> str:
    return _read_text(_rfp_text_path(pid), default="")


def rfp_meta(pid: str) -> dict | None:
    return _read_json(_rfp_meta_path(pid))


# ── __main__ 스모크 테스트 ────────────────────────────────────────────────────
def _smoke() -> int:
    print(f"[smoke] DEFAULT_HWP = {config.DEFAULT_HWP}")
    print("[smoke] creating project from DEFAULT (hwp->hwpx COM 변환은 다소 걸릴 수 있음)...")
    pid = new_project("smoke", config.DEFAULT_HWP)
    pdir = project_dir(pid)
    tree = load_tree(pid)
    n_chap = len(tree)
    n_sec = sum(len(c.get("children", [])) for c in tree)

    yaml_ok = yaml_dir(pid).is_dir() and any(yaml_dir(pid).glob("section_*.yaml"))
    tree_ok = _tree_json(pid).exists()

    print(f"[smoke] pid = {pid}")
    print(f"[smoke] project_dir = {pdir}")
    print(f"[smoke] yaml/ exists+section files: {yaml_ok}")
    print(f"[smoke] tree.json exists: {tree_ok}")
    print(f"[smoke] tree: {n_chap} chapters, {n_sec} sections")

    # read_node 로 기본값 생성까지 확인
    if tree:
        first = tree[0]
        target = (first.get("children") or [first])[0]
        nid = target["id"]
        detail = read_node(pid, nid)
        print(f"[smoke] read_node({nid}): title={detail['title']!r}, "
              f"node_count={detail['node_count']}, "
              f"template_keys={list(detail['template'].keys())}")
        node_files_ok = (
            _template_path(pid, nid).exists() and _prompts_path(pid, nid).exists()
        )
        print(f"[smoke] node default files written: {node_files_ok}")
    else:
        node_files_ok = False

    ok = yaml_ok and tree_ok and n_chap > 0 and node_files_ok
    print(f"[smoke] RESULT: {'PASS' if ok else 'FAIL'}  pid={pid}")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(_smoke())
