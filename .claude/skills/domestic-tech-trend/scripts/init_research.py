"""조사 폴더 골격을 만든다: research/<주제>/{sources.yaml, raw/, md/}

사용:
    python init_research.py --topic "고체산화물 수전해(SOEC)" --root research
    python init_research.py --topic "..." --root research --slug soec
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import slugify  # noqa: E402

SOURCES_TMPL = """# 국내기술개발 동향 조사 — 자료 수집 계획
# 3개 정찰 에이전트가 제안한 후보를 병합·중복제거해 여기에 확정한다.
# id 는 S01 부터. kind: report|paper|patent|policy|stat|company|news|standard
# tier: 1(핵심·반드시) / 2(보강) / 3(있으면 좋음)

topic: "{topic}"
scope: "국내 중심 + 해외는 비교 근거로 최소"
created: "{today}"

sources:
  - id: S01
    title: "예시 — 2025 xx 기술로드맵"
    publisher: "한국산업기술기획평가원(KEIT)"
    year: 2025
    kind: report
    tier: 1
    url: "https://…/xxx.pdf"
    note: "무엇을 얻으려는 자료인지 한 줄"
    # 로그인·JS 렌더링으로 자동 다운로드가 막히면 브라우저로 직접 저장한 뒤
    # local: raw/S01_직접저장.pdf  를 적어두면 fetch.py 가 그 파일을 채택한다.
"""

PLAN_TMPL = """# 조사 계획 — {topic}

작성일: {today}

## 1. 조사 질문 (이 조사가 답해야 할 것)

1.
2.
3.

## 2. 정찰 결과 요약 (에이전트 3인)

| 에이전트 | 축 | 핵심 발견 | 제안 출처 |
|---|---|---|---|
| A1 | 기술·시장 동향 |  |  |
| A2 | 연구·논문·특허 |  |  |
| A3 | 산업생태계·정책·표준 |  |  |

### 쟁점 / 서로 어긋난 주장

-

## 3. 수집 대상 (sources.yaml 과 일치시킬 것)

| id | 자료 | 발행기관 | 연도 | 종류 | tier | 이 자료로 답할 질문 |
|---|---|---|---|---|---|---|
| S01 |  |  |  |  | 1 |  |

## 4. 확인된 공백 / 대체 계획

-

## 5. 산출물

- `md/` — 문단마다 출처 마커가 붙은 변환본
- `report.md` — 템플릿에 맞춰 작성한 최종 문서
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--root", default="research")
    ap.add_argument("--slug", default="")
    ap.add_argument("--today", default="", help="YYYY-MM-DD (미지정 시 빈칸으로 둔다)")
    args = ap.parse_args()

    slug = args.slug or slugify(args.topic, 30)
    root = Path(args.root).resolve() / slug
    (root / "raw").mkdir(parents=True, exist_ok=True)
    (root / "md").mkdir(parents=True, exist_ok=True)

    for name, tmpl in (("sources.yaml", SOURCES_TMPL), ("plan.md", PLAN_TMPL)):
        p = root / name
        if p.exists():
            print(f"  건너뜀(이미 있음)  {p}")
            continue
        p.write_text(tmpl.format(topic=args.topic, today=args.today or "YYYY-MM-DD"),
                     encoding="utf-8")
        print(f"  생성  {p}")

    print(f"\n조사 폴더 준비 완료: {root}")
    print("다음: plan.md 와 sources.yaml 을 채운 뒤 fetch.py → to_md.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
