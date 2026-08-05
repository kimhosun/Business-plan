# 연구개발계획서 작성 웹서비스

hwpx에서 뽑은 세부 항목을 **왼쪽 트리 메뉴(1, 1.1 …)** 로 고르고, 오른쪽 2열에서
**양식 템플릿**(기본은 hwpx에서 추출·AI 생성 가능)과 **작성 프롬프트**(문체·구성)를 정한 뒤,
사용자 입력을 그 양식·문체로 변환해 **YAML→hwpx에 그대로 반영**하는 웹앱.

설계·API·저장구조 계약: [ARCHITECTURE.md](ARCHITECTURE.md).

## 실행

```bash
cd webapp
python -m pip install -r requirements.txt        # 최초 1회
uvicorn backend.main:app --reload --port 8000
# 브라우저 http://127.0.0.1:8000
```

- **Claude 연동**: 환경변수 `ANTHROPIC_API_KEY` 를 설정하면 양식 생성/입력 변환에 실제 Claude 를 호출한다(`ANTHROPIC_MODEL` 기본 `claude-sonnet-5`). 없으면 **결정론적 스텁**으로도 전 기능이 동작한다(입력을 문단 분할→템플릿 마커 적용→해당 절 노드에 매핑).
- **hwp→hwpx 변환·PDF 미리보기**: 한컴오피스가 설치된 Windows 필요(pyhwpx COM). 그 외 단계(추출/변환/원복)는 한컴 불필요.

## 사용 흐름

1. 상단 **[기본 문서로 새 프로젝트]** → 저장소 `연구개발계획서.hwp` 를 변환·추출해 프로젝트 생성.
2. 좌측 트리에서 절(예: **1.1**) 클릭 → 우측에 제목·※작성요령과 4개 패널 로드.
3. **양식 템플릿** 패널: hwpx에서 뽑은 기본 양식이 채워짐. 설명을 적고 *AI로 양식 생성* 하거나 직접 수정 후 저장.
4. **작성 프롬프트** 패널: 문체(style)·구성(structure)을 지정(※작성요령이 기본 프리필).
5. **입력** 패널: 원문을 쓰고 저장.
6. **변환** 패널: [변환] → 입력이 양식·문체대로 바뀌어 해당 절 노드에 매핑(before/after 표시).
7. 상단 **[hwpx 빌드]** → `output/final.hwpx` 생성, 다운로드 + PDF 미리보기 링크.

## 데이터 저장(파일 기반)

```
webapp/data/projects/<pid>/
  project.json · source.hwpx · yaml/section_*.yaml · tree.json
  nodes/<nid>/ template.yaml · prompts.json · input.md · result.yaml
  output/final.hwpx · output/preview.pdf
```
`webapp/data/` 는 개인정보가 담길 수 있어 `.gitignore` 로 제외된다(실제 값 채운 산출물 커밋 금지).

## 재사용 파이프라인

백엔드는 `.claude/skills/hwpx-yaml-roundtrip/` 의 CLI(hwp2hwpx/hwpx2yaml/template/yaml2hwpx)를
그대로 호출한다. yaml2hwpx 는 **미변경 문단을 건드리지 않아** 원본 서식·레이아웃을 보존한다
(PDF 대조로 원본 37p == 복원 37p 검증).
