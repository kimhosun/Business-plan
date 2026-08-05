# 연구개발계획서 HWP–Markdown 문서 자동화 도구 모음

정부 R&D **연구개발계획서(HWP)** 를 구조·서식 복원 정보를 보존하는 Markdown으로 변환하고, 장·절 단위로 **분할·작성·검증·재병합** 하기 위한 문서 자동화 도구·스킬 모음이다.

> 이 저장소는 **특정 기업의 완성된 사업계획서가 아니다.** 현재 포함된 `연구개발계획서.hwp` 는 값이 채워지지 않은 **KEIT 산업기술혁신사업 빈 서식(템플릿)** 이며, 개인정보·기관정보·예산·서명은 들어 있지 않다. 저장소의 실제 자산은 "계획서 내용"이 아니라 **HWP를 무손실 보존하며 AI·사람이 나눠 작성할 수 있게 하는 파이프라인** 이다.

## 무엇을 하는가 / 하지 않는가

- **한다**: HWP → 자체 완결형 Markdown 변환, 원본 HWP 바이트 복원, 장·절 분할과 무손실 재병합, 앵커·해시·규정 링크 무결성 검사, JSON 값으로 Markdown 입력영역 채우기, 절별 작성 지침 추출.
- **하지 않는다(현재)**: 편집된 Markdown을 **수정된 HWP로 자동 생성** 하지 않는다(아래 표 참조). 복합 표·이미지·다중 스타일의 자유 편집을 지원하지 않는다. 계획서의 실제 사업 내용(고객·시장·매출·근거수치)을 대신 만들지 않는다.

## 기능 상태표

| 기능 | 상태 |
|------|------|
| HWP → 자체 완결형 Markdown(`export`) | ✅ 지원 |
| 원본 HWP 바이트 복원(`restore-original`) | ✅ 지원 |
| 장·절 분할 및 무편집 재병합 | ✅ 지원 |
| 앵커·본문해시·규정 링크 무결성 검사(`validate`) | ✅ 지원 |
| JSON 값으로 Markdown 입력영역 채우기(fill-hwp-template) | ⚠️ 제한적(텍스트 전용, 행 추가·삭제/이미지/복합셀 미지원) |
| 절별 작성 지침 추출·동기화(extract-md-guidelines) | ✅ 지원 |
| **편집된 Markdown → 수정된 HWP 자동 생성** | ❌ **미구현** — 아래 "최종 HWP 산출" 참조 |

`restore-original` 은 Markdown에 임베드된 **원본** HWP 바이트를 다시 꺼내는 기능이며, 편집분을 반영해 새 HWP를 쓰는 기능이 아니다(`tools/hwpmd_tool.py` 명령: `export` / `validate` / `restore-original`).

## 전체 흐름

```
원본 HWP
  │ export                (tools/hwpmd_tool.py)
  ▼
자체 완결형 Markdown  = 본문 + canonical XML + 원본 HWP 페이로드
  │ split                 (tools/split_hwpmd_chapters.py)
  ▼
장별·절별 Markdown
  │ 내용 채우기            (fill-hwp-template / JSON 입력, 지침: extract-md-guidelines)
  ▼
편집된 장별 Markdown
  │ validate              (tools/validate_split_hwpmd.py — 앵커·해시·링크·규정)
  │ merge                 (tools/merge_hwpmd_chapters.py)
  ▼
통합 Markdown
  │ ※ 외부·수동 단계       ← 최종 HWP 산출(아래)
  ▼
최종 HWP
```

### 최종 HWP 산출(현재는 수동/외부 단계)

편집된 Markdown을 **수정된 HWP로 자동 변환하는 라이브러리는 아직 없다.** 최종 HWP는 한/글에서 원본을 열고 편집 내용을 반영해 저장하는 **수동 절차** 로 만든다. 이 단계의 자동화는 미구현 상태이며, 향후 과제다. (`restore-original` 로는 *편집 전 원본* 만 복원된다.)

## 주요 파일

- `연구개발계획서.hwp`: 원본 HWP(빈 KEIT 서식)
- `연구개발계획서.md`: 구조 매니페스트와 원본 HWP 페이로드를 포함한 복원용 마스터 Markdown
- `연구개발계획서_장별/`: 공통영역 4개, 본문 8장, 별첨 9개 및 국내 규정·지침 참조
- `연구개발계획서_장별_병합.md`: 장별 파일을 무편집 상태로 재병합해 검증한 마스터 Markdown
- `tools/`: 분할·재병합·구조 검증 및 원본 HWP 복원 도구
- `.claude/skills/`: HWP↔Markdown 파이프라인 및 계획서 작성 스킬(split/subsplit/fill/embed/extract-md-guidelines/rnd-proposal-writer)
- `.agents/skills/verify-korean-rnd-regulations/`: 국내 R&D 규정의 현행성·적용성·출처 일치성을 공식 원문으로 감사하는 Codex 스킬
- `skill_R1.md`, `skill_hwp_style.md`: 연구개발계획서 작성·서식 참고자료
- `규정_최신성_감사_2026-08-03.md`: 장별 규정 참조의 최신성 감사 결과

장별 편집과 복원 방법은 [`연구개발계획서_장별/README.md`](연구개발계획서_장별/README.md)를 참고하라.

## 빠른 시작(검증)

PowerShell(Windows):

```powershell
python .\tools\validate_split_hwpmd.py
python .\tools\merge_hwpmd_chapters.py
python .\tools\hwpmd_tool.py validate --input .\연구개발계획서_장별_병합.md
```

POSIX 셸(Linux/macOS/Git Bash):

```bash
python tools/validate_split_hwpmd.py
python tools/merge_hwpmd_chapters.py
python tools/hwpmd_tool.py validate --input 연구개발계획서_장별_병합.md
```

현재 분할본은 21개 원문 구간, 공식 규정 링크 89개, 최상위 HWP 앵커 809개를 포함한다. 무편집 재병합 시 `연구개발계획서.md` 와 동일한 SHA-256을 재현한다.

> 외부 의존성: `pyhwp`/`hwp5proc`(HWP 파싱), 최종 HWP 편집·저장에는 한/글(HWP) 프로그램이 필요하다. 표준 의존성 명세(`pyproject.toml`)·라이선스는 후속 정비 대상이다.

## ⚠️ 보안·개인정보 주의

- **임베드 페이로드**: `연구개발계획서.md` 와 `연구개발계획서_장별_병합.md` 는 원본 HWP 전체를 base64로 임베드한다. 즉 **Markdown만으로 원본 문서를 완전히 복원**할 수 있다. 현재 원본은 빈 템플릿이라 노출 위험이 낮지만, **실제 값이 채워진 계획서를 이 파이프라인으로 공개 저장소에 커밋하면 개인정보가 그대로 노출**된다.
- **채워진 문서 커밋 금지**: 실제 과제 데이터가 든 HWP/Markdown은 비공개로 관리하거나, 페이로드 임베드 없이 다뤄라.
- **로컬 설정 커밋 금지**: 개인 경로·머신별 권한이 든 `.claude/settings.local.json` 은 `.gitignore` 로 제외된다. 공유용 설정만 `.claude/settings.json` 에 둔다(절대경로·사용자명 금지).
- **AI 생성물 검토 책임**: 스킬이 생성한 내용은 제출 전 담당자가 근거·수치·규정 적용을 직접 검증해야 한다.

## 규정 기준일

국내 규정·지침 링크는 2026-07-30 기준으로 확인했다. 실제 제출 시에는 해당 세부사업의 최신 공고·RFP·협약 및 소관 전문기관 지침을 우선 적용해야 한다. 알려진 규정 참조 불일치는 `규정_최신성_감사_2026-08-03.md` 와 [`검토_반영_보고서.md`](검토_반영_보고서.md)에 정리되어 있다.
