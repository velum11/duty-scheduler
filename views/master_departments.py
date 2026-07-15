"""기준정보 — 부서 관리: 조밀한 스프레드시트형 직접 편집 화면.

행 상태 계약(_row_id/_row_state/_sel)으로 기존 저장 행과 미저장 신규 행을 분리한다.
  - 기존 행: 첫 열에 선택 체크박스 → 상단 [삭제] 대상, 선택 건수 포함
  - 신규 행: 첫 열에 − 제거 버튼 → 즉시 개별 제거(확인·DB 작업 없음), 선택 대상 아님
선택은 _sel 데이터로 명시 기록되어 신규 행에는 실릴 수 없다(팬텀 선택 원천 차단).
붙여넣기/− 제거 등 구조 변경은 Python 권위 상태(md_rows)로 정규화 후 그리드를 재마운트한다.

[삭제]는 저장된 기존 행만 처리하며, 참조 없는 부서는 실제 삭제, 참조 중이면 미사용 처리,
ADMIN 등 시스템 필수 부서는 차단한다. 화면 골격은 사이드바(차콜·오프화이트·골드)와 어울린다.
"""
import pandas as pd
import streamlit as st

from modules import db, ui
from views.workspace import grid_bool, selectable_master_grid, set_flash, show_flash

_STATUS = ["사용 중", "사용 안 함", "전체"]
_USER_COLS = ["부서코드", "부서명", "표시순서", "사용"]
_ROW_COLS = ["_row_id", "_row_state", "_sel", *_USER_COLS]
_GRID_COLUMNS = {"부서코드": "text", "부서명": "text", "표시순서": "text", "사용": "bool"}
_SYSTEM_CODES = {"ADMIN"}

_CSS = """
<style>
.st-key-md_screen .md-title {
  font-size: 1.18rem; font-weight: 700; color: #26241F; letter-spacing: -0.01em;
  margin: 0; line-height: 2rem;
}
.st-key-md_bar div[data-testid="stHorizontalBlock"] { align-items: center; }
.st-key-md_bar div.stButton > button {
  min-height: 2rem; height: 2rem; padding: 0 0.7rem; border-radius: 5px;
  font-size: 0.8rem; font-weight: 600; white-space: nowrap; gap: 0.3rem;
}
.st-key-md_bar div.stButton > button [data-testid="stIconMaterial"] { font-size: 16px; }
.st-key-md_save button[kind="primary"] {
  background: #1B1B1D !important; border: 1px solid #1B1B1D !important; color: #FFFFFF !important;
}
.st-key-md_save button[kind="primary"]:hover { background: #000000 !important; border-color: #000000 !important; }
.st-key-md_add button {
  background: #FFFFFF !important; border: 1px solid #D8D2C7 !important; color: #3D3A34 !important;
}
.st-key-md_add button:hover { background: #F1EEE9 !important; border-color: #C9A26B !important; }
.st-key-md_del button {
  background: #FFFFFF !important; border: 1px solid #E0CFC9 !important; color: #9A3B2E !important;
}
.st-key-md_del button:hover:not(:disabled) { background: #F7EFEC !important; border-color: #C77B6B !important; }
.st-key-md_del button:disabled { color: #B8B4AC !important; border-color: #E7E3DB !important; }

.st-key-md_tools { margin: 0.15rem 0 0.35rem; }
.st-key-md_tools div[data-testid="stHorizontalBlock"] { align-items: flex-end; }
.st-key-md_tools div.stButton > button {
  min-height: 2rem; height: 2rem; padding: 0 0.7rem; border-radius: 5px;
  font-size: 0.78rem; font-weight: 600; background: #FFFFFF; border: 1px solid #D8D2C7; color: #3D3A34;
}
.st-key-md_tools div.stButton > button:hover { background: #F1EEE9; border-color: #C9A26B; }

/* 표는 상단 영역 아래부터 남는 세로 공간을 반응형으로 채운다(드래그 크기조절 없음). */
.st-key-md_grid iframe {
  height: clamp(400px, calc(100vh - 250px), 720px) !important;
  min-height: 400px;
}

.st-key-md_screen .md-count { font-size: 0.76rem; color: #8A8880; margin: 0.4rem 0 0; }
.st-key-md_screen .md-count b { color: #3D3A34; font-weight: 600; }
</style>
"""


def render(user: dict) -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    source_depts = db.get_departments()

    with st.container(key="md_screen"):
        bar = st.container(key="md_bar")

        with st.container(key="md_tools"):
            f1, f2, _sp, f3 = st.columns([1.3, 2.4, 4.3, 1.0], vertical_alignment="bottom")
            active = f1.selectbox("사용 여부", _STATUS, key="md_active", label_visibility="collapsed")
            search = f2.text_input(
                "검색", key="md_search", placeholder="부서코드·부서명 검색",
                label_visibility="collapsed",
            )
            refresh = f3.button("새로고침", key="md_go", width="stretch")

        params = {"active": active, "search": search.strip()}
        if (
            refresh
            or st.session_state.get("q_master_departments") != params
            or "md_rows" not in st.session_state
        ):
            st.session_state["q_master_departments"] = params
            st.session_state.pop("md_del_plan", None)
            _load_editor(params, source_depts)

        show_flash("master_departments")

        plan = st.session_state.get("md_del_plan")
        if plan:
            _confirm_bar(plan, params)

        nonce = st.session_state.setdefault("md_nonce", 0)
        with st.container(key="md_grid"):
            grid_df = selectable_master_grid(
                st.session_state["md_rows"],
                key=f"md_grid_{nonce}",
                columns=_GRID_COLUMNS,
                order=_USER_COLS,
                height=560,
            )

        live = _live(grid_df)
        existing = live[live["_row_state"] == "existing"]
        new_rows = live[live["_row_state"] != "existing"]
        sel_count = int((existing["_sel"].map(grid_bool)).sum()) if not existing.empty else 0

        new_txt = f" · 신규 <b>{len(new_rows)}</b>건" if len(new_rows) else ""
        st.markdown(
            f"<div class='md-count'>총 <b>{len(existing)}</b>건{new_txt} · 선택 <b>{sel_count}</b>건</div>",
            unsafe_allow_html=True,
        )

        with bar:
            title, b_add, b_del, b_save = st.columns([6, 1.5, 1.3, 1.3], vertical_alignment="center")
            title.markdown("<div class='md-title'>부서 관리</div>", unsafe_allow_html=True)
            b_add.button(
                "행 추가", key="md_add", icon=":material/add:", width="stretch",
                on_click=lambda: st.session_state.update(md_add_req=True),
            )
            b_del.button(
                "삭제", key="md_del", icon=":material/delete:", width="stretch",
                disabled=sel_count == 0,
                on_click=lambda: st.session_state.update(md_del_req=True),
            )
            b_save.button(
                "저장", key="md_save", type="primary", width="stretch",
                on_click=lambda: st.session_state.update(md_save_req=True),
            )

    # 버튼 클릭 처리 (최신 grid_df 기준) — 플래그 이름은 버튼 key 와 달라야 한다.
    if st.session_state.pop("md_save_req", False):
        _save(grid_df, params)
    if st.session_state.pop("md_del_req", False):
        _handle_delete(grid_df, params)
    if st.session_state.pop("md_add_req", False):
        _add_row(grid_df)

    # 구조 변경(− 제거 / 붙여넣기 신규 행) 권위 반영 + 재마운트
    if _normalize(grid_df):
        st.rerun()


# ---------- 행 상태 헬퍼 ----------
def _live(grid_df: pd.DataFrame) -> pd.DataFrame:
    """− 로 제거 표시된 행을 제외한 현재 유효 행."""
    if "_removed" not in grid_df.columns:
        return grid_df
    keep = grid_df["_removed"].fillna("").astype(str).str.strip() != "1"
    return grid_df[keep]


def _next_rid() -> str:
    n = st.session_state.get("md_rid", 0) + 1
    st.session_state["md_rid"] = n
    return f"n:{n}"


def _next_order(rows: pd.DataFrame) -> int:
    orders = pd.to_numeric(rows.get("표시순서"), errors="coerce").dropna()
    return int(orders.max()) + 1 if len(orders) else 1


def _new_row(order_val: int) -> dict:
    return {
        "_row_id": _next_rid(), "_row_state": "new", "_sel": False,
        "부서코드": "", "부서명": "", "표시순서": str(order_val), "사용": True,
    }


def _add_row(grid_df: pd.DataFrame) -> None:
    """신규 편집 행 1개 추가. 기존 행의 편집·선택 상태는 보존한다."""
    live = _live(grid_df)
    st.session_state["md_rows"] = pd.concat(
        [live[_ROW_COLS], pd.DataFrame([_new_row(_next_order(live))])],
        ignore_index=True,
    )[_ROW_COLS]
    st.session_state["md_nonce"] = st.session_state.get("md_nonce", 0) + 1
    st.rerun()


def _normalize(grid_df: pd.DataFrame) -> bool:
    """붙여넣기로 생긴 무명 신규 행에 안정적 _row_id/_row_state 부여하고,
    − 로 제거된 행을 권위 상태에서 실제 제거한다. 구조 변경이 있으면 True.

    (팬텀을 화면에서 임시로 감추는 것이 아니라, Python 권위 상태를 그리드와 재동기화한다.)
    """
    if grid_df is None or grid_df.empty or "_row_id" not in grid_df.columns:
        return False
    removed = grid_df["_removed"].fillna("").astype(str).str.strip() == "1" if "_removed" in grid_df else pd.Series(False, index=grid_df.index)
    live = grid_df[~removed].copy()

    rid = live["_row_id"].fillna("").astype(str).str.strip()
    needs_id = rid == ""
    changed = bool(removed.any() or needs_id.any())
    if not changed:
        return False

    live["_row_id"] = rid
    for idx in live.index[needs_id]:
        live.at[idx, "_row_id"] = _next_rid()
        live.at[idx, "_row_state"] = "new"
        live.at[idx, "_sel"] = False
    # 상태값이 비어 있으면 신규로 간주
    live["_row_state"] = live["_row_state"].fillna("").astype(str).replace("", "new")

    st.session_state["md_rows"] = live[_ROW_COLS].reset_index(drop=True)
    st.session_state["md_nonce"] = st.session_state.get("md_nonce", 0) + 1
    return True


# ---------- 삭제 (기존 저장 행 전용) ----------
def _handle_delete(grid_df: pd.DataFrame, params: dict) -> None:
    live = _live(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    codes = sorted({str(c).strip() for c in sel["부서코드"] if str(c).strip()})
    if not codes:
        set_flash("master_departments", "warning", "삭제할 기존 부서를 선택하세요.")
        st.rerun()

    plan = {"delete": [], "deactivate": [], "block": []}
    for code in codes:
        if code.upper() in _SYSTEM_CODES:
            plan["block"].append(code)
            continue
        refs = db.department_reference_counts(code)
        total = sum(refs.values())
        if total > 0:
            plan["deactivate"].append({"code": code, "refs": refs})
        else:
            plan["delete"].append(code)
    st.session_state["md_del_plan"] = plan
    st.rerun()


def _ref_text(refs: dict) -> str:
    parts = []
    if refs.get("users"):
        parts.append(f"사용자 {refs['users']}명")
    if refs.get("teams"):
        parts.append(f"조 {refs['teams']}개")
    if refs.get("shift_groups"):
        parts.append(f"편성 {refs['shift_groups']}건")
    return ", ".join(parts) or "참조 있음"


def _confirm_bar(plan: dict, params: dict) -> None:
    lines = []
    if plan["delete"]:
        lines.append("삭제 가능: " + ", ".join(plan["delete"]))
    for item in plan["deactivate"]:
        lines.append(f"미사용 처리: {item['code']} — {_ref_text(item['refs'])} 참조 중")
    for code in plan["block"]:
        lines.append(f"처리 불가: {code} — 시스템 필수 부서")
    st.warning("선택한 부서를 다음과 같이 처리합니다.\n\n- " + "\n- ".join(lines))

    c1, c2, _sp = st.columns([1.4, 1.0, 6], vertical_alignment="center")
    actionable = bool(plan["delete"] or plan["deactivate"])
    if c1.button("실행", key="md_del_ok", type="primary", width="stretch", disabled=not actionable):
        _execute_delete(plan, params)
    if c2.button("취소", key="md_del_cancel", width="stretch"):
        st.session_state.pop("md_del_plan", None)
        st.rerun()


def _execute_delete(plan: dict, params: dict) -> None:
    """참조 없는 부서는 물리 삭제, 참조 중인 부서는 미사용 처리, 시스템 부서는 건너뛴다."""
    n_del = 0
    for code in plan["delete"]:
        db.delete_department(code)  # 물리 삭제 (참조 없음 확인 완료)
        n_del += 1

    deactivate_codes = [item["code"] for item in plan["deactivate"]]
    n_deact = 0
    if deactivate_codes:
        store = db.get_departments().copy()
        mask = store["dept_code"].astype(str).isin(deactivate_codes)
        n_deact = int(mask.sum())
        store.loc[mask, "is_active"] = False
        db.save_departments(store[db.DEPT_COLUMNS])

    st.session_state.pop("md_del_plan", None)
    _load_editor(params)

    parts = []
    if n_del:
        parts.append(f"{n_del}개 삭제")
    if n_deact:
        parts.append(f"{n_deact}개 미사용 처리")
    if plan["block"]:
        parts.append(f"시스템 부서 제외: {', '.join(plan['block'])}")
    msg = "부서를 " + ", ".join(parts) + "했습니다." if parts else "처리할 부서가 없습니다."
    set_flash("master_departments", "success" if (n_del or n_deact) else "warning", msg)
    st.rerun()


# ---------- 적재 / 저장 ----------
def _load_editor(q: dict, source: pd.DataFrame | None = None) -> None:
    """조회 조건(사용 여부 + 검색어)으로 저장된 부서를 편집기에 적재한다(모두 기존 행)."""
    source = db.get_departments() if source is None else source
    df = source.copy()
    if q["active"] == "사용 중":
        df = df[df["is_active"]]
    elif q["active"] == "사용 안 함":
        df = df[~df["is_active"].astype(bool)]
    term = str(q.get("search", "")).strip()
    if term:
        code_hit = df["dept_code"].astype(str).str.contains(term, case=False, na=False, regex=False)
        name_hit = df["dept_name"].astype(str).str.contains(term, case=False, na=False, regex=False)
        df = df[code_hit | name_hit]
    df = df.sort_values("sort_order").reset_index(drop=True)

    order = pd.to_numeric(df["sort_order"], errors="coerce").fillna(0).astype("int64")
    rows = pd.DataFrame({
        "_row_id": "e:" + df["dept_code"].astype(str),
        "_row_state": "existing",
        "_sel": False,
        "부서코드": df["dept_code"].fillna("").astype("string"),
        "부서명": df["dept_name"].fillna("").astype("string"),
        "표시순서": order.astype(str).astype("string"),
        "사용": df["is_active"].fillna(True).astype(bool),
    }) if not df.empty else pd.DataFrame(columns=_ROW_COLS)

    st.session_state["md_rows"] = rows[_ROW_COLS].reset_index(drop=True)
    st.session_state["md_nonce"] = st.session_state.get("md_nonce", 0) + 1


def _save(grid_df, q) -> None:
    """편집 결과를 검증하고 부서코드 기준 upsert 로 저장한다(오류 시 전체 차단)."""
    live = _live(grid_df)
    records, errors = _validate(live)

    store = db.get_departments()
    merged, dup, n_c, n_u, _n_d = db.upsert_records(
        store, records, set(), ["dept_code"], "is_active", db.DEPT_COLUMNS,
    )
    if dup:
        errors.append("부서코드가 중복되었습니다: " + ", ".join(k[0] for k in dup))
    if errors:
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return

    db.save_departments(merged)
    _load_editor(q)  # 저장된 스토어 기준 재조회 → 신규 행이 기존 행(체크박스)으로 전환
    set_flash(
        "master_departments", "success",
        f"부서를 저장했습니다. (신규 {n_c} · 수정 {n_u})",
    )
    st.rerun()


def _validate(live: pd.DataFrame):
    """표시 형태 → 저장 형태 변환 + 행별 검증. 완전히 빈 신규 행은 제외."""
    records, errors = [], []
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        code = str(row.get("부서코드") or "").strip()
        name = str(row.get("부서명") or "").strip()
        order_raw = row.get("표시순서")
        if not any([code, name]):
            continue

        tag = f"{i}행" + (f"({code})" if code else "")
        if not code:
            errors.append(f"{i}행: 부서코드를 입력하세요.")
        if not name:
            errors.append(f"{tag}: 부서명을 입력하세요.")
        try:
            order_val = int(order_raw) if str(order_raw).strip() != "" else 0
        except (TypeError, ValueError):
            order_val = 0
            errors.append(f"{tag}: 표시순서는 숫자여야 합니다.")

        records.append({
            "dept_code": code, "dept_name": name,
            "sort_order": order_val, "is_active": grid_bool(row.get("사용")),
        })
    return records, errors
