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

# 로컬 샘플 모드에서 편집 결과를 담아 세션 동안 유지하는 스토어 키.
_USERS_STORE = "store_users"


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
def get_departments() -> pd.DataFrame:
    # departments 는 dept_code 를 이미 보유하므로 그대로 반환한다.
    return sample_data.departments()


def get_teams() -> pd.DataFrame:
    df = sample_data.teams()
    if df.empty:
        return df
    df = df.copy()
    df["dept_code"] = df["department_id"].astype(str).map(_dept_code_by_id()).fillna("")
    return df


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


def get_work_types() -> pd.DataFrame:
    return sample_data.work_types()


def get_schedules() -> pd.DataFrame:
    df = sample_data.work_schedules()
    if df.empty:
        return df
    df = df.copy()
    df["emp_no"] = df["user_id"].astype(str).map(_emp_no_by_id()).fillna("")
    df["duty_date"] = df["work_date"]
    return df


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
