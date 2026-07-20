"""기준정보 4화면 통일 계약 테스트 (sample/소스 정적, 실DB 미접속).

- 네 화면이 공통 레이아웃(제목/설명/필터/버튼/그리드/건수)과 공통 helper 를 사용
- 저장 버튼 네이비(검정 금지), 통계 카드·하단 신규/독립 저장·큰 필터 카드 제거
- 공통 작업 버튼 순서(행추가/삭제/저장 · 새로고침), 선택 없음 시 삭제 disabled
- 사용자 관리 변환(권한/부서/조 표시↔코드)·소프트 삭제 유지
- 사이드바 승인 디자인·월간/편성/내근무표 회귀는 별도 스위트에서 확인

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_master_unified.py
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

import pandas as pd  # noqa: E402

from modules import db, nav  # noqa: E402
from views import workspace, master_users, master_departments, master_teams, master_org, master_work_types  # noqa: E402

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


_MODULES = {
    "사용자 관리": master_users,
    "조직 관리": master_org,
    "근무형태 관리": master_work_types,
}


# ===== 1) 화면 공통 helper·구조 사용 =====
print("기준정보 화면 공통 레이아웃·helper")
for label, mod in _MODULES.items():
    src = inspect.getsource(mod)
    check(f"{label}: 공통 헤더(master_screen_head) 사용", "master_screen_head" in src)
    check(f"{label}: 공통 작업 버튼(master_action_bar) 사용", "master_action_bar" in src)
    check(f"{label}: 동적 그리드 높이(master_grid_height) 사용", "master_grid_height" in src)
    check(f"{label}: 공통 필터 컨테이너(ms_filter) 사용", 'key="ms_filter"' in src)
    check(f"{label}: 공통 그리드(selectable_master_grid) 사용", "selectable_master_grid" in src)
    check(f"{label}: 공통 건수(master_count) 사용", "master_count" in src)


# ===== 1-1) 조직 관리 통합 계약 =====
print("조직 관리 통합 (부서/조 메뉴 → 같은 화면, 좌/우 분리 저장)")
check("부서 관리 메뉴가 조직 관리 화면으로 위임",
      "master_org.render" in inspect.getsource(master_departments.render))
check("조 관리 메뉴가 조직 관리 화면으로 위임",
      "master_org.render" in inspect.getsource(master_teams.render))
org_src = inspect.getsource(master_org)
check("화면 제목은 '조직 관리'", '"조직 관리"' in org_src)
check("좌(그룹·부서)/우(운영단위) 저장 계약 분리(od_/ou_)",
      "od_save_req" in org_src and "ou_save_req" in org_src)
check("그룹순서 전역 유일 검증 존재", "_group_structure_errors" in org_src)
check("운영단위 유형 교대/일반 지원", '"SHIFT"' in org_src and '"GENERAL"' in org_src)


# ===== 2) 구형 요소 제거 =====
print("구형 카드·버튼·통계 제거")
for label, mod in _MODULES.items():
    full = inspect.getsource(mod)
    check(f"{label}: 통계 카드(summary_cards) 없음", "summary_cards" not in full)
    check(f"{label}: 필터 카드(ui.card) 없음", "ui.card(" not in full)
    check(f"{label}: 구형 editable_aggrid 없음", "editable_aggrid" not in full)
    check(f"{label}: 검정 저장 버튼(#1B1B1D/#000000) 없음", "#1B1B1D" not in full and "#000000" not in full)
    check(f"{label}: 하단 독립 저장(ui.action_bar) 없음", "ui.action_bar" not in full)
# 사용자 관리: 하단 '신규' 텍스트 버튼 제거 (행 추가로 통일)
check("사용자 관리: 하단 '신규' 버튼 제거", 'st.button(\n        "신규"' not in inspect.getsource(master_users)
      and '"신규"' not in inspect.getsource(master_users.render))


# ===== 3) 공통 작업 버튼 순서·스타일 =====
print("공통 작업 버튼 규칙")
bar_src = inspect.getsource(workspace.master_action_bar)
order_ok = (
    bar_src.index('"행 추가"') < bar_src.index('"삭제"')
    < bar_src.index('"저장"') < bar_src.index('"새로고침"')
)
check("버튼 순서: 행추가 → 삭제 → 저장 → 새로고침", order_ok)
check("저장은 네이비 primary(type='primary')", 'type="primary"' in bar_src and '_save"' in bar_src)
check("삭제는 선택 없음 시 disabled", "disabled=int(sel_count) == 0" in bar_src)
check("새로고침은 작업 버튼 행 우측(같은 함수 내)", '"새로고침"' in bar_src and '_refresh"' in bar_src)
check("prefix 기본값 ms(기존 화면 무변경)", 'prefix: str = "ms"' in bar_src)

css = workspace._MASTER_CSS
check("공통 CSS: 저장 네이비 #1E3A6E", "#1E3A6E" in css and ".st-key-ms_save" in css)
check("공통 CSS: 조직 관리 좌/우 저장 버튼도 네이비", ".st-key-od_save" in css and ".st-key-ou_save" in css)
check("공통 CSS: 검정 저장(#1B1B1D/#000000) 없음", "#1B1B1D" not in css and "#000000" not in css)
check("공통 CSS: 삭제 disabled 스타일 존재", ".st-key-ms_del button:disabled" in css)


# ===== 4) 동적 그리드 높이 계산 (240~460, 행 수 반응) =====
print("동적 그리드 높이")
check("빈 목록도 최소 240", workspace.master_grid_height(0) == 240)
check("행 적으면 과도하게 높지 않음(<460)", workspace.master_grid_height(3) < 460)
check("행 많으면 460 상한", workspace.master_grid_height(100) == 460)
check("행 수에 따라 증가", workspace.master_grid_height(3) < workspace.master_grid_height(10))


# ===== 5) 사용자 관리 변환·검증 (권한/부서/조 표시↔코드) =====
print("사용자 관리 변환·검증")
depts = db.get_departments()
teams = db.get_teams()
dept_names = {str(r["dept_code"]): str(r["dept_name"]) for _, r in depts.iterrows()}
team_resolve, _team_display = master_users._team_maps(teams)
dept_resolver = master_users._dept_resolver(dept_names)
labels = master_users._dept_labels(dept_names)
d0 = next(iter(dept_names))           # 부서코드
d0_label = labels[d0]                 # 표시 라벨
# d0 부서의 한 조명
t0_rows = teams[teams["dept_code"].astype(str) == str(d0)]
t0_name = str(t0_rows.iloc[0]["team_name"]) if not t0_rows.empty else ""
t0_code = str(t0_rows.iloc[0]["team_code"]) if not t0_rows.empty else ""


def _live(rows):
    frame = pd.DataFrame(rows)
    frame["_removed"] = ""
    return frame


recs, errs = master_users._validate(_live([
    {"_row_id": "n:1", "_row_state": "new", "_sel": False,
     "사번": "TESTU1", "성명": "홍길동", "부서": d0_label, "조": t0_name,
     "직급": "사원", "권한": "관리자", "재직": True},
]), dept_resolver, team_resolve)
check("권한 표시(관리자)→ADMIN", recs and recs[0]["role"] == "ADMIN")
check("부서 표시명→dept_code", recs and recs[0]["dept_code"] == str(d0))
check("조명→team_code", recs and recs[0]["team_code"] == t0_code)
check("정상 행 오류 없음", not errs)

# 조 없는 부서: 빈 조 허용
recs2, errs2 = master_users._validate(_live([
    {"_row_id": "n:2", "_row_state": "new", "_sel": False,
     "사번": "TESTU2", "성명": "김철수", "부서": d0_label, "조": "",
     "직급": "", "권한": "조원", "재직": True},
]), dept_resolver, team_resolve)
check("조 미지정 허용(빈 조)", recs2 and recs2[0]["team_code"] == "" and not errs2)

# 타 부서 조 차단
other = teams[teams["dept_code"].astype(str) != str(d0)]
if not other.empty:
    other_name = str(other.iloc[0]["team_name"])
    # d0 부서에 존재하지 않는 조명이면 차단
    if other_name not in set(t0_rows["team_name"].astype(str)):
        _r, e3 = master_users._validate(_live([
            {"_row_id": "n:3", "_row_state": "new", "_sel": False,
             "사번": "TESTU3", "성명": "이영희", "부서": d0_label, "조": other_name,
             "직급": "", "권한": "조원", "재직": True},
        ]), dept_resolver, team_resolve)
        check("타 부서 조 차단", any("없는 조" in x for x in e3))
    else:
        check("타 부서 조 차단(공통 조명이라 스킵)", True)
else:
    check("타 부서 조 차단(부서 1개라 스킵)", True)

# 빈 행 스킵
recs4, _e4 = master_users._validate(_live([
    {"_row_id": "n:9", "_row_state": "new", "_sel": False,
     "사번": "", "성명": "", "부서": "", "조": "", "직급": "", "권한": "", "재직": True},
]), dept_resolver, team_resolve)
check("완전히 빈 행은 저장 대상 제외", len(recs4) == 0)

# 소프트 삭제 계약 (물리 삭제 아님)
del_src = inspect.getsource(master_users._execute_delete)
check("사용자 삭제는 소프트(is_active=False + save_users)", 'is_active"] = False' in del_src and "save_users" in del_src)
check("사용자 물리 삭제 호출 없음", "delete_user" not in inspect.getsource(master_users))


# ===== 6) 권한 라우팅·회귀 =====
print("권한 라우팅")
for page in ("master_users", "master_departments", "master_teams", "master_work_types"):
    check(f"USER 는 {page} 접근 불가(계약 유지)", not nav.allowed(page, "USER"))
    check(f"ADMIN 은 {page} 접근 가능", nav.allowed(page, "ADMIN"))


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
