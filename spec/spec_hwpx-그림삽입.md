# spec: 마크다운 그림/차트(```chart · ![](url)) → 실제 HWPX 그림개체

자동작성 초안의 **데이터 차트**와 **온라인/로컬 이미지**를, 복원 시 본문 문단을 쪼개
**실제 HWPX 그림개체(`<hp:pic>`)** 로 바꾸고 그 아래 `<그림 N>` 캡션(+출처)을 붙인다.
관련: [표변환](spec_hwpx-표변환.md), [글꼴·내어쓰기](spec_hwpx-글꼴적용.md),
[RFP 자동작성](spec_rfp-자동작성.md), [변환출력품질](spec_webapp-변환출력품질.md).

## ① 질의·요청 히스토리

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
