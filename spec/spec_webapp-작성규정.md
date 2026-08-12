# spec: 절별 작성 규정(법령·요령·지침) 매핑 · 작성 프롬프트 하단 표시

각 절(nid)에 적용되는 법령·요령·지침을 상세 매핑하고, «② 작성 프롬프트» 패널 하단에
읽기전용으로 표기한다. 관련: [작성 프롬프트](spec_webapp-작성프롬프트.md),
[RFP 업로드](spec_rfp-자동작성.md).

## ① 질의·요청 히스토리
- **2026-08-10**: "작성 규정에서 장별 규정을 표기해놨는데, **상세히 다시 분석해 챕터별 어떤
  규정을 참조해야 하는지** 분석하고, **«② 작성 프롬프트» 하단에 관련 규정을 표기**하라."

## ② 확정 사양
- **데이터 원천**: `webapp/backend/regulations_data.json`(schema `rnd-regulations/1.0`).
  `common`(전 절 공통, 4건) + `sections[nid].regulations`(절별). 각 항목:
  `{title, kind, article, authority, requirement, effective_date, source_url, confidence,
  verified_date, note}`. `GET /api/regulations/{nid}` → `regulation_for(nid)` 가
  `laws = common + sections[nid].regulations` 로 합쳐 반환.
- **전 33개 절 매핑 완비**: 종전 26개 절 → 누락 7개(1-3,1-4,2-4,6-3,7-4,9-1,9-2) 추가로 **33개 절**.
  - 신규 절 규정은 **기존 검증 corpus 의 항목을 재사용**(법 제명·조문·출처URL·검증일 그대로)하고
    `requirement`(절별 적용 사유)만 새로 작성 — **법 인용을 새로 지어내지 않는다**. 각 재사용
    항목 `note` 에 "본 절 적용 매핑 2026-08-10 추가 …대조 권장" 표기.
  - 변형 절(2-4↔2-3, 7-4↔7-3)은 형제 절 규정을 그대로 복제(내용 동일 변형).
- **표시 위치·형식**: «② 작성 프롬프트» 패널 하단(구성·저장 아래, RFP 박스 위)에 `#reg-ref`
  읽기전용 박스. 절 열 때 `GET /api/regulations/{nid}` 를 불러 `laws` 를 카드로 렌더:
  제명(kind)·조문·소관·적용 사유(requirement)·출처 원문 링크·시행일. 헤더에 "N건 · 기준일".
  하단에 면책(§ AI 웹검증·법적 자문 아님, 제출 전 대조) + 전체 전문은 상단 «📕 작성 규정 PDF».
- **레이스 방지**: `renderRegRef(nid)` 는 fetch 후 `state.nid !== nid` 면 반영하지 않음(빠른
  절 이동 시 stale 규정 표기 방지). 규정 조회 실패해도 노드 로드에는 영향 없음(try/catch).

## ③ 구현 상태 (완료 2026-08-10)
- `backend/regulations_data.json`: 7개 절 추가로 33개 절 완비(공통 4 + 절별 총 118건).
  재생성/추가 스크립트 로직은 기존 corpus 재사용 방식(요청 시 `tools`/`refresh_regulations` 계열로 관리).
- `frontend/index.html`: «② 작성 프롬프트» 하단에 `#reg-ref`(제명·조문·소관·사유·출처·시행일 카드) 추가.
- `frontend/app.js`: `API.getRegulation(nid)`, `renderRegRef(nid)`(비동기·레이스가드·에러내성) 추가,
  노드 로드 시 호출.
- `frontend/styles.css`: `.reg-ref*`·`.reg-item*` 스타일.
- 검증(headless): 2-1(9건)·5-4(8건)·8-3(8건)·6-1(8건) 카드 렌더, 출처 링크·기준일 표시,
  콘솔 오류 0. `GET /api/regulations/{1-3,9-1,2-4}` 신규 절도 laws 정상(8/7/9건).
- 참고: 규정 표기는 프로젝트 트리에 **존재하는 절**에만 뜬다(문서에 없는 절은 트리에 없어 미표시).

## ④ 미결/후속
- 신규 7개 절의 `requirement`(적용 사유)는 corpus 재사용 기반 분석 결과 — 조문 자체는 검증본이나
  **절 적용 타당성은 제출 전 담당자 확인 권장**(note 에 명시). 필요 시 `research-rnd-regulations`
  워크플로로 절별 웹 재검증.
- 규정 기준일(`as_of` 2026-08-05)·조문은 주기 재검증 필요(README 갱신 절차 참조).
- `regulation_for` 는 절마다 지침 파일을 읽어 응답 — 노드 열 때 1회 호출(성능 이슈 시 캐시 후속).
