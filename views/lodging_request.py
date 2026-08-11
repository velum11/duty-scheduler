"""숙소 예약 신청 — 폼형(DESIGN.md §1-D) 단건 제출 폼(FORM_ENTRY).

아차사고 등록(``views/near_miss_submit.py``)의 골격을 그대로 따른다:

    REQUESTER 신원 줄(읽기 전용) → 01 · 숙소·기간
    우측 aside: 가용 현황(선택 숙소·기간의 확정 예약 충돌) + 필수 체크리스트 + [예약 신청]

입력은 숙소·체크인·체크아웃 3개가 전부다(2026-08-07 사용자 결정 — 사용 목적·인원·
동반자·비고 필드 제거). 같은 숙소·겹치는 기간에 살아있는 예약이 있으면 **신청 시점에
팝업으로 거부**한다(`lodging_data.ReservationConflict`). 신청 후 수정·취소는
'내 숙소 예약'에서 한다.

- 카드 금지(§0-5) — 구획은 헤어라인과 여백만. 색은 §2 팔레트만(§0-8).
- ``st.form`` 을 쓰지 않는다 — 일반 키드 위젯이라 입력 즉시 세션에 반영되어 **가용 현황과
  체크리스트가 실시간**으로 갱신된다(아차사고 등록의 Medium 1 결정과 동일). 제출 시 전체를
  재검증한다.
- 신원(신청자·사번·소속)은 위젯이 아니라 세션 사용자에서 서버측 확정한다(위조 방지).

프로토타입 범위: 저장은 ``modules/lodging_data`` (로컬 파일 영속)이며 라우팅·Supabase 는
후속 통합 작업 소관이다.
"""
# DESIGN.md §1-D 폼형 — 단건 입력·제출.
SCREEN_ARCHETYPE = "FORM_ENTRY"

from datetime import date, timedelta

import streamlit as st

from modules import lodging_data as ld
from modules import mailer
from views.common import erp, proto, scaffold
from views.master import PersistResult, banner, ledger_banner

_PAGE_ID = "lodging_request"
_DONE_KEY = "lr_submit_done"

_K_LODGING = "lr_f_lodging"
_K_IN = "lr_f_check_in"
_K_OUT = "lr_f_check_out"
_FORM_KEYS = (_K_LODGING, _K_IN, _K_OUT)


def render(user: dict) -> None:
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="숙소 예약 신청",
        desc="숙소 사용을 신청합니다. 같은 기간에 이미 예약이 있으면 접수되지 않으며, 접수 후 승인권자 승인이 필요합니다.",
        breadcrumb="숙소 예약 › 예약 신청",
        badges=scaffold.mode_badge(),
    )
    proto.inject()

    done = st.session_state.get(_DONE_KEY)
    if done:
        _render_post_submit(done)
        return

    emp_no = ld.clean(user.get("emp_no"))
    if not emp_no:
        banner("warn", "로그인 사번을 확인할 수 없어 예약을 신청할 수 없습니다.")
        return

    try:
        lodgings = ld.load_lodgings(include_inactive=False)
        reservations = ld.load_reservations()
    except ValueError as exc:
        banner("danger", str(exc))
        return

    if not lodgings:
        banner("warn", "신청할 수 있는 숙소가 없습니다. 기준정보에서 숙소를 먼저 등록하세요.")
        return

    _render_form(user, lodgings, reservations)


# ---------- 폼 본문 ----------
def _render_form(user: dict, lodgings: list[dict], reservations: list[dict]) -> None:
    by_code = {ld.clean(l.get("lodging_code")): l for l in lodgings}
    codes = [""] + list(by_code)

    with st.container(key="pr_formwrap"):
        form_col, side_col = st.columns([2.7, 1.0], vertical_alignment="top")
        with form_col:
            proto.identity_row(
                "REQUESTER",
                [("신청자", ld.clean(user.get("name")) or "(이름 미확인)"),
                 ("사번", ld.clean(user.get("emp_no"))),
                 ("소속", ld.clean(user.get("dept_code")) or "미지정")],
                lock="로그인 정보로 자동 지정 · 수정 불가",
            )

            # ── 01 · 숙소·기간 ──
            proto.section("01", "숙소·기간")
            # 숙소는 두 곳뿐인 짧은 코드값 — 열 전체를 채우지 않고 내용 맞춤 폭(§0.6, LRQ-2).
            code = st.selectbox(
                "숙소 *", codes, key=_K_LODGING, width=240,
                format_func=lambda c: "— 선택 —" if c == "" else _lodging_option(by_code[c]),
            )
            lodging = by_code.get(ld.clean(code))

            # 체크인·체크아웃은 한 쌍으로 읽는 값이라 인접 배치한다(등폭 2열이면 두
            # 컨트롤이 화면 절반씩 떨어져 기간으로 읽히지 않는다 — LRQ-3).
            with st.container(horizontal=True, gap="small", vertical_alignment="bottom"):
                check_in = st.date_input("체크인 *", value=date.today() + timedelta(days=7),
                                         format="YYYY-MM-DD", key=_K_IN, width=170)
                # 체크인을 체크아웃 뒤로 옮기면 체크아웃을 최소 1박으로 따라 붙인다(위젯
                # 인스턴스화 전에 세션 값을 보정 — 역순 기간이 화면에 남지 않는다).
                _out_cur = ld.to_date(st.session_state.get(_K_OUT))
                if check_in is not None and _out_cur is not None and _out_cur <= check_in:
                    st.session_state[_K_OUT] = check_in + timedelta(days=1)
                check_out = st.date_input("체크아웃 *", value=date.today() + timedelta(days=9),
                                          format="YYYY-MM-DD", key=_K_OUT, width=170)
            proto.note_line(
                "체크아웃 당일은 점유하지 않습니다 — 같은 날 다음 사용자가 체크인할 수 있습니다."
            )

        # 가용 판정은 aside(가용 현황)·체크리스트·제출 활성이 **같은 결과**를 봐야 하므로
        # 한 번만 계산해 세 곳에 넘긴다(화면 안에서 판정이 갈리지 않게).
        hits = (ld.occupied_conflicts(reservations, ld.clean(code), check_in, check_out)
                if lodging else [])
        checks = _checks(code, check_in, check_out, lodging, hits)
        can_submit = all(ok for _, ok in checks)

        with side_col:
            st.markdown(_availability_html(lodging, check_in, check_out, hits),
                        unsafe_allow_html=True)
            st.markdown(_checklist(checks), unsafe_allow_html=True)
            # 표시 계층의 사전 차단일 뿐 — 접수 가능 여부의 최종 판정은 여전히
            # ``create_reservation`` 서버측 재검증이다(경합 백스톱, LRQ-1).
            submitted = st.button(
                "예약 신청", type="primary", key="lr_submit_btn", width="stretch",
                disabled=not can_submit,
                help=None if can_submit else
                "미충족: " + " · ".join(label for label, ok in checks if not ok),
            )

    if not submitted:
        return

    payload = {
        "lodging_code": ld.clean(code),
        "check_in": check_in,
        "check_out": check_out,
    }
    errors = ld.validate_reservation(payload, lodging=lodging)
    if errors:
        banner("danger", " / ".join(errors))
        return
    _persist(payload, user)


def _lodging_option(lodging: dict) -> str:
    # 숙소는 대관령·태안 두 곳뿐이라 이름만 표기한다(2026-08-07 사용자 결정).
    return ld.lodging_label(lodging)


def _checks(code, check_in, check_out, lodging, hits) -> list[tuple[str, bool]]:
    """제출 준비 상태 4항목 — 체크리스트 표시와 제출 버튼 활성이 같은 목록을 본다.

    '기간 가용'은 겹치는 살아있는 예약이 없는지다(LRQ-1). 숙소·기간이 아직 확정되지
    않았으면 판정 자체가 성립하지 않으므로 미충족으로 둔다.
    """
    picked = bool(ld.clean(code)) and lodging is not None
    span_ok = ld.nights(check_in, check_out) > 0
    return [
        ("숙소", picked),
        ("체크인", ld.to_date(check_in) is not None),
        ("체크아웃", span_ok),
        ("기간 가용", picked and span_ok and not hits),
    ]


def _checklist(checks: list[tuple[str, bool]]) -> str:
    """필수 4항목 실시간 체크리스트(§1-D 우측 aside)."""
    return proto.checklist_html(
        checks,
        note="네 항목을 모두 충족하면 신청할 수 있습니다. 제출 시 기간·중복이 다시 검증됩니다.",
    )


def _availability_html(lodging, check_in, check_out, hits) -> str:
    """선택 숙소·기간의 가용 여부 — 겹치는 기존 예약이 있으면 제출 전에 먼저 알린다."""
    if not lodging:
        return proto.aside_kv("AVAILABILITY", [("선택 숙소", "미선택")],
                              note="숙소를 선택하면 해당 기간의 예약 상황을 보여줍니다.")
    n = ld.nights(check_in, check_out)
    rows = [
        ("선택 숙소", ld.lodging_label(lodging)),
        ("신청 기간", f"{n}박" if n else "기간 확인 필요"),
        ("기간 내 기존 예약", f"{len(hits)}건" if hits else "없음"),
    ]
    note = ld.conflict_message(hits) if hits else "선택한 기간은 현재 예약 가능합니다."
    return proto.aside_kv("AVAILABILITY", rows, note=note)


# ---------- 저장 ----------
@st.dialog("예약할 수 없습니다")
def _conflict_dialog(message: str) -> None:
    """신청 시점 중복 차단 팝업 — 겹치는 예약번호·기간을 그대로 보여준다."""
    banner("danger", message)
    proto.note_line("겹치지 않는 일정으로 바꾸거나 '예약 캘린더'에서 빈 기간을 확인해 주세요.")
    if st.button("확인", key="lr_conflict_ok", type="primary", width="stretch"):
        st.rerun()


def _persist(payload: dict, user: dict) -> None:
    """저장을 시도하고 lifecycle ``PersistResult``/``ledger_banner`` 패턴으로 결과를 알린다.

    중복 기간 충돌(:class:`ld.ReservationConflict`)만 팝업으로 알린다(2026-08-07 결정) —
    그 외 검증 실패는 기존 배너 패턴 그대로다.
    """
    try:
        record = ld.create_reservation(payload, current_user=user)
    except ld.ReservationConflict as exc:
        _conflict_dialog(str(exc))
        return
    except ValueError as exc:
        ledger_banner(PersistResult.failure(_PAGE_ID, ["예약 신청"], str(exc), retryable=True))
        return
    except Exception:  # noqa: BLE001 — 저장 백엔드 오류(원문 비노출).
        ledger_banner(PersistResult.unresolved(
            _PAGE_ID, "저장 결과를 확인할 수 없습니다. 예약 현황을 재조회한 뒤 다시 시도하세요."))
        return

    period = ld.period_label(record)
    lodging = ld.lodging_label(ld.lodging_map().get(ld.clean(record.get("lodging_code"))))
    # 접수 저장 성공 후 담당자 알림 — 발송 결과가 접수를 되돌리지 않는다(mailer 계약).
    mail = mailer.notify_lodging_requested(record, lodging_label=lodging, period_label=period)
    st.session_state[_DONE_KEY] = {
        "request_no": ld.clean(record.get("request_no")),
        "period": period,
        "lodging": lodging,
        "mail": mail,
    }
    st.rerun()


def _render_post_submit(done: dict) -> None:
    """제출 완료 결과 + 다음 작업."""
    request_no = ld.clean(done.get("request_no")) or "(번호 확인 필요)"
    ledger_banner(PersistResult.success(_PAGE_ID, [request_no]))
    banner("success",
           f"예약을 신청했습니다. 신청번호 {request_no} · {done.get('lodging')} · "
           f"{done.get('period')} · 상태 신청(REQUESTED)")
    if done.get("mail") is True:
        proto.note_line("승인 담당자에게 접수 알림 메일을 발송했습니다.")
    elif done.get("mail") is False:
        banner("warn", "신청은 완료됐지만 담당자 알림 메일 발송에 실패했습니다. 담당자에게 별도로 알려주세요.")
    proto.note_line("승인 결과 확인과 수정·취소는 '내 숙소 예약'에서 합니다.")
    if st.button("새 예약 신청", key="lr_done_new", icon=":material/add:"):
        for key in _FORM_KEYS:
            st.session_state.pop(key, None)
        st.session_state.pop(_DONE_KEY, None)
        st.rerun()
