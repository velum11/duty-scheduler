"""기준정보 4개 화면 렌더 회귀 + 조/근무형태 저장 전 검증 (sample 모드).

로컬 sample 모드에서만 동작하며 Supabase 에 접속하지 않는다. AG Grid 는 AppTest 가
셀 편집 이벤트를 제공하지 않으므로, 화면 렌더링은 AppTest 로(예외 없음), 저장 전
변환/검증은 순수 함수로 검증한다. 그리드 편집 계약(행 추가/붙여넣기/선택/삭제)의
상세 검증은 scripts/test_master_and_views.py 를 참조.

실행: python scripts/test_master_forms.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

import pandas as pd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

PASSED = 0


def check(name: str, condition: bool) -> None:
    global PASSED
    assert condition, f"FAILED: {name}"
    PASSED += 1
    print(f"  ok - {name}")


# AppTest.from_function 은 클로저를 지원하지 않으므로 화면별 top-level 함수를 둔다.
def _screen_users():
    from modules import db
    from views import master_users
    master_users.render(db.find_user_by_emp_no("1001"))


def _screen_departments():
    from modules import db
    from views import master_departments
    master_departments.render(db.find_user_by_emp_no("1001"))


def _screen_teams():
    from modules import db
    from views import master_teams
    master_teams.render(db.find_user_by_emp_no("1001"))


def _screen_work_types():
    from modules import db
    from views import master_work_types
    master_work_types.render(db.find_user_by_emp_no("1001"))


_SCREENS = {
    "master_users": _screen_users,
    "master_departments": _screen_departments,
    "master_teams": _screen_teams,
    "master_work_types": _screen_work_types,
}


def _meta_rows(rows):
    frame = pd.DataFrame(rows)
    if "_removed" not in frame:
        frame["_removed"] = ""
    return frame


# ===== 4개 기준정보 화면 렌더 스모크 (예외 없음) =====
def test_master_render_smoke() -> None:
    print("기준정보 4개 화면 렌더 스모크")
    for page, fn in _SCREENS.items():
        at = AppTest.from_function(fn, default_timeout=45).run()
        check(f"{page} 렌더 예외 없음", not at.exception)


# ===== 조 관리 저장 전 검증 (신 시그니처) =====
def test_team_validate() -> None:
    print("조 관리 - 저장 전 변환/검증 (신형 selectable grid)")
    from views import master_teams
    disp_of, code_of = master_teams._dept_maps()
    d1 = next(iter(code_of.values()))
    label = disp_of[d1]
    recs, errors = master_teams._validate(_meta_rows([
        {"부서": label, "조코드": "A", "조명": "A조", "표시순서": "1", "사용": True},
        {"부서": label, "조코드": "A", "조명": "중복", "표시순서": "2", "사용": True},
    ]))
    check("표시명이 dept_code 로 변환", recs and recs[0]["dept_code"] == d1)
    check("같은 부서 내 조코드 중복 차단", any("중복" in e for e in errors))


# ===== 근무형태 관리 저장 전 검증 =====
def test_work_type_validate() -> None:
    print("근무형태 관리 - 저장 전 검증 (색상 HEX 보존)")
    from views import master_work_types
    recs, errors = master_work_types._validate(_meta_rows([
        {"코드": "WX", "명칭": "테스트", "분류": "주간", "약칭": "테", "시작": "", "종료": "",
         "색상": "#AABBCC", "실근무": True, "특근수당": False, "설명": "", "표시순서": "1", "사용": True},
        {"코드": "", "명칭": "", "분류": "", "약칭": "약", "시작": "", "종료": "", "색상": "",
         "실근무": False, "특근수당": False, "설명": "", "표시순서": "", "사용": True},
    ]))
    check("색상 HEX 보존", recs and recs[0]["color"] == "#AABBCC")
    check("필수 코드 누락 차단", any("코드" in e for e in errors))


# ===== 앱 라우팅 회귀 =====
def test_app_routing() -> None:
    print("app.py 라우팅 회귀 (로그인 상태 주입)")
    from modules import db
    user = db.find_user_by_emp_no("1001")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=45)
    at.session_state["user"] = user
    for page in ("master_departments", "master_teams", "master_users",
                 "master_work_types", "schedule_view", "my_schedule"):
        at.session_state["nav_page"] = page
        at.run()
        check(f"{page} 라우팅 예외 없음", not at.exception)


def main() -> int:
    for test in (
        test_master_render_smoke,
        test_team_validate,
        test_work_type_validate,
        test_app_routing,
    ):
        test()
    print(f"\nALL PASSED ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
