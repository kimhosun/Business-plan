#!/usr/bin/env python3
"""backend/regulations.py — 절별 '작성 규정' 묶음 + PDF 생성.

웹 UI 상단 우측 [작성 규정 PDF] 버튼이 부르는 모듈. 해당 절(nid)을 쓸 때
적용해야 할 규정을 한 장의 PDF 로 모아 보여준다.

수록 순서
  1. 서식 자체의 작성요령(※)      — 원본 hwpx 에서 추출된 node.guidelines
  2. 이 절의 골격·변형·문체 지침   — _지침/지침.json 의 files[절_*.md].directives
  3. 체크리스트                    — 같은 JSON 의 checklist
  4. 이 절이 참조하는 공통원칙 §   — common_refs 에 해당하는 §의 전문
  5. 공통 작성 원칙 §0~§9 요약     — 전 절 공통
  6. 심화 지침(수동 편집 영역)     — .지침.md 의 sync 보존 구간
  7. 출처(원본 확인)               — 원본 md / 지침 md / JSON 경로·sha256, 서식 경로

7번이 있어 UI ② '작성 프롬프트' 칸의 요약 문구가 어느 원본에서 왔는지 나중에
추적·확인할 수 있다(프롬프트 조립은 presets.preset_for 가 같은 JSON 을 쓴다).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

from . import config, presets

# ── 원천 경로 ────────────────────────────────────────────────────────────────
REF_DIR = (
    config.ROOT_DIR / ".claude" / "skills" / "rnd-proposal-writer" / "references"
)
GUIDE_DIR = REF_DIR / "_지침"
GUIDE_JSON = GUIDE_DIR / "지침.json"
COMMON_SRC = "00_공통_작성원칙.md"

# 절별 적용 법령·규정 데이터셋(웹검증 큐레이션). regulations.py 옆.
REGDATA_JSON = Path(__file__).with_name("regulations_data.json")

# 공통원칙 §번호 → 지침 파일 안 section 라벨("§1. 문체·종결형") 매칭용
_SEC_RE = re.compile(r"^(§\d+)")


# ── 지침 로딩 ────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _guide() -> dict:
    try:
        return json.loads(GUIDE_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 지침 자산이 없어도 서비스는 살아있어야 함
        return {}


def _regdata() -> dict:
    """절별 적용 법령·규정 데이터셋(웹검증 큐레이션). 매 호출 시 파일을 다시 읽어
    재검증(refresh)으로 갱신된 최신본이 캐시 없이 반영되게 한다."""
    try:
        return json.loads(REGDATA_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 데이터셋이 없어도 서비스는 살아있어야 함
        return {}


def _guide_md_path(src_name: str) -> Path:
    """원본 md 파일명 → 자동 생성 지침 md 경로(절_X.md → 절_X.지침.md)."""
    return GUIDE_DIR / (Path(src_name).stem + ".지침.md")


def _deep_guidelines(src_name: str) -> list[str]:
    """.지침.md 의 '심화 지침(수동·에이전트 편집 영역)' 본문 줄들."""
    path = _guide_md_path(src_name)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    idx = text.find("## 심화 지침")
    if idx < 0:
        return []
    body = text[idx:].split("\n", 1)[1] if "\n" in text[idx:] else ""
    out = []
    for ln in body.splitlines():
        s = ln.strip()
        if not s or s.startswith("<!--"):
            continue
        out.append(re.sub(r"^[-*]\s+", "", s))
    return out


def _grouped(directives: list, only: set[str] | None = None) -> list[tuple[str, list[str]]]:
    """directives 를 section 라벨 기준으로 등장 순서대로 묶는다."""
    order: list[str] = []
    buckets: dict[str, list[str]] = {}
    for d in directives or []:
        if isinstance(d, dict):
            sec = (d.get("section") or "").strip()
            txt = (d.get("text") or "").strip()
        else:
            sec, txt = "", str(d).strip()
        if not txt:
            continue
        if only is not None:
            m = _SEC_RE.match(sec)
            if not m or m.group(1) not in only:
                continue
        if sec not in buckets:
            buckets[sec] = []
            order.append(sec)
        buckets[sec].append(txt)
    return [(s, buckets[s]) for s in order]


def regulation_for(nid: str, node: dict | None = None) -> dict:
    """절 nid 에 적용되는 규정 묶음(구조화). 지침을 못 찾아도 빈 값으로 응답."""
    guide = _guide()
    files = guide.get("files", {})
    src_name = presets.file_for(nid) or ""
    entry = files.get(src_name, {}) if src_name else {}
    common_entry = files.get(COMMON_SRC, {})

    refs = [r for r in (entry.get("common_refs") or []) if _SEC_RE.match(r)]
    common_sections = guide.get("common_principles", {}).get("sections", []) or []

    # 절별 적용 법령·규정(공통 + 절 특유). 데이터셋이 없으면 빈 목록.
    regdata = _regdata()
    sec_reg = (regdata.get("sections", {}) or {}).get(nid, {}) or {}
    laws = list(regdata.get("common", []) or []) + list(sec_reg.get("regulations", []) or [])

    node = node or {}
    return {
        "nid": nid,
        "label": node.get("label", "") or nid.replace("-", "."),
        "node_title": node.get("title", ""),
        # 적용 법령·규정(웹검증 큐레이션)
        "laws": laws,
        "law_notes": sec_reg.get("notes", ""),
        "reg_as_of": regdata.get("as_of", ""),
        "reg_business": regdata.get("business", ""),
        "reg_disclaimer": regdata.get("disclaimer", ""),
        # 지침 원천
        "title": entry.get("title", ""),
        "skill": entry.get("skill", "") or presets.skill_for(nid),
        "applies_to": entry.get("applies_to", ""),
        "role": entry.get("role", ""),
        # 본문
        "form_guidelines": list(node.get("guidelines") or []),
        "sections": _grouped(entry.get("directives") or []),
        "checklist": [
            c if isinstance(c, str) else (c.get("text") or "")
            for c in (entry.get("checklist") or [])
        ],
        "common_refs": refs,
        "common_ref_sections": _grouped(common_entry.get("directives") or [], set(refs)),
        "common_summary": [
            (s.get("id", ""), s.get("title", ""), s.get("summary", ""))
            for s in common_sections
        ],
        "deep": _deep_guidelines(src_name) if src_name else [],
        # 출처
        "source_md": str(REF_DIR / src_name) if src_name else "",
        "guide_md": str(_guide_md_path(src_name)) if src_name else "",
        "guide_json": str(GUIDE_JSON),
        "source_sha256": entry.get("source_sha256", ""),
        "common_md": str(REF_DIR / COMMON_SRC),
        "common_guide_md": str(_guide_md_path(COMMON_SRC)),
    }


# ── 인라인 마크다운 → reportlab 인라인 마크업 ────────────────────────────────
def _rt(text: str) -> str:
    """**굵게** / `코드` 를 살려 reportlab Paragraph 마크업으로."""
    s = xml_escape(str(text or ""))
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s, flags=re.S)
    s = re.sub(r"`([^`]+?)`", r'<font color="#b45309">\1</font>', s)
    s = s.replace("\u00a0", " ")
    return s


def _link(path: str) -> str:
    """파일 경로를 클릭 가능한 file:// 링크로(뷰어가 지원하면)."""
    if not path:
        return "—"
    href = "file:///" + quote(str(path).replace("\\", "/"), safe="/:")
    shown = xml_escape(_rel(path))
    return f'<link href="{href}" color="#1d4ed8">{shown}</link>'


def _rel(path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(config.ROOT_DIR)).replace("\\", "/")
    except Exception:  # noqa: BLE001 - 저장소 밖 경로면 그대로
        return str(path).replace("\\", "/")


# ── 한글 폰트 ────────────────────────────────────────────────────────────────
_FONT_CANDIDATES = [
    ("MalgunGothic", "C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/malgunbd.ttf"),
    ("NanumGothic", "C:/Windows/Fonts/NanumGothic.ttf", "C:/Windows/Fonts/NanumGothicBold.ttf"),
    ("NanumGothic", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
     "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
    ("AppleGothic", "/System/Library/Fonts/AppleSDGothicNeo.ttc", ""),
]


@lru_cache(maxsize=1)
def _fonts() -> tuple[str, str]:
    """(regular, bold) 폰트명 등록 후 반환. 한글 폰트가 없으면 RuntimeError."""
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for name, reg, bold in _FONT_CANDIDATES:
        if not Path(reg).exists():
            continue
        pdfmetrics.registerFont(TTFont(name, reg))
        bold_name = name
        if bold and Path(bold).exists():
            bold_name = name + "-Bold"
            pdfmetrics.registerFont(TTFont(bold_name, bold))
        addMapping(name, 0, 0, name)
        addMapping(name, 1, 0, bold_name)
        addMapping(name, 0, 1, name)
        addMapping(name, 1, 1, bold_name)
        return name, bold_name
    raise RuntimeError(
        "PDF 에 쓸 한글 폰트를 찾지 못했습니다(맑은 고딕/나눔고딕). "
        "폰트를 설치하거나 regulations._FONT_CANDIDATES 에 경로를 추가하세요."
    )


# ── PDF 빌드 ─────────────────────────────────────────────────────────────────
def build_pdf(reg: dict, out_path: Path, project_ctx: dict | None = None) -> Path:
    """regulation_for() 결과를 A4 PDF 로 렌더링해 out_path 에 쓴다."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable,
        ListFlowable,
        ListItem,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    font, bold = _fonts()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def style(name, **kw):
        base = dict(fontName=font, fontSize=9.5, leading=14, alignment=TA_LEFT)
        base.update(kw)
        return ParagraphStyle(name, **base)

    S_TITLE = style("t", fontName=bold, fontSize=17, leading=22, spaceAfter=2)
    S_SUB = style("s", fontSize=10, leading=15, textColor=colors.HexColor("#475569"))
    S_H1 = style("h1", fontName=bold, fontSize=12.5, leading=18,
                 textColor=colors.HexColor("#1d4ed8"), spaceBefore=14, spaceAfter=5)
    S_H2 = style("h2", fontName=bold, fontSize=10.5, leading=15,
                 textColor=colors.HexColor("#334155"), spaceBefore=8, spaceAfter=3)
    S_BODY = style("b", spaceAfter=2)
    S_NOTE = style("n", fontSize=8.8, leading=13, textColor=colors.HexColor("#64748b"))
    S_SRC = style("src", fontSize=8.6, leading=13)

    flow: list = []

    def h1(t):
        flow.append(Paragraph(_rt(t), S_H1))

    def h2(t):
        flow.append(Paragraph(_rt(t), S_H2))

    def bullets(items, style_=None, bullet="•", raw=False):
        """raw=True 면 이미 reportlab 마크업이 들어있는 문자열로 보고 재이스케이프하지 않음."""
        items = [i for i in items if str(i).strip()]
        if not items:
            return
        conv = (lambda s: s) if raw else _rt
        flow.append(
            ListFlowable(
                [ListItem(Paragraph(conv(i), style_ or S_BODY), leftIndent=12) for i in items],
                bulletType="bullet",
                start=bullet,
                bulletFontName=font,
                bulletFontSize=8,
                leftIndent=12,
            )
        )
        flow.append(Spacer(1, 4))

    # ── 표지 머리 ───────────────────────────────────────────────────────────
    label = reg.get("label") or reg.get("nid", "")
    head = f"{label} {reg.get('node_title') or reg.get('title') or ''}".strip()
    flow.append(Paragraph(_rt(f"작성 규정 — {head}"), S_TITLE))
    sub = ["연구개발계획서 작성 웹서비스 · 절별 적용 규정 모음"]
    if reg.get("skill"):
        sub.append(f"대응 스킬 {reg['skill']}")
    sub.append(datetime.now().strftime("%Y-%m-%d %H:%M"))
    flow.append(Paragraph(_rt(" · ".join(sub)), S_SUB))
    flow.append(Spacer(1, 4))
    flow.append(HRFlowable(width="100%", color=colors.HexColor("#cbd5e1")))
    if reg.get("applies_to"):
        flow.append(Spacer(1, 6))
        flow.append(Paragraph("<b>적용 범위</b> — " + _rt(reg["applies_to"]), S_NOTE))
    if reg.get("role"):
        flow.append(Paragraph("<b>역할</b> — " + _rt(reg["role"]), S_NOTE))

    # ── 0. 적용 법령·규정 (웹검증 큐레이션) ─────────────────────────────────
    as_of = reg.get("reg_as_of") or ""
    h1(f"1. 적용 법령·규정  (기준일 {as_of})" if as_of else "1. 적용 법령·규정")
    if reg.get("reg_disclaimer"):
        flow.append(Paragraph("⚠ " + _rt(reg["reg_disclaimer"]), S_NOTE))
        flow.append(Spacer(1, 5))
    if reg.get("law_notes"):
        flow.append(Paragraph("<b>이 절 유의</b> — " + _rt(reg["law_notes"]), S_BODY))
        flow.append(Spacer(1, 4))
    laws = reg.get("laws") or []
    if not laws:
        flow.append(Paragraph(
            _rt("이 절에 매핑된 법령·규정 데이터가 아직 없음(규정 데이터셋 미수록/미검증). "
                "regulations_data.json 을 재검증(refresh)해 채운다."), S_NOTE))
    for lw in laws:
        title = (lw.get("title") or "").strip()
        kind = (lw.get("kind") or "").strip()
        article = (lw.get("article") or "").strip()
        head_bits = [f"<b>{_rt(title)}</b>"]
        if kind:
            head_bits.append(f"({_rt(kind)})")
        if article:
            head_bits.append(_rt(article))
        flow.append(Paragraph(" ".join(head_bits), S_H2))
        if lw.get("requirement"):
            flow.append(Paragraph(_rt(lw["requirement"]), S_BODY))
        meta = []
        if lw.get("authority"):
            meta.append("소관 " + lw["authority"])
        if lw.get("effective_date"):
            meta.append("시행일 " + lw["effective_date"])
        if lw.get("verified_date"):
            meta.append("확인일 " + lw["verified_date"])
        conf = (lw.get("confidence") or "").strip()
        if conf:
            meta.append("신뢰도 " + conf)
        if meta:
            flow.append(Paragraph(_rt(" · ".join(meta)), S_NOTE))
        url = (lw.get("source_url") or "").strip()
        if url:
            safe = xml_escape(url)
            flow.append(Paragraph(
                f'출처 <link href="{safe}" color="#1d4ed8">{safe}</link>', S_SRC))
        if lw.get("note"):
            flow.append(Paragraph("비고 — " + _rt(lw["note"]), S_NOTE))
        flow.append(Spacer(1, 7))

    # ── 1. 서식 자체의 작성요령(※) ─────────────────────────────────────────
    h1("2. 서식 작성요령 (※ — 원본 hwpx 발췌)")
    if reg.get("form_guidelines"):
        bullets(reg["form_guidelines"], bullet="※")
    else:
        flow.append(Paragraph(_rt("이 절의 서식에는 별도 ※ 작성요령이 없음."), S_NOTE))

    # ── 2. 이 절의 지침 ─────────────────────────────────────────────────────
    h1("3. 이 절의 골격·변형·문체 지침")
    if reg.get("sections"):
        for sec, items in reg["sections"]:
            if sec:
                h2(sec)
            bullets(items)
    else:
        flow.append(Paragraph(_rt("이 절에 매핑된 지침이 없음(지침.json 미수록)."), S_NOTE))

    # ── 3. 체크리스트 ───────────────────────────────────────────────────────
    if reg.get("checklist"):
        h1("4. 제출 전 체크리스트")
        bullets(reg["checklist"], bullet="□")

    # ── 4. 참조 공통원칙 ────────────────────────────────────────────────────
    refs = reg.get("common_refs") or []
    h1(f"5. 이 절이 반드시 따르는 공통원칙 ({', '.join(refs) if refs else '지정 없음'})")
    if reg.get("common_ref_sections"):
        for sec, items in reg["common_ref_sections"]:
            if sec:
                h2(sec)
            bullets(items)
    else:
        flow.append(Paragraph(_rt("절별로 지정된 참조 §가 없음 — 아래 5번 전체가 적용됨."), S_NOTE))

    # ── 5. 공통원칙 전체 요약 ───────────────────────────────────────────────
    if reg.get("common_summary"):
        h1("6. 전 절 공통 작성 원칙 §0~§9 (요약)")
        bullets(
            [
                f"<b>{_rt(f'{sid} {title}')}</b> — {_rt(summary)}"
                for sid, title, summary in reg["common_summary"]
            ],
            raw=True,
        )

    # ── 6. 심화 지침 ────────────────────────────────────────────────────────
    if reg.get("deep"):
        h1("7. 심화 지침 (수동 편집 영역)")
        bullets(reg["deep"])

    # ── 7. 출처 ─────────────────────────────────────────────────────────────
    flow.append(PageBreak())
    h1("부록. 출처 — 원본 확인 경로")
    flow.append(
        Paragraph(
            _rt(
                "이 PDF 의 2~6번은 아래 원본에서 자동 추출·요약된 것이다. "
                "웹 UI ② '작성 프롬프트' 탭의 문체/구성 문구도 같은 원천(지침.json)에서 조립되므로, "
                "요약이 미심쩍으면 아래 경로의 원본을 직접 확인한다."
            ),
            S_NOTE,
        )
    )
    flow.append(Spacer(1, 6))

    rows = [
        ("이 절 원본 지침 md", reg.get("source_md")),
        ("자동 생성 지침 md", reg.get("guide_md")),
        ("구조화 지침 JSON", reg.get("guide_json")),
        ("공통 작성원칙 원본 md", reg.get("common_md")),
        ("공통 작성원칙 지침 md", reg.get("common_guide_md")),
    ]
    ctx = project_ctx or {}
    if ctx.get("source_hwpx"):
        rows.append(("서식 원본 hwpx", ctx["source_hwpx"]))
    if ctx.get("yaml_dir"):
        rows.append(("추출 YAML 디렉터리", ctx["yaml_dir"]))
    if ctx.get("node_dir"):
        rows.append(("이 절 작업 디렉터리", ctx["node_dir"]))

    for label_, path in rows:
        if not path:
            continue
        flow.append(Paragraph(f"<b>{xml_escape(label_)}</b><br/>{_link(path)}", S_SRC))
        flow.append(Spacer(1, 3))

    if reg.get("source_sha256"):
        flow.append(Spacer(1, 4))
        flow.append(
            Paragraph(
                _rt(
                    f"원본 md sha256 = `{reg['source_sha256']}` "
                    "(extract-md-guidelines sync 가 이 해시로 최신성을 판정)"
                ),
                S_NOTE,
            )
        )
    if ctx.get("node_paths"):
        paths = ctx["node_paths"]
        shown = ", ".join(paths[:6]) + (f" … (총 {len(paths)}개)" if len(paths) > 6 else "")
        flow.append(Spacer(1, 6))
        flow.append(
            Paragraph("<b>이 절의 편집 대상 문단 경로</b><br/>" + _rt(shown), S_SRC)
        )

    # ── 문서 생성 ───────────────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title=f"작성 규정 {label}",
        author="연구개발계획서 작성 웹서비스",
    )

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont(font, 7.5)
        canvas.setFillColor(colors.HexColor("#94a3b8"))
        canvas.drawString(20 * mm, 10 * mm, f"작성 규정 · {head}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, str(doc_.page))
        canvas.restoreState()

    doc.build(flow, onFirstPage=_footer, onLaterPages=_footer)
    return out_path


if __name__ == "__main__":  # 스모크: python -m backend.regulations 5-3
    import sys

    nid = sys.argv[1] if len(sys.argv) > 1 else "5-3"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"규정_{nid}.pdf")
    build_pdf(regulation_for(nid), out)
    print(f"wrote {out}")
