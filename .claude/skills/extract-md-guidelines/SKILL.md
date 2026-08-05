---
name: extract-md-guidelines
description: rnd-proposal-writer/references 의 각 .md 에서 "적용해야 할 규칙·지침·가이드라인"을 (1) 파일별 지침 .md 와 (2) 구조화된 지침 JSON 으로 추출하고, 원본이 바뀌면 변경분만 자동으로 최신 동기화(sync)한다. 공통원칙 §N 을 각 지침 문서에 인라인 해소하고, 파일별·마스터 두 층위로 JSON 에 지침을 삽입한다. 사람이 덧붙인 "심화 지침" 영역은 sync 가 보존한다. 트리거 예 "references 지침 추출해줘", "각 절 md 규칙을 지침 md 로 뽑아줘", "지침을 JSON 에 넣어줘", "지침 최신으로 업데이트/동기화".
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
---

# references md → 지침 추출·구조화·자동 동기화

`rnd-proposal-writer/references/` 의 각 절 md(`절_*.md`, `00_공통_작성원칙.md`)는 그 절을 쓸 때 **적용해야 할 규칙**을 담고 있다. 이 스킬은 그 규칙을 기계가 읽기 좋게 **정규화**해 두 산출물로 뽑고, 원본이 바뀌면 **변경분만** 다시 만들어 항상 최신본을 유지한다.

산출물(기본 위치 `references/_지침/`, 이름이 `_`로 시작해 다른 도구의 스캔에서 자동 제외):

| 산출물 | 내용 |
|--------|------|
| `_지침/<원본>.지침.md` | 파일별 지침 문서. **공통원칙 §N 을 인라인 해소**(각 §의 제목+요지 삽입) + 골격/변형/문체/정합/금지 지침 + 체크리스트 + 그 파일의 구조화 지침 JSON 블록 |
| `_지침/지침.json` | **마스터 JSON**. 모든 원본 파일의 지침을 `files.<name>.directives[]` 로 삽입한 구조화 산출물 |
| `_지침/.manifest.json` | 원본 SHA-256 매니페스트. 변경 감지·자동 동기화의 기준 |

## 실행

```bash
ENGINE=".claude/skills/extract-md-guidelines/scripts/guidelines_engine.py"

# 자동 동기화(핵심): 새로 생기거나 바뀐 원본만 재생성 + 마스터 JSON 재조립
python -X utf8 $ENGINE sync

# 미리보기: 무엇이 재생성 대상인지만 보고, 쓰지 않음
python -X utf8 $ENGINE status

# 전체 강제 재생성(AUTO 구간만; 심화 지침 영역은 그대로 보존)
python -X utf8 $ENGINE extract        # = sync --force

# 마스터 JSON 만 다시 조립
python -X utf8 $ENGINE build-json

# 다른 references 폴더를 대상으로
python -X utf8 $ENGINE sync --dir "경로/references"
```

`--dir` 를 생략하면 형제 스킬 `rnd-proposal-writer/references` 를 기본 대상으로 삼는다. 스캔은 폴더 최상위 `*.md` 만 대상이며 `README.md` 와 `_지침/` 산출물은 제외한다.

## 최신 버전 자동 유지 방식

- **결정론적 diff**: `sync` 는 각 원본의 SHA-256 을 매니페스트와 비교해 **추가·변경된 파일만** 재생성한다. 몇 번을 돌려도 결과가 같다(idempotent).
- **공통원칙 파급**: `00_공통_작성원칙.md` 가 바뀌면 §N 요지 인라인이 달라지므로 **전 파일을 재생성**한다.
- **원본 삭제 반영**: 원본이 없어지면 대응 지침 md 를 지우고 매니페스트에서 뺀다.
- **심화 지침 보존**: 각 지침 md 의 `<!--@guideline-auto-end-->` **뒤**(“## 심화 지침” 영역)는 사람이/에이전트가 편집해도 sync 가 **그대로 보존**한다. AUTO 구간만 재생성된다.

### (선택) 편집 즉시 자동 동기화 훅

원본을 고칠 때마다 손으로 `sync` 를 부르기 싫으면, `update-config` 스킬로 `.claude/settings.json` 에 PostToolUse 훅을 걸어 references 하위 md 편집 후 자동 실행할 수 있다(개념):

```json
{ "hooks": { "PostToolUse": [ {
  "matcher": "Edit|Write",
  "hooks": [ { "type": "command",
    "command": "python -X utf8 .claude/skills/extract-md-guidelines/scripts/guidelines_engine.py sync" } ] } ] } }
```

훅 없이도 절 작성 전에 `sync` 한 번이면 최신 지침이 보장된다.

## 지침 md 구조(파일별)

```markdown
<!--@guideline-auto-begin-->        ← 여기부터
# [지침] <원본 제목>
> 원본 · 대응 스킬 · 적용 절
**역할**: …
## 반드시 적용할 공통원칙        ← §N 을 제목+요지로 인라인 해소
## 골격 지침 / 문서별 변형 지침 / 문체·표기 지침 / 정합 지침 / …
## 체크리스트                    ← 원문 [ ] 항목 그대로
## 구조화 지침(JSON)             ← 이 파일의 directives 를 JSON 으로 자체 포함
<!--@guideline-auto-end-->          ← 여기까지가 sync 재생성 대상

## 심화 지침 (수동·에이전트 편집 영역)   ← 이 아래는 sync 가 보존
```

## 마스터 JSON 스키마(`지침.json`)

```jsonc
{
  "schema": "md-guidelines/1.0",
  "common_principles": { "file": "00_공통_작성원칙.md",
    "sections": [ { "id": "§1", "title": "문체·종결형", "summary": "…" }, … ] },
  "files": {
    "절_1-1_….md": {
      "title": "…", "skill": "rnd-write-1-1-overview", "applies_to": "### 1-1 …", "role": "…",
      "common_refs": ["§1","§2","§3","§5","§8"],
      "directives": [ { "type": "skeleton|variant|style|consistency|budget-code|applicability|note",
                        "section": "표준 골격", "text": "…" }, … ],
      "checklist": [ "…", … ],
      "source_sha256": "…"
    }, …
  }
}
```

- `directives[].type` 은 원문 섹션 헤딩으로 분류한다: 골격→`skeleton`, 변형/존재형태→`variant`, 문체→`style`, 정합→`consistency`, 비목·코드·관계식→`budget-code`, 적용 판단→`applicability`, 그 외→`note`. 예문·원본 참조 섹션은 지침에서 제외한다.
- `common_refs` 는 원문의 `[공통원칙 §N]` 인용을 모은 것으로, 파일별 지침 md 에서 §의 요지로 풀어 준다.

## 불변식·주의

- **무손실 아님(요약형)**: 예문·원본 참조 경로는 의도적으로 지침에서 제외한다(작성 규칙만 추림). 필요하면 원본 `references/절_*.md` 를 본다.
- **하위 불릿 흡수**: 원문의 중첩 불릿은 상위 지침 텍스트에 ` · ` 로 평탄화해 한 directive 로 합친다.
- **UTF-8/Windows**: 항상 `python -X utf8` 로 실행. 산출물은 `\n` 개행으로 기록.
- 심화 지침 영역을 채울 때는 반드시 `<!--@guideline-auto-end-->` **아래에서만** 편집한다(위쪽은 sync 가 덮어씀).

## 관계

- 입력 원본은 `rnd-proposal-writer/references/` (각 `rnd-write-*` 세부 절 스킬이 근거로 삼는 파일들).
- 산출된 `지침.json` 은 절 작성 시 “적용해야 할 규칙” 체크리스트나 자동 점검의 입력으로 쓸 수 있다.
