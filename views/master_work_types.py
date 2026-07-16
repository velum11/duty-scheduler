"""기준정보 — 근무형태 관리: 부서 관리와 동일한 스프레드시트형 직접 편집 화면.

행 상태 계약(_row_id/_row_state/_sel)으로 기존 저장 행과 미저장 신규 행을 분리한다.
색상 열은 HEX 텍스트 대신 색상표(네이티브 컬러 피커)로 입력하며, 저장 형식은 기존과
동일한 #RRGGBB 를 유지한다. [삭제]는 근무표에서 사용 중인 코드는 미사용 처리,
참조 없는 코드는 실제 삭제한다.
"""
import pandas as pd
import streamlit as st
from st_aggrid import JsCode

from modules import db
from views import workspace
from views.workspace import grid_bool, selectable_master_grid, set_flash, show_flash

_STATUS = ["사용 중", "사용 안 함", "전체"]
_USER_COLS = ["코드", "명칭", "분류", "약칭", "시작", "종료", "색상", "실근무", "특근수당", "설명", "표시순서", "사용"]
_BOOL_COLS = {"실근무", "특근수당", "사용"}
_ROW_COLS = ["_row_id", "_row_state", "_sel", *_USER_COLS]
_GRID_COLUMNS = {c: ("bool" if c in _BOOL_COLS else "text") for c in _USER_COLS}

# 색상 열 — 스와치 + HEX 표시(렌더러) / 네이티브 컬러 피커(에디터, 더블클릭). 저장은 #RRGGBB.
_COLOR_RENDERER = JsCode(
    """
    (class {
      init(p) {
        const v = String(p.value == null ? '' : p.value).trim();
        const valid = /^#([0-9a-fA-F]{6})$/.test(v);
        const g = document.createElement('div');
        g.style.display='flex'; g.style.alignItems='center'; g.style.height='100%'; g.style.gap='6px'; g.style.paddingLeft='6px';
        const sw = document.createElement('span');
        sw.style.width='16px'; sw.style.height='16px'; sw.style.borderRadius='3px'; sw.style.border='1px solid rgba(0,0,0,0.2)';
        sw.style.background = valid ? v : 'transparent';
        g.appendChild(sw);
        const t = document.createElement('span'); t.textContent = v; t.style.fontSize='11px'; t.style.color='#3D3A34';
        g.appendChild(t);
        this.eGui = g;
      }
      getGui() { return this.eGui; }
      refresh() { return false; }
    })
    """
)
_COLOR_EDITOR = JsCode(
    """
    (class {
      init(p) {
        const v = String(p.value == null ? '' : p.value).trim();
        this.value = /^#([0-9a-fA-F]{6})$/.test(v) ? v : '#9AA0A6';
        const g = document.createElement('div');
        g.style.display='flex'; g.style.alignItems='center'; g.style.height='100%'; g.style.gap='6px'; g.style.paddingLeft='6px';
        const input = document.createElement('input');
        input.type='color'; input.value=this.value;
        input.style.width='28px'; input.style.height='22px'; input.style.border='none'; input.style.background='transparent'; input.style.cursor='pointer';
        const hex = document.createElement('span'); hex.textContent=this.value; hex.style.fontSize='11px'; hex.style.color='#3D3A34';
        input.addEventListener('input', () => { this.value = input.value; hex.textContent = input.value; });
        g.appendChild(input); g.appendChild(hex);
        this.eGui = g; this.eInput = input;
      }
      getGui() { return this.eGui; }
      afterGuiAttached() { this.eInput.focus(); }
      getValue() { return String(this.value || '').toUpperCase(); }
      isPopup() { return false; }
    })
    """
)

def render(user: dict) -> None:
    workspace.master_screen_head(
        "근무형태 관리", "근무형태(코드·명칭·약칭·색상)를 표에서 직접 편집하고 [저장]으로 일괄 반영합니다.",
    )

    refresh = st.session_state.pop("ms_refresh_req", False)
    with st.container(key="ms_filter"):
        f1, f2, _sp = st.columns([1.4, 3.0, 5.6], vertical_alignment="bottom")
        active = f1.selectbox("사용 여부", _STATUS, key="mw_active", label_visibility="collapsed")
        search = f2.text_input("검색", key="mw_search", placeholder="코드·명칭·약칭 검색", label_visibility="collapsed")

    params = {"active": active, "search": search.strip()}
    if refresh or st.session_state.get("q_master_work_types") != params or "mw_rows" not in st.session_state:
        st.session_state["q_master_work_types"] = params
        st.session_state.pop("mw_del_plan", None)
        _load_editor(params)

    show_flash("master_work_types")

    plan = st.session_state.get("mw_del_plan")
    if plan:
        _confirm_bar(plan, params)

    bar = st.container(key="ms_bar")

    nonce = st.session_state.setdefault("mw_nonce", 0)
    col_config = {
        "코드": {"width": 96, "minWidth": 80, "cellClass": "md-c-left"},
        "명칭": {"width": 110, "minWidth": 90, "cellClass": "md-c-left"},
        "분류": {"width": 84, "minWidth": 70, "cellClass": "md-c-left"},
        "약칭": {"width": 72, "minWidth": 56, "cellClass": "md-c-center"},
        "시작": {"width": 78, "minWidth": 64, "cellClass": "md-c-center"},
        "종료": {"width": 78, "minWidth": 64, "cellClass": "md-c-center"},
        "색상": {"width": 118, "minWidth": 100, "cellClass": "md-c-left",
                "cellRenderer": _COLOR_RENDERER, "cellEditor": _COLOR_EDITOR},
        "실근무": {"width": 78, "minWidth": 64, "cellClass": "md-c-center"},
        "특근수당": {"width": 88, "minWidth": 72, "cellClass": "md-c-center"},
        "설명": {"flex": 1, "minWidth": 140, "cellClass": "md-c-left"},
        "표시순서": {"width": 96, "minWidth": 80, "cellClass": "md-c-center"},
        "사용": {"width": 74, "minWidth": 64, "cellClass": "md-c-center"},
    }
    rows = st.session_state["mw_rows"]
    with st.container(key="ms_grid"):
        grid_df = selectable_master_grid(
            rows, key=f"mw_grid_{nonce}", columns=_GRID_COLUMNS, order=_USER_COLS,
            height=workspace.master_grid_height(len(rows)),
            col_config=col_config, select_all_header=True,
        )

    live = _live(grid_df)
    existing = live[live["_row_state"] == "existing"]
    new_rows = live[live["_row_state"] != "existing"]
    sel_count = int((existing["_sel"].map(grid_bool)).sum()) if not existing.empty else 0
    workspace.master_count(len(existing), len(new_rows), sel_count)

    with bar:
        workspace.master_action_bar(sel_count)

    if st.session_state.pop("ms_save_req", False):
        _save(grid_df, params)
    if st.session_state.pop("ms_del_req", False):
        _handle_delete(grid_df, params)
    if st.session_state.pop("ms_add_req", False):
        _add_row(grid_df)
    if _normalize(grid_df):
        st.rerun()


# ---------- 행 상태 헬퍼 ----------
def _live(grid_df: pd.DataFrame) -> pd.DataFrame:
    if "_removed" not in grid_df.columns:
        return grid_df
    return grid_df[grid_df["_removed"].fillna("").astype(str).str.strip() != "1"]


def _next_rid() -> str:
    n = st.session_state.get("mw_rid", 0) + 1
    st.session_state["mw_rid"] = n
    return f"n:{n}"


def _next_order(rows: pd.DataFrame) -> int:
    orders = pd.to_numeric(rows.get("표시순서"), errors="coerce").dropna()
    return int(orders.max()) + 1 if len(orders) else 1


def _new_row(order_val: int) -> dict:
    row = {"_row_id": _next_rid(), "_row_state": "new", "_sel": False}
    for c in _USER_COLS:
        row[c] = (c == "사용") if c in _BOOL_COLS else ""
    row["색상"] = "#9AA0A6"
    row["표시순서"] = str(order_val)
    return row


def _add_row(grid_df: pd.DataFrame) -> None:
    live = _live(grid_df)
    st.session_state["mw_rows"] = pd.concat(
        [live[_ROW_COLS], pd.DataFrame([_new_row(_next_order(live))])], ignore_index=True,
    )[_ROW_COLS]
    st.session_state["mw_nonce"] = st.session_state.get("mw_nonce", 0) + 1
    st.rerun()


def _normalize(grid_df: pd.DataFrame) -> bool:
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
    live["_row_state"] = live["_row_state"].fillna("").astype(str).replace("", "new")
    st.session_state["mw_rows"] = live[_ROW_COLS].reset_index(drop=True)
    st.session_state["mw_nonce"] = st.session_state.get("mw_nonce", 0) + 1
    return True


# ---------- 삭제 (기존 저장 행 전용) ----------
def _handle_delete(grid_df: pd.DataFrame, params: dict) -> None:
    live = _live(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    codes = sorted({str(c).strip() for c in sel["코드"] if str(c).strip()})
    if not codes:
        set_flash("master_work_types", "warning", "삭제할 기존 근무형태를 선택하세요.")
        st.rerun()
    plan = {"delete": [], "deactivate": []}
    for code in codes:
        refs = db.work_type_reference_counts(code)
        item = {"code": code, "refs": refs}
        (plan["deactivate"] if sum(refs.values()) > 0 else plan["delete"]).append(item)
    st.session_state["mw_del_plan"] = plan
    st.rerun()


def _confirm_bar(plan: dict, params: dict) -> None:
    lines = []
    if plan["delete"]:
        lines.append("삭제 가능: " + ", ".join(it["code"] for it in plan["delete"]))
    for it in plan["deactivate"]:
        lines.append(f"미사용 처리: {it['code']} — 근무표 {it['refs'].get('schedules', 0)}건 사용 중")
    st.warning("선택한 근무형태를 다음과 같이 처리합니다.\n\n- " + "\n- ".join(lines))
    c1, c2, _sp = st.columns([1.4, 1.0, 6], vertical_alignment="center")
    if c1.button("실행", key="mw_del_ok", type="primary", width="stretch"):
        _execute_delete(plan, params)
    if c2.button("취소", key="mw_del_cancel", width="stretch"):
        st.session_state.pop("mw_del_plan", None)
        st.rerun()


def _execute_delete(plan: dict, params: dict) -> None:
    n_del = 0
    for it in plan["delete"]:
        db.delete_work_type(it["code"])
        n_del += 1
    deact = plan["deactivate"]
    n_deact = 0
    if deact:
        store = db.get_work_types().copy()
        codes = [it["code"] for it in deact]
        mask = store["code"].astype(str).isin(codes)
        n_deact = int(mask.sum())
        store.loc[mask, "is_active"] = False
        db.save_work_types(store[db.WORK_TYPE_COLUMNS])
    st.session_state.pop("mw_del_plan", None)
    _load_editor(params)
    parts = []
    if n_del:
        parts.append(f"{n_del}개 삭제")
    if n_deact:
        parts.append(f"{n_deact}개 미사용 처리")
    msg = "근무형태를 " + ", ".join(parts) + "했습니다." if parts else "처리할 근무형태가 없습니다."
    set_flash("master_work_types", "success" if (n_del or n_deact) else "warning", msg)
    st.rerun()


# ---------- 적재 / 저장 ----------
def _load_editor(q: dict) -> None:
    df = db.get_work_types().copy()
    if q["active"] == "사용 중":
        df = df[df["is_active"]]
    elif q["active"] == "사용 안 함":
        df = df[~df["is_active"].astype(bool)]
    term = str(q.get("search", "")).strip()
    if term:
        hit = (
            df["code"].astype(str).str.contains(term, case=False, na=False, regex=False)
            | df["name"].astype(str).str.contains(term, case=False, na=False, regex=False)
            | df["short_label"].astype(str).str.contains(term, case=False, na=False, regex=False)
        )
        df = df[hit]
    df = df.sort_values("sort_order").reset_index(drop=True)

    order = pd.to_numeric(df["sort_order"], errors="coerce").fillna(0).astype("int64")
    if df.empty:
        st.session_state["mw_rows"] = pd.DataFrame(columns=_ROW_COLS)
    else:
        st.session_state["mw_rows"] = pd.DataFrame({
            "_row_id": "e:" + df["code"].astype(str),
            "_row_state": "existing", "_sel": False,
            "코드": df["code"].fillna("").astype("string"),
            "명칭": df["name"].fillna("").astype("string"),
            "분류": df["category"].fillna("").astype("string"),
            "약칭": df["short_label"].fillna("").astype("string"),
            "시작": df["start_time"].fillna("").astype("string"),
            "종료": df["end_time"].fillna("").astype("string"),
            "색상": df["color"].fillna("").astype("string"),
            "실근무": df["is_work"].fillna(False).astype(bool),
            "특근수당": df["affects_allowance"].fillna(False).astype(bool),
            "설명": df["description"].fillna("").astype("string"),
            "표시순서": order.astype(str).astype("string"),
            "사용": df["is_active"].fillna(True).astype(bool),
        })[_ROW_COLS]
    st.session_state["mw_nonce"] = st.session_state.get("mw_nonce", 0) + 1


def _save(grid_df, q) -> None:
    live = _live(grid_df)
    records, errors = _validate(live)
    store = db.get_work_types()
    merged, dup, n_c, n_u, _n_d = db.upsert_records(
        store, records, set(), ["code"], "is_active", db.WORK_TYPE_COLUMNS,
    )
    if dup:
        errors.append("근무형태 코드가 중복되었습니다: " + ", ".join(k[0] for k in dup))
    if errors:
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return
    db.save_work_types(merged)
    _load_editor(q)
    set_flash("master_work_types", "success", f"근무형태를 저장했습니다. (신규 {n_c} · 수정 {n_u})")
    st.rerun()


def _validate(live: pd.DataFrame):
    records, errors = [], []
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        code = str(row.get("코드") or "").strip()
        name = str(row.get("명칭") or "").strip()
        category = str(row.get("분류") or "").strip()
        short_label = str(row.get("약칭") or "").strip()
        if not any([code, name, category, short_label]):
            continue

        tag = f"{i}행" + (f"({code})" if code else "")
        if not code:
            errors.append(f"{i}행: 근무형태 코드를 입력하세요.")
        if not name:
            errors.append(f"{tag}: 근무형태명을 입력하세요.")
        if not short_label:
            errors.append(f"{tag}: 약칭을 입력하세요.")
        if not category:
            errors.append(f"{tag}: 분류를 입력하세요.")

        try:
            order_val = int(row.get("표시순서")) if str(row.get("표시순서")).strip() != "" else 0
        except (TypeError, ValueError):
            order_val = 0
            errors.append(f"{tag}: 표시순서는 숫자여야 합니다.")

        records.append({
            "code": code, "name": name, "category": category, "short_label": short_label,
            "start_time": str(row.get("시작") or "").strip(),
            "end_time": str(row.get("종료") or "").strip(),
            "color": str(row.get("색상") or "").strip(),
            "is_work": grid_bool(row.get("실근무")),
            "affects_allowance": grid_bool(row.get("특근수당")),
            "description": str(row.get("설명") or "").strip(),
            "sort_order": order_val,
            "is_active": grid_bool(row.get("사용")),
        })
    return records, errors
