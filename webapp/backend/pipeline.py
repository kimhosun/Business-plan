#!/usr/bin/env python3
"""backend/pipeline.py — hwpx-yaml-roundtrip 스킬 CLI 래핑 + 헬퍼.

- convert(src,dst)                     : hwp2hwpx.py convert
- extract(hwpx,out_dir)                : hwpx2yaml.py extract
- restore(hwpx,yaml_dir,out,template)  : yaml2hwpx.py restore
- hwpx_to_pdf(hwpx,pdf)                : pyhwpx (Hancom COM, guarded)
- default_template_from_hwpx(pid,nid)  : 해당 절 기존 마커/번호·표 양식 → template dict
- merge_result_into_yaml(pid,result)   : [{path,marker,text}] → yaml/section_*.yaml 병합

CLI 는 cwd=SKILL_SCRIPTS 로 호출한다(hwpx_common 형제 모듈 import 보장).
"""
from __future__ import annotations

import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from . import config


# ── 공용: 서브프로세스 실행 ───────────────────────────────────────────────────
def _run(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    """SKILL_SCRIPTS 디렉터리에서 파이썬 CLI 실행. 실패 시 RuntimeError."""
    cmd = [config.PYTHON, *args]
    proc = subprocess.run(
        cmd,
        cwd=str(config.SKILL_SCRIPTS),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"pipeline command failed (rc={proc.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def _script(name: str) -> str:
    return str(config.SKILL_SCRIPTS / name)


# ── CLI 래퍼 ──────────────────────────────────────────────────────────────────
def convert(src: str | Path, dst: str | Path) -> str:
    """.hwp/.hwpx → .hwpx (hwp2hwpx.py convert). 산출 경로(str) 반환."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run([_script("hwp2hwpx.py"), "convert", "--in", str(src), "--out", str(dst)])
    return str(dst)


def extract(hwpx: str | Path, out_dir: str | Path) -> str:
    """hwpx → yaml/section_*.yaml (+_manifest.yaml). 출력 dir(str) 반환."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _run([_script("hwpx2yaml.py"), "extract", "--in", str(hwpx), "--out-dir", str(out_dir)])
    return str(out_dir)


def restore(
    hwpx: str | Path,
    yaml_dir: str | Path,
    out: str | Path,
    template_path: str | Path | None = None,
) -> str:
    """채워진 yaml 을 원본 hwpx 에 오버레이 → 최종 hwpx (yaml2hwpx.py restore)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    args = [
        _script("yaml2hwpx.py"), "restore",
        "--hwpx", str(hwpx),
        "--yaml-dir", str(yaml_dir),
        "--out", str(out),
    ]
    if template_path:
        args += ["--template", str(template_path)]
    # 최종 문서 글꼴 강제: 본문=돋움 12pt, 표 셀=돋움 8pt (환경변수로 조정 가능).
    env = dict(os.environ)
    env.setdefault("HWPX_APPLY_FONTS", "1")
    env.setdefault("HWPX_FONT", "돋움")
    env.setdefault("HWPX_BODY_PT", "12")
    env.setdefault("HWPX_CELL_PT", "8")
    # 개조식 문단 마커(□·○·- 등) 기준 자동 내어쓰기
    env.setdefault("HWPX_HANGING_INDENT", "1")
    # 마크다운 표(| a | b |) → 실제 HWPX 표
    env.setdefault("HWPX_MD_TABLES", "1")
    _run(args, env=env)
    return str(out)


def _hancom_running() -> bool:
    """한컴(HwpObject)이 이미 실행 중인지 Running Object Table 로 확인한다.

    pyhwpx 의 부착(attach) 판정과 동일 기준(`!HwpObject.` 모니커). True 면 pyhwpx 가
    사용자의 실행 중 인스턴스에 붙으므로, 자동화가 앱을 종료(Quit)하면 사용자가 열어둔
    한글/PDF 창까지 닫힌다 → 이 경우 우리가 연 문서만 닫아야 한다(_shutdown_hwp 참조).
    """
    try:
        import pythoncom  # pywin32 (pyhwpx 의존성)

        ctx = pythoncom.CreateBindCtx(0)
        rot = pythoncom.GetRunningObjectTable()
        for mon in rot.EnumRunning():
            try:
                name = mon.GetDisplayName(ctx, mon)
            except Exception:  # noqa: BLE001
                continue
            if name.startswith("!HwpObject."):
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _shutdown_hwp(h, pre_running: bool) -> None:
    """자동화 뒤처리 — 사용자가 열어둔 한글 창을 닫지 않도록 조건부 종료.

    pre_running 이면 우리가 연 활성 문서만 close(앱 유지), 아니면 우리가 띄운 앱을 quit.
    """
    if h is None:
        return
    try:
        if pre_running:
            h.close(is_dirty=False)
        else:
            h.quit(save=False)
    except Exception:  # noqa: BLE001
        pass


def hwpx_to_pdf(hwpx: str | Path, pdf: str | Path) -> str:
    """hwpx → pdf (pyhwpx/Hancom COM). pyhwpx 미설치/실패는 RuntimeError.

    사용자가 한글을 이미 열어둔 경우 그 인스턴스에 붙게 되므로, 작업 후 앱을 종료하지
    않고 우리가 연 문서만 닫는다(사용자 창 보존).
    """
    hwpx = str(Path(hwpx).resolve())
    pdf = Path(pdf)
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf_abs = str(pdf.resolve())
    try:
        from pyhwpx import Hwp
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"pyhwpx import 실패: {exc}") from exc

    h = None
    pre_running = _hancom_running()
    try:
        # 사용자 인스턴스에 붙을 땐 visible=True(그의 활성 창이 숨겨지지 않도록),
        # 우리가 새로 띄울 땐 visible=False(헤드리스, 창 팝업 없음).
        h = Hwp(visible=pre_running)
        h.open(hwpx)
        ok = h.save_as(pdf_abs, format="PDF")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"hwpx_to_pdf 실패: {exc}") from exc
    finally:
        _shutdown_hwp(h, pre_running)
    if not ok or not pdf.exists():
        raise RuntimeError(f"hwpx_to_pdf: PDF 미생성 (ok={ok}, out={pdf_abs})")
    return pdf_abs


# ── yaml 노드 접근 헬퍼 ───────────────────────────────────────────────────────
def _yaml_dir(pid: str) -> Path:
    return config.PROJECTS_DIR / pid / "yaml"


def _section_files(yaml_dir: Path) -> list[Path]:
    return sorted(
        p for p in yaml_dir.glob("section_*.yaml") if p.name != "_manifest.yaml"
    )


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _dump_yaml(data: Any, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(
            data, fh, allow_unicode=True, sort_keys=False, default_flow_style=False
        )


def _all_nodes_by_path(pid: str) -> dict[str, dict]:
    """프로젝트의 모든 yaml 노드를 path→node dict 로 인덱싱."""
    index: dict[str, dict] = {}
    for f in _section_files(_yaml_dir(pid)):
        data = _load_yaml(f)
        for n in data.get("nodes", []):
            p = n.get("path")
            if p:
                index[p] = n
    return index


def body_paths(pid: str, node_paths, index: dict | None = None) -> list[str]:
    """node_paths 중 **순수 본문 문단(kind=para)** 만 남긴다.

    다음을 제외한다.
    - 표 셀(cell_para): 산문은 '본문 필드'에 쓰고 표는 그리드 편집으로만 채운다.
    - 표를 품은 문단(sX/pY 아래 sX/pY/tZ 표 노드가 있는 경우): 여기에 긴 본문을 채우면
      표와 텍스트가 한 문단에 섞여 깨진다 → 대상에서 뺀다.
    판정 불가(인덱스에 없는) path 는 보수적으로 본문으로 취급한다.
    """
    idx = index if index is not None else _all_nodes_by_path(pid)
    # 표를 품은 문단 path 집합(표 노드 path 에서 마지막 '/tN' 제거)
    hosts: set[str] = set()
    for p, n in idx.items():
        if n.get("kind") == "table":
            hosts.add(re.sub(r"/t\d+$", "", p))
    out = []
    for p in (node_paths or []):
        n = idx.get(p)
        if (n is None or n.get("kind") == "para") and p not in hosts:
            out.append(p)
    return out


_NUMERIC_RE = re.compile(r"\d")


# ── default_template_from_hwpx ────────────────────────────────────────────────
def default_template_from_hwpx(pid: str, nid: str) -> dict:
    """해당 노드(nid)의 node_paths 를 yaml 에서 읽어, 기존 마커/번호·표 양식을
    추정한 hwpx-yaml-template/1.0 dict 를 만든다.

    - 레벨별로 등장한 선두 마커를 모아 대표값을 뽑는다.
    - 대표 마커가 숫자를 포함하면 '번호식'(numbering) 기본을, 아니면 '마커식'
      (markers)을 채택한다. 표는 header_rows=1.
    """
    from . import store  # 지연 임포트(순환 방지)

    node = store.node_by_id(pid, nid)
    node_paths = list((node or {}).get("node_paths", []))
    index = _all_nodes_by_path(pid)

    level_markers: dict[int, Counter] = {}
    for p in node_paths:
        yn = index.get(p)
        if not yn or yn.get("kind") not in ("para", "cell_para"):
            continue
        marker = (yn.get("marker") or "").strip()
        if not marker:
            continue
        level = int(yn.get("level", 1) or 1)
        level_markers.setdefault(level, Counter())[marker] += 1

    # 레벨별 대표 마커
    rep: dict[int, str] = {
        lvl: cnt.most_common(1)[0][0] for lvl, cnt in level_markers.items()
    }
    numeric_votes = sum(1 for m in rep.values() if _NUMERIC_RE.search(m))
    symbol_votes = len(rep) - numeric_votes

    tpl: dict[str, Any] = {"schema": "hwpx-yaml-template/1.0"}

    if rep and numeric_votes >= symbol_votes and numeric_votes > 0:
        # 번호식 기본(표준 개요 번호)
        tpl["numbering"] = {
            "level1": "{n}.",
            "level2": "{p}.{n}",
            "level3": "{p}.{n}",
        }
    else:
        # 마커식: 감지된 대표 마커를 레벨별로, 없으면 표준 기본
        defaults = {1: "□", 2: "○", 3: "-"}
        markers: dict[str, str] = {}
        for lvl in (1, 2, 3):
            markers[f"level{lvl}"] = rep.get(lvl) or defaults[lvl]
        tpl["markers"] = markers

    tpl["strip_existing"] = True
    tpl["table"] = {
        "header_rows": 1,
        "header_marker": "",
        "cell_bullet": "",
        "apply_to_cells": False,
    }
    return tpl


# ── merge_result_into_yaml ────────────────────────────────────────────────────
def merge_result_into_yaml(pid: str, result: list[dict]) -> dict:
    """result = [{path,marker,text}] 를 yaml/section_*.yaml 의 같은 path 노드에
    기록(marker/text 갱신)하고 저장한다. 변경 통계 dict 반환."""
    by_path: dict[str, dict] = {}
    for r in result or []:
        p = r.get("path")
        if p:
            by_path[p] = r

    yaml_dir = _yaml_dir(pid)
    updated = 0
    changed_files = 0
    for f in _section_files(yaml_dir):
        data = _load_yaml(f)
        dirty = False
        for n in data.get("nodes", []):
            p = n.get("path")
            if p in by_path:
                r = by_path[p]
                if "marker" in r:
                    n["marker"] = r.get("marker", "") or ""
                n["text"] = r.get("text", "") or ""
                dirty = True
                updated += 1
        if dirty:
            _dump_yaml(data, f)
            changed_files += 1
    return {"updated": updated, "files": changed_files}
