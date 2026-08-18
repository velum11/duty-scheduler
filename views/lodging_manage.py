"""숙소 예약 승인 관리 — 테이블 선택형(DESIGN.md §0 MASTER_DETAIL).

    제목/설명 → [지표 스트립] → 헤어라인 → [범위 칩] → [예약 테이블(체크박스 선택)]
    → [선택 건 상세] → 헤어라인 → [액션 바: 의견 | 일정 수정 취소 반려 사용완료 승인]
    → [비활성 사유 줄] → [일정 수정 폼(신청 건)]

2026-08-07 사용자 결정: 칩 큐 대신 **테이블 형식 + 체크박스 선택**으로 재편했다.
목록은 ``erp.select_grid`` (AG Grid 단일 선택 + 체크박스 마커) — 행 선택이 곧 상세다.
본인 예약의 조회·수정·취소는 '내 숙소 예약' 소관이라 이 화면은 **승인권자 전용**이다.

- 액션 활성/비활성 사유는 ``lodging_data.action_blocker`` 단일 출처를 그대로 툴팁에 쓴다.
- 신청(REQUESTED) 건은 승인권자가 일정(숙소·기간)을 정정할 수 있다
  (``update_reservation`` — 2026-08-07 결정). 겹치는 예약이 있으면 팝업으로 알린다.
- 승인 시 확정(승인·사용완료) 겹침 백스톱은 유지한다(신청 시점 차단의 경합 보루).
"""
# DESIGN.md §0 MASTER_DETAIL — 목록(테이블 선택) + 전체폭 상세/워크플로.
SCREEN_ARCHETYPE = "WORKLIST"

from datetime import date

import pandas as pd
import streamlit as st

from modules import lodging_data as ld
from views.common import erp, proto, scaffold
from views.master import DraftState, banner, empty_state, show_flash

_STATE = DraftState("lodging_manage")
_PAGE_ID = _STATE.page_id
_KEY_FIELD = "_rid"
_SEL_KEY = "lm_selected_no"
_SCOPE_KEY = "lm_scope"
_OP_KEY = "lm_opinion_"
_EDIT_KEY = "lm_edit_open_"
_CONFIRM_KEY = "lm_cancel_confirm"

SCOPE_PENDING = "승인 대기"
SCOPE_ALL = "전체"

_BADGE_CODE = {
    ld.REQUESTED: proto.BADGE_SUBMITTED,
    ld.APPROVED: proto.BADGE_EVALUATED,
    ld.COMPLETED: proto.BADGE_CLOSED,
    ld.REJECTED: proto.BADGE_REJECTED,
    ld.CANCELLED: proto.BADGE_CLOSED,
}
# 액션 표시 순서(주 액션 = 우측 primary, §1-A 액션 바).
# [취소]는 되돌릴 수 없는 파괴적 액션이라 primary([승인]) 바로 옆에 두지 않는다 —
# 사이에 최소 두 버튼(반려·사용완료)을 두어 오클릭 거리를 확보한다(D2, 2026-08-07 재검수).
_ACTION_ORDER = (
    (ld.ACT_CANCEL, "secondary"),
    (ld.ACT_REJECT, "secondary"),
    (ld.ACT_COMPLETE, "secondary"),
    (ld.ACT_APPROVE, "primary"),
)


def render(user: dict) -> None:
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="숙소 예약 승인 관리",
        desc="신청된 예약을 검토해 승인·반려하고, 필요하면 일정을 정정하거나 취소합니다.",
        breadcrumb="숙소 예약 › 승인 관리",
        badges=scaffold.mode_badge(),
    )
    proto.inject()
    if not ld.can_approve(user):
        empty_state("숙소 예약 승인 권한이 없습니다",
                    "관리자·매니저만 예약을 승인·반려할 수 있습니다. 본인 예약은 '내 숙소 예약'에서 확인하세요.")
        return
    show_flash(_STATE)

    try:
        reservations = ld.load_reservations()
    except ValueError as exc:
        banner("danger", str(exc))
        return

    erp.metric_strip(_metrics(reservations))
    proto.hairline()

    scope = _scope_chips()
    queue = _queue(reservations, scope)
    if not queue:
        erp.detail_empty(f"{scope} 건 없음",
                         "처리할 예약이 없습니다. 범위를 바꾸면 다른 건을 볼 수 있습니다.")
        st.session_state.pop(_SEL_KEY, None)
        return

    ordered = [ld.clean(r.get("request_no")) for r in queue]
    remembered = ld.clean(st.session_state.get(_SEL_KEY))
    if remembered not in ordered:
        remembered = ordered[0]

    picked = _render_table(queue, remembered)
    selected = picked or remembered
    st.session_state[_SEL_KEY] = selected
    # 다른 건으로 옮기면 열려 있던 취소 확인은 대상이 바뀌므로 폐기한다(오확인 방지).
    if ld.clean(st.session_state.get(_CONFIRM_KEY)) not in ("", selected):
        st.session_state.pop(_CONFIRM_KEY, None)
    _detail(user, reservations, selected)


# ===========================================================================
# 지표 · 범위 · 테이블
# ===========================================================================
def _metrics(reservations: list[dict]) -> list[tuple]:
    today = date.today()
    pending = sum(1 for r in reservations if ld.clean(r.get("status")) == ld.REQUESTED)
    approved = sum(1 for r in reservations if ld.clean(r.get("status")) == ld.APPROVED)
    checkin_today = sum(1 for r in reservations
                        if ld.clean(r.get("status")) == ld.APPROVED
                        and ld.to_date(r.get("check_in")) == today)
    due = sum(1 for r in reservations
              if ld.clean(r.get("status")) == ld.APPROVED
              and (ld.to_date(r.get("check_out")) or date.max) <= today)
    staying = sum(1 for r in reservations
                  if ld.clean(r.get("status")) in (ld.APPROVED, ld.COMPLETED)
                  and today in ld.day_span(r))
    return [
        ("승인 대기", pending, "건", "REQUESTED", pending > 0),
        ("승인 확정", approved, "건", "APPROVED", False),
        ("오늘 체크인", checkin_today, "건", "TODAY", False),
        ("사용완료 처리 대기", due, "건", "DUE", due > 0),
        ("오늘 재실", staying, "건", "STAY", False),
    ]


def _scope_chips() -> str:
    scopes = (SCOPE_PENDING, SCOPE_ALL)
    current = st.session_state.get(_SCOPE_KEY)
    if current not in scopes:
        current = SCOPE_PENDING
        st.session_state[_SCOPE_KEY] = current
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        st.markdown(
            f"<span style='font-size:14px;font-weight:600;color:{proto.INK};"
            "white-space:nowrap;'>범위</span>",
            unsafe_allow_html=True,
        )
        for scope in scopes:
            if st.button(scope, key=f"prq_scope_{scope}",
                         type="primary" if scope == current else "secondary") \
                    and scope != current:
                st.session_state[_SCOPE_KEY] = scope
                st.session_state.pop(_SEL_KEY, None)
                st.rerun()
    return current


def _queue(reservations: list[dict], scope: str) -> list[dict]:
    """범위별 목록. 승인 대기는 신청 건만, 전체는 전 상태(최근 체크인 순)."""
    if scope == SCOPE_PENDING:
        rows = [r for r in reservations if ld.clean(r.get("status")) == ld.REQUESTED]
    else:
        rows = list(reservations)
    return sorted(rows, key=lambda r: (ld.clean(r.get("check_in")),
                                       ld.clean(r.get("request_no"))))


def _render_table(queue: list[dict], selected: str) -> str | None:
    """예약 테이블 — 체크박스 선택(단일)이 곧 상세 열기(2026-08-07 사용자 결정 형식)."""
    lodgings = ld.lodging_map()
    frame = pd.DataFrame([
        {
            _KEY_FIELD: ld.clean(r.get("request_no")),
            "신청번호": ld.clean(r.get("request_no")),
            "신청자": f"{ld.clean(r.get('applicant_name'))}({ld.clean(r.get('applicant_emp_no'))})",
            "소속": ld.clean(r.get("dept_code")),
            "숙소": ld.lodging_label(lodgings.get(ld.clean(r.get("lodging_code")))),
            "체크인": ld.clean(r.get("check_in")),
            "체크아웃": ld.clean(r.get("check_out")),
            "박": str(ld.nights(r.get("check_in"), r.get("check_out"))),
            "상태": ld.STATUS_LABELS.get(ld.clean(r.get("status")), ld.clean(r.get("status"))),
        }
        for r in queue
    ])
    color_rules = {"상태": {
        ld.STATUS_LABELS[ld.REQUESTED]: "#8a6212",
        ld.STATUS_LABELS[ld.APPROVED]: "#2f6b45",
        ld.STATUS_LABELS[ld.COMPLETED]: "#5c564d",
        ld.STATUS_LABELS[ld.REJECTED]: "#9c3232",
        ld.STATUS_LABELS[ld.CANCELLED]: "#5c564d",
    }}
    col_config = {
        # 150: 실측 신청번호 문자열 폭(scrollWidth 143)에 여백을 더한 값 — 140 에서는 끝이 잘렸다.
        "신청번호": {"width": 150, "cellStyle": {"fontFamily": "'IBM Plex Mono', monospace"}},
        "신청자": {"flex": 1.4, "minWidth": 150},
        "소속": {"width": 80},
        "숙소": {"width": 100},
        "체크인": {"width": 104},
        "체크아웃": {"width": 104},
        "박": {"width": 56},
        "상태": {"width": 88},
    }
    return erp.select_grid(
        frame, key=f"{_PAGE_ID}_grid", key_field=_KEY_FIELD,
        columns=["신청번호", "신청자", "소속", "숙소", "체크인", "체크아웃", "박", "상태"],
        selected_key=selected,
        color_rules=color_rules, col_config=col_config,
        checkbox_marker=True,
    )


# ===========================================================================
# 전체폭 상세 + 일정 수정 + 액션 바
# ===========================================================================
def _detail(user: dict, reservations: list[dict], request_no: str) -> None:
    row = next((r for r in reservations if ld.clean(r.get("request_no")) == request_no), None)
    if row is None:
        st.session_state.pop(_SEL_KEY, None)
        erp.detail_empty("이 예약은 더 이상 목록에 없습니다",
                         "다른 사용자가 먼저 처리했을 수 있습니다 — 새로고침한 뒤 다시 선택하세요.")
        return

    lodging = ld.lodging_map().get(ld.clean(row.get("lodging_code")))
    status = ld.clean(row.get("status"))
    proto.hairline(top="12px", bottom="10px")
    # 상세 헤더 한 줄: 신청번호 · 상태 배지 · 숙소 · 기간 — 처리 판단에 필요한 핵심을
    # 시선 이동 없이 먼저 준다(기간은 메타가 아니라 여기 소속).
    st.markdown(
        "<div style='display:flex;flex-wrap:wrap;align-items:center;gap:10px;"
        "margin:2px 0 12px;'>"
        f"<span style='font-family:{proto.MONO};font-size:18px;font-weight:600;"
        f"color:{proto.INK};'>{ld.clean(row.get('request_no'))}</span>"
        f"{proto.badge(_BADGE_CODE.get(status, proto.BADGE_CLOSED), ld.STATUS_LABELS.get(status, status))}"
        f"<span style='font-size:17px;font-weight:600;color:{proto.INK};'>"
        f"{ld.lodging_label(lodging)}</span>"
        f"<span style='font-size:14px;color:{proto.INK2};'>{ld.period_label(row)}</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown(proto.meta_cells([
        ("신청자", f"{ld.clean(row.get('applicant_name'))}({ld.clean(row.get('applicant_emp_no'))})"),
        ("소속", ld.clean(row.get("dept_code"))),
        ("신청일시", ld.clean(row.get("created_at"))),
        ("처리자", ld.clean(row.get("decided_by")) or "-"),
        ("처리 의견", ld.clean(row.get("decision_comment")) or "-"),
    ]), unsafe_allow_html=True)

    _conflict_notice(row, reservations)
    proto.hairline(top="14px", bottom="12px")
    _action_bar(user, row, reservations)


@st.dialog("예약을 수정할 수 없습니다")
def _conflict_dialog(message: str) -> None:
    """일정 정정 시 중복 차단 팝업(신청 화면과 동일 계약)."""
    banner("danger", message)
    proto.note_line("겹치지 않는 일정으로 바꾸거나 '예약 캘린더'에서 빈 기간을 확인해 주세요.")
    if st.button("확인", key="lm_conflict_ok", type="primary", width="stretch"):
        st.rerun()


def _edit_form(user: dict, row: dict) -> None:
    """신청(REQUESTED) 건의 일정 정정 폼 — 액션 바의 [일정 수정] 토글이 연다
    (``update_reservation`` 이 서버측에서 권한·상태를 재확인한다)."""
    no = ld.clean(row.get("request_no"))
    lodgings = ld.load_lodgings(include_inactive=False)
    by_code = {ld.clean(l.get("lodging_code")): l for l in lodgings}
    codes = list(by_code)
    current_code = ld.clean(row.get("lodging_code"))
    with st.form(f"lm_edit_{no}", clear_on_submit=False):
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


def _conflict_notice(row: dict, reservations: list[dict]) -> None:
    """확정 예약과 겹치면 승인 전에 이유를 먼저 보여준다(버튼 비활성 사유와 동일 근거)."""
    if ld.clean(row.get("status")) != ld.REQUESTED:
        return
    hits = ld.find_conflicts(reservations, row.get("lodging_code"),
                             row.get("check_in"), row.get("check_out"),
                             exclude_no=row.get("request_no"))
    if not hits:
        return
    detail = " / ".join(
        f"{ld.clean(h.get('request_no'))} {ld.clean(h.get('check_in'))}~{ld.clean(h.get('check_out'))}"
        f" {ld.clean(h.get('applicant_name'))}"
        for h in hits
    )
    banner("warn", f"같은 숙소에 확정된 예약과 기간이 겹칩니다 — {detail}. 승인할 수 없습니다.")


def _action_bar(user: dict, row: dict, reservations: list[dict]) -> None:
    """처리 의견 + [일정 수정] [취소] [반려] [사용완료] [승인] — 처리 수단을 한 줄에 모은다.

    비활성 사유는 ``action_blocker`` 문구를 그대로 툴팁과 바 아래 안내 줄에 쓴다(LMG-4 —
    hover 로만 알 수 있으면 왜 못 누르는지 발견되지 않는다). 일정 수정 폼은 이 바 아래에
    펼쳐진다(액션이 상세 곳곳에 흩어지지 않게 — 2026-08-07 개선).
    """
    request_no = ld.clean(row.get("request_no"))
    op_key = f"{_OP_KEY}{request_no}"
    edit_key = f"{_EDIT_KEY}{request_no}"
    comment = ld.clean(st.session_state.get(op_key, ""))
    editable = ld.clean(row.get("status")) == ld.REQUESTED

    clicked = None
    blocked: list[tuple[str, str]] = []
    with st.container(horizontal=True, gap="small", vertical_alignment="bottom"):
        st.text_input("처리 의견 · 반려·타인 취소 시 필수", key=op_key, width="stretch",
                      placeholder="처리 사유를 한 줄로")
        if editable and st.button("일정 수정", key=f"pract_edit_{request_no}",
                                  type="secondary", width="content",
                                  help="신청 건의 숙소·기간을 정정합니다"):
            st.session_state[edit_key] = not bool(st.session_state.get(edit_key, False))
            st.rerun()
        for action, kind in _ACTION_ORDER:
            blocker = ld.action_blocker(row, action, user, comment=comment,
                                        reservations=reservations)
            if blocker:
                blocked.append((ld.ACTION_LABELS[action], blocker))
            hit = st.button(ld.ACTION_LABELS[action], key=f"pract_{action}_{request_no}",
                            type=kind, width="content", disabled=bool(blocker), help=blocker)
            if hit:
                clicked = action
    if blocked:
        # 문구는 action_blocker 반환값 그대로다 — 화면이 비활성 사유를 지어내지 않는다(계약 C9).
        proto.note_line(" · ".join(f"{label} 불가: {why}" for label, why in blocked))

    if clicked == ld.ACT_CANCEL:
        st.session_state[_CONFIRM_KEY] = request_no
        st.rerun()
    elif clicked:
        _run(clicked, request_no, user, comment)
    if st.session_state.get(_CONFIRM_KEY) == request_no:
        _cancel_dialog(row, user, comment)
    if editable and st.session_state.get(edit_key):
        _edit_form(user, row)


@st.dialog("예약 취소 확인", width="large")
def _cancel_dialog(row: dict, user: dict, comment: str) -> None:
    """승인권자 취소도 되돌릴 수 없으므로 실행 전에 한 번 확인한다(D2).

    표시 계층의 오조작 방지일 뿐이며 권한·사유 필수 판정은 ``run_action`` 이 재확인한다.
    """
    request_no = ld.clean(row.get("request_no"))
    place = ld.lodging_label(ld.lodging_map().get(ld.clean(row.get("lodging_code"))))
    banner("warn", f"예약을 취소하시겠습니까 — {request_no} · {place} · {ld.period_label(row)}.")
    proto.note_line("취소하면 되돌릴 수 없으며 해당 기간은 다른 사람이 예약할 수 있게 됩니다.")
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        confirmed = st.button("예약 취소 확정", key="prdanger_lm_cancel_ok", width="content")
        if st.button("돌아가기", key="pract_lm_cancel_back", type="secondary",
                     width="content"):
            st.session_state.pop(_CONFIRM_KEY, None)
            st.rerun()
    if confirmed:
        st.session_state.pop(_CONFIRM_KEY, None)
        _run(ld.ACT_CANCEL, request_no, user, comment)


def _run(action: str, request_no: str, user: dict, comment: str) -> None:
    """처리 실행 — 도메인 오류 문구는 그대로 노출하고, 그 외 예외는 원문을 감춘다."""
    label = ld.ACTION_LABELS.get(action, action)
    try:
        ld.run_action(request_no, action, current_user=user, comment=comment)
    except ValueError as exc:
        _STATE.set_flash("error", f"{label} 처리 실패 — {exc}")
        st.rerun()
    except Exception:  # noqa: BLE001 — 저장 백엔드 오류(원문 비노출).
        _STATE.set_flash("error", f"{label} 처리 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.")
        st.rerun()
    _STATE.set_flash("success", f"{request_no} {label} 완료.")
    # 처리된 건은 승인 대기 목록에서 빠지므로 선택을 해제한다(다음 건이 자동 선택된다).
    st.session_state.pop(_SEL_KEY, None)
    st.rerun()
