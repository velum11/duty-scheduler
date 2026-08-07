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
from views.workspace import work_type_display


_MONTH_KEY = "my_schedule_month"
_GROUP_ORDER = ("주간", "야간", "OFF", "휴가")
# 합계 dot 색 — 근무형태 §2 색 계열(주=파랑·야=적·OFF=중립·휴가=녹). 근무 chip 은 개별
# 근무형태 DB hex 를 쓰지만, 합계는 그룹 집계라 그룹 대표색(§2)으로 dot 을 찍는다.
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
    #duty-month-wheel { min-height:40px; font-family:inherit; }
    .wheel-nav { display:inline-grid; grid-template-columns:30px minmax(118px, auto) 30px; align-items:center; gap:8px; }
    .wheel-nav .previous, .wheel-nav .next { height:30px; width:30px; border:1px solid #e2ddd4; border-radius:8px; background:#fff; color:#6b665d; cursor:pointer; font:inherit; font-size:13px; }
    .wheel-nav .previous:hover, .wheel-nav .next:hover { border-color:#cfc8bd; }
    .wheel-nav .month-title { height:30px; border:0; background:transparent; color:#1c1a17; cursor:pointer; font-size:16px; font-weight:600; letter-spacing:-0.02em; text-align:center; }
    .wheel-backdrop { position:fixed; inset:0; z-index:9999; display:flex; align-items:center; justify-content:center; background:rgba(28,26,23,.28); }
    .wheel-sheet { width:min(420px,calc(100vw - 32px)); border-radius:8px; background:#fbfaf8; box-shadow:0 18px 45px rgba(0,0,0,.22); padding:18px; }
    .wheel-heading { color:#1c1a17; font-size:15px; font-weight:600; text-align:center; } .wheel-columns { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:14px 0; }
    .wheel-column { position:relative; height:220px; overflow:hidden; } .wheel-column::before, .wheel-column::after { content:''; position:absolute; z-index:1; left:0; right:0; height:88px; pointer-events:none; }
    .wheel-column::before { top:0; background:linear-gradient(#fbfaf8 20%,rgba(251,250,248,0)); } .wheel-column::after { bottom:0; background:linear-gradient(rgba(251,250,248,0),#fbfaf8 80%); }
    .wheel-column .selection-line { position:absolute; z-index:0; top:88px; left:0; right:0; height:44px; border-top:1px solid #cfc8bd; border-bottom:1px solid #cfc8bd; }
    .wheel-list { position:relative; z-index:2; height:220px; overflow-y:auto; scroll-snap-type:y mandatory; scrollbar-width:none; padding:88px 0; box-sizing:border-box; } .wheel-list::-webkit-scrollbar { display:none; }
    .wheel-option { height:44px; scroll-snap-align:center; color:#a09a90; font-size:1rem; line-height:44px; text-align:center; } .wheel-option.is-selected { color:#1c1a17; font-weight:600; }
    .wheel-actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; } .wheel-actions button { min-height:38px; border:1px solid #e2ddd4; border-radius:8px; background:#fff; color:#1c1a17; cursor:pointer; font:inherit; font-weight:600; }
    .wheel-actions .confirm { border-color:#c2410c; background:#c2410c; color:#fff; }
    @media (max-width:640px) { .wheel-backdrop { align-items:flex-end; } .wheel-sheet { width:100vw; border-radius:10px 10px 0 0; padding:18px 16px 22px; } }
    """,
    js="""
    export default function(component) {
      const { data, setTriggerValue, parentElement } = component;
      const root = parentElement.querySelector('#duty-month-wheel') || parentElement;
      const year = Number(data.year), month = Number(data.month);
      root.innerHTML = `<div class="wheel-nav"><button class="previous" aria-label="이전 달">‹</button><button class="month-title" aria-label="연월 선택">${year}년 ${month}월</button><button class="next" aria-label="다음 달">›</button></div>`;
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
          requestAnimationFrame(() => { list.scrollTop = Math.max(0, index) * 44; mark(list, options[index]); });
          let timer;
          list.addEventListener('scroll', () => { clearTimeout(timer); timer = setTimeout(() => { const active = Math.round(list.scrollTop / 44); const option = options[Math.max(0, Math.min(options.length - 1, active))]; if (option) { setValue(Number(option.dataset.value)); mark(list, option); } }, 80); });
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


def _styles() -> str:
    # dc.html isMySched 달력 골격 + §2 팔레트. 카드 없음(셀=헤어라인/틴트). 작은 의미
    # 텍스트는 #6b665d 이상(A-2). 근무 chip·합계 dot 색은 근무형태 DB hex(§2 예외 SoT).
    return """
<style>
.my-title { color:#1c1a17; font-size:25px; font-weight:600; letter-spacing:-0.025em; margin:0 0 8px; }
/* 헤더 줄: 사용자·소속(좌) | 근무형태 합계 dot(우) — 하단 헤어라인 */
.my-head { display:flex; flex-wrap:wrap; align-items:center; gap:10px 16px;
  padding:8px 0 14px; margin:2px 0 4px; border-bottom:1px solid #e0dbd2; }
.my-emp { font-size:12.5px; color:#6b665d; line-height:1.45; }
.my-emp strong { color:#1c1a17; font-weight:600; }
.my-totals { margin-left:auto; display:flex; flex-wrap:wrap; gap:10px 14px; }
.my-total { display:inline-flex; align-items:baseline; gap:6px; white-space:nowrap; }
.my-total .dot { width:8px; height:8px; border-radius:3px; align-self:center; flex:0 0 auto; }
.my-total .lab { font-size:12px; color:#6b665d; }
.my-total .val { font-family:'IBM Plex Mono',monospace; font-size:13.5px; font-weight:600; color:#1c1a17; }
.my-calendar { width:100%; }
.my-weekdays, .my-calendar-grid { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:6px; }
.my-weekday { font-size:11.5px; font-weight:600; color:#6b665d; padding:6px 0 8px; text-align:center; }
.my-weekday.sat { color:#2f4d99; } .my-weekday.sun { color:#9c3232; }
/* 셀: 카드 아님 — 투명 배경 + 헤어라인 보더, 오늘만 오렌지 보더+옅은 틴트 */
.my-day { min-width:0; min-height:72px; display:flex; flex-direction:column; gap:6px;
  border:1px solid #e0dbd2; border-radius:9px; padding:8px 6px; background:transparent; }
.my-day.is-today { border-color:#c2410c; background:rgba(255,255,255,.75); }
.my-day.empty { min-height:0; padding:0; border:0; }
.my-date { font-family:'IBM Plex Mono',monospace; font-size:11.5px; font-weight:600; color:#6b665d; line-height:1; }
.my-day.is-sat .my-date { color:#2f4d99; } .my-day.is-sun .my-date { color:#9c3232; }
.my-duty { display:flex; align-items:center; justify-content:center; min-height:22px;
  border-radius:6px; font-size:12.5px; font-weight:600; line-height:1; padding:4px 0;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.my-duty.is-empty { background:transparent; }
@media (max-width:640px) {
  .my-title { display:none; } .my-emp { font-size:12px; }
  .my-head { padding:6px 0 10px; }
  .my-weekdays, .my-calendar-grid { gap:3px; } .my-weekday { font-size:10.5px; padding:4px 0 6px; }
  .my-day { min-height:58px; padding:6px 3px; gap:4px; border-radius:7px; }
  .my-date { font-size:10.5px; } .my-duty { font-size:11px; min-height:20px; padding:3px 0; }
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
        # 근무 chip = 근무형태 DB hex 배경(§2 예외 SoT) + WCAG 대비 텍스트(흰/검).
        duty = (
            f"<span class='my-duty' style='background:{escape(color)};color:{_text_on(color)}'>"
            f"{escape(label)}</span>"
            if code else "<span class='my-duty is-empty'>&nbsp;</span>"
        )
        cells.append(f"<div class='{' '.join(classes)}'><span class='my-date'>{day}</span>{duty}</div>")
    while len(cells) % 7:
        cells.append("<div class='my-day empty'></div>")
    weekdays = "".join(f"<div class='my-weekday'>{day}</div>" for day in ["월", "화", "수", "목", "금", "토", "일"])
    return f"<div class='my-calendar'><div class='my-weekdays'>{weekdays}</div><div class='my-calendar-grid'>{''.join(cells)}</div></div>"


def _month_navigation(year: int, month: int) -> None:
    result = _MONTH_PICKER()(
        key="my_schedule_wheel_picker",
        data={"year": year, "month": month},
        on_month_change_change=lambda: None,
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

    # dc isMySched 순서: 제목 → 월 이동(‹ 월 ›) → 헤더 줄(사용자·소속 | 근무형태 합계) →
    # 7열 달력. 합계는 헤더 우측으로 이관(하단 요약 제거). 아이콘 밴드·카드 없음.
    st.markdown(_styles(), unsafe_allow_html=True)
    st.markdown("<div class='my-title'>내 근무표</div>", unsafe_allow_html=True)
    _month_navigation(year, month)
    groups = _group_counts(rows, work_type_df) if not rows.empty else []
    st.markdown(_header_html(user, dept, team, groups), unsafe_allow_html=True)
    if snapshot_failed:
        st.caption("⚠ 편성 정보를 불러오지 못해 소속을 현재 정보로 표시합니다(달력은 정상).")
    if rows.empty:
        st.caption("해당 월에 저장된 근무내역이 없습니다.")
    st.markdown(_calendar_html(rows, year, month, work_types, display_of, color_of), unsafe_allow_html=True)
