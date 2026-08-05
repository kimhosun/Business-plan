# hwpmd 파이프라인 참조 — 마커·앵커·매니페스트

이 문서는 장별 분리·재병합·복원이 어떤 좌표계 위에서 동작하는지 정리한다. 편집·자동화 시 반드시 보존해야 하는 요소를 명시한다.

## 1. 마스터 `.md` 구조 (hwpmd/1.0)

`hwpmd_tool.py export`가 만드는 마스터는 다음 순서로 구성된다.

1. **YAML 프런트매터** — `hwpmd: "hwpmd/1.0"`, `source`(name/size/sha256/hwp_version), `serialization`, `counts`(sections/paragraphs/tables/table_cells/…), `payloads`(각 페이로드 sha256).
2. **본문(body)** — `<!--@hwp-document-begin-->` … `<!--@hwp-document-end-->` 사이. 편집·분리 대상은 **오직 이 구간**이다.
3. **내장 페이로드 3종** — 아래 fenced 코드블록.

### 내장 페이로드
| 시작 마커 | 인코딩 | fence 언어 | 용도 |
|---|---|---|---|
| `<!--@hwp-template-begin bytes=… sha256=… encoding=base64-->` | base64 | `hwp-template-base64` | 원본 HWP 바이트(복원용) |
| `<!--@hwp-xml-begin bytes=… compressed-bytes=… sha256=… encoding=gzip+base64-->` | gzip+base64 | `hwp-xml-gzip-base64` | 캐논 XML(검증·복원 보조) |
| `<!--@hwp-manifest-begin bytes=… sha256=… encoding=utf-8-->` | utf-8 | `hwp-manifest-json` | 구조 매니페스트 JSON |

모든 sha256은 **대문자 hex**. `restore-original`은 `hwp-template-base64`만 꺼내 길이·sha256을 확인한 뒤 그대로 기록한다(편집 내용은 반영되지 않음 — 원본 무결성 확인용).

## 2. 앵커·노드 경로 체계

본문 안 요소는 다음 규칙으로 주소를 갖는다. **이 주석·속성이 분리/재병합/복원의 좌표다. 절대 삭제·개명하지 않는다.**

- 섹션: `<!--@hwp section=S{n}-->` (예 `S2`). 섹션 라벨은 `## Section {n}: …` Markdown 헤딩으로도 표시된다.
- **최상위 문단(장 분리 단위):** 문단 바로 앞에
  `<!--@hwp node=S{n}.P{index:04d} pid=… style=… para=…-->` (예 `S2.P0065`), 이어서 HTML 블록
  `<p|h1..h5 class="hwp-paragraph|hwp-note" data-hwp-node=… data-hwp-style=… data-hwp-parashape=…>…</…>`.
- 명시적 쪽 나눔: `<!--@hwp page-break before=S{n}.P{index} explicit="true"-->` (해당 문단 앞).
- 표: `<!--@hwp table=…-->` + `<table data-hwp-node data-hwp-table-id data-hwp-rows data-hwp-cols>`, `<tr data-hwp-row>`, `<td data-hwp-cell/col/row/width/height/borderfill [colspan] [rowspan]>`.
- 하위 노드: 표 `…P####.T{nn}` / 기타 컨트롤 `.C{nn}`, 셀 `…R{rr}C{cc}`, 셀 내부 다단 `…COL{nn}`, 셀 문단 `…P{nn}`(셀 내부는 2자리, 최상위는 4자리).

### 헤딩 판정(export 시)
`연구개발계획서`→h1, `목차`→h2, `style_id==170` 또는 `[별첨 N]`→h2, `N.`→h2, `N-N.`→h3, `가.`→h4, `(N)`→h5. 셀 내부는 헤딩으로 보지 않는다.

### 최상위 앵커 정규식(도구 공통)
```
(?m)^<!--@hwp node=(S\d+\.P\d{4}) pid=
```
장 경계는 이 패턴이 잡는 위치에서만 자른다(표·셀 내부 미포함). `page-break` 주석이 앵커 바로 앞에 있으면 경계를 그 앞으로 당겨 쪽 나눔을 보존한다.

## 3. 장 파일 구조

```markdown
---
split_hwpmd: "1.0" | "auto/1.0"
source_hwpmd: "../마스터.md"
source_sha256: "<마스터 전체 sha256(소문자)>"
source_range: "S2.P0065..S2.P0094"
source_fragment_sha256: "<조각 sha256>"
category: "공통" | "장" | "별첨"
...
---

# <제목>

## 원문 양식

<!--@hwp-source-begin-->
<... 마스터 본문에서 잘라낸 조각(앵커·표·속성 그대로) ...>
<!--@hwp-source-end-->

## 국내 규정·지침·가이드라인 참조   ← 경로 A 전용, 복원 대상 아님
```

- 복원 대상은 `hwp-source` 구간뿐이다. `merge`는 `<!--@hwp-source-begin-->\n` 다음부터 `<!--@hwp-source-end-->` 직전까지를 꺼낸다.
- 프런트매터 키는 `source_fragment_sha256`, 매니페스트 키는 `fragment_sha256` — 값은 동일.

## 4. 매니페스트 스키마 (`_복원_매니페스트.json`)

최상위: `format`("split-hwpmd-manifest"), `version`(1), `source_file`, `source_sha256`, `source_body_sha256`, `source_body_chars`, `*_marker` 4종, `regulatory_reviewed`, `parts[]`.

`parts[]` 각 항목:
| 키 | 뜻 |
|---|---|
| `filename` | 장 파일명 |
| `title` / `category` | 제목 / 공통·장·별첨 |
| `source_range` | `S2.Pxxxx..S2.Pyyyy` |
| `start_node` | 시작 앵커(없으면 null) |
| `end_node_exclusive` | 다음 장 시작 앵커(배타, 마지막 장 null) |
| `fragment_sha256` / `fragment_chars` | 조각 해시 / 길이 |
| `top_level_nodes` | 조각 내 최상위 앵커 수 |
| `reference_count` | 규정 참조 수(자동 분리는 0) |

`autosplit_hwpmd.py`도 **같은 스키마**를 쓰므로 `merge_hwpmd_chapters.py`로 그대로 재병합·검증된다.

## 5. 도구별 검증 불변식

- **split(A)**: 조각을 이으면 본문과 완전 일치(`"".join==body`), 경계는 증가·유일, 시작 노드는 최상위 앵커여야 함.
- **autosplit(B)**: 위 무손실 검증 + 목차 중복 제목 제거(마지막 위치만 경계). `lossless:true` 미충족 시 실패.
- **merge**: 마스터 본문 마커 유일성, 각 조각에 `start_node` 존재·`end_node_exclusive` 부재, `top_level_nodes` 일치 확인 후 스플라이스. 본문 해시를 `source_body_sha256`와 대조해 보고(무편집이면 동일).
- **validate(A, 이 문서 전용)**: 조각별 sha256, 참조 절 존재, 링크 수, 공식 도메인 화이트리스트, 중복 앵커 없음, **S2 노드 0..804(805개) 연속 커버리지**. 오류 시 exit 1.

## 6. 흔한 함정

- 마스터에 `<!--@hwp-document-begin-->`가 정확히 1개가 아니면 분리·병합이 모두 실패한다. `hwpmd_tool.py export` 산출물인지 먼저 확인.
- 자동 분리에서 목차·작성안내가 장 제목을 헤딩으로 반복하면 과분할된다(dedup으로 완화하되, 제목이 미세하게 다르면 남을 수 있음). 결과 검수 필요.
- 에디터의 개행 자동 변환(CRLF↔LF)·말미 공백 정리는 조각 해시를 깨뜨린다. `newline` 보존 설정으로 편집.
- 경로 A 도구를 다른 문서에 그대로 돌리면 앵커 범위 불일치로 `missing top-level anchor` 오류가 난다. 새 문서는 경로 B 또는 `PARTS` 재작성.
