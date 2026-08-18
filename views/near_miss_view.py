"""아차사고(near-miss) 조회 — 보고서 목록(조회 전용).

DESIGN.md §2 READ_VIEW 골격: 제목 → 조회 조건 → 표. 저장/평가 액션은 이 화면의 책임이
아니다(별도 평가 화면 소관) — 여기는 순수 조회다.

2026-08-18 §2 정합: 지표 스트립을 제목 직후 슬롯(deferred container)에서 **조회 조건 뒤·
표 앞**으로 옮겨 골격의 세 영역 순서를 그대로 따르고, 내 아차사고(``near_miss_my``)와
같은 위치·같은 목록 어휘를 쓰게 했다. 스트립 자체의 존폐는 §7.2-8(§4-1 vs 지표 스트립
9화면) 미결이라 이 화면에서 단독으로 결정하지 않는다.

구조는 공용 중립 키트(``views/common/erp``)를 쓰고, 데이터/권한 로직(_scope_for
fail-closed·readiness 3-state·facade 전용)은 그대로 유지한다.

파사드 계약: ``modules/db.py`` 의 ``get_near_miss_reports(filters)`` 만 호출하고
repository 를 직접 부르지 않는다(자연키 계약, NEAR_MISS_COLUMNS).
"""
from __future__ import annotations

# DESIGN.md §0 화면 유형 규약 — 조회형.
SCREEN_ARCHETYPE = "READ_VIEW"

import base64
from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from modules import db, ui
from views import near_miss_pdf, workspace
from views.common import erp
from views.common.photo_paths import normalize_photo_paths
from views.common.photos import render_photo_thumbs
from views.master import TOKENS, banner, sheet_head
from views.master.lifecycle import Readiness, ReadinessState

_PAGE_ID = "near_miss_view"

# 필터 줄 하단 헤어라인·라벨 정렬·지표 타일은 공용 erp 키트(_KIT_CSS)가 소유한다
# (condition_panel §1-E·metric_strip). 작은 의미 텍스트는 §A-2(≥#6b665d)를 따른다.
# 선택형 목록 자연키(항상 hidden) + 선택 상태 세션키. 선택은 자연키(id)로 오간다
# (정렬·필터 후 위치 비의존). 필터/새로고침 시 _SEL_KEY 를 해제한다.
_KEY_FIELD = "_report_id"
_SEL_KEY = "nm_view_selected_id"

# 상태·원인 코드 → 한글 라벨(파사드 코드값은 NEAR_MISS_STATUSES/NEAR_MISS_CAUSE_CODES,
# 화면 표시만 한글화한다 — 코드 자체는 바꾸지 않는다).
# 상태 코드→라벨 — 6화면 단일 어휘. SUBMITTED 는 '제출'이 아니라 **'제출됨'**(DESIGN §2 상태
# 배지 표기이자 평가·개선조치·내 아차사고·등록 안내 문구와 동일, 2026-08-14 통일).
# IN_REVIEW 는 **'평가중'**(§3.6 어휘 — 한 도메인에 한 낱말: 평가 대기 → 평가중 → 평가완료).
# 종전 '검토중'은 화면명(평가 관리)·완료 상태(평가완료)와 어근이 달랐다. 영문 코드값
# (IN_REVIEW)은 그대로 두고 한글 라벨만 통일한다 — 코드값이 한글 표기를 규정하지 않는다.
_STATUS_LABEL = {
    "SUBMITTED": "제출됨",
    "IN_REVIEW": "평가중",
    "EVALUATED": "평가완료",
    "CLOSED": "종결",
    "REJECTED": "반려",
}
# §3.3 상태의 **결과** — 배지는 상태 이름만 말하고, 그 상태가 무엇을 막고 무엇을 여는지는
# 배지 옆 한 줄로 적는다. 문구는 평가 관리(near_miss_evaluate._STATUS_EFFECT)·내 아차사고와
# 같은 어휘를 쓴다(같은 상태가 화면마다 다른 결과를 말하면 안 된다).
_STATUS_EFFECT = {
    "SUBMITTED": "평가 착수 전 — 보고자 수정 가능",
    "IN_REVIEW": "보고자 수정 잠김",
    "EVALUATED": "개선조치 등록 단계",
    "REJECTED": "보고자 수정 잠김 — 반려 사유 확인",
    "CLOSED": "종결 — 변경 불가",
}
# 상태 색(이중부호화 — 라벨 텍스트는 항상 함께 표시되므로 색은 보조 신호).
# 값은 DESIGN §2 상태 배지 = ``views/master/style.py::LIFECYCLE_BADGE`` 와 **같은 색**으로
# 맞춘다(2026-08-14): 종전 이 화면은 제출됨=파랑·평가중=황토로 두 상태가 서로 바뀌어 있어,
# 평가·개선조치(lifecycle_badge_html)와 같은 상태가 화면마다 다른 색으로 보였다.
_STATUS_COLOR = {
    "SUBMITTED": TOKENS["gold"],       # #8a6212 (§1.3 대기·주의)
    "IN_REVIEW": TOKENS["info"],       # #2f4d99 (§1.3 진행·정보 — 평가중)
    "EVALUATED": TOKENS["success"],    # #2f6b45
    "CLOSED": "#5c564d",               # §2 종결 배지 텍스트
    "REJECTED": TOKENS["danger"],      # #9c3232
}
# 발생원인 코드→한글 라벨 — **6화면 단일 어휘**(2026-08-14 통일). 산업안전(KOSHA 재해발생형태)
# 현행 용어를 우선하고, 코드 의미가 겹치지 않게 단문으로 고정한다:
#   HIT=부딪힘(현행 표준어, 구 '충돌') · DROP=낙하물(물체 — 사람의 FALL=추락과 구분) ·
#   SLIP=미끄러짐 · BURN=화상 · JAM=끼임 / PINCH=협착(2026-08-13 결정 계승).
# 라벨 최대 4자(미끄러짐 = 실측 53.4px)라 목록 원인 열(72px = 53.4 + 셀 패딩·보더 16, 아래
# _COL_CONFIG)·분석 라벨 트랙(76px/모바일 64px)에서 잘리지 않는다.
_CAUSE_LABEL = {
    "JAM": "끼임", "FALL": "추락", "DROP": "낙하물", "HIT": "부딪힘",
    "SLIP": "미끄러짐", "BURN": "화상", "PINCH": "협착", "ETC": "기타",
}
# 등급 색(S 가 가장 중대 → 옅어질수록 경미). TOKENS 재사용.
_GRADE_COLOR = {
    "S": TOKENS["danger"], "A": TOKENS["gold"], "B": TOKENS["warn"],
    "C": TOKENS["info"], "D": TOKENS["ink-3"],
}
# 등급 순서(§3.1: 등급=셰브런+색텍스트, pill 아님). S=최상위 위험.
_GRADE_LEVEL = {"S": 4, "A": 3, "B": 2, "C": 1, "D": 0}


def _grade_mark(grade, empty: str = "미정") -> str:
    """등급 마크(§3.1: 셰브런+색텍스트, pill 아님). 빈 값은 중립 점 마커(empty 라벨).

    빈 값 판정은 ``_clean``(pd.isna 처리)을 쓴다 — ``str(x or "")`` 는 pandas 결측(NaN)이
    truthy 라 'NAN' 을 등급으로 렌더한다(2026-08-18 실렌더 확인)."""
    g = _clean(grade).upper()
    if not g:
        return erp.grade_mark_html(empty, TOKENS["ink-3"], level=None)
    return erp.grade_mark_html(g, _GRADE_COLOR.get(g, TOKENS["ink-2"]), level=_GRADE_LEVEL.get(g))


# §1-A 상세 메타 어휘 — 평가·개선조치 상세와 통일한다(최종 QA Low): 카드성 보더 박스
# (erp.metadata_strip) 대신 10.5px 오버라인 라벨 + 13.5px 값을 박스 없이 flex 로 나열한다.
# 작은 라벨 색은 #6b665d(캔버스 위 ≥5:1) — §A-2 대비 규칙 준수.
# 2026-08-18: 라벨 전용 모노 상수(_META_MONO)는 제거했다 — 라벨이 전부 한글이라 모노가
# 폴백을 유발했고(§1.2 서체는 본문 한글 sans), 남은 사용처가 없다.
_META_FAINT = "#6b665d"


def _meta_cell(label: str, value: str, is_html: bool = False) -> str:
    """상세 메타 한 셀(라벨 오버라인 위 / 값 아래) — 박스 없음. ``is_html`` 이면 값을 그대로
    쓴다(status_badge_html·grade_mark_html 등 신뢰 HTML), 아니면 escape 한 평문."""
    v = value if is_html else escape(str(value if value not in (None, "") else "-"))
    # 라벨은 **한글**(상태·신고자·소속·발생일·평가 등급·발생원인)이라 모노·자간을 걸지
    # 않는다 — IBM Plex Mono 에 한글 글리프가 없어 글자마다 폴백 폰트로 떨어지고, 거기에
    # letter-spacing 까지 더해져 '신 고 자'처럼 자간이 이중으로 벌어진다(2026-08-18 실렌더).
    # 모노·자간은 영숫자 전용 표기(보고번호·태그 오버라인)에만 유지한다. 크기·색은 불변.
    return (
        "<div style='display:flex;flex-direction:column;gap:3px;min-width:0;'>"
        f"<span style='font-size:10.5px;color:{_META_FAINT};'>{escape(label)}</span>"
        f"<span style='font-size:13.5px;color:{TOKENS['ink']};line-height:1.35;'>{v}</span></div>"
    )


def _read_field(label: str, value: str) -> None:
    """전폭 읽기 필드(라벨 12.5/600 + 본문 **14.5px**/1.7).

    공용 ``erp.field_block`` 은 본문이 13px 이라 같은 항목(사고내용·예방대책 등)이 평가·개선
    조치·내 아차사고의 상세 본문(14.5px/1.7)보다 작게 보였다 — DESIGN 부속서 A-3(본문
    ≥14.5px)에도 미달한다. kit 은 이 작업의 수정 범위 밖(공용)이라 화면 로컬로 같은 구조를
    14.5px 로 렌더하고, kit 쪽 정합은 별도 보고 항목으로 남긴다(2026-08-14)."""
    body = escape(value) if str(value or "").strip() else "-"
    st.markdown(
        "<div style='margin:8px 0 0;'>"
        f"<div style='font-size:12.5px;font-weight:600;color:{TOKENS['ink-2']};"
        "margin-bottom:2px;'>" + escape(label) + "</div>"
        f"<div style='font-size:14.5px;line-height:1.7;color:{TOKENS['ink']};"
        f"white-space:pre-wrap;text-wrap:pretty;'>{body}</div></div>",
        unsafe_allow_html=True,
    )

# 표시 8열 — 2026-08-18 제안등급(proposed_grade) 열 폐기(§7.2-1b) 상태를 유지한다: 등록
# 폼에 입력 경로가 없어 항상 비는 열이었고, 남은 등급이 하나뿐이라 '확정' 수식어도 불필요해
# 헤더는 §3.6 축약 허용 범위인 **'등급'**을 쓴다(정본 '평가 등급'은 상세·필터처럼 폭이
# 넉넉한 곳에 그대로).
#
# 순서는 2026-08-18 사용자 확정 지시다:
#   문서번호 · 발생일 · 원인 · 작업명 · 소속 · 신고자 · 등급 · **상태(제일 우측)**.
# 종전 순서(보고번호·작업명·신고자·소속·발생일·등급·상태·원인)는 상태가 7번째, 원인이
# 마지막이라 지시와 어긋났다. 식별(번호·언제·무엇 때문에) → 서술(무슨 작업) → 주체(소속·
# 신고자) → 판정(등급·상태) 순으로 읽히고, 판정 결과인 상태가 행 끝을 닫는다.
#
# 헤더 낱말은 이번 변경에서 **'보고번호'로 유지**한다. 확정 지시의 낱말은 '문서번호'지만
# 이 앱은 같은 개념에 보고번호(조회·내 아차사고 표/평가·개선조치 주석)와 접수번호
# (near_miss_submit 접수 배너)를 이미 병용하고 있어, 낱말 교체는 §3.6 어휘 단일화로 한
# 번에 해야 한다(이 두 파일 밖으로 파급 — 등록 완료 배너·DESIGN §1.2 예시). 범위 밖이라
# 순서만 지시대로 바꾸고 낱말은 보고 항목으로 남긴다.
_DISPLAY_COLUMNS = [
    "보고번호", "발생일", "원인", "작업명", "소속", "신고자", "등급", "상태",
]

# ── 컬럼 폭 — **실제 값의 최대 길이에서 역산한 고정폭**(flex 없음). ─────────────────────
# 2026-08-18 사용자 확정: "남는 가로 폭을 flex 로 아무 열에나 흡수시키지 마라. 남으면
# 남긴다." 종전에는 작업명 flex:2 · 소속 flex:1 이 잔여 폭을 흡수해 1440 폭에서 작업명이
# **407px**(표 폭의 35%)이 됐다 — 실제 값은 '원료 투입'·'설비 청소' 4~5자(57px)다. 폭이
# 내용과 무관하게 정해지는 것이 근본 원인이라 flex 를 없애고 전부 고정폭으로 바꾼다.
# 표 우측에 남는 빈 공간은 결함이 아니다(지시).
#
# 폭 산식 — width = 4의 배수로 올림( max(값 실폭, 헤더 실폭) + 16 ).
# +16 은 추정이 아니라 실측이다(2026-08-18): 셀은 `.ag-cell` 패딩 7+7 **에 더해 좌우
# 1px 보더**가 있어 가용폭 = width − 16 이고, 헤더는 `.ag-header-cell` 패딩 8+8(보더 없음,
# 라벨 자체 패딩 0)이라 역시 width − 16 이다. 보더 2px 을 빠뜨린 1차 산정(패딩 14만 반영)은
# 보고번호·소속·원인·상태 4열이 1~2px 씩 말줄임됐다 — 실렌더 재계측으로 확인·정정했다.
#
# 한글 계수(실측 — 추정치 아님): 조회 표 AG Grid iframe 안에서 셀/헤더의 computed style
# (font-family·size·weight·letter-spacing)을 그대로 복사한 hidden span 에 문자열을 넣고
# getBoundingClientRect().width 를 읽었다(Chromium 1440×900, sample, 포트 8512).
#   · 셀 14.5px sans  — 한글 1자 13.34px / 숫자 1자 8.07px → **한글 = 숫자의 1.65배**
#                       (한글 폭 ≈ 글자 크기 × 0.92)
#   · 헤더 12.5px/600 — 한글 1자 11.5px
#   · 보고번호 셀 모노(IBM Plex Mono 14.5px + letter-spacing 0.145px) — 숫자 1자 8.12px
# 예측값은 라이브 셀 실폭과 대조 검증했다('PET생산부(원료실)' 예측 117.9 ↔ 실측 118).
#
# 열별 근거(값 최대 → 필요폭 → 채택):
#   보고번호 89.3px('202612-9999' = YYYYMM-NNNN 11자 고정, docs/database.md 자연키 계약)
#            → 105.3 → **108**. 월순번 5자리(>9999건/월)는 고려하지 않는다.
#   발생일   74.2px('2026-12-31' ISO 10자, 값 형식 고정) → 90.2 → **92**
#   원인     53.4px('미끄러짐' 4자 = _CAUSE_LABEL 8종 중 최장, 닫힌 집합) → 69.4 → **72**
#   작업명  153.6px('3라인 컨베이어 벨트 점검' 14자) → 169.6 → **172**. ★가정 — work_name 은
#            max_chars=120 자유 입력이라 실DB 최대를 모른다. sample 최장은 5자(57px)뿐이라
#            근거가 못 되고, 등록 폼 placeholder 의 예시값(near_miss_submit.py:512)을 실무
#            상한 가정으로 삼았다. 이보다 긴 값은 말줄임되고 전문은 행 클릭 상세에서 본다.
#   소속    117.9px('PET생산부(원료실)' = sample 부서명 최장) → 133.9 → **136**. ★가정 —
#            실DB 부서명이 더 길면 말줄임(상세 메타에 전문).
#   신고자   53.4px(한글 성명 4자) → 69.4 → **72**. ★가정 — sample 은 3자(40px)뿐이다.
#   등급      9.7px('S' 1자)이라 값이 아니라 **헤더**('등급' 23px)가 폭을 정한다 → 39 → **40**
#   상태     53.4px('평가완료' 4자 = _STATUS_LABEL 5종 중 최장, 닫힌 집합) → 69.4 → **72**
# 합계 764px. 1440 뷰포트에서 표 가용폭 1167px → 우측 403px 는 빈 공간으로 남긴다.
# 같은 성격 열은 내 아차사고(near_miss_my._COL_CONFIG)와 **같은 값**을 쓴다(기존 계약).
_COL_CONFIG = {
    "보고번호": {"width": 108, "cellStyle": {"fontFamily": "'IBM Plex Mono', monospace",
                                          "letterSpacing": "0.01em"}},
    "발생일": {"width": 92},
    "원인": {"width": 72},
    "작업명": {"width": 172},
    "소속": {"width": 136},
    "신고자": {"width": 72},
    "등급": {"width": 44},
    "상태": {"width": 72},
}


def render(user: dict) -> None:
    # near_miss_view 는 nav.py 에 등록돼 있다(그룹 '아차사고' › '조회'). 제목/설명은 nav.py
    # 라벨과 정합되게 명시한다(desc 는 nav.py 와 동일 문구). page_chrome_for 로 nav 라벨을
    # 단일 출처에서 끌어오는 통일은 후속(통합 담당) — 현재는 screen_frame 명시 문자열로 충분.
    # §1-E READ: 헤더 중립 프레임만(아이콘 밴드 제거 — 표준 아이콘 8종은 상단 52px 헤더가
    # 소유·§A-5). 조회/새로고침은 필터 줄 우측 [조회] 버튼이 담당한다(아래).
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="아차사고 조회",
        desc="아차사고 보고서를 조건별로 조회합니다.",
        breadcrumb="아차사고 › 조회",
    )
    # 접근 범위(제품 결정 — Coordinator): 아차사고 조회는 전 사용자에게 열려 있고
    # 회사 전체 범위이며, 신고자 이름·상세 내용을 숨기지 않는다. 과거 평가자 전용 게이트
    # (auth.can_evaluate_near_miss)와 MANAGER 부서 스코프(_scope_for)는 이 경로에서
    # 제거했다. _scope_for 정의 자체는 회귀 계약(scripts/test_near_miss_view.py)이
    # 고정하고 있어 남겨두되(과거 스코프 동작 보존), render 는 더 이상 호출하지 않는다.
    _readiness().banner()
    # 헤더 인쇄 아이콘 기본 음영(상세 미선택). 유효 상세가 렌더되면 _render_result_detail 이
    # 활성으로 다시 발행한다(다음 rerun 헤더 반영 — 1-rerun 지연 수용).
    ui.publish_header_actions("near_miss_view", {"print": (True, "보고서를 먼저 선택하세요")})

    try:
        dept_names = _all_dept_names()
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"조직 정보를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("조직 정보를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    # 영역 순서(§2 READ_VIEW: 제목 → 조회 조건 → 표): 필터 줄(조건 패널·우측 인라인 [조회])
    # → 헤어라인(condition_panel 소유) → 지표 스트립 → 건수 행 → 표 → 상세.
    # [조회] 클릭이 조회 트리거.
    q, clicked = _collect_conditions("all", None, dept_names)
    if clicked:
        # 필터/조회로 결과 집합이 바뀌면 이전 선택을 해제한다(stale 상세 방지).
        st.session_state.pop(_SEL_KEY, None)

    # U3: 진입 시 세션 최초 1회 기본 조건(최근 90일)으로 자동 조회 seed — 빈 안내 패널 대신 즉시
    # 데이터가 보인다. 최초 1회만이며 이후 [조회]가 명시 갱신한다(매 rerun 자동조회 아님).
    workspace.seed_query_once(_PAGE_ID, q)
    saved = workspace.run_query(_PAGE_ID, clicked, q)
    if saved is None:  # seed 이후엔 도달하지 않음(방어적 유지)
        ui.empty_state("조회 조건을 지정하고 [조회]를 눌러 아차사고 보고서를 확인하세요.", head="아차사고 조회")
        return

    try:
        df = db.get_near_miss_reports(_facade_filters(saved))
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"아차사고 데이터를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("아차사고 데이터를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    has_filters = _has_filters(saved)
    if df.empty:
        st.session_state.pop(_SEL_KEY, None)  # 빈 결과 → 선택 해제
        if has_filters:
            ui.empty_state("조회 조건에 해당하는 아차사고 보고서가 없습니다.", head="아차사고 조회")
        else:
            ui.empty_state("등록된 아차사고 보고서가 없습니다.", head="아차사고 조회")
        return

    try:
        display = _to_display(df)
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"사용자·부서 정보를 불러오지 못해 목록을 표시할 수 없습니다. ({exc})")
        return
    except Exception:
        st.error("사용자·부서 정보를 불러오지 못해 목록을 표시할 수 없습니다. 잠시 후 다시 확인하세요.")
        return

    # 지표 타일(조회 조건 뒤·표 앞) — 조회 건수·상태 분해(기존 데이터 파생). 내 아차사고와
    # 같은 위치·같은 라벨을 쓴다(§2 골격의 세 영역 사이에 끼우고 제목을 밀어내지 않는다).
    erp.metric_strip(_view_metrics(df))

    # primary — 선택형 목록(select_grid). 구 st.selectbox 상세 선택을 없애고 행 클릭이 상세
    # 선택을 대체한다(Codex: 목록 클릭=상세). 네이티브 single-selection: 색 틴트+체크박스로
    # 이중부호화(§4), 선택 자연키(_report_id)를 반환한다. 등급/상태 색은 보조 신호(라벨 유지).
    frame = _select_frame(df, display)
    sheet_head("아차사고 보고서 목록", count=len(frame))
    status_rules = {label: _STATUS_COLOR[code] for code, label in _STATUS_LABEL.items()}
    picked = erp.select_grid(
        frame, key=f"{_PAGE_ID}_grid", key_field=_KEY_FIELD,
        columns=_DISPLAY_COLUMNS, selected_key=st.session_state.get(_SEL_KEY),
        col_config=_COL_CONFIG,
        checkbox_marker=False,  # §0-1: 행 클릭이 곧 선택(상세 열기용 체크박스 금지)
        scroll_affordance=True,  # 모바일 폭에서 "오른쪽에 열이 더 있음" 신호(상시 스크롤바)
        color_rules={
            "등급": _GRADE_COLOR,
            "상태": status_rules,
        },
    )
    # 선택을 상세 렌더 전에 소비한다 — select_grid 의 selectionChanged rerun 이 이미 일어난
    # run 이므로 세션만 갱신하면 추가 st.rerun 없이 곧바로 상세를 그린다(즉시 상세).
    if picked is not None and picked != st.session_state.get(_SEL_KEY):
        st.session_state[_SEL_KEY] = picked

    # details — 행 클릭으로 선택된 보고서만 아래 전체폭 상세로 렌더한다(§8-2: '선택하세요'
    # 빈 안내 패널을 두지 않는다 — 선택 전에는 상세 영역 자체를 그리지 않는다).
    # 하단 '조회 건수' 박스는 제거하고 표 위 지표 타일로 이관했다.
    if st.session_state.get(_SEL_KEY):
        st.write("")
        _render_result_detail(df)


def _view_metrics(df: pd.DataFrame) -> list[tuple]:
    """조회 결과 지표 타일 항목(기존 데이터 파생) — 조회 건수 + 상태 분해(미평가·평가완료·
    종결·반려). 새 지표를 만들지 않고 status 컬럼 집계만 쓴다."""
    n = len(df)
    codes = df["status"].astype(str) if "status" in df.columns else pd.Series(dtype=str)
    counts = codes.value_counts().to_dict()
    pending = counts.get("SUBMITTED", 0) + counts.get("IN_REVIEW", 0)
    evaluated = counts.get("EVALUATED", 0)
    closed_rej = counts.get("CLOSED", 0) + counts.get("REJECTED", 0)
    # 라벨은 내 아차사고(_my_metrics)와 **같은 낱말**을 쓴다(§3.6) — 같은 계산(SUBMITTED+
    # IN_REVIEW)을 한쪽은 '미평가', 다른 쪽은 '진행중'이라 부르던 불일치를 '미평가'로 통일.
    return [
        ("조회 건수", n, "건", "TOTAL", n > 0),
        ("미평가", int(pending), "건", "PENDING", False),
        ("평가완료", int(evaluated), "건", "DONE", False),
        ("종결·반려", int(closed_rej), "건", "CLOSED", False),
    ]


def _select_frame(df: pd.DataFrame, display: pd.DataFrame) -> pd.DataFrame:
    """8열 표시 프레임에 숨김 자연키(_report_id)를 붙인 select_grid 입력 프레임.

    ``_to_display`` 는 df.iterrows() 순서로 8열을 만들므로 df 의 id 를 같은 순서(위치)로
    실으면 행이 정합한다(select_grid 가 자연키로 위치 비의존 선택을 보장). 표시 8열은
    ``_to_display`` 계약(테스트 고정)을 건드리지 않고 그대로 재사용한다."""
    frame = display.copy()
    frame[_KEY_FIELD] = [str(r.get("id")) for _, r in df.iterrows()]
    return frame


def _render_result_detail(df: pd.DataFrame) -> None:
    """선택 행(_SEL_KEY)의 보고서 상세를 그룹2 표시 어휘로 조회 전용 렌더한다.

    쓰기 액션(detail_actions) 없음 — READ_VIEW 는 순수 조회다. 상태 badge → (반려 사유
    배너) → 짧은 메타 2열 → 핵심 내용(작업명·사고내용) → 부차 서술 접기 순으로, 신고자
    이름·전체 내용을 숨기지 않는다(전사 공개 조회 계약)."""
    selected_id = st.session_state.get(_SEL_KEY)
    if not selected_id:
        return  # 호출부가 선택 시에만 부르지만 방어적으로 무렌더(§8-2: 빈 안내 패널 금지)
    match = df[df["id"].astype(str) == str(selected_id)]
    if match.empty:
        # 목록에서 사라진 stale 선택 — 해제하고 조용히 미선택으로 되돌린다(안내 패널 없음).
        st.session_state.pop(_SEL_KEY, None)
        return
    report = match.iloc[0].to_dict()

    # 신고자 이름·부서명 라벨링(부가 정보) — 조회 실패로 상세 전체를 막지 않고 코드로 폴백한다.
    # U6: 폴백을 무음으로 삼키지 않고 인라인 경고로 표면화한다(코드값 폴백은 유지).
    meta_load_failed = False
    try:
        users = db.get_users()
        depts = db.get_departments()
    except Exception:  # noqa: BLE001 — 부가 라벨 조회 실패(상세 본문은 계속 렌더).
        users = pd.DataFrame()
        depts = pd.DataFrame()
        meta_load_failed = True
    if meta_load_failed:
        banner("warn", "일부 표시 정보(신고자·부서명)를 불러오지 못했습니다. 코드값으로 표시합니다.")
    name_of = {str(r["emp_no"]): str(r["name"]) for _, r in users.iterrows()} if not users.empty else {}
    dept_of = {str(r["dept_code"]): str(r["dept_name"]) for _, r in depts.iterrows()} if not depts.empty else {}

    emp = _clean(report.get("reporter_emp_no"))
    dept = _clean(report.get("dept_code"))
    status = _clean(report.get("status"))
    cause = _clean(report.get("cause_code"))

    # ── 상단: 보고번호(제목 §2 20/700). 상태는 메타 스트립에서 pill 로 노출(§3.2). ──
    report_no = escape(_clean(report.get("report_no")) or "(번호 미상)")
    st.markdown(
        f"<div style='font-size:20px;font-weight:700;color:{TOKENS['ink']};"
        f"line-height:1.2;margin:2px 0 8px;'>{report_no}</div>",
        unsafe_allow_html=True,
    )

    # ── 반려 사유(있을 때) — 종결 분기의 경고 배너. ──
    if status == "REJECTED" and _clean(report.get("rejection_reason")):
        banner("warn", f"반려 사유: {_clean(report.get('rejection_reason'))}")

    # ── 읽기 메타(§1-A: 라벨 모노 오버라인 + 값, 박스 없이 flex 나열 — 평가·개선조치 상세와
    #    통일). 형식 분리(§3.1): 상태=pill / 등급=grade_mark(셰브런+색텍스트) / 발생원인=평문. ──
    status_badge = erp.status_badge_html(
        _STATUS_LABEL.get(status, status or "-"),
        _STATUS_COLOR.get(status, TOKENS["ink-3"]),
    )
    # §3.3: 배지 옆에 그 상태의 **결과**를 한 줄로 붙인다(상태 이름만으로는 무엇이 막히고
    # 열리는지 알 수 없다). 제안등급 열이 빠지면서 생긴 폭을 이 표기가 쓴다.
    effect = _STATUS_EFFECT.get(status, "")
    if effect:
        status_badge += (
            f"<span style='margin-left:8px;font-size:12px;color:{_META_FAINT};'>"
            f"{escape(effect)}</span>"
        )
    meta_cells = "".join([
        _meta_cell("상태", status_badge, is_html=True),
        _meta_cell("신고자", name_of.get(emp, emp) or "-"),
        _meta_cell("소속", dept_of.get(dept, dept) or "-"),
        _meta_cell("발생일", _clean(report.get("incident_date")) or "-"),
        _meta_cell("평가 등급", _grade_mark(report.get("confirmed_grade"), empty="미정"), is_html=True),
        _meta_cell("발생원인", _CAUSE_LABEL.get(cause, cause) or "-"),
    ])
    st.markdown(
        "<div style='display:flex;flex-wrap:wrap;gap:12px 26px;padding:2px 0 8px;'>"
        f"{meta_cells}</div>",
        unsafe_allow_html=True,
    )
    _read_field("작업명", _clean(report.get("work_name")))
    _read_field("사고내용", _clean(report.get("incident_content")))

    # ── 부차 참조 서술(발생원인 상세·작업내용·예방대책·현장 상황) 기본 접힘으로 상세 높이 bound. ──
    with st.expander("보고서 상세 더 보기", expanded=False):
        cause_detail = _clean(report.get("cause_detail"))
        if cause_detail:
            _read_field("발생원인 상세", cause_detail)
        _read_field("작업내용", _clean(report.get("work_content")))
        _read_field("예방대책", _clean(report.get("countermeasure")))
        _read_field("작업현장 상황설명", _clean(report.get("site_description")))

    # ── 사진(있을 때) — 서명 URL 썸네일 그리드(조회 전용, 클릭 확대는 st.image 기본). ──
    _render_view_photos(report.get("photo_paths"))

    # ── A4 세로 PDF 출력 — 상세 다운로드 버튼(발견성) + 헤더 인쇄 아이콘 트리거(자동 다운로드). ──
    # 유효 상세 표시 중 → 인쇄 활성(헤더가 다음 rerun 반영)
    ui.publish_header_actions("near_miss_view", {"print": (False, None)})
    pdf_data = near_miss_pdf.report_to_pdf_data(
        report,
        reporter=name_of.get(emp, emp) or "-",
        dept=dept_of.get(dept, dept) or "-",
        status_label=_STATUS_LABEL.get(status, status or "-"),
        cause_label=_CAUSE_LABEL.get(cause, cause) or "-",
        status_effect=_STATUS_EFFECT.get(status, ""),  # §3.3 — 출력물에도 상태의 결과를 남긴다
    )
    fname = f"{pdf_data['report_no']}.pdf"
    try:
        pdf_bytes = near_miss_pdf.build_report_pdf(pdf_data)
    except Exception:
        pdf_bytes = None
        st.session_state.pop("nmv_print_req", None)
        st.caption("PDF 생성에 실패했습니다. 잠시 후 다시 시도하세요.")
    if pdf_bytes:
        st.download_button(
            "PDF 저장 (A4)", data=pdf_bytes, file_name=fname,
            mime="application/pdf", key="nmv_pdf_dl",
        )
        # 헤더 인쇄 아이콘(nmv_print_req) → data-URI 자동 다운로드(추가 클릭 없이).
        if st.session_state.pop("nmv_print_req", False):
            b64 = base64.b64encode(pdf_bytes).decode("ascii")
            components.html(
                f"<a id='nmvdl' href='data:application/pdf;base64,{b64}' "
                f"download='{escape(fname)}'></a>"
                "<script>document.getElementById('nmvdl').click();</script>",
                height=0,
            )


def _photo_overline(count: int) -> None:
    """사진 섹션 오버라인(카드 아님·헤어라인 없이 라벨만) — §2 팔레트 중립 텍스트.

    한글('사진')이 섞여 있어 모노·자간을 걸지 않는다(한글 글리프 부재 → 글자별 폴백 +
    letter-spacing 이중 적용으로 자간이 벌어진다). 개수는 숫자지만 라벨과 한 문자열이다."""
    st.markdown(
        f"<div style='font-size:11px;color:{TOKENS['ink-2']};margin:14px 0 8px;'>"
        f"사진 · {count}</div>",
        unsafe_allow_html=True,
    )


def _render_view_photos(photo_paths) -> None:
    """첨부 사진을 서명 URL 썸네일 그리드로 조회 렌더한다(없으면 아무것도 그리지 않음).

    표시 URL 은 파사드(db.get_near_miss_photo_url)가 소유한다 — sample 은 data:URL, supabase 는
    단기 서명 URL. 클릭 확대는 st.image 기본 전체화면 버튼을 쓴다(추가 배선 없음)."""
    paths = normalize_photo_paths(photo_paths)
    if not paths:
        return
    _photo_overline(len(paths))
    render_photo_thumbs(paths, key_prefix="nmv_thumb")  # U5 공용 헬퍼(읽기 전용)


def _all_dept_names() -> dict:
    """부서코드→부서명 전체 맵(회사 전체 범위 조건 드롭다운·표시용)."""
    depts = db.get_departments()
    if depts.empty:
        return {}
    return {str(r["dept_code"]): str(r["dept_name"]) for _, r in depts.iterrows()}


# ---------- 접근 범위(fail-closed) — 회귀 계약(test_near_miss_view)이 고정. 현재 render 는
# 회사 전체 공개로 전환되어 이 함수를 호출하지 않는다(정의만 보존). ----------
def _scope_for(user: dict) -> tuple[str, str | None, dict]:
    """조회 범위를 결정한다(dashboard._scope_for 와 같은 fail-closed 관행).

    반환: (scope, manager_dept, dept_names)
      - ("all", None, {코드: 이름 전체})       — ADMIN, 또는 안전담당자(역할과 무관하게
        부서를 넘나드는 안전 점검이 직무이므로 전체 조회를 허용한다).
      - ("scoped", dept, {코드: 이름})         — MANAGER 且 유효 담당 부서일 때만.
      - ("blocked", None, {})                 — 부서 미확정 MANAGER(그 외는
        can_evaluate_near_miss 게이트를 통과하지 못해 이 함수에 도달하지 않는다).
    """
    depts = db.get_departments()
    dept_names = {
        str(r["dept_code"]): str(r["dept_name"]) for _, r in depts.iterrows()
    } if not depts.empty else {}
    role = str(user.get("role") or "").strip().upper()
    if role == "MANAGER":
        dept = str(user.get("dept_code") or "").strip() or None
        if dept and dept in dept_names:
            return "scoped", dept, dept_names
        return "blocked", None, {}
    # ADMIN 또는 안전담당자(role 무관) — 전체 조회.
    return "all", None, dept_names


# ---------- 조회 조건(col-N 우측 인라인 라벨) ----------
def _collect_conditions(scope: str, manager_dept: str | None, dept_names: dict) -> dict:
    """조건 패널을 렌더하고 facade 조회조건 dict 를 만든다.

    필드 key 는 기존 위젯 key suffix 와 동일하게 유지해 세션 상태를 보존한다
    (period_on/from/to/dept/grade/status/cause). 기간 미지정 시 날짜 필드는 비활성.
    """
    # 기간 select — 기본 '최근 90일'(U3: 진입 즉시 bounded 조회로 '조회를 누르세요' 빈 패널 해소).
    # '기간 지정' 선택 시에만 날짜 2필드를 렌더하고, '전체'는 전 기간(date 파라미터 생략).
    period_on = st.session_state.get(f"{_PAGE_ID}_period_mode") == "기간 지정"

    if scope == "scoped":
        dept_field = erp.Field(
            key="dept", label="부서", kind="select",
            options=[manager_dept], disabled=True, width=180,
            format_func=lambda c: dept_names.get(c, c),
        )
    else:
        dept_field = erp.Field(
            key="dept", label="부서", kind="select",
            options=[workspace.ALL] + sorted(dept_names), width=180,
            format_func=lambda c: dept_names.get(c, c),
        )

    # 필터 순서(피드백3): 자주 쓰는 축을 앞에 둔다 — 기간 → 부서 → 상태, 그 뒤 평가 등급 → 원인.
    # 기본 기간은 '전체'(미지정=전 기간 조회, date 파라미터 생략). '기간 지정' 선택 시에만 날짜
    # 2필드를 렌더한다(§0.6 강제: 비활성 필드가 자리를 상시 점유하지 않음). cols=5 로 미지정
    # 5필드는 한 줄에 우선 배치(flex-wrap — 좁아지면 자연 wrap).
    fields: list[erp.Field] = [
        erp.Field(key="period_mode", label="기간", kind="select", width=150,
                  options=["최근 90일", "전체", "기간 지정"]),
    ]
    if period_on:
        fields += [
            erp.Field(key="from", label="발생일(시작)", kind="date",
                      value=date.today() - timedelta(days=90), width=150),
            erp.Field(key="to", label="발생일(종료)", kind="date",
                      value=date.today(), width=150),
        ]
    fields += [
        dept_field,
        # 상태를 평가 등급보다 앞에(자주 쓰는 축 우선). 짧은 코드값 select 는 내용 맞춤 폭(§0.6).
        erp.Field(key="status", label="상태", kind="select", width=140,
                  options=[workspace.ALL] + list(db.NEAR_MISS_STATUSES),
                  format_func=lambda v: _STATUS_LABEL.get(v, v) if v != workspace.ALL else v),
        # 필터 key(grade)와 파사드 필드(confirmed_grade)는 코드값이라 그대로 두고 라벨만
        # §3.6 정본으로 통일한다(폭 140 — 축약 없이 '평가 등급'이 들어간다).
        erp.Field(key="grade", label="평가 등급", kind="select", width=140,
                  options=[workspace.ALL] + list(db.NEAR_MISS_GRADES)),
        erp.Field(key="cause", label="원인", kind="select", width=140,
                  options=[workspace.ALL] + list(db.NEAR_MISS_CAUSE_CODES),
                  format_func=lambda v: _CAUSE_LABEL.get(v, v) if v != workspace.ALL else v),
    ]
    # [조회]를 필터 줄 우측에 인라인(오렌지)으로. U4: content_fit=True 로 짧은 코드값 select 는
    # 내용 맞춤 폭(값 길이 비례)으로 흘리고 좁아지면 자연 wrap(§0.6).
    v, clicked = erp.condition_panel(_PAGE_ID, fields, content_fit=True,
                                     submit=("조회", f"{_PAGE_ID}_go"),
                                     submit_icon=":material/search:")  # 조회 아이콘 앱 전체 통일(2026-08-07)

    mode = v["period_mode"]
    if mode == "최근 90일":
        date_from = (date.today() - timedelta(days=90)).isoformat()
        date_to = date.today().isoformat()
        period_active = True
    elif mode == "기간 지정":
        date_from = v["from"].isoformat() if "from" in v else ""
        date_to = v["to"].isoformat() if "to" in v else ""
        period_active = True
    else:  # 전체 — 전 기간(date 파라미터 생략)
        date_from = date_to = ""
        period_active = False
    q = {
        "dept": v["dept"],
        "grade": v["grade"],
        "status": v["status"],
        "cause": v["cause"],
        "period_on": period_active,
        "date_from": date_from,
        "date_to": date_to,
    }
    return q, clicked


def _has_filters(q: dict) -> bool:
    return (
        q.get("dept") != workspace.ALL
        or q.get("grade") != workspace.ALL
        or q.get("status") != workspace.ALL
        or q.get("cause") != workspace.ALL
        or bool(q.get("period_on"))
    )


def _facade_filters(q: dict) -> dict:
    filters: dict = {}
    if q.get("dept") != workspace.ALL:
        filters["dept_code"] = q["dept"]
    if q.get("grade") != workspace.ALL:
        filters["confirmed_grade"] = q["grade"]
    if q.get("status") != workspace.ALL:
        filters["status"] = q["status"]
    if q.get("cause") != workspace.ALL:
        filters["cause_code"] = q["cause"]
    if q.get("date_from"):
        filters["date_from"] = q["date_from"]
    if q.get("date_to"):
        filters["date_to"] = q["date_to"]
    return filters


# ---------- readiness (migration 006 3-state) ----------
def _readiness() -> ReadinessState:
    if db.is_sample_mode():
        return ReadinessState.ready()
    probe = db.near_miss_schema_probe()
    if probe == Readiness.PROBE_ERROR.value:
        return ReadinessState.probe_error(
            "아차사고 스키마 상태 확인에 실패했습니다 — 재확인이 필요합니다."
        )
    if probe == Readiness.NOT_READY.value:
        return ReadinessState.not_ready(
            "아차사고 스키마가 아직 적용되지 않아 보고서를 조회할 수 없습니다."
        )
    return ReadinessState.ready()


# ---------- 표시 변환 ----------
def _clean(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _to_display(df: pd.DataFrame) -> pd.DataFrame:
    users = db.get_users()
    name_of = {
        str(r["emp_no"]): str(r["name"]) for _, r in users.iterrows()
    } if not users.empty else {}
    depts = db.get_departments()
    dept_name_of = {
        str(r["dept_code"]): str(r["dept_name"]) for _, r in depts.iterrows()
    } if not depts.empty else {}

    rows = []
    for _, r in df.iterrows():
        emp = _clean(r.get("reporter_emp_no"))
        dept = _clean(r.get("dept_code"))
        # dict 삽입 순서가 곧 표시 열 순서다 — _DISPLAY_COLUMNS 와 같은 순서로 싣는다
        # (2026-08-18 확정 순서: 번호 → 발생일 → 원인 → 작업명 → 소속 → 신고자 → 등급 → 상태).
        rows.append({
            "보고번호": _clean(r.get("report_no")),
            "발생일": _clean(r.get("incident_date")) or "-",
            "원인": _CAUSE_LABEL.get(_clean(r.get("cause_code")), _clean(r.get("cause_code")) or "-"),
            "작업명": _clean(r.get("work_name")),
            "소속": dept_name_of.get(dept, dept) or "-",
            "신고자": name_of.get(emp, emp) or "-",
            "등급": _clean(r.get("confirmed_grade")) or "-",
            "상태": _STATUS_LABEL.get(_clean(r.get("status")), _clean(r.get("status"))),
        })
    return pd.DataFrame(rows)
