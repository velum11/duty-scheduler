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

# --- 비밀번호 인증 (migration 008) ---
# 초기 비밀번호는 사번이며 최초 로그인 시 변경을 강제한다. 사번은 비밀이 아니므로
# 방치된 계정을 남이 선점하지 못하도록 초기 비밀번호에 유효기간을 둔다(특히 ADMIN).
INITIAL_PASSWORD_VALID_DAYS = 7
# 연속 실패 잠금 — 사용자가 실제 비번을 설정한 뒤의 무차별 대입을 늦춘다.
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_MINUTES = 10

# --- 임시 고정 비밀번호 (정책 예외, 한시적) ---
# 사용자 지시(2026-08-05): 개발·베타 준비 동안 지정 관리자 계정의 비밀번호를 고정하고
# 강제변경·길이·사번동일 금지 정책을 면제한다. 여기 등재된 계정은:
#   * 이 고정값으로만 로그인하며(저장된 해시가 있어도 무시)
#   * 최초 변경을 요구받지 않고
#   * 비밀번호 변경이 거부된다(고정값이 계속 통하므로 변경이 무의미).
# 키는 **DB 원본 사번과 정확히 일치**해야 한다(대소문자 무시 아님) — 이 DB 에는
# 'ADMIN'(활성)과 'admin'(비활성)이 함께 있어, casefold 로 맞추면 의도하지 않은
# 계정까지 예외가 된다.
#
# !! 베타 오픈 전에 이 dict 를 비운다. 비우면 예외는 전부 사라지고 해당 계정은
#    일반 정책(초기 비번=사번, 최초 로그인 시 변경 강제)으로 돌아간다.
FIXED_PASSWORD_ACCOUNTS: dict[str, str] = {
    "ADMIN": "ADMIN",
}

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
