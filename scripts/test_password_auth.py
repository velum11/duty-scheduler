"""비밀번호 인증 계약 테스트 (sample, migration 008).

정책: 초기 비밀번호 = 사번, 최초 로그인 시 변경 강제, 초기 비번 유효기간,
연속 실패 잠금, 비번 변경 시 기존 세션 폐기, 스키마 미적용 시 fail-closed.

원격 DB 를 건드리지 않는다 — sample 모드에서 세션 상태 저장소로 동작을 검증한다.

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_password_auth.py
"""
from __future__ import annotations

import inspect
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

import streamlit as st  # noqa: E402

from modules import auth, config, db, passwords  # noqa: E402

# 베타 한시 스위치는 기본이 켜져 있어 강제변경 게이트를 끈다(사용자 지시 2026-08-13).
# 이 테스트 본문은 **정책 원형**(강제변경 포함)을 검증하므로 잠시 끄고, 마지막
# 섹션(8)에서 스위치 동작 자체를 검증한 뒤 원래 값으로 되돌린다.
_ORIG_BETA_SKIP = config.BETA_SKIP_FORCED_PASSWORD_CHANGE
config.BETA_SKIP_FORCED_PASSWORD_CHANGE = False

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


def reset_state() -> None:
    """로그인 세션만 비운다(로그아웃 상태로 되돌림).

    sample 모드에서 자격증명 저장소도 st.session_state 에 살기 때문에, 전체를 비우면
    DB 를 통째로 지우는 셈이 되어 "비번 변경 후 재로그인" 같은 검증이 성립하지 않는다.
    """
    for key in ("user", "auth_token", "nav_page", "must_change_password"):
        st.session_state.pop(key, None)


# =========================================================================
# 1) passwords: 해싱·검증·정책 (순수 함수)
# =========================================================================
h = passwords.hash_password("abcd1234")
check("hash: 자기서술 형식(scrypt$n$r$p$salt$hash)",
      h.split("$")[0] == "scrypt" and len(h.split("$")) == 6)
check("hash: 같은 평문도 매번 다른 해시(salt 무작위)",
      passwords.hash_password("abcd1234") != h)
check("verify: 정답 통과", passwords.verify_password("abcd1234", h) is True)
check("verify: 오답 거부", passwords.verify_password("abcd1235", h) is False)
check("verify: 손상된 저장값은 예외 대신 False(fail-closed)",
      passwords.verify_password("x", "garbage") is False
      and passwords.verify_password("x", "") is False
      and passwords.verify_password("x", None) is False)
check("verify: 조작된 과대 파라미터 거부(메모리 고갈 차단)",
      passwords.verify_password("abcd1234", "scrypt$99999999$8$1$AAAA$AAAA") is False)
check("needs_rehash: 현재 기본값 해시는 재해싱 불필요", passwords.needs_rehash(h) is False)

check("policy: 최소 길이 미만 거부",
      passwords.validate_new_password("abc1234") is not None)
check("policy: 사번과 동일한 값 거부",
      passwords.validate_new_password("10011001", "10011001") is not None)
check("policy: 사번과 대소문자만 다른 값도 거부",
      passwords.validate_new_password("adminadmin", "AdminAdmin") is not None)
check("policy: 앞뒤 공백 거부(조용한 trim 으로 저장값이 어긋나는 것 방지)",
      passwords.validate_new_password(" abcd1234 ") is not None)
check("policy: 정상 통과", passwords.validate_new_password("abcd1234", "1001") is None)
check("초기비번: 사번과 trim+대소문자 무시 비교",
      passwords.matches_employee_number(" 1001 ", "1001") is True
      and passwords.matches_employee_number("1002", "1001") is False)

# =========================================================================
# 2) 자격증명이 일반 사용자 조회 계약(USER_COLUMNS)에 새지 않는다
# =========================================================================
users_df = db.get_users()
leaked = [c for c in users_df.columns
          if c in ("password_hash", "password_set_at", "must_change_password",
                   "failed_login_count", "locked_until")]
check("계약: get_users DataFrame 에 자격증명 컬럼이 없다", leaked == [])

# =========================================================================
# 3) login: 초기 비밀번호(=사번) 경로와 강제변경 플래그
# =========================================================================
reset_state()
user, err = auth.login("1001", "1001")
check("login: 초기 비밀번호(사번)로 로그인 성공", user is not None and err is None)
check("login: 성공 직후 강제변경 플래그가 선다",
      auth.needs_password_change() is True)

reset_state()
user, err = auth.login("1001", "wrongpass")
check("login: 틀린 비밀번호 거부", user is None and err is not None)

reset_state()
user, err = auth.login("1001", "")
check("login: 빈 비밀번호 거부", user is None and "비밀번호" in str(err))

reset_state()
_, err_missing = auth.login("nosuchemp", "whatever")
reset_state()
_, err_wrong = auth.login("1001", "wrongpass")
check("login: 미등록 사번과 틀린 비번의 응답 문구가 동일(사용자 열거 방지)",
      err_missing == err_wrong)

# =========================================================================
# 4) 초기 비밀번호 유효기간
# =========================================================================
reset_state()
db.get_user_credential("1001")  # sample 저장소에 기본 레코드 생성
past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
db._sample_update_credential("1001", {"initial_password_expires_at": past})
user, err = auth.login("1001", "1001")
check("초기비번 만료: 기간이 지나면 사번 로그인 거부",
      user is None and "초기 비밀번호" in str(err))

# =========================================================================
# 5) 연속 실패 잠금
# =========================================================================
reset_state()
db.get_user_credential("1002")
for _ in range(config.LOGIN_MAX_FAILURES):
    auth.login("1002", "definitely-wrong")
user, err = auth.login("1002", "1002")   # 올바른 초기 비번이어도 잠겨 있어야 한다
check(f"잠금: {config.LOGIN_MAX_FAILURES}회 실패 후 올바른 비번도 거부",
      user is None and "잠" in str(err))

cred = db.get_user_credential("1002")
check("잠금: locked_until 이 기록된다", bool(cred.get("locked_until")))

# =========================================================================
# 6) change_password: 정책·현재비번 확인·강제변경 해제
# =========================================================================
reset_state()
auth.login("1003", "1003")
ok, err = auth.change_password("wrong-current", "abcd1234", "abcd1234")
check("변경: 현재 비밀번호가 틀리면 거부", ok is False and "현재 비밀번호" in str(err))

ok, err = auth.change_password("1003", "abcd1234", "abcd9999")
check("변경: 새 비밀번호 확인값 불일치 거부", ok is False and "일치" in str(err))

ok, err = auth.change_password("1003", "1003", "1003")
check("변경: 사번과 같은 새 비밀번호 거부", ok is False and err is not None)

ok, err = auth.change_password("1003", "abcd1234", "abcd1234")
check("변경: 정상 변경 성공", ok is True and err is None)
check("변경: 강제변경 플래그 해제", auth.needs_password_change() is False)

cred = db.get_user_credential("1003")
check("변경: 해시가 저장되고 평문이 남지 않는다",
      bool(cred.get("password_hash")) and "abcd1234" not in str(cred.get("password_hash")))
check("변경: must_change_password 가 꺼진다",
      cred.get("must_change_password") is False)

reset_state()
user, err = auth.login("1003", "abcd1234")
check("변경 후: 새 비밀번호로 로그인 성공", user is not None and err is None)
check("변경 후: 더 이상 강제변경이 걸리지 않는다",
      auth.needs_password_change() is False)

reset_state()
user, err = auth.login("1003", "1003")
check("변경 후: 예전 초기 비밀번호(사번)는 거부", user is None)

# =========================================================================
# 6b) 한시적 고정 비밀번호 예외 (사용자 지시 2026-08-05)
#     config.FIXED_PASSWORD_ACCOUNTS 가 단일 SoT 여야 한다 — 비우면 예외가 전부 사라진다.
# =========================================================================
orig_fixed = dict(config.FIXED_PASSWORD_ACCOUNTS)
try:
    # sample 사번 1001(ADMIN 역할)을 예외로 등재해 동작을 검증한다.
    config.FIXED_PASSWORD_ACCOUNTS.clear()
    config.FIXED_PASSWORD_ACCOUNTS["1001"] = "FIXEDPW"

    reset_state()
    user, err = auth.login("1001", "FIXEDPW")
    check("고정예외: 고정 비밀번호로 로그인 성공", user is not None and err is None)
    check("고정예외: 강제변경이 걸리지 않는다", auth.needs_password_change() is False)

    ok, err = auth.change_password("FIXEDPW", "abcd1234", "abcd1234")
    check("고정예외: 비밀번호 변경 거부", ok is False and "고정" in str(err))

    reset_state()
    user, err = auth.login("1001", "1001")
    check("고정예외: 초기 비번(사번)은 더 이상 통하지 않는다", user is None)

    # 정확 일치 계약: 대소문자만 다른 사번은 예외에 걸리지 않는다.
    # (실 DB 에 'ADMIN' 활성 / 'admin' 비활성이 공존하므로 casefold 매칭은 위험하다.)
    # 고정 예외는 스키마 게이트보다 앞에 있어야 한다 — 008 미적용 환경에서도 지정
    # 관리자가 들어올 수 있게 하는 것이 이 예외의 목적이다.
    login_body = inspect.getsource(auth.login)
    check("고정예외: 스키마 fail-closed 게이트보다 앞에서 판정한다",
          login_body.index("fixed_password_for(") < login_body.index("password_auth_ready()"))
    check("고정예외: 자격증명 컬럼을 읽지 않는 경로",
          login_body.index("fixed_password_for(") < login_body.index("get_user_credential("))

    check("고정예외: 정확 일치 — 대소문자 다른 사번은 예외 아님",
          auth.fixed_password_for("1001") == "FIXEDPW"
          and auth.fixed_password_for("1002") is None)
    config.FIXED_PASSWORD_ACCOUNTS.clear()
    config.FIXED_PASSWORD_ACCOUNTS["ADMIN"] = "ADMIN"
    check("고정예외: 'ADMIN' 등재 시 'admin' 은 예외에서 제외",
          auth.fixed_password_for("ADMIN") == "ADMIN"
          and auth.fixed_password_for("admin") is None)

    # 예외를 비우면 흔적 없이 일반 정책으로 복귀해야 한다(제거 가능성 검증).
    config.FIXED_PASSWORD_ACCOUNTS.clear()
    check("고정예외: dict 를 비우면 예외가 사라진다",
          auth.fixed_password_for("1001") is None
          and auth.fixed_password_for("ADMIN") is None)
    reset_state()
    # 4) 에서 1001 의 초기비번 만료를 과거로 세팅했으므로 되돌린다(픽스처 격리).
    db._sample_update_credential("1001", {"initial_password_expires_at": None})
    user, err = auth.login("1001", "1001")
    check("고정예외 해제 후: 초기 비번(사번) 경로가 되살아난다",
          user is not None and auth.needs_password_change() is True)
finally:
    config.FIXED_PASSWORD_ACCOUNTS.clear()
    config.FIXED_PASSWORD_ACCOUNTS.update(orig_fixed)

check("고정예외: 베타 오픈에 맞춰 등재가 비어 있다(일반 정책 복귀, 2026-08-13)",
      config.FIXED_PASSWORD_ACCOUNTS == {})

# =========================================================================
# 7) 정적 계약: fail-closed·게이트 배치·세션 해시 저장
# =========================================================================
login_src = inspect.getsource(auth.login)
check("fail-closed: 스키마 미적용이면 로그인을 거부한다",
      "password_auth_ready()" in login_src and "not db.password_auth_ready()" in login_src)

app_src = (ROOT / "app.py").read_text(encoding="utf-8")
gate_pos = app_src.find("needs_password_change()")
shell_pos = app_src.find("app_shell(user)")
check("게이트: 강제변경 확인이 app_shell(네비게이션)보다 앞에 있다",
      gate_pos != -1 and shell_pos != -1 and gate_pos < shell_pos)

auth_src = (ROOT / "modules" / "auth.py").read_text(encoding="utf-8")
check("세션: DB 에 원문 토큰이 아니라 sha256 해시를 저장한다",
      "_token_hash" in auth_src and "hashlib.sha256" in auth_src)
check("세션: 비번 변경 시 기존 세션을 폐기한다",
      "revoke_user_sessions" in inspect.getsource(auth.change_password))
check("자동로그인: 쿠키 경로도 강제변경 게이트를 받는다",
      "_must_change_for" in inspect.getsource(auth.get_current_user))

reset_src = inspect.getsource(db.reset_user_password)
check("초기화: ADMIN 초기화는 해시를 지우고 강제변경을 켠다",
      '"password_hash": None' in reset_src and '"must_change_password": True' in reset_src)

mu_src = (ROOT / "views" / "master_users.py").read_text(encoding="utf-8")
check("초기화 UI: ADMIN 에게만 노출된다", "auth.is_admin(user)" in mu_src)
check("초기화 UI: 초기화 시 세션도 폐기한다", "revoke_user_sessions" in mu_src)

# =========================================================================
# 8) 베타 한시 스위치 — 강제변경 라우팅 게이트만 끈다(로그인 검증·잠금은 그대로)
# =========================================================================
reset_state()
db._sample_update_credential("1001", {"initial_password_expires_at": None})
config.BETA_SKIP_FORCED_PASSWORD_CHANGE = True

user, err = auth.login("1001", "1001")
check("베타 스위치: 초기 비번(사번) 로그인은 그대로 성공", user is not None and err is None)
check("베타 스위치: 강제변경 게이트가 꺼진다", auth.needs_password_change() is False)
check("베타 스위치: 세션 판정(must_change)은 보존된다",
      st.session_state.get("must_change_password") is True)

reset_state()
user, err = auth.login("1001", "wrongpass")
check("베타 스위치: 틀린 비밀번호는 여전히 거부", user is None and err is not None)

config.BETA_SKIP_FORCED_PASSWORD_CHANGE = False
reset_state()
auth.login("1001", "1001")
check("베타 스위치: 끄면 강제변경이 즉시 복원된다", auth.needs_password_change() is True)
config.BETA_SKIP_FORCED_PASSWORD_CHANGE = _ORIG_BETA_SKIP

print(f"\n{PASS} passed, {len(FAIL)} failed")
for name in FAIL:
    print(f"  - {name}")
sys.exit(1 if FAIL else 0)
