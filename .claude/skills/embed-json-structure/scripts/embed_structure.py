#!/usr/bin/env python3
"""분류된 hwpmd Markdown 원본에 JSON 입력구조를 삽입한다(SOURCE 구간 밖).

각 .md 의 `<!--@hwp-source-end-->` 뒤에 `## 입력구조(JSON)` 섹션을 만들고
```json 블록을 넣는다. 이 블록은 `<!--@tmpl-json-begin-->`~`<!--@tmpl-json-end-->`
주석으로 감싸 idempotent하게 교체·제거할 수 있다.

핵심: 삽입 위치가 SOURCE 구간(`<!--@hwp-source-begin/end-->`) **밖**이므로
장→마스터 재병합과 원본 HWP 복원에 전혀 영향이 없다(merge는 SOURCE 구간만 읽는다).

서브커맨드:
  embed   각 md에 JSON 입력구조 섹션을 삽입/갱신(있으면 교체).
          구조는 옆의 `<md>.tmpl.json`이 있으면 그걸, 없으면 fill-hwp-template의
          extract 로직으로 즉석 생성.
  read    md에 박힌 JSON을 꺼낸다(stdout 또는 --to-sidecar 로 `<md>.tmpl.json` 기록).
  strip   삽입한 JSON 섹션을 제거해 원래 md로 되돌린다.

전형적 사용:
  embed → (md 안 JSON 편집) → read --to-sidecar → fill-hwp-template apply → 재병합
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SOURCE_BEGIN = "<!--@hwp-source-begin-->"
SOURCE_END = "<!--@hwp-source-end-->"
JSON_BEGIN = "<!--@tmpl-json-begin-->"
JSON_END = "<!--@tmpl-json-end-->"
SECTION_TITLE = "## 입력구조(JSON)"
FENCE = "```json"

# fill-hwp-template 의 추출 로직 재사용(사이드카가 없을 때).
_SIB = Path(__file__).resolve().parents[2] / "fill-hwp-template" / "scripts"
if _SIB.exists():
    sys.path.insert(0, str(_SIB))
try:
    from input_template import extract_file as _extract_file  # type: ignore
except Exception:
    _extract_file = None


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


def has_source_region(text: str) -> bool:
    return text.count(SOURCE_BEGIN) == 1 and text.count(SOURCE_END) == 1


def remove_block(text: str) -> str:
    """삽입된 JSON 블록을 제거(삽입의 정확한 역연산). 앞 구분 개행 1개 + 블록 +
    블록 뒤 개행 1개만 제거하므로 원본 끝 개행은 보존된다."""
    i = text.find(JSON_BEGIN)
    if i < 0:
        return text
    start = i
    if start > 0 and text[start - 1] == "\n":   # 구분 개행 1개만 제거
        start -= 1
    j = text.find(JSON_END, i)
    if j < 0:
        # 손상된 블록(END 없음): BEGIN부터 끝까지 제거(블록은 항상 파일 끝에 있음)
        return text[:start]
    end = j + len(JSON_END)
    if end < len(text) and text[end] == "\n":
        end += 1
    return text[:start] + text[end:]


def read_embedded(text: str) -> dict | None:
    i = text.find(JSON_BEGIN)
    j = text.find(JSON_END, i)
    if i < 0 or j < 0:
        return None
    block = text[i:j]
    m = re.search(r"```json\r?\n(.*?)\r?\n```", block, re.S)
    if not m:
        return None
    return json.loads(m.group(1))


def make_block(struct: dict) -> str:
    payload = json.dumps(struct, ensure_ascii=False, indent=2)
    # 안전장치: SOURCE 마커나 펜스 종료가 페이로드에 있으면 삽입하지 않는다.
    if SOURCE_BEGIN in payload or SOURCE_END in payload:
        raise ValueError("구조 JSON에 SOURCE 마커가 들어 있어 삽입 불가")
    if "```" in payload:
        raise ValueError("구조 JSON에 코드펜스(```)가 들어 있어 삽입 불가")
    # 선두 개행 = 원본과의 구분 빈 줄. remove_block이 이 개행 1개만 되돌린다.
    return (f"\n{JSON_BEGIN}\n{SECTION_TITLE}\n\n{FENCE}\n{payload}\n```\n{JSON_END}\n")


def structure_for(path: Path, prefer_extract: bool = False) -> dict | None:
    """사이드카가 있으면 사용, 없으면 extract로 생성.
    prefer_extract=True면 사이드카를 무시하고 SOURCE에서 새로 추출한다."""
    sidecar = path.with_suffix(path.suffix + ".tmpl.json")
    if not prefer_extract and _lp(sidecar).exists():
        return json.loads(read_text_lp(sidecar))
    if _extract_file is not None:
        return _extract_file(path, path.name)
    if _lp(sidecar).exists():                     # extract 불가 시 사이드카로 대체
        return json.loads(read_text_lp(sidecar))
    raise RuntimeError(
        "구조를 만들 수 없습니다. fill-hwp-template의 input_template.py 를 찾지 못했고 "
        f"사이드카({sidecar.name})도 없습니다.")


# ─────────────────────────── 명령 ───────────────────────────

def cmd_embed(args: argparse.Namespace) -> None:
    reports = []
    for path, rel in _targets(args):
        text = read_text_lp(path)
        if not has_source_region(text):
            continue
        try:
            struct = structure_for(path, getattr(args, "re_extract", False))
            if struct is None:
                reports.append({"file": rel, "embedded": False, "reason": "구조 없음"})
                continue
            # make_block의 선두 개행이 구분자 겸 strip의 복원 기준이다.
            # base의 종료 개행을 인위적으로 바꾸지 않아야 embed↔strip이 완전 가역.
            base = remove_block(text)
            new = base + make_block(struct)
            # 삽입 후에도 SOURCE 구간이 정확히 1쌍인지 확인(불변식)
            if not has_source_region(new):
                reports.append({"file": rel, "embedded": False, "reason": "SOURCE 구간 손상 위험"})
                continue
            write_text_lp(path, new)
        except (ValueError, RuntimeError, json.JSONDecodeError) as ex:
            reports.append({"file": rel, "embedded": False, "reason": str(ex)})
            continue
        reports.append({"file": rel, "embedded": True,
                        "fields": len(struct.get("fields", [])),
                        "tables": len(struct.get("tables", []))})
    _print(reports, "embedded")


def cmd_read(args: argparse.Namespace) -> None:
    reports = []
    for path, rel in _targets(args):
        text = read_text_lp(path)
        try:
            struct = read_embedded(text)
        except json.JSONDecodeError as ex:
            reports.append({"file": rel, "error": f"JSON 파싱 실패: {ex}"})
            continue
        if struct is None:
            continue
        if args.to_sidecar:
            sc = path.with_suffix(path.suffix + ".tmpl.json")
            write_text_lp(sc, json.dumps(struct, ensure_ascii=False, indent=2) + "\n")
            reports.append({"file": rel, "sidecar": sc.name})
        elif args.file:
            print(json.dumps(struct, ensure_ascii=False, indent=2))
            return
        else:
            reports.append({"file": rel, "fields": len(struct.get("fields", [])),
                            "tables": len(struct.get("tables", []))})
    _print(reports, "read")


def cmd_strip(args: argparse.Namespace) -> None:
    reports = []
    for path, rel in _targets(args):
        text = read_text_lp(path)
        if JSON_BEGIN not in text:
            continue
        new = remove_block(text)
        if new != text:
            write_text_lp(path, new)
            reports.append({"file": rel, "stripped": True})
    _print(reports, "stripped")


# ─────────────────────────── 공통 ───────────────────────────

def _targets(args: argparse.Namespace) -> list[tuple[Path, str]]:
    if args.file:
        return [(args.file, args.file.name)]
    out = []
    for p in sorted(_lp(args.dir).glob("**/*.md")):
        name = p.name
        if name == "README.md" or name.startswith("_") or ".tmpl" in name:
            continue
        if "_tables" in str(p).replace("\\", "/").split("/"):
            continue
        try:
            rel = str(Path(str(p)).relative_to(_lp(args.dir)))
        except ValueError:
            rel = name
        out.append((Path(str(p)), rel))
    return out


def _print(reports: list, key: str) -> None:
    n = sum(1 for r in reports if r.get(key) or r.get("sidecar") or r.get("fields") is not None)
    print(json.dumps({"files": len(reports), key: n, "reports": reports[:300]},
                     ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    specs = (("embed", cmd_embed, "JSON 입력구조 섹션 삽입/갱신"),
             ("read", cmd_read, "박힌 JSON을 꺼내기"),
             ("strip", cmd_strip, "삽입한 JSON 섹션 제거"))
    for name, fn, helptext in specs:
        sp = sub.add_parser(name, help=helptext)
        g = sp.add_mutually_exclusive_group(required=True)
        g.add_argument("--dir", type=Path, help="폴더(하위 .md 전체)")
        g.add_argument("--file", type=Path, help="md 하나만")
        if name == "read":
            sp.add_argument("--to-sidecar", action="store_true",
                            help="<md>.tmpl.json 으로 기록(fill apply 용)")
        if name == "embed":
            sp.add_argument("--re-extract", action="store_true",
                            help="사이드카를 무시하고 SOURCE에서 구조를 새로 추출")
        sp.set_defaults(func=fn)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
