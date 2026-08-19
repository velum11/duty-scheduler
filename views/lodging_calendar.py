"""숙소 예약 캘린더 — READ_VIEW(DESIGN.md §2, 2026-08-18 신판 골격).

골격: 제목 → 조회 조건(연·월·숙소·상태 + 월 이동 한 줄) → 월 캘린더 → 범례.
종전의 지표 스트립(월 예약·가동률 등)은 §4-1(목록을 바꾸지 않는 읽기 전용 타일 금지)에
따라 제거했다 — 점유 현황은 캘린더 자체가 말한다. 캘린더가 화면의 전부다(2026-08-07
사용자 결정 — 하단 예약 목록·상세 제거). 상태 변경은 승인 관리, 본인 수정·취소는
내 숙소 예약 소관 — 여기는 순수 조회다.

캘린더는 **구글 캘린더식 월 뷰**다: 한 예약은 기간 전체가 이어진 하나의 막대로 그려지고,
주(week) 경계를 넘는 예약은 모서리를 끊어(radius 0) 다음 주로 이어짐을 표현한다.
막대의 세로 줄은 **숙소별 고정 lane**(대관령 윗줄 · 태안 아랫줄 — 기준정보 순서)이다.
신청 시점 중복 차단 정책 덕에 한 숙소의 살아있는 예약은 겹치지 않아 lane 하나로 충분하다.

색·lane 배정(2026-08-07 재검수 D4)
----------------------------------
막대 **색은 숙소 코드 기반 고정 맵**이다 — 기준정보 전체 순서로 1회 산출하며 조회 조건과
무관하다. 종전에는 필터 결과 순서로 색을 배정해 '태안만 보기'를 걸면 태안이 대관령 색
(녹색)으로 바뀌는 결함이 있었다(실측 재현). lane(세로 위치)만 보이는 숙소 수만큼 압축한다.
"""
# DESIGN.md §0 — 이 화면이 내리는 결정.
SCREEN_ARCHETYPE = "READ_VIEW"
SCREEN_DECISION = "원하는 기간에 빈 숙소가 있는가"
SCREEN_EVIDENCE = ("월별 점유 막대(기간 연속)", "숙소별 고정 lane·색", "상태 표기(승인대기 점선)")

from datetime import date
from html import escape

import streamlit as st

from modules import lodging_data as ld
from views.common import erp, proto, scaffold
from views.master import banner

_PAGE_ID = "lodging_calendar"

_WEEKDAYS = ("일", "월", "화", "수", "목", "금", "토")

# 막대 색은 **숙소별**로 구분한다(2026-08-07 사용자 결정 — 사용자·상태별 색 분리 없음).
# 기준정보 순서대로 배정: 대관령=녹색, 태안=앰버. 전부 기존 틴트 재사용.
_LODGING_TINTS = (
    ("#eef5f0", "#2f6b45"),   # 대관령
    ("#fdf3e3", "#8a6212"),   # 태안
    ("#f2f0ec", "#5c564d"),   # (추가 숙소 대비 회색)
)
# 상태는 색이 아니라 **표기**로 구분한다("대관령 - 승인대기" 식) + 승인대기는 점선 테두리.
_STATUS_WORD = {ld.REQUESTED: "승인대기", ld.APPROVED: "예약", ld.COMPLETED: "사용완료"}

_ALL = "전체"


def render(user: dict) -> None:
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="숙소 예약 캘린더",
        desc="월별 예약 일정을 한눈에 봅니다. 한 예약은 기간 전체가 이어진 막대로 표시됩니다.",
        breadcrumb="숙소 예약 › 예약 캘린더",
        badges=scaffold.mode_badge(),
    )
    proto.inject()

    try:
        lodgings = ld.load_lodgings()
        reservations = ld.load_reservations()
    except ValueError as exc:
        banner("danger", str(exc))
        return

    # §2 READ_VIEW: 제목 → 조회 조건 → 캘린더. 지표 스트립은 §4-1 에 따라 두지 않는다.
    cond = _conditions(lodgings)
    days = ld.month_days(cond["year"], cond["month"])
    # 색 배정은 조회 조건이 아니라 기준정보 전체 순서로 1회 산출한다(D4 — 필터 불변).
    tint_of = _tint_map(lodgings)
    visible_codes = _visible_codes(lodgings, cond["lodging"])
    rows = _month_rows(reservations, days, visible_codes, cond["status"])

    if not rows:
        erp.detail_empty(
            f"{cond['year']}년 {cond['month']}월 예약 없음",
            "조건에 해당하는 예약이 없습니다. 월·숙소·상태 조건을 조정해 보세요.",
        )

    _render_month(days, rows, visible_codes, tint_of, user)
    proto.note_line("승인·반려 처리는 '승인 관리'에서, 본인 예약의 수정·취소는 '내 숙소 예약'에서 합니다.")


# ===========================================================================
# 조회 조건 (§1-E 필터 줄) + 월 이동
# ===========================================================================
def _conditions(lodgings: list[dict]) -> dict:
    """연·월·숙소·상태 조건 + 월 이동을 **한 줄**로 낸다(§1-E 필터 줄, LCAL-3).

    종전에는 조건 셀렉트 줄 아래에 ``2026-08 ‹ 이번 달 ›`` 나브가 한 줄 더 있어 월 이동
    수단이 이중화되고 1366×768 에서 캘린더 하단이 접혔다(실측 ~48px). 기능(연·월 직접
    선택 + 이전/다음/이번 달)은 모두 남기고 배치만 한 줄로 합친다. 짧은 코드값 컨트롤은
    내용 맞춤 폭(§0.6).
    """
    today = date.today()
    st.session_state.setdefault(f"{_PAGE_ID}_year", today.year)
    st.session_state.setdefault(f"{_PAGE_ID}_month", today.month)
    # 월 이동으로 세션 연도가 기본 범위를 벗어날 수 있으므로 현재 값을 항상 옵션에 포함한다
    # (옵션에 없는 세션 값은 Streamlit 이 예외로 막는다).
    years = sorted({today.year - 1, today.year, today.year + 1,
                    int(st.session_state[f"{_PAGE_ID}_year"])})
    codes = [_ALL] + [ld.clean(l.get("lodging_code")) for l in lodgings]
    labels = {ld.clean(l.get("lodging_code")): ld.lodging_label(l) for l in lodgings}
    status_opts = [_ALL, ld.REQUESTED, ld.APPROVED, ld.COMPLETED]

    # 조건 스트립과 월 이동 버튼을 같은 가로 컨테이너의 형제로 둔다 — 조건 스트립은
    # 남는 폭을 채우고(stretch) 버튼은 내용 폭이라 우측에 붙는다.
    with st.container(key="lc_condrow", horizontal=True, gap="medium",
                      vertical_alignment="bottom"):
        values = erp.condition_panel(
            _PAGE_ID,
            [
                erp.Field(key="year", label="연도", options=years, width=110,
                          format_func=lambda y: f"{y}년"),
                erp.Field(key="month", label="월", options=list(range(1, 13)), width=100,
                          format_func=lambda m: f"{m}월"),
                erp.Field(key="lodging", label="숙소", options=codes, width=240,
                          format_func=lambda c: c if c == _ALL else labels.get(c, c)),
                erp.Field(key="status", label="상태", options=status_opts, width=130,
                          format_func=lambda s: s if s == _ALL else ld.STATUS_LABELS.get(s, s)),
            ],
            content_fit=True,
        )
        year, month = int(values["year"]), int(values["month"])
        prev_hit = st.button("‹", key="pr_prev", help="이전 달", width="content")
        today_hit = st.button("이번 달", key="lc_today", width="content")
        next_hit = st.button("›", key="pr_next", help="다음 달", width="content")

    # 나브는 조건 셀렉트의 세션 값을 갱신한다(월 상태의 단일 출처 유지 — 별도 상태 없음).
    if prev_hit:
        _shift_month(year, month, -1)
    if today_hit:
        today = date.today()
        _set_month(today.year, today.month)
    if next_hit:
        _shift_month(year, month, +1)
    return {
        "year": year,
        "month": month,
        "lodging": values["lodging"],
        "status": values["status"],
    }


def _shift_month(year: int, month: int, delta: int) -> None:
    index = year * 12 + (month - 1) + delta
    _set_month(index // 12, index % 12 + 1)


def _set_month(year: int, month: int) -> None:
    st.session_state[f"{_PAGE_ID}_year"] = year
    st.session_state[f"{_PAGE_ID}_month"] = month
    st.rerun()


def _tint_map(lodgings: list[dict]) -> dict[str, tuple[str, str]]:
    """숙소 코드 → (배경, 전경) 고정 색. **기준정보 전체 순서**로 1회 산출한다(D4).

    조회 조건(숙소 필터)과 무관하므로 '태안만 보기'를 걸어도 태안은 계속 앰버다.
    """
    return {
        ld.clean(l.get("lodging_code")): _LODGING_TINTS[i % len(_LODGING_TINTS)]
        for i, l in enumerate(lodgings)
    }


def _visible_codes(lodgings: list[dict], selected) -> list[str]:
    codes = [ld.clean(l.get("lodging_code")) for l in lodgings]
    if selected and selected != _ALL:
        return [c for c in codes if c == ld.clean(selected)]
    return codes


def _month_rows(reservations, days, codes, status) -> list[dict]:
    """해당 월·숙소·상태 조건에 걸리는 예약(점유 상태만 — 반려·취소 제외)."""
    if not days:
        return []
    statuses = (status,) if status and status != _ALL else ld.OCCUPYING_STATUSES
    code_set = set(codes)
    out = []
    for row in reservations:
        if ld.clean(row.get("status")) not in statuses:
            continue
        if ld.clean(row.get("lodging_code")) not in code_set:
            continue
        span = ld.day_span(row)
        if any(days[0] <= d <= days[-1] for d in span):
            out.append(row)
    return sorted(out, key=lambda r: (ld.clean(r.get("check_in")),
                                      ld.clean(r.get("lodging_code"))))


# ===========================================================================
# 월 캘린더 — 구글 캘린더식 주(week) 행 + 연속 예약 막대
# ===========================================================================
def _render_month(days: list[date], rows: list[dict], codes: list[str],
                  tint_of: dict[str, tuple[str, str]], user: dict) -> None:
    """주 단위 행에 예약을 연속 막대로 그린다.

    한 예약은 주 안에서 하나의 세그먼트(절대배치 막대)이고, 주 경계를 넘으면 다음 주
    행에 이어진다 — 실제 시작/끝 주에서만 모서리를 둥글린다(구글 캘린더 관용구).
    막대 세로 위치(lane)는 보이는 숙소 순서로 압축하지만 **색은 ``tint_of`` 고정 맵**
    이다(D4). 상태는 표기("대관령 - 승인대기")와 점선 테두리로 구분한다.

    본인 예약(D3): 채움색은 숙소색 그대로 두고 **좌측 3px 액센트 캡 + 액센트 텍스트**로
    소유권만 덧입힌다. 라벨에 "내 예약"을 적지 않아 1박짜리 짧은 막대에서도 글자가
    잘리지 않는다 — 소유권은 캡·텍스트색·범례가 함께 운반한다(§4 이중부호화).

    개인정보: 신청자 성명은 **승인권자와 본인에게만** 보인다 — 일반 사용자에게는
    "숙소 - 상태" 익명 표기만 노출한다(2026-08-07 사용자 결정).
    """
    if not days:
        return
    lodgings = ld.lodging_map()
    lane_of = {code: i for i, code in enumerate(codes)}
    n_lanes = max(len(codes), 1)
    approver = ld.can_approve(user)
    my_emp = (user or {}).get("emp_no")
    first = days[0]
    lead = (first.weekday() + 1) % 7          # 일요일 시작
    start = date.fromordinal(first.toordinal() - lead)
    n_weeks = (lead + len(days) + 6) // 7
    today = date.today()

    spans = []
    for row in rows:
        ci, co = ld.to_date(row.get("check_in")), ld.to_date(row.get("check_out"))
        if ci is None or co is None or co <= ci:
            continue
        spans.append((row, ci, co))
    spans.sort(key=lambda t: (t[1], ld.clean(t[0].get("request_no"))))

    head = "".join(f"<span>{w}</span>" for w in _WEEKDAYS)
    weeks = []
    for w in range(n_weeks):
        wk_start = date.fromordinal(start.toordinal() + w * 7)
        wk_end_excl = date.fromordinal(wk_start.toordinal() + 7)

        segs = []
        for row, ci, co in spans:
            s, e = max(ci, wk_start), min(co, wk_end_excl)
            if e <= s:
                continue
            segs.append({"row": row, "s": (s - wk_start).days, "len": (e - s).days,
                         "starts": ci >= wk_start, "ends": co <= wk_end_excl,
                         "lane": lane_of.get(ld.clean(row.get("lodging_code")), 0)})
        height = 30 + n_lanes * 24 + 4

        cells = []
        for i in range(7):
            day = date.fromordinal(wk_start.toordinal() + i)
            outside = day.month != first.month
            classes = "pr-cw-d" + (" out" if outside else "") + \
                      (" today" if day == today and not outside else "")
            label = f"{day.month}월 {day.day}일" if day.day == 1 else str(day.day)
            cells.append(f"<div class='{classes}'><span class='n'>{label}</span></div>")

        bars = []
        for seg in segs:
            row = seg["row"]
            status = ld.clean(row.get("status"))
            code = ld.clean(row.get("lodging_code"))
            bg, fg = tint_of.get(code, _LODGING_TINTS[-1])
            place = ld.lodging_label(lodgings.get(code))
            word = _STATUS_WORD.get(status, ld.STATUS_LABELS.get(status, status))
            own = ld.emp_eq(row.get("applicant_emp_no"), my_emp)
            if own:
                text = f"{place} · {word}"
            elif approver:
                name = ld.clean(row.get("applicant_name")) or ld.clean(row.get("applicant_emp_no"))
                text = f"{place} - {name} · {word}"
            else:
                text = f"{place} - {word}"
            left = seg["s"] / 7 * 100
            width = seg["len"] / 7 * 100
            il = 3 if seg["starts"] else 0        # 시작/끝 주에서만 그리드에서 살짝 띄운다
            ir = 3 if seg["ends"] else 0
            rl = "10px" if seg["starts"] else "0"
            rr = "10px" if seg["ends"] else "0"
            dash = f"border:1px dashed {fg};" if status == ld.REQUESTED else ""
            # 본인 예약: 텍스트는 액센트색, 캡은 **시작 세그먼트에만**(이어지는 주에
            # 캡이 반복되면 매주 새 예약처럼 읽힌다).
            ink = proto.ACCENT_TEXT if own else fg
            cls = "pr-gbar mine" if (own and seg["starts"]) else "pr-gbar"
            bars.append(
                f"<span class='{cls}' style='left:calc({left:.4f}% + {il}px);"
                f"width:calc({width:.4f}% - {il + ir}px);top:{seg['lane'] * 24}px;"
                f"background:{bg};color:{ink};border-radius:{rl} {rr} {rr} {rl};{dash}' "
                f"title='{_bar_title(row, lodgings, anonymous=not (approver or own))}'>"
                f"{escape(text)}</span>"
            )

        weeks.append(
            f"<div class='pr-cw' style='height:{height}px'>"
            f"<div class='pr-cw-days'>{''.join(cells)}</div>"
            f"<div class='pr-cw-bars'>{''.join(bars)}</div></div>"
        )

    st.markdown(
        f"<div class='pr-cal'><div class='pr-cal-hd'>{head}</div>{''.join(weeks)}</div>",
        unsafe_allow_html=True,
    )
    _legend(codes, lodgings, tint_of)


def _bar_title(row: dict, lodgings: dict, *, anonymous: bool) -> str:
    """막대 hover 툴팁 — 일반 사용자에게는 성명을 싣지 않는다. 따옴표까지 escape."""
    lodging = lodgings.get(ld.clean(row.get("lodging_code")), {})
    status = ld.clean(row.get("status"))
    word = _STATUS_WORD.get(status, ld.STATUS_LABELS.get(status, status))
    parts = [ld.clean(row.get("request_no")), ld.lodging_label(lodging)]
    if not anonymous:
        parts.append(ld.clean(row.get("applicant_name")))
    parts += [ld.period_label(row), word]
    return escape(" · ".join(p for p in parts if p), quote=True)


def _legend(codes: list[str], lodgings: dict,
            tint_of: dict[str, tuple[str, str]]) -> None:
    """범례 = 막대가 쓰는 모든 부호(숙소 채움색 · 본인 예약 캡 · 승인대기 점선) — LCAL-4.

    라벨에서 뺀 '내 예약' 문구를 여기서 회수한다: 캡·점선은 라벨 없이는 읽히지 않는다.
    """
    items: list[tuple] = [
        (ld.lodging_label(lodgings.get(code)), *tint_of.get(code, _LODGING_TINTS[-1]))
        for code in codes
    ]
    items.append(("내 예약", proto.SURFACE_2, proto.LINE_HDR, "cap"))
    items.append(("승인대기", proto.SURFACE_2, proto.MUT, "dashed"))
    proto.legend(items)
    proto.note_line("막대 표기는 '숙소 - 상태'(승인대기·예약·사용완료)이며, 본인 예약은 좌측 액센트 캡과 주황 글자로 구분합니다.")


