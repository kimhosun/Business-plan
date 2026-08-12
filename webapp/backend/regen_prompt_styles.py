#!/usr/bin/env python3
"""backend/regen_prompt_styles.py — `_프롬프트/` → prompt_styles.json 재생성.

각 절 `_프롬프트/{절}.md` 의 **핵심 섹션**(## 역할·## 이 절의 목적과 평가 관점·
## 참고 문서에서 관찰된 공통 구성·## 문체·형식 규칙 등)을 뽑아 절별 문체(styles[nid])로
저장한다. 작성자 로컬 경로가 든 '## 참고 자료' 와 빈칸 채우기용 '## 작성 지시' 섹션,
그리고 파일 맨 위 제목·인용 블록(> …)은 제외한다.

이 결과가 웹앱 «② 작성 프롬프트 → ② 스킬로 제공한 것»(presets.preset_for(nid).style)의 원천이다.
`_프롬프트/` 를 고치면 다시 실행한다:  python -m backend.regen_prompt_styles
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROMPTS_DIR = _HERE.parent.parent / "_프롬프트"
_OUT = _HERE / "prompt_styles.json"

# 제외할 섹션(헤딩이 이 말로 시작하면 통째로 버림)
_DROP_HEAD = re.compile(r"^\s*(참고\s*자료|작성\s*지시)", re.I)
_NID_RE = re.compile(r"^(\d+-\d+)_")


def _core(text: str) -> str:
    """첫 '## ' 섹션부터 끝까지 중, 제외 헤딩 섹션을 뺀 본문."""
    lines = text.split("\n")
    starts = [i for i, l in enumerate(lines) if l.startswith("## ")]
    if not starts:
        return ""
    lines = lines[starts[0]:]
    out: list[str] = []
    buf: list[str] = []
    keep = True

    def flush() -> None:
        if keep and buf:
            out.append("\n".join(buf).rstrip())

    for l in lines:
        if l.startswith("## "):
            flush()
            buf = [l]
            keep = not _DROP_HEAD.match(l[3:].strip())
        else:
            buf.append(l)
    flush()
    return "\n\n".join(s for s in out if s.strip()).strip()


def build() -> dict:
    styles: dict[str, str] = {}
    for f in sorted(_PROMPTS_DIR.glob("*.md")):
        if f.name in ("README.md", "_TEMPLATE.md"):
            continue
        m = _NID_RE.match(f.name)
        if not m:
            continue
        core = _core(f.read_text(encoding="utf-8"))
        if core:
            styles[m.group(1)] = core
    return {
        "as_of": "2026-08-10",
        "source": "_프롬프트/ 각 절 md 의 핵심 섹션(역할·목적·관찰된 구성·문서별 편차·문체·형식 규칙). "
                  "'참고 자료'·'작성 지시' 스캐폴딩은 제외.",
        "note": "presets.preset_for(nid) 의 style(=② 스킬로 제공한 것) 원천. "
                "_프롬프트 개정 시 `python -m backend.regen_prompt_styles` 로 재생성.",
        "styles": styles,
    }


def main() -> int:
    data = build()
    _OUT.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    styles = data["styles"]
    avg = sum(len(v) for v in styles.values()) // max(len(styles), 1)
    print(f"[regen_prompt_styles] {len(styles)}개 절, 평균 {avg}자 → {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
