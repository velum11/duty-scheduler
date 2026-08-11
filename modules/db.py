"""데이터 접근 계층 (sample/Supabase facade).

데이터 모드는 설정에서 명시적으로 선택하며, Supabase 오류를 sample 모드로 숨기지 않는다.
화면/로직 코드는 이 모듈의 자연키 기반 함수만 호출한다.

저장 계층(CSV/Supabase)은 docs/database.md 대로 id 기반(department_id / team_id /
user_id)이다. 화면은 자연키(dept_code / team_code / emp_no / duty_date)를 쓰므로,
이 파사드에서 기준정보를 조인해 자연키 컬럼을 덧붙여 반환한다. 원본(캐시된)
DataFrame 을 훼손하지 않도록 항상 copy 후 컬럼을 추가한다.
"""
import hashlib
import logging
from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st

from modules import config, photo_storage, sample_data, supabase_repository, validators

# 감사/진단 로거. **비밀 금지**: 서명 URL·service key·개인정보를 남기지 않는다. 사진
# 관련 로그는 보고서 id 와 스토리지 객체 경로(near-miss/{id}/{uuid}.jpg)만 기록한다.
_LOG = logging.getLogger("duty.db")

DATA_SOURCE_ERRORS = (
    config.DataSourceConfigurationError,
    supabase_repository.SupabaseDataError,
)

# 참조 건수 조회가 '알 수 없음'으로 실패했을 때 결과 dict 에 추가하는 sentinel 키.
# 삭제 화면 controller 는 ``sum(refs.values()) > 0`` 으로 물리삭제/미사용을 가르므로,
# 이 sentinel(값 1)이 있으면 합이 양수가 되어 물리 삭제 대신 미사용 처리(fail-closed)로
# 라우팅된다. 실제 참조 키(users/schedules/…)는 그대로 유지해 기존 표시·테스트를 보존한다.
REFERENCE_CHECK_FAILED = "_reference_check_failed"

# 참조 건수 경로 전용 '테이블 미생성' 고신뢰 표식.
# readiness probe 의 ``_MISSING_COLUMN_MARKERS`` 는 generic 문구("does not exist",
# "could not find")·컬럼 단위 코드(42703/PGRST204)까지 포함해, 네트워크/DNS/프록시
# 오류 문구("temporary failure: host does not exist" 등)에도 매칭되어 fail-OPEN 을
# 유발한다. 삭제 안전 경로에서는 그 위험을 없애기 위해, 테이블 단위 undefined 신호
# (PostgreSQL 42P01 / PostgREST PGRST205)만 신뢰하고 나머지는 전부 일시 실패로 본다.
_MISSING_TABLE_CODES = ("42p01", "pgrst205")


def _is_missing_table_error(exc: Exception) -> bool:
    """예외가 '테이블 미생성(마이그레이션 미적용)' **고신뢰** 신호인지 판정한다.

    참조 건수 경로는 물리 삭제/미사용을 가르는 삭제 안전 임계 경로다. 따라서 오직
    테이블 단위 undefined 코드(PostgreSQL ``42P01`` / PostgREST ``PGRST205``) 또는
    PostgREST 스키마 캐시의 테이블 미발견 문구("Could not find the table '…' in the
    schema cache")만 참조 0(물리 삭제 허용)으로 인정한다. bare "does not exist" 같은
    generic 부분문자열은 네트워크 오류에도 등장하므로 신뢰하지 않는다 → 모호하면 일시
    실패로 간주(fail-closed → 미사용 처리). code/message/details/hint 구조 필드가 있으면
    함께 검사한다(문구가 중첩 원인에 숨어도 탐지)."""
    parts = [repr(exc)]
    for attr in ("code", "message", "details", "hint"):
        val = getattr(exc, attr, None)
        if val:
            parts.append(str(val))
    text = " ".join(parts).lower()
    if any(code in text for code in _MISSING_TABLE_CODES):
        return True
    # 테이블(table) 단어가 명시된 스키마 캐시 미발견 문구만 인정(컬럼/generic 제외).
    return "could not find the table" in text and "schema cache" in text

# 저장 부분성공 원장 계약(프레임워크 비의존). 화면 controller 는 이 결과를
# ``views.master.lifecycle.PersistResult(page_id=..., **result.to_persist_kwargs())``
# 로 매핑한다. 기존 save_* 는 None 을 반환하는 계약을 유지하고, 부분성공이 필요한
# 화면만 아래 ``save_*_report`` 를 호출한다(추가형).
BatchWriteResult = supabase_repository.BatchWriteResult

# migration readiness 3-state(READY/NOT_READY/PROBE_ERROR) 문자열 상수.
READINESS_READY = supabase_repository.READINESS_READY
READINESS_NOT_READY = supabase_repository.READINESS_NOT_READY
READINESS_PROBE_ERROR = supabase_repository.READINESS_PROBE_ERROR

# 화면이 사용하는 사용자 자연키 컬럼 (id/외래키는 파사드 내부에서만 사용).
# display_order: 부서그룹 안에서의 직원 표시순서 (migration 003, NULL=미지정).
USER_COLUMNS = [
    "emp_no", "name", "dept_code", "team_code", "position", "role", "is_active",
    "display_order", "hire_date", "resign_date",
]

# 화면이 사용하는 부서 컬럼 (id 는 파사드 내부 매핑에만 사용).
DEPT_COLUMNS = ["dept_code", "dept_name", "sort_order", "is_active"]

# 화면이 사용하는 조/팀 컬럼 (id/department_id 는 파사드 내부 매핑에만 사용).
TEAM_COLUMNS = ["dept_code", "team_code", "team_name", "sort_order", "is_active"]

# 조직 관리 화면 전용 확장 계약 (migration 004: 그룹 → 부서 → 운영단위, group_id/FK).
# 기존 DEPT_COLUMNS/TEAM_COLUMNS 소비 화면(근무표·편성 등)은 그대로 두고,
# 조직 관리 화면만 이 확장 컬럼을 사용한다. 그룹은 organization_groups 1급 테이블이며
# 부서는 group_code(내부적으로 group_id FK)로 그룹에 귀속된다. 조는 dept_code(내부적으로
# department_id FK)로 부서에 귀속된다. 003 잔재(department_group/group_sort_order)는 폐기.
ORG_GROUP_COLUMNS = ["group_code", "group_name", "sort_order", "description", "is_active"]
# major_category/minor_category: 사람이 직접 입력하는 조직 계층 2단 (migration 009).
# 그룹 시트 폐지(2026-08-07 사용자 결정)로 계층 표현의 주역이 group_code 에서 이 둘로
# 넘어왔다. group_code 는 계약에 남겨두되 화면에서 편집하지 않는다 — 기존 값 보존용.
ORG_DEPT_COLUMNS = [
    "dept_code", "dept_name", "group_code", "major_category", "minor_category",
    "description", "sort_order", "is_active",
]
ORG_TEAM_COLUMNS = [
    "dept_code", "team_code", "team_name", "unit_type", "description", "sort_order", "is_active",
]

# 운영단위 유형 내부값 ↔ 화면 표시 (내부값만 저장 — CLAUDE.md §8).
UNIT_TYPES = ("SHIFT", "GENERAL")
UNIT_TYPE_LABELS = {"SHIFT": "교대", "GENERAL": "일반"}

# 화면이 사용하는 근무형태 컬럼 (id 는 파사드 내부 매핑에만 사용).
WORK_TYPE_COLUMNS = [
    "code", "name", "category", "short_label", "start_time", "end_time",
    "color", "is_work", "affects_allowance", "description", "sort_order", "is_active",
]

# 화면이 사용하는 근무표 자연키 컬럼 (id/user_id/work_date 는 파사드 내부에서만 사용).
SCHEDULE_COLUMNS = ["emp_no", "duty_date", "work_type_code", "note"]

# 화면이 사용하는 근무조 기준정보 컬럼 (id/department_id 는 파사드 내부 매핑에만 사용).
SHIFT_GROUP_COLUMNS = ["dept_code", "shift_code", "shift_name", "sort_order", "is_active"]

# 화면이 사용하는 직원별 월 편성 컬럼 (docs/database.md §5.1).
# schedule_month 는 해당 월 1일 ISO 문자열('YYYY-MM-01')로 정규화한다.
SCHEDULE_ASSIGNMENT_COLUMNS = [
    "emp_no", "schedule_month", "dept_code", "team_code", "shift_group_code",
]

# 편성 정보가 붙은 일별 근무 계약 (get_month_roster 반환값의 근무 프레임).
SCHEDULE_ASSIGNED_COLUMNS = SCHEDULE_COLUMNS + [
    "schedule_month", "dept_code", "team_code", "shift_group_code",
]

_BOOLEAN_COLUMNS = {"is_active", "is_work", "affects_allowance"}
_INTEGER_COLUMNS = {"sort_order"}

# 로컬 샘플 모드에서 편집 결과를 담아 세션 동안 유지하는 스토어 키.
_USERS_STORE = "store_users"
_DEPTS_STORE = "store_departments"
_TEAMS_STORE = "store_teams"
_WORK_TYPES_STORE = "store_work_types"
_SCHEDULES_STORE = "store_schedules"
_SHIFT_GROUPS_STORE = "store_shift_groups"
_ASSIGNMENTS_STORE = "store_schedule_assignments"
# 조직 그룹 전용 샘플 스토어. 그룹은 기존 기준정보에 대응 테이블이 없어 독립 스토어를
# 쓴다. 반면 조직 화면의 부서·조 데이터는 **기본 부서·조와 동일한 단일 스토어**
# (_DEPTS_STORE/_TEAMS_STORE)를 확장 컬럼과 함께 공유한다 — 저장/물리삭제/soft삭제/조회와
# 사용자·근무 화면 읽기가 같은 backing store 를 보게 하기 위함이다(store 이원화 금지).
# supabase 모드는 실제 테이블(organization_groups/departments.group_id/teams.department_id)을
# 쓰므로 이 스토어를 사용하지 않는다 — 모드별 경로를 명확히 분리한다.
_ORG_GROUPS_STORE = "store_org_groups"
# 아차사고(near-miss) 샘플 backing store (migration 006). supabase 모드는 실제
# near_miss_reports 테이블을 쓰므로 이 스토어를 사용하지 않는다.
_NEAR_MISS_STORE = "store_near_miss_reports"
# 아차사고 사진 sample backing store (요구사항 §4 세션 인메모리 계약). 저장 경로 →
# 정규화된 JPEG bytes 의 dict. supabase 모드는 비공개 Storage 버킷을 쓰므로 이
# 스토어를 사용하지 않는다(모드별 경로 분리, sample/live 동일 API·거동 parity).
_NEAR_MISS_PHOTO_STORE = "store_near_miss_photos"


def datasource() -> str:
    """현재 데이터 소스 이름. 'supabase' 또는 'sample'."""
    return config.data_mode()


def is_sample_mode() -> bool:
    return datasource() == "sample"


# --- Supabase 읽기 캐시 (supabase 모드 전용) ---------------------------------
# 문제: sample_data 와 달리 supabase 읽기에는 캐시가 없어 매 Streamlit rerun 마다
# db.get_* 가 네트워크를 다시 친다. 아래 _fetch_* 는 지연 무거운 원격 조회만
# ``st.cache_data`` 로 짧게(30s) 캐시하는 staleness 안전망이다.
#
# 계약 유지:
#  - sample 모드는 이 캐시를 절대 쓰지 않는다. 각 파사드가 is_sample_mode() 로
#    세션 편집 스토어를 먼저 반환하므로 로컬 편집은 즉시 반영된다(edit-first).
#  - ``st.cache_data`` 는 함수가 성공적으로 끝났을 때만 결과를 저장한다. 예외는
#    캐시하지 않으므로 Supabase 오류가 빈/성공 결과로 위장되지 않는다(모듈 docstring
#    의 오류 은폐 금지 계약 유지).
#  - 반환값은 호출마다 복사본이므로(cache_data 계약) 파사드의 후처리(필터·컬럼
#    추가)가 원본 캐시를 훼손하지 않는다.
#  - 쓰기 후에는 반드시 아래 _invalidate_* 로 관련 캐시를 비워 편집 결과가 다음
#    렌더에 즉시 보이게 한다(누락 시 stale 표시 — 이 캐시의 최대 위험).
_READ_TTL = 30


@st.cache_data(ttl=_READ_TTL, show_spinner=False)
def _fetch_departments() -> pd.DataFrame:
    return supabase_repository.get_departments()


@st.cache_data(ttl=_READ_TTL, show_spinner=False)
def _fetch_teams() -> pd.DataFrame:
    return supabase_repository.get_teams()


@st.cache_data(ttl=_READ_TTL, show_spinner=False)
def _fetch_users() -> pd.DataFrame:
    return supabase_repository.get_users()


@st.cache_data(ttl=_READ_TTL, show_spinner=False)
def _fetch_work_types() -> pd.DataFrame:
    return supabase_repository.get_work_types()


@st.cache_data(ttl=_READ_TTL, show_spinner=False)
def _fetch_shift_groups() -> pd.DataFrame:
    return supabase_repository.get_shift_groups()


@st.cache_data(ttl=_READ_TTL, show_spinner=False)
def _fetch_organization_groups() -> pd.DataFrame:
    return supabase_repository.get_organization_groups()


@st.cache_data(ttl=_READ_TTL, show_spinner=False)
def _fetch_departments_org() -> pd.DataFrame:
    return supabase_repository.get_departments_org()


@st.cache_data(ttl=_READ_TTL, show_spinner=False)
def _fetch_teams_org() -> pd.DataFrame:
    return supabase_repository.get_teams_org()


@st.cache_data(ttl=_READ_TTL, show_spinner=False)
def _fetch_schedules() -> pd.DataFrame:
    return supabase_repository.get_schedules()


@st.cache_data(ttl=_READ_TTL, show_spinner=False)
def _fetch_user_schedules(emp_no: str) -> pd.DataFrame:
    return supabase_repository.get_user_schedules(emp_no)


@st.cache_data(ttl=_READ_TTL, show_spinner=False)
def _fetch_month_schedules(emp_nos: tuple, year: int, month: int) -> pd.DataFrame:
    return supabase_repository.get_month_schedules(list(emp_nos), year, month)


@st.cache_data(ttl=_READ_TTL, show_spinner=False)
def _fetch_day_schedules(iso: str) -> pd.DataFrame:
    return supabase_repository._schedule_rows(
        lambda query: query.eq("work_date", iso).order("user_id")
    )


@st.cache_data(ttl=_READ_TTL, show_spinner=False)
def _fetch_month_assignments(year: int, month: int, emp_nos: tuple) -> pd.DataFrame:
    return supabase_repository.get_month_assignments(year, month, list(emp_nos) or None)


@st.cache_data(ttl=_READ_TTL, show_spinner=False)
def _fetch_near_miss(include_archived: bool) -> pd.DataFrame:
    """활성(또는 전체) 아차사고 보고서를 원격에서 1회 조회해 짧게 캐시한다.

    나머지 필터(상태/부서/원인/등급/기간/보고자)는 파사드가 프레임에서 적용한다.
    쓰기 후에는 _invalidate_near_miss() 로 비운다."""
    rows = supabase_repository.get_near_miss_reports({"include_archived": include_archived})
    return _near_miss_frame(rows)


# --- 쓰기 후 캐시 무효화 -----------------------------------------------------
# 원칙: 미무효화 → stale 표시가 가장 큰 위험이므로, 변경 테이블이 파생시키는
# 조회·매핑 캐시를 넉넉히(over-clear) 비운다. 과다 무효화는 재조회 1회 비용뿐이고
# 정확성을 해치지 않는다. supabase_repository 의 id↔code 매핑 캐시도 같은 무효화에
# 묶어 신선도를 일치시킨다(조직 2단계 저장에서 부서 저장 후 조 저장이 새 부서를
# 보게 하는 교차단계 정합성 포함).
def _invalidate_departments() -> None:
    _fetch_departments.clear()
    _fetch_departments_org.clear()
    _fetch_teams.clear()            # 조 조회의 dept_code 해석(_department_maps)
    _fetch_teams_org.clear()
    _fetch_users.clear()            # 사용자 조회의 dept_code 해석
    _fetch_shift_groups.clear()     # 근무조 조회의 dept_code 해석
    _fetch_month_assignments.clear()  # 편성 조회의 dept_code 해석
    supabase_repository._department_maps.clear()
    supabase_repository._team_maps.clear()


def _invalidate_teams() -> None:
    _fetch_teams.clear()
    _fetch_teams_org.clear()
    _fetch_users.clear()            # 사용자 조회의 team_code 해석
    _fetch_month_assignments.clear()  # 편성 조회의 team_code 해석
    supabase_repository._team_maps.clear()


def _invalidate_groups() -> None:
    _fetch_organization_groups.clear()
    _fetch_departments_org.clear()  # 부서 뷰의 group_code 파생
    supabase_repository._group_maps.clear()


def _invalidate_users() -> None:
    _fetch_users.clear()
    _fetch_schedules.clear()        # 근무 조회의 emp_no 해석(_user_maps)
    _fetch_user_schedules.clear()
    _fetch_month_schedules.clear()
    _fetch_day_schedules.clear()
    _fetch_month_assignments.clear()  # 편성 조회의 emp_no 해석
    supabase_repository._user_maps.clear()


def _invalidate_work_types() -> None:
    _fetch_work_types.clear()


def _invalidate_shift_groups() -> None:
    _fetch_shift_groups.clear()


def _invalidate_schedules() -> None:
    _fetch_schedules.clear()
    _fetch_user_schedules.clear()
    _fetch_month_schedules.clear()
    _fetch_day_schedules.clear()


def _invalidate_assignments() -> None:
    _fetch_month_assignments.clear()


def _invalidate_near_miss() -> None:
    _fetch_near_miss.clear()


def _invalidate_all() -> None:
    """모든 supabase 읽기·매핑 캐시를 비운다(클라이언트 재연결·스키마 재확인 등
    데이터 소스 자체가 바뀔 수 있는 경로에서 호출한다)."""
    _invalidate_departments()
    _invalidate_teams()
    _invalidate_groups()
    _invalidate_users()
    _invalidate_work_types()
    _invalidate_shift_groups()
    _invalidate_schedules()
    _invalidate_assignments()
    _invalidate_near_miss()


def _typed_empty_frame(columns) -> pd.DataFrame:
    """빈 기준정보도 화면 필터가 가능한 컬럼/dtype 계약으로 반환한다."""
    return pd.DataFrame({
        column: pd.Series(
            dtype="bool" if column in _BOOLEAN_COLUMNS
            else "int64" if column in _INTEGER_COLUMNS
            else "object"
        )
        for column in columns
    })


def _empty_contract(df: pd.DataFrame, columns) -> pd.DataFrame:
    return _typed_empty_frame(columns) if df.empty else df


def frame_signature(df: pd.DataFrame, columns) -> str:
    """화면 편집 스냅샷이 원본 DB 데이터와 같은지 비교할 안정적인 서명."""
    required = list(columns)
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"DataFrame 필수 컬럼이 없습니다: {', '.join(missing)}")
    payload = df[required].reset_index(drop=True).to_json(
        orient="split", date_format="iso", force_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _changed_records(
    current: pd.DataFrame,
    desired: pd.DataFrame,
    key_columns,
    columns,
) -> list[dict]:
    """자연키 기준으로 신규 또는 실제 값이 바뀐 행만 반환한다."""
    keys = list(key_columns)
    compare_columns = list(columns)

    def normalized(value):
        if value is None or pd.isna(value):
            return None
        if isinstance(value, bool):
            return bool(value)
        if isinstance(value, int):
            return int(value)
        return str(value).strip()

    def key_of(record):
        return tuple(normalized(record[column]) for column in keys)

    current_by_key = {
        key_of(row): tuple(normalized(row[column]) for column in compare_columns)
        for _, row in current.iterrows()
    }
    changed = []
    for _, row in desired.iterrows():
        record = row[compare_columns].to_dict()
        values = tuple(normalized(record[column]) for column in compare_columns)
        if current_by_key.get(key_of(record)) != values:
            changed.append(record)
    return changed


def _natural_keys(records: list[dict], key_cols) -> list:
    """부분성공 원장용 자연키 목록(단일 컬럼=str, 복합키=tuple)."""
    cols = list(key_cols)
    keys = []
    for record in records:
        values = tuple(str(record.get(col, "")).strip() for col in cols)
        keys.append(values[0] if len(values) == 1 else values)
    return keys


def _sample_report(changed: list[dict], key_cols) -> BatchWriteResult:
    """sample 모드 저장 결과(항상 전체 성공). 변경 행의 자연키를 saved 로 보고한다."""
    return BatchWriteResult(saved_keys=_natural_keys(changed, key_cols))


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
        return _typed_empty_frame(DEPT_COLUMNS)
    return df[DEPT_COLUMNS].reset_index(drop=True).copy()


def _dept_store() -> pd.DataFrame:
    """샘플 모드 부서 단일 backing store. 기본 화면과 조직 화면이 함께 쓴다.

    처음 접근 시 기본 부서(DEPT_COLUMNS)로 seed 한다. 조직 화면 저장이 group_code/
    description 확장 컬럼을 얹으면 그대로 보존한다 — 저장/물리삭제/조회/사용자 화면
    읽기가 모두 이 한 스토어를 본다(store 이원화 금지).
    """
    if _DEPTS_STORE not in st.session_state:
        st.session_state[_DEPTS_STORE] = _base_departments()
    return st.session_state[_DEPTS_STORE]


def _team_store() -> pd.DataFrame:
    """샘플 모드 조 단일 backing store. 기본 화면과 조직 화면이 함께 쓴다."""
    if _TEAMS_STORE not in st.session_state:
        st.session_state[_TEAMS_STORE] = _base_teams()
    return st.session_state[_TEAMS_STORE]


def get_departments(is_active: bool | None = None) -> pd.DataFrame:
    """부서 목록(DEPT_COLUMNS).

    로컬 샘플 모드에서는 세션 편집 결과(save_departments/save_org_departments)를 우선
    반환하므로, 조직 관리 화면에서 저장한 내용이 다른 화면에도 그대로 반영된다.
    조직 화면이 확장 컬럼(group_code 등)을 저장해도 여기서는 기본 계약(DEPT_COLUMNS)만
    투영한다.
    """
    if is_sample_mode():
        store = _dept_store()
        return _empty_contract(store[DEPT_COLUMNS].reset_index(drop=True).copy(), DEPT_COLUMNS)
    df = _fetch_departments()
    if is_active is not None:
        df = df[df["is_active"].astype(bool) == bool(is_active)]
    return _empty_contract(df.reset_index(drop=True), DEPT_COLUMNS)


def save_departments(df: pd.DataFrame) -> None:
    """편집된 부서 목록을 저장한다.

    로컬 샘플 모드에서는 세션 상태에 보관해 현재 세션 동안 유지한다(CSV 는 건드리지
    않는다). Phase 5(Supabase)에서는 여기서 upsert / is_active 소프트삭제로 교체한다.
    """
    keep = [c for c in DEPT_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_DEPTS_STORE] = normalized
        return
    changed = _changed_records(
        _fetch_departments(), normalized, ["dept_code"], DEPT_COLUMNS
    )
    # finally 무효화: 배치가 중간에 커밋된 뒤 예외가 나도 방금 저장된 행이 stale
    # 캐시에 가려지지 않게 한다(예외는 그대로 전파 — 오류를 숨기지 않는다).
    try:
        supabase_repository.upsert_departments(changed)
    finally:
        _invalidate_departments()


def save_departments_report(df: pd.DataFrame) -> BatchWriteResult:
    """save_departments 의 부분성공 원장 반환 변형. 기존 save_departments 는 그대로 둔다."""
    keep = [c for c in DEPT_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_DEPTS_STORE] = normalized
        return _sample_report(normalized.to_dict("records"), ["dept_code"])
    changed = _changed_records(
        _fetch_departments(), normalized, ["dept_code"], DEPT_COLUMNS
    )
    if not changed:
        return BatchWriteResult()
    try:
        return supabase_repository.upsert_departments_reported(changed)
    finally:
        _invalidate_departments()


def _base_teams() -> pd.DataFrame:
    """샘플 CSV(id 기반)를 화면용 조/팀 컬럼(TEAM_COLUMNS)으로 변환한 원본."""
    df = sample_data.teams()
    if df.empty:
        return _typed_empty_frame(TEAM_COLUMNS)
    df = df.copy()
    df["dept_code"] = df["department_id"].astype(str).map(_dept_code_by_id()).fillna("")
    return df[TEAM_COLUMNS].reset_index(drop=True).copy()


def get_teams(dept_code: str | None = None, is_active: bool | None = None) -> pd.DataFrame:
    """조/팀 목록(TEAM_COLUMNS).

    로컬 샘플 모드에서는 세션 편집 결과(save_teams)를 우선 반환하므로,
    조 관리 화면에서 저장한 내용이 다른 화면에도 그대로 반영된다.
    Phase 5(Supabase)에서는 이 분기를 실제 조회로 교체한다.
    """
    if is_sample_mode():
        store = _team_store()
        return _empty_contract(store[TEAM_COLUMNS].reset_index(drop=True).copy(), TEAM_COLUMNS)
    df = _fetch_teams()
    if dept_code is not None:
        df = df[df["dept_code"].astype(str) == str(dept_code).strip()]
    if is_active is not None:
        df = df[df["is_active"].astype(bool) == bool(is_active)]
    return _empty_contract(df.reset_index(drop=True), TEAM_COLUMNS)


def save_teams(df: pd.DataFrame) -> None:
    """편집된 조/팀 목록을 저장한다.

    로컬 샘플 모드에서는 세션 상태에 보관해 현재 세션 동안 유지한다(CSV 는 건드리지
    않는다). Phase 5(Supabase)에서는 여기서 upsert / is_active 소프트삭제로 교체한다.
    """
    keep = [c for c in TEAM_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_TEAMS_STORE] = normalized
        return
    changed = _changed_records(
        _fetch_teams(),
        normalized,
        ["dept_code", "team_code"],
        TEAM_COLUMNS,
    )
    try:
        supabase_repository.upsert_teams(changed)
    finally:
        _invalidate_teams()


def save_teams_report(df: pd.DataFrame) -> BatchWriteResult:
    """save_teams 의 부분성공 원장 반환 변형. 기존 save_teams 는 그대로 둔다."""
    keep = [c for c in TEAM_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_TEAMS_STORE] = normalized
        return _sample_report(normalized.to_dict("records"), ["dept_code", "team_code"])
    changed = _changed_records(
        _fetch_teams(), normalized, ["dept_code", "team_code"], TEAM_COLUMNS
    )
    if not changed:
        return BatchWriteResult()
    try:
        return supabase_repository.upsert_teams_reported(changed)
    finally:
        _invalidate_teams()


# --- 조직 관리 (그룹·부서·운영단위, migration 004: group_id/FK 기반) ---
def org_schema_ready() -> bool:
    """004 조직 그룹 스키마(organization_groups + departments.group_id) 사용 가능 여부.

    sample 모드는 세션 스토어에 기본값을 채워 항상 사용 가능하다. supabase 모드는
    라이브 스키마를 1회 probe 한다 — 미적용이면 조회는 안전한 기본값으로 폴백하고
    저장은 repository 계층에서 명확한 오류로 차단된다.
    """
    if is_sample_mode():
        return True
    return supabase_repository.org_extensions_ready()


def org_schema_readiness() -> str:
    """004 조직 그룹 스키마 준비 상태를 3-state 로 반환한다.

    반환: ``READINESS_READY`` / ``READINESS_NOT_READY`` / ``READINESS_PROBE_ERROR``.
    sample 모드는 항상 READY. supabase 모드는 라이브 스키마를 read-only 로 확인해
    미적용(NOT_READY)과 확인 실패(PROBE_ERROR)를 구분한다 — 화면 배너/재확인 UX 용.
    실제 WRITE 차단은 ``org_schema_ready()`` bool 게이트가 담당한다(오분류가 쓰기를
    열지 않음). controller 는 이 값을 ``ReadinessState`` 로 승격한다."""
    if is_sample_mode():
        return READINESS_READY
    return supabase_repository.org_extensions_probe()


def reset_org_schema_cache() -> None:
    """org readiness 캐시를 비운다(다음 확인에서 재프로브).

    실행 중 migration 004 가 적용된 뒤 프로세스 재시작 없이 반영하려면(예: 화면의
    '스키마 재확인' 동작) 이 경로를 쓴다. sample 모드는 캐시가 없어 no-op."""
    if not is_sample_mode():
        supabase_repository.reset_org_readiness()
        # 009(부서 분류·재직기간) probe 도 함께 재확인한다 — 앱이 009 적용 전에 기동한
        # 경우 이 경로 없이는 프로세스 재시작 전까지 폴백 분기에 갇힌다.
        supabase_repository.reset_org_category_readiness()
        # readiness 가 바뀌면 조직 조회의 분기(폴백↔완전 조직 뷰)가 달라지므로 관련
        # 읽기·매핑 캐시를 함께 비워 다음 렌더가 새 분기로 재조회하게 한다.
        _invalidate_all()


def org_team_defaults(df: pd.DataFrame) -> pd.DataFrame:
    """unit_type 이 없거나 비정상인 운영단위 프레임을 SHIFT 기본값으로 정규화한다."""
    frame = df.copy()
    if "unit_type" not in frame:
        frame["unit_type"] = "SHIFT"
    unit = frame["unit_type"].fillna("").astype(str).str.strip().str.upper()
    frame["unit_type"] = unit.where(unit.isin(UNIT_TYPES), "SHIFT")
    return frame


# --- 샘플 모드 조직 계층 seed (supabase 와 인터페이스 대칭, 실제 테이블 미사용) ---
def _sample_org_groups() -> pd.DataFrame:
    """샘플 그룹 seed — 부서 1개당 그룹 1개(group_code=dept_code)로 초기화한다.

    supabase 모드의 organization_groups(그룹코드/그룹명/순서/비고/사용유무)와 같은
    계약 컬럼(ORG_GROUP_COLUMNS)을 반환한다. 로컬 편집·저장은 세션 스토어에서만
    유지되며 실제 DB 를 건드리지 않는다.
    """
    depts = _base_departments()
    if depts.empty:
        return _typed_empty_frame(ORG_GROUP_COLUMNS)
    frame = depts.sort_values(["sort_order", "dept_code"]).reset_index(drop=True)
    return pd.DataFrame({
        "group_code": frame["dept_code"].astype(str),
        "group_name": frame["dept_name"].astype(str),
        "sort_order": range(1, len(frame) + 1),
        "description": "",
        "is_active": True,
    })[ORG_GROUP_COLUMNS].reset_index(drop=True)


def _org_dept_view(store: pd.DataFrame) -> pd.DataFrame:
    """공유 부서 스토어(_DEPTS_STORE)를 조직 화면 계약(ORG_DEPT_COLUMNS)으로 투영한다.

    기본 부서 스토어는 group_code/description 를 안 가질 수 있으므로(레거시 basic seed),
    없으면 안전한 기본값으로 보강한다: group_code 미배정은 '부서 1개=그룹 1개'(=dept_code),
    비고는 빈 문자열. 조직 화면이 저장한 확장 컬럼이 있으면 그대로 보존한다.
    """
    frame = store.copy()
    if frame.empty:
        return _typed_empty_frame(ORG_DEPT_COLUMNS)
    if "description" not in frame.columns:
        frame["description"] = ""
    frame["description"] = frame["description"].fillna("").astype(str)
    if "group_code" not in frame.columns:
        frame["group_code"] = ""
    gc = frame["group_code"].fillna("").astype(str).str.strip()
    blank = gc == ""
    frame["group_code"] = gc
    frame.loc[blank, "group_code"] = frame.loc[blank, "dept_code"].astype(str)
    # 조직 계층 2단(009). 레거시 스토어에 없으면 빈 문자열 = 미분류로 시작한다.
    for col in ("major_category", "minor_category"):
        if col not in frame.columns:
            frame[col] = ""
        frame[col] = frame[col].fillna("").astype(str)
    return frame[ORG_DEPT_COLUMNS].reset_index(drop=True)


def _org_team_view(store: pd.DataFrame) -> pd.DataFrame:
    """공유 조 스토어(_TEAMS_STORE)를 조직 화면 계약(ORG_TEAM_COLUMNS)으로 투영한다.

    unit_type 이 없으면 SHIFT(교대) 기본값, 비고가 없으면 빈 문자열로 보강한다.
    조직 화면이 저장한 확장 컬럼이 있으면 그대로 보존한다.
    """
    frame = store.copy()
    if frame.empty:
        return _typed_empty_frame(ORG_TEAM_COLUMNS)
    if "description" not in frame.columns:
        frame["description"] = ""
    frame["description"] = frame["description"].fillna("").astype(str)
    frame = org_team_defaults(frame)  # unit_type 없음/비정상 → SHIFT
    return frame[ORG_TEAM_COLUMNS].reset_index(drop=True)


# --- 그룹(organization_groups) ---
def get_org_groups(is_active: bool | None = None) -> pd.DataFrame:
    """조직 그룹 목록(ORG_GROUP_COLUMNS). 그룹은 부서·조 계층의 최상위다."""
    if is_sample_mode():
        if _ORG_GROUPS_STORE not in st.session_state:
            st.session_state[_ORG_GROUPS_STORE] = _sample_org_groups()
        df = st.session_state[_ORG_GROUPS_STORE].copy()
    elif supabase_repository.org_extensions_ready():
        df = _fetch_organization_groups()
    else:
        df = _typed_empty_frame(ORG_GROUP_COLUMNS)  # 조직 스키마 capability 미준비(도입: migration 004) — 조회 전용 빈 그룹
    if is_active is not None and not df.empty:
        df = df[df["is_active"].astype(bool) == bool(is_active)]
    return _empty_contract(df[ORG_GROUP_COLUMNS].reset_index(drop=True), ORG_GROUP_COLUMNS)


def save_org_groups(df: pd.DataFrame) -> None:
    """그룹 편집 결과를 저장한다 (변경 행만 upsert, 저장코드 수정 불가)."""
    keep = [c for c in ORG_GROUP_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_ORG_GROUPS_STORE] = normalized
        return
    changed = _changed_records(
        get_org_groups(), normalized, ["group_code"], ORG_GROUP_COLUMNS
    )
    try:
        supabase_repository.upsert_organization_groups(changed)
    finally:
        _invalidate_groups()


def save_org_groups_report(df: pd.DataFrame) -> BatchWriteResult:
    """save_org_groups 의 부분성공 원장 반환 변형. 조직 스키마 capability(도입: migration 004) 미준비는 전체 failed."""
    keep = [c for c in ORG_GROUP_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_ORG_GROUPS_STORE] = normalized
        return _sample_report(normalized.to_dict("records"), ["group_code"])
    changed = _changed_records(
        get_org_groups(), normalized, ["group_code"], ORG_GROUP_COLUMNS
    )
    if not changed:
        return BatchWriteResult()
    try:
        return supabase_repository.upsert_organization_groups_reported(changed)
    finally:
        _invalidate_groups()


def deactivate_org_group(group_code: str) -> None:
    """그룹을 미사용 처리(soft-delete)한다. 저장된(기존) 그룹 삭제의 기본 경로."""
    code = str(group_code).strip()
    if is_sample_mode():
        if _ORG_GROUPS_STORE in st.session_state:
            store = st.session_state[_ORG_GROUPS_STORE].copy()
            mask = store["group_code"].astype(str).str.strip() == code
            store.loc[mask, "is_active"] = False
            st.session_state[_ORG_GROUPS_STORE] = store.reset_index(drop=True)
        return
    try:
        supabase_repository.deactivate_organization_group(code)
    finally:
        _invalidate_groups()


def delete_org_group(group_code: str) -> None:
    """그룹을 물리 삭제한다(참조 없는 그룹 전용 — 참조 확인은 호출부가 담당).

    참조가 있으면 supabase 는 departments_group_fk(on delete restrict)로 삭제를 거부한다.
    """
    code = str(group_code).strip()
    if is_sample_mode():
        if _ORG_GROUPS_STORE in st.session_state:
            store = st.session_state[_ORG_GROUPS_STORE]
            st.session_state[_ORG_GROUPS_STORE] = (
                store[store["group_code"].astype(str).str.strip() != code].reset_index(drop=True)
            )
        return
    try:
        supabase_repository.delete_organization_group(code)
    finally:
        _invalidate_groups()


def org_group_reference_counts(group_code: str) -> dict:
    """그룹을 참조하는 부서 건수를 반환한다(활성·비활성 모두 포함)."""
    code = str(group_code).strip()
    try:
        depts = get_org_departments()
    except Exception as exc:
        # 미적용 스키마(테이블/컬럼 없음)만 참조 0. 그 외 실패는 fail-closed.
        if _is_missing_table_error(exc):
            return {"departments": 0}
        return {"departments": 0, REFERENCE_CHECK_FAILED: 1}
    if depts.empty or "group_code" not in depts:
        return {"departments": 0}
    return {"departments": int((depts["group_code"].astype(str).str.strip() == code).sum())}


# --- 부서(departments, group_code→group_id FK) ---
def get_org_departments(
    group_code: str | None = None, is_active: bool | None = None
) -> pd.DataFrame:
    """조직 관리 화면용 부서 목록(ORG_DEPT_COLUMNS, 소속 그룹코드 포함).

    group_code 를 넘기면 해당 그룹 소속 부서만(그룹별 부서 조회). supabase 모드는
    group_id FK 를 group_code 로 해석해 반환한다.
    """
    if is_sample_mode():
        df = _org_dept_view(_dept_store())
    elif supabase_repository.org_extensions_ready():
        df = _fetch_departments_org()
    else:
        # 조직 스키마 capability 미준비(도입: migration 004) — 그룹 정보 없이 부서만 표시(조회 전용, 저장은 차단됨)
        df = _fetch_departments().copy()
        df["group_code"] = ""
        df["description"] = ""
        df["major_category"] = ""
        df["minor_category"] = ""
    if group_code is not None and not df.empty:
        df = df[df["group_code"].astype(str).str.strip() == str(group_code).strip()]
    if is_active is not None and not df.empty:
        df = df[df["is_active"].astype(bool) == bool(is_active)]
    return _empty_contract(df[ORG_DEPT_COLUMNS].reset_index(drop=True), ORG_DEPT_COLUMNS)


def save_org_departments(df: pd.DataFrame) -> None:
    """조직 관리 화면의 부서 편집 결과를 저장한다 (변경 행만 upsert).

    부서→그룹 귀속은 group_code(내부 group_id FK)로 저장한다. 저장코드(dept_code)는
    수정 불가이며, 신규 부서만 새 코드로 insert 한다.
    """
    keep = [c for c in ORG_DEPT_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_DEPTS_STORE] = normalized
        return
    changed = _changed_records(
        get_org_departments(), normalized, ["dept_code"], ORG_DEPT_COLUMNS
    )
    try:
        supabase_repository.upsert_departments_org(changed)
    finally:
        _invalidate_departments()


def save_org_departments_report(df: pd.DataFrame) -> BatchWriteResult:
    """save_org_departments 의 부분성공 원장 반환 변형. 기존 함수는 그대로 둔다.

    조직 스키마 capability(도입: migration 004) 미준비 supabase 모드에서는 repository 가 전체
    failed(비재시도) 원장을 반환한다."""
    keep = [c for c in ORG_DEPT_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_DEPTS_STORE] = normalized
        return _sample_report(normalized.to_dict("records"), ["dept_code"])
    changed = _changed_records(
        get_org_departments(), normalized, ["dept_code"], ORG_DEPT_COLUMNS
    )
    if not changed:
        return BatchWriteResult()
    try:
        return supabase_repository.upsert_departments_org_reported(changed)
    finally:
        _invalidate_departments()


# --- 운영단위(teams, dept_code→department_id FK) ---
def get_org_teams(dept_code: str | None = None, is_active: bool | None = None) -> pd.DataFrame:
    """조직 관리 화면용 운영단위 목록(ORG_TEAM_COLUMNS, unit_type·비고 포함).

    dept_code 를 넘기면 해당 부서 소속 조만(부서별 조 조회, department_id FK 필터).
    """
    if is_sample_mode():
        df = _org_team_view(_team_store())
    elif supabase_repository.org_extensions_ready():
        df = _fetch_teams_org()
    else:
        # 조직 스키마 capability 미준비(도입: migration 004) — unit_type/비고 기본값으로 폴백(조회 전용, 저장은 차단됨)
        df = org_team_defaults(_fetch_teams())
        df["description"] = ""
    if dept_code is not None and not df.empty:
        df = df[df["dept_code"].astype(str) == str(dept_code).strip()]
    if is_active is not None and not df.empty:
        df = df[df["is_active"].astype(bool) == bool(is_active)]
    return _empty_contract(df[ORG_TEAM_COLUMNS].reset_index(drop=True), ORG_TEAM_COLUMNS)


def save_org_teams(df: pd.DataFrame) -> None:
    """조직 관리 화면의 운영단위 편집 결과를 저장한다 (변경 행만 upsert)."""
    keep = [c for c in ORG_TEAM_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_TEAMS_STORE] = normalized
        return
    changed = _changed_records(
        get_org_teams(), normalized, ["dept_code", "team_code"], ORG_TEAM_COLUMNS
    )
    try:
        supabase_repository.upsert_teams_org(changed)
    finally:
        _invalidate_teams()


def save_org_teams_report(df: pd.DataFrame) -> BatchWriteResult:
    """save_org_teams 의 부분성공 원장 반환 변형. 기존 함수는 그대로 둔다."""
    keep = [c for c in ORG_TEAM_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_TEAMS_STORE] = normalized
        return _sample_report(normalized.to_dict("records"), ["dept_code", "team_code"])
    changed = _changed_records(
        get_org_teams(), normalized, ["dept_code", "team_code"], ORG_TEAM_COLUMNS
    )
    if not changed:
        return BatchWriteResult()
    try:
        return supabase_repository.upsert_teams_org_reported(changed)
    finally:
        _invalidate_teams()


def save_org_structure_report(
    dept_df: pd.DataFrame, team_df: pd.DataFrame
) -> BatchWriteResult:
    """조직(부서→운영단위) 2단계 저장을 하나의 부분성공 원장으로 합쳐 반환한다.

    부서 저장이 하나도 성공하지 못하면(전체 실패/불명) 운영단위 저장을 시도하지
    않는다 — 없는 부서를 참조하는 운영단위 저장 실패를 부르지 않기 위함이다. 부서가
    (일부라도) 저장되면 운영단위도 저장하고 두 결과를 ``merge`` 한다.

    주의: 이는 진짜 원자성이 아니다(부서 성공·운영단위 실패 = partial 로 드러남).
    완전한 원자성은 서버 transaction/RPC(=migration, **승인 필요**)가 있어야 한다.
    controller 는 반환 원장으로 실패분 draft 를 유지하고 재시도할 수 있다."""
    dept_result = save_org_departments_report(dept_df)
    if not dept_result.saved_keys and (dept_result.failed_keys or dept_result.unknown):
        return dept_result
    return dept_result.merge(save_org_teams_report(team_df))


# --- 부서그룹 기준 사용자 표시순서 (users.display_order, migration 003) ---
def normalize_display_order(value):
    """표시순서 입력 정규화 — 빈 값/NaN 은 None(미지정), 그 외 int. 실패 시 ValueError.

    pandas 가 int+NULL 혼합 컬럼을 float 로 승격시키므로("1.0") float 표기도 수용한다.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "<na>"}:
        return None
    number = float(text)  # 정수/float 표기 외에는 ValueError
    if number != int(number):
        raise ValueError(f"표시순서는 정수여야 합니다: {value!r}")
    return int(number)


def dept_group_map(org_depts: pd.DataFrame | None = None) -> dict:
    """dept_code -> (group_code, group_sort_order) 매핑 (migration 004: group_id 기반).

    org_depts 를 넘기면 그 프레임(예: 저장 후 예상 merged) 기준으로 계산한다 —
    조직 저장 전 '변경 후 그룹 구조' 기준 검증(§그룹 병합 충돌)에 사용한다.
    그룹순서는 organization_groups.sort_order 를 group_code 로 조회해 붙인다.
    """
    frame = get_org_departments() if org_depts is None else org_depts
    group_orders: dict = {}
    # get_org_groups() 의 진짜 저장소 오류(DATA_SOURCE_ERRORS 등)는 get_org_departments()
    # 와 동일하게 호출부로 전파한다(다른 조직 조회와의 오류 처리 일관성 — 조용히 빈
    # 매핑으로 위장하지 않는다). 행 단위 정렬값 결측/형식 이상만 그 행에 한해 0으로 폴백.
    for _, g in get_org_groups().iterrows():
        try:
            order = int(pd.to_numeric(g["sort_order"], errors="coerce"))
        except (TypeError, ValueError):
            order = 0
        group_orders[str(g["group_code"]).strip()] = order
    out: dict = {}
    for _, r in frame.iterrows():
        code = str(r.get("group_code", "") or "").strip()
        out[str(r["dept_code"]).strip()] = (code, group_orders.get(code, 0))
    return out


def display_order_conflicts(users_df: pd.DataFrame, group_of: dict) -> list[str]:
    """부서그룹 기준 활성 사용자 display_order 중복 오류 목록.

    - 검증 대상: 활성(is_active) + 표시순서 지정(display_order not NULL) 사용자만.
      비활성(퇴직) 사용자는 번호를 점유하지 않는다.
    - group_of: dept_code -> (group, group_order) — 저장 후 예상 매핑을 넘기면
      그룹 병합·부서 이동 후 충돌을 사전 차단할 수 있다.
    """
    errors: list[str] = []
    if users_df is None or users_df.empty:
        return errors
    holders: dict[tuple[str, int], list[str]] = {}
    for _, r in users_df.iterrows():
        if not bool(r.get("is_active")):
            continue
        try:
            order = normalize_display_order(r.get("display_order"))
        except (TypeError, ValueError):
            continue  # 형식 오류는 입력 화면 검증이 담당
        if order is None:
            continue
        dept = str(r.get("dept_code") or "").strip()
        group = group_of.get(dept, (dept, 0))[0]
        key = (group, order)
        holders.setdefault(key, []).append(
            f"{str(r.get('emp_no') or '').strip()} {str(r.get('name') or '').strip()}".strip()
        )
    for (group, order), users in sorted(holders.items()):
        if len(users) > 1:
            errors.append(
                f"그룹 '{group}'의 사용자 표시순서 {order}이(가) 중복되었습니다: "
                + ", ".join(users)
            )
    return errors


def plan_display_order_slots(
    visible_emp_nos: list,
    users_df: pd.DataFrame,
    group_of: dict,
) -> list[tuple[str, int]]:
    """화면에 보이는 행 순서를 users.display_order 로 옮길 최소 변경 목록 (순수).

    부서그룹 단위 **슬롯 재배정**이다 — 그룹 안에서 "보이는 행들이 지금 점유한 번호"를
    오름차순 슬롯으로 삼아 새 시각 순서대로 다시 나눠 준다. 그래서 화면에 없는(필터로
    숨은) 사용자의 번호는 절대 바뀌지 않고, 그룹 내 유일성(:func:`display_order_conflicts`
    계약)도 그대로 유지된다.

    규칙:
      - 대상은 ``users_df`` 에 있고 활성인 사번만. 비활성(퇴직)·미등록 사번에는 순서를
        쓰지 않는다(비활성은 번호를 점유하지 않는다는 기존 계약과 정합).
      - 그룹키는 :func:`display_order_conflicts` 와 동일하게 ``group_of[dept_code]`` 이며,
        매핑이 없는 부서는 dept_code 자체를 그룹키로 쓴다.
      - 보이는 행이 슬롯보다 많으면(미지정 NULL 등) **그 그룹 전체 사용자**(숨은·비활성
        포함) 최대 display_order + 10, +20 … 으로 슬롯을 연장한다.
      - 같은 그룹의 보이는 행이 같은 번호를 중복 점유 중이면 중복을 하나로 접고 연장
        슬롯으로 메운다(기존 중복을 그대로 복제하지 않는다).
      - 부서 기준은 화면의 편성 부서가 아니라 **users 마스터의 dept_code** 다 — 번호
        유일성 판정이 마스터 소속 기준이기 때문이다.

    반환: 값이 실제로 달라지는 ``(emp_no, display_order)`` 쌍만 (그룹 등장 순서 → 시각 순서).
    """
    if users_df is None or users_df.empty:
        return []
    info: dict[str, dict] = {}
    group_max: dict[str, int] = {}
    for _, r in users_df.iterrows():
        emp = str(r.get("emp_no") or "").strip()
        if not emp:
            continue
        dept = str(r.get("dept_code") or "").strip()
        group = group_of.get(dept, (dept, 0))[0]
        try:
            order = normalize_display_order(r.get("display_order"))
        except (TypeError, ValueError):
            order = None  # 형식 오류는 기준정보 화면 검증이 담당 — 여기선 미지정 취급
        info[emp] = {"group": group, "order": order, "active": bool(r.get("is_active"))}
        if order is not None:
            group_max[group] = max(group_max.get(group, 0), order)

    members: dict[str, list[str]] = {}
    seen: set[str] = set()
    for raw in visible_emp_nos or []:
        emp = str(raw or "").strip()
        row = info.get(emp)
        if not emp or emp in seen or row is None or not row["active"]:
            continue
        seen.add(emp)
        members.setdefault(row["group"], []).append(emp)

    pairs: list[tuple[str, int]] = []
    for group, emps in members.items():
        slots = sorted({info[e]["order"] for e in emps if info[e]["order"] is not None})
        base = group_max.get(group, 0)
        step = 1
        while len(slots) < len(emps):
            slots.append(base + 10 * step)
            step += 1
        for emp, order in zip(emps, slots):
            if info[emp]["order"] != order:
                pairs.append((emp, order))
    return pairs


def sort_users_for_display(users_df: pd.DataFrame, org_depts: pd.DataFrame | None = None) -> pd.DataFrame:
    """근무표·편성 공통 직원 정렬 — 그룹순서 → 표시순서(NULL 뒤) → 사번.

    이번 미션에서는 helper 만 제공하고 월간/편성 화면 적용은 후속 미션에서 한다.
    """
    if users_df is None or users_df.empty:
        return users_df
    group_of = dept_group_map(org_depts)
    frame = users_df.copy()
    frame["_g_order"] = [
        group_of.get(str(d).strip(), ("", 10**9))[1] for d in frame["dept_code"]
    ]
    orders = []
    for value in frame.get("display_order", pd.Series([None] * len(frame))):
        try:
            orders.append(normalize_display_order(value))
        except (TypeError, ValueError):
            orders.append(None)
    frame["_d_null"] = [1 if o is None else 0 for o in orders]
    frame["_d_order"] = [0 if o is None else o for o in orders]
    frame = frame.sort_values(
        ["_g_order", "_d_null", "_d_order", "emp_no"], kind="stable"
    ).drop(columns=["_g_order", "_d_null", "_d_order"])
    return frame.reset_index(drop=True)


def _base_users() -> pd.DataFrame:
    """샘플 CSV(id 기반)를 화면용 자연키 컬럼(USER_COLUMNS)으로 변환한 원본."""
    df = sample_data.users()
    if df.empty:
        return _typed_empty_frame(USER_COLUMNS)
    df = df.copy()
    df["dept_code"] = df["department_id"].astype(str).map(_dept_code_by_id()).fillna("")
    df["team_code"] = df["team_id"].astype(str).map(_team_code_by_id()).fillna("")
    if "display_order" not in df.columns:  # 샘플 CSV 미보유 → NULL(미지정)로 시작
        df["display_order"] = None
    for col in ("hire_date", "resign_date"):  # 재직기간(009)도 샘플 CSV 미보유 → NULL
        if col not in df.columns:
            df[col] = None
    return df[USER_COLUMNS].reset_index(drop=True)


def is_resigned(resign_date, today: date | None = None) -> bool:
    """퇴사일이 기준일(기본 오늘)을 지났는지. 빈 값·해석 불가는 재직으로 본다.

    "해석 불가 → 재직"은 의도적이다. 날짜를 못 읽었다고 재직자를 명단에서 지우거나
    로그인을 막는 쪽이 훨씬 나쁜 오작동이다(fail-open 이 맞는 드문 자리).
    퇴사일 당일은 아직 재직으로 본다 — 마지막 근무일이 명단에서 사라지면 안 된다.
    """
    parsed = supabase_repository._clean_date(resign_date)
    if not parsed:
        return False
    try:
        return date.fromisoformat(parsed) < (today or date.today())
    except ValueError:
        return False


def get_users(
    dept_code: str | None = None,
    team_code: str | None = None,
    is_active: bool | None = None,
    include_resigned: bool = True,
) -> pd.DataFrame:
    """사용자 목록(USER_COLUMNS).

    로컬 샘플 모드에서는 세션 편집 결과(save_users)를 우선 반환하므로,
    사용자 관리 화면에서 저장한 내용이 다른 화면에도 그대로 반영된다.

    ``include_resigned=False`` 면 퇴사일이 지난 직원을 제외한다(근무표 편성·조회 명단용).
    기본값이 True 인 이유: 사용자 관리 화면은 퇴사자를 봐야 되돌릴 수 있고, 아차사고 등
    과거 기록 화면은 퇴사자 이름을 계속 해석해야 한다.
    """
    if is_sample_mode():
        if _USERS_STORE not in st.session_state:
            st.session_state[_USERS_STORE] = _base_users()
        df = st.session_state[_USERS_STORE].copy()
    else:
        df = _fetch_users()
        if dept_code is not None:
            df = df[df["dept_code"].astype(str) == str(dept_code).strip()]
        if team_code is not None:
            df = df[df["team_code"].astype(str) == str(team_code).strip()]
        if is_active is not None:
            df = df[df["is_active"].astype(bool) == bool(is_active)]
    if not include_resigned and not df.empty and "resign_date" in df.columns:
        df = df[~df["resign_date"].map(is_resigned)]
    return _empty_contract(df.reset_index(drop=True), USER_COLUMNS)


def save_users(df: pd.DataFrame) -> None:
    """편집된 사용자 목록을 저장한다.

    로컬 샘플 모드에서는 세션 상태에 보관해 현재 세션 동안 유지한다(CSV 는 건드리지
    않는다). Phase 5(Supabase)에서는 여기서 upsert / is_active 소프트삭제로 교체한다.
    """
    keep = [c for c in USER_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_USERS_STORE] = normalized
        return
    changed = _changed_records(
        _fetch_users(), normalized, ["emp_no"], USER_COLUMNS
    )
    try:
        supabase_repository.upsert_users(changed)
    finally:
        _invalidate_users()


def save_users_report(df: pd.DataFrame) -> BatchWriteResult:
    """save_users 의 부분성공 원장 반환 변형. 기존 save_users 는 그대로 둔다.

    supabase 모드에서 조직 스키마 capability(도입: migration 004) 미준비 + 표시순서
    입력이 있으면 repository 가 전체 failed(비재시도) 원장을 반환한다(부분 저장 금지
    계약 유지)."""
    keep = [c for c in USER_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_USERS_STORE] = normalized
        return _sample_report(normalized.to_dict("records"), ["emp_no"])
    changed = _changed_records(
        _fetch_users(), normalized, ["emp_no"], USER_COLUMNS
    )
    if not changed:
        return BatchWriteResult()
    try:
        return supabase_repository.upsert_users_reported(changed)
    finally:
        _invalidate_users()


def update_users_display_order(pairs) -> int:
    """지정한 사용자만 표시순서(users.display_order)를 갱신한다.

    근무표 편성 화면의 행 드래그 결과를 영속화하는 **대상 지정** 쓰기다 — 사용자 목록
    전량 upsert(save_users)를 쓰지 않는다: 화면에 없는 사용자의 다른 필드를 되돌릴
    위험이 없고, 편성 화면이 users 마스터의 나머지 값을 소유하지도 않기 때문이다.

    pairs: ``[(emp_no, display_order)]``. 사번이 비었거나 순서가 미지정(None)인 항목은
    건너뛴다(이 경로는 순서를 '지우는' 용도가 아니다 — 해제는 사용자 관리 화면 담당).
    반환: 실제로 갱신 요청한 건수.
    """
    normalized: list[tuple[str, int]] = []
    for emp_no, order in pairs or []:
        emp = str(emp_no or "").strip()
        value = normalize_display_order(order)
        if not emp or value is None:
            continue
        normalized.append((emp, value))
    if not normalized:
        return 0
    if is_sample_mode():
        if _USERS_STORE not in st.session_state:
            st.session_state[_USERS_STORE] = _base_users()
        store = st.session_state[_USERS_STORE].copy()
        by_emp = dict(normalized)
        store["display_order"] = [
            by_emp.get(str(emp).strip(), current)
            for emp, current in zip(store["emp_no"], store["display_order"])
        ]
        st.session_state[_USERS_STORE] = store
        return len(normalized)
    try:
        supabase_repository.update_users_display_order(normalized)
    finally:
        _invalidate_users()
    return len(normalized)


def _base_work_types() -> pd.DataFrame:
    """샘플 CSV 를 화면용 근무형태 컬럼(WORK_TYPE_COLUMNS)으로 정리한 원본."""
    df = sample_data.work_types()
    if df.empty:
        return _typed_empty_frame(WORK_TYPE_COLUMNS)
    df = df.copy()
    for c in WORK_TYPE_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[WORK_TYPE_COLUMNS].reset_index(drop=True).copy()


def get_work_types(active_only: bool = False) -> pd.DataFrame:
    """근무형태 목록(WORK_TYPE_COLUMNS).

    로컬 샘플 모드에서는 세션 편집 결과(save_work_types)를 우선 반환하므로,
    근무형태 관리 화면에서 저장한 내용이 다른 화면에도 그대로 반영된다.
    Phase 5(Supabase)에서는 이 분기를 실제 조회로 교체한다.
    """
    if is_sample_mode():
        if _WORK_TYPES_STORE not in st.session_state:
            st.session_state[_WORK_TYPES_STORE] = _base_work_types()
        return _empty_contract(st.session_state[_WORK_TYPES_STORE].copy(), WORK_TYPE_COLUMNS)
    df = _fetch_work_types()
    if active_only:
        df = df[df["is_active"].astype(bool)]
    return _empty_contract(df.reset_index(drop=True), WORK_TYPE_COLUMNS)


def save_work_types(df: pd.DataFrame) -> None:
    """편집된 근무형태 목록을 저장한다.

    로컬 샘플 모드에서는 세션 상태에 보관해 현재 세션 동안 유지한다(CSV 는 건드리지
    않는다). Phase 5(Supabase)에서는 여기서 upsert / is_active 소프트삭제로 교체한다.
    """
    keep = [c for c in WORK_TYPE_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_WORK_TYPES_STORE] = normalized
        return
    changed = _changed_records(
        _fetch_work_types(), normalized, ["code"], WORK_TYPE_COLUMNS
    )
    try:
        supabase_repository.upsert_work_types(changed)
    finally:
        _invalidate_work_types()


def save_work_types_report(df: pd.DataFrame) -> BatchWriteResult:
    """save_work_types 의 부분성공 원장 반환 변형. 기존 save_work_types 는 그대로 둔다."""
    keep = [c for c in WORK_TYPE_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_WORK_TYPES_STORE] = normalized
        return _sample_report(normalized.to_dict("records"), ["code"])
    changed = _changed_records(
        _fetch_work_types(), normalized, ["code"], WORK_TYPE_COLUMNS
    )
    if not changed:
        return BatchWriteResult()
    try:
        return supabase_repository.upsert_work_types_reported(changed)
    finally:
        _invalidate_work_types()


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
    return _fetch_schedules()


def save_schedules(df: pd.DataFrame) -> None:
    """근무표 전체(세로형 long format, SCHEDULE_COLUMNS)를 저장한다.

    화면(schedule_edit)에서 (선택 직원 × 선택 월) 범위만 교체해 만든 전체
    스냅샷을 넘겨받아 세션 스토어에 그대로 보관한다. 로컬 샘플 모드에서는 현재
    세션 동안만 유지하며 CSV 는 건드리지 않는다. Phase 5(Supabase)에서는 여기서
    범위 삭제 후 batch upsert 로 교체한다.
    """
    keep = [c for c in SCHEDULE_COLUMNS if c in df.columns]
    normalized = df[keep].reset_index(drop=True).copy()
    if is_sample_mode():
        st.session_state[_SCHEDULES_STORE] = normalized
        return
    try:
        supabase_repository.upsert_schedules(normalized.to_dict("records"))
    finally:
        _invalidate_schedules()


def upsert_month_schedules(records) -> None:
    """근무표 레코드를 (직원, 일자) 키로 upsert 만 한다 — 삭제 없음.

    빈 셀 때문에 기존 근무를 자동 삭제하지 않는다는 원칙(CLAUDE.md §5)에 맞춰
    근무표 편성 화면의 [저장]은 이 경로를 사용한다. 기존 근무의 삭제는
    replace_month_schedules(명시적 범위 교체)로만 수행한다.
    """
    normalized = pd.DataFrame(list(records), columns=SCHEDULE_COLUMNS)
    if normalized.empty:
        return
    if is_sample_mode():
        store = get_schedules()
        by_key = {
            (str(r["emp_no"]).strip(), str(r["duty_date"])): r
            for r in store.to_dict("records")
        }
        for r in normalized.to_dict("records"):
            by_key[(str(r["emp_no"]).strip(), str(r["duty_date"]))] = r
        save_schedules(pd.DataFrame(list(by_key.values()), columns=SCHEDULE_COLUMNS))
        return
    try:
        supabase_repository.upsert_schedules(normalized.to_dict("records"))
    finally:
        _invalidate_schedules()


def replace_month_schedules(emp_nos, year: int, month: int, records) -> None:
    """선택 직원·월 범위만 전달받은 근무표로 교체한다."""
    normalized_emp_nos = [str(emp_no).strip() for emp_no in emp_nos if str(emp_no).strip()]
    normalized = pd.DataFrame(records, columns=SCHEDULE_COLUMNS)
    if is_sample_mode():
        store = get_schedules()
        month_start = pd.Timestamp(year=int(year), month=int(month), day=1)
        next_month = month_start + pd.offsets.MonthBegin(1)
        duty_dates = pd.to_datetime(store["duty_date"], errors="coerce")
        in_scope = (
            store["emp_no"].astype(str).str.strip().isin(normalized_emp_nos)
            & duty_dates.ge(month_start)
            & duty_dates.lt(next_month)
        )
        save_schedules(pd.concat([store[~in_scope], normalized], ignore_index=True))
        return
    # replace_month_schedules 는 upsert 후 개별 삭제를 수행하므로 중간 실패 시 일부만
    # 반영될 수 있다 — finally 로 어떤 결과든 캐시를 비운다(예외는 전파).
    try:
        supabase_repository.replace_month_schedules(
            normalized_emp_nos, int(year), int(month), normalized.to_dict("records")
        )
    finally:
        _invalidate_schedules()


# --- 근무조 기준정보 / 직원별 월 편성 (docs/database.md §4.5·§5.1) ---
def _base_shift_groups() -> pd.DataFrame:
    """샘플 CSV(id 기반)를 화면용 근무조 컬럼(SHIFT_GROUP_COLUMNS)으로 변환한 원본."""
    df = sample_data.shift_groups()
    if df.empty:
        return _typed_empty_frame(SHIFT_GROUP_COLUMNS)
    df = df.copy()
    df["dept_code"] = df["department_id"].astype(str).map(_dept_code_by_id()).fillna("")
    return df[SHIFT_GROUP_COLUMNS].reset_index(drop=True).copy()


def get_shift_groups(dept_code: str | None = None, is_active: bool | None = None) -> pd.DataFrame:
    """근무조 목록(SHIFT_GROUP_COLUMNS). 선택지 제공·유효성 검사 전용 기준정보."""
    if is_sample_mode():
        if _SHIFT_GROUPS_STORE not in st.session_state:
            st.session_state[_SHIFT_GROUPS_STORE] = _base_shift_groups()
        df = st.session_state[_SHIFT_GROUPS_STORE].copy()
    else:
        df = _fetch_shift_groups()
    if dept_code is not None:
        df = df[df["dept_code"].astype(str) == str(dept_code).strip()]
    if is_active is not None:
        df = df[df["is_active"].astype(bool) == bool(is_active)]
    return _empty_contract(df.reset_index(drop=True), SHIFT_GROUP_COLUMNS)


def _base_assignments() -> pd.DataFrame:
    """샘플 CSV(id 기반)를 화면용 월 편성 컬럼(SCHEDULE_ASSIGNMENT_COLUMNS)으로 변환한 원본."""
    df = sample_data.schedule_assignments()
    if df.empty:
        return _typed_empty_frame(SCHEDULE_ASSIGNMENT_COLUMNS)
    df = df.copy()
    df["emp_no"] = df["user_id"].astype(str).map(_emp_no_by_id()).fillna("")
    df["dept_code"] = df["department_id"].astype(str).map(_dept_code_by_id()).fillna("")
    df["team_code"] = df["team_id"].astype(str).map(_team_code_by_id()).fillna("")
    df["schedule_month"] = df["schedule_month"].map(
        lambda value: validators.normalize_schedule_month(value) if str(value).strip() else ""
    )
    df["shift_group_code"] = df["shift_group_code"].fillna("").astype(str)
    df = df[df["emp_no"] != ""]
    return df[SCHEDULE_ASSIGNMENT_COLUMNS].reset_index(drop=True).copy()


def _assignments_store() -> pd.DataFrame:
    if _ASSIGNMENTS_STORE not in st.session_state:
        st.session_state[_ASSIGNMENTS_STORE] = _base_assignments()
    return st.session_state[_ASSIGNMENTS_STORE]


def get_month_assignments(year: int, month: int, emp_nos=None) -> pd.DataFrame:
    """대상 월의 직원별 편성 스냅샷(SCHEDULE_ASSIGNMENT_COLUMNS).

    편성은 근무표 작성 당시 값이므로 users 의 현재 소속으로 재계산하지 않는다.
    """
    if isinstance(emp_nos, str):
        emp_nos = [emp_nos]
    normalized = {str(e).strip() for e in (emp_nos or []) if str(e).strip()}
    if not is_sample_mode():
        return _fetch_month_assignments(int(year), int(month), tuple(sorted(normalized)))
    schedule_month = validators.normalize_schedule_month((int(year), int(month)))
    df = _assignments_store().copy()
    if df.empty:
        return _typed_empty_frame(SCHEDULE_ASSIGNMENT_COLUMNS)
    df = df[df["schedule_month"].astype(str) == schedule_month]
    if normalized:
        df = df[df["emp_no"].astype(str).str.strip().isin(normalized)]
    return _empty_contract(df.reset_index(drop=True), SCHEDULE_ASSIGNMENT_COLUMNS)


def upsert_month_assignments(records, require_shift: bool = True) -> dict:
    """직원·월 편성을 upsert 한다 (직원별 월 편성 1건).

    반환: {(emp_no, schedule_month): 편성 레코드(id 포함)} — supabase 모드는 실제
    DB id, sample 모드는 (emp_no, month) 기반 안정 합성 id. 근무 저장이 이 id 로
    schedule_assignment_id 를 연결할 수 있게 한다.

    검증은 modules/validators 순수 함수로 수행한다: 사번·부서 존재, 팀-부서 소속,
    부서의 활성 조, 대상 월 정규화, 같은 직원·월 중복. 검증 실패 시 ValueError
    (supabase 모드는 SupabaseDataError) 를 던지고 아무것도 저장하지 않는다.
    편성 저장은 users 를 변경하지 않는다.

    require_shift=False 면 근무조 코드 없이 부서·팀 스냅샷만 저장한다
    (근무표 편성 화면 — 근무조 입력이 아직 없는 경로).
    """
    records = list(records)
    if not is_sample_mode():
        try:
            return supabase_repository.upsert_month_assignments(records, require_shift=require_shift)
        finally:
            _invalidate_assignments()
    users = get_users()
    depts = get_departments()
    teams = get_teams()
    shift_groups = get_shift_groups()
    normalized, errors = validators.validate_assignment_records(
        records,
        emp_nos=set(users["emp_no"].astype(str).str.strip()),
        dept_codes=set(depts["dept_code"].astype(str)),
        team_keys=set(zip(teams["dept_code"].astype(str), teams["team_code"].astype(str))),
        shift_keys={
            (str(d), str(s))
            for d, s, a in zip(
                shift_groups["dept_code"], shift_groups["shift_code"], shift_groups["is_active"]
            )
            if bool(a)
        },
        require_shift=require_shift,
    )
    if errors:
        raise ValueError("월 편성 검증 실패:\n- " + "\n- ".join(errors))
    store = _assignments_store()
    by_key = {
        (str(r["emp_no"]), str(r["schedule_month"])): r for r in store.to_dict("records")
    }
    for record in normalized:
        by_key[(record["emp_no"], record["schedule_month"])] = record
    st.session_state[_ASSIGNMENTS_STORE] = pd.DataFrame(
        list(by_key.values()), columns=SCHEDULE_ASSIGNMENT_COLUMNS
    )
    result: dict = {}
    for record in normalized:
        key = (record["emp_no"], record["schedule_month"])
        # sample 안정 합성 id — 같은 (직원·월)은 재저장해도 같은 id.
        result[key] = {
            "id": f"S-{record['emp_no']}-{record['schedule_month']}",
            "emp_no": record["emp_no"],
            "schedule_month": record["schedule_month"],
            "dept_code": record["dept_code"],
            "team_code": record["team_code"],
            "shift_group_code": record.get("shift_group_code", ""),
        }
    return result


def get_month_roster(emp_nos, year: int, month: int):
    """대상 월의 (편성, 편성정보가 붙은 일별 근무) 를 함께 반환한다.

    반환: (assignments, schedules)
      - assignments: SCHEDULE_ASSIGNMENT_COLUMNS
      - schedules: SCHEDULE_ASSIGNED_COLUMNS — 일별 근무에 해당 월 편성의
        schedule_month/dept_code/team_code/shift_group_code 를 붙인 long format.
        편성이 없는 근무 행은 빈 문자열로 채운다 (backfill 이전 데이터 호환).
    """
    assignments = get_month_assignments(year, month, emp_nos)
    schedules = get_month_schedules(emp_nos, int(year), int(month))
    merged = schedules.merge(
        assignments[["emp_no", "schedule_month", "dept_code", "team_code", "shift_group_code"]],
        on="emp_no",
        how="left",
    )
    for column in ("schedule_month", "dept_code", "team_code", "shift_group_code"):
        merged[column] = merged[column].fillna("").astype(str)
    return assignments, merged[SCHEDULE_ASSIGNED_COLUMNS].reset_index(drop=True)


# --- 아차사고(near-miss) — migration 006 (DRAFT: 실행/원격 write 승인 게이트 전) ---
# 파사드 계약(자연키): reporter_emp_no/evaluator_emp_no/dept_code. 화면은 이 함수만
# 호출하고 repository 를 직접 부르지 않는다. sample 모드는 세션 스토어, supabase
# 모드는 near_miss_reports 테이블(readiness-aware)로 분기한다.
NEAR_MISS_GRADES = supabase_repository.NEAR_MISS_GRADES
NEAR_MISS_CAUSE_CODES = supabase_repository.NEAR_MISS_CAUSE_CODES
NEAR_MISS_STATUSES = supabase_repository.NEAR_MISS_STATUSES
NEAR_MISS_COLUMNS = supabase_repository.NEAR_MISS_COLUMNS

# 허용 상태 전이(actor 의미·컷오프는 docs/database.md 상태전이 계약 참조).
#   SUBMITTED  → IN_REVIEW(검토 착수) / EVALUATED(평가 즉시확정) / REJECTED(반려)
#   IN_REVIEW  → EVALUATED / REJECTED / SUBMITTED(반송)
#   EVALUATED  → CLOSED(종결) / IN_REVIEW(재개 — 평가필드 초기화)
#   REJECTED   → SUBMITTED(재개)
#   CLOSED     → (종결, 전이 없음)
NEAR_MISS_TRANSITIONS = {
    "SUBMITTED": frozenset({"IN_REVIEW", "EVALUATED", "REJECTED"}),
    "IN_REVIEW": frozenset({"EVALUATED", "REJECTED", "SUBMITTED"}),
    "EVALUATED": frozenset({"CLOSED", "IN_REVIEW"}),
    "REJECTED": frozenset({"SUBMITTED"}),
    "CLOSED": frozenset(),
}
# 평가 필드(확정등급/평가자/평가시각)가 유지되는 상태. 이외로 전이하면 초기화한다
# (near_miss_eval_consistency DB 제약 충족 — 006).
_NEAR_MISS_EVAL_STATES = frozenset({"EVALUATED", "CLOSED"})

# 클라이언트(화면 위젯)가 payload 로 보내도 파사드가 무시하고 서버측(세션 사용자·서버
# 시각·상태머신)에서만 확정하는 필드. 다른 사람 이름으로 보고/평가했다고 위조하거나
# 상태·평가값을 임의로 밀어넣는 것을 막는다(fail-closed 신원 계약).
_NEAR_MISS_SERVER_FIELDS = frozenset({
    "id", "report_no", "status",
    "reporter_emp_no", "reporter_user_id",
    "evaluator_emp_no", "evaluator_user_id",
    "dept_code", "department_id",
    "confirmed_grade", "evaluated_at",
    "rejection_reason", "is_active",
    "created_by", "updated_by", "created_at", "updated_at",
})

# 동시 전이/평가가 서로의 결과를 덮어쓰는 lost update 를 막는 조건부 UPDATE 실패 메시지.
_NEAR_MISS_STALE_MESSAGE = (
    "상태가 이미 변경되어 요청을 적용할 수 없습니다(다른 사용자가 먼저 처리). "
    "목록을 재조회한 뒤 다시 시도하세요."
)

# 평가(EVALUATED 확정)를 시작할 수 있는 사전(pre-evaluation) 상태. 이미 평가/종결된
# 보고서(EVALUATED/CLOSED)는 재평가로 덮어쓸 수 없다(lost update 방지).
_NEAR_MISS_PRE_EVAL_STATES = frozenset({"SUBMITTED", "IN_REVIEW"})

# 서버측 인가 실패(능력·소유자 게이트 미충족) 메시지. 상태전이·평가확정은 평가자
# (ADMIN/MANAGER/안전담당자) 능력이 필요하고, REJECTED→SUBMITTED 재개만 보고자 본인
# 이 추가로 허용된다(docs/database.md §8 행위자 계약).
_NEAR_MISS_NOT_AUTHORIZED_MESSAGE = (
    "이 작업을 수행할 권한이 없습니다. 아차사고 평가·상태 변경은 관리자·매니저 또는 "
    "안전담당자만 할 수 있습니다."
)

# 재개(EVALUATED→IN_REVIEW) probe 오류(fail-closed) 메시지. 007 적용 여부가 불명일 때
# 일반 UPDATE 로 조용히 빠져 CAPA 리셋을 건너뛰는 fail-open 창을 막고 명시적으로 전파한다.
_NEAR_MISS_REOPEN_PROBE_ERROR_MESSAGE = (
    "개선조치 스키마 준비 상태를 확인할 수 없어 재개를 진행할 수 없습니다"
    "(일시 오류 가능). 잠시 후 다시 시도하세요."
)

# 보완요청(반송, IN_REVIEW→SUBMITTED) 전용 안내. 반려(REJECTED, 종결분기)와 의미가
# 다르며, 사유를 저장할 007 컬럼이 준비되지 않으면 사유 없는 반송을 만들지 않도록
# fail-closed 로 차단한다.
_NEAR_MISS_REVISION_VIA_FACADE_MESSAGE = (
    "보완요청(반송)은 request_near_miss_revision 로만 가능합니다. 보완 사유가 필요합니다."
)
_NEAR_MISS_REVISION_NOT_READY_MESSAGE = (
    "보완요청 스키마가 아직 준비되지 않아 보완 사유를 저장할 수 없습니다. "
    "개선조치·보완요청 스키마(007)를 적용한 뒤 다시 시도하세요."
)


def _near_miss_actor(current_user, *, action: str) -> dict:
    """세션 사용자에서 행위자 신원을 서버측으로 확정한다(위조 방지).

    화면은 반드시 인증된 현재 사용자(auth.get_current_user 반환값)를 넘겨야 하며,
    위젯 입력값이 아니다. **사번(emp_no)만** 신뢰하고, 사번·부서·역할·안전담당 여부는
    세션 dict 가 아니라 그 사번으로 조회한 DB 권위 사용자 레코드에서 다시 도출한다 —
    위조된 current_user(예: 사번은 유효하나 dept_code/role 을 조작)로 다른 부서에
    귀속시키거나 권한을 가장하는 것을 막는다. payload 의 신원 필드는 신뢰하지 않는다.
    비활성(is_active=false) 사용자는 행위할 수 없다. 신원을 확인할 수 없으면 DB 요청
    전에 차단한다.

    반환 dict 는 emp_no·dept_code 와 함께 능력 판정 근거(role·is_safety_officer)를
    담아, 인가는 auth.can_evaluate_near_miss(actor) 단일 SoT 로 판정한다(db 에 능력
    규칙을 중복 구현하지 않는다)."""
    if not isinstance(current_user, dict):
        raise ValueError(f"{action}에는 인증된 현재 사용자 정보가 필요합니다.")
    emp_no = str(current_user.get("emp_no") or "").strip()
    # 인가 판정 근거(role·is_active·is_safety_officer)는 30초 읽기 캐시(_fetch_users)를
    # 우회한 권위 읽기로 가져온다 — 권한 회수/비활성화 직후 최대 30초 stale 통과를
    # 막는다(Codex P2-1). 조회 화면용 읽기 캐시는 훼손하지 않는다.
    record = find_user_by_emp_no(emp_no, use_cache=False) if emp_no else None
    if not emp_no or record is None:
        raise ValueError(f"{action} 행위자 사번을 확인할 수 없습니다: {emp_no!r}")
    # 지연 import — auth 는 db 를 import 하므로 모듈 최상위 import 는 순환이 된다(Codex P2).
    from modules import auth
    # 비활성 사용자는 인증됐더라도 행위 차단(fail-closed).
    if not auth._as_bool(record.get("is_active", True)):
        raise ValueError(f"{action} 권한이 없습니다: 비활성 사용자입니다({emp_no}).")
    # 사번·부서·능력근거 모두 권위 레코드에서 가져온다(세션 dict 의 dept_code/role 무시).
    # emp_no 는 개선조치 행단위 인가(assignee/designated_confirmer 본인 매칭)의 **권위 신원**
    # 이다. 사용자 자연키 계약(USER_COLUMNS)·조회 경로는 사용자 id 를 노출하지 않으므로
    # (sample/supabase 공통), 담당자/확인자 매칭은 저장된 권위 사번(DB 원본 표기) 대 actor
    # 권위 사번의 정확 일치로 한다(auth.can_work_improvement/can_review_improvement).
    return {
        "emp_no": str(record.get("emp_no") or emp_no).strip(),
        "dept_code": str(record.get("dept_code") or "").strip(),
        "role": str(record.get("role") or "").strip().upper(),
        "is_safety_officer": auth._as_bool(record.get("is_safety_officer", False)),
    }


def _near_miss_updated_by(current_user):
    """감사(updated_by)용 행위자 사번을 세션 사용자에서 얻는다(없으면 None, 비강제)."""
    if isinstance(current_user, dict):
        emp = str(current_user.get("emp_no") or "").strip()
        return emp or None
    return None


def near_miss_transition_allowed(current, target) -> bool:
    """current → target 상태 전이가 허용되는지."""
    return str(target).strip() in NEAR_MISS_TRANSITIONS.get(str(current).strip(), frozenset())


def near_miss_schema_ready() -> bool:
    """006 아차사고 스키마 사용 가능 여부. sample 은 항상 True."""
    if is_sample_mode():
        return True
    return supabase_repository.near_miss_extensions_ready()


def near_miss_schema_probe(*, force: bool = False) -> str:
    """006 아차사고 스키마 준비 상태를 3-state 로 반환한다(배너/재확인 UX 용).

    반환: READINESS_READY / READINESS_NOT_READY(미적용) / READINESS_PROBE_ERROR(확인 실패).
    sample 은 항상 READY. 조직 스키마 3-state(org_extensions_probe)와 같은 관행이며,
    PROBE_ERROR(일시 장애)를 '미적용/빈 데이터'로 단정하지 않는다."""
    if is_sample_mode():
        return supabase_repository.READINESS_READY
    return supabase_repository.near_miss_extensions_probe(force=force)


def _near_miss_frame(rows) -> pd.DataFrame:
    """자연키 dict 리스트를 NEAR_MISS_COLUMNS 계약 프레임으로 만든다(photo_paths=list 보존)."""
    if rows:
        df = pd.DataFrame(list(rows))
        for column in NEAR_MISS_COLUMNS:
            if column not in df.columns:
                df[column] = None
        return df[NEAR_MISS_COLUMNS].reset_index(drop=True).copy()
    return pd.DataFrame({
        column: pd.Series(dtype="bool" if column == "is_active" else "object")
        for column in NEAR_MISS_COLUMNS
    })


# sample 모드 아차사고 시드 — 화면 확인용 가상 사례(세션 스토어 최초 접근 시 1회).
# 상태 흐름(제출→검토→평가→종결)별 1건씩 두어 큐·조회·통계 화면이 빈 화면이 아니게 한다.
# 인물·부서는 data/sample 의 가상 기준정보만 사용한다.
_NEAR_MISS_SEED = [
    {"id": "NM-S1", "report_no": "202607-0001", "status": "CLOSED",
     "work_name": "원료 투입", "work_content": "PET 원료 포대 투입 작업",
     "incident_content": "호이스트로 포대 인양 중 결속이 풀려 바닥으로 낙하, 작업자 1m 옆 통과",
     "countermeasure": "결속 상태 2인 상호 확인 후 인양, 인양 구간 하부 출입 통제",
     "site_description": "원료 투입장 호이스트 하부",
     "proposed_grade": "B", "confirmed_grade": "A",
     "cause_code": "DROP", "cause_detail": "결속 불량", "incident_date": "2026-07-03",
     "reporter_emp_no": "1005", "evaluator_emp_no": "1001", "dept_code": "PET2",
     "photo_paths": [], "rejection_reason": "", "evaluated_at": "2026-07-04T09:00:00+00:00",
     "is_active": True},
    {"id": "NM-S2", "report_no": "202607-0002", "status": "EVALUATED",
     "work_name": "설비 청소", "work_content": "압출기 주변 바닥 청소",
     "incident_content": "냉각수 누수로 바닥이 젖어 있어 이동 중 미끄러질 뻔함",
     "countermeasure": "누수 구간 즉시 보수 요청, 미끄럼 주의 표지 설치",
     "site_description": "1층 압출기 3호기 옆 통로",
     "proposed_grade": "C", "confirmed_grade": "C",
     "cause_code": "SLIP", "cause_detail": "바닥 수분", "incident_date": "2026-07-21",
     "reporter_emp_no": "1003", "evaluator_emp_no": "1001", "dept_code": "PET1",
     "photo_paths": [], "rejection_reason": "", "evaluated_at": "2026-07-22T02:30:00+00:00",
     "is_active": True},
    {"id": "NM-S3", "report_no": "202608-0001", "status": "SUBMITTED",
     "work_name": "제품 적재", "work_content": "완제품 팔레트 지게차 적재",
     "incident_content": "적재 중 팔레트 모서리가 선반 기둥에 충돌해 제품 일부 흔들림",
     "countermeasure": "적재 구역 유도선 재도색, 후진 시 유도자 배치",
     "site_description": "완제품 창고 3열 선반",
     "proposed_grade": "D", "confirmed_grade": None,
     "cause_code": "HIT", "cause_detail": "시야 미확보", "incident_date": "2026-08-05",
     "reporter_emp_no": "1004", "evaluator_emp_no": None, "dept_code": "PET1",
     "photo_paths": [], "rejection_reason": "", "evaluated_at": None,
     "is_active": True},
]


def _near_miss_store() -> pd.DataFrame:
    """sample 모드 아차사고 backing store(세션 유지, 실DB 미변경). 최초 접근 시 시드 주입."""
    if _NEAR_MISS_STORE not in st.session_state:
        st.session_state[_NEAR_MISS_STORE] = _near_miss_frame(
            [dict(r) for r in _NEAR_MISS_SEED]
        )
    return st.session_state[_NEAR_MISS_STORE]


def _sample_report_no(store: pd.DataFrame, incident_date: str) -> str:
    """sample 채번 — 연월(YYYYMM)+월순번. supabase 는 repository._next_report_no."""
    ym = str(incident_date).replace("-", "")[:6]
    max_seq = 0
    if not store.empty:
        for value in store["report_no"].astype(str):
            if value.startswith(ym + "-"):
                try:
                    max_seq = max(max_seq, int(value.rsplit("-", 1)[-1]))
                except (TypeError, ValueError):
                    continue
    return f"{ym}-{max_seq + 1:04d}"


def _near_miss_editable_fields(payload: dict) -> dict:
    """수정 가능한 본문 필드(자연키)를 검증·정규화한다(신원/상태 제외).

    sample create(`_sample_near_miss_record`)와 수정(`update_near_miss_report`)이
    **같은** 필드 검증을 공유하도록 추출한 헬퍼다 — 한쪽만 느슨해지는 검증 분기를
    막는다. reporter/부서/상태/평가/시각은 포함하지 않는다(서버측 확정 대상)."""
    work_name = str(payload.get("work_name") or "").strip()
    if not work_name:
        raise ValueError("작업명은 비어 있을 수 없습니다.")
    cause = str(payload.get("cause_code") or "").strip().upper()
    if cause not in NEAR_MISS_CAUSE_CODES:
        raise ValueError(f"원인 코드가 유효하지 않습니다: {cause}")
    proposed = payload.get("proposed_grade")
    proposed = str(proposed).strip().upper() if proposed not in (None, "") else None
    if proposed is not None and proposed not in NEAR_MISS_GRADES:
        raise ValueError(f"제안 등급이 유효하지 않습니다: {proposed}")
    incident_date = str(payload.get("incident_date") or "").strip()
    date.fromisoformat(incident_date)  # 형식 오류 시 ValueError
    # photo_paths 는 본문(편집) 계약에서 **완전히 제외**한다(P1-3, repository 와 동일).
    # 사진 배열은 오직 첨부/삭제 CAS 경로로만 변경한다 — 본문 수정이 사진 배열을 read-
    # modify-write 로 덮어써 lost update 를 내는 것을 차단한다. payload 의 photo_paths 는
    # 읽지도 저장하지도 않는다(무시).
    return {
        "work_name": work_name,
        "work_content": str(payload.get("work_content") or ""),
        "incident_content": str(payload.get("incident_content") or ""),
        "countermeasure": str(payload.get("countermeasure") or ""),
        "site_description": str(payload.get("site_description") or ""),
        "proposed_grade": proposed,
        "cause_code": cause,
        "cause_detail": str(payload.get("cause_detail") or ""),
        "incident_date": incident_date,
    }


def _sample_near_miss_record(payload: dict, store: pd.DataFrame) -> dict:
    """create 입력(자연키)을 검증해 sample 스토어 레코드로 만든다.

    reporter_emp_no·dept_code·시각은 서버측 값이다(화면이 세션에서 채워 넘긴다).
    본문 필드 검증은 수정 경로와 공유하는 `_near_miss_editable_fields` 로 위임한다.
    """
    body = _near_miss_editable_fields(payload)
    reporter = str(payload.get("reporter_emp_no") or "").strip()
    if not reporter or find_user_by_emp_no(reporter) is None:
        raise ValueError(f"아차사고 보고자 사번을 찾을 수 없습니다: {reporter}")
    ids = pd.to_numeric(store["id"], errors="coerce").dropna() if not store.empty else pd.Series([], dtype=float)
    new_id = int(ids.max()) + 1 if not ids.empty else 1
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": new_id,
        "report_no": _sample_report_no(store, body["incident_date"]),
        "status": "SUBMITTED",
        **body,
        # 사진은 create 시점엔 항상 빈 배열(create-then-upload). body 는 photo_paths 를
        # 담지 않으므로(P1-3) 여기서 명시 초기화한다 — supabase 계약과 parity.
        "photo_paths": [],
        "confirmed_grade": None,
        "reporter_emp_no": reporter,
        "evaluator_emp_no": "",
        "dept_code": str(payload.get("dept_code") or ""),
        "rejection_reason": None,
        "evaluated_at": None,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


def _sample_update_near_miss(
    report_id, *, expected_status=None, owner_emp_no=None, expected_photo_paths=None,
    clear_eval: bool = False, allow_null=(), **changes
) -> bool:
    """sample 스토어의 단일 보고서 필드를 변경한다(존재하는 컬럼만).

    ``expected_status`` 가 주어지면 현재 상태가 일치할 때만 적용한다(supabase 조건부
    UPDATE 와 동일한 원자 전이 계약을 sample 에서도 모사). ``owner_emp_no`` 가 주어지면
    보고자(reporter_emp_no)가 **정확히 일치**(trim only, casefold 아님)할 때만 적용한다
    — supabase 의 ``where reporter_user_id=?`` 조건과 대응하는 소유자 게이트다.
    ``expected_photo_paths`` 가 주어지면 현재 저장된 사진 배열이 그 스냅샷과 **정확히
    일치**할 때만 적용한다(P1-3 CAS) — supabase 의 ``updated_at`` CAS 와 대응해, 두 동시
    사진 변경이 서로를 덮어쓰는 lost update 를 sample 에서도 막는다(경합 시 False→stale).
    적용하면 True, 대상 없음·상태 불일치(이미 전이됨)·소유자 불일치·사진 스냅샷 불일치면
    False 를 반환해 파사드가 stale 오류를 낼 수 있게 한다. ``allow_null`` 에 든 컬럼은 값이
    None 이어도 갱신한다(제안등급 해제 등) — 기본은 None 을 건너뛰어 전이 시 다른 필드
    클로버를 막는다."""
    store = _near_miss_store().copy()
    mask = store["id"].astype(str) == str(report_id)
    if not mask.any():
        return False
    if expected_status is not None:
        current = store.loc[mask, "status"].astype(str).str.strip()
        if not (current == str(expected_status).strip()).all():
            return False
    if expected_photo_paths is not None:
        # CAS: 현재 사진 배열이 읽은 스냅샷과 다르면(그 사이 다른 첨부/삭제) 적용 거부.
        snapshot = [str(p) for p in expected_photo_paths]
        for i in store.index[mask]:
            cur = store.at[i, "photo_paths"]
            cur_list = [str(p) for p in cur] if isinstance(cur, (list, tuple)) else []
            if cur_list != snapshot:
                return False
    if owner_emp_no is not None:
        # 정확 일치(trim only, casefold 아님) — 대소문자만 다른 사번(ABC vs abc)은
        # supabase(reporter_user_id 구분)처럼 별개 소유자다. casefold 하면 sample 에서만
        # abc 가 ABC 보고서를 수정하게 되어 계약(requirements.md:39)과 어긋난다.
        owners = store.loc[mask, "reporter_emp_no"].astype(str).str.strip()
        if not (owners == str(owner_emp_no).strip()).all():
            return False
    allow_null = set(allow_null)
    if clear_eval:
        store.loc[mask, "confirmed_grade"] = None
        store.loc[mask, "evaluator_emp_no"] = ""
        store.loc[mask, "evaluated_at"] = None
    indices = store.index[mask]
    for column, value in changes.items():
        if column in store.columns and (value is not None or column in allow_null):
            # .at 로 인덱스별 단일 셀에 대입한다 — list(photo_paths) 를 loc 로 대입하면
            # pandas 가 원소별 정렬을 시도해 리스트가 풀리거나 길이 불일치로 실패한다.
            for i in indices:
                store.at[i, column] = value
    store.loc[mask, "updated_at"] = datetime.now(timezone.utc).isoformat()
    st.session_state[_NEAR_MISS_STORE] = store.reset_index(drop=True)
    return True


def get_near_miss_reports(filters: dict | None = None) -> pd.DataFrame:
    """아차사고 보고서 목록(NEAR_MISS_COLUMNS).

    filters(선택): include_archived(bool, 기본 False=활성만), status, dept_code,
    cause_code, confirmed_grade, reporter_emp_no, date_from/date_to(incident_date 기준).
    """
    filters = dict(filters or {})
    include_archived = bool(filters.get("include_archived"))
    if is_sample_mode():
        df = _near_miss_store().copy()
        if not include_archived and not df.empty:
            df = df[df["is_active"].astype(bool)]
    else:
        df = _fetch_near_miss(include_archived).copy()
    if df.empty:
        return _near_miss_frame([])
    for column, value in (
        ("status", filters.get("status")),
        ("dept_code", filters.get("dept_code")),
        ("cause_code", filters.get("cause_code")),
        ("confirmed_grade", filters.get("confirmed_grade")),
        ("reporter_emp_no", filters.get("reporter_emp_no")),
    ):
        if value is not None and str(value).strip() != "":
            df = df[df[column].astype(str).str.strip() == str(value).strip()]
    if filters.get("date_from"):
        df = df[df["incident_date"].astype(str) >= str(filters["date_from"]).strip()]
    if filters.get("date_to"):
        df = df[df["incident_date"].astype(str) <= str(filters["date_to"]).strip()]
    return _empty_contract(df.reset_index(drop=True).copy(), NEAR_MISS_COLUMNS)


def get_near_miss_report(report_id) -> dict | None:
    """단일 아차사고 보고서(자연키 dict) 또는 None."""
    if is_sample_mode():
        store = _near_miss_store()
        match = store[store["id"].astype(str) == str(report_id)]
        if match.empty:
            return None
        record = match.iloc[0].to_dict()
        # Series 경유에서 None 이 NaN 으로 승격될 수 있다(스토어 dtype 추론 — 시드 도입
        # 후 실측). 계약은 "빈 값 = None" 이므로 경계에서 정규화해 supabase 와 동형화한다.
        # photo_paths 같은 list 값은 pd.isna 판정 대상이 아니다(배열 ambiguity 회피).
        return {
            k: (None if (not isinstance(v, (list, dict)) and pd.isna(v)) else v)
            for k, v in record.items()
        }
    return supabase_repository.get_near_miss_report(report_id)


def create_near_miss_report(payload: dict, *, current_user) -> dict:
    """아차사고 보고서를 생성한다(status=SUBMITTED). 생성된 자연키 dict 반환.

    보고자·부서·created_by 는 payload 가 아니라 인증된 ``current_user``(세션 사용자,
    auth.get_current_user() 반환값)에서 **서버측으로 확정**한다. payload 의 신원·상태
    필드(reporter_*, evaluator_*, dept_code, status, created_by 등)는 무시한다 —
    클라이언트가 다른 사람 이름으로 보고하는 위조를 막는다. 화면은 위젯 값이 아니라
    세션 사용자를 넘겨야 한다. 시각·상태·report_no 는 서버측에서 설정한다.
    """
    actor = _near_miss_actor(current_user, action="아차사고 보고 생성")
    # 클라이언트가 보낸 신원/상태/서버측 필드를 제거하고 서버 확정값으로만 덮어쓴다.
    safe = {k: v for k, v in dict(payload or {}).items() if k not in _NEAR_MISS_SERVER_FIELDS}
    safe["reporter_emp_no"] = actor["emp_no"]
    safe["dept_code"] = actor["dept_code"]
    safe["created_by"] = actor["emp_no"]
    if is_sample_mode():
        store = _near_miss_store()
        record = _sample_near_miss_record(safe, store)
        st.session_state[_NEAR_MISS_STORE] = pd.concat(
            [store, _near_miss_frame([record])], ignore_index=True
        )
        return record
    try:
        return supabase_repository.create_near_miss_report(safe)
    finally:
        _invalidate_near_miss()


_NEAR_MISS_EDITABLE_STATUS = "SUBMITTED"
_NEAR_MISS_NOT_OWNER_MESSAGE = "본인이 보고한 아차사고만 수정할 수 있습니다."
_NEAR_MISS_NOT_EDITABLE_MESSAGE = (
    "제출(SUBMITTED) 상태의 아차사고만 수정할 수 있습니다. "
    "검토·평가·반려·종결된 보고서는 수정할 수 없습니다."
)


def update_near_miss_report(report_id, payload: dict, *, current_user) -> dict | None:
    """보고자 본인이 SUBMITTED 상태의 아차사고 본문을 수정한다.

    수정 행위자 신원은 payload/위젯이 아니라 인증된 ``current_user``(세션 사용자,
    auth.get_current_user() 반환값)에서 **서버측으로 확정**한다(사번만 신뢰). 소유자
    게이트(보고자 본인)와 생명주기 게이트(status==SUBMITTED)를 DB 요청 전에 확인해
    사람이 읽을 수 있는 오류를 주고, 실제 저장은 소유자·상태를 함께 조건으로 거는
    원자적 조건부 UPDATE 로 수행해 TOCTOU/lost update 를 서버측에서 재차 막는다.

    server-owned 필드(id/report_no/status/reporter_*/evaluator_*/부서/확정등급/
    평가시각/반려사유/is_active/감사시각)는 payload 에서 제거되어 **절대** 저장되지
    않는다 — 본문 컬럼만 수정한다. 상태/생명주기는 이 경로로 바꾸지 않으며 제출취소는
    범위 밖이다. 검증은 create 와 공유하는 `_near_miss_editable_fields` /
    repository `_near_miss_editable_payload` 를 사용한다(검증 단일화, fail-closed).
    updated_by 는 세션 행위자 사번으로 확정한다."""
    actor = _near_miss_actor(current_user, action="아차사고 수정")
    current = get_near_miss_report(report_id)
    if current is None:
        raise ValueError(f"아차사고 보고서를 찾을 수 없습니다: {report_id}")
    # 소유자 게이트: 보고자 본인만. **정확 일치(trim only, casefold 아님)** — 대소문자만
    # 다른 사번(ABC vs abc)은 계약상 별개 활성 계정이며(requirements.md:39, SQL unique 는
    # 대소문자 구분), supabase 는 reporter_user_id 로 서로 다르게 귀속된다. 여기서 casefold
    # 하면 sample 에서만 abc 가 ABC 의 보고서를 수정할 수 있어 supabase 와 어긋난다.
    # 보고서의 reporter_emp_no 와 actor.emp_no 는 같은 사람의 권위 원본값이므로 정확
    # 일치로 정당한 소유자를 배제하지 않는다(로그인 시 casefold 계정 선택과는 무관).
    owner = str(current.get("reporter_emp_no") or "").strip()
    if owner != actor["emp_no"]:
        raise ValueError(_NEAR_MISS_NOT_OWNER_MESSAGE)
    # 생명주기 게이트: SUBMITTED 에서만 수정 가능(docs/database.md 상태전이 계약).
    if str(current.get("status") or "").strip() != _NEAR_MISS_EDITABLE_STATUS:
        raise ValueError(_NEAR_MISS_NOT_EDITABLE_MESSAGE)
    # server-owned 필드를 제거한다 — 상태/신원/평가/부서/감사는 payload 로 못 쓴다.
    safe = {k: v for k, v in dict(payload or {}).items() if k not in _NEAR_MISS_SERVER_FIELDS}
    if is_sample_mode():
        fields = _near_miss_editable_fields(safe)  # create 와 같은 검증
        ok = _sample_update_near_miss(
            report_id, expected_status=_NEAR_MISS_EDITABLE_STATUS,
            owner_emp_no=actor["emp_no"], allow_null={"proposed_grade"}, **fields,
        )
        if not ok:
            raise ValueError(_NEAR_MISS_STALE_MESSAGE)
        return get_near_miss_report(report_id)
    try:
        return supabase_repository.update_near_miss_report(
            report_id, safe, reporter_emp_no=actor["emp_no"], updated_by=actor["emp_no"],
        )
    finally:
        _invalidate_near_miss()


# =========================================================================
# 아차사고 사진 첨부 저장 계약 (Storage 백엔드 — supabase 비공개 버킷 / sample 세션)
# =========================================================================
def _near_miss_photo_store() -> dict:
    """sample 모드 사진 backing store(세션 유지): 저장경로 → 정규화 JPEG bytes."""
    if _NEAR_MISS_PHOTO_STORE not in st.session_state:
        st.session_state[_NEAR_MISS_PHOTO_STORE] = {}
    return st.session_state[_NEAR_MISS_PHOTO_STORE]


def _near_miss_owner_editable_gate(report_id, actor) -> dict:
    """보고서를 조회하고 소유자(보고자 본인)+SUBMITTED 게이트를 확인해 반환한다.

    본문 수정(update_near_miss_report)과 같은 게이트를 사진 첨부/삭제에도 적용한다 —
    사진은 SUBMITTED 상태의 보고자 본인만 추가·삭제할 수 있다. 소유자 비교는 본문
    수정과 동일하게 **정확 일치(trim only, casefold 아님)** 다."""
    current = get_near_miss_report(report_id)
    if current is None:
        raise ValueError(f"아차사고 보고서를 찾을 수 없습니다: {report_id}")
    owner = str(current.get("reporter_emp_no") or "").strip()
    if owner != actor["emp_no"]:
        raise ValueError(_NEAR_MISS_NOT_OWNER_MESSAGE)
    if str(current.get("status") or "").strip() != _NEAR_MISS_EDITABLE_STATUS:
        raise ValueError(_NEAR_MISS_NOT_EDITABLE_MESSAGE)
    return current


def near_miss_photo_bucket_probe(*, force: bool = False) -> str:
    """사진 저장소(Storage 버킷) 준비 상태를 3-state 로 확인한다(read-only).

    sample 은 항상 READY(세션 인메모리 저장). supabase 는 버킷 존재 여부를 probe 한다
    (near_miss_schema_probe 와 같은 3-state 관행)."""
    if is_sample_mode():
        return supabase_repository.READINESS_READY
    return supabase_repository.near_miss_photo_bucket_probe(force=force)


def upload_near_miss_photo(report_id, file_bytes, filename, *, current_user) -> dict:
    """소유자(SUBMITTED)가 사진 1장을 첨부한다: 검증→압축→저장→경로 배열 갱신.

    행위자 신원은 payload 가 아니라 인증된 ``current_user``(세션 사용자)에서 서버측
    확정한다. 게이트: 보고자 본인 + status==SUBMITTED + 현재 첨부 < ``MAX_PHOTOS``.
    파일은 ``photo_storage.validate_and_compress`` 로 검증(확장자+매직바이트 jpg/png/
    webp, 원본 ≤10MB)·압축(최대변 1600px·JPEG)한 뒤, **서버가 생성한** 경로
    ``near-miss/{report_id}/{uuid}.jpg`` 로 저장한다(사용자 파일명은 경로에 미사용).
    저장 성공 후 photo_paths 배열에 원자적 조건부(소유자+SUBMITTED) 추가한다.

    반환: ``{"path": 저장경로, "photo_paths": 갱신된 배열}``. 검증/게이트 실패는
    ValueError(사용자 안전 문구). supabase 모드에서 버킷 미준비면 fail-closed."""
    actor = _near_miss_actor(current_user, action="아차사고 사진 첨부")
    current = _near_miss_owner_editable_gate(report_id, actor)
    existing = [str(p) for p in (current.get("photo_paths") or [])]
    if len(existing) >= photo_storage.MAX_PHOTOS:
        raise ValueError(
            f"사진은 보고서당 최대 {photo_storage.MAX_PHOTOS}장까지 첨부할 수 있습니다."
        )
    # 검증·압축(도메인 오류는 ValueError=PhotoValidationError 로 그대로 노출).
    data, _ext, content_type = photo_storage.validate_and_compress(file_bytes, filename)
    path = photo_storage.build_object_path(report_id)
    new_paths = existing + [path]
    snapshot = current.get("updated_at")  # P1-3 CAS 토큰(supabase updated_at)

    if is_sample_mode():
        ok = _sample_update_near_miss(
            report_id, expected_status=_NEAR_MISS_EDITABLE_STATUS,
            owner_emp_no=actor["emp_no"], expected_photo_paths=existing,
            photo_paths=new_paths,
        )
        if not ok:
            raise ValueError(_NEAR_MISS_STALE_MESSAGE)
        self_store = _near_miss_photo_store()
        self_store[path] = data  # 정규화 bytes 를 세션에 보관(실DB 미변경)
        return {"path": path, "photo_paths": new_paths}

    # supabase: 버킷 미준비면 fail-closed(저장 전 차단 — 조용한 무시 없음).
    if not supabase_repository.near_miss_photo_bucket_ready():
        raise ValueError(supabase_repository._NM_PHOTO_BUCKET_NOT_READY_MESSAGE)
    supabase_repository.upload_near_miss_photo_object(path, data, content_type)
    try:
        updated = supabase_repository.set_near_miss_photo_paths(
            report_id, new_paths, reporter_emp_no=actor["emp_no"],
            expected_updated_at=snapshot, updated_by=actor["emp_no"],
        )
    except Exception:
        # 경로 배열 갱신 실패(CAS stale 등) → 방금 올린 객체를 보상 삭제(고아 방지).
        # 보상 삭제까지 실패하면 고아 객체가 남으므로 감사 로그를 남긴다(P1-4). 로그에는
        # 보고서 id 와 객체 경로만 — 서명 URL·키는 절대 남기지 않는다.
        try:
            supabase_repository.remove_near_miss_photo_object(path)
        except Exception:  # noqa: BLE001 — 정리 실패는 원 오류를 가리지 않는다.
            _LOG.warning(
                "near-miss photo orphan after failed path-append: report_id=%s object=%s",
                report_id, path,
            )
        raise
    finally:
        _invalidate_near_miss()
    return {"path": path, "photo_paths": list((updated or {}).get("photo_paths") or new_paths)}


def get_near_miss_photo_url(path: str) -> str | None:
    """사진 표시용 URL 을 반환한다(없으면 None).

    supabase: 비공개 버킷의 단기 signed URL(service key 서버 전용 — 공개 URL 미생성).
    sample: 세션 인메모리 bytes 를 data: URL 로 인라인(외부 저장 없음)."""
    p = str(path or "")
    if not p:
        return None
    if is_sample_mode():
        data = _near_miss_photo_store().get(p)
        if not data:
            return None
        import base64
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{photo_storage.OUTPUT_CONTENT_TYPE};base64,{b64}"
    return supabase_repository.signed_near_miss_photo_url(p)


def read_near_miss_photo(path: str) -> bytes | None:
    """사진 원본(정규화 JPEG) bytes 를 반환한다(서버 전용, 없으면 None)."""
    p = str(path or "")
    if not p:
        return None
    if is_sample_mode():
        return _near_miss_photo_store().get(p)
    return supabase_repository.download_near_miss_photo_object(p)


def delete_near_miss_photo(report_id, path, *, current_user) -> dict:
    """소유자(SUBMITTED)가 첨부 사진 1장을 삭제한다: 경로 배열 갱신→객체 삭제.

    게이트는 첨부와 동일(보고자 본인 + SUBMITTED). ``path`` 는 해당 보고서 경로
    스킴에 속해야 한다(임의 경로 객체 삭제 차단). photo_paths 에서 먼저 제거(원자적
    CAS)한 뒤 객체를 삭제한다 — 참조가 사라진 dangling 이미지를 만들지 않기 위해 참조
    제거를 우선한다.

    반환: ``{"photo_paths": 갱신배열, "storage_deleted": bool}``. **P1-4**: 스토리지
    객체 삭제가 실패해도 성공으로 위장하지 않는다 — ``storage_deleted=False`` 로 부분
    성공(참조는 제거됐으나 객체는 남음=고아)을 표면화하고, 보고서 id·객체 경로만 감사
    로그로 남긴다(서명 URL·키 기록 금지). 참조 제거(CAS) 자체가 경합/게이트로 실패하면
    stale 오류를 올린다(아무 것도 삭제하지 않음)."""
    actor = _near_miss_actor(current_user, action="아차사고 사진 삭제")
    current = _near_miss_owner_editable_gate(report_id, actor)
    target = str(path or "")
    if not photo_storage.is_owned_path(report_id, target):
        raise ValueError("이 보고서의 사진 경로가 아닙니다.")
    existing = [str(p) for p in (current.get("photo_paths") or [])]
    if target not in existing:
        raise ValueError("첨부되지 않은 사진입니다.")
    new_paths = [p for p in existing if p != target]
    snapshot = current.get("updated_at")  # P1-3 CAS 토큰

    if is_sample_mode():
        ok = _sample_update_near_miss(
            report_id, expected_status=_NEAR_MISS_EDITABLE_STATUS,
            owner_emp_no=actor["emp_no"], expected_photo_paths=existing,
            photo_paths=new_paths,
        )
        if not ok:
            raise ValueError(_NEAR_MISS_STALE_MESSAGE)
        _near_miss_photo_store().pop(target, None)
        return {"photo_paths": new_paths, "storage_deleted": True}

    try:
        updated = supabase_repository.set_near_miss_photo_paths(
            report_id, new_paths, reporter_emp_no=actor["emp_no"],
            expected_updated_at=snapshot, updated_by=actor["emp_no"],
        )
    finally:
        _invalidate_near_miss()
    # 참조 제거(CAS) 성공 후 객체 삭제. 실패는 은폐하지 않고 부분성공으로 표면화(P1-4).
    storage_deleted = True
    try:
        supabase_repository.remove_near_miss_photo_object(target)
    except Exception:  # noqa: BLE001 — 객체 삭제 실패 = 고아 객체(표시 무결성엔 영향 없음).
        storage_deleted = False
        _LOG.warning(
            "near-miss photo storage delete failed (reference removed, object orphaned): "
            "report_id=%s object=%s", report_id, target,
        )
    return {
        "photo_paths": list((updated or {}).get("photo_paths") or new_paths),
        "storage_deleted": storage_deleted,
    }


def update_near_miss_status(
    report_id, status: str, *, rejection_reason=None, current_user=None, updated_by=None,
) -> dict | None:
    """아차사고 상태를 전이 규칙에 맞게 변경한다.

    행위자 신원은 payload/위젯이 아니라 인증된 ``current_user``(세션 사용자,
    auth.get_current_user() 반환값)에서 **서버측으로 확정**한다 — 무인증·사번 미상·
    비활성 사용자는 DB 요청 전에 ValueError 로 차단한다(``updated_by`` 폴백 없음).

    **전이별 인가**(docs/database.md §8 행위자 계약):
      - ``REJECTED→SUBMITTED`` 재개: 보고서 소유자(보고자 사번 일치) **또는** 평가
        능력(can_evaluate_near_miss)이면 허용.
      - 그 외 모든 전이(SUBMITTED→*, IN_REVIEW→*, EVALUATED→*): 평가 능력
        (can_evaluate_near_miss) 필수. 인증된 일반 USER 라도 능력이 없으면 차단한다.
    인가 판정은 auth.can_evaluate_near_miss(actor) 단일 SoT 를 쓰며 db 에 능력 규칙을
    중복 구현하지 않는다. 게이트가 파사드 상단이라 sample/supabase 계약이 동일하다.

    허용되지 않은 전이·반려 사유 누락은 ValueError. 평가상태(EVALUATED/CLOSED)를
    벗어나면 평가 필드를 함께 초기화한다(DB 제약 충족). 전이는 읽은 현재 상태를
    기대값으로 하는 원자적 조건부 UPDATE 로 수행하며, 그 사이 다른 사용자가 먼저
    상태를 바꿨으면(TOCTOU) 덮어쓰지 않고 stale 오류를 낸다. 감사(updated_by)는
    인증된 세션 행위자 사번으로 확정한다(``updated_by`` 인자는 하위호환용으로 남기되
    무시한다 — 위조 방지).
    """
    target = str(status).strip()
    if target not in NEAR_MISS_STATUSES:
        raise ValueError(f"유효하지 않은 상태입니다: {target}")
    # 평가확정(EVALUATED)은 이 경로로 만들 수 없다(Codex P2-2). 여기서는 확정등급·
    # 평가자·평가시각을 세팅하지 않으므로, 허용하면 sample 은 불완전 EVALUATED 저장,
    # supabase 는 near_miss_eval_consistency 제약 위반이 된다. EVALUATED 전이는
    # evaluate_near_miss 전용으로 강제한다(전이표 SUBMITTED/IN_REVIEW→EVALUATED 는
    # evaluate_near_miss 가 소비하므로 표는 그대로 두고 진입부에서만 차단한다).
    # evaluate_near_miss 는 이 파사드를 재사용하지 않고 직접 원자 UPDATE 하므로 이
    # 차단이 정상 평가 경로를 막지 않는다.
    if target == "EVALUATED":
        raise ValueError("평가 확정은 evaluate_near_miss 로만 가능합니다.")
    # 종결(CLOSED)도 이 경로로 만들 수 없다(007, Codex round-2 P1-#2). 종결은 확인된
    # 활성 개선조치를 요구하는 하드게이트(close_near_miss_report/RPC/trigger)로만 가능하다.
    # EVALUATED 차단과 같은 방식으로 진입부에서 거부한다(무인증 호출도 동일 사유로 거부).
    if target == "CLOSED":
        raise ValueError(
            "종결(CLOSED)은 close_near_miss_report 로만 가능합니다. "
            "확인(CONFIRMED)된 개선조치가 있어야 종결할 수 있습니다."
        )
    # 인증·권위 재조회 강제(무인증/사번 미상/비활성 → DB 요청 전 ValueError).
    actor = _near_miss_actor(current_user, action="아차사고 상태 변경")
    current = get_near_miss_report(report_id)
    if current is None:
        raise ValueError(f"아차사고 보고서를 찾을 수 없습니다: {report_id}")
    cur_status = str(current.get("status") or "").strip()
    # 허용표(NEAR_MISS_TRANSITIONS)는 어떤 상태도 자기 자신을 포함하지 않는다. 동일상태
    # 재호출(REJECTED→REJECTED 로 반려사유 덮어쓰기, CLOSED→CLOSED 무효 재실행 등)은
    # 정상 사용자 플로우가 아니라 경합(동시클릭/TOCTOU) 시나리오이므로 여기서 일괄
    # 차단한다 — cur==target 을 예외 취급하지 않고 그대로 허용표 검사를 받게 한다.
    if not near_miss_transition_allowed(cur_status, target):
        raise ValueError(f"허용되지 않은 상태 전이입니다: {cur_status} → {target}")
    # 보완요청(반송, IN_REVIEW→SUBMITTED)은 이 일반 경로로 만들 수 없다. 반송은 전용
    # 사유(revision_request 3필드)를 서버측으로 기록해야 하며 사유 없는 반송은 만들지
    # 않는다 — request_near_miss_revision 전용 파사드로만 가능하게 한다(EVALUATED/CLOSED
    # 를 전용 경로로 강제하는 것과 같은 관행). REJECTED→SUBMITTED(재개/재제출)는 →SUBMITTED
    # 지만 소스가 REJECTED 라 여기서 걸리지 않고 그대로 허용된다(보고자 본인 경로 포함).
    if cur_status == "IN_REVIEW" and target == "SUBMITTED":
        raise ValueError(_NEAR_MISS_REVISION_VIA_FACADE_MESSAGE)
    if target == "REJECTED" and not str(rejection_reason or "").strip():
        raise ValueError("반려하려면 반려 사유가 필요합니다.")
    # 전이별 서버측 인가. REJECTED→SUBMITTED 재개만 보고자 소유자에게도 열려 있고,
    # 그 외 전이는 평가 능력이 필수다. 능력 판정은 auth 단일 SoT 로 위임한다.
    from modules import auth  # 지연 import(순환 회피, Codex P2)
    if cur_status == "REJECTED" and target == "SUBMITTED":
        owner = str(current.get("reporter_emp_no") or "").strip()
        # 소유자 비교는 권위 사번 원본끼리의 정확 일치(trim only) — 수정/생성 경로와 동일.
        if not (owner == actor["emp_no"] or auth.can_evaluate_near_miss(actor)):
            raise ValueError(_NEAR_MISS_NOT_AUTHORIZED_MESSAGE)
    elif not auth.can_evaluate_near_miss(actor):
        raise ValueError(_NEAR_MISS_NOT_AUTHORIZED_MESSAGE)
    clear_eval = target not in _NEAR_MISS_EVAL_STATES
    reason = str(rejection_reason).strip() if target == "REJECTED" else None
    # 감사 귀속은 인증된 세션 행위자 사번으로 확정한다(폴백 없음, 위조 방지).
    attribution = actor["emp_no"]
    # 재개(EVALUATED→IN_REVIEW): report 평가필드 초기화(clear_eval)와 함께 확인된
    # 개선조치도 CONFIRMED→PENDING 으로 되돌린다(확인 근거가 재개 후에도 남지 않게 — 007).
    reopening = cur_status == "EVALUATED" and target == "IN_REVIEW"
    if is_sample_mode():
        # 재개는 report 전이(clear_eval) + 확인 개선조치 초기화의 2단계다. sample 은 세션-로컬
        # dict 라 완전 트랜잭션이 불가하므로 best-effort 롤백으로 부분성공을 막는다(Codex P2):
        # report 변경 전 스냅샷을 떠 두고, CAPA 리셋이 실패하면 report 를 재개 이전으로 원복한다.
        # 완전 원자성은 아니다(주석 명시) — supabase 만 원자 RPC 로 보장한다.
        snapshot = get_near_miss_report(report_id) if reopening else None
        ok = _sample_update_near_miss(
            report_id, expected_status=cur_status, clear_eval=clear_eval,
            status=target, rejection_reason=reason,
        )
        if not ok:
            raise ValueError(_NEAR_MISS_STALE_MESSAGE)
        if reopening:
            try:
                _nmi_sample_reset_on_reopen(report_id)
            except Exception:
                if snapshot is not None:
                    _sample_restore_near_miss(report_id, snapshot)
                raise
        return get_near_miss_report(report_id)
    try:
        # 재개(EVALUATED→IN_REVIEW)는 report 전이 + 확인 개선조치 초기화를 원자 RPC 로 묶는다
        # (Codex P1-4). 과거의 '전이 후 별도 리셋' 2단계가 남기던 stale CONFIRMED 재사용 창을
        # 없앤다. readiness 는 3-state 로 판정한다(P1-2 fail-open 제거):
        #   READY      → 원자 reopen RPC(확인 개선조치 CONFIRMED→PENDING 초기화 포함)
        #   NOT_READY  → 007 미적용이라 초기화할 개선조치가 없음 → 일반 EVALUATED→IN_REVIEW
        #   PROBE_ERROR→ 준비상태 불명(일시/네트워크/권한). 여기서 일반 UPDATE 로 빠지면 007
        #                적용 환경에서 CAPA 리셋을 건너뛰는 fail-open 이므로 전파(fail-closed).
        # RPC 오류는 조용히 건너뛰지 않고 전파한다(중간 실패 은폐 금지).
        if reopening:
            probe = near_miss_improvement_schema_probe()
            if probe == READINESS_PROBE_ERROR:
                raise supabase_repository.SupabaseDataError(
                    _NEAR_MISS_REOPEN_PROBE_ERROR_MESSAGE
                )
            if probe == READINESS_READY:
                return supabase_repository.reopen_near_miss_report(
                    report_id, actor_emp_no=attribution
                )
            # NOT_READY: 007 미적용 — 초기화 대상 개선조치가 없어 일반 전이로 진행한다.
        return supabase_repository.update_near_miss_status(
            report_id, target, expected_status=cur_status, rejection_reason=reason,
            clear_evaluation=clear_eval, updated_by=attribution,
        )
    finally:
        _invalidate_near_miss()


def request_near_miss_revision(report_id, reason: str, *, current_user) -> dict | None:
    """보완요청(반송): IN_REVIEW→SUBMITTED 로 되돌리며 보완 사유를 서버측으로 기록한다.

    반려(REJECTED, 종결분기)와 의미가 다르며 ``rejection_reason`` 을 재사용하지 않는다.
    보완요청은 보고자에게 재작성을 요청하는 것이고, 반려는 종결(폐기) 분기다.

    - 보완 사유(``reason``)는 필수다(빈값이면 ValueError) — 사유 없는 반송은 만들지 않는다.
    - 요청자(revision_requested_by)·요청시각은 payload/위젯이 아니라 인증된 ``current_user``
      에서 **서버측 확정**한다(위조 무시). 인가는 평가 능력(auth.can_evaluate_near_miss)
      이 필수다(화면 게이트를 계약으로 승격).
    - 보완요청은 검토중(IN_REVIEW)에서만 가능하다. 재개(EVALUATED→IN_REVIEW)와는 다른 전이다.
    - supabase 는 007 보완요청 컬럼이 준비된 경우에만 기록한다. 미적용/probe 오류면
      fail-closed 로 차단한다(사유를 저장할 수 없는 상태에서 반송만 만들지 않음).
    """
    reason_text = str(reason or "").strip()
    if not reason_text:
        raise ValueError("보완요청을 하려면 보완 사유가 필요합니다.")
    actor = _near_miss_actor(current_user, action="아차사고 보완요청")
    current = get_near_miss_report(report_id)
    if current is None:
        raise ValueError(f"아차사고 보고서를 찾을 수 없습니다: {report_id}")
    cur_status = str(current.get("status") or "").strip()
    if cur_status != "IN_REVIEW":
        raise ValueError(
            f"보완요청(반송)은 검토중(IN_REVIEW) 상태에서만 가능합니다: 현재 {cur_status}"
        )
    from modules import auth  # 지연 import(순환 회피)
    if not auth.can_evaluate_near_miss(actor):
        raise ValueError(_NEAR_MISS_NOT_AUTHORIZED_MESSAGE)
    requester = actor["emp_no"]  # 서버귀속(위조 requested_by 무시)
    if is_sample_mode():
        ok = _sample_update_near_miss(
            report_id, expected_status=cur_status, clear_eval=True, status="SUBMITTED",
        )
        if not ok:
            raise ValueError(_NEAR_MISS_STALE_MESSAGE)
        _nm_sample_record_revision(report_id, reason_text, requester)
        return get_near_miss_report(report_id)
    # supabase: 007 보완요청 컬럼이 있어야 사유를 기록할 수 있다. 3-state fail-closed —
    # NOT_READY(미적용)·PROBE_ERROR(불명) 모두 차단해 사유 없는 반송을 막는다.
    if near_miss_improvement_schema_probe() != READINESS_READY:
        raise supabase_repository.SupabaseDataError(_NEAR_MISS_REVISION_NOT_READY_MESSAGE)
    try:
        return supabase_repository.request_near_miss_revision(
            report_id, reason_text, requester_emp_no=requester, expected_status=cur_status,
        )
    finally:
        _invalidate_near_miss()


def evaluate_near_miss(
    report_id, confirmed_grade: str, *, current_user, updated_by=None,
) -> dict | None:
    """평가 확정: status=EVALUATED + 확정등급/평가자/평가시각 설정.

    평가자(evaluator)·평가시각은 payload/위젯이 아니라 인증된 ``current_user``에서
    **서버측으로 확정**한다 — 다른 사람이 평가한 것처럼 위조하는 것을 막는다. 평가는
    평가 능력(auth.can_evaluate_near_miss — ADMIN/MANAGER/안전담당자)이 서버측에서
    필수이며, 인증된 일반 USER 가 파사드를 직접 호출해도 차단한다(화면 게이트를 계약으로
    승격). 확정 등급 유효성을 검증하고, 보고서가 **평가 이전 상태(SUBMITTED/IN_REVIEW)**
    일 때만 평가한다.
    이미 평가/종결된 보고서(EVALUATED/CLOSED)는 재평가로 덮어쓸 수 없으며 stale 오류를
    낸다. 읽은 현재 상태를 기대값으로 하는 원자적 조건부 UPDATE 로 확정하므로 두 평가자가
    동시에 확정해도 하나만 성공하고 다른 하나는 '상태가 이미 변경됨'을 받는다.
    """
    grade = str(confirmed_grade).strip().upper()
    if grade not in NEAR_MISS_GRADES:
        raise ValueError(f"확정 등급이 유효하지 않습니다: {grade}")
    actor = _near_miss_actor(current_user, action="아차사고 평가")
    # 서버측 능력 게이트: 평가확정은 평가자(ADMIN/MANAGER/안전담당자)만. 화면 게이트를
    # 계약으로 승격한다(인증된 일반 USER 가 파사드를 직접 호출해도 차단). auth 단일 SoT.
    from modules import auth  # 지연 import(순환 회피, Codex P2)
    if not auth.can_evaluate_near_miss(actor):
        raise ValueError(_NEAR_MISS_NOT_AUTHORIZED_MESSAGE)
    evaluator = actor["emp_no"]
    current = get_near_miss_report(report_id)
    if current is None:
        raise ValueError(f"아차사고 보고서를 찾을 수 없습니다: {report_id}")
    cur_status = str(current.get("status") or "").strip()
    # 평가 이전 상태에서만 확정 가능. 이미 EVALUATED/CLOSED 면 재평가 덮어쓰기를 막는다.
    if cur_status not in _NEAR_MISS_PRE_EVAL_STATES:
        raise ValueError(_NEAR_MISS_STALE_MESSAGE)
    # 평가 귀속(updated_by)은 세션 평가자로 확정한다(서버측).
    attribution = evaluator
    if is_sample_mode():
        ok = _sample_update_near_miss(
            report_id, expected_status=cur_status, status="EVALUATED",
            confirmed_grade=grade, evaluator_emp_no=evaluator,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
        )
        if not ok:
            raise ValueError(_NEAR_MISS_STALE_MESSAGE)
        return get_near_miss_report(report_id)
    try:
        return supabase_repository.evaluate_near_miss(
            report_id, grade, evaluator_emp_no=evaluator,
            expected_status=cur_status, updated_by=attribution,
        )
    finally:
        _invalidate_near_miss()


def set_near_miss_active(
    report_id, is_active: bool, *, current_user=None, updated_by=None
) -> None:
    """보존(archival) 플래그 토글. 철회/반려는 상태로 표현하며 이 경로가 아니다.

    ``current_user`` 는 감사(updated_by) 귀속에 쓰인다(세션 사용자, 위젯 값 아님).
    """
    attribution = _near_miss_updated_by(current_user) or updated_by
    if is_sample_mode():
        _sample_update_near_miss(report_id, is_active=bool(is_active))
        return
    try:
        supabase_repository.set_near_miss_active(
            report_id, bool(is_active), updated_by=attribution
        )
    finally:
        _invalidate_near_miss()


def near_miss_stats(by: str = "status", filters: dict | None = None) -> dict:
    """아차사고 통계 집계(by = grade|dept|period|cause|status). {키: 건수} 반환.

    두 모드 모두 같은 자연키 프레임에서 집계하므로 결과 계약이 일치한다.
    """
    df = get_near_miss_reports(filters)
    return supabase_repository._aggregate_near_miss(df.to_dict("records"), by)


# --- 아차사고 개선조치(CAPA) — migration 007 (DRAFT: 실행/원격 write 승인 게이트 전) ---
# 보고서 1건당 개선조치 1건(1:1). 등록/제출/확인/반려 라이프사이클과 확인+종결 하드게이트
# 를 데이터 계층에서 강제한다. sample 모드는 세션 스토어에서 DB CHECK/자기확인/하드게이트/
# 강등방어 규칙을 파이썬으로 동일 재현하고(오류 은폐 금지), supabase 모드는 007 테이블·
# RPC·trigger 로 강제한다. 신원·인가는 아차사고 보고 경로(P1-a)와 같은 패턴을 미러한다.
NEAR_MISS_IMPROVEMENT_COLUMNS = supabase_repository.NEAR_MISS_IMPROVEMENT_COLUMNS
_NEAR_MISS_IMPROVEMENT_STORE = "store_near_miss_improvements"
# sample 모드 보완요청(revision_request) 세션-로컬 저장소(report_id→사유/요청자/시각).
# supabase 는 near_miss_reports 의 revision_request_* 컬럼(007)에 기록하므로 read 계약이
# NEAR_MISS_COLUMNS 에 아직 노출되지 않는다(표시는 UI 소관 — BACKLOG defer). 저장 위치만
# 모드별로 다르고 파사드 뒤로 감춰지며, 서버귀속·사유필수 동작은 두 모드가 일치한다.
_NEAR_MISS_REVISION_STORE = "store_near_miss_revision_requests"


def _nm_revision_store() -> dict:
    """sample 보완요청 backing store(report_id→revision_request 자연키, 세션 유지)."""
    if _NEAR_MISS_REVISION_STORE not in st.session_state:
        st.session_state[_NEAR_MISS_REVISION_STORE] = {}
    return st.session_state[_NEAR_MISS_REVISION_STORE]


def _nm_sample_record_revision(report_id, reason: str, requester_emp_no: str) -> None:
    """sample: 보완요청 사유·요청자·요청시각을 서버측 값으로 기록(위조 무시는 파사드가 보장)."""
    _nm_revision_store()[str(report_id)] = {
        "revision_request_reason": str(reason),
        "revision_requested_by_emp_no": str(requester_emp_no),
        "revision_requested_at": datetime.now(timezone.utc).isoformat(),
    }


def _sample_restore_near_miss(report_id, snapshot: dict) -> None:
    """sample 재개 best-effort 롤백: report 를 스냅샷(재개 이전)의 상태/평가필드로 원복한다.

    CAPA 리셋 실패 시에만 호출된다 — 부분성공(report 만 IN_REVIEW, CAPA CONFIRMED 잔존)을
    막기 위한 보상이며 완전 원자성은 아니다(세션-로컬 dict 한계)."""
    _sample_update_near_miss(
        report_id,
        status=snapshot.get("status"),
        confirmed_grade=snapshot.get("confirmed_grade"),
        evaluator_emp_no=snapshot.get("evaluator_emp_no"),
        evaluated_at=snapshot.get("evaluated_at"),
        allow_null=("confirmed_grade", "evaluated_at"),
    )


def get_near_miss_revision_request(report_id) -> dict | None:
    """보고서의 마지막 보완요청(사유/요청자 사번/요청시각) 또는 None. 표시용(읽기).

    sample 은 세션 저장소에서, supabase 는 007 컬럼에서 읽는다. 007 미적용이면 None."""
    if is_sample_mode():
        rec = _nm_revision_store().get(str(report_id))
        return dict(rec) if rec else None
    return supabase_repository.get_near_miss_revision_request(report_id)

# 클라이언트(화면)가 payload 로 보내도 파사드가 무시하고 서버측에서만 확정하는 필드.
# 실제 확인/반려 행위자·시각·상태·감사는 위조할 수 없다(서버 귀속).
_NEAR_MISS_IMPROVEMENT_SERVER_FIELDS = frozenset({
    "id", "report_id", "submit_status", "confirm_status",
    "submitted_at", "confirmed_at", "confirmed_by_emp_no", "confirmed_by_user_id",
    "rejected_at", "rejected_by_emp_no", "rejected_by_user_id",
    "is_active", "created_by", "updated_by", "created_at", "updated_at",
})

# 배정 전용 필드(담당자·지정 확인자). 배정·재배정은 평가자/ADMIN 전용 명령이며, 조치
# 담당자의 작업(upsert/submit) 경로에서는 payload 로 와도 무시된다(재지정 차단) — 담당자가
# 자신을 다른 사람으로 바꾸거나 확인자를 조작하지 못하게 봉함한다(CAPA 행단위 인가 핵심).
_NEAR_MISS_IMPROVEMENT_ASSIGN_FIELDS = ("assignee_emp_no", "designated_confirmer_emp_no")

# 작업(조치) 전용 필드. 저장·제출 경로에서 배정된 담당자·ADMIN 만 수정할 수 있으며, 배정
# 권한만 있는 비담당자 평가자(MANAGER 등)의 payload 로 오면 무시된다(배정 branch 는 작업
# 본문을 건드리지 않는다 — CAPA 배정/작업 branch 완전분리). present-only 병합이므로 payload
# 에 없는 작업 필드는 빈값으로 덮어쓰지 않고 기존 값을 보존한다.
_NEAR_MISS_IMPROVEMENT_WORK_FIELDS = ("action_body", "result_body", "due_date")

_NEAR_MISS_IMPROVEMENT_CONFIRMED = "CONFIRMED"
_NEAR_MISS_IMPROVEMENT_NO_CAPA_MESSAGE = (
    "확인(CONFIRMED)된 활성 개선조치가 없어 종결할 수 없습니다. "
    "개선조치를 등록·제출하고 확인을 받은 뒤 종결하세요."
)
# 조치 저장·제출(작업 필드) 인가 실패 — 저장된 배정 담당자 본인 또는 ADMIN 만 가능하다.
_NEAR_MISS_IMPROVEMENT_NOT_ASSIGNEE_MESSAGE = (
    "이 개선조치를 저장·제출할 권한이 없습니다. 배정된 조치 담당자 본인 또는 관리자만 "
    "조치 필드를 수정·제출할 수 있습니다."
)
# 확인·재조치 요청·종결(검토 행위) 인가 실패 — 지정 확인자 또는 평가자 또는 ADMIN 만 가능.
_NEAR_MISS_IMPROVEMENT_NOT_REVIEWER_MESSAGE = (
    "이 개선조치를 확인·재조치 요청·종결할 권한이 없습니다. 지정 확인자 또는 평가자"
    "(관리자·매니저·안전담당자)만 검토 행위를 할 수 있습니다."
)
# 미배정 상태에서 담당자가 조치를 저장하려 할 때 — 배정이 선행돼야 한다(평가자/ADMIN).
_NEAR_MISS_IMPROVEMENT_NOT_ASSIGNED_MESSAGE = (
    "개선조치가 아직 배정되지 않았습니다. 평가자·관리자가 조치 담당자를 먼저 배정해야 "
    "조치를 저장할 수 있습니다."
)
# 조회~쓰기 사이 재배정 경합으로 조건부 UPDATE(담당자=행위자)가 0행이 된 경우.
_NEAR_MISS_IMPROVEMENT_REASSIGNED_MESSAGE = (
    "배정이 이미 변경되어 요청을 적용할 수 없습니다(다른 담당자로 재배정됨). "
    "목록을 재조회한 뒤 다시 시도하세요."
)


def near_miss_improvement_schema_ready() -> bool:
    """007 개선조치 스키마 사용 가능 여부. sample 은 항상 True."""
    if is_sample_mode():
        return True
    return supabase_repository.near_miss_improvement_extensions_ready()


def near_miss_improvement_schema_probe(*, force: bool = False) -> str:
    """007 개선조치 스키마 준비 상태 3-state(배너/재확인 UX 용). near_miss_schema_probe 관행 복제.

    반환: READINESS_READY / READINESS_NOT_READY(미적용) / READINESS_PROBE_ERROR(확인 실패).
    sample 은 항상 READY."""
    if is_sample_mode():
        return supabase_repository.READINESS_READY
    return supabase_repository.near_miss_improvement_extensions_probe(force=force)


def _nmi_store() -> dict:
    """sample 모드 개선조치 backing store(report_id→자연키 레코드, 세션 유지·실DB 미변경)."""
    if _NEAR_MISS_IMPROVEMENT_STORE not in st.session_state:
        st.session_state[_NEAR_MISS_IMPROVEMENT_STORE] = {}
    return st.session_state[_NEAR_MISS_IMPROVEMENT_STORE]


def _nmi_sample_work_body(payload: dict, *, present_only: bool) -> dict:
    """개선조치 **작업 필드**(조치 내용/결과/기한)만 검증·정규화한다(신원/상태/배정 제외).

    배정 필드(담당자·확인자)는 여기 포함하지 않는다 — 작업(upsert/submit) 경로와 배정
    경로를 분리하기 위해서다(supabase `_near_miss_improvement_work_body` 미러).
    ``present_only=True`` 면 payload 에 실제로 존재하는 키만 반환한다(키 부재=작업 미변경/
    보존). ``False`` 면 세 필드를 모두 기본값으로 반환한다(생성 시 초기값). 부분 upsert 가
    payload 에 없는 작업 필드를 빈값/NULL 로 덮어써 기존 조치·결과·기한을 지우지 않게 한다."""
    payload = dict(payload or {})
    out: dict = {}
    if not present_only or "action_body" in payload:
        out["action_body"] = str(payload.get("action_body") or "")
    if not present_only or "result_body" in payload:
        out["result_body"] = str(payload.get("result_body") or "")
    if not present_only or "due_date" in payload:
        due = str(payload.get("due_date") or "").strip()
        if due:
            date.fromisoformat(due)  # 형식 오류 시 ValueError
        out["due_date"] = due or None
    return out


def _nmi_sample_resolve_assignment(payload: dict) -> dict:
    """배정 필드(담당자·확인자)를 **payload 에 실제로 존재하는 키만** 검증·정규화한다.

    키 부재 = 배정 미변경(보존), 빈 값 = 해제. 권위 사번(DB 원본 표기)으로 정규화해 저장
    한다(대소문자만 다른 입력이 자기확인 비교를 우회하지 못하게 — 비교도 casefold 로 이중
    방어). supabase `_near_miss_improvement_assign_body(present_only=True)` 미러."""
    payload = dict(payload or {})

    def resolve(emp_key):
        emp = str(payload.get(emp_key) or "").strip()
        if not emp:
            return ""
        found = find_user_by_emp_no(emp)
        if found is None:
            raise ValueError(f"사용자 사번을 찾을 수 없습니다: {emp}")
        return str(found.get("emp_no") or emp).strip()

    out: dict = {}
    for emp_key in _NEAR_MISS_IMPROVEMENT_ASSIGN_FIELDS:
        if emp_key in payload:
            out[emp_key] = resolve(emp_key)
    return out


def _nmi_new_id(store: dict) -> int:
    ids = [int(r["id"]) for r in store.values() if str(r.get("id") or "").isdigit()]
    return (max(ids) + 1) if ids else 1


def _nmi_sample_reset_on_reopen(report_id) -> None:
    """sample: report 재개 시 확인된 개선조치를 CONFIRMED→PENDING 초기화(결과/기한 보존)."""
    store = _nmi_store()
    rec = store.get(str(report_id))
    if rec is None or rec.get("confirm_status") != _NEAR_MISS_IMPROVEMENT_CONFIRMED:
        return
    rec = dict(rec)
    rec.update({
        "confirm_status": "PENDING",
        "confirmed_by_emp_no": "",
        "confirmed_at": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    store[str(report_id)] = rec


def _near_miss_improvement_raw(report_id) -> dict | None:
    """보고서의 개선조치 원본(스코핑 없음) 또는 None — **내부 인가 판정·집계 전용**.

    이 헬퍼는 actor-aware 스코핑을 적용하지 않는다. "unscoped 가 실수가 아니라 의도"임을
    이름과 위치로 드러내려고 별도 private 함수로 분리했다. 사용자에게 노출되는 조회 경로는
    반드시 ``get_near_miss_improvement(current_user=...)`` / ``list_near_miss_improvements
    (current_user=...)`` 를 쓴다(actor 필수·필터링). 이 raw 조회는 파사드 내부의 인가 판정
    (담당자/확인자/상태 확인)이나 명시적 권한 게이트를 통과한 집계(예: 평가자 전용 CAPA
    기한초과)에서만 호출한다 — 각 호출부가 자체 인가를 별도로 강제한다."""
    if is_sample_mode():
        rec = _nmi_store().get(str(report_id))
        return dict(rec) if rec else None
    return supabase_repository.get_near_miss_improvement(report_id)


def get_near_miss_improvement(report_id, *, current_user) -> dict | None:
    """보고서의 개선조치(자연키 dict) 또는 None — **actor-aware 스코핑(current_user 필수)**.

    인증 행위자가 이 개선조치의 저장된 담당자·지정 확인자·평가자·ADMIN 중 하나가 아니면
    None 을 돌려준다(권한 없음 = 미노출). report_id 를 클라이언트가 넘겼다는 이유만으로
    조회를 허용하지 않는다. ``current_user`` 는 필수다 — default None fail-open 을 제거해
    스코핑 없는 노출을 봉했다. 스코핑 없는 원본이 필요한 내부 판정·집계는 명시적으로
    ``_near_miss_improvement_raw`` 를 쓴다(의도된 unscoped).

    **존재 여부 oracle 봉함**: 행위자 확정(actor 확정)을 raw 조회보다 먼저 하고, 미인증/
    미상/비활성 actor 는 개선조치의 존재 여부와 무관하게 None 을 돌려준다(예외 전파 금지).
    이전에는 raw 조회를 먼저 해 부재는 None, 존재는 actor 확정 예외로 갈려 "CAPA 있음→예외/
    없음→None" 존재 oracle 이 됐다. 이제 **authorized+present 만 행을 반환**하고, 그 외
    (부재 OR 미인가)는 모두 None 이라 미인가 접근자가 존재 여부를 구분할 수 없다. actor
    확정 실패(current_user 결여·미상 사번·비활성)는 예외 대신 None 으로 접는다 — 이 공개
    getter 는 내부 인가·집계에 쓰이지 않으므로(그건 ``_near_miss_improvement_raw`` 전용)
    미인가=None 이 내부 로직에 영향을 주지 않는다."""
    from modules import auth  # 지연 import(순환 회피)
    try:
        actor = _near_miss_actor(current_user, action="개선조치 조회")
    except ValueError:
        # 미인증/미상/비활성 actor: 존재 여부를 누설하지 않도록 부재와 동일하게 None.
        return None
    imp = _near_miss_improvement_raw(report_id)
    if imp is None:
        return None
    return imp if auth.can_access_improvement(actor, imp) else None


def list_near_miss_improvements(report_ids, *, current_user) -> dict:
    """report_id 목록의 개선조치를 report_id(str)→자연키 dict 로 반환한다(큐 enrich 용).

    **actor-aware 큐 스코핑(current_user 필수)**: 권한자(평가자/ADMIN)는 전체를, 그 외 인증
    사용자는 자신이 저장된 담당자이거나 지정 확인자인 개선조치만 본다. 미배정/조회 None 은
    결과에서 빠진다. current_user 는 필수다(fail-open 제거) — 스코핑 없는 전량 조회가
    필요한 내부·집계 경로는 명시적으로 ``_near_miss_improvement_raw`` 를 순회한다."""
    from modules import auth  # 지연 import(순환 회피)
    actor = _near_miss_actor(current_user, action="개선조치 조회")
    out: dict = {}
    for rid in (report_ids or []):
        imp = _near_miss_improvement_raw(rid)  # 스코핑 없이 원본 조회 후 actor 필터
        if imp is None:
            continue
        if auth.can_access_improvement(actor, imp):
            out[str(rid)] = imp
    return out


def _has_active_improvement_assignment(actor: dict) -> bool:
    """행위자가 담당자 또는 지정 확인자인 **활성** 개선조치가 1건 이상인지(가벼운 존재확인).

    sample 은 세션 store 를 순회하며 활성 레코드에 대해 ``auth.can_access_improvement``
    (비평가 분기 = 담당자/지정 확인자 정확 일치)로 판정해 매칭 로직 중복을 피하고, supabase
    는 리포지토리 경량 count 쿼리(``has_active_improvement_assignment``)에 위임한다. 평가자/
    ADMIN 단축은 호출부(``has_near_miss_improvement_access``)에서 이미 처리하므로, 여기 도달
    하는 actor 는 사실상 비평가 USER 다. 스코핑 없는 원본이 필요하나 행을 노출하지는 않는다."""
    from modules import auth  # 지연 import(순환 회피)
    if is_sample_mode():
        for rec in _nmi_store().values():
            if not auth._as_bool(rec.get("is_active", True)):
                continue
            if auth.can_access_improvement(actor, rec):
                return True
        return False
    return supabase_repository.has_active_improvement_assignment(actor.get("emp_no"))


def has_near_miss_improvement_access(current_user) -> bool:
    """개선조치 화면 진입·nav 메뉴 노출 판정(접근 가능 여부만 반환, 행 노출 아님).

    True 조건:
      - ADMIN 또는 평가 능력자(``auth.can_evaluate_near_miss``), 또는
      - 007(개선조치 스키마) READY 이고, 이 행위자가 저장된 담당자(assignee) 또는 지정
        확인자(designated_confirmer)인 **활성** 개선조치가 1건 이상 존재.

    신원은 ``_near_miss_actor`` 로 서버측 확정한다(세션 role 위조 무시, uncached 권위 읽기·
    is_active 재확인). current_user 결여·미상 사번·비활성이면 False(fail-closed). 평가자/
    ADMIN 은 배정 조회 없이 즉시 True(단축) — 매 렌더 nav 호출의 쿼리 비용을 없앤다.

    007 준비 판정: NOT_READY(미적용)면 배정 기반 부분은 False — 미적용 환경에선 평가자/
    ADMIN 만 True 로, 현재 nav capability 게이트(CAP_EVALUATE_NEAR_MISS)와 정합한다(개선조치
    자체가 fail-closed 라 담당자에게 메뉴를 열어도 쓸 게 없다). **PROBE_ERROR(일시 확인 실패)도
    여기서는 False(안전·비크래시)로 접는다** — 이 함수는 매 렌더 nav 게이트라 예외를 올리면
    사이드바가 크래시한다. 평가자/ADMIN 은 probe 이전에 이미 True 라 일시 오류의 영향을 받지
    않고, 담당자는 장애 동안 메뉴가 잠깐 숨을 뿐 기능 손실이 없다(화면 진입 후 개별 조회의
    read_gate 가 여전히 오류를 배너로 표면화한다). 배정 존재 조회 자체가 실패해도 False 로
    접어 nav 를 크래시시키지 않는다. **actor 권위 조회(_near_miss_actor)의 일시 데이터소스
    오류(DATA_SOURCE_ERRORS)도 여기서는 False 로 접는다** — 무인증(ValueError)만 잡던 과거
    구현은 데이터소스 오류를 전파해 caps 계산·CAPA 무관 화면까지 크래시시켰다(P2)."""
    from modules import auth  # 지연 import(순환 회피)
    try:
        actor = _near_miss_actor(current_user, action="개선조치 접근 판정")
    except (ValueError, *DATA_SOURCE_ERRORS):
        # 무인증/미상 사번/비활성(ValueError)뿐 아니라 actor 권위 조회의 일시 데이터소스
        # 오류(DATA_SOURCE_ERRORS)도 여기서는 False(비크래시)로 접는다. 이 함수는 매 렌더
        # nav/route 게이트라 예외를 올리면 caps 계산이 크래시해 CAPA 무관 화면까지 렌더가
        # 죽는다. nav 는 배너를 못 띄우는 boolean 게이트라 "오류≈미배정" 병합이 불가피하다:
        # 개선조치 화면에 도달한 평가자에겐 개별 조회의 load_failed 배너가 여전히 오류를
        # 표면화하고, 담당자는 장애 동안 메뉴만 잠깐 사라질 뿐 기능 손실은 없다(장애 해소 시
        # 복귀). 이 트레이드오프(nav boolean 게이트의 오류-미배정 병합)는 BACKLOG 에 KNOWN.
        return False
    if auth.can_evaluate_near_miss(actor):
        return True  # 평가자/ADMIN: 배정 조회 없이 단축.
    # 배정 기반은 007 READY 일 때만. NOT_READY·PROBE_ERROR 는 배정 부분 False(안전).
    if near_miss_improvement_schema_probe() != READINESS_READY:
        return False
    try:
        return _has_active_improvement_assignment(actor)
    except Exception:
        return False  # nav 게이트: 배정 조회 실패 시 안전(False)·비크래시.


def upsert_near_miss_improvement(report_id, payload: dict, *, current_user) -> dict:
    """개선조치를 DRAFT 로 저장한다. **배정 필드와 작업 필드를 인가로 분리**한다(CAPA 핵심).

    행위자 신원은 payload/위젯이 아니라 인증된 ``current_user``에서 서버측 확정한다
    (무인증/비활성 차단). **배정 branch 와 작업 branch 가 인가·필드 모두 완전분리**된다:
      - 배정 branch(주체 can_assign=평가자/ADMIN): 배정 필드(담당자·지정 확인자)만
        present-only 로 적용한다(배정·재배정). **작업 필드는 건드리지 않는다** — 비담당자
        평가자가 조치 본문을 조작하거나 지우지 못한다.
      - 작업 branch(주체 can_work=저장된 담당자 본인 또는 ADMIN): 작업 필드(조치/결과/기한)
        만 present-only 로 적용한다. **배정 필드는 strip** 되어 재지정할 수 없다.
      - 두 필드군 동시 변경은 **ADMIN 또는 (담당자 본인이면서 평가 능력자)** 만 — 두 능력을
        모두 가질 때만 자연히 두 branch 가 열린다.
      - can_assign 도 can_work 도 아니면 저장 불가(fail-closed).
    두 필드군 모두 **present-only 병합**이라 payload 에 없는 필드는 빈값/NULL 로 덮어쓰지
    않고 기존 값을 보존한다(부분 upsert 가 조치·결과·기한이나 담당자를 지우지 않게 —
    무조건 본문 재생성이 근본원인이었다. sample·supabase 동일). 미배정 개선조치를 담당자가
    스스로 만들 수는 없다(배정 선행). 편집은 항상 DRAFT/PENDING 으로 되돌리며, 이미
    확인(CONFIRMED)된 개선조치는 편집할 수 없다(강등 방지). server-owned 필드(상태·확인/반려
    행위자·시각·감사·report_id)는 payload 에서 제거된다. 담당자 작업 경로는 조건부
    UPDATE(WHERE 담당자=행위자)로 조회~쓰기 사이 재배정 경합을 차단한다."""
    actor = _near_miss_actor(current_user, action="개선조치 저장")
    from modules import auth  # 지연 import(순환 회피)
    if get_near_miss_report(report_id) is None:
        raise ValueError(f"아차사고 보고서를 찾을 수 없습니다: {report_id}")
    existing = _near_miss_improvement_raw(report_id)  # 스코핑 없이 원본(인가 판정용)
    can_assign = auth.can_evaluate_near_miss(actor)      # 배정·재배정 권한(평가자/ADMIN)
    can_work = auth.can_work_improvement(actor, existing)  # 작업 권한(저장된 담당자/ADMIN)
    if not (can_assign or can_work):
        raise ValueError(_NEAR_MISS_IMPROVEMENT_NOT_ASSIGNEE_MESSAGE)
    if existing is not None and existing.get("confirm_status") == _NEAR_MISS_IMPROVEMENT_CONFIRMED:
        raise ValueError("이미 확인(CONFIRMED)된 개선조치는 수정할 수 없습니다.")
    if existing is None and not can_assign:
        # 담당자(작업 권한)는 배정 전에 스스로 개선조치를 만들 수 없다(배정은 평가자/ADMIN).
        raise ValueError(_NEAR_MISS_IMPROVEMENT_NOT_ASSIGNED_MESSAGE)
    safe = {k: v for k, v in dict(payload or {}).items()
            if k not in _NEAR_MISS_IMPROVEMENT_SERVER_FIELDS}
    if not can_assign:
        # 작업 branch 주체(비평가자): 배정 필드는 payload 로 와도 제거(담당자·확인자 재지정 차단).
        for field in _NEAR_MISS_IMPROVEMENT_ASSIGN_FIELDS:
            safe.pop(field, None)
    if not can_work:
        # 배정 branch 주체(비담당자 평가자): 작업 필드는 payload 로 와도 제거(조치 본문 불가침).
        for field in _NEAR_MISS_IMPROVEMENT_WORK_FIELDS:
            safe.pop(field, None)
    if is_sample_mode():
        return _sample_upsert_improvement(
            report_id, safe, actor=actor, can_assign=can_assign,
        )
    # 작업 경로(비평가자 담당자)는 조건부 UPDATE(담당자=행위자)로 재배정 경합을 막는다.
    # ADMIN 은 전역 우회이므로 제한하지 않는다(can_assign True 인 평가자도 제한 없음).
    restrict = (not can_assign) and (not auth.is_admin(actor))
    return supabase_repository.upsert_near_miss_improvement(
        report_id, safe, updated_by=actor["emp_no"], allow_assignment=can_assign,
        restrict_to_assignee_emp_no=(actor["emp_no"] if restrict else None),
    )


def _sample_upsert_improvement(report_id, safe: dict, *, actor: dict, can_assign: bool) -> dict:
    """sample 개선조치 upsert — supabase 배정/작업 분리·조건부 경합 차단을 파이썬으로 재현."""
    from modules import auth  # 지연 import(순환 회피)
    store = _nmi_store()
    key = str(report_id)
    now = datetime.now(timezone.utc).isoformat()
    # 배정 필드는 평가자만(present-only). 작업 필드는 파사드가 이미 비담당자 작업 필드를
    # strip 했으므로 여기서는 present-only 병합만 하면 된다.
    assignment = _nmi_sample_resolve_assignment(safe) if can_assign else {}
    existing = store.get(key)
    if existing is None:
        # 생성: 작업 필드는 기본값으로 초기화(present_only=False), 배정은 present-only.
        work = _nmi_sample_work_body(safe, present_only=False)
        record = {
            "id": _nmi_new_id(store), "report_id": report_id,
            "assignee_emp_no": assignment.get("assignee_emp_no", ""),
            "designated_confirmer_emp_no": assignment.get("designated_confirmer_emp_no", ""),
            **work,
            "confirmed_by_emp_no": "", "rejected_by_emp_no": "",
            "submit_status": "DRAFT", "confirm_status": "PENDING",
            "submitted_at": None, "confirmed_at": None, "rejected_at": None,
            "revision_note": None, "is_active": True,
            "created_by": actor["emp_no"], "updated_by": actor["emp_no"],
            "created_at": now, "updated_at": now,
        }
        store[key] = record
        return dict(record)
    if existing.get("confirm_status") == _NEAR_MISS_IMPROVEMENT_CONFIRMED:
        raise ValueError("이미 확인(CONFIRMED)된 개선조치는 수정할 수 없습니다.")
    # 작업 경로(비평가자 담당자)의 재배정 경합 차단: 저장된 담당자가 여전히 행위자여야 한다
    # (조건부 UPDATE WHERE 담당자=행위자 미러). ADMIN 은 전역 우회.
    if not can_assign and not auth.is_admin(actor):
        if not auth._emp_exact_match(actor["emp_no"], existing.get("assignee_emp_no")):
            raise ValueError(_NEAR_MISS_IMPROVEMENT_REASSIGNED_MESSAGE)
    # 편집: 작업 필드는 present-only(payload 에 없으면 기존 조치·결과·기한 보존). 배정은
    # 평가자만 채워짐(작업 경로는 빈 dict → 배정 보존).
    work_body = _nmi_sample_work_body(safe, present_only=True)
    # 무변경 필드는 레코드에 다시 쓰지 않는다(값 비교): 저장값과 동일한 작업/배정 필드는 제외
    # 하고, 전 필드 무변경이면 no-op 으로 처리한다 — supabase UPDATE 미호출과 동형으로 레코드·
    # 제출/확인 상태·감사(updated_by/updated_at)를 모두 보존한다(SUBMITTED/확정 값 그대로 저장을
    # 눌러도 강등·시각변경 없음, 동일 재배정도 보존). 명시적 ""/None 도 기존 값과 다르면 실변경.
    changed_fields = {
        field: value
        for field, value in {**work_body, **assignment}.items()
        if existing.get(field) != value
    }
    if not changed_fields:
        return dict(existing)  # 전 무변경 no-op: 레코드·상태·감사 보존(리포지토리 미호출 동형).
    # 실변경(하나 이상): 변경된 필드만 반영하고 감사·제출·확인 상태를 초기화한다(기존 규칙).
    # 확인(CONFIRMED) 강등 차단은 상단 게이트가 별도로 강제한다.
    record = dict(existing)
    record.update(changed_fields)
    record.update({
        "updated_by": actor["emp_no"], "updated_at": now,
        "submit_status": "DRAFT", "confirm_status": "PENDING",
        "submitted_at": None, "confirmed_at": None, "rejected_at": None,
        "confirmed_by_emp_no": "", "rejected_by_emp_no": "",
    })
    store[key] = record
    return dict(record)


def submit_near_miss_improvement(report_id, *, current_user) -> dict:
    """DRAFT→SUBMITTED. 담당자·조치 결과가 있어야 제출할 수 있다(DB CHECK 미러).

    제출은 **작업 권한**(auth.can_work_improvement: 저장된 배정 담당자 본인 또는 ADMIN)이
    필수다 — 조치를 수행한 담당자가 제출한다. 평가자라도 담당자가 아니면 대리 제출할 수
    없다(작업·검토 분리). 담당자 경로는 조건부 UPDATE(담당자=행위자)로 재배정 경합을 막는다."""
    actor = _near_miss_actor(current_user, action="개선조치 제출")
    from modules import auth  # 지연 import(순환 회피)
    existing = _near_miss_improvement_raw(report_id)  # 스코핑 없이 원본(인가 판정용)
    if existing is None:
        raise ValueError("제출할 개선조치가 없습니다.")
    if not auth.can_work_improvement(actor, existing):
        raise ValueError(_NEAR_MISS_IMPROVEMENT_NOT_ASSIGNEE_MESSAGE)
    if is_sample_mode():
        store = _nmi_store()
        rec = store.get(str(report_id))
        if rec is None:
            raise ValueError("제출할 개선조치가 없습니다.")
        if rec.get("submit_status") != "DRAFT":
            raise ValueError(_NEAR_MISS_STALE_MESSAGE)
        if not str(rec.get("assignee_emp_no") or "").strip():
            raise ValueError("조치 담당자가 지정되어야 제출할 수 있습니다.")
        if not str(rec.get("result_body") or "").strip():
            raise ValueError("조치 결과가 입력되어야 제출할 수 있습니다.")
        rec = dict(rec)
        rec.update({
            "submit_status": "SUBMITTED",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": actor["emp_no"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        store[str(report_id)] = rec
        return dict(rec)
    restrict = not auth.is_admin(actor)  # 담당자 제출은 담당자=행위자 조건부(ADMIN 우회)
    return supabase_repository.submit_near_miss_improvement(
        report_id, updated_by=actor["emp_no"],
        restrict_to_assignee_emp_no=(actor["emp_no"] if restrict else None),
    )


def confirm_near_miss_improvement(report_id, *, current_user) -> dict:
    """PENDING→CONFIRMED. 실제 확인 행위자=인증 actor(서버 귀속, select 값 아님).

    확인은 **검토 권한**(auth.can_review_improvement: 지정 확인자 본인 또는 평가자 또는
    ADMIN)이 필수이며, 자기확인(담당자==확인자)은 검토 권한과 별개로 추가 차단한다
    (DB CHECK 이중). 이미 확인/반려됐거나 미제출이면 stale."""
    actor = _near_miss_actor(current_user, action="개선조치 확인")
    from modules import auth  # 지연 import(순환 회피)
    existing = _near_miss_improvement_raw(report_id)  # 스코핑 없이 원본(인가 판정용)
    if existing is None:
        raise ValueError("확인할 개선조치가 없습니다.")
    if not auth.can_review_improvement(actor, existing):
        raise ValueError(_NEAR_MISS_IMPROVEMENT_NOT_REVIEWER_MESSAGE)
    # 자기확인 금지: 저장된 담당자 본인은 확인할 수 없다(검토 권한이 있어도). 비교는 로그인
    # 사번 비교 관행과 동일하게 trim+casefold(대소문자 무시) — 담당자를 다른 case 로 지정해도
    # 자기확인이 통과하지 않는다(Codex P2-4). DB CHECK 는 정확 비교이며 repo 가 이중 방어.
    if (str(existing.get("assignee_emp_no") or "").strip().casefold()
            == str(actor["emp_no"]).strip().casefold()):
        raise ValueError("조치 담당자는 자신의 개선조치를 확인할 수 없습니다(자기확인 금지).")
    if is_sample_mode():
        store = _nmi_store()
        rec = store.get(str(report_id))
        if rec is None:
            raise ValueError("확인할 개선조치가 없습니다.")
        if not (rec.get("submit_status") == "SUBMITTED" and rec.get("confirm_status") == "PENDING"):
            raise ValueError(_NEAR_MISS_STALE_MESSAGE)
        now = datetime.now(timezone.utc).isoformat()
        rec = dict(rec)
        rec.update({
            "confirm_status": _NEAR_MISS_IMPROVEMENT_CONFIRMED,
            "confirmed_by_emp_no": actor["emp_no"], "confirmed_at": now,
            "rejected_by_emp_no": "", "rejected_at": None,
            "updated_by": actor["emp_no"], "updated_at": now,
        })
        store[str(report_id)] = rec
        return dict(rec)
    return supabase_repository.confirm_near_miss_improvement(
        report_id, confirmed_by_emp_no=actor["emp_no"], updated_by=actor["emp_no"]
    )


def reject_near_miss_improvement(report_id, note: str, *, current_user) -> dict:
    """PENDING→REJECTED(재조치 요청). 반려 사유 필수.

    반려 권한은 확인과 동일한 **검토 권한**(auth.can_review_improvement: 지정 확인자 또는
    평가자 또는 ADMIN)이다."""
    actor = _near_miss_actor(current_user, action="개선조치 반려")
    from modules import auth  # 지연 import(순환 회피)
    if not str(note or "").strip():
        raise ValueError("개선조치를 반려하려면 사유가 필요합니다.")
    existing = _near_miss_improvement_raw(report_id)  # 스코핑 없이 원본(인가 판정용)
    if existing is None:
        raise ValueError("반려할 개선조치가 없습니다.")
    if not auth.can_review_improvement(actor, existing):
        raise ValueError(_NEAR_MISS_IMPROVEMENT_NOT_REVIEWER_MESSAGE)
    if is_sample_mode():
        store = _nmi_store()
        rec = store.get(str(report_id))
        if rec is None:
            raise ValueError("반려할 개선조치가 없습니다.")
        if not (rec.get("submit_status") == "SUBMITTED" and rec.get("confirm_status") == "PENDING"):
            raise ValueError(_NEAR_MISS_STALE_MESSAGE)
        now = datetime.now(timezone.utc).isoformat()
        rec = dict(rec)
        rec.update({
            "confirm_status": "REJECTED",
            "rejected_by_emp_no": actor["emp_no"], "rejected_at": now,
            "confirmed_by_emp_no": "", "confirmed_at": None,
            "revision_note": str(note).strip(),
            "updated_by": actor["emp_no"], "updated_at": now,
        })
        store[str(report_id)] = rec
        return dict(rec)
    return supabase_repository.reject_near_miss_improvement(
        report_id, note, rejected_by_emp_no=actor["emp_no"], updated_by=actor["emp_no"]
    )


def close_near_miss_report(report_id, *, current_user) -> dict | None:
    """확인+종결 하드게이트: 확인된 활성 개선조치가 있어야 report 를 EVALUATED→CLOSED 로 종결한다.

    supabase 는 원자 RPC(close_near_miss_report)로, sample 은 동일 규칙을 파이썬으로 재현한다.
    인가는 **검토 권한**(auth.can_review_improvement: 지정 확인자 또는 평가자 또는 ADMIN)이며,
    확인된 개선조치 존재·조건부 전이(EVALUATED 에서만, stale 차단)를 강제한다. 이 경로 밖의
    일반 상태변경(update_near_miss_status)은 →CLOSED 를 거부한다."""
    actor = _near_miss_actor(current_user, action="아차사고 종결")
    from modules import auth  # 지연 import(순환 회피)
    existing = _near_miss_improvement_raw(report_id)  # 스코핑 없이 원본(지정 확인자 인가 판정용)
    if not auth.can_review_improvement(actor, existing):
        raise ValueError(_NEAR_MISS_IMPROVEMENT_NOT_REVIEWER_MESSAGE)
    if is_sample_mode():
        # (1) 확인된 활성 개선조치 존재 확인(없으면 종결 불가 — RPC/trigger 하드계약 미러).
        rec = existing
        if not (rec and bool(rec.get("is_active"))
                and rec.get("confirm_status") == _NEAR_MISS_IMPROVEMENT_CONFIRMED):
            raise ValueError(_NEAR_MISS_IMPROVEMENT_NO_CAPA_MESSAGE)
        # (2) 조건부 EVALUATED→CLOSED(다른 상태/동시전이는 stale 로 거부).
        ok = _sample_update_near_miss(report_id, expected_status="EVALUATED", status="CLOSED")
        if not ok:
            raise ValueError(_NEAR_MISS_STALE_MESSAGE)
        return get_near_miss_report(report_id)
    try:
        return supabase_repository.close_near_miss_report(report_id, actor_emp_no=actor["emp_no"])
    finally:
        _invalidate_near_miss()


def near_miss_overdue_count(*, current_user) -> int | None:
    """활성 개선조치(CAPA) 중 기한초과 건수 = due_date < 오늘 AND confirm_status<>CONFIRMED.

    **평가자/ADMIN 전용 집계**다. CAPA 는 역할 기반 접근이 정본(requirements)이므로, 아차사고
    분석 화면이 전 역할에 열려 있어도 CAPA 기한초과는 aggregate count 라도 일반 USER 에게
    노출하지 않는다 — 비권한자(및 무능력자)에게는 ``None``('—')을 돌려 게이트한다(신고 분포는
    전사 공개지만 CAPA 는 권한자만). 인가 게이트 뒤의 이 집계는 명시적으로
    ``_near_miss_improvement_raw`` 를 순회하는 privileged 조회다(스코핑 없이 전량이 의도).

    007 미준비(NOT_READY/PROBE_ERROR)면 ``None``(가짜 0 금지). READY 이후 개별 조회가
    실패하면 축소 수치(최악 0)를 내지 않고 ``None``(미상='—')을 돌린다 — 오류≠정상 0."""
    actor = _near_miss_actor(current_user, action="개선조치 기한초과 집계")
    from modules import auth  # 지연 import(순환 회피)
    if not auth.can_evaluate_near_miss(actor):
        return None  # 일반 USER: CAPA 역할 기반 접근 — 집계 수치도 미노출('—').
    if near_miss_improvement_schema_probe() != READINESS_READY:
        return None
    try:
        reports = get_near_miss_reports({})
    except Exception:
        return None
    if reports is None or reports.empty:
        return 0
    today = date.today().isoformat()
    count = 0
    for rid in reports["id"].astype(str):
        try:
            imp = _near_miss_improvement_raw(rid)  # 권한 게이트 통과 후의 명시적 privileged 조회.
        except Exception:
            return None  # 축소 수치/가짜 0 금지 — 미상('—')으로 정직하게 표시.
        if not imp or not bool(imp.get("is_active", True)):
            continue
        if str(imp.get("confirm_status") or "") == _NEAR_MISS_IMPROVEMENT_CONFIRMED:
            continue
        due = str(imp.get("due_date") or "").strip()
        if due and due < today:  # ISO YYYY-MM-DD 는 사전식 == 시간순 비교.
            count += 1
    return count


# --- 조회 헬퍼 ---
def _safety_officer_flag(emp_no, *, strict: bool = False) -> bool:
    """사용자의 안전담당자 지정 여부(users.is_safety_officer, migration 006).

    sample 모드는 CSV 에 해당 컬럼이 없어 항상 False. supabase 모드는 원격 조회한다.

    ``strict`` 는 인가(write 게이트) 경로 전용이다.
      - 기본(strict=False, 표시/로그인): 조회 오류를 안전하게 False 로 접는다(기존
        거동 보존 — 표시 경로가 일시 오류로 화면을 깨지 않는다).
      - strict=True(인가): **정상적 미준비**(006 미적용/컬럼 부재)만 False 로 접고
        (fail-closed), 그 외 **일시 데이터소스 오류는 False 로 은폐하지 않고 전파**한다.
        일시 원격 오류가 '안전담당자 아님(권한 없음)'으로 둔갑해 실제 안전담당자의
        능력을 조용히 떨어뜨리는 것을 막는다(AGENTS.md '에러를 숨기지 않는다').
    '미준비 vs 일시오류'는 readiness 3-state 와 같은 표식을 쓰는
    ``supabase_repository.is_missing_column_error`` 로 구분한다.

    주의(세션 캐시): 로그인 시점의 값이 세션 사용자 dict 에 실린다. 플래그를 바꾸면
    재로그인해야 반영된다(get_current_user 가 세션 사용자를 우선 반환하기 때문).
    """
    if is_sample_mode():
        return False
    try:
        return supabase_repository.user_is_safety_officer(str(emp_no).strip())
    except DATA_SOURCE_ERRORS as exc:
        if not strict or supabase_repository.is_missing_column_error(exc):
            # 비strict(표시/로그인) 또는 정상적 미준비(006 미적용/컬럼 부재) → False.
            return False
        raise  # strict(인가) 경로의 일시 데이터소스 오류는 은폐하지 않고 전파한다.


def _uncached_users() -> pd.DataFrame:
    """인가 판정 전용 권위 사용자 조회 — 30초 읽기 캐시(_fetch_users)를 우회한다.

    권한 회수·비활성화 직후 아차사고 상태변경/평가 인가가 최대 30초 stale 통과하는 것을
    막기 위해(Codex P2-1), 이 경로만 캐시를 건너뛰어 원격에서 다시 읽는다. 조회 화면용
    읽기 캐시(get_users→_fetch_users)는 그대로 두어 성능을 훼손하지 않는다. sample 모드는
    애초에 이 캐시를 쓰지 않으므로 get_users() 와 동일하다(오류 은폐 없음: 원격 오류는
    그대로 전파된다)."""
    if is_sample_mode():
        return get_users()
    df = supabase_repository.get_users()
    return _empty_contract(df.reset_index(drop=True), USER_COLUMNS)


def find_user_by_emp_no(emp_no: str, *, use_cache: bool = True):
    """사번으로 사용자 1명을 dict 로 반환. 없으면 None.

    사번 조회는 앞뒤 공백을 제거하고 대소문자를 구분하지 않는다
    (영문 사번 ADMIN·admin·Admin 은 동일 사용자). 정규화(trim+casefold)는
    비교에만 쓰고, DB 의 원래 emp_no 값은 변경하지 않는다.
    대소문자만 다른 사번이 여러 건이면 활성 사용자 → 정확한 대소문자 순으로 우선한다.

    ``use_cache=False`` 는 인가 판정용 권위 읽기로, 30초 읽기 캐시를 우회한다
    (권한 회수/비활성화 즉시 반영 — Codex P2-1). 로그인·화면 조회 등 기본 호출은
    캐시를 사용한다.
    """
    df = get_users() if use_cache else _uncached_users()
    if df.empty:
        return None
    raw = str(emp_no).strip()
    key = raw.casefold()
    norm = df["emp_no"].astype(str).str.strip()
    match = df[norm.str.casefold() == key]
    if match.empty:
        return None
    if len(match) > 1:
        pool = match
        if "is_active" in pool.columns:
            active = pool[pool["is_active"].astype(bool)]
            if not active.empty:
                pool = active
        exact = pool[norm.loc[pool.index] == raw]
        if not exact.empty:
            pool = exact
        record = pool.iloc[0].to_dict()
    else:
        record = match.iloc[0].to_dict()
    # 안전담당자 지정 플래그(006)를 세션 사용자 dict 에 실어 능력 헬퍼가 읽게 한다.
    # USER_COLUMNS/get_users 계약은 건드리지 않는다(그 컬럼 계약은 테스트로 고정).
    #
    # 인가 경로(use_cache=False)는 이 조회의 일시 오류를 False 로 은폐하지 않는다
    # (strict — Codex P2). 단 능력이 role 로 이미 결정되는 사용자(ADMIN/MANAGER:
    # auth.can_evaluate_near_miss 가 플래그 없이 True)에게는 안전담당자 조회가 인가에
    # 무의미하므로 strict 에서 제외한다 — 그들이 필요로 하지 않는 조회의 일시 오류가
    # write 를 막지 않게(ADMIN/MANAGER 경로 비영향 보존). 인가 판정 자체는 여전히
    # auth.can_evaluate_near_miss 단일 SoT 가 하고, 여기서는 조회 strict 여부만 정한다.
    # 표시/로그인(use_cache=True)은 항상 관대하게 False 로 접는다.
    role = str(record.get("role") or "").strip().upper()
    strict_flag = (not use_cache) and role not in ("ADMIN", "MANAGER")
    record["is_safety_officer"] = _safety_officer_flag(
        record.get("emp_no"), strict=strict_flag
    )
    return record


# =========================================================================
# 비밀번호 자격증명 · 로그인 세션 파사드 (migration 008)
#
# 이 파사드의 모든 함수는 **사번(emp_no)** 을 식별자로 받는다 — sample 모드에는 DB id 가
# 없기 때문이다. supabase 구현이 내부에서 사번 → id 를 해석한다.
#
# 자격증명은 USER_COLUMNS/get_users 계약에 넣지 않는다. 그 DataFrame 은 화면까지
# 흘러가므로, 해시가 거기 실리면 어느 화면에서든 노출될 수 있다.
#
# sample 모드: 자격증명을 st.session_state 에만 둔다(프로세스 수명). 로컬 디스크에
#   비밀번호 파일을 만들지 않으며, 재시작하면 초기 상태(사번이 곧 비번)로 돌아간다.
#   개발 편의로는 충분하고, 관리해야 할 로컬 비밀이 늘지 않는다.
# =========================================================================
_SAMPLE_CRED_KEY = "_sample_credentials"


def _sample_credentials() -> dict:
    import streamlit as _st

    if _SAMPLE_CRED_KEY not in _st.session_state:
        _st.session_state[_SAMPLE_CRED_KEY] = {}
    return _st.session_state[_SAMPLE_CRED_KEY]


def _sample_credential_default(emp_no: str) -> dict:
    """sample 모드의 초기 자격증명 상태 — 비번 미설정(사번이 곧 비번)."""
    return {
        "id": None,
        "emp_no": str(emp_no),
        "password_hash": None,
        "password_set_at": None,
        "must_change_password": True,
        "initial_password_expires_at": None,
        "failed_login_count": 0,
        "locked_until": None,
    }


def password_auth_ready(*, force: bool = False) -> bool:
    """비밀번호 인증 스키마(008)를 쓸 수 있는가.

    sample 모드는 세션 상태를 쓰므로 항상 True. supabase 모드는 실제 컬럼·테이블
    존재를 프로브한다 — 미적용이면 auth 가 로그인을 **거부**한다(fail-closed).
    스키마가 없다고 비번 없는 예전 동작으로 되돌아가면, 마이그레이션 누락을 모른 채
    "비번이 켜졌다"고 믿고 운영에 들어가는 사고가 난다.
    """
    if is_sample_mode():
        return True
    return supabase_repository.password_auth_ready(force=force)


def get_user_credential(emp_no: str) -> dict | None:
    """정규 사번의 자격증명 dict. 없으면 None.

    ``emp_no`` 는 find_user_by_emp_no 가 해석한 DB 원본 사번이어야 한다.
    """
    if not str(emp_no or "").strip():
        return None
    if is_sample_mode():
        store = _sample_credentials()
        key = str(emp_no)
        if key not in store:
            store[key] = _sample_credential_default(key)
        return dict(store[key])
    return supabase_repository.get_user_credential(emp_no)


def _sample_update_credential(emp_no: str, changes: dict) -> None:
    store = _sample_credentials()
    key = str(emp_no)
    record = store.get(key) or _sample_credential_default(key)
    record.update(changes)
    store[key] = record


def set_user_password(emp_no: str, password_hash: str) -> None:
    """사용자가 스스로 비번을 설정했다. 강제변경·잠금·초기비번 만료를 함께 해제한다."""
    now_iso = _utc_now_iso()
    if is_sample_mode():
        _sample_update_credential(emp_no, {
            "password_hash": str(password_hash),
            "password_set_at": now_iso,
            "must_change_password": False,
            "initial_password_expires_at": None,
            "failed_login_count": 0,
            "locked_until": None,
        })
        return
    credential = supabase_repository.get_user_credential(emp_no)
    if not credential:
        raise ValueError(f"비밀번호를 설정할 사용자를 찾을 수 없습니다: {emp_no}")
    supabase_repository.set_user_password(credential["id"], password_hash)


def reset_user_password(emp_no: str, *, valid_days: int | None = None) -> None:
    """ADMIN 초기화: 비번을 지워 사번이 다시 초기 비번이 되게 하고 강제변경을 켠다.

    ``valid_days`` 가 주어지면 그만큼 뒤를 초기 비번 만료 시각으로 둔다(기본
    config.INITIAL_PASSWORD_VALID_DAYS). 활성 세션은 호출부가 함께 폐기한다.
    """
    days = config.INITIAL_PASSWORD_VALID_DAYS if valid_days is None else valid_days
    expires = None
    if days and days > 0:
        from datetime import datetime, timedelta, timezone

        expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    if is_sample_mode():
        _sample_update_credential(emp_no, {
            "password_hash": None,
            "password_set_at": None,
            "must_change_password": True,
            "initial_password_expires_at": expires,
            "failed_login_count": 0,
            "locked_until": None,
        })
        return
    credential = supabase_repository.get_user_credential(emp_no)
    if not credential:
        raise ValueError(f"비밀번호를 초기화할 사용자를 찾을 수 없습니다: {emp_no}")
    supabase_repository.reset_user_password(credential["id"], expires)


def update_login_failure(emp_no: str, failed_count: int, locked_until: str | None) -> None:
    """로그인 실패 카운트·잠금 시각을 기록한다."""
    if is_sample_mode():
        _sample_update_credential(emp_no, {
            "failed_login_count": max(0, int(failed_count)),
            "locked_until": locked_until,
        })
        return
    credential = supabase_repository.get_user_credential(emp_no)
    if credential:
        supabase_repository.update_login_failure(
            credential["id"], failed_count, locked_until
        )


def clear_login_failure(emp_no: str) -> None:
    """로그인 성공 시 실패 카운트·잠금을 초기화한다."""
    update_login_failure(emp_no, 0, None)


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# --- 로그인 세션 ---
# sample 모드는 기존 로컬 JSON 폴백(auth._load_sessions)을 그대로 쓴다 — 로컬 개발에서
# 앱 재시작 후에도 로그인이 유지되는 편의를 깨지 않는다. supabase 모드만 테이블을 쓴다.
def use_session_table() -> bool:
    """세션을 DB 테이블에 저장하는가(supabase 모드 + 008 적용)."""
    return (not is_sample_mode()) and password_auth_ready()


def create_login_session(token_hash: str, emp_no: str, expires_at: str) -> None:
    credential = supabase_repository.get_user_credential(emp_no)
    if not credential:
        raise ValueError(f"세션을 만들 사용자를 찾을 수 없습니다: {emp_no}")
    supabase_repository.create_login_session(
        token_hash, credential["id"], credential["emp_no"], expires_at
    )


def find_login_session(token_hash: str) -> dict | None:
    return supabase_repository.find_login_session(token_hash)


def touch_login_session(token_hash: str) -> None:
    supabase_repository.touch_login_session(token_hash)


def revoke_login_session(token_hash: str, reason: str = "logout") -> None:
    supabase_repository.revoke_login_session(token_hash, reason)


def revoke_user_sessions(emp_no: str, reason: str = "password_change") -> None:
    """한 사용자의 활성 세션을 모두 폐기한다(비번 변경·초기화 시)."""
    if is_sample_mode():
        return
    credential = supabase_repository.get_user_credential(emp_no)
    if credential:
        supabase_repository.revoke_user_sessions(credential["id"], reason)


def purge_expired_sessions() -> None:
    supabase_repository.purge_expired_sessions()


# ─── 업무별 담당 권한 + 알림 이메일 (migration 010) — emp_no 파사드 ───────────
# sample 모드는 세션 스토어로 동형 제공(실DB 무접촉). supabase 모드는 010 probe 로
# 분기해 미적용 환경에서 조회는 빈 값, 저장은 명확한 오류를 낸다.
_CAPS_STORE = "_sample_capabilities"   # {emp_no: set[str]}
_EMAILS_STORE = "_sample_user_emails"  # {emp_no: list[{"email","scope"}]}


def capabilities_ready() -> bool:
    if is_sample_mode():
        return True
    return supabase_repository.capabilities_ready()


def get_user_capabilities(emp_no: str) -> list[str]:
    emp = str(emp_no).strip()
    if is_sample_mode():
        return sorted(st.session_state.get(_CAPS_STORE, {}).get(emp, set()))
    return supabase_repository.get_user_capabilities(emp)


def set_user_capabilities(emp_no: str, caps: list[str], *, actor_emp_no: str = "") -> None:
    emp = str(emp_no).strip()
    wanted = {str(c).strip() for c in caps if str(c).strip()}
    unknown = wanted - set(config.CAPABILITIES)
    if unknown:
        raise ValueError("알 수 없는 담당 코드: " + ", ".join(sorted(unknown)))
    if is_sample_mode():
        store = st.session_state.setdefault(_CAPS_STORE, {})
        store[emp] = set(wanted)
        return
    supabase_repository.set_user_capabilities(emp, sorted(wanted), actor_emp_no=actor_emp_no)


def has_capability(emp_no: str, capability: str) -> bool:
    """담당 여부 판정 — 화면·게이트는 이 함수만 쓴다(저장소 직접 조회 금지)."""
    return str(capability).strip() in get_user_capabilities(emp_no)


def get_user_emails(emp_no: str) -> list[dict]:
    emp = str(emp_no).strip()
    if is_sample_mode():
        return [dict(r) for r in st.session_state.get(_EMAILS_STORE, {}).get(emp, [])]
    return supabase_repository.get_user_emails(emp)


def set_user_emails(emp_no: str, rows: list[dict], *, actor_emp_no: str = "") -> None:
    emp = str(emp_no).strip()
    valid_scopes = {config.EMAIL_SCOPE_ALL} | set(config.CAPABILITIES)
    cleaned, seen = [], set()
    for row in rows or []:
        email = str(row.get("email") or "").strip().lower()  # 소문자 정규화(저장 계약)
        scope = str(row.get("scope") or config.EMAIL_SCOPE_ALL).strip().upper()
        if not email:
            continue
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError(f"이메일 형식이 올바르지 않습니다: {email}")
        if scope not in valid_scopes:
            raise ValueError(f"알 수 없는 수신 범위: {scope}")
        if (scope, email) in seen:
            continue
        seen.add((scope, email))
        cleaned.append({"email": email, "scope": scope})
    if is_sample_mode():
        st.session_state.setdefault(_EMAILS_STORE, {})[emp] = cleaned
        return
    supabase_repository.set_user_emails(emp, cleaned, actor_emp_no=actor_emp_no)


def notification_recipients(capability: str) -> list[str]:
    """해당 업무 담당자들의 수신 이메일(중복 제거·정렬). 발송 fallback 은 mailer 소관."""
    cap = str(capability).strip()
    if is_sample_mode():
        caps_store = st.session_state.get(_CAPS_STORE, {})
        emails_store = st.session_state.get(_EMAILS_STORE, {})
        out = set()
        for emp, caps in caps_store.items():
            if cap not in caps:
                continue
            for r in emails_store.get(emp, []):
                if r.get("scope") in (config.EMAIL_SCOPE_ALL, cap):
                    out.add(str(r.get("email") or "").lower())
        return sorted(e for e in out if e)
    return supabase_repository.notification_recipients(cap)


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
            "category": r.get("category", ""),
            "color": r["color"] or "#9AA0A6",
            "is_work": bool(r["is_work"]),
        }
    return out


def classify_work_group(code: str, work_type: dict) -> str | None:
    """근무코드를 개인 화면 공통 집계 그룹으로 분류한다."""
    code = str(code or "").strip()
    category = str(work_type.get("category") or "").strip()
    name = str(work_type.get("name") or "")
    label = f"{code} {category} {name}"
    if code == "OFF" or category.upper() == "OFF":
        return "OFF"
    if "야간" in category or code.startswith("야") or "특야" in code:
        return "야간"
    if "주간" in category or code.startswith("주") or "특주" in code:
        return "주간"
    if not bool(work_type.get("is_work")) or any(
        word in label for word in ("휴가", "연차", "경조")
    ):
        return "휴가"
    return None


def get_user_schedules(emp_no: str) -> pd.DataFrame:
    """특정 사번의 근무표 레코드(long format). 컬럼: emp_no, duty_date, work_type_code, note."""
    if not is_sample_mode():
        return _fetch_user_schedules(str(emp_no).strip())
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
    if not is_sample_mode():
        return _fetch_month_schedules(tuple(sorted(emp_nos)), int(year), int(month))
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


def get_day_schedules(the_date) -> pd.DataFrame:
    """지정 일자의 전체 근무내역(long format, SCHEDULE_COLUMNS)을 조회한다.

    대시보드 그룹 보드 전용 **읽기 전용** 조회이며 저장 계약과 무관하다.
    the_date 는 ``datetime.date`` / ``datetime.datetime`` / ISO 문자열('YYYY-MM-DD')
    을 받는다. 입력을 항상 날짜(자정)로 정규화해 sample/Supabase 가 같은
    'YYYY-MM-DD' 기준을 쓰게 한다 — datetime 의 시간부가 eq 조건을 어긋나게 하는
    문제를 막는다.

    sample 모드는 세션 스토어를 일자로 필터하고, supabase 모드는 근무일자 eq
    조건으로 조회한다(get_month_schedules 와 같은 _schedule_rows 패턴 준용).
    문자열 접두어 비교 대신 실제 날짜로 해석해, ISO 가 아닌 문자열이나
    datetime 으로 저장된 기존 행 누락을 피한다.
    """
    target = pd.to_datetime(the_date, errors="coerce")
    if pd.isna(target):
        # 파싱 불가 일자 — 조회 없이 빈 계약 반환(오류 위장 금지).
        return _typed_empty_frame(SCHEDULE_COLUMNS)
    iso = target.strftime("%Y-%m-%d")  # 시간부 제거 — sample/Supabase 일관
    if not is_sample_mode():
        return _fetch_day_schedules(iso)
    df = get_schedules()
    if df.empty:
        return df.iloc[0:0].copy()
    duty_dates = pd.to_datetime(df["duty_date"], errors="coerce")
    return df[duty_dates.dt.normalize() == target.normalize()].reset_index(drop=True).copy()


# --- Supabase 운영·검증 API ---
def test_connection() -> dict[str, int]:
    if is_sample_mode():
        raise config.DataSourceConfigurationError("연결 테스트는 supabase 모드에서만 실행할 수 있습니다.")
    return supabase_repository.test_connection()


def upsert_department(record: dict) -> None:
    try:
        supabase_repository.upsert_departments([record])
    finally:
        _invalidate_departments()


def upsert_team(record: dict) -> None:
    try:
        supabase_repository.upsert_teams([record])
    finally:
        _invalidate_teams()


def upsert_user(record: dict) -> None:
    try:
        supabase_repository.upsert_users([record])
    finally:
        _invalidate_users()


def upsert_work_type(record: dict) -> None:
    try:
        supabase_repository.upsert_work_types([record])
    finally:
        _invalidate_work_types()


def upsert_schedule(record: dict) -> None:
    try:
        supabase_repository.upsert_schedules([record])
    finally:
        _invalidate_schedules()


def upsert_shift_group(record: dict) -> None:
    try:
        supabase_repository.upsert_shift_groups([record])
    finally:
        _invalidate_shift_groups()


def delete_schedule(emp_no: str, duty_date: str) -> None:
    try:
        supabase_repository.delete_schedule(str(emp_no).strip(), str(duty_date).strip())
    finally:
        _invalidate_schedules()


def deactivate_department(dept_code: str) -> None:
    try:
        supabase_repository.deactivate_department(str(dept_code).strip())
    finally:
        _invalidate_departments()


def delete_department(dept_code: str) -> None:
    """부서를 물리 삭제한다(참조 없는 부서 전용 — 참조 확인은 호출부가 담당).

    로컬 샘플 모드에서는 세션 스토어에서 제거하고, Supabase 모드에서는 물리 삭제한다.
    """
    code = str(dept_code).strip()
    if is_sample_mode():
        if _DEPTS_STORE in st.session_state:
            store = st.session_state[_DEPTS_STORE]
            st.session_state[_DEPTS_STORE] = (
                store[store["dept_code"].astype(str) != code].reset_index(drop=True)
            )
        return
    try:
        supabase_repository.delete_department(code)
    finally:
        _invalidate_departments()


def department_reference_counts(dept_code: str) -> dict:
    """부서를 참조하는 사용자/조/편성 조 건수를 반환한다(활성·비활성 모두 포함).

    아직 생성되지 않은 테이블(예: migration 002 미적용 시 shift_groups)의 조회
    실패만 참조 0 으로 안전하게 처리한다. 네트워크/소켓 등 일시 실패는 참조 확인
    실패로 보아 fail-closed sentinel 을 실어 물리 삭제를 막는다(미사용 처리로 라우팅).
    """
    code = str(dept_code).strip()
    check_failed = False

    def _count(loader) -> int:
        nonlocal check_failed
        try:
            frame = loader()
        except Exception as exc:
            if not _is_missing_table_error(exc):
                check_failed = True
            return 0
        if frame.empty or "dept_code" not in frame:
            return 0
        return int((frame["dept_code"].astype(str).str.strip() == code).sum())

    result = {
        "users": _count(get_users),
        "teams": _count(get_teams),
        "shift_groups": _count(get_shift_groups),
    }
    if check_failed:
        result[REFERENCE_CHECK_FAILED] = 1
    return result


def deactivate_team(dept_code: str, team_code: str) -> None:
    try:
        supabase_repository.deactivate_team(str(dept_code).strip(), str(team_code).strip())
    finally:
        _invalidate_teams()


def delete_team(dept_code: str, team_code: str) -> None:
    """조를 물리 삭제한다(참조 없는 조 전용 — 참조 확인은 호출부가 담당)."""
    dc, tc = str(dept_code).strip(), str(team_code).strip()
    if is_sample_mode():
        if _TEAMS_STORE in st.session_state:
            store = st.session_state[_TEAMS_STORE]
            keep = ~(
                (store["dept_code"].astype(str) == dc)
                & (store["team_code"].astype(str) == tc)
            )
            st.session_state[_TEAMS_STORE] = store[keep].reset_index(drop=True)
        return
    try:
        supabase_repository.delete_team(dc, tc)
    finally:
        _invalidate_teams()


def team_reference_counts(dept_code: str, team_code: str) -> dict:
    """조를 참조하는 사용자 수를 반환한다(활성·비활성 모두 포함)."""
    dc, tc = str(dept_code).strip(), str(team_code).strip()
    try:
        users = get_users()
    except Exception as exc:
        if _is_missing_table_error(exc):
            return {"users": 0}
        return {"users": 0, REFERENCE_CHECK_FAILED: 1}
    if users.empty:
        return {"users": 0}
    mask = (
        (users["dept_code"].astype(str).str.strip() == dc)
        & (users["team_code"].astype(str).str.strip() == tc)
    )
    return {"users": int(mask.sum())}


def deactivate_user(emp_no: str) -> None:
    try:
        supabase_repository.deactivate_user(str(emp_no).strip())
    finally:
        _invalidate_users()


def deactivate_work_type(code: str) -> None:
    try:
        supabase_repository.deactivate_work_type(str(code).strip())
    finally:
        _invalidate_work_types()


def delete_work_type(code: str) -> None:
    """근무형태를 물리 삭제한다(근무표 참조 없는 코드 전용 — 확인은 호출부가 담당)."""
    c = str(code).strip()
    if is_sample_mode():
        if _WORK_TYPES_STORE in st.session_state:
            store = st.session_state[_WORK_TYPES_STORE]
            st.session_state[_WORK_TYPES_STORE] = (
                store[store["code"].astype(str) != c].reset_index(drop=True)
            )
        return
    try:
        supabase_repository.delete_work_type(c)
    finally:
        _invalidate_work_types()


def work_type_reference_counts(code: str) -> dict:
    """근무형태 코드를 참조하는 근무표(work_schedules) 건수를 반환한다."""
    c = str(code).strip()
    try:
        scheds = get_schedules()
    except Exception as exc:
        if _is_missing_table_error(exc):
            return {"schedules": 0}
        return {"schedules": 0, REFERENCE_CHECK_FAILED: 1}
    if scheds.empty or "work_type_code" not in scheds:
        return {"schedules": 0}
    return {"schedules": int((scheds["work_type_code"].astype(str).str.strip() == c).sum())}


def cleanup_test_records(dept_code: str, team_code: str, emp_no: str, work_type_codes) -> None:
    """의존성 역순으로 TEST_* 레코드만 물리 삭제한다."""
    try:
        supabase_repository.hard_delete_test_user(emp_no)
        for code in work_type_codes:
            supabase_repository.hard_delete_test_work_type(str(code).strip())
        supabase_repository.hard_delete_test_team(dept_code, team_code)
        supabase_repository.hard_delete_test_department(dept_code)
    finally:
        # 순차 삭제 중 일부만 커밋된 뒤 예외가 나도 관련 캐시를 모두 비운다.
        _invalidate_users()
        _invalidate_work_types()
        _invalidate_teams()
        _invalidate_departments()


def hard_delete_test_user(emp_no: str) -> None:
    try:
        supabase_repository.hard_delete_test_user(str(emp_no).strip())
    finally:
        _invalidate_users()


def hard_delete_test_work_type(code: str) -> None:
    try:
        supabase_repository.hard_delete_test_work_type(str(code).strip())
    finally:
        _invalidate_work_types()


def hard_delete_test_team(dept_code: str, team_code: str) -> None:
    try:
        supabase_repository.hard_delete_test_team(str(dept_code).strip(), str(team_code).strip())
    finally:
        _invalidate_teams()


def hard_delete_test_department(dept_code: str) -> None:
    try:
        supabase_repository.hard_delete_test_department(str(dept_code).strip())
    finally:
        _invalidate_departments()


def reset_supabase_client() -> None:
    supabase_repository.reset_client()
    # 클라이언트가 새 연결로 교체되면 이전 연결로 캐시된 읽기 결과는 무효다.
    _invalidate_all()


def sample_seed_frames() -> dict[str, pd.DataFrame]:
    """샘플 CSV를 화면 자연키 형식으로 변환해 seed 순서대로 반환한다."""
    return {
        "departments": _base_departments(),
        "teams": _base_teams(),
        "work_types": _base_work_types(),
        "users": _base_users(),
        "work_schedules": _base_schedules(),
    }
