"""아차사고 제안서(near-miss) 신청 — 단건 제출 폼(FORM_ENTRY).

종이 양식 "아차사고 제안서"를 화면 폼으로 옮긴 단건 입력·제출 화면이다. 작업자가
현장에서 발견한 아차사고(near-miss)를 작업명·발생원인·사고내용·예방대책과 함께
제출하면 ``status=SUBMITTED`` 로 접수된다. 평가(확정 등급 부여)는 별도 화면·권한이며
이 화면은 신청까지만 담당한다.

신원 계약(중요): 신고자·소속·created_by 는 화면 위젯이 아니라 인증된 세션 사용자
(``auth.get_current_user()``)에서 **서버측으로 확정**한다(``db.create_near_miss_report``
가 payload 의 신원·상태 필드를 무시하고 세션 사번으로 다시 도출). 화면은 신원을 읽기
전용으로 **표시만** 하고 payload 에 신원 필드를 넣지 않는다 — 타인 명의 위조 방지.

사진 첨부는 GATED: Supabase Storage 버킷이 아직 없어 실제 업로드는 승인 후 활성화한다.
지금은 촬영/선택 UI 만 노출하고, 저장 payload 의 ``photo_paths`` 는 빈 배열로 보낸다
(존재하지 않는 Storage 호출을 지어내지 않는다).
"""
# DESIGN.md §0 화면 유형 규약 — 폼 입력형.
SCREEN_ARCHETYPE = "FORM_ENTRY"

from datetime import date
from html import escape

import streamlit as st

from modules import auth, db
from views.common import scaffold
from views.master import PersistResult, banner, ledger_banner

_PAGE_ID = "near_miss_submit"

# 표시용 라벨(display-only). 실제로 저장·검증되는 것은 통제 코드(NEAR_MISS_CAUSE_CODES/
# NEAR_MISS_GRADES)이며, 아래 라벨은 선택 위젯의 사람이 읽는 표기일 뿐이다. 코드에 없는
# 값은 코드 그대로 노출한다(신규 코드가 추가돼도 깨지지 않게).
_CAUSE_LABELS = {
    "JAM": "끼임",
    "FALL": "추락",
    "DROP": "낙하물",
    "HIT": "부딪힘·충돌",
    "SLIP": "미끄러짐·넘어짐",
    "BURN": "화상·고온",
    "PINCH": "협착",
    "ETC": "기타",
}

# 스캐폴드 헤더(master 공통 CSS) 위에 얹는 폼 전용 소량 스코프 CSS. 장식이 아니라
# 읽기전용 신원 행·섹션 라벨·필수 표식의 밀도/대비만 조정한다(ERP CRUD 원칙).
_FORM_CSS = """
<style>
.nm-identity { display:flex; flex-wrap:wrap; gap:.5rem 1.4rem; align-items:baseline;
  background:var(--ms-surface-2); border:1px solid var(--ms-line); border-radius:8px;
  padding:.6rem .85rem; margin:.35rem 0 .2rem; }
.nm-identity .nm-id-item { display:flex; gap:.4rem; align-items:baseline; font-size:.82rem; }
.nm-identity .nm-id-k { color:var(--ms-ink-2); font-weight:600; }
.nm-identity .nm-id-v { color:var(--ms-ink); font-weight:700; }
.nm-identity .nm-id-lock { margin-left:auto; color:var(--ms-ink-3); font-size:.72rem; white-space:nowrap; }
.nm-sec { font-size:.82rem; font-weight:700; color:var(--ms-ink); letter-spacing:-.01em;
  margin:.9rem 0 .1rem; padding-top:.5rem; border-top:1px solid var(--ms-line); }
.nm-sec:first-of-type { border-top:none; padding-top:0; }
.nm-note { font-size:.75rem; color:var(--ms-ink-2); margin:.15rem 0 .3rem; line-height:1.35; }
</style>
"""


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _dept_display(dept_code: str) -> str:
    """소속 표시 문자열: 부서명(코드) — 코드만 있으면 코드, 없으면 '미지정'."""
    code = _clean(dept_code)
    if not code:
        return "미지정"
    try:
        depts = db.get_departments()
        hit = depts[depts["dept_code"].astype(str).str.strip() == code]
        if not hit.empty:
            name = _clean(hit.iloc[0].get("dept_name"))
            if name:
                return f"{name} ({code})"
    except Exception:  # noqa: BLE001 — 표시 폴백. 조회 실패로 폼을 막지 않는다.
        pass
    return code


def _identity_row(user: dict) -> None:
    """신고자·소속을 읽기 전용으로 표시한다(편집 입력 아님 — 서버가 세션에서 확정)."""
    name = _clean(user.get("name")) or "(이름 미확인)"
    emp_no = _clean(user.get("emp_no"))
    dept = _dept_display(user.get("dept_code"))
    st.markdown(
        "<div class='nm-identity'>"
        f"<span class='nm-id-item'><span class='nm-id-k'>신고자</span>"
        f"<span class='nm-id-v'>{escape(name)}</span></span>"
        f"<span class='nm-id-item'><span class='nm-id-k'>사번</span>"
        f"<span class='nm-id-v'>{escape(emp_no)}</span></span>"
        f"<span class='nm-id-item'><span class='nm-id-k'>소속</span>"
        f"<span class='nm-id-v'>{escape(dept)}</span></span>"
        "<span class='nm-id-lock'>로그인 정보로 자동 지정 · 수정 불가</span>"
        "</div>",
        unsafe_allow_html=True,
    )


def _readiness_gate() -> bool:
    """아차사고 스키마 준비 상태를 확인하고 배너를 렌더한다. 제출 가능하면 True.

    sample 은 항상 READY. supabase 는 3-state(READY/NOT_READY/PROBE_ERROR)로, 미적용·
    확인 실패면 제출을 막고(fail-closed) 사유 배너를 노출한다.
    """
    probe = db.near_miss_schema_probe()
    if probe == "READY":
        return True
    if probe == "NOT_READY":
        banner("warn", "아차사고 스키마가 아직 준비되지 않아 신청을 저장할 수 없습니다. "
                       "스키마 적용 후 다시 시도하세요.")
    else:  # PROBE_ERROR
        banner("danger", "아차사고 스키마 상태를 확인하지 못했습니다. 잠시 후 다시 시도하세요.")
    return False


def render(user: dict) -> None:
    # ── 헤더 크롬(§0 FORM_ENTRY): 브레드크럼 → 제목·모드 배지 ─────────────────
    # nav 라우팅이 아직 연결되지 않아(B2) page_chrome_for 대신 명시 문자열로 헤더를
    # 만든다. 라우팅 연결 후에는 page_chrome_for(_PAGE_ID, ...) 로 통일 가능하다.
    scaffold.page_chrome(
        SCREEN_ARCHETYPE,
        title="아차사고 신청",
        desc="현장에서 발견한 아차사고(near-miss)를 제안서로 접수합니다. 접수 후 상태는 제출됨(SUBMITTED)입니다.",
        breadcrumb="안전관리 › 아차사고 신청",
        badges=scaffold.mode_badge(),
    )
    st.markdown(_FORM_CSS, unsafe_allow_html=True)

    can_submit = _readiness_gate()

    # ── 입력 폼 본문(라벨드 필드 + 첨부) ─────────────────────────────────────
    with st.form("near_miss_submit_form", clear_on_submit=False):
        st.markdown("<div class='nm-sec'>신고자 정보</div>", unsafe_allow_html=True)
        _identity_row(user)

        st.markdown("<div class='nm-sec'>작업·발생 개요</div>", unsafe_allow_html=True)
        c1, c2 = st.columns([2, 1])
        with c1:
            work_name = st.text_input("작업명", max_chars=120,
                                      placeholder="예: 3라인 컨베이어 벨트 점검")
        with c2:
            incident_date = st.date_input("발생일", value=date.today(),
                                          format="YYYY-MM-DD")
        c3, c4 = st.columns(2)
        with c3:
            grade_opts = [""] + list(db.NEAR_MISS_GRADES)
            proposed_grade = st.selectbox(
                "제안 등급", grade_opts, index=0,
                format_func=lambda g: "— 선택 안 함 —" if g == "" else g,
                help="신고자가 제안하는 위험 등급(S~D). 확정 등급은 평가 단계에서 부여됩니다.",
            )
        with c4:
            cause_opts = [""] + list(db.NEAR_MISS_CAUSE_CODES)
            cause_code = st.selectbox(
                "발생원인", cause_opts, index=0,
                format_func=lambda c: "— 선택 —" if c == "" else f"{_CAUSE_LABELS.get(c, c)} ({c})",
            )
        cause_detail = st.text_input("발생원인 상세", max_chars=200,
                                     placeholder="원인을 구체적으로 적어 주세요(선택)")

        st.markdown("<div class='nm-sec'>세부 내용</div>", unsafe_allow_html=True)
        work_content = st.text_area("작업내용", height=90,
                                    placeholder="어떤 작업을 하고 있었는지")
        incident_content = st.text_area("사고내용", height=110,
                                        placeholder="무슨 일이 있었는지(아차사고 상황)")
        countermeasure = st.text_area("예방대책", height=90,
                                      placeholder="재발을 막기 위한 제안 대책")
        site_description = st.text_area("작업현장 상황설명", height=90,
                                        placeholder="현장 상황·주변 환경(선택)")

        st.markdown("<div class='nm-sec'>사진 첨부</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='nm-note'>사진 업로드는 승인 후 활성화됩니다. 지금은 촬영·선택만 "
            "가능하며 제출해도 사진은 저장되지 않습니다.</div>",
            unsafe_allow_html=True,
        )
        pc1, pc2 = st.columns(2)
        with pc1:
            camera_shot = st.camera_input("현장 촬영(모바일)")
        with pc2:
            uploaded = st.file_uploader("사진 선택(PC)", type=["png", "jpg", "jpeg"],
                                        accept_multiple_files=True)

        submitted = st.form_submit_button("제안서 제출", type="primary",
                                          disabled=not can_submit, use_container_width=False)

    # ── 제출 처리 + 저장 결과 배너(§0 순서: 폼 → 제출 → 결과 배너) ────────────
    if not submitted:
        return

    # 첨부 개수(안내용). 실제 저장은 GATED — photo_paths 는 빈 배열로 보낸다.
    photo_count = (1 if camera_shot is not None else 0) + len(uploaded or [])

    missing = _validate({
        "work_name": work_name,
        "cause_code": cause_code,
        "incident_content": incident_content,
        "incident_date": incident_date,
    })
    if missing:
        banner("danger", "필수 항목을 입력하세요: " + ", ".join(missing))
        return

    payload = {
        "work_name": _clean(work_name),
        "proposed_grade": proposed_grade or None,
        "cause_code": cause_code,
        "cause_detail": _clean(cause_detail),
        "incident_date": incident_date.isoformat(),
        "work_content": _clean(work_content),
        "incident_content": _clean(incident_content),
        "countermeasure": _clean(countermeasure),
        "site_description": _clean(site_description),
        "photo_paths": [],  # GATED: Storage 버킷 없음 — 승인 후 활성화.
    }

    _persist_and_report(payload, photo_count)


def _validate(fields: dict) -> list[str]:
    """필수 항목 검증. 비어 있는 항목의 한글 라벨 목록을 반환한다."""
    labels = {
        "work_name": "작업명",
        "cause_code": "발생원인",
        "incident_content": "사고내용",
        "incident_date": "발생일",
    }
    missing: list[str] = []
    for key, label in labels.items():
        value = fields.get(key)
        if value in (None, "") or (isinstance(value, str) and not value.strip()):
            missing.append(label)
    return missing


def _persist_and_report(payload: dict, photo_count: int) -> None:
    """저장을 시도하고 lifecycle PersistResult/ledger_banner 패턴으로 결과를 표시한다.

    two-tier: 도메인 검증 오류(ValueError, 사용자 안전 문구)는 그대로 노출하고, 그 외
    예기치 못한 예외는 원문(raw)을 노출하지 않고 '결과 불명' 배너로 접는다.
    """
    try:
        record = db.create_near_miss_report(payload, current_user=auth.get_current_user())
    except ValueError as exc:  # 파사드의 도메인 검증 메시지는 사용자 안전 문구다.
        ledger_banner(PersistResult.failure(_PAGE_ID, [payload.get("work_name") or "신청"],
                                            str(exc), retryable=True))
        return
    except Exception:  # noqa: BLE001 — raw 예외 문구 비노출, 결과 불명으로 접는다.
        ledger_banner(PersistResult.unresolved(
            _PAGE_ID, "저장 결과를 확인할 수 없습니다. 목록을 재조회한 뒤 다시 시도하세요."))
        return

    report_no = _clean((record or {}).get("report_no")) or "(채번 확인 필요)"
    ledger_banner(PersistResult.success(_PAGE_ID, [report_no]))
    extra = f" · 첨부 {photo_count}장은 저장되지 않았습니다(사진 기능 승인 대기)" if photo_count else ""
    banner("success",
           f"아차사고 제안서를 접수했습니다. 접수번호 {report_no} · 상태 제출됨(SUBMITTED){extra}")
