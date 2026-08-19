"""모바일 우선 개인 근무표 조회 화면."""
# DESIGN.md §0 화면 유형 규약 — 조회형.
SCREEN_ARCHETYPE = "READ_VIEW"

import calendar
from datetime import date
from functools import partial
from html import escape

import pandas as pd
import streamlit as st

from modules import db
from views.common import erp
from views.common import scaffold
from views.workspace import work_type_display


_MONTH_KEY = "my_schedule_month"
_MODE_KEY = "my_schedule_mode"
# 달력 셀 표시 방식(2026-08-11 사용자 요구 재정의) — 두 모드 모두 근무형태 기준정보가
# 원천이다: 약칭 = work_types.short_label, 명칭 = work_types.name. 색상도 두 모드 모두
# 근무형태 관리의 색(work_types.color)을 그대로 쓴다(그룹 대표색 접기 폐기).
_MODE_SHORT = "약칭"
_MODE_NAME = "명칭"
_GROUP_ORDER = ("주간", "야간", "OFF", "휴가")
# 합계 dot 색 — DESIGN §1.3 의미 색의 글자값(진행·정보 #2f4d99 / 부정·반려 #9c3232 /
# 비활성·장식 #8b857c / 완료·정상 #2f6b45)을 주·야·OFF·휴가에 매핑한 것이다. 근무 chip 은
# 개별 근무형태 DB hex 를 쓰지만, 합계는 그룹 집계라 그룹 대표색으로 dot 을 찍는다.
# (종전 주석의 "§2 색 계열"은 색이 §2 에 있던 옛 판의 인용이다 — 현행 §2 는 화면 유형이다.)
_GROUP_COLOR = {"주간": "#2f4d99", "야간": "#9c3232", "OFF": "#8b857c", "휴가": "#2f6b45"}


def _text_on(hex_color: str) -> str:
    """근무형태 DB hex 배경 위 대비 텍스트색(흰/검) — WCAG 상대명도 기준(약칭 chip 가독)."""
    m = str(hex_color or "").strip().lstrip("#")
    if len(m) != 6:
        return "#1c1a17"
    try:
        r, g, b = (int(m[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "#1c1a17"

    def _lin(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    lum = 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)
    return "#ffffff" if (1.05 / (lum + 0.05)) >= ((lum + 0.05) / 0.05) else "#111111"

_MONTH_PICKER = partial(
    st.components.v2.component,
    "duty_month_wheel_picker",
    html="<div id='duty-month-wheel'></div>",
    css="""
    /* CCv2 shadow root 는 앱 본문 폰트를 상속받지 못한다 — 2026-08-18 실측에서 이 안의
       computed font-family 가 Arial 로 떨어졌다(호스트가 스타일 격리된다). 화면 나머지와
       같은 스택·본문 크기를 명시한다.
       --wheel-row 44px = DESIGN §1.4 cozy 히트영역 하한(§3.4 가 이 화면을 "모바일 우선"
       으로 지목한다). 휠 옵션 높이이자 스크롤 스냅 단위이며, 휠 컬럼 높이(5행)와 상하
       여백(2행)은 §1.1 간격 스케일이 아니라 이 행 높이의 정수배로 계산되는 스냅 기하다
       (§1.1 예외 — 사유: 선택 줄이 컬럼 정중앙에 오려면 여백이 정확히 정수 행이어야
       하고, JS 의 scrollTop 계산도 같은 행 높이를 쓴다). */
    #duty-month-wheel { --wheel-row:44px; min-height:var(--wheel-row); font-size:14px;
      font-family:"Pretendard","Malgun Gothic","Apple SD Gothic Neo",-apple-system,sans-serif; }
    /* 월 이동은 이 화면의 주 내비게이션이라 히트영역 우선순위가 가장 높다 → 세 버튼 모두
       44px 이상. 폭에는 고정 숫자를 주지 않는다: 좌우는 히트영역 하한이, 가운데는 아래
       ghost 라벨(표기 최대 길이)이 정한다. */
    .wheel-nav { display:inline-grid; grid-template-columns:auto auto auto; align-items:center; gap:8px; }
    .wheel-nav .previous, .wheel-nav .next { display:flex; align-items:center; justify-content:center;
      min-width:var(--wheel-row); min-height:var(--wheel-row); padding:0;
      border:1px solid #e2ddd4; border-radius:8px; background:#fff; color:#6b665d; cursor:pointer;
      font:inherit; font-size:20px; }  /* ‹› = 글리프 — 아이콘 20px 규칙 */
    .wheel-nav .previous:hover, .wheel-nav .next:hover { border-color:#cfc8bd; }
    .wheel-nav .previous:active, .wheel-nav .next:active { background:#fdf3ec; border-color:#c2410c; }
    .wheel-nav button:focus-visible { outline:2px solid #c2410c; outline-offset:2px; }
    /* 제목 폭은 "YYYY년 12월"(연·월 표기의 최대 길이)을 숨긴 ghost 로 예약한다. 종전
       minmax(118px,auto) 는 내용과 무관한 숫자였고, 폭을 내용에 맡기면 1월↔12월 한 자리
       차이로 ‹ › 위치가 달마다 흔들린다. tabular-nums 로 자릿수 폭을 고정해 ghost 가
       정확한 상한이 되게 한다(실측 근거: 4자리 연도는 어떤 값이든 같은 폭). */
    .wheel-nav .month-title { display:grid; min-height:var(--wheel-row); padding:0 8px; border:0;
      background:transparent; color:#1c1a17; cursor:pointer; font:inherit; font-size:14px;
      font-weight:600; letter-spacing:-0.02em; font-variant-numeric:tabular-nums; text-align:center; }
    .wheel-nav .month-title > span { grid-area:1/1; place-self:center; white-space:nowrap; }
    .wheel-nav .month-title .ghost { visibility:hidden; }
    .wheel-nav .month-title:hover .live { color:#b4451a; }
    .wheel-backdrop { position:fixed; inset:0; z-index:9999; display:flex; align-items:center; justify-content:center; background:rgba(28,26,23,.28); }
    .wheel-sheet { width:min(420px,calc(100vw - 32px)); border-radius:8px; background:#fbfaf8; box-shadow:0 16px 40px rgba(0,0,0,.22); padding:16px; }
    .wheel-heading { color:#1c1a17; font-size:14px; font-weight:600; text-align:center; }
    .wheel-columns { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:16px 0; }
    .wheel-column { position:relative; height:calc(var(--wheel-row) * 5); overflow:hidden; }
    .wheel-column::before, .wheel-column::after { content:''; position:absolute; z-index:1; left:0; right:0; height:calc(var(--wheel-row) * 2); pointer-events:none; }
    .wheel-column::before { top:0; background:linear-gradient(#fbfaf8 20%,rgba(251,250,248,0)); } .wheel-column::after { bottom:0; background:linear-gradient(rgba(251,250,248,0),#fbfaf8 80%); }
    .wheel-column .selection-line { position:absolute; z-index:0; top:calc(var(--wheel-row) * 2); left:0; right:0; height:var(--wheel-row); border-top:1px solid #cfc8bd; border-bottom:1px solid #cfc8bd; }
    .wheel-list { position:relative; z-index:2; height:calc(var(--wheel-row) * 5); overflow-y:auto; scroll-snap-type:y mandatory; scrollbar-width:none; padding:calc(var(--wheel-row) * 2) 0; box-sizing:border-box; } .wheel-list::-webkit-scrollbar { display:none; }
    /* 비선택 옵션 #6b665d — 종전 #a09a90 은 캔버스 대비 2.5:1 로 §1.3 이 읽는 텍스트에
       금지한 값이다(선택 항목은 #1c1a17/600 로 계속 구분된다). */
    .wheel-option { height:var(--wheel-row); scroll-snap-align:center; color:#6b665d; font-size:14px; line-height:var(--wheel-row); text-align:center; font-variant-numeric:tabular-nums; } .wheel-option.is-selected { color:#1c1a17; font-weight:600; }
    .wheel-actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; } .wheel-actions button { min-height:var(--wheel-row); padding:0 16px; border:1px solid #e2ddd4; border-radius:8px; background:#fff; color:#1c1a17; cursor:pointer; font:inherit; font-size:14px; font-weight:600; }
    .wheel-actions .confirm { border-color:#c2410c; background:#c2410c; color:#fff; }
    /* 폰 폭에서 줄이는 것은 간격뿐이다 — 히트영역 44px(§1.4)과 글자 크기(§1.2)는 좁은
       폭에서도 내리지 않는다(종전에는 여기서 30px·15px 로 내려가 계약을 깼다). */
    @media (max-width:640px) {
      .wheel-nav { gap:4px; }
      .wheel-backdrop { align-items:flex-end; } .wheel-sheet { width:100vw; border-radius:8px 8px 0 0; padding:16px; }
    }
    """,
    js="""
    export default function(component) {
      const { data, setTriggerValue, parentElement } = component;
      const root = parentElement.querySelector('#duty-month-wheel') || parentElement;
      const year = Number(data.year), month = Number(data.month);
      // ROW = CSS --wheel-row(44px, §1.4 cozy). 휠 스크롤 계산과 CSS 스냅 기하가 같은
      // 행 높이를 써야 선택 줄과 값이 어긋나지 않는다.
      const ROW = 44;
      // ghost = 이 연도에서 나올 수 있는 가장 긴 표기("YYYY년 12월"). 보이지 않지만 제목
      // 버튼의 폭을 정한다 → 달을 넘겨도 ‹ › 가 좌우로 움직이지 않는다(폭이 고정 숫자가
      // 아니라 실제 표기 최대 길이에서 나온다). aria 는 버튼 aria-label 이 담당한다.
      root.innerHTML = `<div class="wheel-nav"><button class="previous" aria-label="이전 달">‹</button><button class="month-title" aria-label="연월 선택"><span class="ghost" aria-hidden="true">${year}년 12월</span><span class="live">${year}년 ${month}월</span></button><button class="next" aria-label="다음 달">›</button></div>`;
      root.querySelector('.previous').onclick = () => setTriggerValue('month_change', { type: 'shift', offset: -1 });
      root.querySelector('.next').onclick = () => setTriggerValue('month_change', { type: 'shift', offset: 1 });
      root.querySelector('.month-title').onclick = () => openWheel();

      function openWheel() {
        const years = Array.from({ length: 21 }, (_, index) => year - 10 + index);
        const months = Array.from({ length: 12 }, (_, index) => index + 1);
        const overlay = document.createElement('div');
        overlay.className = 'wheel-backdrop';
        overlay.innerHTML = `<div class="wheel-sheet" role="dialog" aria-modal="true" aria-label="연월 선택"><div class="wheel-heading">연월 선택</div><div class="wheel-columns">${wheel('year', years, year, value => value + '년')}${wheel('month', months, month, value => value + '월')}</div><div class="wheel-actions"><button class="cancel">취소</button><button class="confirm">완료</button></div></div>`;
        root.appendChild(overlay);
        let selectedYear = year, selectedMonth = month;
        const bind = (name, initial, setValue) => {
          const list = overlay.querySelector(`[data-wheel="${name}"]`);
          const options = Array.from(list.querySelectorAll('.wheel-option'));
          const index = options.findIndex(option => Number(option.dataset.value) === initial);
          requestAnimationFrame(() => { list.scrollTop = Math.max(0, index) * ROW; mark(list, options[index]); });
          let timer;
          list.addEventListener('scroll', () => { clearTimeout(timer); timer = setTimeout(() => { const active = Math.round(list.scrollTop / ROW); const option = options[Math.max(0, Math.min(options.length - 1, active))]; if (option) { setValue(Number(option.dataset.value)); mark(list, option); } }, 80); });
        };
        bind('year', year, value => { selectedYear = value; }); bind('month', month, value => { selectedMonth = value; });
        overlay.querySelector('.cancel').onclick = () => overlay.remove();
        overlay.querySelector('.confirm').onclick = () => setTriggerValue('month_change', { type: 'select', year: selectedYear, month: selectedMonth });
        overlay.addEventListener('click', event => { if (event.target === overlay) overlay.remove(); });
      }
      function wheel(name, values, selected, label) { return `<div class="wheel-column"><div class="selection-line"></div><div class="wheel-list" data-wheel="${name}">${values.map(value => `<div class="wheel-option${value === selected ? ' is-selected' : ''}" data-value="${value}">${label(value)}</div>`).join('')}</div></div>`; }
      function mark(list, selected) { list.querySelectorAll('.wheel-option').forEach(option => option.classList.toggle('is-selected', option === selected)); }
    }
    """,
)


def _month_value() -> tuple[int, int]:
    if _MONTH_KEY not in st.session_state:
        today = date.today()
        st.session_state[_MONTH_KEY] = (today.year, today.month)
    return st.session_state[_MONTH_KEY]


def _set_month(year: int, month: int) -> None:
    st.session_state[_MONTH_KEY] = (year, month)


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    month += offset
    if month == 0:
        return year - 1, 12
    if month == 13:
        return year + 1, 1
    return year, month


def _group_counts(rows: pd.DataFrame, work_types: pd.DataFrame) -> list[tuple[str, int]]:
    type_map = {
        str(row["code"]): row.to_dict()
        for _, row in work_types.iterrows()
    }
    totals = {group: 0 for group in _GROUP_ORDER}
    for code, count in rows["work_type_code"].value_counts().items():
        group = db.classify_work_group(str(code), type_map.get(str(code), {}))
        if group:
            totals[group] += int(count)
    return [(group, count) for group, count in totals.items() if count]


def _name_display_map(work_types: pd.DataFrame, display_of: dict) -> dict:
    """명칭 모드용 코드→명칭(work_types.name) 맵.

    기준정보에 없는(미등록·소프트삭제 후 잔존) 코드는 명칭을 지어내지 않고
    약칭 표시(display_of) 또는 코드 원문으로 폴백한다. 색은 모드와 무관하게
    근무형태 관리의 색(color_of)을 그대로 쓰므로 여기서 만들지 않는다.
    """
    name_of = dict(display_of)  # 폴백: 약칭/코드
    if work_types is not None and not work_types.empty:
        for _, r in work_types.iterrows():
            code = str(r.get("code") or "").strip()
            name = str(r.get("name") or "").strip()
            if code and name:
                name_of[code] = name
    return name_of


def _styles() -> str:
    # dc.html isMySched 달력 골격 + §1.3 팔레트. 카드 없음(셀=헤어라인/틴트). 작은 의미
    # 텍스트는 #6b665d 이상(§1.3 "읽는 텍스트의 최저 대비" — 종전 주석의 "A-2" 는 DESIGN
    # 변경이력의 부록 폐기로 사라진 절이다, 2026-08-18 정정). 근무 chip·합계 dot 색은
    # 근무형태 DB hex(§1.3 도메인 색 예외 — 팔레트가 아니라 데이터다).
    return """
<style>
/* 제목 블록(브레드크럼·제목 25/600·설명 13.5·모드 배지)은 근무표 편성·월간 근무표와
   같은 공용 크롬(erp.screen_frame)이 소유한다 — 종전 .my-title 은 이 화면만의 사설
   제목이라 높이(40 vs 30)·위치(top 96.8 vs 105.9)·설명 유무가 갈렸다(2026-08-14 검수). */
/* 타이포 — §1.2 는 28/20/16/14/12 다섯 단계뿐이다. 이 화면에 흩어져 있던 12.5·13.5·
   14.5·15px 은 어느 것도 그 다섯에 없었다(2026-08-18 실측 55곳). 역할로 다시 배정한다:
   메타·라벨(사용자·소속, 보조 안내, 요일 머리, 날짜 숫자) = 12, 값(합계 수치, 근무 chip,
   전환 버튼) = 14, 대상 제목(월 표기, 연월 시트 제목) = 16. */
/* 헤더 줄: 사용자·소속(좌) | 근무형태 합계 dot(우) — 하단 헤어라인 */
.my-head { display:flex; flex-wrap:wrap; align-items:center; gap:8px 16px;
  padding:8px 0 12px; margin:0 0 4px; border-bottom:1px solid #e0dbd2; }
.my-emp { font-size:12px; color:#6b665d; line-height:1.45; }
.my-emp strong { color:#1c1a17; font-weight:600; }
/* 보조 안내 1줄 — st.caption 은 Streamlit 기본 글꼴(Source Sans)로 렌더돼 이 화면만
   본문 글꼴(IBM Plex Sans KR)에서 벗어났다(2026-08-14 실측). 다른 두 근무표 화면의
   보조 텍스트(.se-note/.sv-rotate)와 같은 역할이라 §1.2 label 12px·#4a453d 로 맞춘다. */
.my-note { font-size:12px; color:#4a453d; margin:4px 0 8px; line-height:1.4; }
.my-totals { margin-left:auto; display:flex; flex-wrap:wrap; gap:8px 16px; }
.my-total { display:inline-flex; align-items:baseline; gap:4px; white-space:nowrap; }
.my-total .dot { width:8px; height:8px; border-radius:2px; align-self:center; flex:0 0 auto; }
.my-total .lab { font-size:12px; color:#6b665d; }
.my-total .val { font-family:"Pretendard","Malgun Gothic",-apple-system,sans-serif; font-size:14px; font-weight:600;
  color:#1c1a17; font-variant-numeric:tabular-nums; }
/* 표시 방식(약칭/명칭) 전환.
   높이 — §3.4 가 이 화면을 "모바일 우선 = 밀도 cozy"로 지목하므로 44px 이상(§1.4).
     종전 32px 은 터치 하한 미달이었고 1440·390 실측이 동일해 좁은 폭 보정도 없었다.
   폭 — "두 버튼 동일 폭"(2026-08-11 사용자 요구)을 고정 숫자 대신 레이아웃으로 만든다.
     버튼 줄을 width:fit-content 그리드로 두고 열을 1fr 로 깔면 모든 열이 가장 넓은 열의
     max-content 폭으로 맞춰진다 → 폭이 실제 라벨 길이에서 나오고, 라벨이 바뀌어도 동일
     폭이 유지된다. 종전 min-width:84px 은 내용과 무관한 값이었다(실측: '약칭'='명칭'
     =24.98px @14px/400 IBM Plex Sans KR — 한글 100자 반복 폭 ÷ 100 = 12.488px/자,
     좌우 패딩 16+16 → 실제 버튼 폭 55.86px. 84px 은 28px 을 근거 없이 더 잡고 있었다).
   글자 — Streamlit 기본은 0.875rem(실측 12.25px)으로 §1.2 다섯 단계 밖이라 값 14px 로 올린다. */
.st-key-my_schedule_mode div[data-testid="stButtonGroup"] > div,
.st-key-my_schedule_mode div[data-testid="stSegmentedControl"] > div {
  display:grid; grid-auto-flow:column; grid-auto-columns:1fr; width:fit-content;
  column-gap:0; row-gap:0; }
.st-key-my_schedule_mode div[data-testid="stButtonGroup"] button,
.st-key-my_schedule_mode div[data-testid="stSegmentedControl"] button {
  min-width:0; min-height:44px; padding:0 16px; font-size:14px; justify-content:center; }
/* 라벨은 버튼 안 <p> 로 렌더되고 Streamlit 이 0.875em(실측 12.25px)을 건다 — §1.2 밖이라
   버튼과 같은 14px 로 맞춘다. 내부 span 의 gap 도 §1.1 값(8px)으로 정리한다. */
.st-key-my_schedule_mode div[data-testid="stButtonGroup"] button p,
.st-key-my_schedule_mode div[data-testid="stSegmentedControl"] button p {
  font-size:14px; margin:0; }
.st-key-my_schedule_mode div[data-testid="stButtonGroup"] button span,
.st-key-my_schedule_mode div[data-testid="stSegmentedControl"] button span { gap:8px !important; }
/* ── 상단 한 행: 월 이동(좌) + 약칭/명칭 전환(우) ─────────────────────────────
   2026-08-13 실 DOM 실측으로 확인한 사실(추정 아님):
     · st.container(key="my_toprow") 는 flex 컨테이너 자신(stHorizontalBlock)에
       .st-key-my_toprow 를 단다 → 컨테이너 선택자는 유효하다.
     · 각 위젯의 element container 에도 .st-key-<위젯 key> 가 붙는다
       (.st-key-my_schedule_wheel_picker / .st-key-my_schedule_mode).
       따라서 순번(:first/:last-child)에 기대지 않고 키 클래스로 직접 지정한다.
     · 줄바꿈의 진짜 원인은 CSS 가 아니라 CCv2 컴포넌트의 width 기본값이
       "stretch" 라서 element container 가 width:100%(1405px) 를 받은 것이다.
       flex 첫 항목이 한 줄을 통째로 먹어 전환이 다음 줄로 밀렸다.
       1차 수정은 파이썬(_month_navigation 의 width="content"), 아래 CSS 는 보강이다.
   emotion 규칙은 단일 클래스(0-1-0)라 아래 2단 선택자(0-2-0)가 !important 없이 이긴다. */
/* Streamlit 가로 컨테이너의 gap 은 0.6rem(root 14px 기준 실측 8.4px)이라 §1.1 스케일
   밖이다. gap=None 으로 넘겨도 emotion 규칙이 남아 두 클래스 선택자(0-2-0)로도 지므로
   여기서만 !important 로 §1.1 값을 확정한다(키 지정 컨테이너 한정). */
.stHorizontalBlock.st-key-my_toprow { align-items:center; flex-wrap:wrap;
  row-gap:8px !important; column-gap:8px !important; }
.st-key-my_toprow > .st-key-my_schedule_wheel_picker { flex:0 1 auto; width:fit-content;
  min-width:0; }
/* CCv2 shadow host 2겹은 emotion 으로 width:100% 가 박혀 있어 content 폭으로 낮춘다. */
.st-key-my_toprow .stBidiComponent,
.st-key-my_toprow [data-testid="stBidiComponentIsolated"] { width:fit-content; min-width:0; }
.st-key-my_toprow > .st-key-my_schedule_mode { flex:0 0 auto; width:fit-content;
  margin-left:auto; }
.my-calendar { width:100%; }
/* 7열 균등 그리드 — 요일 축은 내용 길이와 무관하게 균등해야 같은 요일이 세로로 정렬된다.
   여기서 역산 대상은 셀 폭이 아니라 그 안의 chip 이다. gap 은 §1.1 스케일(8/폰 4). */
.my-weekdays, .my-calendar-grid { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:8px; }
/* 요일 머리 = 표 헤더 역할 → §1.2 label 12px 에 헤더 굵기 600(근무표 편성·월간 표 헤더와
   같은 역할). 종전 12.5/11.5px 은 §1.2 다섯 단계 밖이었다. */
.my-weekday { font-size:12px; font-weight:600; color:#6b665d; padding:4px 0 8px; text-align:center; }
.my-weekday.sat { color:#2f4d99; } .my-weekday.sun { color:#9c3232; }
/* 셀: 카드 아님 — 투명 배경 + 헤어라인 보더, 오늘만 오렌지 보더+옅은 틴트.
   min-height 는 §1.1 예외(데이터 밀도 — 6주 × 7열이 스크롤 없이 들어가야 한다). 값은
   내용에서 역산한다: 상하 패딩 8+8 + 날짜줄 12(line-height 1) + gap 4 + chip 24 = 56 이
   내용 하한이고, 근무가 없는 날도 같은 높이를 유지하도록 72(=8의 배수)로 둔다.
   패딩·gap 자체는 §1.1 스케일 값이다. */
.my-day { min-width:0; min-height:72px; display:flex; flex-direction:column; gap:4px;
  border:1px solid #e0dbd2; border-radius:8px; padding:8px 4px; background:transparent; }
.my-day.is-today { border-color:#c2410c; background:rgba(255,255,255,.75); }
.my-day.empty { min-height:0; padding:0; border:0; }
/* 날짜 숫자 = 모노 수치(컨텍스트 줄 .se-ctx .num / .sv-ctx .num 과 같은 역할) → §1.2
   label 12px/600 모노. 선택자를 .my-day .my-date(0,2,0)로 올린다 — 단일 클래스(0,1,0)로는
   마크다운 컨테이너 본문 글꼴 규칙에 져서 모노가 sans 로 렌더됐다(2026-08-14 실측). */
.my-day .my-date { font-family:"Pretendard","Malgun Gothic",-apple-system,sans-serif; font-size:12px; font-weight:600;
  color:#6b665d; line-height:1; font-variant-numeric:tabular-nums; }
.my-day.is-sat .my-date { color:#2f4d99; } .my-day.is-sun .my-date { color:#9c3232; }
/* 근무형태 표시값 = 표 본문 역할 → §1.2 body 14px(굵기만 600 으로 올려 셀 안에서 값을
   먼저 읽게 한다). 편성·월간 그리드 셀과 같은 값이다.
   종전 값 14.5px 의 근거 주석은 "DESIGN §8-6·부속서 A-3" 을 들었으나 DESIGN 변경이력의
   부록 폐기로 그 절은 존재하지 않는다 — 현행 근거는 §1.2 다섯 단계뿐이고 14.5 는 그 안에
   없다(2026-08-18 정정).
   min-height 24px 도 내용에서 나온다: 14px × line-height 1.15 = 16.1 + 상하 패딩 4+4 =
   24.1 → §1.1 값 24.
   폭은 내용 폭이다 — align-self:center 로 셀의 남는 가로폭을 흡수하지 않는다(종전에는
   flex stretch 라 '주' 한 글자 chip 이 1440 에서 183.9px 로 늘어났다: 폭이 내용과 무관
   하게 정해지던 자리다. 남는 폭은 남긴다). 좌우 패딩 8px 은 §1.1 값이고, 상한은 셀
   안폭(max-width:100%)이며 넘치면 말줄임 + title 툴팁으로 흡수한다.
   실측 근거 @14/600 IBM Plex Sans KR: 최장 명칭 '경조(자녀결혼)' 87.39px → chip 103.4px
   < 1440 셀 안폭 185.9px. 폰(390)은 셀 안폭 41.69px 이라 좌우 패딩을 4px 로 낮춰 약칭
   최장 '야-4' 26.53px → chip 34.5px 로 말줄임 없이 들어간다. */
.my-duty { display:flex; align-items:center; justify-content:center; align-self:center;
  min-height:24px; max-width:100%; border-radius:4px; font-size:14px; font-weight:600;
  line-height:1.15; padding:4px 8px;
  min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.my-duty.is-empty { background:transparent; }
/* 폰 폭에서 줄이는 것은 간격뿐이다 — 글자 크기(§1.2)·히트영역(§1.4)은 그대로 둔다.
   chip 좌우 패딩만 8→4px 로 낮춘다: 390 실측 셀 안폭 41.69px 대비 약칭 최장
   '야-4' 26.53 + 8 = 34.5px, 'OFF' 26.13 + 8 = 34.1px 로 말줄임 없이 들어간다. */
@media (max-width:640px) {
  .my-head { padding:4px 0 8px; }
  .stHorizontalBlock.st-key-my_toprow { column-gap:4px !important; }
  .my-weekdays, .my-calendar-grid { gap:4px; } .my-weekday { padding:4px 0; }
  .my-day { min-height:58px; padding:4px; gap:4px; }
  .my-duty { padding:4px; }
}
/* 폰 가로(낮은 뷰포트): 달력이 화면을 최대로 쓰도록 상하 여백만 압축한다 — 월간 근무표
   _SV_CSS 의 같은 미디어쿼리와 동일한 규율이다(폰트·색·히트영역은 그대로, 줄이는 것은
   여백과 '한 줄 설명'뿐). 종전에는 max-width:640 만 있어 844×390 가로에서 데스크톱
   치수 그대로 렌더돼 달력이 화면 밖으로 밀렸다(2026-08-14 실측: 달력 top 259.9·높이 416). */
@media (orientation:landscape) and (max-height:540px) {
  section[data-testid="stMain"] .block-container { padding-bottom:8px !important; }
  .ms-desc { display:none !important; }
  .my-head { padding:4px 0 8px !important; margin:0 !important; }
  .my-weekday { padding:0 0 4px !important; }
  .my-weekdays, .my-calendar-grid { gap:4px !important; }
  .my-day { min-height:44px !important; padding:4px !important; gap:4px !important; }
}
</style>
"""


def _header_html(user: dict, dept: str, team: str,
                 groups: list[tuple[str, int]]) -> str:
    """헤더 줄 — 사용자·소속(좌) + 근무형태별 합계 dot·라벨·모노 수치(우, dc isMySched)."""
    name = escape(str(user.get("name", "")))
    dept = escape(str(dept))
    team = escape(str(team or "-"))
    totals = "".join(
        f"<span class='my-total'>"
        f"<span class='dot' style='background:{_GROUP_COLOR.get(group, '#8b857c')}'></span>"
        f"<span class='lab'>{escape(group)}</span>"
        f"<span class='val'>{count}일</span></span>"
        for group, count in groups
    )
    return (
        "<div class='my-head'>"
        f"<span class='my-emp'><strong>{name}</strong> · {dept} · {team}</span>"
        f"<span class='my-totals'>{totals}</span>"
        "</div>"
    )


def _calendar_html(rows: pd.DataFrame, year: int, month: int, work_types: dict,
                   display_of: dict, color_of: dict) -> str:
    first_weekday, days_in_month = calendar.monthrange(year, month)
    duty_by_date = {
        row["d"]: str(row["work_type_code"])
        for _, row in rows.drop_duplicates("d", keep="first").iterrows()
    }
    cells = ["<div class='my-day empty'></div>" for _ in range(first_weekday)]
    today = date.today()
    for day in range(1, days_in_month + 1):
        duty_date = date(year, month, day)
        code = duty_by_date.get(duty_date, "")
        label = display_of.get(code, code)  # 셀은 약칭으로 표시
        color = str(color_of.get(code) or work_types.get(code, {}).get("color") or "#9AA0A6")
        classes = ["my-day"]
        if code:
            classes.append("has-duty")
        if duty_date == today:
            classes.append("is-today")
        if duty_date.weekday() == 5:
            classes.append("is-sat")
        elif duty_date.weekday() == 6:
            classes.append("is-sun")
        # 근무 chip = 근무형태 DB hex 배경(§1.3 "도메인 색은 이 팔레트의 예외") + WCAG
        # 대비 텍스트(흰/검).
        # title: 좁은 셀에서 말줄임된 명칭의 전문을 보증한다(편성·월간 그리드의
        # tooltipField 와 같은 역할 — 길이 차이는 말줄임 + 툴팁으로 흡수).
        duty = (
            f"<span class='my-duty' title='{escape(str(label))}' "
            f"style='background:{escape(color)};color:{_text_on(color)}'>"
            f"{escape(label)}</span>"
            if code else "<span class='my-duty is-empty'>&nbsp;</span>"
        )
        cells.append(f"<div class='{' '.join(classes)}'><span class='my-date'>{day}</span>{duty}</div>")
    while len(cells) % 7:
        cells.append("<div class='my-day empty'></div>")
    weekdays = "".join(f"<div class='my-weekday'>{day}</div>" for day in ["월", "화", "수", "목", "금", "토", "일"])
    return f"<div class='my-calendar'><div class='my-weekdays'>{weekdays}</div><div class='my-calendar-grid'>{''.join(cells)}</div></div>"


def _month_navigation(year: int, month: int) -> None:
    # width="content": CCv2 기본값은 "stretch"(=element container width:100%)라서
    # 가로 컨테이너의 첫 항목이 한 줄을 다 먹고 표시 전환을 다음 줄로 밀어냈다.
    # 순번 CSS 로 덮지 않고 Streamlit 레이아웃 계약으로 content 폭을 선언한다.
    result = _MONTH_PICKER()(
        key="my_schedule_wheel_picker",
        data={"year": year, "month": month},
        on_month_change_change=lambda: None,
        width="content",
        height="content",
    )
    change = result.get("month_change")
    if not isinstance(change, dict):
        return
    if change.get("type") == "shift":
        _set_month(*_shift_month(year, month, int(change.get("offset", 0))))
        st.rerun()
    if change.get("type") == "select":
        selected_year = int(change.get("year", year))
        selected_month = int(change.get("month", month))
        if 1 <= selected_month <= 12:
            _set_month(selected_year, selected_month)
            st.rerun()
def render(user: dict) -> None:
    year, month = _month_value()
    # 기준정보 조회 실패(repository 오류)와 정상 빈 월을 구분한다:
    #  - repository 오류 → 명확한 오류 메시지 후 중단 (빈 월로 위장하지 않음)
    #  - 근무내역 없음 → 정상 빈 달력 렌더링
    try:
        rows = db.get_month_schedules(str(user["emp_no"]).strip(), year, month).copy()
        work_type_df = db.get_work_types()
        work_types = db.work_types_map()
        display_of, color_of = work_type_display()
        rows["d"] = pd.to_datetime(rows["duty_date"], errors="coerce").dt.date
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(
            "근무표 또는 기준정보를 불러오지 못했습니다(일시적 연결 문제일 수 있습니다). "
            f"잠시 후 다시 조회하세요. ({exc})"
        )
        return
    except Exception:
        st.error("근무표 또는 기준정보를 불러오지 못했습니다. 잠시 후 다시 조회하세요.")
        return

    # 소속(부서·조)은 선택 월 편성 스냅샷 우선, 없으면 users 현재 소속으로 표시 fallback.
    # 표시 전용이며 fallback 값을 저장하지 않는다. 편성 조회 실패가 근무/달력을 막지
    # 않도록 별도 try 로 감싸 users 기본값으로 안전하게 되돌린다.
    dept_code = str(user.get("dept_code", "") or "")
    team_code = str(user.get("team_code", "") or "")
    shift_code = ""  # 근무조(편성표 직접입력 텍스트) — users 마스터에는 없고 스냅샷에만 있다
    snapshot_failed = False  # U6: 편성 스냅샷 조회 실패 시 폴백 사실을 표면화(무음 금지)
    try:
        assignment = db.get_month_assignments(year, month, str(user["emp_no"]).strip())
        if not assignment.empty:
            snap = assignment.iloc[0]
            dept_code = str(snap["dept_code"]).strip() or dept_code
            team_code = str(snap["team_code"]).strip()  # NULL 조 → "" 그대로(조 없음 표시)
            shift_code = str(snap.get("shift_group_code") or "").strip()
    except Exception:  # noqa: BLE001 — 편성 조회 실패 → users 현재 소속으로 표시(근무 달력은 정상)
        snapshot_failed = True
    dept = db.dept_name(dept_code)
    # 조 표시: 신 축(근무조)이 있으면 그것, 없으면 레거시 운영단위명 폴백.
    team = shift_code or db.team_name(dept_code, team_code)

    # dc isMySched 순서: 제목 → 월 이동(‹ 월 ›) → 표시 방식(약칭/명칭) → 헤더 줄
    # (사용자·소속 | 근무형태 합계) → 7열 달력. 합계는 헤더 우측(항상 4그룹 기준).
    #
    # 제목 블록은 근무표 편성·월간 근무표와 **같은 공용 크롬**을 쓴다(브레드크럼·제목
    # 25/600·설명 13.5·데이터 모드 배지). 종전 사설 .my-title 은 설명·배지가 없고 높이·
    # 위치가 달라 세 화면을 오갈 때 제목 기준선이 흔들렸다(2026-08-14 검수). USER 셸에서도
    # 다른 USER 화면(아차사고 등록·내 아차사고 등)이 이미 이 크롬을 쓴다.
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="내 근무표",
        desc="본인 근무를 월 단위로 확인합니다.",
        breadcrumb="근무표 › 내 근무표",
        badges=scaffold.mode_badge(),
    )
    st.markdown(_styles(), unsafe_allow_html=True)
    # 구 세션 값('실제 근무'/'요약')이 남아 있으면 새 옵션과 충돌하므로 정리한다.
    if st.session_state.get(_MODE_KEY) not in (_MODE_SHORT, _MODE_NAME):
        st.session_state.pop(_MODE_KEY, None)
    # 월 이동(좌)과 약칭/명칭 전환(우)을 한 행에 — 남는 우측 공간 활용(2026-08-12 사용자 요구).
    # gap=None: Streamlit 기본 가로 gap 은 0.6rem(실측 8.4px)으로 §1.1 스케일 밖이라
    # 컨테이너 gap 을 끄고 _styles() 에서 8px(폰 4px)로 선언한다.
    with st.container(key="my_toprow", horizontal=True, gap=None,
                      vertical_alignment="center"):
        _month_navigation(year, month)
        mode = st.segmented_control(
            "표시 방식", [_MODE_SHORT, _MODE_NAME], key=_MODE_KEY,
            default=_MODE_SHORT, label_visibility="collapsed",
        )
    # 색은 두 모드 공통으로 근무형태 관리 색(color_of). 표시 텍스트만 약칭↔명칭 전환.
    display_cal, color_cal = display_of, color_of
    if mode == _MODE_NAME:
        display_cal = _name_display_map(work_type_df, display_of)
    groups = _group_counts(rows, work_type_df) if not rows.empty else []
    st.markdown(_header_html(user, dept, team, groups), unsafe_allow_html=True)
    # 보조 안내는 st.caption 대신 .my-note 로 그린다 — st.caption 은 Streamlit 기본 글꼴
    # (Source Sans)로 렌더돼 이 화면만 본문 글꼴(IBM Plex Sans KR)에서 벗어났다.
    # 문구·표시 조건은 그대로다(폰트·크기만 다른 두 근무표 화면의 보조 텍스트와 정합).
    if snapshot_failed:
        st.markdown(
            "<div class='my-note'>편성 정보를 불러오지 못해 소속을 현재 정보로 표시합니다"
            "(달력은 정상).</div>",
            unsafe_allow_html=True,
        )
    if rows.empty:
        st.markdown(
            "<div class='my-note'>해당 월에 저장된 근무내역이 없습니다.</div>",
            unsafe_allow_html=True,
        )
    st.markdown(_calendar_html(rows, year, month, work_types, display_cal, color_cal), unsafe_allow_html=True)
