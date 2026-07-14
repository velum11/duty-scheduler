"""부서 폼과 조 편집 그리드의 회귀 검증.

로컬 sample 모드에서만 동작하며 Supabase 에 접속하지 않는다. TEST_* 자연키만 쓰고
sample 세션 스토어는 AppTest 인스턴스에만 존재하므로 실제 기초 데이터를 건드리지 않는다.
실행: python scripts/test_master_forms.py

조 관리의 AgGrid는 Streamlit AppTest가 셀 편집 이벤트를 제공하지 않으므로,
화면 렌더링은 AppTest로, 저장 전 변환·검증은 순수 함수 테스트로 검증한다.
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


# --- AppTest 하니스 (로그인 UI 없이 관리자로 화면만 렌더) ---
def _dep_screen() -> None:
    from modules import db
    from views import master_departments
    master_departments.render(db.find_user_by_emp_no("1001"))


def _team_screen() -> None:
    from modules import db
    from views import master_teams
    master_teams.render(db.find_user_by_emp_no("1001"))


def _submit(at):
    for button in at.button:
        if button.key and button.key.startswith("FormSubmitter:"):
            return button.click().run()
    raise AssertionError("form submit button not found")


def _inject_dept(at, code, name, order=90, active=True):
    """sample 스토어와 폼 상태에 TEST 부서를 주입해 '선택된' 상태를 만든다."""
    store = at.session_state["store_departments"]
    row = {"dept_code": code, "dept_name": name, "sort_order": order, "is_active": active}
    at.session_state["store_departments"] = pd.concat(
        [store, pd.DataFrame([row])], ignore_index=True)
    at.session_state["md_editing"] = code
    at.session_state["md_f_code"] = code
    at.session_state["md_f_name"] = name
    at.session_state["md_f_order"] = order
    at.session_state["md_f_active"] = active
    return at.run()


# ===== 부서 관리 =====
def test_dept_new() -> None:
    print("부서 관리 — 신규 등록 (한글 입력)")
    at = AppTest.from_function(_dep_screen, default_timeout=30).run()
    check("초기 렌더 예외 없음", not at.exception)
    check("목록 그리드 1개", len(at.dataframe) == 1)
    check("신규 모드 기본값", at.session_state["md_editing"] is None)

    at.text_input(key="md_f_code").set_value("TEST_DEPT_1")
    at.text_input(key="md_f_name").set_value("PET생산부")
    at.number_input(key="md_f_order").set_value(97)
    at = _submit(at)
    check("신규 저장 예외 없음", not at.exception)
    store = at.session_state["store_departments"]
    row = store[store["dept_code"] == "TEST_DEPT_1"]
    check("신규 부서 저장됨", len(row) == 1)
    check("한글 부서명 보존", row.iloc[0]["dept_name"] == "PET생산부")


def test_dept_edit() -> None:
    print("부서 관리 — 기존 수정 (한글 명칭 변경)")
    at = AppTest.from_function(_dep_screen, default_timeout=30).run()
    at = _inject_dept(at, "TEST_DEPT_2", "임시부서")
    at.text_input(key="md_f_name").set_value("생산관리부")
    at = _submit(at)
    store = at.session_state["store_departments"]
    row = store[store["dept_code"] == "TEST_DEPT_2"]
    check("수정 반영", len(row) == 1 and row.iloc[0]["dept_name"] == "생산관리부")


def test_dept_delete() -> None:
    print("부서 관리 — 삭제(비활성)")
    at = AppTest.from_function(_dep_screen, default_timeout=30).run()
    at = _inject_dept(at, "TEST_DEPT_3", "삭제대상")
    at.button(key="md_del").click().run()
    store = at.session_state["store_departments"]
    row = store[store["dept_code"] == "TEST_DEPT_3"]
    check("삭제(비활성) 반영", len(row) == 1 and not bool(row.iloc[0]["is_active"]))
    check("삭제 후 신규 모드 복귀", at.session_state["md_editing"] is None)


def test_dept_validation() -> None:
    print("부서 관리 — 필수값 누락 차단")
    at = AppTest.from_function(_dep_screen, default_timeout=30).run()
    at.text_input(key="md_f_code").set_value("TEST_DEPT_9")
    at.text_input(key="md_f_name").set_value("")
    at = _submit(at)
    check("오류 메시지 표시", len(at.error) >= 1)
    store = at.session_state["store_departments"]
    check("차단 시 미저장", store[store["dept_code"] == "TEST_DEPT_9"].empty)


# ===== 조 관리 (AgGrid) =====
def test_team_grid() -> None:
    print("조 관리 — AgGrid 렌더 및 저장 전 검증")
    at = AppTest.from_function(_team_screen, default_timeout=30).run()
    check("초기 렌더 예외 없음", not at.exception)
    from views import master_teams

    labels = master_teams._dept_labels({"D1": "생산부", "D2": "생산부"})
    edited = pd.DataFrame([
        {"부서": labels["D1"], "조코드": "A", "조명": "A조", "표시순서": 1, "사용": True},
        {"부서": labels["D2"], "조코드": "A", "조명": "A조", "표시순서": 2, "사용": True},
    ])
    records, errors = master_teams._validate(
        edited, {label: code for code, label in labels.items()}
    )
    check("동명 부서도 코드별로 구분", not errors and [r["dept_code"] for r in records] == ["D1", "D2"])

    duplicate = pd.concat([edited.iloc[[0]], edited.iloc[[0]]], ignore_index=True)
    _, errors = master_teams._validate(duplicate, {label: code for code, label in labels.items()})
    check("같은 부서 내 조코드 중복 차단", any("중복" in error for error in errors))


# ===== 앱 라우팅 회귀 =====
def test_app_routing() -> None:
    print("app.py 라우팅 회귀 (로그인 상태 주입)")
    from modules import db
    user = db.find_user_by_emp_no("1001")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.session_state["user"] = user
    at.session_state["nav_page"] = "master_departments"
    at.run()
    check("부서 관리 라우팅 예외 없음", not at.exception)
    at.session_state["nav_page"] = "master_teams"
    at.run()
    check("조 관리 라우팅 예외 없음", not at.exception)
    at.session_state["nav_page"] = "master_users"
    at.run()
    check("사용자 관리 라우팅 예외 없음", not at.exception)


def main() -> int:
    for test in (
        test_dept_new, test_dept_edit, test_dept_delete, test_dept_validation,
        test_team_grid,
        test_app_routing,
    ):
        test()
    print(f"\nALL PASSED ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
