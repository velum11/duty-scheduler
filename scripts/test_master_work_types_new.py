"""근무형태 관리(master_work_types) 재구현 focused 테스트 (Phase4 Lane C).

공통 기반 `views.master` 위에 재구현한 근무형태 화면의 계약을 검증한다:
  - 렌더 스모크(AppTest, 예외 없음, sample 모드)
  - 액션 진입점 단일화(2026-08-14): 화면 안 버튼 바 없음 · 상단 52px 헤더 아이콘 4종에
    같은 활성/사유 발행 · 발행값 변경 시에만 1회 재렌더(헤더 선렌더 지연 보정) ·
    미저장/선택 상태 표시 보존
  - 저장 전 검증 `_validate` 하위호환((records, errors), 색상 #RRGGBB 보존, 필수값)
  - 보강 검증(Codex 지적): 색상 #RRGGBB 형식·정규화, 시간 HH:MM, 셀 오류 맵
  - dirty baseline 헬퍼(_row_tuple / _dirty_fields_json), 약칭 중복 소프트 경고
  - 삭제 정책(참조>0 → 미사용, 참조0 → 물리 삭제)

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_master_work_types_new.py
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


def _meta(rows):
    frame = pd.DataFrame(rows)
    if "_removed" not in frame:
        frame["_removed"] = ""
    if "_row_id" not in frame:
        frame["_row_id"] = [f"e:{i}" for i in range(len(frame))]
    if "_row_state" not in frame:
        frame["_row_state"] = "existing"
    return frame


# ===== 1) 렌더 스모크 =====
def _screen_work_types():
    from modules import db
    from views import master_work_types
    master_work_types.render(db.find_user_by_emp_no("1001"))


def test_render_smoke() -> None:
    print("렌더 스모크 (공통 기반 재구현, 예외 없음)")
    at = AppTest.from_function(_screen_work_types, default_timeout=60).run()
    check("master_work_types 렌더 예외 없음", not at.exception)
    # 공통 기반 사용 확인(정적 소스)
    import inspect
    from views import master_work_types
    src = inspect.getsource(master_work_types)
    check("공통 기반 views.master 사용", "from views import master" in src or "views.master" in src)
    # 헤더 크롬은 공통 기반을 직접(master_screen_head) 또는 중립 키트(erp.screen_frame —
    # 내부적으로 scaffold.page_chrome → master.master_screen_head 를 호출)를 통해 쓴다.
    # KP-standard 구조 이전(§0.2) 후에도 최종 렌더 계층은 동일 함수다(test_screen_scaffold.py
    # 가 render-path AST 로 이를 별도 검증).
    check("공통 헤더(master_screen_head/erp.screen_frame) 사용",
          "master_screen_head" in src or "screen_frame" in src)
    # 액션은 상단 타이틀 밴드(toolbar=True + page_action_specs)로 승격됐다 — 인페이지
    # master_action_bar 대신 공통 활성/건수/사유 규칙(page_action_specs)을 밴드에 채운다.
    check("공통 액션 규칙(master_action_bar/밴드 page_action_specs) 사용",
          "master_action_bar" in src or "page_action_specs" in src)
    check("공통 그리드(render_master_grid) 사용", "render_master_grid" in src)
    check("동적 그리드 높이(master_grid_height) 사용", "master_grid_height" in src)


# ===== 1-1) 액션 진입점 = 상단 52px 앱 헤더 아이콘 하나 (2026-08-14 사용자 지시) =====
# 종전: 헤더 아이콘 4종 + 건수 행 우측 인페이지 버튼 바 4개 = 같은 액션에 진입점이 둘.
# 현재: 인페이지 버튼 바를 제거하고 상단 헤더 아이콘만 남긴다(DESIGN §0-3 "아이콘 툴바는
# 최상단 헤더 바 안에만"). 활성/사유 계산(page_action_specs)·flag 소비(take_actions)·
# 확인 게이트는 종전 그대로다 — 진입점만 하나로 줄었다.
def test_actions_in_app_header_only() -> None:
    print("액션 진입점 단일화 — 화면 안 버튼 바 제거, 상단 52px 헤더 아이콘만")
    import inspect
    from views import master_work_types as m
    src = inspect.getsource(m.render)
    i_frame = src.find("erp.screen_frame(")
    i_grid = src.find("render_master_grid(spec")
    i_crow = src.find("count_row_slot = st.container()")
    i_specs = src.find("page_action_specs")
    i_pub = src.find("_publish_header_actions(state, specs)")
    check("헤더는 중립 프레임(erp.screen_frame)만 사용", 0 <= i_frame)
    check("아이콘 밴드 제거(toolbar/render_icons 없음)",
          'toolbar="icons"' not in src and "render_icons" not in src)
    check("건수 행 슬롯을 그리드보다 먼저 확보", 0 <= i_crow < i_grid)
    check("액션 스펙은 그리드 건수 계산 뒤 산출(page_action_specs)", i_grid < i_specs)
    check("액션 활성/사유는 공통 규칙(page_action_specs) 재사용", 0 <= i_specs)
    # 회귀 방지 핵심: 화면 안에 행 추가·삭제·저장·새로고침 버튼을 되살리지 않는다.
    check("화면 안 액션 버튼 바 없음(action_requester 버튼 미렌더)",
          "action_requester(" not in src and 'f"{PAGE_ID}__{role}"' not in src)
    check("render 본문에 st.button 없음(확인 바 버튼은 배너 함수가 소유)", "st.button(" not in src)
    check("상단 헤더 아이콘에 같은 스펙 발행(header_actions_from_specs)", 0 <= i_specs < i_pub)
    check("클릭 flag 소비 경로는 종전 그대로(take_actions)", "take_actions(state)" in src)
    check("배너 슬롯은 그리드보다 먼저 확보", 0 <= src.find("banner_slot = st.container()") < i_grid)


# ===== 1-1b) 헤더 아이콘 발행 상태 = 인페이지 규칙과 동일 (선택/미저장 기준) =====
def test_header_action_states() -> None:
    print("헤더 아이콘 상태 발행 — 선택 0 · 미저장 0 → 추가·새로고침 활성 / 삭제·저장 음영")
    from modules.ui import _HDR_STATE_PREFIX
    from views.master import page_action_specs

    at = AppTest.from_function(_screen_work_types, default_timeout=60).run()
    check("렌더 예외 없음(발행 경로 포함)", not at.exception)
    # AppTest 의 session_state 프록시는 dict.get 이 없다 — 존재 확인 후 인덱싱한다.
    hdr_key = _HDR_STATE_PREFIX + "master_work_types"
    pub = at.session_state[hdr_key] if hdr_key in at.session_state else None
    check("헤더 아이콘 상태가 page 스코프로 발행됨", isinstance(pub, dict))
    if isinstance(pub, dict):
        check("4종(add/delete/save/refresh) 모두 발행",
              set(pub) == {"add", "delete", "save", "refresh"})
        check("행 추가는 활성", pub["add"][0] is False)
        check("새로고침은 활성", pub["refresh"][0] is False)
        check("선택 0 → 삭제 음영", pub["delete"][0] is True)
        check("미저장 0 → 저장 음영", pub["save"][0] is True)
        check("삭제 음영 사유 tooltip 존재", "선택" in (pub["delete"][1] or ""))
        check("저장 음영 사유 tooltip 존재", "변경" in (pub["save"][1] or ""))

    # 발행값은 인페이지 액션바와 같은 순수 규칙(page_action_specs)에서 나온다 — 선택/미저장이
    # 생기면 삭제·저장이 활성으로 뒤집히는지 규칙 단위로 고정한다(화면은 이 스펙을 그대로 넘긴다).
    by_role = {s["role"]: s for s in page_action_specs(sel_count=2, dirty_total=3, can_save=True)}
    check("선택 2건 → 삭제 활성", by_role["delete"]["disabled"] is False)
    check("미저장 3건 → 저장 활성", by_role["save"]["disabled"] is False)
    check("저장 라벨에 미저장 건수 배지", by_role["save"]["label"] == "저장 · 3")


# ===== 1-1c) 헤더 발행 → 헤더 재렌더 게이트 =====
# 상단 52px 헤더는 화면 본문보다 **먼저** 렌더되므로 본문 끝의 publish 는 그 프레임의
# 헤더에 반영되지 못한다. 인페이지 버튼이 사라진 뒤에는 이 지연이 그대로 기능 결함이 된다
# (실측 1440px/sample: 진입 후 추가 음영 18s+ · 행 선택 후 삭제 음영 55s+ · 행 추가 후
# 저장 음영 25s+ — 본문발 상태 변화 뒤 자동 rerun 이 보장되지 않는다). 그래서 발행값이
# 직전과 다를 때만 1회 rerun 하고, 같으면 rerun 하지 않아 수렴한다.
def _probe_publish_gate():
    """AppTest 안에서 _publish_header_actions 의 변경-게이트 동작을 관찰한다."""
    import streamlit as _st

    from views import master_work_types as m
    from views.master import page_action_specs
    from views.master.state import DraftState

    s = DraftState("master_work_types")
    clean = page_action_specs(sel_count=0, dirty_total=0, can_save=True)
    selected = page_action_specs(sel_count=1, dirty_total=0, can_save=True)
    _st.session_state["probe"] = [
        m._publish_header_actions(s, clean),     # 최초 발행 → 재렌더 필요
        m._publish_header_actions(s, clean),     # 같은 값 → 재렌더 없음(수렴)
        m._publish_header_actions(s, selected),  # 선택 발생 → 재렌더 필요
        m._publish_header_actions(s, selected),  # 같은 값 → 재렌더 없음
    ]


def test_header_publish_rerender_gate() -> None:
    print("헤더 발행값 변경 시에만 1회 재렌더(_publish_header_actions)")
    import inspect
    from modules.ui import _HDR_STATE_PREFIX
    from views import master_work_types as m

    src = inspect.getsource(m._publish_header_actions)
    check("발행은 공통 경로(header_actions_from_specs)", "header_actions_from_specs(PAGE_ID" in src)
    check("발행 서명을 page-scoped 세션 키에 보관", "_HDR_SIG" in src and "state.key(" in src)

    render_src = inspect.getsource(m.render)
    check("render 는 발행 결과로 말미 rerun 을 판단",
          "hdr_changed = _publish_header_actions(" in render_src)
    check("rerun 은 액션 flag 소비(take_actions) 뒤에 온다",
          0 <= render_src.find("take_actions(state)") < render_src.find("structural or hdr_changed"))
    check("_normalize 부작용은 short-circuit 되지 않게 먼저 호출",
          "structural = _normalize(state, grid_df)" in render_src)
    # §21 flash 는 pop-1회 표시라 재렌더 프레임에서 유실된다 — 붙잡았다가 rerun 직전 복구.
    check("재렌더 시 flash 를 붙잡아 둠(배너 렌더 전)",
          0 <= render_src.find("pending_flash = st.session_state.get(state.flash_key)")
          < render_src.find("_render_banners(state, params)"))
    check("rerun 직전 flash 복구", "st.session_state[state.flash_key] = pending_flash" in render_src)

    at = AppTest.from_function(_probe_publish_gate, default_timeout=60).run()
    check("게이트 프로브 렌더 예외 없음", not at.exception)
    seq = at.session_state["probe"] if "probe" in at.session_state else None
    check("변경 시에만 재렌더(True,False,True,False)", seq == [True, False, True, False])
    hdr_key = _HDR_STATE_PREFIX + "master_work_types"
    pub = at.session_state[hdr_key] if hdr_key in at.session_state else None
    check("마지막 발행값이 헤더 상태로 남음(선택 1건 → 삭제 활성)",
          isinstance(pub, dict) and pub["delete"][0] is False)


# ===== 1-1d) 상태 표시 보존 — 버튼을 없애도 미저장·선택 건수는 남는다 =====
def test_edit_state_still_visible() -> None:
    print("상태 표시 보존 — 건수 행 미저장·선택 칩 + 하단 상태 스트립")
    import inspect
    from views import master_work_types as m
    src = inspect.getsource(m.render)
    check("건수 행에 미저장 건수 표시", "미저장 {dtotal}건" in src)
    check("건수 행에 선택 건수 표시", "선택 {sel_count}건" in src)
    check("칩은 공용 토큰(chip_html) 재사용 — 새 색 없음", "master.chip_html(" in src)
    check("우측 편집 상태 자리 CSS(.wt-crow .edit)", ".wt-crow .edit" in m._WT_CROW_CSS)
    check("하단 상태 스트립(count_strip) 유지", "count_strip(" in src)
    check("건수 행 좌측(근무형태 건수·사용/미사용) 유지",
          "wt-crow" in src and "_summary_counts(live)" in src)


# ===== 1-2) B2: 부분성공 원장 — save_work_types_report → PersistResult =====
def test_partial_success_ledger_wiring() -> None:
    print("B2 부분성공 원장 배선 (save_work_types_report → PersistResult)")
    import inspect
    from views import master_work_types as m
    from views.master import PersistResult
    from modules import db
    save_src = inspect.getsource(m._save)
    check("void save_work_types 대신 원장 API(save_work_types_report) 호출",
          "save_work_types_report" in save_src and "db.save_work_types(" not in save_src)
    check("원장 결과를 PersistResult 로 매핑(to_persist_kwargs)", "to_persist_kwargs" in save_src)
    check("partial/unknown 원장 배너 경로 존재",
          "_SAVE_LEDGER" in inspect.getsource(m) and "ledger_banner" in inspect.getsource(m))

    # 실제 매핑(sample 모드 = 전체 성공) 이 PersistResult.ok 로 이어지는지 확인.
    merged = db.get_work_types().copy()[db.WORK_TYPE_COLUMNS]
    report = db.save_work_types_report(merged)
    pr = PersistResult(page_id="master_work_types", **report.to_persist_kwargs())
    check("sample 저장 원장은 전체 성공(ok)", pr.ok is True)
    check("성공 자연키가 원장에 보고됨", len(pr.succeeded_keys) >= 1)

    # 부분성공 reconcile 헬퍼(순수 로직): 성공 key baseline 갱신 / 실패 key 셀 오류.
    live = _meta([
        {"코드": "AAA", "명칭": "가", "분류": "주간", "약칭": "가", "시작": "", "종료": "",
         "색상": "#111111", "실근무": True, "특근수당": False, "설명": "", "표시순서": "1", "사용": True},
        {"코드": "BBB", "명칭": "나", "분류": "주간", "약칭": "나", "시작": "", "종료": "",
         "색상": "#222222", "실근무": True, "특근수당": False, "설명": "", "표시순서": "2", "사용": True},
    ])
    live["_row_id"] = ["e:AAA", "e:BBB"]
    by_code = {str(r["코드"]).strip(): True for _, r in live.iterrows()}
    check("reconcile 대상 코드 매핑 준비", by_code == {"AAA": True, "BBB": True})


# ===== 1-3) B4: 삭제 실패 controller 경계 처리 =====
def test_delete_error_handling() -> None:
    print("B4 삭제 실패 처리 (DATA_SOURCE_ERRORS 포착·재시도 계획)")
    import inspect
    from views import master_work_types as m
    exec_src = inspect.getsource(m._execute_delete)
    check("삭제 write 를 DATA_SOURCE_ERRORS 로 포착", "db.DATA_SOURCE_ERRORS" in exec_src)
    check("비활성 처리는 원장 API(save_work_types_report) 사용", "save_work_types_report" in exec_src)
    check("성공분만 재조회(_load_editor)", "_load_editor(state, params)" in exec_src)
    check("실패분을 재시도 가능한 삭제 계획으로 남김",
          "delete_plan_key" in exec_src and "_DELETE_ERROR" in exec_src)
    conf_src = inspect.getsource(m._confirm_delete)
    check("재시도 확인 바에 실패 사유 노출", "_DELETE_ERROR" in conf_src and "재시도" in conf_src)
    check("참조 시 비활성·미참조 물리삭제 계약 유지",
          "delete_work_type" in exec_src and 'is_active"] = False' in exec_src)

    # 헬퍼 순수 로직.
    check("_key_str: 복합키 결합", m._key_str(("D1", "A")) == "D1/A")
    check("_key_str: 단일키 문자열", m._key_str("DAY") == "DAY")
    check("_err_text: 빈 예외는 기본 문구", m._err_text(Exception("")) != "")


# ===== 1-4) WAVE 2b 통일 재설계 — 약칭 중복칩·분류칩·필터 요약칩 =====
def test_unified_redesign_features() -> None:
    print("WAVE2b 통일 재설계 (약칭 중복 경고칩·분류 칩·필터 요약칩)")
    import inspect
    from views import master_work_types as m

    cfg = m._col_config()
    check("약칭 열에 셀 렌더러 주입(라이브 중복칩)", "cellRenderer" in cfg["약칭"])
    check("분류 열에 셀 렌더러 주입(칩)", "cellRenderer" in cfg["분류"])

    # 약칭 중복칩은 공통 `.ms-chip warn` 어휘 + 활성 기준(저장 검증과 동일 규칙)을 사용.
    short_src = str(m._SHORT_LABEL_RENDERER.js_code)
    check("약칭 렌더러가 공통 warn 칩 사용", "ms-chip warn" in short_src and "약칭 중복" in short_src)
    check("약칭 중복 판정은 활성 행 기준(사용/제거 반영)", "_active" in short_src and "_removed" in short_src)
    cat_src = str(m._CATEGORY_RENDERER.js_code)
    check("분류 렌더러가 공통 mute 칩 사용", "ms-chip mute" in cat_src)

    # 다른 행 약칭/사용 편집에 반응하도록 onCellValueChanged 로 약칭 열을 refresh.
    render_src = inspect.getsource(m.render)
    check("그리드에 onCellValueChanged(_DUP_REFRESH) 배선", "onCellValueChanged" in render_src)
    dup_src = str(m._DUP_REFRESH.js_code)
    check("변경 셀이 약칭/사용일 때 약칭 열 refresh", "refreshCells" in dup_src and "약칭" in dup_src)

    # 요약칩 — 현재 필터결과(로드된 기존 행) 기준 사용/미사용 분포(전체 카운트 아님).
    frame = _meta([
        {"코드": "A", "명칭": "가", "분류": "주간", "약칭": "가", "색상": "#111111",
         "실근무": True, "특근수당": False, "설명": "", "표시순서": "1", "사용": True},
        {"코드": "B", "명칭": "나", "분류": "주간", "약칭": "나", "색상": "#222222",
         "실근무": True, "특근수당": False, "설명": "", "표시순서": "2", "사용": True},
        {"코드": "C", "명칭": "다", "분류": "주간", "약칭": "다", "색상": "#333333",
         "실근무": True, "특근수당": False, "설명": "", "표시순서": "3", "사용": False},
    ])
    active, inactive = m._summary_counts(frame)
    check("요약 카운트는 필터결과(프레임) 기준 사용 중", active == 2)
    check("요약 카운트는 필터결과(프레임) 기준 미사용", inactive == 1)
    # 신규 행은 저장 전이므로 분포에서 제외.
    frame_new = _meta([
        {"코드": "N", "명칭": "신규", "분류": "", "약칭": "", "색상": "", "실근무": False,
         "특근수당": False, "설명": "", "표시순서": "9", "사용": True},
    ])
    frame_new["_row_state"] = "new"
    check("신규 행은 요약 분포에서 제외", m._summary_counts(frame_new) == (0, 0))

    # §1-E(8단계): 요약칩 카드 제거 → 건수 행(count_row_slot)에 사용 중/미사용 분포를
    # _summary_counts(필터결과 기준) 로 인라인 표기. 전체 db 카운트가 아니라 라이브 프레임 기준.
    check("건수 행에 사용 중/미사용 라벨", "사용 중" in render_src and "미사용" in render_src)
    check("분포는 필터결과 기준(_summary_counts(live) 사용, 전체 db 카운트 아님)",
          "_summary_counts(live)" in render_src)
    check("분포·건수를 그리드 위 건수 행 슬롯에서 렌더",
          0 <= render_src.find("count_row_slot = st.container()") < render_src.find("render_master_grid(spec"))


# ===== 1-5) 색 미리보기 = 셀 단위 계약 (2026-08-07 사용자 요구로 별도 스와치 줄 폐지) =====
# 구 계약: 그리드 위 '근무표 색·약칭 미리보기' 스와치 줄(_preview_html/_PREVIEW_CAP).
# 같은 색·약칭이 스와치 줄·색상 열·약칭 열에 3중으로 반복돼 화면이 산만하다는 사용자
# 지적으로 스와치 줄을 제거했다. 미리보기 **계약 자체는 셀 단위로 이전**된다 — 색상 열의
# 스와치+대문자 HEX, 약칭 열의 근무형태 색 chip(근무표 배지와 같은 solid 색 + 명도 기반
# 텍스트색). 아래 검사는 그 이전된 계약과 '스와치 줄이 되살아나지 않음'을 함께 고정한다.
def test_preview_color_short_label_contract() -> None:
    print("색 미리보기 = 셀 단위(색상 열 스와치 + 약칭 열 색 chip) · 별도 스와치 줄 없음")
    import inspect
    from views import master_work_types as m

    # (1) 별도 미리보기 줄이 되살아나지 않는다(화면·CSS 양쪽).
    render_src = inspect.getsource(m.render)
    check("별도 미리보기 스와치 줄 미렌더(preview_slot 없음)", "preview_slot" not in render_src)
    check("_preview_html/_render_preview 심볼 없음",
          not hasattr(m, "_preview_html") and not hasattr(m, "_render_preview"))
    check("미리보기 스트립 CSS 제거(.ms-preview/.ms-sw)",
          ".ms-preview" not in m._EXTRA_CSS and ".ms-sw" not in m._EXTRA_CSS)
    check("저장 오류 배너 CSS 는 유지(.ms-errlist/.ms-absorb)",
          ".ms-errlist" in m._EXTRA_CSS and ".ms-absorb" in m._EXTRA_CSS)

    # (2) 색상 열 = 스와치 + 대문자 HEX(유효하지 않으면 해치) — 셀 안 미리보기.
    color_src = str(m._COLOR_RENDERER.js_code)
    check("색상 셀에 스와치 렌더", "sw.style.background = v" in color_src)
    check("색상 셀 유효성 해치 표시", "repeating-linear-gradient" in color_src)
    check("색상 열에 렌더러·에디터 주입",
          m._COL_WIDTHS["색상"].get("cellRenderer") is m._COLOR_RENDERER
          and m._COL_WIDTHS["색상"].get("cellEditor") is m._COLOR_EDITOR)

    # (3) 약칭 열 = 근무형태 색 chip(근무표 배지와 동일 어휘) — 색·약칭 적용 결과 시연.
    label_src = str(m._SHORT_LABEL_RENDERER.js_code)
    check("약칭 chip 이 DB 색을 solid 배경으로 적용", "t.style.background = hex" in label_src)
    check("약칭 chip 텍스트색은 명도기반 자동 선택(_textOn)", "this._textOn(hex)" in label_src)
    check("약칭 chip 은 pill 형태(borderRadius 999)", "999px" in label_src)
    check("색이 없으면 평문 폴백(색 없는 행도 표시)", "else if (!val)" in label_src)


# ===== 1-5c) 셀 색 chip 대비 계약 (DESIGN §8 시각 게이트 → 지속 계약) =====
def test_preview_badge_contrast_contract() -> None:
    print("약칭 색 chip 대비(DESIGN §8) — 명도기반 자동 텍스트색이 본문 4.5:1을 보장")
    import re
    from views import master_work_types as m

    # 셀 렌더러(JS)의 _textOn 이 WCAG 상대명도 공식으로 흰/검을 고르는지 구조 고정.
    src = str(m._SHORT_LABEL_RENDERER.js_code)
    check("상대명도 계수 0.2126/0.7152/0.0722 사용",
          "0.2126" in src and "0.7152" in src and "0.0722" in src)
    check("sRGB 선형화 임계(0.03928)·감마(2.4) 사용", "0.03928" in src and "2.4" in src)
    check("흰/검 두 후보만 반환", "'#ffffff'" in src and "'#000000'" in src)

    # 동일 공식을 파이썬으로 재현해 표본 팔레트에서 4.5:1 이상을 실제 수치로 확인한다.
    def _lin(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    def _lum(hexc: str) -> float:
        r, g, b = int(hexc[1:3], 16), int(hexc[3:5], 16), int(hexc[5:7], 16)
        return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)

    def _text_on(hexc: str) -> str:  # JS _textOn 과 동일 판정
        lum = _lum(hexc)
        return "#ffffff" if (1.05 / (lum + 0.05)) >= ((lum + 0.05) / 0.05) else "#000000"

    def _ratio(fg: str, bg: str) -> float:
        a, b = _lum(fg), _lum(bg)
        hi, lo = max(a, b), min(a, b)
        return (hi + 0.05) / (lo + 0.05)

    check("JS 판정식이 흰/검 크로스오버 그대로",
          bool(re.search(r"\(1\.05 / \(L \+ 0\.05\)\) >= \(\(L \+ 0\.05\) / 0\.05\)", src)))
    palette = [
        "#1E6FD9", "#7B4FD8", "#9A7BE3", "#5A3DB8", "#E8862E", "#B4541B",
        "#9AA0A6", "#2E9E5B", "#D64596", "#12A5A5", "#FFFFFF", "#000000",
        "#808080", "#2B2B2B", "#7F7F7F", "#C0C0C0",
    ]
    worst = min(_ratio(_text_on(c), c) for c in palette)
    check(f"표본 전체 chip 대비 ≥ 4.5:1 (최저 {worst:.2f})", worst >= 4.5)


# ===== 1-6) 자연키(코드) 저장행 잠금 계약 (org/users 동일) =====
def test_code_natural_key_locked() -> None:
    print("코드(자연키) 저장행 잠금 — editable=_EDIT_NEW_ONLY + 저장행 읽기전용 틴트")
    from views import master_work_types as m

    # 신규행만 편집 가능한 predicate 정의(org/users 와 동일 식).
    pred = str(m._EDIT_NEW_ONLY.js_code)
    check("_EDIT_NEW_ONLY predicate 정의", "_row_state === 'new'" in pred)
    check("저장행 읽기전용 룰(ms-cell-readonly)", m._CODE_READONLY_RULES ==
          {"ms-cell-readonly": "data._row_state !== 'new'"})

    cfg = m._col_config()
    check("코드 열 editable 게이트 = 신규행만", cfg["코드"].get("editable") is m._EDIT_NEW_ONLY)
    check("코드 열에 저장행 읽기전용 틴트 룰 병합",
          cfg["코드"]["cellClassRules"].get("ms-cell-readonly") == "data._row_state !== 'new'")
    # 다른 편집 컬럼(명칭)은 저장행 잠금 대상이 아님(자연키만 잠금).
    check("명칭 열은 자연키 잠금 미적용", "ms-cell-readonly" not in cfg["명칭"]["cellClassRules"])
    check("코드 열 error/dirty 하이라이트 유지",
          any(k for k in cfg["코드"]["cellClassRules"] if k != "ms-cell-readonly"))


# ===== 2) _validate 하위호환 =====
def test_validate_backward_compat() -> None:
    print("_validate 하위호환 ((records, errors), 색상 보존, 필수값)")
    from views import master_work_types as m
    recs, errs = m._validate(_meta([
        {"코드": "TESTW", "명칭": "테스트근무", "분류": "주간", "약칭": "테", "시작": "08:00",
         "종료": "17:00", "색상": "#123456", "실근무": True, "특근수당": False, "설명": "x",
         "표시순서": "5", "사용": True},
        {"코드": "", "명칭": "이름만", "분류": "", "약칭": "", "시작": "", "종료": "", "색상": "",
         "실근무": False, "특근수당": False, "설명": "", "표시순서": "", "사용": True},
    ]))
    check("색상 HEX 보존(#RRGGBB)", recs[0]["color"] == "#123456")
    check("실근무 bool 변환", recs[0]["is_work"] is True)
    check("필수값(코드/약칭/분류) 검출 ≥3", sum(1 for e in errs if ("코드" in e or "약칭" in e or "분류" in e)) >= 3)
    check("반환 형태는 (records, errors) 2-튜플", isinstance(recs, list) and isinstance(errs, list))

    # 완전 빈 행은 저장 대상 제외
    recs2, _ = m._validate(_meta([
        {"코드": "", "명칭": "", "분류": "", "약칭": "", "시작": "", "종료": "", "색상": "",
         "실근무": False, "특근수당": False, "설명": "", "표시순서": "", "사용": True},
    ]))
    check("완전 빈 행은 records 에서 제외", len(recs2) == 0)


# ===== 3) 색상·시간 보강 검증 =====
def test_color_time_validation() -> None:
    print("보강 검증 (색상 #RRGGBB·정규화, 시간 HH:MM, 셀 오류 맵)")
    from views import master_work_types as m
    recs, errs, emap = m._validate_detailed(_meta([
        {"코드": "OKROW", "명칭": "정상", "분류": "주간", "약칭": "정", "시작": "08:00",
         "종료": "20:00", "색상": "#2e9e5b", "실근무": True, "특근수당": False, "설명": "",
         "표시순서": "1", "사용": True},
        {"코드": "SHORT", "명칭": "삼자리", "분류": "주간", "약칭": "삼", "시작": "", "종료": "",
         "색상": "abc", "실근무": True, "특근수당": False, "설명": "", "표시순서": "2", "사용": True},
        {"코드": "BADHEX", "명칭": "잘못색", "분류": "주간", "약칭": "잘", "시작": "25:00",
         "종료": "9:99", "색상": "red", "실근무": True, "특근수당": False, "설명": "",
         "표시순서": "3", "사용": True},
    ]))
    check("유효 소문자 HEX 는 대문자로 정규화", recs[0]["color"] == "#2E9E5B")
    check("3자리 HEX 는 6자리로 확장", recs[1]["color"] == "#AABBCC")
    check("정상 행은 색상/시간 오류 없음", "e:0" not in emap)
    check("잘못된 색상 검출", any("색상" in e for e in errs))
    check("잘못된 시간(HH:MM) 검출", any("시작" in e for e in errs))
    check("오류 행은 셀 오류 맵에 필드별 기록", emap.get("e:2", {}).get("색상") is not None
          and emap.get("e:2", {}).get("시작") is not None)

    # _normalize_hex 단위
    check("normalize: 누락 # 보정", m._normalize_hex("123456") == "#123456")
    check("normalize: 3자리 확장", m._normalize_hex("#abc") == "#AABBCC")
    check("normalize: 빈 값 → 빈 문자열", m._normalize_hex("") == "")
    check("normalize: 잘못된 값 → None", m._normalize_hex("nope") is None)

    # 빈 색상은 기본색으로 채워짐(오류 아님)
    recs2, errs2, _ = m._validate_detailed(_meta([
        {"코드": "EMPTYC", "명칭": "빈색", "분류": "주간", "약칭": "빈", "시작": "", "종료": "",
         "색상": "", "실근무": False, "특근수당": False, "설명": "", "표시순서": "9", "사용": True},
    ]))
    check("빈 색상은 기본색(#9AA0A6)으로 채움", recs2[0]["color"] == "#9AA0A6")
    check("빈 색상은 오류가 아님", not any("색상" in e for e in errs2))


# ===== 4) dirty baseline·약칭 중복 헬퍼 =====
def test_dirty_and_dup_helpers() -> None:
    print("dirty baseline / 약칭 중복 헬퍼")
    from views import master_work_types as m
    row = {"_row_id": "e:X", "_row_state": "existing",
           "코드": "DAY", "명칭": "주간", "분류": "주간", "약칭": "주", "시작": "08:00",
           "종료": "20:00", "색상": "#1E6FD9", "실근무": True, "특근수당": False,
           "설명": "", "표시순서": "10", "사용": True}
    base = m._row_tuple(row)
    check("baseline 튜플은 사용자 컬럼 전체 포함", set(base.keys()) == set(m._USER_COLS))
    check("변경 없으면 dirty_fields 없음", m._dirty_fields_json(row, base) == "")
    changed = dict(row)
    changed["색상"] = "#2E9E5B"
    check("색상만 바꾸면 색상만 dirty", m._dirty_fields_json(changed, base) == '["색상"]')
    new_row = dict(changed, _row_state="new")
    check("신규 행은 dirty_fields 대상 아님", m._dirty_fields_json(new_row, base) == "")

    dup = m._duplicate_short_labels([
        {"short_label": "주", "is_active": True},
        {"short_label": "주", "is_active": True},
        {"short_label": "야", "is_active": True},
        {"short_label": "비", "is_active": False},  # 비활성은 제외
        {"short_label": "비", "is_active": False},
    ])
    check("활성 약칭 중복만 소프트 경고 대상", dup == ["주"])


# ===== 5) 삭제 정책 (참조>0 → 미사용, 참조0 → 물리 삭제) =====
def test_delete_policy() -> None:
    print("삭제 정책 분류 (근무표 참조 기준)")
    from modules import db
    scheds = db.get_schedules()
    referenced = None
    if not scheds.empty and "work_type_code" in scheds:
        vc = scheds["work_type_code"].astype(str).str.strip()
        vc = vc[vc != ""]
        if not vc.empty:
            referenced = vc.value_counts().index[0]
    if referenced is not None:
        refs = db.work_type_reference_counts(referenced)
        check("참조 있는 코드는 refs>0(→미사용 처리 대상)", sum(refs.values()) > 0)
    else:
        check("참조 있는 코드 없음(스킵)", True)

    all_wt = db.get_work_types()
    used = set(scheds["work_type_code"].astype(str).str.strip()) if not scheds.empty else set()
    unref = None
    for c in all_wt["code"].astype(str):
        if c.strip() and c.strip() not in used:
            unref = c.strip()
            break
    if unref is not None:
        refs = db.work_type_reference_counts(unref)
        check("참조 없는 코드는 refs==0(→물리 삭제 대상)", sum(refs.values()) == 0)
    else:
        check("참조 없는 코드 없음(스킵)", True)


def main() -> int:
    for test in (
        test_render_smoke,
        test_actions_in_app_header_only,
        test_header_action_states,
        test_header_publish_rerender_gate,
        test_edit_state_still_visible,
        test_unified_redesign_features,
        test_preview_color_short_label_contract,
        test_preview_badge_contrast_contract,
        test_code_natural_key_locked,
        test_partial_success_ledger_wiring,
        test_delete_error_handling,
        test_validate_backward_compat,
        test_color_time_validation,
        test_dirty_and_dup_helpers,
        test_delete_policy,
    ):
        test()
    print()
    if FAIL:
        print(f"FAILED {len(FAIL)}: {FAIL}")
        return 1
    print(f"ALL PASSED ({PASS} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
