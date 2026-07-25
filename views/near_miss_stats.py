"""아차사고(near-miss) 집계 — 등급·부서·기간·원인·상태 분포 대시보드.

DESIGN.md §0 DASHBOARD 크롬: 브레드크럼 → 제목·모드 배지 → 지표 카드 행 → 현황
패널(분포). 저장/평가 액션은 이 화면의 책임이 아니다 — 순수 집계 조회다.

파사드 계약: ``modules/db.py`` 의 ``near_miss_stats(by=..., filters=...)`` 만 호출하고
repository(``_aggregate_near_miss`` 등)를 직접 부르지 않는다. by 축(grade/dept/period/
cause/status)마다 각각 호출한다 — 화면이 자체 집계 로직을 재구현하지 않는다(기간의
분기 롤업만 이미 받은 월별 dict 를 표시용으로 재묶음한 것이며 새 조회가 아니다).
"""
from __future__ import annotations

# DESIGN.md §0 화면 유형 규약 — 대시보드형.
SCREEN_ARCHETYPE = "DASHBOARD"

from html import escape

import streamlit as st

from modules import auth, db, ui
from views.common import scaffold
from views.master import TOKENS
from views.master.lifecycle import Readiness, ReadinessState

_PAGE_ID = "near_miss_stats"

_STATUS_LABEL = {
    "SUBMITTED": "제출", "IN_REVIEW": "검토중", "EVALUATED": "평가완료",
    "CLOSED": "종결", "REJECTED": "반려",
}
_STATUS_COLOR = {
    "SUBMITTED": TOKENS["info"], "IN_REVIEW": TOKENS["gold"],
    "EVALUATED": TOKENS["success"], "CLOSED": TOKENS["ink-3"], "REJECTED": TOKENS["danger"],
}
_GRADE_COLOR = {
    "S": TOKENS["danger"], "A": TOKENS["gold"], "B": TOKENS["warn"],
    "C": TOKENS["info"], "D": TOKENS["ink-3"],
}
_CAUSE_LABEL = {
    "JAM": "협착", "FALL": "추락", "DROP": "낙하", "HIT": "충돌",
    "SLIP": "미끄러짐", "BURN": "화상", "PINCH": "끼임", "ETC": "기타",
}
_NEUTRAL = TOKENS["navy"]


def render(user: dict) -> None:
    # nav.py 에 아직 라우팅되지 않은 화면(B2 routing 이후 예정)이므로 page_chrome_for 대신
    # page_chrome 에 제목/설명/브레드크럼을 직접 넘긴다 — near_miss_view.render 와 동일
    # 사유(nav.py 미등록 page_id 로 인한 group_of KeyError 회피).
    scaffold.page_chrome(
        SCREEN_ARCHETYPE,
        title="아차사고 집계",
        desc="아차사고 등급·부서·기간·원인·상태별 분포를 확인합니다.",
        breadcrumb="아차사고 › 집계",
        badges=scaffold.mode_badge(),
    )
    _inject_panel_style()

    if not auth.can_evaluate_near_miss(user):
        ui.empty_state(
            "아차사고 집계 권한이 없습니다. 안전담당자 또는 관리자만 조회할 수 있습니다.",
            head="접근 제한",
        )
        return

    _readiness().banner()

    try:
        scope, manager_dept = _scope_for(user)
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"조직 정보를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("조직 정보를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return
    if scope == "blocked":
        ui.empty_state(
            "소속 부서가 지정되지 않아 아차사고 집계를 표시할 수 없습니다. "
            "관리자에게 부서 지정을 요청하세요.",
            head="아차사고 집계",
        )
        return
    filters = {"dept_code": manager_dept} if scope == "scoped" else {}

    try:
        status_counts = db.near_miss_stats(by="status", filters=filters)
        grade_counts = db.near_miss_stats(by="grade", filters=filters)
        dept_counts = db.near_miss_stats(by="dept", filters=filters)
        period_counts = db.near_miss_stats(by="period", filters=filters)
        cause_counts = db.near_miss_stats(by="cause", filters=filters)
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"아차사고 집계 데이터를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("아차사고 집계 데이터를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    total = sum(status_counts.values())
    if total == 0:
        ui.empty_state("집계할 아차사고 보고서가 없습니다.", head="아차사고 집계")
        return

    _kpi_cards(status_counts, total)
    st.write("")

    col_a, col_b = st.columns(2)
    with col_a:
        _grade_panel(grade_counts, total)
    with col_b:
        _status_panel(status_counts, total)

    col_c, col_d = st.columns(2)
    with col_c:
        _dept_panel(dept_counts, total)
    with col_d:
        _cause_panel(cause_counts, total)

    _period_panels(period_counts, total)


# ---------- 접근 범위(fail-closed) — near_miss_view._scope_for 와 동일 관행 ----------
def _scope_for(user: dict) -> tuple[str, str | None]:
    """집계 범위: ADMIN/안전담당자=전체, MANAGER=본인 부서, 그 외(부서 미확정 MANAGER)=차단."""
    role = str(user.get("role") or "").strip().upper()
    if role == "MANAGER":
        dept = str(user.get("dept_code") or "").strip() or None
        depts = db.get_departments()
        codes = set(depts["dept_code"].astype(str)) if not depts.empty else set()
        if dept and dept in codes:
            return "scoped", dept
        return "blocked", None
    return "all", None


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


# ---------- KPI 카드 ----------
def _kpi_cards(status_counts: dict, total: int) -> None:
    pending = status_counts.get("SUBMITTED", 0) + status_counts.get("IN_REVIEW", 0)
    evaluated = status_counts.get("EVALUATED", 0)
    closed_or_rejected = status_counts.get("CLOSED", 0) + status_counts.get("REJECTED", 0)
    ui.summary_cards([
        ("총 건수", f"{total}건"),
        ("평가 대기", f"{pending}건"),
        ("평가완료", f"{evaluated}건"),
        ("종결·반려", f"{closed_or_rejected}건"),
    ])


# ---------- 분포 패널 ----------
def _panel(title: str, rows: list[tuple[str, int, str]], total: int) -> None:
    max_count = max((c for _, c, _ in rows), default=0) or 1
    body = []
    for label, count, color in rows:
        pct = round(count / max_count * 100) if max_count else 0
        share = round(count / total * 100) if total else 0
        body.append(
            "<div class='nm-row'>"
            f"<div class='nm-row-label'>{ui.badge_html(escape(label), color)}</div>"
            "<div class='nm-row-bar-wrap'>"
            f"<div class='nm-row-bar' style='width:{pct}%;background:{color}'></div>"
            "</div>"
            f"<div class='nm-row-count'>{count}건 <span class='nm-row-pct'>({share}%)</span></div>"
            "</div>"
        )
    with ui.card():
        ui.panel_head(title, f"총 {total}건")
        st.markdown(f"<div class='nm-panel'>{''.join(body)}</div>", unsafe_allow_html=True)


def _grade_panel(counts: dict, total: int) -> None:
    order = list(db.NEAR_MISS_GRADES) + ["미확정"]
    rows = [
        (grade, counts.get(grade, 0), _GRADE_COLOR.get(grade, TOKENS["ink-3"]))
        for grade in order
    ]
    _panel("등급별 분포(제안·확정 미평가는 미확정)", rows, total)


def _status_panel(counts: dict, total: int) -> None:
    order = list(db.NEAR_MISS_STATUSES)
    rows = [
        (_STATUS_LABEL.get(code, code), counts.get(code, 0), _STATUS_COLOR.get(code, TOKENS["ink-3"]))
        for code in order
    ]
    _panel("상태별 분포", rows, total)


def _dept_panel(counts: dict, total: int) -> None:
    rows = []
    for code, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        label = code if code == "미지정" else _safe_dept_name(code)
        rows.append((label, count, _NEUTRAL))
    _panel("부서·소속별 분포", rows, total)


def _safe_dept_name(code: str) -> str:
    """부서명 라벨링은 부가 정보 — 조회 실패로 집계 패널 전체를 막지 않고 코드만 표시한다."""
    try:
        return db.dept_name(code)
    except Exception:
        return code


def _cause_panel(counts: dict, total: int) -> None:
    rows = []
    for code, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        label = _CAUSE_LABEL.get(code, code)
        rows.append((label, count, _NEUTRAL))
    _panel("발생원인별 분포", rows, total)


def _period_panels(period_counts: dict, total: int) -> None:
    monthly = sorted(
        ((k if k else "(미상)", v) for k, v in period_counts.items()),
        key=lambda kv: (kv[0] == "(미상)", kv[0]),
    )
    rows = [(label, count, _NEUTRAL) for label, count in monthly]

    quarterly: dict[str, int] = {}
    for key, count in period_counts.items():
        quarterly[_quarter_of(key)] = quarterly.get(_quarter_of(key), 0) + count
    q_rows = [
        (label, count, _NEUTRAL)
        for label, count in sorted(quarterly.items(), key=lambda kv: (kv[0] == "(미상)", kv[0]))
    ]

    col_m, col_q = st.columns(2)
    with col_m:
        _panel("월별 발생 추이", rows, total)
    with col_q:
        _panel("분기별 발생 추이", q_rows, total)


def _quarter_of(month_key: str) -> str:
    """``YYYY-MM`` → ``YYYY-Qn`` (표시용 재묶음, 새 조회 아님)."""
    if len(month_key) != 7 or month_key[4] != "-":
        return "(미상)"
    year, month = month_key.split("-")
    try:
        q = (int(month) - 1) // 3 + 1
    except ValueError:
        return "(미상)"
    return f"{year}-Q{q}"


def _inject_panel_style() -> None:
    st.markdown(
        """
<style>
.nm-panel { display:flex; flex-direction:column; gap:.4rem; margin-top:.3rem; }
.nm-row { display:grid; grid-template-columns:110px 1fr 120px; align-items:center; gap:.5rem; }
.nm-row-bar-wrap { background:#F1EEE7; border-radius:4px; height:10px; overflow:hidden; }
.nm-row-bar { height:100%; border-radius:4px; }
.nm-row-count { font-size:12.5px; color:#24262B; font-variant-numeric:tabular-nums; text-align:right; }
.nm-row-pct { color:#908C83; }
@media (max-width:768px) {
  .nm-row { grid-template-columns:88px 1fr 96px; }
}
</style>
""",
        unsafe_allow_html=True,
    )
