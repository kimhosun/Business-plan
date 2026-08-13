#!/usr/bin/env python3
"""backend/skills.py — 스킬 보관함(웹 대화창에서 자동으로 붙는 참고 지침).

사용자가 웹 UI 에서 '스킬'(작성 노하우·규칙 묶음)을 저장해 두면, 절 작성 채팅에서
질문 내용과 관련된 스킬을 골라 시스템 프롬프트 꼬리에 붙인다. Claude Code 의
`.claude/skills/<name>/SKILL.md` 와 같은 형식(YAML frontmatter + 본문)을 쓰므로
저장소의 기존 스킬을 그대로 가져올 수 있다.

저장 레이아웃(프로젝트 공용 — 모든 프로젝트가 같은 보관함을 쓴다):
  data/skills/<slug>.md
    ---
    name: 절_1-1 개요 작성
    description: 언제 쓰는지 한 줄. 여기 단어들이 자동 선택의 기준이 된다.
    triggers: ["개요", "필요성", "1-1"]      # 선택(없으면 name/description 으로만 판정)
    scope: auto | always | off               # auto=관련 있을 때만, always=항상, off=사용 안 함
    source: user | repo:<원본 스킬명>
    updated: 2026-08-13T00:00:00+00:00
    ---
    (본문 = 모델에게 그대로 전달할 지침)

선택 방식은 LLM 호출 없는 **결정론적 키워드 매칭**이다(추가 지연 0).
질문/절 제목의 토큰과 스킬의 name·triggers·description·본문 토큰을 겹쳐 점수를 내고,
`_MIN_SCORE` 이상인 상위 `_MAX_SKILLS` 개만 문자 예산 안에서 붙인다.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import config

SKILLS_DIR = config.DATA_DIR / "skills"

# 저장소에 이미 있는 Claude Code 스킬(가져오기 원본)
REPO_SKILLS_DIR = config.ROOT_DIR / ".claude" / "skills"

SCOPES = ("auto", "always", "off")

# ── 매칭/예산 상수 ────────────────────────────────────────────────────────────
_MAX_SKILLS = 3            # 한 번의 대화에 붙일 최대 스킬 수(always 포함)
_MAX_BODY_CHARS = 6000     # 스킬 1개 본문 최대 길이(넘으면 잘라 붙인다)
_MAX_TOTAL_CHARS = 12000   # 붙는 스킬 본문 합계 상한
_MIN_SCORE = 2.0           # 이 점수 미만이면 '관련 없음'으로 보고 붙이지 않는다

_W_TRIGGER, _W_NAME, _W_DESC, _W_BODY = 3.0, 2.5, 1.5, 0.5
_W_CONTEXT = 0.4           # 질문이 아닌 맥락(절 제목 등) 토큰의 가중치

_TOKEN_RE = re.compile(r"[가-힣]{2,}|[a-zA-Z]{2,}|\d+(?:-\d+)?")
# 조사·일반어 — 매칭에서 제외(거의 모든 질문에 나와 변별력이 없다)
_STOPWORDS = {
    "그리고", "그래서", "하지만", "해줘", "해주세요", "합니다", "입니다", "있는", "없는",
    "이거", "저거", "우리", "내용", "부분", "작성", "써줘", "써주세요", "만들어", "please",
    "the", "and", "for", "with", "you", "this", "that",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── slug ─────────────────────────────────────────────────────────────────────
def slugify(name: str) -> str:
    """파일명으로 쓸 안전한 slug. 한글은 그대로 두고 공백/기호만 '-' 로."""
    text = unicodedata.normalize("NFC", (name or "").strip())
    text = re.sub(r"[^0-9A-Za-z가-힣]+", "-", text).strip("-").lower()
    return text[:60] or "skill"


def _unique_slug(base: str, exclude: str = "") -> str:
    slug, n = base, 2
    while slug != exclude and _path(slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _path(slug: str) -> Path:
    return SKILLS_DIR / f"{slug}.md"


# ── frontmatter 직렬화 ────────────────────────────────────────────────────────
_FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)


def parse_skill_md(text: str) -> tuple[dict, str]:
    """SKILL.md 문자열 → (frontmatter dict, 본문). frontmatter 없으면 ({}, 전체)."""
    m = _FM_RE.match(text or "")
    if not m:
        return {}, (text or "").strip()
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except Exception:  # noqa: BLE001 - 깨진 frontmatter 는 본문으로 취급
        return {}, (text or "").strip()
    return (meta if isinstance(meta, dict) else {}), m.group(2).strip()


def _dump_skill_md(meta: dict, body: str) -> str:
    fm = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{fm}\n---\n\n{(body or '').strip()}\n"


def _normalize_triggers(triggers) -> list[str]:
    if isinstance(triggers, str):
        parts = re.split(r"[,\n]", triggers)
    elif isinstance(triggers, (list, tuple)):
        parts = [str(t) for t in triggers]
    else:
        parts = []
    return [p.strip() for p in parts if p and p.strip()][:30]


def _normalize_scope(scope) -> str:
    scope = (str(scope or "auto")).strip().lower()
    return scope if scope in SCOPES else "auto"


# ── CRUD ─────────────────────────────────────────────────────────────────────
def _load(slug: str) -> dict | None:
    path = _path(slug)
    if not path.exists():
        return None
    meta, body = parse_skill_md(path.read_text(encoding="utf-8"))
    return {
        "slug": slug,
        "name": str(meta.get("name") or slug),
        "description": str(meta.get("description") or ""),
        "triggers": _normalize_triggers(meta.get("triggers")),
        "scope": _normalize_scope(meta.get("scope")),
        "source": str(meta.get("source") or "user"),
        "updated": str(meta.get("updated") or ""),
        "body": body,
        "chars": len(body),
    }


def list_skills(with_body: bool = False) -> list[dict]:
    """보관함의 스킬 목록(name 순). with_body=False 면 본문을 뺀 요약만."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for path in sorted(SKILLS_DIR.glob("*.md")):
        skill = _load(path.stem)
        if not skill:
            continue
        if not with_body:
            skill = {k: v for k, v in skill.items() if k != "body"}
        out.append(skill)
    out.sort(key=lambda s: (s["scope"] != "always", s["name"]))
    return out


def read_skill(slug: str) -> dict | None:
    return _load(slug)


def save_skill(
    name: str,
    description: str = "",
    body: str = "",
    triggers=None,
    scope: str = "auto",
    slug: str = "",
    source: str = "user",
) -> dict:
    """스킬 저장(신규/수정). slug 를 주면 그 파일을 덮어쓰고, 없으면 name 으로 만든다."""
    name = (name or "").strip()
    if not name:
        raise ValueError("스킬 이름(name)이 필요합니다.")
    body = (body or "").strip()
    if not body:
        raise ValueError("스킬 본문(body)이 비어 있습니다.")

    old = _load(slug) if slug else None
    if old is None:
        slug = _unique_slug(slugify(name))
        source = source or "user"
    else:
        source = old.get("source") or source

    meta = {
        "name": name,
        "description": (description or "").strip(),
        "triggers": _normalize_triggers(triggers),
        "scope": _normalize_scope(scope),
        "source": source,
        "updated": _now(),
    }
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    _path(slug).write_text(_dump_skill_md(meta, body), encoding="utf-8")
    return _load(slug)  # type: ignore[return-value]


def delete_skill(slug: str) -> bool:
    path = _path(slug)
    if not path.exists():
        return False
    path.unlink()
    return True


# ── 저장소(.claude/skills) 가져오기 ───────────────────────────────────────────
def repo_skills() -> list[dict]:
    """.claude/skills/*/SKILL.md 목록 — 보관함으로 가져올 수 있는 원본."""
    out: list[dict] = []
    if not REPO_SKILLS_DIR.is_dir():
        return out
    imported = {s.get("source") for s in list_skills()}
    for path in sorted(REPO_SKILLS_DIR.glob("*/SKILL.md")):
        try:
            meta, body = parse_skill_md(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        key = path.parent.name
        out.append({
            "key": key,
            "name": str(meta.get("name") or key),
            "description": str(meta.get("description") or ""),
            "chars": len(body),
            "imported": f"repo:{key}" in imported,
        })
    return out


def import_repo_skill(key: str, scope: str = "auto") -> dict:
    """저장소 스킬 하나를 보관함으로 복사(이미 있으면 본문만 갱신)."""
    path = REPO_SKILLS_DIR / key / "SKILL.md"
    if not path.exists():
        raise FileNotFoundError(f"저장소 스킬을 찾을 수 없습니다: {key}")
    meta, body = parse_skill_md(path.read_text(encoding="utf-8"))
    source = f"repo:{key}"
    existing = next((s for s in list_skills() if s.get("source") == source), None)
    return save_skill(
        name=str(meta.get("name") or key),
        description=str(meta.get("description") or ""),
        body=body,
        triggers=meta.get("triggers"),
        scope=(existing or {}).get("scope") or scope,
        slug=(existing or {}).get("slug", ""),
        source=source,
    )


# ── 매칭 ─────────────────────────────────────────────────────────────────────
def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", (text or "")).lower()
    return [t for t in _TOKEN_RE.findall(text) if t not in _STOPWORDS]


def _hit(q: str, s: str) -> float:
    """질문 토큰 q 와 스킬 토큰 s 의 일치도. 어절(조사 포함)을 감안한 접두 일치 허용."""
    if q == s:
        return 1.0
    if len(q) >= 3 and len(s) >= 3 and (q.startswith(s) or s.startswith(q)):
        return 0.6
    return 0.0


def _score(query_tokens: list[tuple[str, float]], skill: dict) -> float:
    fields = (
        (_W_TRIGGER, set(_tokens(" ".join(skill.get("triggers") or [])))),
        (_W_NAME, set(_tokens(skill.get("name") or ""))),
        (_W_DESC, set(_tokens(skill.get("description") or ""))),
        (_W_BODY, set(_tokens((skill.get("body") or "")[:4000]))),
    )
    total = 0.0
    for token, tw in query_tokens:
        best = 0.0
        for weight, bag in fields:
            for s in bag:
                best = max(best, weight * _hit(token, s))
        total += best * tw
    return round(total, 3)


def match(query: str, context: str = "", limit: int = _MAX_SKILLS) -> list[dict]:
    """질문(query)과 맥락(절 제목 등)에 관련된 스킬을 점수순으로 고른다.

    scope="always" 는 점수와 무관하게 항상 포함, "off" 는 항상 제외.
    반환: [{slug,name,description,scope,score,body,chars}] (limit 개 이하)
    """
    all_skills = [s for s in list_skills(with_body=True) if s["scope"] != "off"]
    if not all_skills:
        return []

    qt: list[tuple[str, float]] = [(t, 1.0) for t in dict.fromkeys(_tokens(query))]
    seen = {t for t, _ in qt}
    qt += [(t, _W_CONTEXT) for t in dict.fromkeys(_tokens(context)) if t not in seen]

    scored = []
    for skill in all_skills:
        skill = dict(skill)
        skill["score"] = _score(qt, skill)
        scored.append(skill)

    always = [s for s in scored if s["scope"] == "always"]
    auto = [s for s in scored if s["scope"] != "always" and s["score"] >= _MIN_SCORE]
    auto.sort(key=lambda s: -s["score"])

    picked, used = [], 0
    for skill in always + auto:
        if len(picked) >= max(1, limit):
            break
        body = (skill.get("body") or "")[:_MAX_BODY_CHARS]
        if used + len(body) > _MAX_TOTAL_CHARS:
            body = body[: max(0, _MAX_TOTAL_CHARS - used)]
        if not body.strip():
            continue
        used += len(body)
        picked.append({**skill, "body": body})
    return picked


def context_block(skills: list[dict]) -> str:
    """고른 스킬들을 시스템 프롬프트 꼬리에 붙일 텍스트로."""
    skills = [s for s in (skills or []) if (s.get("body") or "").strip()]
    if not skills:
        return ""
    parts = [
        "\n\n[적용 스킬]\n"
        "아래는 이 요청에 관련된 사용자 저장 스킬(작성 지침)이다. "
        "절 양식·작성요령과 충돌하지 않는 범위에서 그대로 따른다."
    ]
    for skill in skills:
        head = f"\n\n### 스킬: {skill.get('name') or skill.get('slug')}"
        desc = (skill.get("description") or "").strip()
        if desc:
            head += f"\n({desc})"
        parts.append(head + "\n" + (skill.get("body") or "").strip())
    return "".join(parts)


def brief(skills: list[dict]) -> list[dict]:
    """응답/이력에 남길 요약 형태."""
    return [
        {"slug": s.get("slug", ""), "name": s.get("name", ""),
         "scope": s.get("scope", "auto"), "score": s.get("score", 0)}
        for s in (skills or [])
    ]


# ── __main__ 스모크 테스트 ────────────────────────────────────────────────────
def _smoke() -> int:
    tmp_slug = "zz-스모크-테스트-스킬"
    saved = save_skill(
        name="스모크 테스트 스킬",
        description="시장 규모와 성장률을 정량으로 쓰는 방법",
        body="- CAGR 은 (출처, 연도)와 함께 쓴다.\n- 국내/세계 시장을 분리해 제시한다.",
        triggers=["시장", "CAGR", "1-2"],
        slug=tmp_slug if _path(tmp_slug).exists() else "",
    )
    ok = saved["name"] == "스모크 테스트 스킬"
    print(f"[smoke] saved slug={saved['slug']} chars={saved['chars']}")

    hit = match("1-2 시장 현황을 CAGR 포함해서 써줘", context="1.2 시장 동향")
    miss = match("표지에 들어갈 기관명만 바꿔줘", context="표지")
    print(f"[smoke] hit  = {[(s['name'], s['score']) for s in hit]}")
    print(f"[smoke] miss = {[(s['name'], s['score']) for s in miss]}")
    ok &= any(s["slug"] == saved["slug"] for s in hit)
    ok &= all(s["slug"] != saved["slug"] for s in miss)
    ok &= "[적용 스킬]" in context_block(hit)

    print(f"[smoke] repo skills = {[s['key'] for s in repo_skills()]}")
    ok &= delete_skill(saved["slug"])
    print(f"[smoke] RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(_smoke())
