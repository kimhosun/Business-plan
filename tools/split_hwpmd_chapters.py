#!/usr/bin/env python3
"""Split the round-trip HWP Markdown into edit-safe chapter files.

The text between the hwp-source markers is copied byte-for-byte (UTF-8 text
wise) from the master Markdown.  Regulatory notes are kept outside that range,
so they cannot accidentally enter a reconstructed HWP body.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "연구개발계획서.md"
OUT_DIR = ROOT / "연구개발계획서_장별"
REVIEW_DATE = "2026-07-30"
BODY_BEGIN = "<!--@hwp-document-begin-->"
BODY_END = "<!--@hwp-document-end-->"
SOURCE_BEGIN = "<!--@hwp-source-begin-->"
SOURCE_END = "<!--@hwp-source-end-->"

LAW_INNOVATION = "https://www.law.go.kr/법령/국가연구개발혁신법"
DECREE_INNOVATION = "https://www.law.go.kr/법령/국가연구개발혁신법시행령"
RULE_INNOVATION = "https://www.law.go.kr/법령/국가연구개발혁신법시행규칙"
INDUSTRIAL_ACT = "https://www.law.go.kr/법령/산업기술혁신촉진법"
COMMON_RULE = (
    "https://www.law.go.kr/LSW/admRulInfoP.do?"
    "admRulSeq=2100000251982&chrClsCd=010201"
)
EVAL_GUIDE = (
    "https://law.go.kr/admRulLsInfoP.do?admRulSeq=2100000252016"
)
RND_COST = (
    "https://www.law.go.kr/LSW/admRulInfoP.do?"
    "admRulSeq=2100000278740&chrClsCd=010201"
)
SECURITY = (
    "https://law.go.kr/LSW/admRulInfoP.do?"
    "admRulSeq=2100000231472&chrClsCd=010201"
)
EQUIPMENT = (
    "https://www.law.go.kr/LSW/admRulInfoP.do?"
    "admRulSeq=2100000278230&chrClsCd=010201"
)
INDUSTRIAL_EQUIPMENT = (
    "https://law.go.kr/LSW/admRulInfoP.do?"
    "admRulSeq=2100000242382&chrClsCd=010201"
)
TECH_FEE = (
    "https://www.law.go.kr/LSW/admRulInfoP.do?"
    "admRulSeq=2100000257278&chrClsCd=010201"
)
PERFORMANCE_6 = (
    "https://www.kistep.re.kr/boardDownload.es?"
    "bid=0002&list_no=93091&seq=1"
)
IRIS_EVAL = (
    "https://www.iris.go.kr/contents/retrieveNoticeView.do?"
    "blbdId=00000001&blltSeq=170747"
)
IRIS = "https://www.iris.go.kr/"
RCMS = "https://www.rcms.go.kr/"


@dataclass(frozen=True)
class Ref:
    name: str
    point: str
    url: str


@dataclass(frozen=True)
class Part:
    filename: str
    title: str
    source_range: str
    start_node: str | None
    end_node: str | None
    references: tuple[Ref, ...]
    checks: tuple[str, ...]
    category: str


def r(name: str, point: str, url: str) -> Ref:
    return Ref(name, point, url)


GENERAL_REFS = (
    r(
        "국가연구개발혁신법·시행령·시행규칙",
        "법정 계획서 항목, 선정·협약·평가·성과·연구개발비의 상위 기준을 확인한다.",
        LAW_INNOVATION,
    ),
    r(
        "산업기술혁신사업 공통 운영요령",
        "KEIT 산업기술혁신사업의 신청, 협약, 변경, 평가 및 성과관리 특칙을 확인한다.",
        COMMON_RULE,
    ),
    r(
        "2026년도 산업기술혁신사업 통합 시행계획",
        "해당 내역사업의 지원목적·분야·기간을 확인하고 실제 세부공고·RFP 링크를 추가한다.",
        "https://www.motir.go.kr/kor/article/ATCLc01b2801b/70718/view",
    ),
)


PARTS: tuple[Part, ...] = (
    Part(
        "00_표지_및_과제개요.md",
        "표지 및 과제개요",
        "Section 0 전체",
        None,
        None,
        GENERAL_REFS,
        (
            "과제명·공고번호·기관명·연구책임자·기간·금액을 IRIS 입력값 및 협약안과 일치시킨다.",
            "기업규모, 연구개발기관 유형 및 공동기관 구분의 증빙 유효기간을 확인한다.",
            "변경 시 모든 장과 별첨에서 같은 식별정보를 함께 갱신한다.",
        ),
        "공통",
    ),
    Part(
        "00_요약문.md",
        "요약문",
        "Section 1 전체",
        None,
        None,
        (
            r(
                "국가연구개발혁신법 시행규칙 별지 제1호",
                "법정 연구개발계획서의 필드 의미와 순서를 유지한다.",
                RULE_INNOVATION,
            ),
            r(
                "2024 국가연구개발 과제평가 표준지침",
                "목표·지표·평가방법·판정기준이 요약문과 본문에서 동일하도록 작성한다.",
                IRIS_EVAL,
            ),
            r(
                "국가연구개발사업 표준 성과지표 6차",
                "과학·기술·경제·사회·인프라 성과를 SMART 지표로 요약한다.",
                PERFORMANCE_6,
            ),
        ),
        (
            "요약문의 수치·기간·TRL·성과지표가 제2장, 제4장, 제8장과 일치하는지 대조한다.",
            "기술개발 필요성, 최종목표, 수행방법, 활용방안이 각각 본문의 근거로 추적되는지 확인한다.",
            "분량 제한과 공개 가능한 정보 범위를 해당 공고에서 재확인한다.",
        ),
        "공통",
    ),
    Part(
        "00_본문_목차.md",
        "본문 목차",
        "S2.P0000..S2.P0057",
        "S2.P0000",
        "S2.P0058",
        GENERAL_REFS,
        (
            "최종 편집 후 HWP에서 실제 쪽수를 다시 계산해 목차 쪽수를 갱신한다.",
            "실제 본문에는 국제공동연구개발비 별첨이 있어 별첨 1~9 순서를 사용한다.",
            "제목·번호 변경 시 각 장 파일명과 복원 매니페스트 순서는 바꾸지 않는다.",
        ),
        "공통",
    ),
    Part(
        "00_본문_공통표지_및_작성안내.md",
        "본문 공통표지 및 작성안내",
        "S2.P0058..S2.P0064",
        "S2.P0058",
        "S2.P0065",
        (
            r(
                "국가연구개발혁신법 시행규칙",
                "계획서 법정 서식과 작성항목의 의미를 확인한다.",
                RULE_INNOVATION,
            ),
            r(
                "국가연구개발사업 보안대책",
                "AI·데이터·해외협력 내용의 공개범위와 보안등급을 사전에 판단한다.",
                SECURITY,
            ),
            r(
                "국가연구개발사업 표준 성과지표 6차",
                "전체 장에서 사용하는 성과지표의 정의·단위·근거를 통일한다.",
                PERFORMANCE_6,
            ),
        ),
        (
            "서식이 지정한 글꼴·크기·색상·삭제 금지 영역은 HWP 앵커 및 HTML 속성과 함께 보존한다.",
            "AI 활용 시 데이터 출처, 검증, 사람의 감독, 저작권·개인정보·보안 검토를 기록한다.",
            "해당 세부사업 공고와 RFP의 분량·첨부·평가기준을 최종 우선 적용한다.",
        ),
        "공통",
    ),
    Part(
        "01_연구개발과제의_필요성.md",
        "1. 연구개발과제의 필요성",
        "S2.P0065..S2.P0094",
        "S2.P0065",
        "S2.P0095",
        (
            r(
                "국가연구개발혁신법 제10조",
                "창의성·충실성, 연구자 역량, 파급효과, 활용 가능성 및 국가계획 부합성을 필요성의 근거로 삼는다.",
                LAW_INNOVATION,
            ),
            r(
                "산업기술혁신 촉진법 제5조·제11조",
                "산업·시장 문제, 기술개발 시급성, 국가 지원 필요성과 산업기술정책 연계를 제시한다.",
                INDUSTRIAL_ACT,
            ),
            r(
                "산업기술혁신사업 공통 운영요령",
                "과제유형과 사업 목적, 품목·RFP의 요구사항을 직접 연결한다.",
                COMMON_RULE,
            ),
            r(
                "2026년도 산업기술혁신사업 통합 시행계획",
                "지원 목적·분야·기간을 확인하고 실제 세부공고·RFP를 최종 기준으로 적용한다.",
                "https://www.motir.go.kr/kor/article/ATCLc01b2801b/70718/view",
            ),
            r(
                "제5차 과학기술기본계획(2023~2027)",
                "과제와 직접 대응하는 국가전략만 선별하여 기술·시장·공공수요의 공백과 연결한다.",
                "https://www.kistep.re.kr/reportDetail.es?mid=a10305030000&rpt_no=RES0220230107&rpt_tp=831-002",
            ),
        ),
        (
            "정책·산업 문제 → 기존 기술 한계 → 미해결 격차 → 정부지원 필요성 → RFP 정합성 순으로 논리를 연결한다.",
            "시장·기술 수치는 조사기관, 기준연도, 조사일, URL과 함께 제시한다.",
            "유사·중복 과제와의 차별성을 기술범위·성능·수요처·TRL 기준으로 설명한다.",
            "분야별 인허가·표준·탄소·환경 규제가 필요성에 미치는 영향을 조건부로 확인한다.",
        ),
        "장",
    ),
    Part(
        "02_연구개발과제의_목표_및_내용.md",
        "2. 연구개발과제의 목표 및 내용",
        "S2.P0095..S2.P0323",
        "S2.P0095",
        "S2.P0324",
        (
            r(
                "국가연구개발혁신법 제10조·제12조 및 시행령",
                "최종·단계·연차 목표를 단계평가, 최종평가 및 보고서 구조와 일치시킨다.",
                DECREE_INNOVATION,
            ),
            r(
                "국가연구개발혁신법 시행규칙 별지 제1호",
                "법정 계획서의 목표·내용 필드 의미와 순서를 유지한다.",
                RULE_INNOVATION,
            ),
            r(
                "2024 국가연구개발 과제평가 표준지침",
                "목표–지표–평가방법–평가환경–판정기준–증빙을 한 묶음으로 정의한다.",
                IRIS_EVAL,
            ),
            r(
                "국가연구개발사업 표준 성과지표 6차",
                "SMART 원칙과 5개 성과영역을 활용해 산출물 수보다 성능·품질·활용 결과 중심으로 설정한다.",
                PERFORMANCE_6,
            ),
            r(
                "국가연구개발사업 보안대책",
                "보안과제 여부와 공개 가능한 목표·내용의 범위를 판단한다.",
                SECURITY,
            ),
            r(
                "AI 관련 법률(조건부)",
                "AI가 연구대상·성과물인 경우 신뢰성, 안전성, 투명성, 데이터 권리, 사람의 감독과 고영향 AI 여부를 검토한다.",
                "https://www.law.go.kr/법령/인공지능발전과신뢰기반조성등에관한기본법",
            ),
        ),
        (
            "지표명·단위·기준값·국내외 최고수준과 기준일·연차별 목표·측정식·시험환경·증빙을 모두 둔다.",
            "세부 연구내용, WBS, 산출물, 일정, 담당기관, 예산이 서로 추적되도록 번호를 통일한다.",
            "TRL·핵심기술요소(CTE)의 시작·목표 수준과 판정 증빙을 명시한다.",
            "AI·개인정보·인체·화학·수출통제 등 조건부 규제의 적용 여부를 목표 단계에서 판정한다.",
        ),
        "장",
    ),
    Part(
        "03_연구개발과제의_추진전략_방법_및_추진체계.md",
        "3. 연구개발과제의 추진전략·방법 및 추진체계",
        "S2.P0324..S2.P0364",
        "S2.P0324",
        "S2.P0365",
        (
            r(
                "국가연구개발혁신법 및 시행령",
                "기관별 역할, 의사결정·변경관리, 평가 대응, 성과·자료·보안 책임을 구체화한다.",
                DECREE_INNOVATION,
            ),
            r(
                "산업기술혁신사업 공통 운영요령",
                "협약·변경·평가, 인력·신규채용, 성과관리 요구를 해당 공고와 맞춘다.",
                COMMON_RULE,
            ),
            r(
                "국가연구개발사업 동시수행 연구개발과제 수 제한 기준",
                "연구책임자와 참여연구자의 동시수행 과제 수 및 예외를 확인한다.",
                "https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000196149&chrClsCd=010201",
            ),
            r(
                "국가연구개발사업 연구노트 지침",
                "연구노트 작성·검토·서명·버전관리와 시험 원자료의 재현성 증빙 절차를 정한다.",
                "https://www.law.go.kr/행정규칙/국가연구개발사업연구노트지침",
            ),
            r(
                "국가연구개발사업 보안대책",
                "보안책임자, 접근권한, 외부·외국기관 접촉 및 보안사고 대응 역할을 배정한다.",
                SECURITY,
            ),
            r(
                "국가연구개발 시설·장비 관리 표준지침(조건부)",
                "장비의 중복성 검토부터 도입·검수·등록·공동활용·종료 후 활용까지 책임을 연결한다.",
                EQUIPMENT,
            ),
        ),
        (
            "기관별 세부업무–산출물–일정–권한–품질검증–데이터·보안 책임–리스크 대응을 한 표로 연결한다.",
            "의사결정, 변경승인, 진도·품질 게이트, 이슈 상향보고의 주기와 책임자를 명시한다.",
            "동시수행 과제 수, 참여기간, 실제 기여 가능 시간을 검증한다.",
            "신규·청년채용 조건은 공통 기준이 아니라 실제 세부공고의 의무와 대조한다.",
        ),
        "장",
    ),
    Part(
        "04_연구개발성과의_활용방안_및_기대효과.md",
        "4. 연구개발성과의 활용방안 및 기대효과",
        "S2.P0365..S2.P0393",
        "S2.P0365",
        "S2.P0394",
        (
            r(
                "국가연구개발혁신법 제16조~제18조 및 시행령",
                "성과 소유·공동지분·등록·기탁·공개·실시·기술료·연구자 보상 구조를 정의한다.",
                LAW_INNOVATION,
            ),
            r(
                "국가연구개발사업 등의 성과평가 및 성과관리에 관한 법률",
                "목표와 성과지표를 연결하고 종료 후 성과관리·활용·추적조사 계획을 둔다.",
                "https://www.law.go.kr/법령/국가연구개발사업등의성과평가및성과관리에관한법률",
            ),
            r(
                "연구개발성과 관리·유통 전담기관 지정 고시",
                "성과유형별 등록·기탁기관, 책임자와 제출시점을 정한다.",
                "https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000196755&chrClsCd=010201",
            ),
            r(
                "기술의 이전 및 사업화 촉진에 관한 법률",
                "기술이전 대상·방식, 가치평가, 수요기업 발굴, 실시·사업화 일정과 후속투자를 구체화한다.",
                "https://www.law.go.kr/법령/기술의이전및사업화촉진에관한법률",
            ),
            r(
                "기술료 징수 및 관리에 관한 통합요령",
                "정부납부기술료 대상, 기술기여도, 매출 전망, 보고·납부계획을 현행 기준으로 계산한다.",
                TECH_FEE,
            ),
            r(
                "국가연구개발사업 표준 성과지표 6차",
                "기대효과를 5개 성과영역으로 나누고 효과 실현을 확인할 지표·측정시점을 둔다.",
                PERFORMANCE_6,
            ),
        ),
        (
            "성과별 소유기관, 공동소유 지분, 출원·등록·기탁·공개 책임을 명시한다.",
            "활용주체, 수요처, 직접실시·이전·라이선스 경로와 연차별 성과를 연결한다.",
            "기대효과 수치는 기준값, 산식, 가정, 측정시점, 증빙자료를 남긴다.",
            "서식의 기술료 예시를 그대로 쓰지 말고 현행 통합요령과 실제 공고로 다시 계산한다.",
        ),
        "장",
    ),
    Part(
        "05_연구개발성과의_사업화_전략_및_계획.md",
        "5. 연구개발성과의 사업화 전략 및 계획",
        "S2.P0394..S2.P0483",
        "S2.P0394",
        "S2.P0484",
        (
            r(
                "국가연구개발혁신법 제16조~제18조 및 시행령",
                "성과 귀속, 실시·양도·사업화 방식, 기술료 처리와 참여기관 간 권리를 일치시킨다.",
                LAW_INNOVATION,
            ),
            r(
                "기술의 이전 및 사업화 촉진에 관한 법률",
                "이전 대상 권리, 사업화 주체, 실시지역·기간·대가와 가치평가 방식을 정한다.",
                "https://www.law.go.kr/법령/기술의이전및사업화촉진에관한법률",
            ),
            r(
                "발명진흥법",
                "직무발명 승계, 보상, 권리화 및 특허전략을 참여기관 내부규정과 연결한다.",
                "https://www.law.go.kr/법령/발명진흥법",
            ),
            r(
                "기술료 징수 및 관리에 관한 통합요령",
                "정부납부기술료 대상 여부, 매출·기술기여도 산정, 보고·납부계획을 사업화 매출과 연결한다.",
                TECH_FEE,
            ),
            r(
                "산업기술혁신사업 기술개발 평가관리지침",
                "사업화 가능성, 목표 달성, 성과 증빙을 연차별 시장진입 마일스톤으로 제시한다.",
                EVAL_GUIDE,
            ),
            r(
                "산업표준화법(조건부)",
                "표준·인증이 시장진입 조건이면 표준화·시험·인증 로드맵과 책임기관을 둔다.",
                "https://www.law.go.kr/법령/산업표준화법",
            ),
        ),
        (
            "시장규모·가격·점유율·매출의 자료원, 조사일, 산식과 가정을 명시한다.",
            "직접사업화·기술이전·라이선스·공동사업화 중 경로와 대체 경로를 구분한다.",
            "특허 FTO, 표준·인증·인허가, 생산·조달·투자·유통 일정을 하나의 로드맵으로 만든다.",
            "성과별 권리자·사업화주체·수익배분·기술료·실패위험 대응을 협약과 일치시킨다.",
        ),
        "장",
    ),
    Part(
        "06_연구개발_안전_및_보안조치_이행계획.md",
        "6. 연구개발 안전 및 보안조치 이행계획",
        "S2.P0484..S2.P0543",
        "S2.P0484",
        "S2.P0544",
        (
            r(
                "연구실 안전환경 조성에 관한 법률",
                "안전관리규정, 교육, 건강검진, 점검·진단, 보험, 사고보고·재발방지를 적용한다.",
                "https://www.law.go.kr/법령/연구실안전환경조성에관한법률",
            ),
            r(
                "연구실 안전점검 및 정밀안전진단에 관한 지침",
                "점검·정밀안전진단 대상과 주기, 기록, 개선조치 책임자를 정한다.",
                "https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000248134",
            ),
            r(
                "산업안전보건법",
                "위험성평가, 작업자 참여, 저감조치, 교육·기록 및 MSDS 관리를 반영한다.",
                "https://www.law.go.kr/법령/산업안전보건법",
            ),
            r(
                "국가연구개발사업 보안대책",
                "보안과제 분류, 보안책임자, 교육, 접근·반출 통제, 외국기관·외국인 관리와 사고보고를 정한다.",
                SECURITY,
            ),
            r(
                "산업기술의 유출방지 및 보호에 관한 법률",
                "산업기술·국가핵심기술 해당 여부, 해외이전 통제, 비밀유지와 보호조치를 검토한다.",
                "https://www.law.go.kr/법령/산업기술의유출방지및보호에관한법률",
            ),
            r(
                "국가핵심기술 지정 등에 관한 고시",
                "현행 별표와 과제기술을 대조하고 해당 시 해외공동연구·수출·M&A 통제를 반영한다.",
                "https://www.law.go.kr/admRulInfoP.do?admRulSeq=2100000272798&chrClsCd=010202&urlMode=admRulRvsInfoR",
            ),
        ),
        (
            "안전은 위험원–예방조치–점검주기–담당자–사고대응 순으로 관리한다.",
            "보안은 보호대상–등급–접근권한–저장·전송·반출–외부자–사고보고 순으로 관리한다.",
            "인체·개인정보·화학물질·생물체·고압가스 등 분야별 법령과 인허가를 조건부로 추가한다.",
            "외국기관·외국인, 클라우드, 생성형 AI, 해외 서버 사용 시 데이터 이전·보안·수출통제를 검토한다.",
        ),
        "장",
    ),
    Part(
        "07_연구개발기관_현황.md",
        "7. 연구개발기관 현황",
        "S2.P0544..S2.P0656",
        "S2.P0544",
        "S2.P0657",
        (
            r(
                "산업기술혁신사업 공통 운영요령",
                "신청자격, 참여제한, 재무요건, 기관·연구자 현황과 변경사항을 시스템 정보와 일치시킨다.",
                COMMON_RULE,
            ),
            r(
                "국가연구개발혁신법 시행령",
                "참여제한, 연구책임자·참여자 정보 및 동시수행 과제 수 제한을 확인한다.",
                DECREE_INNOVATION,
            ),
            r(
                "국가연구개발사업 동시수행 연구개발과제 수 제한 기준",
                "과제별 역할·기간·동시수행 수와 예외를 중복 없이 기재한다.",
                "https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000196149&chrClsCd=010201",
            ),
            r(
                "기업부설연구소와 연구개발전담부서 신고요령",
                "기업부설연구소·전담부서의 인력·공간·신고 및 사후관리 현황을 유효한 증빙과 맞춘다.",
                "https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000273808&chrClsCd=010201",
            ),
            r(
                "중소기업기본법·시행령",
                "평균매출액, 자산, 독립성 기준에 따른 기업규모와 유효한 확인서를 검증한다.",
                "https://www.law.go.kr/법령/중소기업기본법",
            ),
            r(
                "개인정보 보호법",
                "참여연구자 개인정보는 신청·협약 목적에 필요한 최소 범위로 수집·공유한다.",
                "https://www.law.go.kr/법령/개인정보보호법",
            ),
        ),
        (
            "기관·연구자 정보가 IRIS, 사업자등록, 기업확인서, 4대보험 및 결산서와 일치하는지 확인한다.",
            "매출·자산·고용·R&D 투자액의 기준연도와 재무제표 기준을 통일한다.",
            "최근 5년 수행실적·성과의 증빙번호, 기여기관, 중복성과 여부를 확인한다.",
            "연구시설·장비의 소유·설치 장소·공동활용 상태를 장비 별첨 및 예산과 일치시킨다.",
        ),
        "장",
    ),
    Part(
        "08_연구개발비_사용에_관한_계획.md",
        "8. 연구개발비 사용에 관한 계획",
        "S2.P0657..S2.P0749",
        "S2.P0657",
        "S2.P0750",
        (
            r(
                "국가연구개발혁신법 제13조 및 시행령",
                "정부지원금·기관부담금, 지급·사용·정산의 상위 기준을 적용한다.",
                DECREE_INNOVATION,
            ),
            r(
                "국가연구개발사업 연구개발비 사용 기준",
                "2026-05-06 시행 고시를 기준으로 사용용도, 증빙·검수, 장비, 외부전문기술, 영리기관 특례, 사전승인을 적용한다.",
                RND_COST,
            ),
            r(
                "산업기술혁신사업 공통 운영요령 별표 5",
                "산업기술과제의 항목별 사용용도·세부 산정, 현금·현물, 장비·외주·기술도입 특칙을 적용한다.",
                COMMON_RULE,
            ),
            r(
                "RCMS",
                "계좌·카드·이체·증빙·비목·거래처·일자를 일치시키고 상시점검·정산보완 체계를 둔다.",
                RCMS,
            ),
            r(
                "국가연구개발 시설·장비 관리 표준지침(조건부)",
                "장비비가 있으면 심의·중복성·등록·공동활용·처분 기준을 함께 적용한다.",
                EQUIPMENT,
            ),
        ),
        (
            "정부지원금 + 기관부담금 = 총연구개발비, 현금 + 현물 = 기관부담금을 검산한다.",
            "연차·기관·비목·재원별 합계와 세부 산출내역을 교차 검산한다.",
            "부가가치세 환급 가능액을 제외하고 계약·발주·검수·세금계산서·이체 증빙을 연결한다.",
            "사전승인 대상 변경은 집행 전에 전문기관 승인을 받도록 일정과 책임자를 둔다.",
        ),
        "장",
    ),
    Part(
        "별첨01_연구시설_장비_구입_또는_임차_활용계획서.md",
        "별첨 1. 연구시설·장비 구입 또는 임차 활용계획서",
        "S2.P0750..S2.P0755",
        "S2.P0750",
        "S2.P0756",
        (
            r(
                "국가연구개발 시설·장비의 관리 등에 관한 표준지침",
                "3천만원 이상 장비 심의, 1억원 이상 국가심의, ZEUS 중복성·공동활용, 등록·운영·처분을 확인한다.",
                EQUIPMENT,
            ),
            r(
                "산업기술개발장비 통합관리요령",
                "산업기술개발장비의 심의, i-Tube·ZEUS 등록, 취득·검수·공동활용·처분을 반영한다.",
                INDUSTRIAL_EQUIPMENT,
            ),
            r(
                "국가연구개발사업 연구개발비 사용 기준 제23조",
                "필요성, 사양, 수량, 견적, 중복장비, 도입·설치·검수, 활용률과 유지비를 기재한다.",
                RND_COST,
            ),
            r(
                "ZEUS 국가연구시설장비 종합정보시스템",
                "장비 중복성 검토, 등록 및 공동활용 가능성을 확인한다.",
                "https://www.zeus.go.kr/",
            ),
        ),
        (
            "부가세·설치부대비를 포함해 3천만원·1억원 심의기준 적용 여부를 판정한다.",
            "동일·유사 장비 보유 현황, 공동활용 가능성, 구매 대비 임차의 경제성을 제시한다.",
            "견적·도입·설치·검수 일정이 해당 단계 종료 전 허용 시점과 맞는지 확인한다.",
            "장비명·금액·연차가 제3장 추진계획과 제8장 예산에 동일하게 반영됐는지 검산한다.",
        ),
        "별첨",
    ),
    Part(
        "별첨02_시약_재료구입_및_활용계획서.md",
        "별첨 2. 시약·재료구입 및 활용계획서",
        "S2.P0756..S2.P0758",
        "S2.P0756",
        "S2.P0759",
        (
            r(
                "국가연구개발사업 연구개발비 사용 기준",
                "품명·규격·수량·단가·사용 세부과제·구매시기·견적 및 구매·입고·검수·사용기록을 연결한다.",
                RND_COST,
            ),
            r(
                "산업기술혁신사업 공통 운영요령 별표 5",
                "재료비 사용용도, 현물 산정 및 영리기관 자체 생산 재료의 인정기준을 확인한다.",
                COMMON_RULE,
            ),
            r(
                "산업안전보건법(화학물질 조건부)",
                "MSDS, 저장·취급조건, 보호구, 작업자 교육을 안전계획과 교차 반영한다.",
                "https://www.law.go.kr/법령/산업안전보건법",
            ),
            r(
                "폐기물관리법(조건부)",
                "폐시약·폐재료의 분류, 보관, 인계 및 적법한 처리계획을 확인한다.",
                "https://www.law.go.kr/법령/폐기물관리법",
            ),
        ),
        (
            "서식의 고액 단일품목 기준과 실제 공고의 제출기준을 함께 확인한다.",
            "수량·소모율·구매시기를 WBS와 시험 횟수로 산정하고 견적·부가세 근거를 둔다.",
            "입고·검수·재고·불출·사용·폐기 기록의 관리책임자를 정한다.",
            "위험물질은 제6장 안전계획과 저장·보호구·비상대응 내용을 일치시킨다.",
        ),
        "별첨",
    ),
    Part(
        "별첨03_외주_용역_활용계획서.md",
        "별첨 3. 외주 용역 활용계획서",
        "S2.P0759..S2.P0764",
        "S2.P0759",
        "S2.P0765",
        (
            r(
                "국가연구개발사업 연구개발비 사용 기준 제10조·제25조",
                "외부전문기술 활용의 사용용도, 한도, 초과승인 및 증빙요건을 확인한다.",
                RND_COST,
            ),
            r(
                "산업기술혁신사업 공통 운영요령 별표 5",
                "핵심 연구개발 공정·기술 자체가 아닌 제3자의 보조적 용역인지 확인한다.",
                COMMON_RULE,
            ),
            r(
                "국가연구개발사업 보안대책",
                "외주업체의 자료 접근, 비밀유지, 반출·복제·반환·폐기와 보안사고 책임을 계약에 넣는다.",
                SECURITY,
            ),
        ),
        (
            "서식상 1건 3천만원 이상 및 금액과 무관한 해외용역 작성대상 여부를 확인한다.",
            "업무범위, 산출물, 일정, 검수·합격기준, 금액 산정과 업체선정 근거를 명시한다.",
            "핵심기술 외주화 금지 여부와 내부 수행 대비 불가피성을 설명한다.",
            "IP 귀속, 비밀유지, 개인정보·보안, 재위탁, 자료반환·폐기 조항을 계약과 일치시킨다.",
        ),
        "별첨",
    ),
    Part(
        "별첨04_기술준비도_TRL_목표.md",
        "별첨 4. 기술준비도(TRL) 목표",
        "S2.P0765..S2.P0791",
        "S2.P0765",
        "S2.P0792",
        (
            r(
                "산업기술혁신사업 기술개발 평가관리지침",
                "핵심기술요소별 현재·목표 TRL, 단계 증빙자료와 검증환경을 목표평가와 연결한다.",
                EVAL_GUIDE,
            ),
            r(
                "KEIT 기술준비도(TRL) 안내",
                "해당 산업분야 TRL 정의와 시작·종료 수준의 판정기준을 확인한다.",
                "https://keit.re.kr/menu.es?mid=a20206010000",
            ),
            r(
                "KEIT SROME 공고의 과제명·TRL 작성 가이드",
                "해당 공고 첨부본의 TRL 정의가 있으면 그것을 우선 적용한다.",
                "https://srome.keit.re.kr/srome/biz/perform/opnnPrpsl/retrieveRndPlnnDtlView.do?prgmId=XPG201010000&sbjtPlnnAncmId=000878",
            ),
        ),
        (
            "핵심기술요소별 현재 TRL과 객관적 증빙, 목표 TRL과 판정기준을 구분한다.",
            "검증환경, 시험방법, 정량 합격기준, 예정시점, 책임기관을 명시한다.",
            "제2장의 최종·연차 목표 및 제3장의 WBS·게이트와 동일한 번호를 사용한다.",
            "공고·RFP가 별도 TRL 정의를 제시하면 본 별첨의 일반 예시보다 우선한다.",
        ),
        "별첨",
    ),
    Part(
        "별첨05_외부기술도입비_현물산정_신청서.md",
        "별첨 5. 외부기술도입비 현물산정 신청서",
        "S2.P0792..S2.P0793",
        "S2.P0792",
        "S2.P0794",
        (
            r(
                "국가연구개발사업 연구개발비 사용 기준 제68조",
                "과제 시작 전 도입기술의 실제 지급액, 인정비율, 도입완료 시점 등 영리기관 요건을 확인한다.",
                RND_COST,
            ),
            r(
                "산업기술혁신사업 공통 운영요령 별표 5",
                "평가 인정, 총액한도, 해외기술 특례, 현물 인정비율과 도입기한을 실제 공고와 재검증한다.",
                COMMON_RULE,
            ),
            r(
                "기술의 이전 및 사업화 촉진에 관한 법률",
                "기술이전·실시권 계약, 권리범위, 대가와 가치평가의 근거를 확인한다.",
                "https://www.law.go.kr/법령/기술의이전및사업화촉진에관한법률",
            ),
        ),
        (
            "계약서, 지급증빙, 권리범위·기간, 도입완료일, 평가·가치산정 자료를 준비한다.",
            "과제 직접 필요성과 국내 보유기술 여부, 도입기술의 세부 활용계획을 연결한다.",
            "금액·비율·도입기한은 현행 별표와 세부공고를 기준으로 신청 직전에 재검증한다.",
            "신청서 제출만으로 현물 인정이 확정되는 것은 아니며 평가·승인 결과를 반영한다.",
        ),
        "별첨",
    ),
    Part(
        "별첨06_영리기관_연구실운영비_활용관리계획.md",
        "별첨 6. 영리기관의 연구실운영비 활용·관리 계획",
        "S2.P0794..S2.P0795",
        "S2.P0794",
        "S2.P0796",
        (
            r(
                "국가연구개발사업 연구개발비 사용 기준 제68조·제73조",
                "영리기관 허용 품목, 협약 시 제출대상과 총액·품목·수량 변경의 사전승인 여부를 확인한다.",
                RND_COST,
            ),
            r(
                "산업기술혁신사업 공통 운영요령 별표 5",
                "산업기술과제의 연구실운영비 사용용도와 세부 산정 특칙을 적용한다.",
                COMMON_RULE,
            ),
            r(
                "RCMS",
                "세부계획, 거래, 증빙, 사용장소 및 관리책임자를 RCMS 집행자료와 일치시킨다.",
                RCMS,
            ),
        ),
        (
            "품목·수량·단가·필요성·사용장소·관리담당자를 제8장 금액과 일치시킨다.",
            "연구개발 직접 관련성, 기관 공통운영경비와의 구분, 사적·범용 사용 배제를 설명한다.",
            "품목·수량·총액 변경 시 집행 전 승인·통보 대상을 확인한다.",
            "자산·소모품 구분, 검수, 사용자, 보관·폐기 기록을 관리한다.",
        ),
        "별첨",
    ),
    Part(
        "별첨07_신규_참여연구자_채용예정_확인서.md",
        "별첨 7. 영리기관 신규 참여연구자 채용(예정) 확인서",
        "S2.P0796..S2.P0798",
        "S2.P0796",
        "S2.P0799",
        (
            r(
                "산업기술혁신사업 공통 운영요령",
                "신규 참여연구자 정보, 채용일, 참여기간·기여, 현금 인건비를 본문·예산과 일치시킨다.",
                COMMON_RULE,
            ),
            r(
                "국가연구개발사업 연구개발비 사용 기준",
                "영리기관 현금 인건비 계상 및 지급·증빙 요건을 확인한다.",
                RND_COST,
            ),
            r(
                "근로기준법",
                "근로계약, 임금, 근로조건과 채용관계의 실재성을 확인한다.",
                "https://www.law.go.kr/법령/근로기준법",
            ),
            r(
                "개인정보 보호법",
                "채용예정자 정보와 증빙은 신청·협약 목적에 필요한 최소 범위로 처리한다.",
                "https://www.law.go.kr/법령/개인정보보호법",
            ),
        ),
        (
            "성명·채용예정일·실제채용일·역할·참여기간·인건비를 제7장과 제8장에 일치시킨다.",
            "근로계약, 4대보험, 급여대장, 원천징수, 계좌이체 증빙을 보관한다.",
            "예정자 변경 시 세부공고·협약의 통보 또는 승인 절차를 따른다.",
            "청년의무채용 조건은 사업별로 다르므로 실제 세부공고에서 인원·기간·예외를 확인한다.",
        ),
        "별첨",
    ),
    Part(
        "별첨08_국제공동연구개발비_활용관리계획.md",
        "별첨 8. 국제공동연구개발비 활용·관리 계획",
        "S2.P0799..S2.P0801",
        "S2.P0799",
        "S2.P0802",
        (
            r(
                "국가연구개발혁신법 및 시행령",
                "외국기관의 역할, 협약, 성과 소유·활용과 연구개발비 지급의 상위 기준을 적용한다.",
                DECREE_INNOVATION,
            ),
            r(
                "국가연구개발사업 연구개발비 사용 기준",
                "국제공동연구개발비의 사용용도, 지급·정산·증빙과 사전승인 요건을 확인한다.",
                RND_COST,
            ),
            r(
                "국가연구개발사업 보안대책",
                "외국기관·외국인 참여, 자료접근·국외이전, 공개·반출과 보안사고 대응을 계약에 반영한다.",
                SECURITY,
            ),
            r(
                "외국환거래법(조건부)",
                "국외 송금·수령, 외화환산 및 신고 대상 여부를 재무부서와 확인한다.",
                "https://www.law.go.kr/법령/외국환거래법",
            ),
        ),
        (
            "외국기관 법적 지위, 담당자, 세부역할, 산출물, 지급일정·조건과 검수기준을 명시한다.",
            "IP·데이터·배경기술·논문·공개·분쟁·준거법·환율·세금 조건을 계약과 일치시킨다.",
            "국가핵심기술·수출통제·개인정보·보안등급에 따른 승인·반출 제한을 확인한다.",
            "제3장 역할, 제6장 보안, 제8장 예산과 국제공동연구개발비 금액을 교차 검산한다.",
        ),
        "별첨",
    ),
    Part(
        "별첨09_평가의견_수정보완_대비표.md",
        "별첨 9. 평가의견에 대한 수정·보완 대비표",
        "S2.P0802..S2.P0804",
        "S2.P0802",
        None,
        (
            r(
                "산업기술혁신사업 기술개발 평가관리지침",
                "선정평가·협약 단계의 수정·보완 요구와 처리절차에 따라 의견별 조치를 추적한다.",
                EVAL_GUIDE,
            ),
            r(
                "산업기술혁신사업 공통 운영요령",
                "평가결과 통보, 협약 체결, 계획서 변경과 전문기관 승인 범위를 확인한다.",
                COMMON_RULE,
            ),
            r(
                "해당 과제 평가결과 통보문·협약 요청문",
                "평가의견 원문, 의무·권고 구분, 제출기한과 승인조건의 직접 근거로 첨부한다.",
                IRIS,
            ),
        ),
        (
            "평가의견을 축약하지 말고 원문별로 조치구분·수정 전·수정 후·반영위치·증빙을 기록한다.",
            "미반영은 기술적·규정상 근거와 대체조치, 전문기관 협의결과를 남긴다.",
            "예산·목표·일정 변경은 본문, 요약문, 모든 관련 별첨에 동시에 반영한다.",
            "목차는 별첨 8개로 보이지만 실제 본문은 국제공동연구개발비를 포함한 별첨 1~9임을 유지한다.",
        ),
        "별첨",
    ),
)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def anchor_start(body: str, node: str) -> int:
    marker = f"<!--@hwp node={node} "
    marker_at = body.find(marker)
    if marker_at < 0:
        raise ValueError(f"missing top-level anchor: {node}")
    prefix = body[:marker_at]
    page_pattern = re.compile(
        rf"<!--@hwp page-break before={re.escape(node)} explicit=\"true\"-->\r?\n?$"
    )
    page_match = page_pattern.search(prefix)
    if page_match:
        start = page_match.start()
        if start > 0 and body[start - 1] == "\n":
            start -= 1
        return start
    return marker_at


def split_fragments(body: str) -> list[tuple[Part, str]]:
    section_1 = body.find("## Section 1:")
    section_2 = body.find("## Section 2:")
    if not (0 < section_1 < section_2):
        raise ValueError("cannot locate Section 0/1/2 boundaries")

    starts: list[int] = [0, section_1, section_2]
    for part in PARTS[3:]:
        if part.start_node is None:
            raise ValueError(f"missing start node for {part.filename}")
        starts.append(anchor_start(body, part.start_node))
    if len(starts) != len(PARTS):
        raise AssertionError("part boundary count mismatch")
    if starts != sorted(starts) or len(starts) != len(set(starts)):
        raise ValueError("part boundaries are not strictly increasing")

    result: list[tuple[Part, str]] = []
    for i, part in enumerate(PARTS):
        end = starts[i + 1] if i + 1 < len(starts) else len(body)
        fragment = body[starts[i] : end]
        result.append((part, fragment))
    if "".join(fragment for _, fragment in result) != body:
        raise AssertionError("split fragments do not reconstruct the body exactly")
    return result


def reference_markdown(part: Part) -> str:
    rows = [
        "## 국내 규정·지침·가이드라인 참조",
        "",
        f"> 확인 기준일: {REVIEW_DATE}. 적용 우선순위는 `해당 세부사업 공고·RFP·협약 → 소관부처·전문기관 최신 규정 → 일반 가이드`입니다. "
        "금액·비율·기한·서식은 개정 가능성이 있으므로 제출 직전에 공식 원문을 다시 확인하세요.",
        "",
        "| 규정·지침 | 이 파일에 반영할 사항 | 공식 원문 |",
        "|---|---|---|",
    ]
    for ref in part.references:
        rows.append(f"| {ref.name} | {ref.point} | [공식 링크]({ref.url}) |")
    rows.extend(
        [
            "",
            "### 작성 점검사항",
            "",
            *[f"- {check}" for check in part.checks],
            "",
            "### 과제별 추가 확인",
            "",
            "- `[해당 세부사업 공고/RFP 직접 링크 삽입]` — 이 자리에는 실제 신청 과제의 공고, 품목요약서, RFP, 협약 특수조건 링크를 넣으세요.",
            "- 제품·공정 분야에 따라 인허가, 시험·인증, 표준, 환경, 안전, 개인정보, 생명윤리, 수출통제 규정을 추가하세요.",
        ]
    )
    return "\n".join(rows)


def render_part(part: Part, fragment: str, master_hash: str) -> str:
    fragment_hash = sha256_text(fragment)
    header = "\n".join(
        [
            "---",
            'split_hwpmd: "1.0"',
            'source_hwpmd: "../연구개발계획서.md"',
            f'source_sha256: "{master_hash}"',
            f'source_range: "{part.source_range}"',
            f'source_fragment_sha256: "{fragment_hash}"',
            f'category: "{part.category}"',
            f'regulatory_reviewed: "{REVIEW_DATE}"',
            'restoration: "anchor-overlay-to-source"',
            "---",
            "",
            f"# {part.title}",
            "",
            "> 편집 시 `<!--@hwp ...-->` 앵커, `data-hwp-*`, `rowspan`, `colspan`과 HWP 제어 주석을 보존하세요. "
            "아래 `hwp-source` 구간만 복원 대상이며, 규정 참조 절은 HWP 본문에 병합되지 않습니다.",
            "",
            "## 원문 양식",
            "",
            SOURCE_BEGIN,
            "",
        ]
    )
    footer = "\n".join(
        [
            SOURCE_END,
            "",
            reference_markdown(part),
            "",
        ]
    )
    return header + fragment + footer


def make_readme(manifest: dict) -> str:
    lines = [
        "# 연구개발계획서 장별 Markdown",
        "",
        f"- 생성 기준일: {REVIEW_DATE}",
        "- 원본: `../연구개발계획서.hwp`",
        "- 복원 기준 마스터: `../연구개발계획서.md`",
        f"- 마스터 SHA-256: `{manifest['source_sha256']}`",
        "- 분할 원칙: 최상위 HWP 문단 앵커와 명시적 쪽 나눔을 함께 보존하며 표 내부에서는 분할하지 않음",
        "",
        "## 편집·복원 원칙",
        "",
        "1. 각 파일의 `<!--@hwp-source-begin-->`과 `<!--@hwp-source-end-->` 사이에서 본문을 편집합니다.",
        "2. `<!--@hwp ...-->`, `data-hwp-*`, 표의 `rowspan`·`colspan` 및 제어 주석은 삭제하거나 이름을 바꾸지 않습니다.",
        "3. 각 파일 뒤의 규정 참조 절은 조사·작성용 주석이며 HWP 본문 복원 대상이 아닙니다.",
        "4. `python .\\tools\\merge_hwpmd_chapters.py`를 실행하면 장별 원문 구간을 마스터 구조에 재병합합니다.",
        "5. 무편집 원본 HWP의 바이트 단위 복원은 `python .\\tools\\hwpmd_tool.py restore-original --input .\\연구개발계획서.md --output .\\복원본.hwp`로 검증할 수 있습니다.",
        "6. 편집된 재병합 MD는 앵커 기반 HWP 오버레이 입력으로 사용합니다. 한글에서 다시 저장하면 레이아웃은 보존 대상이지만 파일 바이트 동일성은 목표가 아닙니다.",
        "",
        "## 파일 목록",
        "",
        "| 구분 | 파일 | 원본 범위 |",
        "|---|---|---|",
    ]
    for item in manifest["parts"]:
        lines.append(
            f"| {item['category']} | [{item['title']}]({item['filename']}) | `{item['source_range']}` |"
        )
    lines.extend(
        [
            "",
            "## 원본 목차와 실제 본문의 차이",
            "",
            "원본 목차에는 별첨 8개만 보이지만 실제 본문에는 `별첨 8. 국제공동연구개발비 활용·관리 계획`이 추가되어 있으며, "
            "`평가의견에 대한 수정·보완 대비표`는 실제로 별첨 9입니다. 이 디렉터리는 복원 손실을 막기 위해 실제 본문 순서인 별첨 1~9를 사용합니다.",
            "",
            "## 규정 적용 주의",
            "",
            f"규정 링크는 {REVIEW_DATE}에 국가법령정보센터, 산업통상부, IRIS, KISTEP, KEIT 등 공식 출처에서 확인했습니다. "
            "현재 서식은 KEIT 산업기술혁신사업 체계이므로 다른 전문기관 규정을 혼용하지 말고, 실제 세부사업 공고·RFP·협약의 특칙을 최우선 적용하세요.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    master = MASTER.read_text(encoding="utf-8")
    if master.count(BODY_BEGIN) != 1 or master.count(BODY_END) != 1:
        raise ValueError("master must contain exactly one HWP document body")
    body_start = master.index(BODY_BEGIN) + len(BODY_BEGIN)
    body_end = master.index(BODY_END, body_start)
    body = master[body_start:body_end]
    master_hash = sha256_text(master)
    fragments = split_fragments(body)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_parts: list[dict] = []
    for part, fragment in fragments:
        output = OUT_DIR / part.filename
        output.write_text(
            render_part(part, fragment, master_hash), encoding="utf-8", newline=""
        )
        top_nodes = re.findall(
            r"(?m)^<!--@hwp node=(S\d+\.P\d{4}) pid=", fragment
        )
        manifest_parts.append(
            {
                "filename": part.filename,
                "title": part.title,
                "category": part.category,
                "source_range": part.source_range,
                "start_node": part.start_node,
                "end_node_exclusive": part.end_node,
                "fragment_sha256": sha256_text(fragment),
                "fragment_chars": len(fragment),
                "top_level_nodes": len(top_nodes),
                "reference_count": len(part.references),
                "regulatory_reviewed": REVIEW_DATE,
            }
        )

    manifest = {
        "format": "split-hwpmd-manifest",
        "version": 1,
        "source_file": "../연구개발계획서.md",
        "source_sha256": master_hash,
        "source_body_sha256": sha256_text(body),
        "source_body_chars": len(body),
        "body_begin_marker": BODY_BEGIN,
        "body_end_marker": BODY_END,
        "source_begin_marker": SOURCE_BEGIN,
        "source_end_marker": SOURCE_END,
        "regulatory_reviewed": REVIEW_DATE,
        "parts": manifest_parts,
    }
    (OUT_DIR / "_복원_매니페스트.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    (OUT_DIR / "README.md").write_text(
        make_readme(manifest), encoding="utf-8", newline=""
    )

    print(f"created {len(fragments)} split Markdown files in {OUT_DIR}")
    print(f"master sha256: {master_hash}")
    print(f"body sha256:   {manifest['source_body_sha256']}")


if __name__ == "__main__":
    main()
