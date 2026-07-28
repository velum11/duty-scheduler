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
from html import escape

import pandas as pd
import streamlit as st

from modules import db, nav, ui
from views import workspace
from views.common import erp
from views.common import scaffold
from views.master import TOKENS, banner, icon_toolbar_specs, sheet_head
from views.master.lifecycle import Readiness, ReadinessState

_PAGE_ID = "near_miss_view"
# 선택형 목록 자연키(항상 hidden) + 선택 상태 세션키. 선택은 자연키(id)로 오간다
# (정렬·필터 후 위치 비의존). 필터/새로고침 시 _SEL_KEY 를 해제한다.
_KEY_FIELD = "_report_id"
_SEL_KEY = "nm_view_selected_id"

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
    band = erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="아차사고 조회",
        desc="아차사고 보고서를 조건별로 조회합니다.",
        breadcrumb="아차사고 › 조회",
        badges=scaffold.mode_badge(),
        toolbar="icons",
    )
    # 상단 파랑 밴드 아이콘 툴바(기준정보·근무표 편성과 동일 표준). 조회/새로고침(search
    # 아이콘)만 활성 — 클릭은 on_click 플래그로 남겨 아래에서 소비한다(구 pill 의 조회·
    # 새로고침 OR clicked 게이트와 동일). 추가·삭제·저장은 조회 전용이라 N/A(shaded).
    if band is not None:
        band.render_icons(icon_toolbar_specs(
            _PAGE_ID, info_content=nav.page_desc(_PAGE_ID),
            add={"key": f"{_PAGE_ID}__add_na", "disabled": True,
                 "help": "이 화면에서는 사용하지 않습니다"},
            refresh={"key": f"{_PAGE_ID}_go", "help": "조회/새로고침",
                     "on_click": lambda: st.session_state.update({f"{_PAGE_ID}_go_req": True})},
            delete={"key": f"{_PAGE_ID}__del_na", "disabled": True,
                    "help": "이 화면에서는 사용하지 않습니다"},
            save={"key": f"{_PAGE_ID}__save_na", "disabled": True,
                  "help": "이 화면에서는 사용하지 않습니다"},
        ))

    # 접근 범위(제품 결정 — Coordinator): 아차사고 조회는 전 사용자에게 열려 있고
    # 회사 전체 범위이며, 신고자 이름·상세 내용을 숨기지 않는다. 과거 평가자 전용 게이트
    # (auth.can_evaluate_near_miss)와 MANAGER 부서 스코프(_scope_for)는 이 경로에서
    # 제거했다. _scope_for 정의 자체는 회귀 계약(scripts/test_near_miss_view.py)이
    # 고정하고 있어 남겨두되(과거 스코프 동작 보존), render 는 더 이상 호출하지 않는다.
    _readiness().banner()

    try:
        dept_names = _all_dept_names()
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"조직 정보를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("조직 정보를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    # 영역 순서(§0.3): title(밴드 아이콘 툴바) → conditions → primary(선택형 목록) →
    # details(선택 보고서 상세) → status(조회 결과 규모=건수만). 조회/새로고침 클릭 플래그를
    # 소비한다(위 render_icons on_click 이 남긴 플래그).
    clicked = bool(st.session_state.pop(f"{_PAGE_ID}_go_req", False))
    if clicked:
        # 필터/새로고침으로 결과 집합이 바뀌면 이전 선택을 해제한다(stale 상세 방지).
        st.session_state.pop(_SEL_KEY, None)
    q = _collect_conditions("all", None, dept_names)

    saved = workspace.run_query(_PAGE_ID, clicked, q)
    if saved is None:
        ui.empty_state("조회 조건을 지정하고 [조회]를 눌러 아차사고 보고서를 확인하세요.", head="아차사고 조회")
        return

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
        st.session_state.pop(_SEL_KEY, None)  # 빈 결과 → 선택 해제
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

    # primary — 선택형 목록(select_grid). 구 st.selectbox 상세 선택을 없애고 행 클릭이 상세
    # 선택을 대체한다(Codex: 목록 클릭=상세). 네이티브 single-selection: 색 틴트+체크박스로
    # 이중부호화(§4), 선택 자연키(_report_id)를 반환한다. 등급/상태 색은 보조 신호(라벨 유지).
    frame = _select_frame(df, display)
    sheet_head("아차사고 보고서 목록", count=len(frame))
    status_rules = {label: _STATUS_COLOR[code] for code, label in _STATUS_LABEL.items()}
    picked = erp.select_grid(
        frame, key=f"{_PAGE_ID}_grid", key_field=_KEY_FIELD,
        columns=_DISPLAY_COLUMNS, selected_key=st.session_state.get(_SEL_KEY),
        col_config=_COL_CONFIG,
        color_rules={
            "제안등급": _GRADE_COLOR,
            "확정등급": _GRADE_COLOR,
            "상태": status_rules,
        },
    )
    # 선택을 상세 렌더 전에 소비한다 — select_grid 의 selectionChanged rerun 이 이미 일어난
    # run 이므로 세션만 갱신하면 추가 st.rerun 없이 곧바로 상세를 그린다(즉시 상세).
    if picked is not None and picked != st.session_state.get(_SEL_KEY):
        st.session_state[_SEL_KEY] = picked

    # details — 선택 보고서 상세(조회 전용). 신고자 이름·상세 내용을 숨기지 않는다.
    st.write("")
    _render_result_detail(df)

    # status — 조회 결과 규모(건수만 슬림). 평가대기/평가완료/종결·반려 집계는 분석(stats)
    # 소관으로 이관했다(KPI 중복 제거 — 집계는 stats 소유).
    st.write("")
    erp.status_region([("조회 건수", f"{len(df)}건")])


def _select_frame(df: pd.DataFrame, display: pd.DataFrame) -> pd.DataFrame:
    """9열 표시 프레임에 숨김 자연키(_report_id)를 붙인 select_grid 입력 프레임.

    ``_to_display`` 는 df.iterrows() 순서로 9열을 만들므로 df 의 id 를 같은 순서(위치)로
    실으면 행이 정합한다(select_grid 가 자연키로 위치 비의존 선택을 보장). 표시 9열은
    ``_to_display`` 계약(테스트 고정)을 건드리지 않고 그대로 재사용한다."""
    frame = display.copy()
    frame[_KEY_FIELD] = [str(r.get("id")) for _, r in df.iterrows()]
    return frame


def _render_result_detail(df: pd.DataFrame) -> None:
    """선택 행(_SEL_KEY)의 보고서 상세를 그룹2 표시 어휘로 조회 전용 렌더한다.

    쓰기 액션(detail_actions) 없음 — READ_VIEW 는 순수 조회다. 상태 badge → (반려 사유
    배너) → 짧은 메타 2열 → 핵심 내용(작업명·사고내용) → 부차 서술 접기 순으로, 신고자
    이름·전체 내용을 숨기지 않는다(전사 공개 조회 계약)."""
    selected_id = st.session_state.get(_SEL_KEY)
    if not selected_id:
        erp.detail_empty("보고서를 선택하세요",
                         "위 목록에서 행을 클릭하면 신고자·상세 내용을 확인할 수 있습니다.")
        return
    match = df[df["id"].astype(str) == str(selected_id)]
    if match.empty:
        # 목록에서 사라진 stale 선택 — 해제하고 미선택 상태로 되돌린다.
        st.session_state.pop(_SEL_KEY, None)
        erp.detail_empty("보고서를 선택하세요",
                         "선택한 보고서를 목록에서 찾을 수 없습니다. 목록에서 다시 선택하세요.")
        return
    report = match.iloc[0].to_dict()

    # 신고자 이름·부서명 라벨링(부가 정보) — 조회 실패로 상세 전체를 막지 않고 코드로 폴백한다.
    try:
        users = db.get_users()
        depts = db.get_departments()
    except Exception:
        users = pd.DataFrame()
        depts = pd.DataFrame()
    name_of = {str(r["emp_no"]): str(r["name"]) for _, r in users.iterrows()} if not users.empty else {}
    dept_of = {str(r["dept_code"]): str(r["dept_name"]) for _, r in depts.iterrows()} if not depts.empty else {}

    emp = _clean(report.get("reporter_emp_no"))
    dept = _clean(report.get("dept_code"))
    status = _clean(report.get("status"))
    cause = _clean(report.get("cause_code"))

    # ── 상단: 보고번호 + 상태 배지(색+라벨 이중부호화) ──
    report_no = escape(_clean(report.get("report_no")) or "(번호 미상)")
    badge = erp.status_badge_html(
        _STATUS_LABEL.get(status, status or "-"),
        _STATUS_COLOR.get(status, TOKENS["ink-3"]),
    )
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:2px 0 8px;'>"
        f"<span style='font-size:20px;font-weight:700;color:{TOKENS['ink']};"
        f"line-height:1.2;'>{report_no}</span>{badge}</div>",
        unsafe_allow_html=True,
    )

    # ── 반려 사유(있을 때) — 종결 분기의 경고 배너. ──
    if status == "REJECTED" and _clean(report.get("rejection_reason")):
        banner("warn", f"반려 사유: {_clean(report.get('rejection_reason'))}")

    # ── 짧은 메타 2열 + 핵심 내용(작업명·사고내용, 전폭) ──
    left = [
        ("신고자", name_of.get(emp, emp) or "-"),
        ("소속", dept_of.get(dept, dept) or "-"),
        ("발생일", _clean(report.get("incident_date")) or "-"),
    ]
    right = [
        ("제안등급", _clean(report.get("proposed_grade")) or "없음"),
        ("확정등급", _clean(report.get("confirmed_grade")) or "미정"),
        ("발생원인", _CAUSE_LABEL.get(cause, cause) or "-"),
    ]
    mc1, mc2 = st.columns(2)
    mc1.markdown(erp.meta_col_html(left), unsafe_allow_html=True)
    mc2.markdown(erp.meta_col_html(right), unsafe_allow_html=True)
    erp.field_block("작업명", _clean(report.get("work_name")))
    erp.field_block("사고내용", _clean(report.get("incident_content")))

    # ── 부차 참조 서술(발생원인 상세·작업내용·예방대책·현장 상황) 기본 접힘으로 상세 높이 bound. ──
    with st.expander("보고서 상세 더 보기", expanded=False):
        cause_detail = _clean(report.get("cause_detail"))
        if cause_detail:
            erp.field_block("발생원인 상세", cause_detail)
        erp.field_block("작업내용", _clean(report.get("work_content")))
        erp.field_block("예방대책", _clean(report.get("countermeasure")))
        erp.field_block("작업현장 상황설명", _clean(report.get("site_description")))


def _all_dept_names() -> dict:
    """부서코드→부서명 전체 맵(회사 전체 범위 조건 드롭다운·표시용)."""
    depts = db.get_departments()
    if depts.empty:
        return {}
    return {str(r["dept_code"]): str(r["dept_name"]) for _, r in depts.iterrows()}


# ---------- 접근 범위(fail-closed) — 회귀 계약(test_near_miss_view)이 고정. 현재 render 는
# 회사 전체 공개로 전환되어 이 함수를 호출하지 않는다(정의만 보존). ----------
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
