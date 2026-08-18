"""업무요청 처리 — 큐 처리형(DESIGN.md §1-A / §0 MASTER_DETAIL).

    제목/설명 → [지표 스트립] → 헤어라인 → [조회 조건] → [큐 칩 스트립] → 헤어라인
    → [선택 건 전체폭 상세] → 헤어라인 → [액션 바: 담당자 | 처리 의견 | 반려 착수 완료]

아차사고 평가 관리(``views/near_miss_evaluate.py``)의 골격을 그대로 따른다. 진입 시 큐의
첫 건이 자동 선택되고 칩 클릭 = 선택, 이전/다음으로 순회한다. 좌우 분할·빈 우측 패널·행
체크박스를 쓰지 않는다(§0 금지 1·2).

권한: 처리자(프로토타입 가정 ``role ∈ {ADMIN, MANAGER}``)만 진입한다. 액션 비활성 사유는
``work_request_data.action_blocker`` 단일 출처를 그대로 툴팁에 쓴다.
"""
# DESIGN.md §1-A 큐 처리형 — 읽기 큐(칩) + 전체폭 상세/워크플로.
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


def render(user: dict) -> None:
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="업무요청 처리",
        desc="접수된 업무요청을 담당자에게 배정하고 처리·완료·반려합니다.",
        breadcrumb="업무요청 › 업무요청 처리",
        badges=scaffold.mode_badge(),
    )
    proto.inject()
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
    st.markdown(
        "<div style='display:flex;flex-wrap:wrap;align-items:center;gap:10px;"
        "margin:2px 0 10px;'>"
        f"<span style='font-family:{proto.MONO};font-size:18px;font-weight:600;"
        f"color:{proto.INK};'>{wr.clean(row.get('request_no'))}</span>"
        f"{proto.badge(_BADGE_CODE.get(status, proto.BADGE_CLOSED), wr.STATUS_LABELS.get(status, status))}"
        f"<span style='font-size:12.5px;font-weight:600;"
        f"color:{_PRIORITY_COLOR.get(priority, proto.INK2)};'>{priority}</span></div>"
        f"<div style='font-size:17px;font-weight:600;color:{proto.INK};"
        f"letter-spacing:-0.02em;margin:0 0 14px;'>{_esc(row.get('title'))}</div>",
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
