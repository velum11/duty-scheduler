"""아차사고(near-miss, migration 006) 데이터 계약 단위 테스트.

Codex 감사 지적(데이터 안전) 회귀 방지용. 원격 write 없이 sample 모드 + 순수 mock
으로만 파사드/리포지토리 계약을 검증한다.

검증 항목:
  P1-1 행위자 신원은 서버측(세션 사용자)에서 확정된다 — payload 의 신원 위조 무시.
  P1-2 비멱등 create INSERT 는 일시 오류로 맹목 재시도하지 않는다(중복 방지).
        진짜 unique 충돌만 안전하게 재채번 재시도한다.
  P1-3 상태 전이/평가는 원자적 조건부 UPDATE(where status=expected)로 하고,
        0행이면 stale 오류를 낸다(lost update 금지).
  006 SQL 계약: 필수 컬럼/제약/인덱스가 마이그레이션 파일에 존재.

실행: python scripts/test_near_miss_data.py
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

# 콘솔 인코딩(cp949 등)에서도 한글 출력이 깨지지 않도록 stdout 을 UTF-8 로.
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


def _sample_emp(idx: int) -> dict:
    """sample CSV 의 실제 사용자 dict(세션 사용자 대용)."""
    df = db.get_users()
    row = df.iloc[idx].to_dict()
    return {
        "emp_no": str(row["emp_no"]),
        "dept_code": str(row.get("dept_code") or ""),
        "role": str(row.get("role") or "USER"),
        "name": str(row.get("name") or ""),
    }


def _base_payload(**over) -> dict:
    payload = {
        "work_name": "설비 점검",
        "incident_content": "덮개 미고정",
        "cause_code": "JAM",
        "incident_date": "2026-07-10",
        "proposed_grade": "C",
    }
    payload.update(over)
    return payload


def _users_frame(rows: list[dict]) -> pd.DataFrame:
    """USER_COLUMNS 계약 프레임(supabase 모드 조회 mock 용)."""
    df = pd.DataFrame(rows)
    for col in db.USER_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[db.USER_COLUMNS].reset_index(drop=True)


# =========================================================================
# P3 — auth._as_bool / is_safety_officer 정규화("false" 는 거짓)
# =========================================================================
def test_auth_bool_canonicalization() -> None:
    print("auth.is_safety_officer 불리언 정규화 (P3)")
    check('문자열 "false" 는 거짓', auth._as_bool("false") is False)
    check('문자열 "False" 는 거짓', auth._as_bool("False") is False)
    check('빈 문자열은 거짓', auth._as_bool("") is False)
    check('"0" 은 거짓', auth._as_bool("0") is False)
    check('숫자 0 은 거짓', auth._as_bool(0) is False)
    check('실제 True 는 참', auth._as_bool(True) is True)
    check('숫자 1 은 참', auth._as_bool(1) is True)
    check('"true" 는 참', auth._as_bool("true") is True)
    # 회귀: bool("false") == True 함정
    check('is_safety_officer("false") 안전', auth.is_safety_officer({"is_safety_officer": "false"}) is False)
    check('is_safety_officer(True) 참', auth.is_safety_officer({"is_safety_officer": True}) is True)
    check('None 사용자 거짓', auth.is_safety_officer(None) is False)


# =========================================================================
# P1-1 — 서버측 행위자 신원 (payload 신원 위조 무시)
# =========================================================================
def test_server_side_identity_on_create() -> None:
    print("create_near_miss_report 서버측 신원 확정 (P1-1)")
    st.session_state.pop(db._NEAR_MISS_STORE, None)
    reporter = _sample_emp(0)   # 실제 세션 사용자
    other = _sample_emp(1)      # payload 로 위조 시도할 타인

    # payload 에 타인 사번·상태·평가값·created_by 위조를 심는다.
    spoofed = _base_payload(
        reporter_emp_no=other["emp_no"],
        reporter_user_id=999999,
        dept_code="ZZZ-없는부서",
        status="EVALUATED",
        confirmed_grade="S",
        evaluator_emp_no=other["emp_no"],
        created_by="9999",
        is_active=False,
    )
    record = db.create_near_miss_report(spoofed, current_user=reporter)

    check("보고자는 세션 사용자로 확정(위조 무시)", record["reporter_emp_no"] == reporter["emp_no"])
    check("부서는 세션 사용자 부서로 확정", record["dept_code"] == reporter["dept_code"])
    check("상태는 서버측 SUBMITTED 강제", record["status"] == "SUBMITTED")
    check("확정등급은 생성 시 비어있음", record["confirmed_grade"] in (None, ""))
    check("평가자는 생성 시 비어있음", str(record["evaluator_emp_no"]) == "")
    check("is_active 서버측 True", bool(record["is_active"]) is True)
    check("보고자 제안 등급은 존중", record["proposed_grade"] == "C")

    # current_user 누락은 DB 요청 전에 차단.
    check("current_user 없으면 차단",
          raises(lambda: db.create_near_miss_report(_base_payload(), current_user=None), ValueError) is not None)
    check("current_user 사번 미상 차단",
          raises(lambda: db.create_near_miss_report(_base_payload(), current_user={"emp_no": "없는사번"}), ValueError) is not None)


def test_server_side_identity_on_evaluate() -> None:
    print("evaluate_near_miss 서버측 평가자 확정 (P1-1)")
    st.session_state.pop(db._NEAR_MISS_STORE, None)
    reporter = _sample_emp(0)
    evaluator = _sample_emp(1)
    record = db.create_near_miss_report(_base_payload(), current_user=reporter)
    rid = record["id"]

    updated = db.evaluate_near_miss(rid, "B", current_user=evaluator)
    check("평가자는 세션 사용자로 확정", updated["evaluator_emp_no"] == evaluator["emp_no"])
    check("확정 등급 저장", updated["confirmed_grade"] == "B")
    check("상태 EVALUATED", updated["status"] == "EVALUATED")
    check("평가시각 서버측 설정", bool(str(updated["evaluated_at"] or "")))

    # 신원을 파라미터로 위조하는 옛 경로(evaluator_emp_no=)는 제거되어야 한다.
    check("evaluator_emp_no 파라미터 위조 불가(TypeError)",
          raises(lambda: db.evaluate_near_miss(rid, "B", evaluator_emp_no="9999"), TypeError) is not None)
    check("evaluate current_user 필수",
          raises(lambda: db.evaluate_near_miss(rid, "B"), TypeError) is not None)


def test_forged_current_user_dept_ignored() -> None:
    print("위조된 current_user 부서 무시 — 권위 레코드 부서로 귀속 (P1-1 잔여)")
    st.session_state.pop(db._NEAR_MISS_STORE, None)
    reporter = _sample_emp(0)
    check("전제: 권위 사용자 부서가 존재", reporter["dept_code"] != "")

    # 사번은 유효하나 dept_code 를 타 부서로 조작한 current_user.
    forged = {"emp_no": reporter["emp_no"], "dept_code": "ZZZ-위조부서", "role": "USER"}
    record = db.create_near_miss_report(_base_payload(), current_user=forged)
    check("부서는 DB 권위 레코드로 귀속", record["dept_code"] == reporter["dept_code"])
    check("위조 dept_code 는 무시됨", record["dept_code"] != "ZZZ-위조부서")


def test_facade_strips_client_audit_fields() -> None:
    print("파사드가 client created_by/updated_by/status 를 제거·서버확정 (P1-1 잔여)")
    reporter = _sample_emp(0)
    auth_record = db.find_user_by_emp_no(reporter["emp_no"])  # 권위 레코드(sample)
    captured: dict = {}
    orig_sample = db.is_sample_mode
    orig_find = db.find_user_by_emp_no
    orig_create = db.supabase_repository.create_near_miss_report
    # supabase 경로(파사드가 repo 를 호출)를 타되, 권위 사용자 조회·repo create 는 mock.
    db.is_sample_mode = lambda: False
    db.find_user_by_emp_no = lambda emp, **kw: auth_record if str(emp).strip() == reporter["emp_no"] else None
    db.supabase_repository.create_near_miss_report = lambda safe: (captured.update(safe) or {"ok": True})
    try:
        db.create_near_miss_report(
            _base_payload(
                created_by="9999", updated_by="8888", status="EVALUATED",
                reporter_emp_no="위조사번", dept_code="위조부서",
                confirmed_grade="S", evaluator_emp_no="위조평가자",
            ),
            current_user={"emp_no": reporter["emp_no"], "dept_code": "무시될부서"},
        )
    finally:
        db.is_sample_mode = orig_sample
        db.find_user_by_emp_no = orig_find
        db.supabase_repository.create_near_miss_report = orig_create

    check("created_by 서버측(세션 사번)으로 설정", captured.get("created_by") == reporter["emp_no"])
    check("client created_by 무시", captured.get("created_by") != "9999")
    check("client updated_by 는 payload 에서 제거", captured.get("updated_by") in (None, reporter["emp_no"]) and captured.get("updated_by") != "8888")
    check("client status 제거(서버측 상태머신)", "status" not in captured)
    check("client confirmed_grade 제거", "confirmed_grade" not in captured)
    check("보고자 서버측 확정", captured.get("reporter_emp_no") == reporter["emp_no"])
    check("부서는 권위 레코드(세션 dict dept 무시)", captured.get("dept_code") == reporter["dept_code"])
    check("계약: created_by/updated_by 는 server-field", {"created_by", "updated_by"} <= db._NEAR_MISS_SERVER_FIELDS)


def test_reevaluate_already_evaluated_rejected() -> None:
    print("이미 EVALUATED 인 보고서 재평가 거부(덮어쓰기 방지) (P1-3 잔여)")
    st.session_state.pop(db._NEAR_MISS_STORE, None)
    reporter = _sample_emp(0)
    evaluator = _sample_emp(1)
    rec = db.create_near_miss_report(_base_payload(), current_user=reporter)
    rid = rec["id"]
    db.evaluate_near_miss(rid, "A", current_user=evaluator)
    check("최초 평가 EVALUATED", db.get_near_miss_report(rid)["status"] == "EVALUATED")

    # 두 번째 평가자(또는 재클릭)의 재평가 → stale 거부, 확정 등급 유지.
    exc = raises(lambda: db.evaluate_near_miss(rid, "S", current_user=evaluator), ValueError)
    check("재평가는 '상태 이미 변경' 으로 거부", exc is not None and "이미 변경" in str(exc))
    check("확정 등급 덮어써지지 않음(A 유지)", db.get_near_miss_report(rid)["confirmed_grade"] == "A")

    # CLOSED 로 종결한 뒤에도 재평가 불가.
    db.update_near_miss_status(rid, "CLOSED", current_user=evaluator)
    exc2 = raises(lambda: db.evaluate_near_miss(rid, "B", current_user=evaluator), ValueError)
    check("CLOSED 재평가도 거부", exc2 is not None and "이미 변경" in str(exc2))


def test_same_state_retransition_blocked() -> None:
    print("update_near_miss_status 동일상태 재전이 차단(종말상태 반복전이 방지)")
    st.session_state.pop(db._NEAR_MISS_STORE, None)
    reporter = _sample_emp(0)
    evaluator = _sample_emp(1)

    # 허용표에는 어떤 상태도 자기 자신으로의 전이가 없다(계약 고정).
    for state, targets in db.NEAR_MISS_TRANSITIONS.items():
        check(f"{state} 는 자기 자신으로의 전이 없음", state not in targets)

    # REJECTED → REJECTED 재호출 차단(반려사유 덮어쓰기 방지).
    rec = db.create_near_miss_report(_base_payload(), current_user=reporter)
    rid = rec["id"]
    db.update_near_miss_status(rid, "REJECTED", rejection_reason="최초 사유", current_user=evaluator)
    check("반려 상태 진입", db.get_near_miss_report(rid)["status"] == "REJECTED")
    exc = raises(lambda: db.update_near_miss_status(
        rid, "REJECTED", rejection_reason="덮어쓰기 시도", current_user=evaluator), ValueError)
    check("REJECTED→REJECTED 재호출 거부", exc is not None and "허용되지 않은 상태 전이" in str(exc))
    check("반려 사유 덮어써지지 않음(최초 유지)",
          db.get_near_miss_report(rid)["rejection_reason"] == "최초 사유")

    # CLOSED → CLOSED 재호출 차단(무효 재실행 방지).
    rec2 = db.create_near_miss_report(_base_payload(), current_user=reporter)
    rid2 = rec2["id"]
    db.evaluate_near_miss(rid2, "A", current_user=evaluator)
    db.update_near_miss_status(rid2, "CLOSED", current_user=evaluator)
    check("종결 상태 진입", db.get_near_miss_report(rid2)["status"] == "CLOSED")
    exc2 = raises(lambda: db.update_near_miss_status(
        rid2, "CLOSED", current_user=evaluator), ValueError)
    check("CLOSED→CLOSED 재호출 거부", exc2 is not None and "허용되지 않은 상태 전이" in str(exc2))

    # 정상 전이(cur != target, 허용표 포함)는 이 변경에 영향받지 않는다.
    rec3 = db.create_near_miss_report(_base_payload(), current_user=reporter)
    rid3 = rec3["id"]
    db.update_near_miss_status(rid3, "IN_REVIEW", current_user=evaluator)
    check("SUBMITTED→IN_REVIEW 정상 전이 유지", db.get_near_miss_report(rid3)["status"] == "IN_REVIEW")
    db.update_near_miss_status(rid3, "REJECTED", rejection_reason="사유", current_user=evaluator)
    check("IN_REVIEW→REJECTED 정상 전이 유지", db.get_near_miss_report(rid3)["status"] == "REJECTED")
    db.update_near_miss_status(rid3, "SUBMITTED", current_user=evaluator)
    check("REJECTED→SUBMITTED 재개 전이 유지", db.get_near_miss_report(rid3)["status"] == "SUBMITTED")


# =========================================================================
# P1-a — update_near_miss_status / evaluate_near_miss 서버측 인증·인가
#         (Codex 2회 검수 확정: 이미 배포된 상태전이·평가 경로의 보안 갭 봉인)
# =========================================================================
def _actor_of_role(role: str, *, active: bool = True, exclude=()):
    """sample 사용자 중 주어진 role·활성 여부에 맞는 세션 사용자(emp_no 만 신뢰).

    파사드는 넘긴 dict 의 role 을 믿지 않고 사번으로 권위 레코드를 재조회하므로,
    테스트도 emp_no 만 담아 넘긴다(위조 role 무시 계약을 그대로 검증)."""
    exclude = set(exclude)
    df = db.get_users()
    for _, row in df.iterrows():
        emp = str(row["emp_no"])
        if (str(row.get("role") or "").strip().upper() == role.upper()
                and bool(row.get("is_active")) == active and emp not in exclude):
            return {"emp_no": emp}
    raise AssertionError(f"sample 사용자에 role={role} active={active} 없음")


def test_status_change_requires_authenticated_actor() -> None:
    print("update_near_miss_status 무인증/사번미상/비활성 차단 (P1-a F1)")
    manager = _actor_of_role("MANAGER")
    reporter = _actor_of_role("USER")
    rec = _fresh_submitted(reporter)  # SUBMITTED
    rid = rec["id"]
    # 무인증(current_user=None) → DB 요청 전 ValueError.
    check("current_user=None 차단",
          raises(lambda: db.update_near_miss_status(rid, "IN_REVIEW", current_user=None), ValueError) is not None)
    # updated_by 폴백으로도 우회 불가(폴백 경로 제거 확인).
    check("updated_by 폴백 우회 불가",
          raises(lambda: db.update_near_miss_status(
              rid, "IN_REVIEW", current_user=None, updated_by=manager["emp_no"]), ValueError) is not None)
    # 사번 미상 → 차단.
    check("사번 미상 차단",
          raises(lambda: db.update_near_miss_status(
              rid, "IN_REVIEW", current_user={"emp_no": "없는사번"}), ValueError) is not None)
    check("차단 시 상태 불변(SUBMITTED)", db.get_near_miss_report(rid)["status"] == "SUBMITTED")
    # 비활성 사용자 → _near_miss_actor 단계에서 '비활성' 차단.
    inactive = _actor_of_role("USER", active=False)
    exc = raises(lambda: db.update_near_miss_status(
        rid, "IN_REVIEW", current_user={"emp_no": inactive["emp_no"]}), ValueError)
    check("비활성 사용자 차단", exc is not None and "비활성" in str(exc))


def test_status_change_capability_gate() -> None:
    print("update_near_miss_status 평가능력 없는 USER 전이 차단 + 위조 role 무시 (P1-a F2)")
    manager = _actor_of_role("MANAGER")
    user = _actor_of_role("USER")
    reporter = _actor_of_role("USER")
    # 비평가자 USER 는 SUBMITTED→(REJECTED/IN_REVIEW) 전이 불가(권한 게이트).
    # EVALUATED 는 update_near_miss_status 진입부에서 role 과 무관하게 차단되므로(P2-2)
    # 아래 능력 게이트 루프와 분리해 별도로 확인한다.
    for target, kwargs in (("REJECTED", {"rejection_reason": "x"}), ("IN_REVIEW", {})):
        rec = _fresh_submitted(reporter)
        rid = rec["id"]
        exc = raises(lambda: db.update_near_miss_status(
            rid, target, current_user={"emp_no": user["emp_no"]}, **kwargs), ValueError)
        check(f"USER SUBMITTED→{target} 차단", exc is not None and "권한" in str(exc))
        check(f"USER {target} 시도 후 상태 불변", db.get_near_miss_report(rid)["status"] == "SUBMITTED")
    # EVALUATED 직접전이는 evaluate_near_miss 전용 — 능력 있는 actor 로도 이 경로 차단(P2-2).
    rec_ev = _fresh_submitted(reporter)
    exc_ev = raises(lambda: db.update_near_miss_status(
        rec_ev["id"], "EVALUATED", current_user={"emp_no": manager["emp_no"]}), ValueError)
    check("EVALUATED 직접전이는 update_near_miss_status 로 차단",
          exc_ev is not None and "evaluate_near_miss" in str(exc_ev))
    check("EVALUATED 차단 후 상태 불변(SUBMITTED)",
          db.get_near_miss_report(rec_ev["id"])["status"] == "SUBMITTED")
    # 위조 role=ADMIN 은 무시된다(권위 레코드가 USER 라 차단).
    rec = _fresh_submitted(reporter)
    exc = raises(lambda: db.update_near_miss_status(
        rec["id"], "IN_REVIEW", current_user={"emp_no": user["emp_no"], "role": "ADMIN"}), ValueError)
    check("위조 role=ADMIN 무시하고 차단", exc is not None and "권한" in str(exc))
    # EVALUATED→CLOSED 도 USER 차단(평가자 전이).
    rec2 = _fresh_submitted(reporter)
    db.evaluate_near_miss(rec2["id"], "A", current_user={"emp_no": manager["emp_no"]})
    exc2 = raises(lambda: db.update_near_miss_status(
        rec2["id"], "CLOSED", current_user={"emp_no": user["emp_no"]}), ValueError)
    check("USER EVALUATED→CLOSED 차단", exc2 is not None and "권한" in str(exc2))
    check("차단 시 EVALUATED 유지", db.get_near_miss_report(rec2["id"])["status"] == "EVALUATED")
    # 양성 대조: 평가자(MANAGER)는 정상 전이 허용(정상 플로우 비파괴).
    rec3 = _fresh_submitted(reporter)
    db.update_near_miss_status(rec3["id"], "IN_REVIEW", current_user={"emp_no": manager["emp_no"]})
    check("MANAGER SUBMITTED→IN_REVIEW 허용", db.get_near_miss_report(rec3["id"])["status"] == "IN_REVIEW")


def test_rejected_to_submitted_authz() -> None:
    print("REJECTED→SUBMITTED 재개: 소유자 OR 평가자 허용·타인 USER 차단 (P1-a F9)")
    manager = _actor_of_role("MANAGER")
    owner = _actor_of_role("USER")
    other = _actor_of_role("USER", exclude=(owner["emp_no"],))

    def _rejected_report(reporter) -> object:
        rec = _fresh_submitted(reporter)
        db.update_near_miss_status(
            rec["id"], "REJECTED", rejection_reason="반려", current_user={"emp_no": manager["emp_no"]})
        return rec["id"]

    # (a) 소유자 USER 재제출 허용(능력 없어도 소유자라 허용).
    rid_a = _rejected_report(owner)
    db.update_near_miss_status(rid_a, "SUBMITTED", current_user={"emp_no": owner["emp_no"]})
    check("소유자 USER REJECTED→SUBMITTED 허용", db.get_near_miss_report(rid_a)["status"] == "SUBMITTED")

    # (b) 타인 USER(비소유자·비평가자) 차단.
    rid_b = _rejected_report(owner)
    exc = raises(lambda: db.update_near_miss_status(
        rid_b, "SUBMITTED", current_user={"emp_no": other["emp_no"]}), ValueError)
    check("타인 USER 재제출 차단", exc is not None and "권한" in str(exc))
    check("차단 시 REJECTED 유지", db.get_near_miss_report(rid_b)["status"] == "REJECTED")

    # (c) 평가자(비소유자)도 재개 허용(능력 경로).
    rid_c = _rejected_report(owner)
    db.update_near_miss_status(rid_c, "SUBMITTED", current_user={"emp_no": manager["emp_no"]})
    check("평가자 REJECTED→SUBMITTED 허용", db.get_near_miss_report(rid_c)["status"] == "SUBMITTED")


def test_evaluate_requires_capability() -> None:
    print("evaluate_near_miss 평가능력 없는 USER 호출 차단 + 위조 role 무시 (P1-a F2)")
    user = _actor_of_role("USER")
    reporter = _actor_of_role("USER", exclude=(user["emp_no"],))
    rec = _fresh_submitted(reporter)
    rid = rec["id"]
    exc = raises(lambda: db.evaluate_near_miss(rid, "B", current_user={"emp_no": user["emp_no"]}), ValueError)
    check("USER evaluate_near_miss 차단", exc is not None and "권한" in str(exc))
    check("차단 시 상태 불변(SUBMITTED)", db.get_near_miss_report(rid)["status"] == "SUBMITTED")
    check("확정 등급 미설정", str(db.get_near_miss_report(rid).get("confirmed_grade") or "") == "")
    exc2 = raises(lambda: db.evaluate_near_miss(
        rid, "B", current_user={"emp_no": user["emp_no"], "role": "MANAGER"}), ValueError)
    check("위조 role=MANAGER 무시하고 차단", exc2 is not None and "권한" in str(exc2))


def test_safety_officer_can_evaluate() -> None:
    print("안전담당자 USER 는 평가 허용 (P1-a 능력 근거=is_safety_officer)")
    user = _actor_of_role("USER")
    reporter = _actor_of_role("USER", exclude=(user["emp_no"],))
    rec = _fresh_submitted(reporter)
    rid = rec["id"]
    # sample CSV 에는 is_safety_officer 컬럼이 없어 항상 False → 능력조회 지점만 주입한다.
    orig = db._safety_officer_flag
    db._safety_officer_flag = lambda emp, **_: str(emp).strip() == user["emp_no"]
    try:
        check("전제: 안전담당자 능력 인정",
              auth.can_evaluate_near_miss(db.find_user_by_emp_no(user["emp_no"])))
        updated = db.evaluate_near_miss(rid, "B", current_user={"emp_no": user["emp_no"]})
        check("안전담당자 USER 평가 허용", updated["status"] == "EVALUATED")
        check("평가자는 안전담당자 사번으로 확정", updated["evaluator_emp_no"] == user["emp_no"])
        # 반려도 능력 경로로 허용(SUBMITTED→REJECTED)되는지 별건으로 확인.
        rec2 = _fresh_submitted(reporter)
        db.update_near_miss_status(
            rec2["id"], "REJECTED", rejection_reason="사유", current_user={"emp_no": user["emp_no"]})
        check("안전담당자 USER 반려 허용", db.get_near_miss_report(rec2["id"])["status"] == "REJECTED")
    finally:
        db._safety_officer_flag = orig


def test_inactive_user_action_blocked() -> None:
    print("비활성 사용자는 능력이 있어도 행위 차단 (Codex P2 is_active 게이트)")
    inactive = _actor_of_role("USER", active=False)
    reporter = _actor_of_role("USER")
    rec = _fresh_submitted(reporter)
    rid = rec["id"]
    # 비활성 사용자를 안전담당자(능력 보유)로 만들어도 is_active 게이트가 먼저 차단해야 한다.
    orig = db._safety_officer_flag
    db._safety_officer_flag = lambda emp, **_: str(emp).strip() == inactive["emp_no"]
    try:
        exc = raises(lambda: db.evaluate_near_miss(
            rid, "B", current_user={"emp_no": inactive["emp_no"]}), ValueError)
        check("비활성+안전담당자도 평가 차단", exc is not None and "비활성" in str(exc))
        exc2 = raises(lambda: db.update_near_miss_status(
            rid, "IN_REVIEW", current_user={"emp_no": inactive["emp_no"]}), ValueError)
        check("비활성 상태변경 차단", exc2 is not None and "비활성" in str(exc2))
        check("차단 시 상태 불변(SUBMITTED)", db.get_near_miss_report(rid)["status"] == "SUBMITTED")
        excA = raises(lambda: db._near_miss_actor(
            {"emp_no": inactive["emp_no"]}, action="테스트"), ValueError)
        check("_near_miss_actor 비활성 직접 차단", excA is not None and "비활성" in str(excA))
    finally:
        db._safety_officer_flag = orig


# =========================================================================
# P1-a Codex 재감사 반영(P2-2/P2-1/P3-1/P3-2)
#   P2-2 EVALUATED 직접전이 차단(evaluate_near_miss 전용 강제)
#   P2-1 인가 판정용 actor 조회는 캐시 우회(권한 회수/비활성화 즉시 반영)
#   P3-1 감사 귀속=인증 actor 사번(위조 updated_by 무시) facade→repo
#   P3-2 ADMIN·안전담당자 전체 전이표 양성 + 실 읽기경로 + 인가·stale 결합
#
# 계약 주석(라이브 불가 분기): supabase 006(users.is_safety_officer·near_miss_reports)
# 적용/미적용 분기는 원격 write·라이브 스키마가 필요해 이 sample+mock 스위트에서 직접
# 재현하지 않는다. 미적용 시 near_miss_extensions_ready()=False 로 쓰기가 보수적으로
# 차단되는 계약은 test_readiness_three_state/test_probe_error_not_sticky 가, is_safety_officer
# 실 컬럼 읽기 계약은 test_safety_officer_capability_real_read_path 가 mock 으로 근사한다.
# =========================================================================
def test_evaluated_direct_transition_blocked() -> None:
    print("update_near_miss_status 로는 EVALUATED 직접전이 불가 — evaluate 전용 (P2-2)")
    manager = _actor_of_role("MANAGER")
    reporter = _actor_of_role("USER")

    # 능력 있는 MANAGER 로도 update_near_miss_status(…, "EVALUATED") 는 진입부에서 차단.
    rid = _fresh_submitted(reporter)["id"]
    exc = raises(lambda: db.update_near_miss_status(
        rid, "EVALUATED", current_user={"emp_no": manager["emp_no"]}), ValueError)
    check("EVALUATED 직접전이 거부", exc is not None and "evaluate_near_miss" in str(exc))
    check("차단 후 상태 불변(SUBMITTED)", db.get_near_miss_report(rid)["status"] == "SUBMITTED")
    check("차단 후 확정등급 미설정", str(db.get_near_miss_report(rid).get("confirmed_grade") or "") == "")

    # 진입부 차단이라 무인증 호출도 EVALUATED 는 동일 사유로 거부(인증 이전 게이트).
    exc2 = raises(lambda: db.update_near_miss_status(
        rid, "EVALUATED", current_user=None), ValueError)
    check("무인증 EVALUATED 직접전이도 거부", exc2 is not None and "evaluate_near_miss" in str(exc2))

    # 정상 평가확정 경로(evaluate_near_miss)는 이 차단에 막히지 않고 EVALUATED 로 확정.
    updated = db.evaluate_near_miss(rid, "B", current_user={"emp_no": manager["emp_no"]})
    check("evaluate_near_miss 는 EVALUATED 확정 정상", updated["status"] == "EVALUATED")
    check("평가확정 시 확정등급·평가자·시각 채워짐",
          updated["confirmed_grade"] == "B" and updated["evaluator_emp_no"] == manager["emp_no"]
          and bool(str(updated["evaluated_at"] or "")))


def test_status_change_audit_attribution() -> None:
    print("update_near_miss_status 감사 귀속=인증 actor 사번, 위조 updated_by 무시 (P3-1)")
    manager = _actor_of_role("MANAGER")
    reporter = _actor_of_role("USER")
    auth_record = db.find_user_by_emp_no(manager["emp_no"])  # 권위 레코드(MANAGER, 능력 보유)
    captured: dict = {}

    def _capture_update(*a, **k):
        captured.update(k)
        captured["_args"] = a
        return {"id": 7, "status": "IN_REVIEW"}

    orig_sample = db.is_sample_mode
    orig_find = db.find_user_by_emp_no
    orig_get = db.get_near_miss_report
    orig_repo = db.supabase_repository.update_near_miss_status
    # supabase 경로(파사드→repo)를 타되 권위 조회·현재 상태·repo update 만 mock.
    db.is_sample_mode = lambda: False
    db.find_user_by_emp_no = lambda emp, **kw: auth_record if str(emp).strip() == manager["emp_no"] else None
    db.get_near_miss_report = lambda _id: {"id": 7, "status": "SUBMITTED", "reporter_emp_no": reporter["emp_no"]}
    db.supabase_repository.update_near_miss_status = _capture_update
    try:
        db.update_near_miss_status(
            7, "IN_REVIEW",
            current_user={"emp_no": manager["emp_no"], "role": "USER"},  # 위조 role 무시
            updated_by="9999",  # 위조 감사값 — repo 로 전달되면 안 됨
        )
    finally:
        db.is_sample_mode = orig_sample
        db.find_user_by_emp_no = orig_find
        db.get_near_miss_report = orig_get
        db.supabase_repository.update_near_miss_status = orig_repo

    check("repo 로 전달된 updated_by = 인증 actor 사번", captured.get("updated_by") == manager["emp_no"])
    check("위조 updated_by=9999 는 repo 로 전달되지 않음", captured.get("updated_by") != "9999")
    check("전이 자체는 IN_REVIEW(정상 경로) 유지", captured.get("_args", (None, None))[1] == "IN_REVIEW")


def test_safety_officer_capability_real_read_path() -> None:
    print("안전담당자 능력이 실제 users.is_safety_officer(006) 읽기로 판정됨 (P3-2 실경로)")
    # db._safety_officer_flag 자체를 갈아끼우지 않고, supabase 리포지토리의 실제 컬럼
    # 조회 경로(sr._select_all)만 mock 해 006 컬럼 값이 능력으로 이어지는지 검증한다.
    orig_sample = db.is_sample_mode
    orig_select = sr._select_all
    db.is_sample_mode = lambda: False

    def _fake_select(table, columns="*", query_builder=None):
        if table == "users" and "is_safety_officer" in columns:
            return [{"emp_no": "7777", "is_safety_officer": True}]
        return []

    sr._select_all = _fake_select
    try:
        check("실 컬럼 읽기 → 안전담당자 True", db._safety_officer_flag("7777") is True)
        check("USER + is_safety_officer → 평가 능력 인정",
              auth.can_evaluate_near_miss({"emp_no": "7777", "role": "USER", "is_safety_officer": True}) is True)
        sr._select_all = lambda table, columns="*", query_builder=None: (
            [{"emp_no": "7777", "is_safety_officer": False}] if table == "users" else [])
        check("실 컬럼 false → 안전담당자 아님", db._safety_officer_flag("7777") is False)
    finally:
        db.is_sample_mode = orig_sample
        sr._select_all = orig_select


def _walk_transition_table(actor_cu: dict, reporter: dict) -> None:
    """능력 있는 actor 로 전이표의 모든 간선을 양성 통과시킨다(EVALUATED 는 evaluate 경유)."""
    # SUBMITTED → IN_REVIEW → SUBMITTED(반송)
    rid = _fresh_submitted(reporter)["id"]
    db.update_near_miss_status(rid, "IN_REVIEW", current_user=actor_cu)
    check("SUBMITTED→IN_REVIEW", db.get_near_miss_report(rid)["status"] == "IN_REVIEW")
    db.update_near_miss_status(rid, "SUBMITTED", current_user=actor_cu)
    check("IN_REVIEW→SUBMITTED(반송)", db.get_near_miss_report(rid)["status"] == "SUBMITTED")
    # SUBMITTED → REJECTED → SUBMITTED(재개)
    db.update_near_miss_status(rid, "REJECTED", rejection_reason="사유", current_user=actor_cu)
    check("SUBMITTED→REJECTED", db.get_near_miss_report(rid)["status"] == "REJECTED")
    db.update_near_miss_status(rid, "SUBMITTED", current_user=actor_cu)
    check("REJECTED→SUBMITTED(재개)", db.get_near_miss_report(rid)["status"] == "SUBMITTED")
    # IN_REVIEW → REJECTED
    rid2 = _fresh_submitted(reporter)["id"]
    db.update_near_miss_status(rid2, "IN_REVIEW", current_user=actor_cu)
    db.update_near_miss_status(rid2, "REJECTED", rejection_reason="사유", current_user=actor_cu)
    check("IN_REVIEW→REJECTED", db.get_near_miss_report(rid2)["status"] == "REJECTED")
    # SUBMITTED → EVALUATED(evaluate) → IN_REVIEW(재개, 평가필드 초기화)
    rid3 = _fresh_submitted(reporter)["id"]
    db.evaluate_near_miss(rid3, "B", current_user=actor_cu)
    check("SUBMITTED→EVALUATED(evaluate)", db.get_near_miss_report(rid3)["status"] == "EVALUATED")
    db.update_near_miss_status(rid3, "IN_REVIEW", current_user=actor_cu)
    check("EVALUATED→IN_REVIEW(재개)", db.get_near_miss_report(rid3)["status"] == "IN_REVIEW")
    check("재개 시 확정등급 초기화", str(db.get_near_miss_report(rid3).get("confirmed_grade") or "") == "")
    # IN_REVIEW → EVALUATED(evaluate) → CLOSED(종결, 평가필드 유지)
    db.evaluate_near_miss(rid3, "A", current_user=actor_cu)
    check("IN_REVIEW→EVALUATED(evaluate)", db.get_near_miss_report(rid3)["status"] == "EVALUATED")
    db.update_near_miss_status(rid3, "CLOSED", current_user=actor_cu)
    check("EVALUATED→CLOSED(종결)", db.get_near_miss_report(rid3)["status"] == "CLOSED")
    check("종결 후 확정등급 유지", db.get_near_miss_report(rid3)["confirmed_grade"] == "A")


def test_full_transition_table_positive() -> None:
    print("전체 전이표 양성 케이스 — ADMIN·안전담당자 (P3-2 양성 공백 보강)")
    admin = _actor_of_role("ADMIN")
    reporter = _actor_of_role("USER")
    _walk_transition_table({"emp_no": admin["emp_no"]}, reporter)

    # 안전담당자 USER: sample CSV 에 is_safety_officer 컬럼이 없어 능력 근거를 실제로
    # 실을 수 없으므로 능력 조회 지점(_safety_officer_flag)만 주입한다(monkeypatch 근거
    # 명시). supabase 모드는 users.is_safety_officer(006) 실컬럼으로 대체되며 그 실 읽기
    # 경로는 test_safety_officer_capability_real_read_path 가 별도로 덮는다.
    so = _actor_of_role("USER")
    reporter2 = _actor_of_role("USER", exclude=(so["emp_no"],))
    orig = db._safety_officer_flag
    db._safety_officer_flag = lambda emp, **_: str(emp).strip() == so["emp_no"]
    try:
        _walk_transition_table({"emp_no": so["emp_no"]}, reporter2)
    finally:
        db._safety_officer_flag = orig


def test_authz_then_stale_race() -> None:
    print("인가 통과 후 원자 조건부 UPDATE stale 경합 결합 (P3-2 결합)")
    manager = _actor_of_role("MANAGER")
    reporter = _actor_of_role("USER")
    rid = _fresh_submitted(reporter)["id"]
    # 능력 있는 MANAGER 라 인가는 통과하지만, 읽기~쓰기 사이 다른 사용자가 먼저 전이해
    # 원자 조건부 UPDATE 가 0행(False)이면 stale 로 거부돼야 한다(lost update 금지).
    orig = db._sample_update_near_miss
    db._sample_update_near_miss = lambda *a, **k: False
    try:
        exc = raises(lambda: db.update_near_miss_status(
            rid, "IN_REVIEW", current_user={"emp_no": manager["emp_no"]}), ValueError)
    finally:
        db._sample_update_near_miss = orig
    check("인가 통과해도 stale 경합이면 거부", exc is not None and "이미 변경" in str(exc))
    check("경합 거부 후 상태 불변(SUBMITTED)", db.get_near_miss_report(rid)["status"] == "SUBMITTED")


# =========================================================================
# 보고자 자기수정(update_near_miss_report) — 소유자+SUBMITTED 게이트, 서버필드 보호
# =========================================================================
def _valid_edit(**over) -> dict:
    payload = {
        "work_name": "수정된 작업",
        "work_content": "수정된 작업 내용",
        "incident_content": "수정된 사고 내용",
        "countermeasure": "수정된 대책",
        "site_description": "현장 설명",
        "cause_code": "FALL",
        "cause_detail": "상세",
        "incident_date": "2026-07-15",
        "proposed_grade": "B",
        "photo_paths": ["a.jpg", "b.jpg"],
    }
    payload.update(over)
    return payload


def _fresh_submitted(reporter: dict) -> dict:
    st.session_state.pop(db._NEAR_MISS_STORE, None)
    return db.create_near_miss_report(_base_payload(), current_user=reporter)


def test_update_owner_submitted_allows_edit() -> None:
    print("update_near_miss_report 소유자+SUBMITTED 수정 허용 + 서버필드 무시")
    reporter = _sample_emp(0)
    rec = _fresh_submitted(reporter)
    rid = rec["id"]
    orig_report_no = rec["report_no"]

    # 본문 편집 + server-owned 위조 필드 동시 주입.
    updated = db.update_near_miss_report(rid, _valid_edit(
        status="EVALUATED", report_no="WRONG", reporter_emp_no="9999",
        reporter_user_id=999, confirmed_grade="S", evaluator_emp_no="9999",
        dept_code="ZZZ", is_active=False, id=999999, rejection_reason="위조",
        evaluated_at="2000-01-01T00:00:00Z",
    ), current_user=reporter)

    check("작업명 수정 반영", updated["work_name"] == "수정된 작업")
    check("사고 내용 수정 반영", updated["incident_content"] == "수정된 사고 내용")
    check("원인 코드 수정 반영", updated["cause_code"] == "FALL")
    check("제안 등급 수정 반영", updated["proposed_grade"] == "B")
    check("사고일 수정 반영", updated["incident_date"] == "2026-07-15")
    check("사진 배열 수정 반영(list 보존)", updated["photo_paths"] == ["a.jpg", "b.jpg"])
    # server-owned 필드는 위조 시도에도 불변.
    check("상태는 SUBMITTED 유지(위조 무시)", updated["status"] == "SUBMITTED")
    check("report_no 불변", updated["report_no"] == orig_report_no)
    check("보고자 불변", updated["reporter_emp_no"] == reporter["emp_no"])
    check("확정 등급 미설정 유지", updated["confirmed_grade"] in (None, ""))
    check("평가자 미설정 유지", str(updated["evaluator_emp_no"]) == "")
    check("id 불변", str(updated["id"]) == str(rid))
    check("is_active True 유지", bool(updated["is_active"]) is True)

    # 제안 등급을 비워(해제) 저장하면 None 으로 반영된다(allow_null).
    cleared = db.update_near_miss_report(rid, _valid_edit(proposed_grade=None), current_user=reporter)
    check("제안 등급 해제(None) 반영", cleared["proposed_grade"] in (None, ""))


def test_update_non_owner_blocked() -> None:
    print("update_near_miss_report 비소유자 차단")
    reporter = _sample_emp(0)
    other = _sample_emp(1)
    check("전제: 두 사용자 사번 다름", reporter["emp_no"] != other["emp_no"])
    rec = _fresh_submitted(reporter)
    rid = rec["id"]

    exc = raises(lambda: db.update_near_miss_report(rid, _valid_edit(), current_user=other), ValueError)
    check("비소유자 수정은 ValueError", exc is not None)
    check("비소유자 안내 메시지", exc is not None and "본인이 보고한" in str(exc))
    check("비소유자 시도로 본문 불변", db.get_near_miss_report(rid)["work_name"] == "설비 점검")


def test_update_non_submitted_blocked() -> None:
    print("update_near_miss_report 비-SUBMITTED 상태 차단(IN_REVIEW/EVALUATED/REJECTED/CLOSED)")
    reporter = _sample_emp(0)
    evaluator = _sample_emp(1)

    # IN_REVIEW 에서 수정 불가.
    rec = _fresh_submitted(reporter)
    rid = rec["id"]
    db.update_near_miss_status(rid, "IN_REVIEW", current_user=evaluator)
    exc = raises(lambda: db.update_near_miss_report(rid, _valid_edit(), current_user=reporter), ValueError)
    check("IN_REVIEW 수정 차단", exc is not None and "SUBMITTED" in str(exc))
    check("IN_REVIEW 시도로 본문 불변", db.get_near_miss_report(rid)["work_name"] == "설비 점검")

    # EVALUATED 에서 수정 불가.
    db.evaluate_near_miss(rid, "B", current_user=evaluator)
    exc2 = raises(lambda: db.update_near_miss_report(rid, _valid_edit(), current_user=reporter), ValueError)
    check("EVALUATED 수정 차단", exc2 is not None and "SUBMITTED" in str(exc2))

    # CLOSED 에서 수정 불가.
    db.update_near_miss_status(rid, "CLOSED", current_user=evaluator)
    exc3 = raises(lambda: db.update_near_miss_report(rid, _valid_edit(), current_user=reporter), ValueError)
    check("CLOSED 수정 차단", exc3 is not None and "SUBMITTED" in str(exc3))

    # REJECTED 에서 수정 불가(별도 보고서).
    rec2 = _fresh_submitted(reporter)
    rid2 = rec2["id"]
    db.update_near_miss_status(rid2, "REJECTED", rejection_reason="사유", current_user=evaluator)
    exc4 = raises(lambda: db.update_near_miss_report(rid2, _valid_edit(), current_user=reporter), ValueError)
    check("REJECTED 수정 차단", exc4 is not None and "SUBMITTED" in str(exc4))


def test_update_invalid_values_rejected() -> None:
    print("update_near_miss_report 필드 검증(create 와 동일 검증) — 잘못된 값 거부")
    reporter = _sample_emp(0)
    rec = _fresh_submitted(reporter)
    rid = rec["id"]

    def bad(**over):
        return raises(lambda: db.update_near_miss_report(rid, _valid_edit(**over), current_user=reporter), ValueError)

    check("빈 작업명 거부", bad(work_name="   ") is not None)
    check("잘못된 원인 코드 거부", bad(cause_code="NOPE") is not None)
    check("잘못된 제안 등급 거부", bad(proposed_grade="Z") is not None)
    check("잘못된 사고일 형식 거부", bad(incident_date="2026/07/15") is not None)
    check("photo_paths 비배열 거부", bad(photo_paths="notalist") is not None)
    # 검증 실패 후에도 원본은 그대로(DB 요청 전 차단).
    check("검증 실패는 본문 미변경", db.get_near_miss_report(rid)["work_name"] == "설비 점검")


def test_update_stale_zero_row_raises() -> None:
    print("update_near_miss_report stale(0행/소유자·상태 불일치) 처리")
    reporter = _sample_emp(0)
    rec = _fresh_submitted(reporter)
    rid = rec["id"]

    # sample primitive: 소유자 불일치 → False(=조건부 0행 대응).
    ok = db._sample_update_near_miss(
        rid, expected_status="SUBMITTED", owner_emp_no="다른사번", work_name="x")
    check("소유자 불일치 primitive False", ok is False)
    # sample primitive: 상태 불일치 → False.
    stale = db._sample_update_near_miss(
        rid, expected_status="IN_REVIEW", owner_emp_no=reporter["emp_no"], work_name="x")
    check("상태 불일치 primitive False", stale is False)
    check("primitive 실패로 본문 불변", db.get_near_miss_report(rid)["work_name"] == "설비 점검")

    # 파사드: primitive 가 False 면 stale 오류로 올린다(게이트 통과 후 원자 UPDATE 실패).
    orig = db._sample_update_near_miss
    db._sample_update_near_miss = lambda *a, **k: False
    try:
        exc = raises(lambda: db.update_near_miss_report(rid, _valid_edit(), current_user=reporter), ValueError)
    finally:
        db._sample_update_near_miss = orig
    check("파사드 stale 오류", exc is not None and "이미 변경" in str(exc))

    # 존재하지 않는 보고서 → ValueError(찾을 수 없음).
    exc2 = raises(lambda: db.update_near_miss_report(999999, _valid_edit(), current_user=reporter), ValueError)
    check("없는 보고서 수정 차단", exc2 is not None and "찾을 수 없습니다" in str(exc2))


def test_update_owner_case_sensitive_distinct() -> None:
    print("update_near_miss_report 소유자 대소문자 구분(ABC vs abc 는 별개 소유자, supabase 정합)")
    st.session_state.pop(db._NEAR_MISS_STORE, None)
    orig_find = db.find_user_by_emp_no

    def finder(emp, **kw):
        # 대소문자만 다른 두 활성 계정(정확 대소문자 보존) — 로그인 exact-preference 모사.
        e = str(emp).strip()
        if e in ("ABC", "abc"):
            return {"emp_no": e, "dept_code": "D1", "role": "USER", "is_active": True}
        return orig_find(emp)

    db.find_user_by_emp_no = finder
    try:
        upper = {"emp_no": "ABC", "dept_code": "D1", "role": "USER"}
        lower = {"emp_no": "abc", "dept_code": "D1", "role": "USER"}
        rec = db.create_near_miss_report(_base_payload(), current_user=upper)
        rid = rec["id"]
        check("보고자 대문자 ABC 로 확정", rec["reporter_emp_no"] == "ABC")

        # (a) 대소문자만 다른 abc 는 별개 소유자 → 수정 차단(supabase 0행 stale 과 동일 효과).
        exc = raises(lambda: db.update_near_miss_report(rid, _valid_edit(), current_user=lower), ValueError)
        check("abc 는 ABC 보고서 수정 불가(대소문자 구분)", exc is not None and "본인이 보고한" in str(exc))
        check("차단 후 본문 불변", db.get_near_miss_report(rid)["work_name"] == "설비 점검")

        # 진짜 소유자 ABC 는 정상 수정.
        updated = db.update_near_miss_report(rid, _valid_edit(), current_user=upper)
        check("ABC 본인은 수정 가능", updated["work_name"] == "수정된 작업")

        # (b) 내 아차사고 reporter 필터는 정확 일치 — abc 목록에 ABC 보고서 없음.
        mine_lower = db.get_near_miss_reports({"reporter_emp_no": "abc"})
        check("abc 의 내 목록은 비어있음(ABC 보고서 미포함)", mine_lower.empty)
        mine_upper = db.get_near_miss_reports({"reporter_emp_no": "ABC"})
        check("ABC 의 내 목록에는 ABC 보고서 있음",
              not mine_upper.empty and (mine_upper["reporter_emp_no"] == "ABC").all())

        # (c) 원자 primitive 소유자 게이트도 정확 일치.
        check("primitive: abc 소유자 불일치 False",
              db._sample_update_near_miss(rid, expected_status="SUBMITTED", owner_emp_no="abc", work_name="x") is False)
        check("primitive: ABC 소유자 일치 True",
              db._sample_update_near_miss(rid, expected_status="SUBMITTED", owner_emp_no="ABC", work_name="x") is True)
    finally:
        db.find_user_by_emp_no = orig_find
        st.session_state.pop(db._NEAR_MISS_STORE, None)


def test_repo_update_atomic_conditional() -> None:
    print("supabase update_near_miss_report 원자 조건부 UPDATE(소유자+상태+id)")
    edit = {
        "work_name": "x", "cause_code": "JAM", "incident_date": "2026-07-01",
        "proposed_grade": "C", "photo_paths": [],
    }

    # (a) 0행 갱신 → stale 오류(비소유자/비SUBMITTED/삭제 서버측 강제).
    bus = _new_bus([[]])
    exc = _with_repo_mocks(bus, lambda: raises(
        lambda: sr.update_near_miss_report(7, edit, reporter_emp_no="1001"),
        sr.SupabaseDataError))
    check("조건부 0행이면 stale 오류", exc is not None and "이미 변경" in str(exc))
    check("id 조건 포함", ("id", 7) in bus["eq"])
    check("reporter_user_id 조건 포함(소유자 서버강제)", ("reporter_user_id", 1) in bus["eq"])
    check("status=SUBMITTED 조건 포함(컷오프 서버강제)", ("status", "SUBMITTED") in bus["eq"])
    check("update 에 status 없음(상태 미변경)", "status" not in (bus["update"] or {}))
    check("update 에 server-owned 필드 없음",
          not (set(bus["update"] or {}) & (db._NEAR_MISS_SERVER_FIELDS - {"updated_by"})))

    # (b) 1행 갱신 → 정상 반환 + updated_by 서버 귀속.
    bus2 = _new_bus([[{"id": 7, "status": "SUBMITTED", "work_name": "x"}]])
    out = _with_repo_mocks(bus2, lambda: sr.update_near_miss_report(
        7, edit, reporter_emp_no="1001", updated_by="1001"))
    check("1행 갱신 시 정상 반환", out and out.get("id") == 7)
    check("updated_by 기록", (bus2["update"] or {}).get("updated_by") == "1001")


# =========================================================================
# P1-3 — 원자 전이(조건부 UPDATE) 로 stale 갱신 거부
# =========================================================================
def test_sample_atomic_transition_primitive() -> None:
    print("sample 원자 전이 primitive (_sample_update_near_miss expected_status) (P1-3)")
    st.session_state.pop(db._NEAR_MISS_STORE, None)
    reporter = _sample_emp(0)
    record = db.create_near_miss_report(_base_payload(), current_user=reporter)
    rid = record["id"]

    ok = db._sample_update_near_miss(rid, expected_status="SUBMITTED", status="IN_REVIEW")
    check("기대 상태 일치 시 적용(True)", ok is True)
    check("상태가 IN_REVIEW 로 전이", db.get_near_miss_report(rid)["status"] == "IN_REVIEW")

    # 이제 현재 상태는 IN_REVIEW. 오래된 기대값(SUBMITTED)으로 갱신하면 거부(False).
    stale = db._sample_update_near_miss(rid, expected_status="SUBMITTED", status="EVALUATED")
    check("stale 기대 상태면 미적용(False)", stale is False)
    check("stale 갱신은 상태를 바꾸지 않음", db.get_near_miss_report(rid)["status"] == "IN_REVIEW")


# --- 순수 mock: supabase 조건부 UPDATE 원자성 ---
class _FakeResp:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, bus):
        self.bus = bus

    def insert(self, record):
        self.bus["inserts"].append(dict(record))
        return self

    def update(self, updates):
        self.bus["update"] = dict(updates)
        return self

    def eq(self, col, val):
        self.bus["eq"].append((col, val))
        return self

    def execute(self):
        self.bus["execute_calls"] += 1
        item = self.bus["script"].pop(0)
        if isinstance(item, BaseException):
            raise item
        return _FakeResp(item)


class _FakeClient:
    def __init__(self, bus):
        self.bus = bus

    def table(self, name):
        self.bus["tables"].append(name)
        return _FakeQuery(self.bus)


def _new_bus(script):
    return {
        "script": list(script), "execute_calls": 0,
        "inserts": [], "update": None, "eq": [], "tables": [],
    }


def _with_repo_mocks(bus, fn):
    """near_miss_extensions_ready·client·_user_maps·_near_miss_natural 를 mock 으로 대체."""
    saved = {
        "ready": sr.near_miss_extensions_ready,
        "client": sr.client,
        "umaps": sr._user_maps,
        "natural": sr._near_miss_natural,
        "payload": sr._near_miss_write_payload,
        "nextno": sr._next_report_no,
    }
    sr.near_miss_extensions_ready = lambda: True
    sr.client = lambda: _FakeClient(bus)
    sr._user_maps = lambda: ({"1001": 1, "1002": 2}, {"1": "1001", "2": "1002"})
    sr._near_miss_natural = lambda rows: [dict(r) for r in rows]
    sr._near_miss_write_payload = lambda payload: {"incident_date": "2026-07-01"}
    sr._next_report_no = lambda ym: f"{ym}-0001"
    try:
        return fn()
    finally:
        sr.near_miss_extensions_ready = saved["ready"]
        sr.client = saved["client"]
        sr._user_maps = saved["umaps"]
        sr._near_miss_natural = saved["natural"]
        sr._near_miss_write_payload = saved["payload"]
        sr._next_report_no = saved["nextno"]


def test_repo_atomic_conditional_update() -> None:
    print("supabase update/evaluate 원자 조건부 UPDATE (P1-3)")

    # (a) 0행 갱신(다른 사용자가 먼저 전이) → stale 오류, 덮어쓰지 않음.
    bus = _new_bus([[]])  # 조건부 update 가 0행 반환
    exc = _with_repo_mocks(bus, lambda: raises(
        lambda: sr.update_near_miss_status(7, "EVALUATED", expected_status="SUBMITTED"),
        sr.SupabaseDataError,
    ))
    check("조건부 0행이면 stale 오류", exc is not None and "이미 변경" in str(exc))
    check("status=expected 조건이 쿼리에 포함", ("status", "SUBMITTED") in bus["eq"])
    check("id 조건도 포함", ("id", 7) in bus["eq"])

    # (b) 1행 갱신 → 정상 반환(덮어쓰기 성공).
    bus2 = _new_bus([[{"id": 7, "status": "EVALUATED"}]])
    out = _with_repo_mocks(bus2, lambda: sr.update_near_miss_status(
        7, "EVALUATED", expected_status="SUBMITTED"))
    check("1행 갱신 시 정상 반환", out and out.get("status") == "EVALUATED")

    # (c) evaluate 도 조건부 0행이면 stale.
    bus3 = _new_bus([[]])
    exc3 = _with_repo_mocks(bus3, lambda: raises(
        lambda: sr.evaluate_near_miss(7, "B", evaluator_emp_no="1002", expected_status="SUBMITTED"),
        sr.SupabaseDataError,
    ))
    check("evaluate 조건부 0행이면 stale", exc3 is not None and "이미 변경" in str(exc3))
    check("evaluate status 조건 포함", ("status", "SUBMITTED") in bus3["eq"])


# =========================================================================
# P1-2 — 비멱등 create 는 일시 오류로 재시도하지 않는다(중복 방지)
# =========================================================================
class _ReadError(Exception):
    """repr 에 transient marker(ReadError) 를 포함하는 가짜 소켓 오류."""


class _DupError(Exception):
    """unique_violation — 구조적 SQLSTATE 코드(23505)를 속성으로 노출(비-transient).

    텍스트 "duplicate key"/"unique" 없이 코드만으로 판정되는지 검증하기 위해
    메시지에는 해당 문구를 넣지 않는다."""
    code = "23505"

    def __init__(self, message="unique_violation on report_no"):
        super().__init__(message)


def test_create_no_blind_retry_on_transient() -> None:
    print("create INSERT 일시 오류 비멱등 처리 + SQLSTATE 채번 (P1-2)")

    # (a) 일시 통신 오류: 재시도하지 않고 '재조회 필요' 오류. INSERT 는 1회만.
    bus = _new_bus([_ReadError("socket read failed")])
    exc = _with_repo_mocks(bus, lambda: raises(
        lambda: sr.create_near_miss_report({}), sr.SupabaseDataError))
    check("일시 오류는 명시적 실패", exc is not None and "불명확" in str(exc))
    check("일시 오류 시 INSERT 재시도 안 함(1회)", bus["execute_calls"] == 1)
    check("일시 오류 시 INSERT 1건만 시도", len(bus["inserts"]) == 1)

    # (b) 진짜 unique 충돌(SQLSTATE 23505, 텍스트 아님): DB 거부(=미저장) → 재채번 안전.
    bus2 = _new_bus([
        _DupError(),
        _DupError(),
        [{"id": 5, "report_no": "202607-0001", "status": "SUBMITTED"}],
    ])
    out = _with_repo_mocks(bus2, lambda: sr.create_near_miss_report({}))
    check("SQLSTATE 23505 로 unique 판정(텍스트 무관)", out and out.get("id") == 5)
    check("unique 충돌은 실제 재채번 재시도함(3회)", bus2["execute_calls"] == 3)
    # 구조적 판정 확인: 원 예외에 duplicate/unique 텍스트가 없어도 감지.
    check("_is_unique_violation 는 코드 기반", sr._is_unique_violation(_DupError()) is True)
    check("일반 오류는 unique 아님", sr._is_unique_violation(Exception("boom")) is False)

    # (c) 재채번 상한 소진 → 무한 루프 없이 fail-closed '재조회 필요'.
    bus3 = _new_bus([_DupError() for _ in range(sr._NEAR_MISS_CREATE_RETRIES)])
    exc3 = _with_repo_mocks(bus3, lambda: raises(
        lambda: sr.create_near_miss_report({}), sr.SupabaseDataError))
    check("상한 소진 시 fail-closed 오류", exc3 is not None and "재조회" in str(exc3))
    check("재시도는 상한(bounded)까지만", bus3["execute_calls"] == sr._NEAR_MISS_CREATE_RETRIES)


# =========================================================================
# P2 — readiness 3-state (미적용 vs probe 실패 구분, 일시 장애 비고착)
# =========================================================================
def test_readiness_three_state() -> None:
    print("near_miss readiness 3-state (P2)")
    saved_client = sr.client
    try:
        # NOT_READY: undefined table/column 표식 → False 로 안정 캐시.
        sr.reset_near_miss_readiness()

        class _MissingQuery:
            def select(self, *a, **k):
                return self

            def limit(self, *a, **k):
                return self

            def execute(self):
                raise Exception('relation "near_miss_reports" does not exist (42P01)')

        class _MissingClient:
            def table(self, name):
                return _MissingQuery()

        sr.client = lambda: _MissingClient()
        check("NOT_READY probe", sr.near_miss_extensions_probe(force=True) == sr.READINESS_NOT_READY)
        check("NOT_READY → ready False", sr.near_miss_extensions_ready() is False)

        # PROBE_ERROR: 일시/권한 오류 → 영구 부재로 캐시하지 않는다(재프로브).
        sr.reset_near_miss_readiness()
        probe_calls = {"n": 0}

        class _FlakyQuery:
            def select(self, *a, **k):
                return self

            def limit(self, *a, **k):
                return self

            def execute(self):
                probe_calls["n"] += 1
                raise Exception("network unreachable: connection timed out")

        class _FlakyClient:
            def table(self, name):
                return _FlakyQuery()

        sr.client = lambda: _FlakyClient()
        check("PROBE_ERROR probe", sr.near_miss_extensions_probe(force=True) == sr.READINESS_PROBE_ERROR)
        # ready() 는 보수적으로 False 지만 캐시하지 않고 매번 재프로브한다.
        n0 = probe_calls["n"]
        check("PROBE_ERROR → ready False(쓰기 보수 차단)", sr.near_miss_extensions_ready() is False)
        check("PROBE_ERROR 는 재프로브(비고착)", probe_calls["n"] > n0)
        again = probe_calls["n"]
        sr.near_miss_extensions_ready()
        check("PROBE_ERROR 매 호출 재프로브", probe_calls["n"] > again)
    finally:
        sr.client = saved_client
        sr.reset_near_miss_readiness()


class _OKQuery:
    def select(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _FakeResp([{"id": 1}])


class _OKClient:
    def table(self, name):
        return _OKQuery()


class _ErrQuery:
    def select(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        raise Exception("network unreachable: connection timed out")


class _ErrClient:
    def table(self, name):
        return _ErrQuery()


def test_probe_error_not_sticky() -> None:
    print("PROBE_ERROR 는 sticky 아님 — 이후 성공 시 갱신 (P2 잔여)")
    saved_client = sr.client
    try:
        # 1) 일시 장애 → PROBE_ERROR (캐시하지 않음).
        sr.reset_near_miss_readiness()
        sr.client = lambda: _ErrClient()
        check("최초 PROBE_ERROR", sr.near_miss_extensions_probe() == sr.READINESS_PROBE_ERROR)
        # 2) 장애 해소 후 재프로브 → READY (PROBE_ERROR 에 고착되지 않음).
        sr.client = lambda: _OKClient()
        check("이후 성공 시 probe READY(비고착)", sr.near_miss_extensions_probe() == sr.READINESS_READY)
        check("ready True", sr.near_miss_extensions_ready() is True)

        # 3) ready() 경로에서 성공하면 이전 PROBE_ERROR 캐시를 READY 로 갱신한다.
        sr.reset_near_miss_readiness()
        sr.client = lambda: _ErrClient()
        sr.near_miss_extensions_ready()  # PROBE_ERROR → False (비캐시)
        sr.client = lambda: _OKClient()
        check("ready() 성공", sr.near_miss_extensions_ready() is True)
        check("probe 도 READY 로 정합(고착 해제)", sr.near_miss_extensions_probe() == sr.READINESS_READY)
    finally:
        sr.client = saved_client
        sr.reset_near_miss_readiness()


# =========================================================================
# 006 SQL 계약(정적) — 필수 컬럼/제약/인덱스 존재
# =========================================================================
def test_migration_006_sql_contract() -> None:
    print("006_near_miss.sql 정적 계약")
    path = ROOT / "supabase" / "migrations" / "006_near_miss.sql"
    check("006 파일 존재", path.exists())
    sql = path.read_text(encoding="utf-8")
    low = sql.lower()

    # 신규 컬럼/테이블
    check("users.is_safety_officer 추가", "is_safety_officer" in low and "add column if not exists" in low)
    check("near_miss_reports 테이블(guarded)", "create table if not exists public.near_miss_reports" in low)

    # 필수 컬럼
    for col in (
        "report_no", "reporter_user_id", "evaluator_user_id", "department_id",
        "proposed_grade", "confirmed_grade", "cause_code", "incident_date",
        "photo_paths", "status", "rejection_reason", "evaluated_at", "is_active",
    ):
        check(f"컬럼 {col} 정의", col in low)

    # FK / 참조 무결성
    check("reporter FK on delete restrict", "reporter_user_id bigint not null references public.users(id) on delete restrict" in low)
    check("department FK", "department_id bigint references public.departments(id)" in low)
    check("report_no unique", "report_no text not null unique" in low)

    # 제약(constraint)
    for cons in (
        "near_miss_status_check", "near_miss_cause_code_check",
        "near_miss_proposed_grade_check", "near_miss_confirmed_grade_check",
        "near_miss_eval_consistency", "near_miss_rejection_reason",
        "near_miss_photo_paths_is_array",
    ):
        check(f"제약 {cons} 존재", cons in low)

    # 인덱스
    for idx in (
        "near_miss_status_active_idx", "near_miss_incident_date_idx",
        "near_miss_dept_date_idx", "near_miss_confirmed_grade_idx",
        "near_miss_cause_code_idx", "near_miss_reporter_idx",
    ):
        check(f"인덱스 {idx} 존재", idx in low)

    # 안전 관행: no-drop 테이블, RLS enable
    check("RLS enable", "enable row level security" in low)
    check("테이블 drop 없음(재실행 안전)", "drop table" not in low.replace("drop table if exists public.near_miss_reports;", ""))


# =========================================================================
# P1-a 재감사 반영 — 인가 조회 계약(P3-1 uncached / P3-2 종단 · P2 에러 투명성)
# =========================================================================
def test_find_user_uncached_contract() -> None:
    print("find_user_by_emp_no(use_cache=False) 캐시 우회·비훼손·오류전파·sample 동일 (P3-1)")
    # (d) sample 모드: uncached 와 cached 가 동일 레코드(사이에 캐시 계층이 없다).
    a = db.find_user_by_emp_no("1001", use_cache=True)
    b = db.find_user_by_emp_no("1001", use_cache=False)
    check("sample: use_cache True/False 같은 사용자", a is not None and b is not None and a["emp_no"] == b["emp_no"])
    check("sample: 두 경로 dict 동등", a == b)

    # (a)(b)(c) supabase 모드 시뮬레이션 — 캐시 소스(_fetch_users)와 uncached 소스
    # (sr.get_users)를 서로 다른 프레임으로 두고, 어느 소스에서 읽는지·호출 여부를 관측한다.
    saved = {
        "sample": db.is_sample_mode, "fetch": db._fetch_users,
        "sruser": sr.get_users, "flag": db._safety_officer_flag,
    }
    calls = {"fetch": 0, "sruser": 0}

    def cached():
        calls["fetch"] += 1
        return _users_frame([{"emp_no": "7000", "name": "c", "dept_code": "CACHED",
                              "role": "USER", "is_active": True}])

    def uncached(*a, **k):
        calls["sruser"] += 1
        return _users_frame([{"emp_no": "7000", "name": "u", "dept_code": "UNCACHED",
                              "role": "USER", "is_active": True}])

    db.is_sample_mode = lambda: False
    db._fetch_users = cached
    sr.get_users = uncached
    db._safety_officer_flag = lambda emp, **_: False  # 캐시 경로 검증에 안전담당 조회는 무관.
    try:
        # (a) use_cache=False 는 uncached 소스(sr.get_users)에서 읽는다.
        rec_u = db.find_user_by_emp_no("7000", use_cache=False)
        check("uncached 소스에서 읽음(dept=UNCACHED)", rec_u is not None and rec_u["dept_code"] == "UNCACHED")
        check("uncached 는 sr.get_users 호출", calls["sruser"] == 1)
        check("uncached 는 캐시 소스(_fetch_users) 미호출", calls["fetch"] == 0)

        # (b) 이어진 use_cache=True 는 캐시 소스에서 읽는다(uncached 읽기가 캐시를 훼손하지 않음).
        rec_c = db.find_user_by_emp_no("7000", use_cache=True)
        check("cached 소스에서 읽음(dept=CACHED)", rec_c is not None and rec_c["dept_code"] == "CACHED")
        check("cached 는 _fetch_users 호출", calls["fetch"] == 1)

        # (c) uncached 경로의 원격 오류는 전파한다(None·빈 결과로 은폐하지 않음).
        def boom(*a, **k):
            raise sr.SupabaseDataError("Supabase users 조회 실패: connection reset")

        sr.get_users = boom
        exc = raises(lambda: db.find_user_by_emp_no("7000", use_cache=False), sr.SupabaseDataError)
        check("uncached 원격 오류 전파", exc is not None)
    finally:
        db.is_sample_mode = saved["sample"]
        db._fetch_users = saved["fetch"]
        sr.get_users = saved["sruser"]
        db._safety_officer_flag = saved["flag"]


def test_safety_officer_authz_error_transparency() -> None:
    print("인가 안전담당자 조회: 미준비=False(fail-closed) vs 일시오류=전파, ADMIN 비영향 (P2)")
    # 표식 분류가 미준비(undefined-column)와 일시오류(네트워크)를 가른다.
    check("미준비(undefined-column) 분류",
          sr.is_missing_column_error(sr.SupabaseDataError("... column is_safety_officer does not exist (42703)")) is True)
    check("일시오류(네트워크) 분류(미준비 아님)",
          sr.is_missing_column_error(sr.SupabaseDataError("connection timed out")) is False)

    saved = {"sample": db.is_sample_mode, "sruser": sr.get_users, "sofl": sr.user_is_safety_officer}
    db.is_sample_mode = lambda: False

    def not_ready(emp):
        raise sr.SupabaseDataError("Supabase users 조회 실패: column users.is_safety_officer does not exist (42703)")

    def transient(emp):
        raise sr.SupabaseDataError("Supabase users 조회 실패: network unreachable: connection timed out")

    try:
        # (1) 미준비(006 미적용/컬럼 부재): 인가 경로라도 능력 없음(False)로 접는다(fail-closed).
        sr.get_users = lambda *a, **k: _users_frame([
            {"emp_no": "U1", "name": "u", "dept_code": "D", "role": "USER", "is_active": True}])
        sr.user_is_safety_officer = not_ready
        rec = db.find_user_by_emp_no("U1", use_cache=False)
        check("미준비 → is_safety_officer False(fail-closed)", rec is not None and rec["is_safety_officer"] is False)
        check("미준비 → USER 평가 능력 없음", auth.can_evaluate_near_miss(rec) is False)

        # (2) 일시 데이터소스 오류: False 로 은폐하지 않고 전파(권한없음으로 둔갑 금지).
        sr.user_is_safety_officer = transient
        exc = raises(lambda: db.find_user_by_emp_no("U1", use_cache=False), sr.SupabaseDataError)
        check("USER 인가 조회 일시오류 → 전파(은폐 금지)", exc is not None)
        excT = raises(lambda: db.evaluate_near_miss(1, "B", current_user={"emp_no": "U1"}), Exception)
        check("evaluate 진입 시 일시오류 전파(SupabaseDataError)", isinstance(excT, sr.SupabaseDataError))
        check("전파 오류는 '권한없음' ValueError 가 아님", not isinstance(excT, ValueError))

        # (3) 표시/로그인(use_cache=True, strict=False)은 일시오류도 관대하게 False(기존 거동 보존).
        rec_disp = db.find_user_by_emp_no("U1", use_cache=True)
        check("표시 경로는 일시오류도 False 로 접음", rec_disp is not None and rec_disp["is_safety_officer"] is False)

        # (4) ADMIN: 능력이 role 로 결정 → 안전담당자 조회 일시오류가 인가를 막지 않는다.
        sr.get_users = lambda *a, **k: _users_frame([
            {"emp_no": "A1", "name": "a", "dept_code": "D", "role": "ADMIN", "is_active": True}])
        sr.user_is_safety_officer = transient
        rec_admin = db.find_user_by_emp_no("A1", use_cache=False)  # 예외 없이 반환
        check("ADMIN 인가 조회 일시오류 비영향(전파 안 함)", rec_admin is not None and rec_admin["is_safety_officer"] is False)
        check("ADMIN 능력은 role 로 True(플래그 불필요)", auth.can_evaluate_near_miss(rec_admin) is True)
    finally:
        db.is_sample_mode = saved["sample"]
        sr.get_users = saved["sruser"]
        sr.user_is_safety_officer = saved["sofl"]
        db._invalidate_users()


def test_near_miss_actor_end_to_end_real_flag() -> None:
    print("종단: _near_miss_actor→find_user(use_cache=False)→실 컬럼 읽기→실제 평가 전이 (P3-2)")
    saved = {
        "sample": db.is_sample_mode, "sruser": sr.get_users,
        "sofl": sr.user_is_safety_officer, "getrep": db.get_near_miss_report,
        "repoeval": sr.evaluate_near_miss,
    }
    db.is_sample_mode = lambda: False
    calls = {"sofl": 0, "eval": 0}
    try:
        # 안전담당자 USER — use_cache=False 실 조회 + is_safety_officer 실 컬럼 읽기 + 실제 전이를
        # 하나의 경로로 실행한다(기존엔 컬럼읽기와 actor 능력판정을 따로 검사).
        sr.get_users = lambda *a, **k: _users_frame([
            {"emp_no": "SO1", "name": "so", "dept_code": "D", "role": "USER", "is_active": True}])

        def real_flag_read(emp):
            calls["sofl"] += 1
            return str(emp).strip() == "SO1"  # 006 컬럼 값(True)

        def repo_eval(report_id, grade, *, evaluator_emp_no, expected_status, updated_by):
            calls["eval"] += 1
            return {"id": report_id, "status": "EVALUATED", "confirmed_grade": grade,
                    "evaluator_emp_no": evaluator_emp_no}

        sr.user_is_safety_officer = real_flag_read
        db.get_near_miss_report = lambda rid: {"id": rid, "status": "SUBMITTED", "reporter_emp_no": "OTHER"}
        sr.evaluate_near_miss = repo_eval

        out = db.evaluate_near_miss(42, "B", current_user={"emp_no": "SO1"})
        check("종단 평가 성공(EVALUATED)", out is not None and out["status"] == "EVALUATED")
        check("평가자=권위 안전담당자 사번(서버확정)", out["evaluator_emp_no"] == "SO1")
        check("능력근거가 실 컬럼 읽기에서 옴", calls["sofl"] >= 1)
        check("실제 전이(repo evaluate) 1회 실행", calls["eval"] == 1)
    finally:
        db.is_sample_mode = saved["sample"]
        sr.get_users = saved["sruser"]
        sr.user_is_safety_officer = saved["sofl"]
        db.get_near_miss_report = saved["getrep"]
        sr.evaluate_near_miss = saved["repoeval"]
        db._invalidate_near_miss()


def main() -> int:
    for test in (
        test_auth_bool_canonicalization,
        test_server_side_identity_on_create,
        test_server_side_identity_on_evaluate,
        test_forged_current_user_dept_ignored,
        test_facade_strips_client_audit_fields,
        test_reevaluate_already_evaluated_rejected,
        test_same_state_retransition_blocked,
        test_status_change_requires_authenticated_actor,
        test_status_change_capability_gate,
        test_rejected_to_submitted_authz,
        test_evaluate_requires_capability,
        test_safety_officer_can_evaluate,
        test_inactive_user_action_blocked,
        test_evaluated_direct_transition_blocked,
        test_status_change_audit_attribution,
        test_safety_officer_capability_real_read_path,
        test_full_transition_table_positive,
        test_authz_then_stale_race,
        test_update_owner_submitted_allows_edit,
        test_update_non_owner_blocked,
        test_update_non_submitted_blocked,
        test_update_invalid_values_rejected,
        test_update_stale_zero_row_raises,
        test_update_owner_case_sensitive_distinct,
        test_repo_update_atomic_conditional,
        test_sample_atomic_transition_primitive,
        test_repo_atomic_conditional_update,
        test_create_no_blind_retry_on_transient,
        test_readiness_three_state,
        test_probe_error_not_sticky,
        test_find_user_uncached_contract,
        test_safety_officer_authz_error_transparency,
        test_near_miss_actor_end_to_end_real_flag,
        test_migration_006_sql_contract,
    ):
        test()
    print(f"\nALL PASSED ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
