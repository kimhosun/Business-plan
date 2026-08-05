---
name: embed-json-structure
description: 분류된 hwpmd Markdown 원본 파일 안에 JSON 입력구조를 직접 삽입한다. 각 .md 의 SOURCE 구간(`<!--@hwp-source-begin/end-->`) 밖, 파일 끝에 `## 입력구조(JSON)` 섹션을 만들고 ```json 블록을 넣어 문서를 자체 완결형으로 만든다. 삽입 위치가 SOURCE 밖이라 장→마스터 재병합·HWP 복원에 영향이 없고, 삽입은 idempotent하며 strip으로 원본과 바이트 동일하게 되돌린다. 사용 예 "원본 md에 JSON 구조 삽입", "구조를 파일 안에 박아줘", "박힌 JSON 다시 빼줘". fill-hwp-template의 입력구조를 그대로 사용한다.
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
---

# 원본 md에 JSON 입력구조 삽입

`fill-hwp-template`이 만드는 JSON 입력구조를 **사이드카 파일 대신 원본 md 안**에 넣는다. 각 파일의 `<!--@hwp-source-end-->` 뒤에 `## 입력구조(JSON)` 섹션을 삽입해 문서 하나가 원문·구조를 모두 담게 한다.

**핵심 안전성**: 삽입 위치가 SOURCE 구간 **밖**이라, 장→마스터 재병합(`merge_hwpmd_chapters.py`)과 원본 HWP 복원은 전혀 영향을 받지 않는다(merge는 SOURCE 구간만 읽는다). 검증: 모든 장에 삽입해도 마스터 본문이 바이트 단위로 동일했고, subsplit `merge`도 `content_identical`을 유지했다.

전제: `split-hwp-chapters` 또는 `subsplit-hwp-sections`로 분리돼 있어야 한다. 좌표계는 [../split-hwp-chapters/references/pipeline.md](../split-hwp-chapters/references/pipeline.md), 입력구조 스키마는 [../fill-hwp-template/SKILL.md](../fill-hwp-template/SKILL.md) 참고.

## 삽입 형태

파일 끝에 아래 블록이 들어간다. `<!--@tmpl-json-begin-->`~`<!--@tmpl-json-end-->` 주석 경계로 감싸 idempotent하게 교체·제거된다.

```markdown
…(원문·규정 참조 등 기존 내용)…

<!--@tmpl-json-begin-->
## 입력구조(JSON)

```json
{ "input_template": "hwpmd-fill/1.0", "fields": [...], "tables": [...] }
```
<!--@tmpl-json-end-->
```

## 서브커맨드

```bash
TOOL=.claude/skills/embed-json-structure/scripts/embed_structure.py

# 삽입/갱신: 각 md에 입력구조 섹션을 넣는다(있으면 교체)
python $TOOL embed --dir 연구개발계획서_세부      # 폴더 전체
python $TOOL embed --file 어느_절.md
python $TOOL embed --dir 연구개발계획서_세부 --re-extract   # 사이드카 무시, SOURCE에서 새로 추출

# 꺼내기: 박힌 JSON을 stdout 출력, 또는 사이드카로 기록
python $TOOL read --file 어느_절.md                # stdout
python $TOOL read --dir 연구개발계획서_세부 --to-sidecar   # <md>.tmpl.json 생성

# 제거: 삽입한 섹션을 지워 원본으로 복원
python $TOOL strip --dir 연구개발계획서_세부
```

`--dir`는 하위 모든 `.md`를 처리하되 `README.md`, `_`로 시작하는 파일, `_tables/`, 이름에 `.tmpl`이 든 `.md`는 건너뛴다(`.tmpl.json` 사이드카는 `.md`가 아니라 자동 제외). `연구개발계획서_장별`(장 단위)에도 그대로 쓸 수 있다.

### 구조의 출처(embed)

`embed`가 넣을 JSON은 다음 순서로 얻는다.

1. 같은 이름의 `<md>.tmpl.json` 사이드카가 있으면 **그 내용을 그대로** 넣는다(사람이 채운 값 포함).
2. 없으면 `fill-hwp-template`의 `input_template.py extract` 로직으로 **즉석 생성**해 넣는다.
3. `--re-extract`를 주면 사이드카를 무시하고 **항상 SOURCE에서 새로 추출**한다.

따라서 값을 채운 뒤 그 상태로 문서에 박고 싶으면, 사이드카를 채운 다음 `embed`한다. 반대로 `apply`로 SOURCE 본문을 편집한 뒤 구조를 다시 박을 때는 사이드카(옛 구조)가 우선되므로, 편집분을 반영하려면 `--re-extract`로 새로 추출한다.

## 워크플로우

**A. 구조를 문서에 박아 두기(자체 완결형 배포)**
```bash
python $TOOL embed --dir 연구개발계획서_세부      # 각 md에 구조 삽입
# 이제 각 md 하나만 열어도 원문 + 입력구조를 함께 본다
```

**B. 문서 안 JSON을 채워서 본문에 반영**
```bash
# (md 안 ## 입력구조(JSON) 블록의 value를 편집한 뒤)
python $TOOL read --dir 연구개발계획서_세부 --to-sidecar     # 박힌 JSON → 사이드카
python .claude/skills/fill-hwp-template/scripts/input_template.py apply --dir 연구개발계획서_세부
python .claude/skills/subsplit-hwp-sections/scripts/subsplit_hwpmd.py merge \
  --output 연구개발계획서_세부 --write-back 연구개발계획서_장별 --allow-edits
python tools/merge_hwpmd_chapters.py --master 연구개발계획서.md \
  --parts-dir 연구개발계획서_장별 --out 연구개발계획서_병합.md
```

**C. 배포용으로만 쓰고 최종 산출물에서 구조 제거**
```bash
python $TOOL strip --dir 연구개발계획서_세부      # 원본과 바이트 동일하게 복원
```

## 불변식·보장

- **재병합 무영향**: JSON 섹션은 SOURCE 구간 밖이라 장·마스터 병합·HWP 복원이 그대로 동작한다(전 장 삽입 후 마스터 본문 SHA 동일 확인).
- **idempotent**: `embed`를 여러 번 해도 블록은 항상 1개(기존 블록을 교체).
- **완전 가역**: `strip`은 원본과 **바이트 단위로 동일**하게 되돌린다(선두 구분 개행 1개까지 정확히 복원).
- **삽입 안전 검사**: 구조 JSON에 SOURCE 마커나 코드펜스(```)가 들어 있으면 그 파일은 삽입하지 않고 `reason`과 함께 건너뛴다(배치는 계속 진행). 삽입 후 SOURCE 마커가 정확히 1쌍인지 재확인한다. 사이드카/문서 안 JSON이 깨져 있어도 해당 파일만 오류로 보고하고 나머지는 처리한다.

## 주의

- `read`로 사이드카를 만들면 `fill-hwp-template apply`가 그것을 사용한다. 문서 안 JSON을 편집했으면 **반드시 `read --to-sidecar`로 먼저 내보낸 뒤** apply한다(apply는 문서 안 블록이 아니라 사이드카를 읽는다).
- 삽입된 ```json 블록 안의 JSON은 반드시 유효한 JSON이어야 한다. 값에 큰따옴표·역슬래시는 JSON 규칙대로 이스케이프한다.
- `README.md`는 편집 규칙 설명에 SOURCE 마커 문자열을 포함하므로 대상에서 제외된다(정상).

## Windows·UTF-8

- `python -X utf8 ...`로 실행한다. 모든 파일은 `newline=""`로 기록되어 개행 바이트가 보존된다(에디터 자동 개행 변환 끄기).
