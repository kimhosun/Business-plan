---
name: fill-hwp-template
description: 세분화된 hwpmd Markdown(연구개발계획서_세부/_장별)에서 JSON 입력 템플릿을 추출하고, 사람이 채운 값을 본문 문단과 표 셀에 자동으로 기록한다. 헤딩은 `{{title}}`로 템플릿화하고, ※ 작성요령은 guideline으로, 표는 셀 grid로 JSON에 담는다. 앵커·data-hwp-*·표 구조를 보존해 장→마스터→HWP로 재병합된다. 사용 예 "입력 템플릿 뽑아줘", "JSON 채우면 md에 자동 작성", "표 셀에 값 채우기". subsplit-hwp-sections(또는 split-hwp-chapters)로 먼저 분리돼 있어야 한다.
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
---

# 입력 템플릿 기반 자동 작성 (본문·표)

세분화된 hwpmd Markdown(SOURCE 구간이 있는 `.md`)에서 **JSON 입력 템플릿**을 뽑고, 사람이 그 JSON의 `value`를 채우면 해당 **본문 문단과 표 셀**에 자동으로 써 넣는다. 앵커·`data-hwp-*`·표 구조는 보존되므로 상위 파이프라인으로 장→마스터→(원본 HWP 오버레이)까지 이어진다.

전제: `split-hwp-chapters` → `subsplit-hwp-sections`로 이미 분리돼 있어야 한다. 좌표계(마커·앵커)는 [../split-hwp-chapters/references/pipeline.md](../split-hwp-chapters/references/pipeline.md) 참고.

## 두 서브커맨드

```bash
TOOL=.claude/skills/fill-hwp-template/scripts/input_template.py

# 1) 추출: 각 .md 옆에 <파일>.tmpl.json 생성
python $TOOL extract --dir 연구개발계획서_세부       # 폴더 전체(하위 .md)
python $TOOL extract --file 어느_절.md               # 파일 하나

# 2) 적용: 채운 <파일>.tmpl.json 의 value를 .md 에 기록
python $TOOL apply --dir 연구개발계획서_세부
python $TOOL apply --file 어느_절.md [--force]
```

`--dir`는 하위 모든 `.md`를 처리하되 `README.md`, `_`로 시작하는 파일, `_tables/` 복사본, `.tmpl.json`은 건너뛴다. `extract`/`apply`는 `연구개발계획서_장별`(장 단위)에도 그대로 쓸 수 있다.

## JSON 입력 템플릿 구조

각 `.md`에 대해 `<파일>.tmpl.json`이 생성된다.

```jsonc
{
  "input_template": "hwpmd-fill/1.0",
  "file": "…/01_(1)_국내_기술의_수준_및_시장_동향.md",
  "source_fragment_sha256": "…",          // 드리프트 감지용(적용 시 대조)
  "section": {"label": "(1)", "title": "…"},
  "guidelines": ["신청 기관의 기술수준 등을 포함", …],   // ※ 작성요령 모음
  "fields": [
    {"id":"S2.P0397","role":"heading","level":5,
     "label":"(1)","template":"(1) {{title}}",
     "current_title":"국내 기술의 수준 및 시장 동향",
     "guideline":"신청 기관의 기술수준 등을 포함","value":""},
    {"id":"S2.P0399","role":"label","current":"[국내 기술 동향 및 수준]","guideline":"","value":""},
    {"id":"S2.P0401","role":"bullet","marker":"  o ","value":""},
    {"id":"S2.P0405","role":"note","guideline":"직접 관련된 시장 규모"}   // 읽기전용
  ],
  "tables": [
    {"id":"S2.P0445.T00","rows":10,"cols":5,"guideline":"본 과제를 통한 생산 계획",
     "cells":[
       {"cell":"R00C00","r":0,"c":0,"kind":"label","current":"구분","p00":"…R00C00.P00","value":""},
       {"cell":"R01C02","r":1,"c":2,"kind":"fill","current":"","p00":"…R01C02.P00","value":""}
     ]}
  ],
  "_help": "...", "_skipped_blocks": 0        // 내부 참고용 키(무시해도 됨)
}
```

> `_`로 시작하는 최상위 키(`_help` 안내문, `_skipped_blocks` 건너뛴 블록 수)는 내부 참고용이며 채우지 않는다.

### 필드 역할(role)

| role | 뜻 | value로 하는 일 |
|---|---|---|
| `heading` | 헤딩. `template`이 `라벨 {{title}}` 꼴로 **템플릿화** | value에 **제목만** 넣으면 `라벨 제목`으로 교체 |
| `bullet` | 빈 불릿 스텁(`o`,`-`,`·`,`□`) | 마커·들여쓰기를 **보존**하고 value를 뒤에 추가 |
| `content` | 일반 내용 문단 | value가 문단 텍스트를 교체 |
| `label` | `[…]` 라벨 등 | value가 있으면 교체(선택). `readonly:true`(탭·고정폭 구조)는 미편집 |
| `note` | ※ 작성요령(순수 노트) | **읽기전용** — 채우지 않는다 |

### 표 셀(kind)

| kind | 뜻 | 채우기 |
|---|---|---|
| `fill` | 빈 셀(`<br>`) 또는 플레이스홀더(`(   년)`) | `value`가 `{셀}.R..C..P00`에 기록 |
| `label` | 고정 텍스트 헤더/라벨 셀 | value가 있으면 교체(선택) |
| `skip` | 이미지·직인·수식(`FieldFormula`) 셀 | 기록 안 함(자동 계산·객체 보호) |
| `nested` | 셀 안에 표가 중첩 | 해당 중첩 표는 상위 표로 별도 노출 |

병합 셀(rowspan/colspan)은 좌상단 앵커 셀만 존재하며 그 셀 하나가 병합 영역을 대표한다.

## 채우기 규칙

1. 채우고 싶은 항목의 `value`에만 내용을 넣는다. **빈 문자열은 원문 유지**(건드리지 않음).
2. `role:"note"`와 `readonly:true`, `kind:"skip"`/`"nested"`는 채우지 않는다(작성요령·구조·객체 보호).
3. 헤딩은 제목만 넣는다(라벨은 `template`이 유지). 예: `value:"국내외 기술·시장 현황"` → `(1) 국내외 기술·시장 현황`.
4. 불릿은 한 슬롯당 한 줄 개념이다. 여러 줄이 필요하면 원본에 여러 불릿이 있으므로 각 슬롯을 채운다.
5. 표 셀 값은 각 셀 `P00` 문단에 단일 텍스트로 들어간다(글꼴 run은 `data-hwp-cs`를 재사용, 기본 29).

## 적용·재병합

```bash
# 값 채운 뒤
python $TOOL apply --dir 연구개발계획서_세부

# 세부 → 장 파일 반영(편집이므로 --allow-edits 필수)
python .claude/skills/subsplit-hwp-sections/scripts/subsplit_hwpmd.py merge \
  --output 연구개발계획서_세부 --write-back 연구개발계획서_장별 --allow-edits

# 장 → 마스터 반영(앵커 검증, 본문은 편집분만큼 달라짐)
python tools/merge_hwpmd_chapters.py --master 연구개발계획서.md \
  --parts-dir 연구개발계획서_장별 --out 연구개발계획서_병합.md
```

`apply`는 각 문단/셀의 **앵커·태그·속성을 그대로 두고 내부 텍스트만** 바꾸므로 최상위 앵커 수가 변하지 않는다(검증 완료: 편집 후에도 809개 유지, 마스터 재병합 시 "anchors were validated"). 최종적으로 편집된 재병합 MD를 한글에서 HWP 오버레이로 열어 저장한다.

`apply` 출력의 `drift`가 표시되면 템플릿 추출 이후 `.md`가 바뀐 것이다. 의도한 것이면 `--force`로 적용하되, 앵커가 이동했을 수 있으니 `extract`를 다시 하는 편이 안전하다.

## 한계·주의

- **표 셀은 P00(첫 문단)에 단일 텍스트**로 기록한다. 한 셀에 여러 문단(P01,P02…)이 필요한 복잡한 셀은 자동 대상이 아니며, 필요 시 원문 구간을 직접 편집한다.
- `content`/`label`을 채우면 그 문단의 서식 run이 단일 span(원 cs 재사용)으로 단순화된다. 불릿은 마커 span을 보존한다. 표·이미지·수식이 든 문단은 건드리지 않는다.
- 헤딩 value를 넣으면 그 헤딩의 인라인 ※ 안내는 제거된다(제출본 기준). 남기려면 value를 비워 둔다.
- `guideline`/`note`는 **작성요령**이지 채울 값이 아니다. 최종 제출 시 원본 서식의 파란 안내문(※)은 한글에서 함께 정리한다.
- 이 스킬은 **텍스트 채움**만 한다. 표의 행 추가·삭제, 이미지 삽입은 범위 밖이다.
- 셀의 컨트롤(이미지·직인·수식) 판정은 **P00 기준**이다. 컨트롤이 P01 이후에만 있는 드문 셀은 `fill`로 보일 수 있으니, `guideline`·`current`를 보고 자동 계산 셀에는 값을 넣지 않는다.
- 중첩 표(셀 안의 표)는 상위 셀이 `kind:"nested"`로 표시되며 자동 채움 대상이 아니다. 필요하면 원문 구간을 직접 편집한다.

## Windows·UTF-8

- `python -X utf8 ...`로 실행한다. 모든 파일은 `newline=""`로 기록되어 `\r\n`/`\n`이 보존되므로 에디터 자동 개행 변환을 끈다.
- JSON은 UTF-8로 저장한다(BOM 없이). `value`에 큰따옴표·역슬래시가 있으면 JSON 규칙대로 이스케이프한다.
