"""업무요청서 도메인(프로토타입) — 상태 전이·검증 + 로컬 파일 영속.

아차사고(제출 → 검토 → 평가 → 종결) 라이프사이클 패턴을 그대로 차용한다. 저장은
``modules/proto_store`` (시드 ``data/sample/work_requests.csv`` → 런타임 JSON)만 쓰고
``modules/db.py`` 파사드·원격 저장소는 호출하지 않는다.

역할 분담(아차사고와 동일한 사고방식)
-------------------------------------
- **요청자**: 제출 · 처리완료 건 종결 확인 · 보완 요청(처리중으로 반송).
- **처리자**(프로토타입 가정 ``role ∈ {ADMIN, MANAGER}``): 처리 착수(담당자 지정) ·
  처리 완료(결과 필수) · 반려(사유 필수).
- 신원은 화면 위젯이 아니라 세션 사용자에서 서버측 확정한다.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from modules import proto_store

REQUESTS = "work_requests"

# ── 상태(라이프사이클) ───────────────────────────────────────────────────────
SUBMITTED = "SUBMITTED"
IN_PROGRESS = "IN_PROGRESS"
DONE = "DONE"
CLOSED = "CLOSED"
REJECTED = "REJECTED"

STATUSES: tuple[str, ...] = (SUBMITTED, IN_PROGRESS, DONE, CLOSED, REJECTED)
STATUS_LABELS = {
    SUBMITTED: "제출됨",
    IN_PROGRESS: "처리중",
    DONE: "처리완료",
    CLOSED: "종결",
    REJECTED: "반려",
}
TERMINAL_STATUSES: tuple[str, ...] = (CLOSED, REJECTED)
#: 처리 큐에 남는 상태(담당 부서가 지금 손대야 하는 건).
PENDING_STATUSES: tuple[str, ...] = (SUBMITTED, IN_PROGRESS)
#: 진행 단계 pill 순서(반려는 분기라 별도).
PROGRESS_ORDER = ((SUBMITTED, "제출"), (IN_PROGRESS, "처리중"),
                  (DONE, "처리완료"), (CLOSED, "종결"))

REQUEST_TYPES = ("전산", "설비", "시설", "구매", "기타")
PRIORITIES = ("긴급", "보통", "낮음")
#: 처리 부서 후보 — 기존 sample 부서 코드를 그대로 쓴다(자연키 계약 유지).
TARGET_DEPTS = ("PET1", "PET2", "MGT")
#: 부서 코드→명칭. 프로토타입 표시용 비정규화이며, 통합 시
#: ``db.get_departments()`` 조회로 대체한다(코드 자체는 바꾸지 않는다).
DEPT_LABELS = {"PET1": "PET생산부(본동)", "PET2": "PET생산부(원료실)", "MGT": "생산관리팀"}


def dept_label(code) -> str:
    text = str(code or "").strip()
    if not text:
        return "-"
    name = DEPT_LABELS.get(text)
    return f"{name} ({text})" if name else text

# ── 액션 ────────────────────────────────────────────────────────────────────
ACT_START = "start"        # 제출됨 → 처리중 (담당자 지정 필수)
ACT_COMPLETE = "complete"  # 처리중 → 처리완료 (처리 결과 필수)
ACT_REJECT = "reject"      # 제출됨/처리중 → 반려 (사유 필수)
ACT_CLOSE = "close"        # 처리완료 → 종결 (요청자 확인)
ACT_REOPEN = "reopen"      # 처리완료 → 처리중 (보완 요청, 사유 필수)
ACTIONS: tuple[str, ...] = (ACT_START, ACT_COMPLETE, ACT_REJECT, ACT_CLOSE, ACT_REOPEN)
ACTION_LABELS = {
    ACT_START: "처리 착수",
    ACT_COMPLETE: "처리 완료",
    ACT_REJECT: "반려",
    ACT_CLOSE: "종결 확인",
    ACT_REOPEN: "보완 요청",
}
#: 의견 입력이 필수인 액션(액션별 라벨은 화면이 아니라 여기가 소유).
COMMENT_REQUIRED = (ACT_COMPLETE, ACT_REJECT, ACT_REOPEN)
COMMENT_LABELS = {
    ACT_COMPLETE: "처리 결과",
    ACT_REJECT: "반려 사유",
    ACT_REOPEN: "보완 사유",
}

HANDLER_ROLES = ("ADMIN", "MANAGER")
TITLE_MAX = 80
CONTENT_MIN = 10

REQUEST_COLUMNS = [
    "request_no", "title", "request_type", "priority",
    "requester_emp_no", "requester_name", "requester_dept", "target_dept",
    "desired_due", "content", "reference", "status",
    "assignee_emp_no", "assignee_name", "result_note", "reject_reason",
    "created_at", "updated_at",
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
    a, b = clean(left), clean(right)
    return bool(a) and bool(b) and a.casefold() == b.casefold()


def to_date(value) -> date | None:
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


def is_overdue(request: dict, *, today: date | None = None) -> bool:
    """희망 완료일이 지났는데 아직 미완료면 지연."""
    if clean(request.get("status")) not in PENDING_STATUSES:
        return False
    due = to_date(request.get("desired_due"))
    return due is not None and due < (today or date.today())


def days_left(request: dict, *, today: date | None = None) -> int | None:
    due = to_date(request.get("desired_due"))
    if due is None:
        return None
    return (due - (today or date.today())).days


# ===========================================================================
# 검증 — 순수
# ===========================================================================
def validate_request(payload: dict, *, today: date | None = None) -> list[str]:
    """제출 payload 검증. 사용자에게 보여줄 문구 목록(빈 목록=통과)."""
    today = today or date.today()
    errors: list[str] = []

    title = clean(payload.get("title"))
    if not title:
        errors.append("요청 제목을 입력하세요.")
    elif len(title) > TITLE_MAX:
        errors.append(f"요청 제목은 {TITLE_MAX}자 이내로 입력하세요.")

    if clean(payload.get("request_type")) not in REQUEST_TYPES:
        errors.append("요청 유형을 선택하세요.")
    if clean(payload.get("priority")) not in PRIORITIES:
        errors.append("우선순위를 선택하세요.")
    if not clean(payload.get("target_dept")):
        errors.append("처리 부서를 선택하세요.")

    due = to_date(payload.get("desired_due"))
    if due is None:
        errors.append("희망 완료일을 입력하세요.")
    elif due < today:
        errors.append("희망 완료일은 오늘 이후여야 합니다.")

    content = clean(payload.get("content"))
    if not content:
        errors.append("요청 내용을 입력하세요.")
    elif len(content) < CONTENT_MIN:
        errors.append(f"요청 내용을 {CONTENT_MIN}자 이상 구체적으로 적어 주세요.")
    return errors


# ===========================================================================
# 권한·허용 액션 — 순수
# ===========================================================================
def can_handle(user: dict | None) -> bool:
    """처리자 여부(프로토타입 가정: ADMIN·MANAGER). 확정 시 처리 부서 소속 기준으로 대체 가능."""
    return clean((user or {}).get("role")).upper() in HANDLER_ROLES


def is_requester(request: dict, user: dict | None) -> bool:
    return emp_eq(request.get("requester_emp_no"), (user or {}).get("emp_no"))


def is_admin(user: dict | None) -> bool:
    return clean((user or {}).get("role")).upper() == "ADMIN"


def allowed_actions(request: dict, user: dict | None) -> tuple[str, ...]:
    """이 사용자가 이 요청에 대해 지금 할 수 있는 액션(순서 고정, 종결은 빈 튜플)."""
    status = clean(request.get("status"))
    if status in TERMINAL_STATUSES or status not in STATUSES:
        return ()

    acts: list[str] = []
    if can_handle(user):
        if status == SUBMITTED:
            acts += [ACT_START, ACT_REJECT]
        elif status == IN_PROGRESS:
            acts += [ACT_COMPLETE, ACT_REJECT]
    if status == DONE and (is_requester(request, user) or is_admin(user)):
        acts += [ACT_CLOSE, ACT_REOPEN]
    return tuple(dict.fromkeys(acts))


def action_blocker(request: dict, action: str, user: dict | None, *,
                   comment: str = "", assignee: dict | None = None) -> str | None:
    """액션이 지금 불가능한 이유(툴팁 문구). 가능하면 ``None`` — 화면 비활성 사유와 단일 출처."""
    status = clean(request.get("status"))
    if status in TERMINAL_STATUSES:
        return f"{STATUS_LABELS.get(status, status)} 상태는 더 이상 처리할 수 없습니다."
    if action not in allowed_actions(request, user):
        if action in (ACT_START, ACT_COMPLETE, ACT_REJECT) and not can_handle(user):
            return "업무요청 처리 권한이 없습니다."
        if action in (ACT_CLOSE, ACT_REOPEN):
            if status != DONE:
                return "처리완료 상태에서만 종결 확인·보완 요청을 할 수 있습니다."
            return "요청자 본인만 종결 확인·보완 요청을 할 수 있습니다."
        return f"현재 상태({STATUS_LABELS.get(status, status)})에서는 할 수 없습니다."
    if action in COMMENT_REQUIRED and not clean(comment):
        return f"{COMMENT_LABELS.get(action, '의견')}을(를) 입력하세요."
    if action == ACT_START and not clean((assignee or {}).get("emp_no")):
        return "처리 담당자를 지정하세요."
    return None


def apply_action(request: dict, action: str, *, user: dict | None, comment: str = "",
                 assignee: dict | None = None) -> dict:
    """상태 전이를 적용한 **새 요청 dict** 를 반환한다(원본 불변). 불가하면 :class:`ValueError`."""
    if action not in ACTIONS:
        raise ValueError(f"알 수 없는 처리입니다: {action}")
    blocker = action_blocker(request, action, user, comment=comment, assignee=assignee)
    if blocker:
        raise ValueError(blocker)

    updated = dict(request)
    updated["updated_at"] = _now_text()
    if action == ACT_START:
        updated["status"] = IN_PROGRESS
        updated["assignee_emp_no"] = clean((assignee or {}).get("emp_no"))
        updated["assignee_name"] = clean((assignee or {}).get("name"))
    elif action == ACT_COMPLETE:
        updated["status"] = DONE
        updated["result_note"] = clean(comment)
    elif action == ACT_REJECT:
        updated["status"] = REJECTED
        updated["reject_reason"] = clean(comment)
    elif action == ACT_CLOSE:
        updated["status"] = CLOSED
    elif action == ACT_REOPEN:
        updated["status"] = IN_PROGRESS
        updated["reject_reason"] = clean(comment)  # 보완 사유(요청자 반송)
        updated["result_note"] = ""                # 반송되면 직전 처리 결과는 무효
    return updated


def next_request_no(existing, *, today: date | None = None) -> str:
    """``WR-YYYYMM-NNN`` 채번. 같은 연월의 최대 일련번호 + 1."""
    today = today or date.today()
    prefix = f"WR-{today:%Y%m}-"
    top = 0
    for row in existing or []:
        no = clean(row.get("request_no") if isinstance(row, dict) else row)
        if no.startswith(prefix):
            tail = no[len(prefix):]
            try:
                top = max(top, int(tail))
            except ValueError:
                continue
    return f"{prefix}{top + 1:03d}"


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ===========================================================================
# 저장소 접근(IO)
# ===========================================================================
def load_requests() -> list[dict]:
    return proto_store.load_rows(REQUESTS)


def get_request(request_no) -> dict | None:
    target = clean(request_no)
    for row in load_requests():
        if clean(row.get("request_no")) == target:
            return row
    return None


def filter_requests(rows, *, statuses=None, requester_emp_no=None, target_dept=None,
                    request_type=None, priority=None, keyword=None) -> list[dict]:
    """순수 필터 — 상태·요청자·처리 부서·유형·우선순위·제목 키워드."""
    kw = clean(keyword).casefold()
    out = []
    for row in rows or []:
        if statuses and clean(row.get("status")) not in statuses:
            continue
        if requester_emp_no and not emp_eq(row.get("requester_emp_no"), requester_emp_no):
            continue
        if target_dept and clean(row.get("target_dept")) != clean(target_dept):
            continue
        if request_type and clean(row.get("request_type")) != clean(request_type):
            continue
        if priority and clean(row.get("priority")) != clean(priority):
            continue
        if kw and kw not in clean(row.get("title")).casefold() \
                and kw not in clean(row.get("content")).casefold():
            continue
        out.append(row)
    return out


def requests_frame(rows=None) -> pd.DataFrame:
    return proto_store.to_frame(rows if rows is not None else load_requests(),
                                REQUEST_COLUMNS)


def create_request(payload: dict, *, current_user: dict) -> dict:
    """요청서를 저장한다. 요청자 신원은 세션 사용자에서 서버측 확정한다."""
    errors = validate_request(payload)
    if errors:
        raise ValueError(" / ".join(errors))
    emp_no = clean((current_user or {}).get("emp_no"))
    if not emp_no:
        raise ValueError("로그인 사번을 확인할 수 없어 요청을 등록할 수 없습니다.")

    rows = load_requests()
    now = _now_text()
    record = {
        "request_no": next_request_no(rows),
        "title": clean(payload.get("title")),
        "request_type": clean(payload.get("request_type")),
        "priority": clean(payload.get("priority")),
        "requester_emp_no": emp_no,
        "requester_name": clean((current_user or {}).get("name")),
        "requester_dept": clean((current_user or {}).get("dept_code")),
        "target_dept": clean(payload.get("target_dept")),
        "desired_due": to_date(payload.get("desired_due")).isoformat(),
        "content": clean(payload.get("content")),
        "reference": clean(payload.get("reference")),
        "status": SUBMITTED,
        "assignee_emp_no": "", "assignee_name": "",
        "result_note": "", "reject_reason": "",
        "created_at": now, "updated_at": now,
    }
    rows.append(record)
    proto_store.save_rows(REQUESTS, rows)
    return record


def update_request(request_no, payload: dict, *, current_user: dict) -> dict:
    """제출됨(SUBMITTED) 상태의 **본인 요청** 본문을 수정한다(아차사고 자기수정과 동일 계약)."""
    rows = load_requests()
    target = clean(request_no)
    index = next((i for i, r in enumerate(rows)
                  if clean(r.get("request_no")) == target), None)
    if index is None:
        raise ValueError("요청서를 찾을 수 없습니다. 목록을 새로고침한 뒤 다시 시도하세요.")
    current = rows[index]
    if not is_requester(current, current_user):
        raise ValueError("본인이 등록한 요청서만 수정할 수 있습니다.")
    if clean(current.get("status")) != SUBMITTED:
        raise ValueError("제출됨 상태에서만 내용을 수정할 수 있습니다.")
    errors = validate_request({**current, **payload})
    if errors:
        raise ValueError(" / ".join(errors))

    updated = dict(current)
    for key in ("title", "request_type", "priority", "target_dept", "content", "reference"):
        if key in payload:
            updated[key] = clean(payload.get(key))
    if "desired_due" in payload:
        updated["desired_due"] = to_date(payload.get("desired_due")).isoformat()
    updated["updated_at"] = _now_text()
    rows[index] = updated
    proto_store.save_rows(REQUESTS, rows)
    return updated


def run_action(request_no, action: str, *, current_user: dict, comment: str = "",
               assignee: dict | None = None) -> dict:
    """저장된 요청에 상태 전이를 적용하고 영속화한다. 실패는 :class:`ValueError`."""
    rows = load_requests()
    target = clean(request_no)
    index = next((i for i, r in enumerate(rows)
                  if clean(r.get("request_no")) == target), None)
    if index is None:
        raise ValueError("요청서를 찾을 수 없습니다. 목록을 새로고침한 뒤 다시 시도하세요.")
    updated = apply_action(rows[index], action, user=current_user, comment=comment,
                           assignee=assignee)
    rows[index] = updated
    proto_store.save_rows(REQUESTS, rows)
    return updated


def summarize(rows, *, today: date | None = None) -> dict:
    """지표 스트립용 집계(전부 기존 데이터 파생 — 허수 없음)."""
    today = today or date.today()
    counts = {s: 0 for s in STATUSES}
    overdue = 0
    for row in rows or []:
        status = clean(row.get("status"))
        if status in counts:
            counts[status] += 1
        if is_overdue(row, today=today):
            overdue += 1
    counts["TOTAL"] = len(rows or [])
    counts["OVERDUE"] = overdue
    counts["PENDING"] = counts[SUBMITTED] + counts[IN_PROGRESS]
    return counts
