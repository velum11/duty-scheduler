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
    db.find_user_by_emp_no = lambda emp: auth_record if str(emp).strip() == reporter["emp_no"] else None
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

    def finder(emp):
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


def main() -> int:
    for test in (
        test_auth_bool_canonicalization,
        test_server_side_identity_on_create,
        test_server_side_identity_on_evaluate,
        test_forged_current_user_dept_ignored,
        test_facade_strips_client_audit_fields,
        test_reevaluate_already_evaluated_rejected,
        test_same_state_retransition_blocked,
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
        test_migration_006_sql_contract,
    ):
        test()
    print(f"\nALL PASSED ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
