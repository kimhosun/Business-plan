# webapp 개발 실행·동기화

## ① 질의·요청 히스토리

- **2026-08-12** — "웹 켜줘". `webapp/` FastAPI 앱을 기동 요청. 포트 8000 비어 있음 확인,
  의존성(PyMuPDF·pdfplumber 포함) 설치 확인 후 `uvicorn backend.main:app --reload --port 8000`
  백그라운드 기동, HTTP 200 확인.
- **2026-08-12** — "https://github.com/kimhosun/Business-plan.git · 작업한 내용 푸쉬한 게
  이 PC에 반영이 안 되어 있어. 반영해줘". 다른 PC에서 푸시한 `c0d3b65` (24파일, +4626/−411) 를
  로컬 미커밋 3파일을 유지한 채 반영. stash → `pull --ff-only` → stash pop 으로 무충돌 자동 병합.
- **2026-08-12** — "지금 했던 내용 스킬로 만들어줘". 범위를 물어 **"둘 다 한 스킬"** 선택 →
  `webapp-dev` 스킬 1개로 통합 작성.

## ② 확정 사양

**스킬**: [.claude/skills/webapp-dev/SKILL.md](../.claude/skills/webapp-dev/SKILL.md) — 원본은 그 파일.
여기에는 결정 사항만 남긴다.

- 단일 스킬 `webapp-dev` 가 **A. git 안전 동기화 → B. 서버 기동 → C. 검증** 세 단계를 모두 담는다.
  "웹 켜줘"와 "푸시한 거 반영해줘"가 실제로는 한 흐름(최신 받고 띄우기)이라 분리하지 않는다.
- **안전 규칙(불변)**: 로컬 미커밋 작업분을 파기하지 않는다 —
  `reset --hard` · `checkout --` · `clean` · `stash drop` 금지(사용자 명시 요구 시에만).
- **pull 은 `--ff-only`**. 갈라지면(local ahead & behind) 자동 처리하지 않고 사용자 판단을 받는다.
- **pull 전 겹침 분석**: 원격 커밋이 건드린 파일 ↔ 로컬 dirty 파일을 대조해 충돌 가능성을 미리 판정한다.
- **충돌 시 임의 해결 금지**. 파일별 보고 후 사용자 판단. 미커밋분 자동 커밋·자동 푸시도 하지 않는다.
- **기동 규약**: `cd webapp` 필수(임포트 경로 · `--reload` 감시 범위), 백그라운드 실행,
  포트 8000 이 이미 LISTENING 이면 재기동하지 않고 헬스체크만.
- **동기화 직후 검증**은 로그 + HTTP 200 만으로 부족하다. `--reload` 가 임포트 에러를 삼킬 수 있어
  신규 모듈 임포트를 별도 확인한다. 프런트 변경 시 사용자에게 강제 새로고침(Ctrl+Shift+R) 안내.

## ③ 구현 상태

- ✅ `webapp-dev` 스킬 작성 완료 (2026-08-12).
- ✅ 이번 세션에서 절차 실증: `c4607e7 → c0d3b65` ff-pull, 미커밋 3파일
  (`webapp/backend/rfp.py` · `webapp/requirements.txt` · `spec/spec_rfp-자동작성.md`)
  stash pop 무충돌 자동 병합, 전 모듈 임포트 OK, HTTP 200.
- 관련 주제 원본: 실행·사용 흐름 [webapp/README.md](../webapp/README.md),
  API·저장구조 계약 [webapp/ARCHITECTURE.md](../webapp/ARCHITECTURE.md).

## ④ 미결/후속

- 로컬 미커밋 3파일(PyMuPDF 임포트 폴백 + requirements + spec)의 커밋·푸시 여부 **미정**.
- 포트 8000 이 이미 점유됐을 때의 프로세스 종료 절차는 정의하지 않았다 — PID 보고 후 사용자 판단.
- `main` 외 브랜치 운용은 고려하지 않았다(현재 단일 `main`).
