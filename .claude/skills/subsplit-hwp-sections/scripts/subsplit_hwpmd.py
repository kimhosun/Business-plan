#!/usr/bin/env python3
"""장별 hwpmd Markdown을 하위절(1-1, 1-2, (1), (2), 가. …)로 재귀 분리한다.

입력: `split_hwpmd_chapters.py`/`autosplit_hwpmd.py`가 만든 장 파일들
(각 파일의 `<!--@hwp-source-begin-->`~`<!--@hwp-source-end-->` 구간이 원문 조각).

동작:
  * 각 장 조각을 실제 헤딩 계층(h2 장 > h3 N-N > h4 가. > h5 (N))대로 재귀 분리한다.
  * 분리 단위는 언제나 최상위 문단 앵커(`<!--@hwp node=SN.Pdddd pid=...-->`)이며 표·셀 내부에서는 자르지 않는다.
  * DFS 순서로 이으면 장 조각과 바이트 단위로 동일하다(무손실). 생성 시 assert로 검증한다.
  * 표는 (a) 장·절별 목록(카탈로그)과 (b) 앵커째로 별도 .md 복사본을 함께 만든다(본문은 유지).

출력(중첩 폴더):
  <out>/<장폴더>/00_<장라벨>_머리.md          장 머리(개요) — 하위절이 있을 때
  <out>/<장폴더>/01_5-1_.../00_5-1_머리.md      하위절 머리
  <out>/<장폴더>/01_5-1_.../01_(1)_....md        (N) 잎 파일
  <out>/<장폴더>/_tables/<노드>.md              표 복사본
  <out>/<장폴더>/_tables.md                      장 표 목록
  <out>/<장폴더>/_세부_매니페스트.json          재병합용 매니페스트
  <out>/_tables_index.{json,md}                  전체 표 색인
  <out>/README.md                                전체 트리 요약

재병합(하위절 → 장 조각 검증):
  python subsplit_hwpmd.py merge --output <out> [--write-back <장별폴더>]
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SOURCE_BEGIN = "<!--@hwp-source-begin-->"
SOURCE_END = "<!--@hwp-source-end-->"

TOP_NODE_RE = re.compile(r"(?m)^<!--@hwp node=(S\d+\.P\d{4}) pid=")
# 앵커 + 바로 다음 줄의 블록 태그(헤딩 판정).
ANCHOR_BLOCK_RE = re.compile(
    r"(?m)^<!--@hwp node=(S\d+\.P\d{4}) pid=[^>]*-->\r?\n<(h[1-6]|p)\b"
)
TABLE_NODE_RE = re.compile(r"<!--@hwp table=(S\d+\.P\d{4}\.T\d{2})-->")
TABLE_OPEN_RE = re.compile(r"<table\b[^>]*>")
TABLE_ATTR_RE = re.compile(r'data-hwp-(rows|cols)="(\d+)"')
TAG_RE = re.compile(r"<[^>]+>")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _lp(path: Path) -> Path:
    """Windows MAX_PATH(260) 제한을 피하기 위한 확장 경로(\\\\?\\)."""
    if os.name == "nt":
        ap = os.path.abspath(str(path))
        if not ap.startswith("\\\\?\\"):
            ap = "\\\\?\\" + ap
        return Path(ap)
    return path


def write_text_lp(path: Path, data: str) -> None:
    _lp(path).write_text(data, encoding="utf-8", newline="")


def read_text_lp(path: Path) -> str:
    with _lp(path).open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def mkdir_lp(path: Path) -> None:
    _lp(path).mkdir(parents=True, exist_ok=True)


def strip_tags(line: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", line))).strip()


def sanitize(text: str, limit: int = 40) -> str:
    text = re.sub(r"[·∙・]", "_", text.strip())
    text = re.sub(r"[^0-9A-Za-z가-힣]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")[:limit] or "절"


def safe_label(label: str) -> str:
    """파일명에 쓸 라벨. 괄호·하이픈은 유지((1), 5-1)."""
    s = re.sub(r"\s+", "_", label.strip().rstrip("."))
    s = re.sub(r"[^0-9A-Za-z가-힣()\-]", "", s)
    return s or "절"


def base_name(ordinal: int, label: str, title: str) -> str:
    body = sanitize(title_body(title, label))
    if not label.strip():
        return f"{ordinal:02d}_{body}" if body else f"{ordinal:02d}_절"
    lab = safe_label(label)
    return f"{ordinal:02d}_{lab}" + (f"_{body}" if body else "")


def head_name(label: str) -> str:
    return f"00_{safe_label(label)}_머리"


def make_label(title: str) -> str:
    """헤딩 제목에서 분류 라벨(1-1, (1), 가, 5 …)을 뽑는다."""
    t = title.strip()
    m = re.match(r"^\(?\s*(\d+-\d+)\.?", t)          # 1-1
    if m:
        return m.group(1)
    m = re.match(r"^(\(\d+\))", t)                    # (1)
    if m:
        return m.group(1)
    m = re.match(r"^([가-힣])\.", t)                  # 가.
    if m:
        return m.group(1)
    m = re.match(r"^\[?\s*(별첨\s*\d+)", t)           # 별첨 1
    if m:
        return m.group(1).replace(" ", "")
    m = re.match(r"^(\d+)\.", t)                      # 5.
    if m:
        return m.group(1)
    return ""


_LABEL_PREFIXES = [
    r"^\(?\s*\d+-\d+\.?\)?\s*",       # 1-1.
    r"^\(\d+\)\s*",                    # (1)
    r"^[가-힣]\.\s*",                  # 가.
    r"^\[?\s*별첨\s*\d+[.\]]?\s*",     # 별첨 1
    r"^\d+\.\s*",                      # 5.
]


def title_body(title: str, label: str) -> str:
    """라벨을 뗀 제목 본문(파일명용). 인식된 라벨 형태만 제거한다.
    ※ 이후 안내문은 버린다."""
    t = title.strip()
    if label:
        for p in _LABEL_PREFIXES:
            new = re.sub(p, "", t, count=1)
            if new != t:
                t = new
                break
    return t.split("※")[0].strip()


# ─────────────────────────── 헤딩·트리 ───────────────────────────

@dataclass
class Heading:
    cut: int      # 자를 위치(쪽 나눔 포함)
    level: int    # 2..6
    title: str
    node: str


@dataclass
class Node:
    label: str
    title: str
    level: int
    node_id: str | None
    text: str
    preamble: str = ""
    children: list["Node"] = field(default_factory=list)
    abs_start: int = 0     # 장 조각 내 절대 시작 오프셋


def page_break_cut(text: str, node: str, anchor_at: int) -> int:
    prefix = text[:anchor_at]
    m = re.compile(
        rf'<!--@hwp page-break before={re.escape(node)} explicit="true"-->\r?\n?$'
    ).search(prefix)
    if m:
        start = m.start()
        if start > 0 and text[start - 1] == "\n":
            start -= 1
        return start
    return anchor_at


def find_headings(text: str) -> list[Heading]:
    out: list[Heading] = []
    for m in ANCHOR_BLOCK_RE.finditer(text):
        node, tag = m.group(1), m.group(2)
        if not tag.startswith("h"):
            continue
        level = int(tag[1])
        anchor_at = m.start()
        line_start = text.find("<" + tag, anchor_at)
        line_end = text.find("\n", line_start)
        line = text[line_start : line_end if line_end >= 0 else len(text)]
        out.append(Heading(page_break_cut(text, node, anchor_at), level, strip_tags(line), node))
    return out


def make_node(text: str, label: str, title: str, level: int,
              node_id: str | None, max_level: int, abs_start: int) -> Node:
    node = Node(label, title, level, node_id, text, abs_start=abs_start)
    headings = find_headings(text)
    rest = headings[1:] if headings else []          # headings[0] = 자기 제목
    cand = [h for h in rest if h.level <= max_level]
    if not cand:
        node.preamble = text                          # 잎: 전체가 자기 내용
        return node
    target = min(h.level for h in cand)
    splits = [h for h in rest if h.level == target]
    node.preamble = text[: splits[0].cut]
    for i, h in enumerate(splits):
        s = h.cut
        e = splits[i + 1].cut if i + 1 < len(splits) else len(text)
        child_label = make_label(h.title) or (h.node or f"seg{i}")
        node.children.append(
            make_node(text[s:e], child_label, h.title, h.level, h.node,
                      max_level, abs_start + s)
        )
    return node


# ─────────────────────────── 표 ───────────────────────────

@dataclass
class Table:
    node: str
    start: int
    end: int
    rows: str
    cols: str
    html: str


def match_table_end(text: str, open_at: int) -> int:
    """중첩 표를 고려해 여는 <table>에 대응하는 </table> 끝 위치를 찾는다."""
    depth = 0
    i = open_at
    token = re.compile(r"</?table\b")
    while True:
        m = token.search(text, i)
        if not m:
            return len(text)
        if text[m.start() + 1] == "/":
            depth -= 1
            if depth == 0:
                return text.find(">", m.end()) + 1 or len(text)
        else:
            depth += 1
        i = m.end()


def find_tables(text: str) -> list[Table]:
    out: list[Table] = []
    captured: list[tuple[int, int]] = []      # 이미 잡은 표 span(중첩 표 중복 방지)
    for m in TABLE_NODE_RE.finditer(text):
        if any(a <= m.start() < b for a, b in captured):
            continue
        node = m.group(1)
        open_m = TABLE_OPEN_RE.search(text, m.end())
        if not open_m:
            continue
        end = match_table_end(text, open_m.start())
        captured.append((open_m.start(), end))
        attrs = dict((k, v) for k, v in TABLE_ATTR_RE.findall(open_m.group(0)))
        out.append(Table(node, m.start(), end, attrs.get("rows", "?"),
                         attrs.get("cols", "?"), text[open_m.start():end]))
    return out


# ─────────────────────────── 파일 입출력 ───────────────────────────

def source_span(text: str, name: str) -> tuple[int, int]:
    """SOURCE_BEGIN 다음 줄부터 SOURCE_END 직전까지의 (시작, 끝). CRLF도 허용."""
    if text.count(SOURCE_BEGIN) != 1 or text.count(SOURCE_END) != 1:
        raise ValueError(f"{name}: SOURCE 마커가 정확히 1쌍이 아님")
    m = re.search(re.escape(SOURCE_BEGIN) + r"\r?\n", text)
    if not m:
        raise ValueError(f"{name}: SOURCE_BEGIN 뒤 개행을 찾지 못함")
    return m.end(), text.index(SOURCE_END, m.end())


def read_source_fragment(path: Path) -> tuple[str, str]:
    """장 파일에서 (제목, SOURCE 조각)을 추출한다."""
    text = read_text_lp(path)
    b, e = source_span(text, path.name)
    m = re.search(r"(?m)^#\s+(.+?)\s*$", text[:b])
    title = m.group(1).strip() if m else path.stem
    return title, text[b:e]


def write_leaf(path: Path, title: str, content: str, meta: dict) -> dict:
    fm = "\n".join([
        "---",
        'subsplit_hwpmd: "1.0"',
        f'section_label: "{meta["label"]}"',
        f'level: {meta["level"]}',
        f'source_range: "{meta["source_range"]}"',
        f'fragment_sha256: "{sha256_text(content)}"',
        "---",
        "",
        f"# {title}",
        "",
        SOURCE_BEGIN,
        "",
    ])
    write_text_lp(path, fm + content + SOURCE_END + "\n")
    nodes = TOP_NODE_RE.findall(content)
    return {
        "file": meta["relpath"],
        "label": meta["label"],
        "title": title,
        "level": meta["level"],
        "chars": len(content),
        "fragment_sha256": sha256_text(content),
        "top_level_nodes": len(nodes),
        "start_node": nodes[0] if nodes else None,
        "end_node": nodes[-1] if nodes else None,
    }


def range_str(content: str) -> str:
    nodes = TOP_NODE_RE.findall(content)
    if not nodes:
        return "(헤딩/표 없음)"
    return nodes[0] if len(nodes) == 1 else f"{nodes[0]}..{nodes[-1]}"


def emit_node(node: Node, out_dir: Path, rel_prefix: str, ordinal: int,
              order: list[dict], ranges: list[tuple[int, int, str]]) -> None:
    """트리를 중첩 폴더로 기록하고, 무손실 순서 목록·오프셋 범위를 채운다."""
    base = base_name(ordinal, node.label, node.title)
    if node.children:
        folder = out_dir / base
        mkdir_lp(folder)
        # 0) 머리(자기 개요) 파일
        hname = head_name(node.label)
        head_rel = f"{rel_prefix}{base}/{hname}.md"
        meta = {"label": node.label, "level": node.level,
                "source_range": range_str(node.preamble), "relpath": head_rel}
        rec = write_leaf(folder / f"{hname}.md",
                         f"{node.title} (머리)", node.preamble, meta)
        order.append(rec)
        ranges.append((node.abs_start, node.abs_start + len(node.preamble), head_rel))
        # 1..) 하위 노드
        for i, ch in enumerate(node.children, start=1):
            emit_node(ch, folder, f"{rel_prefix}{base}/", i, order, ranges)
    else:
        rel = f"{rel_prefix}{base}.md"
        meta = {"label": node.label, "level": node.level,
                "source_range": range_str(node.text), "relpath": rel}
        rec = write_leaf(out_dir / f"{base}.md", node.title, node.text, meta)
        order.append(rec)
        ranges.append((node.abs_start, node.abs_start + len(node.text), rel))


def tree_outline(node: Node, depth: int = 0) -> list[str]:
    pad = "  " * depth
    line = f"{pad}- {node.label} {title_body(node.title, node.label)}".rstrip()
    lines = [line]
    for ch in node.children:
        lines.extend(tree_outline(ch, depth + 1))
    return lines


# ─────────────────────────── split 명령 ───────────────────────────

def process_chapter(path: Path, out_root: Path, max_level: int) -> dict:
    title, fragment = read_source_fragment(path)
    chapter_label = make_label(title)   # 공통 문서는 라벨 없음("")
    root = make_node(fragment, chapter_label, title, 2, None, max_level, 0)

    chapter_dir = out_root / path.stem
    mkdir_lp(chapter_dir)

    order: list[dict] = []
    ranges: list[tuple[int, int, str]] = []
    if root.children:
        # 장 머리
        hname = head_name(chapter_label)
        head_rel = f"{hname}.md"
        meta = {"label": chapter_label, "level": 2,
                "source_range": range_str(root.preamble), "relpath": head_rel}
        order.append(write_leaf(chapter_dir / head_rel, f"{title} (머리)",
                                root.preamble, meta))
        ranges.append((0, len(root.preamble), head_rel))
        for i, ch in enumerate(root.children, start=1):
            emit_node(ch, chapter_dir, "", i, order, ranges)
    else:
        rel = f"{base_name(0, chapter_label, title)}.md"
        meta = {"label": chapter_label, "level": 2,
                "source_range": range_str(fragment), "relpath": rel}
        order.append(write_leaf(chapter_dir / rel, title, fragment, meta))
        ranges.append((0, len(fragment), rel))

    # 무손실 검증: merge가 의존하는 순서(=manifest order, emission 순서) 그대로
    # 이어붙여 원 조각과 대조한다. 정렬하지 않는다(정렬하면 순서 오류를 놓친다).
    pos = 0
    for a, b, _ in ranges:
        if a != pos or b < a:
            raise AssertionError(
                f"{path.name}: 절 범위가 연속적이지 않음 (start={a}, expected={pos})")
        pos = b
    if pos != len(fragment) or "".join(fragment[a:b] for a, b, _ in ranges) != fragment:
        raise AssertionError(f"{path.name}: 하위절 재조합이 원 조각과 불일치")

    # 표 카탈로그 + 복사본
    tables = find_tables(fragment)
    table_records = []
    if tables:
        tdir = chapter_dir / "_tables"
        mkdir_lp(tdir)
        for t in tables:
            owner = next((rel for a, b, rel in ranges if a <= t.start < b), "(?)")
            caption = _caption_for(fragment, t.start)
            write_text_lp(
                tdir / f"{t.node}.md",
                f"---\ntable_node: \"{t.node}\"\nrows: {t.rows}\ncols: {t.cols}\n"
                f"owner_section: \"{owner}\"\ncaption: \"{caption}\"\n---\n\n"
                f"<!--@hwp table={t.node}-->\n{t.html}\n")
            table_records.append({
                "node": t.node, "rows": t.rows, "cols": t.cols,
                "owner_section": owner, "caption": caption,
                "copy": f"{path.stem}/_tables/{t.node}.md",
            })
        _write_chapter_tables_md(chapter_dir, title, table_records)

    manifest = {
        "format": "subsplit-hwpmd-manifest",
        "version": 1,
        "chapter_file": f"../../{path.name}",
        "chapter_title": title,
        "fragment_sha256": sha256_text(fragment),
        "fragment_chars": len(fragment),
        "max_level": max_level,
        "order": order,
        "tables": table_records,
    }
    write_text_lp(chapter_dir / "_세부_매니페스트.json",
                  json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    write_text_lp(chapter_dir / "_구조.md",
                  f"# {title} 하위 구조\n\n" + "\n".join(tree_outline(root)) + "\n")

    return {
        "chapter": path.stem,
        "title": title,
        "leaves": len(order),
        "tables": len(table_records),
        "outline": tree_outline(root),
        "table_records": table_records,
    }


def _caption_for(fragment: str, table_start: int) -> str:
    """표 바로 앞의 가장 가까운 헤딩 제목을 캡션 추정으로 사용."""
    best = ""
    for h in find_headings(fragment):
        if h.cut <= table_start:
            best = h.title
        else:
            break
    return best.split("※")[0].strip()[:80]


def _write_chapter_tables_md(chapter_dir: Path, title: str, recs: list[dict]) -> None:
    lines = [f"# {title} 표 목록", "", f"총 {len(recs)}개", "",
             "| 표 노드 | 크기(행×열) | 소속 절 | 캡션(추정) | 복사본 |",
             "|---|---|---|---|---|"]
    for r in recs:
        lines.append(
            f"| `{r['node']}` | {r['rows']}×{r['cols']} | `{r['owner_section']}` | "
            f"{r['caption']} | [{Path(r['copy']).name}](_tables/{Path(r['copy']).name}) |"
        )
    write_text_lp(chapter_dir / "_tables.md", "\n".join(lines) + "\n")


def cmd_split(args: argparse.Namespace) -> None:
    if args.input:
        chapter_files = [args.input]
    else:
        chapter_files = sorted(
            p for p in _lp(args.parts_dir).glob("*.md")
            if p.name != "README.md" and not p.name.startswith("_")
        )
    if not chapter_files:
        raise SystemExit("처리할 장 파일이 없습니다.")

    out_root = args.output
    mkdir_lp(out_root)
    results, all_tables = [], []
    for cf in chapter_files:
        r = process_chapter(cf, out_root, args.max_level)
        results.append(r)
        all_tables.extend(r["table_records"])

    # 전체 표 색인
    write_text_lp(out_root / "_tables_index.json",
                  json.dumps(all_tables, ensure_ascii=False, indent=2) + "\n")
    idx = ["# 전체 표 색인", "", f"총 {len(all_tables)}개 표", "",
           "| 표 노드 | 행×열 | 소속 절 | 캡션(추정) |", "|---|---|---|---|"]
    for t in all_tables:
        idx.append(f"| `{t['node']}` | {t['rows']}×{t['cols']} | `{t['owner_section']}` | {t['caption']} |")
    write_text_lp(out_root / "_tables_index.md", "\n".join(idx) + "\n")

    # README(트리 요약)
    rd = ["# 세부 분류 결과", "", f"- 장 {len(results)}개, 표 {len(all_tables)}개",
          f"- 최대 세분화 레벨: h{args.max_level}", "",
          "각 장 폴더의 `_세부_매니페스트.json`으로 장 조각을 무손실 재병합할 수 있다.", ""]
    for r in results:
        rd.append(f"## {r['chapter']} ({r['leaves']}개 잎, 표 {r['tables']}개)")
        rd.extend(r["outline"])
        rd.append("")
    write_text_lp(out_root / "README.md", "\n".join(rd) + "\n")

    print(json.dumps({
        "output": str(out_root),
        "chapters": len(results),
        "leaves": sum(r["leaves"] for r in results),
        "tables": len(all_tables),
        "lossless": True,
    }, ensure_ascii=False, indent=2))


# ─────────────────────────── merge 명령 ───────────────────────────

def cmd_merge(args: argparse.Namespace) -> None:
    out_root = args.output
    reports = []
    for man_path in sorted(_lp(out_root).glob("*/_세부_매니페스트.json")):
        manifest = json.loads(read_text_lp(man_path))
        chapter_dir = man_path.parent
        pieces = []
        for rec in manifest["order"]:
            fpath = chapter_dir / rec["file"]
            t = read_text_lp(fpath)
            b, e = source_span(t, rec["file"])
            pieces.append(t[b:e])
        rebuilt = "".join(pieces)
        content_ok = sha256_text(rebuilt) == manifest["fragment_sha256"]
        # 구조 검증: 각 조각의 최상위 앵커 수가 매니페스트 기록과 일치(편집 시에도 필수)
        structure_ok = all(
            len(TOP_NODE_RE.findall(piece)) == rec["top_level_nodes"]
            for rec, piece in zip(manifest["order"], pieces)
        )
        writable = content_ok or (args.allow_edits and structure_ok)
        rec_out = {"chapter": chapter_dir.name, "content_identical": content_ok,
                   "structure_ok": structure_ok, "edited": not content_ok,
                   "chars": len(rebuilt)}
        if args.write_back:
            if writable:
                _write_back(args.write_back, manifest, rebuilt)
                rec_out["written_back"] = True
            else:
                rec_out["written_back"] = False
                rec_out["reason"] = ("구조 불일치(앵커 수 변경)" if not structure_ok
                                     else "편집됨 — --allow-edits 필요")
        reports.append(rec_out)
    print(json.dumps({
        "chapters": len(reports),
        "all_content_identical": all(r["content_identical"] for r in reports),
        "all_structure_ok": all(r["structure_ok"] for r in reports),
        "edited_chapters": [r["chapter"] for r in reports if r["edited"]],
        "reports": reports,
    }, ensure_ascii=False, indent=2))


def _write_back(parts_dir: Path, manifest: dict, fragment: str) -> None:
    chapter_name = Path(manifest["chapter_file"]).name
    cf = parts_dir / chapter_name
    text = read_text_lp(cf)
    b, e = source_span(text, cf.name)
    write_text_lp(cf, text[:b] + fragment + text[e:])


# ─────────────────────────── CLI ───────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("split", help="장 파일을 하위절로 재귀 분리")
    src = sp.add_mutually_exclusive_group(required=True)
    src.add_argument("--parts-dir", type=Path, help="장 파일 폴더(예: 연구개발계획서_장별)")
    src.add_argument("--input", type=Path, help="장 파일 하나만 처리")
    sp.add_argument("--output", type=Path, required=True, help="세부 분류 출력 폴더")
    sp.add_argument("--max-level", type=int, default=5, choices=[3, 4, 5, 6],
                    help="세분화할 최대 헤딩 레벨(기본 5 = (N)까지)")
    sp.set_defaults(func=cmd_split)

    mp = sub.add_parser("merge", help="하위절을 장 조각으로 재병합·검증")
    mp.add_argument("--output", type=Path, required=True, help="세부 분류 폴더")
    mp.add_argument("--write-back", type=Path,
                    help="검증 통과 시 장별 폴더의 장 파일 SOURCE 구간을 갱신")
    mp.add_argument("--allow-edits", action="store_true",
                    help="편집으로 내용이 바뀌어도(앵커 구조가 유지되면) 재병합·기록")
    mp.set_defaults(func=cmd_merge)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
