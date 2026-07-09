"""공용 설정: 경로 상수, 앱 상수, Supabase 설정 감지.

이 모듈은 다른 modules 를 import 하지 않는다 (순환 참조 방지).
"""
from pathlib import Path

import streamlit as st

# --- 경로 ---
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SAMPLE_DIR = DATA_DIR / "sample"
SESSIONS_FILE = ROOT / ".local_sessions.json"  # 로컬 폴백 로그인 세션 (gitignore)

# --- 앱 상수 ---
APP_NAME = "생산 근무표 관리"
SESSION_TTL_DAYS = 30           # 로그인 유지 기간
COOKIE_NAME = "duty_token"      # 브라우저 쿠키 키

ROLES = ("USER", "MANAGER", "ADMIN")


def supabase_configured() -> bool:
    """secrets.toml 에 supabase url/key 가 있으면 True.

    설정이 없으면(파일 자체가 없는 경우 포함) False 를 돌려주고,
    앱은 로컬 샘플 데이터(data/sample/*.csv)로 동작한다. (DESIGN.md §3, NFR-03)
    """
    try:
        conf = st.secrets["supabase"]
        return bool(conf.get("url") and conf.get("key"))
    except Exception:
        return False
