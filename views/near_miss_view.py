"""아차사고(near-miss) 조회 — 보고서 목록(조회 전용).

DESIGN.md §0 READ_VIEW / KP-standard: title → top actions(조회·새로고침) → 조건 패널
(col-N 우측 인라인 라벨) → 읽기 그리드 → 요약. 저장/평가 액션은 이 화면의 책임이 아니다
(별도 평가 화면 소관) — 여기는 순수 조회다.

구조는 공용 중립 키트(``views/common/erp``)를 쓰고, 데이터/권한 로직(_scope_for
fail-closed·readiness 3-state·facade 전용)은 그대로 유지한다.

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
from views.common import erp
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

_DISPLAY_COLUMNS = [
    "보고번호", "작업명", "신고자", "소속", "발생일",
    "제안등급", "확정등급", "상태", "원인",
]

# 컬럼 폭(1366×768에서 9열이 가로 오버플로 없이 들어가도록 — 작업명·소속은 flex 로 잔여 폭 흡수).
_COL_CONFIG = {
    "보고번호": {"width": 108},
    "작업명": {"flex": 2, "minWidth": 160},
    "신고자": {"width": 92},
    "소속": {"flex": 1, "minWidth": 96},
    "발생일": {"width": 104},
    "제안등급": {"width": 84},
    "확정등급": {"width": 84},
    "상태": {"width": 88},
    "원인": {"width": 92},
}


def render(user: dict) -> None:
    # near_miss_view 는 nav.py 에 등록돼 있다(그룹 '아차사고' › '조회'). 제목/설명은 nav.py
    # 라벨과 정합되게 명시한다(desc 는 nav.py 와 동일 문구). page_chrome_for 로 nav 라벨을
    # 단일 출처에서 끌어오는 통일은 후속(통합 담당) — 현재는 screen_frame 명시 문자열로 충분.
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="아차사고 조회",
        desc="아차사고 보고서를 조건별로 조회합니다.",
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

    # readiness 배너만 표시하고 차단하지 않는다(READ_VIEW — facade 가 미적용 시 빈 프레임으로
    # 안전하게 저하되므로 조회 자체는 막지 않는다).
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

    # 영역 순서(§0.3): title → top actions(조회·새로고침) → conditions → primary → status.
    acts = erp.top_action_bar(_PAGE_ID, [("조회", "primary"), ("새로고침", "default")])
    clicked = bool(acts.get("조회") or acts.get("새로고침"))
    q = _collect_conditions(scope, manager_dept, dept_names)

    saved = workspace.run_query(_PAGE_ID, clicked, q)
    if saved is None:
        ui.empty_state("조회 조건을 지정하고 [조회]를 눌러 아차사고 보고서를 확인하세요.", head="아차사고 조회")
        return

    # MANAGER 부서 범위는 저장된 조회조건(이전 세션 값일 수 있음)에도 항상 재적용한다
    # (workspace.schedule_screen 과 동일한 fail-closed 관행 — 위젯 잠금만 믿지 않는다).
    # 이 override 는 누수 방지의 핵심 통제이므로 매 렌더·facade 호출 직전에 무조건 실행한다.
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

    # primary — 읽기 그리드(색은 보조 신호, 한글 라벨 텍스트는 항상 유지).
    st.markdown(
        f"<div style='font-weight:600;color:{TOKENS['ink']};margin:2px 0 6px;'>"
        f"아차사고 보고서 목록 "
        f"<span style='color:{TOKENS['ink-2']};font-weight:400;'>· 조회 결과 {len(display)}건</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    status_rules = {label: _STATUS_COLOR[code] for code, label in _STATUS_LABEL.items()}
    erp.read_grid(
        display, columns=_DISPLAY_COLUMNS, key=f"{_PAGE_ID}_grid",
        col_config=_COL_CONFIG,
        color_rules={
            "제안등급": _GRADE_COLOR,
            "확정등급": _GRADE_COLOR,
            "상태": status_rules,
        },
    )

    # status — 요약(현재 필터된 결과 기준, raw status 코드로 집계).
    st.write("")
    counts = df["status"].astype(str)
    erp.status_region([
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


# ---------- 조회 조건(col-N 우측 인라인 라벨) ----------
def _collect_conditions(scope: str, manager_dept: str | None, dept_names: dict) -> dict:
    """조건 패널을 렌더하고 facade 조회조건 dict 를 만든다.

    필드 key 는 기존 위젯 key suffix 와 동일하게 유지해 세션 상태를 보존한다
    (period_on/from/to/dept/grade/status/cause). 기간 미지정 시 날짜 필드는 비활성.
    """
    period_on = bool(st.session_state.get(f"{_PAGE_ID}_period_on", False))

    if scope == "scoped":
        dept_field = erp.Field(
            key="dept", label="부서", kind="select",
            options=[manager_dept], disabled=True,
            format_func=lambda c: dept_names.get(c, c),
        )
    else:
        dept_field = erp.Field(
            key="dept", label="부서", kind="select",
            options=[workspace.ALL] + sorted(dept_names),
            format_func=lambda c: dept_names.get(c, c),
        )

    fields = [
        erp.Field(key="period_on", label="기간 지정", kind="checkbox", value=False),
        erp.Field(key="from", label="발생일(시작)", kind="date",
                  value=date.today() - timedelta(days=90), disabled=not period_on),
        erp.Field(key="to", label="발생일(종료)", kind="date",
                  value=date.today(), disabled=not period_on),
        dept_field,
        erp.Field(key="grade", label="확정등급", kind="select",
                  options=[workspace.ALL] + list(db.NEAR_MISS_GRADES)),
        erp.Field(key="status", label="상태", kind="select",
                  options=[workspace.ALL] + list(db.NEAR_MISS_STATUSES),
                  format_func=lambda v: _STATUS_LABEL.get(v, v) if v != workspace.ALL else v),
        erp.Field(key="cause", label="원인", kind="select",
                  options=[workspace.ALL] + list(db.NEAR_MISS_CAUSE_CODES),
                  format_func=lambda v: _CAUSE_LABEL.get(v, v) if v != workspace.ALL else v),
    ]
    v = erp.condition_panel(_PAGE_ID, fields, cols=3)

    on = bool(v["period_on"])
    return {
        "dept": v["dept"],
        "grade": v["grade"],
        "status": v["status"],
        "cause": v["cause"],
        "period_on": on,
        "date_from": v["from"].isoformat() if on else "",
        "date_to": v["to"].isoformat() if on else "",
    }


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
