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
    # 2026-08-07: 조 편집 칼럼 제거 — _scan 은 team_code 를 항상 빈 값으로 두고,
    # 기존 배정의 보존은 _save 가 저장 직전 권위 스토어에서 백필한다(그리드가
    # spec.order+META 외 컬럼을 잘라내므로 행 데이터 왕복로는 보존 불가).
    recs, errs = mu._validate(_live([
        {"_row_id": "n:1", "_row_state": "new", "_sel": False,
         "사번": "TESTU1", "성명": "홍길동", "부서": _D0_LABEL,
         "직급": "사원", "권한": "관리자", "입사일": "2024-01-02", "퇴사일": "",
         "표시순서": "", "재직": True},
    ]), _DEPT_RESOLVER, _TEAM_RESOLVE)
    check("권한 관리자→ADMIN", bool(recs) and recs[0]["role"] == "ADMIN")
    check("부서 표시명→dept_code", recs[0]["dept_code"] == str(_D0))
    check("_scan 은 team_code 를 만들지 않음(빈 값)", recs[0]["team_code"] == "")
    check("입사일 정규화 저장·빈 퇴사일 NULL",
          recs[0]["hire_date"] == "2024-01-02" and recs[0]["resign_date"] is None)
    check("정상 행 오류 없음", not errs)
    check("records 계약 키 완전", set(recs[0]) == {
        "emp_no", "name", "dept_code", "team_code", "position", "role", "is_active",
        "display_order", "hire_date", "resign_date"})
    # 보존 계약: _save 가 저장 직전 스토어 백필로 team_code 를 되살린다(소스 계약).
    save_src = inspect.getsource(mu._save)
    check("_save 가 기존 team_code 스토어 백필 수행",
          "stored_team" in save_src and 'rec["team_code"] = stored_team.get' in save_src)


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


def test_tenure_validation():
    """입사일/퇴사일(009) 검증 — 형식 오류·순서 위반이 셀 마커로 매핑된다."""
    _r, errs, cells = mu._scan(_live([
        {"_row_id": "e:X", "_row_state": "existing", "_sel": False, "사번": "X", "성명": "엑스",
         "부서": _D0_LABEL, "직급": "", "권한": "조원",
         "입사일": "엉터리", "퇴사일": "", "표시순서": "", "재직": True},
        {"_row_id": "e:Y", "_row_state": "existing", "_sel": False, "사번": "Y", "성명": "와이",
         "부서": _D0_LABEL, "직급": "", "권한": "조원",
         "입사일": "2024-05-01", "퇴사일": "2024-01-01", "표시순서": "", "재직": True},
    ]), _DEPT_RESOLVER, _TEAM_RESOLVE)
    check("입사일 형식 오류 차단", any("입사일 형식" in e for e in errs))
    check("입사일 오류가 셀 마커로 매핑", cells.get("e:X", {}).get("입사일") is not None)
    check("퇴사일<입사일 차단", any("앞설 수 없습니다" in e for e in errs))
    check("퇴사일 오류가 셀 마커로 매핑", cells.get("e:Y", {}).get("퇴사일") is not None)
    recs, errs2, _ = mu._scan(_live([
        {"_row_id": "e:Z", "_row_state": "existing", "_sel": False, "사번": "Z", "성명": "지",
         "부서": _D0_LABEL, "직급": "", "권한": "조원",
         "입사일": "2024.01.02", "퇴사일": "20240301", "표시순서": "", "재직": True},
    ]), _DEPT_RESOLVER, _TEAM_RESOLVE)
    check("구분자 변형(점·무구분)도 ISO 로 정규화",
          not errs2 and recs[0]["hire_date"] == "2024-01-02" and recs[0]["resign_date"] == "2024-03-01")


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


def test_refresh_invalidates_reads():
    """새로고침은 '다시 읽는다' — 읽기 캐시를 이 화면 범위만 좁게 비운 뒤 재적재한다."""
    src = inspect.getsource(mu)
    check("새로고침이 기준정보 캐시를 실제로 비운다",
          'db.refresh_reference_data("users")' in src)
    check("전역 캐시 초기화(st.cache_data.clear)는 쓰지 않는다",
          "st.cache_data.clear()" not in src)


def test_source_guards():
    src = inspect.getsource(mu)
    render_src = inspect.getsource(mu.render)
    check("검정 저장 버튼 색 없음", "#1B1B1D" not in src and "#000000" not in src)
    check("구형 통계/카드/독립저장 없음", not any(
        t in src for t in ("summary_cards", "ui.card(", "editable_aggrid", "ui.action_bar")))
    check("render 소스에 '신규' 리터럴 없음(계약)", '"신규"' not in render_src)
    check("표시순서 004 차단 안내 문구 유지", "표시순서를 입력하면 저장이 차단됩니다" in src)
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

    # 데이터셀(성명/부서/직급/권한/입사일/퇴사일/표시순서/재직): 보호행만 잠금, 일반 저장행 편집 유지.
    for c in ("성명", "부서", "직급", "권한", "입사일", "퇴사일", "표시순서", "재직"):
        ed = cc[c]["editable"].js_code
        check(f"{c} editable=보호행만 잠금", "_protected" in ed and "function(p)" in ed)

    # 읽기전용 시각(ms-cell-readonly): 보호행에만(사번 포함) — 저장행 과잉 틴트 회피(org 코드열과 동일).
    check("사번 읽기전용 규칙(보호행)", "ms-cell-readonly" in cc["사번"]["cellClassRules"]
          and "_protected" in cc["사번"]["cellClassRules"]["ms-cell-readonly"])
    check("성명 읽기전용 규칙(보호행)", "ms-cell-readonly" in cc["성명"]["cellClassRules"]
          and "_protected" in cc["성명"]["cellClassRules"]["ms-cell-readonly"])
    check("재직 읽기전용 규칙(보호행)", "ms-cell-readonly" in cc["재직"]["cellClassRules"])
    # 2026-08-19 폐기: "재직/권한 §1-E pill 렌더러 지정".
    # 표 안 장식성 색 채움 폐지(사용자 판단) — 권한 3색 pill·재직 녹색 pill 은 값을 읽어야
    # 하는 열에서 색면이 먼저 눈을 끌었고, 12.5px 라 DESIGN §1.2 네 단계 밖이기도 했다.
    # 상태 이중부호화는 성명 열 배지(_NAME_STATUS_RENDERER)와 행 상태 배경이 유지한다.
    # 편집 계약(재직=bool 체크박스 / 권한=select)은 그대로여야 한다.
    check("재직은 공용 native 체크박스(pill 렌더러 없음)", "cellRenderer" not in cc["재직"])
    check("권한은 평문 + select 편집 유지(pill 렌더러 없음)",
          "cellRenderer" not in cc["권한"] and cc["권한"].get("cellEditor") == "agSelectCellEditor"
          and "ms-cell-select" in cc["권한"]["cellClass"])
    check("pill 렌더러 정의 제거", not hasattr(mu, "_ROLE_PILL_RENDERER")
          and not hasattr(mu, "_ACTIVE_PILL_RENDERER"))
    # 열 폭은 12px 기준 역산 비율이고 남는 폭은 fitGridWidth 가 비례 분배한다 — flex 잔존 0.
    check("사용자 시트 flex 잔존 0", all(float(c.get("flex", 0)) == 0 for c in cc.values()))
    check("고정 서식·체크박스 열만 maxWidth", all("maxWidth" in cc[c] for c in
          ("입사일", "퇴사일", "표시순서", "재직"))
          and not any("maxWidth" in cc[c] for c in ("사번", "성명", "부서", "직급", "권한")))

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
        {"_row_id": "e:1", "_row_state": "existing", "_sel": False, "_team_code": "", "사번": "1",
         "성명": "가", "부서": "D", "직급": "", "권한": "조원", "이메일": "a@x.com",
         "입사일": "", "퇴사일": "", "표시순서": "1", "재직": True},
        {"_row_id": "n:1", "_row_state": "new", "_sel": False, "_team_code": "", "사번": "NEW1",
         "성명": "신", "부서": "D", "직급": "", "권한": "조원", "이메일": "",
         "입사일": "", "퇴사일": "", "표시순서": "", "재직": True},
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
    not_html = mu._head_badges(ReadinessState.not_ready("조직 스키마 미준비"))
    err_html = mu._head_badges(ReadinessState.probe_error("probe"))
    check("READY 는 스키마 배지 생략(모드 배지만)", "ms-ready" not in ready_html and "ms-mode" in ready_html)
    check("NOT_READY 는 스키마 배지 동반", "ms-ready" in not_html and "ms-mode" in not_html)
    check("PROBE_ERROR 도 스키마 배지 동반", "ms-ready" in err_html and "ms-mode" in err_html)


def test_readiness_gate_wired():
    src = inspect.getsource(mu.render)
    # §1-E: 아이콘 밴드 제거로 헤더 배지 조합(_head_badges)은 더 이상 헤더에 붙지 않는다 —
    # readiness 는 배너로, 데이터 연결 pill 은 상단 52px 셸 헤더가 소유(P1). 액션은 건수 행으로.
    check("readiness 배너로 표면화(헤더 배지 조합 제거)",
          "readiness.banner()" in src and "_head_badges(readiness)" not in src)
    check("액션 활성/사유는 공통 규칙(page_action_specs) 재사용",
          "page_action_specs(" in src and "toolbar=\"icons\"" not in src)
    check("readiness 재프로브 노출", "reset_org_schema_cache" in src)
    check("저장 게이트가 readiness.write_enabled 로 통일", "ready = readiness.write_enabled" in src)


# ---------------------------------------------------------------------------
# 10b) 액션 진입점 단일화(2026-08-14) — 실행 버튼은 상단 52px 헤더 아이콘 하나뿐
# ---------------------------------------------------------------------------
def test_single_action_entry_point():
    """화면 안 액션 버튼 제거 + 헤더 발행/동기화. 활성 규칙·플래그 계약은 불변."""
    render_src = inspect.getsource(mu.render)
    src = inspect.getsource(mu)

    # (a) 화면 안 실행 버튼(행 추가/삭제/저장/새로고침) 진입점이 없다.
    check("인페이지 액션바 미사용(master_action_bar)", "master_action_bar(" not in src)
    check("인페이지 액션 버튼 키 없음({page}__{role})",
          f'key=f"{{PAGE_ID}}__{{role}}"' not in src and "__save\"" not in render_src)
    check("인페이지 on_click 액션 요청 없음(action_requester)",
          "action_requester(" not in src)
    for label in ('"행 추가"', '"새로고침"'):
        check(f"render 소스에 인페이지 버튼 라벨 없음 [{label}]", label not in render_src)

    # (b) 헤더 아이콘이 유일 진입점 — 활성/사유는 공통 규칙 그대로 발행한다.
    check("헤더 아이콘에 공통 활성 규칙 발행",
          "header_actions_from_specs(PAGE_ID, specs)" in render_src)
    check("헤더 발행값 동기화 훅 호출", "_sync_header(specs)" in render_src)

    # (c) 실행 경로·확인 게이트는 종전 그대로(플래그 소비 → 저장/삭제/추가/재적재).
    check("액션 플래그 소비 유지(take_actions)", "take_actions(state)" in render_src)
    for role in ("SAVE", "DELETE", "ADD"):
        check(f"액션 처리 분기 유지 [{role}]", f"acts[{role}]" in render_src)


def test_header_sync_converges():
    """_sync_header: 발행값이 같으면 재실행 없음, 폭주 방지 상한(2회)에서 멈춘다."""
    try:
        from streamlit.testing.v1 import AppTest
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] AppTest 미가용: {exc}")
        return
    at = AppTest.from_function(_sync_app, default_timeout=60).run()
    check("_sync_header 예외 없음", not at.exception, str(at.exception))
    check("동일 발행값이면 재실행 없음(가드 리셋)", at.session_state["sync_same_ok"])
    check("연속 보정 상한에서 멈춤(무한 rerun 방지)", at.session_state["sync_capped_ok"])


def _sync_app():
    import os as _os
    _os.environ["DUTY_DATA_MODE"] = "sample"
    import streamlit as _st
    from views import master_users as _mu
    specs = [
        {"role": "add", "disabled": False, "help": None},
        {"role": "delete", "disabled": True, "help": "삭제할 행을 먼저 선택"},
        {"role": "save", "disabled": True, "help": "저장할 변경이 없습니다"},
        {"role": "refresh", "disabled": False, "help": None},
    ]
    payload = {s["role"]: (bool(s["disabled"]), s["help"]) for s in specs}
    # (a) 이미 같은 값이 발행돼 있으면 rerun 하지 않는다(가드도 0 으로 리셋).
    _st.session_state[f"{_mu.PAGE_ID}:hdr_mirror"] = payload
    _st.session_state[f"{_mu.PAGE_ID}:hdr_sync_n"] = 1
    _mu._sync_header(specs)
    _st.session_state["sync_same_ok"] = (
        _st.session_state[f"{_mu.PAGE_ID}:hdr_sync_n"] == 0)
    # (b) 값이 달라도 연속 보정 상한(2)에 도달했으면 rerun 하지 않고 값만 갱신한다.
    _st.session_state[f"{_mu.PAGE_ID}:hdr_mirror"] = {"add": (True, None)}
    _st.session_state[f"{_mu.PAGE_ID}:hdr_sync_n"] = 2
    _mu._sync_header(specs)
    _st.session_state["sync_capped_ok"] = (
        _st.session_state[f"{_mu.PAGE_ID}:hdr_mirror"] == payload)


def test_count_row_status():
    """건수 행: 미저장/선택 상태 텍스트와 진입점 안내가 남아 있다(액션 이전 후에도)."""
    html = mu._count_row_html(9, 8, 1, 0, 0, 0)
    check("건수·재직/퇴직 분포 유지", ">9<" in html and "재직 8 · 퇴직 1" in html)
    check("미저장 0 이면 '변경 없음' 표기", "미저장 변경 없음" in html)
    check("진입점 안내(상단 아이콘) 표기", "상단 아이콘" in html)
    dirty = mu._count_row_html(9, 8, 1, 2, 3, 1)
    check("미저장 건수·분해 표기", "미저장 5건" in dirty and "신규 2" in dirty and "변경 3" in dirty)
    check("선택 건수 표기", "선택 1건" in dirty)


# ---------------------------------------------------------------------------
# 11) 이메일 열(010 user_emails) — scope=ALL 대표 1건 슬롯, 다중 이메일 계약 보존
# ---------------------------------------------------------------------------
def test_email_column_contract():
    """이메일은 **보이는 열**이어야 저장까지 값이 살아 온다(숨김 컬럼 절단 함정)."""
    check("EMAIL_COL 상수 정의", mu.EMAIL_COL == "이메일")
    check("편집 열 계약에 포함(_USER_COLS)", mu.EMAIL_COL in mu._USER_COLS)
    check("행 계약에 포함(_ROW_COLS)", mu.EMAIL_COL in mu._ROW_COLS)
    check("그리드 컬럼 타입 text", mu._GRID_COLUMNS.get(mu.EMAIL_COL) == "text")
    st_ = mstate.DraftState("email_spec_test")
    spec = mu._grid_spec(st_, "{}")
    check("spec.order 에 포함(왕복 보장)", mu.EMAIL_COL in spec.order)
    cc = spec.col_config[mu.EMAIL_COL]
    check("보호행만 편집 잠금(일반 저장행 편집 유지)", "_protected" in cc["editable"].js_code)
    check("셀 오류·변경 마커 병존",
          "ms-cell-error" in cc["cellClassRules"] and "ms-cell-dirty" in cc["cellClassRules"])
    code = cc["cellRenderer"].js_code
    check("이메일 렌더러는 component class(textContent)",
          "document.createElement" in code and "textContent" in code and "innerHTML" not in code)
    # 조회 실패/미준비 → 조회 전용(모르는 값을 빈 값으로 덮어쓰지 않는다)
    ro = mu._grid_spec(st_, "{}", email_editable=False).col_config[mu.EMAIL_COL]
    check("스키마 미준비면 editable=False", ro["editable"] is False)
    check("스키마 미준비면 읽기전용 시각", ro["cellClassRules"].get("ms-cell-readonly") == "true")


def test_email_validation():
    """형식 오류는 저장 전 화면에서 차단하고, records(USER_COLUMNS)에는 섞이지 않는다."""
    recs, errs, cells = mu._scan(_live([
        {"_row_id": "e:E1", "_row_state": "existing", "_sel": False, "사번": "E1", "성명": "가",
         "부서": _D0_LABEL, "직급": "", "권한": "조원", "이메일": "notanemail",
         "입사일": "", "퇴사일": "", "표시순서": "", "재직": True},
        {"_row_id": "e:E2", "_row_state": "existing", "_sel": False, "사번": "E2", "성명": "나",
         "부서": _D0_LABEL, "직급": "", "권한": "조원", "이메일": " Ok.User@Corp.CO.KR ",
         "입사일": "", "퇴사일": "", "표시순서": "", "재직": True},
    ]), _DEPT_RESOLVER, _TEAM_RESOLVE)
    check("이메일 형식 오류 차단", any("이메일 형식" in e for e in errs))
    check("이메일 오류가 셀 마커로 매핑", cells.get("e:E1", {}).get("이메일") is not None)
    check("정상 이메일은 오류 아님", cells.get("e:E2", {}).get("이메일") is None)
    check("records 는 USER_COLUMNS 계약 유지(email 없음)",
          all("email" not in r for r in recs))
    check("이메일 형식 판정은 파사드와 동일 규칙",
          mu._valid_email("a@b.co") and not mu._valid_email("a@b") and not mu._valid_email(""))


def test_email_primary_and_merge():
    """대표 주소 선정은 모드 무관 결정적이고, 병합은 나머지 주소를 보존한다."""
    from modules import config as _cfg
    cap = next(iter(_cfg.CAPABILITIES))
    rows = [
        {"email": "z@x.com", "scope": _cfg.EMAIL_SCOPE_ALL},
        {"email": "a@x.com", "scope": _cfg.EMAIL_SCOPE_ALL},
        {"email": "duty@x.com", "scope": cap},
    ]
    check("대표 = ALL 주소 정렬 최소값(삽입순 무관)", mu._primary_email(rows) == "a@x.com")
    check("대표 없음(ALL 미등록)", mu._primary_email([{"email": "d@x.com", "scope": cap}]) == "")
    check("추가 주소 건수(대표 제외)", mu._extra_email_count(rows) == 2)

    merged = mu._merge_email_rows(rows, "NEW@x.com")
    check("대표만 교체(소문자 정규화)",
          {"email": "new@x.com", "scope": _cfg.EMAIL_SCOPE_ALL} in merged
          and all(r["email"] != "a@x.com" for r in merged))
    check("다른 ALL 주소 보존", {"email": "z@x.com", "scope": _cfg.EMAIL_SCOPE_ALL} in merged)
    check("담당별(scope=capability) 주소 보존", {"email": "duty@x.com", "scope": cap} in merged)

    cleared = mu._merge_email_rows(rows, "")
    check("빈 값 = 대표 1건만 삭제", all(r["email"] != "a@x.com" for r in cleared)
          and len(cleared) == 2)
    added = mu._merge_email_rows([{"email": "duty@x.com", "scope": cap}], "me@x.com")
    check("대표가 없던 사용자에 신규 등록",
          {"email": "me@x.com", "scope": _cfg.EMAIL_SCOPE_ALL} in added and len(added) == 2)


def _email_save_app():
    """sample 세션 스토어로 저장 경로 왕복 — 변경 행만 쓰고 나머지 주소는 보존."""
    import os as _os
    _os.environ["DUTY_DATA_MODE"] = "sample"
    import pandas as _pd
    import streamlit as _st
    from modules import config as _cfg
    from modules import db as _db
    from views import master_users as _mu
    from views.master import state as _state

    cap = next(iter(_cfg.CAPABILITIES))
    # 대표(그리드 슬롯) = ALL 주소 정렬 최소값 → aa@x.com. zz@x.com 은 추가 ALL 주소.
    _db.set_user_emails("1001", [
        {"email": "aa@x.com", "scope": _cfg.EMAIL_SCOPE_ALL},
        {"email": "zz@x.com", "scope": _cfg.EMAIL_SCOPE_ALL},
        {"email": "duty@x.com", "scope": cap},
    ])
    _db.set_user_emails("1002", [{"email": "untouched@x.com", "scope": _cfg.EMAIL_SCOPE_ALL}])

    s = _state.DraftState("email_save_test")
    # 로드 시점 프레임(대표 주소가 실려 온 상태) → baseline. 그 뒤 1001 만 편집한다.
    loaded = _pd.DataFrame([
        {"_row_id": "e:1001", "_row_state": "existing", "_sel": False, "사번": "1001",
         "성명": "가", "부서": "D", "직급": "", "권한": "조원", "이메일": "aa@x.com",
         "입사일": "", "퇴사일": "", "표시순서": "", "재직": True},
        {"_row_id": "e:1002", "_row_state": "existing", "_sel": False, "사번": "1002",
         "성명": "나", "부서": "D", "직급": "", "권한": "조원", "이메일": "untouched@x.com",
         "입사일": "", "퇴사일": "", "표시순서": "", "재직": True},
    ])
    _st.session_state[s.key("baseline")] = _mu._baseline_of(loaded)
    live = _pd.concat([loaded, _pd.DataFrame([
        {"_row_id": "n:1", "_row_state": "new", "_sel": False, "사번": "NEWU",
         "성명": "신", "부서": "D", "직급": "", "권한": "조원", "이메일": "fresh@x.com",
         "입사일": "", "퇴사일": "", "표시순서": "", "재직": True},
    ])], ignore_index=True)
    live.loc[live["사번"] == "1001", "이메일"] = "new@x.com"  # 이 행만 편집
    failures = _mu._persist_emails(s, live, None, actor="1001")
    _st.session_state["mail_failures"] = list(failures)
    _st.session_state["mail_1001"] = _db.get_user_emails("1001")
    _st.session_state["mail_1002"] = _db.get_user_emails("1002")
    _st.session_state["mail_new"] = _db.get_user_emails("NEWU")

    # 조회 실패/미준비 상태에서는 아무것도 쓰지 않는다(빈 값 덮어쓰기 금지).
    _st.session_state[s.key("email_error")] = "조회 실패"
    blocked = live.copy()
    blocked.loc[blocked["사번"] == "1002", "이메일"] = ""
    _mu._persist_emails(s, blocked, None, actor="1001")
    _st.session_state["mail_blocked"] = _db.get_user_emails("1002")


def test_email_save_roundtrip():
    try:
        from streamlit.testing.v1 import AppTest
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] AppTest 미가용: {exc}")
        return
    at = AppTest.from_function(_email_save_app, default_timeout=60).run()
    check("이메일 저장 예외 없음", not at.exception, str(at.exception))
    if at.exception:
        return
    check("저장 실패 없음", at.session_state["mail_failures"] == [])
    rows = at.session_state["mail_1001"]
    got = {(r["email"], r["scope"]) for r in rows}
    from modules import config as _cfg
    cap = next(iter(_cfg.CAPABILITIES))
    check("대표 주소 교체", ("new@x.com", _cfg.EMAIL_SCOPE_ALL) in got
          and ("aa@x.com", _cfg.EMAIL_SCOPE_ALL) not in got)
    check("추가 ALL 주소 보존", ("zz@x.com", _cfg.EMAIL_SCOPE_ALL) in got)
    check("담당별 주소 보존", ("duty@x.com", cap) in got)
    check("변경 없는 사용자는 그대로(불필요한 재작성 없음)",
          [dict(r) for r in at.session_state["mail_1002"]]
          == [{"email": "untouched@x.com", "scope": _cfg.EMAIL_SCOPE_ALL}])
    check("신규 사용자 이메일 등록(사용자 저장 뒤 순서)",
          [r["email"] for r in at.session_state["mail_new"]] == ["fresh@x.com"])
    check("조회 실패 상태면 저장 skip(빈 값 덮어쓰기 금지)",
          [r["email"] for r in at.session_state["mail_blocked"]] == ["untouched@x.com"])


def test_admin_editor_targets():
    """ADMIN 편집기 대상 목록은 **그리드 표시 컬럼(사번/성명)** 으로 만든다.

    저장소 컬럼명(emp_no/name)으로 읽으면 항상 빈 목록이 돼 비밀번호 초기화·담당
    권한/이메일 편집기가 캡션만 남고 조용히 사라진다(2026-08-14 실화면 검증 발견).
    """
    frame = pd.DataFrame([
        {"_row_state": "existing", "사번": "1001", "성명": "가"},
        {"_row_state": "existing", "사번": " ", "성명": "빈사번"},
        {"_row_state": "existing", "사번": "1002", "성명": ""},
    ])
    opts = mu._target_options(frame)
    check("표시 컬럼으로 대상 목록 구성", opts and opts[0] == "1001 · 가")
    check("사번 없는 행 제외", all(not o.startswith(" ") for o in opts) and len(opts) == 2)
    check("성명 없어도 사번만으로 선택 가능", "1002" in opts)
    check("빈 프레임은 빈 목록", mu._target_options(pd.DataFrame()) == [])
    src = inspect.getsource(mu)
    check("편집기 두 곳 모두 공통 헬퍼 사용", src.count("_target_options(existing)") == 2)
    check("대상 사번 파싱 규칙 유지(사번 · 성명)", 'split(" · ", 1)[0]' in src)


def _email_map_bulk_app():
    """목록 1회 조회(bulk)가 단건 반복과 같은 값을 내는지 — sample 세션 스토어로 왕복."""
    import streamlit as _st
    from modules import config as _cfg
    from modules import db as _db
    from views import master_users as _mu

    cap = next(iter(_cfg.CAPABILITIES))
    _db.set_user_emails("1001", [
        {"email": "aa@x.com", "scope": _cfg.EMAIL_SCOPE_ALL},
        {"email": "zz@x.com", "scope": _cfg.EMAIL_SCOPE_ALL},
        {"email": "duty@x.com", "scope": cap},
    ])
    _db.set_user_emails("1002", [])
    emps = ["1001", "1002"]

    bulk = _db.get_user_emails_bulk(emps)
    _st.session_state["bulk_eq"] = bulk == {e: _db.get_user_emails(e) for e in emps}
    primary, extra, err = _mu._email_map(emps)
    _st.session_state["map_primary"] = dict(primary)
    _st.session_state["map_extra"] = dict(extra)
    _st.session_state["map_err"] = err

    # 조회가 실패하면 값을 만들어내지 않고 사유를 돌려준다(이메일 열 조회 전용 전환 근거).
    saved = _db.get_user_emails_bulk

    def _boom(_emps):
        raise _db.DATA_SOURCE_ERRORS[1]("mock 조회 실패")

    try:
        _mu.db.get_user_emails_bulk = _boom
        _st.session_state["map_failed"] = _mu._email_map(emps)
    finally:
        _mu.db.get_user_emails_bulk = saved


def test_email_map_bulk_contract():
    """N+1 제거(목록 1회 조회)가 단건 반복과 동일한 값·실패 계약을 유지한다."""
    try:
        from streamlit.testing.v1 import AppTest
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] AppTest 미가용: {exc}")
        return
    at = AppTest.from_function(_email_map_bulk_app, default_timeout=60).run()
    check("bulk 계약 probe 예외 없음", not at.exception, str(at.exception))
    if at.exception:
        return
    check("bulk[사번] == 단건 get_user_emails(사번) (전건)", at.session_state["bulk_eq"] is True)
    check("_email_map 대표 주소 = ALL scope 최소값",
          at.session_state["map_primary"].get("1001") == "aa@x.com",
          str(at.session_state["map_primary"]))
    check("_email_map 추가 주소 수(대표 제외)",
          at.session_state["map_extra"].get("1001") == 2
          and at.session_state["map_extra"].get("1002") == 0,
          str(at.session_state["map_extra"]))
    check("정상 조회는 사유 없음", at.session_state["map_err"] == "")
    p2, e2, err2 = at.session_state["map_failed"]
    check("bulk 조회 실패는 빈 값 위조가 아니라 사유로 표면화",
          p2 == {} and e2 == {} and err2.startswith("알림 이메일을 불러오지 못했습니다"), str(err2))
    src = inspect.getsource(mu._email_map)
    check("화면은 사번당 단건 조회(N+1)를 하지 않는다",
          "get_user_emails_bulk" in src and "db.get_user_emails(" not in src)


def test_email_map_not_ready():
    """010 미준비면 값을 만들지 않고 사유를 돌려준다(조회 전용 전환 근거)."""
    orig = mu.db.capabilities_ready
    try:
        mu.db.capabilities_ready = lambda: False
        primary, extra, err = mu._email_map(["1001"])
        check("미준비 시 사유 반환", bool(err) and primary == {} and extra == {})
    finally:
        mu.db.capabilities_ready = orig
    check("빈 목록은 조회하지 않음", mu._email_map([]) == ({}, {}, ""))


def test_summary_chips_empty_keeps_filter():
    """0건 결과에서도 활성(비기본) 필터 칩은 유지하되 분포 칩은 결과 있을 때만(P2b 통일)."""
    captured: list[str] = []
    orig = mu.st.markdown
    mu.st.markdown = lambda html, **k: captured.append(html)
    try:
        empty = pd.DataFrame(columns=["_row_state", "재직"])
        default = {"active": "전체", "dept": mu._ALL, "role": mu._ALL, "search": ""}

        # (a) 0건 + 활성 필터: 필터 칩(lock) 유지, 분포 칩(ok/mute) 없음
        mu._render_summary_chips(empty, {**default, "active": "퇴직"}, {})
        html_a = captured[-1] if captured else ""
        check("0건이어도 활성 필터 칩 표시", "ms-chip lock" in html_a and "재직 여부: 퇴직" in html_a)
        check("0건이면 분포 칩(ok/mute) 미표시",
              "ms-chip ok" not in html_a and "ms-chip mute" not in html_a)

        # (b) 활성 필터 전무 + 0건: 아무것도 렌더 안 함(markdown 미호출)
        before = len(captured)
        mu._render_summary_chips(empty, default, {})
        check("필터 없고 0건이면 아무 칩도 렌더 안 함", len(captured) == before)

        # (c) 결과 있음 + 필터: 필터 칩과 분포 칩 공존(기존 계약 유지)
        rows = pd.DataFrame([
            {"_row_state": "existing", "재직": True},
            {"_row_state": "existing", "재직": False},
        ])
        mu._render_summary_chips(rows, {**default, "search": "김"}, {})
        html_c = captured[-1]
        check("결과 있으면 필터 칩+분포 칩 공존",
              "ms-chip lock" in html_c and "ms-chip ok" in html_c and "ms-chip mute" in html_c)
    finally:
        mu.st.markdown = orig


def main():
    test_transform_ok()
    test_role_variants()
    test_empty_team_and_skip()
    test_tenure_validation()
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
    test_refresh_invalidates_reads()
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
    test_single_action_entry_point()
    test_header_sync_converges()
    test_count_row_status()
    test_email_column_contract()
    test_email_validation()
    test_email_primary_and_merge()
    test_email_save_roundtrip()
    test_admin_editor_targets()
    test_email_map_not_ready()
    test_email_map_bulk_contract()
    test_summary_chips_empty_keeps_filter()

    print("-" * 60)
    if _failures:
        print(f"FAILED {len(_failures)}건: " + ", ".join(_failures))
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
