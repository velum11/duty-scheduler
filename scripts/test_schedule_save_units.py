"""근무표 편성 — 혼합 저장 분류·약칭 해석·조 스냅샷·행 순서 영속 단위 테스트 (bare mode).

실행: .venv/Scripts/python.exe scripts/test_schedule_save_units.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DUTY_DATA_MODE"] = "sample"  # Supabase 미접속 보장

import pandas as pd  # noqa: E402

from modules import db  # noqa: E402
from views.schedule_edit import (  # noqa: E402
    classify_save_targets, _order_moved, _resolve_work, _visible_emp_order,
)

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


# ===========================================================================
# 행 드래그 순서 영속 — 슬롯 재배정 순수 함수 (db.plan_display_order_slots)
# ===========================================================================
print("_visible_emp_order (화면 행 → 사번 시퀀스)")
_rows = pd.DataFrame({"사번": ["1002", " 1001 ", "", "1002", None, "1003"]})
check("공백 정규화·빈 행·중복 제거 후 화면 순서 유지",
      _visible_emp_order(_rows) == ["1002", "1001", "1003"])
check("빈 프레임은 빈 리스트", _visible_emp_order(pd.DataFrame()) == [])

print("_order_moved (표시용 '순서 변경' 판정 — 추가·삭제 중복 계상 방지)")
check("맞바꾸면 변경", _order_moved(["a", "b", "c"], ["b", "a", "c"]) is True)
check("그대로면 무변경", _order_moved(["a", "b", "c"], ["a", "b", "c"]) is False)
check("행 삭제만 하면 순서 변경 아님(삭제 건수로 이미 셈)",
      _order_moved(["a", "b", "c"], ["a", "c"]) is False)
check("행 추가만 하면 순서 변경 아님", _order_moved(["a", "b"], ["a", "x", "b"]) is False)
check("추가 + 실제 이동은 변경", _order_moved(["a", "b"], ["b", "x", "a"]) is True)

print("plan_display_order_slots (부서그룹 단위 슬롯 재배정)")
# G1 = D1·D2(같은 그룹), G2 = D3. h9 는 화면에 안 보이는 '숨은' 사용자다.
_users = pd.DataFrame([
    {"emp_no": "a1", "dept_code": "D1", "is_active": True, "display_order": 10},
    {"emp_no": "a2", "dept_code": "D2", "is_active": True, "display_order": 20},
    {"emp_no": "a3", "dept_code": "D1", "is_active": True, "display_order": 30},
    {"emp_no": "h9", "dept_code": "D1", "is_active": True, "display_order": 40},
    {"emp_no": "b1", "dept_code": "D3", "is_active": True, "display_order": 5},
    {"emp_no": "b2", "dept_code": "D3", "is_active": True, "display_order": 15},
    {"emp_no": "n1", "dept_code": "D1", "is_active": True, "display_order": None},
    {"emp_no": "x1", "dept_code": "D1", "is_active": False, "display_order": 70},
])
_groups = {"D1": ("G1", 0), "D2": ("G1", 0), "D3": ("G2", 1)}

# (1) 그룹 2개 혼재 — 각 그룹이 자기 슬롯 안에서만 재배정된다.
pairs = dict(db.plan_display_order_slots(
    ["a3", "b2", "a1", "a2", "b1"], _users, _groups))
check("G1: 시각 순서 a3,a1,a2 가 점유 슬롯 10/20/30 에 재배정",
      pairs.get("a3") == 10 and pairs.get("a1") == 20 and pairs.get("a2") == 30)
check("G2: 시각 순서 b2,b1 이 점유 슬롯 5/15 에 재배정",
      pairs.get("b2") == 5 and pairs.get("b1") == 15)
check("숨은 사용자(h9)·비활성(x1) 은 대상 아님",
      "h9" not in pairs and "x1" not in pairs)
check("그룹 경계를 넘어 번호가 섞이지 않음(모든 값이 자기 그룹 슬롯 안)",
      set(pairs.values()) == {10, 20, 30, 5, 15})

# (2) 변경분만 diff — 순서를 그대로 두면 쓸 것이 없다.
check("순서 무변경이면 빈 목록",
      db.plan_display_order_slots(["a1", "a2", "a3", "b1", "b2"], _users, _groups) == [])
check("일부만 바뀌면 바뀐 사용자만 반환(그대로인 a1 제외)",
      dict(db.plan_display_order_slots(["a1", "a3", "a2"], _users, _groups))
      == {"a3": 20, "a2": 30})

# (3) NULL(미지정) 순서 — 슬롯이 모자라면 그룹 전체 최대(숨은 h9=40, 비활성 x1=70)
#     기준 +10 으로 연장한다. 연장값은 그룹의 어떤 기존 번호보다도 크다.
pairs_null = dict(db.plan_display_order_slots(["n1", "a1", "a2", "a3"], _users, _groups))
check("NULL 사용자 포함 시 점유 슬롯(10/20/30) + 그룹최대(70)+10 으로 연장",
      pairs_null == {"n1": 10, "a1": 20, "a2": 30, "a3": 80})
check("연장 슬롯이 숨은 사용자(40)·비활성(70) 번호와 충돌하지 않음",
      all(v not in (40, 70) for v in pairs_null.values()))
check("연장 후에도 시각 순서 = 번호 오름차순",
      [pairs_null[e] for e in ["n1", "a1", "a2", "a3"]]
      == sorted(pairs_null[e] for e in ["n1", "a1", "a2", "a3"]))

# (4) 미등록 사번·중복 사번 방어.
check("users 에 없는 사번은 무시",
      dict(db.plan_display_order_slots(["zzz", "a3", "a1", "a2"], _users, _groups))
      == {"a3": 10, "a1": 20, "a2": 30})
check("같은 사번이 두 번 나와도 첫 등장만 사용",
      dict(db.plan_display_order_slots(["a3", "a3", "a1", "a2"], _users, _groups))
      == {"a3": 10, "a1": 20, "a2": 30})

# (5) 부서→그룹 매핑이 없는 부서는 dept_code 자체가 그룹키(display_order_conflicts 와 동일).
#     같은 G1 이던 D1·D2 가 갈라지므로 a2(D3 아님, D2 단독)는 자기 슬롯 20 을 유지하고
#     a3·a1(D1)만 서로 슬롯을 맞바꾼다.
check("매핑 없는 부서는 dept_code 를 그룹키로 분리 처리",
      dict(db.plan_display_order_slots(["a3", "a1", "a2", "b2", "b1"], _users, {}))
      == {"a3": 10, "a1": 30, "b2": 5, "b1": 15})

# (6) 기존 중복 점유는 접어서 연장 슬롯으로 메운다(중복을 복제하지 않는다).
_dup = pd.DataFrame([
    {"emp_no": "d1", "dept_code": "D1", "is_active": True, "display_order": 10},
    {"emp_no": "d2", "dept_code": "D1", "is_active": True, "display_order": 10},
])
dup_pairs = dict(db.plan_display_order_slots(["d2", "d1"], _dup, _groups))
check("중복 번호는 하나로 접고 연장 슬롯 부여(d2=10 유지 · d1=20 으로 분리)",
      dup_pairs == {"d1": 20})

# (7) 빈 입력 방어.
check("사용자 프레임이 비면 빈 목록",
      db.plan_display_order_slots(["a1"], pd.DataFrame(), _groups) == [])
check("보이는 행이 없으면 빈 목록",
      db.plan_display_order_slots([], _users, _groups) == [])

print("update_users_display_order (sample 모드 — 대상 사용자만 갱신 · 재정렬 왕복)")
# 같은 부서 사용자 2명을 대상으로 잡는다(정렬 1차 축이 부서그룹이므로, 순서 왕복을
# 검증하려면 같은 그룹 안이어야 한다 — 편성 화면의 실제 제약과 동일한 조건).
_before = db.get_users()
_same_dept = _before.groupby("dept_code").filter(lambda g: len(g) >= 3)
_dept = str(_same_dept["dept_code"].iloc[0])
_in_dept = _same_dept[_same_dept["dept_code"].astype(str) == _dept]
_targets = [str(e) for e in _in_dept["emp_no"].astype(str).iloc[:2]]
_untouched = str(_in_dept["emp_no"].astype(str).iloc[2])
_by_emp_before = _before.set_index(_before["emp_no"].astype(str))
_orig_untouched = _by_emp_before.loc[_untouched, "display_order"]

n = db.update_users_display_order([(_targets[0], 900), (_targets[1], 800)])
_after = db.get_users()
_by_emp_after = _after.set_index(_after["emp_no"].astype(str))
check("갱신 건수 반환", n == 2)
check("대상 사용자만 값이 바뀜",
      int(_by_emp_after.loc[_targets[0], "display_order"]) == 900
      and int(_by_emp_after.loc[_targets[1], "display_order"]) == 800)
check("대상 아닌 사용자는 무변경",
      (pd.isna(_orig_untouched) and pd.isna(_by_emp_after.loc[_untouched, "display_order"]))
      or _by_emp_after.loc[_untouched, "display_order"] == _orig_untouched)
check("사용자 수·다른 컬럼은 그대로(전량 upsert 아님)",
      len(_after) == len(_before)
      and _after.drop(columns=["display_order"]).equals(_before.drop(columns=["display_order"])))
check("빈 목록·빈 사번·순서 None 은 아무것도 쓰지 않음",
      db.update_users_display_order([]) == 0
      and db.update_users_display_order([("", 1), (_targets[0], None)]) == 0)
# 저장 결과가 실제 표시 정렬(편성 화면 재조회 경로)에 반영되는가.
_sorted = db.sort_users_for_display(_after[_after["emp_no"].astype(str).isin(_targets)])
check("sort_users_for_display 가 새 표시순서를 반영(800 < 900)",
      list(_sorted["emp_no"].astype(str)) == [_targets[1], _targets[0]])

print("행 순서 왕복 (sample: 로드 → 재정렬 → 영속 → 재조회) · 그룹 경계 한계")
import streamlit as st  # noqa: E402
from views import schedule_edit as se  # noqa: E402

_q = {"year": 2026, "month": 7, "dept": "(전체)", "team": "(전체)"}
st.session_state["q_schedule_edit"] = _q
se._load_grid(_q)
_loaded = list(st.session_state["se_order_base"])
check("샘플 근무 보유자가 로드됨(왕복 검증 전제)", len(_loaded) >= 4)

_gmap = db.dept_group_map()
_all_users = db.get_users()
_group_of = {
    str(r["emp_no"]).strip(): _gmap.get(
        str(r["dept_code"]).strip(), (str(r["dept_code"]).strip(), 0))[0]
    for _, r in _all_users.iterrows()
}
_hidden = {
    str(r["emp_no"]).strip(): r["display_order"]
    for _, r in _all_users.iterrows()
    if str(r["emp_no"]).strip() not in _loaded
}


def _live_in_order(order):
    """se_rows 를 주어진 사번 순서로 재배열한 '화면 최종 상태' 프레임."""
    rows = st.session_state["se_rows"]
    keyed = rows.set_index(rows["사번"].astype(str).str.strip())
    return keyed.loc[order].reset_index(drop=True)


# (a) 같은 부서그룹 안에서 인접 두 행 맞바꾸기 → 재조회에서 그대로 유지된다.
_i = next(i for i in range(len(_loaded) - 1)
          if _group_of[_loaded[i]] == _group_of[_loaded[i + 1]])
_swapped = list(_loaded)
_swapped[_i], _swapped[_i + 1] = _swapped[_i + 1], _swapped[_i]
_n_order, _err = se._persist_row_order(_live_in_order(_swapped))
check("같은 그룹 내 이동 → 표시순서 영속 발생(오류 없음)", _n_order > 0 and _err == "")
se._load_grid(_q)
check("재조회 순서 = 드래그한 순서(왕복 유지)",
      list(st.session_state["se_order_base"]) == _swapped)
check("순서를 다시 안 바꾸면 아무것도 쓰지 않음",
      se._persist_row_order(_live_in_order(_swapped)) == (0, ""))
_after_hidden = {
    str(r["emp_no"]).strip(): r["display_order"]
    for _, r in db.get_users().iterrows()
    if str(r["emp_no"]).strip() in _hidden
}
check("화면에 없던 사용자의 표시순서는 불변",
      all((pd.isna(v) and pd.isna(_after_hidden[k])) or v == _after_hidden[k]
          for k, v in _hidden.items()))
check("영속 후에도 그룹 내 표시순서 중복 없음",
      db.display_order_conflicts(db.get_users(), _gmap) == [])

# (b) 그룹 경계를 넘는 이동은 왕복하지 않는다 — 정렬 1차 축이 부서그룹이라는 알려진 한계.
_other = next((e for e in _swapped if _group_of[e] != _group_of[_swapped[0]]), None)
check("검증 전제: 로드 명단에 다른 부서그룹 직원이 있다", _other is not None)
if _other is not None:
    _crossed = [_other] + [e for e in _swapped if e != _other]
    se._persist_row_order(_live_in_order(_crossed))
    se._load_grid(_q)
    check("그룹 경계를 넘는 이동은 재조회에서 그룹 순서로 복원(문서화된 한계)",
          list(st.session_state["se_order_base"])[0] != _other)
    check("그 경우에도 그룹 내 중복은 생기지 않음",
          db.display_order_conflicts(db.get_users(), _gmap) == [])

print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
