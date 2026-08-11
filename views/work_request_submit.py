"""업무요청 등록 — 폼형(DESIGN.md §1-D) 단건 제출 폼(FORM_ENTRY).

아차사고 등록(``views/near_miss_submit.py``)의 골격을 그대로 따른다:

    REQUESTER 신원 줄(읽기 전용) → 01 · 요청 개요 → 02 · 요청 내용
    우측 aside: 필수 6항목 체크리스트 + 진행 바 + [요청서 제출]

- 카드 금지(§0-5), §2 팔레트만(§0-8), 입력 14.5px·라벨 12.5px(§3).
- ``st.form`` 을 쓰지 않아 체크리스트가 입력 즉시 갱신된다. 제출 시 전체 재검증.
- 요청자 신원(사번·성명·소속)은 세션 사용자에서 서버측 확정한다(위조 방지).
"""
# DESIGN.md §1-D 폼형 — 단건 입력·제출.
SCREEN_ARCHETYPE = "FORM_ENTRY"

from datetime import date, timedelta

import streamlit as st

from modules import mailer
from modules import work_request_data as wr
from views.common import erp, proto, scaffold
from views.master import PersistResult, banner, ledger_banner

_PAGE_ID = "work_request_submit"
_DONE_KEY = "wr_submit_done"

_K_TITLE = "wr_f_title"
_K_TYPE = "wr_f_type"
_K_PRIORITY = "wr_f_priority"
_K_DEPT = "wr_f_dept"
_K_DUE = "wr_f_due"
_K_CONTENT = "wr_f_content"
_K_REF = "wr_f_reference"
_FORM_KEYS = (_K_TITLE, _K_TYPE, _K_PRIORITY, _K_DEPT, _K_DUE, _K_CONTENT, _K_REF)


def render(user: dict) -> None:
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="업무요청 등록",
        desc="담당 부서에 처리할 업무를 요청합니다. 등록 후 상태는 제출됨(SUBMITTED)입니다.",
        breadcrumb="업무요청 › 업무요청 등록",
        badges=scaffold.mode_badge(),
    )
    proto.inject()

    done = st.session_state.get(_DONE_KEY)
    if done:
        _render_post_submit(done)
        return

    if not wr.clean(user.get("emp_no")):
        banner("warn", "로그인 사번을 확인할 수 없어 요청서를 등록할 수 없습니다.")
        return
    _render_form(user)


def _render_form(user: dict) -> None:
    with st.container(key="pr_formwrap"):
        form_col, side_col = st.columns([2.7, 1.0], vertical_alignment="top")
        with form_col:
            proto.identity_row(
                "REQUESTER",
                [("요청자", wr.clean(user.get("name")) or "(이름 미확인)"),
                 ("사번", wr.clean(user.get("emp_no"))),
                 ("소속", wr.clean(user.get("dept_code")) or "미지정")],
                lock="로그인 정보로 자동 지정 · 수정 불가",
            )

            # ── 01 · 요청 개요 ──
            proto.section("01", "요청 개요")
            title = st.text_input("요청 제목 *", max_chars=wr.TITLE_MAX, key=_K_TITLE,
                                  placeholder="예: 생산관리 PC 3대 교체 요청")
            c1, c2, c3, c4 = st.columns([1, 1, 1.3, 1])
            with c1:
                request_type = st.selectbox("요청 유형 *", [""] + list(wr.REQUEST_TYPES),
                                            key=_K_TYPE, width=140,
                                            format_func=lambda v: "— 선택 —" if v == "" else v)
            with c2:
                priority = st.selectbox("우선순위 *", [""] + list(wr.PRIORITIES),
                                        key=_K_PRIORITY, width=140,
                                        format_func=lambda v: "— 선택 —" if v == "" else v)
            with c3:
                target_dept = st.selectbox(
                    "처리 부서 *", [""] + list(wr.TARGET_DEPTS), key=_K_DEPT, width=230,
                    format_func=lambda v: "— 선택 —" if v == "" else wr.dept_label(v),
                )
            with c4:
                desired_due = st.date_input("희망 완료일 *", value=date.today() + timedelta(days=7),
                                            format="YYYY-MM-DD", key=_K_DUE, width=170)

            # ── 02 · 요청 내용 ──
            proto.section("02", "요청 내용")
            content = st.text_area(
                "요청 내용 *", height=150, key=_K_CONTENT,
                placeholder="무엇이 · 어디서 · 어떻게 문제인지와 필요한 조치를 구체적으로 적어 주세요",
            )
            reference = st.text_input("참고 사항", max_chars=200, key=_K_REF,
                                      placeholder="자산번호 · 작업 가능 시간 등(선택)")

        with side_col:
            st.markdown(
                _checklist(title, request_type, priority, target_dept, desired_due, content),
                unsafe_allow_html=True,
            )
            proto.submit_hint("제출 후 상태는 ", "제출됨(SUBMITTED)", "이 됩니다.")
            submitted = st.button("요청서 제출", type="primary", key="wr_submit_btn",
                                  width="stretch")

    if not submitted:
        return

    payload = {
        "title": title,
        "request_type": request_type,
        "priority": priority,
        "target_dept": target_dept,
        "desired_due": desired_due,
        "content": content,
        "reference": reference,
    }
    errors = wr.validate_request(payload)
    if errors:
        banner("danger", " / ".join(errors))
        return
    _persist(payload, user)


def _checklist(title, request_type, priority, target_dept, desired_due, content) -> str:
    today = date.today()
    due = wr.to_date(desired_due)
    items = [
        ("요청 제목", bool(wr.clean(title))),
        ("요청 유형", wr.clean(request_type) in wr.REQUEST_TYPES),
        ("우선순위", wr.clean(priority) in wr.PRIORITIES),
        ("처리 부서", bool(wr.clean(target_dept))),
        ("희망 완료일", due is not None and due >= today),
        ("요청 내용", len(wr.clean(content)) >= wr.CONTENT_MIN),
    ]
    return proto.checklist_html(
        items,
        note=f"요청 내용은 {wr.CONTENT_MIN}자 이상 적어 주세요. 제출 시 전체가 다시 검증됩니다.",
    )


def _persist(payload: dict, user: dict) -> None:
    try:
        record = wr.create_request(payload, current_user=user)
    except ValueError as exc:
        ledger_banner(PersistResult.failure(_PAGE_ID, ["업무요청"], str(exc), retryable=True))
        return
    except Exception:  # noqa: BLE001 — 저장 백엔드 오류(원문 비노출).
        ledger_banner(PersistResult.unresolved(
            _PAGE_ID, "저장 결과를 확인할 수 없습니다. 내 업무요청에서 확인한 뒤 다시 시도하세요."))
        return
    # 접수 저장 성공 후 담당자 알림 — 발송 결과가 접수를 되돌리지 않는다(mailer 계약).
    mail = mailer.notify_work_request_created(
        record,
        target_dept_label=wr.dept_label(record.get("target_dept")),
        requester_dept_label=wr.dept_label(record.get("requester_dept")),
    )
    st.session_state[_DONE_KEY] = {
        "request_no": wr.clean(record.get("request_no")),
        "title": wr.clean(record.get("title")),
        "target_dept": wr.dept_label(record.get("target_dept")),
        "mail": mail,
    }
    st.rerun()


def _render_post_submit(done: dict) -> None:
    request_no = wr.clean(done.get("request_no")) or "(번호 확인 필요)"
    ledger_banner(PersistResult.success(_PAGE_ID, [request_no]))
    banner("success",
           f"업무요청을 등록했습니다. 요청번호 {request_no} · {done.get('target_dept')} · "
           "상태 제출됨(SUBMITTED)")
    if done.get("mail") is True:
        proto.note_line("처리 부서 담당자에게 접수 알림 메일을 발송했습니다.")
    elif done.get("mail") is False:
        banner("warn", "접수는 완료됐지만 담당자 알림 메일 발송에 실패했습니다. 담당자에게 별도로 알려주세요.")
    proto.note_line("처리 진행 상황은 '내 업무요청'에서 확인하고, 처리완료 건은 직접 종결 확인합니다.")
    if st.button("새 업무요청 등록", key="wr_done_new", icon=":material/add:"):
        for key in _FORM_KEYS:
            st.session_state.pop(key, None)
        st.session_state.pop(_DONE_KEY, None)
        st.rerun()
