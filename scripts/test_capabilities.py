"""담당 권한(capability)·알림 이메일 계약 테스트 — migration 010, sample 모드.

- capability 부여/회수 왕복, 미등록 코드 차단
- 이메일 소문자 정규화·(scope,email) 중복 접힘·형식/scope 검증
- 수신자 계산: 담당 보유자 × scope(ALL ∪ 해당 업무)
- config 예약어: ALL 은 capability 로 등록 불가

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_capabilities.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

from streamlit.testing.v1 import AppTest  # noqa: E402

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS
    if cond:
        PASS += 1
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name}" + (f" :: {detail}" if detail else ""))


def _probe():
    import streamlit as st
    from modules import config, db

    out = {}
    # 1) capability 왕복 + 회수
    db.set_user_capabilities("1001", ["LODGING_OFFICER", "WORK_REQUEST_OFFICER"])
    out["caps_set"] = db.get_user_capabilities("1001")
    out["has"] = db.has_capability("1001", "LODGING_OFFICER")
    db.set_user_capabilities("1001", ["WORK_REQUEST_OFFICER"])
    out["caps_revoked"] = db.get_user_capabilities("1001")
    # 2) 미등록 코드 차단
    try:
        db.set_user_capabilities("1001", ["NOPE_OFFICER"])
        out["bad_cap"] = "허용됨(결함)"
    except ValueError as exc:
        out["bad_cap"] = str(exc)
    # 3) 이메일 정규화·중복·검증
    db.set_user_emails("1001", [
        {"email": "A@X.com", "scope": "ALL"},
        {"email": "a@x.com", "scope": "ALL"},            # 대소문자 중복 → 1건
        {"email": "b@x.com", "scope": "WORK_REQUEST_OFFICER"},
        {"email": "", "scope": "ALL"},                    # 빈 행 skip
    ])
    out["emails"] = db.get_user_emails("1001")
    try:
        db.set_user_emails("1001", [{"email": "notanemail", "scope": "ALL"}])
        out["bad_email"] = "허용됨(결함)"
    except ValueError as exc:
        out["bad_email"] = str(exc)
    try:
        db.set_user_emails("1001", [{"email": "a@x.com", "scope": "NOPE"}])
        out["bad_scope"] = "허용됨(결함)"
    except ValueError as exc:
        out["bad_scope"] = str(exc)
    # 4) 수신자 계산 — 담당 보유자 × scope
    db.set_user_capabilities("1002", ["LODGING_OFFICER"])
    db.set_user_emails("1002", [
        {"email": "mgr@x.com", "scope": "ALL"},
        {"email": "lodge@x.com", "scope": "LODGING_OFFICER"},
        {"email": "wr-only@x.com", "scope": "WORK_REQUEST_OFFICER"},  # 미보유 업무 scope
    ])
    out["rcpt_lodging"] = db.notification_recipients("LODGING_OFFICER")
    out["rcpt_wr"] = db.notification_recipients("WORK_REQUEST_OFFICER")
    out["ready"] = db.capabilities_ready()
    out["reserved"] = config.EMAIL_SCOPE_ALL not in config.CAPABILITIES
    st.session_state["_cap_out"] = out


def main() -> None:
    at = AppTest.from_function(_probe, default_timeout=60).run()
    check("probe 예외 없음", not at.exception, str(at.exception))
    o = at.session_state["_cap_out"] if "_cap_out" in at.session_state else {}
    check("capability 부여 왕복", o.get("caps_set") == ["LODGING_OFFICER", "WORK_REQUEST_OFFICER"])
    check("has_capability 판정", o.get("has") is True)
    check("회수 = 행 삭제(잔존 없음)", o.get("caps_revoked") == ["WORK_REQUEST_OFFICER"])
    check("미등록 capability 차단", "알 수 없는 담당 코드" in str(o.get("bad_cap")))
    check("이메일 소문자 정규화 + 대소문자 중복 접힘",
          o.get("emails") == [
              {"email": "a@x.com", "scope": "ALL"},
              {"email": "b@x.com", "scope": "WORK_REQUEST_OFFICER"},
          ], str(o.get("emails")))
    check("이메일 형식 차단", "형식" in str(o.get("bad_email")))
    check("미등록 scope 차단", "수신 범위" in str(o.get("bad_scope")))
    check("수신자: 담당 보유자의 ALL+해당업무만",
          o.get("rcpt_lodging") == ["lodge@x.com", "mgr@x.com"], str(o.get("rcpt_lodging")))
    check("수신자: 담당 없는 업무는 미보유 scope 미포함",
          o.get("rcpt_wr") == ["a@x.com", "b@x.com"] or o.get("rcpt_wr") == ["b@x.com"],
          str(o.get("rcpt_wr")))
    check("sample capabilities_ready=True", o.get("ready") is True)
    check("ALL 예약어는 capability 아님", o.get("reserved") is True)

    print()
    if FAIL:
        print(f"FAILED {len(FAIL)}: {FAIL}")
        sys.exit(1)
    print(f"ALL PASSED ({PASS} checks)")


if __name__ == "__main__":
    main()
