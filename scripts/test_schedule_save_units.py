"""근무표 편성 — 혼합 저장 분류·약칭 해석 계약 단위 테스트 (bare mode).

실행: .venv/Scripts/python.exe scripts/test_schedule_save_units.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
