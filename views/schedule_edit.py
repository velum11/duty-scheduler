"""근무표 관리 — 근무표 편성 화면 (사번 중심 입력, 1차 기능 기반).

전체 사용자를 자동 나열하지 않는다. 저장된 해당 월 근무표가 있으면 그 직원 행만,
없으면 신규 입력 행 1개만 표시하고, 필요한 직원은 [행 추가]나 Excel 붙여넣기로
사번을 입력한다. 사번을 입력하면 성명·부서·조를 사용자 기준정보에서 자동 조회해
채우고, 부서·조는 이 화면에서 편성값으로만 수정한다(users 기준정보는 변경하지 않음).

행 표시·정렬 축(2026-08-13 사용자 확정):
  - 행은 조직관리 **대분류·중분류**(departments.major_category/minor_category, migration
    009)를 함께 보여준다. 중분류는 부서와 1:1 이 아니므로(예: PET생산1팀·PET생산2팀 →
    중분류 'PET생산팀') 저장 계약의 원천은 종전대로 '부서' 열이다 — 대분류·중분류는
    부서에서 파생한 읽기 전용 표시이며 저장 payload 에 실리지 않는다.
  - 조회 조건의 '부서'는 대분류 단위다(해당 월 편성에 존재하는 대분류에서 유도).
  - 정렬은 ① 대분류(대분류 내 부서 최소 표시순서, 미분류 마지막) ② 조(A조→B조→C조→
    비표준 표기→빈 조) ③ 부서그룹 순서 ④ 표시순서(display_order, 미지정 뒤) ⑤ 사번.
    이 화면 로컬 규칙이며 modules/db.py 의 공용 정렬(sort_users_for_display)을 쓰지 않는다.

근태 등록 대상 부서 필터(2026-08-14 사용자 지시 — "근태에서는 해당 조직만 목록이나 조회"):
  - 조회 조건 '부서'(대분류) 선택지·'조' 선택지·그리드 행을 모두 근태 등록 대상 부서
    (departments.tracks_attendance)로 좁힌다. 판정 원천은 db.attendance_dept_codes()
    하나이며 이 화면에 부서 목록을 복제하지 않는다.
  - db.attendance_flag_ready() 가 False 면(지정 스키마 미적용 배포) 필터를 걸지 않는다 —
    플래그를 모른다고 근무표를 통째로 비우지 않는 의도적 fail-open(파사드와 같은 방향).
  - 비대상 부서로 저장된 기존 편성 행은 목록에서 빼되 '제외 N명'을 알림 슬롯에 남긴다.
    조용히 사라지면 근무가 지워진 것으로 읽히기 때문이며, 저장된 근무는 그대로 있다.

행 상태 계약(_row_id/_row_state/_sel — views/workspace.selectable_master_grid):
  - 기존 행: 첫 열 선택 체크박스 → [행 삭제]로 저장 시 삭제 예정 지정(취소 가능)
  - 신규 행: 첫 열 − 버튼 → 즉시 개별 제거 (DB 작업 없음)
  - 첫 열 드래그 핸들: 행 순서 변경(rowDragManaged). 확정 순서는 [저장] 시
    users.display_order 로 영속화한다(부서그룹 단위 슬롯 재배정 — _persist_row_order).
    1차 정렬축이 대분류·조라서 그 경계를 넘는 이동은 재조회에서 복원된다(같은
    대분류·조 안에서의 이동만 왕복한다).

날짜 셀은 work_types 약칭으로 표시·입력하고 저장 시 내부 코드로 변환한다.
[저장]은 변경된 셀만 upsert 하며, 빈 셀로 기존 근무를 자동 삭제하지 않는다
(CLAUDE.md §5 — 삭제는 [행 삭제] → 저장의 명시적 흐름으로만).

부서·조 편성값의 영구 저장(schedule_assignments 스냅샷)은 migration 002 미적용 +
근무조 필수 계약(validators) 때문에 이번 단계에서는 수행하지 않는다 — 화면 편집·
검증까지만 지원하고 저장 시 안내한다.

dirty tracking: 원본 스냅샷과 현재 편집 상태를 정규화 비교해 판단하며, dirty 상태에서
사이드바 이동·로그아웃(modules/ui.request_nav 가드)·조회 조건 변경 시 확인을 거친다.
"""
# DESIGN.md §0 화면 유형 규약 — 매트릭스 편집형.
SCREEN_ARCHETYPE = "MATRIX_EDIT"

import calendar
import json
from datetime import date
from html import escape

import pandas as pd
import streamlit as st
from st_aggrid import JsCode

from modules import db, ui
from views.common import erp
from views.common import scaffold
from views.workspace import (
    DAY_COL_MAX_PX,
    DAY_COL_MIN_PX,
    compact_hidden_meta,
    duty_legend_html,
    grid_bool,
    identity_col_config,
    month_grid_height,
    mount_viewport_probe,
    selectable_master_grid,
    set_flash,
    show_flash,
    viewport_state,
)

_MAJOR = "대분류"
_MINOR = "중분류"
# 신원·소속 열. 대분류·중분류는 부서에서 파생한 **읽기 전용 표시**지만 반드시 이 목록에
# 있어야 한다 — 그리드는 order + META 컬럼만 왕복하므로(views/workspace.selectable_master_grid)
# 목록에 없는 열은 편집 왕복에서 값이 사라진다(과거 P1 사고 유형).
_FIXED = ["사번", "성명", _MAJOR, _MINOR, "부서", "조"]
#: 파생 표시 열 — 편집 불가, dirty 비교·저장 payload 에서 제외한다.
_DERIVED = (_MAJOR, _MINOR)
_ALL = "(전체)"  # 부서·조 '전체' 센티널(workspace.ALL 과 동일 값). 전체 조회 시 다부서/조 표시.
#: 조회 조건 '부서'가 대분류가 아니라 특정 부서로 잠긴 경우(MANAGER)의 값 접두사.
#: 대분류 이름과 값 공간이 섞이지 않게 접두사로 구분한다.
_DEPT_SCOPE = "dept:"
#: 대분류가 비어 있는 부서의 표시 라벨(감추지 않고 드러내 조직관리에서 채우게 한다).
_UNCLASSIFIED = "미분류"
#: 조회 조건에서 제외할 대분류(대시보드 _EXCLUDED_MAJORS 와 같은 사용자 지정 규칙).
#: 데이터·다른 화면은 건드리지 않고 이 화면 필터 선택지에서만 감춘다.
#: 근태 등록 대상 지정(tracks_attendance)이 동작하는 환경에서는 이 이름 기반 규칙을
#: **적용하지 않는다** — 어느 조직이 근태 대상인지는 조직 관리에서 명시 지정한 값이
#: 답이고, 그 위에 화면이 대분류 이름으로 한 번 더 감추면 사용자가 지정한 부서가
#: 필터에서 사라진다(행에는 나오는데 좁힐 수는 없는 상태). 지정 기능을 쓸 수 없는
#: 폴백에서만 종전 규칙을 그대로 유지한다.
_EXCLUDED_MAJORS = ("관리",)
_TAIL_ORDER = 10 ** 6  # 기준정보에 없는 부서·대분류의 정렬 자리(항상 뒤)
_META = ["_row_id", "_row_state", "_sel"]

# 기존 행의 사번은 읽기 전용(관계키). 신규 행에서만 편집한다.
_EMP_EDITABLE = JsCode("function(p){ return p.data && p.data._row_state !== 'existing'; }")

# ── §2 팔레트 (팔레트 밖 색 금지 §0-8) ──
_INK = "#1c1a17"
_INK2 = "#4a453d"
# Codex P1: _WEAK(.se-ctx .op 운영단위 라벨)·_FAINT(.se-legend .lab 모노 오버라인)는 읽는
# 텍스트라 #6b665d(5.1:1↑)로 상향 — #8b857c·#a09a90 은 읽는 텍스트 금지.
_WEAK = "#6b665d"
_FAINT = "#6b665d"
_LINE = "#e6e2da"
_LINE_HDR = "#cfc8bd"
_LINE_SEC = "#e0dbd2"
_ACCENT = "#c2410c"
_ACCENT_TEXT = "#b4451a"

# §1-C 그리드 컨테이너 리스킨 — AG Grid iframe 바깥 래퍼에 흰 배경·헤어라인·radius 를 입힌다
# (내부 헤더/셀 헤어라인은 공용 _MASTER_GRID_CSS 의 #CFC8BB 계열이 §2 와 정합). 셀 색은
# 근무형태 DB hex(day_style JsCode). sticky 4열은 AG Grid pinned(신원 4열+선택열)로 확보.
_ROSTER_CSS = f"""
<style>
.st-key-se_gridwrap div[data-testid="stAgGrid"] {{
  border-radius:8px; overflow:hidden; border:1px solid {_LINE_HDR}; background:#ffffff;
}}
.se-hint {{ display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin:2px 0 8px; }}
.se-hint .lab {{ font-size:12px; color:{_INK2}; margin-right:2px; }}
.se-key {{ display:inline-flex; align-items:center; gap:6px; padding:3px 10px; border-radius:7px;
  border:1px solid {_LINE}; background:#ffffff; font-size:12px; color:{_INK}; white-space:nowrap; }}
/* 모노 서체 폐지(DESIGN.md §1.2) — 세로로 겹쳐 읽는 수치는 tabular-nums 로 자릿수를
   맞춘다. 크기도 네 단계(24·20·14·12) 안으로 내렸다(종전 12.5px). */
.se-key .n {{ font-variant-numeric:tabular-nums; font-weight:600; color:{_ACCENT_TEXT}; }}
.se-key .sw {{ width:9px; height:9px; border-radius:2px; flex:0 0 auto; }}
.se-ctx {{ display:flex; flex-wrap:wrap; align-items:center; gap:6px 16px; margin:6px 0 10px;
  font-size:12px; color:{_INK2}; }}
.se-ctx .loc {{ font-weight:600; color:{_INK}; }}
.se-ctx .num {{ font-variant-numeric:tabular-nums; font-weight:600; color:{_INK}; }}
.se-ctx .op {{ color:{_WEAK}; }}
/* 범위 안내 1줄(알림 슬롯 전용) — 근태 비대상 부서 편성을 목록에서 뺐다는 사실과 건수.
   경고가 아니라 사실 고지라 중립 잉크로 두고 숫자만 모노로 세운다(§0.6 한 줄). */
.se-note {{ font-size:12px; color:{_INK2}; margin:2px 0 6px; }}
.se-note .num {{ font-variant-numeric:tabular-nums; font-weight:600; color:{_INK}; }}
/* 모바일 세로 한 줄 안내(가로 전환 제안) — 월간 근무표 .sv-rotate 와 같은 문구·크기·색. */
.se-rotate {{ font-size:12px; color:{_WEAK}; margin:8px 0 6px; line-height:1.35; }}
/* (근무형태 범례는 3화면 공통 views.workspace.duty_legend_html 이 마크업·CSS 를 소유한다 —
   종전 .se-legend/.se-leg 는 월간 근무표의 색 pill 범례와 시각 언어가 갈렸다.) */
/* 뷰포트 프로브(views.workspace.mount_viewport_probe) — 값만 읽는 0크기 요소라 흐름에서
   뺀다(월간 근무표 _SV_CSS 의 같은 규칙과 동일 값). */
.st-key-sv_vp {{ position:absolute; width:0; height:0; overflow:hidden; }}
/* 미저장 변경 표시 — 0건은 '알릴 것 없음'이라 중립(ink-2·normal), 1건 이상일 때만
   액센트+굵게로 주의를 끈다. 종전엔 0건도 오렌지 굵게라 상시 경고처럼 읽혔다. */
.se-dirty {{ text-align:right; color:{_INK2}; font-size:12px; font-weight:400; margin-top:6px; }}
.se-dirty.on {{ color:{_ACCENT_TEXT}; font-weight:600; }}
</style>
"""


# '조'(근무조) 열 입력 안내 — 자유 입력 + 한 글자 자동 보정 규칙(normalize_shift_group)을
# 헤더 툴팁 1줄로만 노출한다. 문구는 이 상수 한 곳이 원천이다.
_SHIFT_HINT = "직접 입력 · 한 글자만 쓰면 저장 시 '조'가 붙습니다 (A → A조)"
# (빈 셀 placeholder 렌더러는 폐기 — 복사 시 placeholder 문구가 실데이터로 붙여넣어질 수
#  있어(code-review P2) 헤더 툴팁·하단 힌트 줄만 남긴다.)


# ---------- 조직 계층(대분류·중분류) 파생 ----------
def _clean(value) -> str:
    """pandas NA-safe 문자열 정규화 — None/NaN/pd.NA → ''(폴백), 그 외 str.strip()."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass  # 배열·비스칼라 등 isna 판정 불가 값은 그대로 문자열화
    return str(value).strip()


def _order_of(value) -> int:
    """표시순서 숫자화(해석 불가는 뒤로) — 조직 관리 시트의 '순서' 열을 그대로 따른다."""
    num = pd.to_numeric(value, errors="coerce")
    return _TAIL_ORDER if pd.isna(num) else int(num)


def _dept_catalog() -> dict:
    """부서 기준정보 색인 — 대분류·중분류·부서명 해석과 대분류 정렬순서의 단일 출처.

    반환 키::

        org_of      dept_code -> (대분류, 중분류)
        major_order 대분류 -> 그 대분류에 속한 부서의 **최소 표시순서**(정렬 기준)
        name_codes  부서명 -> {dept_code}  (동명 부서가 있으면 원소가 2 이상)
        codes       유효 dept_code 집합

    비활성 부서도 넣는다 — 그 부서로 저장된 과거 편성이 남아 있으면 계층을 해석해
    제자리에 보여야 한다(표시를 조용히 버리지 않는다).
    """
    org = db.get_org_departments()
    org_of: dict = {}
    major_order: dict = {}
    name_codes: dict = {}
    codes: set = set()
    if org is None or org.empty:
        return {"org_of": org_of, "major_order": major_order,
                "name_codes": name_codes, "codes": codes}
    for _, row in org.iterrows():
        code = _clean(row.get("dept_code"))
        if not code:
            continue
        codes.add(code)
        major = _clean(row.get("major_category"))
        org_of[code] = (major, _clean(row.get("minor_category")))
        name = _clean(row.get("dept_name"))
        if name:
            name_codes.setdefault(name, set()).add(code)
        if major:
            order = _order_of(row.get("sort_order"))
            major_order[major] = min(major_order.get(major, _TAIL_ORDER), order)
    return {"org_of": org_of, "major_order": major_order,
            "name_codes": name_codes, "codes": codes}


def _org_labels(dept_code: str, catalog: dict) -> tuple[str, str]:
    """dept_code → (대분류 표시, 중분류 표시). 대분류가 비면 '미분류', 중분류는 빈 칸.

    중분류에 부서명을 대신 채우지 않는다 — 이 화면은 '부서' 열을 따로 보여주므로
    없는 분류를 있는 것처럼 만들면 조직관리 입력 누락이 가려진다.
    """
    code = _clean(dept_code)
    if not code:
        return "", ""
    major, minor = catalog["org_of"].get(code, ("", ""))
    return (major or _UNCLASSIFIED), minor


def _dept_code_of_text(text: str, catalog: dict) -> str:
    """'부서' 셀 입력(부서코드 또는 부서명) → dept_code. 미해석·동명 모호는 ''.

    저장 경로(_save)의 부서 해석 규칙과 같은 기준을 쓴다 — 표시(대분류·중분류)와
    저장이 서로 다른 부서를 가리키지 않게 하기 위해서다.
    """
    value = _clean(text)
    if not value:
        return ""
    if value in catalog["codes"]:
        return value
    matched = catalog["name_codes"].get(value, set())
    return next(iter(matched)) if len(matched) == 1 else ""


def _month_assignments(year: int, month: int):
    """대상 월의 전체 편성 스냅샷(조회 조건 선택지 유도용). 테이블이 없으면 빈 프레임."""
    try:
        frame = db.get_month_assignments(int(year), int(month))
    except Exception:
        return pd.DataFrame(columns=["emp_no", "dept_code", "shift_group_code"])
    if frame is None:
        return pd.DataFrame(columns=["emp_no", "dept_code", "shift_group_code"])
    return frame


def _in_scope(token: str, dept_code: str, catalog: dict) -> bool:
    """조회 조건 '부서' 토큰이 이 부서를 포함하는가 (순수).

    토큰은 세 가지다: ``_ALL``(전체), ``dept:<code>``(MANAGER 부서 잠금), 그 밖에는
    대분류 이름. 대분류 토큰은 그 대분류에 속한 **모든 부서**를 포함한다.
    """
    scope = _clean(token)
    if not scope or scope == _ALL:
        return True
    code = _clean(dept_code)
    if scope.startswith(_DEPT_SCOPE):
        return code == scope[len(_DEPT_SCOPE):]
    return catalog["org_of"].get(code, ("", ""))[0] == scope


def _attendance_scope() -> set[str] | None:
    """근태(근무표) 등록 대상 부서코드 집합. ``None`` 이면 '필터 없음'(폴백 상태).

    - 지정 기능을 읽고 쓸 수 없는 환경(db.attendance_flag_ready() False)에서는 ``None``
      을 돌려 종전처럼 전 부서를 보여준다. 스키마 미적용의 대가가 "근무표가 통째로
      빈다"가 되면 안 된다(파사드 docstring 의 fail-open 계약과 같은 방향).
    - 비활성 부서도 포함한다(``is_active=None``). 이 화면은 그 달 편성에 남아 있는
      부서를 계층 해석해 제자리에 보여주는 계약이라(_dept_catalog), 부서를 나중에
      비활성화했다고 과거 편성 행이 사라지면 안 된다.
    - 지정된 부서가 하나도 없으면 빈 집합이다. 이때는 '아직 지정하지 않았다'가 사실
      이므로 목록을 비우고 사유를 안내한다(_scope_notice) — 임의로 전 부서를 열지 않는다.
    """
    if not db.attendance_flag_ready():
        return None
    return db.attendance_dept_codes(is_active=None)


def _tracked_dept(dept_code: str, tracked: set[str] | None) -> bool:
    """이 부서가 근태 등록 대상인가 (순수). ``tracked`` 가 None 이면 항상 True(폴백)."""
    if tracked is None:
        return True
    return _clean(dept_code) in tracked


def _major_options(year: int, month: int, catalog: dict,
                   tracked: set[str] | None = None) -> list[str]:
    """조회 조건 '부서'(대분류) 선택지 — 해당 월 편성에 실제로 존재하는 대분류만.

    부서 마스터 전체에서 뽑지 않는 이유: 이 화면은 그 달 근무표가 저장된 직원만
    표시하므로, 편성이 없는 대분류는 고르면 반드시 0건인 죽은 선택지가 된다.
    대분류가 비어 있는(미분류) 부서는 선택지를 만들지 않는다 — 이름이 아니기 때문이며,
    해당 행은 [전체 부서]에서 보이고 정렬은 마지막이다.
    순서는 대분류에 속한 부서의 최소 표시순서(조직관리 시트 순서)를 따른다.

    ``tracked`` 가 주어지면 근태 등록 대상 부서에서만 대분류를 유도한다 — 그리드 행과
    같은 기준이어야 "고르면 0건"인 선택지가 생기지 않는다.
    """
    assigns = _month_assignments(year, month)
    found: dict = {}
    if assigns is not None and not assigns.empty and "dept_code" in assigns.columns:
        for value in assigns["dept_code"]:
            code = _clean(value)
            if not _tracked_dept(code, tracked):
                continue
            major = catalog["org_of"].get(code, ("", ""))[0]
            if not major:
                continue
            # 이름 기반 제외는 지정 기능을 못 쓰는 폴백에서만 쓴다(_EXCLUDED_MAJORS 주석).
            if tracked is None and major in _EXCLUDED_MAJORS:
                continue
            found[major] = catalog["major_order"].get(major, _TAIL_ORDER)
    return [name for name, _order in sorted(found.items(), key=lambda kv: (kv[1], kv[0]))]


def _shift_rank(value: str) -> tuple:
    """조 정렬·선택지 순서 (순수) — A조→B조→C조 → 비표준 표기 → 빈 조.

    'A조'처럼 normalize_shift_group 의 표준형(한 글자 + '조')을 먼저 놓고, '원료실'
    처럼 표준형이 아닌 실데이터 값은 감추지 않고 그 뒤에 붙인다.
    """
    text = _clean(value)
    if not text:
        return (2, "")
    if len(text) == 2 and text.endswith("조") and text[0].isalnum():
        return (0, text)
    return (1, text)


def _shift_options(year: int, month: int, catalog: dict, scope: str,
                   tracked: set[str] | None = None) -> list[str]:
    """조회 조건 '조' 선택지 — 해당 월·선택 대분류 범위의 편성에 실제로 있는 근무조.

    조는 기준정보 축이 아니라 편성표 자유 입력(shift_group_code)이므로 선택지도
    스냅샷에서만 유도한다. 표기 흔들림('A' 등)은 normalize_shift_group 으로 접는다.
    부서 축과 같은 근태 대상 필터(``tracked``)를 적용한다 — 비대상 부서에만 있는 조가
    선택지에 남으면 고르는 순간 0건이 된다.
    """
    assigns = _month_assignments(year, month)
    values: set = set()
    if assigns is not None and not assigns.empty and "shift_group_code" in assigns.columns:
        for _, row in assigns.iterrows():
            dept_code = _clean(row.get("dept_code"))
            if not _tracked_dept(dept_code, tracked):
                continue
            if not _in_scope(scope, dept_code, catalog):
                continue
            code = normalize_shift_group(row.get("shift_group_code"))
            if code:
                values.add(code)
    return sorted(values, key=_shift_rank)


def _scope_label(token: str, dept_names: dict) -> str:
    """조회 조건 '부서' 토큰의 표시 라벨(컨텍스트 줄·선택지 공용)."""
    scope = _clean(token)
    if not scope or scope == _ALL:
        return "전체 부서"
    if scope.startswith(_DEPT_SCOPE):
        code = scope[len(_DEPT_SCOPE):]
        return dept_names.get(code, code)
    return scope


def _scope_notice(manager_dept: str, tracked: set[str] | None) -> None:
    """근태 대상 범위 안내 — **알림 슬롯(se_notice) 안에서만** 호출한다.

    본문 최상위에 조건부 요소를 새로 두면 저장 직후 그리드 높이만큼 빈 블록이 남는
    회귀가 재발한다(se_notice 주석 참조). 여기서 그리는 것은 세 가지다.

    1. 지정된 부서가 하나도 없음 → 화면이 빈 이유와 다음 행동(조직 관리에서 지정).
    2. MANAGER 소속 부서가 비대상 → 잠긴 범위가 통째로 비는 이유. 잠금 자체는 풀지
       않는다(푸는 순간 전체가 열려 fail-open 이 된다).
    3. 비대상 부서 편성을 목록에서 뺐음 → 제외 인원수와 부서. "근무가 지워졌다"로
       읽히지 않게 저장된 근무가 남아 있다는 사실을 함께 적는다.
    폴백(tracked None)에서는 아무것도 그리지 않는다 — 적용되지 않은 규칙을 안내하면
    사용자가 지정이 걸린 줄 안다.
    """
    if tracked is None:
        return
    if not tracked:
        st.warning(
            "근태 등록 대상으로 지정된 부서가 없습니다. "
            "조직 관리에서 근태 등록 대상 부서를 지정하면 이 화면에 편성 대상이 나타납니다."
        )
    elif manager_dept and manager_dept not in tracked:
        st.warning(
            f"소속 부서({db.dept_name(manager_dept)})는 근태 등록 대상이 아닙니다. "
            "조직 관리에서 근태 등록 대상으로 지정해야 이 화면에서 편성할 수 있습니다."
        )
    hidden = st.session_state.get("se_untracked") or {}
    count = int(hidden.get("count") or 0)
    if not count:
        return
    names = [n for n in hidden.get("depts", []) if n]
    shown = ", ".join(names[:3]) + (f" 외 {len(names) - 3}개" if len(names) > 3 else "")
    where = f" · {escape(shown)}" if shown else ""
    st.markdown(
        "<div class='se-note'>근태 등록 대상이 아닌 부서의 편성 "
        f"<span class='num'>{count}</span>명은 목록에서 제외했습니다{where} — "
        "저장된 근무는 그대로 남아 있습니다.</div>",
        unsafe_allow_html=True,
    )


# ── 헤더 아이콘 따라잡기(기준정보 3화면과 같은 보정) ─────────────────────────────
#: 직전 run 에 발행한 헤더 상태 거울 / 연속 보정 횟수 가드.
_HDR_MIRROR = "se_hdr_mirror"
_HDR_GUARD = "se_hdr_sync_n"


def _sync_header(states: dict) -> None:
    """헤더 아이콘 발행값이 바뀐 run 에서만 1회 재실행해 상단 아이콘을 따라오게 한다.

    앱 셸(modules/ui)은 본문보다 **먼저** 헤더를 그리므로, 이 화면이 render 말미에
    ``publish_header_actions`` 로 발행한 활성/사유는 **다음 run 부터** 헤더에 반영된다.
    본문 액션 버튼을 없애고 헤더가 유일한 진입점이 된 뒤로 이 지연은 실동작 결함이다.

    특히 [추가]는 미발행 기본값이 음영(``ui._HDR_DEFAULT_DISABLED``)이라, 화면에 들어와
    아무것도 만지지 않으면 발행값을 반영할 rerun 자체가 생기지 않아 **+ 아이콘이 계속
    음영**으로 남는다(2026-08-14 "행 추가 먹통" 신고의 실측 원인 — 진입 직후 + 는 눌리지
    않고, 셀을 한 번 편집해 rerun 이 나면 그때부터 활성이 되는 것으로 재현했다).
    발행값이 직전 run 과 다르면 즉시 재실행하고, 같은 값이면 멈춘다. 폭주 방지로 연속
    보정은 2회로 제한한다(정상 경로에서는 상태 전이당 1회).
    """
    payload = {str(k): (bool(v[0]), v[1]) for k, v in dict(states).items()}
    if st.session_state.get(_HDR_MIRROR) == payload:
        st.session_state[_HDR_GUARD] = 0
        return
    st.session_state[_HDR_MIRROR] = payload
    tries = int(st.session_state.get(_HDR_GUARD) or 0)
    if tries < 2:
        st.session_state[_HDR_GUARD] = tries + 1
        st.rerun()


def _active_ordered() -> list[tuple[str, str, str]]:
    """활성 근무형태를 sort_order 순으로 (code, short_label, color) 리스트로 반환(도메인 파생)."""
    wt = db.get_work_types()
    act = wt[wt["is_active"]] if wt is not None and not wt.empty else wt
    if act is None or act.empty:
        return []
    if "sort_order" in act.columns:
        act = act.sort_values("sort_order", kind="stable")
    out = []
    for _, r in act.iterrows():
        code = str(r["code"]).strip()
        if not code:
            continue
        sl = str(r.get("short_label") or "").strip() or code
        color = str(r.get("color") or "").strip()
        out.append((code, sl, color))
    return out


def _day_cell_handlers(cycle_labels: list[str], number_labels: list[str]) -> dict:
    """day 컬럼 셀 상호작용 JsCode(§1-C, 도메인 파생) — 클릭 순환은 제거(사용자 피드백):
    셀 편집은 더블클릭 편집기·직접 타이핑(이전 방식)으로 하고, 숫자키 1..N=N번째 근무형태·
    0=지움, 방향키 이동은 유지한다. 값 반영은 setDataValue→cellValueChanged→기존 dirty/저장
    경로 그대로. Ctrl+V(붙여넣기)도 유지된다. (cycle_labels 는 숫자키/붙여넣기 검증용 보존.)"""
    nums = json.dumps(number_labels, ensure_ascii=False)
    # 숫자키(1..N·0)는 편집 중이 아닐 때만 근무형태 즉시 입력. 그 외 키(방향키 등)는 기본
    # 동작(이동)을 그대로 두고, 편집 시작 키·타이핑은 AG Grid 기본 편집기로 흘린다.
    suppress_kbd = JsCode(
        "function(p){"
        "  var e=p.event; if(!e)return false;"
        "  if(p.editing)return false;"
        f" var nums={nums};"
        "  var k=e.key;"
        "  if(k==='0'){ p.node.setDataValue(p.column.getColId(), ''); return true; }"
        "  if(k>='1'&&k<='9'){ var i=parseInt(k,10)-1;"
        "    if(i<nums.length){ p.node.setDataValue(p.column.getColId(), nums[i]); return true; } }"
        "  return false;"
        "}"
    )
    return {"suppressKeyboardEvent": suppress_kbd}


def _day_header_component(day_col: str) -> JsCode:
    """일자 헤더 2줄(숫자 위·요일 아래) headerComponent. day_col 형식 'D(요일)'."""
    num = day_col.split("(")[0].strip()
    wd = day_col.split("(")[1].rstrip(")") if "(" in day_col else ""
    num_j = json.dumps(num)
    wd_j = json.dumps(wd)
    # 두 줄 모두 12px Pretendard (DESIGN.md §1.2 네 단계 안 · 모노 폐지). 숫자 줄은
    # label-strong(600/ink) + tabular-nums 로 날짜가 세로로 정렬되고, 요일 줄은 label
    # (400/ink-3)이다. 종전 12.5px 모노 + 10px 는 둘 다 스케일 밖이었다(2026-08-19).
    return JsCode(
        "class{init(p){this.eGui=document.createElement('div');"
        "this.eGui.style.cssText='line-height:1.15;text-align:center';"
        f"this.eGui.innerHTML=\"<div style='font-weight:600;font-variant-numeric:tabular-nums;"
        f"font-size:12px;color:{_INK}'>\"+{num_j}+\"</div><div style='font-size:12px;font-weight:400;"
        f"color:{_WEAK}'>\"+{wd_j}+\"</div>\";}}getGui(){{return this.eGui;}}}}"
    )


#: 일자 열 폭 하한/상한(px) — 월간 근무표와 **같은 값**을 쓴다(근무표 3화면 공통 토큰,
#: views.workspace.DAY_COL_MIN_PX/MAX_PX). 종전에는 편성 44~56 / 월간 40~52 로 같은 성격
#: 열의 밀도가 화면마다 달랐다(2026-08-14 검수).
#: 상한은 밀도 보호선이다: 표시 축이 명칭으로 바뀌면서 '특근(주간)'·'경조(자녀결혼)'
#: 처럼 긴 값이 생겼는데, 그 최댓값에 열을 맞추면 31일 매트릭스가 3천 px 를 넘겨 한
#: 화면에서 볼 수 있는 날짜가 반토막 난다. 상한을 넘는 값은 셀에서 말줄임되고 전체
#: 문자열은 셀 tooltip(enableBrowserTooltips)과 하단 범례가 보증한다.
_DAY_W_MIN, _DAY_W_MAX = DAY_COL_MIN_PX, DAY_COL_MAX_PX


#: 표 셀 12px Pretendard 의 실측 자폭(px/자) — 한글, 그 외(숫자·ASCII).
#: 폭 역산의 단일 출처이며 파이썬(_label_px)과 JsCode(day_style) 양쪽이 같은 값을 쓴다.
_CH_KO_PX, _CH_ASCII_PX = 11.04, 7.2
#: 셀 좌우 패딩 합(px) — 필요폭 = max(값, 헤더) + 이 값 → 4의 배수 올림.
_CELL_PAD_PX = 16


def _label_px(text: str) -> float:
    """표시값의 대략 렌더 폭(px, 표 셀 12px Pretendard 기준) — 실측 자폭 계수로 합산.

    종전 계수(14.5/8.0)는 폐지된 IBM Plex 14.5px 기준이라 12px 표에서 폭을 20% 과대
    계산했다(DESIGN.md §1.2 — 글꼴 Pretendard 하나, 표 셀·헤더 12px).
    """
    return sum(_CH_KO_PX if ord(ch) > 0x1100 else _CH_ASCII_PX for ch in str(text))


def _day_width(labels) -> int:
    """일자 열 폭 — 실제 표시값(도메인 파생)에서 유도하되 §밀도 상한을 지킨다 (순수).

    하드코딩한 고정 폭이 아니라 활성 근무형태의 표시값에서 계산한다: 약칭처럼 짧은
    값만 쓰는 환경에서는 하한 그대로이고, 명칭이 길어진 만큼만 넓어진다. 산식은 신원 열과
    같다 — ``max(값 최대 렌더폭, 헤더) + 16`` 을 4의 배수로 올린 뒤 [하한, 상한] 으로 자른다.
    일자 헤더는 숫자 2자(14.4)라 값이 언제나 헤더보다 넓다.
    """
    longest = max((_label_px(label) for label in labels if str(label).strip()), default=0.0)
    need = -(-int(longest + _CELL_PAD_PX + 0.999) // 4) * 4  # 4의 배수 올림
    return int(max(_DAY_W_MIN, min(_DAY_W_MAX, need)))


def _hint_html(number_labels: list[str], colors: dict) -> str:
    """입력 단축키 안내 라인 — [1 주][2 야]… 실제 활성 근무형태에서 파생(도메인). 색 스와치 포함."""
    keys = []
    for i, lab in enumerate(number_labels[:9], start=1):
        c = colors.get(lab, "")
        sw = f"<span class='sw' style='background:{c}'></span>" if c.startswith("#") else ""
        keys.append(f"<span class='se-key'><span class='n'>{i}</span>{sw}{escape(lab)}</span>")
    return ("<div class='se-hint'><span class='lab'>입력 단축키</span>"
            + "".join(keys)
            + "<span class='se-key'><span class='n'>0</span>지움</span></div>")


def _context_html(q: dict, dept_name: str, team_name: str,
                  n_people: int, filled: int, empty: int) -> str:
    """컨텍스트 라인 — YYYY-MM · 부서 · 조 + 인원/입력/미입력 모노 수치 + 조작 안내."""
    ym = f"{q['year']}-{q['month']:02d}"
    return (
        "<div class='se-ctx'>"
        f"<span class='loc'>{escape(ym)}</span><span>·</span>"
        f"<span class='loc'>{escape(dept_name)}</span><span>·</span>"
        f"<span class='loc'>{escape(team_name)}</span>"
        f"<span>인원 <span class='num'>{n_people}</span></span>"
        f"<span>입력 <span class='num'>{filled}</span></span>"
        f"<span>미입력 <span class='num'>{empty}</span></span>"
        f"<span class='op'>더블클릭 편집 · 숫자키 1~9·0 입력 · 방향키 이동 · Ctrl+V 붙여넣기"
        f" · 조 열 직접 입력(A → A조) · 행 앞 핸들 드래그로 순서 변경</span></div>"
    )


def _legend_html(active: list[tuple[str, str, str]]) -> str:
    """하단 범례 — 활성 근무형태 색·표시값(도메인 파생).

    마크업·CSS 는 근무표 3화면 공통(:func:`views.workspace.duty_legend_html`)이다.
    """
    return duty_legend_html([(sl, color) for _code, sl, color in active])


def _visible_emp_order(rows: pd.DataFrame) -> list[str]:
    """화면에 보이는 행의 사번 시퀀스 (빈 행·중복 제외, 순수) — 행 순서 영속의 입력."""
    out: list[str] = []
    seen: set[str] = set()
    if rows is None or rows.empty or "사번" not in rows.columns:
        return out
    for value in rows["사번"]:
        emp = "" if pd.isna(value) else str(value).strip()
        if not emp or emp in seen:
            continue
        seen.add(emp)
        out.append(emp)
    return out


def _order_moved(base: list, final: list) -> bool:
    """행을 서로 **맞바꿨는가** (순수) — 추가·삭제로 인한 시퀀스 차이는 제외한다.

    양쪽에 공통으로 있는 사번만 남겨 비교하므로, 행 삭제(이미 '삭제 N건'으로 세는 변경)나
    신규 행 추가가 '순서 변경'으로 중복 계상되지 않는다. 영속 판정(_persist_row_order)은
    이보다 넓은 기준(시퀀스 자체가 다르면 재배정)을 쓴다 — 새로 들어온 직원에게도 슬롯을
    줘야 하기 때문이며, 그쪽은 값이 안 바뀌면 어차피 쓰지 않는다.
    """
    base_set, final_set = set(base), set(final)
    return [e for e in base if e in final_set] != [e for e in final if e in base_set]


def _change_count(live: pd.DataFrame, day_cols: list, orig_cells: dict, n_del: int,
                  order_changed: bool = False) -> int:
    """미저장 변경 건수 — 기존 행 셀 변경 + 신규 행 입력 셀 + 삭제 예정 행 + 행 순서 변경.
    dirty 판정과 별개 표시용 카운트(셀 클릭 순환/숫자키 입력마다 증가해 자가검증 근거가 된다).

    행 순서 변경은 셀 값이 하나도 안 바뀌므로 위 항목으로는 잡히지 않는다 — 드래그만 한
    상태에서 '미저장 변경 0건'인데 [저장]이 활성인 모순을 막기 위해 1건으로 센다
    (몇 칸을 옮겼든 '순서 변경'이라는 한 가지 변경으로 읽는 편이 정확하다)."""
    cnt = int(n_del) + (1 if order_changed else 0)
    if live is None or live.empty or not day_cols:
        return cnt
    for _, r in live.iterrows():
        rid = str(r.get("_row_id"))
        is_existing = str(r.get("_row_state")) == "existing"
        for c in day_cols:
            now = "" if pd.isna(r.get(c)) else str(r.get(c)).strip()
            if is_existing:
                if now != orig_cells.get((rid, c), ""):
                    cnt += 1
            elif now:
                cnt += 1
    return cnt


# ---------- 진입점 ----------
def render(user: dict) -> None:
    # 크롬은 키트로 통일(screen_frame). 필터 select 만 condition_panel 로 이관했고
    # (widget_key=se_y/se_m/se_d/se_t 로 revert 키 계약 유지), 새로고침은 클릭소실
    # 회피(on_click 플래그) 그대로 패널 밖 별도 버튼이다. 편집 버튼·MATRIX 그리드·
    # 저장/dirty/이탈가드는 계약상 이번엔 건드리지 않는다 — top_action_bar·MATRIX
    # 어댑터 추출은 BACKLOG.
    # §1-C 스프레드시트 입력형(구조 교체) — 파랑 아이콘 밴드 제거(§0-3). 액션은 1행(필터 우측)
    # 으로 이전하고 셀 입력은 클릭 순환 + 숫자키(도메인 파생). 저장/dirty/검증/이탈가드/편성
    # 스냅샷 계약은 전부 불변(표현 계층만 교체).
    # CSS 주입은 **크롬 뒤**에 둔다 — 앞에 두면 빈 마크다운 블록 하나가 제목 위에 생겨
    # 세로 블록 gap(9.1px)만큼 이 화면만 아래로 밀렸다(2026-08-14 실측: 제목 top 편성
    # 115 / 월간 105.9). 화면 간 제목 기준선을 맞추려면 크롬이 첫 블록이어야 한다.
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="근무표 편성",
        desc="부서와 조를 선택하여 월별 근무표를 관리합니다.",
        breadcrumb="근무표 › 근무표 편성",
        badges=scaffold.mode_badge(),
    )
    st.markdown(_ROSTER_CSS, unsafe_allow_html=True)

    # 화면 폭/방향 — 좁은 폭에서 표시 신원 열·표 높이를 정한다(월간 근무표와 같은 규칙·
    # 같은 프로브). 프로브 마운트는 본문 마지막이고 여기서는 세션 값을 읽기만 한다.
    vp = viewport_state("schedule_edit")
    compact = bool(vp.get("compact"))
    landscape = bool(vp.get("landscape"))

    depts = db.get_departments()
    today = date.today()

    active_depts = depts[depts["is_active"]].sort_values("sort_order")
    dept_names = {r["dept_code"]: r["dept_name"] for _, r in active_depts.iterrows()}
    if not dept_names:
        ui.empty_state("등록된 부서가 없습니다. 먼저 기준정보에서 부서를 등록하세요.", head="월별 근무표")
        return

    manager_locked = user["role"] == "MANAGER" and user.get("dept_code") in dept_names
    years = list(range(today.year - 1, today.year + 2))

    # [계속 편집]으로 조회 조건 변경을 취소한 경우 — 위젯 값을 이전 조건으로 되돌린다.
    q_prev = st.session_state.get("q_schedule_edit")
    if st.session_state.pop("se_revert", False) and q_prev:
        st.session_state["se_y"] = q_prev["year"]
        st.session_state["se_m"] = q_prev["month"]
        st.session_state["se_d"] = q_prev["dept"]
        st.session_state["se_t"] = q_prev["team"]
    elif q_prev and "se_y" not in st.session_state:
        # 다른 화면을 다녀오면 Streamlit 이 위젯 상태를 지운다 — 마지막 조회 조건으로
        # 복원해 조건이 기본값으로 리셋되며 가짜 '조건 변경'이 생기는 것을 막는다.
        st.session_state["se_y"] = q_prev["year"]
        st.session_state["se_m"] = q_prev["month"]
        st.session_state["se_d"] = q_prev["dept"]
        st.session_state["se_t"] = q_prev["team"]

    # 위젯 key 를 session_state 로 관리하므로 default(index)를 함께 주지 않는다
    # (Streamlit "default value + Session State API" 경고 방지). 값은 여기서 초기화.
    st.session_state.setdefault("se_y", today.year)
    st.session_state.setdefault("se_m", today.month)
    # 부서·조 기본 = 전체(피드백 #3). MANAGER 는 아래에서 자기 부서로 잠금(fail-closed 불변).
    st.session_state.setdefault("se_d", _ALL)
    st.session_state.setdefault("se_t", _ALL)

    # 조회 조건(우측 인라인 라벨, KP-standard) — 위젯 key 는 기존 se_y/se_m/se_d/se_t 를
    # widget_key 로 그대로 지정해 revert 로직(위 67-90행)·테스트가 이름으로 참조하는
    # 세션 키를 변경 없이 유지한다(구조만 이전, views.workspace.schedule_screen 과 동일 패턴).
    #
    # '부서' 축이 개별 부서 → **대분류**로 바뀌었다(2026-08-13). 선택지는 하드코딩이
    # 아니라 해당 월 편성 스냅샷에 존재하는 대분류에서 유도한다(_major_options).
    # 선택지는 연/월에 따라 달라지므로, 위젯을 만들기 전에 세션 값이 현재 선택지 안에
    # 있는지 확인해 벗어나면 전체로 되돌린다 — 안 하면 Streamlit selectbox 가 값 없음
    # 예외를 낸다.
    catalog = _dept_catalog()
    # 근태 등록 대상 부서(조직 관리 지정) — 부서 선택지·조 선택지·행 로딩이 같은 기준을
    # 쓴다. None 이면 지정 기능을 쓸 수 없는 폴백이라 종전대로 전 부서를 대상으로 둔다.
    tracked = _attendance_scope()
    year_sel = int(st.session_state.get("se_y") or today.year)
    month_sel = int(st.session_state.get("se_m") or today.month)
    if manager_locked:
        # MANAGER 는 자기 **부서**로 잠금(fail-closed). 대분류로 넓히면 같은 대분류의
        # 다른 부서까지 열리므로 조회 범위 계약을 바꾸지 않고 부서 잠금을 유지한다.
        # 그 부서가 근태 비대상이어도 잠금을 풀지 않는다 — manager_locked 가 False 가
        # 되는 순간 조회 조건이 전체 대분류로 열려 권한 범위가 넓어진다(fail-open).
        # 대신 화면이 비는 사유를 알림 슬롯에서 밝힌다(_scope_notice).
        locked = f"{_DEPT_SCOPE}{user['dept_code']}"
        st.session_state["se_d"] = locked
        dept_field = erp.Field(
            key="d", label="부서", kind="select",
            options=[locked], format_func=lambda c: _scope_label(c, dept_names),
            disabled=True, widget_key="se_d", width=200,
        )
    else:
        dept_options = [_ALL] + _major_options(year_sel, month_sel, catalog, tracked)
        if st.session_state.get("se_d") not in dept_options:
            st.session_state["se_d"] = _ALL
        dept_field = erp.Field(
            key="d", label="부서", kind="select",
            options=dept_options, format_func=lambda c: _scope_label(c, dept_names),
            widget_key="se_d", width=200,
        )
    # 부서(대분류)→조 종속 옵션: 조 Field 를 만들기 전에 "현재" 부서 선택을 세션 상태에서
    # 읽는다(위젯 렌더 순서가 아니라 세션 상태로 종속을 해석해, 사용자가 부서를 바꾼 그
    # rerun 에서 조 옵션이 갱신되게 한다 — workspace.schedule_screen 과 동일).
    team_options = [_ALL] + _shift_options(
        year_sel, month_sel, catalog, st.session_state.get("se_d") or _ALL, tracked
    )
    if st.session_state.get("se_t") not in team_options:
        st.session_state["se_t"] = _ALL

    fields = [
        # format_func=str 명시: 키트 select 기본 포맷터(항등함수)는 int 옵션(연도)을
        # 그대로 protobuf 문자열 필드에 넣어 TypeError 를 낸다(workspace.schedule_screen 과
        # 동일 회피 — 키트 자체는 손대지 않는다). str(int) 는 기존 selectbox 표시와 동일.
        erp.Field(key="y", label="연도", kind="select", options=years, format_func=str,
                  widget_key="se_y", width=110),
        erp.Field(key="m", label="월", kind="select", options=list(range(1, 13)),
                  format_func=lambda m: f"{m}월", widget_key="se_m", width=100),
        dept_field,
        erp.Field(key="t", label="조", kind="select", options=team_options,
                  format_func=lambda c: "전체 조" if c == _ALL else str(c),
                  widget_key="se_t", width=120),
    ]
    # §0.6 컨트롤 폭 내용 맞춤 — cols=4 등폭은 연도(4자리)·월 select 까지 285px(1440 기준)
    # 로 늘려 조건 줄이 화면 폭을 삼켰다. 같은 조건(연/월/부서/조)을 쓰는 월간 근무표와
    # 동일한 content_fit 배치로 맞춘다(조회 계약·위젯 key 무변경).
    v = erp.condition_panel("se", fields, content_fit=True)
    year, month, dept, team = v["y"], v["m"], v["d"], v["t"]

    # 액션은 상단 52px 헤더 아이콘 4종(추가·새로고침·삭제·저장)이 소유한다(피드백 #1,
    # 부속서 A-5 단일 범위 화면). 페이지 본문의 4단추는 제거했고, 헤더 아이콘 클릭이 기존
    # flag(se_*_req)를 발화한다(ui._PAGE_HEADER_ACTIONS). 삭제·저장 음영은 아래에서 세션
    # (page 스코프 hdr_state — ui.publish_header_actions)로 발행해 헤더가 읽는다
    # (선택·dirty 변화는 rerun 주기 내 반영).
    # 필터 하단 헤어라인은 condition_panel(§1-E)이 소유한다.
    clicked = st.session_state.pop("se_go_req", False)
    # 저장/삭제 배너(show_flash)와 삭제 예정 패널은 **본문 최상위에 맨몸으로 두지 않는다** —
    # 아래 '알림 슬롯'(se_notice) 안에서 렌더한다. 이유는 그 주석 참조(저장 직후 공백 회귀).

    # ('조' 선택지는 항상 [전체 조]를 포함하므로 값 없음 분기는 더 이상 생기지 않는다 —
    #  종전 "선택한 부서에 등록된 조/팀이 없습니다" 안내는 조 기준정보 축과 함께 폐기.)

    # 조회 범위 결정 + 조건 변경/새로고침 가드 (dirty 는 직전 렌더 기준) — 계약 불변.
    params = {"year": year, "month": month, "dept": dept, "team": team}
    q = st.session_state.get("q_schedule_edit")
    if q is None:
        q = params
        st.session_state["q_schedule_edit"] = q
        _load_grid(q)
    elif clicked or params != q:
        if st.session_state.get("se_dirty"):
            st.session_state.setdefault("nav_pending", {"type": "scope", "params": params})
        else:
            q = params
            st.session_state["q_schedule_edit"] = q
            _load_grid(q)
    elif "se_rows" not in st.session_state:
        _load_grid(q)

    day_cols = [c for c, _ in st.session_state["se_days"]]
    row_cols = _META + _FIXED + day_cols

    # ── 도메인 파생(하드코딩 금지): 활성 근무형태 순서·색·표시값 → 순환 목록·숫자키·힌트·범례 ──
    #    표시값의 원천은 _label_maps 하나다(명칭 우선·중복 시 코드 폴백). 숫자키·힌트·범례·
    #    셀 색·일자 열 폭이 전부 같은 값을 쓰게 해 셀에 보이는 문자열과 안내가 갈리지 않는다.
    active = _active_ordered()
    display_of, _codes, _lc = _label_maps()
    labeled = [(code, display_of.get(code, sl), color) for code, sl, color in active]
    number_labels = [label for _code, label, _c in labeled][:9]
    cycle_labels = [label for _code, label, _c in labeled] + [""]  # 빈값 포함(지움)
    hint_colors = {}
    for _code, label, color in labeled:
        if color.startswith("#"):
            hint_colors[label] = color

    # ── 알림 슬롯(se_notice): 저장/삭제 배너 + 삭제 예정 패널 + 입력 단축키 줄을 **한 컨테이너**로
    #    묶는다. 배너·패널은 rerun 마다 있거나 없으므로 본문 최상위에 맨몸 요소로 두면 그 유무에
    #    따라 뒤따르는 모든 요소의 delta 경로가 한 칸씩 밀린다. 그러면 Streamlit 이 새 경로에
    #    AG Grid 컨테이너(se_gridwrap)를 다시 만들고, 직전 run 의 그리드 블록이 형제로 남아
    #    **그리드 높이만큼(최대 500px) 빈 블록**이 배너 아래에 생긴다(2026-08-13 저장 직후 공백
    #    회귀). 실측으로 원인을 좁혔다: 배너 개수가 변하지 않는 새로고침에서는 재현되지 않고,
    #    배너가 생기거나 사라지는 rerun 에서만 se_gridwrap 블록이 2개가 된다.
    #    항상 존재하는 컨테이너로 감싸면 본문 최상위 요소 수가 고정돼 그리드 경로가 흔들리지 않는다
    #    (배너가 없을 때 자식은 힌트 줄 하나뿐이라 종전과 같은 높이·간격이다).
    with st.container(key="se_notice"):
        show_flash("schedule_edit")
        _deleted_panel(q)
        # 근태 대상 범위 안내(지정 없음·MANAGER 비대상 부서·비대상 편성 제외 건수).
        # 그리드 **위의 새 최상위 요소가 아니라** 이 슬롯 안이어야 한다(위 주석).
        _scope_notice(str(user.get("dept_code") or "").strip() if manager_locked else "", tracked)
        # 입력 단축키 힌트 라인
        st.markdown(_hint_html(number_labels, hint_colors), unsafe_allow_html=True)
    # 컨텍스트 라인(값은 그리드 뒤 채움) → 표
    context_slot = st.container()

    # 조회 범위가 특정 대분류(또는 MANAGER 부서 잠금)로 좁혀졌는가 — 대분류 열 숨김 판단.
    dept_scope_fixed = _clean(q.get("dept")) not in ("", _ALL)

    # 신원 열 폭·정렬·좌우 패딩(8px)·툴팁은 근무표 3화면 공통 토큰이 소유한다
    # (views.workspace.identity_col_config) — 월간 근무표와 같은 열은 같은 폭이다.
    # 여기서는 이 화면 고유의 편집 계약(사번만 신규 행 편집 가능·파생 2열 읽기 전용·
    # 좁은 폭 숨김·헤더 툴팁)만 덧붙인다.
    #
    # 대분류·중분류는 조직관리(부서 기준정보)에서 파생한 읽기 전용 표시다. 편집·저장의
    # 원천은 '부서' 열 하나이며(중분류가 부서와 1:1 이 아니라 역산이 불가능하다),
    # 여기서 값을 고칠 수 있게 하면 저장되지 않는 편집을 유도하게 된다.
    # 대분류는 조회 조건이 특정 대분류로 좁혀지면 모든 행이 같은 값이라 숨긴다
    # (§0.6 밀도 — 조건 줄·컨텍스트 줄이 이미 같은 값을 말하고 있다). 숨겨도 열은
    # order 에 남아 편집 왕복에서 값이 사라지지 않는다(META 컬럼과 동일 방식).
    #
    # 좁은 폭(폰)에서는 월간 근무표와 **같은 방식**으로 신원 열을 접는다. 종전에는 신원
    # 6열이 모두 pinned 라 390px 에서 고정 열이 280px 을 먹고 날짜 칸이 73px(=1.3일)만
    # 남아 사실상 편성이 불가능했다(2026-08-14 실측). 숨김이라 편집 왕복·저장 payload 는
    # 그대로다. 월간(읽기)은 '성명'만 남기지만 편성은 '사번'도 남긴다 — 신규 행 입력·
    # 붙여넣기의 입력 축이라 접으면 좁은 폭에서 그 기능이 사라진다.
    hidden_meta = set(compact_hidden_meta(_FIXED, compact=compact, keep=("사번",)))
    col_config = dict(identity_col_config(_FIXED))
    col_config["사번"]["editable"] = _EMP_EDITABLE
    col_config["성명"]["editable"] = False
    col_config[_MAJOR].update({
        "editable": False,
        "hide": dept_scope_fixed or _MAJOR in hidden_meta,
        "headerTooltip": "조직관리 대분류 — 부서 기준정보에서 관리합니다(여기서는 편집 불가)",
    })
    col_config[_MINOR].update({
        "editable": False, "hide": _MINOR in hidden_meta,
        "headerTooltip": "조직관리 중분류 — 부서 기준정보에서 관리합니다(여기서는 편집 불가)",
    })
    # '부서'는 **항상 숨긴다**(2026-08-19 사용자 요구). 대분류·중분류가 이미 같은 조직을
    # 말하고 있어 화면에서 사라져도 정보 손실이 없고, 31일 매트릭스에서 116px 은 곧 날짜
    # 두 칸이다. 열을 **제거하지 않고 숨기는** 이유는 저장이 이 열을 원천으로 쓰기 때문이다:
    # _save_rows → _dept_code_of_text(row.get("부서"), catalog) 가 셀 텍스트로 부서코드를
    # 해소하고(중분류는 부서와 1:1 이 아니라 역산 불가), _refresh_org_labels 도 같은 값을
    # 읽는다. AG Grid 의 hide 는 표시만 끄고 rowData 는 그대로 왕복하므로(_FIXED 에 남아
    # order·columns 에 실리고 data_return_mode=AS_INPUT 이 그대로 돌려준다) 저장 payload·
    # 붙여넣기·행 추가 경로는 전부 불변이다. 좁은 폭 숨김(hidden_meta)과 결과가 같아져
    # 조건이 흡수됐다.
    col_config["부서"].update({
        "hide": True,
        "headerTooltip": "이 달 편성 부서 — 부서명 또는 부서코드로 입력하면 대분류·중분류가 따라옵니다",
    })
    # '조'(근무조)는 기준정보 조회가 아니라 자유 입력이며 한 글자만 치면 저장 시
    # 'A' → 'A조' 로 보정된다(normalize_shift_group). 안내는 헤더 툴팁 + 하단 힌트
    # 줄로만 한다 — 빈 셀 placeholder 렌더러는 두지 않는다: 셀 복사가 브라우저
    # 네이티브 텍스트 선택이라 placeholder 문구('직접 입력')가 복사→붙여넣기로
    # 실데이터가 되어 저장될 수 있다(code-review P2, 자유 입력이라 검증도 안 걸림).
    col_config["조"].update({"hide": "조" in hidden_meta, "headerTooltip": _SHIFT_HINT})
    # 날짜 셀 색상 — work_types 기준정보 hex 를 약칭/코드에 매핑(도메인 SoT, 하드코딩 금지).
    # 정렬은 값 길이에 따라 갈린다: 열에 들어가는 값(대부분의 근무형태 명칭)은 가운데,
    # 열보다 긴 값('경조(자녀결혼)' 등)은 좌측이다. 가운데 정렬로 넘치면 브라우저가
    # 양쪽을 잘라 '간 4시' 처럼 앞뒤가 다 사라지고 말줄임 '…' 도 뜨지 않는다(실측).
    # 좌측 정렬이면 뒤쪽만 잘리고 ellipsis 가 살아나며 전문은 tooltipField 가 보증한다.
    # 폭 추정은 파이썬 _label_px 와 **같은 계수**(_CH_KO_PX/_CH_ASCII_PX)를 쓴다.
    # 셀 배경의 근무형태 색은 장식이 아니라 이 화면의 핵심 정보다 — 편성표는 색 패턴으로
    # 교대 주기·연속 야간·휴무 몰림을 읽는 화면이라 남긴다(DESIGN.md §1.3 도메인 색).
    # 구분은 색이 아니라 약칭이 담당하므로 텍스트는 그대로 두고 배경은 26(≈15%) 틴트다.
    day_style = JsCode(
        "function(p) {"
        f"  const colors = {json.dumps(st.session_state.get('se_colors', {}), ensure_ascii=False)};"
        # md-c-center 셀은 좌우 패딩 0 이라 여백은 테두리 몫만 뺀다(정렬 판정용 실폭).
        f"  const room = {json.dumps(max(int(_day_width(cycle_labels)) - 4, 24))};"
        f"  const KO = {_CH_KO_PX}, AS = {_CH_ASCII_PX};"
        "  const v = String(p.value == null ? '' : p.value).trim();"
        "  let w = 0;"
        "  for (let i = 0; i < v.length; i++) { w += v.charCodeAt(i) > 0x1100 ? KO : AS; }"
        "  const align = w <= room ? 'center' : 'left';"
        "  const c = colors[v];"
        # 표 셀 12px (DESIGN.md §1.2 `table`). 30px 행 높이 유지.
        "  if (!c) { return { textAlign: align, fontSize: '12px' }; }"
        "  return { backgroundColor: c + '26', color: '#1c1a17', fontWeight: 600, textAlign: align, fontSize: '12px' };"
        "}"
    )
    # 셀 클릭=근무 순환(빈값 포함) + 숫자키 1..N/0 = 근무형태/지움(도메인 파생). 값은
    # setDataValue→cellValueChanged→기존 dirty/검증/저장 경로 그대로(계약 불변).
    handlers = _day_cell_handlers(cycle_labels, number_labels)
    # 일자 열 폭은 실제 표시값에서 유도한다(_day_width) — 명칭 축 전환으로 값이 길어진
    # 만큼만 넓히고 상한에서 멈춘다. 상한을 넘는 값은 말줄임되므로 tooltipField 로
    # 전체 문자열을 보증한다(그리드가 enableBrowserTooltips 로 네이티브 title 렌더).
    day_w = _day_width(cycle_labels)
    for c in day_cols:
        col_config[c] = {
            "width": day_w, "minWidth": 34, "cellClass": "md-c-center", "cellStyle": day_style,
            "headerComponent": _day_header_component(c),  # 일자 헤더 2줄(숫자/요일)
            "tooltipField": c,
            **handlers,
        }

    # se_feed 는 remount 시점 값으로 고정(편집 결과 재전송이 버튼 클릭 rerun 을 삼키는 것 방지).
    nonce = st.session_state.setdefault("se_nonce", 0)
    feed = st.session_state.get("se_feed", st.session_state["se_rows"])
    if compact and not landscape:
        # 좁은 폭 세로: 한 화면에 담기는 날짜가 적다 — 월간 근무표와 같은 문구·같은 자리
        # (표 바로 위 보조 텍스트 1줄, 장식·아이콘 없음)로 가로 전환을 안내한다.
        st.markdown(
            "<div class='se-rotate'>가로로 돌리면 한 번에 더 많은 날짜를 볼 수 있습니다</div>",
            unsafe_allow_html=True,
        )
    with st.container(key="se_gridwrap"):
        grid_df = selectable_master_grid(
            feed,
            key=f"se_grid_{nonce}",
            columns={c: "text" for c in _FIXED + day_cols},
            order=_FIXED + day_cols,
            # ≈62vh 내부 스크롤. 좁은 폭에서는 월간 근무표와 같은 뷰포트 클램프를 쓴다
            # (행 피치 30px·하한 210 은 이 화면 값 — §1-C).
            height=month_grid_height(len(feed), compact=compact, landscape=landscape,
                                     viewport_h=int(vp.get("h") or 0),
                                     row_px=30, pad_px=96, min_px=210),
            col_config=col_config,
            select_all_header=True,  # 표시 중인 기존 행만 대상 (신규 행 제외)
            # 셀 높이 30px(§1-C). 클릭 순환 제거(피드백) → suppressClickEdit 해제해 더블클릭
            # 편집기·직접 타이핑을 복원한다. 숫자키·방향키·Ctrl+V 는 그대로 유지.
            # enableBrowserTooltips: '조' 열 headerTooltip 을 AG Grid 자체 tooltip 컴포넌트
            # (별도 모듈 등록 필요)가 아니라 브라우저 기본 title 로 렌더해 항상 뜨게 한다.
            extra_grid_options=_grid_extra_options(feed),
            # 행 앞 핸들 드래그로 순서 변경(2026-08-11 사용자 요구 — 근태표 등록 순서 유지).
            # 확정된 순서는 저장 시 users.display_order 로 영속화된다(_persist_row_order).
            row_drag=True,
        )

    # 구조 변경(− 제거/붙여넣기 신규 행) + 사번 자동 조회를 권위 상태로 동기화
    if _sync_rows(grid_df, row_cols):
        st.rerun()

    live = _live(grid_df)

    # 건수 계산
    existing_live = live[live["_row_state"] == "existing"] if not live.empty else live
    n_exist = len(existing_live)
    n_sel = int(existing_live["_sel"].map(grid_bool).sum()) if n_exist else 0
    n_del = len(st.session_state.get("se_deleted", []))
    n_people = len(live)
    filled = 0
    if not live.empty and day_cols:
        filled = int(live[day_cols].apply(
            lambda col: col.map(lambda v: bool(str(v).strip()) if pd.notna(v) else False)
        ).sum().sum())
    empty_cells = max(n_people * len(day_cols) - filled, 0)

    # 컨텍스트 라인 채움(YYYY-MM · 대분류 · 조 + 인원/입력/미입력). 전체(_ALL)면 라벨로 표기.
    dept_lbl = _scope_label(q.get("dept"), dept_names)
    team_lbl = "전체 조" if q.get("team") == _ALL else str(q.get("team") or "")
    with context_slot:
        st.markdown(
            _context_html(q, dept_lbl, team_lbl, n_people, filled, empty_cells),
            unsafe_allow_html=True,
        )

    # dirty 판정: 원본 스냅샷과 현재 편집 상태(정규화)를 비교 — 계약 불변.
    dirty = _canon(live, st.session_state.get("se_deleted", []), day_cols) \
        != st.session_state.get("se_orig")
    st.session_state["se_dirty"] = dirty
    if dirty:
        st.session_state["nav_guard"] = {"owner": "schedule_edit"}
    elif st.session_state.get("nav_guard", {}).get("owner") == "schedule_edit":
        st.session_state.pop("nav_guard", None)

    # 브라우저 새로고침/탭 닫기 경고 (best effort)
    st.html(
        "<script>window.onbeforeunload = "
        + ("function(e){e.preventDefault(); e.returnValue='';};" if dirty else "null;")
        + "</script>",
        unsafe_allow_javascript=True,
    )

    # 미저장 이탈 확인 (그리드보다 아래에 렌더 — iframe 재생성로 편집 리셋 방지)
    pending = st.session_state.get("nav_pending")
    if pending:
        _leave_dialog(pending, q)

    # ── 하단: 범례(근무형태 색) + 미저장 변경 N건 ──
    #    범례도 셀과 **같은 표시값**(labeled)을 쓴다 — 셀은 명칭인데 범례만 약칭이면
    #    말줄임된 셀을 범례로 되짚을 수 없다.
    st.markdown(_legend_html(labeled), unsafe_allow_html=True)
    order_base = st.session_state.get("se_order_base")
    order_changed = bool(order_base) and _order_moved(list(order_base), _visible_emp_order(live))
    changed = _change_count(
        live, day_cols, st.session_state.get("se_orig_cells", {}), n_del, order_changed
    )
    st.markdown(
        f"<div class='se-dirty{' on' if changed else ''}'>미저장 변경 {changed}건</div>",
        unsafe_allow_html=True,
    )

    # ── 헤더 아이콘 음영 상태를 화면 스코프로 발행(다음 rerun 의 헤더가 읽음) — 삭제는
    #    선택 0, 저장은 dirty 0 일 때 음영. 사유 문구는 tooltip 으로 함께 노출한다. ──
    header_states = {
        "add": (False, None),
        "refresh": (False, None),
        "delete": (n_sel == 0, "삭제할 기존 행을 먼저 선택하세요" if n_sel == 0 else None),
        "save": (not dirty, "저장할 변경이 없습니다" if not dirty else None),
    }
    ui.publish_header_actions("schedule_edit", header_states)

    # 헤더 아이콘이 발화한 플래그 처리 (최신 live 기준) — 실행 경로·확인 게이트 불변.
    if st.session_state.pop("se_save_req", False):
        _save(live, q, day_cols)
    if st.session_state.pop("se_del_req", False):
        _mark_delete(live, row_cols)
    if st.session_state.pop("se_add_req", False):
        _add_row(live, row_cols, day_cols)

    # 화면 폭/방향 프로브는 본문의 **맨 끝**에 둔다(월간 근무표와 같은 이유 —
    # mount_viewport_probe 주석: 조건 위젯이 모두 만들어진 뒤에만 리런이 걸리게 한다).
    # 넓은 폭에서는 값이 표시에 쓰이지 않아 추가 리런을 만들지 않는다(_layout 판정).
    mount_viewport_probe("schedule_edit")

    # 발행값을 헤더가 따라오게 한다 — **액션 flag 소비 뒤**에 둔다(위 세 handler 는 각자
    # st.rerun() 으로 끝나므로 실행된 run 에서는 여기까지 오지 않는다). 여기보다 앞에서
    # rerun 하면 헤더 클릭으로 세팅된 flag 가 소비되기 전에 프레임이 끝난다.
    _sync_header(header_states)


# ---------- 행 상태 헬퍼 ----------
def _live(grid_df: pd.DataFrame) -> pd.DataFrame:
    if grid_df is None or grid_df.empty or "_removed" not in grid_df.columns:
        return grid_df if grid_df is not None else pd.DataFrame()
    keep = grid_df["_removed"].fillna("").astype(str).str.strip() != "1"
    return grid_df[keep]


def _next_rid() -> str:
    n = st.session_state.get("se_rid", 0) + 1
    st.session_state["se_rid"] = n
    return f"n:{n}"


def _remount(scroll_rid=None, focus_col: str | None = None) -> None:
    """그리드를 권위 상태(se_rows) 기준으로 재마운트한다.

    재마운트는 AgGrid iframe 을 새로 만들어 **내부 스크롤·포커스가 맨 위로 초기화**된다
    — 행 추가·사번 자동 조회처럼 아래쪽 행을 만지던 중이면 사용자는 매번 다시 아래로
    내려가야 했다(2026-08-20 "한 줄 추가하면 화면 초기화" 신고의 실체. 저장이 아니라
    재마운트다). ``scroll_rid`` 를 주면 다음 마운트에서 그 행을 다시 보이게 하고
    (onFirstDataRendered → ensureIndexVisible), ``focus_col`` 까지 주면 그 셀에
    포커스를 되돌린다 — 작업 지점이 보존된다."""
    st.session_state["se_feed"] = st.session_state["se_rows"].copy()
    st.session_state["se_nonce"] = st.session_state.get("se_nonce", 0) + 1
    if scroll_rid is not None:
        st.session_state["se_scroll"] = {"rid": str(scroll_rid), "col": focus_col}


def _grid_extra_options(feed: pd.DataFrame) -> dict:
    """재마운트 1회분 스크롤·포커스 복원 옵션(_remount 가 남긴 se_scroll 소비).

    onFirstDataRendered 는 마운트당 1회만 발화하므로 이후 편집 rerun 에는 영향이
    없다. 대상 행이 피드에 없으면(삭제 직후 등) 조용히 건너뛴다."""
    extra = {"rowHeight": 30, "enableBrowserTooltips": True}
    scroll = st.session_state.pop("se_scroll", None)
    if scroll and feed is not None and not feed.empty and "_row_id" in feed.columns:
        ids = [str(v) for v in feed["_row_id"]]
        rid = str(scroll.get("rid"))
        if rid in ids:
            idx = ids.index(rid)
            col = scroll.get("col")
            js = "function(params){params.api.ensureIndexVisible(%d, 'middle');" % idx
            if col:
                js += "params.api.setFocusedCell(%d, '%s');" % (idx, col)
            js += "}"
            extra["onFirstDataRendered"] = JsCode(js)
    return extra


def _blank_row(day_cols: list) -> dict:
    row = {"_row_id": _next_rid(), "_row_state": "new", "_sel": False}
    for c in _FIXED + day_cols:
        row[c] = ""
    return row


def classify_save_targets(live_emps, deleted_emps):
    """혼합 저장 분류 — (delete_only, replace_after_delete) 를 정렬 리스트로 반환.

    삭제 예정 사번이 화면에 다시 입력돼 있으면 충돌이 아니라 '해당 월 교체' 대상이다.
    """
    live = {str(e).strip() for e in live_emps if str(e).strip()}
    dele = {str(e).strip() for e in deleted_emps if str(e).strip()}
    return sorted(dele - live), sorted(dele & live)


def normalize_shift_group(text) -> str:
    """근무조 자유 입력 정규화 (순수). ``A`` → ``A조``, ``b`` → ``B조``, 빈 값 → ``''``.

    2026-08-07 사용자 결정으로 A/B/C조는 기준정보(teams)가 아니라 편성표에서 직접
    입력한다. 한 글자만 치면 '조'를 붙여주되, **자동 부착은 한 글자 입력에만** 적용한다 —
    '주간'을 '주간조'로 바꾸는 식의 오지랖을 막기 위해서다. 이미 '조'로 끝나면 그대로 둔다.
    """
    value = str(text or "").strip()
    if not value:
        return ""
    if len(value) == 1 and value.isalnum():
        return f"{value.upper()}조"
    # 'a조' 처럼 영문 한 글자 + 조 인 경우만 대문자로 맞춘다(표기 흔들림 방지).
    if len(value) == 2 and value.endswith("조") and value[0].isascii() and value[0].isalpha():
        return f"{value[0].upper()}조"
    return value


def should_save_assignment(state, cur_dept_code, cur_team_code, loaded) -> bool:
    """이 행의 부서·조 편성을 schedule_assignments 에 저장(upsert)해야 하는가 (순수).

    - state == "new": 신규 직원·월 → 유효 부서가 있으면 저장.
    - 기존 행: 로드 스냅샷(loaded=(dept_code, team_code))과 현재 부서·조가 다를 때만.
      legacy(편성 없던) 행이든 persisted 행이든 '변경됐을 때만' 저장하므로, 근무만
      수정한 경우 users 현재 소속이 과거 편성으로 자동 저장되지 않는다.
    loaded 가 None(스냅샷 없음)이면 신규가 아닌 한 저장하지 않는다.
    """
    if state == "new":
        return bool(str(cur_dept_code or "").strip())
    if loaded is None:
        return False
    # 스냅샷은 (부서, 조, 근무조) 3-튜플이다. 화면의 '조' 축이 team_code 에서
    # shift_group_code 로 옮겨갔으므로 비교 대상도 근무조다. 2-튜플(구 계약)이 들어오면
    # 종전대로 team_code 와 비교한다 — 기존 회귀 테스트를 그대로 통과시키기 위해서다.
    prev_shift = str(loaded[2] if len(loaded) > 2 else loaded[1])
    return (str(cur_dept_code or ""), str(cur_team_code or "")) != (str(loaded[0]), prev_shift)


def _build_users_map(users: pd.DataFrame) -> dict:
    return {
        str(r["emp_no"]).strip(): {
            "name": str(r["name"]),
            "dept_code": str(r["dept_code"]).strip(),
            "team_code": str(r["team_code"]).strip(),
            "is_active": bool(r["is_active"]),
        }
        for _, r in users.iterrows()
        if str(r["emp_no"]).strip()
    }


def _users_by_emp() -> dict:
    """사용자 매핑 — 조회(_load_grid) 시점 캐시를 재사용한다.

    rerun/저장마다 users 전체를 반복 조회하면 일시 소켓 오류(WinError 10035)에
    노출되는 표면적만 커진다. 최신화는 [새로고침]/조건 변경 시 이루어진다.
    """
    cached = st.session_state.get("se_users_map")
    if cached is None:
        cached = _build_users_map(db.get_users(include_resigned=False))
        st.session_state["se_users_map"] = cached
    return cached


def _refresh_org_labels(live: pd.DataFrame, idx, row, catalog: dict) -> bool:
    """한 행의 대분류·중분류를 '부서' 값에서 다시 파생한다. 값이 바뀌었으면 True.

    부서가 비었거나 해석되지 않으면(오타·동명 부서) 두 칸을 비운다 — 옛 부서의 분류가
    남아 새 부서인 척하는 것이 가장 나쁜 표시다. 저장은 이 열을 보지 않으므로
    (원천은 '부서' 열) 여기서 비워도 저장 계약에는 영향이 없다.
    """
    dept_code = _dept_code_of_text(row.get("부서"), catalog)
    major, minor = _org_labels(dept_code, catalog) if dept_code else ("", "")
    changed = False
    for col, value in ((_MAJOR, major), (_MINOR, minor)):
        if _clean(row.get(col)) != value:
            live.at[idx, col] = value
            changed = True
    return changed


def _sync_rows(grid_df: pd.DataFrame, row_cols: list) -> bool:
    """그리드 구조 변경을 권위 상태로 반영하고 사번 기반 자동 조회를 수행한다.

    - − 로 제거된 행을 실제 제거
    - 붙여넣기로 생긴 무명 행에 _row_id/_row_state 부여
    - 신규 행: 사번 → 성명 자동 표시(미등록이면 "(미등록)"), 부서·조가 비어 있으면
      사용자 기준정보의 현재 소속으로 기본값 채움 (users 는 변경하지 않음)
    - 기존 행: 사번·성명을 원본으로 강제(붙여넣기로 덮여도 복원)
    - 모든 행: '부서' 값에서 대분류·중분류를 다시 파생(읽기 전용 표시 열이므로 사용자가
      붙여넣기로 덮어써도 부서 기준의 값으로 되돌린다). 파생은 같은 입력에 같은 결과라
      한 번 수렴하면 더 이상 changed 를 만들지 않는다(재마운트 루프 없음).
    변경이 있으면 se_rows 갱신 + 그리드 재마운트 후 True.
    """
    if grid_df is None or grid_df.empty or "_row_id" not in grid_df.columns:
        return False
    removed = grid_df["_removed"].fillna("").astype(str).str.strip() == "1" \
        if "_removed" in grid_df.columns else pd.Series(False, index=grid_df.index)
    live = grid_df[~removed].copy()
    changed = bool(removed.any())
    # 재마운트 후 되돌아갈 작업 지점(행 id) — 아래 각 변경 지점이 갱신한다. 없으면
    # 종전처럼 맨 위 마운트다(_remount docstring 참조).
    anchor = None
    if changed and not live.empty:
        # − 제거: 제거된 자리 부근의 남은 행을 계속 보이게 한다.
        first_removed = int(removed.to_numpy().argmax())
        kept_pos = min(max(first_removed - 1, 0), len(live) - 1)
        anchor = str(live.iloc[kept_pos]["_row_id"])

    users = _users_by_emp()
    catalog = _dept_catalog()

    rid = live["_row_id"].fillna("").astype(str).str.strip()
    needs_id = rid == ""
    if needs_id.any():
        changed = True
        for idx in live.index[needs_id]:
            live.at[idx, "_row_id"] = _next_rid()
            live.at[idx, "_row_state"] = "new"
            live.at[idx, "_sel"] = False
    live["_row_state"] = live["_row_state"].fillna("").astype(str).replace("", "new")

    for idx, row in live.iterrows():
        state = str(row["_row_state"])
        emp = str(row.get("사번") or "").strip()
        if state == "existing":
            orig_emp = str(row["_row_id"])[2:]  # "e:{emp_no}"
            master = users.get(orig_emp)
            name = str(master["name"]) if master is not None else ""
            if emp != orig_emp:
                live.at[idx, "사번"] = orig_emp
                changed = True
            if str(row.get("성명") or "") != name:
                live.at[idx, "성명"] = name
                changed = True
            if _refresh_org_labels(live, idx, row, catalog):
                changed = True
            continue
        master = users.get(emp) if emp else None
        target_name = "" if not emp else (str(master["name"]) if master is not None else "(미등록)")
        if str(row.get("성명") or "") != target_name:
            live.at[idx, "성명"] = target_name
            changed = True
            anchor = str(live.at[idx, "_row_id"])  # 방금 사번을 입력한 그 행으로 복귀
        if master is not None:
            if not str(row.get("부서") or "").strip():
                live.at[idx, "부서"] = db.dept_name(master["dept_code"])
                row = live.loc[idx]  # 아래 대분류·중분류 파생이 방금 채운 부서를 보게 한다
                changed = True
            # '조'(근무조)는 자동 채움하지 않는다 — 2026-08-07 결정으로 이 칸은 운영단위가
            # 아니라 자유 입력 근무조이며, users 마스터에는 대응 값이 없다.
        if _refresh_org_labels(live, idx, row, catalog):
            changed = True

    # 행 드래그(_action 열 핸들) 결과 — 반환 프레임의 _row_id 시퀀스가 권위 상태와 다르면
    # 그 순서를 서버 권위로 즉시 확정하고 재마운트한다. 확정하지 않으면 다음 remount 에서
    # se_feed(옛 순서)가 다시 실려 이동이 소실된다. _row_id 집합이 **정확히 같을 때만**
    # 재배열해 붙여넣기 신규 행·− 제거 같은 구조 변경과의 경합에서 순서를 추측하지 않는다
    # (구조 변경은 아래 changed 경로가 이미 remount 한다).
    prev_rows = st.session_state.get("se_rows")
    if prev_rows is not None and not prev_rows.empty and "_row_id" in prev_rows.columns:
        prev_ids = [str(v) for v in prev_rows["_row_id"]]
        cur_ids = [str(v) for v in live["_row_id"]]
        if prev_ids != cur_ids and sorted(prev_ids) == sorted(cur_ids):
            changed = True
            # 첫 어긋남 위치의 현재 행 = 드래그 목적지 부근 — 그 행으로 복귀한다.
            diff_at = next(i for i, (a, b) in enumerate(zip(prev_ids, cur_ids)) if a != b)
            anchor = cur_ids[diff_at]

    # 값 편집도 매 rerun 권위 상태에 반영한다 (구조 변경이 없으면 remount 는 하지 않음
    # — 그리드가 이미 최신 값을 보여주고 있고, feed 재전송은 클릭 rerun 을 삼킬 수 있다).
    st.session_state["se_rows"] = live[row_cols].reset_index(drop=True)
    if changed:
        _remount(scroll_rid=anchor)
    return changed


def _add_row(live: pd.DataFrame, row_cols: list, day_cols: list) -> None:
    base = live[row_cols].copy() if not live.empty else pd.DataFrame(columns=row_cols)
    new_row = _blank_row(day_cols)
    st.session_state["se_rows"] = pd.concat(
        [base, pd.DataFrame([new_row])], ignore_index=True,
    )[row_cols]
    # 새 행은 맨 아래(저장 시 부서그룹 마지막 슬롯 계약과 일치) — 대신 그리드가 거기로
    # 따라가 사번 셀에 포커스를 준다. 안내로 "저장된 것 아님"을 못박는다(자동 저장 오해).
    _remount(scroll_rid=new_row["_row_id"], focus_col="사번")
    set_flash("schedule_edit", "info",
              "빈 행을 맨 아래에 추가하고 그 위치로 이동했습니다 — 사번을 입력하세요. "
              "[저장]을 누르기 전에는 아무것도 저장되지 않습니다.")
    st.rerun()


def _mark_delete(live: pd.DataFrame, row_cols: list) -> None:
    """선택된 기존 행을 삭제 예정으로 옮긴다 (즉시 DB 삭제 없음 — 저장 시 처리)."""
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    if sel.empty:
        set_flash("schedule_edit", "warning", "삭제할 기존 행(체크박스)을 선택하세요. 신규 행은 − 버튼으로 제거합니다.")
        st.rerun()
    deleted = st.session_state.setdefault("se_deleted", [])
    deleted.extend(r.to_dict() for _, r in sel[row_cols].iterrows())
    remaining = live[~live.index.isin(sel.index)].assign(_sel=False)
    st.session_state["se_rows"] = remaining[row_cols].reset_index(drop=True)
    # 첫 삭제 행 직전(없으면 첫) 남은 행으로 복귀 — 삭제 후 맨 위로 튀지 않는다.
    anchor = None
    if not remaining.empty:
        live_ids = [str(v) for v in live["_row_id"]]
        del_ids = {str(v) for v in sel["_row_id"]}
        kept_ids = [i for i in live_ids if i not in del_ids]
        first_del = next(i for i, v in enumerate(live_ids) if v in del_ids)
        anchor = kept_ids[min(max(first_del - 1, 0), len(kept_ids) - 1)]
    _remount(scroll_rid=anchor)
    st.rerun()


def _deleted_panel(q: dict) -> None:
    deleted = st.session_state.get("se_deleted", [])
    if not deleted:
        return
    names = ", ".join(f"{r.get('성명', '')}({str(r.get('사번', '')).strip()})" for r in deleted)
    st.warning(
        f"[저장] 시 다음 직원의 {q['year']}-{q['month']:02d} 근무표가 모두 삭제됩니다: {names}\n\n"
        "다른 월의 근무표와 사용자 기준정보는 삭제되지 않습니다."
    )
    c1, _sp = st.columns([1.6, 8], vertical_alignment="center")
    if c1.button("삭제 예정 취소", key="se_undel", width="stretch"):
        rows = st.session_state.get("se_rows", pd.DataFrame())
        restored = pd.concat([rows, pd.DataFrame(deleted)], ignore_index=True)
        st.session_state["se_rows"] = restored[rows.columns] if not rows.empty else restored
        st.session_state["se_deleted"] = []
        _remount()
        st.rerun()


# ---------- 이탈 확인 ----------
def _discard_draft() -> None:
    for key in ("se_rows", "se_feed", "se_days", "se_orig", "se_orig_cells",
                "se_orig_assign", "se_order_base", "se_deleted", "se_dirty",
                "se_untracked"):
        st.session_state.pop(key, None)
    st.session_state.pop("nav_guard", None)


def _leave_dialog(pending: dict, q: dict) -> None:
    st.warning("저장하지 않은 변경사항이 있습니다.\n\n이동하면 입력한 내용이 사라집니다.")
    c1, c2, _sp = st.columns([1.4, 1.9, 5.7], vertical_alignment="center")
    if c1.button("계속 편집", key="se_stay", type="primary", width="stretch"):
        st.session_state.pop("nav_pending", None)
        if pending.get("type") == "scope":
            st.session_state["se_revert"] = True
        _remount()  # 권위 상태(se_rows) 기준으로 편집 내용을 확실히 복원
        st.rerun()
    if c2.button("저장하지 않고 이동", key="se_leave", width="stretch"):
        st.session_state.pop("nav_pending", None)
        _discard_draft()
        if pending.get("type") == "scope":
            new_q = pending["params"]
            st.session_state["q_schedule_edit"] = new_q
            _load_grid(new_q)
        else:
            ui.apply_nav(pending)
        st.rerun()


# ---------- 적재 ----------
def _label_maps():
    """근무형태 표시/입력 매핑 — 표시는 **명칭(name)**, 입력은 명칭·약칭·코드를 받는다.

    2026-08-14 사용자 지시로 이 화면의 셀 표시·입력 축을 약칭(short_label)에서
    명칭(name)으로 옮긴다. 실데이터에서 약칭은 여러 근무형태가 공유해(한 약칭을 십수
    개 코드가 사용) 왕복 변환이 모호해졌고, 그때 코드로 표시하는 기존 안전장치가
    발동해 화면에 내부 코드가 그대로 보였다. 명칭은 근무형태마다 유일하므로 이 모호성이
    원천 제거된다.

    **안전장치는 그대로 유지한다** — 축만 옮기는 것이지 보호를 없애는 게 아니다:
      - 명칭이 비었거나 다른 근무형태와 겹치면 그 코드는 **코드로 표시**한다.
      - 입력은 명칭·약칭·코드를 모두 받되, 값 하나가 여러 코드에 걸리면 저장을 막는다
        (:func:`_resolve_work` 의 ``AMBIG``). 종전처럼 약칭을 치던 사용자는 그 약칭이
        유일할 때 그대로 통과하고, 겹치는 약칭이면 "여러 근무형태에 매핑" 오류로 막힌다
        — 조용히 아무 코드나 고르는 것이 이 화면에서 가장 위험한 동작이기 때문이다.

    반환: (display_of: 코드→표시값, codes: 유효 코드 집합, input_codes: 입력값→코드집합)
    """
    wt = db.get_work_types()
    active = wt[wt["is_active"]] if not wt.empty else wt
    codes: set = set()
    name_codes: dict = {}   # 표시 유일성 판정(명칭 축)
    input_codes: dict = {}  # 입력 해석(명칭 + 약칭 병합)
    for _, r in active.iterrows():
        code = str(r["code"]).strip()
        if not code:
            continue
        codes.add(code)
        name = str(r.get("name") or "").strip()
        if name:
            name_codes.setdefault(name, set()).add(code)
            input_codes.setdefault(name, set()).add(code)
        label = str(r.get("short_label") or "").strip()
        if label:
            input_codes.setdefault(label, set()).add(code)
    display_of = {}
    for _, r in active.iterrows():
        code = str(r["code"]).strip()
        name = str(r.get("name") or "").strip()
        display_of[code] = name if name and len(name_codes.get(name, set())) == 1 else code
    return display_of, codes, input_codes


def _resolve_work(value: str, codes: set, label_codes: dict):
    """입력값(명칭·약칭 또는 코드) → 내부 코드. 미등록 None, 모호한 값 'AMBIG' 반환."""
    if value in codes:
        return value
    matched = label_codes.get(value)
    if not matched:
        return None
    return next(iter(matched)) if len(matched) == 1 else "AMBIG"


def _day_color_map(display_of: dict) -> dict:
    """날짜 셀 색상 맵 — work_types 기준정보의 색상을 표시값과 코드에 매핑한다.

    약칭이 바뀌거나 재조회돼도 같은 코드는 같은 색을 유지한다(색은 코드에 귀속).
    """
    wt = db.get_work_types()
    active = wt[wt["is_active"]] if not wt.empty else wt
    colors = {}
    for _, r in active.iterrows():
        code = str(r["code"]).strip()
        color = str(r["color"] or "").strip()
        if not code or not color.startswith("#"):
            continue
        colors[code] = color                      # 코드 그대로 표시되는 fallback 셀
        display = display_of.get(code)
        if display:
            colors[display] = color               # 약칭 표시 셀
    return colors


def _row_sort_key(major: str, major_order: int, shift: str, group_order: int,
                  display_order, emp: str) -> tuple:
    """행 정렬 키 (순수) — 2026-08-13 사용자 확정 기준.

    ① 대분류: 그 대분류에 속한 부서의 최소 표시순서(조직관리 시트 순서)를 따른다 —
       분류 이름을 코드에 고정하지 않고 기준정보 순서만 읽는다. 조직관리에서 순서를
       바꾸면 이 화면 묶음 순서도 따라 바뀐다. 대분류가 없는(미분류) 행은 언제나 마지막.
    ② 조: A조 → B조 → C조 → 비표준 표기 → 빈 조 (:func:`_shift_rank`).
    ③ 부서그룹 순서: 행 순서 영속(users.display_order)이 부서그룹 단위 슬롯이라
       같은 축을 유지해야 드래그 결과가 재조회에서 그대로 돌아온다. 실데이터의
       생산 부서는 모두 같은 그룹이라 이 단계는 사실상 무영향이다.
    ④ 표시순서(display_order, 근태표 등록 순서) — 미지정은 뒤. ⑤ 사번.
    """
    major_tier = (0, int(major_order), major) if major else (1, 0, "")
    return (
        major_tier,
        _shift_rank(shift),
        int(group_order),
        1 if display_order is None else 0,
        0 if display_order is None else int(display_order),
        emp,
    )


def _load_grid(q: dict) -> None:
    """선택 범위(대분류·조 재직 직원)의 해당 월 '저장된' 근무표 행만 적재한다.

    전체 사용자를 자동 나열하지 않는다 — 저장 행이 없으면 신규 입력 행 1개만 둔다.

    필터는 **화면에 보이는 값 기준**이다: 부서는 그 달 편성 스냅샷의 부서(없으면 users
    현재 소속)에서 유도한 대분류로, 조는 편성 스냅샷의 근무조로 거른다. users 마스터로
    먼저 거르지 않는 이유는 인사이동 뒤에도 그 달 편성이 진실이기 때문이다.

    마지막으로 근태 등록 대상 부서(_attendance_scope)로 한 번 더 거른다. 제외한 행은
    사라진 것처럼 두지 않고 부서별 인원수를 se_untracked 에 남겨 알림 슬롯이 밝힌다.
    """
    ndays = calendar.monthrange(q["year"], q["month"])[1]
    days = []
    for d in range(1, ndays + 1):
        dt = date(q["year"], q["month"], d)
        days.append((f"{d}({ui.weekday_kr(dt)})", dt.isoformat()))
    day_cols = [c for c, _ in days]
    row_cols = _META + _FIXED + day_cols

    users = db.get_users(include_resigned=False)  # 퇴사자는 편성 명단에서 제외
    st.session_state["se_users_map"] = _build_users_map(users)  # 조회 시점 캐시 갱신
    scope = users[users["is_active"]]  # 재직자 전체 — 부서·조 필터는 표시값 기준으로 아래에서
    emp_nos = [str(e).strip() for e in scope["emp_no"]]

    scheds = db.get_month_schedules(emp_nos, q["year"], q["month"]) if emp_nos else pd.DataFrame(
        columns=db.SCHEDULE_COLUMNS
    )
    display_of, _, _ = _label_maps()
    st.session_state["se_colors"] = _day_color_map(display_of)
    lookup = {
        (str(r["emp_no"]).strip(), str(r["duty_date"])): str(r["work_type_code"]).strip()
        for _, r in scheds.iterrows()
    }
    with_rows = {emp for emp, _iso in lookup}
    # 부서·조는 편성 스냅샷을 우선 표시한다 (없으면 users 의 현재 소속).
    snaps = _assignment_snapshots(q, sorted(with_rows))
    catalog = _dept_catalog()
    group_of = db.dept_group_map()
    tracked = _attendance_scope()  # None 이면 필터 없음(폴백)
    untracked_counts: dict = {}  # dept_code -> 근태 비대상으로 제외한 인원수

    keyed = []  # (정렬키, row) — 정렬은 이 화면 로컬 규칙(_row_sort_key)이다
    orig_assign = {}  # rid -> (dept_code, team_code, shift) 로드 스냅샷 (편성 변경 판정용)
    for _, u in scope.iterrows():
        emp = str(u["emp_no"]).strip()
        if emp not in with_rows:
            continue  # 저장된 행이 있는 직원만 표시 (전체 자동 나열 금지)
        # 과거 편성이 없으면 users 현재 소속을 표시용 fallback 으로만 쓴다(자동 저장 금지).
        # 근무조는 fallback 대상이 아니다 — 마스터에 없는 값이라 빈 칸에서 시작한다.
        dept_code, team_code, shift_code = snaps.get(
            emp, (str(u["dept_code"]).strip(), str(u["team_code"]).strip(), "")
        )
        if not _in_scope(q.get("dept"), dept_code, catalog):
            continue  # 조회 조건: 대분류(또는 MANAGER 부서 잠금) 범위 밖
        shift_label = normalize_shift_group(shift_code)
        if q.get("team") != _ALL and shift_label != _clean(q.get("team")):
            continue  # 조회 조건: 근무조 범위 밖
        if not _tracked_dept(dept_code, tracked):
            # 근태 등록 대상이 아닌 부서의 편성 — 목록에서 빼되 '몇 명을 뺐는지'는 남긴다.
            # (조회 조건·조 필터를 통과한 행만 세므로 안내 건수가 화면 범위와 일치한다.)
            code = _clean(dept_code)
            untracked_counts[code] = untracked_counts.get(code, 0) + 1
            continue
        major, minor = _org_labels(dept_code, catalog)
        rid = f"e:{emp}"
        orig_assign[rid] = (dept_code, team_code, shift_code)
        row = {
            "_row_id": rid, "_row_state": "existing", "_sel": False,
            "사번": emp,
            "성명": str(u["name"]),
            _MAJOR: major,
            _MINOR: minor,
            "부서": db.dept_name(dept_code),
            "조": shift_code,
        }
        for col, iso in days:
            code = lookup.get((emp, iso), "")
            row[col] = display_of.get(code, code) if code else ""
        try:
            display_order = db.normalize_display_order(u.get("display_order"))
        except (TypeError, ValueError):
            display_order = None  # 형식 오류는 기준정보 화면 검증이 담당 — 여기선 미지정
        # 부서그룹 tier 는 users 마스터 소속 기준이다(행 순서 영속 슬롯과 같은 축).
        master_dept = str(u["dept_code"]).strip()
        row_major = catalog["org_of"].get(dept_code, ("", ""))[0]
        keyed.append((
            _row_sort_key(
                row_major,
                catalog["major_order"].get(row_major, _TAIL_ORDER),
                shift_label,
                group_of.get(master_dept, (master_dept, _TAIL_ORDER))[1],
                display_order,
                emp,
            ),
            row,
        ))
    keyed.sort(key=lambda item: item[0])
    rows = [row for _key, row in keyed]

    frame = pd.DataFrame(rows, columns=row_cols) if rows else pd.DataFrame(
        [_blank_row(day_cols)], columns=row_cols
    )

    st.session_state["se_rows"] = frame
    st.session_state["se_days"] = days
    st.session_state["se_deleted"] = []
    # 근태 비대상으로 제외한 편성 — 알림 슬롯이 '제외 N명'으로 드러낸다(감춘 채 두지 않음).
    st.session_state["se_untracked"] = {
        "count": sum(untracked_counts.values()),
        "depts": [db.dept_name(code) or code for code in untracked_counts],
    }
    # 행 순서 영속(users.display_order)의 기준선 — 이 순서와 최종 화면 순서가 다를 때만
    # 저장 단계에서 슬롯 재배정을 쓴다(순서를 안 바꾼 저장은 users 를 건드리지 않는다).
    st.session_state["se_order_base"] = _visible_emp_order(frame)
    st.session_state["se_orig_assign"] = orig_assign  # 편성 변경 판정용 로드 스냅샷
    st.session_state["se_orig"] = _canon(frame, [], day_cols)
    # 원본 셀 값(기존 행): '변경분만 저장'과 '빈 칸 = 삭제 아님' 안내에 사용
    st.session_state["se_orig_cells"] = {
        (str(r["_row_id"]), c): str(r[c]).strip()
        for _, r in frame.iterrows() if r["_row_state"] == "existing"
        for c in day_cols
    }
    st.session_state["se_dirty"] = False
    if st.session_state.get("nav_guard", {}).get("owner") == "schedule_edit":
        st.session_state.pop("nav_guard", None)
    _remount()


def _canon(rows: pd.DataFrame, deleted: list, day_cols: list):
    """dirty 비교용 정규화 스냅샷 (성명은 파생값이므로 제외)."""
    out = []
    for _, r in rows.iterrows():
        out.append(tuple(
            str(r.get(c) if pd.notna(r.get(c)) else "").strip()
            for c in ["사번", "부서", "조"] + day_cols
        ))
    dele = tuple(sorted(str(r.get("사번", "")).strip() for r in deleted))
    return (tuple(out), dele)


def _assignment_snapshots(q: dict, emp_nos: list) -> dict:
    """대상 월의 부서·조 편성 스냅샷 맵 {emp_no: (dept_code, team_code)}.

    우선순위: 영속 저장(schedule_assignments — migration 002 적용 시)
    → 세션 스냅샷(이번 세션에서 저장 성공한 편성값) 순으로 합친다.
    영속 테이블이 없으면(002 이전) 조회 실패를 무시하고 세션 값만 쓴다.
    """
    snaps = {}
    month_key = f"{q['year']:04d}-{q['month']:02d}"
    cache = st.session_state.get("se_assign_cache", {})
    for (mk, emp), value in cache.items():
        if mk == month_key:
            snaps[emp] = (
                value["dept_code"], value["team_code"], value.get("shift_group_code", ""),
            )
    if emp_nos:
        try:
            assigns = db.get_month_assignments(q["year"], q["month"], emp_nos)
            for _, r in assigns.iterrows():
                snaps[str(r["emp_no"]).strip()] = (
                    str(r["dept_code"]).strip(), str(r["team_code"]).strip(),
                    str(r.get("shift_group_code") or "").strip(),
                )
        except Exception:
            pass  # 002 이전에는 테이블이 없다 — 세션 스냅샷/마스터 기본값 사용
    return snaps


# ---------- 저장 ----------
def _persist_row_order(live: pd.DataFrame) -> tuple[int, str]:
    """드래그로 바뀐 행 순서를 users.display_order 로 영속화한다 (근무 저장 성공 뒤 단계).

    - 로드 시점 순서(se_order_base)와 최종 화면 순서가 같으면 아무것도 쓰지 않는다.
    - 재배정은 부서그룹 단위 슬롯 교환(db.plan_display_order_slots)이라 화면에 없는
      사용자의 번호는 바뀌지 않고, 값이 실제로 달라지는 사용자만 갱신한다.
    - 부서그룹 매핑·유일성 판정은 users 마스터 기준이므로 db.get_users() 전체(퇴사자
      포함)를 넘긴다 — 그룹 최대 번호 계산에 숨은 사용자도 필요하다.
    - 실패해도 예외를 올리지 않고 사유를 돌려준다: 근무 저장은 이미 확정됐고 되돌릴 수
      없다. 여기서 return 해버리면 재조회가 막혀 '저장해도 dirty 가 안 풀리는' 루프가
      된다. 대신 사유를 저장 결과 메시지에 그대로 노출해 실패를 숨기지 않는다.
    반환: (갱신한 사용자 수, 실패 사유 — 성공이거나 대상 없음이면 "").
    """
    base = st.session_state.get("se_order_base")
    if base is None:
        return 0, ""
    final = _visible_emp_order(live)
    if final == list(base):
        return 0, ""
    try:
        pairs = db.plan_display_order_slots(final, db.get_users(), db.dept_group_map())
        if not pairs:
            return 0, ""
        db.update_users_display_order(pairs)
    except Exception as exc:  # 사유를 그대로 보고 — 은폐 금지, 근무 저장은 확정 유지
        return 0, str(exc)
    return len(pairs), ""


def _save(live: pd.DataFrame, q: dict, day_cols: list) -> None:
    """최종 화면 상태 기준 혼합 저장.

    직원별 최종 상태로 분류해 처리한다 (classify_save_targets):
      - delete_only: 삭제 예정 + 재입력 없음 → 해당 월 삭제
      - replace_after_delete: 삭제 예정 + 같은 사번 재입력 → 해당 월을 입력값으로 교체
      - 그 외 행: 변경 셀만 upsert (빈 셀 자동 삭제 없음)
    삭제만 저장하는 경우에는 users/근무형태/부서·조 조회를 실행하지 않는다.
    Repository 는 원자적이지 않으므로 실패 시 단계를 보고하고 초안을 유지한다.
    """
    day_isos = dict(st.session_state.get("se_days", []))
    orig_cells = st.session_state.get("se_orig_cells", {})
    deleted = st.session_state.get("se_deleted", [])
    deleted_emps = sorted({str(r.get("사번", "")).strip() for r in deleted if str(r.get("사번", "")).strip()})

    # 1) 최종 화면 상태 정규화 — 내용이 있는 행만 (완전히 빈 신규 행 제외)
    content_rows = []
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        emp = str(row.get("사번") or "").strip()
        dept_txt = str(row.get("부서") or "").strip()
        team_txt = str(row.get("조") or "").strip()
        day_vals = {
            c: ("" if pd.isna(row.get(c)) else str(row.get(c)).strip()) for c in day_cols
        }
        if not any([emp, dept_txt, team_txt, *day_vals.values()]):
            continue
        content_rows.append((i, row, emp, dept_txt, team_txt, day_vals))

    live_emps = {emp for (_i, _r, emp, *_rest) in content_rows if emp}
    delete_only, replace_after_delete = classify_save_targets(live_emps, deleted_emps)
    replace_set = set(replace_after_delete)

    if not content_rows and not deleted_emps:
        set_flash("schedule_edit", "warning", "저장할 변경 내용이 없습니다.")
        st.rerun()

    # 2) 신규·수정 입력 검증 (삭제만 저장하는 경로에서는 참조 조회를 건너뛴다)
    records_plain, records_replace, errors = [], {}, []
    assign_rows = []  # 편성 저장 대상 (신규 행 또는 부서·조가 로드값과 달라진 행)
    if content_rows:
        display_of, codes, label_codes = _label_maps()
        users = _users_by_emp()  # 조회 시점 캐시 재사용 (rerun 반복 조회 방지)
        depts = db.get_departments()
        # (조 기준정보 조회는 두지 않는다 — 이 화면의 '조'는 자유 입력 근무조다.)
        orig_assign = st.session_state.get("se_orig_assign", {})  # rid -> (dept_code, team_code) 로드 스냅샷
        dept_name_codes = {}
        for _, r in depts.iterrows():
            dept_name_codes.setdefault(str(r["dept_name"]).strip(), set()).add(str(r["dept_code"]).strip())
        dept_codes = set(depts["dept_code"].astype(str).str.strip())
        seen = set()

        for i, row, emp, dept_txt, team_txt, day_vals in content_rows:
            if not emp:
                errors.append(f"{i}행: 사번을 입력하세요.")
                continue
            master = users.get(emp)
            if master is None:
                errors.append(f"{i}행({emp}): 등록되지 않은 사번입니다.")
                continue
            if not bool(master["is_active"]):
                errors.append(f"{i}행({emp}): 재직 중이 아닌 사용자입니다.")
            if emp in seen:
                # 최종 화면에 같은 사번이 2행 이상일 때만 중복 오류
                errors.append(f"{i}행({emp}): 같은 월에 동일 사번이 여러 행입니다.")
            seen.add(emp)

            # 부서·조 편성값 검증 (표시명 또는 코드 입력 허용 → 내부 코드로 확인)
            dept_code = None
            if not dept_txt:
                errors.append(f"{i}행({emp}): 부서를 입력하세요.")
            elif dept_txt in dept_codes:
                dept_code = dept_txt
            else:
                matched = dept_name_codes.get(dept_txt, set())
                if len(matched) == 1:
                    dept_code = next(iter(matched))
                elif len(matched) > 1:
                    errors.append(f"{i}행({emp}): 부서명 '{dept_txt}'이(가) 여러 부서에 해당합니다.")
                else:
                    errors.append(f"{i}행({emp}): 존재하지 않는 부서입니다: {dept_txt}")

            # '조'는 기준정보 조회가 아니라 자유 입력이다(2026-08-07 결정). 마스터에 없는
            # 값이라고 막지 않으며, 한 글자 입력만 'A' → 'A조'로 보정한다.
            shift_code = normalize_shift_group(team_txt)
            # team_code(운영단위)는 이 화면에서 더 이상 편집하지 않는다 — 로드 스냅샷 값을
            # 그대로 실어 보내 과거 배정을 보존한다. 단 **부서를 바꾼 행은 빈 값**으로
            # 해제한다: 팀은 부서 소속이라 옛 부서의 팀 코드를 새 부서에 실으면 검증
            # ("선택한 부서에 없는 팀")이 저장 전체를 영구 차단한다(code-review P1).
            loaded_snap = orig_assign.get(str(row.get("_row_id", "")))
            team_code = str(loaded_snap[1]) if loaded_snap and len(loaded_snap) > 1 else ""
            if team_code and loaded_snap and dept_code is not None \
                    and str(loaded_snap[0]).strip() != str(dept_code).strip():
                team_code = ""

            # 편성 저장 여부 결정 (§편성 저장 조건):
            #  - 신규 직원·월 행 → 저장(새 편성)
            #  - 기존 행 → 로드 스냅샷과 부서·조가 달라졌을 때만 저장(명시적 변경)
            #  - legacy 행 + 근무만 수정 → 저장 안 함 → 근무는 schedule_assignment_id NULL
            # users 현재 소속을 과거 편성으로 자동 각인하지 않는다.
            state = str(row.get("_row_state") or "new")
            loaded = orig_assign.get(str(row.get("_row_id", "")))
            if dept_code is not None and should_save_assignment(
                state, dept_code, shift_code, loaded
            ):
                assign_rows.append({
                    "emp_no": emp,
                    "schedule_month": (q["year"], q["month"]),
                    "dept_code": dept_code,
                    "team_code": team_code,
                    "shift_group_code": shift_code,
                })

            rid = str(row.get("_row_id", ""))
            is_replace = emp in replace_set
            for col, val in day_vals.items():
                if not val:
                    continue
                # 교체 대상은 전체 값을 저장하고, 그 외에는 변경 셀만 저장한다
                if not is_replace and orig_cells.get((rid, col), "") == val:
                    continue
                code = _resolve_work(val, codes, label_codes)
                if code is None:
                    errors.append(f"{i}행({emp}) {col}: 알 수 없는 근무형태 '{val}'")
                    continue
                if code == "AMBIG":
                    errors.append(f"{i}행({emp}) {col}: 약칭 '{val}'이(가) 여러 근무형태에 매핑됩니다.")
                    continue
                rec = {"emp_no": emp, "duty_date": day_isos[col], "work_type_code": code, "note": ""}
                if is_replace:
                    records_replace.setdefault(emp, []).append(rec)
                else:
                    records_plain.append(rec)

    if errors:
        shown = errors[:20]
        more = f"\n- 외 {len(errors) - 20}건" if len(errors) > 20 else ""
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(shown) + more)
        return

    # 빈 칸으로 지운 셀 = 삭제 아님(기존 근무 유지) 안내 (삭제 예정/교체 행 제외)
    cleared = 0
    live_by_rid = {str(r["_row_id"]): r for _, r in live.iterrows()}
    for (rid, col), orig_val in orig_cells.items():
        if not orig_val:
            continue
        row = live_by_rid.get(rid)
        if row is None:
            continue
        now = "" if pd.isna(row.get(col)) else str(row.get(col)).strip()
        if not now:
            cleared += 1

    # 3) 편성(schedule_assignments) 먼저 저장 — work_schedules 가 이 id 를 참조한다.
    #    실패 시 근무 저장을 진행하지 않고(성공 은폐 방지) 초안을 유지한다.
    month_key = f"{q['year']:04d}-{q['month']:02d}"
    assign_persisted = False
    if assign_rows:
        try:
            db.upsert_month_assignments(assign_rows, require_shift=False)
            assign_persisted = True
        except db.DATA_SOURCE_ERRORS as exc:
            st.error(
                "편성(부서·조) 저장 단계에서 실패했습니다. 근무는 저장하지 않았습니다.\n\n"
                f"편집 내용은 화면에 유지됩니다. [새로고침]으로 확인 후 다시 시도하세요.\n\n({exc})"
            )
            return
        except Exception:
            st.error(
                "편성(부서·조) 저장 단계에서 실패했습니다. 근무는 저장하지 않았습니다.\n\n"
                "편집 내용은 화면에 유지됩니다. [새로고침]으로 확인 후 다시 시도하세요."
            )
            return
        cache = st.session_state.setdefault("se_assign_cache", {})
        for rec in assign_rows:
            cache[(month_key, rec["emp_no"])] = {
                "dept_code": rec["dept_code"], "team_code": rec["team_code"],
                "shift_group_code": rec["shift_group_code"],
            }

    # 4~6) 근무 저장 — 삭제 → 교체 → upsert 순. Repository 가 이 저장 payload 의 각
    #      행을 (사용자·월) 편성이 있으면 schedule_assignment_id 로 연결한다(없으면 NULL).
    #      편성이 먼저 저장됐으므로 신규 편성도 연결된다. 원자적이지 않으므로 실패 시
    #      단계를 보고하고 초안을 유지한다(편성이 이미 저장됐으면 부분 성공을 안내).
    step = "삭제"
    try:
        if delete_only:
            db.replace_month_schedules(delete_only, q["year"], q["month"], [])
        step = "삭제 후 재등록(교체)"
        if replace_after_delete:
            replace_records = [
                rec for emp in replace_after_delete for rec in records_replace.get(emp, [])
            ]
            db.replace_month_schedules(replace_after_delete, q["year"], q["month"], replace_records)
        step = "신규·수정 저장"
        if records_plain:
            db.upsert_month_schedules(records_plain)
    except db.DATA_SOURCE_ERRORS as exc:
        prefix = "편성(부서·조)은 저장되었으나, " if assign_persisted else ""
        st.error(
            f"{prefix}근무 저장이 '{step}' 단계에서 실패했습니다. 이전 단계까지는 반영되었을 수 있습니다.\n\n"
            f"편집 내용은 화면에 유지됩니다. [새로고침]으로 실제 저장 상태를 확인한 뒤 다시 시도하세요.\n\n({exc})"
        )
        return
    except Exception:
        prefix = "편성(부서·조)은 저장되었으나, " if assign_persisted else ""
        st.error(
            f"{prefix}근무 저장이 '{step}' 단계에서 실패했습니다. 이전 단계까지는 반영되었을 수 있습니다.\n\n"
            "편집 내용은 화면에 유지됩니다. [새로고침]으로 실제 저장 상태를 확인한 뒤 다시 시도하세요."
        )
        return

    # 월 근무를 삭제한 직원의 세션 스냅샷 정리 (편성 DB 는 건드리지 않음 — assignment-only 허용)
    if delete_only:
        cache = st.session_state.setdefault("se_assign_cache", {})
        for emp in delete_only:
            cache.pop((month_key, emp), None)

    # 7) 행 순서(users.display_order) 저장 — 드래그로 바꾼 시각 순서를 영속화한다.
    #    여기서 쓰지 않으면 바로 아래 재조회(_load_grid)가 옛 표시순서로 다시 정렬해
    #    "저장했는데 순서가 돌아오고 dirty 도 안 풀리는" 루프가 된다.
    order_saved, order_error = _persist_row_order(live)

    n_saved = len(records_plain) + sum(len(v) for v in records_replace.values())
    _load_grid(q)  # 재조회 → 신규 행 existing 전환, DB 편성 재수화, dirty/선택 초기화

    parts = [f"근무 {n_saved}건 저장"]
    if delete_only:
        parts.append(f"{len(delete_only)}명 월 근무 삭제")
    if replace_after_delete:
        parts.append(f"{len(replace_after_delete)}명 월 근무 교체")
    if assign_rows and assign_persisted:
        parts.append(f"편성 {len(assign_rows)}명 저장")
    if order_saved:
        parts.append(f"행 순서 {order_saved}명 반영")
    notes = []
    if order_error:
        notes.append(f"행 순서는 저장하지 못했습니다(근무는 저장됨): {order_error}")
    if cleared:
        notes.append(f"빈 칸으로 지운 {cleared}개 셀은 삭제되지 않고 기존 근무가 유지됩니다.")
    msg = "근무표를 저장했습니다. (" + " · ".join(parts) + ")"
    if notes:
        msg += "\n\n" + "\n".join(f"- {n}" for n in notes)
    set_flash("schedule_edit", "warning" if notes else "success", msg)
    st.rerun()
