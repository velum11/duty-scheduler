"""접수 알림 메일 발송 모듈 (SMTP).

계약
----
- 설정은 ``st.secrets`` 의 ``[smtp]``(host·port·user·app_password)와 ``[notify]``
  (``to`` = 수신자 목록)에서 읽는다. 두 섹션이 모두 채워져 있을 때만 발송한다.
- 발송 실패·미설정이 **본 작업(접수 저장)을 절대 막지 않는다.** 공개 함수는 예외를
  밖으로 던지지 않고 ``True``(발송)/``False``(실패)/``None``(미설정·비활성)을
  반환하며, 호출 화면이 결과를 안내 문구로 표면화한다.
- 환경변수 ``DUTY_MAIL_DISABLE`` 이 설정되면 무조건 발송하지 않는다(테스트 격리용 —
  ``DUTY_PROTO_STATE_DIR`` 과 같은 목적의 훅).
- 발송 계정은 한시로 지메일(587 STARTTLS)이며, 운영 전환 시 비즈메카 SMTP
  (``ezesmtp.bizmeka.com:587`` STARTTLS + AUTH LOGIN 실검증 완료)로 secrets 만
  교체한다 — `docs/BACKLOG.md` 이메일 알림 트랙. 465 포트는 SSL 직결로 처리한다.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

import streamlit as st

from modules.config import APP_NAME

#: 발송 전면 차단 환경변수(테스트 격리용).
DISABLE_ENV = "DUTY_MAIL_DISABLE"

_TIMEOUT_SEC = 15

_FOOTER = f"※ 본 메일은 {APP_NAME} 자동 발송 알림입니다. 회신하지 마세요."
_RULE = "─" * 28


def _secret_section(name: str) -> dict:
    try:
        section = st.secrets.get(name, {})
        return dict(section) if section else {}
    except Exception:
        return {}


def _recipients() -> list[str]:
    to = _secret_section("notify").get("to")
    if isinstance(to, str):
        to = [to]
    return [str(t).strip() for t in (to or []) if str(t).strip()]


def _smtp_config() -> dict | None:
    """발송 가능한 완전한 설정 또는 ``None``. 비밀값은 반환 dict 밖으로 꺼내지 않는다."""
    if os.getenv(DISABLE_ENV):
        return None
    smtp = _secret_section("smtp")
    cfg = {
        "host": str(smtp.get("host", "")).strip(),
        "port": str(smtp.get("port", "")).strip(),
        "user": str(smtp.get("user", "")).strip(),
        # 지메일 앱 비밀번호는 표시용 공백이 섞여 들어올 수 있어 제거한다.
        "password": str(smtp.get("app_password", "")).replace(" ", ""),
        "to": _recipients(),
    }
    if not all(cfg.values()):
        return None
    try:
        cfg["port"] = int(cfg["port"])
    except ValueError:
        return None
    return cfg


def is_enabled() -> bool:
    """현재 환경에서 알림 메일이 발송될 조건인지(설정 완비 + 비활성 아님)."""
    return _smtp_config() is not None


def send(subject: str, body: str) -> bool | None:
    """설정된 수신자에게 발송한다. True 발송/False 실패/None 미설정·비활성."""
    cfg = _smtp_config()
    if cfg is None:
        return None
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"{APP_NAME} 알림 <{cfg['user']}>"
        msg["To"] = ", ".join(cfg["to"])
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()
        msg.set_content(body)
        if cfg["port"] == 465:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=_TIMEOUT_SEC) as conn:
                conn.login(cfg["user"], cfg["password"])
                conn.send_message(msg)
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=_TIMEOUT_SEC) as conn:
                conn.starttls()
                conn.login(cfg["user"], cfg["password"])
                conn.send_message(msg)
        return True
    except Exception:
        return False


# ── 접수 알림 서식 ──────────────────────────────────────────────


def work_request_created_mail(record: dict, *, target_dept_label: str = "",
                              requester_dept_label: str = "") -> tuple[str, str]:
    """업무요청 접수 알림 (제목, 본문). 순수 함수 — 발송하지 않는다."""
    no = str(record.get("request_no", "")).strip()
    subject = f"[{APP_NAME}] 업무요청 접수 · {no} — {record.get('title', '')}"
    body = f"""업무요청이 접수되었습니다.

{_RULE}
  접수번호    : {no}
  요청 제목   : {record.get('title', '')}
  유형/우선순위: {record.get('request_type', '')} / {record.get('priority', '')}
  신청자      : {record.get('requester_name', '')} ({requester_dept_label or record.get('requester_dept', '')})
  처리 부서   : {target_dept_label or record.get('target_dept', '')}
  희망 완료일 : {record.get('desired_due', '')}
  접수일시    : {record.get('created_at', '')}
{_RULE}

요청 내용:
{record.get('content', '')}

{APP_NAME}에 로그인하여 [업무요청 처리] 화면에서 처리해 주세요.

{_FOOTER}
"""
    return subject, body


def lodging_requested_mail(record: dict, *, lodging_label: str = "",
                           period_label: str = "") -> tuple[str, str]:
    """숙소 예약 신청 접수 알림 (제목, 본문). 순수 함수 — 발송하지 않는다."""
    no = str(record.get("request_no", "")).strip()
    subject = f"[{APP_NAME}] 숙소 예약 신청 · {no} — {lodging_label or record.get('lodging_code', '')}"
    body = f"""숙소 예약 신청이 접수되었습니다.

{_RULE}
  신청번호 : {no}
  숙소     : {lodging_label or record.get('lodging_code', '')}
  기간     : {period_label or f"{record.get('check_in', '')} ~ {record.get('check_out', '')}"}
  신청자   : {record.get('applicant_name', '')} ({record.get('dept_code', '')})
  접수일시 : {record.get('created_at', '')}
{_RULE}

{APP_NAME}에 로그인하여 [숙소 예약 승인] 화면에서 승인/반려 처리해 주세요.

{_FOOTER}
"""
    return subject, body


def notify_work_request_created(record: dict, *, target_dept_label: str = "",
                                requester_dept_label: str = "") -> bool | None:
    subject, body = work_request_created_mail(
        record, target_dept_label=target_dept_label,
        requester_dept_label=requester_dept_label)
    return send(subject, body)


def notify_lodging_requested(record: dict, *, lodging_label: str = "",
                             period_label: str = "") -> bool | None:
    subject, body = lodging_requested_mail(
        record, lodging_label=lodging_label, period_label=period_label)
    return send(subject, body)
