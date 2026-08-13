# webapp 절별 에이전트 + 실시간 스트리밍 작성 + 변경사항 검토(diff)

> 대상: `webapp/` 연구개발계획서 작성 웹서비스의 ③ 입력 탭 "AI와 대화하며 작성" 패널.
> 관련 원본: 아키텍처 계약 [webapp/ARCHITECTURE.md](../webapp/ARCHITECTURE.md),
> 작성 프롬프트 [spec_webapp-작성프롬프트.md](spec_webapp-작성프롬프트.md),
> 작성 규정 [spec_webapp-작성규정.md](spec_webapp-작성규정.md),
> RFP 자동작성 [spec_rfp-자동작성.md](spec_rfp-자동작성.md).

## ① 질의·요청 히스토리

- **2026-08-13** — "이거 어디서 응답해?" (채팅이 "작성 중…"에 머문 화면).
  답: 프론트 `sendChat()` → `POST /api/projects/{pid}/nodes/{nid}/chat` → `claude_service.chat_write()`
  → **API 키 → `claude` CLI 헤드리스 → 스텁** 폴백. 이 PC 는 키가 없어 **CLI 경로가 실제 동작 경로**이고,
  응답이 끝날 때까지 통째로 기다리므로 30초~1분(웹 조사 절은 최대 600초) 걸린다.
- **2026-08-13** — "이걸 에이전트로 챕터별로 채팅마다 에이전트를 달리해서 붙이려고 한다.
  챕터에 프롬프트·지침이 있고 이걸 에이전트가 받아 왼쪽 화면에 사용자 요청 시 문서를 실시간으로 작성해 준다.
  결과가 실시간으로 나왔으면 좋겠다."
  → 갈림길 3개를 물어 확정: **(1) 절별 세션 유지형 에이전트**, **(2) 왼쪽 입력칸에 직접 실시간 타이핑**,
  **(3) 사양서 먼저 → 승인 후 구현**.
- **2026-08-13** — "변경된 사항, 정확히 단어까지. 삭제된 건 붉은색, 추가된 건 녹색으로 하고
  각각 연결된 하나의 아이템으로 보고 accept 할지 reject 할지 선택할 수 있고, 일괄 취소·삭제·추가 기능도 넣어줘."
  → **§2.9 변경사항 검토(diff) 모드** 추가. 저장 시점이 '스트림 종료 즉시' → **'사용자 검토 후 적용'** 으로 바뀐다.

## ② 확정 사양

### 2.1 목표

절(챕터)마다 **자기 규정·양식·문체를 기억하는 전용 에이전트**를 두고, 채팅 지시에 대해
**본문이 왼쪽 '사용자 원문 입력' 칸에 실시간으로 써지며**, 다 쓰고 나면 **원본 대비 단어 단위 변경분을
색으로 보여 주고 항목별로 수락/거절**할 수 있게 한다.

### 2.2 현재 구조 대비 변경점

| 구분 | 현재 | 변경 후 |
|---|---|---|
| 호출 | `_cli_text()` = `subprocess.run`, `--output-format json` (블로킹 1회) | `_cli_stream()` = `Popen` + `--output-format stream-json --include-partial-messages --verbose` NDJSON |
| 전달 | 완료 후 `{reply, draft}` 한 번에 | **SSE**(`text/event-stream`) 델타 push |
| 절 구분 | 시스템 프롬프트 꼬리(`_chat_context_block`)만 절마다 다르고 매 턴 전체 재전송 | 절마다 `agent.json`(session_id·모델·도구·프로파일). 규정은 **첫 턴에만** 주입 |
| 세션 | `--no-session-persistence` (기억 없음) | 첫 턴 `--session-id <uuid>` → 이후 `--resume <uuid>` |
| 출력 계약 | JSON 코드펜스 `{reply, draft}` | 본문 평문 스트림 → 구분자 → 짧은 reply (부분 JSON 파싱 회피) |
| 반영 | `apply=True` 면 서버가 즉시 `input.md` 덮어쓰기 | **단어 단위 diff 검토 후 사용자가 '적용'** 할 때 저장 |

전제: 설치된 CLI(`claude.exe` 2.1.229)가 `--output-format stream-json`, `--include-partial-messages`,
`--session-id`, `--resume`, `--append-system-prompt`, `--agents` 를 모두 지원함을 `--help` 로 확인했다(2026-08-13).

### 2.3 절별 에이전트 (session)

- 저장: `webapp/data/projects/<pid>/nodes/<nid>/agent.json`
  = `{session_id, model, effort, tools[], profile, system_sha, turns, created, updated}`.
- **시스템 프롬프트**(첫 턴에만 전달) = 공통 집필 규칙 + 그 절의
  ※작성요령(`node.guidelines`) · 양식 템플릿(`template.yaml`) · 문체/구성(`prompts.json`) ·
  절 지침(`regulations.regulation_for`) · 제반사항 · RFP 요지.
  기존 `_chat_context_block()` 의 조립 로직을 그대로 재사용한다.
- **프로파일**: 절 성격별로 도구·타임아웃을 달리한다. 기존 `_wants_reference_images(nid)` 규칙을
  `profile_for(nid)` 로 흡수한다.
  - `research` (1-2 동향·시장 등): `--allowed-tools WebSearch WebFetch`, timeout `CLAUDE_RESEARCH_TIMEOUT`(600s)
  - `plain` (그 외): 도구 전면 차단, timeout `CLAUDE_CLI_TIMEOUT`(300s)
- **무효화**: 템플릿·문체·규정·RFP·제반사항이 바뀌면 `system_sha` 불일치 → **새 session_id 로 재시작**하고,
  직전 채팅 이력 최근 N턴을 첫 프롬프트에 요약 재주입한다. 채팅 이력(`chat.json`) 자체는 보존한다.
- **수동 초기화**: 채팅 패널의 🗑 옆에 '에이전트 초기화' → `POST .../agent/reset` 으로 session_id 폐기.
- CLI 는 계속 `cwd=tempdir` 에서 돌려 저장소 `CLAUDE.md`/훅 자동 탐색을 타지 않는다.

### 2.4 스트리밍 출력 계약

JSON 을 스트리밍하면 부분 파싱이 필요하므로, **스트리밍 전용 시스템 프롬프트**에서 형식을 바꾼다.

```
<본문 전체 — 평문, 코드펜스·JSON 금지>
⟦REPLY⟧
<사용자에게 할 짧은 한국어 답변>
```

- 본문을 고칠 필요가 없으면 첫 줄에 `⟦REPLY⟧` 만 쓰고 답변만 쓴다(= 기존 `draft: null`).
- 서버가 델타를 구분자 기준으로 `draft` / `reply` 채널로 라우팅한다.
- 구분자 `⟦REPLY⟧` 는 본문에 등장할 수 없는 문자로 고른다.

### 2.5 API

```
POST /api/projects/{pid}/nodes/{nid}/chat/stream   → text/event-stream
  body: {message}
  event: status  data:{"text":"에이전트 준비"|"웹 조사 중…"|"작성 중…"}
  event: draft   data:{"delta":"..."}     # 왼쪽 칸에 실시간 append
  event: reply   data:{"delta":"..."}     # 말풍선에 append
  event: done    data:{"draft":"<본문 전체>", "chat":[...], "session_id":"..."}
  event: error   data:{"detail":"..."}
POST /api/projects/{pid}/nodes/{nid}/input          → 검토 후 확정본 저장(기존 저장 라우트 재사용)
POST /api/projects/{pid}/nodes/{nid}/agent/reset    → {session_id: null}
GET  /api/projects/{pid}/nodes/{nid}/agent          → agent.json (진단용)
```

- 헤더 `Cache-Control: no-cache`, `X-Accel-Buffering: no` (프록시 버퍼링 방지).
- Starlette 이 **sync generator 를 threadpool 에서 순회**하므로 `StreamingResponse` 에 sync generator 를 넘긴다
  (blocking `readline` 을 그대로 써도 이벤트 루프를 막지 않는다).
- **`input.md` 는 스트림이 건드리지 않는다.** 채팅 이력(`chat.json`)만 스트림 정상 종료 시 1회 기록하고,
  본문 저장은 사용자가 diff 를 검토하고 '적용' 했을 때 프론트가 별도 호출한다(§2.9).
- 클라이언트 연결 끊김/`GeneratorExit` → `proc.kill()`.
- 기존 `POST .../chat`(비스트리밍)은 **남겨 둔다** — 스텁 폴백·진단·스크립트용.

### 2.6 프론트 동작 — 1단계: 실시간 타이핑

- `EventSource` 는 POST 불가 → `fetch` + `res.body.getReader()` + `TextDecoder` 로 SSE 를 직접 파싱한다.
- **시작**: `const base = #input-text.value` 로 원본을 기억(= diff 기준선), textarea `readOnly=true` +
  `.streaming` 클래스, 전송 버튼이 **'중단'** 으로 바뀐다(`AbortController`).
- **draft 델타**: `#input-text` 에 append + 하단 자동 스크롤 → 요청하신 "실시간으로 써지는" 화면.
- **reply 델타**: 마지막 AI 말풍선에 append(기존 "작성 중…" 자리표시를 대체).
- **status**: 말풍선 위 회색 상태줄.
- **error/중단**: `#input-text.value = base` 로 **원본 복원**(사용자 글이 날아가지 않는다).
- '답변을 왼쪽 입력칸에 자동 반영·저장' 체크를 해제하면 왼쪽 칸을 건드리지 않고 reply 만 스트리밍한다.

### 2.7 프론트 동작 — 2단계: 변경사항 검토

스트림이 정상 종료되면 곧바로 **검토 모드**(§2.9)로 전환한다. 저장은 이 단계에서만 일어난다.

### 2.8 폴백

CLI/SDK 스트림이 실패하면 기존 `_stub_chat_write` 결과를 **SSE 형식 그대로** 한 번에 흘려보내
프론트 경로를 단일화한다(답변에 `(스텁 모드)` + 사유 유지).
`ANTHROPIC_API_KEY` 가 있으면 SDK `client.messages.stream()` 의 `text_stream` 을 같은 인터페이스로 쓴다.

### 2.9 변경사항 검토(diff) — 단어 단위·항목별 수락/거절

**모드 전환**. textarea 는 색을 못 그리므로, 검토 중에는 같은 자리에 **diff 뷰(div)** 를 띄우고
textarea 는 숨긴다. 검토를 마치면(적용/취소) 다시 textarea 로 돌아간다.

**기준선과 대상**. `base` = 스트림 시작 시점의 `input.md` 본문, `next` = 에이전트가 낸 `draft` 전체.

**diff 알고리즘**(외부 라이브러리 없이 순수 JS, 오프라인 동작).
1. 줄 단위 LCS 로 먼저 변경 블록을 좁힌다(전체 O(n·m) DP 회피).
2. 변경 블록 안에서만 **단어 단위**로 다시 diff 한다. 토큰 = `한글/영문/숫자 덩어리` · `문장부호` ·
   `공백` · `줄바꿈`. 공백은 표시에 쓰되 항목 경계 판정에서는 무시한다.
3. 붙어 있는 삭제/추가 토큰과, 사이에 **유지 토큰 3개 이하**로 끼인 변경들을 **하나의 항목(hunk)** 으로 묶는다
   → 요청하신 "각각 연결된 하나의 아이템".

**표시**.
- 삭제: 붉은색 + 취소선 (`.diff-del`, 배경 연한 적색)
- 추가: 녹색 (`.diff-add`, 배경 연한 녹색)
- 유지: 평문
- 항목마다 우측(또는 hover)에 **✓ 수락 / ✗ 거절** 버튼, 항목 번호와 현재 상태(대기/수락/거절)를 표시.
- 항목이 화면 밖이면 상단 툴바의 `◀ n/N ▶` 로 이동한다.

**항목 상태 의미**.

| 상태 | 결과 |
|---|---|
| 수락(accept) | 그 항목의 삭제분은 실제로 지우고, 추가분은 살린다(= 새 안 채택) |
| 거절(reject) | 그 항목은 원문 그대로 둔다 |
| 대기(pending) | 기본값. '적용' 시 **수락으로 간주**(툴바에서 기본값 반전 가능) |

**일괄 기능**(툴바).
- **모두 수락** — 전 항목 accept.
- **일괄 취소** — 전 항목 reject(원문 그대로 복귀). 검토 자체를 끝내려면 '검토 취소'.
- **일괄 삭제** — *삭제* 를 포함한 항목만 일괄 accept(지우자는 제안만 한 번에 반영).
- **일괄 추가** — *추가* 를 포함한 항목만 일괄 accept(덧붙이자는 제안만 한 번에 반영).
- 삭제와 추가가 한 항목에 섞여 있으면(치환) '일괄 삭제'·'일괄 추가' 양쪽 모두에서 대상으로 본다.

**확정**.
- **적용** — 항목 상태대로 병합한 텍스트를 textarea 에 넣고 `POST .../input` 으로 저장, 검토 모드 종료.
- **검토 취소** — `base` 로 되돌리고 저장 없이 종료(에이전트 답변 말풍선은 남는다).
- 검토 중 브라우저를 닫으면 저장되지 않는다. 재검토가 필요하면 채팅에서 다시 지시한다.

**스트리밍 중 diff 는 하지 않는다** — 미완성 뒷부분이 통째로 '삭제'로 보이기 때문. 1단계는 평문 타이핑,
2단계에서만 diff 를 계산한다.

### 2.10 불변 규칙

- 왼쪽 입력칸의 **기존 사용자 글을 임의로 잃지 않는다**(base 보관 → 실패·거절 시 복원).
- 부분 생성물은 파일에 쓰지 않는다. 본문 저장은 **사용자의 '적용'** 으로만 일어난다.
- 절별 에이전트는 **해당 절 밖의 내용을 쓰지 않는다**(기존 집필 규칙 유지).
- CLI 는 파일/셸/에이전트 도구를 계속 차단하고, `research` 프로파일만 웹 도구를 연다.

## ③ 구현 상태

- ✅ 사양 확정(2026-08-13). 갈림길 3개 + diff 검토 요구 반영.
- ⬜ `backend/agent.py` (신규) — 절별 세션·프로파일 레지스트리
- ⬜ `backend/claude_service.py` — `_cli_stream()` / `_sdk_stream()` / `chat_write_stream()`
- ⬜ `backend/store.py` — `read_agent/write_agent/reset_agent`
- ⬜ `backend/main.py` — `/chat/stream`(SSE), `/agent`, `/agent/reset`
- ⬜ `frontend/diff.js` (신규) — 줄→단어 2단 diff, 항목 묶기, 병합
- ⬜ `frontend/app.js` — SSE 리더, 실시간 타이핑, 중단/복원, 검토 모드 전환
- ⬜ `frontend/index.html`·`styles.css` — 상태줄, 중단 버튼, 에이전트 초기화, diff 뷰·툴바·항목 버튼
- ⬜ 실증: 절 2개 세션 유지 / 웹 조사 절 스트리밍 / 중단 후 원본 복원 /
  긴 본문(수천 단어) diff 성능 / 항목별·일괄 수락·거절 후 병합 정확성

## ④ 미결/후속

- `--resume` 상태에서 `--system-prompt` 재지정이 먹는지 미확인 → 구현 중 실증. 안 먹으면
  변경분만 `--append-system-prompt` 로 주입하거나 새 세션으로 재시작한다(2.3 무효화 규칙).
- CLI 세션 파일이 `~/.claude/projects/<tempdir>` 에 **절 수 × 프로젝트 수**만큼 쌓인다 — 정리 정책 미정.
- 동일 절에 대한 **동시 스트리밍 2건**(창 2개) 처리 미정 — 우선은 선점 없이 그대로 둔다.
- 절별 모델·effort 차등(`--model`, `--effort`)은 `agent.json` 에 자리만 만들고 기본값 공통으로 시작.
- 검토 모드에서 **부분 직접 편집**(diff 뷰 안에서 타이핑)은 범위 밖 — 적용 후 textarea 에서 고친다.
- diff 항목 묶기 임계값(유지 토큰 3개)은 사용해 보고 조정한다.
- `--agents <json>` 로 CLI 네이티브 서브에이전트를 쓰는 방식은 이번 범위 밖.
- 표 자동채움(`tables.py`)·문서 표(`doc_fill.py`) 경로는 이번 스트리밍·diff 대상이 아니다.
