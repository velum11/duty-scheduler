"""접수 알림 메일 모듈 계약 테스트 — modules/mailer.py.

검증 대상은 **순수 서식 함수**(제목·본문 필드 포함)와 발송 게이트 계약(비활성 환경변수·
설정 결여 시 ``None``, 예외 비전파)이다. 네트워크 발송은 하지 않는다 —
``DUTY_MAIL_DISABLE`` 로 발송 경로를 차단하고 게이트만 검사한다.

실행: .venv/Scripts/python.exe scripts/test_mailer.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# import 전에 발송을 전면 차단한다 — 로컬 secrets.toml 에 실제 계정이 있어도
# 이 테스트가 진짜 메일을 보내는 일은 없어야 한다.
os.environ["DUTY_MAIL_DISABLE"] = "1"

from modules import mailer  # noqa: E402

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"FAIL - {name}")


WR = {
    "request_no": "WR-2026-0007",
    "title": "회의실 프로젝터 수리",
    "request_type": "시설",
    "priority": "높음",
    "requester_name": "김샘플",
    "requester_dept": "PET1",
    "target_dept": "MGT",
    "desired_due": "2026-08-14",
    "content": "전원이 켜지지 않습니다. 점검 부탁드립니다.",
    "created_at": "2026-08-07 15:00",
}
LODGE = {
    "request_no": "LR-2026-0003",
    "lodging_code": "SATAEK-A-101",
    "applicant_name": "이가상",
    "dept_code": "PET2",
    "check_in": "2026-08-20",
    "check_out": "2026-08-22",
    "created_at": "2026-08-07 15:00",
}

print("[1] 업무요청 접수 서식")
subject, body = mailer.work_request_created_mail(
    WR, target_dept_label="경영지원팀", requester_dept_label="1공장")
check("제목에 접수번호·요청 제목", "WR-2026-0007" in subject and "프로젝터" in subject)
for field in ("WR-2026-0007", "회의실 프로젝터 수리", "시설", "높음", "김샘플",
              "1공장", "경영지원팀", "2026-08-14", "전원이 켜지지 않습니다"):
    check(f"본문 필드: {field}", field in body)
check("라벨 미제공 시 코드 fallback",
      "MGT" in mailer.work_request_created_mail(WR)[1])
check("자동 발송 문구", "자동 발송" in body and "회신하지" in body)

print("[2] 숙소 예약 접수 서식")
subject, body = mailer.lodging_requested_mail(
    LODGE, lodging_label="한빛사택 A동 101호", period_label="08-20(목) ~ 08-22(토) 2박")
check("제목에 신청번호·숙소", "LR-2026-0003" in subject and "한빛사택" in subject)
for field in ("LR-2026-0003", "한빛사택 A동 101호", "08-20(목)", "이가상", "PET2"):
    check(f"본문 필드: {field}", field in body)
check("라벨 미제공 시 코드·기간 fallback",
      all(t in mailer.lodging_requested_mail(LODGE)[1]
          for t in ("SATAEK-A-101", "2026-08-20 ~ 2026-08-22")))

print("[3] 발송 게이트")
check("DUTY_MAIL_DISABLE 설정 시 send=None(발송 안 함)",
      mailer.send("제목", "본문") is None)
check("DUTY_MAIL_DISABLE 설정 시 is_enabled=False", mailer.is_enabled() is False)
check("notify_* 도 None", mailer.notify_work_request_created(WR) is None
      and mailer.notify_lodging_requested(LODGE) is None)

# 차단 해제 + 설정 결여(빈 secrets 가정은 불가 — 로컬에 실제 secrets 가 있을 수 있다).
# 대신 게이트 함수 단위로: port 가 숫자가 아니면 None 을 확인한다.
os.environ.pop("DUTY_MAIL_DISABLE", None)
_orig = mailer._secret_section
try:
    mailer._secret_section = lambda name: (
        {"host": "h", "port": "abc", "user": "u", "app_password": "p"}
        if name == "smtp" else {"to": ["a@b.c"]})
    check("port 비정상 시 send=None", mailer.send("제목", "본문") is None)
    mailer._secret_section = lambda name: {}
    check("설정 전무 시 send=None", mailer.send("제목", "본문") is None)
    mailer._secret_section = lambda name: (
        {"host": "h", "port": "587", "user": "u", "app_password": "p"}
        if name == "smtp" else {})
    check("수신자 없으면 send=None", mailer.send("제목", "본문") is None)
    mailer._secret_section = lambda name: (
        {"host": "127.0.0.1", "port": "9", "user": "u", "app_password": "p"}
        if name == "smtp" else {"to": ["a@b.c"]})
    check("접속 실패는 예외 없이 False", mailer.send("제목", "본문") is False)
finally:
    mailer._secret_section = _orig
    os.environ["DUTY_MAIL_DISABLE"] = "1"

print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL} (passed {PASS})")
    sys.exit(1)
print(f"ALL PASS ({PASS})")
