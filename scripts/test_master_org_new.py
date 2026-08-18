"""조직 관리(master_org) 부서 단일 시트 focused UI 계약 테스트.

2026-08-07 사용자 결정: 그룹·조(운영단위) 시트를 화면에서 폐지하고 부서 단일 시트에
대분류/중분류 텍스트 2단(009)을 둔다. 이 파일은 그 **단일 시트 UI 계약**을 검증한다:

- 공통 기반(``views/master``) 위에 재구현: DraftState/MasterGridSpec/render_master_grid/
  run_save/ReadinessState/master_action_bar/ledger_banner/sheet_head 를 실제로 사용하는가.
- **액션 진입점은 상단 52px 헤더 아이콘 하나**(2026-08-14 사용자 지시 · DESIGN §0-3):
  화면 안 액션 버튼(``org_dept__add/delete/save/refresh``)은 렌더되지 않고, 활성/음영·
  사유는 종전과 같은 규칙(page_action_specs)으로 헤더에 발행된다
  (``modules.ui.publish_header_actions`` → ``hdr_state:master_org``).
- page-scoped 부서 시트 상태(org_dept) — 공용 ``ms_*`` action key 누수 없음.
- 그룹/조 시트가 렌더되지 않는다(버튼 키·시트 제목 부재). 보존된 그룹/조 시트
  함수·CSS 는 소스에 남아 있을 수 있다(라우팅되지 않음 — 데이터·테이블은 보존).
- migration readiness 3-state: NOT_READY 면 부서 시트 write 비활성 + 조회 전용 배너.
- dirty_total 공식(신규+기존변경)·필터 전환 폐기 게이트(draft 보존/폐기).
- 부분성공 원장(save_*_report → to_persist_kwargs) + 삭제 예외 처리.

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
from modules import ui as app_ui  # noqa: E402
from views import master_org  # noqa: E402
from views import master as master_pkg  # noqa: E402

PASS = 0
FAIL: list[str] = []

#: 화면이 상단 52px 헤더 아이콘에 발행하는 세션 키(modules.ui.publish_header_actions).
_HDR_KEY = app_ui._HDR_STATE_PREFIX + "master_org"


def _hdr(app_test) -> dict:
    """발행된 헤더 아이콘 상태 ``{role: (disabled, help)}``. 미발행이면 빈 dict."""
    if _HDR_KEY not in app_test.session_state:
        return {}
    return dict(app_test.session_state[_HDR_KEY])


def _sess(app_test, key, default=None):
    """AppTest session_state 는 ``.get`` 을 노출하지 않는다 — 존재 확인 후 읽는다."""
    return app_test.session_state[key] if key in app_test.session_state else default


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


# ===== 2) 화면 렌더 — 공통 크롬·부서 단일 시트 =====
print("화면 렌더 — 공통 크롬·부서 단일 시트(그룹/조 시트 미렌더)")


def _screen_render():
    from modules import db as app_db
    from views import master_org as mo
    mo.render(app_db.find_user_by_emp_no("1001"))


at = AppTest.from_function(_screen_render, default_timeout=45).run()
check("렌더 예외 없음", not at.exception)
body = " ".join(str(m.value) for m in at.markdown)
check("페이지 제목(조직 관리) 표시", "조직 관리" in body)
check("부서 시트 제목", "<span class='t'>부서</span>" in body)
check("그룹 시트 미렌더(단일 시트)", "<span class='t'>그룹</span>" not in body)
check("조 시트 미렌더(단일 시트)", "<span class='t'>조</span>" not in body)
check("공통 헤더 크롬(ms-head/ms-title)", "ms-head" in body and "ms-title" in body)
check("공통 시트 헤더(ms-sheet-head) 존재", "ms-sheet-head" in body)
# 연결 상태 pill 은 상단 52px 셸 헤더(modules/ui.py)가 소유(ADOPTION_SPEC 항목4·§0.4).
# 본문 크롬은 제목/설명만 — 본문에서 연결 pill 을 중복 렌더하지 않는다.
check("본문에 연결 pill 렌더 없음(상단 헤더 소유)",
      "샘플 데이터" not in body and "Supabase 연결" not in body)
check("상태 스트립(ms-count)", "ms-count" in body)
keys = {b.key for b in at.button}
for k in ("org_dept__save", "org_dept__add", "org_dept__delete", "org_dept__refresh"):
    check(f"인페이지 액션 버튼 부재(진입점=상단 헤더 아이콘): {k}", k not in keys)
for k in ("org_group__save", "org_group__add", "org_unit__save", "org_unit__add"):
    check(f"폐지 시트 버튼 키 부재: {k}", k not in keys)
check("인페이지 액션바 컨테이너 미렌더(__bar)", "org_dept__bar" not in body)


def _save_button(app_test, key):
    for b in app_test.button:
        if b.key == key:
            return b
    return None


# ===== 2a) 액션 진입점 = 상단 52px 헤더 아이콘 4종(발행 상태로 검증) =====
# 헤더 아이콘 자체는 앱 셸(modules/ui.py)이 그리므로 화면 계약은 "무엇을 발행했는가"다.
print("액션 진입점 — 상단 헤더 아이콘 4종 발행(활성/음영/사유)")
hdr0 = _hdr(at)
check("헤더에 4종(add/delete/save/refresh) 발행",
      set(hdr0) == {"add", "delete", "save", "refresh"})
check("갓 로드: 추가 활성", hdr0.get("add", (True, None))[0] is False)
check("갓 로드: 새로고침 활성", hdr0.get("refresh", (True, None))[0] is False)
check("갓 로드: 저장 음영 + 사유(변경 없음)",
      hdr0.get("save", (False, None))[0] is True
      and "저장할 변경이 없습니다" in (hdr0.get("save", (False, ""))[1] or ""))
check("갓 로드: 삭제 음영 + 사유(선택 없음)",
      hdr0.get("delete", (False, None))[0] is True
      and "선택" in (hdr0.get("delete", (False, ""))[1] or ""))
check("발행 규칙은 인페이지와 같은 순수 계산(page_action_specs) 재사용",
      "page_action_specs(" in src and "_publish_header_actions(" in src)
# 헤더는 본문보다 먼저 그려진다 → 발행 지문이 바뀐 런만 1회 따라잡기 재실행(루프 금지).
check("헤더 따라잡기 지문 보관", master_org._HDR_FINGERPRINT_KEY in at.session_state)
check("따라잡기 재실행 플래그는 소비돼 남지 않음(루프 없음)",
      not _sess(at, master_org._HDR_RESYNC_KEY, False))


# ===== 2b) 단일 시트 — 드릴다운·상위 잠금 제거 =====
print("단일 시트 — 드릴다운 상위 선택 제거 + 잠금 없이 즉시 편집 가능")
sb_keys = {s.key for s in at.selectbox}
check("상단 그룹 선택 selectbox 없음", "og_group" not in sb_keys and "og_group_empty" not in sb_keys)
check("상단 부서 선택 selectbox 없음", "og_dept" not in sb_keys and "og_dept_empty" not in sb_keys)
check("사용 여부 필터 selectbox 는 유지", "og_active" in sb_keys)
# 문구 부재 검사는 공통 style CSS 주석에 같은 문구가 있어 오탐한다 — 렌더된 잠금
# 컴포넌트의 실제 HTML 마커(class='ms-locked')로 검사한다.
check("잠금 시트 렌더 없음(sheet_locked HTML 부재)", "class='ms-locked'" not in body)
check("부서 시트는 갓 로드에도 편집 가능(헤더 추가 아이콘 활성)",
      _hdr(at).get("add", (True, None))[0] is False)
check("부서 시트에 대분류/중분류 편집 칼럼(009) 계약",
      master_org._DEPT_COLS[:2] == ["대분류", "중분류"])


# ===== 2c) 상태별 헤더 아이콘 — 선택 1건 · 미저장 1건 =====
# 인페이지 버튼이 사라진 뒤에도 "선택/미저장 → 삭제·저장 활성"이 종전과 같아야 한다.
# AppTest 에서 그리드 컴포넌트는 입력 프레임을 그대로 돌려주므로, 세션 rows 로 선택·
# 편집 상태를 만들면 실제 렌더 경로(page_action_specs)를 그대로 통과한다.
print("상태별 헤더 아이콘 — 선택 1건·미저장 1건 → 삭제·저장 활성 + 상태 칩")


def _state_probe():
    import streamlit as st
    from modules import db as adb
    from views import master_org as mo
    # 화면 기본 필터(사용 여부=사용 중)와 같은 params 로 적재·commit 해야 render 가
    # 재적재하지 않고 이 draft 를 그대로 그린다.
    _q = {"active": "사용 중", "search": ""}
    if not st.session_state.get("_ssetup"):
        st.session_state["_ssetup"] = True
        mo._load_depts(_q)
        rows = mo._OD.get_rows().copy()
        rows.loc[rows.index[0], "코드명"] = "편집됨ABC"  # 기존 변경 1건
        rows.loc[rows.index[0], "_sel"] = True           # 선택 1건
        mo._OD.set_rows(rows)
        mo._OD.set_dirty(True)
        mo._OD.commit_query(_q)
    mo.render(adb.find_user_by_emp_no("1001"))


at_s = AppTest.from_function(_state_probe, default_timeout=45).run()
check("상태 probe 렌더 예외 없음", not at_s.exception)
s_body = " ".join(str(m.value) for m in at_s.markdown)
hdr_s = _hdr(at_s)
check("미저장 1건 → 헤더 저장 활성", hdr_s.get("save", (True, None))[0] is False)
check("선택 1건 → 헤더 삭제 활성", hdr_s.get("delete", (True, None))[0] is False)
check("추가·새로고침은 계속 활성",
      hdr_s.get("add", (True, None))[0] is False and hdr_s.get("refresh", (True, None))[0] is False)
check("표 위 상태 칩에 미저장 건수 표기(저장 badge 승계)", "미저장 1건" in s_body)
check("표 위 상태 칩에 선택 건수 표기", "선택 1건" in s_body)
check("표 아래 상태 스트립도 종전대로 유지(총/기존 변경/선택)",
      "ms-count" in s_body and "기존 변경" in s_body)
check("헤더 따라잡기 후 재실행 플래그 잔류 없음",
      not _sess(at_s, master_org._HDR_RESYNC_KEY, False))


# ===== 2d) 결과 배너가 헤더 따라잡기 재실행에 삼켜지지 않는다 =====
# 저장/삭제 결과 flash 는 1회성이라, 헤더 상태가 바뀐 런(=따라잡기 재실행 예정)에서
# 소비하면 화면에 남지 않는다. 실측으로 잡은 회귀라 계약으로 고정한다.
print("결과 배너 유실 방지 — flash 는 재실행 예정 런에서 소비하지 않는다")


def _flash_probe():
    import streamlit as st
    from modules import db as adb
    from views import master_org as mo
    if not st.session_state.get("_fsetup"):
        st.session_state["_fsetup"] = True
        mo._OD.set_flash("success", "부서를 저장했습니다. (신규 0 · 수정 1)")
    mo.render(adb.find_user_by_emp_no("1001"))


at_f = AppTest.from_function(_flash_probe, default_timeout=45).run()
check("flash probe 렌더 예외 없음", not at_f.exception)
f_body = " ".join(str(m.value) for m in at_f.markdown)
check("저장 결과 flash 가 화면에 남는다(따라잡기 재실행에도 유실 없음)",
      "부서를 저장했습니다" in f_body)
check("flash 는 표시 후 소비(중복 표시 없음)", master_org._OD.flash_key not in at_f.session_state)
check("flash 는 배너 슬롯에서 렌더(1회성 상태 소비 가드)",
      "if not resync:" in src and "show_flash(_OD)" in src)


# ===== 3) migration readiness 3-state =====
print("readiness 3-state — 세 시트 write 전부 비활성 + 상태별 배너/배지 + 재확인")
check("_readiness 가 3-state db.org_schema_readiness() 를 사용", "org_schema_readiness" in src)
check("PROBE_ERROR 시 reset_org_schema_cache 재probe 동작", "reset_org_schema_cache" in src)


def _hdr_disabled(app_test, roles) -> bool:
    """발행된 헤더 아이콘 상태에서 ``roles`` 가 전부 음영인가."""
    states = _hdr(app_test)
    for r in roles:
        if r not in states or not states[r][0]:
            return False
    return True


def _hdr_reason(app_test, role) -> str:
    return (_hdr(app_test).get(role, (False, "")) or (False, ""))[1] or ""


# 2026-08-07 단일 시트 · 2026-08-14 헤더 단일 진입점: write 게이트 대상은 헤더 3아이콘이다.
_WRITE_KEYS = ("add", "delete", "save")
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
    check("NOT_READY 헤더 write 아이콘(추가·삭제·저장) 전부 음영",
          _hdr_disabled(at_nr, _WRITE_KEYS))
    check("NOT_READY 음영 사유 = readiness 메시지(툴팁 동일 문구)",
          all(master_org._NOT_READY_MSG in _hdr_reason(at_nr, r) for r in _WRITE_KEYS))
    check("NOT_READY 에도 새로고침(조회)은 활성",
          not _hdr_disabled(at_nr, ("refresh",)))

    db.org_schema_readiness = lambda: db.READINESS_PROBE_ERROR
    at_pe = AppTest.from_function(_screen_render, default_timeout=45).run()
    check("PROBE_ERROR 렌더 예외 없음", not at_pe.exception)
    pe_body = " ".join(str(m.value) for m in at_pe.markdown)
    check("PROBE_ERROR 상태 확인 실패 배너/배지", "확인 실패" in pe_body)
    check("PROBE_ERROR 재확인 버튼 노출", any(b.key == "org__recheck" for b in at_pe.button))
    check("PROBE_ERROR 헤더 write 아이콘 전부 음영", _hdr_disabled(at_pe, _WRITE_KEYS))
    check("PROBE_ERROR 음영 사유 = 확인 실패 메시지",
          all("확인" in _hdr_reason(at_pe, r) for r in _WRITE_KEYS))
    check("PROBE_ERROR 에도 새로고침(조회)은 활성", not _hdr_disabled(at_pe, ("refresh",)))
finally:
    db.org_schema_readiness = _orig_readiness

check("sample 모드는 READY(write 가능)", master_org._readiness().write_enabled)


# ===== 3b) 그룹 0개에도 부서 시트는 잠기지 않는다(단일 시트 — 상위 선택 없음) =====
print("그룹 0개 → 부서 시트 잠금 없음(단일 시트)")
_orig_groups = db.get_org_groups
try:
    db.get_org_groups = lambda *a, **k: db._typed_empty_frame(db.ORG_GROUP_COLUMNS)
    at_lock = AppTest.from_function(_screen_render, default_timeout=45).run()
    check("그룹 0개 렌더 예외 없음", not at_lock.exception)
    lock_body = " ".join(str(m.value) for m in at_lock.markdown)
    check("그룹 0개에도 잠금 렌더 없음", "class='ms-locked'" not in lock_body)
    check("그룹 0개에도 부서 write 활성(단일 시트 — 그룹 의존 없음)",
          not _hdr_disabled(at_lock, ("add",)))
finally:
    db.get_org_groups = _orig_groups


# ===== 3c) 반응형/nowrap + 시트 카드 컨테이너 =====
print("반응형 시트 스택(공통) + 시트 안 버튼 nowrap + 시트 카드 컨테이너")
check("부서 시트 카드 컨테이너 키(org_dept__sheet)", "org_dept__sheet" in src)
check("시트 안 버튼 white-space:nowrap(확인 바 라벨 눌림 방지)", "white-space:nowrap" in src)


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
# 표 위 슬롯(placeholder) 통일 / 필터결과 요약 상단 통일(사용자 관리와 동일) /
# ▸ 열림 중복칩 제거(행 강조로 충분) / 최소 열폭 축소로 1366·1280px 3열 적합.
print("Codex 2차 — 표 위 슬롯·필터결과 요약·중복칩 제거·열폭 축소")
# 2026-08-14: 부서(라우팅) 시트의 표 위 슬롯은 액션바가 아니라 **상태 칩 줄**이다
# (액션=상단 헤더 아이콘 단일 진입점). 미라우팅 보존 시트(그룹·조)만 bar_slot 을 갖는다.
check("부서 시트 표 위 슬롯 = 상태 칩(chips_slot), 액션바 아님",
      "chips_slot = st.container()" in src and "with chips_slot:" in src
      and src.count("bar_slot = st.container()") == 2
      and src.count("with bar_slot, st.container") == 2)
check("필터/스코프 결과 요약 상단 통일(_summary_chips + chip_html, 3시트)",
      "chip_html" in src and src.count("_summary_chips(rows, params") == 3)
check("인페이지 액션바가 들고 있던 상태 신호를 칩으로 승계(미저장·선택)",
      "미저장 {int(dirty)}건" in src and "선택 {int(sel)}건" in src)
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
# 라이브 부서 시트 8열은 폭을 flex(=남은 자리)가 아니라 값의 실측 잉크폭에서 역산한다.
# flex 가 하나라도 살아 있으면 값이 없는 열이 다시 가장 넓어진다(2026-08-18 실측:
# 대분류 162 · 중분류 162 · 비고 180 이 전 행 빈 값이었다).
_dept_cfg = master_org._dept_col_config()
check("부서 시트 전 열이 고정폭 — flex 잔존 0 (남는 가로 폭은 어느 열도 흡수하지 않는다)",
      all(float(c.get("flex", 0)) == 0 for c in _dept_cfg.values()))
check("값이 폭을 구속하는 열(코드명)은 실측 최대 잉크 + 셀 패딩 이상",
      _dept_cfg["코드명"].get("width", 0) >= 132)
check("값 0건 열(대분류·중분류·비고)은 구 flex 렌더폭(162/162/180)보다 좁다",
      _dept_cfg["대분류"]["width"] < 162 and _dept_cfg["중분류"]["width"] < 162
      and _dept_cfg["비고"]["width"] < 180)
check("minWidth 는 헤더가 잘리지 않는 하한(헤더 잉크+16) 이상",
      _dept_cfg["대분류"]["minWidth"] >= 51 and _dept_cfg["중분류"]["minWidth"] >= 51
      and _dept_cfg["코드명"]["minWidth"] >= 51 and _dept_cfg["비고"]["minWidth"] >= 39)
check("액션바 keyed __bar 컨테이너는 미라우팅 보존 시트에만(부서는 액션바 없음)",
      src.count(".page_id}__bar\")") == 2)
check("표준 배너 순서 — 확인/폐기 배너를 표 위 슬롯 뒤 banner_slot 으로(3시트)",
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
    # baseline 튜플은 _DEPT_COLS 순서(대분류·중분류·코드·코드명·근태 등록 대상·순서·
    # 비고·사용)를 따른다 — 근태 등록 대상(011)은 코드명 뒤 다섯째 칸이다.
    _ATT = mo._ATTENDANCE_COL
    st.session_state[mo._OD.key("baseline")] = {
        "e:D1": ("", "", "D1", "PET생산부", "True", "1", "", "True"),
    }
    live = pd.DataFrame([
        {"_row_id": "e:D1", "_row_state": "existing", "_sel": False, "대분류": "", "중분류": "",
         "코드": "D1", "코드명": "PET생산부수정", _ATT: True,
         "순서": "1", "비고": "", "사용": True},                                          # 기존 변경 1
        {"_row_id": "e:D2", "_row_state": "existing", "_sel": False, "대분류": "", "중분류": "",
         "코드": "D2", "코드명": "원료실", _ATT: True,
         "순서": "2", "비고": "", "사용": True},                                          # 변경 없음(집계 제외)
        {"_row_id": "n:1", "_row_state": "new", "_sel": False, "대분류": "", "중분류": "",
         "코드": "NEW", "코드명": "새부서", _ATT: False,
         "순서": "3", "비고": "", "사용": True},                                          # 신규 1
    ])
    st.session_state[mo._OD.key("baseline")]["e:D2"] = ("", "", "D2", "원료실", "True", "2", "", "True")
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


# ===== 7) 필터 전환 폐기 게이트 — write 차단 + discard/취소 draft 처리 =====
# 단일 시트 전환(2026-08-07) 후 게이트의 트리거는 상위(그룹) 전환이 아니라 **필터
# 변경**이다: dirty draft 상태에서 필터를 바꾸면 폐기 확인 게이트가 열리고, 해소
# 전까지 write 가 비활성된다. discard=편집 폐기 후 재적재, 취소=draft 보존.
print("필터 전환 폐기 게이트 — write 차단 + discard/취소 draft 처리")


# 부서 draft 를 편집한 뒤 필터(사용 여부)를 바꾼 상태를 재현한다.
# (AppTest.from_function 은 대상 함수만 실행하므로 헬퍼 참조 대신 각 probe 에 인라인한다.)
def _gate_block_probe():
    import streamlit as st
    from modules import db as adb
    from views import master_org as mo
    if not st.session_state.get("_gsetup"):
        st.session_state["_gsetup"] = True
        mo._load_depts({"active": "전체", "search": ""})
        rows = mo._OD.get_rows().copy()
        rows.loc[rows.index[0], "코드명"] = "임시편집ABC"
        mo._OD.set_rows(rows); mo._OD.set_dirty(True)
        mo._OD.commit_query({"active": "전체", "search": ""})
        st.session_state["og_active"] = "사용 안 함"   # 필터 전환 → 폐기 게이트
    mo.render(adb.find_user_by_emp_no("1001"))


atb = AppTest.from_function(_gate_block_probe, default_timeout=45).run()
check("게이트 render 예외 없음", not atb.exception)
gbody = " ".join(str(m.value) for m in atb.markdown)
check("폐기 확인 게이트 표시", "저장되지 않은 변경" in gbody)
for r in _WRITE_KEYS:
    check(f"게이트중 헤더 {r} 아이콘 음영(유실 방지)", _hdr_disabled(atb, (r,)))
check("게이트중 음영 사유 = 안내 처리 요구", "먼저 처리" in _hdr_reason(atb, "save"))
check("게이트중에도 새로고침(조회)은 유지", not _hdr_disabled(atb, ("refresh",)))
check("게이트 배너 버튼(폐기/취소)은 화면 안에 유지",
      {"org_dept__discard_ok", "org_dept__discard_cancel"} <= {b.key for b in atb.button})


def _gate_discard_probe():
    import streamlit as st
    from modules import db as adb
    from views import master_org as mo
    if not st.session_state.get("_gsetup"):
        st.session_state["_gsetup"] = True
        mo._load_depts({"active": "전체", "search": ""})
        rows = mo._OD.get_rows().copy()
        rows.loc[rows.index[0], "코드명"] = "임시편집ABC"
        mo._OD.set_rows(rows); mo._OD.set_dirty(True)
        mo._OD.commit_query({"active": "전체", "search": ""})
        st.session_state["og_active"] = "사용 안 함"
    mo.render(adb.find_user_by_emp_no("1001"))


# discard(폐기하고 이동): 편집 폐기 → 새 필터로 재적재
atx = AppTest.from_function(_gate_discard_probe, default_timeout=45).run()
for b in atx.button:
    if b.key == "org_dept__discard_ok":
        b.click(); break
atx.run()
check("discard 후 render 예외 없음", not atx.exception)
rows_x = atx.session_state["org_dept:rows"] if "org_dept:rows" in atx.session_state else None
check("discard: 미저장 편집 폐기(재적재 행에 편집 없음)",
      rows_x is not None and "임시편집ABC" not in set(rows_x["코드명"].astype(str)))
check("discard: 폐기 게이트 해소(pending 제거)",
      master_org._OD.pending_query_key not in atx.session_state)


def _gate_cancel_probe():
    import streamlit as st
    from modules import db as adb
    from views import master_org as mo
    if not st.session_state.get("_gsetup"):
        st.session_state["_gsetup"] = True
        mo._load_depts({"active": "전체", "search": ""})
        rows = mo._OD.get_rows().copy()
        rows.loc[rows.index[0], "코드명"] = "임시편집ABC"
        mo._OD.set_rows(rows); mo._OD.set_dirty(True)
        mo._OD.commit_query({"active": "전체", "search": ""})
        st.session_state["og_active"] = "사용 안 함"
    mo.render(adb.find_user_by_emp_no("1001"))


# 취소(continue editing): draft 보존 + 저장은 발생하지 않음
atc = AppTest.from_function(_gate_cancel_probe, default_timeout=45).run()
for b in atc.button:
    if b.key == "org_dept__discard_cancel":
        b.click(); break
atc.run()
check("취소 후 render 예외 없음", not atc.exception)
rows_c = atc.session_state["org_dept:rows"] if "org_dept:rows" in atc.session_state else None
check("취소: 미저장 draft 보존(편집 유지)",
      rows_c is not None and "임시편집ABC" in set(rows_c["코드명"].astype(str)))


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


# ===== 9) 근태 등록 대상 지정 열(migration 011) =====
# 2026-08-14 사용자 지시: "조직 관리에 근태 등록하는 부서만 지정할 수 있게".
# 계약: (1) 보이는 편집 열이다(숨김 금지 — 왕복하지 않으면 저장이 지정을 못 싣는다),
# (2) `사용`(is_active)은 계속 마지막 열이고 지정 열은 코드명 뒤에 온다,
# (3) 신규 행 기본값은 미지정(False), (4) 저장 왕복에서 다른 컬럼이 소실되지 않는다.
print("근태 등록 대상(011) — 열 계약·기본값·저장 왕복·상태 칩")
_ATT = master_org._ATTENDANCE_COL
check("정본 용어 그대로 사용(requirements §6 · docs/database.md)", _ATT == "근태 등록 대상")
check("부서 시트에 보이는 데이터 열로 존재(숨김 컬럼 아님)", _ATT in master_org._DEPT_COLS)
check("열 위치: 코드명 다음", master_org._DEPT_COLS.index(_ATT) == master_org._DEPT_COLS.index("코드명") + 1)
check("`사용`(is_active)은 종전대로 마지막 열", master_org._DEPT_COLS[-1] == "사용")
check("타 컬럼 순서·구성 보존(대분류·중분류·코드·코드명 / 순서·비고·사용)",
      [c for c in master_org._DEPT_COLS if c != _ATT]
      == ["대분류", "중분류", "코드", "코드명", "순서", "비고", "사용"])
check("bool 열로 선언(native 체크박스 — JsCode 렌더러 미사용)",
      master_org._DEPT_GRID_COLUMNS.get(_ATT) == "bool" and "_BOOL_RENDERER" not in src)
check("행 컬럼 계약에도 반영(_DEPT_ROW_COLS)", _ATT in master_org._DEPT_ROW_COLS)
_att_cfg = master_org._dept_col_config()[_ATT]
check("헤더 잘림 방지 폭 + 내용 맞춤(체크박스라 flex 확장 없음)",
      _att_cfg.get("flex") == 0 and _att_cfg.get("minWidth", 0) >= 96)
check("체크박스 열 가운데 정렬(사용 열과 같은 어휘)", "md-c-center" in _att_cfg.get("cellClass", ""))
check("보호 행(ADMIN)은 지정도 편집 불가(사용 열과 같은 규칙)",
      _att_cfg.get("editable") is master_org._EDIT_UNLESS_PROTECTED)
check("지정 스키마 미준비면 읽기전용 어포던스로 내림",
      master_org._dept_col_config(attendance_editable=False)[_ATT].get("editable") is False
      and "ms-cell-readonly"
      in master_org._dept_col_config(attendance_editable=False)[_ATT].get("cellClass", ""))
check("화면 설명이 지정의 결과를 알린다(근무표 노출 범위)",
      "근태 등록 대상" in src and "근무표 편성·조회에 나타납니다" in src)

# 조회 → 편집 행 매핑(실제 bool) + 컬럼 없는 옛 프레임 폴백.
_att_rows = master_org.build_dept_rows(pd.DataFrame([
    {"dept_code": "D1", "dept_name": "PET생산부", "group_code": "PET", "major_category": "",
     "minor_category": "", "description": "", "sort_order": 1, "is_active": True,
     "tracks_attendance": True},
    {"dept_code": "D2", "dept_name": "관리팀", "group_code": "PET", "major_category": "",
     "minor_category": "", "description": "", "sort_order": 2, "is_active": True,
     "tracks_attendance": False},
]))
check("조회값이 편집 행으로 그대로 매핑(bool)",
      list(_att_rows[_ATT]) == [True, False])
check("지정 컬럼 없는 옛 프레임도 렌더 가능(미지정 폴백)",
      list(master_org.build_dept_rows(pd.DataFrame([
          {"dept_code": "D9", "dept_name": "옛계약", "group_code": "", "major_category": "",
           "minor_category": "", "description": "", "sort_order": 1, "is_active": True},
      ]))[_ATT]) == [False])

# 저장 레코드 계약 — 전 행이 명시값을 실어야 저장 계층이 반영한다(payload all 판정).
_att_recs, _ = master_org._validate_depts(pd.DataFrame([
    {"_row_id": "e:D1", "_row_state": "existing", "_sel": False, "대분류": "", "중분류": "",
     "코드": "D1", "코드명": "PET생산부", _ATT: True, "순서": "1", "비고": "", "사용": True},
    {"_row_id": "n:1", "_row_state": "new", "_sel": False, "대분류": "", "중분류": "",
     "코드": "D2", "코드명": "새부서", _ATT: False, "순서": "2", "비고": "", "사용": True},
]))
check("저장 레코드에 tracks_attendance 를 전 행 명시",
      all("tracks_attendance" in r for r in _att_recs)
      and [r["tracks_attendance"] for r in _att_recs] == [True, False])


def _new_row_probe():
    import streamlit as st
    from views import master_org as mo
    if st.session_state.get("_nr"):
        return
    st.session_state["_nr"] = True
    mo._load_depts({"active": "전체", "search": ""})
    grid = mo._OD.get_rows().copy()
    grid["_removed"] = ""
    try:
        mo._add_dept_row(grid)   # 내부에서 st.rerun()
    except BaseException:
        pass


at_nrow = AppTest.from_function(_new_row_probe, default_timeout=45).run()
_nrows = at_nrow.session_state["org_dept:rows"] if "org_dept:rows" in at_nrow.session_state else None
_new_only = _nrows[_nrows["_row_state"] == "new"] if _nrows is not None else None
check("신규 행 기본값 = 미지정(명시 지정 원칙)",
      _new_only is not None and len(_new_only) == 1
      and bool(_new_only.iloc[0][_ATT]) is False)
check("신규 행의 다른 기본값은 종전 그대로(사용=True)",
      _new_only is not None and bool(_new_only.iloc[0]["사용"]) is True)


# 저장 왕복(sample 세션 저장) — 지정 변경이 보존되고 다른 컬럼이 소실되지 않는다.
def _roundtrip_probe():
    import streamlit as st
    from modules import db as adb
    from views import master_org as mo
    _ATT = mo._ATTENDANCE_COL  # AppTest.from_function 은 대상 함수만 실행 — 전역 참조 금지
    if st.session_state.get("_rt_done"):
        return
    st.session_state["_rt_done"] = True
    q = {"active": "전체", "search": ""}
    mo._load_depts(q)
    before = adb.get_org_departments()
    st.session_state["_rt_before"] = {
        str(r["dept_code"]): (
            str(r["dept_name"]), str(r["major_category"]), str(r["minor_category"]),
            str(r["description"]), int(r["sort_order"]), bool(r["is_active"]),
            bool(r["tracks_attendance"]),
        ) for _, r in before.iterrows()
    }
    grid = mo._OD.get_rows().copy()
    grid["_removed"] = ""
    # 지정 상태를 뒤집는다: 대상(True) 하나 해제 + 비대상(False) 하나 지정.
    on = grid.index[grid[_ATT].map(bool)]
    off = grid.index[~grid[_ATT].map(bool)]
    st.session_state["_rt_flip"] = (str(grid.loc[on[0], "코드"]), str(grid.loc[off[0], "코드"]))
    grid.loc[on[0], _ATT] = False
    grid.loc[off[0], _ATT] = True
    try:
        mo._save_depts(grid, q)   # 성공 경로 끝에서 st.rerun()
    except BaseException:
        pass
    after = adb.get_org_departments()
    st.session_state["_rt_after"] = {
        str(r["dept_code"]): (
            str(r["dept_name"]), str(r["major_category"]), str(r["minor_category"]),
            str(r["description"]), int(r["sort_order"]), bool(r["is_active"]),
            bool(r["tracks_attendance"]),
        ) for _, r in after.iterrows()
    }
    st.session_state["_rt_codes"] = sorted(adb.attendance_dept_codes(is_active=None))


at_rt = AppTest.from_function(_roundtrip_probe, default_timeout=45).run()
check("저장 왕복 probe 예외 없음", not at_rt.exception)
_before = _sess(at_rt, "_rt_before", {})
_after = _sess(at_rt, "_rt_after", {})
_flip_on, _flip_off = _sess(at_rt, "_rt_flip", ("", ""))
check("재조회에서 해제가 보존", bool(_before) and _after.get(_flip_on, (None,) * 7)[6] is False)
check("재조회에서 신규 지정이 보존", _after.get(_flip_off, (None,) * 7)[6] is True)
check("지정을 바꾸지 않은 부서의 지정값 보존",
      all(_after[c][6] == _before[c][6] for c in _before if c not in (_flip_on, _flip_off)))
check("타 컬럼(코드명·대분류·중분류·비고·순서·사용) 소실 없음",
      set(_after) == set(_before) and all(_after[c][:6] == _before[c][:6] for c in _before))
check("db.attendance_dept_codes 가 지정 결과를 그대로 반영",
      _flip_off in _sess(at_rt, "_rt_codes", []) and _flip_on not in _sess(at_rt, "_rt_codes", []))


# 상태 칩 — 지정 건수(0이면 warn)·저장 전 해제 건수·지정 잠김 사유.
def _att_chip_probe():
    import pandas as pd
    import streamlit as st
    from views import master_org as mo
    _ATT = mo._ATTENDANCE_COL  # AppTest.from_function 은 대상 함수만 실행 — 전역 참조 금지
    rows = pd.DataFrame([
        {"_row_id": "e:D1", "_row_state": "existing", "_sel": False, "대분류": "", "중분류": "",
         "코드": "D1", "코드명": "가", _ATT: True, "순서": "1", "비고": "", "사용": True},
        {"_row_id": "e:D2", "_row_state": "existing", "_sel": False, "대분류": "", "중분류": "",
         "코드": "D2", "코드명": "나", _ATT: False, "순서": "2", "비고": "", "사용": True},
    ])
    st.write("A:")
    mo._summary_chips(rows, {"active": "전체", "search": ""})
    st.write("B:")
    zero = rows.copy(); zero[_ATT] = False
    mo._summary_chips(zero, {"active": "전체", "search": ""})
    st.write("C:")
    mo._summary_chips(rows, {"active": "전체", "search": ""}, dirty=1, untracked=2)
    st.write("D:")
    mo._summary_chips(rows, {"active": "전체", "search": ""}, attendance_locked=True)
    # 해제 건수 계산(기준선 True → 현재 False 인 기존 행만).
    st.session_state[mo._OD.key("baseline")] = {
        "e:D1": ("", "", "D1", "가", "True", "1", "", "True"),
        "e:D2": ("", "", "D2", "나", "False", "2", "", "True"),
    }
    live = rows.copy(); live.loc[0, _ATT] = False   # D1 해제, D2 는 원래 미지정
    st.write(f"UNTRACKED={mo._untracked_count(live)}")


at_ac = AppTest.from_function(_att_chip_probe, default_timeout=45).run()
check("칩 probe 예외 없음", not at_ac.exception)
_ac = " ".join(str(m.value) for m in at_ac.markdown)
check("지정 건수 칩(분포 칩과 같은 어휘·스코프)", f"{_ATT} 1</span>" in _ac)
check("지정 0건은 warn 톤으로 표면화(근무표 부서 목록이 비는 상태)",
      f"ms-chip warn'>{_ATT} 0</span>" in _ac)
check("저장 전 해제 건수 칩(미저장 칩 옆)", f"{_ATT} 해제 2건" in _ac)
check("지정 스키마 미준비 사유 칩(편집 불가)", f"{_ATT}: 지정 스키마 준비 전" in _ac)
check("해제 건수 = 기준선 지정 → 현재 미지정 기존 행", "UNTRACKED=1" in _ac)


# 배포·핫리로드 경계 — 지정 열이 없던 옛 draft 는 폐기하고 스토어에서 다시 읽는다.
def _stale_draft_probe():
    import streamlit as st
    from modules import db as adb
    from views import master_org as mo
    _ATT = mo._ATTENDANCE_COL  # AppTest.from_function 은 대상 함수만 실행 — 전역 참조 금지
    if not st.session_state.get("_sd"):
        st.session_state["_sd"] = True
        mo._load_depts({"active": "사용 중", "search": ""})
        old = mo._OD.get_rows().drop(columns=[_ATT])   # 옛 컬럼 계약 draft 재현
        mo._OD.set_rows(old)
        mo._OD.commit_query({"active": "사용 중", "search": ""})
    mo.render(adb.find_user_by_emp_no("1001"))


at_sd = AppTest.from_function(_stale_draft_probe, default_timeout=45).run()
check("옛 컬럼 계약 draft 에서도 렌더 예외 없음", not at_sd.exception)
_sd_rows = _sess(at_sd, "org_dept:rows")
check("옛 draft 는 폐기·재적재되어 지정 열을 되찾는다",
      _sd_rows is not None and _ATT in list(_sd_rows.columns))
check("재적재된 지정값이 스토어 값과 일치(전부 미지정으로 뒤집히지 않음)",
      _sd_rows is not None and bool(_sd_rows[_ATT].map(bool).any()))


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
