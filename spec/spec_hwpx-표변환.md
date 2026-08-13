# spec: 마크다운 표(| a | b |) → 실제 HWPX 표

자동작성 초안이 텍스트로 만든 파이프 표를, 복원 시 본문 문단을 쪼개 **실제 HWPX 표**로
바꾼다. 관련: [글꼴·내어쓰기](spec_hwpx-글꼴적용.md), [RFP 자동작성](spec_rfp-자동작성.md).

## ① 질의·요청 히스토리

- **2026-08-06** (원문 요지) "'○ 관련 SW·플랫폼 시장' 아래처럼 파이프 표로 들어간 내용을
  실제 표로 넣어야 함. 그런 사례가 여럿 있으니 반영해서 수정."
- **2026-08-13** (원문 요지) "왼쪽에 작성된 걸 표로 새로 만들었는데, 오른쪽 기존에 있던
  표에 삽입해야 해. 수정." (2-1 성능목표표: AI가 쓴 마크다운 표가 별도 새 표로 렌더되어
  소스의 빈 공식 템플릿 표와 **중복**됨.) → 결정: **템플릿 서식 유지+내용 구조로 재구성**,
  **파이프라인 전반(코드)** 로 처리(AskUserQuestion).

## ② 확정 사양

- **원인**: 조사 초안에 `| 시장 구분 | 기준연도 규모 | … |` 같은 마크다운 표가 텍스트로 있고,
  packed 세그먼트가 여러 줄을 한 문단에 몰아넣어(fixed-slot overlay 한계) 표가 파이프 텍스트로 렌더됨.
- **표 대상 문단 제외**(`pipeline.body_paths`): 표를 품은 문단(sX/pY 아래 sX/pY/tZ 표 노드 존재)도
  자동작성 대상에서 제외 → 긴 본문이 표-문단에 섞이지 않게.
- **변환**(`hwpx_common.apply_markdown_tables`): 복원 후, 표를 품지 않은 본문 문단의 텍스트를
  블록으로 나눠(마크다운 표행 연속 = 표 블록, 그 외 = 텍스트) 원 문단 자리에 순서대로 삽입:
  - 표 블록 → `python-hwpx add_table(rows,cols)` + `set_cell_text` 로 **실제 표** 생성(유효 refs).
  - 텍스트 블록 → **줄마다 별도 문단**(개조식 한 항목=한 문단 → 내어쓰기 정상 적용).
  lxml `addnext` 로 원 위치에 끼우고 원 문단 제거. 표 셀 내부·기존 표는 건드리지 않음.
- **복원 후처리 순서**: `apply_markdown_tables`(표 생성) → `apply_fonts`(새 셀도 돋움 8pt) →
  `apply_hanging_indent`(쪼갠 개조식 문단에 내어쓰기). 기본 OFF, 웹앱 `pipeline.restore` 가
  `HWPX_MD_TABLES=1`(+글꼴·내어쓰기)로 켬.

## ③ 구현 상태 (완료 2026-08-06)

- [x] `pipeline.body_paths`: 표-품은 문단도 제외.
- [x] `hwpx_common.apply_markdown_tables`(+`_md_blocks`/`_md_parse_row`/`_host_para_of` 등).
- [x] `yaml2hwpx.py` restore: fonts 앞에서 env 게이트로 호출. `pipeline.py`: `HWPX_MD_TABLES=1`.
- [x] 검증(6d90731b, 1-2 리셋·본문 재작성 후): 마크다운 표 **17개 → 실제 HWPX 표**. 파이프 텍스트
  ('| 시장 구분 |') 잔존 0. 변환 표 셀 = 돋움 8pt(charPr 360), '○ 관련 SW·플랫폼 시장' 단독 문단·
  내어쓰기(-1800/-3600). 파일 정상 오픈·zip 무결성 OK.

### 2026-08-06 후속 — 표 안에 전체가 들어감(해결)
- 증상: 1-2 '국내 기술 동향 및 수준' 템플릿 표 셀(r0/c1)에 산문 전체가 들어가 있었음
  (원래 자동작성이 셀을 채웠던 잔재 + result.yaml 이 옛 20행 매핑으로 남아 있었음).
- 확정: **산문 전체는 본문 필드로, 시장 실적 등 표형 내용(| 구분 | 2025년 실적 | 선박 수출액 |…)만
  실제 표로.** 템플릿 안내표는 placeholder 로 남김(사용자가 삭제).
- 조치: 해당 표-품은 문단(s2/p94)+셀 7개를 원본 placeholder 로 리셋, result.yaml 을 body-only(12행)로
  재작성, input.md 를 본문 필드로 재분배. 이후 markdown 표 변환이 셀 밖 본문의 표형 텍스트를 실제 표로.
- 검증(built): '(강점)…' 산문 in_cell=False(필드), '선박 수출액' in_cell=True(실제 표), 파이프 텍스트 0,
  안내표 placeholder 유지. 코드(body_paths 셀·표문단 제외 + markdown 변환)로 신규 자동작성엔 자동 적용.

### 2026-08-13 — 마크다운 표를 기존 '빈 템플릿 표'에 삽입(중복 제거)
- **원인**: 소스에 빈 공식 템플릿 표(예: 2-1 성능목표표 `s2/p109/t0`, 12행×13열)가 있는데
  AI가 같은 내용을 마크다운 표로 써서, `apply_markdown_tables` 가 이를 **새 표**로 만들어
  빈 템플릿과 중복됨. 게다가 과제 단계구조(1단계 2차+2단계 2차)가 템플릿 열(1단계 3차+n단계)과
  달라 단순 삽입 불가 → **템플릿을 md 내용 구조로 재구성**하는 방식 채택.
- **확정 사양**(`hwpx_common.fill_template_tables_from_markdown`, `apply_markdown_tables` **직전** 실행):
  1. 순수 마크다운-표 문단(그 밖 실질 텍스트 없음)을 찾고, 그 **뒤쪽 최상위 문단**을 훑어
     (텍스트 문단은 건너뜀, window=6) **'비었고(셀 공백비율≥0.5) 헤더가 유사(≥0.4)'** 한
     템플릿 표를 페어링. 다음 표가 이미 채워졌거나 헤더가 다르면 페어링 안 함(안전).
  2. 페어링되면 **md 행×열로 새 표를 만들되 템플릿 셀 스타일(표·헤더·본문 `borderFillIDRef`)을
     이식** → 테두리·헤더 음영 유지(글꼴·가운데·폭맞춤은 뒤의 apply_fonts/table_layout 이 덮음).
     `**볼드**`·`__밑줄__` 마커는 셀에서 제거.
  3. 새 표를 **md 문단 자리**에 넣고 md 문단과 원래 빈 템플릿 표를 제거(중복 해소, 순서 보존).
  - 페어링 안 되는 md 표는 손대지 않음 → 기존대로 `apply_markdown_tables` 가 새 표로 변환(폴백).
  - 게이트: `HWPX_FILL_TEMPLATES`(기본 1, `HWPX_MD_TABLES` 블록 안에서 실행).
- **구현 상태(완료 2026-08-13)**: [hwpx_common.py](.claude/skills/hwpx-yaml-roundtrip/scripts/hwpx_common.py)
  `fill_template_tables_from_markdown`(+`_is_empty_template_table` 셀단위 판정, `_header_similarity`,
  `_find_pair_template_table`, `_build_table_like`, `_md_cell_clean`).
  [yaml2hwpx.py](.claude/skills/hwpx-yaml-roundtrip/scripts/yaml2hwpx.py): md 변환 직전 호출.
  검증(09754646): "template tables filled: 2", md표 21→19, 한컴 PDF 에서 성능목표표·핵심어·지표및목표가
  **템플릿 음영 헤더로 채워지고** 빈 템플릿('개발 목표치' 헤더) 잔존 0, 전 XML 정상.

## ④ 미결/후속

- 표 폭/열너비는 python-hwpx 기본값(균등) — 열별 폭 자동조정은 후속.
- 템플릿 페어링은 '헤더 유사도+빈 표+근접'을 신뢰조건으로 보수적 동작 — 유사도가 낮으면
  삽입 대신 새 표(폴백). 대응 템플릿 없는 자유 md 표(예: 평가방법·평가환경)는 새 표로 남고,
  그 셀의 `<br>` 리터럴은 별도 이슈(현재 미처리).
- 표 안에 다시 표(중첩)는 미변환. 병합셀 마크다운(rowspan/colspan)은 지원 안 함(단순 격자만).
- 표를 품은 문단에 섞여 있던 기존 프로젝트 콘텐츠는 본문 재작성으로 옮겨야 반영됨
  (현재 프로젝트는 1-2 리셋·재작성 완료). 새 자동작성은 자동 반영.
