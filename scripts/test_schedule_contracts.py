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

    # datetime(시간부 포함) 입력도 날짜로 정규화 — Supabase eq 어긋남 방지(P2-2)
    from datetime import datetime as _dtm
    day_dt = db.get_day_schedules(_dtm(2026, 7, 1, 13, 30))
    check("datetime 시간부 정규화 동등", len(day_dt) == len(day))

    # 근무 없는 일자는 빈 계약 유지(오류 아님)
    empty = db.get_day_schedules(_date(2030, 1, 1))
    check("빈 일자 컬럼 계약", list(empty.columns) == db.SCHEDULE_COLUMNS)
    check("빈 일자 0건", empty.empty)

    # 버킷 분류 계약: OFF→휴무, 주간/야간, 휴가(연차·출산 등)
    wt = db.work_types_map()
    check("주간 코드 분류", db.classify_work_group("주", wt.get("주", {})) == "주간")
    check("야간 코드 분류", db.classify_work_group("야", wt.get("야", {})) == "야간")
    check("OFF 코드 분류", db.classify_work_group("OFF", wt.get("OFF", {})) == "OFF")

    # Supabase 분기가 실제로 정규화된 YYYY-MM-DD 인자로 eq 조회하는지 검증(P2-2·E2E).
    # datetime 시간부가 eq 조건에 새지 않음을 supabase 인자 수준에서 증명한다.
    from datetime import datetime as _dtm2

    captured: dict = {}

    class _FakeQuery:
        def eq(self, col, val):
            captured[col] = val
            return self

        def order(self, *args, **kwargs):
            return self

    def _fake_schedule_rows(builder):
        builder(_FakeQuery())
        return db._typed_empty_frame(db.SCHEDULE_COLUMNS)

    orig_sample = db.is_sample_mode
    orig_rows = db.supabase_repository._schedule_rows
    db.is_sample_mode = lambda: False
    db.supabase_repository._schedule_rows = _fake_schedule_rows
    try:
        db.get_day_schedules(_dtm2(2026, 7, 1, 13, 30))
        check("Supabase eq 인자 정규화(YYYY-MM-DD)", captured.get("work_date") == "2026-07-01")
    finally:
        db.is_sample_mode = orig_sample
        db.supabase_repository._schedule_rows = orig_rows


def test_dashboard_board_contracts() -> None:
    print("views.dashboard 보드 계약 (MANAGER 범위·스냅샷 소속·비활성 표시)")
    from datetime import date as _date
    from views import dashboard as dash

    st.session_state.pop(db._SCHEDULES_STORE, None)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)
    _seed_shift_groups()

    day = db.get_day_schedules(_date(2026, 7, 1))
    users = db.get_users()
    wt = db.work_types_map()
    merged = day.merge(users, on="emp_no", how="left")

    # ADMIN(범위 없음): 근무행 전원 집계
    board, present, totals = dash._build_board(day, users, wt)
    admin_total = sum(g["total"] for g in board)
    check("ADMIN 전체 집계 = 근무행 수", admin_total == len(day))
    check("요약 totals 합 = 근무행 수", sum(totals.values()) == len(day))

    # MANAGER 범위: 담당 부서만
    some_dept = str(merged["dept_code"].dropna().astype(str).iloc[0])
    mboard, _, _ = dash._build_board(day, users, wt, manager_dept=some_dept)
    m_total = sum(g["total"] for g in mboard)
    expected = int((merged["dept_code"].astype(str) == some_dept).sum())
    check("MANAGER 부서 범위 필터 = 해당 부서 근무행", m_total == expected)
    check("MANAGER 범위 < ADMIN 전체(부서 2개 이상 데이터)", m_total < admin_total)

    def has_person(bd, person_name):
        return any(
            p["name"] == person_name
            for g in bd for lst in g["buckets"].values() for p in lst
        )

    # 스냅샷 소속 우선: 1005(현재 PET2)에 2026-07 PET1 편성 → PET1 로 그룹핑
    teams = db.get_teams()
    t = str(teams[teams["dept_code"] == "PET1"].iloc[0]["team_code"])
    db.upsert_month_assignments([{
        "emp_no": "1005", "schedule_month": "2026-07",
        "dept_code": "PET1", "team_code": t, "shift_group_code": "A",
    }])
    snap = dash._month_snapshot(_date(2026, 7, 1))
    check("스냅샷 emp→dept 조회", snap.get("1005", ("", ""))[0] == "PET1")
    b_pet1, _, _ = dash._build_board(day, users, wt, snap=snap, manager_dept="PET1")
    b_pet2, _, _ = dash._build_board(day, users, wt, snap=snap, manager_dept="PET2")
    check("스냅샷 부서(PET1)로 그룹핑", has_person(b_pet1, "정근무"))
    check("현재 부서(PET2) 아님(스냅샷 우선·자동저장 없음)", not has_person(b_pet2, "정근무"))
    # 스냅샷은 users 를 바꾸지 않는다(표시용)
    check("스냅샷이 users 현재 소속 불변", db.find_user_by_emp_no("1005")["dept_code"] == "PET2")

    # P2-4: 비활성 그룹은 재출현하지 않고 부서명으로 폴백(그룹 권위=활성 organization_groups)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)
    groups = db.get_org_groups().copy()
    groups.loc[groups["group_code"] == "PET2", "group_name"] = "구분되는그룹명"
    groups.loc[groups["group_code"] == "PET2", "is_active"] = False
    db.save_org_groups(groups)
    day2 = db.get_day_schedules(_date(2026, 7, 1))
    board2, _, _ = dash._build_board(day2, db.get_users(), wt)
    pet2_names = [g["name"] for g in board2 if g["code"] == "PET2"]
    check("비활성 그룹명 미사용(재출현 방지)", "구분되는그룹명" not in pet2_names)
    check("비활성 그룹 부서는 부서명으로 폴백", bool(pet2_names) and pet2_names[0] == db.dept_name("PET2"))

    st.session_state.pop(db._ORG_GROUPS_STORE, None)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)


def test_dashboard_scope_and_safety() -> None:
    print("views.dashboard 권한범위(fail-closed)·NA-safety·견고성")
    from datetime import date as _date
    from views import dashboard as dash
    from views import workspace

    st.session_state.pop(db._SCHEDULES_STORE, None)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)
    st.session_state.pop(db._ORG_GROUPS_STORE, None)
    st.session_state.pop(db._WORK_TYPES_STORE, None)

    day = db.get_day_schedules(_date(2026, 7, 1))
    users = db.get_users()
    wt = db.work_types_map()

    # (a) fail-closed: 전체 조회는 ADMIN 만. 부서 미확정 MANAGER 는 차단(전체 아님).
    check("ADMIN → 전체", dash._scope_for({"role": "ADMIN"}) == ("all", None))
    check("유효 MANAGER → 자기부서 한정",
          dash._scope_for({"role": "MANAGER", "dept_code": "PET1"}) == ("scoped", "PET1"))
    check("공백 dept MANAGER → 차단(blocked)",
          dash._scope_for({"role": "MANAGER", "dept_code": ""}) == ("blocked", None))
    check("None dept MANAGER → 차단(blocked)",
          dash._scope_for({"role": "MANAGER", "dept_code": None}) == ("blocked", None))
    import numpy as _np
    check("NaN dept MANAGER → 차단(NA-safe)",
          dash._scope_for({"role": "MANAGER", "dept_code": _np.nan}) == ("blocked", None))
    # 차단 MANAGER 는 결코 전체(ADMIN) 보드로 열리지 않는다: manager_dept 로 None 이
    # 넘어가지 않음을 계약으로 고정(전체 집계와 비교).
    admin_board, _, _ = dash._build_board(day, users, wt, manager_dept=None)
    admin_total = sum(g["total"] for g in admin_board)
    check("차단 MANAGER 는 전체 조회 아님(fail-open 아님)",
          dash._scope_for({"role": "MANAGER", "dept_code": ""})[0] == "blocked"
          and admin_total == len(day))

    # (b) 비활성 근무형태 참조 근무의 약칭·색 표시(소프트삭제 참조 보존)
    wts = db.get_work_types().copy()
    wts.loc[wts["code"] == "특주", "is_active"] = False
    db.save_work_types(wts)
    active_only, _ = workspace.work_type_display()
    check("활성전용 맵은 비활성 근무형태 제외", "특주" not in active_only)
    disp, col = dash._display_maps()
    check("비활성 근무형태 약칭 보존", disp.get("특주") == "특주")
    check("비활성 근무형태 색 보존", str(col.get("특주", "")).startswith("#"))
    st.session_state.pop(db._WORK_TYPES_STORE, None)  # 원복

    # (c) 조직 조회 실패가 보드에서 삼켜지지 않고 전파(화면 render try 가 처리)
    orig = db.get_org_groups

    def _boom(*a, **k):
        raise db.supabase_repository.SupabaseDataError("조직 조회 실패(모의)")

    db.get_org_groups = _boom
    try:
        propagated = raises(
            lambda: dash._build_board(day, users, wt), db.DATA_SOURCE_ERRORS
        )
        check("조직 조회 실패 전파(화면 밖 유출 아님)", propagated is not None)
    finally:
        db.get_org_groups = orig

    # (d) 활성 그룹 0건에도 보드 구성(부서 폴백, crash 없음)
    st.session_state[db._ORG_GROUPS_STORE] = db.get_org_groups().iloc[0:0].copy()
    board0, _, tot0 = dash._build_board(day, db.get_users(), wt)
    check("활성 그룹 0건 → 부서 폴백 집계 유지", sum(g["total"] for g in board0) == len(day))
    check("활성 그룹 0건 → 요약 합 유지", sum(tot0.values()) == len(day))
    st.session_state.pop(db._ORG_GROUPS_STORE, None)

    # (e) _month_snapshot NA-safety: dept/team 이 NaN 인 편성도 예외 없이 처리
    import pandas as _pd
    st.session_state[db._ASSIGNMENTS_STORE] = _pd.DataFrame([
        {"emp_no": "1002", "schedule_month": "2026-07-01",
         "dept_code": _np.nan, "team_code": None, "shift_group_code": ""},
    ], columns=db.SCHEDULE_ASSIGNMENT_COLUMNS)
    snap = dash._month_snapshot(_date(2026, 7, 1))
    check("NA 편성도 NA-safe(빈 문자열 폴백)", snap.get("1002") == ("", ""))
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)


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
        test_dashboard_board_contracts,
        test_dashboard_scope_and_safety,
    ):
        test()
    print(f"\nALL PASSED ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
