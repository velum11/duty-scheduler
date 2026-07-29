"""내 아차사고 — 본인이 등록한 아차사고 목록 + 상세 + 상태(+ 제출됨 자기수정).

DESIGN.md §0 화면 유형: ``MASTER_DETAIL`` — 읽기 목록(본인 작성 건) + 상세/워크플로
패널(상세 확인 + SUBMITTED 상태에서만 본문 수정). 상단 액션바는 조회(새로고침)만 두고,
유일한 쓰기(본문 수정)는 상세 패널의 scope 액션이 담당한다.

신원 계약(중요): 목록 범위는 화면 위젯이 아니라 인증된 세션 사용자의 사번으로 고정한다
(``get_near_miss_reports({"reporter_emp_no": <세션 사번>})``). 수정도 세션 사용자를 그대로
넘겨(``db.update_near_miss_report(report_id, payload, current_user=...)``) 파사드가 소유자·
상태를 서버측에서 재확인한다 — 타인 건 열람·수정 위조 방지.

수정 게이트: 선택 건이 ``SUBMITTED`` 일 때만 수정 진입이 나타난다. 파사드
``db.update_near_miss_report`` 는 병렬 작업으로 추가되는 중이라, 부재 시
``hasattr(db, "update_near_miss_report")`` 로 진입을 가드하고 통합 대기 안내만 노출한다.

보완요청 피드백: 평가자가 보완요청(반송)한 제출됨(SUBMITTED) 건은 ``info`` 배너로 사유를
안내한다(반려 ≠ 보완요청 — 별도 시각·문구). 보고자는 기존 SUBMITTED 자기수정·재제출
경로로 자연 연결된다(별도 재제출 버튼 없음).

범위 밖(의도적 미구현): 제출 취소(deferred — 버튼 없음/안내만, 삭제로 대체하지 않음),
복잡한 상태 시스템.
"""
from __future__ import annotations

# DESIGN.md §0 화면 유형 규약 — 읽기 목록 + 상세/워크플로 패널.
SCREEN_ARCHETYPE = "MASTER_DETAIL"

from datetime import date
from html import escape

import pandas as pd
import streamlit as st

from modules import auth, db, nav, ui
from views.common import erp, scaffold
from views.master import TOKENS, banner, icon_toolbar_specs, sheet_head
from views.master.lifecycle import Readiness, ReadinessState

_PAGE_ID = "near_miss_my"
_SEL_KEY = "nm_my_selected_id"

_STATUS_LABEL = {
    "SUBMITTED": "제출됨", "IN_REVIEW": "검토중", "EVALUATED": "평가완료",
    "REJECTED": "반려", "CLOSED": "종결",
}
_STATUS_COLOR = {
    "SUBMITTED": TOKENS["info"], "IN_REVIEW": TOKENS["gold"],
    "EVALUATED": TOKENS["success"], "REJECTED": TOKENS["danger"], "CLOSED": TOKENS["ink-3"],
}
_CAUSE_LABEL = {
    "JAM": "끼임", "FALL": "추락", "DROP": "낙하물", "HIT": "부딪힘·충돌",
    "SLIP": "미끄러짐·넘어짐", "BURN": "화상·고온", "PINCH": "협착", "ETC": "기타",
}
_EDITABLE_STATUS = "SUBMITTED"

# 큐 표시 열 + 숨김 자연키(_report_id). 선택은 자연키로 오간다(정렬·필터 후 위치 비의존).
# USER·모바일 세로 폭에서 가로 스크롤 0 을 보장하려고 목록은 식별에 필요한 4열만 남긴다
# (제안등급은 상세 메타로 내려 좁은 폭 열 폭 합을 줄인다 — 평가/개선조치 파일럿의 밀도 결정과 동일).
_KEY_FIELD = "_report_id"
_QUEUE_COLS = ["보고번호", "작업명", "발생일", "상태"]
# 폭 합(고정 3열 + 작업명 minWidth ≈ 348)을 모바일 세로 스택 시 목록 폭(≈370px)에 맞춰
# 가로 스크롤 0 을 보장한다(실측 조정). @1024·1366 넓은 폭에선 flex 작업명이 여유를 채운다.
_QUEUE_COL_CONFIG = {
    "보고번호": {"flex": 0, "width": 100, "minWidth": 88, "cellClass": "md-c-left"},
    "작업명": {"flex": 1.4, "minWidth": 88, "cellClass": "md-c-left"},
    "발생일": {"flex": 0, "width": 90, "minWidth": 82, "cellClass": "md-c-center"},
    "상태": {"flex": 0, "width": 70, "minWidth": 60, "maxWidth": 92, "cellClass": "md-c-center"},
}
# USER·터치 행 피치(§0.6 — 44px, 32×32 히트영역 계약과 정합). 데스크톱 34 가 아니라 44 를 준다.
_ROW_PX = 44


def render(user: dict) -> None:
    band = erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="내 아차사고",
        desc="본인이 등록한 아차사고와 처리 상태를 확인합니다.",
        breadcrumb="아차사고 › 내 아차사고",
        badges=scaffold.mode_badge(),
        toolbar="icons",
    )
    # 상단 파랑 밴드 아이콘 툴바(공통 표준). page-scope 조회 액션은 새로고침뿐 — search
    # 아이콘 클릭의 rerun 만으로 아래 목록이 재조회된다(구 pill 과 동일). 유일한 쓰기(본문
    # 수정)는 상세 패널 scope 액션 소관이라 밴드 추가·삭제·저장은 N/A(shaded).
    if band is not None:
        band.render_icons(icon_toolbar_specs(
            _PAGE_ID, info_content=nav.page_desc(_PAGE_ID),
            add={"key": f"{_PAGE_ID}__add_na", "disabled": True,
                 "help": "이 화면에서는 사용하지 않습니다"},
            refresh={"key": f"{_PAGE_ID}_refresh", "help": "새로고침", "on_click": None},
            delete={"key": f"{_PAGE_ID}__del_na", "disabled": True,
                    "help": "이 화면에서는 사용하지 않습니다"},
            save={"key": f"{_PAGE_ID}__save_na", "disabled": True,
                  "help": "이 화면에서는 사용하지 않습니다"},
        ))

    emp_no = str(user.get("emp_no") or "").strip()
    if not emp_no:
        ui.empty_state("로그인 사번을 확인할 수 없어 내 아차사고를 표시할 수 없습니다.",
                       head="내 아차사고")
        return

    _readiness().banner()

    # 영역 순서(§0.3): title(밴드 아이콘 툴바) → primary(목록) + details(상세).
    # 새로고침은 상단 밴드 아이콘으로 이전했다(위 render_icons — 인페이지 pill 제거).

    try:
        reports = db.get_near_miss_reports({"reporter_emp_no": emp_no})
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"내 아차사고 목록을 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("내 아차사고 목록을 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    if reports is None or reports.empty:
        ui.empty_state("아직 등록한 아차사고가 없습니다. '아차사고 등록'에서 접수할 수 있습니다.",
                       head="내 아차사고")
        return

    # 영역 순서(§0.3): primary(큐) + details(상세). USER·모바일 좁은 폭에서는 st.columns 가
    # 세로로 접혀 목록→상세 스택이 된다(§0.7). 데스크톱(M/A)에서는 §0.6 강제(상세 폭 ≥600px)에
    # 맞춰 목록 40%·상세 60%로 분할한다(SUBMITTED 자기수정 폼 확보). 선택은 select_grid 행클릭.
    list_col, detail_col = erp.master_detail_frame(list_ratio=1.0, detail_ratio=1.5)
    selected_id = st.session_state.get(_SEL_KEY)
    with list_col:
        picked = _render_queue(reports, selected_id)
    # 선택을 상세 렌더 전에 소비한다 — select_grid 의 selectionChanged rerun 이 이미 일어난
    # run 이므로 여기서 세션만 갱신하면 추가 st.rerun 없이 곧바로 상세를 그린다(즉시 상세).
    if picked is not None and picked != selected_id:
        st.session_state[_SEL_KEY] = picked
        selected_id = picked
    with detail_col:
        _render_detail(user, reports)


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


# ---------- 목록/큐(primary — 단일 선택) ----------
def _clean(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _queue_rows(reports: pd.DataFrame) -> pd.DataFrame:
    """큐 표시 프레임 — 숨김 자연키(_report_id) + 표시 4열."""
    cols = [_KEY_FIELD, *_QUEUE_COLS]
    if reports is None or reports.empty:
        return pd.DataFrame(columns=cols)
    frame = reports.sort_values("incident_date", ascending=False, kind="stable")
    rows = []
    for _, r in frame.iterrows():
        status = _clean(r.get("status"))
        rows.append({
            _KEY_FIELD: str(r.get("id")),
            "보고번호": _clean(r.get("report_no")) or "-",
            "작업명": _clean(r.get("work_name")) or "-",
            "발생일": _clean(r.get("incident_date")) or "-",
            "상태": _STATUS_LABEL.get(status, status or "-"),
        })
    return pd.DataFrame(rows, columns=cols)


def _render_queue(reports: pd.DataFrame, selected_id) -> str | None:
    """내 아차사고를 단일 선택 큐로 렌더하고 선택된 보고서 자연키를 돌려준다.

    구 ``st.selectbox('상세 볼 보고서')`` 를 없애고 목록 행 선택이 상세 선택을 대체한다
    (Codex 지적 — 목록 클릭=상세). ``erp.select_grid`` 네이티브 single-selection: 행 클릭 시
    체크 마커 + 배경 틴트로 이중부호화(§4)되고, 선택 자연키(_report_id)를 반환한다(정렬·필터
    후 위치 비의존). USER·터치 밀도 44px(§0.6)."""
    rows = _queue_rows(reports)
    sheet_head("내 아차사고", count=len(rows))
    status_rules = {label: _STATUS_COLOR[code] for code, label in _STATUS_LABEL.items()}
    return erp.select_grid(
        rows, key=f"{_PAGE_ID}_queue", key_field=_KEY_FIELD,
        columns=_QUEUE_COLS, selected_key=selected_id,
        col_config=_QUEUE_COL_CONFIG, color_rules={"상태": status_rules},
        row_height=_ROW_PX,
    )


# ---------- 상세(details, 그룹2 골격) + SUBMITTED 자기수정 ----------
def _render_detail(user: dict, reports: pd.DataFrame) -> None:
    """그룹2 상세: 상태 badge → 피드백 배너 → 짧은 메타 2열 + 핵심 내용 → 워크플로(자기수정)
    상단 근처 → 부차 서술 접기. 선택은 왼쪽 큐 행클릭(_SEL_KEY)이 소유한다(구 selectbox 제거)."""
    selected_id = st.session_state.get(_SEL_KEY)
    if not selected_id:
        erp.detail_empty("보고서를 선택하세요",
                         "왼쪽 목록에서 행을 클릭하면 상세와 처리 상태를 확인할 수 있습니다.")
        return

    match = reports[reports["id"].astype(str) == str(selected_id)]
    if match.empty:
        # 목록에서 사라진 stale 선택 — _SEL_KEY 해제하고 미선택 상태로 되돌린다.
        st.session_state.pop(_SEL_KEY, None)
        erp.detail_empty("보고서를 선택하세요",
                         "선택한 보고서를 목록에서 찾을 수 없습니다. 목록에서 다시 선택하세요.")
        return
    report = match.iloc[0].to_dict()
    status = _clean(report.get("status"))

    # ── 상단: 보고번호 + 상태 배지(색+라벨 이중부호화) ──
    _render_detail_head(report, status)

    # ── 피드백 배너(상단 근처) — 반려(warn)와 보완요청(info)은 별개 시각·문구를 유지한다. ──
    if status == "REJECTED" and _clean(report.get("rejection_reason")):
        banner("warn", f"반려 사유: {_clean(report.get('rejection_reason'))}")
    # 보완요청(반송) 피드백 — 제출됨(SUBMITTED) 상태에서 평가자가 재작성을 요청한 경우.
    # 반려(REJECTED=종결분기)와 별개 의미·별개 문구·별개 시각(info)이며, 보고자는 기존
    # SUBMITTED 자기수정·재제출 경로로 자연 연결된다(별도 재제출 버튼 없음).
    if status == "SUBMITTED":
        _render_revision_banner(selected_id)

    # ── 짧은 메타 2열 + 핵심 내용(작업명·사고내용, 전폭) ──
    _render_report_context(report)

    # ── 워크플로(SUBMITTED 자기수정 액션) — 핵심 내용 바로 뒤(부차 서술보다 위). ──
    _render_edit_entry(user, report, status)

    # ── 부차 참조 서술(발생원인 상세·작업내용·예방대책·현장 상황) 기본 접힘으로 상세 높이 bound. ──
    _render_report_reference(report)


def _render_detail_head(report: dict, status: str) -> None:
    """보고번호(제목 §2 20/700) + 상태 배지(색+라벨 이중부호화)."""
    report_no = escape(_clean(report.get("report_no")) or "(번호 미상)")
    badge = erp.status_badge_html(
        _STATUS_LABEL.get(status, status or "-"),
        _STATUS_COLOR.get(status, TOKENS["ink-3"]),
    )
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:2px 0 8px;'>"
        f"<span style='font-size:20px;font-weight:700;color:{TOKENS['ink']};"
        f"line-height:1.2;'>{report_no}</span>{badge}</div>",
        unsafe_allow_html=True,
    )


def _render_report_context(report: dict) -> None:
    """짧은 메타 2열(발생일·제안등급 / 확정등급·발생원인) + 핵심 내용(작업명·사고내용, 전폭)."""
    cause = _clean(report.get("cause_code"))
    left = [
        ("발생일", _clean(report.get("incident_date")) or "-"),
        ("제안등급", _clean(report.get("proposed_grade")) or "없음"),
    ]
    right = [
        ("확정등급", _clean(report.get("confirmed_grade")) or "미정"),
        ("발생원인", _CAUSE_LABEL.get(cause, cause) or "-"),
    ]
    mc1, mc2 = st.columns(2)
    mc1.markdown(erp.meta_col_html(left), unsafe_allow_html=True)
    mc2.markdown(erp.meta_col_html(right), unsafe_allow_html=True)
    erp.field_block("작업명", _clean(report.get("work_name")))
    erp.field_block("사고내용", _clean(report.get("incident_content")))


def _render_report_reference(report: dict) -> None:
    """참조성 서술(발생원인 상세·작업내용·예방대책·현장 상황)을 기본 접힘 expander 로 내린다.

    자기수정 워크플로가 이 위에 있으므로 장문 케이스에서도 주요 행동(수정 진입)이 긴 서술에
    밀리지 않는다(§0.4 sticky/fixed 미사용, st.expander 네이티브 접기만)."""
    with st.expander("보고서 상세 더 보기", expanded=False):
        cause_detail = _clean(report.get("cause_detail"))
        if cause_detail:
            erp.field_block("발생원인 상세", cause_detail)
        erp.field_block("작업내용", _clean(report.get("work_content")))
        erp.field_block("예방대책", _clean(report.get("countermeasure")))
        erp.field_block("작업현장 상황설명", _clean(report.get("site_description")))


def _render_revision_banner(report_id) -> None:
    """제출됨 건에 걸린 보완요청(사유/요청자/시각)을 안내한다.

    반려(REJECTED) 배너는 ``warn``(경고), 보완요청은 ``info``(파랑)로 **별도 시각**을 준다
    — 반려는 종결분기, 보완요청은 재작성 요청이라 성격이 다르다. 007 미적용이면 facade 가
    None 을 돌려주므로 배너가 뜨지 않는다(정상 부재 = 가짜 표시 없음). 반면 실제 조회
    오류는 '보완요청 없음'으로 조용히 삼키지 않고 danger 배너로 표면화한다 — 보완요청이
    걸린 건을 오류 때문에 못 본 채 방치하지 않기 위함이다(오류≠정상 부재)."""
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


def _render_edit_entry(user: dict, report: dict, status: str) -> None:
    """SUBMITTED 상태에서만 본문 수정 진입을 노출한다. 제출 취소는 범위 밖(안내만)."""
    if status != _EDITABLE_STATUS:
        st.caption("제출됨 상태에서만 내용을 수정할 수 있습니다.")
        return
    # 파사드가 아직 없으면(병렬 통합 대기) 진입을 막고 사유만 알린다.
    if not hasattr(db, "update_near_miss_report"):
        banner("info", "수정 기능은 통합 대기 중입니다(update_near_miss_report 파사드 연결 후 활성화).")
        return

    with st.expander("내용 수정 (제출됨 상태)", expanded=False):
        _render_edit_form(user, report)
    st.caption("제출 취소는 현재 준비되지 않았습니다(후속 반영 예정).")


def _render_edit_form(user: dict, report: dict) -> None:
    rid = report.get("id")
    with st.form(f"nm_my_edit_{rid}", clear_on_submit=False):
        work_name = st.text_input("작업명", value=_clean(report.get("work_name")), max_chars=120)
        # 제안 등급 입력은 사용자 요구 변경(2026-07-29)으로 제거했다 — 기존 저장값은 보존한다
        # (수정으로 조용히 지워지지 않게). 발생일·발생원인을 2열로 배치(§0.6 중첩 1회 내).
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
        "photo_paths": list(report.get("photo_paths") or []),  # 기존 첨부 보존(본문만 수정).
    }
    _save_edit(rid, payload)


def _save_edit(report_id, payload: dict) -> None:
    """세션 사용자로 본문 수정을 시도한다(파사드가 소유자·SUBMITTED 를 서버측 재확인).

    도메인 검증 오류(ValueError)는 사용자 안전 문구이므로 그대로 노출하고, 그 외
    예외는 원문(raw)을 감춰 일반 안내로 접는다.
    """
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
