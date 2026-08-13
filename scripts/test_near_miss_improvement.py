"""아차사고 개선조치(CAPA, migration 007) 데이터 계약 단위 테스트.

Codex 2회 설계검수로 확정된 007 계약(엄격 1:1·통제코드·자기확인 금지·확인+종결 하드
게이트·강등방어·재개 초기화·직접 CLOSED 차단)의 회귀 방지용. 원격 write 없이 sample 모드
+ 순수 mock 으로만 파사드/리포지토리 계약을 검증한다(SQL 은 정적 계약만 확인, 미실행).

실행: PYTHONUTF8=1 DUTY_DATA_MODE=sample .venv/Scripts/python.exe scripts/test_near_miss_improvement.py
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"  # Supabase 미접속 보장

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from modules import auth, db  # noqa: E402
from modules import supabase_repository as sr  # noqa: E402

PASSED = 0


def check(name: str, condition: bool) -> None:
    global PASSED
    assert condition, f"FAILED: {name}"
    PASSED += 1
    print(f"  ok - {name}")


def raises(fn, exc_type=Exception):
    try:
        fn()
    except exc_type as exc:
        return exc
    return None


def _reset() -> None:
    st.session_state.pop(db._NEAR_MISS_STORE, None)
    st.session_state.pop(db._NEAR_MISS_IMPROVEMENT_STORE, None)


def _actor_of_role(role: str, *, active: bool = True, exclude=()):
    """sample 사용자 중 role·활성 여부에 맞는 세션 사용자(emp_no 만 신뢰)."""
    exclude = set(exclude)
    df = db.get_users()
    for _, row in df.iterrows():
        emp = str(row["emp_no"])
        if (str(row.get("role") or "").strip().upper() == role.upper()
                and bool(row.get("is_active")) == active and emp not in exclude):
            return {"emp_no": emp}
    raise AssertionError(f"sample 사용자에 role={role} active={active} 없음")


def _base_payload(**over) -> dict:
    payload = {
        "work_name": "설비 점검", "incident_content": "덮개 미고정",
        "cause_code": "JAM", "incident_date": "2026-07-10", "proposed_grade": "C",
    }
    payload.update(over)
    return payload


def _evaluated_report(reporter: dict, evaluator: dict):
    """SUBMITTED 보고서를 만들고 EVALUATED 로 확정해 report_id 를 돌려준다."""
    rec = db.create_near_miss_report(_base_payload(), current_user=reporter)
    db.evaluate_near_miss(rec["id"], "B", current_user=evaluator)
    return rec["id"]


def _users_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for col in db.USER_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[db.USER_COLUMNS].reset_index(drop=True)


# =========================================================================
# 스키마 probe 3-state (near_miss_improvement)
# =========================================================================
def test_improvement_schema_probe_three_state() -> None:
    print("개선조치 readiness 3-state (007)")
    check("sample 은 항상 READY", db.near_miss_improvement_schema_probe() == sr.READINESS_READY)
    check("sample ready True", db.near_miss_improvement_schema_ready() is True)

    saved_client = sr.client
    try:
        # NOT_READY: undefined table/column 표식 → False 로 안정 캐시.
        sr.reset_near_miss_improvement_readiness()

        class _MissingQuery:
            def select(self, *a, **k): return self
            def limit(self, *a, **k): return self
            def execute(self):
                raise Exception('relation "near_miss_improvements" does not exist (42P01)')

        sr.client = lambda: type("C", (), {"table": lambda self, n: _MissingQuery()})()
        check("NOT_READY probe", sr.near_miss_improvement_extensions_probe(force=True) == sr.READINESS_NOT_READY)
        check("NOT_READY → ready False", sr.near_miss_improvement_extensions_ready() is False)

        # PROBE_ERROR: 일시/권한 오류 → 캐시하지 않음(재프로브).
        sr.reset_near_miss_improvement_readiness()
        calls = {"n": 0}

        class _FlakyQuery:
            def select(self, *a, **k): return self
            def limit(self, *a, **k): return self
            def execute(self):
                calls["n"] += 1
                raise Exception("network unreachable: connection timed out")

        sr.client = lambda: type("C", (), {"table": lambda self, n: _FlakyQuery()})()
        check("PROBE_ERROR probe", sr.near_miss_improvement_extensions_probe(force=True) == sr.READINESS_PROBE_ERROR)
        n0 = calls["n"]
        check("PROBE_ERROR → ready False(보수 차단)", sr.near_miss_improvement_extensions_ready() is False)
        check("PROBE_ERROR 재프로브(비고착)", calls["n"] > n0)
    finally:
        sr.client = saved_client
        sr.reset_near_miss_improvement_readiness()


# =========================================================================
# 조회 게이트 readiness 일시오류 표면화 (종합감사 P2-query)
# =========================================================================
def test_improvement_read_gate_surfaces_probe_error() -> None:
    """개선조치 조회 readiness 게이트: 미적용(NOT_READY)은 None(정상 부재), 일시오류
    (PROBE_ERROR)는 None 으로 접지 않고 예외 전파(near_miss_my danger 배너 표면화).

    supabase 조회 경로(리포지토리)를 직접 검증한다 — 캐시되지 않은 readiness 오류 경로는
    facade 직접 예외만 보던 test_near_miss_error_surfacing 이 다루지 않던 구멍."""
    print("개선조치 조회 게이트 — NOT_READY→None vs PROBE_ERROR→예외 전파 (P2-query)")
    saved_client = sr.client

    class _MissingQuery:  # 007 미적용(테이블/컬럼 부재) 시그널.
        def select(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def execute(self):
            raise Exception('relation "near_miss_improvements" does not exist (42P01)')

    class _FlakyQuery:  # 일시/네트워크/권한 오류 시그널.
        def select(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def execute(self):
            raise Exception("network unreachable: connection timed out")

    try:
        # (a) NOT_READY(007 미적용) → 정상 부재 None, 예외 없음.
        sr.reset_near_miss_improvement_readiness()
        sr.client = lambda: type("C", (), {"table": lambda self, n: _MissingQuery()})()
        check("미적용 → get_near_miss_revision_request None",
              sr.get_near_miss_revision_request("r1") is None)
        sr.reset_near_miss_improvement_readiness()
        check("미적용 → get_near_miss_improvement None",
              sr.get_near_miss_improvement("r1") is None)

        # (b) 일시오류(PROBE_ERROR) → None 으로 은폐하지 않고 예외 전파.
        sr.reset_near_miss_improvement_readiness()
        sr.client = lambda: type("C", (), {"table": lambda self, n: _FlakyQuery()})()
        exc_rev = raises(lambda: sr.get_near_miss_revision_request("r1"), sr.SupabaseDataError)
        check("일시오류 → revision_request 예외 전파(무배너 은폐 아님)", exc_rev is not None)
        sr.reset_near_miss_improvement_readiness()
        exc_imp = raises(lambda: sr.get_near_miss_improvement("r1"), sr.SupabaseDataError)
        check("일시오류 → improvement 예외 전파(미작성 위장 아님)", exc_imp is not None)

        # 전파 예외는 파사드 DATA_SOURCE_ERRORS 로 잡힌다(뷰 danger 배너 경로).
        check("전파 예외는 DATA_SOURCE_ERRORS(뷰 danger 배너 포착)",
              isinstance(exc_rev, db.DATA_SOURCE_ERRORS))
    finally:
        sr.client = saved_client
        sr.reset_near_miss_improvement_readiness()


# =========================================================================
# upsert(DRAFT) — 신원 서버확정·server-field 위조 무시·검증
# =========================================================================
def test_upsert_creates_draft_server_fields() -> None:
    print("upsert_near_miss_improvement DRAFT 생성 + server-field 위조 무시")
    _reset()
    reporter = _actor_of_role("USER")
    manager = _actor_of_role("MANAGER")
    admin = _actor_of_role("ADMIN")
    rid = _evaluated_report(reporter, manager)

    # ADMIN 은 배정+작업 두 branch 를 함께 열 수 있어 생성 시 배정·작업필드를 한 번에 쓴다
    # (비담당 평가자는 작업 branch 가 닫혀 작업필드가 무시되므로, 이 종합 생성 검증은 ADMIN).
    rec = db.upsert_near_miss_improvement(rid, {
        "assignee_emp_no": reporter["emp_no"], "action_body": "조치안",
        "result_body": "조치결과", "due_date": "2026-08-01",
        # server-owned 위조 시도.
        "submit_status": "SUBMITTED", "confirm_status": "CONFIRMED",
        "confirmed_by_emp_no": manager["emp_no"], "confirmed_at": "2000-01-01T00:00:00Z",
        "is_active": False, "id": 99999,
    }, current_user=admin)

    check("submit_status 서버측 DRAFT", rec["submit_status"] == "DRAFT")
    check("confirm_status 서버측 PENDING", rec["confirm_status"] == "PENDING")
    check("확인 행위자 위조 무시(빈값)", str(rec["confirmed_by_emp_no"]) == "")
    check("submitted_at 미설정", rec["submitted_at"] in (None, ""))
    check("is_active 서버측 True", bool(rec["is_active"]) is True)
    check("담당자 저장", rec["assignee_emp_no"] == reporter["emp_no"])
    check("조치 결과 저장", rec["result_body"] == "조치결과")
    check("기한 저장", rec["due_date"] == "2026-08-01")
    check("report 1:1 키", str(rec["report_id"]) == str(rid))

    # 무인증·비활성 차단.
    check("무인증 upsert 차단",
          raises(lambda: db.upsert_near_miss_improvement(rid, {}, current_user=None), ValueError) is not None)
    inactive = _actor_of_role("USER", active=False)
    exc = raises(lambda: db.upsert_near_miss_improvement(
        rid, {}, current_user={"emp_no": inactive["emp_no"]}), ValueError)
    check("비활성 upsert 차단", exc is not None and "비활성" in str(exc))
    # 잘못된 담당자·기한 거부.
    check("없는 담당자 거부",
          raises(lambda: db.upsert_near_miss_improvement(
              rid, {"assignee_emp_no": "없는사번"}, current_user=manager), ValueError) is not None)
    # 기한 형식 검증은 작업 branch(작업필드) — 작업 권한자(ADMIN)로 확인한다(비담당 평가자는
    # due_date 가 strip 되어 검증에 도달하지 않으므로 잘못된 계약이 아니라 주체를 맞춘다).
    check("잘못된 기한 형식 거부",
          raises(lambda: db.upsert_near_miss_improvement(
              rid, {"due_date": "2026/08/01"}, current_user=admin), ValueError) is not None)
    check("없는 보고서 upsert 차단",
          raises(lambda: db.upsert_near_miss_improvement(
              999999, {}, current_user=manager), ValueError) is not None)


# =========================================================================
# submit — 담당자·결과 필수, DRAFT→SUBMITTED, stale
# =========================================================================
def test_submit_requires_assignee_and_result() -> None:
    print("submit_near_miss_improvement 담당자·결과 필수 + DRAFT→SUBMITTED")
    _reset()
    reporter = _actor_of_role("USER")
    manager = _actor_of_role("MANAGER")
    rid = _evaluated_report(reporter, manager)

    # 평가자가 담당자를 배정하되 조치 결과는 아직 없음(담당자가 조치 내용만 저장).
    db.upsert_near_miss_improvement(rid, {"assignee_emp_no": reporter["emp_no"]}, current_user=manager)
    db.upsert_near_miss_improvement(rid, {"action_body": "조치만"}, current_user=reporter)
    # 조치 결과 없이 담당자 제출 불가.
    check("결과 없으면 제출 차단",
          raises(lambda: db.submit_near_miss_improvement(rid, current_user=reporter), ValueError) is not None)

    # 결과 채우고 담당자 제출.
    db.upsert_near_miss_improvement(rid, {"result_body": "결과"}, current_user=reporter)
    rec = db.submit_near_miss_improvement(rid, current_user=reporter)
    check("DRAFT→SUBMITTED", rec["submit_status"] == "SUBMITTED")
    check("submitted_at 서버측 설정", bool(str(rec["submitted_at"] or "")))
    check("confirm_status PENDING 유지", rec["confirm_status"] == "PENDING")

    # 이미 SUBMITTED 인데 다시 제출 → stale.
    exc = raises(lambda: db.submit_near_miss_improvement(rid, current_user=reporter), ValueError)
    check("SUBMITTED 재제출 stale", exc is not None and "이미 변경" in str(exc))


# =========================================================================
# confirm — 서버귀속·자기확인 차단·능력 게이트·stale
# =========================================================================
def _submitted_improvement(rid, assignee, actor):
    """CAPA 행단위 인가 흐름: 평가자(actor)가 배정하고, 배정된 담당자(assignee)가 조치를
    작성·제출한다. 배정과 작업(제출)이 서버측 인가로 분리됐으므로 각각 올바른 주체로 호출한다."""
    db.upsert_near_miss_improvement(rid, {
        "assignee_emp_no": assignee["emp_no"]}, current_user=actor)              # 배정(평가자)
    db.upsert_near_miss_improvement(rid, {"result_body": "결과"}, current_user=assignee)  # 담당자 작업
    db.submit_near_miss_improvement(rid, current_user=assignee)                  # 담당자 제출


def test_confirm_server_attribution_and_self_confirm() -> None:
    print("confirm_near_miss_improvement 서버귀속 + 자기확인 차단 + 능력 게이트")
    _reset()
    reporter = _actor_of_role("USER")
    manager = _actor_of_role("MANAGER")
    rid = _evaluated_report(reporter, manager)
    _submitted_improvement(rid, reporter, manager)

    # USER(능력 없음) 확인 차단.
    exc = raises(lambda: db.confirm_near_miss_improvement(
        rid, current_user={"emp_no": reporter["emp_no"]}), ValueError)
    check("USER 확인 차단(권한)", exc is not None and "권한" in str(exc))
    # 무인증 차단.
    check("무인증 확인 차단",
          raises(lambda: db.confirm_near_miss_improvement(rid, current_user=None), ValueError) is not None)

    # 능력 있는 MANAGER(≠담당자) 확인 → confirmed_by=서버 actor.
    rec = db.confirm_near_miss_improvement(rid, current_user={"emp_no": manager["emp_no"]})
    check("PENDING→CONFIRMED", rec["confirm_status"] == "CONFIRMED")
    check("확인 행위자=인증 actor(서버귀속)", rec["confirmed_by_emp_no"] == manager["emp_no"])
    check("confirmed_at 서버측 설정", bool(str(rec["confirmed_at"] or "")))

    # 재확인 → stale.
    exc2 = raises(lambda: db.confirm_near_miss_improvement(
        rid, current_user={"emp_no": manager["emp_no"]}), ValueError)
    check("확인된 개선조치 재확인 stale", exc2 is not None and "이미 변경" in str(exc2))

    # 자기확인 차단: 담당자==확인자.
    _reset()
    rid2 = _evaluated_report(reporter, manager)
    _submitted_improvement(rid2, manager, manager)   # 담당자=manager
    exc3 = raises(lambda: db.confirm_near_miss_improvement(
        rid2, current_user={"emp_no": manager["emp_no"]}), ValueError)
    check("담당자 본인 자기확인 차단", exc3 is not None and "자기확인" in str(exc3))
    check("자기확인 차단 후 PENDING 유지",
          db._near_miss_improvement_raw(rid2)["confirm_status"] == "PENDING")


def test_safety_officer_can_confirm() -> None:
    print("안전담당자 USER 는 개선조치 확인 허용 (능력 근거=is_safety_officer)")
    _reset()
    so = _actor_of_role("USER")
    reporter = _actor_of_role("USER", exclude=(so["emp_no"],))
    manager = _actor_of_role("MANAGER")
    rid = _evaluated_report(reporter, manager)
    _submitted_improvement(rid, reporter, manager)

    orig = db._safety_officer_flag
    db._safety_officer_flag = lambda emp, **_: str(emp).strip() == so["emp_no"]
    try:
        rec = db.confirm_near_miss_improvement(rid, current_user={"emp_no": so["emp_no"]})
        check("안전담당자 확인 허용", rec["confirm_status"] == "CONFIRMED")
        check("확인 행위자=안전담당자 사번", rec["confirmed_by_emp_no"] == so["emp_no"])
    finally:
        db._safety_officer_flag = orig


# =========================================================================
# reject — 사유 필수·능력 게이트·재초안
# =========================================================================
def test_reject_flow() -> None:
    print("reject_near_miss_improvement 사유 필수 + 능력 게이트 + 재초안 리셋")
    _reset()
    reporter = _actor_of_role("USER")
    manager = _actor_of_role("MANAGER")
    rid = _evaluated_report(reporter, manager)
    _submitted_improvement(rid, reporter, manager)

    # 사유 없으면 반려 불가.
    check("반려 사유 필수",
          raises(lambda: db.reject_near_miss_improvement(rid, "  ", current_user=manager), ValueError) is not None)
    # USER 능력 없음 → 반려 차단.
    check("USER 반려 차단",
          raises(lambda: db.reject_near_miss_improvement(
              rid, "미흡", current_user={"emp_no": reporter["emp_no"]}), ValueError) is not None)

    rec = db.reject_near_miss_improvement(rid, "조치 근거 미흡", current_user=manager)
    check("PENDING→REJECTED", rec["confirm_status"] == "REJECTED")
    check("반려 행위자=인증 actor", rec["rejected_by_emp_no"] == manager["emp_no"])
    check("반려 사유(revision_note) 기록", rec["revision_note"] == "조치 근거 미흡")
    check("확인 행위자 비어있음", str(rec["confirmed_by_emp_no"]) == "")

    # 반려된 개선조치를 담당자가 실제로 재편집(값 변경: "결과"→"보완결과")하면 DRAFT/PENDING
    # 으로 되돌아간다(값 비교 계약). 반려 후 재조치는 담당자(작업 권한) 본인의 실변경이 정상
    # 경로다 — 평가자의 동일 재배정 같은 no-op 은 새 계약상 status 를 건드리지 않는다.
    redraft = db.upsert_near_miss_improvement(
        rid, {"result_body": "보완결과"}, current_user={"emp_no": reporter["emp_no"]})
    check("반려 후 재편집 DRAFT 복귀", redraft["submit_status"] == "DRAFT")
    check("반려 후 재편집 PENDING 복귀", redraft["confirm_status"] == "PENDING")
    check("재편집 시 반려행위자 초기화", str(redraft["rejected_by_emp_no"]) == "")


# =========================================================================
# 확인된 개선조치는 편집 불가(강등 방지)
# =========================================================================
def test_confirmed_is_immutable() -> None:
    print("확인(CONFIRMED)된 개선조치 upsert 편집 거부(강등 방지)")
    _reset()
    reporter = _actor_of_role("USER")
    manager = _actor_of_role("MANAGER")
    rid = _evaluated_report(reporter, manager)
    _submitted_improvement(rid, reporter, manager)
    db.confirm_near_miss_improvement(rid, current_user={"emp_no": manager["emp_no"]})

    exc = raises(lambda: db.upsert_near_miss_improvement(
        rid, {"result_body": "덮어쓰기"}, current_user=manager), ValueError)
    check("확인된 개선조치 편집 거부", exc is not None and "확인" in str(exc))
    check("편집 거부 후 CONFIRMED 유지", db._near_miss_improvement_raw(rid)["confirm_status"] == "CONFIRMED")


# =========================================================================
# 확인+종결 하드게이트 (close_near_miss_report)
# =========================================================================
def test_close_hard_gate() -> None:
    print("close_near_miss_report 확인+종결 하드게이트")
    _reset()
    reporter = _actor_of_role("USER")
    manager = _actor_of_role("MANAGER")
    rid = _evaluated_report(reporter, manager)

    # (1) 확인된 개선조치 없이 종결 → 거부, EVALUATED 유지.
    exc = raises(lambda: db.close_near_miss_report(rid, current_user=manager), ValueError)
    check("개선조치 없이 종결 거부", exc is not None and "개선조치" in str(exc))
    check("거부 후 EVALUATED 유지", db.get_near_miss_report(rid)["status"] == "EVALUATED")

    # 제출·확인.
    _submitted_improvement(rid, reporter, manager)
    db.confirm_near_miss_improvement(rid, current_user={"emp_no": manager["emp_no"]})

    # (2) USER(능력 없음) 종결 차단.
    exc2 = raises(lambda: db.close_near_miss_report(
        rid, current_user={"emp_no": reporter["emp_no"]}), ValueError)
    check("USER 종결 차단(권한)", exc2 is not None and "권한" in str(exc2))

    # (3) 능력자 종결 성공.
    out = db.close_near_miss_report(rid, current_user=manager)
    check("확인된 개선조치로 종결 성공", out["status"] == "CLOSED")

    # (4) 이미 CLOSED → 재종결 stale(EVALUATED 조건 불충족).
    exc3 = raises(lambda: db.close_near_miss_report(rid, current_user=manager), ValueError)
    check("CLOSED 재종결 stale", exc3 is not None and "이미 변경" in str(exc3))


def test_direct_close_transition_blocked() -> None:
    print("update_near_miss_status 직접 →CLOSED 차단(close_near_miss_report 위임)")
    _reset()
    reporter = _actor_of_role("USER")
    manager = _actor_of_role("MANAGER")
    rid = _evaluated_report(reporter, manager)
    _submitted_improvement(rid, reporter, manager)
    db.confirm_near_miss_improvement(rid, current_user={"emp_no": manager["emp_no"]})

    # 확인된 개선조치가 있어도 일반 상태변경으로는 CLOSED 로 못 간다(진입부 차단).
    exc = raises(lambda: db.update_near_miss_status(rid, "CLOSED", current_user=manager), ValueError)
    check("직접 →CLOSED 차단", exc is not None and "close_near_miss_report" in str(exc))
    check("차단 후 EVALUATED 유지", db.get_near_miss_report(rid)["status"] == "EVALUATED")
    # 무인증 호출도 동일 사유(진입부 게이트).
    exc2 = raises(lambda: db.update_near_miss_status(rid, "CLOSED", current_user=None), ValueError)
    check("무인증 →CLOSED 도 위임 차단", exc2 is not None and "close_near_miss_report" in str(exc2))


# =========================================================================
# 강등방어(sample) — CLOSED 후 확인된 개선조치는 편집으로 되돌릴 수 없다
# =========================================================================
def test_child_demotion_defense_sample() -> None:
    print("CLOSED 후 확인된 개선조치 강등방어(sample facade 집행)")
    _reset()
    reporter = _actor_of_role("USER")
    manager = _actor_of_role("MANAGER")
    rid = _evaluated_report(reporter, manager)
    _submitted_improvement(rid, reporter, manager)
    db.confirm_near_miss_improvement(rid, current_user={"emp_no": manager["emp_no"]})
    db.close_near_miss_report(rid, current_user=manager)
    check("종결 진입", db.get_near_miss_report(rid)["status"] == "CLOSED")

    # 확인된 개선조치는 편집(강등 유일 경로)이 거부되어 사후에 무를 수 없다.
    exc = raises(lambda: db.upsert_near_miss_improvement(
        rid, {"result_body": "사후 변경"}, current_user=manager), ValueError)
    check("CLOSED 후 확인 개선조치 편집 거부", exc is not None and "확인" in str(exc))
    imp = db._near_miss_improvement_raw(rid)
    check("확인 개선조치 CONFIRMED 유지", imp["confirm_status"] == "CONFIRMED")
    check("확인 개선조치 활성 유지", bool(imp["is_active"]) is True)


# =========================================================================
# 재개(EVALUATED→IN_REVIEW) 초기화 — 확인된 개선조치 PENDING 리셋(결과 보존)
# =========================================================================
def test_reopen_resets_confirmed_capa() -> None:
    print("재개(EVALUATED→IN_REVIEW) 시 확인된 개선조치 CONFIRMED→PENDING 초기화")
    _reset()
    reporter = _actor_of_role("USER")
    manager = _actor_of_role("MANAGER")
    rid = _evaluated_report(reporter, manager)
    db.upsert_near_miss_improvement(rid, {
        "assignee_emp_no": reporter["emp_no"]}, current_user=manager)   # 배정(평가자)
    db.upsert_near_miss_improvement(rid, {
        "result_body": "조치결과", "due_date": "2026-08-15"}, current_user=reporter)  # 담당자 작업
    db.submit_near_miss_improvement(rid, current_user=reporter)         # 담당자 제출
    db.confirm_near_miss_improvement(rid, current_user={"emp_no": manager["emp_no"]})
    check("사전 CONFIRMED", db._near_miss_improvement_raw(rid)["confirm_status"] == "CONFIRMED")

    # 재개 전이.
    db.update_near_miss_status(rid, "IN_REVIEW", current_user=manager)
    check("report IN_REVIEW 재개", db.get_near_miss_report(rid)["status"] == "IN_REVIEW")
    check("report 확정등급 초기화", str(db.get_near_miss_report(rid).get("confirmed_grade") or "") == "")

    imp = db._near_miss_improvement_raw(rid)
    check("개선조치 CONFIRMED→PENDING 초기화", imp["confirm_status"] == "PENDING")
    check("확인 행위자 초기화", str(imp["confirmed_by_emp_no"]) == "")
    check("확인 시각 초기화", imp["confirmed_at"] in (None, ""))
    check("조치 결과 보존", imp["result_body"] == "조치결과")
    check("기한 보존", imp["due_date"] == "2026-08-15")
    check("제출 상태 보존(SUBMITTED)", imp["submit_status"] == "SUBMITTED")


# =========================================================================
# 서버귀속 라우팅(supabase 경로) — 위조 confirmed_by 무시, actor 로 repo 호출
# =========================================================================
def test_confirm_supabase_path_server_attribution() -> None:
    print("supabase 경로 confirm: confirmed_by=인증 actor 로 repo 호출(위조 무시)")
    manager = _actor_of_role("MANAGER")
    auth_record = db.find_user_by_emp_no(manager["emp_no"])
    captured: dict = {}

    orig_sample = db.is_sample_mode
    orig_find = db.find_user_by_emp_no
    orig_get = db._near_miss_improvement_raw
    orig_repo = db.supabase_repository.confirm_near_miss_improvement
    db.is_sample_mode = lambda: False
    db.find_user_by_emp_no = lambda emp, **kw: auth_record if str(emp).strip() == manager["emp_no"] else None
    # 인가 판정용 원본 개선조치(담당자는 actor 와 다른 사람 → 자기확인 아님, manager 는 평가자).
    db._near_miss_improvement_raw = lambda rid, **kw: {
        "assignee_emp_no": "1003", "designated_confirmer_emp_no": ""}
    db.supabase_repository.confirm_near_miss_improvement = (
        lambda report_id, *, confirmed_by_emp_no, updated_by: (
            captured.update({"report_id": report_id, "confirmed_by_emp_no": confirmed_by_emp_no,
                             "updated_by": updated_by}) or {"confirm_status": "CONFIRMED"}))
    try:
        db.confirm_near_miss_improvement(7, current_user={"emp_no": manager["emp_no"], "role": "USER"})
    finally:
        db.is_sample_mode = orig_sample
        db.find_user_by_emp_no = orig_find
        db._near_miss_improvement_raw = orig_get
        db.supabase_repository.confirm_near_miss_improvement = orig_repo

    check("repo confirmed_by = 인증 actor 사번", captured.get("confirmed_by_emp_no") == manager["emp_no"])
    check("repo updated_by = 인증 actor 사번", captured.get("updated_by") == manager["emp_no"])
    check("report_id 전달", captured.get("report_id") == 7)


def test_sample_self_confirm_case_insensitive() -> None:
    print("sample 자기확인 대소문자 무차별 차단 + 담당자 사번 정규화 저장 (P2-4)")
    _reset()
    # sample 사번은 숫자라 대소문자 차이가 없다. 알파벳 사번 담당자(=확인 능력 있는 MANAGER)를
    # 실제 프레임에 덧붙여 대소문자 우회 시나리오를 만든다.
    orig_users = db.get_users
    base = orig_users()
    extra = base[base["emp_no"] == "1002"].iloc[[0]].copy()
    extra["emp_no"] = "CapaMgr"
    frame = pd.concat([base, extra], ignore_index=True)
    db.get_users = lambda *a, **k: frame
    try:
        reporter = {"emp_no": "1003"}
        manager = {"emp_no": "1002"}
        rid = _evaluated_report(reporter, manager)
        # 담당자를 소문자 'capamgr' 로 지정(DB 원본 표기는 'CapaMgr'). 배정은 평가자(manager).
        db.upsert_near_miss_improvement(
            rid, {"assignee_emp_no": "capamgr"}, current_user=manager)
        # 조치 결과는 배정된 담당자(CapaMgr) 본인이 작성한다(작업 branch — 평가자는 작업필드 불가).
        db.upsert_near_miss_improvement(
            rid, {"result_body": "결과"}, current_user={"emp_no": "CapaMgr"})
        # 제출은 배정된 담당자(CapaMgr) 본인이 한다(작업 권한).
        db.submit_near_miss_improvement(rid, current_user={"emp_no": "CapaMgr"})
        check("담당자 사번 정규화 저장(DB 원본 표기)",
              db._near_miss_improvement_raw(rid)["assignee_emp_no"] == "CapaMgr")
        # 같은 사람을 대문자 'CAPAMGR' 로 확인자 지정 → 자기확인 차단(대소문자 무차별).
        exc = raises(lambda: db.confirm_near_miss_improvement(
            rid, current_user={"emp_no": "CAPAMGR"}), ValueError)
        check("대소문자 다른 자기확인 차단", exc is not None and "자기확인" in str(exc))
        check("자기확인 차단 후 PENDING 유지",
              db._near_miss_improvement_raw(rid)["confirm_status"] == "PENDING")
    finally:
        db.get_users = orig_users


def test_repo_update_status_rejects_direct_closed() -> None:
    print("supabase_repository.update_near_miss_status 직접 →CLOSED 거부 (P1-3 repository 이중방어)")
    orig_ready = sr.near_miss_extensions_ready
    sr.near_miss_extensions_ready = lambda: True
    try:
        exc = raises(lambda: sr.update_near_miss_status(1, "CLOSED"), sr.SupabaseDataError)
        check("repo 직접 CLOSED 거부", exc is not None and "close_near_miss_report" in str(exc))
        exc2 = raises(lambda: sr.update_near_miss_status(1, "closed"), sr.SupabaseDataError)
        check("repo 직접 closed(소문자) 거부", exc2 is not None)
    finally:
        sr.near_miss_extensions_ready = orig_ready


def test_reopen_supabase_path_uses_atomic_rpc() -> None:
    print("supabase 경로 재개: 원자 RPC(reopen_near_miss_report)로 위임(2단계 아님) (P1-4)")
    manager = _actor_of_role("MANAGER")
    auth_record = db.find_user_by_emp_no(manager["emp_no"])
    captured: dict = {}
    calls = {"reset": 0, "plain": 0}

    orig_sample = db.is_sample_mode
    orig_find = db.find_user_by_emp_no
    orig_get = db.get_near_miss_report
    orig_probe = db.near_miss_improvement_schema_probe
    orig_reopen = db.supabase_repository.reopen_near_miss_report
    orig_plain = db.supabase_repository.update_near_miss_status
    db.is_sample_mode = lambda: False
    db.find_user_by_emp_no = lambda emp, **kw: auth_record if str(emp).strip() == manager["emp_no"] else None
    db.get_near_miss_report = lambda rid: {"id": rid, "status": "EVALUATED", "reporter_emp_no": "1003"}
    db.near_miss_improvement_schema_probe = lambda **k: db.READINESS_READY  # 007 적용(ready)
    db.supabase_repository.reopen_near_miss_report = (
        lambda report_id, *, actor_emp_no: (
            captured.update({"report_id": report_id, "actor_emp_no": actor_emp_no})
            or {"status": "IN_REVIEW"}))
    db.supabase_repository.update_near_miss_status = (
        lambda *a, **k: calls.__setitem__("plain", calls["plain"] + 1) or {"status": "X"})
    try:
        out = db.update_near_miss_status(11, "IN_REVIEW", current_user={"emp_no": manager["emp_no"]})
    finally:
        db.is_sample_mode = orig_sample
        db.find_user_by_emp_no = orig_find
        db.get_near_miss_report = orig_get
        db.near_miss_improvement_schema_probe = orig_probe
        db.supabase_repository.reopen_near_miss_report = orig_reopen
        db.supabase_repository.update_near_miss_status = orig_plain

    check("재개는 원자 RPC 로 위임", out and out.get("status") == "IN_REVIEW")
    check("actor_emp_no 서버귀속", captured.get("actor_emp_no") == manager["emp_no"])
    check("report_id 전달", captured.get("report_id") == 11)
    check("일반 상태변경 경로 미사용", calls["plain"] == 0)


def test_reopen_supabase_path_not_ready_uses_plain() -> None:
    print("supabase 경로 재개: 007 미적용(NOT_READY)이면 일반 전이(리셋 대상 없음) (P1-2 (a))")
    manager = _actor_of_role("MANAGER")
    auth_record = db.find_user_by_emp_no(manager["emp_no"])
    calls = {"plain": 0, "rpc": 0}

    orig_sample = db.is_sample_mode
    orig_find = db.find_user_by_emp_no
    orig_get = db.get_near_miss_report
    orig_probe = db.near_miss_improvement_schema_probe
    orig_reopen = db.supabase_repository.reopen_near_miss_report
    orig_plain = db.supabase_repository.update_near_miss_status
    db.is_sample_mode = lambda: False
    db.find_user_by_emp_no = lambda emp, **kw: auth_record if str(emp).strip() == manager["emp_no"] else None
    db.get_near_miss_report = lambda rid: {"id": rid, "status": "EVALUATED", "reporter_emp_no": "1003"}
    db.near_miss_improvement_schema_probe = lambda **k: db.READINESS_NOT_READY  # 007 미적용
    db.supabase_repository.reopen_near_miss_report = (
        lambda *a, **k: calls.__setitem__("rpc", calls["rpc"] + 1) or {"status": "IN_REVIEW"})
    db.supabase_repository.update_near_miss_status = (
        lambda *a, **k: calls.__setitem__("plain", calls["plain"] + 1) or {"status": "IN_REVIEW"})
    try:
        out = db.update_near_miss_status(13, "IN_REVIEW", current_user={"emp_no": manager["emp_no"]})
    finally:
        db.is_sample_mode = orig_sample
        db.find_user_by_emp_no = orig_find
        db.get_near_miss_report = orig_get
        db.near_miss_improvement_schema_probe = orig_probe
        db.supabase_repository.reopen_near_miss_report = orig_reopen
        db.supabase_repository.update_near_miss_status = orig_plain

    check("미적용 재개는 일반 전이 위임", out and out.get("status") == "IN_REVIEW")
    check("미적용 시 원자 RPC 미사용", calls["rpc"] == 0)
    check("미적용 시 일반 상태변경 사용", calls["plain"] == 1)


def test_reopen_supabase_path_probe_error_fails_closed() -> None:
    print("supabase 경로 재개: probe 오류(PROBE_ERROR)면 전파·일반 UPDATE 우회 안 함 (P1-2 (b))")
    manager = _actor_of_role("MANAGER")
    auth_record = db.find_user_by_emp_no(manager["emp_no"])
    calls = {"plain": 0, "rpc": 0}

    orig_sample = db.is_sample_mode
    orig_find = db.find_user_by_emp_no
    orig_get = db.get_near_miss_report
    orig_probe = db.near_miss_improvement_schema_probe
    orig_reopen = db.supabase_repository.reopen_near_miss_report
    orig_plain = db.supabase_repository.update_near_miss_status
    db.is_sample_mode = lambda: False
    db.find_user_by_emp_no = lambda emp, **kw: auth_record if str(emp).strip() == manager["emp_no"] else None
    db.get_near_miss_report = lambda rid: {"id": rid, "status": "EVALUATED", "reporter_emp_no": "1003"}
    db.near_miss_improvement_schema_probe = lambda **k: db.READINESS_PROBE_ERROR  # 일시/네트워크 오류
    db.supabase_repository.reopen_near_miss_report = (
        lambda *a, **k: calls.__setitem__("rpc", calls["rpc"] + 1) or {"status": "IN_REVIEW"})
    db.supabase_repository.update_near_miss_status = (
        lambda *a, **k: calls.__setitem__("plain", calls["plain"] + 1) or {"status": "IN_REVIEW"})
    try:
        exc = raises(lambda: db.update_near_miss_status(
            14, "IN_REVIEW", current_user={"emp_no": manager["emp_no"]}),
            db.supabase_repository.SupabaseDataError)
    finally:
        db.is_sample_mode = orig_sample
        db.find_user_by_emp_no = orig_find
        db.get_near_miss_report = orig_get
        db.near_miss_improvement_schema_probe = orig_probe
        db.supabase_repository.reopen_near_miss_report = orig_reopen
        db.supabase_repository.update_near_miss_status = orig_plain

    check("probe 오류는 전파(fail-closed)", exc is not None)
    check("probe 오류 시 원자 RPC 미사용", calls["rpc"] == 0)
    check("probe 오류 시 일반 UPDATE 우회 안 함", calls["plain"] == 0)


def test_reopen_supabase_path_error_propagates() -> None:
    print("supabase 경로 재개 RPC 실패는 조용히 건너뛰지 않고 전파 (P1-4 중간실패 전파)")
    manager = _actor_of_role("MANAGER")
    auth_record = db.find_user_by_emp_no(manager["emp_no"])

    def _boom(report_id, *, actor_emp_no):
        raise RuntimeError("원자 재개 실패(테스트)")

    orig_sample = db.is_sample_mode
    orig_find = db.find_user_by_emp_no
    orig_get = db.get_near_miss_report
    orig_probe = db.near_miss_improvement_schema_probe
    orig_reopen = db.supabase_repository.reopen_near_miss_report
    db.is_sample_mode = lambda: False
    db.find_user_by_emp_no = lambda emp, **kw: auth_record if str(emp).strip() == manager["emp_no"] else None
    db.get_near_miss_report = lambda rid: {"id": rid, "status": "EVALUATED", "reporter_emp_no": "1003"}
    db.near_miss_improvement_schema_probe = lambda **k: db.READINESS_READY
    db.supabase_repository.reopen_near_miss_report = _boom
    try:
        exc = raises(lambda: db.update_near_miss_status(
            12, "IN_REVIEW", current_user={"emp_no": manager["emp_no"]}), RuntimeError)
    finally:
        db.is_sample_mode = orig_sample
        db.find_user_by_emp_no = orig_find
        db.get_near_miss_report = orig_get
        db.near_miss_improvement_schema_probe = orig_probe
        db.supabase_repository.reopen_near_miss_report = orig_reopen

    check("재개 RPC 오류 전파(은폐 없음)", exc is not None and "원자 재개 실패" in str(exc))


def _in_review_report(reporter: dict, evaluator: dict):
    """SUBMITTED 보고서를 만들고 IN_REVIEW(검토착수)로 전이해 report_id 를 돌려준다."""
    rec = db.create_near_miss_report(_base_payload(), current_user=reporter)
    db.update_near_miss_status(rec["id"], "IN_REVIEW", current_user=evaluator)
    return rec["id"]


def test_request_revision_sample() -> None:
    print("request_near_miss_revision(sample): 사유필수·서버귀속·인가·IN_REVIEW→SUBMITTED (Phase1 #2)")
    _reset()
    st.session_state.pop(db._NEAR_MISS_REVISION_STORE, None)
    reporter = _actor_of_role("USER")
    manager = _actor_of_role("MANAGER")
    rid = _in_review_report(reporter, manager)

    # 사유 필수.
    exc = raises(lambda: db.request_near_miss_revision(rid, "   ", current_user=manager), ValueError)
    check("빈 사유 차단", exc is not None and "사유" in str(exc))
    # 무인증 차단.
    check("무인증 차단",
          raises(lambda: db.request_near_miss_revision(rid, "사유", current_user=None), ValueError) is not None)
    # 능력 없는 USER 차단(인가).
    excu = raises(lambda: db.request_near_miss_revision(
        rid, "사유", current_user={"emp_no": reporter["emp_no"]}), ValueError)
    check("USER 인가 차단", excu is not None and "권한" in str(excu))
    # 차단들 이후에도 여전히 IN_REVIEW(전이 안 됨).
    check("차단 시 IN_REVIEW 유지", db.get_near_miss_report(rid)["status"] == "IN_REVIEW")

    # 정상 보완요청: IN_REVIEW→SUBMITTED + 사유/요청자/시각 서버기록.
    out = db.request_near_miss_revision(rid, "덮개 상세 보완 바람", current_user=manager)
    check("IN_REVIEW→SUBMITTED 전이", out and out.get("status") == "SUBMITTED")
    rev = db.get_near_miss_revision_request(rid)
    check("사유 기록", rev is not None and rev["revision_request_reason"] == "덮개 상세 보완 바람")
    check("요청자 서버귀속(인증 actor 사번)", rev["revision_requested_by_emp_no"] == manager["emp_no"])
    check("요청시각 서버기록", bool(str(rev.get("revision_requested_at") or "")))

    # 이미 SUBMITTED(IN_REVIEW 아님) → 차단.
    exc2 = raises(lambda: db.request_near_miss_revision(rid, "사유", current_user=manager), ValueError)
    check("IN_REVIEW 아니면 차단", exc2 is not None and "IN_REVIEW" in str(exc2))

    # 일반 파사드로는 IN_REVIEW→SUBMITTED 반송이 차단된다(사유 없는 반송 금지).
    rid2 = _in_review_report(reporter, manager)
    excp = raises(lambda: db.update_near_miss_status(rid2, "SUBMITTED", current_user=manager), ValueError)
    check("일반 경로 반송 차단", excp is not None and "request_near_miss_revision" in str(excp))


def test_request_revision_supabase_path() -> None:
    print("request_near_miss_revision(supabase): repo 위임·서버귀속·probe fail-closed (Phase1 #2)")
    manager = _actor_of_role("MANAGER")
    auth_record = db.find_user_by_emp_no(manager["emp_no"])
    captured: dict = {}

    orig_sample = db.is_sample_mode
    orig_find = db.find_user_by_emp_no
    orig_get = db.get_near_miss_report
    orig_probe = db.near_miss_improvement_schema_probe
    orig_repo = db.supabase_repository.request_near_miss_revision
    db.is_sample_mode = lambda: False
    db.find_user_by_emp_no = lambda emp, **kw: auth_record if str(emp).strip() == manager["emp_no"] else None
    db.get_near_miss_report = lambda rid: {"id": rid, "status": "IN_REVIEW", "reporter_emp_no": "1003"}
    db.supabase_repository.request_near_miss_revision = (
        lambda report_id, reason, *, requester_emp_no, expected_status=None: (
            captured.update({"report_id": report_id, "reason": reason,
                             "requester_emp_no": requester_emp_no,
                             "expected_status": expected_status})
            or {"status": "SUBMITTED"}))
    try:
        # READY → repo 위임 + 서버귀속.
        db.near_miss_improvement_schema_probe = lambda **k: db.READINESS_READY
        out = db.request_near_miss_revision(20, "보완 사유", current_user={"emp_no": manager["emp_no"]})
        check("READY 면 repo 위임", out and out.get("status") == "SUBMITTED")
        check("사유 전달", captured.get("reason") == "보완 사유")
        check("요청자 서버귀속(인증 actor)", captured.get("requester_emp_no") == manager["emp_no"])
        check("expected_status=IN_REVIEW 조건부", captured.get("expected_status") == "IN_REVIEW")

        # NOT_READY → fail-closed(차단, repo 미호출).
        captured.clear()
        db.near_miss_improvement_schema_probe = lambda **k: db.READINESS_NOT_READY
        excn = raises(lambda: db.request_near_miss_revision(
            20, "사유", current_user={"emp_no": manager["emp_no"]}),
            db.supabase_repository.SupabaseDataError)
        check("NOT_READY 보완요청 차단(사유 없는 반송 방지)", excn is not None and not captured)

        # PROBE_ERROR → fail-closed(차단, repo 미호출).
        db.near_miss_improvement_schema_probe = lambda **k: db.READINESS_PROBE_ERROR
        exce = raises(lambda: db.request_near_miss_revision(
            20, "사유", current_user={"emp_no": manager["emp_no"]}),
            db.supabase_repository.SupabaseDataError)
        check("PROBE_ERROR 보완요청 차단", exce is not None and not captured)
    finally:
        db.is_sample_mode = orig_sample
        db.find_user_by_emp_no = orig_find
        db.get_near_miss_report = orig_get
        db.near_miss_improvement_schema_probe = orig_probe
        db.supabase_repository.request_near_miss_revision = orig_repo


def test_close_supabase_path_calls_rpc() -> None:
    print("supabase 경로 close: RPC(close_near_miss_report)로 위임")
    manager = _actor_of_role("MANAGER")
    auth_record = db.find_user_by_emp_no(manager["emp_no"])
    captured: dict = {}

    orig_sample = db.is_sample_mode
    orig_find = db.find_user_by_emp_no
    orig_get = db._near_miss_improvement_raw
    orig_repo = db.supabase_repository.close_near_miss_report
    db.is_sample_mode = lambda: False
    db.find_user_by_emp_no = lambda emp, **kw: auth_record if str(emp).strip() == manager["emp_no"] else None
    # 종결 인가 판정용 개선조치 조회(평가자 manager 는 None 이어도 can_review 통과 — 하드게이트는 RPC).
    db._near_miss_improvement_raw = lambda rid, **kw: None
    db.supabase_repository.close_near_miss_report = (
        lambda report_id, *, actor_emp_no: (
            captured.update({"report_id": report_id, "actor_emp_no": actor_emp_no})
            or {"status": "CLOSED"}))
    try:
        out = db.close_near_miss_report(5, current_user={"emp_no": manager["emp_no"]})
    finally:
        db.is_sample_mode = orig_sample
        db.find_user_by_emp_no = orig_find
        db._near_miss_improvement_raw = orig_get
        db.supabase_repository.close_near_miss_report = orig_repo

    check("close 는 repo(RPC)로 위임", out and out.get("status") == "CLOSED")
    check("actor_emp_no = 인증 actor 서버귀속", captured.get("actor_emp_no") == manager["emp_no"])
    check("report_id 전달", captured.get("report_id") == 5)


# =========================================================================
# CAPA 작업(저장·제출) 행단위 인가 — 배정된 담당자 허용 / 비담당자 차단 (Phase1 계약 갱신)
#   계약 변경: 이전 "활성 USER 저장·제출 전면 차단(평가 능력 필수)"에서, 배정된 담당자
#   (일반 USER 가능)는 작업 필드 저장·제출 허용, 비담당자·비평가자는 차단으로 바뀌었다.
#   assertion 약화가 아니라 의도 업무흐름(담당자가 조치를 수행)에 맞춘 행단위 인가다.
# =========================================================================
def test_capa_save_submit_capability_gate() -> None:
    print("CAPA 작업 인가: 배정 담당자(USER) 저장·제출 허용 / 비담당자 차단 (Phase1 계약 갱신)")
    _reset()
    assignee = _actor_of_role("USER")
    other = _actor_of_role("USER", exclude=(assignee["emp_no"],))
    manager = _actor_of_role("MANAGER")
    admin = _actor_of_role("ADMIN")
    rid = _evaluated_report(assignee, manager)

    # 미배정 상태에서 담당자 후보(USER)가 스스로 저장 시도 → 차단(배정 선행 필요, 권한 없음).
    excu = raises(lambda: db.upsert_near_miss_improvement(
        rid, {"result_body": "미배정 저장 시도"},
        current_user={"emp_no": assignee["emp_no"]}), ValueError)
    check("미배정 담당자 저장 차단", excu is not None and "권한" in str(excu))
    check("차단 후 개선조치 미생성", db._near_miss_improvement_raw(rid) is None)

    # 평가자(MANAGER)가 담당자를 배정(생성). 배정은 평가자/ADMIN 전용.
    db.upsert_near_miss_improvement(
        rid, {"assignee_emp_no": assignee["emp_no"]}, current_user=manager)
    check("배정 후 개선조치 생성", db._near_miss_improvement_raw(rid) is not None)
    check("배정된 담당자 저장", db._near_miss_improvement_raw(rid)["assignee_emp_no"] == assignee["emp_no"])

    # 배정된 담당자(USER)는 작업 필드 저장 허용(양성).
    db.upsert_near_miss_improvement(
        rid, {"result_body": "담당자 조치결과"}, current_user={"emp_no": assignee["emp_no"]})
    check("배정 담당자 저장 허용", db._near_miss_improvement_raw(rid)["result_body"] == "담당자 조치결과")

    # 다른 USER(비담당자)는 저장 차단(타인 조치 작업 금지).
    exco = raises(lambda: db.upsert_near_miss_improvement(
        rid, {"result_body": "타인 개입"}, current_user={"emp_no": other["emp_no"]}), ValueError)
    check("비담당자 USER 저장 차단", exco is not None and "권한" in str(exco))
    check("비담당자 차단 후 결과 불변",
          db._near_miss_improvement_raw(rid)["result_body"] == "담당자 조치결과")

    # 배정된 담당자(USER) 제출 허용(양성).
    rec = db.submit_near_miss_improvement(rid, current_user={"emp_no": assignee["emp_no"]})
    check("배정 담당자 제출 허용", rec["submit_status"] == "SUBMITTED")

    # 비담당자 USER 제출 차단(다른 rid 로 검증 — 위 rid 는 이미 SUBMITTED).
    _reset()
    rid2 = _evaluated_report(assignee, manager)
    db.upsert_near_miss_improvement(rid2, {"assignee_emp_no": assignee["emp_no"]}, current_user=manager)
    db.upsert_near_miss_improvement(rid2, {"result_body": "결과"}, current_user={"emp_no": assignee["emp_no"]})
    excs = raises(lambda: db.submit_near_miss_improvement(
        rid2, current_user={"emp_no": other["emp_no"]}), ValueError)
    check("비담당자 USER 제출 차단", excs is not None and "권한" in str(excs))
    check("제출 차단 후 DRAFT 유지", db._near_miss_improvement_raw(rid2)["submit_status"] == "DRAFT")

    # ADMIN 은 담당자가 아니어도 작업(저장·제출) 허용(전역 우회).
    db.upsert_near_miss_improvement(rid2, {"result_body": "ADMIN 보정"}, current_user=admin)
    check("ADMIN 작업 저장 허용", db._near_miss_improvement_raw(rid2)["result_body"] == "ADMIN 보정")
    rec2 = db.submit_near_miss_improvement(rid2, current_user=admin)
    check("ADMIN 제출 허용", rec2["submit_status"] == "SUBMITTED")


# =========================================================================
# 배정은 평가자/ADMIN 전용 + 담당자 upsert 는 배정필드 재지정 불가(핵심 보안)
# =========================================================================
def test_assignment_authority_and_field_separation() -> None:
    print("배정은 평가자/ADMIN 만 + 담당자 작업 upsert 는 담당자·확인자 재지정 불가 (Phase1 #2)")
    _reset()
    assignee = _actor_of_role("USER")
    other = _actor_of_role("USER", exclude=(assignee["emp_no"],))
    manager = _actor_of_role("MANAGER")
    rid = _evaluated_report(assignee, manager)

    # 평가자만 배정(생성)할 수 있다. USER 는 생성/배정 불가.
    excu = raises(lambda: db.upsert_near_miss_improvement(
        rid, {"assignee_emp_no": assignee["emp_no"]},
        current_user={"emp_no": assignee["emp_no"]}), ValueError)
    check("USER 는 배정(생성) 불가", excu is not None and "권한" in str(excu))

    # 평가자 배정: 담당자=assignee, 확인자=other.
    db.upsert_near_miss_improvement(rid, {
        "assignee_emp_no": assignee["emp_no"],
        "designated_confirmer_emp_no": other["emp_no"]}, current_user=manager)
    imp = db._near_miss_improvement_raw(rid)
    check("배정 담당자 저장", imp["assignee_emp_no"] == assignee["emp_no"])
    check("배정 확인자 저장", imp["designated_confirmer_emp_no"] == other["emp_no"])

    # 담당자(USER)가 작업 upsert 에 담당자·확인자 재지정을 시도해도 무시된다(배정필드 서버전용).
    db.upsert_near_miss_improvement(rid, {
        "result_body": "조치", "assignee_emp_no": other["emp_no"],
        "designated_confirmer_emp_no": assignee["emp_no"]},
        current_user={"emp_no": assignee["emp_no"]})
    imp2 = db._near_miss_improvement_raw(rid)
    check("담당자 재지정 무시(담당자 불변)", imp2["assignee_emp_no"] == assignee["emp_no"])
    check("확인자 재지정 무시(확인자 불변)", imp2["designated_confirmer_emp_no"] == other["emp_no"])
    check("작업 필드는 반영", imp2["result_body"] == "조치")

    # 평가자는 재배정 가능(배정 권한): 담당자를 other 로 변경.
    db.upsert_near_miss_improvement(rid, {"assignee_emp_no": other["emp_no"]}, current_user=manager)
    check("평가자 재배정 반영", db._near_miss_improvement_raw(rid)["assignee_emp_no"] == other["emp_no"])
    # 재배정 후 이전 담당자(assignee)는 더 이상 작업 불가.
    exco = raises(lambda: db.upsert_near_miss_improvement(
        rid, {"result_body": "이전 담당자 개입"}, current_user={"emp_no": assignee["emp_no"]}), ValueError)
    check("재배정 후 이전 담당자 작업 차단", exco is not None)


# =========================================================================
# 배정/작업 branch 완전분리 + present-only 병합 — 비담당 평가자 작업필드 무시,
# 배정-only 가 조치·결과·기한을 지우지 않음, 부분 upsert 필드 보존 (Phase1 감사 P1)
# =========================================================================
def test_assign_work_branch_full_separation() -> None:
    print("CAPA 배정/작업 branch 완전분리 + present-only(비담당 평가자 작업 무시·배정only 작업 보존) (P1)")
    _reset()
    assignee = _actor_of_role("USER")
    confirmer = _actor_of_role("USER", exclude=(assignee["emp_no"],))
    manager = _actor_of_role("MANAGER")
    admin = _actor_of_role("ADMIN")
    rid = _evaluated_report(assignee, manager)

    # 비담당 평가자(MANAGER) 배정: 같은 payload 에 작업필드를 넣어도 작업 branch 가 닫혀 무시된다.
    db.upsert_near_miss_improvement(rid, {
        "assignee_emp_no": assignee["emp_no"], "result_body": "평가자 작성 시도",
        "action_body": "평가자 조치 시도"}, current_user=manager)
    created = db._near_miss_improvement_raw(rid)
    check("비담당 평가자 배정 반영", created["assignee_emp_no"] == assignee["emp_no"])
    check("비담당 평가자 작업필드(result) 무시", str(created.get("result_body") or "") == "")
    check("비담당 평가자 작업필드(action) 무시", str(created.get("action_body") or "") == "")

    # 담당자(USER)가 작업필드를 채운다(작업 branch).
    db.upsert_near_miss_improvement(rid, {
        "result_body": "담당자 결과", "action_body": "담당자 조치",
        "due_date": "2030-01-31"}, current_user=assignee)
    worked = db._near_miss_improvement_raw(rid)
    check("담당자 작업필드 저장(result)", worked["result_body"] == "담당자 결과")
    check("담당자 작업필드 저장(action)", worked["action_body"] == "담당자 조치")
    check("담당자 작업필드 저장(due)", worked["due_date"] == "2030-01-31")

    # 비담당 평가자가 작업필드 덮어쓰기를 시도해도 무시되고 기존 조치가 보존된다(계약 정정).
    db.upsert_near_miss_improvement(rid, {"result_body": "평가자 덮어쓰기"}, current_user=manager)
    after_mgr = db._near_miss_improvement_raw(rid)
    check("비담당 평가자 작업 덮어쓰기 무시(result 보존)", after_mgr["result_body"] == "담당자 결과")

    # 평가자 배정-only(확인자만) payload 가 조치·결과·기한을 빈값으로 지우지 않는다(present-only).
    db.upsert_near_miss_improvement(rid, {
        "designated_confirmer_emp_no": confirmer["emp_no"]}, current_user=manager)
    a = db._near_miss_improvement_raw(rid)
    check("배정-only 확인자 반영", a["designated_confirmer_emp_no"] == confirmer["emp_no"])
    check("배정-only 가 조치결과 보존", a["result_body"] == "담당자 결과")
    check("배정-only 가 조치내용 보존", a["action_body"] == "담당자 조치")
    check("배정-only 가 기한 보존", a["due_date"] == "2030-01-31")
    check("배정-only 담당자 불변", a["assignee_emp_no"] == assignee["emp_no"])

    # 담당자 작업 upsert 가 result 만 담아도 기존 action/due 를 지우지 않는다(작업 present-only).
    db.upsert_near_miss_improvement(rid, {"result_body": "결과 보완"}, current_user=assignee)
    p = db._near_miss_improvement_raw(rid)
    check("작업 부분수정 result 갱신", p["result_body"] == "결과 보완")
    check("작업 부분수정 action 보존", p["action_body"] == "담당자 조치")
    check("작업 부분수정 due 보존", p["due_date"] == "2030-01-31")

    # ADMIN 은 두 branch 동시(배정+작업)를 한 payload 로 쓸 수 있다.
    db.upsert_near_miss_improvement(rid, {
        "assignee_emp_no": confirmer["emp_no"], "result_body": "ADMIN 동시수정"}, current_user=admin)
    both = db._near_miss_improvement_raw(rid)
    check("ADMIN 동시 배정 변경", both["assignee_emp_no"] == confirmer["emp_no"])
    check("ADMIN 동시 작업 변경", both["result_body"] == "ADMIN 동시수정")


# =========================================================================
# 지정 확인자(일반 USER) 확인 허용 + 자기확인 차단
# =========================================================================
def test_designated_confirmer_user_can_confirm() -> None:
    print("지정 확인자(일반 USER) 확인 허용 + 담당자 자기확인 차단 (Phase1 매트릭스)")
    _reset()
    assignee = _actor_of_role("USER")
    confirmer = _actor_of_role("USER", exclude=(assignee["emp_no"],))
    outsider = _actor_of_role("USER", exclude=(assignee["emp_no"], confirmer["emp_no"]))
    manager = _actor_of_role("MANAGER")
    rid = _evaluated_report(assignee, manager)

    # 배정: 담당자=assignee, 지정 확인자=confirmer(일반 USER). 담당자가 작업·제출.
    db.upsert_near_miss_improvement(rid, {
        "assignee_emp_no": assignee["emp_no"],
        "designated_confirmer_emp_no": confirmer["emp_no"]}, current_user=manager)
    db.upsert_near_miss_improvement(rid, {"result_body": "결과"}, current_user={"emp_no": assignee["emp_no"]})
    db.submit_near_miss_improvement(rid, current_user={"emp_no": assignee["emp_no"]})

    # 관계없는 USER 는 확인 불가(검토 권한 없음).
    exco = raises(lambda: db.confirm_near_miss_improvement(
        rid, current_user={"emp_no": outsider["emp_no"]}), ValueError)
    check("관계없는 USER 확인 차단", exco is not None and "권한" in str(exco))

    # 담당자 본인 자기확인 차단(지정 확인자가 따로 있어도).
    excsc = raises(lambda: db.confirm_near_miss_improvement(
        rid, current_user={"emp_no": assignee["emp_no"]}), ValueError)
    check("담당자 자기확인 차단", excsc is not None)
    check("자기확인 차단 후 PENDING 유지",
          db._near_miss_improvement_raw(rid)["confirm_status"] == "PENDING")

    # 지정 확인자(일반 USER) 확인 허용 + 서버 귀속.
    rec = db.confirm_near_miss_improvement(rid, current_user={"emp_no": confirmer["emp_no"]})
    check("지정 확인자(USER) 확인 허용", rec["confirm_status"] == "CONFIRMED")
    check("확인 행위자=지정 확인자 서버귀속", rec["confirmed_by_emp_no"] == confirmer["emp_no"])

    # 지정 확인자(USER)는 종결도 가능(검토 권한 = 확인·재조치·종결).
    out = db.close_near_miss_report(rid, current_user={"emp_no": confirmer["emp_no"]})
    check("지정 확인자(USER) 종결 허용", out["status"] == "CLOSED")


# =========================================================================
# actor-aware 개별 조회·큐 스코핑 — 담당자/확인자/평가자만, report_id 로만 접근 금지
# =========================================================================
def test_actor_aware_access_and_queue_scoping() -> None:
    print("actor-aware 조회: 담당자·지정 확인자·평가자만 개별 접근 / 큐 스코핑 (Phase1 #3)")
    _reset()
    assignee = _actor_of_role("USER")
    confirmer = _actor_of_role("USER", exclude=(assignee["emp_no"],))
    outsider = _actor_of_role("USER", exclude=(assignee["emp_no"], confirmer["emp_no"]))
    manager = _actor_of_role("MANAGER")
    rid = _evaluated_report(assignee, manager)
    db.upsert_near_miss_improvement(rid, {
        "assignee_emp_no": assignee["emp_no"],
        "designated_confirmer_emp_no": confirmer["emp_no"]}, current_user=manager)

    # 개별 조회 스코핑: 담당자·지정 확인자·평가자는 보이고, 무관 USER 는 None(미노출).
    check("담당자 개별 조회 허용",
          db.get_near_miss_improvement(rid, current_user={"emp_no": assignee["emp_no"]}) is not None)
    check("지정 확인자 개별 조회 허용",
          db.get_near_miss_improvement(rid, current_user={"emp_no": confirmer["emp_no"]}) is not None)
    check("평가자 개별 조회 허용",
          db.get_near_miss_improvement(rid, current_user=manager) is not None)
    check("무관 USER 개별 조회 미노출(None)",
          db.get_near_miss_improvement(rid, current_user={"emp_no": outsider["emp_no"]}) is None)
    # 스코핑 없는 원본은 명시적 private helper 로만(의도된 unscoped, 내부 인가·집계 전용).
    # 외부용 get_near_miss_improvement 는 current_user 필수라 fail-open 경로가 없다.
    check("명시적 raw 조회는 원본(unscoped)", db._near_miss_improvement_raw(rid) is not None)
    excn = raises(lambda: db.get_near_miss_improvement(rid), TypeError)
    check("외부 조회는 current_user 필수(fail-open 제거)", excn is not None)

    # 큐 스코핑: 무관 USER 는 자기 큐에서 이 개선조치를 보지 못한다.
    scoped_assignee = db.list_near_miss_improvements([rid], current_user={"emp_no": assignee["emp_no"]})
    scoped_confirmer = db.list_near_miss_improvements([rid], current_user={"emp_no": confirmer["emp_no"]})
    scoped_outsider = db.list_near_miss_improvements([rid], current_user={"emp_no": outsider["emp_no"]})
    scoped_manager = db.list_near_miss_improvements([rid], current_user=manager)
    check("담당자 큐에 포함", str(rid) in scoped_assignee)
    check("지정 확인자 큐에 포함", str(rid) in scoped_confirmer)
    check("평가자 큐에 전체 포함", str(rid) in scoped_manager)
    check("무관 USER 큐에서 제외", str(rid) not in scoped_outsider)


# =========================================================================
# 재배정 경합(조건부 UPDATE) — supabase 작업 경로에 담당자=행위자 조건 결합
# =========================================================================
def test_work_path_conditional_reassignment_race() -> None:
    print("작업 경로 조건부 UPDATE: 담당자 upsert/submit 에 assignee_user_id=행위자 결합 (Phase1 #4)")
    manager = _actor_of_role("MANAGER")
    # supabase 경로에서 담당자(USER)가 작업할 때 repo 로 담당자 제한 사번이 전달되는지 확인한다.
    assignee_rec = db.find_user_by_emp_no("1003")
    imp_natural = {"assignee_emp_no": "1003", "designated_confirmer_emp_no": ""}
    captured: dict = {}

    orig_sample = db.is_sample_mode
    orig_find = db.find_user_by_emp_no
    orig_get = db._near_miss_improvement_raw
    orig_report = db.get_near_miss_report
    orig_upsert = db.supabase_repository.upsert_near_miss_improvement
    orig_submit = db.supabase_repository.submit_near_miss_improvement
    db.is_sample_mode = lambda: False
    db.find_user_by_emp_no = lambda emp, **kw: assignee_rec if str(emp).strip() == "1003" else None
    db.get_near_miss_report = lambda rid: {"id": rid, "status": "EVALUATED"}
    db._near_miss_improvement_raw = lambda rid, **kw: dict(imp_natural)
    db.supabase_repository.upsert_near_miss_improvement = (
        lambda report_id, payload, *, updated_by=None, allow_assignment=False,
        restrict_to_assignee_emp_no=None: (
            captured.update({"u_allow": allow_assignment, "u_restrict": restrict_to_assignee_emp_no})
            or {"submit_status": "DRAFT"}))
    db.supabase_repository.submit_near_miss_improvement = (
        lambda report_id, *, updated_by=None, restrict_to_assignee_emp_no=None: (
            captured.update({"s_restrict": restrict_to_assignee_emp_no})
            or {"submit_status": "SUBMITTED"}))
    try:
        # 담당자(1003, USER) 작업 upsert → 배정권한 없음 + 담당자 제한 결합.
        db.upsert_near_miss_improvement(9, {"result_body": "결과"}, current_user={"emp_no": "1003"})
        db.submit_near_miss_improvement(9, current_user={"emp_no": "1003"})
    finally:
        db.is_sample_mode = orig_sample
        db.find_user_by_emp_no = orig_find
        db._near_miss_improvement_raw = orig_get
        db.get_near_miss_report = orig_report
        db.supabase_repository.upsert_near_miss_improvement = orig_upsert
        db.supabase_repository.submit_near_miss_improvement = orig_submit

    check("작업 upsert 는 배정 미허용(allow_assignment=False)", captured.get("u_allow") is False)
    check("작업 upsert 담당자 제한 결합(=행위자)", captured.get("u_restrict") == "1003")
    check("제출 담당자 제한 결합(=행위자)", captured.get("s_restrict") == "1003")


# =========================================================================
# report_id 불변 sample parity (종합감사 P1-B)
# =========================================================================
def test_report_id_immutable_sample() -> None:
    print("sample: 개선조치 report_id 이동 불가(부모 결속 불변, 종합감사 P1-B parity)")
    _reset()
    reporter = _actor_of_role("USER")
    manager = _actor_of_role("MANAGER")
    admin = _actor_of_role("ADMIN")
    rid_a = _evaluated_report(reporter, manager)
    rid_b = _evaluated_report(reporter, manager)
    # ADMIN 은 배정·작업 두 branch 를 모두 열 수 있어(is_admin) 한 payload 로 배정+작업필드
    # 를 함께 쓸 수 있다 — report_id 불변 검증에 작업필드 변경이 필요하므로 ADMIN 을 쓴다.
    db.upsert_near_miss_improvement(rid_a, {
        "assignee_emp_no": reporter["emp_no"], "result_body": "A 조치"}, current_user=admin)

    # payload 로 report_id 를 rid_b 로 바꾸려 해도 server-field 로 제거되어 이동하지 않는다.
    rec = db.upsert_near_miss_improvement(rid_a, {
        "report_id": rid_b, "result_body": "A 조치 수정"}, current_user=admin)
    check("upsert 후에도 report_id 는 rid_a 유지", str(rec["report_id"]) == str(rid_a))
    check("rid_b 로 개선조치가 이동/생성되지 않음", db._near_miss_improvement_raw(rid_b) is None)
    check("rid_a 개선조치 그대로 존재", db._near_miss_improvement_raw(rid_a) is not None)
    check("rid_a 결과는 수정 반영(이동 아님)",
          db._near_miss_improvement_raw(rid_a)["result_body"] == "A 조치 수정")


# =========================================================================
# 007 SQL 계약(정적) — 테이블/제약/RPC/trigger/하드닝 존재
# =========================================================================
def test_migration_007_sql_contract() -> None:
    print("007_near_miss_improvement.sql 정적 계약")
    path = ROOT / "supabase" / "migrations" / "007_near_miss_improvement.sql"
    check("007 파일 존재", path.exists())
    sql = path.read_text(encoding="utf-8")
    low = sql.lower()

    check("near_miss_improvements 테이블(guarded)",
          "create table if not exists public.near_miss_improvements" in low)
    check("report_id UNIQUE 1:1", "near_miss_improvement_report_uniq unique (report_id)" in low)
    check("report FK on delete restrict",
          "report_id bigint not null references public.near_miss_reports(id) on delete restrict" in low)

    # 핵심 컬럼
    for col in (
        "assignee_user_id", "designated_confirmer_user_id", "confirmed_by_user_id",
        "rejected_by_user_id", "action_body", "result_body", "due_date",
        "submit_status", "confirm_status", "submitted_at", "confirmed_at",
        "rejected_at", "revision_note", "is_active",
    ):
        check(f"컬럼 {col} 정의", col in low)

    # 통제코드·정합·자기확인 제약
    for cons in (
        "near_miss_improvement_submit_status_check",
        "near_miss_improvement_confirm_status_check",
        "near_miss_improvement_submit_consistency",
        "near_miss_improvement_confirm_consistency",
        "near_miss_improvement_no_self_confirm",
    ):
        check(f"제약 {cons} 존재", cons in low)
    check("자기확인 방지 CHECK 표현",
          "confirmed_by_user_id <> assignee_user_id" in low)

    # near_miss_reports 보완요청 컬럼(P1-4)
    for col in ("revision_request_reason", "revision_requested_by_user_id", "revision_requested_at"):
        check(f"보완요청 컬럼 {col}", col in low)

    # 종결 RPC + SECURITY DEFINER 하드닝
    check("close RPC 정의", "function public.close_near_miss_report(bigint, text)" in low)
    check("RPC security definer", "security definer" in low)
    check("RPC search_path 고정", "set search_path" in low)
    check("RPC EXECUTE 회수(public/anon/authenticated)",
          "revoke execute on function public.close_near_miss_report(bigint, text) from public" in low
          and "from anon" in low and "from authenticated" in low)
    check("RPC service_role 부여",
          "grant execute on function public.close_near_miss_report(bigint, text) to service_role" in low)

    # 하드게이트·강등방어 trigger
    check("종결 하드게이트 trigger", "near_miss_close_requires_confirmed_capa" in low)
    check("종결 trigger before update on reports",
          "before update on public.near_miss_reports" in low)
    check("강등방어 trigger", "near_miss_improvement_guard_closed_parent" in low)
    check("강등방어 before update or delete",
          "before update or delete on public.near_miss_improvements" in low)

    # P1-3: 종결 trigger 는 EVALUATED 에서만 CLOSED 를 허용한다(유일 소스 강제).
    check("종결 trigger EVALUATED 소스 강제",
          "old.status is distinct from 'evaluated'" in low)
    # P1-1: 강등방어 trigger 는 report_id 이동(부모 재지정)도 차단한다.
    check("강등방어 report_id 불변",
          "new.report_id is distinct from old.report_id" in low)

    # 종합감사 P1-B: report_id 불변은 CLOSED 분기와 무관하게 무조건 강제해야 한다.
    #   전용 BEFORE UPDATE trigger(near_miss_improvement_report_id_immutable)가 존재하고,
    #   그 함수 본문은 부모 상태(closed/v_parent_status)와 무관한 무조건 경로여야 한다.
    check("report_id 불변 전용 trigger 정의",
          "function public.near_miss_improvement_report_id_immutable()" in low)
    check("report_id 불변 trigger before update on improvements",
          "before update on public.near_miss_improvements" in low
          and "near_miss_improvement_report_id_immutable()" in low)
    _imm_start = low.find("create or replace function public.near_miss_improvement_report_id_immutable()")
    _imm_body = low[_imm_start:low.find("$$;", _imm_start)] if _imm_start >= 0 else ""
    check("report_id 불변 검사가 전용 함수 본문에 존재",
          "new.report_id is distinct from old.report_id" in _imm_body
          and "raise exception" in _imm_body)
    check("report_id 불변이 무조건 경로(CLOSED/부모상태 분기 밖)",
          "closed" not in _imm_body and "v_parent_status" not in _imm_body)
    # P1-2: close RPC·강등방어·재개 RPC 는 FOR UPDATE 로 직렬화한다(락 순서 improvement→report).
    check("FOR UPDATE 직렬화(≥3)", low.count("for update") >= 3)

    # P1-4: 재개 원자 RPC + 하드닝(EXECUTE 회수·service_role 부여·EVALUATED→IN_REVIEW).
    check("reopen RPC 정의", "function public.reopen_near_miss_report(bigint, text)" in low)
    check("SECURITY DEFINER 함수 ≥4(trigger 2 + rpc 2)", low.count("security definer") >= 4)
    check("reopen RPC EXECUTE 회수",
          "revoke execute on function public.reopen_near_miss_report(bigint, text) from public" in low
          and "from anon" in low and "from authenticated" in low)
    check("reopen RPC service_role 부여",
          "grant execute on function public.reopen_near_miss_report(bigint, text) to service_role" in low)
    check("reopen RPC EVALUATED→IN_REVIEW", "status = 'in_review'" in low)

    # P2-2: 보완요청 all-or-none CHECK + REJECTED 반려사유 필수.
    check("보완요청 all-or-none CHECK",
          "near_miss_reports_revision_request_all_or_none" in low)
    check("REJECTED revision_note 필수", "btrim(coalesce(revision_note" in low)

    # P2-1: 강화된 스키마 assertion(타입·NOT NULL·FK·CHECK 정의).
    check("스키마 assertion 타입/NOT NULL", "atttypid = 'bigint'::regtype" in low)
    check("스키마 assertion FK 존재", "confrelid = 'public.near_miss_reports'::regclass" in low)
    check("스키마 assertion CHECK 정의", "pg_get_constraintdef" in low)

    # P2-3: 신뢰 경계·적용게이트 owner/public 주석.
    check("신뢰 경계 주석", "신뢰 경계" in sql)

    # 인덱스
    check("종결대기 인덱스", "near_miss_improvement_confirm_active_idx" in low)
    check("overdue 인덱스", "near_miss_improvement_overdue_idx" in low)

    # 스키마 assertion(부분 기존구조 묵인 방지) + 006 전제 assertion
    check("006 전제 assertion", "near_miss_reports" in low and "raise exception" in low)
    check("near_miss_improvements 스키마 assertion", "스키마 불일치" in sql or "schema" in low)

    # 안전 관행: RLS enable, no-drop 테이블(롤백 주석 제외)
    check("RLS enable", "enable row level security" in low)
    body_wo_rollback = "\n".join(
        l for l in low.splitlines() if "drop table if exists public.near_miss_improvements" not in l)
    check("테이블 drop 없음(재실행 안전)", "drop table" not in body_wo_rollback)


# =========================================================================
# 단건 조회 존재 oracle 봉함(P2) — 미인가/미상 actor 는 CAPA 유무와 무관하게 None
# =========================================================================
def test_get_improvement_existence_oracle_sealed() -> None:
    print("단건 조회 존재 oracle 봉함: 미인증/미상/무권한 actor 는 CAPA 유무와 무관하게 None")
    _reset()
    assignee = _actor_of_role("USER")
    manager = _actor_of_role("MANAGER")
    rid_present = _evaluated_report(assignee, manager)
    db.upsert_near_miss_improvement(
        rid_present, {"assignee_emp_no": assignee["emp_no"]}, current_user=manager)
    rid_absent = _evaluated_report(assignee, manager)  # 개선조치 미생성(부재)
    check("전제: present rid 에 CAPA 존재", db._near_miss_improvement_raw(rid_present) is not None)
    check("전제: absent rid 에 CAPA 부재", db._near_miss_improvement_raw(rid_absent) is None)

    # current_user=None: 존재/부재가 동일하게 None — 예전엔 존재→actor 확정 예외/부재→None 으로
    # 갈려 존재 oracle 이었다. 이제 예외로 존재를 누설하지 않는다.
    check("None actor · CAPA 존재 → None(예외 아님)",
          db.get_near_miss_improvement(rid_present, current_user=None) is None)
    check("None actor · CAPA 부재 → None",
          db.get_near_miss_improvement(rid_absent, current_user=None) is None)

    # 미상 사번(존재하지 않는 사용자) actor: 존재/부재 동일하게 None(actor 확정 실패=None).
    ghost = {"emp_no": "___no_such_emp___"}
    check("미상 actor · CAPA 존재 → None",
          db.get_near_miss_improvement(rid_present, current_user=ghost) is None)
    check("미상 actor · CAPA 부재 → None",
          db.get_near_miss_improvement(rid_absent, current_user=ghost) is None)

    # 무권한 USER(유효 사번, 무관자): 존재/부재 동일하게 None(can_access False).
    outsider = _actor_of_role("USER", exclude=(assignee["emp_no"],))
    check("무권한 USER · CAPA 존재 → None",
          db.get_near_miss_improvement(rid_present, current_user=outsider) is None)
    check("무권한 USER · CAPA 부재 → None",
          db.get_near_miss_improvement(rid_absent, current_user=outsider) is None)

    # 대조(정상 경로 회귀): 담당자 본인은 존재 시 행을 반환한다(authorized+present 만 노출).
    check("담당자 · CAPA 존재 → 행 반환",
          db.get_near_miss_improvement(rid_present, current_user=assignee) is not None)


# =========================================================================
# 개선조치 접근 판정 facade (Phase2 nav/화면 진입) — has_near_miss_improvement_access
# =========================================================================
def test_has_improvement_access() -> None:
    print("has_near_miss_improvement_access: 평가자/ADMIN 즉시 True·배정 USER·fail-closed·007 게이트")
    _reset()
    assignee = _actor_of_role("USER")
    confirmer = _actor_of_role("USER", exclude=(assignee["emp_no"],))
    outsider = _actor_of_role("USER", exclude=(assignee["emp_no"], confirmer["emp_no"]))
    manager = _actor_of_role("MANAGER")
    admin = _actor_of_role("ADMIN")
    inactive = _actor_of_role("USER", active=False)
    rid = _evaluated_report(assignee, manager)
    db.upsert_near_miss_improvement(rid, {
        "assignee_emp_no": assignee["emp_no"],
        "designated_confirmer_emp_no": confirmer["emp_no"]}, current_user=manager)

    # 평가자/ADMIN 즉시 True.
    check("ADMIN 접근 True", db.has_near_miss_improvement_access(admin) is True)
    check("평가자(MANAGER) 접근 True", db.has_near_miss_improvement_access(manager) is True)

    # 배정된 USER(담당자·지정 확인자)는 007 READY(sample 항상 READY)에서 True.
    check("배정 담당자 USER 접근 True",
          db.has_near_miss_improvement_access({"emp_no": assignee["emp_no"]}) is True)
    check("지정 확인자 USER 접근 True",
          db.has_near_miss_improvement_access({"emp_no": confirmer["emp_no"]}) is True)

    # 미배정 USER 는 False(배정 없음).
    check("미배정 USER 접근 False",
          db.has_near_miss_improvement_access({"emp_no": outsider["emp_no"]}) is False)

    # fail-closed: 무인증/미상 사번/비활성 사용자.
    check("current_user=None 접근 False", db.has_near_miss_improvement_access(None) is False)
    check("미상 사번 접근 False",
          db.has_near_miss_improvement_access({"emp_no": "___no_such_emp___"}) is False)
    check("비활성 사용자 접근 False", db.has_near_miss_improvement_access(inactive) is False)

    # 비활성 개선조치는 배정 근거로 치지 않는다(활성 조건).
    store = db._nmi_store()
    saved = {k: dict(v) for k, v in store.items()}
    try:
        for rec in store.values():
            rec["is_active"] = False
        check("비활성 개선조치만 있으면 배정 USER 도 False",
              db.has_near_miss_improvement_access({"emp_no": assignee["emp_no"]}) is False)
        check("비활성이라도 평가자는 여전히 True(단축)",
              db.has_near_miss_improvement_access(manager) is True)
    finally:
        store.clear()
        store.update(saved)

    # 007 미준비(NOT_READY): 배정 기반 부분은 False → 평가자/ADMIN 만 True.
    orig_probe = db.near_miss_improvement_schema_probe
    db.near_miss_improvement_schema_probe = lambda **kw: sr.READINESS_NOT_READY
    try:
        check("007 NOT_READY · 배정 USER 접근 False",
              db.has_near_miss_improvement_access({"emp_no": assignee["emp_no"]}) is False)
        check("007 NOT_READY · 평가자 접근 True(probe 이전 단축)",
              db.has_near_miss_improvement_access(manager) is True)
        check("007 NOT_READY · ADMIN 접근 True",
              db.has_near_miss_improvement_access(admin) is True)
        # PROBE_ERROR 도 배정 부분은 False(안전·비크래시).
        db.near_miss_improvement_schema_probe = lambda **kw: sr.READINESS_PROBE_ERROR
        check("007 PROBE_ERROR · 배정 USER 접근 False(안전)",
              db.has_near_miss_improvement_access({"emp_no": assignee["emp_no"]}) is False)
    finally:
        db.near_miss_improvement_schema_probe = orig_probe

    # 평가자/ADMIN 단축: 배정 조회를 절대 호출하지 않는다(예외를 심어도 True 유지).
    orig_helper = db._has_active_improvement_assignment
    def _boom(*a, **k):
        raise AssertionError("평가자/ADMIN 은 배정 조회를 호출하면 안 된다(단축)")
    db._has_active_improvement_assignment = _boom
    try:
        check("평가자 단축(배정 조회 미호출) True", db.has_near_miss_improvement_access(manager) is True)
        check("ADMIN 단축(배정 조회 미호출) True", db.has_near_miss_improvement_access(admin) is True)
    finally:
        db._has_active_improvement_assignment = orig_helper


def test_has_improvement_access_supabase_query_contract() -> None:
    print("has_active_improvement_assignment(supabase): OR(담당자|확인자)+is_active count 경량 쿼리")
    captured: dict = {}

    class _Q:
        def select(self, *a, **k):
            captured["select_args"] = a
            captured["select_kwargs"] = k
            return self

        def or_(self, expr):
            captured["or_"] = expr
            return self

        def eq(self, col, val):
            captured.setdefault("eq", []).append((col, val))
            return self

        def limit(self, n):
            captured["limit"] = n
            return self

        def execute(self):
            captured["executed"] = True
            return type("R", (), {"count": 1, "data": []})()

    orig_client = sr.client
    orig_user_maps = sr._user_maps
    sr.client = lambda: type("C", (), {"table": lambda self, n: (captured.__setitem__("table", n) or _Q())})()
    sr._user_maps = lambda emp_nos=None: ({"1003": 42}, {"42": "1003"})
    try:
        res = sr.has_active_improvement_assignment("1003")
    finally:
        sr.client = orig_client
        sr._user_maps = orig_user_maps

    check("count>0 → True", res is True)
    check("대상 테이블 = near_miss_improvements", captured.get("table") == sr.NEAR_MISS_IMPROVEMENT_TABLE)
    check("count=exact select", captured.get("select_kwargs", {}).get("count") == "exact")
    check("OR 필터에 담당자 user_id", "assignee_user_id.eq.42" in captured.get("or_", ""))
    check("OR 필터에 지정 확인자 user_id", "designated_confirmer_user_id.eq.42" in captured.get("or_", ""))
    check("is_active=True eq 결합", ("is_active", True) in captured.get("eq", []))
    check("limit 1 경량 조회", captured.get("limit") == 1)

    # 미상 사번(user_id 해석 실패)은 쿼리 없이 False(fail-closed).
    captured.clear()
    sr.client = lambda: type("C", (), {"table": lambda self, n: (captured.__setitem__("executed", True) or _Q())})()
    sr._user_maps = lambda emp_nos=None: ({}, {})
    try:
        res2 = sr.has_active_improvement_assignment("___ghost___")
    finally:
        sr.client = orig_client
        sr._user_maps = orig_user_maps
    check("미상 사번 → False(fail-closed)", res2 is False)
    check("미상 사번 → 쿼리 미실행", captured.get("executed") is None)


# =========================================================================
# 접근 facade: actor 권위 조회 데이터소스 오류 → False(비크래시) (P2)
# =========================================================================
def test_access_facade_folds_actor_datasource_error() -> None:
    print("has_near_miss_improvement_access: actor 권위 조회 데이터소스 오류 → False(비크래시, 예외 전파 안 함)")
    _reset()
    orig_lookup = db.find_user_by_emp_no

    def _boom(emp_no, use_cache=True):
        raise sr.SupabaseDataError("일시 데이터소스 오류(테스트)")

    db.find_user_by_emp_no = _boom
    try:
        # nav/route 매 렌더 게이트: 권위 조회가 데이터소스 오류여도 예외를 올리지 않고 False.
        result = db.has_near_miss_improvement_access({"emp_no": "1003"})
        check("데이터소스 오류 시 False 반환", result is False)
        check("예외를 전파하지 않음(비크래시)", isinstance(result, bool))
    finally:
        db.find_user_by_emp_no = orig_lookup


# =========================================================================
# 무변경(no-op) upsert status 강등 방지(P2) — sample: 빈 작업/배정 본문은 상태 보존
# =========================================================================
def test_noop_upsert_preserves_status_sample() -> None:
    print("sample no-op upsert: 빈 작업/배정 본문은 status 보존 / 실변경은 DRAFT 초기화 (P2 무결성)")
    _reset()
    assignee = _actor_of_role("USER")
    confirmer = _actor_of_role("USER", exclude=(assignee["emp_no"],))
    manager = _actor_of_role("MANAGER")
    rid = _evaluated_report(assignee, manager)
    db.upsert_near_miss_improvement(rid, {
        "assignee_emp_no": assignee["emp_no"],
        "designated_confirmer_emp_no": confirmer["emp_no"]}, current_user=manager)
    db.upsert_near_miss_improvement(
        rid, {"result_body": "조치 결과"}, current_user={"emp_no": assignee["emp_no"]})
    db.submit_near_miss_improvement(rid, current_user={"emp_no": assignee["emp_no"]})
    check("전제: SUBMITTED", db._near_miss_improvement_raw(rid)["submit_status"] == "SUBMITTED")

    # 비담당자 평가자(manager)의 work-only payload → 파사드가 작업필드 전량 strip → 빈 update.
    # no-op 이므로 status 를 강등하지 않는다(예전엔 SUBMITTED→DRAFT 로 강등되던 결함).
    db.upsert_near_miss_improvement(rid, {"result_body": "몰래 수정"}, current_user=manager)
    after = db._near_miss_improvement_raw(rid)
    check("no-op(비담당자 work-only): submit_status 보존(SUBMITTED)", after["submit_status"] == "SUBMITTED")
    check("no-op: 작업본문 불가침(보존)", after["result_body"] == "조치 결과")
    check("no-op: submitted_at 보존", after["submitted_at"] is not None)

    # 담당자 본인이 기존과 동일한 값으로 저장(present-only 로 병합되나 값 무변경) → 값 비교로
    # 전 무변경이므로 레코드·status·submitted_at·updated_at 모두 보존(no-op, 리포지토리 미호출
    # 동형). 예전엔 키 존재만으로 강등되거나 감사시각이 갱신됐다.
    before_ua = db._near_miss_improvement_raw(rid)["updated_at"]
    db.upsert_near_miss_improvement(
        rid, {"result_body": "조치 결과"}, current_user={"emp_no": assignee["emp_no"]})
    same = db._near_miss_improvement_raw(rid)
    check("동일값 저장(작업필드): submit_status 보존(SUBMITTED)", same["submit_status"] == "SUBMITTED")
    check("동일값 저장: submitted_at 보존", same["submitted_at"] is not None)
    check("동일값 저장: updated_at 무변경(no-op·감사 미갱신)", same["updated_at"] == before_ua)
    # 평가자가 동일 담당자·확인자로 재배정(값 무변경) → status 보존(동일 재배정도 무변경).
    db.upsert_near_miss_improvement(rid, {
        "assignee_emp_no": assignee["emp_no"],
        "designated_confirmer_emp_no": confirmer["emp_no"]}, current_user=manager)
    same2 = db._near_miss_improvement_raw(rid)
    check("동일 재배정: submit_status 보존(SUBMITTED)", same2["submit_status"] == "SUBMITTED")
    check("동일 재배정: submitted_at 보존", same2["submitted_at"] is not None)

    # 담당자 본인의 실제 작업 변경 → 기존 정책대로 DRAFT/PENDING 초기화(문서화 불변식).
    db.upsert_near_miss_improvement(
        rid, {"result_body": "결과 보완"}, current_user={"emp_no": assignee["emp_no"]})
    reset = db._near_miss_improvement_raw(rid)
    check("실변경: submit_status DRAFT 초기화", reset["submit_status"] == "DRAFT")
    check("실변경: confirm_status PENDING", reset["confirm_status"] == "PENDING")
    check("실변경: submitted_at 해제(None)", reset["submitted_at"] is None)
    check("실변경: result_body 반영", reset["result_body"] == "결과 보완")

    # 확인(CONFIRMED) CAPA 강등 차단 회귀 유지: 재제출·확인 후 편집은 여전히 예외(강등 불가).
    db.submit_near_miss_improvement(rid, current_user={"emp_no": assignee["emp_no"]})
    db.confirm_near_miss_improvement(rid, current_user={"emp_no": confirmer["emp_no"]})
    excc = raises(lambda: db.upsert_near_miss_improvement(
        rid, {"result_body": "확인 후 수정"}, current_user={"emp_no": assignee["emp_no"]}), ValueError)
    check("확인 CAPA 는 편집 불가(강등 차단 회귀)", excc is not None)
    check("확인 CAPA status 보존(CONFIRMED)",
          db._near_miss_improvement_raw(rid)["confirm_status"] == "CONFIRMED")


# =========================================================================
# 무변경(no-op) upsert status 강등 방지(P2) — supabase 편집 UPDATE payload 검증(parity)
# =========================================================================
def test_noop_upsert_preserves_status_supabase() -> None:
    print("supabase 편집 upsert: 무변경 필드 UPDATE 제외·전무변경 no-op(미호출) / 실변경만 변경필드+상태초기화")
    existing = {
        "report_id": 5, "assignee_user_id": 10, "designated_confirmer_user_id": 20,
        "submit_status": "SUBMITTED", "confirm_status": "PENDING",
        "submitted_at": "2026-07-20T00:00:00Z",
        "action_body": "기존조치", "result_body": "기존결과", "due_date": "2026-08-01",
        "updated_by": "orig", "updated_at": "2026-07-20T00:00:00Z",
    }
    calls: dict = {"update": 0}
    captured: dict = {"updates": None}

    class _Builder:
        def update(self, updates):
            captured["updates"] = dict(updates)
            return self
        def eq(self, *a, **k): return self
        def neq(self, *a, **k): return self
        def execute(self):
            return type("R", (), {"data": [dict(existing, **captured["updates"])]})()

    class _Table:
        def update(self, updates):
            calls["update"] += 1  # repository UPDATE 실제 호출 횟수(무변경 no-op 은 0 이어야 함).
            return _Builder().update(updates)

    orig_ready = sr.near_miss_improvement_extensions_ready
    orig_raw = sr._nmi_raw
    orig_natural = sr._near_miss_improvement_natural
    orig_client = sr.client
    sr.near_miss_improvement_extensions_ready = lambda: True
    sr._nmi_raw = lambda rid: dict(existing)
    sr._near_miss_improvement_natural = lambda rows: list(rows)  # _user_maps 회피(client 불필요)
    sr.client = lambda: type("C", (), {"table": lambda self, n: _Table()})()
    try:
        # (a) 전 무변경(빈 payload: 비담당자 평가자 work-only 가 파사드에서 strip 된 상태 미러) →
        #     repository UPDATE 미호출·성공 no-op(updated_by/updated_at·상태 무변경).
        out_empty = sr.upsert_near_miss_improvement(5, {}, updated_by="X", allow_assignment=False)
        check("빈 payload: repository UPDATE 미호출(no-op)", calls["update"] == 0)
        check("빈 payload: updated_by 무변경(감사 미갱신)", out_empty.get("updated_by") == "orig")
        check("빈 payload: submit_status 보존(SUBMITTED)", out_empty.get("submit_status") == "SUBMITTED")
        check("빈 payload: submitted_at 보존", out_empty.get("submitted_at") == existing["submitted_at"])

        # (b) 동일값(present 이지만 저장값과 같음) → 값 비교로 전 무변경 → UPDATE 미호출·no-op.
        out_same = sr.upsert_near_miss_improvement(
            5, {"result_body": "기존결과", "action_body": "기존조치"},
            updated_by="X", allow_assignment=False)
        check("동일값 저장: repository UPDATE 미호출(0회)", calls["update"] == 0)
        check("동일값 저장: updated_at 무변경(no-op)", out_same.get("updated_at") == existing["updated_at"])
        check("동일값 저장: submit_status 보존(SUBMITTED)", out_same.get("submit_status") == "SUBMITTED")

        # (c) 실변경(작업필드 1개만 변경, 나머지는 동일값 동봉) → UPDATE 1회, payload 에 변경 필드만
        #     싣고 무변경 필드는 제외한다(phantom rewrite 방지).
        captured["updates"] = None
        sr.upsert_near_miss_improvement(
            5, {"result_body": "새 결과", "action_body": "기존조치", "due_date": "2026-08-01"},
            updated_by="X", allow_assignment=False)
        check("실변경: repository UPDATE 1회 호출", calls["update"] == 1)
        upd = captured["updates"]
        check("실변경: 변경 필드(result_body) UPDATE 포함", upd.get("result_body") == "새 결과")
        check("실변경: 무변경 필드(action_body) UPDATE 제외", "action_body" not in upd)
        check("실변경: 무변경 필드(due_date) UPDATE 제외", "due_date" not in upd)
        check("실변경: submit_status=DRAFT 초기화", upd.get("submit_status") == "DRAFT")
        check("실변경: confirm_status=PENDING 초기화", upd.get("confirm_status") == "PENDING")
        check("실변경: submitted_at=None 해제", "submitted_at" in upd and upd["submitted_at"] is None)
        check("실변경: updated_by 감사 갱신", upd.get("updated_by") == "X")

        # (d) CONFIRMED 상태변경 차단: 변경 필드가 있어도 상단 게이트가 예외(편집 불가), UPDATE 미호출.
        confirmed = dict(existing, confirm_status="CONFIRMED")
        sr._nmi_raw = lambda rid: dict(confirmed)
        calls["update"] = 0
        excc = raises(lambda: sr.upsert_near_miss_improvement(
            5, {"result_body": "확인 후 변경"}, updated_by="X", allow_assignment=False),
            sr.SupabaseDataError)
        check("CONFIRMED 편집 차단(상단 게이트 예외)", excc is not None and "확인" in str(excc))
        check("CONFIRMED 차단: UPDATE 미호출", calls["update"] == 0)
    finally:
        sr.near_miss_improvement_extensions_ready = orig_ready
        sr._nmi_raw = orig_raw
        sr._near_miss_improvement_natural = orig_natural
        sr.client = orig_client


def test_cause_label_display() -> None:
    """H2: 개선조치 상세의 CAUSE 가 원시 코드가 아니라 한글 라벨로 표기된다(표시 전용).

    JAM→끼임 매핑(2026-08-13 정본 통일 — KOSHA 용법: JAM=끼임/말려듦, PINCH=협착),
    cause_detail 보존(· 상세), 미등록 코드는 원문 fallback. DB 코드·필터·저장
    payload 는 불변이며 표시 계층만 라벨링한다."""
    print("H2: 개선조치 상세 CAUSE 라벨 표기(원시코드 노출 제거)")
    from views import near_miss_improvement as nmi
    check("_CAUSE_LABEL JAM→끼임", nmi._CAUSE_LABEL.get("JAM") == "끼임")
    check("_CAUSE_LABEL 미등록 코드 fallback(get 기본값)", nmi._CAUSE_LABEL.get("ZZZ", "ZZZ") == "ZZZ")
    base = {
        "id": 1, "report_no": "202607-0001", "cause_code": "JAM", "cause_detail": "덮개 미고정",
        "incident_content": "점검 중 낙하 위험", "countermeasure": "덮개 고정", "work_name": "설비 점검",
        "confirmed_grade": "B", "reporter_emp_no": "1001", "incident_date": "2026-07-10",
        "dept_code": "PET1",
    }
    html = nmi._detail_read_html(base, None, "EVALUATED")
    check("CAUSE 값에 '끼임' 표기", "끼임" in html)
    check("원시 'JAM' 코드는 CAUSE 값으로 미노출", ">JAM<" not in html)
    check("cause_detail 보존(· 덮개 미고정)", "덮개 미고정" in html)
    unreg = dict(base, cause_code="ZZZ", cause_detail="")
    html2 = nmi._detail_read_html(unreg, None, "EVALUATED")
    check("미등록 코드는 원문 fallback(ZZZ 표기)", "ZZZ" in html2)


def main() -> int:
    for test in (
        test_cause_label_display,
        test_improvement_schema_probe_three_state,
        test_improvement_read_gate_surfaces_probe_error,
        test_upsert_creates_draft_server_fields,
        test_submit_requires_assignee_and_result,
        test_confirm_server_attribution_and_self_confirm,
        test_safety_officer_can_confirm,
        test_reject_flow,
        test_confirmed_is_immutable,
        test_close_hard_gate,
        test_direct_close_transition_blocked,
        test_child_demotion_defense_sample,
        test_reopen_resets_confirmed_capa,
        test_sample_self_confirm_case_insensitive,
        test_repo_update_status_rejects_direct_closed,
        test_reopen_supabase_path_uses_atomic_rpc,
        test_reopen_supabase_path_not_ready_uses_plain,
        test_reopen_supabase_path_probe_error_fails_closed,
        test_reopen_supabase_path_error_propagates,
        test_request_revision_sample,
        test_request_revision_supabase_path,
        test_confirm_supabase_path_server_attribution,
        test_close_supabase_path_calls_rpc,
        test_capa_save_submit_capability_gate,
        test_assignment_authority_and_field_separation,
        test_assign_work_branch_full_separation,
        test_designated_confirmer_user_can_confirm,
        test_actor_aware_access_and_queue_scoping,
        test_get_improvement_existence_oracle_sealed,
        test_has_improvement_access,
        test_has_improvement_access_supabase_query_contract,
        test_access_facade_folds_actor_datasource_error,
        test_noop_upsert_preserves_status_sample,
        test_noop_upsert_preserves_status_supabase,
        test_work_path_conditional_reassignment_race,
        test_report_id_immutable_sample,
        test_migration_007_sql_contract,
    ):
        test()
    print(f"\nALL PASSED ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
