# spec: RFP 업로드 → 절 자동작성 (webapp)

RFP(공고·제안요청서)를 올리면 그 내용을 읽어 연구개발계획서의 여러 절을 참조
프리셋 문체·구성으로 **자동 작성**해 채우는 기능. 관련 주제: [작성 프롬프트](spec_webapp-작성프롬프트.md),
[변환 출력 품질](spec_webapp-변환출력품질.md).

## ① 질의·요청 히스토리

- **2026-08-06** (원문 요지) "웹 좌측에 RFP(한글 또는 PDF) 업로드 아이콘(글자)을 추가.
  업로드하면 자료를 읽어 **1.1, 1.2, 2.1, 2.2(기본 제안), 4.1, 4.2, 5.1, 5.2, 5.3, 5.5** 절이
  자동 입력되어 LLM이 출력되도록 자동화. 작성 프롬프트는 제안된(프리셋) 프롬프트 사용. 충분한 에이전트 사용."
- **2026-08-06** (후속) "제안된 프롬프트가 실제 조사가 아니라 유사하게 만들어 **수치가 빠져** 있다.
  **실제 인터넷 조사**를 해서 조사 내용을 바탕으로 작성하도록 작성 프롬프트를 업데이트."
  → 조사 결과: 웹 도구가 CLI에서 전면 차단돼 있었고 프롬프트가 '수치는 지어내지 말고 자리표시'를
  지시하고 있었음(그래서 수치 공란). 웹 조사 모드로 전환.

## ② 확정 사양

- **대상 절(TARGET_SECTIONS)**: `1-1, 1-2, 2-1, 2-2, 4-1, 4-2, 5-1, 5-2, 5-3, 5-5`
  (트리 nid). 사용자 요청의 "2.2 기본 제안"은 2-2 를 RFP 근거의 baseline 제안형으로 작성.
- **입력 형식**: `.pdf`, `.hwpx`, `.hwp`. 텍스트 추출
  - `.pdf` → PyMuPDF(fitz), 실패 시 pdfplumber 폴백.
  - `.hwpx` → `hwpx2yaml.py extract` 로 문단 텍스트 연결(한컴 COM 불필요).
  - `.hwp` → `hwp2hwpx.py convert`(한컴 COM) 후 위와 동일.
  - 추출 텍스트는 `RFP_MAX_CHARS`(기본 48000자)로 절단.
- **작성 프롬프트 = 제안된 프리셋 + 인터넷 조사**: 절별 `presets.preset_for(nid)`(rnd-write-* 문체·구성)를
  그대로 문체/구성으로 사용하되, `draft_from_rfp` 는 **웹 조사 모드**로 동작한다.
  - CLI: `--allowed-tools WebSearch WebFetch`(파일/셸/에이전트 도구는 계속 차단), SDK: 서버측 `web_search` 도구.
  - 시스템 프롬프트(`_RFP_SYSTEM_RESEARCH`): "지어내지 말고 조사해서 쓴다" — 시장규모·성장률(CAGR)·전망,
    기술수준·경쟁사, 특허·국제표준(IEC/ISO)·인증·선급, 정책·법령·유사 국책과제 실적을 검색해
    **핵심 수치에 (출처, 연도) 병기**, 확인 못한 값만 `[○○ 확인 필요]`. 말미에 `[출처]` URL 목록 허용(검토용).
  - 끄기: `RFP_DISABLE_RESEARCH` 설정 시 예전(자리표시) `_RFP_SYSTEM_NORESEARCH`. 조사 타임아웃 `CLAUDE_RESEARCH_TIMEOUT`(기본 600s).
  - 병렬성: 조사 켜지면 무거우므로 기본 동시 실행 `5→3`(`RFP_AUTOFILL_WORKERS`로 조정).
- **에이전트 병렬성**: 절별 초안 생성은 서로 독립 → `ThreadPoolExecutor`(`RFP_AUTOFILL_WORKERS`,
  기본 5)로 동시에 여러 Claude 호출. **yaml 병합은 `section_*.yaml` 공유 갱신이라 순차**(경합 방지).
- **결과 반영**:
  - 기본: 각 절 `input.md` 에 초안 저장(사용자가 검토 후 절별 [변환]으로 yaml 반영).
  - `apply=true`(UI "YAML 문서까지 반영"): 초안을 `segment_input`(LLM 재호출 없는 결정론적 분할)로
    나눠 `result.yaml` 저장 + `yaml/section_*.yaml` 병합 → 즉시 [hwpx 빌드] 가능.
- **호출 폴백**: `draft_from_rfp` 는 API 키 → claude 실행파일 → 스텁(개조식 RFP 발췌) 순. 스텁도
  절을 채워 실패해도 UI 흐름은 유지.
- **UI(좌측)**: `[📥 RFP 업로드 · 자동작성]` 라벨(파일선택) + "YAML 문서까지 반영" 체크박스 +
  상태줄(업로드/작성 경과초). 프로젝트가 없으면 기본 문서로 자동 생성 후 진행. 완료 시 성공 절
  leaf 에 "✓ 자동작성" 배지, 현재 열린 절이면 입력칸 자동 갱신.
- **REST**(ARCHITECTURE.md 계약):
  - `GET  /api/projects/{pid}/rfp` → `{meta,sections}`
  - `POST /api/projects/{pid}/rfp` (multipart file) → `{filename,chars,sections}`
  - `POST /api/projects/{pid}/rfp/autofill` `{sections?,apply}` → `{results,ok_count,total}`
- **저장**: `data/projects/<pid>/rfp/{source.<ext>,rfp.txt,meta.json}`.

## ③ 구현 상태

- [x] `backend/claude_service.py`: `draft_from_rfp`, `segment_input`(+스텁) 추가.
- [x] `backend/rfp.py` 신규: `extract_rfp_text`, `autofill`(병렬 초안 + 순차 병합).
- [x] `backend/store.py`: `save_rfp/write_rfp_text/read_rfp_text/rfp_meta` 추가.
- [x] `backend/schemas.py`: `RfpAutofillBody`.
- [x] `backend/main.py`: RFP 3개 라우트.
- [x] `frontend/`: 좌측 RFP 업로드 박스 + 자동작성 흐름 + 배지(index.html, app.js, styles.css).
- [x] `ARCHITECTURE.md`: 계약·모듈·저장구조·UI 갱신.

## ④ 미결/후속

- 스캔 이미지 PDF(텍스트 레이어 없음)는 추출 0자 → 422 안내. OCR 은 범위 밖.
- 진행률을 절 단위로 실시간 표기하려면 SSE/폴링 필요(현재는 단일 요청 + 경과초 타이머).
- 5-4(경제성)·2-3(일정) 등 표 중심 절은 대상에서 제외(표 그리드 입력 경로 사용).

### 2026-08-06 후속 — 자동작성은 본문 필드에만(표 셀 제외)
- 요청: "국내 기술 동향 및 수준이 표 안에 있는데 필드에 작성하게." → 선택지 중
  **"자동작성을 본문 필드로만"**(표는 템플릿 유지) 채택.
- 해결: `pipeline.body_paths(pid, node_paths)` 로 **kind=para(본문 문단)만** 대상에 남기고
  표 셀(cell_para)은 제외. RFP `autofill`(`_context_for`)·빌드 flush(`_flush_pending_inputs`)·
  수동 `④ 변환`(convert) 모두 body-only. 표는 그리드 편집으로만 채운다.
  - 참고: 1-2 의 해당 표(s2/p94/t0)는 원본상 '작성 요령(삭제용) 표' 였음 → 자동작성이 덮어썼던 것.
    현재 프로젝트(6d90731b)는 그 표 셀 7개를 원본 템플릿으로 되돌리고 본문 13필드로 재작성 반영.
- 검증: 1-2 대상 20→13(셀 7 제외). 복원 hwpx 에 국내 기술 동향 본문 포함·표는 템플릿 문구 유지.

### 2026-08-06 후속 — 빌드했는데 아무것도 안 채워짐(해결)
- 증상: RFP 자동작성 후 [hwpx 빌드]→다운로드했더니 문서가 비어 있음.
- 원인: 자동작성은 `input.md` 만 채우고(“문서에 즉시 반영” 미체크 시) `yaml/` 에는 반영 안 됨.
  빌드는 `yaml/` 만 읽어 복원 → 결과가 빈 문서.
- 해결(2건):
  1) **빌드 직전 자동 반영** — `main._flush_pending_inputs(pid)`: `input.md` 는 있고 `result.yaml`
     이 없는 절을 빌드/섹션다운로드 직전에 자동으로 yaml 에 반영(응답 `flushed` 로 개수 전달,
     UI 토스트 표시). 이미 변환/반영된 절은 건드리지 않음.
  2) **유실 없는 매핑** — `claude_service.segment_input_packed`: 문서 슬롯(node_paths) 수가
     초안 문단 수보다 적으면 **마지막 슬롯에 나머지를 합쳐** 담고, 많으면 남는 슬롯은 결과에
     넣지 않아 원본 문단을 빈값으로 지우지 않음. (계약형 `segment_input` 은 그대로 두고 RFP
     apply·빌드 반영 경로에서만 packed 사용.) 예: 5-3(1칸)에도 초안 전체가 한 문단으로 들어감.
- 검증: 프로젝트 6d90731b 빌드 → 대상 절 슬롯이 채워지고 복원 hwpx 에 조사 본문(‘다중 정밀도’,
  ‘MDO’, ‘표준화 추진’ 등) 포함 확인.
- 한계: 슬롯이 적은 절은 여러 문단이 한 문단으로 합쳐져 들어감(문단 삽입은 파이프라인 미지원).
  세밀한 문단 구조가 필요하면 사용자가 문서에서 조정.
