"""신규 화면 프로토타입 미리보기 실행기(숙소 예약 · 업무요청서) — 단독 Streamlit 엔트리.

``app.py`` 를 건드리지 않고 신규 화면만 살펴보기 위한 **임시 실행기**다. 로그인 게이트
없이 가상 사용자(ADMIN/MANAGER/USER)를 골라 각 화면의 권한별 동작을 확인한다. 실데이터·
원격(Supabase) 접근은 하지 않으며, 데이터는 ``data/sample/*.csv`` 시드 +
``.orca/artifacts/new-screens/state/*.json`` 런타임 파일이 전부다.

실행::

    DUTY_DATA_MODE=sample .venv/Scripts/streamlit.exe run scripts/preview_new_screens.py \
        --server.port 8503 --server.headless true

(포트 배치: 8501=본 앱 supabase, 8502=본 앱 sample, 8503=신규 화면 미리보기.)

라우팅(``app.py``·``modules/nav.py``)·권한 gating·DB 연결은 후속 통합 작업 소관이며 이
파일은 통합 시 제거하거나 개발 전용으로 남긴다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 이 실행기는 항상 로컬 sample 모드다(원격 접근 방지) — modules import 전에 고정한다.
os.environ.setdefault("DUTY_DATA_MODE", "sample")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from modules import proto_store, ui  # noqa: E402

# 페이지 설정 + 공통 CSS 를 위젯보다 먼저 적용한다(app.py 와 동일 순서).
ui.setup_page()

from views import (  # noqa: E402
    lodging_calendar, lodging_manage, lodging_my, lodging_request,
    work_request_handle, work_request_my, work_request_submit,
)

# ── 가상 사용자(전부 허구 — 실직원 정보 없음) ──────────────────────────────
DEMO_USERS = {
    "USER · 김샘플(2024TEST01)": {
        "emp_no": "2024TEST01", "name": "김샘플", "role": "USER", "dept_code": "PET1",
    },
    "MANAGER · 한매니저(2024TEST50)": {
        "emp_no": "2024TEST50", "name": "한매니저", "role": "MANAGER", "dept_code": "MGT",
    },
    "ADMIN · 조관리(2024TEST90)": {
        "emp_no": "2024TEST90", "name": "조관리", "role": "ADMIN", "dept_code": "MGT",
    },
}

SCREENS = {
    "숙소 예약 · 예약 신청": lodging_request,
    "숙소 예약 · 내 숙소 예약": lodging_my,
    "숙소 예약 · 승인 관리": lodging_manage,
    "숙소 예약 · 예약 캘린더": lodging_calendar,
    "업무요청 · 업무요청 등록": work_request_submit,
    "업무요청 · 내 업무요청": work_request_my,
    "업무요청 · 업무요청 처리": work_request_handle,
}

DATASETS = ["lodgings", "lodging_reservations", "work_requests"]

# 사용자·화면 전환 시 지워야 하는 화면 상태 접두사(선택·펼침·의견 입력 등).
_VOLATILE_PREFIXES = (
    "lc_", "lm_", "lmy_", "wrm_", "wrh_", "lr_", "wr_f_", "wr_submit_done",
    "lodging_calendar_", "lodging_manage_", "lodging_my_",
    "work_request_my_", "work_request_handle_",
)


def _reset_screen_state() -> None:
    for key in [k for k in st.session_state
                if isinstance(k, str) and k.startswith(_VOLATILE_PREFIXES)]:
        st.session_state.pop(key, None)


def _apply_query_params() -> None:
    """``?user=0&screen=2`` 로 초기 선택을 지정한다(세션 최초 1회).

    스크린샷·QA 가 클릭 없이 특정 화면을 바로 열 수 있게 하는 진입 훅이다. 이후에는
    사이드바 선택이 우선한다(쿼리 파라미터는 재적용하지 않는다).
    """
    if st.session_state.get("pv_qp_applied"):
        return
    st.session_state["pv_qp_applied"] = True
    params = st.query_params

    def _pick(raw, options):
        text = str(raw or "").strip()
        if not text:
            return None
        if text.isdigit() and int(text) < len(options):
            return options[int(text)]
        return next((o for o in options if text in o), None)

    user = _pick(params.get("user"), list(DEMO_USERS))
    if user:
        st.session_state["pv_user"] = user
        st.session_state["pv_user_prev"] = user
    screen = _pick(params.get("screen"), list(SCREENS))
    if screen:
        st.session_state["pv_screen"] = screen


def _sidebar() -> tuple[dict, object]:
    _apply_query_params()
    with st.sidebar:
        st.markdown("### 프로토타입 미리보기")
        st.caption("로그인 없이 가상 사용자로 신규 화면을 확인합니다. 실데이터 접근 없음.")

        user_label = st.selectbox("가상 사용자", list(DEMO_USERS), key="pv_user")
        screen_label = st.selectbox("화면", list(SCREENS), key="pv_screen")

        if st.session_state.get("pv_user_prev") != user_label:
            st.session_state["pv_user_prev"] = user_label
            _reset_screen_state()

        st.divider()
        if st.button("샘플 데이터로 초기화", width="stretch", icon=":material/restart_alt:"):
            proto_store.reset_all(DATASETS)
            _reset_screen_state()
            st.rerun()
        st.caption(f"런타임 상태: `{proto_store.state_dir()}`")

    return DEMO_USERS[user_label], SCREENS[screen_label]


def main() -> None:
    user, screen = _sidebar()
    st.caption(
        f"미리보기 · {user['role']} {user['name']}({user['emp_no']}) · "
        f"소속 {user['dept_code']} — 라우팅·DB 미연결 프로토타입"
    )
    screen.render(user)


main()
