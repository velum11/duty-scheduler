"""아차사고 평가 관리 — 큐 처리형(DESIGN.md §1-A).

신판 DESIGN.md §1-A "큐 처리형" 골격을 그대로 구현한다(색 리스킨이 아니라 구조 교체):

    제목/설명 → [지표 스트립] → 헤어라인 → [큐 칩 스트립] → 헤어라인
    → [선택 건 전체폭 상세] → 헤어라인 → [하단 액션 바]

- 좌우 분할·행 체크박스·"케이스를 선택하세요" 빈 패널을 쓰지 않는다(§0 금지 1·2).
- 진입 시 큐의 첫 건이 자동 선택된다. 칩 클릭 = 선택(오렌지 칩), 이전/다음으로 순회.
- 본문에 빈 아이콘 툴바 띠를 넣지 않는다(§0 금지 3) — 아이콘은 상단 52px 헤더에만.
- 카드(테두리+radius+그림자) 금지(§0 금지 5) — 구획은 헤어라인 + 여백만.
- 색·크기·간격은 §2~§4 값만 사용(§0 금지 8, 새 색 없음).

레퍼런스 골격: ``아차사고 관리.dc.html`` isEval 블록(509~583).

기능 계약(불변 — 표현 계층만 교체):
  - 권한 게이트 ``auth.can_evaluate_near_miss(user)``.
  - 상태 전이 4종: 검토착수(SUBMITTED→IN_REVIEW) · 평가확정(evaluate_near_miss) ·
    보완요청(IN_REVIEW→SUBMITTED, request_near_miss_revision) · 반려(→REJECTED).
    반려·보완요청은 '의견' 필수(dc 와 동일한 단일 의견 입력 — 반려는 rejection_reason,
    보완요청은 사유로 재사용). 신원은 서버측(current_user=auth.get_current_user())으로 확정.
  - 등급 세그먼트 값은 ``db.NEAR_MISS_GRADES`` 도메인 소스에서 파생(하드코딩 없음).
  - 모든 파사드 호출은 ``modules/db.py`` 만 사용(repository 직접 호출 없음). stale 충돌은
    파사드 원문 메시지를 배너로 그대로 노출(가공 금지).
"""
# DESIGN.md §1-A 큐 처리형 — 읽기 큐(칩) + 전체폭 상세/워크플로.
SCREEN_ARCHETYPE = "MASTER_DETAIL"

from html import escape

import pandas as pd
import streamlit as st

from modules import auth, db
from views.common import erp, scaffold
from views.common.photo_paths import normalize_photo_paths
from views.common.photos import render_photo_thumbs
from views.master import (
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

_STATUS_LABEL = {
    "SUBMITTED": "제출됨",
    "IN_REVIEW": "검토중",
    "EVALUATED": "평가완료",
    "REJECTED": "반려",
    "CLOSED": "종결",
}
# 발생원인 코드→한글 라벨(§3.1: 분류축=평문, 색 없음). near_miss_stats 와 동일.
_CAUSE_LABEL = {
    "JAM": "끼임", "FALL": "추락", "DROP": "낙하", "HIT": "충돌",
    "SLIP": "미끄러짐", "BURN": "화상", "PINCH": "협착", "ETC": "기타",
}

_NOT_READY_MSG = (
    "아차사고 스키마가 준비되지 않아 평가를 진행할 수 없습니다(조회만 가능). "
    "스키마를 적용한 뒤 다시 시도하세요."
)
_PROBE_ERROR_MSG = (
    "아차사고 스키마 상태 확인 실패 — 재확인이 필요합니다(확인 전까지 평가는 차단됩니다)."
)
_STALE_MARK = "이미 변경"  # db._NEAR_MISS_STALE_MESSAGE 원문 일부 — kind 분기(warning vs error).

_SEL_KEY = "nm_eval_selected_id"       # 상세에 열린 보고서 id(문자열)
_OP_KEY = "nm_eval_opinion_"           # 평가 의견(반려·보완요청 공용) prefix + id
_GRADE_KEY = "nm_eval_grade_"          # 확정 등급 선택 prefix + id
_EVAL_ACTIVE_KEY = "nm_eval_active_id"  # 직전 렌더의 활성 케이스 id(케이스 전환 시 등급 선택 초기화)

# ── §2 팔레트 (팔레트 밖 색 금지 §0-8) — 리터럴로 고정해 새 색 유입을 원천 차단한다. ──
_INK = "#1c1a17"          # 본문
_INK2 = "#4a453d"         # 보조(섹션 라벨)
# Codex P1: 이 파일의 _WEAK/_FAINT 는 모두 읽는 작은 텍스트(라벨·단위·모노 오버라인·메타)에
# 쓰이므로 #6b665d(5.1:1↑)로 상향한다 — #8b857c(3.27:1)·#a09a90(2.5:1)은 읽는 텍스트 금지.
_WEAK = "#6b665d"         # 읽는 보조 텍스트(구 #8b857c)
_FAINT = "#6b665d"        # 읽는 캡션·모노 오버라인(구 #a09a90)
_LINE = "#e6e2da"         # 행 헤어라인
_LINE_HDR = "#cfc8bd"     # 표 헤더 헤어라인
_LINE_SEC = "#e0dbd2"     # 섹션 헤어라인
_ACCENT = "#c2410c"
_ACCENT_TEXT = "#b4451a"
_ACCENT_TINT = "#fdf3ec"
_MONO = "'IBM Plex Mono', monospace"

# 화면 스코프 CSS(칩·세그먼트·나브·의견 입력) — 선택 상태는 색+형태 이중부호화(오렌지 배경
# +굵기). 히트영역 ≥32px. primary=선택/CTA 는 전역 오렌지 액센트(modules/ui.py) 재사용.
_EVAL_CSS = f"""
<style>
/* 큐 칩(선택=primary 오렌지, 비선택=secondary 흰+테두리) — pill, 히트영역 32px */
[class*="st-key-nmq_"] button {{
  border-radius:999px !important; min-height:32px !important; height:auto !important;
  padding:5px 14px !important; font-size:12.5px !important; font-weight:600 !important;
  white-space:nowrap !important; line-height:1.2 !important;
}}
/* 등급 세그먼트(선택=primary 오렌지) — 모노 코드, radius 7, 히트영역 32px */
[class*="st-key-nmg_"] button {{
  border-radius:7px !important; min-width:44px !important; min-height:34px !important;
  padding:6px 12px !important; font-family:{_MONO} !important; font-size:14px !important;
  font-weight:600 !important;
}}
/* 이전/다음 나브 — 32x32 정사각 */
.st-key-nm_qprev button, .st-key-nm_qnext button {{
  min-width:32px !important; width:32px !important; min-height:32px !important; height:32px !important;
  padding:0 !important; border-radius:7px !important; font-size:14px !important;
}}
/* 액션 버튼(검토착수/보완요청/반려/평가확정) — 히트영역 34px */
[class*="st-key-nm_act_"] button {{
  min-height:34px !important; border-radius:8px !important; font-size:13px !important;
  font-weight:600 !important; white-space:nowrap !important;
}}
/* 세그먼트 인라인 라벨 */
.nm-seg-label {{ font-size:12.5px; font-weight:500; color:{_INK2}; white-space:nowrap; }}
.nm-qhead {{ display:flex; align-items:center; gap:8px; margin:2px 0 6px; }}
.nm-qhead .t {{ font-size:14px; font-weight:600; color:{_INK}; }}
.nm-qhead .c {{ font-family:{_MONO}; font-size:11px; font-weight:600; padding:2px 8px;
  border-radius:999px; background:{_ACCENT_TINT}; color:{_ACCENT_TEXT}; }}
.nm-qpos {{ font-family:{_MONO}; font-size:11.5px; color:{_FAINT}; white-space:nowrap; }}
</style>
"""


# ---------- 진입 ----------
def render(user: dict) -> None:
    # 제목 크롬만(아이콘 툴바 밴드 없음 §0-3) — 아이콘은 상단 52px 헤더에만.
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="평가 관리",
        desc="등록된 아차사고를 검토해 등급을 확정하거나 반려합니다.",
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
    state = db.near_miss_schema_probe()
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
        if st.button("스키마 재확인", key="nm_eval__recheck", icon=":material/refresh:"):
            db.near_miss_schema_probe(force=True)
            st.rerun()

    try:
        reports = _load_pending_reports()
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"평가 대기 목록을 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("평가 대기 목록을 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    # ── 지표 스트립(제목 바로 아래 첫 블록 §0-4) — 좌측 2px 보더 + 26px 모노 숫자 ──
    subm = inrev = 0
    if reports is not None and not reports.empty:
        counts = reports["status"].astype(str).value_counts()
        subm = int(counts.get("SUBMITTED", 0))
        inrev = int(counts.get("IN_REVIEW", 0))
    total = subm + inrev
    st.markdown(_metric_strip_html([
        ("평가 대기", subm, "건", "SUBMITTED", True),
        ("검토중", inrev, "건", "IN REVIEW", False),
        ("대기 합계", total, "건", "PENDING", False),
    ]), unsafe_allow_html=True)
    _hairline()

    ordered = _ordered_ids(reports)
    if not ordered:
        st.markdown(
            f"<div style='padding:22px 0;font-size:14.5px;color:{_INK2};'>"
            "현재 평가 대기 중인 아차사고가 없습니다.</div>",
            unsafe_allow_html=True,
        )
        return

    # 진입 시 첫 건 자동 선택(§1-A) — 선택이 없거나 큐에서 사라진 경우.
    selected_id = st.session_state.get(_SEL_KEY)
    if selected_id not in ordered:
        selected_id = ordered[0]
        st.session_state[_SEL_KEY] = selected_id

    reports_by_id = {str(r["id"]): r for _, r in reports.iterrows()}
    _render_queue_chips(ordered, reports_by_id, selected_id)
    _hairline()
    _render_detail(user, readiness, selected_id)


# ---------- 데이터 ----------
def _load_pending_reports() -> pd.DataFrame:
    """활성 아차사고 중 평가 대기(SUBMITTED/IN_REVIEW)만. 단일 status 필터만 지원하는
    파사드 계약이라 두 상태는 여기서 클라이언트 측으로 골라낸다."""
    df = db.get_near_miss_reports({})
    if df is None or df.empty:
        return df
    mask = df["status"].astype(str).isin(_PENDING_STATUSES)
    return df[mask].reset_index(drop=True)


def _ordered_ids(df: pd.DataFrame) -> list[str]:
    if df is None or df.empty:
        return []
    frame = df.sort_values("incident_date", ascending=False, kind="stable")
    return [str(v) for v in frame["id"].tolist()]


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


# ---------- 지표 스트립 ----------
def _metric_strip_html(items) -> str:
    """지표 스트립 HTML(§1-A) — 좌측 2px 보더 + 26px 모노 숫자. items=[(label,value,unit,note,accent)]."""
    cells = []
    for label, value, unit, _note, accent in items:  # _note(영문 오버라인) 미렌더 — 2줄 타일
        border = _ACCENT if accent else _LINE_SEC
        valcolor = _ACCENT_TEXT if accent else _INK
        cells.append(
            f"<div style='flex:1 1 150px;min-width:0;display:flex;flex-direction:column;gap:5px;"
            f"padding:0 18px;border-left:2px solid {border};'>"
            f"<span style='font-size:12px;color:{_WEAK};'>{escape(label)}</span>"
            f"<div style='display:flex;align-items:baseline;gap:4px;'>"
            f"<span style='font-family:{_MONO};font-size:26px;font-weight:600;letter-spacing:-0.03em;"
            f"color:{valcolor};'>{int(value)}</span>"
            f"<span style='font-size:11.5px;color:{_FAINT};'>{escape(unit)}</span></div></div>"
        )
    return (
        f"<div style='display:flex;flex-wrap:wrap;gap:12px;padding:2px 0 14px;'>{''.join(cells)}</div>"
    )


def _hairline() -> None:
    st.markdown(
        f"<div style='border-top:1px solid {_LINE_SEC};margin:2px 0 10px;'></div>",
        unsafe_allow_html=True,
    )


# ---------- 큐 칩 스트립 ----------
def _render_queue_chips(ordered: list[str], reports_by_id: dict, selected_id: str) -> None:
    """평가 대기 큐를 칩 스트립으로 렌더(§1-A·§7: st.button 반복 + session_state.sel).

    선택 칩 = 오렌지(primary), 나머지 = 흰+테두리(secondary). 우측에 [n/m] + 이전/다음."""
    idx = ordered.index(selected_id)
    st.markdown(
        f"<div class='nm-qhead'><span class='t'>평가 대기 큐</span>"
        f"<span class='c'>{len(ordered)}</span></div>",
        unsafe_allow_html=True,
    )
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        for rid in ordered:
            r = reports_by_id.get(rid, {})
            short = str(r.get("report_no") or rid)[-8:]
            title = str(r.get("work_name") or "(제목 없음)")
            if len(title) > 22:
                title = title[:21] + "…"
            picked = st.button(
                f"{short} · {title}",
                key=f"nmq_{rid}",
                type="primary" if rid == selected_id else "secondary",
            )
            if picked and rid != selected_id:
                st.session_state[_SEL_KEY] = rid
                st.rerun()
        # 우측: 위치 + 이전/다음
        st.markdown(f"<span class='nm-qpos'>{idx + 1}/{len(ordered)}</span>",
                    unsafe_allow_html=True)
        if st.button("‹", key="nm_qprev", help="이전 건",
                     disabled=idx <= 0, type="secondary"):
            st.session_state[_SEL_KEY] = ordered[idx - 1]
            st.rerun()
        if st.button("›", key="nm_qnext", help="다음 건",
                     disabled=idx >= len(ordered) - 1, type="secondary"):
            st.session_state[_SEL_KEY] = ordered[idx + 1]
            st.rerun()


# ---------- 전체폭 상세 + 액션 바 ----------
def _detail_read_html(report: dict, status: str) -> str:
    """선택 건 전체폭 상세(§1-A) — 보고번호+상태 배지 / 제목 / 우측 메타 / 본문 블록.

    본문 블록 WHAT·TASK·SITE·CAUSE·ACTION = 좌측 2px 보더 + 모노 오버라인 + 라벨 + 본문
    14.5px/1.7. 긴 항목 flex:2 1 420px, 짧은 항목 flex:1 1 260px(2열로 자연 채움)."""
    report_no = escape(str(report.get("report_no") or "-"))
    badge = lifecycle_badge_html(status, _STATUS_LABEL.get(status, status))
    title = escape(str(report.get("work_name") or "(제목 없음)"))

    proposed = str(report.get("proposed_grade") or "").strip() or "미지정"
    meta = [
        ("발생일", str(report.get("incident_date") or "-")),
        ("신고자", _reporter_label(report.get("reporter_emp_no"))),
        ("부서", str(report.get("dept_code") or "-")),
        ("제안등급", proposed),
    ]
    meta_cells = "".join(
        f"<div style='display:flex;flex-direction:column;gap:3px;'>"
        f"<span style='font-size:10.5px;letter-spacing:0.08em;color:{_FAINT};font-family:{_MONO};'>"
        f"{escape(label)}</span>"
        f"<span style='font-size:13.5px;color:{_INK};'>{escape(str(value))}</span></div>"
        for label, value in meta
    )
    head = (
        "<div style='padding:4px 0 18px;display:flex;flex-wrap:wrap;align-items:flex-start;"
        "justify-content:space-between;gap:14px 20px;'>"
        "<div style='display:flex;flex-direction:column;gap:7px;min-width:0;'>"
        "<div style='display:flex;align-items:center;gap:10px;flex-wrap:wrap;'>"
        f"<span style='font-family:{_MONO};font-size:18px;font-weight:600;color:{_INK};'>{report_no}</span>"
        f"{badge}</div>"
        f"<span style='font-size:17px;color:{_INK};font-weight:600;letter-spacing:-0.02em;'>{title}</span>"
        "</div>"
        f"<div style='display:flex;flex-wrap:wrap;gap:12px 26px;'>{meta_cells}</div>"
        "</div>"
    )

    cause = str(report.get("cause_code") or "")
    cause_detail = str(report.get("cause_detail") or "")
    cause_val = _CAUSE_LABEL.get(cause, cause) + (f" · {cause_detail}" if cause_detail else "")
    blocks = [
        ("WHAT", "사고 내용", str(report.get("incident_content") or ""), True),
        ("TASK", "작업 내용", str(report.get("work_content") or ""), False),
        ("SITE", "현장 설명", str(report.get("site_description") or ""), False),
        ("CAUSE", "원인", cause_val, False),
        ("ACTION", "대책", str(report.get("countermeasure") or ""), True),
    ]
    block_cells = []
    for tag, label, value, long in blocks:
        flex = "2 1 420px" if long else "1 1 260px"
        body = escape(value).strip() or "-"
        block_cells.append(
            f"<div style='flex:{flex};min-width:0;border-left:2px solid {_LINE_SEC};"
            "padding-left:14px;display:flex;flex-direction:column;gap:6px;'>"
            f"<span style='font-size:11px;letter-spacing:0.1em;color:{_FAINT};font-family:{_MONO};'>{tag}</span>"
            f"<span style='font-size:12.5px;font-weight:600;color:{_INK2};'>{escape(label)}</span>"
            f"<p style='margin:0;font-size:14.5px;line-height:1.7;color:{_INK};text-wrap:pretty;"
            f"white-space:pre-wrap;'>{body}</p></div>"
        )
    body_blocks = (
        "<div style='padding:22px 0 22px;border-top:1px solid "
        f"{_LINE_SEC};display:flex;flex-wrap:wrap;gap:22px 32px;'>{''.join(block_cells)}</div>"
    )
    return head + body_blocks


def _render_detail(user: dict, readiness: ReadinessState, selected_id) -> None:
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
        st.markdown(
            f"<div style='padding:22px 0;font-size:14.5px;color:{_INK2};'>"
            "이 케이스는 더 이상 대기 중이 아닙니다. 다른 사용자가 먼저 처리했을 수 있습니다 — "
            "새로고침한 뒤 다시 선택하세요.</div>",
            unsafe_allow_html=True,
        )
        return

    # ── 전체폭 상세(읽기 HTML) ──
    st.markdown(_detail_read_html(report, status), unsafe_allow_html=True)

    # ── 하단 액션 바(§1-A): 등급 세그먼트 S~D | 의견 입력 | 검토착수 보완요청 반려 [평가확정] ──
    st.markdown(
        f"<div style='border-top:1px solid {_LINE_SEC};margin:2px 0 12px;'></div>",
        unsafe_allow_html=True,
    )
    grades = list(db.NEAR_MISS_GRADES)  # 도메인 소스 파생(하드코딩 금지)
    grade_key = f"{_GRADE_KEY}{selected_id}"
    # 큐 이동/재진입 시 이전 등급 선택을 초기화한다(직전 렌더의 활성 케이스와 다르면 fresh 진입).
    # 같은 케이스 내 등급 버튼 상호작용(동일 id rerun)에서는 초기화하지 않아 선택이 유지된다.
    if st.session_state.get(_EVAL_ACTIVE_KEY) != selected_id:
        st.session_state[_EVAL_ACTIVE_KEY] = selected_id
        st.session_state.pop(grade_key, None)
    # 확정 등급 기본은 **미선택**(S 자동 선택 제거) — 평가자가 명시적으로 고르게 한다.
    cur_grade = st.session_state.get(grade_key)
    if cur_grade not in grades:
        cur_grade = ""
        st.session_state[grade_key] = ""
    grade_selected = cur_grade in grades

    can_write = readiness.write_enabled
    op_key = f"{_OP_KEY}{selected_id}"
    opinion = str(st.session_state.get(op_key, "") or "").strip()

    # 활성 게이트(불변 계약 보존)
    review_disabled = (not can_write) or status != "SUBMITTED"
    review_help = (
        readiness.message if not can_write
        else ("이미 검토에 착수한 케이스입니다." if status != "SUBMITTED" else None)
    )
    # 평가확정: 확정 등급 미선택이면 비활성(+안내). 검토착수·보완요청·반려는 등급 무관(현행 유지).
    eval_disabled = (not can_write) or (not grade_selected)
    if not can_write:
        eval_help = readiness.message
    elif not grade_selected:
        eval_help = "등급을 선택하세요."
    else:
        eval_help = None
    # 보완요청(IN_REVIEW→SUBMITTED): 검토중 케이스만, 의견 필수. 반려와 별개 의미.
    revision_disabled = (not can_write) or status != "IN_REVIEW" or not opinion
    if not can_write:
        revision_help = readiness.message
    elif status != "IN_REVIEW":
        revision_help = "검토중(IN_REVIEW) 케이스만 보완요청할 수 있습니다."
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

    # 등급 세그먼트 — 확정 등급 라벨 + S~D 버튼(선택=오렌지 primary).
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        st.markdown("<span class='nm-seg-label'>확정 등급</span>", unsafe_allow_html=True)
        for g in grades:
            hit = st.button(g, key=f"nmg_{g}_{selected_id}",
                            type="primary" if g == cur_grade else "secondary")
            if hit and g != cur_grade:
                st.session_state[grade_key] = g
                st.rerun()

    # 의견 입력(flex:1) + 액션 버튼 — 반려·보완요청 공용 단일 의견(dc 정본).
    with st.container(horizontal=True, gap="small", vertical_alignment="bottom"):
        st.text_input(
            "평가 의견 · 반려·보완요청 시 필수",
            key=op_key, width="stretch", disabled=not can_write,
            placeholder="검토 의견을 한 줄로",
        )
        review = st.button("검토착수", key=f"nm_act_review_{selected_id}",
                           disabled=review_disabled, help=review_help, type="secondary")
        revision = st.button("보완요청", key=f"nm_act_revision_{selected_id}",
                             disabled=revision_disabled, help=revision_help, type="secondary")
        reject = st.button("반려", key=f"nm_act_reject_{selected_id}",
                           disabled=reject_disabled, help=reject_help, type="secondary")
        evaluate = st.button("평가확정", key=f"nm_act_eval_{selected_id}",
                             disabled=eval_disabled, help=eval_help, type="primary")

    # ── 참조성 첨부(사진) — U5: 자리표시자 제거, 서명 URL 썸네일 뷰어 실구현(읽기 전용). ──
    photos = normalize_photo_paths(report.get("photo_paths"))
    with st.expander(f"첨부 사진 ({len(photos)}건)", expanded=bool(photos)):
        if photos:
            render_photo_thumbs(photos, key_prefix=f"nmeval_thumb_{selected_id}")
        else:
            st.caption("첨부된 사진이 없습니다.")

    grade = st.session_state.get(grade_key, cur_grade)
    if review:
        _run_action(user, "검토착수", lambda: db.update_near_miss_status(
            selected_id, "IN_REVIEW", current_user=auth.get_current_user(),
        ))
    if evaluate:
        _run_action(user, "평가확정", lambda: db.evaluate_near_miss(
            selected_id, grade, current_user=auth.get_current_user(),
        ))
    if revision:
        # 보완요청: IN_REVIEW→SUBMITTED 반송 + 의견을 사유로 서버기록(반려와 별개 의미).
        _run_action(user, "보완요청", lambda: db.request_near_miss_revision(
            selected_id, opinion, current_user=auth.get_current_user(),
        ))
    if reject:
        _run_action(user, "반려", lambda: db.update_near_miss_status(
            selected_id, "REJECTED", rejection_reason=opinion,
            current_user=auth.get_current_user(),
        ))


def _flash_kind_for(exc: Exception) -> str:
    """stale 충돌(다른 평가자가 먼저 처리)은 warning, 그 외 검증 실패는 error."""
    return "warning" if _STALE_MARK in str(exc) else "error"


def _run_action(user: dict, label: str, call) -> None:
    """평가/반려 공통 실행 — 예외를 흡수해 raw traceback 을 노출하지 않는다
    (2단계 배너: 제목 + 파사드 원문 사유, stale 메시지는 가공 없이 그대로)."""
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
    st.session_state.pop(_SEL_KEY, None)  # 처리된 케이스는 큐에서 빠지므로 상세를 닫는다.
    st.rerun()
