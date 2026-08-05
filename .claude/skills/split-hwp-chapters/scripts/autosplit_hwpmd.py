#!/usr/bin/env python3
"""hwpmd 마스터 Markdown을 장(章)별 Markdown으로 자동 분리한다.

이 도구는 `hwpmd_tool.py export`가 만든 마스터 `.md`(hwpmd/1.0)를 입력으로 받아,
본문 상단 헤딩(h1/h2)과 `## Section N:` 경계를 기준으로 장별 파일을 자동으로 나눈다.
`split_hwpmd_chapters.py`와 달리 문서별 PARTS 표를 손으로 만들지 않아도 되며,
어떤 hwpmd 마스터에도 동작한다.

산출물(모두 UTF-8, newline="" 로 바이트 보존):
  <out>/NN_<제목>.md           각 장 파일 (SOURCE 마커로 원문 구간을 감쌈)
  <out>/_복원_매니페스트.json    재병합용 매니페스트 (기존 merge_hwpmd_chapters.py 호환)
  <out>/README.md              장 목록·편집/복원 안내

핵심 불변식:
  * 장 경계는 반드시 최상위 문단 앵커(`<!--@hwp node=SN.Pdddd pid=...-->`)에서만 자른다.
    표·셀 내부에서는 절대 자르지 않는다.
  * 모든 조각을 순서대로 이으면 원본 본문과 바이트 단위로 동일하다(무손실).
  * 각 파일의 `<!--@hwp-source-begin-->`~`<!--@hwp-source-end-->` 구간만 복원 대상이다.

전체 파이프라인:
  hwp5proc xml X.hwp > X.xml
  python hwpmd_tool.py export --source X.hwp --xml X.xml --output X.md
  python autosplit_hwpmd.py --input X.md --output X_장별
  python merge_hwpmd_chapters.py --master X.md --parts-dir X_장별 --out X_병합.md   # 역변환 검증
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

BODY_BEGIN = "<!--@hwp-document-begin-->"
BODY_END = "<!--@hwp-document-end-->"
SOURCE_BEGIN = "<!--@hwp-source-begin-->"
SOURCE_END = "<!--@hwp-source-end-->"

# 최상위 문단 앵커. 셀/표 하위 노드(더 긴 경로)는 걸리지 않는다.
TOP_NODE_RE = re.compile(r"(?m)^<!--@hwp node=(S\d+\.P\d{4}) pid=")
# 앵커 바로 다음 줄의 블록 태그(헤딩 여부 판정용).
ANCHOR_BLOCK_RE = re.compile(
    r"(?m)^<!--@hwp node=(S\d+\.P\d{4}) pid=[^>]*-->\r?\n<(h[1-6]|p)\b"
)
SECTION_RE = re.compile(r"(?m)^## Section \d+:.*$")
TAG_RE = re.compile(r"<[^>]+>")


def sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def strip_tags(html_line: str) -> str:
    """HTML 블록 한 줄에서 태그를 제거하고 표시 텍스트만 뽑는다."""
    text = TAG_RE.sub("", html_line)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def sanitize(title: str, limit: int = 60) -> str:
    """제목을 파일명 안전 문자열로 변환(한글 보존)."""
    text = title.strip()
    text = re.sub(r"[·∙・]", "_", text)
    text = re.sub(r"[^0-9A-Za-z가-힣]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:limit] or "장"


def classify(title: str) -> str:
    t = title.strip()
    if t.startswith("[별첨") or t.startswith("별첨") or "붙임" in t[:4]:
        return "별첨"
    if re.match(r"^\[?\s*\d+[.\-]", t):
        return "장"
    return "공통"


def block_at(body: str, offset: int) -> str:
    """offset 이후 첫 HTML 블록 한 줄을 반환(제목 추출용)."""
    line_end = body.find("\n", offset)
    if line_end < 0:
        line_end = len(body)
    return body[offset:line_end]


def page_break_start(body: str, node: str, marker_at: int) -> int:
    """앵커 바로 앞의 명시적 쪽 나눔 주석이 있으면 그 앞으로 경계를 당긴다."""
    prefix = body[:marker_at]
    page_pattern = re.compile(
        rf'<!--@hwp page-break before={re.escape(node)} explicit="true"-->\r?\n?$'
    )
    m = page_pattern.search(prefix)
    if m:
        start = m.start()
        if start > 0 and body[start - 1] == "\n":
            start -= 1
        return start
    return marker_at


@dataclass
class SplitPoint:
    offset: int
    title: str
    kind: str  # "section" | "heading"


@dataclass
class ChapterSpec:
    filename: str
    title: str
    category: str
    fragment: str
    start_node: str | None
    end_node_exclusive: str | None
    source_range: str
    top_level_nodes: int
    fragment_sha256: str = field(default="")


def find_split_points(body: str, level: int, dedup: bool = True) -> list[SplitPoint]:
    allowed = {f"h{i}" for i in range(1, level + 1)}
    points: dict[int, SplitPoint] = {}

    # 1) 섹션 경계
    for m in SECTION_RE.finditer(body):
        title = m.group(0).lstrip("# ").strip()
        # "Section N: 라벨" -> 라벨만 사용
        label = title.split(":", 1)[1].strip() if ":" in title else title
        points[m.start()] = SplitPoint(m.start(), label, "section")

    # 2) 헤딩 경계
    for m in ANCHOR_BLOCK_RE.finditer(body):
        node, tag = m.group(1), m.group(2)
        if tag not in allowed:
            continue
        anchor_at = m.start()
        cut = page_break_start(body, node, anchor_at)
        # 앵커 다음 줄의 헤딩 블록에서 표시 텍스트를 제목으로 뽑는다.
        line = block_at(body, body.find("<" + tag, anchor_at))
        title = strip_tags(line) or node
        points.setdefault(cut, SplitPoint(cut, title, "heading"))

    ordered = [points[o] for o in sorted(points)]

    # 목차(TOC) 잡음 제거: 같은 제목이 여러 번 헤딩으로 나오면(목차 항목 + 실제 장)
    # 마지막(=실제 본문) 항목만 경계로 남기고 앞선 목차 항목은 버린다.
    # 섹션 경계는 항상 유지한다.
    if dedup:
        last_offset: dict[str, int] = {}
        for sp in ordered:
            if sp.kind == "heading":
                last_offset[sp.title] = sp.offset
        ordered = [
            sp
            for sp in ordered
            if sp.kind != "heading" or last_offset.get(sp.title) == sp.offset
        ]

    if not ordered:
        ordered = [SplitPoint(0, "본문", "heading")]
    # 첫 경계를 본문 시작(0)으로 당겨 앞부분 잔여 바이트를 첫 장에 흡수한다.
    if ordered[0].offset != 0:
        first = ordered[0]
        ordered[0] = SplitPoint(0, first.title, first.kind)
    return ordered


def build_chapters(body: str, points: list[SplitPoint]) -> list[ChapterSpec]:
    chapters: list[ChapterSpec] = []
    used_names: dict[str, int] = {}
    for i, sp in enumerate(points):
        end = points[i + 1].offset if i + 1 < len(points) else len(body)
        fragment = body[sp.offset : end]
        nodes = TOP_NODE_RE.findall(fragment)
        start_node = nodes[0] if nodes else None
        end_node_exclusive = (
            _first_node_after(body, points[i + 1].offset)
            if i + 1 < len(points)
            else None
        )
        if nodes:
            source_range = f"{nodes[0]}..{nodes[-1]}"
        else:
            source_range = sp.title

        base = f"{i:02d}_{sanitize(sp.title)}"
        if base in used_names:
            used_names[base] += 1
            base = f"{base}_{used_names[base]}"
        else:
            used_names[base] = 0
        filename = f"{base}.md"

        chapters.append(
            ChapterSpec(
                filename=filename,
                title=sp.title,
                category=classify(sp.title),
                fragment=fragment,
                start_node=start_node,
                end_node_exclusive=end_node_exclusive,
                source_range=source_range,
                top_level_nodes=len(nodes),
                fragment_sha256=sha256_text(fragment),
            )
        )
    return chapters


def _first_node_after(body: str, offset: int) -> str | None:
    m = TOP_NODE_RE.search(body, offset)
    return m.group(1) if m else None


def render_chapter(ch: ChapterSpec, master_hash: str, source_name: str, review_date: str) -> str:
    header = "\n".join(
        [
            "---",
            'split_hwpmd: "auto/1.0"',
            f'source_hwpmd: "../{source_name}"',
            f'source_sha256: "{master_hash}"',
            f'source_range: "{ch.source_range}"',
            f'source_fragment_sha256: "{ch.fragment_sha256}"',
            f'category: "{ch.category}"',
            f'generated: "{review_date}"',
            'restoration: "anchor-overlay-to-source"',
            "---",
            "",
            f"# {ch.title}",
            "",
            "> 편집 시 `<!--@hwp ...-->` 앵커, `data-hwp-*`, `rowspan`, `colspan`과 HWP 제어 주석을 "
            "삭제하거나 이름을 바꾸지 마세요. 아래 `hwp-source` 구간만 복원 대상입니다.",
            "",
            "## 원문 양식",
            "",
            SOURCE_BEGIN,
            "",
        ]
    )
    footer = "\n".join([SOURCE_END, ""])
    return header + ch.fragment + footer


def make_manifest(
    master_text: str,
    body: str,
    chapters: list[ChapterSpec],
    source_name: str,
    review_date: str,
) -> dict:
    return {
        "format": "split-hwpmd-manifest",
        "version": 1,
        "generator": "autosplit_hwpmd/1.0",
        "source_file": f"../{source_name}",
        "source_sha256": sha256_text(master_text),
        "source_body_sha256": sha256_text(body),
        "source_body_chars": len(body),
        "body_begin_marker": BODY_BEGIN,
        "body_end_marker": BODY_END,
        "source_begin_marker": SOURCE_BEGIN,
        "source_end_marker": SOURCE_END,
        "regulatory_reviewed": review_date,
        "parts": [
            {
                "filename": ch.filename,
                "title": ch.title,
                "category": ch.category,
                "source_range": ch.source_range,
                "start_node": ch.start_node,
                "end_node_exclusive": ch.end_node_exclusive,
                "fragment_sha256": ch.fragment_sha256,
                "fragment_chars": len(ch.fragment),
                "top_level_nodes": ch.top_level_nodes,
                "reference_count": 0,
                "regulatory_reviewed": review_date,
            }
            for ch in chapters
        ],
    }


def make_readme(manifest: dict, source_name: str) -> str:
    lines = [
        f"# {source_name} 장별 Markdown (자동 분리)",
        "",
        f"- 생성 기준일: {manifest['regulatory_reviewed']}",
        f"- 원본 마스터: `../{source_name}`",
        f"- 마스터 SHA-256: `{manifest['source_sha256']}`",
        f"- 생성기: `{manifest['generator']}`",
        "- 분할 원칙: 최상위 HWP 문단 앵커와 헤딩(h1/h2)·섹션 경계에서만 분리하며 표 내부에서는 자르지 않음",
        "",
        "## 편집·복원 원칙",
        "",
        "1. 각 파일의 `<!--@hwp-source-begin-->`과 `<!--@hwp-source-end-->` 사이에서만 본문을 편집합니다.",
        "2. `<!--@hwp ...-->`, `data-hwp-*`, 표의 `rowspan`·`colspan` 및 제어 주석은 삭제/개명하지 않습니다.",
        "3. `python merge_hwpmd_chapters.py --parts-dir <이 폴더>` 로 장별 원문을 마스터에 재병합합니다.",
        "4. 무편집 원본 HWP 복원은 `python hwpmd_tool.py restore-original --input ../마스터.md --output 복원본.hwp` 로 검증합니다.",
        "",
        "## 파일 목록",
        "",
        "| 구분 | 파일 | 원본 범위 |",
        "|---|---|---|",
    ]
    for item in manifest["parts"]:
        lines.append(
            f"| {item['category']} | [{item['title']}]({item['filename']}) | `{item['source_range']}` |"
        )
    lines.append("")
    return "\n".join(lines)


def hwp_to_master(hwp: Path, hwpmd_tool: Path, workdir: Path) -> Path:
    """hwp5proc + hwpmd_tool.py 로 .hwp -> 마스터 .md 파이프라인을 실행."""
    xml_path = workdir / (hwp.stem + ".xml")
    md_path = workdir / (hwp.stem + ".md")
    with xml_path.open("wb") as fh:
        subprocess.run(["hwp5proc", "xml", str(hwp)], check=True, stdout=fh)
    subprocess.run(
        [
            sys.executable,
            str(hwpmd_tool),
            "export",
            "--source",
            str(hwp),
            "--xml",
            str(xml_path),
            "--output",
            str(md_path),
        ],
        check=True,
    )
    return md_path


def run(master_path: Path, out_dir: Path, level: int, review_date: str, dedup: bool = True) -> dict:
    # newline="" 로 읽어 CRLF 마스터가 조용히 정규화되지 않도록 바이트를 보존한다.
    with master_path.open("r", encoding="utf-8", newline="") as fh:
        master = fh.read()
    if master.count(BODY_BEGIN) != 1 or master.count(BODY_END) != 1:
        raise ValueError("master must contain exactly one hwpmd document body")
    body_start = master.index(BODY_BEGIN) + len(BODY_BEGIN)
    body_end = master.index(BODY_END, body_start)
    body = master[body_start:body_end]

    points = find_split_points(body, level, dedup=dedup)
    chapters = build_chapters(body, points)

    # 무손실 검증
    rejoined = "".join(ch.fragment for ch in chapters)
    if rejoined != body:
        raise AssertionError("split fragments do not reconstruct the body exactly")

    master_hash = sha256_text(master)
    source_name = master_path.name
    out_dir.mkdir(parents=True, exist_ok=True)
    for ch in chapters:
        (out_dir / ch.filename).write_text(
            render_chapter(ch, master_hash, source_name, review_date),
            encoding="utf-8",
            newline="",
        )
    manifest = make_manifest(master, body, chapters, source_name, review_date)
    (out_dir / "_복원_매니페스트.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    (out_dir / "README.md").write_text(
        make_readme(manifest, source_name), encoding="utf-8", newline=""
    )
    return {
        "output_dir": str(out_dir),
        "chapters": len(chapters),
        "body_chars": len(body),
        "lossless": True,
        "source_sha256": manifest["source_sha256"],
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", type=Path, help="hwpmd 마스터 .md 경로")
    src.add_argument("--from-hwp", type=Path, help=".hwp 를 직접 받아 마스터 .md 부터 생성")
    p.add_argument("--output", type=Path, help="장별 출력 폴더 (기본: <마스터이름>_장별)")
    p.add_argument("--level", type=int, default=2, choices=[1, 2, 3, 4],
                   help="분리 기준 헤딩 최대 레벨 (기본 2 = h1/h2에서 분리)")
    p.add_argument("--review-date", default="", help="파일에 기록할 생성 기준일 YYYY-MM-DD")
    p.add_argument("--no-dedup", action="store_true",
                   help="목차 중복 제목 제거를 끄고 모든 헤딩에서 분리(진단용)")
    p.add_argument("--hwpmd-tool", type=Path,
                   help="--from-hwp 사용 시 hwpmd_tool.py 경로 (기본: 자동 탐색)")
    return p


def resolve_hwpmd_tool(explicit: Path | None) -> Path:
    if explicit:
        return explicit
    here = Path(__file__).resolve()
    # here = .../.agents/skills/split-hwp-chapters/scripts/autosplit_hwpmd.py
    # 스킬 폴더 위치에 상관없이 상위로 올라가며 tools/hwpmd_tool.py 를 찾는다.
    candidates = [p / "tools" / "hwpmd_tool.py" for p in here.parents]
    candidates.append(here.parent / "hwpmd_tool.py")        # 스킬 scripts/ 동봉본
    candidates.append(Path.cwd() / "tools" / "hwpmd_tool.py")  # 현재 작업 폴더
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("hwpmd_tool.py 를 찾지 못했습니다. --hwpmd-tool 로 경로를 지정하세요.")


def main() -> None:
    args = build_parser().parse_args()
    review_date = args.review_date or "미기재"

    if args.from_hwp:
        with tempfile.TemporaryDirectory() as tmp:
            master_path = hwp_to_master(
                args.from_hwp, resolve_hwpmd_tool(args.hwpmd_tool), Path(tmp)
            )
            # 마스터를 출력 폴더 옆에 보존
            out_dir = args.output or args.from_hwp.with_name(args.from_hwp.stem + "_장별")
            kept_master = out_dir.parent / (args.from_hwp.stem + ".md")
            out_dir.parent.mkdir(parents=True, exist_ok=True)
            with master_path.open("r", encoding="utf-8", newline="") as fh:
                kept_master.write_text(fh.read(), encoding="utf-8", newline="")
            result = run(kept_master, out_dir, args.level, review_date, dedup=not args.no_dedup)
            result["master_md"] = str(kept_master)
    else:
        out_dir = args.output or args.input.with_name(args.input.stem + "_장별")
        result = run(args.input, out_dir, args.level, review_date, dedup=not args.no_dedup)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
