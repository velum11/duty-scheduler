"""월별 편성 저장·연결 계약 테스트 (sample/pure, 실DB 미접속).

migration 002 적용 후 운영 저장 경로의 계약을 고정한다:
  - schedule_assignments upsert 가 실제 id 를 반환 (전역 identity 추정 없음)
  - work_schedules 각 행을 (사용자·월) 편성에만 연결 (없으면 NULL, legacy 호환)
  - 다른 직원·다른 월 편성 id 오연결 차단
  - 편성 저장 여부 결정 (신규 / 부서·조 변경만 / legacy 근무만 수정은 제외)
  - users 기준정보 불변, team_id NULL 보존

라이브 DB·브라우저로만 검증 가능한 계약(§표기)은 E2E 로 확인한다:
  #16/#17 저장 순서 부분실패, #22/#23 새로고침·재로그인 재수화, #24 dirty 정리.
  #25 mixed-save/선택삭제 회귀는 test_schedule_contracts·test_schedule_save_units.

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_assignment_linking.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

from modules import db  # noqa: E402
from modules import supabase_repository as repo  # noqa: E402
from views.schedule_edit import should_save_assignment  # noqa: E402

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS
    if cond:
        PASS += 1
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name}" + (f" [{detail}]" if detail else ""))


# ===== plan_schedule_links (순수): work_schedules ↔ assignment id 연결 =====
print("plan_schedule_links (근무 행 → schedule_assignment_id 결정)")
U, M = 31, "2027-01-01"
rows = [
    {"user_id": U, "work_date": "2027-01-01", "work_type_code": "DAY", "note": "", "schedule_month": M},
    {"user_id": U, "work_date": "2027-01-02", "work_type_code": "NIGHT", "note": "", "schedule_month": M},
]

# #3/#4: (user,month) 편성이 있으면 그 id 연결
linked = repo.plan_schedule_links(rows, {(U, M): 777})
check("#3/#4 편성 존재 → 두 근무 행 모두 그 id(777) 연결",
      all(r["schedule_assignment_id"] == 777 for r in linked))
check("#8/#9 입력 행 수만큼만 payload(기존 행 일괄 생성/연결 없음)", len(linked) == len(rows))

# #6: 편성 없으면 NULL (legacy)
legacy = repo.plan_schedule_links(rows, {})
check("#6 편성 없음 → schedule_assignment_id NULL(legacy 호환)",
      all(r["schedule_assignment_id"] is None for r in legacy))

# #14: 다른 직원 편성 id 는 연결되지 않음
other_user = repo.plan_schedule_links(rows, {(99, M): 500})
check("#14 다른 직원(99) 편성 id 는 이 직원 근무에 연결되지 않음",
      all(r["schedule_assignment_id"] is None for r in other_user))

# #15: 다른 월 편성 id 는 연결되지 않음
other_month = repo.plan_schedule_links(rows, {(U, "2027-02-01"): 600})
check("#15 다른 월(2027-02) 편성 id 는 1월 근무에 연결되지 않음",
      all(r["schedule_assignment_id"] is None for r in other_month))

# 혼합: 한 직원만 편성 존재
mixed = repo.plan_schedule_links(
    rows + [{"user_id": 32, "work_date": "2027-01-01", "work_type_code": "OFF",
             "note": "", "schedule_month": M}],
    {(U, M): 777},
)
check("혼합: 편성 있는 직원만 연결, 없는 직원은 NULL",
      mixed[0]["schedule_assignment_id"] == 777 and mixed[2]["schedule_assignment_id"] is None)


# ===== should_save_assignment (순수): 편성 저장 여부 결정 =====
print("should_save_assignment (편성 upsert 대상 결정)")
# #2 신규 직원·월 → 저장
check("#2 신규 행 + 유효 부서 → 저장", should_save_assignment("new", "PET", "B", None) is True)
check("신규 행 + 부서 없음 → 저장 안 함", should_save_assignment("new", "", "", None) is False)
# #5 legacy 근무만 수정(부서·조 로드값 그대로) → 저장 안 함
check("#5 기존 행 + 부서·조 로드값과 동일(근무만 수정) → 저장 안 함",
      should_save_assignment("existing", "PET", "A", ("PET", "A")) is False)
# #7 부서·조 명시 변경 → 저장
check("#7 기존 행 + 조 변경(A→B) → 저장", should_save_assignment("existing", "PET", "B", ("PET", "A")) is True)
check("기존 행 + 부서 변경 → 저장", should_save_assignment("existing", "PVC", "A", ("PET", "A")) is True)
check("기존 행 + 로드 스냅샷 없음 → 저장 안 함(과각인 방지)",
      should_save_assignment("existing", "PET", "A", None) is False)
check("조 없음 유지(team ''→'') → 저장 안 함(NULL 보존)",
      should_save_assignment("existing", "ADMIN", "", ("ADMIN", "")) is False)


# ===== sample upsert_month_assignments: 반환 id + users 불변 + NULL 보존 =====
print("db.upsert_month_assignments (반환 id·users 불변·NULL 보존, sample)")
users = db.get_users()
au = users[users["is_active"]]
emp0 = str(au.iloc[0]["emp_no"]).strip()
dept0 = str(au.iloc[0]["dept_code"]).strip()
teams0 = db.get_teams()
team_in_dept = teams0[teams0["dept_code"].astype(str) == dept0]
team_code0 = str(team_in_dept.iloc[0]["team_code"]).strip() if not team_in_dept.empty else ""

users_before = db.get_users().to_dict("records")
ret = db.upsert_month_assignments([
    {"emp_no": emp0, "schedule_month": (2027, 1), "dept_code": dept0,
     "team_code": team_code0, "shift_group_code": ""},
], require_shift=False)
# #1 실제(합성) id 반환, (emp, month) 매핑
key = (emp0, "2027-01-01")
check("#1 upsert 가 (emp,month)→레코드(id 포함) 반환", key in ret and bool(ret[key].get("id")))
check("#1 반환 레코드에 dept/team/shift 포함",
      ret[key]["dept_code"] == dept0 and ret[key]["team_code"] == team_code0
      and "shift_group_code" in ret[key])
# #19 조회 시 편성 우선(방금 저장분 반환)
got = db.get_month_assignments(2027, 1, emp0)
check("#19 get_month_assignments 가 저장 편성을 반환(조회 우선순위 1)",
      not got.empty and str(got.iloc[0]["team_code"]).strip() == team_code0)
# #20 없는 월은 빈 결과(→ 호출부가 users fallback)
check("#20 편성 없는 월은 빈 결과(users fallback 은 호출부 담당)",
      db.get_month_assignments(2030, 6, emp0).empty)
# #10/#11 users 불변
check("#10/#11 편성 저장이 users(부서·조) 를 변경하지 않음",
      db.get_users().to_dict("records") == users_before)

# #12 team 미지정('') → 편성 team_code '' 보존(NULL 계약)
ret_null = db.upsert_month_assignments([
    {"emp_no": emp0, "schedule_month": (2027, 3), "dept_code": dept0,
     "team_code": "", "shift_group_code": ""},
], require_shift=False)
check("#12 team 미지정 저장 → 반환 team_code '' 보존(NULL 계약)",
      ret_null[(emp0, "2027-03-01")]["team_code"] == "")
got_null = db.get_month_assignments(2027, 3, emp0)
check("#12 조회에서도 team_code '' (A조 등 자동 대입 없음)",
      not got_null.empty and str(got_null.iloc[0]["team_code"]).strip() == "")

# #13 선택 부서에 없는 조 저장 시 차단 (부서·조 복합 소속 검증)
valid_codes = set(team_in_dept["team_code"].astype(str).str.strip())
bad_team = "ZZZ_NOT_A_TEAM"
assert bad_team not in valid_codes
raised = False
try:
    db.upsert_month_assignments([
        {"emp_no": emp0, "schedule_month": (2027, 4), "dept_code": dept0,
         "team_code": bad_team, "shift_group_code": ""},
    ], require_shift=False)
except ValueError:
    raised = True
check("#13 선택 부서에 없는 조 저장 차단(복합 소속 검증)", raised)

# #21 편성 유무와 무관하게 근무 조회는 동작(독립성)
sched = db.get_month_schedules([emp0], 2026, 7)
check("#21 근무 조회는 편성과 독립(계약 컬럼 유지)", list(sched.columns) == db.SCHEDULE_COLUMNS)


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
