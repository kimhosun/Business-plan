# 사양서 — 웹앱 «② 작성 프롬프트»의 문체 스타일

## ① 질의·요청 히스토리
- **2026-08-13**: "«② 작성 프롬프트»·«③ 입력» 탭에서 **제목을 클릭하면 아래 내용이 보였다 안보였다**
  하게." → `initCollapsibles()`(app.js) 추가: 두 패널의 `label.field-label` 은 클릭 시 바로 아래
  textarea 를(`collapsed-content`), 섹션 제목(`.style-part-title`·`.reg-ref-head`·`.rfp-ref-head`·
  채팅 헤더 span)은 그 섹션 본문을(`sec-collapsed`, 제목만 남김) 접는다. 헤더 안 버튼·체크박스 클릭은
  토글에서 제외. 제목 앞 ▾/▸ 캐럿 표시(styles.css `.collapsible`). 기본 펼침, 세션 중 상태 유지.
- 2026-08-05: "웹에서 절마다 프롬프트를 작성한 게 `_프롬프트/` 폴더다. 이걸 참조해
  각 절마다 «② 작성 프롬프트 → 문체 스타일(style)»을 업데이트해달라. 충분한 에이전트 사용."
- **2026-08-10**: "각 챕터별로 «② 작성 프롬프트»에서 **문체 스타일을 3개로 분류**하라 —
  ① 기존 한글파일에서 요구하는 것, ② 스킬로 제공한 것, ③ 추가로 작성. 그리고 **PDF(RFP)
  업로드된 내용도 아래에 추가**." → 문체 스타일 필드를 3원천으로 나누고, 패널 하단에 RFP 참조 표시.
- **2026-08-10(후속)**: "«② 작성 프롬프트»의 **②(스킬)은 (`_프롬프트/`로) 모두 제공했었으니 그걸
  반영**하라." → ②의 원천을 축약본(4~7줄)에서 **`_프롬프트/{절}.md` 핵심 전문**으로 교체.
  '핵심만'(역할·목적·관찰된 구성·문서별 편차·문체규칙; '참고 자료' 로컬경로·'작성 지시' 제외) 채택.

## ② 확정 사양
- «② 작성 프롬프트» 탭의 `문체 스타일 (style)` 은 **3원천으로 분류**해 각각 별도 textarea 로 보인다:
  - **① 기존 한글파일에서 요구하는 것** = 원본 hwpx 의 `※작성요령`(=`node.guidelines`). **읽기전용 참조**.
    (별도 저장 안 함 — chat/convert 에 `[작성요령]` 으로 이미 전달됨.)
  - **② 스킬로 제공한 것** = rnd-write 작성 스킬 = **`_프롬프트/{절}.md` 핵심 전문**(역할·목적·
    관찰된 구성·문서별 편차·문체규칙). **읽기전용·자동**: 저장하지 않고 read 시 항상 현재
    프리셋(`preset.style`)에서 파생한다 → `prompt_styles.json` 만 갱신하면 **모든 절·모든 프로젝트에
    즉시 반영**(저장분 마이그레이션 불필요). "참조 프리셋 불러오기" 버튼은 이제 구성(structure)만 채운다.
  - **③ 추가로 작성** = 사용자가 이 절에만 더할 문체 지침. 편집·저장(사용자 소유).
- **합본**(작성 파이프라인용 `prompts.style`) = `combine(preset.style ②, style_extra ③)` =
  `②\n\n[추가 지침]\n③`(빈 원천 제외). `store.read_node`·`put_prompts` 가 `presets.combine_style`
  로 파생하므로 `chat_write`/`convert_input` 은 무변경으로 항상 최신 ②를 쓴다. ①은 guidelines
  로 별도 전달돼 합본에 넣지 않는다(중복 방지).
- **저장 스키마**(`prompts.json`, 사용자 소유만): `{style_extra, structure, guidelines, preset_skill}`.
  `style`·`style_skill`(②)은 저장하지 않고 read 시 파생. 구버전 파일의 잔여 `style`는 무시된다.
- **② 원천 데이터**: `webapp/backend/prompt_styles.json`(`styles:{nid:text}`, 33개 절, 평균 ~1.4KB).
  `_프롬프트/` 개정 시 `python -m backend.regen_prompt_styles` 로 재생성(핵심 섹션 추출, 스캐폴딩 제외).
- **RFP 참조**: 패널 하단에 업로드된 RFP 본문을 읽기전용으로 표시(`#rfp-ref`). 상세는
  [RFP 업로드](spec_rfp-자동작성.md). 절별 관련 발췌가 아니라 전체 본문.

## ③ 구현 상태
- (2026-08-05) `prompt_styles.json` + `presets.py`(`_style_for(nid)`)로 절별 ② 문체 서빙.
- (2026-08-10) 문체 3분류 + RFP 참조:
  - `frontend/index.html`: 문체 스타일을 `#prompt-style-doc`(①,readonly)·`#prompt-style-skill`(②)·
    `#prompt-style-extra`(③) 3개로 분리, 하단 `#rfp-ref` 박스.
  - `frontend/app.js`: 노드 로드 시 ①=guidelines, ②=`style_skill`(read_node 파생), ③=`style_extra`.
    `API.putPrompts(obj)` 로 변경.
- (2026-08-10 후속) ② 원천을 `_프롬프트/` 핵심 전문으로 교체 + ② 자동파생·읽기전용:
  - `backend/regen_prompt_styles.py` 신규 — `_프롬프트/*.md` 핵심 섹션 추출('참고 자료'·'작성 지시'
    제외) → `prompt_styles.json` 재생성(33절, 평균 ~1.4KB). 재실행: `python -m backend.regen_prompt_styles`.
  - `backend/presets.py`: `_style_for` 라벨 `[이 절 작성 스킬]`, `combine_style(skill,extra)` 추가.
  - `backend/store.py`: `read_node` 가 ②(`style_skill`)·합본 `style` 을 **항상 현재 preset+저장된
    ③ 에서 파생**(사용자 소유는 `style_extra`·`structure` 만). 기존 프로젝트도 저장분 수정 없이 즉시 반영.
  - `backend/main.py`: `put_prompts` 는 `{style_extra,structure}`만 저장하고 응답엔 파생 ②·합본 채움.
  - `backend/schemas.py`: `PromptsBody{style?,style_skill?,style_extra?,structure,guidelines?}`(구버전 필드 관용).
  - `frontend/index.html`·`app.js`·`styles.css`: ② readonly(회색), `savePrompts` 는 {style_extra,structure}만
    전송, `loadPreset` 은 구성(structure)만 채움.
  - 검증(headless): 2-1/2-2 에서 ② ~1.8~2.3KB(## 역할·목적·구성·문체규칙 포함, '참고 자료'·'작성 지시'
    없음) readonly 표시, ③ 저장 왕복 영속(preset 갱신과 무관), ① 518자·RFP 2480자·콘솔오류 0.
    `regen_prompt_styles` 재실행 idempotent 확인.

### 2026-08-10 후속 — '노드 로드 실패'(캐시된 옛 프론트) 수정
- 증상: 3분류 UI 배포 후 열려 있던 탭에서 절 클릭 시 "노드 로드 실패" 토스트.
- 원인: 브라우저가 옛 `index.html`(신규 `#prompt-style-doc/skill/extra` 없음)을 캐시한 채 새
  `app.js` 를 받아, `renderNode` 가 없는 요소의 `.value` 접근 → 예외 → `selectNode` catch.
- 수정: (1) `app.js` `renderNode` 의 프롬프트 필드 대입을 `setVal(sel,v)`(요소 없으면 skip)로
  방어. (2) `main.py` `_NoCacheStatic` 으로 프론트 정적 파일에 `Cache-Control: no-store`.
  (3) **재발 계속되어 추가**: `index.html` 이 `app.js?v=…`·`styles.css?v=…` **버전 쿼리**로 참조 →
  index.html(no-store)은 항상 최신이라 버전만 올리면 브라우저가 새 app.js 를 강제 재요청(옛
  app.js + 새 DOM 불일치 원천 차단). 배포 시 `v=` 를 올린다(현재 `20260810c`).
  (4) `selectNode` catch 에 `console.error(e)` 추가(재발 시 실제 스택 확인용).
- 검증(headless, 버전쿼리 반영): index.html→app.js?v=/styles.css?v=, 두 프로젝트 노드 전부
  로드 성공(실패 0, console error 0). 사용자는 일반 새로고침만 하면 됨(강력새로고침 불필요).

## ④ 미결/후속
- ① 원천(guidelines)이 없는 절(예: 1-1)은 ① 칸이 빈다 — 원본 hwpx 에 ※작성요령이 없어서임(정상).
- ②는 읽기전용(스킬 제공). 절별로 스킬을 손보려면 `_프롬프트/` 를 고치고 재생성한다(프로젝트별 편집은 ③).
- ③ 여러 줄은 합본 `style` 에 `[추가 지침]` 헤더로 붙는다. 헤더 문구는 후속 조정 가능.
