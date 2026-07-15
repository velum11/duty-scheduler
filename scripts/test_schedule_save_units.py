"""근무표 편성 — 혼합 저장 분류·약칭 해석·조 스냅샷 계약 단위 테스트 (bare mode).

실행: .venv/Scripts/python.exe scripts/test_schedule_save_units.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DUTY_DATA_MODE"] = "sample"  # Supabase 미접속 보장

from modules import db  # noqa: E402
from views.schedule_edit import classify_save_targets, _resolve_work  # noqa: E402

PASS = 0
FAIL = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name}")


print("classify_save_targets (혼합 저장 분류)")
d, r = classify_save_targets(live_emps=[], deleted_emps=["1001", "1002"])
check("재입력 없음 → 전부 delete_only", d == ["1001", "1002"] and r == [])

d, r = classify_save_targets(live_emps=["1002"], deleted_emps=["1001", "1002"])
check("삭제 예정 + 동일 사번 재등록 → 교체", d == ["1001"] and r == ["1002"])

d, r = classify_save_targets(live_emps=["2001", "1002"], deleted_emps=["1001", "1002"])
check("삭제 + 신규 사번 동시 → 삭제·교체 분리", d == ["1001"] and r == ["1002"])

d, r = classify_save_targets(live_emps=[" 1001 "], deleted_emps=["1001"])
check("공백 정규화 후 매칭", d == [] and r == ["1001"])

d, r = classify_save_targets(live_emps=["3001"], deleted_emps=[])
check("삭제 예정 없음 → 두 집합 모두 비움", d == [] and r == [])

d, r = classify_save_targets(live_emps=["", "  "], deleted_emps=["1001"])
check("빈 사번은 최종 상태에서 제외", d == ["1001"] and r == [])

print("_resolve_work (약칭 → 내부 코드)")
codes = {"DAY", "NIGHT", "OFF"}
labels = {"주": {"DAY"}, "야": {"NIGHT"}, "겹": {"DAY", "NIGHT"}}
check("코드 직접 입력 허용", _resolve_work("DAY", codes, labels) == "DAY")
check("약칭 → 코드 변환", _resolve_work("주", codes, labels) == "DAY")
check("미등록 약칭 → None", _resolve_work("없음", codes, labels) is None)
check("모호 약칭 → AMBIG", _resolve_work("겹", codes, labels) == "AMBIG")

print("월 편성 조 스냅샷 (sample 모드: 조 표시명->team_code->저장->재조회 계약)")
users = db.get_users()
teams = db.get_teams()
active_teams = teams[teams["is_active"].astype(bool)]
multi = active_teams.groupby("dept_code").filter(lambda g: len(g) >= 2)
dept = str(multi["dept_code"].iloc[0])
in_dept = multi[multi["dept_code"].astype(str) == dept]
team_a = str(in_dept["team_code"].iloc[0])
team_b = str(in_dept["team_code"].iloc[1])
emp1 = str(users["emp_no"].astype(str).iloc[0])
emp2 = str(users["emp_no"].astype(str).iloc[1])

db.upsert_month_assignments([
    {"emp_no": emp1, "schedule_month": (2027, 7), "dept_code": dept,
     "team_code": team_a, "shift_group_code": ""},
    {"emp_no": emp2, "schedule_month": (2027, 7), "dept_code": dept,
     "team_code": team_b, "shift_group_code": ""},
], require_shift=False)
back = db.get_month_assignments(2027, 7, [emp1, emp2])
by_emp = {str(r["emp_no"]): str(r["team_code"]) for _, r in back.iterrows()}
check("서로 다른 조 2명이 각자 선택한 조로 저장", by_emp.get(emp1) == team_a and by_emp.get(emp2) == team_b)
check("첫 번째 조/A조 강제 fallback 없음", by_emp.get(emp2) != team_a)

# 기존 직원의 조 변경(같은 직원·월 upsert = 교체와 동일 경로) 후에도 새 조 유지
db.upsert_month_assignments([
    {"emp_no": emp1, "schedule_month": (2027, 7), "dept_code": dept,
     "team_code": team_b, "shift_group_code": ""},
], require_shift=False)
back2 = db.get_month_assignments(2027, 7, [emp1])
check("조 변경 저장 후 새 조 유지", str(back2.iloc[0]["team_code"]) == team_b)

# users 기준정보는 변경되지 않음
after = db.get_users()
check("users.team_code 무변경", after.equals(users))

# 기본 계약(require_shift=True)은 그대로 — 근무조 없는 저장 차단
try:
    db.upsert_month_assignments([
        {"emp_no": emp1, "schedule_month": (2027, 7), "dept_code": dept,
         "team_code": team_a, "shift_group_code": ""},
    ])
    check("require_shift 기본값에서 근무조 필수 유지", False)
except ValueError:
    check("require_shift 기본값에서 근무조 필수 유지", True)

print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
