---
name: hwpx-yaml-roundtrip
description: 정부 R&D 연구개발계획서 등 한글 문서를 hwpx로 변환한 뒤, 세부 항목(문단·표)을 편집 가능한 YAML로 추출하고, 사람이 채운 내용을 다시 원본 hwpx에 오버레이해 서식 보존 상태로 원복(복원)한다. 원복 시 사용자가 제공한 번호/마커 템플릿(1·1.1·1.1.1 또는 □·○·-)과 표 양식을 적용한다. hwpx는 ZIP+XML이라 편집분→수정 hwpx 자동생성이 실제로 된다(.hwp에서 막혔던 단계). 트리거 예 "hwpx로 바꿔 yaml로 뽑아줘", "yaml 채워서 hwpx로 원복", "번호 1.1.1 템플릿 적용해 복원", "표 양식대로 마커 붙여줘".
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
---

# hwpx ↔ YAML 왕복 + 템플릿 적용

한글 문서(.hwp/.hwpx)를 **hwpx로 변환 → 세부 항목별 YAML 추출 → 내용 작성 → 원본 hwpx에
오버레이 원복**하는 실행구조. 원복 시 사용자가 준 **번호/마커 템플릿**과 **표 양식**을 적용한다.

핵심 원칙: **hwpx = 서식·구조의 원천, YAML = 편집 가능한 내용 오버레이.** hwpx를 새로
만들지 않고 원본 hwpx를 열어 YAML의 `marker`+`text`를 같은 좌표(path)의 문단에 다시
얹으므로 글꼴·문단·표 테두리·병합 등 서식이 **100% 보존**된다. .hwp(바이너리)에서는
불가능하던 "편집분 → 수정 파일 자동생성"이 hwpx(ZIP+XML)에서는 실제로 된다.

전제(검증됨): `python-hwpx`, `pyhwpx`, `PyYAML` 설치 + hwp→hwpx 변환에는 한컴오피스 필요.
공유 계약은 [references/schema.md](references/schema.md), 공용 함수는
[scripts/hwpx_common.py](scripts/hwpx_common.py)에 고정돼 있다.

## 실행구조 (4 커맨드)

```
SC=.claude/skills/hwpx-yaml-roundtrip/scripts

# [0] hwp → hwpx  (이미 hwpx면 생략/복사)         ※ 한컴 COM
python $SC/hwp2hwpx.py convert --in 연구개발계획서.hwp --out 연구개발계획서.hwpx

# [1] hwpx → 세부 항목별 YAML  (섹션당 1파일 + _manifest.yaml)
python $SC/hwpx2yaml.py extract --in 연구개발계획서.hwpx --out-dir yaml

# [2] 내용 작성: yaml/section_*.yaml 의 각 노드 text(필요시 marker)를 채운다
#     (rnd-write-* 스킬로 절별 내용을 생성해 넣어도 된다)

# [3] (선택) 번호/마커 템플릿 적용: 각 노드 marker 재계산
python $SC/template.py apply --yaml-dir yaml --template template.yaml

# [4] 원복: 원본 hwpx에 오버레이 → 최종 hwpx  (--template로 [3]을 겸할 수 있음)
python $SC/yaml2hwpx.py restore --hwpx 연구개발계획서.hwpx --yaml-dir yaml \
       --out 연구개발계획서_최종.hwpx --template template.yaml
```

`--template`을 `restore`에 주면 별도 `apply` 없이 쓰기 시점에 템플릿이 적용된다.

## YAML 스키마 (hwpx-yaml/1.0)

섹션당 `section_00.yaml … `. 각 노드는 문서 순서(DFS)를 유지한다.

```yaml
schema: hwpx-yaml/1.0
source: 연구개발계획서.hwpx
source_sha256: "…"          # 원복 시 원본 대조(드리프트 경고)
section_index: 0
nodes:
  - path: s0/p0             # 위치 경로(안정 식별자) — 편집 금지
    kind: para              # para | cell_para | table
    level: 1                # 개요 깊이(템플릿용)
    marker: "□"             # 선두 마커 — 편집/템플릿 대상
    text: "개발 대상 기술의 개요"   # 본문 — 편집 대상
    style: 172              # 서식 참조 — 편집 금지
    para_pr: 62
    char_pr: 31
  - path: s0/p1/t0
    kind: table
    rows: 26
    cols: 5
  - path: s0/p1/t0/r0/c0/p0
    kind: cell_para
    row: 0
    col: 0
    span: [1, 1]
    marker: ""
    text: "구분"
```

**편집 가능한 필드는 `marker`, `text` 뿐.** `path/kind/style/para_pr/char_pr/row/col/span`
등은 좌표·서식 보존용이라 손대지 않는다(바꾸면 원복 좌표가 어긋난다).

## 템플릿 (hwpx-yaml-template/1.0)

레벨별 **번호/마커 규칙 + 표 양식**. 예시는 [template.example.yaml](template.example.yaml).

```yaml
schema: hwpx-yaml-template/1.0
numbering:                 # 번호식(있으면 우선). {n}현재 {p}상위누적 {P}전체
  level1: "{n}."           # 1.  2.
  level2: "{p}.{n}"        # 1.1
  level3: "{p}.{n}"        # 1.1.1
# markers:                 # 마커식(numbering 없을 때). □ / ○ / -
#   level1: "□"
#   level2: "○"
#   level3: "-"
strip_existing: true       # 기존 마커 제거 후 재적용
table:
  header_rows: 1
  header_marker: "■"       # 헤더 셀 마커(빈값=없음)
  cell_bullet: "-"         # 본문 셀 마커(빈값=없음)
  apply_to_cells: false    # true면 셀에도 레벨 번호 적용
```

- `numbering`이 있으면 번호식, 없고 `markers`가 있으면 마커식.
- `level{N}` 미정의 깊은 레벨은 가장 깊은 정의를 재사용.
- 번호 카운터는 상위 레벨이 증가하면 하위가 리셋되는 표준 개요 방식.
- 셀 문단은 기본적으로 표 양식(header_marker/cell_bullet)만 받고, `apply_to_cells:true`면 레벨 번호를 받는다.

## 무손실 보장

무편집 왕복(추출→즉시 원복)은 원본과 **본문 텍스트가 동일**하다(round-trip 검증 포함).
서식은 원본 hwpx에서 그대로 나온다. 단, hwpx는 재압축되므로 **바이트 동일이 아니라
내용·서식 동일**이다(.hwp 페이로드 복원과 다른 점). 표 구조·병합·스타일 참조는 보존된다.

## 다른 스킬과의 관계

- `rnd-write-*` : YAML의 `text`를 절별 문체로 생성해 채우는 데 쓴다.
- `fill-hwp-template` / `split-hwp-chapters` : **.hwp + Markdown + JSON** 계열 파이프라인(원본 바이트 보존형). 이 스킬은 **.hwpx + YAML** 계열(편집분 자동 재생성형)로 목적이 다르다.

## 주의

- 실제 값이 채워진 hwpx/YAML은 개인정보가 들어갈 수 있으니 공개 저장소에 커밋 금지.
- 한컴 COM 변환([0])은 한컴오피스가 설치된 Windows에서만 동작한다.
- 생성 내용은 제출 전 담당자가 근거·수치·규정 적용을 직접 검증해야 한다.
