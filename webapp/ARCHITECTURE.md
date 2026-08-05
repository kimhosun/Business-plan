# 연구개발계획서 웹서비스 — 아키텍처 계약(freeze)

hwpx에서 뽑은 세부 항목을 **왼쪽 트리 메뉴(1, 1.1 …)** 로 고르고, 오른쪽 2열에서
① **양식 템플릿**(기본은 hwpx에서 추출, 사용자가 수정/AI생성)과 ② **작성 프롬프트**
(문체·구성 스타일, 기본은 ※작성요령)를 두고, 사용자 입력을 그 양식·문체로 변환해
**YAML→hwpx 템플릿에 그대로 반영**하는 웹앱.

## 스택 / 실행

- 백엔드: **FastAPI + uvicorn** (파이프라인이 파이썬이라 직결)
- 프론트: 정적 **2열 SPA**(바닐라 JS/HTML/CSS), FastAPI가 `/`로 서빙
- 저장: **파일 기반**(결과가 곧 hwpx 반영값 YAML이라 파이프라인과 동일 소스)
- Claude: `anthropic` SDK, `ANTHROPIC_API_KEY` 있으면 실호출·없으면 **결정론적 스텁**
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
  output/final.hwpx    # 빌드 산출물
  output/preview.pdf   # 미리보기
```

## 모듈 책임

- `backend/config.py` : DATA_DIR, SKILL_SCRIPTS 경로, 기본 원본 hwpx 경로 상수.
- `backend/store.py`  : 프로젝트/노드 파일 CRUD. `project_dir(pid)`, `read_node(pid,nid)`,
  `write_template/prompts/input/result`, `list_projects`, `load_tree`, `node_by_id(tree,nid)`.
- `backend/pipeline.py` : 스킬 CLI 래핑(subprocess). `convert(src,dst)`, `extract(hwpx,dir)`,
  `restore(hwpx,yaml_dir,out,template=None)`, `hwpx_to_pdf(hwpx,pdf)`(pyhwpx),
  `default_template_from_hwpx(pid,nid)`(해당 절의 기존 마커/번호·표 양식을 template.yaml dict로),
  `merge_result_into_yaml(pid, result)`(result의 {path,marker,text}를 yaml/section_*.yaml에 기록).
- `backend/claude_service.py` : `generate_template(description, default_template, sample_texts) -> dict`,
  `convert_input(input_text, template, prompts, targets) -> list[{path,marker,text}]`.
  실키 없으면 스텁(입력을 문단분할→template 마커 적용→targets에 순서대로 매핑).
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
| POST | `/api/projects/{pid}/nodes/{nid}/convert` | Claude 변환→result.yaml 저장+yaml/ 병합 → `{result:[{path,before,after,marker}]}` |
| POST | `/api/projects/{pid}/build` | yaml2hwpx restore → final.hwpx(+pdf) → `{download,preview}` |
| GET  | `/api/projects/{pid}/download` | final.hwpx 파일 |
| GET  | `/api/projects/{pid}/preview.pdf` | preview.pdf 파일 |

- nid 는 URL-safe(예 "1-1"). node_count = len(node_paths).
- 기본 원본: `use_default` 시 저장소 루트 `연구개발계획서.hwp` 를 변환해 사용.
- convert 는 targets = 해당 노드의 `node_paths`(비어있지 않은/편집대상). 스텁도 이 경로에만 기록.
- 모든 파일 IO는 UTF-8. YAML은 `allow_unicode=True, sort_keys=False`.

## UI 요구(프론트)

- 좌: 접기/펼치기 트리. 장 "1", 절 "1.1" 라벨. 클릭 시 노드 로드.
- 우: 제목 + 가이드(※) 박스, 그리고 4개 패널
  1. **양식 템플릿**: template.yaml 텍스트에디터 + "AI로 양식 생성"(설명 입력→generate) + 저장
  2. **작성 프롬프트**: style/structure textarea(기본 가이드 프리필) + 저장
  3. **입력**: 사용자 원문 textarea + 저장
  4. **변환**: 버튼 → 변환결과 before/after 리스트 표시
- 상단바: [hwpx 빌드] → 완료 시 다운로드 링크 + PDF 미리보기 링크.
- fetch 로 API 호출, 한국어 라벨, 반응형 2열(모바일은 세로 스택).
