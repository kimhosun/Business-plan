#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
guidelines_engine.py — references/의 각 .md 에서 "적용해야 할 규칙/지침/가이드라인"을
추출해 (1) 파일별 지침 .md 와 (2) 구조화된 지침 JSON 으로 산출하고,
원본이 바뀌면 최신본으로 자동 동기화(sync)하는 결정론적 엔진.

산출물(기본: <references>/_지침/):
  _지침/<원본이름>.지침.md      파일별 지침 문서(공통원칙 §N 을 인라인 해소)
  _지침/지침.json               모든 파일의 지침을 담은 구조화 JSON(마스터)
  _지침/.manifest.json          원본 SHA-256 매니페스트(변경 감지·자동 동기화용)

지침 .md 의 <!--@guideline-auto-begin/end--> 구간만 sync 가 재생성한다.
그 뒤(심화 지침 영역)는 사람이/에이전트가 편집해도 sync 가 보존한다.

Windows/UTF-8:  python -X utf8 guidelines_engine.py <cmd>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

AUTO_BEGIN = "<!--@guideline-auto-begin-->"
AUTO_END = "<!--@guideline-auto-end-->"
GUIDELINE_SUFFIX = ".지침.md"
OUT_DIRNAME = "_지침"
MASTER_JSON = "지침.json"
MANIFEST = ".manifest.json"
SCHEMA = "md-guidelines/1.0"

# README 등 지침 원본이 아닌 파일
EXCLUDE_NAMES = {"README.md"}

DEFAULT_TAIL = (
    "\n\n## 심화 지침 (수동·에이전트 편집 영역)\n"
    "<!-- 이 줄부터 파일 끝까지는 sync 가 보존합니다. 자유롭게 정제·추가하세요. -->\n"
)

# ── 섹션 헤딩 → 지침 유형 분류 (위에서부터 우선; 더 구체적/종결적 항목 먼저) ──
SECTION_TYPES = [
    ("체크리스트", "checklist"),      # "체크리스트 (금액 정합 …)" 가 consistency 로 새지 않게 최우선
    ("예문", "example"),
    ("원본 참조", "source-ref"),
    ("참조 경로", "source-ref"),
    ("비목", "budget-code"),
    ("관계식", "budget-code"),
    ("코드", "budget-code"),
    ("골격", "skeleton"),
    ("존재 형태", "variant"),
    ("변형", "variant"),
    ("적용 판단", "applicability"),
    ("문체", "style"),
    ("정합", "consistency"),
    ("판단", "applicability"),
]
# 지침(directive)으로 편입할 유형 (예문·원본참조·체크리스트는 별도 취급/제외)
DIRECTIVE_TYPES = {
    "skeleton", "variant", "style", "consistency",
    "budget-code", "applicability", "note",
}

HEADING_RE = re.compile(r"^##\s+(?:\d+\.\s*)?(.*?)\s*$")
LIST_ITEM_RE = re.compile(r"^(\s*)(?:[-*]|\d+\.)\s+(?:\[[ xX]\]\s+)?(.*)$")
CHECK_ITEM_RE = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.*)$")
COMMON_REF_RANGE_RE = re.compile(r"공통원칙\s*§\s*(\d+)\s*[~\-–]\s*§?\s*(\d+)")
COMMON_REF_RE = re.compile(r"공통원칙\s*§\s*(\d+)")
META_BULLET_RE = re.compile(r"^-\s+\*\*(.+?)\*\*\s*[:：]\s*(.*)$")
COMMON_SECTION_RE = re.compile(r"^##\s+§\s*(\d+)\.?\s*(.*?)\s*$")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def strip_backticks(s: str) -> str:
    return s.replace("`", "").strip()


def classify(heading: str) -> str:
    for key, typ in SECTION_TYPES:
        if key in heading:
            return typ
    return "note"


# ── 데이터 모델 ───────────────────────────────────────────────────────────
@dataclass
class Section:
    heading: str
    type: str
    lines: list[str] = field(default_factory=list)


@dataclass
class Record:
    name: str
    title: str
    meta: dict[str, str]
    sections: list[Section]
    common_refs: list[str]
    source_sha256: str
    is_common: bool = False

    @property
    def skill(self) -> str:
        for k in ("대응 스킬", "대응스킬"):
            if k in self.meta:
                return strip_backticks(self.meta[k])
        return ""

    @property
    def applies_to(self) -> str:
        for k in ("적용 절", "표준 절 제목", "적용절"):
            if k in self.meta:
                return strip_backticks(self.meta[k])
        return ""

    @property
    def role(self) -> str:
        return self.meta.get("역할", "").strip()

    def directives(self) -> list[dict]:
        out: list[dict] = []
        for sec in self.sections:
            if sec.type not in DIRECTIVE_TYPES:
                continue
            for text in sec.lines:
                out.append({"type": sec.type, "section": sec.heading, "text": text})
        return out

    def checklist(self) -> list[str]:
        items: list[str] = []
        for sec in self.sections:
            if sec.type == "checklist":
                items.extend(sec.lines)
        return items


# ── 파싱 ─────────────────────────────────────────────────────────────────
def parse_markdown(name: str, text: str, is_common: bool = False) -> Record:
    lines = text.splitlines()
    title = ""
    meta: dict[str, str] = {}
    sections: list[Section] = []
    cur: Section | None = None
    seen_heading = False

    in_code = False
    merge_target: int | None = None  # 직전 최상위 불릿 인덱스(하위 불릿 병합 대상)

    for raw in lines:
        line = raw.rstrip("\n")
        if not title and line.startswith("# "):
            title = line[2:].strip()
            continue
        m = HEADING_RE.match(line)
        if m and not in_code:
            seen_heading = True
            heading = m.group(1).strip()
            cur = Section(heading=heading, type=classify(heading))
            sections.append(cur)
            merge_target = None
            continue
        # 헤딩 전 상단 메타 불릿
        if not seen_heading:
            mm = META_BULLET_RE.match(line)
            if mm:
                meta[mm.group(1).strip()] = mm.group(2).strip()
            continue
        if cur is None:
            continue

        stripped = line.strip()

        # 코드펜스: 표시줄은 버리고, 블록 내부 각 줄(관계식·골격 등)을 지침으로 수집
        if stripped.startswith("```"):
            in_code = not in_code
            merge_target = None
            continue
        if in_code:
            if cur.type != "checklist" and stripped:
                cur.lines.append(stripped)
                merge_target = None
            continue

        # 체크리스트 섹션은 [ ] 항목만
        if cur.type == "checklist":
            cm = CHECK_ITEM_RE.match(line)
            if cm and cm.group(1).strip():
                cur.lines.append(cm.group(1).strip())
            continue

        if not stripped:
            merge_target = None
            continue

        # 하위 헤딩(### 이하)은 라벨 텍스트로 수집
        if stripped.startswith("#"):
            h = stripped.lstrip("#").strip()
            if h:
                cur.lines.append(h)
                merge_target = None
            continue

        # 표 행: 구분선 제외, 셀을 ' · ' 로 결합해 한 줄 지침으로
        if stripped.startswith("|"):
            if re.match(r"^\|[\s:\-|]+\|?\s*$", stripped):
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            row = " · ".join(c for c in cells if c)
            if row:
                cur.lines.append(row)
                merge_target = None
            continue

        # 리스트 아이템
        lm = LIST_ITEM_RE.match(line)
        if lm:
            indent = len(lm.group(1).replace("\t", "  "))
            body = lm.group(2).strip()
            if not body:
                continue
            # 하위 불릿은 직전 최상위 불릿에 ' · ' 로 평탄화 흡수
            if indent >= 2 and merge_target is not None:
                cur.lines[merge_target] = cur.lines[merge_target] + "  · " + body
            else:
                cur.lines.append(body)
                merge_target = len(cur.lines) - 1
            continue

        # 인용문
        if stripped.startswith(">"):
            q = stripped.lstrip(">").strip()
            if q:
                cur.lines.append(q)
                merge_target = None
            continue

        # 일반 산문(규칙 서술)
        cur.lines.append(stripped)
        merge_target = None

    nums: set[int] = set()
    for a, b in COMMON_REF_RANGE_RE.findall(text):  # §1~§5 → 1..5 확장
        lo, hi = int(a), int(b)
        if lo <= hi:
            nums.update(range(lo, hi + 1))
    nums.update(int(n) for n in COMMON_REF_RE.findall(text))
    common_refs = [f"§{n}" for n in sorted(nums)]
    return Record(
        name=name,
        title=title or name,
        meta=meta,
        sections=sections,
        common_refs=common_refs,
        source_sha256=sha256_text(text),
        is_common=is_common,
    )


def parse_common(text: str) -> dict[str, dict]:
    """00_공통_작성원칙.md → {'§1': {'title':..., 'summary':...}, ...}"""
    out: dict[str, dict] = {}
    lines = text.splitlines()
    cur_id: str | None = None
    buf: list[str] = []

    def flush():
        nonlocal cur_id, buf
        if cur_id is None:
            return
        summary = ""
        for ln in buf:
            lm = LIST_ITEM_RE.match(ln)
            if lm and lm.group(2).strip():
                summary = lm.group(2).strip()
                break
        out[cur_id]["summary"] = summary
        buf = []

    for raw in lines:
        line = raw.rstrip("\n")
        m = COMMON_SECTION_RE.match(line)
        if m:
            flush()
            cur_id = f"§{m.group(1)}"
            out[cur_id] = {"title": m.group(2).strip(), "summary": ""}
        elif cur_id is not None:
            buf.append(line)
    flush()
    return out


# ── 원본 수집 ────────────────────────────────────────────────────────────
def is_common_file(name: str) -> bool:
    return name.startswith("00_") or "공통_작성원칙" in name


def collect_sources(ref_dir: Path) -> list[Path]:
    out = []
    for p in sorted(ref_dir.glob("*.md")):
        if p.name in EXCLUDE_NAMES:
            continue
        if p.name.endswith(GUIDELINE_SUFFIX):
            continue
        out.append(p)
    return out


# ── 지침 .md 렌더링 ───────────────────────────────────────────────────────
def render_auto_block(rec: Record, common: dict[str, dict]) -> str:
    L: list[str] = [AUTO_BEGIN]
    L.append(f"# [지침] {rec.title}")
    L.append("")
    meta_bits = [f"원본: `{rec.name}`"]
    if rec.skill:
        meta_bits.append(f"대응 스킬: `{rec.skill}`")
    if rec.applies_to:
        meta_bits.append(f"적용 절: {rec.applies_to}")
    L.append("> " + " · ".join(meta_bits))
    L.append(">")
    L.append("> 자동 생성 문서 — 아래 `@guideline-auto` 구간은 sync 가 재생성합니다.")
    if rec.role:
        L.append("")
        L.append(f"**역할**: {rec.role}")

    # 공통원칙 (인라인 해소)
    if rec.common_refs and not rec.is_common:
        L.append("")
        L.append("## 반드시 적용할 공통원칙")
        for ref in rec.common_refs:
            info = common.get(ref, {})
            title = info.get("title", "")
            summary = info.get("summary", "")
            head = f"- **{ref} {title}**".rstrip()
            if summary:
                head += f" — {summary}"
            L.append(head)

    # 유형별 지침
    order = [
        ("applicability", "적용 판단"),
        ("skeleton", "골격 지침"),
        ("variant", "문서별 변형 지침"),
        ("style", "문체·표기 지침"),
        ("budget-code", "비목·코드 관계식"),
        ("consistency", "정합 지침"),
        ("note", "기타 지침"),
    ]
    grouped: dict[str, list[str]] = {}
    for d in rec.directives():
        grouped.setdefault(d["type"], []).append(d["text"])
    for typ, label in order:
        items = grouped.get(typ)
        if not items:
            continue
        L.append("")
        L.append(f"## {label}")
        for it in items:
            L.append(f"- {it}")

    # 체크리스트
    checks = rec.checklist()
    if checks:
        L.append("")
        L.append("## 체크리스트")
        for c in checks:
            L.append(f"- [ ] {c}")

    # 파일별 구조화 지침(JSON) — 자체 완결형
    L.append("")
    L.append("## 구조화 지침(JSON)")
    L.append("```json")
    L.append(json.dumps(file_json(rec), ensure_ascii=False, indent=2))
    L.append("```")

    L.append(AUTO_END)
    # 정확히 AUTO_END 에서 끝난다(뒤 개행은 tail 이 공급) → 반복 sync 시 바이트 동일
    return "\n".join(L)


def write_guideline_md(rec: Record, common: dict, out_path: Path) -> str:
    """반환: 'written' | 'skipped'(마커 훼손으로 보존 위해 미기록)"""
    auto = render_auto_block(rec, common)
    tail = DEFAULT_TAIL
    if out_path.exists():
        old = read_text(out_path)
        idx = old.find(AUTO_END)
        if idx != -1:
            tail = old[idx + len(AUTO_END):]
        elif old.strip():
            # AUTO_END 마커가 사라진 파일: 수동/에이전트 편집분을 덮어쓰지 않도록 건너뜀
            print(f"  ! {out_path.name}: '{AUTO_END}' 마커 없음 → 데이터 보존 위해 건너뜀(수동 확인 필요)")
            return "skipped"
    out_path.write_text(auto + tail, encoding="utf-8", newline="\n")
    return "written"


# ── JSON 조립 ────────────────────────────────────────────────────────────
def file_json(rec: Record) -> dict:
    return {
        "source": rec.name,
        "title": rec.title,
        "skill": rec.skill,
        "applies_to": rec.applies_to,
        "role": rec.role,
        "common_refs": rec.common_refs,
        "directives": rec.directives(),
        "checklist": rec.checklist(),
        "source_sha256": rec.source_sha256,
    }


def build_master_json(records: list[Record], common: dict, common_name: str) -> dict:
    return {
        "schema": SCHEMA,
        "source_dir": "references",
        "common_principles": {
            "file": common_name,
            "sections": [
                {"id": k, "title": v.get("title", ""), "summary": v.get("summary", "")}
                for k, v in common.items()
            ],
        },
        "files": {rec.name: file_json(rec) for rec in records},
    }


# ── 매니페스트 ───────────────────────────────────────────────────────────
def load_manifest(out_dir: Path) -> dict:
    p = out_dir / MANIFEST
    if p.exists():
        try:
            return json.loads(read_text(p))
        except Exception:
            pass
    return {"schema": "md-guidelines-manifest/1.0", "common_sha256": "", "files": {}}


def save_manifest(out_dir: Path, man: dict) -> None:
    (out_dir / MANIFEST).write_text(
        json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )


# ── 엔진 코어 ────────────────────────────────────────────────────────────
def load_records(ref_dir: Path):
    common: dict[str, dict] = {}
    common_name = ""
    records: list[Record] = []
    for p in collect_sources(ref_dir):
        text = read_text(p)
        isc = is_common_file(p.name)
        rec = parse_markdown(p.name, text, is_common=isc)
        records.append(rec)
        if isc:
            common = parse_common(text)
            common_name = p.name
    return records, common, common_name


def diff_against_manifest(records, common_sha, man):
    prev_files = man.get("files", {})
    prev_common = man.get("common_sha256", "")
    common_changed = prev_common != common_sha
    added, updated, unchanged = [], [], []
    for rec in records:
        prev = prev_files.get(rec.name)
        if prev is None:
            added.append(rec.name)
        elif prev.get("source_sha256") != rec.source_sha256:
            updated.append(rec.name)
        else:
            unchanged.append(rec.name)
    cur_names = {rec.name for rec in records}
    removed = [n for n in prev_files if n not in cur_names]
    return added, updated, unchanged, removed, common_changed


def cmd_sync(ref_dir: Path, force: bool, status_only: bool) -> int:
    out_dir = ref_dir / OUT_DIRNAME
    records, common, common_name = load_records(ref_dir)
    common_sha = ""
    for rec in records:
        if rec.is_common:
            common_sha = rec.source_sha256
    man = load_manifest(out_dir)
    added, updated, unchanged, removed, common_changed = diff_against_manifest(
        records, common_sha, man
    )

    # common 이 바뀌면 §N 해소가 달라지므로 전체 재생성
    regen = set(added) | set(updated)
    if force or common_changed:
        regen |= {rec.name for rec in records}

    # 산출물이 사라졌거나 훼손된 경우: 원본 SHA 가 같아도 재생성해야 함
    missing = [
        rec.name for rec in records
        if not (out_dir / (Path(rec.name).stem + GUIDELINE_SUFFIX)).exists()
    ]
    regen |= set(missing)

    print(f"[대상] references = {ref_dir}")
    print(f"[산출] {out_dir}")
    print(f"  추가 {len(added)} · 변경 {len(updated)} · 동일 {len(unchanged)} · 삭제 {len(removed)}"
          + (f" · 산출물누락 {len(missing)}" if missing else "")
          + (" · 공통원칙변경→전체재생성" if common_changed and not force else "")
          + (" · --force" if force else ""))
    for n in added:
        print(f"  + {n}")
    for n in updated:
        print(f"  ~ {n}")
    for n in missing:
        if n not in added and n not in updated:
            print(f"  ↻ {n} (산출물 누락→복구)")
    for n in removed:
        print(f"  - {n} (원본 삭제)")

    if status_only:
        stale = sorted(regen)
        if stale:
            print(f"[status] 재생성 필요 {len(stale)}건: " + ", ".join(stale))
        else:
            print("[status] 모든 지침이 최신입니다.")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)

    # 재생성 (마커 훼손으로 건너뛴 파일은 매니페스트에서 옛 항목 유지→다음 sync 에 재시도)
    skipped: set[str] = set()
    for rec in records:
        if rec.name in regen:
            out_path = out_dir / (Path(rec.name).stem + GUIDELINE_SUFFIX)
            if write_guideline_md(rec, common, out_path) == "skipped":
                skipped.add(rec.name)

    # 삭제된 원본의 산출물 제거
    for n in removed:
        gp = out_dir / (Path(n).stem + GUIDELINE_SUFFIX)
        if gp.exists():
            gp.unlink()
            print(f"  x 산출물 삭제 {gp.name}")

    # 마스터 JSON 은 항상 재조립
    master = build_master_json(records, common, common_name)
    (out_dir / MASTER_JSON).write_text(
        json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )

    # 매니페스트 갱신 (건너뛴 파일은 옛 SHA 유지 → 다음 sync 가 다시 재생성 시도)
    prev_files = man.get("files", {})
    files_man = {}
    for rec in records:
        if rec.name in skipped and rec.name in prev_files:
            files_man[rec.name] = prev_files[rec.name]
        else:
            files_man[rec.name] = {
                "source_sha256": rec.source_sha256,
                "output": Path(rec.name).stem + GUIDELINE_SUFFIX,
            }
    new_man = {
        "schema": "md-guidelines-manifest/1.0",
        "common_sha256": common_sha if not skipped else man.get("common_sha256", common_sha),
        "files": files_man,
    }
    save_manifest(out_dir, new_man)

    done = len(regen) - len(skipped)
    tail_msg = f" · 건너뜀 {len(skipped)}(마커확인필요)" if skipped else ""
    print(f"[완료] 지침 {len(records)}개 · 재생성 {done}개{tail_msg} · JSON={MASTER_JSON}")
    return 0


def cmd_build_json(ref_dir: Path) -> int:
    out_dir = ref_dir / OUT_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    records, common, common_name = load_records(ref_dir)
    master = build_master_json(records, common, common_name)
    (out_dir / MASTER_JSON).write_text(
        json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    total = sum(len(file_json(r)["directives"]) for r in records)
    print(f"[완료] {out_dir / MASTER_JSON} · 파일 {len(records)}개 · 지침 {total}개")
    return 0


def default_ref_dir() -> Path:
    # scripts/../.. = extract-md-guidelines/ ; 형제 스킬의 references 를 기본 대상으로
    here = Path(__file__).resolve()
    cand = here.parents[2] / "rnd-proposal-writer" / "references"
    return cand


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="references md → 지침 md + 구조화 JSON 추출·동기화")
    ap.add_argument("command", choices=["sync", "extract", "build-json", "status"],
                    help="sync/extract: 변경분만 재생성 · build-json: JSON만 · status: 미리보기")
    ap.add_argument("--dir", type=str, default=None, help="references 디렉터리 (기본: 형제 rnd-proposal-writer/references)")
    ap.add_argument("--force", action="store_true", help="변경 여부와 무관하게 전체 재생성")
    args = ap.parse_args(argv)

    ref_dir = Path(args.dir).resolve() if args.dir else default_ref_dir()
    if not ref_dir.is_dir():
        print(f"[오류] references 디렉터리를 찾을 수 없음: {ref_dir}", file=sys.stderr)
        return 2

    if args.command in ("sync", "extract"):
        return cmd_sync(ref_dir, force=(args.force or args.command == "extract"), status_only=False)
    if args.command == "status":
        return cmd_sync(ref_dir, force=False, status_only=True)
    if args.command == "build-json":
        return cmd_build_json(ref_dir)
    return 1


if __name__ == "__main__":
    sys.exit(main())
