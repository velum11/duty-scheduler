"""신규 화면 프로토타입 계약 테스트 — 숙소 예약 · 업무요청서.

검증 대상은 **순수 도메인 함수**(검증 · 중복 판정 · 허용 액션 · 상태 전이 · 채번)와
로컬 저장소 왕복이다. Streamlit 런타임 없이 도는 순수 파이썬 테스트이며, 저장소는
``DUTY_PROTO_STATE_DIR`` 로 임시 디렉터리에 격리해 실제 작업 상태를 오염시키지 않는다.

화면(``views/*.py``) 자체의 유형 선언·크롬 규약은 ``scripts/test_screen_scaffold.py`` 가
소유하므로 여기서 중복 검사하지 않는다.

실행: .venv/Scripts/python.exe scripts/test_new_screens.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 저장소를 임시 디렉터리로 격리(import 전에 지정할 필요는 없다 — state_dir 는 호출 시 조회).
_TMP = tempfile.TemporaryDirectory(prefix="workops-proto-test-")
os.environ["DUTY_PROTO_STATE_DIR"] = _TMP.name

from modules import lodging_data as ld  # noqa: E402
from modules import proto_store  # noqa: E402
from modules import work_request_data as wr  # noqa: E402

PASS = 0
FAIL: list[str] = []

# 순수 함수 검사에는 today 를 명시 주입하고, 파일 왕복(e2e)은 실제 오늘을 쓰는 저장 경로를
# 지나므로 기준일을 실제 오늘로 둔다(날짜에 의존해 깨지지 않게).
TODAY = date.today()
D = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731

APPROVER = {"emp_no": "2024TEST50", "name": "한매니저", "role": "MANAGER", "dept_code": "MGT"}
ADMIN = {"emp_no": "2024TEST90", "name": "조관리", "role": "ADMIN", "dept_code": "MGT"}
OWNER = {"emp_no": "2024TEST01", "name": "김샘플", "role": "USER", "dept_code": "PET1"}
OTHER = {"emp_no": "2024TEST02", "name": "이가상", "role": "USER", "dept_code": "PET2"}

LODGING = {"lodging_code": "SATAEK-A-101", "lodging_name": "한빛사택 A동", "room_no": "101호",
           "lodging_type": "사택", "capacity": "4", "location": "-", "is_active": "true"}
LODGING_OFF = {**LODGING, "lodging_code": "DORM-2-110", "is_active": "false"}


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name}")


def reservation(**over) -> dict:
    base = {
        "request_no": "LDG-202608-001", "lodging_code": "SATAEK-A-101",
        "applicant_emp_no": "2024TEST01", "applicant_name": "김샘플", "dept_code": "PET1",
        "check_in": D(3), "check_out": D(6), "status": ld.REQUESTED,
        "decided_by": "", "decided_at": "", "decision_comment": "", "created_at": "",
    }
    base.update(over)
    return base


def request(**over) -> dict:
    base = {
        "request_no": "WR-202608-001", "title": "PC 교체 요청", "request_type": "전산",
        "priority": "보통", "requester_emp_no": "2024TEST01", "requester_name": "김샘플",
        "requester_dept": "PET1", "target_dept": "MGT", "desired_due": D(7),
        "content": "부팅 지연으로 인수인계가 늦어집니다. 교체를 요청합니다.",
        "reference": "", "status": wr.SUBMITTED, "assignee_emp_no": "", "assignee_name": "",
        "result_note": "", "reject_reason": "", "created_at": "", "updated_at": "",
    }
    base.update(over)
    return base


# ===========================================================================
print("(a) 숙소 — 반개구간 점유 판정")
# ===========================================================================
check("같은 날 체크아웃/체크인 교대는 겹침이 아니다",
      not ld.overlaps("2026-08-10", "2026-08-14", "2026-08-14", "2026-08-16"))
check("하루라도 물리면 겹침", ld.overlaps("2026-08-10", "2026-08-14", "2026-08-13", "2026-08-16"))
check("포함 관계도 겹침", ld.overlaps("2026-08-10", "2026-08-20", "2026-08-12", "2026-08-14"))
check("완전히 떨어진 구간은 비겹침",
      not ld.overlaps("2026-08-01", "2026-08-03", "2026-08-10", "2026-08-12"))
check("역순·결측 구간은 겹침으로 보지 않는다",
      not ld.overlaps("2026-08-14", "2026-08-10", "2026-08-12", "2026-08-16")
      and not ld.overlaps("", "2026-08-14", "2026-08-12", "2026-08-16"))
check("점유 일자는 체크아웃 당일을 제외한다",
      [d.isoformat() for d in ld.day_span(reservation(check_in="2026-08-10",
                                                      check_out="2026-08-13"))]
      == ["2026-08-10", "2026-08-11", "2026-08-12"])

_pool = [
    reservation(request_no="A", status=ld.APPROVED, check_in="2026-08-10", check_out="2026-08-14"),
    reservation(request_no="B", status=ld.REQUESTED, check_in="2026-08-11", check_out="2026-08-13"),
    reservation(request_no="C", status=ld.CANCELLED, check_in="2026-08-11", check_out="2026-08-13"),
    reservation(request_no="D", status=ld.APPROVED, lodging_code="DORM-1-305",
                check_in="2026-08-11", check_out="2026-08-13"),
]
check("승인 중복 판정은 확정(승인·사용완료) 상태만 본다",
      [r["request_no"] for r in ld.find_conflicts(_pool, "SATAEK-A-101",
                                                  "2026-08-12", "2026-08-16")] == ["A"])
check("다른 숙소는 중복 대상이 아니다",
      ld.find_conflicts(_pool, "DORM-1-306", "2026-08-11", "2026-08-13") == [])
check("자기 자신은 중복 대상에서 제외된다(exclude_no)",
      ld.find_conflicts(_pool, "SATAEK-A-101", "2026-08-10", "2026-08-14",
                        exclude_no="A") == [])
check("대기 신청도 상태를 지정하면 조회된다",
      [r["request_no"] for r in ld.find_conflicts(_pool, "SATAEK-A-101", "2026-08-11",
                                                  "2026-08-13",
                                                  statuses=(ld.REQUESTED,))] == ["B"])


# ===========================================================================
print("(b) 숙소 — 신청 검증")
# ===========================================================================
_ok = {"lodging_code": "SATAEK-A-101", "check_in": D(3), "check_out": D(6)}
check("정상 신청은 오류 없음", ld.validate_reservation(_ok, lodging=LODGING, today=TODAY) == [])
check("필수 3항목 누락은 각각 문구를 만든다",
      len(ld.validate_reservation({}, lodging=None, today=TODAY)) >= 3)
check("체크아웃이 체크인 이하이면 거부",
      any("뒤여야" in m for m in ld.validate_reservation(
          {**_ok, "check_out": _ok["check_in"]}, lodging=LODGING, today=TODAY)))
check("과거 날짜 신청은 거부",
      any("지난 날짜" in m for m in ld.validate_reservation(
          {**_ok, "check_in": D(-1), "check_out": D(2)}, lodging=LODGING, today=TODAY)))
check("최대 숙박일수 초과는 거부",
      any(str(ld.MAX_NIGHTS) in m for m in ld.validate_reservation(
          {**_ok, "check_out": D(3 + ld.MAX_NIGHTS + 1)}, lodging=LODGING, today=TODAY)))
check("사용 중지 숙소는 거부",
      any("사용 중지" in m for m in ld.validate_reservation(
          {**_ok, "lodging_code": "DORM-2-110"}, lodging=LODGING_OFF, today=TODAY)))
check("알 수 없는 숙소는 거부",
      any("찾을 수 없" in m for m in ld.validate_reservation(_ok, lodging=None, today=TODAY)))
check("겹치는 기간의 살아있는 예약은 신청 충돌로 잡힌다(타인 예약 포함)",
      [r["request_no"] for r in ld.occupied_conflicts(
          [reservation(request_no="X", applicant_emp_no="2024TEST02", status=ld.REQUESTED,
                       check_in=_ok["check_in"], check_out=_ok["check_out"])],
          "SATAEK-A-101", _ok["check_in"], _ok["check_out"])] == ["X"])
check("종결(반려·취소) 예약은 신청을 막지 않는다",
      ld.occupied_conflicts(
          [reservation(request_no="X", status=ld.REJECTED,
                       check_in=_ok["check_in"], check_out=_ok["check_out"]),
           reservation(request_no="Y", status=ld.CANCELLED,
                       check_in=_ok["check_in"], check_out=_ok["check_out"])],
          "SATAEK-A-101", _ok["check_in"], _ok["check_out"]) == [])
check("사번 비교는 trim·대소문자 무시", ld.emp_eq(" 2024test01 ", "2024TEST01"))
check("exclude_no 로 자기 자신은 충돌 재검사에서 빠진다",
      ld.occupied_conflicts(
          [reservation(request_no="X", status=ld.REQUESTED,
                       check_in=_ok["check_in"], check_out=_ok["check_out"])],
          "SATAEK-A-101", _ok["check_in"], _ok["check_out"], exclude_no="X") == [])
check("충돌 문구는 예약번호를 그대로 노출한다",
      "X" in ld.conflict_message([reservation(request_no="X")])
      and "이미 예약" in ld.conflict_message([reservation(request_no="X")]))
check("기간 조회는 숙박 기간과 조회 구간의 겹침으로 좁힌다",
      [r["request_no"] for r in ld.filter_reservations(
          [reservation(request_no="A", check_in="2026-08-10", check_out="2026-08-14"),
           reservation(request_no="B", check_in="2026-09-01", check_out="2026-09-03")],
          date_from="2026-08-01", date_to="2026-08-31")] == ["A"])
check("조회 종료일 당일 체크인도 기간 조회에 잡힌다(폐구간)",
      [r["request_no"] for r in ld.filter_reservations(
          [reservation(request_no="A", check_in="2026-08-31", check_out="2026-09-02")],
          date_from="2026-08-01", date_to="2026-08-31")] == ["A"])


# ===========================================================================
print("(c) 숙소 — 허용 액션·상태 전이")
# ===========================================================================
_req = reservation()
check("승인권자는 신청 건에 승인·반려·취소 가능",
      set(ld.allowed_actions(_req, APPROVER, today=TODAY))
      == {ld.ACT_APPROVE, ld.ACT_REJECT, ld.ACT_CANCEL})
check("신청자 본인은 체크인 전 취소만 가능",
      ld.allowed_actions(_req, OWNER, today=TODAY) == (ld.ACT_CANCEL,))
check("타인(비승인권자)은 아무 액션도 없다",
      ld.allowed_actions(_req, OTHER, today=TODAY) == ())
check("체크인 당일 이후 본인 취소는 불가",
      ld.allowed_actions(reservation(check_in=D(-1), check_out=D(2), status=ld.APPROVED),
                         OWNER, today=TODAY) == ())
check("승인 건은 체크아웃 전에는 사용완료 불가",
      ld.ACT_COMPLETE not in ld.allowed_actions(
          reservation(status=ld.APPROVED), APPROVER, today=TODAY))
check("체크아웃일 도달 후 사용완료 가능",
      ld.ACT_COMPLETE in ld.allowed_actions(
          reservation(status=ld.APPROVED, check_in=D(-4), check_out=D(0)),
          APPROVER, today=TODAY))
for terminal in ld.TERMINAL_STATUSES:
    check(f"종결 상태({terminal})에는 액션이 없다",
          ld.allowed_actions(reservation(status=terminal), ADMIN, today=TODAY) == ())

check("반려는 사유가 없으면 막힌다",
      ld.action_blocker(_req, ld.ACT_REJECT, APPROVER, comment="", today=TODAY) is not None)
check("반려는 사유가 있으면 통과",
      ld.action_blocker(_req, ld.ACT_REJECT, APPROVER, comment="업무 목적 아님",
                        today=TODAY) is None)
check("타인 예약 취소는 승인권자라도 사유 필수",
      ld.action_blocker(_req, ld.ACT_CANCEL, APPROVER, comment="", today=TODAY) is not None)
check("본인 취소는 사유 없이 가능",
      ld.action_blocker(_req, ld.ACT_CANCEL, OWNER, comment="", today=TODAY) is None)
check("확정 예약과 겹치면 승인이 막히고 충돌 번호가 문구에 남는다",
      "A" in (ld.action_blocker(
          reservation(request_no="Z", check_in="2026-08-12", check_out="2026-08-16"),
          ld.ACT_APPROVE, APPROVER, today=TODAY, reservations=_pool) or ""))
check("겹치지 않으면 승인 가능",
      ld.action_blocker(reservation(request_no="Z", check_in="2026-08-20",
                                    check_out="2026-08-22"),
                        ld.ACT_APPROVE, APPROVER, today=TODAY, reservations=_pool) is None)

_approved = ld.apply_action(_req, ld.ACT_APPROVE, user=APPROVER, today=TODAY, reservations=[])
check("승인 전이는 상태·처리자·처리일시를 남긴다",
      _approved["status"] == ld.APPROVED
      and _approved["decided_by"] == APPROVER["emp_no"] and _approved["decided_at"])
check("전이는 원본 dict 를 변경하지 않는다", _req["status"] == ld.REQUESTED)
_rejected = ld.apply_action(_req, ld.ACT_REJECT, user=APPROVER, comment="목적 부적합",
                            today=TODAY)
check("반려 전이는 사유를 보존한다",
      _rejected["status"] == ld.REJECTED and _rejected["decision_comment"] == "목적 부적합")
try:
    ld.apply_action(reservation(status=ld.COMPLETED), ld.ACT_APPROVE, user=ADMIN, today=TODAY)
    check("종결 건 전이는 ValueError", False)
except ValueError:
    check("종결 건 전이는 ValueError", True)
try:
    ld.apply_action(_req, "nope", user=ADMIN, today=TODAY)
    check("알 수 없는 액션은 ValueError", False)
except ValueError:
    check("알 수 없는 액션은 ValueError", True)
try:
    ld.apply_action(_req, ld.ACT_APPROVE, user=OWNER, today=TODAY, reservations=[])
    check("권한 없는 승인은 ValueError", False)
except ValueError:
    check("권한 없는 승인은 ValueError", True)

check("채번은 같은 연월 최대값 + 1",
      ld.next_request_no([{"request_no": "LDG-202608-001"}, {"request_no": "LDG-202608-007"},
                          {"request_no": "LDG-202607-099"}], today=TODAY) == "LDG-202608-008")
check("첫 채번은 001", ld.next_request_no([], today=TODAY) == "LDG-202608-001")
check("월 일자 목록 길이", len(ld.month_days(2026, 8)) == 31 and len(ld.month_days(2026, 2)) == 28)
check("가동률은 (숙소×일) 기준 백분율",
      ld.occupancy_rate([reservation(status=ld.APPROVED, check_in="2026-08-01",
                                     check_out="2026-08-03")],
                        ["SATAEK-A-101"], ld.month_days(2026, 8)) == round(2 * 100 / 31, 1))
check("분모가 0이면 가동률 0.0", ld.occupancy_rate([], [], []) == 0.0)


# ===========================================================================
print("(d) 업무요청 — 검증")
# ===========================================================================
_wok = {"title": "PC 교체", "request_type": "전산", "priority": "보통", "target_dept": "MGT",
        "desired_due": D(5), "content": "부팅 지연이 심해 교체를 요청합니다."}
check("정상 요청은 오류 없음", wr.validate_request(_wok, today=TODAY) == [])
check("필수 6항목 누락은 각각 문구를 만든다", len(wr.validate_request({}, today=TODAY)) >= 6)
check("과거 희망 완료일은 거부",
      any("오늘 이후" in m for m in wr.validate_request({**_wok, "desired_due": D(-1)},
                                                        today=TODAY)))
check("짧은 요청 내용은 거부",
      any(str(wr.CONTENT_MIN) in m for m in wr.validate_request({**_wok, "content": "짧음"},
                                                                today=TODAY)))
check("제목 길이 상한 초과는 거부",
      any(str(wr.TITLE_MAX) in m for m in wr.validate_request(
          {**_wok, "title": "가" * (wr.TITLE_MAX + 1)}, today=TODAY)))
check("정의되지 않은 유형·우선순위는 거부",
      len(wr.validate_request({**_wok, "request_type": "없음", "priority": "최상"},
                              today=TODAY)) == 2)
check("기한 초과 판정은 미처리 건에만 적용",
      wr.is_overdue(request(desired_due=D(-1)), today=TODAY)
      and not wr.is_overdue(request(desired_due=D(-1), status=wr.CLOSED), today=TODAY))


# ===========================================================================
print("(e) 업무요청 — 허용 액션·상태 전이")
# ===========================================================================
_sub = request()
check("처리자는 제출됨 건에 착수·반려 가능",
      set(wr.allowed_actions(_sub, APPROVER)) == {wr.ACT_START, wr.ACT_REJECT})
check("요청자는 제출됨 건에 처리 액션이 없다", wr.allowed_actions(_sub, OWNER) == ())
check("처리중 건은 완료·반려 가능",
      set(wr.allowed_actions(request(status=wr.IN_PROGRESS), APPROVER))
      == {wr.ACT_COMPLETE, wr.ACT_REJECT})
check("처리완료 건은 요청자만 종결·보완 가능",
      set(wr.allowed_actions(request(status=wr.DONE), OWNER))
      == {wr.ACT_CLOSE, wr.ACT_REOPEN})
check("처리완료 건이라도 타인은 종결할 수 없다",
      wr.allowed_actions(request(status=wr.DONE), OTHER) == ())
check("ADMIN 은 요청자 대행으로 종결 가능",
      wr.ACT_CLOSE in wr.allowed_actions(request(status=wr.DONE), ADMIN))
for terminal in wr.TERMINAL_STATUSES:
    check(f"종결 상태({terminal})에는 액션이 없다",
          wr.allowed_actions(request(status=terminal), ADMIN) == ())

check("착수는 담당자 지정이 없으면 막힌다",
      wr.action_blocker(_sub, wr.ACT_START, APPROVER, assignee=None) is not None)
check("담당자를 지정하면 착수 가능",
      wr.action_blocker(_sub, wr.ACT_START, APPROVER, assignee=APPROVER) is None)
check("완료는 처리 결과가 없으면 막힌다",
      wr.action_blocker(request(status=wr.IN_PROGRESS), wr.ACT_COMPLETE, APPROVER,
                        comment="") is not None)

_started = wr.apply_action(_sub, wr.ACT_START, user=APPROVER, assignee=APPROVER)
check("착수 전이는 담당자를 기록한다",
      _started["status"] == wr.IN_PROGRESS
      and _started["assignee_emp_no"] == APPROVER["emp_no"]
      and _started["assignee_name"] == APPROVER["name"])
check("전이는 원본 dict 를 변경하지 않는다", _sub["status"] == wr.SUBMITTED)
_done = wr.apply_action(_started, wr.ACT_COMPLETE, user=APPROVER, comment="교체 완료")
check("완료 전이는 처리 결과를 보존한다",
      _done["status"] == wr.DONE and _done["result_note"] == "교체 완료")
_closed = wr.apply_action(_done, wr.ACT_CLOSE, user=OWNER)
check("요청자 종결 전이", _closed["status"] == wr.CLOSED)
_reopened = wr.apply_action(_done, wr.ACT_REOPEN, user=OWNER, comment="일부 미완")
check("보완 요청은 처리중으로 되돌리고 직전 처리 결과를 무효화한다",
      _reopened["status"] == wr.IN_PROGRESS and _reopened["reject_reason"] == "일부 미완"
      and _reopened["result_note"] == "")
try:
    wr.apply_action(request(status=wr.CLOSED), wr.ACT_REOPEN, user=OWNER, comment="x")
    check("종결 건 전이는 ValueError", False)
except ValueError:
    check("종결 건 전이는 ValueError", True)
check("업무요청 채번",
      wr.next_request_no([{"request_no": "WR-202608-012"}], today=TODAY) == "WR-202608-013")
_summary = wr.summarize([request(), request(status=wr.IN_PROGRESS, desired_due=D(-2)),
                         request(status=wr.CLOSED)], today=TODAY)
check("집계는 총계·대기·기한초과를 함께 낸다",
      _summary["TOTAL"] == 3 and _summary["PENDING"] == 2 and _summary["OVERDUE"] == 1)


# ===========================================================================
print("(f) 로컬 저장소 — 시드·왕복·초기화(임시 디렉터리 격리)")
# ===========================================================================
check("테스트 상태 디렉터리가 격리됐다", str(proto_store.state_dir()) == _TMP.name)
_seed = proto_store.seed_rows(ld.RESERVATIONS)
check("시드 CSV 를 읽는다", len(_seed) > 0 and "request_no" in _seed[0])
_loaded = proto_store.load_rows(ld.RESERVATIONS)
check("상태 파일이 없으면 시드로 최초 생성", len(_loaded) == len(_seed)
      and proto_store.state_path(ld.RESERVATIONS).exists())
proto_store.save_rows(ld.RESERVATIONS, _loaded[:1])
check("저장 후 다시 읽으면 저장한 내용", len(proto_store.load_rows(ld.RESERVATIONS)) == 1)
proto_store.reset(ld.RESERVATIONS)
check("초기화하면 시드로 복원", len(proto_store.load_rows(ld.RESERVATIONS)) == len(_seed))
proto_store.state_path(ld.RESERVATIONS).write_text("{ broken", encoding="utf-8")
try:
    proto_store.load_rows(ld.RESERVATIONS)
    check("손상된 상태 파일은 조용히 시드로 덮지 않고 오류를 낸다", False)
except ValueError:
    check("손상된 상태 파일은 조용히 시드로 덮지 않고 오류를 낸다", True)
proto_store.reset_all([ld.LODGINGS, ld.RESERVATIONS, wr.REQUESTS])

check("시드 인물은 전부 가상 사번(2024TEST*)",
      all(str(r.get("applicant_emp_no", "")).startswith("2024TEST")
          for r in proto_store.seed_rows(ld.RESERVATIONS))
      and all(str(r.get("requester_emp_no", "")).startswith("2024TEST")
              for r in proto_store.seed_rows(wr.REQUESTS)))


# ===========================================================================
print("(g) 엔드투엔드 — 신청/처리가 파일에 영속된다")
# ===========================================================================
_before = len(ld.load_reservations())
_created = ld.create_reservation(
    {"lodging_code": "TAEAN", "check_in": D(40), "check_out": D(42)},
    current_user=OWNER,
)
check("신청이 저장되고 신원은 세션 사용자로 확정된다",
      len(ld.load_reservations()) == _before + 1
      and _created["applicant_emp_no"] == OWNER["emp_no"]
      and _created["status"] == ld.REQUESTED)
try:
    ld.create_reservation(
        {"lodging_code": "TAEAN", "check_in": D(41), "check_out": D(43)},
        current_user=OWNER)
    check("겹치는 기간 신청은 접수 자체가 거부된다(ReservationConflict)", False)
except ld.ReservationConflict as exc:
    check("겹치는 기간 신청은 접수 자체가 거부된다(ReservationConflict)",
          _created["request_no"] in str(exc) and "이미 예약" in str(exc))
_edited = ld.update_reservation(
    _created["request_no"], {"check_in": D(40), "check_out": D(43)}, current_user=OWNER)
check("신청 상태 본인 수정이 파일에 반영된다(자기 자신은 중복 제외)",
      _edited["check_out"] == D(43)
      and (ld.get_reservation(_created["request_no"]) or {}).get("check_out") == D(43))
try:
    ld.update_reservation(_created["request_no"], {"check_in": D(40), "check_out": D(41)},
                          current_user=OTHER)
    check("승인권자가 아닌 타인의 수정은 거부", False)
except ValueError:
    check("승인권자가 아닌 타인의 수정은 거부", True)
_appr_edit = ld.update_reservation(
    _created["request_no"], {"check_in": D(40), "check_out": D(44)}, current_user=APPROVER)
check("승인권자는 신청 건 일정을 정정할 수 있다", _appr_edit["check_out"] == D(44))
_after = ld.run_action(_created["request_no"], ld.ACT_APPROVE, current_user=APPROVER)
check("승인이 파일에 반영된다",
      _after["status"] == ld.APPROVED
      and (ld.get_reservation(_created["request_no"]) or {}).get("status") == ld.APPROVED)
try:
    ld.run_action(_created["request_no"], ld.ACT_APPROVE, current_user=APPROVER)
    check("이미 승인된 건 재승인은 거부", False)
except ValueError:
    check("이미 승인된 건 재승인은 거부", True)
try:
    ld.update_reservation(_created["request_no"], {"check_in": D(40), "check_out": D(41)},
                          current_user=OWNER)
    check("승인된 건 수정은 거부", False)
except ValueError:
    check("승인된 건 수정은 거부", True)

_wbefore = len(wr.load_requests())
_wcreated = wr.create_request(
    {"title": "테스트 요청", "request_type": "기타", "priority": "낮음", "target_dept": "MGT",
     "desired_due": D(10), "content": "프로토타입 계약 테스트용 요청입니다."},
    current_user=OWNER,
)
check("업무요청이 저장된다",
      len(wr.load_requests()) == _wbefore + 1 and _wcreated["status"] == wr.SUBMITTED)
wr.run_action(_wcreated["request_no"], wr.ACT_START, current_user=APPROVER, assignee=APPROVER)
wr.run_action(_wcreated["request_no"], wr.ACT_COMPLETE, current_user=APPROVER, comment="완료함")
_final = wr.get_request(_wcreated["request_no"]) or {}
check("착수→완료가 파일에 반영된다",
      _final.get("status") == wr.DONE and _final.get("result_note") == "완료함"
      and _final.get("assignee_emp_no") == APPROVER["emp_no"])
try:
    wr.update_request(_wcreated["request_no"], {"title": "수정 시도"}, current_user=OWNER)
    check("처리완료 건 본문 수정은 거부", False)
except ValueError:
    check("처리완료 건 본문 수정은 거부", True)
try:
    wr.update_request(_wcreated["request_no"], {"title": "타인 수정"}, current_user=OTHER)
    check("타인 요청 수정은 거부", False)
except ValueError:
    check("타인 요청 수정은 거부", True)
wr.run_action(_wcreated["request_no"], wr.ACT_CLOSE, current_user=OWNER)
check("요청자 종결이 파일에 반영된다",
      (wr.get_request(_wcreated["request_no"]) or {}).get("status") == wr.CLOSED)


print()
_TMP.cleanup()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
