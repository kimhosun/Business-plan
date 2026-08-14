#!/usr/bin/env python3
"""backend/doc_fill.py — 제반사항(구조화 입력)으로 '문서의 정형 표'를 자동 채운다.

대상 표(정부 R&D 연구개발계획서 KEIT 표준 서식):
  1) 표지(사업계획서 표지) 표      — 과제명·주관/공동기관·총괄책임자·연구개발기간·정부지원비
  2) 요약문 표(연구개발 목표 및 내용) — 최종목표+연차별 목표, 연차별 개발내용
  3) 3-3 기술개발팀 편성도 표       — 주관/공동 기관명·담당기술내용

표는 문서마다 좌표(sX/pY/tZ)가 달라질 수 있어 **셀 텍스트 시그니처로 표를 찾고**,
표 안에서는 KEIT 표준 서식의 (row,col) 좌표로 값 셀을 지정한다. 빈 값은 건너뛰어
템플릿 안내문/기존 셀을 훼손하지 않는다. 기록은 tables._spread + pipeline.merge_result_into_yaml
경로(→ cell_para 노드 text)라 [hwpx 빌드] 시 최종 문서 표 셀로 나온다.

빌드(build_project·section.hwpx) 직전에 apply(pid)를 호출한다(항상 최신 제반사항 반영, 멱등).
"""
from __future__ import annotations

import re
from collections import defaultdict

from . import pipeline, store, tables


# ── 표 탐색 / 셀 좌표 ─────────────────────────────────────────────────────────
def _index(pid: str) -> dict:
    return pipeline._all_nodes_by_path(pid)


def _find_table(index: dict, *needles: str) -> str | None:
    """모든 표를 셀 텍스트로 훑어, needles 를 '전부' 포함하는 표의 path 를 반환."""
    joined: dict[str, list[str]] = defaultdict(list)
    for p, n in index.items():
        if n.get("kind") == "cell_para":
            tp = re.sub(r"/r\d+/c\d+/p\d+$", "", p)
            joined[tp].append(n.get("text", "") or "")
    for tp, texts in joined.items():
        blob = " ".join(texts)
        if all(x in blob for x in needles):
            return tp
    return None


def _cellmap(index: dict, tpath: str) -> dict[tuple[int, int], list[str]]:
    """(row,col) → 그 셀의 문단 path 목록."""
    return {(c["row"], c["col"]): c["paths"] for c in tables._cells_of_table(index, tpath)}


def _put(edits: list, cm: dict, row: int, col: int, text) -> None:
    """(row,col) 값 셀에 text 를 기록(빈 값은 건너뜀). 여러 문단이면 줄 단위 분배."""
    if text is None:
        return
    s = str(text)
    if not s.strip():
        return
    paths = cm.get((row, col))
    if not paths:
        return
    edits.extend(tables._spread(s, paths))


def _clear(edits: list, cm: dict, row: int, col: int) -> None:
    """(row,col) 셀을 빈 칸으로(템플릿 예시 placeholder 제거용)."""
    for p in cm.get((row, col)) or []:
        edits.append({"path": p, "text": ""})


def _set_paras(edits: list, cm: dict, row: int, col: int, paras: list) -> None:
    """(row,col) 셀의 각 문단(p0,p1,…)을 paras 로 정확히 덮어쓴다(체크박스 셀 재작성용).

    셀 문단 수보다 paras 가 적으면 남는 문단은 그대로 두고, 많으면 마지막 문단에 합친다."""
    paths = cm.get((row, col)) or []
    if not paths:
        return
    n = len(paths)
    for i, p in enumerate(paths):
        if i < len(paras):
            txt = paras[i] if i < n - 1 else "\n".join(str(x) for x in paras[i:])
            edits.append({"path": p, "text": str(txt)})


# 체크박스 마커
_CHK, _UNC = "[ √ ]", "[  ]"


# ── 값 헬퍼 ──────────────────────────────────────────────────────────────────
def _num(s) -> int:
    d = re.sub(r"[^\d]", "", str(s or ""))
    return int(d) if d else 0


def _fmt(n: int) -> str:
    return f"{n:,}" if n else ""


def _pct(a: int, b: int) -> str:
    return f"{round(a / b * 100, 1)}%" if b else ""


# ── 기업유형별 매칭 비율(정부출연금→기관부담 현금/현물 산정) ──────────────────
# 정부지원연구개발비 / 총연구개발비 비율(기본값, 산업기술 R&D 통상 기준). 비영리류는 100%.
_GOV_RATIO = {"대기업": 0.50, "중견기업": 0.70, "중소기업": 0.80}
# 기관부담연구개발비 중 '현금' 비율(나머지는 현물). 영리기업 유형별.
_CASH_RATIO = {"대기업": 0.15, "중견기업": 0.13, "중소기업": 0.10}


def _funding_breakdown(gov_cash: int, org_type: str) -> dict:
    """정부출연금(=정부지원현금 A)과 기업유형 → 부담·합계 현금/현물 계산.

    영리기업: 총 E=A/정부지원율, 기관부담 D=E-A, 현금 B=D×현금율, 현물 C=D-B.
    비영리·대학·출연연·기타: 기관부담 0(전액 정부지원)."""
    A = max(0, int(gov_cash or 0))
    gr = _GOV_RATIO.get((org_type or "").strip())
    if not gr or A <= 0:
        return {"A": A, "B": 0, "C": 0, "D": 0, "cash": A, "inkind": 0, "E": A}
    E = round(A / gr)
    D = max(0, E - A)
    B = round(D * _CASH_RATIO.get((org_type or "").strip(), 0.10))
    C = max(0, D - B)
    return {"A": A, "B": B, "C": C, "D": D, "cash": A + B, "inkind": C, "E": A + B + C}


def _org_type_map(insts: list) -> dict:
    return {(i.get("name") or "").strip(): (i.get("type") or "").strip() for i in (insts or [])}


def _period_label(p: dict) -> str:
    """단계+차년도 → 라벨 '1단계 1차년도'(단계 없으면 차년도만). 정부출연금/요약 키와 일치."""
    st = (p.get("stage") or "").strip()
    yr = (p.get("year") or "").strip()
    if st and yr:
        return f"{st}단계 {yr}"
    return yr or st


def _period_total(periods: list) -> str:
    """연차별 기간 목록 → '첫 시작 ~ 마지막 끝' 요약 문자열."""
    rs = [(p.get("range") or "").strip() for p in (periods or []) if (p.get("range") or "").strip()]
    if not rs:
        return ""
    if len(rs) == 1:
        return rs[0]
    def _parts(r):
        return [x.strip() for x in re.split(r"\s*[~\-]\s*", r) if x.strip()]
    first, last = _parts(rs[0]), _parts(rs[-1])
    start = first[0] if first else ""
    end = last[-1] if last else ""
    return f"{start} ~ {end}" if start and end else rs[0]


def _main_org(insts: list) -> dict | None:
    for i in insts or []:
        if (i.get("role") or "") == "주관":
            return i
    return (insts or [None])[0]


def _coops(insts: list) -> list:
    return [i for i in (insts or []) if (i.get("role") or "") == "공동"]


# ── 표지 표 ──────────────────────────────────────────────────────────────────
def _fill_cover(pid: str, index: dict, ov: dict, edits: list) -> int:
    tp = _find_table(index, "연구개발과제명", "주관연구개발기관", "사업자등록번호")
    if not tp:
        return 0
    cm = _cellmap(index, tp)
    cov = ov.get("cover") or {}
    insts = ov.get("institutions") or []
    periods = ov.get("periods") or []
    funding = ov.get("funding") or []

    # ── 상단 선택(체크박스) 항목 ─────────────────────────────────────────────
    pt = (cov.get("proj_type") or "").strip()
    if pt:
        _set_paras(edits, cm, 0, 5, [f"{_CHK if pt == '일반형' else _UNC} 일반형", "(해당항목 체크)"])
        _set_paras(edits, cm, 0, 9, [f"{_CHK if pt == '통합형' else _UNC} 통합형(세부)"])
        _set_paras(edits, cm, 1, 9, [f"{_CHK if pt == '병렬형' else _UNC} 병렬형(세부)"])
    dt = (cov.get("doc_type") or "").strip()
    if dt:
        b = lambda v: _CHK if v == dt else _UNC  # noqa: E731
        _set_paras(edits, cm, 0, 17,
                   [f"{b('신청용')} 신청용 {b('협약용')} 협약용", f"{b('차단계')} 차단계 제출용"])
    sec = (cov.get("security") or "").strip()
    if sec:
        _set_paras(edits, cm, 1, 24,
                   [f"일반[{'√' if sec == '일반' else '  '}] 보안[{'√' if sec == '보안' else '  '}]"])
    selm = (cov.get("selection") or "").strip()
    if selm:
        m = lambda v: "√" if v == selm else "  "  # noqa: E731
        _set_paras(edits, cm, 7, 5,
                   [f" 정책지정[{m('정책지정')}] 지정공모[{m('지정공모')}]  "
                    f"품목지정[{m('품목지정')}]  자유공모[{m('자유공모')}]"])

    # ── 상단 텍스트 항목 ─────────────────────────────────────────────────────
    _put(edits, cm, 2, 5, cov.get("gov_dept"))     # 중앙행정기관명(기본 산업통상부)
    _put(edits, cm, 4, 5, cov.get("agency"))       # 전문기관명
    _put(edits, cm, 2, 22, cov.get("sub_biz"))     # 세부사업명
    _put(edits, cm, 3, 22, cov.get("detail_biz"))  # 내역사업명
    _put(edits, cm, 5, 5, cov.get("notice_no"))    # 공고번호
    _put(edits, cm, 5, 22, cov.get("master_no"))   # 총괄연구개발 과제번호
    _put(edits, cm, 6, 22, cov.get("task_no"))     # 연구개발 과제번호
    # 산업기술분류(1~3순위 명칭+비율)
    _put(edits, cm, 8, 5, cov.get("ind_class1"))
    _put(edits, cm, 8, 11, cov.get("ind_pct1"))
    _put(edits, cm, 8, 14, cov.get("ind_class2"))
    _put(edits, cm, 8, 20, cov.get("ind_pct2"))
    _put(edits, cm, 8, 22, cov.get("ind_class3"))
    _put(edits, cm, 8, 29, cov.get("ind_pct3"))
    # 국가과학기술분류
    _put(edits, cm, 9, 5, cov.get("nat_class1"))
    _put(edits, cm, 9, 11, cov.get("nat_pct1"))
    _put(edits, cm, 9, 14, cov.get("nat_class2"))
    _put(edits, cm, 9, 20, cov.get("nat_pct2"))
    _put(edits, cm, 9, 22, cov.get("nat_class3"))
    _put(edits, cm, 9, 29, cov.get("nat_pct3"))
    # 총괄연구개발과제명(국/영)
    _put(edits, cm, 10, 10, cov.get("master_title_ko"))
    _put(edits, cm, 11, 10, cov.get("master_title_en"))

    _put(edits, cm, 12, 10, cov.get("title_ko"))
    _put(edits, cm, 13, 10, cov.get("title_en"))

    main = _main_org(insts)
    if main:
        _put(edits, cm, 14, 10, main.get("name"))
        _put(edits, cm, 16, 26, main.get("type"))
        # 연구책임자 = 주관연구개발기관 책임자 (직장전화·국가연구자번호는 입력칸 제거로 미채움)
        _put(edits, cm, 17, 13, main.get("lead_name"))
        _put(edits, cm, 17, 26, main.get("lead_title"))
        _put(edits, cm, 18, 26, main.get("lead_mobile"))
        _put(edits, cm, 19, 13, main.get("lead_email"))
    _put(edits, cm, 14, 26, cov.get("biz_no"))
    _put(edits, cm, 15, 10, cov.get("address"))
    _put(edits, cm, 15, 26, cov.get("corp_no"))

    _put(edits, cm, 20, 13, _period_total(periods) or ov.get("period"))
    # 단계별 연구기간: 1단계 → r21~r24(1~4년차), 그 외 첫 단계(n단계) → r25~r26.
    _by_stage: dict[str, list] = defaultdict(list)
    for p in periods:
        _by_stage[(p.get("stage") or "").strip() or "1"].append(p)
    _stages = sorted(_by_stage.keys(), key=lambda s: (0, int(s)) if s.isdigit() else (1, 0))
    if _stages:
        for i, p in enumerate(_by_stage[_stages[0]][:4]):
            _put(edits, cm, 21 + i, 13, p.get("range"))
        if len(_stages) > 1:
            for i, p in enumerate(_by_stage[_stages[1]][:2]):
                _put(edits, cm, 25 + i, 13, p.get("range"))

    # 공동연구개발기관 (r39~r42): 기관명 c5, 책임자 c10, 직위 c13, 휴대전화 c16,
    #   전자우편 c21, 역할(비고) c25, 기관유형 c28
    coops = _coops(insts)
    for i, co in enumerate(coops[:4]):
        r = 39 + i
        _put(edits, cm, r, 5, co.get("name"))
        _put(edits, cm, r, 10, co.get("lead_name"))
        _put(edits, cm, r, 13, co.get("lead_title"))
        _put(edits, cm, r, 16, co.get("lead_mobile"))
        _put(edits, cm, r, 21, co.get("lead_email"))
        _put(edits, cm, r, 25, "공동")
        _put(edits, cm, r, 28, co.get("type"))

    # 연구개발과제 실무책임자 (r45~r47)
    _put(edits, cm, 45, 12, cov.get("pm_name"))
    _put(edits, cm, 45, 25, cov.get("pm_title"))
    _put(edits, cm, 46, 12, cov.get("pm_tel"))
    _put(edits, cm, 46, 25, cov.get("pm_mobile"))
    _put(edits, cm, 47, 12, cov.get("pm_email"))
    _put(edits, cm, 47, 25, cov.get("pm_researcher_no"))

    # 연구개발비 표(r31~r36). 열: c4=정부지원현금(A), c5=기관부담현금(B), c7=기관부담현물(C),
    #   c13=그외현금, c16=그외현물, c19=총현금, c23=총현물, c27=합계(E).
    #   정부출연금(그리드)=정부지원현금 → 기업유형별 매칭비율로 기관부담 현금/현물을 산정해 채운다.
    #   예시행(r31) placeholder 는 명시적으로 제거한다.
    tmap = _org_type_map(insts)
    ylabels = [_period_label(p) for p in periods]
    _ZERO = {"A": 0, "B": 0, "C": 0, "cash": 0, "inkind": 0, "E": 0}
    agg: dict[str, dict] = {y: dict(_ZERO) for y in ylabels}
    any_fund = False
    for f in funding:
        y = (f.get("year") or "").strip()
        A = _num(f.get("amount"))
        if not y or A <= 0:
            continue
        any_fund = True
        bd = _funding_breakdown(A, tmap.get((f.get("org") or "").strip(), ""))
        a = agg.setdefault(y, dict(_ZERO))
        for k in ("A", "B", "C", "cash", "inkind", "E"):
            a[k] += bd[k]
    if any_fund:
        for cc in (4, 5, 7, 13, 16, 19, 23, 27):  # 예시행 placeholder 제거
            _clear(edits, cm, 31, cc)
        tot = dict(_ZERO)
        for i, y in enumerate(ylabels[:5]):
            a = agg.get(y)
            row = 31 + i
            if a and a["E"] > 0:
                _put(edits, cm, row, 4, _fmt(a["A"]))
                _put(edits, cm, row, 5, _fmt(a["B"]))
                _put(edits, cm, row, 7, _fmt(a["C"]))
                _clear(edits, cm, row, 13)
                _clear(edits, cm, row, 16)
                _put(edits, cm, row, 19, _fmt(a["cash"]))
                _put(edits, cm, row, 23, _fmt(a["inkind"]))
                _put(edits, cm, row, 27, _fmt(a["E"]))
                for k in tot:
                    tot[k] += a[k]
        if tot["E"] > 0:
            _put(edits, cm, 36, 4, _fmt(tot["A"]))
            _put(edits, cm, 36, 5, _fmt(tot["B"]))
            _put(edits, cm, 36, 7, _fmt(tot["C"]))
            _clear(edits, cm, 36, 13)
            _clear(edits, cm, 36, 16)
            _put(edits, cm, 36, 19, _fmt(tot["cash"]))
            _put(edits, cm, 36, 23, _fmt(tot["inkind"]))
            _put(edits, cm, 36, 27, _fmt(tot["E"]))
    return 1


# ── 요약문 표(연구개발 목표 및 내용) ─────────────────────────────────────────
def _fill_summary(pid: str, index: dict, ov: dict, edits: list) -> int:
    tp = _find_table(index, "연구개발 목표", "국문핵심어")
    if not tp:
        return 0
    cm = _cellmap(index, tp)
    sm = ov.get("summary") or {}

    goal_lines: list[str] = []
    if (sm.get("goal_final") or "").strip():
        goal_lines += ["[최종목표]", "ㅇ " + sm["goal_final"].strip()]
    for g in (sm.get("goals") or []):
        yr = (g.get("year") or "").strip()
        tx = (g.get("text") or "").strip()
        if tx:
            goal_lines += [f"[{yr} 목표]" if yr else "[목표]", "ㅇ " + tx]
    if goal_lines:
        _put(edits, cm, 16, 7, "\n".join(goal_lines))

    con_lines: list[str] = []
    for c in (sm.get("contents") or []):
        yr = (c.get("year") or "").strip()
        tx = (c.get("text") or "").strip()
        if tx:
            con_lines += [f"[{yr} 개발내용]" if yr else "[개발내용]", "ㅇ " + tx]
    if con_lines:
        _put(edits, cm, 17, 7, "\n".join(con_lines))
    return 1


# ── 3-3 기술개발팀 편성도 표 ─────────────────────────────────────────────────
def _fill_team(pid: str, index: dict, ov: dict, edits: list) -> int:
    tp = _find_table(index, "주관연구개발기관명", "담당기술내용", "참 여 연 구 원")
    if not tp:
        return 0
    cm = _cellmap(index, tp)
    insts = ov.get("institutions") or []
    periods = ov.get("periods") or []
    period_str = _period_total(periods) or (ov.get("period") or "")

    main = _main_org(insts)
    if main:
        _put(edits, cm, 0, 2, main.get("name"))     # 주관기관명
        _put(edits, cm, 1, 6, main.get("duty"))     # 주관 담당기술내용

    # 공동 3블록: 이름/기간 → r5 (c0,c3,c6), 담당 기술개발 내용 → r12 동일 열
    cols = [0, 3, 6]
    for i, co in enumerate(_coops(insts)[:3]):
        col = cols[i]
        head = (co.get("name") or "").strip()
        if head and period_str:
            head = f"{head}\n(연구개발기간)\n{period_str}"
        _put(edits, cm, 5, col, head)
        _put(edits, cm, 12, col, co.get("duty"))
    return 1


# ── 8-1 지원·부담계획 표(단계/연차/기관별 정부지원·기관부담 현금·현물) ─────────
def _ratio_floor(a: int, b: int) -> str:
    """a/b 백분율을 소수 첫째자리 '내림'으로(작성요령: 소수 둘째자리에서 내림). 예 10.0%."""
    if not b:
        return ""
    return f"{int(a / b * 1000) / 10:.1f}%"


def _ratio_ae(a: int, b: int) -> str:
    """A/E 비율(정수 %)."""
    return f"{int(round(a / b * 100))}%" if b else ""


_BKEYS = ("A", "B", "C", "cash", "inkind", "E")


def _fill_budget_81(pid: str, index: dict, ov: dict, edits: list) -> int:
    tp = _find_table(index, "기관부담연구개발비", "비율(A/E)", "현금(A)")
    if not tp:
        return 0
    tcells = tables._cells_of_table(index, tp)
    cmap = {(c["row"], c["col"]): c["paths"] for c in tcells}
    info = {(c["row"], c["col"]): c for c in tcells}

    # 표의 '단계 그룹'(c0 anchor: 숫자 또는 'n') → (row_start, row_end)
    tbl_stages = sorted(
        (c["row"], c["row"] + c["rowspan"]) for c in tcells
        if c["col"] == 0 and re.fullmatch(r"(\d+|[nN])", (c["text"] or "").strip()))
    if not tbl_stages:
        return 0

    insts = ov.get("institutions") or []
    tmap = _org_type_map(insts)
    funding = ov.get("funding") or []
    rank = {}
    for i, inst in enumerate(insts):
        rank[(inst.get("name") or "").strip()] = (0 if (inst.get("role") == "주관") else 1, i)

    def fund_for(label: str):
        rows = []
        for f in funding:
            if (f.get("year") or "").strip() != label:
                continue
            org = (f.get("org") or "").strip()
            A = _num(f.get("amount"))
            if org and A > 0:
                rows.append((rank.get(org, (2, 99)), org, A))
        rows.sort()
        return [(org, A) for _, org, A in rows]

    # 제반사항 periods 를 단계별로 그룹화(단계 오름차순, 각 단계 안은 입력순)
    by_stage: dict[str, list] = defaultdict(list)
    for p in (ov.get("periods") or []):
        by_stage[(p.get("stage") or "").strip() or "1"].append(p)
    proj_stages = sorted(by_stage.items(),
                         key=lambda kv: int(kv[0]) if kv[0].isdigit() else 999)

    def _year_subgroups(rs, re_):
        return sorted((c["row"], c["row"] + c["rowspan"]) for c in tcells
                      if c["col"] == 1 and re.fullmatch(r"\d+", (c["text"] or "").strip())
                      and rs <= c["row"] < re_)

    def _slots(rs, re_):
        return sorted((c["row"], c["rowspan"]) for c in tcells
                      if c["col"] == 2 and rs <= c["row"] < re_)

    def _cell(row, col, val):
        # 0 이면 빈칸으로 명시(템플릿 예시값이 남지 않도록). 비영리는 부담·현물 0 → 빈칸.
        if val:
            _put(edits, cmap, row, col, _fmt(val))
        else:
            _clear(edits, cmap, row, col)

    def _put_row(srow, sspan, org, bd):
        _put(edits, cmap, srow, 2, org)
        _put(edits, cmap, srow, 3, tmap.get(org, ""))
        _put(edits, cmap, srow, 4, _fmt(bd["A"]))     # 정부현금 A>0
        _cell(srow, 5, bd["B"])                        # 기관부담 현금
        _cell(srow, 6, bd["C"])                        # 기관부담 현물
        _cell(srow, 7, bd["D"])                        # 부담 소계
        _put(edits, cmap, srow, 8, _fmt(bd["cash"]))   # 합계 현금(A+B)>0
        _cell(srow, 9, bd["inkind"])                   # 합계 현물(C)
        _put(edits, cmap, srow, 10, _fmt(bd["E"]))     # 합계 E>0
        if sspan >= 2 and (srow + 1, 4) in info:   # 비율행
            rr = srow + 1
            _set_paras(edits, cmap, rr, 4, [_ratio_ae(bd["A"], bd["E"])])
            _set_paras(edits, cmap, rr, 5, [_ratio_floor(bd["B"], bd["D"])])
            _set_paras(edits, cmap, rr, 6, [_ratio_floor(bd["C"], bd["D"])])
            _set_paras(edits, cmap, rr, 7, [_ratio_floor(bd["D"], bd["E"])])

    def _put_sum(row, agg):
        _put(edits, cmap, row, 4, _fmt(agg["A"]))
        _put(edits, cmap, row, 5, _fmt(agg["B"]))
        _put(edits, cmap, row, 6, _fmt(agg["C"]))
        _put(edits, cmap, row, 7, _fmt(agg["B"] + agg["C"]))
        _put(edits, cmap, row, 8, _fmt(agg["cash"]))
        _put(edits, cmap, row, 9, _fmt(agg["inkind"]))
        _put(edits, cmap, row, 10, _fmt(agg["E"]))

    filled = 0
    # 표 단계 그룹 ← 제반사항 단계(순서대로) 매핑
    for si, (rs, re_) in enumerate(tbl_stages):
        if si >= len(proj_stages):
            break
        stage_label, stage_periods = proj_stages[si]
        # 단계 라벨 갱신(표의 'n' 등 → 실제 단계번호)
        for c in tcells:
            if c["col"] == 0 and c["row"] == rs:
                _put(edits, cmap, rs, 0, stage_label)
                break
        stage_sub = {k: 0 for k in _BKEYS}
        ysubs = _year_subgroups(rs, re_)
        for yi, (yrs, yre) in enumerate(ysubs):
            if yi >= len(stage_periods):
                break
            p = stage_periods[yi]
            _put(edits, cmap, yrs, 1, (p.get("year") or "").replace("차년도", "").strip() or str(yi + 1))
            data = fund_for(_period_label(p))
            for oi, (srow, sspan) in enumerate(_slots(yrs, yre)):
                if oi >= len(data):
                    break
                org, A = data[oi]
                bd = _funding_breakdown(A, tmap.get(org, ""))
                _put_row(srow, sspan, org, bd)
                for k in _BKEYS:
                    stage_sub[k] += bd[k]
                filled += 1
        # 단계 소계
        for c in tcells:
            if c["col"] == 1 and (c["text"] or "").strip() == "소계" and rs <= c["row"] < re_:
                _put_sum(c["row"], stage_sub)
                break

    if not filled:
        return 0

    # 총계(전체 합 — 표지와 일치)
    grand = {k: 0 for k in _BKEYS}
    for f in funding:
        A = _num(f.get("amount"))
        if A > 0:
            bd = _funding_breakdown(A, tmap.get((f.get("org") or "").strip(), ""))
            for k in _BKEYS:
                grand[k] += bd[k]
    for c in tcells:
        if c["col"] == 0 and (c["text"] or "").strip() == "총계":
            _put_sum(c["row"], grand)
            break
    return 1


# ── 8장 비목별 사용계획 표: 연구개발비 총액(M) = 표지/요약 연차별 금액(합계 E) ──
def _find_tables(index: dict, *needles: str) -> list[str]:
    """needles 를 모두 포함하는 **모든** 표 path 를 문서 순서(s,p,t)로 반환."""
    joined: dict[str, list[str]] = defaultdict(list)
    for p, n in index.items():
        if n.get("kind") == "cell_para":
            tp = re.sub(r"/r\d+/c\d+/p\d+$", "", p)
            joined[tp].append(n.get("text", "") or "")
    out = [tp for tp, texts in joined.items() if all(x in " ".join(texts) for x in needles)]
    return sorted(out, key=lambda tp: tuple(int(x) for x in re.findall(r"\d+", tp)))


def _cal_year(rng) -> str:
    m = re.search(r"(19|20)\d\d", str(rng or ""))
    return m.group(0) if m else ""


def _ordered_insts(insts: list) -> list:
    """주관 먼저, 그 뒤 나머지(공동)를 입력순으로."""
    mains = [i for i in (insts or []) if (i.get("role") or "") == "주관"]
    others = [i for i in (insts or []) if (i.get("role") or "") != "주관"]
    return mains + others


def _budget_model(cells: list) -> dict | None:
    """비목 표(총괄/세부)의 열 모델을 추출한다.

    반환 {mrow, year_cols, total_col, stage_spans:[(라벨,[cols])], year_label:{col:row},
          cal:{col:row}}. '연구개발비 총액' 행과 상단 단계/연차 헤더로 유도한다."""
    mrow = None
    for c in cells:
        if "연구개발비 총액" in (c["text"] or ""):
            mrow = c["row"]
            break
    if mrow is None:
        return None
    val = sorted((c for c in cells if c["row"] == mrow and c["colspan"] == 1),
                 key=lambda c: c["col"])
    if len(val) < 2:
        return None
    year_cols = [c["col"] for c in val[:-1]]
    total_col = val[-1]["col"]
    stage_spans: list = []
    for c in cells:
        if c["row"] == 0:
            m = re.match(r"(\d+|[nN])\s*단계", (c["text"] or "").strip())
            if m:
                cols = [yc for yc in year_cols if c["col"] <= yc < c["col"] + c["colspan"]]
                if cols:
                    stage_spans.append((m.group(1), cols))
    if not stage_spans:
        stage_spans = [("1", year_cols)]
    year_label: dict[int, int] = {}
    cal: dict[int, int] = {}
    for c in cells:
        if c["col"] not in year_cols or c["colspan"] != 1:
            continue
        t = (c["text"] or "").strip()
        if re.fullmatch(r"(\d+|[nN])\s*차년도", t):
            year_label[c["col"]] = c["row"]
        elif t == "20xx":
            cal[c["col"]] = c["row"]
    return {"mrow": mrow, "year_cols": year_cols, "total_col": total_col,
            "stage_spans": stage_spans, "year_label": year_label, "cal": cal}


def _period_col_map(periods: list, stage_spans: list) -> list:
    """periods → 열 매핑 [(period, col)]. 다단계면 단계별, 단일단계면 평면 순서."""
    by_stage: dict[str, list] = defaultdict(list)
    for p in periods:
        by_stage[(p.get("stage") or "").strip() or "1"].append(p)
    proj = sorted(by_stage.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 999)
    if len(proj) > 1 and len(stage_spans) > 1:
        out = []
        for (_, ps), (_, cols) in zip(proj, stage_spans):
            out += list(zip(ps, cols))
        return out
    flat_p = [p for _, ps in proj for p in ps]
    flat_c = [col for _, cols in stage_spans for col in cols]
    return list(zip(flat_p, flat_c))


def _e_by_label(funding: list, tmap: dict, org_filter: str | None = None) -> dict:
    """연차라벨 → 합계 E(정부+기관부담) 합. org_filter 지정 시 그 기관만."""
    agg: dict[str, int] = defaultdict(int)
    for f in funding:
        org = (f.get("org") or "").strip()
        if org_filter is not None and org != org_filter:
            continue
        lbl = (f.get("year") or "").strip()
        A = _num(f.get("amount"))
        if not lbl or A <= 0:
            continue
        agg[lbl] += _funding_breakdown(A, tmap.get(org, ""))["E"]
    return agg


def _fill_bimok(cells: list, ov: dict, edits: list, org_filter: str | None) -> int:
    """비목 표 한 개의 M 행(연구개발비 총액)을 연차별 E 로 채우고, 연차/달력 헤더도 갱신."""
    model = _budget_model(cells)
    if not model:
        return 0
    cm = {(c["row"], c["col"]): c["paths"] for c in cells}
    tmap = _org_type_map(ov.get("institutions") or [])
    e_by = _e_by_label(ov.get("funding") or [], tmap, org_filter)
    mrow, total = model["mrow"], 0
    wrote = False
    for p, col in _period_col_map(ov.get("periods") or [], model["stage_spans"]):
        yr = (p.get("year") or "").strip()
        if yr and col in model["year_label"]:
            _set_paras(edits, cm, model["year_label"][col], col, [yr])
        cy = _cal_year(p.get("range"))
        if cy and col in model["cal"]:
            _set_paras(edits, cm, model["cal"][col], col, [cy])
        e = e_by.get(_period_label(p), 0)
        if e > 0:
            _put(edits, cm, mrow, col, _fmt(e))
            total += e
            wrote = True
    if wrote:
        _put(edits, cm, mrow, model["total_col"], _fmt(total))
    return 1 if wrote else 0


def usage_bimok_paths(pid: str, index: dict) -> list[str]:
    """8-2 절의 '비목별 사용계획 총괄표'(기관별, 26×11) path 를 문서순으로.

    앱이 아는 표(노드 8-2 의 table_paths)로만 한정한다(등록 안 된 중복 총괄표는 편집기와
    동일하게 무시). 시그니처('수정인건비'+'직접비 소계'+'연구개발비 총액')로 집계표
    (p672, '인건비 비율(E1/M)')·인건비/학생인건비/참고자료 하위표를 배제한다."""
    node = store.node_by_id(pid, "8-2") or {}
    out = []
    for tp in (node.get("table_paths") or []):
        blob = " ".join((c.get("text") or "")
                        for c in tables._cells_of_table(index, tp))
        if all(x in blob for x in ("수정인건비", "직접비 소계", "연구개발비 총액")):
            out.append(tp)
    return sorted(out, key=lambda tp: tuple(int(x) for x in re.findall(r"\d+", tp)))


def _fill_budget_82(pid: str, index: dict, ov: dict, edits: list) -> int:
    """8-2 연구개발비 사용계획:
    - 집계(전 기관 합) 총괄표: '인건비 비율(E1/M)' 시그니처, 전 기관 연차별 E 합.
    - 기관별 비목 총괄표(표1, 26×11): 등장순 ↔ 기관(주관 먼저) 매핑, 각 M 행 = 그 기관
      연차별 E(= /budget/sync-usage 로 표 개수를 기관 수에 맞춘 뒤 채움)."""
    filled = 0
    agg = _find_table(index, "인건비 비율(E1/M)", "직접비 소계", "연구개발비 총액")
    if agg:
        filled += _fill_bimok(tables._cells_of_table(index, agg), ov, edits, None)
    ordered = [i for i in _ordered_insts(ov.get("institutions") or [])
               if (i.get("name") or "").strip()]
    for i, tp in enumerate(usage_bimok_paths(pid, index)):
        if i >= len(ordered):
            break
        name = (ordered[i].get("name") or "").strip()
        filled += _fill_bimok(tables._cells_of_table(index, tp), ov, edits, name)
    return 1 if filled else 0


def _fill_budget_83(pid: str, index: dict, ov: dict, edits: list) -> int:
    """8-3 비목별 세부표(기관별): 등장순 표 ↔ 기관(주관먼저) 매핑, 각 M 행 = 그 기관 연차별 E."""
    tps = _find_tables(index, "수정인건비", "간접비 비율", "연구개발비 총액")
    if not tps:
        return 0
    # 이름 있는 기관만(주관 먼저) — 세부표 복제 개수(_sync_budget_detail)와 동일 기준으로 정렬 매핑.
    ordered = [i for i in _ordered_insts(ov.get("institutions") or [])
               if (i.get("name") or "").strip()]
    filled = 0
    for i, tp in enumerate(tps):
        if i >= len(ordered):
            break
        name = (ordered[i].get("name") or "").strip()
        filled += _fill_bimok(tables._cells_of_table(index, tp), ov, edits, name)
    return 1 if filled else 0


# ── 2-3 수행일정(간트) 표: 표지 연구기간(periods)으로 단계·연차 헤더 자동 갱신 ──
def _fill_schedule_23(pid: str, index: dict, ov: dict, edits: list) -> int:
    """2-3 '추진 일정' 간트표의 단계(N단계)·연차(N차년도) 머리글을 표지 연구기간에 맞춰 갱신.

    표지/요약문 입력의 periods(단계·차년도)를 단계별로 그룹화해, 표의 단계 블록(row1)과 그
    안의 연차 셀(row2)을 실제 단계·연차로 relabel 한다(남는 연차 칸은 비움). 구조는 바꾸지
    않고 텍스트만 갱신하며, 세부표('N단계-n차년도(개월)') 제목도 실제 기간으로 갱신한다."""
    periods = ov.get("periods") or []
    by_stage: dict[str, list] = defaultdict(list)
    for p in periods:
        by_stage[(p.get("stage") or "").strip() or "1"].append(p)
    proj_stages = sorted(by_stage.items(),
                         key=lambda kv: int(kv[0]) if kv[0].isdigit() else 999)
    if not proj_stages:
        return 0

    filled = 0
    # (1) 간트표: 시그니처 '추진 일정'+'일련'
    tp = _find_table(index, "추진 일정", "일련")
    if tp:
        cells = tables._cells_of_table(index, tp)
        cm = _cellmap(index, tp)
        stage_cells = sorted(
            (c for c in cells if c["row"] == 1 and "단계" in (c.get("text") or "")),
            key=lambda c: c["col"])
        for si, sc in enumerate(stage_cells):
            lo, hi = sc["col"], sc["col"] + int(sc.get("colspan", 1) or 1)
            year_cells = sorted(
                (c for c in cells if c["row"] == 2 and lo <= c["col"] < hi
                 and "차년도" in (c.get("text") or "")),
                key=lambda c: c["col"])
            if si < len(proj_stages):
                stage_label, ps = proj_stages[si]
                _put(edits, cm, 1, sc["col"], f"{stage_label}단계")
                for yi, yc in enumerate(year_cells):
                    if yi < len(ps):
                        _put(edits, cm, 2, yc["col"],
                             (ps[yi].get("year") or f"{yi + 1}차년도").strip())
                    else:
                        _clear(edits, cm, 2, yc["col"])   # 남는 연차 칸 비움
            else:  # 프로젝트 단계보다 많은 표의 단계 블록은 비운다
                _clear(edits, cm, 1, sc["col"])
                for yc in year_cells:
                    _clear(edits, cm, 2, yc["col"])
        filled = 1

    # (2) 세부표: '…단계-…차년도(개월)' 제목을 실제 기간으로(등장순 ↔ 연차순)
    flat = [p for _, ps in proj_stages for p in ps]
    detail_tps = _find_tables(index, "개월", "기간")
    di = 0
    for dtp in detail_tps:
        title = next((c for c in tables._cells_of_table(index, dtp)
                      if c["row"] == 0 and "개월" in (c.get("text") or "")), None)
        if not title or di >= len(flat):
            continue
        p = flat[di]
        lab = _period_label(p) or f"{di + 1}차년도"
        cy = _cal_year(p.get("range"))
        cm = _cellmap(index, dtp)
        _put(edits, cm, 0, title["col"], f"{lab}(개월)" + (f" [{cy}]" if cy else ""))
        di += 1
        filled = 1
    return filled


# ── 4-3 기술기여도 표(기관별 = 정부출연금/총연구개발비 비율, 전 연차 동일) ──────
def contrib_table_path(pid: str, index: dict) -> str | None:
    """4-3 '기술기여도' 표 path 를 4-3 노드에 등록된 표로 한정해 찾는다.

    다른 절·작성안내표의 동일 시그니처(1장 요약 내 중첩 복사본 등) 오탐을 막는다."""
    node = store.node_by_id(pid, "4-3") or {}
    for cand in (node.get("table_paths") or []):
        # 셀·문단 분리(예: '연구개발\n기관명')에 영향받지 않게 공백 제거 후 매칭.
        blob = re.sub(r"\s+", "", " ".join(
            (c.get("text") or "") for c in tables._cells_of_table(index, cand)))
        if "기술기여도" in blob and "매출액발생" in blob and "기관명" in blob:
            return cand
    return None


def contrib_data_rows(cells: list) -> list[int]:
    """기술기여도 표의 데이터(기관) 행 번호 목록(머리글·소계 제외)."""
    hdr_row = min((c["row"] for c in cells
                   if c["col"] >= 1 and int(c.get("colspan", 1) or 1) == 1), default=1)
    sum_rows = {c["row"] for c in cells if c["col"] == 0
                and re.search(r"(소?계|합\s*계)", c.get("text", "") or "")}
    return sorted(c["row"] for c in cells
                  if c["col"] == 0 and c["row"] > hdr_row and c["row"] not in sum_rows)


def _fill_contrib_43(pid: str, index: dict, ov: dict, edits: list) -> int:
    """4-3 '기술기여도' 표를 참여기관별로 채운다.

    기술기여도 = 정부출연금(A) / 총연구개발비(E) × 100 (협약 비율, 기술료 산정 계수).
    _funding_breakdown 이 산출한 A·E 를 쓴다 → 영리기업은 유형별 정부지원율(대 50·중견
    70·중소 80%), 비영리·대학·출연연 등은 기관부담이 없어(부담 0) 100%.
    표의 열은 '매출액발생 N년차'(기술료 대상 매출연차)로, 계수인 기술기여도는 연차와
    무관하게 일정하므로 1년차부터 모든 열에 같은 값을 기입한다."""
    tp = contrib_table_path(pid, index)
    if not tp:
        return 0
    cells = tables._cells_of_table(index, tp)
    cm = {(c["row"], c["col"]): c["paths"] for c in cells}

    # 값(연차) 열: '기술기여도' 병합 머리글 아래의 개별 연차 셀(col>=1, colspan 1)
    hdr_row = min((c["row"] for c in cells
                   if c["col"] >= 1 and int(c.get("colspan", 1) or 1) == 1), default=1)
    val_cols = sorted({c["col"] for c in cells if c["row"] == hdr_row and c["col"] >= 1})
    data_rows = contrib_data_rows(cells)   # 데이터(기관) 행 — 머리글·소계 제외
    if not val_cols or not data_rows:
        return 0

    insts = ov.get("institutions") or []
    tmap = _org_type_map(insts)
    # 기관별 A·E 합(전 차년도 합) — A/E 는 유형별 정부지원율로 일정.
    agg: dict[str, dict] = defaultdict(lambda: {"A": 0, "E": 0})
    for f in (ov.get("funding") or []):
        org = (f.get("org") or "").strip()
        A = _num(f.get("amount"))
        if not org or A <= 0:
            continue
        bd = _funding_breakdown(A, tmap.get(org, ""))
        agg[org]["A"] += bd["A"]
        agg[org]["E"] += bd["E"]

    ordered = [i for i in _ordered_insts(insts) if (i.get("name") or "").strip()]
    wrote = 0
    for i, row in enumerate(data_rows):
        if i >= len(ordered):        # 남는 템플릿 행(AAAAA/BBBBB…)의 예시값 제거
            _clear(edits, cm, row, 0)
            for cc in val_cols:
                _clear(edits, cm, row, cc)
            continue
        org = (ordered[i].get("name") or "").strip()
        _put(edits, cm, row, 0, org)
        a = agg.get(org)
        pct = f"{a['A'] / a['E'] * 100:.1f}" if a and a["E"] > 0 else ""
        for cc in val_cols:
            if pct:
                _put(edits, cm, row, cc, pct)
            else:
                _clear(edits, cm, row, cc)
        wrote = 1
    return wrote


# ── 공개 API ─────────────────────────────────────────────────────────────────
_FILLERS = (_fill_cover, _fill_summary, _fill_team, _fill_budget_81,
            _fill_budget_82, _fill_budget_83, _fill_schedule_23, _fill_contrib_43)


def apply(pid: str) -> dict:
    """제반사항으로 표지·요약문·편성도·연구개발비 표 셀을 채우고 yaml 에 병합. 통계 반환."""
    ov = store.read_overview_data(pid)
    index = _index(pid)
    edits: list[dict] = []
    filled = 0
    for fn in _FILLERS:
        try:
            filled += fn(pid, index, ov, edits)
        except Exception:  # noqa: BLE001 - 표 채움 실패가 빌드를 막지 않게
            continue
    if edits:
        pipeline.merge_result_into_yaml(pid, edits)
    return {"tables_filled": filled, "cells_written": len(edits)}


def preview(pid: str, ov: dict | None = None) -> list[dict]:
    """(테스트용) 실제 병합 없이 채울 edits 목록만 계산해 반환."""
    ov = ov if ov is not None else store.read_overview_data(pid)
    index = _index(pid)
    edits: list[dict] = []
    for fn in _FILLERS:
        fn(pid, index, ov, edits)
    return edits
