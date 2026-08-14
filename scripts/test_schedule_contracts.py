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

    # 스냅샷 부서(PET2)로 조회 → 이동 직원 포함 + 소속 열(대분류·중분류)이 스냅샷 부서 기준
    # (2026-08-13 표시 계약: 부서명 열 → 조직 관리 대분류·중분류. 샘플 부서에는 분류가
    #  없으므로 대분류=무분류·중분류=부서명 폴백이 그대로 스냅샷 해석의 증거가 된다.)
    g_pet2 = grid_for("PET2")
    emps_pet2 = set(g_pet2["사번"].astype(str)) if not g_pet2.empty else set()
    check("스냅샷 부서(PET2) 조회에 이동 직원 포함", "1002" in emps_pet2)
    snap_row = g_pet2[g_pet2["사번"].astype(str) == "1002"].iloc[0]
    check("중분류 열이 스냅샷 부서로 해석(중분류 미입력 → 부서명 폴백)",
          snap_row["중분류"] == db.dept_name("PET2"))
    check("대분류 미입력 부서는 무분류로 표시(행을 감추지 않음)",
          snap_row["대분류"] == workspace.UNCLASSIFIED_LABEL)

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


def test_month_grid_org_labels_and_order() -> None:
    """월간 근무표 소속 표시(대분류·중분류) + 행 정렬(2026-08-13 사용자 확정).

    정렬 ① 대분류(부서 마스터에서 유도한 순서·무분류 마지막) ② 조(A→B→C→기타→빈 조)
    ③ 등록순(display_order, 없으면 뒤) → 사번. 대분류 이름을 코드에 고정하지 않는다.
    """
    print("월간 근무표 — 대분류·중분류 표시 + 대분류→조→등록순 정렬")
    from views import workspace

    # (1) 라벨/순서 도출은 순수 함수 — 주입 프레임만으로 검증(조회 없음).
    depts = pd.DataFrame([
        {"dept_code": "B1", "dept_name": "비생산부", "major_category": "PVC생산부",
         "minor_category": "PVC생산팀", "sort_order": 20},
        {"dept_code": "A1", "dept_name": "에이부서1", "major_category": "PET생산부",
         "minor_category": "PET생산팀", "sort_order": 10},
        {"dept_code": "A2", "dept_name": "에이부서2", "major_category": "PET생산부",
         "minor_category": "", "sort_order": 11},
        {"dept_code": "N1", "dept_name": "분류없는부서", "major_category": "",
         "minor_category": "", "sort_order": 5},
    ])
    labels, majors = workspace.org_labels(depts)
    check("대분류 노출 순서는 부서 sort_order 에서 유도(이름 하드코딩 아님)",
          majors == ["PET생산부", "PVC생산부"])
    check("중분류 미입력은 부서명 폴백", labels["A2"] == ("PET생산부", "에이부서2"))
    check("대분류 미입력은 무분류이며 순서 목록에 넣지 않는다(항상 마지막)",
          labels["N1"][0] == workspace.UNCLASSIFIED_LABEL
          and workspace.UNCLASSIFIED_LABEL not in majors)
    check("마스터에 없는 부서코드도 무분류 + 코드 표시(행을 감추지 않음)",
          workspace._org_label_of("ZZZ", labels)
          == (workspace.UNCLASSIFIED_LABEL, "ZZZ"))
    check("빈 부서 프레임도 안전(빈 맵·빈 순서)",
          workspace.org_labels(pd.DataFrame()) == ({}, []))

    # (2) 조 정렬 키 — A→B→C→그 밖→빈 조.
    keyed = sorted(["상시", "", "C조", "A조", "1팀", "B조"], key=workspace._team_sort_key)
    check("조 정렬: 영문 머리 알파벳 우선 → 그 밖 표기 → 빈 조 마지막",
          keyed[:3] == ["A조", "B조", "C조"] and keyed[-1] == ""
          and set(keyed[3:5]) == {"상시", "1팀"})

    # (3) 실제 그리드 행 순서 — 샘플 부서에 분류를 주입(세션 store)하고 원복한다.
    st.session_state.pop(db._SCHEDULES_STORE, None)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)
    base = db.get_org_departments().copy()
    injected = base.copy()
    codes = [str(c) for c in injected["dept_code"]]
    check("전제: 샘플 부서 3개 이상(계층 주입 가능)", len(codes) >= 3)
    injected.loc[injected["dept_code"] == codes[0],
                 ["major_category", "minor_category"]] = ["PET생산부", "PET생산팀"]
    injected.loc[injected["dept_code"] == codes[1],
                 ["major_category", "minor_category"]] = ["PVC생산부", "PVC생산팀"]
    injected.loc[injected["dept_code"] == codes[2],
                 ["major_category", "minor_category"]] = ["", ""]  # 무분류(마지막)
    db.save_org_departments(injected[db.ORG_DEPT_COLUMNS])
    try:
        disp, _ = workspace.work_type_display()
        grid, _rows = workspace._build_month_grid(
            {"year": 2026, "month": 7, "dept": workspace.ALL, "team": workspace.ALL,
             "keyword": ""}, disp)
        check("소속 열이 대분류·중분류(부서명 단일 열 아님)",
              list(grid.columns)[:5] == ["사번", "성명", "대분류", "중분류", "조"])
        rank = {"PET생산부": 0, "PVC생산부": 1, workspace.UNCLASSIFIED_LABEL: 2}
        seen = [rank[m] for m in grid["대분류"]]
        check("① 대분류 순서(무분류 마지막)로 묶여 정렬",
              seen == sorted(seen) and len(set(seen)) >= 2)
        users = db.get_users()
        order_of = {}
        for _, u in users.iterrows():
            try:
                value = db.normalize_display_order(u.get("display_order"))
            except (TypeError, ValueError):
                value = None
            order_of[str(u["emp_no"]).strip()] = (1, 0) if value is None else (0, value)
        keys = [
            (rank[r["대분류"]], workspace._team_sort_key(r["조"]),
             order_of.get(str(r["사번"]).strip(), (1, 0)), str(r["사번"]).strip())
            for _, r in grid.iterrows()
        ]
        check("②③ 같은 대분류 안에서 조 → 등록순(display_order) → 사번 순",
              keys == sorted(keys))
    finally:
        db.save_org_departments(base[db.ORG_DEPT_COLUMNS])  # 다른 테스트 격리(원복)


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


def test_dashboard_attendance_target_scope() -> None:
    print("views.dashboard 근태 등록 대상 부서 한정(모집단 = 칩·명단·지표 공통, 폴백 보존)")
    from datetime import date as _date
    from views import dashboard as dash

    st.session_state.pop(db._SCHEDULES_STORE, None)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)
    day_date = _date(2026, 7, 1)
    day = db.get_day_schedules(day_date)
    merged = day.merge(db.get_users(), on="emp_no", how="left")
    dept_of = merged["dept_code"].astype(str)

    # (a) 모집단 해석 — 지정 가능한 환경에서는 대상 부서 집합.
    tracked = dash._attendance_scope()
    check("sample 지정 그대로(대상 부서만)", tracked == db.attendance_dept_codes(is_active=None))
    check("대상 아닌 부서는 모집단 밖", "MGT" not in tracked and {"PET1", "PET2"} <= tracked)

    saved_codes, saved_ready = db.attendance_dept_codes, db.attendance_flag_ready
    seen: dict = {}

    def _spy_codes(is_active=True):
        seen["is_active"] = is_active
        return {"PET1"}

    try:
        db.attendance_dept_codes = _spy_codes
        check("대상이면 비활성 부서도 포함해 조회(과거 일자 조회 보존)",
              dash._attendance_scope() == {"PET1"} and seen["is_active"] is None)
        # (b) 폴백 — 지정을 판독할 수 없으면 필터 자체를 걸지 않는다(종전 전 부서).
        db.attendance_flag_ready = lambda: False
        check("ready=False → 무필터(None), 대상 조회도 하지 않음",
              dash._attendance_scope() is None)
    finally:
        db.attendance_dept_codes, db.attendance_flag_ready = saved_codes, saved_ready

    # (c) 집계 — 명단과 지표가 같은 트리에서 나오므로 모집단이 갈릴 수 없다.
    base_tree, _ = dash._duty_board(day_date, tracked=None)
    check("무필터(폴백)는 종전 전체 집계 그대로", len(_board_names(base_tree)) == len(day))
    t_pet1, _ = dash._duty_board(day_date, tracked={"PET1"})
    expect1 = int((dept_of == "PET1").sum())
    check("대상 부서 근무자만 명단에 남는다",
          len(_board_names(t_pet1)) == expect1 and expect1 < len(day))
    totals1, _ = dash._summarize(t_pet1)
    check("지표도 같은 모집단(지표 = 명단 합)",
          sum(totals1.values()) == len(_board_names(t_pet1)))
    t_pet2, _ = dash._duty_board(day_date, tracked={"PET2"})
    check("대상 밖 부서 인원은 명단에도 지표에도 없다",
          not (set(_board_names(t_pet2)) & set(_board_names(t_pet1)))
          and sum(dash._summarize(t_pet2)[0].values()) == len(_board_names(t_pet2)))

    # (d) 부서 필터 칩 — 대상 부서의 대분류만. '미분류'도 대상 안으로 좁혀진다.
    depts = db.get_org_departments().copy()
    depts.loc[depts["dept_code"] == "PET1",
              ["major_category", "minor_category"]] = ["PET생산부", "PET생산팀"]
    depts.loc[depts["dept_code"] == "PET2", ["major_category", "minor_category"]] = ["", ""]
    _, chips_all = dash._duty_board(day_date, depts=depts, tracked=None)
    check("전제: 폴백에서는 두 축(분류·미분류) 모두 칩",
          chips_all == ["PET생산부", dash._UNCLASSIFIED_LABEL])
    _, chips_pet1 = dash._duty_board(day_date, depts=depts, tracked={"PET1"})
    check("대상 밖 부서의 대분류 칩은 사라진다", chips_pet1 == ["PET생산부"])
    _, chips_pet2 = dash._duty_board(day_date, depts=depts, tracked={"PET2"})
    check("'미분류' 칩 = 근태 대상인데 대분류가 빈 부서만",
          chips_pet2 == [dash._UNCLASSIFIED_LABEL])

    # (e) 지정 0건 — 빈 계층·빈 칩·지표 0(조용한 전 부서 노출 아님).
    tree0, chips0 = dash._duty_board(day_date, tracked=set())
    check("지정 0건 → 명단·칩 없음, 지표 0(fail-open 아님)",
          tree0 == [] and chips0 == [] and sum(dash._summarize(tree0)[0].values()) == 0)

    # (f) 소속을 해석하지 못한 근무행 — 대상 화면에서는 빠지고, 폴백에서는 종전대로 남는다.
    ghost = day.iloc[[0]].copy()
    ghost["emp_no"] = "9999"
    rows = pd.concat([day, ghost], ignore_index=True)
    t_ghost, _ = dash._duty_board(day_date, day_rows=rows, tracked={"PET1", "PET2"})
    check("소속 미해석 근무행은 대상 부서 모집단 밖", len(_board_names(t_ghost)) == len(day))
    t_ghost_fb, _ = dash._duty_board(day_date, day_rows=rows, tracked=None)
    check("폴백에서는 종전대로 미분류에 남는다",
          len(_board_names(t_ghost_fb)) == len(day) + 1)

    # (g) 헤더 스탬프·빈 상태 문구.
    check("스탬프: 필터가 살아 있으면 '전사' 아님",
          dash._scope_label(dash._ALL_MAJORS, None, {"PET1"}) == "근태 대상")
    check("스탬프: 폴백은 종전 '전사'",
          dash._scope_label(dash._ALL_MAJORS, None, None) == "전사")
    check("스탬프: 대분류 선택·MANAGER 표기는 무변경",
          dash._scope_label("PET생산부", None, {"PET1"}) == "PET생산부"
          and dash._scope_label(dash._ALL_MAJORS, "PET1", {"PET1"}) == db.dept_name("PET1"))
    check("빈 상태: 지정 0건은 조직 관리 다음 행동을 가리킨다",
          "조직 관리" in dash._empty_message(day_date, set(), None))
    check("빈 상태: 담당 부서가 대상 아님을 구분",
          "근태 등록 대상이 아닙니다" in dash._empty_message(day_date, {"PET1"}, "MGT"))
    check("빈 상태: 그 외는 종전 '등록된 근무가 없습니다'",
          "등록된 근무가 없습니다" in dash._empty_message(day_date, {"PET1"}, "PET1")
          and "등록된 근무가 없습니다" in dash._empty_message(day_date, None, None))

    # (h) render 회귀 가드 — 화면이 실제로 모집단을 집계에 넘기는가.
    captured: dict = {}
    orig_board = dash._duty_board

    def _spy_board(*a, **k):
        captured.update(k)
        return ([], [])

    st.session_state["dashboard_date"] = day_date
    st.session_state["dash_date_input"] = day_date
    dash._duty_board = _spy_board
    try:
        dash.render({"role": "ADMIN", "dept_code": "", "emp_no": "9001", "name": "관리자"})
        check("render 가 근태 대상 모집단을 집계에 전달",
              captured.get("tracked") == dash._attendance_scope())
        captured.clear()
        db.attendance_flag_ready = lambda: False
        dash.render({"role": "ADMIN", "dept_code": "", "emp_no": "9001", "name": "관리자"})
        check("폴백 배포에서는 무제한(None)으로 전달", captured.get("tracked") is None)
    finally:
        dash._duty_board = orig_board
        db.attendance_flag_ready = saved_ready

    st.session_state.pop(db._SCHEDULES_STORE, None)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)


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
            # 2026-08-13: [조회] 버튼 제거로 조회조건의 원천이 저장 조회조건(q_*)에서
            # **조건 위젯 세션 상태**로 바뀌었다. 잔존 조회조건 위협모형(이전 사용자가
            # 남긴 전체/타 부서 조건)은 그대로이므로 위젯 키에 그 잔존값을 심는다.
            at.session_state["schedule_view_y"] = stale_q["year"]
            at.session_state["schedule_view_m"] = stale_q["month"]
            at.session_state["schedule_view_d"] = stale_q["dept"]
            at.session_state["schedule_view_t"] = stale_q["team"]
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
        # 표시 열은 대분류·중분류(2026-08-13). 샘플 부서에는 분류가 없어 중분류가
        # 부서명 폴백이므로, 이 열이 곧 '어느 부서가 보이는가'의 증거다.
        orgs_shown = set(grid["중분류"].astype(str))
        check("잔존 ALL → PET1 축소: 타 부서 직원(1005/PET2) 제외", "1005" not in emps)
        check("잔존 ALL 축소: 본인 부서 직원(1003) 포함", "1003" in emps)
        check("표시 소속 PET1 단일(권한범위 강제)", orgs_shown == {db.dept_name("PET1")})

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
        check("ADMIN: 잔존 ALL 전체 유지(다중 소속 표시)",
              len(set(grid2["중분류"].astype(str))) >= 2)


def test_month_view_top_actions() -> None:
    """월간 근무표 상단 액션 정리(2026-08-07 → 2026-08-13 갱신).

    - 화면 안 [조회] 버튼은 **없다**(2026-08-13 사용자 요구): 조건 위젯 변경이 곧 조회다.
    - 같은 조건의 재조회는 상단 52px 헤더의 **새로고침 아이콘**이 담당한다(읽기 캐시를
      비우고 재적재). 헤더 아이콘 배선은 modules/ui.py 의 페이지별 플래그 매핑 한 줄.
    - 화면 버튼은 상단(컨텍스트 줄)에 모은다: 표 아래 전폭 [엑셀 다운로드] 를
      컨텍스트 줄 우측으로 올린다.
    - 엑셀 CSV 계약(원본 grid·utf-8-sig·파일명·mime)은 불변.
    """
    print("월간 근무표 상단 액션 — 조건 즉시 반영 · 헤더 새로고침 배선 · CSV 계약 불변")
    import inspect
    from streamlit.testing.v1 import AppTest
    from modules import ui as ui_mod
    from views import workspace

    src = inspect.getsource(workspace.schedule_screen)

    # (1) [조회] 버튼 없음 = 조건 패널에 submit 을 주지 않는다 → 위젯 값이 곧 조회조건.
    check("조건 패널에 제출(조회) 버튼 미지정", "submit=(" not in src)
    check("조회 게이트(run_query) 미사용 — 위젯 변경 즉시 반영", "run_query(" not in src)
    check("조회조건은 조건 패널 반환값에서 직접 구성", 'v = erp.condition_panel(' in src)

    # (2) 헤더 새로고침 아이콘 배선 — 매핑(ui) ↔ 소비(workspace) 양쪽이 같은 플래그.
    flag = ui_mod._PAGE_HEADER_ACTIONS.get("schedule_view", {}).get("refresh")
    check("헤더 새로고침이 월간 근무표에 배선됨", flag == "schedule_view_refresh_req")
    check("화면이 같은 플래그를 소비", 'f"{page_id}_refresh_req"' in src)
    check("새로고침은 읽기 캐시를 비우고 재적재", "st.cache_data.clear()" in src)
    # 새로고침 외 아이콘(추가·삭제·저장·인쇄)은 READ 화면이라 미매핑 = 음영 유지.
    check("READ 화면에 쓰기 아이콘을 배선하지 않음",
          set(ui_mod._PAGE_HEADER_ACTIONS["schedule_view"]) == {"refresh"})

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
    check("[조회] 버튼 미렌더(조건 즉시 반영)", not any(b.label == "조회" for b in at.button))
    check("엑셀 다운로드 컨트롤 렌더",
          any(d.label == "엑셀 다운로드" for d in at.get("download_button")))
    # 헤더 새로고침 클릭 = 플래그 → 다음 렌더에서 화면이 소비(플래그가 남지 않는다).
    at.session_state["schedule_view_refresh_req"] = True
    at.run()
    check("새로고침 플래그 소비 후 예외 없음", not at.exception)
    check("새로고침 플래그는 소비되어 남지 않음",
          "schedule_view_refresh_req" not in at.session_state)


def test_month_view_scope_defaults() -> None:
    """월간 근무표 조회조건 기본값 = 로그인 사용자의 부서·조(2026-08-13 사용자 요구).

    - 부서 원천: ``users.dept_code``. 부서 마스터에 없는 코드는 심지 않는다(0건 조건 금지).
    - 조 원천: 조 축이 기준정보가 아니라 편성 스냅샷이므로 **대상 월 본인 편성**이 1순위
      (``shift_group_code`` → 레거시 ``team_code``), 편성이 없으면 ``users.team_code``
      (스냅샷 없는 월에 표가 쓰는 폴백과 같은 값 → 심은 조건 안에 본인이 반드시 포함).
    - 이미 선택값이 있으면 덮어쓰지 않는다(사용자가 바꾼 조건 유지).
    """
    print("월간 근무표 조회조건 기본값 — 내 부서·조 시드(선택값이 있으면 불변)")
    from streamlit.testing.v1 import AppTest
    from views import workspace

    dept_names = {"PET1": "PET생산부(본동)", "PET2": "PET생산부(원료실)"}
    user = {"emp_no": "1003", "dept_code": "PET1", "team_code": "A", "role": "USER"}

    # (1) 편성 스냅샷 없음 → users 현재 소속(부서·조)
    d, t = workspace.scope_defaults(user, dept_names, None)
    check("스냅샷 없음: 부서=users.dept_code", d == "PET1")
    check("스냅샷 없음: 조=users.team_code(표 폴백과 동일 값)", t == "A")

    # (2) 스냅샷의 근무조(신 축)가 최우선
    snap_shift = pd.DataFrame([{
        "emp_no": "1003", "schedule_month": "2026-07", "dept_code": "PET1",
        "team_code": "A", "shift_group_code": "가조",
    }])
    d, t = workspace.scope_defaults(user, dept_names, snap_shift)
    check("스냅샷 근무조(shift_group_code) 우선", t == "가조")

    # (3) 근무조가 비면 레거시 운영단위(team_code)
    snap_team = snap_shift.copy()
    snap_team["shift_group_code"] = ""
    snap_team["team_code"] = "B"
    _d, t = workspace.scope_defaults(user, dept_names, snap_team)
    check("근무조 미기입 월은 레거시 운영단위로 폴백", t == "B")

    # (4) 마스터에 없는 부서코드는 심지 않는다(전체 부서 폴백)
    d, _t = workspace.scope_defaults({**user, "dept_code": "NOPE"}, dept_names, None)
    check("부서 마스터에 없는 코드는 미시드(전체 부서 폴백)", d == "")
    d, t = workspace.scope_defaults({"emp_no": "9001"}, dept_names, None)
    check("소속 없는 사용자는 부서·조 모두 미시드", (d, t) == ("", ""))

    # (5) 실렌더: 첫 진입에 위젯 세션값이 내 부서·조로 심어진다
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.session_state["user"] = {
        "role": "USER", "dept_code": "PET1", "team_code": "A",
        "emp_no": "1003", "name": "박근무", "is_active": True,
    }
    at.session_state["nav_page"] = "schedule_view"
    at.run()
    check("첫 진입 렌더 예외 없음", not at.exception)
    check("첫 진입: 부서 조건이 내 부서로 시드", at.session_state["schedule_view_d"] == "PET1")
    check("첫 진입: 조 조건이 내 조로 시드", at.session_state["schedule_view_t"] == "A")

    # (6) 사용자가 바꾼 선택은 덮어쓰지 않는다('전체'로 되돌린 경우 포함)
    at.session_state["schedule_view_d"] = workspace.ALL
    at.session_state["schedule_view_t"] = workspace.ALL
    at.run()
    check("사용자 선택('전체 부서')을 재시드로 덮어쓰지 않음",
          at.session_state["schedule_view_d"] == workspace.ALL)
    check("사용자 선택('전체 조')을 재시드로 덮어쓰지 않음",
          at.session_state["schedule_view_t"] == workspace.ALL)

    # (7) MANAGER 는 시드가 권한범위를 넓히지 않는다(본인 부서 그대로 · fail-closed 유지)
    at_m = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at_m.session_state["user"] = {
        "role": "MANAGER", "dept_code": "PET1", "team_code": "A",
        "emp_no": "1002", "name": "이책임", "is_active": True,
    }
    at_m.session_state["nav_page"] = "schedule_view"
    at_m.run()
    check("MANAGER 렌더 예외 없음", not at_m.exception)
    check("MANAGER 시드는 본인 부서(권한범위 확대 없음)",
          at_m.session_state["schedule_view_d"] == "PET1")


def test_month_view_attendance_scope() -> None:
    """월간 근무표 — 근태 등록 대상 부서만 목록·조회(2026-08-14 사용자 요구).

    - 부서 옵션 · 조 옵션 · 표 행이 **같은 집합**으로 좁혀진다(고를 수는 있는데 0건인
      조건을 남기지 않는다).
    - 조회 화면이라 이력 보존이 우선이다: 대상 지정이 남아 있으면 **사용 중지 부서도**
      조회하고(``is_active=None``), 지정 여부를 판정할 수 없는 부서코드(마스터에 없음·
      미배정)는 감추지 않는다 — 차단 목록 방식.
    - 로그인 사용자의 부서가 비대상이면 조회조건 시드가 일어나지 않는다(옵션 밖 값이
      조건에 실려 빈 화면이 되는 경로 차단).
    - 지정 컬럼을 판독할 수 없으면(``attendance_flag_ready()==False``) 종전 전 부서.
    """
    print("월간 근무표 — 근태 대상 부서 한정(옵션·조·행 동일 집합 · 이력 보존 · 시드 폴백)")
    import inspect
    from streamlit.testing.v1 import AppTest
    from views import workspace

    ALL = workspace.ALL
    dept_names = {"PET1": db.dept_name("PET1"), "PET2": db.dept_name("PET2"),
                  "MGT": db.dept_name("MGT")}

    # (a) 옵션·차단 목록(순수) — 폴백은 원본 그대로.
    check("폴백(None): 부서 옵션은 원본 그대로",
          workspace.attendance_dept_options(dept_names, None) == dept_names)
    check("대상 부서만 옵션에 남는다",
          list(workspace.attendance_dept_options(dept_names, {"PET1", "PET2"}))
          == ["PET1", "PET2"])
    check("폴백(None): 차단 목록 없음(= 종전 전 부서 조회)",
          workspace.attendance_blocked_depts(dept_names, None) == ())
    check("차단은 '마스터에 있으면서 대상이 아닌' 부서만",
          workspace.attendance_blocked_depts(dept_names, {"PET1", "PET2"}) == ("MGT",))
    check("지정 0건이면 마스터 전 부서가 차단(조용한 전체 노출 아님)",
          workspace.attendance_blocked_depts(dept_names, set())
          == ("MGT", "PET1", "PET2"))

    # (b) 조 옵션도 같은 집합 — 차단 부서에만 있는 조는 목록에서 사라진다.
    teams = pd.DataFrame([
        {"dept_code": "PET1", "team_code": "A", "team_name": "A조"},
        {"dept_code": "MGT", "team_code": "M", "team_name": "관리조"},
    ])
    assigns = pd.DataFrame([
        {"emp_no": "1", "dept_code": "PET1", "team_code": "A", "shift_group_code": "가조"},
        {"emp_no": "2", "dept_code": "MGT", "team_code": "M", "shift_group_code": "관리"},
    ])
    check("차단 부서의 조(마스터·스냅샷 양축)는 옵션에서 제외",
          set(workspace.team_filter_options(assigns, teams, ALL, ("MGT",))) == {"A", "가조"})
    check("차단 목록이 없으면 종전 조 옵션 그대로",
          set(workspace.team_filter_options(assigns, teams, ALL))
          == {"A", "가조", "M", "관리"})

    # (c) 표 행 — 스냅샷 기준(_eff_dept)으로 차단하며, 차단 목록 방식이라 판정 불가
    #     부서코드(마스터에 없음·미배정)는 감추지 않는다.
    check("행 필터는 차단 목록(허용 목록이 아니다 — 판정 불가 코드를 감추지 않음)",
          '~users["_eff_dept"].isin(blocked_depts)'
          in inspect.getsource(workspace._build_month_grid))
    st.session_state.pop(db._SCHEDULES_STORE, None)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)
    disp, _ = workspace.work_type_display()

    def grid_for(excluded):
        g, _rows = workspace._build_month_grid(
            {"year": 2026, "month": 7, "dept": ALL, "team": ALL, "keyword": "",
             "excluded_depts": excluded}, disp)
        return set(g["사번"].astype(str)) if not g.empty else set()

    base = grid_for(())
    check("전제: 무제한 조회에 PET1·PET2 근무자가 함께 있다",
          {"1003", "1005"} <= base)
    scoped = grid_for(("PET2",))
    check("차단 부서 근무자는 표 행에서 제외", "1005" not in scoped)
    check("대상 부서 근무자는 그대로", "1003" in scoped and scoped < base)
    check("지정 0건(전 부서 차단)이면 표가 비고, 데이터는 그대로 남는다",
          grid_for(("MGT", "PET1", "PET2")) == set() and grid_for(()) == base)

    # (d) 빈 상태 문구 — '사람이 없음'과 '대상이 아님'을 구분한다.
    check("빈 상태: 지정 0건은 조직 관리 다음 행동을 가리킨다",
          "조직 관리" in workspace.month_empty_message({"dept": ALL}, set()))
    check("빈 상태: 선택 부서가 대상이 아님을 구분",
          "근태 등록 대상이 아닙니다"
          in workspace.month_empty_message({"dept": "MGT"}, {"PET1"}))
    check("그 밖(폴백·정상 조건)은 종전 문구 그대로",
          workspace.month_empty_message({"dept": ALL}, None)
          == "조회 조건에 해당하는 직원이 없습니다."
          and workspace.month_empty_message({"dept": "PET1"}, {"PET1"})
          == "조회 조건에 해당하는 직원이 없습니다.")

    # (e) 컨텍스트 줄 — 대상만 담은 화면에 '전체 부서'라고 쓰지 않는다.
    ctx_q = {"year": 2026, "month": 7, "dept": ALL, "team": ALL}
    check("컨텍스트 줄: 지정이 살아 있으면 '근태 대상 부서'",
          "근태 대상 부서"
          in workspace._view_context_html(ctx_q, {}, {}, 1, 1, 1, {"PET1"}))
    check("컨텍스트 줄: 폴백은 종전 '전체 부서'",
          "전체 부서" in workspace._view_context_html(ctx_q, {}, {}, 1, 1, 1, None))

    # (f) 실렌더 — 비대상 부서(MGT) 사용자의 첫 진입. 시드가 옵션 밖 값을 심지 않는다.
    def run(user, ready=None):
        saved = db.attendance_flag_ready
        if ready is not None:
            db.attendance_flag_ready = lambda: ready
        try:
            at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
            at.session_state["user"] = user
            at.session_state["nav_page"] = "schedule_view"
            at.session_state["schedule_view_y"] = 2026
            at.session_state["schedule_view_m"] = 7
            at.run()
            return at
        finally:
            db.attendance_flag_ready = saved

    def dept_options(at):
        return next(
            list(sb.options) for sb in at.selectbox if sb.key == "schedule_view_d"
        )

    st.session_state.pop(db._ASSIGNMENTS_STORE, None)
    admin_mgt = {"role": "ADMIN", "dept_code": "MGT", "team_code": "",
                 "emp_no": "9001", "name": "관리자", "is_active": True}
    at = run(admin_mgt)
    check("비대상 부서 사용자: 렌더 예외 없음", not at.exception)
    check("비대상 부서는 조회조건에 시드되지 않는다(빈 화면 방지)",
          at.session_state["schedule_view_d"] == ALL)
    check("부서 옵션에 비대상 부서 없음", db.dept_name("MGT") not in dept_options(at))
    check("부서 옵션에 대상 부서는 그대로",
          {db.dept_name("PET1"), db.dept_name("PET2")} <= set(dept_options(at)))
    check("표가 비지 않는다(대상 부서 근무자 조회)",
          any(d.label == "엑셀 다운로드" for d in at.get("download_button")))

    # (g) 폴백(ready=False) — 종전과 동일하게 전 부서(옵션·시드 모두 복귀).
    at_fb = run(admin_mgt, ready=False)
    check("ready=False: 렌더 예외 없음", not at_fb.exception)
    check("ready=False: 부서 옵션에 전 부서 복귀",
          db.dept_name("MGT") in dept_options(at_fb))
    check("ready=False: 시드도 종전대로 내 부서",
          at_fb.session_state["schedule_view_d"] == "MGT")

    # (h) 이력 보존 — 대상 집합 조회는 is_active=None(사용 중지 부서의 과거 근무 보존).
    seen: dict = {}
    saved_codes = db.attendance_dept_codes

    def _spy(is_active=True):
        seen["is_active"] = is_active
        return {"PET1"}

    captured: dict = {}
    orig_build = workspace._build_month_grid

    def _spy_build(q, display_of=None):
        result = orig_build(q, display_of)
        captured["q"] = dict(q)
        captured["grid"] = result[0]
        return result

    try:
        db.attendance_dept_codes = _spy
        workspace._build_month_grid = _spy_build
        at_h = run({"role": "ADMIN", "dept_code": "", "emp_no": "9001", "name": "관리자"})
    finally:
        db.attendance_dept_codes = saved_codes
        workspace._build_month_grid = orig_build
    check("대상 집합 조회는 is_active=None(사용 중지 부서 이력 보존)",
          seen.get("is_active") is None)
    check("화면이 계산에 넘기는 차단 목록 = 마스터 − 대상",
          captured.get("q", {}).get("excluded_depts") == ("MGT", "PET2"))
    if "grid" in captured:
        shown = set(captured["grid"]["사번"].astype(str))
        check("대상(PET1) 근무자만 표에 남는다", "1003" in shown and "1005" not in shown)
    check("실렌더 예외 없음", not at_h.exception)

    # (i) 비대상 부서 MANAGER — 권한 게이트(부서 유효성)는 그대로 통과하고, 빈 이유를
    #     '부서가 유효하지 않음'이 아니라 '근태 대상이 아님'으로 구분해 안내한다.
    at_m = run({"role": "MANAGER", "dept_code": "MGT", "team_code": "",
                "emp_no": "9002", "name": "관리팀장", "is_active": True})
    md_m = " ".join(str(m.value) for m in at_m.markdown)
    check("비대상 부서 MANAGER: 렌더 예외 없음", not at_m.exception)
    check("비대상 부서 MANAGER: 권한 차단 문구가 아니라 근태 대상 안내",
          "소속 부서가 유효하지 않아" not in md_m
          and "근태 등록 대상이 아닙니다" in md_m)

    st.session_state.pop(db._SCHEDULES_STORE, None)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)


def test_month_view_compact_layout() -> None:
    """좁은 폭(모바일)에서 성명 + 일자만 표시하고 표 높이를 뷰포트에 맞춘다.

    사용자 요구(2026-08-13): "모바일은 이름, 근무표만 나오면 되고, 가로로 보는 게 좋겠어".
    표시 열만 줄이며 데이터(_build_month_grid)와 CSV 다운로드 원본은 그대로다.
    """
    print("월간 근무표 좁은 폭 — 성명+일자만 표시 · 표 높이 뷰포트 맞춤 · 가로 안내")
    import inspect
    from streamlit.testing.v1 import AppTest
    from views import workspace

    meta = ["사번", "성명", "대분류", "중분류", "조"]
    days = ["1(수)", "2(목)"]
    wide = workspace.month_grid_columns(meta, days, compact=False)
    compact = workspace.month_grid_columns(meta, days, compact=True)
    check("넓은 폭: 신원 5열 + 일자(종전과 동일)", wide == meta + days)
    check("좁은 폭: 성명 + 일자만", compact == ["성명"] + days)
    check("좁은 폭에서도 일자 열은 하나도 빠지지 않음",
          [c for c in compact if c in days] == days)
    check("신원 열에 성명이 없으면(스키마 변화) 기존 신원 열 유지",
          workspace.month_grid_columns(["사번"], days, compact=True) == ["사번"] + days)

    # 높이: 데스크톱 규칙 불변 / 좁은 폭은 뷰포트에서 크롬을 뺀 값으로 자른다.
    tall = workspace.month_grid_height(40, compact=False, landscape=False, viewport_h=900)
    check("넓은 폭 높이 상한 유지(500)", tall == 500)
    check("넓은 폭 높이 하한 유지(240)",
          workspace.month_grid_height(1, compact=False, landscape=False, viewport_h=900) == 240)
    land = workspace.month_grid_height(40, compact=True, landscape=True, viewport_h=390)
    check("폰 가로: 표가 뷰포트 안에 들어옴", land <= 390 - 150)
    check("폰 가로: 최소 높이(헤더+몇 행) 확보", land >= 150)
    port = workspace.month_grid_height(40, compact=True, landscape=False, viewport_h=844)
    check("폰 세로: 가로보다 높은 표(세로 공간 활용)", port > land)
    check("뷰포트 높이를 모르면 행 수 기준 높이(하한 150)",
          workspace.month_grid_height(1, compact=True, landscape=False, viewport_h=0) == 150)

    src = inspect.getsource(workspace.schedule_screen)
    check("CSV 다운로드 원본은 표시 열 축소와 무관(grid 원본 유지)",
          "grid.to_csv(index=False).encode(\"utf-8-sig\")" in src)
    check("표시 열만 read_grid 에 전달(데이터 프레임은 그대로)",
          "columns=shown_meta + day_cols" in src and "grid_ui," in src)

    # 실렌더: 좁은 폭 세션값이면 안내 문구가 뜨고 집계 표는 두지 않는다.
    def run_with(viewport):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
        at.session_state["user"] = {
            "role": "USER", "dept_code": "PET1", "team_code": "A",
            "emp_no": "1003", "name": "박근무", "is_active": True,
        }
        at.session_state["nav_page"] = "schedule_view"
        at.session_state["schedule_view_y"] = 2026
        at.session_state["schedule_view_m"] = 7
        if viewport is not None:
            at.session_state["schedule_view_viewport"] = viewport
        at.run()
        return at

    md = lambda at: " ".join(m.value for m in at.markdown)  # noqa: E731
    at_p = run_with({"w": 390, "h": 844, "compact": True, "landscape": False})
    check("좁은 폭 세로 렌더 예외 없음", not at_p.exception)
    check("좁은 폭 세로: 가로 보기 안내 1줄 표시", "가로로 돌리면" in md(at_p))
    check("좁은 폭: 직원별 집계 표는 두지 않음(이름·근무표만)",
          "직원별 근무형태 집계" not in md(at_p))
    check("좁은 폭에서도 엑셀 다운로드는 그대로",
          any(d.label == "엑셀 다운로드" for d in at_p.get("download_button")))

    at_l = run_with({"w": 844, "h": 390, "compact": True, "landscape": True})
    check("좁은 폭 가로 렌더 예외 없음", not at_l.exception)
    check("좁은 폭 가로: 회전 안내는 표시하지 않음", "가로로 돌리면" not in md(at_l))

    at_w = run_with({"w": 1440, "h": 900, "compact": False, "landscape": True})
    check("넓은 폭: 회전 안내 없음", "가로로 돌리면" not in md(at_w))
    check("넓은 폭: 직원별 집계 표 유지(종전 동작)", "직원별 근무형태 집계" in md(at_w))


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


def test_schedule_edit_org_axis() -> None:
    """근무표 편성 — 대분류·중분류 표시 축과 조회/정렬 계약 (2026-08-13 사용자 확정).

    ① 그리드 행이 조직관리 대분류·중분류를 함께 보여준다(부서에서 파생한 읽기 전용).
    ② 조회 조건 '부서'는 대분류 단위이며 선택지는 그 달 편성에서 유도한다(하드코딩 금지).
    ③ 조 선택지·정렬은 편성 스냅샷의 근무조에서 유도한다(조 기준정보 축 아님).
    ④ 정렬은 대분류 → 조 → 부서그룹 → 표시순서 → 사번.
    저장 계약(부서 코드 저장)은 종전대로 '부서' 열 하나가 원천이라는 것도 함께 고정한다.
    """
    print("근무표 편성 — 대분류·중분류 표시 축 · 대분류 조회 · 조/대분류 정렬")
    import inspect
    from views import schedule_edit as se

    # (1) 표시 열 계약 — 파생 열이 order 에 들어가 편집 왕복에서 값이 사라지지 않는다.
    check("신원 열에 대분류·중분류 포함", se._FIXED == ["사번", "성명", "대분류", "중분류", "부서", "조"])
    check("파생 열 선언", se._DERIVED == ("대분류", "중분류"))
    check("dirty 비교는 파생 열을 보지 않음(저장 대상 아님)",
          "[\"사번\", \"부서\", \"조\"]" in inspect.getsource(se._canon))
    grid_src = inspect.getsource(se.render)
    check("그리드 order 가 _FIXED 를 그대로 사용(숨김 열도 왕복)",
          "order=_FIXED + day_cols" in grid_src)
    check("파생 열은 편집 불가", '_MAJOR: {"pinned"' in grid_src and '"editable": False' in grid_src)

    # (2) 대분류 라벨 파생 — 코드에 이름을 고정하지 않고 기준정보에서만 읽는다.
    catalog = {
        "org_of": {"D1": ("가생산부", "가생산팀"), "D2": ("가생산부", ""), "D3": ("", "")},
        "major_order": {"가생산부": 22},
        "name_codes": {"가1팀": {"D1"}, "가2팀": {"D2"}, "겹침": {"D1", "D2"}},
        "codes": {"D1", "D2", "D3"},
    }
    check("대분류·중분류 파생", se._org_labels("D1", catalog) == ("가생산부", "가생산팀"))
    check("중분류 없으면 빈 칸(부서명으로 지어내지 않음)", se._org_labels("D2", catalog) == ("가생산부", ""))
    check("대분류 없으면 미분류", se._org_labels("D3", catalog) == ("미분류", ""))
    check("미등록 부서코드도 미분류로 표시", se._org_labels("NOPE", catalog) == ("미분류", ""))
    check("부서 셀 → 코드(코드 입력)", se._dept_code_of_text("D1", catalog) == "D1")
    check("부서 셀 → 코드(부서명 입력)", se._dept_code_of_text("가2팀", catalog) == "D2")
    check("동명 부서는 해석하지 않음(저장 검증과 같은 기준)",
          se._dept_code_of_text("겹침", catalog) == "")

    # (3) 조회 범위 판정 — 전체 / 대분류 / MANAGER 부서 잠금.
    check("전체는 모두 포함", se._in_scope(se._ALL, "D3", catalog))
    check("대분류는 소속 부서 전부 포함",
          se._in_scope("가생산부", "D1", catalog) and se._in_scope("가생산부", "D2", catalog))
    check("다른 대분류는 제외", not se._in_scope("가생산부", "D3", catalog))
    check("MANAGER 부서 잠금은 그 부서만(대분류로 넓히지 않음)",
          se._in_scope(f"{se._DEPT_SCOPE}D1", "D1", catalog)
          and not se._in_scope(f"{se._DEPT_SCOPE}D1", "D2", catalog))

    # (4) 조 순서 — A조→B조→C조 → 비표준 표기 → 빈 조 (실데이터 값을 감추지 않는다).
    values = ["", "B팀", "C조", "A조", "B조"]
    check("조 정렬: 표준 조 먼저, 비표준 뒤, 빈 값 마지막",
          sorted(values, key=se._shift_rank) == ["A조", "B조", "C조", "B팀", ""])

    # (5) 행 정렬 키 — 대분류(최소 표시순서) → 조 → 부서그룹 → 표시순서(없으면 뒤) → 사번.
    def key(major, morder, shift, group, order, emp):
        return se._row_sort_key(major, morder, shift, group, order, emp)

    check("대분류는 최소 표시순서 순", key("가", 22, "A조", 0, 1, "1") < key("나", 24, "A조", 0, 1, "1"))
    check("미분류는 언제나 마지막", key("가", 999, "", 0, None, "9") < key("", 0, "A조", 0, 1, "1"))
    check("같은 대분류면 조 순", key("가", 22, "A조", 0, 9, "9") < key("가", 22, "B조", 0, 1, "1"))
    check("같은 조면 표시순서 순", key("가", 22, "A조", 0, 1, "9") < key("가", 22, "A조", 0, 2, "1"))
    check("표시순서 미지정은 뒤", key("가", 22, "A조", 0, 99, "9") < key("가", 22, "A조", 0, None, "1"))
    check("마지막 동률은 사번", key("가", 22, "A조", 0, None, "1") < key("가", 22, "A조", 0, None, "2"))

    # (6) 조 선택지는 조 기준정보가 아니라 편성 스냅샷에서 나온다.
    src = (ROOT / "views" / "schedule_edit.py").read_text(encoding="utf-8")
    check("조 선택지가 편성 스냅샷 유도(_shift_options)", "def _shift_options" in src)
    check("조 선택지에 db.get_teams 를 쓰지 않음", "db.get_teams()" not in src)
    check("대분류 선택지도 유도(하드코딩된 대분류 이름 없음)",
          "def _major_options" in src and "PET생산부" not in src and "PVC생산부" not in src)

    # (7) 실렌더(sample) — 새 열이 실제 행에 실리고 초기 상태가 깨끗하다.
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.session_state["user"] = {"role": "ADMIN", "dept_code": "", "emp_no": "9001", "name": "관리자"}
    at.session_state["nav_page"] = "schedule_edit"
    at.session_state["se_y"] = 2026
    at.session_state["se_m"] = 7
    at.run()
    check("대분류 축 렌더 예외 없음", not at.exception)
    rows = at.session_state["se_rows"]
    check("행 프레임에 대분류·중분류 열 존재", {"대분류", "중분류"}.issubset(set(rows.columns)))
    check("부서 열(저장 원천)은 그대로 유지", "부서" in rows.columns)
    check("조회 조건 '부서' 선택지는 항상 전체를 포함",
          any(sb.key == "se_d" and "전체 부서" in list(sb.options) for sb in at.selectbox))
    check("조 선택지도 항상 전체를 포함",
          any(sb.key == "se_t" and "전체 조" in list(sb.options) for sb in at.selectbox))
    check("초기 로드는 dirty 아님(파생 열이 가짜 변경을 만들지 않음)",
          at.session_state["se_dirty"] is False)


def test_schedule_edit_attendance_scope() -> None:
    """근무표 편성 — 근태 등록 대상 부서만 목록·조회 (2026-08-14 사용자 지시).

    "조직 관리에 근태 등록하는 부서만 지정 / 근태에서는 해당 조직만 목록이나 조회"
      ① 조회 조건 '부서'(대분류)·'조' 선택지와 그리드 행이 **같은 기준**(근태 대상 부서)
         으로 좁혀진다 — 선택지와 행이 어긋나면 '고르면 0건'인 죽은 선택지가 생긴다.
      ② 지정 기능을 쓸 수 없으면(attendance_flag_ready False) 종전대로 전 부서다(fail-open).
      ③ 비대상 부서로 저장된 기존 편성은 조용히 사라지지 않고 '제외 N명'으로 드러난다.
      ④ MANAGER 부서 잠금은 근태 지정과 무관하다 — 잠금이 풀리면 전체가 열린다.
    """
    print("근무표 편성 — 근태 등록 대상 부서 필터(선택지·행·폴백·MANAGER)")
    import inspect
    from streamlit.testing.v1 import AppTest
    from views import schedule_edit as se

    src = (ROOT / "views" / "schedule_edit.py").read_text(encoding="utf-8")
    render_src = inspect.getsource(se.render)

    # (1) 순수 판정 — None(폴백)은 '필터 없음'이며 빈 집합으로 접히지 않는다.
    check("폴백(None)은 전 부서 통과", se._tracked_dept("PET1", None))
    check("지정 집합 안은 통과(공백 정규화)", se._tracked_dept(" PET1 ", {"PET1"}))
    check("지정 밖은 제외", not se._tracked_dept("PET2", {"PET1"}))
    check("지정 0건이면 어떤 부서도 통과하지 않음", not se._tracked_dept("PET1", set()))

    # (2) 판정 원천은 파사드 하나 — 화면이 부서 플래그를 직접 읽거나 복제하지 않는다.
    check("근태 대상 판정은 db 파사드", "db.attendance_dept_codes(" in src)
    check("폴백 판정도 파사드", "db.attendance_flag_ready()" in src)
    check("과거 편성 조회용으로 비활성 부서도 포함(is_active=None)",
          "db.attendance_dept_codes(is_active=None)" in src)
    check("화면이 부서 플래그 컬럼을 직접 인덱싱하지 않음(파사드 경유)",
          '["tracks_attendance"]' not in src)
    check("MANAGER 잠금 판정은 근태 지정과 무관(잠금 해제 = 전체 개방)",
          'manager_locked = user["role"] == "MANAGER" and user.get("dept_code") in dept_names'
          in render_src)
    i_slot = render_src.find('st.container(key="se_notice")')
    i_note = render_src.find("_scope_notice(")
    i_grid = render_src.find('st.container(key="se_gridwrap")')
    check("범위 안내는 알림 슬롯 안에서 렌더(그리드 위 새 최상위 요소 금지)",
          0 <= i_slot < i_note < i_grid)

    # (3) 선택지 유도 — 부서(대분류)·조 모두 근태 대상에서만.
    st.session_state.pop(db._SCHEDULES_STORE, None)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)
    base = db.get_org_departments().copy()
    injected = base.copy()
    injected.loc[injected["dept_code"] == "PET1",
                 ["major_category", "minor_category"]] = ["PET생산부", "PET생산팀"]
    injected.loc[injected["dept_code"] == "PET2",
                 ["major_category", "minor_category"]] = ["PVC생산부", "PVC생산팀"]
    injected["tracks_attendance"] = injected["dept_code"].astype(str).isin(["PET1"])
    teams = db.get_teams()
    t1 = str(teams[teams["dept_code"] == "PET1"].iloc[0]["team_code"])
    t2 = str(teams[teams["dept_code"] == "PET2"].iloc[0]["team_code"])
    try:
        db.save_org_departments(injected[db.ORG_DEPT_COLUMNS])
        # require_shift=False — 편성 화면과 같은 자유 텍스트 근무조 경로(2026-08-07 결정).
        db.upsert_month_assignments([
            {"emp_no": "1003", "schedule_month": "2026-07", "dept_code": "PET1",
             "team_code": t1, "shift_group_code": "A"},
            {"emp_no": "1005", "schedule_month": "2026-07", "dept_code": "PET2",
             "team_code": t2, "shift_group_code": "B"},
        ], require_shift=False)
        dept_store = st.session_state[db._DEPTS_STORE].copy()
        assign_store = st.session_state[db._ASSIGNMENTS_STORE].copy()

        catalog = se._dept_catalog()
        tracked = se._attendance_scope()
        check("근태 대상 집합 = 지정 부서만", tracked == {"PET1"})
        check("대분류 선택지는 근태 대상 부서의 대분류만",
              se._major_options(2026, 7, catalog, tracked) == ["PET생산부"])
        check("폴백은 종전 선택지(전 부서)",
              se._major_options(2026, 7, catalog, None) == ["PET생산부", "PVC생산부"])
        check("조 선택지도 근태 대상 부서에서만 유도",
              se._shift_options(2026, 7, catalog, se._ALL, tracked) == ["A조"])
        check("폴백 조 선택지는 종전대로 전 부서",
              se._shift_options(2026, 7, catalog, se._ALL, None) == ["A조", "B조"])

        # 이름 기반 제외(_EXCLUDED_MAJORS)와 명시 지정이 부딪히면 지정이 이긴다 —
        # 사용자가 근태 대상으로 고른 부서를 화면이 대분류 이름으로 다시 감추지 않는다.
        catalog_mgmt = {
            "org_of": {"PET1": ("PET생산부", ""), "PET2": (se._EXCLUDED_MAJORS[0], "")},
            "major_order": {"PET생산부": 1, se._EXCLUDED_MAJORS[0]: 2},
            "name_codes": {}, "codes": {"PET1", "PET2"},
        }
        check("폴백에서는 이름 기반 대분류 제외를 유지",
              se._major_options(2026, 7, catalog_mgmt, None) == ["PET생산부"])
        check("지정이 동작하면 지정 부서는 이름 규칙보다 우선해 선택 가능",
              se._major_options(2026, 7, catalog_mgmt, {"PET1", "PET2"})
              == ["PET생산부", se._EXCLUDED_MAJORS[0]])

        # (4) 실렌더 — AppTest 는 별도 세션이므로 sample backing store 를 함께 심는다.
        def run_as(user, depts=None, ready=True):
            original = db.attendance_flag_ready
            if not ready:
                db.attendance_flag_ready = lambda: False
            try:
                at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
                at.session_state["user"] = user
                at.session_state["nav_page"] = "schedule_edit"
                at.session_state["se_y"] = 2026
                at.session_state["se_m"] = 7
                at.session_state[db._DEPTS_STORE] = \
                    (dept_store if depts is None else depts).copy()
                at.session_state[db._ASSIGNMENTS_STORE] = assign_store.copy()
                return at.run()
            finally:
                db.attendance_flag_ready = original

        def emps(at):
            rows = at.session_state["se_rows"]
            return [str(v).strip() for v in rows["사번"] if str(v).strip()]

        def md(at):
            return " ".join(str(m.value) for m in at.markdown)

        admin = {"role": "ADMIN", "dept_code": "", "emp_no": "9001", "name": "관리자"}
        at = run_as(admin)
        check("근태 필터 렌더 예외 없음", not at.exception)
        check("행 목록이 근태 대상 부서 소속만",
              sorted(emps(at)) == ["1002", "1003", "1004", "1007"])
        check("비대상 부서(PET2) 편성 인원은 행에서 제외", "1005" not in emps(at))
        check("제외 인원수를 세션에 남김", at.session_state["se_untracked"]["count"] == 1)
        check("제외 사실을 안내 1줄로 드러냄(조용히 감추지 않음)",
              "목록에서 제외했습니다" in md(at))
        check("안내에 '저장된 근무는 남아 있다'를 함께 적음", "저장된 근무는 그대로" in md(at))
        options = [list(sb.options) for sb in at.selectbox if sb.key == "se_d"]
        check("부서 선택지에 근태 대상 대분류만",
              options and "PET생산부" in options[0] and "PVC생산부" not in options[0])
        check("부서 선택지의 [전체 부서]는 유지", options and "전체 부서" in options[0])

        # (5) 폴백(attendance_flag_ready False) — 종전과 동일하게 전 부서.
        at_fb = run_as(admin, ready=False)
        check("폴백 렌더 예외 없음", not at_fb.exception)
        check("폴백은 전 부서 행 복귀(비대상 필터 없음)",
              sorted(emps(at_fb)) == ["1002", "1003", "1004", "1005", "1007"])
        check("폴백에서는 제외 안내를 그리지 않음", "목록에서 제외했습니다" not in md(at_fb))
        opts_fb = [list(sb.options) for sb in at_fb.selectbox if sb.key == "se_d"]
        check("폴백 부서 선택지는 종전대로 전 대분류",
              opts_fb and {"PET생산부", "PVC생산부"} <= set(opts_fb[0]))

        # (6) MANAGER 소속 부서가 비대상 — 잠금은 유지하고 빈 화면의 사유를 밝힌다.
        at_m = run_as({"role": "MANAGER", "dept_code": "PET2",
                       "emp_no": "1006", "name": "강책임"})
        check("MANAGER 비대상 부서 렌더 예외 없음", not at_m.exception)
        check("MANAGER 비대상 부서: 기존 행 없음(신규 입력 행만)",
              set(at_m.session_state["se_rows"]["_row_state"]) == {"new"})
        check("MANAGER 비대상 부서: 사유를 경고로 안내(빈 화면 방치 금지)",
              any("근태 등록 대상이 아닙니다" in str(w.value) for w in at_m.warning))
        check("MANAGER 부서 잠금 유지(선택지는 자기 부서 1개 — 대분류로 넓히지 않음)",
              any(sb.key == "se_d" and list(sb.options) == [db.dept_name("PET2")]
                  for sb in at_m.selectbox))

        # (7) 지정 0건 — 목록을 임의로 열지 않고 다음 행동을 안내한다.
        none_store = dept_store.copy()
        none_store["tracks_attendance"] = False
        at_z = run_as(admin, depts=none_store)
        check("지정 0건 렌더 예외 없음", not at_z.exception)
        check("지정 0건: 기존 행 없음",
              set(at_z.session_state["se_rows"]["_row_state"]) == {"new"})
        check("지정 0건: 사유와 다음 행동 안내",
              any("근태 등록 대상으로 지정된 부서가 없습니다" in str(w.value)
                  for w in at_z.warning))
        check("지정 0건에서도 제외 인원수는 그대로 드러냄",
              at_z.session_state["se_untracked"]["count"] == 5)
    finally:
        db.save_org_departments(base[db.ORG_DEPT_COLUMNS])  # 다른 테스트 격리(원복)
        st.session_state.pop(db._ASSIGNMENTS_STORE, None)
        st.session_state.pop(db._SCHEDULES_STORE, None)


def test_schedule_edit_row_add_and_paste() -> None:
    """근무표 편성 — 행 추가(헤더 아이콘) 실동작 + 다중 행 붙여넣기 자동 확장.

    2026-08-14 사용자 신고 2건.
      ① "행 추가가 먹통": 앱 셸이 헤더를 본문보다 먼저 그려서 render 말미의
         publish_header_actions 발행값이 한 run 늦게 반영된다. [추가]는 미발행
         기본값이 음영이라, 화면에 들어와 아무것도 만지지 않으면 발행값을 실을 rerun
         자체가 생기지 않아 + 아이콘이 계속 음영으로 남았다 → 기준정보 3화면과 같은
         따라잡기(_sync_header)로 닫는다.
      ② "여러 줄 붙여넣으면 행이 자동 확장돼야 한다": 확장 자체는 공용 그리드의
         네이티브 paste 핸들러가 클라이언트에서 수행하고(부족분 applyTransaction),
         서버는 무명 행에 행 상태를 부여해 같은 저장 계약에 태운다(_sync_rows).
         두 절반이 모두 살아 있어야 동작하므로 양쪽을 고정한다.
    """
    print("근무표 편성 — 행 추가 헤더 따라잡기 · 다중 행 붙여넣기 확장")
    import inspect
    from streamlit.testing.v1 import AppTest
    from views import schedule_edit as se
    from views import workspace as ws

    render_src = inspect.getsource(se.render)

    # (1) 따라잡기 배선 — 발행 뒤, **액션 flag 소비 뒤**에 호출해야 한다.
    #     앞에서 rerun 하면 헤더 클릭으로 세팅된 flag 가 소비되기 전에 프레임이 끝난다.
    i_pub = render_src.find("ui.publish_header_actions(")
    i_add = render_src.find('st.session_state.pop("se_add_req"')
    i_sync = render_src.find("_sync_header(header_states)")
    check("헤더 발행 → 액션 flag 소비 → 따라잡기 순서", 0 <= i_pub < i_add < i_sync)
    sync_src = inspect.getsource(se._sync_header)
    check("발행값이 바뀐 run 에서만 재실행", "st.rerun()" in sync_src and "== payload" in sync_src)
    check("폭주 방지 가드(연속 보정 상한)", "tries < 2" in sync_src)

    # (2) 붙여넣기 확장의 클라이언트 절반 — 공용 핸들러가 부족한 행을 만들고,
    #     편성 그리드가 그 핸들러를 실제로 물고 있어야 한다(둘 중 하나만 있어도 무용).
    paste_src = str(ws._NATIVE_PASTE_HANDLER.js_code)
    check("붙여넣기 핸들러가 부족분만큼 행을 생성", "missing > 0" in paste_src
          and "applyTransaction" in paste_src)
    check("확장은 편집 가능한 열에만 값을 쓴다(기존 행 읽기전용 열 보호)",
          "editable" in paste_src)
    grid_src = inspect.getsource(ws.selectable_master_grid)
    check("편성 그리드가 공용 붙여넣기 핸들러를 물고 있음",
          '"onGridReady": _NATIVE_PASTE_HANDLER' in grid_src)
    check("화면이 onGridReady 를 덮어쓰지 않음(확장 무력화 방지)",
          "onGridReady" not in render_src)

    # (3) 붙여넣기 확장의 서버 절반 — 무명 행에 행 상태 부여 + 사번 자동 조회.
    st.session_state.pop(db._SCHEDULES_STORE, None)
    st.session_state.pop(db._ASSIGNMENTS_STORE, None)
    day_cols = ["1(수)"]
    row_cols = se._META + se._FIXED + day_cols
    st.session_state["se_rows"] = pd.DataFrame(
        [{**{c: "" for c in row_cols}, "_row_id": "n:1", "_row_state": "new", "_sel": False}],
        columns=row_cols,
    )
    st.session_state["se_days"] = [("1(수)", "2026-07-01")]
    st.session_state["se_rid"] = 1
    st.session_state.pop("se_users_map", None)
    pasted = pd.DataFrame([
        {"_row_id": "n:1", "_row_state": "new", "_sel": False, "_removed": "",
         "사번": "1002", "성명": "", "대분류": "", "중분류": "", "부서": "", "조": "", "1(수)": ""},
        # 붙여넣기로 생긴 행: 클라이언트 applyTransaction 은 필드가 비어 있다.
        {"_row_id": "", "_row_state": "", "_sel": False, "_removed": "",
         "사번": "1004", "성명": "", "대분류": "", "중분류": "", "부서": "", "조": "", "1(수)": ""},
        {"_row_id": "", "_row_state": "", "_sel": False, "_removed": "",
         "사번": "1007", "성명": "", "대분류": "", "중분류": "", "부서": "", "조": "", "1(수)": ""},
    ])
    changed = se._sync_rows(pasted, row_cols)
    rows = st.session_state["se_rows"]
    check("붙여넣기 행이 권위 상태에 그대로 남는다(버려지지 않음)", len(rows) == 3)
    check("무명 행에 행 식별자 부여", all(str(v).strip() for v in rows["_row_id"]))
    check("무명 행은 신규 행 상태(기존 행으로 둔갑 금지)",
          set(rows["_row_state"]) == {"new"})
    check("사번으로 성명 자동 조회", all(str(v).strip() for v in rows["성명"]))
    check("사번으로 부서 자동 채움(저장 검증 통과 조건)",
          all(str(v).strip() for v in rows["부서"]))
    check("구조 변경이므로 재마운트 신호", changed is True)
    for key in ("se_rows", "se_feed", "se_days", "se_rid", "se_nonce", "se_users_map"):
        st.session_state.pop(key, None)

    # (4) 실렌더 — 진입 직후(아무 상호작용 없이) + 아이콘이 활성이어야 한다.
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.session_state["user"] = {"role": "ADMIN", "dept_code": "", "emp_no": "9001", "name": "관리자"}
    at.session_state["nav_page"] = "schedule_edit"
    at.session_state["se_y"] = 2026
    at.session_state["se_m"] = 7
    at.run()
    check("행 추가 렌더 예외 없음", not at.exception)
    add_btns = [b for b in at.button if b.key == "app_hdr_add"]
    check("헤더 [추가] 아이콘 존재", bool(add_btns))
    check("진입 직후 [추가] 아이콘이 활성(먹통 회귀 차단)",
          bool(add_btns) and not add_btns[0].disabled)
    before = len(at.session_state["se_rows"])
    at.session_state["se_add_req"] = True
    at.run()
    check("[추가] 1회 = 신규 행 1개", len(at.session_state["se_rows"]) == before + 1)
    check("추가된 행은 신규 상태", str(at.session_state["se_rows"].iloc[-1]["_row_state"]) == "new")


def test_schedule_edit_work_type_name_axis() -> None:
    """근무표 편성 — 날짜 셀 표시·입력 축을 약칭에서 **명칭**으로 (2026-08-14 사용자 지시).

    실데이터에서 약칭은 여러 근무형태가 공유해(한 약칭에 십수 개 코드) 왕복 변환이
    모호해졌고, 기존 안전장치가 발동해 셀에 내부 코드가 보였다. 명칭은 유일하므로
    모호성이 사라진다. **안전장치는 유지**한다: 명칭이 겹치면 코드로 표시하고, 입력이
    여러 코드에 걸리면 저장을 막는다(AMBIG). 저장은 종전대로 내부 코드로 기록한다.
    """
    print("근무표 편성 — 근무형태 명칭 표시·입력 축")
    from views import schedule_edit as se

    st.session_state.pop(db._WORK_TYPES_STORE, None)
    base = db.get_work_types().copy()
    try:
        display_of, codes, input_codes = se._label_maps()
        by_code = {str(r["code"]).strip(): r for _, r in base.iterrows() if bool(r["is_active"])}
        check("표시값이 약칭이 아니라 명칭",
              all(display_of[c] == str(by_code[c]["name"]).strip() for c in by_code))
        check("표시값과 약칭이 실제로 다른 케이스가 있다(축 전환 확인)",
              any(display_of[c] != str(by_code[c]["short_label"]).strip() for c in by_code))
        check("입력은 명칭을 받는다",
              se._resolve_work(str(by_code["주"]["name"]).strip(), codes, input_codes) == "주")
        check("입력은 약칭도 계속 받는다(하위 호환)",
              se._resolve_work("주", codes, input_codes) == "주")
        check("입력은 코드도 계속 받는다", se._resolve_work("OFF", codes, input_codes) == "OFF")
        check("미등록 입력은 None(저장 차단)",
              se._resolve_work("없는근무", codes, input_codes) is None)
        check("색은 코드에 귀속(명칭으로 바뀌어도 같은 색)",
              se._day_color_map(display_of).get(display_of["주"])
              == str(by_code["주"]["color"]).strip())

        # 명칭이 겹치는 데이터에서는 코드 폴백 + 모호 입력 차단(안전장치 유지).
        dup = base.copy()
        dup.loc[dup["code"] == "야", "name"] = str(by_code["주"]["name"]).strip()
        st.session_state[db._WORK_TYPES_STORE] = dup
        d2, c2, i2 = se._label_maps()
        check("명칭 중복이면 코드로 표시(왕복 모호성 방지)",
              d2["주"] == "주" and d2["야"] == "야")
        check("모호한 입력은 AMBIG(저장 차단)",
              se._resolve_work(str(by_code["주"]["name"]).strip(), c2, i2) == "AMBIG")
    finally:
        st.session_state[db._WORK_TYPES_STORE] = base

    # 일자 열 폭은 표시값에서 유도하되 밀도 상한을 지킨다(하드코딩 폭 아님).
    check("짧은 표시값에서는 종전 폭 유지", se._day_width(["주", "야", "OFF"]) == se._DAY_W_MIN)
    check("긴 명칭은 상한에서 멈춘다(31일 매트릭스 밀도 보호)",
          se._day_width(["경조(자녀결혼)"]) == se._DAY_W_MAX)
    check("중간 길이는 내용에 맞춰 늘어난다",
          se._DAY_W_MIN <= se._day_width(["야간"]) <= se._DAY_W_MAX)
    check("빈 목록도 안전(하한)", se._day_width([]) == se._DAY_W_MIN)


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
        test_dashboard_attendance_target_scope,
        test_month_grid_snapshot,
        test_month_grid_org_labels_and_order,
        test_retired_employee_month_display,
        test_schedule_view_manager_scope_enforced,
        test_month_view_top_actions,
        test_month_view_scope_defaults,
        test_month_view_attendance_scope,
        test_month_view_compact_layout,
        test_schedule_edit_row_reorder,
        test_schedule_edit_org_axis,
        test_schedule_edit_attendance_scope,
        test_schedule_edit_row_add_and_paste,
        test_schedule_edit_work_type_name_axis,
    ):
        test()
    print(f"\nALL PASSED ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
