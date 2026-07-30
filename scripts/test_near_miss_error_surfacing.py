"""아차사고 조회 오류 표면화 회귀 (종합감사 P2 — '조회 오류 은폐' 수정).

계약: READY 이후의 실제 조회 오류를 '미작성/보완요청 없음/overdue 0' 같은 정상 부재로
위장하지 않는다(오류 ≠ 정상 부재). 정상 부재(None)는 그대로 정상으로 표시한다.

세 화면의 오류 경로는 모두 순수 헬퍼(st 미접촉)로 분기되므로, 개별 조회 파사드에 오류를
주입해 다음을 직접 검증한다.
  1) near_miss_improvement._improvements_for  — actor-aware bulk(list_near_miss_improvements).
                                                조회 실패는 빈 dict 로 접지 않고 load_failed=True
                                                (행 라벨 '조회실패'), 정상 부재는 빈 dict + 미작성.
  2) near_miss_my._render_revision_banner     — 조회 실패는 danger 배너, 없음은 무배너.
  3) db.near_miss_overdue_count               — 평가자/ADMIN 전용, 개별 조회 실패는 축소 수치/
                                                가짜 0 아닌 None('—'), 일반 USER 는 미노출(None).
"""
from __future__ import annotations

import os
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

import pandas as pd  # noqa: E402

from modules import db  # noqa: E402
from views import near_miss_improvement as nmi  # noqa: E402
from views import near_miss_my as nmy  # noqa: E402
from views import near_miss_stats as nms  # noqa: E402

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name}")


class _Boom(db.DATA_SOURCE_ERRORS[1]):  # SupabaseDataError — 실제 데이터소스 오류 모사.
    pass


def _swap(mod, name, value):
    """모듈 속성 임시 교체 컨텍스트(원복 보장)."""
    class _Ctx:
        def __enter__(self_):
            self_.orig = getattr(mod, name)
            setattr(mod, name, value)
            return self_

        def __exit__(self_, *a):
            setattr(mod, name, self_.orig)
            return False
    return _Ctx()


_REPORTS = pd.DataFrame([{"id": "r1"}, {"id": "r2"}])


# ===== 1) near_miss_improvement._improvements_for (actor-aware bulk + load_failed) =====
print("개선조치 큐 enrich — 조회 실패 vs 정상 부재 구분")

_VIEWER = {"emp_no": "x"}  # _improvements_for 는 actor-aware(current_user 필수).

# 조회 실패(READY 이후 실제 오류)는 빈 dict('미작성')로 접지 않고 load_failed=True 로 표면화한다.
with _swap(db, "list_near_miss_improvements",
           lambda ids, **kw: (_ for _ in ()).throw(_Boom("boom"))):
    imps, load_failed = nmi._improvements_for(_REPORTS, _VIEWER)
check("조회 실패 → load_failed=True(오류 표면화)", load_failed is True)
check("조회 실패 시 enrich dict 는 비어있음(미작성 위장 아님)", imps == {})

# 정상 부재(개선조치 없음)는 빈 dict + load_failed=False — '미작성'으로 정상 표시.
with _swap(db, "list_near_miss_improvements", lambda ids, **kw: {}):
    imps_absent, lf_absent = nmi._improvements_for(_REPORTS, _VIEWER)
check("정상 부재 → load_failed=False", lf_absent is False)
check("정상 부재 dict 비어있음(그러나 오류 아님)", imps_absent == {})
check("정상 부재는 '미작성' 라벨(오류 표식과 구분)",
      nmi._confirm_state_of(None) == "미작성")

# §1-A 큐 칩 스트립 재구조: 담당자·확인상태 열이 없다. load_failed 는 KPI 파생 지표를 0으로
# 위장하지 않고 '—'로 표면화한다(오류≠정상 부재). _render_body 는 별도 error 배너도 띄운다.
_QUEUE_REPORTS = pd.DataFrame([
    {"id": "r1", "report_no": "NM-1", "work_name": "작업A",
     "confirmed_grade": "B", "incident_date": "2026-07-01"},
    {"id": "r2", "report_no": "NM-2", "work_name": "작업B",
     "confirmed_grade": "C", "incident_date": "2026-07-02"},
])
with _swap(db, "list_near_miss_improvements",
           lambda ids, **kw: (_ for _ in ()).throw(_Boom("boom"))):
    imps_q, lf_q = nmi._improvements_for(_QUEUE_REPORTS, _VIEWER)
check("큐 조회 실패 → load_failed=True(오류 표면화)", lf_q is True)
kpi_fail = nmi._kpi_strip_html(_QUEUE_REPORTS, imps_q, lf_q)
check("KPI 파생 지표는 실패 시 '—'(0 위장 아님)", "—" in kpi_fail)
check("KPI 종결 대기(큐 크기)는 실제 표시(2)", ">2<" in kpi_fail)
body_src = inspect.getsource(nmi._render_body)
check("load_failed 시 별도 error 배너 표면화", "load_failed" in body_src and "st.error" in body_src)


# ===== 2) near_miss_my._render_revision_banner =====
print("내 아차사고 보완요청 — 조회 실패 표면화 vs 무배너")

_banners: list[tuple] = []


def _rec_banner(kind, msg):
    _banners.append((kind, msg))


with _swap(nmy, "banner", _rec_banner):
    # 조회 실패 → danger 배너(조용한 생략 금지).
    _banners.clear()
    with _swap(db, "get_near_miss_revision_request",
               lambda rid: (_ for _ in ()).throw(_Boom("boom"))):
        nmy._render_revision_banner("r1")
    check("보완요청 조회 실패 → 배너 1건", len(_banners) == 1)
    check("보완요청 조회 실패 → danger 배너(오류 표면화)",
          bool(_banners) and _banners[0][0] == "danger")

    # 정상 부재(None) → 무배너(가짜 표시 없음).
    _banners.clear()
    with _swap(db, "get_near_miss_revision_request", lambda rid: None):
        nmy._render_revision_banner("r1")
    check("보완요청 없음(None) → 무배너(정상)", _banners == [])

    # 정상 존재 → info 배너(반려 warn 과 별개 시각).
    _banners.clear()
    with _swap(db, "get_near_miss_revision_request",
               lambda rid: {"revision_request_reason": "보완해주세요"}):
        nmy._render_revision_banner("r1")
    check("보완요청 존재 → info 배너", _banners and _banners[0][0] == "info")


# ===== 3) db.near_miss_overdue_count (CAPA 기한초과 집계 파사드) =====
print("CAPA 기한초과 집계 — 평가자/ADMIN 전용 + 개별 조회 실패는 None('—'), 가짜 0/축소 금지")

_PAST_DUE = {"is_active": True, "confirm_status": "PENDING", "due_date": "2000-01-01"}
_EVAL_ACTOR = {"emp_no": "eval", "role": "MANAGER", "is_safety_officer": False}
_USER_ACTOR = {"emp_no": "u", "role": "USER", "is_safety_officer": False}

# 집계는 명시적 privileged 경로 — 원본은 _near_miss_improvement_raw 를 순회한다(actor 게이트 통과 후).
with _swap(db, "_near_miss_actor", lambda cu, **k: dict(_EVAL_ACTOR)), \
        _swap(db, "near_miss_improvement_schema_probe", lambda **k: db.READINESS_READY), \
        _swap(db, "get_near_miss_reports", lambda f=None: _REPORTS):
    # 개별 개선조치 조회가 던지면 축소 수치/0 이 아니라 None(미상).
    with _swap(db, "_near_miss_improvement_raw",
               lambda rid: (_ for _ in ()).throw(_Boom("boom"))):
        overdue_err = db.near_miss_overdue_count(current_user=_EVAL_ACTOR)
    check("개별 조회 실패 → None(미상, 가짜 0/축소 금지)", overdue_err is None)
    check("None 은 KPI 에서 '—'로 표기", nms._overdue_label(overdue_err) == "—")

    # 대조군: 모두 기한초과면 실제 건수(축소 없음).
    with _swap(db, "_near_miss_improvement_raw", lambda rid: dict(_PAST_DUE)):
        overdue_all = db.near_miss_overdue_count(current_user=_EVAL_ACTOR)
    check("정상 경로: 기한초과 실제 건수 집계", overdue_all == len(_REPORTS))
    check("정상 건수는 '{n}건'으로 표기", nms._overdue_label(overdue_all) == f"{len(_REPORTS)}건")

    # 대조군: 진짜 0(모두 확인됨)은 0 그대로(오류 아님).
    with _swap(db, "_near_miss_improvement_raw",
               lambda rid: {"is_active": True, "confirm_status": "CONFIRMED", "due_date": "2000-01-01"}):
        overdue_zero = db.near_miss_overdue_count(current_user=_EVAL_ACTOR)
    check("진짜 0(모두 확인)은 0 유지 — 오류와 구분", overdue_zero == 0)

# 역할 게이트: 일반 USER 는 CAPA 기한초과 집계를 못 본다(aggregate leak 방지 → None='—').
with _swap(db, "_near_miss_actor", lambda cu, **k: dict(_USER_ACTOR)), \
        _swap(db, "near_miss_improvement_schema_probe", lambda **k: db.READINESS_READY), \
        _swap(db, "get_near_miss_reports", lambda f=None: _REPORTS), \
        _swap(db, "_near_miss_improvement_raw", lambda rid: dict(_PAST_DUE)):
    overdue_user = db.near_miss_overdue_count(current_user=_USER_ACTOR)
check("일반 USER 는 CAPA 기한초과 미노출(None='—', 역할 게이트)", overdue_user is None)


print()
if FAIL:
    print(f"FAILED ({len(FAIL)}): " + "; ".join(FAIL))
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
