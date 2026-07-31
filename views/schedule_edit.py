"""근무표 관리 — 근무표 편성 화면 (사번 중심 입력, 1차 기능 기반).

전체 사용자를 자동 나열하지 않는다. 저장된 해당 월 근무표가 있으면 그 직원 행만,
없으면 신규 입력 행 1개만 표시하고, 필요한 직원은 [행 추가]나 Excel 붙여넣기로
사번을 입력한다. 사번을 입력하면 성명·부서·조를 사용자 기준정보에서 자동 조회해
채우고, 부서·조는 이 화면에서 편성값으로만 수정한다(users 기준정보는 변경하지 않음).

행 상태 계약(_row_id/_row_state/_sel — views/workspace.selectable_master_grid):
  - 기존 행: 첫 열 선택 체크박스 → [행 삭제]로 저장 시 삭제 예정 지정(취소 가능)
  - 신규 행: 첫 열 − 버튼 → 즉시 개별 제거 (DB 작업 없음)

날짜 셀은 work_types 약칭으로 표시·입력하고 저장 시 내부 코드로 변환한다.
[저장]은 변경된 셀만 upsert 하며, 빈 셀로 기존 근무를 자동 삭제하지 않는다
(CLAUDE.md §5 — 삭제는 [행 삭제] → 저장의 명시적 흐름으로만).

부서·조 편성값의 영구 저장(schedule_assignments 스냅샷)은 migration 002 미적용 +
근무조 필수 계약(validators) 때문에 이번 단계에서는 수행하지 않는다 — 화면 편집·
검증까지만 지원하고 저장 시 안내한다.

dirty tracking: 원본 스냅샷과 현재 편집 상태를 정규화 비교해 판단하며, dirty 상태에서
사이드바 이동·로그아웃(modules/ui.request_nav 가드)·조회 조건 변경 시 확인을 거친다.
"""
# DESIGN.md §0 화면 유형 규약 — 매트릭스 편집형.
SCREEN_ARCHETYPE = "MATRIX_EDIT"

import calendar
import json
from datetime import date
from html import escape

import pandas as pd
import streamlit as st
from st_aggrid import JsCode

from modules import db, ui
from views.common import erp
from views.common import scaffold
from views.workspace import (
    grid_bool,
    selectable_master_grid,
    set_flash,
    show_flash,
)

_FIXED = ["사번", "성명", "부서", "조"]
_ALL = "(전체)"  # 부서·조 '전체' 센티널(workspace.ALL 과 동일 값). 전체 조회 시 다부서/조 표시.
_META = ["_row_id", "_row_state", "_sel"]

# 기존 행의 사번은 읽기 전용(관계키). 신규 행에서만 편집한다.
_EMP_EDITABLE = JsCode("function(p){ return p.data && p.data._row_state !== 'existing'; }")

# ── §2 팔레트 (팔레트 밖 색 금지 §0-8) ──
_INK = "#1c1a17"
_INK2 = "#4a453d"
# Codex P1: _WEAK(.se-ctx .op 운영단위 라벨)·_FAINT(.se-legend .lab 모노 오버라인)는 읽는
# 텍스트라 #6b665d(5.1:1↑)로 상향 — #8b857c·#a09a90 은 읽는 텍스트 금지.
_WEAK = "#6b665d"
_FAINT = "#6b665d"
_LINE = "#e6e2da"
_LINE_HDR = "#cfc8bd"
_LINE_SEC = "#e0dbd2"
_ACCENT = "#c2410c"
_ACCENT_TEXT = "#b4451a"
_MONO = "'IBM Plex Mono', monospace"

# §1-C 그리드 컨테이너 리스킨 — AG Grid iframe 바깥 래퍼에 흰 배경·헤어라인·radius 를 입힌다
# (내부 헤더/셀 헤어라인은 공용 _MASTER_GRID_CSS 의 #CFC8BB 계열이 §2 와 정합). 셀 색은
# 근무형태 DB hex(day_style JsCode). sticky 4열은 AG Grid pinned(신원 4열+선택열)로 확보.
_ROSTER_CSS = f"""
<style>
.st-key-se_gridwrap div[data-testid="stAgGrid"] {{
  border-radius:8px; overflow:hidden; border:1px solid {_LINE_HDR}; background:#ffffff;
}}
.se-hint {{ display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin:2px 0 8px; }}
.se-hint .lab {{ font-size:12px; color:{_INK2}; margin-right:2px; }}
.se-key {{ display:inline-flex; align-items:center; gap:6px; padding:3px 10px; border-radius:7px;
  border:1px solid {_LINE}; background:#ffffff; font-size:12px; color:{_INK}; white-space:nowrap; }}
.se-key .n {{ font-family:{_MONO}; font-weight:600; color:{_ACCENT_TEXT}; }}
.se-key .sw {{ width:9px; height:9px; border-radius:2px; flex:0 0 auto; }}
.se-ctx {{ display:flex; flex-wrap:wrap; align-items:center; gap:6px 16px; margin:6px 0 10px;
  font-size:12.5px; color:{_INK2}; }}
.se-ctx .loc {{ font-weight:600; color:{_INK}; }}
.se-ctx .num {{ font-family:{_MONO}; font-weight:600; color:{_INK}; }}
.se-ctx .op {{ color:{_WEAK}; }}
.se-legend {{ display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin:10px 0 2px; }}
.se-legend .lab {{ font-size:11px; letter-spacing:.1em; color:{_FAINT}; font-family:{_MONO}; margin-right:4px; }}
.se-leg {{ display:inline-flex; align-items:center; gap:6px; font-size:12px; color:{_INK}; }}
.se-leg .sw {{ width:11px; height:11px; border-radius:3px; flex:0 0 auto; }}
.se-dirty {{ text-align:right; color:{_ACCENT_TEXT}; font-size:12.5px; font-weight:600; margin-top:6px; }}
</style>
"""


def _active_ordered() -> list[tuple[str, str, str]]:
    """활성 근무형태를 sort_order 순으로 (code, short_label, color) 리스트로 반환(도메인 파생)."""
    wt = db.get_work_types()
    act = wt[wt["is_active"]] if wt is not None and not wt.empty else wt
    if act is None or act.empty:
        return []
    if "sort_order" in act.columns:
        act = act.sort_values("sort_order", kind="stable")
    out = []
    for _, r in act.iterrows():
        code = str(r["code"]).strip()
        if not code:
            continue
        sl = str(r.get("short_label") or "").strip() or code
        color = str(r.get("color") or "").strip()
        out.append((code, sl, color))
    return out


def _day_cell_handlers(cycle_labels: list[str], number_labels: list[str]) -> dict:
    """day 컬럼 셀 상호작용 JsCode(§1-C, 도메인 파생) — 클릭 순환은 제거(사용자 피드백):
    셀 편집은 더블클릭 편집기·직접 타이핑(이전 방식)으로 하고, 숫자키 1..N=N번째 근무형태·
    0=지움, 방향키 이동은 유지한다. 값 반영은 setDataValue→cellValueChanged→기존 dirty/저장
    경로 그대로. Ctrl+V(붙여넣기)도 유지된다. (cycle_labels 는 숫자키/붙여넣기 검증용 보존.)"""
    nums = json.dumps(number_labels, ensure_ascii=False)
    # 숫자키(1..N·0)는 편집 중이 아닐 때만 근무형태 즉시 입력. 그 외 키(방향키 등)는 기본
    # 동작(이동)을 그대로 두고, 편집 시작 키·타이핑은 AG Grid 기본 편집기로 흘린다.
    suppress_kbd = JsCode(
        "function(p){"
        "  var e=p.event; if(!e)return false;"
        "  if(p.editing)return false;"
        f" var nums={nums};"
        "  var k=e.key;"
        "  if(k==='0'){ p.node.setDataValue(p.column.getColId(), ''); return true; }"
        "  if(k>='1'&&k<='9'){ var i=parseInt(k,10)-1;"
        "    if(i<nums.length){ p.node.setDataValue(p.column.getColId(), nums[i]); return true; } }"
        "  return false;"
        "}"
    )
    return {"suppressKeyboardEvent": suppress_kbd}


def _day_header_component(day_col: str) -> JsCode:
    """일자 헤더 2줄(숫자 위·요일 아래) headerComponent. day_col 형식 'D(요일)'."""
    num = day_col.split("(")[0].strip()
    wd = day_col.split("(")[1].rstrip(")") if "(" in day_col else ""
    num_j = json.dumps(num)
    wd_j = json.dumps(wd)
    return JsCode(
        "class{init(p){this.eGui=document.createElement('div');"
        "this.eGui.style.cssText='line-height:1.12;text-align:center';"
        f"this.eGui.innerHTML=\"<div style='font-family:IBM Plex Mono,monospace;font-weight:600;"
        f"font-size:12.5px;color:{_INK}'>\"+{num_j}+\"</div><div style='font-size:10px;color:{_INK2}'>\""
        f"+{wd_j}+\"</div>\";}}getGui(){{return this.eGui;}}}}"
    )


def _hint_html(number_labels: list[str], colors: dict) -> str:
    """입력 단축키 안내 라인 — [1 주][2 야]… 실제 활성 근무형태에서 파생(도메인). 색 스와치 포함."""
    keys = []
    for i, lab in enumerate(number_labels[:9], start=1):
        c = colors.get(lab, "")
        sw = f"<span class='sw' style='background:{c}'></span>" if c.startswith("#") else ""
        keys.append(f"<span class='se-key'><span class='n'>{i}</span>{sw}{escape(lab)}</span>")
    return ("<div class='se-hint'><span class='lab'>입력 단축키</span>"
            + "".join(keys)
            + "<span class='se-key'><span class='n'>0</span>지움</span></div>")


def _context_html(q: dict, dept_name: str, team_name: str,
                  n_people: int, filled: int, empty: int) -> str:
    """컨텍스트 라인 — YYYY-MM · 부서 · 조 + 인원/입력/미입력 모노 수치 + 조작 안내."""
    ym = f"{q['year']}-{q['month']:02d}"
    return (
        "<div class='se-ctx'>"
        f"<span class='loc'>{escape(ym)}</span><span>·</span>"
        f"<span class='loc'>{escape(dept_name)}</span><span>·</span>"
        f"<span class='loc'>{escape(team_name)}</span>"
        f"<span>인원 <span class='num'>{n_people}</span></span>"
        f"<span>입력 <span class='num'>{filled}</span></span>"
        f"<span>미입력 <span class='num'>{empty}</span></span>"
        f"<span class='op'>더블클릭 편집 · 숫자키 1~9·0 입력 · 방향키 이동 · Ctrl+V 붙여넣기</span></div>"
    )


def _legend_html(active: list[tuple[str, str, str]]) -> str:
    """하단 범례 — 활성 근무형태 색·약칭(도메인 파생)."""
    items = []
    for _code, sl, color in active:
        sw = f"<span class='sw' style='background:{color}'></span>" if color.startswith("#") else ""
        items.append(f"<span class='se-leg'>{sw}{escape(sl)}</span>")
    return ("<div class='se-legend'><span class='lab'>근무형태</span>" + "".join(items) + "</div>")


def _change_count(live: pd.DataFrame, day_cols: list, orig_cells: dict, n_del: int) -> int:
    """미저장 변경 건수 — 기존 행 셀 변경 + 신규 행 입력 셀 + 삭제 예정 행. dirty 판정과 별개
    표시용 카운트(셀 클릭 순환/숫자키 입력마다 증가해 자가검증 근거가 된다)."""
    cnt = int(n_del)
    if live is None or live.empty or not day_cols:
        return cnt
    for _, r in live.iterrows():
        rid = str(r.get("_row_id"))
        is_existing = str(r.get("_row_state")) == "existing"
        for c in day_cols:
            now = "" if pd.isna(r.get(c)) else str(r.get(c)).strip()
            if is_existing:
                if now != orig_cells.get((rid, c), ""):
                    cnt += 1
            elif now:
                cnt += 1
    return cnt


# ---------- 진입점 ----------
def render(user: dict) -> None:
    # 크롬은 키트로 통일(screen_frame). 필터 select 만 condition_panel 로 이관했고
    # (widget_key=se_y/se_m/se_d/se_t 로 revert 키 계약 유지), 새로고침은 클릭소실
    # 회피(on_click 플래그) 그대로 패널 밖 별도 버튼이다. 편집 버튼·MATRIX 그리드·
    # 저장/dirty/이탈가드는 계약상 이번엔 건드리지 않는다 — top_action_bar·MATRIX
    # 어댑터 추출은 BACKLOG.
    # §1-C 스프레드시트 입력형(구조 교체) — 파랑 아이콘 밴드 제거(§0-3). 액션은 1행(필터 우측)
    # 으로 이전하고 셀 입력은 클릭 순환 + 숫자키(도메인 파생). 저장/dirty/검증/이탈가드/편성
    # 스냅샷 계약은 전부 불변(표현 계층만 교체).
    st.markdown(_ROSTER_CSS, unsafe_allow_html=True)
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="근무표 편성",
        desc="부서와 조를 선택하여 월별 근무표를 관리합니다.",
        breadcrumb="근무표 › 근무표 편성",
        badges=scaffold.mode_badge(),
    )

    depts = db.get_departments()
    teams = db.get_teams()
    today = date.today()

    active_depts = depts[depts["is_active"]].sort_values("sort_order")
    dept_names = {r["dept_code"]: r["dept_name"] for _, r in active_depts.iterrows()}
    if not dept_names:
        ui.empty_state("등록된 부서가 없습니다. 먼저 기준정보에서 부서를 등록하세요.", head="월별 근무표")
        return

    manager_locked = user["role"] == "MANAGER" and user.get("dept_code") in dept_names
    years = list(range(today.year - 1, today.year + 2))

    # [계속 편집]으로 조회 조건 변경을 취소한 경우 — 위젯 값을 이전 조건으로 되돌린다.
    q_prev = st.session_state.get("q_schedule_edit")
    if st.session_state.pop("se_revert", False) and q_prev:
        st.session_state["se_y"] = q_prev["year"]
        st.session_state["se_m"] = q_prev["month"]
        st.session_state["se_d"] = q_prev["dept"]
        st.session_state["se_t"] = q_prev["team"]
    elif q_prev and "se_y" not in st.session_state:
        # 다른 화면을 다녀오면 Streamlit 이 위젯 상태를 지운다 — 마지막 조회 조건으로
        # 복원해 조건이 기본값으로 리셋되며 가짜 '조건 변경'이 생기는 것을 막는다.
        st.session_state["se_y"] = q_prev["year"]
        st.session_state["se_m"] = q_prev["month"]
        st.session_state["se_d"] = q_prev["dept"]
        st.session_state["se_t"] = q_prev["team"]

    # 위젯 key 를 session_state 로 관리하므로 default(index)를 함께 주지 않는다
    # (Streamlit "default value + Session State API" 경고 방지). 값은 여기서 초기화.
    st.session_state.setdefault("se_y", today.year)
    st.session_state.setdefault("se_m", today.month)
    # 부서·조 기본 = 전체(피드백 #3). MANAGER 는 아래에서 자기 부서로 잠금(fail-closed 불변).
    st.session_state.setdefault("se_d", _ALL)
    st.session_state.setdefault("se_t", _ALL)

    # 조회 조건(우측 인라인 라벨, KP-standard) — 위젯 key 는 기존 se_y/se_m/se_d/se_t 를
    # widget_key 로 그대로 지정해 revert 로직(위 67-90행)·테스트가 이름으로 참조하는
    # 세션 키를 변경 없이 유지한다(구조만 이전, views.workspace.schedule_screen 과 동일 패턴).
    if manager_locked:
        cur_dept = user["dept_code"]
        # MANAGER 는 자기 부서로 잠금(fail-closed). 기본 se_d=_ALL 은 잠금 옵션에 없으므로
        # 자기 부서로 교정한다(조는 _ALL=자기 부서 전체 조 허용).
        st.session_state["se_d"] = cur_dept
        dept_field = erp.Field(
            key="d", label="부서", kind="select",
            options=[user["dept_code"]], format_func=lambda c: dept_names.get(c, c),
            disabled=True, widget_key="se_d",
        )
    else:
        # 부서→조 종속 옵션: 조 Field 를 만들기 전에 "현재" 부서 선택을 세션 상태에서
        # 읽는다(위젯 렌더 순서가 아니라 세션 상태로 종속을 해석해, 사용자가 부서를 바꾼
        # 그 rerun 에서 조 옵션이 갱신되게 한다 — workspace.schedule_screen 과 동일).
        cur_dept = st.session_state.get("se_d") or _ALL
        dept_field = erp.Field(
            key="d", label="부서", kind="select",
            options=[_ALL] + list(dept_names),
            format_func=lambda c: "전체 부서" if c == _ALL else dept_names.get(c, c),
            widget_key="se_d",
        )
    # 부서=전체면 조는 '전체'만(특정 부서 종속 조 목록 없음). 특정 부서면 그 부서 조 + 전체.
    if cur_dept == _ALL:
        team_names = {}
    else:
        team_rows = teams[(teams["dept_code"] == cur_dept) & teams["is_active"]].sort_values("sort_order")
        team_names = {r["team_code"]: r["team_name"] for _, r in team_rows.iterrows()}

    fields = [
        # format_func=str 명시: 키트 select 기본 포맷터(항등함수)는 int 옵션(연도)을
        # 그대로 protobuf 문자열 필드에 넣어 TypeError 를 낸다(workspace.schedule_screen 과
        # 동일 회피 — 키트 자체는 손대지 않는다). str(int) 는 기존 selectbox 표시와 동일.
        erp.Field(key="y", label="연도", kind="select", options=years, format_func=str,
                  widget_key="se_y"),
        erp.Field(key="m", label="월", kind="select", options=list(range(1, 13)),
                  format_func=lambda m: f"{m}월", widget_key="se_m"),
        dept_field,
        erp.Field(key="t", label="조", kind="select", options=[_ALL] + list(team_names),
                  format_func=lambda c: "전체 조" if c == _ALL else team_names.get(c, c),
                  widget_key="se_t"),
    ]
    v = erp.condition_panel("se", fields, cols=4)
    year, month, dept, team = v["y"], v["m"], v["d"], v["t"]

    # 액션은 상단 52px 헤더 아이콘 4종(추가·새로고침·삭제·저장)이 소유한다(피드백 #1,
    # 부속서 A-5 단일 범위 화면). 페이지 본문의 4단추는 제거했고, 헤더 아이콘 클릭이 기존
    # flag(se_*_req)를 발화한다(ui._PAGE_HEADER_ACTIONS). 삭제·저장 음영은 아래에서 세션
    # (hdr_dis_delete/save)에 저장해 헤더가 읽는다(선택·dirty 변화는 rerun 주기 내 반영).
    # 필터 하단 헤어라인은 condition_panel(§1-E)이 소유한다.
    clicked = st.session_state.pop("se_go_req", False)
    show_flash("schedule_edit")

    if team is None:
        ui.empty_state("선택한 부서에 등록된 조/팀이 없습니다.", head="월별 근무표")
        return

    # 조회 범위 결정 + 조건 변경/새로고침 가드 (dirty 는 직전 렌더 기준) — 계약 불변.
    params = {"year": year, "month": month, "dept": dept, "team": team}
    q = st.session_state.get("q_schedule_edit")
    if q is None:
        q = params
        st.session_state["q_schedule_edit"] = q
        _load_grid(q)
    elif clicked or params != q:
        if st.session_state.get("se_dirty"):
            st.session_state.setdefault("nav_pending", {"type": "scope", "params": params})
        else:
            q = params
            st.session_state["q_schedule_edit"] = q
            _load_grid(q)
    elif "se_rows" not in st.session_state:
        _load_grid(q)

    _deleted_panel(q)

    day_cols = [c for c, _ in st.session_state["se_days"]]
    row_cols = _META + _FIXED + day_cols

    # ── 도메인 파생(하드코딩 금지): 활성 근무형태 순서·색·약칭 → 순환 목록·숫자키·힌트·범례 ──
    active = _active_ordered()
    display_of, _codes, _lc = _label_maps()
    number_labels = [display_of.get(code, sl) for code, sl, _c in active][:9]
    cycle_labels = [display_of.get(code, sl) for code, sl, _c in active] + [""]  # 빈값 포함(지움)
    hint_colors = {}
    for code, sl, color in active:
        if color.startswith("#"):
            hint_colors[display_of.get(code, sl)] = color

    # 입력 단축키 힌트 라인 → 컨텍스트 라인(값은 그리드 뒤 채움) → 표
    st.markdown(_hint_html(number_labels, hint_colors), unsafe_allow_html=True)
    context_slot = st.container()

    col_config = {
        # Codex P2(§8-6): 신원 4열 본문 14.5px. 사번(10자리 모노)은 96px 폭을 좌우 패딩
        # 4px 축소로 수용(잘림 없음 실측). 30px 행 높이·sticky(pinned left) 유지.
        "사번": {"pinned": "left", "width": 96, "minWidth": 96,
                "editable": _EMP_EDITABLE, "cellClass": "md-c-left",
                "cellStyle": {"fontSize": "14.5px", "paddingLeft": "4px", "paddingRight": "4px"}},
        "성명": {"pinned": "left", "width": 92, "minWidth": 80,
                "editable": False, "cellClass": "md-c-left",
                "cellStyle": {"fontSize": "14.5px"}},
        "부서": {"pinned": "left", "width": 116, "minWidth": 96, "cellClass": "md-c-left",
                "cellStyle": {"fontSize": "14.5px"}},
        "조": {"pinned": "left", "width": 88, "minWidth": 72, "cellClass": "md-c-left",
              "cellStyle": {"fontSize": "14.5px"}},
    }
    # 날짜 셀 색상 — work_types 기준정보 hex 를 약칭/코드에 매핑(도메인 SoT, 하드코딩 금지).
    day_style = JsCode(
        "function(p) {"
        f"  const colors = {json.dumps(st.session_state.get('se_colors', {}), ensure_ascii=False)};"
        "  const v = String(p.value == null ? '' : p.value).trim();"
        "  const c = colors[v];"
        # Codex P2(§8-6 우선): 근무 셀 본문 14.5px(목업 픽셀보다 §8-6). 30px 행 높이 유지.
        "  if (!c) { return { textAlign: 'center', fontSize: '14.5px' }; }"
        "  return { backgroundColor: c + '26', color: '#1c1a17', fontWeight: 600, textAlign: 'center', fontSize: '14.5px' };"
        "}"
    )
    # 셀 클릭=근무 순환(빈값 포함) + 숫자키 1..N/0 = 근무형태/지움(도메인 파생). 값은
    # setDataValue→cellValueChanged→기존 dirty/검증/저장 경로 그대로(계약 불변).
    handlers = _day_cell_handlers(cycle_labels, number_labels)
    for c in day_cols:
        col_config[c] = {
            "width": 44, "minWidth": 34, "cellClass": "md-c-center", "cellStyle": day_style,
            "headerComponent": _day_header_component(c),  # 일자 헤더 2줄(숫자/요일)
            **handlers,
        }

    # se_feed 는 remount 시점 값으로 고정(편집 결과 재전송이 버튼 클릭 rerun 을 삼키는 것 방지).
    nonce = st.session_state.setdefault("se_nonce", 0)
    feed = st.session_state.get("se_feed", st.session_state["se_rows"])
    with st.container(key="se_gridwrap"):
        grid_df = selectable_master_grid(
            feed,
            key=f"se_grid_{nonce}",
            columns={c: "text" for c in _FIXED + day_cols},
            order=_FIXED + day_cols,
            height=min(max(210, 30 * len(feed) + 96), 500),  # ≈62vh 내부 스크롤
            col_config=col_config,
            select_all_header=True,  # 표시 중인 기존 행만 대상 (신규 행 제외)
            # 셀 높이 30px(§1-C). 클릭 순환 제거(피드백) → suppressClickEdit 해제해 더블클릭
            # 편집기·직접 타이핑을 복원한다. 숫자키·방향키·Ctrl+V 는 그대로 유지.
            extra_grid_options={"rowHeight": 30},
        )

    # 구조 변경(− 제거/붙여넣기 신규 행) + 사번 자동 조회를 권위 상태로 동기화
    if _sync_rows(grid_df, row_cols):
        st.rerun()

    live = _live(grid_df)

    # 건수 계산
    existing_live = live[live["_row_state"] == "existing"] if not live.empty else live
    n_exist = len(existing_live)
    n_sel = int(existing_live["_sel"].map(grid_bool).sum()) if n_exist else 0
    n_del = len(st.session_state.get("se_deleted", []))
    n_people = len(live)
    filled = 0
    if not live.empty and day_cols:
        filled = int(live[day_cols].apply(
            lambda col: col.map(lambda v: bool(str(v).strip()) if pd.notna(v) else False)
        ).sum().sum())
    empty_cells = max(n_people * len(day_cols) - filled, 0)

    # 컨텍스트 라인 채움(YYYY-MM · 부서 · 조 + 인원/입력/미입력). 전체(_ALL)면 라벨로 표기.
    dept_lbl = "전체 부서" if q.get("dept") == _ALL else dept_names.get(q["dept"], q["dept"])
    team_lbl = "전체 조" if q.get("team") == _ALL else team_names.get(q["team"], q["team"])
    with context_slot:
        st.markdown(
            _context_html(q, dept_lbl, team_lbl, n_people, filled, empty_cells),
            unsafe_allow_html=True,
        )

    # dirty 판정: 원본 스냅샷과 현재 편집 상태(정규화)를 비교 — 계약 불변.
    dirty = _canon(live, st.session_state.get("se_deleted", []), day_cols) \
        != st.session_state.get("se_orig")
    st.session_state["se_dirty"] = dirty
    if dirty:
        st.session_state["nav_guard"] = {"owner": "schedule_edit"}
    elif st.session_state.get("nav_guard", {}).get("owner") == "schedule_edit":
        st.session_state.pop("nav_guard", None)

    # 브라우저 새로고침/탭 닫기 경고 (best effort)
    st.html(
        "<script>window.onbeforeunload = "
        + ("function(e){e.preventDefault(); e.returnValue='';};" if dirty else "null;")
        + "</script>",
        unsafe_allow_javascript=True,
    )

    # 미저장 이탈 확인 (그리드보다 아래에 렌더 — iframe 재생성로 편집 리셋 방지)
    pending = st.session_state.get("nav_pending")
    if pending:
        _leave_dialog(pending, q)

    # ── 하단: 범례(근무형태 색) + 미저장 변경 N건 ──
    st.markdown(_legend_html(active), unsafe_allow_html=True)
    changed = _change_count(live, day_cols, st.session_state.get("se_orig_cells", {}), n_del)
    st.markdown(f"<div class='se-dirty'>미저장 변경 {changed}건</div>", unsafe_allow_html=True)

    # ── 헤더 아이콘 음영 상태를 세션에 저장(다음 rerun 의 헤더가 읽음) — 삭제는 선택 0,
    #    저장은 dirty 0 일 때 음영. 기본 True(음영·안전)로, 값이 준비된 뒤 갱신한다. ──
    st.session_state["hdr_dis_delete"] = (n_sel == 0)
    st.session_state["hdr_dis_save"] = (not dirty)

    # 헤더 아이콘이 발화한 플래그 처리 (최신 live 기준) — 실행 경로·확인 게이트 불변.
    if st.session_state.pop("se_save_req", False):
        _save(live, q, day_cols)
    if st.session_state.pop("se_del_req", False):
        _mark_delete(live, row_cols)
    if st.session_state.pop("se_add_req", False):
        _add_row(live, row_cols, day_cols)


# ---------- 행 상태 헬퍼 ----------
def _live(grid_df: pd.DataFrame) -> pd.DataFrame:
    if grid_df is None or grid_df.empty or "_removed" not in grid_df.columns:
        return grid_df if grid_df is not None else pd.DataFrame()
    keep = grid_df["_removed"].fillna("").astype(str).str.strip() != "1"
    return grid_df[keep]


def _next_rid() -> str:
    n = st.session_state.get("se_rid", 0) + 1
    st.session_state["se_rid"] = n
    return f"n:{n}"


def _remount() -> None:
    """그리드를 권위 상태(se_rows) 기준으로 재마운트한다."""
    st.session_state["se_feed"] = st.session_state["se_rows"].copy()
    st.session_state["se_nonce"] = st.session_state.get("se_nonce", 0) + 1


def _blank_row(day_cols: list) -> dict:
    row = {"_row_id": _next_rid(), "_row_state": "new", "_sel": False}
    for c in _FIXED + day_cols:
        row[c] = ""
    return row


def classify_save_targets(live_emps, deleted_emps):
    """혼합 저장 분류 — (delete_only, replace_after_delete) 를 정렬 리스트로 반환.

    삭제 예정 사번이 화면에 다시 입력돼 있으면 충돌이 아니라 '해당 월 교체' 대상이다.
    """
    live = {str(e).strip() for e in live_emps if str(e).strip()}
    dele = {str(e).strip() for e in deleted_emps if str(e).strip()}
    return sorted(dele - live), sorted(dele & live)


def should_save_assignment(state, cur_dept_code, cur_team_code, loaded) -> bool:
    """이 행의 부서·조 편성을 schedule_assignments 에 저장(upsert)해야 하는가 (순수).

    - state == "new": 신규 직원·월 → 유효 부서가 있으면 저장.
    - 기존 행: 로드 스냅샷(loaded=(dept_code, team_code))과 현재 부서·조가 다를 때만.
      legacy(편성 없던) 행이든 persisted 행이든 '변경됐을 때만' 저장하므로, 근무만
      수정한 경우 users 현재 소속이 과거 편성으로 자동 저장되지 않는다.
    loaded 가 None(스냅샷 없음)이면 신규가 아닌 한 저장하지 않는다.
    """
    if state == "new":
        return bool(str(cur_dept_code or "").strip())
    if loaded is None:
        return False
    return (str(cur_dept_code or ""), str(cur_team_code or "")) != (str(loaded[0]), str(loaded[1]))


def _build_users_map(users: pd.DataFrame) -> dict:
    return {
        str(r["emp_no"]).strip(): {
            "name": str(r["name"]),
            "dept_code": str(r["dept_code"]).strip(),
            "team_code": str(r["team_code"]).strip(),
            "is_active": bool(r["is_active"]),
        }
        for _, r in users.iterrows()
        if str(r["emp_no"]).strip()
    }


def _users_by_emp() -> dict:
    """사용자 매핑 — 조회(_load_grid) 시점 캐시를 재사용한다.

    rerun/저장마다 users 전체를 반복 조회하면 일시 소켓 오류(WinError 10035)에
    노출되는 표면적만 커진다. 최신화는 [새로고침]/조건 변경 시 이루어진다.
    """
    cached = st.session_state.get("se_users_map")
    if cached is None:
        cached = _build_users_map(db.get_users())
        st.session_state["se_users_map"] = cached
    return cached


def _sync_rows(grid_df: pd.DataFrame, row_cols: list) -> bool:
    """그리드 구조 변경을 권위 상태로 반영하고 사번 기반 자동 조회를 수행한다.

    - − 로 제거된 행을 실제 제거
    - 붙여넣기로 생긴 무명 행에 _row_id/_row_state 부여
    - 신규 행: 사번 → 성명 자동 표시(미등록이면 "(미등록)"), 부서·조가 비어 있으면
      사용자 기준정보의 현재 소속으로 기본값 채움 (users 는 변경하지 않음)
    - 기존 행: 사번·성명을 원본으로 강제(붙여넣기로 덮여도 복원)
    변경이 있으면 se_rows 갱신 + 그리드 재마운트 후 True.
    """
    if grid_df is None or grid_df.empty or "_row_id" not in grid_df.columns:
        return False
    removed = grid_df["_removed"].fillna("").astype(str).str.strip() == "1" \
        if "_removed" in grid_df.columns else pd.Series(False, index=grid_df.index)
    live = grid_df[~removed].copy()
    changed = bool(removed.any())

    users = _users_by_emp()

    rid = live["_row_id"].fillna("").astype(str).str.strip()
    needs_id = rid == ""
    if needs_id.any():
        changed = True
        for idx in live.index[needs_id]:
            live.at[idx, "_row_id"] = _next_rid()
            live.at[idx, "_row_state"] = "new"
            live.at[idx, "_sel"] = False
    live["_row_state"] = live["_row_state"].fillna("").astype(str).replace("", "new")

    for idx, row in live.iterrows():
        state = str(row["_row_state"])
        emp = str(row.get("사번") or "").strip()
        if state == "existing":
            orig_emp = str(row["_row_id"])[2:]  # "e:{emp_no}"
            master = users.get(orig_emp)
            name = str(master["name"]) if master is not None else ""
            if emp != orig_emp:
                live.at[idx, "사번"] = orig_emp
                changed = True
            if str(row.get("성명") or "") != name:
                live.at[idx, "성명"] = name
                changed = True
            continue
        master = users.get(emp) if emp else None
        target_name = "" if not emp else (str(master["name"]) if master is not None else "(미등록)")
        if str(row.get("성명") or "") != target_name:
            live.at[idx, "성명"] = target_name
            changed = True
        if master is not None:
            if not str(row.get("부서") or "").strip():
                live.at[idx, "부서"] = db.dept_name(master["dept_code"])
                changed = True
            if not str(row.get("조") or "").strip() and str(master["team_code"]).strip():
                live.at[idx, "조"] = db.team_name(master["dept_code"], master["team_code"])
                changed = True

    # 값 편집도 매 rerun 권위 상태에 반영한다 (구조 변경이 없으면 remount 는 하지 않음
    # — 그리드가 이미 최신 값을 보여주고 있고, feed 재전송은 클릭 rerun 을 삼킬 수 있다).
    st.session_state["se_rows"] = live[row_cols].reset_index(drop=True)
    if changed:
        _remount()
    return changed


def _add_row(live: pd.DataFrame, row_cols: list, day_cols: list) -> None:
    base = live[row_cols].copy() if not live.empty else pd.DataFrame(columns=row_cols)
    st.session_state["se_rows"] = pd.concat(
        [base, pd.DataFrame([_blank_row(day_cols)])], ignore_index=True,
    )[row_cols]
    _remount()
    st.rerun()


def _mark_delete(live: pd.DataFrame, row_cols: list) -> None:
    """선택된 기존 행을 삭제 예정으로 옮긴다 (즉시 DB 삭제 없음 — 저장 시 처리)."""
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    if sel.empty:
        set_flash("schedule_edit", "warning", "삭제할 기존 행(체크박스)을 선택하세요. 신규 행은 − 버튼으로 제거합니다.")
        st.rerun()
    deleted = st.session_state.setdefault("se_deleted", [])
    deleted.extend(r.to_dict() for _, r in sel[row_cols].iterrows())
    remaining = live[~live.index.isin(sel.index)].assign(_sel=False)
    st.session_state["se_rows"] = remaining[row_cols].reset_index(drop=True)
    _remount()
    st.rerun()


def _deleted_panel(q: dict) -> None:
    deleted = st.session_state.get("se_deleted", [])
    if not deleted:
        return
    names = ", ".join(f"{r.get('성명', '')}({str(r.get('사번', '')).strip()})" for r in deleted)
    st.warning(
        f"[저장] 시 다음 직원의 {q['year']}-{q['month']:02d} 근무표가 모두 삭제됩니다: {names}\n\n"
        "다른 월의 근무표와 사용자 기준정보는 삭제되지 않습니다."
    )
    c1, _sp = st.columns([1.6, 8], vertical_alignment="center")
    if c1.button("삭제 예정 취소", key="se_undel", width="stretch"):
        rows = st.session_state.get("se_rows", pd.DataFrame())
        restored = pd.concat([rows, pd.DataFrame(deleted)], ignore_index=True)
        st.session_state["se_rows"] = restored[rows.columns] if not rows.empty else restored
        st.session_state["se_deleted"] = []
        _remount()
        st.rerun()


# ---------- 이탈 확인 ----------
def _discard_draft() -> None:
    for key in ("se_rows", "se_feed", "se_days", "se_orig", "se_orig_cells",
                "se_orig_assign", "se_deleted", "se_dirty"):
        st.session_state.pop(key, None)
    st.session_state.pop("nav_guard", None)


def _leave_dialog(pending: dict, q: dict) -> None:
    st.warning("저장하지 않은 변경사항이 있습니다.\n\n이동하면 입력한 내용이 사라집니다.")
    c1, c2, _sp = st.columns([1.4, 1.9, 5.7], vertical_alignment="center")
    if c1.button("계속 편집", key="se_stay", type="primary", width="stretch"):
        st.session_state.pop("nav_pending", None)
        if pending.get("type") == "scope":
            st.session_state["se_revert"] = True
        _remount()  # 권위 상태(se_rows) 기준으로 편집 내용을 확실히 복원
        st.rerun()
    if c2.button("저장하지 않고 이동", key="se_leave", width="stretch"):
        st.session_state.pop("nav_pending", None)
        _discard_draft()
        if pending.get("type") == "scope":
            new_q = pending["params"]
            st.session_state["q_schedule_edit"] = new_q
            _load_grid(new_q)
        else:
            ui.apply_nav(pending)
        st.rerun()


# ---------- 적재 ----------
def _label_maps():
    """근무형태 약칭 표시/입력 매핑.

    반환: (display_of: 코드→표시값, codes: 유효 코드 집합, label_codes: 약칭→코드집합)
    약칭이 비어 있으면 코드를 그대로 표시하고, 같은 약칭이 여러 코드에 걸리면
    표시도 코드로 대체한다(왕복 변환 모호성 방지). 입력 시 모호한 약칭은 저장 차단.
    """
    wt = db.get_work_types()
    active = wt[wt["is_active"]] if not wt.empty else wt
    codes, label_codes = set(), {}
    for _, r in active.iterrows():
        code = str(r["code"]).strip()
        if not code:
            continue
        codes.add(code)
        sl = str(r["short_label"]).strip()
        if sl:
            label_codes.setdefault(sl, set()).add(code)
    display_of = {}
    for _, r in active.iterrows():
        code = str(r["code"]).strip()
        sl = str(r["short_label"]).strip()
        display_of[code] = sl if sl and len(label_codes.get(sl, set())) == 1 else code
    return display_of, codes, label_codes


def _resolve_work(value: str, codes: set, label_codes: dict):
    """입력값(약칭 또는 코드) → 내부 코드. 미등록 None, 모호 약칭 'AMBIG' 반환."""
    if value in codes:
        return value
    matched = label_codes.get(value)
    if not matched:
        return None
    return next(iter(matched)) if len(matched) == 1 else "AMBIG"


def _day_color_map(display_of: dict) -> dict:
    """날짜 셀 색상 맵 — work_types 기준정보의 색상을 표시값과 코드에 매핑한다.

    약칭이 바뀌거나 재조회돼도 같은 코드는 같은 색을 유지한다(색은 코드에 귀속).
    """
    wt = db.get_work_types()
    active = wt[wt["is_active"]] if not wt.empty else wt
    colors = {}
    for _, r in active.iterrows():
        code = str(r["code"]).strip()
        color = str(r["color"] or "").strip()
        if not code or not color.startswith("#"):
            continue
        colors[code] = color                      # 코드 그대로 표시되는 fallback 셀
        display = display_of.get(code)
        if display:
            colors[display] = color               # 약칭 표시 셀
    return colors


def _load_grid(q: dict) -> None:
    """선택 범위(부서·조 재직 직원)의 해당 월 '저장된' 근무표 행만 적재한다.

    전체 사용자를 자동 나열하지 않는다 — 저장 행이 없으면 신규 입력 행 1개만 둔다.
    """
    ndays = calendar.monthrange(q["year"], q["month"])[1]
    days = []
    for d in range(1, ndays + 1):
        dt = date(q["year"], q["month"], d)
        days.append((f"{d}({ui.weekday_kr(dt)})", dt.isoformat()))
    day_cols = [c for c, _ in days]
    row_cols = _META + _FIXED + day_cols

    users = db.get_users()
    st.session_state["se_users_map"] = _build_users_map(users)  # 조회 시점 캐시 갱신
    # 부서·조 '전체'(_ALL)면 해당 필터를 생략한다(다부서/조 표시). 재직자만 대상.
    mask = users["is_active"]
    if q.get("dept") != _ALL:
        mask = mask & (users["dept_code"] == q["dept"])
    if q.get("team") != _ALL:
        mask = mask & (users["team_code"] == q["team"])
    scope = users[mask].sort_values("emp_no")
    emp_nos = [str(e).strip() for e in scope["emp_no"]]

    scheds = db.get_month_schedules(emp_nos, q["year"], q["month"]) if emp_nos else pd.DataFrame(
        columns=db.SCHEDULE_COLUMNS
    )
    display_of, _, _ = _label_maps()
    st.session_state["se_colors"] = _day_color_map(display_of)
    lookup = {
        (str(r["emp_no"]).strip(), str(r["duty_date"])): str(r["work_type_code"]).strip()
        for _, r in scheds.iterrows()
    }
    with_rows = {emp for emp, _iso in lookup}
    # 부서·조는 편성 스냅샷을 우선 표시한다 (없으면 users 의 현재 소속).
    snaps = _assignment_snapshots(q, sorted(with_rows))

    rows = []
    orig_assign = {}  # rid -> (dept_code, team_code) 로드 스냅샷 (편성 변경 여부 판정용)
    for _, u in scope.iterrows():
        emp = str(u["emp_no"]).strip()
        if emp not in with_rows:
            continue  # 저장된 행이 있는 직원만 표시 (전체 자동 나열 금지)
        dept_code, team_code = snaps.get(
            emp, (str(u["dept_code"]).strip(), str(u["team_code"]).strip())
        )
        rid = f"e:{emp}"
        orig_assign[rid] = (dept_code, team_code)
        row = {
            "_row_id": rid, "_row_state": "existing", "_sel": False,
            "사번": emp,
            "성명": str(u["name"]),
            "부서": db.dept_name(dept_code),
            "조": db.team_name(dept_code, team_code),
        }
        for col, iso in days:
            code = lookup.get((emp, iso), "")
            row[col] = display_of.get(code, code) if code else ""
        rows.append(row)

    frame = pd.DataFrame(rows, columns=row_cols) if rows else pd.DataFrame(
        [_blank_row(day_cols)], columns=row_cols
    )

    st.session_state["se_rows"] = frame
    st.session_state["se_days"] = days
    st.session_state["se_deleted"] = []
    st.session_state["se_orig_assign"] = orig_assign  # 편성 변경 판정용 로드 스냅샷
    st.session_state["se_orig"] = _canon(frame, [], day_cols)
    # 원본 셀 값(기존 행): '변경분만 저장'과 '빈 칸 = 삭제 아님' 안내에 사용
    st.session_state["se_orig_cells"] = {
        (str(r["_row_id"]), c): str(r[c]).strip()
        for _, r in frame.iterrows() if r["_row_state"] == "existing"
        for c in day_cols
    }
    st.session_state["se_dirty"] = False
    if st.session_state.get("nav_guard", {}).get("owner") == "schedule_edit":
        st.session_state.pop("nav_guard", None)
    _remount()


def _canon(rows: pd.DataFrame, deleted: list, day_cols: list):
    """dirty 비교용 정규화 스냅샷 (성명은 파생값이므로 제외)."""
    out = []
    for _, r in rows.iterrows():
        out.append(tuple(
            str(r.get(c) if pd.notna(r.get(c)) else "").strip()
            for c in ["사번", "부서", "조"] + day_cols
        ))
    dele = tuple(sorted(str(r.get("사번", "")).strip() for r in deleted))
    return (tuple(out), dele)


def _assignment_snapshots(q: dict, emp_nos: list) -> dict:
    """대상 월의 부서·조 편성 스냅샷 맵 {emp_no: (dept_code, team_code)}.

    우선순위: 영속 저장(schedule_assignments — migration 002 적용 시)
    → 세션 스냅샷(이번 세션에서 저장 성공한 편성값) 순으로 합친다.
    영속 테이블이 없으면(002 이전) 조회 실패를 무시하고 세션 값만 쓴다.
    """
    snaps = {}
    month_key = f"{q['year']:04d}-{q['month']:02d}"
    cache = st.session_state.get("se_assign_cache", {})
    for (mk, emp), value in cache.items():
        if mk == month_key:
            snaps[emp] = (value["dept_code"], value["team_code"])
    if emp_nos:
        try:
            assigns = db.get_month_assignments(q["year"], q["month"], emp_nos)
            for _, r in assigns.iterrows():
                snaps[str(r["emp_no"]).strip()] = (
                    str(r["dept_code"]).strip(), str(r["team_code"]).strip(),
                )
        except Exception:
            pass  # 002 이전에는 테이블이 없다 — 세션 스냅샷/마스터 기본값 사용
    return snaps


# ---------- 저장 ----------
def _save(live: pd.DataFrame, q: dict, day_cols: list) -> None:
    """최종 화면 상태 기준 혼합 저장.

    직원별 최종 상태로 분류해 처리한다 (classify_save_targets):
      - delete_only: 삭제 예정 + 재입력 없음 → 해당 월 삭제
      - replace_after_delete: 삭제 예정 + 같은 사번 재입력 → 해당 월을 입력값으로 교체
      - 그 외 행: 변경 셀만 upsert (빈 셀 자동 삭제 없음)
    삭제만 저장하는 경우에는 users/근무형태/부서·조 조회를 실행하지 않는다.
    Repository 는 원자적이지 않으므로 실패 시 단계를 보고하고 초안을 유지한다.
    """
    day_isos = dict(st.session_state.get("se_days", []))
    orig_cells = st.session_state.get("se_orig_cells", {})
    deleted = st.session_state.get("se_deleted", [])
    deleted_emps = sorted({str(r.get("사번", "")).strip() for r in deleted if str(r.get("사번", "")).strip()})

    # 1) 최종 화면 상태 정규화 — 내용이 있는 행만 (완전히 빈 신규 행 제외)
    content_rows = []
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        emp = str(row.get("사번") or "").strip()
        dept_txt = str(row.get("부서") or "").strip()
        team_txt = str(row.get("조") or "").strip()
        day_vals = {
            c: ("" if pd.isna(row.get(c)) else str(row.get(c)).strip()) for c in day_cols
        }
        if not any([emp, dept_txt, team_txt, *day_vals.values()]):
            continue
        content_rows.append((i, row, emp, dept_txt, team_txt, day_vals))

    live_emps = {emp for (_i, _r, emp, *_rest) in content_rows if emp}
    delete_only, replace_after_delete = classify_save_targets(live_emps, deleted_emps)
    replace_set = set(replace_after_delete)

    if not content_rows and not deleted_emps:
        set_flash("schedule_edit", "warning", "저장할 변경 내용이 없습니다.")
        st.rerun()

    # 2) 신규·수정 입력 검증 (삭제만 저장하는 경로에서는 참조 조회를 건너뛴다)
    records_plain, records_replace, errors = [], {}, []
    assign_rows = []  # 편성 저장 대상 (신규 행 또는 부서·조가 로드값과 달라진 행)
    if content_rows:
        display_of, codes, label_codes = _label_maps()
        users = _users_by_emp()  # 조회 시점 캐시 재사용 (rerun 반복 조회 방지)
        depts = db.get_departments()
        teams = db.get_teams()
        orig_assign = st.session_state.get("se_orig_assign", {})  # rid -> (dept_code, team_code) 로드 스냅샷
        dept_name_codes = {}
        for _, r in depts.iterrows():
            dept_name_codes.setdefault(str(r["dept_name"]).strip(), set()).add(str(r["dept_code"]).strip())
        dept_codes = set(depts["dept_code"].astype(str).str.strip())
        seen = set()

        for i, row, emp, dept_txt, team_txt, day_vals in content_rows:
            if not emp:
                errors.append(f"{i}행: 사번을 입력하세요.")
                continue
            master = users.get(emp)
            if master is None:
                errors.append(f"{i}행({emp}): 등록되지 않은 사번입니다.")
                continue
            if not bool(master["is_active"]):
                errors.append(f"{i}행({emp}): 재직 중이 아닌 사용자입니다.")
            if emp in seen:
                # 최종 화면에 같은 사번이 2행 이상일 때만 중복 오류
                errors.append(f"{i}행({emp}): 같은 월에 동일 사번이 여러 행입니다.")
            seen.add(emp)

            # 부서·조 편성값 검증 (표시명 또는 코드 입력 허용 → 내부 코드로 확인)
            dept_code = None
            if not dept_txt:
                errors.append(f"{i}행({emp}): 부서를 입력하세요.")
            elif dept_txt in dept_codes:
                dept_code = dept_txt
            else:
                matched = dept_name_codes.get(dept_txt, set())
                if len(matched) == 1:
                    dept_code = next(iter(matched))
                elif len(matched) > 1:
                    errors.append(f"{i}행({emp}): 부서명 '{dept_txt}'이(가) 여러 부서에 해당합니다.")
                else:
                    errors.append(f"{i}행({emp}): 존재하지 않는 부서입니다: {dept_txt}")

            team_code = ""
            if dept_code is not None and team_txt:
                in_dept = teams[teams["dept_code"].astype(str).str.strip() == dept_code]
                by_code = in_dept[in_dept["team_code"].astype(str).str.strip() == team_txt]
                by_name = in_dept[in_dept["team_name"].astype(str).str.strip() == team_txt]
                if not by_code.empty:
                    team_code = team_txt
                elif len(by_name) == 1:
                    team_code = str(by_name.iloc[0]["team_code"]).strip()
                elif len(by_name) > 1:
                    errors.append(f"{i}행({emp}): 조명 '{team_txt}'이(가) 같은 부서에 중복됩니다.")
                else:
                    errors.append(f"{i}행({emp}): 선택한 부서에 없는 조입니다: {team_txt}")

            # 편성 저장 여부 결정 (§편성 저장 조건):
            #  - 신규 직원·월 행 → 저장(새 편성)
            #  - 기존 행 → 로드 스냅샷과 부서·조가 달라졌을 때만 저장(명시적 변경)
            #  - legacy 행 + 근무만 수정 → 저장 안 함 → 근무는 schedule_assignment_id NULL
            # users 현재 소속을 과거 편성으로 자동 각인하지 않는다.
            state = str(row.get("_row_state") or "new")
            loaded = orig_assign.get(str(row.get("_row_id", "")))
            if dept_code is not None and should_save_assignment(
                state, dept_code, team_code, loaded
            ):
                assign_rows.append({
                    "emp_no": emp,
                    "schedule_month": (q["year"], q["month"]),
                    "dept_code": dept_code,
                    "team_code": team_code,
                    "shift_group_code": "",  # 근무조 입력은 아직 없음 (NULL 허용)
                })

            rid = str(row.get("_row_id", ""))
            is_replace = emp in replace_set
            for col, val in day_vals.items():
                if not val:
                    continue
                # 교체 대상은 전체 값을 저장하고, 그 외에는 변경 셀만 저장한다
                if not is_replace and orig_cells.get((rid, col), "") == val:
                    continue
                code = _resolve_work(val, codes, label_codes)
                if code is None:
                    errors.append(f"{i}행({emp}) {col}: 알 수 없는 근무형태 '{val}'")
                    continue
                if code == "AMBIG":
                    errors.append(f"{i}행({emp}) {col}: 약칭 '{val}'이(가) 여러 근무형태에 매핑됩니다.")
                    continue
                rec = {"emp_no": emp, "duty_date": day_isos[col], "work_type_code": code, "note": ""}
                if is_replace:
                    records_replace.setdefault(emp, []).append(rec)
                else:
                    records_plain.append(rec)

    if errors:
        shown = errors[:20]
        more = f"\n- 외 {len(errors) - 20}건" if len(errors) > 20 else ""
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(shown) + more)
        return

    # 빈 칸으로 지운 셀 = 삭제 아님(기존 근무 유지) 안내 (삭제 예정/교체 행 제외)
    cleared = 0
    live_by_rid = {str(r["_row_id"]): r for _, r in live.iterrows()}
    for (rid, col), orig_val in orig_cells.items():
        if not orig_val:
            continue
        row = live_by_rid.get(rid)
        if row is None:
            continue
        now = "" if pd.isna(row.get(col)) else str(row.get(col)).strip()
        if not now:
            cleared += 1

    # 3) 편성(schedule_assignments) 먼저 저장 — work_schedules 가 이 id 를 참조한다.
    #    실패 시 근무 저장을 진행하지 않고(성공 은폐 방지) 초안을 유지한다.
    month_key = f"{q['year']:04d}-{q['month']:02d}"
    assign_persisted = False
    if assign_rows:
        try:
            db.upsert_month_assignments(assign_rows, require_shift=False)
            assign_persisted = True
        except db.DATA_SOURCE_ERRORS as exc:
            st.error(
                "편성(부서·조) 저장 단계에서 실패했습니다. 근무는 저장하지 않았습니다.\n\n"
                f"편집 내용은 화면에 유지됩니다. [새로고침]으로 확인 후 다시 시도하세요.\n\n({exc})"
            )
            return
        except Exception:
            st.error(
                "편성(부서·조) 저장 단계에서 실패했습니다. 근무는 저장하지 않았습니다.\n\n"
                "편집 내용은 화면에 유지됩니다. [새로고침]으로 확인 후 다시 시도하세요."
            )
            return
        cache = st.session_state.setdefault("se_assign_cache", {})
        for rec in assign_rows:
            cache[(month_key, rec["emp_no"])] = {
                "dept_code": rec["dept_code"], "team_code": rec["team_code"],
            }

    # 4~6) 근무 저장 — 삭제 → 교체 → upsert 순. Repository 가 이 저장 payload 의 각
    #      행을 (사용자·월) 편성이 있으면 schedule_assignment_id 로 연결한다(없으면 NULL).
    #      편성이 먼저 저장됐으므로 신규 편성도 연결된다. 원자적이지 않으므로 실패 시
    #      단계를 보고하고 초안을 유지한다(편성이 이미 저장됐으면 부분 성공을 안내).
    step = "삭제"
    try:
        if delete_only:
            db.replace_month_schedules(delete_only, q["year"], q["month"], [])
        step = "삭제 후 재등록(교체)"
        if replace_after_delete:
            replace_records = [
                rec for emp in replace_after_delete for rec in records_replace.get(emp, [])
            ]
            db.replace_month_schedules(replace_after_delete, q["year"], q["month"], replace_records)
        step = "신규·수정 저장"
        if records_plain:
            db.upsert_month_schedules(records_plain)
    except db.DATA_SOURCE_ERRORS as exc:
        prefix = "편성(부서·조)은 저장되었으나, " if assign_persisted else ""
        st.error(
            f"{prefix}근무 저장이 '{step}' 단계에서 실패했습니다. 이전 단계까지는 반영되었을 수 있습니다.\n\n"
            f"편집 내용은 화면에 유지됩니다. [새로고침]으로 실제 저장 상태를 확인한 뒤 다시 시도하세요.\n\n({exc})"
        )
        return
    except Exception:
        prefix = "편성(부서·조)은 저장되었으나, " if assign_persisted else ""
        st.error(
            f"{prefix}근무 저장이 '{step}' 단계에서 실패했습니다. 이전 단계까지는 반영되었을 수 있습니다.\n\n"
            "편집 내용은 화면에 유지됩니다. [새로고침]으로 실제 저장 상태를 확인한 뒤 다시 시도하세요."
        )
        return

    # 월 근무를 삭제한 직원의 세션 스냅샷 정리 (편성 DB 는 건드리지 않음 — assignment-only 허용)
    if delete_only:
        cache = st.session_state.setdefault("se_assign_cache", {})
        for emp in delete_only:
            cache.pop((month_key, emp), None)

    n_saved = len(records_plain) + sum(len(v) for v in records_replace.values())
    _load_grid(q)  # 재조회 → 신규 행 existing 전환, DB 편성 재수화, dirty/선택 초기화

    parts = [f"근무 {n_saved}건 저장"]
    if delete_only:
        parts.append(f"{len(delete_only)}명 월 근무 삭제")
    if replace_after_delete:
        parts.append(f"{len(replace_after_delete)}명 월 근무 교체")
    if assign_rows and assign_persisted:
        parts.append(f"편성 {len(assign_rows)}명 저장")
    notes = []
    if cleared:
        notes.append(f"빈 칸으로 지운 {cleared}개 셀은 삭제되지 않고 기존 근무가 유지됩니다.")
    msg = "근무표를 저장했습니다. (" + " · ".join(parts) + ")"
    if notes:
        msg += "\n\n" + "\n".join(f"- {n}" for n in notes)
    set_flash("schedule_edit", "warning" if notes else "success", msg)
    st.rerun()
