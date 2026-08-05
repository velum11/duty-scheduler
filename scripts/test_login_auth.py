"""로그인 사번 정규화 회귀 테스트 (sample).

정책: 사번 조회는 trim + 대소문자 무시(casefold). 정규화는 비교에만 쓰고
DB emp_no 원본은 불변. 세션/토큰에는 정규 emp_no 저장. Enter/버튼 단일 경로.

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_login_auth.py
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

import pandas as pd  # noqa: E402

from modules import auth, db  # noqa: E402

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name}")


# 1) 실제 sample 데이터: 숫자 사번 trim 매칭, USER/MANAGER 회귀
u1001 = db.find_user_by_emp_no(" 1001 ")
check("숫자 사번 ' 1001 ' trim 매칭", u1001 is not None and str(u1001["emp_no"]) == "1001")
check("1001 은 ADMIN 권한", bool(u1001) and u1001.get("role") == "ADMIN")
u1002 = db.find_user_by_emp_no("1002")
check("1002 MANAGER 회귀", bool(u1002) and u1002.get("role") == "MANAGER")
u1003 = db.find_user_by_emp_no("1003")
check("1003 USER 회귀", bool(u1003) and u1003.get("role") == "USER")
check("미존재 사번 None", db.find_user_by_emp_no("999999") is None)

# 2) 영문 사번 대소문자 무시 + trim (get_users 를 통제된 df 로 대체)
fake = pd.DataFrame(
    [
        {"emp_no": "ADMIN", "name": "관리자", "dept_code": "D1", "team_code": "",
         "position": "팀장", "role": "ADMIN", "is_active": True},
        {"emp_no": "1001", "name": "김관리", "dept_code": "D1", "team_code": "T1",
         "position": "파트장", "role": "ADMIN", "is_active": True},
    ]
)
orig = db.get_users
db.get_users = lambda *a, **k: fake  # type: ignore[assignment]
try:
    for q in ["ADMIN", "admin", "Admin", "  aDmIn  "]:
        r = db.find_user_by_emp_no(q)
        check(f"'{q}' -> 동일 ADMIN 사용자", bool(r) and r["emp_no"] == "ADMIN")
    # 원본 emp_no 는 대문자 그대로 (정규화가 저장값을 바꾸지 않음)
    r = db.find_user_by_emp_no("admin")
    check("매칭 결과의 원본 emp_no 는 'ADMIN' 유지", bool(r) and r["emp_no"] == "ADMIN")
    check("존재하지 않는 영문 사번 None", db.find_user_by_emp_no("root") is None)
finally:
    db.get_users = orig  # type: ignore[assignment]

# 2-b) 대소문자만 다른 중복 사번: 비활성 admin + 활성 ADMIN → 활성 우선 선택
dup = pd.DataFrame(
    [
        {"emp_no": "admin", "name": "구관리(비활성)", "dept_code": "D1", "team_code": "",
         "position": "팀장", "role": "ADMIN", "is_active": False},
        {"emp_no": "ADMIN", "name": "관리자", "dept_code": "D1", "team_code": "",
         "position": "팀장", "role": "ADMIN", "is_active": True},
    ]
)
db.get_users = lambda *a, **k: dup  # type: ignore[assignment]
try:
    for q in ["admin", "ADMIN", "  Admin  "]:
        r = db.find_user_by_emp_no(q)
        check(f"중복 사번 '{q}' -> 활성 사용자(ADMIN) 선택",
              bool(r) and r["emp_no"] == "ADMIN" and r["is_active"] is True)
finally:
    db.get_users = orig  # type: ignore[assignment]

# 3) auth.login 계약 (정적): trim, 단일 조회, 정규 emp_no 토큰
lsrc = inspect.getsource(auth.login)
check("auth.login: 입력 trim", ".strip()" in lsrc)
check("auth.login: find_user_by_emp_no 단일 호출", lsrc.count("db.find_user_by_emp_no(") == 1)
check("auth.login: 토큰에 정규 emp_no(user) 사용", 'user.get("emp_no"' in lsrc)
check("auth.login: 실패 시 오류 메시지 반환", "_BAD_CREDENTIALS" in lsrc)
# 사용자 열거 방지: "사번이 없다"와 "비번이 틀렸다"를 구분해 알려주면 유효 사번을 캐낼 수
# 있으므로, 두 경로 모두 같은 문구(_BAD_CREDENTIALS)를 돌려준다.
check("auth.login: 미등록 사번과 비번 오류를 같은 문구로 응답(사용자 열거 방지)",
      "등록되지 않은 사번" not in lsrc
      and lsrc.count("_BAD_CREDENTIALS") >= 2
      and "_BAD_CREDENTIALS" in inspect.getsource(auth._register_failure))

# 4) login 화면: Enter/버튼 동일 단일 폼 경로
login_src = (ROOT / "views" / "login.py").read_text(encoding="utf-8")
check("login: 단일 st.form", login_src.count("st.form(") == 1)
check("login: form_submit_button(Enter=버튼 동일 제출)", "form_submit_button" in login_src)
check("login: auth.login 단일 경로", login_src.count("auth.login(") == 1)
check("login: 성공 시 rerun 전환", "st.rerun()" in login_src)

# 5) logout: 화면별 조회조건(q_*) 삭제로 stale 권한범위가 로그인 간 잔존하지 않음
import streamlit as st  # noqa: E402

st.session_state["user"] = {"emp_no": "1001", "role": "ADMIN"}
st.session_state["auth_token"] = "tkn-x"
st.session_state["nav_page"] = "schedule_view"
st.session_state["q_schedule_view"] = {"dept": "(전체)", "team": "(전체)",
                                       "year": 2026, "month": 7, "keyword": ""}
st.session_state["q_schedule_edit"] = {"dept": "PET1", "team": "A"}
st.session_state["keep_me"] = "preserve"  # 비-q 키는 보존
auth.logout()
check("logout: user 삭제", "user" not in st.session_state)
check("logout: auth_token 삭제", "auth_token" not in st.session_state)
check("logout: nav_page 삭제", "nav_page" not in st.session_state)
check("logout: q_schedule_view(조회조건) 삭제", "q_schedule_view" not in st.session_state)
check("logout: q_schedule_edit(조회조건) 삭제", "q_schedule_edit" not in st.session_state)
check("logout: 무관 세션키는 보존", st.session_state.get("keep_me") == "preserve")
check("logout 소스: q_ 접두 세션키 정리", 'startswith("q_")' in inspect.getsource(auth.logout))

print(f"\n{PASS} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
