# 사양서 — 웹앱 «② 작성 프롬프트»의 문체 스타일

## ① 질의·요청 히스토리
- 2026-08-05: "웹에서 절마다 프롬프트를 작성한 게 `_프롬프트/` 폴더다. 이걸 참조해
  각 절마다 «② 작성 프롬프트 → 문체 스타일(style)»을 업데이트해달라. 충분한 에이전트 사용."

## ② 확정 사양
- «② 작성 프롬프트» 탭의 `문체 스타일 (style)` 필드는 **절별로 달라야** 한다(기존엔 전 절 동일한
  공통 문체 원칙만 제공).
- 절별 문체는 `_프롬프트/{절}.md` 의 `## 문체·형식 규칙`(+ 절 목적·관찰 구성·문서별 편차)에서
  도출한 4~7줄 개조식 블록으로 한다.
- 서빙 형식: `[이 절 문체·형식]\n{절별}\n\n[공통 문체 원칙]\n{공통}`.
  절별 문체가 없는 nid(예: 요약문)는 공통 문체 원칙만 반환.
- 데이터 원천: `webapp/backend/prompt_styles.json`(`styles: {nid: text}`, 33개 절).
  원천 참조는 `_프롬프트/` 이며, `_프롬프트` 개정 시 재생성한다.

## ③ 구현 상태 (완료 2026-08-05)
- `webapp/backend/prompt_styles.json` 신규 — 33개 절 문체(에이전트 9개가 장별로 분담 도출).
- `webapp/backend/presets.py`:
  - `_prompt_styles()` 로더, `_section_style(nid)`(‑OVERRIDES 보정), `_style_for(nid)` 결합 추가.
  - `preset_for()` 의 `style` = `_style_for(nid)`(기존 `_common_style()` 대체).
- 서빙 경로 `GET /api/presets/{nid}` → `preset_for` → `style`(절별) 그대로 반영, 프런트 미변경.

## ④ 미결/후속
- 프런트 `renderNode` 는 저장된 `node.prompts.style` 를 우선 표시 → 절 진입 시 자동 프리필은
  기존대로 "참조 문체 프리셋 불러오기" 버튼(loadPreset)에 의존. 자동 프리필 필요 시 별도 논의.
- `_프롬프트` 원본이 바뀌면 `prompt_styles.json` 재생성 필요(현재 수동).
