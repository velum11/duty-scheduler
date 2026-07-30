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


# ===== 3) 접힘(66px 레일) 상태 — 펼치기 버튼 + 모듈 글리프 + 로그아웃, 접기 버튼 없음 =====
# DESIGN §4: 완전 숨김이 아니라 66px 레일로 전환(모듈 2글자 글리프·브랜드·유저 세로 스택).
print("사이드바 접힘 레일 상태 (sb_collapsed=True)")
at2 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=45)
at2.session_state["user"] = ADMIN
at2.session_state["nav_page"] = "dashboard"
at2.session_state["sb_collapsed"] = True
at2.run()
check("레일 상태 렌더 예외 없음", not at2.exception)
keys2 = {b.key for b in at2.button}
check("레일: 펼치기 버튼(sb_expand) 표시", "sb_expand" in keys2)
check("레일: 모듈 글리프 버튼(sbr_*) 표시", any(str(k).startswith("sbr_") for k in keys2))
check("레일: 로그아웃(btn_logout) 유지", "btn_logout" in keys2)
check("레일: 확장형 접기 버튼(sb_hide) 미표시", "sb_hide" not in keys2)
check("레일: 확장형 리프/그룹(sbi_/sbg_) 미표시",
      not any(str(k).startswith(("sbi_", "sbg_")) for k in keys2))


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
check("접기 버튼이 sb_collapsed=True 설정(66px 레일)", "sb_collapsed = True" in inspect.getsource(ui._sidebar_brand))
check("펼치기 버튼이 sb_collapsed=False 설정(레일 내부)", "sb_collapsed = False" in inspect.getsource(ui._sidebar_rail))
check("로그아웃 버튼이 request_nav(logout) 유지", '"type": "logout"' in inspect.getsource(ui._sidebar_user_card))
# 레일 라우팅·접근성 계약: 모듈 글리프는 help(tooltip/접근성 이름) 필수, route 는 request_nav 재사용
rail_src = inspect.getsource(ui._sidebar_rail)
check("레일 모듈 글리프에 help(접근성 이름) 필수", "help=g[\"label\"]" in rail_src or "help=g['label']" in rail_src)
check("레일 단독 모듈은 request_nav 로 이동(가드 준수)", "request_nav" in rail_src)
check("레일 다자식 모듈은 펼침+그룹 오픈(라우팅 변경 아님)", "sb_grp_" in rail_src)


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
check("펼치기 버튼(sb_expand) 아이콘 존재(레일)", 'key="sb_expand"' in inspect.getsource(ui._sidebar_rail))
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


# ===== 8) Claude Design 다크 메뉴트리 (다크 토큰·활성 밝은텍스트+선택배경·접이식·검색) =====
# 계약 의도 보존: 트리 구조·검색·접이식·활성 표기·즐겨찾기 제외는 그대로, 팔레트만
# KPtech 라이트 → Claude Design 다크(ADOPTION_SPEC 정본)로 갱신. 보조 텍스트 대비 ≥4.5:1.
print("Claude Design 다크 메뉴트리 계약")
shell_css = ui._SHELL_CSS
# 다크 팔레트 토큰(ADOPTION_SPEC) — 라이트 KPtech 토큰 제거
check("사이드바 배경 다크 #1a1917", "--sb-col-bg: #1a1917" in shell_css)
check("구분선 #2b2925", "--sb-border: #2b2925" in shell_css)
check("선택 배경 #2f2c26", "--sb-sel-bg: #2f2c26" in shell_css)
check("기본 텍스트 #a49d92(6.54:1)", "--sb-text: #a49d92" in shell_css)
check("보조 dim #9a9284(≥4.5:1 실측 5.70)", "--sb-text-dim: #9a9284" in shell_css)
check("선택 텍스트 #fdf3ec", "--sb-sel-text: #fdf3ec" in shell_css)
check("액센트 오렌지 #c2410c", "--sb-accent: #c2410c" in shell_css)
check("검색 placeholder 전용 #8b857c", "--sb-placeholder: #8b857c" in shell_css)
check("라이트 KPtech 컬럼(#F5F5F5) 제거", "#F5F5F5" not in shell_css)
check("파랑 활성색(#1466C4) 제거", "#1466C4" not in shell_css)
check("골드 로고 그라데이션 제거", "linear-gradient(135deg, #D5B27C" not in shell_css)
check("테마 준비 토큰 주석", "이 토큰 블록만 오버라이드" in shell_css)
# 활성 리프 = 밝은 텍스트 + 굵게 + 선택 배경 강조
check("활성 리프 밝은텍스트+굵게+선택배경",
      'div[class*="st-key-sbi_"] div.stButton > button[kind="primary"] {' in shell_css
      and "color: var(--sb-sel-text) !important; font-weight: 700; background: var(--sb-sel-bg)" in shell_css)
# DESIGN §4·§7: 폴더 아이콘 제거 → 모듈 6px 사각 마크 + 캐럿, 리프 5px 점(가이드선 제거)
check("폴더 아이콘 제거(§7) — 폴더 SVG 경로 없음", "M3 7a2 2 0 0 1 2-2" not in shell_css)
check("모듈 6px 사각 마크(::before)",
      'st-key-sbg_"] div.stButton > button::before' in shell_css
      and "flex: 0 0 6px; width: 6px; height: 6px; border-radius: 2px" in shell_css
      and "background: var(--sb-mark)" in shell_css)
check("활성 모듈 마크 오렌지(--sb-accent)",
      'button[kind="primary"]::before' in shell_css and "background: var(--sb-accent)" in shell_css)
check("모듈 세미볼드(600)", "font-weight: 600; color: var(--sb-text)" in shell_css)
check("리프 5px 점(::before, 가이드선 아님)",
      'st-key-sbi_"] div.stButton > button::before' in shell_css
      and "flex: 0 0 5px; width: 5px; height: 5px; border-radius: 50%" in shell_css)
check("가이드선 제거(--sb-guide 토큰·border-left 없음)",
      "--sb-guide" not in shell_css and "border-left: 1px solid var(--sb-guide)" not in shell_css)
check("리프 들여쓰기 그룹보다 깊음(pad-left 18 vs 그룹 12)",
      "padding: 0 12px 0 18px" in shell_css and "padding: 0 12px 0 12px" in shell_css)
check("마크·점 토큰(--sb-mark/--sb-dot)·캐럿 토큰(--sb-icon)",
      "--sb-mark:" in shell_css and "--sb-dot:" in shell_css and "--sb-icon:" in shell_css)
check("활성 리프 오렌지 점 + 좌측 오렌지 바",
      'st-key-sbi_"] div.stButton > button[kind="primary"]::before' in shell_css
      and "box-shadow: inset 2px 0 0 var(--sb-accent)" in shell_css)
# 접이식 그룹 캐럿 › 회전(닫힘 0deg / 열림 90deg)
check("그룹 캐럿 › 회전(닫힘 0deg / 열림 90deg)",
      "\\203A" in shell_css and "rotate(0deg)" in shell_css
      and "rotate(90deg)" in shell_css and "_grpopen" in shell_css)
# 66px 레일 CSS 계약 — 폭 66px + 모듈 글리프 히트영역 + 세로 스택
check("레일 폭 66px 전환", "_RAIL_CSS" in ui_src and "width: 66px !important" in ui._RAIL_CSS)
check("레일 모듈 글리프 히트영역(≥40px)", "st-key-sbr_" in ui._RAIL_CSS and "height: 44px" in ui._RAIL_CSS)
check("레일 세로 스택(브랜드 W·유저 아바타)",
      "sb-rail-logo" in ui._RAIL_CSS and "sb-rail-ava" in ui._RAIL_CSS)
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

# ===== 9) 상단 52px 아이콘 헤더 + 페이지 타이틀 크롬 (파랑 밴드 제거) =====
# 계약 의도 보존: 헤더 크롬 클래스(ms-head/ms-title)는 유지하되, 파랑 타이틀 밴드는 제거하고
# 25px 제목 크롬으로 통일(항목5). 브레드크럼·연결 pill 은 상단 52px 헤더가 소유(항목4).
print("상단 52px 헤더 + 타이틀 크롬 계약")
from views import master as _master  # noqa: E402
head_src = inspect.getsource(_master.master_screen_head)
mstyle = _master.style._PAGE_CSS
check("헤더 계약 클래스 유지(ms-head/ms-title)",
      "ms-head" in head_src and "ms-title" in head_src)
check("파랑 밴드 토큰(#0F6FCB) 제거", "#0F6FCB" not in mstyle)
check("제목 25px/600(-0.025em) 다크 잉크",
      "font-size:25px; font-weight:600" in mstyle and "color:var(--ms-ink)" in mstyle
      and "letter-spacing:-.025em" in mstyle)
check("설명 13.5px 크롬", "font-size:13.5px" in mstyle)
check("본문 브레드크럼(.ms-crumb) 숨김(상단 헤더가 소유)", ".ms-crumb { display:none;" in mstyle)
check("중립 액션 스트립 토큰(파랑 아님)", "--ms-band:#fbfaf8" in mstyle)
# 상단 52px 헤더(modules/ui.py) — MODULE / SCREEN 모노 브레드크럼 + 연결 pill
hdr_src = inspect.getsource(ui._breadcrumb_header)
check("상단 헤더 모노 브레드크럼(crumb-mod/crumb-scr)",
      "crumb-mod" in hdr_src and "crumb-scr" in hdr_src)
check("상단 헤더 연결 pill 렌더", "_conn_pill_html" in hdr_src)
check("연결 pill 데이터모드 신호(샘플/Supabase)",
      "샘플 데이터" in inspect.getsource(ui._conn_pill_html)
      and "Supabase 연결" in inspect.getsource(ui._conn_pill_html))
check("헤더 실기능 아이콘(새로고침) — 전역 저장/삭제 아님",
      'key="app_refresh"' in hdr_src and "__save" not in hdr_src and "__del" not in hdr_src)
check("헤더 바 52px + hover #f1eee8", ".st-key-app_header" in shell_css
      and "min-height: 52px" in shell_css and "#f1eee8" in shell_css)
# 렌더: 상단 헤더에 새로고침 버튼(app_refresh) 존재
check("렌더: 상단 헤더 새로고침 버튼(app_refresh)",
      any(b.key == "app_refresh" for b in at.button))


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
