"""WORKLIST(DESIGN.md §2) 공용 파생값 — 목록 행이 담는 "처리 우선순위 근거".

§2 는 목록 행에 "무엇을 먼저 처리할지 고를 근거(경과일·소속·분류)"를 요구한다. 이 모듈은
그중 **경과일**을 소유한다 — 소속·분류는 레코드 필드를 그대로 쓰므로 파생이 필요 없다.

경과일 계약(DESIGN.md §7.2-4 확정, 2026-08-18 사용자 결정)
--------------------------------------------------------
- **접수일(``created_at``) 기준**이다. ``incident_date`` 가 아니다 — 평가자의 책임 구간은
  접수 이후다. ``006_near_miss.sql:69`` 주석의 "기간 통계는 ``incident_date`` 기준"은
  **집계 축**에 대한 규칙이고, 경과일은 처리 지연 측정이라 별개다(§7.2-4 가 이 구분을
  명시적으로 남겼다 — 나중에 "일관성"을 이유로 바꾸지 않는다).
- **반송(보완요청) 건도 최초 접수부터 누적한다**(§7.2-4-c). 이 모듈이 읽는 ``created_at``
  은 반송·재제출로 바뀌지 않으므로 누적이 구조적으로 보장된다 — 리셋 경로를 만들지
  않는 것이 곧 "반송을 반복해 지연 지표를 0으로 되돌리는 경로"를 만들지 않는 것이다.
- **경과일에 색을 칠하지 않는다**(§7.2-4-b). SLA 가 없으므로 임계가 없고, 목록이 경과일
  내림차순이라 순서가 이미 우선순위를 말한다. 색은 같은 말을 두 번 한다.

날짜 경계
--------
``created_at`` 은 ``timestamptz``(UTC)로 저장되고 사용자는 한국 시간으로 일한다. UTC 로
날을 세면 09:00 이전 접수 건이 하루 적게 나온다. 그래서 **UTC 시각을 KST 로 변환한 뒤
날짜만 취해** 오늘(KST)과 뺀다. 시간대가 없는 문자열은 UTC 로 해석한다(DB 저장 규약).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

#: 한국 표준시. 이 저장소는 한 사업장 전용이라 tz 를 데이터로 두지 않는다.
KST = timezone(timedelta(hours=9))

#: 경과일을 알 수 없을 때의 표기(값 없음 ≠ 0일). 목록 행 폭이 고정이라 짧게 쓴다.
UNKNOWN_LABEL = "-"


def _to_datetime(value) -> datetime | None:
    """``created_at`` 원본을 tz-aware ``datetime`` 으로 정규화한다(실패는 ``None``).

    허용 입력: ``datetime`` / ``pandas.Timestamp``(``datetime`` 하위형) / ISO 문자열
    (``...Z`` 접미도 허용) / ``date``. tz 정보가 없으면 UTC 로 본다(DB 저장 규약).
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        # date 는 이미 날짜 경계가 확정된 값이라 KST 자정으로 올린다(재변환 금지).
        return datetime(value.year, value.month, value.day, tzinfo=KST)
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def elapsed_days(created_at, *, today: date | None = None) -> int | None:
    """접수일(``created_at``)부터 오늘까지의 경과일. 판정 불가면 ``None``.

    ``today`` 를 주지 않으면 **KST 기준 오늘**을 쓴다(테스트는 고정 날짜를 넘긴다).
    시계 오차·미래 타임스탬프로 음수가 나오면 0 으로 클램프한다 — "-1일"은 사용자에게
    아무 의미가 없고 정렬만 망가뜨린다.
    """
    dt = _to_datetime(created_at)
    if dt is None:
        return None
    received = dt.astimezone(KST).date()
    ref = today or datetime.now(KST).date()
    return max((ref - received).days, 0)


def elapsed_label(created_at, *, today: date | None = None) -> str:
    """목록 행 우측에 찍는 경과일 표기. 색을 쓰지 않는다(§7.2-4-b).

    ``None``(판정 불가) → ``"-"`` · 0 → ``"오늘"`` · n → ``"n일"``. 단위를 붙이는 것은
    §3.5(숫자에 단위) 요구다.
    """
    days = elapsed_days(created_at, today=today)
    if days is None:
        return UNKNOWN_LABEL
    return "오늘" if days == 0 else f"{days}일"


def order_by_elapsed(rows: list[tuple]) -> list[str]:
    """``[(key, created_at, tiebreak)]`` 을 **경과일 내림차순**(오래 묵은 건 먼저)으로 정렬해
    키 목록을 돌려준다.

    경과일을 알 수 없는 건은 맨 뒤로 보낸다(0일로 위장하면 방금 접수된 건과 섞인다).
    같은 경과일 안에서는 ``tiebreak``(발생일 등) 내림차순이다 — 두 번 정렬해 안정성을
    이용하므로 비교 키에 문자열 역순 트릭을 넣지 않는다.
    """
    ranked = [(str(key), elapsed_days(created_at), str(tiebreak or ""))
              for key, created_at, tiebreak in rows]
    ranked.sort(key=lambda t: t[2], reverse=True)
    ranked.sort(key=lambda t: (t[1] is None, -(t[1] if t[1] is not None else 0)))
    return [key for key, _, _ in ranked]


__all__ = ["KST", "UNKNOWN_LABEL", "elapsed_days", "elapsed_label", "order_by_elapsed"]
