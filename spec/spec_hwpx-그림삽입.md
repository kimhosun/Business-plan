# spec: 마크다운 그림/차트(```chart · ![](url)) → 실제 HWPX 그림개체

자동작성 초안의 **데이터 차트**와 **온라인/로컬 이미지**를, 복원 시 본문 문단을 쪼개
**실제 HWPX 그림개체(`<hp:pic>`)** 로 바꾸고 그 아래 `<그림 N>` 캡션(+출처)을 붙인다.
관련: [표변환](spec_hwpx-표변환.md), [글꼴·내어쓰기](spec_hwpx-글꼴적용.md),
[RFP 자동작성](spec_rfp-자동작성.md), [변환출력품질](spec_webapp-변환출력품질.md).

## ① 질의·요청 히스토리

- **2026-08-10(후속)** (원문 요지) "**1-2 절 작성할 때 내용과 관련된 이미지도 추가**해줘. 새로
  그림을 그리는 게 아니라 **참고문헌·뉴스·보도자료에서 사용된 이미지를 가져와** 제목·출처와 함께
  표시. 예: 국외 동향에 Seagreen 해상풍력을 썼으면 그 단지 이미지를, 건설비 내용이 있으면 해상풍력
  건설단가 이미지를 찾아 넣는 식." → 철회된 '도표 자동생성'과 구분되는 **실제 참조 이미지 삽입**을
  동향·시장 절 작성 경로(④ 변환·작성 채팅)에 붙임. 결정(사용자 문답): 두 경로 모두 적용 / 대상은
  동향·시장 성격 절 전체(nid 게이트) / 진짜 출처 URL 확보를 위해 **웹조사 ON**. [②③] 참조.
- **2026-08-10(철회)** (원문 요지) "그림은 있는데 **이런 간단한 의미 없는 그림은 필요 없다. 기존대로
  바꿔줘**." → 바로 아래 '작성 시 도표 자동 생성' 변경을 **철회**. ④ 변환·작성 채팅 프롬프트를
  차트 가이드 이전으로 되돌리고(RFP 반영은 유지), 이미 생성돼 yaml 에 저장된 ```chart 블록을 제거.
- **2026-08-10** (원문 요지) "1-1에서 전반적인 내용 파악해서 **그림도 그릴 수 있도록 프롬프트 보완**."
  → 활성 작성 경로(④ 변환 `convert_input`·작성 채팅 `chat_write`) 시스템 프롬프트에 `_CHART_GUIDE`
  연결. **위 철회로 되돌림.**
- **2026-08-09** (원문 요지) "한글파일로 변환할때 그림, 도표, 이미지도 추가해줘."
  - 확인 결과: 그림 출처 = ① **데이터→차트 자동생성**(matplotlib), ② **동향 조사 시 나오는
    온라인 이미지(출처 포함)**. 적용 경로 = **웹앱·스킬 둘 다**(공용 `hwpx_common`).

## ② 확정 사양

- **마커(자동작성 초안 텍스트에 그대로 씀)**
  - 차트: 본문 흐름 속 ```` ```chart ```` 펜스 블록(YAML) → matplotlib 렌더.
    키: `type`(bar|barh|line|pie), `title`, `x`(=labels/categories), `y`(=values/data)
    또는 `series:{이름:[값…]}`, `xlabel`/`ylabel`, `colors`, `source`, `caption`,
    `width_mm`, `fig_w`/`fig_h`.
  - 이미지: `![캡션](URL 또는 로컬경로)` 한 줄 + (선택) 바로 다음 줄 `출처: …`.
    캡션에 `캡션|출처` 형태도 허용. URL 은 **직접 열리는 이미지 파일**만(.png/.jpg/.gif…).
- **변환**(`hwpx_common.apply_markdown_images`): 복원 후, 표를 품지 않은 **본문 문단**의
  텍스트를 블록으로 나눠(chart/image/text) 원 문단 자리에 순서대로 삽입:
  - chart → matplotlib PNG 렌더 → 임베드. image → URL 다운로드(캐시)·로컬 읽기 → PNG 정규화 →
    임베드. 각 그림 아래 `<그림 N> 캡션 (출처: …)` 문단 자동 생성.
  - 실패(다운로드·렌더 실패) 블록은 **캡션·출처를 텍스트로 보존**(내용 손실 방지).
  - 표 셀 내부·표를 이미 품은 문단은 건드리지 않음.
- **HWPX 그림 임베드 방식**(검증됨)
  - `python-hwpx doc.add_image(png,"png")` 로 BinData·manifest·header binItem 등록 →
    반환 item_id(BIN####)를 pic 의 `binaryItemIDRef` 로 사용.
  - **manifest `opf:item` 에 `isEmbeded="1"` 를 반드시 덧붙인다** — 없으면 한컴이 임베드
    그림을 로드하지 못해 렌더가 누락됨(핵심 발견).
  - Hancom 이 만든 `<hp:pic>` 구조를 본떠 직접 구성(treatAsChar=1, HWPUNIT 크기=
    `mm×7200/25.4`, PNG 종횡비 유지, scaMatrix=단위행렬). lxml `addnext` 로 원 위치 삽입 후
    원 문단 제거. **섹션 `mark_dirty()` 필수**(안 하면 저장 시 캐시 원본으로 직렬화돼 유실).
- **복원 후처리 순서**: `apply_markdown_tables`(표) → **`apply_markdown_images`(그림, 글꼴 전)** →
  `apply_fonts` → `apply_table_layout` → `apply_hanging_indent`.
  기본 OFF, 웹앱 `pipeline.restore` 가 `HWPX_MD_IMAGES=1`(+`HWPX_IMG_WIDTH_MM`, 기본 140) 로 켬.
- **자동작성이 마커를 생성하도록**: RFP 조사 시스템 프롬프트에 `_CHART_GUIDE`(+연구경로엔
  `_IMAGE_GUIDE`) 를 붙여, 정량 데이터는 ```` ```chart ````, 조사 그림은 `![](url)`+출처로 쓰게 안내.
- **세그먼트·마커 보존**(중요 회귀 방지)
  - `_split_segments`: ```` ``` ```` 펜스 블록을 **한 세그먼트로 원자 보존**(문단/줄 분할·packed
    매핑이 여러 문단으로 쪼개 펜스를 깨지 않게). 펜스 밖은 기존 규칙(`_split_plain`).
  - `_apply_markers`: 그래픽 세그먼트(```` ``` ```` · `![](…)`)에는 마커를 붙이지 않음
    ("□ ```chart" 로 깨지는 것 방지).
  - `_unwrap_fence`: RFP draft 방어적 언랩을 "전체를 감싼 바깥 펜스만 제거"로 교체 —
    기존 `_extract_fenced` 는 draft 안 ```` ```chart ```` 가 2개면 중간만 잘라내는 버그가 있었음.

## ③ 구현 상태 (완료 2026-08-09)

- [x] `hwpx_common`: `apply_markdown_images` + `_render_chart_png`(bar/barh/line/pie, 한글폰트
  Malgun Gothic 자동) + `_download_image`(requests→urllib 폴백, PIL PNG 정규화, `.img_cache`) +
  `_read_local_image` + `_add_image_embedded`(isEmbeded 패치) + `_build_pic_paragraph` + `_img_blocks`.
- [x] `yaml2hwpx.py` restore: `HWPX_MD_IMAGES` 게이트(표 뒤·글꼴 앞), import 추가.
- [x] `webapp/backend/pipeline.py` restore: `env.setdefault("HWPX_MD_IMAGES","1")`.
- [x] `webapp/backend/claude_service.py`: `_CHART_GUIDE`/`_IMAGE_GUIDE` 를 RFP 프롬프트에 연결,
  `_split_segments`(펜스 원자화)·`_apply_markers`(그래픽 마커 제거)·`_unwrap_fence` 보강.
- [x] 검증(한컴 PDF 렌더 확인): ```` ```chart ```` bar → 실제 막대그래프 + `<그림 1> … (출처:
  한국에너지공단(2025))`, 로컬 pie 이미지 → `<그림 2> … (출처: 내부 작성)`. zip 무결성 OK,
  재오픈 OK, 잔존 마커 0. 온라인 이미지는 다운로드 성공 시 동일 경로로 임베드(샌드박스는
  네트워크 불가로 텍스트 폴백 동작까지 확인).
- [x] 단위검증: 펜스 블록 1세그먼트 원자 보존, 그래픽 세그먼트 marker="".

### 2026-08-10 후속 — 동향·시장 절 작성 시 '참조 이미지' 자동 삽입(구현)

- **무엇**: 철회된 `_CHART_GUIDE`(도표 자동생성)와 별개로, **실제 참조 이미지**(뉴스·보도자료·
  참고문헌·기관보고서에 실린 사진·그래프·개념도)를 서술 내용에 맞춰 조사해 본문에 끼운다. 산출은
  기존 이미지 마커 `![제목](직접 이미지 URL)` + 다음 줄 `출처: 매체/기관(연도), URL` — 빌드 시
  `apply_markdown_images` 가 실제 `<hp:pic>` 그림개체로 변환(파이프라인·env 게이트 변경 없음).
- **대상 절(게이트)**: `claude_service._wants_reference_images(nid)` — 기본 `{"1-2","5-1"}`(동향·시장
  성격 절). 환경변수 `IMAGE_SECTIONS`(공백/쉼표 구분)로 재정의. 그 외 절은 종전과 동일(이미지 미삽입).
- **적용 경로(둘 다)**:
  - ④ 변환 `_claude_convert_input(...,nid=)`: 대상 절이면 `_REF_IMAGE_GUIDE` 를 시스템에 붙이고
    user 에 세그먼트-보존 주의(정확히 N개 유지, 관련 세그먼트 끝에 마커 덧붙임)를 추가.
  - 작성 채팅 `_claude_chat_write`: `context["nid"]` 로 판정, 대상 절이면 `_chat_context_block`
    뒤에 `_REF_IMAGE_GUIDE` 를 붙임. draft(단일 문자열) 안에 마커가 들어가 apply→빌드에서 변환.
- **웹조사 ON**: 대상 절 경로는 `allow_tools=("WebSearch","WebFetch")` + `timeout=_research_timeout()`
  (기본 600s)로 호출 — 진짜로 열리는 이미지 URL·출처를 조사하게 함(지어낸 URL 방지, 못 찾으면 미삽입).
  convert `max_tokens` 8000→12000. API 키 경로는 서버측 `web_search`, CLI 경로는 WebSearch/WebFetch.
- **비대상 절·폴백**: 종전과 100% 동일(가이드·도구 없음, `max_tokens` 8000/16000). 조사·호출 실패는
  기존 스텁 폴백(이미지 없이 본문만).
- **철회 유지**: `_CHART_GUIDE`(도표 자동생성)는 **연결하지 않음** — 사용자 요청("새로 그리지 말 것")대로
  실제 자료 이미지만 가져온다. 마커 문법·`apply_markdown_images`·`HWPX_MD_IMAGES=1` 게이트는 불변.
- **파일**: `webapp/backend/claude_service.py`(`_REF_IMAGE_GUIDE`·`_reference_image_nids`·
  `_wants_reference_images` 추가, `_claude_convert_input`/`convert_input`/`_claude_chat_write` 수정),
  `webapp/backend/main.py`(`convert_node`→`convert_input(...,nid=nid)`, `chat_node` context 에 `nid`).
- **검증**: 모듈 컴파일·`_selftest` PASS(스텁), 게이트 단위확인(1-2/5-1=True, 2-1/None=False,
  `IMAGE_SECTIONS` 재정의 반영). 실호출(웹조사)로 실제 단지 사진·건설단가 이미지가 붙는지는 API/CLI
  환경에서 절 열어 확인 필요(④ 미결).

#### 2026-08-10 후속2 — "그림이 없다" 진단·보강
- **1차 원인(재확인)**: 사용자 백엔드(PID 34456)가 **14:47 기동, 명령줄에 `--reload` 없음**
  (`python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`). 코드 수정은 15:05 저장 →
  15:12 채팅·15:22 변환은 **옛 코드(이미지 지침·웹조사 없음)** 로 실행돼 마커 0. 프로젝트 5cff978f/
  nodes/1-2 의 input·result·yaml 에 `![` 없음으로 확증. **조치: 서버를 새 코드로 재기동해야 함**
  (README 는 `--reload` 이지만 실제 프로세스엔 빠져 있었음).
- **2차 원인(구조적)**: SDK(API 키) 경로 `_messages_text` 가 `web_search` 만 붙였음 → 검색은
  페이지 URL·요지만 주고 **직접 이미지 URL(.jpg/.png)은 못 얻음** → 엄격 지침("확실치 않으면 미삽입")
  상 이미지 0. **조치: `web_fetch_20250910`(beta 헤더 `web-fetch-2025-09-10`)를 추가**해 출처 페이지를
  열어 `<img>` 실주소를 뽑게 함. 단계적 폴백(search+fetch→search→무도구)으로 미지원 환경도 안전.
  `_REF_IMAGE_GUIDE` 에 "web_fetch 로 페이지 열어 이미지 주소 복사, upload.wikimedia.org 직접 URL 허용"
  추가. CLI 경로는 `_RFP_RESEARCH_TOOLS=("WebSearch","WebFetch")` 로 이미 fetch 허용됨.
- **키 소재 주의**: 이 저장소엔 `.env`/dotenv 없음, `ANTHROPIC_API_KEY` 도 User/Machine 영구 변수
  아님(claude CLI 도 없음). 실행 서버는 **사용자 터미널 세션 env 로만** 키를 얻었음 → **재기동은
  키가 있는 그 터미널에서** 해야 하고, 키 없는 셸에서 띄우면 스텁 모드로 떨어진다.
- 파일: `webapp/backend/claude_service.py`(`_messages_text` web_fetch 폴백, `_REF_IMAGE_GUIDE` 보강).

### 2026-08-10 후속 — 표와 같은 문단의 차트가 빈 도표로 나옴(해결)
- 증상: ```chart 가 마크다운 표와 **같은 노드(문단)** 에 있을 때, 차트가 데이터 없는 **빈 축**으로
  렌더되고 스펙(type/x/y…)이 본문 텍스트로 남음(스크린샷 `<그림 6>`). 표가 없는 노드의 차트는 정상.
- 원인: 복원 후처리 순서가 `apply_markdown_tables` → `apply_markdown_images` 인데, 표를 품은
  문단을 표로 바꾸며 **나머지 텍스트를 줄 단위로 재분할**할 때 ```chart 펜스까지 줄별로 쪼개져
  ("```chart" 한 문단 + "type: bar" 다른 문단 …) 뒤이은 이미지 변환이 빈 스펙만 봄.
- 조치: 공용 `_split_para_chunks`(```…``` 펜스·![](){+출처}를 한 청크로 유지)를 만들어
  `apply_markdown_tables` 의 텍스트 재분할에 사용. `add_paragraph` 가 여러 줄(\n) 청크의 줄바꿈을
  보존함을 확인(왕복 OK).
- 검증(프로젝트 09754646 재빌드): `<hp:pic>` 21개, 잔여 차트-스펙 텍스트 1건(표 셀 내부 차트 —
  의도적 제외)로 급감. 한컴 PDF 렌더로 `<그림 6> 글로벌 누적 설치용량(83·92.5·238·441 GW)` 막대·
  하부구조물 시장 선그래프·실적표 모두 정상 표시 확인.

## ④ 미결/후속

- **(참조 이미지) 실호출 검증 필요**: 웹조사가 실제로 여는 이미지 URL 을 얼마나 잘 찾는지는
  API/CLI 환경에서 1-2·5-1 절을 열어 ④ 변환/작성 채팅→[hwpx 빌드]로 확인해야 한다(샌드박스는
  네트워크 불가). 조사로도 직접 이미지 URL 을 못 얻으면 이미지는 안 붙는다(지어내지 않음, 의도된 동작).
- **(참조 이미지) 지연**: 대상 절은 웹조사(최대 600s)로 변환·채팅이 느려진다. 급하면 `IMAGE_SECTIONS`
  를 비우거나 대상 절에서 제외해 종전 속도로 되돌릴 수 있다(비대상 절은 영향 없음).
- **(참조 이미지) convert 세그먼트 원자화**: 마커를 세그먼트 텍스트 '끝'에 덧붙이게 유도하지만,
  모델이 이미지를 별도 세그먼트로 내면 N-count 를 맞추려 마지막 슬롯에 합쳐질 수 있다(`packed`).
  마커 문법 자체는 보존되어 빌드 변환에는 문제 없음. 문단 단위 이미지 배치가 중요하면 작성 채팅 권장.
- 온라인 이미지 다운로드는 **복원 시점**에 수행(네트워크 필요). 사내망/차단 환경에선 실패→텍스트
  폴백. 필요 시 자동작성 단계에서 미리 받아 로컬 경로로 바꾸는 프리페치는 후속.
- `![](url)` 와 다음 줄 `출처:` 가 **서로 다른 문단으로 분리**되면(초안 전체가 단일 문단이라
  줄 폴백된 경우) 캡션 출처는 URL 도메인으로 대체되고 `출처:` 줄은 별도 텍스트로 남음. 문단
  구분이 있는 일반 초안에선 정상. 이미지+출처 원자화는 후속.
- **표 셀 안의 차트/이미지는 미변환**(apply_markdown_images 가 표 셀·표-품은 문단을 건너뜀) —
  셀 안엔 ```chart 텍스트가 그대로 남는다. 셀 안 그림은 크기 산정이 복잡해 후속. 자동작성이
  차트를 표 셀에 넣지 않도록 프롬프트로 유도하거나, 필요 시 셀 지원을 별도 구현.
- 그림 문단 정렬은 pic 자체를 가운데(horzAlign=CENTER)로 두되 문단 정렬은 본문 상속. 캡션도
  본문 문단 스타일 상속(전용 '그림 캡션' 스타일 지정은 후속).
- 병합셀·중첩표처럼, 애니메이션/투명도·클리핑 등 고급 이미지 속성은 미지원(단순 삽입).
- rowspan 없는 그룹막대까지만 지원. 복합 축(2축)·보조계열 스타일 등은 후속.

### 2026-08-10 후속 — 작성 시 도표 자동 생성(프롬프트 보완) → **철회**
- (도입) ④ 변환·작성 채팅 시스템에 `_CHART_GUIDE` 포함, 파싱 `_unwrap_fence` 교체, `max_tokens` 12000.
  1-1 변환에서 RFP 근거 ```chart 2개 생성·빌드 시 그림 렌더까지 확인.
- (철회 사유) 사용자: "이런 간단한 의미 없는 그림은 필요 없다. 기존대로." 자동 생성 도표가
  절 이해에 도움이 안 되고 산만함.
- (철회 내용)
  - `claude_service`: `_claude_convert_input`·`_claude_chat_write` 를 차트 가이드 이전으로 복구
    — `system=_CONVERT_SYSTEM`/`_CHAT_SYSTEM + _chat_context_block`(가이드 미포함),
    파싱 `_extract_fenced(raw,("json",))`, 변환 `max_tokens` 8000. **RFP 반영(직전 요청)은 유지.**
    `_CHART_GUIDE` 앞머리 '적극 삽입' 문구도 원복.
  - 데이터 정리: 저장된 `yaml/section_*.yaml`·`nodes/*/result.yaml` 에서 생성된 ```chart 블록
    44개 제거(09754646 등, 산문은 보존). 이후 스캔 시 ```chart 잔존 0.
- 유의: **파이프라인(`apply_markdown_images`)·마커 문법(```chart · ![](url))·env 게이트는 그대로 유지** —
  사용자가 의미 있는 도표를 마커로 직접 넣으면 빌드 시 실제 그림으로 변환된다(자동 생성만 중단).
  이미 빌드된 `output/final.hwpx` 는 정리 전 산출물이므로, 도표를 없애려면 **다시 [hwpx 빌드]** 한다.
