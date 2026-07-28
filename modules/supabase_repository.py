"""Supabase-backed persistence for duty scheduler data.

This module is server-side only. It translates database identifiers into the
natural keys used by the existing Streamlit views.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Callable, Iterable

import pandas as pd
import streamlit as st
from supabase import Client, create_client

from modules import config, validators

# id↔자연키 매핑 memoize 의 ttl(초). db.py 파사드 읽기 캐시와 같은 짧은 staleness
# 안전망을 쓴다 — 쓰기 후에는 db.py 의 _invalidate_* 가 이 매핑 캐시도 함께 비운다.
_MAP_CACHE_TTL = 30

PAGE_SIZE = 1000
WRITE_BATCH_SIZE = 500
REQUIRED_TABLES = ("departments", "teams", "users", "work_types", "work_schedules")
_BOOLEAN_COLUMNS = {"is_active", "is_work", "affects_allowance"}
_INTEGER_COLUMNS = {"sort_order"}

# 운영단위 유형 내부값 (migration 003 teams.unit_type CHECK 와 동일).
UNIT_TYPES = ("SHIFT", "GENERAL")

# 조직 그룹(organization_groups) 자연키 계약 컬럼 (migration 004).
ORG_GROUP_COLUMNS = ["group_code", "group_name", "sort_order", "description", "is_active"]


class SupabaseDataError(RuntimeError):
    """A sanitized Supabase operation failure."""


class SupabaseTransientError(SupabaseDataError):
    """일시적(재시도 가능) 통신 오류로 판정된 실패.

    ``SupabaseDataError`` 의 하위형이므로 기존 ``except SupabaseDataError`` 경로는
    그대로 잡는다. 비멱등 쓰기(예: near-miss INSERT)에서 '결과 불명(ambiguous)'을
    타입으로 신뢰성 있게 구분해, 맹목 재시도로 중복을 만들지 않게 하는 데 쓴다."""


# --- 저장 부분성공 결과 계약 (Phase2 §8-1·§10-4, 위험 #1) ------------------
# 프레임워크 비의존(=views 를 import 하지 않음) 결과 원장. 화면 controller 는
# ``to_persist_kwargs()`` 로 ``views.master.lifecycle.PersistResult`` 를 만들 수
# 있고, 저장 계약을 바꾸지 않는 기존 호출부는 이 타입을 몰라도 된다(추가형).
#
# 왜 필요한가: ``_upsert`` 는 WRITE_BATCH_SIZE(500) chunk 를 순차 실행하며
# transaction 이 아니다. 중간 batch 실패 시 앞 batch 는 이미 저장된다. 조직은
# 부서/운영단위가 별도 호출이라 더 취약하다. 진짜 원자성은 서버 RPC/transaction
# (=migration, 승인 필요)이 필요하므로, 그 전까지 "무엇이 저장되고 무엇이
# 실패했는지"를 자연키로 드러내는 것을 잠정 계약으로 삼는다.
@dataclass
class BatchWriteResult:
    """단일 저장 명령(한 테이블/한 단계)의 부분성공 결과.

    - ``saved_keys``/``failed_keys``: 자연키(단일 컬럼=문자열, 복합키=튜플) 목록.
    - ``error``: 실패/불명 사유(사용자 문구, 이미 sanitize 됨).
    - ``retryable``: 실패분 재시도 가능 여부(검증 실패는 False).
    - ``unknown``: 결과 불명(일시적 소켓/네트워크 오류로 저장 여부를 알 수 없음).
      전체 성공으로 추정하지 않고 '재조회 필요'로 표기하기 위한 플래그.
    """

    saved_keys: list = field(default_factory=list)
    failed_keys: list = field(default_factory=list)
    error: str | None = None
    retryable: bool = False
    unknown: bool = False

    @property
    def ok(self) -> bool:
        """대상이 모두 성공하고 실패/불명이 없을 때만 True."""
        return not self.failed_keys and not self.unknown and self.error is None

    @property
    def partial(self) -> bool:
        return bool(self.saved_keys) and (bool(self.failed_keys) or self.unknown)

    def merge(self, other: "BatchWriteResult") -> "BatchWriteResult":
        """여러 단계(예: 조직 부서→운영단위) 결과를 하나로 합친다.

        두 단계가 모두 성공해야 전체 성공이다. 앞 단계 성공 + 뒤 단계 실패는
        ``partial`` 로 드러난다(조직 2단계 저장의 부분성공 표면화)."""
        return BatchWriteResult(
            saved_keys=list(self.saved_keys) + list(other.saved_keys),
            failed_keys=list(self.failed_keys) + list(other.failed_keys),
            error=self.error or other.error,
            retryable=self.retryable or other.retryable,
            unknown=self.unknown or other.unknown,
        )

    def to_persist_kwargs(self) -> dict:
        """``PersistResult(page_id=..., **result.to_persist_kwargs())`` 로 매핑."""
        return {
            "succeeded_keys": list(self.saved_keys),
            "failed_keys": list(self.failed_keys),
            "error": self.error,
            "retryable": self.retryable,
            "unknown": self.unknown,
        }


# --- migration readiness 3-state (Phase2 §8-5·§10-6, 위험 #5) --------------
# ``org_extensions_ready() -> bool`` 는 미적용과 probe 실패를 모두 False 로 접는다
# (안전하지만 UX 상 원인을 구분하지 못함). 아래 3-state probe 는 라이브 스키마를
# read-only 로 확인해 READY/NOT_READY(컬럼 없음)/PROBE_ERROR(확인 자체 실패)를
# 구분한다. 실제 WRITE 차단은 여전히 bool gate 로 하므로(오분류가 쓰기를 열지
# 않음) 3-state 는 배너 문구·재확인 UX 전용이다.
READINESS_READY = "READY"
READINESS_NOT_READY = "NOT_READY"
READINESS_PROBE_ERROR = "PROBE_ERROR"

# undefined-column / schema-cache 오류 표식 → NOT_READY(마이그레이션 미적용).
# 그 외 오류(권한/네트워크)는 PROBE_ERROR(확인 실패)로 본다.
_MISSING_COLUMN_MARKERS = (
    "42703", "does not exist", "could not find", "PGRST204", "PGRST203", "schema cache",
)


def is_missing_column_error(exc: Exception) -> bool:
    """예외가 '컬럼/스키마 미적용'(undefined-column / schema-cache) 신호인지 판정한다.

    True → 마이그레이션 미적용 등 **정상적 미준비**(호출부가 능력 없음=False 로 접어도
    되는 fail-closed 상황). False → 그 외(권한/네트워크 등) 오류로, '미적용'으로 단정할
    수 없다(호출부가 은폐하지 말고 전파할 근거). ``near_miss_extensions_ready()``/
    ``near_miss_extensions_probe()`` 의 NOT_READY vs PROBE_ERROR 판정과 **같은 표식**을
    써서, 능력 조회 폴백과 readiness 3-state 가 '무엇을 미준비로 볼지'에서 어긋나지
    않게 한다."""
    return any(marker in repr(exc) for marker in _MISSING_COLUMN_MARKERS)


def _sanitized_error(
    action: str, table: str, exc: Exception, *, transient: bool = False
) -> SupabaseDataError:
    message = str(exc)
    try:
        url, key = config.supabase_settings()
        message = message.replace(url, "<supabase>").replace(key, "<redacted>")
    except Exception:
        pass
    cls = SupabaseTransientError if transient else SupabaseDataError
    return cls(f"Supabase {table} {action} 실패: {message}")


@lru_cache(maxsize=1)
def client() -> Client:
    url, service_role_key = config.supabase_settings()
    try:
        return create_client(url, service_role_key)
    except Exception as exc:
        raise _sanitized_error("연결", "client", exc) from exc


def reset_client() -> None:
    """Drop the cached client so a subsequent call creates a fresh connection."""
    client.cache_clear()
    reset_org_readiness()


def reset_org_readiness() -> None:
    """org 확장 스키마 readiness 캐시를 비운다(다음 확인에서 재프로브).

    실행 중 migration 004 가 적용된 뒤 프로세스 재시작 없이 재평가하려면 이
    경로를 쓴다(Phase2 blocking 6 — readiness cache 재평가 절차)."""
    global _ORG_READY, _ORG_PROBE
    _ORG_READY = None
    _ORG_PROBE = None


# Windows 비동기 소켓의 일시 오류 표식 (예: WinError 10035 — 즉시 완료 실패).
# 이런 오류는 영구 장애가 아니므로 1회에 한해 재시도한다 (무한 재시도 금지).
_TRANSIENT_MARKERS = ("10035", "10054", "ConnectionResetError", "ReadError", "ConnectError")

# PostgreSQL unique_violation SQLSTATE. PostgREST/postgrest-py 는 이 코드를 예외
# 속성(code) 또는 details 에 담는다. report_no 채번 충돌을 텍스트("duplicate key")가
# 아니라 이 구조적 코드로 판정한다(로케일/문구 변화에 견고).
_UNIQUE_VIOLATION_SQLSTATE = "23505"


def _is_unique_violation(exc: Exception) -> bool:
    """예외가 PostgreSQL unique_violation(23505)인지 구조적으로 판정한다.

    원 예외(또는 __cause__ 로 연결된 원 예외)의 ``code``/``details`` 속성을 우선
    확인하고, 없으면 sanitize 된 메시지 문자열에서 코드 문자열을 폴백 검사한다."""
    seen = []
    cursor: BaseException | None = exc
    while cursor is not None and cursor not in seen and len(seen) < 8:
        seen.append(cursor)
        for attr in ("code", "details", "message"):
            value = getattr(cursor, attr, None)
            if value is not None and _UNIQUE_VIOLATION_SQLSTATE in str(value):
                return True
        cursor = getattr(cursor, "__cause__", None)
    return _UNIQUE_VIOLATION_SQLSTATE in str(exc)


def _execute(query, action: str, table: str, *, retry_transient: bool = True):
    """query.execute() 를 실행하되 일시적 소켓 오류는 1회 재시도한다.

    ``retry_transient=False`` 는 비멱등(non-idempotent) 쓰기(예: INSERT)에서 쓴다.
    일시 오류로 실패한 INSERT 는 서버에 실제로 반영됐는지 불명(ambiguous)하므로
    맹목 재시도하면 중복 레코드를 만들 수 있다 — 이 경우 재시도하지 않고 원 오류를
    그대로 올려 호출부가 '재조회 필요'로 다루게 한다(fail-closed)."""
    try:
        return query.execute()
    except Exception as exc:
        is_transient = any(marker in repr(exc) for marker in _TRANSIENT_MARKERS)
        if is_transient and retry_transient:
            try:
                return query.execute()  # 일시적 소켓 오류 1회 재시도(멱등 연산만)
            except Exception as retry_exc:
                retry_transient_marker = any(
                    marker in repr(retry_exc) for marker in _TRANSIENT_MARKERS
                )
                raise _sanitized_error(
                    action, table, retry_exc, transient=retry_transient_marker
                ) from retry_exc
        raise _sanitized_error(action, table, exc, transient=is_transient) from exc


def _select_all(table: str, columns: str = "*", query_builder=None) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        query = client().table(table).select(columns)
        if query_builder is not None:
            query = query_builder(query)
        response = _execute(query.range(start, start + PAGE_SIZE - 1), "조회", table)
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def _chunks(records: list[dict], size: int = WRITE_BATCH_SIZE):
    for start in range(0, len(records), size):
        yield records[start:start + size]


def _upsert(table: str, records: list[dict], on_conflict: str) -> None:
    for batch in _chunks(records):
        query = client().table(table).upsert(batch, on_conflict=on_conflict)
        _execute(query, "upsert", table)


def _upsert_returning(table: str, records: list[dict], on_conflict: str) -> list[dict]:
    """upsert 후 실제 저장된 행(id 포함)을 반환한다. INSERT·UPDATE 모두 대상."""
    saved: list[dict] = []
    for batch in _chunks(records):
        query = client().table(table).upsert(batch, on_conflict=on_conflict)
        response = _execute(query, "upsert", table)
        saved.extend(response.data or [])
    return saved


def _natural_key(record: dict, key_cols: list[str]):
    """부분성공 원장에 쓸 사람이 읽을 수 있는 자연키(단일=str, 복합=tuple)."""
    values = tuple(str(record.get(col, "")).strip() for col in key_cols)
    return values[0] if len(values) == 1 else values


def _upsert_reported(
    table: str, payload: list[dict], on_conflict: str, keys: list
) -> BatchWriteResult:
    """``_upsert`` 와 같은 chunk 순차 저장이되, batch 경계 부분성공을 원장으로 반환한다.

    payload 와 keys 는 1:1 정렬 상태여야 한다. 한 batch 가 실패하면 그 batch 부터
    끝까지를 failed 로 표기한다(앞선 batch 는 이미 저장 → saved). 일시적 소켓 오류로
    끝난 실패는 저장 여부를 단정할 수 없어 ``unknown`` 으로 표기한다."""
    saved_keys: list = []
    cursor = 0
    for batch in _chunks(payload):
        batch_keys = keys[cursor:cursor + len(batch)]
        try:
            _execute(client().table(table).upsert(batch, on_conflict=on_conflict), "upsert", table)
        except SupabaseDataError as exc:
            remaining = keys[cursor:]
            unknown = any(marker in str(exc) for marker in _TRANSIENT_MARKERS)
            return BatchWriteResult(
                saved_keys=saved_keys,
                failed_keys=list(remaining),
                error=str(exc),
                retryable=True,
                unknown=unknown,
            )
        saved_keys.extend(batch_keys)
        cursor += len(batch)
    return BatchWriteResult(saved_keys=saved_keys)


def _reported_write(
    table: str,
    records: list[dict],
    on_conflict: str,
    key_cols: list[str],
    payload_builder: Callable[[list[dict]], list[dict]],
) -> BatchWriteResult:
    """검증(payload_builder)→batch 저장을 부분성공 원장으로 감싼다.

    payload_builder 가 던지는 검증 오류(SupabaseDataError)는 write 전이므로 대상
    전체를 failed(retryable=False)로 표기한다 — draft 를 유지하고 명시적 실패로
    controller 가 처리할 수 있게 한다. 저장 예외는 ``_upsert_reported`` 가 batch
    경계로 나눠 saved/failed 를 구분한다."""
    keys = [_natural_key(record, key_cols) for record in records]
    try:
        payload = payload_builder(records)
    except SupabaseDataError as exc:
        return BatchWriteResult(failed_keys=keys, error=str(exc), retryable=False)
    if not payload:
        return BatchWriteResult()
    return _upsert_reported(table, payload, on_conflict, keys)


def _clean_text(value, *, nullable: bool = False):
    if value is None or pd.isna(value):
        return None if nullable else ""
    text = str(value).strip()
    return text or (None if nullable else "")


def _clean_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y", "t", "on"}


def _clean_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _frame(
    rows: list[dict],
    columns: list[str],
    table: str,
    nullable_columns: Iterable[str] = (),
) -> pd.DataFrame:
    if not rows:
        # Empty object-typed boolean columns make ``df[df["is_active"]]``
        # behave like a column selection. Keep the view contract and dtypes.
        return pd.DataFrame({
            column: pd.Series(
                dtype="bool" if column in _BOOLEAN_COLUMNS
                else "int64" if column in _INTEGER_COLUMNS
                else "object"
            )
            for column in columns
        })
    frame = pd.DataFrame(rows)
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise SupabaseDataError(
            f"Supabase {table} 응답에 필수 컬럼이 없습니다: {', '.join(missing)}"
        )
    nullable = set(nullable_columns)
    null_columns = [
        column for column in columns
        if column not in nullable and frame[column].isna().any()
    ]
    if null_columns:
        raise SupabaseDataError(
            f"Supabase {table} 필수 컬럼에 NULL 값이 있습니다: {', '.join(null_columns)}"
        )
    return frame[columns].reset_index(drop=True)


def _required(row: dict, table: str, column: str):
    if column not in row:
        raise SupabaseDataError(f"Supabase {table} 응답에 필수 컬럼이 없습니다: {column}")
    value = row[column]
    if value is None:
        raise SupabaseDataError(f"Supabase {table}.{column} 필수값이 NULL입니다.")
    return value


def _optional(row: dict, table: str, column: str):
    if column not in row:
        raise SupabaseDataError(f"Supabase {table} 응답에 필수 컬럼이 없습니다: {column}")
    return row[column]


def _mapped(mapping: dict, key, relation: str):
    value = mapping.get(str(key))
    if value is None:
        raise SupabaseDataError(f"Supabase FK 매핑을 찾을 수 없습니다: {relation}={key}")
    return value


@st.cache_data(ttl=_MAP_CACHE_TTL, show_spinner=False)
def _department_maps() -> tuple[dict[str, int], dict[str, str]]:
    rows = _select_all("departments", "id,dept_code")
    by_code = {
        str(_required(row, "departments", "dept_code")): _required(row, "departments", "id")
        for row in rows
    }
    by_id = {str(value): key for key, value in by_code.items()}
    return by_code, by_id


@st.cache_data(ttl=_MAP_CACHE_TTL, show_spinner=False)
def _team_maps() -> tuple[dict[tuple[str, str], int], dict[str, str]]:
    # _department_maps() 도 memoize 되어 있어 조 매핑이 두 번째 departments 조회를
    # 유발하지 않는다(같은 렌더 내 중복 fetch 제거).
    _, dept_by_id = _department_maps()
    rows = _select_all("teams", "id,department_id,team_code")
    by_key: dict[tuple[str, str], int] = {}
    by_id: dict[str, str] = {}
    for row in rows:
        dept_code = _mapped(
            dept_by_id, _required(row, "teams", "department_id"), "teams.department_id"
        )
        team_code = str(_required(row, "teams", "team_code"))
        team_id = _required(row, "teams", "id")
        by_key[(dept_code, team_code)] = team_id
        by_id[str(team_id)] = team_code
    return by_key, by_id


@st.cache_data(ttl=_MAP_CACHE_TTL, show_spinner=False)
def _user_maps(emp_nos: Iterable[str] | None = None) -> tuple[dict[str, int], dict[str, str]]:
    normalized = sorted({str(value).strip() for value in (emp_nos or []) if str(value).strip()})

    def filtered(query):
        return query.in_("emp_no", normalized) if normalized else query

    rows = _select_all("users", "id,emp_no", filtered if normalized else None)
    by_emp = {
        str(_required(row, "users", "emp_no")): _required(row, "users", "id")
        for row in rows
    }
    by_id = {str(value): key for key, value in by_emp.items()}
    return by_emp, by_id


def test_connection() -> dict[str, int]:
    """Verify that every required table is accessible without exposing settings."""
    counts = {}
    for table in REQUIRED_TABLES:
        response = _execute(
            client().table(table).select("*", count="exact").limit(1),
            "연결 확인",
            table,
        )
        counts[table] = int(response.count or 0)
    return counts


def get_departments() -> pd.DataFrame:
    rows = _select_all(
        "departments",
        "dept_code,dept_name,sort_order,is_active",
        lambda query: query.order("sort_order").order("dept_code"),
    )
    frame = _frame(
        rows,
        ["dept_code", "dept_name", "sort_order", "is_active"],
        "departments",
    )
    if not frame.empty:
        frame["sort_order"] = frame["sort_order"].map(_clean_int)
        frame["is_active"] = frame["is_active"].map(_clean_bool)
    return frame


def _departments_payload(records: list[dict]) -> list[dict]:
    payload = [
        {
            "dept_code": _clean_text(row.get("dept_code")),
            "dept_name": _clean_text(row.get("dept_name")),
            "sort_order": _clean_int(row.get("sort_order")),
            "is_active": _clean_bool(row.get("is_active")),
        }
        for row in records
    ]
    if any(not row["dept_code"] or not row["dept_name"] for row in payload):
        raise SupabaseDataError("부서코드와 부서명은 비어 있을 수 없습니다.")
    return payload


def upsert_departments(records: list[dict]) -> None:
    payload = _departments_payload(records)
    if payload:
        _upsert("departments", payload, "dept_code")


def upsert_departments_reported(records: list[dict]) -> BatchWriteResult:
    """부서 upsert(부분성공 원장 반환). 기존 ``upsert_departments`` 는 그대로 둔다."""
    return _reported_write(
        "departments", records, "dept_code", ["dept_code"], _departments_payload
    )


def get_teams() -> pd.DataFrame:
    _, dept_by_id = _department_maps()
    rows = _select_all(
        "teams",
        "department_id,team_code,team_name,sort_order,is_active",
        lambda query: query.order("department_id").order("sort_order").order("team_code"),
    )
    natural = []
    for row in rows:
        natural.append({
            "dept_code": _mapped(
                dept_by_id,
                _required(row, "teams", "department_id"),
                "teams.department_id",
            ),
            "team_code": str(_required(row, "teams", "team_code")),
            "team_name": str(_required(row, "teams", "team_name")),
            "sort_order": _clean_int(_required(row, "teams", "sort_order")),
            "is_active": _clean_bool(_required(row, "teams", "is_active")),
        })
    return _frame(
        natural,
        ["dept_code", "team_code", "team_name", "sort_order", "is_active"],
        "teams",
    )


def _teams_payload(records: list[dict]) -> list[dict]:
    dept_by_code, _ = _department_maps()
    payload = []
    for row in records:
        dept_code = _clean_text(row.get("dept_code"))
        if dept_code not in dept_by_code:
            raise SupabaseDataError(f"조의 부서코드를 찾을 수 없습니다: {dept_code}")
        team_code = _clean_text(row.get("team_code"))
        team_name = _clean_text(row.get("team_name"))
        if not team_code or not team_name:
            raise SupabaseDataError("조코드와 조명은 비어 있을 수 없습니다.")
        payload.append({
            "department_id": dept_by_code[dept_code],
            "team_code": team_code,
            "team_name": team_name,
            "sort_order": _clean_int(row.get("sort_order")),
            "is_active": _clean_bool(row.get("is_active")),
        })
    return payload


def upsert_teams(records: list[dict]) -> None:
    payload = _teams_payload(records)
    if payload:
        _upsert("teams", payload, "department_id,team_code")


def upsert_teams_reported(records: list[dict]) -> BatchWriteResult:
    """조 upsert(부분성공 원장 반환). 기존 ``upsert_teams`` 는 그대로 둔다."""
    return _reported_write(
        "teams", records, "department_id,team_code", ["dept_code", "team_code"], _teams_payload
    )


# --- 조직 관리 (migration 004: organization_groups 테이블 + group_id/FK 기반) ---
# 004 적용 전 라이브 DB 에는 organization_groups 테이블과 departments.group_id 가
# 없다. 조회는 호출부(db 파사드)가 org_extensions_ready() 로 분기해 안전한 기본값으로
# 폴백하고, 저장은 이 계층에서 명확한 오류로 차단한다(부분 저장·조용한 무시 없음).
# 계층은 전부 ID/FK 로 표현한다: organization_groups(id) ─< departments(group_id)
# ─< teams(department_id). 003 잔재 컬럼(department_group/group_sort_order)은 더 이상
# 읽지도 쓰지도 않는다(물리 제거는 후속 migration).
_ORG_READY: bool | None = None
_ORG_PROBE: str | None = None
# 사용자 노출 문구에는 migration 번호를 넣지 않는다(도입 이력: migration 004,
# supabase/migrations/004_org_groups.sql — 코드 주석·진단에만 남긴다).
_ORG_NOT_READY_MESSAGE = (
    "조직 스키마(조직 그룹)가 아직 준비되지 않아 저장할 수 없습니다. "
    "조직 그룹 스키마를 적용한 뒤 다시 시도하세요."
)


def org_extensions_ready() -> bool:
    """004 조직 그룹 스키마(organization_groups 테이블 + departments.group_id FK)
    사용 가능 여부를 확인한다 (1회 probe 후 캐시). 한 파일(004)로 함께 적용되므로
    둘을 묶어 판정한다 — group_id 계층 조회·저장의 준비 상태다."""
    global _ORG_READY
    if _ORG_READY is None:
        try:
            client().table("organization_groups").select("group_code").limit(1).execute()
            client().table("departments").select("group_id").limit(1).execute()
            _ORG_READY = True
        except Exception:
            _ORG_READY = False
    return _ORG_READY


def org_extensions_probe(*, force: bool = False) -> str:
    """004 조직 그룹 스키마 준비 상태를 3-state 로 확인한다(read-only, 1회 probe 후 캐시).

    반환: ``READINESS_READY`` / ``READINESS_NOT_READY`` / ``READINESS_PROBE_ERROR``.
      - READY: organization_groups 테이블 + departments.group_id 가 존재한다(004 적용됨).
      - NOT_READY: 확인은 성공했으나 없다(undefined-column/undefined-table/schema-cache).
      - PROBE_ERROR: 확인 자체가 실패했다(권한/네트워크) — 미적용으로 단정 불가.

    ``force=True`` 또는 ``reset_org_readiness()`` 후 재프로브한다(실행 중 004 적용
    반영 경로). bool ``org_extensions_ready()`` 와 캐시(_ORG_READY)를 함께 정합화한다:
    READY→True, NOT_READY→False, PROBE_ERROR→None(불명, 쓰기는 보수적으로 차단)."""
    global _ORG_READY, _ORG_PROBE
    if force:
        _ORG_PROBE = None
    if _ORG_PROBE is not None:
        return _ORG_PROBE
    try:
        client().table("organization_groups").select("group_code").limit(1).execute()
        client().table("departments").select("group_id").limit(1).execute()
        _ORG_PROBE = READINESS_READY
        _ORG_READY = True
    except Exception as exc:
        if any(marker in repr(exc) for marker in _MISSING_COLUMN_MARKERS):
            _ORG_PROBE = READINESS_NOT_READY
            _ORG_READY = False
        else:
            _ORG_PROBE = READINESS_PROBE_ERROR
            _ORG_READY = None  # 불명 — org_extensions_ready() 가 다시 보수적으로 판정
    return _ORG_PROBE


# --- 그룹(organization_groups) — 조직 1급 테이블 ---
@st.cache_data(ttl=_MAP_CACHE_TTL, show_spinner=False)
def _group_maps() -> tuple[dict[str, int], dict[str, str]]:
    """(group_code→id, id→group_code) 매핑. departments.group_id FK 해석용."""
    rows = _select_all("organization_groups", "id,group_code")
    by_code = {
        str(_required(row, "organization_groups", "group_code")):
            _required(row, "organization_groups", "id")
        for row in rows
    }
    by_id = {str(value): key for key, value in by_code.items()}
    return by_code, by_id


def get_organization_groups() -> pd.DataFrame:
    """조직 그룹 목록(ORG_GROUP_COLUMNS). 조직 스키마 capability(도입: migration 004) 준비 후에만 호출한다."""
    rows = _select_all(
        "organization_groups",
        "group_code,group_name,sort_order,description,is_active",
        lambda query: query.order("sort_order").order("group_code"),
    )
    frame = _frame(rows, ORG_GROUP_COLUMNS, "organization_groups")
    if not frame.empty:
        frame["sort_order"] = frame["sort_order"].map(_clean_int)
        frame["is_active"] = frame["is_active"].map(_clean_bool)
        frame["description"] = frame["description"].fillna("").astype(str)
    return frame


def _org_groups_payload(records: list[dict]) -> list[dict]:
    if not org_extensions_ready():
        raise SupabaseDataError(_ORG_NOT_READY_MESSAGE)
    payload = [
        {
            "group_code": _clean_text(row.get("group_code")),
            "group_name": _clean_text(row.get("group_name")),
            "sort_order": _clean_int(row.get("sort_order")),
            "description": _clean_text(row.get("description")),
            "is_active": _clean_bool(row.get("is_active")),
        }
        for row in records
    ]
    if any(not row["group_code"] or not row["group_name"] for row in payload):
        raise SupabaseDataError("그룹코드와 그룹명은 비어 있을 수 없습니다.")
    return payload


def upsert_organization_groups(records: list[dict]) -> None:
    """그룹 upsert. 조직 스키마 capability(도입: migration 004) 미준비면 저장을 차단한다. 저장코드(group_code) 수정 불가."""
    payload = _org_groups_payload(records)
    if payload:
        _upsert("organization_groups", payload, "group_code")


def upsert_organization_groups_reported(records: list[dict]) -> BatchWriteResult:
    """그룹 upsert(부분성공 원장). 조직 스키마 capability(도입: migration 004) 미준비는 전체 failed 로 표기한다."""
    return _reported_write(
        "organization_groups", records, "group_code", ["group_code"], _org_groups_payload
    )


def deactivate_organization_group(group_code: str) -> None:
    """그룹을 미사용 처리(soft-delete)한다 — 부서가 참조 중이어도 안전하다."""
    query = client().table("organization_groups").update(
        {"is_active": False}
    ).eq("group_code", group_code)
    _execute(query, "비활성화", "organization_groups")


def delete_organization_group(group_code: str) -> None:
    """그룹을 물리 삭제한다(참조 없는 그룹 전용). 부서가 group_id 로 참조 중이면
    departments_group_fk(on delete restrict) 로 삭제가 거부된다(안전장치)."""
    query = client().table("organization_groups").delete().eq("group_code", group_code)
    _execute(query, "삭제", "organization_groups")


# --- 부서(departments) + group_id FK → group_code ---
def get_departments_org() -> pd.DataFrame:
    """부서 목록 + 소속 그룹코드(group_id FK→group_code) + 비고. 조직 스키마 capability(도입: migration 004) 준비 후 호출.

    자연키 계약: dept_code, dept_name, group_code, description, sort_order, is_active.
    group_id 가 NULL(미배정)인 부서는 group_code 를 빈 문자열로 반환한다.
    """
    _, group_by_id = _group_maps()
    rows = _select_all(
        "departments",
        "dept_code,dept_name,group_id,description,sort_order,is_active",
        lambda query: query.order("sort_order").order("dept_code"),
    )
    natural = []
    for row in rows:
        group_id = row.get("group_id")
        natural.append({
            "dept_code": str(_required(row, "departments", "dept_code")),
            "dept_name": str(_required(row, "departments", "dept_name")),
            "group_code": group_by_id.get(str(group_id), "") if group_id is not None else "",
            "description": str(row.get("description") or ""),
            "sort_order": _clean_int(_required(row, "departments", "sort_order")),
            "is_active": _clean_bool(_required(row, "departments", "is_active")),
        })
    return _frame(
        natural,
        ["dept_code", "dept_name", "group_code", "description", "sort_order", "is_active"],
        "departments",
    )


def _departments_org_payload(records: list[dict]) -> list[dict]:
    if not org_extensions_ready():
        raise SupabaseDataError(_ORG_NOT_READY_MESSAGE)
    group_by_code, _ = _group_maps()
    payload = []
    for row in records:
        dept_code = _clean_text(row.get("dept_code"))
        dept_name = _clean_text(row.get("dept_name"))
        group_code = _clean_text(row.get("group_code"))
        if not dept_code or not dept_name:
            raise SupabaseDataError("부서코드와 부서명은 비어 있을 수 없습니다.")
        if not group_code:
            raise SupabaseDataError(f"부서의 소속 그룹을 선택하세요: {dept_code}")
        group_id = group_by_code.get(group_code)
        if group_id is None:
            raise SupabaseDataError(f"부서의 소속 그룹을 찾을 수 없습니다: {group_code}")
        payload.append({
            "dept_code": dept_code,
            "dept_name": dept_name,
            "group_id": group_id,
            "description": _clean_text(row.get("description")),
            "sort_order": _clean_int(row.get("sort_order")),
            "is_active": _clean_bool(row.get("is_active")),
        })
    return payload


def upsert_departments_org(records: list[dict]) -> None:
    """group_id/비고를 포함한 부서 upsert. 조직 스키마 capability(도입: migration 004) 미준비면 저장을 차단한다.

    003 잔재 컬럼(department_group/group_sort_order)은 payload 에 넣지 않는다 —
    기존 행은 값이 유지되고 신규 행은 컬럼 기본값('' / 0)으로 채워진다(무해).
    """
    payload = _departments_org_payload(records)
    if payload:
        _upsert("departments", payload, "dept_code")


def upsert_departments_org_reported(records: list[dict]) -> BatchWriteResult:
    """group_id 포함 부서 upsert(부분성공 원장). 조직 스키마 capability(도입: migration 004) 미준비는 전체 failed 로 표기한다."""
    return _reported_write(
        "departments", records, "dept_code", ["dept_code"], _departments_org_payload
    )


# --- 운영단위(teams) + department_id FK ---
def get_teams_org() -> pd.DataFrame:
    """운영단위(조) 목록 + unit_type + 비고. 조직 스키마 capability(도입: migration 004) 준비 후에만 호출한다."""
    _, dept_by_id = _department_maps()
    rows = _select_all(
        "teams",
        "department_id,team_code,team_name,unit_type,description,sort_order,is_active",
        lambda query: query.order("department_id").order("sort_order").order("team_code"),
    )
    natural = []
    for row in rows:
        natural.append({
            "dept_code": _mapped(
                dept_by_id,
                _required(row, "teams", "department_id"),
                "teams.department_id",
            ),
            "team_code": str(_required(row, "teams", "team_code")),
            "team_name": str(_required(row, "teams", "team_name")),
            "unit_type": str(_required(row, "teams", "unit_type")),
            "description": str(row.get("description") or ""),
            "sort_order": _clean_int(_required(row, "teams", "sort_order")),
            "is_active": _clean_bool(_required(row, "teams", "is_active")),
        })
    return _frame(
        natural,
        ["dept_code", "team_code", "team_name", "unit_type", "description", "sort_order", "is_active"],
        "teams",
    )


def _teams_org_payload(records: list[dict]) -> list[dict]:
    if not org_extensions_ready():
        raise SupabaseDataError(_ORG_NOT_READY_MESSAGE)
    dept_by_code, _ = _department_maps()
    payload = []
    for row in records:
        dept_code = _clean_text(row.get("dept_code"))
        if dept_code not in dept_by_code:
            raise SupabaseDataError(f"운영단위의 부서코드를 찾을 수 없습니다: {dept_code}")
        team_code = _clean_text(row.get("team_code"))
        team_name = _clean_text(row.get("team_name"))
        if not team_code or not team_name:
            raise SupabaseDataError("운영단위 코드와 명칭은 비어 있을 수 없습니다.")
        unit_type = _clean_text(row.get("unit_type")) or "SHIFT"
        if unit_type not in UNIT_TYPES:
            raise SupabaseDataError(f"운영단위 유형이 유효하지 않습니다: {unit_type}")
        payload.append({
            "department_id": dept_by_code[dept_code],
            "team_code": team_code,
            "team_name": team_name,
            "unit_type": unit_type,
            "description": _clean_text(row.get("description")),
            "sort_order": _clean_int(row.get("sort_order")),
            "is_active": _clean_bool(row.get("is_active")),
        })
    return payload


def upsert_teams_org(records: list[dict]) -> None:
    """unit_type/비고를 포함한 운영단위 upsert. 조직 스키마 capability(도입: migration 004) 미준비면 저장을 차단한다."""
    payload = _teams_org_payload(records)
    if payload:
        _upsert("teams", payload, "department_id,team_code")


def upsert_teams_org_reported(records: list[dict]) -> BatchWriteResult:
    """unit_type 포함 운영단위 upsert(부분성공 원장). 조직 스키마 capability(도입: migration 004) 미준비는 전체 failed."""
    return _reported_write(
        "teams", records, "department_id,team_code", ["dept_code", "team_code"], _teams_org_payload
    )


def _clean_order(value):
    """display_order 정규화 — 빈 값/NaN 은 None(미지정), 그 외 int."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "<na>"}:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def get_users() -> pd.DataFrame:
    """사용자 목록. display_order 는 조직 확장(004) 적용 시 실제 값, 미적용이면 NULL 컬럼."""
    _, dept_by_id = _department_maps()
    _, team_by_id = _team_maps()
    with_order = org_extensions_ready()
    select_cols = "emp_no,name,department_id,team_id,position,role,is_active"
    if with_order:
        select_cols += ",display_order"
    rows = _select_all("users", select_cols, lambda query: query.order("emp_no"))
    natural = []
    for row in rows:
        team_id = _optional(row, "users", "team_id")
        natural.append({
            "emp_no": str(_required(row, "users", "emp_no")),
            "name": str(_required(row, "users", "name")),
            "dept_code": _mapped(
                dept_by_id,
                _required(row, "users", "department_id"),
                "users.department_id",
            ),
            "team_code": _mapped(team_by_id, team_id, "users.team_id")
            if team_id is not None else "",
            "position": str(_required(row, "users", "position")),
            "role": str(_required(row, "users", "role")).strip().upper(),
            "is_active": _clean_bool(_required(row, "users", "is_active")),
            "display_order": _clean_order(row.get("display_order")) if with_order else None,
        })
    return _frame(
        natural,
        ["emp_no", "name", "dept_code", "team_code", "position", "role", "is_active",
         "display_order"],
        "users",
        nullable_columns=("display_order",),
    )


def _users_payload(records: list[dict]) -> list[dict]:
    with_order = org_extensions_ready()
    blocked_emp_nos = [
        _clean_text(row.get("emp_no")) or "(사번 없음)"
        for row in records
        if _clean_order(row.get("display_order")) is not None
    ] if not with_order else []
    if blocked_emp_nos:
        raise SupabaseDataError(
            "조직 스키마(조직 그룹) 미준비 상태에서는 사용자 표시순서를 저장할 수 없습니다: "
            + ", ".join(blocked_emp_nos)
        )

    dept_by_code, _ = _department_maps()
    team_by_key, _ = _team_maps()
    payload = []
    for row in records:
        dept_code = _clean_text(row.get("dept_code"))
        team_code = _clean_text(row.get("team_code"))
        if dept_code not in dept_by_code:
            raise SupabaseDataError(f"사용자의 부서코드를 찾을 수 없습니다: {dept_code}")
        team_id = None
        if team_code:
            team_id = team_by_key.get((dept_code, team_code))
            if team_id is None:
                raise SupabaseDataError(f"사용자의 조를 찾을 수 없습니다: {dept_code}/{team_code}")
        emp_no = _clean_text(row.get("emp_no"))
        name = _clean_text(row.get("name"))
        role = _clean_text(row.get("role")).upper()
        if not emp_no or not name or role not in config.ROLES:
            raise SupabaseDataError(f"사용자 필수값 또는 역할이 유효하지 않습니다: {emp_no}")
        record = {
            "emp_no": emp_no,
            "name": name,
            "department_id": dept_by_code[dept_code],
            "team_id": team_id,
            "position": _clean_text(row.get("position")),
            "role": role,
            "is_active": _clean_bool(row.get("is_active")),
        }
        if with_order:
            record["display_order"] = _clean_order(row.get("display_order"))
        payload.append(record)
    return payload


def upsert_users(records: list[dict]) -> None:
    """사용자 upsert. 조직 스키마 capability(도입: migration 004) 미준비 상태의 display_order 입력은 전체 차단한다.

    표시순서가 모두 NULL이면 기존 사용자 필드만 저장할 수 있지만, 값이 하나라도
    있으면 일부 필드만 성공하는 상태를 만들지 않도록 DB 조회 전에 실패시킨다.
    """
    payload = _users_payload(records)
    if payload:
        _upsert("users", payload, "emp_no")


def upsert_users_reported(records: list[dict]) -> BatchWriteResult:
    """사용자 upsert(부분성공 원장). 조직 스키마 capability(도입: migration 004) 미준비 + 표시순서 입력은 전체 failed(비재시도)."""
    return _reported_write("users", records, "emp_no", ["emp_no"], _users_payload)


def get_work_types() -> pd.DataFrame:
    columns = [
        "code", "name", "category", "short_label", "start_time", "end_time",
        "color", "is_work", "affects_allowance", "description", "sort_order", "is_active",
    ]
    rows = _select_all(
        "work_types",
        ",".join(columns),
        lambda query: query.order("sort_order").order("code"),
    )
    frame = _frame(
        rows,
        columns,
        "work_types",
        nullable_columns=("start_time", "end_time", "color"),
    )
    if not frame.empty:
        for column in ("start_time", "end_time"):
            frame[column] = frame[column].fillna("").astype(str).str.slice(0, 5)
        for column in ("is_work", "affects_allowance", "is_active"):
            frame[column] = frame[column].map(_clean_bool)
        frame["sort_order"] = frame["sort_order"].map(_clean_int)
        for column in ("color", "description"):
            frame[column] = frame[column].fillna("").astype(str)
    return frame


def _work_types_payload(records: list[dict]) -> list[dict]:
    payload = []
    for row in records:
        code = _clean_text(row.get("code"))
        name = _clean_text(row.get("name"))
        category = _clean_text(row.get("category"))
        short_label = _clean_text(row.get("short_label"))
        if not all((code, name, category, short_label)):
            raise SupabaseDataError(f"근무형태 필수값이 비어 있습니다: {code}")
        payload.append({
            "code": code,
            "name": name,
            "category": category,
            "short_label": short_label,
            "start_time": _clean_text(row.get("start_time"), nullable=True),
            "end_time": _clean_text(row.get("end_time"), nullable=True),
            "color": _clean_text(row.get("color"), nullable=True),
            "is_work": _clean_bool(row.get("is_work")),
            "affects_allowance": _clean_bool(row.get("affects_allowance")),
            "description": _clean_text(row.get("description")),
            "sort_order": _clean_int(row.get("sort_order")),
            "is_active": _clean_bool(row.get("is_active")),
        })
    return payload


def upsert_work_types(records: list[dict]) -> None:
    payload = _work_types_payload(records)
    if payload:
        _upsert("work_types", payload, "code")


def upsert_work_types_reported(records: list[dict]) -> BatchWriteResult:
    """근무형태 upsert(부분성공 원장 반환). 기존 ``upsert_work_types`` 는 그대로 둔다."""
    return _reported_write("work_types", records, "code", ["code"], _work_types_payload)


def get_shift_groups() -> pd.DataFrame:
    """근무조 기준정보 (자연키: dept_code, shift_code)."""
    _, dept_by_id = _department_maps()
    rows = _select_all(
        "shift_groups",
        "department_id,shift_code,shift_name,sort_order,is_active",
        lambda query: query.order("department_id").order("sort_order").order("shift_code"),
    )
    natural = []
    for row in rows:
        natural.append({
            "dept_code": _mapped(
                dept_by_id,
                _required(row, "shift_groups", "department_id"),
                "shift_groups.department_id",
            ),
            "shift_code": str(_required(row, "shift_groups", "shift_code")),
            "shift_name": str(_required(row, "shift_groups", "shift_name")),
            "sort_order": _clean_int(_required(row, "shift_groups", "sort_order")),
            "is_active": _clean_bool(_required(row, "shift_groups", "is_active")),
        })
    return _frame(
        natural,
        ["dept_code", "shift_code", "shift_name", "sort_order", "is_active"],
        "shift_groups",
    )


def upsert_shift_groups(records: list[dict]) -> None:
    dept_by_code, _ = _department_maps()
    payload = []
    for row in records:
        dept_code = _clean_text(row.get("dept_code"))
        if dept_code not in dept_by_code:
            raise SupabaseDataError(f"근무조의 부서코드를 찾을 수 없습니다: {dept_code}")
        shift_code = _clean_text(row.get("shift_code"))
        shift_name = _clean_text(row.get("shift_name"))
        if not shift_code or not shift_name:
            raise SupabaseDataError("근무조 코드와 근무조명은 비어 있을 수 없습니다.")
        payload.append({
            "department_id": dept_by_code[dept_code],
            "shift_code": shift_code,
            "shift_name": shift_name,
            "sort_order": _clean_int(row.get("sort_order")),
            "is_active": _clean_bool(row.get("is_active")),
        })
    if payload:
        _upsert("shift_groups", payload, "department_id,shift_code")


def get_month_assignments(year: int, month: int, emp_nos: Iterable[str] | None = None) -> pd.DataFrame:
    """대상 월의 직원별 편성 스냅샷 (자연키 계약: SCHEDULE_ASSIGNMENT_COLUMNS)."""
    _, dept_by_id = _department_maps()
    _, team_by_id = _team_maps()
    schedule_month = validators.normalize_schedule_month((int(year), int(month)))

    normalized = sorted({str(value).strip() for value in (emp_nos or []) if str(value).strip()})
    user_by_emp, emp_by_id = _user_maps(normalized or None)
    if normalized and not user_by_emp:
        return _frame(
            [],
            ["emp_no", "schedule_month", "dept_code", "team_code", "shift_group_code"],
            "schedule_assignments",
        )

    def builder(query):
        query = query.eq("schedule_month", schedule_month)
        if normalized:
            query = query.in_("user_id", list(user_by_emp.values()))
        return query.order("user_id")

    rows = _select_all(
        "schedule_assignments",
        "user_id,schedule_month,department_id,team_id,shift_group_code",
        builder,
    )
    natural = []
    for row in rows:
        team_id = _optional(row, "schedule_assignments", "team_id")
        shift_code = _optional(row, "schedule_assignments", "shift_group_code")
        natural.append({
            "emp_no": _mapped(
                emp_by_id,
                _required(row, "schedule_assignments", "user_id"),
                "schedule_assignments.user_id",
            ),
            "schedule_month": str(_required(row, "schedule_assignments", "schedule_month")),
            "dept_code": _mapped(
                dept_by_id,
                _required(row, "schedule_assignments", "department_id"),
                "schedule_assignments.department_id",
            ),
            "team_code": _mapped(team_by_id, team_id, "schedule_assignments.team_id")
            if team_id is not None else "",
            "shift_group_code": str(shift_code or ""),
        })
    return _frame(
        natural,
        ["emp_no", "schedule_month", "dept_code", "team_code", "shift_group_code"],
        "schedule_assignments",
    )


def upsert_month_assignments(records: list[dict], require_shift: bool = True) -> dict:
    """직원·월 편성 upsert. 자연키 입력을 검증 후 id 관계값으로 변환해 저장한다.

    반환: {(emp_no, schedule_month): {id, emp_no, schedule_month, dept_code,
    team_code, shift_group_code}} — INSERT·UPDATE 모두 실제 DB 레코드(id 포함)를
    반환한다(전역 identity 추정 없음). 근무 저장이 이 id 로 연결할 수 있게 한다.

    검증(팀-부서 소속, 부서의 활성 조, 월 정규화, 직원·월 중복)은
    modules/validators 순수 함수를 사용한다. require_shift=False 면 근무조 코드
    없이 부서·팀 스냅샷만 저장하며, 이때는 shift_groups 조회도 생략한다.
    """
    dept_by_code, dept_by_id = _department_maps()
    team_by_key, team_by_id = _team_maps()
    user_by_emp, user_by_id = _user_maps()
    if require_shift:
        shift_groups = get_shift_groups()
        shift_keys = {
            (str(row["dept_code"]), str(row["shift_code"]))
            for _, row in shift_groups.iterrows()
            if bool(row["is_active"])
        }
    else:
        shift_keys = set()

    normalized, errors = validators.validate_assignment_records(
        records,
        emp_nos=set(user_by_emp),
        dept_codes=set(dept_by_code),
        team_keys=set(team_by_key),
        shift_keys=shift_keys,
        require_shift=require_shift,
    )
    if errors:
        raise SupabaseDataError("월 편성 검증 실패:\n- " + "\n- ".join(errors))

    payload = []
    for row in normalized:
        team_id = team_by_key[(row["dept_code"], row["team_code"])] if row["team_code"] else None
        payload.append({
            "user_id": user_by_emp[row["emp_no"]],
            "schedule_month": row["schedule_month"],
            "department_id": dept_by_code[row["dept_code"]],
            "team_id": team_id,
            "shift_group_code": row["shift_group_code"] or None,
        })
    result: dict[tuple[str, str], dict] = {}
    if payload:
        saved = _upsert_returning("schedule_assignments", payload, "user_id,schedule_month")
        for saved_row in saved:
            emp_no = user_by_id.get(str(saved_row["user_id"]), "")
            month = str(saved_row["schedule_month"])
            team_id = saved_row.get("team_id")
            result[(emp_no, month)] = {
                "id": saved_row["id"],
                "emp_no": emp_no,
                "schedule_month": month,
                "dept_code": dept_by_id.get(str(saved_row["department_id"]), ""),
                "team_code": team_by_id.get(str(team_id), "") if team_id is not None else "",
                "shift_group_code": str(saved_row.get("shift_group_code") or ""),
            }
    return result


def _schedule_rows(query_builder=None) -> pd.DataFrame:
    _, emp_by_id = _user_maps()
    rows = _select_all(
        "work_schedules",
        "user_id,work_date,work_type_code,note",
        query_builder,
    )
    natural = []
    for row in rows:
        emp_no = _mapped(
            emp_by_id,
            _required(row, "work_schedules", "user_id"),
            "work_schedules.user_id",
        )
        natural.append({
            "emp_no": emp_no,
            "duty_date": str(_required(row, "work_schedules", "work_date")),
            "work_type_code": str(_required(row, "work_schedules", "work_type_code")),
            "note": str(row.get("note") or ""),
        })
    return _frame(
        natural,
        ["emp_no", "duty_date", "work_type_code", "note"],
        "work_schedules",
    )


def get_schedules() -> pd.DataFrame:
    return _schedule_rows(lambda query: query.order("work_date").order("user_id"))


def get_user_schedules(emp_no: str) -> pd.DataFrame:
    user_by_emp, _ = _user_maps([emp_no])
    user_id = user_by_emp.get(str(emp_no).strip())
    if user_id is None:
        return _frame([], ["emp_no", "duty_date", "work_type_code", "note"], "work_schedules")
    return _schedule_rows(
        lambda query: query.eq("user_id", user_id).order("work_date")
    )


def get_month_schedules(emp_nos: Iterable[str], year: int, month: int) -> pd.DataFrame:
    normalized = sorted({str(value).strip() for value in emp_nos if str(value).strip()})
    user_by_emp, _ = _user_maps(normalized)
    user_ids = list(user_by_emp.values())
    if not user_ids:
        return _frame([], ["emp_no", "duty_date", "work_type_code", "note"], "work_schedules")
    start = date(int(year), int(month), 1)
    next_month = date(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1)
    return _schedule_rows(
        lambda query: query.in_("user_id", user_ids)
        .gte("work_date", start.isoformat())
        .lt("work_date", next_month.isoformat())
        .order("work_date")
        .order("user_id")
    )


def _assignment_id_index(pairs: set[tuple[int, str]]) -> dict[tuple[int, str], int]:
    """(user_id, schedule_month) -> schedule_assignment_id. 없는 키는 담지 않는다.

    work_schedules 저장 시 각 근무 행을 그 (사용자·월)에 '이미 존재하는' 편성에만
    연결하기 위한 조회다(편성 없으면 매핑 없음 → legacy NULL). 편성 upsert 이후에
    호출되므로 이번 저장에서 새로 만든 편성도 포함된다.
    """
    if not pairs:
        return {}
    user_ids = sorted({int(u) for u, _ in pairs})
    months = sorted({m for _, m in pairs})
    rows = _select_all(
        "schedule_assignments",
        "id,user_id,schedule_month",
        lambda query: query.in_("user_id", user_ids).in_("schedule_month", months),
    )
    index: dict[tuple[int, str], int] = {}
    for row in rows:
        key = (int(row["user_id"]), str(row["schedule_month"]))
        if key in pairs:
            index[key] = row["id"]
    return index


def plan_schedule_links(rows: list[dict], assignment_index: dict[tuple[int, str], int]) -> list[dict]:
    """근무 payload 각 행의 schedule_assignment_id 를 결정한다 (순수 함수).

    rows 각 항목: {user_id, work_date, work_type_code, note, schedule_month}
    - (user_id, schedule_month) 편성이 있으면 그 id 연결, 없으면 None(legacy NULL).
    키에 user_id·schedule_month 를 모두 쓰므로 다른 직원·다른 월 편성 id 가 섞이지
    않는다(복합 FK 위반·오연결 방지). 입력 행만 다루므로 기존 근무를 일괄 연결하지
    않는다.
    """
    payload = []
    for row in rows:
        key = (int(row["user_id"]), str(row["schedule_month"]))
        payload.append({
            "user_id": row["user_id"],
            "work_date": row["work_date"],
            "work_type_code": row["work_type_code"],
            "note": row.get("note", ""),
            "schedule_assignment_id": assignment_index.get(key),
        })
    return payload


def _schedule_payload(records: list[dict]) -> list[dict]:
    emp_nos = [_clean_text(row.get("emp_no")) for row in records]
    user_by_emp, _ = _user_maps(emp_nos)
    work_codes = {str(row.get("code")) for row in _select_all("work_types", "code")}
    prepared = []
    pairs: set[tuple[int, str]] = set()
    for row in records:
        emp_no = _clean_text(row.get("emp_no"))
        work_code = _clean_text(row.get("work_type_code"))
        duty_date = _clean_text(row.get("duty_date"))
        if emp_no not in user_by_emp:
            raise SupabaseDataError(f"근무표 사용자를 찾을 수 없습니다: {emp_no}")
        if work_code not in work_codes:
            raise SupabaseDataError(f"근무형태 코드를 찾을 수 없습니다: {work_code}")
        try:
            date.fromisoformat(duty_date)
        except ValueError as exc:
            raise SupabaseDataError(f"근무일자 형식이 유효하지 않습니다: {duty_date}") from exc
        user_id = user_by_emp[emp_no]
        schedule_month = validators.normalize_schedule_month(duty_date)
        pairs.add((int(user_id), schedule_month))
        prepared.append({
            "user_id": user_id,
            "work_date": duty_date,
            "work_type_code": work_code,
            "note": _clean_text(row.get("note")),
            "schedule_month": schedule_month,
        })
    # 편성 upsert 뒤 호출되므로, 존재하는 (사용자·월) 편성 id 를 각 근무 행에 연결한다.
    return plan_schedule_links(prepared, _assignment_id_index(pairs))


def upsert_schedules(records: list[dict]) -> None:
    payload = _schedule_payload(records)
    if payload:
        _upsert("work_schedules", payload, "user_id,work_date")


def replace_month_schedules(emp_nos: Iterable[str], year: int, month: int, records: list[dict]) -> None:
    normalized = sorted({str(value).strip() for value in emp_nos if str(value).strip()})
    desired = {(str(row["emp_no"]).strip(), str(row["duty_date"])) for row in records}

    # Upsert first. If validation or the write fails, existing rows are not removed.
    upsert_schedules(records)
    current = get_month_schedules(normalized, year, month)
    stale = current[
        ~current.apply(lambda row: (str(row["emp_no"]), str(row["duty_date"])) in desired, axis=1)
    ]
    for _, row in stale.iterrows():
        delete_schedule(str(row["emp_no"]), str(row["duty_date"]))


def delete_schedule(emp_no: str, duty_date: str) -> None:
    user_by_emp, _ = _user_maps([emp_no])
    user_id = user_by_emp.get(str(emp_no).strip())
    if user_id is None:
        return
    query = client().table("work_schedules").delete().eq("user_id", user_id).eq("work_date", duty_date)
    _execute(query, "삭제", "work_schedules")


def _require_test_key(value: str, prefix: str) -> None:
    if not str(value).startswith(prefix):
        raise SupabaseDataError(f"테스트 레코드만 물리 삭제할 수 있습니다: {prefix}*")


def deactivate_department(dept_code: str) -> None:
    query = client().table("departments").update({"is_active": False}).eq("dept_code", dept_code)
    _execute(query, "비활성화", "departments")


def delete_department(dept_code: str) -> None:
    """부서를 물리 삭제한다. 참조 여부 판단은 호출부(화면)가 담당하며, 참조가 있으면
    DB FK 제약으로도 삭제가 거부된다(안전장치)."""
    query = client().table("departments").delete().eq("dept_code", dept_code)
    _execute(query, "삭제", "departments")


def deactivate_team(dept_code: str, team_code: str) -> None:
    dept_by_code, _ = _department_maps()
    department_id = dept_by_code.get(dept_code)
    if department_id is None:
        return
    query = client().table("teams").update({"is_active": False}).eq("department_id", department_id).eq("team_code", team_code)
    _execute(query, "비활성화", "teams")


def delete_team(dept_code: str, team_code: str) -> None:
    """조를 물리 삭제한다. 참조 여부 판단은 호출부(화면)가 담당하며, 참조가 있으면
    DB FK 제약으로도 삭제가 거부된다(안전장치)."""
    dept_by_code, _ = _department_maps()
    department_id = dept_by_code.get(dept_code)
    if department_id is None:
        return
    query = client().table("teams").delete().eq("department_id", department_id).eq("team_code", team_code)
    _execute(query, "삭제", "teams")


def deactivate_user(emp_no: str) -> None:
    query = client().table("users").update({"is_active": False}).eq("emp_no", emp_no)
    _execute(query, "비활성화", "users")


def deactivate_work_type(code: str) -> None:
    query = client().table("work_types").update({"is_active": False}).eq("code", code)
    _execute(query, "비활성화", "work_types")


def delete_work_type(code: str) -> None:
    """근무형태를 물리 삭제한다. 참조 여부 판단은 호출부(화면)가 담당하며, 근무표가
    참조 중이면 DB FK 제약으로도 삭제가 거부된다(안전장치)."""
    query = client().table("work_types").delete().eq("code", code)
    _execute(query, "삭제", "work_types")


def hard_delete_test_user(emp_no: str) -> None:
    _require_test_key(emp_no, "TEST_EMP_")
    _execute(client().table("users").delete().eq("emp_no", emp_no), "테스트 정리", "users")


def hard_delete_test_work_type(code: str) -> None:
    _require_test_key(code, "TEST_WORK_")
    _execute(client().table("work_types").delete().eq("code", code), "테스트 정리", "work_types")


def hard_delete_test_team(dept_code: str, team_code: str) -> None:
    _require_test_key(dept_code, "TEST_DEPT_")
    _require_test_key(team_code, "TEST_TEAM_")
    dept_by_code, _ = _department_maps()
    department_id = dept_by_code.get(dept_code)
    if department_id is None:
        return
    query = client().table("teams").delete().eq("department_id", department_id).eq("team_code", team_code)
    _execute(query, "테스트 정리", "teams")


def hard_delete_test_department(dept_code: str) -> None:
    _require_test_key(dept_code, "TEST_DEPT_")
    _execute(client().table("departments").delete().eq("dept_code", dept_code), "테스트 정리", "departments")


# =========================================================================
# 아차사고(near-miss) — migration 006 (DRAFT: 실행/원격 write 승인 게이트 전)
# =========================================================================
# 006 적용 전 라이브 DB 에는 near_miss_reports 테이블과 users.is_safety_officer 가
# 없다. 조회는 호출부(db 파사드)가 near_miss_extensions_ready() 로 분기해 안전한
# 빈 결과로 폴백하고, 저장은 이 계층에서 명확한 오류로 차단한다(부분 저장·조용한
# 무시 없음 — 004 조직 확장과 같은 관행).
NEAR_MISS_TABLE = "near_miss_reports"
# report_no 채번 unique 충돌 시 bounded 재채번 재시도 상한(무한 루프 금지).
_NEAR_MISS_CREATE_RETRIES = 5
NEAR_MISS_GRADES = ("S", "A", "B", "C", "D")
NEAR_MISS_CAUSE_CODES = ("JAM", "FALL", "DROP", "HIT", "SLIP", "BURN", "PINCH", "ETC")
NEAR_MISS_STATUSES = ("SUBMITTED", "IN_REVIEW", "EVALUATED", "CLOSED", "REJECTED")

# 화면(파사드)이 보는 자연키 계약. id/report_no + 자연키(reporter_emp_no/
# evaluator_emp_no/dept_code). reporter/evaluator/부서는 ID/FK 로 저장하고 여기서
# 조인해 자연키로 되돌린다(다른 테이블 관행과 동일).
NEAR_MISS_COLUMNS = [
    "id", "report_no", "status",
    "work_name", "work_content", "incident_content", "countermeasure", "site_description",
    "proposed_grade", "confirmed_grade",
    "cause_code", "cause_detail", "incident_date",
    "reporter_emp_no", "evaluator_emp_no", "dept_code",
    "photo_paths", "rejection_reason", "evaluated_at",
    "is_active", "created_at", "updated_at",
]

_NM_READY: bool | None = None
_NM_PROBE: str | None = None
_NM_NOT_READY_MESSAGE = (
    "아차사고 스키마가 아직 준비되지 않아 저장할 수 없습니다. "
    "아차사고 스키마를 적용한 뒤 다시 시도하세요."
)
# 동시 평가/전이가 TOCTOU 로 서로의 결과를 덮어쓰는 것을 막기 위한 조건부 UPDATE
# 실패(0행) 메시지. 상태가 이미 바뀌었거나 보고서가 사라진 경우다(lost update 금지).
_NM_STALE_MESSAGE = (
    "상태가 이미 변경되어 요청을 적용할 수 없습니다(다른 사용자가 먼저 처리). "
    "목록을 재조회한 뒤 다시 시도하세요."
)


def reset_near_miss_readiness() -> None:
    """near_miss readiness 캐시를 비운다(다음 확인에서 재프로브 — 006 적용 반영 경로)."""
    global _NM_READY, _NM_PROBE
    _NM_READY = None
    _NM_PROBE = None


def near_miss_extensions_ready() -> bool:
    """006 아차사고 스키마(near_miss_reports 테이블 + users.is_safety_officer 컬럼)
    사용 가능 여부를 확인한다(1회 probe 후 캐시). 한 파일(006)로 함께 적용되므로
    둘을 묶어 판정한다.

    3-state 판정과 정합화한다(org_extensions_ready 관행): 미적용(undefined
    table/column)은 False 로 캐시하지만, probe 자체 실패(권한/네트워크 등 일시 장애)는
    영구 부재로 캐시하지 않고 다음 호출에서 재프로브한다 — 일시 장애를 '빈 데이터'로
    고착시키지 않기 위함(fail-closed: 이 경우에도 쓰기는 보수적으로 차단된다)."""
    global _NM_READY, _NM_PROBE
    if _NM_READY is None:
        try:
            client().table(NEAR_MISS_TABLE).select("id").limit(1).execute()
            client().table("users").select("is_safety_officer").limit(1).execute()
            _NM_READY = True
            _NM_PROBE = READINESS_READY  # 성공 시 직전 PROBE_ERROR 캐시를 갱신(비고착)
        except Exception as exc:
            if any(marker in repr(exc) for marker in _MISSING_COLUMN_MARKERS):
                _NM_READY = False  # 006 미적용 — 안정적으로 캐시
                _NM_PROBE = READINESS_NOT_READY
            else:
                # PROBE_ERROR: 일시 장애를 영구 부재로 캐시하지 않는다(다음 호출 재프로브).
                _NM_PROBE = None
                return False
    return _NM_READY


def near_miss_extensions_probe(*, force: bool = False) -> str:
    """006 아차사고 스키마 준비 상태를 3-state 로 확인한다(read-only, 1회 probe 후 캐시).

    반환: ``READINESS_READY`` / ``READINESS_NOT_READY`` / ``READINESS_PROBE_ERROR``.
      - READY: near_miss_reports 테이블 + users.is_safety_officer 가 존재한다(006 적용됨).
      - NOT_READY: 확인은 성공했으나 없다(undefined-table/undefined-column/schema-cache).
      - PROBE_ERROR: 확인 자체가 실패했다(권한/네트워크) — 미적용으로 단정 불가.

    ``force=True`` 또는 ``reset_near_miss_readiness()`` 후 재프로브한다. bool
    ``near_miss_extensions_ready()`` 와 캐시(_NM_READY)를 함께 정합화한다:
    READY→True, NOT_READY→False, PROBE_ERROR→불명(쓰기는 보수적으로 차단).

    PROBE_ERROR 는 **캐시하지 않는다**(sticky 방지). 일시 장애로 한 번 PROBE_ERROR 를
    받아도 다음 호출은 다시 프로브하며, 장애가 풀려 READY/NOT_READY 로 확정되면 그
    결과로 갱신된다 — outage 를 '미적용/빈 데이터'로 고착시키지 않는다."""
    global _NM_READY, _NM_PROBE
    if force:
        _NM_PROBE = None
    if _NM_PROBE is not None:
        return _NM_PROBE
    try:
        client().table(NEAR_MISS_TABLE).select("id").limit(1).execute()
        client().table("users").select("is_safety_officer").limit(1).execute()
        _NM_PROBE = READINESS_READY
        _NM_READY = True
    except Exception as exc:
        if any(marker in repr(exc) for marker in _MISSING_COLUMN_MARKERS):
            _NM_PROBE = READINESS_NOT_READY
            _NM_READY = False
        else:
            # PROBE_ERROR 는 캐시하지 않는다(_NM_PROBE=None) — 다음 호출 재프로브(비고착).
            _NM_PROBE = None
            _NM_READY = None
            return READINESS_PROBE_ERROR
    return _NM_PROBE


def user_is_safety_officer(emp_no: str) -> bool:
    """users.is_safety_officer 플래그를 사번으로 조회한다.

    컬럼이 없거나(006 미적용) 사용자를 못 찾으면 False. 오류는 sanitize 되어
    전파되므로 호출부(db._safety_officer_flag)가 안전하게 False 로 접는다."""
    emp = str(emp_no).strip()
    if not emp:
        return False
    rows = _select_all(
        "users", "emp_no,is_safety_officer", lambda query: query.eq("emp_no", emp)
    )
    for row in rows:
        return _clean_bool(row.get("is_safety_officer"))
    return False


def _near_miss_natural(rows: list[dict]) -> list[dict]:
    """near_miss 행(ID/FK)을 화면 자연키 계약으로 변환한다."""
    _, emp_by_id = _user_maps()
    _, dept_by_id = _department_maps()
    out = []
    for row in rows:
        reporter_id = row.get("reporter_user_id")
        evaluator_id = row.get("evaluator_user_id")
        dept_id = row.get("department_id")
        photo = row.get("photo_paths")
        if not isinstance(photo, list):
            photo = []
        out.append({
            "id": row.get("id"),
            "report_no": str(row.get("report_no") or ""),
            "status": str(row.get("status") or ""),
            "work_name": str(row.get("work_name") or ""),
            "work_content": str(row.get("work_content") or ""),
            "incident_content": str(row.get("incident_content") or ""),
            "countermeasure": str(row.get("countermeasure") or ""),
            "site_description": str(row.get("site_description") or ""),
            "proposed_grade": row.get("proposed_grade") or None,
            "confirmed_grade": row.get("confirmed_grade") or None,
            "cause_code": str(row.get("cause_code") or ""),
            "cause_detail": str(row.get("cause_detail") or ""),
            "incident_date": str(row.get("incident_date") or ""),
            "reporter_emp_no": emp_by_id.get(str(reporter_id), "") if reporter_id is not None else "",
            "evaluator_emp_no": emp_by_id.get(str(evaluator_id), "") if evaluator_id is not None else "",
            "dept_code": dept_by_id.get(str(dept_id), "") if dept_id is not None else "",
            "photo_paths": photo,
            "rejection_reason": row.get("rejection_reason") or None,
            "evaluated_at": str(row.get("evaluated_at") or "") or None,
            "is_active": _clean_bool(row.get("is_active")),
            "created_at": str(row.get("created_at") or ""),
            "updated_at": str(row.get("updated_at") or ""),
        })
    return out


def get_near_miss_reports(filters: dict | None = None) -> list[dict]:
    """아차사고 보고서 목록을 자연키 계약(dict 리스트)으로 반환한다.

    filters(선택): include_archived(bool), status, dept_code, cause_code,
    confirmed_grade, reporter_emp_no, date_from/date_to(ISO, incident_date 기준).
    서버 측에서 가능한 필터를 적용한다. 006 미적용이면 빈 리스트."""
    if not near_miss_extensions_ready():
        return []
    filters = filters or {}
    dept_by_code, _ = _department_maps()
    user_by_emp, _ = _user_maps()

    def builder(query):
        if not filters.get("include_archived"):
            query = query.eq("is_active", True)
        if filters.get("status"):
            query = query.eq("status", str(filters["status"]).strip())
        if filters.get("cause_code"):
            query = query.eq("cause_code", str(filters["cause_code"]).strip())
        if filters.get("confirmed_grade"):
            query = query.eq("confirmed_grade", str(filters["confirmed_grade"]).strip())
        dept_code = filters.get("dept_code")
        if dept_code and str(dept_code).strip() in dept_by_code:
            query = query.eq("department_id", dept_by_code[str(dept_code).strip()])
        reporter = filters.get("reporter_emp_no")
        if reporter and str(reporter).strip() in user_by_emp:
            query = query.eq("reporter_user_id", user_by_emp[str(reporter).strip()])
        if filters.get("date_from"):
            query = query.gte("incident_date", str(filters["date_from"]).strip())
        if filters.get("date_to"):
            query = query.lte("incident_date", str(filters["date_to"]).strip())
        return query.order("incident_date", desc=True).order("id", desc=True)

    rows = _select_all(NEAR_MISS_TABLE, "*", builder)
    return _near_miss_natural(rows)


def get_near_miss_report(report_id) -> dict | None:
    """단일 아차사고 보고서(자연키 dict) 또는 None."""
    if not near_miss_extensions_ready():
        return None
    rows = _select_all(
        NEAR_MISS_TABLE, "*", lambda query: query.eq("id", report_id).limit(1)
    )
    natural = _near_miss_natural(rows)
    return natural[0] if natural else None


def _near_miss_editable_payload(payload: dict) -> dict:
    """수정 가능한 본문 필드(자연키 입력)를 검증·정규화한다(신원/상태 제외).

    create(`_near_miss_write_payload`)와 수정(`update_near_miss_report`)이 **같은**
    필드 검증을 공유하도록 추출한 헬퍼다 — 두 경로의 검증이 어긋나 한쪽만 느슨해지는
    것을 막는다(fail-closed). 반환 dict 는 본문 저장 컬럼만 담으며 reporter/부서/상태/
    평가/감사 필드는 절대 포함하지 않는다(서버측 확정 대상)."""
    work_name = _clean_text(payload.get("work_name"))
    if not work_name:
        raise SupabaseDataError("작업명은 비어 있을 수 없습니다.")
    cause_code = _clean_text(payload.get("cause_code")).upper()
    if cause_code not in NEAR_MISS_CAUSE_CODES:
        raise SupabaseDataError(f"원인 코드가 유효하지 않습니다: {cause_code}")
    proposed = _clean_text(payload.get("proposed_grade"), nullable=True)
    if proposed is not None:
        proposed = proposed.upper()
        if proposed not in NEAR_MISS_GRADES:
            raise SupabaseDataError(f"제안 등급이 유효하지 않습니다: {proposed}")
    incident_date = _clean_text(payload.get("incident_date"))
    try:
        date.fromisoformat(incident_date)
    except ValueError as exc:
        raise SupabaseDataError(f"사고 발생일 형식이 유효하지 않습니다: {incident_date}") from exc
    photo_paths = payload.get("photo_paths") or []
    if not isinstance(photo_paths, (list, tuple)):
        raise SupabaseDataError("photo_paths 는 배열이어야 합니다.")
    return {
        "work_name": work_name,
        "work_content": _clean_text(payload.get("work_content")),
        "incident_content": _clean_text(payload.get("incident_content")),
        "countermeasure": _clean_text(payload.get("countermeasure")),
        "site_description": _clean_text(payload.get("site_description")),
        "proposed_grade": proposed,
        "cause_code": cause_code,
        "cause_detail": _clean_text(payload.get("cause_detail")),
        "incident_date": incident_date,
        "photo_paths": [str(p) for p in photo_paths],
    }


def _near_miss_write_payload(payload: dict) -> dict:
    """create 용 payload(자연키 입력)를 ID/FK 저장 레코드로 검증·변환한다.

    reporter_emp_no·부서·시각은 서버측 값이다(화면이 세션에서 채워 넘긴다 —
    클라이언트 임의값 신뢰 금지). 여기서는 관계 무결성만 재확인한다. 본문 필드 검증은
    수정 경로와 공유하는 `_near_miss_editable_payload` 로 위임한다(검증 단일화)."""
    if not near_miss_extensions_ready():
        raise SupabaseDataError(_NM_NOT_READY_MESSAGE)
    user_by_emp, _ = _user_maps()
    dept_by_code, _ = _department_maps()

    reporter_emp = _clean_text(payload.get("reporter_emp_no"))
    if reporter_emp not in user_by_emp:
        raise SupabaseDataError(f"아차사고 보고자 사번을 찾을 수 없습니다: {reporter_emp}")
    body = _near_miss_editable_payload(payload)
    dept_code = _clean_text(payload.get("dept_code"), nullable=True)
    department_id = None
    if dept_code:
        if dept_code not in dept_by_code:
            raise SupabaseDataError(f"아차사고 부서코드를 찾을 수 없습니다: {dept_code}")
        department_id = dept_by_code[dept_code]
    return {
        **body,
        "reporter_user_id": user_by_emp[reporter_emp],
        "department_id": department_id,
        "status": "SUBMITTED",
        "is_active": True,
        "created_by": _clean_text(payload.get("created_by"), nullable=True),
        "updated_by": _clean_text(payload.get("created_by"), nullable=True),
    }


def _next_report_no(year_month: str) -> str:
    """대상 연월(YYYYMM)의 다음 순번 report_no. 충돌 시 재시도는 create 가 담당."""
    prefix = str(year_month)
    rows = _select_all(
        NEAR_MISS_TABLE, "report_no",
        lambda query: query.like("report_no", f"{prefix}-%"),
    )
    max_seq = 0
    for row in rows:
        try:
            max_seq = max(max_seq, int(str(row.get("report_no")).rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            continue
    return f"{prefix}-{max_seq + 1:04d}"


def create_near_miss_report(payload: dict) -> dict:
    """아차사고 보고서를 생성한다(status=SUBMITTED). 생성된 자연키 dict 반환.

    report_no 는 incident_date 의 연월 기준으로 채번하며, **unique 충돌(SQLSTATE 23505)**
    시에만 순번을 재계산해 최대 ``_NEAR_MISS_CREATE_RETRIES`` 회 bounded 재시도한다
    (동시 삽입 collision-safe). 이 충돌은 DB 가 INSERT 를 거부한 것이므로(=미저장 확정)
    새 순번으로 재시도해도 중복이 생기지 않는다. 재시도가 소진되면 무한 루프 대신
    fail-closed '재조회 필요' 오류를 올린다.

    반대로 INSERT 는 비멱등이므로 일시적 통신 오류로 실패하면 서버 반영 여부가
    불명(ambiguous)하다. 이때는 재시도하지 않고 명시적 '재조회 필요' 오류를 올린다
    — 맹목 재시도가 중복 보고서를 조용히 만드는 것을 막는다(fail-closed)."""
    record = _near_miss_write_payload(payload)
    year_month = record["incident_date"].replace("-", "")[:6]
    for _ in range(_NEAR_MISS_CREATE_RETRIES):
        record["report_no"] = _next_report_no(year_month)
        try:
            # retry_transient=False: 비멱등 INSERT 를 일시 오류로 맹목 재시도하지 않는다.
            response = _execute(
                client().table(NEAR_MISS_TABLE).insert(record), "생성", NEAR_MISS_TABLE,
                retry_transient=False,
            )
            saved = (response.data or [None])[0]
            if saved is None:
                raise SupabaseDataError("아차사고 보고서 생성 결과가 비어 있습니다.")
            return _near_miss_natural([saved])[0]
        except SupabaseTransientError as exc:
            # 저장 여부 불명(ambiguous) — 중복 방지를 위해 재시도하지 않고 재조회를 요구한다.
            raise SupabaseDataError(
                "아차사고 보고서 저장 결과가 불명확합니다(일시적 통신 오류). "
                "중복 생성을 막기 위해 재시도하지 않았습니다. 목록을 재조회해 "
                "저장 여부를 확인한 뒤 필요할 때만 다시 제출하세요."
            ) from exc
        except SupabaseDataError as exc:
            if _is_unique_violation(exc):
                continue  # report_no 충돌(23505, DB 거부=미저장) — 재채번 후 재시도(안전)
            raise
    # bounded 재시도 소진: 무한 루프 없이 fail-closed 로 종료한다.
    raise SupabaseDataError(
        "아차사고 보고서 번호가 반복 충돌하여 채번에 실패했습니다. "
        "목록을 재조회한 뒤 다시 시도하세요."
    )


def update_near_miss_report(
    report_id, payload: dict, *, reporter_emp_no: str, updated_by=None,
) -> dict | None:
    """보고자 본인이 SUBMITTED 상태의 본문을 수정한다(원자적 조건부 UPDATE).

    ``where id=? and reporter_user_id=? and status='SUBMITTED'`` 로 갱신하므로
    **소유자·수정가능 상태(컷오프)·lost update** 를 서버측에서 함께 강제한다. 0행이면
    소유자가 아니거나 이미 상태가 바뀌었거나(검토 착수/평가/반려/종결) 보고서가 사라진
    것이므로 덮어쓰지 않고 stale 오류를 낸다(TOCTOU 방지). 본문 컬럼만 쓰며 상태/신원/
    평가 필드는 절대 갱신하지 않는다. 검증은 create 와 공유하는
    `_near_miss_editable_payload` 를 사용한다(검증 단일화)."""
    if not near_miss_extensions_ready():
        raise SupabaseDataError(_NM_NOT_READY_MESSAGE)
    user_by_emp, _ = _user_maps()
    reporter = _clean_text(reporter_emp_no)
    if reporter not in user_by_emp:
        raise SupabaseDataError(f"아차사고 보고자 사번을 찾을 수 없습니다: {reporter}")
    updates = _near_miss_editable_payload(payload)
    if updated_by is not None:
        updates["updated_by"] = _clean_text(updated_by, nullable=True)
    query = (
        client().table(NEAR_MISS_TABLE).update(updates)
        .eq("id", report_id)
        .eq("reporter_user_id", user_by_emp[reporter])
        .eq("status", "SUBMITTED")
    )
    response = _execute(query, "수정", NEAR_MISS_TABLE)
    saved = (response.data or [None])[0]
    if saved is None:
        # 조건부 0행 = 비소유자/비SUBMITTED/삭제됨 — 덮어쓰지 않고 재조회를 요구한다.
        raise SupabaseDataError(_NM_STALE_MESSAGE)
    return _near_miss_natural([saved])[0]


def update_near_miss_status(
    report_id, status: str, *, expected_status=None, rejection_reason=None,
    clear_evaluation: bool = False, updated_by=None,
) -> dict | None:
    """아차사고 상태를 변경한다(전이 검증은 파사드가 수행 후 호출).

    clear_evaluation=True 면 평가 필드(확정등급/평가자/평가시각)를 NULL 로 되돌린다
    (EVALUATED→IN_REVIEW 재개 시 near_miss_eval_consistency 제약 충족).

    ``expected_status`` 가 주어지면 원자적 조건부 UPDATE(``where id=? and status=?``)로
    수행하고 갱신 행 수를 확인한다. 0행이면 상태가 이미 바뀌었거나(다른 사용자가 먼저
    처리 — TOCTOU) 보고서가 없어진 것이므로 덮어쓰지 않고 stale 오류를 올린다."""
    if not near_miss_extensions_ready():
        raise SupabaseDataError(_NM_NOT_READY_MESSAGE)
    target = str(status).strip()
    # →CLOSED 는 이 일반 상태변경 경로로 직접 UPDATE 할 수 없다(Codex P1-3, repository 이중방어).
    # 종결은 확인된 활성 개선조치를 요구하는 하드게이트 RPC(close_near_miss_report)로만 가능하며,
    # DB trigger(near_miss_close_requires_confirmed_capa)도 EVALUATED→CLOSED 만 허용한다. facade
    # 진입부 차단에 더해 repository 계층에서도 fail-closed 로 막는다.
    if target.upper() == "CLOSED":
        raise SupabaseDataError(
            "종결(CLOSED)은 일반 상태변경으로 할 수 없습니다. "
            "close_near_miss_report(확인+종결 하드게이트 RPC)를 사용하세요."
        )
    updates: dict = {"status": target}
    if rejection_reason is not None:
        updates["rejection_reason"] = _clean_text(rejection_reason, nullable=True)
    if clear_evaluation:
        updates["confirmed_grade"] = None
        updates["evaluator_user_id"] = None
        updates["evaluated_at"] = None
    if updated_by is not None:
        updates["updated_by"] = _clean_text(updated_by, nullable=True)
    query = client().table(NEAR_MISS_TABLE).update(updates).eq("id", report_id)
    if expected_status is not None:
        query = query.eq("status", str(expected_status).strip())
    response = _execute(query, "상태변경", NEAR_MISS_TABLE)
    saved = (response.data or [None])[0]
    if saved is None:
        if expected_status is not None:
            raise SupabaseDataError(_NM_STALE_MESSAGE)  # 조건부 0행 = lost update 방지
        return get_near_miss_report(report_id)
    return _near_miss_natural([saved])[0]


def evaluate_near_miss(
    report_id, confirmed_grade: str, *, evaluator_emp_no: str,
    expected_status=None, updated_by=None,
) -> dict | None:
    """평가 확정: status=EVALUATED + 확정등급/평가자/평가시각 설정.

    ``expected_status`` 가 주어지면 원자적 조건부 UPDATE(``where id=? and status=?``)로
    수행한다 — 두 평가자가 동시에 같은 보고서를 평가해도 하나만 성공하고(0행 갱신 시
    stale 오류) 다른 하나는 덮어쓰지 못한다(TOCTOU 방지)."""
    if not near_miss_extensions_ready():
        raise SupabaseDataError(_NM_NOT_READY_MESSAGE)
    grade = _clean_text(confirmed_grade).upper()
    if grade not in NEAR_MISS_GRADES:
        raise SupabaseDataError(f"확정 등급이 유효하지 않습니다: {grade}")
    user_by_emp, _ = _user_maps()
    evaluator = _clean_text(evaluator_emp_no)
    if evaluator not in user_by_emp:
        raise SupabaseDataError(f"평가자 사번을 찾을 수 없습니다: {evaluator}")
    from datetime import datetime, timezone
    updates = {
        "status": "EVALUATED",
        "confirmed_grade": grade,
        "evaluator_user_id": user_by_emp[evaluator],
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": _clean_text(updated_by, nullable=True),
    }
    query = client().table(NEAR_MISS_TABLE).update(updates).eq("id", report_id)
    if expected_status is not None:
        query = query.eq("status", str(expected_status).strip())
    response = _execute(query, "평가", NEAR_MISS_TABLE)
    saved = (response.data or [None])[0]
    if saved is None:
        if expected_status is not None:
            raise SupabaseDataError(_NM_STALE_MESSAGE)  # 조건부 0행 = 이미 평가됨/변경됨
        return get_near_miss_report(report_id)
    return _near_miss_natural([saved])[0]


def set_near_miss_active(report_id, is_active: bool, *, updated_by=None) -> None:
    """보존(archival) 플래그 토글. 철회/반려는 상태로 표현하며 이 경로가 아니다."""
    if not near_miss_extensions_ready():
        raise SupabaseDataError(_NM_NOT_READY_MESSAGE)
    updates: dict = {"is_active": bool(is_active)}
    if updated_by is not None:
        updates["updated_by"] = _clean_text(updated_by, nullable=True)
    _execute(
        client().table(NEAR_MISS_TABLE).update(updates).eq("id", report_id),
        "보존변경", NEAR_MISS_TABLE,
    )


def near_miss_stats(by: str = "status", filters: dict | None = None) -> dict:
    """서버 조회 결과를 by 기준으로 집계한다(등급/부서/기간/원인/상태)."""
    rows = get_near_miss_reports(filters)
    return _aggregate_near_miss(rows, by)


def _aggregate_near_miss(rows: list[dict], by: str) -> dict:
    """자연키 dict 리스트를 by 기준으로 count 집계(순수 함수 — sample/supabase 공용)."""
    key_of = _near_miss_stat_key(by)
    counts: dict = {}
    for row in rows:
        key = key_of(row)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (str(kv[0]))))


def _near_miss_stat_key(by: str):
    by = str(by or "status").strip().lower()
    if by == "grade":
        return lambda r: str(r.get("confirmed_grade") or "미확정")
    if by == "dept":
        return lambda r: str(r.get("dept_code") or "미지정")
    if by == "cause":
        return lambda r: str(r.get("cause_code") or "미지정")
    if by == "period":
        return lambda r: str(r.get("incident_date") or "")[:7]  # YYYY-MM
    if by == "status":
        return lambda r: str(r.get("status") or "")
    raise ValueError(f"지원하지 않는 통계 기준입니다: {by}")


# =========================================================================
# 아차사고 개선조치(CAPA) — migration 007 (DRAFT: 실행/원격 write 승인 게이트 전)
# =========================================================================
# 007 적용 전 라이브 DB 에는 near_miss_improvements 테이블과 near_miss_reports 의
# 보완요청 컬럼(revision_request_reason 등)이 없다. 조회는 호출부(db 파사드)가
# near_miss_improvement_extensions_ready() 로 분기해 안전한 빈 결과로 폴백하고, 저장은
# 이 계층에서 명확한 오류로 차단한다(006 관행 동일). 종결은 원자 RPC 로만 한다.
NEAR_MISS_IMPROVEMENT_TABLE = "near_miss_improvements"
NEAR_MISS_IMPROVEMENT_SUBMIT_STATES = ("DRAFT", "SUBMITTED")
NEAR_MISS_IMPROVEMENT_CONFIRM_STATES = ("PENDING", "CONFIRMED", "REJECTED")

# 화면(파사드)이 보는 자연키 계약. 사람 참조는 ID/FK 로 저장하고 여기서 emp_no 로 되돌린다.
NEAR_MISS_IMPROVEMENT_COLUMNS = [
    "id", "report_id",
    "assignee_emp_no", "designated_confirmer_emp_no", "confirmed_by_emp_no", "rejected_by_emp_no",
    "action_body", "result_body", "due_date",
    "submit_status", "confirm_status",
    "submitted_at", "confirmed_at", "rejected_at", "revision_note",
    "is_active", "created_at", "updated_at",
]

_NMI_READY: bool | None = None
_NMI_PROBE: str | None = None
_NMI_NOT_READY_MESSAGE = (
    "아차사고 개선조치 스키마가 아직 준비되지 않아 저장할 수 없습니다. "
    "개선조치 스키마(007)를 적용한 뒤 다시 시도하세요."
)
_NMI_STALE_MESSAGE = (
    "개선조치 상태가 이미 변경되어 요청을 적용할 수 없습니다(다른 사용자가 먼저 처리). "
    "목록을 재조회한 뒤 다시 시도하세요."
)


def reset_near_miss_improvement_readiness() -> None:
    """개선조치(007) readiness 캐시를 비운다(다음 확인에서 재프로브 — 적용 반영 경로)."""
    global _NMI_READY, _NMI_PROBE
    _NMI_READY = None
    _NMI_PROBE = None


def near_miss_improvement_extensions_ready() -> bool:
    """007 개선조치 스키마(near_miss_improvements 테이블 + near_miss_reports 보완요청 컬럼)
    사용 가능 여부. 006 관행(near_miss_extensions_ready)과 동일한 3-state 정합화:
    미적용은 False 로 캐시, probe 자체 실패(일시 장애)는 캐시하지 않고 재프로브한다."""
    global _NMI_READY, _NMI_PROBE
    if _NMI_READY is None:
        try:
            client().table(NEAR_MISS_IMPROVEMENT_TABLE).select("id").limit(1).execute()
            client().table(NEAR_MISS_TABLE).select("revision_request_reason").limit(1).execute()
            _NMI_READY = True
            _NMI_PROBE = READINESS_READY
        except Exception as exc:
            if any(marker in repr(exc) for marker in _MISSING_COLUMN_MARKERS):
                _NMI_READY = False
                _NMI_PROBE = READINESS_NOT_READY
            else:
                _NMI_PROBE = None
                return False
    return _NMI_READY


def near_miss_improvement_extensions_probe(*, force: bool = False) -> str:
    """007 개선조치 스키마 준비 상태 3-state(read-only). near_miss_extensions_probe 관행 복제.

    반환: READINESS_READY / READINESS_NOT_READY(미적용) / READINESS_PROBE_ERROR(확인 실패).
    PROBE_ERROR 는 캐시하지 않는다(sticky 방지 — outage 를 '미적용'으로 고착시키지 않음)."""
    global _NMI_READY, _NMI_PROBE
    if force:
        _NMI_PROBE = None
    if _NMI_PROBE is not None:
        return _NMI_PROBE
    try:
        client().table(NEAR_MISS_IMPROVEMENT_TABLE).select("id").limit(1).execute()
        client().table(NEAR_MISS_TABLE).select("revision_request_reason").limit(1).execute()
        _NMI_PROBE = READINESS_READY
        _NMI_READY = True
    except Exception as exc:
        if any(marker in repr(exc) for marker in _MISSING_COLUMN_MARKERS):
            _NMI_PROBE = READINESS_NOT_READY
            _NMI_READY = False
        else:
            _NMI_PROBE = None
            _NMI_READY = None
            return READINESS_PROBE_ERROR
    return _NMI_PROBE


def _near_miss_improvement_read_gate() -> bool:
    """개선조치(007) **조회** 게이트(read-only 3-state). 쓰기 게이트와 달리 미적용과
    일시오류를 구분한다.

    반환 True(READY) → 조회 진행. False(NOT_READY=007 미적용) → 호출부가 None(정상
    부재, 무배너)로 처리한다. PROBE_ERROR(일시/네트워크/권한 오류)는 **정상 부재로 접지
    않고 예외를 전파**해 상위 뷰의 danger 배너로 표면화한다(오류 ≠ 미적용). 즉 쓰기
    게이트(``near_miss_improvement_extensions_ready`` False → NOT_READY 로 차단)가
    NOT_READY·PROBE_ERROR 를 모두 fail-closed 하는 것과 달리, 읽기는 일시오류만 표면화하고
    진짜 미적용은 조용한 부재로 둔다(가짜 '보완요청 없음'/'미작성' 위장 방지)."""
    probe = near_miss_improvement_extensions_probe()
    if probe == READINESS_PROBE_ERROR:
        raise SupabaseDataError(
            "아차사고 개선조치 스키마 준비 상태를 확인할 수 없습니다(일시 오류). "
            "데이터 연결 상태를 확인한 뒤 다시 시도하세요."
        )
    return probe == READINESS_READY


def _near_miss_improvement_natural(rows: list[dict]) -> list[dict]:
    """개선조치 행(ID/FK)을 화면 자연키 계약으로 변환한다."""
    _, emp_by_id = _user_maps()

    def emp(uid):
        return emp_by_id.get(str(uid), "") if uid is not None else ""

    out = []
    for row in rows:
        out.append({
            "id": row.get("id"),
            "report_id": row.get("report_id"),
            "assignee_emp_no": emp(row.get("assignee_user_id")),
            "designated_confirmer_emp_no": emp(row.get("designated_confirmer_user_id")),
            "confirmed_by_emp_no": emp(row.get("confirmed_by_user_id")),
            "rejected_by_emp_no": emp(row.get("rejected_by_user_id")),
            "action_body": str(row.get("action_body") or ""),
            "result_body": str(row.get("result_body") or ""),
            "due_date": str(row.get("due_date") or "") or None,
            "submit_status": str(row.get("submit_status") or ""),
            "confirm_status": str(row.get("confirm_status") or ""),
            "submitted_at": str(row.get("submitted_at") or "") or None,
            "confirmed_at": str(row.get("confirmed_at") or "") or None,
            "rejected_at": str(row.get("rejected_at") or "") or None,
            "revision_note": row.get("revision_note") or None,
            "is_active": _clean_bool(row.get("is_active")),
            "created_at": str(row.get("created_at") or ""),
            "updated_at": str(row.get("updated_at") or ""),
        })
    return out


def _near_miss_improvement_body(payload: dict) -> dict:
    """개선조치 본문 입력(자연키)을 검증·정규화해 ID/FK 저장 dict 로 만든다(신원/상태 제외).

    assignee/designated_confirmer 는 emp_no 로 받아 FK 로 해석한다. 본문·기한만 담으며
    submit/confirm 상태·확인/반려 행위자·시각은 절대 포함하지 않는다(서버측 확정 대상)."""
    user_by_emp, _ = _user_maps()

    def resolve(emp_key):
        emp = _clean_text(payload.get(emp_key), nullable=True)
        if not emp:
            return None
        if emp not in user_by_emp:
            raise SupabaseDataError(f"사용자 사번을 찾을 수 없습니다: {emp}")
        return user_by_emp[emp]

    due = _clean_text(payload.get("due_date"), nullable=True)
    if due:
        try:
            date.fromisoformat(due)
        except ValueError as exc:
            raise SupabaseDataError(f"조치 기한 형식이 유효하지 않습니다: {due}") from exc
    return {
        "assignee_user_id": resolve("assignee_emp_no"),
        "designated_confirmer_user_id": resolve("designated_confirmer_emp_no"),
        "action_body": _clean_text(payload.get("action_body")),
        "result_body": _clean_text(payload.get("result_body")),
        "due_date": due or None,
    }


def get_near_miss_improvement(report_id) -> dict | None:
    """보고서의 개선조치(자연키 dict) 또는 None. 007 미적용이면 None(정상 부재).

    readiness 확인이 일시오류(PROBE_ERROR)면 None 으로 접지 않고 예외를 전파한다 —
    호출부(큐 enrich·overdue 집계)가 이를 '조회실패'/미상으로 표면화하도록(오류 은폐 금지)."""
    if not _near_miss_improvement_read_gate():
        return None
    rows = _select_all(
        NEAR_MISS_IMPROVEMENT_TABLE, "*",
        lambda query: query.eq("report_id", report_id).limit(1),
    )
    natural = _near_miss_improvement_natural(rows)
    return natural[0] if natural else None


def _nmi_raw(report_id) -> dict | None:
    """개선조치 원본 행(FK 그대로) 1건 — 상태·소유 판정용 내부 조회."""
    rows = _select_all(
        NEAR_MISS_IMPROVEMENT_TABLE, "*",
        lambda query: query.eq("report_id", report_id).limit(1),
    )
    return rows[0] if rows else None


def upsert_near_miss_improvement(report_id, payload: dict, *, updated_by=None) -> dict:
    """개선조치를 DRAFT 로 저장한다(없으면 생성, 있으면 편집).

    편집은 항상 DRAFT/PENDING 으로 되돌리며(확인/반려 행위자·시각 초기화), 이미 확인
    (CONFIRMED)된 개선조치는 편집할 수 없다(강등 방지). 상태는 조건부 UPDATE(where
    confirm_status <> 'CONFIRMED')로 서버측에서도 다시 강제한다(lost update/강등 방지)."""
    if not near_miss_improvement_extensions_ready():
        raise SupabaseDataError(_NMI_NOT_READY_MESSAGE)
    body = _near_miss_improvement_body(payload)
    existing = _nmi_raw(report_id)
    attribution = _clean_text(updated_by, nullable=True)
    if existing is None:
        record = {
            "report_id": report_id,
            **body,
            "submit_status": "DRAFT",
            "confirm_status": "PENDING",
            "is_active": True,
            "created_by": attribution,
            "updated_by": attribution,
        }
        response = _execute(
            client().table(NEAR_MISS_IMPROVEMENT_TABLE).insert(record),
            "생성", NEAR_MISS_IMPROVEMENT_TABLE, retry_transient=False,
        )
        saved = (response.data or [None])[0]
        if saved is None:
            raise SupabaseDataError("개선조치 생성 결과가 비어 있습니다.")
        return _near_miss_improvement_natural([saved])[0]
    if str(existing.get("confirm_status") or "") == "CONFIRMED":
        raise SupabaseDataError("이미 확인(CONFIRMED)된 개선조치는 수정할 수 없습니다.")
    updates = {
        **body,
        "submit_status": "DRAFT",
        "confirm_status": "PENDING",
        "submitted_at": None,
        "confirmed_by_user_id": None,
        "confirmed_at": None,
        "rejected_by_user_id": None,
        "rejected_at": None,
        "updated_by": attribution,
    }
    query = (
        client().table(NEAR_MISS_IMPROVEMENT_TABLE).update(updates)
        .eq("report_id", report_id)
        .neq("confirm_status", "CONFIRMED")
    )
    response = _execute(query, "수정", NEAR_MISS_IMPROVEMENT_TABLE)
    saved = (response.data or [None])[0]
    if saved is None:
        raise SupabaseDataError(_NMI_STALE_MESSAGE)
    return _near_miss_improvement_natural([saved])[0]


def submit_near_miss_improvement(report_id, *, updated_by=None) -> dict:
    """DRAFT→SUBMITTED. 담당자·조치 결과가 채워져 있어야 한다(DB CHECK 미러)."""
    if not near_miss_improvement_extensions_ready():
        raise SupabaseDataError(_NMI_NOT_READY_MESSAGE)
    existing = _nmi_raw(report_id)
    if existing is None:
        raise SupabaseDataError("제출할 개선조치가 없습니다.")
    if existing.get("assignee_user_id") is None:
        raise SupabaseDataError("조치 담당자가 지정되어야 제출할 수 있습니다.")
    if not str(existing.get("result_body") or "").strip():
        raise SupabaseDataError("조치 결과가 입력되어야 제출할 수 있습니다.")
    from datetime import datetime, timezone
    updates = {
        "submit_status": "SUBMITTED",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": _clean_text(updated_by, nullable=True),
    }
    query = (
        client().table(NEAR_MISS_IMPROVEMENT_TABLE).update(updates)
        .eq("report_id", report_id)
        .eq("submit_status", "DRAFT")
    )
    response = _execute(query, "제출", NEAR_MISS_IMPROVEMENT_TABLE)
    saved = (response.data or [None])[0]
    if saved is None:
        raise SupabaseDataError(_NMI_STALE_MESSAGE)
    return _near_miss_improvement_natural([saved])[0]


def confirm_near_miss_improvement(report_id, *, confirmed_by_emp_no: str, updated_by=None) -> dict:
    """PENDING→CONFIRMED. 실제 확인 행위자(confirmed_by)를 서버측 사번으로 귀속하고,
    자기확인(담당자==확인자)을 차단한다(DB CHECK 이중). SUBMITTED·PENDING 조건부 UPDATE."""
    if not near_miss_improvement_extensions_ready():
        raise SupabaseDataError(_NMI_NOT_READY_MESSAGE)
    user_by_emp, _ = _user_maps()
    confirmer = _clean_text(confirmed_by_emp_no)
    if confirmer not in user_by_emp:
        raise SupabaseDataError(f"확인자 사번을 찾을 수 없습니다: {confirmer}")
    existing = _nmi_raw(report_id)
    if existing is None:
        raise SupabaseDataError("확인할 개선조치가 없습니다.")
    if existing.get("assignee_user_id") == user_by_emp[confirmer]:
        raise SupabaseDataError("조치 담당자는 자신의 개선조치를 확인할 수 없습니다(자기확인 금지).")
    from datetime import datetime, timezone
    updates = {
        "confirm_status": "CONFIRMED",
        "confirmed_by_user_id": user_by_emp[confirmer],
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "rejected_by_user_id": None,
        "rejected_at": None,
        "updated_by": _clean_text(updated_by, nullable=True),
    }
    query = (
        client().table(NEAR_MISS_IMPROVEMENT_TABLE).update(updates)
        .eq("report_id", report_id)
        .eq("submit_status", "SUBMITTED")
        .eq("confirm_status", "PENDING")
    )
    response = _execute(query, "확인", NEAR_MISS_IMPROVEMENT_TABLE)
    saved = (response.data or [None])[0]
    if saved is None:
        raise SupabaseDataError(_NMI_STALE_MESSAGE)
    return _near_miss_improvement_natural([saved])[0]


def reject_near_miss_improvement(report_id, note: str, *, rejected_by_emp_no: str, updated_by=None) -> dict:
    """PENDING→REJECTED. 반려 사유(note) 필수, 반려 행위자 서버측 귀속."""
    if not near_miss_improvement_extensions_ready():
        raise SupabaseDataError(_NMI_NOT_READY_MESSAGE)
    reason = _clean_text(note, nullable=True)
    if not reason:
        raise SupabaseDataError("개선조치를 반려하려면 사유가 필요합니다.")
    user_by_emp, _ = _user_maps()
    rejecter = _clean_text(rejected_by_emp_no)
    if rejecter not in user_by_emp:
        raise SupabaseDataError(f"반려 행위자 사번을 찾을 수 없습니다: {rejecter}")
    from datetime import datetime, timezone
    updates = {
        "confirm_status": "REJECTED",
        "rejected_by_user_id": user_by_emp[rejecter],
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "confirmed_by_user_id": None,
        "confirmed_at": None,
        "revision_note": reason,
        "updated_by": _clean_text(updated_by, nullable=True),
    }
    query = (
        client().table(NEAR_MISS_IMPROVEMENT_TABLE).update(updates)
        .eq("report_id", report_id)
        .eq("submit_status", "SUBMITTED")
        .eq("confirm_status", "PENDING")
    )
    response = _execute(query, "반려", NEAR_MISS_IMPROVEMENT_TABLE)
    saved = (response.data or [None])[0]
    if saved is None:
        raise SupabaseDataError(_NMI_STALE_MESSAGE)
    return _near_miss_improvement_natural([saved])[0]


def reset_near_miss_improvement_on_reopen(report_id, *, updated_by=None) -> dict | None:
    """[SUPERSEDED — Codex P1-4] 비원자 재개 초기화(단독 UPDATE).

    facade 재개 경로는 이제 원자 RPC ``reopen_near_miss_report`` 를 사용한다(report 전이 +
    개선조치 초기화 단일 트랜잭션). 이 함수는 그 2단계 중 뒤 절반만 수행하므로 재개 경로에서
    더는 호출하지 않는다(원자성 창 문제 때문). 하위호환/보조용으로만 남긴다.

    report 재개(EVALUATED→IN_REVIEW) 시 확인된 개선조치를 CONFIRMED→PENDING 으로 되돌린다.

    confirmed_by/confirmed_at 를 초기화하고 result_body/submit_status/due_date 는 보존한다.
    개선조치가 없거나 이미 확인 상태가 아니면 no-op(None). 강등방어 트리거는 부모가 아직
    CLOSED 가 아니므로(재개는 EVALUATED→IN_REVIEW) 이 초기화를 막지 않는다."""
    if not near_miss_improvement_extensions_ready():
        raise SupabaseDataError(_NMI_NOT_READY_MESSAGE)
    updates = {
        "confirm_status": "PENDING",
        "confirmed_by_user_id": None,
        "confirmed_at": None,
        "updated_by": _clean_text(updated_by, nullable=True),
    }
    query = (
        client().table(NEAR_MISS_IMPROVEMENT_TABLE).update(updates)
        .eq("report_id", report_id)
        .eq("confirm_status", "CONFIRMED")
    )
    response = _execute(query, "재개초기화", NEAR_MISS_IMPROVEMENT_TABLE)
    saved = (response.data or [None])[0]
    return _near_miss_improvement_natural([saved])[0] if saved else None


def close_near_miss_report(report_id, *, actor_emp_no: str) -> dict | None:
    """확인+종결 하드게이트 원자 RPC(close_near_miss_report)를 호출한다.

    행위자 능력 검증·확인된 활성 개선조치 존재·조건부 EVALUATED→CLOSED 전이는 모두 서버(RPC)
    에서 단일 트랜잭션으로 강제한다. RPC 는 전달된 actor 사번을 행위자 신원으로 신뢰하되(신원
    인증은 앱 계층 신뢰경계), 그 사용자의 활성·능력만 users 에서 재조회해 검증한다."""
    if not near_miss_improvement_extensions_ready():
        raise SupabaseDataError(_NMI_NOT_READY_MESSAGE)
    actor = _clean_text(actor_emp_no)
    if not actor:
        raise SupabaseDataError("종결 행위자 사번이 필요합니다.")
    _execute_rpc = client().rpc(
        "close_near_miss_report",
        {"p_report_id": report_id, "p_actor_emp_no": actor},
    )
    _execute(_execute_rpc, "종결", NEAR_MISS_TABLE, retry_transient=False)
    return get_near_miss_report(report_id)


def reopen_near_miss_report(report_id, *, actor_emp_no: str) -> dict | None:
    """재개 원자 RPC(reopen_near_miss_report)를 호출한다(Codex P1-4).

    report EVALUATED→IN_REVIEW 전이(평가필드 초기화)와 확인된 활성 개선조치 CONFIRMED→PENDING
    초기화(confirmer/confirmed_at 초기화, result/submit/due 보존)를 단일 트랜잭션으로 원자
    실행한다. 과거의 '전이 후 별도 리셋' 2단계가 남기던 stale CONFIRMED 재사용 창을 없앤다.
    RPC 는 전달된 actor 사번을 행위자 신원으로 신뢰하되(신원 인증은 앱 계층 신뢰경계), 그
    사용자의 활성·능력만 users 에서 재조회해 검증한다."""
    if not near_miss_improvement_extensions_ready():
        raise SupabaseDataError(_NMI_NOT_READY_MESSAGE)
    actor = _clean_text(actor_emp_no)
    if not actor:
        raise SupabaseDataError("재개 행위자 사번이 필요합니다.")
    _execute_rpc = client().rpc(
        "reopen_near_miss_report",
        {"p_report_id": report_id, "p_actor_emp_no": actor},
    )
    _execute(_execute_rpc, "재개", NEAR_MISS_TABLE, retry_transient=False)
    return get_near_miss_report(report_id)


def request_near_miss_revision(
    report_id, reason: str, *, requester_emp_no: str, expected_status=None,
) -> dict | None:
    """보완요청(반송): IN_REVIEW→SUBMITTED + revision_request 3필드(사유/요청자/시각) 기록.

    보완요청 컬럼(revision_request_reason 등, 007)이 있어야 한다. 요청자 사번은 users 로
    해소해 ``revision_requested_by_user_id`` (FK)로 저장한다 — 서버귀속(파사드가 인증 actor
    로 확정). all-or-none CHECK(near_miss_reports_revision_request_all_or_none)를 만족하도록
    세 필드를 함께 세팅하고, 평가 이전 상태로 되돌리므로 평가필드를 비운다
    (near_miss_eval_consistency 충족). ``expected_status`` 조건부 UPDATE 로 TOCTOU(다른
    평가자가 먼저 전이)를 막는다 — 0행이면 stale 오류.

    이 경로는 구조 불변식(하드게이트)이 아니라 앱계층 인가 대상이라 RPC 가 아닌 일반
    UPDATE 다(CHECK 로 데이터 정합만 DB 가 보장). 행위자 인가는 파사드가 소유한다."""
    if not near_miss_improvement_extensions_ready():
        raise SupabaseDataError(_NMI_NOT_READY_MESSAGE)
    reason_text = _clean_text(reason)
    if not reason_text:
        raise SupabaseDataError("보완 사유가 필요합니다.")
    user_by_emp, _ = _user_maps()
    requester = _clean_text(requester_emp_no)
    if requester not in user_by_emp:
        raise SupabaseDataError(f"요청자 사번을 찾을 수 없습니다: {requester}")
    from datetime import datetime, timezone
    updates = {
        "status": "SUBMITTED",
        "confirmed_grade": None,
        "evaluator_user_id": None,
        "evaluated_at": None,
        "revision_request_reason": reason_text,
        "revision_requested_by_user_id": user_by_emp[requester],
        "revision_requested_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": requester,
    }
    query = client().table(NEAR_MISS_TABLE).update(updates).eq("id", report_id)
    if expected_status is not None:
        query = query.eq("status", str(expected_status).strip())
    response = _execute(query, "보완요청", NEAR_MISS_TABLE)
    saved = (response.data or [None])[0]
    if saved is None:
        if expected_status is not None:
            raise SupabaseDataError(_NM_STALE_MESSAGE)  # 조건부 0행 = 이미 전이됨/변경됨
        return get_near_miss_report(report_id)
    return _near_miss_natural([saved])[0]


def get_near_miss_revision_request(report_id) -> dict | None:
    """보고서의 보완요청 3필드(사유/요청자 사번/요청시각) 또는 None. 007 미적용이면 None.

    read-only 표시 경로 — 007 컬럼에서 직접 읽어 요청자 user_id 를 사번으로 되돌린다.
    007 미적용은 None(정상 부재, 무배너)이지만, readiness 확인 일시오류(PROBE_ERROR)는
    None 으로 접지 않고 예외를 전파한다 — near_miss_my 의 danger 배너가 표면화하도록
    (오류를 '보완요청 없음'으로 위장하지 않는다)."""
    if not _near_miss_improvement_read_gate():
        return None
    _, emp_by_id = _user_maps()
    rows = _select_all(
        NEAR_MISS_TABLE,
        "revision_request_reason,revision_requested_by_user_id,revision_requested_at",
        lambda query: query.eq("id", report_id).limit(1),
    )
    if not rows:
        return None
    row = rows[0]
    reason = row.get("revision_request_reason")
    if not reason:
        return None
    by_id = row.get("revision_requested_by_user_id")
    return {
        "revision_request_reason": str(reason),
        "revision_requested_by_emp_no": emp_by_id.get(str(by_id), "") if by_id is not None else "",
        "revision_requested_at": str(row.get("revision_requested_at") or "") or None,
    }
