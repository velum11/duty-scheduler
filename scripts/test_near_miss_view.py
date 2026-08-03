"""views/near_miss_view.py 순수 함수 회귀 테스트(구조적 UI 이관 전 보존 목록).

대상: `_scope_for`(fail-closed 접근 범위) · `_to_display`(9열 표시 변환) ·
`_has_filters` · `_facade_filters`. 그리드 엔진/필터 레이아웃을 구조적으로
바꾸기 전, 이 네 함수의 현재 계약을 고정한다(비회귀 그물).

로컬 sample 모드에서만 동작하며 Supabase 에 접속하지 않는다. `db.get_departments`/
`db.get_users` 는 통제된 DataFrame 으로 monkeypatch 한다(scripts/test_login_auth.py
의 `db.get_users = lambda *a, **k: fake` 관행을 따름 — near_miss_view 는
`from modules import db` 로 같은 모듈 객체를 참조하므로 monkeypatch 가 그대로 반영된다).

실행: C:\\dev\\workops\\.venv\\Scripts\\python.exe scripts/test_near_miss_view.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"  # Supabase 미접속 보장

import pandas as pd  # noqa: E402

from modules import db  # noqa: E402
from views import near_miss_view as nmv  # noqa: E402
from views import workspace  # noqa: E402

PASSED = 0


def check(name: str, condition: bool) -> None:
    global PASSED
    assert condition, f"FAILED: {name}"
    PASSED += 1
    print(f"  ok - {name}")


# ---------- 통제된 부서/사용자 DataFrame (test_schedule_contracts.py 의
# PET1/PET2 dept 설정 관행을 mirror) ----------
_DEPTS_DF = pd.DataFrame([
    {"dept_code": "PET1", "dept_name": "PET1부"},
    {"dept_code": "PET2", "dept_name": "PET2부"},
    {"dept_code": "MGT", "dept_name": "경영지원"},
])
_USERS_DF = pd.DataFrame([
    {"emp_no": "1001", "name": "김철수"},
    {"emp_no": "1002", "name": "이영희"},
])


def test_scope_for() -> None:
    print("_scope_for (fail-closed 접근 범위)")
    orig_get_departments = db.get_departments
    db.get_departments = lambda *a, **k: _DEPTS_DF  # type: ignore[assignment]
    try:
        # MANAGER + 유효 dept_code → scoped
        scope, dept, names = nmv._scope_for({"role": "MANAGER", "dept_code": "PET1"})
        check("MANAGER 유효 dept → scoped", scope == "scoped")
        check("MANAGER 유효 dept → manager_dept == 'PET1'", dept == "PET1")
        check("MANAGER 유효 dept → dept_names 채워짐", names == {
            "PET1": "PET1부", "PET2": "PET2부", "MGT": "경영지원",
        })

        # MANAGER + 빈 dept_code("") → blocked
        r = nmv._scope_for({"role": "MANAGER", "dept_code": ""})
        check("MANAGER 빈 dept('') → blocked", r == ("blocked", None, {}))

        # MANAGER + None dept_code → blocked
        r = nmv._scope_for({"role": "MANAGER", "dept_code": None})
        check("MANAGER dept=None → blocked", r == ("blocked", None, {}))

        # MANAGER + 존재하지 않는(삭제/오래된) dept_code → blocked, "all" 로 새지 않음
        r = nmv._scope_for({"role": "MANAGER", "dept_code": "NOPE"})
        check("MANAGER 미존재 dept('NOPE') → blocked(전체조회로 새지 않음)",
              r == ("blocked", None, {}))

        # ADMIN → all + 전체 부서맵
        scope, dept, names = nmv._scope_for({"role": "ADMIN"})
        check("ADMIN → scope == 'all'", scope == "all")
        check("ADMIN → manager_dept is None", dept is None)
        check("ADMIN → dept_names 전체", names == {
            "PET1": "PET1부", "PET2": "PET2부", "MGT": "경영지원",
        })

        # role == "USER" 且 안전담당자 → all (역할 무관 — 코드 주석 의도)
        # 주의(플래그): _scope_for 자체는 is_safety_officer 를 읽지 않는다.
        # role != "MANAGER" 이면 무조건 "all" 을 반환하므로, 안전담당자 여부와
        # 무관하게 동일 결과가 나온다 — 실제 게이트는 상위 auth.can_evaluate_near_miss
        # (render 진입 시점)에 있다. 이 테스트는 그 상위 계약을 전제로, 안전담당자
        # user-dict 모양을 그대로 사용해 _scope_for 반환값만 고정한다.
        scope, dept, names = nmv._scope_for(
            {"role": "USER", "dept_code": "", "is_safety_officer": True}
        )
        check("USER+안전담당자 → scope == 'all'(역할 무관)", scope == "all")
        check("USER+안전담당자 → manager_dept is None", dept is None)
        check("USER+안전담당자 → dept_names 전체", names == {
            "PET1": "PET1부", "PET2": "PET2부", "MGT": "경영지원",
        })
    finally:
        db.get_departments = orig_get_departments  # type: ignore[assignment]


def test_to_display() -> None:
    print("_to_display (9열 표시 변환)")
    orig_get_users = db.get_users
    orig_get_departments = db.get_departments
    db.get_users = lambda *a, **k: _USERS_DF  # type: ignore[assignment]
    db.get_departments = lambda *a, **k: _DEPTS_DF  # type: ignore[assignment]
    try:
        raw = pd.DataFrame([
            # 1) 정상 매핑(사번→이름, 부서코드→부서명, 상태/원인 라벨화)
            {
                "report_no": "NM-2026-001", "work_name": "배관 청소",
                "reporter_emp_no": "1001", "dept_code": "PET1",
                "incident_date": "2026-07-01", "proposed_grade": "B",
                "confirmed_grade": "A", "status": "EVALUATED", "cause_code": "SLIP",
            },
            # 2) 빈 값 전부 → "-" 폴백(신고자/소속/발생일/제안등급/확정등급/원인),
            #    보고번호/작업명은 폴백 없이 그대로(빈 문자열), 상태는 값이
            #    있으므로("SUBMITTED") "-" 폴백 대상 아님.
            {
                "report_no": "NM-2026-002", "work_name": "",
                "reporter_emp_no": "", "dept_code": "",
                "incident_date": "", "proposed_grade": "", "confirmed_grade": "",
                "status": "SUBMITTED", "cause_code": "",
            },
            # 3) 매핑에 없는 코드(사번/부서/상태/원인) → 원문 그대로 폴백(빈 값
            #    아니므로 "-" 아님).
            {
                "report_no": "NM-2026-003", "work_name": "지게차 이동",
                "reporter_emp_no": "9999", "dept_code": "ZZZ",
                "incident_date": "2026-07-15", "proposed_grade": "S",
                "confirmed_grade": "S", "status": "WEIRD_STATUS",
                "cause_code": "WEIRD_CAUSE",
            },
            # 4) None/NaN → 정리(clean) 후 "-" 폴백
            {
                "report_no": "NM-2026-004", "work_name": "안전모 미착용",
                "reporter_emp_no": None, "dept_code": None,
                "incident_date": None, "proposed_grade": None,
                "confirmed_grade": None, "status": "CLOSED", "cause_code": None,
            },
        ])

        out = nmv._to_display(raw)

        check(
            "출력 열 집합·순서 고정",
            list(out.columns) == [
                "보고번호", "작업명", "신고자", "소속", "발생일",
                "제안등급", "확정등급", "상태", "원인",
            ],
        )
        check("4행 유지(입력 행수 보존)", len(out) == 4)

        row1 = out.iloc[0]
        check("정상행 보고번호", row1["보고번호"] == "NM-2026-001")
        check("정상행 작업명", row1["작업명"] == "배관 청소")
        check("정상행 신고자: 사번→이름 매핑", row1["신고자"] == "김철수")
        check("정상행 소속: 코드→부서명 매핑", row1["소속"] == "PET1부")
        check("정상행 발생일", row1["발생일"] == "2026-07-01")
        check("정상행 제안등급", row1["제안등급"] == "B")
        check("정상행 확정등급", row1["확정등급"] == "A")
        check("정상행 상태: EVALUATED→평가완료", row1["상태"] == "평가완료")
        check("정상행 원인: SLIP→미끄러짐", row1["원인"] == "미끄러짐")

        row2 = out.iloc[1]
        check("빈값행 보고번호 유지(폴백 없음)", row2["보고번호"] == "NM-2026-002")
        check("빈값행 작업명 빈 문자열 유지(폴백 없음)", row2["작업명"] == "")
        check("빈값행 신고자 '-' 폴백", row2["신고자"] == "-")
        check("빈값행 소속 '-' 폴백", row2["소속"] == "-")
        check("빈값행 발생일 '-' 폴백", row2["발생일"] == "-")
        check("빈값행 제안등급 '-' 폴백", row2["제안등급"] == "-")
        check("빈값행 확정등급 '-' 폴백", row2["확정등급"] == "-")
        check("빈값행 상태(SUBMITTED→제출, '-' 아님)", row2["상태"] == "제출")
        check("빈값행 원인 '-' 폴백(빈 cause_code)", row2["원인"] == "-")

        row3 = out.iloc[2]
        check("미매핑 사번 → 원문 그대로", row3["신고자"] == "9999")
        check("미매핑 부서코드 → 원문 그대로", row3["소속"] == "ZZZ")
        check("미매핑 상태코드 → 원문 그대로", row3["상태"] == "WEIRD_STATUS")
        check("미매핑 원인코드 → 원문 그대로", row3["원인"] == "WEIRD_CAUSE")

        row4 = out.iloc[3]
        check("None 신고자 → 정리 후 '-' 폴백", row4["신고자"] == "-")
        check("None 소속 → 정리 후 '-' 폴백", row4["소속"] == "-")
        check("None 발생일 → 정리 후 '-' 폴백", row4["발생일"] == "-")
        check("None 제안등급 → 정리 후 '-' 폴백", row4["제안등급"] == "-")
        check("None 확정등급 → 정리 후 '-' 폴백", row4["확정등급"] == "-")
        check("None 원인 → 정리 후 '-' 폴백", row4["원인"] == "-")
        check("None 아닌 상태(CLOSED→종결) 정상 매핑", row4["상태"] == "종결")

        # 빈 원본(0행): 예외는 없으나 현재 구현은 rows=[] 인 채 pd.DataFrame(rows) 를
        # 만들므로 0행뿐 아니라 0열(스키마 소실)이 된다 — 인벤토리에 명시되지 않은
        # 발견 사항(플래그): 구조 이관 시 "빈 결과도 9열 스키마 유지"를 새 기대로
        # 삼는다면 이건 현재 동작 대비 개선이지 회귀가 아니다. 이 테스트는 회귀
        # 방지가 목적이므로 현재의 실제 동작(0행·0열)을 그대로 고정한다.
        empty_out = nmv._to_display(pd.DataFrame(columns=list(raw.columns)))
        check(
            "빈 입력 → 예외 없이 0행(현재 구현은 열 스키마도 소실 — 플래그, 조회 시 df.empty"
            " 로 먼저 걸러지므로 render 경로에선 이 경우가 실도달하지 않음)",
            len(empty_out) == 0 and len(empty_out.columns) == 0,
        )
    finally:
        db.get_users = orig_get_users  # type: ignore[assignment]
        db.get_departments = orig_get_departments  # type: ignore[assignment]


def test_has_filters() -> None:
    print("_has_filters")
    ALL = workspace.ALL
    default_q = {
        "dept": ALL, "grade": ALL, "status": ALL, "cause": ALL,
        "period_on": False, "date_from": "", "date_to": "",
    }
    check("전부 기본값 → False", nmv._has_filters(default_q) is False)
    check("dept 만 지정 → True", nmv._has_filters({**default_q, "dept": "PET1"}) is True)
    check("grade 만 지정 → True", nmv._has_filters({**default_q, "grade": "A"}) is True)
    check("status 만 지정 → True", nmv._has_filters({**default_q, "status": "SUBMITTED"}) is True)
    check("cause 만 지정 → True", nmv._has_filters({**default_q, "cause": "JAM"}) is True)
    check("period_on 만 True → True", nmv._has_filters({**default_q, "period_on": True}) is True)
    check(
        "모두 지정 → True",
        nmv._has_filters({
            "dept": "PET1", "grade": "A", "status": "SUBMITTED", "cause": "JAM",
            "period_on": True, "date_from": "2026-01-01", "date_to": "2026-01-31",
        }) is True,
    )


def test_facade_filters() -> None:
    print("_facade_filters")
    ALL = workspace.ALL
    default_q = {
        "dept": ALL, "grade": ALL, "status": ALL, "cause": ALL,
        "period_on": False, "date_from": "", "date_to": "",
    }
    check("전부 기본값 → 빈 dict", nmv._facade_filters(default_q) == {})

    check(
        "dept → dept_code",
        nmv._facade_filters({**default_q, "dept": "PET1"}) == {"dept_code": "PET1"},
    )
    check(
        "grade → confirmed_grade",
        nmv._facade_filters({**default_q, "grade": "A"}) == {"confirmed_grade": "A"},
    )
    check(
        "status → status(코드 그대로)",
        nmv._facade_filters({**default_q, "status": "SUBMITTED"}) == {"status": "SUBMITTED"},
    )
    check(
        "cause → cause_code",
        nmv._facade_filters({**default_q, "cause": "JAM"}) == {"cause_code": "JAM"},
    )
    check(
        "date_from/date_to → 그대로 통과",
        nmv._facade_filters({**default_q, "date_from": "2026-01-01", "date_to": "2026-01-31"})
        == {"date_from": "2026-01-01", "date_to": "2026-01-31"},
    )
    check(
        "빈 date_from/date_to는 제외",
        "date_from" not in nmv._facade_filters(default_q)
        and "date_to" not in nmv._facade_filters(default_q),
    )
    check(
        "복합: dept+grade+status+cause+기간 전부 결합",
        nmv._facade_filters({
            "dept": "PET1", "grade": "A", "status": "SUBMITTED", "cause": "JAM",
            "period_on": True, "date_from": "2026-01-01", "date_to": "2026-01-31",
        }) == {
            "dept_code": "PET1", "confirmed_grade": "A", "status": "SUBMITTED",
            "cause_code": "JAM", "date_from": "2026-01-01", "date_to": "2026-01-31",
        },
    )


def main() -> int:
    for test in (
        test_scope_for,
        test_to_display,
        test_has_filters,
        test_facade_filters,
    ):
        test()
    print(f"\nALL PASSED ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
