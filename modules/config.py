"""공용 설정: 경로 상수, 앱 상수, Supabase 설정 감지.

이 모듈은 다른 modules 를 import 하지 않는다 (순환 참조 방지).
"""
import os
from pathlib import Path

import streamlit as st

# --- 경로 ---
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SAMPLE_DIR = DATA_DIR / "sample"
SESSIONS_FILE = ROOT / ".local_sessions.json"  # 로컬 폴백 로그인 세션 (gitignore)

# --- 앱 상수 ---
APP_NAME = "WorkOps"
SESSION_TTL_DAYS = 30           # 로그인 유지 기간
COOKIE_NAME = "duty_token"      # 브라우저 쿠키 키

ROLES = ("USER", "MANAGER", "ADMIN")

DATA_MODES = ("sample", "supabase")


class DataSourceConfigurationError(RuntimeError):
    """데이터 소스 설정이 없거나 유효하지 않을 때 발생한다."""


def _secret_section(name: str) -> dict:
    try:
        section = st.secrets.get(name, {})
        return dict(section) if section else {}
    except Exception:
        return {}


def data_mode() -> str:
    """명시적으로 선택한 데이터 모드를 반환한다."""
    app = _secret_section("app")
    mode = str(os.getenv("DUTY_DATA_MODE") or app.get("data_mode") or "").strip().lower()
    if not mode:
        raise DataSourceConfigurationError(
            "데이터 모드가 설정되지 않았습니다. DUTY_DATA_MODE 또는 "
            "[app].data_mode에 sample/supabase 중 하나를 지정하세요."
        )
    if mode not in DATA_MODES:
        raise DataSourceConfigurationError(
            f"지원하지 않는 데이터 모드입니다: {mode!r}. sample 또는 supabase를 사용하세요."
        )
    return mode


def supabase_settings() -> tuple[str, str]:
    """서버 전용 Supabase URL과 service role key를 검증해 반환한다."""
    conf = _secret_section("supabase")
    url = str(os.getenv("SUPABASE_URL") or conf.get("url") or "").strip().rstrip("/")
    key = str(
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or conf.get("service_role_key")
        or conf.get("key")
        or ""
    ).strip()
    if not url or not key:
        raise DataSourceConfigurationError(
            "Supabase 모드에는 SUPABASE_URL과 SUPABASE_SERVICE_ROLE_KEY 또는 "
            "[supabase].url/service_role_key가 필요합니다."
        )
    if not url.startswith("https://"):
        raise DataSourceConfigurationError("Supabase URL은 https:// 주소여야 합니다.")
    return url, key


def supabase_test_project_confirmed() -> bool:
    """원격 seed/CRUD 테스트가 허용된 테스트 프로젝트인지 확인한다."""
    conf = _secret_section("supabase")
    raw = os.getenv("DUTY_SUPABASE_TEST_PROJECT")
    if raw is None:
        raw = conf.get("test_project", False)
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def supabase_configured() -> bool:
    """Supabase 접속정보가 완전하게 설정됐는지 확인한다."""
    try:
        supabase_settings()
        return True
    except DataSourceConfigurationError:
        return False
