---
name: webapp-dev
description: webapp/ 연구개발계획서 작성 웹서비스를 띄우고, 다른 PC에서 푸시한 원격 커밋을 로컬 미커밋 작업분을 잃지 않고 안전하게 반영한다. git fetch 로 ahead/behind 와 "원격 커밋 ↔ 로컬 dirty 파일" 겹침을 먼저 판정한 뒤 stash → pull --ff-only → stash pop 으로 동기화하고, 포트 점검·의존성 확인·uvicorn --reload 백그라운드 기동·HTTP 200 헬스체크까지 수행한다. 트리거 예 "웹 켜줘", "서버 띄워줘", "푸시한 내용 이 PC에 반영해줘", "최신 받고 웹 실행해줘", "8000 포트가 안 열려".
allowed-tools: Bash, Read, Grep, Glob
---

# webapp 실행 + 원격 변경 안전 반영

저장소 루트는 `c:\Users\kimhs\Business-plan`, 앱은 `webapp/` (FastAPI + 정적 프런트).
이 스킬은 **A. git 안전 동기화 → B. 서버 기동 → C. 검증** 순서로 진행한다.

- "웹 켜줘"만 요청받아도 **A를 먼저 가볍게 확인**한다(fetch 후 behind면 사용자에게 알림).
  단, 사용자가 동기화를 원하지 않거나 dirty 상태가 복잡하면 B만 하고 A는 보고만 한다.
- "반영해줘"만 요청받으면 A만 하고, 서버가 이미 떠 있으면 `--reload` 가 알아서 재시작한다(C로 확인).

핵심 원칙: **로컬 미커밋 작업분을 절대 버리지 않는다.** `git checkout --`, `git reset --hard`,
`git stash drop`, `git clean` 은 사용자가 명시적으로 요구하지 않는 한 쓰지 않는다.

---

## A. 원격 변경 안전 반영

### A-1. 상태 판정 (먼저 읽기만 한다)

```bash
git remote -v
git status --short
git fetch origin
git rev-list --left-right --count origin/main...main   # "<behind> <ahead>"
git log --oneline main..origin/main                    # 새로 받을 커밋
```

`rev-list --left-right --count origin/main...main` 출력은 **왼쪽 = origin/main 이 앞선 수(받을 것)**,
**오른쪽 = 로컬 main 이 앞선 수(밀 것)** 이다.

| behind | ahead | dirty | 조치 |
|---|---|---|---|
| 0 | 0 | - | 이미 최신. A 종료 |
| N | 0 | 없음 | `git pull --ff-only origin main` 바로 |
| N | 0 | 있음 | **A-2 (stash 경유)** |
| N | M | - | 갈라짐 — **자동 처리 금지.** 상황을 보고하고 rebase/merge 여부를 사용자에게 묻는다 |
| 0 | M | - | 로컬만 앞섬 — 푸시 여부를 묻는다(임의 푸시 금지) |

### A-2. 겹침 분석 → stash 경유 pull

pull 전에 **원격 커밋이 건드린 파일**과 **로컬 dirty 파일**이 겹치는지 본다. 겹치면 충돌 가능성을
미리 알고 시작하는 것이고, 안 겹치면 무조건 깨끗이 붙는다.

```bash
git show --stat --oneline <원격커밋SHA>   # 또는: git diff --name-only main..origin/main
git diff --stat                           # 로컬 dirty
git diff                                  # 겹치는 파일은 내용까지 확인
```

겹치는 파일은 **원격 쪽이 그 부분을 실제로 바꿨는지**까지 확인하면 판단이 정확해진다:

```bash
git show <SHA>:webapp/backend/rfp.py | sed -n '40,100p'
```

그다음 stash → ff-only pull → pop:

```bash
git stash push -m "pre-pull local wip (<무엇인지 짧게>)"
git pull --ff-only origin main
git stash pop
```

- `--ff-only` 를 쓴다. 조용히 merge 커밋이 생기는 것을 막는다(갈라졌으면 여기서 실패 → 위 표대로 사용자에게).
- `git stash pop` 은 **성공하면 stash 를 지우고, 충돌하면 stash 를 남긴다.** 충돌 시 되돌릴 여지가 있다.
- pop 이 3-way 자동 병합에 성공하면 `Auto-merging <파일>` 만 뜨고 `CONFLICT` 는 없다.

### A-3. 충돌 처리

`CONFLICT` 가 나면 **임의로 해결하지 않는다.** 파일별로 무엇이 부딪혔는지 보고하고 사용자의 판단을 받는다.

```bash
git status --short | grep -E '^(UU|AA|DD|AU|UA)'
git diff --diff-filter=U
git stash list        # pop 실패 시 stash 는 남아 있다
```

되돌리려면 (사용자 확인 후): `git checkout --merge -- <파일>` 또는 `git reset --merge` 로 pop 전 상태 복구.

### A-4. 동기화 후 보고 항목

- 받은 커밋 SHA·제목·파일수/증감
- **신규 파일**(새 모듈·새 spec) — 이후 임포트 검증 대상
- **로컬 미커밋분이 어떻게 됐는지** — 보존됐는지, 자동 병합됐는지, 충돌했는지 파일별로
- 미커밋분은 **자동 커밋하지 않는다.** 커밋·푸시는 사용자에게 묻는다

---

## B. 서버 기동

### B-1. 포트 점검

```bash
netstat -ano | grep -i LISTENING | grep ':8000'
```

이미 떠 있으면 **또 띄우지 않는다.** `--reload` 라 코드 변경은 자동 반영되므로 C(헬스체크)만 한다.
포트를 정말 비워야 하면 PID 를 확인해 사용자에게 알리고 종료 여부를 묻는다.

### B-2. 의존성 확인

`webapp/requirements.txt` 가 최근에 바뀌었으면(특히 A 로 pull 한 직후) 설치 여부를 먼저 본다.

```bash
git diff webapp/requirements.txt
python -c "import fastapi,uvicorn,yaml,anthropic;print('core ok')"
python -c "import fitz;print('pymupdf ok')"
python -c "import pdfplumber;print('pdfplumber ok')"
```

빠진 게 있으면: `python -m pip install -r webapp/requirements.txt`
(`import fitz` 는 deprecation 경고를 낸다 — 정상. 정식 모듈명은 `pymupdf`.)

### B-3. 기동

**Bash 툴의 `run_in_background: true` 로 띄운다.** 포그라운드로 띄우면 세션이 막힌다.

```bash
cd /c/Users/kimhs/Business-plan/webapp && python -m uvicorn backend.main:app --reload --port 8000 2>&1
```

- `cd webapp` 이 필수다 — `backend.main` 은 `webapp/` 기준 임포트 경로이고, `--reload` 감시 대상도 `webapp/` 가 된다.
- 백그라운드 실행은 로그 파일 경로를 돌려준다. 이후 `tail` 로 그 파일을 본다.
- 한컴오피스(COM) 는 hwp→hwpx 변환·PDF 미리보기에만 필요하다. 없어도 서버는 뜬다.

관련 환경변수(README 참조): `ANTHROPIC_API_KEY` · `CLAUDE_CLI_PATH` · `CLAUDE_EFFORT` · `CLAUDE_DISABLE_CLI=1`.
키가 없으면 Claude Code CLI 로 폴백하고, 그것도 없으면 **스텁 모드**로 동작한다(응답에 `(스텁 모드)` 표기).

---

## C. 검증

```bash
for i in 1 2 3 4 5 6 7 8 9 10; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/ 2>/dev/null)
  if [ "$code" = "200" ]; then echo "UP (HTTP $code)"; break; fi
done
tail -20 "<백그라운드 로그 경로>"
```

`Application startup complete.` + HTTP 200 이면 정상.

A 로 pull 한 직후라면 **신규 모듈 임포트까지 확인**한다(`--reload` 는 임포트 에러가 나도
이전 프로세스를 유지할 수 있어 로그만으로는 놓친다):

```bash
cd /c/Users/kimhs/Business-plan/webapp && python -c "from backend import main, doc_fill, rfp, tables, store; print('all modules import OK')"
```

사용자 안내: **프런트가 바뀌었으면 브라우저 강제 새로고침(Ctrl+Shift+R)** 을 시킨다.
`app.js`/`styles.css` 는 캐시(304)로 구버전이 남는다 — 로그의 `304 Not Modified` 로 확인 가능.

접속 주소: **http://127.0.0.1:8000**

---

## 함정·주의

- **`webapp/data/` 는 `.gitignore` 대상**(개인정보 포함 가능). 산출물을 커밋하지 않는다.
- pull 하면 `--reload` 가 파일 변경을 감지해 재시작한다. 로그에 `WatchFiles detected changes ... Reloading...`
  이 뜬 뒤 새 프로세스가 떴는지 확인한다.
- 스킬 스크립트(`.claude/skills/hwpx-yaml-roundtrip/scripts/`)도 원격 커밋에 포함될 수 있다.
  백엔드가 이 CLI 를 직접 호출하므로, 동기화 후 hwpx 빌드가 이상하면 여기 변경을 먼저 의심한다.
- 파이프라인 계약·API 스펙은 [webapp/ARCHITECTURE.md](../../../webapp/ARCHITECTURE.md),
  실행·사용 흐름은 [webapp/README.md](../../../webapp/README.md) 가 원본이다. 이 스킬은 그 문서를 대체하지 않는다.
