"""raw/ 의 원본(PDF·HTML·HWPX·TXT)을 md/ 의 Markdown 으로 변환한다.

핵심 규칙: **모든 문단 앞에 출처 마커를 붙인다.**

    [S03:p12:4] 국내 수전해 시장은 2024년 기준 …

    S03 = 출처 id · p12 = 원본 12쪽(웹은 web, 한글은 hwpx) · 4 = 그 위치의 4번째 문단

파일 머리에는 출처 원장(제목·발행기관·연도·URL·수집일시·sha256)을 YAML frontmatter 로 넣는다.
따라서 md 조각 하나만 봐도 어디서 왔는지 추적된다.

사용:
    python to_md.py --dir research/<주제>
    python to_md.py --dir research/<주제> --only S03 --tables
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import is_noise, load_manifest, load_sources, norm_ws, slugify  # noqa: E402


# ─────────────────────────────── PDF ───────────────────────────────

def pdf_blocks(path: Path, want_tables: bool) -> list[tuple[str, list[str]]]:
    """[(loc, [문단…]), …] — loc 은 'p1', 'p2' …"""
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # 구버전 호환
        except ImportError:
            raise SystemExit("[!] PyMuPDF 가 필요합니다: python -m pip install PyMuPDF")

    doc = pymupdf.open(str(path))
    pages: list[list[str]] = []
    for page in doc:
        blocks = [b for b in page.get_text("blocks") if len(b) > 6 and b[6] == 0]
        blocks.sort(key=lambda b: (round(b[1], 1), round(b[0], 1)))
        pages.append([norm_ws(b[4]) for b in blocks])
    doc.close()

    # 머리말·꼬리말 제거: 전체 쪽수의 40% 이상에서 반복되는 짧은 줄
    if len(pages) >= 5:
        from collections import Counter
        c = Counter(t for pg in pages for t in set(pg) if len(t) <= 60)
        repeated = {t for t, n in c.items() if n >= max(3, int(len(pages) * 0.4))}
    else:
        repeated = set()

    tables_by_page: dict[int, list[str]] = {}
    if want_tables:
        tables_by_page = pdf_tables(path)

    out: list[tuple[str, list[str]]] = []
    for i, paras in enumerate(pages, start=1):
        keep = [t for t in paras if t and t not in repeated and not is_noise(t)]
        keep += tables_by_page.get(i, [])
        if keep:
            out.append((f"p{i}", keep))
    return out


def pdf_tables(path: Path) -> dict[int, list[str]]:
    """pdfplumber 로 표를 뽑아 Markdown 표 문자열로 만든다(선택 기능)."""
    try:
        import pdfplumber
    except ImportError:
        print("  [i] pdfplumber 미설치 — 표 추출을 건너뜁니다.")
        return {}
    res: dict[int, list[str]] = {}
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            for tbl in page.extract_tables() or []:
                rows = [[norm_ws(str(c or "")) for c in row] for row in tbl if any(row)]
                if len(rows) < 2:
                    continue
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                md = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
                md += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                res.setdefault(i, []).append("<!--표--> " + " ⏎ ".join(md))
    return res


# ─────────────────────────────── HTML ───────────────────────────────

class _Extract(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside",
            "form", "svg", "iframe", "button", "select"}
    BLOCK = {"p", "div", "li", "tr", "br", "section", "article", "blockquote",
             "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "dd", "dt", "pre"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.buf: list[str] = []
        self.parts: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self.depth == 0 and data.strip():
            self.buf.append(data)

    def _flush(self):
        if self.buf:
            t = norm_ws("".join(self.buf))
            if t:
                self.parts.append(t)
            self.buf = []

    def close(self):
        super().close()
        self._flush()


def html_blocks(path: Path) -> tuple[list[tuple[str, list[str]]], str]:
    raw = path.read_bytes()
    text = ""
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:4096], re.I)
    encs = ([m.group(1).decode("ascii", "ignore")] if m else []) + ["utf-8", "cp949", "euc-kr"]
    for enc in encs:
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if not text:
        text = raw.decode("utf-8", "replace")

    p = _Extract()
    p.feed(text)
    p.close()
    paras = [t for t in p.parts if not is_noise(t) and len(t) >= 8]
    # 인접 중복(메뉴 반복) 제거
    dedup: list[str] = []
    for t in paras:
        if not dedup or dedup[-1] != t:
            dedup.append(t)
    return ([("web", dedup)] if dedup else []), html.unescape(p.title.strip())


# ─────────────────────────────── HWPX / TXT ───────────────────────────────

def hwpx_blocks(path: Path) -> list[tuple[str, list[str]]]:
    paras: list[str] = []
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist()
                       if n.startswith("Contents/section") and n.endswith(".xml"))
        for name in names:
            root = ET.fromstring(z.read(name))
            for el in root.iter():
                if el.tag.rsplit("}", 1)[-1] != "p":
                    continue
                buf = [t.text or "" for t in el.iter() if t.tag.rsplit("}", 1)[-1] == "t"]
                t = norm_ws("".join(buf))
                if t and not is_noise(t):
                    paras.append(t)
    return [("hwpx", paras)] if paras else []


def text_blocks(path: Path) -> list[tuple[str, list[str]]]:
    raw = path.read_bytes()
    for enc in ("utf-8", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "replace")
    paras = [norm_ws(p) for p in re.split(r"\n\s*\n", text)]
    paras = [p for p in paras if p and not is_noise(p)]
    return [("txt", paras)] if paras else []


# ─────────────────────────────── 조립 ───────────────────────────────

def yaml_q(v) -> str:
    s = str(v or "")
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(sid: str, src: dict, meta: dict,
           groups: list[tuple[str, list[str]]]) -> tuple[str, int]:
    publisher = src.get("publisher") or "(발행기관 미상)"
    url = meta.get("final_url") or src.get("url") or "(로컬 파일)"
    fm = [
        "---",
        f"source_id: {sid}",
        f"title: {yaml_q(src.get('title') or meta.get('title'))}",
        f"publisher: {yaml_q(src.get('publisher'))}",
        f"year: {yaml_q(src.get('year'))}",
        f"kind: {yaml_q(src.get('kind'))}",
        f"url: {yaml_q(meta.get('final_url') or src.get('url'))}",
        f"origin_file: {yaml_q(meta.get('file'))}",
        f"fetched_at: {yaml_q(meta.get('fetched_at'))}",
        f"sha256: {yaml_q(meta.get('sha256'))}",
        f"cite_prefix: {yaml_q('[' + sid + ':<loc>:<n>]')}",
        "---",
        "",
        f"# [{sid}] {src.get('title') or meta.get('title') or sid}",
        "",
        f"> 출처: {publisher} · {src.get('year') or '연도미상'} · {url}",
        f"> 수집: {meta.get('fetched_at') or '-'} · 원본: `{meta.get('file') or '-'}`",
        "",
        "각 문단 앞 `[출처ID:위치:문단번호]` 가 그 문장이 원본 어디에서 나왔는지 가리킨다.",
        "",
    ]
    body: list[str] = []
    total = 0
    for loc, paras in groups:
        body.append(f"## {loc}")
        body.append("")
        for n, t in enumerate(paras, start=1):
            body.append(f"[{sid}:{loc}:{n}] {t}")
            body.append("")
            total += 1
    return "\n".join(fm + body).rstrip() + "\n", total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--tables", action="store_true", help="PDF 표를 pdfplumber 로 함께 추출")
    args = ap.parse_args()

    root = Path(args.dir).resolve()
    data = load_sources(root)
    manifest = load_manifest(root)
    outdir = root / "md"
    outdir.mkdir(parents=True, exist_ok=True)

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    index: list[str] = []
    done = 0

    for src in data["sources"]:
        sid = src["id"]
        if only and sid not in only:
            continue
        meta = manifest.get(sid, {})
        rel = meta.get("file")
        if not rel:
            print(f"  {sid}  [!] 내려받은 파일 없음 — fetch.py 를 먼저 실행하세요.")
            continue
        path = root / rel
        if not path.exists():
            print(f"  {sid}  [!] 파일 없음: {path}")
            continue

        ext = path.suffix.lower()
        title_from_doc = ""
        if ext == ".pdf":
            groups = pdf_blocks(path, args.tables)
        elif ext in (".html", ".htm"):
            groups, title_from_doc = html_blocks(path)
        elif ext == ".hwpx":
            groups = hwpx_blocks(path)
        elif ext in (".txt", ".md"):
            groups = text_blocks(path)
        elif ext == ".hwp":
            print(f"  {sid}  [!] .hwp 는 먼저 .hwpx 로 변환하세요 "
                  f"(hwpx-yaml-roundtrip/scripts/hwp2hwpx.py). 건너뜁니다.")
            continue
        else:
            print(f"  {sid}  [!] 지원하지 않는 형식: {ext} — 건너뜁니다.")
            continue

        if not groups:
            print(f"  {sid}  [!] 추출된 본문 없음(스캔 PDF·JS 렌더링 의심) — 수동 확인 필요")
            continue

        if not meta.get("title"):
            meta["title"] = title_from_doc
        text, n = render(sid, src, meta, groups)
        name = f"{sid}_{slugify(src.get('title') or sid)}.md"
        (outdir / name).write_text(text, encoding="utf-8")
        locs = len(groups)
        print(f"  {sid}  → md/{name}  (문단 {n}개 / 위치 {locs}개)")
        index.append(
            f"- **{sid}** [{src.get('title') or sid}](./{name}) — "
            f"{src.get('publisher') or '-'} · {src.get('year') or '-'} · "
            f"{src.get('kind') or '-'} · 문단 {n}"
        )
        done += 1

    if index:
        (outdir / "INDEX.md").write_text(
            "# 수집 자료 색인\n\n"
            f"주제: **{data.get('topic', '(미기재)')}**\n\n"
            "본문 인용 시 각 문단 앞의 `[출처ID:위치:문단번호]` 를 그대로 옮겨 붙인다.\n\n"
            + "\n".join(index) + "\n",
            encoding="utf-8",
        )
    print(f"\n완료: {done}건 변환 → {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
