"""아차사고 화면 공용 파생 — 보완요청 상태 파생 · 개선조치 단계 라벨.

DESIGN.md §3.6 "라벨은 단일 출처를 갖는다". 이 모듈은 **여러 화면이 같은 값을 파생해야
하는 두 가지**만 담는다(화면별 ``_STATUS_LABEL`` 전체 통합은 §3.6 이 지적한 별건이다):

1. **보완요청 파생** — 보완요청(반송)은 상태를 ``IN_REVIEW`` → ``SUBMITTED`` 로 되돌린다
   (``db.request_near_miss_revision``). 그래서 DB 상태 코드만 보면 보완요청 건과 **갓 등록한
   건이 완전히 같다**. 보고자는 무엇을 보완해야 하는지 알 수 없고 평가자는 재제출을 기다리는
   건인지 새 건인지 알 수 없다.

   해결은 **새 DB 상태값을 만드는 것이 아니라**(migration 회피) 이미 저장되는 보완요청
   3필드(``revision_request_reason``/``revision_requested_by_emp_no``/
   ``revision_requested_at``, 007)에서 표시 라벨을 파생하는 것이다. 코드값 ``SUBMITTED`` 는
   그대로 두고 화면 라벨만 ``보완요청`` 으로 바꾼다 — §3.6 "영문 코드값은 바꾸지 않는다".

2. **개선조치 단계 라벨** — 아차사고 조회의 '개선조치' 열과 개선조치 관리의 탭·행·상세가
   같은 낱말을 써야 한다. 한 도메인에 한 낱말(§3.6).

도메인 데이터 접근은 하지 않는다(순수 함수) — 조회는 호출부가 파사드로 한다.
"""
from __future__ import annotations

# 보완요청이 걸린 SUBMITTED 건의 표시 라벨. 상태 5종 라벨과 같은 계층의 낱말이며
# 평가 관리의 액션 이름('보완요청')과 어근을 공유한다(§3.6).
REVISION_LABEL = "보완요청"

# 개선조치 단계 라벨 — 개선조치 관리(views/near_miss_improvement)의 탭·행·상세와 같은 낱말.
IMPROVEMENT_STAGE_NONE = "미작성"     # 개선조치 레코드는 있으나 상태를 읽을 수 없을 때
IMPROVEMENT_STAGE_DRAFT = "작성중"
IMPROVEMENT_STAGE_PENDING = "확인대기"
IMPROVEMENT_STAGE_CONFIRMED = "확인됨"
IMPROVEMENT_STAGE_REJECTED = "반려"
# 조회 표에서 개선조치 자체가 없는 행의 표기. 빈 문자열이 아니라 '-' 를 쓴다 — 빈 셀은
# "값이 없다"와 "불러오지 못했다"를 구분하지 못한다.
IMPROVEMENT_STAGE_EMPTY = "-"


def _text(value) -> str:
    """None·NaN·공백을 안전하게 빈 문자열로 정리한다(pandas 결측 포함)."""
    if value is None:
        return ""
    # pandas 결측(NaN)은 truthy 라 ``str(v or "")`` 로는 걸러지지 않는다. list/dict 는
    # pd.isna 가 원소별 배열을 돌려주므로(ambiguity) 판정 대상에서 제외한다.
    if not isinstance(value, (list, dict, tuple)):
        try:
            import pandas as pd

            if pd.isna(value):
                return ""
        except (TypeError, ValueError, ImportError):
            pass
    return str(value).strip()


def has_revision_request(row) -> bool:
    """이 보고서에 **미해소 보완요청**이 걸려 있는가.

    판정은 사유(``revision_request_reason``) 하나로 한다 — DB CHECK
    (``near_miss_reports_revision_request_all_or_none``)가 사유·요청자·시각을 all-or-none
    으로 묶으므로 사유가 있으면 나머지도 있고, 사유가 없으면 요청이 없다. 재제출
    (``db.resubmit_near_miss``)이 세 필드를 함께 비우면 이 판정이 곧 False 가 된다.

    ``row`` 는 dict 또는 pandas Series(``.get`` 지원). 007 미적용이면 필드 자체가 없어
    False(정상 부재)."""
    if row is None:
        return False
    try:
        value = row.get("revision_request_reason")
    except AttributeError:
        return False
    return bool(_text(value))


def status_label(row, labels: dict, *, default: str = "") -> str:
    """상태 표시 라벨 — 보완요청이 걸린 ``SUBMITTED`` 는 ``보완요청`` 으로 파생한다.

    ``labels`` 는 호출 화면의 상태 코드→라벨 사전이다. 코드값은 바꾸지 않고 표시만
    바꾸므로 필터·저장·전이 계약은 전부 그대로다(``SUBMITTED`` 필터는 보완요청 건도
    포함한다 — 실제로 같은 상태이기 때문이다).

    보완요청이 의미를 갖는 상태는 ``SUBMITTED`` 하나다. 평가착수·평가확정·반려로 넘어가면
    그 상태가 곧 현재 사실이므로 파생하지 않는다(요청 3필드가 남아 있어도 무시)."""
    code = _text(row.get("status") if row is not None else "")
    if code == "SUBMITTED" and has_revision_request(row):
        return REVISION_LABEL
    return labels.get(code, code or default)


def improvement_stage(imp) -> str:
    """개선조치 한 건의 '조치 단계' 라벨(제출/확인 상태 파생).

    미작성(DRAFT 이전) < 작성중(DRAFT) < 확인대기(SUBMITTED·PENDING) < 확인됨(CONFIRMED) /
    반려(REJECTED). 확정 상태(확인됨/반려)를 제출 상태보다 **먼저** 판정한다 — 확인·반려된
    건도 submit_status 는 SUBMITTED 로 남아 있어 순서를 바꾸면 전부 '확인대기'가 된다."""
    if not imp:
        return IMPROVEMENT_STAGE_NONE
    confirm = _text(imp.get("confirm_status"))
    submit = _text(imp.get("submit_status"))
    if confirm == "CONFIRMED":
        return IMPROVEMENT_STAGE_CONFIRMED
    if confirm == "REJECTED":
        return IMPROVEMENT_STAGE_REJECTED
    if submit == "SUBMITTED":
        return IMPROVEMENT_STAGE_PENDING
    if submit == "DRAFT":
        return IMPROVEMENT_STAGE_DRAFT
    return IMPROVEMENT_STAGE_NONE


def improvement_cell(imp) -> str:
    """조회 표의 '개선조치' 셀 값 — 개선조치가 **없으면** ``-``, 있으면 단계 라벨.

    개선조치는 평가완료(EVALUATED) 이후 단계라 대부분의 행에는 아직 존재하지 않는다.
    없는 행에 '미작성'을 쓰면 "작성해야 하는데 안 했다"로 읽혀 사실과 다르다 — 아직
    그 단계에 오지 않은 것이다. 그래서 부재는 ``-`` 로 두고, 레코드가 실제로 있는
    행만 단계를 말한다."""
    return improvement_stage(imp) if imp else IMPROVEMENT_STAGE_EMPTY
