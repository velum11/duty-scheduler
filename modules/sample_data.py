"""로컬 샘플 데이터 로딩 (data/sample/*.csv).

Supabase 미설정 시 이 모듈이 데이터 소스를 대신한다 (Phase 1 은 읽기 전용).
CSV 구조는 docs/database.md 의 테이블 구조를 그대로 따른다 — 각 테이블은 `id`
기본키를 가지고, 참조는 `department_id` / `team_id` / `user_id` 로 연결한다.
이 모듈은 CSV 를 원형(id 기반) 그대로 로드·타입변환만 하며, 화면이 쓰는 자연키
컬럼(dept_code / team_code / emp_no 등)으로의 조인은 db.py 파사드에서 처리한다.
"""
import pandas as pd
import streamlit as st

from modules import config

_TRUE = {"true", "1", "y", "yes", "t"}


def _read(name: str) -> pd.DataFrame:
    path = config.SAMPLE_DIR / f"{name}.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")


def _to_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin(_TRUE)


def _to_int(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0).astype(int)


@st.cache_data(show_spinner=False)
def departments() -> pd.DataFrame:
    df = _read("departments")
    if df.empty:
        return df
    df["is_active"] = _to_bool(df["is_active"])
    df["sort_order"] = _to_int(df["sort_order"])
    return df.sort_values("sort_order").reset_index(drop=True)


@st.cache_data(show_spinner=False)
def teams() -> pd.DataFrame:
    df = _read("teams")
    if df.empty:
        return df
    df["is_active"] = _to_bool(df["is_active"])
    df["sort_order"] = _to_int(df["sort_order"])
    df["_dept"] = _to_int(df["department_id"])
    return (
        df.sort_values(["_dept", "sort_order"])
        .drop(columns="_dept")
        .reset_index(drop=True)
    )


@st.cache_data(show_spinner=False)
def users() -> pd.DataFrame:
    df = _read("users")
    if df.empty:
        return df
    df["is_active"] = _to_bool(df["is_active"])
    return df.reset_index(drop=True)


@st.cache_data(show_spinner=False)
def work_types() -> pd.DataFrame:
    df = _read("work_types")
    if df.empty:
        return df
    df["is_work"] = _to_bool(df["is_work"])
    df["affects_allowance"] = _to_bool(df["affects_allowance"])
    df["is_active"] = _to_bool(df["is_active"])
    df["sort_order"] = _to_int(df["sort_order"])
    return df.sort_values("sort_order").reset_index(drop=True)


@st.cache_data(show_spinner=False)
def work_schedules() -> pd.DataFrame:
    df = _read("work_schedules")
    if df.empty:
        return df
    return df.reset_index(drop=True)
