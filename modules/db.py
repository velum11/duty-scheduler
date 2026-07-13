"""데이터 접근 계층 (data source facade).

Phase 1: 항상 로컬 샘플 데이터(sample_data)를 사용한다.
Phase 5: supabase_configured() 가 True 면 이 함수들을 Supabase 쿼리로 교체한다.
         화면/로직 코드는 db 함수만 호출하므로, 데이터 소스 전환 시 이 파일만 바뀐다.

저장 계층(CSV/Supabase)은 docs/database.md 대로 id 기반(department_id / team_id /
user_id)이다. 화면은 자연키(dept_code / team_code / emp_no / duty_date)를 쓰므로,
이 파사드에서 기준정보를 조인해 자연키 컬럼을 덧붙여 반환한다. 원본(캐시된)
DataFrame 을 훼손하지 않도록 항상 copy 후 컬럼을 추가한다.
"""
import pandas as pd
import streamlit as st

from modules import config, sample_data

# 화면이 사용하는 사용자 자연키 컬럼 (id/외래키는 파사드 내부에서만 사용).
USER_COLUMNS = ["emp_no", "name", "dept_code", "team_code", "position", "role", "is_active"]

# 화면이 사용하는 부서 컬럼 (id 는 파사드 내부 매핑에만 사용).
DEPT_COLUMNS = ["dept_code", "dept_name", "sort_order", "is_active"]

# 화면이 사용하는 조/팀 컬럼 (id/department_id 는 파사드 내부 매핑에만 사용).
TEAM_COLUMNS = ["dept_code", "team_code", "team_name", "sort_order", "is_active"]

# 화면이 사용하는 근무형태 컬럼 (id 는 파사드 내부 매핑에만 사용).
WORK_TYPE_COLUMNS = [
    "code", "name", "category", "short_label", "start_time", "end_time",
    "color", "is_work", "affects_allowance", "description", "sort_order", "is_active",
]

# 화면이 사용하는 근무표 자연키 컬럼 (id/user_id/work_date 는 파사드 내부에서만 사용).
SCHEDULE_COLUMNS = ["emp_no", "duty_date", "work_type_code", "note"]

# 로컬 샘플 모드에서 편집 결과를 담아 세션 동안 유지하는 스토어 키.
_USERS_STORE = "store_users"
_DEPTS_STORE = "store_departments"
_TEAMS_STORE = "store_teams"
_WORK_TYPES_STORE = "store_work_types"
_SCHEDULES_STORE = "store_schedules"


def datasource() -> str:
    """현재 데이터 소스 이름. 'supabase' 또는 'sample'."""
    return "supabase" if config.supabase_configured() else "sample"


def is_sample_mode() -> bool:
    return datasource() == "sample"


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
        return pd.DataFrame(columns=DEPT_COLUMNS)
    return df[DEPT_COLUMNS].reset_index(drop=True).copy()


def get_departments() -> pd.DataFrame:
    """부서 목록(DEPT_COLUMNS).

    로컬 샘플 모드에서는 세션 편집 결과(save_departments)를 우선 반환하므로,
    부서 관리 화면에서 저장한 내용이 다른 화면에도 그대로 반영된다.
    Phase 5(Supabase)에서는 이 분기를 실제 조회로 교체한다.
    """
    if is_sample_mode():
        if _DEPTS_STORE not in st.session_state:
            st.session_state[_DEPTS_STORE] = _base_departments()
        return st.session_state[_DEPTS_STORE].copy()
    return _base_departments()


def save_departments(df: pd.DataFrame) -> None:
    """편집된 부서 목록을 저장한다.

    로컬 샘플 모드에서는 세션 상태에 보관해 현재 세션 동안 유지한다(CSV 는 건드리지
    않는다). Phase 5(Supabase)에서는 여기서 upsert / is_active 소프트삭제로 교체한다.
    """
    keep = [c for c in DEPT_COLUMNS if c in df.columns]
    st.session_state[_DEPTS_STORE] = df[keep].reset_index(drop=True).copy()


def _base_teams() -> pd.DataFrame:
    """샘플 CSV(id 기반)를 화면용 조/팀 컬럼(TEAM_COLUMNS)으로 변환한 원본."""
    df = sample_data.teams()
    if df.empty:
        return pd.DataFrame(columns=TEAM_COLUMNS)
    df = df.copy()
    df["dept_code"] = df["department_id"].astype(str).map(_dept_code_by_id()).fillna("")
    return df[TEAM_COLUMNS].reset_index(drop=True).copy()


def get_teams() -> pd.DataFrame:
    """조/팀 목록(TEAM_COLUMNS).

    로컬 샘플 모드에서는 세션 편집 결과(save_teams)를 우선 반환하므로,
    조 관리 화면에서 저장한 내용이 다른 화면에도 그대로 반영된다.
    Phase 5(Supabase)에서는 이 분기를 실제 조회로 교체한다.
    """
    if is_sample_mode():
        if _TEAMS_STORE not in st.session_state:
            st.session_state[_TEAMS_STORE] = _base_teams()
        return st.session_state[_TEAMS_STORE].copy()
    return _base_teams()


def save_teams(df: pd.DataFrame) -> None:
    """편집된 조/팀 목록을 저장한다.

    로컬 샘플 모드에서는 세션 상태에 보관해 현재 세션 동안 유지한다(CSV 는 건드리지
    않는다). Phase 5(Supabase)에서는 여기서 upsert / is_active 소프트삭제로 교체한다.
    """
    keep = [c for c in TEAM_COLUMNS if c in df.columns]
    st.session_state[_TEAMS_STORE] = df[keep].reset_index(drop=True).copy()


def _base_users() -> pd.DataFrame:
    """샘플 CSV(id 기반)를 화면용 자연키 컬럼(USER_COLUMNS)으로 변환한 원본."""
    df = sample_data.users()
    if df.empty:
        return pd.DataFrame(columns=USER_COLUMNS)
    df = df.copy()
    df["dept_code"] = df["department_id"].astype(str).map(_dept_code_by_id()).fillna("")
    df["team_code"] = df["team_id"].astype(str).map(_team_code_by_id()).fillna("")
    return df[USER_COLUMNS].reset_index(drop=True)


def get_users() -> pd.DataFrame:
    """사용자 목록(USER_COLUMNS).

    로컬 샘플 모드에서는 세션 편집 결과(save_users)를 우선 반환하므로,
    사용자 관리 화면에서 저장한 내용이 다른 화면에도 그대로 반영된다.
    Phase 5(Supabase)에서는 이 분기를 실제 조회로 교체한다.
    """
    if is_sample_mode():
        if _USERS_STORE not in st.session_state:
            st.session_state[_USERS_STORE] = _base_users()
        return st.session_state[_USERS_STORE].copy()
    return _base_users()


def save_users(df: pd.DataFrame) -> None:
    """편집된 사용자 목록을 저장한다.

    로컬 샘플 모드에서는 세션 상태에 보관해 현재 세션 동안 유지한다(CSV 는 건드리지
    않는다). Phase 5(Supabase)에서는 여기서 upsert / is_active 소프트삭제로 교체한다.
    """
    keep = [c for c in USER_COLUMNS if c in df.columns]
    st.session_state[_USERS_STORE] = df[keep].reset_index(drop=True).copy()


def _base_work_types() -> pd.DataFrame:
    """샘플 CSV 를 화면용 근무형태 컬럼(WORK_TYPE_COLUMNS)으로 정리한 원본."""
    df = sample_data.work_types()
    if df.empty:
        return pd.DataFrame(columns=WORK_TYPE_COLUMNS)
    df = df.copy()
    for c in WORK_TYPE_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[WORK_TYPE_COLUMNS].reset_index(drop=True).copy()


def get_work_types() -> pd.DataFrame:
    """근무형태 목록(WORK_TYPE_COLUMNS).

    로컬 샘플 모드에서는 세션 편집 결과(save_work_types)를 우선 반환하므로,
    근무형태 관리 화면에서 저장한 내용이 다른 화면에도 그대로 반영된다.
    Phase 5(Supabase)에서는 이 분기를 실제 조회로 교체한다.
    """
    if is_sample_mode():
        if _WORK_TYPES_STORE not in st.session_state:
            st.session_state[_WORK_TYPES_STORE] = _base_work_types()
        return st.session_state[_WORK_TYPES_STORE].copy()
    return _base_work_types()


def save_work_types(df: pd.DataFrame) -> None:
    """편집된 근무형태 목록을 저장한다.

    로컬 샘플 모드에서는 세션 상태에 보관해 현재 세션 동안 유지한다(CSV 는 건드리지
    않는다). Phase 5(Supabase)에서는 여기서 upsert / is_active 소프트삭제로 교체한다.
    """
    keep = [c for c in WORK_TYPE_COLUMNS if c in df.columns]
    st.session_state[_WORK_TYPES_STORE] = df[keep].reset_index(drop=True).copy()


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
    return _base_schedules()


def save_schedules(df: pd.DataFrame) -> None:
    """근무표 전체(세로형 long format, SCHEDULE_COLUMNS)를 저장한다.

    화면(schedule_edit)에서 (선택 직원 × 선택 월) 범위만 교체해 만든 전체
    스냅샷을 넘겨받아 세션 스토어에 그대로 보관한다. 로컬 샘플 모드에서는 현재
    세션 동안만 유지하며 CSV 는 건드리지 않는다. Phase 5(Supabase)에서는 여기서
    범위 삭제 후 batch upsert 로 교체한다.
    """
    keep = [c for c in SCHEDULE_COLUMNS if c in df.columns]
    st.session_state[_SCHEDULES_STORE] = df[keep].reset_index(drop=True).copy()


# --- 조회 헬퍼 ---
def find_user_by_emp_no(emp_no: str):
    """사번으로 사용자 1명을 dict 로 반환. 없으면 None."""
    df = get_users()
    if df.empty:
        return None
    match = df[df["emp_no"].astype(str).str.strip() == str(emp_no).strip()]
    return None if match.empty else match.iloc[0].to_dict()


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
            "color": r["color"] or "#9AA0A6",
            "is_work": bool(r["is_work"]),
        }
    return out


def get_user_schedules(emp_no: str) -> pd.DataFrame:
    """특정 사번의 근무표 레코드(long format). 컬럼: emp_no, duty_date, work_type_code, note."""
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
