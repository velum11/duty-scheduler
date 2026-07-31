"""개선조치 관리 — 큐 처리형(DESIGN.md §1-A 변형) + CAPA 폐루프.

신판 DESIGN.md §1-A "큐 처리형" 골격으로 구현한다(색 리스킨이 아니라 구조 교체):

    제목/설명 → [KPI 스트립 4종] → 헤어라인 → [종결 대기 큐 칩 스트립]
    → 헤어라인 → [선택 건 전체폭 상세 + CAPA 워크플로] → 하단 액션 바

- 좌우 분할·행 체크박스·"케이스를 선택하세요" 빈 패널·본문 아이콘 툴바 띠 제거(§0 금지 1·2·3).
- 진입 시 큐의 첫 건 자동 선택. 칩 클릭=선택(오렌지), [n/m]+이전/다음 순회.
- 카드 금지(§0 금지 5) — 구획은 헤어라인+여백만. 색·크기·간격은 §2~§4 값만(§0 금지 8).

레퍼런스 골격: ``아차사고 관리.dc.html`` isCapa 블록(426~507).

기능 계약(불변 — CAPA 폐루프 핵심, 표현 계층만 교체):
  - 행단위 권한(담당자=조치저장/제출, 확인자=확인/재조치요청, 평가자=배정/보고서 종결)과
    서버측 인가·자기확인 차단·007 하드게이트·2단계 종결 RPC 경로 변경 0(modules/db.py 무수정).
  - 워크플로 액션 전부 유지: 조치 저장/배정 저장/저장 · 제출 · 확인 · 재조치 요청 · 보고서 종결.
    역할별 비활성/숨김 규칙 현행 유지. 신원은 항상 ``auth.get_current_user()``.
  - 큐 = 현재 사용자 역할 기준 처리 대상(actor-aware ``list_near_miss_improvements`` +
    담당자 스코핑 ``_scope_reports``). 상태 배지는 §2(P1) 팔레트.
"""
from __future__ import annotations

# DESIGN.md §1-A 큐 처리형 — 읽기 큐(칩) + 전체폭 상세/워크플로.
SCREEN_ARCHETYPE = "MASTER_DETAIL"

from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st

from modules import auth, db
from views import workspace
from views.common import erp, scaffold
from views.master import (
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
_CLOSE_CONFIRM_KEY = "nm_impr_close_confirm"  # 2단계 종결 확인 중인 보고서 id.

_IMPROVEMENT_DESC = "평가 확정된 아차사고의 개선조치를 등록·확인하고 보고서를 종결합니다."

# 이 화면이 다루는 큐 — 평가 확정(EVALUATED) = 개선조치 진행·종결 대기.
_QUEUE_STATUS = "EVALUATED"

_SUBMIT_LABEL = {"DRAFT": "작성중", "SUBMITTED": "제출됨"}
_CONFIRM_LABEL = {"PENDING": "확인대기", "CONFIRMED": "확인됨", "REJECTED": "반려"}
_CONFIRMED = "CONFIRMED"

# ── §2 팔레트 (팔레트 밖 색 금지 §0-8) — 리터럴 고정으로 새 색 유입 차단. ──
_INK = "#1c1a17"          # 본문
_INK2 = "#4a453d"         # 보조(섹션 라벨)
# Codex P1: 이 파일의 _WEAK/_FAINT 는 모두 읽는 작은 텍스트(라벨·단위·모노 오버라인·메타)에
# 쓰이므로 #6b665d(5.1:1↑)로 상향한다 — #8b857c(3.27:1)·#a09a90(2.5:1)은 읽는 텍스트 금지.
_WEAK = "#6b665d"         # 읽는 보조 텍스트(구 #8b857c)
_FAINT = "#6b665d"        # 읽는 캡션·모노 오버라인(구 #a09a90)
_LINE = "#e6e2da"         # 행 헤어라인
_LINE_SEC = "#e0dbd2"     # 섹션 헤어라인
_ACCENT = "#c2410c"
_ACCENT_TEXT = "#b4451a"
_ACCENT_TINT = "#fdf3ec"
_NEUTRAL = "#5c564d"      # §2 종결 배지 텍스트(중립, 6.4:1) — 비-§2 회색(#6b665d) 대체
_MONO = "'IBM Plex Mono', monospace"

# 상태 배지 색(§2 배지 텍스트색 — status_badge_html 이 옅은 배경/테두리를 파생). 모두 §2 값.
_SUBMIT_COLOR = {"DRAFT": _NEUTRAL, "SUBMITTED": "#2f4d99"}
_CONFIRM_COLOR = {"PENDING": "#8a6212", "CONFIRMED": "#2f6b45", "REJECTED": "#9c3232",
                  "미작성": _NEUTRAL}

_LOAD_FAILED_LABEL = "조회실패"
_NOT_READY_MSG = (
    "개선조치 스키마(007)가 아직 적용되지 않아 저장·제출·확인·종결을 진행할 수 없습니다"
    "(조회만 가능). 스키마를 적용한 뒤 다시 시도하세요."
)
_PROBE_ERROR_MSG = (
    "개선조치 스키마 상태 확인 실패 — 재확인이 필요합니다(확인 전까지 쓰기는 차단됩니다)."
)
_STALE_MARK = "이미 변경"  # db 원문 일부 — stale 충돌(다른 사용자 선처리)은 warning 로 분기.

_EVAL_CSS = f"""
<style>
/* 종결 대기 큐 칩(선택=primary 오렌지, 비선택=secondary 흰+테두리) — pill, 히트영역 32px */
[class*="st-key-cq_"] button {{
  border-radius:999px !important; min-height:32px !important; height:auto !important;
  padding:5px 14px !important; font-size:12.5px !important; font-weight:600 !important;
  white-space:nowrap !important; line-height:1.2 !important;
}}
.st-key-cq_prev button, .st-key-cq_next button {{
  min-width:32px !important; width:32px !important; min-height:32px !important; height:32px !important;
  padding:0 !important; border-radius:7px !important; font-size:14px !important;
}}
.cq-head {{ display:flex; align-items:center; gap:8px; margin:2px 0 6px; }}
.cq-head .t {{ font-size:14px; font-weight:600; color:{_INK}; }}
.cq-head .c {{ font-family:{_MONO}; font-size:11px; font-weight:600; padding:2px 8px;
  border-radius:999px; background:{_ACCENT_TINT}; color:{_ACCENT_TEXT}; }}
.cq-pos {{ font-family:{_MONO}; font-size:11.5px; color:{_FAINT}; white-space:nowrap; }}
</style>
"""


# ---------- 진입 ----------
def render(user: dict) -> None:
    # 제목 크롬만(아이콘 툴바 밴드 없음 §0-3) — 아이콘은 상단 52px 헤더에만.
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="개선조치 관리",
        desc=_IMPROVEMENT_DESC,
        breadcrumb="아차사고 › 개선조치 관리",
        badges=scaffold.mode_badge(),
    )
    st.markdown(_EVAL_CSS, unsafe_allow_html=True)
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

    # ── KPI 스트립(제목 바로 아래 첫 블록 §0-4) — 기존 요약 지표를 상단으로 이동 + 기한초과. ──
    # KPI 는 항상 전체 스코프 큐 기준(실제 종결 대기·기한초과 총량) — 필터로 왜곡하지 않는다.
    st.markdown(_kpi_strip_html(scoped, improvements, load_failed), unsafe_allow_html=True)
    _hairline()

    # ── 큐 위 필터(조치 단계·담당자·기간) — 뷰단 필터링(facade 파라미터 없음, 코디 B-2). ──
    # 권한·스코핑·KPI 는 불변이며, 표시 큐만 좁힌다. 제출 버튼 없이 변경 즉시 반영.
    fq, fq_active = _collect_impr_filters(scoped, improvements)
    scoped_view = _apply_impr_filters(scoped, improvements, fq)

    ordered = _ordered_ids(scoped_view)
    if not ordered:
        msg = ("조건에 해당하는 종결 대기 건이 없습니다. 조치 단계·담당자·기간 필터를 조정하세요."
               if fq_active else "현재 종결 대기 중인 개선조치 건이 없습니다.")
        st.markdown(
            f"<div style='padding:22px 0;font-size:14.5px;color:{_INK2};'>{msg}</div>",
            unsafe_allow_html=True,
        )
        return

    # 진입 시 첫 건 자동 선택(§1-A) — 선택이 없거나 (필터로) 큐에서 사라진 경우.
    selected_id = st.session_state.get(_SEL_KEY)
    if selected_id not in ordered:
        selected_id = ordered[0]
        st.session_state[_SEL_KEY] = selected_id
        st.session_state.pop(_CLOSE_CONFIRM_KEY, None)

    reports_by_id = {str(r["id"]): r for _, r in scoped_view.iterrows()}
    _render_queue_chips(ordered, reports_by_id, improvements, load_failed, selected_id)
    _hairline()
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
    if df is None or df.empty:
        return []
    frame = df.sort_values("incident_date", ascending=False, kind="stable")
    return [str(v) for v in frame["id"].tolist()]


# ---------- 큐 필터(뷰단 — 조치 단계·담당자·기간) ----------
_FILTER_PID = f"{_PAGE_ID}_flt"          # condition_panel page_id(세션 위젯 키 접두)
_STAGE_OPTS = ["전체", "미작성", "작성중", "확인대기", "확인됨", "반려"]


def _impr_stage(imp) -> str:
    """개선조치 한 건의 '조치 단계' 라벨(제출/확인 상태 파생 — 필터·표시 어휘 통일).

    미작성(imp 없음) < 작성중(DRAFT) < 확인대기(SUBMITTED·PENDING) < 확인됨(CONFIRMED) /
    반려(REJECTED). 확정 상태(확인됨/반려)를 제출 상태보다 우선 판정한다."""
    if not imp:
        return "미작성"
    confirm = str(imp.get("confirm_status") or "").strip()
    submit = str(imp.get("submit_status") or "").strip()
    if confirm == "CONFIRMED":
        return "확인됨"
    if confirm == "REJECTED":
        return "반려"
    if submit == "SUBMITTED":
        return "확인대기"
    if submit == "DRAFT":
        return "작성중"
    return "미작성"


def _collect_impr_filters(scoped: pd.DataFrame, improvements: dict) -> tuple[dict, bool]:
    """§1-E 필터 줄(조치 단계·담당자·기간)을 렌더하고 (필터 dict, 활성여부)를 반환한다.

    담당자 옵션은 현재 스코프 큐에 실제 배정된 담당자만(+전체)으로 구성한다(허수 옵션 방지).
    기본 기간은 '전체'. 제출 버튼 없이 변경 즉시 반영(뷰단 필터)."""
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
        erp.Field(key="stage", label="조치 단계", kind="select", width=150, options=_STAGE_OPTS),
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
        "stage": v["stage"],
        "assignee": v["assignee"],
        "date_from": v["from"].isoformat() if on and "from" in v else "",
        "date_to": v["to"].isoformat() if on and "to" in v else "",
    }
    active = (v["stage"] != "전체") or (v["assignee"] != workspace.ALL) or on
    return q, active


def _apply_impr_filters(scoped: pd.DataFrame, improvements: dict, q: dict) -> pd.DataFrame:
    """뷰단 필터 적용(권한·스코핑 불변 — 표시 큐만 좁힌다). 조건 불일치 행을 제거한다."""
    if scoped is None or scoped.empty:
        return scoped
    stage = q.get("stage") or "전체"
    assignee = q.get("assignee")
    date_from = q.get("date_from") or ""
    date_to = q.get("date_to") or ""
    keep = []
    for idx, r in scoped.iterrows():
        imp = improvements.get(str(r["id"]))
        if stage != "전체" and _impr_stage(imp) != stage:
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


def _confirm_state_of(imp) -> str:
    if not imp:
        return "미작성"
    return str(imp.get("confirm_status") or "").strip() or "미작성"


# ---------- KPI 스트립 ----------
def _kpi_strip_html(scoped: pd.DataFrame, improvements: dict, load_failed: bool) -> str:
    """KPI 4종(§1-A: 좌측 2px 보더 + 26px 모노 숫자). 전부 기존 데이터에서 파생.

    종결 대기(scoped 큐 크기, accent) · 확인 완료(CONFIRMED) · 진행·미작성(대기-확인완료) ·
    기한초과(due_date 경과 & 미확인). 조회 실패 시 파생 3종은 '—'(오류≠0)."""
    total = 0 if scoped is None or scoped.empty else len(scoped)
    if load_failed:
        items = [
            ("종결 대기", total, "건", "PENDING CLOSE", True),
            ("확인 완료", "—", "건", "VERIFIED", False),
            ("진행·미작성", "—", "건", "IN PROGRESS", False),
            ("기한초과", "—", "건", "OVERDUE", False),
        ]
        return _metric_strip_html(items)
    confirmed = sum(1 for imp in improvements.values()
                    if imp and str(imp.get("confirm_status") or "") == _CONFIRMED)
    in_progress = max(total - confirmed, 0)
    today = date.today().isoformat()
    overdue = 0
    for imp in improvements.values():
        if not imp or str(imp.get("confirm_status") or "") == _CONFIRMED:
            continue
        due = str(imp.get("due_date") or "").strip()
        if due and due < today:  # ISO 날짜 문자열 사전식 비교(안전)
            overdue += 1
    return _metric_strip_html([
        ("종결 대기", total, "건", "PENDING CLOSE", True),
        ("확인 완료", confirmed, "건", "VERIFIED", False),
        ("진행·미작성", in_progress, "건", "IN PROGRESS", False),
        ("기한초과", overdue, "건", "OVERDUE", False),
    ])


def _metric_strip_html(items) -> str:
    cells = []
    for label, value, unit, note, accent in items:
        border = _ACCENT if accent else _LINE_SEC
        valcolor = _ACCENT_TEXT if accent else _INK
        val = escape(str(value)) if not isinstance(value, (int, float)) else str(int(value))
        cells.append(
            f"<div style='flex:1 1 150px;min-width:0;display:flex;flex-direction:column;gap:5px;"
            f"padding:0 18px;border-left:2px solid {border};'>"
            f"<span style='font-size:12px;color:{_WEAK};'>{escape(label)}</span>"
            f"<div style='display:flex;align-items:baseline;gap:4px;'>"
            f"<span style='font-family:{_MONO};font-size:26px;font-weight:600;letter-spacing:-0.03em;"
            f"color:{valcolor};'>{val}</span>"
            f"<span style='font-size:11.5px;color:{_FAINT};'>{escape(unit)}</span></div>"
            f"<span style='font-size:11px;color:{_FAINT};font-family:{_MONO};'>{escape(note)}</span></div>"
        )
    return f"<div style='display:flex;flex-wrap:wrap;gap:12px;padding:2px 0 14px;'>{''.join(cells)}</div>"


def _hairline() -> None:
    st.markdown(
        f"<div style='border-top:1px solid {_LINE_SEC};margin:2px 0 10px;'></div>",
        unsafe_allow_html=True,
    )


# ---------- 종결 대기 큐 칩 스트립 ----------
def _render_queue_chips(ordered: list[str], reports_by_id: dict, improvements: dict,
                        load_failed: bool, selected_id: str) -> None:
    """종결 대기 큐를 칩 스트립으로 렌더(§1-A·§7: st.button 반복 + session_state.sel).

    칩=보고번호+작업명+확정등급. 선택=오렌지(primary), 나머지=흰+테두리. [n/m]+이전/다음.
    케이스 전환 시 2단계 종결 확인(_CLOSE_CONFIRM_KEY)을 초기화한다(오처리 방지)."""
    idx = ordered.index(selected_id)
    st.markdown(
        f"<div class='cq-head'><span class='t'>종결 대기 큐</span>"
        f"<span class='c'>{len(ordered)}</span></div>",
        unsafe_allow_html=True,
    )
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        for rid in ordered:
            r = reports_by_id.get(rid, {})
            short = str(r.get("report_no") or rid)[-8:]
            title = str(r.get("work_name") or "(제목 없음)")
            if len(title) > 20:
                title = title[:19] + "…"
            grade = str(r.get("confirmed_grade") or "").strip()
            label = f"{short} · {title}" + (f" · {grade}" if grade else "")
            picked = st.button(
                label, key=f"cq_{rid}",
                type="primary" if rid == selected_id else "secondary",
            )
            if picked and rid != selected_id:
                st.session_state[_SEL_KEY] = rid
                st.session_state.pop(_CLOSE_CONFIRM_KEY, None)
                st.rerun()
        st.markdown(f"<span class='cq-pos'>{idx + 1}/{len(ordered)}</span>",
                    unsafe_allow_html=True)
        if st.button("‹", key="cq_prev", help="이전 건",
                     disabled=idx <= 0, type="secondary"):
            st.session_state[_SEL_KEY] = ordered[idx - 1]
            st.session_state.pop(_CLOSE_CONFIRM_KEY, None)
            st.rerun()
        if st.button("›", key="cq_next", help="다음 건",
                     disabled=idx >= len(ordered) - 1, type="secondary"):
            st.session_state[_SEL_KEY] = ordered[idx + 1]
            st.session_state.pop(_CLOSE_CONFIRM_KEY, None)
            st.rerun()


# ---------- 전체폭 상세 ----------
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
        st.markdown(
            f"<div style='padding:22px 0;font-size:14.5px;color:{_INK2};'>"
            "이 케이스는 더 이상 종결 대기 상태가 아닙니다. 다른 사용자가 먼저 처리했을 수 있습니다 — "
            "새로고침한 뒤 다시 선택하세요.</div>",
            unsafe_allow_html=True,
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

    # ── 전체폭 상세(읽기 HTML): 보고번호+평가완료 pill + 제출/확인 배지 / 제목 / 메타 / 본문 블록 ──
    st.markdown(_detail_read_html(report, imp, status), unsafe_allow_html=True)

    # ── 워크플로 클러스터(CAPA 폼 + 역할별 scope 액션) — 본문 블록 바로 뒤 ──
    st.markdown(
        f"<div style='border-top:1px solid {_LINE_SEC};margin:12px 0 2px;'></div>",
        unsafe_allow_html=True,
    )
    form = _render_capa_form(selected_id, imp, readiness, can_work=can_work, can_assign=can_assign)
    _render_actions(user, report, imp, form, readiness,
                    can_work=can_work, can_review=can_review, can_assign=can_assign)

    # ── 부차 참조 서술(작업 내용·현장 설명)은 기본 접힘으로 상세 높이 bound(§0.4 네이티브 expander). ──
    with st.expander("보고서 원문 더 보기", expanded=False):
        erp.field_block("작업 내용", str(report.get("work_content") or ""))
        erp.field_block("현장 설명", str(report.get("site_description") or ""))


def _detail_read_html(report: dict, imp, status: str) -> str:
    """선택 건 전체폭 상세(§1-A) — 보고번호(18px 모노)+상태 pill·제출/확인 배지 / 제목(17/600) /
    우측 메타(신고자·발생일·부서·확정등급) / 본문 블록(WHAT·CAUSE·ACTION)."""
    report_no = escape(str(report.get("report_no") or "-"))
    status_pill = lifecycle_badge_html(status, "평가완료")
    submit_status = str(imp.get("submit_status") or "") if imp else ""
    confirm_status = _confirm_state_of(imp)
    submit_badge = erp.status_badge_html(
        _SUBMIT_LABEL.get(submit_status, "미작성"),
        _SUBMIT_COLOR.get(submit_status, _NEUTRAL))
    confirm_badge = erp.status_badge_html(
        _CONFIRM_LABEL.get(confirm_status, confirm_status),
        _CONFIRM_COLOR.get(confirm_status, _NEUTRAL))
    title = escape(str(report.get("work_name") or "(제목 없음)"))
    grade = escape(str(report.get("confirmed_grade") or "-"))

    lbl = f"font-size:11.5px;color:{_INK2};"
    head_left = (
        "<div style='display:flex;flex-direction:column;gap:7px;min-width:0;'>"
        "<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap;'>"
        f"<span style='font-family:{_MONO};font-size:18px;font-weight:600;color:{_INK};'>{report_no}</span>"
        f"{status_pill}"
        f"<span style='{lbl}'>제출</span>{submit_badge}"
        f"<span style='{lbl}'>확인</span>{confirm_badge}</div>"
        f"<span style='font-size:17px;color:{_INK};font-weight:600;letter-spacing:-0.02em;'>{title}</span>"
        "</div>"
    )
    meta = [
        ("신고자", _user_label(report.get("reporter_emp_no"))),
        ("발생일", str(report.get("incident_date") or "-")),
        ("부서", str(report.get("dept_code") or "-")),
        ("확정등급", grade),
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
        f"justify-content:space-between;gap:14px 20px;'>{head_left}"
        f"<div style='display:flex;flex-wrap:wrap;gap:12px 26px;'>{meta_cells}</div></div>"
    )

    cause = str(report.get("cause_code") or "")
    cause_detail = str(report.get("cause_detail") or "")
    cause_val = cause + (f" · {cause_detail}" if cause_detail else "")
    blocks = [
        ("WHAT", "사고 내용", str(report.get("incident_content") or ""), True),
        ("CAUSE", "원인", cause_val, False),
        ("ACTION", "제안 대책", str(report.get("countermeasure") or ""), True),
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
        f"<div style='padding:22px 0 6px;border-top:1px solid {_LINE_SEC};"
        f"display:flex;flex-wrap:wrap;gap:22px 32px;'>{''.join(block_cells)}</div>"
    )
    return head + body_blocks


def _user_options() -> tuple[list[str], dict]:
    """활성 사용자 select 옵션(빈 항목 포함) + emp_no→라벨 사전."""
    try:
        df = db.get_users()
    except Exception:
        return [""], {"": "— 선택 —"}
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
    return options, labels


def _select_index(options: list[str], value) -> int:
    value = str(value or "").strip()
    return options.index(value) if value in options else 0


def _render_capa_form(selected_id, imp, readiness: ReadinessState,
                      *, can_work: bool, can_assign: bool) -> dict:
    """CAPA 입력 폼(담당자·확인자·기한·조치 내용/결과). 반환은 위젯 현재값.

    행단위 편집 경계: 배정 필드(담당자·확인자)는 can_assign(평가자/ADMIN)만, 작업 필드
    (기한·조치 내용/결과)는 can_work(배정 담당자 본인·ADMIN)만 편집 가능하고 그 외에는
    읽기전용(disabled)으로 표시한다 — facade 가 어차피 strip 하지만 화면도 경계를 드러낸다."""
    confirm_status = _confirm_state_of(imp)
    if imp and confirm_status == "REJECTED" and str(imp.get("revision_note") or "").strip():
        banner("warn", f"재조치 요청 사유: {str(imp.get('revision_note')).strip()}")

    options, labels = _user_options()
    fmt = lambda emp: labels.get(emp, emp)  # noqa: E731

    if not can_assign:
        st.caption("담당자·확인자 배정은 평가자·관리자만 변경할 수 있습니다.")
    with st.container(horizontal=True, gap="medium"):
        assignee = st.selectbox(
            "조치 담당자", options,
            index=_select_index(options, imp.get("assignee_emp_no") if imp else ""),
            format_func=fmt, key=f"nm_impr_assignee_{selected_id}",
            disabled=not can_assign, width=240,
        )
        confirmer = st.selectbox(
            "조치 확인자", options,
            index=_select_index(options, imp.get("designated_confirmer_emp_no") if imp else ""),
            format_func=fmt, key=f"nm_impr_confirmer_{selected_id}",
            disabled=not can_assign, width=240,
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


def _render_actions(user: dict, report: dict, imp, form: dict, readiness: ReadinessState,
                    *, can_work: bool, can_review: bool, can_assign: bool) -> None:
    """행단위 역할 variant scope 액션(§0.4) — §1-A 하단 액션 바. 버튼 노출을 능력으로 가른다:

      - can_work(담당자/ADMIN): 조치 저장·제출.
      - can_assign(평가자/ADMIN): 배정 저장(담당자·확인자 지정).
      - can_review(확인자/평가자/ADMIN): 확인·재조치 요청·보고서 종결.

    자기확인(담당자==세션) 시 확인은 disabled+help 로 남기고 facade 도 차단한다. 실제 쓰기·
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

    clicks = erp.detail_actions(_PAGE_ID, actions)

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
    if close_clicks.get("보고서 종결") and not disabled:
        st.session_state[_CLOSE_CONFIRM_KEY] = selected_id
        st.rerun()

    if st.session_state.get(_CLOSE_CONFIRM_KEY) != selected_id:
        return

    # 인라인 확인 영역 — 보고번호·확정등급·확인된 개선조치 요약 + 불가역 고지.
    report_no = str(report.get("report_no") or "-")
    grade = str(report.get("confirmed_grade") or "-")
    result_summary = str((imp or {}).get("result_body") or "").strip() or "(조치 결과 없음)"
    if len(result_summary) > 80:
        result_summary = result_summary[:80] + "…"
    banner(
        "warn",
        f"보고서 종결(불가역): {report_no} · 확정등급 {grade} · 확인된 개선조치 "
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
