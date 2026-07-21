"""조직 관리(master_org) 재구현 focused 계약 테스트 (Phase4 Lane D).

기존 ``test_master_org.py`` 는 데이터·도메인 계약(순수 함수)을 지키는 회귀 가드다.
이 파일은 **재구현으로 새로 도입된 UI 계약**을 검증한다:

- 공통 기반(``views/master``) 위에 재구현: DraftState/MasterGridSpec/run_save/
  ReadinessState/master_action_bar/ledger_banner/공통 style 을 실제로 사용하는가.
- page-scoped 편집 상태(org_dept/org_unit) — 공용 ``ms_*`` action key 누수 없음.
- migration readiness 3-state: NOT_READY 면 좌·우 write control 비활성 + 조회 전용 배너.
- dirty_total 공식(신규+기존변경)·view-model 메타(_inactive/_protected/_delete).
- 화면이 공통 크롬/패널 계약으로 렌더된다(제목·패널·흐름 스텝, 예외 없음).
- 보존된 순수 함수 계약 스모크(회귀 이중 확인).

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_master_org_new.py
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

from modules import db  # noqa: E402
from views import master_org  # noqa: E402
from views import master as master_pkg  # noqa: E402

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


# ===== 1) 공통 기반(views/master) 위에 재구현 =====
print("공통 기반 사용 — DraftState/MasterGridSpec/run_save/ReadinessState")
src = master_org.__file__ and Path(master_org.__file__).read_text(encoding="utf-8")
check("공통 기반 패키지에서 import", "from views.master import" in src)
for token in ("DraftState", "MasterGridSpec", "render_master_grid", "run_save",
              "ReadinessState", "master_action_bar", "ledger_banner", "PersistResult"):
    check(f"공통 기반 심볼 사용: {token}", token in src)
check("workspace 공용 grid 헬퍼에 더 이상 의존하지 않음",
      "selectable_master_grid" not in src and "from views import workspace" not in src)
check("page-scoped 좌/우 상태(org_dept/org_unit)", 'DraftState("org_dept")' in src
      and 'DraftState("org_unit")' in src)
check("공용 ms_* action 플래그 잔재 없음",
      "od_save_req" not in src and "ou_save_req" not in src and "ms_save_req" not in src)

# 공통 기반 공개 API 가 실제로 존재(계약 결합 확인)
for attr in ("DraftState", "MasterGridSpec", "run_save", "ReadinessState",
             "master_action_bar", "ledger_banner", "PersistResult", "count_strip",
             "dirty_total", "confirm_bar", "mode_badge_html"):
    check(f"views.master 공개 API 존재: {attr}", hasattr(master_pkg, attr))


# ===== 2) 화면 렌더 — 공통 크롬/패널 계약 (예외 없음) =====
print("화면 렌더 — 공통 크롬·패널·흐름 스텝")


def _screen_render():
    from modules import db as app_db
    from views import master_org as mo
    mo.render(app_db.find_user_by_emp_no("1001"))


at = AppTest.from_function(_screen_render, default_timeout=45).run()
check("렌더 예외 없음", not at.exception)
body = " ".join(str(m.value) for m in at.markdown)
check("페이지 제목(조직 관리) 표시", "조직 관리" in body)
check("좌 패널 제목(그룹 · 부서 구조)", "그룹 · 부서 구조" in body)
check("우 패널 제목(운영단위)", "운영단위" in body)
check("공통 헤더 크롬(ms-head/ms-title)", "ms-head" in body and "ms-title" in body)
check("공통 패널 클래스(ms-panel)", "ms-panel" in body)
check("그룹→부서→운영단위 흐름 스텝", "org-flow-step" in body)
check("모드 배지(데이터 연결) 표시", "ms-mode" in body and "샘플 데이터" in body)
# 좌/우 액션 버튼이 page-scoped role key 로 존재
keys = {b.key for b in at.button}
for k in ("org_dept__save", "org_dept__addg", "org_dept__add", "org_dept__delete",
          "org_dept__refresh", "org_unit__save", "org_unit__add"):
    check(f"page-scoped 버튼 키 존재: {k}", k in keys)


def _save_button(app_test, key):
    for b in app_test.button:
        if b.key == key:
            return b
    return None


# 갓 로드된 화면은 dirty=0 → 저장 비활성 (§8: dirty 일 때만 활성)
sv = _save_button(at, "org_dept__save")
check("갓 로드 시 좌 저장 버튼 존재", sv is not None)
if sv is not None and hasattr(sv, "disabled"):
    check("갓 로드 시 좌 저장 비활성(변경 없음)", bool(sv.disabled))
else:  # 속성 미노출 환경 — 라벨로 대체 확인(변경 0이면 badge 없음)
    check("갓 로드 시 좌 저장 라벨에 변경 badge 없음", sv is not None and sv.label == "저장")


# ===== 3) migration readiness 3-state (READY/NOT_READY/PROBE_ERROR) =====
print("readiness 3-state — 좌·우 write 전부 비활성 + 상태별 배너/배지 + 재확인")
check("_readiness 가 3-state db.org_schema_readiness() 를 사용", "org_schema_readiness" in src)
check("PROBE_ERROR 시 reset_org_schema_cache 재probe 동작", "reset_org_schema_cache" in src)


def _all_disabled(app_test, keys):
    for k in keys:
        b = _save_button(app_test, k)
        if b is None:
            return False
        if hasattr(b, "disabled") and not b.disabled:
            return False
    return True


# 좌 4버튼 + 우 add/delete/save 전부 — READY 에서만 활성(§25 all write controls disabled).
_WRITE_KEYS = ("org_dept__save", "org_dept__add", "org_dept__addg", "org_dept__delete",
               "org_unit__save", "org_unit__add", "org_unit__delete")
_orig_readiness = db.org_schema_readiness
try:
    # --- NOT_READY: migration 003 미적용(확인 성공) ---
    db.org_schema_readiness = lambda: db.READINESS_NOT_READY
    at_nr = AppTest.from_function(_screen_render, default_timeout=45).run()
    check("NOT_READY 렌더 예외 없음", not at_nr.exception)
    nr_body = " ".join(str(m.value) for m in at_nr.markdown)
    check("NOT_READY 조회 전용 경고 배너 표시", "migration 003" in nr_body and "조회만 가능" in nr_body)
    check("NOT_READY 스키마 배지(모드 배지와 분리)", "migration 미적용" in nr_body)
    check("NOT_READY 좌·우 모든 write 버튼 비활성(공통 can_write)", _all_disabled(at_nr, _WRITE_KEYS))
    check("NOT_READY 에도 새로고침(조회)은 활성",
          not _all_disabled(at_nr, ("org_dept__refresh",)))

    # --- PROBE_ERROR: 확인 자체 실패(권한/네트워크) ---
    db.org_schema_readiness = lambda: db.READINESS_PROBE_ERROR
    at_pe = AppTest.from_function(_screen_render, default_timeout=45).run()
    check("PROBE_ERROR 렌더 예외 없음", not at_pe.exception)
    pe_body = " ".join(str(m.value) for m in at_pe.markdown)
    check("PROBE_ERROR 상태 확인 실패 배너/배지", "확인 실패" in pe_body)
    check("PROBE_ERROR 재확인 버튼 노출", any(b.key == "org__recheck" for b in at_pe.button))
    check("PROBE_ERROR 좌·우 모든 write 버튼 비활성", _all_disabled(at_pe, _WRITE_KEYS))
finally:
    db.org_schema_readiness = _orig_readiness

# READY(sample) 는 write 가능 상태
ready = master_org._readiness()
check("sample 모드는 READY(write 가능)", ready.write_enabled)


# ===== 3b) 반응형 — ≤1100px 세로 스택 CSS + 버튼 nowrap =====
print("반응형 — ≤1100px 2패널 세로 스택 + 액션바 버튼 nowrap(눌림 방지)")
check("패널 행 스코프 컨테이너(org__panels)", "org__panels" in src)
check("≤1100px 미디어쿼리로 세로 스택", "@media (max-width: 1100px)" in src and "flex:1 1 100%" in src)
check("액션바 버튼 white-space:nowrap(부/서 눌림 방지)", "white-space:nowrap" in src)


# ===== 3c) 부분성공 원장 API 사용 + 삭제 예외 처리 =====
print("저장 원장(save_*_report) 사용 · 좌/우 별도 ledger · 삭제 예외 처리(B2/B4)")
check("좌 저장이 save_org_departments_report 사용", "save_org_departments_report" in src)
check("우 저장이 save_org_teams_report 사용", "save_org_teams_report" in src)
check("PersistResult 를 report.to_persist_kwargs 로 구성", "to_persist_kwargs()" in src)
check("좌/우를 한 명령으로 합치지 않음(save_org_structure_report 미사용)",
      "save_org_structure_report" not in src)
check("부서 삭제 예외 포착(DATA_SOURCE_ERRORS)", src.count("except db.DATA_SOURCE_ERRORS") >= 4)
check("삭제 실패 시 재시도 안내 flash", "재시도하세요" in src)


# ===== 3d) 부분성공 원장 동작(주입) — saved/failed 키 표시·완전성공 미단정 =====
print("부분성공 원장 동작 — 좌 저장 partial 주입(§22)")
import modules.supabase_repository as _sr  # noqa: E402
_orig_rep = db.save_org_departments_report
_orig_conf = db.display_order_conflicts
db.save_org_departments_report = lambda merged: _sr.BatchWriteResult(
    saved_keys=["PET1"], failed_keys=["PET2"], error="주입 실패", retryable=True)
db.display_order_conflicts = lambda users, m: []
try:
    def _partial_probe():
        from modules import db as adb
        from views import master_org as mo
        grid = mo.build_org_rows(adb.get_org_departments()).copy()
        grid["_removed"] = ""
        mo._save_depts(grid, {"active": "전체", "search": ""})

    at_pp = AppTest.from_function(_partial_probe, default_timeout=45).run()
    check("부분성공 렌더 예외 없음", not at_pp.exception)
    pp_body = " ".join(str(m.value) for m in at_pp.markdown)
    check("부분성공 원장에 실패 키 표기(§22)", "실패" in pp_body)
    check("부분성공은 완전성공으로 단정하지 않음(성공 flash 없음)",
          master_org._OD.flash_key not in at_pp.session_state)
finally:
    db.save_org_departments_report = _orig_rep
    db.display_order_conflicts = _orig_conf


# ===== 3e) 삭제 실행 예외가 raw 로 새지 않고 성공/실패로 구분(B4) =====
print("삭제 실행 예외 → error flash 구분(raw 예외 방지)")
_orig_del = db.delete_department
db.delete_department = lambda code: (_ for _ in ()).throw(db.DATA_SOURCE_ERRORS[0]("주입 실패"))
try:
    def _delete_fail_probe():
        import streamlit as st
        from views import master_org as mo
        if st.session_state.get("_dfp"):
            return  # rerun 재진입 시 no-op (무한 rerun 방지)
        st.session_state["_dfp"] = True
        try:
            mo._execute_dept_delete(
                {"delete": ["ZZZZ"], "deactivate": [], "block": []},
                {"active": "전체", "search": ""},
            )
        except BaseException:
            pass  # st.rerun() 신호 등은 무시(여기서는 flash 만 확인)

    at_df = AppTest.from_function(_delete_fail_probe, default_timeout=45).run()
    check("삭제 예외가 raw 로 새지 않음(렌더 예외 없음)", not at_df.exception)
    _fk = master_org._OD.flash_key
    flash = at_df.session_state[_fk] if _fk in at_df.session_state else None
    check("삭제 실패가 error flash 로 구분 표기",
          bool(flash) and flash[0] == "error" and "실패" in flash[1])
finally:
    db.delete_department = _orig_del


# ===== 4) dirty_total 공식 · view-model 메타 =====
print("dirty_total(신규+기존변경) · view-model 메타(_inactive/_protected/_delete)")


def _dirty_probe():
    # AppTest.from_function 은 본문을 독립 스크립트로 실행하므로 자기완결로 작성한다.
    import pandas as pd
    import streamlit as st
    from views import master_org as mo
    st.session_state[mo._OD.key("baseline")] = {
        "e:D1": ("PET생산부", "1", "PET", "D1", "True"),
    }
    live = pd.DataFrame([
        {"_row_id": "e:D1", "_row_state": "existing", "_sel": False, "그룹·부서명": "PET생산부수정",
         "순서": "1", "소속그룹": "PET", "부서코드": "D1", "사용": True},   # 기존 변경 1
        {"_row_id": "n:1", "_row_state": "new", "_sel": False, "그룹·부서명": "새부서",
         "순서": "1", "소속그룹": "PET", "부서코드": "NEW", "사용": True},   # 신규 1
        {"_row_id": "gn:1", "_row_state": "group", "_sel": False, "그룹·부서명": "",
         "순서": "", "소속그룹": "", "부서코드": "", "사용": True},          # 빈 신규 그룹(제외)
    ])
    new_cnt, changed_cnt = mo._dirty_counts(mo._OD, live, mo._DEPT_COLS)
    st.write(f"NEW={new_cnt};CHANGED={changed_cnt};TOTAL={mo.dirty_total(new_cnt, changed_cnt)}")


at_d = AppTest.from_function(_dirty_probe, default_timeout=45).run()
check("dirty probe 예외 없음", not at_d.exception)
dtext = " ".join(str(m.value) for m in at_d.markdown)
check("신규 행만 신규로 집계(빈 신규 그룹 제외)", "NEW=1" in dtext)
check("baseline 대비 변경만 기존 변경으로 집계", "CHANGED=1" in dtext)
check("dirty_total = 신규+기존변경", "TOTAL=2" in dtext)


def _meta_probe():
    import pandas as pd
    import streamlit as st
    from views import master_org as mo
    rows = mo.build_org_rows(pd.DataFrame([
        {"dept_code": "ADMIN", "dept_name": "관리부", "department_group": "SYS",
         "group_sort_order": 1, "sort_order": 1, "is_active": True},
        {"dept_code": "PET1", "dept_name": "PET생산부", "department_group": "PET",
         "group_sort_order": 2, "sort_order": 1, "is_active": False},
    ]))
    disp = mo._dept_display(rows)
    admin = disp[disp["부서코드"] == "ADMIN"].iloc[0]
    inact = disp[disp["부서코드"] == "PET1"].iloc[0]
    st.write(f"PROT={admin['_protected']};INACT={inact['_inactive']}")


at_m = AppTest.from_function(_meta_probe, default_timeout=45).run()
check("메타 probe 예외 없음", not at_m.exception)
mtext = " ".join(str(m.value) for m in at_m.markdown)
check("ADMIN 부서는 _protected=1(보호·선택 비활성)", "PROT=1" in mtext)
check("비활성 부서는 _inactive=1(미사용 시각)", "INACT=1" in mtext)


# ===== 5) 저장 프로토콜 가드 =====
print("저장 프로토콜 — 부서 미선택 시 운영단위 저장 차단")


def _save_units_no_dept():
    from views import master_org as mo
    mo._save_units(None, "")


at_g = AppTest.from_function(_save_units_no_dept, default_timeout=45).run()
check("부서 미선택 운영단위 저장 차단 오류", any("부서를 먼저 선택" in str(e.value) for e in at_g.error))


# ===== 6) 보존된 순수 함수 계약 스모크(회귀 이중 확인) =====
print("보존 순수 함수 스모크 — build_org_rows/parse_org_grid/구조검증/validate_units")
rows = master_org.build_org_rows(pd.DataFrame([
    _dept("PET1", "PET생산부", "PET", 1, 1),
    _dept("PET2", "PET원료실", "PET", 1, 1),
    _dept("PVC1", "PVC생산부", "PVC", 2, 1),
]))
check("계층 모델: 그룹 부모 2 + 부서 자식 3",
      int((rows["_row_state"] == "group").sum()) == 2
      and int((rows["_row_state"] != "group").sum()) == 3)

store = pd.DataFrame([
    _dept("PET1", "PET생산부", "PET", 1, 1),
    _dept("PET2", "PET원료실", "PET", 1, 1),
])
recs, errs = master_org.parse_org_grid(_meta_rows([
    _grow("g:PET", "PET그룹", 1),
    _drow("e:PET1", "PET생산부", 1, "PET", "PET1"),
]), store)
by = {r["dept_code"]: r for r in recs}
check("그룹 rename 이 화면 밖 같은 그룹 부서로 전파", not errs
      and by.get("PET2", {}).get("department_group") == "PET그룹")

check("빈 새 그룹 저장 차단", any("부서가 없습니다" in e for e in master_org.parse_org_grid(
    _meta_rows([_grow("gn:1", "DECO", 3)]), store)[1]))
check("그룹순서 전역 유일 위반 차단", any("여러 그룹" in e for e in master_org._group_structure_errors(
    pd.DataFrame([_dept("D1", "부서1", "PET", 1, 1), _dept("D2", "부서2", "PVC", 1, 1)]))))
u_recs, u_errs = master_org._validate_units(_meta_rows([
    {"코드": "A", "명칭": "A조", "유형": "교대", "표시순서": "1", "사용": True},
    {"코드": "B", "명칭": "상근", "유형": "심야", "표시순서": "2", "사용": True},
]), "D1")
check("운영단위 교대→SHIFT + 허용 외 유형 차단",
      u_recs[0]["unit_type"] == "SHIFT" and any("유형" in e for e in u_errs))


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
