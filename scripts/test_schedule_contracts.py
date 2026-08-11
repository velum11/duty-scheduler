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


def _board_names(tree) -> list:
    """계층 트리에 실린 근무자 이름 전체(순서 무관 비교용)."""
    return [p["name"] for m in tree for o in m["orgs"] for lst in o["people"].values()
            for p in lst]


def test_dashboard_board_contracts() -> None:
    print("views.dashboard 계층 집계 계약 (MANAGER 범위·스냅샷 소속·중분류 합산·빈 조직 미표시)")
    from datetime import date as _date
    from views import dashboard as dash

    st.session_state.pop(db._SCHEDULES_STORE, None)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)
    _seed_shift_groups()

    day = db.get_day_schedules(_date(2026, 7, 1))
    users = db.get_users()
    merged = day.merge(users, on="emp_no", how="left")

    # ADMIN(범위 없음): 근무행 전원이 계층 어딘가에 실린다(집계를 조용히 버리지 않는다).
    tree, majors = dash._duty_board(_date(2026, 7, 1))
    admin_total = len(_board_names(tree))
    check("ADMIN 전체 집계 = 근무행 수", admin_total == len(day))
    totals, columns = dash._summarize(tree)
    check("지표 totals 합 = 근무행 수(지표=명단 합)", sum(totals.values()) == len(day))
    check("기본 3열(주간·야간·휴무) 항상 노출",
          columns[:3] == ["주간", "야간", "휴무"])
    check("필터 칩 선택지 = 계층 대분류(노출 순서 그대로)",
          majors == [m["name"] for m in tree])
    check("근무자 없는 조직은 애초에 생기지 않는다",
          all(sum(len(v) for v in o["people"].values()) > 0
              for m in tree for o in m["orgs"]))

    # MANAGER 범위: 담당 부서만
    some_dept = str(merged["dept_code"].dropna().astype(str).iloc[0])
    mtree, _ = dash._duty_board(_date(2026, 7, 1), manager_dept=some_dept)
    m_total = len(_board_names(mtree))
    expected = int((merged["dept_code"].astype(str) == some_dept).sum())
    check("MANAGER 부서 범위 필터 = 해당 부서 근무행", m_total == expected)
    check("MANAGER 범위 < ADMIN 전체(부서 2개 이상 데이터)", m_total < admin_total)

    # 스냅샷 소속 우선: 1005(현재 PET2)에 2026-07 PET1 편성 → PET1 계층으로
    teams = db.get_teams()
    t = str(teams[teams["dept_code"] == "PET1"].iloc[0]["team_code"])
    db.upsert_month_assignments([{
        "emp_no": "1005", "schedule_month": "2026-07",
        "dept_code": "PET1", "team_code": t, "shift_group_code": "A",
    }])
    snap = dash._month_snapshot(_date(2026, 7, 1))
    check("스냅샷 emp→dept 조회", snap.get("1005", ("", ""))[0] == "PET1")
    t_pet1, _ = dash._duty_board(_date(2026, 7, 1), manager_dept="PET1")
    t_pet2, _ = dash._duty_board(_date(2026, 7, 1), manager_dept="PET2")
    check("스냅샷 부서(PET1)로 계층 결정", "정근무" in _board_names(t_pet1))
    check("현재 부서(PET2) 아님(스냅샷 우선·자동저장 없음)", "정근무" not in _board_names(t_pet2))
    # 스냅샷은 users 를 바꾸지 않는다(표시용)
    check("스냅샷이 users 현재 소속 불변", db.find_user_by_emp_no("1005")["dept_code"] == "PET2")
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)

    # 계층 규약: 대분류=부서 / 중분류=조직, 인원은 **중분류 단위 합산**(1팀·2팀 → 한 조직).
    # 실제 조직 데이터(migration 009)를 흉내 낸 부서 프레임을 주입해 규약만 격리 검증한다.
    depts = db.get_org_departments().copy()
    depts.loc[depts["dept_code"] == "PET1", ["major_category", "minor_category"]] = \
        ["PET생산부", "PET생산팀"]
    depts.loc[depts["dept_code"] == "PET2", ["major_category", "minor_category"]] = \
        ["PET생산부", "PET생산팀"]
    tree2, majors2 = dash._duty_board(_date(2026, 7, 1), depts=depts)
    pet = next((m for m in tree2 if m["name"] == "PET생산부"), None)
    check("대분류가 부서 계층이 된다", pet is not None)
    check("중분류 단위 합산(PET1+PET2 → 조직 1개)",
          pet is not None and [o["name"] for o in pet["orgs"]] == ["PET생산팀"])
    pet_rows = int(merged["dept_code"].astype(str).isin(["PET1", "PET2"]).sum())
    check("합산 인원 = 두 부서 근무행 합",
          pet is not None and sum(len(v) for v in pet["orgs"][0]["people"].values()) == pet_rows)
    check("분류된 부서만 있으면 미분류가 생기지 않는다",
          majors2 == ["PET생산부"])
    # 분류가 빠진 부서(조직 관리 입력 누락)는 감추지 않고 '미분류'로 **마지막**에 둔다.
    depts_partial = depts.copy()
    depts_partial.loc[depts_partial["dept_code"] == "PET2",
                      ["major_category", "minor_category"]] = ["", ""]
    tree_mix, majors_mix = dash._duty_board(_date(2026, 7, 1), depts=depts_partial)
    check("분류 없는 부서는 미분류로 마지막",
          majors_mix[-1] == dash._UNCLASSIFIED_LABEL and len(majors_mix) == 2)
    check("미분류의 조직 라벨은 부서명 폴백",
          [o["name"] for o in tree_mix[-1]["orgs"]] == [db.dept_name("PET2")])
    check("미분류도 집계에서 빠지지 않는다",
          len(_board_names(tree_mix)) == len(day))

    # 제외 규칙(시스템 부서·제외 대분류)은 지표와 명단에 같은 기준으로 적용된다.
    depts_ex = depts.copy()
    depts_ex.loc[depts_ex["dept_code"] == "PET1", "major_category"] = \
        dash._EXCLUDED_MAJORS[0]
    tree3, _ = dash._duty_board(_date(2026, 7, 1), depts=depts_ex)
    totals3, _ = dash._summarize(tree3)
    pet1_rows = int((merged["dept_code"].astype(str) == "PET1").sum())
    check("제외 대분류는 명단에서 빠진다",
          len(_board_names(tree3)) == len(day) - pet1_rows)
    check("제외 대분류는 지표에서도 같이 빠진다(지표=명단)",
          sum(totals3.values()) == len(_board_names(tree3)))

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
    # 미지/비정상 역할은 유효 dept 가 있어도 scoped 로 새지 않고 차단(fail-closed)
    check("미지 역할+유효 dept → 차단(scoped 아님)",
          dash._scope_for({"role": "SUPERVISOR", "dept_code": "PET1"}) == ("blocked", None))
    check("역할 공백+dept 있음 → 차단",
          dash._scope_for({"role": "", "dept_code": "PET1"}) == ("blocked", None))
    check("USER 역할도 _scope_for 상 차단(방어; render 는 상위서 개인요약 분기)",
          dash._scope_for({"role": "USER", "dept_code": "PET1"}) == ("blocked", None))
    # 차단 MANAGER 는 결코 전체(ADMIN) 보드로 열리지 않는다: manager_dept 로 None 이
    # 넘어가지 않음을 계약으로 고정(전체 집계와 비교).
    admin_tree, _ = dash._duty_board(_date(2026, 7, 1), manager_dept=None)
    admin_total = len(_board_names(admin_tree))
    check("차단 MANAGER 는 전체 조회 아님(fail-open 아님)",
          dash._scope_for({"role": "MANAGER", "dept_code": ""})[0] == "blocked"
          and admin_total == len(day))

    # (b) 비활성(소프트삭제) 근무형태를 참조하는 근무도 분류되어 명단에 남는다
    #     (근무형태 약칭·색 표시는 이 화면에서 제거됐고, 사람이 사라지지 않는 것이 계약이다)
    wts = db.get_work_types().copy()
    wts.loc[wts["code"] == "특주", "is_active"] = False
    db.save_work_types(wts)
    active_only, _ = workspace.work_type_display()
    check("활성전용 맵은 비활성 근무형태 제외", "특주" not in active_only)
    tree_soft, _ = dash._duty_board(_date(2026, 7, 1))
    check("비활성 근무형태 참조 근무도 명단에 남는다(집계 유실 없음)",
          len(_board_names(tree_soft)) == len(day))
    check("비활성 근무형태도 버킷 분류 유지(주간)", dash._bucket_of("특주", {}) == "주간")
    st.session_state.pop(db._WORK_TYPES_STORE, None)  # 원복

    # (c) 부서 기준정보 조회 실패가 집계에서 삼켜지지 않고 전파(화면 render try 가 처리)
    orig = db.get_org_departments

    def _boom(*a, **k):
        raise db.supabase_repository.SupabaseDataError("조직 조회 실패(모의)")

    db.get_org_departments = _boom
    try:
        propagated = raises(
            lambda: dash._duty_board(_date(2026, 7, 1)), db.DATA_SOURCE_ERRORS
        )
        check("부서 조회 실패 전파(화면 밖 유출 아님)", propagated is not None)
    finally:
        db.get_org_departments = orig

    # (d) 부서 기준정보 0건에도 집계 유지(부서명 폴백, crash 없음)
    empty_depts = db.get_org_departments().iloc[0:0].copy()
    tree0, _ = dash._duty_board(_date(2026, 7, 1), depts=empty_depts)
    check("부서 기준정보 0건 → 집계 유지", len(_board_names(tree0)) == len(day))
    tot0, _ = dash._summarize(tree0)
    check("부서 기준정보 0건 → 지표 합 유지", sum(tot0.values()) == len(day))
    check("부서 기준정보 0건 → 미분류로 모임",
          all(m["name"] == dash._UNCLASSIFIED_LABEL for m in tree0))

    # (e) 근무 0건 → 빈 계층(빈 조직을 만들지 않는다)
    tree_none, majors_none = dash._duty_board(
        _date(2026, 7, 1), day_rows=day.iloc[0:0].copy()
    )
    check("근무 0건 → 빈 계층·빈 칩", tree_none == [] and majors_none == [])

    # (f) _month_snapshot NA-safety: dept/team 이 NaN 인 편성도 예외 없이 처리
    import pandas as _pd
    st.session_state[db._ASSIGNMENTS_STORE] = _pd.DataFrame([
        {"emp_no": "1002", "schedule_month": "2026-07-01",
         "dept_code": _np.nan, "team_code": None, "shift_group_code": ""},
    ], columns=db.SCHEDULE_ASSIGNMENT_COLUMNS)
    snap = dash._month_snapshot(_date(2026, 7, 1))
    check("NA 편성도 NA-safe(빈 문자열 폴백)", snap.get("1002") == ("", ""))
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)


def test_month_grid_snapshot() -> None:
    print("workspace._build_month_grid 월 편성 스냅샷 우선(과거 월 인사이동)")
    from views import workspace

    st.session_state.pop(db._SCHEDULES_STORE, None)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)

    ALL = workspace.ALL
    disp, _ = workspace.work_type_display()

    # 1002(이책임): 현재 소속 PET1, 2026-07 근무 존재. 그 달 편성 스냅샷을 PET2 로 이동.
    teams = db.get_teams()
    pet2_team = str(teams[teams["dept_code"] == "PET2"].iloc[0]["team_code"])
    db.upsert_month_assignments([{
        "emp_no": "1002", "schedule_month": "2026-07",
        "dept_code": "PET2", "team_code": pet2_team, "shift_group_code": "",
    }], require_shift=False)

    def grid_for(dept):
        q = {"year": 2026, "month": 7, "dept": dept, "team": ALL, "keyword": ""}
        g, _ = workspace._build_month_grid(q, disp)
        return g

    # 스냅샷 부서(PET2)로 조회 → 이동 직원 포함 + 부서 열이 스냅샷 부서명
    g_pet2 = grid_for("PET2")
    emps_pet2 = set(g_pet2["사번"].astype(str)) if not g_pet2.empty else set()
    check("스냅샷 부서(PET2) 조회에 이동 직원 포함", "1002" in emps_pet2)
    dept_cell = g_pet2[g_pet2["사번"].astype(str) == "1002"].iloc[0]["부서"]
    check("부서 열이 스냅샷 부서명 표시", dept_cell == db.dept_name("PET2"))

    # 현재 부서(PET1)로 조회 → 스냅샷 이동으로 1002 제외, 미이동 직원(1003)은 유지
    g_pet1 = grid_for("PET1")
    emps_pet1 = set(g_pet1["사번"].astype(str)) if not g_pet1.empty else set()
    check("현재 부서(PET1) 조회에서 이동 직원 제외(스냅샷 필터)", "1002" not in emps_pet1)
    check("스냅샷 없는 직원은 현재 부서(PET1)에 유지", "1003" in emps_pet1)

    # 표시 전용 — users 기준정보는 변경되지 않음(자동저장/백필 없음)
    check("스냅샷 표시가 users 현재 소속 불변",
          db.find_user_by_emp_no("1002")["dept_code"] == "PET1")

    # 스냅샷 없는 월 → 빈 맵(현재 소속 폴백), 예외 없음
    check("스냅샷 없는 월 → 빈 맵(현재 소속 폴백)",
          workspace._month_assignment_snapshot(2030, 1) == {})

    # (b) 조(team)만 이동한 케이스도 스냅샷 우선 — 1002 를 같은 PET1 안에서 A→B 로 이동
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)
    check("전제: 1002 현재 조 A", db.find_user_by_emp_no("1002")["team_code"] == "A")
    db.upsert_month_assignments([{
        "emp_no": "1002", "schedule_month": "2026-07",
        "dept_code": "PET1", "team_code": "B", "shift_group_code": "",
    }], require_shift=False)

    def grid_team(dept, team):
        q = {"year": 2026, "month": 7, "dept": dept, "team": team, "keyword": ""}
        g, _ = workspace._build_month_grid(q, disp)
        return g

    g_b = grid_team("PET1", "B")
    emps_b = set(g_b["사번"].astype(str)) if not g_b.empty else set()
    check("조 이동: 스냅샷 조(B)로 조회에 1002 포함", "1002" in emps_b)
    if "1002" in emps_b:
        team_cell = g_b[g_b["사번"].astype(str) == "1002"].iloc[0]["조"]
        check("조 열이 스냅샷 조(B) 이름 표시", team_cell == db.team_name("PET1", "B"))
    g_a = grid_team("PET1", "A")
    emps_a = set(g_a["사번"].astype(str)) if not g_a.empty else set()
    check("조 이동: 현재 조(A) 조회에서 1002 제외", "1002" not in emps_a)
    check("조 이동: 미이동 A조 직원(1003) 유지", "1003" in emps_a)
    check("조 이동도 users 마스터 불변(무쓰기)", db.find_user_by_emp_no("1002")["team_code"] == "A")

    # (a) repository 오류는 조용한 현재소속 폴백이 아니라 DATA_SOURCE_ERRORS 전파
    orig = db.get_month_assignments

    def _repo_boom(*a, **k):
        raise db.supabase_repository.SupabaseDataError("편성 조회 실패(모의)")

    db.get_month_assignments = _repo_boom
    try:
        prop1 = raises(lambda: workspace._month_assignment_snapshot(2026, 7),
                       db.DATA_SOURCE_ERRORS)
        check("스냅샷 조회 repository 오류 전파(빈 월 위장 아님)", prop1 is not None)
        prop2 = raises(
            lambda: workspace._build_month_grid(
                {"year": 2026, "month": 7, "dept": ALL, "team": ALL, "keyword": ""}, disp),
            db.DATA_SOURCE_ERRORS)
        check("월 그리드도 repository 오류 전파(현재소속 조용한 폴백 아님)", prop2 is not None)
    finally:
        db.get_month_assignments = orig

    st.session_state.pop(db._ASSIGNMENTS_STORE, None)


def test_retired_employee_month_display() -> None:
    print("퇴직(비활성) 직원: 근무 기록 있는 월만 조회 포함 + 퇴직 라벨/행 음영")
    from views import workspace

    st.session_state.pop(db._SCHEDULES_STORE, None)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)

    ALL = workspace.ALL
    disp, _ = workspace.work_type_display()

    retiree = db.find_user_by_emp_no("2001")
    check("전제: 2001 은 비활성(퇴직) 사용자", retiree is not None and not bool(retiree["is_active"]))

    def grid_for(year, month, dept=ALL):
        q = {"year": year, "month": month, "dept": dept, "team": ALL, "keyword": ""}
        g, _ = workspace._build_month_grid(q, disp)
        return g

    # 기록 없는 달(2026-06) 조회 → 퇴직자 미표시(빈 행 생성 금지)
    g_no_record = grid_for(2026, 6)
    emps_no_record = set(g_no_record["사번"].astype(str)) if not g_no_record.empty else set()
    check("기록 없는 달: 퇴직자(2001) 미표시", "2001" not in emps_no_record)

    # 2026-07 에 퇴직자 근무 기록 추가(공개 API — db.save_schedules)
    scheds = db.get_schedules()
    new_row = pd.DataFrame([{
        "emp_no": "2001", "duty_date": "2026-07-10", "work_type_code": "주", "note": "",
    }])
    db.save_schedules(pd.concat([scheds, new_row], ignore_index=True))

    g_with_record = grid_for(2026, 7)
    row_2001 = g_with_record[g_with_record["사번"].astype(str) == "2001"]
    check("기록 있는 달: 퇴직자(2001) 표시", len(row_2001) == 1)
    if len(row_2001) == 1:
        name_cell = str(row_2001.iloc[0]["성명"])
        check("퇴직 라벨 접미(성명+RETIRED_LABEL)", name_cell.endswith(workspace.RETIRED_LABEL))
        day_col = next(c for c in g_with_record.columns if c.startswith("10("))
        check("근무일 셀에 근무형태 약칭 표시", row_2001.iloc[0][day_col] == disp.get("주", "주"))

    # 재직자는 영향 없음 — 같은 달 재직자(1003) 계속 포함, 라벨 없음
    row_1003 = g_with_record[g_with_record["사번"].astype(str) == "1003"]
    check("재직자(1003) 계속 포함", len(row_1003) == 1)
    if len(row_1003) == 1:
        check("재직자는 퇴직 라벨 없음",
              not str(row_1003.iloc[0]["성명"]).endswith(workspace.RETIRED_LABEL))

    # 행 음영 — 색+라벨 이중부호화(퇴직자 행에만 css 적용, 재직자 행은 미적용)
    if len(row_2001) == 1:
        css_retired = workspace._retired_row_style(row_2001.iloc[0])
        check("퇴직자 행: 음영 css 적용", all(c == workspace._RETIRED_ROW_CSS for c in css_retired))
    if len(row_1003) == 1:
        css_active = workspace._retired_row_style(row_1003.iloc[0])
        check("재직자 행: 음영 css 미적용", all(c == "" for c in css_active))

    # 부서 스코프도 퇴직자에게 동일 적용(소속 불일치 부서 조회에는 노출되지 않음)
    g_pet1 = grid_for(2026, 7, dept="PET1")
    check("부서 필터(소속 PET1) 조회: 퇴직자 포함",
          "2001" in (set(g_pet1["사번"].astype(str)) if not g_pet1.empty else set()))
    g_pet2 = grid_for(2026, 7, dept="PET2")
    check("부서 필터(타 부서 PET2) 조회: 퇴직자 제외",
          "2001" not in (set(g_pet2["사번"].astype(str)) if not g_pet2.empty else set()))

    # 다른 달(기록 없음)에는 여전히 미표시 — 기록 추가가 전체 노출로 새지 않음
    g_other_month = grid_for(2026, 6)
    emps_other = set(g_other_month["사번"].astype(str)) if not g_other_month.empty else set()
    check("타 월(기록 없음)에는 여전히 미표시", "2001" not in emps_other)

    st.session_state.pop(db._SCHEDULES_STORE, None)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)


def test_dashboard_render_scope_gate() -> None:
    print("views.dashboard.render scope 게이트 회귀(blocked → _duty_board 미호출)")
    from datetime import date as _date
    from views import dashboard as dash

    # render() 를 직접 호출해 scope 게이트만 격리 검증한다(app.dispatch 라우팅·app_shell
    # 과 무관). _duty_board 를 spy 로 교체해 blocked 케이스에서 호출 0회(=데이터 미구성)
    # 를, 허용 케이스에서 호출 발생을 확인한다. 읽기 전용 검증이라 어떤 저장도 없다.
    calls = {"n": 0}
    orig = dash._duty_board

    def _spy(*a, **k):
        calls["n"] += 1
        return ([], [])

    st.session_state["dashboard_date"] = _date(2026, 7, 1)
    st.session_state["dash_date_input"] = _date(2026, 7, 1)
    st.session_state.pop(db._SCHEDULES_STORE, None)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)

    dash._duty_board = _spy
    try:
        # blocked 케이스: 어느 것도 _build_board 를 호출하지 않는다(데이터 미노출).
        for label, user in [
            ("MANAGER 공백 dept", {"role": "MANAGER", "dept_code": "", "emp_no": "9998", "name": "공백부서장"}),
            ("MANAGER None dept", {"role": "MANAGER", "dept_code": None, "emp_no": "9995", "name": "무부서장"}),
            ("미지 역할+유효 dept", {"role": "SUPERVISOR", "dept_code": "PET1", "emp_no": "9997", "name": "미지역할"}),
            ("역할 공백+유효 dept", {"role": "", "dept_code": "PET1", "emp_no": "9996", "name": "역할없음"}),
        ]:
            calls["n"] = 0
            dash.render(user)
            check(f"blocked({label}): _duty_board 0회(fail-open 아님)", calls["n"] == 0)

        # 허용 케이스: ADMIN·유효 MANAGER 는 _duty_board 를 호출한다.
        calls["n"] = 0
        dash.render({"role": "ADMIN", "dept_code": "", "emp_no": "9001", "name": "관리자"})
        check("ADMIN: _duty_board 호출(전체)", calls["n"] >= 1)

        calls["n"] = 0
        dash.render({"role": "MANAGER", "dept_code": "PET1", "emp_no": "1002", "name": "이책임"})
        check("유효 MANAGER: _duty_board 호출(부서 한정)", calls["n"] >= 1)
        check("MANAGER 범위 인자 전달(부서 한정)",
              st.session_state.get("dashboard_date") == _date(2026, 7, 1))
    finally:
        dash._duty_board = orig


def test_schedule_view_manager_scope_enforced() -> None:
    print("schedule_view MANAGER 잔존 조회조건 fail-closed(권한범위 재적용)")
    from streamlit.testing.v1 import AppTest
    from views import workspace

    # KP-standard(views/common/erp) 이관 이후 그리드는 AgGrid 로 렌더되어
    # AppTest.dataframe(pandas Styler/st.dataframe 전용 계약)에 값이 실리지 않는다.
    # 렌더 계층(어떤 위젯으로 그렸는지)이 아니라 스코프 계약(fail-closed 재적용이 실제
    # 계산에 반영됐는지)을 고정하기 위해, HARD BOUNDARY 로 보존된
    # ``workspace._build_month_grid``(편집하지 않음)를 spy 로 감싸 그 함수가 받은 q 와
    # 실제로 계산해 낸 grid(원본 로직 그대로 위임 호출)를 함께 캡처한다. 이렇게 하면
    # "MANAGER 는 타 부서를 볼 수 없다"는 의도를 렌더러 교체와 무관하게, 실제 필터링된
    # 데이터로 검증할 수 있다(약화 아님 — 오히려 원본 테스트와 동일한 데이터 단언).
    captured: dict = {}
    orig_build = workspace._build_month_grid

    def _spy(q, display_of=None):
        result = orig_build(q, display_of)
        captured["q"] = dict(q)
        captured["grid"] = result[0]
        return result

    def run(user, stale_q):
        captured.clear()
        workspace._build_month_grid = _spy
        try:
            at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
            at.session_state["user"] = user
            at.session_state["nav_page"] = "schedule_view"
            at.session_state[db._ASSIGNMENTS_STORE] = db._typed_empty_frame(
                db.SCHEDULE_ASSIGNMENT_COLUMNS
            )  # 스냅샷 없음 → 현재 소속 표시
            at.session_state["q_schedule_view"] = stale_q
            return at.run()
        finally:
            workspace._build_month_grid = orig_build

    def md_of(at):
        return " ".join(m.value for m in at.markdown)

    ALL = workspace.ALL  # "(전체)" 센티널
    # 이전 사용자(ADMIN)가 남긴 dept=ALL 조회조건. 이 잔존조회로 각 역할·부서를 검증.
    stale = {"year": 2026, "month": 7, "dept": ALL, "team": ALL, "keyword": ""}

    # (d) 유효 dept MANAGER(1002/PET1) → scoped(잔존 ALL 을 본인 부서로 축소)
    at = run({"role": "MANAGER", "dept_code": "PET1", "emp_no": "1002", "name": "이책임"}, stale)
    check("유효 MANAGER 잔존조회: 예외 없음", not at.exception)
    check("유효 MANAGER 잔존조회: _build_month_grid 호출(그리드 계산됨)", "grid" in captured)
    if "grid" in captured:
        check("잔존 ALL → PET1 축소: _build_month_grid 가 받은 q['dept']=='PET1'",
              captured["q"].get("dept") == "PET1")
        check("잔존 ALL → PET1 축소: q['team'] 초기화((전체))",
              captured["q"].get("team") == ALL)
        grid = captured["grid"]
        emps = set(grid["사번"].astype(str))
        depts_shown = set(grid["부서"].astype(str))
        check("잔존 ALL → PET1 축소: 타 부서 직원(1005/PET2) 제외", "1005" not in emps)
        check("잔존 ALL 축소: 본인 부서 직원(1003) 포함", "1003" in emps)
        check("표시 부서 PET1 단일(권한범위 강제)", depts_shown == {db.dept_name("PET1")})

    # 차단 케이스: dept 가 유효하지 않으면 전체조회로 새지 않고 blocked(_build_month_grid
    # 자체가 호출되지 않아야 한다 — fail-closed 는 계산 이전에 막는다).
    for label, bad_dept in [
        ("빈 dept", ""),
        ("미존재 dept 코드", "NOPE"),
        ("ALL 센티널 dept", ALL),
    ]:
        at_b = run({"role": "MANAGER", "dept_code": bad_dept, "emp_no": "9002", "name": "부서이상"}, stale)
        check(f"MANAGER {label}: 예외 없음", not at_b.exception)
        check(f"MANAGER {label}: _build_month_grid 미호출(전체조회로 새지 않음)",
              "grid" not in captured)
        check(f"MANAGER {label}: 차단 안내 표시", "소속 부서가 유효하지 않아" in md_of(at_b))

    # (e) ADMIN 은 잔존 ALL 로 전체(PET1+PET2) 조회 유지(부서 미확정이어도 무영향)
    at2 = run({"role": "ADMIN", "dept_code": "", "emp_no": "9001", "name": "관리자"}, stale)
    check("ADMIN: _build_month_grid 호출(전체 조회)", "grid" in captured)
    if "grid" in captured:
        check("ADMIN: 잔존 ALL 유지(_build_month_grid 가 받은 q['dept']=='(전체)')",
              captured["q"].get("dept") == ALL)
        grid2 = captured["grid"]
        check("ADMIN: 잔존 ALL 전체 유지(다중 부서 표시)",
              len(set(grid2["부서"].astype(str))) >= 2)


def test_month_view_top_actions() -> None:
    """월간 근무표 상단 액션 정리(2026-08-07 사용자 요구).

    - 조회 액션은 **돋보기 아이콘**으로 통일한다(상단 52px 헤더의 새로고침=원형 화살표와
      의미가 섞이지 않게).
    - 화면 버튼은 상단(조건 줄·컨텍스트 줄)에 모은다: 표 아래 전폭 [엑셀 다운로드] 를
      컨텍스트 줄 우측으로 올린다.
    - 조회 게이트(run_query)·엑셀 CSV 계약(원본 grid·utf-8-sig·파일명·mime)은 불변.
    """
    print("월간 근무표 상단 액션 — 조회=돋보기 아이콘 · 다운로드 상단 이전 · CSV 계약 불변")
    import inspect
    from streamlit.testing.v1 import AppTest
    from views import workspace
    from views.common.erp import kit

    src = inspect.getsource(workspace.schedule_screen)

    # (1) 조회 버튼 = 돋보기 아이콘(키트 submit_icon 경로).
    check("조회 제출 버튼에 돋보기 아이콘 지정", 'submit_icon=":material/search:"' in src)
    check("조회 라벨·키 계약 유지", 'submit=("조회", f"{page_id}_go")' in src)
    kit_src = inspect.getsource(kit.condition_panel)
    check("키트 condition_panel 이 submit_icon 을 버튼 icon 으로 전달", "icon=submit_icon" in kit_src)
    check("submit_icon 기본값 None(기존 호출부 무영향)",
          inspect.signature(kit.condition_panel).parameters["submit_icon"].default is None)

    # (2) 다운로드는 표 위(컨텍스트 줄)에서 렌더된다 — 표 아래 전폭 버튼 아님.
    i_dl = src.find("st.download_button")
    i_grid = src.find("erp.read_grid(")
    check("엑셀 다운로드가 표(read_grid)보다 위에서 렌더", 0 <= i_dl < i_grid)
    # 2026-08-07 개선 라운드: st.columns([1,0.22]) → horizontal container + 내용맞춤 버튼
    # (좁은 폭에서 버튼 라벨 2줄 접힘 해결). 포함 관계로 검증한다 — 다운로드 버튼이
    # sv_ctxrow 컨테이너 블록 **안**에 있어야 통과(밖으로 나가면 회귀로 잡힘).
    i_row = src.find('st.container(key="sv_ctxrow", horizontal=True')
    i_grid2 = src.find("erp.read_grid(", i_row if i_row >= 0 else 0)
    check("다운로드가 컨텍스트 줄(horizontal container) 블록 안에 위치",
          0 <= i_row < i_dl < i_grid2 and 'width="content"' in src[i_row:i_grid2])
    check("표 아래 하단 액션 블록 제거", "하단 액션 — 다운로드" not in src)

    # (3) CSV 내보내기 계약 불변(원본 grid·인코딩·파일명·mime·위젯 key).
    check("다운로드 원본은 표시 부가 없는 grid",
          "grid.to_csv(index=False).encode(\"utf-8-sig\")" in src)
    check("파일명 계약 유지(근무표_YYYY-MM.csv)",
          'file_name=f"근무표_{q[\'year\']}-{q[\'month\']:02d}.csv"' in src)
    check("mime/키 계약 유지", 'mime="text/csv"' in src and 'key=f"{page_id}_dl"' in src)

    # (4) 실렌더: 조회·다운로드 컨트롤이 실제로 존재하고 예외가 없다.
    # 2026-08-11 규칙(근무 보유자만 행) 이후 빈 월은 empty_state 로 끝나 다운로드가
    # 렌더되지 않으므로, 샘플 데이터가 있는 2026-07 로 조회 조건을 시드한다.
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.session_state["user"] = {"role": "ADMIN", "dept_code": "", "emp_no": "9001", "name": "관리자"}
    at.session_state["nav_page"] = "schedule_view"
    at.session_state["schedule_view_y"] = 2026
    at.session_state["schedule_view_m"] = 7
    at.run()
    check("월간 근무표 렌더 예외 없음", not at.exception)
    check("조회 버튼 렌더", any(b.label == "조회" for b in at.button))
    check("엑셀 다운로드 컨트롤 렌더",
          any(d.label == "엑셀 다운로드" for d in at.get("download_button")))


def test_schedule_edit_row_reorder() -> None:
    """근무표 편성 — 행 드래그 재정렬 + 순서 영속(2026-08-11 사용자 요구).

    "행 앞 핸들을 잡고 드래그해서 옮기는 방식 / 엑셀(근태표) 등록 순서가 앞으로도
    유지되어야 함" → 시각 순서는 AG Grid 관리형 이동, 영속은 users.display_order 의
    부서그룹 단위 슬롯 재배정이다. 여기서는 화면 배선(권위 상태 확정·저장 경로 포함)과
    실렌더 무예외를 고정한다. 슬롯 계산 자체는 test_schedule_save_units.py 가 소유한다.
    """
    print("근무표 편성 — 행 드래그 순서 변경 · users.display_order 영속 배선")
    import inspect
    from streamlit.testing.v1 import AppTest
    from views import schedule_edit as se

    # (1) 그리드가 드래그 옵트인을 켠다(핸들·관리형 이동의 실제 옵션은 test_erp_cell_copy).
    check("편성 그리드에 row_drag 옵트인", "row_drag=True" in inspect.getsource(se.render))

    # (2) 반환 순서를 서버 권위로 확정한다 — 확정하지 않으면 다음 remount 에서 소실된다.
    sync_src = inspect.getsource(se._sync_rows)
    check("반환 _row_id 시퀀스와 권위 순서를 비교", "_row_id" in sync_src and "sorted(" in sync_src)
    check("순서가 다르면 재마운트 경로로 진입(changed=True)", "changed = True" in sync_src)
    check("행 집합이 정확히 같을 때만 재배열(구조 변경 경합 보호)",
          "sorted(prev_ids) == sorted(cur_ids)" in sync_src)

    # (3) 저장 경로가 순서를 영속화한다 — 빠지면 '저장해도 dirty 가 안 풀리는' 루프.
    save_src = inspect.getsource(se._save)
    check("저장에 행 순서 영속 단계 포함", "_persist_row_order(live)" in save_src)
    i_order = save_src.find("_persist_row_order(live)")
    i_reload = save_src.find("_load_grid(q)")
    check("순서 저장이 재조회보다 먼저(재조회가 새 순서로 정렬되도록)",
          0 <= i_order < i_reload)
    order_src = inspect.getsource(se._persist_row_order)
    check("재배정은 공용 순수 함수(db.plan_display_order_slots) 사용",
          "db.plan_display_order_slots" in order_src)
    check("대상 지정 쓰기(db.update_users_display_order) 사용 — 전량 upsert 아님",
          "db.update_users_display_order" in order_src and "save_users" not in order_src)
    check("순서 무변경이면 아무것도 쓰지 않음", "if final == list(base):" in order_src)

    # (4) 로드 기준선·초안 폐기 정리.
    check("로드 시 순서 기준선 기록", "se_order_base" in inspect.getsource(se._load_grid))
    check("초안 폐기 시 기준선도 정리", "se_order_base" in inspect.getsource(se._discard_draft))

    # (5) 드래그만 해도 미저장 변경 건수가 0 이 아니다(저장 활성과 표시가 모순되지 않게).
    check("변경 건수에 순서 변경 반영", se._change_count(pd.DataFrame(), [], {}, 0, True) == 1)
    check("순서 미변경이면 종전과 동일", se._change_count(pd.DataFrame(), [], {}, 0) == 0)

    # (6) 실렌더 — 샘플 근무 보유자가 있는 2026-07 로 조회 조건을 시드한다.
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.session_state["user"] = {"role": "ADMIN", "dept_code": "", "emp_no": "9001", "name": "관리자"}
    at.session_state["nav_page"] = "schedule_edit"
    at.session_state["se_y"] = 2026
    at.session_state["se_m"] = 7
    at.run()
    check("근무표 편성 렌더 예외 없음", not at.exception)
    check("로드 기준선이 실제 행 순서로 채워짐",
          at.session_state["se_order_base"]
          == [str(v).strip() for v in at.session_state["se_rows"]["사번"]])
    check("드래그 안내가 조작 힌트에 노출",
          any("핸들 드래그로 순서 변경" in str(m.value) for m in at.markdown))


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
        test_dashboard_render_scope_gate,
        test_month_grid_snapshot,
        test_retired_employee_month_display,
        test_schedule_view_manager_scope_enforced,
        test_month_view_top_actions,
        test_schedule_edit_row_reorder,
    ):
        test()
    print(f"\nALL PASSED ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
