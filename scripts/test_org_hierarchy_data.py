"""조직 계층 데이터계층 계약 테스트 — group_id/FK 기반 (migration 004).

WAVE 3a 데이터 소유자 산출물. 조직 계층을 organization_groups(그룹) →
departments.group_id(부서) → teams.department_id(조) 로 전부 ID/FK 로 조회·저장하는
db 파사드/supabase_repository 계약을 검증한다.

- Part A (sample 모드): 그룹/부서/조 3계층 조회·필터·저장·미사용/삭제 대칭,
  users/근무형태 컬럼 안정성. 세션 스토어만 사용(실제 DB 무접촉).
- Part B (supabase 모드, read-only 라이브 probe): 테스트 프로젝트가 설정된 경우에만
  group_id 계층이 실제 4그룹/5부서/6조와 일치하는지 확인한다. **쓰기 없음.**
  미설정이면 SKIP(실패 아님), 확인 자체 실패면 원인을 구분해 보고한다.

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_org_hierarchy_data.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from modules import config, db  # noqa: E402

PASS = 0
FAIL: list[str] = []
SKIP: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS
    if cond:
        PASS += 1
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name}" + (f" :: {detail}" if detail else ""))


# ===========================================================================
# Part A — sample 모드 데이터계층 계약
# ===========================================================================
def part_a_sample() -> None:
    os.environ["DUTY_DATA_MODE"] = "sample"
    print("Part A — sample 모드 (그룹→부서→조 계층, 세션 스토어)")
    check("sample 모드 확인", db.is_sample_mode())

    # 1) 컬럼 계약 (code/name/order/description/is_active + teams.unit_type)
    check("ORG_GROUP_COLUMNS 계약",
          db.ORG_GROUP_COLUMNS == ["group_code", "group_name", "sort_order", "description", "is_active"])
    check("ORG_DEPT_COLUMNS 는 group_code/description 기반(003 잔재 제거)",
          db.ORG_DEPT_COLUMNS == ["dept_code", "dept_name", "group_code", "description", "sort_order", "is_active"])
    check("ORG_TEAM_COLUMNS 는 unit_type/description 포함",
          db.ORG_TEAM_COLUMNS == ["dept_code", "team_code", "team_name", "unit_type", "description", "sort_order", "is_active"])

    groups = db.get_org_groups()
    check("그룹 조회 컬럼 계약", list(groups.columns) == db.ORG_GROUP_COLUMNS)
    check("그룹 비어있지 않음(샘플 seed)", not groups.empty)
    orders = list(pd.to_numeric(groups["sort_order"], errors="coerce"))
    check("그룹은 sort_order 오름차순", orders == sorted(orders))

    depts = db.get_org_departments()
    check("부서 조회 컬럼 계약", list(depts.columns) == db.ORG_DEPT_COLUMNS)
    group_codes = set(groups["group_code"].astype(str))
    dept_group_codes = set(depts["group_code"].astype(str)) - {""}
    check("모든 부서 group_code 가 그룹에 존재(참조 무결성)",
          dept_group_codes.issubset(group_codes),
          f"orphans={dept_group_codes - group_codes}")

    # 2) 그룹별 부서 조회(group_code 필터)
    a_group = str(depts.iloc[0]["group_code"])
    filtered = db.get_org_departments(group_code=a_group)
    check("group_code 필터가 해당 그룹 부서만 반환",
          not filtered.empty and set(filtered["group_code"].astype(str)) == {a_group})

    # 3) 부서별 조 조회(department_id FK 필터)
    teams = db.get_org_teams()
    check("조 조회 컬럼 계약", list(teams.columns) == db.ORG_TEAM_COLUMNS)
    check("조 unit_type 은 허용값만", set(teams["unit_type"].astype(str)).issubset(set(db.UNIT_TYPES)))
    team_dept_codes = set(teams["dept_code"].astype(str))
    check("모든 조의 dept_code 가 부서에 존재(참조 무결성)",
          team_dept_codes.issubset(set(depts["dept_code"].astype(str))),
          f"orphans={team_dept_codes - set(depts['dept_code'].astype(str))}")
    a_dept = str(teams.iloc[0]["dept_code"])
    dteams = db.get_org_teams(dept_code=a_dept)
    check("dept_code 필터가 해당 부서 조만 반환",
          not dteams.empty and set(dteams["dept_code"].astype(str)) == {a_dept})

    # 4) dept_group_map — dept_code -> (group_code, group_sort_order)
    mapping = db.dept_group_map()
    sample_dept = str(depts.iloc[0]["dept_code"])
    check("dept_group_map 반환 형태 (group_code, order)",
          isinstance(mapping.get(sample_dept), tuple) and len(mapping[sample_dept]) == 2)

    # 5) 부서→그룹 재귀속 저장 round-trip (group_id FK 로 이동)
    if len(group_codes) >= 2:
        target_dept = sample_dept
        cur_group = str(depts[depts["dept_code"] == target_dept].iloc[0]["group_code"])
        other_group = next(g for g in group_codes if g != cur_group)
        edited = depts.copy()
        edited.loc[edited["dept_code"] == target_dept, "group_code"] = other_group
        db.save_org_departments(edited)
        reloaded = db.get_org_departments()
        got = str(reloaded[reloaded["dept_code"] == target_dept].iloc[0]["group_code"])
        check("부서 group 재귀속 저장 round-trip", got == other_group, f"got={got}")
        # 원복
        db.save_org_departments(depts)
        check("부서 재귀속 원복",
              str(db.get_org_departments().set_index("dept_code").loc[target_dept, "group_code"]) == cur_group)

    # 6) 그룹 저장 round-trip (그룹명·비고 수정 — 저장코드는 불변)
    g_edit = db.get_org_groups().copy()
    g_code = str(g_edit.iloc[0]["group_code"])
    g_edit.loc[g_edit["group_code"] == g_code, "description"] = "계약테스트비고"
    db.save_org_groups(g_edit)
    check("그룹 비고 저장 round-trip",
          str(db.get_org_groups().set_index("group_code").loc[g_code, "description"]) == "계약테스트비고")

    # 7) 저장행 삭제 = soft-delete(is_active=False), 즉시 제거 = 스토어에서 사라짐
    tmp = db.get_org_groups().copy()
    tmp = pd.concat([tmp, pd.DataFrame([{
        "group_code": "ZZTEMP", "group_name": "임시그룹", "sort_order": 900,
        "description": "", "is_active": True,
    }])], ignore_index=True)
    db.save_org_groups(tmp)
    check("임시 그룹 추가됨", "ZZTEMP" in set(db.get_org_groups()["group_code"].astype(str)))
    db.deactivate_org_group("ZZTEMP")
    after_deact = db.get_org_groups()
    row = after_deact[after_deact["group_code"] == "ZZTEMP"]
    check("미사용 처리(soft-delete): 행은 남고 is_active=False",
          not row.empty and bool(row.iloc[0]["is_active"]) is False)
    db.delete_org_group("ZZTEMP")
    check("즉시 삭제: 스토어에서 제거", "ZZTEMP" not in set(db.get_org_groups()["group_code"].astype(str)))
    check("그룹 참조 수 계약(부서 기준)", "departments" in db.org_group_reference_counts(g_code))

    # 8) users/근무형태 화면 계약 안정성 (회귀 금지)
    check("USER_COLUMNS 안정",
          db.USER_COLUMNS == ["emp_no", "name", "dept_code", "team_code", "position", "role", "is_active", "display_order"])
    check("get_users 컬럼 계약 유지", list(db.get_users().columns) == db.USER_COLUMNS)
    check("get_work_types 컬럼 계약 유지", list(db.get_work_types().columns) == db.WORK_TYPE_COLUMNS)


# ===========================================================================
# Part A2 — sample 단일 backing store (Codex major 회귀 가드)
#   저장(save_org_*) · 물리삭제(delete_department/delete_team) · 조직 조회 ·
#   기본 조회(get_departments/get_teams) · 사용자 경로(dept_group_map)가
#   같은 in-memory store 를 보는지 검증한다. (이전 결함: 조직 저장은 store_org_*,
#   삭제·기본조회는 레거시 store 를 봐서 삭제가 반영 안 되고 사용자 화면이 못 봄.)
# ===========================================================================
def part_a2_store_unification() -> None:
    os.environ["DUTY_DATA_MODE"] = "sample"
    print("Part A2 — sample 단일 backing store (저장/삭제/사용자읽기 일치)")

    groups = db.get_org_groups()
    g_code = str(groups.iloc[0]["group_code"])

    # (a) 조직 화면에서 임시 부서 저장 → 조직/기본/사용자 읽기 전부 반영
    snap = pd.concat([db.get_org_departments(), pd.DataFrame([{
        "dept_code": "ZZDEPT", "dept_name": "임시부서", "group_code": g_code,
        "description": "", "sort_order": 99, "is_active": True,
    }])], ignore_index=True)
    db.save_org_departments(snap[db.ORG_DEPT_COLUMNS])
    check("조직 저장 임시부서 → 조직 조회 반영",
          "ZZDEPT" in set(db.get_org_departments()["dept_code"].astype(str)))
    check("조직 저장 임시부서 → 기본 부서조회(get_departments)도 반영(단일 store)",
          "ZZDEPT" in set(db.get_departments()["dept_code"].astype(str)))
    check("조직 저장 임시부서 → 사용자 경로(dept_group_map)가 그룹까지 봄",
          db.dept_group_map().get("ZZDEPT", (None,))[0] == g_code)

    # (b) 물리 삭제 → 실제 제거 (성공메시지만 뜨고 남던 버그 회귀 가드)
    db.delete_department("ZZDEPT")
    check("부서 물리삭제 → 조직 조회에서 실제 제거",
          "ZZDEPT" not in set(db.get_org_departments()["dept_code"].astype(str)))
    check("부서 물리삭제 → 기본 부서조회에서도 실제 제거",
          "ZZDEPT" not in set(db.get_departments()["dept_code"].astype(str)))

    # (c) 임시 조 저장 → 삭제 → 실제 제거 (기본/조직 조회 동일 store)
    a_dept = str(db.get_org_departments().iloc[0]["dept_code"])
    tsnap = pd.concat([db.get_org_teams(), pd.DataFrame([{
        "dept_code": a_dept, "team_code": "ZZ", "team_name": "임시조",
        "unit_type": "SHIFT", "description": "", "sort_order": 99, "is_active": True,
    }])], ignore_index=True)
    db.save_org_teams(tsnap[db.ORG_TEAM_COLUMNS])

    def _team_present(getter) -> bool:
        t = getter()
        return not t[(t["dept_code"].astype(str) == a_dept)
                     & (t["team_code"].astype(str) == "ZZ")].empty

    check("조직 저장 임시조 → 조직 조회 반영", _team_present(lambda: db.get_org_teams(a_dept)))
    check("조직 저장 임시조 → 기본 조회(get_teams)도 반영(단일 store)", _team_present(db.get_teams))
    db.delete_team(a_dept, "ZZ")
    check("조 물리삭제 → 조직 조회에서 실제 제거", not _team_present(lambda: db.get_org_teams(a_dept)))
    check("조 물리삭제 → 기본 조회에서도 실제 제거", not _team_present(db.get_teams))

    # (d) 부서 그룹 재귀속 저장이 사용자 경로(dept_group_map)에 즉시 반영
    if len(groups) >= 2:
        target = str(db.get_org_departments().iloc[0]["dept_code"])
        cur = db.dept_group_map()[target][0]
        other = next(str(g) for g in groups["group_code"] if str(g) != cur)
        snap2 = db.get_org_departments().copy()
        snap2.loc[snap2["dept_code"] == target, "group_code"] = other
        db.save_org_departments(snap2[db.ORG_DEPT_COLUMNS])
        check("부서 그룹 재귀속 → 사용자 경로(dept_group_map) 반영",
              db.dept_group_map().get(target, (None,))[0] == other)
        # 원복(다른 테스트 격리)
        snap2.loc[snap2["dept_code"] == target, "group_code"] = cur
        db.save_org_departments(snap2[db.ORG_DEPT_COLUMNS])


# ===========================================================================
# Part B — supabase 모드 read-only 라이브 probe (테스트 프로젝트 한정, 쓰기 없음)
# ===========================================================================
def part_b_live() -> None:
    print("Part B — supabase read-only 라이브 probe (group_id 계층)")
    if not config.supabase_configured():
        SKIP.append("live probe: supabase 미설정")
        print("  SKIP - supabase 접속정보 없음 (라이브 probe 생략)")
        return
    if not config.supabase_test_project_confirmed():
        SKIP.append("live probe: 테스트 프로젝트 미승인")
        print("  SKIP - 테스트 프로젝트 미승인 (라이브 probe 생략)")
        return

    os.environ["DUTY_DATA_MODE"] = "supabase"
    from modules import supabase_repository as sr
    sr.reset_org_readiness()

    readiness = db.org_schema_readiness()
    if readiness == db.READINESS_PROBE_ERROR:
        FAIL.append("live probe: 스키마 확인 실패(PROBE_ERROR) — 네트워크/권한")
        print("  FAIL - readiness PROBE_ERROR (원인: 네트워크/권한 — 미적용 아님)")
        return
    check("라이브 readiness READY (004 적용)", readiness == db.READINESS_READY, f"readiness={readiness}")
    if readiness != db.READINESS_READY:
        return

    groups = db.get_org_groups()
    check("라이브 그룹 4건", len(groups) == 4, f"len={len(groups)}")
    check("라이브 그룹코드 = {PET,PVC,DECO,ADMIN}",
          set(groups["group_code"].astype(str)) == {"PET", "PVC", "DECO", "ADMIN"})

    depts = db.get_org_departments()
    check("라이브 부서 5건", len(depts) == 5, f"len={len(depts)}")
    check("라이브 부서코드 = {PET,PVC,DECO,MTRL,ADMIN}",
          set(depts["dept_code"].astype(str)) == {"PET", "PVC", "DECO", "MTRL", "ADMIN"})
    check("모든 부서가 group_id→group_code 로 연결(미배정 0)",
          int((depts["group_code"].astype(str) == "").sum()) == 0)
    dg = depts.set_index("dept_code")["group_code"].astype(str).to_dict()
    check("MTRL 은 PET 그룹 소속 부서(승인 매핑)", dg.get("MTRL") == "PET")
    check("PET/PVC/DECO/ADMIN 자기 그룹 소속",
          dg.get("PET") == "PET" and dg.get("PVC") == "PVC"
          and dg.get("DECO") == "DECO" and dg.get("ADMIN") == "ADMIN")

    teams = db.get_org_teams()
    check("라이브 조 6건", len(teams) == 6, f"len={len(teams)}")
    check("모든 조의 dept_code 가 부서에 존재(department_id FK 무결성)",
          set(teams["dept_code"].astype(str)).issubset(set(depts["dept_code"].astype(str))))

    # 그룹별 부서 조회(group_id 필터) — PET 그룹은 {PET, MTRL}
    pet_depts = db.get_org_departments(group_code="PET")
    check("group_code=PET 필터 → {PET,MTRL}",
          set(pet_depts["dept_code"].astype(str)) == {"PET", "MTRL"})
    # 부서별 조 조회(department_id 필터)
    pet_teams = db.get_org_teams(dept_code="PET")
    check("dept_code=PET 필터 → 조 3건(A/B/C)",
          set(pet_teams["team_code"].astype(str)) == {"A", "B", "C"})

    print("  (read-only 확인 — 라이브 데이터 무변경)")


def main() -> None:
    part_a_sample()
    print()
    part_a2_store_unification()
    print()
    try:
        part_b_live()
    except Exception as exc:  # noqa: BLE001 — 원인 구분 보고
        FAIL.append(f"live probe 예외: {type(exc).__name__}")
        print(f"  FAIL - live probe 예외(원인 구분): {type(exc).__name__}: {exc}")

    print()
    if SKIP:
        print("SKIPPED: " + "; ".join(SKIP))
    if FAIL:
        print(f"FAILED {len(FAIL)}: {FAIL}")
        sys.exit(1)
    print(f"ALL PASSED ({PASS} checks)")


if __name__ == "__main__":
    main()
