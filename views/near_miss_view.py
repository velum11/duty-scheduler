"""아차사고(near-miss) 조회 — 보고서 목록(조회 전용).

DESIGN.md §0 READ_VIEW 크롬: 브레드크럼 → 제목 → 조회 조건바(발생일 기간·부서·등급·
상태·원인) → 읽기 그리드 → 범례·요약. 저장/평가 액션은 이 화면의 책임이 아니다
(별도 평가 화면 소관) — 여기는 순수 조회다.

파사드 계약: ``modules/db.py`` 의 ``get_near_miss_reports(filters)`` 만 호출하고
repository 를 직접 부르지 않는다(자연키 계약, NEAR_MISS_COLUMNS).
"""
from __future__ import annotations

# DESIGN.md §0 화면 유형 규약 — 조회형.
SCREEN_ARCHETYPE = "READ_VIEW"

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from modules import auth, db, ui
from views import workspace
from views.common import scaffold
from views.master import TOKENS
from views.master.lifecycle import Readiness, ReadinessState

_PAGE_ID = "near_miss_view"

# 상태·원인 코드 → 한글 라벨(파사드 코드값은 NEAR_MISS_STATUSES/NEAR_MISS_CAUSE_CODES,
# 화면 표시만 한글화한다 — 코드 자체는 바꾸지 않는다).
_STATUS_LABEL = {
    "SUBMITTED": "제출",
    "IN_REVIEW": "검토중",
    "EVALUATED": "평가완료",
    "CLOSED": "종결",
    "REJECTED": "반려",
}
# 상태 색(이중부호화 — 라벨 텍스트는 항상 함께 표시되므로 색은 보조 신호).
# 기존 기준정보 색 토큰(views/master/style.py TOKENS)을 재사용해 새 색을 만들지 않는다.
_STATUS_COLOR = {
    "SUBMITTED": TOKENS["info"],
    "IN_REVIEW": TOKENS["gold"],
    "EVALUATED": TOKENS["success"],
    "CLOSED": TOKENS["ink-3"],
    "REJECTED": TOKENS["danger"],
}
_CAUSE_LABEL = {
    "JAM": "협착", "FALL": "추락", "DROP": "낙하", "HIT": "충돌",
    "SLIP": "미끄러짐", "BURN": "화상", "PINCH": "끼임", "ETC": "기타",
}
# 등급 색(S 가 가장 중대 → 옅어질수록 경미). TOKENS 재사용.
_GRADE_COLOR = {
    "S": TOKENS["danger"], "A": TOKENS["gold"], "B": TOKENS["warn"],
    "C": TOKENS["info"], "D": TOKENS["ink-3"],
}


def render(user: dict) -> None:
    # nav.py 에 아직 라우팅되지 않은 화면(B2 routing 이후 예정)이므로 page_chrome_for
    # (modules/nav.py 의 그룹/라벨을 조회)가 아니라 page_chrome 에 제목/설명/브레드크럼을
    # 직접 넘긴다 — nav.py 미등록 page_id 로 인한 KeyError(group_of)를 피한다. B2 routing
    # 후 nav.py 라벨과의 정합은 통합 담당(§0 크롬 계약은 page_chrome 실호출로 이미 충족).
    scaffold.page_chrome(
        SCREEN_ARCHETYPE,
        title="아차사고 조회",
        desc="아차사고 보고서 목록을 조회합니다.",
        breadcrumb="아차사고 › 조회",
        badges=scaffold.mode_badge(),
    )

    # 접근 통제: 평가자(안전담당자) 또는 ADMIN/MANAGER 만 조회한다(auth.can_evaluate_near_miss
    # 가 이미 이 세 경우를 판정한다 — 화면은 판정을 다시 만들지 않는다).
    if not auth.can_evaluate_near_miss(user):
        ui.empty_state(
            "아차사고 조회 권한이 없습니다. 안전담당자 또는 관리자만 조회할 수 있습니다.",
            head="접근 제한",
        )
        return

    _readiness().banner()

    try:
        scope, manager_dept, dept_names = _scope_for(user)
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"조직 정보를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("조직 정보를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return
    if scope == "blocked":
        ui.empty_state(
            "소속 부서가 지정되지 않아 아차사고 현황을 표시할 수 없습니다. "
            "관리자에게 부서 지정을 요청하세요.",
            head="아차사고 조회",
        )
        return

    q, clicked = _filter_bar(scope, manager_dept, dept_names)
    saved = workspace.run_query(_PAGE_ID, clicked, q)
    if saved is None:
        ui.empty_state("조회 조건을 지정하고 [조회]를 눌러 아차사고 보고서를 확인하세요.", head="아차사고 조회")
        return

    # MANAGER 부서 범위는 저장된 조회조건(이전 세션 값일 수 있음)에도 항상 재적용한다
    # (workspace.schedule_screen 과 동일한 fail-closed 관행 — 위젯 잠금만 믿지 않는다).
    if scope == "scoped":
        saved = {**saved, "dept": manager_dept}

    try:
        df = db.get_near_miss_reports(_facade_filters(saved))
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"아차사고 데이터를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("아차사고 데이터를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    has_filters = _has_filters(saved)
    if df.empty:
        if has_filters:
            ui.empty_state("조회 조건에 해당하는 아차사고 보고서가 없습니다.", head="아차사고 조회")
        else:
            ui.empty_state("등록된 아차사고 보고서가 없습니다.", head="아차사고 조회")
        return

    try:
        display = _to_display(df)
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"사용자·부서 정보를 불러오지 못해 목록을 표시할 수 없습니다. ({exc})")
        return
    except Exception:
        st.error("사용자·부서 정보를 불러오지 못해 목록을 표시할 수 없습니다. 잠시 후 다시 확인하세요.")
        return
    ui.panel_head("아차사고 보고서 목록", f"조회 결과 {len(display)}건")
    styled = display.style.map(_style_grade, subset=["제안등급", "확정등급"])
    styled = styled.map(_style_status, subset=["상태"])
    st.dataframe(
        styled, width="stretch", hide_index=True,
        height=workspace.list_height(len(display)),
    )
    st.write("")

    counts = df["status"].astype(str)
    ui.summary_cards([
        ("조회 건수", f"{len(df)}건"),
        ("평가 대기", f"{counts.isin(['SUBMITTED', 'IN_REVIEW']).sum()}건"),
        ("평가완료", f"{(counts == 'EVALUATED').sum()}건"),
        ("종결·반려", f"{counts.isin(['CLOSED', 'REJECTED']).sum()}건"),
    ])


# ---------- 접근 범위(fail-closed) ----------
def _scope_for(user: dict) -> tuple[str, str | None, dict]:
    """조회 범위를 결정한다(dashboard._scope_for 와 같은 fail-closed 관행).

    반환: (scope, manager_dept, dept_names)
      - ("all", None, {코드: 이름 전체})       — ADMIN, 또는 안전담당자(역할과 무관하게
        부서를 넘나드는 안전 점검이 직무이므로 전체 조회를 허용한다).
      - ("scoped", dept, {코드: 이름})         — MANAGER 且 유효 담당 부서일 때만.
      - ("blocked", None, {})                 — 부서 미확정 MANAGER(그 외는
        can_evaluate_near_miss 게이트를 통과하지 못해 이 함수에 도달하지 않는다).
    """
    depts = db.get_departments()
    dept_names = {
        str(r["dept_code"]): str(r["dept_name"]) for _, r in depts.iterrows()
    } if not depts.empty else {}
    role = str(user.get("role") or "").strip().upper()
    if role == "MANAGER":
        dept = str(user.get("dept_code") or "").strip() or None
        if dept and dept in dept_names:
            return "scoped", dept, dept_names
        return "blocked", None, {}
    # ADMIN 또는 안전담당자(role 무관) — 전체 조회.
    return "all", None, dept_names


# ---------- 조회 조건바 ----------
def _filter_bar(scope: str, manager_dept: str | None, dept_names: dict) -> tuple[dict, bool]:
    with ui.card():
        r1 = st.columns([1.0, 1.15, 1.15, 1.5, 1.0], vertical_alignment="bottom")
        with r1[0]:
            period_on = st.checkbox("기간 지정", value=False, key=f"{_PAGE_ID}_period_on")
        with r1[1]:
            date_from = st.date_input(
                "발생일(시작)", value=date.today() - timedelta(days=90),
                key=f"{_PAGE_ID}_from", disabled=not period_on,
            )
        with r1[2]:
            date_to = st.date_input(
                "발생일(종료)", value=date.today(),
                key=f"{_PAGE_ID}_to", disabled=not period_on,
            )
        with r1[3]:
            if scope == "scoped":
                dept = st.selectbox(
                    "부서", [manager_dept],
                    format_func=lambda c: dept_names.get(c, c),
                    key=f"{_PAGE_ID}_dept", disabled=True,
                )
            else:
                dept_opts = [workspace.ALL] + sorted(dept_names)
                dept = st.selectbox(
                    "부서", dept_opts,
                    format_func=lambda c: dept_names.get(c, c),
                    key=f"{_PAGE_ID}_dept",
                )
        with r1[4]:
            clicked = st.button("조회", key=f"{_PAGE_ID}_go", type="primary", width="stretch")

        r2 = st.columns([1.0, 1.0, 1.0, 3.0])
        with r2[0]:
            grade = st.selectbox(
                "확정등급", [workspace.ALL] + list(db.NEAR_MISS_GRADES), key=f"{_PAGE_ID}_grade",
            )
        with r2[1]:
            status = st.selectbox(
                "상태", [workspace.ALL] + list(db.NEAR_MISS_STATUSES),
                format_func=lambda v: _STATUS_LABEL.get(v, v) if v != workspace.ALL else v,
                key=f"{_PAGE_ID}_status",
            )
        with r2[2]:
            cause = st.selectbox(
                "원인", [workspace.ALL] + list(db.NEAR_MISS_CAUSE_CODES),
                format_func=lambda v: _CAUSE_LABEL.get(v, v) if v != workspace.ALL else v,
                key=f"{_PAGE_ID}_cause",
            )

    params = {
        "dept": dept,
        "grade": grade,
        "status": status,
        "cause": cause,
        "period_on": period_on,
        "date_from": date_from.isoformat() if period_on else "",
        "date_to": date_to.isoformat() if period_on else "",
    }
    return params, clicked


def _has_filters(q: dict) -> bool:
    return (
        q.get("dept") != workspace.ALL
        or q.get("grade") != workspace.ALL
        or q.get("status") != workspace.ALL
        or q.get("cause") != workspace.ALL
        or bool(q.get("period_on"))
    )


def _facade_filters(q: dict) -> dict:
    filters: dict = {}
    if q.get("dept") != workspace.ALL:
        filters["dept_code"] = q["dept"]
    if q.get("grade") != workspace.ALL:
        filters["confirmed_grade"] = q["grade"]
    if q.get("status") != workspace.ALL:
        filters["status"] = q["status"]
    if q.get("cause") != workspace.ALL:
        filters["cause_code"] = q["cause"]
    if q.get("date_from"):
        filters["date_from"] = q["date_from"]
    if q.get("date_to"):
        filters["date_to"] = q["date_to"]
    return filters


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
            "아차사고 스키마가 아직 적용되지 않아 보고서를 조회할 수 없습니다."
        )
    return ReadinessState.ready()


# ---------- 표시 변환 ----------
def _clean(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _to_display(df: pd.DataFrame) -> pd.DataFrame:
    users = db.get_users()
    name_of = {
        str(r["emp_no"]): str(r["name"]) for _, r in users.iterrows()
    } if not users.empty else {}
    depts = db.get_departments()
    dept_name_of = {
        str(r["dept_code"]): str(r["dept_name"]) for _, r in depts.iterrows()
    } if not depts.empty else {}

    rows = []
    for _, r in df.iterrows():
        emp = _clean(r.get("reporter_emp_no"))
        dept = _clean(r.get("dept_code"))
        rows.append({
            "보고번호": _clean(r.get("report_no")),
            "작업명": _clean(r.get("work_name")),
            "신고자": name_of.get(emp, emp) or "-",
            "소속": dept_name_of.get(dept, dept) or "-",
            "발생일": _clean(r.get("incident_date")) or "-",
            "제안등급": _clean(r.get("proposed_grade")) or "-",
            "확정등급": _clean(r.get("confirmed_grade")) or "-",
            "상태": _STATUS_LABEL.get(_clean(r.get("status")), _clean(r.get("status"))),
            "원인": _CAUSE_LABEL.get(_clean(r.get("cause_code")), _clean(r.get("cause_code")) or "-"),
        })
    return pd.DataFrame(rows)


def _style_grade(value: str) -> str:
    color = _GRADE_COLOR.get(str(value).strip())
    if not color:
        return ""
    return f"background-color:{color}22; color:{TOKENS['ink']}; font-weight:600;"


def _style_status(value: str) -> str:
    # 표시값은 한글 라벨이므로 라벨→색 역맵으로 조회한다(코드 자체는 바꾸지 않음).
    label_to_color = {label: _STATUS_COLOR[code] for code, label in _STATUS_LABEL.items()}
    color = label_to_color.get(str(value).strip())
    if not color:
        return ""
    return f"background-color:{color}22; color:{TOKENS['ink']}; font-weight:600;"
