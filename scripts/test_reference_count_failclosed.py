"""참조 건수 조회 fail-closed 계약 회귀 테스트 (순수 mock, 원격 쓰기 없음).

삭제 화면 controller 는 ``sum(refs.values()) > 0`` 으로 물리 삭제(참조 0)와 미사용
처리(참조>0)를 가른다. 따라서 참조 건수 조회는 삭제 안전 임계 경로다. 이 스위트는
``modules/db.py`` 의 4개 ``*_reference_counts`` 가 다음을 지키는지 검증한다.

  - 고신뢰 '테이블 미생성'(migration 미적용) 신호(42P01 / PGRST205 / "Could not find
    the table … schema cache") → 참조 0, sentinel 없음 → 물리 삭제 허용(정당).
  - 그 외 모든 실패(네트워크/소켓, 그리고 결정적으로 "…does not exist" 를 포함한 DNS
    오류) → sentinel(REFERENCE_CHECK_FAILED) → sum>0 → 미사용 처리(fail-closed).
  - 정상 경로 → 실제 건수, sentinel 없음.
  - department 부분 실패: 한 loader 만 일시 실패해도 sentinel + 나머지 실제 건수 보존.

fail-OPEN 회귀(예: bare "does not exist" 를 테이블 미생성으로 오분류)를 잡는 것이 목적.
"""
import sys
from contextlib import contextmanager
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from modules import db  # noqa: E402

SENT = db.REFERENCE_CHECK_FAILED

_passed = 0
_failed = 0


def check(label: str, cond: bool) -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok - {label}")
    else:
        _failed += 1
        print(f"  FAIL - {label}")


# --- mock 예외들 ---------------------------------------------------------
class FakeAPIError(Exception):
    """postgrest APIError 유사 — 구조 필드(code/message)를 노출한다."""

    def __init__(self, code="", message="", details="", hint=""):
        super().__init__(message or code)
        self.code = code
        self.message = message
        self.details = details
        self.hint = hint


def err_missing_table_code():
    # PostgREST 스키마 캐시 테이블 미발견(PGRST205) — 고신뢰 미생성.
    return FakeAPIError(
        code="PGRST205",
        message="Could not find the table 'public.shift_groups' in the schema cache",
    )


def err_missing_table_42p01():
    # PostgreSQL undefined_table 코드가 문자열로만 노출되는 경우.
    return db.DATA_SOURCE_ERRORS[1](
        'Supabase shift_groups 조회 실패: 42P01 relation "shift_groups" does not exist'
    )


def err_transient_reset():
    return ConnectionResetError("[Errno 104] Connection reset by peer")


def err_transient_dns():
    # 결정적 케이스: 'does not exist' 가 네트워크 오류 문구에 등장 → 반드시 fail-closed.
    return db.DATA_SOURCE_ERRORS[1](
        "Supabase users 조회 실패: temporary failure in name resolution: host does not exist"
    )


def err_transient_column_42703():
    # 무관 컬럼 undefined(42703) — 테이블 미생성이 아니므로 fail-closed 이어야 한다.
    return db.DATA_SOURCE_ERRORS[1](
        'Supabase users 조회 실패: 42703 column "bogus" does not exist'
    )


# --- loader 패치 유틸 -----------------------------------------------------
@contextmanager
def patched(**loaders):
    """db 모듈의 loader 심볼을 임시 교체한다."""
    saved = {name: getattr(db, name) for name in loaders}
    try:
        for name, fn in loaders.items():
            setattr(db, name, fn)
        yield
    finally:
        for name, fn in saved.items():
            setattr(db, name, fn)


def raises(exc_factory):
    def _f(*a, **k):
        raise exc_factory()
    return _f


def returns(df):
    def _f(*a, **k):
        return df.copy()
    return _f


def users_df(rows):
    return pd.DataFrame(rows, columns=["emp_no", "dept_code", "team_code"])


# =========================================================================
print("team_reference_counts — 미생성/일시/정상")
with patched(get_users=raises(err_missing_table_code)):
    r = db.team_reference_counts("D1", "T1")
    check("PGRST205 미생성 → users 0", r.get("users") == 0)
    check("PGRST205 미생성 → sentinel 없음(물리삭제 허용)", SENT not in r and sum(r.values()) == 0)

with patched(get_users=raises(err_missing_table_42p01)):
    r = db.team_reference_counts("D1", "T1")
    check("42P01 미생성 → sentinel 없음(물리삭제 허용)", SENT not in r and sum(r.values()) == 0)

with patched(get_users=raises(err_transient_reset)):
    r = db.team_reference_counts("D1", "T1")
    check("ConnectionReset → sentinel + sum>0(미사용)", SENT in r and sum(r.values()) > 0)

with patched(get_users=raises(err_transient_dns)):
    r = db.team_reference_counts("D1", "T1")
    check("DNS 'does not exist' → fail-closed sentinel(핵심)", SENT in r and sum(r.values()) > 0)

with patched(get_users=raises(err_transient_column_42703)):
    r = db.team_reference_counts("D1", "T1")
    check("무관 컬럼 42703 → fail-closed sentinel", SENT in r and sum(r.values()) > 0)

with patched(get_users=returns(users_df([("E1", "D1", "T1"), ("E2", "D1", "T1"), ("E3", "D9", "T9")]))):
    r = db.team_reference_counts("D1", "T1")
    check("정상 → 실제 건수(users=2), sentinel 없음", r.get("users") == 2 and SENT not in r)


print("work_type_reference_counts — 미생성/일시/정상")
sched = pd.DataFrame([("WT1",), ("WT1",), ("WT2",)], columns=["work_type_code"])
with patched(get_schedules=raises(err_missing_table_code)):
    r = db.work_type_reference_counts("WT1")
    check("PGRST205 미생성 → sentinel 없음(물리삭제 허용)", SENT not in r and sum(r.values()) == 0)

with patched(get_schedules=raises(err_transient_dns)):
    r = db.work_type_reference_counts("WT1")
    check("DNS 'does not exist' → fail-closed sentinel(핵심)", SENT in r and sum(r.values()) > 0)

with patched(get_schedules=raises(err_transient_reset)):
    r = db.work_type_reference_counts("WT1")
    check("ConnectionReset → fail-closed sentinel", SENT in r and sum(r.values()) > 0)

with patched(get_schedules=returns(sched)):
    r = db.work_type_reference_counts("WT1")
    check("정상 → 실제 건수(schedules=2), sentinel 없음", r.get("schedules") == 2 and SENT not in r)


print("org_group_reference_counts — 미생성/일시/정상")
depts = pd.DataFrame([("D1", "G1"), ("D2", "G1"), ("D3", "G2")], columns=["dept_code", "group_code"])
with patched(get_org_departments=raises(err_missing_table_code)):
    r = db.org_group_reference_counts("G1")
    check("PGRST205 미생성 → sentinel 없음(물리삭제 허용)", SENT not in r and sum(r.values()) == 0)

with patched(get_org_departments=raises(err_transient_dns)):
    r = db.org_group_reference_counts("G1")
    check("DNS 'does not exist' → fail-closed sentinel(핵심)", SENT in r and sum(r.values()) > 0)

with patched(get_org_departments=returns(depts)):
    r = db.org_group_reference_counts("G1")
    check("정상 → 실제 건수(departments=2), sentinel 없음", r.get("departments") == 2 and SENT not in r)


print("department_reference_counts — 미생성/일시/부분실패/정상")
udf = users_df([("E1", "D1", "T1"), ("E2", "D1", "T2")])
tdf = pd.DataFrame([("D1", "T1"), ("D1", "T2"), ("D9", "T9")], columns=["dept_code", "team_code"])
sgdf = pd.DataFrame([("D1",), ("D2",)], columns=["dept_code"])

with patched(
    get_users=returns(udf), get_teams=returns(tdf),
    get_shift_groups=raises(err_missing_table_code),
):
    r = db.department_reference_counts("D1")
    check("shift_groups 테이블 미생성만 실패 → sentinel 없음(정당 0 처리)",
          SENT not in r and r.get("users") == 2 and r.get("teams") == 2 and r.get("shift_groups") == 0)

with patched(
    get_users=raises(err_transient_dns), get_teams=returns(tdf),
    get_shift_groups=returns(sgdf),
):
    r = db.department_reference_counts("D1")
    check("부분 일시실패(users DNS) → sentinel + 나머지 실제건수 보존",
          SENT in r and sum(r.values()) > 0 and r.get("teams") == 2 and r.get("shift_groups") == 1)

with patched(get_users=raises(err_transient_reset), get_teams=raises(err_transient_reset),
             get_shift_groups=raises(err_transient_reset)):
    r = db.department_reference_counts("D1")
    check("전 loader 일시실패 → fail-closed sentinel", SENT in r and sum(r.values()) > 0)

with patched(get_users=returns(udf), get_teams=returns(tdf), get_shift_groups=returns(sgdf)):
    r = db.department_reference_counts("D1")
    check("정상 → 실제 건수(users=2,teams=2,sg=1), sentinel 없음",
          r.get("users") == 2 and r.get("teams") == 2 and r.get("shift_groups") == 1 and SENT not in r)


print()
if _failed:
    print(f"FAILED ({_failed} of {_passed + _failed} checks)")
    sys.exit(1)
print(f"ALL PASSED ({_passed} checks)")
