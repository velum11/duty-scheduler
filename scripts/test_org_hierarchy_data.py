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
    check("ORG_DEPT_COLUMNS 는 group_code+대분류/중분류+근태대상 기반(003 잔재 제거)",
          db.ORG_DEPT_COLUMNS == ["dept_code", "dept_name", "group_code",
                                  "major_category", "minor_category",
                                  "description", "sort_order", "is_active",
                                  "tracks_attendance"])
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
    check("USER_COLUMNS 안정(009: 입사일/퇴사일 포함)",
          db.USER_COLUMNS == ["emp_no", "name", "dept_code", "team_code", "position",
                              "role", "is_active", "display_order",
                              "hire_date", "resign_date"])
    check("get_users 컬럼 계약 유지", list(db.get_users().columns) == db.USER_COLUMNS)
    check("get_work_types 컬럼 계약 유지", list(db.get_work_types().columns) == db.WORK_TYPE_COLUMNS)


# ===========================================================================
# Part A3 — 근태(근무표) 등록 대상 부서 지정 (departments.tracks_attendance)
#   조회 계약 · 저장 왕복 · 미편집 컬럼 보존 · 신규 부서 기본값 · 폴백(fail-open
#   조회 / fail-closed 저장) · sample↔supabase 동형을 고정한다.
# ===========================================================================
def part_a3_attendance_flag() -> None:
    os.environ["DUTY_DATA_MODE"] = "sample"
    print("Part A3 — 근태 등록 대상 부서 지정(tracks_attendance)")

    import streamlit as st  # noqa: PLC0415 — bare 모드 세션 스토어 직접 정리용

    from modules import supabase_repository as sr  # noqa: PLC0415

    # 이전 Part 가 남긴 세션 부서 스토어를 비워 CSV seed 로 다시 시작한다.
    st.session_state.pop("store_departments", None)

    depts = db.get_org_departments()
    check("부서 조회에 tracks_attendance 포함", "tracks_attendance" in depts.columns)
    check("tracks_attendance dtype 은 bool(필터 가능)",
          str(depts["tracks_attendance"].dtype) == "bool",
          f"dtype={depts['tracks_attendance'].dtype}")

    # sample seed 는 live 백필과 같은 규칙(근무 기록 있는 부서만 true)을 쓴다.
    flags = dict(zip(depts["dept_code"].astype(str), depts["tracks_attendance"].astype(bool)))
    check("sample seed: 근무 기록 있는 부서만 근태 대상(PET1/PET2=true, MGT=false)",
          flags.get("PET1") is True and flags.get("PET2") is True and flags.get("MGT") is False,
          f"flags={flags}")

    codes = db.attendance_dept_codes()
    check("attendance_dept_codes() 는 지정된 부서만 반환",
          codes == {c for c, f in flags.items() if f}, f"codes={codes}")
    check("attendance_dept_codes() 는 set[str] 계약",
          isinstance(codes, set) and all(isinstance(c, str) for c in codes))
    check("sample 모드는 근태 지정 capability 준비 상태", db.attendance_flag_ready() is True)

    # (a) 저장 왕복 — 미지정 부서를 대상으로 켰다가 되돌린다.
    store = db.get_org_departments().copy()
    store.loc[store["dept_code"].astype(str) == "MGT", "tracks_attendance"] = True
    db.save_org_departments(store[db.ORG_DEPT_COLUMNS])
    check("저장 왕복: MGT 를 근태 대상으로 지정하면 조회에 반영",
          "MGT" in db.attendance_dept_codes())

    # (b) 미편집 보존 — 화면이 아직 이 컬럼을 다루지 않는 저장 입력(컬럼 자체 없음)이
    #     기존 지정을 지우지 않아야 한다(조직 화면 저장 1회로 전 부서 지정 해제 방지).
    without = db.get_org_departments().drop(columns=["tracks_attendance"])
    db.save_org_departments(without)
    check("보존: tracks_attendance 없는 저장 입력이 기존 지정을 지우지 않음",
          db.attendance_dept_codes() == {"PET1", "PET2", "MGT"},
          f"codes={db.attendance_dept_codes()}")

    # (c) 빈 값(NaN) 보존 — 그리드가 컬럼은 넘기되 값을 비운 경우도 같다.
    blanked = db.get_org_departments().copy()
    blanked["tracks_attendance"] = pd.NA
    db.save_org_departments(blanked)
    check("보존: 빈 값(NaN) 저장 입력도 기존 지정을 유지",
          db.attendance_dept_codes() == {"PET1", "PET2", "MGT"})

    # (d) 되돌리기 — 명시 False 는 정상 반영된다(보존이 '수정 불가'가 아님).
    revert = db.get_org_departments().copy()
    revert.loc[revert["dept_code"].astype(str) == "MGT", "tracks_attendance"] = False
    db.save_org_departments(revert[db.ORG_DEPT_COLUMNS])
    check("명시 False 는 반영됨(보존 규칙이 수정을 막지 않음)",
          db.attendance_dept_codes() == {"PET1", "PET2"})

    # (e) 신규 부서 기본값 — 값 없이 추가하면 대상 아님(명시 지정 원칙, 011 DDL 과 동일).
    added = pd.concat([db.get_org_departments(), pd.DataFrame([{
        "dept_code": "ZZATT", "dept_name": "임시부서", "group_code": "",
        "major_category": "", "minor_category": "",
        "description": "", "sort_order": 98, "is_active": True,
    }])], ignore_index=True)
    db.save_org_departments(added[db.ORG_DEPT_COLUMNS])
    check("신규 부서는 근태 대상 기본값 False(명시 지정 원칙)",
          "ZZATT" not in db.attendance_dept_codes()
          and "ZZATT" in set(db.get_org_departments()["dept_code"].astype(str)))
    db.delete_department("ZZATT")

    # (f) is_active 상호작용 — 미사용 부서는 기본 조회에서 빠지고, is_active=None 이면 포함.
    deact = db.get_org_departments().copy()
    deact.loc[deact["dept_code"].astype(str) == "PET2", "is_active"] = False
    db.save_org_departments(deact[db.ORG_DEPT_COLUMNS])
    check("미사용 부서는 기본(attendance_dept_codes) 결과에서 제외",
          "PET2" not in db.attendance_dept_codes())
    check("is_active=None 이면 미사용 지정 부서도 포함(과거 자료 조회용)",
          "PET2" in db.attendance_dept_codes(is_active=None))

    # 세션 스토어를 CSV seed 로 되돌려 뒤 Part 에 영향을 남기지 않는다.
    st.session_state.pop("store_departments", None)

    # --- supabase 경로 단위 계약 (원격 접속 없음 — capability 만 대체) ---------
    saved = (sr.org_extensions_ready, sr.org_category_ready,
             sr.attendance_flag_ready, sr._group_maps)
    try:
        sr.org_extensions_ready = lambda: True
        sr.org_category_ready = lambda: True
        sr._group_maps = lambda: ({}, {})

        sr.attendance_flag_ready = lambda: True
        rows = [{"dept_code": "D1", "dept_name": "부서1", "sort_order": 1,
                 "is_active": True, "tracks_attendance": False}]
        payload = sr._departments_org_payload(rows)
        check("supabase payload: 명시값이 있으면 tracks_attendance 를 저장한다",
              payload[0].get("tracks_attendance") is False)

        mixed = [dict(rows[0]), {"dept_code": "D2", "dept_name": "부서2", "sort_order": 2,
                                 "is_active": True}]
        payload = sr._departments_org_payload(mixed)
        check("supabase payload: 한 행이라도 값이 없으면 키 자체를 빼 기존 값 보존",
              all("tracks_attendance" not in record for record in payload))

        # 미적용 스키마: 조회는 전 부서 True 폴백, 저장은 False 지정만 차단(fail-closed).
        sr.attendance_flag_ready = lambda: False
        payload = sr._departments_org_payload(
            [{"dept_code": "D1", "dept_name": "부서1", "sort_order": 1,
              "is_active": True, "tracks_attendance": True}]
        )
        check("미적용 스키마: True(=폴백과 동일) 저장은 키를 빼고 통과",
              "tracks_attendance" not in payload[0])
        blocked = False
        try:
            sr._departments_org_payload(
                [{"dept_code": "D1", "dept_name": "부서1", "sort_order": 1,
                  "is_active": True, "tracks_attendance": False}]
            )
        except sr.SupabaseDataError:
            blocked = True
        check("미적용 스키마: '대상 아님' 지정 저장은 차단(fail-closed, 의도 유실 금지)",
              blocked)

        # 조회 폴백: 컬럼이 없어도 부서 목록이 비지 않고 전 부서가 대상이 된다.
        sr._select_all_backup = sr._select_all
        sr._select_all = lambda *a, **k: [
            {"dept_code": "D1", "dept_name": "부서1", "group_id": None,
             "description": "", "sort_order": 1, "is_active": True},
        ]
        frame = sr.get_departments_org()
        check("미적용 스키마 조회 폴백: 전 부서 tracks_attendance=True",
              bool(frame["tracks_attendance"].all()) and len(frame) == 1)
        sr._select_all = sr._select_all_backup
        del sr._select_all_backup
    finally:
        (sr.org_extensions_ready, sr.org_category_ready,
         sr.attendance_flag_ready, sr._group_maps) = saved


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

    # 2026-08-07: 초기 seed(4그룹/5부서/6조) 고정 검증을 폐기했다 — 실조직 125명
    # 적재(그룹 9·부서 32·운영단위 0)로 데이터가 교체됐고, 이후 화면 편집으로 계속
    # 변한다. 특정 건수·코드 대신 **구조 불변식**만 검증한다(live 데이터 형태 불문).
    groups = db.get_org_groups()
    check("라이브 그룹 1건 이상", not groups.empty, f"len={len(groups)}")
    check("시스템 필수 ADMIN 그룹 존재(화면 보호 대상)",
          "ADMIN" in set(groups["group_code"].astype(str)))

    depts = db.get_org_departments()
    check("라이브 부서 1건 이상", not depts.empty, f"len={len(depts)}")
    check("시스템 필수 ADMIN 부서 존재(화면 보호 대상)",
          "ADMIN" in set(depts["dept_code"].astype(str)))
    check("모든 부서가 group_id→group_code 로 연결(미배정 0)",
          int((depts["group_code"].astype(str) == "").sum()) == 0)
    check("부서 대분류/중분류 컬럼 존재(009 적용)",
          "major_category" in depts.columns and "minor_category" in depts.columns)
    check("중분류가 있는 부서는 대분류도 있음(계층 정합)",
          depts[(depts["minor_category"].astype(str).str.strip() != "")
                & (depts["major_category"].astype(str).str.strip() == "")].empty)

    # 근태 등록 대상 지정 — 적용 여부를 파일명이 아니라 capability probe 로 판정한다.
    # 미적용 환경에서도 실패가 아니라 '폴백이 실제로 동작하는지'를 검증한다.
    check("라이브 부서 조회에 tracks_attendance 컬럼 계약 포함",
          "tracks_attendance" in depts.columns)
    tracked = db.attendance_dept_codes()
    if db.attendance_flag_ready():
        check("근태 대상 지정 적용 환경: 대상 부서가 전체보다 좁거나 같음",
              tracked <= set(depts["dept_code"].astype(str)),
              f"tracked={len(tracked)} / depts={len(depts)}")
        check("근태 대상 지정 적용 환경: 지정 결과가 조회 계약과 일치",
              tracked == {
                  str(code).strip() for code, flag, active in zip(
                      depts["dept_code"], depts["tracks_attendance"], depts["is_active"])
                  if bool(flag) and bool(active)
              })
        print(f"  (근태 대상 부서 {len(tracked)}건 / 전체 {len(depts)}건 — read-only)")
    else:
        SKIP.append("근태 대상 지정 스키마 미적용 — 조회 폴백 경로만 확인")
        check("미적용 라이브: 폴백으로 전 부서가 근태 대상(목록이 비지 않음)",
              bool(depts["tracks_attendance"].astype(bool).all())
              and tracked == set(depts[depts["is_active"].astype(bool)]["dept_code"].astype(str)))

    teams = db.get_org_teams()
    check("모든 조의 dept_code 가 부서에 존재(department_id FK 무결성)",
          set(teams["dept_code"].astype(str)).issubset(set(depts["dept_code"].astype(str))),
          f"orphans={set(teams['dept_code'].astype(str)) - set(depts['dept_code'].astype(str))}")

    # 그룹별 부서 조회(group_id 필터) — 필터 결과가 자기 그룹 부서만 담는지(건수 불문)
    admin_group = "ADMIN"
    admin_depts = db.get_org_departments(group_code=admin_group)
    check("group_code 필터 결과는 해당 그룹 소속만",
          set(admin_depts["group_code"].astype(str)) <= {admin_group})

    users = db.get_users()
    check("라이브 사용자 입사일/퇴사일 컬럼 존재(009 적용)",
          "hire_date" in users.columns and "resign_date" in users.columns)

    print("  (read-only 확인 — 라이브 데이터 무변경)")


def main() -> None:
    part_a_sample()
    print()
    part_a3_attendance_flag()
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
