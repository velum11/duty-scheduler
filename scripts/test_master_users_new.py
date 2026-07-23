"""사용자 관리(master_users) 재구현 화면 계약 테스트 (sample 모드, 실DB 미접속).

Phase4 Lane B — 공통 기반(views/master) 위 재구현이 기능 계약을 100% 보존하는지 검증한다.
- 표시↔코드 변환(부서명/조명/권한↔ADMIN/MANAGER/USER), 부서 종속 조 드롭다운 옵션,
  표시순서 파싱·검증, 완전 빈 행 skip, 셀 오류 마커 매핑
- 소프트 삭제(is_active=False + save_users, 물리삭제 없음), 시스템 admin 보호
- dirty(변경) 판별·신규 행 채움 기준, page-scoped 상태 격리, 저장 실패 시 초안 보존
- 렌더 스모크(AppTest) 예외 없음 + 로드 상태/모드 배지

브라우저(AgGrid JS paste/IME/드롭다운 동작)는 이 스크립트 범위 밖(수동/통합 검증).
실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_master_users_new.py
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

from modules import db  # noqa: E402
from views import master_users as mu  # noqa: E402
from views.master import state as mstate  # noqa: E402

_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "OK " if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def _live(rows):
    frame = pd.DataFrame(rows)
    if "_removed" not in frame:
        frame["_removed"] = ""
    return frame


# 공통 기준정보 픽스처
_DEPTS = db.get_departments()
_TEAMS = db.get_teams()
_DEPT_NAMES = {str(r["dept_code"]): str(r["dept_name"]) for _, r in _DEPTS.iterrows()}
_TEAM_RESOLVE, _TEAM_DISPLAY = mu._team_maps(_TEAMS)
_DEPT_RESOLVER = mu._dept_resolver(_DEPT_NAMES)
_DEPT_LABELS = mu._dept_labels(_DEPT_NAMES)
_D0 = next(iter(_DEPT_NAMES))
_D0_LABEL = _DEPT_LABELS[_D0]
_T0_ROWS = _TEAMS[_TEAMS["dept_code"].astype(str) == str(_D0)]
_T0_NAME = str(_T0_ROWS.iloc[0]["team_name"]) if not _T0_ROWS.empty else ""
_T0_CODE = str(_T0_ROWS.iloc[0]["team_code"]) if not _T0_ROWS.empty else ""


# ---------------------------------------------------------------------------
# 1) 표시↔코드 변환 + 검증 (records/errors)
# ---------------------------------------------------------------------------
def test_transform_ok():
    recs, errs = mu._validate(_live([
        {"_row_id": "n:1", "_row_state": "new", "_sel": False,
         "사번": "TESTU1", "성명": "홍길동", "부서": _D0_LABEL, "조": _T0_NAME,
         "직급": "사원", "권한": "관리자", "표시순서": "", "재직": True},
    ]), _DEPT_RESOLVER, _TEAM_RESOLVE)
    check("권한 관리자→ADMIN", bool(recs) and recs[0]["role"] == "ADMIN")
    check("부서 표시명→dept_code", recs[0]["dept_code"] == str(_D0))
    check("조명→team_code", recs[0]["team_code"] == _T0_CODE)
    check("정상 행 오류 없음", not errs)
    check("records 계약 키 완전", set(recs[0]) == {
        "emp_no", "name", "dept_code", "team_code", "position", "role", "is_active", "display_order"})


def test_role_variants():
    recs, _ = mu._validate(_live([
        {"_row_id": "n:1", "_row_state": "new", "_sel": False, "사번": "A", "성명": "가",
         "부서": _D0_LABEL, "조": "", "직급": "", "권한": "조장", "표시순서": "", "재직": True},
        {"_row_id": "n:2", "_row_state": "new", "_sel": False, "사번": "B", "성명": "나",
         "부서": _D0_LABEL, "조": "", "직급": "", "권한": "user", "표시순서": "", "재직": True},
    ]), _DEPT_RESOLVER, _TEAM_RESOLVE)
    check("권한 조장→MANAGER", recs[0]["role"] == "MANAGER")
    check("권한 코드 user→USER(대소문자 무관)", recs[1]["role"] == "USER")


def test_empty_team_and_skip():
    recs, errs = mu._validate(_live([
        {"_row_id": "n:1", "_row_state": "new", "_sel": False, "사번": "C", "성명": "다",
         "부서": _D0_LABEL, "조": "", "직급": "", "권한": "조원", "표시순서": "", "재직": True},
    ]), _DEPT_RESOLVER, _TEAM_RESOLVE)
    check("빈 조 허용", recs and recs[0]["team_code"] == "" and not errs)
    recs2, _ = mu._validate(_live([
        {"_row_id": "n:9", "_row_state": "new", "_sel": False, "사번": "", "성명": "",
         "부서": "", "조": "", "직급": "", "권한": "", "표시순서": "", "재직": True},
    ]), _DEPT_RESOLVER, _TEAM_RESOLVE)
    check("완전 빈 행 skip", len(recs2) == 0)


def test_team_dept_binding():
    other = _TEAMS[_TEAMS["dept_code"].astype(str) != str(_D0)]
    if other.empty:
        check("타 부서 조 차단(부서 1개라 스킵)", True)
        return
    other_name = str(other.iloc[0]["team_name"])
    if other_name in set(_T0_ROWS["team_name"].astype(str)):
        check("타 부서 조 차단(공통 조명이라 스킵)", True)
        return
    _r, errs, cells = mu._scan(_live([
        {"_row_id": "e:X", "_row_state": "existing", "_sel": False, "사번": "X", "성명": "엑스",
         "부서": _D0_LABEL, "조": other_name, "직급": "", "권한": "조원", "표시순서": "", "재직": True},
    ]), _DEPT_RESOLVER, _TEAM_RESOLVE)
    check("타 부서 조 차단('없는 조')", any("없는 조" in e for e in errs))
    check("조 오류가 셀 마커로 매핑", cells.get("e:X", {}).get("조") is not None)


def test_display_order_parse():
    recs, errs = mu._validate(_live([
        {"_row_id": "n:1", "_row_state": "new", "_sel": False, "사번": "T1", "성명": "가",
         "부서": _D0_LABEL, "조": "", "직급": "", "권한": "조원", "표시순서": "3", "재직": True},
        {"_row_id": "n:2", "_row_state": "new", "_sel": False, "사번": "T2", "성명": "나",
         "부서": _D0_LABEL, "조": "", "직급": "", "권한": "조원", "표시순서": "", "재직": True},
        {"_row_id": "n:3", "_row_state": "new", "_sel": False, "사번": "T3", "성명": "다",
         "부서": _D0_LABEL, "조": "", "직급": "", "권한": "조원", "표시순서": "abc", "재직": True},
        {"_row_id": "n:4", "_row_state": "new", "_sel": False, "사번": "T4", "성명": "라",
         "부서": _D0_LABEL, "조": "", "직급": "", "권한": "조원", "표시순서": "0", "재직": True},
    ]), _DEPT_RESOLVER, _TEAM_RESOLVE)
    check("표시순서 정수 저장", recs[0]["display_order"] == 3)
    check("표시순서 빈=NULL", recs[1]["display_order"] is None)
    check("표시순서 문자 차단", any("숫자" in e for e in errs))
    check("표시순서 1 미만 차단", any("1 이상" in e for e in errs))


def test_cell_error_mapping():
    _r, errs, cells = mu._scan(_live([
        {"_row_id": "e:9", "_row_state": "existing", "_sel": False, "사번": "9", "성명": "",
         "부서": "", "조": "", "직급": "", "권한": "", "표시순서": "", "재직": True},
    ]), _DEPT_RESOLVER, _TEAM_RESOLVE)
    m = cells.get("e:9", {})
    check("셀 오류: 성명/부서/권한 매핑", all(k in m for k in ("성명", "부서", "권한")))
    check("셀 오류와 flat errors 병행", bool(errs))


# ---------------------------------------------------------------------------
# 2) 부서 종속 조 옵션 / 그룹 힌트
# ---------------------------------------------------------------------------
def test_dependent_team_options():
    opts = mu._dept_team_options(_TEAMS, _DEPT_LABELS)
    check("모든 부서 라벨에 옵션 존재", set(opts) == set(_DEPT_LABELS.values()))
    check("옵션은 빈 항목으로 시작(선택 해제)", all(v and v[0] == "" for v in opts.values()))
    if _T0_NAME:
        check("선택 부서 옵션에 해당 부서 조 포함", _T0_NAME in opts[_D0_LABEL])
    # 부서 종속: d0 옵션에 다른 부서 전용 조명이 섞이지 않는다
    other = _TEAMS[_TEAMS["dept_code"].astype(str) != str(_D0)]
    exclusive = [
        str(r["team_name"]) for _, r in other.iterrows()
        if str(r["team_name"]) not in set(_T0_ROWS["team_name"].astype(str))
    ]
    if exclusive:
        check("타 부서 전용 조명은 옵션에서 제외", exclusive[0] not in opts[_D0_LABEL])
    else:
        check("타 부서 전용 조명 없음(스킵)", True)


def test_group_hint():
    group_of = db.dept_group_map()
    hints = mu._group_hints(group_of, _DEPT_NAMES, _DEPT_LABELS)
    # 그룹명이 부서명과 같으면 힌트 생략(중복 표기 방지)
    for label, grp in hints.items():
        check(f"그룹 힌트는 부서명과 다를 때만({label})", grp and grp != label.split(" (")[0])
        break
    else:
        check("그룹 힌트 없음(부서=그룹, 정상)", True)


# ---------------------------------------------------------------------------
# 3) 소프트 삭제 / 보호 계정
# ---------------------------------------------------------------------------
def test_soft_delete_contract():
    src = inspect.getsource(mu._execute_delete)
    check("소프트 삭제(is_active=False + save_users)", 'is_active"] = False' in src and "save_users" in src)
    check("물리 삭제(delete_user) 호출 없음", "delete_user" not in inspect.getsource(mu))


def test_protected_admin():
    check("admin 보호(대문자)", mu._is_protected("ADMIN"))
    check("admin 보호(소문자/공백)", mu._is_protected("  admin "))
    check("일반 사번 비보호", not mu._is_protected("1001"))


# ---------------------------------------------------------------------------
# 4) dirty(변경) 판별 · 신규 행 채움
# ---------------------------------------------------------------------------
def test_dirty_detection():
    rows = pd.DataFrame([
        {"_row_id": "e:1", "_row_state": "existing", "_sel": False, "사번": "1", "성명": "가",
         "부서": _D0_LABEL, "조": "", "직급": "사원", "권한": "조원", "표시순서": "1", "재직": True},
    ])
    baseline = mu._baseline_of(rows)
    check("baseline 기존행만", set(baseline) == {"e:1"})
    same, _ = mu._changed(rows, baseline)
    check("변경 없음 감지", same == set())
    edited = rows.copy()
    edited.loc[0, "권한"] = "조장"
    changed, dmap = mu._changed(edited, baseline)
    check("권한 변경 감지", changed == {"e:1"} and dmap["e:1"] == ["권한"])


def test_new_row_filled():
    empty = {"사번": "", "성명": "", "부서": "", "조": "", "직급": ""}
    filled = {"사번": "", "성명": "이름", "부서": "", "조": "", "직급": ""}
    check("빈 신규 행은 미채움(dirty 제외)", not mu._row_filled(empty))
    check("일부 입력 신규 행은 채움", mu._row_filled(filled))
    st_ = mstate.DraftState("t")
    nr = mu._new_row(st_)
    check("신규 행 기본 재직 True", nr["재직"] is True and nr["_row_state"] == "new")


# ---------------------------------------------------------------------------
# 5) page-scoped 상태 격리 (공용 ms_* 누수 없음)
# ---------------------------------------------------------------------------
def test_page_scope():
    s = mstate.DraftState(mu.PAGE_ID)
    check("page_id 확정", mu.PAGE_ID == "master_users")
    check("rows key page-scoped", s.rows_key == "master_users:rows")
    check("action key page-scoped", s.action_key("save") == "master_users:action:save")
    other = mstate.DraftState("master_work_types")
    check("화면 간 save flag 격리", s.action_key("save") != other.action_key("save"))


def test_source_guards():
    src = inspect.getsource(mu)
    render_src = inspect.getsource(mu.render)
    check("검정 저장 버튼 색 없음", "#1B1B1D" not in src and "#000000" not in src)
    check("구형 통계/카드/독립저장 없음", not any(
        t in src for t in ("summary_cards", "ui.card(", "editable_aggrid", "ui.action_bar")))
    check("render 소스에 '신규' 리터럴 없음(계약)", '"신규"' not in render_src)
    check("표시순서 003 차단 안내 문구 유지", "표시순서를 입력하면 저장이 차단됩니다" in src)
    check("소프트 삭제 라벨 '퇴직 처리' 사용", "퇴직 처리" in src)


# ---------------------------------------------------------------------------
# 6) 렌더 스모크 (AppTest) — 예외 없음 + 로드 상태
# ---------------------------------------------------------------------------
def _render_app():
    import os as _os
    _os.environ["DUTY_DATA_MODE"] = "sample"
    from modules import db as _db
    from views import master_users as _mu
    _mu.render(_db.find_user_by_emp_no("1001"))


def test_render_apptest():
    try:
        from streamlit.testing.v1 import AppTest
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] AppTest 미가용: {exc}")
        return
    at = AppTest.from_function(_render_app, default_timeout=60).run()
    check("render 예외 없음", not at.exception, str(at.exception))
    check("편집기 rows 로드됨", "master_users:rows" in at.session_state)
    dirty = at.session_state["master_users:dirty"] if "master_users:dirty" in at.session_state else False
    check("최초 진입 dirty=False", not dirty)


# ---------------------------------------------------------------------------
# 7) B1 — 셀 renderer 는 component class(DOM/textContent), HTML 문자열 반환 아님
# ---------------------------------------------------------------------------
def test_renderers_are_components():
    cases = {
        "_dept_renderer": mu._dept_renderer("{}").js_code,
        "_NAME_STATUS_RENDERER": mu._NAME_STATUS_RENDERER.js_code,
    }
    for name, code in cases.items():
        check(f"{name}: component class(init/getGui)",
              "document.createElement" in code and "getGui" in code and "init(" in code)
        check(f"{name}: DB 값은 textContent(HTML 문자열 조합 아님)", "textContent" in code)
        check(f"{name}: innerHTML 미사용", "innerHTML" not in code)
        check(f"{name}: <span 문자열 반환 없음",
              'return "<span' not in code and "return '<span" not in code)


# ---------------------------------------------------------------------------
# 7b) D2 — 편집 게이트(자연키·보호행 잠금) + 읽기전용/보호행 시각 + 배지 상태색 상속
# ---------------------------------------------------------------------------
def test_editable_gate():
    st_ = mstate.DraftState("gate_test")
    spec = mu._grid_spec(st_, "{}", "{}")
    cc = spec.col_config

    # 사번(자연키): 신규행만 편집 — 저장행 잠금(_row_state === 'new').
    sabun_ed = cc["사번"]["editable"].js_code
    check("사번 editable=신규행만", "_row_state === 'new'" in sabun_ed)

    # 데이터셀(성명/부서/조/직급/권한/표시순서/재직): 보호행만 잠금, 일반 저장행 편집 유지.
    for c in ("성명", "부서", "조", "직급", "권한", "표시순서", "재직"):
        ed = cc[c]["editable"].js_code
        check(f"{c} editable=보호행만 잠금", "_protected" in ed and "function(p)" in ed)

    # 읽기전용 시각(ms-cell-readonly): 보호행에만(사번 포함) — 저장행 과잉 틴트 회피(org 코드열과 동일).
    check("사번 읽기전용 규칙(보호행)", "ms-cell-readonly" in cc["사번"]["cellClassRules"]
          and "_protected" in cc["사번"]["cellClassRules"]["ms-cell-readonly"])
    check("성명 읽기전용 규칙(보호행)", "ms-cell-readonly" in cc["성명"]["cellClassRules"]
          and "_protected" in cc["성명"]["cellClassRules"]["ms-cell-readonly"])
    check("재직 읽기전용 규칙(보호행)", "ms-cell-readonly" in cc["재직"]["cellClassRules"])
    # 재직 bool 은 native(cellDataType) — 화면에서 JsCode cellRenderer 를 지정하지 않는다.
    check("재직 화면 JsCode 렌더러 미지정(native bool)", "cellRenderer" not in cc["재직"])

    # 셀 오류/변경 마커는 읽기전용과 병존한다(약화 금지).
    check("사번 오류·변경 마커 병존", "ms-cell-error" in cc["사번"]["cellClassRules"]
          and "ms-cell-dirty" in cc["사번"]["cellClassRules"])

    # 보호행 rowClassRule — 상태 cascade 위에 겹치되 배경을 덮지 않는다.
    rr = spec.row_class_rules or {}
    check("ms-row-protected rowClassRule 존재", "ms-row-protected" in rr and "_protected" in rr["ms-row-protected"])
    check("상태 cascade 보존(신규/퇴직/선택 규칙 유지)",
          all(k in rr for k in ("ms-row-new", "ms-row-inactive", "ms-row-selected")))


def test_name_badge_status_color():
    code = mu._NAME_STATUS_RENDERER.js_code
    check("성명 배지 ms-badge class 사용(행 상태색 상속)", "ms-badge" in code)
    check("성명 배지 흰배경 인라인 제거", "#FFFFFF" not in code and "#FFF'" not in code)
    check("성명 배지 색은 element.style.color 로만 지정(테두리 currentColor)", "style.color" in code)


# ---------------------------------------------------------------------------
# 8) B2 — _persist_users 가 부분성공 원장(save_*_report)을 그대로 반환
# ---------------------------------------------------------------------------
def test_persist_report_wiring():
    import modules.db as _db
    from modules.supabase_repository import BatchWriteResult
    orig = _db.save_users_report
    try:
        _db.save_users_report = lambda merged: BatchWriteResult(
            saved_keys=["A"], failed_keys=["B"], error="boom", retryable=True)
        pr = mu._persist_users("master_users", None, [{"emp_no": "A"}, {"emp_no": "B"}])
        check("report saved/failed key 전달", list(pr.succeeded_keys) == ["A"] and list(pr.failed_keys) == ["B"])
        check("partial/retryable 전달, 전체성공 단정 없음", pr.partial and pr.retryable and not pr.ok)
        _db.save_users_report = lambda merged: BatchWriteResult(saved_keys=["A", "B"])
        pr2 = mu._persist_users("master_users", None, [])
        check("전체 성공 ok", pr2.ok and list(pr2.succeeded_keys) == ["A", "B"])
        _db.save_users_report = lambda merged: BatchWriteResult(error="net", unknown=True, retryable=True)
        pr3 = mu._persist_users("master_users", None, [])
        check("결과 불명 전달(전체성공 추정 금지)", pr3.unknown and not pr3.ok)
    finally:
        _db.save_users_report = orig
    save_src = inspect.getsource(mu._save)
    check("_save 가 _persist_users(report) 사용", "_persist_users" in save_src)
    check("_save 가 부분성공 reconcile 수행", "_reconcile_partial" in save_src)


def _reconcile_app():
    import os as _os
    _os.environ["DUTY_DATA_MODE"] = "sample"
    import pandas as _pd
    import streamlit as _st
    from views import master_users as _mu
    from views.master import state as _state
    s = _state.DraftState("recon_test")
    rows = _pd.DataFrame([
        {"_row_id": "e:1", "_row_state": "existing", "_sel": False, "사번": "1", "성명": "가",
         "부서": "D", "조": "", "직급": "", "권한": "조원", "표시순서": "1", "재직": True},
        {"_row_id": "n:1", "_row_state": "new", "_sel": False, "사번": "NEW1", "성명": "신",
         "부서": "D", "조": "", "직급": "", "권한": "조원", "표시순서": "", "재직": True},
    ])
    _st.session_state[s.key("baseline")] = _mu._baseline_of(rows)
    _mu._reconcile_partial(s, rows, ["1", "NEW1"])  # 성공 자연키: 기존1 + 신규 NEW1
    out = s.get_rows()
    base = _st.session_state[s.key("baseline")]
    _st.session_state["recon_new_existing"] = bool(
        (out["_row_id"] == "e:NEW1").any()
        and (out.loc[out["_row_id"] == "e:NEW1", "_row_state"] == "existing").all())
    _st.session_state["recon_baseline_new"] = "e:NEW1" in base
    changed, _dmap = _mu._changed(out[out["_row_state"] == "existing"], base)
    _st.session_state["recon_no_dirty"] = (changed == set())


def test_reconcile_partial_apptest():
    try:
        from streamlit.testing.v1 import AppTest
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] AppTest 미가용: {exc}")
        return
    at = AppTest.from_function(_reconcile_app, default_timeout=60).run()
    check("reconcile 예외 없음", not at.exception, str(at.exception))
    check("성공 신규행 → 기존행 전환", at.session_state["recon_new_existing"])
    check("성공행 baseline 갱신", at.session_state["recon_baseline_new"])
    check("reconcile 후 성공행 dirty 아님", at.session_state["recon_no_dirty"])


# ---------------------------------------------------------------------------
# 9) B4 — 삭제 결과 판정(순수) + controller 오류 포착
# ---------------------------------------------------------------------------
def test_summarize_delete():
    from modules.supabase_repository import BatchWriteResult
    o, ft, msg = mu._summarize_delete(BatchWriteResult(saved_keys=["1", "2"]), ["1", "2"], ["1", "2"])
    check("삭제 전체 성공 done", o == "done" and ft == [] and "2명" in msg)
    o, ft, msg = mu._summarize_delete(
        BatchWriteResult(saved_keys=["1"], failed_keys=["2"], error="FK 위반"), ["1", "2"], ["1", "2"])
    check("삭제 부분 실패 partial(실패분만 재시도)", o == "partial" and ft == ["2"] and "FK 위반" in msg)
    o, ft, msg = mu._summarize_delete(
        BatchWriteResult(saved_keys=["1"], failed_keys=["2"], unknown=True, error="net"), ["1", "2"], ["1", "2"])
    check("삭제 결과 불명 unknown(성공 단정 금지)", o == "unknown" and ft == ["1", "2"])
    o, ft, msg = mu._summarize_delete(BatchWriteResult(saved_keys=[]), ["1"], [])
    check("삭제 대상 없음 안내", o == "done" and "처리할 사용자가 없습니다" in msg)


def test_delete_controller_guards():
    src = inspect.getsource(mu._execute_delete)
    check("삭제 실행이 DATA_SOURCE_ERRORS 포착", "DATA_SOURCE_ERRORS" in src)
    check("삭제 실행이 부분성공 원장(save_users_report) 사용", "save_users_report" in src)
    check("삭제 실행이 소프트(is_active=False) 유지", 'is_active"] = False' in src)
    check("삭제 실행이 물리삭제(delete_user) 없음", "delete_user" not in inspect.getsource(mu))


# ---------------------------------------------------------------------------
# 10) 통일 헤더 — readiness 배지(스키마 준비) + 모드 배지(데이터 연결) 분리 (§5/§25)
# ---------------------------------------------------------------------------
def test_readiness_state():
    from views.master import Readiness
    r = mu._readiness()  # sample 모드 → 항상 READY
    check("sample 모드 readiness READY", r.state is Readiness.READY and r.write_enabled)


def test_head_badges_compose():
    from views.master import ReadinessState
    ready_html = mu._head_badges(ReadinessState.ready())
    not_html = mu._head_badges(ReadinessState.not_ready("mig 003"))
    err_html = mu._head_badges(ReadinessState.probe_error("probe"))
    check("READY 는 스키마 배지 생략(모드 배지만)", "ms-ready" not in ready_html and "ms-mode" in ready_html)
    check("NOT_READY 는 스키마 배지 동반", "ms-ready" in not_html and "ms-mode" in not_html)
    check("PROBE_ERROR 도 스키마 배지 동반", "ms-ready" in err_html and "ms-mode" in err_html)


def test_readiness_gate_wired():
    src = inspect.getsource(mu.render)
    check("헤더가 readiness 배지 조합(_head_badges) 사용", "_head_badges(readiness)" in src)
    check("readiness 배너/재프로브 노출", "readiness.banner()" in src and "reset_org_schema_cache" in src)
    check("저장 게이트가 readiness.write_enabled 로 통일", "ready = readiness.write_enabled" in src)


def main():
    test_transform_ok()
    test_role_variants()
    test_empty_team_and_skip()
    test_team_dept_binding()
    test_display_order_parse()
    test_cell_error_mapping()
    test_dependent_team_options()
    test_group_hint()
    test_soft_delete_contract()
    test_protected_admin()
    test_dirty_detection()
    test_new_row_filled()
    test_page_scope()
    test_source_guards()
    test_render_apptest()
    test_renderers_are_components()
    test_editable_gate()
    test_name_badge_status_color()
    test_persist_report_wiring()
    test_reconcile_partial_apptest()
    test_summarize_delete()
    test_delete_controller_guards()
    test_readiness_state()
    test_head_badges_compose()
    test_readiness_gate_wired()

    print("-" * 60)
    if _failures:
        print(f"FAILED {len(_failures)}건: " + ", ".join(_failures))
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
