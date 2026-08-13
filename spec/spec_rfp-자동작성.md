# spec: RFP 업로드 → 각 절 '작성 프롬프트' 아래 참조 표시 (webapp)

RFP(공고·제안요청서)를 올리면 본문을 추출·저장하고, 각 절 편집화면의 **'작성 프롬프트'
패널 아래에 RFP 본문을 참조용(읽기전용)으로 표시**한다. (초기의 '절 자동작성'은 2026-08-10
제거됨 — 아래 히스토리 참조.) 관련 주제: [작성 프롬프트](spec_webapp-작성프롬프트.md),
[변환 출력 품질](spec_webapp-변환출력품질.md), [그림 삽입](spec_hwpx-그림삽입.md).

## ① 질의·요청 히스토리

- **2026-08-10(후속2)** (원문 요지) "1-1 작성해 ④ 변환까지 했는데 **RFP를 전혀 반영 안 함**.
  작성 프롬프트(RFP 포함) 내용을 반영해 작성되도록 수정." → ④ 변환·작성 채팅이 RFP 원문을
  근거로 쓰도록 파이프라인 수정([②③] 참조). 원인: `convert_input`/`chat_write` 가 style·
  structure·guidelines 만 넘기고 **RFP 를 넘기지 않았음**(참조 표시만 됐지 생성엔 미투입).
- **2026-08-10** (원문 요지) "RFP 업로드는 놔두고 **자동 작성은 삭제**. RFP 업로드하면 각
  챕터별로 '작성 프롬프트' 아래에 RFP 내용을 삽입."
  → 자동작성(autofill) 기능·UI·라우트 제거, RFP는 업로드·추출만 유지하고 각 절의 작성
  프롬프트 아래에 참조 표시로 전환.
- **2026-08-06** (원문 요지) "웹 좌측에 RFP(한글 또는 PDF) 업로드 아이콘(글자)을 추가.
  업로드하면 자료를 읽어 **1.1, 1.2, 2.1, 2.2(기본 제안), 4.1, 4.2, 5.1, 5.2, 5.3, 5.5** 절이
  자동 입력되어 LLM이 출력되도록 자동화. 작성 프롬프트는 제안된(프리셋) 프롬프트 사용. 충분한 에이전트 사용."
- **2026-08-06** (후속) "제안된 프롬프트가 실제 조사가 아니라 유사하게 만들어 **수치가 빠져** 있다.
  **실제 인터넷 조사**를 해서 조사 내용을 바탕으로 작성하도록 작성 프롬프트를 업데이트."
  → 조사 결과: 웹 도구가 CLI에서 전면 차단돼 있었고 프롬프트가 '수치는 지어내지 말고 자리표시'를
  지시하고 있었음(그래서 수치 공란). 웹 조사 모드로 전환.
- **2026-08-10** (원문 요지) "RFP 업로드하는데 추출 실패라고 나온다. 해결해줘."
  → PDF 업로드 시 500. 원인은 `requirements.txt` 에 PDF 추출 라이브러리 누락(아래 후속 절).

## ② 확정 사양 (2026-08-10 개정 — 자동작성 제거, 참조 표시로 전환)

- **입력 형식**: `.pdf`, `.hwpx`, `.hwp`. 텍스트 추출(`rfp.extract_rfp_text`)
  - `.pdf` → PyMuPDF(fitz), 실패 시 pdfplumber 폴백.
  - `.hwpx` → `hwpx2yaml.py extract` 로 문단 텍스트 연결(한컴 COM 불필요).
  - `.hwp` → `hwp2hwpx.py convert`(한컴 COM) 후 위와 동일.
  - 추출 텍스트는 `RFP_MAX_CHARS`(기본 48000자)로 절단.
- **동작**: 업로드 → 추출 → `store` 저장뿐. **절 자동작성(LLM 초안 생성)은 하지 않는다.**
- **표시**: 각 절 편집화면 **② 작성 프롬프트 패널 아래**에 읽기전용 'RFP 내용' 박스(`#rfp-ref`).
  파일명·글자수(`#rfp-ref-meta`) + 추출 본문 전체(`#rfp-ref-text`). RFP 없으면 숨김.
  - 프론트는 프로젝트 열 때 `GET /rfp` 로 `state.rfp={filename,chars,text}` 를 담고, 절을 열
    때마다 `renderRfpRef()` 로 그 박스를 채운다(모든 절에서 같은 RFP 본문을 참조).
- **UI(좌측)**: `[📥 RFP 업로드]` 라벨(파일선택) + 상태줄. 프로젝트가 없으면 기본 문서로 자동
  생성 후 업로드. (기존 "YAML 즉시 반영" 체크박스·"✓ 자동작성" 배지 제거.)
- **REST**(ARCHITECTURE.md 계약):
  - `GET  /api/projects/{pid}/rfp` → `{meta, text}`  (text = 추출 본문)
  - `POST /api/projects/{pid}/rfp` (multipart file) → `{filename, chars, text}`
  - ~~`POST /api/projects/{pid}/rfp/autofill`~~ — **제거**.
- **저장**: `data/projects/<pid>/rfp/{source.<ext>,rfp.txt,meta.json}` (변경 없음).
- **작성 흐름**: 본문 작성은 기존 수동 경로 유지 — ③ 입력 패널(+채팅 `chat_write`)에 쓰고
  ④ 변환/[hwpx 빌드] 시 `segment_input_packed` 로 yaml 반영. 사용자는 옆의 RFP 참조를 보며 쓴다.
- **RFP 를 작성 근거로 투입(2026-08-10 후속2)**: ④ 변환(`convert_input`)·작성 채팅(`chat_write`)이
  **RFP 원문을 생성 컨텍스트로 받는다**.
  - `convert_node`·chat 라우트가 `store.read_rfp_text(pid)` 를 읽어 `convert_input(..., rfp_text=)`·
    chat context `rfp` 로 전달. 프롬프트에 `[RFP 원문]` 블록(최대 `CONVERT_RFP_MAX_CHARS`=30000자) 포함.
  - `_CONVERT_SYSTEM`·`_CHAT_SYSTEM`: "RFP 를 최우선 근거로 반영, 입력이 비어도 RFP 로 이 절을
    구체화, RFP·입력에 없는 수치는 [○○ 확인 필요]" 규칙 추가. 문체·구성·작성요령은 그대로 준수.

## ③ 구현 상태 (자동작성 제거 완료 2026-08-10)

- [x] `backend/rfp.py`: `autofill`·`_context_for`·`_max_workers`·`TARGET_SECTIONS`·`_SPECIAL_NOTE`
  제거, `extract_rfp_text`(+`_pdf_text`/`_hwpx_text`)만 유지. import(`ThreadPoolExecutor`,
  `claude_service`) 정리.
- [x] `backend/main.py`: `autofill_rfp` 라우트 삭제, `get_rfp`→`{meta,text}`, `upload_rfp`→`{filename,chars,text}`.
- [x] `backend/schemas.py`: `RfpAutofillBody` 삭제(+main import 제거).
- [x] `frontend/index.html`: RFP 박스 라벨 "RFP 업로드", 즉시반영 체크박스 제거; 작성 프롬프트
  패널 아래 `#rfp-ref` 박스 추가.
- [x] `frontend/app.js`: `autofillRfp` API·자동작성 흐름·`state.filled`·`markLeafFilled`·트리 배지
  제거; `state.rfp`·`renderRfpRef()`·업로드 후 참조 표시 추가.
- [x] `frontend/styles.css`: `.rfp-ref*` 스타일 추가.
- [x] 검증(headless chromium): 절 열고 ② 탭 → RFP 박스 표시(파일명·2480자·본문), 라벨=RFP 업로드,
  체크박스 없음, 콘솔 오류 0. `openapi.json` 에 autofill 경로 없음.
- 참고: `claude_service.draft_from_rfp`/`_RFP_SYSTEM_*`/`_CHART_GUIDE`/`_IMAGE_GUIDE` 는 이제
  호출되지 않는 **미사용 코드**로 남음(제거는 후속). `segment_input_packed` 는 빌드 flush 에서
  계속 사용하므로 유지.
- (2026-08-10 후속2) RFP 를 변환·채팅 생성 근거로 투입:
  - `backend/main.py`: `convert_node` 가 `rfp_text=store.read_rfp_text(pid)` 전달, chat 라우트
    context 에 `rfp` 추가.
  - `backend/claude_service.py`: `convert_input(...rfp_text)`·`_claude_convert_input` 에 `[RFP 원문]`
    블록·시스템규칙, `_chat_context_block` 에 `[RFP 원문]`, `_CHAT_SYSTEM` 규칙 1-1 추가.
    예산 `_CONVERT_RFP_MAX`(=30000자, `CONVERT_RFP_MAX_CHARS`).
  - 검증: 09754646 1-1 변환(입력 6032자·RFP 2480자) → 결과에 해상풍력·자켓·하부구조·운송·설치·
    경제성 모두 반영, "수심 30m↑ 15MW급 초대형 해상풍력 실단지·프리파일링 대비 운송·설치 10%
    단축" 등 RFP 주제로 개조식·정량 작성(13세그먼트, 12초). 콘솔/서버 오류 0.

## ④ 미결/후속

- 스캔 이미지 PDF(텍스트 레이어 없음)는 추출 0자 → 422 안내. OCR 은 범위 밖.
- RFP 참조는 **절 무관하게 전체 본문**을 그대로 보여 준다. 절별로 관련 구간만 발췌해 보이는
  기능은 후속(현재는 자동작성 제거로 절별 매핑 로직 없음).
- 미사용으로 남은 자동작성 코드(`claude_service.draft_from_rfp` 등, [②③] 참조) 정리는 후속.
- (구) 자동작성 관련 아래 히스토리는 기능 제거 전 기록으로 남겨 둔다(참고용).

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

### 2026-08-10 후속 — PDF 업로드 "RFP 추출 실패"(해결)
- 증상: PDF RFP 업로드 시 `POST /api/projects/{pid}/rfp` 가 500, UI 에 "RFP 추출 실패".
- 원인: `_pdf_text` 는 PyMuPDF→pdfplumber 순으로 임포트하는데 **둘 다
  `webapp/requirements.txt` 에 없었다.** 새 환경에서 requirements 대로 설치하면 PDF 경로만
  `ModuleNotFoundError` 로 죽는다(.hwpx/.hwp 경로는 정상). ②의 "PyMuPDF, 실패 시 pdfplumber"
  사양과 의존성 명세가 어긋나 있던 것.
- 해결:
  1) `requirements.txt` 에 `PyMuPDF`, `pdfplumber` 추가.
  2) `rfp._pdf_text`: `import pymupdf`(정식 모듈명) 우선, 실패 시 `fitz` 폴백 —
     PyMuPDF ≥1.24 의 `fitz` deprecation 경고 제거.
  3) 둘 다 없을 때는 `ModuleNotFoundError` 대신 "`pip install -r webapp/requirements.txt`
     를 실행하세요" 라는 `RuntimeError` 로 원인을 노출.
- 검증: 실제 업로드 PDF(에너지기술개발사업 기술개요서, 175KB)로
  `POST /api/projects/a84a7c5d/rfp` → **HTTP 200, chars=2480**, 본문 텍스트 정상 추출.
- 참고(환경): 이 PC 에 Python 이 없어 3.12.10(winget) 설치 후 requirements 설치함.
