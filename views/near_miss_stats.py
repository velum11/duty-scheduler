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

from modules import db, nav, ui
from views.common import erp
from views.common import scaffold
from views.master import TOKENS, icon_toolbar_specs
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
    # near_miss_stats 는 nav.py 에 등록돼 있다(그룹 '아차사고' › '집계'). 제목/설명은
    # page_chrome_for 대신 screen_frame 에 직접 넘긴다 — near_miss_view.render 와 동일하게
    # nav 라벨과의 단일 출처 통일은 후속(통합 담당) 과제로 남겨둔다.
    band = erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="아차사고 분석",
        desc="아차사고 등급·부서·기간·원인·상태별 분포를 분석합니다.",
        breadcrumb="아차사고 › 아차사고 분석",
        badges=scaffold.mode_badge(),
        toolbar="icons",
    )
    # 상단 파랑 밴드 아이콘 툴바(공통 표준). 조회조건이 없는 집계 화면이라 새로고침만
    # 활성 — search 아이콘 클릭의 rerun 만으로 아래 5건 통계 호출이 재실행된다(구 pill 과
    # 동일). 추가·삭제·저장은 순수 조회라 N/A(shaded).
    if band is not None:
        band.render_icons(icon_toolbar_specs(
            _PAGE_ID, info_content=nav.page_desc(_PAGE_ID),
            add={"key": f"{_PAGE_ID}__add_na", "disabled": True,
                 "help": "이 화면에서는 사용하지 않습니다"},
            refresh={"key": f"{_PAGE_ID}_refresh", "help": "새로고침", "on_click": None},
            delete={"key": f"{_PAGE_ID}__del_na", "disabled": True,
                    "help": "이 화면에서는 사용하지 않습니다"},
            save={"key": f"{_PAGE_ID}__save_na", "disabled": True,
                  "help": "이 화면에서는 사용하지 않습니다"},
        ))
    _inject_panel_style()

    # 접근 범위(제품 결정 — Coordinator): 아차사고 분석은 전 사용자에게 열려 있고 회사
    # 전체 범위다. 과거 평가자 전용 게이트·MANAGER 부서 스코프는 제거했다(filters 비움).
    _readiness().banner()
    filters: dict = {}

    # 영역 순서(§0.3, Codex 정합): title(밴드 아이콘 툴바) → primary(KPI 지표) →
    # details(분포). 이전엔 KPI 를 status 로, 분포를 primary 로 봐 순서가 역전돼 있었다 —
    # DASHBOARD 는 지표가 primary(좌상단 우선), 분포가 세부(details)다. 새로고침은 상단 밴드
    # 아이콘으로 이전했다(위 render_icons — 인페이지 pill 제거).

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

    # primary — KPI 지표(좌상단 우선). CAPA 기한초과는 신고 분포(전사 공개)와 달리 역할 기반
    # 접근이다 — 파사드가 평가자/ADMIN 만 집계를 돌려주고 일반 USER 에게는 None('—')을 준다
    # (집계 수치 leak 방지).
    _kpi_cards(status_counts, total, db.near_miss_overdue_count(current_user=user))
    st.write("")

    # details — 분포(등급·상태·부서·원인·월·분기 6종을 컴팩트 테이블 2열로).
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
def _kpi_cards(status_counts: dict, total: int, overdue: int | None) -> None:
    """6개 KPI 를 단일 스트립 1행으로 렌더한다(§0.6 강제: 요약/KPI 한 줄 스트립 ≤72px,
    2행 이상 쌓기 금지 — 종전 2행×3 카드가 행을 넘어 겹치던 문제를 근본 제거).

    좌상단 우선 순서: 규모·백로그·긴급 초과(총 건수·평가 대기·기한초과)를 앞에, 파생·완료
    지표(평가완료·종결·반려·보고서 종결률)를 뒤에 둔다. 정확히 현재 6개 KPI 를 보존하며
    공용 스트립 컴포넌트(erp.status_region)를 재사용한다(밴드 새 위젯 없음)."""
    pending = status_counts.get("SUBMITTED", 0) + status_counts.get("IN_REVIEW", 0)
    evaluated = status_counts.get("EVALUATED", 0)
    closed = status_counts.get("CLOSED", 0)
    closed_or_rejected = closed + status_counts.get("REJECTED", 0)
    erp.status_region([
        ("총 건수", f"{total}건"),
        ("평가 대기", f"{pending}건"),
        ("기한초과", _overdue_label(overdue)),
        ("평가완료", f"{evaluated}건"),
        ("종결·반려", f"{closed_or_rejected}건"),
        ("보고서 종결률", _closure_rate_label(closed, evaluated)),
    ])


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


# ---------- 분포 패널(컴팩트 테이블) ----------
def _panel(title: str, rows: list[tuple[str, int, str]], total: int) -> None:
    """분포를 라벨·건수·비중 컴팩트 테이블로 렌더한다(카드 반복+수제 막대 지양).

    카드마다 큰 막대를 반복하는 대신 밀도 높은 표 한 행에 라벨(색+텍스트 배지 이중부호화)·
    건수·비중(%)을 싣고, 막대는 패널 내 최댓값 대비의 **보조 인라인** 신호로만 남긴다.
    실데이터 집계만 표시하며 허수·장식 차트는 만들지 않는다(빈 분포는 방어 문구로 대체)."""
    max_count = max((c for _, c, _ in rows), default=0) or 1
    body = []
    for label, count, color in rows:
        bar = round(count / max_count * 100) if max_count else 0   # 패널 내 상대(막대 = 보조)
        share = round(count / total * 100) if total else 0         # 전체 대비 비중(수치 열)
        body.append(
            "<div class='nm-tr'>"
            f"<div class='nm-td-l'>{ui.badge_html(escape(label), color)}</div>"
            "<div class='nm-td-bar'>"
            f"<div class='nm-td-fill' style='width:{bar}%;background:{color}'></div>"
            "</div>"
            f"<div class='nm-td-c'>{count}</div>"
            f"<div class='nm-td-p'>{share}%</div>"
            "</div>"
        )
    if not body:
        body.append("<div class='nm-tr nm-empty'><div>표시할 분포가 없습니다</div></div>")
    # §0.6 박스 상한: 분포마다 독립 bordered 카드를 나열하지 않는다(6개 카드 → 상한 3 초과).
    # 사내 ERP 방식대로 굵은 소제목 라벨 + hairline 구획으로만 분포를 나눈다(카드/보더 없음).
    st.markdown(
        "<div class='nm-panel'>"
        f"<div class='nm-panel-h'>{escape(title)}"
        f"<span class='nm-panel-sub'>총 {total}건</span></div>"
        "<div class='nm-tbl'>"
        "<div class='nm-tr nm-th'><div class='nm-td-l'>항목</div>"
        "<div class='nm-td-bar'></div><div class='nm-td-c'>건수</div>"
        "<div class='nm-td-p'>비중</div></div>"
        f"{''.join(body)}</div></div>",
        unsafe_allow_html=True,
    )


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
        f"""
<style>
/* 분포 패널(카드 아님) — 굵은 소제목 라벨 + hairline 구획만(§0.6 박스 상한, 사내 ERP 방식). */
.nm-panel {{ padding:.1rem 0 .55rem; margin-bottom:.35rem; border-bottom:1px solid {TOKENS['line']}; }}
.nm-panel-h {{ display:flex; align-items:baseline; justify-content:space-between;
  font-size:.86rem; font-weight:700; color:{TOKENS['ink']}; margin:.15rem 0 .1rem; }}
.nm-panel-sub {{ font-size:.72rem; font-weight:500; color:{TOKENS['ink-2']};
  font-variant-numeric:tabular-nums; }}
.nm-tbl {{ display:flex; flex-direction:column; margin-top:.25rem; }}
.nm-tr {{ display:grid; grid-template-columns:minmax(84px,132px) 1fr 44px 46px;
  align-items:center; gap:.5rem; padding:2px 0;
  border-bottom:1px solid {TOKENS['line']}; }}
.nm-tr:last-child {{ border-bottom:0; }}
.nm-th {{ font-size:11px; color:{TOKENS['ink-2']}; font-weight:600;
  border-bottom:1px solid {TOKENS['line-strong']}; padding-bottom:3px; }}
.nm-th .nm-td-c, .nm-th .nm-td-p {{ text-align:right; }}
.nm-td-bar {{ background:{TOKENS['surface-2']}; border-radius:3px; height:8px; overflow:hidden; }}
.nm-th .nm-td-bar {{ background:transparent; }}
.nm-td-fill {{ height:100%; border-radius:3px; }}
.nm-td-c {{ font-size:12.5px; color:{TOKENS['ink']};
  font-variant-numeric:tabular-nums; text-align:right; }}
.nm-td-p {{ font-size:12px; color:{TOKENS['ink-2']};
  font-variant-numeric:tabular-nums; text-align:right; }}
.nm-empty {{ grid-template-columns:1fr; color:{TOKENS['ink-3']}; font-size:12.5px; padding:6px 0; }}
@media (max-width:768px) {{
  .nm-tr {{ grid-template-columns:minmax(72px,104px) 1fr 40px 42px; }}
}}
</style>
""",
        unsafe_allow_html=True,
    )
