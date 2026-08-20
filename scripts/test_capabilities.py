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

    saved = (sr._user_maps, sr._select_all, sr.capabilities_ready, sr.capabilities_probe)
    try:
        sr._user_maps = fake_user_maps
        sr._select_all = fake_select_all
        sr.capabilities_ready = lambda: True
        # 준비 판정은 3-state probe 가 소유한다 — 스텁하지 않으면 실제 client 를 탄다.
        sr.capabilities_probe = lambda **_k: sr.READINESS_READY

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
        (sr._user_maps, sr._select_all, sr.capabilities_ready,
         sr.capabilities_probe) = saved


def test_single_read_id_resolution() -> None:
    """단건 담당·이메일의 사번→id 해석 경로 계약 (supabase 분기, 가짜 client — 무네트워크).

    조회는 캐시된 ``_user_maps`` 로 해석하고(같은 화면에서 사번당 users 왕복이 되살아나지
    않게), 쓰기는 저장 직전 권위 조회(``_user_id_of``)를 유지한다. 어느 쪽이든 해석되지
    않는 사번은 빈 값이 아니라 오류다.
    """
    from modules import supabase_repository as sr

    calls = {"user_maps": 0, "users_select": 0}

    def fake_user_maps(emp_nos=None):
        calls["user_maps"] += 1
        picked = [str(e).strip() for e in (emp_nos or [])]
        sub = {e: 7 for e in picked if e == "E1"}
        return sub, {str(v): k for k, v in sub.items()}

    def fake_select_all(table, columns="*", query_builder=None):
        if table == "users":
            calls["users_select"] += 1
            return [{"id": 7, "emp_no": "E1"}]
        if table == "user_emails":
            return [{"email": "a@x.com", "scope": "ALL"}]
        if table == "user_capabilities":
            return [{"capability": "LODGING_OFFICER"}]
        return []

    class _Chain:
        def __getattr__(self, _name):
            return lambda *_a, **_k: self

    class _Client:
        def table(self, _name):
            return _Chain()

    saved = (sr._user_maps, sr._select_all, sr.capabilities_ready, sr._execute, sr.client,
             sr.capabilities_probe)
    try:
        sr._user_maps = fake_user_maps
        sr._select_all = fake_select_all
        sr.capabilities_ready = lambda: True
        sr.capabilities_probe = lambda **_k: sr.READINESS_READY
        sr._execute = lambda *_a, **_k: type("R", (), {"data": []})()
        sr.client = _Client

        # 조회 2건: 매핑은 _user_maps 로만 해석하고 users 를 따로 왕복하지 않는다.
        emails = sr.get_user_emails("E1")
        caps = sr.get_user_capabilities("E1")
        check("단건 이메일 조회 값 유지", emails == [{"email": "a@x.com", "scope": "ALL"}], str(emails))
        check("단건 담당 조회 값 유지", caps == ["LODGING_OFFICER"], str(caps))
        check("조회 경로는 users 를 따로 조회하지 않는다(매핑 캐시 재사용)",
              calls["users_select"] == 0, f"users_select={calls['users_select']}")
        check("조회 경로는 _user_maps 로 해석한다", calls["user_maps"] == 2,
              f"user_maps={calls['user_maps']}")

        # 미해석 사번: 빈 값으로 위조하지 않고 단건과 같은 실패 계약.
        for name, fn in (("이메일", sr.get_user_emails), ("담당", sr.get_user_capabilities)):
            raised = ""
            try:
                fn("GHOST")
            except sr.SupabaseDataError as exc:
                raised = str(exc)
            check(f"미해석 사번 단건 {name} 조회는 오류(빈 값 아님)",
                  "GHOST" in raised, raised or "예외 없음(결함)")

        # 쓰기는 저장 직전 권위 조회를 유지한다(캐시된 매핑으로 남의 행을 건드리지 않음).
        calls["users_select"] = 0
        sr.set_user_emails("E1", [{"email": "a@x.com", "scope": "ALL"}])
        check("이메일 저장은 권위 users 조회로 id 해석", calls["users_select"] == 1,
              f"users_select={calls['users_select']}")
        calls["users_select"] = 0
        sr.set_user_capabilities("E1", ["LODGING_OFFICER"])
        check("담당 저장은 권위 users 조회로 id 해석", calls["users_select"] == 1,
              f"users_select={calls['users_select']}")
    finally:
        (sr._user_maps, sr._select_all, sr.capabilities_ready,
         sr._execute, sr.client, sr.capabilities_probe) = saved


# ---------------------------------------------------------------------------
# 담당 권한 저장소 준비 판정 3-state — 순수 mock(가짜 client). 실DB 미접속·쓰기 없음.
#
# 왜 3-state 인가: 이 판정이 숙소 예약 승인 인가의 입력이다(승인권자 = 담당자만, role
# 우회 없음). 종전처럼 **어떤 예외든 False 로 캐시**하면 일시 장애 한 번에 프로세스
# 수명 동안 전 담당자가 조용히 승인 권한을 잃는다("권한 없음"과 "확인 불가"가
# 구분되지 않는 fail-silent). 아래가 그 구분을 고정한다.
# ---------------------------------------------------------------------------
def _fake_client(error, counter):
    class _Chain:
        def select(self, *_a, **_k):
            return self

        def limit(self, *_a, **_k):
            return self

        def execute(self):
            counter["probes"] += 1
            if error is not None:
                raise error
            return type("R", (), {"data": []})()

    class _Client:
        def table(self, _name):
            return _Chain()

    return lambda: _Client()


def test_capabilities_probe_states() -> None:
    from modules import supabase_repository as sr

    saved = (sr.client, sr._user_maps, sr._select_all)
    counter = {"probes": 0}
    try:
        sr._user_maps = lambda emp_nos=None: ({"1001": 1}, {"1": "1001"})
        sr._select_all = lambda *a, **k: []

        # (1) 미준비(undefined table) — 안정적으로 캐시하고, 조회는 빈 값·저장은 오류.
        sr.reset_capabilities_readiness()
        sr.client = _fake_client(
            Exception('relation "public.user_capabilities" does not exist'), counter)
        check("미준비는 NOT_READY", sr.capabilities_probe() == sr.READINESS_NOT_READY)
        check("미준비면 ready=False", sr.capabilities_ready() is False)
        before = counter["probes"]
        sr.capabilities_probe()
        check("NOT_READY 는 캐시된다(재프로브 없음)", counter["probes"] == before)
        check("미준비 조회는 빈 목록", sr.get_user_capabilities("1001") == []
              and sr.get_user_emails("1001") == [])
        check("미준비 수신자 계산도 빈 목록", sr.notification_recipients("LODGING_OFFICER") == [])
        raised = ""
        try:
            sr.set_user_capabilities("1001", ["LODGING_OFFICER"])
        except sr.SupabaseDataError as exc:
            raised = str(exc)
        check("미준비 저장은 준비 안내 오류", "준비되지 않아" in raised, raised or "예외 없음(결함)")

        # (2) 확인 불가(일시 장애) — 캐시하지 않고, 조회·저장 모두 오류(빈 값 위조 금지).
        sr.reset_capabilities_readiness()
        sr.client = _fake_client(Exception("ConnectionResetError(10054)"), counter)
        check("일시 장애는 PROBE_ERROR", sr.capabilities_probe() == sr.READINESS_PROBE_ERROR)
        before = counter["probes"]
        sr.capabilities_probe()
        check("PROBE_ERROR 는 캐시하지 않는다(다음 호출에서 재프로브)",
              counter["probes"] > before)
        for label, call in (
            ("담당 조회", lambda: sr.get_user_capabilities("1001")),
            ("이메일 조회", lambda: sr.get_user_emails("1001")),
            ("수신자 계산", lambda: sr.notification_recipients("LODGING_OFFICER")),
            ("담당 저장", lambda: sr.set_user_capabilities("1001", [])),
        ):
            raised = ""
            try:
                call()
            except sr.SupabaseDataError as exc:
                raised = str(exc)
            check(f"확인 불가 상태의 {label}는 오류(빈 값·성공 위조 금지)",
                  "확인하지 못했습니다" in raised, raised or "예외 없음(결함)")
        check("확인 불가에서도 ready=False(권한은 fail-closed)",
              sr.capabilities_ready() is False)

        # (3) 장애가 풀리면 READY 로 갱신된다(고착 없음).
        sr.client = _fake_client(None, counter)
        check("장애 해소 후 READY 로 회복", sr.capabilities_probe() == sr.READINESS_READY)
        check("회복 후 ready=True", sr.capabilities_ready() is True)
    finally:
        sr.client, sr._user_maps, sr._select_all = saved
        sr.reset_capabilities_readiness()


# ---------------------------------------------------------------------------
# 숙소 예약 저장소 준비 판정도 같은 3-state 계약을 쓴다(쓰기 fail-closed, 조회 허용).
# ---------------------------------------------------------------------------
def test_lodging_readiness_states() -> None:
    from modules import supabase_repository as sr

    saved = (sr.client, sr._select_all)
    counter = {"probes": 0}
    try:
        sr._select_all = lambda *a, **k: []
        sr.reset_lodging_readiness()
        sr.client = _fake_client(
            Exception("Could not find the table 'public.lodgings' in the schema cache"),
            counter)
        check("숙소 저장소 미적용은 NOT_READY",
              sr.lodging_extensions_probe() == sr.READINESS_NOT_READY)
        check("미준비 조회는 빈 목록(화면은 계속 뜬다)",
              sr.get_lodgings() == [] and sr.get_lodging_reservations() == [])
        raised = ""
        try:
            sr.require_lodging(for_write=True)
        except sr.SupabaseDataError as exc:
            raised = str(exc)
        check("미준비 쓰기는 차단", "준비되지 않아" in raised, raised or "예외 없음(결함)")

        sr.reset_lodging_readiness()
        sr.client = _fake_client(Exception("ReadError"), counter)
        check("확인 불가는 PROBE_ERROR",
              sr.lodging_extensions_probe() == sr.READINESS_PROBE_ERROR)
        raised = ""
        try:
            sr.get_lodging_reservations()
        except sr.SupabaseDataError as exc:
            raised = str(exc)
        check("확인 불가 조회는 빈 목록으로 위조하지 않는다",
              "확인하지 못했습니다" in raised, raised or "예외 없음(결함)")
    finally:
        sr.client, sr._select_all = saved
        sr.reset_lodging_readiness()


# ---------------------------------------------------------------------------
# 겹침 배타 제약 위반(23P01)은 채번 충돌(23505)과 **다르게** 다뤄야 한다:
# 전자는 사용자에게 알릴 도메인 거부(재시도 금지), 후자는 재채번 재시도 대상이다.
# ---------------------------------------------------------------------------
def test_violation_classification() -> None:
    from modules import supabase_repository as sr

    class _Err(Exception):
        def __init__(self, code):
            super().__init__(f"저장 실패({code})")
            self.code = code

    check("23P01 은 겹침 위반으로 분류", sr._is_exclusion_violation(_Err("23P01")) is True)
    check("23505 는 겹침 위반이 아니다", sr._is_exclusion_violation(_Err("23505")) is False)
    check("23505 는 unique 위반으로 분류", sr.is_unique_violation(_Err("23505")) is True)
    check("23P01 은 unique 위반이 아니다", sr.is_unique_violation(_Err("23P01")) is False)
    chained = Exception("wrapper")
    chained.__cause__ = _Err("23P01")
    check("원인 체인에 있어도 찾아낸다", sr._is_exclusion_violation(chained) is True)


# ---------------------------------------------------------------------------
# 채번 규칙은 순수 함수(lodging_data.next_request_no)가 단일 출처다. 저장소는 계산에
# 필요한 사실(기존 번호)만 최신으로 가져온다 — 두 번째 구현이 생기지 않았는지 고정한다.
# ---------------------------------------------------------------------------
def test_request_number_single_source() -> None:
    import re
    from datetime import date

    from modules import lodging_data as ld
    from modules import supabase_repository as sr

    from modules import db

    repo_src = Path(sr.__file__).read_text(encoding="utf-8")
    facade_src = Path(db.__file__).read_text(encoding="utf-8")
    check("저장소는 순번 형식을 스스로 만들지 않는다", ":03d" not in repo_src,
          "저장소에 순번 서식이 생겼다(순수 함수와 이중 구현 위험)")
    check("파사드도 접두 문자열을 재조립하지 않는다",
          '"LDG-' not in facade_src and "'LDG-" not in facade_src,
          "파사드에 채번 문자열이 생겼다")
    check("파사드는 순수 채번 함수에 위임한다",
          facade_src.count("ld.next_request_no(") >= 2
          and "ld.request_no_prefix()" in facade_src)
    today = date(2026, 8, 20)
    check("첫 채번은 001", ld.next_request_no([], today=today) == "LDG-202608-001")
    check("같은 연월 최대값 + 1",
          ld.next_request_no([{"request_no": "LDG-202608-007"},
                              {"request_no": "LDG-202607-099"}], today=today)
          == "LDG-202608-008")
    check("형식은 LDG-YYYYMM-NNN",
          bool(re.fullmatch(r"LDG-\d{6}-\d{3}", ld.next_request_no([], today=today))))


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
    test_single_read_id_resolution()
    test_capabilities_probe_states()
    test_lodging_readiness_states()
    test_violation_classification()
    test_request_number_single_source()

    print()
    if FAIL:
        print(f"FAILED {len(FAIL)}: {FAIL}")
        sys.exit(1)
    print(f"ALL PASSED ({PASS} checks)")


if __name__ == "__main__":
    main()
