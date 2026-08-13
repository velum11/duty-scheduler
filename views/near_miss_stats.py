"""아차사고(near-miss) 분석 — DESIGN.md §1-F 분석형(지표 6 + 분포 4블록).

DESIGN.md §1-F: 지표 6개(좌측 2px 보더 + 26px 모노 숫자, 제목 바로 아래 1행) →
분포 4블록(등급별·상태별·발생원인별·월별 추이). 각 블록 = 제목 + `76px 라벨 / 8px 바 /
52px 수치` 그리드, 카테고리 단색(등급 오렌지·상태 초록·원인 황토·추이 파랑). 저장/평가
액션은 이 화면의 책임이 아니다 — 순수 집계 조회다.

지표 타일은 **라벨+값 2줄**이다(영문 오버라인 없음 — near-miss 4화면 공통, `erp.metric_strip`
와 동일 어휘). 누적·당월 두 행은 **같은 그리드 트랙**을 공유해 카드 폭이 동일하고, 지표가
적은 행은 늘어나지 않고 남는 칸을 비운다.

년월 지정(기본=당월) + 두 관점: **해당월 말까지 누적**과 **당월 실적**. 파사드 신설 없이
``get_near_miss_reports({})`` 로 회사 전체 보고서를 1회 조회하고 년월 기준으로 UI 단에서
누적/당월을 슬라이스해 count 집계한다(코디 결정 B-1 — facade 신설 없음). count 키 계약은
``_aggregate_near_miss`` 와 동일(grade=confirmed_grade|미확정·status·cause·period=YYYY-MM).
등급·상태·원인 분포는 당월 기준, 월별 추이는 누적 관점이며 조회 스코프(전 사용자·회사 전체)는
불변이다.
"""
from __future__ import annotations

# DESIGN.md §0 화면 유형 규약 — 대시보드형(§1-F 분석형은 DASHBOARD 아키타입의 분석 변형).
SCREEN_ARCHETYPE = "DASHBOARD"

import calendar
from datetime import date
from html import escape

import streamlit as st

from modules import db, ui
from views.common import erp
from views.common import scaffold
from views.master.lifecycle import Readiness, ReadinessState

_PAGE_ID = "near_miss_stats"

_STATUS_LABEL = {
    "SUBMITTED": "제출", "IN_REVIEW": "검토중", "EVALUATED": "평가완료",
    "CLOSED": "종결", "REJECTED": "반려",
}
_CAUSE_LABEL = {
    "JAM": "끼임", "FALL": "추락", "DROP": "낙하", "HIT": "충돌",
    "SLIP": "미끄러짐", "BURN": "화상", "PINCH": "협착", "ETC": "기타",
}

# ── §2 팔레트 리터럴(§1-F 분석 계층은 정확 색 규정 — 도메인 legacy 토큰 대신 §2 직접 사용) ──
_INK = "#1c1a17"          # 본문 텍스트
_INK2 = "#4a453d"         # 보조 텍스트(라벨)
_LINE = "#e6e2da"         # 행 헤어라인 / 바 트랙
_LINE_STRONG = "#cfc8bd"  # 블록 상단 구분선
_LINE_SEC = "#e0dbd2"     # 지표 좌측 보더(기본)
_ACCENT = "#c2410c"       # 액센트 보더(강조 지표)
_ACCENT_TEXT = "#b4451a"  # 액센트 값 텍스트
# Codex P1: 작은 의미 텍스트(축 라벨·캡션·오버라인)는 #a09a90 금지 — #6b665d(5.1:1) 이상.
_MUT = "#6b665d"          # 지표 라벨·단위·note·차트 meta·비중 캡션
# 모노 폰트는 인라인으로 못박는다 — 전역 `.stApp [data-testid=stMarkdownContainer] *`(특이도
# 0,2,0)가 클래스 규칙(0,1,0)을 덮어 숫자가 sans 로 떨어지므로, 인라인(최상위)으로 강제한다.
_MONO = "font-family:'IBM Plex Mono',monospace;"
# 분포 카테고리 단색(§1-F): 등급 오렌지·상태 초록·원인 황토·추이 파랑.
_C_GRADE = "#c2410c"
_C_STATUS = "#2f6b45"
_C_CAUSE = "#8a6212"
_C_TREND = "#2f4d99"


def render(user: dict) -> None:
    # §1-F: 헤더 중립 프레임만(아이콘 밴드 제거 — §0-3 본문 아이콘 띠 금지). badges 는
    # screen_frame 기본(scaffold.mode_badge — 헤더 우측 연결 pill, DESIGN §4). 조회조건이
    # 없는 회사 전체 집계라 인페이지 필터 줄·새로고침 위젯을 두지 않는다(모든 상호작용이
    # rerun → 집계 재호출).
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="아차사고 분석",
        desc="아차사고 등급·상태·발생원인·월별 추이를 분석합니다.",
        breadcrumb="아차사고 › 아차사고 분석",
    )
    _inject_style()

    # 접근 범위(제품 결정): 아차사고 분석은 전 사용자에게 열려 있고 회사 전체 범위다
    # (filters 비움 — 스코프 불변).
    _readiness().banner()

    # 회사 전체 보고서를 1회 조회하고(facade 신설 없음 — 코디 B-1) 년월 기준으로 UI 단에서
    # 누적(해당월 말까지)·당월(월초~월말)을 슬라이스해 집계한다(get_near_miss_reports 는 이미
    # incident_date date_from/date_to 를 지원하지만, 년월 옵션 산출과 2구간 계산을 위해
    # 한 번만 읽고 메모리에서 나눈다 — DB 왕복 최소화).
    try:
        all_df = db.get_near_miss_reports({})
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"아차사고 집계 데이터를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("아차사고 집계 데이터를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    # 제목 아래 년월 선택(기본=당월). 데이터에 있는 월 + 당월을 옵션으로 제공한다.
    ym = _month_selector(all_df)
    year, month = int(ym[:4]), int(ym[5:7])
    month_start = f"{year:04d}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    month_end = f"{year:04d}-{month:02d}-{last_day:02d}"

    if all_df is None or all_df.empty:
        ui.empty_state("집계할 아차사고 보고서가 없습니다.", head="아차사고 집계")
        return
    inc = all_df["incident_date"].astype(str)
    cum_df = all_df[inc <= month_end]                          # 해당월 말까지 누적
    cur_df = all_df[(inc >= month_start) & (inc <= month_end)]  # 당월(월초~월말)

    if cum_df.empty:
        ui.empty_state(f"{_ym_dot(ym)}까지 집계할 아차사고 보고서가 없습니다.", head="아차사고 집계")
        return

    status_cum = _counts(cum_df, "status")
    period_cum = _counts(cum_df, "period")
    total_cum = len(cum_df)
    status_cur = _counts(cur_df, "status")
    grade_cur = _counts(cur_df, "grade")
    cause_cur = _counts(cur_df, "cause")
    total_cur = len(cur_df)

    # ① 지표 두 그룹(제목 바로 아래 §8 수용기준 4): 해당월까지 누적 + 당월 실적. CAPA 기한초과는
    #    역할 기반 접근이라 파사드가 평가자/ADMIN 만 집계를 돌려주고 일반 USER 에게는 None('—').
    #    두 그룹은 한 번에 렌더한다 — 같은 그리드 트랙을 공유해야 카드 폭이 행 간에 같다.
    overdue = db.near_miss_overdue_count(current_user=user)
    _kpi_section([
        _kpi_cards_cumulative(status_cum, total_cum, overdue, ym),
        _kpi_cards_current(status_cur, total_cur, ym),
    ])

    # ② 분포 4블록 — 등급·상태·원인은 당월 기준(라벨 명시), 월별 추이는 누적 관점.
    _render_charts(grade_cur, status_cur, cause_cur, total_cur, period_cum, total_cum, ym)


def _ym_dot(ym: str) -> str:
    """'YYYY-MM' → 'YYYY.MM' 표시형."""
    return str(ym).replace("-", ".")


def _month_selector(all_df) -> str:
    """제목 아래 년월 선택(기본=당월). 데이터에 존재하는 월 + 당월을 내림차순 옵션으로 준다."""
    today = date.today()
    cur_ym = f"{today.year:04d}-{today.month:02d}"
    months: set = {cur_ym}
    if all_df is not None and not all_df.empty:
        for v in all_df["incident_date"].astype(str):
            if len(v) >= 7:
                months.add(v[:7])
    options = sorted(months, reverse=True)
    idx = options.index(cur_ym) if cur_ym in options else 0
    with st.container(key="nmf_ymrow"):
        ym = st.selectbox("년월", options, index=idx, key="nmf_ym", width=170,
                          format_func=_ym_dot)
    return ym


def _counts(df, by: str) -> dict:
    """df 를 by 축으로 count 집계(supabase_repository._aggregate_near_miss 와 동일 키 계약).

    grade=confirmed_grade|'미확정' · status=status · cause=cause_code|'미지정' ·
    period=incident_date[:7](YYYY-MM). UI 단 계산이라 facade 신설이 없다(코디 B-1)."""
    counts: dict = {}
    if df is None or df.empty:
        return counts
    for _, r in df.iterrows():
        if by == "grade":
            key = str(r.get("confirmed_grade") or "미확정")
        elif by == "cause":
            key = str(r.get("cause_code") or "미지정")
        elif by == "period":
            key = str(r.get("incident_date") or "")[:7]
        else:  # status
            key = str(r.get("status") or "")
        counts[key] = counts.get(key, 0) + 1
    return counts


# ---------- readiness (migration 006 3-state) ----------
def _readiness() -> ReadinessState:
    if db.is_sample_mode():
        return ReadinessState.ready()
    probe = db.near_miss_schema_probe()
    if probe == Readiness.PROBE_ERROR.value:
        return ReadinessState.probe_error(
            "아차사고 스키마 상태 확인에 실패했습니다 — 재확인이 필요합니다."
        )
    if probe == Readiness.NOT_READY.value:
        return ReadinessState.not_ready(
            "아차사고 스키마가 아직 적용되지 않아 집계할 데이터가 없습니다."
        )
    return ReadinessState.ready()


# ---------- 지표 두 그룹(§1-F 좌측 보더 스트립) ----------
def _kpi_section(groups: list[tuple[str, list[tuple]]]) -> None:
    """지표 그룹 전체를 **한 번에** 렌더한다(그룹 오버라인 + 스트립).

    모든 그룹이 같은 그리드 트랙 수(=지표가 가장 많은 그룹의 개수)를 쓰므로 누적·당월 카드
    폭이 행 간에 동일하다. 지표가 적은 그룹은 남는 칸을 **비운다**(늘려 채우지 않는다).
    트랙 수는 데이터에서 파생하고 상수로 박지 않는다."""
    groups = [(label, items) for label, items in groups if items]
    if not groups:
        return
    cols = max(len(items) for _, items in groups)
    html = [_kpi_grid_css(cols)]
    for label, items in groups:
        html.append(_kpi_group_html(label, items))
    st.markdown("".join(html), unsafe_allow_html=True)


def _kpi_grid_css(cols: int) -> str:
    """지표 그리드 트랙 수(데이터 파생) + 좁은 폭 단계. 트랙 수가 렌더 시점에 정해지므로
    정적 CSS(_inject_style)와 분리한다 — 인라인 style 은 media query 로 못 덮는다."""
    return (
        "<style>"
        f".nmf-kpis{{grid-template-columns:repeat({cols},minmax(0,1fr));}}"
        f"@media (max-width:1100px){{.nmf-kpis"
        f"{{grid-template-columns:repeat({min(cols, 3)},minmax(0,1fr));}}}}"
        f"@media (max-width:640px){{.nmf-kpis"
        f"{{grid-template-columns:repeat({min(cols, 2)},minmax(0,1fr));}}}}"
        "</style>"
    )


def _kpi_group_html(group_label: str, kpis: list[tuple]) -> str:
    """지표 스트립 1행 HTML(§1-F: 좌측 2px 보더 + 26px 모노) + 그룹 오버라인.

    ``kpis``: ``(label, value, unit, note, accent)``. 강조(오렌지 보더)는 지금 조치가 필요한
    값>0 항목만. ``note``(영문 오버라인)는 호출부 튜플 계약 호환을 위해 남기지만 렌더하지
    않는다 — 라벨과 중복이라 near-miss 4화면 공통으로 3줄→2줄(라벨+값)로 줄였다
    (`erp.metric_strip`/평가·개선조치 화면과 동일 어휘)."""
    cells = []
    for label, value, unit, _note, accent in kpis:  # _note(영문 오버라인) 미렌더 — 2줄 타일
        border = _ACCENT if accent else _LINE_SEC
        vcolor = _ACCENT_TEXT if accent else _INK
        unit_html = f"<span class='nmf-kunit'>{escape(unit)}</span>" if unit else ""
        cells.append(
            f"<div class='nmf-kpi' style='border-left:2px solid {border};'>"
            f"<span class='nmf-klabel'>{escape(label)}</span>"
            f"<div class='nmf-kval-row'>"
            f"<span class='nmf-kval' style='color:{vcolor};{_MONO}'>{escape(value)}</span>{unit_html}"
            f"</div>"
            f"</div>"
        )
    head = (f"<div class='nmf-kgroup'>{escape(group_label)}</div>" if group_label else "")
    return f"{head}<div class='nmf-kpis'>{''.join(cells)}</div>"


def _kpi_cards_cumulative(status_counts: dict, total: int, overdue: int | None,
                          ym: str) -> tuple[str, list[tuple]]:
    """누적 그룹(해당월 말까지): 총 건수·평가 대기·검토중·평가완료·기한초과·보고서 종결률.

    dc §1-F 6지표 구성을 그대로 누적 관점으로 쓴다. '평가 대기'=제출됨(검토 착수 전) 백로그,
    '검토중'=IN_REVIEW. 기한초과는 역할 게이트(파사드) 결과를 그대로 표시한다.
    렌더는 하지 않고 ``(그룹 라벨, 타일 목록)`` 만 돌려준다(두 그룹 폭 통일 — `_kpi_section`)."""
    submitted = status_counts.get("SUBMITTED", 0)
    in_review = status_counts.get("IN_REVIEW", 0)
    evaluated = status_counts.get("EVALUATED", 0)
    closed = status_counts.get("CLOSED", 0)
    return f"누적 · {_ym_dot(ym)}까지", [
        ("총 건수", str(total), "건", "ALL", False),
        ("평가 대기", str(submitted), "건", "PENDING", submitted > 0),
        ("검토중", str(in_review), "건", "IN REVIEW", False),
        ("평가완료", str(evaluated), "건", "DONE", False),
        ("기한초과", _overdue_label(overdue), "", "OVERDUE", bool(overdue)),
        ("보고서 종결률", _closure_rate_label(closed, evaluated), "", "CLOSED", False),
    ]


def _kpi_cards_current(status_counts: dict, total: int, ym: str) -> tuple[str, list[tuple]]:
    """당월 그룹(월초~월말 발생분): 당월 발생·미평가·평가완료·종결. 동일 타일 어휘를 재사용한다."""
    submitted = status_counts.get("SUBMITTED", 0)
    in_review = status_counts.get("IN_REVIEW", 0)
    evaluated = status_counts.get("EVALUATED", 0)
    closed = status_counts.get("CLOSED", 0)
    pending = submitted + in_review
    return f"당월 · {_ym_dot(ym)}", [
        ("당월 발생", str(total), "건", "MONTH", total > 0),
        ("미평가", str(pending), "건", "PENDING", False),
        ("평가완료", str(evaluated), "건", "DONE", False),
        ("종결", str(closed), "건", "CLOSED", False),
    ]


def _overdue_label(overdue: int | None) -> str:
    """기한초과 지표 표시값. 007 미준비·비권한자·조회미상(None)이면 '—'(가짜 0 금지).

    집계·권한 판정은 파사드 ``db.near_miss_overdue_count(current_user=)`` 가 소유한다 —
    CAPA 는 역할 기반 접근이라 일반 USER 에게는 이 지표가 None('—')으로 게이트된다."""
    return "—" if overdue is None else f"{overdue}건"


def _closure_rate_label(closed: int, evaluated: int) -> str:
    """보고서 종결률 = CLOSED / (CLOSED + EVALUATED). 평가 이후 파이프라인에서 종결까지
    도달한 보고서의 비율이다.

    ※ 명칭은 정확히 '보고서 종결률' — 'CAPA 종결률'이 아니다. 007 개선조치 하드게이트
    (담당자/확인자 승인)가 적용·검증되기 전에는 status=CLOSED 가 CAPA 완료를 보증하지
    않으므로, 미확인 종결을 CAPA 완료로 오표기하지 않는다(Codex 확정).

    분모(CLOSED+EVALUATED)가 0이면 산정 불가 — '—'로 방어한다(0% 오표기 금지)."""
    denom = closed + evaluated
    if denom == 0:
        return "—"
    return f"{round(closed / denom * 100)}%"


# ---------- 분포 4블록(§1-F 76/1fr/52 그리드) ----------
def _render_charts(grade_cur: dict, status_cur: dict, cause_cur: dict, total_cur: int,
                   period_cum: dict, total_cum: int, ym: str) -> None:
    """분포 4블록을 flex-wrap 그리드(각 블록 flex:1 1 340px)로 렌더한다.

    등급·상태·원인은 **당월 기준**(블록 meta 에 '당월 YYYY.MM' 명시), 월별 발생 추이는
    **누적 관점**(전 기간 월별). 카테고리 단색 막대(등급 오렌지·상태 초록·원인 황토·추이 파랑).
    수치는 건수+비중(각 블록의 기준 총계 대비). 집계 계산 로직은 불변(UI 단 count)."""
    dot = _ym_dot(ym)
    grade_rows = [
        (grade, grade_cur.get(grade, 0))
        for grade in list(db.NEAR_MISS_GRADES) + ["미확정"]
    ]
    status_rows = [
        (_STATUS_LABEL.get(code, code), status_cur.get(code, 0))
        for code in db.NEAR_MISS_STATUSES
    ]
    cause_rows = [
        (_CAUSE_LABEL.get(code, code), count)
        for code, count in sorted(cause_cur.items(), key=lambda kv: -kv[1])
    ]
    trend_rows = sorted(
        ((k if k else "(미상)", v) for k, v in period_cum.items()),
        key=lambda kv: (kv[0] == "(미상)", kv[0]),
    )

    blocks = "".join([
        _chart_block("등급별 분포", f"당월 {dot} · 미평가=미확정", grade_rows, total_cur, _C_GRADE),
        _chart_block("상태별 분포", f"당월 {dot}", status_rows, total_cur, _C_STATUS),
        _chart_block("발생원인별 분포", f"당월 {dot}", cause_rows, total_cur, _C_CAUSE),
        _chart_block("월별 발생 추이", f"누적 ~{dot}", trend_rows, total_cum, _C_TREND),
    ])
    st.markdown(f"<div class='nmf-charts'>{blocks}</div>", unsafe_allow_html=True)


def _chart_block(title: str, note: str | None, rows: list[tuple[str, int]],
                 total: int, color: str) -> str:
    meta = escape(note) if note else f"총 {total}건"
    body = []
    for label, count in rows:
        share = round(count / total * 100) if total else 0  # 전체 대비(0분모 방어)
        body.append(
            "<div class='nmf-row'>"
            f"<span class='nmf-rlabel'>{escape(str(label))}</span>"
            "<div class='nmf-track'>"
            f"<div class='nmf-fill' style='width:{share}%;background:{color};'></div>"
            "</div>"
            "<div class='nmf-rval'>"
            f"<span class='nmf-rcount' style='{_MONO}'>{count}</span>"
            f"<span class='nmf-rpct' style='{_MONO}'>{share}%</span>"
            "</div></div>"
        )
    if not body:
        body.append("<div class='nmf-empty'>표시할 분포가 없습니다</div>")
    return (
        "<section class='nmf-block'>"
        "<div class='nmf-bhead'>"
        f"<span class='nmf-btitle'>{escape(title)}</span>"
        f"<span class='nmf-bmeta' style='{_MONO}'>{meta}</span>"
        "</div>"
        f"<div class='nmf-rows'>{''.join(body)}</div>"
        "</section>"
    )


def _inject_style() -> None:
    st.markdown(
        f"""
<style>
/* §1-F 분석형 — 지표 스트립(좌측 보더) + 분포 4블록(카드 없음, 상단 헤어라인 구획). */
/* 지표 그룹 오버라인(누적/당월 구분) — 모노 소문자 라벨, 카드 아님. */
.nmf-kgroup {{ font-family:'IBM Plex Mono',monospace; font-size:10.5px; letter-spacing:.12em;
  color:{_MUT}; margin:.5rem 0 .35rem; }}
/* 지표 스트립 = 고정 트랙 그리드. 누적(6)·당월(4)이 같은 트랙 수를 공유해 카드 폭이
   행 간에 동일하고, 지표가 적은 행은 늘어나지 않고 남는 칸을 비운다. 트랙 수는 렌더 시
   데이터에서 파생해 주입한다(_kpi_grid_css). 타일은 라벨+값 2줄(영문 오버라인 없음). */
.nmf-kpis {{ display:grid; gap:10px 12px; margin:.1rem 0 .8rem; }}
.nmf-kpi {{ min-width:0; display:flex; flex-direction:column; gap:4px; padding:2px 18px; }}
.nmf-klabel {{ font-size:12px; color:{_MUT}; white-space:nowrap; overflow:hidden;
  text-overflow:ellipsis; }}
.nmf-kval-row {{ display:flex; align-items:baseline; gap:4px; }}
.nmf-kval {{ font-family:'IBM Plex Mono',monospace; font-size:26px; font-weight:600;
  letter-spacing:-0.03em; font-variant-numeric:tabular-nums; }}
.nmf-kunit {{ font-size:11.5px; color:{_MUT}; }}

.nmf-charts {{ display:flex; flex-wrap:wrap; gap:16px 28px; }}
.nmf-block {{ flex:1 1 340px; min-width:0; padding:16px 0 8px;
  border-top:1px solid {_LINE_STRONG}; display:flex; flex-direction:column; gap:12px; }}
.nmf-bhead {{ display:flex; align-items:baseline; justify-content:space-between; gap:12px; }}
.nmf-btitle {{ font-size:13.5px; font-weight:600; color:{_INK}; }}
.nmf-bmeta {{ font-family:'IBM Plex Mono',monospace; font-size:10.5px; letter-spacing:.08em;
  color:{_MUT}; white-space:nowrap; }}
.nmf-rows {{ display:flex; flex-direction:column; gap:10px; }}
.nmf-row {{ display:grid; grid-template-columns:76px minmax(0,1fr) 52px; gap:10px;
  align-items:center; }}
.nmf-rlabel {{ font-size:12.5px; color:{_INK2}; text-align:right; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }}
.nmf-track {{ height:8px; border-radius:999px; background:{_LINE}; overflow:hidden; }}
.nmf-fill {{ height:100%; border-radius:999px; }}
.nmf-rval {{ display:flex; align-items:baseline; gap:5px; justify-content:flex-end; }}
.nmf-rcount {{ font-family:'IBM Plex Mono',monospace; font-size:12px; font-weight:600;
  color:{_INK}; font-variant-numeric:tabular-nums; }}
.nmf-rpct {{ font-family:'IBM Plex Mono',monospace; font-size:10.5px; color:{_MUT};
  font-variant-numeric:tabular-nums; }}
.nmf-empty {{ font-size:12.5px; color:{_MUT}; padding:4px 0; }}
/* 모노 강제 — 전역 `.stApp [data-testid=stMarkdownContainer] *`(특이도 0,2,0)를 이기려면
   0,3,0 이상이어야 한다(숫자·오버라인이 sans 로 떨어지는 것 방지). 인라인과 병행 못박음. */
.stApp [data-testid="stMarkdownContainer"] .nmf-kval,
.stApp [data-testid="stMarkdownContainer"] .nmf-bmeta,
.stApp [data-testid="stMarkdownContainer"] .nmf-rcount,
.stApp [data-testid="stMarkdownContainer"] .nmf-rpct {{
  font-family:'IBM Plex Mono','Consolas','Menlo',monospace;
}}
@media (max-width:768px) {{
  .nmf-row {{ grid-template-columns:64px minmax(0,1fr) 48px; }}
}}
</style>
""",
        unsafe_allow_html=True,
    )
