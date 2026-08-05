"""비밀번호 해싱·검증·정책 (순수 함수 — I/O 없음).

저장 형식은 자기서술적이다::

    scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>

파라미터가 문자열 안에 들어있으므로 DB 는 알고리즘을 알 필요가 없고, 나중에 비용을
올리거나 알고리즘을 바꿔도 **기존 해시를 그대로 검증할 수 있다**(검증은 저장된 값의
파라미터를 쓰고, 신규 발급만 현재 기본값을 쓴다).

표준 라이브러리 ``hashlib.scrypt`` 를 쓴다 — bcrypt/argon2 를 넣으면 requirements 에
새 의존성이 생겨 Streamlit Cloud 빌드 실패 표면이 늘어난다. 사내 수십 명 규모에서
scrypt(n=2^14) 는 충분하고 의존성은 0 이다.

정책 (사용자 승인 2026-08-05):
  * 초기 비밀번호 = 사번. 최초 로그인 시 변경 강제.
  * 새 비밀번호 최소 8자, 사번과 동일한 값 금지.
  * 복잡도(특수문자) 강제 없음 — 현장 사용자 마찰 대비 실익이 낮다.
"""
import base64
import hashlib
import hmac
import secrets as pysecrets

# --- scrypt 기본 파라미터 (신규 해시 발급용) ---
# n=2^14, r=8 → 필요 메모리 128*n*r = 16MiB. 로그인 1회당 비용이라 수용 가능하다.
_SCRYPT_N = 1 << 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 32
_SALT_BYTES = 16
# OpenSSL 기본 maxmem(약 32MiB)에 걸리지 않도록 명시한다. 파라미터를 올릴 때 여기도 올린다.
_MAXMEM = 64 * 1024 * 1024

_ALGO = "scrypt"

# --- 정책 상수 ---
MIN_LENGTH = 8
MAX_LENGTH = 128  # 과도한 입력으로 scrypt 비용을 끌어올리는 것을 막는다(DoS 완충).


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _derive(plain: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        plain.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=_DKLEN,
        maxmem=_MAXMEM,
    )


def hash_password(plain: str) -> str:
    """평문 비밀번호를 저장 문자열로 변환한다.

    호출 전에 :func:`validate_new_password` 로 정책을 통과시켜야 한다. 여기서는
    빈 값만 거부한다(정책 판정과 해싱 책임을 섞지 않는다).
    """
    if not isinstance(plain, str) or plain == "":
        raise ValueError("빈 비밀번호는 해싱할 수 없습니다.")
    salt = pysecrets.token_bytes(_SALT_BYTES)
    digest = _derive(plain, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    return "$".join(
        [_ALGO, str(_SCRYPT_N), str(_SCRYPT_R), str(_SCRYPT_P), _b64e(salt), _b64e(digest)]
    )


def verify_password(plain: str, stored: str) -> bool:
    """평문이 저장된 해시와 일치하는가.

    비교는 ``hmac.compare_digest`` 로 상수시간이며, 저장값이 비었거나 형식이 깨졌거나
    알고리즘을 모르면 예외 대신 **False** 를 반환한다 — 손상된 자격증명 한 건이 로그인
    화면 전체를 500 으로 만들지 않게 하되, 통과시키지도 않는다(fail-closed).
    """
    if not plain or not isinstance(plain, str):
        return False
    if not stored or not isinstance(stored, str):
        return False
    parts = stored.split("$")
    if len(parts) != 6:
        return False
    algo, n_s, r_s, p_s, salt_s, hash_s = parts
    if algo != _ALGO:
        return False
    try:
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = _b64d(salt_s)
        expected = _b64d(hash_s)
    except (ValueError, TypeError, base64.binascii.Error):
        return False
    # 저장된 파라미터가 비정상적으로 크면 계산을 시도하지 않는다(조작된 해시로 메모리를
    # 고갈시키는 경로 차단). 정상 범위는 현재 기본값 이하다.
    if n <= 0 or r <= 0 or p <= 0 or 128 * n * r > _MAXMEM:
        return False
    try:
        actual = _derive(plain, salt, n, r, p)
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str) -> bool:
    """저장된 해시가 현재 기본 파라미터보다 약한가(재해싱 권장 여부).

    비번 검증 성공 직후 호출해 조용히 승급할 때 쓴다. 형식이 깨진 값도 True 로 본다.
    """
    if not stored or not isinstance(stored, str):
        return True
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != _ALGO:
        return True
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
    except (ValueError, TypeError):
        return True
    return (n, r, p) != (_SCRYPT_N, _SCRYPT_R, _SCRYPT_P)


def validate_new_password(plain: str, emp_no: str = "") -> str | None:
    """새 비밀번호 정책 검사. 통과하면 None, 아니면 사용자에게 보여줄 오류 메시지.

    사번과 같은 값을 막는 것이 핵심이다 — 초기 비밀번호가 사번이므로, 이 검사가 없으면
    "변경 강제"가 같은 값 재입력으로 무력화된다. 비교는 로그인 조회와 같은 규칙
    (trim + 대소문자 무시)을 쓴다.
    """
    if plain is None or not isinstance(plain, str) or plain.strip() == "":
        return "새 비밀번호를 입력하세요."
    # 앞뒤 공백은 사용자가 의도하지 않은 입력 사고가 대부분이라 거부한다(조용히 trim 하면
    # 본인이 친 값과 저장된 값이 달라져 다음 로그인에 실패한다).
    if plain != plain.strip():
        return "비밀번호 앞뒤에 공백을 쓸 수 없습니다."
    if len(plain) < MIN_LENGTH:
        return f"비밀번호는 최소 {MIN_LENGTH}자 이상이어야 합니다."
    if len(plain) > MAX_LENGTH:
        return f"비밀번호는 최대 {MAX_LENGTH}자까지 가능합니다."
    if emp_no and plain.strip().casefold() == str(emp_no).strip().casefold():
        return "사번과 동일한 비밀번호는 사용할 수 없습니다."
    return None


def matches_employee_number(plain: str, emp_no: str) -> bool:
    """입력값이 초기 비밀번호(= 사번)인가.

    ``password_hash IS NULL`` 인 미설정 계정의 로그인 판정에 쓴다. 사번 조회와 같은
    규칙(trim + 대소문자 무시)을 쓰되, 비교 자체는 상수시간으로 한다.
    """
    if not plain or not isinstance(plain, str):
        return False
    if not emp_no:
        return False
    return hmac.compare_digest(
        plain.strip().casefold().encode("utf-8"),
        str(emp_no).strip().casefold().encode("utf-8"),
    )
