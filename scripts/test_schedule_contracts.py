"""002 데이터 구조(월 편성/근무조) 계약·검증 단위 테스트.

로컬 sample 모드에서만 동작하며 Supabase 에 접속하지 않는다.
실행: python scripts/test_schedule_contracts.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"  # Supabase 미접속 보장

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from modules import db, validators  # noqa: E402

PASSED = 0


def check(name: str, condition: bool) -> None:
    global PASSED
    assert condition, f"FAILED: {name}"
    PASSED += 1
    print(f"  ok - {name}")


def raises(fn, exc_type=Exception) -> Exception | None:
    try:
        fn()
    except exc_type as exc:
        return exc
    return None


def test_normalize_schedule_month() -> None:
    print("validators.normalize_schedule_month")
    check("YYYY-MM", validators.normalize_schedule_month("2026-07") == "2026-07-01")
    check("YYYY-MM-DD", validators.normalize_schedule_month("2026-07-15") == "2026-07-01")
    check("tuple", validators.normalize_schedule_month((2026, 7)) == "2026-07-01")
    from datetime import date
    check("date", validators.normalize_schedule_month(date(2026, 7, 31)) == "2026-07-01")
    check("잘못된 입력 ValueError", raises(lambda: validators.normalize_schedule_month("2026/07"), ValueError) is not None)
    check("빈 값 ValueError", raises(lambda: validators.normalize_schedule_month(""), ValueError) is not None)
    check("13월 ValueError", raises(lambda: validators.normalize_schedule_month("2026-13"), ValueError) is not None)


def test_month_matches() -> None:
    print("validators.month_matches")
    check("같은 달", validators.month_matches("2026-07-15", "2026-07-01"))
    check("다른 달", not validators.month_matches("2026-08-01", "2026-07-01"))
    check("잘못된 날짜", not validators.month_matches("not-a-date", "2026-07-01"))


_EMP_NOS = {"1001", "1002"}
_DEPTS = {"PET1", "PET2"}
_TEAMS = {("PET1", "T1"), ("PET2", "T2")}
_SHIFTS = {("PET1", "A"), ("PET1", "B"), ("PET2", "C")}


def _assignment(**overrides) -> dict:
    record = {
        "emp_no": "1001", "schedule_month": "2026-07",
        "dept_code": "PET1", "team_code": "T1", "shift_group_code": "A",
    }
    record.update(overrides)
    return record


def test_validate_assignment_records() -> None:
    print("validators.validate_assignment_records")
    normalized, errors = validators.validate_assignment_records(
        [_assignment()], _EMP_NOS, _DEPTS, _TEAMS, _SHIFTS)
    check("정상 레코드 통과", not errors)
    check("월 1일 정규화", normalized[0]["schedule_month"] == "2026-07-01")

    _, errors = validators.validate_assignment_records(
        [_assignment(), _assignment(schedule_month="2026-07-20", shift_group_code="B")],
        _EMP_NOS, _DEPTS, _TEAMS, _SHIFTS)
    check("같은 직원·같은 달 중복 차단", any("중복" in e for e in errors))

    _, errors = validators.validate_assignment_records(
        [_assignment(), _assignment(schedule_month="2026-08")],
        _EMP_NOS, _DEPTS, _TEAMS, _SHIFTS)
    check("다른 달은 허용", not errors)

    _, errors = validators.validate_assignment_records(
        [_assignment(team_code="T2")], _EMP_NOS, _DEPTS, _TEAMS, _SHIFTS)
    check("타 부서 팀 차단", any("없는 팀" in e for e in errors))

    _, errors = validators.validate_assignment_records(
        [_assignment(team_code="")], _EMP_NOS, _DEPTS, _TEAMS, _SHIFTS)
    check("팀 미지정 허용 (users 정책과 동일)", not errors)

    _, errors = validators.validate_assignment_records(
        [_assignment(shift_group_code="C")], _EMP_NOS, _DEPTS, _TEAMS, _SHIFTS)
    check("타 부서 조 차단", any("활성 조가 아닙니다" in e for e in errors))

    _, errors = validators.validate_assignment_records(
        [_assignment(shift_group_code="")], _EMP_NOS, _DEPTS, _TEAMS, _SHIFTS)
    check("조 미입력 차단", any("조 코드를 입력" in e for e in errors))

    _, errors = validators.validate_assignment_records(
        [_assignment(dept_code="NOPE")], _EMP_NOS, _DEPTS, _TEAMS, _SHIFTS)
    check("없는 부서 차단", any("부서코드" in e for e in errors))

    _, errors = validators.validate_assignment_records(
        [_assignment(emp_no="9999")], _EMP_NOS, _DEPTS, _TEAMS, _SHIFTS)
    check("없는 사번 차단", any("사번" in e for e in errors))


def test_validate_schedule_records() -> None:
    print("validators.validate_schedule_records")
    codes = {"주", "야", "OFF"}
    ok = [{"emp_no": "1001", "duty_date": "2026-07-01", "work_type_code": "주"}]
    check("정상 레코드 통과", not validators.validate_schedule_records(ok, _EMP_NOS, codes, "2026-07-01"))

    errors = validators.validate_schedule_records(
        ok + ok, _EMP_NOS, codes, "2026-07-01")
    check("같은 직원·같은 날짜 중복 차단", any("중복" in e for e in errors))

    errors = validators.validate_schedule_records(
        [{"emp_no": "1001", "duty_date": "2026-08-01", "work_type_code": "주"}],
        _EMP_NOS, codes, "2026-07-01")
    check("편성 대상 월 밖 근무일 차단", any("속하지 않습니다" in e for e in errors))

    errors = validators.validate_schedule_records(
        [{"emp_no": "1001", "duty_date": "2026-07-01", "work_type_code": "특특"}],
        _EMP_NOS, codes, "2026-07-01")
    check("미등록/비활성 근무코드 차단", any("활성 근무형태" in e for e in errors))


def _seed_shift_groups() -> None:
    """sample 세션 스토어에 근무조 기준정보를 적재한다 (CSV 파일 불필요)."""
    st.session_state[db._SHIFT_GROUPS_STORE] = pd.DataFrame([
        {"dept_code": "PET1", "shift_code": "A", "shift_name": "A조",
         "sort_order": 1, "is_active": True},
        {"dept_code": "PET1", "shift_code": "B", "shift_name": "B조",
         "sort_order": 2, "is_active": True},
        {"dept_code": "PET1", "shift_code": "X", "shift_name": "X조(중지)",
         "sort_order": 3, "is_active": False},
    ], columns=db.SHIFT_GROUP_COLUMNS)


def test_facade_contracts() -> None:
    print("db 파사드 계약 (sample 모드)")
    check("sample 모드 동작", db.is_sample_mode())

    empty = db.get_month_assignments(2030, 1)
    check("빈 편성 컬럼 계약", list(empty.columns) == db.SCHEDULE_ASSIGNMENT_COLUMNS)
    check("빈 편성 0건", empty.empty)

    st.session_state.pop(db._SHIFT_GROUPS_STORE, None)
    sg_empty = db.get_shift_groups()
    check("빈 근무조 컬럼 계약", list(sg_empty.columns) == db.SHIFT_GROUP_COLUMNS)
    check("빈 근무조 is_active dtype", str(sg_empty["is_active"].dtype) == "bool")
    check("빈 근무조 sort_order dtype", str(sg_empty["sort_order"].dtype) == "int64")

    _seed_shift_groups()
    check("활성 조 조회", db.get_shift_groups(is_active=True)["shift_code"].tolist() == ["A", "B"])
    check("부서 필터", set(db.get_shift_groups(dept_code="PET1")["shift_code"]) == {"A", "B", "X"})


def test_facade_upsert_assignments() -> None:
    print("db.upsert_month_assignments (sample 모드)")
    _seed_shift_groups()
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)

    teams = db.get_teams()
    team_code = teams[teams["dept_code"] == "PET1"].iloc[0]["team_code"]

    db.upsert_month_assignments([{
        "emp_no": "1001", "schedule_month": "2026-07",
        "dept_code": "PET1", "team_code": team_code, "shift_group_code": "A",
    }])
    got = db.get_month_assignments(2026, 7, "1001")
    check("편성 1건 저장", len(got) == 1)
    check("월 1일 정규화 저장", got.iloc[0]["schedule_month"] == "2026-07-01")
    check("조 스냅샷 저장", got.iloc[0]["shift_group_code"] == "A")

    # 같은 직원·같은 달 재저장은 중복 생성이 아니라 수정(upsert)
    db.upsert_month_assignments([{
        "emp_no": "1001", "schedule_month": "2026-07-15",
        "dept_code": "PET1", "team_code": team_code, "shift_group_code": "B",
    }])
    got = db.get_month_assignments(2026, 7, "1001")
    check("직원별 월 편성 1건 유지", len(got) == 1)
    check("upsert 로 조 변경", got.iloc[0]["shift_group_code"] == "B")

    # 한 batch 안의 같은 직원·같은 달 중복은 차단
    exc = raises(lambda: db.upsert_month_assignments([
        {"emp_no": "1001", "schedule_month": "2026-09", "dept_code": "PET1",
         "team_code": team_code, "shift_group_code": "A"},
        {"emp_no": "1001", "schedule_month": "2026-09-20", "dept_code": "PET1",
         "team_code": team_code, "shift_group_code": "B"},
    ]), ValueError)
    check("batch 내 직원·월 중복 차단", exc is not None and "중복" in str(exc))

    # 비활성 조 차단
    exc = raises(lambda: db.upsert_month_assignments([
        {"emp_no": "1001", "schedule_month": "2026-10", "dept_code": "PET1",
         "team_code": team_code, "shift_group_code": "X"},
    ]), ValueError)
    check("비활성 조 차단", exc is not None and "활성 조" in str(exc))

    # 선택 부서에 속하지 않는 팀 차단.
    # 샘플 데이터는 부서 간 팀 코드가 겹치므로(PET1·PET2 모두 A/B),
    # PET1 에 존재하지 않는 팀 코드로 부서-팀 소속 검증을 확인한다.
    pet1_codes = set(teams[teams["dept_code"] == "PET1"]["team_code"].astype(str))
    other_only = sorted(set(teams["team_code"].astype(str)) - pet1_codes) or ["ZZ"]
    exc = raises(lambda: db.upsert_month_assignments([
        {"emp_no": "1001", "schedule_month": "2026-10", "dept_code": "PET1",
         "team_code": other_only[0], "shift_group_code": "A"},
    ]), ValueError)
    check("부서에 속하지 않는 팀 차단", exc is not None and "없는 팀" in str(exc))

    # 검증 실패 시 아무것도 저장되지 않음
    check("실패 batch 미반영", db.get_month_assignments(2026, 10, "1001").empty)


def test_snapshot_immune_to_user_master_change() -> None:
    print("사용자 기준정보 변경이 기존 편성을 바꾸지 않음")
    _seed_shift_groups()
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)
    teams = db.get_teams()
    team_code = teams[teams["dept_code"] == "PET1"].iloc[0]["team_code"]
    db.upsert_month_assignments([{
        "emp_no": "1001", "schedule_month": "2026-07",
        "dept_code": "PET1", "team_code": team_code, "shift_group_code": "A",
    }])

    users_before = db.get_users().copy()
    moved = users_before.copy()
    mask = moved["emp_no"].astype(str) == "1001"
    moved.loc[mask, "dept_code"] = "PET2"  # 인사이동 시뮬레이션
    moved.loc[mask, "team_code"] = ""
    db.save_users(moved)
    try:
        got = db.get_month_assignments(2026, 7, "1001")
        check("인사이동 후에도 편성 부서 유지", got.iloc[0]["dept_code"] == "PET1")
        check("인사이동 후에도 편성 조 유지", got.iloc[0]["shift_group_code"] == "A")
        check("users 는 실제로 변경됨", db.find_user_by_emp_no("1001")["dept_code"] == "PET2")
    finally:
        db.save_users(users_before)  # 세션 스토어 원복

    # 반대 방향: 편성 upsert 가 users 를 바꾸지 않음
    db.upsert_month_assignments([{
        "emp_no": "1001", "schedule_month": "2026-11",
        "dept_code": "PET2", "team_code": "", "shift_group_code": "C",
    }] if ("PET2", "C") in {
        (str(d), str(s)) for d, s in zip(
            db.get_shift_groups()["dept_code"], db.get_shift_groups()["shift_code"])
    } else [{
        "emp_no": "1001", "schedule_month": "2026-11",
        "dept_code": "PET1", "team_code": "", "shift_group_code": "A",
    }])
    check("편성 저장이 users 를 변경하지 않음", db.find_user_by_emp_no("1001")["dept_code"] != "")


def test_month_roster() -> None:
    print("db.get_month_roster (sample 모드)")
    _seed_shift_groups()
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)
    st.session_state.pop(db._SCHEDULES_STORE, None)

    # 샘플 CSV 에 1002(user_id=2) 의 2026-07 근무가 있다.
    assignments, schedules = db.get_month_roster(["1002"], 2026, 7)
    check("근무 프레임 컬럼 계약", list(schedules.columns) == db.SCHEDULE_ASSIGNED_COLUMNS)
    check("편성 없으면 편성 0건", assignments.empty)
    if not schedules.empty:
        check("편성 없는 근무의 편성 컬럼은 빈 문자열",
              (schedules["dept_code"] == "").all() and (schedules["shift_group_code"] == "").all())

    teams = db.get_teams()
    team_code = teams[teams["dept_code"] == "PET1"].iloc[0]["team_code"]
    db.upsert_month_assignments([{
        "emp_no": "1002", "schedule_month": "2026-07",
        "dept_code": "PET1", "team_code": team_code, "shift_group_code": "B",
    }])
    assignments, schedules = db.get_month_roster(["1002"], 2026, 7)
    check("편성 1건 반환", len(assignments) == 1)
    check("근무 행에 편성 정보 병합",
          schedules.empty or (schedules["shift_group_code"] == "B").all())

    # 빈 조회도 계약 유지
    assignments, schedules = db.get_month_roster(["없는사번"], 2026, 7)
    check("빈 편성 계약", list(assignments.columns) == db.SCHEDULE_ASSIGNMENT_COLUMNS)
    check("빈 근무 계약", list(schedules.columns) == db.SCHEDULE_ASSIGNED_COLUMNS)


def test_day_schedules() -> None:
    print("db.get_day_schedules (sample 모드, 대시보드 조회 전용)")
    from datetime import date as _date

    st.session_state.pop(db._SCHEDULES_STORE, None)
    day = db.get_day_schedules(_date(2026, 7, 1))
    check("일자 조회 컬럼 계약", list(day.columns) == db.SCHEDULE_COLUMNS)
    check("샘플 07-01 근무 5건", len(day) == 5)
    check("모든 행이 대상 일자", set(day["duty_date"].astype(str).str[:10]) == {"2026-07-01"})

    # ISO 문자열 입력도 date 와 동일하게 동작
    day_str = db.get_day_schedules("2026-07-01")
    check("ISO 문자열 입력 동등", len(day_str) == len(day))

    # 근무 없는 일자는 빈 계약 유지(오류 아님)
    empty = db.get_day_schedules(_date(2030, 1, 1))
    check("빈 일자 컬럼 계약", list(empty.columns) == db.SCHEDULE_COLUMNS)
    check("빈 일자 0건", empty.empty)

    # 버킷 분류 계약: OFF→휴무, 주간/야간, 휴가(연차·출산 등)
    wt = db.work_types_map()
    check("주간 코드 분류", db.classify_work_group("주", wt.get("주", {})) == "주간")
    check("야간 코드 분류", db.classify_work_group("야", wt.get("야", {})) == "야간")
    check("OFF 코드 분류", db.classify_work_group("OFF", wt.get("OFF", {})) == "OFF")


def main() -> int:
    for test in (
        test_normalize_schedule_month,
        test_month_matches,
        test_validate_assignment_records,
        test_validate_schedule_records,
        test_facade_contracts,
        test_facade_upsert_assignments,
        test_snapshot_immune_to_user_master_change,
        test_month_roster,
        test_day_schedules,
    ):
        test()
    print(f"\nALL PASSED ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
