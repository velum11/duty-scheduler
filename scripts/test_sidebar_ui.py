"""사이드바 명칭·버튼 가시성 정리 회귀 테스트 (sample, AppTest + 소스 정적).

- 상단 제목 "교대 근무표", "생산 근무표"/"WORKFORCE" 사이드바 문자열 제거
- 접기(sb_hide)·로그아웃(btn_logout) 버튼 렌더 유지
- ADMIN/MANAGER App Shell 렌더, USER 전용 헤더 회귀 없음
- 메뉴 라우팅·로그아웃·펼침/접힘 session_state 계약 불변

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_sidebar_ui.py
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

from streamlit.testing.v1 import AppTest  # noqa: E402

from modules import db, ui  # noqa: E402

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


def _first(role: str):
    users = db.get_users()
    match = users[users["role"].astype(str).str.upper() == role]
    return db.find_user_by_emp_no(str(match.iloc[0]["emp_no"])) if not match.empty else None


ADMIN = _first("ADMIN") or db.find_user_by_emp_no("1001")
MANAGER = _first("MANAGER")
USER = _first("USER")


def _render(user):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=45)
    at.session_state["user"] = user
    at.session_state["nav_page"] = "dashboard"
    return at.run()


# ===== 1) 브랜드 문자열 (소스 정적 — 표시 명칭만, 공식 APP_NAME 은 불변) =====
print("사이드바 브랜드 문자열")
brand_src = inspect.getsource(ui._sidebar_brand)
check("사이드바 브랜드에 '교대 근무표' 존재", "교대 근무표" in brand_src)
check("사이드바 브랜드에 '생산 근무표' 제거", "생산 근무표" not in brand_src)
ui_src = inspect.getsource(ui)
check("ui.py 전체에서 'WORKFORCE' 제거", "WORKFORCE" not in ui_src)
check("ui.py 에서 부제 클래스 'sb-title-en' 제거", "sb-title-en" not in ui_src)
# 공식 앱 명칭은 그대로 유지 (확대 변경 금지)
from modules import config  # noqa: E402
check("공식 APP_NAME('생산 근무표 관리') 불변", config.APP_NAME == "생산 근무표 관리")


# ===== 2) ADMIN App Shell 렌더 + 버튼 유지 =====
print("ADMIN App Shell 렌더")
at = _render(ADMIN)
check("ADMIN 렌더 예외 없음", not at.exception)
md_values = " ".join(m.value for m in at.markdown)
check("렌더 결과에 '교대 근무표' 표시", "교대 근무표" in md_values)
check("렌더 결과에 'WORKFORCE' 미표시", "WORKFORCE" not in md_values)
btn_keys = {b.key for b in at.button}
check("접기 버튼(sb_hide) 렌더 유지", "sb_hide" in btn_keys)
check("로그아웃 버튼(btn_logout) 렌더 유지", "btn_logout" in btn_keys)
check("메뉴 버튼(sbs_*/sbi_*) 렌더 유지", any(str(k).startswith(("sbs_", "sbi_")) for k in btn_keys))


# ===== 3) 접힘(숨김) 상태 — 열기 버튼(sb_show) 표시, 접기 버튼 숨김 =====
print("사이드바 접힘 상태 (sb_hidden=True)")
at2 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=45)
at2.session_state["user"] = ADMIN
at2.session_state["nav_page"] = "dashboard"
at2.session_state["sb_hidden"] = True
at2.run()
check("접힘 상태 렌더 예외 없음", not at2.exception)
keys2 = {b.key for b in at2.button}
check("접힘 상태: 열기 버튼(sb_show) 표시", "sb_show" in keys2)
check("접힘 상태: 사이드바 미렌더(접기 버튼 없음)", "sb_hide" not in keys2)


# ===== 4) MANAGER App Shell 동일 동작 =====
print("MANAGER App Shell 렌더")
if MANAGER:
    atm = _render(MANAGER)
    check("MANAGER 렌더 예외 없음", not atm.exception)
    mkeys = {b.key for b in atm.button}
    check("MANAGER 접기/로그아웃 버튼 유지", "sb_hide" in mkeys and "btn_logout" in mkeys)
    check("MANAGER 렌더에 '교대 근무표'", "교대 근무표" in " ".join(m.value for m in atm.markdown))
else:
    check("MANAGER 샘플 계정 존재", False)


# ===== 5) USER 전용 헤더 회귀 없음 =====
print("USER 전용 헤더 (회귀 없음)")
if USER:
    atu = _render(USER)
    check("USER 렌더 예외 없음", not atu.exception)
    ukeys = {b.key for b in atu.button}
    check("USER 는 사이드바 접기 버튼 없음(전용 헤더)", "sb_hide" not in ukeys)
    check("USER 전용 로그아웃(btn_logout_user) 유지", "btn_logout_user" in ukeys)
else:
    check("USER 샘플 계정 존재", False)


# ===== 6) 계약 불변 (소스) — 로그아웃 동작·펼침/접힘 키 =====
print("동작 계약 불변")
check("로그아웃은 auth.logout 로 처리(apply_nav)", "auth.logout()" in inspect.getsource(ui.apply_nav))
check("접기 버튼이 sb_hidden=True 설정", "sb_hidden = True" in inspect.getsource(ui._sidebar_brand))
check("열기 버튼이 sb_hidden=False 설정", "sb_hidden = False" in inspect.getsource(ui._breadcrumb_header))
check("로그아웃 버튼이 request_nav(logout) 유지", '"type": "logout"' in inspect.getsource(ui._sidebar_user_card))


# ===== 7) 심플 아이콘 스타일 계약 (칩/전체폭/텍스트/구분선 제거) =====
print("심플 아이콘 스타일 계약")
card_src = inspect.getsource(ui._sidebar_user_card)
# 로그아웃: 텍스트 없는 아이콘 전용, 카드 우측 컬럼 배치
check("로그아웃 텍스트 버튼 없음(icon-only)", 'st.button("로그아웃"' not in card_src)
check("로그아웃 아이콘 버튼(btn_logout) 존재",
      'icon=":material/logout:", key="btn_logout"' in card_src)
check("로그아웃이 전체폭(width=stretch) 아님", 'width="stretch"' not in card_src)
check("로그아웃이 사용자 카드 우측 컬럼 배치", "st.columns" in card_src)
check("접기 버튼(sb_hide) 아이콘 존재", 'key="sb_hide"' in inspect.getsource(ui._sidebar_brand))
check("열기 버튼(sb_show) 아이콘 존재", 'key="sb_show"' in inspect.getsource(ui._breadcrumb_header))
# 사용자 정보-로그아웃 구분선 제거 (직전 버전의 separator)
check("사용자 카드 구분선 제거", "border-bottom: 1px solid rgba(255, 255, 255, 0.07)" not in ui_src)
# 세 아이콘 버튼 기본 투명 배경 + hover + focus-visible (CSS)
check("세 버튼 기본 투명 배경(>=3)", ui_src.count("background: transparent !important") >= 3)
check("세 버튼 focus-visible 아웃라인(>=3)", ui_src.count("focus-visible") >= 3)
check("세 버튼 hover 옅은 배경(rgba 반투명)", ui_src.count("button:hover") >= 3)
# 큰 칩 흔적(진한 테두리 rgba .10/.14 기본 배경) 제거
check("접기 버튼 기본 칩 배경(rgba .05) 제거",
      "background: rgba(255, 255, 255, 0.05) !important" not in ui_src)
check("열기 버튼 기본 칩 배경(rgba 27 .05) 제거",
      "background: rgba(27, 27, 29, 0.05) !important" not in ui_src)
# 렌더 결과: 로그아웃 버튼 라벨이 비어 있음(아이콘 전용).
# 참고: help="로그아웃"(툴팁/aria-label)은 접근성상 필수라 유지 — 시각 텍스트 라벨만 없음.
logout_btn = next((b for b in at.button if b.key == "btn_logout"), None)
check("렌더: btn_logout 라벨 비어 있음(아이콘 전용, 툴팁은 유지)",
      logout_btn is not None and (logout_btn.label or "") == "")


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
