"""내 숙소 예약 — 테이블 선택형(DESIGN.md §0 MASTER_DETAIL) + 신청 상태 수정 · 취소.

    제목/설명 → [지표 스트립] → [기간·상태 조건] → [예약 테이블(행 클릭 = 선택)]
    → [선택 건 전체폭 상세: 진행 단계 · 메타 · 처리 의견 · 액션]

2026-08-07 재검수 결정(D1): 목록형 아코디언 대신 **테이블 + 전체폭 상세**로 전환했다 —
예약이 쌓이면 아코디언은 기간·상태를 세로로만 훑게 해 비교가 어렵고, 펼침 상태에 따라
행 위치가 흔들린다. 승인 관리와 같은 목록 어휘(``erp.select_grid``)를 쓰되 이 화면은
USER 소관이라 행 피치 44px(터치 variant)이고, 상세 열기는 **행 클릭**이다(체크박스 마커
없음 — §0-1).

- 좌우 분할·"예약을 선택하세요" 빈 패널 없음(§0 금지 1·2 — 진입 시 첫 행 자동 선택).
  카드 금지(§0-5).
- 목록 범위는 위젯이 아니라 **인증 세션 사번**으로 고정한다(타인 건 열람 방지).
- 수정(신청 상태만)·취소 게이트는 화면이 아니라 ``lodging_data.update_reservation`` /
  ``action_blocker`` 가 서버측에서 재확인한다. 수정 시 겹치는 예약이 있으면
  :class:`ld.ReservationConflict` 를 팝업으로 알린다(신청 화면과 동일 계약).
- 취소는 되돌릴 수 없으므로 실행 전에 확인 팝업을 거친다(D2) — 팝업은 표시 계층의
  오조작 방지이고, 권한·상태 판정은 여전히 ``run_action`` 이 소유한다.
"""
# DESIGN.md §0 MASTER_DETAIL — 목록(테이블 선택) + 전체폭 상세/워크플로.
SCREEN_ARCHETYPE = "MASTER_DETAIL"

from datetime import date

import pandas as pd
import streamlit as st

from modules import lodging_data as ld
from views.common import erp, proto, scaffold
from views.master import DraftState, banner, show_flash

_STATE = DraftState("lodging_my")
_PAGE_ID = _STATE.page_id
_KEY_FIELD = "_rid"
_SEL_KEY = "lmy_selected_no"
_EDIT_KEY = "lmy_edit_open_"
_CONFIRM_KEY = "lmy_cancel_confirm"

_ALL = "전체"
_BADGE_CODE = {
    ld.REQUESTED: proto.BADGE_SUBMITTED,
    ld.APPROVED: proto.BADGE_EVALUATED,
    ld.COMPLETED: proto.BADGE_CLOSED,
    ld.REJECTED: proto.BADGE_REJECTED,
    ld.CANCELLED: proto.BADGE_CLOSED,
}
_STEP_ORDER = ((ld.REQUESTED, "신청"), (ld.APPROVED, "승인"), (ld.COMPLETED, "사용완료"))
_BRANCH_LABEL = {ld.REJECTED: "반려", ld.CANCELLED: "취소"}
# 상태 색은 승인 관리와 **같은 값**을 쓴다(같은 상태가 화면마다 다른 색이면 안 된다).
_STATUS_COLORS = {
    ld.STATUS_LABELS[ld.REQUESTED]: "#8a6212",
    ld.STATUS_LABELS[ld.APPROVED]: "#2f6b45",
    ld.STATUS_LABELS[ld.COMPLETED]: "#5c564d",
    ld.STATUS_LABELS[ld.REJECTED]: "#9c3232",
    ld.STATUS_LABELS[ld.CANCELLED]: "#5c564d",
}


def render(user: dict) -> None:
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="내 숙소 예약",
        desc="본인이 신청한 숙소 예약을 확인하고, 승인 전 건은 일정을 수정하거나 취소합니다.",
        breadcrumb="숙소 예약 › 내 숙소 예약",
        badges=scaffold.mode_badge(),
    )
    proto.inject()
    show_flash(_STATE)

    emp_no = ld.clean(user.get("emp_no"))
    if not emp_no:
        banner("warn", "로그인 사번을 확인할 수 없어 내 예약을 표시할 수 없습니다.")
        return
    try:
        rows = ld.filter_reservations(ld.load_reservations(), applicant_emp_no=emp_no)
    except ValueError as exc:
        banner("danger", str(exc))
        return

    if not rows:
        erp.detail_empty("신청한 숙소 예약이 없습니다",
                         "'숙소 예약 신청'에서 대관령·태안 숙소 사용을 신청할 수 있습니다.")
        return

    # §0-4·§4 영역 순서: 지표는 제목 바로 아래 첫 블록(필터보다 위). 값은 전체 내 예약
    # 기준이므로 필터와 무관하지만, 슬롯을 먼저 잡아 렌더 순서를 규약에 맞춘다.
    metric_slot = st.container()
    filters = _filters()
    date_from, date_to = filters["date_from"], filters["date_to"]
    if date_from and date_to and date_from > date_to:
        banner("warn", "조회 시작일이 종료일보다 늦어 기간 조건을 적용하지 않았습니다.")
        date_from = date_to = None
    shown = ld.filter_reservations(
        rows,
        statuses=None if filters["status"] == _ALL else (filters["status"],),
        date_from=date_from, date_to=date_to,
    )
    with metric_slot:
        erp.metric_strip(_metrics(rows))
        # 지표는 아래 조건과 무관하다는 사실을 말로 고정한다(LMY-4) — 숫자가 표 건수와
        # 달라 보이는 이유를 사용자가 추측하지 않게.
        proto.caption_line("지표는 조회 조건과 무관하게 내 예약 전체 기준입니다.")

    if not shown:
        erp.detail_empty("조건에 해당하는 예약이 없습니다", "기간·상태 조건을 조정해 보세요.")
        st.session_state.pop(_SEL_KEY, None)
        return

    ordered = sorted(shown, key=lambda r: (ld.clean(r.get("check_in")),
                                           ld.clean(r.get("request_no"))), reverse=True)
    numbers = [ld.clean(r.get("request_no")) for r in ordered]
    remembered = ld.clean(st.session_state.get(_SEL_KEY))
    if remembered not in numbers:
        remembered = numbers[0]      # 빈 상세 패널 금지(§0) — 진입 시 첫 행 자동 선택.

    picked = _render_table(ordered, remembered)
    selected = picked or remembered
    st.session_state[_SEL_KEY] = selected
    # 다른 건으로 옮기면 열려 있던 취소 확인은 대상이 바뀌므로 폐기한다(오확인 방지).
    if ld.clean(st.session_state.get(_CONFIRM_KEY)) not in ("", selected):
        st.session_state.pop(_CONFIRM_KEY, None)
    _detail(user, ordered, selected)


def _filters() -> dict:
    """기간(비우면 전체) + 상태. 기간은 숙박 기간과 조회 구간의 **겹침**으로 좁힌다 —
    예약이 쌓여도 원하는 시기의 건만 빠르게 찾기 위한 조건이다."""
    return erp.condition_panel(
        _PAGE_ID,
        [
            erp.Field(key="date_from", label="조회 시작일", kind="date", width=150,
                      help="숙박 기간이 조회 구간과 겹치는 예약을 보여줍니다. 비우면 제한 없음."),
            erp.Field(key="date_to", label="조회 종료일", kind="date", width=150,
                      help="비우면 제한 없음."),
            erp.Field(key="status", label="상태", width=150,
                      options=[_ALL] + list(ld.STATUSES),
                      format_func=lambda s: s if s == _ALL else ld.STATUS_LABELS.get(s, s)),
        ],
        content_fit=True,
    )


def _metrics(rows: list[dict]) -> list[tuple]:
    today = date.today()
    waiting = sum(1 for r in rows if ld.clean(r.get("status")) == ld.REQUESTED)
    approved = sum(1 for r in rows if ld.clean(r.get("status")) == ld.APPROVED)
    upcoming = sum(1 for r in rows
                   if ld.clean(r.get("status")) == ld.APPROVED
                   and (ld.to_date(r.get("check_in")) or date.min) >= today)
    closed = sum(1 for r in rows if ld.clean(r.get("status")) in ld.TERMINAL_STATUSES)
    return [
        ("내 예약", len(rows), "건", "MINE", len(rows) > 0),
        ("승인 대기", waiting, "건", "REQUESTED", waiting > 0),
        ("승인 확정", approved, "건", "APPROVED", False),
        ("다가오는 숙박", upcoming, "건", "UPCOMING", False),
        ("종결", closed, "건", "CLOSED", False),
    ]


# ===========================================================================
# 목록(테이블 선택)
# ===========================================================================
def _render_table(rows: list[dict], selected: str) -> str | None:
    """내 예약 테이블 — 행 클릭이 곧 선택이자 상세 열기(체크박스 마커 없음, §0-1).

    행 피치는 USER·터치 variant 44px(``erp.select_grid`` 계약)다 — 승인 관리(32px 큐
    밀도)와 달리 이 화면은 하루에 몇 번 보는 개인 목록이라 잘못 눌러 다른 건을 여는
    비용이 더 크다.
    """
    lodgings = ld.lodging_map()
    frame = pd.DataFrame([
        {
            _KEY_FIELD: ld.clean(r.get("request_no")),
            "신청번호": ld.clean(r.get("request_no")),
            "숙소": ld.lodging_label(lodgings.get(ld.clean(r.get("lodging_code")))),
            "체크인": ld.clean(r.get("check_in")),
            "체크아웃": ld.clean(r.get("check_out")),
            "박": str(ld.nights(r.get("check_in"), r.get("check_out"))),
            "상태": ld.STATUS_LABELS.get(ld.clean(r.get("status")), ld.clean(r.get("status"))),
            "신청일시": ld.clean(r.get("created_at")),
        }
        for r in rows
    ])
    col_config = {
        "신청번호": {"width": 150, "cellStyle": {"fontFamily": "'IBM Plex Mono', monospace"}},
        "숙소": {"width": 100},
        "체크인": {"width": 104},
        "체크아웃": {"width": 104},
        "박": {"width": 56},
        "상태": {"width": 88},
        "신청일시": {"flex": 1, "minWidth": 140},
    }
    return erp.select_grid(
        frame, key=f"{_PAGE_ID}_grid", key_field=_KEY_FIELD,
        columns=["신청번호", "숙소", "체크인", "체크아웃", "박", "상태", "신청일시"],
        selected_key=selected,
        color_rules={"상태": _STATUS_COLORS}, col_config=col_config,
        row_height=44, checkbox_marker=False,
    )


# ===========================================================================
# 전체폭 상세 + 일정 수정 + 액션
# ===========================================================================
def _detail(user: dict, rows: list[dict], request_no: str) -> None:
    """선택 건 상세: 진행 단계 pill → 메타 → 처리 의견 → 액션."""
    row = next((r for r in rows if ld.clean(r.get("request_no")) == request_no), None)
    if row is None:
        st.session_state.pop(_SEL_KEY, None)
        erp.detail_empty("이 예약은 더 이상 목록에 없습니다",
                         "조건이 바뀌었거나 상태가 변경됐습니다 — 새로고침한 뒤 다시 선택하세요.")
        return

    status = ld.clean(row.get("status"))
    lodging = ld.lodging_map().get(ld.clean(row.get("lodging_code")))
    proto.hairline(top="10px", bottom="4px")
    # 상세 앵커 한 줄: 신청번호 + 상태 배지 — 어떤 건을 보고 있는지만 고정한다(숙소·기간은
    # 바로 아래 메타 셀이 소유하므로 여기서 되풀이하지 않는다).
    st.markdown(
        "<div style='display:flex;flex-wrap:wrap;align-items:center;gap:10px;"
        "margin:2px 0 0;'>"
        f"<span style='font-family:{proto.MONO};font-size:16px;font-weight:600;"
        f"color:{proto.INK};'>{ld.clean(row.get('request_no'))}</span>"
        f"{proto.badge(_BADGE_CODE.get(status, proto.BADGE_CLOSED), ld.STATUS_LABELS.get(status, status))}"
        "</div>",
        unsafe_allow_html=True,
    )
    branch = (status, _BRANCH_LABEL[status]) if status in _BRANCH_LABEL else None
    st.markdown(proto.steps_html(list(_STEP_ORDER), status, branch=branch),
                unsafe_allow_html=True)

    comment = ld.clean(row.get("decision_comment"))
    if status == ld.REJECTED and comment:
        banner("warn", f"반려 사유: {comment}")

    st.markdown(proto.meta_cells([
        ("숙소", ld.lodging_label(lodging)),
        ("기간", ld.period_label(row)),
        ("신청일시", ld.clean(row.get("created_at"))),
        ("처리자", ld.clean(row.get("decided_by")) or "-"),
        ("처리일시", ld.clean(row.get("decided_at")) or "-"),
    ]), unsafe_allow_html=True)
    if comment and status != ld.REJECTED:
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        st.markdown(proto.body_blocks([
            ("DECISION", "처리 의견", comment, True),
        ]), unsafe_allow_html=True)

    proto.hairline(top="10px", bottom="4px")
    _render_actions(user, row, status)


def _render_actions(user: dict, row: dict, status: str) -> None:
    """본인 액션 — 신청 상태의 [일정 수정], 체크인 전의 [예약 취소]."""
    no = ld.clean(row.get("request_no"))
    can_edit = status == ld.REQUESTED
    cancel_block = ld.action_blocker(row, ld.ACT_CANCEL, user)

    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        if can_edit:
            if st.button("일정 수정", key=f"pract_edit_{no}", type="secondary",
                         width="content"):
                edit_key = f"{_EDIT_KEY}{no}"
                st.session_state[edit_key] = not bool(st.session_state.get(edit_key, False))
                st.rerun()
        if st.button("예약 취소", key=f"pract_cancel_{no}", type="secondary",
                     width="content", disabled=bool(cancel_block), help=cancel_block):
            st.session_state[_CONFIRM_KEY] = no
            st.rerun()
    # 수정 불가 사유는 취소 가능 여부와 무관하게 항상 알린다(LMY-3 — 종전에는 취소까지
    # 막힌 건에서만 떠서, 승인된 건에서 안내가 침묵했다).
    if not can_edit:
        proto.note_line("승인 전(신청 상태)에만 일정을 수정할 수 있고, 취소는 체크인 전까지 가능합니다.")

    if st.session_state.get(_CONFIRM_KEY) == no:
        _cancel_dialog(row, user)
    if can_edit and st.session_state.get(f"{_EDIT_KEY}{no}"):
        _render_edit_form(user, row)


@st.dialog("예약 취소 확인", width="large")
def _cancel_dialog(row: dict, user: dict) -> None:
    """취소는 되돌릴 수 없고 기간이 곧바로 풀리므로 실행 전에 한 번 확인한다(D2).

    표시 계층의 오조작 방지일 뿐이며 권한·상태 판정은 ``run_action`` 이 재확인한다.
    """
    no = ld.clean(row.get("request_no"))
    place = ld.lodging_label(ld.lodging_map().get(ld.clean(row.get("lodging_code"))))
    banner("warn", f"예약을 취소하시겠습니까 — {no} · {place} · {ld.period_label(row)}.")
    proto.note_line("취소하면 되돌릴 수 없으며 해당 기간은 다른 사람이 예약할 수 있게 됩니다.")
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        confirmed = st.button("예약 취소 확정", key="prdanger_lmy_cancel_ok",
                              width="content")
        if st.button("돌아가기", key="pract_lmy_cancel_back", type="secondary",
                     width="content"):
            st.session_state.pop(_CONFIRM_KEY, None)
            st.rerun()
    if confirmed:
        st.session_state.pop(_CONFIRM_KEY, None)
        _cancel(no, user)


@st.dialog("예약을 수정할 수 없습니다")
def _conflict_dialog(message: str) -> None:
    """수정 시점 중복 차단 팝업(신청 화면과 동일 계약)."""
    banner("danger", message)
    proto.note_line("겹치지 않는 일정으로 바꾸거나 '예약 캘린더'에서 빈 기간을 확인해 주세요.")
    if st.button("확인", key="lmy_conflict_ok", type="primary", width="stretch"):
        st.rerun()


def _render_edit_form(user: dict, row: dict) -> None:
    no = ld.clean(row.get("request_no"))
    lodgings = ld.load_lodgings(include_inactive=False)
    by_code = {ld.clean(l.get("lodging_code")): l for l in lodgings}
    codes = list(by_code)
    current_code = ld.clean(row.get("lodging_code"))
    with st.form(f"lmy_edit_{no}", clear_on_submit=False):
        c1, c2, c3 = st.columns([1.6, 1, 1])
        with c1:
            code = st.selectbox(
                "숙소", codes,
                index=codes.index(current_code) if current_code in codes else 0,
                format_func=lambda c: ld.lodging_label(by_code[c]),
            )
        with c2:
            check_in = st.date_input("체크인", format="YYYY-MM-DD",
                                     value=ld.to_date(row.get("check_in")) or date.today())
        with c3:
            check_out = st.date_input("체크아웃", format="YYYY-MM-DD",
                                      value=ld.to_date(row.get("check_out")) or date.today())
        saved = erp.form_submit("수정 저장")

    if not saved:
        return
    try:
        ld.update_reservation(no, {"lodging_code": code, "check_in": check_in,
                                   "check_out": check_out}, current_user=user)
    except ld.ReservationConflict as exc:
        _conflict_dialog(str(exc))
        return
    except ValueError as exc:
        banner("danger", f"수정하지 못했습니다 — {exc}")
        return
    except Exception:  # noqa: BLE001 — 저장 백엔드 오류(원문 비노출).
        banner("danger", "수정 중 오류가 발생했습니다. 목록을 재조회한 뒤 다시 시도하세요.")
        return
    st.session_state.pop(f"{_EDIT_KEY}{no}", None)
    _STATE.set_flash("success", f"{no} 일정을 수정했습니다.")
    st.rerun()


def _cancel(request_no: str, user: dict) -> None:
    try:
        ld.run_action(request_no, ld.ACT_CANCEL, current_user=user)
    except ValueError as exc:
        _STATE.set_flash("error", f"취소 처리 실패 — {exc}")
        st.rerun()
    except Exception:  # noqa: BLE001 — 저장 백엔드 오류(원문 비노출).
        _STATE.set_flash("error", "취소 처리 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.")
        st.rerun()
    _STATE.set_flash("success", f"{request_no} 예약을 취소했습니다.")
    st.rerun()
