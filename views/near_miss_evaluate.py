"""아차사고 평가 화면 — 대기 큐(단일 선택 목록) + 케이스 상세 드릴다운.

DESIGN.md §0 화면 유형: ``MASTER_DETAIL``. 이 화면은 다건 인라인 편집·저장 그리드가
아니라, 조회 전용 목록(큐)과 그 옆 상세/워크플로 패널로 구성된 읽기 목록 + 상세 화면이다
(§0.8/§0.1 유형 매뉴페스트: MASTER_DETAIL = 읽기 목록 + 상세/워크플로). 상단 액션바는
page-scope 조회 액션(새로고침)만 두고, 유일한 쓰기(평가확정/반려)는 상세 패널의
scope 액션(``erp.detail_actions``)이 담당한다 — 파사드 직접 호출, 그리드 저장 lifecycle
미사용(이 화면은 다건 편집·저장이 아니라 단건 상태전이라 ``run_save`` 대상이 아니다).
목록 그리드는 중립 키트의 **단일 선택 어댑터**(``erp.select_grid``)를 쓴다 — 편집
렌더러(``render_master_grid``)의 ``_action`` 열·paste·hidden 편집메타·unsafe jscode 를
쓰지 않고, AgGrid 네이티브 single-selection(체크 마커 + 배경 틴트 이중부호화)으로 케이스를
고른다. 선택은 자연키(보고서 id)로 오가며(정렬·필터 후 위치 비의존), 상세 렌더 전에 소비해
추가 rerun 없이 상세를 그린다(§0.5 capability 분리 정합).

권한 게이트: ``auth.can_evaluate_near_miss(user)`` — ADMIN/MANAGER 또는 안전담당자만
평가할 수 있다(``modules/auth.py``). 게이트를 통과하지 못하면 조회 전용 안내만 보여주고
그리드·상세 패널을 렌더하지 않는다.

파사드 호출(전부 ``modules/db.py`` 만 사용, repository 직접 호출 없음):
  - ``db.get_near_miss_reports(filters)`` — 목록 조회 후 SUBMITTED/IN_REVIEW 만
    화면에서 필터링(파사드는 단일 status 필터만 지원하므로 두 상태는 클라이언트 측에서
    골라낸다).
  - ``db.get_near_miss_report(report_id)`` — 상세 패널 단건 재조회(선택 갱신·행위 직전
    최신 상태 확인).
  - ``db.evaluate_near_miss(report_id, grade, current_user=...)`` — 평가확정
    (SUBMITTED/IN_REVIEW 에서만 허용, 서버측에서 평가자·시각을 확정한다).
  - ``db.update_near_miss_status(report_id, "IN_REVIEW", current_user=...)`` — 검토착수
    상태전이(SUBMITTED 에서만, 전이표 밖이면 ValueError). 전용 사유 필드가 없어 payload
    없이 상태만 바꾼다(보완요청 SUBMITTED 반송은 사유 저장이 007 종속이라 이번 범위 아님).
  - ``db.update_near_miss_status(report_id, "REJECTED", rejection_reason=,
    current_user=...)`` — 반려 상태전이(전이표 밖이면 ValueError).
  - ``db.request_near_miss_revision(report_id, reason, current_user=...)`` — 보완요청
    (IN_REVIEW→SUBMITTED 반송 + 사유 서버기록). 반려(REJECTED, 종결분기)와 **의미가
    다르다**: 보완요청은 보고자에게 재작성을 요청하는 것이고 사유는 rejection_reason 을
    재사용하지 않는다. IN_REVIEW 에서만 가능하며 007 미적용/probe 오류면 파사드가
    fail-closed 로 차단한다(사유 없는 반송 방지).
  - ``db.near_miss_schema_probe()`` — migration 006 준비 상태(3-state) 배너.

신원 위조 방지: 두 쓰기 호출 모두 ``current_user=auth.get_current_user()`` 를 그대로
넘긴다(위젯 입력이 아니라 세션 사용자) — 파사드가 사번을 다시 DB 에서 확인해 평가자를
서버측으로 확정한다(``modules/db.py::_near_miss_actor``).

stale 처리: 두 파사드 모두 사전평가 상태(SUBMITTED/IN_REVIEW)를 조건부로 확인하고,
다른 평가자가 먼저 처리했으면 정확한 문구("상태가 이미 변경되어...")를 담은
``ValueError`` 를 낸다. 이 화면은 그 메시지를 원문 그대로 배너에 노출한다(가공/삭제
금지) — 새 예외 텍스트를 만들지 않는다. 배너는 2단계(제목 + 원문 사유) 패턴이며 raw
traceback 은 절대 노출하지 않는다(``_run_action``).
"""
# DESIGN.md §0 화면 유형 규약 — 읽기 목록(큐) + 상세/워크플로 패널.
SCREEN_ARCHETYPE = "MASTER_DETAIL"

from html import escape

import pandas as pd
import streamlit as st

from modules import auth, db, nav
from views.common import erp, scaffold
from views.master import (
    TOKENS,
    DraftState,
    Readiness,
    ReadinessState,
    empty_state,
    icon_toolbar_specs,
    sheet_head,
    show_flash,
)

_STATE = DraftState("nm_eval")
_PAGE_ID = _STATE.page_id  # erp.top_action_bar/detail_actions 위젯 key 스코프(동일 page_id).

# 이 화면이 다루는 "평가 대기" 상태 — 파사드 NEAR_MISS_STATUSES 의 부분집합.
# db.evaluate_near_miss 의 _NEAR_MISS_PRE_EVAL_STATES 와 같은 집합(소스 오브 트루스는
# db.py 이며 여기서는 화면 필터링용으로 상수만 복제한다).
_PENDING_STATUSES = ("SUBMITTED", "IN_REVIEW")

_STATUS_LABEL = {
    "SUBMITTED": "제출됨",
    "IN_REVIEW": "검토중",
    "EVALUATED": "평가완료",
    "REJECTED": "반려",
    "CLOSED": "종결",
}
# 상태 색(이중부호화 — 라벨 텍스트는 항상 함께 표시되므로 색은 보조 신호). 기준정보 색
# 토큰(views/master/style.py TOKENS)을 재사용해 새 색을 만들지 않는다(near_miss_view 와 동일).
_STATUS_COLOR = {
    "SUBMITTED": TOKENS["info"],
    "IN_REVIEW": TOKENS["gold"],
    "EVALUATED": TOKENS["success"],
    "REJECTED": TOKENS["danger"],
    "CLOSED": TOKENS["ink-3"],
}

_NOT_READY_MSG = (
    "아차사고 스키마가 준비되지 않아 평가를 진행할 수 없습니다(조회만 가능). "
    "스키마를 적용한 뒤 다시 시도하세요."
)
_PROBE_ERROR_MSG = (
    "아차사고 스키마 상태 확인 실패 — 재확인이 필요합니다(확인 전까지 평가는 차단됩니다)."
)
_STALE_MARK = "이미 변경"  # db._NEAR_MISS_STALE_MESSAGE 원문 일부 — kind 분기용(warning vs error).

# 큐 표시 열 — 첫 열은 사람이 읽는 식별자(작업명), 상태는 색+한글 라벨. 상세에 이미 나오는
# 제안등급은 큐에서 빼 @1024 좁은 목록 컬럼의 가로 스크롤을 없앤다(불필요 메타열 제거).
_QUEUE_COLS = ["작업명", "신고자", "발생일", "상태"]
_KEY_FIELD = "_report_id"  # 숨김 자연키 열(선택 반환값) — 표시 컬럼을 오염시키지 않는다.
# 폭 합(첫 열 minWidth + 나머지 고정폭)을 좁은 목록 컬럼(@1024 ≈ 420px)에 맞춰 가로
# 스크롤 0 을 보장한다: 128(min) + 104 + 94 + 84 = 410 ≤ 뷰포트. flex 작업명이 잔여를 흡수.
_QUEUE_COL_CONFIG = {
    "작업명": {"flex": 1.7, "minWidth": 128, "cellClass": "md-c-left"},
    "신고자": {"flex": 0, "width": 104, "minWidth": 82, "maxWidth": 148, "cellClass": "md-c-left"},
    "발생일": {"flex": 0, "width": 94, "minWidth": 82, "maxWidth": 116,
              "cellClass": "md-c-center"},
    "상태": {"flex": 0, "width": 84, "minWidth": 74, "maxWidth": 108,
            "cellClass": "md-c-center"},
}

_SEL_KEY = "nm_eval_selected_id"  # 상세 패널에 열린 보고서 id(문자열). 케이스 이탈 시 pop.


def render(user: dict) -> None:
    band = erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="평가 관리",
        desc="등록된 아차사고를 검토해 등급을 확정하거나 반려합니다.",
        breadcrumb="아차사고 › 평가 관리",
        badges=scaffold.mode_badge(),
        toolbar="icons",
    )
    # 상단 파랑 밴드 아이콘 툴바(공통 표준). 이 화면의 page-scope 조회 액션은 새로고침
    # 뿐이다 — search 아이콘 클릭이 유발하는 rerun 만으로 _load_pending_reports() 가 매
    # 렌더 무조건 재조회한다(구 pill 과 동일 — on_click 없이 클릭=rerun). 평가확정·반려
    # (쓰기)는 상세 패널 scope 액션 소관이라 밴드 추가·삭제·저장은 N/A(shaded).
    if band is not None:
        band.render_icons(icon_toolbar_specs(
            _PAGE_ID, info_content=nav.page_desc("near_miss_evaluate"),
            add={"key": f"{_PAGE_ID}__add_na", "disabled": True,
                 "help": "이 화면에서는 사용하지 않습니다"},
            refresh={"key": f"{_PAGE_ID}_refresh", "help": "새로고침", "on_click": None},
            delete={"key": f"{_PAGE_ID}__del_na", "disabled": True,
                    "help": "이 화면에서는 사용하지 않습니다"},
            save={"key": f"{_PAGE_ID}__save_na", "disabled": True,
                  "help": "이 화면에서는 사용하지 않습니다"},
        ))
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

    # page-scope 조회 액션(새로고침)은 상단 밴드 아이콘으로 이전했다(render 의 render_icons).
    # 아이콘 클릭이 유발하는 rerun 만으로 아래 _load_pending_reports() 가 매 렌더 무조건
    # 재조회하므로 별도 배선이 필요 없다(인페이지 pill 제거).

    try:
        reports = _load_pending_reports()
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"평가 대기 목록을 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("평가 대기 목록을 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    # 상세는 판단 워크플로형이라 §0.6 강제(상세 폭 ≥600px)를 만족하도록 목록 40%·상세 60%로
    # 분할한다(1366 기준 상세 ≈660px). 목록은 4열로 좁혀도 첫 열(작업명) flex 로 식별성을 유지한다.
    list_col, detail_col = erp.master_detail_frame(list_ratio=1.0, detail_ratio=1.5)
    selected_id = st.session_state.get(_SEL_KEY)
    with list_col:
        picked = _render_queue(reports, selected_id)
    # 선택을 상세 렌더 **전에** 소비한다 — select_grid 의 selectionChanged rerun 이 이미
    # 일어난 run 이므로 여기서 세션만 갱신하면 추가 st.rerun 없이 곧바로 상세를 그린다.
    if picked is not None and picked != selected_id:
        st.session_state[_SEL_KEY] = picked
        selected_id = picked
    with detail_col:
        _render_detail(user, readiness, selected_id)


# ---------- 데이터 적재 ----------
def _load_pending_reports() -> pd.DataFrame:
    """활성 아차사고 중 평가 대기(SUBMITTED/IN_REVIEW)만. 단일 status 필터만 지원하는
    파사드 계약이라 두 상태는 여기서 클라이언트 측으로 골라낸다."""
    df = db.get_near_miss_reports({})
    if df is None or df.empty:
        return df
    mask = df["status"].astype(str).isin(_PENDING_STATUSES)
    return df[mask].reset_index(drop=True)


def _reporter_label(emp_no) -> str:
    emp_no = str(emp_no or "").strip()
    if not emp_no:
        return ""
    try:
        record = db.find_user_by_emp_no(emp_no)
    except Exception:
        # 이름 라벨링은 부가 정보 — 조회 실패로 큐/상세 렌더 전체를 막지 않고 사번만 표시한다.
        return emp_no
    name = str(record.get("name") or "").strip() if record else ""
    return f"{name}({emp_no})" if name else emp_no


def _queue_rows(df: pd.DataFrame) -> pd.DataFrame:
    """큐 표시 프레임 — 숨김 자연키(_report_id) + 표시 4열(작업명·신고자·발생일·상태)."""
    cols = [_KEY_FIELD, *_QUEUE_COLS]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    frame = df.sort_values("incident_date", ascending=False, kind="stable").reset_index(drop=True)
    rows = pd.DataFrame({
        _KEY_FIELD: frame["id"].astype(str),
        "작업명": frame["work_name"].fillna("").astype(str),
        "신고자": frame["reporter_emp_no"].map(_reporter_label),
        "발생일": frame["incident_date"].fillna("").astype(str),
        "상태": frame["status"].astype(str).map(lambda s: _STATUS_LABEL.get(s, s)),
    })
    return rows[cols].reset_index(drop=True)


# ---------- 큐 그리드(단일 선택) ----------
def _render_queue(reports: pd.DataFrame, selected_id) -> str | None:
    """평가 대기 큐를 단일 선택 목록으로 렌더하고 선택된 보고서 자연키를 돌려준다.

    편집 그리드가 아니라 ``erp.select_grid``(네이티브 single-selection) — 행 클릭으로
    케이스를 고르면 체크 마커 + 배경 틴트로 이중부호화되고, 선택 자연키(_report_id)를
    반환한다(정렬·필터 후 위치 비의존)."""
    rows = _queue_rows(reports)
    sheet_head("평가 대기 큐", count=len(rows))

    # 상태 색 규칙(대기 두 상태만) — 한글 라벨 → 색. 텍스트 라벨은 항상 유지(색은 보조).
    status_rules = {_STATUS_LABEL[s]: _STATUS_COLOR[s] for s in _PENDING_STATUSES}
    return erp.select_grid(
        rows, key=f"{_PAGE_ID}_queue", key_field=_KEY_FIELD,
        columns=_QUEUE_COLS, selected_key=selected_id,
        col_config=_QUEUE_COL_CONFIG,
        color_rules={"상태": status_rules},
    )


# ---------- 상세 패널 ----------
# 상태→색/라벨(도메인 매핑)은 이 화면이 소유하고, 배지·메타·전폭 필드의 **표시**는 중립 kit
# 순수 primitive(erp.status_badge_html/meta_col_html/field_block)에 위임한다(§0.3, 복제 제거).
def _status_badge_html(status: str) -> str:
    """상태 배지 — 도메인 매핑(색+한글 라벨)을 kit 순수 표시 primitive 로 렌더(이중부호화)."""
    label = _STATUS_LABEL.get(status, status)
    color = _STATUS_COLOR.get(status, TOKENS["ink-2"])
    return erp.status_badge_html(label, color)


def _render_detail(user: dict, readiness: ReadinessState, selected_id) -> None:
    if not selected_id:
        erp.detail_empty("케이스를 선택하세요", "왼쪽 큐에서 행을 클릭하면 상세 내용이 여기에 표시됩니다.")
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
    if report is None or status not in _PENDING_STATUSES:
        # 다른 평가자가 먼저 처리했거나(EVALUATED/REJECTED/CLOSED) 삭제됨 — stale 선택 해제
        # (상세와 _SEL_KEY 동시 해제, 큐도 자연키 불일치로 선택 마커가 함께 풀린다).
        st.session_state.pop(_SEL_KEY, None)
        erp.detail_empty(
            "이 케이스는 더 이상 대기 중이 아닙니다",
            "다른 사용자가 먼저 처리했을 수 있습니다. 목록을 새로고침한 뒤 다시 선택하세요.",
        )
        return

    # ── 상단: 보고번호(제목 §2 20/700) + 상태 배지 ──
    report_no = escape(str(report.get("report_no") or "-"))
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:10px;margin:2px 0 8px;'>"
        f"<span style='font-size:20px;font-weight:700;color:{TOKENS['ink']};"
        f"line-height:1.2;'>{report_no}</span>{_status_badge_html(status)}</div>",
        unsafe_allow_html=True,
    )

    # ── 짧은 메타 2열(단일 st.columns(2), 중첩 1회) ──
    proposed = str(report.get("proposed_grade") or "")
    left_pairs = [
        ("신고자", _reporter_label(report.get("reporter_emp_no"))),
        ("발생일", str(report.get("incident_date") or "-")),
    ]
    cause = str(report.get("cause_code") or "")
    cause_detail = str(report.get("cause_detail") or "")
    cause_val = cause + (f" · {cause_detail}" if cause_detail else "")
    right_pairs = [
        ("부서", str(report.get("dept_code") or "-")),
        ("제안등급", proposed or "없음"),
    ]
    mc1, mc2 = st.columns(2)
    mc1.markdown(erp.meta_col_html(left_pairs), unsafe_allow_html=True)
    mc2.markdown(erp.meta_col_html(right_pairs), unsafe_allow_html=True)

    # ── 판단 컨텍스트(§0.6 강제: 접지 않고 노출) — 평가 결정에 필요한 핵심 서술을 상세에
    #    상시 노출한다. 작업명·사고 내용·작업 내용·대책·현장 설명·원인은 등급 확정/반려
    #    판단의 근거이므로 expander 로 숨기지 않는다(참조성 첨부만 아래 접기 유지). ──
    erp.field_block("작업명", str(report.get("work_name") or ""))
    erp.field_block("사고 내용", str(report.get("incident_content") or ""))
    erp.field_block("작업 내용", str(report.get("work_content") or ""))
    erp.field_block("대책", str(report.get("countermeasure") or ""))
    erp.field_block("현장 설명", str(report.get("site_description") or ""))
    if cause_val.strip():
        erp.field_block("원인", cause_val)

    # ── 평가 워크플로 클러스터(등급 select + 사유 + scope 액션) — 판단 컨텍스트 바로 뒤 ──
    st.markdown(
        f"<div style='border-top:1px solid {TOKENS['line']};margin:12px 0 2px;'></div>",
        unsafe_allow_html=True,
    )
    grades = list(db.NEAR_MISS_GRADES)
    default_idx = grades.index(proposed) if proposed in grades else 0
    # 확정 등급은 짧은 코드값(S–D) — 내용 맞춤 폭(§0.6 강제: 전폭 컨트롤 금지).
    grade = st.selectbox("확정 등급", grades, index=default_idx, key=f"nm_grade_{selected_id}",
                         width=160)

    can_write = readiness.write_enabled
    reason = st.text_area(
        "반려 사유(반려 시 필수)", key=f"nm_reason_{selected_id}", height=56, disabled=not can_write,
    )
    # 보완요청 전용 사유(반려와 별개 필드·별개 의미: 보완요청=보고자 재작성 요청, 반려=종결분기).
    # IN_REVIEW 에서만 의미가 있어 그 외 상태에서는 입력을 비활성화한다.
    revision_reason = st.text_area(
        "보완요청 사유(보완요청 시 필수)", key=f"nm_revreason_{selected_id}", height=56,
        disabled=(not can_write) or status != "IN_REVIEW",
    )

    # 상세 패널 scope 액션(§0.4) — 실제 쓰기는 이 두 버튼만 담당한다(page 액션바에는
    # 없음). disabled/help 판정은 여기서 그대로 계산해 넘기고, erp.detail_actions 는
    # 순수 UI(버튼 렌더 + 클릭 반환)만 담당한다 — facade 호출·current_user 전달·
    # 오류/stale 처리는 이 화면(아래 클릭 분기 + ``_run_action``)이 그대로 소유한다.
    # 검토착수(SUBMITTED→IN_REVIEW): 아직 검토에 착수하지 않은(SUBMITTED) 케이스에서만
    # 활성. 큐는 SUBMITTED/IN_REVIEW 만 담으므로 IN_REVIEW 는 이미 착수한 상태라 비활성.
    # 검토착수는 전용 사유 필드 없이 상태만 전이한다(보완요청은 아래 별도 버튼·전용 사유).
    review_disabled = (not can_write) or status != "SUBMITTED"
    if not can_write:
        review_help = readiness.message
    elif status != "SUBMITTED":
        review_help = "이미 검토에 착수한 케이스입니다."
    else:
        review_help = None

    eval_disabled = not can_write
    eval_help = None if can_write else readiness.message

    reject_disabled = (not can_write) or not str(reason or "").strip()
    reject_help = readiness.message if not can_write else (
        None if str(reason or "").strip() else "반려 사유를 입력하세요."
    )

    # 보완요청(IN_REVIEW→SUBMITTED): 검토중 케이스만 활성, 사유 필수. 반려와 별도 버튼·의미.
    revision_disabled = (not can_write) or status != "IN_REVIEW" or not str(revision_reason or "").strip()
    if not can_write:
        revision_help = readiness.message
    elif status != "IN_REVIEW":
        revision_help = "검토중(IN_REVIEW) 케이스만 보완요청할 수 있습니다."
    elif not str(revision_reason or "").strip():
        revision_help = "보완요청 사유를 입력하세요."
    else:
        revision_help = None

    # 종결(EVALUATED→CLOSED)은 이 평가 대기 화면의 책임이 아니다 — 큐가 SUBMITTED/IN_REVIEW
    # 만 담아 여기서는 항상 비활성일 수밖에 없었다. 종결 UI 는 향후 개선조치 관리 화면에서
    # 재설계하며(별도 제품 결정 — BACKLOG 추적), db.py 의 EVALUATED→CLOSED 전이 능력
    # 자체는 데이터 계약으로 그대로 유지한다(이 화면에서 버튼만 제거).
    clicks = erp.detail_actions(_PAGE_ID, [
        ("검토착수", "default", review_disabled, review_help),
        ("평가확정", "primary", eval_disabled, eval_help),
        ("보완요청", "default", revision_disabled, revision_help),
        ("반려", "default", reject_disabled, reject_help),
    ])

    # ── 참조성 첨부(사진)만 기본 접힘으로 남긴다 — 판단 컨텍스트(서술)는 위에 상시 노출했고,
    #    첨부 뷰어는 미구현이라 자리표시만 접어 상세 높이를 절약한다(§0.4 st.expander 네이티브). ──
    photos = report.get("photo_paths") or []
    with st.expander(f"첨부 사진 ({len(photos)}건)", expanded=False):
        if photos:
            st.caption(f"첨부 사진 {len(photos)}건 (뷰어 미구현 — 자리표시)")
        else:
            st.caption("첨부된 사진이 없습니다.")

    if clicks.get("검토착수"):
        # 검토착수 후 케이스는 IN_REVIEW 로 여전히 큐(대기)에 남는다. _run_action 은 기존
        # 패턴대로 선택을 닫고 성공 배너를 띄운다 — 목록에서 다시 선택해 평가/반려를 이어간다.
        _run_action(user, "검토착수", lambda: db.update_near_miss_status(
            selected_id, "IN_REVIEW", current_user=auth.get_current_user(),
        ))
    if clicks.get("평가확정"):
        _run_action(user, "평가확정", lambda: db.evaluate_near_miss(
            selected_id, grade, current_user=auth.get_current_user(),
        ))
    if clicks.get("보완요청"):
        # 보완요청: IN_REVIEW→SUBMITTED 반송 + 사유 서버기록(보고자 재작성 요청). 반려와 별개.
        _run_action(user, "보완요청", lambda: db.request_near_miss_revision(
            selected_id, revision_reason, current_user=auth.get_current_user(),
        ))
    if clicks.get("반려"):
        _run_action(user, "반려", lambda: db.update_near_miss_status(
            selected_id, "REJECTED", rejection_reason=reason, current_user=auth.get_current_user(),
        ))


def _flash_kind_for(exc: Exception) -> str:
    """stale 충돌(다른 평가자가 먼저 처리)은 warning, 그 외 검증 실패는 error."""
    return "warning" if _STALE_MARK in str(exc) else "error"


def _run_action(user: dict, label: str, call) -> None:
    """평가/반려 공통 실행 — 예외를 여기서 흡수해 raw traceback 을 노출하지 않는다
    (2단계 배너: 제목 + 파사드 원문 사유, stale 메시지는 가공 없이 그대로 노출)."""
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
    st.session_state.pop(_SEL_KEY, None)  # 처리된 케이스는 큐에서 빠지므로 상세 패널을 닫는다.
    st.rerun()
