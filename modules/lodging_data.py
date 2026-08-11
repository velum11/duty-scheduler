"""숙소 예약 도메인(프로토타입) — 상태 전이·검증·중복 판정 + 로컬 파일 영속.

라우팅·Supabase 연결 전 단계의 **로컬 sample 전용** 모듈이다. 저장은
``modules/proto_store`` (시드 ``data/sample/lodgings.csv`` ·
``data/sample/lodging_reservations.csv`` → 런타임 JSON)로만 하고, ``modules/db.py``
파사드나 원격 저장소를 호출하지 않는다.

설계 원칙(기존 계약 계승)
-------------------------
- **순수 함수 우선**: 검증(:func:`validate_reservation`) · 중복 판정(:func:`overlaps`
  · :func:`find_conflicts`) · 허용 액션(:func:`allowed_actions`) · 전이
  (:func:`apply_action`) 는 IO 없이 dict/값만 다룬다 — 계약 테스트가 이 함수들을 직접
  고정한다(``scripts/test_new_screens.py``).
- **신원은 서버측 확정**: 신청자·처리자 사번은 화면 위젯이 아니라 세션 사용자
  (``current_user``)에서 채운다. 사번 비교는 trim + 대소문자 무시이며 원본 사번을
  변환해 저장하지 않는다.
- **점유 구간은 반개구간** ``[check_in, check_out)`` — 체크아웃 당일은 점유하지 않으므로
  같은 날 다음 사용자가 체크인할 수 있다.
- **중복 차단은 신청 시점부터**(2026-08-07 사용자 결정): 같은 숙소·겹치는 기간에 살아있는
  예약(신청·승인·사용완료)이 있으면 신규 신청·수정 자체를 :class:`ReservationConflict`
  로 거부한다 — 화면은 이를 팝업으로 알린다. 승인 시점의 확정(승인·사용완료) 겹침 검사는
  경합 백스톱으로 유지한다(충돌 예약번호를 문구에 그대로 노출 — 원인을 감추지 않는다).
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from modules import proto_store

LODGINGS = "lodgings"
RESERVATIONS = "lodging_reservations"

# ── 상태(라이프사이클) ───────────────────────────────────────────────────────
REQUESTED = "REQUESTED"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
CANCELLED = "CANCELLED"
COMPLETED = "COMPLETED"

STATUSES: tuple[str, ...] = (REQUESTED, APPROVED, REJECTED, CANCELLED, COMPLETED)
STATUS_LABELS = {
    REQUESTED: "신청",
    APPROVED: "승인",
    REJECTED: "반려",
    CANCELLED: "취소",
    COMPLETED: "사용완료",
}
#: 종결 상태 — 이후 어떤 전이도 없다.
TERMINAL_STATUSES: tuple[str, ...] = (REJECTED, CANCELLED, COMPLETED)
#: 캘린더/현황에서 숙소를 점유한 것으로 보는 상태(반려·취소 제외).
OCCUPYING_STATUSES: tuple[str, ...] = (REQUESTED, APPROVED, COMPLETED)
#: 승인 시 중복을 차단하는 기준 상태 — 이미 확정된 점유만 막는다.
BLOCKING_STATUSES: tuple[str, ...] = (APPROVED, COMPLETED)

# ── 액션 ────────────────────────────────────────────────────────────────────
ACT_APPROVE = "approve"
ACT_REJECT = "reject"
ACT_CANCEL = "cancel"
ACT_COMPLETE = "complete"
ACTIONS: tuple[str, ...] = (ACT_APPROVE, ACT_REJECT, ACT_CANCEL, ACT_COMPLETE)
ACTION_LABELS = {
    ACT_APPROVE: "승인",
    ACT_REJECT: "반려",
    ACT_CANCEL: "취소",
    ACT_COMPLETE: "사용완료",
}
#: 의견(사유) 입력이 필수인 액션.
COMMENT_REQUIRED = (ACT_REJECT,)

APPROVER_ROLES = ("ADMIN", "MANAGER")
MAX_NIGHTS = 30


class ReservationConflict(ValueError):
    """같은 숙소·겹치는 기간에 이미 살아있는 예약이 있어 신청/수정이 거부됨."""

RESERVATION_COLUMNS = [
    "request_no", "lodging_code", "applicant_emp_no", "applicant_name", "dept_code",
    "check_in", "check_out", "status",
    "decided_by", "decided_at", "decision_comment", "created_at",
]
LODGING_COLUMNS = [
    "lodging_code", "lodging_name", "room_no", "lodging_type", "capacity",
    "location", "is_active",
]


# ===========================================================================
# 값 헬퍼(순수)
# ===========================================================================
def clean(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def emp_eq(left, right) -> bool:
    """사번 비교 — trim + 대소문자 무시(원본 사번은 변환하지 않는다)."""
    a, b = clean(left), clean(right)
    return bool(a) and bool(b) and a.casefold() == b.casefold()


def to_date(value) -> date | None:
    """``date`` / ``YYYY-MM-DD`` 문자열을 ``date`` 로. 해석 불가면 ``None``."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = clean(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def to_int(value, default: int = 0) -> int:
    text = clean(value)
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def to_bool(value) -> bool:
    return clean(value).lower() in {"true", "1", "y", "yes", "t"}


def nights(check_in, check_out) -> int:
    """숙박일수. 값이 불완전하거나 역순이면 0."""
    ci, co = to_date(check_in), to_date(check_out)
    if ci is None or co is None or co <= ci:
        return 0
    return (co - ci).days


def lodging_label(lodging: dict | None) -> str:
    if not lodging:
        return "-"
    name = clean(lodging.get("lodging_name"))
    room = clean(lodging.get("room_no"))
    return " ".join(p for p in (name, room) if p) or clean(lodging.get("lodging_code")) or "-"


def period_label(reservation: dict) -> str:
    ci = clean(reservation.get("check_in")) or "-"
    co = clean(reservation.get("check_out")) or "-"
    n = nights(reservation.get("check_in"), reservation.get("check_out"))
    return f"{ci} ~ {co} ({n}박)" if n else f"{ci} ~ {co}"


# ===========================================================================
# 중복(점유) 판정 — 순수
# ===========================================================================
def overlaps(a_in, a_out, b_in, b_out) -> bool:
    """반개구간 ``[in, out)`` 두 구간이 겹치는지. 체크아웃 당일 교대는 겹침이 아니다."""
    ai, ao, bi, bo = to_date(a_in), to_date(a_out), to_date(b_in), to_date(b_out)
    if None in (ai, ao, bi, bo):
        return False
    if ao <= ai or bo <= bi:
        return False
    return ai < bo and bi < ao


def find_conflicts(reservations, lodging_code, check_in, check_out, *,
                   exclude_no: str | None = None,
                   statuses: tuple[str, ...] = BLOCKING_STATUSES) -> list[dict]:
    """``statuses`` 상태의 같은 숙소 예약 중 기간이 겹치는 것들(순수 필터)."""
    code = clean(lodging_code)
    out: list[dict] = []
    for row in reservations or []:
        if clean(row.get("lodging_code")) != code:
            continue
        if clean(row.get("status")) not in statuses:
            continue
        if exclude_no and clean(row.get("request_no")) == clean(exclude_no):
            continue
        if overlaps(check_in, check_out, row.get("check_in"), row.get("check_out")):
            out.append(row)
    return out


# ===========================================================================
# 검증 — 순수
# ===========================================================================
def validate_reservation(payload: dict, *, lodging: dict | None = None,
                         today: date | None = None) -> list[str]:
    """신청 payload 를 검증하고 **사용자에게 보여줄 문구 목록**을 반환한다(빈 목록=통과).

    필수 3항목(숙소·체크인·체크아웃) + 기간/활성 규칙을 본다. 중복 신청(본인 미종결
    예약과 겹침)은 예약 목록이 필요하므로 :func:`duplicate_own_request` 로 분리했다.
    """
    today = today or date.today()
    errors: list[str] = []

    code = clean(payload.get("lodging_code"))
    if not code:
        errors.append("숙소를 선택하세요.")
    elif lodging is None:
        errors.append("선택한 숙소를 찾을 수 없습니다.")
    elif not to_bool(lodging.get("is_active")):
        errors.append("사용 중지된 숙소는 신청할 수 없습니다.")

    ci = to_date(payload.get("check_in"))
    co = to_date(payload.get("check_out"))
    if ci is None:
        errors.append("체크인 날짜를 입력하세요.")
    if co is None:
        errors.append("체크아웃 날짜를 입력하세요.")
    if ci is not None and co is not None:
        if co <= ci:
            errors.append("체크아웃 날짜는 체크인 날짜보다 뒤여야 합니다.")
        elif (co - ci).days > MAX_NIGHTS:
            errors.append(f"연속 숙박은 최대 {MAX_NIGHTS}박까지 신청할 수 있습니다.")
    if ci is not None and ci < today:
        errors.append("지난 날짜로는 신청할 수 없습니다.")
    return errors


def occupied_conflicts(reservations, lodging_code, check_in, check_out, *,
                       exclude_no: str | None = None) -> list[dict]:
    """신청 시점 점유 충돌 — 같은 숙소에서 살아있는 예약(신청·승인·사용완료)과의 겹침.

    누구의 예약이든 겹치면 신규 신청·수정을 막는다(2026-08-07 결정).
    ``exclude_no`` 는 수정 재검사에서 자기 자신을 빼기 위한 훅이다."""
    return find_conflicts(reservations, lodging_code, check_in, check_out,
                          exclude_no=exclude_no, statuses=OCCUPYING_STATUSES)


def conflict_message(hits: list[dict]) -> str:
    """신청 충돌 안내 문구 — 충돌 예약번호·기간을 그대로 노출한다(원인을 감추지 않는다)."""
    spans = " / ".join(
        f"{clean(h.get('request_no'))} {period_label(h)}" for h in hits[:3]
    )
    more = f" 외 {len(hits) - 3}건" if len(hits) > 3 else ""
    return f"해당 일자는 이미 예약되어 있습니다({spans}{more}). 다른 일정을 선택해 주세요."


# ===========================================================================
# 권한·허용 액션 — 순수
# ===========================================================================
def can_approve(user: dict | None) -> bool:
    """승인권자 여부(프로토타입 가정: ADMIN·MANAGER). 확정 시 총무 담당 지정으로 대체 가능."""
    return clean((user or {}).get("role")).upper() in APPROVER_ROLES


def is_owner(reservation: dict, user: dict | None) -> bool:
    return emp_eq(reservation.get("applicant_emp_no"), (user or {}).get("emp_no"))


def allowed_actions(reservation: dict, user: dict | None, *,
                    today: date | None = None) -> tuple[str, ...]:
    """이 사용자가 이 예약에 대해 지금 수행할 수 있는 액션(순서 고정).

    종결 상태(반려·취소·사용완료)에는 어떤 액션도 없다. 신청자 본인은 체크인 전까지만
    취소할 수 있고, 승인권자는 승인/반려/사용완료/취소를 상태 규칙대로 수행한다.
    """
    today = today or date.today()
    status = clean(reservation.get("status"))
    if status in TERMINAL_STATUSES or status not in STATUSES:
        return ()

    approver = can_approve(user)
    owner = is_owner(reservation, user)
    check_in = to_date(reservation.get("check_in"))
    check_out = to_date(reservation.get("check_out"))

    acts: list[str] = []
    if approver and status == REQUESTED:
        acts += [ACT_APPROVE, ACT_REJECT]
    if approver and status == APPROVED and check_out is not None and today >= check_out:
        acts.append(ACT_COMPLETE)
    if approver:
        acts.append(ACT_CANCEL)
    elif owner and (check_in is None or today < check_in):
        acts.append(ACT_CANCEL)
    return tuple(dict.fromkeys(acts))


def action_blocker(reservation: dict, action: str, user: dict | None, *,
                   comment: str = "", today: date | None = None,
                   reservations=None) -> str | None:
    """액션이 지금 불가능한 이유(툴팁 문구). 가능하면 ``None``.

    화면의 버튼 비활성/툴팁과 :func:`apply_action` 의 거부 사유가 **같은 규칙**을 보게
    한다 — 비활성 이유를 화면이 따로 지어내지 않는다.
    """
    today = today or date.today()
    status = clean(reservation.get("status"))
    if status in TERMINAL_STATUSES:
        return f"{STATUS_LABELS.get(status, status)} 상태는 더 이상 처리할 수 없습니다."
    if action not in allowed_actions(reservation, user, today=today):
        if action in (ACT_APPROVE, ACT_REJECT, ACT_COMPLETE) and not can_approve(user):
            return "승인 권한이 없습니다."
        if action == ACT_CANCEL:
            return "본인 신청만 체크인 전까지 취소할 수 있습니다."
        if action == ACT_COMPLETE:
            return "체크아웃일 이후에 사용완료로 처리할 수 있습니다."
        return f"현재 상태({STATUS_LABELS.get(status, status)})에서는 할 수 없습니다."
    if action in COMMENT_REQUIRED and not clean(comment):
        return f"{ACTION_LABELS[action]} 사유를 입력하세요."
    if action == ACT_CANCEL and can_approve(user) and not is_owner(reservation, user) \
            and not clean(comment):
        return "다른 사람의 예약을 취소하려면 사유를 입력하세요."
    if action == ACT_APPROVE and reservations is not None:
        hits = find_conflicts(reservations, reservation.get("lodging_code"),
                              reservation.get("check_in"), reservation.get("check_out"),
                              exclude_no=reservation.get("request_no"))
        if hits:
            nos = ", ".join(clean(h.get("request_no")) for h in hits)
            return f"같은 숙소에 이미 확정된 예약과 기간이 겹칩니다({nos})."
    return None


def apply_action(reservation: dict, action: str, *, user: dict | None,
                 comment: str = "", today: date | None = None,
                 reservations=None) -> dict:
    """상태 전이를 적용한 **새 예약 dict** 를 반환한다. 불가하면 :class:`ValueError`.

    원본 dict 는 변경하지 않는다(호출부가 저장 시점을 통제). 거부 사유는
    :func:`action_blocker` 와 동일 문구를 쓴다.
    """
    today = today or date.today()
    if action not in ACTIONS:
        raise ValueError(f"알 수 없는 처리입니다: {action}")
    blocker = action_blocker(reservation, action, user, comment=comment, today=today,
                             reservations=reservations)
    if blocker:
        raise ValueError(blocker)

    next_status = {
        ACT_APPROVE: APPROVED,
        ACT_REJECT: REJECTED,
        ACT_CANCEL: CANCELLED,
        ACT_COMPLETE: COMPLETED,
    }[action]
    updated = dict(reservation)
    updated["status"] = next_status
    updated["decided_by"] = clean((user or {}).get("emp_no"))
    updated["decided_at"] = _now_text()
    updated["decision_comment"] = clean(comment)
    return updated


def next_request_no(existing, *, today: date | None = None) -> str:
    """``LDG-YYYYMM-NNN`` 채번. 같은 연월의 최대 일련번호 + 1."""
    today = today or date.today()
    prefix = f"LDG-{today:%Y%m}-"
    top = 0
    for row in existing or []:
        no = clean(row.get("request_no") if isinstance(row, dict) else row)
        if no.startswith(prefix):
            top = max(top, to_int(no[len(prefix):], 0))
    return f"{prefix}{top + 1:03d}"


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ===========================================================================
# 저장소 접근(IO)
# ===========================================================================
def load_lodgings(*, include_inactive: bool = True) -> list[dict]:
    rows = proto_store.load_rows(LODGINGS)
    if include_inactive:
        return rows
    return [r for r in rows if to_bool(r.get("is_active"))]


def lodging_map() -> dict[str, dict]:
    return {clean(r.get("lodging_code")): r for r in load_lodgings()}


def load_reservations() -> list[dict]:
    return proto_store.load_rows(RESERVATIONS)


def get_reservation(request_no) -> dict | None:
    target = clean(request_no)
    for row in load_reservations():
        if clean(row.get("request_no")) == target:
            return row
    return None


def filter_reservations(rows, *, statuses=None, lodging_code=None,
                        applicant_emp_no=None, date_from=None, date_to=None) -> list[dict]:
    """순수 필터 — 상태·숙소·신청자·기간 겹침(반개구간)으로 좁힌다."""
    out = []
    for row in rows or []:
        if statuses and clean(row.get("status")) not in statuses:
            continue
        if lodging_code and clean(row.get("lodging_code")) != clean(lodging_code):
            continue
        if applicant_emp_no and not emp_eq(row.get("applicant_emp_no"), applicant_emp_no):
            continue
        if date_from or date_to:
            lo = to_date(date_from) or date.min
            hi = to_date(date_to) or date.max
            # 조회 구간은 폐구간(양끝 포함)이라 종료일 +1 로 반개구간 비교에 맞춘다.
            hi_excl = date.fromordinal(min(hi.toordinal() + 1, date.max.toordinal()))
            if not overlaps(row.get("check_in"), row.get("check_out"), lo, hi_excl):
                continue
        out.append(row)
    return out


def reservations_frame(rows=None) -> pd.DataFrame:
    return proto_store.to_frame(rows if rows is not None else load_reservations(),
                                RESERVATION_COLUMNS)


def lodgings_frame(rows=None) -> pd.DataFrame:
    return proto_store.to_frame(rows if rows is not None else load_lodgings(),
                                LODGING_COLUMNS)


def create_reservation(payload: dict, *, current_user: dict) -> dict:
    """신청을 저장한다. 신원(신청자 사번·성명·소속)은 세션 사용자에서 서버측 확정한다.

    검증 실패는 :class:`ValueError`(첫 문구 + 전체 목록)로 올린다 — 화면이 원문을 그대로
    보여줄 수 있는 사용자 안전 문구다.
    """
    rows = load_reservations()
    lodging = lodging_map().get(clean(payload.get("lodging_code")))
    errors = validate_reservation(payload, lodging=lodging)
    if errors:
        raise ValueError(" / ".join(errors))

    emp_no = clean((current_user or {}).get("emp_no"))
    if not emp_no:
        raise ValueError("로그인 사번을 확인할 수 없어 신청할 수 없습니다.")
    hits = occupied_conflicts(rows, payload.get("lodging_code"),
                              payload.get("check_in"), payload.get("check_out"))
    if hits:
        raise ReservationConflict(conflict_message(hits))

    record = {
        "request_no": next_request_no(rows),
        "lodging_code": clean(payload.get("lodging_code")),
        "applicant_emp_no": emp_no,
        "applicant_name": clean((current_user or {}).get("name")),
        "dept_code": clean((current_user or {}).get("dept_code")),
        "check_in": to_date(payload.get("check_in")).isoformat(),
        "check_out": to_date(payload.get("check_out")).isoformat(),
        "status": REQUESTED,
        "decided_by": "", "decided_at": "", "decision_comment": "",
        "created_at": _now_text(),
    }
    rows.append(record)
    proto_store.save_rows(RESERVATIONS, rows)
    return record


def update_reservation(request_no, payload: dict, *, current_user: dict) -> dict:
    """신청(REQUESTED) 상태 예약의 숙소·기간을 수정한다.

    주체는 **신청자 본인 또는 승인권자**(2026-08-07 결정 — 승인 관리에서 일정 정정 가능).
    업무요청 `update_request` 자기수정과 같은 계약으로, 서버측에서 권한·상태를 재확인한다.
    """
    rows = load_reservations()
    target = clean(request_no)
    index = next((i for i, r in enumerate(rows)
                  if clean(r.get("request_no")) == target), None)
    if index is None:
        raise ValueError("예약을 찾을 수 없습니다. 목록을 새로고침한 뒤 다시 시도하세요.")
    current = rows[index]
    if not (is_owner(current, current_user) or can_approve(current_user)):
        raise ValueError("본인 신청 또는 승인 담당자만 수정할 수 있습니다.")
    if clean(current.get("status")) != REQUESTED:
        raise ValueError("신청(REQUESTED) 상태에서만 수정할 수 있습니다.")

    merged = {**current, **payload}
    lodging = lodging_map().get(clean(merged.get("lodging_code")))
    errors = validate_reservation(merged, lodging=lodging)
    if errors:
        raise ValueError(" / ".join(errors))
    hits = occupied_conflicts(rows, merged.get("lodging_code"),
                              merged.get("check_in"), merged.get("check_out"),
                              exclude_no=target)
    if hits:
        raise ReservationConflict(conflict_message(hits))

    updated = dict(current)
    updated["lodging_code"] = clean(merged.get("lodging_code"))
    updated["check_in"] = to_date(merged.get("check_in")).isoformat()
    updated["check_out"] = to_date(merged.get("check_out")).isoformat()
    rows[index] = updated
    proto_store.save_rows(RESERVATIONS, rows)
    return updated


def run_action(request_no, action: str, *, current_user: dict, comment: str = "") -> dict:
    """저장된 예약에 상태 전이를 적용하고 영속화한다. 실패는 :class:`ValueError`."""
    rows = load_reservations()
    target = clean(request_no)
    index = next((i for i, r in enumerate(rows)
                  if clean(r.get("request_no")) == target), None)
    if index is None:
        raise ValueError("예약을 찾을 수 없습니다. 목록을 새로고침한 뒤 다시 시도하세요.")
    updated = apply_action(rows[index], action, user=current_user, comment=comment,
                           reservations=rows)
    rows[index] = updated
    proto_store.save_rows(RESERVATIONS, rows)
    return updated


# ===========================================================================
# 현황 집계(캘린더 공용) — 순수
# ===========================================================================
def day_span(reservation: dict) -> list[date]:
    """예약이 점유하는 날짜 목록(반개구간 — 체크아웃 당일 제외)."""
    ci, co = to_date(reservation.get("check_in")), to_date(reservation.get("check_out"))
    if ci is None or co is None or co <= ci:
        return []
    return [date.fromordinal(o) for o in range(ci.toordinal(), co.toordinal())]


def occupancy_index(reservations, *, statuses: tuple[str, ...] = OCCUPYING_STATUSES
                    ) -> dict[tuple[str, date], dict]:
    """``(숙소코드, 날짜) → 예약`` 인덱스. 캘린더 두 시안이 공유하는 단일 집계."""
    index: dict[tuple[str, date], dict] = {}
    for row in reservations or []:
        if clean(row.get("status")) not in statuses:
            continue
        code = clean(row.get("lodging_code"))
        for day in day_span(row):
            index.setdefault((code, day), row)
    return index


def occupancy_rate(reservations, lodging_codes, days) -> float:
    """기간 가동률(%) — 점유 (숙소×일) / 전체 (숙소×일). 분모가 0이면 0.0."""
    codes = [clean(c) for c in (lodging_codes or []) if clean(c)]
    total = len(codes) * len(days or [])
    if not total:
        return 0.0
    index = occupancy_index(reservations)
    used = sum(1 for c in codes for d in days if (c, d) in index)
    return round(used * 100.0 / total, 1)


def month_days(year: int, month: int) -> list[date]:
    """해당 연월의 날짜 목록."""
    start = date(year, month, 1)
    end = date(year + (month == 12), (month % 12) + 1, 1)
    return [date.fromordinal(o) for o in range(start.toordinal(), end.toordinal())]
