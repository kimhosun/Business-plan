# hwpx-yaml-roundtrip

한글 문서(.hwp/.hwpx)를 **hwpx로 변환 → 세부 항목별 YAML → 내용 작성 → 원본 hwpx에
오버레이 원복**하는 실행구조와, 원복 시 **번호/마커 템플릿**·**표 양식**을 적용하는 스킬.

`.hwp`(바이너리, CFB)와 달리 **`.hwpx`는 ZIP+XML(OWPML)** 이라 편집분을 다시 써넣는
왕복이 실제로 가능하다. 저장소의 기존 `split-hwp-chapters`/`fill-hwp-template` 파이프라인이
".hwp+Markdown+JSON, 원본 바이트 보존" 계열이라면, 이 스킬은 ".hwpx+YAML, 편집분 자동
재생성" 계열이다.

## 구성

| 파일 | 역할 |
|------|------|
| `SKILL.md` | 스킬 사용법(트리거·커맨드·스키마·템플릿) |
| `references/schema.md` | 4개 CLI가 공유하는 **고정 계약**(YAML 스키마·템플릿 스펙·좌표 규칙) |
| `scripts/hwpx_common.py` | 공용 모듈: 노드 추출·path 해석·마커 감지·읽기/쓰기(검증됨) |
| `scripts/hwp2hwpx.py` | `[0]` hwp→hwpx 변환(pyhwpx, 한컴 COM) |
| `scripts/hwpx2yaml.py` | `[1]` hwpx→섹션별 YAML 추출 |
| `scripts/template.py` | `[3]` 번호/마커 템플릿 엔진(`apply_to_nodes` + CLI) |
| `scripts/yaml2hwpx.py` | `[4]` YAML 오버레이 원복(+ 선택적 템플릿) |
| `template.example.yaml` | 번호식/마커식 템플릿 예시 |

## 빠른 시작

```bash
SC=.claude/skills/hwpx-yaml-roundtrip/scripts
python $SC/hwp2hwpx.py  convert --in 연구개발계획서.hwp   --out 연구개발계획서.hwpx
python $SC/hwpx2yaml.py extract --in 연구개발계획서.hwpx  --out-dir yaml
#  ... yaml/section_*.yaml 의 text(필요시 marker) 작성 ...
python $SC/yaml2hwpx.py restore --hwpx 연구개발계획서.hwpx --yaml-dir yaml \
        --out 연구개발계획서_최종.hwpx --template template.yaml
```

## 의존성

- `python-hwpx`(순수 파이썬 hwpx 편집), `pyhwpx`(한컴 COM 자동화), `PyYAML`
- hwp→hwpx 변환 단계는 **한컴오피스가 설치된 Windows** 필요. 추출/원복/템플릿 단계는 한컴 불필요.

## 보안

실제 값이 채워진 hwpx/YAML은 개인정보를 포함할 수 있으므로 공개 저장소 커밋 금지.
빈 서식(템플릿)만 저장소에 둔다.
