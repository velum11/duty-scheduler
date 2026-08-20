"""내 숙소 예약 — READ_VIEW(DESIGN.md §2, 2026-08-18 신판 골격) + 신청 상태 수정 · 취소.

    제목/설명 → [기간·상태 조회 조건] → [목록 카드: 헤더 + 표]
    → [상세 카드: 헤더(번호·배지·액션) + 속성 스택]

§2 READ_VIEW 골격(제목 → 조회 조건 → 표)을 따른다. 종전의 지표 스트립은 §4-1
(읽기 전용 지표 타일 금지 — 목록을 바꾸지 않는 수치는 자리값을 못 한다)에 따라
제거했다(2026-08-18 신판 정합). 테이블 + 전체폭 상세는 내 아차사고(READ_VIEW)와
같은 관용구이며, 행 피치는 USER 소관 화면이라 44px(§1.4 cozy — 터치 조작 대상).

- 진입 시 첫 행 자동 선택(빈 상세 패널을 만들지 않는다 — §3.5 빈 상태 회피).
- 상태는 배지 낱말로만 읽는다 — 표의 상태 색과 진행 단계 pill 은 소음이라 제거했다
  (2026-08-19 사용자 결정). 수정 불가 사유는 상세 하단 한 줄이 소유한다(§3.2).
- 목록 범위는 위젯이 아니라 **인증 세션 사번**으로 고정한다(타인 건 열람 방지).
- 수정(신청 상태만)·취소 게이트는 화면이 아니라 ``lodging_data.update_reservation`` /
  ``action_blocker`` 가 서버측에서 재확인한다. 수정 시 겹치는 예약이 있으면
  :class:`ld.ReservationConflict` 를 팝업으로 알린다(신청 화면과 동일 계약).
- 취소는 되돌릴 수 없으므로 실행 전에 확인 팝업을 거친다(D2) — 팝업은 표시 계층의
  오조작 방지이고, 권한·상태 판정은 여전히 ``run_action`` 이 소유한다.
"""
# DESIGN.md §0 — 이 화면이 내리는 결정.
SCREEN_ARCHETYPE = "READ_VIEW"
SCREEN_DECISION = "내 예약이 어느 단계에 있고, 일정 수정이나 취소가 필요한가"
SCREEN_EVIDENCE = ("내 예약 목록(기간·상태)", "진행 단계·처리 의견", "허용 액션과 불가 사유")

from datetime import date
from html import escape

import pandas as pd
import streamlit as st

from modules import db
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


def render(user: dict) -> None:
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="내 숙소 예약",
        desc="본인이 신청한 숙소 예약을 확인하고, 승인 전 건은 일정을 수정하거나 취소합니다.",
        breadcrumb="숙소 예약 › 내 숙소 예약",
        badges=scaffold.mode_badge(),
    )
    proto.inject()
    # 조건부 배너는 상시 컨테이너 안에서만 — 요소 수 고정(승인 관리와 같은 계약).
    with st.container(key="lmy_notice"):
        show_flash(_STATE)

    emp_no = ld.clean(user.get("emp_no"))
    if not emp_no:
        banner("warn", "로그인 사번을 확인할 수 없어 내 예약을 표시할 수 없습니다.")
        return
    try:
        rows = db.get_lodging_reservations(
            {"applicant_emp_no": emp_no}, current_user=user,
        ).to_dict("records")
    except (ValueError, *db.DATA_SOURCE_ERRORS) as exc:
        banner("danger", str(exc))
        return

    if not rows:
        erp.detail_empty("신청한 숙소 예약이 없습니다",
                         "'숙소 예약 신청'에서 대관령·태안 숙소 사용을 신청할 수 있습니다.")
        return

    # §2 READ_VIEW: 제목 → 조회 조건 → 표. 지표 스트립은 §4-1(목록을 바꾸지 않는
    # 읽기 전용 타일 금지)에 따라 두지 않는다 — 상태별로 보고 싶으면 상태 조건이 있다.
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

    with st.container(key="prcard_list"):
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


# ===========================================================================
# 목록(테이블 선택)
# ===========================================================================
def _render_table(rows: list[dict], selected: str) -> str | None:
    """내 예약 목록 — 카드 패널 + 표(승인 관리와 같은 어휘).

    행 클릭이 곧 선택이자 상세 열기이며, 행 피치는 USER·터치 variant 44px(§1.4 cozy).
    상태는 색을 쓰지 않는다(2026-08-19 사용자 결정 — 낱말만으로 읽힌다).
    """
    lodgings = db.lodging_map()
    st.markdown(
        f"<div class='pr-panelhd'><span class='t'>내 예약</span>"
        f"<span class='r'>체크인 최근 순 · {len(rows)}건</span></div>",
        unsafe_allow_html=True,
    )
    frame = pd.DataFrame([
        {
            _KEY_FIELD: ld.clean(r.get("request_no")),
            "접수번호": ld.clean(r.get("request_no")),
            "신청일자": ld.clean(r.get("created_at"))[:10],
            "장소": ld.lodging_label(lodgings.get(ld.clean(r.get("lodging_code")))),
            "기간": _period_cell(r),
            "상태": ld.STATUS_LABELS.get(ld.clean(r.get("status")), ld.clean(r.get("status"))),
        }
        for r in rows
    ])
    col_config = {
        "접수번호": {"width": 152, "cellStyle": {"fontFamily": proto.MONO}},
        "신청일자": {"width": 108},
        "장소": {"width": 96},
        "기간": {"flex": 1, "minWidth": 210},
        "상태": {"width": 84, "cellStyle": {"justifyContent": "flex-end"}},
    }
    height = 44 + min(len(rows), 10) * 44 + 20
    return erp.select_grid(
        frame, key=f"{_PAGE_ID}_grid", key_field=_KEY_FIELD,
        columns=["접수번호", "신청일자", "장소", "기간", "상태"],
        selected_key=selected, col_config=col_config,
        height=height, row_height=44, checkbox_marker=False,
    )


def _period_cell(row: dict) -> str:
    """목록용 기간 표기 — 같은 달이면 종료일의 연·월을 생략한다(승인 관리와 동일 형식)."""
    ci, co = ld.clean(row.get("check_in")), ld.clean(row.get("check_out"))
    tail = co[5:] if len(ci) >= 7 and len(co) >= 7 and ci[:7] == co[:7] else co
    return f"{ci} ~ {tail} ({ld.nights(row.get('check_in'), row.get('check_out'))}박)"


# ===========================================================================
# 전체폭 상세 + 일정 수정 + 액션
# ===========================================================================
def _detail(user: dict, rows: list[dict], request_no: str) -> None:
    """선택 건 상세 — 카드 패널: 헤더(번호·배지·액션) → 속성 스택 → 안내(승인 관리 어휘)."""
    row = next((r for r in rows if ld.clean(r.get("request_no")) == request_no), None)
    if row is None:
        st.session_state.pop(_SEL_KEY, None)
        erp.detail_empty("이 예약은 더 이상 목록에 없습니다",
                         "조건이 바뀌었거나 상태가 변경됐습니다 — 새로고침한 뒤 다시 선택하세요.")
        return

    status = ld.clean(row.get("status"))
    lodging = db.lodging_map().get(ld.clean(row.get("lodging_code")))
    comment = ld.clean(row.get("decision_comment"))
    with st.container(key="prcard_detail"):
        with st.container(key="prhead_my", horizontal=True, gap="small",
                          vertical_alignment="center"):
            st.markdown(
                "<div class='pr-panelhd' style='margin:0;'>"
                f"<span style='font-family:{proto.MONO};font-size:16px;font-weight:600;"
                f"color:{proto.INK};'>{ld.clean(row.get('request_no'))}</span>"
                f"{proto.badge(_BADGE_CODE.get(status, proto.BADGE_CLOSED), ld.STATUS_LABELS.get(status, status))}"
                "</div>",
                unsafe_allow_html=True,
            )
            _render_actions(user, row, status)

        if status == ld.REJECTED and comment:
            banner("warn", f"반려 사유: {comment}")

        nights = ld.nights(row.get("check_in"), row.get("check_out"))
        cells = [
            ("장소 · 기간",
             f"{ld.lodging_label(lodging)} · {_period_cell(row)[:-1]} {nights + 1}일)"),
            ("신청일시", ld.clean(row.get("created_at"))),
        ]
        if ld.clean(row.get("decided_by")):
            cells.append(("처리", f"{ld.clean(row.get('decided_by'))} · "
                                f"{ld.clean(row.get('decided_at')) or '-'}"))
        if comment and status != ld.REJECTED:
            cells.append(("처리 의견", comment))
        body = "".join(
            f"<div><p class='k'>{escape(k)}</p><div class='v'>{escape(v)}</div></div>"
            for k, v in cells
        )
        st.markdown(f"<div class='pr-stack row'>{body}</div>", unsafe_allow_html=True)

        # 비활성 사유는 항상 화면에 쓴다(§3.2) — 승인 전에만 수정 가능하다는 계약.
        if status != ld.REQUESTED:
            proto.note_line("승인 전(신청 상태)에만 일정을 수정할 수 있습니다.")
        if st.session_state.get(_CONFIRM_KEY) == ld.clean(row.get("request_no")):
            _cancel_dialog(row, user)
        with st.container(key="lmy_editslot"):
            if status == ld.REQUESTED and st.session_state.get(
                    f"{_EDIT_KEY}{ld.clean(row.get('request_no'))}"):
                _render_edit_form(user, row)


def _render_actions(user: dict, row: dict, status: str) -> None:
    """헤더 우측 액션 — 신청 상태의 [일정 수정], 체크인 전의 [예약 취소]."""
    no = ld.clean(row.get("request_no"))
    cancel_block = ld.action_blocker(row, ld.ACT_CANCEL, user)

    if status == ld.REQUESTED:
        if st.button("일정 수정", key=f"pract_edit_{no}", type="secondary",
                     width="content"):
            edit_key = f"{_EDIT_KEY}{no}"
            st.session_state[edit_key] = not bool(st.session_state.get(edit_key, False))
            st.rerun()
    if st.button("예약 취소", key=f"prneg_cancel_{no}", type="secondary",
                 width="content", disabled=bool(cancel_block), help=cancel_block):
        st.session_state[_CONFIRM_KEY] = no
        st.rerun()


@st.dialog("예약 취소 확인", width="large")
def _cancel_dialog(row: dict, user: dict) -> None:
    """취소는 되돌릴 수 없고 기간이 곧바로 풀리므로 실행 전에 한 번 확인한다(D2).

    표시 계층의 오조작 방지일 뿐이며 권한·상태 판정은 ``run_action`` 이 재확인한다.
    """
    no = ld.clean(row.get("request_no"))
    place = ld.lodging_label(db.lodging_map().get(ld.clean(row.get("lodging_code"))))
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
    by_code = db.lodging_map(include_inactive=False)
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
        db.update_lodging_reservation(no, {"lodging_code": code, "check_in": check_in,
                                           "check_out": check_out}, current_user=user)
    except ld.ReservationConflict as exc:
        _conflict_dialog(str(exc))
        return
    except (ValueError, *db.DATA_SOURCE_ERRORS) as exc:
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
        db.run_lodging_action(request_no, ld.ACT_CANCEL, current_user=user)
    except (ValueError, *db.DATA_SOURCE_ERRORS) as exc:
        _STATE.set_flash("error", f"취소 처리 실패 — {exc}")
        st.rerun()
    except Exception:  # noqa: BLE001 — 저장 백엔드 오류(원문 비노출).
        _STATE.set_flash("error", "취소 처리 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.")
        st.rerun()
    _STATE.set_flash("success", f"{request_no} 예약을 취소했습니다.")
    st.rerun()
