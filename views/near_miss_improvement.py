"""개선조치 관리 — 종결 대기(EVALUATED) 큐 + CAPA 폐루프 상세.

DESIGN.md §0 화면 유형: ``MASTER_DETAIL`` — 조회 전용 목록(종결 대기 큐)과 그 옆
상세/워크플로 패널(개선조치 CAPA 폼 + scope 액션)로 구성한다. 상단 액션바는 조회
(새로고침)만 두고, 유일한 쓰기(저장·제출·확인·재조치요청·종결)는 상세 패널의 scope
액션(``erp.detail_actions``)이 담당한다 — 파사드 직접 호출, 그리드 저장 lifecycle 미사용.

목록 그리드는 중립 키트의 **단일 선택 어댑터**(``erp.select_grid``)를 쓴다 — 편집
렌더러(``render_master_grid``)의 ``_action`` 열·paste·hidden 편집메타·unsafe jscode 를
쓰지 않고 AgGrid 네이티브 single-selection(체크 마커 + 배경 틴트 이중부호화)으로 케이스를
고른다. 선택은 자연키(보고서 id)로 오가며(정렬·필터 후 위치 비의존), 상세 렌더 전에 소비해
추가 rerun 없이 상세를 그린다(§0.5 capability 분리 정합). 상세는 6화면 중 최밀(폼+역할별
버튼+2단계 종결)이라, 워크플로 클러스터(CAPA 폼 + scope 액션)를 상단 근처로 올리고 보고서
참조 서술(작업명·대책·현장 설명·원인)은 기본 접힘 expander 로 내려 스크롤 깊이를 줄인다.

007 개선조치(CAPA) 데이터층 배선
--------------------------------
평가 확정(EVALUATED)된 보고서에 대해 담당자/확인자/기한/조치를 기록하고, 제출→확인→
보고서 종결까지의 폐루프를 이 화면에서 운영한다. 인가·서버귀속·자기확인 차단·직접 CLOSED
차단·재개 원자성은 전부 ``modules/db.py`` 파사드/DB 소관이며, 이 화면은 호출·예외흡수·
게이트 표시만 한다(신원은 항상 ``auth.get_current_user()`` — 위젯 값이 아니다).

fail-closed(007 미적용): supabase 모드에서 007 스키마가 준비되지 않으면 목록·조회 구조는
표시하되 저장·제출·확인·재조치요청·종결 버튼을 전부 비활성화하고 readiness 배너로 사유를
안내한다. **가짜 성공·임시 데이터·sample fallback 을 만들지 않는다**(sample 모드는 세션
store 로 실제 동작하며 스모크 검증용이다).

파사드 호출(전부 ``modules/db.py`` 만 사용):
  - ``db.get_near_miss_reports({"status": "EVALUATED"})`` — 종결 대기 큐.
  - ``db.get_near_miss_improvement(report_id, current_user=)`` — 큐 enrich + 상세 폼 프리필
    (actor-aware, current_user 필수 — fail-open 없음).
  - ``db.upsert_near_miss_improvement(rid, payload, current_user=)`` — 조치 저장(DRAFT).
  - ``db.submit_near_miss_improvement(rid, current_user=)`` — 제출(DRAFT→SUBMITTED).
  - ``db.confirm_near_miss_improvement(rid, current_user=)`` — 확인(자기확인은 facade 차단).
  - ``db.reject_near_miss_improvement(rid, note, current_user=)`` — 재조치 요청(사유 필수).
  - ``db.close_near_miss_report(rid, current_user=)`` — 보고서 종결(2단계 확인 후, 불가역).
  - ``db.near_miss_improvement_schema_probe()`` — 007 준비 3-state 배너.
"""
from __future__ import annotations

# DESIGN.md §0 화면 유형 규약 — 읽기 목록(종결 대기 큐) + 상세/워크플로 패널.
SCREEN_ARCHETYPE = "MASTER_DETAIL"

from datetime import date
from html import escape

import pandas as pd
import streamlit as st

from modules import auth, db
from views.common import erp, scaffold
from views.master import (
    TOKENS,
    DraftState,
    Readiness,
    ReadinessState,
    banner,
    empty_state,
    icon_toolbar_specs,
    sheet_head,
    show_flash,
)

_STATE = DraftState("nm_impr")
_PAGE_ID = _STATE.page_id
_SEL_KEY = "nm_impr_selected_id"          # 상세에 열린 보고서 id(문자열).
_CLOSE_CONFIRM_KEY = "nm_impr_close_confirm"  # 2단계 종결 확인 중인 보고서 id.

_IMPROVEMENT_DESC = "평가 확정된 아차사고의 개선조치를 등록·확인하고 보고서를 종결합니다."

# 이 화면이 다루는 큐 — 평가 확정(EVALUATED) = 개선조치 진행·종결 대기.
_QUEUE_STATUS = "EVALUATED"

_SUBMIT_LABEL = {"DRAFT": "작성중", "SUBMITTED": "제출됨"}
_CONFIRM_LABEL = {"PENDING": "확인대기", "CONFIRMED": "확인됨", "REJECTED": "반려"}
_CONFIRM_COLOR = {
    "PENDING": TOKENS["gold"], "CONFIRMED": TOKENS["success"], "REJECTED": TOKENS["danger"],
    "미작성": TOKENS["ink-3"],
}
_SUBMIT_COLOR = {"DRAFT": TOKENS["ink-3"], "SUBMITTED": TOKENS["info"]}
# 확정등급 색·순서(§3.1: 등급=셰브런+색텍스트, pill 아님). S=최상위 위험. TOKENS 재사용.
_GRADE_COLOR = {
    "S": TOKENS["danger"], "A": TOKENS["gold"], "B": TOKENS["warn"],
    "C": TOKENS["info"], "D": TOKENS["ink-3"],
}
_GRADE_LEVEL = {"S": 4, "A": 3, "B": 2, "C": 1, "D": 0}


def _grade_mark(grade, empty: str = "-") -> str:
    """등급 마크(§3.1: 셰브런+색텍스트, pill 아님). 빈 값은 중립 점 마커(empty 라벨)."""
    g = str(grade or "").strip().upper()
    if not g:
        return erp.grade_mark_html(empty, TOKENS["ink-3"], level=None)
    return erp.grade_mark_html(g, _GRADE_COLOR.get(g, TOKENS["ink-2"]), level=_GRADE_LEVEL.get(g))


_CONFIRMED = "CONFIRMED"

# 큐 개선조치 조회 '실패' 표시 라벨 — '미작성'(정상 부재)과 명확히 구분한다. READY 이후의
# 실제 조회 오류를 정상 상태(미작성)로 위장하지 않기 위한 표식이며, 표면화(담당자·확인상태 열
# 라벨 '조회실패' + 상단 error 배너 + 담당자 시야 fail-closed)는 _queue_rows/_render_body 소관이다.
_LOAD_FAILED_LABEL = "조회실패"

_NOT_READY_MSG = (
    "개선조치 스키마(007)가 아직 적용되지 않아 저장·제출·확인·종결을 진행할 수 없습니다"
    "(조회만 가능). 스키마를 적용한 뒤 다시 시도하세요."
)
_PROBE_ERROR_MSG = (
    "개선조치 스키마 상태 확인 실패 — 재확인이 필요합니다(확인 전까지 쓰기는 차단됩니다)."
)
_STALE_MARK = "이미 변경"  # db 원문 일부 — stale 충돌(다른 사용자 선처리)은 warning 로 분기.

# 큐 표시 열 + 숨김 자연키(_report_id). 선택은 자연키로 오간다(정렬·필터 후 위치 비의존).
# 6화면 중 최밀 상세를 위해 목록은 CAPA 결정 열(식별·등급·담당·확인상태)만 남긴다 — 발생일은
# 큐가 발생일 내림차순 정렬이라 이미 반영되고 상세에도 표기되므로, @1024 좁은 폭 가로 스크롤을
# 없애기 위해 큐에서 뺀다(평가 파일럿이 제안등급을 뺀 것과 같은 밀도 결정).
_QUEUE_COLS = ["보고번호", "작업명", "확정등급", "담당자", "확인상태"]
_KEY_FIELD = "_report_id"  # 숨김 자연키 열(선택 반환값) — 표시 컬럼을 오염시키지 않는다.
# 폭 합(min ≈ 424 + chrome)을 @1024 좁은 목록 컬럼에 맞춰 가로 스크롤 0 을 보장한다(고정폭
# + 잔여는 flex 작업명/담당자가 흡수). @1366 넓은 폭에선 flex 두 열이 여유를 채운다.
_QUEUE_COL_CONFIG = {
    "보고번호": {"flex": 0, "width": 104, "minWidth": 88, "cellClass": "md-c-left"},
    "작업명": {"flex": 1.5, "minWidth": 96, "cellClass": "md-c-left"},
    "확정등급": {"flex": 0, "width": 60, "minWidth": 46, "maxWidth": 82, "cellClass": "md-c-center",
               "headerName": "등급"},  # 좁은 폭 유지 위해 헤더만 축약(큐에 제안등급 없어 무모호).
    "담당자": {"flex": 1.0, "minWidth": 92, "cellClass": "md-c-left"},
    "확인상태": {"flex": 0, "width": 84, "minWidth": 70, "maxWidth": 100, "cellClass": "md-c-center"},
}


def render(user: dict) -> None:
    # toolbar="icons": 상단 파랑 밴드를 공통 KPtech 아이콘 툴바로 통일한다. page-scope
    # 조회 액션은 새로고침뿐(search 아이콘 클릭의 rerun 만으로 재조회) — 쓰기는 상세 패널
    # scope 액션 소관이라 밴드 추가·삭제·저장은 N/A(shaded).
    band = erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="개선조치 관리",
        desc=_IMPROVEMENT_DESC,
        breadcrumb="아차사고 › 개선조치 관리",
        badges=scaffold.mode_badge(),
        toolbar="icons",
    )
    if band is not None:
        _na = "이 화면에서는 사용하지 않습니다"
        band.render_icons(icon_toolbar_specs(
            _PAGE_ID, info_content=_IMPROVEMENT_DESC,
            add={"key": f"{_PAGE_ID}__add_na", "disabled": True, "help": _na},
            refresh={"key": f"{_PAGE_ID}_refresh", "help": "새로고침", "on_click": None},
            delete={"key": f"{_PAGE_ID}__del_na", "disabled": True, "help": _na},
            save={"key": f"{_PAGE_ID}__save_na", "disabled": True, "help": _na},
        ))

    # 접근 경계는 nav route guard 가 이미 집행하지만, 화면 단독 진입가드로도 이중 방어한다.
    # 판정은 배정 기반 접근 facade(has_near_miss_improvement_access) — 평가자/ADMIN 즉시 True,
    # 배정된 담당자·지정 확인자(007 READY)는 True, 그 외/미인증/비활성은 False(fail-closed·
    # 비크래시). 007 미적용 supabase 에선 평가자/ADMIN 만 True 로 기존 fail-closed 와 정합한다.
    if not db.has_near_miss_improvement_access(user):
        empty_state(
            "개선조치 관리 권한이 없습니다",
            "배정된 담당자·지정 확인자, 또는 관리자·매니저·안전담당자만 개선조치를 다룰 수 있습니다.",
        )
        return
    _render_body(user)


def _readiness() -> ReadinessState:
    state = db.near_miss_improvement_schema_probe()
    if state == db.READINESS_READY:
        return ReadinessState.ready()
    if state == db.READINESS_PROBE_ERROR:
        return ReadinessState.probe_error(_PROBE_ERROR_MSG)
    return ReadinessState.not_ready(_NOT_READY_MSG)


def _render_body(user: dict) -> None:
    show_flash(_STATE)
    readiness = _readiness()
    readiness.banner()
    if readiness.state is Readiness.PROBE_ERROR:
        if st.button("스키마 재확인", key="nm_impr__recheck", icon=":material/refresh:"):
            db.near_miss_improvement_schema_probe(force=True)
            st.rerun()

    try:
        reports = _load_queue()
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"종결 대기 목록을 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("종결 대기 목록을 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    # 큐 스코핑은 actor-aware(list_near_miss_improvements) — 평가자/ADMIN 은 전체, 그 외
    # (담당자·지정 확인자)는 자기 배정건만. is_reviewer(=평가 능력)가 '전체 시야' 여부를
    # 가른다(개선조치 조회 없이도 즉시 판정 — 담당자 행 스코핑 결정에만 쓴다).
    is_reviewer = auth.can_evaluate_near_miss(user)
    improvements, load_failed = _improvements_for(reports, user)
    if load_failed:
        # 조회 실패를 '미작성/0'으로 삼키지 않고 표면화한다(오류≠정상 부재).
        st.error(
            "개선조치 목록을 불러오지 못했습니다 — 담당자·확인상태 열은 실제 상태가 아닙니다. "
            "데이터 연결 상태를 확인하고 새로고침하세요."
        )
    scoped = _scope_reports(reports, improvements, is_reviewer, load_failed)

    # 큐가 정확히 1건이면 자동 선택한다(0건은 상세 한 줄 empty). 담당자/평가자가 단건 큐에서
    # 굳이 클릭하지 않아도 상세·워크플로가 바로 열리게 해 상단 공백을 줄인다(§0.6 빈 surface 축소).
    selected_id = st.session_state.get(_SEL_KEY)
    if (selected_id is None and scoped is not None and not scoped.empty
            and len(scoped) == 1):
        selected_id = str(scoped.iloc[0]["id"])
        st.session_state[_SEL_KEY] = selected_id

    # 상세는 최밀(폼+역할별 버튼+2단계 종결) 워크플로형이라 §0.6 강제(상세 폭 ≥600px)에 맞춰
    # 목록 40%·상세 60%로 분할한다(1366 기준 상세 ≈660px). 목록은 첫 열(보고번호)·flex 작업명으로
    # 식별성을 유지하고 고정폭으로 가로 스크롤 0 을 노린다.
    list_col, detail_col = erp.master_detail_frame(list_ratio=1.0, detail_ratio=1.5)
    with list_col:
        picked = _render_queue(scoped, improvements, load_failed, selected_id)
    # 선택을 상세 렌더 **전에** 소비한다 — select_grid 의 selectionChanged rerun 이 이미
    # 일어난 run 이므로 여기서 세션만 갱신하면 추가 st.rerun 없이 곧바로 상세를 그린다.
    if picked is not None and picked != selected_id:
        st.session_state[_SEL_KEY] = picked
        st.session_state.pop(_CLOSE_CONFIRM_KEY, None)  # 케이스 전환 시 종결 확인 초기화.
        selected_id = picked
    with detail_col:
        _render_detail(user, readiness)

    _render_summary(scoped, improvements, load_failed)


# ---------- 데이터 적재 ----------
def _load_queue() -> pd.DataFrame:
    """종결 대기 = 평가 확정(EVALUATED) 활성 보고서. CLOSED 는 큐에서 빠진다."""
    df = db.get_near_miss_reports({"status": _QUEUE_STATUS})
    if df is None or df.empty:
        return df
    return df.reset_index(drop=True)


def _improvements_for(reports: pd.DataFrame, user: dict) -> tuple[dict, bool]:
    """보고서별 개선조치(report_id(str)→자연키 dict)와 조회 실패 플래그.

    actor-aware 큐 스코핑 facade(``list_near_miss_improvements``)로 한 번에 조회한다 —
    평가자/ADMIN 은 전체를, 그 외(담당자·지정 확인자)는 자신이 배정된 개선조치만 담긴다.
    dict 에 없는 report_id 는 (평가자 시야에선) 미작성/미배정, (담당자 시야에선) 자기
    배정건이 아님을 뜻한다.

    007 미준비면 facade 가 빈 dict 를 돌려주며(정상 부재 = '미작성'), 이는 readiness 배너로
    이미 안내된다. READY 이후의 실제 조회 오류는 빈 dict('미작성')로 위장하지 않고
    ``load_failed=True`` 로 표면화한다(오류≠정상 부재) — 큐 담당자·확인상태 열을 '조회실패'로
    구분 표시하고 상단 error 배너로 안내하며, 담당자 시야는 미스코핑 노출을 막기 위해 빈 큐로
    fail-closed 한다(``_scope_reports``)."""
    if reports is None or reports.empty:
        return {}, False
    report_ids = list(reports["id"].astype(str))
    try:
        return db.list_near_miss_improvements(report_ids, current_user=user), False
    except Exception:
        return {}, True


def _scope_reports(reports: pd.DataFrame, improvements: dict,
                   is_reviewer: bool, load_failed: bool) -> pd.DataFrame:
    """담당자(비평가자) 시야를 자기 배정건으로 좁힌다. 평가자/ADMIN 은 전체 유지.

    큐 보고서(EVALUATED)는 개선조치 조회와 독립이라, 담당자에게도 전량 보이면 미배정 건이
    노출된다 — actor-aware 개선조치 dict 의 report_id 로만 남긴다. 조회 실패 시 담당자는 어떤
    건이 자기 배정인지 알 수 없으므로 빈 큐로 fail-closed 한다(평가자/ADMIN 은 전체 유지·열
    라벨만 '조회실패')."""
    if reports is None or reports.empty or is_reviewer:
        return reports
    if load_failed:
        return reports.iloc[0:0]
    ids = set(improvements.keys())
    return reports[reports["id"].astype(str).isin(ids)].reset_index(drop=True)


def _user_label(emp_no) -> str:
    emp_no = str(emp_no or "").strip()
    if not emp_no:
        return ""
    try:
        record = db.find_user_by_emp_no(emp_no)
    except Exception:
        return emp_no
    name = str(record.get("name") or "").strip() if record else ""
    return f"{name}({emp_no})" if name else emp_no


def _confirm_state_of(imp) -> str:
    if not imp:
        return "미작성"
    return str(imp.get("confirm_status") or "").strip() or "미작성"


# ---------- 큐 그리드(단일 선택) ----------
def _queue_rows(reports: pd.DataFrame, improvements: dict, load_failed: bool) -> pd.DataFrame:
    """큐 표시 프레임 — 숨김 자연키(_report_id) + 표시 6열."""
    cols = [_KEY_FIELD, *_QUEUE_COLS]
    if reports is None or reports.empty:
        return pd.DataFrame(columns=cols)
    frame = reports.sort_values("incident_date", ascending=False, kind="stable").reset_index(drop=True)
    rows = []
    for _, r in frame.iterrows():
        rid = str(r.get("id"))
        imp = improvements.get(rid)
        if load_failed:
            # 조회 실패는 '미지정/미작성'(정상)으로 위장하지 않고 두 열을 '조회실패'로 표시한다.
            assignee = _LOAD_FAILED_LABEL
            confirm_label = _LOAD_FAILED_LABEL
        elif imp:
            assignee = _user_label(imp.get("assignee_emp_no"))
            confirm_state = _confirm_state_of(imp)
            confirm_label = _CONFIRM_LABEL.get(confirm_state, confirm_state)
        else:
            assignee = "미지정"
            confirm_label = _CONFIRM_LABEL.get("미작성", "미작성")
        rows.append({
            _KEY_FIELD: rid,
            "보고번호": str(r.get("report_no") or "-"),
            "작업명": str(r.get("work_name") or "-"),
            "확정등급": str(r.get("confirmed_grade") or "-"),
            "담당자": assignee,
            "확인상태": confirm_label,
        })
    return pd.DataFrame(rows, columns=cols)


def _confirm_color_rules() -> dict:
    """확인상태 셀 색 규칙(한글 라벨 → 색). 텍스트 라벨은 항상 유지(색은 보조 신호)."""
    rules = {_CONFIRM_LABEL[s]: _CONFIRM_COLOR[s] for s in ("PENDING", "CONFIRMED", "REJECTED")}
    rules["미작성"] = _CONFIRM_COLOR["미작성"]
    return rules


def _render_queue(reports: pd.DataFrame, improvements: dict, load_failed: bool,
                  selected_id) -> str | None:
    """종결 대기 큐를 단일 선택 목록으로 렌더하고 선택된 보고서 자연키를 돌려준다.

    편집 그리드가 아니라 ``erp.select_grid``(네이티브 single-selection) — 행 클릭으로
    케이스를 고르면 체크 마커 + 배경 틴트로 이중부호화되고, 선택 자연키(_report_id)를
    반환한다(정렬·필터 후 위치 비의존)."""
    rows = _queue_rows(reports, improvements, load_failed)
    sheet_head("종결 대기 큐", count=len(rows))
    return erp.select_grid(
        rows, key=f"{_PAGE_ID}_queue", key_field=_KEY_FIELD,
        columns=_QUEUE_COLS, selected_key=selected_id,
        col_config=_QUEUE_COL_CONFIG,
        color_rules={"확인상태": _confirm_color_rules()},
    )


# ---------- 상세 패널 ----------
def _render_detail(user: dict, readiness: ReadinessState) -> None:
    selected_id = st.session_state.get(_SEL_KEY)
    if not selected_id:
        erp.detail_empty("케이스를 선택하세요", "왼쪽 큐에서 행을 클릭하면 개선조치를 등록·확인할 수 있습니다.")
        return

    try:
        report = db.get_near_miss_report(selected_id)
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"케이스를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("케이스를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    status = str(report.get("status") or "") if report else ""
    if report is None or status != _QUEUE_STATUS:
        # 다른 사용자가 먼저 종결(CLOSED)했거나 재개(IN_REVIEW)됐거나 삭제됨 — stale 선택 해제.
        st.session_state.pop(_SEL_KEY, None)
        st.session_state.pop(_CLOSE_CONFIRM_KEY, None)
        erp.detail_empty(
            "이 케이스는 더 이상 종결 대기 상태가 아닙니다",
            "다른 사용자가 먼저 처리했을 수 있습니다. 목록을 새로고침한 뒤 다시 선택하세요.",
        )
        return

    # 개선조치 프리필 조회 실패를 None('미작성')으로 접으면, 기존 개선조치가 있는데도
    # 빈 폼처럼 보여 덮어쓰기 저장 위험이 있다 — 오류를 표면화하고 폼/액션을 열지 않는다
    # (report 조회 실패 처리와 동일 관행). 007 미준비의 정상 None 은 여기 도달 전
    # facade 가 None 을 돌려주며 readiness 배너가 이미 안내한다.
    try:
        imp = db.get_near_miss_improvement(selected_id, current_user=user)
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"개선조치를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("개선조치를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    # 행단위 인가(재감사 #1) — 이 개선조치(imp)에 대한 actor 의 능력으로 폼 편집·버튼을 가른다.
    #   can_work   = 저장된 담당자 본인 또는 ADMIN → 작업필드 편집·조치저장·제출.
    #   can_review = 지정 확인자 본인 또는 평가자/ADMIN → 확인·재조치요청·보고서 종결.
    #   can_assign = 평가자/ADMIN → 담당자·확인자 배정(select) 편집.
    # facade 가 서버측 인가·필드 strip 을 전담하지만, 화면도 같은 경계를 표시해 혼동을 막는다
    # (읽기전용 필드·미표시 버튼). 신원은 항상 auth.get_current_user() — 위젯 값이 아니다.
    can_work = auth.can_work_improvement(user, imp)
    can_review = auth.can_review_improvement(user, imp)
    can_assign = auth.can_evaluate_near_miss(user)

    # ── 상단: 보고번호 + 워크플로 상태 배지(제출·확인, 색+라벨 이중부호화) ──
    _render_detail_head(report, imp)
    # ── 짧은 메타 2열 + 핵심 내용(사고 내용, 전폭) ──
    _render_report_context(report)

    # ── 워크플로 클러스터(CAPA 폼 + 역할별 scope 액션) — 핵심 내용 바로 뒤(fold 근처) ──
    st.markdown(
        f"<div style='border-top:1px solid {TOKENS['line']};margin:12px 0 2px;'></div>",
        unsafe_allow_html=True,
    )
    form = _render_capa_form(selected_id, imp, readiness, can_work=can_work, can_assign=can_assign)
    _render_actions(user, report, imp, form, readiness,
                    can_work=can_work, can_review=can_review, can_assign=can_assign)

    # ── 부차 참조 서술(작업명·작업 내용·대책·현장 설명·원인) — 기본 접힘으로 상세 높이 bound. ──
    _render_report_reference(report)


def _render_detail_head(report: dict, imp) -> None:
    """보고번호(제목 §2 20/700) + 제출·확인 워크플로 배지(색+라벨 이중부호화)."""
    report_no = escape(str(report.get("report_no") or "-"))
    submit_status = str(imp.get("submit_status") or "") if imp else ""
    confirm_status = _confirm_state_of(imp)
    submit_badge = erp.status_badge_html(
        _SUBMIT_LABEL.get(submit_status, "미작성"),
        _SUBMIT_COLOR.get(submit_status, TOKENS["ink-3"]))
    confirm_badge = erp.status_badge_html(
        _CONFIRM_LABEL.get(confirm_status, confirm_status),
        _CONFIRM_COLOR.get(confirm_status, TOKENS["ink-3"]))
    lbl = f"color:{TOKENS['ink-2']};font-size:12px;"
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:2px 0 8px;'>"
        f"<span style='font-size:20px;font-weight:700;color:{TOKENS['ink']};"
        f"line-height:1.2;'>{report_no}</span>"
        f"<span style='{lbl}'>제출</span>{submit_badge}"
        f"<span style='{lbl}'>확인</span>{confirm_badge}</div>",
        unsafe_allow_html=True,
    )


def _render_report_context(report: dict) -> None:
    """읽기 메타 스트립(§3.2: 신고자·발생일·부서·확정등급 상시 노출) + 핵심 내용(사고 내용).

    형식 분리(§3.1): 확정등급=grade_mark(셰브런+색텍스트, pill 아님) / 나머지=평문. 제출·확인
    워크플로 상태는 상단 head 의 이중 배지(pill)가 소유한다(보고 lifecycle 과 별개 축)."""
    erp.metadata_strip([
        ("신고자", _user_label(report.get("reporter_emp_no"))),
        ("발생일", str(report.get("incident_date") or "-")),
        ("부서", str(report.get("dept_code") or "-")),
        ("확정등급", _grade_mark(report.get("confirmed_grade"), empty="-"), "html"),
    ])
    erp.field_block("사고 내용", str(report.get("incident_content") or ""))


def _render_report_reference(report: dict) -> None:
    """참조성 긴 서술(작업명·작업 내용·대책·현장 설명·원인)을 기본 접힘 expander 로 내린다.

    워크플로 클러스터가 이 위에 있으므로 장문 케이스에서도 주요 행동(저장·제출·확인·종결)이
    긴 서술에 밀리지 않는다(§0.4 sticky/fixed 미사용, st.expander 네이티브 접기만)."""
    with st.expander("보고서 상세 더 보기", expanded=False):
        erp.field_block("작업명", str(report.get("work_name") or ""))
        erp.field_block("작업 내용", str(report.get("work_content") or ""))
        erp.field_block("대책", str(report.get("countermeasure") or ""))
        erp.field_block("현장 설명", str(report.get("site_description") or ""))
        cause = str(report.get("cause_code") or "")
        cause_detail = str(report.get("cause_detail") or "")
        cause_val = cause + (f" · {cause_detail}" if cause_detail else "")
        if cause_val.strip():
            erp.field_block("원인", cause_val)


def _user_options() -> tuple[list[str], dict]:
    """활성 사용자 select 옵션(빈 항목 포함) + emp_no→라벨 사전."""
    try:
        df = db.get_users()
    except Exception:
        return [""], {"": "— 선택 —"}
    labels: dict = {"": "— 선택 —"}
    options = [""]
    if df is not None and not df.empty:
        for _, r in df.iterrows():
            if not bool(r.get("is_active", True)):
                continue
            emp = str(r.get("emp_no") or "").strip()
            if not emp:
                continue
            name = str(r.get("name") or "").strip()
            labels[emp] = f"{name}({emp})" if name else emp
            options.append(emp)
    return options, labels


def _select_index(options: list[str], value) -> int:
    value = str(value or "").strip()
    return options.index(value) if value in options else 0


def _render_capa_form(selected_id, imp, readiness: ReadinessState,
                      *, can_work: bool, can_assign: bool) -> dict:
    """CAPA 입력 폼(담당자·확인자·기한·조치 내용/결과). 반환은 위젯 현재값.

    행단위 편집 경계: 배정 필드(담당자·확인자)는 can_assign(평가자/ADMIN)만, 작업 필드
    (기한·조치 내용/결과)는 can_work(배정 담당자 본인·ADMIN)만 편집 가능하고 그 외에는
    읽기전용(disabled)으로 표시한다 — facade 가 어차피 strip 하지만 화면도 경계를 드러내
    혼동을 막는다. 읽기전용이라도 위젯은 저장된 값을 반환하므로 반환 dict 는 온전하다.
    (제출·확인 상태 배지는 상세 상단 헤더 _render_detail_head 로 이관했다.)"""
    confirm_status = _confirm_state_of(imp)
    if imp and confirm_status == "REJECTED" and str(imp.get("revision_note") or "").strip():
        banner("warn", f"재조치 요청 사유: {str(imp.get('revision_note')).strip()}")

    options, labels = _user_options()
    fmt = lambda emp: labels.get(emp, emp)  # noqa: E731

    if not can_assign:
        st.caption("담당자·확인자 배정은 평가자·관리자만 변경할 수 있습니다.")
    c1, c2 = st.columns(2)
    with c1:
        assignee = st.selectbox(
            "조치 담당자", options,
            index=_select_index(options, imp.get("assignee_emp_no") if imp else ""),
            format_func=fmt, key=f"nm_impr_assignee_{selected_id}",
            disabled=not can_assign,
        )
    with c2:
        confirmer = st.selectbox(
            "조치 확인자", options,
            index=_select_index(options, imp.get("designated_confirmer_emp_no") if imp else ""),
            format_func=fmt, key=f"nm_impr_confirmer_{selected_id}",
            disabled=not can_assign,
        )

    if not can_work:
        st.caption("조치 내용·결과·기한은 배정된 담당자만 편집할 수 있습니다(조회 전용).")
    due_raw = str(imp.get("due_date") or "").strip() if imp else ""
    try:
        due_default = date.fromisoformat(due_raw) if due_raw else date.today()
    except ValueError:
        due_default = date.today()
    # 조치 기한(단일 날짜)은 내용 맞춤 폭(§0.6 강제: 전폭 컨트롤 금지).
    due = st.date_input("조치 기한", value=due_default, format="YYYY-MM-DD",
                        key=f"nm_impr_due_{selected_id}", disabled=not can_work, width=180)

    action_body = st.text_area(
        "조치 내용", value=str(imp.get("action_body") or "") if imp else "",
        height=80, key=f"nm_impr_action_{selected_id}", disabled=not can_work,
    )
    result_body = st.text_area(
        "조치 결과", value=str(imp.get("result_body") or "") if imp else "",
        height=80, key=f"nm_impr_result_{selected_id}", disabled=not can_work,
    )
    return {
        "assignee_emp_no": assignee,
        "designated_confirmer_emp_no": confirmer,
        "due_date": due.isoformat() if due else "",
        "action_body": action_body,
        "result_body": result_body,
    }


def _render_actions(user: dict, report: dict, imp, form: dict, readiness: ReadinessState,
                    *, can_work: bool, can_review: bool, can_assign: bool) -> None:
    """행단위 역할 variant scope 액션(§0.4). 버튼 노출을 능력으로 가른다:

      - can_work(담당자/ADMIN): 조치 저장·제출.
      - can_assign(평가자/ADMIN): 배정 저장(담당자·확인자 지정).
      - can_review(확인자/평가자/ADMIN): 확인·재조치 요청·보고서 종결.

    버튼 활성은 readiness·status 에 더해 위 행단위 능력으로 판정한다(재감사 #1). 자기확인
    (담당자==세션) 시 확인은 disabled+help 로 남기고 facade 도 차단한다. 실제 쓰기·신원전달
    (auth.get_current_user())·예외흡수는 이 화면 소관이다."""
    selected_id = str(report.get("id"))
    can_write = readiness.write_enabled
    actor_emp = str(user.get("emp_no") or "").strip()

    submit_status = str(imp.get("submit_status") or "") if imp else ""
    confirm_status = _confirm_state_of(imp)
    stored_assignee = str(imp.get("assignee_emp_no") or "").strip() if imp else ""

    is_confirmed = confirm_status == _CONFIRMED
    is_submitted = submit_status == "SUBMITTED"
    is_pending = is_submitted and confirm_status == "PENDING"
    self_confirm = bool(stored_assignee) and stored_assignee.casefold() == actor_emp.casefold()

    # 재조치 요청 사유(전용 필드 — 반려와 별개 의미)는 검토 권한자만 본다. 제출·확인대기일 때만 입력.
    reject_reason = ""
    if can_review:
        reject_reason = str(st.text_area(
            "재조치 요청 사유(요청 시 필수)", key=f"nm_impr_reject_{selected_id}", height=52,
            disabled=(not can_write) or not is_pending,
        ) or "").strip()

    actions: list[tuple] = []

    # ---- 저장(작업 or 배정) — can_work 또는 can_assign. 라벨로 무엇을 저장하는지 드러낸다. ----
    save_label = None
    if can_work or can_assign:
        save_disabled = (not can_write) or is_confirmed
        save_help = readiness.message if not can_write else (
            "확인된 개선조치는 수정할 수 없습니다." if is_confirmed else None)
        if can_work and can_assign:
            save_label = "저장"          # ADMIN(또는 담당자 겸 평가자): 배정+작업 동시(facade 두 branch).
        elif can_work:
            save_label = "조치 저장"       # 담당자: 작업필드만(배정필드 facade strip).
        else:
            save_label = "배정 저장"       # 평가자: 담당자·확인자 배정만(작업필드 facade strip).
        actions.append((save_label, "default", save_disabled, save_help))

    # ---- 제출 — can_work(담당자/ADMIN)만. 비담당 평가자에겐 미표시. ----
    if can_work:
        submit_disabled = (not can_write) or submit_status != "DRAFT"
        if not can_write:
            submit_help = readiness.message
        elif imp is None:
            submit_help = "먼저 조치를 저장한 뒤 제출하세요."
        elif submit_status != "DRAFT":
            submit_help = "이미 제출된 개선조치입니다."
        else:
            submit_help = None
        actions.append(("제출", "primary", submit_disabled, submit_help))

    # ---- 확인·재조치 요청 — can_review(확인자/평가자/ADMIN)만. 담당자에겐 미표시. ----
    if can_review:
        confirm_disabled = (not can_write) or not is_pending or self_confirm
        if not can_write:
            confirm_help = readiness.message
        elif not is_pending:
            confirm_help = "제출된(확인대기) 개선조치만 확인할 수 있습니다."
        elif self_confirm:
            confirm_help = "조치 담당자 본인은 확인할 수 없습니다(자기확인 금지)."
        else:
            confirm_help = None

        reject_disabled = (not can_write) or not is_pending or not reject_reason
        if not can_write:
            reject_help = readiness.message
        elif not is_pending:
            reject_help = "제출된(확인대기) 개선조치만 재조치를 요청할 수 있습니다."
        elif not reject_reason:
            reject_help = "재조치 요청 사유를 입력하세요."
        else:
            reject_help = None

        actions.append(("확인", "primary", confirm_disabled, confirm_help))
        actions.append(("재조치 요청", "default", reject_disabled, reject_help))

    clicks = erp.detail_actions(_PAGE_ID, actions)

    if save_label and clicks.get(save_label):
        _run_action(save_label, lambda: db.upsert_near_miss_improvement(
            selected_id, dict(form), current_user=auth.get_current_user(),
        ), keep_selection=True)
    if clicks.get("제출"):
        # 저장 안 된(위젯만 채운) 상태 제출 방지: 먼저 현재 폼을 저장하고 제출한다.
        _run_action("제출", lambda: _save_then_submit(selected_id, form), keep_selection=True)
    if clicks.get("확인"):
        _run_action("확인", lambda: db.confirm_near_miss_improvement(
            selected_id, current_user=auth.get_current_user(),
        ), keep_selection=True)
    if clicks.get("재조치 요청"):
        _run_action("재조치 요청", lambda: db.reject_near_miss_improvement(
            selected_id, reject_reason, current_user=auth.get_current_user(),
        ), keep_selection=True)

    # 종결 액션은 파괴적(불가역)이라 워크플로 버튼과 분리하고 2단계 확인을 강제한다.
    # 검토 권한자(확인자/평가자/ADMIN)만 노출 — 담당자 뷰엔 종결이 아예 표시되지 않는다.
    if can_review:
        close_disabled = (not can_write) or not is_confirmed
        close_help = readiness.message if not can_write else (
            None if is_confirmed else "확인된 개선조치가 있어야 보고서를 종결할 수 있습니다.")
        _render_close(report, imp, close_disabled, close_help)


def _save_then_submit(report_id, form: dict) -> dict:
    """제출 직전 현재 폼을 DRAFT 로 저장한 뒤 SUBMITTED 로 전이한다(담당자/결과 누락은 facade 차단)."""
    db.upsert_near_miss_improvement(report_id, dict(form), current_user=auth.get_current_user())
    return db.submit_near_miss_improvement(report_id, current_user=auth.get_current_user())


# ---------- 2단계 종결(불가역) ----------
def _render_close(report: dict, imp, disabled: bool, help_: str | None) -> None:
    selected_id = str(report.get("id"))
    close_clicks = erp.detail_actions(f"{_PAGE_ID}_close", [
        ("보고서 종결", "primary", disabled, help_),
    ])
    if close_clicks.get("보고서 종결") and not disabled:
        st.session_state[_CLOSE_CONFIRM_KEY] = selected_id
        st.rerun()

    if st.session_state.get(_CLOSE_CONFIRM_KEY) != selected_id:
        return

    # 인라인 확인 영역 — 보고번호·확정등급·확인된 개선조치 요약 + 불가역 고지.
    report_no = str(report.get("report_no") or "-")
    grade = str(report.get("confirmed_grade") or "-")
    result_summary = str((imp or {}).get("result_body") or "").strip() or "(조치 결과 없음)"
    if len(result_summary) > 80:
        result_summary = result_summary[:80] + "…"
    banner(
        "warn",
        f"보고서 종결(불가역): {report_no} · 확정등급 {grade} · 확인된 개선조치 "
        f"“{result_summary}”. 종결하면 이후 전이가 없습니다.",
    )
    confirm_clicks = erp.detail_actions(f"{_PAGE_ID}_close2", [
        ("종결 확정", "primary", disabled, help_),
        ("취소", "default", False, None),
    ])
    if confirm_clicks.get("취소"):
        st.session_state.pop(_CLOSE_CONFIRM_KEY, None)
        st.rerun()
    if confirm_clicks.get("종결 확정") and not disabled:
        st.session_state.pop(_CLOSE_CONFIRM_KEY, None)
        _run_action("보고서 종결", lambda: db.close_near_miss_report(
            selected_id, current_user=auth.get_current_user(),
        ))


# ---------- 하단 요약 ----------
def _render_summary(reports: pd.DataFrame, improvements: dict, load_failed: bool) -> None:
    total = 0 if reports is None or reports.empty else len(reports)
    if load_failed:
        # 조회 실패를 '진행·미작성 0'으로 접으면 오류가 정상 진행처럼 보인다 — 실패로 명시한다.
        erp.status_region([("종결 대기", f"{total}건"), ("개선조치", "조회 실패")])
        return
    confirmed = sum(1 for imp in improvements.values()
                    if imp and str(imp.get("confirm_status") or "") == _CONFIRMED)
    # scoped 큐 기준(평가자=전체 EVALUATED, 담당자=자기 배정건) 확인완료/진행·미작성 집계.
    in_progress = max(total - confirmed, 0)
    erp.status_region([
        ("종결 대기", f"{total}건"),
        ("확인 완료", f"{confirmed}건"),
        ("진행·미작성", f"{in_progress}건"),
    ])


# ---------- 액션 실행(예외 흡수) ----------
def _flash_kind_for(exc: Exception) -> str:
    return "warning" if _STALE_MARK in str(exc) else "error"


def _run_action(label: str, call, *, keep_selection: bool = False) -> None:
    """scope 액션 공통 실행 — 예외를 흡수해 raw traceback 을 노출하지 않는다
    (2단계 배너: 제목 + 파사드 원문 사유, stale 은 가공 없이 그대로 노출).

    ``keep_selection`` 이면 처리 후에도 상세를 열어둔다(재조치 요청·저장 등 큐에 남는 액션).
    종결처럼 큐에서 빠지는 액션은 선택을 닫는다."""
    try:
        call()
    except ValueError as exc:
        _STATE.set_flash(_flash_kind_for(exc), f"{label} 처리 실패 — {exc}")
        st.rerun()
    except db.DATA_SOURCE_ERRORS as exc:
        _STATE.set_flash("error", f"{label} 처리 중 오류가 발생했습니다: {exc}")
        st.rerun()
    except Exception:
        _STATE.set_flash("error", f"{label} 처리 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.")
        st.rerun()
    _STATE.set_flash("success", f"{label} 완료.")
    if not keep_selection:
        st.session_state.pop(_SEL_KEY, None)
    st.rerun()
