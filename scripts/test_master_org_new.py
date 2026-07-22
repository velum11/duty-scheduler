"""조직 관리(master_org) 3시트 재구현 focused UI 계약 테스트.

``test_master_org.py`` 가 데이터·도메인 계약(순수 함수·드릴다운 데이터계층)을 지키는
회귀 가드라면, 이 파일은 **가로 3시트 [그룹][부서][조] 재구현의 UI 계약**을 검증한다:

- 공통 기반(``views/master``) 위에 재구현: DraftState/MasterGridSpec/render_master_grid/
  run_save/ReadinessState/master_action_bar/ledger_banner/sheet_head/sheet_locked/
  drilldown_context 를 실제로 사용하는가.
- page-scoped 3시트 상태(org_group/org_dept/org_unit) — 공용 ``ms_*`` action key 누수 없음.
- migration readiness 3-state: NOT_READY 면 세 시트의 모든 write control 비활성 + 조회 전용 배너.
- 상위 미선택 시 하위 시트 잠금(sheet_locked + can_write=False), 드릴다운 컨텍스트 스트립.
- dirty_total 공식(신규+기존변경)·view-model 메타(_inactive/_protected/_linked).
- 부분성공 원장(save_*_report → to_persist_kwargs) + 삭제 예외 처리.
- 화면이 공통 크롬/시트 계약으로 렌더된다(제목·시트·드릴다운, 예외 없음).

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


src = Path(master_org.__file__).read_text(encoding="utf-8")


# ===== 1) 공통 기반 위에 재구현 =====
print("공통 기반 사용 — DraftState/MasterGridSpec/run_save/ReadinessState/시트 컴포넌트")
check("공통 기반 패키지에서 import", "from views.master import" in src)
for token in ("DraftState", "MasterGridSpec", "render_master_grid", "run_save",
              "ReadinessState", "master_action_bar", "ledger_banner", "PersistResult",
              "sheet_head", "sheet_locked", "drilldown_context"):
    check(f"공통 기반 심볼 사용: {token}", token in src)
check("workspace 공용 grid 헬퍼에 의존하지 않음",
      "selectable_master_grid" not in src and "from views import workspace" not in src)
check("page-scoped 3시트 상태(org_group/org_dept/org_unit)",
      'DraftState("org_group")' in src and 'DraftState("org_dept")' in src
      and 'DraftState("org_unit")' in src)
check("공용 ms_* action 플래그 잔재 없음",
      "od_save_req" not in src and "ou_save_req" not in src and "ms_save_req" not in src)
for attr in ("DraftState", "MasterGridSpec", "run_save", "ReadinessState",
             "master_action_bar", "ledger_banner", "PersistResult", "count_strip",
             "dirty_total", "confirm_bar", "mode_badge_html", "sheet_head",
             "sheet_locked", "drilldown_context", "empty_state"):
    check(f"views.master 공개 API 존재: {attr}", hasattr(master_pkg, attr))


# ===== 2) 화면 렌더 — 공통 크롬·3시트·드릴다운 =====
print("화면 렌더 — 공통 크롬·3시트·드릴다운 컨텍스트")


def _screen_render():
    from modules import db as app_db
    from views import master_org as mo
    mo.render(app_db.find_user_by_emp_no("1001"))


at = AppTest.from_function(_screen_render, default_timeout=45).run()
check("렌더 예외 없음", not at.exception)
body = " ".join(str(m.value) for m in at.markdown)
check("페이지 제목(조직 관리) 표시", "조직 관리" in body)
check("그룹 시트 제목", "<span class='t'>그룹</span>" in body)
check("부서 시트 제목", "<span class='t'>부서</span>" in body)
check("조 시트 제목", "<span class='t'>조</span>" in body)
check("공통 헤더 크롬(ms-head/ms-title)", "ms-head" in body and "ms-title" in body)
check("공통 시트 헤더(ms-sheet-head) 3개 이상", body.count("ms-sheet-head") >= 3)
check("드릴다운 컨텍스트 스트립(ms-ctx)", "ms-ctx" in body)
check("모드 배지(데이터 연결) 표시", "ms-mode" in body and "샘플 데이터" in body)
check("상태 스트립(ms-count)", "ms-count" in body)
keys = {b.key for b in at.button}
for k in ("org_group__save", "org_group__add", "org_group__delete", "org_group__refresh",
          "org_dept__save", "org_dept__add", "org_dept__delete", "org_dept__refresh",
          "org_unit__save", "org_unit__add", "org_unit__delete", "org_unit__refresh"):
    check(f"page-scoped 버튼 키 존재: {k}", k in keys)


def _save_button(app_test, key):
    for b in app_test.button:
        if b.key == key:
            return b
    return None


# 갓 로드된 화면은 dirty=0 → 저장 비활성
for skey in ("org_group__save", "org_dept__save", "org_unit__save"):
    sv = _save_button(at, skey)
    check(f"갓 로드 시 {skey} 존재", sv is not None)
    if sv is not None and hasattr(sv, "disabled"):
        check(f"갓 로드 시 {skey} 비활성(변경 없음)", bool(sv.disabled))
    else:
        check(f"갓 로드 시 {skey} 라벨에 변경 badge 없음", sv is not None and sv.label == "저장")


# ===== 2b) 드릴다운 단일 선택 selectbox =====
print("드릴다운 단일 선택 — 그룹/부서 selectbox")
sb_keys = {s.key for s in at.selectbox}
check("그룹 단일 선택 selectbox 존재", "og_group" in sb_keys)
check("부서 단일 선택 selectbox 존재(부서/조 드릴다운)",
      "og_dept" in sb_keys or "og_dept_empty" in sb_keys)


# ===== 3) migration readiness 3-state =====
print("readiness 3-state — 세 시트 write 전부 비활성 + 상태별 배너/배지 + 재확인")
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


_WRITE_KEYS = ("org_group__save", "org_group__add", "org_group__delete",
               "org_dept__save", "org_dept__add", "org_dept__delete",
               "org_unit__save", "org_unit__add", "org_unit__delete")
_orig_readiness = db.org_schema_readiness
try:
    db.org_schema_readiness = lambda: db.READINESS_NOT_READY
    at_nr = AppTest.from_function(_screen_render, default_timeout=45).run()
    check("NOT_READY 렌더 예외 없음", not at_nr.exception)
    nr_body = " ".join(str(m.value) for m in at_nr.markdown)
    check("NOT_READY 조회 전용 경고 배너", "migration 004" in nr_body and "조회만 가능" in nr_body)
    check("NOT_READY 스키마 배지(모드 배지와 분리)", "migration 미적용" in nr_body)
    check("NOT_READY 세 시트 모든 write 버튼 비활성", _all_disabled(at_nr, _WRITE_KEYS))
    check("NOT_READY 에도 새로고침(조회)은 활성",
          not _all_disabled(at_nr, ("org_group__refresh",)))

    db.org_schema_readiness = lambda: db.READINESS_PROBE_ERROR
    at_pe = AppTest.from_function(_screen_render, default_timeout=45).run()
    check("PROBE_ERROR 렌더 예외 없음", not at_pe.exception)
    pe_body = " ".join(str(m.value) for m in at_pe.markdown)
    check("PROBE_ERROR 상태 확인 실패 배너/배지", "확인 실패" in pe_body)
    check("PROBE_ERROR 재확인 버튼 노출", any(b.key == "org__recheck" for b in at_pe.button))
    check("PROBE_ERROR 세 시트 모든 write 버튼 비활성", _all_disabled(at_pe, _WRITE_KEYS))
finally:
    db.org_schema_readiness = _orig_readiness

check("sample 모드는 READY(write 가능)", master_org._readiness().write_enabled)


# ===== 3b) 상위 미선택 시 하위 시트 잠금 =====
print("상위 미선택 → 하위 시트 잠금(sheet_locked + write 비활성)")
_orig_groups = db.get_org_groups
try:
    db.get_org_groups = lambda *a, **k: db._typed_empty_frame(db.ORG_GROUP_COLUMNS)
    at_lock = AppTest.from_function(_screen_render, default_timeout=45).run()
    check("그룹 0개 렌더 예외 없음", not at_lock.exception)
    lock_body = " ".join(str(m.value) for m in at_lock.markdown)
    check("그룹 미선택 → 부서 시트 잠금 안내", "그룹을 먼저 선택하세요" in lock_body)
    check("부서 미선택 → 조 시트 잠금 안내", "부서를 먼저 선택하세요" in lock_body)
    check("잠금 시트도 액션바 키 유지(비활성)",
          _all_disabled(at_lock, ("org_dept__save", "org_unit__save")))
finally:
    db.get_org_groups = _orig_groups


# ===== 3c) 반응형/nowrap + 시트 카드 컨테이너 =====
print("반응형 시트 스택(공통) + 액션바 nowrap + 시트 카드 컨테이너")
check("시트 카드 컨테이너 키(org_group/dept/unit __sheet)",
      "org_group__sheet" in src and "org_dept__sheet" in src and "org_unit__sheet" in src)
check("액션바 버튼 white-space:nowrap(눌림 방지)", "white-space:nowrap" in src)


# ===== 3d) 부분성공 원장 API + 삭제 예외 처리 =====
print("저장 원장(save_*_report) 사용 · 시트별 독립 ledger · 삭제 예외 처리")
check("그룹 저장이 save_org_groups_report 사용", "save_org_groups_report" in src)
check("부서 저장이 save_org_departments_report 사용", "save_org_departments_report" in src)
check("조 저장이 save_org_teams_report 사용", "save_org_teams_report" in src)
check("PersistResult 를 report.to_persist_kwargs 로 구성", "to_persist_kwargs()" in src)
check("시트별 독립(save_org_structure_report 미사용)", "save_org_structure_report" not in src)
check("삭제/저장 예외 포착(DATA_SOURCE_ERRORS)", src.count("except db.DATA_SOURCE_ERRORS") >= 6)
check("삭제 실패 시 재시도 안내 flash", "재시도하세요" in src)


# ===== 3e) 부분성공 원장 동작(주입) — 부서 저장 partial =====
print("부분성공 원장 동작 — 부서 저장 partial 주입(§22)")
import modules.supabase_repository as _sr  # noqa: E402
_orig_rep = db.save_org_departments_report
db.save_org_departments_report = lambda merged: _sr.BatchWriteResult(
    saved_keys=["PET"], failed_keys=["MTRL"], error="주입 실패", retryable=True)
try:
    def _partial_probe():
        from modules import db as adb
        from views import master_org as mo
        grp = str(adb.get_org_departments().iloc[0]["group_code"])
        grid = mo.build_dept_rows(adb.get_org_departments(group_code=grp)).copy()
        grid["_removed"] = ""
        mo._save_depts(grid, {"active": "전체", "search": "", "group": grp}, grp)

    at_pp = AppTest.from_function(_partial_probe, default_timeout=45).run()
    check("부분성공 렌더 예외 없음", not at_pp.exception)
    pp_body = " ".join(str(m.value) for m in at_pp.markdown)
    check("부분성공 원장에 실패 표기(§22)", "실패" in pp_body)
    check("부분성공은 완전성공으로 단정하지 않음(성공 flash 없음)",
          master_org._OD.flash_key not in at_pp.session_state)
finally:
    db.save_org_departments_report = _orig_rep


# ===== 3f) 삭제 실행 예외 → error flash 구분(raw 예외 방지) =====
print("삭제 실행 예외 → error flash 구분")
_orig_del = db.delete_org_group
db.delete_org_group = lambda code: (_ for _ in ()).throw(db.DATA_SOURCE_ERRORS[0]("주입 실패"))
try:
    def _delete_fail_probe():
        import streamlit as st
        from views import master_org as mo
        if st.session_state.get("_dfp"):
            return
        st.session_state["_dfp"] = True
        try:
            mo._execute_group_delete(
                {"delete": ["ZZZZ"], "deactivate": [], "block": []},
                {"active": "전체", "search": ""},
            )
        except BaseException:
            pass

    at_df = AppTest.from_function(_delete_fail_probe, default_timeout=45).run()
    check("삭제 예외가 raw 로 새지 않음(렌더 예외 없음)", not at_df.exception)
    _fk = master_org._GRP.flash_key
    flash = at_df.session_state[_fk] if _fk in at_df.session_state else None
    check("삭제 실패가 error flash 로 구분 표기",
          bool(flash) and flash[0] == "error" and "실패" in flash[1])
finally:
    db.delete_org_group = _orig_del


# ===== 4) dirty_total 공식 · view-model 메타 =====
print("dirty_total(신규+기존변경) · view-model 메타(_inactive/_protected/_linked)")


def _dirty_probe():
    import pandas as pd
    import streamlit as st
    from views import master_org as mo
    st.session_state[mo._OD.key("baseline")] = {
        "e:D1": ("D1", "PET생산부", "1", "", "True"),
    }
    live = pd.DataFrame([
        {"_row_id": "e:D1", "_row_state": "existing", "_sel": False, "코드": "D1",
         "코드명": "PET생산부수정", "순서": "1", "비고": "", "사용": True},   # 기존 변경 1
        {"_row_id": "e:D2", "_row_state": "existing", "_sel": False, "코드": "D2",
         "코드명": "원료실", "순서": "2", "비고": "", "사용": True},          # 변경 없음(집계 제외)
        {"_row_id": "n:1", "_row_state": "new", "_sel": False, "코드": "NEW",
         "코드명": "새부서", "순서": "3", "비고": "", "사용": True},          # 신규 1
    ])
    st.session_state[mo._OD.key("baseline")]["e:D2"] = ("D2", "원료실", "2", "", "True")
    new_cnt, changed_cnt = mo._dirty_counts(mo._OD, live, mo._DEPT_COLS)
    st.write(f"NEW={new_cnt};CHANGED={changed_cnt};TOTAL={mo.dirty_total(new_cnt, changed_cnt)}")


at_d = AppTest.from_function(_dirty_probe, default_timeout=45).run()
check("dirty probe 예외 없음", not at_d.exception)
dtext = " ".join(str(m.value) for m in at_d.markdown)
check("내용 있는 신규 행만 신규로 집계", "NEW=1" in dtext)
check("baseline 대비 변경만 기존 변경으로 집계(무변경 행 제외)", "CHANGED=1" in dtext)
check("dirty_total = 신규+기존변경", "TOTAL=2" in dtext)


# ===== 5) 저장 프로토콜 가드 =====
print("저장 프로토콜 — 부서 미선택 시 조 저장 차단")


def _save_units_no_dept():
    from views import master_org as mo
    mo._save_units(None, "")


at_g = AppTest.from_function(_save_units_no_dept, default_timeout=45).run()
check("부서 미선택 조 저장 차단 오류", any("부서를 먼저 선택" in str(e.value) for e in at_g.error))


# ===== 6) 보존된 순수 함수 스모크 =====
print("보존 순수 함수 스모크 — build_*_rows/_validate_*/구조검증")
check("build_group_rows 평면 행", set(master_org.build_group_rows(pd.DataFrame([
    {"group_code": "PET", "group_name": "PET계열", "sort_order": 1, "description": "", "is_active": True},
]))["_row_state"]) == {"existing"})
u_recs, u_errs = master_org._validate_units(pd.DataFrame([
    {"코드": "A", "명칭": "A조", "유형": "교대", "표시순서": "1", "사용": True, "_removed": ""},
    {"코드": "B", "명칭": "상근", "유형": "심야", "표시순서": "2", "사용": True, "_removed": ""},
]), "D1")
check("운영단위 교대→SHIFT + 허용 외 유형 차단",
      u_recs[0]["unit_type"] == "SHIFT" and any("유형" in e for e in u_errs))


# ===== 7) 상위 전환 중 폐기 게이트 = 하위 저장 차단 + continue/discard 무오귀속 =====
# Codex critical: 자식 draft 있고 상위 selectbox 를 바꿔 폐기 게이트가 열린 상태에서
# 저장을 눌러도 옛 행이 새 상위에 오귀속되면 안 된다. 게이트중 write 비활성(차단) +
# discard/취소 해소 시 옛 draft 가 새 상위로 새지 않음을 검증한다.
print("상위 전환 폐기 게이트 — 하위 write 차단 + discard/취소 무오귀속")


# 부서 draft 를 A 로 적재·편집한 뒤 상위 selectbox 를 B 로 전환한 상태를 재현한다.
# (AppTest.from_function 은 대상 함수만 실행하므로 헬퍼 참조 대신 각 probe 에 인라인한다.)
def _gate_block_probe():
    import streamlit as st
    from modules import db as adb
    from views import master_org as mo
    if not st.session_state.get("_gsetup"):
        st.session_state["_gsetup"] = True
        counts = adb.get_org_departments().groupby("group_code").size()
        gA = str(counts.index[0])
        groups = adb.get_org_groups(is_active=True)
        gB = next(str(g) for g in groups["group_code"].astype(str) if g != gA)
        mo._load_depts({"active": "전체", "search": "", "group": gA})
        rows = mo._OD.get_rows().copy()
        rows.loc[rows.index[0], "코드명"] = "임시편집ABC"
        mo._OD.set_rows(rows); mo._OD.set_dirty(True)
        mo._OD.commit_query({"active": "전체", "search": "", "group": gA})
        st.session_state["og_active"] = "전체"
        st.session_state["og_group"] = gB
        st.session_state["_gA"] = gA; st.session_state["_gB"] = gB
        st.session_state["_tgt"] = str(rows.iloc[0]["코드"])
    mo.render(adb.find_user_by_emp_no("1001"))


atb = AppTest.from_function(_gate_block_probe, default_timeout=45).run()
check("게이트 render 예외 없음", not atb.exception)
gbody = " ".join(str(m.value) for m in atb.markdown)
check("폐기 확인 게이트 표시", "저장되지 않은 변경" in gbody)
for k in ("org_dept__save", "org_dept__add", "org_dept__delete"):
    b = _save_button(atb, k)
    check(f"게이트중 {k} 비활성(오귀속 차단)", b is not None and getattr(b, "disabled", False))
rb = _save_button(atb, "org_dept__refresh")
check("게이트중에도 새로고침(조회)은 유지", rb is not None and not getattr(rb, "disabled", True))


def _gate_discard_probe():
    import streamlit as st
    from modules import db as adb
    from views import master_org as mo
    if not st.session_state.get("_gsetup"):
        st.session_state["_gsetup"] = True
        counts = adb.get_org_departments().groupby("group_code").size()
        gA = str(counts.index[0])
        groups = adb.get_org_groups(is_active=True)
        gB = next(str(g) for g in groups["group_code"].astype(str) if g != gA)
        mo._load_depts({"active": "전체", "search": "", "group": gA})
        rows = mo._OD.get_rows().copy()
        rows.loc[rows.index[0], "코드명"] = "임시편집ABC"
        mo._OD.set_rows(rows); mo._OD.set_dirty(True)
        mo._OD.commit_query({"active": "전체", "search": "", "group": gA})
        st.session_state["og_active"] = "전체"
        st.session_state["og_group"] = gB
        st.session_state["_gA"] = gA; st.session_state["_gB"] = gB
        st.session_state["_tgt"] = str(rows.iloc[0]["코드"])
    mo.render(adb.find_user_by_emp_no("1001"))


# discard(폐기하고 이동): 옛 draft 폐기 → 어느 상위에도 저장되지 않음
atx = AppTest.from_function(_gate_discard_probe, default_timeout=45).run()
for b in atx.button:
    if b.key == "org_dept__discard_ok":
        b.click(); break
atx.run()
check("discard 후 render 예외 없음", not atx.exception)
rows_x = atx.session_state["org_dept:rows"] if "org_dept:rows" in atx.session_state else None
lg_x = atx.session_state["org_dept:loaded_group"] if "org_dept:loaded_group" in atx.session_state else None
check("discard: 미저장 편집 폐기(재적재 행에 편집 없음 → 저장·오귀속 안 됨)",
      rows_x is not None and "임시편집ABC" not in set(rows_x["코드명"].astype(str)))
check("discard: 새 상위(B)로 재적재(옛 draft 가 새 상위에 저장·오귀속되지 않음)",
      lg_x is not None and str(lg_x) == str(atx.session_state["_gB"]))
check("discard: 폐기 게이트 해소(pending 제거)",
      master_org._OD.pending_query_key not in atx.session_state)


def _gate_cancel_probe():
    import streamlit as st
    from modules import db as adb
    from views import master_org as mo
    if not st.session_state.get("_gsetup"):
        st.session_state["_gsetup"] = True
        counts = adb.get_org_departments().groupby("group_code").size()
        gA = str(counts.index[0])
        groups = adb.get_org_groups(is_active=True)
        gB = next(str(g) for g in groups["group_code"].astype(str) if g != gA)
        mo._load_depts({"active": "전체", "search": "", "group": gA})
        rows = mo._OD.get_rows().copy()
        rows.loc[rows.index[0], "코드명"] = "임시편집ABC"
        mo._OD.set_rows(rows); mo._OD.set_dirty(True)
        mo._OD.commit_query({"active": "전체", "search": "", "group": gA})
        st.session_state["og_active"] = "전체"
        st.session_state["og_group"] = gB
        st.session_state["_gA"] = gA; st.session_state["_gB"] = gB
        st.session_state["_tgt"] = str(rows.iloc[0]["코드"])
    mo.render(adb.find_user_by_emp_no("1001"))


# 취소(continue editing): draft 보존 + 저장은 발생하지 않음(오귀속 없음)
atc = AppTest.from_function(_gate_cancel_probe, default_timeout=45).run()
for b in atc.button:
    if b.key == "org_dept__discard_cancel":
        b.click(); break
atc.run()
check("취소 후 render 예외 없음", not atc.exception)
rows_c = atc.session_state["org_dept:rows"] if "org_dept:rows" in atc.session_state else None
lg_c = atc.session_state["org_dept:loaded_group"] if "org_dept:loaded_group" in atc.session_state else None
check("취소: 미저장 draft 보존(편집 유지)",
      rows_c is not None and "임시편집ABC" in set(rows_c["코드명"].astype(str)))
check("취소: 원 상위(A) 유지 — 저장·오귀속 발생하지 않음",
      lg_c is not None and str(lg_c) == str(atc.session_state["_gA"]))


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
