# 연구개발계획서 웹서비스 — 아키텍처 계약(freeze)

hwpx에서 뽑은 세부 항목을 **왼쪽 트리 메뉴(1, 1.1 …)** 로 고르고, 오른쪽 2열에서
① **양식 템플릿**(기본은 hwpx에서 추출, 사용자가 수정/AI생성)과 ② **작성 프롬프트**
(문체·구성 스타일, 기본은 ※작성요령)를 두고, 사용자 입력을 그 양식·문체로 변환해
**YAML→hwpx 템플릿에 그대로 반영**하는 웹앱.

## 스택 / 실행

- 백엔드: **FastAPI + uvicorn** (파이프라인이 파이썬이라 직결)
- 프론트: 정적 **2열 SPA**(바닐라 JS/HTML/CSS), FastAPI가 `/`로 서빙
- 저장: **파일 기반**(결과가 곧 hwpx 반영값 YAML이라 파이프라인과 동일 소스)
- Claude: `ANTHROPIC_API_KEY` 있으면 `anthropic` SDK → 없으면 **`claude` 실행파일**
  (Claude Code CLI 헤드리스 `claude -p`, 키 없이 로그인 자격증명 사용) → 둘 다 안 되면 **결정론적 스텁**
- 구동: `cd webapp && uvicorn backend.main:app --reload` → http://127.0.0.1:8000

## 재사용 자산(이미 존재·검증됨)

hwpx↔YAML 파이프라인 CLI (`.claude/skills/hwpx-yaml-roundtrip/scripts/`):
`hwp2hwpx.py convert` · `hwpx2yaml.py extract` · `template.py apply` ·
`yaml2hwpx.py restore [--template]`. yaml2hwpx는 **미변경 문단은 skip**하므로 레이아웃 보존.
좌측 메뉴 트리: `webapp/backend/tree.py :: build_tree(yaml_dir) -> list[node]`
  node = {id,label,num,title,level,path,node_paths[],table_paths[],guidelines[],children[]}

## 파일 저장 구조

```
webapp/data/projects/<pid>/
  project.json         # {id,name,source_hwpx,source_sha256,created}
  source.hwpx          # 원천(서식 기준)
  yaml/section_*.yaml  # 추출본(+_manifest.yaml). 변환 결과가 여기에 병합됨
  tree.json            # build_tree 결과(좌측 메뉴)
  nodes/<nid>/         # nid = 트리 id, 예 "1-1"
    template.yaml      # hwpx-yaml-template/1.0 (기본은 hwpx에서 추출)
    prompts.json       # {"style": "...", "structure": "...", "guidelines": [...]}
    input.md           # 사용자 원문 입력
    result.yaml        # 변환결과 = [{path,marker,text}] (yaml/에 반영된 값)
    chat.json          # 작성 채팅 이력 [{role,content,at}]
  output/final.hwpx    # 빌드 산출물
  output/preview.pdf   # 미리보기
  rfp/source.<ext>     # 업로드된 RFP 원본(.pdf/.hwpx/.hwp)
  rfp/rfp.txt          # 추출 텍스트(MAX_CHARS 로 절단)
  rfp/meta.json        # {filename,ext,chars,uploaded}
```

## 모듈 책임

- `backend/config.py` : DATA_DIR, SKILL_SCRIPTS 경로, 기본 원본 hwpx 경로 상수.
- `backend/store.py`  : 프로젝트/노드 파일 CRUD. `project_dir(pid)`, `read_node(pid,nid)`,
  `write_template/prompts/input/result`, `list_projects`, `load_tree`, `node_by_id(tree,nid)`.
- `backend/pipeline.py` : 스킬 CLI 래핑(subprocess). `convert(src,dst)`, `extract(hwpx,dir)`,
  `restore(hwpx,yaml_dir,out,template=None)`(복원 시 `HWPX_APPLY_FONTS=1`로 **본문 돋움 12pt·표 셀
  돋움 8pt** 전역 적용 — hwpx_common.apply_fonts, 빈 문단 제외), `hwpx_to_pdf(hwpx,pdf)`(pyhwpx),
  `default_template_from_hwpx(pid,nid)`(해당 절의 기존 마커/번호·표 양식을 template.yaml dict로),
  `merge_result_into_yaml(pid, result)`(result의 {path,marker,text}를 yaml/section_*.yaml에 기록).
- `backend/claude_service.py` : `generate_template(description, default_template, sample_texts) -> dict`,
  `convert_input(input_text, template, prompts, targets) -> list[{path,marker,text}]`,
  `chat_write(context, history, message) -> {reply, draft}`(절 맥락 대화로 본문 초안 작성),
  `draft_from_rfp(context, rfp_text) -> str`(RFP 근거 + **인터넷 조사**로 절 본문 1회 생성),
  `segment_input(text, template, prompts, targets) -> list`(LLM 없이 초안을 targets에 결정론적 분할).
  RFP 초안은 기본으로 **웹 조사 모드**: CLI 는 `--allowed-tools WebSearch WebFetch`(그 외 도구는 계속 차단),
  SDK 는 서버측 `web_search` 도구로 시장·기술·표준·정책 수치를 실제 조사해 (출처,연도)와 함께 쓴다.
  `RFP_DISABLE_RESEARCH`로 끄면 예전(자리표시) 방식. 조사는 오래 걸려 `CLAUDE_RESEARCH_TIMEOUT`(기본 600s).
  호출은 `_ask()` 하나로 모이며 **API 키 → `claude` 실행파일(`_find_cli`/`_cli_text`) → 스텁** 순 폴백.
  CLI 는 `--system-prompt` 로 시스템 프롬프트를 교체하고 도구를 모두 막아 순수 생성기로 쓴다.
  스텁으로 떨어지면 답변에 `(스텁 모드)` 와 사유가 남는다.
- `backend/presets.py` : 절별 '작성 프롬프트' 프리셋 조립(rnd-proposal-writer `_지침/지침.json` 단일 원천).
  `preset_for(nid)`, `file_for(nid)`(절→원본 md 파일명), `skill_for(nid)`.
- `backend/rfp.py` : RFP(제안요청서/공고) 업로드 → 절 자동작성. `extract_rfp_text(src)`
  (.pdf=PyMuPDF, .hwpx=hwpx2yaml extract, .hwp=convert 후 동일), `autofill(pid,rfp_text,sections,apply_yaml)`
  (절별 `claude_service.draft_from_rfp` **병렬** 생성→input.md, apply면 `segment_input`으로 나눠 yaml 병합).
  `TARGET_SECTIONS`=[1-1,1-2,2-1,2-2,4-1,4-2,5-1,5-2,5-3,5-5], 2-2는 '기본 제안(baseline)'.
  초안 생성만 ThreadPoolExecutor 병렬(RFP_AUTOFILL_WORKERS, 기본 5), yaml 병합은 공유파일이라 순차.
- `backend/regulations.py` : 절별 '작성 규정' 묶음 + PDF. `regulation_for(nid, node)` 는
  서식 ※작성요령(node.guidelines), 절 지침(골격/변형/문체), 체크리스트, 참조 공통원칙 §,
  공통원칙 §0~§9 요약, 심화 지침, **출처 경로(원본 md·지침 md·지침.json·sha256)** 를 모으고,
  `build_pdf(reg, out, project_ctx)` 가 reportlab(맑은 고딕/나눔고딕)으로 A4 PDF 를 렌더한다.
  출처 부록이 있어 UI ② 프롬프트 칸의 요약 문구를 나중에 원본과 대조할 수 있다.
- `backend/schemas.py` : pydantic 모델(요청/응답).
- `backend/main.py` : FastAPI 앱 + 라우트 + 정적 프론트 마운트.
- `frontend/index.html, app.js, styles.css` : 2열 UI.

## REST API 계약(정확히 구현)

| 메서드 | 경로 | 동작 |
|---|---|---|
| POST | `/api/projects` | body `{use_default:true}` 또는 multipart `file`(.hwp/.hwpx). 변환+추출+트리 생성. → `{pid}` |
| GET  | `/api/projects` | 프로젝트 목록 `[{id,name,created}]` |
| GET  | `/api/projects/{pid}/tree` | tree.json |
| GET  | `/api/projects/{pid}/nodes/{nid}` | `{id,label,title,guidelines,template,prompts,input,result,node_count}` (없는 값은 기본 생성) |
| PUT  | `/api/projects/{pid}/nodes/{nid}/template` | body `{template:{...}}` 저장 |
| POST | `/api/projects/{pid}/nodes/{nid}/template/generate` | body `{description}` → Claude 생성→저장→반환 |
| PUT  | `/api/projects/{pid}/nodes/{nid}/prompts` | body `{style,structure}` 저장 |
| PUT  | `/api/projects/{pid}/nodes/{nid}/input` | body `{input}` 저장 |
| POST | `/api/projects/{pid}/nodes/{nid}/chat` | body `{message,apply}` → Claude 가 절 맥락(양식·작성요령·문체·현재 본문)으로 답변+본문 초안 생성. apply면 input.md 반영 → `{reply,draft,input,chat}` |
| DELETE | `/api/projects/{pid}/nodes/{nid}/chat` | 채팅 이력 초기화(본문 유지) → `{chat}` |
| POST | `/api/projects/{pid}/nodes/{nid}/convert` | Claude 변환→result.yaml 저장+yaml/ 병합 → `{result:[{path,before,after,marker}]}` |
| GET  | `/api/regulations/{nid}` | 절 nid 작성 규정(구조화 JSON) + 원본 확인 경로 |
| GET  | `/api/projects/{pid}/nodes/{nid}/regulations.pdf` | 절 nid 작성 규정 PDF(inline). output/regulations_{nid}.pdf 로 생성 |
| GET  | `/api/projects/{pid}/rfp` | 업로드된 RFP 메타 + 기본 대상 절 → `{meta:{filename,chars,uploaded},sections[]}` |
| POST | `/api/projects/{pid}/rfp` | multipart `file`(.pdf/.hwpx/.hwp). 텍스트 추출·저장 → `{filename,chars,sections}` |
| POST | `/api/projects/{pid}/rfp/autofill` | body `{sections?,apply}`. RFP 근거로 절들을 **병렬** 자동작성해 input.md 채움(apply면 yaml 병합) → `{results:[{nid,title,ok,chars,applied,error}],ok_count,total}` |
| POST | `/api/projects/{pid}/build` | yaml2hwpx restore → final.hwpx(+pdf) → `{download,preview}` |
| GET  | `/api/projects/{pid}/download` | final.hwpx 파일 |
| GET  | `/api/projects/{pid}/preview.pdf` | preview.pdf 파일 |

- nid 는 URL-safe(예 "1-1"). node_count = len(node_paths).
- 기본 원본: `use_default` 시 저장소 루트 `연구개발계획서.hwp` 를 변환해 사용.
- convert 는 targets = 해당 노드의 `node_paths`(비어있지 않은/편집대상). 스텁도 이 경로에만 기록.
- 모든 파일 IO는 UTF-8. YAML은 `allow_unicode=True, sort_keys=False`.

## UI 요구(프론트)

- 좌: 상단에 **[📥 RFP 업로드 · 자동작성]**(한글/PDF 선택 → 업로드·추출→절 병렬 자동작성, 진행 상태·경과초 표시,
  완료 시 대상 절 leaf 에 "✓ 자동작성" 배지). "YAML 문서까지 반영" 체크박스(apply). 그 아래 접기/펼치기 트리.
  장 "1", 절 "1.1" 라벨. 클릭 시 노드 로드.
- 우: 제목 + **우측 상단 [📕 작성 규정 PDF]**(그 절의 규정을 새 탭에 PDF 로) + 가이드(※) 박스, 그리고 4개 패널
  1. **양식 템플릿**: template.yaml 텍스트에디터 + "AI로 양식 생성"(설명 입력→generate) + 저장
  2. **작성 프롬프트**: style/structure textarea(기본 가이드 프리필) + 저장
  3. **입력**: 사용자 원문 textarea + 저장, 하단에 **작성 채팅**(Claude) —
     아래에 지시를 쓰면 위 본문을 양식·문체대로 다시 써서 반영(자동 반영 토글·대화 초기화)
  4. **변환**: 버튼 → 변환결과 before/after 리스트 표시
- 상단바: [hwpx 빌드] → 완료 시 다운로드 링크 + PDF 미리보기 링크.
- fetch 로 API 호출, 한국어 라벨, 반응형 2열(모바일은 세로 스택).
