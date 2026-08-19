"""기준정보 — 조직 관리: 부서 단일 시트 + 계층 텍스트 2단(대분류/중분류).

부서 관리·조 관리 메뉴는 모두 이 화면을 연다 (사이드바 메뉴 구조는 무변경).

2026-08-07 사용자 결정으로 그룹·조(운영단위) 시트를 폐지했다: A/B/C 교대조는 기준정보가
아니라 근무편성표에서 직접 입력하고(schedule_assignments.shift_group_code), 조직 계층은
부서 행의 **대분류/중분류 자유 텍스트 2단**(migration 009)으로 사람이 직접 입력한다.
현장 조직은 담당/부/팀/파트 깊이가 부서마다 달라 고정 관계 모델(그룹 FK 드릴다운)이
매번 재구성을 강요했기 때문이다. organization_groups·teams 테이블과 데이터는 보존되며
(009 는 drop 하지 않음), 기존 group_id 귀속은 저장 시 그대로 유지된다(_save_depts 의
스토어 백필 — 화면이 그룹을 편집하지도, 지우지도 않는다).

부서 시트 계약:
  - 컬럼: 대분류 / 중분류 / 코드 / 코드명 / 근태 등록 대상 / 순서 / 비고 / 사용.
    중분류는 대분류 없이 쓸 수 없다(DB departments_minor_requires_major 와 동일 규칙을
    저장 전 검증).
  - **근태 등록 대상**(departments.tracks_attendance · migration 011)은 근무표를 실제로
    편성·등록하는 부서만 체크하는 지정 열이다. 편성·월간 근무표·대시보드가 이 값으로
    조직 목록을 좁히며(집행: ``db.attendance_dept_codes``), 신규 행 기본값은 **미지정**
    이다(명시 지정 원칙 — requirements §6 · migration 011 컬럼 기본값과 같은 방향).
    이 열은 반드시 **보이는 편집 열**이어야 한다: 그리드가 값을 왕복시키지 않으면 저장
    배치가 지정을 싣지 못해 전 부서 지정이 풀릴 수 있고, 그 사고는 지금 저장 계층
    (``db._org_dept_write_frame`` · ``supabase_repository._departments_org_payload``)이
    "값 없으면 기존값 유지"로 막고 있을 뿐이다. 숨김 컬럼으로 두지 않는다.
  - 행 추가·삭제·저장·새로고침의 진입점은 **상단 52px 헤더 아이콘 하나뿐**이다
    (2026-08-14 사용자 지시 · DESIGN §0-3 "아이콘 툴바는 최상단 헤더 바 안에만").
    인페이지 액션바(master_action_bar)는 이 시트에서 제거했고, 활성/음영·툴팁 사유는
    종전과 같은 순수 규칙(page_action_specs)이 계산해 헤더에 발행한다 — 계산 원천이
    하나라 두 진입점 시절의 불일치 여지가 없다. 클릭 플래그(`org_dept:action:*`)와
    실행 경로(확인 게이트·저장·재적재)는 무변경이다.
  - page-scoped DraftState = ``org_dept``(_OD). dirty draft 상태에서 필터를 바꾸면
    폐기/계속 게이트를 태운다.
  - 저장된 코드는 수정 불가(신규 등록 시에만 입력), 저장 실패 시 draft 를 보존한다.
  - 저장 전 신규행 삭제 = 즉시 제거, 저장행 삭제 = 참조 확인 후 미사용/삭제.
  - ADMIN 부서는 코드수정·미사용처리 등 화면 보호(_protected).

그룹(_GRP)·조(_OU) 시트의 함수·CSS 는 소스에 보존되어 있으나 render() 에서 호출되지
않는다 — 교차 화면 테스트가 참조하는 순수 함수(build_*_rows/_validate_* 등)와 되돌림
가능성 때문이다. 완전 제거 시점은 BACKLOG 에서 추적한다.

공통 기반 패키지(``views/master``)의 계약(DraftState/MasterGridSpec/run_save/
ReadinessState/master_action_bar/ledger_banner/sheet_head/sheet_locked/
drilldown_context/공통 style)을 그대로 사용하고, 조직 스키마 capability(도입: migration 004)
미준비 시 저장을 차단(UI + repository 이중 방어)한다.

순수·도메인 함수(``build_group_rows``/``build_dept_rows``/``build_team_rows``/
``_validate_groups``/``_validate_depts``/``_validate_units``/``_unit_structure_errors``/
``_group_structure_errors``)는 계약 테스트 대상이라 UI 없이 단위 검증 가능하다.
그중 ``_validate_units``/``_unit_structure_errors``/``_group_structure_errors`` 는
교차 화면 회귀 테스트가 참조하는 시그니처라 보존한다.
"""
# DESIGN.md §0 화면 유형 규약 — 기준정보 편집형.
SCREEN_ARCHETYPE = "EDIT_GRID"

from html import escape

import pandas as pd
import streamlit as st
from st_aggrid import JsCode

from modules import db
from views.common import erp
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
    chip_html,
    confirm_bar,
    count_strip,
    dirty_total,
    discard_confirm_bar,
    drilldown_context,
    empty_state,
    grid_bool,
    header_actions_from_specs,
    icon_toolbar_specs,
    ledger_banner,
    live_rows,
    master_action_bar,
    master_grid_height,
    mode_badge_html,
    page_action_specs,
    render_master_grid,
    run_save,
    sheet_head,
    sheet_locked,
    show_flash,
)

_STATUS = ["사용 중", "사용 안 함", "전체"]

# 세 시트의 page-scoped 편집 상태. page_id 는 공통 액션바 버튼 키(`{page_id}__{role}`)와
# 공용 CSS 부분일치 선택자(`[class*="__save"]` 등)의 스코프이기도 하다. 부서=org_dept,
# 조=org_unit 은 기존 교차 화면 계약(버튼 키·소스 심볼)을 그대로 유지하는 이름이다.
_GRP = DraftState("org_group")  # 그룹(organization_groups)
_OD = DraftState("org_dept")    # 부서(선택 그룹의 departments)
_OU = DraftState("org_unit")    # 조(선택 부서의 teams = 운영단위)

# 조직 스키마 capability(도입: migration 004) 미준비/probe 실패 배너 문구(계약: 소스에 1회).
_NOT_READY_MSG = "조직 스키마가 준비되지 않아 조회만 가능하며 저장은 차단됩니다."
_PROBE_ERROR_MSG = "조직 스키마 상태 확인 실패 — 재확인이 필요합니다 (조회만 가능하며 저장은 차단됩니다)."

_SYSTEM_CODES = {"ADMIN"}  # 화면 보호 대상(코드수정·미사용·삭제 차단)

# 조직 액션바 비율 — [행 추가][삭제][저장] · 스페이서 · [새로고침].
# 2026-08-14 이후 라우팅되는 부서 시트는 인페이지 액션바를 쓰지 않는다(액션=상단 헤더
# 아이콘 단일 진입점). 이 비율은 미라우팅 보존 시트(그룹·조) 호출부만 사용한다.
# 구 값 (1.28,1.0,1.12,0.2,1.42) 은 시트가 화면의 1/3 폭이던 3분할 시절 값이라, 2026-08-07
# 단일 시트(전폭) 전환 뒤에는 스페이서(0.2)가 거의 없어 버튼이 1440px 에서 220~315px 로
# 부풀었다(실측). 사용자·근무형태 관리의 액션 열 비율(1.15/1.05/1.35/1.15)과 같은
# 스케일로 되돌려 세 화면 버튼 폭을 통일한다(≈130px @1440).
_ORG_BAR_RATIOS = (1.15, 1.05, 1.35, 5.15, 1.15)

# 공통 컬럼(그룹·부서 시트). field 명이 곧 표시 헤더다.
_GROUP_COLS = ["코드", "코드명", "순서", "비고", "사용"]
_GROUP_ROW_COLS = ["_row_id", "_row_state", "_sel", *_GROUP_COLS]
_GROUP_GRID_COLUMNS = {"코드": "text", "코드명": "text", "순서": "text", "비고": "text", "사용": "bool"}

# 부서 시트 — 대분류/중분류는 사람이 직접 입력하는 조직 계층 2단(migration 009).
# 그룹 시트 폐지(2026-08-07 사용자 결정)로 계층 표현이 이 두 칸으로 넘어왔다.
#
# 근태 등록 대상(migration 011) 열의 **라벨·위치**:
#   * 라벨은 requirements §6·docs/database.md 의 정본 용어 "근태 등록 대상" 그대로 쓴다
#     (화면 전용 약어를 새로 만들지 않는다 — 칩·안내 문구도 같은 말을 쓴다).
#   * 위치는 코드명 다음, 순서·비고·사용 앞이다. 근거 두 가지:
#     (1) 근무형태 관리(_USER_COLS: …약칭·시작·종료·색상·**실근무·특근수당**·설명·표시순서·
#         사용)와 같은 배치 규칙 — 도메인 boolean 은 식별 열 뒤 속성 자리에 두고, 레코드
#         수명 상태인 `사용`(is_active)은 어느 기준정보 화면에서도 **마지막 열**로 고정한다.
#     (2) 편집 안전 — `사용` 바로 옆에 두면 같은 모양의 체크박스 두 개가 붙어 오클릭이
#         곧 "부서가 근무표에서 사라짐"이 된다. 순서·비고가 사이에 있어 두 토글이 섞이지
#         않고, 읽는 순서도 "부서명 → 근태 등록 대상?"이라 스캔 동선과 맞는다.
_ATTENDANCE_COL = "근태 등록 대상"
_DEPT_COLS = ["대분류", "중분류", "코드", "코드명", _ATTENDANCE_COL, "순서", "비고", "사용"]
_DEPT_ROW_COLS = ["_row_id", "_row_state", "_sel", *_DEPT_COLS]
_DEPT_GRID_COLUMNS = {
    "대분류": "text", "중분류": "text", "코드": "text", "코드명": "text",
    _ATTENDANCE_COL: "bool", "순서": "text", "비고": "text", "사용": "bool",
}

# 조 시트 — field 명은 교차 화면 테스트가 참조하는 ``_validate_units`` 의 키(명칭/표시순서)를
# 유지하고, 표시 헤더만 다른 시트와 통일(코드명/순서)한다. 유형 컬럼이 추가된다.
_UNIT_COLS = ["코드", "명칭", "유형", "표시순서", "비고", "사용"]
_UNIT_ROW_COLS = ["_row_id", "_row_state", "_sel", *_UNIT_COLS]
_UNIT_GRID_COLUMNS = {
    "코드": "text", "명칭": "text", "유형": "text", "표시순서": "text", "비고": "text", "사용": "bool",
}

# 유형 입력 정규화 — 화면 표시값(교대/일반)과 내부값(SHIFT/GENERAL) 모두 허용.
_UNIT_TYPE_OF = {"교대": "SHIFT", "일반": "GENERAL", "SHIFT": "SHIFT", "GENERAL": "GENERAL"}

# 저장된 코드는 수정 불가 — 신규 행에서만 코드 입력을 허용한다.
_EDIT_NEW_ONLY = JsCode("function(p){ return !!(p.data && p.data._row_state === 'new'); }")
# 보호 행(ADMIN)은 코드 외 셀도 편집 불가(미사용·재귀속 차단, 화면 보호).
_EDIT_UNLESS_PROTECTED = JsCode(
    "function(p){ return !(p.data && (p.data._protected === '1' || p.data._protected === 1)); }"
)
# 선택된 상위 행은 공통 ``ms-row-linked`` 행 강조(네이비 틴트)로만 표시한다 — 코드명 옆
# 코드명 옆에 붙던 별도 '열림' 표시 칩은 상단 브레드크럼·헤더 컨텍스트와 중복돼 제거한다(ERP).
# 행 강조는 spec ``include_linked_rows`` + ``_linked`` 플래그로 구동되므로 칩 없이도 유지된다.

# 조직 전용 페이지 크롬 — 공통 크롬(views/master/style)을 소비만 하고, 이 화면 고유의
# Wave B 폴리시만 페이지 스코프로 얹는다:
#   (1) 선택 컨텍스트·계층(그룹›부서›조) 통합 브레드크럼 강조(.ms-ctx),
#   (2) 활성/잠김 상태 표시(활성 시트 상단 네이비 액센트 + 잠긴 시트 디엠퍼시스) —
#       계층 순서는 (1) 브레드크럼이 표현하므로 단계 배지·커넥터 장식은 두지 않는다,
#   (3) 잠김 상태 밀도 완화(슬림 플레이스홀더 + 잠긴 시트의 비활성 액션바 숨김 →
#       시트별 액션바 반복 소음 축소), (4) 저장코드 읽기전용 어포던스는 공통 .ms-cell-readonly
#       클래스를 col_config cellClassRules 로 소비.
# 3시트 세로 스택(≤1100px)은 공통 style 의 `stHorizontalBlock:has([class*="__sheet"])` 규칙.
_ORG_PAGE_CSS = """
<style>
/* 시트 안 버튼 nowrap — 부서 시트는 액션바를 폐지(액션=상단 헤더 아이콘)했으므로 이제
   폐기/삭제 확인 바 버튼에 적용되고, 미라우팅 보존 시트(그룹·조)의 4버튼 라벨도 유지한다.
   (후손 셀렉터라 disabled 래퍼도 커버) */
.st-key-org_group__sheet div.stButton button,
.st-key-org_dept__sheet div.stButton button,
.st-key-org_unit__sheet div.stButton button {
  white-space:nowrap; min-width:0; overflow:visible; text-overflow:clip; }

/* §1-E: 3시트 카드 박스 제거 → 세로 헤어라인으로 나눈 3열(카드 아님). 공용 [class*="__sheet"]
   카드 스타일(배경·테두리·radius·그림자)을 로컬 오버라이드로 걷어낸다(shared 무수정, 소스
   순서·특이도로 이김). 2·3열은 좌측 세로 헤어라인(#cfc8bd)으로만 구분한다. */
.st-key-org_group__sheet, .st-key-org_dept__sheet, .st-key-org_unit__sheet {
  background:transparent !important; border:none !important; border-radius:0 !important;
  box-shadow:none !important; padding:4px 12px !important; }  /* §1.1 스케일(구 .2rem/.9rem/.1rem = 2.8/12.6/1.4px) */
/* 단일 시트가 된 부서 시트는 좌우 안쪽 여백을 두지 않는다 — 위 규칙의 좌우 12px + 바깥
   `org__sheets` 의 공용 카드 패딩·1px 테두리가 겹쳐 표·상태 스트립만 제목·조건 줄보다
   14.5px 안으로 들어가 있었다(2026-08-14 실측 x 268.5 vs 253.5). 사용자·근무형태 화면은
   같은 자리에서 253.5 라 세 화면의 좌측 기준선이 어긋났다. 3열 시절의 잔재이므로
   부서 시트에서만 걷고, 미라우팅 보존 시트(그룹·조)의 여백 규칙은 위 선언 그대로 둔다.
   바깥 래퍼 `org__sheets` 는 이름에 "__sheet" 가 들어가 공용 카드 규칙
   (views/master/style.py `[class*="__sheet"]`)에 **의도치 않게** 걸려 흰 배경+테두리+
   radius+그림자를 뒤집어쓰고 있었다 — §0-5(카드로 섹션 감싸기 금지)에 어긋나고
   사용자·근무형태 화면에는 없는 상자라 같이 걷는다. */
.st-key-org__sheets {
  background:transparent !important; border:none !important; border-radius:0 !important;
  box-shadow:none !important; padding:0 !important; }
  /* 상하 패딩도 0 으로 — 공용 `[class*="__sheet"]`(views/master/style.py:434) 이 이 래퍼에도
     .2rem/.1rem(2.8/1.4px)을 얹어 §1.1 스케일 밖 여백이 남아 있었다(실측). 안쪽 부서
     시트가 이미 4px 을 갖고 있으므로 래퍼는 0 이 맞다. */
.st-key-org_dept__sheet { padding-left:0 !important; padding-right:0 !important; }
/* 단일 시트 전환(2026-08-07) — 부서 시트는 더 이상 2열이 아니므로 좌측 헤어라인을 걷는다.
   (조 시트 규칙은 미라우팅 보존 코드용으로만 남김) */
.st-key-org_unit__sheet {
  border-left:1px solid #cfc8bd !important; }
/* 잠긴(상위 미선택) 하위 시트 — dashed 카드 제거, 세로 헤어라인만 유지 + 디엠퍼시스 */
.st-key-org_dept__sheet.ms-sheet-locked, .st-key-org_unit__sheet.ms-sheet-locked {
  background:transparent !important; border-style:none !important;
  border-left:1px solid #cfc8bd !important; }
.st-key-org_dept__sheet:has(.ms-locked), .st-key-org_unit__sheet:has(.ms-locked) { opacity:.72; }

/* ── DRILL 스트립(§1-E): 그룹›부서›조 — 선택=오렌지 틴트 칩, 미선택=중립. 카드 아님(하단 헤어라인). ── */
.ms-ctx { padding:.5rem .2rem .6rem; margin:.1rem 0 .5rem; background:transparent !important;
  border:none !important; border-bottom:1px solid #e0dbd2 !important; border-radius:0 !important;
  box-shadow:none !important; font-size:.8rem; }
.ms-ctx > span:first-child { font-family:'IBM Plex Mono',monospace; font-weight:600;
  letter-spacing:.12em; text-transform:uppercase; font-size:.62rem; color:#6b665d; }
.ms-ctx b { padding:.14rem .55rem; border-radius:7px; background:#f2f0ec; border:1px solid #e4e0d8;
  color:#5c564d; font-weight:600; }
.ms-ctx b.pin, .ms-ctx b.sel { background:#fdf3ec; border-color:#f0dfd0; color:#b4451a; }
.ms-ctx .arw { font-size:.92rem; color:#cfc8bd; }
.ms-ctx .none { font-style:normal; color:#6b665d; }

/* ── 건수 행 타이포를 기준정보 3화면 공통값으로 맞춘다(2026-08-14 재검수) ──
   이 화면만 공용 `sheet_head`(.ms-sheet-head)를 쓰는데 그 정의는 rem 기반이라 이 앱의
   root(14px)에서 제목 12.88px/700 · 건수 9.8px 로 떨어져, 같은 자리의 사용자 관리
   (.mu-crow 14px/600 + 12px/600 모노 pill)·근무형태 관리(.wt-crow 동일)와 크기가
   달랐다(§0-6 라벨 11px 이하 금지 위반 포함). 공용 정의는 소유 밖이라 이 페이지
   스코프에서만 같은 값으로 덮는다 — 구조·문구·계약은 그대로다. */
/* 세로 간격·gap 은 §1.1 스케일(4·8·12·16·24·32·40)만 쓴다. 구 값 .55rem/.5rem/10px
   (=7.7/7/10px)은 스케일 밖이었다. */
.ms-sheet-head { padding:8px 0; gap:8px; }
.ms-sheet-head .t { font-size:14px; font-weight:600; }
.ms-sheet-head .cnt { font-family:'IBM Plex Mono',monospace; font-size:12px; font-weight:600;
  padding:4px 8px; border-radius:999px; background:#f1eee8; color:#4a453d;
  border:none; font-variant-numeric:tabular-nums; }
/* 상태·필터 칩도 근무형태 관리와 같은 12px/600 로 올린다(공용 .ms-chip 은 9.52px 로 렌더). */
.ms-chip { font-size:12px; padding:4px 8px; gap:4px; font-variant-numeric:tabular-nums; }

/* 잠김 상태 밀도 완화(기능 보존) — 슬림 플레이스홀더 + 잠긴 시트 액션바 숨김. */
.st-key-org_dept__sheet .ms-locked, .st-key-org_unit__sheet .ms-locked {
  min-height:118px; padding:1.25rem 1rem; gap:.35rem; }
.st-key-org_dept__sheet .ms-locked .glyph, .st-key-org_unit__sheet .ms-locked .glyph { font-size:1.1rem; }
.st-key-org_dept__sheet:has(.ms-locked) div[data-testid="stHorizontalBlock"]:has(.st-key-org_dept__save),
.st-key-org_unit__sheet:has(.ms-locked) div[data-testid="stHorizontalBlock"]:has(.st-key-org_unit__save) {
  display:none !important; }
</style>
"""

# 행 클릭 드릴다운 — 데이터 셀 클릭 시 저장된 상위 행을 단일 선택(_linked)으로 표시한다.
# _action 열(선택 체크박스/− 제거)의 기존 동작은 그대로 보존하고, 데이터 셀 클릭에서만
# 이 행을 '열린 상위'로 표시한다: 다른 노드의 _linked 를 지우고 클릭 노드에 '1' 을 쓴다
# → cellValueChanged 가 발생해 Python 이 안정 코드키(코드 컬럼)를 읽어 선택을 갱신한다.
# 신규/draft 행·편집 중·이미 선택된 행은 양보해(편집·붙여넣기와 충돌 없음) rerun 을
# 유발하지 않는다.
_DRILL_CLICK = JsCode(
    """
    function(e) {
      var colId = e.colDef && e.colDef.field;
      var d = (e.node && e.node.data) || {};
      var t = e.event && e.event.target;
      if (colId === '_action') {                       // 선택/제거 열 — 기존 동작 보존
        if (!t || !t.classList) { return; }
        if (t.classList.contains('md-act-rm')) {
          e.node.setDataValue('_removed', '1');
        } else if (t.classList.contains('md-act-cb')) {
          if (d._protected === '1' || d._protected === 1) { return; }
          e.node.setDataValue('_sel', !!t.checked);
        }
        return;
      }
      if (d._row_state !== 'existing') { return; }      // 신규/draft 행은 드릴다운 대상 아님
      if (e.api.getEditingCells && e.api.getEditingCells().length > 0) { return; }  // 편집 중 양보
      if (d._linked === '1' || d._linked === 1) { return; }  // 이미 선택된 행 → 무변경
      e.api.forEachNode(function(node) {
        var nd = node.data || {};
        var want = (node === e.node) ? '1' : '';
        if (String(nd._linked || '') !== want) { node.setDataValue('_linked', want); }
      });
    }
    """
)


def render(user: dict) -> None:
    # 화면 설명(§6 카피 — 담백한 실무체 2문장). 계층 두 칸이 자유 입력이라는 사실은
    # 괄호로 압축하고, 새로 생긴 지정 열의 **결과**(근무표에 나타나는 부서가 달라진다)를
    # 한 문장으로 알린다 — 열 이름만으로는 파급을 알 수 없기 때문이다.
    _ORG_DESC = (
        "부서를 대분류·중분류(직접 입력)로 묶어 관리합니다. "
        "근태 등록 대상으로 지정한 부서만 근무표 편성·조회에 나타납니다."
    )
    # §1-E 표형(구조 교체) — 본문 아이콘 밴드 없음(§0-3 "아이콘 툴바는 최상단 헤더 바
    # (52px) 안에만"). 추가·삭제·저장·새로고침은 그 헤더 아이콘이 유일한 진입점이고
    # (2026-08-14 사용자 지시), 화면은 활성/음영 규칙만 발행한다 — 저장·삭제 실행 경로와
    # 확인 게이트는 종전 그대로다.
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="조직 관리",
        desc=_ORG_DESC,
        breadcrumb="기준정보 › 조직 관리",
    )
    st.markdown(_ORG_PAGE_CSS, unsafe_allow_html=True)

    readiness = _readiness()
    readiness.banner()  # NOT_READY/PROBE_ERROR 만 배너, READY 는 모드/스키마 배지로만.
    if readiness.state is Readiness.PROBE_ERROR:
        if st.button("스키마 재확인", key="org__recheck", icon=":material/refresh:"):
            db.reset_org_schema_cache()
            st.rerun()

    # 새로고침 의도는 렌더 시작에서 소비(재적재 판단). 나머지 액션은 그리드 렌더 뒤 소비.
    refresh_dept = _OD.take_action(REFRESH)
    _drop_stale_dept_draft()  # 컬럼 계약이 바뀐 코드로 갱신된 세션의 옛 draft 폐기

    cond = erp.condition_panel(
        "org",
        [
            erp.Field(key="active", label="사용 여부", kind="select", options=_STATUS,
                     widget_key="og_active", width=150),
            erp.Field(key="search", label="검색", kind="text",
                     widget_key="og_search", placeholder="코드·명칭 검색"),
        ],
        # §0.6 컨트롤 폭 내용 맞춤 — 기준정보 3화면 동일(근무형태 관리와 같은 설정).
        content_fit=True,
    )
    filt = {"active": cond["active"], "search": str(cond["search"]).strip()}

    # 부서 로드(필터 변경/새로고침/최초). dirty draft 는 폐기 확인 게이트를 탄다.
    d_params = dict(filt)
    if _OD.resolve_reload(d_params, refresh=refresh_dept, dirty=_OD.is_dirty()) == RELOAD:
        st.session_state.pop(_OD.delete_plan_key, None)
        _load_depts(d_params)

    with st.container(key="org__sheets"):
        with st.container(key="org_dept__sheet"):
            dept_grid = _render_dept_sheet(d_params, readiness)

    # 버튼 클릭 처리 (최신 grid 데이터 기준 — 시트 렌더 이후, page-scoped flag).
    if dept_grid is not None and not _OD.has_pending_reload():
        if _OD.take_action(ADD):
            _add_dept_row(dept_grid)
        if _OD.take_action(DELETE):
            _plan_dept_delete(dept_grid, d_params)
        if _OD.take_action(SAVE):
            _save_depts(dept_grid, d_params)
    elif dept_grid is not None:
        # 폐기 확인 게이트가 떠 있는 동안 들어온 쓰기 의도는 **소비하지 않고 버린다**.
        # 종전에는 소비도 하지 않아 flag 가 세션에 남았고, 게이트를 해소한 다음 rerun 에서
        # 뒤늦게 발화할 수 있었다(사용자가 누른 적 없는 시점의 저장·삭제). 게이트 중에는
        # 헤더 아이콘이 음영이라 정상 경로에서는 설 수 없는 상태지만, 음영 판정이 1 rerun
        # 늦게 반영되는 구간을 fail-closed 로 막는다(_publish_header_actions 의 따라잡기와
        # 별개인 이중 방어 — 헤더 아이콘은 클릭 시점의 음영만 보장할 수 있다).
        _OD.clear_actions(ADD, DELETE, SAVE)

    if dept_grid is not None and _sync_rows(_OD, dept_grid, _DEPT_ROW_COLS):
        st.rerun()

    # 헤더 아이콘 따라잡기(_publish_header_actions 주석 참조) — 액션 소비·구조 동기화가
    # 모두 끝난 뒤 마지막에 한 번만. 이 시점에는 이번 런의 쓰기 의도가 이미 처리됐으므로
    # 재실행이 클릭을 삼키지 않는다.
    if st.session_state.pop(_HDR_RESYNC_KEY, False):
        st.rerun()


# ---------- 헤더 배지 · readiness ----------
def _head_badges() -> str:
    """§5 모드 배지(데이터 연결) + §25 readiness 배지(스키마 준비) — 색·의미 분리."""
    readiness = _readiness()
    badges = ""
    if not readiness.write_enabled:
        badges += readiness.badge_html()
    badges += mode_badge_html(connected=True, sample=db.is_sample_mode())
    return badges


def _attendance_ready() -> bool:
    """근태 등록 대상 지정을 실제로 **저장**할 수 있는 환경인가(migration 011 적용 여부).

    조회는 미적용 환경에서도 전 부서 True 로 폴백하지만(db.attendance_dept_codes 계약),
    "대상 아님" 지정의 저장은 fail-closed 다. 그래서 이 화면은 미준비면 해당 열을
    읽기전용으로 내리고 사유 칩을 붙인다 — 저장 실패로 알려주는 대신 미리 막는다.
    """
    try:
        return bool(db.attendance_flag_ready())
    except db.DATA_SOURCE_ERRORS:
        return False


def _readiness() -> ReadinessState:
    """migration 004 적용 상태를 3-state(READY/NOT_READY/PROBE_ERROR)로 매핑한다."""
    state = db.org_schema_readiness()
    if state == db.READINESS_READY:
        return ReadinessState.ready()
    if state == db.READINESS_PROBE_ERROR:
        return ReadinessState.probe_error(_PROBE_ERROR_MSG)
    return ReadinessState.not_ready(_NOT_READY_MSG)


# ---------- 행 클릭 드릴다운 선택(안정 코드키, 저장된 행만) ----------
# 선택은 상단 컨트롤이 아니라 표 행 클릭으로 정하며, 안정 코드키로 아래 session_state
# 에 보관한다(행 인덱스·표시명 키 금지). 저장된 행이 사라지면(삭제·필터) 자동 해제한다.
_GROUP_SEL_KEY = "og_group_sel"
_DEPT_SEL_KEY = "og_dept_sel"


def _name_by_code(df: pd.DataFrame, code_col: str, name_col: str, code: str) -> str | None:
    """저장 프레임에서 코드로 표시명을 찾는다. 없으면 None(=선택 해제 신호)."""
    if df is None or df.empty:
        return None
    match = df[df[code_col].astype(str).str.strip() == str(code).strip()]
    if match.empty:
        return None
    return str(match.iloc[0][name_col])


def _resolve_group_selection() -> tuple[str, str]:
    """행 클릭으로 정한 그룹 선택을 저장된 그룹과 대조해 (코드, 이름)으로 확정한다.

    선택된 그룹이 더 이상 존재하지 않으면(삭제 등) 선택과 하위(부서) 선택을 함께 비운다.
    """
    code = str(st.session_state.get(_GROUP_SEL_KEY, "") or "").strip()
    if not code:
        return "", ""
    name = _name_by_code(db.get_org_groups(), "group_code", "group_name", code)
    if name is None:
        st.session_state.pop(_GROUP_SEL_KEY, None)
        st.session_state.pop(_DEPT_SEL_KEY, None)
        return "", ""
    return code, name


def _resolve_dept_selection(group_code: str) -> tuple[str, str]:
    """선택 그룹에 종속된 부서 선택을 확정한다. 그룹 미선택이면 부서 선택을 비운다.

    선택된 부서가 현재 그룹의 부서가 아니면(그룹 변경·삭제) 부서 선택을 해제한다.
    """
    if not group_code:
        st.session_state.pop(_DEPT_SEL_KEY, None)
        return "", ""
    code = str(st.session_state.get(_DEPT_SEL_KEY, "") or "").strip()
    if not code:
        return "", ""
    name = _name_by_code(db.get_org_departments(group_code=group_code), "dept_code", "dept_name", code)
    if name is None:
        st.session_state.pop(_DEPT_SEL_KEY, None)
        return "", ""
    return code, name


def _picked_code(grid_df: pd.DataFrame) -> str | None:
    """그룹/부서 그리드 반환에서 클릭으로 열린(=_linked) 저장 행의 코드를 읽는다.

    행 클릭 시 _DRILL_CLICK 이 클릭 노드에만 _linked='1' 을 쓰고 나머지를 지운다. 여기서
    그 안정 코드키(코드 컬럼)를 돌려준다 — 클릭·선택이 없으면 None. 클릭이 없을 때는
    Python 이 현재 선택 행에 계산한 _linked 와 동일하므로 controller 에서 무변경으로 판정된다.
    """
    if grid_df is None or "_linked" not in grid_df.columns or "코드" not in grid_df.columns:
        return None
    linked = grid_df[
        (grid_df["_row_state"].astype(str) == "existing")
        & (grid_df["_linked"].astype(str).str.strip() == "1")
    ]
    if linked.empty:
        return None
    return str(linked.iloc[0]["코드"]).strip()


# ---------- 공통 시트 헬퍼 ----------
def _flag(cond) -> str:
    return "1" if bool(cond) else ""


def _plan_codes(plan) -> set:
    """그룹·부서 삭제 계획의 대상 코드(삭제+미사용) — _delete 시각용."""
    if not plan:
        return set()
    codes = set(plan.get("delete", []))
    codes |= {item["code"] for item in plan.get("deactivate", []) if "code" in item}
    return codes


# 저장된 코드(=신규 아님)는 수정 불가 — 공통 .ms-cell-readonly(Wave A) 로 읽기전용
# 어포던스(중립 틴트 + 기본 커서)를 준다. 상태 행 배경(!important)이 우선하므로 선택/신규/
# 삭제/오류 시각과 충돌하지 않는다(색만으로 상태 표시 금지 계약 유지).
_CODE_READONLY_RULES = {"ms-cell-readonly": "data._row_state !== 'new'"}


def _code_name_config() -> dict:
    """그룹 시트 컬럼 설정(코드=신규만·코드명·순서/비고/사용).

    폭은 12px Pretendard 기준 역산이다(2026-08-19 재산정 — 규칙은 _dept_col_config 주석):
    필요폭 = max(값 실측 최대 잉크, 헤더 실측 잉크) + 16 → 4의 배수. 지정 폭은 고정폭이
    아니라 **비율**이고 남는 폭은 fitGridWidth 가 이 비율대로 나눈다. flex 는 남는 폭을 한
    열에 몰아주므로 쓰지 않는다.
    """
    return {
        # 코드 48 = 코드 표본 최대 'PET1' 30.02x1.05 + 16.
        "코드": {"width": 48, "minWidth": 48, "cellClass": "md-c-left",
                "editable": _EDIT_NEW_ONLY, "cellClassRules": dict(_CODE_READONLY_RULES)},
        # 코드명 120 = 'PET생산부(원료실)' 97.58x1.05 + 16. 행을 특정하는 열이라 상한 없음.
        "코드명": {"width": 120, "minWidth": 120, "cellClass": "md-c-left",
                 "editable": _EDIT_UNLESS_PROTECTED},
        # 순서·사용 40 = 헤더 2글자 22.09x1.05 + 16. 값(정수·체크박스)이 헤더보다 좁아
        # 넓혀도 담을 것이 없다 → maxWidth 로 묶는다.
        "순서": {"width": 40, "minWidth": 40, "maxWidth": 40,
                "cellClass": "md-c-center ms-num", "editable": _EDIT_UNLESS_PROTECTED},
        # 비고 40 = 헤더 하한. sample 에 값이 0건이라 이 화면 안에 역산 재료가 없다
        # (실데이터가 들어오면 다시 재서 갱신). 남는 폭은 fitGridWidth 가 비례로 얹어 준다.
        "비고": {"width": 40, "minWidth": 40, "cellClass": "md-c-left",
                "editable": _EDIT_UNLESS_PROTECTED},
        "사용": {"width": 40, "minWidth": 40, "maxWidth": 40,
                "cellClass": "md-c-center", "editable": _EDIT_UNLESS_PROTECTED},
    }


def _dept_col_config(*, attendance_editable: bool = True) -> dict:
    """부서 단일 시트(전폭) 컬럼 설정 — 2026-08-07 단일 시트 전환 후 전용.

    ``attendance_editable=False`` (근태 대상 지정 스키마 미준비)면 그 열만 읽기전용으로
    내린다 — 저장이 fail-closed 로 막히는 편집을 눌러보게 두지 않는다(§17 편집 안전).
    값은 그대로 보여 준다(폴백 = 전 부서 대상).

    ── 열 폭 = 12px Pretendard 기준 역산(2026-08-19 재산정) ──
    종전 값(코드 108 · 코드명 136 …)은 셀 14.5px·헤더 12.5px 기준이라 DESIGN §1.2 개정
    (표 = `table` 역할 12px) 뒤에는 전부 과대하다. 규칙:

        필요폭 = max(값 실측 최대 잉크, 헤더 실측 잉크) + 16  → 4의 배수로 올림

    16 = 셀 좌우 패딩 7+7 + 보더 2(헤더는 8+8). 잉크는 그리드 iframe 안에서 셀·헤더의
    computed style 을 복사한 hidden span 으로 쟀고, 측정값에 5% 여유를 얹었다 — 이 iframe 은
    지금 Pretendard 를 받지 못해 sans-serif 폴백(한글 10.53px/자)으로 그려지므로, 글꼴이
    정상화되면(11.04px/자) 폴백 기준 폭은 그대로 잘린다.

    **지정 폭은 고정폭이 아니라 비율이다.** 남는 폭은 fitGridWidth 가 이 비율대로 나눈다.
    그래서 flex 를 쓰지 않는다 — flex 는 남는 폭을 내용이 아니라 "남은 자리"로 한 열에
    몰아주고, 값이 한 건도 없는 열이 화면에서 가장 넓어지는 원인이었다(2026-08-18 실측:
    대분류 162 · 중분류 162 · 비고 180, 세 열 모두 전 행 값 잉크 0).
    """
        # minWidth = width: fitGridWidth 는 뷰포트가 좁으면 열을 **minWidth 까지 줄여서**
        # 맞춘다(실측 390px: 코드명 120→96 으로 눌려 값이 잘렸다). 역산한 필요폭이 곧
        # 하한이므로 둘을 같은 값으로 둔다 — 좁은 폭에서는 줄이지 말고 가로 스크롤한다.
    attendance = {
        # 96 = 헤더 '근태 등록 대상' 72.92x1.05 + 16. 값은 체크박스(16px)라 헤더가 폭을
        # 지배하고, 넓혀도 담을 것이 없으므로 maxWidth 로 묶는다.
        "width": 96, "minWidth": 96, "maxWidth": 96,
        "cellClass": "md-c-center",
        "editable": _EDIT_UNLESS_PROTECTED if attendance_editable else False,
    }
    if not attendance_editable:
        attendance["cellClass"] = "md-c-center ms-cell-readonly"
    return {
        # 대분류·중분류 52 = 헤더 33.13x1.05 + 16. 두 열 모두 sample 값이 0건이라 이 화면
        # 안에 역산 재료가 없어 **헤더 하한**만 쓴다(종전에는 저장소 표본으로 84 를 잡았지만
        # 그 근거는 14.5px 기준이었고, 값 0건인 열을 미리 넓히는 것이 이번에 지적된 문제다).
        # migration 009 가 대분류를 그룹명으로 백필하면 그때 다시 재서 갱신한다 — 그 전까지
        # 남는 폭은 fitGridWidth 가 비례로 얹어 주고, 열은 resizable 이다.
        "대분류": {"width": 52, "minWidth": 52, "cellClass": "md-c-left",
                 "editable": _EDIT_UNLESS_PROTECTED},
        "중분류": {"width": 52, "minWidth": 52, "cellClass": "md-c-left",
                 "editable": _EDIT_UNLESS_PROTECTED},
        # 코드 48 = 값 실측 최대 'PET1' 30.02x1.05 + 16. 8~9자리 부서코드가 실제로 들어오면
        # 이 표본으로는 모자라므로(9자리 = 67.5+16) 그때 재측정한다. 자연키라 저장행 편집 불가.
        "코드": {"width": 48, "minWidth": 48, "cellClass": "md-c-left",
                "editable": _EDIT_NEW_ONLY, "cellClassRules": dict(_CODE_READONLY_RULES)},
        # 코드명 120 = 값 실측 최대 'PET생산부(원료실)' 97.58x1.05 + 16. 행을 특정하는 열이라
        # 상한을 두지 않고 남는 폭을 비례로 흡수하게 둔다.
        "코드명": {"width": 120, "minWidth": 120, "cellClass": "md-c-left",
                 "editable": _EDIT_UNLESS_PROTECTED},
        _ATTENDANCE_COL: attendance,
        # 순서·사용 40 = 헤더 2글자 22.09x1.05 + 16. 정수·체크박스라 상한 고정.
        "순서": {"width": 40, "minWidth": 40, "maxWidth": 40,
                "cellClass": "md-c-center ms-num", "editable": _EDIT_UNLESS_PROTECTED},
        # 비고 40 = 헤더 하한(값 0건). 실데이터가 생기면 다시 잰다.
        "비고": {"width": 40, "minWidth": 40, "cellClass": "md-c-left",
                "editable": _EDIT_UNLESS_PROTECTED},
        "사용": {"width": 40, "minWidth": 40, "maxWidth": 40,
                "cellClass": "md-c-center", "editable": _EDIT_UNLESS_PROTECTED},
    }


# 조 시트(6열) — 폭 규칙은 _dept_col_config 주석과 동일(12px 기준 역산 · 비율).
# 유형 열의 색 채움(ms-unit-shift / ms-unit-general)은 걷어냈다: 교대/일반은 오류·경고가
# 아니라 값이고, 표 안에서 색면이 열을 차지하면 읽어야 할 값보다 먼저 눈을 끈다(2026-08-19
# 사용자 판단). 구분은 '교대'/'일반' 텍스트가 그대로 담당한다.
_UNIT_COL_CONFIG = {
    # 코드 48 / 코드명 120 — 부서·그룹 시트와 같은 값(같은 성격 열이 화면마다 다른 폭으로 서지 않게).
    "코드": {"width": 48, "minWidth": 48, "cellClass": "md-c-left",
            "editable": _EDIT_NEW_ONLY, "cellClassRules": dict(_CODE_READONLY_RULES)},
    "명칭": {"headerName": "코드명", "width": 120, "minWidth": 120, "cellClass": "md-c-left",
           "editable": _EDIT_UNLESS_PROTECTED},
    # 유형 40 = '교대'/'일반' 2글자 22.09x1.05 + 16. 어휘가 둘로 고정이라 maxWidth.
    "유형": {
        "headerName": "유형", "width": 40, "minWidth": 40, "maxWidth": 40,
        "cellClass": "md-c-center", "cellEditor": "agSelectCellEditor",
        "cellEditorParams": {"values": ["교대", "일반"]},
    },
    "표시순서": {"headerName": "순서", "width": 40, "minWidth": 40, "maxWidth": 40,
             "cellClass": "md-c-center ms-num", "editable": _EDIT_UNLESS_PROTECTED},
    "비고": {"width": 40, "minWidth": 40, "cellClass": "md-c-left", "editable": _EDIT_UNLESS_PROTECTED},
    "사용": {"width": 40, "minWidth": 40, "maxWidth": 40, "cellClass": "md-c-center",
           "editable": _EDIT_UNLESS_PROTECTED},
}


def _write_reason(readiness: ReadinessState) -> str | None:
    return readiness.message if not readiness.write_enabled else None


def _locked_action_bar(state: DraftState, readiness: ReadinessState) -> None:
    """상위 미선택 잠금 시트의 액션바 — 모든 write 비활성(버튼 키는 유지).

    라우팅되지 않는 조 시트 전용 보존 코드다(부서 단일 시트는 잠기지 않으며 액션
    진입점이 상단 헤더 아이콘 하나다).
    """
    reason = _write_reason(readiness) or "상위 항목을 먼저 선택하세요."
    master_action_bar(state, sel_count=0, dirty_total=0, can_write=False,
                      write_disabled_reason=reason, ratios=_ORG_BAR_RATIOS)


# 헤더 아이콘 동기화 — 상단 52px 헤더는 본문보다 **먼저** 그려지므로,
# ``publish_header_actions`` 로 발행한 활성/음영은 그 다음 런부터 헤더에 반영된다.
# 인페이지 액션바가 함께 있던 동안에는 이 한 런 지연이 가려졌지만(버튼이 즉시 반영),
# 진입점이 헤더 하나가 된 뒤에는 "셀을 고쳤는데 저장 아이콘이 아직 음영 → 클릭 불가"
# 로 그대로 막힘이 된다(실측: 편집 직후 인페이지 저장=활성인데 헤더 저장=음영).
# 그래서 이번 런 헤더가 그린 상태와 방금 계산한 상태가 다를 때만 **한 번** 재실행해
# 헤더를 따라잡게 한다. 지문이 같아지면 재실행하지 않으므로 루프가 생기지 않고,
# 그리드 클라이언트 상태(편집 중인 셀 값)는 리마운트 없는 재실행에서 보존된다.
_HDR_FINGERPRINT_KEY = "org_dept:hdr_fingerprint"
_HDR_RESYNC_KEY = "org_dept:hdr_resync"


def _publish_header_actions(specs: list[dict]) -> bool:
    """액션 스펙을 헤더에 발행하고, 헤더가 옛 상태로 그려졌으면 재실행을 예약한다.

    반환값이 True 면 **이번 런의 출력은 버려진다** — 호출부는 flash·저장 원장 같은
    1회성 상태를 이 런에서 소비하면 안 된다(소비 후 재실행하면 결과 배너가 화면에
    남지 않는다). 게이트/확인 바처럼 세션에 남는 상태는 그대로 렌더해도 무방하다.
    """
    header_actions_from_specs("master_org", specs)
    fingerprint = tuple(
        (s.get("role"), bool(s.get("disabled")), s.get("help")) for s in specs
    )
    # 매 런 덮어쓴다(누적 아님) — 다른 이유로 재실행돼 이미 따라잡혔으면 False 가 된다.
    resync = st.session_state.get(_HDR_FINGERPRINT_KEY) != fingerprint
    st.session_state[_HDR_RESYNC_KEY] = resync
    st.session_state[_HDR_FINGERPRINT_KEY] = fingerprint
    return resync


def _drop_stale_dept_draft() -> None:
    """컬럼 계약이 바뀐 코드로 갱신된 세션의 옛 부서 draft 를 폐기한다(배포·핫리로드 경계).

    근태 등록 대상 열이 없던 시절의 draft 를 그대로 그리면 그리드 준비 단계가 bool
    기본값(False)으로 채워 **전 부서가 해제된 것처럼** 보이고, 그 화면에서 저장하면
    지정이 실제로 풀린다. 사용자가 만지지 않은 값이 조용히 뒤집히는 것보다 스토어에서
    다시 읽는 편이 안전하다(재적재 = 이 화면의 정상 경로).
    """
    rows = _OD.get_rows()
    if rows is None or _ATTENDANCE_COL in getattr(rows, "columns", []):
        return
    st.session_state.pop(_OD.rows_key, None)
    st.session_state.pop(_OD.key("baseline"), None)
    _OD.set_dirty(False)


def _untracked_count(live: pd.DataFrame) -> int:
    """저장 전 **근태 등록 대상 해제** 건수 — 적재 시점 지정(True) → 현재 미지정 기존 행.

    해제는 "이 부서가 근무표에서 사라진다"는 결과로 이어지는데, 표에서는 체크 하나가
    빠진 모습일 뿐이라 저장 직전에 알아채기 어렵다. 그래서 미저장 건수와 같은 자리에서
    건수로 읽히게 한다(칩만 사용 — 별도 장식·모달 없음).
    """
    base = st.session_state.get(_OD.key("baseline")) or {}
    if live is None or getattr(live, "empty", True) or not base:
        return 0
    idx = _DEPT_COLS.index(_ATTENDANCE_COL)
    count = 0
    for _, row in live.iterrows():
        if str(row.get("_row_state")) != "existing":
            continue
        prior = base.get(str(row.get("_row_id")))
        if not prior or len(prior) <= idx:
            continue
        if prior[idx] == str(True) and not grid_bool(row.get(_ATTENDANCE_COL)):
            count += 1
    return count


def _summary_chips(rows: pd.DataFrame, params: dict, *, dirty: int = 0, sel: int = 0,
                   untracked: int = 0, attendance_locked: bool = False) -> None:
    """표 위 요약 스트립 — 좌: 활성 필터 칩(사용 여부·검색), 우: 분포 + 편집 상태 칩.

    사용자 관리(_render_summary_chips)와 동일 규칙: **현재 스코프/필터 결과** 기준으로 세고
    (전체수 아님), 분포 칩 어휘는 필터 옵션어(사용 중/사용 안 함)와 통일한다. 결과가 0건이어도
    활성(비기본) 필터 칩은 남겨 "왜 비었는지"를 알리고, 분포 칩만 결과가 있을 때 렌더한다.
    모든 필터가 기본이고 결과도 없으면 비운다.

    ``dirty``/``sel`` 은 인페이지 액션바가 들고 있던 상태 신호(저장 badge "저장 · N",
    삭제 활성 근거)를 이어받는 편집 상태 칩이다 — 액션이 상단 헤더 아이콘으로 옮겨간 뒤
    그 **활성/음영의 근거**를 표 바로 위에서 읽게 한다(근무형태 관리 건수 행과 같은 어휘).
    0이면 렌더하지 않아 평상시 밀도는 종전과 같다. 그리드 반환 뒤에 계산되는 값이라
    호출부가 슬롯(placeholder)에 지연 렌더한다.

    부서 시트에는 근태 등록 대상(011) 신호가 더 붙는다 — 지정 건수는 분포 칩과 같은
    스코프(현재 필터 결과)로 세고, **0이면 warn 톤**으로 둔다: 지정이 하나도 없으면
    근무표·편성·대시보드의 부서 목록이 통째로 비는데 그 사실을 읽을 수 있는 곳이 이
    화면뿐이기 때문이다("이 부서를 왜 근무표에서 못 찾지?"의 사전 답). ``untracked`` 는
    저장 전 해제 건수, ``attendance_locked`` 는 지정 스키마 미준비(편집 불가) 사유다.
    """
    existing = rows[rows["_row_state"].astype(str) == "existing"] if rows is not None and not rows.empty \
        else pd.DataFrame(columns=["사용"])
    left = ""
    if params.get("active") and params["active"] != "전체":
        left += chip_html(f"사용 여부: {params['active']}", "lock")
    if params.get("search"):
        left += chip_html(f"검색: {params['search']}", "lock")
    if attendance_locked:
        left += chip_html(f"{_ATTENDANCE_COL}: 지정 스키마 준비 전(편집 불가)", "lock")
    right = ""
    if not existing.empty:
        on = int(existing["사용"].map(grid_bool).sum())
        off = len(existing) - on
        right = chip_html(f"사용 중 {on}", "ok")
        if off:
            right += chip_html(f"사용 안 함 {off}", "mute")
        if _ATTENDANCE_COL in existing.columns:
            tracked = int(existing[_ATTENDANCE_COL].map(grid_bool).sum())
            right += chip_html(f"{_ATTENDANCE_COL} {tracked}", "ok" if tracked else "warn")
    if int(dirty):
        right += chip_html(f"미저장 {int(dirty)}건", "warn")
    if int(untracked):
        right += chip_html(f"{_ATTENDANCE_COL} 해제 {int(untracked)}건", "warn")
    if int(sel):
        right += chip_html(f"선택 {int(sel)}건", "mute")
    if not left and not right:
        return
    # 위 시트 헤더(.ms-sheet-head 하단 패딩)와 아래 블록 사이에 실제 여백을 준다 —
    # 구 margin(.1rem/.2rem)은 헤더 패딩과 3px 겹치고 아래와는 0px 로 붙어, 칩 줄이
    # 두 블록 사이에 끼인 것처럼 읽혔다(실측 t313–329, 헤더 b316). 액션바가 있던
    # 자리를 이 줄이 이어받은 뒤에도 같은 여백으로 그리드와 분리한다.
    # 값은 §1.1 스케일만 쓴다(구 .35rem/.45rem/.5rem/.3rem = 4.9/6.3/7/4.2px 은 스케일 밖).
    st.markdown(
        "<div style='display:flex;justify-content:space-between;align-items:center;"
        "gap:8px;margin:8px 0'>"
        f"<div style='display:flex;gap:4px;flex-wrap:wrap'>{left}</div>"
        f"<div style='display:flex;gap:4px;flex:0 0 auto'>{right}</div></div>",
        unsafe_allow_html=True,
    )


# ---------- 그룹 시트 (2026-08-07 이후 라우팅되지 않음) ----------
# 사용자 결정으로 그룹·운영단위 시트는 화면에서 제거됐다(계층은 부서의 대분류/중분류가
# 대신한다). 아래 그룹/조 시트 함수들은 render() 에서 호출되지 않지만 남겨둔다:
#   * organization_groups·teams 테이블과 데이터는 그대로 살아 있다(009 가 drop 하지 않음).
#   * build_group_rows/build_team_rows/_validate_units/_unit_structure_errors/
#     _group_structure_errors/_save_units 등은 교차 화면 회귀 테스트가 직접 참조한다.
# 시트를 되살릴 계획이 확정적으로 없어지면 이 블록과 해당 테스트를 함께 제거한다.
def build_group_rows(df: pd.DataFrame) -> pd.DataFrame:
    """organization_groups 프레임 → 그룹 시트 편집 행. 정렬: 순서 → 코드."""
    if df is None or df.empty:
        return pd.DataFrame(columns=_GROUP_ROW_COLS)
    frame = df.copy()
    frame["_o"] = pd.to_numeric(frame["sort_order"], errors="coerce").fillna(0).astype("int64")
    frame = frame.sort_values(["_o", "group_code"]).reset_index(drop=True)
    rows = pd.DataFrame({
        "_row_id": "e:" + frame["group_code"].astype(str),
        "_row_state": "existing", "_sel": False,
        "코드": frame["group_code"].fillna("").astype("string"),
        "코드명": frame["group_name"].fillna("").astype("string"),
        "순서": frame["_o"].astype(str).astype("string"),
        "비고": frame.get("description", "").fillna("").astype("string") if "description" in frame else "",
        "사용": frame["is_active"].fillna(True).astype(bool),
    })
    return rows[_GROUP_ROW_COLS].reset_index(drop=True)


def _load_groups(q: dict) -> None:
    df = db.get_org_groups()
    df = _apply_filter(df, q, "group_code", "group_name")
    rows = build_group_rows(df)
    _GRP.set_rows(rows)
    _set_baseline(_GRP, rows, _GROUP_COLS)
    _GRP.bump_nonce()
    _GRP.set_dirty(False)


def _group_display(rows: pd.DataFrame, sel_group: str) -> pd.DataFrame:
    frame = rows.copy() if rows is not None else pd.DataFrame(columns=_GROUP_ROW_COLS)
    if frame.empty:
        return frame
    codes = frame["코드"].astype(str).str.strip()
    is_existing = frame["_row_state"].astype(str) == "existing"
    frame["_inactive"] = ((is_existing) & (~frame["사용"].map(grid_bool))).map(_flag)
    frame["_protected"] = (is_existing & codes.str.upper().isin(_SYSTEM_CODES)).map(_flag)
    frame["_linked"] = (codes == str(sel_group).strip()).map(_flag)
    frame["_delete"] = codes.isin(_plan_codes(st.session_state.get(_GRP.delete_plan_key))).map(_flag)
    return frame


def _render_group_sheet(params: dict, readiness: ReadinessState, sel_group: str) -> pd.DataFrame:
    show_flash(_GRP)
    # 폐기 게이트 대기 여부는 여기서 읽되(액션바 can_write 판단), 배너 렌더는 표준 순서대로
    # 액션바 뒤 banner_slot 에서 한다.
    pending = _GRP.has_pending_reload()
    plan = st.session_state.get(_GRP.delete_plan_key)
    rows = _GRP.get_rows()
    sheet_head("그룹", count=_existing_count(rows))

    # 표준 순서(users/worktype 통일): 요약칩 → __bar 액션바 → 확인/결과 배너 → 그리드.
    _summary_chips(rows, params)
    bar_slot = st.container()      # 액션바(keyed __bar) — 건수 계산 후 채운다
    banner_slot = st.container()   # 확인/폐기 배너 — 액션바 뒤·그리드 앞

    spec = MasterGridSpec(
        page_id=_GRP.page_id, columns=_GROUP_GRID_COLUMNS, order=_GROUP_COLS,
        col_config=_code_name_config(), select_all=True, include_linked_rows=True,
        # autoSizeStrategy: 지정 폭을 **비율**로 삼아 남는 가로 폭을 비례 분배한다. 없으면
        # flex 를 뺀 순간 표가 뷰포트보다 좁게 서서 "화면보다 작은 표"가 된다. 공용
        # views/master/grid.py 에 두는 것이 옳지만 그 파일은 이번 범위 밖이라 화면별
        # grid_options 로 얹는다(3화면 동일 — 보고 대상).
        grid_options={"onCellClicked": _DRILL_CLICK,  # 행 클릭 = 그룹 드릴다운 선택
                      "autoSizeStrategy": {"type": "fitGridWidth"}},
        height=master_grid_height(len(rows) if rows is not None else 0),
    )
    grid_df = render_master_grid(spec, _group_display(rows, sel_group), key=_GRP.grid_key())

    live = live_rows(grid_df)
    existing = live[live["_row_state"] == "existing"]
    sel_count = int((existing["_sel"].map(grid_bool)).sum()) if not existing.empty else 0
    new_cnt, changed_cnt = _dirty_counts(_GRP, live, _GROUP_COLS)
    total = dirty_total(new_cnt, changed_cnt)
    _GRP.set_dirty(total > 0)
    with bar_slot, st.container(key=f"{_GRP.page_id}__bar"):
        master_action_bar(
            _GRP, sel_count=sel_count, dirty_total=total,
            can_write=readiness.write_enabled, write_disabled_reason=_write_reason(readiness),
            ratios=_ORG_BAR_RATIOS,
        )
    with banner_slot:
        _render_saved_ledger(_GRP)  # 직전 partial 저장 원장(성공/실패 칩) 1회 표시
        if pending:
            gate = discard_confirm_bar(_GRP)
            if gate == "discard":
                p = _GRP.apply_pending_reload()
                st.session_state.pop(_GRP.delete_plan_key, None)
                _load_groups(p if p is not None else params)
                st.rerun()
            elif gate == "cancel":
                _GRP.cancel_pending_reload()
                st.rerun()
        if plan:
            _group_confirm_bar(plan, params, readiness)
    count_strip(len(existing), new_cnt, changed_cnt, sel_count)
    return grid_df


def _add_group_row(grid_df: pd.DataFrame) -> None:
    live = live_rows(grid_df)
    row = {
        "_row_id": _GRP.next_rid(), "_row_state": "new", "_sel": False,
        "코드": "", "코드명": "", "순서": str(_next_order(live)), "비고": "", "사용": True,
    }
    _GRP.set_rows(pd.concat([live[_GROUP_ROW_COLS], pd.DataFrame([row])], ignore_index=True)[_GROUP_ROW_COLS])
    _GRP.bump_nonce()
    st.rerun()


def _validate_groups(live: pd.DataFrame):
    """그룹 시트 → organization_groups 레코드 + 행 검증. 완전히 빈 신규 행은 제외."""
    records, errors = [], []
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        code = str(row.get("코드") or "").strip()
        name = str(row.get("코드명") or "").strip()
        order_raw = str(row.get("순서") or "").strip()
        if not any([code, name]):
            continue
        tag = f"{i}행" + (f"({code})" if code else "")
        if not code:
            errors.append(f"{i}행: 그룹코드를 입력하세요.")
        if not name:
            errors.append(f"{tag}: 그룹명을 입력하세요.")
        order_val = 0
        if order_raw:
            try:
                order_val = int(order_raw)
            except ValueError:
                errors.append(f"{tag}: 순서는 숫자여야 합니다.")
        records.append({
            "group_code": code, "group_name": name, "sort_order": order_val,
            "description": str(row.get("비고") or "").strip(), "is_active": grid_bool(row.get("사용")),
        })
    return records, errors


def _save_groups(grid_df: pd.DataFrame, q: dict) -> None:
    readiness = _readiness()
    if not readiness.write_enabled:
        banner("danger" if readiness.state is Readiness.PROBE_ERROR else "warn", readiness.message)
        return
    live = live_rows(grid_df)
    store = db.get_org_groups()
    counts: dict[str, int] = {}

    def _validate():
        return _validate_groups(live)

    def _build(records):
        merged, dup, n_c, n_u, _n_d = db.upsert_records(
            store, records, set(), ["group_code"], "is_active", db.ORG_GROUP_COLUMNS,
        )
        counts["create"], counts["update"] = n_c, n_u
        errs = []
        if dup:
            errs.append("그룹코드가 중복되었습니다: " + ", ".join(k[0] for k in dup))
        return merged, errs

    def _persist(merged, records):
        keys = [r["group_code"] for r in records if r.get("group_code")]
        try:
            report = db.save_org_groups_report(merged)
        except db.DATA_SOURCE_ERRORS as exc:
            return PersistResult.failure(_GRP.page_id, keys, str(exc))
        return PersistResult(page_id=_GRP.page_id, **report.to_persist_kwargs())

    outcome = run_save(_GRP, validate=_validate, build_candidate=_build, persist=_persist)
    if outcome.status in ("invalid", "failed"):
        _error_banner("그룹을 저장하지 못했습니다.", outcome.errors)
        return
    if outcome.status == "partial":
        # §22: 성공 자연키만 reconcile(초안 clean·신규→기존), 실패분 draft 유지. 원장은
        # 세션에 보관해 rerun 후 시트 배너에서 표시한다.
        _reconcile_org_partial(_GRP, live, outcome.result, _GROUP_COLS)
        st.session_state[_GRP.key("save_ledger")] = outcome.result
        st.rerun()
    if outcome.status == "unknown":
        # 결과 불명 — reconcile 하지 않고(재조회 필요) 원장만 표기한다.
        ledger_banner(outcome.result)
        return
    _load_groups(q)
    _GRP.set_flash("success", f"그룹을 저장했습니다. (신규 {counts.get('create', 0)} · 수정 {counts.get('update', 0)})")
    st.rerun()


def _plan_group_delete(grid_df: pd.DataFrame) -> None:
    readiness = _readiness()
    if not readiness.write_enabled:
        _GRP.set_flash("error" if readiness.state is Readiness.PROBE_ERROR else "warning", readiness.message)
        st.rerun()
    live = live_rows(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    codes = sorted({str(c).strip() for c in sel["코드"] if str(c).strip()})
    if not codes:
        _GRP.set_flash("warning", "삭제할 기존 그룹을 선택하세요.")
        st.rerun()
    plan = {"delete": [], "deactivate": [], "block": []}
    for code in codes:
        if code.upper() in _SYSTEM_CODES:
            plan["block"].append(code)
            continue
        refs = db.org_group_reference_counts(code)
        if sum(refs.values()) > 0:
            plan["deactivate"].append({"code": code, "refs": refs})
        else:
            plan["delete"].append(code)
    st.session_state[_GRP.delete_plan_key] = plan
    st.rerun()


def _group_confirm_bar(plan: dict, params: dict, readiness: ReadinessState) -> None:
    lines = []
    if plan["delete"]:
        lines.append("삭제 가능: " + ", ".join(plan["delete"]))
    for item in plan["deactivate"]:
        lines.append(f"미사용 처리: {item['code']} — 소속 부서 {item['refs'].get('departments', 0)}개")
    for code in plan["block"]:
        lines.append(f"처리 불가: {code} — 시스템 필수 그룹 (ADMIN 보호)")
    actionable = bool(plan["delete"] or plan["deactivate"]) and readiness.write_enabled
    result = confirm_bar(
        _GRP, title="선택한 그룹을 참조 확인 후 미사용/삭제 처리합니다 (ADMIN 보호).",
        lines=lines, confirm_label="삭제 실행", confirm_enabled=actionable, scope="del",
    )
    if result == "confirm":
        _execute_group_delete(plan, params)
    elif result == "cancel":
        st.session_state.pop(_GRP.delete_plan_key, None)
        st.rerun()


def _execute_group_delete(plan: dict, params: dict) -> None:
    n_del = n_deact = 0
    failed: list[str] = []
    for code in plan["delete"]:
        try:
            db.delete_org_group(code)
            n_del += 1
        except db.DATA_SOURCE_ERRORS:
            failed.append(code)
    for item in plan["deactivate"]:
        try:
            db.deactivate_org_group(item["code"])
            n_deact += 1
        except db.DATA_SOURCE_ERRORS:
            failed.append(item["code"])
    st.session_state.pop(_GRP.delete_plan_key, None)
    _load_groups(params)
    _finish_delete(_GRP, "그룹", n_del, n_deact, plan.get("block"), failed)


# ---------- 부서 시트 ----------
def build_dept_rows(df: pd.DataFrame) -> pd.DataFrame:
    """departments 프레임 → 부서 시트 편집 행. 정렬: 순서 → 코드."""
    if df is None or df.empty:
        return pd.DataFrame(columns=_DEPT_ROW_COLS)
    frame = df.copy()
    frame["_o"] = pd.to_numeric(frame["sort_order"], errors="coerce").fillna(0).astype("int64")
    # 계층이 눈으로 읽히도록 대분류 → 중분류 → 순서 → 코드로 묶어 정렬한다.
    for col in ("major_category", "minor_category"):
        if col not in frame:
            frame[col] = ""
        frame[col] = frame[col].fillna("").astype(str)
    frame = frame.sort_values(
        ["major_category", "minor_category", "_o", "dept_code"]
    ).reset_index(drop=True)
    rows = pd.DataFrame({
        "_row_id": "e:" + frame["dept_code"].astype(str),
        "_row_state": "existing", "_sel": False,
        "대분류": frame["major_category"].astype("string"),
        "중분류": frame["minor_category"].astype("string"),
        "코드": frame["dept_code"].fillna("").astype("string"),
        "코드명": frame["dept_name"].fillna("").astype("string"),
        # 근태 등록 대상(011). 파사드가 bool dtype 을 보장하지만, 이 컬럼 이전 계약으로
        # 만들어진 프레임(교차 화면 테스트 fixture 등)도 그대로 렌더되게 폴백한다.
        _ATTENDANCE_COL: (
            frame["tracks_attendance"].map(grid_bool)
            if "tracks_attendance" in frame else False
        ),
        "순서": frame["_o"].astype(str).astype("string"),
        "비고": frame.get("description", "").fillna("").astype("string") if "description" in frame else "",
        "사용": frame["is_active"].fillna(True).astype(bool),
    })
    return rows[_DEPT_ROW_COLS].reset_index(drop=True)


def _load_depts(q: dict) -> None:
    # 그룹 시트 폐지 후 부서는 단일 시트라 그룹으로 좁히지 않고 전건을 적재한다.
    df = db.get_org_departments()
    df = _apply_filter(df, q, "dept_code", "dept_name")
    rows = build_dept_rows(df)
    _OD.set_rows(rows)
    _set_baseline(_OD, rows, _DEPT_COLS)
    # 적재 시점의 귀속 그룹을 안정 상위키로 기록한다 — 저장은 현재 selectbox 값이 아니라
    # 이 값으로 행을 귀속시켜, 상위 전환 중 옛 행이 새 그룹에 오귀속되는 것을 막는다.
    st.session_state[_OD.key("loaded_group")] = str(q.get("group") or "")
    _OD.bump_nonce()
    _OD.set_dirty(False)


def _dept_display(rows: pd.DataFrame, sel_dept: str) -> pd.DataFrame:
    frame = rows.copy() if rows is not None else pd.DataFrame(columns=_DEPT_ROW_COLS)
    if frame.empty:
        return frame
    codes = frame["코드"].astype(str).str.strip()
    is_existing = frame["_row_state"].astype(str) == "existing"
    frame["_inactive"] = ((is_existing) & (~frame["사용"].map(grid_bool))).map(_flag)
    frame["_protected"] = (is_existing & codes.str.upper().isin(_SYSTEM_CODES)).map(_flag)
    frame["_linked"] = (codes == str(sel_dept).strip()).map(_flag)
    frame["_delete"] = codes.isin(_plan_codes(st.session_state.get(_OD.delete_plan_key))).map(_flag)
    return frame


def _render_dept_sheet(params: dict, readiness: ReadinessState, group_code: str = "",
                       group_name: str = "", sel_dept: str = ""):
    """부서 단일 시트. 그룹/운영단위 시트 폐지(2026-08-07)로 드릴다운 상위가 없다.

    group_code/group_name/sel_dept 는 교차 화면 테스트가 참조하는 시그니처라 선택
    인자로 보존한다 — 현재 화면 경로에서는 모두 빈 값으로 호출된다.
    """
    # flash(저장·삭제 결과)는 배너 슬롯에서 렌더한다 — 헤더 따라잡기 재실행이 걸린
    # 런에서 소비하면 결과 배너가 화면에 남지 않기 때문이다(_publish_header_actions).
    # 미저장 draft 폐기 게이트(필터 변경 등). 해소 전까지 write 를 비활성한다(§17).
    pending = _OD.has_pending_reload()
    plan = st.session_state.get(_OD.delete_plan_key)
    rows = _OD.get_rows()
    sheet_head("부서", count=_existing_count(rows), context=group_name or None)

    # 표준 순서(users/worktype 통일): 요약·상태 칩 줄 → 확인/결과 배너 → 그리드.
    # 인페이지 액션바가 있던 자리는 **버튼이 아니라 상태**가 이어받는다(액션은 상단
    # 헤더 아이콘 단일 진입점). 칩 줄은 그리드 반환 뒤 계산되는 미저장·선택 건수를
    # 포함하므로 슬롯만 잡아 두고 건수 계산 후 채운다.
    chips_slot = st.container()    # 요약(필터·분포) + 편집 상태(미저장·선택) 칩 — deferred
    banner_slot = st.container()   # 확인/폐기 배너 — 칩 줄 뒤·그리드 앞

    # 근태 등록 대상(011) 지정 스키마가 없는 배포에서는 그 열만 읽기전용으로 내린다
    # (조회 폴백 = 전 부서 대상 · 저장은 fail-closed).
    attendance_editable = _attendance_ready()
    spec = MasterGridSpec(
        page_id=_OD.page_id, columns=_DEPT_GRID_COLUMNS, order=_DEPT_COLS,
        col_config=_dept_col_config(attendance_editable=attendance_editable),
        select_all=True, include_linked_rows=True,
        # autoSizeStrategy: 지정 폭을 **비율**로 삼아 남는 가로 폭을 비례 분배한다. 없으면
        # flex 를 뺀 순간 표가 뷰포트보다 좁게 서서 "화면보다 작은 표"가 된다. 공용
        # views/master/grid.py 에 두는 것이 옳지만 그 파일은 이번 범위 밖이라 화면별
        # grid_options 로 얹는다(3화면 동일 — 보고 대상).
        grid_options={"autoSizeStrategy": {"type": "fitGridWidth"}},
        height=master_grid_height(len(rows) if rows is not None else 0),
    )
    grid_df = render_master_grid(spec, _dept_display(rows, sel_dept), key=_OD.grid_key(suffix=group_code))

    live = live_rows(grid_df)
    existing = live[live["_row_state"] == "existing"]
    sel_count = int((existing["_sel"].map(grid_bool)).sum()) if not existing.empty else 0
    new_cnt, changed_cnt = _dirty_counts(_OD, live, _DEPT_COLS)
    total = dirty_total(new_cnt, changed_cnt)
    _OD.set_dirty(total > 0)
    can_write = readiness.write_enabled and not pending
    reason = _write_reason(readiness) or ("미저장 변경 안내를 먼저 처리하세요." if pending else None)
    with chips_slot:
        _summary_chips(rows, params, dirty=total, sel=sel_count,
                       untracked=_untracked_count(live),
                       attendance_locked=not attendance_editable)
    # 상단 52px 헤더 아이콘(추가·삭제·저장·새로고침)이 이 화면의 유일한 액션 진입점이다.
    # 활성/음영·툴팁 사유는 종전 인페이지 액션바와 **같은 규칙**(page_action_specs 순수
    # 계산 — readiness NOT_READY/PROBE_ERROR·폐기 게이트·선택 0·변경 0 전부 동일)이며,
    # 클릭은 종전과 같은 page-scoped flag 를 쏘므로 실행 경로·확인 게이트는 하나 그대로다.
    # 헤더 화면 id 는 nav 기준 'master_org'(DraftState page_id 'org_dept' 와 다름 —
    # 단일 시트 전환 후에도 화면 id 는 그대로다).
    resync = _publish_header_actions(page_action_specs(
        sel_count=sel_count, dirty_total=total,
        can_write=can_write, write_disabled_reason=reason,
    ))
    with banner_slot:
        # 1회성 상태(flash·저장 원장)는 이번 런의 출력이 실제로 남을 때만 소비한다 —
        # 헤더 따라잡기 재실행이 예약된 런에서 pop 하면 "저장했습니다" 배너가 사라진다.
        # (재실행 뒤 런에서 그대로 소비·표시된다 — 유실 없이 한 프레임 늦을 뿐이다.)
        if not resync:
            show_flash(_OD)            # §21 저장·삭제 결과 flash
            _render_saved_ledger(_OD)  # 직전 partial 저장 원장(성공/실패 칩) 1회 표시
        if pending:
            gate = discard_confirm_bar(_OD)
            if gate == "discard":
                _OD.apply_pending_reload()
                st.session_state.pop(_OD.delete_plan_key, None)
                _load_depts(params)
                st.rerun()
            elif gate == "cancel":
                _OD.cancel_pending_reload()
                st.rerun()
        if plan:
            _dept_confirm_bar(plan, params, readiness)
    count_strip(len(existing), new_cnt, changed_cnt, sel_count)
    return grid_df


def _add_dept_row(grid_df: pd.DataFrame, group_code: str = "") -> None:
    live = live_rows(grid_df)
    row = {
        "_row_id": _OD.next_rid(), "_row_state": "new", "_sel": False,
        "대분류": "", "중분류": "", "코드": "", "코드명": "",
        # 근태 등록 대상은 **명시 지정**이 원칙이라 신규 행은 미지정으로 시작한다
        # (migration 011 컬럼 기본값 · requirements §6 와 같은 방향).
        _ATTENDANCE_COL: False,
        "순서": str(_next_order(live)), "비고": "", "사용": True,
    }
    _OD.set_rows(pd.concat([live[_DEPT_ROW_COLS], pd.DataFrame([row])], ignore_index=True)[_DEPT_ROW_COLS])
    _OD.bump_nonce()
    st.rerun()


def _validate_depts(live: pd.DataFrame, group_code: str = ""):
    """부서 시트 → departments 레코드 + 행 검증.

    ``group_code`` 는 그룹 시트 폐지(2026-08-07) 후 화면에서 쓰지 않지만, 교차 화면
    회귀 테스트가 참조하는 시그니처라 선택 인자로 보존한다. 값을 주면 그대로 실어
    보내고(프로그램 경로에서 그룹 귀속을 유지할 수 있다), 빈 값이면 저장 계층이
    group_id 키 자체를 payload 에서 빼 기존 귀속을 보존한다.
    """
    records, errors = [], []
    gcode = str(group_code).strip()
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        code = str(row.get("코드") or "").strip()
        name = str(row.get("코드명") or "").strip()
        order_raw = str(row.get("순서") or "").strip()
        major = str(row.get("대분류") or "").strip()
        minor = str(row.get("중분류") or "").strip()
        if not any([code, name, major, minor]):
            continue
        tag = f"{i}행" + (f"({code})" if code else "")
        if not code:
            errors.append(f"{i}행: 부서코드를 입력하세요.")
        if not name:
            errors.append(f"{tag}: 부서명을 입력하세요.")
        # 중간층만 떠 있는 계층은 트리로 성립하지 않는다(DB departments_minor_requires_major).
        if minor and not major:
            errors.append(f"{tag}: 중분류를 쓰려면 대분류를 먼저 입력하세요.")
        order_val = 0
        if order_raw:
            try:
                order_val = int(order_raw)
            except ValueError:
                errors.append(f"{tag}: 순서는 숫자여야 합니다.")
        records.append({
            "dept_code": code, "dept_name": name, "group_code": gcode,
            "major_category": major, "minor_category": minor,
            "description": str(row.get("비고") or "").strip(), "sort_order": order_val,
            "is_active": grid_bool(row.get("사용")),
            # 근태 등록 대상(011)은 배치 전 행이 명시값을 실어야 저장 계층이 반영한다
            # (일부만 실으면 지정 유실 방지를 위해 통째로 무시된다 —
            # supabase_repository._departments_org_payload 의 all 판정).
            "tracks_attendance": grid_bool(row.get(_ATTENDANCE_COL)),
        })
    return records, errors


def _save_depts(grid_df: pd.DataFrame, q: dict, group_code: str = "") -> None:
    readiness = _readiness()
    if not readiness.write_enabled:
        banner("danger" if readiness.state is Readiness.PROBE_ERROR else "warn", readiness.message)
        return
    live = live_rows(grid_df)
    store = db.get_org_departments()
    counts: dict[str, int] = {}

    def _validate():
        # 그룹 시트 폐지 후 이 화면은 그룹 귀속을 편집하지 않는다. 호출 인자(group_code)로
        # 일괄 재귀속하지도 않는다 — 구 드릴다운의 loaded_group 바인딩과 같은 이유(전 행
        # 오귀속 사고 방지)다. 대신 기존 행의 group_code 를 스토어 값으로 되살려, 스토어
        # 병합·payload 어느 경로에서도 기존 귀속이 빈 값으로 지워지지 않게 보존한다.
        records, errors = _validate_depts(live, "")
        if records and not store.empty:
            stored_group = dict(zip(
                store["dept_code"].astype(str), store["group_code"].astype(str),
            ))
            for rec in records:
                if not str(rec.get("group_code") or "").strip():
                    rec["group_code"] = stored_group.get(rec["dept_code"], "")
        return records, errors

    def _build(records):
        merged, dup, n_c, n_u, _n_d = db.upsert_records(
            store, records, set(), ["dept_code"], "is_active", db.ORG_DEPT_COLUMNS,
        )
        counts["create"], counts["update"] = n_c, n_u
        errs = []
        if dup:
            errs.append("부서코드가 중복되었습니다: " + ", ".join(k[0] for k in dup))
        return merged, errs

    def _persist(merged, records):
        keys = [r["dept_code"] for r in records if r.get("dept_code")]
        try:
            report = db.save_org_departments_report(merged)
        except db.DATA_SOURCE_ERRORS as exc:
            return PersistResult.failure(_OD.page_id, keys, str(exc))
        return PersistResult(page_id=_OD.page_id, **report.to_persist_kwargs())

    outcome = run_save(_OD, validate=_validate, build_candidate=_build, persist=_persist)
    if outcome.status in ("invalid", "failed"):
        _error_banner("부서를 저장하지 못했습니다.", outcome.errors)
        return
    if outcome.status == "partial":
        # §22: 성공 부서코드만 reconcile(신규→기존·baseline clean), 실패분 draft 유지.
        _reconcile_org_partial(_OD, live, outcome.result, _DEPT_COLS)
        st.session_state[_OD.key("save_ledger")] = outcome.result
        st.rerun()
    if outcome.status == "unknown":
        ledger_banner(outcome.result)  # 재조회 필요 — reconcile 금지
        return
    _load_depts(q)  # 단일 시트 — 전건 재적재
    _OD.set_flash("success", f"부서를 저장했습니다. (신규 {counts.get('create', 0)} · 수정 {counts.get('update', 0)})")
    st.rerun()


def _ref_text(refs: dict) -> str:
    parts = []
    if refs.get("users"):
        parts.append(f"사용자 {refs['users']}명")
    if refs.get("teams"):
        parts.append(f"조 {refs['teams']}개")
    if refs.get("shift_groups"):
        parts.append(f"편성 {refs['shift_groups']}건")
    return ", ".join(parts) or "참조 있음"


def _plan_dept_delete(grid_df: pd.DataFrame, params: dict) -> None:
    readiness = _readiness()
    if not readiness.write_enabled:
        _OD.set_flash("error" if readiness.state is Readiness.PROBE_ERROR else "warning", readiness.message)
        st.rerun()
    live = live_rows(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    codes = sorted({str(c).strip() for c in sel["코드"] if str(c).strip()})
    if not codes:
        _OD.set_flash("warning", "삭제할 기존 부서를 선택하세요.")
        st.rerun()
    plan = {"delete": [], "deactivate": [], "block": []}
    for code in codes:
        if code.upper() in _SYSTEM_CODES:
            plan["block"].append(code)
            continue
        refs = db.department_reference_counts(code)
        if sum(refs.values()) > 0:
            plan["deactivate"].append({"code": code, "refs": refs})
        else:
            plan["delete"].append(code)
    st.session_state[_OD.delete_plan_key] = plan
    st.rerun()


def _dept_confirm_bar(plan: dict, params: dict, readiness: ReadinessState) -> None:
    lines = []
    if plan["delete"]:
        lines.append("삭제 가능: " + ", ".join(plan["delete"]))
    for item in plan["deactivate"]:
        lines.append(f"미사용 처리: {item['code']} — {_ref_text(item['refs'])} 참조 중")
    for code in plan["block"]:
        lines.append(f"처리 불가: {code} — 시스템 필수 부서 (ADMIN 보호)")
    actionable = bool(plan["delete"] or plan["deactivate"]) and readiness.write_enabled
    result = confirm_bar(
        _OD, title="선택한 부서를 참조 확인 후 미사용/삭제 처리합니다 (ADMIN 보호).",
        lines=lines, confirm_label="삭제 실행", confirm_enabled=actionable, scope="del",
    )
    if result == "confirm":
        _execute_dept_delete(plan, params)
    elif result == "cancel":
        st.session_state.pop(_OD.delete_plan_key, None)
        st.rerun()


def _execute_dept_delete(plan: dict, params: dict) -> None:
    n_del = 0
    failed: list[str] = []
    for code in plan["delete"]:
        try:
            db.delete_department(code)
            n_del += 1
        except db.DATA_SOURCE_ERRORS:
            failed.append(code)
    deactivate_codes = [item["code"] for item in plan["deactivate"]]
    n_deact = 0
    if deactivate_codes:
        try:
            store = db.get_org_departments().copy()
            mask = store["dept_code"].astype(str).isin(deactivate_codes)
            n_deact = int(mask.sum())
            store.loc[mask, "is_active"] = False
            db.save_org_departments(store[db.ORG_DEPT_COLUMNS])
        except db.DATA_SOURCE_ERRORS:
            n_deact = 0
            failed.extend(deactivate_codes)
    st.session_state.pop(_OD.delete_plan_key, None)
    _load_depts(params)
    st.session_state.pop(_OU.query_key, None)
    _finish_delete(_OD, "부서", n_del, n_deact, plan.get("block"), failed)


# ---------- 조(운영단위) 시트 ----------
def build_team_rows(df: pd.DataFrame) -> pd.DataFrame:
    """teams 프레임 → 조 시트 편집 행(유형 포함). 정렬: 순서 → 코드."""
    if df is None or df.empty:
        return pd.DataFrame(columns=_UNIT_ROW_COLS)
    frame = df.sort_values(["sort_order", "team_code"]).reset_index(drop=True)
    order = pd.to_numeric(frame["sort_order"], errors="coerce").fillna(0).astype("int64")
    rows = pd.DataFrame({
        "_row_id": "e:" + frame["dept_code"].astype(str) + "|" + frame["team_code"].astype(str),
        "_row_state": "existing", "_sel": False,
        "코드": frame["team_code"].fillna("").astype("string"),
        "명칭": frame["team_name"].fillna("").astype("string"),
        "유형": frame["unit_type"].map(db.UNIT_TYPE_LABELS).fillna("교대").astype("string"),
        "표시순서": order.astype(str).astype("string"),
        "비고": frame.get("description", "").fillna("").astype("string") if "description" in frame else "",
        "사용": frame["is_active"].fillna(True).astype(bool),
    })
    return rows[_UNIT_ROW_COLS].reset_index(drop=True)


def _load_units(dept_code: str, q: dict | None = None) -> None:
    df = db.get_org_teams(dept_code)
    if q:
        df = _apply_filter(df, q, "team_code", "team_name")
    rows = build_team_rows(df)
    _OU.set_rows(rows)
    _set_baseline(_OU, rows, _UNIT_COLS)
    st.session_state[_OU.key("loaded_dept")] = str(dept_code)
    _OU.bump_nonce()
    _OU.set_dirty(False)


def _unit_display(rows: pd.DataFrame) -> pd.DataFrame:
    frame = rows.copy() if rows is not None else pd.DataFrame(columns=_UNIT_ROW_COLS)
    if frame.empty:
        return frame
    frame["_inactive"] = (~frame["사용"].map(grid_bool)).map(_flag)
    plan = st.session_state.get(_OU.delete_plan_key)
    del_codes = set()
    if plan:
        for bucket in ("delete", "deactivate"):
            del_codes |= {it["team_code"] for it in plan.get(bucket, []) if "team_code" in it}
    frame["_delete"] = frame["코드"].astype(str).str.strip().isin(del_codes).map(_flag)
    return frame


def _render_unit_sheet(params: dict, readiness: ReadinessState, dept_code: str, dept_name: str):
    show_flash(_OU)
    if not dept_code:
        sheet_head("조", locked=True)
        sheet_locked("부서를 먼저 선택하세요", "부서를 선택하면 해당 부서의 조(운영단위)만 조회·등록됩니다.")
        _locked_action_bar(_OU, readiness)
        return None

    # 상위(부서) 전환 중 미저장 draft 폐기 게이트. 해소 전까지 이 시트의 write 를 비활성해
    # 옛 조 행이 새 부서 밑으로 오귀속·중복 생성되는 것을 차단한다(§17).
    # 게이트 배너 렌더는 표준 순서대로 액션바 뒤 banner_slot 에서 한다.
    pending = _OU.has_pending_reload()
    plan = st.session_state.get(_OU.delete_plan_key)
    rows = _OU.get_rows()
    sheet_head("조", count=_existing_count(rows), context=dept_name)

    # 표준 순서(users/worktype 통일): 요약칩 → __bar 액션바 → 확인/결과 배너 → 그리드.
    _summary_chips(rows, params)
    bar_slot = st.container()      # 액션바(keyed __bar) — 건수 계산 후 채운다
    banner_slot = st.container()   # 확인/폐기 배너 — 액션바 뒤·그리드 앞

    spec = MasterGridSpec(
        page_id=_OU.page_id, columns=_UNIT_GRID_COLUMNS, order=_UNIT_COLS,
        col_config=_UNIT_COL_CONFIG, select_all=True,
        # autoSizeStrategy: 지정 폭을 **비율**로 삼아 남는 가로 폭을 비례 분배한다. 없으면
        # flex 를 뺀 순간 표가 뷰포트보다 좁게 서서 "화면보다 작은 표"가 된다. 공용
        # views/master/grid.py 에 두는 것이 옳지만 그 파일은 이번 범위 밖이라 화면별
        # grid_options 로 얹는다(3화면 동일 — 보고 대상).
        grid_options={"autoSizeStrategy": {"type": "fitGridWidth"}},
        height=master_grid_height(len(rows) if rows is not None else 0),
    )
    grid_df = render_master_grid(spec, _unit_display(rows), key=_OU.grid_key(suffix=dept_code))

    if rows is not None and rows.empty:
        empty_state("등록된 조가 없습니다.", "‘행 추가’로 이 부서의 교대조·일반근무를 등록하세요.")

    live = live_rows(grid_df)
    existing = live[live["_row_state"] == "existing"]
    sel_count = int((existing["_sel"].map(grid_bool)).sum()) if not existing.empty else 0
    new_cnt, changed_cnt = _dirty_counts(_OU, live, _UNIT_COLS)
    total = dirty_total(new_cnt, changed_cnt)
    _OU.set_dirty(total > 0)
    can_write = readiness.write_enabled and not pending
    reason = _write_reason(readiness) or ("미저장 변경 안내를 먼저 처리하세요." if pending else None)
    with bar_slot, st.container(key=f"{_OU.page_id}__bar"):
        master_action_bar(
            _OU, sel_count=sel_count, dirty_total=total,
            can_write=can_write, write_disabled_reason=reason, ratios=_ORG_BAR_RATIOS,
        )
    with banner_slot:
        _render_saved_ledger(_OU)  # 직전 partial 저장 원장(성공/실패 칩) 1회 표시
        if pending:
            gate = discard_confirm_bar(_OU)
            if gate == "discard":
                _OU.apply_pending_reload()
                st.session_state.pop(_OU.delete_plan_key, None)
                _load_units(dept_code, params)
                st.rerun()
            elif gate == "cancel":
                _OU.cancel_pending_reload()
                st.rerun()
        if plan:
            _unit_confirm_bar(plan, dept_code, readiness)
    count_strip(len(existing), new_cnt, changed_cnt, sel_count)
    return grid_df


def _add_unit_row(grid_df: pd.DataFrame, dept_code: str) -> None:
    if grid_df is None or not dept_code:
        _OU.set_flash("warning", "조를 추가할 부서를 먼저 선택하세요.")
        st.rerun()
    readiness = _readiness()
    if not readiness.write_enabled:
        _OU.set_flash("error" if readiness.state is Readiness.PROBE_ERROR else "warning", readiness.message)
        st.rerun()
    live = live_rows(grid_df)
    row = {
        "_row_id": _OU.next_rid(), "_row_state": "new", "_sel": False,
        "코드": "", "명칭": "", "유형": "교대", "표시순서": str(_next_order(live, col="표시순서")),
        "비고": "", "사용": True,
    }
    _OU.set_rows(pd.concat([live[_UNIT_ROW_COLS], pd.DataFrame([row])], ignore_index=True)[_UNIT_ROW_COLS])
    _OU.bump_nonce()
    st.rerun()


def _validate_units(live: pd.DataFrame, dept_code: str):
    """조 시트 표시 형태 → teams 저장 형태 변환 + 행별 검증. 완전히 빈 신규 행은 제외.

    교차 화면 회귀 테스트(test_master_and_views/test_master_forms)가 참조하는 시그니처라
    field 키(명칭/표시순서)와 반환 계약(dept_code·unit_type SHIFT/GENERAL·빈 행 제외)을
    보존한다. 비고는 있으면 반영하고 없으면 빈 값으로 채운다(추가형, 후방호환).
    """
    records, errors = [], []
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        code = str(row.get("코드") or "").strip()
        name = str(row.get("명칭") or "").strip()
        type_raw = str(row.get("유형") or "").strip()
        order_raw = str(row.get("표시순서") or "").strip()
        if not any([code, name]):
            continue
        tag = f"{i}행" + (f"({code})" if code else "")
        if not code:
            errors.append(f"{i}행: 운영단위 코드를 입력하세요.")
        if not name:
            errors.append(f"{tag}: 운영단위 명칭을 입력하세요.")
        unit_type = _UNIT_TYPE_OF.get(type_raw.upper() if type_raw.isascii() else type_raw)
        if unit_type is None:
            errors.append(f"{tag}: 유형은 교대 또는 일반만 가능합니다. (입력값: {type_raw or '빈 값'})")
            unit_type = "SHIFT"
        try:
            order_val = int(order_raw) if order_raw else 0
        except ValueError:
            order_val = 0
            errors.append(f"{tag}: 표시순서는 숫자여야 합니다.")
        if order_raw == "":
            errors.append(f"{tag}: 표시순서를 입력하세요.")
        records.append({
            "dept_code": str(dept_code).strip(), "team_code": code, "team_name": name,
            "unit_type": unit_type, "description": str(row.get("비고") or "").strip(),
            "sort_order": order_val, "is_active": grid_bool(row.get("사용")),
        })
    return records, errors


def _unit_structure_errors(merged: pd.DataFrame, dept_code: str) -> list[str]:
    """선택 부서 기준 구조 검증 — 명칭·표시순서 중복 금지 (코드는 upsert 키로 보장)."""
    errors: list[str] = []
    if merged.empty:
        return errors
    sub = merged[merged["dept_code"].astype(str) == str(dept_code).strip()].copy()
    if sub.empty:
        return errors
    sub["team_name"] = sub["team_name"].astype(str).str.strip()
    sub["sort_order"] = pd.to_numeric(sub["sort_order"], errors="coerce").fillna(0).astype("int64")
    for name, group in sub.groupby("team_name"):
        if len(group) > 1:
            errors.append(f"운영단위 명칭 '{name}'이(가) 중복되었습니다: " + ", ".join(group["team_code"].astype(str)))
    for order, group in sub.groupby("sort_order"):
        if len(group) > 1:
            errors.append(f"표시순서 {order}이(가) 중복되었습니다: " + ", ".join(group["team_code"].astype(str)))
    return errors


def _save_units(grid_df, dept_code: str) -> None:
    """선택 부서의 조(운영단위) 편집 결과 검증 후 (부서, 코드) 기준 upsert."""
    if grid_df is None or not str(dept_code).strip():
        st.error("조를 저장할 부서를 먼저 선택하세요.")
        return
    readiness = _readiness()
    if not readiness.write_enabled:
        banner("danger" if readiness.state is Readiness.PROBE_ERROR else "warn", readiness.message)
        return
    live = live_rows(grid_df)
    store = db.get_org_teams()
    counts: dict[str, int] = {}
    # 귀속 부서는 현재 selectbox 값(dept_code)이 아니라 이 조 행들이 적재된 시점의 부서로
    # 바인딩한다. 상위 전환 중이라도 옛 조 행이 새 부서 밑으로 오귀속·중복되지 않는다.
    owner = str(st.session_state.get(_OU.key("loaded_dept"), dept_code) or dept_code)

    def _validate():
        return _validate_units(live, owner)

    def _build(records):
        merged, dup, n_c, n_u, _n_d = db.upsert_records(
            store, records, set(), ["dept_code", "team_code"], "is_active", db.ORG_TEAM_COLUMNS,
        )
        counts["create"], counts["update"] = n_c, n_u
        errs = []
        if dup:
            errs.append("운영단위 코드가 중복되었습니다: " + ", ".join(t for _d, t in dup))
        errs.extend(_unit_structure_errors(merged, owner))
        return merged, errs

    def _persist(merged, records):
        keys = [(r["dept_code"], r["team_code"]) for r in records if r.get("team_code")]
        try:
            report = db.save_org_teams_report(merged)
        except db.DATA_SOURCE_ERRORS as exc:
            return PersistResult.failure(_OU.page_id, keys, str(exc))
        return PersistResult(page_id=_OU.page_id, **report.to_persist_kwargs())

    outcome = run_save(_OU, validate=_validate, build_candidate=_build, persist=_persist)
    if outcome.status in ("invalid", "failed"):
        _error_banner("조를 저장하지 못했습니다.", outcome.errors)
        return
    if outcome.status == "partial":
        # §22: 성공 (부서,조)키만 reconcile(신규→e:{dept}|{team}·baseline clean), 실패분 유지.
        # 복합키라 적재 시점 소속 부서(owner)를 넘겨 성공 키를 정확히 매칭한다.
        _reconcile_org_partial(_OU, live, outcome.result, _UNIT_COLS, owner=owner)
        st.session_state[_OU.key("save_ledger")] = outcome.result
        st.rerun()
    if outcome.status == "unknown":
        ledger_banner(outcome.result)  # 재조회 필요 — reconcile 금지
        return
    _load_units(owner)  # 방금 저장한(귀속) 부서로 재적재
    _OU.set_flash("success", f"조를 저장했습니다. (신규 {counts.get('create', 0)} · 수정 {counts.get('update', 0)})")
    st.rerun()


def _plan_unit_delete(grid_df, dept_code: str) -> None:
    if grid_df is None:
        return
    readiness = _readiness()
    if not readiness.write_enabled:
        _OU.set_flash("error" if readiness.state is Readiness.PROBE_ERROR else "warning", readiness.message)
        st.rerun()
    live = live_rows(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    keys = [str(r["_row_id"])[2:] for _, r in sel.iterrows()]  # _row_id = "e:{dept}|{team}"
    if not keys:
        _OU.set_flash("warning", "삭제할 기존 조를 선택하세요.")
        st.rerun()
    plan = {"delete": [], "deactivate": []}
    for key in keys:
        dc, tc = key.split("|", 1) if "|" in key else (dept_code, key)
        refs = db.team_reference_counts(dc, tc)
        item = {"dept_code": dc, "team_code": tc, "refs": refs}
        (plan["deactivate"] if sum(refs.values()) > 0 else plan["delete"]).append(item)
    st.session_state[_OU.delete_plan_key] = plan
    st.rerun()


def _unit_confirm_bar(plan: dict, dept_code: str, readiness: ReadinessState) -> None:
    lines = []
    for it in plan["delete"]:
        lines.append(f"삭제 가능: {it['team_code']}")
    for it in plan["deactivate"]:
        lines.append(f"미사용 처리: {it['team_code']} — 사용자 {it['refs'].get('users', 0)}명 소속")
    actionable = bool(plan["delete"] or plan["deactivate"]) and readiness.write_enabled
    result = confirm_bar(
        _OU, title="선택한 조를 참조 확인 후 미사용/삭제 처리합니다.",
        lines=lines, confirm_label="삭제 실행", confirm_enabled=actionable, scope="del",
    )
    if result == "confirm":
        _execute_unit_delete(plan, dept_code)
    elif result == "cancel":
        st.session_state.pop(_OU.delete_plan_key, None)
        st.rerun()


def _execute_unit_delete(plan: dict, dept_code: str) -> None:
    n_del = 0
    failed: list[str] = []
    for it in plan["delete"]:
        try:
            db.delete_team(it["dept_code"], it["team_code"])
            n_del += 1
        except db.DATA_SOURCE_ERRORS:
            failed.append(it["team_code"])
    deact = plan["deactivate"]
    n_deact = 0
    if deact:
        try:
            store = db.get_org_teams().copy()
            for it in deact:
                mask = (
                    (store["dept_code"].astype(str) == it["dept_code"])
                    & (store["team_code"].astype(str) == it["team_code"])
                )
                n_deact += int(mask.sum())
                store.loc[mask, "is_active"] = False
            db.save_org_teams(store[db.ORG_TEAM_COLUMNS])
        except db.DATA_SOURCE_ERRORS:
            n_deact = 0
            failed.extend(it["team_code"] for it in deact)
    st.session_state.pop(_OU.delete_plan_key, None)
    _load_units(dept_code)
    _finish_delete(_OU, "조", n_del, n_deact, None, failed)


# ---------- 그룹 구조 검증(교차 화면 회귀 호환 순수 함수) ----------
def _group_structure_errors(merged: pd.DataFrame) -> list[str]:
    """부서 프레임(department_group/group_sort_order) 기준 그룹순서 전역 유일 검증.

    migration 004 3시트 화면은 그룹을 organization_groups 1급 테이블로 관리하므로 이
    함수를 사용하지 않는다. 다만 교차 화면 회귀 테스트가 참조하는 순수 함수라 시그니처와
    동작(그룹 간 순서 중복·같은 그룹 순서 불일치 검출)을 보존한다.
    """
    errors: list[str] = []
    if merged is None or merged.empty or "department_group" not in merged:
        return errors
    frame = merged.copy()
    frame["department_group"] = frame["department_group"].astype(str).str.strip()
    frame["group_sort_order"] = pd.to_numeric(
        frame["group_sort_order"], errors="coerce"
    ).fillna(0).astype("int64")
    for group, sub in frame.groupby("department_group"):
        if not group:
            errors.append("그룹명이 비어 있는 부서가 있습니다: " + ", ".join(sub["dept_code"].astype(str)))
            continue
        orders = sorted(set(sub["group_sort_order"]))
        if len(orders) > 1:
            errors.append(f"그룹 '{group}'의 그룹순서가 서로 다릅니다: " + ", ".join(str(o) for o in orders))
    order_groups: dict[int, set] = {}
    for _, r in frame.iterrows():
        if r["department_group"]:
            order_groups.setdefault(int(r["group_sort_order"]), set()).add(r["department_group"])
    for order, names in sorted(order_groups.items()):
        if len(names) > 1:
            errors.append(f"그룹순서 {order}이(가) 여러 그룹에 중복되었습니다: " + ", ".join(sorted(names)))
    return errors


# ---------- 행 상태 · dirty · 오류/결과 배너 공통 헬퍼 ----------
def _apply_filter(df: pd.DataFrame, q: dict, code_col: str, name_col: str) -> pd.DataFrame:
    """사용 여부(3-state) + 검색어(코드·명칭 부분일치)로 조회 결과를 거른다."""
    if df is None or df.empty:
        return df
    if q.get("active") == "사용 중":
        df = df[df["is_active"].astype(bool)]
    elif q.get("active") == "사용 안 함":
        df = df[~df["is_active"].astype(bool)]
    term = str(q.get("search", "")).strip()
    if term:
        hit = (
            df[code_col].astype(str).str.contains(term, case=False, na=False, regex=False)
            | df[name_col].astype(str).str.contains(term, case=False, na=False, regex=False)
        )
        df = df[hit]
    return df


def _next_order(live: pd.DataFrame, col: str = "순서") -> int:
    """신규 행 기본 표시순서 = 현재 표시된 순서의 최대 + 1(없으면 1)."""
    if live is None or col not in live:
        return 1
    orders = pd.to_numeric(live[col], errors="coerce").dropna()
    return int(orders.max()) + 1 if len(orders) else 1


def _existing_count(rows: pd.DataFrame) -> int:
    if rows is None or rows.empty:
        return 0
    return int((rows["_row_state"].astype(str) == "existing").sum())


def _finish_delete(state: DraftState, noun: str, n_del: int, n_deact: int,
                   blocked, failed: list[str]) -> None:
    """삭제/미사용 실행 결과를 flash 로 통일 표기하고 rerun 한다(성공/실패 구분)."""
    parts = []
    if n_del:
        parts.append(f"{n_del}개 삭제")
    if n_deact:
        parts.append(f"{n_deact}개 미사용 처리")
    if blocked:
        parts.append(f"시스템 {noun} 제외: {', '.join(blocked)}")
    if failed:
        done = f"{noun} " + ", ".join(parts) + " · " if parts else ""
        state.set_flash(
            "error",
            f"{done}일부 {noun} 처리 실패: {', '.join(sorted(set(failed)))} — 다시 선택해 재시도하세요.",
        )
    else:
        msg = f"{noun}을(를) " + ", ".join(parts) + "했습니다." if parts else f"처리할 {noun}이(가) 없습니다."
        state.set_flash("success" if (n_del or n_deact) else "warning", msg)
    st.rerun()


def _error_banner(title: str, errors: list[str]) -> None:
    """§15/§21 오류 요약 배너 — 사유 목록을 배너 하단에 붙인다. draft 는 재적재하지 않는다."""
    body = "".join(f"<div>· {escape(str(e))}</div>" for e in (errors or []))
    banner("danger", title, extra=(f"<div class='keys'>{body}</div>" if body else ""))


def _set_baseline(state: DraftState, frame: pd.DataFrame, data_cols: list[str]) -> None:
    """dirty 비교 기준선(로드 시점 값)을 저장한다 — 셀 편집을 기존 값과 대조하기 위함."""
    base: dict[str, tuple] = {}
    if frame is not None and not frame.empty:
        for _, r in frame.iterrows():
            base[str(r["_row_id"])] = tuple(str(r.get(c, "")) for c in data_cols)
    st.session_state[state.key("baseline")] = base


def _dirty_counts(state: DraftState, live: pd.DataFrame, data_cols: list[str]) -> tuple[int, int]:
    """(신규 행 수, 기존 변경 행 수) — §20 dirty_total 공식 입력."""
    base = st.session_state.get(state.key("baseline"), {})
    new_cnt = changed_cnt = 0
    if live is None or live.empty:
        return 0, 0
    for _, r in live.iterrows():
        rid = str(r["_row_id"])
        vals = tuple(str(r.get(c, "")) for c in data_cols)
        if str(r["_row_state"]) == "new":
            if any(str(v).strip() for v in vals):
                new_cnt += 1
        elif rid in base and vals != base[rid]:
            changed_cnt += 1
    return new_cnt, changed_cnt


def _reconcile_org_partial(
    state: DraftState, live: pd.DataFrame, result, data_cols: list[str], *, owner=None,
) -> None:
    """부분 성공(partial) 후 **성공 자연키 행만** baseline·초안에 reconcile 한다(§22).

    users 패턴(신규행 e:{key} 전환 + baseline 갱신)을 조직 3시트로 이식한 것이다.
    work_types 패턴은 신규행 전환이 불완전(_row_state==existing 만 baseline 갱신)해
    참조만 했다.

    - 성공 행: 신규→기존 전환(``_row_id='e:{code}'`` / 조는 ``'e:{dept}|{team}'``),
      선택 해제, baseline 을 현재값으로 갱신(``_set_baseline``/``_dirty_counts`` 와 동일
      튜플 포맷)해 더 이상 dirty 로 보이지 않게 한다.
    - 실패·미저장 행: draft·dirty·셀 값을 **그대로 유지**(건드리지 않음) — 재시도 대상.
    - **unknown(재조회 필요)은 이 함수를 호출하지 않는다**(reconcile 금지, 호출부 책임).

    이 함수는 인자 ``state`` 범위의 rows/baseline/nonce **만** 수정한다 — 다른 범위
    (_GRP/_OD/_OU)의 상태를 일절 건드리지 않아 한 범위 저장이 다른 범위의 dirty/적재를
    새게 하지 않는다. 자연키: 그룹=group_code, 부서=dept_code, 조=(dept_code, team_code).
    조는 시트에 부서코드가 없으므로 적재 시점 소속 부서(``owner``)로 복합키를 만든다.
    """
    if live is None or getattr(live, "empty", True):
        return
    row_cols = ["_row_id", "_row_state", "_sel", *data_cols]
    composite = owner is not None
    owner_str = str(owner).strip() if composite else ""
    saved = set()
    for k in (getattr(result, "succeeded_keys", None) or []):
        if isinstance(k, (tuple, list)):
            saved.add(tuple(str(x).strip() for x in k))
        else:
            saved.add(str(k).strip())
    frame = live[row_cols].copy().reset_index(drop=True)
    baseline = dict(st.session_state.get(state.key("baseline")) or {})
    for idx, r in frame.iterrows():
        code = str(r.get("코드") or "").strip()  # 세 시트 모두 코드 컬럼명은 "코드"
        if not code:
            continue
        key = (owner_str, code) if composite else code
        if key not in saved:
            continue  # 실패/미저장 행 — draft·dirty 유지(건드리지 않음)
        rid = str(r["_row_id"])
        if str(r["_row_state"]) != "existing":
            rid = f"e:{owner_str}|{code}" if composite else f"e:{code}"
            frame.at[idx, "_row_id"] = rid
            frame.at[idx, "_row_state"] = "existing"
            frame.at[idx, "_sel"] = False
        baseline[rid] = tuple(str(r.get(c, "")) for c in data_cols)
    state.set_rows(frame[row_cols].reset_index(drop=True))
    st.session_state[state.key("baseline")] = baseline
    state.bump_nonce()  # 리마운트로 reconcile 된 행(성공=clean·기존, 실패=draft)을 반영


def _render_saved_ledger(state: DraftState) -> None:
    """직전 부분성공 저장의 원장(성공/실패 칩)을 1회 표시한다(reconcile 후 rerun 경로).

    partial 저장은 성공 행을 reconcile 하고 rerun 하므로, 원장은 세션에 보관해 다음
    런의 시트 배너 슬롯에서 소비한다(성공 배너가 rerun 으로 유실되지 않게 함)."""
    result = st.session_state.pop(state.key("save_ledger"), None)
    if result is not None:
        ledger_banner(result)


def _sync_rows(state: DraftState, grid_df: pd.DataFrame, row_cols: list[str]) -> bool:
    """붙여넣기로 생긴 무명 신규 행에 _row_id/_row_state 부여 + − 제거 행 반영.

    구조 변경이 있으면 Python 권위 상태(state.rows)를 갱신하고 True 를 반환한다."""
    if grid_df is None or grid_df.empty or "_row_id" not in grid_df.columns:
        return False
    removed = (
        grid_df["_removed"].fillna("").astype(str).str.strip() == "1"
        if "_removed" in grid_df
        else pd.Series(False, index=grid_df.index)
    )
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
    state.set_rows(live[list(row_cols)].reset_index(drop=True))
    state.bump_nonce()
    return True
