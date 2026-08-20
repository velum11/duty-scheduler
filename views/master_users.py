"""기준정보 — 사용자 관리 (기준정보 3화면 공통 기반 재구현).

``views/master`` 공통 기반(Phase4 Lane A) 위에서 사용자 화면을 재구현한다. 상태·그리드·
액션바·저장 lifecycle·상태 시각은 공통 패키지를 쓰고, 이 화면만의 도메인(표시↔코드
변환, 부서 종속 조 드롭다운, 표시순서 그룹 검증, 소프트 삭제=퇴직 처리)만 여기서 소유한다.

행 상태 계약(_row_id/_row_state/_sel)으로 기존 저장 행과 미저장 신규 행을 분리한다.
  - 기존 행: 첫 열 선택 체크박스 → 상단 [삭제](퇴직 처리) 대상
  - 신규 행: 첫 열 − 제거 버튼 → 즉시 개별 제거(확인·DB 작업 없음)
목록에서 직접 입력·수정하고 [저장]으로 일괄 반영한다(자동 저장 없음). Excel 의 여러
행·열(탭/줄바꿈)을 그대로 붙여넣을 수 있고, [행 추가]로 신규 사용자를 추가한다.
사용자는 물리 삭제하지 않고 재직 여부(is_active)로 관리한다([삭제]=퇴직/미사용 처리).

액션 진입점(2026-08-14 사용자 지시): 실행 버튼은 **앱 상단 52px 헤더 아이콘 4종
(추가·삭제·저장·새로고침) 하나뿐**이다. 화면 안 액션 버튼 바는 제거했고, 활성/음영·
툴팁 사유는 종전과 같은 ``page_action_specs`` 계산을 그대로 헤더에 발행한다(규칙 불변,
진입점만 단일화). 앱 셸이 본문보다 먼저 헤더를 그리므로 발행은 한 프레임 늦게 반영되는데,
헤더가 유일한 진입점이 된 뒤로는 그 지연이 곧 '눌리지 않는 아이콘'이라 발행값이 바뀐
run 에서 1회 재실행해 헤더를 따라오게 한다(``_sync_header``).

화면 표시 원칙:
- 부서는 부서명(중복 시 코드 병기)으로 표시하고 저장 시 dept_code 로 변환한다. 부서 셀에는
  소속 그룹명을 보조 라벨로 병기해 표시순서가 어느 그룹 범위에서 검증되는지 알린다.
- 이메일(010 user_emails)은 **전 업무 수신(scope=ALL) 대표 주소 1건**만 그리드 열로
  편집한다. 1인 다중 이메일(M:N) 계약은 유지되며, 담당별(scope=capability) 주소와 추가
  ALL 주소는 저장 시 보존하고 하단 '담당 권한·알림 이메일' 편집기가 계속 소유한다.
- 조(운영단위) 편집 칼럼은 2026-08-07 제거 — A/B/C 근무조는 기준정보가 아니라 근무편성표에서
  직접 입력한다. 기존 행의 team_code 는 _save 가 저장 직전 권위 스토어에서 백필해 보존한다
  (그리드가 spec.order+META 외 컬럼을 잘라내므로 숨김 컬럼 왕복은 불가).
- 입사일/퇴사일(009)은 자유 타이핑 후 저장 시 정규화한다. 퇴사일이 지난 계정은 로그인이
  차단되고 편성 명단에서 숨겨진다(판정 소유: db.is_resigned).
- 권한은 관리자/조장/조원으로 표시하고, 저장 시 ADMIN/MANAGER/USER 로 변환한다. DB 저장값과
  권한 분기 코드는 기존 값을 유지한다.

보존 계약(Phase1 §5): 변경 행만 저장(_changed_records), 완전 빈 행 skip, 소프트 삭제,
필터 미표시 사용자 자동 퇴직 금지(loaded_keys 비움), 사번 중복 차단, display_order 004
게이트(화면·저장소 이중 방어), 저장 실패 시 초안 보존.
"""
from __future__ import annotations

# DESIGN.md §0 화면 유형 규약 — 기준정보 편집형.
SCREEN_ARCHETYPE = "EDIT_GRID"

import json
from html import escape

import pandas as pd
import streamlit as st
from st_aggrid import JsCode

from modules import auth, config, db, nav, supabase_repository
from views.common import erp
from views.master import (
    ADD,
    DELETE,
    REFRESH,
    RELOAD,
    SAVE,
    DraftState,
    icon_toolbar_specs,
    MasterGridSpec,
    PersistResult,
    Readiness,
    ReadinessState,
    banner,
    cell_dirty_rule,
    cell_error_rule,
    chip_html,
    confirm_bar,
    count_strip,
    dirty_total,
    discard_confirm_bar,
    grid_bool,
    header_actions_from_specs,
    ledger_banner,
    live_rows,
    master_grid_height,
    master_row_class_rules,
    mode_badge_html,
    page_action_specs,
    render_master_grid,
    run_save,
    take_actions,
)

PAGE_ID = "master_users"
_ALL = "__ALL__"

# 화면 표시 라벨 ↔ 저장 코드 매핑 (DB 값은 ADMIN/MANAGER/USER 유지)
_ROLE_TO_LABEL = {"ADMIN": "관리자", "MANAGER": "조장", "USER": "조원"}
_LABEL_TO_ROLE = {label: role for role, label in _ROLE_TO_LABEL.items()}

_STATUS = ["전체", "재직", "퇴직"]
# 표시순서: 부서그룹 안에서의 직원 출력 순서 (users.display_order, 빈 값=미지정).
# 같은 부서그룹의 활성 사용자끼리 중복 금지 — 부서가 아니라 그룹 기준으로 검증한다.
# 조(운영단위) 칼럼은 2026-08-07 사용자 결정으로 제거됐다 — A/B/C조는 기준정보가 아니라
# 근무편성표에서 직접 입력한다(schedule_assignments.shift_group_code).
# 입사일/퇴사일은 migration 009. 퇴사일이 지나면 로그인 차단 + 편성 명단에서 숨긴다.
#: 알림 이메일 열(migration 010 user_emails) — scope=ALL 대표 주소 1건 편집 슬롯.
#: 공용 그리드는 ``spec.order + META_COLUMNS`` 만 왕복시키므로(숨김 컬럼은 잘려 나간다)
#: 이메일도 **보이는 열**로 두어야 저장 경로까지 값이 살아 온다 — team_code 소실 사고
#: (2026-08-07 P1)와 같은 함정을 반복하지 않기 위한 배치다.
EMAIL_COL = "이메일"
_USER_COLS = ["사번", "성명", "부서", "직급", "권한", EMAIL_COL,
              "입사일", "퇴사일", "표시순서", "재직"]
# 기존 조(운영단위) 배정은 그리드로 왕복시키지 않는다 — 공용 그리드는 spec.order+META
# 컬럼만 통과시키므로 숨김 컬럼은 잘려 나간다. 보존은 _save 의 스토어 백필이 담당한다.
_ROW_COLS = ["_row_id", "_row_state", "_sel", *_USER_COLS]
_GRID_COLUMNS = {
    "사번": "text", "성명": "text", "부서": "text",
    "직급": "text", "권한": "text", EMAIL_COL: "text",
    "입사일": "text", "퇴사일": "text",
    "표시순서": "text", "재직": "bool",
}
# validate 가 필수/참조를 확인하는 텍스트 필드(재직/표시순서 제외) — 완전 빈 행 판별과 동일.
_CONTENT_COLS = ["사번", "성명", "부서", "직급"]

# 편집 게이트(JsCode predicate) — org 화면과 동일 계약(master_org.py _EDIT_NEW_ONLY /
# _EDIT_UNLESS_PROTECTED). 자연키(사번)는 신규행만 편집(저장행 잠금), 보호행(_protected)은
# 데이터셀·재직토글을 잠근다. 일반 저장행의 성명/부서/조/권한/표시순서/재직 편집은 유지한다.
_IS_PROTECTED_JS = "(data._protected === '1' || data._protected === 1)"
_EDIT_NEW_ONLY = JsCode("function(p){ return !!(p.data && p.data._row_state === 'new'); }")
_EDIT_UNLESS_PROTECTED = JsCode(
    "function(p){ return !(p.data && (p.data._protected === '1' || p.data._protected === 1)); }"
)

# 필터 위젯 세션 key (이 화면 전용 — 취소 시 위젯 복원에 사용).
_F_ACTIVE, _F_DEPT, _F_ROLE, _F_SEARCH = "mu_active", "mu_dept", "mu_role", "mu_search"

# readiness(조직 스키마 capability, 도입: migration 004) 안내 문구 — 표시순서(display_order) 저장이 이 capability 에 의존한다.
_NOT_READY_MSG = (
    "표시순서 기능이 아직 준비되지 않아 표시순서를 저장할 수 없습니다 — 조회·편집만 가능합니다."
)
_PROBE_ERROR_MSG = (
    "스키마 상태를 확인하지 못했습니다(권한·네트워크). '스키마 재확인' 후 다시 시도하세요."
)

# §1-E 건수 행 CSS(사용자 제목 + 건수 pill + 재직/퇴직 분해 + 우측 상태 텍스트).
# 액션 버튼이 헤더로 올라간 뒤 비는 우측 공간은 저장 필요 여부(미저장)·선택 건수와
# 진입점 안내가 채운다 — 상태 신호를 잃지 않으면서 빈 영역도 만들지 않는다(§6).
# §2 팔레트 리터럴 + 부속서 A-2(작은 의미 텍스트 #6b665d 하한).
_MU_CSS = """
<style>
.mu-crow { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.mu-crow .t { font-size:14px; font-weight:600; color:#1c1a17; white-space:nowrap; }
.mu-crow .pill { font-size:12px; font-weight:600; font-variant-numeric:tabular-nums;
  padding:2px 9px; border-radius:999px; background:#f1eee8; color:#4a453d; }
/* 좌측 분포(재직/퇴직)와 우측 상태 텍스트는 같은 성격의 보조 정보라 같은 크기를 쓴다 —
   종전 11.5 vs 12.5 혼재를 12px 로 통일(2026-08-19 DESIGN §1.2 네 단계 밖 값 폐지). */
.mu-crow .dist { font-size:12px; color:#6b665d; white-space:nowrap;
  font-variant-numeric:tabular-nums; }
.mu-crow .gap { flex:1 1 auto; min-width:8px; }
.mu-crow .wip, .mu-crow .calm, .mu-crow .sel, .mu-crow .hint {
  font-size:12px; white-space:nowrap; font-variant-numeric:tabular-nums; }
.mu-crow .wip { font-weight:600; color:#b4451a; }
.mu-crow .wip .sub { font-weight:400; color:#6b665d; margin-left:4px; }
.mu-crow .calm { color:#6b665d; }
.mu-crow .sel { font-weight:600; color:#4a453d; }
.mu-crow .hint { color:#6b665d; }
.mu-crow .sep { color:#cfc8bd; }
/* (2026-08-19) 비밀번호 초기화·담당/이메일 저장 버튼의 32px 개별 우회를 제거했다 —
   공용 버튼 하한이 34px(§1.4 compact, modules/ui.py)로 올라 우회가 오히려 낮추는
   쪽이 됐기 때문. 이제 앱 전역 규칙 하나를 그대로 받는다. */
</style>
"""

# 이메일 열이 조회 전용으로 내려가는 사유(저장소 미준비 / 확인 불가 / 조회 실패) 안내.
# 미준비와 "확인하지 못함"을 구분한다 — 후자는 일시 장애라 재시도로 풀린다.
_EMAIL_NOT_READY_MSG = (
    "담당 권한·알림 이메일 저장소가 아직 준비되지 않았습니다"
)
_EMAIL_PROBE_ERROR_MSG = (
    "담당 권한·알림 이메일 저장소 상태를 확인하지 못했습니다(일시 장애). 잠시 후 다시 시도하세요"
)


# ---------------------------------------------------------------------------
# 표시↔코드 변환 도메인 헬퍼 (이 화면 소유 — 조직/근무형태와 공유되는 계약 아님)
# ---------------------------------------------------------------------------
def _dept_labels(dept_names: dict[str, str]) -> dict[str, str]:
    """부서명 중복에도 안전한 편집기 표시값(code -> label)."""
    counts = pd.Series(list(dept_names.values())).value_counts()
    return {
        code: (name if counts.get(name, 0) == 1 else f"{name} ({code})")
        for code, name in dept_names.items()
    }


def _dept_resolver(dept_names: dict[str, str]) -> dict[str, str]:
    """입력값 -> 부서코드. 표시 라벨/코드를 허용하고, 유일한 부서명도 허용한다."""
    resolver: dict[str, str] = {}
    for code, label in _dept_labels(dept_names).items():
        resolver[label] = code
        resolver[str(code)] = code
    name_counts = pd.Series(list(dept_names.values())).value_counts()
    for code, name in dept_names.items():
        if name_counts.get(name, 0) == 1:
            resolver.setdefault(str(name), code)
    return resolver


def _team_maps(teams: pd.DataFrame):
    """(부서코드, 입력값) -> 조코드 해석기와 (부서코드, 조코드) -> 조명 맵.

    입력값은 조명(표시값) 우선, 조코드도 허용한다. 같은 부서에 조명이 중복되면
    해당 조명은 매핑하지 않아(None) 잘못된 조로 저장되는 것을 막는다.
    """
    resolve: dict[tuple[str, str], str | None] = {}
    display: dict[tuple[str, str], str] = {}
    for _, row in teams.iterrows():
        dept = str(row["dept_code"])
        code = str(row["team_code"])
        name = str(row["team_name"])
        display[(dept, code)] = name
        name_key = (dept, name)
        resolve[name_key] = None if name_key in resolve else code
        resolve.setdefault((dept, code), code)
    return resolve, display


def _order_text(value) -> str:
    """저장소 display_order → 편집기 표시 문자열 ('' = 미지정)."""
    try:
        order = db.normalize_display_order(value)
    except (TypeError, ValueError):
        return ""
    return "" if order is None else str(order)


def _date_text(value) -> str:
    """저장소 날짜 → 편집기 표시 문자열 ('' = 미지정)."""
    return supabase_repository._clean_date(value) or ""


# ---------------------------------------------------------------------------
# 알림 이메일(migration 010 user_emails) — 그리드 1열 = scope=ALL 대표 주소 슬롯
# ---------------------------------------------------------------------------
# 계약 유지 원칙: user_emails 는 (user, email, scope) 행 단위 M:N 이고 한 사람이 복수
# 주소·업무별 상이한 주소를 가질 수 있다. 그리드는 그중 **전 업무 수신(scope=ALL)
# 대표 주소 1건**만 편집 슬롯으로 노출하고, 저장은 그 1건만 교체한다 — 다른 ALL 주소와
# 담당별(scope=capability) 주소는 읽고 그대로 되돌려 써서 보존한다(파괴적 전체 교체 금지).
def _valid_email(value) -> bool:
    """파사드(db.set_user_emails)와 **같은 규칙**의 형식 판정 — 저장 전 화면 방어."""
    email = str(value or "").strip().lower()
    return bool(email) and "@" in email and "." in email.split("@")[-1]


def _primary_email(rows) -> str:
    """이메일 목록에서 그리드 슬롯에 실을 대표 ALL 주소(정렬 최소값, 없으면 '').

    sample(세션 삽입순)·supabase(scope,email 정렬) 어느 모드에서도 같은 값을 고르도록
    정렬 최소값으로 못 박는다 — 대표 주소가 모드마다 달라지면 저장 대상도 달라진다.
    """
    candidates = sorted(
        str(r.get("email") or "").strip()
        for r in (rows or [])
        if str(r.get("scope") or "").strip().upper() == config.EMAIL_SCOPE_ALL
        and str(r.get("email") or "").strip()
    )
    return candidates[0] if candidates else ""


def _extra_email_count(rows) -> int:
    """대표 주소를 뺀 나머지 등록 주소 수(담당별 주소 + 추가 ALL 주소)."""
    total = len([r for r in (rows or []) if str(r.get("email") or "").strip()])
    return max(total - (1 if _primary_email(rows) else 0), 0)


def _merge_email_rows(current, new_email: str) -> list[dict]:
    """기존 목록에서 **대표 ALL 주소 1건만** 교체한 새 목록(저장 payload).

    - 빈 값 입력 = 대표 주소 삭제(나머지 주소는 유지)
    - 나머지 행(다른 ALL 주소·담당별 주소)은 순서·scope 그대로 남긴다
    소문자 정규화는 파사드 계약이지만 여기서도 맞춰 둔다(재조회 전 표시 일관).
    """
    previous = _primary_email(current)
    rows = [
        {"email": str(r.get("email") or "").strip(),
         "scope": str(r.get("scope") or config.EMAIL_SCOPE_ALL).strip().upper()}
        for r in (current or [])
        if str(r.get("email") or "").strip()
    ]
    if previous:
        for idx, row in enumerate(rows):
            if (row["scope"] == config.EMAIL_SCOPE_ALL
                    and row["email"].lower() == previous.lower()):
                rows.pop(idx)
                break
    email = str(new_email or "").strip().lower()
    if email:
        rows.insert(0, {"email": email, "scope": config.EMAIL_SCOPE_ALL})
    return rows


def _email_map(emp_nos) -> tuple[dict[str, str], dict[str, int], str]:
    """사번 목록 → ({사번: 대표 주소}, {사번: 추가 주소 수}, 오류 사유).

    010 미적용이거나 조회가 실패하면 값을 만들어내지 않고 사유를 돌려준다 — 화면은
    그 사유로 이메일 열을 조회 전용으로 내려 **모르는 상태를 빈 값으로 덮어쓰지**
    않는다(sample fallback 으로 오류를 감추지 않는 계약과 같은 취지).
    """
    primary: dict[str, str] = {}
    extra: dict[str, int] = {}
    emps = [str(e).strip() for e in (emp_nos if emp_nos is not None else []) if str(e).strip()]
    if not emps:
        return primary, extra, ""
    probe = db.capabilities_probe()
    if probe == db.READINESS_PROBE_ERROR:
        return {}, {}, _EMAIL_PROBE_ERROR_MSG
    if probe != db.READINESS_READY:
        return {}, {}, _EMAIL_NOT_READY_MSG
    try:
        # 목록 1회 조회(사번당 2회 왕복하던 N+1 제거). 값·오류 계약은 단건과 동일하다.
        rows_of = db.get_user_emails_bulk(emps)
    except db.DATA_SOURCE_ERRORS as exc:
        return {}, {}, f"알림 이메일을 불러오지 못했습니다: {exc}"
    for emp in emps:
        rows = rows_of.get(emp, [])
        primary[emp] = _primary_email(rows)
        extra[emp] = _extra_email_count(rows)
    return primary, extra, ""


def _role_resolver() -> dict[str, str]:
    """입력값 -> 권한 코드. 한글 라벨과 기존 코드(대소문자 무관)를 허용한다."""
    resolver = dict(_LABEL_TO_ROLE)
    for role in _ROLE_TO_LABEL:
        resolver[role] = role
        resolver[role.lower()] = role
    return resolver


def _dept_team_options(teams: pd.DataFrame, dept_labels: dict[str, str]) -> dict[str, list]:
    """부서 표시 라벨 → 그 부서에 속한 조명 목록([''] + 정렬). 부서 종속 조 드롭다운용."""
    out: dict[str, list] = {}
    for code, label in dept_labels.items():
        names = sorted({
            str(r["team_name"]) for _, r in teams.iterrows()
            if str(r["dept_code"]) == code and str(r.get("team_name") or "").strip()
        })
        out[label] = [""] + names
    return out


def _group_hints(group_of: dict, dept_names: dict, dept_labels: dict) -> dict[str, str]:
    """부서 표시 라벨 → 소속 그룹명(부서명과 다를 때만). 표시순서 그룹 context 보조 라벨."""
    out: dict[str, str] = {}
    for code, label in dept_labels.items():
        grp = group_of.get(code, (dept_names.get(code, ""), 0))[0]
        if grp and grp != dept_names.get(code, ""):
            out[label] = grp
    return out


def _readiness() -> ReadinessState:
    """조직 스키마 capability(도입: migration 004) 준비 상태를 3-state(READY/NOT_READY/PROBE_ERROR)로 승격한다.

    표시순서(display_order) 저장은 이 capability 에 의존한다. sample 모드는 항상 READY.
    실제 write 차단은 ``ReadinessState.write_enabled``(READY 에서만 True)가 담당하므로
    오분류(NOT_READY↔PROBE_ERROR)가 저장을 열지 않는다 — 조직 화면과 동일 계약(§25).
    """
    state = db.org_schema_readiness()
    if state == db.READINESS_READY:
        return ReadinessState.ready()
    if state == db.READINESS_PROBE_ERROR:
        return ReadinessState.probe_error(_PROBE_ERROR_MSG)
    return ReadinessState.not_ready(_NOT_READY_MSG)


def _head_badges(readiness: ReadinessState) -> str:
    """§5 readiness 배지(스키마 준비) + 모드 배지(데이터 연결) — 색·의미를 분리해 우측에 노출.

    READY 면 스키마 배지는 생략하고 모드 배지만 보인다(조직 화면과 동일). 정보 종류가
    다른 두 신호를 한 배지에 섞지 않는다.
    """
    sample = db.is_sample_mode()
    badges = ""
    if not readiness.write_enabled:  # READY 가 아니면 스키마 배지를 함께 노출
        badges += readiness.badge_html()
    badges += mode_badge_html(connected=(None if sample else True), sample=sample)
    return badges


def _is_protected(emp_no) -> bool:
    """시스템 보호 계정(관리자 admin) 여부 — 선택/삭제 대상에서 제외한다.

    로그인 관리자 사번(ADMIN, 대소문자 무관)과 동일한 계정을 물리적으로 지우거나
    퇴직 처리하지 못하게 한다(design-contract §14 시스템 보호 행).
    """
    return str(emp_no or "").strip().casefold() == "admin"


# ---------------------------------------------------------------------------
# 저장 전 변환·검증 (records, errors[, cell_errors])
# ---------------------------------------------------------------------------
def _scan(live, dept_resolver, team_resolve):
    """표시 형태 → 저장 형태 변환 + 행별 검증. (records, errors, cell_errors) 반환.

    완전히 빈 행(붙여넣기 버퍼/신규 행)은 조용히 건너뛴다. cell_errors 는 그리드 셀
    오류 마커용 {row_id: {필드: 사유}} 로, 저장 계약(records/errors)에는 영향을 주지 않는다.
    """
    role_resolver = _role_resolver()
    records: list[dict] = []
    errors: list[str] = []
    cell_errors: dict[str, dict[str, str]] = {}

    def mark(rid: str, field: str, msg: str) -> None:
        if rid:
            cell_errors.setdefault(rid, {})[field] = msg

    for i, (_, row) in enumerate(live.iterrows(), start=1):
        rid = str(row.get("_row_id") or "").strip()
        emp_no = str(row.get("사번") or "").strip()
        name = str(row.get("성명") or "").strip()
        dept_value = str(row.get("부서") or "").strip()
        position = str(row.get("직급") or "").strip()
        role = role_resolver.get(str(row.get("권한") or "").strip(), "")
        dept_code = dept_resolver.get(dept_value, "")

        if not any([emp_no, name, dept_value, position]):
            continue

        tag = f"{i}행" + (f"({emp_no})" if emp_no else "")
        if not emp_no:
            errors.append(f"{i}행: 사번을 입력하세요.")
            mark(rid, "사번", "사번을 입력하세요.")
        if not name:
            errors.append(f"{tag}: 성명을 입력하세요.")
            mark(rid, "성명", "성명을 입력하세요.")
        if not dept_code:
            errors.append(f"{tag}: 부서를 선택하세요.")
            mark(rid, "부서", "부서를 선택하세요.")

        # 조(운영단위) 편집은 화면에서 제거됐다(2026-08-07). 여기서는 항상 빈 값으로 두고,
        # 기존 배정의 보존은 _save 가 저장 직전 권위 스토어에서 백필한다(그리드가 숨김
        # 컬럼을 잘라내므로 행 데이터로는 보존할 수 없다).
        team_code = ""

        # 입사일/퇴사일 — 자유 타이핑이라 형식 정규화 후 순서 정합만 본다.
        hire_raw = str(row.get("입사일") or "").strip()
        resign_raw = str(row.get("퇴사일") or "").strip()
        hire_date = supabase_repository._clean_date(hire_raw)
        resign_date = supabase_repository._clean_date(resign_raw)
        if hire_raw and hire_date is None:
            errors.append(f"{tag}: 입사일 형식을 읽을 수 없습니다. (입력값: {hire_raw})")
            mark(rid, "입사일", "YYYY-MM-DD 형식으로 입력하세요.")
        if resign_raw and resign_date is None:
            errors.append(f"{tag}: 퇴사일 형식을 읽을 수 없습니다. (입력값: {resign_raw})")
            mark(rid, "퇴사일", "YYYY-MM-DD 형식으로 입력하세요.")
        if hire_date and resign_date and resign_date < hire_date:
            errors.append(f"{tag}: 퇴사일이 입사일보다 앞설 수 없습니다.")
            mark(rid, "퇴사일", "입사일보다 앞설 수 없습니다.")

        if role not in _ROLE_TO_LABEL:
            errors.append(f"{tag}: 권한을 선택하세요. (관리자/조장/조원)")
            mark(rid, "권한", "권한을 선택하세요. (관리자/조장/조원)")

        # 이메일(선택 입력) — 형식만 화면에서 먼저 막는다. 값 자체는 users 레코드가
        # 아니라 user_emails 로 따로 저장하므로 records 계약(USER_COLUMNS)에 넣지 않는다.
        email_raw = str(row.get(EMAIL_COL) or "").strip()
        if email_raw and not _valid_email(email_raw):
            errors.append(f"{tag}: 이메일 형식이 올바르지 않습니다. (입력값: {email_raw})")
            mark(rid, EMAIL_COL, "이메일 형식이 올바르지 않습니다.")

        # 표시순서: 빈 값=미지정(NULL), 정수만 허용, 1 이상 권장.
        display_order = None
        order_raw = str(row.get("표시순서") or "").strip()
        if order_raw:
            try:
                display_order = db.normalize_display_order(order_raw)
            except (TypeError, ValueError):
                errors.append(f"{tag}: 표시순서는 숫자여야 합니다. (입력값: {order_raw})")
                mark(rid, "표시순서", "표시순서는 숫자여야 합니다.")
            if display_order is not None and display_order < 1:
                errors.append(f"{tag}: 표시순서는 1 이상이어야 합니다.")
                mark(rid, "표시순서", "표시순서는 1 이상이어야 합니다.")

        records.append({
            "emp_no": emp_no,
            "name": name,
            "dept_code": dept_code,
            "team_code": team_code,
            "position": position,
            "role": role,
            "is_active": grid_bool(row.get("재직")),
            "display_order": display_order,
            "hire_date": hire_date,
            "resign_date": resign_date,
        })
    return records, errors, cell_errors


def _validate(live, dept_resolver, team_resolve):
    """저장 계약용 (records, errors). 셀 마커 메타 없이 기존 시그니처를 유지한다."""
    records, errors, _cells = _scan(live, dept_resolver, team_resolve)
    return records, errors


# ---------------------------------------------------------------------------
# 행 상태 헬퍼 · dirty(변경) 판별
# ---------------------------------------------------------------------------
def _new_row(state: DraftState) -> dict:
    row = {"_row_id": state.next_rid(), "_row_state": "new", "_sel": False}
    for c in _USER_COLS:
        row[c] = True if c == "재직" else ""
    return row


def _norm(value, col: str):
    return grid_bool(value) if col == "재직" else str(value if value is not None else "").strip()


def _baseline_of(rows: pd.DataFrame) -> dict[str, dict]:
    """기존 행의 로드 시점 표시값 스냅샷 — 변경(dirty) 셀 비교 기준."""
    baseline: dict[str, dict] = {}
    for _, r in rows.iterrows():
        if str(r.get("_row_state")) == "existing":
            baseline[str(r["_row_id"])] = {c: _norm(r.get(c), c) for c in _USER_COLS}
    return baseline


def _changed(existing_live: pd.DataFrame, baseline: dict) -> tuple[set, dict]:
    """기준 대비 변경된 기존 행 id 집합과 {row_id: [변경 필드]} 를 반환한다."""
    changed_ids: set = set()
    dirty_map: dict[str, list[str]] = {}
    for _, r in existing_live.iterrows():
        rid = str(r["_row_id"])
        base = baseline.get(rid)
        if base is None:
            continue
        fields = [c for c in _USER_COLS if _norm(r.get(c), c) != base.get(c)]
        if fields:
            changed_ids.add(rid)
            dirty_map[rid] = fields
    return changed_ids, dirty_map


def _row_filled(row) -> bool:
    """신규 행이 저장 대상(비어있지 않음)인지 — validate 의 빈 행 skip 과 동일 기준."""
    return any(str(row.get(c) or "").strip() for c in _CONTENT_COLS)


# ---------------------------------------------------------------------------
# 그리드 셀 렌더러 / 에디터 (module-level — render() 소스에 상태 라벨 리터럴을 두지 않는다)
# ---------------------------------------------------------------------------
def _dept_renderer(hint_json: str) -> JsCode:
    """부서 셀: 표시명 + 소속 그룹 보조 라벨(§25 N2). 빈 값은 placeholder.

    문자열 반환 renderer 는 ag-grid-react 경로에서 이스케이프되어 텍스트로 노출되므로,
    ``_ROW_ACTION_RENDERER`` 처럼 component class 로 DOM 을 만든다. DB 값(부서명·그룹명)은
    ``textContent`` 로만 넣어 innerHTML 조합을 하지 않는다(HTML 인젝션·원문 노출 차단).
    """
    return JsCode(
        """
        (class {
          init(p){
            var H = %s;
            var e = document.createElement('span');
            e.style.display = 'inline-flex'; e.style.alignItems = 'center';
            e.style.gap = '4px'; e.style.paddingRight = '14px';
            var v = (p.value == null) ? '' : String(p.value);
            if(!v){
              var ph = document.createElement('span');
              ph.style.color = '#908C83'; ph.textContent = '부서 선택';
              e.appendChild(ph); this.eGui = e; return;
            }
            e.appendChild(document.createTextNode(v));
            var g = H[v];
            if(g){
              var s = document.createElement('span');
              s.style.color = '#5F5C55'; s.style.fontSize = '12px';
              s.textContent = '\\u00B7 ' + String(g);
              e.appendChild(s);
            }
            this.eGui = e;
          }
          getGui(){ return this.eGui; }
          refresh(){ return false; }
        })
        """ % hint_json
    )


def _email_renderer(extra_json: str) -> JsCode:
    """이메일 셀: 대표 주소 + (다른 주소가 더 있으면) '+N' 보조 배지.

    그리드 슬롯은 scope=ALL 대표 1건이라, 같은 사람의 담당별·추가 주소가 화면에서
    사라진 것처럼 보이지 않게 건수를 병기한다(편집은 하단 '담당 권한·알림 이메일').
    ``_dept_renderer`` 와 같은 component class + textContent 계약(HTML 조합 금지).
    """
    return JsCode(
        """
        (class {
          init(p){
            var X = %s;
            var e = document.createElement('span');
            e.style.display = 'inline-flex'; e.style.alignItems = 'center';
            e.style.gap = '4px'; e.style.paddingRight = '10px';
            var v = (p.value == null) ? '' : String(p.value);
            if(v){ e.appendChild(document.createTextNode(v)); }
            var d = p.data || {};
            var n = X[(d['사번'] == null) ? '' : String(d['사번'])];
            if(n){
              var s = document.createElement('span');
              s.style.color = '#5F5C55'; s.style.fontSize = '12px';
              s.title = '담당별·추가 주소 ' + String(n) + '건 — 아래 담당 권한·알림 이메일에서 편집';
              s.textContent = '+' + String(n);
              e.appendChild(s);
            }
            this.eGui = e;
          }
          getGui(){ return this.eGui; }
          refresh(){ return false; }
        })
        """ % extra_json
    )


def _team_editor_params(teams_json: str) -> JsCode:
    """조 셀 에디터: 선택한 부서에 속한 조만 값으로 제공(부서 종속 드롭다운)."""
    return JsCode(
        """
        function(p){
          var M = %s;
          var d = (p.data && p.data['부서']!=null) ? String(p.data['부서']) : '';
          var vals = M[d];
          if(!vals){ vals = ['']; }
          return { values: vals };
        }
        """ % teams_json
    )


# 성명 셀: 배경색과 함께 상태를 이중 부호화하는 단색 텍스트 배지(컬러 이모지 금지, §8).
# 문자열 반환 대신 component class 로 DOM 을 만든다(성명은 textContent, 배지 라벨은 고정 문자열).
_NAME_STATUS_RENDERER = JsCode(
    """
    (class {
      init(p){
        var d = p.data || {};
        var e = document.createElement('span');
        e.style.display = 'inline-flex'; e.style.alignItems = 'center'; e.style.gap = '6px';
        var v = (p.value == null) ? '' : String(p.value);
        e.appendChild(document.createTextNode(v));
        var label = '', fg = '';
        var hasErr = (d._error != null && d._error !== '' && d._error !== '{}');
        if(hasErr){ label = '오류'; fg = '#9A3B2E'; }
        else if(d._delete === '1' || d._delete === 1){ label = '퇴직예정'; fg = '#9A3B2E'; }
        else if(d._protected === '1' || d._protected === 1){ label = '보호'; fg = '#1E3A6E'; }
        else if(d._inactive === '1' || d._inactive === 1){ label = '퇴직'; fg = '#5F5C55'; }
        if(label){
          // 배경은 .ms-badge(transparent)로 행 상태색을 상속하고, 색·테두리(currentColor)만
          // 지정한다 — 틴트행(퇴직/삭제/보호/신규) 위 흰배지 충돌 해소(#2/#5).
          var b = document.createElement('span');
          b.className = 'ms-badge';
          b.style.color = fg;
          b.textContent = label;
          e.appendChild(b);
        }
        this.eGui = e;
      }
      getGui(){ return this.eGui; }
      refresh(){ return false; }
    })
    """
)


# ---------------------------------------------------------------------------
# 권한·재직 열은 값 그대로 보여 준다(권한=평문 + ▾ / 재직=공용 native 체크박스).
# 종전에는 권한 3색 pill · 재직 녹색 pill 을 덮어써, 값을 읽어야 할 표 안에서 색면 두 개가
# 먼저 눈을 끌었다(2026-08-19 사용자 판단: 표 안 장식성 색 채움 폐지). 상태의 이중부호화는
# 성명 열 배지(_NAME_STATUS_RENDERER: 퇴직·퇴직예정·보호·오류)와 행 상태 배경이 이미 담당하고,
# 저장 실패·검증 실패 신호(ms-row-error/ms-cell-error)는 기능이므로 그대로 둔다.
# 재직은 bool 열이라 렌더러를 걷으면 공용 native 체크박스로 돌아간다 — 편집 계약(더블클릭/
# Enter 토글)과 보호행 흐림(.ms-row-protected .ag-checkbox-input-wrapper)은 공용이 유지한다.
# pill 이 쓰던 12.5px 도 DESIGN §1.2 네 단계(24·20·14·12) 밖이었다.


# ---------------------------------------------------------------------------
# 세션 오류/결과 메타 (실패 시 draft 보존 + 셀/배너 표시 — 재적재 없이 메타만 갱신 §25)
# ---------------------------------------------------------------------------
def _store_errors(state: DraftState, messages: list, cell_errors: dict) -> None:
    st.session_state[state.key("err_msgs")] = list(messages)
    st.session_state[state.key("err_cells")] = dict(cell_errors)
    st.session_state.pop(state.key("save_result"), None)


def _store_result(state: DraftState, result: PersistResult) -> None:
    st.session_state[state.key("save_result")] = result
    st.session_state.pop(state.key("err_msgs"), None)
    st.session_state.pop(state.key("err_cells"), None)


def _clear_feedback(state: DraftState) -> None:
    for suffix in ("err_msgs", "err_cells", "save_result", "delete_error"):
        st.session_state.pop(state.key(suffix), None)


def _persist_users(page_id: str, merged, records) -> PersistResult:
    """실제 저장 — 부분성공 원장(save_users_report)을 그대로 PersistResult 로 반환한다.

    자체 success 를 만들지 않는다: batch 경계 실패의 saved/failed 자연키·재시도·불명이
    controller/UI 까지 전달되도록 데이터 계층 결과 계약(§22)을 신뢰한다.
    """
    report = db.save_users_report(merged)
    return PersistResult(page_id=page_id, **report.to_persist_kwargs())


def _reconcile_partial(state: DraftState, live: pd.DataFrame, saved_keys) -> None:
    """부분 성공 후 성공 자연키만 authoritative 초안/baseline 에 reconcile 한다(§22).

    저장된 사번 행은 baseline 을 현재값으로 갱신해 더 이상 dirty 로 보이지 않게 하고,
    신규 행은 기존 행으로 전환한다. 실패/미저장 행의 draft·변경 표식은 그대로 보존한다.
    """
    if live is None or live.empty:
        return
    saved = {str(k).strip() for k in (saved_keys or [])}
    frame = live[_ROW_COLS].copy().reset_index(drop=True)
    baseline = dict(st.session_state.get(state.key("baseline")) or {})
    for idx, r in frame.iterrows():
        emp = str(r.get("사번") or "").strip()
        if not emp or emp not in saved:
            continue
        rid = str(r["_row_id"])
        if str(r["_row_state"]) != "existing":
            rid = f"e:{emp}"
            frame.at[idx, "_row_id"] = rid
            frame.at[idx, "_row_state"] = "existing"
            frame.at[idx, "_sel"] = False
        baseline[rid] = {c: _norm(r.get(c), c) for c in _USER_COLS}
    state.set_rows(frame[_ROW_COLS].reset_index(drop=True))
    st.session_state[state.key("baseline")] = baseline
    state.bump_nonce()


def _summarize_delete(report, emps: list, active_targets: list) -> tuple[str, list, str]:
    """삭제 저장 원장(BatchWriteResult) → (outcome, failed_targets, message).

    outcome: 'done'(전체 반영) | 'partial'(일부 실패, 성공분 반영·실패분 재시도) |
    'unknown'(결과 불명 — 재조회 필요). 순수 함수(테스트 대상)."""
    if getattr(report, "unknown", False):
        msg = "결과를 확인할 수 없습니다(통신 불명). 재조회 후 실패분만 다시 시도하세요"
        if getattr(report, "error", None):
            msg += f": {report.error}"
        return "unknown", list(emps), msg
    failed = {str(k).strip() for k in getattr(report, "failed_keys", [])}
    failed_targets = [e for e in emps if e in failed]
    if failed_targets:
        msg = f"{len(failed_targets)}명을 퇴직 처리하지 못했습니다"
        if getattr(report, "error", None):
            msg += f": {report.error}"
        msg += ". 나머지는 반영되었으며, 실패분만 다시 시도할 수 있습니다."
        return "partial", failed_targets, msg
    n = len(active_targets)
    return "done", [], (f"{n}명을 퇴직(미사용) 처리했습니다." if n else "처리할 사용자가 없습니다.")


# ---------------------------------------------------------------------------
# 적재 / 삭제 / 저장
# ---------------------------------------------------------------------------
def _load_editor(state: DraftState, q: dict, dept_names: dict, team_display: dict,
                 source: pd.DataFrame | None = None) -> None:
    """조회 조건(재직/부서/권한/검색)으로 대상 사용자를 편집기에 적재한다(모두 기존 행)."""
    source = db.get_users() if source is None else source
    df = source.copy()
    if q["active"] == "재직":
        df = df[df["is_active"].astype(bool)]
    elif q["active"] == "퇴직":
        df = df[~df["is_active"].astype(bool)]
    if q["dept"] != _ALL:
        df = df[df["dept_code"] == q["dept"]]
    if q["role"] != _ALL:
        df = df[df["role"].astype(str).str.upper() == q["role"]]
    term = str(q.get("search", "")).strip()
    if term:
        hit = (
            df["emp_no"].astype(str).str.contains(term, case=False, na=False, regex=False)
            | df["name"].astype(str).str.contains(term, case=False, na=False, regex=False)
        )
        df = df[hit]
    df = df.sort_values(["dept_code", "team_code", "emp_no"]).reset_index(drop=True)

    labels = _dept_labels(dept_names)
    # 알림 이메일(010) — 표시 대상 사번만 조회한다. 실패/미준비는 값을 만들지 않고
    # 사유를 남겨 이메일 열을 조회 전용으로 내린다(빈 값 덮어쓰기 방지).
    emails, extra, email_error = _email_map([] if df.empty else df["emp_no"])
    st.session_state[state.key("email_extra")] = extra
    st.session_state[state.key("email_error")] = email_error
    if df.empty:
        rows = pd.DataFrame(columns=_ROW_COLS)
    else:
        rows = pd.DataFrame({
            "_row_id": "e:" + df["emp_no"].astype(str),
            "_row_state": "existing",
            "_sel": False,
            "사번": df["emp_no"].fillna("").astype("string"),
            "성명": df["name"].fillna("").astype("string"),
            "부서": df["dept_code"].map(labels).fillna("").astype("string"),
            "직급": df["position"].fillna("").astype("string"),
            "권한": df["role"].map(_ROLE_TO_LABEL).fillna("").astype("string"),
            EMAIL_COL: [emails.get(str(e).strip(), "") for e in df["emp_no"]],
            "입사일": [_date_text(v) for v in df.get("hire_date", pd.Series([None] * len(df)))],
            "퇴사일": [_date_text(v) for v in df.get("resign_date", pd.Series([None] * len(df)))],
            "표시순서": [_order_text(v) for v in df.get("display_order", pd.Series([None] * len(df)))],
            "재직": df["is_active"].fillna(True).astype(bool),
        })[_ROW_COLS]
    rows = rows[_ROW_COLS].reset_index(drop=True)
    state.set_rows(rows)
    st.session_state[state.key("baseline")] = _baseline_of(rows)
    st.session_state[state.key("dirty_map")] = {}
    st.session_state.pop(state.delete_plan_key, None)
    state.set_dirty(False)
    _clear_feedback(state)
    state.bump_nonce()


def _add_row(state: DraftState, grid_df: pd.DataFrame) -> None:
    live = live_rows(grid_df)
    state.set_rows(pd.concat(
        [live[_ROW_COLS], pd.DataFrame([_new_row(state)])], ignore_index=True,
    )[_ROW_COLS])
    state.set_dirty(True)
    state.bump_nonce()
    st.rerun()


def _normalize(state: DraftState, grid_df: pd.DataFrame) -> bool:
    """붙여넣기로 늘어난(id 없는) 행·− 제거 표식을 권위 상태에 반영한다."""
    if grid_df is None or grid_df.empty or "_row_id" not in grid_df.columns:
        return False
    if "_removed" in grid_df:
        removed = grid_df["_removed"].fillna("").astype(str).str.strip() == "1"
    else:
        removed = pd.Series(False, index=grid_df.index)
    live = grid_df[~removed].copy()
    rid = live["_row_id"].fillna("").astype(str).str.strip()
    needs_id = rid == ""
    if not bool(removed.any() or needs_id.any()):
        return False
    live["_row_id"] = rid
    for idx in live.index[needs_id]:
        live.at[idx, "_row_id"] = state.next_rid()
        live.at[idx, "_row_state"] = "new"
        live.at[idx, "_sel"] = False
    live["_row_state"] = live["_row_state"].fillna("").astype(str).replace("", "new")
    state.set_rows(live[_ROW_COLS].reset_index(drop=True))
    state.set_dirty(True)
    state.bump_nonce()
    return True


def _handle_delete(state: DraftState, grid_df: pd.DataFrame) -> None:
    live = live_rows(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    emps = sorted({
        str(r["_row_id"])[2:] for _, r in sel.iterrows()
        if str(r["_row_id"]).startswith("e:") and not _is_protected(str(r["_row_id"])[2:])
    })
    if not emps:
        state.set_flash("warning", "퇴직 처리할 기존 사용자를 선택하세요.")
        st.rerun()
    st.session_state.pop(state.key("delete_error"), None)  # 이전 시도 사유 초기화
    st.session_state[state.delete_plan_key] = emps
    st.rerun()


def _execute_delete(state: DraftState, emps: list, q: dict, dept_names: dict, team_display: dict) -> None:
    """선택 사용자를 소프트 삭제(is_active=False)한다 — 물리 삭제하지 않는다.

    저장은 부분성공 원장(save_users_report)으로 수행하고, 통신 오류(DATA_SOURCE_ERRORS)는
    controller 경계에서 잡아 raw 예외 대신 재시도 가능한 확인 바로 되돌린다. 성공분만 재조회로
    반영하고 실패분은 재시도 계획으로 남긴다(2단계 확인·soft-delete 계약 유지).
    """
    store = db.get_users().copy()
    emp_str = store["emp_no"].astype(str)
    active_targets = [
        e for e in emps
        if (emp_str == e).any() and bool(store.loc[emp_str == e, "is_active"].astype(bool).any())
    ]
    store.loc[emp_str.isin(emps), "is_active"] = False
    try:
        report = db.save_users_report(store[db.USER_COLUMNS])
    except db.DATA_SOURCE_ERRORS as exc:
        # 통신/데이터 소스 오류 — 저장 여부 불명. 재시도 계획 유지 + 사유 banner.
        st.session_state[state.key("delete_error")] = f"통신 오류로 퇴직 처리를 완료하지 못했습니다: {exc}"
        st.session_state[state.delete_plan_key] = list(emps)
        st.rerun()

    outcome, failed_targets, message = _summarize_delete(report, list(emps), active_targets)

    if outcome == "unknown":
        # 결과 불명 — 재조회하지 않고 계획 유지(성공 단정 금지).
        st.session_state[state.key("delete_error")] = message
        st.session_state[state.delete_plan_key] = list(emps)
        st.rerun()

    # 성공분(및 no-op)은 실제 store 에 반영됨 → 재조회로 반영(feedback·계획 정리).
    _load_editor(state, q, dept_names, team_display)
    if outcome == "partial":
        st.session_state[state.delete_plan_key] = failed_targets  # 실패분만 재시도
        st.session_state[state.key("delete_error")] = message
    else:
        state.set_flash("success" if active_targets else "warning", message)
    st.rerun()


def _persist_emails(state, live: pd.DataFrame, allowed, actor: str) -> list[str]:
    """그리드 이메일 슬롯(scope=ALL 대표 1건)을 저장한다 — 실패 사번 사유 목록 반환.

    **사용자 저장이 끝난 뒤에만** 호출한다: 신규 행은 그때 비로소 계정(user_id)이
    존재하고, 이메일 파사드는 사번으로 그 id 를 해석한다(사용자 저장 → id 확보 →
    이메일 저장). ``allowed`` 가 주어지면(부분 성공) 실제로 저장된 사번만 반영한다.

    변경된 행만 건드린다 — 로드 시점 값(baseline)과 같으면 조회·쓰기 모두 생략하므로,
    손대지 않은 사용자의 다중 이메일이 저장 때문에 재작성되는 일이 없다. 쓸 때도
    기존 목록에서 대표 주소 1건만 교체한다(``_merge_email_rows``).
    """
    if st.session_state.get(state.key("email_error")):
        return []  # 현재 목록을 못 읽은 상태 — 덮어쓰지 않는다(조회 전용 열)
    if live is None or live.empty or EMAIL_COL not in live.columns:
        return []
    baseline = st.session_state.get(state.key("baseline")) or {}
    allow = None if allowed is None else {str(k).strip() for k in allowed}
    failures: list[str] = []
    for _, row in live.iterrows():
        emp = str(row.get("사번") or "").strip()
        if not emp or (allow is not None and emp not in allow):
            continue
        value = str(row.get(EMAIL_COL) or "").strip()
        was = str((baseline.get(str(row.get("_row_id") or "")) or {}).get(EMAIL_COL, "")).strip()
        if value.lower() == was.lower():
            continue
        try:
            db.set_user_emails(emp, _merge_email_rows(db.get_user_emails(emp), value),
                               actor_emp_no=actor)
        except (ValueError, *db.DATA_SOURCE_ERRORS) as exc:
            failures.append(f"{emp}: {exc}")
    return failures


def _save(state, grid_df, q, dept_names, team_resolve, team_display, ready: bool,
          actor: str = "") -> None:
    """편집 결과를 검증하고 사번 기준 upsert 로 병합해 저장한다(오류 시 전체 차단).

    필터로 보이지 않는 기존 사용자를 자동 퇴직 처리하지 않는다(loaded_keys 비움).
    검증 실패는 persist 미호출로 초안을 유지하고, 저장 예외는 '결과 불명'으로 초안을 보존한다.
    이메일은 users 레코드가 아니라 별도 테이블이라, 사용자 저장이 성공한 뒤 성공한
    사번에 대해서만 이어서 반영한다(``_persist_emails``).
    """
    live = live_rows(grid_df)
    records, row_errors, cell_errors = _scan(live, _dept_resolver(dept_names), team_resolve)

    # 운영단위(team) 배정 보존 — 화면에 조 편집 칸이 없으므로(2026-08-07) 기존 사용자의
    # team_code 를 권위 스토어에서 되살려 실어 보낸다. 그리드는 spec.order+META 컬럼만
    # 왕복시키므로 숨김 컬럼으로는 보존할 수 없다(저장 시 전원 team_id 소거 사고 방지 —
    # 2026-08-07 code-review P1). 신규 사번은 빈 값(미배정) 그대로 둔다.
    if records:
        stored_team = {
            str(r["emp_no"]).strip(): str(r["team_code"] or "").strip()
            for _, r in db.get_users().iterrows()
        }
        for rec in records:
            if not str(rec.get("team_code") or "").strip():
                rec["team_code"] = stored_team.get(rec["emp_no"], "")

    # display_order 004 게이트 — 화면 방어(저장소 upsert_users 와 이중 방어).
    if not ready:
        blocked = [
            str(rec.get("emp_no") or "(사번 없음)")
            for rec in records if rec.get("display_order") is not None
        ]
        if blocked:
            row_errors = row_errors + [
                "표시순서 기능이 준비되지 않아 다음 항목의 표시순서를 저장할 수 없습니다: " + ", ".join(blocked)
            ]

    ctx: dict = {}

    def _build(recs):
        store = db.get_users()
        merged, dup, n_c, n_u, _n_d = db.upsert_records(
            store, recs, set(), ["emp_no"], "is_active", db.USER_COLUMNS,
        )
        build_errors = []
        if dup:
            build_errors.append("사번이 중복되었습니다: " + ", ".join(k[0] for k in dup))
        # 표시순서 충돌 — 부서가 아니라 '부서그룹' 기준, 활성 사용자만, 저장 후 전체(merged) 기준.
        build_errors.extend(db.display_order_conflicts(merged, db.dept_group_map()))
        ctx.update(merged=merged, n_c=n_c, n_u=n_u)
        return merged, build_errors

    outcome = run_save(
        state, validate=lambda: (records, row_errors), build_candidate=_build,
        persist=lambda merged, recs: _persist_users(state.page_id, merged, recs),
    )

    if outcome.status == "saved":
        # 사용자 저장 성공 → 이메일 반영(신규 행도 이 시점엔 계정이 있다) → 재조회.
        mail_failed = _persist_emails(state, live, None, actor)
        _load_editor(state, q, dept_names, team_display)  # 저장된 스토어 기준 재조회
        saved_msg = f"사용자를 저장했습니다. (신규 {ctx.get('n_c', 0)} · 수정 {ctx.get('n_u', 0)})"
        if mail_failed:
            state.set_flash("warning", saved_msg + " 다만 알림 이메일은 저장하지 못했습니다 — "
                            + "; ".join(mail_failed))
        else:
            state.set_flash("success", saved_msg)
    elif outcome.status == "invalid":
        _store_errors(state, outcome.errors, cell_errors)
    elif outcome.status == "partial":
        # 성공 자연키만 reconcile(초안 clean), 실패 key draft/재시도는 보존(§22).
        # 이메일도 **성공한 사번만** 반영한다(실패 사번은 계정이 없을 수 있다).
        mail_failed = _persist_emails(state, live, outcome.result.succeeded_keys, actor)
        _reconcile_partial(state, live, outcome.result.succeeded_keys)
        _store_result(state, outcome.result)
        if mail_failed:
            state.set_flash("warning", "알림 이메일을 저장하지 못했습니다 — " + "; ".join(mail_failed))
    else:  # unknown / failed — 초안 보존, 결과 원장 배너로 표기
        if outcome.result is not None:
            _store_result(state, outcome.result)
        else:
            _store_errors(state, outcome.errors, cell_errors)
    st.rerun()


# ---------------------------------------------------------------------------
# 건수 행 / 헤더 아이콘 동기화
# ---------------------------------------------------------------------------
def _count_row_html(total: int, active: int, retired: int,
                    new: int, changed: int, sel: int) -> str:
    """건수 행 HTML — 좌: 사용자 건수·재직/퇴직, 우: 저장 필요 여부·선택·진입점 안내.

    액션 버튼이 상단 헤더로 올라가면서 사라진 두 신호(저장 badge 의 미저장 건수,
    삭제 활성으로 읽던 선택 건수)를 텍스트로 남긴다 — 저장이 필요한지, 왜 삭제가
    활성인지 화면에서 계속 읽을 수 있어야 한다. 모든 값이 정수라 이스케이프 불필요.
    """
    dist = (f"<span class='dist'>재직 {int(active)} · 퇴직 {int(retired)}</span>"
            if int(total) else "")
    dirty = int(new) + int(changed)
    if dirty:
        parts = [p for p in (f"신규 {int(new)}" if new else "",
                             f"변경 {int(changed)}" if changed else "") if p]
        status = (f"<span class='wip'>미저장 {dirty}건"
                  f"<span class='sub'>({' · '.join(parts)})</span></span>")
    else:
        status = "<span class='calm'>미저장 변경 없음</span>"
    if int(sel):
        status += f"<span class='sep'>|</span><span class='sel'>선택 {int(sel)}건</span>"
    status += ("<span class='sep'>|</span>"
               "<span class='hint'>추가·삭제·저장·새로고침은 상단 아이콘</span>")
    return (f"<div class='mu-crow'><span class='t'>사용자</span>"
            f"<span class='pill'>{int(total)}</span>{dist}"
            f"<span class='gap'></span>{status}</div>")


def _sync_header(specs: list[dict]) -> None:
    """헤더 아이콘 발행값이 바뀐 run 에서만 1회 재실행해 상단 아이콘을 따라오게 한다.

    앱 셸(``modules/ui.app_shell``)은 본문보다 **먼저** 헤더를 그리므로, 화면이 지금
    발행하는 활성/사유는 다음 run 부터 반영된다. 화면 안 버튼이 있던 동안에는 그 지연이
    보이지 않았지만(같은 run 에 정상 버튼이 있었다), 헤더가 유일한 진입점이 된 뒤로는
    "선택했는데 삭제 아이콘이 계속 음영" 같은 실동작 결함이 된다. 그래서 발행값이 직전
    run 과 다르면 즉시 재실행한다 — 같은 입력이면 두 번째 run 에서 값이 같아져 멈춘다.

    ``modules/ui`` 를 수정하지 않고 화면 쪽에서만 닫는 보정이며, 폭주 방지로 연속
    보정 횟수를 2회로 제한한다(정상 경로에서는 상태 전이당 1회).
    """
    payload = {s["role"]: (bool(s.get("disabled")), s.get("help")) for s in specs}
    mirror_key, guard_key = f"{PAGE_ID}:hdr_mirror", f"{PAGE_ID}:hdr_sync_n"
    if st.session_state.get(mirror_key) == payload:
        st.session_state[guard_key] = 0
        return
    st.session_state[mirror_key] = payload
    tries = int(st.session_state.get(guard_key) or 0)
    if tries < 2:
        st.session_state[guard_key] = tries + 1
        st.rerun()


# ---------------------------------------------------------------------------
# 렌더
# ---------------------------------------------------------------------------
def render(user: dict) -> None:
    state = DraftState(PAGE_ID)

    # 취소로 요청된 필터 위젯 복원은 위젯 생성 전에 처리한다(인스턴스 후 수정 예외 방지).
    if st.session_state.pop(state.key("restore_filters"), False):
        prev = state.query() or {}
        if prev:
            st.session_state[_F_ACTIVE] = prev.get("active", "전체")
            st.session_state[_F_DEPT] = prev.get("dept", _ALL)
            st.session_state[_F_ROLE] = prev.get("role", _ALL)
            st.session_state[_F_SEARCH] = prev.get("search", "")

    depts = db.get_departments()
    teams = db.get_teams()
    dept_names = {str(r["dept_code"]): str(r["dept_name"]) for _, r in depts.iterrows()}
    team_resolve, team_display = _team_maps(teams)
    dept_labels = _dept_labels(dept_names)
    group_of = db.dept_group_map()

    # 부서 라벨 → 그룹명 보조 라벨(부서명과 다를 때만). 조 편집 칼럼은 2026-08-07 제거
    # (근무조는 편성표 직접입력) — _dept_team_options/_team_editor_params 는 미배선.
    hint_json = json.dumps(_group_hints(group_of, dept_names, dept_labels), ensure_ascii=False)

    readiness = _readiness()
    # §1-E 표형(구조 교체) — 아이콘 밴드 제거(§0-3). 실기능 액션(행 추가·삭제·저장·새로고침)은
    # 건수 행 우측으로 이전하고, 그리드 저장/dirty/2단계 삭제 계약은 전부 보존(표현 계층만).
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="사용자 관리",
        desc="사번·소속·권한을 표에서 직접 편집하고 [저장]으로 일괄 반영합니다.",
        breadcrumb="기준정보 › 사용자 관리",
    )
    # 페이지 CSS 주입은 **제목 뒤**에 둔다 — style 전용 markdown 도 블록 하나를 차지해
    # 앞에 두면 제목이 9px 내려앉고, 조직·근무형태 화면(제목 뒤 주입)과 제목 기준선이
    # 어긋난다(2026-08-14 실측: 제목 y 115.0 vs 105.9).
    st.markdown(_MU_CSS, unsafe_allow_html=True)
    # readiness 배너(NOT_READY/PROBE_ERROR 만) + 확인 실패 시 재프로브 — 조직 화면과 동일 UX(§25).
    readiness.banner()
    if readiness.state is Readiness.PROBE_ERROR:
        if st.button("스키마 재확인", key=f"{PAGE_ID}__recheck", icon=":material/refresh:"):
            db.reset_org_schema_cache()
            st.rerun()

    refresh = state.take_action(REFRESH)
    if refresh:
        # 새로고침은 '다시 읽는다'는 뜻이다 — 읽기 캐시를 이 화면 범위만 좁게
        # 비워야 아래 재적재가 실제 재조회가 된다(전역 clear 는 쓰지 않는다).
        db.refresh_reference_data("users")

    # ---- 조건 패널(우측 인라인 라벨, KP-standard) — 위젯 key 는 기존 필터 세션 key
    #      상수(_F_ACTIVE/_F_DEPT/_F_ROLE/_F_SEARCH)를 widget_key 로 그대로 지정해
    #      restore_filters 되돌리기 경로를 변경 없이 유지한다(구조만 이전). ----
    cond = erp.condition_panel(
        PAGE_ID,
        [
            erp.Field(key="active", label="재직 여부", kind="select", options=_STATUS,
                     widget_key=_F_ACTIVE, width=130),
            erp.Field(
                key="dept", label="부서", kind="select",
                options=[_ALL] + list(dept_names),
                format_func=lambda c: "전체 부서" if c == _ALL else dept_names.get(c, c),
                widget_key=_F_DEPT, width=220,
            ),
            erp.Field(
                key="role", label="권한", kind="select",
                options=[_ALL] + list(_ROLE_TO_LABEL),
                format_func=lambda c: "전체 권한" if c == _ALL else _ROLE_TO_LABEL.get(c, c),
                widget_key=_F_ROLE, width=150,
            ),
            erp.Field(key="search", label="검색", kind="text",
                     widget_key=_F_SEARCH, placeholder="사번·성명 검색"),
        ],
        # §0.6 컨트롤 폭 내용 맞춤 — cols=4 등폭은 3~4지선다 select 를 285px(1440 기준)로
        # 늘렸다. 짧은 코드값 select 는 내용 맞춤, 검색만 신축(기준정보 3화면 동일).
        content_fit=True,
    )
    # §1-E: 필터 줄 → 헤어라인 → (건수 행 + 표). 헤어라인은 조건 패널 자체가 하단
    # border 로 그린다(views/common/erp/kit.py `[class*="st-key-erpcond_"]`) — 여기서 다시
    # 그리면 22px 간격의 이중 괘선이 된다(2026-08-14 실측 y255.3/277.9). 조직 관리는
    # 처음부터 한 줄이었으므로 세 화면 중 이 화면·근무형태만 두 줄이었다.
    params = {
        "active": cond["active"], "dept": cond["dept"], "role": cond["role"],
        "search": str(cond["search"]).strip(),
    }
    ready = readiness.write_enabled  # READY 에서만 True — org_schema_ready() bool 게이트와 동치

    # dirty 인식 재적재 — 미저장 초안이 있으면 필터/새로고침 시 무경고 소실 대신 확인을 요구한다.
    decision = state.resolve_reload(params, refresh=refresh, dirty=state.is_dirty())
    if decision == RELOAD:
        _load_editor(state, params, dept_names, team_display)
    # CONFIRM/KEEP: 현재 draft 유지(재적재 안 함).

    rows = state.get_rows()
    if rows is None:
        _load_editor(state, params, dept_names, team_display)
        rows = state.get_rows()

    # §1-E 건수 행(제목 + 건수 pill + 재직/퇴직 + 우측 액션) — sel/dirty 는 그리드 뒤 확정이라
    # 슬롯만 잡고 나중에 채운다(icon band 와 동일한 deferred 패턴 + 동일 액션 flag 계약).
    count_row_slot = st.container()
    banner_slot = st.container()   # 배너(삭제 확인/폐기 확인/원장/오류/flash 중 1)

    # ---- 그리드 표시 프레임(권위 rows + 상태 view-model) ----
    delete_plan = st.session_state.get(state.delete_plan_key) or []
    delete_ids = {f"e:{e}" for e in delete_plan}
    err_cells = st.session_state.get(state.key("err_cells")) or {}
    prev_dirty = st.session_state.get(state.key("dirty_map")) or {}

    disp = rows.copy().reset_index(drop=True)
    ids = disp["_row_id"].astype(str)
    disp["_delete"] = ids.map(lambda i: "1" if i in delete_ids else "")
    disp["_protected"] = disp["사번"].map(lambda e: "1" if _is_protected(e) else "")
    disp["_inactive"] = [
        "1" if (str(s) == "existing" and not grid_bool(a) and str(i) not in delete_ids) else ""
        for s, a, i in zip(disp["_row_state"], disp["재직"], ids)
    ]
    disp["_error"] = ids.map(lambda i: json.dumps(err_cells.get(i, {}), ensure_ascii=False) if err_cells.get(i) else "")
    disp["_dirty_fields"] = ids.map(lambda i: json.dumps(prev_dirty.get(i, []), ensure_ascii=False) if prev_dirty.get(i) else "")

    # 이메일 열: 대표 주소는 값으로, 나머지 등록 주소 수는 셀 보조 배지로 알린다(편집은
    # 대표 1건만 — 담당별 주소는 하단 편집기 소유). 조회 실패/미준비면 조회 전용으로 내린다.
    email_error = str(st.session_state.get(state.key("email_error")) or "")
    extra_json = json.dumps(
        {str(k): int(v) for k, v in (st.session_state.get(state.key("email_extra")) or {}).items()
         if int(v or 0) > 0},
        ensure_ascii=False,
    )

    spec = _grid_spec(state, hint_json, email_extra_json=extra_json,
                      email_editable=not email_error)
    grid_df = render_master_grid(spec, disp, key=state.grid_key())

    # ---- 건수/변경 계산(그리드 반환 = 현재 편집 상태) ----
    live = live_rows(grid_df)
    existing = live[live["_row_state"] == "existing"]
    new_rows = live[live["_row_state"] != "existing"]
    baseline = st.session_state.get(state.key("baseline")) or {}
    changed_ids, dirty_map = _changed(existing, baseline)
    st.session_state[state.key("dirty_map")] = {k: v for k, v in dirty_map.items()}

    new_filled = int(sum(1 for _, r in new_rows.iterrows() if _row_filled(r)))
    changed_count = len(changed_ids)
    total_dirty = dirty_total(new_filled, changed_count)
    sel_mask = existing["_sel"].map(grid_bool) & ~existing["사번"].map(_is_protected) if not existing.empty else pd.Series(dtype=bool)
    sel_count = int(sel_mask.sum()) if not existing.empty else 0
    has_order = any(str(r.get("표시순서") or "").strip() for _, r in live.iterrows())

    state.set_dirty(total_dirty > 0)

    # ---- 건수 행 채움(deferred) — 좌: 사용자 + 건수 pill + 재직/퇴직, 우: 저장 필요 여부·
    #      선택 건수·진입점 안내. 액션 버튼은 2026-08-14 사용자 지시로 화면에서 제거하고
    #      상단 52px 헤더 아이콘 하나로 일원화했다. 활성/사유 계산(page_action_specs)과
    #      클릭 플래그(page-scoped action key)는 종전 그대로라 저장·2단계 삭제 확인·재적재
    #      경로는 전부 불변이다 — 진입점만 둘에서 하나로 줄었다.
    can_save = ready or not has_order
    specs = page_action_specs(
        sel_count=sel_count, dirty_total=total_dirty, can_save=can_save,
        save_disabled_reason=(
            None if can_save else "표시순서 기능이 준비되면 저장할 수 있습니다 — 시스템 관리자에게 문의하세요"
        ),
    )
    active_ct = int(existing["재직"].map(grid_bool).sum()) if not existing.empty else 0
    retired_ct = len(existing) - active_ct
    with count_row_slot:
        st.markdown(
            _count_row_html(len(existing), active_ct, retired_ct,
                            new_filled, changed_count, sel_count),
            unsafe_allow_html=True,
        )

    # 상단 52px 헤더 아이콘(추가·삭제·저장·새로고침)에 활성 규칙을 발행한다 — 이제 이
    # 아이콘이 **유일한 진입점**이며, 클릭은 종전과 같은 page-scoped flag 를 쏜다.
    header_actions_from_specs(PAGE_ID, specs)

    # ---- 배너(우선순위: 삭제 확인 > 폐기 확인 > 결과 원장 > 오류 > flash) ----
    with banner_slot:
        _render_banners(state, delete_plan, params, dept_names, team_display,
                        new_filled, changed_count)

    # ---- 푸터 상태 스트립 + 안내 캡션 ----
    count_strip(len(existing), new_filled, changed_count, sel_count)
    st.caption("표시순서는 부서의 소속 그룹별로 정렬하며, 같은 그룹 안에서 중복되지 않는지 확인합니다.")
    if not ready:
        st.caption(
            "표시순서 기능이 아직 준비되지 않아, 표시순서를 입력하면 저장이 차단됩니다 — "
            "시스템 관리자에게 표시순서 사용 설정을 요청한 뒤 이용하세요."
        )
    if email_error:
        st.caption(
            f"{email_error} — 이메일 열은 조회 전용이며 저장 대상에서 제외됩니다. "
            "등록된 주소는 그대로 유지됩니다."
        )

    # ---- 액션 처리(셀 편집 blur 와 경합해도 다음 rerun 에서 반드시 처리) ----
    acts = take_actions(state)
    if acts[SAVE]:
        _save(grid_df=grid_df, state=state, q=params, dept_names=dept_names,
              team_resolve=team_resolve, team_display=team_display, ready=ready,
              actor=str(user.get("emp_no") or ""))
    if acts[DELETE]:
        _handle_delete(state, grid_df)
    if acts[ADD]:
        _add_row(state, grid_df)
    if _normalize(state, grid_df):
        st.rerun()

    # ---- 비밀번호 초기화 (ADMIN 전용) ----
    _render_password_reset(user, existing)

    # ---- 담당 권한·알림 이메일 (ADMIN 전용, migration 010) ----
    _render_capability_editor(user, existing)

    # ---- 헤더 아이콘 동기화(마지막) — 발행값이 바뀐 run 에서만 1회 재실행 ----
    _sync_header(specs)


def _target_options(existing: pd.DataFrame) -> list[str]:
    """ADMIN 전용 편집기(비밀번호 초기화·담당 권한/이메일)의 대상 사용자 선택지.

    입력은 **그리드 표시 프레임**이라 컬럼이 한글(사번/성명)이다 — 저장소 컬럼명
    (emp_no/name)으로 읽으면 항상 빈 목록이 돼 두 편집기가 캡션만 남고 조용히
    사라진다(2026-08-14 실화면 검증에서 발견한 기존 결함). 표시 컬럼으로 읽는다.
    """
    if existing is None or existing.empty:
        return []
    out = []
    for _, row in existing.iterrows():
        emp = str(row.get("사번") or "").strip()
        if not emp:
            continue
        name = str(row.get("성명") or "").strip()
        out.append(f"{emp} · {name}" if name else emp)
    return out


def _render_capability_editor(user: dict, existing: pd.DataFrame) -> None:
    """ADMIN 이 사용자별 담당 권한(capability)과 알림 수신 이메일을 편집한다.

    그리드 저장 경로와 완전히 분리한다 — 담당·이메일은 USER_COLUMNS 계약에 없는
    M:N 파생 데이터라 일괄 저장에 섞이면 안 된다(비밀번호 초기화 expander 와 동일 원칙).
    이메일은 복수·업무별 수신 범위(전체/특정 담당)를 지원한다: 같은 사람이 업무마다
    다른 주소(1개 또는 여러 개)를 받을 수 있다.
    """
    if not auth.is_admin(user):
        return
    if existing.empty or not config.CAPABILITIES:
        return
    probe = db.capabilities_probe()

    with st.expander("담당 권한·알림 이메일", expanded=False):
        # 미준비(저장소 없음)와 확인 불가(일시 장애)를 구분해 안내한다 — 후자를 '없음'으로
        # 덮으면 담당 지정이 사라진 것처럼 보인다(오류 은폐 금지).
        if probe == db.READINESS_PROBE_ERROR:
            st.error("담당 권한 저장소 상태를 확인하지 못했습니다(일시 장애). "
                     "잠시 후 다시 시도하세요.")
            return
        if probe != db.READINESS_READY:
            st.warning("담당 권한 저장소가 아직 준비되지 않아 조회·저장할 수 없습니다.")
            return
        st.caption(
            "업무별 담당(숙소관리·업무요청 등)을 지정하고, 접수·상태·결과 알림을 받을 "
            "이메일을 등록합니다. 이메일은 여러 개 등록할 수 있고, 수신 범위를 '전체'로 "
            "두면 모든 담당 업무의 알림을, 특정 담당으로 두면 그 업무만 받습니다."
        )
        options = _target_options(existing)
        if not options:
            return
        picked = st.selectbox("대상 사용자", options, key=f"{PAGE_ID}__cap_target")
        target_emp = str(picked).split(" · ", 1)[0].strip()

        cap_labels = {code: label for code, label in config.CAPABILITIES.items()}
        try:
            current_caps = db.get_user_capabilities(target_emp)
            current_emails = db.get_user_emails(target_emp)
        except db.DATA_SOURCE_ERRORS as exc:
            # 조회 실패를 '담당 없음'으로 그리지 않는다 — 그 화면에서 저장하면 지정이 지워진다.
            st.error(f"담당 권한·이메일을 불러오지 못했습니다: {exc}")
            return
        sel_caps = st.multiselect(
            "담당 권한", options=list(cap_labels),
            default=[c for c in current_caps if c in cap_labels],
            format_func=lambda c: f"{cap_labels[c]} ({c})",
            key=f"{PAGE_ID}__cap_sel_{target_emp}",
        )

        scope_label = {config.EMAIL_SCOPE_ALL: "전체"} | cap_labels
        email_frame = pd.DataFrame(
            current_emails or [], columns=["email", "scope"]
        ).rename(columns={"email": "이메일", "scope": "수신 범위"})
        edited = st.data_editor(
            email_frame, num_rows="dynamic", width="stretch",
            column_config={
                "이메일": st.column_config.TextColumn("이메일", width="large"),
                "수신 범위": st.column_config.SelectboxColumn(
                    "수신 범위", options=list(scope_label),
                    format_func=lambda s: scope_label.get(s, s), default=config.EMAIL_SCOPE_ALL,
                ),
            },
            key=f"{PAGE_ID}__cap_emails_{target_emp}",
        )

        if st.button("담당·이메일 저장", key=f"{PAGE_ID}__cap_save", type="primary"):
            try:
                actor = str(user.get("emp_no") or "")
                db.set_user_capabilities(target_emp, sel_caps, actor_emp_no=actor)
                rows = [
                    {"email": r.get("이메일"), "scope": r.get("수신 범위")}
                    for _, r in edited.iterrows()
                ]
                db.set_user_emails(target_emp, rows, actor_emp_no=actor)
            except (ValueError, *db.DATA_SOURCE_ERRORS) as exc:
                st.error(f"저장하지 못했습니다: {exc}")
            else:
                st.success("담당 권한과 알림 이메일을 저장했습니다.")


def _render_password_reset(user: dict, existing: pd.DataFrame) -> None:
    """ADMIN 이 사용자 비밀번호를 초기화한다 — 비번을 지워 사번이 다시 초기 비번이 되게 한다.

    그리드 저장 경로와 완전히 분리한다: 자격증명은 USER_COLUMNS 계약에 없고, 실수로
    일괄 저장에 섞이면 안 되는 값이다. 초기화하면 그 사용자의 활성 세션도 모두 끊는다.
    """
    if not auth.is_admin(user):
        return
    if existing.empty:
        return

    with st.expander("비밀번호 초기화", expanded=False):
        st.caption(
            f"선택한 사용자의 비밀번호를 지웁니다. 초기 비밀번호는 다시 **사번**이 되고, "
            f"{config.INITIAL_PASSWORD_VALID_DAYS}일 안에 로그인해 새 비밀번호를 설정해야 합니다. "
            "진행 중인 로그인 세션은 모두 해제됩니다."
        )
        options = _target_options(existing)
        if not options:
            return
        picked = st.selectbox(
            "대상 사용자", options, key=f"{PAGE_ID}__pwreset_target"
        )
        target_emp = str(picked).split(" · ", 1)[0].strip()

        confirm = st.checkbox(
            f"{picked} 의 비밀번호를 초기화합니다.",
            key=f"{PAGE_ID}__pwreset_confirm",
        )
        if st.button(
            "초기화 실행",
            key=f"{PAGE_ID}__pwreset_run",
            type="primary",
            disabled=not confirm,
        ):
            try:
                db.reset_user_password(target_emp)
                db.revoke_user_sessions(target_emp, "admin_reset")
            except Exception as exc:
                st.error(f"비밀번호 초기화에 실패했습니다: {exc}")
            else:
                st.success(
                    f"{picked} 의 비밀번호를 초기화했습니다. 초기 비밀번호는 사번입니다."
                )


def _cell_rules(field: str, readonly: str | None = None) -> dict:
    """셀 단위 오류(⚠ 인셋)·변경(warn 인셋)·읽기전용(중립 틴트) 마커.

    숨김 _error/_dirty_fields 를 읽는다. ``readonly`` 표현식이 주어지면 그 조건이 참인 셀에
    ``ms-cell-readonly`` 를 켜 편집 불가 어포던스를 붙인다(editable=false 조건과 동일 식 —
    외형·동작 일치). 상태 행 배경(!important)이 읽기전용 틴트보다 우선한다.
    """
    rules = {**cell_error_rule(field), **cell_dirty_rule(field)}
    if readonly:
        rules["ms-cell-readonly"] = readonly
    return rules


def _grid_spec(state: DraftState, hint_json: str, teams_json: str = "", *,
               email_extra_json: str = "{}", email_editable: bool = True) -> MasterGridSpec:
    # teams_json 은 조 편집 칼럼 제거(2026-08-07)로 미사용 — 교차 테스트 시그니처 호환용.
    # 데이터셀 편집 게이트: 사번(자연키)=신규행만, 그 외=보호행만 잠금(일반 저장행 편집 유지).
    # 읽기전용 시각(ms-cell-readonly)은 각 컬럼의 잠금 조건과 동일 식으로 켠다.
    col_config = {
        # 사번(자연키)은 저장행에서 편집 불가(신규행만)지만, 읽기전용 틴트는 보호행에만 준다 —
        # org 코드열과 동일(모든 저장행 과잉 틴트 회피). editable=false 자체가 키 잠금 어포던스.
        # 폭·정렬은 기준정보 3화면 공통 규격이다(2026-08-14 재검수): 코드/식별 열 108,
        # 명칭 열 114, 순서 74, 사용 여부 토글 72. 같은 성격 열이 화면마다 다른 폭으로
        # 서던 것을 없앤다(근무형태 코드 108 · 조직 코드 108 과 동일).
        # 좁은 폭에서 가로 스크롤될 때 신원(사번)이 사라지지 않도록 좌측 고정한다 —
        # 근무형태 관리 코드 열과 같은 계약(첫 열이라 열 순서는 바뀌지 않는다).
        # ── 열 폭 = 12px Pretendard 기준 역산(2026-08-19 재산정) ──
        # 종전 값은 셀 14.5px·헤더 12.5px(맑은고딕 폴백) 기준이라 전부 과대했다. DESIGN §1.2
        # 개정으로 표 셀·헤더가 모두 12px 이 되었다.
        #   필요폭 = max(값 실측 최대 잉크, 헤더 실측 잉크) + 16 → 4의 배수로 올림
        #   16 = 셀 좌우 패딩 7+7 + 보더 2(헤더 8+8). 잉크는 iframe 안 hidden span 실측이고,
        #   측정값에 5% 여유를 얹었다 — 그리드 iframe 이 지금은 Pretendard 를 못 받아
        #   sans-serif 폴백(한글 10.53px/자)으로 그려지므로, 글꼴이 정상화되면(11.04px/자)
        #   폴백 기준 폭은 그대로 잘린다.
        # **지정 폭은 고정폭이 아니라 비율이다** — 아래 grid_options 의 fitGridWidth 가 남는
        # 폭을 이 비율대로 나눈다. 그래서 flex 를 쓰지 않는다(flex 는 남는 폭을 한 열에 몰아
        # 준다: 종전 이메일 열은 값이 0건인데 198px 로 표에서 두 번째로 넓었다).
        # maxWidth 는 넓혀도 담을 것이 없는 열(체크박스·고정 서식 날짜·순서)에만 건다.
        #
        # minWidth = width: fitGridWidth 는 뷰포트가 좁으면 열을 **minWidth 까지 줄여서**
        # 맞춘다(실측 390px: 코드명 120→96 으로 눌려 값이 잘렸다). 역산한 필요폭이 곧
        # 하한이므로 둘을 같은 값으로 둔다 — 좁은 폭에서는 줄이지 말고 가로 스크롤한다.
        # 사번 60 — 표본은 4자리('9001' 26.7)지만 이 열은 pinned 라 남는 폭 분배에서 자랄
        # 여지가 없고, 6자리 사번(43.2)까지는 잘리지 않아야 하므로 43.2+16 으로 잡는다.
        "사번": {"width": 60, "minWidth": 60, "pinned": "left", "cellClass": "md-c-left",
                "editable": _EDIT_NEW_ONLY,
                "cellClassRules": _cell_rules("사번", readonly=_IS_PROTECTED_JS)},
        # 성명 104 = 이름 + 상태 배지 union 실측 최대 80.13×1.05 + 16.
        "성명": {"width": 104, "minWidth": 104, "cellClass": "md-c-left",
                "editable": _EDIT_UNLESS_PROTECTED,
                "cellRenderer": _NAME_STATUS_RENDERER,
                "cellClassRules": _cell_rules("성명", readonly=_IS_PROTECTED_JS)},
        # 부서 216 = 'PET생산부(원료실)· PET2'(부서명 + 조 보조라벨) 실측 170.14×1.05 + 16
        # + ▾ 표식 자리 14(.ms-cell-select::after 가 right:8px 에 겹친다). 이 화면에서 가장
        # 긴 값이고 행을 특정하는 소속 정보라 상한을 두지 않는다.
        "부서": {"width": 216, "minWidth": 216, "cellClass": "md-c-left ms-cell-select",
                "editable": _EDIT_UNLESS_PROTECTED,
                "cellEditor": "agSelectCellEditor",
                "cellEditorParams": {"values": _dept_option_values(state)},
                "cellRenderer": _dept_renderer(hint_json),
                "cellClassRules": _cell_rules("부서", readonly=_IS_PROTECTED_JS)},
        # 직급 60 = '파트장' 40.03×1.05 + 16.
        "직급": {"width": 60, "minWidth": 60, "cellClass": "md-c-left",
                "editable": _EDIT_UNLESS_PROTECTED,
                "cellClassRules": _cell_rules("직급", readonly=_IS_PROTECTED_JS)},
        # 권한 68 = '관리자' 평문 33.13×1.05 + 16 + ▾ 자리 14 (pill 패딩 22 제거분 반영).
        "권한": {"width": 68, "minWidth": 68, "cellClass": "md-c-center ms-cell-select",
                "editable": _EDIT_UNLESS_PROTECTED,
                "cellEditor": "agSelectCellEditor",
                "cellEditorParams": {"values": list(_LABEL_TO_ROLE)},
                "cellClassRules": _cell_rules("권한", readonly=_IS_PROTECTED_JS)},
        # 이메일(010 user_emails, scope=ALL 대표 1건) — 스키마 미준비·조회 실패면
        # editable=False + 읽기전용 틴트로 내려, 모르는 값을 빈 값으로 덮어쓰는 저장을 차단한다.
        # 폭 52 = 헤더 '이메일' 33.13×1.05 + 16. sample 에 값이 0건이라 역산 재료가 이 화면
        # 안에 없어 **헤더 하한**만 쓴다(종전 flex 1.15 는 값 0건인 열을 198px 로 만들었다).
        # 남는 폭은 fitGridWidth 가 비례로 얹어 주고, 실데이터가 들어오면 다시 재서 갱신한다.
        EMAIL_COL: {"width": 52, "minWidth": 52, "cellClass": "md-c-left",
                "editable": (_EDIT_UNLESS_PROTECTED if email_editable else False),
                "cellRenderer": _email_renderer(email_extra_json),
                "cellClassRules": _cell_rules(
                    EMAIL_COL,
                    readonly=(_IS_PROTECTED_JS if email_editable else "true"))},
        # 입사일/퇴사일 84 = 'YYYY-MM-DD' 고정 서식(숫자 8×7.2 + '-' 2 + 16). 서식이 고정이라
        # 넓혀도 담을 것이 없어 maxWidth 로 묶는다. 값 자체는 자유 타이핑 후 _clean_date 정규화.
        "입사일": {"width": 84, "minWidth": 84, "maxWidth": 84, "cellClass": "md-c-center ms-num",
                "editable": _EDIT_UNLESS_PROTECTED,
                "cellClassRules": _cell_rules("입사일", readonly=_IS_PROTECTED_JS)},
        "퇴사일": {"width": 84, "minWidth": 84, "maxWidth": 84, "cellClass": "md-c-center ms-num",
                "editable": _EDIT_UNLESS_PROTECTED,
                "cellClassRules": _cell_rules("퇴사일", readonly=_IS_PROTECTED_JS)},
        # 표시순서 64 = 헤더 44.17×1.05 + 16(값은 3자리 이하 정수라 헤더가 지배). 상한 고정.
        "표시순서": {"width": 64, "minWidth": 64, "maxWidth": 64, "cellClass": "md-c-center ms-num",
                 "editable": _EDIT_UNLESS_PROTECTED,
                 "cellClassRules": _cell_rules("표시순서", readonly=_IS_PROTECTED_JS)},
        # 재직 40 = 헤더 '재직' 22.09×1.05 + 16(체크박스 16px). bool 열이라 공용 native
        # 체크박스로 표시·편집하며(특근수당 등과 동일), 상태 텍스트는 성명 열 '퇴직' 배지가 맡는다.
        "재직": {"width": 40, "minWidth": 40, "maxWidth": 40, "cellClass": "md-c-center",
                "editable": _EDIT_UNLESS_PROTECTED,
                "cellClassRules": _cell_rules("재직", readonly=_IS_PROTECTED_JS)},
    }
    nrows = len(state.get_rows()) if state.get_rows() is not None else 0
    # 보호행 어포던스: 상태색을 덮지 않는 ms-row-protected 를 기본 cascade 위에 겹친다.
    row_rules = {**master_row_class_rules(), "ms-row-protected": _IS_PROTECTED_JS}
    return MasterGridSpec(
        page_id=PAGE_ID, columns=_GRID_COLUMNS, order=_USER_COLS, col_config=col_config,
        select_all=True, height=master_grid_height(nrows), row_class_rules=row_rules,
        # autoSizeStrategy: 지정 폭을 **비율**로 삼아 남는 가로 폭을 비례 분배한다. 없으면
        # flex 를 뺀 순간 표가 뷰포트보다 좁게 서서 "화면보다 작은 표"가 된다(실측 1440:
        # 열 폭 합 894 vs 그리드 뷰포트 1167). 공용 views/master/grid.py 에 두는 것이 옳지만
        # 그 파일은 이번 작업 범위 밖이라 화면별 grid_options 로 얹는다(3화면 동일 — 보고 대상).
        grid_options={"autoSizeStrategy": {"type": "fitGridWidth"}},
        # rowHeight 는 공용 기본값(views/master/grid.py `_GRID_ROW_PX`=40)을 쓴다. 화면에서
        # 42 로 덮으면 ① 조직 관리(40)와 행 높이가 어긋나고 ② 높이 계산(master_grid_height)이
        # 40 기준이라 행마다 2px 씩 모자라 불필요한 내부 스크롤이 생긴다(2026-08-14 재검수).
    )


def _dept_option_values(state: DraftState) -> list:
    depts = db.get_departments()
    dept_names = {str(r["dept_code"]): str(r["dept_name"]) for _, r in depts.iterrows()}
    return list(_dept_labels(dept_names).values())


def _render_summary_chips(rows: pd.DataFrame, params: dict, dept_names: dict) -> None:
    """상단 요약 스트립 — 좌: 활성(비기본) 필터 상태 칩, 우: 결과 재직/퇴직 분포.

    필터가 어떤 조건으로 좁혀졌는지 라벨로 명시한다(색만 아님). 모든 필터가 기본(전체)이면
    좌측은 비운다. 결과 0건이어도 활성 필터 칩은 표시해 왜 비었는지 알린다.
    """
    # 결과가 0건이어도 활성 필터 칩은 남겨 "왜 비었는지"를 알린다(org _summary_chips 와 동일).
    # 분포 칩(재직/퇴직)만 결과가 있을 때 렌더한다.
    existing = (
        rows[rows["_row_state"] == "existing"]
        if rows is not None and not rows.empty
        else pd.DataFrame(columns=["재직"])
    )

    filt = ""
    if params.get("active") and params["active"] != "전체":
        filt += chip_html(f"재직 여부: {params['active']}", "lock")
    if params.get("dept") and params["dept"] != _ALL:
        filt += chip_html(f"부서: {dept_names.get(params['dept'], params['dept'])}", "lock")
    if params.get("role") and params["role"] != _ALL:
        filt += chip_html(f"권한: {_ROLE_TO_LABEL.get(params['role'], params['role'])}", "lock")
    if params.get("search"):
        filt += chip_html(f"검색: {params['search']}", "lock")

    cnt = ""
    if not existing.empty:
        active = int(existing["재직"].map(grid_bool).sum())
        retired = len(existing) - active
        cnt = chip_html(f"재직 {active}", "ok")
        if retired:
            cnt += chip_html(f"퇴직 {retired}", "mute")

    if not filt and not cnt:
        return
    st.markdown(
        "<div style='display:flex;justify-content:space-between;align-items:center;"
        "gap:.5rem;margin:.1rem 0 .2rem'>"
        f"<div style='display:flex;gap:.3rem;flex-wrap:wrap'>{filt}</div>"
        f"<div style='display:flex;gap:.3rem;flex:0 0 auto'>{cnt}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_banners(state, delete_plan, params, dept_names, team_display,
                    new_filled: int, changed_count: int) -> None:
    # 1) 삭제(퇴직) 확인 바 — 2단계 확인, 실제 소프트 삭제는 여기서만 실행.
    if delete_plan:
        lines = [
            "물리 삭제가 아니라 재직 상태(is_active)를 해제하며, 과거 근무표는 그대로 유지됩니다.",
            escape(", ".join(delete_plan)),
        ]
        derr = st.session_state.get(state.key("delete_error"))
        if derr:  # 이전 시도 실패/불명 사유를 재시도 확인 바에 노출(raw 예외 대신).
            lines.insert(0, escape(str(derr)))
        result = confirm_bar(
            state,
            title=f"선택한 {len(delete_plan)}명을 퇴직 처리합니다.",
            lines=lines,
            confirm_label="퇴직 처리 실행", cancel_label="취소", danger=True, scope="del",
        )
        if result == "confirm":
            _execute_delete(state, list(delete_plan), params, dept_names, team_display)
        if result == "cancel":
            st.session_state.pop(state.delete_plan_key, None)
            st.session_state.pop(state.key("delete_error"), None)
            st.rerun()
        return

    # 2) 미저장 초안 폐기 확인(필터/새로고침으로 재적재 요청 시).
    if state.has_pending_reload():
        gate = discard_confirm_bar(state)
        if gate == "discard":
            applied = state.apply_pending_reload()
            _load_editor(state, applied or params, dept_names, team_display)
            st.rerun()
        if gate == "cancel":
            state.cancel_pending_reload()
            st.session_state[state.key("restore_filters")] = True
            st.rerun()
        return

    # 3) 저장 결과 원장(결과 불명/부분) — repository 결과 계약만 읽는다(§22).
    result = st.session_state.get(state.key("save_result"))
    if result is not None:
        ledger_banner(result)
        return

    # 4) 검증 오류 배너(초안 유지) — dirty 정보는 배너 하단 한 줄로 흡수(§17).
    messages = st.session_state.get(state.key("err_msgs")) or []
    if messages:
        absorb = ""
        total = new_filled + changed_count
        if total:
            absorb = (f"<div class='keys'>· 미저장 {total}건(신규 {new_filled} · 기존 변경 "
                      f"{changed_count})은 그대로 유지됩니다.</div>")
        body = "".join(f"<div>· {escape(str(m))}</div>" for m in messages)
        banner("danger", f"{len(messages)}건의 문제가 있어 저장하지 못했습니다.",
               extra=f"<div class='keys'>{body}</div>{absorb}")
        return

    # 5) 성공/경고/정보 flash(다음 rerun 1회).
    msg = state.pop_flash()
    if msg:
        kind, text = msg
        banner({"success": "success", "warning": "warn", "error": "danger", "info": "info"}.get(kind, "info"), text)
