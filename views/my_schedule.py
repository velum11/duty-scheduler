"""모바일 우선 개인 근무표 조회 화면."""
import calendar
from datetime import date
from functools import partial
from html import escape

import pandas as pd
import streamlit as st

from modules import db, ui


_MONTH_KEY = "my_schedule_month"
_GROUP_ORDER = ("주간", "야간", "OFF", "휴가")

_MONTH_PICKER = partial(
    st.components.v2.component,
    "duty_month_wheel_picker",
    html="<div id='duty-month-wheel'></div>",
    css="""
    #duty-month-wheel { min-height:44px; font-family:inherit; }
    .wheel-nav { display:grid; grid-template-columns:42px minmax(0, 1fr) 42px; align-items:center; gap:8px; }
    .wheel-nav button { height:40px; border:0; border-radius:6px; background:transparent; color:#26282B; cursor:pointer; font:inherit; }
    .wheel-nav button:hover { background:#F5F6F8; } .wheel-nav .month-title { font-size:1rem; font-weight:700; }
    .wheel-backdrop { position:fixed; inset:0; z-index:9999; display:flex; align-items:center; justify-content:center; background:rgba(17,24,39,.28); }
    .wheel-sheet { width:min(420px,calc(100vw - 32px)); border-radius:8px; background:#FFF; box-shadow:0 18px 45px rgba(0,0,0,.22); padding:18px; }
    .wheel-heading { color:#26282B; font-size:1rem; font-weight:700; text-align:center; } .wheel-columns { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:14px 0; }
    .wheel-column { position:relative; height:220px; overflow:hidden; } .wheel-column::before, .wheel-column::after { content:''; position:absolute; z-index:1; left:0; right:0; height:88px; pointer-events:none; }
    .wheel-column::before { top:0; background:linear-gradient(#FFF 20%,rgba(255,255,255,0)); } .wheel-column::after { bottom:0; background:linear-gradient(rgba(255,255,255,0),#FFF 80%); }
    .wheel-column .selection-line { position:absolute; z-index:0; top:88px; left:0; right:0; height:44px; border-top:1px solid #D0D5DD; border-bottom:1px solid #D0D5DD; }
    .wheel-list { position:relative; z-index:2; height:220px; overflow-y:auto; scroll-snap-type:y mandatory; scrollbar-width:none; padding:88px 0; box-sizing:border-box; } .wheel-list::-webkit-scrollbar { display:none; }
    .wheel-option { height:44px; scroll-snap-align:center; color:#9AA0A6; font-size:1rem; line-height:44px; text-align:center; } .wheel-option.is-selected { color:#26282B; font-weight:700; }
    .wheel-actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; } .wheel-actions button { min-height:38px; border:1px solid #D0D5DD; border-radius:6px; background:#FFF; color:#26282B; cursor:pointer; font:inherit; font-weight:700; }
    .wheel-actions .confirm { border-color:#1E3A6E; background:#1E3A6E; color:#FFF; }
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


def _work_group(code: str, work_type: dict) -> str | None:
    category = str(work_type.get("category") or "").strip()
    name = str(work_type.get("name") or "")
    label = f"{code} {category} {name}"
    if code == "OFF" or category.upper() == "OFF":
        return "OFF"
    if "야간" in category or code.startswith("야") or "특야" in code:
        return "야간"
    if "주간" in category or code.startswith("주") or "특주" in code:
        return "주간"
    if not bool(work_type.get("is_work")) or any(word in label for word in ("휴가", "연차", "경조")):
        return "휴가"
    return None


def _group_counts(rows: pd.DataFrame, work_types: pd.DataFrame) -> list[tuple[str, int]]:
    type_map = {
        str(row["code"]): row.to_dict()
        for _, row in work_types.iterrows()
    }
    totals = {group: 0 for group in _GROUP_ORDER}
    for code, count in rows["work_type_code"].value_counts().items():
        group = _work_group(str(code), type_map.get(str(code), {}))
        if group:
            totals[group] += int(count)
    return [(group, count) for group, count in totals.items() if count]


def _styles() -> str:
    return """
<style>
.my-page-title { color:#26282B; font-size:1rem; font-weight:700; margin:0 0 5px; }
.my-employee-line { border-bottom:1px solid #E5E7EB; color:#5F6368; font-size:.86rem; line-height:1.45; padding:0 0 7px; }
.my-employee-line strong { color:#26282B; font-weight:700; }
.my-calendar { width:100%; }
.my-weekdays, .my-calendar-grid { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:3px; }
.my-weekday { color:#5F6368; font-size:.76rem; font-weight:700; padding:2px 0 4px; text-align:center; }
.my-weekday:nth-child(6) { color:#1E6FD9; } .my-weekday:nth-child(7) { color:#D93025; }
.my-day { min-width:0; min-height:58px; border:1px solid transparent; border-radius:6px; padding:5px 3px; text-align:center; }
.my-day.has-duty { border-color:#E5E7EB; background:#FFFFFF; } .my-day.is-today { border-color:#26282B; }
.my-day.empty { min-height:0; padding:0; } .my-date { display:block; color:#26282B; font-size:.76rem; line-height:1; margin-bottom:6px; }
.my-day.is-sat .my-date { color:#1E6FD9; } .my-day.is-sun .my-date { color:#D93025; }
.my-duty { display:block; min-height:21px; border-radius:999px; color:#FFFFFF; font-size:.7rem; font-weight:700; line-height:21px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.my-duty.is-empty { background:transparent; }
.my-summary { display:flex; flex-wrap:wrap; gap:6px 12px; color:#5F6368; font-size:.84rem; line-height:1.5; }
.my-summary span { white-space:nowrap; } .my-summary strong { color:#26282B; font-weight:700; }
@media (max-width:640px) {
  .my-page-title { display:none; } .my-employee-line { font-size:.82rem; padding-bottom:6px; }
  .my-day { min-height:52px; padding:5px 2px; } .my-date { font-size:.7rem; margin-bottom:5px; }
  .my-duty { font-size:.64rem; line-height:20px; min-height:20px; }
  .my-weekdays, .my-calendar-grid { gap:2px; } .my-weekday { font-size:.7rem; }
}
</style>
"""


def _employee_line(user: dict, dept: str, team: str) -> str:
    name = escape(str(user.get("name", "")))
    dept = escape(str(dept))
    team = escape(str(team or "-"))
    return f"""
<div class='my-employee-line'>
  <strong>{name}</strong> · {dept} · {team}
</div>
"""


def _calendar_html(rows: pd.DataFrame, year: int, month: int, work_types: dict) -> str:
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
        color = str(work_types.get(code, {}).get("color") or "#9AA0A6")
        classes = ["my-day"]
        if code:
            classes.append("has-duty")
        if duty_date == today:
            classes.append("is-today")
        if duty_date.weekday() == 5:
            classes.append("is-sat")
        elif duty_date.weekday() == 6:
            classes.append("is-sun")
        duty = (
            f"<span class='my-duty' style='background:{escape(color)}'>{escape(code)}</span>"
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
    try:
        rows = db.get_month_schedules(str(user["emp_no"]).strip(), year, month).copy()
        work_type_df = db.get_work_types()
        work_types = db.work_types_map()
        dept = db.dept_name(user.get("dept_code", ""))
        team = db.team_name(user.get("dept_code", ""), user.get("team_code", ""))
        rows["d"] = pd.to_datetime(rows["duty_date"], errors="coerce").dt.date
    except Exception:
        st.error("근무표 또는 기준정보를 불러오지 못했습니다. 잠시 후 다시 조회하세요.")
        return

    st.markdown(_styles(), unsafe_allow_html=True)
    st.markdown("<div class='my-page-title'>내 근무표</div>", unsafe_allow_html=True)
    st.markdown(_employee_line(user, dept, team), unsafe_allow_html=True)
    _month_navigation(year, month)
    ui.panel_head(f"{year}년 {month}월 근무내역")
    if rows.empty:
        st.caption("해당 월에 저장된 근무내역이 없습니다.")
    st.markdown(_calendar_html(rows, year, month, work_types), unsafe_allow_html=True)

    groups = _group_counts(rows, work_type_df) if not rows.empty else []
    if groups:
        st.write("")
        st.markdown(
            "<div class='my-summary'>" + "".join(
                f"<span><strong>{escape(group)}</strong> {count}일</span>" for group, count in groups
            ) + "</div>",
            unsafe_allow_html=True,
        )
    with st.expander("근무코드 안내", expanded=False):
        st.markdown(ui.legend_html(work_types), unsafe_allow_html=True)
