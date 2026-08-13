"""내 아차사고 — 컬럼형 테이블 선택(§0 MASTER_DETAIL) + SUBMITTED 자기수정.

    제목/설명 → [지표 스트립] → [상태·기간 조건] → [보고서 표(행 클릭 = 선택)]
    → [선택 건 전체폭 상세: 진행 단계 · 본문 블록 · 사진 · 수정]

2026-08-13 사용자 지시("컬럼 나눠줘 — 아차사고 조회 테이블 참조")로 한 줄 요약
아코디언(구 §1-B 목록형)에서 **컬럼형 표 + 전체폭 상세**로 전환했다. 한 줄 요약은
보고번호·작업명·발생일·원인·상태가 한 문장으로 이어져 세로 비교가 불가능했고, 등급
(제안/확정)은 아예 목록에 없어 펼쳐야만 보였다. 표로 나누면 같은 정보가 열로 정렬되고
조회 화면(``views/near_miss_view``)과 같은 목록 어휘를 공유한다.

- 목록 어휘는 조회 화면과 동일 계열: ``erp.select_grid`` + 같은 컬럼 서식(보고번호 모노 ·
  발생일 ISO · 상태/등급 색 규칙은 ``views.master.TOKENS`` 동일 값). 신고자·소속 열은
  본인 전용 화면이라 항상 같은 값이므로 싣지 않는다(모바일 폭 절약).
- 행 클릭이 곧 선택이자 상세 열기(§0 금지 1 — 상세 여는 체크박스 없음, ``checkbox_marker=
  False``). 행 피치는 USER·터치 variant 44px(``views/lodging_my`` 와 동일 계약).
- 좌우 분할·"보고서를 선택하세요" 빈 패널 없음(§0 금지 1·2) — 미선택이면 상세 영역 자체를
  그리지 않는다(조회 화면과 동일).
- 카드 금지(§0 금지 5). §2 팔레트 밖 색 금지(§0 금지 8).
- 좁은 폭(390px)에서는 표가 **컨테이너 안에서** 가로 스크롤한다(§5 "표는 overflow-x:auto") —
  페이지 자체는 가로 스크롤하지 않는다.

기능 계약(불변 — 표현 계층만 교체):
  - 목록 범위는 위젯이 아니라 인증 세션 사번으로 고정(``reporter_emp_no=<세션 사번>``).
  - 본문 수정은 소유자 + ``SUBMITTED`` 상태에서만. 수정도 세션 사용자를 그대로 넘겨
    (``db.update_near_miss_report(..., current_user=...)``) 파사드가 소유자·상태를 서버측
    재확인한다(타인 건 열람·수정 위조 방지). db.py 무수정.
  - 보완요청(info)·반려(warn)는 별개 시각·문구 유지. U/M/A 공유 — USER 모바일 동작 보존.
"""
from __future__ import annotations

# DESIGN.md §0 MASTER_DETAIL — 목록(표 선택) + 전체폭 상세/워크플로.
SCREEN_ARCHETYPE = "MASTER_DETAIL"

from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st

from modules import auth, db, photo_storage, ui
from views import workspace
from views.common import erp, scaffold
from views.common.photo_paths import normalize_photo_paths
from views.common.photos import render_photo_thumbs
from views.master import TOKENS, banner, sheet_head
from views.master.lifecycle import Readiness, ReadinessState

_PAGE_ID = "near_miss_my"
_SEL_KEY = "nm_my_selected_id"      # 선택(상세를 여는) 보고서 id(문자열).
_KEY_FIELD = "_report_id"           # 표에 항상 hidden 으로 실리는 자연키(선택 반환용).

_STATUS_LABEL = {
    "SUBMITTED": "제출됨", "IN_REVIEW": "검토중", "EVALUATED": "평가완료",
    "REJECTED": "반려", "CLOSED": "종결",
}
_CAUSE_LABEL = {
    "JAM": "끼임", "FALL": "추락", "DROP": "낙하물", "HIT": "부딪힘·충돌",
    "SLIP": "미끄러짐·넘어짐", "BURN": "화상·고온", "PINCH": "협착", "ETC": "기타",
}
_EDITABLE_STATUS = "SUBMITTED"

# 업로드 상한(계약: 원본 ≤10MB/장). photo_storage.MAX_UPLOAD_BYTES 단일 출처(읽기만) +
# 위젯 인자(max_upload_size, MB) + 서버 config(maxUploadSize) 다층 차단.
_MAX_UPLOAD_BYTES = photo_storage.MAX_UPLOAD_BYTES
_MAX_UPLOAD_MB = max(1, _MAX_UPLOAD_BYTES // (1024 * 1024))

# ── §2 팔레트 (팔레트 밖 색 금지 §0-8) — 리터럴 고정. ──
_INK = "#1c1a17"
_INK2 = "#4a453d"
_MUT = "#6b665d"    # Codex P1: 읽는 작은 텍스트(모노 오버라인·미도달 단계 라벨) — 5.1:1↑
_LINE = "#e6e2da"
_LINE_SEC = "#e0dbd2"
_ACCENT = "#c2410c"
_ACCENT_TINT = "#fdf3ec"
_MONO = "'IBM Plex Mono', monospace"
# 상태 색 — 상세 진행 단계 pill·상태 배지·표 상태 열 색 규칙 공용. 조회 화면
# (near_miss_view)과 **같은 토큰**을 쓴다: 같은 상태가 화면마다 다른 색이면 안 된다.
_STATUS_COLOR = {
    "SUBMITTED": TOKENS["info"],       # #2f4d99
    "IN_REVIEW": TOKENS["gold"],       # #8a6212
    "EVALUATED": TOKENS["success"],    # #2f6b45
    "CLOSED": TOKENS["ink-3"],         # #6b665d
    "REJECTED": TOKENS["danger"],      # #9c3232
}
# 등급 색(S 가 가장 중대 → 옅어질수록 경미) — 조회 화면과 동일 매핑.
_GRADE_COLOR = {
    "S": TOKENS["danger"], "A": TOKENS["gold"], "B": TOKENS["warn"],
    "C": TOKENS["info"], "D": TOKENS["ink-3"],
}

# ── 표시 컬럼(조회 화면 9열에서 신고자·소속만 제외한 7열) ──
# 본인 전용 화면이라 신고자는 항상 본인이고 소속도 사실상 한 값이라, 두 열은 스캔에
# 기여하지 않으면서 좁은 폭만 잡아먹는다. 나머지 열의 구성·순서·서식은 조회와 같다.
_DISPLAY_COLUMNS = [
    # 상태를 발생일 뒤로 당김(2026-08-13, 코덱스 자문 합치): 본인 보고서 목록의 주 관심은
    # "내 보고서가 어느 단계인가"라, 모바일 첫 화면(스와이프 전)에 상태가 보여야 한다.
    # 조회 화면과는 이 한 칸만 순서가 다르다(컬럼 구성·서식은 동일).
    "보고번호", "작업명", "발생일", "상태", "제안등급", "확정등급", "원인",
]
# 컬럼 폭 — 원인을 뺀 나머지는 조회 화면 _COL_CONFIG 와 같은 값(작업명만 잔여 폭 흡수).
# 고정폭 합 + 작업명 minWidth 가 컨테이너보다 넓어지면 AgGrid 가 **표 안에서** 가로
# 스크롤한다(§5) — 페이지 가로 스크롤은 발생하지 않는다(390px 실측 0).
_COL_CONFIG = {
    "보고번호": {"width": 112, "cellStyle": {"fontFamily": "'IBM Plex Mono', monospace",
                                          "letterSpacing": "0.01em"}},
    "작업명": {"flex": 2, "minWidth": 150},
    "발생일": {"width": 104},
    "제안등급": {"width": 84},
    "확정등급": {"width": 84},
    "상태": {"width": 88},
    # 원인만 조회(92px)보다 넓다 — 이 화면의 원인 라벨(_CAUSE_LABEL)이 조회 화면보다 길어
    # ('미끄러짐·넘어짐' 8자 vs 조회 '미끄러짐' 4자) 92px 에서는 끝이 잘린다. 두 화면의
    # 원인 라벨 어휘 불일치 자체는 별건(보고 대상)이라 여기서 문구를 바꾸지 않고 폭을 맞춘다.
    "원인": {"width": 140},
}

_MINE_CSS = """
<style>
/* 상세 '내용 수정' 버튼 — 히트영역 34px (U8: 제출 취소 버튼 제거로 셀렉터 단일화) */
[class*="st-key-nm_my_editbtn_"] button {
  min-height:34px !important; border-radius:8px !important; font-size:13px !important; }
</style>
"""


def render(user: dict) -> None:
    # 제목 크롬만(아이콘 툴바 밴드 없음 §0-3) — 아이콘은 상단 52px 헤더에만.
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="내 아차사고",
        desc="본인이 등록한 아차사고와 처리 상태를 확인합니다.",
        breadcrumb="아차사고 › 내 아차사고",
        badges=scaffold.mode_badge(),
    )
    st.markdown(_MINE_CSS, unsafe_allow_html=True)

    emp_no = str(user.get("emp_no") or "").strip()
    if not emp_no:
        ui.empty_state("로그인 사번을 확인할 수 없어 내 아차사고를 표시할 수 없습니다.",
                       head="내 아차사고")
        return

    _readiness().banner()

    # 상태·기간 필터(§1-E) — 목록이 늘어도 원하는 건을 좁힐 수 있게. facade 파라미터
    # (reporter_emp_no+status+date_from/date_to)로 서버측 필터한다. 제출 버튼 없이 변경 즉시
    # 재조회(내 목록은 소규모라 반응형이 자연스럽다).
    filters, active = _collect_my_filters(emp_no)
    try:
        reports = db.get_near_miss_reports(filters)
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"내 아차사고 목록을 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("내 아차사고 목록을 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    if reports is None or reports.empty:
        if active:
            ui.empty_state("조건에 해당하는 내 아차사고가 없습니다. 상태·기간 필터를 조정해 보세요.",
                           head="내 아차사고")
        else:
            ui.empty_state("아직 등록한 아차사고가 없습니다. '아차사고 등록'에서 접수할 수 있습니다.",
                           head="내 아차사고")
        return

    # §0-4·분석 화면 표준 타일: 제목 바로 아래 내 보고 합계(현재 필터 결과 기준 파생).
    erp.metric_strip(_my_metrics(reports))
    _render_list(user, reports)


def _collect_my_filters(emp_no: str) -> tuple[dict, bool]:
    """§1-E 필터 줄(상태·기간)을 렌더하고 facade 조회조건 dict + 필터활성 여부를 만든다.

    범위는 위젯이 아니라 인증 세션 사번으로 고정(reporter_emp_no) — 상태/기간만 사용자가
    조정한다. 기본 기간은 '전체'(미지정=전 기간, date 생략). 제출 버튼 없이 변경 즉시 반영."""
    period_on = st.session_state.get(f"{_PAGE_ID}_period_mode") == "기간 지정"
    fields: list[erp.Field] = [
        erp.Field(key="status", label="상태", kind="select", width=160,
                  options=[workspace.ALL] + list(db.NEAR_MISS_STATUSES),
                  format_func=lambda v: _STATUS_LABEL.get(v, v) if v != workspace.ALL else v),
        erp.Field(key="period_mode", label="기간", kind="select", width=140,
                  options=["전체", "기간 지정"]),
    ]
    if period_on:
        fields += [
            erp.Field(key="from", label="발생일(시작)", kind="date",
                      value=date.today() - timedelta(days=90), width=150),
            erp.Field(key="to", label="발생일(종료)", kind="date",
                      value=date.today(), width=150),
        ]
    v = erp.condition_panel(_PAGE_ID, fields, cols=4)

    filters: dict = {"reporter_emp_no": emp_no}
    active = False
    if v["status"] != workspace.ALL:
        filters["status"] = v["status"]
        active = True
    if v["period_mode"] == "기간 지정":
        active = True
        if "from" in v:
            filters["date_from"] = v["from"].isoformat()
        if "to" in v:
            filters["date_to"] = v["to"].isoformat()
    return filters, active


def _my_metrics(reports: pd.DataFrame) -> list[tuple]:
    """내 아차사고 합계 타일(기존 status 파생) — 총·진행중·평가완료·종결·반려."""
    n = len(reports)
    codes = reports["status"].astype(str) if "status" in reports.columns else pd.Series(dtype=str)
    c = codes.value_counts().to_dict()
    in_progress = c.get("SUBMITTED", 0) + c.get("IN_REVIEW", 0)
    evaluated = c.get("EVALUATED", 0)
    closed_rej = c.get("CLOSED", 0) + c.get("REJECTED", 0)
    return [
        ("총 보고", n, "건", "TOTAL", n > 0),
        ("진행중", int(in_progress), "건", "IN PROGRESS", False),
        ("평가완료", int(evaluated), "건", "DONE", False),
        ("종결·반려", int(closed_rej), "건", "CLOSED", False),
    ]


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
            "아차사고 스키마가 아직 적용되지 않아 내 아차사고를 조회할 수 없습니다."
        )
    return ReadinessState.ready()


def _clean(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


# ---------- 컬럼형 표 + 전체폭 상세 ----------
def _to_display(reports: pd.DataFrame) -> pd.DataFrame:
    """표시 7열 프레임(+hidden 자연키). 서식은 조회 화면 ``_to_display`` 와 같은 규칙:
    보고번호/작업명 원문, 발생일 ISO 문자열, 등급은 코드 문자 그대로(빈 값 '-'),
    상태·원인은 한글 라벨. 여기서 라벨로 바꾼 문자열이 색 규칙의 키가 된다."""
    rows = []
    for _, r in reports.iterrows():
        status = _clean(r.get("status"))
        cause = _clean(r.get("cause_code"))
        rows.append({
            _KEY_FIELD: str(r.get("id")),
            "보고번호": _clean(r.get("report_no")) or "(번호 미상)",
            "작업명": _clean(r.get("work_name")) or "(제목 없음)",
            "발생일": _clean(r.get("incident_date")) or "-",
            "제안등급": _clean(r.get("proposed_grade")) or "-",
            "확정등급": _clean(r.get("confirmed_grade")) or "-",
            "상태": _STATUS_LABEL.get(status, status) or "-",
            "원인": _CAUSE_LABEL.get(cause, cause) or "-",
        })
    return pd.DataFrame(rows, columns=[_KEY_FIELD] + _DISPLAY_COLUMNS)


def _render_list(user: dict, reports: pd.DataFrame) -> None:
    """컬럼형 표(행 클릭 = 선택 = 상세 열기) + 선택 건 전체폭 상세.

    조회 화면과 같은 목록 어휘(``erp.select_grid``)를 쓰되 이 화면은 USER 소관이라 행 피치
    44px(터치 variant)이고, 상세 열기용 체크박스는 없다(§0-1 — 행 클릭이 곧 선택).
    선택은 위치가 아니라 자연키(보고서 id)로 오간다 — 정렬·필터가 바뀌어도 같은 건이 열린다.
    미선택이면 상세 영역 자체를 그리지 않는다(§8-2 '선택하세요' 빈 패널 금지)."""
    frame = reports.sort_values("incident_date", ascending=False, kind="stable")
    display = _to_display(frame)

    # stale 선택 해제 — 필터가 바뀌어 목록에서 사라진 건은 조용히 미선택으로 되돌린다.
    selected = st.session_state.get(_SEL_KEY)
    selected = str(selected) if selected is not None else None
    if selected is not None and selected not in set(display[_KEY_FIELD]):
        selected = None
        st.session_state.pop(_SEL_KEY, None)

    sheet_head("내 아차사고 목록", count=len(display))
    picked = erp.select_grid(
        display, key=f"{_PAGE_ID}_grid", key_field=_KEY_FIELD,
        columns=_DISPLAY_COLUMNS, selected_key=selected,
        col_config=_COL_CONFIG,
        checkbox_marker=False,      # §0-1: 행 클릭이 곧 선택(상세 열기용 체크박스 금지)
        row_height=44,              # USER·터치 variant(§4 44px) — lodging_my 와 동일 계약
        color_rules={
            "제안등급": _GRADE_COLOR,
            "확정등급": _GRADE_COLOR,
            "상태": {label: _STATUS_COLOR[code] for code, label in _STATUS_LABEL.items()},
        },
    )
    # 선택을 상세 렌더 **전에** 소비한다 — select_grid 의 selectionChanged rerun 이 이미 일어난
    # run 이므로 세션만 갱신하면 추가 st.rerun 없이 곧바로 상세를 그린다(선택 즉시 상세).
    if picked is not None and picked != selected:
        selected = picked
        st.session_state[_SEL_KEY] = picked
    if not selected:
        return

    match = frame[frame["id"].astype(str) == selected]
    if match.empty:                              # 방어적 — 위에서 이미 걸러진다.
        st.session_state.pop(_SEL_KEY, None)
        return
    report = match.iloc[0].to_dict()
    _render_detail(user, report, _clean(report.get("status")))


def _detail_anchor_html(report: dict, status: str) -> str:
    """상세 앵커 한 줄 — 보고번호(모노 16/600) + 상태 배지. 표 아래 상세가 **어느 건**인지
    고정한다(수정 안전: 잘못된 건을 고치지 않게). 배지는 공용 kit primitive 재사용."""
    report_no = _clean(report.get("report_no")) or "(번호 미상)"
    badge = erp.status_badge_html(
        _STATUS_LABEL.get(status, status or "-"),
        _STATUS_COLOR.get(status, TOKENS["ink-3"]),
    )
    return (
        "<div style='display:flex;flex-wrap:wrap;align-items:center;gap:10px;"
        "margin:10px 0 0;'>"
        f"<span style='font-family:{_MONO};font-size:16px;font-weight:600;"
        f"color:{_INK};'>{escape(report_no)}</span>{badge}</div>"
    )


# ---------- 전체폭 상세(상세 + 워크플로) ----------
def _render_detail(user: dict, report: dict, status: str) -> None:
    """선택 건 상세: 앵커(보고번호·상태) → 진행 단계 pill → 피드백 배너 → 본문 블록 → 수정.

    SUBMITTED 건은 보완요청(info) 배너를 호출하고, REJECTED 건은 반려(warn) 배너를 띄운다
    (별개 시각·문구). 선택은 _SEL_KEY 가 소유한다."""
    with st.container(border=False):
        st.markdown(_detail_anchor_html(report, status), unsafe_allow_html=True)
        st.markdown(_steps_html(status), unsafe_allow_html=True)

        # ── 피드백 배너 — 반려(warn)와 보완요청(info)은 별개 시각·문구를 유지한다. ──
        if status == "REJECTED" and _clean(report.get("rejection_reason")):
            banner("warn", f"반려 사유: {_clean(report.get('rejection_reason'))}")
        if status == "SUBMITTED":
            _render_revision_banner(report.get("id"))

        st.markdown(_detail_blocks_html(report), unsafe_allow_html=True)

        # ── 사진(읽기 그리드) + 소유자·SUBMITTED 첨부/삭제. ──
        _render_my_photos(report, status)

        # ── 워크플로(SUBMITTED 자기수정) — 소유자+제출됨에서만. ──
        _render_edit_entry(user, report, status)
        st.markdown(f"<div style='height:8px'></div>", unsafe_allow_html=True)


def _steps_html(status: str) -> str:
    """진행 단계 pill(제출→검토중→평가완료→종결). 현행 상태값 기준으로 도달 단계를 채운다.

    반려(REJECTED)는 분기 표현: 제출만 도달로 두고 마지막에 '반려' pill(danger)을 덧붙인다."""
    order = [("SUBMITTED", "제출"), ("IN_REVIEW", "검토중"),
             ("EVALUATED", "평가완료"), ("CLOSED", "종결")]
    codes = [c for c, _ in order]
    rejected = (status == "REJECTED")
    cur = codes.index(status) if status in codes else 0
    pills = []
    for i, (_code, lab) in enumerate(order):
        reached = (i == 0) if rejected else (i <= cur)
        if reached:
            dot, txt, bg, bd = _ACCENT, _INK, _ACCENT_TINT, "#f0dfd0"
        else:
            dot, txt, bg, bd = "#cfc8bd", _MUT, "transparent", _LINE
        pills.append(_step_pill(dot, txt, bg, bd, lab))
    if rejected:
        pills.append(_step_pill("#9c3232", "#9c3232", "#fbeeee", "#f0d9d9", "반려"))
    return (f"<div style='display:flex;flex-wrap:wrap;align-items:center;gap:6px;"
            f"margin:12px 0 16px;'>{''.join(pills)}</div>")


def _step_pill(dot: str, txt: str, bg: str, bd: str, label: str) -> str:
    return (
        f"<span style='display:inline-flex;align-items:center;gap:6px;padding:4px 11px;"
        f"border-radius:999px;border:1px solid {bd};background:{bg};font-size:12px;"
        f"font-weight:600;color:{txt};white-space:nowrap;'>"
        f"<span style='width:7px;height:7px;border-radius:50%;background:{dot};flex:0 0 auto;'></span>"
        f"{escape(label)}</span>"
    )


def _detail_blocks_html(report: dict) -> str:
    """펼친 영역 본문 블록(§1-B) — 좌측 2px 보더 + 모노 오버라인 + 라벨 + 본문 14.5px/1.7.

    상단에 제안등급·확정등급 메타를 한 줄로 덧붙인다(행 요약엔 없는 등급 컨텍스트)."""
    pg = _clean(report.get("proposed_grade")) or "없음"
    cg = _clean(report.get("confirmed_grade")) or "미정"
    meta = (
        f"<div style='display:flex;flex-wrap:wrap;gap:6px 20px;margin:0 0 14px;font-size:12.5px;color:{_INK2};'>"
        f"<span>제안등급 <b style='color:{_INK};'>{escape(pg)}</b></span>"
        f"<span>확정등급 <b style='color:{_INK};'>{escape(cg)}</b></span></div>"
    )
    cause = _clean(report.get("cause_code"))
    cause_detail = _clean(report.get("cause_detail"))
    cause_val = (_CAUSE_LABEL.get(cause, cause) or "") + (f" · {cause_detail}" if cause_detail else "")
    blocks = [
        ("WHAT", "사고내용", _clean(report.get("incident_content")), True),
        ("CAUSE", "발생원인", cause_val, False),
        ("ACTION", "예방대책", _clean(report.get("countermeasure")), True),
        ("TASK", "작업내용", _clean(report.get("work_content")), False),
    ]
    cells = []
    for tag, label, value, long in blocks:
        flex = "2 1 420px" if long else "1 1 260px"
        body = escape(value).strip() or "-"
        cells.append(
            f"<div style='flex:{flex};min-width:0;border-left:2px solid {_LINE_SEC};"
            "padding-left:14px;display:flex;flex-direction:column;gap:6px;'>"
            f"<span style='font-size:11px;letter-spacing:0.1em;color:{_MUT};font-family:{_MONO};'>{tag}</span>"
            f"<span style='font-size:12.5px;font-weight:600;color:{_INK2};'>{escape(label)}</span>"
            f"<p style='margin:0;font-size:14.5px;line-height:1.7;color:{_INK};text-wrap:pretty;"
            f"white-space:pre-wrap;'>{body}</p></div>"
        )
    return (meta + "<div style='display:flex;flex-wrap:wrap;gap:20px 32px;'>"
            + "".join(cells) + "</div>")


def _render_revision_banner(report_id) -> None:
    """제출됨 건에 걸린 보완요청(사유/요청자/시각)을 안내한다.

    반려(REJECTED) 배너는 ``warn``(경고), 보완요청은 ``info``(파랑)로 **별도 시각**을 준다
    — 반려는 종결분기, 보완요청은 재작성 요청이라 성격이 다르다. 007 미적용이면 facade 가
    None 을 돌려주므로 배너가 뜨지 않는다(정상 부재). 실제 조회 오류는 '보완요청 없음'으로
    조용히 삼키지 않고 danger 배너로 표면화한다(오류≠정상 부재)."""
    try:
        rev = db.get_near_miss_revision_request(report_id)
    except db.DATA_SOURCE_ERRORS as exc:
        banner("danger", f"보완요청을 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        banner("danger", "보완요청을 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return
    if not rev:
        return
    reason = _clean(rev.get("revision_request_reason"))
    if not reason:
        return
    requester = _clean(rev.get("revision_requested_by_emp_no"))
    at = _clean(rev.get("revision_requested_at"))
    meta = " / ".join(p for p in (requester, at) if p)
    banner("info", f"보완요청: {reason}" + (f" — 요청 {meta}" if meta else ""))


def _render_my_photos(report: dict, status: str) -> None:
    """첨부 사진 썸네일 그리드(읽기) + 소유자·SUBMITTED 첨부/삭제(라이브 db API).

    조회 화면과 달리 내 아차사고는 report_id 가 이미 있으므로 스테이징 없이 db API 를 직접
    호출한다(게이트: 소유자+SUBMITTED — 파사드가 세션 사용자로 서버측 재확인, 위조 방지).
    업로더/카메라·삭제는 st.form(수정 폼) 밖의 상시 상세 영역에 두어 즉시 반응한다."""
    rid = report.get("id")
    paths = normalize_photo_paths(report.get("photo_paths"))
    editable = (status == _EDITABLE_STATUS)
    if not paths and not editable:
        return

    # 이전 rerun 에서 stash 한 첨부/삭제 결과 문구를 표시(성공 썸네일은 재조회로 자동 반영).
    _flush_photo_msg(rid)

    st.markdown(
        f"<div style='font-family:{_MONO};font-size:11px;letter-spacing:0.12em;"
        f"color:{_INK2};margin:16px 0 8px;'>사진 · {len(paths)}</div>",
        unsafe_allow_html=True,
    )
    if paths:
        # U5 공용 헬퍼 — 소유자+SUBMITTED 면 각 셀에 삭제 버튼(delete_cb), 아니면 읽기 전용.
        render_photo_thumbs(
            paths, key_prefix=f"nm_my_photo_{rid}",
            delete_cb=(lambda p: _delete_my_photo(rid, p)) if editable else None,
        )

    if not editable:
        return
    if len(paths) >= photo_storage.MAX_PHOTOS:
        st.caption(f"사진은 최대 {photo_storage.MAX_PHOTOS}장까지 첨부할 수 있습니다.")
        return

    seen = st.session_state.setdefault(f"nm_my_photoseen_{rid}", set())
    ups = st.file_uploader(
        "사진 추가", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True,
        key=f"nm_my_photoup_{rid}", label_visibility="collapsed",
        max_upload_size=_MAX_UPLOAD_MB,  # 위젯 단위 상한(MB) — 서버 config 와 병행 차단.
        help=f"JPG·PNG·WEBP · 최대 {photo_storage.MAX_PHOTOS}장 · 원본 {_MAX_UPLOAD_MB}MB 이하",
    )
    new_files = [f for f in (ups or []) if (getattr(f, "file_id", None) or f.name) not in seen]
    with st.expander("사진 촬영 (카메라)", expanded=False):
        cam = st.camera_input("사진 촬영", key=f"nm_my_photocam_{rid}", label_visibility="collapsed")
    cam_new = cam if (cam is not None and getattr(cam, "file_id", None)
                      and cam.file_id not in seen) else None
    if new_files or cam_new is not None:
        _add_my_photos(rid, new_files, cam_new, seen)


def _add_my_photos(report_id, files: list, cam, seen: set) -> None:
    """선택/촬영 사진을 db API 로 첨부한다(소유자+SUBMITTED 게이트는 파사드 재확인). 결과 후 rerun."""
    current_user = auth.get_current_user()
    errors: list[str] = []
    for f in files:
        seen.add(getattr(f, "file_id", None) or f.name)
        name = f.name or "사진.jpg"
        # 원본 크기 사전 검사(getvalue 전 — 대용량은 메모리 적재 전에 차단).
        size = getattr(f, "size", None)
        if isinstance(size, int) and size > _MAX_UPLOAD_BYTES:
            errors.append(f"{name}: 이미지 용량이 너무 큽니다. 최대 {_MAX_UPLOAD_MB}MB 까지 첨부할 수 있습니다.")
            continue
        try:
            db.upload_near_miss_photo(report_id, f.getvalue(), name, current_user=current_user)
        except ValueError as exc:
            errors.append(f"{name}: {exc}")
        except Exception:  # noqa: BLE001 — 저장 백엔드 오류(원문 비노출).
            errors.append(f"{name}: 첨부하지 못했습니다.")
    if cam is not None:
        seen.add(getattr(cam, "file_id", None))
        cam_size = getattr(cam, "size", None)
        if isinstance(cam_size, int) and cam_size > _MAX_UPLOAD_BYTES:
            errors.append(f"촬영사진: 이미지 용량이 너무 큽니다. 최대 {_MAX_UPLOAD_MB}MB 까지 첨부할 수 있습니다.")
        else:
            try:
                db.upload_near_miss_photo(report_id, cam.getvalue(), "촬영사진.jpg",
                                          current_user=current_user)
            except ValueError as exc:
                errors.append(f"촬영사진: {exc}")
            except Exception:  # noqa: BLE001
                errors.append("촬영사진: 첨부하지 못했습니다.")
    if errors:
        _stash_photo_msg(report_id, "warn", "일부 사진을 첨부하지 못했습니다: " + " / ".join(errors))
    st.rerun()


def _delete_my_photo(report_id, path: str) -> None:
    """첨부 사진 1장을 삭제한다(소유자+SUBMITTED 게이트는 파사드 재확인). 결과 후 rerun.

    파사드 반환의 ``storage_deleted``(P1-4)가 False 면 참조는 제거됐으나 저장소 파일 정리가
    지연됐다는 뜻이므로 부분성공으로 표면화한다(성공 위장 금지)."""
    try:
        res = db.delete_near_miss_photo(report_id, path, current_user=auth.get_current_user())
    except ValueError as exc:
        _stash_photo_msg(report_id, "danger", f"사진을 삭제하지 못했습니다 — {exc}")
        st.rerun()
        return
    except Exception:  # noqa: BLE001 — 저장 백엔드 오류(원문 비노출).
        _stash_photo_msg(report_id, "danger", "사진 삭제 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.")
        st.rerun()
        return
    if isinstance(res, dict) and res.get("storage_deleted") is False:
        _stash_photo_msg(report_id, "warn",
                         "사진 참조는 제거됐으나 저장소 파일 정리가 지연될 수 있습니다(자동 정리 예정).")
    st.rerun()


def _stash_photo_msg(report_id, kind: str, text: str) -> None:
    """rerun 을 넘겨 다음 렌더에서 표시할 사진 처리 결과 문구를 세션에 보관한다."""
    st.session_state[f"nm_my_photomsg_{report_id}"] = (kind, text)


def _flush_photo_msg(report_id) -> None:
    """stash 한 사진 처리 결과 문구를 한 번 표시하고 소비한다."""
    msg = st.session_state.pop(f"nm_my_photomsg_{report_id}", None)
    if msg:
        banner(msg[0], msg[1])


def _render_edit_entry(user: dict, report: dict, status: str) -> None:
    """SUBMITTED 상태에서만 본문 수정 진입을 노출한다(소유자 검증은 facade 소관). 제출 취소는 범위 밖."""
    if status != _EDITABLE_STATUS:
        st.caption("제출됨 상태에서만 내용을 수정할 수 있습니다.")
        return
    if not hasattr(db, "update_near_miss_report"):
        banner("info", "수정 기능은 통합 대기 중입니다(update_near_miss_report 파사드 연결 후 활성화).")
        return

    rid = str(report.get("id"))
    edit_key = f"nm_my_edit_open_{rid}"
    # U8: '제출 취소' 자리표시자(항상 비활성) 버튼을 제거한다 — 상시 비활성 버튼은 거짓 어포던스다.
    # 제출 취소 계약(SUBMITTED 회수→DRAFT/삭제 등 상태전이·권한·감사)이 확정되면 그때 파사드
    # (예: withdraw_near_miss_report)와 함께 실 배선한다(현재는 계약 미확정이라 UI 미노출).
    if st.button("내용 수정", key=f"nm_my_editbtn_{rid}", type="secondary"):
        st.session_state[edit_key] = not bool(st.session_state.get(edit_key, False))
        st.rerun()
    if st.session_state.get(edit_key):
        _render_edit_form(user, report)


def _render_edit_form(user: dict, report: dict) -> None:
    rid = report.get("id")
    with st.form(f"nm_my_edit_{rid}", clear_on_submit=False):
        work_name = st.text_input("작업명", value=_clean(report.get("work_name")), max_chars=120)
        c1, c2 = st.columns(2)
        with c1:
            inc = _clean(report.get("incident_date"))
            try:
                inc_val = date.fromisoformat(inc) if inc else date.today()
            except ValueError:
                inc_val = date.today()
            incident_date = st.date_input("발생일", value=inc_val, format="YYYY-MM-DD")
        with c2:
            cause_opts = list(db.NEAR_MISS_CAUSE_CODES)
            cur_cause = _clean(report.get("cause_code"))
            c_idx = cause_opts.index(cur_cause) if cur_cause in cause_opts else 0
            cause_code = st.selectbox(
                "발생원인", cause_opts, index=c_idx, width=200,
                format_func=lambda c: f"{_CAUSE_LABEL.get(c, c)} ({c})",
            )
        cause_detail = st.text_input("발생원인 상세", value=_clean(report.get("cause_detail")),
                                     max_chars=200)
        work_content = st.text_area("작업내용", value=_clean(report.get("work_content")), height=80)
        incident_content = st.text_area("사고내용", value=_clean(report.get("incident_content")),
                                        height=100)
        countermeasure = st.text_area("예방대책", value=_clean(report.get("countermeasure")),
                                      height=80)
        site_description = st.text_area("작업현장 상황설명",
                                        value=_clean(report.get("site_description")), height=80)
        saved = erp.form_submit("수정 저장")

    if not saved:
        return

    payload = {
        "work_name": work_name,
        # 제안 등급은 폼에서 제거했으나 기존 저장값을 그대로 실어 보존한다(수정으로 미변경).
        "proposed_grade": _clean(report.get("proposed_grade")) or None,
        "cause_code": cause_code,
        "cause_detail": cause_detail,
        "incident_date": incident_date.isoformat(),
        "work_content": work_content,
        "incident_content": incident_content,
        "countermeasure": countermeasure,
        "site_description": site_description,
        # photo_paths 는 본문 수정 payload 에 싣지 않는다(P1-3): 사진 첨부/삭제는 전용 API
        # (db.upload/delete_near_miss_photo)만 photo_paths 를 변경하며, 본문 수정 경로가 이를
        # 함께 보내면 두 경로가 사진 배열을 이중 소유하게 된다. 파사드도 본문 수정에서
        # photo_paths 를 무시하도록 정합되므로 view 도 아예 보내지 않는다.
    }
    _save_edit(rid, payload)


def _save_edit(report_id, payload: dict) -> None:
    """세션 사용자로 본문 수정을 시도한다(파사드가 소유자·SUBMITTED 를 서버측 재확인).

    도메인 검증 오류(ValueError)는 사용자 안전 문구이므로 그대로 노출하고, 그 외 예외는
    원문(raw)을 감춰 일반 안내로 접는다."""
    try:
        db.update_near_miss_report(report_id, payload, current_user=auth.get_current_user())
    except ValueError as exc:
        banner("danger", f"수정하지 못했습니다 — {exc}")
        return
    except db.DATA_SOURCE_ERRORS as exc:
        banner("danger", f"수정 중 오류가 발생했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        banner("danger", "수정 중 오류가 발생했습니다. 목록을 재조회한 뒤 다시 시도하세요.")
        return
    banner("success", "아차사고 내용을 수정했습니다.")
    st.rerun()
