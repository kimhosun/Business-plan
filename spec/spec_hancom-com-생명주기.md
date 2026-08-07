# spec: 한컴 COM 생명주기 — 사용자 창을 닫지 않기

hwp↔hwpx 변환·PDF 내보내기가 한컴(Hancom) COM 자동화를 쓸 때, 사용자가 열어둔
한글/PDF 창을 닫지 않도록 하는 규칙. 관련: [변환 출력 품질](spec_webapp-변환출력품질.md).

## ① 질의·요청 히스토리

- **2026-08-06** (원문 요지) "새 프로젝트 만들 때 윈도우에서 한글·PDF 파일이 꺼지는 현상 개선."

## ② 확정 사양

- **원인**: pyhwpx `Hwp(new=False)`(기본)는 Running Object Table 을 뒤져 **이미 실행 중인
  사용자 한글 인스턴스에 부착(attach)** 한다. 이후 `quit()`(=`HwpObject.Quit()`)은 앱 **전체**를
  종료해 사용자가 열어둔 문서 창까지 닫는다. 또 `Hwp(visible=False)` 로 부착하면 생성 시점의
  **활성 창(사용자 문서)이 숨겨진다**.
- **규칙**: 자동화 전에 한컴 실행 여부를 판정(`_hancom_running`, pyhwpx 와 동일한 `!HwpObject.`
  모니커 기준)하고,
  - **이미 실행 중(pre_running=True)**: 작업 후 `quit()` 하지 않고 **우리가 연 활성 문서만**
    `close(is_dirty=False)` 로 닫는다(앱·사용자 창 보존). 생성 시 `visible=True` 로 부착해
    사용자 창을 숨기지 않는다.
  - **우리가 새로 띄움(pre_running=False)**: `visible=False`(헤드리스)로 띄우고, 작업 후
    `quit(save=False)` 로 우리가 만든 인스턴스만 종료한다.
  - 즉 `visible=pre_running`, 종료는 `pre_running ? close : quit`.
- **적용 범위**: `.hwp→.hwpx` 변환(`hwp2hwpx.py convert`)과 `hwpx→pdf`(`pipeline.hwpx_to_pdf`).
  `.hwpx→.hwpx` 복사 경로는 COM 을 아예 쓰지 않아 무관.
- **트레이드오프**: 사용자 인스턴스에 붙은 경우 앱을 종료하지 않으므로, 드물게 이전 자동화가
  남긴 빈 인스턴스가 잔존할 수 있다(사용자 파일 보호가 우선). 부착 시 변환 문서가 잠깐 보일 수 있음.

## ③ 구현 상태 (완료 2026-08-06)

- [x] `.claude/skills/hwpx-yaml-roundtrip/scripts/hwp2hwpx.py`: `_hancom_running`/`_shutdown`
      추가, `Hwp(visible=pre_running)` + 조건부 close/quit. (서브프로세스라 서버 재기동 불필요)
- [x] `webapp/backend/pipeline.py`: `hwpx_to_pdf` 에 동일 로직(`_hancom_running`/`_shutdown_hwp`).

## ④ 미결/후속

- 잔존 빈 인스턴스 정리(문서 0개 + 우리가 만든 것 판별)는 신뢰 판정이 어려워 보류.
- `yaml2hwpx.py restore` 는 COM 미사용(ZIP+XML)이라 무관.
