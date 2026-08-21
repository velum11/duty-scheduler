"""업무요청 처리 — 큐 칩 + 전체폭 상세(프로토타입, app.py 미라우팅).

    제목/설명 → [지표 스트립] → 헤어라인 → [조회 조건] → [큐 칩 스트립] → 헤어라인
    → [선택 건 전체폭 상세] → 헤어라인 → [액션 바: 담당자 | 처리 의견 | 반려 착수 완료]

아차사고 평가 관리(``views/near_miss_evaluate.py``)의 골격을 그대로 따른다. 진입 시 큐의
첫 건이 자동 선택되고 칩 클릭 = 선택, 이전/다음으로 순회한다. 좌우 분할·빈 우측 패널·행
체크박스를 쓰지 않는다(§0 금지 1·2).

권한: 처리자(프로토타입 가정 ``role ∈ {ADMIN, MANAGER}``)만 진입한다. 액션 비활성 사유는
``work_request_data.action_blocker`` 단일 출처를 그대로 툴팁에 쓴다.
"""
# 현재 구현은 칩 스트립 + 전체폭 상세이며 DESIGN.md §2 WORKLIST 골격(상태 탭 + 2열
# 33/67 + 지표 타일 없음)과 아직 다르다. §7.1 이관 목록의 "승인 큐 4화면"에 이 화면이
# 들어 있고 골격 이관은 별도 범위다 — 여기서는 §1.1·§1.2 토큰만 정합화했다(2026-08-19).
SCREEN_ARCHETYPE = "WORKLIST"

from html import escape

import streamlit as st

from modules import work_request_data as wr
from views.common import erp, proto, scaffold
from views.master import DraftState, empty_state, show_flash, banner

_STATE = DraftState("work_request_handle")
_PAGE_ID = _STATE.page_id
_SEL_KEY = "wrh_selected_no"
_OP_KEY = "wrh_opinion_"
_ASSIGNEE_KEY = "wrh_assignee_"

_ALL = "전체"
_PRIORITY_RANK = {"긴급": 0, "보통": 1, "낮음": 2}
_BADGE_CODE = {
    wr.SUBMITTED: proto.BADGE_SUBMITTED,
    wr.IN_PROGRESS: proto.BADGE_IN_REVIEW,
    wr.DONE: proto.BADGE_EVALUATED,
    wr.CLOSED: proto.BADGE_CLOSED,
    wr.REJECTED: proto.BADGE_REJECTED,
}
_PRIORITY_COLOR = {"긴급": "#9c3232", "보통": "#4a453d", "낮음": "#6b665d"}

# §1.2(2026-08-19) — 버튼·위젯 라벨 글자는 내부 <p>/<label> 이 소유한다. 공용 CSS 가
# button 에만 font-size 를 걸면 <p> 는 Streamlit 기본 12.25px 로 남는다(실측: 칩 4 ·
# ‹› 2 · 액션 3 · 위젯 라벨 2 = 11곳). 네 단계(24/20/14/12) 밖 값이므로 이 화면의
# st-key 선택자로 되돌린다. 개선조치 관리(:168)가 같은 이유로 쓰는 규칙과 같은 형태다.
_WRH_CSS = """
<style>
/* 선택자 특이도 주의 — 앱 전역에 `.stApp [data-testid="stMarkdownContainer"] p`(0,2,1)
   규칙이 있어 `[class*=…] button p`(0,1,2) 로는 지지 않는 쪽이 생긴다(실측: 액션·나브는
   먹고 칩만 12.25px 로 남았다). 같은 앵커를 선택자에 넣어 (0,3,2)로 올린다. */
/* 큐 칩 라벨 — 공용 proto 가 button 에 건 12/600 을 <p> 에도 적용한다. */
.stApp [class*="st-key-prq_"] button [data-testid="stMarkdownContainer"] p {
  font-size:12px !important; font-weight:600 !important; }
/* 큐 순회 ‹ › — 공용이 button 에 건 14px 을 <p> 에도 적용한다. */
.stApp .st-key-pr_prev button [data-testid="stMarkdownContainer"] p,
.stApp .st-key-pr_next button [data-testid="stMarkdownContainer"] p { font-size:14px !important; }
/* 결정 액션(반려·처리 착수·처리 완료) — body-strong(14/600). */
.stApp [class*="st-key-pract_"] button [data-testid="stMarkdownContainer"] p {
  font-size:14px !important; font-weight:600 !important; }
/* 액션 바 위젯 라벨 — §1.2 label-strong(12/600). 조건 패널 라벨과 같은 계층이다. */
.stApp [class*="st-key-wrh_"] label [data-testid="stMarkdownContainer"] p {
  font-size:12px !important; font-weight:600 !important; }
/* 히트영역 §1.4 compact(34~38) — 조건 select·검색창·액션 바 select/text 가 실측 33px 로
   1px 미달이었다. 개선조치 관리(:186)가 자기 위젯 key 에 거는 규칙과 같은 형태다. */
[class*="st-key-work_request_handle_"] div[data-baseweb="select"] > div,
[class*="st-key-work_request_handle_"] [data-testid="stSelectbox"] div[role="group"],
[class*="st-key-work_request_handle_"] input,
[class*="st-key-wrh_"] div[data-baseweb="select"] > div,
[class*="st-key-wrh_"] [data-testid="stSelectbox"] div[role="group"],
[class*="st-key-wrh_"] input { min-height:34px !important; }
</style>
"""


def render(user: dict) -> None:
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="업무요청 처리",
        desc="접수된 업무요청을 담당자에게 배정하고 처리·완료·반려합니다.",
        breadcrumb="업무요청 › 업무요청 처리",
        badges=scaffold.mode_badge(),
    )
    proto.inject()
    st.markdown(_WRH_CSS, unsafe_allow_html=True)
    if not wr.can_handle(user):
        empty_state("업무요청 처리 권한이 없습니다",
                    "관리자·매니저만 업무요청을 처리할 수 있습니다.")
        return
    show_flash(_STATE)
    _render_body(user)


def _render_body(user: dict) -> None:
    try:
        rows = wr.load_requests()
    except ValueError as exc:
        banner("danger", str(exc))
        return

    erp.metric_strip(_metrics(rows))
    proto.hairline()

    cond = _conditions()
    queue = _queue(rows, cond)
    if not queue:
        erp.detail_empty("처리할 업무요청이 없습니다",
                         "조건에 해당하는 미처리 요청이 없습니다. 부서·우선순위 조건을 조정해 보세요.")
        st.session_state.pop(_SEL_KEY, None)
        return

    ordered = [wr.clean(r.get("request_no")) for r in queue]
    selected = wr.clean(st.session_state.get(_SEL_KEY))
    if selected not in ordered:
        selected = ordered[0]
        st.session_state[_SEL_KEY] = selected

    _queue_chips(queue, ordered, selected)
    proto.hairline()
    _detail(user, rows, selected)


# ===========================================================================
# 지표 · 조건 · 큐
# ===========================================================================
def _metrics(rows: list[dict]) -> list[tuple]:
    counts = wr.summarize(rows)
    urgent = sum(1 for r in rows
                 if wr.clean(r.get("priority")) == "긴급"
                 and wr.clean(r.get("status")) in wr.PENDING_STATUSES)
    return [
        ("미착수", counts[wr.SUBMITTED], "건", "SUBMITTED", counts[wr.SUBMITTED] > 0),
        ("처리중", counts[wr.IN_PROGRESS], "건", "IN PROGRESS", False),
        ("긴급 미처리", urgent, "건", "URGENT", urgent > 0),
        ("기한 초과", counts["OVERDUE"], "건", "OVERDUE", counts["OVERDUE"] > 0),
        ("확인 대기", counts[wr.DONE], "건", "DONE", False),
    ]


def _conditions() -> dict:
    values = erp.condition_panel(
        _PAGE_ID,
        [
            erp.Field(key="dept", label="처리 부서", width=230,
                      options=[_ALL] + list(wr.TARGET_DEPTS),
                      format_func=lambda v: v if v == _ALL else wr.dept_label(v)),
            erp.Field(key="priority", label="우선순위", width=130,
                      options=[_ALL] + list(wr.PRIORITIES)),
            erp.Field(key="type", label="요청 유형", width=130,
                      options=[_ALL] + list(wr.REQUEST_TYPES)),
            erp.Field(key="q", label="제목·내용 검색", kind="text",
                      placeholder="키워드"),
        ],
        content_fit=True,
    )
    return values


def _queue(rows: list[dict], cond: dict) -> list[dict]:
    """미처리(제출됨·처리중) 큐 — 긴급 우선, 그다음 희망 완료일 순."""
    filtered = wr.filter_requests(
        rows, statuses=wr.PENDING_STATUSES,
        target_dept=None if cond["dept"] == _ALL else cond["dept"],
        priority=None if cond["priority"] == _ALL else cond["priority"],
        request_type=None if cond["type"] == _ALL else cond["type"],
        keyword=cond.get("q"),
    )
    return sorted(filtered, key=lambda r: (
        _PRIORITY_RANK.get(wr.clean(r.get("priority")), 9),
        wr.clean(r.get("desired_due")) or "9999-12-31",
        wr.clean(r.get("request_no")),
    ))


def _queue_chips(queue: list[dict], ordered: list[str], selected: str) -> None:
    index = ordered.index(selected)
    proto.queue_head("처리 큐", len(ordered))
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        for row in queue:
            no = wr.clean(row.get("request_no"))
            title = wr.clean(row.get("title"))
            if len(title) > 18:
                title = title[:17] + "…"
            # 칩은 번호 뒤 일련번호만(WR-202608-002 → 002). 긴급은 글자로 명시한다
            # (칩 색은 '선택' 축이 이미 쓰고 있어 우선순위를 색으로 겹쳐 싣지 않는다).
            mark = "긴급 " if wr.clean(row.get("priority")) == "긴급" else ""
            if st.button(f"{mark}{no.rsplit('-', 1)[-1]} · {title}", key=f"prq_{no}",
                         type="primary" if no == selected else "secondary") and no != selected:
                st.session_state[_SEL_KEY] = no
                st.rerun()
        st.markdown(f"<span class='pr-qpos'>{index + 1}/{len(ordered)}</span>",
                    unsafe_allow_html=True)
        if st.button("‹", key="pr_prev", help="이전 건", disabled=index <= 0):
            st.session_state[_SEL_KEY] = ordered[index - 1]
            st.rerun()
        if st.button("›", key="pr_next", help="다음 건", disabled=index >= len(ordered) - 1):
            st.session_state[_SEL_KEY] = ordered[index + 1]
            st.rerun()


# ===========================================================================
# 전체폭 상세 + 액션 바
# ===========================================================================
def _detail(user: dict, rows: list[dict], request_no: str) -> None:
    row = next((r for r in rows if wr.clean(r.get("request_no")) == request_no), None)
    if row is None or wr.clean(row.get("status")) not in wr.PENDING_STATUSES:
        st.session_state.pop(_SEL_KEY, None)
        erp.detail_empty("이 요청은 더 이상 대기 중이 아닙니다",
                         "다른 사용자가 먼저 처리했을 수 있습니다 — 새로고침한 뒤 다시 선택하세요.")
        return

    status = wr.clean(row.get("status"))
    priority = wr.clean(row.get("priority"))
    overdue = wr.is_overdue(row)
    left = wr.days_left(row)
    # §1.2(2026-08-19) — 글꼴은 Pretendard 하나이고 크기는 24/20/14/12 뿐이다.
    # 식별자는 body-strong(14/600) + tabular-nums(모노 폐지), 대상 제목은 section(20/600).
    # 간격은 §1.1 스케일(8/16)만 쓴다.
    st.markdown(
        "<div style='display:flex;flex-wrap:wrap;align-items:center;gap:8px;"
        "margin:0 0 8px;'>"
        "<span style='font-size:14px;font-weight:600;"
        f"font-variant-numeric:tabular-nums;color:{proto.INK};'>"
        f"{wr.clean(row.get('request_no'))}</span>"
        f"{proto.badge(_BADGE_CODE.get(status, proto.BADGE_CLOSED), wr.STATUS_LABELS.get(status, status))}"
        f"<span style='font-size:12px;font-weight:600;"
        f"color:{_PRIORITY_COLOR.get(priority, proto.INK2)};'>{priority}</span></div>"
        f"<div style='font-size:20px;font-weight:600;color:{proto.INK};"
        f"margin:0 0 16px;'>{_esc(row.get('title'))}</div>",
        unsafe_allow_html=True,
    )
    # 기한 초과는 색(danger)+문구로 이중부호화한다 — 색만으로 알리지 않는다.
    due = _esc(row.get("desired_due"))
    if overdue:
        due_html = f"{due} <span style='color:#9c3232;font-weight:600;'>기한 초과</span>"
    elif left is not None:
        due_html = f"{due} <span style='color:{proto.MUT};'>" + \
                   (f"D-{left}" if left > 0 else "오늘") + "</span>"
    else:
        due_html = due
    st.markdown(proto.meta_cells([
        ("요청자", f"{wr.clean(row.get('requester_name'))}({wr.clean(row.get('requester_emp_no'))})"),
        ("요청 부서", wr.dept_label(row.get("requester_dept"))),
        ("처리 부서", wr.dept_label(row.get("target_dept"))),
        ("요청 유형", wr.clean(row.get("request_type"))),
        ("희망 완료일", due_html, "html"),
        ("담당자", wr.clean(row.get("assignee_name")) or "미지정"),
        ("등록일시", wr.clean(row.get("created_at"))),
    ]), unsafe_allow_html=True)
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    st.markdown(proto.body_blocks([
        ("REQUEST", "요청 내용", wr.clean(row.get("content")), True),
        ("REF", "참고 사항", wr.clean(row.get("reference")), False),
        ("REASON", "직전 보완 사유", wr.clean(row.get("reject_reason")), False),
    ]), unsafe_allow_html=True)

    proto.hairline(top="16px", bottom="12px")
    _action_bar(user, row, rows)


def _action_bar(user: dict, row: dict, rows: list[dict]) -> None:
    """담당자 지정 + 처리 의견 + [반려] [처리 착수] [처리 완료]."""
    no = wr.clean(row.get("request_no"))
    op_key = f"{_OP_KEY}{no}"
    comment = wr.clean(st.session_state.get(op_key, ""))
    candidates = _assignee_candidates(user, rows, row)
    assignee_key = f"{_ASSIGNEE_KEY}{no}"

    with st.container(horizontal=True, gap="small", vertical_alignment="bottom"):
        picked = st.selectbox(
            "처리 담당자", list(candidates), key=assignee_key, width=200,
            format_func=lambda emp: candidates[emp]["label"],
        )
        st.text_input("처리 의견 · 완료 결과·반려 사유 필수", key=op_key, width="stretch",
                      placeholder="처리 결과 또는 반려 사유를 한 줄로")
        assignee = candidates.get(picked)
        reject_block = wr.action_blocker(row, wr.ACT_REJECT, user, comment=comment)
        start_block = wr.action_blocker(row, wr.ACT_START, user, comment=comment,
                                        assignee=assignee)
        done_block = wr.action_blocker(row, wr.ACT_COMPLETE, user, comment=comment)
        reject = st.button("반려", key=f"pract_reject_{no}", type="secondary",
                           disabled=bool(reject_block), help=reject_block)
        start = st.button("처리 착수", key=f"pract_start_{no}", type="secondary",
                          disabled=bool(start_block), help=start_block)
        complete = st.button("처리 완료", key=f"pract_complete_{no}", type="primary",
                             disabled=bool(done_block), help=done_block)

    if reject:
        _run(wr.ACT_REJECT, no, user, comment)
    if start:
        _run(wr.ACT_START, no, user, comment, assignee=assignee)
    if complete:
        _run(wr.ACT_COMPLETE, no, user, comment)


def _assignee_candidates(user: dict, rows: list[dict], row: dict) -> dict:
    """담당자 후보 — 현재 처리자(본인) + 기존 배정 이력. 프로토타입 범위의 단순 목록이며,
    통합 시 처리 부서 소속 사용자 조회(``db.get_users``)로 대체한다."""
    out: dict[str, dict] = {}
    me = wr.clean(user.get("emp_no"))
    if me:
        name = wr.clean(user.get("name")) or me
        out[me] = {"emp_no": me, "name": name, "label": f"{name}({me}) · 본인"}
    for source in [row] + list(rows):
        emp = wr.clean(source.get("assignee_emp_no"))
        if emp and emp not in out:
            name = wr.clean(source.get("assignee_name")) or emp
            out[emp] = {"emp_no": emp, "name": name, "label": f"{name}({emp})"}
    if not out:
        out[""] = {"emp_no": "", "name": "", "label": "— 담당자 없음 —"}
    return out


def _run(action: str, request_no: str, user: dict, comment: str,
         assignee: dict | None = None) -> None:
    label = wr.ACTION_LABELS.get(action, action)
    try:
        wr.run_action(request_no, action, current_user=user, comment=comment,
                      assignee=assignee)
    except ValueError as exc:
        _STATE.set_flash("error", f"{label} 처리 실패 — {exc}")
        st.rerun()
    except Exception:  # noqa: BLE001 — 저장 백엔드 오류(원문 비노출).
        _STATE.set_flash("error", f"{label} 처리 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.")
        st.rerun()
    _STATE.set_flash("success", f"{request_no} {label} 완료.")
    if action != wr.ACT_START:
        st.session_state.pop(_SEL_KEY, None)  # 큐에서 빠지는 건은 선택 해제
    st.rerun()


def _esc(value) -> str:
    return escape(wr.clean(value))
