"""숙소 예약 승인 관리 — WORKLIST(DESIGN.md §2, 2026-08-18 신판 골격).

    제목/설명 → [상태 탭: 승인 대기 N │ 전체 N]
    → [접수 목록 — 전체폭 표: 접수번호·신청일자·부서·성명·장소·기간·상태]
    ── 헤어라인 ──
    → [처리 판: 접수번호+배지+숙소+기간 → 가용 달력+요약 → 이력 → 결정(의견 → 버튼)]

**상하 분리**(2026-08-19 사용자 지시)다. §2 WORKLIST 는 2열 33/67 을 규정하지만, 숙소
예약 레코드는 짧아 좁은 목록 열에서 기간이 잘리고 우측이 비어 보였다(실측 2026-08-18).
사용자 판정으로 전체폭 표 + 하단 처리 판을 쓴다 — 상태 탭·근거 우선 순서·액션 위계 등
나머지 WORKLIST 계약은 그대로 지킨다. 지표 스트립은 §4-1(목록을 바꾸지 않는 읽기 전용
타일 금지)에 따라 없애고 **상태별 건수를 탭에** 실었다.

- 액션은 **가능한 전이만 그린다**(§3.2): 신청 건 [일정 수정·취소·반려·승인],
  승인 건 [취소·사용완료], 종결 건 없음. 조건 미충족(의견 필요·체크아웃 전·겹침)은
  비활성 + 사유를 바 아래 줄에 쓴다(툴팁 단독 금지). 부정 액션(취소·반려)은 부정
  의미 색 버튼이다(같은 색 버튼 4개 나열 금지의 색 축 분리).
- 승인권자 전용 — **숙소관리 담당자만**(``lodging_data.can_approve`` →
  ``auth.can_approve_lodging``). role 은 판정에 들어가지 않으며, 파사드가 쓰기 직전
  사번으로 담당을 권위 재조회해 다시 막는다(화면 게이트는 첫 관문일 뿐이다).
- 처리 실행·사유 필수·겹침 백스톱 판정은 ``run_action``/``action_blocker`` 서버측 소유.

저장·조회는 ``modules/db`` 파사드가 소유한다(sample/supabase 공통). 검증·중복 판정·
상태 전이 규칙은 ``modules/lodging_data`` 의 순수 함수가 유일한 출처이며, 파사드가
쓰기 직전 같은 함수로 서버측에서 다시 판정한다(화면 판정은 표시용 보조일 뿐이다).
"""
# DESIGN.md §0 — 이 화면이 내리는 결정.
SCREEN_ARCHETYPE = "WORKLIST"
SCREEN_DECISION = "이 신청을 승인할 것인가, 반려·취소·사용완료로 처리할 것인가"
SCREEN_EVIDENCE = ("신청자·숙소·기간", "확정 예약과의 겹침", "접수 후 경과일", "처리 의견")

from datetime import date
from html import escape

import pandas as pd
import streamlit as st

from modules import db
from modules import lodging_data as ld
from views.common import erp, proto, scaffold
from views.master import DraftState, banner, empty_state, show_flash

_STATE = DraftState("lodging_manage")
_PAGE_ID = _STATE.page_id
_KEY_FIELD = "_rid"
_SEL_KEY = "lm_selected_no"
_SCOPE_KEY = "lm_scope"
_SCOPE_PREV = "lm_scope_prev"
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
# 상태의 결과 표기(§3.3) — 배지 옆에서 그 상태가 무엇을 열고 막는지 말한다.
_STATUS_EFFECT = {
    ld.REQUESTED: "승인 대기 — 승인·반려·정정 가능",
    ld.APPROVED: "확정 — 체크아웃 후 사용완료 처리",
    ld.COMPLETED: "종결 — 변경 불가",
    ld.REJECTED: "종결 — 변경 불가",
    ld.CANCELLED: "종결 — 기간이 다시 열림",
}
# 상태별로 **가능한 전이만** 그린다(§3.2 — 불가능한 전이는 비활성이 아니라 부재).
# 순서 = 배치 순서: 부정(취소·반려)은 좌측, 주 액션(승인/사용완료)은 우측 끝 primary.
_POSSIBLE = {
    ld.REQUESTED: (ld.ACT_CANCEL, ld.ACT_REJECT, ld.ACT_APPROVE),
    ld.APPROVED: (ld.ACT_CANCEL, ld.ACT_COMPLETE),
}
_NEGATIVE = (ld.ACT_CANCEL, ld.ACT_REJECT)


def render(user: dict) -> None:
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="숙소 예약 승인 관리",
        desc="신청된 예약을 검토해 승인·반려합니다.",
        breadcrumb="숙소 예약 › 승인 관리",
        badges=scaffold.mode_badge(),
    )
    proto.inject()
    if not ld.can_approve(user):
        # 담당 저장소를 확인하지 못한 상태를 '권한 없음'으로 뭉뚱그리지 않는다 —
        # 전자는 일시 장애라 재시도로 풀리고, 후자는 담당 지정이 필요하다.
        if db.capabilities_probe() == db.READINESS_PROBE_ERROR:
            empty_state("승인 권한을 확인하지 못했습니다",
                        "담당 권한 저장소 상태를 확인하지 못했습니다(일시 장애). "
                        "잠시 후 다시 시도하세요.")
            return
        empty_state("숙소 예약 승인 권한이 없습니다",
                    "숙소관리 담당자로 지정된 사용자만 예약을 승인·반려할 수 있습니다. "
                    "본인 예약은 '내 숙소 예약'에서 확인하세요.")
        return
    # 조건부 배너는 **상시 존재 컨테이너** 안에서만 그린다 — 최상위 요소 수가 run 마다
    # 달라지면 Streamlit delta 경로가 밀려 직전 블록이 DOM 에 잔존한다(2026-08-13 편성
    # 저장 후 공백 버그와 같은 유형, 2026-08-20 승인 직후 재현).
    with st.container(key="lm_notice"):
        show_flash(_STATE)

    try:
        reservations = db.get_lodging_reservations(current_user=user).to_dict("records")
    except (ValueError, *db.DATA_SOURCE_ERRORS) as exc:
        banner("danger", str(exc))
        return

    scope = _scope_tabs(reservations)
    queue = _queue(reservations, scope)
    if not queue:
        erp.detail_empty(f"{scope} 건 없음",
                         "처리할 예약이 없습니다. 탭을 바꾸면 다른 건을 볼 수 있습니다.")
        st.session_state.pop(_SEL_KEY, None)
        return

    ordered = [ld.clean(r.get("request_no")) for r in queue]
    remembered = ld.clean(st.session_state.get(_SEL_KEY))
    if remembered not in ordered:
        remembered = ordered[0]      # 진입 시 첫 행 자동 선택(빈 상세 없음).

    # 상하 분리(2026-08-19 사용자 지시): 접수 목록을 전체폭 표로 위에, 선택 건의 근거와
    # 승인 액션을 아래에 둔다. 좌우 33/67 분할은 폐기했다 — 예약 레코드가 짧아 좁은 열에
    # 넣으면 기간이 잘리고, 화면 우측이 비어 보였다(실측 2026-08-18).
    with st.container(key="prcard_list"):
        picked = _render_table(queue, scope, remembered)
    selected = picked or remembered
    st.session_state[_SEL_KEY] = selected
    # 다른 건으로 옮기면 열려 있던 취소 확인은 대상이 바뀌므로 폐기한다(오확인 방지).
    if ld.clean(st.session_state.get(_CONFIRM_KEY)) not in ("", selected):
        st.session_state.pop(_CONFIRM_KEY, None)
    _detail(user, reservations, selected)


# ===========================================================================
# 상태 탭 · 접수 목록(전체폭)
# ===========================================================================
def _scope_tabs(reservations: list[dict]) -> str:
    """상태 탭 — 건수를 탭 라벨에 싣고, 탭이 목록을 실제로 바꾼다(§2·§4-1).

    ``st.segmented_control`` 은 선택 재클릭으로 해제될 수 있어 None 은 기본 탭으로
    되돌린다. 탭 전환 시 선택 건을 초기화한다(다른 목록의 선택을 이어받지 않게).
    """
    pending_n = sum(1 for r in reservations
                    if ld.clean(r.get("status")) == ld.REQUESTED)
    counts = {SCOPE_PENDING: pending_n, SCOPE_ALL: len(reservations)}
    scope = st.segmented_control(
        "범위", [SCOPE_PENDING, SCOPE_ALL], key=_SCOPE_KEY,
        default=SCOPE_PENDING, label_visibility="collapsed",
        format_func=lambda s: f"{s} {counts.get(s, 0)}",
    ) or SCOPE_PENDING
    if st.session_state.get(_SCOPE_PREV) != scope:
        if _SCOPE_PREV in st.session_state:
            st.session_state.pop(_SEL_KEY, None)
        st.session_state[_SCOPE_PREV] = scope
    return scope


def _queue(reservations: list[dict], scope: str) -> list[dict]:
    """탭별 목록. 승인 대기는 접수 오래된 순(경과일 큰 건 먼저 — 처리 우선순위),
    전체는 최근 체크인 순."""
    if scope == SCOPE_PENDING:
        rows = [r for r in reservations if ld.clean(r.get("status")) == ld.REQUESTED]
        return sorted(rows, key=lambda r: (ld.clean(r.get("created_at")),
                                           ld.clean(r.get("request_no"))))
    return sorted(reservations, key=lambda r: (ld.clean(r.get("check_in")),
                                               ld.clean(r.get("request_no"))),
                  reverse=True)


def _pending_days(row: dict, today: date) -> int:
    """접수 후 경과일 — ``created_at`` 기준(§7.2-4 결정 준용: 처리 책임 구간은 접수 이후)."""
    created = ld.to_date(ld.clean(row.get("created_at"))[:10])
    return max((today - created).days, 0) if created else 0


def _period_cell(row: dict) -> str:
    """목록용 기간 표기 — 같은 달이면 종료일의 연·월을 생략한다(참고 배치 형식)."""
    ci, co = ld.clean(row.get("check_in")), ld.clean(row.get("check_out"))
    tail = co[5:] if len(ci) >= 7 and len(co) >= 7 and ci[:7] == co[:7] else co
    return f"{ci} ~ {tail} ({ld.nights(row.get('check_in'), row.get('check_out'))}박)"


def _render_table(queue: list[dict], scope: str, selected: str) -> str | None:
    """접수 목록 — 카드 패널 + 전체폭 표(2026-08-19 사용자 참고 배치).

    접수번호 · 신청일자 · 부서 · 성명 · 장소 · 기간 · 경과 · 상태. 행 클릭이 곧 선택이며
    선택 건의 근거·승인은 아래 처리 판이 소유한다. 패널 헤더 우측에 정렬 기준과 건수를
    적어 "왜 이 순서인지"를 말한다(§2 목록은 먼저 처리할 건을 고를 근거를 담는다).
    """
    lodgings = db.lodging_map()
    today = date.today()
    order = "신청일 오래된 순" if scope == SCOPE_PENDING else "체크인 최근 순"
    st.markdown(
        f"<div class='pr-panelhd'><span class='t'>{scope} 목록</span>"
        f"<span class='r'>{order} · {len(queue)}건</span></div>",
        unsafe_allow_html=True,
    )
    frame = pd.DataFrame([
        {
            _KEY_FIELD: ld.clean(r.get("request_no")),
            "접수번호": ld.clean(r.get("request_no")),
            "신청일자": ld.clean(r.get("created_at"))[:10],
            "부서": ld.clean(r.get("dept_code")),
            "성명": ld.clean(r.get("applicant_name")),
            "장소": ld.lodging_label(lodgings.get(ld.clean(r.get("lodging_code")))),
            "기간": _period_cell(r),
            "경과": (f"{_pending_days(r, today)}일 경과"
                   if ld.clean(r.get("status")) == ld.REQUESTED else "처리 완료"),
            "상태": ld.STATUS_LABELS.get(ld.clean(r.get("status")), ld.clean(r.get("status"))),
        }
        for r in queue
    ])
    col_config = {
        "접수번호": {"width": 152, "cellStyle": {"fontFamily": proto.MONO}},
        "신청일자": {"width": 104},
        "부서": {"width": 78},
        "성명": {"width": 88},
        "장소": {"width": 88},
        # 기간이 남는 폭을 흡수한다 — 경과·상태는 우측 고정 폭이라 표 끝에 정렬된다.
        "기간": {"flex": 1, "minWidth": 210},
        "경과": {"width": 92, "cellStyle": {"justifyContent": "flex-end"}},
        "상태": {"width": 76, "cellStyle": {"justifyContent": "flex-end"}},
    }
    # 높이를 행수에 맞춘다(kit 기본 최소 120px 가 소량 큐에서 빈 밴드를 만들고, 여유가
    # 모자라면 세로 스크롤바가 뜬다 — 둘 다 실측 2026-08-18). 12행 초과는 목록 내부 스크롤.
    height = 36 + min(len(queue), 12) * 32 + 20
    return erp.select_grid(
        frame, key=f"{_PAGE_ID}_grid", key_field=_KEY_FIELD,
        columns=["접수번호", "신청일자", "부서", "성명", "장소", "기간", "경과", "상태"],
        selected_key=selected, col_config=col_config,
        height=height, checkbox_marker=False,
    )


# ===========================================================================
# 처리 판 — 근거 → 결정 컨트롤 → 실행(§2)
# ===========================================================================
def _detail(user: dict, reservations: list[dict], request_no: str) -> None:
    row = next((r for r in reservations if ld.clean(r.get("request_no")) == request_no), None)
    if row is None:
        st.session_state.pop(_SEL_KEY, None)
        erp.detail_empty("이 예약은 더 이상 목록에 없습니다",
                         "다른 사용자가 먼저 처리했을 수 있습니다 — 새로고침한 뒤 다시 선택하세요.")
        return

    lodging = db.lodging_map().get(ld.clean(row.get("lodging_code")))
    status = ld.clean(row.get("status"))
    with st.container(key="prcard_detail"):
        _detail_head(user, row, reservations, lodging, status)
        with st.container(key="prcols_manage"):
            cal_col, info_col, act_col = st.columns([1.1, 1.15, 1.4],
                                                    vertical_alignment="top")
            with cal_col:
                st.markdown(_availability_html(row, reservations), unsafe_allow_html=True)
            with info_col:
                st.markdown(_info_stack(row, lodging, reservations),
                            unsafe_allow_html=True)
            with act_col:
                _decision_input(row)
        with st.container(key="lm_conflict"):
            _conflict_notice(row, reservations)
        with st.container(key="lm_blocked"):
            _blocked_note(user, row, reservations)


def _detail_head(user: dict, row: dict, reservations: list[dict],
                 lodging: dict | None, status: str) -> None:
    """처리 판 헤더 — 좌: 접수번호·상태 배지·상태 결과 / 우: 실행 버튼(참고 배치).

    버튼은 **가능한 전이만** 그린다(§3.2). 결정 컨트롤(처리 의견)은 아래 3열의 우측
    칸이고, 그 값은 세션 키로 이 헤더가 먼저 읽는다(위젯 렌더 순서와 무관).
    """
    # 상태의 '결과'는 버튼이 이미 말하므로(가능한 전이만 그린다) 문구로 되풀이하지 않고,
    # 버튼이 답하지 못하는 값(경과일)만 적는다.
    aging = (f"{_pending_days(row, date.today())}일 경과"
             if status == ld.REQUESTED else "")
    with st.container(key="prhead_manage", horizontal=True, gap="small",
                      vertical_alignment="center"):
        st.markdown(
            "<div class='pr-panelhd' style='margin:0;'>"
            f"<span style='font-family:{proto.MONO};font-size:16px;font-weight:600;"
            f"color:{proto.INK};'>{ld.clean(row.get('request_no'))}</span>"
            f"{proto.badge(_BADGE_CODE.get(status, proto.BADGE_CLOSED), ld.STATUS_LABELS.get(status, status))}"
            f"<span style='font-size:12px;color:{proto.MUT};'>{aging}</span></div>",
            unsafe_allow_html=True,
        )
        _action_buttons(user, row, reservations)


def _info_stack(row: dict, lodging: dict | None, reservations: list[dict]) -> str:
    """근거 속성 — 라벨 위 / 값 아래 스택(참고 배치). 값 열은 하나다(§3.1)."""
    nights = ld.nights(row.get("check_in"), row.get("check_out"))
    hits = ld.occupied_conflicts(reservations, ld.clean(row.get("lodging_code")),
                                 row.get("check_in"), row.get("check_out"),
                                 exclude_no=ld.clean(row.get("request_no")))
    dup = ("<span class='v bad'>겹치는 예약 %d건</span>" % len(hits) if hits
           else "<span class='v ok'>겹치는 날 없음</span>")
    cells = [
        # period_label 이 이미 "(N박)"을 포함하므로 되풀이하지 않는다(중복 표기 방지).
        ("장소 · 기간",
         f"{ld.lodging_label(lodging)} · {_period_cell(row)[:-1]} {nights + 1}일)", ""),
        ("신청자",
         f"{ld.clean(row.get('applicant_name'))} ({ld.clean(row.get('applicant_emp_no'))})"
         f" · {ld.clean(row.get('dept_code'))}", ""),
        ("접수 시각", ld.clean(row.get("created_at")), ""),
    ]
    body = "".join(
        f"<div><p class='k'>{escape(k)}</p><div class='v'>{escape(v)}</div>"
        + (f"<div class='s'>{escape(sub)}</div>" if sub else "") + "</div>"
        for k, v, sub in cells
    )
    gap = _gap_text(row, reservations)
    body += (f"<div><p class='k'>중복 여부</p>{dup}"
             + (f"<div class='s'>{escape(gap)}</div>" if gap else "") + "</div>")
    if ld.clean(row.get("decision_comment")):
        body += ("<div><p class='k'>처리 의견</p>"
                 f"<div class='v'>{escape(ld.clean(row.get('decision_comment')))}</div></div>")
    return f"<div class='pr-stack'>{body}</div>"


def _decision_input(row: dict) -> None:
    """결정 컨트롤 — 처리 의견(§2: 근거 → 결정 컨트롤 → 실행)."""
    op_key = f"{_OP_KEY}{ld.clean(row.get('request_no'))}"
    st.markdown("<p class='pr-stack' style='margin:0 0 8px;'>"
                "<span style='font-size:12px;color:%s;'>처리 의견</span></p>" % proto.MUT,
                unsafe_allow_html=True)
    st.text_area("처리 의견", key=op_key, height=168, label_visibility="collapsed",
                 placeholder="처리 사유")


def _availability_html(row: dict, reservations: list[dict]) -> str:
    """이 신청 기간의 가용 상황을 **달력으로** 보여준다(2026-08-18 사용자 선택 방향).

    승인 판단의 실제 근거는 "그 기간에 이 숙소가 비어 있는가"다 — 종전에는 그 답이
    텍스트 메타에만 있어 승인권자가 다른 화면(예약 캘린더)으로 나가야 했다. 같은 숙소의
    다른 살아있는 예약(자기 자신 제외)을 숙소 고정 틴트로, 이 신청의 숙박 밤을 액센트로
    칠하고, 둘이 겹치는 날은 충돌색으로 표시한다(신청 화면 달력과 같은 부호).
    기간이 달을 넘기면 걸치는 달을 나란히 낸다(최대 2개 — 30박 상한이라 3개는 없다).
    """
    code = ld.clean(row.get("lodging_code"))
    lodging = db.lodging_map().get(code)
    focus = set(ld.day_span(row))            # 숙박 밤(점유) — 반개구간
    if not focus:
        return "-"
    check_out = ld.to_date(row.get("check_out"))
    edge = {check_out} if check_out else set()   # 체크아웃 당일 — 점유는 아니나 기간의 끝
    occupied: set = set()
    for other in reservations:
        if ld.clean(other.get("request_no")) == ld.clean(row.get("request_no")):
            continue
        if ld.clean(other.get("lodging_code")) != code:
            continue
        if ld.clean(other.get("status")) not in ld.OCCUPYING_STATUSES:
            continue
        occupied.update(ld.day_span(other))

    tint = proto.LODGING_TINTS[_tint_index(code) % len(proto.LODGING_TINTS)]
    months: list[tuple[int, int]] = []
    for day in sorted(focus | edge):
        if (day.year, day.month) not in months:
            months.append((day.year, day.month))
    place = ld.lodging_label(lodging)
    today = date.today()
    # 장소는 바로 위 '장소·기간' 행이 소유하므로 달력 제목에서 뺀다(§4-2 중복 금지).
    cal = "".join(
        proto.mini_month_html(y, m, title=f"{y}년 {m}월",
                              occupied=occupied, focus=focus, edge=edge,
                              tint=tint, today=today)
        for y, m in months[:2]
    )
    items = [("사용기간", proto.ACCENT, proto.ACCENT), (f"{place} 기존 예약", *tint)]
    if focus & occupied:
        items.append(("겹침", "#fbeeee", "#9c3232"))
    # 수치(겹침·여유·점유율)는 중앙 속성 칸이 소유한다 — 달력 칸은 그림과 범례만.
    return f"<div class='pr-mini-wrap'>{cal}</div>{proto.legend_html(items)}"


def _gap_text(row: dict, reservations: list[dict]) -> str:
    """중복 여부 아래 보조 줄 — 앞뒤 여유일과 그 달 점유율.

    앞뒤 여유는 "이 신청 전후로 며칠이 비어 있나"다(일정 정정 여지를 판단하는 값).
    """
    code = ld.clean(row.get("lodging_code"))
    focus = set(ld.day_span(row))
    if not focus:
        return ""
    occupied: set = set()
    for other in reservations:
        if ld.clean(other.get("request_no")) == ld.clean(row.get("request_no")):
            continue
        if ld.clean(other.get("lodging_code")) != code:
            continue
        if ld.clean(other.get("status")) not in ld.OCCUPYING_STATUSES:
            continue
        occupied.update(ld.day_span(other))
    start, end = min(focus), max(focus)
    gap_before = gap_after = 0
    while gap_before < 30 and date.fromordinal(start.toordinal() - gap_before - 1) not in occupied:
        gap_before += 1
    while gap_after < 30 and date.fromordinal(end.toordinal() + gap_after + 1) not in occupied:
        gap_after += 1
    # 앞뒤 30일이 다 비어 있으면 적을 값이 없다 — 무정보 줄을 만들지 않는다.
    if gap_before >= 30 and gap_after >= 30:
        return ""
    return f"앞뒤 여유 {gap_before}일 / {gap_after}일"


def _tint_index(code: str) -> int:
    """숙소 코드 → 기준정보 순서 인덱스(색 축 고정 — 캘린더·신청 화면과 같은 배정)."""
    codes = list(db.lodging_map())
    return codes.index(code) if code in codes else len(proto.LODGING_TINTS) - 1


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
    by_code = db.lodging_map(include_inactive=False)
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


def _action_buttons(user: dict, row: dict, reservations: list[dict]) -> None:
    """실행 버튼 — 헤더 우측(참고 배치). **가능한 전이만** 그린다(§3.2).

    조건 미충족(의견 필요·체크아웃 전·겹침)은 비활성 + 사유를 판 하단 줄에 쓴다
    (``action_blocker`` 문구 그대로 — 화면이 사유를 지어내지 않는다, 계약 C9).
    부정 액션(취소·반려)은 부정 의미 색이고, 주 액션(승인/사용완료)은 우측 끝 primary.
    """
    status = ld.clean(row.get("status"))
    possible = _POSSIBLE.get(status, ())
    if not possible:
        st.markdown(f"<span style='font-size:12px;color:{proto.MUT};margin-left:auto;'>"
                    "종결 상태 — 더 이상 처리할 수 없습니다.</span>",
                    unsafe_allow_html=True)
        return

    request_no = ld.clean(row.get("request_no"))
    edit_key = f"{_EDIT_KEY}{request_no}"
    comment = ld.clean(st.session_state.get(f"{_OP_KEY}{request_no}", ""))
    editable = status == ld.REQUESTED

    clicked = None
    if editable and st.button("일정 수정", key=f"pract_edit_{request_no}",
                              type="secondary", width="content",
                              help="신청 건의 숙소·기간을 정정합니다"):
        st.session_state[edit_key] = not bool(st.session_state.get(edit_key, False))
        st.rerun()
    for action in possible:
        blocker = ld.action_blocker(row, action, user, comment=comment,
                                    reservations=reservations)
        negative = action in _NEGATIVE
        key_prefix = "prneg" if negative else "pract"
        if st.button(ld.ACTION_LABELS[action], key=f"{key_prefix}_{action}_{request_no}",
                     type="secondary" if negative else "primary",
                     width="content", disabled=bool(blocker), help=blocker):
            clicked = action

    if clicked == ld.ACT_CANCEL:
        st.session_state[_CONFIRM_KEY] = request_no
        st.rerun()
    elif clicked:
        _run(clicked, request_no, user, comment)
    if st.session_state.get(_CONFIRM_KEY) == request_no:
        _cancel_dialog(row, user, comment)
    with st.container(key="lm_editslot"):
        if editable and st.session_state.get(edit_key):
            _edit_form(user, row)


def _blocked_note(user: dict, row: dict, reservations: list[dict]) -> None:
    """비활성 사유를 판 하단에 쓴다 — 툴팁 단독 금지(§3.2·§4-3)."""
    status = ld.clean(row.get("status"))
    request_no = ld.clean(row.get("request_no"))
    comment = ld.clean(st.session_state.get(f"{_OP_KEY}{request_no}", ""))
    blocked = []
    for action in _POSSIBLE.get(status, ()):
        why = ld.action_blocker(row, action, user, comment=comment,
                                reservations=reservations)
        if why:
            blocked.append(f"{ld.ACTION_LABELS[action]} 불가: {why}")
    if blocked:
        proto.note_line(" · ".join(blocked))


@st.dialog("예약 취소 확인", width="large")
def _cancel_dialog(row: dict, user: dict, comment: str) -> None:
    """승인권자 취소도 되돌릴 수 없으므로 실행 전에 한 번 확인한다(D2).

    표시 계층의 오조작 방지일 뿐이며 권한·사유 필수 판정은 ``run_action`` 이 재확인한다.
    """
    request_no = ld.clean(row.get("request_no"))
    place = ld.lodging_label(db.lodging_map().get(ld.clean(row.get("lodging_code"))))
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
        db.run_lodging_action(request_no, action, current_user=user, comment=comment)
    except (ValueError, *db.DATA_SOURCE_ERRORS) as exc:
        _STATE.set_flash("error", f"{label} 처리 실패 — {exc}")
        st.rerun()
    except Exception:  # noqa: BLE001 — 저장 백엔드 오류(원문 비노출).
        _STATE.set_flash("error", f"{label} 처리 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.")
        st.rerun()
    _STATE.set_flash("success", f"{request_no} {label} 완료.")
    # 처리된 건은 승인 대기 목록에서 빠지므로 선택을 해제한다(다음 건이 자동 선택된다).
    st.session_state.pop(_SEL_KEY, None)
    st.rerun()
