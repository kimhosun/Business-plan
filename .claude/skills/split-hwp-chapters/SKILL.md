---
name: split-hwp-chapters
description: 한글(HWP) 연구개발계획서 등 제안서 문서를 장(章)·별첨별 Markdown으로 무손실 분리한다. .hwp → 캐논 XML(hwp5proc) → 복원용 마스터 .md(hwpmd_tool export) → 장별 파일 + 매니페스트 + README 로 이어지는 파이프라인을 실행하고, 편집 후 마스터로 재병합·원본 HWP 복원까지 검증한다. 사용 예 "연구개발계획서.hwp 를 장별로 분리", "hwp 문서를 챕터별 md로 나눠줘", "장별 편집본을 다시 병합". 단순 HWP 읽기/요약에는 사용하지 않는다.
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
---

# HWP 문서 장별 분리

HWP 제안서를 **원문·서식·복원정보를 보존하는** 장별 Markdown으로 나눈다. 목표는 두 가지다.

1. **무손실**: 나눈 조각을 순서대로 이으면 마스터 본문과 바이트 단위로 동일하다.
2. **복원 가능**: 각 장 파일의 `<!--@hwp-source-begin-->`~`<!--@hwp-source-end-->` 구간과 앵커를 보존하면 마스터로 재병합하고 원본 HWP까지 복원할 수 있다.

## 언제 이 스킬을 쓰는가

- `.hwp` 제안서를 장·별첨 단위 파일로 나눠 편집하고 싶을 때.
- 이미 만든 마스터 `.md`(hwpmd/1.0)를 장별로 나눌 때.
- 장별 편집본을 마스터로 되돌리거나 원본 HWP 바이트 동일성을 검증할 때.

단순히 HWP 내용을 읽거나 요약만 할 때는 이 스킬을 쓰지 말고 일반 읽기 도구를 쓴다.

## 파이프라인 개요

```
X.hwp ──hwp5proc xml──▶ X.xml ──hwpmd_tool export──▶ X.md(마스터) ──분리──▶ X_장별/
                                                          ▲                    │
                                                          └──merge(재병합)◀────┘
```

- **마스터 `X.md`** 안에는 편집용 본문(HTML+앵커)뿐 아니라 원본 HWP 바이트(base64), 캐논 XML(gzip), 매니페스트가 함께 들어간다. 그래서 마스터 하나로 원본 HWP를 그대로 복원할 수 있다.
- **장별 분리**에는 두 경로가 있다. 아래 0절에서 상황에 맞게 고른다.

## 0. 두 가지 분리 경로 선택

| 경로 | 사용 도구 | 언제 |
|---|---|---|
| **A. 큐레이션(권장, 이 문서 전용)** | `tools/split_hwpmd_chapters.py` | 대상이 이 저장소의 `연구개발계획서.hwp`(또는 동일 서식)일 때. 공통 4 + 장 8 + 별첨 9 = 21개 파일과 장별 규정 참조표까지 정확히 재현한다. |
| **B. 자동(임의 문서)** | `.claude/skills/split-hwp-chapters/scripts/autosplit_hwpmd.py` | 서식이 다른 새 제안서일 때. 헤딩(h1/h2)·섹션 경계에서 자동으로 나눈다. 무손실·재병합 호환이지만 목차/안내문이 헤딩으로 반복되면 과분할될 수 있어 **초안 스캐폴드**로 쓰고 검수한다. |

**두 경로 모두** 마스터 `X.md`가 먼저 있어야 한다. 마스터가 없으면 1절을 먼저 실행한다.

## 1. 사전 요구 및 마스터 생성

### 도구 확인
```bash
python --version
python -c "import hwp5; print('pyhwp OK')"
hwp5proc --version 2>&1 | head -1
```
`pyhwp`(=`hwp5proc`)가 없으면 `pip install pyhwp` 후 사용자에게 보고한다. `hwpmd_tool.py`, `split_hwpmd_chapters.py`, `merge_hwpmd_chapters.py`는 프로젝트 `tools/`에 있으며 **표준 라이브러리만** 쓴다(추가 설치 불필요).

### 마스터 `.md` 생성 (이미 있으면 건너뜀)
```bash
# 1) HWP -> 캐논 XML
hwp5proc xml 연구개발계획서.hwp > 연구개발계획서.xml

# 2) XML + 원본 HWP -> 복원용 마스터 .md
python tools/hwpmd_tool.py export \
  --source 연구개발계획서.hwp \
  --xml    연구개발계획서.xml \
  --output 연구개발계획서.md
```
`export`는 `{"output","bytes","sha256","tables_rendered","images_seen"}`를 출력한다. 이후 XML은 마스터 안에 gzip으로 내장되므로 삭제해도 된다.

### 마스터 무결성 확인
```bash
python tools/hwpmd_tool.py validate --input 연구개발계획서.md --source 연구개발계획서.hwp
```
내장 HWP 페이로드가 원본과 바이트 동일하고, 문단/표/셀/섹션 개수가 매니페스트와 일치하면 통과다.

## 2-A. 경로 A — 큐레이션 분리 (이 문서)

```bash
python tools/split_hwpmd_chapters.py       # 입력/출력 경로는 스크립트에 고정됨
```
`연구개발계획서_장별/`에 21개 장 파일 + `_복원_매니페스트.json` + `README.md`가 생성된다. 이어서 검증한다.
```bash
python tools/validate_split_hwpmd.py        # 오류가 있으면 exit 1 + JSON errors
```
> 경로 A의 `split_hwpmd_chapters.py`와 `validate_split_hwpmd.py`는 **이 문서 전용**이다. 입력 파일명(`연구개발계획서.md`), 장 목록(`PARTS`), 앵커 범위(`S2.P0065..`), S2 노드 개수(805)가 코드에 하드코딩돼 있다. 다른 문서에 그대로 쓰지 말 것. 새 문서는 경로 B를 쓰거나 4절대로 `PARTS`를 새로 작성한다.

## 2-B. 경로 B — 자동 분리 (임의 문서)

`.hwp`에서 한 번에:
```bash
python .claude/skills/split-hwp-chapters/scripts/autosplit_hwpmd.py \
  --from-hwp 새제안서.hwp --review-date 2026-08-03
# hwp5proc + hwpmd_tool export 를 내부에서 실행하고 새제안서.md + 새제안서_장별/ 을 만든다
```
이미 마스터가 있으면:
```bash
python .claude/skills/split-hwp-chapters/scripts/autosplit_hwpmd.py \
  --input 새제안서.md --output 새제안서_장별 --review-date 2026-08-03
```
주요 옵션:
- `--level {1,2,3,4}` (기본 2): 어느 헤딩 레벨까지를 장 경계로 볼지. `h1/h2`(=2)가 장·별첨 제목이면 기본값이 맞다. 너무 잘게 쪼개지면 `--level 1`.
- `--no-dedup`: 같은 제목의 목차 항목을 제거하지 않고 모든 헤딩에서 분리(진단용). 기본은 중복 제목의 **마지막(=실제 본문)** 위치만 경계로 삼아 목차 잡음을 줄인다.

출력은 `{"chapters","body_chars","lossless","source_sha256"}`. `lossless: true`가 아니면 중단하고 원인을 조사한다(마스터가 hwpmd/1.0이 아닐 가능성).

> **경로 B 품질 주의**: 목차·작성안내에 장/별첨 제목이 헤딩으로 반복되거나 별첨 제목이 본문과 목차에서 다르게 렌더링되면 과분할·순서 뒤섞임이 생길 수 있다. 자동 결과는 **검수용 초안**이다. 최종 품질이 필요하면 결과 파일 목록과 매니페스트를 보고 병합·이름변경으로 다듬거나, 경로 A 방식으로 `PARTS`를 확정한다.

## 3. 편집·검증·복원 규칙

장 파일을 편집할 때 **반드시** 지킨다.

1. `<!--@hwp-source-begin-->`와 `<!--@hwp-source-end-->` **사이에서만** 본문을 편집한다.
2. `<!--@hwp ...-->` 앵커, `data-hwp-*` 속성, 표의 `rowspan`·`colspan`, `<br data-hwp-blank>` 등 제어 주석은 **삭제·개명 금지**. 이들이 재병합·복원의 좌표다.
3. 표 셀 경계·행 구조를 임의로 바꾸지 않는다(분리는 표 내부에서 일어나지 않는다).
4. 경로 A의 파일 뒤 `## 국내 규정·지침·가이드라인 참조` 절은 조사·작성용이며 HWP 본문에 병합되지 않는다.

### 재병합 (장별 → 마스터 본문)
```bash
python tools/merge_hwpmd_chapters.py \
  --master 연구개발계획서.md \
  --parts-dir 연구개발계획서_장별 \
  --out 연구개발계획서_장별_병합.md
```
`merge`는 각 장의 SOURCE 구간을 매니페스트 순서로 이어 마스터 본문에 끼워 넣는다. **무편집** 상태면 `body is byte-for-byte identical...`이 출력된다(경로 A·B 산출물 모두 이 도구로 검증 가능 — B의 매니페스트도 동일 스키마다). 편집 후에는 본문 해시가 달라지되 앵커 검증은 통과해야 한다.

### 원본 HWP 바이트 복원 (편집과 무관, 무결성 확인용)
```bash
python tools/hwpmd_tool.py restore-original --input 연구개발계획서.md --output 복원본.hwp
```
마스터에 내장된 원본 바이트를 그대로 되돌린다. 편집 내용을 HWP에 반영하려면 재병합 MD를 앵커 오버레이 입력으로 쓰고 한글에서 다시 저장한다(레이아웃 보존이 목표, 바이트 동일성은 아님).

## 4. 새 문서용 큐레이션 표(PARTS) 작성법

경로 A 수준의 정밀 분리를 새 문서에 적용하려면 `tools/split_hwpmd_chapters.py`의 `PARTS` 튜플을 새로 만든다.

1. 마스터에서 최상위 앵커와 헤딩을 뽑아 장 시작 노드를 찾는다.
   ```bash
   grep -nE '^<!--@hwp node=S[0-9]+\.P[0-9]{4} pid=' 새제안서.md | head
   grep -nE '<h[12] ' 새제안서.md            # 장·별첨 제목 위치
   ```
   또는 경로 B를 먼저 돌려 `_복원_매니페스트.json`의 `start_node`/`source_range`를 초안으로 삼는다.
2. 각 장에 대해 `Part(파일명, 제목, "S2.Pxxxx..S2.Pyyyy", start_node, end_node, references, checks, 카테고리)`를 채운다. `end_node`는 **다음 장의 시작 노드(배타)**, 마지막 장은 `None`.
3. 섹션 0/1/2의 시작(본문 목차 파트 포함)은 `## Section N:` 헤딩 텍스트로, **그 이후의 장·별첨**은 `start_node` 앵커로 잘린다(`split_fragments`는 `starts=[0, section_1, section_2]` 이후 `PARTS[3:]`부터 앵커를 쓴다). `MASTER`/`OUT_DIR`/`REVIEW_DATE` 상수도 새 문서에 맞게 바꾼다.
4. `validate_split_hwpmd.py`의 하드코딩된 경로와 S2 커버리지(`range(805)`)도 새 문서의 노드 수로 고쳐야 한다. 즉시 검증이 필요 없으면 경로 B + `merge`의 본문 해시 확인으로 대체한다.

마커·앵커 체계, 매니페스트 스키마, 세부 규칙은 [references/pipeline.md](references/pipeline.md)를 참고한다.

## Windows·UTF-8 실행 메모

- Python 스크립트는 `python -X utf8 ...`로 실행해 콘솔 인코딩 문제를 피한다.
- 한글 파일을 PowerShell로 읽을 때는 `Get-Content -Encoding UTF8`을 쓴다. 콘솔의 글자 깨짐을 파일 손상으로 단정하지 말고 UTF-8로 다시 읽어 확인한다.
- 모든 산출 파일은 `newline=""`로 기록되어 `\r\n`/`\n` 바이트가 보존된다. 에디터의 자동 개행 변환을 끄고 편집한다.
- `hwp5proc xml` 실행 시 `'xmllint ...': [WinError 2]` 경고가 보일 수 있다. 이는 선택적 예쁜출력기(xmllint)가 없을 때의 폴백 메시지로 **무해**하며 XML은 정상 생성된다(`export`가 표 개수를 정상 보고하면 통과).

## 중단 조건

다음이면 추정하지 말고 사용자에게 확인한다.

- `hwp5proc`/`pyhwp`가 없고 설치 권한이 불확실할 때.
- 자동 분리 결과가 `lossless: false`이거나 마스터에 `<!--@hwp-document-begin-->`가 없을 때(hwpmd/1.0 마스터가 아님).
- 새 문서의 장 경계가 모호해 `PARTS`를 확정할 수 없을 때(목차와 실제 본문의 별첨 개수·순서가 다른 경우 등).
