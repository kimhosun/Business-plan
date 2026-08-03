# 연구개발계획서 HWP–Markdown 프로젝트

`연구개발계획서.hwp`를 구조·서식 복원 정보를 보존하는 Markdown으로 변환하고, 본문 각 장과 별첨을 개별 파일로 분리한 프로젝트입니다.

## 주요 파일

- `연구개발계획서.hwp`: 원본 HWP
- `연구개발계획서.md`: 구조 매니페스트와 원본 HWP 페이로드를 포함한 복원용 마스터 Markdown
- `연구개발계획서_장별/`: 공통영역 4개, 본문 8장, 별첨 9개 및 국내 규정·지침 참조
- `연구개발계획서_장별_병합.md`: 장별 파일을 무편집 상태로 재병합해 검증한 마스터 Markdown
- `tools/`: 분할, 재병합, 구조 검증 및 원본 HWP 복원 도구
- `skill_R1.md`, `skill_hwp_style.md`: 연구개발계획서 작성·서식 참고자료

장별 편집과 복원 방법은 [`연구개발계획서_장별/README.md`](연구개발계획서_장별/README.md)를 참고하세요.

## 검증

```powershell
python .\tools\validate_split_hwpmd.py
python .\tools\merge_hwpmd_chapters.py
python .\tools\hwpmd_tool.py validate --input .\연구개발계획서_장별_병합.md
```

현재 분할본은 21개 원문 구간, 공식 규정 링크 89개, 최상위 HWP 앵커 809개를 포함합니다. 무편집 재병합 시 `연구개발계획서.md`와 동일한 SHA-256을 재현합니다.

## 규정 기준일

국내 규정·지침 링크는 2026-07-30 기준으로 확인했습니다. 실제 제출 시에는 해당 세부사업의 최신 공고, RFP, 협약 및 소관 전문기관 지침을 우선 적용해야 합니다.
