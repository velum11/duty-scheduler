"""개선조치 관리 — WORKLIST(DESIGN.md §2) + CAPA 폐루프.

§2 WORKLIST 골격을 그대로 구현한다(2026-08-18 §7.1 확정 이관 — 구 "KPI 스트립 + 큐 칩
스트립 + 전체폭 상세" 골격 폐기):

    제목/설명 → [상태 탭: 확인대기 n · 진행·미작성 n · 확인 완료 n · 기한초과 n · 전체 n]
    → [담당자·기간 조건] → 헤어라인 → 2열( 목록 33% | 상세 67% )
      목록 : 2줄 고정 행(제목/경과일 · 보고번호·소속/조치 단계) + 좌측 2px 상태 보더
      상세 : 식별자 + 상태 배지 + 상태 결과 + 대상 제목 + 메타
             → 주요 내용 표(라벨 열 + 값 열 1개) → CAPA 결정 컨트롤 → 실행(액션·2단계 종결)

이관에서 바뀐 것(구조·표기만, 기능 계약 불변)
  - **지표 타일 제거**(§4-1·§2) — ``erp.metric_strip`` 4장을 없애고 그 건수를 **상태 탭
    라벨**로 옮겼다. 종전 타일은 클릭·필터링이 없는 순수 HTML 이라 목록을 바꾸지 못했다.
    같은 건수가 이제 탭으로서 목록을 실제로 바꾼다.
  - **조치 단계 필터 → 상태 탭**(§4-2) — 같은 축의 진입점을 두 곳 두지 않는다. 종전
    조건 패널의 ``조치 단계`` select 는 폐지하고 탭이 그 축을 소유한다. 조건 패널에는
    축이 다른 ``담당자``·``기간``만 남는다.
  - **어휘 통일**(§3.6) — ``확정 등급 → 평가 등급``(상세 메타). 영문 코드값
    (``confirmed_grade``)은 불변이며 한글 라벨만 통일한다.
  - **상태의 결과 표기**(§3.3) — 배지 옆에 그 단계가 무엇을 막고 여는지 한 줄
    (``확인됨`` 옆 ``조치 수정 잠김 · 보고서 종결 가능``).
  - **근거 → 결정 → 실행 순서 정정**(§2) — 종전에는 작업 내용·현장 설명이 액션 **뒤**의
    expander 에 있었다(판정 자료가 판정 컨트롤보다 뒤). 주요 내용 표로 끌어올렸다.
  - **목록 정렬** — 경과일(접수일 ``created_at`` 기준, §7.2-4) 내림차순. 색은 칠하지
    않는다(§7.2-4-b). 기한초과는 좌측 보더 + 행 텍스트로 드러낸다(due_date 는 데이터에
    있는 실제 기한이라 SLA 추정이 아니다).

기능 계약(불변 — CAPA 폐루프 핵심, 표현 계층만 교체):
  - 행단위 권한(담당자=조치저장/제출, 확인자=확인/재조치요청, 평가자=배정/보고서 종결)과
    서버측 인가·자기확인 차단·007 하드게이트·2단계 종결 RPC 경로 변경 0(modules/db.py 무수정).
  - 워크플로 액션 전부 유지: 조치 저장/배정 저장/저장 · 제출 · 확인 · 재조치 요청 · 보고서 종결.
    역할별 비활성/숨김 규칙 현행 유지. 신원은 항상 ``auth.get_current_user()``.
  - 큐 = 현재 사용자 역할 기준 처리 대상(actor-aware ``list_near_miss_improvements`` +
    담당자 스코핑 ``_scope_reports``).
"""
from __future__ import annotations

# DESIGN.md §2 WORKLIST — 상태 탭 + 2열(목록 33% / 상세 67%).
SCREEN_ARCHETYPE = "WORKLIST"
# §0 — 이 화면이 내리는 결정(기계 검증은 아직 없다, §5).
SCREEN_DECISION = "이 건의 개선조치를 확인할 것인가, 재조치를 요청할 것인가, 보고서를 종결할 것인가"
SCREEN_EVIDENCE = ("사고 내용·원인·대책", "등록된 조치 내용·결과", "조치 기한과 경과",
                   "담당자·확인자 배정")

from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st

from modules import auth, db
from views import workspace
from views.common import erp, scaffold, worklist
from views.common import near_miss as nm_common
from views.master import (
    TOKENS,
    DraftState,
    Readiness,
    ReadinessState,
    banner,
    empty_state,
    lifecycle_badge_html,
    show_flash,
)

_STATE = DraftState("nm_impr")
_PAGE_ID = _STATE.page_id
_SEL_KEY = "nm_impr_selected_id"              # 상세에 열린 보고서 id(문자열).
_TAB_KEY = "nm_impr_tab"                      # 상태 탭(§2: 탭이 목록을 실제로 바꾼다).
_CLOSE_CONFIRM_KEY = "nm_impr_close_confirm"  # 2단계 종결 확인 중인 보고서 id.

_IMPROVEMENT_DESC = "평가 확정된 아차사고의 개선조치를 등록·확인하고 보고서를 종결합니다."

# 이 화면이 다루는 큐 — 평가 확정(EVALUATED) = 개선조치 진행·종결 대기.
_QUEUE_STATUS = "EVALUATED"

_SUBMIT_LABEL = {"DRAFT": "작성중", "SUBMITTED": "제출됨"}
_CONFIRM_LABEL = {"PENDING": "확인대기", "CONFIRMED": "확인됨", "REJECTED": "반려"}
_CONFIRMED = "CONFIRMED"
# 발생원인 코드→한글 라벨(H2) — 평가/조회 화면과 동일 매핑. 표시 전용이며 DB 코드·필터·저장
# payload 는 불변(코드값 유지). 미등록 코드는 원문 fallback(라벨 누락이 화면을 깨지 않게).
_CAUSE_LABEL = {
    "JAM": "끼임", "FALL": "추락", "DROP": "낙하물", "HIT": "부딪힘",
    "SLIP": "미끄러짐", "BURN": "화상", "PINCH": "협착", "ETC": "기타",
}
# 등급 색·순서 — 조회/내 아차사고/평가와 **같은 매핑**(TOKENS 재사용, 새 색 없음).
_GRADE_COLOR = {
    "S": TOKENS["danger"], "A": TOKENS["gold"], "B": TOKENS["warn"],
    "C": TOKENS["info"], "D": TOKENS["ink-3"],
}
_GRADE_LEVEL = {"S": 4, "A": 3, "B": 2, "C": 1, "D": 0}


def _grade_mark(grade, empty: str) -> str:
    """등급 마크 HTML(공용 kit primitive) — 빈 값은 중립 점 마커 + ``empty`` 라벨."""
    g = str(grade or "").strip().upper()
    if not g:
        return erp.grade_mark_html(empty, TOKENS["ink-3"], level=None)
    return erp.grade_mark_html(g, _GRADE_COLOR.get(g, TOKENS["ink-2"]), level=_GRADE_LEVEL.get(g))


# ── §1.3 팔레트 (토큰 밖 색 금지 §4-7) — 리터럴 고정으로 새 색 유입 차단. ──
_INK = "#1c1a17"          # 본문
_INK2 = "#4a453d"         # 보조(섹션 라벨)
_FAINT = "#6b665d"        # 읽는 텍스트 최저 대비(5.1:1)
_LINE = "#e6e2da"         # 행 헤어라인
_LINE_SEC = "#e0dbd2"     # 섹션 헤어라인
_NEUTRAL = "#5c564d"      # §1.3 종결·중립 배지 텍스트(6.4:1)
# §1.2(2026-08-19 개정) — 글꼴은 **Pretendard 하나**다. 모노 서체 지정(_MONO = IBM Plex
# Mono)은 폐지했고, 세로로 정렬되는 숫자는 ``font-variant-numeric: tabular-nums`` 로만
# 자릿수를 맞춘다. 화면이 자기 글꼴을 선언하지 않으므로 앱 폰트(--cd-sans)를 그대로 상속한다.
_NUM = "font-variant-numeric:tabular-nums;"

# 상태 배지 색(§1.3 의미 색 — status_badge_html 이 옅은 배경/테두리를 파생).
_SUBMIT_COLOR = {"DRAFT": _NEUTRAL, "SUBMITTED": "#2f4d99"}
_CONFIRM_COLOR = {"PENDING": "#8a6212", "CONFIRMED": "#2f6b45", "REJECTED": "#9c3232",
                  "미작성": _NEUTRAL}
# 목록 행 좌측 2px 보더 색(§2: 상태는 줄 수가 아니라 보더 색으로 표현한다).
_STAGE_ACCENT = {
    "미작성": _NEUTRAL, "작성중": "#8a6212", "확인대기": "#2f4d99",
    "확인됨": "#2f6b45", "반려": "#9c3232",
}
_OVERDUE_ACCENT = "#9c3232"   # 기한초과는 단계색을 덮어쓴다(지금 처리해야 하는 신호)
_OVERDUE_MARK = "기한초과"
# §3.3 — 단계 배지 옆에 그 단계가 무엇을 막고 무엇을 여는지 한 줄로 적는다.
# 근거: db.upsert_near_miss_improvement(CONFIRMED 편집 차단) · confirm/reject 는 제출·
# 확인대기에서만 · close 는 확인됨에서만.
_STAGE_EFFECT = {
    "미작성": "담당자 배정·조치 등록 필요 · 종결 불가",
    "작성중": "담당자 편집 가능 · 확인 불가",
    "확인대기": "담당자 수정 잠김 · 확인자 판정 대기",
    "확인됨": "조치 수정 잠김 · 보고서 종결 가능",
    "반려": "담당자 재조치 필요 · 종결 불가",
}

_LOAD_FAILED_LABEL = "조회실패"
_NOT_READY_MSG = (
    "개선조치 스키마(007)가 아직 적용되지 않아 저장·제출·확인·종결을 진행할 수 없습니다"
    "(조회만 가능). 스키마를 적용한 뒤 다시 시도하세요."
)
_PROBE_ERROR_MSG = (
    "개선조치 스키마 상태 확인 실패 — 재확인이 필요합니다(확인 전까지 쓰기는 차단됩니다)."
)
_STALE_MARK = "이미 변경"  # db 원문 일부 — stale 충돌(다른 사용자 선처리)은 warning 로 분기.

# 상태 탭 — 라벨은 종전 지표 타일의 이름을 그대로 물려받는다(§4-1: 지표는 탭 건수로).
# 앞 세 탭은 큐를 나누는 분할이고(합=전체), '기한초과'는 그 위에 겹치는 부분집합이다.
_TAB_PENDING = "확인대기"
_TAB_PROGRESS = "진행·미작성"
_TAB_CONFIRMED = "확인 완료"
_TAB_OVERDUE = "기한초과"
_TAB_ALL = "전체"
_TABS: tuple[str, ...] = (_TAB_PENDING, _TAB_PROGRESS, _TAB_CONFIRMED, _TAB_OVERDUE, _TAB_ALL)
#: ``_kpi_items`` 가 총계에 쓰는 라벨(계약 테스트가 고정) — '전체' 탭이 같은 값을 쓴다.
_TOTAL_LABEL = "종결 대기"

# 목록 열 자체 스크롤 높이(§2: 목록과 상세는 독립 스크롤). 뷰포트 파생값이며 간격 토큰이 아니다.
_LIST_HEIGHT = 520

_IMPR_CSS = f"""
<style>
/* 상태 탭 — compact 히트영역 34px(공용 기본 30.1px 미달 보정). 선택자는 위젯 key
   (_TAB_KEY)에서 오는 st-key 클래스다. 한글 라벨이라 모노·letter-spacing 을 걸지 않는다. */
.st-key-nm_impr_tab button {{
  min-height:34px !important; font-weight:600 !important;
}}
/* 라벨 글자는 내부 <p> 소유 — button 에만 걸면 12.25px 로 남는다(실측). §1.2 14px. */
.st-key-nm_impr_tab button p {{ font-size:14px !important; font-weight:600 !important; }}
/* 선택 탭 라벨 대비: #c2410c on #efe0d7 = 4.03:1(§5 미달) → #a3350a = 5.31:1. */
.st-key-nm_impr_tab button[aria-checked="true"] p {{ color:#a3350a !important; }}
/* 결정 액션·조건 컨트롤 히트영역 — 평가 관리(:173)에는 있는 규칙이 여기엔 없어
   결정 버튼이 30.1px, 셀렉트 33px, 날짜 31.1px 로 §1.4 compact(34~38) 미달이었다. */
[class*="st-key-nm_impr_da_"] button, [class*="st-key-nm_impr_close_da_"] button {{
  min-height:34px !important; border-radius:8px !important; font-weight:600 !important;
  white-space:nowrap !important;
}}
[class*="st-key-nm_impr_da_"] button p, [class*="st-key-nm_impr_close_da_"] button p {{
  font-size:14px !important; font-weight:600 !important;
}}
[class*="st-key-nm_impr_flt_"] div[data-baseweb="select"] > div,
[class*="st-key-nm_impr_flt_"] .react-aria-ComboBox input,
[class*="st-key-nm_impr_flt_"] .react-aria-ComboBox div[role="group"],
[class*="st-key-nm_impr_assignee_"] div[data-baseweb="select"] > div,
[class*="st-key-nm_impr_assignee_"] .react-aria-ComboBox input,
[class*="st-key-nm_impr_assignee_"] .react-aria-ComboBox div[role="group"],
[class*="st-key-nm_impr_confirmer_"] div[data-baseweb="select"] > div,
[class*="st-key-nm_impr_confirmer_"] .react-aria-ComboBox input,
[class*="st-key-nm_impr_confirmer_"] .react-aria-ComboBox div[role="group"],
[class*="st-key-nm_impr_due_"] input {{ min-height:34px !important; }}
/* 비활성 라벨은 Streamlit 기본 #9e9c98(2.46:1, §1.3 팔레트 밖)이다. WCAG 는 비활성을
   예외로 두지만 같은 화면에서 5.04:1 과 2.46:1 이 섞이는 것은 결함이다 — ink-3 로 통일. */
[class*="st-key-nm_impr_da_"] button:disabled p,
[class*="st-key-nm_impr_close_da_"] button:disabled p {{ color:{_FAINT} !important; }}
/* <599px: 목록 고정 높이(520)가 콘텐츠보다 커서 상세가 폴드 밖으로 밀린다(실측). */
@media (max-width:598px) {{
  .st-key-nm_impr_listbox {{ height:auto !important; max-height:none !important; }}
}}
/* 섹션 라벨 — 한글이라 letter-spacing 을 주지 않는다(자간이 벌어진다). */
.nm-sec {{ font-size:12px; font-weight:600; color:{_INK2}; margin:0 0 8px; }}
</style>
"""


# ---------- 진입 ----------
def render(user: dict) -> None:
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="개선조치 관리",
        desc=_IMPROVEMENT_DESC,
        breadcrumb="아차사고 › 개선조치 관리",
        badges=scaffold.mode_badge(),
    )
    st.markdown(_IMPR_CSS, unsafe_allow_html=True)
    # 접근 경계 — 배정 기반 접근 facade(has_near_miss_improvement_access): 평가자/ADMIN·배정
    # 담당자·지정 확인자는 True, 그 외/미인증/비활성은 False(fail-closed·비크래시).
    if not db.has_near_miss_improvement_access(user):
        empty_state(
            "개선조치 관리 권한이 없습니다",
            "배정된 담당자·지정 확인자, 또는 관리자·매니저·안전담당자만 개선조치를 다룰 수 있습니다.",
        )
        return
    _render_body(user)


def _readiness() -> ReadinessState:
    state = db.near_miss_improvement_schema_probe()
    if state == db.READINESS_READY:
        return ReadinessState.ready()
    if state == db.READINESS_PROBE_ERROR:
        return ReadinessState.probe_error(_PROBE_ERROR_MSG)
    return ReadinessState.not_ready(_NOT_READY_MSG)


def _render_body(user: dict) -> None:
    show_flash(_STATE)
    readiness = _readiness()
    readiness.banner()
    if readiness.state is Readiness.PROBE_ERROR:
        if st.button("스키마 재확인", key="nm_impr__recheck", icon=":material/refresh:"):
            db.near_miss_improvement_schema_probe(force=True)
            st.rerun()

    try:
        reports = _load_queue()
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"종결 대기 목록을 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("종결 대기 목록을 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    # 큐 스코핑은 actor-aware — 평가자/ADMIN 은 전체, 담당자·지정 확인자는 자기 배정건만.
    is_reviewer = auth.can_evaluate_near_miss(user)
    improvements, load_failed = _improvements_for(reports, user)
    if load_failed:
        st.error(
            "개선조치 목록을 불러오지 못했습니다 — 담당자·확인상태는 실제 상태가 아닙니다. "
            "데이터 연결 상태를 확인하고 새로고침하세요."
        )
    scoped = _scope_reports(reports, improvements, is_reviewer, load_failed)

    # ── 상태 탭(§2) — 지표 타일 대신 여기에 건수를 싣는다(§4-1). 건수는 항상 전체 스코프
    # 큐 기준이며(담당자·기간 조건으로 왜곡하지 않는다) 탭 선택만이 목록을 바꾼다. ──
    tab = _render_tabs(_tab_counts(scoped, improvements, load_failed))

    # ── 축이 다른 조건(담당자·기간)만 남긴다 — 조치 단계 축은 탭이 소유한다(§4-2). ──
    fq, fq_active = _collect_impr_filters(scoped, improvements)
    scoped_view = _apply_impr_filters(scoped, improvements, dict(fq, tab=tab))

    ordered = _ordered_ids(scoped_view)
    reports_by_id = {}
    if scoped_view is not None and not scoped_view.empty:
        reports_by_id = {str(r["id"]): r for _, r in scoped_view.iterrows()}

    # 선택 보관은 호출부 책임(erp.select_list 계약). 탭·조건 전환으로 선택이 목록에서 빠지면
    # 첫 건으로 되돌리고 2단계 종결 확인을 초기화한다(오처리 방지).
    selected_id = st.session_state.get(_SEL_KEY)
    if selected_id not in ordered:
        selected_id = ordered[0] if ordered else None
        st.session_state[_SEL_KEY] = selected_id
        st.session_state.pop(_CLOSE_CONFIRM_KEY, None)

    list_col, detail_col = erp.master_detail_frame(list_ratio=1, detail_ratio=2)
    with list_col:
        picked = _render_list(ordered, reports_by_id, improvements, selected_id, tab)
        if picked and picked != selected_id:
            st.session_state[_SEL_KEY] = picked
            st.session_state.pop(_CLOSE_CONFIRM_KEY, None)
            st.rerun()
    with detail_col:
        if selected_id is None:
            body = (f"조건에 해당하는 건이 없습니다. '{tab}' 탭과 담당자·기간 조건을 조정하세요."
                    if fq_active else f"'{tab}' 탭에 표시할 개선조치 건이 없습니다.")
            erp.detail_empty("처리할 건이 없습니다", body)
            return
        _render_detail(user, readiness)


# ---------- 데이터 적재 ----------
def _load_queue() -> pd.DataFrame:
    """종결 대기 = 평가 확정(EVALUATED) 활성 보고서. CLOSED 는 큐에서 빠진다."""
    df = db.get_near_miss_reports({"status": _QUEUE_STATUS})
    if df is None or df.empty:
        return df
    return df.reset_index(drop=True)


def _improvements_for(reports: pd.DataFrame, user: dict) -> tuple[dict, bool]:
    """보고서별 개선조치(report_id(str)→자연키 dict)와 조회 실패 플래그.

    actor-aware 큐 스코핑 facade(``list_near_miss_improvements``)로 한 번에 조회한다 —
    평가자/ADMIN 은 전체, 그 외(담당자·지정 확인자)는 자기 배정건만. 007 미준비면 빈 dict
    (정상 부재='미작성', readiness 배너로 안내). READY 이후 실제 조회 오류는 빈 dict 로
    위장하지 않고 ``load_failed=True`` 로 표면화한다(오류≠정상 부재)."""
    if reports is None or reports.empty:
        return {}, False
    report_ids = list(reports["id"].astype(str))
    try:
        return db.list_near_miss_improvements(report_ids, current_user=user), False
    except Exception:
        return {}, True


def _scope_reports(reports: pd.DataFrame, improvements: dict,
                   is_reviewer: bool, load_failed: bool) -> pd.DataFrame:
    """담당자(비평가자) 시야를 자기 배정건으로 좁힌다. 평가자/ADMIN 은 전체 유지.

    조회 실패 시 담당자는 자기 배정 식별이 불가하므로 빈 큐로 fail-closed 한다."""
    if reports is None or reports.empty or is_reviewer:
        return reports
    if load_failed:
        return reports.iloc[0:0]
    ids = set(improvements.keys())
    return reports[reports["id"].astype(str).isin(ids)].reset_index(drop=True)


def _ordered_ids(df: pd.DataFrame) -> list[str]:
    """**경과일 내림차순**(오래 묵은 건 먼저, §7.2-4-b). 경과일은 접수일(``created_at``)
    파생이며 ``incident_date`` 는 동순위 tie-break 로만 쓴다."""
    if df is None or df.empty:
        return []
    return worklist.order_by_elapsed([
        (r["id"], r.get("created_at"), r.get("incident_date")) for _, r in df.iterrows()
    ])


# ---------- 조치 단계·기한 파생 ----------
def _impr_stage(imp) -> str:
    """개선조치 한 건의 '조치 단계' 라벨(제출/확인 상태 파생 — 탭·행·상세 단일 어휘).

    미작성(imp 없음) < 작성중(DRAFT) < 확인대기(SUBMITTED·PENDING) < 확인됨(CONFIRMED) /
    반려(REJECTED). 확정 상태(확인됨/반려)를 제출 상태보다 우선 판정한다.

    2026-08-19: 파생 자체는 공용(``views.common.near_miss.improvement_stage``)으로 옮겼다 —
    아차사고 조회의 '개선조치' 열이 같은 낱말을 써야 하고, 두 화면이 각자 파생하면 한쪽만
    바뀌는 §3.6 결함이 그대로 재발한다. 이 함수는 화면 로컬 이름을 유지하는 얇은 위임이다."""
    return nm_common.improvement_stage(imp)


def _is_overdue(imp, today: str) -> bool:
    """조치 기한(``due_date``) 경과 & 미확인. ISO 날짜 문자열 사전식 비교(안전).

    임의로 정한 SLA 가 아니라 **데이터에 저장된 실제 기한**이라 §7.2-4-b(경과일에 색을
    칠하지 않는다)와 충돌하지 않는다 — 경과일과 기한초과는 다른 값이다."""
    if not imp or str(imp.get("confirm_status") or "") == _CONFIRMED:
        return False
    due = str(imp.get("due_date") or "").strip()
    return bool(due) and due < today


def _confirm_state_of(imp) -> str:
    if not imp:
        return "미작성"
    return str(imp.get("confirm_status") or "").strip() or "미작성"


# ---------- 상태 탭 ----------
def _kpi_items(scoped: pd.DataFrame, improvements: dict, load_failed: bool) -> list[tuple]:
    """상태 탭 건수의 단일 출처 — ``[(label, value)]``.

    **함수명은 종전 KPI 스트립 시절 이름을 유지한다** — 이 파생 계약("조회 실패 시 파생
    지표를 0 으로 위장하지 않고 '—' 로 표면화한다")을 ``test_near_miss_error_surfacing``
    이 이 이름으로 고정하고 있고, 이름만 바꾸면 계약 추적이 끊긴다. 렌더 수단은 지표
    타일에서 **상태 탭**으로 바뀌었다(§4-1: 지표가 목록을 바꾸지 않으면 자리값을 못 한다).

    전부 기존 데이터에서 파생한다: 확인대기(제출·확인대기) · 진행·미작성(작성 전/작성중/
    반려) · 확인 완료(CONFIRMED) · 기한초과(due_date 경과 & 미확인) · 종결 대기(큐 크기).
    앞 세 개는 큐를 나누는 분할이고 기한초과는 그 위에 겹치는 부분집합이다.
    조회 실패 시 파생 4종은 '—'(오류≠0)이며 큐 크기만 실수치를 낸다.
    """
    total = 0 if scoped is None or scoped.empty else len(scoped)
    if load_failed:
        return [
            (_TAB_PENDING, "—"), (_TAB_PROGRESS, "—"),
            ("확인 완료", "—"), ("기한초과", "—"), (_TOTAL_LABEL, total),
        ]
    today = date.today().isoformat()
    pending = progress = confirmed = overdue = 0
    if scoped is not None and not scoped.empty:
        for _, r in scoped.iterrows():
            imp = improvements.get(str(r["id"]))
            stage = _impr_stage(imp)
            if stage == "확인됨":
                confirmed += 1
            elif stage == "확인대기":
                pending += 1
            else:
                progress += 1
            if _is_overdue(imp, today):
                overdue += 1
    return [
        (_TAB_PENDING, pending), (_TAB_PROGRESS, progress),
        ("확인 완료", confirmed), ("기한초과", overdue), (_TOTAL_LABEL, total),
    ]


def _tab_counts(scoped: pd.DataFrame, improvements: dict, load_failed: bool) -> dict:
    """탭 라벨에 붙일 건수 사전. '전체' 탭은 큐 크기(``종결 대기``)와 같은 값이다."""
    counts = {label: value for label, value, *_ in
              _kpi_items(scoped, improvements, load_failed)}
    counts[_TAB_ALL] = counts.get(_TOTAL_LABEL, 0)
    return counts


def _render_tabs(counts: dict) -> str:
    """상태 탭을 렌더하고 선택된 탭 이름을 반환한다(§2 골격의 두 번째 블록).

    ``st.tabs`` 를 쓰지 않는다 — 기본값이 모든 탭을 미리 렌더해 "탭이 목록을 바꾼다"는
    §2 계약이 성립하지 않는다. ``st.segmented_control`` 은 클릭=rerun 이라 필터링이 자동
    성립한다. ``required=True`` 로 선택 해제를 막아 "아무 탭도 아닌" 상태를 만들지 않는다.
    """
    # 첫 진입 탭은 **비어 있지 않은 첫 탭**이다(§3.5: 애초에 빈 영역이 생기지 않게 배치).
    # 처리 우선순위 순서(확인대기 → 진행·미작성 → 확인 완료 → 기한초과 → 전체)로 훑어
    # 건수가 있는 첫 탭을 고른다. 조회 실패 시 파생 건수는 '—'(문자열)라 truthy 이므로
    # 그대로 첫 탭에 머문다. 이미 사용자가 고른 탭은 건드리지 않는다.
    if st.session_state.get(_TAB_KEY) not in _TABS:
        st.session_state[_TAB_KEY] = next(
            (name for name in _TABS if counts.get(name, 0)), _TAB_PENDING)
    picked = st.segmented_control(
        "조치 단계",
        _TABS,
        key=_TAB_KEY,
        required=True,
        format_func=lambda name: f"{name} {counts.get(name, 0)}",
        label_visibility="collapsed",
        width="content",
    )
    return picked if picked in _TABS else _TAB_PENDING


# ---------- 조건(담당자·기간) ----------
_FILTER_PID = f"{_PAGE_ID}_flt"          # condition_panel page_id(세션 위젯 키 접두)


def _collect_impr_filters(scoped: pd.DataFrame, improvements: dict) -> tuple[dict, bool]:
    """조건 줄(담당자·기간)을 렌더하고 (조건 dict, 활성여부)를 반환한다.

    **조치 단계 축은 여기 없다** — 상태 탭이 소유한다(§4-2: 같은 기능의 진입점을 두 곳
    두지 않는다). 담당자 옵션은 현재 스코프 큐에 실제 배정된 담당자만(+전체)으로 구성한다
    (허수 옵션 방지). 기본 기간은 '전체'. 제출 버튼 없이 변경 즉시 반영(뷰단 조건)."""
    period_on = st.session_state.get(f"{_FILTER_PID}_period_mode") == "기간 지정"
    assignees: list[str] = []
    seen: set = set()
    if scoped is not None and not scoped.empty:
        for _, r in scoped.iterrows():
            imp = improvements.get(str(r["id"]))
            emp = str((imp or {}).get("assignee_emp_no") or "").strip()
            if emp and emp not in seen:
                seen.add(emp)
                assignees.append(emp)
    assignees.sort()

    fields: list[erp.Field] = [
        erp.Field(key="assignee", label="담당자", kind="select", width=200,
                  options=[workspace.ALL] + assignees,
                  format_func=lambda e: "전체" if e == workspace.ALL else _user_label(e)),
        erp.Field(key="period_mode", label="기간", kind="select", width=140,
                  options=["전체", "기간 지정"]),
    ]
    if period_on:
        fields += [
            erp.Field(key="from", label="발생일(시작)", kind="date",
                      value=date.today() - timedelta(days=180), width=150),
            erp.Field(key="to", label="발생일(종료)", kind="date",
                      value=date.today(), width=150),
        ]
    v = erp.condition_panel(_FILTER_PID, fields, cols=4)

    on = v["period_mode"] == "기간 지정"
    q = {
        "assignee": v["assignee"],
        "date_from": v["from"].isoformat() if on and "from" in v else "",
        "date_to": v["to"].isoformat() if on and "to" in v else "",
    }
    active = (v["assignee"] != workspace.ALL) or on
    return q, active


def _matches_tab(tab: str, stage: str, overdue: bool) -> bool:
    """상태 탭 술어 — 탭 하나가 목록을 실제로 바꾼다(§2)."""
    if tab == _TAB_ALL:
        return True
    if tab == _TAB_OVERDUE:
        return overdue
    if tab == _TAB_CONFIRMED:
        return stage == "확인됨"
    if tab == _TAB_PENDING:
        return stage == "확인대기"
    return stage not in ("확인됨", "확인대기")   # 진행·미작성


def _apply_impr_filters(scoped: pd.DataFrame, improvements: dict, q: dict) -> pd.DataFrame:
    """상태 탭 + 조건(담당자·기간)을 적용한다(권한·스코핑 불변 — 표시 큐만 좁힌다)."""
    if scoped is None or scoped.empty:
        return scoped
    tab = q.get("tab") or _TAB_ALL
    assignee = q.get("assignee")
    date_from = q.get("date_from") or ""
    date_to = q.get("date_to") or ""
    today = date.today().isoformat()
    keep = []
    for idx, r in scoped.iterrows():
        imp = improvements.get(str(r["id"]))
        if not _matches_tab(tab, _impr_stage(imp), _is_overdue(imp, today)):
            continue
        if assignee not in (None, workspace.ALL):
            if str((imp or {}).get("assignee_emp_no") or "").strip() != str(assignee).strip():
                continue
        inc = str(r.get("incident_date") or "")
        if date_from and inc < date_from:
            continue
        if date_to and inc > date_to:
            continue
        keep.append(idx)
    if not keep:
        return scoped.iloc[0:0]
    return scoped.loc[keep].reset_index(drop=True)


def _user_label(emp_no) -> str:
    emp_no = str(emp_no or "").strip()
    if not emp_no:
        return "-"
    try:
        record = db.find_user_by_emp_no(emp_no)
    except Exception:
        return emp_no
    name = str(record.get("name") or "").strip() if record else ""
    return f"{name}({emp_no})" if name else emp_no


# ---------- 목록 열(33%) ----------
def _list_items(ordered: list[str], reports_by_id: dict, improvements: dict) -> list[dict]:
    """§2 목록 행 2줄 고정 — 1줄: 제목 / 경과일, 2줄: 보고번호·소속 / 조치 단계.

    "무엇을 먼저 처리할지 고를 근거"(경과일·소속·분류=조치 단계)를 담는다. 상태는 줄을
    늘리지 않고 좌측 2px 보더 색으로만 표현하며(§4-5 행 높이 불변), 기한초과는 보더를
    덮어쓰는 동시에 2줄 우측에 낱말로도 적는다(색 단독 신호 금지 §1.3).
    """
    today = date.today().isoformat()
    items: list[dict] = []
    for rid in ordered:
        # ``or {}`` 를 쓰지 않는다 — 값이 pandas Series 라 truthiness 평가에서
        # ValueError("truth value of a Series is ambiguous")로 화면이 통째로 죽는다.
        r = reports_by_id.get(rid)
        if r is None:
            r = {}
        imp = improvements.get(rid)
        stage = _impr_stage(imp)
        overdue = _is_overdue(imp, today)
        dept = str(r.get("dept_code") or "").strip()
        right = f"{stage} · {_OVERDUE_MARK}" if overdue else stage
        items.append({
            "key": rid,
            "line1_left": str(r.get("work_name") or "(제목 없음)"),
            "line1_right": worklist.elapsed_label(r.get("created_at")),
            # line2_left 는 kit 의 ``.esl-mono`` 로 렌더된다 — §1.2 개정(모노 폐지) 이후
            # 이 클래스는 tabular-nums 만 남았다(kit.py 정리 완료). 영숫자 식별자를 넣는
            # 관행은 유지한다 — 자릿수 정렬이 의미 있는 값이기 때문이다.
            "line2_left": str(r.get("report_no") or rid),
            # 소속·조치 단계는 sans 쪽(line2_right)에 모아 둔다(둘 다 한글이 올 수 있다).
            "line2_right": f"{dept} · {right}" if dept else right,
            "accent": _OVERDUE_ACCENT if overdue else _STAGE_ACCENT.get(stage, _NEUTRAL),
        })
    return items


def _render_list(ordered: list[str], reports_by_id: dict, improvements: dict,
                 selected_id, tab: str) -> str | None:
    """목록 열 렌더 — 이번 run 에 새로 클릭된 자연키를 반환한다(선택 보관은 호출부)."""
    with st.container(height=_LIST_HEIGHT, border=False, key="nm_impr_listbox"):
        return erp.select_list(
            "nm_impr_list",
            _list_items(ordered, reports_by_id, improvements),
            selected=str(selected_id) if selected_id is not None else None,
            empty=f"'{tab}' 탭에 표시할 건이 없습니다.",
        )


# ---------- 상세 열(67%) ----------
def _render_detail(user: dict, readiness: ReadinessState) -> None:
    selected_id = st.session_state.get(_SEL_KEY)
    if not selected_id:
        return

    try:
        report = db.get_near_miss_report(selected_id)
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"케이스를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("케이스를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    status = str(report.get("status") or "") if report else ""
    if report is None or status != _QUEUE_STATUS:
        # 다른 사용자가 먼저 종결(CLOSED)했거나 재개(IN_REVIEW)됐거나 삭제됨 — stale 선택 해제.
        st.session_state.pop(_SEL_KEY, None)
        st.session_state.pop(_CLOSE_CONFIRM_KEY, None)
        erp.detail_empty(
            "더 이상 종결 대기 상태가 아닙니다",
            "다른 사용자가 먼저 처리했을 수 있습니다 — 새로고침한 뒤 다시 선택하세요.",
        )
        return

    # 개선조치 프리필 조회 실패는 None('미작성')으로 접지 않고 표면화한다(덮어쓰기 저장 위험 차단).
    try:
        imp = db.get_near_miss_improvement(selected_id, current_user=user)
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"개선조치를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("개선조치를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    # 행단위 인가 — 이 개선조치(imp)에 대한 actor 능력으로 폼 편집·버튼을 가른다.
    #   can_work   = 저장된 담당자 본인 또는 ADMIN → 작업필드 편집·조치저장·제출.
    #   can_review = 지정 확인자 본인 또는 평가자/ADMIN → 확인·재조치요청·보고서 종결.
    #   can_assign = 평가자/ADMIN → 담당자·확인자 배정(select) 편집.
    can_work = auth.can_work_improvement(user, imp)
    can_review = auth.can_review_improvement(user, imp)
    can_assign = auth.can_evaluate_near_miss(user)

    # ── 근거(§2: 근거 → 결정 컨트롤 → 실행 버튼) ──
    st.markdown(_detail_read_html(report, imp, status), unsafe_allow_html=True)

    # ── 결정 컨트롤(CAPA 폼) → 실행(역할별 scope 액션) ──
    st.markdown(
        f"<div style='border-top:1px solid {_LINE_SEC};margin:12px 0 12px;'></div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div class='nm-sec'>개선조치</div>", unsafe_allow_html=True)
    form = _render_capa_form(selected_id, imp, readiness, can_work=can_work, can_assign=can_assign)
    _render_actions(user, report, imp, form, readiness,
                    can_work=can_work, can_review=can_review, can_assign=can_assign)


def _detail_read_html(report: dict, imp, status: str) -> str:
    """상세 머리 + 주요 내용 표.

    머리 — 식별자(16/600 모노) + 상태 배지 + **단계 결과**(§3.3) + 제출/확인 배지 +
    대상 제목(20/600) + 메타(발생일·접수 경과·소속·신고자·평가 등급).
    본문 — **라벨 열 + 값 열 1개**(§3.1·§4-4). 값 열이 둘 이상이면 길이가 다른 산문의 폭을
    맞출 수 없어 반드시 어긋난다(이 저장소에서 같은 결함이 세 번 재발했다). 라벨 열 폭은
    §2 FORM_ENTRY 의 130px 과 같은 값을 써 등록 화면과 필드 순서·라벨 폭을 일치시킨다.
    """
    report_no = escape(str(report.get("report_no") or "-"))
    status_pill = lifecycle_badge_html(status, "평가완료")
    submit_status = str(imp.get("submit_status") or "") if imp else ""
    confirm_status = _confirm_state_of(imp)
    stage = _impr_stage(imp)
    submit_badge = erp.status_badge_html(
        _SUBMIT_LABEL.get(submit_status, "미작성"),
        _SUBMIT_COLOR.get(submit_status, _NEUTRAL))
    confirm_badge = erp.status_badge_html(
        _CONFIRM_LABEL.get(confirm_status, confirm_status),
        _CONFIRM_COLOR.get(confirm_status, _NEUTRAL))
    title = escape(str(report.get("work_name") or "(제목 없음)"))
    effect = escape(_STAGE_EFFECT.get(stage, ""))

    lbl = f"font-size:12px;color:{_FAINT};"
    head = (
        "<div style='padding:0 0 16px;display:flex;flex-direction:column;gap:8px;'>"
        "<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap;'>"
        f"<span style='font-size:14px;font-weight:600;{_NUM}color:{_INK};'>{report_no}</span>"
        f"{status_pill}"
        f"<span style='{lbl}'>제출</span>{submit_badge}"
        f"<span style='{lbl}'>확인</span>{confirm_badge}</div>"
        f"<span style='font-size:12px;color:{_INK2};'>{effect}</span>"
        f"<span style='font-size:20px;font-weight:600;color:{_INK};line-height:1.35;"
        f"text-wrap:pretty;'>{title}</span>"
    )
    # 등급은 조회·평가와 같은 등급 마크(셰브런+색 텍스트)로 렌더한다. 라벨은 §3.6 어휘
    # '평가 등급'이며 코드값 confirmed_grade 는 불변이다(폐기한 낱말은 모듈 docstring 참조).
    # 세 번째 항목(num)은 §1.2 의 tabular-nums 를 켤지다 — 자릿수가 세로로 정렬돼야 하는
    # 숫자 값(날짜 등)에만 켠다. 모노 서체 지정은 §1.2(2026-08-19)로 폐지했다.
    meta = [
        ("발생일", escape(str(report.get("incident_date") or "-")), True),
        ("접수 경과", escape(worklist.elapsed_label(report.get("created_at"))), False),
        ("소속", escape(str(report.get("dept_code") or "-")), False),
        ("신고자", escape(_user_label(report.get("reporter_emp_no"))), False),
        ("평가 등급", _grade_mark(report.get("confirmed_grade"), empty="미정"), False),
    ]
    meta_cells = "".join(
        f"<div style='display:flex;flex-direction:column;gap:4px;min-width:0;'>"
        f"<span style='font-size:12px;color:{_FAINT};'>{escape(label)}</span>"
        f"<span style='font-size:14px;color:{_INK};line-height:1.4;"
        + (_NUM if num else "")
        + f"overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'>{value}</span></div>"
        for label, value, num in meta
    )
    head += (
        f"<div style='display:flex;flex-wrap:wrap;gap:8px 32px;padding-top:4px;"
        f"border-top:1px solid {_LINE};'>{meta_cells}</div></div>"
    )

    cause = str(report.get("cause_code") or "")
    cause_detail = str(report.get("cause_detail") or "")
    cause_label = _CAUSE_LABEL.get(cause, cause)  # 미등록 코드는 원문 fallback(표시 전용)
    cause_val = cause_label + (f" · {cause_detail}" if cause_detail else "")
    # 종전에는 작업 내용·현장 설명이 액션 **뒤**의 expander 에 있었다 — 판정 자료가 판정
    # 컨트롤보다 뒤에 오면 안 된다(§2). 주요 내용 표로 끌어올린다.
    rows = [
        ("사고 내용", str(report.get("incident_content") or "")),
        ("작업 내용", str(report.get("work_content") or "")),
        ("현장 설명", str(report.get("site_description") or "")),
        ("원인", cause_val),
        ("대책", str(report.get("countermeasure") or "")),
    ]
    cells = "".join(
        "<div style='display:flex;gap:16px;padding:8px 0;"
        f"border-top:1px solid {_LINE};'>"
        f"<span style='flex:0 0 130px;font-size:12px;color:{_INK2};font-weight:600;"
        "line-height:1.6;'>" + escape(label) + "</span>"
        f"<span style='flex:1 1 auto;min-width:0;font-size:14px;line-height:1.7;color:{_INK};"
        "white-space:pre-wrap;text-wrap:pretty;'>"
        + (escape(value).strip() or "-") + "</span></div>"
        for label, value in rows
    )
    return head + f"<div style='margin:0 0 4px;'>{cells}</div>"


def _user_options() -> tuple[list[str], dict, bool]:
    """활성 사용자 select 옵션(빈 항목 포함) + emp_no→라벨 사전 + 조회실패 플래그(U6).

    조회 실패를 빈 옵션으로 무음 처리하지 않는다 — ``load_failed=True`` 를 함께 돌려 호출부가
    오류 배너 + 배정 필드 잠금으로 표면화하게 한다(잘못된 배정 저장 위험 차단)."""
    try:
        df = db.get_users()
    except Exception:  # noqa: BLE001 — 사용자 목록 조회 실패(배정 옵션 구성 불가).
        return [""], {"": "— 선택 —"}, True
    labels: dict = {"": "— 선택 —"}
    options = [""]
    if df is not None and not df.empty:
        for _, r in df.iterrows():
            if not bool(r.get("is_active", True)):
                continue
            emp = str(r.get("emp_no") or "").strip()
            if not emp:
                continue
            name = str(r.get("name") or "").strip()
            labels[emp] = f"{name}({emp})" if name else emp
            options.append(emp)
    return options, labels, False


def _select_index(options: list[str], value) -> int:
    value = str(value or "").strip()
    return options.index(value) if value in options else 0


def _render_capa_form(selected_id, imp, readiness: ReadinessState,
                      *, can_work: bool, can_assign: bool) -> dict:
    """CAPA 입력 폼(담당자·확인자·기한·조치 내용/결과). 반환은 위젯 현재값.

    행단위 편집 경계: 배정 필드(담당자·확인자)는 can_assign(평가자/ADMIN)만, 작업 필드
    (기한·조치 내용/결과)는 can_work(배정 담당자 본인·ADMIN)만 편집 가능하고 그 외에는
    읽기전용(disabled)으로 표시한다 — facade 가 어차피 strip 하지만 화면도 경계를 드러낸다.

    상세가 67% 열이라 컨트롤을 한 줄에 셋 늘어놓으면 폭이 모자라 줄바꿈이 어긋난다 —
    배정(담당자·확인자) 한 줄 / 기한 한 줄로 나누고 각 컨트롤은 제 폭만 쓴다(§3.1)."""
    confirm_status = _confirm_state_of(imp)
    if imp and confirm_status == "REJECTED" and str(imp.get("revision_note") or "").strip():
        banner("warn", f"재조치 요청 사유: {str(imp.get('revision_note')).strip()}")

    options, labels, users_failed = _user_options()
    fmt = lambda emp: labels.get(emp, emp)  # noqa: E731

    # U6: 사용자 목록 조회 실패는 무음(빈 옵션)으로 삼키지 않고 오류 배너 + 배정 필드 잠금으로
    # 표면화한다(옵션이 비어 잘못된 배정을 저장하는 위험 차단). can_assign 이어도 잠근다.
    if users_failed:
        banner("danger", "사용자 목록을 불러오지 못해 담당자·확인자를 배정할 수 없습니다. "
                         "데이터 연결 상태를 확인하고 새로고침하세요.")
    assign_disabled = (not can_assign) or users_failed

    if not can_assign:
        st.caption("담당자·확인자 배정은 평가자·관리자만 변경할 수 있습니다.")
    with st.container(horizontal=True, gap="medium"):
        assignee = st.selectbox(
            "조치 담당자", options,
            index=_select_index(options, imp.get("assignee_emp_no") if imp else ""),
            format_func=fmt, key=f"nm_impr_assignee_{selected_id}",
            disabled=assign_disabled, width=240,
        )
        confirmer = st.selectbox(
            "조치 확인자", options,
            index=_select_index(options, imp.get("designated_confirmer_emp_no") if imp else ""),
            format_func=fmt, key=f"nm_impr_confirmer_{selected_id}",
            disabled=assign_disabled, width=240,
        )
    due_raw = str(imp.get("due_date") or "").strip() if imp else ""
    try:
        due_default = date.fromisoformat(due_raw) if due_raw else date.today()
    except ValueError:
        due_default = date.today()
    due = st.date_input("조치 기한", value=due_default, format="YYYY-MM-DD",
                        key=f"nm_impr_due_{selected_id}", disabled=not can_work, width=180)

    if not can_work:
        st.caption("조치 내용·결과·기한은 배정된 담당자만 편집할 수 있습니다(조회 전용).")
    action_body = st.text_area(
        "조치 내용", value=str(imp.get("action_body") or "") if imp else "",
        height=80, key=f"nm_impr_action_{selected_id}", disabled=not can_work,
    )
    result_body = st.text_area(
        "조치 결과", value=str(imp.get("result_body") or "") if imp else "",
        height=80, key=f"nm_impr_result_{selected_id}", disabled=not can_work,
    )
    return {
        "assignee_emp_no": assignee,
        "designated_confirmer_emp_no": confirmer,
        "due_date": due.isoformat() if due else "",
        "action_body": action_body,
        "result_body": result_body,
    }


def _gate_notes(notes: list[tuple]) -> None:
    """비활성 사유를 화면에 쓴다(§3.2·§4-3 — 툴팁에만 두지 않는다).

    마우스를 올려야 알 수 있으면 모르는 것과 같고, 사유 없는 회색 버튼은 고장과 구분되지
    않는다. ``notes``: ``[(라벨, 사유 or None)]`` — 사유가 있는 것만 모아 한 블록으로 쓴다."""
    lines = [f"<b>{escape(str(label))}</b> 비활성 — {escape(str(reason))}"
             for label, reason in notes if reason]
    if not lines:
        return
    st.markdown(
        f"<div style='font-size:12px;color:{_INK2};line-height:1.6;margin:8px 0 0;"
        f"text-wrap:pretty;'>" + "<br>".join(lines) + "</div>",
        unsafe_allow_html=True,
    )


def _render_actions(user: dict, report: dict, imp, form: dict, readiness: ReadinessState,
                    *, can_work: bool, can_review: bool, can_assign: bool) -> None:
    """행단위 역할 variant scope 액션(§0.4) — §2 실행 블록. 버튼 노출을 능력으로 가른다:

      - can_work(담당자/ADMIN): 조치 저장·제출.
      - can_assign(평가자/ADMIN): 배정 저장(담당자·확인자 지정).
      - can_review(확인자/평가자/ADMIN): 확인·재조치 요청·보고서 종결.

    자기확인(담당자==세션) 시 확인은 disabled+사유로 남기고 facade 도 차단한다. 실제 쓰기·
    신원전달(auth.get_current_user())·예외흡수는 이 화면 소관이다."""
    selected_id = str(report.get("id"))
    can_write = readiness.write_enabled
    actor_emp = str(user.get("emp_no") or "").strip()

    submit_status = str(imp.get("submit_status") or "") if imp else ""
    confirm_status = _confirm_state_of(imp)
    stored_assignee = str(imp.get("assignee_emp_no") or "").strip() if imp else ""

    is_confirmed = confirm_status == _CONFIRMED
    is_submitted = submit_status == "SUBMITTED"
    is_pending = is_submitted and confirm_status == "PENDING"
    self_confirm = bool(stored_assignee) and stored_assignee.casefold() == actor_emp.casefold()

    # 재조치 요청 사유(전용 필드 — 반려와 별개 의미)는 검토 권한자만 본다. 제출·확인대기일 때만 입력.
    reject_reason = ""
    if can_review:
        reject_reason = str(st.text_area(
            "재조치 요청 사유(요청 시 필수)", key=f"nm_impr_reject_{selected_id}", height=52,
            disabled=(not can_write) or not is_pending,
        ) or "").strip()

    actions: list[tuple] = []
    gates: list[tuple] = []

    # ---- 저장(작업 or 배정) — can_work 또는 can_assign. 라벨로 무엇을 저장하는지 드러낸다. ----
    save_label = None
    if can_work or can_assign:
        save_disabled = (not can_write) or is_confirmed
        save_help = readiness.message if not can_write else (
            "확인된 개선조치는 수정할 수 없습니다." if is_confirmed else None)
        if can_work and can_assign:
            save_label = "저장"          # ADMIN(또는 담당자 겸 평가자): 배정+작업 동시.
        elif can_work:
            save_label = "조치 저장"       # 담당자: 작업필드만(배정필드 facade strip).
        else:
            save_label = "배정 저장"       # 평가자: 담당자·확인자 배정만(작업필드 facade strip).
        actions.append((save_label, "default", save_disabled, save_help))
        gates.append((save_label, save_help if save_disabled else None))

    # ---- 제출 — can_work(담당자/ADMIN)만. 비담당 평가자에겐 미표시. ----
    if can_work:
        submit_disabled = (not can_write) or submit_status != "DRAFT"
        if not can_write:
            submit_help = readiness.message
        elif imp is None:
            submit_help = "먼저 조치를 저장한 뒤 제출하세요."
        elif submit_status != "DRAFT":
            submit_help = "이미 제출된 개선조치입니다."
        else:
            submit_help = None
        actions.append(("제출", "primary", submit_disabled, submit_help))
        gates.append(("제출", submit_help if submit_disabled else None))

    # ---- 확인·재조치 요청 — can_review(확인자/평가자/ADMIN)만. 담당자에겐 미표시. ----
    if can_review:
        confirm_disabled = (not can_write) or not is_pending or self_confirm
        if not can_write:
            confirm_help = readiness.message
        elif not is_pending:
            confirm_help = "제출된(확인대기) 개선조치만 확인할 수 있습니다."
        elif self_confirm:
            confirm_help = "조치 담당자 본인은 확인할 수 없습니다(자기확인 금지)."
        else:
            confirm_help = None

        reject_disabled = (not can_write) or not is_pending or not reject_reason
        if not can_write:
            reject_help = readiness.message
        elif not is_pending:
            reject_help = "제출된(확인대기) 개선조치만 재조치를 요청할 수 있습니다."
        elif not reject_reason:
            reject_help = "재조치 요청 사유를 입력하세요."
        else:
            reject_help = None

        actions.append(("확인", "primary", confirm_disabled, confirm_help))
        actions.append(("재조치 요청", "default", reject_disabled, reject_help))
        gates.append(("확인", confirm_help if confirm_disabled else None))
        gates.append(("재조치 요청", reject_help if reject_disabled else None))

    clicks = erp.detail_actions(_PAGE_ID, actions)
    _gate_notes(gates)

    if save_label and clicks.get(save_label):
        _run_action(save_label, lambda: db.upsert_near_miss_improvement(
            selected_id, dict(form), current_user=auth.get_current_user(),
        ), keep_selection=True)
    if clicks.get("제출"):
        _run_action("제출", lambda: _save_then_submit(selected_id, form), keep_selection=True)
    if clicks.get("확인"):
        _run_action("확인", lambda: db.confirm_near_miss_improvement(
            selected_id, current_user=auth.get_current_user(),
        ), keep_selection=True)
    if clicks.get("재조치 요청"):
        _run_action("재조치 요청", lambda: db.reject_near_miss_improvement(
            selected_id, reject_reason, current_user=auth.get_current_user(),
        ), keep_selection=True)

    # 종결 액션은 파괴적(불가역)이라 워크플로 버튼과 분리하고 2단계 확인을 강제한다.
    # 검토 권한자(확인자/평가자/ADMIN)만 노출 — 담당자 뷰엔 종결이 아예 표시되지 않는다.
    if can_review:
        close_disabled = (not can_write) or not is_confirmed
        close_help = readiness.message if not can_write else (
            None if is_confirmed else "확인된 개선조치가 있어야 보고서를 종결할 수 있습니다.")
        _render_close(report, imp, close_disabled, close_help)


def _save_then_submit(report_id, form: dict) -> dict:
    """제출 직전 현재 폼을 DRAFT 로 저장한 뒤 SUBMITTED 로 전이한다(누락은 facade 차단)."""
    db.upsert_near_miss_improvement(report_id, dict(form), current_user=auth.get_current_user())
    return db.submit_near_miss_improvement(report_id, current_user=auth.get_current_user())


# ---------- 2단계 종결(불가역) ----------
def _render_close(report: dict, imp, disabled: bool, help_: str | None) -> None:
    selected_id = str(report.get("id"))
    close_clicks = erp.detail_actions(f"{_PAGE_ID}_close", [
        ("보고서 종결", "primary", disabled, help_),
    ])
    _gate_notes([("보고서 종결", help_ if disabled else None)])
    if close_clicks.get("보고서 종결") and not disabled:
        st.session_state[_CLOSE_CONFIRM_KEY] = selected_id
        st.rerun()

    if st.session_state.get(_CLOSE_CONFIRM_KEY) != selected_id:
        return

    # 인라인 확인 영역 — 보고번호·평가 등급·확인된 개선조치 요약 + 불가역 고지.
    report_no = str(report.get("report_no") or "-")
    grade = str(report.get("confirmed_grade") or "-")
    result_summary = str((imp or {}).get("result_body") or "").strip() or "(조치 결과 없음)"
    if len(result_summary) > 80:
        result_summary = result_summary[:80] + "…"
    banner(
        "warn",
        f"보고서 종결(불가역): {report_no} · 평가 등급 {grade} · 확인된 개선조치 "
        f"“{result_summary}”. 종결하면 이후 전이가 없습니다.",
    )
    confirm_clicks = erp.detail_actions(f"{_PAGE_ID}_close2", [
        ("종결 확정", "primary", disabled, help_),
        ("취소", "default", False, None),
    ])
    if confirm_clicks.get("취소"):
        st.session_state.pop(_CLOSE_CONFIRM_KEY, None)
        st.rerun()
    if confirm_clicks.get("종결 확정") and not disabled:
        st.session_state.pop(_CLOSE_CONFIRM_KEY, None)
        _run_action("보고서 종결", lambda: db.close_near_miss_report(
            selected_id, current_user=auth.get_current_user(),
        ))


# ---------- 액션 실행(예외 흡수) ----------
def _flash_kind_for(exc: Exception) -> str:
    return "warning" if _STALE_MARK in str(exc) else "error"


def _run_action(label: str, call, *, keep_selection: bool = False) -> None:
    """scope 액션 공통 실행 — 예외를 흡수해 raw traceback 을 노출하지 않는다
    (2단계 배너: 제목 + 파사드 원문 사유, stale 은 가공 없이 그대로 노출).

    ``keep_selection`` 이면 처리 후에도 상세를 열어둔다(재조치 요청·저장 등 큐에 남는 액션).
    종결처럼 큐에서 빠지는 액션은 선택을 닫는다."""
    try:
        call()
    except ValueError as exc:
        _STATE.set_flash(_flash_kind_for(exc), f"{label} 처리 실패 — {exc}")
        st.rerun()
    except db.DATA_SOURCE_ERRORS as exc:
        _STATE.set_flash("error", f"{label} 처리 중 오류가 발생했습니다: {exc}")
        st.rerun()
    except Exception:
        _STATE.set_flash("error", f"{label} 처리 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.")
        st.rerun()
    _STATE.set_flash("success", f"{label} 완료.")
    if not keep_selection:
        st.session_state.pop(_SEL_KEY, None)
    st.rerun()
