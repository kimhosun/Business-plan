---
name: verify-korean-rnd-regulations
description: Audit Korean national R&D laws, decrees, ministerial rules, administrative rules, notices, annual plans, RFPs, and agency guidelines cited in Markdown or research-plan documents. Use when Codex must determine whether Korean R&D regulatory references are current as of a specified date, detect repealed or superseded rules and future-effective amendments, verify article numbers and numeric requirements, distinguish KEIT/KETEP/other agency applicability, produce an evidence-backed audit report, or safely update regulatory-reference sections. Browse official primary sources on every run. Do not use for generic legal advice or link-only HTTP health checks.
---

# 국내 R&D 규정 최신성 검증

공식 원문의 **시행 상태와 적용 범위**를 기준일 현재 검증하라. 링크가 열리는지만 확인하지 말고 제명, 발령번호, 시행일, 조문, 금액·비율·기한 및 해당 사업 적용성을 함께 대조하라.

## 원칙

- 실행할 때마다 인터넷을 검색하라. 기억이나 이 스킬의 과거 실행 결과를 현행 근거로 사용하지 마라.
- 국가법령정보센터와 소관 부처·전문기관의 공식 원문만 판정 근거로 사용하라.
- 공포일·발령일·게시일과 시행일을 구분하라. 기준일 이후 시행되는 개정은 `시행예정`으로 분리하고 현행으로 표시하지 마라.
- 링크의 `lsiSeq`, `admRulSeq`, `efYd`가 과거 버전을 고정할 수 있으므로 같은 제명을 공식 검색하여 현행 통합본문과 다시 대조하라.
- 포털 사용법, 설명자료, 검색결과 화면은 법적 근거로 승격하지 마라.
- 해당 연도 세부사업 공고·RFP·품목요약서·협약의 특칙을 일반 규정보다 우선하되 상위법과 충돌 여부를 확인하라.
- 기본 동작은 읽기 전용 감사로 제한하라. 사용자가 수정을 요청한 경우에만 파일을 변경하라.
- `최신성`, `과제 적용성`, `출처 일치성`을 서로 다른 축으로 판정하라. 현행 공식 자료라도 다른 과제의 RFP이면 통과시키지 마라.

세부 판정 규칙과 보고서 열은 [references/verification-rules.md](references/verification-rules.md)를 읽고 적용하라.

## 1. 감사 범위 고정

1. 기준일을 `YYYY-MM-DD`로 기록하라. 사용자가 지정하지 않으면 시스템 현재 날짜를 사용하라.
2. 대상 파일과 사업 체계를 식별하라. 본 프로젝트는 기본적으로 산업통상부–KEIT 산업기술혁신사업 서식이지만 실제 공고가 다르면 그 체계를 우선하라.
3. 법령·행정규칙뿐 아니라 표에 적힌 조문, 시행일, 발령번호, 금액, 비율, 기한, 시스템명과 적용기관 주장도 감사 범위에 포함하라.
4. 개인정보나 과제기밀을 검색어로 외부에 전송하지 마라. 규정 제명·발령번호·일반적인 조문 주제만 검색하라.

## 2. 인용 목록 추출

대상 Markdown이 여러 개면 먼저 포함 스크립트를 실행하라.

```powershell
python .\skills\verify-korean-rnd-regulations\scripts\inventory_regulations.py .\연구개발계획서_장별 --as-of YYYY-MM-DD --format markdown
```

JSON이 필요하면 다음과 같이 실행하라.

```powershell
python .\skills\verify-korean-rnd-regulations\scripts\inventory_regulations.py .\연구개발계획서_장별 --as-of YYYY-MM-DD --format json --output .\regulation-inventory.json
```

스크립트 결과의 다음 경고를 우선 검토하라.

- `pinned-version`: 특정 법령·행정규칙 버전에 고정된 링크
- `search-page`: 검색결과 화면 링크
- `non-official`: 공식 출처 허용목록 밖의 링크
- `missing-review-date`: 검토 기준일이 없는 파일
- `project-link-placeholder`: 실제 세부공고·RFP 링크가 아직 비어 있음
- `multi-instrument-single-link`: 법률·시행령·시행규칙 등 여러 규정을 한 링크로 대표함
- `generic-homepage`: 포털 홈페이지이므로 주장에 대한 직접 근거인지 검토가 필요함
- `stale-review-date`: 파일 검토일이 감사 기준일보다 과거임

스크립트는 Markdown 링크, 본문에 직접 적힌 URL, 괄호형 규정명과 일부 고위험 수치 주장을 후보로 수집할 뿐 현행 여부를 판정하지 않는다. HTML로 분절되거나 정식 제명 없이 적힌 조문·수치 주장이 더 있을 수 있으므로 원문 검색을 병행하고, 최종 판정은 반드시 공식 원문을 열어 수행하라. `generic-homepage`는 자동 오류가 아니라 직접 근거성 검토 신호다. RCMS·ZEUS 탐색 링크는 유지할 수 있지만 과제별 통보문·승인·증빙 주장의 직접 근거로는 통과시키지 마라.

## 3. 공식 원문 검증

각 고유 규정에 대해 다음 순서로 확인하라.

1. 제명으로 국가법령정보센터 또는 소관기관 공식 사이트를 검색하라.
2. 기준일에 시행 중인 통합본문의 제명, 법령종류, 공포·발령번호, 공포·발령일, 시행일을 기록하라.
3. 폐지·타법개정·전부개정·제명변경 여부와 후속 규정을 확인하라.
4. 기준일 이후 공포되어 시행 예정인 버전이 있으면 시행일과 영향 조문을 별도 기록하라.
5. 문서가 주장한 조문번호, 기준금액, 비율, 기간, 승인·보고 요건을 현재 조문과 직접 대조하라.
6. 전문기관·사업유형·연구개발기관 유형·과제 선정연도에 따라 적용되는지 판정하라.
7. 서로 다른 전문기관 규정을 혼용했는지 확인하라. 특히 KEIT 산업기술혁신사업과 KETEP 에너지사업 규정을 구분하라.
8. 한 표 행에 여러 규정을 적었다면 각 규정의 직접 원문이 따로 연결됐는지 확인하라.
9. IRIS·SROME 등 홈페이지는 로그인 후 제공되는 과제별 통보문·협약문서를 대신할 수 없다고 판정하라.

기술 질문 검색에는 공식 문서만 사용하라. 검색결과의 요약문만으로 판정하지 말고 원문 페이지를 열어 확인하라.

공식 현행 원문 자체에 삭제된 조문을 가리키는 교차참조나 상위법과의 모순이 보이면 임의로 바로잡지 마라. 세 축 판정과 별도로 `official_source_conflict`를 기록하고 경쟁 문구·발령정보를 나란히 제시한 뒤 소관 전문기관의 서면 확인을 요청하라.

## 4. 세 축 판정

각 인용에 세 상태를 모두 부여하라.

`currency`:

- `current`
- `current_with_promulgated_future_change`
- `future_not_effective`
- `historical`
- `superseded`
- `repealed`
- `unable_to_verify`

`applicability`:

- `applicable`
- `not_applicable`
- `conditional`
- `undetermined`

`source_match`:

- `exact`
- `partial`
- `mismatch`
- `inaccessible`

추가로 자료의 성격을 `legal_authority`, `official_guidance`, `official_system`, `project_document` 중 하나로 표시하라. 예를 들어 현행 KEIT 페이지라도 다른 과제의 수요조사이면 `currency=current`, `applicability=not_applicable`, `source_match=mismatch`가 될 수 있다.

과제 제출·협약 시점이 없으면 `currency`만 확정하고 `applicability=undetermined`로 두어라. 링크가 검색·목록 화면이거나 깨졌으면 `source_match=partial|inaccessible`로 기록하라.

## 5. 보고

먼저 결론을 제시하고 다음 순서로 보고하라.

1. 기준일, 대상 파일 수, 고유 인용 수, 공식 출처 범위
2. 상태별 건수
3. 즉시 수정이 필요한 항목
4. 전체 감사표
5. 시행예정 변경
6. 세부공고·RFP가 없어 미확정인 항목

모든 판정 옆에 공식 원문 링크를 배치하라. `확인됨`, `추정`, `미확인`을 명시적으로 구분하고, 직접 확인하지 않은 발령번호나 시행일을 만들어내지 마라.

법적 효력의 위계와 최신본을 찾는 출처 우선순위를 혼동하지 마라. 법률→대통령령→총리령·부령→적법한 위임 범위의 행정규칙을 먼저 확인하고, 과제별 공고·RFP·협약은 상위 강행규정과 위임 범위 안에서 일반 가이드보다 우선한다고 표현하라.

## 6. 파일 수정

사용자가 수정을 요청한 경우에만 다음 규칙으로 변경하라.

- HWP 복원 대상인 `<!--@hwp-source-begin-->`–`<!--@hwp-source-end-->` 구간은 규정 참조 수정만을 이유로 변경하지 마라.
- 파일 뒤의 `국내 규정·지침·가이드라인 참조` 절과 `regulatory_reviewed` 날짜만 수정하라.
- 현행 통합본문을 찾기 쉬운 안정적 제명 링크를 우선하고, 특정 버전 링크가 필요하면 기준일과 버전을 함께 적어라.
- 과거 과제에 적용되는 규정을 무조건 최신 규정으로 바꾸지 마라. 과제 선정·협약 시점의 경과규정과 협약 조건을 먼저 확인하라.
- 수정 후 인용 목록을 다시 추출하고 변경 전·후 상태를 보고하라.

## 중단 조건

다음 경우 추정하지 말고 사용자에게 필요한 자료를 요청하라.

- 세부사업명·공고번호·선정연도에 따라 적용 규정이 달라지는데 식별할 수 없음
- 로그인이나 비공개 협약서가 있어야 최종 판정 가능
- 공식 사이트 장애로 현행 원문과 시행 상태를 확인할 수 없음
- 상충하는 공식 원문이 있고 소관기관의 해석이 필요함

## Windows 실행

한국어 파일을 PowerShell에서 읽을 때 `Get-Content -Encoding UTF8`을 사용하고, 스킬 검증기는 `python -X utf8 ...\quick_validate.py`로 실행하라. 콘솔 문자 깨짐을 파일 손상으로 단정하지 말고 UTF-8로 다시 읽어 확인하라.
