"""아차사고 평가 관리 — WORKLIST(DESIGN.md §2).

§2 WORKLIST 골격을 그대로 구현한다(2026-08-18 §7.1 확정 이관 — 구 "큐 칩 스트립 +
전체폭 상세" 골격 폐기):

    제목/설명 → [상태 탭: 평가 대기 n · 평가중 n · 전체 n] → 헤어라인
    → 2열( 목록 33% | 상세 67% )
      목록 : 2줄 고정 행(제목/경과일 · 보고번호·소속/분류) + 좌측 2px 상태 보더, 자체 스크롤
      상세 : 식별자 + 상태 배지 + 상태 결과 + 대상 제목 + 메타
             → 주요 내용 표(라벨 열 + 값 열 1개) → 첨부 → 결정(근거 뒤: 등급 → 의견 → 실행)

이관에서 바뀐 것(구조·표기만, 기능 계약 불변)
  - **지표 타일 제거**(§4-1·§2) — ``erp.metric_strip`` 3장(평가 대기·검토중·대기 합계)을
    없애고 그 건수를 **상태 탭 라벨**로 옮겼다. 탭은 목록을 실제로 바꾼다(합계 타일은
    앞 두 타일의 합이라 새 정보가 없었다).
  - **어휘 통일**(§3.6) — ``검토중 → 평가중`` · ``확정 등급 → 평가 등급``. **영문 코드값
    (``IN_REVIEW``·``confirmed_grade``)은 불변**이며 한글 라벨만 통일한다.
    (같이 통일했던 ``검토착수 → 평가착수`` 는 아래 2026-08-19 결정으로 액션 자체가 없어졌다.)
  - **상태의 결과 표기**(§3.3) — 배지 옆에 그 상태가 무엇을 막고 여는지 한 줄
    (``평가중`` 옆 ``보고자 수정 잠김`` — ``docs/database.md`` 보고자 수정 컷오프).
  - **보완요청 활성 게이트 정정**(§7.4 P1) — 종전 활성 판정은 006 프로브였는데 실행부
    ``db.request_near_miss_revision`` 은 **007 프로브**로 fail-closed 차단한다. 006 만
    적용된 배포에서 버튼이 눌리고 실패했다. 활성 판정을 **실행부와 같은 007 기준**으로
    맞추고, 비활성 사유는 툴팁이 아니라 **화면에 쓴다**(§3.2·§4-3).
  - **목록 정렬** — 경과일(접수일 ``created_at`` 기준, §7.2-4) 내림차순. 오래 묵은 건이
    위로 온다. 경과일에는 색을 칠하지 않는다(§7.2-4-b, SLA 미정).

2026-08-19 사용자 결정 — **'평가 착수' 폐지**
  평가자는 평가 대기(SUBMITTED)에서 **곧장 보완요청·반려·평가확정**을 한다. 착수는 그 자체로
  아무 판정도 아니면서 모든 판정 앞에 클릭 한 번을 더 놓던 단계였다.
  - 액션은 4개 → **3개**(보완요청 · 반려 · 평가확정). ``update_near_miss_status(...,
    "IN_REVIEW")`` 배선을 이 화면에서 제거했다.
  - 상태 전이표(``db.NEAR_MISS_TRANSITIONS``)는 손대지 않는다 — SUBMITTED→EVALUATED·
    SUBMITTED→REJECTED 가 이미 허용돼 있었다(migration 불요).
  - **보완요청만 저장 계약이 넓어졌다**: ``db.request_near_miss_revision`` 이 종전 IN_REVIEW
    전용이었는데 ``_NEAR_MISS_REVISION_STATES``(SUBMITTED·IN_REVIEW)로 확대됐다. 화면이
    보완요청 직전에 몰래 IN_REVIEW 로 올리는 2회 쓰기(중간 실패 시 상태 어긋남)를 만들지
    않는다 — 사용자가 없애라고 한 단계를 뒤로 숨기는 것이기도 하다.
  - ``IN_REVIEW``(평가중) **상태값과 탭은 그대로 둔다**(통계·PDF·개선조치가 쓴다). 다만 이
    화면에는 이제 IN_REVIEW 를 만드는 경로가 없으므로 '평가중' 탭에는 재개
    (EVALUATED→IN_REVIEW, 파사드 경로) 또는 과거 데이터로 남은 건만 보인다. 탭 구성 변경은
    사용자 결정 사항이라 이번에 건드리지 않았다.

기능 계약(불변 — 표현 계층만 교체):
  - 권한 게이트 ``auth.can_evaluate_near_miss(user)``.
  - 상태 전이 3종: 평가확정(evaluate_near_miss, SUBMITTED/IN_REVIEW→EVALUATED) ·
    보완요청(request_near_miss_revision — SUBMITTED 는 상태 유지, IN_REVIEW 는 반송) ·
    반려(→REJECTED).
    반려·보완요청은 '의견' 필수(단일 의견 입력 — 반려는 rejection_reason, 보완요청은
    사유로 재사용). 신원은 서버측(current_user=auth.get_current_user())으로 확정.
  - 등급 세그먼트 값은 ``db.NEAR_MISS_GRADES`` 도메인 소스에서 파생(하드코딩 없음).
  - 모든 파사드 호출은 ``modules/db.py`` 만 사용(repository 직접 호출 없음). stale 충돌은
    파사드 원문 메시지를 배너로 그대로 노출(가공 금지).

범위 밖(이번 이관에서 건드리지 않는 것)
  - 빈도×강도 매트릭스 등급 입력(§7.1) — ``frequency``/``severity`` migration(§7.2-1e)이
    없어 저장할 곳이 없다. 기존 등급 세그먼트를 그대로 둔다.
  - ``NEAR_MISS_TRANSITIONS``·``docs/database.md``·migration — ``data-contract`` 소관(§7.3-4).
"""
# DESIGN.md §2 WORKLIST — 상태 탭 + 2열(목록 33% / 상세 67%).
SCREEN_ARCHETYPE = "WORKLIST"
# §0 — 이 화면이 내리는 결정(기계 검증은 아직 없다, §5).
SCREEN_DECISION = "이 건의 등급을 확정할 것인가, 반려할 것인가, 보완을 요청할 것인가"
SCREEN_EVIDENCE = ("사고 내용", "작업·현장 설명", "원인·대책", "첨부 사진", "접수 경과일")

from html import escape

import pandas as pd
import streamlit as st

from modules import auth, db
from views.common import erp, scaffold, worklist
from views.common import near_miss as nm_common
from views.common.photo_paths import normalize_photo_paths
from views.common.photos import render_photo_thumbs
from views.master import (
    LIFECYCLE_BADGE,
    DraftState,
    Readiness,
    ReadinessState,
    empty_state,
    lifecycle_badge_html,
    show_flash,
)

_STATE = DraftState("nm_eval")
_PAGE_ID = _STATE.page_id

# 이 화면이 다루는 "평가 대기" 상태 — 파사드 NEAR_MISS_STATUSES 의 부분집합
# (SoT 는 db.py, 여기서는 화면 필터링용 상수 복제).
_PENDING_STATUSES = ("SUBMITTED", "IN_REVIEW")

# 보완요청을 걸 수 있는 상태 — 실행부 ``db._NEAR_MISS_REVISION_STATES`` 와 같은 집합이다
# (2026-08-19 평가 착수 폐지로 SUBMITTED 포함). 활성 판정과 실행부가 어긋나면 눌리는데
# 실패하는 버튼이 생긴다(§7.4 P1 이 고친 결함) — 두 곳의 값을 같게 유지한다.
_REVISION_STATUSES = ("SUBMITTED", "IN_REVIEW")

# §3.6 어휘: 진행 상태는 '평가중'(구 '검토중'). 영문 코드값은 불변이며 한글 라벨만 통일한다.
# (라벨 사전이 3화면에 복제돼 있는 것은 §3.6 이 지적한 미결이며 단일 출처화는 별건이다.)
_STATUS_LABEL = {
    "SUBMITTED": "제출됨",
    "IN_REVIEW": "평가중",
    "EVALUATED": "평가완료",
    "REJECTED": "반려",
    "CLOSED": "종결",
}
# §3.3 — 상태는 배지로, 그 상태의 **결과**(무엇을 막고 무엇을 여는지)는 별도 표기로 적는다.
# 근거: docs/database.md "보고자 수정 컷오프"(보고자는 SUBMITTED 에서만 수정 가능).
_STATUS_EFFECT = {
    "SUBMITTED": "보고자 수정 가능 · 평가자 미지정",
    "IN_REVIEW": "보고자 수정 잠김",
    "EVALUATED": "개선조치 등록 단계",
    # 2026-08-19 문구 정정: 종전 '보고자 재제출 대기'는 사실이 아니었다. 반려(REJECTED)는
    # 종결 분기이고 보고자 화면(내 아차사고)에는 반려 건을 되살리는 진입점이 없다 —
    # 수정도 잠긴다. 실제로 보고자의 재제출을 기다리는 것은 **보완요청**(아래
    # _REVISION_EFFECT)이며, 그 문구는 그쪽으로 옮겼다.
    "REJECTED": "종결 분기 — 보고자 수정 잠김",
    "CLOSED": "이후 전이 없음",
}
# 보완요청(반송)으로 되돌아온 SUBMITTED 건. 상태 코드는 갓 등록한 건과 같지만 평가자가
# 기다리는 것이 다르다 — 새 건이 아니라 **보고자의 재제출**이다. 보고자 화면에 실제
# 재제출 경로(db.resubmit_near_miss → 내 아차사고 [재제출])가 생겨 이 문구가 사실이 된다.
# 재제출하면 보완요청 3필드가 비어 이 라벨이 자동으로 '제출됨'으로 되돌아간다.
_REVISION_LABEL = nm_common.REVISION_LABEL
_REVISION_EFFECT = "보고자 재제출 대기 — 보완 후 재제출"
# 목록 행 좌측 2px 보더 색(§2: 상태는 줄 수가 아니라 보더 색으로 표현한다). 상태 배지와
# **같은 의미 색**을 쓴다(§1.3 의미 색은 상태마다 새로 만들지 않는다).
_STATUS_ACCENT = {code: pal["text"] for code, pal in LIFECYCLE_BADGE.items()}

# 등급 마크(_grade_mark)·등급 색 매핑은 이 화면에서 제거했다 — 유일한 소비처가 상세 메타의
# **제안등급**이었고 §7.2-1b(2026-08-18 사용자 결정)로 제안등급 표시를 폐기했기 때문이다.
# 이 화면의 큐는 SUBMITTED/IN_REVIEW 뿐이라 confirmed_grade 는 항상 비어 있어 대체 표시도
# 두지 않는다(빈 자리를 만들지 않도록 메타는 발생일·접수 경과·소속·신고자로 재배분).
# DB 컬럼 proposed_grade 는 미사용으로 남긴다(컬럼 제거 판단은 data-contract 소관).

# 발생원인 코드→한글 라벨(§3.1: 분류축=평문, 색 없음) — 아차사고 6화면 단일 어휘
# (2026-08-14: HIT 충돌→부딪힘·DROP 낙하→낙하물, KOSHA 현행 용어 기준).
_CAUSE_LABEL = {
    "JAM": "끼임", "FALL": "추락", "DROP": "낙하물", "HIT": "부딪힘",
    "SLIP": "미끄러짐", "BURN": "화상", "PINCH": "협착", "ETC": "기타",
}

_NOT_READY_MSG = (
    "아차사고 스키마가 준비되지 않아 평가를 진행할 수 없습니다(조회만 가능). "
    "스키마를 적용한 뒤 다시 시도하세요."
)
_PROBE_ERROR_MSG = (
    "아차사고 스키마 상태 확인 실패 — 재확인이 필요합니다(확인 전까지 평가는 차단됩니다)."
)
# §7.4 P1 — 보완요청 실행부(db.request_near_miss_revision)가 요구하는 **007** 프로브의
# 비활성 사유. 실행부 원문(_NEAR_MISS_REVISION_NOT_READY_MESSAGE)과 같은 사실을 말한다.
_REVISION_NOT_READY_MSG = "보완요청 스키마(007)가 적용되지 않아 보완 사유를 저장할 수 없습니다."
_REVISION_PROBE_ERROR_MSG = "보완요청 스키마(007) 상태를 확인하지 못했습니다."
_STALE_MARK = "이미 변경"  # db._NEAR_MISS_STALE_MESSAGE 원문 일부 — kind 분기(warning vs error).

_SEL_KEY = "nm_eval_selected_id"       # 상세에 열린 보고서 id(문자열)
_TAB_KEY = "nm_eval_tab"               # 상태 탭 선택(§2: 탭이 목록을 실제로 바꾼다)
_OP_KEY = "nm_eval_opinion_"           # 평가 의견(반려·보완요청 공용) prefix + id
_GRADE_KEY = "nm_eval_grade_"          # 평가 등급 선택 prefix + id
_EVAL_ACTIVE_KEY = "nm_eval_active_id"  # 직전 렌더의 활성 케이스 id(케이스 전환 시 등급 선택 초기화)

# 상태 탭 — 라벨은 §3.6 어휘("평가 대기 → 평가중"), 값은 상태 코드(불변)로 매핑한다.
# 탭 라벨 문자열에 건수를 섞지 않고 format_func 로 붙인다: 건수가 바뀔 때마다 옵션 문자열이
# 달라지면 세션에 보관된 선택값이 옵션 목록에서 사라져 탭이 초기화된다.
_TABS: tuple[str, ...] = ("평가 대기", "평가중", "전체")
_TAB_STATUSES = {
    "평가 대기": ("SUBMITTED",),
    "평가중": ("IN_REVIEW",),
    "전체": _PENDING_STATUSES,
}

# 목록 열 자체 스크롤 높이(§2: 목록과 상세는 독립 스크롤). 1366×768 기준 상단 크롬을 뺀
# 잔여 높이 근사이며 간격 토큰이 아니라 뷰포트 파생값이다.
_LIST_HEIGHT = 520

# ── §1.3 팔레트 (토큰 밖 색 금지 §4-7) — 리터럴로 고정해 새 색 유입을 원천 차단한다. ──
_INK = "#1c1a17"          # 본문
_INK2 = "#4a453d"         # 보조(섹션 라벨)
_FAINT = "#6b665d"        # 읽는 텍스트 최저 대비(5.1:1) — 이보다 옅은 회색은 읽는 텍스트 금지
_LINE = "#e6e2da"         # 행 헤어라인
_LINE_SEC = "#e0dbd2"     # 섹션 헤어라인
_DANGER = "#9c3232"       # 부정 의미(반려) 글자
_DANGER_BG = "#fbeeee"
_DANGER_LINE = "#f0d9d9"
# 인라인 style 속성 안에 그대로 들어가므로 **큰따옴표**로 감싼다(작은따옴표는 금지).
# style='font-family:{_MONO};…' 에 작은따옴표 계열 값을 넣으면 속성이 첫 내부 따옴표에서
# 끊겨 style 전체가 소실된다(2026-08-14 실측). CSS 블록 안에서도 유효.
_MONO = '"Pretendard","Malgun Gothic",-apple-system,sans-serif'

# 화면 스코프 CSS — §1.2 다섯 단계(28/20/16/14/12)와 §1.4 compact 히트영역(34~38px)만 쓴다.
_EVAL_CSS = f"""
<style>
/* 상태 탭 — compact 히트영역 34px(공용 기본 30.1px 미달 보정). 선택 표시는 Streamlit
   기본(액센트)을 그대로 쓴다. 선택자는 위젯 key(_TAB_KEY)에서 오는 st-key 클래스다.
   한글 라벨이라 모노·letter-spacing 을 걸지 않는다(본문 sans 상속). */
.st-key-nm_eval_tab button {{
  min-height:34px !important; font-weight:600 !important;
}}
/* 라벨 글자는 button 이 아니라 내부 <p> 가 소유한다 — button 에만 font-size 를 걸면
   실제 글자는 Streamlit 기본 12.25px 로 남는다(2026-08-18 실측). §1.2 14px 로 고정. */
.st-key-nm_eval_tab button p {{ font-size:14px !important; font-weight:600 !important; }}
/* 선택 탭 라벨: 기본 액센트 #c2410c 는 10% 틴트 배경(#efe0d7) 위에서 4.03:1 로 §5
   하한(4.5) 미달이다(실측). hover 액센트 #a3350a 로 내리면 5.31:1. */
.st-key-nm_eval_tab button[aria-checked="true"] p {{ color:#a3350a !important; }}
/* <599px: 목록 고정 높이(520)가 콘텐츠보다 커서 빈 공간이 생기고 상세가 폴드 밖으로
   밀린다(390 에서 469px 공백 실측). 좁은 폭에서는 콘텐츠 높이로 푼다. */
@media (max-width:598px) {{
  .st-key-nm_eval_listbox {{ height:auto !important; max-height:none !important; }}
}}
/* 평가 등급 세그먼트(선택=primary 액센트) — 모노 코드, 히트영역 34px */
[class*="st-key-nmg_"] button {{
  border-radius:7px !important; min-width:44px !important; min-height:34px !important;
  padding:6px 12px !important; font-family:{_MONO} !important; font-size:14px !important;
  font-weight:600 !important;
}}
/* 액션 버튼(보완요청/반려/평가확정) — 히트영역 34px */
[class*="st-key-nm_act_"] button {{
  min-height:34px !important; border-radius:8px !important; font-size:14px !important;
  font-weight:600 !important; white-space:nowrap !important;
}}
/* 반려는 부정 의미 색(§3.2) — 보완요청·반려·평가확정 셋이 색으로 갈린다
   (보조 / 부정 / 주 액션). */
[class*="st-key-nm_act_reject_"] button {{
  background:{_DANGER_BG} !important; border-color:{_DANGER_LINE} !important;
  color:{_DANGER} !important;
}}
[class*="st-key-nm_act_reject_"] button:disabled {{ color:{_FAINT} !important; }}
/* 비활성 라벨은 Streamlit 기본 #9e9c98(2.46:1, §1.3 팔레트 밖)이다. WCAG 는 비활성을
   예외로 두지만 한 액션 행에서 2.46:1 과 5.04:1 이 섞이는 것은 결함이라 통일한다. */
[class*="st-key-nm_act_"] button:disabled p {{ color:{_FAINT} !important; }}
[class*="st-key-nm_act_"] button p {{ font-size:14px !important; font-weight:600 !important; }}
.nm-seg-label {{ font-size:12px; font-weight:400; color:{_INK2}; white-space:nowrap; }}
/* 결정 블록 라벨 — 한글이라 letter-spacing 을 주지 않는다(자간이 벌어진다). */
.nm-sec {{ font-size:12px; font-weight:600; color:{_INK2}; margin:0 0 6px; }}
/* 비활성 사유(§3.2·§4-3: 툴팁에만 두지 않는다) */
.nm-gate {{ font-size:12px; color:{_INK2}; line-height:1.6; margin:6px 0 0;
  text-wrap:pretty; }}
</style>
"""


# ---------- 진입 ----------
def render(user: dict) -> None:
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="평가 관리",
        desc="등록된 아차사고를 평가해 등급을 확정하거나 반려합니다.",
        breadcrumb="아차사고 › 평가 관리",
        badges=scaffold.mode_badge(),
    )
    st.markdown(_EVAL_CSS, unsafe_allow_html=True)
    if not auth.can_evaluate_near_miss(user):
        empty_state(
            "평가 권한이 없습니다",
            "관리자·매니저 또는 안전담당자만 아차사고를 평가할 수 있습니다.",
        )
        return
    _render_body(user)


def _readiness() -> ReadinessState:
    """006 아차사고 스키마 — 평가확정·반려 쓰기 게이트(보완요청은 007, 아래 별도)."""
    state = db.near_miss_schema_probe()
    if state == db.READINESS_READY:
        return ReadinessState.ready()
    if state == db.READINESS_PROBE_ERROR:
        return ReadinessState.probe_error(_PROBE_ERROR_MSG)
    return ReadinessState.not_ready(_NOT_READY_MSG)


def _revision_readiness() -> ReadinessState:
    """007 보완요청 스키마 — **보완요청 전용** 쓰기 게이트(§7.4 P1).

    보완요청 실행부(``db.request_near_miss_revision``)는 006 이 아니라 007 프로브로
    fail-closed 차단한다. 화면이 006 으로 활성을 판정하면 006 만 적용된 배포에서 버튼이
    눌리고 실패한다(§3.2 위반). 실행부와 **같은 프로브**를 읽어 판정을 일치시킨다.
    ``modules/db.py`` 는 수정하지 않는다(data-contract 소관).
    """
    state = db.near_miss_improvement_schema_probe()
    if state == db.READINESS_READY:
        return ReadinessState.ready()
    if state == db.READINESS_PROBE_ERROR:
        return ReadinessState.probe_error(_REVISION_PROBE_ERROR_MSG)
    return ReadinessState.not_ready(_REVISION_NOT_READY_MSG)


def _render_body(user: dict) -> None:
    show_flash(_STATE)
    readiness = _readiness()
    revision_readiness = _revision_readiness()
    readiness.banner()
    if readiness.state is Readiness.PROBE_ERROR:
        if st.button("스키마 재확인", key="nm_eval__recheck", icon=":material/refresh:"):
            db.near_miss_schema_probe(force=True)
            db.near_miss_improvement_schema_probe(force=True)
            st.rerun()

    try:
        reports = _load_pending_reports()
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"평가 대기 목록을 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("평가 대기 목록을 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    # ── 상태 탭(§2) — 지표 타일 대신 여기에 건수를 싣는다(§4-1). 탭은 목록을 실제로 바꾼다. ──
    tab = _render_tabs(_tab_counts(reports))
    _hairline()

    ordered = _ordered_ids(reports, _TAB_STATUSES[tab])
    reports_by_id = {}
    if reports is not None and not reports.empty:
        reports_by_id = {str(r["id"]): r for _, r in reports.iterrows()}

    # 선택 보관은 호출부 책임(erp.select_list 계약). 탭 전환으로 선택이 목록에서 빠지면
    # 첫 건으로 되돌린다 — 상세가 빈 채로 남지 않게 한다.
    selected_id = st.session_state.get(_SEL_KEY)
    if selected_id not in ordered:
        selected_id = ordered[0] if ordered else None
        st.session_state[_SEL_KEY] = selected_id

    list_col, detail_col = erp.master_detail_frame(list_ratio=1, detail_ratio=2)
    with list_col:
        picked = _render_list(ordered, reports_by_id, selected_id, tab)
        if picked and picked != selected_id:
            st.session_state[_SEL_KEY] = picked
            st.rerun()
    with detail_col:
        if selected_id is None:
            erp.detail_empty(
                "처리할 건이 없습니다",
                f"'{tab}' 탭에 표시할 아차사고가 없습니다. 다른 상태 탭을 확인하세요.",
            )
            return
        _render_detail(user, readiness, revision_readiness, selected_id)


# ---------- 데이터 ----------
def _load_pending_reports() -> pd.DataFrame:
    """활성 아차사고 중 평가 대기(SUBMITTED/IN_REVIEW)만. 단일 status 필터만 지원하는
    파사드 계약이라 두 상태는 여기서 클라이언트 측으로 골라낸다."""
    df = db.get_near_miss_reports({})
    if df is None or df.empty:
        return df
    mask = df["status"].astype(str).isin(_PENDING_STATUSES)
    return df[mask].reset_index(drop=True)


def _tab_counts(df: pd.DataFrame) -> dict[str, int]:
    """상태 탭 라벨에 붙는 건수(§4-1: 지표는 탭 안의 건수로 표현한다).

    '전체'는 평가 대기 큐 전체(SUBMITTED+IN_REVIEW)이며, 탭이 없으면 선택할 수 없으므로
    §4-1 이 금지한 "읽기만 하는 합계 타일"과 다르다 — 이 값은 목록을 바꾼다.
    """
    counts = {name: 0 for name in _TABS}
    if df is None or df.empty:
        return counts
    by_status = df["status"].astype(str).value_counts()
    for name, statuses in _TAB_STATUSES.items():
        counts[name] = int(sum(int(by_status.get(code, 0)) for code in statuses))
    return counts


def _ordered_ids(df: pd.DataFrame, statuses: tuple[str, ...]) -> list[str]:
    """탭 상태로 거른 뒤 **경과일 내림차순**(오래 묵은 건 먼저)으로 정렬한다(§7.2-4-b).

    경과일은 접수일(``created_at``) 파생이다 — ``incident_date`` 는 동순위 tie-break 로만
    쓴다(같은 날 접수분 안에서 발생일이 최근인 건을 위로).
    """
    if df is None or df.empty:
        return []
    frame = df[df["status"].astype(str).isin(statuses)]
    if frame.empty:
        return []
    return worklist.order_by_elapsed([
        (r["id"], r.get("created_at"), r.get("incident_date")) for _, r in frame.iterrows()
    ])


def _reporter_label(emp_no) -> str:
    emp_no = str(emp_no or "").strip()
    if not emp_no:
        return "-"
    try:
        record = db.find_user_by_emp_no(emp_no)
    except Exception:
        return emp_no
    name = str(record.get("name") or "").strip() if record else ""
    return f"{name}({emp_no})" if name else emp_no


def _hairline() -> None:
    st.markdown(
        f"<div style='border-top:1px solid {_LINE_SEC};margin:4px 0 12px;'></div>",
        unsafe_allow_html=True,
    )


# ---------- 상태 탭 ----------
def _render_tabs(counts: dict[str, int]) -> str:
    """상태 탭을 렌더하고 선택된 탭 이름을 반환한다(§2 골격의 두 번째 블록).

    ``st.tabs`` 를 쓰지 않는다 — 기본값이 모든 탭을 미리 렌더해 "탭이 목록을 바꾼다"는
    §2 계약이 성립하지 않는다. ``st.segmented_control`` 은 클릭=rerun 이라 필터링이 자동
    성립한다(``my_schedule.py`` 실사용 선례). ``required=True`` 로 선택 해제를 막아
    "아무 탭도 아닌" 상태를 만들지 않는다.
    """
    # 첫 진입 탭은 **비어 있지 않은 첫 탭**이다(§3.5: 애초에 빈 영역이 생기지 않게 배치).
    # 처리 우선순위 순서(평가 대기 → 평가중 → 전체)로 훑어 건수가 있는 첫 탭을 고른다.
    # 이미 사용자가 고른 탭이 있으면 건드리지 않는다 — 처리 후 그 탭이 0 이 됐다고 화면이
    # 제멋대로 옮겨 가면 방금 무엇을 했는지 알 수 없다.
    if st.session_state.get(_TAB_KEY) not in _TABS:
        st.session_state[_TAB_KEY] = next(
            (name for name in _TABS if counts.get(name, 0)), _TABS[0])
    picked = st.segmented_control(
        "상태",
        _TABS,
        key=_TAB_KEY,
        required=True,
        format_func=lambda name: f"{name} {counts.get(name, 0)}",
        label_visibility="collapsed",
        width="content",
    )
    return picked if picked in _TABS else _TABS[0]


# ---------- 목록 열(33%) ----------
def _list_items(ordered: list[str], reports_by_id: dict) -> list[dict]:
    """§2 목록 행 2줄 고정 — 1줄: 제목 / 경과일, 2줄: 보고번호·소속 / 분류.

    식별자만 있는 행은 정렬 순서 외에 아무 판단도 돕지 못하므로 "무엇을 먼저 처리할지 고를
    근거"(경과일·소속·분류)를 함께 싣는다. 상태는 줄을 늘리지 않고 좌측 2px 보더 색으로만
    표현한다(§2·§4-5 — 행 높이가 상태에 따라 달라지면 안 된다).
    """
    items: list[dict] = []
    for rid in ordered:
        # ``or {}`` 를 쓰지 않는다 — 값이 pandas Series 라 truthiness 평가에서
        # ValueError("truth value of a Series is ambiguous")로 화면이 통째로 죽는다.
        r = reports_by_id.get(rid)
        if r is None:
            r = {}
        status = str(r.get("status") or "")
        cause = str(r.get("cause_code") or "")
        dept = str(r.get("dept_code") or "").strip()
        klass = _CAUSE_LABEL.get(cause, cause) or "-"
        items.append({
            "key": rid,
            "line1_left": str(r.get("work_name") or "(제목 없음)"),
            "line1_right": worklist.elapsed_label(r.get("created_at")),
            # line2_left 는 kit 이 **모노**로 렌더한다(.esl-mono) — IBM Plex Mono 에는 한글
            # 글리프가 없어 한글을 넣으면 글자마다 폴백돼 자간이 벌어진다. 영숫자 식별자만.
            "line2_left": str(r.get("report_no") or rid),
            # 소속·분류는 sans 쪽(line2_right)에 모아 둔다(둘 다 한글이 올 수 있다).
            "line2_right": f"{dept} · {klass}" if dept else klass,
            "accent": _STATUS_ACCENT.get(status, ""),
        })
    return items


def _render_list(ordered: list[str], reports_by_id: dict, selected_id, tab: str) -> str | None:
    """목록 열 렌더 — 이번 run 에 새로 클릭된 자연키를 반환한다(선택 보관은 호출부)."""
    with st.container(height=_LIST_HEIGHT, border=False, key="nm_eval_listbox"):
        return erp.select_list(
            "nm_eval_list",
            _list_items(ordered, reports_by_id),
            selected=str(selected_id) if selected_id is not None else None,
            empty=f"'{tab}' 탭에 표시할 건이 없습니다.",
        )


# ---------- 상세 열(67%) ----------
def _detail_head_html(report: dict, status: str) -> str:
    """상세 머리 — 식별자(16/600 모노) + 상태 배지 + **상태 결과**(§3.3) + 대상 제목(20/600)
    + 메타(발생일·접수·소속·신고자)."""
    report_no = escape(str(report.get("report_no") or "-"))
    # 보완요청으로 반송된 건은 상태 코드가 SUBMITTED 라 갓 등록한 건과 구분되지 않는다.
    # 라벨·결과 표기만 파생한다 — 코드값·색(LIFECYCLE_BADGE[SUBMITTED])·레이아웃은 불변.
    revision = nm_common.has_revision_request(report)
    badge = lifecycle_badge_html(
        status, _REVISION_LABEL if revision else _STATUS_LABEL.get(status, status))
    effect = escape(_REVISION_EFFECT if revision else _STATUS_EFFECT.get(status, ""))
    title = escape(str(report.get("work_name") or "(제목 없음)"))

    # 세 번째 항목(mono)은 **영숫자 전용 문자열에만** 켠다 — IBM Plex Mono 에는 한글
    # 글리프가 없어 한글에 모노를 걸면 글자마다 폴백 폰트로 떨어져 자간이 벌어진다.
    # 발생일(ISO 날짜)만 모노이고, '12일'·'오늘'(경과)·부서코드·신고자는 본문 sans 를 쓴다.
    meta = [
        ("발생일", escape(str(report.get("incident_date") or "-")), True),
        ("접수 경과", escape(worklist.elapsed_label(report.get("created_at"))), False),
        ("소속", escape(str(report.get("dept_code") or "-")), False),
        ("신고자", escape(_reporter_label(report.get("reporter_emp_no"))), False),
    ]
    meta_cells = "".join(
        f"<div style='display:flex;flex-direction:column;gap:2px;min-width:0;'>"
        f"<span style='font-size:12px;color:{_FAINT};'>{escape(label)}</span>"
        f"<span style='font-size:14px;color:{_INK};line-height:1.4;"
        + (f"font-family:{_MONO};font-variant-numeric:tabular-nums;" if mono else "")
        + f"overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'>{value}</span></div>"
        for label, value, mono in meta
    )
    return (
        "<div style='padding:2px 0 14px;display:flex;flex-direction:column;gap:8px;'>"
        "<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap;'>"
        f"<span style='font-family:{_MONO};font-size:14px;font-weight:600;color:{_INK};'>{report_no}</span>"
        f"{badge}"
        f"<span style='font-size:12px;color:{_INK2};'>{effect}</span></div>"
        f"<span style='font-size:20px;font-weight:600;color:{_INK};line-height:1.35;"
        f"text-wrap:pretty;'>{title}</span>"
        f"<div style='display:flex;flex-wrap:wrap;gap:8px 32px;padding-top:4px;"
        f"border-top:1px solid {_LINE};'>{meta_cells}</div>"
        "</div>"
    )


def _detail_body_html(report: dict) -> str:
    """주요 내용 표 — **라벨 열 + 값 열 1개**(§3.1·§4-4).

    값 열을 둘 이상 두면 길이가 다른 산문의 폭을 맞출 수 없어 반드시 어긋난다(이 저장소에서
    같은 결함이 세 번 재발했다). 라벨 열 폭은 §2 FORM_ENTRY 의 130px 과 같은 값을 써
    등록 화면과 필드 순서·라벨 폭을 일치시킨다.
    """
    cause = str(report.get("cause_code") or "")
    cause_detail = str(report.get("cause_detail") or "")
    cause_val = (_CAUSE_LABEL.get(cause, cause) or "-") + (
        f" · {cause_detail}" if cause_detail else "")
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
    return f"<div style='margin:0 0 4px;'>{cells}</div>"


def _gate_notes(notes: list[tuple[str, str | None]]) -> None:
    """비활성 사유를 화면에 쓴다(§3.2·§4-3 — 툴팁에만 두지 않는다).

    마우스를 올려야 알 수 있으면 모르는 것과 같고, 사유 없는 회색 버튼은 고장과 구분되지
    않는다. ``notes``: ``[(버튼 라벨, 사유 or None)]`` — 사유가 있는 것만 한 줄로 모은다.
    """
    lines = [f"<b>{escape(label)}</b> 비활성 — {escape(reason)}"
             for label, reason in notes if reason]
    if not lines:
        return
    st.markdown(
        "<div class='nm-gate'>" + "<br>".join(lines) + "</div>",
        unsafe_allow_html=True,
    )


def _render_detail(user: dict, readiness: ReadinessState,
                   revision_readiness: ReadinessState, selected_id) -> None:
    try:
        report = db.get_near_miss_report(selected_id)
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"케이스를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("케이스를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    status = str(report.get("status") or "") if report else ""
    if report is None or status not in _PENDING_STATUSES:
        # 다른 평가자가 먼저 처리했거나 삭제됨 — stale 선택 해제 후 재조회 안내.
        st.session_state.pop(_SEL_KEY, None)
        erp.detail_empty(
            "더 이상 대기 중이 아닙니다",
            "다른 사용자가 먼저 처리했을 수 있습니다 — 새로고침한 뒤 다시 선택하세요.",
        )
        return

    # ── 근거(§2: 근거 → 결정 컨트롤 → 실행 버튼) ──
    st.markdown(_detail_head_html(report, status), unsafe_allow_html=True)
    st.markdown(_detail_body_html(report), unsafe_allow_html=True)

    # 참조성 첨부(사진)도 판정 근거다 — 결정 컨트롤보다 **앞**에 온다(§2).
    photos = normalize_photo_paths(report.get("photo_paths"))
    with st.expander(f"첨부 사진 ({len(photos)}건)", expanded=bool(photos)):
        if photos:
            render_photo_thumbs(photos, key_prefix=f"nmeval_thumb_{selected_id}")
        else:
            st.caption("첨부된 사진이 없습니다.")

    # ── 결정 컨트롤: 평가 등급(§3.6 어휘) + 평가 의견 ──
    st.markdown(
        f"<div style='border-top:1px solid {_LINE_SEC};margin:12px 0 12px;'></div>",
        unsafe_allow_html=True,
    )
    grades = list(db.NEAR_MISS_GRADES)  # 도메인 소스 파생(하드코딩 금지)
    grade_key = f"{_GRADE_KEY}{selected_id}"
    # 케이스 전환/재진입 시 이전 등급 선택을 초기화한다(직전 렌더의 활성 케이스와 다르면
    # fresh 진입). 같은 케이스 내 등급 버튼 상호작용에서는 초기화하지 않아 선택이 유지된다.
    if st.session_state.get(_EVAL_ACTIVE_KEY) != selected_id:
        st.session_state[_EVAL_ACTIVE_KEY] = selected_id
        st.session_state.pop(grade_key, None)
    # 평가 등급 기본은 **미선택** — 평가자가 명시적으로 고르게 한다.
    cur_grade = st.session_state.get(grade_key)
    if cur_grade not in grades:
        cur_grade = ""
        st.session_state[grade_key] = ""
    grade_selected = cur_grade in grades

    can_write = readiness.write_enabled
    op_key = f"{_OP_KEY}{selected_id}"
    opinion = str(st.session_state.get(op_key, "") or "").strip()

    # 활성 게이트(불변 계약 보존)
    # 평가확정: 평가 등급 미선택이면 비활성(+안내). 보완요청·반려는 등급 무관.
    # 평가 착수 없이 평가 대기(SUBMITTED)에서 바로 확정한다 — 파사드
    # db.evaluate_near_miss 가 SUBMITTED/IN_REVIEW 둘 다 사전 상태로 받는다.
    eval_disabled = (not can_write) or (not grade_selected)
    if not can_write:
        eval_help = readiness.message
    elif not grade_selected:
        eval_help = "등급을 선택하세요."
    else:
        eval_help = None
    # 보완요청: 평가 대기(SUBMITTED)·평가중(IN_REVIEW) 둘 다 가능, 의견 필수. 반려와 별개
    # 의미다. 상태 조건은 실행부 db._NEAR_MISS_REVISION_STATES 와 같은 집합을 쓴다 —
    # 이 화면의 큐가 마침 같은 두 상태라 실제로는 항상 참이지만, 두 곳이 어긋나면 눌리는데
    # 실패하는 버튼이 다시 생기므로(§7.4 P1 재발 방지) 판정을 생략하지 않는다.
    # §7.4 P1 — 쓰기 가능 판정은 **실행부와 같은 007 프로브**(revision_readiness)로 한다.
    can_revise = revision_readiness.write_enabled
    revision_disabled = (
        (not can_revise) or status not in _REVISION_STATUSES or not opinion)
    if not can_revise:
        revision_help = revision_readiness.message
    elif status not in _REVISION_STATUSES:
        revision_help = "평가 대기·평가중 건만 보완요청할 수 있습니다."
    elif not opinion:
        revision_help = "평가 의견을 입력하세요(보완요청 시 필수)."
    else:
        revision_help = None
    # 반려(→REJECTED): 의견 필수.
    reject_disabled = (not can_write) or not opinion
    reject_help = (
        readiness.message if not can_write
        else (None if opinion else "평가 의견을 입력하세요(반려 시 필수).")
    )

    # 평가 등급 세그먼트 — 라벨 + S~D 버튼(선택=액센트 primary).
    st.markdown("<div class='nm-sec'>결정</div>", unsafe_allow_html=True)
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        st.markdown("<span class='nm-seg-label'>평가 등급</span>", unsafe_allow_html=True)
        for g in grades:
            hit = st.button(g, key=f"nmg_{g}_{selected_id}",
                            type="primary" if g == cur_grade else "secondary")
            if hit and g != cur_grade:
                st.session_state[grade_key] = g
                st.rerun()

    # 의견 입력 + 실행 버튼 — 반려·보완요청 공용 단일 의견.
    st.text_input(
        "평가 의견 · 반려·보완요청 시 필수",
        key=op_key, width="stretch", disabled=not can_write,
        placeholder="평가 의견을 한 줄로",
    )
    with st.container(horizontal=True, gap="small", vertical_alignment="bottom"):
        revision = st.button("보완요청", key=f"nm_act_revision_{selected_id}",
                             disabled=revision_disabled, help=revision_help, type="secondary")
        reject = st.button("반려", key=f"nm_act_reject_{selected_id}",
                           disabled=reject_disabled, help=reject_help, type="secondary")
        evaluate = st.button("평가확정", key=f"nm_act_eval_{selected_id}",
                             disabled=eval_disabled, help=eval_help, type="primary")
    _gate_notes([
        ("보완요청", revision_help if revision_disabled else None),
        ("반려", reject_help if reject_disabled else None),
        ("평가확정", eval_help if eval_disabled else None),
    ])

    grade = st.session_state.get(grade_key, cur_grade)
    if evaluate:
        _run_action(user, "평가확정", lambda: db.evaluate_near_miss(
            selected_id, grade, current_user=auth.get_current_user(),
        ))
    if revision:
        # 보완요청: 의견을 보완 사유로 서버기록(반려와 별개 의미). SUBMITTED 건은 상태가
        # 그대로라 **큐에서 빠지지 않는다** — 선택을 유지해 평가자가 상태 라벨이
        # '보완요청'으로 바뀐 것을 같은 상세에서 확인하게 한다(keep_selection).
        _run_action(user, "보완요청", lambda: db.request_near_miss_revision(
            selected_id, opinion, current_user=auth.get_current_user(),
        ), keep_selection=True)
    if reject:
        _run_action(user, "반려", lambda: db.update_near_miss_status(
            selected_id, "REJECTED", rejection_reason=opinion,
            current_user=auth.get_current_user(),
        ))


def _flash_kind_for(exc: Exception) -> str:
    """stale 충돌(다른 평가자가 먼저 처리)은 warning, 그 외 검증 실패는 error."""
    return "warning" if _STALE_MARK in str(exc) else "error"


def _run_action(user: dict, label: str, call, *, keep_selection: bool = False) -> None:
    """평가/반려 공통 실행 — 예외를 흡수해 raw traceback 을 노출하지 않는다
    (2단계 배너: 제목 + 파사드 원문 사유, stale 메시지는 가공 없이 그대로).

    ``keep_selection`` 은 처리 후에도 그 건이 **평가 대기 큐에 남는** 액션(보완요청)용이다.
    평가확정·반려는 EVALUATED/REJECTED 로 빠져 상세를 닫아야 하지만, SUBMITTED 건의
    보완요청은 상태가 그대로라 선택을 버리면 성공 직후 엉뚱한 건으로 튄다.

    의견 입력칸은 **비우지 않는다.** ``st.session_state.pop(op_key)`` + ``st.rerun()`` 으로
    비워도 rerun 요청에 프런트엔드가 위젯 값을 다시 실어 보내 입력칸에는 글자가 남고,
    파사드 호출 전에 읽는 ``opinion`` 만 빈 값이 된다 — 입력칸에는 글자가 보이는데 게이트는
    "평가 의견을 입력하세요"라고 말하는 모순 상태가 실렌더에서 재현됐다(2026-08-19 실측).
    그래서 입력값은 그대로 두고(보낸 사유가 화면에 남는다) 모순을 만들지 않는다.
    """
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
        st.session_state.pop(_SEL_KEY, None)  # 큐에서 빠지는 건은 상세를 닫는다.
    st.rerun()
