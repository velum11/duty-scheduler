"""데이터 접근 계층 (sample/Supabase facade).

데이터 모드는 설정에서 명시적으로 선택하며, Supabase 오류를 sample 모드로 숨기지 않는다.
화면/로직 코드는 이 모듈의 자연키 기반 함수만 호출한다.

저장 계층(CSV/Supabase)은 docs/database.md 대로 id 기반(department_id / team_id /
user_id)이다. 화면은 자연키(dept_code / team_code / emp_no / duty_date)를 쓰므로,
이 파사드에서 기준정보를 조인해 자연키 컬럼을 덧붙여 반환한다. 원본(캐시된)
DataFrame 을 훼손하지 않도록 항상 copy 후 컬럼을 추가한다.
"""
import hashlib

import pandas as pd
import streamlit as st

from modules import config, sample_data, supabase_repository, validators

DATA_SOURCE_ERRORS = (
    config.DataSourceConfigurationError,
    supabase_repository.SupabaseDataError,
)

# 화면이 사용하는 사용자 자연키 컬럼 (id/외래키는 파사드 내부에서만 사용).
# display_order: 부서그룹 안에서의 직원 표시순서 (migration 003, NULL=미지정).
USER_COLUMNS = [
    "emp_no", "name", "dept_code", "team_code", "position", "role", "is_active",
    "display_order",
]

# 화면이 사용하는 부서 컬럼 (id 는 파사드 내부 매핑에만 사용).
DEPT_COLUMNS = ["dept_code", "dept_name", "sort_order", "is_active"]

# 화면이 사용하는 조/팀 컬럼 (id/department_id 는 파사드 내부 매핑에만 사용).
TEAM_COLUMNS = ["dept_code", "team_code", "team_name", "sort_order", "is_active"]

# 조직 관리 화면 전용 확장 계약 (migration 003: 그룹 → 부서 → 운영단위).
# 기존 DEPT_COLUMNS/TEAM_COLUMNS 소비 화면(근무표·편성 등)은 그대로 두고,
# 조직 관리 화면만 이 확장 컬럼을 사용한다.
ORG_DEPT_COLUMNS = [
    "dept_code", "dept_name", "department_group", "group_sort_order", "sort_order", "is_active",
]
ORG_TEAM_COLUMNS = ["dept_code", "team_code", "team_name", "unit_type", "sort_order", "is_active"]

# 운영단위 유형 내부값 ↔ 화면 표시 (내부값만 저장 — CLAUDE.md §8).
UNIT_TYPES = ("SHIFT", "GENERAL")
UNIT_TYPE_LABELS = {"SHIFT": "교대", "GENERAL": "일반"}

# 화면이 사용하는 근무형태 컬럼 (id 는 파사드 내부 매핑에만 사용).
WORK_TYPE_COLUMNS = [
    "code", "name", "category", "short_label", "start_time", "end_time",
    "color", "is_work", "affects_allowance", "description", "sort_order", "is_active",
]

# 화면이 사용하는 근무표 자연키 컬럼 (id/user_id/work_date 는 파사드 내부에서만 사용).
SCHEDULE_COLUMNS = ["emp_no", "duty_date", "work_type_code", "note"]

# 화면이 사용하는 근무조 기준정보 컬럼 (id/department_id 는 파사드 내부 매핑에만 사용).
SHIFT_GROUP_COLUMNS = ["dept_code", "shift_code", "shift_name", "sort_order", "is_active"]

# 화면이 사용하는 직원별 월 편성 컬럼 (docs/database.md §5.1).
# schedule_month 는 해당 월 1일 ISO 문자열('YYYY-MM-01')로 정규화한다.
SCHEDULE_ASSIGNMENT_COLUMNS = [
    "emp_no", "schedule_month", "dept_code", "team_code", "shift_group_code",
]

# 편성 정보가 붙은 일별 근무 계약 (get_month_roster 반환값의 근무 프레임).
SCHEDULE_ASSIGNED_COLUMNS = SCHEDULE_COLUMNS + [
    "schedule_month", "dept_code", "team_code", "shift_group_code",
]

_BOOLEAN_COLUMNS = {"is_active", "is_work", "affects_allowance"}
_INTEGER_COLUMNS = {"sort_order", "group_sort_order"}

# 로컬 샘플 모드에서 편집 결과를 담아 세션 동안 유지하는 스토어 키.
_USERS_STORE = "store_users"
_DEPTS_STORE = "store_departments"
_TEAMS_STORE = "store_teams"
_WORK_TYPES_STORE = "store_work_types"
_SCHEDULES_STORE = "store_schedules"
_SHIFT_GROUPS_STORE = "store_shift_groups"
_ASSIGNMENTS_STORE = "store_schedule_assignments"


def datasource() -> str:
    """현재 데이터 소스 이름. 'supabase' 또는 'sample'."""
    return config.data_mode()


def is_sample_mode() -> bool:
    return datasource() == "sample"


def _typed_empty_frame(columns) -> pd.DataFrame:
    """빈 기준정보도 화면 필터가 가능한 컬럼/dtype 계약으로 반환한다."""
    return pd.DataFrame({
        column: pd.Series(
            dtype="bool" if column in _BOOLEAN_COLUMNS
            else "int64" if column in _INTEGER_COLUMNS
            else "object"
        )
        for column in columns
    })


def _empty_contract(df: pd.DataFrame, columns) -> pd.DataFrame:
    return _typed_empty_frame(columns) if df.empty else df


def frame_signature(df: pd.DataFrame, columns) -> str:
    """화면 편집 스냅샷이 원본 DB 데이터와 같은지 비교할 안정적인 서명."""
    required = list(columns)
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"DataFrame 필수 컬럼이 없습니다: {', '.join(missing)}")
    payload = df[required].reset_index(drop=True).to_json(
        orient="split", date_format="iso", force_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _changed_records(
    current: pd.DataFrame,
    desired: pd.DataFrame,
    key_columns,
    columns,
) -> list[dict]:
    """자연키 기준으로 신규 또는 실제 값이 바뀐 행만 반환한다."""
    keys = list(key_columns)
    compare_columns = list(columns)

    def normalized(value):
        if value is None or pd.isna(value):
            return None
        if isinstance(value, bool):
            return bool(value)
        if isinstance(value, int):
            return int(value)
        return str(value).strip()

    def key_of(record):
        return tuple(normalized(record[column]) for column in keys)

    current_by_key = {
        key_of(row): tuple(normalized(row[column]) for column in compare_columns)
        for _, row in current.iterrows()
    }
    changed = []
    for _, row in desired.iterrows():
        record = row[compare_columns].to_dict()
        values = tuple(normalized(record[column]) for column in compare_columns)
        if current_by_key.get(key_of(record)) != values:
            changed.append(record)
    return changed


# --- id -> 자연키 매핑 (내부) ---
def _dept_code_by_id() -> dict:
    df = sample_data.departments()
    return {} if df.empty else dict(zip(df["id"].astype(str), df["dept_code"]))


def _team_code_by_id() -> dict:
    df = sample_data.teams()
    return {} if df.empty else dict(zip(df["id"].astype(str), df["team_code"]))


def _emp_no_by_id() -> dict:
    df = sample_data.users()
    return {} if df.empty else dict(zip(df["id"].astype(str), df["emp_no"]))


# --- 기준정보 조회 ---
def _base_departments() -> pd.DataFrame:
    """샘플 CSV 를 화면용 부서 컬럼(DEPT_COLUMNS)으로 정리한 원본."""
    df = sample_data.departments()
    if df.empty:
        return _typed_empty_frame(DEPT_COLUMNS)
    return df[DEPT_COLUMNS].reset_index(drop=True).copy()


def get_departments(is_active: bool | None = None) -> pd.DataFrame:
    """부서 목록(DEPT_COLUMNS).

    로컬 샘플 모드에서는 세션 편집 결과(save_departments)를 우선 반환하므로,
    부서 관리 화면에서 저장한 내용이 다른 화면에도 그대로 반영된다.
    Phase 5(Supabase)에서는 이 분기를 실제 조회로 교체한다.
    """
    if is_sample_mode():
        if _DEPTS_STORE not in st.session_state:
            st.session_state[_DEPTS_STORE] = _base_departments()
        return _empty_contract(st.session_state[_DEPTS_STORE].copy(), DEPT_COLUMNS)
    df = supabase_repository.get_departments()
    if is_active is not None:
        df = df[df["is_active"].astype(bool) == bool(is_active)]
    return _empty_contract(df.reset_index(drop=True), DEPT_COLUMNS)


def save_departments(df: pd.DataFrame) -> None:
    """편집된 부서 목록을 저장한다.

    로컬 샘플 모드에서는 세션 상태에 보관해 현재 세션 동안 유지한다(CSV 는 건드리지
    않는다). Phase 5(Supabase)에서는 여기서 upsert / is_active 소프트삭제로 교체한다.
    """
    keep = [c for c in DEPT_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_DEPTS_STORE] = normalized
        return
    changed = _changed_records(
        supabase_repository.get_departments(), normalized, ["dept_code"], DEPT_COLUMNS
    )
    supabase_repository.upsert_departments(changed)


def _base_teams() -> pd.DataFrame:
    """샘플 CSV(id 기반)를 화면용 조/팀 컬럼(TEAM_COLUMNS)으로 변환한 원본."""
    df = sample_data.teams()
    if df.empty:
        return _typed_empty_frame(TEAM_COLUMNS)
    df = df.copy()
    df["dept_code"] = df["department_id"].astype(str).map(_dept_code_by_id()).fillna("")
    return df[TEAM_COLUMNS].reset_index(drop=True).copy()


def get_teams(dept_code: str | None = None, is_active: bool | None = None) -> pd.DataFrame:
    """조/팀 목록(TEAM_COLUMNS).

    로컬 샘플 모드에서는 세션 편집 결과(save_teams)를 우선 반환하므로,
    조 관리 화면에서 저장한 내용이 다른 화면에도 그대로 반영된다.
    Phase 5(Supabase)에서는 이 분기를 실제 조회로 교체한다.
    """
    if is_sample_mode():
        if _TEAMS_STORE not in st.session_state:
            st.session_state[_TEAMS_STORE] = _base_teams()
        return _empty_contract(st.session_state[_TEAMS_STORE].copy(), TEAM_COLUMNS)
    df = supabase_repository.get_teams()
    if dept_code is not None:
        df = df[df["dept_code"].astype(str) == str(dept_code).strip()]
    if is_active is not None:
        df = df[df["is_active"].astype(bool) == bool(is_active)]
    return _empty_contract(df.reset_index(drop=True), TEAM_COLUMNS)


def save_teams(df: pd.DataFrame) -> None:
    """편집된 조/팀 목록을 저장한다.

    로컬 샘플 모드에서는 세션 상태에 보관해 현재 세션 동안 유지한다(CSV 는 건드리지
    않는다). Phase 5(Supabase)에서는 여기서 upsert / is_active 소프트삭제로 교체한다.
    """
    keep = [c for c in TEAM_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_TEAMS_STORE] = normalized
        return
    changed = _changed_records(
        supabase_repository.get_teams(),
        normalized,
        ["dept_code", "team_code"],
        TEAM_COLUMNS,
    )
    supabase_repository.upsert_teams(changed)


# --- 조직 관리 (그룹·부서·운영단위, migration 003) ---
def org_schema_ready() -> bool:
    """003 확장 컬럼(department_group/group_sort_order/unit_type) 사용 가능 여부.

    sample 모드는 세션 스토어에 기본값을 채워 항상 사용 가능하다. supabase 모드는
    라이브 스키마를 1회 probe 한다 — 미적용이면 조회는 안전한 기본값으로 폴백하고
    저장은 repository 계층에서 명확한 오류로 차단된다.
    """
    if is_sample_mode():
        return True
    return supabase_repository.org_extensions_ready()


def org_dept_defaults(df: pd.DataFrame) -> pd.DataFrame:
    """확장 컬럼이 없거나 비어 있는 부서 프레임에 안전한 그룹 기본값을 채운다.

    백필 전 상태(부서 1개 = 그룹 1개)를 그대로 재현한다: 그룹명은 부서명,
    그룹순서는 sort_order → dept_code 순 1..N (전역 중복 없음). migration 003 의
    백필 전략과 동일하므로 적용 전후 화면 표시가 달라지지 않는다.
    """
    frame = df.copy()
    if "department_group" not in frame:
        frame["department_group"] = ""
    if "group_sort_order" not in frame:
        frame["group_sort_order"] = 0
    group = frame["department_group"].fillna("").astype(str).str.strip()
    blank = group == ""
    frame["department_group"] = group
    frame.loc[blank, "department_group"] = frame.loc[blank, "dept_name"].astype(str)
    order = pd.to_numeric(frame["group_sort_order"], errors="coerce").fillna(0).astype("int64")
    frame["group_sort_order"] = order
    if not frame.empty and (order == 0).all():
        ranked = frame.sort_values(["sort_order", "dept_code"]).index
        frame.loc[ranked, "group_sort_order"] = range(1, len(frame) + 1)
    return frame


def org_team_defaults(df: pd.DataFrame) -> pd.DataFrame:
    """unit_type 이 없거나 비정상인 운영단위 프레임을 SHIFT 기본값으로 정규화한다."""
    frame = df.copy()
    if "unit_type" not in frame:
        frame["unit_type"] = "SHIFT"
    unit = frame["unit_type"].fillna("").astype(str).str.strip().str.upper()
    frame["unit_type"] = unit.where(unit.isin(UNIT_TYPES), "SHIFT")
    return frame


def get_org_departments() -> pd.DataFrame:
    """조직 관리 화면용 부서 목록(ORG_DEPT_COLUMNS, 그룹 컬럼 포함)."""
    if is_sample_mode():
        df = org_dept_defaults(get_departments())
    elif supabase_repository.org_extensions_ready():
        df = supabase_repository.get_departments_org()
    else:
        df = org_dept_defaults(supabase_repository.get_departments())
    return _empty_contract(df[ORG_DEPT_COLUMNS].reset_index(drop=True), ORG_DEPT_COLUMNS)


def save_org_departments(df: pd.DataFrame) -> None:
    """조직 관리 화면의 그룹·부서 편집 결과를 저장한다 (변경 행만 upsert)."""
    keep = [c for c in ORG_DEPT_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_DEPTS_STORE] = normalized
        return
    changed = _changed_records(
        get_org_departments(), normalized, ["dept_code"], ORG_DEPT_COLUMNS
    )
    supabase_repository.upsert_departments_org(changed)


def get_org_teams(dept_code: str | None = None, is_active: bool | None = None) -> pd.DataFrame:
    """조직 관리 화면용 운영단위 목록(ORG_TEAM_COLUMNS, unit_type 포함)."""
    if is_sample_mode():
        df = org_team_defaults(get_teams())
    elif supabase_repository.org_extensions_ready():
        df = supabase_repository.get_teams_org()
    else:
        df = org_team_defaults(supabase_repository.get_teams())
    if dept_code is not None:
        df = df[df["dept_code"].astype(str) == str(dept_code).strip()]
    if is_active is not None:
        df = df[df["is_active"].astype(bool) == bool(is_active)]
    return _empty_contract(df[ORG_TEAM_COLUMNS].reset_index(drop=True), ORG_TEAM_COLUMNS)


def save_org_teams(df: pd.DataFrame) -> None:
    """조직 관리 화면의 운영단위 편집 결과를 저장한다 (변경 행만 upsert)."""
    keep = [c for c in ORG_TEAM_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_TEAMS_STORE] = normalized
        return
    changed = _changed_records(
        get_org_teams(), normalized, ["dept_code", "team_code"], ORG_TEAM_COLUMNS
    )
    supabase_repository.upsert_teams_org(changed)


# --- 부서그룹 기준 사용자 표시순서 (users.display_order, migration 003) ---
def normalize_display_order(value):
    """표시순서 입력 정규화 — 빈 값/NaN 은 None(미지정), 그 외 int. 실패 시 ValueError.

    pandas 가 int+NULL 혼합 컬럼을 float 로 승격시키므로("1.0") float 표기도 수용한다.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "<na>"}:
        return None
    number = float(text)  # 정수/float 표기 외에는 ValueError
    if number != int(number):
        raise ValueError(f"표시순서는 정수여야 합니다: {value!r}")
    return int(number)


def dept_group_map(org_depts: pd.DataFrame | None = None) -> dict:
    """dept_code -> (department_group, group_sort_order) 매핑.

    org_depts 를 넘기면 그 프레임(예: 저장 후 예상 merged) 기준으로 계산한다 —
    조직 저장 전 '변경 후 그룹 구조' 기준 검증(§그룹 병합 충돌)에 사용한다.
    """
    frame = get_org_departments() if org_depts is None else org_depts
    out: dict = {}
    for _, r in frame.iterrows():
        out[str(r["dept_code"]).strip()] = (
            str(r["department_group"]).strip(),
            int(pd.to_numeric(r["group_sort_order"], errors="coerce") or 0),
        )
    return out


def display_order_conflicts(users_df: pd.DataFrame, group_of: dict) -> list[str]:
    """부서그룹 기준 활성 사용자 display_order 중복 오류 목록.

    - 검증 대상: 활성(is_active) + 표시순서 지정(display_order not NULL) 사용자만.
      비활성(퇴직) 사용자는 번호를 점유하지 않는다.
    - group_of: dept_code -> (group, group_order) — 저장 후 예상 매핑을 넘기면
      그룹 병합·부서 이동 후 충돌을 사전 차단할 수 있다.
    """
    errors: list[str] = []
    if users_df is None or users_df.empty:
        return errors
    holders: dict[tuple[str, int], list[str]] = {}
    for _, r in users_df.iterrows():
        if not bool(r.get("is_active")):
            continue
        try:
            order = normalize_display_order(r.get("display_order"))
        except (TypeError, ValueError):
            continue  # 형식 오류는 입력 화면 검증이 담당
        if order is None:
            continue
        dept = str(r.get("dept_code") or "").strip()
        group = group_of.get(dept, (dept, 0))[0]
        key = (group, order)
        holders.setdefault(key, []).append(
            f"{str(r.get('emp_no') or '').strip()} {str(r.get('name') or '').strip()}".strip()
        )
    for (group, order), users in sorted(holders.items()):
        if len(users) > 1:
            errors.append(
                f"그룹 '{group}'의 사용자 표시순서 {order}이(가) 중복되었습니다: "
                + ", ".join(users)
            )
    return errors


def sort_users_for_display(users_df: pd.DataFrame, org_depts: pd.DataFrame | None = None) -> pd.DataFrame:
    """근무표·편성 공통 직원 정렬 — 그룹순서 → 표시순서(NULL 뒤) → 사번.

    이번 미션에서는 helper 만 제공하고 월간/편성 화면 적용은 후속 미션에서 한다.
    """
    if users_df is None or users_df.empty:
        return users_df
    group_of = dept_group_map(org_depts)
    frame = users_df.copy()
    frame["_g_order"] = [
        group_of.get(str(d).strip(), ("", 10**9))[1] for d in frame["dept_code"]
    ]
    orders = []
    for value in frame.get("display_order", pd.Series([None] * len(frame))):
        try:
            orders.append(normalize_display_order(value))
        except (TypeError, ValueError):
            orders.append(None)
    frame["_d_null"] = [1 if o is None else 0 for o in orders]
    frame["_d_order"] = [0 if o is None else o for o in orders]
    frame = frame.sort_values(
        ["_g_order", "_d_null", "_d_order", "emp_no"], kind="stable"
    ).drop(columns=["_g_order", "_d_null", "_d_order"])
    return frame.reset_index(drop=True)


def _base_users() -> pd.DataFrame:
    """샘플 CSV(id 기반)를 화면용 자연키 컬럼(USER_COLUMNS)으로 변환한 원본."""
    df = sample_data.users()
    if df.empty:
        return _typed_empty_frame(USER_COLUMNS)
    df = df.copy()
    df["dept_code"] = df["department_id"].astype(str).map(_dept_code_by_id()).fillna("")
    df["team_code"] = df["team_id"].astype(str).map(_team_code_by_id()).fillna("")
    if "display_order" not in df.columns:  # 샘플 CSV 미보유 → NULL(미지정)로 시작
        df["display_order"] = None
    return df[USER_COLUMNS].reset_index(drop=True)


def get_users(
    dept_code: str | None = None,
    team_code: str | None = None,
    is_active: bool | None = None,
) -> pd.DataFrame:
    """사용자 목록(USER_COLUMNS).

    로컬 샘플 모드에서는 세션 편집 결과(save_users)를 우선 반환하므로,
    사용자 관리 화면에서 저장한 내용이 다른 화면에도 그대로 반영된다.
    Phase 5(Supabase)에서는 이 분기를 실제 조회로 교체한다.
    """
    if is_sample_mode():
        if _USERS_STORE not in st.session_state:
            st.session_state[_USERS_STORE] = _base_users()
        return _empty_contract(st.session_state[_USERS_STORE].copy(), USER_COLUMNS)
    df = supabase_repository.get_users()
    if dept_code is not None:
        df = df[df["dept_code"].astype(str) == str(dept_code).strip()]
    if team_code is not None:
        df = df[df["team_code"].astype(str) == str(team_code).strip()]
    if is_active is not None:
        df = df[df["is_active"].astype(bool) == bool(is_active)]
    return _empty_contract(df.reset_index(drop=True), USER_COLUMNS)


def save_users(df: pd.DataFrame) -> None:
    """편집된 사용자 목록을 저장한다.

    로컬 샘플 모드에서는 세션 상태에 보관해 현재 세션 동안 유지한다(CSV 는 건드리지
    않는다). Phase 5(Supabase)에서는 여기서 upsert / is_active 소프트삭제로 교체한다.
    """
    keep = [c for c in USER_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_USERS_STORE] = normalized
        return
    changed = _changed_records(
        supabase_repository.get_users(), normalized, ["emp_no"], USER_COLUMNS
    )
    supabase_repository.upsert_users(changed)


def _base_work_types() -> pd.DataFrame:
    """샘플 CSV 를 화면용 근무형태 컬럼(WORK_TYPE_COLUMNS)으로 정리한 원본."""
    df = sample_data.work_types()
    if df.empty:
        return _typed_empty_frame(WORK_TYPE_COLUMNS)
    df = df.copy()
    for c in WORK_TYPE_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[WORK_TYPE_COLUMNS].reset_index(drop=True).copy()


def get_work_types(active_only: bool = False) -> pd.DataFrame:
    """근무형태 목록(WORK_TYPE_COLUMNS).

    로컬 샘플 모드에서는 세션 편집 결과(save_work_types)를 우선 반환하므로,
    근무형태 관리 화면에서 저장한 내용이 다른 화면에도 그대로 반영된다.
    Phase 5(Supabase)에서는 이 분기를 실제 조회로 교체한다.
    """
    if is_sample_mode():
        if _WORK_TYPES_STORE not in st.session_state:
            st.session_state[_WORK_TYPES_STORE] = _base_work_types()
        return _empty_contract(st.session_state[_WORK_TYPES_STORE].copy(), WORK_TYPE_COLUMNS)
    df = supabase_repository.get_work_types()
    if active_only:
        df = df[df["is_active"].astype(bool)]
    return _empty_contract(df.reset_index(drop=True), WORK_TYPE_COLUMNS)


def save_work_types(df: pd.DataFrame) -> None:
    """편집된 근무형태 목록을 저장한다.

    로컬 샘플 모드에서는 세션 상태에 보관해 현재 세션 동안 유지한다(CSV 는 건드리지
    않는다). Phase 5(Supabase)에서는 여기서 upsert / is_active 소프트삭제로 교체한다.
    """
    keep = [c for c in WORK_TYPE_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_WORK_TYPES_STORE] = normalized
        return
    changed = _changed_records(
        supabase_repository.get_work_types(), normalized, ["code"], WORK_TYPE_COLUMNS
    )
    supabase_repository.upsert_work_types(changed)


def upsert_records(store, records, loaded_keys, key_cols, status_col, columns):
    """기준정보 저장 공통 병합.

    편집 그리드 결과(records)를 기존 스토어(store)에 자연키(key_cols) 기준으로
    upsert 한다. 키가 이미 있으면 수정(U), 없으면 신규(C)로 처리한다. 조회 시
    적재됐지만(loaded_keys) 편집 결과에서 사라진 행은 물리 삭제하지 않고 상태
    컬럼(status_col)만 False 로 바꾼다(소프트 삭제).

    반환: (merged_df, dup_keys, n_create, n_update, n_soft_deleted)
      dup_keys 는 편집 결과 안에서 키가 겹친 경우만(진짜 중복). upsert 이므로
      기존 스토어 행과 편집 행이 같은 키를 갖는 것은 중복이 아니라 수정이다.
    """
    def key_of(rec):
        return tuple(str(rec[c]).strip() for c in key_cols)

    store_map, order = {}, []
    for _, r in store.iterrows():
        k = key_of(r)
        store_map[k] = r.to_dict()
        order.append(k)

    rec_keys = [key_of(rec) for rec in records]
    dup = sorted({k for k in rec_keys if rec_keys.count(k) > 1})

    n_create = n_update = 0
    edited = set()
    for rec, k in zip(records, rec_keys):
        edited.add(k)
        if k in store_map:
            n_update += 1
        else:
            n_create += 1
            order.append(k)
        store_map[k] = rec

    n_soft = 0
    for k in loaded_keys:
        if k in edited or k not in store_map:
            continue
        row = dict(store_map[k])
        if row.get(status_col) is not False:
            row[status_col] = False
            n_soft += 1
        store_map[k] = row

    merged = pd.DataFrame([store_map[k] for k in order], columns=columns)
    return merged, dup, n_create, n_update, n_soft


def _base_schedules() -> pd.DataFrame:
    """샘플 CSV(id 기반)를 화면용 근무표 자연키 컬럼(SCHEDULE_COLUMNS)으로 변환한 원본.

    저장 계층은 세로형(long) — 사번 | 근무일자 | 근무형태 (docs/database.md §5.4).
    사용자를 찾을 수 없는(user_id 미매핑) 행은 제외한다.
    """
    df = sample_data.work_schedules()
    if df.empty:
        return pd.DataFrame(columns=SCHEDULE_COLUMNS)
    df = df.copy()
    df["emp_no"] = df["user_id"].astype(str).map(_emp_no_by_id()).fillna("")
    df["duty_date"] = df["work_date"].astype(str)
    df["note"] = df["note"].fillna("").astype(str) if "note" in df.columns else ""
    df = df[df["emp_no"] != ""]
    return df[SCHEDULE_COLUMNS].reset_index(drop=True).copy()


def get_schedules() -> pd.DataFrame:
    """근무표 목록(SCHEDULE_COLUMNS, 세로형 long format).

    로컬 샘플 모드에서는 세션 편집 결과(save_schedules)를 우선 반환하므로,
    근무표 등록/수정 화면에서 저장한 내용이 조회·대시보드·내 근무표 화면에도
    그대로 반영된다. Phase 5(Supabase)에서는 이 분기를 실제 조회로 교체한다.
    """
    if is_sample_mode():
        if _SCHEDULES_STORE not in st.session_state:
            st.session_state[_SCHEDULES_STORE] = _base_schedules()
        return st.session_state[_SCHEDULES_STORE].copy()
    return supabase_repository.get_schedules()


def save_schedules(df: pd.DataFrame) -> None:
    """근무표 전체(세로형 long format, SCHEDULE_COLUMNS)를 저장한다.

    화면(schedule_edit)에서 (선택 직원 × 선택 월) 범위만 교체해 만든 전체
    스냅샷을 넘겨받아 세션 스토어에 그대로 보관한다. 로컬 샘플 모드에서는 현재
    세션 동안만 유지하며 CSV 는 건드리지 않는다. Phase 5(Supabase)에서는 여기서
    범위 삭제 후 batch upsert 로 교체한다.
    """
    keep = [c for c in SCHEDULE_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_SCHEDULES_STORE] = normalized
        return
    supabase_repository.upsert_schedules(normalized.to_dict("records"))


def upsert_month_schedules(records) -> None:
    """근무표 레코드를 (직원, 일자) 키로 upsert 만 한다 — 삭제 없음.

    빈 셀 때문에 기존 근무를 자동 삭제하지 않는다는 원칙(CLAUDE.md §5)에 맞춰
    근무표 편성 화면의 [저장]은 이 경로를 사용한다. 기존 근무의 삭제는
    replace_month_schedules(명시적 범위 교체)로만 수행한다.
    """
    normalized = pd.DataFrame(list(records), columns=SCHEDULE_COLUMNS)
    if normalized.empty:
        return
    if is_sample_mode():
        store = get_schedules()
        by_key = {
            (str(r["emp_no"]).strip(), str(r["duty_date"])): r
            for r in store.to_dict("records")
        }
        for r in normalized.to_dict("records"):
            by_key[(str(r["emp_no"]).strip(), str(r["duty_date"]))] = r
        save_schedules(pd.DataFrame(list(by_key.values()), columns=SCHEDULE_COLUMNS))
        return
    supabase_repository.upsert_schedules(normalized.to_dict("records"))


def replace_month_schedules(emp_nos, year: int, month: int, records) -> None:
    """선택 직원·월 범위만 전달받은 근무표로 교체한다."""
    normalized_emp_nos = [str(emp_no).strip() for emp_no in emp_nos if str(emp_no).strip()]
    normalized = pd.DataFrame(records, columns=SCHEDULE_COLUMNS)
    if is_sample_mode():
        store = get_schedules()
        month_start = pd.Timestamp(year=int(year), month=int(month), day=1)
        next_month = month_start + pd.offsets.MonthBegin(1)
        duty_dates = pd.to_datetime(store["duty_date"], errors="coerce")
        in_scope = (
            store["emp_no"].astype(str).str.strip().isin(normalized_emp_nos)
            & duty_dates.ge(month_start)
            & duty_dates.lt(next_month)
        )
        save_schedules(pd.concat([store[~in_scope], normalized], ignore_index=True))
        return
    supabase_repository.replace_month_schedules(
        normalized_emp_nos, int(year), int(month), normalized.to_dict("records")
    )


# --- 근무조 기준정보 / 직원별 월 편성 (docs/database.md §4.5·§5.1) ---
def _base_shift_groups() -> pd.DataFrame:
    """샘플 CSV(id 기반)를 화면용 근무조 컬럼(SHIFT_GROUP_COLUMNS)으로 변환한 원본."""
    df = sample_data.shift_groups()
    if df.empty:
        return _typed_empty_frame(SHIFT_GROUP_COLUMNS)
    df = df.copy()
    df["dept_code"] = df["department_id"].astype(str).map(_dept_code_by_id()).fillna("")
    return df[SHIFT_GROUP_COLUMNS].reset_index(drop=True).copy()


def get_shift_groups(dept_code: str | None = None, is_active: bool | None = None) -> pd.DataFrame:
    """근무조 목록(SHIFT_GROUP_COLUMNS). 선택지 제공·유효성 검사 전용 기준정보."""
    if is_sample_mode():
        if _SHIFT_GROUPS_STORE not in st.session_state:
            st.session_state[_SHIFT_GROUPS_STORE] = _base_shift_groups()
        df = st.session_state[_SHIFT_GROUPS_STORE].copy()
    else:
        df = supabase_repository.get_shift_groups()
    if dept_code is not None:
        df = df[df["dept_code"].astype(str) == str(dept_code).strip()]
    if is_active is not None:
        df = df[df["is_active"].astype(bool) == bool(is_active)]
    return _empty_contract(df.reset_index(drop=True), SHIFT_GROUP_COLUMNS)


def _base_assignments() -> pd.DataFrame:
    """샘플 CSV(id 기반)를 화면용 월 편성 컬럼(SCHEDULE_ASSIGNMENT_COLUMNS)으로 변환한 원본."""
    df = sample_data.schedule_assignments()
    if df.empty:
        return _typed_empty_frame(SCHEDULE_ASSIGNMENT_COLUMNS)
    df = df.copy()
    df["emp_no"] = df["user_id"].astype(str).map(_emp_no_by_id()).fillna("")
    df["dept_code"] = df["department_id"].astype(str).map(_dept_code_by_id()).fillna("")
    df["team_code"] = df["team_id"].astype(str).map(_team_code_by_id()).fillna("")
    df["schedule_month"] = df["schedule_month"].map(
        lambda value: validators.normalize_schedule_month(value) if str(value).strip() else ""
    )
    df["shift_group_code"] = df["shift_group_code"].fillna("").astype(str)
    df = df[df["emp_no"] != ""]
    return df[SCHEDULE_ASSIGNMENT_COLUMNS].reset_index(drop=True).copy()


def _assignments_store() -> pd.DataFrame:
    if _ASSIGNMENTS_STORE not in st.session_state:
        st.session_state[_ASSIGNMENTS_STORE] = _base_assignments()
    return st.session_state[_ASSIGNMENTS_STORE]


def get_month_assignments(year: int, month: int, emp_nos=None) -> pd.DataFrame:
    """대상 월의 직원별 편성 스냅샷(SCHEDULE_ASSIGNMENT_COLUMNS).

    편성은 근무표 작성 당시 값이므로 users 의 현재 소속으로 재계산하지 않는다.
    """
    if isinstance(emp_nos, str):
        emp_nos = [emp_nos]
    normalized = {str(e).strip() for e in (emp_nos or []) if str(e).strip()}
    if not is_sample_mode():
        return supabase_repository.get_month_assignments(
            int(year), int(month), sorted(normalized) or None
        )
    schedule_month = validators.normalize_schedule_month((int(year), int(month)))
    df = _assignments_store().copy()
    if df.empty:
        return _typed_empty_frame(SCHEDULE_ASSIGNMENT_COLUMNS)
    df = df[df["schedule_month"].astype(str) == schedule_month]
    if normalized:
        df = df[df["emp_no"].astype(str).str.strip().isin(normalized)]
    return _empty_contract(df.reset_index(drop=True), SCHEDULE_ASSIGNMENT_COLUMNS)


def upsert_month_assignments(records, require_shift: bool = True) -> dict:
    """직원·월 편성을 upsert 한다 (직원별 월 편성 1건).

    반환: {(emp_no, schedule_month): 편성 레코드(id 포함)} — supabase 모드는 실제
    DB id, sample 모드는 (emp_no, month) 기반 안정 합성 id. 근무 저장이 이 id 로
    schedule_assignment_id 를 연결할 수 있게 한다.

    검증은 modules/validators 순수 함수로 수행한다: 사번·부서 존재, 팀-부서 소속,
    부서의 활성 조, 대상 월 정규화, 같은 직원·월 중복. 검증 실패 시 ValueError
    (supabase 모드는 SupabaseDataError) 를 던지고 아무것도 저장하지 않는다.
    편성 저장은 users 를 변경하지 않는다.

    require_shift=False 면 근무조 코드 없이 부서·팀 스냅샷만 저장한다
    (근무표 편성 화면 — 근무조 입력이 아직 없는 경로).
    """
    records = list(records)
    if not is_sample_mode():
        return supabase_repository.upsert_month_assignments(records, require_shift=require_shift)
    users = get_users()
    depts = get_departments()
    teams = get_teams()
    shift_groups = get_shift_groups()
    normalized, errors = validators.validate_assignment_records(
        records,
        emp_nos=set(users["emp_no"].astype(str).str.strip()),
        dept_codes=set(depts["dept_code"].astype(str)),
        team_keys=set(zip(teams["dept_code"].astype(str), teams["team_code"].astype(str))),
        shift_keys={
            (str(d), str(s))
            for d, s, a in zip(
                shift_groups["dept_code"], shift_groups["shift_code"], shift_groups["is_active"]
            )
            if bool(a)
        },
        require_shift=require_shift,
    )
    if errors:
        raise ValueError("월 편성 검증 실패:\n- " + "\n- ".join(errors))
    store = _assignments_store()
    by_key = {
        (str(r["emp_no"]), str(r["schedule_month"])): r for r in store.to_dict("records")
    }
    for record in normalized:
        by_key[(record["emp_no"], record["schedule_month"])] = record
    st.session_state[_ASSIGNMENTS_STORE] = pd.DataFrame(
        list(by_key.values()), columns=SCHEDULE_ASSIGNMENT_COLUMNS
    )
    result: dict = {}
    for record in normalized:
        key = (record["emp_no"], record["schedule_month"])
        # sample 안정 합성 id — 같은 (직원·월)은 재저장해도 같은 id.
        result[key] = {
            "id": f"S-{record['emp_no']}-{record['schedule_month']}",
            "emp_no": record["emp_no"],
            "schedule_month": record["schedule_month"],
            "dept_code": record["dept_code"],
            "team_code": record["team_code"],
            "shift_group_code": record.get("shift_group_code", ""),
        }
    return result


def get_month_roster(emp_nos, year: int, month: int):
    """대상 월의 (편성, 편성정보가 붙은 일별 근무) 를 함께 반환한다.

    반환: (assignments, schedules)
      - assignments: SCHEDULE_ASSIGNMENT_COLUMNS
      - schedules: SCHEDULE_ASSIGNED_COLUMNS — 일별 근무에 해당 월 편성의
        schedule_month/dept_code/team_code/shift_group_code 를 붙인 long format.
        편성이 없는 근무 행은 빈 문자열로 채운다 (backfill 이전 데이터 호환).
    """
    assignments = get_month_assignments(year, month, emp_nos)
    schedules = get_month_schedules(emp_nos, int(year), int(month))
    merged = schedules.merge(
        assignments[["emp_no", "schedule_month", "dept_code", "team_code", "shift_group_code"]],
        on="emp_no",
        how="left",
    )
    for column in ("schedule_month", "dept_code", "team_code", "shift_group_code"):
        merged[column] = merged[column].fillna("").astype(str)
    return assignments, merged[SCHEDULE_ASSIGNED_COLUMNS].reset_index(drop=True)


# --- 조회 헬퍼 ---
def find_user_by_emp_no(emp_no: str):
    """사번으로 사용자 1명을 dict 로 반환. 없으면 None.

    사번 조회는 앞뒤 공백을 제거하고 대소문자를 구분하지 않는다
    (영문 사번 ADMIN·admin·Admin 은 동일 사용자). 정규화(trim+casefold)는
    비교에만 쓰고, DB 의 원래 emp_no 값은 변경하지 않는다.
    대소문자만 다른 사번이 여러 건이면 활성 사용자 → 정확한 대소문자 순으로 우선한다.
    """
    df = get_users()
    if df.empty:
        return None
    raw = str(emp_no).strip()
    key = raw.casefold()
    norm = df["emp_no"].astype(str).str.strip()
    match = df[norm.str.casefold() == key]
    if match.empty:
        return None
    if len(match) > 1:
        pool = match
        if "is_active" in pool.columns:
            active = pool[pool["is_active"].astype(bool)]
            if not active.empty:
                pool = active
        exact = pool[norm.loc[pool.index] == raw]
        if not exact.empty:
            pool = exact
        return pool.iloc[0].to_dict()
    return match.iloc[0].to_dict()


def dept_name(dept_code: str) -> str:
    df = get_departments()
    if df.empty:
        return dept_code
    match = df[df["dept_code"] == dept_code]
    return dept_code if match.empty else match.iloc[0]["dept_name"]


def team_name(dept_code: str, team_code: str) -> str:
    if not team_code:
        return ""
    df = get_teams()
    if df.empty:
        return team_code
    match = df[(df["dept_code"] == dept_code) & (df["team_code"] == team_code)]
    return team_code if match.empty else match.iloc[0]["team_name"]


def work_types_map() -> dict:
    """근무코드 -> {name, color, is_work} 딕셔너리."""
    df = get_work_types()
    out = {}
    for _, r in df.iterrows():
        out[r["code"]] = {
            "name": r["name"],
            "category": r.get("category", ""),
            "color": r["color"] or "#9AA0A6",
            "is_work": bool(r["is_work"]),
        }
    return out


def classify_work_group(code: str, work_type: dict) -> str | None:
    """근무코드를 개인 화면 공통 집계 그룹으로 분류한다."""
    code = str(code or "").strip()
    category = str(work_type.get("category") or "").strip()
    name = str(work_type.get("name") or "")
    label = f"{code} {category} {name}"
    if code == "OFF" or category.upper() == "OFF":
        return "OFF"
    if "야간" in category or code.startswith("야") or "특야" in code:
        return "야간"
    if "주간" in category or code.startswith("주") or "특주" in code:
        return "주간"
    if not bool(work_type.get("is_work")) or any(
        word in label for word in ("휴가", "연차", "경조")
    ):
        return "휴가"
    return None


def get_user_schedules(emp_no: str) -> pd.DataFrame:
    """특정 사번의 근무표 레코드(long format). 컬럼: emp_no, duty_date, work_type_code, note."""
    if not is_sample_mode():
        return supabase_repository.get_user_schedules(str(emp_no).strip())
    df = get_schedules()
    if df.empty:
        return df
    return df[df["emp_no"].astype(str).str.strip() == str(emp_no).strip()].copy()


def get_month_schedules(emp_nos, year: int, month: int) -> pd.DataFrame:
    """사번 목록의 지정 월 근무내역을 long format으로 반환한다.

    전체 근무표와 개인 근무표가 같은 월 조건과 원본 데이터를 사용하도록
    조회 범위를 이 함수에서 일관되게 제한한다.
    """
    if isinstance(emp_nos, str):
        emp_nos = [emp_nos]
    emp_nos = {str(emp_no).strip() for emp_no in emp_nos if str(emp_no).strip()}
    if not is_sample_mode():
        return supabase_repository.get_month_schedules(emp_nos, int(year), int(month))
    df = get_schedules()
    if df.empty or not emp_nos:
        return df.iloc[0:0].copy()

    # 기존 개인 조회처럼 날짜를 실제 datetime으로 해석한다. 문자열 접두어 비교는
    # date/datetime 또는 ISO가 아닌 문자열로 저장된 기존 행을 누락시킬 수 있다.
    month_start = pd.Timestamp(year=int(year), month=int(month), day=1)
    next_month = month_start + pd.offsets.MonthBegin(1)
    duty_dates = pd.to_datetime(df["duty_date"], errors="coerce")
    emp_values = df["emp_no"].astype(str).str.strip()
    return df[
        emp_values.isin(emp_nos)
        & duty_dates.ge(month_start)
        & duty_dates.lt(next_month)
    ].copy()


# --- Supabase 운영·검증 API ---
def test_connection() -> dict[str, int]:
    if is_sample_mode():
        raise config.DataSourceConfigurationError("연결 테스트는 supabase 모드에서만 실행할 수 있습니다.")
    return supabase_repository.test_connection()


def upsert_department(record: dict) -> None:
    supabase_repository.upsert_departments([record])


def upsert_team(record: dict) -> None:
    supabase_repository.upsert_teams([record])


def upsert_user(record: dict) -> None:
    supabase_repository.upsert_users([record])


def upsert_work_type(record: dict) -> None:
    supabase_repository.upsert_work_types([record])


def upsert_schedule(record: dict) -> None:
    supabase_repository.upsert_schedules([record])


def upsert_shift_group(record: dict) -> None:
    supabase_repository.upsert_shift_groups([record])


def delete_schedule(emp_no: str, duty_date: str) -> None:
    supabase_repository.delete_schedule(str(emp_no).strip(), str(duty_date).strip())


def deactivate_department(dept_code: str) -> None:
    supabase_repository.deactivate_department(str(dept_code).strip())


def delete_department(dept_code: str) -> None:
    """부서를 물리 삭제한다(참조 없는 부서 전용 — 참조 확인은 호출부가 담당).

    로컬 샘플 모드에서는 세션 스토어에서 제거하고, Supabase 모드에서는 물리 삭제한다.
    """
    code = str(dept_code).strip()
    if is_sample_mode():
        if _DEPTS_STORE in st.session_state:
            store = st.session_state[_DEPTS_STORE]
            st.session_state[_DEPTS_STORE] = (
                store[store["dept_code"].astype(str) != code].reset_index(drop=True)
            )
        return
    supabase_repository.delete_department(code)


def department_reference_counts(dept_code: str) -> dict:
    """부서를 참조하는 사용자/조/편성 조 건수를 반환한다(활성·비활성 모두 포함).

    아직 생성되지 않은 테이블(예: migration 002 미적용 시 shift_groups)은
    조회 실패를 참조 0 으로 안전하게 처리한다.
    """
    code = str(dept_code).strip()

    def _count(loader) -> int:
        try:
            frame = loader()
        except Exception:
            return 0
        if frame.empty or "dept_code" not in frame:
            return 0
        return int((frame["dept_code"].astype(str).str.strip() == code).sum())

    return {
        "users": _count(get_users),
        "teams": _count(get_teams),
        "shift_groups": _count(get_shift_groups),
    }


def deactivate_team(dept_code: str, team_code: str) -> None:
    supabase_repository.deactivate_team(str(dept_code).strip(), str(team_code).strip())


def delete_team(dept_code: str, team_code: str) -> None:
    """조를 물리 삭제한다(참조 없는 조 전용 — 참조 확인은 호출부가 담당)."""
    dc, tc = str(dept_code).strip(), str(team_code).strip()
    if is_sample_mode():
        if _TEAMS_STORE in st.session_state:
            store = st.session_state[_TEAMS_STORE]
            keep = ~(
                (store["dept_code"].astype(str) == dc)
                & (store["team_code"].astype(str) == tc)
            )
            st.session_state[_TEAMS_STORE] = store[keep].reset_index(drop=True)
        return
    supabase_repository.delete_team(dc, tc)


def team_reference_counts(dept_code: str, team_code: str) -> dict:
    """조를 참조하는 사용자 수를 반환한다(활성·비활성 모두 포함)."""
    dc, tc = str(dept_code).strip(), str(team_code).strip()
    try:
        users = get_users()
    except Exception:
        return {"users": 0}
    if users.empty:
        return {"users": 0}
    mask = (
        (users["dept_code"].astype(str).str.strip() == dc)
        & (users["team_code"].astype(str).str.strip() == tc)
    )
    return {"users": int(mask.sum())}


def deactivate_user(emp_no: str) -> None:
    supabase_repository.deactivate_user(str(emp_no).strip())


def deactivate_work_type(code: str) -> None:
    supabase_repository.deactivate_work_type(str(code).strip())


def delete_work_type(code: str) -> None:
    """근무형태를 물리 삭제한다(근무표 참조 없는 코드 전용 — 확인은 호출부가 담당)."""
    c = str(code).strip()
    if is_sample_mode():
        if _WORK_TYPES_STORE in st.session_state:
            store = st.session_state[_WORK_TYPES_STORE]
            st.session_state[_WORK_TYPES_STORE] = (
                store[store["code"].astype(str) != c].reset_index(drop=True)
            )
        return
    supabase_repository.delete_work_type(c)


def work_type_reference_counts(code: str) -> dict:
    """근무형태 코드를 참조하는 근무표(work_schedules) 건수를 반환한다."""
    c = str(code).strip()
    try:
        scheds = get_schedules()
    except Exception:
        return {"schedules": 0}
    if scheds.empty or "work_type_code" not in scheds:
        return {"schedules": 0}
    return {"schedules": int((scheds["work_type_code"].astype(str).str.strip() == c).sum())}


def cleanup_test_records(dept_code: str, team_code: str, emp_no: str, work_type_codes) -> None:
    """의존성 역순으로 TEST_* 레코드만 물리 삭제한다."""
    supabase_repository.hard_delete_test_user(emp_no)
    for code in work_type_codes:
        supabase_repository.hard_delete_test_work_type(str(code).strip())
    supabase_repository.hard_delete_test_team(dept_code, team_code)
    supabase_repository.hard_delete_test_department(dept_code)


def hard_delete_test_user(emp_no: str) -> None:
    supabase_repository.hard_delete_test_user(str(emp_no).strip())


def hard_delete_test_work_type(code: str) -> None:
    supabase_repository.hard_delete_test_work_type(str(code).strip())


def hard_delete_test_team(dept_code: str, team_code: str) -> None:
    supabase_repository.hard_delete_test_team(str(dept_code).strip(), str(team_code).strip())


def hard_delete_test_department(dept_code: str) -> None:
    supabase_repository.hard_delete_test_department(str(dept_code).strip())


def reset_supabase_client() -> None:
    supabase_repository.reset_client()


def sample_seed_frames() -> dict[str, pd.DataFrame]:
    """샘플 CSV를 화면 자연키 형식으로 변환해 seed 순서대로 반환한다."""
    return {
        "departments": _base_departments(),
        "teams": _base_teams(),
        "work_types": _base_work_types(),
        "users": _base_users(),
        "work_schedules": _base_schedules(),
    }
