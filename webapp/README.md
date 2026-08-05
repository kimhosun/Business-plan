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

- **Claude 연동**: 양식 생성·입력 변환·작성 채팅은 아래 순서로 폴백한다.
  1. `ANTHROPIC_API_KEY` 가 있으면 `anthropic` SDK 로 호출
  2. 없으면 **`claude` 실행파일(Claude Code CLI)** 을 헤드리스(`claude -p`)로 호출 —
     **API 키 없이 이미 로그인된 자격증명으로 동작한다.** VS Code 확장에 동봉된
     `~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe` 등을
     자동 탐색하며, `CLAUDE_CLI_PATH` 로 경로를 직접 지정할 수 있다.
  3. 둘 다 안 되면 **결정론적 스텁**(입력을 문단 분할→템플릿 마커 적용). 이때 답변에 `(스텁 모드)` 와 사유가 표시된다.
  - 관련 환경변수: `ANTHROPIC_MODEL`(기본 `claude-opus-5`) · `CLAUDE_CLI_PATH` ·
    `CLAUDE_CLI_TIMEOUT`(초, 기본 300) · `CLAUDE_EFFORT`(`low|medium|high|xhigh|max`, 미설정 시 기본값) ·
    `CLAUDE_DISABLE_CLI=1`(CLI 경로를 끄고 스텁으로).
  - CLI 경로는 한 턴에 30초~1분 걸릴 수 있다(양식·문체를 반영해 본문 전체를 다시 쓰기 때문). 급하면 `CLAUDE_EFFORT=medium`.
- **hwp→hwpx 변환·PDF 미리보기**: 한컴오피스가 설치된 Windows 필요(pyhwpx COM). 그 외 단계(추출/변환/원복)는 한컴 불필요.
- **작성 규정 PDF**: reportlab 으로 직접 생성하므로 한컴 불필요. 한글 폰트(맑은 고딕 또는 나눔고딕)가 시스템에 있어야 한다.

## 사용 흐름

1. 상단 **[기본 문서로 새 프로젝트]** → 저장소 `연구개발계획서.hwp` 를 변환·추출해 프로젝트 생성.
2. 좌측 트리에서 절(예: **1.1**) 클릭 → 우측에 제목·※작성요령과 4개 패널 로드.
   - 제목 **우측 상단 [📕 작성 규정 PDF]** → 그 절을 쓸 때 적용할 규정이 새 탭에 PDF 로 열린다:
     ① 서식 ※작성요령(원본 hwpx 발췌) ② 절 골격·문서별 변형·문체 지침 ③ 체크리스트
     ④ 이 절이 따르는 공통원칙 § 전문 ⑤ 공통원칙 §0~§9 요약 ⑥ 심화 지침
     ⑦ **부록: 출처** — 원본 md·지침 md·`지침.json` 경로와 sha256, 서식 hwpx/YAML 경로.
     ②~⑥은 ② *작성 프롬프트* 칸에 요약돼 들어가는 내용과 같은 원천이라, 부록 경로로 **나중에 원본을 대조**할 수 있다.
3. **양식 템플릿** 패널: hwpx에서 뽑은 기본 양식이 채워짐. 설명을 적고 *AI로 양식 생성* 하거나 직접 수정 후 저장.
4. **작성 프롬프트** 패널: 문체(style)·구성(structure)을 지정(※작성요령이 기본 프리필).
5. **입력** 패널: 원문을 쓰고 저장. 패널 **하단 채팅**에 재료·수정 지시를 적으면
   Claude 가 그 절의 양식·작성요령·문체를 참고해 **위 입력칸의 본문을 다시 써서 반영**한다
   (Enter 전송 / Shift+Enter 줄바꿈, 자동 반영 체크 해제 시 답변만 표시).
6. **변환** 패널: [변환] → 입력이 양식·문체대로 바뀌어 해당 절 노드에 매핑(before/after 표시).
7. 상단 **[hwpx 빌드]** → `output/final.hwpx` 생성, 다운로드 + PDF 미리보기 링크.

## 데이터 저장(파일 기반)

```
webapp/data/projects/<pid>/
  project.json · source.hwpx · yaml/section_*.yaml · tree.json
  nodes/<nid>/ template.yaml · prompts.json · input.md · result.yaml · chat.json
  output/final.hwpx · output/preview.pdf · output/regulations_<nid>.pdf
```
`webapp/data/` 는 개인정보가 담길 수 있어 `.gitignore` 로 제외된다(실제 값 채운 산출물 커밋 금지).

## 재사용 파이프라인

백엔드는 `.claude/skills/hwpx-yaml-roundtrip/` 의 CLI(hwp2hwpx/hwpx2yaml/template/yaml2hwpx)를
그대로 호출한다. yaml2hwpx 는 **미변경 문단을 건드리지 않아** 원본 서식·레이아웃을 보존한다
(PDF 대조로 원본 37p == 복원 37p 검증).
