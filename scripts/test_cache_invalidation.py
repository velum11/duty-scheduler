"""캐시 무효화 finally 계약 테스트 (supabase 분기, 순수 mock — 실네트워크 없음).

검증 대상(직전 P1 회귀 방지)
-----------------------------
supabase 읽기 캐시는 쓰기 후 반드시 무효화되어야 한다. 특히 배치 쓰기가 중간에
COMMIT 된 뒤 뒤 배치에서 RAISE 하면(부분 실패), 예전 코드는 ``_invalidate_*()`` 를
건너뛰어 방금 저장된 행이 stale 캐시에 최대 TTL 동안 가려졌다. 수정은 각 쓰기 파사드를
``try: <write> finally: _invalidate_*()`` 로 감싸 어떤 결과(정상/부분성공/예외)에도
무효화가 실행되게 한 것이다.

이 스위트는 각 대표 파사드에 대해 다음을 동시에 증명한다.
  (a) 파사드가 RAISE 하면 예외가 그대로 **전파**된다(삼키지 않음 — 오류를 sample 로
      숨기지 않는다 계약 유지).
  (b) 그럼에도 관련 ``db._invalidate_*`` 가 **실행**된다(finally 도달).
  (c) 정상 반환 시에도 무효화가 실행된다.

안전(무네트워크·무원격쓰기)
----------------------------
supabase 분기는 ``db.is_sample_mode`` 를 False 로 강제해 태우되, 파사드가 부르는
``supabase_repository.*`` 쓰기/읽기 함수는 전부 mock 으로 치환한다. 추가 안전망으로
``supabase_repository.client`` 를 폭발 mock 으로 막아, 어떤 코드가 실제 연결을
시도하면 테스트가 즉시 실패한다(원격 쓰기 물리 불가). DUTY_SUPABASE_TEST_PROJECT
불필요.

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_cache_invalidation.py
      (stdout 은 UTF-8 자동 설정 — cp949 콘솔에서도 실행 가능)
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# st.cache_data 를 런타임 밖(스크립트)에서 참조할 때 나오는 "No runtime found"
# 경고를 잠재운다(무해한 안내 — 테스트 결과와 무관, 출력만 정리). streamlit 은
# import 시 자식 로거 레벨을 다시 세팅하므로, streamlit 을 먼저 import 한 뒤 해당
# 로거를 직접 겨눠야 억제가 유지된다.
import streamlit  # noqa: E402,F401

logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(logging.ERROR)

# Windows 기본 콘솔(cp949)에서도 한글/em dash 출력이 UnicodeEncodeError 로 멈추지
# 않도록 stdout/stderr 를 UTF-8 로 재설정한다(PYTHONUTF8=1 없이도 실행 가능).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# import 는 sample 모드로 안전하게. 실제 supabase 분기는 아래에서 mock 으로 강제한다.
os.environ["DUTY_DATA_MODE"] = "sample"

import pandas as pd  # noqa: E402

from modules import db, supabase_repository  # noqa: E402

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


class _Patch:
    """setattr 저장/복원 헬퍼 — 테스트별 mock 을 확실히 되돌린다."""

    def __init__(self) -> None:
        self._saved: list[tuple[object, str, object]] = []

    def set(self, obj: object, name: str, value) -> None:
        self._saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self) -> None:
        for obj, name, val in reversed(self._saved):
            setattr(obj, name, val)
        self._saved.clear()


class _BoomError(RuntimeError):
    """중간 배치 커밋 후 발생한 쓰기 예외를 흉내내는 표식."""


def _raiser(*_a, **_k):
    # SupabaseDataError 로 던져 실제 sanitize 된 저장 실패와 같은 타입 경로를 태운다.
    raise supabase_repository.SupabaseDataError("2번째 배치 커밋 후 실패(mock)")


# --- 전역 환경: supabase 분기 강제 + 네트워크 폭발 가드 -----------------------
# is_sample_mode() 를 False 로 고정하면 모든 파사드가 supabase 분기를 탄다.
db.is_sample_mode = lambda *_a, **_k: False


def _no_network(*_a, **_k):
    raise AssertionError(
        "실제 Supabase 연결이 시도되었습니다 — 이 테스트는 순수 mock 이어야 하며 "
        "원격 쓰기가 발생해서는 안 됩니다."
    )


# 어떤 경로가 client() 를 부르면 즉시 실패(원격 쓰기 물리 차단 증명).
supabase_repository.client = _no_network


_SCHED_ROW = {
    "emp_no": "1001",
    "duty_date": "2026-07-01",
    "work_type_code": "D",
    "note": "",
}
_DEPT_ROW = {"dept_code": "D1", "dept_name": "부서1", "sort_order": 1, "is_active": True}


def _spy():
    flag = {"ran": False}
    return flag, (lambda *_a, **_k: flag.__setitem__("ran", True))


# ===========================================================================
# 대표 파사드별: (부분)실패 시 예외 전파 + finally 무효화, 정상 시 무효화
# ===========================================================================
def test_save_schedules() -> None:
    print("save_schedules (bulk upsert)")
    # 부분 실패
    p = _Patch()
    flag, spy = _spy()
    p.set(supabase_repository, "upsert_schedules", _raiser)
    p.set(db, "_invalidate_schedules", spy)
    exc = None
    try:
        db.save_schedules(pd.DataFrame([_SCHED_ROW]))
    except supabase_repository.SupabaseDataError as e:
        exc = e
    p.undo()
    check("save_schedules 부분실패: 예외 전파(삼키지 않음)", exc is not None)
    check("save_schedules 부분실패: finally 무효화 실행", flag["ran"] is True)

    # 정상 성공
    p = _Patch()
    flag, spy = _spy()
    p.set(supabase_repository, "upsert_schedules", lambda *_a, **_k: None)
    p.set(db, "_invalidate_schedules", spy)
    db.save_schedules(pd.DataFrame([_SCHED_ROW]))
    p.undo()
    check("save_schedules 정상: 무효화 실행", flag["ran"] is True)


def test_upsert_month_schedules() -> None:
    print("upsert_month_schedules (bulk upsert, 삭제 없음)")
    p = _Patch()
    flag, spy = _spy()
    p.set(supabase_repository, "upsert_schedules", _raiser)
    p.set(db, "_invalidate_schedules", spy)
    exc = None
    try:
        db.upsert_month_schedules([_SCHED_ROW])
    except supabase_repository.SupabaseDataError as e:
        exc = e
    p.undo()
    check("upsert_month_schedules 부분실패: 예외 전파", exc is not None)
    check("upsert_month_schedules 부분실패: finally 무효화 실행", flag["ran"] is True)

    p = _Patch()
    flag, spy = _spy()
    p.set(supabase_repository, "upsert_schedules", lambda *_a, **_k: None)
    p.set(db, "_invalidate_schedules", spy)
    db.upsert_month_schedules([_SCHED_ROW])
    p.undo()
    check("upsert_month_schedules 정상: 무효화 실행", flag["ran"] is True)


def test_replace_month_schedules() -> None:
    print("replace_month_schedules (multi-step: upsert 후 개별 삭제)")
    # 개별 삭제 단계가 raise 하는 부분 실패를 흉내낸다(upsert 는 이미 커밋).
    p = _Patch()
    flag, spy = _spy()
    p.set(supabase_repository, "replace_month_schedules", _raiser)
    p.set(db, "_invalidate_schedules", spy)
    exc = None
    try:
        db.replace_month_schedules(["1001"], 2026, 7, [_SCHED_ROW])
    except supabase_repository.SupabaseDataError as e:
        exc = e
    p.undo()
    check("replace_month_schedules 부분실패: 예외 전파", exc is not None)
    check("replace_month_schedules 부분실패: finally 무효화 실행", flag["ran"] is True)

    p = _Patch()
    flag, spy = _spy()
    p.set(supabase_repository, "replace_month_schedules", lambda *_a, **_k: None)
    p.set(db, "_invalidate_schedules", spy)
    db.replace_month_schedules(["1001"], 2026, 7, [_SCHED_ROW])
    p.undo()
    check("replace_month_schedules 정상: 무효화 실행", flag["ran"] is True)


def test_upsert_month_assignments() -> None:
    print("upsert_month_assignments (편성 upsert, 반환값 통과)")
    p = _Patch()
    flag, spy = _spy()
    p.set(supabase_repository, "upsert_month_assignments", _raiser)
    p.set(db, "_invalidate_assignments", spy)
    exc = None
    try:
        db.upsert_month_assignments([{"emp_no": "1001", "schedule_month": "2026-07-01"}])
    except supabase_repository.SupabaseDataError as e:
        exc = e
    p.undo()
    check("upsert_month_assignments 부분실패: 예외 전파", exc is not None)
    check("upsert_month_assignments 부분실패: finally 무효화 실행", flag["ran"] is True)

    p = _Patch()
    flag, spy = _spy()
    sentinel = {("1001", "2026-07-01"): {"id": "X"}}
    p.set(supabase_repository, "upsert_month_assignments", lambda *_a, **_k: sentinel)
    p.set(db, "_invalidate_assignments", spy)
    result = db.upsert_month_assignments([{"emp_no": "1001", "schedule_month": "2026-07-01"}])
    p.undo()
    check("upsert_month_assignments 정상: 무효화 실행", flag["ran"] is True)
    check("upsert_month_assignments 정상: 반환값이 finally 에 덮이지 않고 통과", result is sentinel)


def test_deactivate_user() -> None:
    print("deactivate_user (단일 wrapper)")
    p = _Patch()
    flag, spy = _spy()
    p.set(supabase_repository, "deactivate_user", _raiser)
    p.set(db, "_invalidate_users", spy)
    exc = None
    try:
        db.deactivate_user("1001")
    except supabase_repository.SupabaseDataError as e:
        exc = e
    p.undo()
    check("deactivate_user 실패: 예외 전파", exc is not None)
    check("deactivate_user 실패: finally 무효화 실행", flag["ran"] is True)

    p = _Patch()
    flag, spy = _spy()
    p.set(supabase_repository, "deactivate_user", lambda *_a, **_k: None)
    p.set(db, "_invalidate_users", spy)
    db.deactivate_user("1001")
    p.undo()
    check("deactivate_user 정상: 무효화 실행", flag["ran"] is True)


def test_save_departments_report() -> None:
    print("save_departments_report (부분성공 원장 경로)")
    # 변경 감지 읽기는 mock(빈 프레임)으로 대체해 네트워크·캐시 런타임을 회피한다.
    empty = db._typed_empty_frame(db.DEPT_COLUMNS)
    p = _Patch()
    flag, spy = _spy()
    p.set(db, "_fetch_departments", lambda: empty)
    p.set(supabase_repository, "upsert_departments_reported", _raiser)
    p.set(db, "_invalidate_departments", spy)
    exc = None
    try:
        db.save_departments_report(pd.DataFrame([_DEPT_ROW]))
    except supabase_repository.SupabaseDataError as e:
        exc = e
    p.undo()
    check("save_departments_report 실패: 예외 전파", exc is not None)
    check("save_departments_report 실패: finally 무효화 실행", flag["ran"] is True)

    # 정상: 원장 반환 + 무효화 실행
    p = _Patch()
    flag, spy = _spy()
    ledger = db.BatchWriteResult(saved_keys=["D1"])
    p.set(db, "_fetch_departments", lambda: empty)
    p.set(supabase_repository, "upsert_departments_reported", lambda *_a, **_k: ledger)
    p.set(db, "_invalidate_departments", spy)
    result = db.save_departments_report(pd.DataFrame([_DEPT_ROW]))
    p.undo()
    check("save_departments_report 정상: 무효화 실행", flag["ran"] is True)
    check("save_departments_report 정상: 원장 반환 통과", result is ledger)


def test_no_change_no_write() -> None:
    print("변경 없음: 쓰기·무효화 미발생(현재 계약 보존)")
    # 변경 감지 결과가 비면 파사드는 조기 반환하고 무효화하지 않는다.
    empty = db._typed_empty_frame(db.DEPT_COLUMNS)
    p = _Patch()
    flag, spy = _spy()
    called = {"write": False}
    p.set(db, "_fetch_departments", lambda: empty)
    p.set(
        supabase_repository,
        "upsert_departments_reported",
        lambda *_a, **_k: called.__setitem__("write", True) or db.BatchWriteResult(),
    )
    p.set(db, "_invalidate_departments", spy)
    result = db.save_departments_report(pd.DataFrame(columns=db.DEPT_COLUMNS))
    p.undo()
    check("변경 없음: repository 쓰기 미호출", called["write"] is False)
    check("변경 없음: 무효화 미실행", flag["ran"] is False)
    check("변경 없음: 빈 원장 반환", result.ok and not result.saved_keys)



# ===========================================================================
# 읽기 TTL 분리 + 새로고침 무효화 경로 (성능 개선 2026-08-19 계약)
# ===========================================================================
def test_read_ttl_separation() -> None:
    print("읽기 TTL 분리: 기준정보 vs 트랜잭션·신분")
    import inspect

    lines = inspect.getsource(db).splitlines()

    def ttl_of(name: str) -> str:
        """@st.cache_data(ttl=X) 데코레이터가 붙은 조회 함수의 TTL 상수 이름."""
        target = "def " + name + "("
        for i, line in enumerate(lines):
            if line.startswith(target) and i and "cache_data(ttl=" in lines[i - 1]:
                return lines[i - 1].split("ttl=")[1].split(",")[0].strip()
        return ""

    check("기준정보 TTL 과 트랜잭션 TTL 이 서로 다른 값으로 유지",
          db._REFERENCE_TTL != db._READ_TTL)
    check("트랜잭션 TTL 은 30초", db._READ_TTL == 30)
    check("기준정보 TTL 은 300초 이상", db._REFERENCE_TTL >= 300)
    ref = ("_fetch_departments", "_fetch_teams", "_fetch_work_types", "_fetch_shift_groups",
           "_fetch_organization_groups", "_fetch_departments_org", "_fetch_teams_org")
    got_ref = {name: ttl_of(name) for name in ref}
    check("기준정보 조회는 _REFERENCE_TTL 을 쓴다",
          all(v == "_REFERENCE_TTL" for v in got_ref.values()))
    # users 는 role/is_active 를 실어 로그인 게이트(auth → find_user_by_emp_no)가 읽는다 —
    # 비활성 계정이 TTL 동안 로그인 가능해지지 않도록 짧은 TTL 을 유지한다.
    check("사용자 조회는 트랜잭션 TTL 유지(로그인 is_active 게이트 staleness 상한)",
          ttl_of("_fetch_users") == "_READ_TTL")
    trans = ("_fetch_schedules", "_fetch_schedule_years", "_fetch_month_schedules",
             "_fetch_month_assignments", "_fetch_near_miss")
    got_tr = {name: ttl_of(name) for name in trans}
    check("근무·편성·아차사고 조회는 트랜잭션 TTL 유지",
          all(v == "_READ_TTL" for v in got_tr.values()))


class _ClearSpy:
    """cache_data 객체의 .clear() 만 흉내내는 스텁."""

    def __init__(self) -> None:
        self.cleared = False

    def clear(self) -> None:
        self.cleared = True


def test_schedule_years_cache_invalidated() -> None:
    print("연도 선택지 캐시: 근무 저장 시 함께 무효화")
    p = _Patch()
    spy = _ClearSpy()
    p.set(db, "_fetch_schedule_years", spy)
    db._invalidate_schedules()
    p.undo()
    check("_invalidate_schedules 가 연도 선택지 캐시도 비운다", spy.cleared is True)

    # 쓰기 파사드에서도 같은 경로를 타는지(대표 1개로 확인)
    p = _Patch()
    spy2 = _ClearSpy()
    p.set(db, "_fetch_schedule_years", spy2)
    p.set(supabase_repository, "upsert_schedules", lambda *_a, **_k: None)
    db.save_schedules(pd.DataFrame([_SCHED_ROW]))
    p.undo()
    check("save_schedules 후에도 연도 선택지 캐시가 비워진다", spy2.cleared is True)


def test_refresh_reference_data_scope() -> None:
    print("기준정보 새로고침: 화면 범위만 좁게 무효화(전역 clear 금지)")
    names = ("_invalidate_users", "_invalidate_departments", "_invalidate_teams",
             "_invalidate_groups", "_invalidate_work_types", "_invalidate_schedules",
             "_invalidate_assignments", "_invalidate_near_miss")
    calls: list[str] = []
    p = _Patch()
    for name in names:
        p.set(db, name, (lambda n: (lambda *_a, **_k: calls.append(n)))(name))

    db.refresh_reference_data("work_types")
    check("work_types 범위 = 근무형태만", calls == ["_invalidate_work_types"])
    calls.clear()
    db.refresh_reference_data("users")
    check("users 범위 = 사용자 + 화면이 함께 보이는 부서·조",
          set(calls) == {"_invalidate_users", "_invalidate_departments", "_invalidate_teams"})
    calls.clear()
    db.refresh_reference_data("organization")
    check("organization 범위 = 그룹 + 부서 + 조",
          set(calls) == {"_invalidate_groups", "_invalidate_departments", "_invalidate_teams"})
    check("어느 범위도 근무·편성·아차사고 캐시를 건드리지 않는다",
          not ({"_invalidate_schedules", "_invalidate_assignments", "_invalidate_near_miss"}
               & set(calls)))
    bad = ""
    try:
        db.refresh_reference_data("nope")
    except ValueError as exc:
        bad = str(exc)
    p.undo()
    check("모르는 범위는 조용히 통과하지 않는다(fail-closed)", "알 수 없는" in bad)


def test_refresh_wired_into_master_screens() -> None:
    print("기준정보 3화면: 새로고침 액션이 실제로 재조회가 되는가")
    for path, scope in (("views/master_users.py", '"users"'),
                        ("views/master_org.py", '"organization"'),
                        ("views/master_work_types.py", '"work_types"')):
        src = (ROOT / path).read_text(encoding="utf-8")
        check(f"{path}: 새로고침이 자기 범위 캐시를 비운다",
              f"refresh_reference_data({scope})" in src)
        check(f"{path}: 전역 캐시 초기화를 쓰지 않는다", "st.cache_data.clear()" not in src)


def main() -> int:
    print("=" * 70)
    print("cache invalidation finally 계약 (순수 mock, 무네트워크)")
    print("=" * 70)
    test_save_schedules()
    test_upsert_month_schedules()
    test_replace_month_schedules()
    test_upsert_month_assignments()
    test_deactivate_user()
    test_save_departments_report()
    test_no_change_no_write()
    test_read_ttl_separation()
    test_schedule_years_cache_invalidated()
    test_refresh_reference_data_scope()
    test_refresh_wired_into_master_screens()
    print("-" * 70)
    if FAIL:
        print(f"{PASS} passed, {len(FAIL)} failed")
        for name in FAIL:
            print(f"  FAIL - {name}")
        return 1
    print(f"ALL PASSED ({PASS} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
