"""조직 관리 3시트 화면 데이터·도메인 계약 테스트 (sample 모드, Supabase 미접속).

migration 004 group_id/FK 데이터계층 위의 가로 3시트 [그룹][부서][조] 화면 계약:
- 부서 관리/조 관리 메뉴가 같은 통합 화면(조직 관리)을 열고 3시트가 렌더되는지
- build_group_rows/build_dept_rows/build_team_rows: 각 테이블 → 평면 편집 행(계층 부모행 없음)
- _validate_groups/_validate_depts/_validate_units: 코드·명칭 필수, 순서 숫자, 빈 행 제외,
  신규·기존 부서는 선택 그룹 귀속(group_code), 조는 유형 교대/일반(SHIFT/GENERAL) + 비고
- _unit_structure_errors: 부서 내 명칭·표시순서 중복 차단(다른 부서 제외)
- upsert_records: 그룹/부서/조 자연키 중복 검출
- 드릴다운 데이터계층: group_code 필터=해당 그룹 부서만, dept_code 필터=해당 부서 조만
- ADMIN 보호(_protected)·비활성(_inactive)·드릴다운 활성(_linked) view-model 메타
- 저장된 코드 수정 불가(신규 등록 시만), 저장 왕복 보존
- 003→004 교차 화면 회귀 호환 순수 함수(_group_structure_errors) 시그니처 보존

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


def _grp(code, name, order, desc="", active=True):
    return {"group_code": code, "group_name": name, "sort_order": order,
            "description": desc, "is_active": active}


def _dep(code, name, group, order, desc="", active=True):
    return {"dept_code": code, "dept_name": name, "group_code": group,
            "description": desc, "sort_order": order, "is_active": active}


def _team(dept, code, name, unit_type, order, desc="", active=True):
    return {"dept_code": dept, "team_code": code, "team_name": name,
            "unit_type": unit_type, "description": desc, "sort_order": order, "is_active": active}


# grid rows helpers (편집 그리드 형태)
def _grow(code, name, order, state="existing", active=True, desc=""):
    return {"_row_id": f"e:{code}" if state == "existing" else code, "_row_state": state,
            "_sel": False, "코드": code, "코드명": name,
            "순서": str(order) if order != "" else "", "비고": desc, "사용": active}


def _urow(code, name, unit_type, order, state="existing", active=True, desc=""):
    return {"_row_id": f"e:D1|{code}" if state == "existing" else code, "_row_state": state,
            "_sel": False, "코드": code, "명칭": name, "유형": unit_type,
            "표시순서": str(order) if order != "" else "", "비고": desc, "사용": active}


# ===== 1) 두 메뉴 → 같은 3시트 통합 화면 =====
print("부서 관리/조 관리 메뉴 → 조직 관리 3시트 통합 화면")


def _screen_departments_menu():
    from modules import db
    from views import master_departments
    master_departments.render(db.find_user_by_emp_no("1001"))


def _screen_teams_menu():
    from modules import db
    from views import master_teams
    master_teams.render(db.find_user_by_emp_no("1001"))


# 2026-08-07: 그룹·조(운영단위) 시트 폐지 — 조직 관리는 부서 단일 시트만 표시한다
# (계층은 부서의 대분류/중분류 텍스트 2단). 그룹/조 시트 표시 검증은 계약에서 제거.
for label, fn in (("부서 관리", _screen_departments_menu), ("조 관리", _screen_teams_menu)):
    at = AppTest.from_function(fn, default_timeout=45).run()
    check(f"{label} 메뉴 렌더 예외 없음", not at.exception)
    body = " ".join(str(m.value) for m in at.markdown)
    check(f"{label} 메뉴가 조직 관리 화면을 표시", "조직 관리" in body)
    check(f"{label} 부서 시트 표시", "<span class='t'>부서</span>" in body)
    check(f"{label} 그룹 시트 미표시(단일 시트 계약)", "<span class='t'>그룹</span>" not in body)
    check(f"{label} 조 시트 미표시(단일 시트 계약)", "<span class='t'>조</span>" not in body)


# ===== 2) 평면 편집 행 모델 (계층 부모행 없음) =====
print("build_group_rows/build_dept_rows/build_team_rows — 평면 행 모델")
g_rows = master_org.build_group_rows(pd.DataFrame([
    _grp("PVC", "PVC계열", 2), _grp("PET", "PET계열", 1),
]))
check("그룹 행은 순서 오름차순 정렬", list(g_rows["코드"]) == ["PET", "PVC"])
check("그룹 행은 모두 existing(부모행 없음)", set(g_rows["_row_state"]) == {"existing"})
check("그룹 행 컬럼 계약", list(g_rows.columns) == master_org._GROUP_ROW_COLS)
check("그룹 코드명·순서 매핑", g_rows.iloc[0]["코드명"] == "PET계열" and g_rows.iloc[0]["순서"] == "1")

d_rows = master_org.build_dept_rows(pd.DataFrame([
    _dep("MTRL", "원료실", "PET", 2), _dep("PET", "PET생산부", "PET", 1),
]))
check("부서 행은 순서 오름차순 정렬", list(d_rows["코드"]) == ["PET", "MTRL"])
check("부서 행 평면(existing만)", set(d_rows["_row_state"]) == {"existing"})

t_rows = master_org.build_team_rows(pd.DataFrame([
    _team("PET", "B", "B조", "SHIFT", 2), _team("PET", "N9", "나인투식스", "GENERAL", 1),
]))
check("조 행은 순서 오름차순 정렬", list(t_rows["코드"]) == ["N9", "B"])
check("조 유형 내부값→표시값 변환(SHIFT→교대/GENERAL→일반)",
      list(t_rows["유형"]) == ["일반", "교대"])
check("조 행 컬럼 계약", list(t_rows.columns) == master_org._UNIT_ROW_COLS)


# ===== 3) _validate_groups =====
print("_validate_groups — 코드·명칭 필수, 순서 숫자, 빈 행 제외")
recs, errs = master_org._validate_groups(_meta_rows([
    _grow("NEWG", "새그룹", 3, state="new"),
    _grow("", "이름만", 4, state="new"),          # 코드 없음
    _grow("BADO", "순서이상", "abc", state="new"),  # 순서 문자
    _grow("", "", "", state="new"),                # 완전 빈 행 → 제외
]), )
check("그룹 정상 신규 레코드 생성", recs[0]["group_code"] == "NEWG" and recs[0]["sort_order"] == 3)
check("그룹코드 필수 검출", any("그룹코드" in e for e in errs))
check("그룹 순서 숫자 검증", any("순서는 숫자" in e for e in errs))
check("그룹 완전 빈 행 제외", len(recs) == 3)


# ===== 4) _validate_depts — 선택 그룹 귀속 =====
print("_validate_depts — 신규·기존 모두 선택 그룹(group_code) 귀속")
d_recs, d_errs = master_org._validate_depts(_meta_rows([
    _grow("PET", "PET생산부", 1),                 # 기존
    _grow("NEWD", "새부서", 2, state="new"),       # 신규
    _grow("", "", "", state="new"),                # 빈 행
]), "PET")
check("부서 레코드 모두 선택 그룹에 귀속", all(r["group_code"] == "PET" for r in d_recs))
check("신규 부서도 선택 그룹 귀속", any(r["dept_code"] == "NEWD" and r["group_code"] == "PET" for r in d_recs))
check("부서 빈 행 제외", len(d_recs) == 2)
_r, d_errs2 = master_org._validate_depts(_meta_rows([_grow("", "이름만", 1, state="new")]), "PET")
check("부서코드 필수 검출", any("부서코드" in e for e in d_errs2))


# ===== 5) _validate_units — 유형 변환·검증·비고 =====
print("_validate_units — 교대/일반 변환, 필수, 빈 행 제외, 비고")
u_recs, u_errs = master_org._validate_units(_meta_rows([
    _urow("A", "A조", "교대", 1),
    _urow("N9", "나인투식스", "일반", 2, desc="09-18"),
    _urow("RG", "상근", "GENERAL", 3),
    _urow("BAD", "이상", "심야", 4),
    _urow("", "", "", ""),
]), "D1")
check("교대→SHIFT 변환", u_recs[0]["unit_type"] == "SHIFT")
check("일반→GENERAL 변환", u_recs[1]["unit_type"] == "GENERAL")
check("내부값 직접 입력(GENERAL) 허용", u_recs[2]["unit_type"] == "GENERAL")
check("허용 외 유형 차단", any("유형" in e for e in u_errs))
check("빈 행 제외", len(u_recs) == 4)
check("모든 행에 선택 부서 부여", all(r["dept_code"] == "D1" for r in u_recs))
check("비고 반영", u_recs[1]["description"] == "09-18")


# ===== 6) 구조 검증 (_unit_structure_errors) =====
print("_unit_structure_errors — 부서 내 명칭·표시순서 중복 차단")
ue = master_org._unit_structure_errors(pd.DataFrame([
    _team("D1", "A", "같은명", "SHIFT", 1), _team("D1", "B", "같은명", "GENERAL", 1),
    _team("OTHER", "C", "같은명", "SHIFT", 1),
]), "D1")
check("부서 내 명칭 중복 차단", any("명칭" in e for e in ue))
check("부서 내 표시순서 중복 차단", any("표시순서" in e for e in ue))
check("다른 부서 행은 검증 대상 아님", all("C" not in e.split(":")[-1] for e in ue))


# ===== 7) upsert_records 중복 검출 (그룹/부서/조) =====
print("upsert_records — 그룹/부서/조 자연키 중복 검출")
_m, g_dup, *_ = db.upsert_records(db.get_org_groups(), [
    _grp("ZZ", "가", 91), _grp("ZZ", "나", 92),
], set(), ["group_code"], "is_active", db.ORG_GROUP_COLUMNS)
check("그룹코드 중복 검출", ("ZZ",) in g_dup)
_m, d_dup, *_ = db.upsert_records(db.get_org_departments(), [
    _dep("ZZ", "가", "PET", 91), _dep("ZZ", "나", "PET", 92),
], set(), ["dept_code"], "is_active", db.ORG_DEPT_COLUMNS)
check("부서코드 중복 검출", ("ZZ",) in d_dup)
_m, t_dup, *_ = db.upsert_records(db.get_org_teams(), [
    _team("D1", "ZZ", "가", "SHIFT", 91), _team("D1", "ZZ", "나", "SHIFT", 92),
], set(), ["dept_code", "team_code"], "is_active", db.ORG_TEAM_COLUMNS)
check("부서 내 조 코드 중복 검출", ("D1", "ZZ") in t_dup)


# ===== 8) 드릴다운 데이터계층 (group_code/dept_code 필터) =====
print("드릴다운 — group_code 필터=그룹 부서만, dept_code 필터=부서 조만")
depts_all = db.get_org_departments()
a_group = str(depts_all.iloc[0]["group_code"])
filtered = db.get_org_departments(group_code=a_group)
check("group_code 필터가 해당 그룹 부서만 반환",
      not filtered.empty and set(filtered["group_code"].astype(str)) == {a_group})
teams_all = db.get_org_teams()
a_dept = str(teams_all.iloc[0]["dept_code"])
dteams = db.get_org_teams(dept_code=a_dept)
check("dept_code 필터가 해당 부서 조만 반환",
      not dteams.empty and set(dteams["dept_code"].astype(str)) == {a_dept})


# ===== 9) view-model 메타 (ADMIN 보호 / 비활성 / 드릴다운 활성) =====
print("view-model 메타 — _protected(ADMIN)/_inactive/_linked")
disp = master_org._dept_display(master_org.build_dept_rows(pd.DataFrame([
    _dep("ADMIN", "관리부", "ADMIN", 1, active=True),
    _dep("PET", "PET생산부", "PET", 2, active=False),
])), "PET")
admin = disp[disp["코드"] == "ADMIN"].iloc[0]
pet = disp[disp["코드"] == "PET"].iloc[0]
check("ADMIN 부서 _protected=1(보호)", admin["_protected"] == "1")
check("비활성 부서 _inactive=1", pet["_inactive"] == "1")
check("선택 부서 _linked=1(드릴다운 활성)", pet["_linked"] == "1")
gdisp = master_org._group_display(master_org.build_group_rows(pd.DataFrame([
    _grp("ADMIN", "관리그룹", 1), _grp("PET", "PET계열", 2),
])), "PET")
check("ADMIN 그룹 _protected=1(보호)", gdisp[gdisp["코드"] == "ADMIN"].iloc[0]["_protected"] == "1")
check("선택 그룹 _linked=1", gdisp[gdisp["코드"] == "PET"].iloc[0]["_linked"] == "1")


# ===== 10) 저장 왕복 보존 (sample 스토어) =====
print("sample 저장 왕복 — 그룹 비고 / 부서 group_code / 조 unit_type")
g0 = db.get_org_groups().copy()
gc = str(g0.iloc[0]["group_code"])
g0.loc[g0["group_code"] == gc, "description"] = "왕복비고"
db.save_org_groups(g0)
check("그룹 비고 저장 왕복", str(db.get_org_groups().set_index("group_code").loc[gc, "description"]) == "왕복비고")

t0 = db.get_org_teams().copy()
t0.loc[t0.index[0], "unit_type"] = "GENERAL"
db.save_org_teams(t0)
check("조 unit_type 저장 왕복", str(db.get_org_teams().iloc[0]["unit_type"]) == "GENERAL")
db.save_org_teams(db.get_org_teams())  # no-op 정리

check("일반 화면 계약(get_teams TEAM_COLUMNS) 무영향",
      list(db.get_teams()[db.TEAM_COLUMNS].columns) == db.TEAM_COLUMNS)
check("일반 화면 계약(get_departments DEPT_COLUMNS) 무영향",
      list(db.get_departments()[db.DEPT_COLUMNS].columns) == db.DEPT_COLUMNS)


# ===== 11) 교차 화면 회귀 호환 순수 함수 =====
print("_group_structure_errors — 교차 화면 회귀 호환 시그니처 보존")
ge = master_org._group_structure_errors(pd.DataFrame([
    {"dept_code": "D1", "dept_name": "부서1", "department_group": "PET", "group_sort_order": 1, "sort_order": 1, "is_active": True},
    {"dept_code": "D2", "dept_name": "부서2", "department_group": "PVC", "group_sort_order": 1, "sort_order": 1, "is_active": True},
]))
check("그룹 간 그룹순서 중복 차단(호환)", any("여러 그룹" in e for e in ge))


# ===== 12) 권한 라우팅 =====
print("권한 라우팅 — 메뉴 id 유지")
for page in ("master_departments", "master_teams"):
    check(f"{page} 메뉴 id 유지(ADMIN 허용)", nav.allowed(page, "ADMIN"))
    check(f"{page} USER 접근 불가", not nav.allowed(page, "USER"))


def _screen_direct_org():
    import app
    from modules import db as app_db
    app.dispatch("master_org", app_db.find_user_by_emp_no("1001"))


at_org = AppTest.from_function(_screen_direct_org, default_timeout=30).run()
check("master_org 직접 라우팅 예외 없음", not at_org.exception)
check("master_org 직접 라우팅이 조직 관리 화면 표시",
      "조직 관리" in " ".join(str(m.value) for m in at_org.markdown))


# ===== 13) 상위 전환 중 저장 = 옛 행이 새 상위에 오귀속되지 않음 (Codex critical FIX) =====
# 자식 시트 편집 후 다른 상위 선택 → 저장 시, 아직 렌더된 옛 행이 새로 선택된
# group/department 로 재귀속/중복되면 데이터 무결성 결함. 저장은 행이 '적재된 시점의
# 상위'(loaded_group/loaded_dept)로 바인딩되어야 한다(현재 selectbox 값 아님).
print("상위 전환 중 저장 오귀속 방지 — 부서(그룹)·조(부서) 안정 상위키 바인딩")


def _dept_misbind_probe():
    # 2026-08-07 단일 시트 전환 후 이 프로브의 의미: 저장 호출에 group_code 를 어떤
    # 값으로 넘기든(구 API 오사용 포함) **행의 기존 그룹 귀속이 변하지 않는다**.
    import streamlit as st
    from modules import db as adb
    from views import master_org as mo
    mo._load_depts({"active": "전체", "search": ""})                 # 단일 시트 — 전건 적재
    grid = mo._OD.get_rows().copy(); grid["_removed"] = ""
    tgt = str(grid.iloc[0]["코드"])
    store = adb.get_org_departments()
    gA = str(store[store["dept_code"] == tgt].iloc[0]["group_code"])  # 행0의 실제 귀속
    groups = adb.get_org_groups(is_active=True)
    gB = next(str(g) for g in groups["group_code"].astype(str) if g != gA)
    grid.loc[grid.index[0], "코드명"] = "변경됨XYZ"                  # 실제 편집
    before_b = set(adb.get_org_departments(group_code=gB)["dept_code"].astype(str))
    try:                                                            # 구 API 로 B 귀속을 시도해도
        mo._save_depts(grid, {"active": "전체", "search": ""}, gB)
    except BaseException:
        pass
    after = adb.get_org_departments()
    row = after[after["dept_code"] == tgt].iloc[0]
    st.session_state["res_group"] = str(row["group_code"])
    st.session_state["res_name"] = str(row["dept_name"])
    st.session_state["b_new"] = sorted(
        set(after[after["group_code"] == gB]["dept_code"].astype(str)) - before_b)
    st.session_state["gA"] = gA
    st.session_state["gB"] = gB


atd = AppTest.from_function(_dept_misbind_probe, default_timeout=45).run()
check("부서 오귀속 probe 예외 없음", not atd.exception)
check("편집한 부서가 원 그룹(A)에 그대로 귀속", atd.session_state["res_group"] == atd.session_state["gA"])
check("편집한 부서가 새 그룹(B)으로 오귀속되지 않음", atd.session_state["res_group"] != atd.session_state["gB"])
check("새 그룹(B)에 오귀속·중복 부서 없음", atd.session_state["b_new"] == [])
check("실제 편집(부서명)은 원 그룹에 정상 저장", atd.session_state["res_name"] == "변경됨XYZ")


def _team_misbind_probe():
    import streamlit as st
    from modules import db as adb
    from views import master_org as mo
    teams = adb.get_org_teams()
    d1 = str(teams.groupby("dept_code").size().index[0])
    depts = adb.get_org_departments()
    d2 = next(str(d) for d in depts["dept_code"].astype(str) if d != d1)
    mo._load_units(d1)                                              # loaded_dept = d1
    grid = mo._OU.get_rows().copy(); grid["_removed"] = ""
    tcode = str(grid.iloc[0]["코드"])
    grid.loc[grid.index[0], "명칭"] = "조편집QQ"
    before_d2 = set(adb.get_org_teams(dept_code=d2)["team_code"].astype(str))
    try:                                                            # 상위가 d2 로 바뀐 척 저장 시도
        mo._save_units(grid, d2)
    except BaseException:
        pass
    after = adb.get_org_teams()
    st.session_state["t_d1_has"] = tcode in set(after[after["dept_code"] == d1]["team_code"].astype(str))
    st.session_state["t_d1_name"] = str(
        after[(after["dept_code"] == d1) & (after["team_code"] == tcode)].iloc[0]["team_name"])
    st.session_state["t_d2_new"] = sorted(
        set(after[after["dept_code"] == d2]["team_code"].astype(str)) - before_d2)


att = AppTest.from_function(_team_misbind_probe, default_timeout=45).run()
check("조 오귀속 probe 예외 없음", not att.exception)
check("조가 원 부서(D1)에 그대로 유지", att.session_state["t_d1_has"])
check("조가 새 부서(D2) 밑으로 오귀속·중복 생성되지 않음", att.session_state["t_d2_new"] == [])
check("실제 편집(조 명칭)은 원 부서에 정상 저장", att.session_state["t_d1_name"] == "조편집QQ")


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
