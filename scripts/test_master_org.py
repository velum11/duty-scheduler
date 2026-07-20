"""조직 관리 통합 화면 계약 테스트 (sample 모드, Supabase 미접속).

- 부서 관리/조 관리 메뉴가 같은 통합 화면(조직 관리)을 여는지
- 가상 그룹 부모 + 부서 자식 행 모델(build_org_rows): 그룹은 한 번만, 부서는 자식으로
- 그룹명·그룹순서는 그룹 행에서 1회 편집 → 소속 부서 전체(화면 밖 포함)로 자동 전파
- 그룹순서 전역 유일 / 같은 그룹 순서 단일 / **부서순서 중복은 허용**(코드 보조 정렬)
- 빈 새 그룹 저장 차단, 소속그룹 필수, casefold 그룹 병합(순서 불일치 차단)
- users.display_order: 그룹 기준 활성 사용자 중복 차단(부서 기준 아님), NULL 허용,
  그룹 병합·부서 이동 후 예상 구조 기준 충돌 차단, NULL 은 뒤 + 사번 보조 정렬
- 운영단위(교대/일반) 코드·명칭·표시순서 중복 차단, SHIFT 백필 계약
- 003 미적용 폴백/저장 차단, sample 저장 왕복, 사이드바 메뉴 계약 유지

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
from views import master_org, master_users  # noqa: E402

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


def _dept(code, name, group, g_order, order, active=True):
    return {
        "dept_code": code, "dept_name": name, "department_group": group,
        "group_sort_order": g_order, "sort_order": order, "is_active": active,
    }


def _grow(gid, name, order):
    return {"_row_id": gid, "_row_state": "group", "_sel": False,
            "그룹·부서명": name, "순서": str(order) if order != "" else "",
            "소속그룹": "", "부서코드": "", "사용": True}


def _drow(rid, name, order, parent, code, state="existing", active=True):
    return {"_row_id": rid, "_row_state": state, "_sel": False,
            "그룹·부서명": name, "순서": str(order) if order != "" else "",
            "소속그룹": parent, "부서코드": code, "사용": active}


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


# ===== 2) 계층 행 모델 (그룹 부모 + 부서 자식) =====
print("build_org_rows — 그룹 부모/부서 자식 계층 모델")
src = pd.DataFrame([
    _dept("PET1", "PET생산부", "PET", 1, 1),
    _dept("PET2", "PET원료실", "PET", 1, 1),   # 부서순서 중복(허용) — 코드 보조 정렬
    _dept("PVC1", "PVC생산부", "PVC", 2, 1),
])
rows = master_org.build_org_rows(src)
groups = rows[rows["_row_state"] == "group"]
depts = rows[rows["_row_state"] != "group"]
check("그룹 부모 행이 그룹당 한 번만 생성", len(groups) == 2)
check("부서가 자식 행으로 모두 포함", len(depts) == 3)
check("PET 그룹 아래 PET생산부·PET원료실이 함께 묶임",
      list(rows["_row_id"])[:3] == ["g:PET", "e:PET1", "e:PET2"])
check("부서순서 동률은 부서코드 보조 정렬", list(depts["부서코드"])[:2] == ["PET1", "PET2"])
check("그룹 행에 그룹명·그룹순서 표시(1회)",
      str(groups.iloc[0]["그룹·부서명"]) == "PET" and str(groups.iloc[0]["순서"]) == "1")
check("부서 행에는 그룹순서 없음(순서=부서순서)", str(depts.iloc[0]["순서"]) == "1")
check("부서 행 소속그룹은 로드 시점 그룹 라벨", set(depts["소속그룹"]) == {"PET", "PVC"})
check("그룹 행 부서코드 셀은 요약 표시", "부서" in str(groups.iloc[0]["부서코드"]))


# ===== 3) parse_org_grid — 그룹 1회 편집 → 자식 전파 =====
print("parse_org_grid — 그룹 편집 전파·검증")
store = src.copy()

# 그룹명 변경이 화면(1개 부서)과 화면 밖(PET2) 모두로 전파
live = _meta_rows([
    _grow("g:PET", "PET그룹", 1),           # 이름 변경 (PET → PET그룹)
    _drow("e:PET1", "PET생산부", 1, "PET", "PET1"),
    # PET2 는 필터로 화면에 없음 — store 전파 대상
    _grow("g:PVC", "PVC", 2),
    _drow("e:PVC1", "PVC생산부", 1, "PVC", "PVC1"),
])
recs, errs = master_org.parse_org_grid(live, store)
check("정상 편집 오류 없음", not errs)
by_code = {r["dept_code"]: r for r in recs}
check("그룹명 변경이 화면 부서에 전파", by_code["PET1"]["department_group"] == "PET그룹")
check("그룹명 변경이 화면 밖 같은 그룹 부서에도 전파",
      "PET2" in by_code and by_code["PET2"]["department_group"] == "PET그룹")
check("그룹순서가 자식 전체에 공유", by_code["PET1"]["group_sort_order"] == 1
      and by_code["PET2"]["group_sort_order"] == 1)

# 그룹순서 변경 전파
live2 = _meta_rows([
    _grow("g:PET", "PET", 7),               # 순서 변경 1 → 7
    _drow("e:PET1", "PET생산부", 1, "PET", "PET1"),
])
recs2, errs2 = master_org.parse_org_grid(live2, store)
by2 = {r["dept_code"]: r for r in recs2}
check("그룹순서 변경이 화면·화면 밖 자식 모두로 전파",
      by2["PET1"]["group_sort_order"] == 7 and by2["PET2"]["group_sort_order"] == 7)

# 부서 행에서는 그룹값을 입력하지 않음 — 소속그룹 선택만으로 그룹값 자동 부여
live3 = _meta_rows([
    _grow("g:PET", "PET", 1),
    _drow("n:1", "PET신규부", 5, "PET", "PETN", state="new"),
])
recs3, errs3 = master_org.parse_org_grid(live3, store)
by3 = {r["dept_code"]: r for r in recs3}
check("신규 부서가 소속그룹 선택만으로 그룹명·그룹순서 자동 부여",
      by3["PETN"]["department_group"] == "PET" and by3["PETN"]["group_sort_order"] == 1)
check("신규 부서 오류 없음", not errs3)

# 소속그룹 미선택/미존재 차단
_r, errs4 = master_org.parse_org_grid(_meta_rows([
    _drow("n:2", "무소속부", 1, "", "XX", state="new"),
]), store)
check("소속그룹 미선택 차단", any("소속그룹" in e for e in errs4))
_r, errs5 = master_org.parse_org_grid(_meta_rows([
    _drow("n:3", "이상부", 1, "없는그룹", "YY", state="new"),
]), store)
check("존재하지 않는 그룹 차단", any("존재하지 않는" in e for e in errs5))

# 빈 새 그룹 차단 + 새 그룹 정상 생성
_r, errs6 = master_org.parse_org_grid(_meta_rows([
    _grow("gn:1", "DECO", 3),
]), store)
check("부서 없는 새 그룹 저장 차단", any("부서가 없습니다" in e for e in errs6))
recs7, errs7 = master_org.parse_org_grid(_meta_rows([
    _grow("gn:1", "DECO", 3),
    _drow("n:4", "DECO생산부", 1, "(신규 그룹 1)", "DEC1", state="new"),
]), store)
check("새 그룹 + 첫 부서 저장 가능", not errs7
      and recs7 and recs7[0]["department_group"] == "DECO" and recs7[0]["group_sort_order"] == 3)

# 새 그룹 이름/순서 필수
_r, errs8 = master_org.parse_org_grid(_meta_rows([
    _grow("gn:2", "", ""),
    _drow("n:5", "새부서", 1, "(신규 그룹 2)", "NEW2", state="new"),
]), store)
check("새 그룹 그룹명 필수", any("그룹명" in e for e in errs8))
check("새 그룹 그룹순서 필수", any("그룹순서" in e for e in errs8))

# casefold 병합 — 이름 같고 순서 다르면 차단
_r, errs9 = master_org.parse_org_grid(_meta_rows([
    _grow("g:PET", "합쳐짐", 1),
    _drow("e:PET1", "PET생산부", 1, "PET", "PET1"),
    _grow("g:PVC", "합쳐짐", 2),
    _drow("e:PVC1", "PVC생산부", 1, "PVC", "PVC1"),
]), store)
check("병합 그룹의 그룹순서 불일치 차단", any("병합" in e for e in errs9))
recs10, errs10 = master_org.parse_org_grid(_meta_rows([
    _grow("g:PET", "통합", 1),
    _drow("e:PET1", "PET생산부", 1, "PET", "PET1"),
    _grow("g:PVC", "통합", 1),
    _drow("e:PVC1", "PVC생산부", 2, "PVC", "PVC1"),
]), store)
check("이름·순서가 같으면 그룹 병합 허용", not errs10
      and {r["department_group"] for r in recs10} == {"통합"})

# 부서순서 중복 허용 (같은 그룹 1·1)
recs11, errs11 = master_org.parse_org_grid(_meta_rows([
    _grow("g:PET", "PET", 1),
    _drow("e:PET1", "PET생산부", 1, "PET", "PET1"),
    _drow("e:PET2", "PET원료실", 1, "PET", "PET2"),
]), store)
check("같은 그룹 부서순서 중복 허용(저장 차단 없음)", not errs11)


# ===== 4) 구조 검증 (merged 기준) =====
print("_group_structure_errors — 그룹순서 검증(부서순서는 자유)")
g_err = master_org._group_structure_errors(pd.DataFrame([
    _dept("D1", "부서1", "PET", 1, 1), _dept("D2", "부서2", "PVC", 1, 1),
]))
check("그룹 간 그룹순서 중복 차단", any("여러 그룹" in e for e in g_err))
g_err2 = master_org._group_structure_errors(pd.DataFrame([
    _dept("D1", "부서1", "PET", 1, 1), _dept("D2", "부서2", "PET", 2, 2),
]))
check("같은 그룹의 그룹순서 불일치 차단", any("서로 다릅니다" in e for e in g_err2))
g_ok = master_org._group_structure_errors(pd.DataFrame([
    _dept("D1", "부서1", "PET", 1, 1),
    _dept("D2", "부서2", "PET", 1, 1),   # 부서순서 중복 — 허용
    _dept("D3", "부서3", "PVC", 2, 1),
]))
check("같은 그룹 부서순서 중복은 구조 오류 아님", not g_ok)


# ===== 5) users.display_order — 그룹 기준 충돌 =====
print("users.display_order — 그룹 기준 검증·정렬")
group_map = {"PET1": ("PET", 1), "PET2": ("PET", 1), "PVC1": ("PVC", 2)}


def _user(emp, dept, order, active=True, name="사용자"):
    return {"emp_no": emp, "name": name, "dept_code": dept, "team_code": "A",
            "position": "", "role": "USER", "is_active": active, "display_order": order}


check("display_order NULL 허용(검증 통과)", not db.display_order_conflicts(
    pd.DataFrame([_user("U1", "PET1", None), _user("U2", "PET1", None)]), group_map))
conf = db.display_order_conflicts(
    pd.DataFrame([_user("U1", "PET1", 1), _user("U2", "PET2", 1)]), group_map)
check("같은 그룹(PET생산부+PET원료실) 표시순서 1 중복 차단", any("PET" in e and "1" in e for e in conf))
check("다른 그룹 동일 표시순서 허용", not db.display_order_conflicts(
    pd.DataFrame([_user("U1", "PET1", 1), _user("U3", "PVC1", 1)]), group_map))
check("비활성 사용자 번호는 충돌에서 제외", not db.display_order_conflicts(
    pd.DataFrame([_user("U1", "PET1", 1), _user("U2", "PET2", 1, active=False)]), group_map))

# 부서 이동 후 충돌: U3 이 PVC1 → PET2 로 이동하면 PET 그룹에서 1 충돌
moved = pd.DataFrame([_user("U1", "PET1", 1), _user("U3", "PET2", 1)])
check("부서 이동 후 대상 그룹 충돌 차단", bool(db.display_order_conflicts(moved, group_map)))

# 그룹 병합 후 충돌: PET·PVC 를 같은 그룹으로 합치면 1 충돌 (저장 후 예상 구조 기준)
merged_map = {"PET1": ("통합", 1), "PET2": ("통합", 1), "PVC1": ("통합", 1)}
check("그룹 병합 후 예상 구조 기준 충돌 차단", bool(db.display_order_conflicts(
    pd.DataFrame([_user("U1", "PET1", 1), _user("U3", "PVC1", 1)]), merged_map)))

# 정렬: 그룹순서 → 표시순서(NULL 뒤) → 사번
users_sorted = db.sort_users_for_display(
    pd.DataFrame([
        _user("2003", "PVC1", 1), _user("1002", "PET1", None),
        _user("1003", "PET2", 1), _user("1001", "PET1", None),
        _user("1004", "PET1", 2),
    ]),
    org_depts=pd.DataFrame([
        _dept("PET1", "PET생산부", "PET", 1, 1),
        _dept("PET2", "PET원료실", "PET", 1, 2),
        _dept("PVC1", "PVC생산부", "PVC", 2, 1),
    ]),
)
check("정렬: 그룹순서 → 표시순서 → NULL(사번순) 뒤",
      list(users_sorted["emp_no"]) == ["1003", "1004", "1001", "1002", "2003"])

# 사용자 관리 화면 검증 — 표시순서 입력 파싱
dept_names = {str(r["dept_code"]): str(r["dept_name"]) for _, r in db.get_departments().iterrows()}
team_resolve, _disp = master_users._team_maps(db.get_teams())
resolver = master_users._dept_resolver(dept_names)
label0 = master_users._dept_labels(dept_names)[next(iter(dept_names))]
recs_u, errs_u = master_users._validate(_meta_rows([
    {"사번": "T1", "성명": "가", "부서": label0, "조": "", "직급": "", "권한": "조원",
     "표시순서": "3", "재직": True},
    {"사번": "T2", "성명": "나", "부서": label0, "조": "", "직급": "", "권한": "조원",
     "표시순서": "", "재직": True},
    {"사번": "T3", "성명": "다", "부서": label0, "조": "", "직급": "", "권한": "조원",
     "표시순서": "abc", "재직": True},
    {"사번": "T4", "성명": "라", "부서": label0, "조": "", "직급": "", "권한": "조원",
     "표시순서": "0", "재직": True},
]), resolver, team_resolve)
check("표시순서 정수 저장", recs_u[0]["display_order"] == 3)
check("표시순서 빈 값 = NULL", recs_u[1]["display_order"] is None)
check("표시순서 문자 차단", any("숫자" in e for e in errs_u))
check("표시순서 1 미만 차단", any("1 이상" in e for e in errs_u))
check("USER_COLUMNS 에 display_order 포함", "display_order" in db.USER_COLUMNS)
check("get_users 가 display_order 컬럼 제공", "display_order" in db.get_users().columns)


# ===== 6) 운영단위 검증 =====
print("운영단위 검증 (_validate_units / _unit_structure_errors)")
store_org = db.get_org_departments()
dcode = str(store_org.iloc[0]["dept_code"])
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

_merged, dup, _c, _u, _d = db.upsert_records(
    db.get_org_teams(),
    [
        {"dept_code": dcode, "team_code": "ZZ", "team_name": "가", "unit_type": "SHIFT", "sort_order": 91, "is_active": True},
        {"dept_code": dcode, "team_code": "ZZ", "team_name": "나", "unit_type": "SHIFT", "sort_order": 92, "is_active": True},
    ],
    set(), ["dept_code", "team_code"], "is_active", db.ORG_TEAM_COLUMNS,
)
check("부서 내 운영단위 코드 중복 검출", (dcode, "ZZ") in dup)


# ===== 7) 선택 부서 없이 운영단위 저장 차단 =====
print("선택 부서 없이 저장 차단")


def _screen_save_units_without_dept():
    from views import master_org
    master_org._save_units(None, "")


at = AppTest.from_function(_screen_save_units_without_dept, default_timeout=45).run()
check("저장 차단 오류 표시", any("부서를 먼저 선택" in str(e.value) for e in at.error))


# ===== 8) 003 미적용 폴백 기본값 =====
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


# ===== 9) sample 스토어 저장 왕복 =====
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
check("unit_type 저장 왕복 보존", str(again_t.iloc[0]["unit_type"]) == "GENERAL")
db.save_org_teams(orig_teams)  # 원복

check("일반 화면 계약(get_teams TEAM_COLUMNS)에 영향 없음",
      list(db.get_teams()[db.TEAM_COLUMNS].columns) == db.TEAM_COLUMNS)
check("일반 화면 계약(get_departments DEPT_COLUMNS)에 영향 없음",
      list(db.get_departments()[db.DEPT_COLUMNS].columns) == db.DEPT_COLUMNS)


# ===== 10) 권한 라우팅 (사이드바 메뉴 계약 유지) =====
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
