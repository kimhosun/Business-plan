# spec: HWPX 복원 서식 후처리 (글꼴·크기 + 개조식 내어쓰기)

최종 HWPX 복원 시 (1) 본문=돋움 12pt·표 셀=돋움 8pt 강제, (2) 개조식 문단의 마커(□·○·-…)
폭 기준 자동 내어쓰기(hanging indent)를 전 구간에 적용.
관련: [변환 출력 품질](spec_webapp-변환출력품질.md), [RFP 자동작성](spec_rfp-자동작성.md).

## ① 질의·요청 히스토리

- **2026-08-06** (원문 요지) "HWPX 변환할 때 본문내용은 돋움체 12pt, 표 안 내용은 돋움 8pt로.
  전체 적용."
- **2026-08-06** (후속) "1-1 내용에서 hwpx로 변환할 때 도형(ㅁ·ㅇ·- 등)에 맞추어 자동으로
  내어쓰기 적용." → 개조식 문단이 줄바꿈되면 둘째 줄 이하가 마커 아래로 되돌아가 정렬이
  깨지는 문제. 마커 폭만큼 내어쓰기해 마커 뒤 본문에 줄맞춤.
- **2026-08-06** (후속2) "헤드(ㅁ·ㅇ·-)를 제외한 한글 시작위치에서 둘째 줄부터 앞줄 맞추기
  (Shift+Tab)." → 위 내어쓰기와 동일 요구의 재확인. 마커 집합에 ㅁ/자모·기호 불릿 추가로 보강."
- **2026-08-11** (원문 요지) "한글 본문 글자체는 **돋움체**로 변경." + 문답: "돋움이랑 돋움체는 다르다"
  → 최초 요청(2026-08-06)의 '본문=돋움체'가 구현에서 본문·셀 모두 **돋움**으로 뭉뚱그려졌던 것을
  정정. **본문=돋움체(고정폭), 표 셀=돋움**으로 분리 적용.

## ② 확정 사양

- **적용 규칙**: 복원(restore)으로 만든 최종 hwpx 에서 **텍스트가 있는** run 의 글꼴/크기를 강제.
  - 표 셀(`<hp:tc>` 하위) 안의 텍스트 run → **돋움 8pt**(height=800).
  - 그 외 본문 텍스트 run → **돋움체 12pt**(height=1200). *(2026-08-11: 본문 돋움→돋움체)*
  - **본문/셀 글꼴 분리**: `HWPX_FONT`(본문)·`HWPX_CELL_FONT`(셀)로 각각 지정. cell_face 가
    문서 fontfaces 에 없으면 본문 글꼴로 폴백. 웹앱은 본문=돋움체·셀=돋움.
  - **빈 run(간격용 빈 문단 등)은 건드리지 않음** → 레이아웃이 부풀지 않음.
- **구현 방식**: `hwpx_common.apply_fonts(hwpx, face, body_pt, cell_pt)` 후처리.
  1) header.xml 에 기준 charPr 를 복제해 본문(12pt)·셀(8pt) charPr 2개를 추가(fontRef 를
     각 언어그룹의 '돋움' font id 로 교체, itemCnt +2).
  2) 각 section*.xml 의 run 을 표셀 여부(`_tc_spans` 중첩 추적)로 판별해 charPrIDRef 를
     본문/셀 charPr 로 치환. 순수 문자열 치환이라 prefix(hh:/hp:)·기타 바이트 보존, zip 순서·
     압축(mimetype=stored) 유지.
- **호출 지점**: `yaml2hwpx.py restore` 가 save 직후 apply_fonts 호출. **기본은 OFF**
  (`HWPX_APPLY_FONTS`=0)로 스킬의 순수 왕복 무손실 계약을 보존. **웹앱만 켠다**:
  `pipeline.restore` 가 `HWPX_APPLY_FONTS=1, HWPX_FONT=돋움체, HWPX_CELL_FONT=돋움,
  HWPX_BODY_PT=12, HWPX_CELL_PT=8` 를 서브프로세스 env 로 주입(사용자 env 가 있으면 그것을 우선).
- **적용 범위**: 웹앱의 [hwpx 빌드]·④ 변환 HWPX 다운로드(둘 다 pipeline.restore 경유) 전체.
- **멱등성**: restore 는 매번 source 에서 새로 복원 후 fonts 적용 → charPr 누적 없음.

## ③ 구현 상태 (완료 2026-08-06)

- [x] `hwpx_common.py`: `apply_fonts` + 헬퍼(`_font_ids_by_lang`, `_clone_charpr`,
      `_augment_header`, `_tc_spans`, `_rewrite_section_runs`). `import os` 추가.
- [x] `yaml2hwpx.py`: restore 에서 save 후 env 게이트로 apply_fonts 호출(기본 OFF).
- [x] `webapp/backend/pipeline.py`: `_run(env=)` 추가, restore 가 폰트 env 주입(기본 ON).
- [x] 검증(프로젝트 6d90731b): charProperties itemCnt 359→361, 새 charPr 359=돋움 12pt·
      360=돋움 8pt. 본문 run 730개→359, 표 셀 run 3273개→360. 파일 정상 오픈·zip 무결성 OK.
      본문 '연구개발계획서'→359, 표셀 '[ √ ] 일반형' 등→360 확인. 바레 CLI(env 없음)는 미적용.

### 2026-08-11 후속 — 본문 돋움체 / 셀 돋움 분리 (완료)
- [x] `hwpx_common.py`: `apply_fonts(…, cell_face=None)` + `_augment_header(header, face, cell_face, …)`
      — 본문 charPr 는 face(돋움체), 셀 charPr 는 cell_face(돋움) fontRef 로 클론. cell_face 미등록 시
      본문 글꼴로 폴백.
- [x] `yaml2hwpx.py`: `HWPX_CELL_FONT` env 읽어(기본=HWPX_FONT) apply_fonts 에 cell_face 전달.
- [x] `webapp/backend/pipeline.py`: `HWPX_FONT=돋움체`, `HWPX_CELL_FONT=돋움` 주입.
- [x] 검증(f44ab9f7 source): apply_fonts ok, body charPr 359=hangulFont 3(돋움체) 1200,
      cell charPr 360=hangulFont 2(돋움) 800, runs=3932. 돋움체 id=3·돋움 id=2 확인.

## ②-내어쓰기 확정 사양

- **규칙**: 본문 문단(표 셀 제외)의 텍스트가 마커(□·■·○·●·◇·-·※··o·1.·1)·(1)·가.·① 등)로
  시작하면, 그 **마커 프리픽스(선두 공백+마커+뒤 공백) 폭만큼 둘째 줄 이하를 내어쓰기**한다.
- **폭 계산**: 전각(East_Asian_Width W/F/**A**)=body_pt×100, 반각=body_pt×50 HWPUNIT.
  `□`·`○` 등은 Unicode 상 'A'(Ambiguous)지만 한글 문서에선 전각 렌더 → 전각으로 계산.
  예: `□ ` = 1200+600 = 1800 → CASE intent=-1800, DEFAULT intent=-3600(문서 표준과 동일).
- **HWPX 표기**: paraPr margin 은 `<hp:switch>` 로 CASE(char)·DEFAULT(HWPUNIT) 두 갈래이며
  이 문서는 **DEFAULT=2×CASE** 규약. CASE intent=-em, DEFAULT intent=-2em 로 두 갈래 모두 설정.
  `left`(단계 들여쓰기)는 원본 유지. 문단의 기존 paraPr 를 복제(마커폭·원 paraPr 별 dedup)해
  새 paraPr 로 부여, itemCnt 증가.
- **구현**: `hwpx_common.apply_hanging_indent(hwpx, body_pt)`. 기본 OFF(`HWPX_HANGING_INDENT`=0),
  웹앱 `pipeline.restore` 가 =1 로 켬. 표 셀은 `_tc_spans` 로 판별해 제외.

## ③ 구현 상태 (완료 2026-08-06)

- [x] 글꼴: `hwpx_common.apply_fonts` + `yaml2hwpx.py`(env 게이트) + `pipeline.py`(env 주입).
- [x] 내어쓰기: `hwpx_common.apply_hanging_indent`(+`_HANG_PREFIX`,`_prefix_em`,`_clone_parapr_hang`,
      `_leading_text`), `yaml2hwpx.py` restore 에서 fonts 뒤 호출(기본 OFF), `pipeline.py` =1.
- [x] 검증(6d90731b): 글꼴 charPr 359/360, 본문 730·셀 3273 run. 내어쓰기 본문 301문단 적용,
      표 셀 0(제외). □·○ → paraPr intent -1800/-3600(문서 표준 일치). 파일 정상 오픈·zip 무결성 OK.

## ④ 미결/후속

- 돋움이 문서 fontfaces 에 없으면 글꼴 미적용(ok=False) — 대상 문서엔 존재.
- '돋움체'가 아니라 '돋움' 사용(요청 문구). 필요 시 `HWPX_FONT` 로 변경.
- 내어쓰기 폭은 글리프 실측이 아닌 전각/반각 근사 → 비례폭 글꼴에서 미세 오차 가능
  (문서 표준값과 동일해 기존 내어쓰기 문단과 일관). 마커가 리스트 밖 실행에 걸치면 미검출 가능.
- Hancom COM PDF 미리보기는 후처리본을 여는데, 유효 hwpx 라 정상 예상(라이브러리 오픈 검증됨).
- 제목/머리말 등도 본문 규칙(12pt)으로 통일됨('전체 적용' 취지). 특정 스타일 예외가 필요하면 후속.
