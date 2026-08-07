# 사양서 — 웹앱 변환/원복 출력 품질(이중 마커·초소형 글씨)

## ① 질의·요청 히스토리
- 2026-08-05: 한글(hwpx) 변환 결과에서 (1) 문단 앞에 쓸데없는 `□` 박스가 붙는 현상,
  (2) 특정 문단부터 글씨가 갑자기 초소형으로 변하는 현상 → 모든 절에 적용되게 고쳐달라.
  (근거 스크린샷: 1-1 절 "□ □ …", "□ ㅇ …", "□ - …" 이중 마커 + 개발대상 문단 4pt 렌더)

## ② 확정 사양
- **이중 마커 금지**: 본문(text)이 이미 개조식 마커(□·ㅇ·○·-·· / < > 캡션 / 번호)를 달고
  있으면 template 기본 마커('□')를 marker 필드에 덧대지 않는다(→ "□ ㅇ" 방지).
  순수 본문(마커 없음)일 때만 template 이 마커를 부여한다.
- **초소형 글씨 보정**: 원본 템플릿의 간격용 빈 문단(1pt=charPr height 100, 4pt=400 등,
  임계값 9pt=900 미만)에 실제 본문을 채우면 안 보이므로, 원복 시 본문 대표 charPr(문서에서
  가장 흔한 9pt 이상 크기)로 글자크기를 올린다. 빈 문단·정상 크기는 건드리지 않는다.
- **무손실 왕복 불변**: 위 보정은 '내용이 바뀐 문단을 쓸 때'만 동작 → extract→restore 순수
  왕복은 0건 기록이라 영향 없음(검증: readback real_diffs=0).

## ③ 구현 상태 (완료 2026-08-05)
- 향후 변환: [claude_service.py](webapp/backend/claude_service.py) `_apply_markers` —
  세그먼트 중 하나라도 선두 마커가 있으면 template 적용을 건너뜀(`_has_leading_marker`).
- 폰트 보정: [hwpx_common.py](.claude/skills/hwpx-yaml-roundtrip/scripts/hwpx_common.py)
  `charpr_heights`·`pick_body_charpr`·`write_para(body_charpr,heights,tiny_threshold=900)`
  추가; [yaml2hwpx.py](.claude/skills/hwpx-yaml-roundtrip/scripts/yaml2hwpx.py) restore 가
  원본 헤더에서 높이맵·본문 charPr 를 구해 write_para 에 전달.
- 기존 데이터: [fix_converted_markers.py](webapp/backend/fix_converted_markers.py) —
  각 프로젝트 result.yaml 의 변환 path 에 한해 군더더기 marker 를 "" 로 정리(멱등, 원본
  노드 미접촉). 1차 실행: 21건 정리(1131deb0 9, e8648f13 12). 폰트는 재빌드 시 자동 보정.
- ⚠ compose 를 "본문에 마커 있으면 marker 무시"로 바꾸는 방어는 무손실 왕복을 깨서(중첩
  마커 "1) - …"·「법률」 내용 오판) **철회**했다. 이중 마커는 데이터/생성 단계에서만 막는다.

## ④ 미결/후속
- 세그먼트→타깃 매핑이 간격용 빈 문단까지 채우는 구조는 유지(폰트 보정으로 가시화). 매핑을
  본문 문단으로 한정하는 개선은 별도 논의.
- `pick_body_charpr` 는 '9pt↑ 최빈 charPr' 휴리스틱 — 문서별로 10pt/12pt 혼재 시 대표값이
  10pt 로 잡힐 수 있음(현재 문서 body=charPr 60=10pt). 필요 시 절 범위 기준으로 정밀화.
- 남은 초소형/캡션 잔여는 해당 절 재변환 시 완전 정리됨.
