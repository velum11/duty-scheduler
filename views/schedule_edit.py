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
import calendar
from datetime import date

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from st_aggrid import JsCode

from modules import db, ui
from views.workspace import (
    grid_bool,
    selectable_master_grid,
    set_flash,
    show_flash,
)

_FIXED = ["사번", "성명", "부서", "조"]
_META = ["_row_id", "_row_state", "_sel"]

# 기존 행의 사번은 읽기 전용(관계키). 신규 행에서만 편집한다.
_EMP_EDITABLE = JsCode("function(p){ return p.data && p.data._row_state !== 'existing'; }")


# ---------- 진입점 ----------
def render(user: dict) -> None:
    ui.page_header("schedule_edit")

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

    # 조회 조건 카드 (기존 디자인 유지)
    with ui.card():
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1.6, 1.2, 0.9], vertical_alignment="bottom")
        year = c1.selectbox("연도", years, index=years.index(today.year), key="se_y")
        month = c2.selectbox(
            "월", list(range(1, 13)), index=today.month - 1,
            format_func=lambda m: f"{m}월", key="se_m",
        )
        if manager_locked:
            dept = c3.selectbox(
                "부서", [user["dept_code"]], format_func=lambda c: dept_names.get(c, c),
                key="se_d", disabled=True,
            )
        else:
            dept = c3.selectbox(
                "부서", list(dept_names), format_func=lambda c: dept_names.get(c, c),
                key="se_d",
            )
        team_rows = teams[(teams["dept_code"] == dept) & teams["is_active"]].sort_values("sort_order")
        team_names = {r["team_code"]: r["team_name"] for _, r in team_rows.iterrows()}
        team = c4.selectbox(
            "조", list(team_names), format_func=lambda c: team_names.get(c, c), key="se_t",
        )
        # 반환값 방식은 그리드 컴포넌트 전송과 경합해 클릭이 소실될 수 있어
        # on_click 플래그로 받는다 (저장/행 추가/행 삭제와 동일 패턴).
        c5.button(
            "새로고침", key="se_go", type="primary", width="stretch",
            on_click=lambda: st.session_state.update(se_go_req=True),
        )
        clicked = st.session_state.pop("se_go_req", False)

    show_flash("schedule_edit")

    if team is None:
        ui.empty_state("선택한 부서에 등록된 조/팀이 없습니다.", head="월별 근무표")
        return

    # 조회 범위 결정 + 조건 변경/새로고침 가드 (dirty 는 직전 렌더 기준)
    params = {"year": year, "month": month, "dept": dept, "team": team}
    q = st.session_state.get("q_schedule_edit")
    if q is None:
        q = params
        st.session_state["q_schedule_edit"] = q
        _load_grid(q)
    elif clicked or params != q:
        if st.session_state.get("se_dirty"):
            # 이미 보류된 이동(페이지/로그아웃)이 있으면 덮어쓰지 않는다.
            st.session_state.setdefault("nav_pending", {"type": "scope", "params": params})
        else:
            q = params
            st.session_state["q_schedule_edit"] = q
            _load_grid(q)
    elif "se_rows" not in st.session_state:
        _load_grid(q)

    # 삭제 예정 패널 (저장 전 실제 삭제 범위 안내 + 취소)
    _deleted_panel(q)

    day_cols = [c for c, _ in st.session_state["se_days"]]
    row_cols = _META + _FIXED + day_cols

    # 요약 카드 placeholder (그리드 반환값 기준으로 아래에서 채움)
    sum_ph = st.container()

    # 표 작업 영역: dirty 표시 + [행 추가] [행 삭제]
    bar_l, bar_add, bar_del = st.columns([7, 1.5, 1.5], vertical_alignment="center")
    with bar_add:
        st.button(
            "행 추가", key="se_add", icon=":material/add:", width="stretch",
            on_click=lambda: st.session_state.update(se_add_req=True),
        )
    with bar_del:
        st.button(
            "행 삭제", key="se_del", icon=":material/delete:", width="stretch",
            on_click=lambda: st.session_state.update(se_del_req=True),
        )

    col_config = {
        "사번": {"pinned": "left", "width": 112, "minWidth": 96,
                "editable": _EMP_EDITABLE, "cellClass": "md-c-left"},
        "성명": {"pinned": "left", "width": 92, "minWidth": 80,
                "editable": False, "cellClass": "md-c-left"},
        "부서": {"pinned": "left", "width": 116, "minWidth": 96, "cellClass": "md-c-left"},
        "조": {"pinned": "left", "width": 88, "minWidth": 72, "cellClass": "md-c-left"},
    }
    for c in day_cols:
        col_config[c] = {"width": 58, "minWidth": 50, "cellClass": "md-c-center"}

    # 그리드에 넘기는 데이터(se_feed)는 remount 시점 값으로 고정한다 — 매 rerun
    # 편집 결과를 되돌려주면 컴포넌트 재전송이 버튼 클릭 rerun 을 삼킬 수 있다.
    # 대신 편집 값은 매 rerun se_rows(권위 상태)에 동기화해 어떤 rerun 경로에서도
    # 미저장 입력이 보존되게 한다.
    nonce = st.session_state.setdefault("se_nonce", 0)
    feed = st.session_state.get("se_feed", st.session_state["se_rows"])
    grid_df = selectable_master_grid(
        feed,
        key=f"se_grid_{nonce}",
        columns={c: "text" for c in _FIXED + day_cols},
        order=_FIXED + day_cols,
        height=min(max(240, 35 * len(feed) + 120), 520),
        col_config=col_config,
        select_all_header=True,  # 표시 중인 기존 행만 대상 (신규 행 제외)
    )

    # 구조 변경(− 제거/붙여넣기 신규 행) + 사번 자동 조회를 권위 상태로 동기화
    if _sync_rows(grid_df, row_cols):
        st.rerun()

    live = _live(grid_df)

    # 표시/선택 건수 — 기존 행만 선택 대상 (신규 행 제외)
    existing_live = live[live["_row_state"] == "existing"] if not live.empty else live
    n_exist = len(existing_live)
    n_new = len(live) - n_exist
    n_sel = int(existing_live["_sel"].map(grid_bool).sum()) if n_exist else 0
    with bar_l:
        st.markdown(
            f"<div style='color:#8A8880; font-size:0.78rem; line-height:2rem;'>"
            f"표시 <b style='color:#3D3A34'>{n_exist}</b>명 · 신규 <b style='color:#3D3A34'>{n_new}</b>명"
            f" · 선택 <b style='color:#3D3A34'>{n_sel}</b>명</div>",
            unsafe_allow_html=True,
        )

    with sum_ph:
        _summary_cards(q, live, day_cols)
        st.write("")

    st.markdown(ui.legend_html(db.work_types_map()), unsafe_allow_html=True)
    ui.sample_mode_banner()

    # dirty 판정: 원본 스냅샷과 현재 편집 상태(정규화)를 비교
    dirty = _canon(live, st.session_state.get("se_deleted", []), day_cols) \
        != st.session_state.get("se_orig")
    st.session_state["se_dirty"] = dirty
    if dirty:
        st.session_state["nav_guard"] = {"owner": "schedule_edit"}
    elif st.session_state.get("nav_guard", {}).get("owner") == "schedule_edit":
        st.session_state.pop("nav_guard", None)

    # 브라우저 새로고침/탭 닫기 경고 (best effort — 브라우저 기본 문구 표시)
    components.html(
        "<script>window.parent.onbeforeunload = "
        + ("function(e){e.preventDefault(); e.returnValue='';};" if dirty else "null;")
        + "</script>",
        height=0,
    )

    # 미저장 이탈 확인 (사이드바 이동/로그아웃 = ui.request_nav 보류분, 조건 변경 = scope).
    # 그리드보다 아래에 렌더링해야 대화 삽입/제거가 그리드 iframe 을 재생성해
    # 미저장 편집 값을 리셋하는 일이 없다.
    pending = st.session_state.get("nav_pending")
    if pending:
        _leave_dialog(pending, q)

    # 저장 영역
    note_col, save_col = st.columns([8.4, 1.6], vertical_alignment="center")
    with note_col:
        if dirty:
            st.markdown(
                "<div style='text-align:right; color:#9A3B2E; font-size:0.78rem;'>"
                "저장되지 않은 변경사항이 있습니다</div>",
                unsafe_allow_html=True,
            )
    with save_col:
        st.button(
            "저장", key="se_save", type="primary", width="stretch",
            on_click=lambda: st.session_state.update(se_save_req=True),
        )

    # 버튼 플래그 처리 (최신 live 기준)
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
    for key in ("se_rows", "se_feed", "se_days", "se_orig", "se_orig_cells", "se_deleted", "se_dirty"):
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
    scope = users[
        users["is_active"]
        & (users["dept_code"] == q["dept"])
        & (users["team_code"] == q["team"])
    ].sort_values("emp_no")
    emp_nos = [str(e).strip() for e in scope["emp_no"]]

    scheds = db.get_month_schedules(emp_nos, q["year"], q["month"]) if emp_nos else pd.DataFrame(
        columns=db.SCHEDULE_COLUMNS
    )
    display_of, _, _ = _label_maps()
    lookup = {
        (str(r["emp_no"]).strip(), str(r["duty_date"])): str(r["work_type_code"]).strip()
        for _, r in scheds.iterrows()
    }
    with_rows = {emp for emp, _iso in lookup}

    rows = []
    for _, u in scope.iterrows():
        emp = str(u["emp_no"]).strip()
        if emp not in with_rows:
            continue  # 저장된 행이 있는 직원만 표시 (전체 자동 나열 금지)
        row = {
            "_row_id": f"e:{emp}", "_row_state": "existing", "_sel": False,
            "사번": emp,
            "성명": str(u["name"]),
            "부서": db.dept_name(u["dept_code"]),
            "조": db.team_name(u["dept_code"], u["team_code"]),
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


def _summary_cards(q: dict, live: pd.DataFrame, day_cols: list) -> None:
    filled = 0
    if not live.empty and day_cols:
        filled = int(live[day_cols].apply(
            lambda col: col.map(lambda v: bool(str(v).strip()) if pd.notna(v) else False)
        ).sum().sum())
    n_del = len(st.session_state.get("se_deleted", []))
    ui.summary_cards([
        ("입력 인원", f"{len(live)}명"),
        ("대상 월", f"{q['year']}-{q['month']:02d}"),
        ("입력 일수", f"{filled}건"),
        ("삭제 예정", f"{n_del}명"),
    ])


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
    assign_edited = False
    if content_rows:
        display_of, codes, label_codes = _label_maps()
        users = _users_by_emp()  # 조회 시점 캐시 재사용 (rerun 반복 조회 방지)
        depts = db.get_departments()
        teams = db.get_teams()
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

            if dept_code is not None and (
                dept_code != str(master["dept_code"]).strip()
                or team_code != str(master["team_code"]).strip()
            ):
                assign_edited = True

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

    # 3~5) 검증 통과 후에만 DB 변경 — 삭제 → 교체 → upsert 순.
    #      원자적이지 않으므로 실패 시 단계를 보고하고 편집 초안을 유지한다.
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
    except Exception as exc:
        st.error(
            f"저장이 '{step}' 단계에서 실패했습니다. 이전 단계까지는 반영되었을 수 있습니다.\n\n"
            f"편집 내용은 화면에 유지됩니다. [새로고침]으로 실제 저장 상태를 확인한 뒤 다시 시도하세요.\n\n{exc}"
        )
        return

    n_saved = len(records_plain) + sum(len(v) for v in records_replace.values())
    _load_grid(q)  # 6~8) 재조회 → 신규 행 existing 전환, dirty/삭제 예정/선택 초기화

    parts = [f"근무 {n_saved}건 저장"]
    if delete_only:
        parts.append(f"{len(delete_only)}명 월 근무 삭제")
    if replace_after_delete:
        parts.append(f"{len(replace_after_delete)}명 월 근무 교체")
    notes = []
    if cleared:
        notes.append(f"빈 칸으로 지운 {cleared}개 셀은 삭제되지 않고 기존 근무가 유지됩니다.")
    if assign_edited:
        notes.append("부서·조 편성값은 migration 002 적용 후 저장됩니다 (이번 저장에는 근무만 반영).")
    msg = "근무표를 저장했습니다. (" + " · ".join(parts) + ")"
    if notes:
        msg += "\n\n" + "\n".join(f"- {n}" for n in notes)
    set_flash("schedule_edit", "warning" if notes else "success", msg)
    st.rerun()
