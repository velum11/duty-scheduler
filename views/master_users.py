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

화면 표시 원칙:
- 부서는 부서명(중복 시 코드 병기)으로 표시하고 저장 시 dept_code 로 변환한다. 부서 셀에는
  소속 그룹명을 보조 라벨로 병기해 표시순서가 어느 그룹 범위에서 검증되는지 알린다.
- 조는 조코드가 아니라 조명(team_name)으로 표시하고, 저장 시 (부서, 조명)을 team_code 로
  변환한다. 조 드롭다운은 선택한 부서에 속한 조만 보인다(부서 종속). 조명은 관계 키가 아니다.
- 권한은 관리자/조장/조원으로 표시하고, 저장 시 ADMIN/MANAGER/USER 로 변환한다. DB 저장값과
  권한 분기 코드는 기존 값을 유지한다.

보존 계약(Phase1 §5): 변경 행만 저장(_changed_records), 완전 빈 행 skip, 소프트 삭제,
필터 미표시 사용자 자동 퇴직 금지(loaded_keys 비움), 사번 중복 차단, display_order 003
게이트(화면·저장소 이중 방어), 저장 실패 시 초안 보존.
"""
from __future__ import annotations

import json
from html import escape

import pandas as pd
import streamlit as st
from st_aggrid import JsCode

from modules import db
from views.master import (
    ADD,
    DELETE,
    REFRESH,
    RELOAD,
    SAVE,
    DraftState,
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
    ledger_banner,
    live_rows,
    master_action_bar,
    master_grid_height,
    master_row_class_rules,
    master_screen_head,
    mode_badge_html,
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
_USER_COLS = ["사번", "성명", "부서", "조", "직급", "권한", "표시순서", "재직"]
_ROW_COLS = ["_row_id", "_row_state", "_sel", *_USER_COLS]
_GRID_COLUMNS = {
    "사번": "text", "성명": "text", "부서": "text", "조": "text",
    "직급": "text", "권한": "text", "표시순서": "text", "재직": "bool",
}
# validate 가 필수/참조를 확인하는 텍스트 필드(재직/표시순서 제외) — 완전 빈 행 판별과 동일.
_CONTENT_COLS = ["사번", "성명", "부서", "조", "직급"]

# 편집 게이트(JsCode predicate) — org 화면과 동일 계약(master_org.py _EDIT_NEW_ONLY /
# _EDIT_UNLESS_PROTECTED). 자연키(사번)는 신규행만 편집(저장행 잠금), 보호행(_protected)은
# 데이터셀·재직토글을 잠근다. 일반 저장행의 성명/부서/조/권한/표시순서/재직 편집은 유지한다.
_IS_PROTECTED_JS = "(data._protected === '1' || data._protected === 1)"
_IS_EXISTING_JS = "(data._row_state !== 'new')"
_EDIT_NEW_ONLY = JsCode("function(p){ return !!(p.data && p.data._row_state === 'new'); }")
_EDIT_UNLESS_PROTECTED = JsCode(
    "function(p){ return !(p.data && (p.data._protected === '1' || p.data._protected === 1)); }"
)

# 필터 위젯 세션 key (이 화면 전용 — 취소 시 위젯 복원에 사용).
_F_ACTIVE, _F_DEPT, _F_ROLE, _F_SEARCH = "mu_active", "mu_dept", "mu_role", "mu_search"

# readiness(migration 003 확장) 안내 문구 — 표시순서(display_order) 저장이 이 확장에 의존한다.
_NOT_READY_MSG = (
    "조직 확장 migration(003)이 아직 적용되지 않아 표시순서를 저장할 수 없습니다 — 조회·편집만 가능합니다."
)
_PROBE_ERROR_MSG = (
    "스키마 상태를 확인하지 못했습니다(권한·네트워크). '스키마 재확인' 후 다시 시도하세요."
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
    """migration 003 확장 스키마 준비 상태를 3-state(READY/NOT_READY/PROBE_ERROR)로 승격한다.

    표시순서(display_order) 저장은 이 확장에 의존한다. sample 모드는 항상 READY.
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
        team_value = str(row.get("조") or "").strip()
        position = str(row.get("직급") or "").strip()
        role = role_resolver.get(str(row.get("권한") or "").strip(), "")
        dept_code = dept_resolver.get(dept_value, "")

        if not any([emp_no, name, dept_value, team_value, position]):
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

        team_code = ""
        if team_value and dept_code:
            resolved = team_resolve.get((dept_code, team_value))
            if resolved is None and (dept_code, team_value) in team_resolve:
                errors.append(f"{tag}: 조명이 부서 내에서 중복되어 특정할 수 없습니다: {team_value}")
                mark(rid, "조", f"부서 내 조명이 중복됩니다: {team_value}")
            elif resolved is None:
                errors.append(f"{tag}: 선택한 부서에 없는 조입니다: {team_value}")
                mark(rid, "조", f"선택한 부서에 없는 조입니다: {team_value}")
            else:
                team_code = resolved
        elif team_value and not dept_code:
            errors.append(f"{tag}: 조를 확인하려면 먼저 부서를 선택하세요.")
            mark(rid, "조", "소속 부서를 먼저 선택하세요.")

        if role not in _ROLE_TO_LABEL:
            errors.append(f"{tag}: 권한을 선택하세요. (관리자/조장/조원)")
            mark(rid, "권한", "권한을 선택하세요. (관리자/조장/조원)")

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
              s.style.color = '#908C83'; s.style.fontSize = '11px';
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
        else if(d._protected === '1' || d._protected === 1){ label = '보호'; fg = '#5F5C55'; }
        else if(d._inactive === '1' || d._inactive === 1){ label = '퇴직'; fg = '#908C83'; }
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
            "조": [team_display.get((str(d), str(t)), str(t or "")) for d, t in zip(df["dept_code"], df["team_code"])],
            "직급": df["position"].fillna("").astype("string"),
            "권한": df["role"].map(_ROLE_TO_LABEL).fillna("").astype("string"),
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


def _save(state, grid_df, q, dept_names, team_resolve, team_display, ready: bool) -> None:
    """편집 결과를 검증하고 사번 기준 upsert 로 병합해 저장한다(오류 시 전체 차단).

    필터로 보이지 않는 기존 사용자를 자동 퇴직 처리하지 않는다(loaded_keys 비움).
    검증 실패는 persist 미호출로 초안을 유지하고, 저장 예외는 '결과 불명'으로 초안을 보존한다.
    """
    live = live_rows(grid_df)
    records, row_errors, cell_errors = _scan(live, _dept_resolver(dept_names), team_resolve)

    # display_order 003 게이트 — 화면 방어(저장소 upsert_users 와 이중 방어).
    if not ready:
        blocked = [
            str(rec.get("emp_no") or "(사번 없음)")
            for rec in records if rec.get("display_order") is not None
        ]
        if blocked:
            row_errors = row_errors + [
                "migration 003 미적용 상태에서는 표시순서를 저장할 수 없습니다: " + ", ".join(blocked)
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
        _load_editor(state, q, dept_names, team_display)  # 저장된 스토어 기준 재조회
        state.set_flash("success", f"사용자를 저장했습니다. (신규 {ctx.get('n_c', 0)} · 수정 {ctx.get('n_u', 0)})")
    elif outcome.status == "invalid":
        _store_errors(state, outcome.errors, cell_errors)
    elif outcome.status == "partial":
        # 성공 자연키만 reconcile(초안 clean), 실패 key draft/재시도는 보존(§22).
        _reconcile_partial(state, live, outcome.result.succeeded_keys)
        _store_result(state, outcome.result)
    else:  # unknown / failed — 초안 보존, 결과 원장 배너로 표기
        if outcome.result is not None:
            _store_result(state, outcome.result)
        else:
            _store_errors(state, outcome.errors, cell_errors)
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

    # 부서 라벨 → 그룹명 보조 라벨(부서명과 다를 때만), 부서 라벨 → 소속 조명 목록(부서 종속).
    hint_json = json.dumps(_group_hints(group_of, dept_names, dept_labels), ensure_ascii=False)
    teams_json = json.dumps(_dept_team_options(teams, dept_labels), ensure_ascii=False)

    readiness = _readiness()
    master_screen_head(
        "사용자 관리",
        "사번·소속·권한을 표에서 직접 편집하고 [저장]으로 일괄 반영합니다.",
        breadcrumb="기준정보 › 사용자 관리",
        mode_badge=_head_badges(readiness),
    )
    # readiness 배너(NOT_READY/PROBE_ERROR 만) + 확인 실패 시 재프로브 — 조직 화면과 동일 UX(§25).
    readiness.banner()
    if readiness.state is Readiness.PROBE_ERROR:
        if st.button("스키마 재확인", key=f"{PAGE_ID}__recheck", icon=":material/refresh:"):
            db.reset_org_schema_cache()
            st.rerun()

    refresh = state.take_action(REFRESH)

    with st.container(key=f"{PAGE_ID}__filter"):
        f1, f2, f3, f4 = st.columns([1.2, 1.6, 1.4, 3.0], vertical_alignment="bottom")
        active = f1.selectbox("재직 여부", _STATUS, key=_F_ACTIVE, label_visibility="collapsed")
        dept = f2.selectbox(
            "부서", [_ALL] + list(dept_names),
            format_func=lambda c: "전체 부서" if c == _ALL else dept_names.get(c, c),
            key=_F_DEPT, label_visibility="collapsed",
        )
        role = f3.selectbox(
            "권한", [_ALL] + list(_ROLE_TO_LABEL),
            format_func=lambda c: "전체 권한" if c == _ALL else _ROLE_TO_LABEL.get(c, c),
            key=_F_ROLE, label_visibility="collapsed",
        )
        search = f4.text_input(
            "검색", key=_F_SEARCH, placeholder="사번·성명 검색", label_visibility="collapsed",
        )

    params = {"active": active, "dept": dept, "role": role, "search": str(search).strip()}
    ready = readiness.write_enabled  # READY 에서만 True — org_schema_ready() bool 게이트와 동치

    # dirty 인식 재적재 — 미저장 초안이 있으면 필터/새로고침 시 무경고 소실 대신 확인을 요구한다.
    decision = state.resolve_reload(params, refresh=refresh, dirty=state.is_dirty())
    if decision == RELOAD:
        _load_editor(state, params, dept_names, team_display)
    # CONFIRM/KEEP: 현재 draft 유지(재적재 안 함).

    # 요약 칩(읽기 전용): 로드된 결과의 재직/퇴직 분포.
    rows = state.get_rows()
    if rows is None:
        _load_editor(state, params, dept_names, team_display)
        rows = state.get_rows()
    _render_summary_chips(rows)

    bar_slot = st.container()      # 액션바(건수 계산 후 채움)
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

    spec = _grid_spec(state, hint_json, teams_json)
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

    # ---- 액션바(placeholder 채움) ----
    can_save = ready or not has_order
    with bar_slot, st.container(key=f"{PAGE_ID}__bar"):
        master_action_bar(
            state, sel_count=sel_count, dirty_total=total_dirty, can_save=can_save,
            save_disabled_reason=(
                None if can_save else "조직 확장 migration 003 적용 후 표시순서를 저장할 수 있습니다"
            ),
        )

    # ---- 배너(우선순위: 삭제 확인 > 폐기 확인 > 결과 원장 > 오류 > flash) ----
    with banner_slot:
        _render_banners(state, delete_plan, params, dept_names, team_display,
                        new_filled, changed_count)

    # ---- 푸터 상태 스트립 + 안내 캡션 ----
    count_strip(len(existing), new_filled, changed_count, sel_count)
    st.caption("표시순서(display_order)는 부서 셀의 소속 그룹 기준으로 정렬·중복을 검증합니다.")
    if not ready:
        st.caption(
            "표시순서 컬럼(users.display_order, migration 003)이 아직 적용되지 않아 "
            "표시순서를 입력하면 저장이 차단됩니다 — supabase/migrations/003_org_structure.sql 적용 후 사용하세요."
        )

    # ---- 액션 처리(셀 편집 blur 와 경합해도 다음 rerun 에서 반드시 처리) ----
    acts = take_actions(state)
    if acts[SAVE]:
        _save(grid_df=grid_df, state=state, q=params, dept_names=dept_names,
              team_resolve=team_resolve, team_display=team_display, ready=ready)
    if acts[DELETE]:
        _handle_delete(state, grid_df)
    if acts[ADD]:
        _add_row(state, grid_df)
    if _normalize(state, grid_df):
        st.rerun()


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


def _grid_spec(state: DraftState, hint_json: str, teams_json: str) -> MasterGridSpec:
    # 데이터셀 편집 게이트: 사번(자연키)=신규행만, 그 외=보호행만 잠금(일반 저장행 편집 유지).
    # 읽기전용 시각(ms-cell-readonly)은 각 컬럼의 잠금 조건과 동일 식으로 켠다.
    col_config = {
        "사번": {"width": 128, "minWidth": 104, "cellClass": "md-c-left",
                "editable": _EDIT_NEW_ONLY,
                "cellClassRules": _cell_rules("사번", readonly=_IS_EXISTING_JS)},
        "성명": {"width": 132, "minWidth": 100, "cellClass": "md-c-left",
                "editable": _EDIT_UNLESS_PROTECTED,
                "cellRenderer": _NAME_STATUS_RENDERER,
                "cellClassRules": _cell_rules("성명", readonly=_IS_PROTECTED_JS)},
        "부서": {"flex": 1, "minWidth": 168, "cellClass": "md-c-left ms-cell-select",
                "editable": _EDIT_UNLESS_PROTECTED,
                "cellEditor": "agSelectCellEditor",
                "cellEditorParams": {"values": _dept_option_values(state)},
                "cellRenderer": _dept_renderer(hint_json),
                "cellClassRules": _cell_rules("부서", readonly=_IS_PROTECTED_JS)},
        "조": {"width": 130, "minWidth": 96, "cellClass": "md-c-left ms-cell-select",
              "editable": _EDIT_UNLESS_PROTECTED,
              "cellEditor": "agSelectCellEditor",
              "cellEditorParams": _team_editor_params(teams_json),
              "cellClassRules": _cell_rules("조", readonly=_IS_PROTECTED_JS)},
        "직급": {"width": 96, "minWidth": 72, "cellClass": "md-c-left",
                "editable": _EDIT_UNLESS_PROTECTED,
                "cellClassRules": _cell_rules("직급", readonly=_IS_PROTECTED_JS)},
        "권한": {"width": 100, "minWidth": 80, "cellClass": "md-c-center ms-cell-select",
                "editable": _EDIT_UNLESS_PROTECTED,
                "cellEditor": "agSelectCellEditor",
                "cellEditorParams": {"values": list(_LABEL_TO_ROLE)},
                "cellClassRules": _cell_rules("권한", readonly=_IS_PROTECTED_JS)},
        "표시순서": {"width": 92, "minWidth": 72, "maxWidth": 120, "cellClass": "md-c-center ms-num",
                 "editable": _EDIT_UNLESS_PROTECTED,
                 "cellClassRules": _cell_rules("표시순서", readonly=_IS_PROTECTED_JS)},
        "재직": {"width": 74, "minWidth": 64, "cellClass": "md-c-center",
                "editable": _EDIT_UNLESS_PROTECTED,
                "cellClassRules": _cell_rules("재직", readonly=_IS_PROTECTED_JS)},
    }
    nrows = len(state.get_rows()) if state.get_rows() is not None else 0
    # 보호행 어포던스: 상태색을 덮지 않는 ms-row-protected 를 기본 cascade 위에 겹친다.
    row_rules = {**master_row_class_rules(), "ms-row-protected": _IS_PROTECTED_JS}
    return MasterGridSpec(
        page_id=PAGE_ID, columns=_GRID_COLUMNS, order=_USER_COLS, col_config=col_config,
        select_all=True, height=master_grid_height(nrows), row_class_rules=row_rules,
    )


def _dept_option_values(state: DraftState) -> list:
    depts = db.get_departments()
    dept_names = {str(r["dept_code"]): str(r["dept_name"]) for _, r in depts.iterrows()}
    return list(_dept_labels(dept_names).values())


def _render_summary_chips(rows: pd.DataFrame) -> None:
    if rows is None or rows.empty:
        return
    existing = rows[rows["_row_state"] == "existing"]
    if existing.empty:
        return
    active = int(existing["재직"].map(grid_bool).sum())
    retired = len(existing) - active
    chips = chip_html(f"재직 {active}", "ok")
    if retired:
        chips += chip_html(f"퇴직 {retired}", "mute")
    st.markdown(
        f"<div style='display:flex;justify-content:flex-end;gap:.3rem;margin:.1rem 0 .2rem'>{chips}</div>",
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
