"""데이터 접근 계층 (data source facade).

Phase 1: 항상 로컬 샘플 데이터(sample_data)를 사용한다.
Phase 5: supabase_configured() 가 True 면 이 함수들을 Supabase 쿼리로 교체한다.
         화면/로직 코드는 db 함수만 호출하므로, 데이터 소스 전환 시 이 파일만 바뀐다.
"""
import pandas as pd

from modules import config, sample_data


def datasource() -> str:
    """현재 데이터 소스 이름. 'supabase' 또는 'sample'."""
    return "supabase" if config.supabase_configured() else "sample"


def is_sample_mode() -> bool:
    return datasource() == "sample"


# --- 기준정보 조회 ---
def get_departments() -> pd.DataFrame:
    # TODO(Phase 5): supabase 이면 departments 테이블 조회
    return sample_data.departments()


def get_teams() -> pd.DataFrame:
    return sample_data.teams()


def get_users() -> pd.DataFrame:
    return sample_data.users()


def get_work_types() -> pd.DataFrame:
    return sample_data.work_types()


def get_schedules() -> pd.DataFrame:
    return sample_data.work_schedules()


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
