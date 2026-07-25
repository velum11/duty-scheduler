"""views/master 공통 기반 패키지(Phase4 Lane A) 단위 테스트.

세션 비의존 순수 로직은 직접 호출로, DraftState 의 세션 상태·dirty 정책은
Streamlit AppTest 로 검증한다. 브라우저(paste/IME/실제 AgGrid 이벤트)는 이 스크립트
범위 밖이며 통합/수동 검증 대상이다(design-contract §24).

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_master_common.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from views.master import actions, grid, lifecycle, state, style  # noqa: E402
from views.master.lifecycle import PersistResult, ReadinessState, run_save  # noqa: E402

_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "OK " if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)


# ---------------------------------------------------------------------------
# 1) grid_bool / live_rows
# ---------------------------------------------------------------------------
def test_grid_bool():
    check("grid_bool 텍스트 진리값", grid.grid_bool("사용") and grid.grid_bool("TRUE")
          and grid.grid_bool("1") and not grid.grid_bool("false") and not grid.grid_bool(""))
    check("grid_bool 파이썬 값", grid.grid_bool(1) and not grid.grid_bool(0)
          and grid.grid_bool(True) and not grid.grid_bool(None))


def test_live_rows():
    df = pd.DataFrame({"_row_id": ["a", "b", "c"], "_removed": ["", "1", ""]})
    live = grid.live_rows(df)
    check("live_rows 제거행 제외", list(live["_row_id"]) == ["a", "c"])
    df2 = pd.DataFrame({"_row_id": ["a"]})  # _removed 없음
    check("live_rows _removed 없으면 원본", len(grid.live_rows(df2)) == 1)


# ---------------------------------------------------------------------------
# 2) prepare_frame / normalize_result (메타 보정·정규화)
# ---------------------------------------------------------------------------
def test_prepare_frame():
    spec = grid.MasterGridSpec(page_id="t", columns={"명칭": "text", "사용": "bool"},
                               order=["명칭", "사용"])
    src = pd.DataFrame({"_row_id": ["e:1"], "_row_state": ["existing"],
                        "명칭": ["가"], "사용": ["사용"], "_removed": ["1"]})
    p = grid.prepare_frame(spec, src)
    check("prepare 메타 컬럼 모두 존재", all(c in p.columns for c in grid.META_COLUMNS))
    check("prepare _removed 초기화", list(p["_removed"]) == [""])
    check("prepare bool 정규화", p["사용"].iloc[0] is True or p["사용"].iloc[0] == True)  # noqa: E712
    check("prepare 누락 데이터컬럼 생성", "_action" in p.columns)
    # 누락 데이터 컬럼 자동 생성
    spec2 = grid.MasterGridSpec(page_id="t", columns={"명칭": "text", "코드": "text"},
                                order=["명칭", "코드"])
    p2 = grid.prepare_frame(spec2, pd.DataFrame({"명칭": ["x"]}))
    check("prepare 없는 컬럼 빈값 생성", "코드" in p2.columns and p2["코드"].iloc[0] == "")


def test_normalize_result():
    spec = grid.MasterGridSpec(page_id="t", columns={"명칭": "text", "사용": "bool"},
                               order=["명칭", "사용"])
    raw = pd.DataFrame({"명칭": [None], "사용": ["true"], "_row_id": [None],
                        "_row_state": ["existing"], "_sel": ["true"]})
    n = grid.normalize_result(spec, raw)
    check("normalize text NaN→''", n["명칭"].iloc[0] == "")
    check("normalize bool", bool(n["사용"].iloc[0]) is True)
    check("normalize _sel bool", bool(n["_sel"].iloc[0]) is True)
    check("normalize 메타 문자열", isinstance(n["_row_id"].iloc[0], str))
    check("normalize None 입력 방어", grid.normalize_result(spec, None) is None)


# ---------------------------------------------------------------------------
# 3) 상태 시각 규칙 — 상호 배타 우선순위
# ---------------------------------------------------------------------------
def test_row_class_rules():
    rules = style.master_row_class_rules(include_group=True, include_linked=True)
    # error 는 최상위라 상위 우선순위 가드(&& !(...))가 없다
    check("error 규칙 무가드", "&& !(" not in rules["ms-row-error"])
    # delete 는 error 를 배제
    check("delete 가 error 배제", "!(data._error" in rules["ms-row-delete"])
    # selected 는 error/delete/new/inactive 4개를 배제(가장 하위)
    negs = rules["ms-row-selected"].count("!(")
    check("selected 가 상위 4개 배제", negs == 4, f"negations={negs}")
    # group 은 독립 규칙
    check("group 독립 규칙", rules["ms-group-row"] == "data._row_state === 'group'")


def test_cell_rules():
    er = style.cell_error_rule("부서")
    check("cell_error_rule 필드 매칭", '"부서"' in er["ms-cell-error"])
    dr = style.cell_dirty_rule("명칭")
    check("cell_dirty_rule 필드 매칭", '"명칭"' in dr["ms-cell-dirty"])
    check("SELECT_CELL_RULE 상수", style.SELECT_CELL_RULE == {"ms-cell-select": "true"})


def test_badges_banners():
    check("chip 텍스트 이스케이프", "&lt;" in style.chip_html("<x>", "new"))
    check("mode 배지 샘플 중립", "samp" in style.mode_badge_html(connected=None, sample=True))
    check("mode 배지 연결 success", "on" in style.mode_badge_html(connected=True, sample=False))
    check("mode 배지 오류 danger", "off" in style.mode_badge_html(connected=False, sample=False))
    check("readiness 배지 3-state",
          "ready" in style.readiness_badge_html("READY")
          and "err" in style.readiness_badge_html("PROBE_ERROR")
          and "not" in style.readiness_badge_html("NOT_READY"))


# ---------------------------------------------------------------------------
# 4) PersistResult / run_save 프로토콜
# ---------------------------------------------------------------------------
def test_persist_result():
    ok = PersistResult.success("t", ["a", "b"])
    check("success ok=True partial=False", ok.ok and not ok.partial)
    part = PersistResult(page_id="t", succeeded_keys=["a"], failed_keys=["b"], error="e")
    check("부분성공 partial=True ok=False", part.partial and not part.ok)
    unk = PersistResult.unresolved("t", "network")
    check("불명 ok=False unknown=True", (not unk.ok) and unk.unknown)
    check("operation_id 부여", bool(ok.operation_id))


def test_run_save():
    st_ = state.DraftState("t")

    # (a) 검증 실패 → persist 미호출, draft 유지
    called = {"persist": False}
    def persist(m, r):
        called["persist"] = True
        return PersistResult.success("t", ["x"])
    out = run_save(st_, validate=lambda: ([], ["필수값 오류"]),
                   build_candidate=lambda r: (None, []), persist=persist)
    check("run_save invalid → persist 미호출", out.status == "invalid" and not called["persist"])

    # (b) build 단계 오류
    out = run_save(st_, validate=lambda: ([{"code": "A"}], []),
                   build_candidate=lambda r: (None, ["중복"]), persist=persist)
    check("run_save build 오류", out.status == "invalid" and not called["persist"])

    # (c) 성공
    out = run_save(st_, validate=lambda: ([{"code": "A"}], []),
                   build_candidate=lambda r: ("MERGED", []),
                   persist=lambda m, r: PersistResult.success("t", ["A"]))
    check("run_save saved + should_reload", out.status == "saved" and out.should_reload)

    # (d) 부분 성공 → reload 안 함
    out = run_save(st_, validate=lambda: ([{"code": "A"}], []),
                   build_candidate=lambda r: ("MERGED", []),
                   persist=lambda m, r: PersistResult(page_id="t", succeeded_keys=["A"], failed_keys=["B"]))
    check("run_save partial → reload 금지", out.status == "partial" and not out.should_reload)

    # (e) 예외 → 불명(draft 보존)
    def boom(m, r):
        raise RuntimeError("timeout")
    out = run_save(st_, validate=lambda: ([{"code": "A"}], []),
                   build_candidate=lambda r: ("MERGED", []), persist=boom)
    check("run_save 예외 → unknown", out.status == "unknown" and out.result.unknown)


def test_readiness():
    check("READY write 활성", ReadinessState.ready().write_enabled)
    nr = ReadinessState.from_ready_flag(False)
    check("NOT_READY write 비활성·원장 금지", (not nr.write_enabled) and (not nr.show_ledger))
    pe = ReadinessState.probe_error()
    check("PROBE_ERROR write 비활성", (not pe.write_enabled) and pe.state.value == "PROBE_ERROR")
    check("from_ready_flag True→READY", ReadinessState.from_ready_flag(True).write_enabled)


# ---------------------------------------------------------------------------
# 5) DraftState key factory (순수 문자열) + actions 공식
# ---------------------------------------------------------------------------
def test_key_factory():
    s = state.DraftState("master_users")
    check("query_key", s.query_key == "master_users:query")
    check("rows_key", s.rows_key == "master_users:rows")
    check("action_key page-scoped", s.action_key("save") == "master_users:action:save")
    check("flash_key 네임스페이스", s.flash_key == "flash:master_users")
    # 화면 간 격리: 다른 page_id 는 절대 같은 key 를 만들지 않는다
    other = state.DraftState("master_work_types")
    check("page 격리(save flag 충돌 없음)",
          s.action_key("save") != other.action_key("save"))


def test_dirty_total():
    check("dirty_total 공식", actions.dirty_total(2, 3) == 5)
    check("dirty_total 0", actions.dirty_total(0, 0) == 0)


# ---------------------------------------------------------------------------
# 6) 세션·dirty 정책 (AppTest)
# ---------------------------------------------------------------------------
_APP = r'''
import streamlit as st
from views.master import state, actions

s = state.DraftState("pg")
mode = st.session_state.get("_mode")

if mode == "resolve":
    # 최초 진입: rows 없음 → RELOAD
    st.session_state["r_first"] = s.resolve_reload({"q": 1}, refresh=False, dirty=False)
    s.set_rows("ROWS")  # 이후엔 rows 존재
    # 조건 동일 → KEEP
    st.session_state["r_same"] = s.resolve_reload({"q": 1}, refresh=False, dirty=False)
    # 조건 변경 + dirty 아님 → RELOAD
    st.session_state["r_reload"] = s.resolve_reload({"q": 2}, refresh=False, dirty=False)
    # 조건 변경 + dirty → CONFIRM (pending 보관, draft 유지)
    st.session_state["r_confirm"] = s.resolve_reload({"q": 3}, refresh=False, dirty=True)
    st.session_state["has_pending"] = s.has_pending_reload()

elif mode == "discard":
    s.set_rows("ROWS")
    s.resolve_reload({"q": 9}, refresh=False, dirty=True)   # → pending
    applied = s.apply_pending_reload()
    st.session_state["applied"] = applied
    st.session_state["dirty_after"] = s.is_dirty()
    st.session_state["pending_after"] = s.has_pending_reload()

elif mode == "cancel":
    s.set_rows("ROWS")
    s.resolve_reload({"q": 9}, refresh=False, dirty=True)
    s.cancel_pending_reload()
    st.session_state["pending_after"] = s.has_pending_reload()

elif mode == "actions":
    s.request_action("save")
    st.session_state["took_save"] = s.take_action("save")
    st.session_state["took_again"] = s.take_action("save")  # 두 번째는 False(누수 없음)
    st.session_state["rid1"] = s.next_rid()
    st.session_state["rid2"] = s.next_rid()
    n0 = s.nonce(); s.bump_nonce()
    st.session_state["nonce_bumped"] = s.nonce() == n0 + 1
    s.set_flash("success", "저장됨")
    st.session_state["flash"] = s.pop_flash()
    st.session_state["flash2"] = s.pop_flash()  # 두 번째는 None

elif mode == "bar_readonly":
    # can_write=False → 행 추가·삭제·저장 모두 비활성, 새로고침만 활성(조회 허용)
    actions.master_action_bar(s, sel_count=2, dirty_total=3, can_write=False,
                              write_disabled_reason="migration 004 적용 전 — 조회만 가능합니다.")

elif mode == "bar_ready":
    # can_write=True(기본) → dirty·선택 있으면 add/delete/save 활성
    actions.master_action_bar(s, sel_count=2, dirty_total=3)

elif mode == "bar_ready_nodirty":
    # 쓰기 가능하지만 선택 0·변경 0 → 삭제/저장만 비활성, 행 추가·새로고침 활성
    actions.master_action_bar(s, sel_count=0, dirty_total=0)

elif mode == "bar_busy":
    # busy → 모든 write control 비활성, 새로고침도 비활성
    actions.master_action_bar(s, sel_count=2, dirty_total=3, busy=True)
'''


def test_session_apptest():
    try:
        from streamlit.testing.v1 import AppTest
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] AppTest 미가용 — 세션 테스트 생략: {exc}")
        return

    def run(mode):
        at = AppTest.from_string(_APP)
        at.session_state["_mode"] = mode
        at.run(timeout=30)
        if at.exception:
            raise AssertionError(f"AppTest 예외({mode}): {at.exception}")
        return at

    at = run("resolve")
    check("resolve 최초 RELOAD", at.session_state["r_first"] == state.RELOAD)
    check("resolve 동일조건 KEEP", at.session_state["r_same"] == state.KEEP)
    check("resolve 변경+clean RELOAD", at.session_state["r_reload"] == state.RELOAD)
    check("resolve 변경+dirty CONFIRM", at.session_state["r_confirm"] == state.CONFIRM)
    check("resolve dirty 시 pending 보관(draft 유지)", at.session_state["has_pending"] is True)

    at = run("discard")
    check("discard 후 pending 적용", at.session_state["applied"] == {"q": 9})
    check("discard 후 dirty 해제", at.session_state["dirty_after"] is False)
    check("discard 후 pending 소진", at.session_state["pending_after"] is False)

    at = run("cancel")
    check("cancel 후 pending 소진(draft 유지)", at.session_state["pending_after"] is False)

    at = run("actions")
    check("action flag 소비", at.session_state["took_save"] is True)
    check("action flag 재소비 시 False(누수 없음)", at.session_state["took_again"] is False)
    check("next_rid 단조 증가", at.session_state["rid1"] == "n:1" and at.session_state["rid2"] == "n:2")
    check("bump_nonce 증가", at.session_state["nonce_bumped"] is True)
    check("flash 1회 표시", at.session_state["flash"] == ("success", "저장됨"))
    check("flash 재조회 None", at.session_state["flash2"] is None)

    # --- master_action_bar write 비활성(§25 all write controls disabled) ---
    def disabled_map(at):
        out = {}
        for b in at.button:
            out[getattr(b, "key", None)] = bool(getattr(b, "disabled", False))
        return out

    d = disabled_map(run("bar_readonly"))
    check("can_write=False → 행 추가 비활성", d.get("pg__add") is True)
    check("can_write=False → 삭제 비활성", d.get("pg__delete") is True)
    check("can_write=False → 저장 비활성", d.get("pg__save") is True)
    check("can_write=False → 새로고침은 활성(조회 허용)", d.get("pg__refresh") is False)

    d = disabled_map(run("bar_ready"))
    check("can_write=True dirty·선택 → 행 추가 활성", d.get("pg__add") is False)
    check("can_write=True 선택 있음 → 삭제 활성", d.get("pg__delete") is False)
    check("can_write=True dirty → 저장 활성", d.get("pg__save") is False)

    d = disabled_map(run("bar_ready_nodirty"))
    check("쓰기 가능·선택0 → 행 추가 활성(후방호환)", d.get("pg__add") is False)
    check("선택0 → 삭제 비활성", d.get("pg__delete") is True)
    check("변경0 → 저장 비활성", d.get("pg__save") is True)

    d = disabled_map(run("bar_busy"))
    check("busy → 행 추가·삭제·저장 비활성", d.get("pg__add") and d.get("pg__delete") and d.get("pg__save"))
    check("busy → 새로고침도 비활성", d.get("pg__refresh") is True)


def main():
    test_grid_bool()
    test_live_rows()
    test_prepare_frame()
    test_normalize_result()
    test_row_class_rules()
    test_cell_rules()
    test_badges_banners()
    test_persist_result()
    test_run_save()
    test_readiness()
    test_key_factory()
    test_dirty_total()
    test_session_apptest()

    print("-" * 60)
    if _failures:
        print(f"FAILED {len(_failures)}건: " + ", ".join(_failures))
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
