"""조직 관리 통합 화면 계약 테스트 (sample 모드, Supabase 미접속).

- 부서 관리/조 관리 메뉴가 같은 통합 화면(조직 관리)을 여는지
- 그룹순서 전역 유일 / 같은 그룹 내 부서순서 유일 / 그룹순서 상속
- 운영단위(교대·일반) 코드/명칭/표시순서 중복 차단, 유형 허용값 검증
- 선택 부서 없이 운영단위 저장 차단
- 003 미적용 상태 폴백 기본값(org_dept_defaults/org_team_defaults)
- sample 스토어 저장 왕복(unit_type/그룹 컬럼 보존)

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_master_org.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

import pandas as pd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from modules import db, nav  # noqa: E402
from views import master_org  # noqa: E402

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


def _meta_rows(rows):
    frame = pd.DataFrame(rows)
    if "_removed" not in frame:
        frame["_removed"] = ""
    return frame


# ===== 1) 두 메뉴 → 같은 통합 화면 =====
print("부서 관리/조 관리 메뉴 → 조직 관리 통합 화면")


def _screen_departments_menu():
    from modules import db
    from views import master_departments
    master_departments.render(db.find_user_by_emp_no("1001"))


def _screen_teams_menu():
    from modules import db
    from views import master_teams
    master_teams.render(db.find_user_by_emp_no("1001"))


for label, fn in (("부서 관리", _screen_departments_menu), ("조 관리", _screen_teams_menu)):
    at = AppTest.from_function(fn, default_timeout=45).run()
    check(f"{label} 메뉴 렌더 예외 없음", not at.exception)
    body = " ".join(str(m.value) for m in at.markdown)
    check(f"{label} 메뉴가 조직 관리 화면을 표시", "조직 관리" in body)
    check(f"{label} 좌측 패널(그룹·부서) 표시", "그룹·부서" in body)
    check(f"{label} 우측 패널(운영단위) 표시", "운영단위" in body)


# ===== 2) 그룹·부서 검증 =====
print("그룹·부서 검증 (_validate_departments / _group_structure_errors)")
store = db.get_org_departments()
d0 = store.iloc[0]
g0 = str(d0["department_group"])
g0_order = int(d0["group_sort_order"])

# 그룹순서 빈 값 → 기존 그룹 순서 상속
recs, errs = master_org._validate_departments(_meta_rows([
    {"그룹명": g0, "그룹순서": "", "부서코드": "NEWD", "부서명": "신규부서", "부서순서": "9", "사용": True},
]), store)
check("기존 그룹의 그룹순서 상속", recs and recs[0]["group_sort_order"] == g0_order)
check("정상 행 오류 없음", not errs)

# 새 그룹인데 그룹순서 없음 → 차단
_r, errs2 = master_org._validate_departments(_meta_rows([
    {"그룹명": "완전새그룹", "그룹순서": "", "부서코드": "NEWD2", "부서명": "신규부서2", "부서순서": "1", "사용": True},
]), store)
check("새 그룹의 그룹순서 미입력 차단", any("그룹순서" in e for e in errs2))

# 필수값
_r, errs3 = master_org._validate_departments(_meta_rows([
    {"그룹명": "", "그룹순서": "1", "부서코드": "NEWD3", "부서명": "신규부서3", "부서순서": "1", "사용": True},
]), store)
check("그룹명 미입력 차단", any("그룹명" in e for e in errs3))

# 편집 행의 명시 그룹순서가 저장값보다 우선 (그룹 순서 변경 편집)
recs4, _e4 = master_org._validate_departments(_meta_rows([
    {"그룹명": g0, "그룹순서": "77", "부서코드": "NEWA", "부서명": "가", "부서순서": "1", "사용": True},
    {"그룹명": g0, "그룹순서": "", "부서코드": "NEWB", "부서명": "나", "부서순서": "2", "사용": True},
]), store)
check("편집 중 명시한 그룹순서를 빈 행이 상속", all(r["group_sort_order"] == 77 for r in recs4))

# 구조 검증: 그룹순서 전역 유일
g_err = master_org._group_structure_errors(pd.DataFrame([
    {"dept_code": "D1", "dept_name": "부서1", "department_group": "PET", "group_sort_order": 1, "sort_order": 1, "is_active": True},
    {"dept_code": "D2", "dept_name": "부서2", "department_group": "PVC", "group_sort_order": 1, "sort_order": 1, "is_active": True},
]))
check("그룹 간 그룹순서 중복 차단", any("여러 그룹" in e for e in g_err))

# 같은 그룹인데 그룹순서가 서로 다름
g_err2 = master_org._group_structure_errors(pd.DataFrame([
    {"dept_code": "D1", "dept_name": "부서1", "department_group": "PET", "group_sort_order": 1, "sort_order": 1, "is_active": True},
    {"dept_code": "D2", "dept_name": "부서2", "department_group": "PET", "group_sort_order": 2, "sort_order": 2, "is_active": True},
]))
check("같은 그룹의 그룹순서 불일치 차단", any("서로 다릅니다" in e for e in g_err2))

# 같은 그룹 내 부서순서 중복
g_err3 = master_org._group_structure_errors(pd.DataFrame([
    {"dept_code": "D1", "dept_name": "부서1", "department_group": "PET", "group_sort_order": 1, "sort_order": 1, "is_active": True},
    {"dept_code": "D2", "dept_name": "부서2", "department_group": "PET", "group_sort_order": 1, "sort_order": 1, "is_active": True},
]))
check("같은 그룹 내 부서순서 중복 차단", any("부서순서" in e for e in g_err3))

# 정상 구조는 오류 없음 (그룹 2개, 순서 유일)
g_ok = master_org._group_structure_errors(pd.DataFrame([
    {"dept_code": "D1", "dept_name": "부서1", "department_group": "PET", "group_sort_order": 1, "sort_order": 1, "is_active": True},
    {"dept_code": "D2", "dept_name": "부서2", "department_group": "PET", "group_sort_order": 1, "sort_order": 2, "is_active": True},
    {"dept_code": "D3", "dept_name": "부서3", "department_group": "PVC", "group_sort_order": 2, "sort_order": 1, "is_active": True},
]))
check("정상 그룹 구조 통과", not g_ok)


# ===== 3) 운영단위 검증 =====
print("운영단위 검증 (_validate_units / _unit_structure_errors)")
dcode = str(store.iloc[0]["dept_code"])
recs, errs = master_org._validate_units(_meta_rows([
    {"코드": "A", "명칭": "A조", "유형": "교대", "표시순서": "1", "사용": True},
    {"코드": "N9", "명칭": "나인투식스", "유형": "일반", "표시순서": "2", "사용": True},
    {"코드": "RG", "명칭": "상근", "유형": "GENERAL", "표시순서": "3", "사용": True},
    {"코드": "BAD", "명칭": "이상", "유형": "심야", "표시순서": "4", "사용": True},
    {"코드": "", "명칭": "", "유형": "", "표시순서": "", "사용": True},
]), dcode)
check("교대→SHIFT 변환", recs[0]["unit_type"] == "SHIFT")
check("일반→GENERAL 변환", recs[1]["unit_type"] == "GENERAL")
check("내부값 직접 입력(GENERAL) 허용", recs[2]["unit_type"] == "GENERAL")
check("허용 외 유형 차단", any("유형" in e for e in errs))
check("빈 행 제외", len(recs) == 4)
check("모든 행에 선택 부서 부여", all(r["dept_code"] == dcode for r in recs))

u_err = master_org._unit_structure_errors(pd.DataFrame([
    {"dept_code": dcode, "team_code": "A", "team_name": "같은명", "unit_type": "SHIFT", "sort_order": 1, "is_active": True},
    {"dept_code": dcode, "team_code": "B", "team_name": "같은명", "unit_type": "GENERAL", "sort_order": 1, "is_active": True},
    {"dept_code": "OTHER", "team_code": "C", "team_name": "같은명", "unit_type": "SHIFT", "sort_order": 1, "is_active": True},
]), dcode)
check("부서 내 명칭 중복 차단", any("명칭" in e for e in u_err))
check("부서 내 표시순서 중복 차단", any("표시순서" in e for e in u_err))
check("다른 부서 행은 검증 대상 아님", all("C" not in e.split(":")[-1] for e in u_err))

# 코드 중복은 upsert_records 의 자연키 중복으로 검출
_merged, dup, _c, _u, _d = db.upsert_records(
    db.get_org_teams(),
    [
        {"dept_code": dcode, "team_code": "ZZ", "team_name": "가", "unit_type": "SHIFT", "sort_order": 91, "is_active": True},
        {"dept_code": dcode, "team_code": "ZZ", "team_name": "나", "unit_type": "SHIFT", "sort_order": 92, "is_active": True},
    ],
    set(), ["dept_code", "team_code"], "is_active", db.ORG_TEAM_COLUMNS,
)
check("부서 내 운영단위 코드 중복 검출", (dcode, "ZZ") in dup)


# ===== 4) 선택 부서 없이 운영단위 저장 차단 =====
print("선택 부서 없이 저장 차단")


def _screen_save_units_without_dept():
    from views import master_org
    master_org._save_units(None, "")


at = AppTest.from_function(_screen_save_units_without_dept, default_timeout=45).run()
check("저장 차단 오류 표시", any("부서를 먼저 선택" in str(e.value) for e in at.error))


# ===== 5) 003 미적용 폴백 기본값 =====
print("확장 컬럼 폴백 기본값 (org_dept_defaults / org_team_defaults)")
plain = pd.DataFrame([
    {"dept_code": "B2", "dept_name": "부서B", "sort_order": 2, "is_active": True},
    {"dept_code": "A1", "dept_name": "부서A", "sort_order": 1, "is_active": True},
])
fallback = db.org_dept_defaults(plain)
check("그룹명 기본값 = 부서명", list(fallback["department_group"]) == ["부서B", "부서A"])
orders = sorted(fallback["group_sort_order"])
check("그룹순서 기본값은 전역 유일(1..N)", orders == [1, 2])
check("sort_order 낮은 부서가 앞 순서",
      int(fallback.loc[fallback["dept_code"] == "A1", "group_sort_order"].iloc[0]) == 1)

teams_plain = pd.DataFrame([
    {"dept_code": "A1", "team_code": "A", "team_name": "A조", "sort_order": 1, "is_active": True},
])
t_fallback = db.org_team_defaults(teams_plain)
check("unit_type 기본값 SHIFT(교대)", str(t_fallback.iloc[0]["unit_type"]) == "SHIFT")
mixed = db.org_team_defaults(pd.DataFrame([
    {"dept_code": "A1", "team_code": "A", "team_name": "A조", "unit_type": "general", "sort_order": 1, "is_active": True},
    {"dept_code": "A1", "team_code": "B", "team_name": "B조", "unit_type": "잘못", "sort_order": 2, "is_active": True},
]))
check("소문자 general 정규화", str(mixed.iloc[0]["unit_type"]) == "GENERAL")
check("비정상 unit_type 은 SHIFT 로 정규화", str(mixed.iloc[1]["unit_type"]) == "SHIFT")


# ===== 6) sample 스토어 저장 왕복 =====
print("sample 저장 왕복 (그룹·unit_type 보존)")
orig_depts = db.get_org_departments()
edited = orig_depts.copy()
edited.loc[edited.index[0], "department_group"] = "TESTGRP"
edited.loc[edited.index[0], "group_sort_order"] = 91
db.save_org_departments(edited)
again = db.get_org_departments()
row = again[again["dept_code"] == orig_depts.iloc[0]["dept_code"]].iloc[0]
check("그룹명 저장 왕복 보존", str(row["department_group"]) == "TESTGRP")
check("그룹순서 저장 왕복 보존", int(row["group_sort_order"]) == 91)
db.save_org_departments(orig_depts)  # 원복

orig_teams = db.get_org_teams()
edited_t = orig_teams.copy()
edited_t.loc[edited_t.index[0], "unit_type"] = "GENERAL"
db.save_org_teams(edited_t)
again_t = db.get_org_teams()
row_t = again_t.iloc[0]
check("unit_type 저장 왕복 보존", str(row_t["unit_type"]) == "GENERAL")
db.save_org_teams(orig_teams)  # 원복

check("일반 화면 계약(get_teams TEAM_COLUMNS)에 영향 없음",
      list(db.get_teams()[db.TEAM_COLUMNS].columns) == db.TEAM_COLUMNS)
check("일반 화면 계약(get_departments DEPT_COLUMNS)에 영향 없음",
      list(db.get_departments()[db.DEPT_COLUMNS].columns) == db.DEPT_COLUMNS)


# ===== 7) 권한 라우팅 (사이드바 메뉴 계약 유지) =====
print("권한 라우팅 (메뉴 id 유지)")
for page in ("master_departments", "master_teams"):
    check(f"{page} 메뉴 id 유지(ADMIN 허용)", nav.allowed(page, "ADMIN"))
    check(f"{page} USER 접근 불가", not nav.allowed(page, "USER"))
check("메뉴 라벨 무변경(부서 관리)", nav.page_label("master_departments") == "부서 관리")
check("메뉴 라벨 무변경(조 관리)", nav.page_label("master_teams") == "조 관리")


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
