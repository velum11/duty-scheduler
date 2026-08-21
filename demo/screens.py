"""데모 3화면 — 근무 현황(DASHBOARD) · 근무표 편성(MATRIX_EDIT) · 사용자 관리(EDIT_GRID).

무엇이 진짜 Streamlit 이고 무엇이 주입 HTML 인지 구분해 둔다. 이 구분이 데모의 핵심이다.

- **진짜 위젯** : 조회조건(selectbox·text_input) · 액션 버튼 · 부서 칩 · 기준일 이동
  → 클릭하면 rerun 이 돌고 값이 Python 으로 온다.
- **주입 HTML** : 표 전체(머리글·행·셀 칩·sticky 열)
  → 목업과 픽셀이 같지만 **읽기 전용**이다. 편집·정렬·선택이 없다.
    `st.dataframe`/AgGrid 로 바꾸면 편집은 되지만 iframe 이라 글꼴·1px 정합을 잃는다.
    데모는 그 교환을 보여주려고 일부러 HTML 쪽을 골랐다.
"""
import streamlit as st

import data as D
import grids
import ui as U


# ── 공통 조각 ──────────────────────────────────────────────────────
def _filter_row(fields: list) -> dict:
    """조회조건 줄. 목업: auto-fit minmax(230px,1fr) · 라벨 62px 우측정렬 · 컨트롤 28px."""
    out = {}
    with st.container(key="filterbar"):
        cols = st.columns(len(fields), gap="small")
        for col, f in zip(cols, fields):
            with col:
                lab, ctl = st.columns([0.15, 0.85], vertical_alignment="center")
                lab.html(
                    f'<div class="wo-flabel">{f["label"]}</div>')
                with ctl:
                    key = f"f_{f['key']}"
                    if f["kind"] == "select":
                        out[f["key"]] = st.selectbox(
                            f["label"], f["options"], key=key,
                            label_visibility="collapsed")
                    else:
                        out[f["key"]] = st.text_input(
                            f["label"], key=key, placeholder=f.get("placeholder", ""),
                            label_visibility="collapsed")
    return out


def _section_head(title: str, sub: str = "", actions: list | None = None) -> None:
    """■ 제목 + 보조 문구 (좌) / 액션 버튼 (우). 목업 padding:8px 14px 0."""
    with st.container(key=f"sechead_{title}"):
        left, right = st.columns([0.55, 0.45], vertical_alignment="center")
        with left:
            st.html(
                f'<div class="wo-sechead"><span class="wo-sectitle">■ {title}</span>'
                f'<span class="wo-secsub">{sub}</span></div>')
        if actions:
            with right:
                # 목업은 `flex-wrap:wrap` 에 버튼이 내용 폭이다. 컬럼으로 나누면 좁은 폭에서
                # 글자가 잘리고 겹친다(실제로 겹쳤다) — btnrow 컨테이너로 접히게 만든다.
                with st.container(key=f"btnrow_{title}"):
                    for label, primary in actions:
                        st.button(label, key=f"act_{title}_{label}",
                                  type="primary" if primary else "secondary")


def _grid_open(max_h: int = 520) -> str:
    return (f'<div style="margin:6px 14px 0;border:1px solid {U.LINE_OUTER};'
            f'overflow:auto;max-height:{max_h}px"><table style="width:100%;'
            f'border-collapse:collapse">')


_TH = (f"height:{U.ROW_H}px;padding:0 8px;font-size:11.5px;font-weight:700;color:{U.INK};"
       f"background:{U.HEAD_BG};border-bottom:1px solid {U.LINE_OUTER};"
       f"border-right:1px solid {U.LINE_HEAD};text-align:center;white-space:nowrap")
_TD = (f"height:{U.ROW_H}px;padding:0 8px;font-size:12.5px;"
       f"border-bottom:1px solid {U.LINE_ROW};border-right:1px solid {U.LINE_COL};"
       f"white-space:nowrap")


def _chip(label: str, style: dict, min_w: int = 30, size: str = "11.5px") -> str:
    return (f'<span style="display:inline-flex;align-items:center;justify-content:center;'
            f'min-width:{min_w}px;height:18px;padding:0 4px;border:1px solid {style["bd"]};'
            f'border-radius:2px;font-size:{size};color:{style["fg"]}">{label}</span>')


def _render_mode(scope: str) -> str:
    """표를 어느 방식으로 그릴지 고른다. **이 데모의 핵심 비교 장치다.**

    - HTML  : 목업과 픽셀이 같다. 편집·정렬·선택이 없다.
    - AgGrid: 편집·정렬·선택이 된다. iframe 안이라 글꼴·1px 정합을 잃는다.
    """
    key = f"mode_{scope}"
    cur = st.session_state.setdefault(key, "HTML")
    with st.container(key=f"modebar_{scope}"):
        with st.container(key=f"btnrow_mode_{scope}"):
            st.html('<div class="wo-modehint">표 렌더 방식</div>')
            for name in ("HTML", "AgGrid"):
                if st.button(name, key=f"{key}_{name}",
                             type="primary" if name == cur else "secondary"):
                    st.session_state[key] = name
                    st.rerun()
    return st.session_state[key]


# ── 1. 근무 현황 (DASHBOARD) ────────────────────────────────────────
def dash() -> None:
    sel = st.session_state.setdefault("wo_dash_dept", "전체")
    with st.container(key="dashbar"):
        # 목업은 이 줄 전체가 하나의 `flex-wrap:wrap` 이다. 컬럼으로 쪼개면 좁은 폭에서
        # 칩이 잘리므로 라벨·날짜상자·버튼을 같은 flex 줄의 아이템으로 둔다.
        with st.container(key="btnrow_left_dash"):
            st.html('<div class="wo-dateline">'
                    '<span class="wo-flabel" style="text-align:left">기준일</span>'
                    '<span class="wo-datebox">&lsaquo;&nbsp; 2026-08-21 (금) &nbsp;&rsaquo;</span>'
                    '</div>')
            st.button("오늘", key="d_today")
            for name in D.DASH_DEPT_CHIPS:
                if st.button(name, key=f"d_chip_{name}",
                             type="primary" if name == sel else "secondary"):
                    st.session_state.wo_dash_dept = name
                    st.rerun()

    _section_head("근무 인원 요약", f"2026-08-21 (금) · 근태 대상 {sel}")

    heads = ["부서", "조", "정원", "당일 근무", "주간", "야간", "휴무", "휴가", "근무 인원"]
    html = [_grid_open(), "<thead><tr>"]
    for h in heads:
        html.append(f'<th style="{_TH}">{h}</th>')
    html.append("</tr></thead><tbody>")
    for i, row in enumerate(D.DASH_SUMMARY):
        total = i == 0
        bg = U.ROW_PICK if total else "#fff"
        bar = f"box-shadow:inset 3px 0 0 {U.ACCENT};" if total else ""
        fw = "700" if total else "400"
        html.append(f'<tr style="background:{bg};{bar}">')
        html.append(f'<td style="{_TD};font-weight:{fw};color:{U.INK}">{row[0]}</td>')
        html.append(f'<td style="{_TD};text-align:center;color:{U.INK3}">{row[1]}</td>')
        for j, v in enumerate(row[2:8]):
            color = "#c4c0b9" if v == 0 else (U.ACCENT if (total and j == 1) else U.INK)
            html.append(
                f'<td style="{_TD};text-align:right;font-weight:{fw};color:{color}">{v}</td>')
        html.append(f'<td style="{_TD};text-align:right;font-weight:{fw};'
                    f'border-right:0">{row[8]}</td>')
        html.append("</tr>")
    html.append("</tbody></table></div>")
    st.html("".join(html))

    _section_head("당일 근무자 명단", "28명",
                  actions=[("부서별", False), ("근무형태별", True)])

    heads = ["No", "사번", "성명", "부서", "조", "근무형태", "시작", "종료", "비고"]
    html = [_grid_open(), "<thead><tr>"]
    html.append(f'<th style="{_TH};width:30px;padding:0 5px">No</th>')
    for h in heads[1:]:
        html.append(f'<th style="{_TH}">{h}</th>')
    html.append("</tr></thead><tbody>")
    for i, p in enumerate(D.DASH_TODAY, 1):
        bg = U.ROW_PICK if i == 1 else "#fff"
        bar = f"box-shadow:inset 3px 0 0 {U.ACCENT};" if i == 1 else ""
        wt = D.WT.get(p[4], D.WT["OFF"])
        html.append(f'<tr style="background:{bg};{bar}">')
        html.append(f'<td style="{_TD};width:30px;padding:0 5px;text-align:center;'
                    f'font-size:11px;color:{U.MUTED}">{i}</td>')
        html.append(f'<td style="{_TD}">{p[0]}</td>')
        html.append(f'<td style="{_TD};font-weight:600">{p[1]}</td>')
        html.append(f'<td style="{_TD};color:{U.INK3}">{p[2]}</td>')
        html.append(f'<td style="{_TD};text-align:center;color:{U.INK3}">{p[3]}</td>')
        html.append(f'<td style="{_TD};text-align:center;font-weight:600">'
                    f'{_chip(p[4], wt, min_w=34, size="12.5px")}</td>')
        html.append(f'<td style="{_TD};text-align:center">{p[5]}</td>')
        html.append(f'<td style="{_TD};text-align:center">{p[6]}</td>')
        html.append(f'<td style="{_TD};color:#888;border-right:0">{p[7]}</td>')
        html.append("</tr>")
    html.append("</tbody></table></div><div style='height:14px'></div>")
    st.html("".join(html))


# ── 2. 근무표 편성 (MATRIX_EDIT) ────────────────────────────────────
def plan() -> None:
    _filter_row([
        {"key": "period", "label": "기간", "kind": "select", "options": ["2026-08", "2026-07"]},
        {"key": "dept", "label": "부서", "kind": "select", "options": D.DEPARTMENTS},
        {"key": "team", "label": "조", "kind": "select", "options": D.TEAMS},
        {"key": "q", "label": "사번·성명", "kind": "text", "placeholder": ""},
    ])
    _section_head("2026-08 근무표 편성", "", actions=U.ACTIONS["plan"])
    if _render_mode("plan") == "AgGrid":
        st.html('<div style="height:6px"></div>')
        grids.plan_grid()
        _plan_footer()
        return

    n_days = 31
    days = [(d, D.WEEKDAYS[(d - 1) % 7]) for d in range(1, n_days + 1)]

    # sticky 좌측 열 폭 — 목업 state.cw
    w_no, w_id, w_name, w_dept, w_team = 30, 82, 70, 118, 44
    left_name = w_no + w_id

    sticky_th = (f"position:sticky;top:0;z-index:3;{_TH}")
    html = [_grid_open(), "<thead><tr>"]
    html.append(f'<th style="{sticky_th};left:0;width:{w_no}px;padding:0 5px">No</th>')
    html.append(f'<th style="{sticky_th};left:{w_no}px;width:{w_id}px">사번</th>')
    html.append(f'<th style="{sticky_th};left:{left_name}px;width:{w_name}px">성명</th>')
    html.append(f'<th style="{_TH};position:sticky;top:0;z-index:2;width:{w_dept}px">부서</th>')
    html.append(f'<th style="{_TH};position:sticky;top:0;z-index:2;width:{w_team}px;'
                f'border-right:1px solid {U.LINE_OUTER}">조</th>')
    for d, w in days:
        weekend = w in ("토", "일")
        hbg = "#f4f1ea" if weekend else U.HEAD_BG
        hfg = "#c0392b" if w == "일" else ("#2f5fa8" if w == "토" else U.INK)
        html.append(
            f'<th style="{_TH};position:sticky;top:0;z-index:2;width:34px;padding:0 2px;'
            f'font-size:11px;background:{hbg};color:{hfg}">{d}<br>'
            f'<span style="font-size:9.5px;font-weight:500">{w}</span></th>')
    html.append("</tr></thead><tbody>")

    for i, (emp, name, dept, team, pat) in enumerate(D.PEOPLE, 1):
        first = i == 1
        rowbg = U.ROW_PICK if first else "#fff"
        bar = f"box-shadow:inset 3px 0 0 {U.ACCENT};" if first else ""
        html.append(f'<tr style="{bar}">')
        html.append(f'<td style="{_TD};position:sticky;left:0;z-index:1;width:{w_no}px;'
                    f'padding:0 5px;text-align:center;font-size:11px;color:{U.MUTED};'
                    f'background:{rowbg}">{i}</td>')
        html.append(f'<td style="{_TD};position:sticky;left:{w_no}px;z-index:1;'
                    f'background:{rowbg}">{emp}</td>')
        html.append(f'<td style="{_TD};position:sticky;left:{left_name}px;z-index:1;'
                    f'font-weight:600;background:{rowbg}">{name}</td>')
        html.append(f'<td style="{_TD};color:{U.INK3};background:{rowbg}">{dept}</td>')
        html.append(f'<td style="{_TD};text-align:center;color:{U.INK3};'
                    f'border-right:1px solid {U.LINE_OUTER};background:{rowbg}">'
                    f'{team or "—"}</td>')
        for t in D.PATTERNS[pat][:n_days]:
            wt = D.WT.get(t, D.WT["OFF"])
            html.append(f'<td style="{_TD};padding:0 2px;text-align:center;font-weight:600;'
                        f'background:{rowbg}">{_chip(t, wt)}</td>')
        html.append("</tr>")
    html.append("</tbody></table></div>")
    st.html("".join(html))

    _plan_footer()


def _plan_footer() -> None:
    legend = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;'
        f'color:#444;white-space:nowrap"><span style="width:9px;height:9px;'
        f'background:{c}"></span>{t}</span>'
        for c, t in D.LEGEND)
    st.html(f"""
<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:8px 14px 0;
            padding:7px 10px;border:1px solid {U.LINE_PANEL};background:{U.SIDEBAR_BG}">
  <span style="font-size:11px;font-weight:700;color:{U.INK4}">근무형태</span>
  {legend}
  <span style="font-size:11px;color:#999">{D.LEGEND_TAIL}</span>
</div>
<div style="display:flex;justify-content:flex-end;padding:8px 14px 14px">
  <span style="font-size:11.5px;color:{U.INK4}">총 <b>45</b>명 · 1,395건</span>
</div>""")


# ── 3. 사용자 관리 (EDIT_GRID) ──────────────────────────────────────
def user() -> None:
    _filter_row([
        {"key": "active", "label": "재직 여부", "kind": "select",
         "options": ["전체", "재직", "퇴직"]},
        {"key": "dept", "label": "부서", "kind": "select", "options": D.DEPARTMENTS},
        {"key": "role", "label": "권한", "kind": "select",
         "options": ["전체 권한", "관리자", "매니저", "안전담당", "조원"]},
        {"key": "q", "label": "검색", "kind": "text", "placeholder": "사번 · 성명"},
    ])
    _section_head("사용자", "총 <b>127</b>명 · 재직 126 · 퇴직 1", actions=U.ACTIONS["user"])
    if _render_mode("user") == "AgGrid":
        st.html('<div style="height:6px"></div>')
        grids.user_grid()
        st.html("<div style='height:14px'></div>")
        return

    heads = ["사번", "성명", "부서", "부서코드", "직급", "권한", "이메일",
             "입사일", "퇴사일", "표시순서", "재직"]
    box = ('<span style="display:inline-block;width:15px;height:15px;vertical-align:middle;'
           'border:1px solid {bd};border-radius:2px;background:{bg}"></span>')
    html = [_grid_open(), "<thead><tr>"]
    html.append(f'<th style="{_TH};width:34px;padding:0 5px">'
                + box.format(bd="#9a958d", bg="#fff") + "</th>")
    for h in heads:
        html.append(f'<th style="{_TH}">{h}</th>')
    html.append("</tr></thead><tbody>")
    for i, u in enumerate(D.USERS):
        first = i == 0
        bg = U.ROW_PICK if first else "#fff"
        bar = f"box-shadow:inset 3px 0 0 {U.ACCENT};" if first else ""
        rfg, rfw = D.ROLE_STYLE.get(u[5], (U.INK, 400))
        resigned = u[10] == "퇴직"
        html.append(f'<tr style="background:{bg};{bar}">')
        html.append(f'<td style="{_TD};width:34px;padding:0 5px;text-align:center">'
                    + box.format(bd=U.ACCENT if first else "#b9b4ac",
                                 bg=U.ACCENT if first else "#fff") + "</td>")
        html.append(f'<td style="{_TD}">{u[0]}</td>')
        html.append(f'<td style="{_TD};font-weight:600">{u[1]}</td>')
        html.append(f'<td style="{_TD};color:#444">{u[2]}</td>')
        html.append(f'<td style="{_TD};text-align:center;color:#777">{u[3]}</td>')
        html.append(f'<td style="{_TD};text-align:center;color:#777">{u[4]}</td>')
        html.append(f'<td style="{_TD};text-align:center;font-weight:{rfw};'
                    f'color:{rfg}">{u[5]}</td>')
        html.append(f'<td style="{_TD};color:{U.INK3}">{u[6]}</td>')
        html.append(f'<td style="{_TD};text-align:center">{u[7]}</td>')
        html.append(f'<td style="{_TD};text-align:center;color:#a3282a">{u[8]}</td>')
        html.append(f'<td style="{_TD};text-align:right;font-size:12px;color:#777">{u[9]}</td>')
        html.append(f'<td style="{_TD};text-align:center;border-right:0;'
                    f'color:{"#a3282a" if resigned else U.INK}">{u[10]}</td>')
        html.append("</tr>")
    html.append("</tbody></table></div><div style='height:14px'></div>")
    st.html("".join(html))


# ── 4. 아차사고 등록 (FORM_ENTRY) ───────────────────────────────────
#: 목업 실측 — 라벨 셀 132px / 배경 #eceae5 / 11.5px·700 / 필수는 앞에 * (#b8460d)
FORM_FIELDS = [
    ("작업명", True, "text", "예: 3라인 컨베이어 벨트 점검"),
    ("발생일", True, "date", "2026-08-21"),
    ("사고내용", True, "text", "무슨 일이 있었는지(아차사고 상황)를 구체적으로"),
    ("작업내용", True, "text", "어떤 작업을 하고 있었는지"),
    ("작업현장 상황설명", True, "text", "현장 상황 · 주변 환경"),
    ("발생원인", True, "select", ["— 선택 —", "미끄러짐", "끼임", "낙하물", "추락", "협착", "부딪힘", "기타"]),
    ("발생원인 상세", True, "text", "원인을 구체적으로"),
    ("예방대책", True, "text", "재발을 막기 위한 대책"),
]

RECENT = [
    ("202608-0005", "컨베이어 이물 제거 · 끼임", "2026-08-14", "평가완료", "#1c6b41"),
    ("202607-0003", "권취 롤러 청소 · 협착", "2026-07-16", "평가중", U.ACCENT),
]


def form() -> None:
    """아차사고 등록. **표가 없는 화면** — 전부 진짜 Streamlit 위젯으로 만들 수 있는지 본다."""
    st.html(f'<div class="wo-sechead" style="padding:11px 14px 0">'
            f'<span class="wo-sectitle">■ 아차사고 등록</span>'
            f'<span class="wo-secsub">신고자 이광호 · 전산팀 · 2004051202</span></div>')

    with st.container(key="formwrap"):
        left, right = st.columns([1.7, 1.0])

        with left:
            with st.container(key="formpanel"):
                for i, (label, req, kind, arg) in enumerate(FORM_FIELDS):
                    with st.container(key=f"frow_{i}"):
                        lc, vc = st.columns([0.18, 0.82], vertical_alignment="center")
                        star = f'<span style="color:{U.ACCENT};margin-right:3px">*</span>' if req else ""
                        lc.html(f'<div class="wo-fcell">{star}{label}</div>')
                        with vc:
                            k = f"form_{i}"
                            if kind == "select":
                                st.selectbox(label, arg, key=k, label_visibility="collapsed")
                            elif kind == "date":
                                st.text_input(label, value=arg, key=k,
                                              label_visibility="collapsed")
                            else:
                                st.text_input(label, key=k, placeholder=arg,
                                              label_visibility="collapsed")
                # 첨부 사진 행 — 버튼 2개 + 파일 칩
                with st.container(key="frow_up"):
                    lc, vc = st.columns([0.18, 0.82], vertical_alignment="center")
                    lc.html('<div class="wo-fcell">첨부 사진</div>')
                    with vc:
                        with st.container(key="btnrow_left_up"):
                            st.button("파일 업로드", key="up_file")
                            st.button("사진 촬영", key="up_cam", type="primary")
                            st.html('<div class="wo-filechip">촬영_20260821_1.jpg · 1.2MB</div>')
                            st.html('<div class="wo-fhint">JPG · PNG · PDF / 10MB 이하 · 최대 5개</div>')
                # 하단 액션 바
                with st.container(key="formacts"):
                    with st.container(key="btnrow_form"):
                        st.button("제출", key="f_submit", type="primary")
                        st.button("임시저장", key="f_draft")
                        st.button("초기화", key="f_reset")

        with right:
            rows = "".join(
                f'<div class="wo-siderow"><div class="wo-siderow-top">'
                f'<span>{no}</span><span style="color:{fg};font-weight:700">{stt}</span></div>'
                f'<span style="font-size:12.5px;color:{U.INK}">{title}</span>'
                f'<span style="font-size:11px;color:{U.MUTED}">{d}</span></div>'
                for no, title, d, stt, fg in RECENT)
            st.html(f"""
<div class="wo-sidepanel">
  <div class="wo-sidehead"><span>내 최근 아차사고</span>
    <span style="font-size:11px;font-weight:400;color:{U.MUTED}">최근순</span></div>
  {rows}
  <div class="wo-sidefoot"><span style="color:{U.ACCENT};cursor:pointer">전체 보기 &rsaquo;</span></div>
</div>""")


RENDERERS = {"dash": dash, "plan": plan, "user": user, "nearReg": form}

