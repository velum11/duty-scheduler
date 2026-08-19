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
    # 5) 목록 조회(bulk) == 단건 반복 — N+1 제거가 값을 바꾸지 않는다는 파사드 계약.
    #    미등록 사번도 포함해 '없는 사번은 빈 값'까지 같은지 본다(sample 계약).
    emps = ["1001", "1002", "NOSUCH"]
    out["bulk_caps"] = db.get_user_capabilities_bulk(emps)
    out["single_caps"] = {e: db.get_user_capabilities(e) for e in emps}
    out["bulk_emails"] = db.get_user_emails_bulk(emps)
    out["single_emails"] = {e: db.get_user_emails(e) for e in emps}
    out["bulk_empty"] = (db.get_user_capabilities_bulk([]) == {}
                         and db.get_user_emails_bulk([]) == {})
    out["bulk_norm"] = sorted(db.get_user_emails_bulk(["  1001 ", "1001", ""]))
    st.session_state["_cap_out"] = out



# ---------------------------------------------------------------------------
# 저장소 계층 bulk 조회 — 순수 mock(가짜 조회기). 실DB 미접속·쓰기 없음.
# in_() 인자는 URL 쿼리스트링이라 길면 한계에 걸린다 → IN_FILTER_CHUNK 단위 분할이
# 계약이다. 분할해도 (a) 결과가 정확히 합쳐지고 (b) 어느 청크에도 없는 사번이 조용히
# 사라지지 않고 미해석 오류로 잡히는지 고정한다(단건 _user_id_of 와 같은 실패 계약).
# ---------------------------------------------------------------------------
def test_bulk_chunking() -> None:
    from modules import supabase_repository as sr

    size = sr.IN_FILTER_CHUNK
    emps = [f"E{i:04d}" for i in range(size + 1)]          # 201 → 2 청크
    ids = {emp: 1000 + i for i, emp in enumerate(emps)}

    emp_chunks: list[list[str]] = []
    id_chunks: list[list[int]] = []

    def fake_user_maps(emp_nos=None):
        picked = [str(e).strip() for e in (emp_nos or [])]
        emp_chunks.append(picked)
        sub = {e: ids[e] for e in picked if e in ids}
        return sub, {str(v): k for k, v in sub.items()}

    class _Q:
        def in_(self, col, values):
            if col == "user_id":
                id_chunks.append(list(values))
            return self

        def order(self, *_a, **_k):
            return self

    def fake_select_all(table, columns="*", query_builder=None):
        q = _Q()
        if query_builder is not None:
            query_builder(q)
        picked = id_chunks[-1]
        if table == "user_emails":
            return [{"user_id": u, "email": f"u{u}@x.com", "scope": "ALL"} for u in picked]
        return [{"user_id": u, "capability": "LODGING_OFFICER"} for u in picked]

    saved = (sr._user_maps, sr._select_all, sr.capabilities_ready)
    try:
        sr._user_maps = fake_user_maps
        sr._select_all = fake_select_all
        sr.capabilities_ready = lambda: True

        got = sr.get_user_emails_bulk(emps)
        check(f"사번 해석이 {size} 단위로 분할된다",
              [len(c) for c in emp_chunks] == [size, 1], str([len(c) for c in emp_chunks]))
        check(f"user_id in_() 도 {size} 단위로 분할된다",
              [len(c) for c in id_chunks] == [size, 1], str([len(c) for c in id_chunks]))
        check("청크 결과가 누락 없이 합쳐진다(요청 사번 전건)", set(got) == set(emps))
        check("경계 넘어간 사번도 자기 주소를 받는다",
              got[emps[-1]] == [{"email": f"u{ids[emps[-1]]}@x.com", "scope": "ALL"}],
              str(got.get(emps[-1])))
        check("합쳐진 결과에 중복 행이 없다", all(len(v) == 1 for v in got.values()))

        id_chunks.clear()
        emp_chunks.clear()
        caps = sr.get_user_capabilities_bulk(emps)
        check("담당 bulk 도 같은 분할·병합 계약",
              len(caps) == len(emps) and caps[emps[-1]] == ["LODGING_OFFICER"])

        # 두 번째 청크에만 있는 미해석 사번 → 조용히 사라지지 않고 오류로 표면화
        id_chunks.clear()
        emp_chunks.clear()
        raised = ""
        try:
            sr.get_user_emails_bulk(emps + ["GHOST"])
        except sr.SupabaseDataError as exc:
            raised = str(exc)
        check("미해석 사번은 빈 값이 아니라 오류(단건과 같은 실패 계약)",
              "GHOST" in raised, raised or "예외 없음(결함)")
    finally:
        sr._user_maps, sr._select_all, sr.capabilities_ready = saved


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
    check("담당 bulk == 단건 반복(sample)",
          o.get("bulk_caps") == o.get("single_caps"), str(o.get("bulk_caps")))
    check("이메일 bulk == 단건 반복(sample)",
          o.get("bulk_emails") == o.get("single_emails"), str(o.get("bulk_emails")))
    check("빈 사번 목록은 조회하지 않고 빈 dict", o.get("bulk_empty") is True)
    check("사번 공백·중복·빈값 정규화(요청 사번 키만)",
          o.get("bulk_norm") == ["1001"], str(o.get("bulk_norm")))
    test_bulk_chunking()

    print()
    if FAIL:
        print(f"FAILED {len(FAIL)}: {FAIL}")
        sys.exit(1)
    print(f"ALL PASSED ({PASS} checks)")


if __name__ == "__main__":
    main()
