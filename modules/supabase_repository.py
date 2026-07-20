"""Supabase-backed persistence for duty scheduler data.

This module is server-side only. It translates database identifiers into the
natural keys used by the existing Streamlit views.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Iterable

import pandas as pd
from supabase import Client, create_client

from modules import config, validators

PAGE_SIZE = 1000
WRITE_BATCH_SIZE = 500
REQUIRED_TABLES = ("departments", "teams", "users", "work_types", "work_schedules")
_BOOLEAN_COLUMNS = {"is_active", "is_work", "affects_allowance"}
_INTEGER_COLUMNS = {"sort_order", "group_sort_order"}

# 운영단위 유형 내부값 (migration 003 teams.unit_type CHECK 와 동일).
UNIT_TYPES = ("SHIFT", "GENERAL")


class SupabaseDataError(RuntimeError):
    """A sanitized Supabase operation failure."""


def _sanitized_error(action: str, table: str, exc: Exception) -> SupabaseDataError:
    message = str(exc)
    try:
        url, key = config.supabase_settings()
        message = message.replace(url, "<supabase>").replace(key, "<redacted>")
    except Exception:
        pass
    return SupabaseDataError(f"Supabase {table} {action} 실패: {message}")


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
    global _ORG_READY
    _ORG_READY = None


# Windows 비동기 소켓의 일시 오류 표식 (예: WinError 10035 — 즉시 완료 실패).
# 이런 오류는 영구 장애가 아니므로 1회에 한해 재시도한다 (무한 재시도 금지).
_TRANSIENT_MARKERS = ("10035", "10054", "ConnectionResetError", "ReadError", "ConnectError")


def _execute(query, action: str, table: str):
    try:
        return query.execute()
    except Exception as exc:
        if any(marker in repr(exc) for marker in _TRANSIENT_MARKERS):
            try:
                return query.execute()  # 일시적 소켓 오류 1회 재시도
            except Exception as retry_exc:
                raise _sanitized_error(action, table, retry_exc) from retry_exc
        raise _sanitized_error(action, table, exc) from exc


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


def _department_maps() -> tuple[dict[str, int], dict[str, str]]:
    rows = _select_all("departments", "id,dept_code")
    by_code = {
        str(_required(row, "departments", "dept_code")): _required(row, "departments", "id")
        for row in rows
    }
    by_id = {str(value): key for key, value in by_code.items()}
    return by_code, by_id


def _team_maps() -> tuple[dict[tuple[str, str], int], dict[str, str]]:
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


def upsert_departments(records: list[dict]) -> None:
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
    if payload:
        _upsert("departments", payload, "dept_code")


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


def upsert_teams(records: list[dict]) -> None:
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
    if payload:
        _upsert("teams", payload, "department_id,team_code")


# --- 조직 관리 확장 (migration 003: 부서그룹 + 운영단위 유형) ---
# 003 적용 전 라이브 DB 에는 확장 컬럼이 없다. 조회는 호출부(db 파사드)가
# org_extensions_ready() 로 분기해 안전한 기본값으로 폴백하고, 저장은 이 계층에서
# 명확한 오류로 차단한다 (부분 저장·조용한 무시 없음).
_ORG_READY: bool | None = None
_ORG_NOT_READY_MESSAGE = (
    "조직 관리 확장 컬럼(migration 003)이 아직 적용되지 않아 저장할 수 없습니다. "
    "supabase/migrations/003_org_structure.sql 적용 후 다시 시도하세요."
)


def org_extensions_ready() -> bool:
    """departments/teams 에 003 확장 컬럼이 존재하는지 확인한다 (1회 probe 후 캐시)."""
    global _ORG_READY
    if _ORG_READY is None:
        try:
            client().table("departments").select(
                "department_group,group_sort_order"
            ).limit(1).execute()
            client().table("teams").select("unit_type").limit(1).execute()
            _ORG_READY = True
        except Exception:
            _ORG_READY = False
    return _ORG_READY


def get_departments_org() -> pd.DataFrame:
    """부서 목록 + 그룹 확장 컬럼. 003 적용 후에만 호출한다."""
    rows = _select_all(
        "departments",
        "dept_code,dept_name,department_group,group_sort_order,sort_order,is_active",
        lambda query: query.order("group_sort_order").order("sort_order").order("dept_code"),
    )
    frame = _frame(
        rows,
        ["dept_code", "dept_name", "department_group", "group_sort_order", "sort_order", "is_active"],
        "departments",
    )
    if not frame.empty:
        frame["group_sort_order"] = frame["group_sort_order"].map(_clean_int)
        frame["sort_order"] = frame["sort_order"].map(_clean_int)
        frame["is_active"] = frame["is_active"].map(_clean_bool)
    return frame


def upsert_departments_org(records: list[dict]) -> None:
    """그룹 컬럼을 포함한 부서 upsert. 003 미적용이면 저장을 차단한다."""
    if not org_extensions_ready():
        raise SupabaseDataError(_ORG_NOT_READY_MESSAGE)
    payload = [
        {
            "dept_code": _clean_text(row.get("dept_code")),
            "dept_name": _clean_text(row.get("dept_name")),
            "department_group": _clean_text(row.get("department_group")),
            "group_sort_order": _clean_int(row.get("group_sort_order")),
            "sort_order": _clean_int(row.get("sort_order")),
            "is_active": _clean_bool(row.get("is_active")),
        }
        for row in records
    ]
    if any(
        not row["dept_code"] or not row["dept_name"] or not row["department_group"]
        for row in payload
    ):
        raise SupabaseDataError("부서코드·부서명·그룹명은 비어 있을 수 없습니다.")
    if payload:
        _upsert("departments", payload, "dept_code")


def get_teams_org() -> pd.DataFrame:
    """운영단위(조) 목록 + unit_type. 003 적용 후에만 호출한다."""
    _, dept_by_id = _department_maps()
    rows = _select_all(
        "teams",
        "department_id,team_code,team_name,unit_type,sort_order,is_active",
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
            "sort_order": _clean_int(_required(row, "teams", "sort_order")),
            "is_active": _clean_bool(_required(row, "teams", "is_active")),
        })
    return _frame(
        natural,
        ["dept_code", "team_code", "team_name", "unit_type", "sort_order", "is_active"],
        "teams",
    )


def upsert_teams_org(records: list[dict]) -> None:
    """unit_type 을 포함한 운영단위 upsert. 003 미적용이면 저장을 차단한다."""
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
            "sort_order": _clean_int(row.get("sort_order")),
            "is_active": _clean_bool(row.get("is_active")),
        })
    if payload:
        _upsert("teams", payload, "department_id,team_code")


def get_users() -> pd.DataFrame:
    _, dept_by_id = _department_maps()
    _, team_by_id = _team_maps()
    rows = _select_all(
        "users",
        "emp_no,name,department_id,team_id,position,role,is_active",
        lambda query: query.order("emp_no"),
    )
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
        })
    return _frame(
        natural,
        ["emp_no", "name", "dept_code", "team_code", "position", "role", "is_active"],
        "users",
    )


def upsert_users(records: list[dict]) -> None:
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
        payload.append({
            "emp_no": emp_no,
            "name": name,
            "department_id": dept_by_code[dept_code],
            "team_id": team_id,
            "position": _clean_text(row.get("position")),
            "role": role,
            "is_active": _clean_bool(row.get("is_active")),
        })
    if payload:
        _upsert("users", payload, "emp_no")


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


def upsert_work_types(records: list[dict]) -> None:
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
    if payload:
        _upsert("work_types", payload, "code")


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
