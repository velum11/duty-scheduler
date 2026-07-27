"""아차사고 평가 화면 — 대기 큐(그리드) + 케이스 상세 드릴다운.

DESIGN.md §0 화면 유형: ``MASTER_DETAIL``. 이 화면은 다건 인라인 편집·저장 그리드가
아니라, 조회 전용 목록(큐)과 그 옆 상세/워크플로 패널로 구성된 읽기 목록 + 상세 화면이다
(§0.8/§0.1 유형 매뉴페스트: MASTER_DETAIL = 읽기 목록 + 상세/워크플로). 상단 액션바는
page-scope 조회 액션(새로고침)만 두고, 유일한 쓰기(평가확정/반려)는 상세 패널의
scope 액션(``erp.detail_actions``)이 담당한다 — 파사드 직접 호출, 그리드 저장 lifecycle
미사용(이 화면은 다건 편집·저장이 아니라 단건 상태전이라 ``run_save`` 대상이 아니다).
목록 그리드 자체는 ``views/master`` 의 ``render_master_grid``/``MasterGridSpec``(행 클릭
선택 JsCode 포함)을 그대로 쓴다 — 중립 키트에는 아직 선택 가능한 read_grid 가 없어
그 추출은 후속(BACKLOG)으로 미루고, 목록 렌더 로직 자체는 이전 그대로 유지한다.

권한 게이트: ``auth.can_evaluate_near_miss(user)`` — ADMIN/MANAGER 또는 안전담당자만
평가할 수 있다(``modules/auth.py``). 게이트를 통과하지 못하면 조회 전용 안내만 보여주고
그리드·상세 패널을 렌더하지 않는다.

파사드 호출(전부 ``modules/db.py`` 만 사용, repository 직접 호출 없음):
  - ``db.get_near_miss_reports(filters)`` — 목록 조회 후 SUBMITTED/IN_REVIEW 만
    화면에서 필터링(파사드는 단일 status 필터만 지원하므로 두 상태는 클라이언트 측에서
    골라낸다).
  - ``db.get_near_miss_report(report_id)`` — 상세 패널 단건 재조회(선택 갱신·행위 직전
    최신 상태 확인).
  - ``db.evaluate_near_miss(report_id, grade, current_user=...)`` — 평가확정
    (SUBMITTED/IN_REVIEW 에서만 허용, 서버측에서 평가자·시각을 확정한다).
  - ``db.update_near_miss_status(report_id, "REJECTED", rejection_reason=,
    current_user=...)`` — 반려 상태전이(전이표 밖이면 ValueError).
  - ``db.near_miss_schema_probe()`` — migration 006 준비 상태(3-state) 배너.

신원 위조 방지: 두 쓰기 호출 모두 ``current_user=auth.get_current_user()`` 를 그대로
넘긴다(위젯 입력이 아니라 세션 사용자) — 파사드가 사번을 다시 DB 에서 확인해 평가자를
서버측으로 확정한다(``modules/db.py::_near_miss_actor``).

stale 처리: 두 파사드 모두 사전평가 상태(SUBMITTED/IN_REVIEW)를 조건부로 확인하고,
다른 평가자가 먼저 처리했으면 정확한 문구("상태가 이미 변경되어...")를 담은
``ValueError`` 를 낸다. 이 화면은 그 메시지를 원문 그대로 배너에 노출한다(가공/삭제
금지) — 새 예외 텍스트를 만들지 않는다. 배너는 2단계(제목 + 원문 사유) 패턴이며 raw
traceback 은 절대 노출하지 않는다(``_run_action``).
"""
# DESIGN.md §0 화면 유형 규약 — 읽기 목록(큐) + 상세/워크플로 패널.
SCREEN_ARCHETYPE = "MASTER_DETAIL"

from html import escape

import pandas as pd
import streamlit as st
from st_aggrid import JsCode

from modules import auth, db, nav
from views.common import erp, scaffold
from views.master import (
    DraftState,
    MasterGridSpec,
    Readiness,
    ReadinessState,
    count_strip,
    empty_state,
    icon_toolbar_specs,
    master_grid_height,
    render_master_grid,
    sheet_head,
    show_flash,
)

_STATE = DraftState("nm_eval")
_PAGE_ID = _STATE.page_id  # erp.top_action_bar/detail_actions 위젯 key 스코프(동일 page_id).

# 이 화면이 다루는 "평가 대기" 상태 — 파사드 NEAR_MISS_STATUSES 의 부분집합.
# db.evaluate_near_miss 의 _NEAR_MISS_PRE_EVAL_STATES 와 같은 집합(소스 오브 트루스는
# db.py 이며 여기서는 화면 필터링용으로 상수만 복제한다).
_PENDING_STATUSES = ("SUBMITTED", "IN_REVIEW")

_STATUS_LABEL = {
    "SUBMITTED": "제출됨",
    "IN_REVIEW": "검토중",
    "EVALUATED": "평가완료",
    "REJECTED": "반려",
    "CLOSED": "종결",
}

_NOT_READY_MSG = (
    "아차사고 스키마가 준비되지 않아 평가를 진행할 수 없습니다(조회만 가능). "
    "스키마를 적용한 뒤 다시 시도하세요."
)
_PROBE_ERROR_MSG = (
    "아차사고 스키마 상태 확인 실패 — 재확인이 필요합니다(확인 전까지 평가는 차단됩니다)."
)
_STALE_MARK = "이미 변경"  # db._NEAR_MISS_STALE_MESSAGE 원문 일부 — kind 분기용(warning vs error).

_QUEUE_COLS = ["신고자", "작업명", "제안등급", "발생일", "상태"]
_QUEUE_ROW_COLS = ["_row_id", "_row_state", "_sel", *_QUEUE_COLS]
_QUEUE_GRID_COLUMNS = {c: "text" for c in _QUEUE_COLS}
_QUEUE_COL_CONFIG = {
    "신고자": {"flex": 0, "width": 128, "minWidth": 100, "cellClass": "md-c-left", "editable": False},
    "작업명": {"flex": 1.6, "minWidth": 140, "cellClass": "md-c-left", "editable": False},
    "제안등급": {"flex": 0, "width": 80, "minWidth": 66, "maxWidth": 96,
               "cellClass": "md-c-center", "editable": False},
    "발생일": {"flex": 0, "width": 102, "minWidth": 90, "maxWidth": 122,
              "cellClass": "md-c-center", "editable": False},
    "상태": {"flex": 0, "width": 88, "minWidth": 76, "maxWidth": 108,
            "cellClass": "md-c-center", "editable": False},
}

_SEL_KEY = "nm_eval_selected_id"  # 상세 패널에 열린 보고서 id(문자열). 케이스 이탈 시 pop.

# 행 클릭 드릴다운 — master_org.py 의 _DRILL_CLICK 패턴을 단순화(이 그리드는 전 컬럼
# 비편집·다건 선택 없음이므로 _action 열 분기 없이 모든 컬럼 클릭을 단일 열림으로 다룬다).
_ROW_CLICK = JsCode(
    """
    function(e) {
      var d = (e.node && e.node.data) || {};
      if (d._row_state !== 'existing') { return; }
      if (d._linked === '1' || d._linked === 1) { return; }
      e.api.forEachNode(function(node) {
        var nd = node.data || {};
        var want = (node === e.node) ? '1' : '';
        if (String(nd._linked || '') !== want) { node.setDataValue('_linked', want); }
      });
    }
    """
)


def render(user: dict) -> None:
    band = erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="평가 관리",
        desc="등록된 아차사고를 검토해 등급을 확정하거나 반려합니다.",
        breadcrumb="아차사고 › 평가 관리",
        badges=scaffold.mode_badge(),
        toolbar="icons",
    )
    # 상단 파랑 밴드 아이콘 툴바(공통 표준). 이 화면의 page-scope 조회 액션은 새로고침
    # 뿐이다 — search 아이콘 클릭이 유발하는 rerun 만으로 _load_pending_reports() 가 매
    # 렌더 무조건 재조회한다(구 pill 과 동일 — on_click 없이 클릭=rerun). 평가확정·반려
    # (쓰기)는 상세 패널 scope 액션 소관이라 밴드 추가·삭제·저장은 N/A(shaded).
    if band is not None:
        band.render_icons(icon_toolbar_specs(
            _PAGE_ID, info_content=nav.page_desc("near_miss_evaluate"),
            add={"key": f"{_PAGE_ID}__add_na", "disabled": True,
                 "help": "이 화면에서는 사용하지 않습니다"},
            refresh={"key": f"{_PAGE_ID}_refresh", "help": "새로고침", "on_click": None},
            delete={"key": f"{_PAGE_ID}__del_na", "disabled": True,
                    "help": "이 화면에서는 사용하지 않습니다"},
            save={"key": f"{_PAGE_ID}__save_na", "disabled": True,
                  "help": "이 화면에서는 사용하지 않습니다"},
        ))
    if not auth.can_evaluate_near_miss(user):
        empty_state(
            "평가 권한이 없습니다",
            "관리자·매니저 또는 안전담당자만 아차사고를 평가할 수 있습니다.",
        )
        return
    _render_body(user)


def _readiness() -> ReadinessState:
    state = db.near_miss_schema_probe()
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
        if st.button("스키마 재확인", key="nm_eval__recheck", icon=":material/refresh:"):
            db.near_miss_schema_probe(force=True)
            st.rerun()

    # page-scope 조회 액션(새로고침)은 상단 밴드 아이콘으로 이전했다(render 의 render_icons).
    # 아이콘 클릭이 유발하는 rerun 만으로 아래 _load_pending_reports() 가 매 렌더 무조건
    # 재조회하므로 별도 배선이 필요 없다(인페이지 pill 제거).

    try:
        reports = _load_pending_reports()
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"평가 대기 목록을 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("평가 대기 목록을 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    list_col, detail_col = erp.master_detail_frame(list_ratio=1.5, detail_ratio=1.0)
    with list_col:
        grid_df = _render_queue(reports, readiness)
    with detail_col:
        _render_detail(user, readiness)

    picked = _picked_report_id(grid_df)
    if picked is not None and picked != st.session_state.get(_SEL_KEY):
        st.session_state[_SEL_KEY] = picked
        st.rerun()


# ---------- 데이터 적재 ----------
def _load_pending_reports() -> pd.DataFrame:
    """활성 아차사고 중 평가 대기(SUBMITTED/IN_REVIEW)만. 단일 status 필터만 지원하는
    파사드 계약이라 두 상태는 여기서 클라이언트 측으로 골라낸다."""
    df = db.get_near_miss_reports({})
    if df is None or df.empty:
        return df
    mask = df["status"].astype(str).isin(_PENDING_STATUSES)
    return df[mask].reset_index(drop=True)


def _reporter_label(emp_no) -> str:
    emp_no = str(emp_no or "").strip()
    if not emp_no:
        return ""
    try:
        record = db.find_user_by_emp_no(emp_no)
    except Exception:
        # 이름 라벨링은 부가 정보 — 조회 실패로 큐/상세 렌더 전체를 막지 않고 사번만 표시한다.
        return emp_no
    name = str(record.get("name") or "").strip() if record else ""
    return f"{name}({emp_no})" if name else emp_no


def _flag(cond) -> str:
    return "1" if bool(cond) else ""


def _queue_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=_QUEUE_ROW_COLS)
    frame = df.sort_values("incident_date", ascending=False, kind="stable").reset_index(drop=True)
    rows = pd.DataFrame({
        "_row_id": "e:" + frame["id"].astype(str),
        "_row_state": "existing",
        "_sel": False,
        "신고자": frame["reporter_emp_no"].map(_reporter_label),
        "작업명": frame["work_name"].fillna("").astype(str),
        "제안등급": frame["proposed_grade"].fillna("").astype(str),
        "발생일": frame["incident_date"].fillna("").astype(str),
        "상태": frame["status"].astype(str).map(lambda s: _STATUS_LABEL.get(s, s)),
    })
    return rows[_QUEUE_ROW_COLS].reset_index(drop=True)


def _queue_display(rows: pd.DataFrame, selected_id) -> pd.DataFrame:
    frame = rows.copy() if rows is not None else pd.DataFrame(columns=_QUEUE_ROW_COLS)
    if frame.empty:
        return frame
    target = f"e:{selected_id}" if selected_id else None
    frame["_linked"] = (
        (frame["_row_id"].astype(str) == str(target)).map(_flag) if target else ""
    )
    return frame


def _picked_report_id(grid_df: pd.DataFrame):
    """클릭으로 열린(=_linked) 행의 보고서 id(문자열). 클릭·데이터 없으면 None."""
    if grid_df is None or "_linked" not in grid_df.columns or "_row_id" not in grid_df.columns:
        return None
    linked = grid_df[
        (grid_df["_row_state"].astype(str) == "existing")
        & (grid_df["_linked"].astype(str).str.strip() == "1")
    ]
    if linked.empty:
        return None
    rid = str(linked.iloc[0]["_row_id"]).strip()
    return rid[2:] if rid.startswith("e:") else rid


# ---------- 큐 그리드 ----------
def _render_queue(reports: pd.DataFrame, readiness: ReadinessState) -> pd.DataFrame:
    selected_id = st.session_state.get(_SEL_KEY)
    rows = _queue_rows(reports)
    sheet_head("평가 대기 큐", count=len(rows))

    spec = MasterGridSpec(
        page_id=_STATE.page_id, columns=_QUEUE_GRID_COLUMNS, order=_QUEUE_COLS,
        col_config=_QUEUE_COL_CONFIG, select_all=False, include_linked_rows=True,
        grid_options={"onCellClicked": _ROW_CLICK},  # 행 클릭 → 상세 패널 열기(드릴다운)
        height=master_grid_height(len(rows)),
    )
    grid_df = render_master_grid(spec, _queue_display(rows, selected_id), key=_STATE.grid_key())

    # 이 큐는 조회 전용이다 — 행 추가/삭제/저장은 이 화면의 책임이 아니다(평가/반려는
    # 상세 패널 전용 버튼이 파사드를 직접 호출한다). page-scope 액션바(erp.top_action_bar)의
    # 새로고침만이 유일한 이 화면 액션이며, 그리드 자체 action열/편집도 없다(전 컬럼
    # editable=False) — 이 카운트 스트립은 "케이스를 클릭해 상세에서 평가"하라는 안내 없이도
    # 목록 규모만 보이면 충분하다.
    count_strip(len(rows), 0, 0, 0)
    return grid_df


# ---------- 상세 패널 ----------
def _render_detail(user: dict, readiness: ReadinessState) -> None:
    selected_id = st.session_state.get(_SEL_KEY)
    if not selected_id:
        erp.detail_empty("케이스를 선택하세요", "왼쪽 큐에서 행을 클릭하면 상세 내용이 여기에 표시됩니다.")
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
    if report is None or status not in _PENDING_STATUSES:
        # 다른 평가자가 먼저 처리했거나(EVALUATED/REJECTED/CLOSED) 삭제됨 — stale 선택 해제.
        st.session_state.pop(_SEL_KEY, None)
        erp.detail_empty(
            "이 케이스는 더 이상 대기 중이 아닙니다",
            "다른 사용자가 먼저 처리했을 수 있습니다. 목록을 새로고침한 뒤 다시 선택하세요.",
        )
        return

    st.markdown(
        f"### {escape(str(report.get('report_no') or ''))} · "
        f"{escape(_STATUS_LABEL.get(status, status))}",
    )
    st.caption(
        f"신고자 {escape(_reporter_label(report.get('reporter_emp_no')))} · "
        f"발생일 {escape(str(report.get('incident_date') or '-'))} · "
        f"부서 {escape(str(report.get('dept_code') or '-'))}"
    )

    st.markdown(f"**작업명** {escape(str(report.get('work_name') or '-'))}")
    st.text_area("작업 내용", value=str(report.get("work_content") or ""),
                 height=68, disabled=True, key=f"nm_wc_{selected_id}")
    st.text_area("사고 내용", value=str(report.get("incident_content") or ""),
                 height=88, disabled=True, key=f"nm_ic_{selected_id}")
    st.text_area("대책", value=str(report.get("countermeasure") or ""),
                 height=68, disabled=True, key=f"nm_cm_{selected_id}")
    st.text_area("현장 설명", value=str(report.get("site_description") or ""),
                 height=68, disabled=True, key=f"nm_sd_{selected_id}")

    cause = str(report.get("cause_code") or "")
    cause_detail = str(report.get("cause_detail") or "")
    st.caption(f"원인 코드 {escape(cause)}" + (f" · {escape(cause_detail)}" if cause_detail else ""))

    photos = report.get("photo_paths") or []
    if photos:
        st.caption(f"첨부 사진 {len(photos)}건 (뷰어 미구현 — 자리표시)")
    else:
        st.caption("첨부된 사진이 없습니다.")

    proposed = str(report.get("proposed_grade") or "")
    st.caption(f"제안 등급 {escape(proposed) if proposed else '없음'}")

    grades = list(db.NEAR_MISS_GRADES)
    default_idx = grades.index(proposed) if proposed in grades else 0
    grade = st.selectbox("확정 등급", grades, index=default_idx, key=f"nm_grade_{selected_id}")

    can_write = readiness.write_enabled
    reason = st.text_area(
        "반려 사유(반려 시 필수)", key=f"nm_reason_{selected_id}", height=56, disabled=not can_write,
    )

    # 상세 패널 scope 액션(§0.4) — 실제 쓰기는 이 두 버튼만 담당한다(page 액션바에는
    # 없음). disabled/help 판정은 여기서 그대로 계산해 넘기고, erp.detail_actions 는
    # 순수 UI(버튼 렌더 + 클릭 반환)만 담당한다 — facade 호출·current_user 전달·
    # 오류/stale 처리는 이 화면(아래 클릭 분기 + ``_run_action``)이 그대로 소유한다.
    eval_disabled = not can_write
    eval_help = None if can_write else readiness.message

    reject_disabled = (not can_write) or not str(reason or "").strip()
    reject_help = readiness.message if not can_write else (
        None if str(reason or "").strip() else "반려 사유를 입력하세요."
    )

    # 종결(EVALUATED→CLOSED)은 이 평가 대기 화면의 책임이 아니다 — 큐가 SUBMITTED/IN_REVIEW
    # 만 담아 여기서는 항상 비활성일 수밖에 없었다. 종결 UI 는 향후 개선조치 관리 화면에서
    # 재설계하며(별도 제품 결정 — BACKLOG 추적), db.py 의 EVALUATED→CLOSED 전이 능력
    # 자체는 데이터 계약으로 그대로 유지한다(이 화면에서 버튼만 제거).
    clicks = erp.detail_actions(_PAGE_ID, [
        ("평가확정", "primary", eval_disabled, eval_help),
        ("반려", "default", reject_disabled, reject_help),
    ])

    if clicks.get("평가확정"):
        _run_action(user, "평가확정", lambda: db.evaluate_near_miss(
            selected_id, grade, current_user=auth.get_current_user(),
        ))
    if clicks.get("반려"):
        _run_action(user, "반려", lambda: db.update_near_miss_status(
            selected_id, "REJECTED", rejection_reason=reason, current_user=auth.get_current_user(),
        ))


def _flash_kind_for(exc: Exception) -> str:
    """stale 충돌(다른 평가자가 먼저 처리)은 warning, 그 외 검증 실패는 error."""
    return "warning" if _STALE_MARK in str(exc) else "error"


def _run_action(user: dict, label: str, call) -> None:
    """평가/반려 공통 실행 — 예외를 여기서 흡수해 raw traceback 을 노출하지 않는다
    (2단계 배너: 제목 + 파사드 원문 사유, stale 메시지는 가공 없이 그대로 노출)."""
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
    st.session_state.pop(_SEL_KEY, None)  # 처리된 케이스는 큐에서 빠지므로 상세 패널을 닫는다.
    st.rerun()
