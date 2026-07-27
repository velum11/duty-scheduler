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

from modules import db, nav, ui  # noqa: E402

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
admin_groups = ui._shell_groups("ADMIN")
master_children = next(g["children"] for g in admin_groups if g["id"] == "master")
check("ADMIN 기준정보 순서: 사용자→조직→근무형태",
      [c["label"] for c in master_children] == ["사용자 관리", "조직 관리", "근무형태 관리"])
check("조직 관리 메뉴는 한 번만 표시", [c["label"] for c in master_children].count("조직 관리") == 1)
check("부서 관리·조 관리 메뉴 숨김",
      not ({"부서 관리", "조 관리"} & {c["label"] for c in master_children}))
check("조직 관리 메뉴 id 고정", [c["id"] for c in master_children] == [
    "master_users", "master_org", "master_work_types",
])


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
    check("MANAGER 기존 권한 메뉴 불변", ui._shell_groups("MANAGER") == nav.visible_groups("MANAGER"))
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


# ===== 8) KPtech 라이트 메뉴트리 재구축 (실측 토큰·활성 파랑·접이식·검색·즐겨찾기 제외) =====
print("KPtech 라이트 메뉴트리 계약")
shell_css = ui._SHELL_CSS
# 실측 토큰(라이트) — 다크 팔레트 제거
check("메뉴 컬럼 토큰 #F5F5F5", "--sb-col-bg: #F5F5F5" in shell_css)
check("트리 영역 토큰 #F2F4FA", "--sb-tree-bg: #F2F4FA" in shell_css)
check("경계 0.8px #D2D2D2", "--sb-border: #D2D2D2" in shell_css and "0.8px solid var(--sb-border)" in shell_css)
check("각진(radius 0) 토큰", "--sb-radius: 0px" in shell_css)
check("활성 강조 파랑 #1466C4(대비 보정)", "--sb-accent: #1466C4" in shell_css)
check("사번 dim #6E6E6E(4.68:1)", "--sb-text-dim: #6E6E6E" in shell_css)
check("검색 placeholder 전용 #8D8D8D", "--sb-placeholder: #8D8D8D" in shell_css)
check("다크 사이드바 배경(#1B1B1D) 제거", "#1B1B1D" not in shell_css)
check("골드 로고 그라데이션 제거", "linear-gradient(135deg, #D5B27C" not in shell_css)
check("테마 준비 토큰 주석", "이 토큰 블록만 오버라이드" in shell_css)
# 활성 = 파랑 글자 + 굵게, 배경 강조 없음(KPtech 방식)
check("활성 리프 파랑+굵게",
      'div[class*="st-key-sbi_"] div.stButton > button[kind="primary"] {' in shell_css
      and "color: var(--sb-accent) !important; font-weight: 700" in shell_css)
# FIX1 — 그룹 vs 리프 계층 명확화(KPtech: 폴더 아이콘 + 들여쓰기 + 가이드선)
check("그룹 헤더 폴더 아이콘(::before)",
      'st-key-sbg_"] div.stButton > button::before' in shell_css and "M3 7a2 2 0 0 1 2-2" in shell_css)
check("그룹 헤더 세미볼드(600)로 대비 강화",
      'div[class*="st-key-sbg_"] div.stButton > button { font-weight: 600' in shell_css)
check("리프 좌측 가이드선(::before border-left)",
      'st-key-sbi_"] div.stButton > button::before' in shell_css
      and "border-left: 1px solid var(--sb-guide)" in shell_css)
check("리프 들여쓰기 그룹보다 깊음(pad-left 18 vs 그룹 10)",
      "padding: 0 12px 0 18px" in shell_css and "padding: 0 12px 0 10px" in shell_css)
check("가이드선 토큰(--sb-guide)·아이콘 토큰(--sb-icon)",
      "--sb-guide:" in shell_css and "--sb-icon:" in shell_css)
check("활성 리프 가이드선 강조색(파랑)",
      "border-left-color: var(--sb-accent)" in shell_css)
# 접이식 그룹 chevron(닫힘 ▸ / 열림 ▾)
check("그룹 chevron ▸(닫힘)", "\\25B8" in shell_css)
check("그룹 chevron ▾(열림)", "\\25BE" in shell_css and "_grpopen" in shell_css)
# 검색 상자 + 즐겨찾기 제외
nav_src = inspect.getsource(ui._sidebar_nav)
search_src = inspect.getsource(ui._sidebar_search)
check("검색 입력창(sb_search_q) 존재", 'key="sb_search_q"' in search_src)
check("검색 컨테이너(sb_search) 존재", 'key="sb_search"' in search_src)
check("접힌 그룹은 자식 미렌더(ghost 없음)", "if expanded:" in nav_src)
check("그룹 토글 세션키(sb_grp_)", "sb_grp_" in nav_src)
check("즐겨찾기 제외(sbfav_/sb_favorites 없음)",
      "sbfav_" not in ui_src and "sb_favorites" not in ui_src)
# 렌더: ADMIN 대시보드 화면 — 그룹 헤더(sbg_)와 단독항목(sbs_) 존재, 접힌 그룹 리프는 미렌더
grp_keys = {b.key for b in at.button if str(b.key).startswith("sbg_")}
check("렌더: 접이식 그룹 헤더(sbg_) 존재", bool(grp_keys))
check("렌더: 접힌 그룹 리프(sbi_) 미렌더(대시보드 활성 시)",
      not any(str(b.key).startswith("sbi_") for b in at.button))
check("렌더: 단독 최상위 항목(sbs_dashboard) 존재",
      any(b.key == "sbs_dashboard" for b in at.button))
# 검색어 입력 시 트리 필터 — '조직' 검색이면 조직 관리만, 대시보드 리프는 사라짐
ats = AppTest.from_file(str(ROOT / "app.py"), default_timeout=45)
ats.session_state["user"] = ADMIN
ats.session_state["nav_page"] = "dashboard"
ats.session_state["sb_search_q"] = "조직"
ats.run()
check("검색 렌더 예외 없음", not ats.exception)
skeys = {b.key for b in ats.button}
check("검색 '조직': 조직 관리 리프 표시", "sbi_master_org" in skeys)
check("검색 '조직': 비매칭 단독항목(대시보드) 숨김", "sbs_dashboard" not in skeys)

# ===== 9) 상단 타이틀 밴드(KPtech) — 계약 클래스 유지 + 흰 제목 밴드 =====
print("상단 타이틀 밴드 계약")
from views import master as _master  # noqa: E402
head_src = inspect.getsource(_master.master_screen_head)
mstyle = _master.style._PAGE_CSS
check("헤더 계약 클래스 유지(ms-head/ms-title/ms-mode)",
      "ms-head" in head_src and "ms-title" in head_src)
check("파랑 밴드 클래스(ms-band)", "ms-band" in head_src and ".ms-band {" in mstyle)
check("밴드 파랑 토큰 #0F6FCB(흰 제목 5.05:1)", "--ms-band:#0F6FCB" in mstyle)
check("제목 흰색·18px", "color:#FFFFFF" in mstyle and "font-size:18px" in mstyle)
check("우측 툴바 아이콘 클러스터(ms-tool)",
      "ms-tool" in inspect.getsource(_master._toolbar_html) and ".ms-tool {" in mstyle)
check("툴바를 밴드에 주입(_toolbar_html 호출)", "_toolbar_html()" in head_src)
check("모드 배지 밴드 내 유지", "badge" in head_src and "ms-band-tools" in head_src)


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
