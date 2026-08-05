#!/usr/bin/env python3
"""절별 법령·규정 데이터셋(regulations_data.json) 병합·갱신 도구.

'항상 최신버전' 반영 방식(큐레이션 + 주기적 웹검증):
  1) research-rnd-regulations 워크플로(6개 법영역 에이전트가 law.go.kr·KEIT 공식원문을
     웹검증)가 절별 규정 fragment(JSON: {common?, sections})를 만든다.
  2) 이 스크립트가 fragment 들을 regulations_data.json 으로 병합하고 as_of(기준일)를 찍는다.
  3) 웹앱은 매 클릭 시 regulations_data.json 을 다시 읽어(캐시 없음) 최신본을 PDF 로 낸다.

재검증(주기) 방법:
  - 워크플로를 다시 돌려 fragment 를 새로 만든 뒤 `python -m backend.refresh_regulations \
    --from <fragment_dir> --as-of YYYY-MM-DD` 로 병합.
  - schedule/cron 스킬로 위를 주기 실행하면 '주기적 웹검증'이 된다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DATA = Path(__file__).with_name("regulations_data.json")

DEFAULT_BUSINESS = "산업통상자원부 · KEIT 산업기술혁신사업(연구개발계획서)"
DEFAULT_DISCLAIMER = (
    "AI가 공식 원문(국가법령정보센터 등)을 검색·정리한 결과이며 법적 자문이 아니다. "
    "제출 전 담당자가 해당 세부사업의 최신 공고·RFP·품목요약서·협약 및 소관 전문기관 지침과 "
    "반드시 대조해 확정해야 한다. 기준일 이후 개정·시행분은 반영되지 않을 수 있다."
)


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_dataset(fragments: list[dict], as_of: str,
                  business: str | None = None,
                  disclaimer: str | None = None) -> dict:
    """fragment({common?, sections}) 목록을 하나의 데이터셋으로 병합한다.

    - common: 모든 fragment 의 common 을 이어 붙이되 (title, article) 중복 제거.
    - sections: nid 별로 regulations 를 이어 붙이되 (title, article) 중복 제거, notes 는 병합.
    - as_of 미확인 entry 의 verified_date 는 as_of 로 보정.
    """
    common: list[dict] = []
    seen_common: set[tuple] = set()
    sections: dict[str, dict] = {}

    def _key(lw: dict) -> tuple:
        return ((lw.get("title") or "").strip(), (lw.get("article") or "").strip())

    def _norm(lw: dict) -> dict:
        lw = dict(lw)
        if not lw.get("verified_date"):
            lw["verified_date"] = as_of
        return lw

    for frag in fragments:
        for lw in frag.get("common", []) or []:
            k = _key(lw)
            if k in seen_common:
                continue
            seen_common.add(k)
            common.append(_norm(lw))
        for nid, sec in (frag.get("sections", {}) or {}).items():
            bucket = sections.setdefault(nid, {"notes": "", "regulations": [], "_seen": set()})
            note = (sec.get("notes") or "").strip()
            if note and note not in bucket["notes"]:
                bucket["notes"] = (bucket["notes"] + " " + note).strip()
            for lw in sec.get("regulations", []) or []:
                k = _key(lw)
                if k in bucket["_seen"]:
                    continue
                bucket["_seen"].add(k)
                bucket["regulations"].append(_norm(lw))

    for nid in sections:
        sections[nid].pop("_seen", None)

    return {
        "schema": "rnd-regulations/1.0",
        "as_of": as_of,
        "business": business or DEFAULT_BUSINESS,
        "disclaimer": disclaimer or DEFAULT_DISCLAIMER,
        "common": common,
        "sections": sections,
    }


def write_dataset(dataset: dict, path: Path = DATA) -> Path:
    path.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="절별 법령·규정 데이터셋 병합·갱신")
    ap.add_argument("--from", dest="frag_dir", required=True,
                    help="fragment JSON({common?,sections}) 들이 든 디렉터리")
    ap.add_argument("--as-of", required=True, help="기준일 YYYY-MM-DD")
    ap.add_argument("--out", default=str(DATA))
    a = ap.parse_args()

    frags = [_load(p) for p in sorted(Path(a.frag_dir).glob("*.json"))]
    frags = [f for f in frags if f]
    ds = build_dataset(frags, a.as_of)
    write_dataset(ds, Path(a.out))
    n_sec = len(ds["sections"])
    n_law = sum(len(s["regulations"]) for s in ds["sections"].values())
    print(f"regulations_data.json 갱신: 공통 {len(ds['common'])}건, "
          f"절 {n_sec}개, 법령 {n_law}건, 기준일 {a.as_of}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
