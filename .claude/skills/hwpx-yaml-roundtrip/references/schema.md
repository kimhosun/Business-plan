# hwpx-yaml-roundtrip 공유 계약 (freeze)

이 문서는 4개 CLI(`hwp2hwpx.py`, `hwpx2yaml.py`, `yaml2hwpx.py`, `template.py`)가
공유하는 **고정 계약**이다. 모든 구현은 `scripts/hwpx_common.py`의 함수만 사용해
좌표계·마커·경로 규칙을 일치시킨다. 임의로 스키마 키를 바꾸지 말 것.

## 파이프라인(실행구조)

```
연구개발계획서.hwp
  │ hwp2hwpx.py convert           (pyhwpx, 한컴 COM)      ※ 이미 .hwpx면 생략
  ▼
연구개발계획서.hwpx   ← 서식·구조의 "원천(source of truth)"
  │ hwpx2yaml.py extract          (python-hwpx)
  ▼
yaml/section_00.yaml … + _manifest.yaml   (세부 항목별)
  │ 사람/AI가 text 값 작성
  │ template.py apply             (template.yaml → marker 필드 재계산)
  ▼
채워진 yaml
  │ yaml2hwpx.py restore          (원본 hwpx에 오버레이 + 템플릿)
  ▼
연구개발계획서_최종.hwpx
```

핵심 원칙: **hwpx = 서식 원천, YAML = 내용 오버레이.** hwpx를 새로 생성하지 않고
원본 hwpx를 열어 YAML의 `marker`+`text`를 같은 좌표(path)의 문단에 다시 얹는다.
따라서 서식(글꼴·문단·표 테두리·병합)은 100% 보존된다.

## 편집 단위 = 문단(paragraph). 좌표 = positional path

모든 편집 대상은 **문단**이다(표는 컨테이너, 텍스트는 항상 셀 안 문단에 있음).
문단은 hwpx 내부 id가 아니라 **위치 경로(path)** 로 식별한다(오버레이 안정성).

```
s{sidx}/p{pi}                                  최상위 문단
s{sidx}/p{pi}/t{ti}                            그 문단이 품은 ti번째 표
s{sidx}/p{pi}/t{ti}/r{row}/c{col}/p{cpi}       셀(row,col) 안 cpi번째 문단
```

중첩(셀 안 표)도 같은 규칙을 재귀 적용한다. `row/col`은 셀 앵커 주소(`cell.address`)를
쓴다(병합 셀은 앵커 좌표 1개만 등장).

## YAML 스키마: `hwpx-yaml/1.0` (섹션당 1파일)

`yaml/section_00.yaml`, `section_01.yaml`, … (hwpx 섹션 단위, 무손실 왕복 보장)

```yaml
schema: hwpx-yaml/1.0
source: 연구개발계획서.hwpx        # 원천 hwpx 파일명
source_sha256: "ABCD…"            # 드리프트 감지(restore 시 대조, 불일치는 경고)
section_index: 0
nodes:
  - path: s0/p0
    kind: para                    # para | cell_para | table
    level: 1                      # 개요 깊이(템플릿 번호/마커용). table은 없음
    marker: "□"                   # 감지된 선두 마커(편집·치환 대상). 없으면 ""
    text: "개발 대상 기술의 개요"   # 마커 제거된 본문(편집 대상)
    style: 172                    # styleIDRef (참조·보존, 편집 금지)
    para_pr: 62                   # paraPrIDRef  (참조·보존, 편집 금지)
    char_pr: 31                   # charPrIDRef  (참조·보존, 편집 금지)
  - path: s0/p1/t0
    kind: table
    rows: 26
    cols: 5                       # 표는 구조만 기록(셀 문단은 아래 cell_para로)
  - path: s0/p1/t0/r0/c0/p0
    kind: cell_para
    row: 0
    col: 0
    span: [1, 1]                  # [rowspan, colspan]
    level: 1
    marker: ""
    text: "구분"
    style: 0
    para_pr: 0
    char_pr: 0
```

- `nodes`는 **문서 순서(DFS)** 를 유지한다. 순서·path를 바꾸지 말 것.
- 편집 가능한 필드는 `marker`, `text` 뿐. 나머지(`path/kind/style/para_pr/char_pr/row/col/span/rows/cols`)는 좌표·서식 보존용이므로 사람이 손대지 않는다.
- `_manifest.yaml`: `{schema, source, source_sha256, sections:[{index, part_name, file, node_count}]}`.

## 템플릿 스펙: `hwpx-yaml-template/1.0`  (`template.yaml`)

사용자가 제공하는 **레벨별 번호/마커 규칙 + 표 양식**. `template.py`가 이 규칙으로
각 노드의 `marker` 필드를 재계산한다.

```yaml
schema: hwpx-yaml-template/1.0

# (A) 번호식: 순차 번호. 있으면 markers보다 우선.
#   {n}=현재레벨 카운터, {p}=상위 누적("1.2"), {P}=조상 전체("1.2.3")
numbering:
  level1: "{n}."        # 1.  2.  3.
  level2: "{p}.{n}"     # 1.1  1.2
  level3: "{p}.{n}"     # 1.1.1

# (B) 마커식: 고정 기호(번호 없음). numbering이 없을 때 사용.
markers:
  level1: "□"
  level2: "○"
  level3: "-"

strip_existing: true    # 기존 선두 마커를 제거 후 새 마커/번호로 교체

# (C) 표 양식
table:
  header_rows: 1        # 상단 N행을 헤더로
  header_marker: "■"    # 헤더 셀 선두 마커(없으면 생략)
  cell_bullet: ""       # 본문 셀 선두 마커(없으면 생략)
  apply_to_cells: false # true면 셀 문단에도 numbering/markers 레벨 규칙 적용
```

규칙: `numbering`이 있으면 번호식, 없고 `markers`가 있으면 마커식.
`level{N}` 키가 없는 깊은 레벨은 가장 깊은 정의를 재사용한다.
`strip_existing:true`면 기존 `marker`를 버리고 새로 계산, `false`면 비어있을 때만 채운다.
카운터는 **섹션 경계와 무관하게 문서 전체에서 이어지는 것이 아니라**, 같은 상위 레벨
그룹 안에서 리셋된다(표준 개요 번호). 셀 문단(`cell_para`)은 `apply_to_cells:true`일 때만
레벨 규칙을 받고, 그 외에는 표 양식(header_marker/cell_bullet)만 받는다.

## hwpx_common.py 공개 함수(모든 CLI가 이것만 사용)

```python
open_hwpx(path) -> HwpxDocument
sha256_file(path) -> str                      # 대문자 hex
detect_marker(text) -> (marker:str, rest:str) # 선두 마커 분리
MARKER_RE                                      # 컴파일된 선두 마커 정규식
iter_section_nodes(section, sidx) -> Iterator[dict]   # 스키마 노드 dict(DFS)
resolve_para(doc, path) -> HwpxOxmlParagraph   # path로 문단 객체 해석(오버레이용)
resolve_table(doc, path) -> HwpxOxmlTable      # tXXX로 끝나는 path
write_para(para, marker, text) -> None         # marker+text를 서식 보존하며 기록
save_hwpx(doc, path) -> None                   # deprecated save 회피(to_bytes/save_to_path)
infer_level(marker, style, in_cell) -> int     # 마커/스타일로 레벨 추정(기본 1)
```

`write_para`는 `para.text = (f"{marker} {text}" if marker else text)` 규칙으로
쓰되 첫 run의 charPr을 보존한다(python-hwpx `.text` setter가 이를 처리).
`save_hwpx`는 `doc.save_to_path(path)`가 있으면 그것을, 없으면 `to_bytes()`를 파일에 쓴다.
