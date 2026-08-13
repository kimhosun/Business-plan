# webapp 스킬 보관함 — 대화창 질문에 관련 스킬 자동 적용

> 대상: `webapp/` 연구개발계획서 작성 웹서비스의 상단바 [🧰 스킬] 과 ③ 입력 탭 "AI와 대화하며 작성" 패널.
> 관련 원본: 아키텍처 계약 [webapp/ARCHITECTURE.md](../webapp/ARCHITECTURE.md),
> 절별 에이전트 [spec_webapp-절별에이전트.md](spec_webapp-절별에이전트.md),
> 작성 프롬프트 [spec_webapp-작성프롬프트.md](spec_webapp-작성프롬프트.md).

## ① 질의·요청 히스토리

- **2026-08-13** — "현재 웹 대화창에서 사용자가 질문했을때 관련된 스킬을 사용할 수 있도록
  스킬을 저장할 수 있는 기능을 추가해줘."
  → 웹 UI 에서 **스킬(작성 지침 묶음)을 저장**하고, 절 작성 채팅에서 **질문과 관련된 스킬이 자동으로**
  시스템 프롬프트에 붙도록 구현. 아래 ②가 확정 사양.

## ② 확정 사양

### 2.1 목표

자주 쓰는 작성 규칙·노하우를 **스킬**로 웹에 저장해 두면, 절 작성 대화창에서 사용자의 질문 내용과
**관련된 스킬만 골라** 프롬프트 꼬리에 붙어 답변·본문 초안에 반영된다. 어떤 스킬이 붙었는지는
채팅에 배지로 남아 사후 확인이 된다.

### 2.2 저장 형식 — Claude Code SKILL.md 와 동일

프로젝트 **공용**(모든 프로젝트가 같은 보관함을 본다). `webapp/data/skills/<slug>.md`:

```markdown
---
name: 시장 동향 정량 작성 규칙
description: 시장 규모·성장률(CAGR)·경쟁사 비교를 쓸 때 적용    # 자동 선택의 1차 근거
triggers: ["시장", "규모", "CAGR", "1-2"]                      # 선택(강한 가중치)
scope: auto | always | off                                     # 자동 / 항상 / 사용 안 함
source: user | repo:<.claude/skills 폴더명>
updated: 2026-08-13T06:31:27+00:00
---

- 시장 규모는 국내/세계를 분리해 제시하고 (출처, 연도)를 붙인다.
- 성장률은 CAGR(%)로 쓰고 기준 구간을 명시한다.
```

frontmatter 형식이 `.claude/skills/<name>/SKILL.md` 와 같으므로 **저장소 스킬을 그대로 가져오기**할 수 있다
(`source: repo:<key>` 로 표시, 다시 가져오면 본문만 갱신되고 사용자가 바꾼 scope 는 유지).

### 2.3 선택(매칭) 규칙 — LLM 호출 없는 결정론적 키워드 매칭

추가 지연 0 을 위해 별도 모델 호출 없이 점수로 고른다(`backend/skills.py :: match`).

| 항목 | 값 |
|---|---|
| 토큰화 | `[가-힣]{2,}` / `[a-zA-Z]{2,}` / `\d+(-\d+)?`, 불용어 제외. 어절(조사 포함)은 **접두 일치 0.6** 허용 |
| 필드 가중 | triggers 3.0 · name 2.5 · description 1.5 · 본문(앞 4000자) 0.5 |
| 맥락 가중 | 질문 토큰 ×1.0, 절 라벨·제목 등 맥락 토큰 ×0.4 |
| 채택 | 점수 **2.0 이상** 상위 **3개**까지, 본문은 스킬당 6000자·합계 12000자 상한 |
| scope | `always` = 점수 무관 항상 포함 · `off` = 항상 제외 · `auto` = 위 규칙 |

### 2.4 프롬프트 주입 지점

`claude_service._chat_context_block()` 이 [문체] 다음, [현재 작성본] 앞에 `[적용 스킬]` 블록을 넣는다.
문구는 *"[작성요령]·[양식 템플릿]과 충돌하지 않는 범위에서 그대로 따른다"* — 즉 **문서 서식·작성요령이 상위**,
스킬은 그 안에서의 작성 지침이다. `claude_service` 는 순수 모듈이라 스킬 **선택은 라우트(main.py)** 가 하고
모듈은 렌더만 한다.

### 2.5 REST (ARCHITECTURE 계약에 추가)

| 메서드 | 경로 | 동작 |
|---|---|---|
| GET | `/api/skills` | 보관함 목록 + 저장소 가져오기 후보 → `{skills, repo}` |
| GET | `/api/skills/{slug}` | 스킬 하나(본문 포함) |
| POST | `/api/skills` | `{slug?,name,description,body,triggers,scope}` 저장(신규/수정) |
| DELETE | `/api/skills/{slug}` | 삭제 |
| POST | `/api/skills/import` | `{keys:[...]}` — `.claude/skills/<key>/SKILL.md` 복사 |
| POST | `/api/skills/match` | `{query,context}` — 붙을 스킬 미리보기 |

채팅은 `POST .../chat` 이 `{message, apply, skills?, use_skills}` 를 받고 `{reply,draft,input,chat,skills}` 를
돌려준다. `skills`(slug 배열)를 주면 자동 선택 대신 그것만, `use_skills:false` 면 스킬 없이 간다.
적용된 스킬 요약은 `chat.json` 의 그 턴에 `skills` 키로 함께 남는다.

### 2.6 UI

- 상단바 **[🧰 스킬]** → 보관함 모달.
  - 좌: 저장된 스킬 목록(적용범위 배지) · **저장소 스킬 가져오기**(.claude/skills) ·
    **질문 미리보기**("이 질문이면 어떤 스킬이 붙나" + 점수).
  - 우: 이름 / 설명(자동 선택 기준) / 트리거 키워드 / 적용 범위(자동·항상·사용 안 함) / 본문 편집.
- 채팅 헤더 **[🧰 스킬 자동적용]** 토글(끄면 그 요청은 스킬 없이).
- 답변 아래 **적용된 스킬 배지**, 채팅 상단에 "🧰 적용된 스킬: …" 안내 한 줄.

## ③ 구현 상태

| 항목 | 상태 | 위치 |
|---|---|---|
| 스킬 저장/조회/삭제·저장소 가져오기·매칭 | 완료 | `webapp/backend/skills.py` (`python -m backend.skills` 스모크 PASS) |
| REST 6종 + 채팅 라우트 연동 | 완료 | `webapp/backend/main.py`, `webapp/backend/schemas.py` |
| 프롬프트 `[적용 스킬]` 블록 | 완료 | `webapp/backend/claude_service.py :: _skills_block` |
| 턴별 적용 스킬 이력 저장 | 완료 | `webapp/backend/store.py :: append_chat(..., skills=)` |
| 보관함 모달 · 채팅 토글/배지 | 완료 | `webapp/frontend/{index.html,app.js,styles.css}` |
| 실제 채팅 경로 검증 | 완료 | scope=always 스킬이 응답 `skills` 와 `chat.json` 턴에 기록됨(2026-08-13) |

## ④ 미결·후속

- **자동 선택 정확도**: 키워드 매칭이라 설명·트리거를 부실하게 적으면 안 붙는다. 모달의 "질문 미리보기"로
  점수를 확인해 보완하는 운용. 필요해지면 LLM 선택기(1회 저비용 호출)로 교체 가능 — 매칭 로직은
  `skills.match()` 한 곳에 모여 있다.
- **적용 범위**: 현재 절 작성 채팅(`/chat`)에만 붙는다. RFP 자동작성(`draft_from_rfp`)·변환(`convert_input`)
  에는 아직 붙이지 않았다 — 필요하면 같은 `match()` 를 그 경로에도 연결.
- **절별 기본 스킬 고정**(예 1-2 절엔 항상 이 스킬)은 미구현. 현재는 전역 `always` 또는 트리거 키워드에
  절 번호("1-2")를 넣어 근사한다.
- 스킬은 프로젝트 공용이라 프로젝트별로 다른 규칙을 쓰려면 scope 를 바꿔 가며 써야 한다(프로젝트 스코프 미구현).
