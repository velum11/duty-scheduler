"""기준정보 — 근무형태 관리 화면.

조회 조건으로 대상을 불러온 뒤 스프레드시트형 편집기(st.data_editor)로 등록/수정한다.
[저장] 을 눌렀을 때만 검증 후 반영하며(자동 저장 없음), 로컬 샘플 모드에서는
세션 상태(db.save_work_types)에 저장해 현재 세션 동안 유지된다.

'사용 중'만 조회했더라도 저장 시 미조회 근무형태(미사용 등)는 그대로 보존한다
(조회 대상만 교체 후 병합). 색상 값은 비어 있어도 저장할 수 있다.
"""
import pandas as pd
import streamlit as st

from modules import db, ui
from views.workspace import grid_height, save_bar, set_flash, show_flash

_COLS = [
    "코드", "명칭", "분류", "약칭", "시작", "종료", "색상",
    "실근무", "특근수당", "설명", "표시순서", "사용",
]
_STATUS = ["사용 중", "사용 안 함", "전체"]


def render(user: dict) -> None:
    ui.page_header("master_work_types")

    # 조회 조건 카드
    with ui.card():
        c1, c2 = st.columns([1.4, 0.9], vertical_alignment="bottom")
        active = c1.selectbox("사용 여부", _STATUS, key="mw_active")
        clicked = c2.button("새로고침", key="mw_go", type="primary", width="stretch")

    # 화면 진입 시 기본 필터로 자동 조회, [새로고침] 시 현재 필터로 재조회.
    params = {"active": active}
    q = st.session_state.get("q_master_work_types")
    if clicked or q is None:
        q = params
        st.session_state["q_master_work_types"] = q
        _load_editor(q)
    elif "mw_work" not in st.session_state:  # rerun 등으로 조건만 남고 편집본이 없을 때
        _load_editor(q)

    show_flash("master_work_types")

    # 요약 카드 (편집 중인 내용 기준으로 갱신)
    sum_ph = st.container()

    # 스프레드시트형 편집 그리드 (행 추가 가능)
    edited = st.data_editor(
        st.session_state["mw_work"],
        key="mw_editor",
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        height=grid_height(len(st.session_state["mw_work"]) + 1),
        column_config={
            "코드": st.column_config.TextColumn("코드", width="small"),
            "명칭": st.column_config.TextColumn("명칭", width="small"),
            "분류": st.column_config.TextColumn("분류", width="small"),
            "약칭": st.column_config.TextColumn("약칭", width="small"),
            "시작": st.column_config.TextColumn("시작", width="small"),
            "종료": st.column_config.TextColumn("종료", width="small"),
            "색상": st.column_config.TextColumn("색상", width="small"),
            "실근무": st.column_config.CheckboxColumn("실근무", width="small"),
            "특근수당": st.column_config.CheckboxColumn("특근수당", width="small"),
            "설명": st.column_config.TextColumn("설명"),
            "표시순서": st.column_config.NumberColumn(
                "표시순서", width="small", min_value=0, step=1,
            ),
            "사용": st.column_config.CheckboxColumn("사용", width="small", default=True),
        },
    )

    with sum_ph:
        _summary_cards(edited)

    # 색상 범례 (색상이 지정된 코드만)
    legend = [
        (str(r["코드"]).strip(), str(r["색상"]).strip())
        for _, r in edited.iterrows()
        if str(r["코드"] or "").strip() and str(r["색상"] or "").strip()
    ]
    if legend:
        badges = "".join(ui.badge_html(code, color) for code, color in legend)
        st.markdown(f"<div class='duty-legend'>{badges}</div>", unsafe_allow_html=True)

    if save_bar("mw"):
        _save(edited, q)


def _to_display(df: pd.DataFrame) -> pd.DataFrame:
    """저장 형태 → 편집기 표시 형태."""
    return pd.DataFrame({
        "코드": df["code"].astype(str),
        "명칭": df["name"].astype(str),
        "분류": df["category"].astype(str),
        "약칭": df["short_label"].astype(str),
        "시작": df["start_time"].astype(str),
        "종료": df["end_time"].astype(str),
        "색상": df["color"].astype(str),
        "실근무": df["is_work"].astype(bool),
        "특근수당": df["affects_allowance"].astype(bool),
        "설명": df["description"].astype(str),
        "표시순서": df["sort_order"].astype(int),
        "사용": df["is_active"].astype(bool),
    })


def _load_editor(q: dict) -> None:
    """조회 조건으로 대상 근무형태를 편집기에 적재하고, 원본 코드 집합을 스냅샷한다."""
    df = db.get_work_types()
    if q["active"] == "사용 중":
        df = df[df["is_active"]]
    elif q["active"] == "사용 안 함":
        df = df[~df["is_active"].astype(bool)]
    df = df.sort_values("sort_order").reset_index(drop=True)

    st.session_state["mw_work"] = _to_display(df)
    st.session_state["mw_loaded"] = [(str(c).strip(),) for c in df["code"]]
    st.session_state.pop("mw_editor", None)  # 이전 편집 상태 초기화


def _summary_cards(edited: pd.DataFrame) -> None:
    is_work = edited["실근무"].fillna(False).astype(bool)
    ui.summary_cards([
        ("근무형태", f"{len(edited)}개"),
        ("사용 중", f"{int(edited['사용'].fillna(False).astype(bool).sum())}개"),
        ("실근무 코드", f"{int(is_work.sum())}개"),
        ("휴무·휴가 코드", f"{int((~is_work).sum())}개"),
    ])
    st.write("")


def _save(edited: pd.DataFrame, q: dict) -> None:
    """편집 결과를 검증하고, 자연키 기준 upsert 로 스토어에 병합해 저장한다."""
    records, errors = _validate(edited)

    # 기존 행은 U, 신규 행은 C, 조회했다가 사라진 행은 사용=False 소프트 삭제.
    loaded = set(st.session_state.get("mw_loaded", []))
    store = db.get_work_types()
    merged, dup, n_c, n_u, n_d = db.upsert_records(
        store, records, loaded, ["code"], "is_active", db.WORK_TYPE_COLUMNS,
    )
    if dup:
        errors.append("근무형태 코드가 중복되었습니다: " + ", ".join(k[0] for k in dup))

    if errors:
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return

    db.save_work_types(merged)
    st.session_state.pop("mw_editor", None)
    _load_editor(q)  # 저장된 스토어 기준으로 편집기 새로고침
    set_flash(
        "master_work_types", "success",
        f"근무형태를 저장했습니다. (신규 {n_c} · 수정 {n_u} · 미사용 처리 {n_d})",
    )
    st.rerun()


def _validate(edited: pd.DataFrame):
    """표시 형태 → 저장 형태 변환 + 행별 기본 검증. (records, errors) 반환."""
    records, errors = [], []
    for i, (_, row) in enumerate(edited.iterrows(), start=1):
        code = str(row["코드"] or "").strip()
        name = str(row["명칭"] or "").strip()
        category = str(row["분류"] or "").strip()
        short_label = str(row["약칭"] or "").strip()

        # 완전히 빈 행(새 행 자동 추가분)은 조용히 건너뛴다
        if not any([code, name, category, short_label]):
            continue

        tag = f"{i}행" + (f"({code})" if code else "")
        if not code:
            errors.append(f"{i}행: 근무형태 코드를 입력하세요.")
        if not name:
            errors.append(f"{tag}: 근무형태명을 입력하세요.")
        if not short_label:
            errors.append(f"{tag}: 약칭(short_label)을 입력하세요.")
        if not category:
            errors.append(f"{tag}: 분류(category)를 입력하세요.")

        try:
            so = row["표시순서"]
            sort_order = 0 if pd.isna(so) else int(so)
        except (TypeError, ValueError):
            sort_order = 0

        records.append({
            "code": code,
            "name": name,
            "category": category,
            "short_label": short_label,
            "start_time": str(row["시작"] or "").strip(),
            "end_time": str(row["종료"] or "").strip(),
            "color": str(row["색상"] or "").strip(),
            "is_work": bool(row["실근무"]),
            "affects_allowance": bool(row["특근수당"]),
            "description": str(row["설명"] or "").strip(),
            "sort_order": sort_order,
            "is_active": bool(row["사용"]),
        })
    return records, errors
