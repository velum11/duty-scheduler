"""로그인 / 세션 / 쿠키 관리.

- 사번만 입력하는 로그인 (비밀번호 없음, MVP).
- 로그인 성공 시 랜덤 토큰을 발급해 브라우저 쿠키에 저장 → 새로고침/재접속 시 자동 로그인.
- Phase 1 폴백: 토큰-세션 매핑을 로컬 JSON 파일(.local_sessions.json)에 저장한다.
  Phase 5 에서는 login_sessions 테이블로 교체한다.

보안 한계(항상 고지): 타인의 사번을 아는 사람은 그 사람으로 로그인할 수 있다.
사내 구성원 대상 MVP 로 수용하며, 추후 사번+이름 확인 또는 PIN 으로 강화한다.
"""
import json
import secrets as pysecrets
from datetime import datetime, timedelta, timezone

import streamlit as st

from modules import config, db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --- 로컬 세션 저장소 (폴백) ---
def _load_sessions() -> dict:
    try:
        return json.loads(config.SESSIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_sessions(data: dict) -> None:
    try:
        config.SESSIONS_FILE.write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def _issue_token(emp_no: str) -> str:
    token = pysecrets.token_urlsafe(32)
    sessions = _load_sessions()
    now = _now()
    # 만료 세션 lazy cleanup
    sessions = {t: v for t, v in sessions.items() if _parse(v["expires_at"]) > now}
    sessions[token] = {
        "emp_no": str(emp_no),
        "expires_at": (now + timedelta(days=config.SESSION_TTL_DAYS)).isoformat(),
    }
    _save_sessions(sessions)
    return token


def _revoke_token(token: str) -> None:
    if not token:
        return
    sessions = _load_sessions()
    if sessions.pop(token, None) is not None:
        _save_sessions(sessions)


def _validate_token(token: str):
    """토큰이 유효하면 사용자 dict, 아니면 None. 만료 토큰은 정리한다."""
    if not token:
        return None
    sessions = _load_sessions()
    rec = sessions.get(token)
    if not rec:
        return None
    if _parse(rec["expires_at"]) <= _now():
        _revoke_token(token)
        return None
    user = db.find_user_by_emp_no(rec["emp_no"])
    if user is None or not user.get("is_active", False):
        return None
    return user


# --- 쿠키 컨트롤러 (없거나 실패해도 앱은 동작) ---
def _cookies():
    if "cookie_ctrl" not in st.session_state:
        try:
            from streamlit_cookies_controller import CookieController

            st.session_state.cookie_ctrl = CookieController()
        except Exception:
            st.session_state.cookie_ctrl = None
    return st.session_state.cookie_ctrl


def _cookie_set(token: str) -> None:
    ctrl = _cookies()
    if ctrl is not None:
        try:
            ctrl.set(config.COOKIE_NAME, token, max_age=config.SESSION_TTL_DAYS * 86400)
        except Exception:
            pass


def _cookie_get():
    ctrl = _cookies()
    if ctrl is None:
        return None
    try:
        return ctrl.get(config.COOKIE_NAME)
    except Exception:
        return None


def _cookie_clear() -> None:
    ctrl = _cookies()
    if ctrl is not None:
        try:
            ctrl.remove(config.COOKIE_NAME)
        except Exception:
            pass


# --- 공개 API ---
def login(emp_no: str):
    """(user_dict, None) 또는 (None, error_message) 반환."""
    emp_no = str(emp_no or "").strip()
    if not emp_no:
        return None, "사번을 입력하세요."
    # 사번 조회는 trim + 대소문자 무시(find_user_by_emp_no). 세션/토큰에는
    # 입력값이 아니라 DB 의 정규 emp_no 를 저장해 대소문자 표기 흔들림을 막는다.
    user = db.find_user_by_emp_no(emp_no)
    if user is None or not user.get("is_active", False):
        return None, "등록되지 않은 사번입니다. 관리자에게 문의하세요."
    token = _issue_token(user.get("emp_no", emp_no))
    st.session_state.pop("nav_page", None)
    st.session_state.user = user
    st.session_state.auth_token = token
    _cookie_set(token)
    return user, None


def logout() -> None:
    _revoke_token(st.session_state.get("auth_token"))
    _cookie_clear()
    for k in ("user", "auth_token", "nav_page"):
        st.session_state.pop(k, None)
    # 화면별 저장 조회조건(run_query 의 q_* — 예: q_schedule_view/q_schedule_edit)을
    # 지운다. 이전 사용자의 조회범위(부서 등)가 로그인 간 잔존해 다음 사용자에게
    # 노출되는 stale 권한범위 누출을 막는다(fail-closed).
    for k in [key for key in list(st.session_state.keys()) if str(key).startswith("q_")]:
        st.session_state.pop(k, None)


def get_current_user():
    """현재 로그인 사용자 dict 또는 None.

    1) session_state 에 있으면 그대로 사용
    2) 없으면 쿠키의 토큰을 검증해 자동 로그인 (로그인 유지)
    """
    if st.session_state.get("user"):
        return st.session_state.user

    token = _cookie_get()
    user = _validate_token(token) if token else None
    if user:
        st.session_state.user = user
        st.session_state.auth_token = token
    return user


# --- 능력(권한) 헬퍼 — 아차사고 평가 (migration 006) ---
# nav.allowed(화면 접근)와 별개의 '행위 능력' 판정 함수만 제공한다. nav 렌더/라우팅은
# 바꾸지 않으며(UI 담당), 화면이 평가 버튼 노출·차단에 이 함수를 호출한다.
# 참(True)로 볼 값 집합(canonical). 문자열 "false"/"0"/"" 등은 False 로 접는다
# (bool("false") 가 True 가 되는 파이썬 함정 방지 — supabase_repository._clean_bool 과 정합).
_TRUE_TOKENS = frozenset({"true", "1", "yes", "y", "t", "on"})


def _as_bool(value) -> bool:
    """실제 True / 1 / "true" 계열만 참으로 본다. 그 외(문자열 "false" 포함)는 거짓."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    return str(value).strip().lower() in _TRUE_TOKENS


def is_safety_officer(user) -> bool:
    """사용자가 안전담당자로 지정됐는지. user dict 의 is_safety_officer 를 읽는다.

    이 플래그는 로그인 시 db.find_user_by_emp_no 가 세션 사용자 dict 에 실어준다.
    세션 캐시 주의: 플래그를 바꾸면 재로그인해야 반영된다(get_current_user 가 세션
    사용자를 우선 반환하기 때문).
    """
    if not user:
        return False
    return _as_bool(user.get("is_safety_officer", False))


def can_evaluate_near_miss(user) -> bool:
    """아차사고 평가(확정 등급 부여) 능력: ADMIN 또는 MANAGER 또는 안전담당자."""
    if not user:
        return False
    role = str(user.get("role", "")).strip().upper()
    return role in ("ADMIN", "MANAGER") or is_safety_officer(user)
