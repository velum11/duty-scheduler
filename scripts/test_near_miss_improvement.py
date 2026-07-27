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
# upsert(DRAFT) — 신원 서버확정·server-field 위조 무시·검증
# =========================================================================
def test_upsert_creates_draft_server_fields() -> None:
    print("upsert_near_miss_improvement DRAFT 생성 + server-field 위조 무시")
    _reset()
    reporter = _actor_of_role("USER")
    manager = _actor_of_role("MANAGER")
    rid = _evaluated_report(reporter, manager)

    rec = db.upsert_near_miss_improvement(rid, {
        "assignee_emp_no": reporter["emp_no"], "action_body": "조치안",
        "result_body": "조치결과", "due_date": "2026-08-01",
        # server-owned 위조 시도.
        "submit_status": "SUBMITTED", "confirm_status": "CONFIRMED",
        "confirmed_by_emp_no": manager["emp_no"], "confirmed_at": "2000-01-01T00:00:00Z",
        "is_active": False, "id": 99999,
    }, current_user=manager)

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
    check("잘못된 기한 형식 거부",
          raises(lambda: db.upsert_near_miss_improvement(
              rid, {"due_date": "2026/08/01"}, current_user=manager), ValueError) is not None)
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

    # 담당자·결과 없이 제출 불가.
    db.upsert_near_miss_improvement(rid, {"action_body": "조치만"}, current_user=manager)
    check("담당자/결과 없으면 제출 차단",
          raises(lambda: db.submit_near_miss_improvement(rid, current_user=manager), ValueError) is not None)

    # 담당자·결과 채우고 제출.
    db.upsert_near_miss_improvement(rid, {
        "assignee_emp_no": reporter["emp_no"], "result_body": "결과"}, current_user=manager)
    rec = db.submit_near_miss_improvement(rid, current_user=manager)
    check("DRAFT→SUBMITTED", rec["submit_status"] == "SUBMITTED")
    check("submitted_at 서버측 설정", bool(str(rec["submitted_at"] or "")))
    check("confirm_status PENDING 유지", rec["confirm_status"] == "PENDING")

    # 이미 SUBMITTED 인데 다시 제출 → stale.
    exc = raises(lambda: db.submit_near_miss_improvement(rid, current_user=manager), ValueError)
    check("SUBMITTED 재제출 stale", exc is not None and "이미 변경" in str(exc))


# =========================================================================
# confirm — 서버귀속·자기확인 차단·능력 게이트·stale
# =========================================================================
def _submitted_improvement(rid, assignee, actor):
    db.upsert_near_miss_improvement(rid, {
        "assignee_emp_no": assignee["emp_no"], "result_body": "결과"}, current_user=actor)
    db.submit_near_miss_improvement(rid, current_user=actor)


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
          db.get_near_miss_improvement(rid2)["confirm_status"] == "PENDING")


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

    # 반려된 개선조치를 재편집(upsert)하면 DRAFT/PENDING 으로 되돌아간다.
    redraft = db.upsert_near_miss_improvement(rid, {
        "assignee_emp_no": reporter["emp_no"], "result_body": "보완결과"}, current_user=manager)
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
    check("편집 거부 후 CONFIRMED 유지", db.get_near_miss_improvement(rid)["confirm_status"] == "CONFIRMED")


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
    imp = db.get_near_miss_improvement(rid)
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
        "assignee_emp_no": reporter["emp_no"], "result_body": "조치결과",
        "due_date": "2026-08-15"}, current_user=manager)
    db.submit_near_miss_improvement(rid, current_user=manager)
    db.confirm_near_miss_improvement(rid, current_user={"emp_no": manager["emp_no"]})
    check("사전 CONFIRMED", db.get_near_miss_improvement(rid)["confirm_status"] == "CONFIRMED")

    # 재개 전이.
    db.update_near_miss_status(rid, "IN_REVIEW", current_user=manager)
    check("report IN_REVIEW 재개", db.get_near_miss_report(rid)["status"] == "IN_REVIEW")
    check("report 확정등급 초기화", str(db.get_near_miss_report(rid).get("confirmed_grade") or "") == "")

    imp = db.get_near_miss_improvement(rid)
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
    orig_repo = db.supabase_repository.confirm_near_miss_improvement
    db.is_sample_mode = lambda: False
    db.find_user_by_emp_no = lambda emp, **kw: auth_record if str(emp).strip() == manager["emp_no"] else None
    db.supabase_repository.confirm_near_miss_improvement = (
        lambda report_id, *, confirmed_by_emp_no, updated_by: (
            captured.update({"report_id": report_id, "confirmed_by_emp_no": confirmed_by_emp_no,
                             "updated_by": updated_by}) or {"confirm_status": "CONFIRMED"}))
    try:
        db.confirm_near_miss_improvement(7, current_user={"emp_no": manager["emp_no"], "role": "USER"})
    finally:
        db.is_sample_mode = orig_sample
        db.find_user_by_emp_no = orig_find
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
        # 담당자를 소문자 'capamgr' 로 지정(DB 원본 표기는 'CapaMgr').
        db.upsert_near_miss_improvement(
            rid, {"assignee_emp_no": "capamgr", "result_body": "결과"}, current_user=manager)
        db.submit_near_miss_improvement(rid, current_user=manager)
        check("담당자 사번 정규화 저장(DB 원본 표기)",
              db.get_near_miss_improvement(rid)["assignee_emp_no"] == "CapaMgr")
        # 같은 사람을 대문자 'CAPAMGR' 로 확인자 지정 → 자기확인 차단(대소문자 무차별).
        exc = raises(lambda: db.confirm_near_miss_improvement(
            rid, current_user={"emp_no": "CAPAMGR"}), ValueError)
        check("대소문자 다른 자기확인 차단", exc is not None and "자기확인" in str(exc))
        check("자기확인 차단 후 PENDING 유지",
              db.get_near_miss_improvement(rid)["confirm_status"] == "PENDING")
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
    orig_ready = db.near_miss_improvement_schema_ready
    orig_reopen = db.supabase_repository.reopen_near_miss_report
    orig_reset = db.supabase_repository.reset_near_miss_improvement_on_reopen
    orig_plain = db.supabase_repository.update_near_miss_status
    db.is_sample_mode = lambda: False
    db.find_user_by_emp_no = lambda emp, **kw: auth_record if str(emp).strip() == manager["emp_no"] else None
    db.get_near_miss_report = lambda rid: {"id": rid, "status": "EVALUATED", "reporter_emp_no": "1003"}
    db.near_miss_improvement_schema_ready = lambda: True
    db.supabase_repository.reopen_near_miss_report = (
        lambda report_id, *, actor_emp_no: (
            captured.update({"report_id": report_id, "actor_emp_no": actor_emp_no})
            or {"status": "IN_REVIEW"}))
    db.supabase_repository.reset_near_miss_improvement_on_reopen = (
        lambda *a, **k: calls.__setitem__("reset", calls["reset"] + 1))
    db.supabase_repository.update_near_miss_status = (
        lambda *a, **k: calls.__setitem__("plain", calls["plain"] + 1) or {"status": "X"})
    try:
        out = db.update_near_miss_status(11, "IN_REVIEW", current_user={"emp_no": manager["emp_no"]})
    finally:
        db.is_sample_mode = orig_sample
        db.find_user_by_emp_no = orig_find
        db.get_near_miss_report = orig_get
        db.near_miss_improvement_schema_ready = orig_ready
        db.supabase_repository.reopen_near_miss_report = orig_reopen
        db.supabase_repository.reset_near_miss_improvement_on_reopen = orig_reset
        db.supabase_repository.update_near_miss_status = orig_plain

    check("재개는 원자 RPC 로 위임", out and out.get("status") == "IN_REVIEW")
    check("actor_emp_no 서버귀속", captured.get("actor_emp_no") == manager["emp_no"])
    check("report_id 전달", captured.get("report_id") == 11)
    check("비원자 2단계 reset 미사용", calls["reset"] == 0)
    check("일반 상태변경 경로 미사용", calls["plain"] == 0)


def test_reopen_supabase_path_error_propagates() -> None:
    print("supabase 경로 재개 RPC 실패는 조용히 건너뛰지 않고 전파 (P1-4 중간실패 전파)")
    manager = _actor_of_role("MANAGER")
    auth_record = db.find_user_by_emp_no(manager["emp_no"])

    def _boom(report_id, *, actor_emp_no):
        raise RuntimeError("원자 재개 실패(테스트)")

    orig_sample = db.is_sample_mode
    orig_find = db.find_user_by_emp_no
    orig_get = db.get_near_miss_report
    orig_ready = db.near_miss_improvement_schema_ready
    orig_reopen = db.supabase_repository.reopen_near_miss_report
    db.is_sample_mode = lambda: False
    db.find_user_by_emp_no = lambda emp, **kw: auth_record if str(emp).strip() == manager["emp_no"] else None
    db.get_near_miss_report = lambda rid: {"id": rid, "status": "EVALUATED", "reporter_emp_no": "1003"}
    db.near_miss_improvement_schema_ready = lambda: True
    db.supabase_repository.reopen_near_miss_report = _boom
    try:
        exc = raises(lambda: db.update_near_miss_status(
            12, "IN_REVIEW", current_user={"emp_no": manager["emp_no"]}), RuntimeError)
    finally:
        db.is_sample_mode = orig_sample
        db.find_user_by_emp_no = orig_find
        db.get_near_miss_report = orig_get
        db.near_miss_improvement_schema_ready = orig_ready
        db.supabase_repository.reopen_near_miss_report = orig_reopen

    check("재개 RPC 오류 전파(은폐 없음)", exc is not None and "원자 재개 실패" in str(exc))


def test_close_supabase_path_calls_rpc() -> None:
    print("supabase 경로 close: RPC(close_near_miss_report)로 위임")
    manager = _actor_of_role("MANAGER")
    auth_record = db.find_user_by_emp_no(manager["emp_no"])
    captured: dict = {}

    orig_sample = db.is_sample_mode
    orig_find = db.find_user_by_emp_no
    orig_repo = db.supabase_repository.close_near_miss_report
    db.is_sample_mode = lambda: False
    db.find_user_by_emp_no = lambda emp, **kw: auth_record if str(emp).strip() == manager["emp_no"] else None
    db.supabase_repository.close_near_miss_report = (
        lambda report_id, *, actor_emp_no: (
            captured.update({"report_id": report_id, "actor_emp_no": actor_emp_no})
            or {"status": "CLOSED"}))
    try:
        out = db.close_near_miss_report(5, current_user={"emp_no": manager["emp_no"]})
    finally:
        db.is_sample_mode = orig_sample
        db.find_user_by_emp_no = orig_find
        db.supabase_repository.close_near_miss_report = orig_repo

    check("close 는 repo(RPC)로 위임", out and out.get("status") == "CLOSED")
    check("actor_emp_no = 인증 actor 서버귀속", captured.get("actor_emp_no") == manager["emp_no"])
    check("report_id 전달", captured.get("report_id") == 5)


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


def main() -> int:
    for test in (
        test_improvement_schema_probe_three_state,
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
        test_reopen_supabase_path_error_propagates,
        test_confirm_supabase_path_server_attribution,
        test_close_supabase_path_calls_rpc,
        test_migration_007_sql_contract,
    ):
        test()
    print(f"\nALL PASSED ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
