"""월간/개인 조회 + 조·근무형태 관리 계약 단위 테스트 (sample 모드, Supabase 미접속).

실행: .venv/Scripts/python.exe scripts/test_master_and_views.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DUTY_DATA_MODE"] = "sample"

import pandas as pd  # noqa: E402

from modules import db  # noqa: E402
from views import workspace, master_teams, master_work_types  # noqa: E402

PASS = 0
FAIL = []


def check(name, cond):
    global PASS
    if cond:
        PASS += 1
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name}")


def _meta_rows(rows):
    """행 상태 계약 메타 컬럼을 붙인 편집 결과 프레임(그리드 반환 모사)."""
    frame = pd.DataFrame(rows)
    if "_removed" not in frame:
        frame["_removed"] = ""
    return frame


# ---------- workspace.work_type_display ----------
print("workspace.work_type_display (코드->약칭, 색상 매핑)")
display_of, color_of = workspace.work_type_display()
wt = db.get_work_types()
active = wt[wt["is_active"]]
sample_code = str(active.iloc[0]["code"]).strip()
sample_label = str(active.iloc[0]["short_label"]).strip() or sample_code
check("코드가 약칭으로 매핑됨", display_of.get(sample_code) == sample_label)
_codes = [str(rr["code"]).strip() for _, rr in active.iterrows()]
check("약칭 표시값도 색상 키에 존재하면 코드와 동일 색(색은 코드에 귀속)", all(
    color_of.get(display_of.get(c)) == color_of.get(c)
    for c in _codes if c in color_of
) if color_of else True)


# ---------- workspace._build_month_grid (월간 조회 필터·약칭) ----------
print("workspace._build_month_grid (필터·약칭·빈월)")
users = db.get_users()
au = users[users["is_active"]]
dept0 = str(au.iloc[0]["dept_code"])
team0 = str(au.iloc[0]["team_code"])

q_all = {"year": 2026, "month": 7, "dept": workspace.ALL, "team": workspace.ALL, "keyword": ""}
grid_all, rows_all = workspace._build_month_grid(q_all, display_of)
n_active = len(au)
check("전체 필터 → 활성 사용자 전원", len(grid_all) == n_active)

q_dept = {"year": 2026, "month": 7, "dept": dept0, "team": workspace.ALL, "keyword": ""}
grid_dept, _ = workspace._build_month_grid(q_dept, display_of)
expect_dept = len(au[au["dept_code"].astype(str) == dept0])
check("부서 필터가 결과를 제한", len(grid_dept) == expect_dept and expect_dept < n_active)

q_team = {"year": 2026, "month": 7, "dept": dept0, "team": team0, "keyword": ""}
grid_team, _ = workspace._build_month_grid(q_team, display_of)
expect_team = len(au[(au["dept_code"].astype(str) == dept0) & (au["team_code"].astype(str) == team0)])
check("조 필터가 결과를 제한(특정 조 선택 시 전체 아님)", len(grid_team) == expect_team and expect_team <= expect_dept)

# 키워드 검색: 첫 사용자 사번
emp0 = str(au.iloc[0]["emp_no"])
q_kw = {"year": 2026, "month": 7, "dept": workspace.ALL, "team": workspace.ALL, "keyword": emp0}
grid_kw, _ = workspace._build_month_grid(q_kw, display_of)
check("사번 검색이 결과를 제한", len(grid_kw) >= 1 and all(str(v) == emp0 for v in grid_kw["사번"]))

# 셀이 약칭으로 표시(코드가 아님) — 값이 있는 셀 확인
day_cols = [c for c in grid_all.columns if c[0].isdigit()]
codes_in_data = set(str(c).strip() for c in rows_all["work_type_code"])
labels_shown = set()
for _, r in grid_all.iterrows():
    for c in day_cols:
        v = str(r[c]).strip()
        if v:
            labels_shown.add(v)
check("셀 표시값이 내부 코드 원본이 아니라 약칭 매핑을 따름",
      labels_shown.issubset(set(display_of.values()) | {""}) and len(labels_shown) > 0)

# 빈 월(데이터 없는 2030-01) — 여전히 사용자 행은 나오되 셀은 빈값
q_empty = {"year": 2030, "month": 1, "dept": workspace.ALL, "team": workspace.ALL, "keyword": ""}
grid_empty, rows_empty = workspace._build_month_grid(q_empty, display_of)
check("빈 월: repository 예외 없이 빈 근무(행은 존재)", len(rows_empty) == 0 and len(grid_empty) == n_active)

# 2026-07과 다른 월이 섞이지 않음
q_aug = {"year": 2026, "month": 8, "dept": workspace.ALL, "team": workspace.ALL, "keyword": ""}
_g, rows_aug = workspace._build_month_grid(q_aug, display_of)
check("월이 섞이지 않음(2026-08은 0건)", len(rows_aug) == 0)


# ---------- master_teams._validate ----------
print("master_teams._validate (부서 표시명->코드, 중복·필수)")
disp_of, code_of = master_teams._dept_maps()
dcode = str(db.get_departments().iloc[0]["dept_code"])
dlabel = disp_of[dcode]
recs, errs = master_teams._validate(_meta_rows([
    {"부서": dlabel, "조코드": "Z1", "조명": "가조", "표시순서": "1", "사용": True},
    {"부서": dlabel, "조코드": "Z1", "조명": "중복조", "표시순서": "2", "사용": True},  # dup
    {"부서": "없는부서", "조코드": "Z3", "조명": "X", "표시순서": "3", "사용": True},  # bad dept
    {"부서": "", "조코드": "", "조명": "", "표시순서": "", "사용": True},  # empty skip
]))
check("표시명이 dept_code 로 변환됨", recs[0]["dept_code"] == dcode)
check("부서 내 조코드 중복 검출", any("중복" in e for e in errs))
check("존재하지 않는 부서 검출", any("존재하지 않는 부서" in e for e in errs))
check("빈 행은 저장 대상에서 제외", len(recs) == 3)  # empty row skipped


# ---------- master_work_types._validate ----------
print("master_work_types._validate (필수값·색상 보존)")
recs2, errs2 = master_work_types._validate(_meta_rows([
    {"코드": "TESTW", "명칭": "테스트근무", "분류": "주간", "약칭": "테", "시작": "08:00",
     "종료": "17:00", "색상": "#123456", "실근무": True, "특근수당": False, "설명": "x",
     "표시순서": "5", "사용": True},
    {"코드": "", "명칭": "이름만", "분류": "", "약칭": "", "시작": "", "종료": "", "색상": "",
     "실근무": False, "특근수당": False, "설명": "", "표시순서": "", "사용": True},  # missing code/label/category
]))
check("색상 HEX 보존(#RRGGBB)", recs2[0]["color"] == "#123456")
check("실근무 bool 변환", recs2[0]["is_work"] is True)
check("필수값 누락(코드/약칭/분류) 검출", sum(1 for e in errs2 if ("코드" in e or "약칭" in e or "분류" in e)) >= 3)


# ---------- db 참조·삭제 (sample) ----------
print("db team/work_type 참조·삭제 (sample 모드)")
t = db.get_teams()
au2 = db.get_users()
# 참조 있는 조 찾기
ref_team = None
for _, r in t.iterrows():
    dc, tc = str(r["dept_code"]), str(r["team_code"])
    if db.team_reference_counts(dc, tc)["users"] > 0:
        ref_team = (dc, tc)
        break
check("소속 사용자 있는 조의 참조 수 > 0", ref_team is not None)

# 참조 없는 조 하나 만들어 삭제 (sample store)
db.save_teams(pd.concat([db.get_teams(), pd.DataFrame([
    {"dept_code": str(t.iloc[0]["dept_code"]), "team_code": "TMPZ", "team_name": "임시조", "sort_order": 99, "is_active": True}
])], ignore_index=True)[db.TEAM_COLUMNS])
check("임시 조 추가됨", not db.get_teams()[db.get_teams()["team_code"].astype(str) == "TMPZ"].empty)
check("임시 조 참조 0", db.team_reference_counts(str(t.iloc[0]["dept_code"]), "TMPZ")["users"] == 0)
db.delete_team(str(t.iloc[0]["dept_code"]), "TMPZ")
check("delete_team 후 조가 사라짐", db.get_teams()[db.get_teams()["team_code"].astype(str) == "TMPZ"].empty)

w = db.get_work_types()
used_code = str(db.get_schedules().iloc[0]["work_type_code"]).strip()
check("근무표 사용 중 코드 참조 > 0", db.work_type_reference_counts(used_code)["schedules"] > 0)
db.save_work_types(pd.concat([db.get_work_types(), pd.DataFrame([
    {"code": "TMPWT", "name": "임시", "category": "주간", "short_label": "임", "start_time": "",
     "end_time": "", "color": "#abcdef", "is_work": True, "affects_allowance": False,
     "description": "", "sort_order": 99, "is_active": True}
])], ignore_index=True)[db.WORK_TYPE_COLUMNS])
check("임시 근무형태 참조 0", db.work_type_reference_counts("TMPWT")["schedules"] == 0)
db.delete_work_type("TMPWT")
check("delete_work_type 후 코드가 사라짐", db.get_work_types()[db.get_work_types()["code"].astype(str) == "TMPWT"].empty)


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
