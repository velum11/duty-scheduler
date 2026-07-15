"""기준정보 — 부서 관리: 조밀한 스프레드시트형 직접 편집 화면.

목록에서 직접 입력·수정하고 [저장]으로 일괄 반영한다(자동 저장 없음).
Excel 의 여러 행·열(탭/줄바꿈 구분)을 그대로 붙여넣을 수 있고, [＋ 행 추가]로
필요할 때만 신규 편집 행을 추가한다(기본 화면에는 영구 빈 행을 두지 않는다).
부서는 물리 삭제하지 않고 사용 여부(is_active)로 관리한다(소프트 삭제).

화면 골격은 사이드바(다크 차콜·오프화이트·골드)와 어울리게 구성하며,
요약 카드·큰 조회 카드·하단 등록 폼을 두지 않는다.
"""
import pandas as pd
import streamlit as st

from modules import db, ui
from views.workspace import editable_aggrid, grid_bool, set_flash, show_flash

_STATUS = ["사용 중", "사용 안 함", "전체"]
_COLS = ["선택", "부서코드", "부서명", "표시순서", "사용"]

# 이 화면 전용 CSS. app_shell 의 사이드바 토큰(--sb-bg/--gold/--line 등)과 같은 계열을
# 쓰고 네이비를 새로 만들지 않는다. 버튼 key 로 스코프를 좁혀 다른 화면에 영향을 주지 않는다.
_CSS = """
<style>
.st-key-md_screen .md-title {
  font-size: 1.18rem; font-weight: 700; color: #26241F; letter-spacing: -0.01em;
  margin: 0; line-height: 2rem;
}
/* 제목 행: 제목 + 우측 액션 버튼을 한 줄로 정렬 */
.st-key-md_bar div[data-testid="stHorizontalBlock"] { align-items: center; }
.st-key-md_bar div.stButton > button {
  min-height: 2rem; height: 2rem; padding: 0 0.7rem; border-radius: 5px;
  font-size: 0.8rem; font-weight: 600; white-space: nowrap; gap: 0.3rem;
}
.st-key-md_bar div.stButton > button [data-testid="stIconMaterial"] { font-size: 16px; }
/* [저장] — 사이드바 계열 차콜 Primary (네이비 오버라이드) */
.st-key-md_save button[kind="primary"] {
  background: #1B1B1D !important; border: 1px solid #1B1B1D !important; color: #FFFFFF !important;
}
.st-key-md_save button[kind="primary"]:hover { background: #000000 !important; border-color: #000000 !important; }
/* [＋ 행 추가] — 보조 */
.st-key-md_add button {
  background: #FFFFFF !important; border: 1px solid #D8D2C7 !important; color: #3D3A34 !important;
}
.st-key-md_add button:hover { background: #F1EEE9 !important; border-color: #C9A26B !important; }
/* [삭제] — 경고 의미(과하지 않은 벽돌색) */
.st-key-md_del button {
  background: #FFFFFF !important; border: 1px solid #E0CFC9 !important; color: #9A3B2E !important;
}
.st-key-md_del button:hover:not(:disabled) { background: #F7EFEC !important; border-color: #C77B6B !important; }
.st-key-md_del button:disabled { color: #B8B4AC !important; border-color: #E7E3DB !important; }

/* 도구 모음: 작은 한 줄(큰 카드 아님) */
.st-key-md_tools { margin: 0.15rem 0 0.35rem; }
.st-key-md_tools div[data-testid="stHorizontalBlock"] { align-items: flex-end; }
.st-key-md_tools div.stButton > button {
  min-height: 2rem; height: 2rem; padding: 0 0.7rem; border-radius: 5px;
  font-size: 0.78rem; font-weight: 600; background: #FFFFFF; border: 1px solid #D8D2C7; color: #3D3A34;
}
.st-key-md_tools div.stButton > button:hover { background: #F1EEE9; border-color: #C9A26B; }

/* 총 건수 / 선택 건수 — 작게 */
.st-key-md_screen .md-count { font-size: 0.76rem; color: #8A8880; margin: 0.35rem 0 0; }
.st-key-md_screen .md-count b { color: #3D3A34; font-weight: 600; }
</style>
"""


def _grid_height(nrows: int) -> int:
    """행 수에 맞춘 조밀한 높이. 적으면 필요한 만큼, 많으면 최대에서 내부 스크롤."""
    return max(132, min(30 * nrows + 46, 460))


def _next_order(edited: pd.DataFrame) -> int:
    """신규 행에 미리 채울 표시순서(현재 최대값 + 1, 최소 1)."""
    orders = pd.to_numeric(edited.get("표시순서"), errors="coerce").dropna()
    return int(orders.max()) + 1 if len(orders) else 1


def render(user: dict) -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    source_depts = db.get_departments()

    with st.container(key="md_screen"):
        # 제목 + 우측 액션 버튼(그리드 이후 채운다 — 선택 건수를 정확히 반영하기 위함)
        bar = st.container(key="md_bar")

        # 도구 모음 (작은 한 줄): 사용 여부 · 검색 · 새로고침
        with st.container(key="md_tools"):
            f1, f2, _sp, f3 = st.columns([1.3, 2.4, 4.3, 1.0], vertical_alignment="bottom")
            active = f1.selectbox("사용 여부", _STATUS, key="md_active", label_visibility="collapsed")
            search = f2.text_input(
                "검색", key="md_search", placeholder="부서코드·부서명 검색",
                label_visibility="collapsed",
            )
            refresh = f3.button("새로고침", key="md_go", width="stretch")

        # 목록 적재: 필터/검색 변경 · 새로고침 · 최초 진입 시에만 DB 재조회.
        params = {"active": active, "search": search.strip()}
        if (
            refresh
            or st.session_state.get("q_master_departments") != params
            or "md_work" not in st.session_state
        ):
            st.session_state["q_master_departments"] = params
            _load_editor(params, source_depts)

        show_flash("master_departments")

        # 기존 부서 삭제 확인 바 (미저장 신규 행은 확인 없이 이미 제거됨)
        pending = st.session_state.get("md_pending_delete")
        if pending:
            _confirm_bar(pending, params)

        # 그리드에 넘기는 데이터(md_work)는 조회 시점 값으로 고정한다. 편집 결과를 매
        # rerun 되돌려주면 컴포넌트 재전송이 이어지는 버튼 클릭 rerun 을 삼킬 수 있다.
        # 편집 내용은 반환값(edited)으로 받고, 행 확장은 그리드 내부(JS)가 처리한다.
        nonce = st.session_state.setdefault("md_nonce", 0)
        edited = editable_aggrid(
            st.session_state["md_work"],
            key=f"md_editor_{nonce}",
            columns={
                "선택": "bool",
                "부서코드": "text",
                "부서명": "text",
                "표시순서": "text",
                "사용": "bool",
            },
            height=_grid_height(len(st.session_state["md_work"])),
            blank_rows=0,  # 영구 빈 행 없음 — 신규 행은 [＋ 행 추가]로만 생성
        )

        # 저장 대상(빈 행 제외)과 선택 건수 계산
        real = edited[
            edited[["부서코드", "부서명"]]
            .fillna("").astype(str)
            .apply(lambda r: r.str.strip().ne("").any(), axis=1)
        ]
        sel_count = int(edited["선택"].map(grid_bool).sum()) if "선택" in edited else 0

        st.markdown(
            f"<div class='md-count'>총 <b>{len(real)}</b>건 · 선택 <b>{sel_count}</b>건</div>",
            unsafe_allow_html=True,
        )

        # 제목 행(버튼 포함)을 이제 채운다 — sel_count 를 정확히 반영
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

    # 클릭 플래그 처리 (최신 edited 기준) — 플래그 이름은 버튼 key 와 달라야 한다.
    if st.session_state.pop("md_add_req", False):
        _add_row(edited)
    if st.session_state.pop("md_del_req", False):
        _handle_delete(edited, params)
    if st.session_state.pop("md_save_req", False):
        _save(edited, params)


def _add_row(edited: pd.DataFrame) -> None:
    """표 끝에 신규 편집 행 1개 추가. 표시순서를 미리 채워 빈 행 정리에 지워지지 않게 한다."""
    newrow = {
        "선택": False, "부서코드": "", "부서명": "",
        "표시순서": str(_next_order(edited)), "사용": True,
    }
    base = edited.assign(선택=False)
    st.session_state["md_work"] = pd.concat(
        [base, pd.DataFrame([newrow])], ignore_index=True,
    )[_COLS]
    st.session_state["md_nonce"] = st.session_state.get("md_nonce", 0) + 1
    st.rerun()


def _handle_delete(edited: pd.DataFrame, params: dict) -> None:
    """선택 행 삭제. 미저장 신규 행은 즉시 제거, 기존 행은 확인 후 미사용 처리."""
    # 선택된 행 중 완전히 빈 행(코드·명 모두 없음)은 삭제 대상에서 제외한다.
    # (st_aggrid 반환 desync 로 빈 버퍼 행에 선택값이 실려도 오삭제되지 않게 함)
    nonempty = edited[["부서코드", "부서명"]].fillna("").astype(str).apply(
        lambda r: r.str.strip().ne("").any(), axis=1
    )
    sel = edited[edited["선택"].map(grid_bool) & nonempty]
    if sel.empty:
        set_flash("master_departments", "warning", "삭제할 행을 선택하세요.")
        st.rerun()

    store_codes = set(db.get_departments()["dept_code"].astype(str))
    codes = sel["부서코드"].astype(str).str.strip()
    is_existing = codes.isin(store_codes) & codes.ne("")

    new_idx = sel[~is_existing].index
    existing_codes = sorted(set(codes[is_existing]))

    # 미저장 신규 행은 즉시 제거하고 나머지 편집 상태는 보존(선택 해제).
    remaining = edited.drop(index=new_idx).assign(선택=False)
    st.session_state["md_work"] = remaining[_COLS].reset_index(drop=True)
    st.session_state["md_nonce"] = st.session_state.get("md_nonce", 0) + 1

    if existing_codes:
        st.session_state["md_pending_delete"] = existing_codes
    elif len(new_idx):
        set_flash("master_departments", "success", f"신규 행 {len(new_idx)}개를 삭제했습니다.")
    st.rerun()


def _confirm_bar(codes: list[str], params: dict) -> None:
    """기존 부서 미사용 처리 확인 바."""
    st.warning(
        "선택한 기존 부서를 미사용 처리합니다 (데이터는 삭제하지 않습니다): "
        + ", ".join(codes)
    )
    c1, c2, _sp = st.columns([1.2, 1.0, 6], vertical_alignment="center")
    if c1.button("미사용 처리", key="md_del_ok", type="primary", width="stretch"):
        _soft_delete(codes, params)
    if c2.button("취소", key="md_del_cancel", width="stretch"):
        st.session_state.pop("md_pending_delete", None)
        st.rerun()


def _soft_delete(codes: list[str], params: dict) -> None:
    """기존 부서를 is_active=False 로 미사용 처리(소프트 삭제). 시스템 필수 부서는 제외."""
    blocked = [c for c in codes if c.upper() == "ADMIN"]
    targets = [c for c in codes if c.upper() != "ADMIN"]

    store = db.get_departments().copy()
    mask = store["dept_code"].astype(str).isin(targets)
    n = int(mask.sum())
    store.loc[mask, "is_active"] = False
    db.save_departments(store[db.DEPT_COLUMNS])

    # 참조 인원 안내 (물리 삭제가 아니므로 관계는 유지된다)
    users = db.get_users()
    ref = int(users[users["dept_code"].astype(str).isin(targets)].shape[0]) if not users.empty else 0

    st.session_state.pop("md_pending_delete", None)
    _load_editor(params)
    msg = f"기존 부서 {n}개를 미사용 처리했습니다."
    if ref:
        msg += f" (소속 {ref}명은 관계 유지)"
    if blocked:
        msg += f" 시스템 필수 부서 제외: {', '.join(blocked)}"
    set_flash("master_departments", "success" if n else "warning", msg)
    st.rerun()


def _to_display(df: pd.DataFrame) -> pd.DataFrame:
    """저장 형태 → 편집기 표시 형태.

    표시순서는 AG Grid 숫자 컬럼의 Excel 붙여넣기 값 반영 문제를 피하려고
    (공용 editable_aggrid 의 "number" 컬럼은 붙여넣은 문자열이 반영되지 않는다)
    텍스트 컬럼으로 표시하고, 저장 시 정수로 변환한다. 선택 컬럼은 삭제 대상
    선택용 화면 전용 값으로 DB 에 저장하지 않는다.
    """
    order = pd.to_numeric(df["sort_order"], errors="coerce").fillna(0).astype("int64")
    return pd.DataFrame({
        "선택": False,
        "부서코드": df["dept_code"].fillna("").astype("string"),
        "부서명": df["dept_name"].fillna("").astype("string"),
        "표시순서": order.astype(str).astype("string"),
        "사용": df["is_active"].fillna(True).astype(bool),
    })


def _load_editor(q: dict, source: pd.DataFrame | None = None) -> None:
    """조회 조건(사용 여부 + 검색어)으로 대상 부서를 편집기에 적재한다."""
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

    st.session_state["md_work"] = _to_display(df)
    st.session_state["md_nonce"] = st.session_state.get("md_nonce", 0) + 1


def _save(edited, q) -> None:
    """편집 결과를 검증하고, 부서코드 기준 upsert 로 병합해 저장한다.

    검증 오류가 하나라도 있으면 아무것도 저장하지 않는다(전체 성공/전체 차단).
    upsert 는 코드 기준이라 기존 코드를 제자리 변경하지 않는다(관계키 보존).
    필터로 보이지 않는 기존 부서를 자동 미사용 처리하지 않는다.
    """
    records, errors = _validate(edited)

    store = db.get_departments()
    merged, dup, n_c, n_u, n_d = db.upsert_records(
        store, records, set(), ["dept_code"], "is_active", db.DEPT_COLUMNS,
    )
    if dup:
        errors.append("부서코드가 중복되었습니다: " + ", ".join(k[0] for k in dup))

    if errors:
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return

    db.save_departments(merged)
    _load_editor(q)  # 저장된 스토어 기준으로 편집기 새로고침 (미저장 신규 상태 정리)
    set_flash(
        "master_departments", "success",
        f"부서를 저장했습니다. (신규 {n_c} · 수정 {n_u})",
    )
    st.rerun()


def _validate(edited):
    """표시 형태 → 저장 형태 변환 + 행별 기본 검증. (records, errors) 반환.

    선택 컬럼은 화면 전용이므로 저장 레코드에 포함하지 않는다.
    """
    records, errors = [], []
    for i, (_, row) in enumerate(edited.iterrows(), start=1):
        code = str(row.get("부서코드") or "").strip()
        name = str(row.get("부서명") or "").strip()
        order_raw = row.get("표시순서")

        # 완전히 빈 신규 행(코드·명 모두 없음)은 조용히 건너뛴다
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
            "dept_code": code,
            "dept_name": name,
            "sort_order": order_val,
            "is_active": grid_bool(row.get("사용")),
        })
    return records, errors
