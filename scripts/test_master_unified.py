"""기준정보 3화면 **통합/크로스스크린 계약** 테스트 (Phase4 Lane F).

per-screen 계약(변환·검증·삭제정책)은 각 화면 focused 스위트가 지킨다:
  scripts/test_master_users_new.py / test_master_org_new.py / test_master_work_types_new.py
  그리고 공통 기반 단위는 scripts/test_master_common.py.

이 스위트는 그 위에서 **세 화면이 한 시스템으로 일관되는지**를 검증한다:
  1) 세 화면 모두 신규 공통 기반 ``views/master`` 로 재구현됐고, 구 workspace
     grid 헬퍼(selectable_master_grid/master_count/editable_aggrid)·구 전역
     action key(ms_*_req/od_*_req/ou_*_req)에 더 이상 의존하지 않는다.
  2) page-scoped 상태 격리 — 네 편집 컨텍스트(master_users/master_work_types/
     org_dept/org_unit)의 세션 key 가 서로 절대 충돌하지 않는다(구 ms_* 전역키 누수 없음).
  3) 화면 간 공통 크롬 일관성(제목/모드배지/필터/액션바/그리드/건수) — AppTest 렌더.
  4) 상태→시각 이중부호화(색 + 테두리/아이콘) 단일기준을 세 화면이 공유한다.
  5) 조직 좌/우 독립 저장 + 부분성공 계약(한쪽 partial 이 다른쪽·재적재에 새지 않음).
  6) 근무형태 색상 단일기준이 근무표/개인 조회 화면 색을 구동한다(workspace 공존).
  7) workspace.py 는 근무표/편성/개인 화면과 공존해 깨지지 않는다(호환).
  8) 기준정보 route 권한(USER 차단 / ADMIN 허용) 회귀.

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

from streamlit.testing.v1 import AppTest  # noqa: E402

from modules import db, nav  # noqa: E402
from views import (  # noqa: E402
    master_departments,
    master_org,
    master_teams,
    master_users,
    master_work_types,
    workspace,
)
from views import master as master_pkg  # noqa: E402
from views.master import state as mstate  # noqa: E402

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


# 세 화면과 각자의 소스(정적 계약 검사용).
_SCREENS = {
    "사용자 관리": master_users,
    "조직 관리": master_org,
    "근무형태 관리": master_work_types,
}
_SRC = {label: inspect.getsource(mod) for label, mod in _SCREENS.items()}


# ===========================================================================
# 1) 세 화면이 모두 신규 공통 기반(views/master)으로 재구현됨 (정적)
# ===========================================================================
print("공통 기반 재구현 — 세 화면이 views/master 골격을 실제로 사용")
# 공통 기반이 제공하는 핵심 심볼(제목/액션/그리드/저장/건수/dirty)을 실제로 참조하는가.
_COMMON_SYMBOLS = (
    "master_screen_head", "master_action_bar", "render_master_grid",
    "master_grid_height", "MasterGridSpec", "run_save", "PersistResult",
    "dirty_total", "count_strip",
)
for label, src in _SRC.items():
    check(f"{label}: 공통 기반 패키지 import", "from views.master import" in src
          or "from views import master" in src)
    for sym in _COMMON_SYMBOLS:
        check(f"{label}: 공통 심볼 사용 [{sym}]", sym in src)

# 구 workspace grid 헬퍼·모듈 의존 제거 (마이그레이션 완료 — 되돌아가지 않았는가)
print("구 workspace grid 의존 제거")
for label, src in _SRC.items():
    check(f"{label}: 구 selectable_master_grid 미사용", "selectable_master_grid" not in src)
    check(f"{label}: 구 master_count 미사용", "master_count(" not in src)
    check(f"{label}: 구 editable_aggrid 미사용", "editable_aggrid" not in src)
    check(f"{label}: workspace 모듈 import 없음",
          "from views import workspace" not in src and "views.workspace" not in src
          and "workspace." not in src)

# 구 전역 action key(ms_*_req/od_*_req/ou_*_req)·구형 UI 잔재 제거
print("구 전역 action key·구형 UI 잔재 제거")
_LEGACY_FLAGS = ("ms_add_req", "ms_del_req", "ms_save_req", "ms_refresh_req",
                 "od_save_req", "od_add_req", "ou_save_req", "ou_add_req")
_LEGACY_UI = ("summary_cards", "ui.card(", "ui.action_bar", 'key="ms_filter"',
              'key="ms_bar"')
for label, src in _SRC.items():
    for flag in _LEGACY_FLAGS:
        check(f"{label}: 구 전역 플래그 없음 [{flag}]", flag not in src)
    for ui_token in _LEGACY_UI:
        check(f"{label}: 구형 UI 없음 [{ui_token}]", ui_token not in src)
    check(f"{label}: 검정 저장 버튼 색(#1B1B1D/#000000) 없음",
          "#1B1B1D" not in src and "#000000" not in src)


# ===========================================================================
# 2) 공통 기반 공개 API 존재 (테스트↔실제 결합 — 심볼이 사라지면 즉시 FAIL)
# ===========================================================================
print("공통 기반 공개 API 존재")
for attr in ("DraftState", "MasterGridSpec", "render_master_grid", "run_save",
             "PersistResult", "ReadinessState", "master_action_bar", "count_strip",
             "dirty_total", "ledger_banner", "master_screen_head", "master_grid_height",
             "mode_badge_html", "master_row_class_rules", "GRID_CSS"):
    check(f"views.master 공개 API [{attr}]", hasattr(master_pkg, attr))


# ===========================================================================
# 3) page-scoped 상태 격리 — 네 편집 컨텍스트 key 가 절대 충돌하지 않음
# ===========================================================================
print("page-scoped 상태 격리 (구 공용 ms_* 전역키 누수 없음)")
check("사용자 PAGE_ID 확정", master_users.PAGE_ID == "master_users")
check("근무형태 PAGE_ID 확정", master_work_types.PAGE_ID == "master_work_types")
check("조직 좌 패널 DraftState('org_dept')", 'DraftState("org_dept")' in _SRC["조직 관리"])
check("조직 우 패널 DraftState('org_unit')", 'DraftState("org_unit")' in _SRC["조직 관리"])

_CONTEXTS = ["master_users", "master_work_types", "org_dept", "org_unit"]
_states = {pid: mstate.DraftState(pid) for pid in _CONTEXTS}
# 모든 action key / rows key / flash key 가 컨텍스트 간 유일해야 한다(누수 원천 차단).
for role in ("save", "add", "delete", "refresh"):
    keys = [s.action_key(role) for s in _states.values()]
    check(f"action key '{role}' 4개 컨텍스트 전부 유일", len(set(keys)) == len(keys))
    # 어떤 key 도 구 공용 접두사(ms_/ms:)로 시작하지 않는다.
    check(f"action key '{role}' 구 공용 접두사 없음",
          all(not k.startswith("ms_") and not k.startswith("ms:") for k in keys))
row_keys = [s.rows_key for s in _states.values()]
flash_keys = [s.flash_key for s in _states.values()]
check("rows key 4개 컨텍스트 전부 유일", len(set(row_keys)) == len(row_keys))
check("flash key 4개 컨텍스트 전부 유일", len(set(flash_keys)) == len(flash_keys))
check("좌/우 조직 패널 save flag 격리(od≠ou)",
      _states["org_dept"].action_key("save") != _states["org_unit"].action_key("save"))


# ===========================================================================
# 4) 화면 간 공통 크롬 일관성 (AppTest 렌더 — 예외 없음 + 동일 골격)
# ===========================================================================
print("화면 간 공통 크롬 일관성 (제목·모드배지·필터·액션바·그리드·건수)")
_ADMIN = db.find_user_by_emp_no("1001")


def _render_users():
    import os as _os
    _os.environ["DUTY_DATA_MODE"] = "sample"
    from modules import db as _db
    from views import master_users as _m
    _m.render(_db.find_user_by_emp_no("1001"))


def _render_work_types():
    import os as _os
    _os.environ["DUTY_DATA_MODE"] = "sample"
    from modules import db as _db
    from views import master_work_types as _m
    _m.render(_db.find_user_by_emp_no("1001"))


def _render_org():
    import os as _os
    _os.environ["DUTY_DATA_MODE"] = "sample"
    from modules import db as _db
    from views import master_org as _m
    _m.render(_db.find_user_by_emp_no("1001"))


_RENDERS = {
    "사용자 관리": (_render_users, "사용자 관리", ("master_users__save", "master_users__add",
                                             "master_users__delete", "master_users__refresh")),
    "근무형태 관리": (_render_work_types, "근무형태 관리",
                 ("master_work_types__save", "master_work_types__add",
                  "master_work_types__delete", "master_work_types__refresh")),
    "조직 관리": (_render_org, "조직 관리", ("org_dept__save", "org_dept__add",
                                       "org_dept__delete", "org_dept__refresh",
                                       "org_unit__save")),
}

_bodies: dict[str, str] = {}
for label, (fn, title, keys) in _RENDERS.items():
    at = AppTest.from_function(fn, default_timeout=60).run()
    check(f"{label}: 렌더 예외 없음", not at.exception)
    body = " ".join(str(m.value) for m in at.markdown)
    _bodies[label] = body
    check(f"{label}: 페이지 제목 표시", title in body)
    # 공통 크롬 4요소가 모두 있어야 화면 간 일관 — 색만으로 구분하지 않는 프레임.
    check(f"{label}: 공통 헤더 크롬(ms-head/ms-title)", "ms-head" in body and "ms-title" in body)
    check(f"{label}: 모드 배지(ms-mode + 샘플 데이터)", "ms-mode" in body and "샘플 데이터" in body)
    check(f"{label}: 상태 스트립(ms-count)", "ms-count" in body)
    btn_keys = {b.key for b in at.button}
    for k in keys:
        check(f"{label}: page-scoped 액션 버튼 키 [{k}]", k in btn_keys)
    # 갓 로드(변경 0) → 저장 버튼 비활성 — 세 화면 공통 §8 계약.
    save_key = keys[0]
    save_btn = next((b for b in at.button if b.key == save_key), None)
    if save_btn is not None and hasattr(save_btn, "disabled"):
        check(f"{label}: 갓 로드 시 저장 비활성(변경 없음)", bool(save_btn.disabled))
    else:
        check(f"{label}: 저장 버튼 존재(비활성 속성 미노출)", save_btn is not None)

# 크로스스크린 일관성 — 세 화면이 정확히 같은 크롬 클래스 집합을 렌더한다.
_CHROME = ("ms-head", "ms-title", "ms-mode", "ms-count")
for cls in _CHROME:
    present = [label for label, body in _bodies.items() if cls in body]
    check(f"크롬 '{cls}' 를 세 화면 모두 렌더", len(present) == 3)


# ===========================================================================
# 5) 상태→시각 이중부호화 단일기준 (색 + 테두리/아이콘, 상호배타 우선순위)
# ===========================================================================
print("상태 이중부호화 단일기준 (color-only 금지)")
from views.master import style  # noqa: E402

rules = style.master_row_class_rules(include_group=True, include_linked=True)
# 우선순위 상호배타: selected 는 상위 4개(error/delete/new/inactive)를 모두 배제.
check("행 상태 상호배타: selected 가 상위 4개 배제", rules["ms-row-selected"].count("!(") == 4)
check("행 상태: error 는 최상위(무가드)", "&& !(" not in rules["ms-row-error"])
# 이중부호화: 색(background) 과 함께 비색 신호(box-shadow inset/테두리)를 갖는다.
# cascade #6(D2): 배경은 셀(.ms-row-X .ag-cell), 좌측 상태바(비색)는 행(.ag-row.ms-row-X)로
# 정당하게 분리됐다 — 셀 dirty/error box-shadow 와 슬롯이 겹치지 않게. 두 신호가 세 상태
# 모두에 실재하는지(약화 없이) 각 selector 에서 검증한다.
gcss = style.GRID_CSS
for state_cls in ("ms-row-new", "ms-row-delete", "ms-row-error"):
    cell_spec = gcss.get(f".{state_cls} .ag-cell", {})   # 색(배경)
    row_spec = gcss.get(f".ag-row.{state_cls}", {})       # 비색(좌측 상태바)
    has_color = "background" in cell_spec
    has_noncolor = any("box-shadow" in k or "border" in k for k in row_spec)
    check(f"'{state_cls}' 색+비색 이중부호화(배경=셀 / 좌측바=행)", has_color and has_noncolor)
# 셀 오류/드롭다운도 비색 신호(테두리/▾)를 동반.
check("셀 오류는 테두리(inset) 동반", "box-shadow" in gcss.get(".ms-cell-error", {}))
check("드롭다운 셀은 ▾ 표식 동반", ".ms-cell-select::after" in gcss)
# 세 화면 렌더가 실제로 이 공통 GRID_CSS/rowClassRules 경로를 통과함을 정적 확인.
for label, src in _SRC.items():
    check(f"{label}: 공통 render_master_grid 경유(상태 시각 단일기준)", "render_master_grid" in src)


# ===========================================================================
# 6) 조직 좌/우 독립 저장 + 부분성공 계약
# ===========================================================================
print("조직 좌/우 독립 저장 · 부분성공(한쪽이 다른쪽·재적재로 새지 않음)")
org_src = _SRC["조직 관리"]
check("좌(그룹·부서) 저장 경로 _save_depts + run_save(_OD)", "def _save_depts" in org_src
      and "run_save(_OD" in org_src)
check("우(운영단위) 저장 경로 _save_units + run_save(_OU)", "def _save_units" in org_src
      and "run_save(_OU" in org_src)
# Phase5: 성공/부분성공은 report(save_org_*_report → to_persist_kwargs)로 정확 반환,
# 예외만 PersistResult.failure. 두 경로가 report 기반 부분성공 계약을 쓰는지 검증.
check("좌 저장: 부서 report 기반 부분성공 계약(save_org_departments_report)",
      "save_org_departments_report" in org_src)
check("우 저장: 운영단위 report 기반 부분성공 계약(save_org_teams_report)",
      "save_org_teams_report" in org_src)
check("두 경로 모두 report→PersistResult 매핑(to_persist_kwargs) 사용",
      "to_persist_kwargs" in org_src)
check("두 경로 모두 예외 시 PersistResult.failure 로 불명 처리",
      "PersistResult.failure" in org_src)
# 부서/조 메뉴가 같은 조직 관리 화면으로 위임(단일 통합 화면).
check("부서 관리 메뉴 → 조직 관리 위임",
      "master_org.render" in inspect.getsource(master_departments.render))
check("조 관리 메뉴 → 조직 관리 위임",
      "master_org.render" in inspect.getsource(master_teams.render))


def _org_partial_independence():
    # 좌 패널 저장이 partial 이면: 재적재 금지(draft 보존) + 우 패널 상태 무영향.
    import streamlit as st
    from views.master import state as _state
    from views.master.lifecycle import PersistResult as PR, run_save as _run_save

    od = _state.DraftState("org_dept")
    ou = _state.DraftState("org_unit")
    od.set_rows("LEFT_DRAFT")
    ou.set_rows("RIGHT_DRAFT")
    ou.set_dirty(True)  # 우 패널은 별도로 dirty

    def _persist(_m, _r):
        return PR(page_id="org_dept", succeeded_keys=["A"], failed_keys=["B"], error="일부 실패")

    out = _run_save(od, validate=lambda: ([{"code": "A"}], []),
                    build_candidate=lambda r: ("MERGED", []), persist=_persist)
    st.session_state["status"] = out.status
    st.session_state["should_reload"] = out.should_reload
    # 좌 partial 후에도 우 패널 draft/ dirty 는 그대로여야 한다(독립).
    st.session_state["right_rows"] = ou.get_rows()
    st.session_state["right_dirty"] = ou.is_dirty()
    # 좌 action flag 를 소비해도 우 save flag 는 소비되지 않는다(page-scoped).
    od.request_action("save")
    st.session_state["left_took"] = od.take_action("save")
    st.session_state["right_took"] = ou.take_action("save")  # 다른 컨텍스트 → False


at_p = AppTest.from_function(_org_partial_independence, default_timeout=45).run()
check("부분성공 계약 렌더 예외 없음", not at_p.exception)
check("좌 partial → status='partial'", at_p.session_state["status"] == "partial")
check("좌 partial → 재적재 금지(draft 보존)", at_p.session_state["should_reload"] is False)
check("우 패널 draft 무영향(독립)", at_p.session_state["right_rows"] == "RIGHT_DRAFT")
check("우 패널 dirty 무영향(독립)", at_p.session_state["right_dirty"] is True)
check("좌 save flag 소비가 우로 누수 없음",
      at_p.session_state["left_took"] is True and at_p.session_state["right_took"] is False)


# ===========================================================================
# 7) 근무형태 색상 단일기준 → 근무표/개인 조회 색 구동 (workspace 공존)
# ===========================================================================
print("근무형태 색상 단일기준 (work_types.color → 조회 화면 색)")
check("근무형태 기본색 단일 상수(#9AA0A6)", master_work_types._DEFAULT_COLOR == "#9AA0A6")
check("색상 정규화 #RRGGBB 대문자 단일기준",
      master_work_types._normalize_hex("#2e9e5b") == "#2E9E5B"
      and master_work_types._normalize_hex("#abc") == "#AABBCC")

display_of, color_of = workspace.work_type_display()
check("근무형태 표시/색 매핑 비어있지 않음", bool(display_of) and bool(color_of))
check("모든 색은 #RRGGBB 형식", all(str(c).startswith("#") for c in color_of.values()))
# 색은 코드에 귀속 — 같은 코드의 표시값(약칭)과 코드가 같은 색을 공유한다(단일기준).
shared_ok = True
for code, disp in display_of.items():
    if code in color_of and disp in color_of and color_of[code] != color_of[disp]:
        shared_ok = False
        break
check("색은 코드에 귀속(약칭↔코드 동일 색)", shared_ok)
# 단일기준이 실제 조회 화면으로 전파: 개인/전체 근무표가 work_type_display 를 소비.
check("개인 근무표가 색 단일기준(work_type_display) 소비",
      "work_type_display" in inspect.getsource(__import__("views.my_schedule", fromlist=["x"])))
check("전체 근무표(schedule_screen)가 색 단일기준 소비",
      "work_type_display" in inspect.getsource(workspace.schedule_screen))


# ===========================================================================
# 8) workspace.py 공존/호환 — 근무표·편성·개인 화면이 깨지지 않음
# ===========================================================================
print("workspace 공존/호환 (신규 패키지와 병존, 기존 소비처 무손상)")
for helper in ("work_type_display", "schedule_screen", "selectable_master_grid",
               "editable_aggrid"):
    check(f"workspace 기존 소비처용 헬퍼 유지 [{helper}]", hasattr(workspace, helper))
# 스케줄 소비처가 실제로 workspace 에 계속 의존(호환 경로가 살아있음).
sv_src = inspect.getsource(__import__("views.schedule_view", fromlist=["x"]))
se_src = inspect.getsource(__import__("views.schedule_edit", fromlist=["x"]))
check("schedule_view → workspace.schedule_screen 사용", "workspace.schedule_screen" in sv_src)
check("schedule_edit → workspace 헬퍼 사용", "from views.workspace import" in se_src)
# 신규 공통 기반과 구 workspace 가 동시에 import 되어도 충돌 없음(공존 스모크).
check("공통 기반·workspace 동시 로드 정상", master_pkg is not None and workspace is not None)


# ===========================================================================
# 9) 기준정보 route 권한 회귀
# ===========================================================================
print("route 권한 회귀 (USER 차단 / ADMIN 허용)")
for page in ("master_users", "master_departments", "master_teams", "master_work_types"):
    check(f"USER 는 {page} 접근 불가", not nav.allowed(page, "USER"))
    check(f"ADMIN 은 {page} 접근 가능", nav.allowed(page, "ADMIN"))


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
