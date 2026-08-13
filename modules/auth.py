"""로그인 / 세션 / 쿠키 관리.

- 사번 + 비밀번호 로그인 (migration 008).
- 초기 비밀번호는 사번이며(``password_hash IS NULL`` 상태), 최초 로그인 시 변경을
  강제한다. 사번은 비밀이 아니므로 초기 비밀번호에는 유효기간을 둔다 — 방치된 계정을
  남이 먼저 선점해 비번을 설정하고 본인을 잠가버리는 창을 닫는다(특히 ADMIN).
- 로그인 성공 시 랜덤 토큰을 발급해 브라우저 쿠키에 저장 → 새로고침/재접속 시 자동 로그인.
- 세션 저장소:
    * supabase 모드 → ``login_sessions`` 테이블. 원문 토큰이 아니라 sha256 만 저장한다.
    * sample 모드   → 기존 로컬 JSON 폴백(.local_sessions.json). 로컬 개발 편의 유지.
  Streamlit Cloud 컨테이너 파일시스템은 휘발성이라, 운영 모드에서 파일 폴백을 쓰면
  재배포·재시작마다 전원 로그아웃된다. 그래서 테이블이 기본이다.

비밀번호 검증·잠금 판정은 전부 이 앱 계층이 한다(DB 는 저장 형태와 상태 정합만 보장).
앱이 service_role 로 접근하는 현재 구조에서 인증 신뢰경계는 여기다.
"""
import hashlib
import hmac
import json
import secrets as pysecrets
from datetime import datetime, timedelta, timezone

import streamlit as st

from modules import config, db, passwords


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


def _token_hash(token: str) -> str:
    """세션 조회 키 — 원문 토큰의 sha256.

    DB 에는 이 값만 저장한다. 덤프가 유출돼도 그 값으로 세션을 재생할 수 없다
    (원문은 브라우저 쿠키에만 존재). 비밀번호 해시와 같은 이유다.
    """
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _issue_token(emp_no: str) -> str:
    token = pysecrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(days=config.SESSION_TTL_DAYS)
    if db.use_session_table():
        db.create_login_session(_token_hash(token), str(emp_no), expires.isoformat())
        # 만료 행 lazy cleanup — 실패해도 로그인을 막지 않는다(정리는 부수 작업).
        try:
            db.purge_expired_sessions()
        except Exception:
            pass
        return token
    sessions = _load_sessions()
    # 만료 세션 lazy cleanup
    sessions = {t: v for t, v in sessions.items() if _parse(v["expires_at"]) > now}
    sessions[token] = {
        "emp_no": str(emp_no),
        "expires_at": expires.isoformat(),
    }
    _save_sessions(sessions)
    return token


def _revoke_token(token: str) -> None:
    if not token:
        return
    if db.use_session_table():
        try:
            db.revoke_login_session(_token_hash(token), "logout")
        except Exception:
            # 로그아웃은 세션 상태·쿠키 정리가 본체다. 원격 폐기 실패가 로그아웃 자체를
            # 막으면 사용자는 로그아웃도 못 한 채 화면에 갇힌다(호출부가 계속 진행).
            pass
        return
    sessions = _load_sessions()
    if sessions.pop(token, None) is not None:
        _save_sessions(sessions)


def _validate_token(token: str):
    """토큰이 유효하면 사용자 dict, 아니면 None. 만료 토큰은 정리한다."""
    if not token:
        return None
    if db.use_session_table():
        record = db.find_login_session(_token_hash(token))
        if not record:
            return None
        # 폐기(로그아웃·비번 변경·ADMIN 초기화)는 만료와 무관하게 즉시 무효다.
        if record.get("revoked_at"):
            return None
        expires_at = record.get("expires_at")
        if not expires_at or _parse(str(expires_at)) <= _now():
            return None
        emp_no = str(record.get("emp_no") or "")
        try:
            db.touch_login_session(_token_hash(token))
        except Exception:
            pass  # 마지막 사용 시각은 감사용 부가정보 — 실패가 인증을 막지 않는다.
    else:
        sessions = _load_sessions()
        rec = sessions.get(token)
        if not rec:
            return None
        if _parse(rec["expires_at"]) <= _now():
            _revoke_token(token)
            return None
        emp_no = rec["emp_no"]
    user = db.find_user_by_emp_no(emp_no)
    if user is None or not user.get("is_active", False):
        return None
    # 퇴사일이 지나면 이미 발급된 세션도 즉시 끊는다 — 로그인만 막으면 재직 중 받아둔
    # 30일 쿠키로 퇴사 후에도 계속 들어올 수 있다.
    if _is_resigned(user):
        _revoke_token(token)
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
# 자격증명 실패를 사용자에게 알릴 때 쓰는 단일 문구. "사번은 있는데 비번이 틀렸다"와
# "사번 자체가 없다"를 구분해 알려주면 유효한 사번 목록을 캐낼 수 있으므로 합친다.
_BAD_CREDENTIALS = "사번 또는 비밀번호가 올바르지 않습니다."


def _is_resigned(user) -> bool:
    """퇴사일이 지난 사용자인지(migration 009). 판정은 db.is_resigned 가 소유한다.

    퇴사자에게도 ``_BAD_CREDENTIALS`` 를 돌려주는 것은 비활성 계정과 같은 처리다 —
    "퇴사한 계정입니다"라고 알려주면 그 사번이 실재한다는 사실을 확인해 준다.
    """
    if not isinstance(user, dict):
        return False
    return db.is_resigned(user.get("resign_date"))


def fixed_password_for(emp_no: str) -> str | None:
    """정규 사번이 한시적 고정 비밀번호 예외 대상이면 그 고정값, 아니면 None.

    비교는 **정확 일치**다(trim 만, casefold 아님). 이 DB 에는 대소문자만 다른
    'ADMIN'/'admin' 이 별개 계정으로 존재하므로, casefold 로 맞추면 의도하지 않은
    계정까지 예외가 된다 — 인가 *부여* 판정에 정확 일치를 쓰는 _emp_exact_match 와
    같은 근거다.
    """
    key = str(emp_no or "").strip()
    if not key:
        return None
    return config.FIXED_PASSWORD_ACCOUNTS.get(key)


def _lock_message(locked_until: datetime) -> str:
    remaining = max(1, int((locked_until - _now()).total_seconds() // 60) + 1)
    return f"로그인 시도가 많아 계정이 잠겼습니다. {remaining}분 후 다시 시도하세요."


def _register_failure(emp_no: str, credential: dict) -> str:
    """실패 카운트를 올리고, 임계값을 넘으면 잠근다. 사용자에게 보일 메시지를 반환한다."""
    count = int(credential.get("failed_login_count") or 0) + 1
    locked_until = None
    if count >= config.LOGIN_MAX_FAILURES:
        locked_until = _now() + timedelta(minutes=config.LOGIN_LOCK_MINUTES)
        count = 0  # 잠금으로 대체되므로 카운터는 초기화한다(잠금 해제 후 다시 센다).
    try:
        db.update_login_failure(
            emp_no, count, locked_until.isoformat() if locked_until else None
        )
    except Exception:
        # 카운터 기록 실패가 "비번이 틀렸다"는 판정을 뒤집지는 않는다(fail-closed).
        pass
    if locked_until is not None:
        return _lock_message(locked_until)
    return _BAD_CREDENTIALS


def login(emp_no: str, password: str = ""):
    """(user_dict, None) 또는 (None, error_message) 반환.

    초기 비밀번호(사번)와 설정된 비밀번호를 한 경로에서 처리한다:
    ``password_hash IS NULL`` 이면 아직 비번을 설정하지 않은 계정이라 입력값을 사번과
    비교하고, 그렇지 않으면 저장된 해시로 검증한다. 어느 쪽이든 성공 후
    ``must_change_password`` 가 참이면 호출부가 비번 변경 화면으로 보낸다.
    """
    emp_no = str(emp_no or "").strip()
    if not emp_no:
        return None, "사번을 입력하세요."
    if not password:
        return None, "비밀번호를 입력하세요."

    # 사번 조회는 trim + 대소문자 무시(find_user_by_emp_no). 세션/토큰에는
    # 입력값이 아니라 DB 의 정규 emp_no 를 저장해 대소문자 표기 흔들림을 막는다.
    user = db.find_user_by_emp_no(emp_no)
    if user is None or not user.get("is_active", False):
        return None, _BAD_CREDENTIALS
    # 퇴사자 차단은 고정 비밀번호 예외보다 **앞**이다. 예외는 "스키마 미적용 환경에서도
    # 관리자가 들어올 수 있게" 하려는 것이지, 퇴사한 계정을 살려두려는 것이 아니다.
    if _is_resigned(user):
        return None, _BAD_CREDENTIALS
    canonical = str(user.get("emp_no", emp_no))

    # 한시적 고정 비밀번호 예외 — 등재 계정은 고정값으로만 로그인하고 강제변경을 면제한다.
    # 스키마 게이트보다 **앞**에 둔다: 008 미적용 환경에서도 지정 관리자는 들어올 수 있어야
    # 한다는 것이 이 예외의 목적이기 때문이다(자격증명 컬럼을 아예 읽지 않는 경로).
    # 그 대가로 이 계정에 한해 fail-closed 가드가 뚫린다 — config 의 등재를 지우면
    # 예외와 함께 가드도 원상복구된다.
    fixed = fixed_password_for(canonical)
    if fixed is not None:
        if not hmac.compare_digest(str(password), str(fixed)):
            return None, _BAD_CREDENTIALS
        token = _issue_token(canonical)
        st.session_state.pop("nav_page", None)
        st.session_state.user = user
        st.session_state.auth_token = token
        st.session_state.must_change_password = False
        _cookie_set(token)
        return user, None

    # 스키마 미적용이면 로그인을 거부한다(fail-closed). 비번 없는 예전 동작으로 조용히
    # 되돌아가면, 마이그레이션 누락을 모른 채 "비번이 켜졌다"고 믿고 운영에 들어간다.
    if not db.password_auth_ready():
        return None, (
            "비밀번호 인증 스키마(008)가 아직 적용되지 않아 로그인할 수 없습니다. "
            "관리자에게 문의하세요."
        )

    credential = db.get_user_credential(canonical)
    if credential is None:
        return None, _BAD_CREDENTIALS

    locked_raw = credential.get("locked_until")
    if locked_raw:
        locked_until = _parse(str(locked_raw))
        if locked_until > _now():
            return None, _lock_message(locked_until)

    stored = credential.get("password_hash")
    if stored:
        verified = passwords.verify_password(password, str(stored))
    else:
        # 비번 미설정 = 사번이 초기 비밀번호. 유효기간이 지났으면 ADMIN 초기화를 받아야 한다.
        expires_raw = credential.get("initial_password_expires_at")
        if expires_raw and _parse(str(expires_raw)) <= _now():
            return None, (
                "초기 비밀번호 사용 기간이 지났습니다. 관리자에게 초기화를 요청하세요."
            )
        verified = passwords.matches_employee_number(password, canonical)

    if not verified:
        return None, _register_failure(canonical, credential)

    try:
        db.clear_login_failure(canonical)
    except Exception:
        pass  # 성공 판정은 이미 끝났다. 카운터 초기화 실패가 로그인을 막지 않는다.

    token = _issue_token(canonical)
    st.session_state.pop("nav_page", None)
    st.session_state.user = user
    st.session_state.auth_token = token
    # 해시가 없으면(초기 비밀번호) 플래그와 무관하게 변경을 강제한다 — 플래그가 어떤
    # 경로로든 꺼져 있어도 사번을 비번으로 쓰는 상태로 서비스에 들어가지 못하게 한다.
    st.session_state.must_change_password = (
        not stored or _as_bool(credential.get("must_change_password", True))
    )
    _cookie_set(token)
    return user, None


def needs_password_change() -> bool:
    """현재 로그인 사용자가 비밀번호를 바꾸기 전인가(라우팅 게이트).

    베타 한시 스위치(config.BETA_SKIP_FORCED_PASSWORD_CHANGE)가 켜져 있으면 게이트를
    통째로 끈다 — 세션의 must_change_password 판정 자체는 그대로 계산·보존되므로
    스위치를 끄는 즉시 강제변경이 복원된다."""
    if config.BETA_SKIP_FORCED_PASSWORD_CHANGE:
        return False
    if not st.session_state.get("user"):
        return False
    return bool(st.session_state.get("must_change_password", False))


def change_password(current_password: str, new_password: str, confirm_password: str):
    """로그인 사용자의 비밀번호를 변경한다. (True, None) 또는 (False, error_message).

    성공 시 그 사용자의 **다른 모든 세션을 폐기**하고 현재 세션에는 새 토큰을 발급한다 —
    비번을 바꿔도 예전 쿠키가 계속 유효하면 자격증명 교체의 의미가 없다.
    """
    user = st.session_state.get("user")
    if not user:
        return False, "로그인 상태가 아닙니다."
    canonical = str(user.get("emp_no") or "").strip()
    if not canonical:
        return False, "사용자 사번을 확인할 수 없습니다."

    # 고정 비밀번호 예외 계정은 변경을 거부한다 — 바꿔봐야 고정값이 계속 통하므로
    # "바꿨다"는 잘못된 안심만 남는다. 예외를 풀려면 config 에서 등재를 지운다.
    if fixed_password_for(canonical) is not None:
        return False, (
            "이 계정은 관리자 지시로 비밀번호가 한시적으로 고정되어 있어 변경할 수 없습니다."
        )

    credential = db.get_user_credential(canonical)
    if credential is None:
        return False, "사용자 자격증명을 찾을 수 없습니다."

    # 현재 비밀번호 확인 — 자리를 비운 사이 남이 비번을 바꿔버리는 것을 막는다.
    stored = credential.get("password_hash")
    if stored:
        current_ok = passwords.verify_password(current_password, str(stored))
    else:
        current_ok = passwords.matches_employee_number(current_password, canonical)
    if not current_ok:
        return False, "현재 비밀번호가 올바르지 않습니다."

    if new_password != confirm_password:
        return False, "새 비밀번호가 서로 일치하지 않습니다."
    policy_error = passwords.validate_new_password(new_password, canonical)
    if policy_error:
        return False, policy_error
    if new_password == current_password:
        return False, "현재 비밀번호와 다른 비밀번호를 사용하세요."

    db.set_user_password(canonical, passwords.hash_password(new_password))

    # 기존 세션 전부 폐기 → 현재 세션에 새 토큰 재발급(본인은 로그아웃되지 않는다).
    old_token = st.session_state.get("auth_token")
    try:
        db.revoke_user_sessions(canonical, "password_change")
    except Exception:
        pass
    if not db.use_session_table() and old_token:
        _revoke_token(old_token)
    token = _issue_token(canonical)
    st.session_state.auth_token = token
    st.session_state.must_change_password = False
    _cookie_set(token)
    return True, None


def logout() -> None:
    _revoke_token(st.session_state.get("auth_token"))
    _cookie_clear()
    for k in ("user", "auth_token", "nav_page", "must_change_password"):
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
        # 쿠키 자동 로그인도 강제변경 게이트를 그대로 받는다. 이 값을 세우지 않으면
        # 변경 화면에서 새로고침하는 것만으로 게이트를 지나칠 수 있다(fail-closed).
        st.session_state.must_change_password = _must_change_for(user)
    return user


def _must_change_for(user) -> bool:
    """자격증명을 다시 읽어 강제변경 여부를 판정한다. 읽기 실패는 True 로 접는다.

    쿠키 자동 로그인 경로에서 쓴다. 판정을 못 하면 "바꿔야 한다"로 보내는 쪽이 안전하다 —
    비번 미설정 계정을 일반 화면에 들여보내는 것보다 변경 화면을 한 번 더 보는 편이 낫다.
    """
    emp_no = str((user or {}).get("emp_no") or "").strip()
    if not emp_no:
        return True
    if fixed_password_for(emp_no) is not None:
        return False  # 고정 비밀번호 예외 계정은 강제변경 대상이 아니다.
    try:
        credential = db.get_user_credential(emp_no)
    except Exception:
        return True
    if credential is None:
        return True
    return (not credential.get("password_hash")) or _as_bool(
        credential.get("must_change_password", True)
    )


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


def is_admin(user) -> bool:
    """행위자가 ADMIN 인지(role 대소문자 무시). 개선조치 작업/검토 인가의 전역 우회 근거."""
    if not user:
        return False
    return str(user.get("role", "")).strip().upper() == "ADMIN"


def _emp_exact_match(actor_emp, stored_emp) -> bool:
    """권위 사번 정확 일치(trim only, casefold 아님).

    개선조치 인가 *부여*(담당자·확인자 본인 매칭)는 정확 일치를 쓴다 — 대소문자만 다른
    사번은 계약상 별개 계정(supabase 는 서로 다른 user_id, requirements.md)이므로 casefold
    로 매칭하면 sample 에서만 다른 계정에 권한이 새어 supabase(user_id 매칭)와 어긋난다.
    저장된 담당자/확인자 사번과 actor 사번은 같은 사람의 권위 원본값이라 정확 일치로
    정당한 주체를 배제하지 않는다(아차사고 보고 소유자 게이트와 동일한 근거). 자기확인
    *금지* 같은 배제 판정은 반대로 casefold(포괄) 를 쓴다 — 우회를 넓게 막아야 하므로."""
    actor_emp = str(actor_emp or "").strip()
    return actor_emp != "" and actor_emp == str(stored_emp or "").strip()


def can_work_improvement(user, improvement) -> bool:
    """개선조치 **작업 필드**(조치 저장·제출) 권한: 저장된 배정 담당자 본인 또는 ADMIN.

    ``improvement`` 는 자연키 계약 dict(assignee_emp_no 포함) 또는 None(미배정)이다.
    미배정(None)이면 담당자 본인 매칭이 성립하지 않으므로 ADMIN 만 참이다 — 담당자는
    배정 전에 스스로 조치를 만들 수 없다(배정은 평가자/ADMIN 전용)."""
    if not user:
        return False
    if is_admin(user):
        return True
    if not improvement:
        return False
    return _emp_exact_match(user.get("emp_no"), improvement.get("assignee_emp_no"))


def can_review_improvement(user, improvement) -> bool:
    """개선조치 **검토 행위**(확인·재조치 요청·종결) 권한: 지정 확인자 본인 또는 평가 능력
    (ADMIN/MANAGER/안전담당자).

    ``improvement=None`` 이면 지정 확인자를 알 수 없어 평가 능력자만 참이다. 자기확인
    금지(확인 시 담당자 본인 배제)는 이 함수가 아니라 확인 파사드가 추가로 강제한다 —
    검토 권한과 자기확인 금지는 별개 규칙이다."""
    if not user:
        return False
    if can_evaluate_near_miss(user):   # ADMIN/MANAGER/안전담당자 (ADMIN 포함)
        return True
    if not improvement:
        return False
    return _emp_exact_match(user.get("emp_no"), improvement.get("designated_confirmer_emp_no"))


def can_access_improvement(user, improvement) -> bool:
    """개선조치 **개별 조회** 권한: 작업 권한 또는 검토 권한 중 하나.

    = 저장된 담당자 · 지정 확인자 · 평가자 · ADMIN. 그 밖의 인증 사용자는 report_id 를
    넘겼다는 이유만으로 접근할 수 없다(actor-aware 스코핑의 단일 판정 지점)."""
    return can_work_improvement(user, improvement) or can_review_improvement(user, improvement)
