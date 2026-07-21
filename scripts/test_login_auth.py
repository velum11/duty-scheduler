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
check("auth.login: 실패 시 오류 메시지 반환", "등록되지 않은 사번" in lsrc)

# 4) login 화면: Enter/버튼 동일 단일 폼 경로
login_src = (ROOT / "views" / "login.py").read_text(encoding="utf-8")
check("login: 단일 st.form", login_src.count("st.form(") == 1)
check("login: form_submit_button(Enter=버튼 동일 제출)", "form_submit_button" in login_src)
check("login: auth.login 단일 경로", login_src.count("auth.login(") == 1)
check("login: 성공 시 rerun 전환", "st.rerun()" in login_src)

print(f"\n{PASS} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
