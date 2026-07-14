"""부서/조 관리 폼 화면(한글 IME 안전 구조) AppTest 검증.

로컬 sample 모드에서만 동작하며 Supabase 에 접속하지 않는다. TEST_* 자연키만 쓰고
sample 세션 스토어는 AppTest 인스턴스에만 존재하므로 실제 기초 데이터를 건드리지 않는다.
실행: python scripts/test_master_forms.py

주의(테스트 방식): st.form 제출 핸들러에서 st.rerun 을 호출하는 화면은 AppTest 에서
한 세션에 두 번째 폼 제출이 발화하지 않는 알려진 아티팩트가 있다(실제 브라우저는 정상).
그래서 신규/수정/삭제를 각각 새 AppTest 세션 + 단일 상호작용으로 검증한다.
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


def _inject_team(at, dept_code, code, name, order=90, active=True):
    store = at.session_state["store_teams"]
    row = {"dept_code": dept_code, "team_code": code, "team_name": name,
           "sort_order": order, "is_active": active}
    at.session_state["store_teams"] = pd.concat(
        [store, pd.DataFrame([row])], ignore_index=True)
    at.session_state["mt_editing"] = (dept_code, code)
    at.session_state["mt_f_dept"] = dept_code
    at.session_state["mt_f_code"] = code
    at.session_state["mt_f_name"] = name
    at.session_state["mt_f_order"] = order
    at.session_state["mt_f_active"] = active
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


# ===== 조 관리 =====
def test_team_new() -> None:
    print("조 관리 — 신규 등록 (B조 한글, BWH 변환 방지)")
    at = AppTest.from_function(_team_screen, default_timeout=30).run()
    check("초기 렌더 예외 없음", not at.exception)
    check("목록 그리드 1개", len(at.dataframe) == 1)
    dept_code = at.selectbox(key="mt_f_dept").value

    at.text_input(key="mt_f_code").set_value("TEST_TEAM_1")
    at.text_input(key="mt_f_name").set_value("B조")
    at = _submit(at)
    check("신규 저장 예외 없음", not at.exception)
    store = at.session_state["store_teams"]
    row = store[(store["dept_code"] == dept_code) & (store["team_code"] == "TEST_TEAM_1")]
    check("신규 조 저장됨", len(row) == 1)
    check("한글 조명 보존 (B조)", row.iloc[0]["team_name"] == "B조")


def test_team_edit() -> None:
    print("조 관리 — 기존 수정")
    at = AppTest.from_function(_team_screen, default_timeout=30).run()
    dept_code = at.selectbox(key="mt_f_dept").value
    at = _inject_team(at, dept_code, "TEST_TEAM_2", "임시조")
    at.text_input(key="mt_f_name").set_value("생산1조")
    at = _submit(at)
    store = at.session_state["store_teams"]
    row = store[(store["dept_code"] == dept_code) & (store["team_code"] == "TEST_TEAM_2")]
    check("수정 반영", len(row) == 1 and row.iloc[0]["team_name"] == "생산1조")


def test_team_delete() -> None:
    print("조 관리 — 삭제(비활성)")
    at = AppTest.from_function(_team_screen, default_timeout=30).run()
    dept_code = at.selectbox(key="mt_f_dept").value
    at = _inject_team(at, dept_code, "TEST_TEAM_3", "삭제대상조")
    at.button(key="mt_del").click().run()
    store = at.session_state["store_teams"]
    row = store[(store["dept_code"] == dept_code) & (store["team_code"] == "TEST_TEAM_3")]
    check("삭제(비활성) 반영", len(row) == 1 and not bool(row.iloc[0]["is_active"]))


def test_team_validation() -> None:
    print("조 관리 — 필수값 누락 차단")
    at = AppTest.from_function(_team_screen, default_timeout=30).run()
    at.text_input(key="mt_f_code").set_value("")
    at.text_input(key="mt_f_name").set_value("조명만")
    at = _submit(at)
    check("오류 메시지 표시", len(at.error) >= 1)


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


def main() -> int:
    for test in (
        test_dept_new, test_dept_edit, test_dept_delete, test_dept_validation,
        test_team_new, test_team_edit, test_team_delete, test_team_validation,
        test_app_routing,
    ):
        test()
    print(f"\nALL PASSED ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
