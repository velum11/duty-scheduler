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
# 연결 상태 pill 은 상단 52px 셸 헤더(modules/ui.py)가 소유(ADOPTION_SPEC 항목4·§0.4).
# 본문 크롬은 제목/설명만 — 본문에서 연결 pill 을 중복 렌더하지 않는다.
check("본문에 연결 pill 렌더 없음(상단 헤더 소유)",
      "샘플 데이터" not in body and "Supabase 연결" not in body)
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


# ===== 2b) 행 클릭 드릴다운 (상단 그룹/부서 selectbox 제거) =====
print("행 클릭 드릴다운 — 상단 selectbox 제거 + 행 클릭 배선 + 초기 미선택 하위 잠금")
sb_keys = {s.key for s in at.selectbox}
check("상단 그룹 선택 selectbox 제거", "og_group" not in sb_keys and "og_group_empty" not in sb_keys)
check("상단 부서 선택 selectbox 제거", "og_dept" not in sb_keys and "og_dept_empty" not in sb_keys)
check("사용 여부 필터 selectbox 는 유지", "og_active" in sb_keys)
check("그룹/부서 그리드에 행 클릭 드릴다운 핸들러(onCellClicked) 배선",
      "_DRILL_CLICK" in src and "onCellClicked" in src)
check("드릴다운 선택은 안정 코드키(session_state)로 보관",
      "og_group_sel" in src and "og_dept_sel" in src)
check("그룹 변경 시 하위(부서·조) 선택 초기화(og_dept_sel pop)", 'pop("og_dept_sel"' in src)
check("클릭된(_linked) 행의 안정 코드키를 읽는 _picked_code 존재",
      "_picked_code" in src and hasattr(master_org, "_picked_code"))
# 초기(아무 상위도 클릭 안 함) → 하위 시트 잠금(비우고 행추가 비활성)
check("초기 미선택 → 부서 시트 잠금(그룹 먼저 선택)", "그룹을 먼저 선택하세요" in body)
check("초기 미선택 → 조 시트 잠금(부서 먼저 선택)", "부서를 먼저 선택하세요" in body)
check("초기 미선택 → 부서·조 write 버튼 비활성", all(
    (_b is not None and getattr(_b, "disabled", False))
    for _b in (_save_button(at, k) for k in
               ("org_dept__save", "org_dept__add", "org_unit__save", "org_unit__add"))))


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
    check("NOT_READY 조회 전용 경고 배너", "조직 스키마" in nr_body and "조회만 가능" in nr_body)
    # readiness(스키마 준비) 신호는 배너(readiness.banner())로 표면화한다 — 연결 pill(상단
    # 셸 헤더)과 의미·위치가 분리된다. P1 에서 헤더 배지 슬롯은 제거됐고 배너가 정본 신호다.
    check("NOT_READY 스키마 신호는 배너로 표면화(연결 pill 과 분리)",
          "조직 스키마" in nr_body and "조회만 가능" in nr_body)
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


# ===== 3c-2) Wave B 통일 디자인 폴리시 마커 =====
# Codex UI 지적 반영: 시트별 액션바 반복·잠김 밀도 완화 / 선택 컨텍스트·계층 통합 /
# 저장코드 읽기전용 어포던스(공통 .ms-cell-readonly 소비) / bool 은 native 유지.
print("Wave B 폴리시 — 잠김 밀도 완화·계층 통합·읽기전용 코드·native bool")
check("잠긴 하위 시트 액션바 숨김(반복·밀도 완화)", ":has(.ms-locked)" in src and "display:none" in src)
check("잠긴 플레이스홀더 슬림화(.ms-locked 재정의)", ".ms-locked" in src and "min-height:118px" in src)
check("선택 컨텍스트·계층 통합 브레드크럼 강조(.ms-ctx)", ".ms-ctx" in src and "drilldown_context" in src)
check("장식 제거(ERP) — 단계 배지 원형 1·2·3·시트 커넥터 없음(계층은 .ms-ctx 브레드크럼으로 충분)",
      "content:'1'" not in src and "content:'2'" not in src and "content:'3'" not in src
      and "\\203A" not in src)
# §1-E: 카드(네이비 카드-탑 액센트) 제거 → 세로 헤어라인 3열 + 잠긴 시트 디엠퍼시스로
# 활성/잠김을 표현하고, 선택 경로는 DRILL 스트립(.ms-ctx 오렌지 틴트 칩)이 소유한다.
check("§1-E 활성/잠김 표시(세로 헤어라인 3열 + 잠긴 디엠퍼시스, 네이비 카드-탑 제거)",
      "opacity:.72" in src and "border-left:1px solid #cfc8bd" in src
      and "border-top:2px solid var(--ms-navy)" not in src)
check("§1-E DRILL 스트립 선택=오렌지 틴트(#b4451a)",
      "#b4451a" in src and ".ms-ctx b.pin" in src)
check("저장코드 읽기전용 어포던스(공통 .ms-cell-readonly 소비)",
      "ms-cell-readonly" in src and "_CODE_READONLY_RULES" in src)
check("bool(사용) native 유지 — JsCode bool 렌더러 미사용(3.14 배포 회귀 방지)",
      "BOOL_DISPLAY_RENDERER" not in src and "_BOOL_RENDERER" not in src)


# ===== 3c-3) Codex 디자인 리뷰 2차 — ERP 밀도·일관성 =====
# 액션바는 표 위(placeholder) 통일 / 필터결과 요약 상단 통일(사용자 관리와 동일) /
# ▸ 열림 중복칩 제거(행 강조로 충분) / 최소 열폭 축소로 1366·1280px 3열 적합.
print("Codex 2차 — 액션바 표 위·필터결과 요약·중복칩 제거·열폭 축소")
check("액션바 표 위(placeholder)로 3시트 통일(그리드 렌더 앞 bar_slot)",
      src.count("bar_slot = st.container()") == 3 and src.count("with bar_slot, st.container") == 3)
check("필터/스코프 결과 요약 상단 통일(_summary_chips + chip_html, 3시트)",
      "chip_html" in src and src.count("_summary_chips(rows, params)") == 3)
check("요약칩 분포 어휘를 필터 옵션(사용 중/사용 안 함)과 통일 — 옛 사용/미사용 칩 제거",
      "사용 중 {on}" in src and "사용 안 함 {off}" in src
      and "미사용 {off}" not in src and "사용 {on}" not in src)
check("요약칩 0건 규칙 통일 — 활성 필터칩은 결과 0건에도 유지, 분포칩만 결과 있을 때",
      'pd.DataFrame(columns=["사용"])' in src and "if not existing.empty:" in src
      and "if not left and not right:" in src)
check("▸ 열림 중복칩 제거 — 행 강조(ms-row-linked)로 충분",
      "_LINK_CHIP" not in src and "▸ 열림" not in src and "include_linked_rows=True" in src)
check("최소 열폭 축소(1366·1280px 3열 가로스크롤·잘림 방지) — 코드명 minWidth 완화",
      "minWidth\": 116" not in src and "minWidth\": 106" not in src)
check("액션바 keyed __bar 컨테이너로 3시트 통일(공통 여백·포커스 재사용)",
      src.count(".page_id}__bar\")") == 3)
check("표준 배너 순서 — 확인/폐기 배너를 액션바 뒤 banner_slot 로 이동(3시트)",
      src.count("banner_slot = st.container()") == 3 and src.count("with banner_slot:") == 3)


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
        import streamlit as st
        from modules import db as adb
        from views import master_org as mo
        if st.session_state.get("_pp_done"):
            # reconcile 후 st.rerun() 재진입: 시트 배너 슬롯이 하는 것처럼 세션 원장을
            # 소비·표시한다(성공 배너가 rerun 으로 유실되지 않음을 재현).
            mo._render_saved_ledger(mo._OD)
            return
        st.session_state["_pp_done"] = True
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
    check("부분성공 원장을 세션에 보관(reconcile 후 rerun 표시용) 후 소비",
          master_org._OD.key("save_ledger") not in at_pp.session_state)
    check("부분성공이 성공분(PET) baseline reconcile — baseline 존재",
          master_org._OD.key("baseline") in at_pp.session_state)
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
        st.session_state["og_group_sel"] = gB
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
        st.session_state["og_group_sel"] = gB
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
        st.session_state["og_group_sel"] = gB
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


# ===== 8) 부분성공 reconcile 계약(§22, M6) — 범위별 성공만/혼합/전실패 + unknown 미reconcile + 범위격리 =====
# 성공 자연키 행만 baseline·초안에 reconcile(신규→기존 전환·clean), 실패/미저장 행은
# draft·dirty 유지, unknown 은 일절 reconcile 하지 않는다. 한 범위 저장이 다른 범위
# 상태를 건드리지 않음(격리)을 함께 검증한다.
print("부분성공 reconcile 계약(M6) — 신규행 전환·baseline·dirty 유지·범위격리·unknown 미reconcile")


def _reconcile_probe():
    import pandas as pd
    import streamlit as st
    from views import master_org as mo

    class _Res:  # 최소 PersistResult 대체(succeeded/failed/unknown 만 참조).
        def __init__(self, succeeded=(), failed=(), unknown=False):
            self.succeeded_keys = list(succeeded)
            self.failed_keys = list(failed)
            self.unknown = unknown

    out: dict = {}

    def _clean(prefix):
        for k in [k for k in list(st.session_state.keys()) if k.startswith(prefix + ":")]:
            st.session_state.pop(k, None)

    def _grp_live(newg_state="new"):
        return pd.DataFrame([
            {"_row_id": "e:PET", "_row_state": "existing", "_sel": False, "코드": "PET",
             "코드명": "펫새이름", "순서": "1", "비고": "", "사용": True},        # 기존 변경
            {"_row_id": "n:1", "_row_state": newg_state, "_sel": True, "코드": "NEWG",
             "코드명": "신규그룹", "순서": "2", "비고": "", "사용": True},         # 신규
        ])[mo._GROUP_ROW_COLS]

    def _grp_baseline():
        orig = pd.DataFrame([
            {"_row_id": "e:PET", "_row_state": "existing", "_sel": False, "코드": "PET",
             "코드명": "펫옛이름", "순서": "1", "비고": "", "사용": True},  # baseline=옛 이름(변경 유발)
        ])[mo._GROUP_ROW_COLS]
        mo._set_baseline(mo._GRP, orig, mo._GROUP_COLS)

    # (a) 그룹 전체 성공: 신규 NEWG → 기존 e:NEWG 전환, 전부 clean.
    _clean("org_group"); _grp_baseline()
    mo._reconcile_org_partial(mo._GRP, _grp_live(), _Res(succeeded=["PET", "NEWG"]), mo._GROUP_COLS)
    rows = mo._GRP.get_rows()
    newg = rows[rows["코드"] == "NEWG"].iloc[0]
    out["a_newg_state"] = str(newg["_row_state"])
    out["a_newg_rid"] = str(newg["_row_id"])
    out["a_dirty"] = tuple(mo._dirty_counts(mo._GRP, rows, mo._GROUP_COLS))

    # (b) 그룹 혼합: PET 성공(clean)·NEWG 실패(draft 유지, 여전히 신규/dirty).
    _clean("org_group"); _grp_baseline()
    mo._reconcile_org_partial(mo._GRP, _grp_live(), _Res(succeeded=["PET"], failed=["NEWG"]), mo._GROUP_COLS)
    rows = mo._GRP.get_rows()
    newg = rows[rows["코드"] == "NEWG"].iloc[0]
    out["b_newg_state"] = str(newg["_row_state"])
    out["b_newg_rid"] = str(newg["_row_id"])
    out["b_dirty"] = tuple(mo._dirty_counts(mo._GRP, rows, mo._GROUP_COLS))

    # (c) 그룹 전실패: 아무 것도 reconcile 안 함(신규·변경 모두 dirty 유지).
    _clean("org_group"); _grp_baseline()
    mo._reconcile_org_partial(mo._GRP, _grp_live(), _Res(succeeded=[], failed=["PET", "NEWG"]), mo._GROUP_COLS)
    out["c_dirty"] = tuple(mo._dirty_counts(mo._GRP, _grp_live(), mo._GROUP_COLS))
    out["c_newg_state"] = str(_grp_live().iloc[1]["_row_state"])

    # (d) 조(복합키) 혼합: owner=PET. 신규 A → e:PET|A 전환(성공), 기존 e:PET|B 실패(유지).
    _clean("org_unit")
    ou_orig = pd.DataFrame([
        {"_row_id": "e:PET|B", "_row_state": "existing", "_sel": False, "코드": "B",
         "명칭": "B조옛", "유형": "교대", "표시순서": "2", "비고": "", "사용": True},
    ])[mo._UNIT_ROW_COLS]
    mo._set_baseline(mo._OU, ou_orig, mo._UNIT_COLS)
    ou_live = pd.DataFrame([
        {"_row_id": "e:PET|B", "_row_state": "existing", "_sel": False, "코드": "B",
         "명칭": "B조새", "유형": "교대", "표시순서": "2", "비고": "", "사용": True},   # 변경(실패)
        {"_row_id": "n:1", "_row_state": "new", "_sel": True, "코드": "A",
         "명칭": "A조", "유형": "교대", "표시순서": "1", "비고": "", "사용": True},      # 신규(성공)
    ])[mo._UNIT_ROW_COLS]
    mo._reconcile_org_partial(mo._OU, ou_live, _Res(succeeded=[("PET", "A")], failed=[("PET", "B")]),
                              mo._UNIT_COLS, owner="PET")
    urows = mo._OU.get_rows()
    arow = urows[urows["코드"] == "A"].iloc[0]
    brow = urows[urows["코드"] == "B"].iloc[0]
    out["d_a_rid"] = str(arow["_row_id"])
    out["d_a_state"] = str(arow["_row_state"])
    out["d_b_state"] = str(brow["_row_state"])
    out["d_dirty"] = tuple(mo._dirty_counts(mo._OU, urows, mo._UNIT_COLS))

    # (e) 범위 격리: _GRP reconcile 이 _OU rows/baseline 을 건드리지 않는다.
    _clean("org_group"); _clean("org_unit")
    mo._OU.set_rows(ou_live.copy())
    mo._set_baseline(mo._OU, ou_orig, mo._UNIT_COLS)
    ou_nonce_before = mo._OU.nonce()
    ou_rows_before = mo._OU.get_rows().to_dict("records")
    _grp_baseline()
    mo._reconcile_org_partial(mo._GRP, _grp_live(), _Res(succeeded=["PET", "NEWG"]), mo._GROUP_COLS)
    out["e_ou_rows_same"] = (mo._OU.get_rows().to_dict("records") == ou_rows_before)
    out["e_ou_nonce_same"] = (mo._OU.nonce() == ou_nonce_before)

    st.session_state["_recon_out"] = out


at_r = AppTest.from_function(_reconcile_probe, default_timeout=45).run()
check("reconcile probe 예외 없음", not at_r.exception)
_ro = at_r.session_state["_recon_out"] if "_recon_out" in at_r.session_state else {}
# (a) 전체 성공
check("(a) 신규 성공행 → 기존 전환(_row_state=existing)", _ro.get("a_newg_state") == "existing")
check("(a) 신규 성공행 rid = e:{group_code}", _ro.get("a_newg_rid") == "e:NEWG")
check("(a) 전체 성공 후 dirty 0(신규·변경 모두 clean)", _ro.get("a_dirty") == (0, 0))
# (b) 혼합
check("(b) 실패 신규행은 draft 유지(_row_state=new)", _ro.get("b_newg_state") == "new")
check("(b) 실패 신규행 rid 미전환(n:1 유지)", _ro.get("b_newg_rid") == "n:1")
check("(b) 성공(PET)만 clean·실패(NEWG)만 dirty → (신규1, 변경0)", _ro.get("b_dirty") == (1, 0))
# (c) 전실패
check("(c) 전실패는 아무 것도 전환 안 함(NEWG 여전히 new)", _ro.get("c_newg_state") == "new")
check("(c) 전실패 후 dirty 유지 (신규1, 변경1)", _ro.get("c_dirty") == (1, 1))
# (d) 복합키(조)
check("(d) 복합키 신규 성공행 → e:{dept}|{team} 전환", _ro.get("d_a_rid") == "e:PET|A")
check("(d) 복합키 신규 성공행 existing 전환", _ro.get("d_a_state") == "existing")
check("(d) 복합키 실패행(B)은 draft 유지", _ro.get("d_b_state") == "existing" and _ro.get("d_dirty") == (0, 1))
# (e) 범위 격리
check("(e) _GRP reconcile 이 _OU rows 를 건드리지 않음", _ro.get("e_ou_rows_same") is True)
check("(e) _GRP reconcile 이 _OU nonce 를 건드리지 않음", _ro.get("e_ou_nonce_same") is True)

# (f) unknown 은 controller 가 reconcile 하지 않고 원장만 표기(소스 계약).
check("(f) 3시트 save 가 partial 에서만 reconcile 호출(3건)", src.count("_reconcile_org_partial(_") == 3)
check("(f) 3시트 save 가 unknown 분기에서 ledger_banner 만(재조회 필요)",
      src.count('if outcome.status == "unknown":') == 3)
check("(f) 성공분만 save_ledger 세션 보관 후 rerun(3건)", src.count('.key("save_ledger")] = outcome.result') == 3)


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
