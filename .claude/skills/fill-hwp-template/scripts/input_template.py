#!/usr/bin/env python3
"""세분화된 hwpmd Markdown에서 JSON 입력 템플릿을 추출하고, 채운 값을 본문·표에 다시 기록한다.

두 서브커맨드:
  extract  각 .md 옆에 `<파일>.tmpl.json` 을 만든다. 헤딩은 `{{title}}`로 템플릿화하고,
           채울 슬롯(불릿/문단/표 셀)에는 `value:""` 필드를, ※ 작성요령은 `guideline`으로 담는다.
  apply    `<파일>.tmpl.json` 의 value를 읽어 해당 .md 의 SOURCE 구간(본문 문단·표 셀)에 기록한다.
           앵커(`<!--@hwp ...-->`)·`data-hwp-*`·표 구조는 보존하므로 상위 파이프라인으로 재병합된다.

분류 규칙(본문 최상위 문단, 순서대로):
  표 컨테이너/레이아웃·객체 컨트롤 → 건너뜀 · 빈 줄 → 제외 · hwp-note(※) → guideline(읽기전용)
  · 헤딩 → title 템플릿화 · 불릿 스텁(o,-,·,□) → 채움(마커 보존) · [라벨]/일반 내용 → 채움
표 셀: 병합(rowspan/colspan) 앵커 셀만 존재. 채움 대상 = 빈 셀(<br>)·플레이스홀더((   )). 각 셀의
  `{table}.R{rr}C{cc}.P00` 문단에 기록. data-hwp-control(이미지·직인·수식) 셀은 건너뜀.

전체 흐름:
  subsplit split → input_template extract → (사람이 JSON value 작성) → input_template apply
  → subsplit merge --allow-edits --write-back 장별 → tools/merge_hwpmd_chapters.py → 마스터/HWP
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import os
import re
import sys
from pathlib import Path

SOURCE_BEGIN = "<!--@hwp-source-begin-->"
SOURCE_END = "<!--@hwp-source-end-->"

TOP_ANCHOR_RE = re.compile(r"(?m)^<!--@hwp node=(S\d+\.P\d{4}) pid=[^>]*-->\r?\n")
TABLE_OPEN_FULL_RE = re.compile(
    r'<table data-hwp-node="(S\d+\.P\d{4}\.T\d{2})"[^>]*'
    r'data-hwp-rows="(\d+)"[^>]*data-hwp-cols="(\d+)"[^>]*>')
TD_RE = re.compile(
    r'<td data-hwp-cell="(?P<cell>[^"]+)" data-hwp-col="(?P<c>\d+)" '
    r'data-hwp-row="(?P<r>\d+)"[^>]*?(?:colspan="(?P<cs>\d+)")?[^>]*?'
    r'(?:rowspan="(?P<rs>\d+)")?[^>]*>')
TAG_RE = re.compile(r"<[^>]+>")
CS_RE = re.compile(r'data-hwp-cs="(\d+)"')
BLANK_INNER = '<br data-hwp-blank="true">'
BULLET_CHARS = "o○◦●□▪·⋅∙\\-*ㅇ"
BULLET_ONLY_RE = re.compile(rf"^\s*[{BULLET_CHARS}]+\s*$")
PLACEHOLDER_RE = re.compile(r"\(\s{2,}[^)]*\)|\[\s{2,}\]|YYYY|\(\s*\)")


def sha256_text(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8")).hexdigest()


def _lp(path: Path) -> Path:
    if os.name == "nt":
        ap = os.path.abspath(str(path))
        if not ap.startswith("\\\\?\\"):
            ap = "\\\\?\\" + ap
        return Path(ap)
    return path


def read_text_lp(path: Path) -> str:
    with _lp(path).open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write_text_lp(path: Path, data: str) -> None:
    _lp(path).write_text(data, encoding="utf-8", newline="")


def source_span(text: str, name: str) -> tuple[int, int]:
    if text.count(SOURCE_BEGIN) != 1 or text.count(SOURCE_END) != 1:
        raise ValueError(f"{name}: SOURCE 마커가 정확히 1쌍이 아님")
    m = re.search(re.escape(SOURCE_BEGIN) + r"\r?\n", text)
    if not m:
        raise ValueError(f"{name}: SOURCE_BEGIN 뒤 개행 없음")
    return m.end(), text.index(SOURCE_END, m.end())


def visible(inner: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(TAG_RE.sub("", inner))).strip()


def first_cs(inner: str, default: str) -> str:
    m = CS_RE.search(inner)
    return m.group(1) if m else default


def esc(text: str) -> str:
    return htmllib.escape(text, quote=False)


def make_label(title: str) -> str:
    t = title.strip()
    for pat in (r"^\(?\s*(\d+-\d+)\.?", r"^(\(\d+\))", r"^([가-힣])\.",
                r"^\[?\s*(별첨\s*\d+)", r"^(\d+)\."):
        m = re.match(pat, t)
        if m:
            return m.group(1).replace(" ", "")
    return ""


def split_note(vtext: str) -> tuple[str, str]:
    """가시 텍스트를 (내용, ※가이드라인)으로 분리."""
    i = vtext.find("※")
    if i < 0:
        return vtext.strip(), ""
    return vtext[:i].strip(), vtext[i + 1:].strip()


# ─────────────────────────── 본문 문단 파싱 ───────────────────────────

def top_elements(fragment: str):
    """(node, tag, cls, inner, is_container) 최상위 요소들을 순서대로 산출."""
    for m in TOP_ANCHOR_RE.finditer(fragment):
        node = m.group(1)
        start = m.end()
        # 요소 여는 태그
        om = re.match(r'<(p|h[1-6]) class="([^"]*)" data-hwp-node="'
                      + re.escape(node) + r'"[^>]*>', fragment[start:])
        if not om:
            continue
        tag, cls = om.group(1), om.group(2)
        open_end = start + om.end()
        line_end = fragment.find("\n", open_end)
        if line_end < 0:
            line_end = len(fragment)
        line = fragment[open_end:line_end]
        close = f"</{tag}>"
        # 단일 라인 요소: 같은 줄에서 닫힘
        if close in line and "<table" not in line:
            inner = line[:line.rfind(close)]
            yield node, tag, cls, inner, False
        else:
            yield node, tag, cls, "", True   # 표 컨테이너 등 → 건너뜀


def classify(tag: str, cls: str, inner: str) -> dict:
    vt = visible(inner)
    if inner.strip() == BLANK_INNER or vt == "":
        return {"role": "blank"}
    if cls == "hwp-note" or vt.startswith("※"):
        return {"role": "note", "guideline": split_note(vt)[1] or vt.lstrip("※ ").strip()}
    controls = re.findall(r'data-hwp-control="([^"]+)"', inner)
    if any(c != "NewNumbering" for c in controls):
        return {"role": "skip"}
    # 컨트롤 span(NewNumbering 등)·탭·고정폭이 있으면 텍스트 교체 금지(보호)
    protect = ("data-hwp-control" in inner) or ("data-hwp-ctl" in inner)
    if tag in ("h2", "h3", "h4", "h5"):
        content, note = split_note(vt)
        # 라벨을 원형(문장부호 포함: "5-1.", "(1)", "가.")대로 보존
        lm = re.match(r"^\s*(\(?\d+(?:-\d+)?\)?\.?|\[?\s*별첨\s*\d+\]?\.?|[가-힣]\.)", content)
        label = lm.group(1).strip() if lm else ""
        title = content[lm.end():].strip() if lm else content
        return {"role": "heading", "level": int(tag[1]), "label": label,
                "title": title, "guideline": note, "protect": protect}
    # 불릿 스텁(단일 span, 마커만)
    if inner.count("<span") == 1 and "data-hwp-ctl" not in inner \
            and BULLET_ONLY_RE.match(vt):
        return {"role": "bullet", "marker": vt}
    content, note = split_note(vt)
    if re.match(r"^\s*\[[^\]]*\]", vt):
        return {"role": "label", "current": content, "guideline": note, "protect": protect}
    return {"role": "content", "current": content, "guideline": note, "protect": protect}


# ─────────────────────────── 표 파싱 ───────────────────────────

def match_table_end(text: str, open_at: int) -> int:
    depth, i = 0, open_at
    tok = re.compile(r"</?table\b")
    while True:
        m = tok.search(text, i)
        if not m:
            return len(text)
        if text[m.start() + 1] == "/":
            depth -= 1
            if depth == 0:
                gt = text.find(">", m.end())
                return gt + 1 if gt >= 0 else len(text)
        else:
            depth += 1
        i = m.end()


def cell_p_inner(table_html: str, pnode: str) -> tuple[str | None, bool]:
    """(inner, multiline). inner=None이면 P00 문단 없음. multiline=True면
    같은 줄에서 닫히지 않음(중첩 표 등) → 텍스트 채움 대상 아님."""
    m = re.search(r'<p class="[^"]*" data-hwp-node="' + re.escape(pnode) + r'"[^>]*>',
                  table_html)
    if not m:
        return None, False
    rest = table_html[m.end():]
    nl = rest.find("\n")
    seg = rest if nl < 0 else rest[:nl]
    close = seg.find("</p>")
    if close >= 0:
        return seg[:close], False
    return "", True


def parse_tables(fragment: str) -> list[dict]:
    tables = []
    for m in TABLE_OPEN_FULL_RE.finditer(fragment):
        tnode, rows, cols = m.group(1), int(m.group(2)), int(m.group(3))
        end = match_table_end(fragment, m.start())
        thtml = fragment[m.start():end]
        cells = []
        for td in TD_RE.finditer(thtml):
            cell = td.group("cell")
            if cell.rsplit(".", 1)[0] != tnode:     # 중첩 표 셀 제외
                continue
            r, c = int(td.group("r")), int(td.group("c"))
            p00 = f"{cell}.P00"
            rel = cell[len(tnode) + 1:]
            inner, multiline = cell_p_inner(thtml, p00)
            if inner is None:
                continue
            if multiline or "<table" in inner:
                cells.append({"cell": rel, "r": r, "c": c,
                              "kind": "nested", "current": "(표/다단 셀)"})
                continue
            if "data-hwp-control" in inner:
                cells.append({"cell": rel, "r": r, "c": c,
                              "kind": "skip", "current": visible(inner)})
                continue
            vt = visible(inner)
            raw = htmllib.unescape(TAG_RE.sub("", inner))   # 공백 보존(플레이스홀더 판정)
            fillable = (inner.strip() == BLANK_INNER or vt == ""
                        or bool(PLACEHOLDER_RE.search(raw)))
            cells.append({"cell": rel, "r": r, "c": c,
                          "p00": p00, "kind": "fill" if fillable else "label",
                          "current": vt, "value": ""})
        cap = _nearest_heading(fragment, m.start())
        tables.append({"id": tnode, "rows": rows, "cols": cols,
                       "guideline": cap, "cells": cells})
    return tables


def _nearest_heading(fragment: str, pos: int) -> str:
    best = ""
    for m in TOP_ANCHOR_RE.finditer(fragment):
        if m.start() >= pos:
            break
        nl = fragment.find("\n", m.end())
        seg = fragment[m.end(): nl if nl >= 0 else len(fragment)]
        hm = re.match(r'<(h[2-5]) [^>]*>(.*?)</\1>', seg)
        if hm:
            best = split_note(visible(hm.group(2)))[0]
    return best[:80]


# ─────────────────────────── extract ───────────────────────────

def _set_editable(field: dict, info: dict) -> None:
    """protect(컨트롤·탭 span)면 읽기전용, 아니면 value 슬롯 부여."""
    if info.get("protect"):
        field["readonly"] = True
    else:
        field["value"] = ""


def extract_file(path: Path, rel: str) -> dict | None:
    text = read_text_lp(path)
    try:
        b, e = source_span(text, path.name)
    except ValueError:
        return None
    fragment = text[b:e]
    tm = re.search(r"(?m)^#\s+(.+?)\s*$", text[:b])
    title = tm.group(1).strip() if tm else path.stem
    label = make_label(title)

    fields, skipped = [], 0
    for node, tag, cls, inner, container in top_elements(fragment):
        if container:
            skipped += 1
            continue
        info = classify(tag, cls, inner)
        role = info["role"]
        if role in ("blank", "skip"):
            skipped += 1
            continue
        if role == "note":
            fields.append({"id": node, "role": "note", "guideline": info["guideline"]})
        elif role == "heading":
            f = {"id": node, "role": "heading", "level": info["level"],
                 "label": info["label"],
                 "template": (f"{info['label']} {{{{title}}}}" if info["label"] else "{{title}}"),
                 "current_title": info["title"], "guideline": info["guideline"]}
            _set_editable(f, info)
            fields.append(f)
        elif role == "bullet":
            fields.append({"id": node, "role": "bullet", "marker": info["marker"], "value": ""})
        else:  # label / content
            f = {"id": node, "role": role, "current": info["current"],
                 "guideline": info["guideline"]}
            _set_editable(f, info)
            fields.append(f)

    tables = parse_tables(fragment)
    guidelines = [f["guideline"] for f in fields if f.get("guideline")]

    return {
        "input_template": "hwpmd-fill/1.0",
        "file": rel,
        "source_fragment_sha256": sha256_text(fragment),
        "section": {"label": label, "title": title},
        "_help": ("value 필드에 내용을 채우면 apply 시 해당 문단/셀에 기록됩니다. "
                  "빈 문자열은 원문 유지. role=note와 readonly=true는 작성요령/구조라 편집하지 않습니다. "
                  "헤딩은 value에 제목만 넣으면 '{label} 제목'으로 대체됩니다."),
        "guidelines": guidelines,
        "fields": fields,
        "tables": tables,
        "_skipped_blocks": skipped,
    }


def cmd_extract(args: argparse.Namespace) -> None:
    files = _target_files(args)
    made = 0
    summary = []
    for path, rel in files:
        tmpl = extract_file(path, rel)
        if tmpl is None:
            continue
        out = path.with_suffix(path.suffix + ".tmpl.json")
        write_text_lp(out, json.dumps(tmpl, ensure_ascii=False, indent=2) + "\n")
        made += 1
        fillable = sum(1 for f in tmpl["fields"] if "value" in f) + \
            sum(1 for t in tmpl["tables"] for c in t["cells"] if c.get("kind") == "fill")
        summary.append({"file": rel, "fields": len(tmpl["fields"]),
                        "tables": len(tmpl["tables"]), "fillable": fillable})
    print(json.dumps({"templates": made, "files": summary[:200]},
                     ensure_ascii=False, indent=2))


# ─────────────────────────── apply ───────────────────────────

def replace_top_inner(fragment: str, node: str, new_inner: str) -> tuple[str, int]:
    pat = re.compile(r'(<(p|h[1-6]) class="[^"]*" data-hwp-node="'
                     + re.escape(node) + r'"[^>]*>)([^\n]*?)(</\2>)')
    return pat.subn(lambda m: m.group(1) + new_inner + m.group(4), fragment, count=1)


def read_top_inner(fragment: str, node: str) -> str | None:
    m = re.search(r'<(p|h[1-6]) class="[^"]*" data-hwp-node="'
                  + re.escape(node) + r'"[^>]*>([^\n]*?)</\1>', fragment)
    return m.group(2) if m else None


def span(cs: str, text: str) -> str:
    return f'<span data-hwp-cs="{cs}" lang="ko">{esc(text)}</span>'


def apply_file(path: Path, tmpl: dict, force: bool) -> dict:
    text = read_text_lp(path)
    b, e = source_span(text, path.name)
    fragment = text[b:e]
    drift = sha256_text(fragment) != tmpl.get("source_fragment_sha256")
    if drift and not force:
        return {"file": tmpl["file"], "applied": 0, "skipped_drift": True,
                "note": "md가 템플릿 추출 이후 변경됨 — --force 필요"}

    applied = 0
    # 본문 필드
    for f in tmpl.get("fields", []):
        val = (f.get("value") or "").strip()
        if not val or f.get("readonly") or f["role"] == "note":
            continue
        cur = read_top_inner(fragment, f["id"])
        if cur is None:
            continue
        role = f["role"]
        # 방어: 컨트롤·탭 span이 있으면 텍스트 교체하지 않는다(구조 보호)
        if role in ("heading", "content", "label") and \
                ("data-hwp-control" in cur or "data-hwp-ctl" in cur):
            continue
        if role == "heading":
            cs = first_cs(cur, "38")
            label = f.get("label", "")
            new_inner = span(cs, f"{label} {val}".strip())
        elif role == "bullet":
            # 마커 span만 남기고 값을 추가 → 재적용해도 중복되지 않음(idempotent)
            mm = re.match(r"\s*<span[^>]*>.*?</span>", cur)
            marker_span = mm.group(0) if mm else ""
            cs = first_cs(marker_span or cur, "20")
            new_inner = marker_span + span(cs, val)
        else:                                     # content / label
            cs = first_cs(cur, "15")
            new_inner = span(cs, val)
        fragment, n = replace_top_inner(fragment, f["id"], new_inner)
        applied += n

    # 표 셀
    for t in tmpl.get("tables", []):
        for c in t["cells"]:
            val = (c.get("value") or "").strip()
            if not val or c.get("kind") not in ("fill", "label") or "p00" not in c:
                continue
            cur = read_top_inner(fragment, c["p00"])
            if cur is None:
                continue
            cs = first_cs(cur, "29")
            fragment, n = replace_top_inner(fragment, c["p00"], span(cs, val))
            applied += n

    if applied:
        write_text_lp(path, text[:b] + fragment + text[e:])
    return {"file": tmpl["file"], "applied": applied, "drift": drift}


def cmd_apply(args: argparse.Namespace) -> None:
    files = _target_files(args)
    reports = []
    for path, rel in files:
        tp = path.with_suffix(path.suffix + ".tmpl.json")
        if not _lp(tp).exists():
            continue
        try:
            tmpl = json.loads(read_text_lp(tp))
            reports.append(apply_file(path, tmpl, args.force))
        except (ValueError, json.JSONDecodeError) as ex:
            reports.append({"file": rel, "applied": 0, "error": str(ex)})
    total = sum(r.get("applied", 0) for r in reports)
    print(json.dumps({"files": len(reports), "total_applied": total,
                      "reports": [r for r in reports
                                  if r.get("applied") or r.get("skipped_drift") or r.get("error")]},
                     ensure_ascii=False, indent=2))


# ─────────────────────────── 공통 ───────────────────────────

def _target_files(args: argparse.Namespace) -> list[tuple[Path, str]]:
    if args.file:
        return [(args.file, args.file.name)]
    root = args.dir
    out = []
    for p in sorted(_lp(root).glob("**/*.md")):
        name = p.name
        if name == "README.md" or name.startswith("_") or ".tmpl" in name:
            continue
        if "_tables" in str(p).replace("\\", "/").split("/"):
            continue
        try:
            rel = str(Path(str(p)).relative_to(_lp(root)))
        except ValueError:
            rel = name
        out.append((Path(str(p)), rel))
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    for name, fn, helptext in (("extract", cmd_extract, "JSON 입력 템플릿 추출"),
                               ("apply", cmd_apply, "채운 템플릿을 md에 기록")):
        sp = sub.add_parser(name, help=helptext)
        g = sp.add_mutually_exclusive_group(required=True)
        g.add_argument("--dir", type=Path, help="세부/장별 폴더(하위 .md 전체)")
        g.add_argument("--file", type=Path, help="md 하나만")
        if name == "apply":
            sp.add_argument("--force", action="store_true",
                            help="md가 템플릿 추출 이후 바뀌었어도 적용")
        sp.set_defaults(func=fn)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
