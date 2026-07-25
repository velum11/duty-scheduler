"""데이터 접근 계층 (sample/Supabase facade).

데이터 모드는 설정에서 명시적으로 선택하며, Supabase 오류를 sample 모드로 숨기지 않는다.
화면/로직 코드는 이 모듈의 자연키 기반 함수만 호출한다.

저장 계층(CSV/Supabase)은 docs/database.md 대로 id 기반(department_id / team_id /
user_id)이다. 화면은 자연키(dept_code / team_code / emp_no / duty_date)를 쓰므로,
이 파사드에서 기준정보를 조인해 자연키 컬럼을 덧붙여 반환한다. 원본(캐시된)
DataFrame 을 훼손하지 않도록 항상 copy 후 컬럼을 추가한다.
"""
import hashlib
from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st

from modules import config, sample_data, supabase_repository, validators

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
    "display_order",
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
ORG_DEPT_COLUMNS = [
    "dept_code", "dept_name", "group_code", "description", "sort_order", "is_active",
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
    return df[USER_COLUMNS].reset_index(drop=True)


def get_users(
    dept_code: str | None = None,
    team_code: str | None = None,
    is_active: bool | None = None,
) -> pd.DataFrame:
    """사용자 목록(USER_COLUMNS).

    로컬 샘플 모드에서는 세션 편집 결과(save_users)를 우선 반환하므로,
    사용자 관리 화면에서 저장한 내용이 다른 화면에도 그대로 반영된다.
    Phase 5(Supabase)에서는 이 분기를 실제 조회로 교체한다.
    """
    if is_sample_mode():
        if _USERS_STORE not in st.session_state:
            st.session_state[_USERS_STORE] = _base_users()
        return _empty_contract(st.session_state[_USERS_STORE].copy(), USER_COLUMNS)
    df = _fetch_users()
    if dept_code is not None:
        df = df[df["dept_code"].astype(str) == str(dept_code).strip()]
    if team_code is not None:
        df = df[df["team_code"].astype(str) == str(team_code).strip()]
    if is_active is not None:
        df = df[df["is_active"].astype(bool) == bool(is_active)]
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


def _near_miss_actor(current_user, *, action: str) -> dict:
    """세션 사용자에서 행위자 신원을 서버측으로 확정한다(위조 방지).

    화면은 반드시 인증된 현재 사용자(auth.get_current_user 반환값)를 넘겨야 하며,
    위젯 입력값이 아니다. **사번(emp_no)만** 신뢰하고, 사번·부서는 세션 dict 가 아니라
    그 사번으로 조회한 DB 권위 사용자 레코드에서 다시 도출한다 — 위조된
    current_user(예: 사번은 유효하나 dept_code 를 타 부서로 조작)로 다른 부서에 귀속시키는
    것을 막는다. payload 의 신원 필드는 신뢰하지 않는다. 신원을 확인할 수 없으면 DB 요청
    전에 차단한다."""
    if not isinstance(current_user, dict):
        raise ValueError(f"{action}에는 인증된 현재 사용자 정보가 필요합니다.")
    emp_no = str(current_user.get("emp_no") or "").strip()
    record = find_user_by_emp_no(emp_no) if emp_no else None
    if not emp_no or record is None:
        raise ValueError(f"{action} 행위자 사번을 확인할 수 없습니다: {emp_no!r}")
    # 사번·부서 모두 권위 레코드에서 가져온다(세션 dict 의 dept_code 는 무시).
    return {
        "emp_no": str(record.get("emp_no") or emp_no).strip(),
        "dept_code": str(record.get("dept_code") or "").strip(),
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


def _near_miss_store() -> pd.DataFrame:
    """sample 모드 아차사고 backing store(세션 유지, 실DB 미변경)."""
    if _NEAR_MISS_STORE not in st.session_state:
        st.session_state[_NEAR_MISS_STORE] = _near_miss_frame([])
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


def _sample_near_miss_record(payload: dict, store: pd.DataFrame) -> dict:
    """create 입력(자연키)을 검증해 sample 스토어 레코드로 만든다.

    reporter_emp_no·dept_code·시각은 서버측 값이다(화면이 세션에서 채워 넘긴다).
    """
    work_name = str(payload.get("work_name") or "").strip()
    if not work_name:
        raise ValueError("작업명은 비어 있을 수 없습니다.")
    reporter = str(payload.get("reporter_emp_no") or "").strip()
    if not reporter or find_user_by_emp_no(reporter) is None:
        raise ValueError(f"아차사고 보고자 사번을 찾을 수 없습니다: {reporter}")
    cause = str(payload.get("cause_code") or "").strip().upper()
    if cause not in NEAR_MISS_CAUSE_CODES:
        raise ValueError(f"원인 코드가 유효하지 않습니다: {cause}")
    proposed = payload.get("proposed_grade")
    proposed = str(proposed).strip().upper() if proposed not in (None, "") else None
    if proposed is not None and proposed not in NEAR_MISS_GRADES:
        raise ValueError(f"제안 등급이 유효하지 않습니다: {proposed}")
    incident_date = str(payload.get("incident_date") or "").strip()
    date.fromisoformat(incident_date)  # 형식 오류 시 ValueError
    photo = payload.get("photo_paths") or []
    if not isinstance(photo, (list, tuple)):
        raise ValueError("photo_paths 는 배열이어야 합니다.")
    ids = pd.to_numeric(store["id"], errors="coerce").dropna() if not store.empty else pd.Series([], dtype=float)
    new_id = int(ids.max()) + 1 if not ids.empty else 1
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": new_id,
        "report_no": _sample_report_no(store, incident_date),
        "status": "SUBMITTED",
        "work_name": work_name,
        "work_content": str(payload.get("work_content") or ""),
        "incident_content": str(payload.get("incident_content") or ""),
        "countermeasure": str(payload.get("countermeasure") or ""),
        "site_description": str(payload.get("site_description") or ""),
        "proposed_grade": proposed,
        "confirmed_grade": None,
        "cause_code": cause,
        "cause_detail": str(payload.get("cause_detail") or ""),
        "incident_date": incident_date,
        "reporter_emp_no": reporter,
        "evaluator_emp_no": "",
        "dept_code": str(payload.get("dept_code") or ""),
        "photo_paths": [str(p) for p in photo],
        "rejection_reason": None,
        "evaluated_at": None,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


def _sample_update_near_miss(
    report_id, *, expected_status=None, clear_eval: bool = False, **changes
) -> bool:
    """sample 스토어의 단일 보고서 필드를 변경한다(존재하는 컬럼만).

    ``expected_status`` 가 주어지면 현재 상태가 일치할 때만 적용한다(supabase 조건부
    UPDATE 와 동일한 원자 전이 계약을 sample 에서도 모사). 적용하면 True, 대상 없음·
    상태 불일치(이미 전이됨)면 False 를 반환해 파사드가 stale 오류를 낼 수 있게 한다."""
    store = _near_miss_store().copy()
    mask = store["id"].astype(str) == str(report_id)
    if not mask.any():
        return False
    if expected_status is not None:
        current = store.loc[mask, "status"].astype(str).str.strip()
        if not (current == str(expected_status).strip()).all():
            return False
    if clear_eval:
        store.loc[mask, "confirmed_grade"] = None
        store.loc[mask, "evaluator_emp_no"] = ""
        store.loc[mask, "evaluated_at"] = None
    for column, value in changes.items():
        if column in store.columns and value is not None:
            store.loc[mask, column] = value
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
        return None if match.empty else match.iloc[0].to_dict()
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


def update_near_miss_status(
    report_id, status: str, *, rejection_reason=None, current_user=None, updated_by=None,
) -> dict | None:
    """아차사고 상태를 전이 규칙에 맞게 변경한다.

    허용되지 않은 전이·반려 사유 누락은 ValueError. 평가상태(EVALUATED/CLOSED)를
    벗어나면 평가 필드를 함께 초기화한다(DB 제약 충족). 전이는 읽은 현재 상태를
    기대값으로 하는 원자적 조건부 UPDATE 로 수행하며, 그 사이 다른 사용자가 먼저
    상태를 바꿨으면(TOCTOU) 덮어쓰지 않고 stale 오류를 낸다. ``current_user`` 는
    감사(updated_by) 귀속에 쓰인다(세션 사용자, 위젯 값 아님).
    """
    target = str(status).strip()
    if target not in NEAR_MISS_STATUSES:
        raise ValueError(f"유효하지 않은 상태입니다: {target}")
    current = get_near_miss_report(report_id)
    if current is None:
        raise ValueError(f"아차사고 보고서를 찾을 수 없습니다: {report_id}")
    cur_status = str(current.get("status") or "").strip()
    if cur_status != target and not near_miss_transition_allowed(cur_status, target):
        raise ValueError(f"허용되지 않은 상태 전이입니다: {cur_status} → {target}")
    if target == "REJECTED" and not str(rejection_reason or "").strip():
        raise ValueError("반려하려면 반려 사유가 필요합니다.")
    clear_eval = target not in _NEAR_MISS_EVAL_STATES
    reason = str(rejection_reason).strip() if target == "REJECTED" else None
    # updated_by 는 세션 사용자(서버측)에서 확정한다. 명시 인자는 세션이 없을 때만 폴백.
    attribution = _near_miss_updated_by(current_user) or updated_by
    if is_sample_mode():
        ok = _sample_update_near_miss(
            report_id, expected_status=cur_status, clear_eval=clear_eval,
            status=target, rejection_reason=reason,
        )
        if not ok:
            raise ValueError(_NEAR_MISS_STALE_MESSAGE)
        return get_near_miss_report(report_id)
    try:
        return supabase_repository.update_near_miss_status(
            report_id, target, expected_status=cur_status, rejection_reason=reason,
            clear_evaluation=clear_eval, updated_by=attribution,
        )
    finally:
        _invalidate_near_miss()


def evaluate_near_miss(
    report_id, confirmed_grade: str, *, current_user, updated_by=None,
) -> dict | None:
    """평가 확정: status=EVALUATED + 확정등급/평가자/평가시각 설정.

    평가자(evaluator)·평가시각은 payload/위젯이 아니라 인증된 ``current_user``에서
    **서버측으로 확정**한다 — 다른 사람이 평가한 것처럼 위조하는 것을 막는다. 확정 등급
    유효성을 검증하고, 보고서가 **평가 이전 상태(SUBMITTED/IN_REVIEW)**일 때만 평가한다.
    이미 평가/종결된 보고서(EVALUATED/CLOSED)는 재평가로 덮어쓸 수 없으며 stale 오류를
    낸다. 읽은 현재 상태를 기대값으로 하는 원자적 조건부 UPDATE 로 확정하므로 두 평가자가
    동시에 확정해도 하나만 성공하고 다른 하나는 '상태가 이미 변경됨'을 받는다.
    """
    grade = str(confirmed_grade).strip().upper()
    if grade not in NEAR_MISS_GRADES:
        raise ValueError(f"확정 등급이 유효하지 않습니다: {grade}")
    actor = _near_miss_actor(current_user, action="아차사고 평가")
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


# --- 조회 헬퍼 ---
def _safety_officer_flag(emp_no) -> bool:
    """사용자의 안전담당자 지정 여부(users.is_safety_officer, migration 006).

    sample 모드는 CSV 에 해당 컬럼이 없어 항상 False. supabase 모드는 원격 조회하며
    컬럼 미적용(006 전)·오류는 안전하게 False 로 접는다.
    주의(세션 캐시): 로그인 시점의 값이 세션 사용자 dict 에 실린다. 플래그를 바꾸면
    재로그인해야 반영된다(get_current_user 가 세션 사용자를 우선 반환하기 때문).
    """
    if is_sample_mode():
        return False
    try:
        return supabase_repository.user_is_safety_officer(str(emp_no).strip())
    except DATA_SOURCE_ERRORS:
        return False


def find_user_by_emp_no(emp_no: str):
    """사번으로 사용자 1명을 dict 로 반환. 없으면 None.

    사번 조회는 앞뒤 공백을 제거하고 대소문자를 구분하지 않는다
    (영문 사번 ADMIN·admin·Admin 은 동일 사용자). 정규화(trim+casefold)는
    비교에만 쓰고, DB 의 원래 emp_no 값은 변경하지 않는다.
    대소문자만 다른 사번이 여러 건이면 활성 사용자 → 정확한 대소문자 순으로 우선한다.
    """
    df = get_users()
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
    record["is_safety_officer"] = _safety_officer_flag(record.get("emp_no"))
    return record


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
