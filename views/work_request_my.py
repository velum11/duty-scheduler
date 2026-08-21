"""내 업무요청 — 목록형 아코디언(DESIGN.md §1-B) + 제출됨 자기수정 · 처리완료 확인.

내 아차사고(``views/near_miss_my.py``)의 골격을 그대로 따른다:

    행 = 한 줄 요약(요청번호 모노 · 제목 · 유형 · 희망일 · 상태 · 캐럿) — 클릭 시 아래로 펼침.
    펼친 영역: 진행 단계 pill(제출→처리중→처리완료→종결) + 본문 블록 + 액션.

- 좌우 분할·행 체크박스·"요청을 선택하세요" 빈 패널 없음(§0 금지 1·2). 카드 금지(§0-5).
- 목록 범위는 위젯이 아니라 **인증 세션 사번**으로 고정한다(타인 건 열람 방지).
- 액션 게이트(종결 확인·보완 요청은 요청자 본인, 수정은 제출됨 상태만)는 화면이 아니라
  ``work_request_data.action_blocker`` / ``update_request`` 가 서버측에서 재확인한다.
"""
# DESIGN.md §1-B 목록형 아코디언 — 읽기 목록 + 인라인 펼침 상세/워크플로.
SCREEN_ARCHETYPE = "READ_VIEW"

from datetime import date

import streamlit as st

from modules import work_request_data as wr
from views.common import erp, proto, scaffold
from views.master import DraftState, banner, show_flash

_STATE = DraftState("work_request_my")
_PAGE_ID = _STATE.page_id
_SEL_KEY = "wrm_open_no"
_EDIT_KEY = "wrm_edit_open_"
_OP_KEY = "wrm_opinion_"

_ALL = "전체"
_BADGE_CODE = {
    wr.SUBMITTED: proto.BADGE_SUBMITTED,
    wr.IN_PROGRESS: proto.BADGE_IN_REVIEW,
    wr.DONE: proto.BADGE_EVALUATED,
    wr.CLOSED: proto.BADGE_CLOSED,
    wr.REJECTED: proto.BADGE_REJECTED,
}

# §1.2(2026-08-19) — 버튼 라벨 글자는 내부 <p> 가 소유하고 Streamlit 기본값 12.25px/500
# 으로 남는다(실측: 목록 행 4 · '내용 수정' 1 = 5곳, 네 단계·두 굵기 밖). 전역
# `.stApp [data-testid="stMarkdownContainer"] p` 와 특이도가 맞물리므로 같은 앵커를
# 선택자에 넣어 (0,3,2)로 올린다.
#   - 목록 행: 한 줄에 번호·제목·유형·우선순위·희망일·상태를 모두 싣는 요약이라 §1.2
#     `table`(12/400)을 쓴다. 14px 로 올리면 390px 폭에서 줄바꿈이 생겨 §4-5(행 높이
#     불변)를 깬다.
#   - '내용 수정': 결정 액션이라 `body-strong`(14/600).
_WRM_CSS = """
<style>
.stApp [class*="st-key-prrow_"] button [data-testid="stMarkdownContainer"] p {
  font-size:12px !important; font-weight:400 !important; }
.stApp [class*="st-key-pract_"] button [data-testid="stMarkdownContainer"] p {
  font-size:14px !important; font-weight:600 !important; }
.stApp [class*="st-key-wrm_"] label [data-testid="stMarkdownContainer"] p {
  font-size:12px !important; font-weight:600 !important; }
/* 히트영역 §1.4 compact(34~38) — 조건 select 가 실측 33px 로 1px 미달이었다. */
[class*="st-key-work_request_my_"] div[data-baseweb="select"] > div,
[class*="st-key-work_request_my_"] [data-testid="stSelectbox"] div[role="group"],
[class*="st-key-work_request_my_"] input,
[class*="st-key-wrm_"] [data-testid="stSelectbox"] div[role="group"],
[class*="st-key-wrm_"] input { min-height:34px !important; }
</style>
"""


def render(user: dict) -> None:
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="내 업무요청",
        desc="본인이 등록한 업무요청과 처리 상태를 확인하고 처리완료 건을 종결합니다.",
        breadcrumb="업무요청 › 내 업무요청",
        badges=scaffold.mode_badge(),
    )
    proto.inject()
    st.markdown(_WRM_CSS, unsafe_allow_html=True)
    show_flash(_STATE)

    emp_no = wr.clean(user.get("emp_no"))
    if not emp_no:
        banner("warn", "로그인 사번을 확인할 수 없어 내 업무요청을 표시할 수 없습니다.")
        return
    try:
        rows = wr.filter_requests(wr.load_requests(), requester_emp_no=emp_no)
    except ValueError as exc:
        banner("danger", str(exc))
        return

    if not rows:
        erp.detail_empty("등록한 업무요청이 없습니다",
                         "'업무요청 등록'에서 담당 부서에 처리할 업무를 요청할 수 있습니다.")
        return

    # §0-4·§4 영역 순서: 지표는 제목 바로 아래 첫 블록(필터보다 위). 값은 전체 내 요청
    # 기준이므로 필터와 무관하지만, 슬롯을 먼저 잡아 렌더 순서를 규약에 맞춘다.
    metric_slot = st.container()
    filters = _filters()
    shown = wr.filter_requests(
        rows,
        statuses=None if filters["status"] == _ALL else (filters["status"],),
        request_type=None if filters["type"] == _ALL else filters["type"],
    )
    with metric_slot:
        erp.metric_strip(_metrics(rows))

    if not shown:
        erp.detail_empty("조건에 해당하는 요청이 없습니다", "상태·유형 조건을 조정해 보세요.")
        return
    _render_list(user, shown)


def _filters() -> dict:
    values = erp.condition_panel(
        _PAGE_ID,
        [
            erp.Field(key="status", label="상태", width=150,
                      options=[_ALL] + list(wr.STATUSES),
                      format_func=lambda s: s if s == _ALL else wr.STATUS_LABELS.get(s, s)),
            erp.Field(key="type", label="요청 유형", width=140,
                      options=[_ALL] + list(wr.REQUEST_TYPES)),
        ],
        content_fit=True,
    )
    return {"status": values["status"], "type": values["type"]}


def _metrics(rows: list[dict]) -> list[tuple]:
    counts = wr.summarize(rows)
    return [
        ("총 요청", counts["TOTAL"], "건", "TOTAL", counts["TOTAL"] > 0),
        ("진행중", counts["PENDING"], "건", "PENDING", False),
        ("확인 대기", counts[wr.DONE], "건", "DONE", counts[wr.DONE] > 0),
        ("종결·반려", counts[wr.CLOSED] + counts[wr.REJECTED], "건", "CLOSED", False),
        ("기한 초과", counts["OVERDUE"], "건", "OVERDUE", counts["OVERDUE"] > 0),
    ]


# ===========================================================================
# 목록형 아코디언
# ===========================================================================
def _render_list(user: dict, rows: list[dict]) -> None:
    """한 줄 요약 행(전체폭 클릭 버튼) + 클릭 시 인라인 펼침(단일 아코디언)."""
    ordered = sorted(rows, key=lambda r: wr.clean(r.get("created_at")), reverse=True)
    st.markdown(f"<div style='border-top:1px solid {proto.LINE_SEC};'></div>",
                unsafe_allow_html=True)

    open_no = wr.clean(st.session_state.get(_SEL_KEY))
    numbers = {wr.clean(r.get("request_no")) for r in ordered}
    if open_no and open_no not in numbers:
        open_no = ""
        st.session_state.pop(_SEL_KEY, None)

    today = date.today()
    for row in ordered:
        no = wr.clean(row.get("request_no"))
        status = wr.clean(row.get("status"))
        badge_code = _BADGE_CODE.get(status, proto.BADGE_CLOSED)
        is_open = (no == open_no)
        overdue = " · 기한초과" if wr.is_overdue(row, today=today) else ""
        # 요청번호 / 제목 / 메타 세 덩어리를 EM SPACE(U+2003)로 벌린다 — ASCII 공백은 HTML
        # 에서 하나로 접혀 한 줄이 통째로 붙어 보인다. 버튼 라벨은 혼합 서식이 불가하므로
        # 상태는 텍스트 + 좌측 색바로 이중부호화한다(DESIGN 부속서 A-4).
        label = (f"{no}  {wr.clean(row.get('title'))}  "
                 f"{wr.clean(row.get('request_type'))} · {wr.clean(row.get('priority'))} · "
                 f"희망 {wr.clean(row.get('desired_due'))} · "
                 f"{wr.STATUS_LABELS.get(status, status)}{overdue}")
        key = f"prrow_{no}__b_{badge_code}__{'open' if is_open else 'shut'}"
        if st.button(label, key=key, width="stretch"):
            st.session_state[_SEL_KEY] = "" if is_open else no
            st.rerun()
        if is_open:
            _render_detail(user, row, status)


def _render_detail(user: dict, row: dict, status: str) -> None:
    """펼친 행 상세: 진행 단계 pill → 피드백 배너 → 메타 → 본문 블록 → 액션."""
    with st.container(border=False):
        st.markdown(
            proto.steps_html(list(wr.PROGRESS_ORDER), status,
                             branch=(wr.REJECTED, "반려")),
            unsafe_allow_html=True,
        )
        reason = wr.clean(row.get("reject_reason"))
        if status == wr.REJECTED and reason:
            banner("warn", f"반려 사유: {reason}")
        elif status == wr.IN_PROGRESS and reason:
            banner("info", f"보완 요청 사유: {reason}")

        st.markdown(proto.meta_cells([
            ("처리 부서", wr.dept_label(row.get("target_dept"))),
            ("담당자", wr.clean(row.get("assignee_name")) or "미지정"),
            ("희망 완료일", wr.clean(row.get("desired_due"))),
            ("등록일시", wr.clean(row.get("created_at"))),
            ("최근 갱신", wr.clean(row.get("updated_at"))),
        ]), unsafe_allow_html=True)
        # §1.1 간격 스케일 — 14px 은 스케일 밖이었다(2026-08-19 §1.2 개정 정합화).
        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        st.markdown(proto.body_blocks([
            ("REQUEST", "요청 내용", wr.clean(row.get("content")), True),
            ("REF", "참고 사항", wr.clean(row.get("reference")), False),
            ("RESULT", "처리 결과", wr.clean(row.get("result_note")), True),
        ]), unsafe_allow_html=True)

        _render_actions(user, row, status)
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)


def _render_actions(user: dict, row: dict, status: str) -> None:
    """요청자 액션 — 처리완료 건의 [종결 확인]·[보완 요청], 제출됨 건의 [내용 수정]."""
    no = wr.clean(row.get("request_no"))
    if status == wr.DONE:
        op_key = f"{_OP_KEY}{no}"
        comment = wr.clean(st.session_state.get(op_key, ""))
        with st.container(horizontal=True, gap="small", vertical_alignment="bottom"):
            st.text_input("확인 의견 · 보완 요청 시 필수", key=op_key, width="stretch",
                          placeholder="보완이 필요하면 사유를 적어 주세요")
            reopen_block = wr.action_blocker(row, wr.ACT_REOPEN, user, comment=comment)
            close_block = wr.action_blocker(row, wr.ACT_CLOSE, user, comment=comment)
            reopen = st.button("보완 요청", key=f"pract_reopen_{no}", type="secondary",
                               disabled=bool(reopen_block), help=reopen_block)
            close = st.button("종결 확인", key=f"pract_close_{no}", type="primary",
                              disabled=bool(close_block), help=close_block)
        if reopen:
            _run(wr.ACT_REOPEN, no, user, comment)
        if close:
            _run(wr.ACT_CLOSE, no, user, comment)
        return

    if status != wr.SUBMITTED:
        proto.note_line("제출됨 상태에서만 내용을 수정할 수 있고, 처리완료 건만 종결 확인할 수 있습니다.")
        return

    edit_key = f"{_EDIT_KEY}{no}"
    if st.button("내용 수정", key=f"pract_edit_{no}", type="secondary"):
        st.session_state[edit_key] = not bool(st.session_state.get(edit_key, False))
        st.rerun()
    if st.session_state.get(edit_key):
        _render_edit_form(user, row)


def _render_edit_form(user: dict, row: dict) -> None:
    no = wr.clean(row.get("request_no"))
    with st.form(f"wrm_edit_{no}", clear_on_submit=False):
        title = st.text_input("요청 제목", value=wr.clean(row.get("title")),
                              max_chars=wr.TITLE_MAX)
        c1, c2, c3, c4 = st.columns([1, 1, 1.3, 1])
        types = list(wr.REQUEST_TYPES)
        prios = list(wr.PRIORITIES)
        depts = list(wr.TARGET_DEPTS)
        with c1:
            request_type = st.selectbox(
                "요청 유형", types, width=140,
                index=types.index(wr.clean(row.get("request_type")))
                if wr.clean(row.get("request_type")) in types else 0)
        with c2:
            priority = st.selectbox(
                "우선순위", prios, width=140,
                index=prios.index(wr.clean(row.get("priority")))
                if wr.clean(row.get("priority")) in prios else 0)
        with c3:
            target_dept = st.selectbox(
                "처리 부서", depts, width=230, format_func=wr.dept_label,
                index=depts.index(wr.clean(row.get("target_dept")))
                if wr.clean(row.get("target_dept")) in depts else 0)
        with c4:
            due = wr.to_date(row.get("desired_due")) or date.today()
            desired_due = st.date_input("희망 완료일", value=due, format="YYYY-MM-DD", width=170)
        content = st.text_area("요청 내용", value=wr.clean(row.get("content")), height=130)
        reference = st.text_input("참고 사항", value=wr.clean(row.get("reference")),
                                  max_chars=200)
        saved = erp.form_submit("수정 저장")

    if not saved:
        return
    payload = {
        "title": title, "request_type": request_type, "priority": priority,
        "target_dept": target_dept, "desired_due": desired_due,
        "content": content, "reference": reference,
    }
    try:
        wr.update_request(no, payload, current_user=user)
    except ValueError as exc:
        banner("danger", f"수정하지 못했습니다 — {exc}")
        return
    except Exception:  # noqa: BLE001 — 저장 백엔드 오류(원문 비노출).
        banner("danger", "수정 중 오류가 발생했습니다. 목록을 재조회한 뒤 다시 시도하세요.")
        return
    st.session_state.pop(f"{_EDIT_KEY}{no}", None)
    _STATE.set_flash("success", f"{no} 내용을 수정했습니다.")
    st.rerun()


def _run(action: str, request_no: str, user: dict, comment: str) -> None:
    label = wr.ACTION_LABELS.get(action, action)
    try:
        wr.run_action(request_no, action, current_user=user, comment=comment)
    except ValueError as exc:
        _STATE.set_flash("error", f"{label} 처리 실패 — {exc}")
        st.rerun()
    except Exception:  # noqa: BLE001
        _STATE.set_flash("error", f"{label} 처리 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.")
        st.rerun()
    _STATE.set_flash("success", f"{request_no} {label} 완료.")
    st.rerun()
