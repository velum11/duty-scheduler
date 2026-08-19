"""숙소 예약 신청 — FORM_ENTRY(DESIGN.md §2, 2026-08-18 신판 골격).

    제목 → REQUESTER 신원 줄(세션 확정·수정 불가) → 01 · 숙소·기간(라벨 열 + 값 열)
    → 하단 고정 제출 바(필수 충족 상태 + [예약 신청])

입력은 숙소·체크인·체크아웃 3개가 전부다(2026-08-07 사용자 결정). 날짜는 date_input
쌍이 아니라 **달력에서 직접 클릭**해 고른다(2026-08-18 사용자 결정). 첫 클릭이
체크인, 둘째 클릭이 체크아웃이며 이미 예약된 밤은 숙소 틴트로 칠해 클릭 전에 가용
여부가 보인다. 같은 숙소·겹치는 기간에 살아있는 예약이 있으면 **신청 시점에 팝업으로
거부**한다(`lodging_data.ReservationConflict`). 신청 후 수정·취소는 '내 숙소 예약'.

- 필드는 §3.1 라벨 열(130px 고정) + 값 열 구조 — 별도 체크리스트 패널을 두지 않고
  **필수 충족 상태는 하단 고정 바**에 개수+남은 항목 이름으로 표시한다(§2 FORM_ENTRY).
  제출 불가 사유가 항상 화면에 있다(§3.2 — 툴팁 단독 금지).
- 날짜 셀은 일반 ``st.button`` 이고 선택 상태 변경은 전부 ``on_click`` 콜백에서
  처리한다(콜백은 렌더 전에 실행되므로 화면에는 항상 정합한 선택만 남는다).
- 신원(신청자·사번·소속)은 위젯이 아니라 세션 사용자에서 서버측 확정한다(위조 방지).

프로토타입 범위: 저장은 ``modules/lodging_data`` (로컬 파일 영속)이며 라우팅·Supabase 는
후속 통합 작업 소관이다(§2 — 미라우팅 프로토타입, 검증 대상 제외).
"""
# DESIGN.md §0 — 이 화면이 내리는 결정.
SCREEN_ARCHETYPE = "FORM_ENTRY"
SCREEN_DECISION = "이 숙소·기간으로 예약을 신청할 준비가 되었는가"
SCREEN_EVIDENCE = ("달력의 점유 현황", "선택한 체크인·체크아웃", "필수 충족 상태")

from datetime import date
from html import escape

import streamlit as st

from modules import lodging_data as ld
from modules import mailer
from views.common import erp, proto, scaffold
from views.master import PersistResult, banner, ledger_banner

_PAGE_ID = "lodging_request"
_DONE_KEY = "lr_submit_done"

_K_LODGING = "lr_f_lodging"
_K_IN = "lr_f_check_in"       # 달력 선택값(date | None) — 위젯 키 아님
_K_OUT = "lr_f_check_out"
_K_CAL_Y = "lr_cal_year"
_K_CAL_M = "lr_cal_month"
_K_MSG = "lr_cal_msg"
_FORM_KEYS = (_K_LODGING, _K_IN, _K_OUT, _K_CAL_Y, _K_CAL_M, _K_MSG)

_WEEKDAYS = ("일", "월", "화", "수", "목", "금", "토")

# 점유일 틴트 — 예약 캘린더 ``_LODGING_TINTS``(D4)와 같은 값·같은 기준정보 순서 축.
# 인덱스가 proto.PROTO_CSS 의 ``lrqd_occ{0,1,x}`` 셀 클래스와 1:1 이다.
_OCC_TINTS = (
    ("#eef5f0", "#2f6b45"),   # 대관령
    ("#fdf3e3", "#8a6212"),   # 태안
    ("#f2f0ec", "#5c564d"),   # (추가 숙소 대비 회색)
)


def render(user: dict) -> None:
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="숙소 예약 신청",
        desc="숙소 사용을 신청합니다. 접수 후 승인권자 승인이 필요합니다.",
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

    st.markdown(
        "<div class='pr-idchip'><span>"
        f"<b>{escape(ld.clean(user.get('name')) or '(이름 미확인)')}</b><i></i>"
        f"{escape(ld.clean(user.get('emp_no')))}<i></i>"
        f"{escape(ld.clean(user.get('dept_code')) or '미지정')}"
        "</span></div>",
        unsafe_allow_html=True,
    )
    _render_form(user, lodgings, reservations)


# ---------- 폼 본문 ----------
def _render_form(user: dict, lodgings: list[dict], reservations: list[dict]) -> None:
    by_code = {ld.clean(l.get("lodging_code")): l for l in lodgings}
    codes = [""] + list(by_code)
    # 틴트 인덱스는 기준정보 전체 순서 — 예약 캘린더의 색 배정(D4)과 같은 축이라
    # 두 화면에서 같은 숙소가 항상 같은 색이다.
    tint_idx = {code: i for i, code in enumerate(by_code)}

    with st.container(key="prcard_form"):
        with st.container(key="prcols_req"):
            cal_col, side_col = st.columns([2.7, 1], vertical_alignment="top")
            with cal_col:
                code = _picker_panel(by_code, codes, tint_idx, reservations)
            lodging = by_code.get(ld.clean(code))
            check_in = ld.to_date(st.session_state.get(_K_IN))
            check_out = ld.to_date(st.session_state.get(_K_OUT))
            # 달력이 점유일 클릭을 막아 평시엔 비지만, 제출 사이 경합의 백스톱이다.
            hits = (ld.occupied_conflicts(reservations, ld.clean(code), check_in, check_out)
                    if lodging and check_in and check_out else [])
            with side_col:
                submitted = _summary_panel(lodging, check_in, check_out, hits)

    if not submitted:
        return
    payload = {"lodging_code": ld.clean(code), "check_in": check_in,
               "check_out": check_out}
    errors = ld.validate_reservation(payload, lodging=lodging)
    if errors:
        banner("danger", " / ".join(errors))
        return
    _persist(payload, user)


def _picker_panel(by_code: dict, codes: list, tint_idx: dict,
                  reservations: list[dict]) -> str:
    """좌측 판 — 숙소 선택 + 월 이동 한 줄, 그 아래 전체폭 달력과 범례(2026-08-19 시안)."""
    today = date.today()
    st.session_state.setdefault(_K_CAL_Y, today.year)
    st.session_state.setdefault(_K_CAL_M, today.month)
    with st.container(key="lrq_toprow", horizontal=True, gap="small",
                      vertical_alignment="center"):
        proto.field_label("숙소", required=True)
        # 숙소가 바뀌면 점유일 지도가 달라지므로 날짜 선택을 초기화한다.
        code = st.selectbox(
            "숙소 *", codes, key=_K_LODGING, width=240, label_visibility="collapsed",
            format_func=lambda c: "— 선택 —" if c == "" else _lodging_option(by_code[c]),
            on_change=_reset_selection,
        )
        st.markdown("<div class='pr-spacer'></div>", unsafe_allow_html=True)
        st.button("‹", key="pr_prev", help="이전 달", width="content",
                  on_click=_shift_cal, args=(-1,))
        st.markdown(
            f"<div class='pr-calttl'>{st.session_state[_K_CAL_Y]}년 "
            f"{st.session_state[_K_CAL_M]}월</div>", unsafe_allow_html=True)
        st.button("›", key="pr_next", help="다음 달", width="content",
                  on_click=_shift_cal, args=(+1,))

    lodging = by_code.get(ld.clean(code))
    _calendar_picker(lodging, tint_idx.get(ld.clean(code)), reservations)
    return code


def _summary_panel(lodging, check_in, check_out, hits) -> bool:
    """우측 판 — 신청 요약 + 필수 충족 + 제출(2026-08-19 시안).

    제출 불가 사유가 항상 이 판에 있다(§3.2) — 필수 미충족은 진행 바로, 기간 충돌은
    경고 문구로 말한다. 최종 판정은 여전히 ``create_reservation`` 서버측 재검증이다.
    """
    n = ld.nights(check_in, check_out)
    rows = [
        ("숙소", ld.lodging_label(lodging) if lodging else "—"),
        ("체크인", _fmt_day(check_in) if check_in else "—"),
        ("체크아웃", _fmt_day(check_out) if check_out else "—"),
        ("숙박", f"{n}박 {n + 1}일" if n > 0 else "—"),
    ]
    body = "".join(
        f"<div class='k'>{escape(k)}</div>"
        f"<div class='v{'' if v != '—' else ' off'}'>{escape(v)}</div>"
        for k, v in rows
    )
    done = sum(1 for x in (lodging, check_in, check_out) if x)
    st.markdown(
        "<div class='pr-panelhd'><span class='t'>신청 요약</span></div>"
        f"<div class='pr-sum'>{body}</div>"
        f"<div class='pr-req'><span>필수 <b>{done}/3</b></span>"
        f"<span class='bar'><i style='width:{round(done / 3 * 100)}%'></i></span></div>",
        unsafe_allow_html=True,
    )
    if hits:
        banner("warn", ld.conflict_message(hits))
    can_submit = bool(lodging and check_in and check_out and n > 0 and not hits)
    return st.button("예약 신청", type="primary", key="lr_submit_btn",
                     width="stretch", disabled=not can_submit)


def _lodging_option(lodging: dict) -> str:
    # 숙소는 대관령·태안 두 곳뿐이라 이름만 표기한다(2026-08-07 사용자 결정).
    return ld.lodging_label(lodging)


# ---------- 인라인 달력 선택기 ----------
def _calendar_picker(lodging: dict | None, tint_i: int | None,
                     reservations: list[dict]) -> None:
    """달력에서 체크인→체크아웃을 차례로 고르는 인라인 선택기.

    이미 예약된 밤(점유일)은 숙소 틴트로 칠하고 체크인으로는 막되, **체크아웃
    경계로는 허용**한다(반개구간 — 체크아웃 당일은 점유하지 않으므로 다른 예약의
    체크인일이어도 된다). 날짜 셀의 상태는 위젯 key 접두(``lrqd_{state}_``)로
    나르고 표현은 proto.PROTO_CSS 의 정적 규칙이 맡는다 — 화면 로컬 CSS 없음.
    """
    today = date.today()
    st.session_state.setdefault(_K_CAL_Y, today.year)
    st.session_state.setdefault(_K_CAL_M, today.month)
    year, month = st.session_state[_K_CAL_Y], st.session_state[_K_CAL_M]

    code = ld.clean((lodging or {}).get("lodging_code"))
    occupied = _occupied_nights(reservations, code) if lodging else frozenset()
    ci = ld.to_date(st.session_state.get(_K_IN))
    co = ld.to_date(st.session_state.get(_K_OUT))

    with st.container(key="lrq_cal"):
        st.markdown(
            "<div class='pr-dow'>" +
            "".join(f"<span>{w}</span>" for w in _WEEKDAYS) + "</div>",
            unsafe_allow_html=True,
        )

        days = ld.month_days(year, month)
        first = days[0]
        lead = (first.weekday() + 1) % 7          # 일요일 시작(예약 캘린더와 동일)
        start = date.fromordinal(first.toordinal() - lead)
        n_weeks = (lead + len(days) + 6) // 7
        for w in range(n_weeks):
            cols = st.columns(7, gap="small")
            for i in range(7):
                day = date.fromordinal(start.toordinal() + w * 7 + i)
                with cols[i]:
                    _day_button(day, month, today, ci, co, occupied, tint_i)

    _picker_legend(lodging, tint_i)
    msg = st.session_state.get(_K_MSG)
    if msg:
        banner("warn", msg)


def _day_button(day: date, month: int, today: date, ci: date | None, co: date | None,
                occupied: frozenset, tint_i: int | None) -> None:
    """날짜 셀 하나 — 상태 우선순위: 선택 끝점 > 선택 구간 > 점유 > 오늘 > 기본.

    바깥 달·지난 날짜는 비활성(비활성 표현이 상태 틴트보다 우선 — CSS 순서로 보장).
    """
    outside = day.month != month
    in_range = (ci is not None and
                (day == ci or (co is not None and ci <= day <= co)))
    if outside:
        state = "out"
    elif in_range:
        # 이어짐 표시 — 좌우 이웃도 선택 구간이고 주(week) 경계가 아니면 붙인다.
        wk = (day.weekday() + 1) % 7
        left = (co is not None and ci < day <= co and wk != 0)
        right = (co is not None and ci <= day < co and wk != 6)
        state = "sel" + ("L" if left else "") + ("R" if right else "")
    elif day in occupied:
        state = f"occ{tint_i}" if tint_i in (0, 1) else "occx"
    elif day == today:
        state = "tdy"
    else:
        state = "day"
    st.button(
        str(day.day), key=f"lrqd_{state}_{day.isoformat()}",
        width="stretch", disabled=outside or day < today,
        on_click=_pick, args=(day, occupied),
        help="이미 예약된 날짜" if state.startswith("occ") else None,
    )


def _occupied_nights(reservations: list[dict], code: str) -> frozenset:
    """해당 숙소의 점유 밤 집합(살아있는 예약 — 반개구간이라 체크아웃 당일 제외)."""
    nights: set[date] = set()
    for row in reservations or []:
        if ld.clean(row.get("status")) not in ld.OCCUPYING_STATUSES:
            continue
        if ld.clean(row.get("lodging_code")) != code:
            continue
        nights.update(ld.day_span(row))
    return frozenset(nights)


def _pick(day: date, occupied: frozenset) -> None:
    """달력 클릭 처리(``on_click`` 콜백 — 렌더 전에 실행).

    새 선택 시작 조건: 체크인이 없거나, 기간이 이미 완성됐거나, 체크인 이전 날짜를
    눌렀을 때. 그 외에는 체크아웃 후보로 보고 숙박 밤 ``[체크인, 후보)`` 전체가
    비어 있는지 확인한다(점유일을 건너뛰는 기간 선택 차단).
    """
    st.session_state.pop(_K_MSG, None)
    ci = ld.to_date(st.session_state.get(_K_IN))
    co = ld.to_date(st.session_state.get(_K_OUT))
    if ci is None or co is not None or day <= ci:
        if day in occupied:
            # 기존 선택은 지우지 않는다 — 잘못 누른 클릭이 선택을 날리지 않게.
            st.session_state[_K_MSG] = "이미 예약된 날짜입니다. 비어 있는 날짜에서 체크인을 선택해 주세요."
            return
        st.session_state[_K_IN] = day
        st.session_state[_K_OUT] = None
        return
    if (day - ci).days > ld.MAX_NIGHTS:
        st.session_state[_K_MSG] = (
            f"연속 숙박은 최대 {ld.MAX_NIGHTS}박까지 신청할 수 있습니다. 체크아웃을 다시 선택해 주세요.")
        return
    if any(date.fromordinal(o) in occupied
           for o in range(ci.toordinal(), day.toordinal())):
        st.session_state[_K_IN] = None
        st.session_state[_K_OUT] = None
        st.session_state[_K_MSG] = "선택한 기간에 이미 예약된 날짜가 있습니다. 체크인부터 다시 선택해 주세요."
        return
    st.session_state[_K_OUT] = day


def _shift_cal(delta: int) -> None:
    index = st.session_state[_K_CAL_Y] * 12 + (st.session_state[_K_CAL_M] - 1) + delta
    st.session_state[_K_CAL_Y], st.session_state[_K_CAL_M] = index // 12, index % 12 + 1




def _reset_selection() -> None:
    st.session_state[_K_IN] = None
    st.session_state[_K_OUT] = None
    st.session_state.pop(_K_MSG, None)


def _picker_legend(lodging: dict | None, tint_i: int | None) -> None:
    """달력 부호 범례 — 점유 틴트(숙소 선택 시)와 선택 기간 액센트."""
    items: list[tuple] = [("선택 기간", proto.ACCENT, proto.ACCENT)]
    if lodging is not None:
        bg, fg = _OCC_TINTS[tint_i] if tint_i in (0, 1) else _OCC_TINTS[-1]
        items.append((f"{ld.lodging_label(lodging)} 예약됨", bg, fg))
    items.append(("선택 불가", proto.SURFACE_2, proto.LINE))
    proto.legend(items)


# ---------- 하단 고정 제출 바 ----------
def _fmt_day(day: date) -> str:
    return f"{day.isoformat()} ({_WEEKDAYS[(day.weekday() + 1) % 7]})"



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
