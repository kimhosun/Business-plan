"""작성된 문서의 출처 마커가 실제 수집 자료와 맞는지 검증한다.

검사 항목
  1. 문서에 쓴 `[S03:p12:4]` 가 md/ 코퍼스에 실제로 존재하는가 (유령 인용 탐지)
  2. 인용한 문장이 원문 문단과 실제로 겹치는가 (--strict, 어절 겹침률)
  3. 수치·연도·비율이 들어간 문단에 인용이 붙어 있는가 (무출처 주장 탐지)
  4. 수집했지만 한 번도 쓰이지 않은 출처

사용:
    python cite_check.py --dir research/<주제> --doc research/<주제>/report.md
    python cite_check.py --dir research/<주제> --doc ... --strict
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CITE_RE, norm_ws  # noqa: E402

# 근거가 필요한 주장으로 볼 신호: 연도·퍼센트·금액·규모 표현
CLAIM_RE = re.compile(
    r"(\b(19|20)\d{2}\s*년|\d+(\.\d+)?\s*%|\d+\s*(억|조|천만|만)\s*원|"
    r"\d+(\.\d+)?\s*(배|위|건|개사|명)|세계\s*\d|점유율|연평균)"
)


def load_corpus(md_dir: Path) -> dict[str, str]:
    """{'[S03:p12:4]': 문단본문} 사전."""
    corpus: dict[str, str] = {}
    for f in sorted(md_dir.glob("*.md")):
        if f.name == "INDEX.md":
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            m = CITE_RE.match(line.strip())
            if m:
                corpus[m.group(0)] = line.strip()[m.end():].strip()
    return corpus


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", norm_ws(text))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="조사 폴더(md/ 가 있는 곳)")
    ap.add_argument("--doc", required=True, help="검증할 작성 문서(.md)")
    ap.add_argument("--strict", action="store_true", help="원문과 어절 겹침까지 검사")
    ap.add_argument("--overlap", type=float, default=0.25, help="--strict 겹침 하한(기본 0.25)")
    args = ap.parse_args()

    root = Path(args.dir).resolve()
    md_dir = root / "md"
    if not md_dir.exists():
        raise SystemExit(f"[!] {md_dir} 가 없습니다. to_md.py 를 먼저 실행하세요.")
    doc = Path(args.doc).resolve()
    if not doc.exists():
        raise SystemExit(f"[!] 문서가 없습니다: {doc}")

    corpus = load_corpus(md_dir)
    text = doc.read_text(encoding="utf-8")
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]

    ghosts: list[tuple[int, str]] = []
    weak: list[tuple[int, str, float]] = []
    unsourced: list[tuple[int, str]] = []
    used: set[str] = set()

    in_code = False
    for i, para in enumerate(paras, start=1):
        if para.lstrip().startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        cites = CITE_RE.findall(para)
        keys = [f"[{a}:{b}:{c}]" for a, b, c in cites]
        for k in keys:
            if k not in corpus:
                ghosts.append((i, k))
            else:
                used.add(k)
        if args.strict and keys:
            src_tok: set[str] = set()
            for k in keys:
                src_tok |= tokens(corpus.get(k, ""))
            body = CITE_RE.sub("", para)
            body_tok = tokens(body)
            if body_tok and src_tok:
                ov = len(body_tok & src_tok) / len(body_tok)
                if ov < args.overlap:
                    weak.append((i, para.strip()[:70], ov))
        if not keys and CLAIM_RE.search(para) and not para.lstrip().startswith(("#", "|", ">")):
            unsourced.append((i, para.strip()[:70]))

    all_ids = {k.split(":")[0][1:] for k in corpus}
    used_ids = {k.split(":")[0][1:] for k in used}
    unused_ids = sorted(all_ids - used_ids)

    print(f"문서: {doc}")
    print(f"코퍼스: {len(corpus):,} 문단 / 출처 {len(all_ids)}건")
    print(f"인용: {len(used):,} 문단 인용 · 사용 출처 {len(used_ids)}건\n")

    bad = False
    if ghosts:
        bad = True
        print(f"[X] 코퍼스에 없는 인용 {len(ghosts)}건 — 지어낸 출처이거나 오타:")
        for i, k in ghosts[:30]:
            print(f"    문단 {i}: {k}")
        if len(ghosts) > 30:
            print(f"    … 외 {len(ghosts)-30}건")
        print()
    if weak:
        bad = True
        print(f"[!] 원문과 겹침이 낮은 문단 {len(weak)}건 (하한 {args.overlap}) — 인용 위치 재확인:")
        for i, s, ov in weak[:20]:
            print(f"    문단 {i} (겹침 {ov:.2f}): {s}…")
        print()
    if unsourced:
        print(f"[!] 수치·연도가 있으나 인용이 없는 문단 {len(unsourced)}건:")
        for i, s in unsourced[:20]:
            print(f"    문단 {i}: {s}…")
        print()
    if unused_ids:
        print(f"[i] 수집했으나 인용되지 않은 출처: {', '.join(unused_ids)}\n")

    if not bad and not unsourced:
        print("통과: 모든 인용이 수집 자료로 추적됩니다.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
