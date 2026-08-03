#!/usr/bin/env python3
"""Inventory regulation-related Markdown links without deciding currentness."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse


OFFICIAL_DOMAINS = (
    "law.go.kr",
    "motie.go.kr",
    "motir.go.kr",
    "msit.go.kr",
    "moel.go.kr",
    "moleg.go.kr",
    "iris.go.kr",
    "keit.re.kr",
    "srome.keit.re.kr",
    "kistep.re.kr",
    "ketep.re.kr",
    "rcms.go.kr",
    "zeus.go.kr",
    "itube.or.kr",
    "gwanbo.go.kr",
    "digitalmarket.kr",
)

LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
BARE_URL_RE = re.compile(r"https?://[^\s<>\"']+")
BRACKETED_TITLE_RE = re.compile(r"「([^」\r\n]{2,1000})」")
QUOTED_TITLE_RES = (
    re.compile(r"[“\"]([^”\"\r\n]{2,300})[”\"]"),
    re.compile(r"[‘']([^’'\r\n]{2,300})[’']"),
    re.compile(r"『([^』\r\n]{2,300})』"),
)
REVIEW_RE = re.compile(
    r"(?:regulatory_reviewed:\s*[\"']?|확인\s*기준일:\s*)(\d{4}-\d{2}-\d{2})"
)
NUMERIC_VALUE_RE = re.compile(
    r"\d[\d,.]*\s*(?:%|퍼센트|억원|억\s*원|천만원|천만\s*원|백만원|백만\s*원|만원|원|개월|시간|세|명|일|년|회|건|개|대|주)"
)
RISK_WORD_RE = re.compile(
    r"이상|이하|초과|미만|한도|사전승인|승인|보고|제출|의무|계상|지원|채용|검수|필수|제외|감면"
)
REGULATION_TERMS = (
    "법",
    "시행령",
    "시행규칙",
    "고시",
    "예규",
    "훈령",
    "요령",
    "지침",
    "기준",
    "계획",
    "공고",
    "rFP",
    "RFP",
    "규정",
    "가이드",
    "매뉴얼",
    "RCMS",
    "IRIS",
    "ZEUS",
    "SROME",
    "TRL",
    "기술준비도",
    "지표",
)


@dataclass(frozen=True)
class Citation:
    file: str
    line: int
    label: str
    url: str
    domain: str
    source_type: str
    nature: str
    review_date: str | None
    region: str
    flags: tuple[str, ...]
    context: str


@dataclass(frozen=True)
class Mention:
    file: str
    line: int
    title: str
    kind: str
    region: str
    linked_on_line: bool
    context: str


@dataclass(frozen=True)
class BareUrl:
    file: str
    line: int
    url: str
    domain: str
    source_type: str
    nature: str
    region: str
    flags: tuple[str, ...]
    context: str


def iter_markdown(paths: list[Path]) -> list[Path]:
    found: set[Path] = set()
    for path in paths:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".md":
            found.add(path)
        elif path.is_dir():
            found.update(p for p in path.rglob("*.md") if p.is_file())
        else:
            raise FileNotFoundError(path)
    return sorted(found, key=lambda p: str(p).lower())


def is_official(domain: str) -> bool:
    domain = domain.lower().split(":", 1)[0]
    return any(domain == item or domain.endswith("." + item) for item in OFFICIAL_DOMAINS)


def classify(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()
    if "law.go.kr" in domain:
        if "admrulsc" in path or "lssc" in path:
            return "search-page"
        if "admrul" in path or "행정규칙" in path:
            return "administrative-rule"
        if "법령" in path or "lsinfo" in path or "lslink" in path:
            return "legislation"
        return "legal-portal"
    if "motie.go.kr" in domain or "motir.go.kr" in domain:
        return "ministry-publication"
    if (
        domain in ("www.iris.go.kr", "iris.go.kr", "itech.keit.re.kr")
        and path in ("", "/")
    ):
        return "official-system"
    if any(
        item in domain
        for item in ("iris.go.kr", "keit.re.kr", "kistep.re.kr", "ketep.re.kr")
    ):
        return "agency-guidance"
    if any(
        item in domain
        for item in ("rcms.go.kr", "zeus.go.kr", "itube.or.kr", "digitalmarket.kr")
    ):
        return "official-system"
    return "web"


def nature_for(source_type: str, instrument: str) -> str:
    if source_type in ("legislation", "administrative-rule", "legal-portal"):
        return "legal_authority"
    if source_type == "official-system":
        return "official_system"
    if any(
        term in instrument
        for term in ("공고", "RFP", "협약", "통보문", "요청문", "수요조사", "시행계획")
    ):
        return "project_document"
    return "official_guidance"


def flags_for(
    url: str,
    source_type: str,
    review_date: str | None,
    instrument: str,
    as_of: str,
) -> tuple[str, ...]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    flags: list[str] = []
    if not is_official(parsed.netloc):
        flags.append("non-official")
    if source_type == "search-page":
        flags.append("search-page")
    if any(key in query for key in ("lsiSeq", "admRulSeq", "admRulId", "efYd")):
        flags.append("pinned-version")
    if (
        "시행령" in instrument
        and ("법" in instrument or "법률" in instrument)
        and ("·" in instrument or "및" in instrument)
    ) or "시행령·시행규칙" in instrument:
        flags.append("multi-instrument-single-link")
    if parsed.path in ("", "/") and source_type in (
        "official-system",
        "agency-guidance",
    ):
        flags.append("generic-homepage")
    if review_date is None:
        flags.append("missing-review-date")
    elif review_date < as_of:
        flags.append("stale-review-date")
    elif review_date > as_of:
        flags.append("review-date-after-as-of")
    return tuple(flags)


def relevant(label: str, context: str, url: str) -> bool:
    haystack = f"{label} {context} {url}"
    return is_official(urlparse(url).netloc) or any(
        term in haystack for term in REGULATION_TERMS
    )


def table_instrument(line: str, fallback: str) -> str:
    if not line.lstrip().startswith("|"):
        return fallback
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if not cells:
        return fallback
    first = re.sub(r"[*_`]", "", cells[0]).strip()
    if first and not re.fullmatch(r":?-{3,}:?", first):
        return first
    return fallback


def plain_text(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", "", value))
    return re.sub(r"\s+", " ", value).strip()


def scan(
    path: Path, root: Path, as_of: str
) -> tuple[list[Citation], list[Mention], list[BareUrl], list[str]]:
    text = path.read_text(encoding="utf-8")
    review_match = REVIEW_RE.search(text)
    review_date = review_match.group(1) if review_match else None
    citations: list[Citation] = []
    mentions: list[Mention] = []
    bare_urls: list[BareUrl] = []
    file_flags: list[str] = []
    if "[해당 세부사업 공고/RFP 직접 링크 삽입]" in text:
        file_flags.append("project-link-placeholder")
    if review_date is None:
        file_flags.append("missing-review-date")
    elif review_date < as_of:
        file_flags.append("stale-review-date")
    elif review_date > as_of:
        file_flags.append("review-date-after-as-of")
    relative = str(path.relative_to(root)).replace("\\", "/")
    in_hwp_source = False
    for line_no, line in enumerate(text.splitlines(), 1):
        if "<!--@hwp-source-begin-->" in line:
            in_hwp_source = True
        region = "hwp-source" if in_hwp_source else "annotation"
        linked_on_line = bool(LINK_RE.search(line))
        linked_urls = {match.group(2).strip() for match in LINK_RE.finditer(line)}
        for match in LINK_RE.finditer(line):
            label, url = match.groups()
            instrument = table_instrument(line, label.strip())
            if not relevant(instrument, line, url):
                continue
            parsed = urlparse(url)
            source_type = classify(url)
            citations.append(
                Citation(
                    file=relative,
                    line=line_no,
                    label=instrument,
                    url=url.strip(),
                    domain=parsed.netloc.lower(),
                    source_type=source_type,
                    nature=nature_for(source_type, instrument),
                    review_date=review_date,
                    region=region,
                    flags=flags_for(
                        url, source_type, review_date, instrument, as_of
                    ),
                    context=line.strip()[:500],
                )
            )
        for url_match in BARE_URL_RE.finditer(line):
            url = url_match.group(0).rstrip(").,;]")
            if url in linked_urls:
                continue
            parsed = urlparse(url)
            source_type = classify(url)
            bare_urls.append(
                BareUrl(
                    file=relative,
                    line=line_no,
                    url=url,
                    domain=parsed.netloc.lower(),
                    source_type=source_type,
                    nature=nature_for(source_type, "bare URL"),
                    region=region,
                    flags=flags_for(
                        url, source_type, review_date, "bare URL", as_of
                    ),
                    context=line.strip()[:500],
                )
            )
        plain_line = plain_text(line)
        title_matches = [match.group(1) for match in BRACKETED_TITLE_RE.finditer(plain_line)]
        for pattern in QUOTED_TITLE_RES:
            title_matches.extend(match.group(1) for match in pattern.finditer(plain_line))
        seen_titles: set[str] = set()
        for raw_title in title_matches:
            title = plain_text(raw_title)
            if "/" in title or title.lower().endswith((".md", ".json", ".hwp", ".hwpx")):
                continue
            if not any(term in title for term in REGULATION_TERMS):
                continue
            if title in seen_titles:
                continue
            seen_titles.add(title)
            mentions.append(
                Mention(
                    file=relative,
                    line=line_no,
                    title=title,
                    kind="named-instrument",
                    region=region,
                    linked_on_line=linked_on_line,
                    context=line.strip()[:500],
                )
            )
        if (
            in_hwp_source
            and ("TRL" in line or "기술준비도" in line)
            and re.search(r"비지원|평가지표|단계", line)
        ):
            claim = plain_text(line)
            mentions.append(
                Mention(
                    file=relative,
                    line=line_no,
                    title=f"TRL 주장: {claim[:220]}",
                    kind="trl-claim",
                    region=region,
                    linked_on_line=linked_on_line,
                    context=line.strip()[:500],
                )
            )
        if in_hwp_source and NUMERIC_VALUE_RE.search(line) and RISK_WORD_RE.search(line):
            claim = plain_text(line)
            mentions.append(
                Mention(
                    file=relative,
                    line=line_no,
                    title=f"수치 주장: {claim[:220]}",
                    kind="numeric-claim",
                    region=region,
                    linked_on_line=linked_on_line,
                    context=line.strip()[:500],
                )
            )
        if "<!--@hwp-source-end-->" in line:
            in_hwp_source = False
    return citations, mentions, bare_urls, file_flags


def markdown_report(payload: dict) -> str:
    mention_counts = payload["summary"]["mention_counts"]
    lines = [
        "# 규정 인용 인벤토리",
        "",
        f"- 파일: {payload['summary']['files']}개",
        f"- 인용: {payload['summary']['citations']}개",
        f"- Markdown 링크 고유 URL: {payload['summary']['unique_urls']}개",
        f"- 전체 고유 URL: {payload['summary']['all_unique_urls']}개",
        f"- 전체 공식 출처 고유 URL: {payload['summary']['official_urls']}개",
        f"- 검토 후보: {payload['summary']['inline_mentions']}개 "
        f"(규정명 {mention_counts['named-instrument']}, TRL 주장 {mention_counts['trl-claim']}, "
        f"고위험 수치 주장 {mention_counts['numeric-claim']})",
        f"- Markdown 링크가 아닌 URL: {payload['summary']['bare_urls']}개",
        "",
        "> 이 결과는 인용 목록과 위험 신호만 추출합니다. 현행성은 공식 원문을 열어 별도로 판정해야 합니다.",
        "",
        "| 파일·줄 | 표기 | 유형 | 검토일 | 경고 | URL |",
        "|---|---|---|---|---|---|",
    ]
    for item in payload["citations"]:
        flags = ", ".join(item["flags"]) or "-"
        label = item["label"].replace("|", "\\|")
        lines.append(
            f"| `{item['file']}:{item['line']}` | {label} | {item['source_type']} | "
            f"{item['review_date'] or '-'} | {flags} | [열기]({item['url']}) |"
        )
    if payload["file_flags"]:
        lines.extend(["", "## 파일 단위 경고", ""])
        for filename, flags in payload["file_flags"].items():
            lines.append(f"- `{filename}`: {', '.join(flags)}")
    if payload["mentions"]:
        lines.extend(
            [
                "",
                "## 본문 내 검토 후보",
                "",
                "| 파일·줄 | 유형 | 표기·주장 | 영역 | 같은 줄 링크 |",
                "|---|---|---|---|---|",
            ]
        )
        for item in payload["mentions"]:
            lines.append(
                f"| `{item['file']}:{item['line']}` | {item['kind']} | {item['title']} | "
                f"{item['region']} | {'예' if item['linked_on_line'] else '아니오'} |"
            )
    if payload["bare_urls"]:
        lines.extend(
            [
                "",
                "## Markdown 링크가 아닌 URL",
                "",
                "| 파일·줄 | 영역 | 유형 | 경고 | URL |",
                "|---|---|---|---|---|",
            ]
        )
        for item in payload["bare_urls"]:
            flags = ", ".join(item["flags"]) or "-"
            lines.append(
                f"| `{item['file']}:{item['line']}` | {item['region']} | "
                f"{item['source_type']} | {flags} | [열기]({item['url']}) |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Extract regulation-related citations from Markdown files."
    )
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--as-of",
        default=date.today().isoformat(),
        help="audit date in YYYY-MM-DD (defaults to today)",
    )
    args = parser.parse_args()
    date.fromisoformat(args.as_of)

    cwd = Path.cwd().resolve()
    files = iter_markdown(args.paths)
    citations: list[Citation] = []
    mentions: list[Mention] = []
    bare_urls: list[BareUrl] = []
    file_flags: dict[str, list[str]] = {}
    for path in files:
        items, inline_items, bare_items, flags = scan(path, cwd, args.as_of)
        citations.extend(items)
        mentions.extend(inline_items)
        bare_urls.extend(bare_items)
        if flags:
            relative = str(path.relative_to(cwd)).replace("\\", "/")
            file_flags[relative] = flags

    urls = {item.url for item in citations}
    bare_url_set = {item.url for item in bare_urls}
    all_urls = urls | bare_url_set
    mention_counts = {
        kind: sum(item.kind == kind for item in mentions)
        for kind in ("named-instrument", "trl-claim", "numeric-claim")
    }
    payload = {
        "summary": {
            "as_of": args.as_of,
            "files": len(files),
            "citations": len(citations),
            "unique_urls": len(urls),
            "official_markdown_urls": len(
                {url for url in urls if is_official(urlparse(url).netloc)}
            ),
            "official_urls": len(
                {url for url in all_urls if is_official(urlparse(url).netloc)}
            ),
            "inline_mentions": len(mentions),
            "mention_counts": mention_counts,
            "bare_urls": len(bare_urls),
            "all_unique_urls": len(all_urls),
        },
        "file_flags": file_flags,
        "citations": [asdict(item) for item in citations],
        "mentions": [asdict(item) for item in mentions],
        "bare_urls": [asdict(item) for item in bare_urls],
    }
    output = (
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if args.format == "json"
        else markdown_report(payload)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8", newline="")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
