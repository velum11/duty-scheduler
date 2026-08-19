"""아차사고 보완요청 파생 라벨 · 재제출 인가 · 개선조치 일괄조회(N+1 금지) 계약 테스트.

2026-08-19 사용자 요청 2건의 새 계약을 고정한다.

1. **보완요청을 보고자가 알 수 있어야 한다** — 보완요청(반송)은 상태를 IN_REVIEW→SUBMITTED
   로 되돌리므로 DB 상태만으로는 갓 등록한 건과 구분되지 않는다. 새 DB 상태값을 만들지
   않고(migration 회피) 보완요청 3필드(007)를 **조회 payload 에 실어** 화면이 '보완요청'
   라벨을 파생한다. 두 모드(sample/supabase)가 같은 키를 갖는다(parity).
2. **보완 후 재제출** — ``db.resubmit_near_miss`` 가 3필드를 비운다. 인가(본인·보완요청
   걸림·SUBMITTED)는 **서버측(파사드)** 판정이며 화면 게이트를 신뢰하지 않는다.
3. **개선조치 상태 열** — 조회 목록 전체의 개선조치를 **1회(청크당 1회)** 조회한다.
   보고서 수에 비례하는 단건 조회(N+1)를 만들지 않는다.
4. **'평가 착수' 폐지**(2026-08-19 사용자 결정) — 평가 대기(SUBMITTED)에서 곧장 보완요청·
   반려·평가확정을 한다. 전이표는 그대로이고(SUBMITTED→EVALUATED/REJECTED 는 이미 허용)
   보완요청 허용 상태만 ``{SUBMITTED, IN_REVIEW}`` 로 넓어졌다. 화면이 착수를 몰래 대신
   누르는 2회 쓰기를 만들지 않는지, 인가가 약해지지 않았는지 함께 고정한다.

원격 write 없이 sample 모드 + 순수 mock 으로만 검증한다(실DB 미접속).

실행: PYTHONUTF8=1 DUTY_DATA_MODE=sample .venv/Scripts/python.exe scripts/test_near_miss_revision_resubmit.py
"""
from __future__ import annotations

import inspect
import io
import os
import re
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

from modules import db  # noqa: E402
from modules import supabase_repository as sr  # noqa: E402
from views import near_miss_evaluate as nme  # noqa: E402
from views import near_miss_my as nmy  # noqa: E402
from views import near_miss_view as nmv  # noqa: E402
from views.common import near_miss as nmc  # noqa: E402

PASSED = 0

_REVISION_FIELDS = (
    "revision_request_reason",
    "revision_requested_by_emp_no",
    "revision_requested_at",
)


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    assert condition, f"FAILED: {name}" + (f" — {detail}" if detail else "")
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


def _actor_of_role(role: str, *, exclude=()):
    exclude = set(exclude)
    for _, row in db.get_users().iterrows():
        emp = str(row["emp_no"])
        if (str(row.get("role") or "").strip().upper() == role.upper()
                and bool(row.get("is_active")) and emp not in exclude):
            return {"emp_no": emp}
    raise AssertionError(f"sample 사용자에 role={role} 없음")


def _payload(**over) -> dict:
    p = {"work_name": "설비 점검", "incident_content": "덮개 미고정",
         "cause_code": "JAM", "incident_date": "2026-07-10"}
    p.update(over)
    return p


def _revision_report(reporter: dict, evaluator: dict, reason: str = "덮개 상세를 보완하세요"):
    """SUBMITTED → IN_REVIEW → 보완요청(SUBMITTED 로 반송) 한 건을 만들고 id 를 돌려준다."""
    rec = db.create_near_miss_report(_payload(), current_user=reporter)
    db.update_near_miss_status(rec["id"], "IN_REVIEW", current_user=evaluator)
    db.request_near_miss_revision(rec["id"], reason, current_user=evaluator)
    return rec["id"]


# =========================================================================
# 1) 조회 payload 계약 — 보완요청 3필드가 실린다(sample/supabase parity)
# =========================================================================
def test_payload_carries_revision_fields() -> None:
    print("조회 payload — 보완요청 3필드(NEAR_MISS_COLUMNS parity)")
    for field in _REVISION_FIELDS:
        check(f"NEAR_MISS_COLUMNS 에 {field}", field in db.NEAR_MISS_COLUMNS)
    check("파사드 계약이 리포지토리 계약과 동일",
          db.NEAR_MISS_COLUMNS is sr.NEAR_MISS_COLUMNS)

    _reset()
    reporter = _actor_of_role("USER")
    evaluator = _actor_of_role("MANAGER")
    rid = _revision_report(reporter, evaluator)

    frame = db.get_near_miss_reports({"reporter_emp_no": reporter["emp_no"]})
    for field in _REVISION_FIELDS:
        check(f"목록 프레임 열에 {field}", field in frame.columns)
    row = frame[frame["id"].astype(str) == str(rid)].iloc[0]
    check("목록 payload 에 보완 사유", str(row["revision_request_reason"]) == "덮개 상세를 보완하세요")
    check("목록 payload 에 요청자(서버귀속 사번)",
          str(row["revision_requested_by_emp_no"]) == evaluator["emp_no"])
    check("목록 payload 에 요청시각", bool(str(row["revision_requested_at"] or "").strip()))
    check("상태 코드는 SUBMITTED 그대로(새 DB 상태값 없음)", str(row["status"]) == "SUBMITTED")

    # supabase 자연키 변환도 같은 3키를 낸다(모드 parity — 화면 파생이 모드에 따라 갈리지 않게).
    natural = sr._near_miss_natural([{
        "id": 1, "status": "SUBMITTED",
        "revision_request_reason": "보완 바람",
        "revision_requested_by_user_id": None,
        "revision_requested_at": "2026-08-19T00:00:00+00:00",
    }])[0]
    for field in _REVISION_FIELDS:
        check(f"supabase 자연키에도 {field}", field in natural)
    check("supabase: 요청자 미해석은 빈 문자열(부재 표기)",
          natural["revision_requested_by_emp_no"] == "")

    # 단건 편의 조회도 같은 값을 낸다(상세 배너 경로).
    rev = db.get_near_miss_revision_request(rid)
    check("get_near_miss_revision_request 사유 일치",
          rev and rev["revision_request_reason"] == "덮개 상세를 보완하세요")
    check("get_near_miss_revision_request 요청자 일치",
          rev["revision_requested_by_emp_no"] == evaluator["emp_no"])


# =========================================================================
# 2) 파생 라벨 — SUBMITTED + 보완요청 → '보완요청'(코드값 불변)
# =========================================================================
def test_derived_revision_label() -> None:
    print("보완요청 파생 라벨(§3.6 코드값 불변·화면 라벨만)")
    labels = {"SUBMITTED": "제출됨", "IN_REVIEW": "평가중"}
    pending = {"status": "SUBMITTED", "revision_request_reason": "보완 바람"}
    plain = {"status": "SUBMITTED", "revision_request_reason": None}

    check("보완요청 걸린 SUBMITTED → '보완요청'",
          nmc.status_label(pending, labels) == "보완요청")
    check("보완요청 없는 SUBMITTED → '제출됨'",
          nmc.status_label(plain, labels) == "제출됨")
    check("공백만인 사유는 요청 아님",
          nmc.status_label({"status": "SUBMITTED", "revision_request_reason": "   "},
                           labels) == "제출됨")
    check("pandas 결측(NaN) 사유도 요청 아님",
          nmc.status_label({"status": "SUBMITTED",
                            "revision_request_reason": float("nan")}, labels) == "제출됨")
    check("SUBMITTED 아닌 상태는 파생하지 않는다(현재 상태가 사실)",
          nmc.status_label({"status": "IN_REVIEW",
                            "revision_request_reason": "보완 바람"}, labels) == "평가중")
    check("007 미적용(필드 부재)은 정상 부재",
          nmc.has_revision_request({"status": "SUBMITTED"}) is False)
    check("코드값은 어디서도 바뀌지 않는다(SUBMITTED 가 상태 도메인에 그대로)",
          "SUBMITTED" in db.NEAR_MISS_STATUSES and "REVISION" not in db.NEAR_MISS_STATUSES)

    # 3화면이 모두 공용 파생을 쓴다 — 한 화면만 바뀌는 §3.6 결함 재발 방지.
    check("조회 표가 공용 파생 사용",
          "nm_common.status_label" in inspect.getsource(nmv._to_display))
    check("내 아차사고 표가 공용 파생 사용",
          "nm_common.status_label" in inspect.getsource(nmy._to_display))
    check("내 아차사고 상세 배지가 공용 파생 사용",
          "nm_common.status_label" in inspect.getsource(nmy._detail_anchor_html))
    check("평가 관리 상세 배지가 공용 파생 사용",
          "has_revision_request" in inspect.getsource(nme._detail_head_html))

    # §3.3 — 상태의 '결과'도 보완요청 전용 문구로 갈린다(평가자는 새 건이 아니라 재제출 대기).
    check("평가 관리 보완요청 결과 문구 = 보고자 재제출 대기",
          "재제출" in nme._REVISION_EFFECT)
    check("반려 문구에서 '재제출' 제거(반려는 종결분기 — 재제출 경로 없음)",
          "재제출" not in nme._STATUS_EFFECT["REJECTED"])
    check("내 아차사고 보완요청 결과 문구가 재제출을 지시",
          "재제출" in nmy._REVISION_EFFECT)


# =========================================================================
# 2-b) 평가 착수 없이 판정한다 (2026-08-19 사용자 결정)
# =========================================================================
def test_decide_without_review_start() -> None:
    """'평가 착수' 폐지 계약 — 평가 대기(SUBMITTED)에서 곧장 3 판정.

    사용자 요청: "평가 착수를 제거 했으면 좋겠어. 바로 보완요청이나 반려, 확정할 수 있게."

    상태 전이표(``db.NEAR_MISS_TRANSITIONS``)는 이미 SUBMITTED→EVALUATED·SUBMITTED→REJECTED
    를 허용했으므로 **전이표·migration 변경이 없다.** 넓어진 것은 보완요청 하나
    (``db._NEAR_MISS_REVISION_STATES``)이며, SUBMITTED 보완요청은 결과 상태가 같아
    **전이가 아니라 3필드 기록**이다.
    """
    print("평가 착수 없이 판정 — 평가 대기에서 보완요청·반려·평가확정")
    _reset()
    reporter = _actor_of_role("USER")
    evaluator = _actor_of_role("MANAGER")

    # 전이표는 손대지 않았다 — 즉시 확정·즉시 반려가 원래 허용돼 있었다는 사실을 고정한다.
    check("전이표 불변: SUBMITTED→EVALUATED 허용",
          db.near_miss_transition_allowed("SUBMITTED", "EVALUATED"))
    check("전이표 불변: SUBMITTED→REJECTED 허용",
          db.near_miss_transition_allowed("SUBMITTED", "REJECTED"))
    check("전이표는 자기 전이를 만들지 않는다(SUBMITTED→SUBMITTED 아님)",
          not db.near_miss_transition_allowed("SUBMITTED", "SUBMITTED"))
    check("보완요청 허용 상태 = SUBMITTED·IN_REVIEW",
          set(db._NEAR_MISS_REVISION_STATES) == {"SUBMITTED", "IN_REVIEW"})

    # (a) 평가 대기 → 보완요청. 착수 전이 없이 한 번의 쓰기로 끝난다.
    rid = db.create_near_miss_report(_payload(), current_user=reporter)["id"]
    check("갓 등록한 건은 SUBMITTED", db.get_near_miss_report(rid)["status"] == "SUBMITTED")
    out = db.request_near_miss_revision(rid, "덮개 사진을 첨부하세요", current_user=evaluator)
    check("착수 없이 보완요청 성공", out is not None)
    row = db.get_near_miss_report(rid)
    check("상태는 SUBMITTED 유지(전이 아님)", row["status"] == "SUBMITTED")
    check("보완요청 라벨 파생 유지(다른 Owner 계약 불변)",
          nmc.status_label(row, {"SUBMITTED": "제출됨"}) == "보완요청")
    check("요청자 서버귀속", row["revision_requested_by_emp_no"] == evaluator["emp_no"])
    # 보고자 재제출도 그대로 동작한다(3필드 해제 → 라벨 원복).
    db.resubmit_near_miss(rid, current_user={"emp_no": reporter["emp_no"]})
    check("재제출 후 라벨 원복",
          nmc.status_label(db.get_near_miss_report(rid), {"SUBMITTED": "제출됨"}) == "제출됨")

    # (b) 평가 대기 → 평가확정. IN_REVIEW 를 거치지 않는다.
    rid2 = db.create_near_miss_report(_payload(), current_user=reporter)["id"]
    db.evaluate_near_miss(rid2, "B", current_user=evaluator)
    ev = db.get_near_miss_report(rid2)
    check("착수 없이 평가확정 성공(SUBMITTED→EVALUATED)", ev["status"] == "EVALUATED")
    check("확정 등급 저장", str(ev["confirmed_grade"]) == "B")
    check("평가자 서버귀속", str(ev["evaluator_emp_no"]) == evaluator["emp_no"])

    # (c) 평가 대기 → 반려. 사유 필수는 그대로다.
    rid3 = db.create_near_miss_report(_payload(), current_user=reporter)["id"]
    check("반려 사유 없으면 차단(불변)",
          raises(lambda: db.update_near_miss_status(
              rid3, "REJECTED", current_user=evaluator), ValueError) is not None)
    db.update_near_miss_status(rid3, "REJECTED", rejection_reason="중복 보고",
                               current_user=evaluator)
    rj = db.get_near_miss_report(rid3)
    check("착수 없이 반려 성공(SUBMITTED→REJECTED)", rj["status"] == "REJECTED")
    check("반려 사유 저장", str(rj["rejection_reason"]) == "중복 보고")

    # (d) 인가는 약해지지 않았다 — 평가 능력 없는 USER 는 세 경로 모두 차단(서버측).
    rid4 = db.create_near_miss_report(_payload(), current_user=reporter)["id"]
    plain = {"emp_no": reporter["emp_no"]}
    for name, call in (
        ("보완요청", lambda: db.request_near_miss_revision(rid4, "사유", current_user=plain)),
        ("반려", lambda: db.update_near_miss_status(
            rid4, "REJECTED", rejection_reason="x", current_user=plain)),
        ("평가확정", lambda: db.evaluate_near_miss(rid4, "C", current_user=plain)),
    ):
        exc = raises(call, ValueError)
        check(f"무능력 USER {name} 차단(권한)", exc is not None and "권한" in str(exc))
    check("차단 후에도 상태 불변(SUBMITTED)",
          db.get_near_miss_report(rid4)["status"] == "SUBMITTED")
    check("차단 후 보완요청 기록도 남지 않는다",
          nmc.has_revision_request(db.get_near_miss_report(rid4)) is False)

    # (e) 화면 배선 — 액션 3종만 있고 IN_REVIEW 로 올리는 경로가 없다.
    _detail = inspect.getsource(nme._render_detail)
    check("화면 액션 3종(보완요청·반려·평가확정)",
          re.findall(r'st\.button\(\s*"([^"]+)"', _detail)
          == ["보완요청", "반려", "평가확정"])
    check("화면 보완요청 허용 상태 == 파사드 허용 상태",
          set(nme._REVISION_STATUSES) == set(db._NEAR_MISS_REVISION_STATES))
    check("보완요청은 선택을 유지한다(큐에 남는 액션 — 성공 후 엉뚱한 건으로 튀지 않게)",
          "keep_selection=True" in _detail)


# =========================================================================
# 3) 재제출 인가 — **서버측(파사드) 판정**
# =========================================================================
def test_resubmit_authorization_sample() -> None:
    print("resubmit_near_miss(sample): 본인·보완요청·SUBMITTED 서버측 인가")
    _reset()
    reporter = _actor_of_role("USER")
    other = _actor_of_role("USER", exclude={reporter["emp_no"]})
    evaluator = _actor_of_role("MANAGER")
    rid = _revision_report(reporter, evaluator)

    # (a) 무인증 — 세션 사용자가 없으면 DB 요청 전에 차단.
    check("무인증 차단",
          raises(lambda: db.resubmit_near_miss(rid, current_user=None), ValueError) is not None)
    # (b) 타인 — 평가 능력이 있어도 이 경로는 열리지 않는다(재제출은 보고자의 행위).
    exc_other = raises(lambda: db.resubmit_near_miss(
        rid, current_user={"emp_no": other["emp_no"]}), ValueError)
    check("타인 차단", exc_other is not None and "본인" in str(exc_other))
    exc_eval = raises(lambda: db.resubmit_near_miss(
        rid, current_user={"emp_no": evaluator["emp_no"]}), ValueError)
    check("평가자(비소유자)도 차단 — 평가 능력이 재제출을 열지 않는다",
          exc_eval is not None and "본인" in str(exc_eval))
    # (c) 차단 후에도 보완요청이 그대로 남아 있다(부분 적용 없음).
    check("차단 시 보완요청 유지",
          nmc.has_revision_request(db.get_near_miss_report(rid)) is True)

    # (d) 위조된 세션(사번만 신뢰) — role 조작으로는 열리지 않는다.
    exc_forge = raises(lambda: db.resubmit_near_miss(
        rid, current_user={"emp_no": other["emp_no"], "role": "ADMIN"}), ValueError)
    check("세션 role 위조로 우회 불가", exc_forge is not None and "본인" in str(exc_forge))

    # (e) 정상 재제출 — 3필드가 함께 비고 상태는 SUBMITTED 그대로다.
    out = db.resubmit_near_miss(rid, current_user={"emp_no": reporter["emp_no"]})
    check("재제출 성공(반환 있음)", out is not None)
    after = db.get_near_miss_report(rid)
    check("재제출 후 상태 불변(SUBMITTED)", str(after.get("status")) == "SUBMITTED")
    check("재제출 후 보완요청 해소", nmc.has_revision_request(after) is False)
    check("3필드가 함께 비었다(all-or-none)",
          not str(after.get("revision_request_reason") or "").strip()
          and not str(after.get("revision_requested_by_emp_no") or "").strip()
          and not str(after.get("revision_requested_at") or "").strip())
    check("재제출 후 라벨이 '제출됨'으로 되돌아간다",
          nmc.status_label(after, {"SUBMITTED": "제출됨"}) == "제출됨")
    check("단건 편의 조회도 None(요청 해소)", db.get_near_miss_revision_request(rid) is None)

    # (f) 보완요청이 없는 건은 재제출 대상이 아니다(중복 클릭·평범한 제출 건).
    exc_again = raises(lambda: db.resubmit_near_miss(
        rid, current_user={"emp_no": reporter["emp_no"]}), ValueError)
    check("보완요청 없는 건 차단", exc_again is not None and "보완요청" in str(exc_again))

    # (g) 상태가 SUBMITTED 가 아니면 차단(평가 착수 후 등).
    rid2 = _revision_report(reporter, evaluator)
    db.update_near_miss_status(rid2, "IN_REVIEW", current_user=evaluator)
    exc_state = raises(lambda: db.resubmit_near_miss(
        rid2, current_user={"emp_no": reporter["emp_no"]}), ValueError)
    check("SUBMITTED 아니면 차단", exc_state is not None and "SUBMITTED" in str(exc_state))

    # (h) 없는 보고서.
    check("미존재 보고서 차단",
          raises(lambda: db.resubmit_near_miss(
              "NO-SUCH-ID", current_user={"emp_no": reporter["emp_no"]}), ValueError) is not None)


def test_revision_fields_are_server_owned() -> None:
    print("보완요청 3필드는 서버 확정 — 본문 수정 payload 로 위조·해제 불가")
    for field in ("revision_request_reason", "revision_requested_at",
                  "revision_requested_by_emp_no", "revision_requested_by_user_id"):
        check(f"{field} 는 server-field", field in db._NEAR_MISS_SERVER_FIELDS)

    _reset()
    reporter = _actor_of_role("USER")
    evaluator = _actor_of_role("MANAGER")
    rid = _revision_report(reporter, evaluator)
    # 보고자가 본문 수정 payload 에 3필드를 실어도 파사드가 걷어낸다(재제출 위장 차단).
    db.update_near_miss_report(
        rid,
        _payload(revision_request_reason="", revision_requested_by_emp_no="",
                 revision_requested_at=""),
        current_user={"emp_no": reporter["emp_no"]},
    )
    check("본문 수정으로 보완요청을 지울 수 없다",
          nmc.has_revision_request(db.get_near_miss_report(rid)) is True)


# =========================================================================
# 4) supabase 경로 — 위임 인자·조건부 UPDATE·007 fail-closed
# =========================================================================
def test_resubmit_supabase_path() -> None:
    print("resubmit_near_miss(supabase): 위임 인자·서버귀속·007 fail-closed")
    reporter = _actor_of_role("USER")
    other = _actor_of_role("USER", exclude={reporter["emp_no"]})
    # 권위 사용자 레코드는 sample 에서 미리 떠 둔다(supabase 분기에서는 조회를 대체한다).
    records = {emp: db.find_user_by_emp_no(emp)
               for emp in (reporter["emp_no"], other["emp_no"])}
    captured: dict = {}

    saved = (db.is_sample_mode, db.find_user_by_emp_no, db.get_near_miss_report,
             db.near_miss_improvement_schema_probe,
             db.supabase_repository.clear_near_miss_revision_request,
             db._invalidate_near_miss)
    try:
        db.is_sample_mode = lambda: False  # type: ignore[assignment]
        db.find_user_by_emp_no = (  # type: ignore[assignment]
            lambda emp, **kw: records.get(str(emp).strip()))
        db.get_near_miss_report = lambda rid: {  # type: ignore[assignment]
            "id": rid, "status": "SUBMITTED",
            "reporter_emp_no": reporter["emp_no"],
            "revision_request_reason": "보완 바람",
            "revision_requested_at": "2026-08-19T01:00:00+00:00",
        }
        db.near_miss_improvement_schema_probe = lambda **k: db.READINESS_READY  # type: ignore[assignment]
        db._invalidate_near_miss = lambda: None  # type: ignore[assignment]

        def fake_clear(rid, *, reporter_emp_no, expected_status="SUBMITTED",
                       expected_revision_at=None):
            captured.update({"rid": rid, "reporter": reporter_emp_no,
                             "expected": expected_status,
                             "revision_at": expected_revision_at})
            return {"id": rid, "status": "SUBMITTED"}

        db.supabase_repository.clear_near_miss_revision_request = fake_clear  # type: ignore[assignment]

        db.resubmit_near_miss(20, current_user={"emp_no": reporter["emp_no"]})
        check("리포지토리에 위임", captured.get("rid") == 20)
        check("보고자는 인증 actor 사번으로 서버 확정(payload 아님)",
              captured.get("reporter") == reporter["emp_no"])
        check("조건부 UPDATE 기대상태 = SUBMITTED", captured.get("expected") == "SUBMITTED")
        # 재제출은 **읽은 그 요청**만 해소한다 — 그 사이 평가자가 새 보완요청을 걸었으면
        # 조건이 어긋나 0행(stale)이 된다. 조건을 안 걸면 못 본 요청을 지워 버린다.
        check("읽은 보완요청 시각을 UPDATE 조건으로 고정",
              captured.get("revision_at") == "2026-08-19T01:00:00+00:00")

        # 타인은 리포지토리에 도달하지 못한다(파사드가 먼저 차단).
        captured.clear()
        raises(lambda: db.resubmit_near_miss(20, current_user={"emp_no": other["emp_no"]}),
               ValueError)
        check("타인 요청은 리포지토리 호출 없이 차단", captured == {})

        # 007 미적용/불명 → fail-closed(사유를 해제할 컬럼이 없다).
        captured.clear()
        db.near_miss_improvement_schema_probe = lambda **k: db.READINESS_NOT_READY  # type: ignore[assignment]
        exc_nr = raises(lambda: db.resubmit_near_miss(
            20, current_user={"emp_no": reporter["emp_no"]}))
        check("007 미적용 → 차단", exc_nr is not None and captured == {})
        db.near_miss_improvement_schema_probe = lambda **k: db.READINESS_PROBE_ERROR  # type: ignore[assignment]
        exc_pe = raises(lambda: db.resubmit_near_miss(
            20, current_user={"emp_no": reporter["emp_no"]}))
        check("007 probe 오류 → 차단(불명을 성공으로 위장하지 않음)",
              exc_pe is not None and captured == {})
    finally:
        (db.is_sample_mode, db.find_user_by_emp_no, db.get_near_miss_report,
         db.near_miss_improvement_schema_probe,
         db.supabase_repository.clear_near_miss_revision_request,
         db._invalidate_near_miss) = saved


def test_repository_clear_conditions() -> None:
    print("clear_near_miss_revision_request: 3필드 동시 NULL + 소유자·상태 조건 UPDATE")
    seen: dict = {}

    class _Q:
        def update(self, updates):
            seen["updates"] = dict(updates)
            return self

        def eq(self, col, val):
            seen.setdefault("eq", []).append((col, val))
            return self

    class _Table:
        def table(self, name):
            seen["table"] = name
            return _Q()

    class _Resp:
        data = [{"id": 7, "status": "SUBMITTED"}]

    saved = (sr.near_miss_improvement_extensions_ready, sr._user_maps, sr.client, sr._execute)
    try:
        sr.near_miss_improvement_extensions_ready = lambda: True  # type: ignore[assignment]
        sr._user_maps = lambda emp_nos=None: ({"1001": 11}, {"11": "1001"})  # type: ignore[assignment]
        sr.client = lambda: _Table()  # type: ignore[assignment]
        sr._execute = lambda q, *a, **k: _Resp()  # type: ignore[assignment]

        sr.clear_near_miss_revision_request(7, reporter_emp_no="1001")
        updates = seen["updates"]
        check("사유·요청자·시각을 한 UPDATE 에서 모두 NULL(all-or-none CHECK 충족)",
              updates["revision_request_reason"] is None
              and updates["revision_requested_by_user_id"] is None
              and updates["revision_requested_at"] is None)
        check("상태 컬럼은 건드리지 않는다(새 전이 없음)", "status" not in updates)
        check("감사 귀속은 보고자 사번", updates.get("updated_by") == "1001")
        eq = dict(seen["eq"])
        check("WHERE 에 보고서 id", eq.get("id") == 7)
        check("WHERE 에 기대 상태(SUBMITTED) — TOCTOU 차단", eq.get("status") == "SUBMITTED")
        check("WHERE 에 소유자(reporter_user_id) — 광범위 UPDATE 방지",
              eq.get("reporter_user_id") == 11)

        # 0행(이미 전이됨/소유자 아님) → stale 오류. 조용한 성공 위장 없음.
        class _Empty:
            data = []

        sr._execute = lambda q, *a, **k: _Empty()  # type: ignore[assignment]
        exc = raises(lambda: sr.clear_near_miss_revision_request(7, reporter_emp_no="1001"),
                     sr.SupabaseDataError)
        check("조건부 0행 → stale 오류", exc is not None and "이미 변경" in str(exc))

        # 사번 미해석 → UPDATE 를 보내지 않고 차단(fail-closed).
        seen.clear()
        sr._execute = lambda q, *a, **k: _Resp()  # type: ignore[assignment]
        exc2 = raises(lambda: sr.clear_near_miss_revision_request(7, reporter_emp_no="GHOST"),
                      sr.SupabaseDataError)
        check("미해석 사번은 UPDATE 없이 차단", exc2 is not None and "updates" not in seen)

        # 007 미적용 → 차단.
        sr.near_miss_improvement_extensions_ready = lambda: False  # type: ignore[assignment]
        check("007 미적용 → 차단",
              raises(lambda: sr.clear_near_miss_revision_request(7, reporter_emp_no="1001"),
                     sr.SupabaseDataError) is not None)
    finally:
        (sr.near_miss_improvement_extensions_ready, sr._user_maps,
         sr.client, sr._execute) = saved


# =========================================================================
# 5) 개선조치 상태 열 — 일괄 조회(N+1 금지)
# =========================================================================
def test_improvement_status_bulk_not_n_plus_1() -> None:
    print("개선조치 일괄조회 — 왕복 수는 보고서 수가 아니라 청크 수")
    size = sr.IN_FILTER_CHUNK
    report_ids = list(range(1, size + 3))  # 202건 → 2 청크
    calls: list[dict] = []

    class _Q:
        def in_(self, col, values):
            calls[-1]["in"] = (col, list(values))
            return self

        def eq(self, col, val):
            calls[-1].setdefault("eq", []).append((col, val))
            return self

        def limit(self, *_a, **_k):
            return self

    def fake_select_all(table, columns="*", query_builder=None):
        calls.append({"table": table, "columns": columns})
        q = _Q()
        if query_builder is not None:
            query_builder(q)
        picked = calls[-1].get("in", (None, []))[1]
        return [{"report_id": rid, "submit_status": "SUBMITTED",
                 "confirm_status": "PENDING"} for rid in picked]

    saved = (sr._select_all, sr._near_miss_improvement_read_gate)
    try:
        sr._select_all = fake_select_all  # type: ignore[assignment]
        sr._near_miss_improvement_read_gate = lambda: True  # type: ignore[assignment]

        got = sr.get_near_miss_improvement_status_map(report_ids)
        check(f"보고서 {len(report_ids)}건 → 조회 호출 2회(청크 수)", len(calls) == 2,
              f"실제 {len(calls)}회")
        check("왕복 수가 보고서 수에 비례하지 않는다(N+1 아님)",
              len(calls) < len(report_ids))
        check(f"in_() 가 {size} 단위로 분할된다",
              [len(c["in"][1]) for c in calls] == [size, 2],
              str([len(c["in"][1]) for c in calls]))
        check("단건 eq(report_id) 조회를 쓰지 않는다",
              all("eq" not in c for c in calls))
        check("결과가 누락 없이 합쳐진다",
              set(got) == {str(r) for r in report_ids})
        check("상태값만 투영한다(본문·담당자 컬럼 미조회)",
              all(c["columns"] == "report_id,submit_status,confirm_status" for c in calls))

        # 빈 목록은 조회 자체를 하지 않는다.
        calls.clear()
        check("빈 목록 → 조회 0회", sr.get_near_miss_improvement_status_map([]) == {}
              and calls == [])

        # 큐 enrich(list_near_miss_improvements)도 같은 일괄 계약.
        calls.clear()
        rows = sr.get_near_miss_improvements_bulk(report_ids)
        check("큐 enrich 원본도 청크당 1회", len(calls) == 2, f"실제 {len(calls)}회")
        check("큐 enrich 결과도 전건 병합", len(rows) == len(report_ids))
    finally:
        sr._select_all, sr._near_miss_improvement_read_gate = saved


def test_view_improvement_column() -> None:
    print("조회 표 '개선조치' 열 — 상태 오른쪽 · 부재는 '-' · 단일 조회")
    check("개선조치가 상태 바로 오른쪽",
          nmv._DISPLAY_COLUMNS[-1] == "개선조치"
          and nmv._DISPLAY_COLUMNS.index("개선조치")
          == nmv._DISPLAY_COLUMNS.index("상태") + 1)
    check("개선조치 열에 폭 지정", nmv._COL_CONFIG["개선조치"]["width"] == 64)
    check("개선조치 열도 flex 없음(§ 남으면 남긴다)",
          "flex" not in nmv._COL_CONFIG["개선조치"])

    saved = (db.get_users, db.get_departments)
    try:
        db.get_users = lambda *a, **k: pd.DataFrame()  # type: ignore[assignment]
        db.get_departments = lambda *a, **k: pd.DataFrame()  # type: ignore[assignment]
        raw = pd.DataFrame([
            {"id": 1, "report_no": "N1", "status": "EVALUATED", "work_name": "a",
             "incident_content": "x", "incident_date": "2026-07-01", "cause_code": "JAM",
             "confirmed_grade": "B", "reporter_emp_no": "1001", "dept_code": "PET1"},
            {"id": 2, "report_no": "N2", "status": "SUBMITTED", "work_name": "b",
             "incident_content": "y", "incident_date": "2026-07-02", "cause_code": "JAM",
             "confirmed_grade": "", "reporter_emp_no": "1001", "dept_code": "PET1",
             "revision_request_reason": "보완 바람"},
        ])
        impr = {"1": {"submit_status": "SUBMITTED", "confirm_status": "CONFIRMED"}}
        out = nmv._to_display(raw, impr)
        check("개선조치 있는 행 → 단계 라벨", out.iloc[0]["개선조치"] == "확인됨")
        check("개선조치 없는 행 → '-'", out.iloc[1]["개선조치"] == "-")
        check("매핑 없이 호출하면 전 행 '-'",
              list(nmv._to_display(raw)["개선조치"]) == ["-", "-"])
        check("보완요청 건의 상태 열이 '보완요청'", out.iloc[1]["상태"] == "보완요청")
        check("보완요청 없는 건은 종전 라벨 유지", out.iloc[0]["상태"] == "평가완료")
        check("개선조치 단계 어휘가 개선조치 관리와 같은 출처",
              nmc.improvement_stage({"submit_status": "DRAFT"}) == "작성중"
              and nmc.improvement_stage({"confirm_status": "REJECTED"}) == "반려")
    finally:
        db.get_users, db.get_departments = saved

    # 화면은 목록 전체를 **한 번** 조회한다(행 루프 안에서 부르지 않는다).
    calls: list = []
    saved_map = db.get_near_miss_improvement_status_map
    try:
        db.get_near_miss_improvement_status_map = (  # type: ignore[assignment]
            lambda ids: calls.append(list(ids)) or {})
        df = pd.DataFrame({"id": [1, 2, 3, 4, 5]})
        got, failed = nmv._improvement_stages(df)
        check("보고서 5건에 파사드 호출 1회", len(calls) == 1, f"실제 {len(calls)}회")
        check("한 번에 전 id 를 넘긴다", calls[0] == [1, 2, 3, 4, 5])
        check("정상 조회는 실패 플래그 없음", failed is False and got == {})

        calls.clear()
        db.get_near_miss_improvement_status_map = (  # type: ignore[assignment]
            lambda ids: (_ for _ in ()).throw(RuntimeError("boom")))
        got2, failed2 = nmv._improvement_stages(df)
        check("조회 실패는 빈 값으로 위장하지 않고 플래그로 표면화",
              failed2 is True and got2 == {})
    finally:
        db.get_near_miss_improvement_status_map = saved_map  # type: ignore[assignment]


def test_my_screen_resubmit_entry() -> None:
    print("내 아차사고 — 재제출 진입은 보완요청 건에만, 인가는 파사드가 판정")
    src = inspect.getsource(nmy._render_edit_entry)
    check("보완요청이 없으면 재제출 버튼을 그리지 않는다(§3.2)", "resubmit_ready" in src)
    check("재제출 버튼이 주 액션(primary)", 'type="primary"' in src)
    resub = inspect.getsource(nmy._resubmit)
    check("재제출은 파사드를 부른다", "db.resubmit_near_miss" in resub)
    check("신원은 인증 세션에서 넘긴다(위젯 값 아님)",
          "auth.get_current_user()" in resub)
    check("실패는 fail-closed 로 표면화(성공 위장 없음)",
          "danger" in resub and "success" in resub)
    check("상세가 보완요청 사유·요청자·요청시각을 보여준다",
          all(f in inspect.getsource(nmy._render_revision_banner)
              for f in ("revision_request_reason", "revision_requested_by_emp_no",
                        "revision_requested_at")))
    # 성공 문구는 rerun 을 넘겨야 보인다 — 배너를 그린 직후 st.rerun() 하면 그 화면이
    # 즉시 버려져 사용자는 결과를 한 번도 못 본다(2026-08-19 실렌더에서 확인한 결함).
    check("성공 문구는 stash 후 rerun(직후 banner 금지)",
          "_stash_action_msg" in resub and 'banner("success"' not in resub)
    check("수정 저장도 같은 관행",
          "_stash_action_msg" in inspect.getsource(nmy._save_edit))
    check("상세 머리에서 stash 문구를 한 번 소비",
          "_flush_action_msg" in inspect.getsource(nmy._render_detail))

    # 조회 상세도 보완요청을 반려(warn)와 다른 시각(info)으로, 추가 조회 없이 보여준다.
    note = inspect.getsource(nmv._render_revision_note)
    check("조회 상세 보완요청은 info 배너(반려 warn 과 별개)", 'banner("info"' in note)
    check("조회 상세는 payload 3필드를 그대로 읽는다(추가 조회 없음)",
          all(f in note for f in ("revision_request_reason", "revision_requested_by_emp_no",
                                  "revision_requested_at"))
          and "get_near_miss_revision_request" not in note)

# =========================================================================
# 11) SUBMITTED 이탈 시 미해소 보완요청이 함께 끝난다 (Codex 감사 F1)
# =========================================================================
def test_revision_cleared_when_leaving_submitted() -> None:
    """미해소 보완요청은 **SUBMITTED 에서만** 존재한다는 규칙을 쓰기 경로에 고정한다.

    화면 라벨(views/common/near_miss.status_label)은 이미 SUBMITTED 일 때만 '보완요청'을
    파생하지만, 저장 쪽에서 3필드를 남겨 두면 데이터가 상태와 모순된다. 실제 피해는
    **재개**에서 나온다 — 반려로 3필드를 안고 나간 건이 REJECTED→SUBMITTED 로 돌아오면
    끝난 지 오래인 옛 사유가 현재 보완요청인 것처럼 되살아난다."""
    print("SUBMITTED 이탈 — 미해소 보완요청 3필드가 함께 끝난다(F1)")
    _reset()
    reporter = _actor_of_role("USER")
    evaluator = _actor_of_role("MANAGER")

    # (1) 평가확정으로 이탈
    rid = _revision_report(reporter, evaluator)
    before = db.get_near_miss_report(rid)
    check("전제: 보완요청이 걸린 SUBMITTED",
          str(before["status"]) == "SUBMITTED" and nmc.has_revision_request(before))
    db.evaluate_near_miss(rid, "B", current_user=evaluator)
    after = db.get_near_miss_report(rid)
    check("평가확정 후 상태 EVALUATED", str(after["status"]) == "EVALUATED")
    check("평가확정이 보완요청 3필드를 함께 비운다(all-or-none)",
          not nmc.has_revision_request(after)
          and not str(after.get("revision_requested_by_emp_no") or "").strip()
          and not str(after.get("revision_requested_at") or "").strip())

    # (2) 반려로 이탈 → 재개해도 옛 사유가 되살아나지 않는다
    rid2 = _revision_report(reporter, evaluator)
    db.update_near_miss_status(rid2, "REJECTED", rejection_reason="중복 보고",
                               current_user=evaluator)
    rejected = db.get_near_miss_report(rid2)
    check("반려도 3필드를 비운다", not nmc.has_revision_request(rejected))
    check("반려 사유는 보완 사유와 별개로 남는다",
          str(rejected.get("rejection_reason") or "").strip() == "중복 보고")

    db.update_near_miss_status(rid2, "SUBMITTED", current_user=reporter)
    reopened = db.get_near_miss_report(rid2)
    check("재개 후 상태 SUBMITTED", str(reopened["status"]) == "SUBMITTED")
    check("재개해도 '보완요청' 라벨이 부활하지 않는다",
          nmc.status_label(reopened, {"SUBMITTED": "제출됨"}) == "제출됨")
    check("재개 후 재제출도 불가(해소할 요청이 없다)",
          raises(lambda: db.resubmit_near_miss(rid2, current_user=reporter),
                 ValueError) is not None)

    # (3) 보완요청이 없던 평범한 건은 아무 영향이 없다(과잉 해제 금지)
    rec = db.create_near_miss_report(_payload(), current_user=reporter)
    db.evaluate_near_miss(rec["id"], "C", current_user=evaluator)
    plain = db.get_near_miss_report(rec["id"])
    check("보완요청 없던 건도 정상 평가확정", str(plain["status"]) == "EVALUATED"
          and str(plain.get("confirmed_grade")) == "C")


# =========================================================================
# 12) 읽은 보완요청 상태를 쓰기 조건에 고정한다 (Codex 감사 F2)
# =========================================================================
def test_revision_state_is_pinned() -> None:
    """``status`` 만으로는 '보완요청 걸린 SUBMITTED' 와 '재제출된 SUBMITTED' 가 구분되지
    않는다. 그래서 조건부 UPDATE 가 ``id+status(+owner)`` 만 걸면 그 사이 들어온 변경을
    못 본 채 덮어쓴다 — 보고자의 재제출이 평가자의 **새** 보완요청을 지우고, 두 평가자의
    보완요청 중 뒤엣것이 앞엣것을 조용히 덮어쓴다. 읽은 시각을 함께 고정하면 0행(stale)."""
    print("보완요청 상태 고정(CAS) — 못 본 변경을 덮어쓰지 않는다(F2)")
    _reset()
    reporter = _actor_of_role("USER")
    evaluator = _actor_of_role("MANAGER")
    other_eval = _actor_of_role("ADMIN", exclude={evaluator["emp_no"]})

    rid = _revision_report(reporter, evaluator)
    first = db.get_near_miss_report(rid)
    stamp = str(first["revision_requested_at"])
    check("전제: R1 시각이 있다", bool(stamp.strip()))

    # 다른 평가자가 새 요청(R2)을 건다 — 요청 시각이 바뀐다.
    db.request_near_miss_revision(rid, "사진도 첨부하세요", current_user=other_eval)
    second = db.get_near_miss_report(rid)
    check("R2 기록으로 요청 시각이 바뀐다", str(second["revision_requested_at"]) != stamp)
    check("R2 사유가 현재 사유", str(second["revision_request_reason"]) == "사진도 첨부하세요")

    # R1 만 본 상태의 재제출은 거부된다(sample CAS = supabase _pin_revision 대응).
    ok = db._sample_update_near_miss(
        rid, expected_status="SUBMITTED", owner_emp_no=reporter["emp_no"],
        expected_revision_at=stamp, clear_revision=True,
    )
    check("읽은 시각이 낡았으면 CAS 가 거부한다(stale)", ok is False)
    check("R2 는 지워지지 않고 남는다",
          nmc.has_revision_request(db.get_near_miss_report(rid)))

    # 현재 시각으로 읽은 재제출은 정상 성공한다(과잉 차단 금지).
    db.resubmit_near_miss(rid, current_user=reporter)
    check("최신 요청을 본 재제출은 성공",
          not nmc.has_revision_request(db.get_near_miss_report(rid)))

    # 본문 수정 경로(Codex r2 P1-1): 수정 폼을 열어 둔 사이 평가자가 보완요청을 걸면
    # 렌더 시점 값(None)을 조건으로 넘긴 저장은 stale 로 멈춘다 — 보고자가 사유를
    # 못 본 채 본문만 저장하는 일이 없다. 최신 값을 본 저장은 성공한다.
    rid2 = db.create_near_miss_report(_payload(), current_user=reporter)["id"]
    stale_view_at = db._near_miss_revision_at(db.get_near_miss_report(rid2))  # None
    db.request_near_miss_revision(rid2, "위치를 구체적으로", current_user=evaluator)
    check("수정 CAS — 낡은 렌더(요청 없음)를 조건으로 넘긴 저장은 차단",
          raises(lambda: db.update_near_miss_report(
              rid2, _payload(work_name="수정본"), current_user=reporter,
              expected_revision_at=stale_view_at), ValueError) is not None)
    check("차단됐으므로 본문은 그대로",
          str(db.get_near_miss_report(rid2)["work_name"]) != "수정본")
    fresh_at = db._near_miss_revision_at(db.get_near_miss_report(rid2))
    db.update_near_miss_report(rid2, _payload(work_name="수정본"),
                               current_user=reporter, expected_revision_at=fresh_at)
    check("최신 요청을 본 수정은 성공(요청은 유지)",
          str(db.get_near_miss_report(rid2)["work_name"]) == "수정본"
          and nmc.has_revision_request(db.get_near_miss_report(rid2)))

    # 리포지토리 쓰기 4종이 모두 고정 조건을 건다 — 하나만 빠져도 그 경로로 샌다.
    for fn in (sr.evaluate_near_miss, sr.update_near_miss_status,
               sr.request_near_miss_revision, sr.clear_near_miss_revision_request):
        check(f"{fn.__name__} 이 보완요청 상태를 고정한다",
              "_pin_revision" in inspect.getsource(fn))

    # _pin_revision 의 세 갈래(NULL 고정 / 시각 고정 / 미전달)와 007 미적용 처리.
    class _Q:
        def __init__(self):
            self.calls = []

        def is_(self, col, val):
            self.calls.append(("is_", col, val))
            return self

        def eq(self, col, val):
            self.calls.append(("eq", col, val))
            return self

    orig_probe = sr.near_miss_improvement_extensions_probe
    try:
        sr.near_miss_improvement_extensions_probe = lambda **k: sr.READINESS_READY
        q = _Q()
        sr._pin_revision(q, None)
        check("요청이 없던 상태는 NULL 로 고정",
              q.calls == [("is_", "revision_requested_at", "null")])
        q = _Q()
        sr._pin_revision(q, "2026-08-19T01:00:00+00:00")
        check("요청이 있던 상태는 그 시각으로 고정",
              q.calls == [("eq", "revision_requested_at", "2026-08-19T01:00:00+00:00")])
        q = _Q()
        sr._pin_revision(q, sr._UNPINNED)
        check("인자 미전달이면 조건을 걸지 않는다", q.calls == [])
        sr.near_miss_improvement_extensions_probe = lambda **k: sr.READINESS_NOT_READY
        q = _Q()
        sr._pin_revision(q, None)
        check("007 미적용(NOT_READY)이면 없는 컬럼에 조건을 걸지 않는다", q.calls == [])
        # probe 실패(PROBE_ERROR)는 미적용과 다르다 — 조건을 생략하면 007 적용 환경의
        # 일시 장애에서 CAS 없는 UPDATE 가 나가는 fail-open 이 된다(Codex r2 P1-2).
        sr.near_miss_improvement_extensions_probe = lambda **k: sr.READINESS_PROBE_ERROR
        q = _Q()
        check("probe 불명(PROBE_ERROR)이면 쓰기 차단(fail-closed)",
              raises(lambda: sr._pin_revision(q, None), sr.SupabaseDataError) is not None
              and q.calls == [])
    finally:
        sr.near_miss_improvement_extensions_probe = orig_probe


def main() -> None:
    test_payload_carries_revision_fields()
    test_derived_revision_label()
    test_decide_without_review_start()
    test_resubmit_authorization_sample()
    test_revision_fields_are_server_owned()
    test_resubmit_supabase_path()
    test_repository_clear_conditions()
    test_improvement_status_bulk_not_n_plus_1()
    test_view_improvement_column()
    test_my_screen_resubmit_entry()
    test_revision_cleared_when_leaving_submitted()
    test_revision_state_is_pinned()
    print(f"\nALL PASSED ({PASSED} checks)")


if __name__ == "__main__":
    main()
