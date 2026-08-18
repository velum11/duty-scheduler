"""아차사고 UI 게이트 회귀 — 능력 통일(nav)·평가 평가착수·stats 보고서 종결률·
WORKLIST 골격(DESIGN.md §2).

007 스키마와 무관하게 즉시 구현된 UI 계약을 고정한다(비회귀 그물):
  1) nav 능력 게이트 — near_miss_improvement 는 '배정 기반' 접근 능력
     (CAP_ACCESS_NEAR_MISS_IMPROVEMENT)으로 노출하고, 평가 관리는 평가 능력
     (CAP_EVALUATE_NEAR_MISS)으로 노출한다(두 능력 분리 — Phase2). 정적 roles 없음.
     USER_MENU(평면)·route guard(nav.allowed)가 동일 caps 로 노출·차단 일치한다.
  2) 평가 관리(near_miss_evaluate) — 상세 scope 액션에 평가착수(SUBMITTED→IN_REVIEW) 배선,
     status=="SUBMITTED" 에서만 활성. EVALUATED 종결 버튼은 이 화면에 없음(개선조치 소관).
  3) stats(near_miss_stats) — _closure_rate_label 은 CLOSED/(CLOSED+EVALUATED), 0분모 방어('—'),
     명칭은 정확히 '보고서 종결률'('CAPA 종결률' 금지).
  12) **WORKLIST 골격**(2026-08-18 §7.1 이관) — 평가 관리·개선조치 관리 두 화면이
     ``erp.master_detail_frame(list_ratio=1, detail_ratio=2)`` 실호출 + 상태 탭 +
     ``erp.select_list`` 목록을 갖고, **지표 타일(erp.metric_strip)이 없다**(§4-1).
     종전 이 자리에는 "구 큐 칩 스트립 유지"를 지키는 **과도기 검사**가 있었다 — 유형만
     WORKLIST 로 바뀌고 레이아웃은 구 골격이던 시기의 현상 유지 검사였고, 레이아웃 이관과
     함께 **반대 방향으로 재작성**했다.
  13) 어휘(§3.6)·상태 결과 표기(§3.3)·경과일(§7.2-4)·보완요청 007 게이트(§7.4 P1).

실행: PYTHONUTF8=1 C:\\dev\\workops\\.venv\\Scripts\\python.exe scripts/test_near_miss_ui_gates.py
"""
from __future__ import annotations

import inspect
import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

import streamlit as st  # noqa: E402

from modules import auth, db, nav  # noqa: E402
from views import near_miss_evaluate as nme  # noqa: E402
from views import near_miss_improvement as nmi  # noqa: E402
from views import near_miss_my as nmy  # noqa: E402
from views import near_miss_stats as nms  # noqa: E402
from views import near_miss_submit as nmsub  # noqa: E402
from views import near_miss_view as nmv  # noqa: E402
from views import workspace as wsp  # noqa: E402

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name}")


CAPS = {nav.CAP_EVALUATE_NEAR_MISS}                         # 평가 능력만.
IMPR_CAPS = {nav.CAP_ACCESS_NEAR_MISS_IMPROVEMENT}          # 개선조치 접근 능력만(배정 기반).
ALL_CAPS = CAPS | IMPR_CAPS


# ===== 1) nav 능력 게이트 (개선조치=접근 능력 / 평가 관리=평가 능력, 분리) =====
print("nav 능력 게이트 (개선조치 접근 능력 분리)")
# 개선조치 child 는 접근 능력 capability 로 노출되고 static ADMIN roles 는 없다.
_child = next(c for g in nav.MENU_GROUPS if g["id"] == "near_miss"
              for c in g["children"] if c["id"] == "near_miss_improvement")
check("개선조치 child capability=CAP_ACCESS_NEAR_MISS_IMPROVEMENT",
      _child.get("capability") == nav.CAP_ACCESS_NEAR_MISS_IMPROVEMENT)
check("개선조치 child 에 static ADMIN roles 제거", tuple(_child.get("roles", ())) == ())
# 평가 관리 child 는 여전히 평가 능력(두 능력 분리 회귀).
_eval_child = next(c for g in nav.MENU_GROUPS if g["id"] == "near_miss"
                   for c in g["children"] if c["id"] == "near_miss_evaluate")
check("평가 관리 child capability=CAP_EVALUATE_NEAR_MISS",
      _eval_child.get("capability") == nav.CAP_EVALUATE_NEAR_MISS)

# route guard 정합 — 개선조치는 접근 능력으로만 노출/라우팅, 평가 능력만으론 불충분(분리).
check("ADMIN(개선조치 caps) 개선조치 allowed", nav.allowed("near_miss_improvement", "ADMIN", IMPR_CAPS))
check("MANAGER(개선조치 caps) 개선조치 allowed", nav.allowed("near_miss_improvement", "MANAGER", IMPR_CAPS))
check("caps 없는 role 은 개선조치 차단(ADMIN caps=None)",
      not nav.allowed("near_miss_improvement", "ADMIN", None))
check("평가 능력만으론 개선조치 미노출(능력 분리)",
      not nav.allowed("near_miss_improvement", "ADMIN", CAPS))
# 반대로 평가 관리는 평가 능력으로 노출되고 개선조치 접근능력만으론 불충분.
check("평가 관리는 평가 능력으로 allowed", nav.allowed("near_miss_evaluate", "ADMIN", CAPS))
check("개선조치 접근능력만으론 평가 관리 미노출",
      not nav.allowed("near_miss_evaluate", "ADMIN", IMPR_CAPS))

# USER_MENU(평면) — 개선조치는 접근 능력, 평가 관리는 평가 능력으로만 노출.
user_ids_no_caps = {i["id"] for i in nav.user_menu(None)}
user_ids_impr = {i["id"] for i in nav.user_menu(IMPR_CAPS)}
user_ids_eval = {i["id"] for i in nav.user_menu(CAPS)}
check("USER_MENU 에 개선조치 정의 존재",
      any(i["id"] == "near_miss_improvement" for i in nav.USER_MENU))
check("무능력 USER 는 개선조치·평가 관리 미노출",
      not ({"near_miss_improvement", "near_miss_evaluate"} & user_ids_no_caps))
check("접근 능력 USER 는 개선조치 노출(배정 기반)",
      "near_miss_improvement" in user_ids_impr)
check("접근 능력만으론 평가 관리 미노출(능력 분리)",
      "near_miss_evaluate" not in user_ids_impr)
check("평가 능력 USER 는 평가 관리 노출", "near_miss_evaluate" in user_ids_eval)
check("배정/안전담당자 USER route guard: 개선조치 allowed",
      nav.allowed("near_miss_improvement", "USER", IMPR_CAPS))
check("무능력 USER route guard: 개선조치 차단",
      not nav.allowed("near_miss_improvement", "USER", None))

# 회귀: 기존 노출 계약 불변(base 4 는 caps 무관 전원, 평가/개선조치만 caps 종속).
check("base 4 항목은 caps 없이도 USER 노출",
      {"near_miss_submit", "near_miss_my", "near_miss_view", "near_miss_stats"} <= user_ids_no_caps)


# ===== 2) 평가 관리 평가착수 배선 =====
# §3.6 어휘: 시작 액션은 '평가착수'다(구 '검토착수' 폐기 — 화면명·역할·완료 상태가 전부
# '평가' 어근인데 시작 액션만 '검토'였다). 영문 코드값 IN_REVIEW 는 그대로 둔다.
print("평가 관리 평가착수")
detail_src = inspect.getsource(nme._render_detail)
check("평가착수 scope 액션 라벨 존재", '"평가착수"' in detail_src or "'평가착수'" in detail_src)
check("구 어휘 '검토착수' 잔재 없음", "검토착수" not in detail_src)
check("평가착수 → update_near_miss_status(..., \"IN_REVIEW\", ...)",
      "IN_REVIEW" in detail_src and "update_near_miss_status" in detail_src)
check("평가착수 활성 게이트: status == 'SUBMITTED'",
      'status != "SUBMITTED"' in detail_src)
check("평가착수는 current_user=auth.get_current_user() 전달(신원 서버측 확정)",
      "current_user=auth.get_current_user()" in detail_src)
# 종결 버튼은 이 화면에 없다(개선조치 소관) — 회귀 방지. detail_actions 튜플에 종결 라벨 없음.
check("평가 화면에 종결 버튼 미도입(detail_actions 라벨 없음)",
      '("종결"' not in detail_src and "'종결'," not in detail_src)
# §3.2 액션 위계 — 평가확정만 primary CTA, 평가착수는 보조(secondary) 버튼.
check("평가확정만 primary CTA(평가착수는 보조 secondary)",
      'st.button("평가확정"' in detail_src and 'type="primary"' in detail_src
      and 'st.button("평가착수"' in detail_src and 'type="secondary"' in detail_src)


# ===== 3) stats 보고서 종결률 =====
print("stats 보고서 종결률")
check("(0,0) → '—'(0분모 방어)", nms._closure_rate_label(0, 0) == "—")
check("(1,1) → 50%", nms._closure_rate_label(1, 1) == "50%")
check("(2,0) → 100%", nms._closure_rate_label(2, 0) == "100%")
check("(0,3) → 0%", nms._closure_rate_label(0, 3) == "0%")
check("(1,2) → 33%(반올림)", nms._closure_rate_label(1, 2) == "33%")
kpi_src = inspect.getsource(nms._kpi_cards_cumulative)
check("KPI 행에 '보고서 종결률' 타일 추가", "보고서 종결률" in kpi_src)
# KPI 타일 라벨 자체에 'CAPA' 명칭을 쓰지 않는다(미확인 종결을 CAPA 완료로 오표기 금지).
check("KPI 타일 라벨에 'CAPA' 명칭 미사용", "CAPA" not in kpi_src)


# ===== 4) stats 기한초과(overdue) 지표 (007 배선·fail-closed) =====
print("stats 기한초과")
check("기한초과 타일 KPI 행에 추가", "기한초과" in kpi_src)
check("overdue None → '—'(007 미준비 방어)", nms._overdue_label(None) == "—")
check("overdue 0 → '0건'(실집계 0 은 표시)", nms._overdue_label(0) == "0건")
check("overdue 4 → '4건'", nms._overdue_label(4) == "4건")
# 집계·권한 판정은 파사드 db.near_miss_overdue_count 가 소유한다(뷰 _overdue_count 제거).
overdue_src = inspect.getsource(nms.db.near_miss_overdue_count)
check("overdue 는 007 readiness 게이트(미준비 None)",
      "near_miss_improvement_schema_probe" in overdue_src and "READINESS_READY" in overdue_src)
check("overdue 조건: 미확인(CONFIRMED 제외) + due_date 과거",
      "CONFIRMED" in overdue_src and "due" in overdue_src)
check("overdue 는 평가자/ADMIN 역할 게이트(일반 USER 미노출)",
      "can_evaluate_near_miss" in overdue_src)
# 뷰는 파사드만 호출하고 개별 개선조치를 직접 순회하지 않는다(권한 게이트 우회 방지).
stats_render_src = inspect.getsource(nms.render)
check("stats 뷰는 overdue 를 파사드로 위임(near_miss_overdue_count)",
      "near_miss_overdue_count" in stats_render_src)


# ===== 5) 개선조치 관리(near_miss_improvement) WORKLIST 폐루프 =====
print("개선조치 관리 CAPA 폐루프")
check("SCREEN_ARCHETYPE == 'WORKLIST'", nmi.SCREEN_ARCHETYPE == "WORKLIST")
render_src = inspect.getsource(nmi.render)
# Phase2: 진입가드는 배정 기반 접근 facade 로(평가 능력 단독이 아니라 담당자·확인자 포함).
check("진입가드: has_near_miss_improvement_access(배정 기반)",
      "has_near_miss_improvement_access" in render_src)
body_src = inspect.getsource(nmi._render_body)
# 이 자리에는 2026-08-18 까지 **과도기 검사**("구 큐 칩 스트립 유지 + master_detail_frame
# 미사용")가 있었다. 유형만 WORKLIST 로 바뀌고 레이아웃은 구 골격이던 시기의 현상 유지
# 검사였고, 레이아웃 이관과 함께 **반대 방향으로 재작성**했다. 구 DESIGN.md §0-2 의
# "좌우 분할 마스터-디테일 금지"는 이유 없는 규칙이라 폐기됐다(부록).
check("구 큐 칩 스트립 폐기(_render_queue_chips 부재)",
      "_render_queue_chips" not in body_src
      and not hasattr(nmi, "_render_queue_chips"))
check("진입 시 첫 건 자동 선택", "ordered[0]" in body_src)
# Phase2: 큐는 actor-aware(list_near_miss_improvements) + 담당자 스코핑(_scope_reports).
impr_for_src = inspect.getsource(nmi._improvements_for)
check("큐 actor-aware(list_near_miss_improvements)", "list_near_miss_improvements" in impr_for_src)
check("담당자 큐 스코핑(_scope_reports)", "_scope_reports" in body_src)

act_src = inspect.getsource(nmi._render_actions)
for label in ("조치 저장", "제출", "확인", "재조치 요청"):
    check(f"scope 액션 라벨 '{label}'", f'"{label}"' in act_src)
check("자기확인 차단 게이트(self_confirm)", "self_confirm" in act_src and "자기확인" in act_src)
check("신원 서버측 확정(current_user=auth.get_current_user())",
      "current_user=auth.get_current_user()" in act_src)
# Phase2: 행단위 역할 variant — 작업(can_work)/검토(can_review)/배정(can_assign)로 버튼 분기.
detail_src2 = inspect.getsource(nmi._render_detail)
check("상세 행단위 인가 판정(can_work/can_review/can_assign)",
      "can_work_improvement" in detail_src2 and "can_review_improvement" in detail_src2
      and "can_evaluate_near_miss" in detail_src2)
check("작업 버튼(조치 저장·제출)은 can_work 게이트", "if can_work" in act_src)
check("확인·재조치·종결은 can_review 게이트", "if can_review" in act_src)
check("배정 저장은 can_assign 기반", "배정 저장" in act_src and "can_assign" in act_src)
form_src = inspect.getsource(nmi._render_capa_form)
# U6: 배정 필드는 can_assign 이 아니거나 사용자 목록 조회 실패 시 잠근다(assign_disabled).
# 의도(배정은 can_assign 만) 보존 + 조회 실패 시 추가 잠금.
check("배정필드는 can_assign(+조회실패) 읽기전용",
      "assign_disabled = (not can_assign) or users_failed" in form_src
      and "disabled=assign_disabled" in form_src)
check("사용자 목록 조회 실패는 배정 잠금+오류 배너로 표면화(U6)",
      "users_failed" in form_src and 'banner("danger"' in form_src)
check("작업필드는 can_work 읽기전용", "disabled=not can_work" in form_src)
close_src = inspect.getsource(nmi._render_close)
check("보고서 종결 라벨 존재", '"보고서 종결"' in close_src)
check("2단계 종결: 확인 세션키 가드", "_CLOSE_CONFIRM_KEY" in close_src)
check("2단계 종결: 종결 확정 + 취소", '"종결 확정"' in close_src and '"취소"' in close_src)
check("불가역 고지 문구", "불가역" in close_src)
check("종결은 close_near_miss_report 파사드로만", "close_near_miss_report" in close_src)
# 007 미적용 fail-closed: 쓰기 활성은 readiness.write_enabled 로만 판정(가짜 성공 없음).
check("쓰기 활성은 readiness.write_enabled 게이트", "readiness.write_enabled" in act_src)


# ===== 6) 평가 보완요청(near_miss_evaluate) — 반려와 별개 =====
print("평가 보완요청")
check("보완요청 scope 액션 라벨 존재", '"보완요청"' in detail_src)
check("보완요청 → request_near_miss_revision 파사드", "request_near_miss_revision" in detail_src)
check("보완요청 활성 게이트: status == 'IN_REVIEW'", 'status != "IN_REVIEW"' in detail_src)
# §1-A 단일 의견 필드(dc 정본) — 반려·보완요청 공용, 각각 의견 필수. 반려=rejection_reason,
# 보완요청=사유로 재사용하되 버튼·facade·의미는 별개(반려≠보완요청).
check("단일 의견 필드 공용(반려=rejection_reason, 보완요청=사유; 각각 필수)",
      "rejection_reason=opinion" in detail_src
      and "opinion," in detail_src
      and "not opinion" in detail_src)
check("반려 버튼 여전히 존재(별도 의미)", '"반려"' in detail_src)
check("보완요청도 current_user 서버측 확정",
      "request_near_miss_revision" in detail_src and "auth.get_current_user()" in detail_src)


# ===== 7) 내 아차사고 보완요청 배너(near_miss_my) — info, 별개 시각 =====
print("내 아차사고 보완요청 배너")
rev_src = inspect.getsource(nmy._render_revision_banner)
check("보완요청 조회 파사드 사용", "get_near_miss_revision_request" in rev_src)
check("보완요청 배너 kind='info'(반려 warn 과 별개 시각)", 'banner("info"' in rev_src)
check("보완요청 문구 사용", "보완요청" in rev_src)
my_detail_src = inspect.getsource(nmy._render_detail)
check("SUBMITTED 에서 보완요청 배너 호출", "_render_revision_banner" in my_detail_src)
check("반려(REJECTED) 배너는 warn 유지(별개 시각)", 'banner("warn"' in my_detail_src)


# ===== 8) P1-4 삭제 부분성공 표면화(near_miss_my) — storage_deleted=False 경고 표면화 =====
print("사진 삭제 부분성공 표면화(storage_deleted)")
# 표면화 배선 정적 확인: _delete_my_photo 가 반환의 storage_deleted 를 읽어 warn 스태시,
# _render_my_photos 가 _flush_photo_msg 로 표시한다.
del_src = inspect.getsource(nmy._delete_my_photo)
check("_delete_my_photo 가 반환을 캡처(res=)", "res = db.delete_near_miss_photo" in del_src)
check("storage_deleted is False 분기 존재", 'res.get("storage_deleted") is False' in del_src)
check("부분성공 경고 문구(정리 지연) 표면화", "정리가 지연" in del_src and '"warn"' in del_src)
check("_render_my_photos 가 결과 문구를 flush(표시)", "_flush_photo_msg" in inspect.getsource(nmy._render_my_photos))

# 행위 검증: 파사드가 storage_deleted=False 를 돌려주면 warn 문구가 세션에 스태시된다.
_rid = "p14test"
_msg_key = f"nm_my_photomsg_{_rid}"
_orig_del = db.delete_near_miss_photo
_orig_user = auth.get_current_user
try:
    db.delete_near_miss_photo = lambda *a, **k: {"photo_paths": [], "storage_deleted": False}
    auth.get_current_user = lambda: {"emp_no": "1003", "role": "USER"}
    st.session_state.pop(_msg_key, None)
    nmy._delete_my_photo(_rid, "near-miss/1/x.jpg")  # st.rerun 은 bare 모드에서 no-op
    _stashed = st.session_state.get(_msg_key)
    check("storage_deleted=False → warn 스태시됨",
          isinstance(_stashed, tuple) and _stashed[0] == "warn" and "정리가 지연" in _stashed[1])
    # 대조군: storage_deleted=True 면 부분성공 경고 없음.
    db.delete_near_miss_photo = lambda *a, **k: {"photo_paths": [], "storage_deleted": True}
    st.session_state.pop(_msg_key, None)
    nmy._delete_my_photo(_rid, "near-miss/1/x.jpg")
    check("storage_deleted=True → 부분성공 경고 없음", st.session_state.get(_msg_key) is None)
finally:
    db.delete_near_miss_photo = _orig_del
    auth.get_current_user = _orig_user
    st.session_state.pop(_msg_key, None)


# ===== 9) DESIGN §2 FORM_ENTRY 골격 — 라벨 열 + 하단 고정 제출 바(near_miss_submit) =====
# 종전 판정("우측 CHECKLIST 패널이 실시간인가")은 §2 가 그 패널 자체를 폐기하면서 근거를
# 잃었다 — 라벨 열 구조에서는 폼이 이미 세로 목록이라 빈 값이 보이고, 패널에 다시 나열하면
# §4-2(진입점 중복)에 걸리며 필드가 늘 때 두 곳을 고쳐야 한다. 판정 대상을 §2 골격
# (라벨 열 + 값 열 · 하단 고정 바의 개수+남은 이름 · 미충족 비활성+사유 표기)으로 옮긴다.
print("등록 §2 FORM_ENTRY 골격(라벨 열 + 하단 고정 제출 바)")
sub_render = inspect.getsource(nmsub.render)
bar_src = inspect.getsource(nmsub._submit_bar)
check("등록 폼은 st.form 을 쓰지 않는다(위젯 즉시 세션 반영)", "st.form(" not in sub_render)
check("제출은 하단 바의 st.button('제출')", 'st.button("제출"' in bar_src)
check("별도 체크리스트 패널 폐기(§2) — 진입점은 하단 바 하나",
      not hasattr(nmsub, "_checklist_html") and "CHECKLIST" not in nmsub._FORM_CSS)
check("하단 바는 개수 + 남은 항목 **이름**을 함께 쓴다(§2)",
      "_remaining_html" in bar_src and "필수 " in bar_src
      and "{done}" in bar_src and "{total}" in bar_src)
check("하단 바와 제출 재검증이 같은 _validate 를 공유한다(두 곳 유지 금지)",
      "_validate(" in bar_src and "_validate(" in sub_render)
check("미충족이면 제출 비활성 + 사유를 화면에 쓴다(§3.2·§4-3, 툴팁 전용 금지)",
      "disabled=not (schema_ready and not missing)" in bar_src
      and "rest" in bar_src and "help=" not in bar_src)
check("라벨 열은 고정폭 130px — 평가 상세(_detail_body_html)와 같은 값(§2)",
      nmsub._LABEL_COL_PX == 130 and 'stColumn"]:first-child' in nmsub._FORM_CSS)
check("<599px 에서 라벨 열+값 열을 세로로 접는다(§3.4 브레이크포인트)",
      "@media (max-width:598px)" in nmsub._FORM_CSS)
# 등록에는 등급 입력 경로가 없다 — payload 키("proposed_grade")·kwarg 어느 쪽으로도 보내지
# 않는다. 문자열 자체는 "되살리지 말 것" 주석에 남아 있어도 되므로 **실코드 형태**로 본다.
check("제안등급 입력 경로 없음(§7.2-1b — 등급은 확정등급만)",
      '"proposed_grade"' not in sub_render and "proposed_grade=" not in sub_render)
check("제출 시 전체 재검증(_validate) 계약 유지", "_validate(" in sub_render)
check("사진 스테이징-후-첨부 유지(_render_photo_stage)", "_render_photo_stage" in sub_render)

# ----- 9b) 폭·밀도·리듬 (2026-08-18 실렌더 계측 기반 재작성) -----
# 종전에는 폭이 "날짜 160 / 코드 180 / 서술 전폭"이라 한 줄 답을 받는 칸이 1021px 이었고,
# 같은 부류인 날짜(160)와 코드(180)가 서로 다른 폭이라 우측 가장자리가 어긋났다. 폭을
# **값의 실측 길이에서 역산한 3계단**으로 바꾸고 그 계단을 여기서 고정한다.
# (실측: 한글 12.488px/자 @14px — `views/near_miss_submit.py` 의 _KO_ADV_PX 주석 참조)
_KO = nmsub._KO_ADV_PX
check("글자 폭 계수는 실측 상수로 코드에 남아 있다(추정치 주석 금지)",
      abs(_KO - 12.488) < 0.01 and abs(nmsub._LAT_ADV_PX - 7.952) < 0.01)
check("짧은 값(날짜·코드) 폭 = 최장 코드 라벨에서 역산한 140",
      nmsub._W_SHORT == 140 and nmsub._W_SHORT >= 91.88 + 14 + 28 + 2)
check("한 줄 구(작업명·원인 상세) 폭 = 20자 역산 272",
      nmsub._W_LINE == 272 and nmsub._W_LINE >= 20 * _KO + 17.5)
check("서술 폭 = 한 줄 40자 역산 524(가독 상한 안)",
      nmsub._W_PROSE == 524 and nmsub._W_PROSE >= 40 * _KO + 21)
check("폭 계단은 3개뿐 — 값 열을 전부 채우는 컨트롤이 없다",
      len({nmsub._W_SHORT, nmsub._W_LINE, nmsub._W_PROSE}) == 3
      and 'width="stretch"' not in sub_render)
check("날짜·원인 코드는 **같은** 폭 상수를 쓴다(우측 가장자리 일치)",
      sub_render.count("width=_W_SHORT") == 2)
check("서술 4칸은 **같은** 폭 상수를 쓴다", sub_render.count("width=_W_PROSE") == 4)
check("한 줄 구 2칸은 **같은** 폭 상수를 쓴다", sub_render.count("width=_W_LINE") == 2)
check("서술 높이는 줄 수 역산(3줄/4줄) 상수",
      nmsub._H_PROSE_3 == 96 and nmsub._H_PROSE_4 == 120
      and sub_render.count("height=_H_PROSE_3") == 3
      and sub_render.count("height=_H_PROSE_4") == 1)
# 밀도 — 상자와 안쪽 컨트롤을 함께 44 로 못박는다(종전엔 input 만 44 라 상자 35 밖으로
# 삐져나왔고, selectbox 안쪽 input 은 12.25px/31.1px 로 남아 §1.2·§1.4 를 둘 다 어겼다).
check("cozy 하한 44 를 상자와 컨트롤 양쪽에 건다",
      nmsub._HIT_PX == 44
      and f"min-height:{nmsub._HIT_PX}px" in nmsub._FORM_CSS
      and "stTextInputRootElement" in nmsub._FORM_CSS)
check("selectbox 안쪽 input 도 14px/44px 로 되돌린다(§1.2 5단계·§1.4)",
      'div[data-testid="stSelectbox"] input' in nmsub._FORM_CSS)
# 리듬 — Streamlit 기본 세로 gap 9.1px 은 §1.1 스케일 밖이라 이 화면 본문 블록에서 12 로
# 못박고, 섹션 머리 위는 12(gap)+12(margin)=24 가 되게 한다.
check("본문 블록 세로 gap 을 스케일 값(12)으로 못박는다",
      nmsub._ROW_GAP == 12 and f"gap:{nmsub._ROW_GAP}px !important" in nmsub._FORM_CSS)
check("섹션 머리 여백도 스케일 값(12 → 위 24)", nmsub._SEC_GAP == 12
      and f"margin:{nmsub._SEC_GAP}px 0 0" in nmsub._FORM_CSS)
check("CSS 주입 블록은 레이아웃(gap)에서 제외한다", "st-key-nm_css" in nmsub._FORM_CSS
      and 'st.container(key="nm_css")' in sub_render)
# CSS 안의 간격 값이 전부 §1.1 스케일인지 — px 로 적힌 gap/margin/padding 값을 훑는다.
_SCALE = {0, 4, 8, 12, 16, 24, 32, 40}
_spacing = re.findall(r"(?:gap|margin|padding)(?:-[a-z]+)?:\s*([^;{}]+);", nmsub._FORM_CSS)
_offscale = []
for _decl in _spacing:
    for _tok in _decl.replace("!important", "").split():
        if _tok.endswith("px"):
            try:
                _v = float(_tok[:-2])
            except ValueError:
                continue
            if _v not in _SCALE:
                _offscale.append(_tok)
check(f"CSS 간격 값이 전부 §1.1 스케일(4·8·12·16·24·32·40) 안 — 밖: {_offscale}",
      not _offscale)


# ===== 10) Medium 2 — 평가 확정등급 기본 미선택 + 미선택 시 평가확정 비활성 =====
print("평가 확정등급 기본 미선택 게이트")
eval_src = inspect.getsource(nme._render_detail)
check("확정등급 기본 미선택(S/grades[0] 자동선택 제거)",
      'cur_grade = ""' in eval_src and "grades[0]" not in eval_src)
check("평가확정은 등급 미선택 시 비활성(grade_selected 게이트)",
      "grade_selected" in eval_src and "not grade_selected" in eval_src)
check("미선택 안내 문구('등급을 선택하세요')", "등급을 선택하세요" in eval_src)
check("평가착수/보완요청/반려는 등급 무관(현행 게이트 유지)",
      'status != "SUBMITTED"' in eval_src and 'status != "IN_REVIEW"' in eval_src and "not opinion" in eval_src)
check("케이스 전환 시 이전 등급 선택 초기화(_EVAL_ACTIVE_KEY)",
      "_EVAL_ACTIVE_KEY" in eval_src and "grade_key, None" in eval_src)
check("등급 목록 db 파생(하드코딩 금지)", "list(db.NEAR_MISS_GRADES)" in eval_src)


# ===== 11) 수정 라운드 3 (U2·U3·U5·U8) =====
print("수정 라운드 3 — 등록 제출 위치·조회 seed·평가 사진 뷰어·제출취소 제거")
sub_src = inspect.getsource(nmsub.render)
# U2: 본문은 01→02→03(사진)으로 자연 종결하고 제출은 **하단 고정 바**가 맡는다(§2 골격) —
# 소스상 사진 스테이징 렌더가 제출 바보다 먼저 온다. 우측 CHECKLIST 열은 §2 로 폐기됐다.
check("U2 제출 바가 사진 섹션(03) 뒤(소스 순서: _render_photo_stage < _submit_bar)",
      sub_src.index("_render_photo_stage(") < sub_src.index("_submit_bar("))
# U3: 조회 진입 seed(최근 90일) — 빈 안내 패널 대신 즉시 데이터.
view_src = inspect.getsource(nmv.render)
cond_src = inspect.getsource(nmv._collect_conditions)
check("U3 near_miss_view 진입 seed(seed_query_once)", "seed_query_once" in view_src)
check("U3 기간 셀렉트에 '최근 90일' 기본 옵션", '"최근 90일"' in cond_src)
check("U3 seed_query_once 헬퍼 존재(workspace)", hasattr(wsp, "seed_query_once"))
# U5: 평가 상세 사진 뷰어 실구현(자리표시 제거).
eval_detail = inspect.getsource(nme._render_detail)
check("U5 평가 상세 사진 뷰어 실구현(render_photo_thumbs)", "render_photo_thumbs" in eval_detail)
check("U5 '뷰어 미구현' 자리표시 문구 제거", "뷰어 미구현" not in eval_detail)
# U8: '제출 취소' 자리표시 버튼 제거.
entry_src = inspect.getsource(nmy._render_edit_entry)
check("U8 '제출 취소' 비활성 버튼 제거(버튼·키 부재)",
      'st.button("제출 취소"' not in entry_src and "nm_my_cancel" not in entry_src)


# ===== 12) WORKLIST 골격 이관 (DESIGN.md §2 · §4-1 · §7.1) =====
# 종전 이 파일은 "좌우 분할 금지"를 PASS 조건으로 강제했다(구 §0-2). 그 금지는 이유 없이
# 적혀 있었고 승인 큐의 업계 표준 구조를 막았으므로 폐기됐다(DESIGN.md 부록). 지금은 §2 가
# 요구하는 **상태 탭 + 2열(목록 33% / 상세 67%)** 을 실제로 구현했는지 반대 방향으로 고정한다.
print("WORKLIST 골격(§2) — 상태 탭 + 2열 33/67 + 지표 타일 부재")
_WORKLIST_SCREENS = (("평가 관리", nme), ("개선조치 관리", nmi))
for _label, _mod in _WORKLIST_SCREENS:
    _src = inspect.getsource(_mod)
    _body = inspect.getsource(_mod._render_body)
    check(f"[{_label}] SCREEN_ARCHETYPE == 'WORKLIST'", _mod.SCREEN_ARCHETYPE == "WORKLIST")
    # 33/67 분할 — master_detail_frame 의 기본값은 1.5/1.0(≈60/40)이라 **반대**다.
    # 인자를 실제로 넘기는지까지 봐야 한다(호출만 있으면 60/40 으로 렌더된다).
    check(f"[{_label}] erp.master_detail_frame 실호출", "master_detail_frame(" in _body)
    check(f"[{_label}] 비율 인자 list_ratio=1, detail_ratio=2(=33/67)",
          "list_ratio=1" in _body and "detail_ratio=2" in _body)
    # 상태 탭 — st.tabs 는 기본값이 모든 탭을 미리 렌더해 "탭이 목록을 바꾼다"는 §2 계약이
    # 성립하지 않는다. segmented_control(클릭=rerun)만 인정한다.
    check(f"[{_label}] 상태 탭은 st.segmented_control", "st.segmented_control(" in _src)
    check(f"[{_label}] st.tabs 미사용(전 탭 선렌더 금지)", "st.tabs(" not in _src)
    check(f"[{_label}] 탭이 목록을 실제로 바꾼다(_render_tabs 결과가 목록 필터로 흐름)",
          "_render_tabs(" in _body and "tab" in _body)
    # §4-1 — 읽기 전용 지표 타일 금지. 건수는 탭 라벨이 싣는다.
    # (docstring 은 "무엇을 폐기했는지" 적어야 하므로 이름이 등장한다 — **호출**을 본다.)
    check(f"[{_label}] 지표 타일(erp.metric_strip) 호출 없음(§4-1)", "metric_strip(" not in _src)
    check(f"[{_label}] 탭 라벨에 건수 표기(format_func)", "format_func" in _src)
    # 목록 열 — 2줄 고정 행 컴포넌트 + 자연키 선택 + 자체 스크롤.
    check(f"[{_label}] 목록은 erp.select_list(2줄 고정 행)", "erp.select_list(" in _src)
    check(f"[{_label}] 목록 자체 스크롤(st.container(height=...))",
          "st.container(height=" in _src)
    check(f"[{_label}] 목록 행에 경과일·소속·분류(처리 우선순위 근거)",
          "elapsed_label" in _src and "line1_right" in _src
          and "line2_left" in _src and "line2_right" in _src)
    check(f"[{_label}] 상태는 좌측 2px 보더(accent)로만 — 행 높이 불변(§4-5)",
          '"accent"' in _src)
    # 선택은 위치가 아니라 자연키. 선택 보관은 호출부 책임(select_list 계약).
    check(f"[{_label}] 선택 상태는 세션 자연키로 보관", "_SEL_KEY" in _body)

# ===== 13) 어휘(§3.6)·상태 결과(§3.3)·경과일(§7.2-4)·보완요청 007 게이트(§7.4) =====
print("어휘·상태 결과·경과일·보완요청 007 게이트")
_eval_mod_src = inspect.getsource(nme)
_impr_mod_src = inspect.getsource(nmi)

# §3.6 — 한 도메인에 한 낱말. 한글 라벨만 통일하고 영문 코드값은 바꾸지 않는다.
# 소스 전문 grep 은 쓰지 않는다 — 모듈 docstring 은 "무엇을 폐기했는지" 적어야 하므로 구
# 낱말이 반드시 등장한다. **렌더 결과와 라벨 사전**으로 본다.
_EVAL_SAMPLE = {
    "id": "r1", "report_no": "202608-0001", "work_name": "제품 적재",
    "status": "IN_REVIEW", "incident_date": "2026-08-05", "dept_code": "PET1",
    "reporter_emp_no": "", "created_at": "2026-08-05T00:00:00+00:00",
}
_eval_head = nme._detail_head_html(_EVAL_SAMPLE, "IN_REVIEW")
check("평가 관리: '검토중' 폐기 → '평가중'(배지 라벨·렌더)",
      nme._STATUS_LABEL["IN_REVIEW"] == "평가중"
      and "평가중" in _eval_head and "검토중" not in _eval_head)
check("평가 관리: 상태 라벨 사전에 '검토' 어근 없음",
      not any("검토" in v for v in nme._STATUS_LABEL.values()))
check("평가 관리: '확정 등급' 폐기 → '평가 등급'(결정 컨트롤 라벨)",
      "평가 등급" in detail_src and "확정 등급" not in detail_src
      and "확정등급" not in detail_src)
_impr_head = nmi._detail_read_html(
    dict(_EVAL_SAMPLE, status="EVALUATED", confirmed_grade="B",
         cause_code="HIT", cause_detail="", incident_content="", countermeasure=""),
    None, "EVALUATED")
check("개선조치: '확정등급' 폐기 → '평가 등급'(상세 메타 렌더)",
      "평가 등급" in _impr_head and "확정등급" not in _impr_head)
check("영문 코드값 불변(IN_REVIEW · confirmed_grade)",
      "IN_REVIEW" in _eval_mod_src and "confirmed_grade" in _impr_mod_src)

# §3.3 — 상태는 배지로, 그 상태의 **결과**는 별도 표기로. 배지 라벨만으로는 그 상태가
# 무엇을 막고 무엇을 여는지 알 수 없다.
check("평가 관리: 상태 결과 표기(_STATUS_EFFECT)", hasattr(nme, "_STATUS_EFFECT"))
check("평가중 = 보고자 수정 잠김(docs/database.md 보고자 수정 컷오프)",
      nme._STATUS_EFFECT["IN_REVIEW"] == "보고자 수정 잠김")
check("제출됨 = 보고자 수정 가능(잠금 전)",
      "보고자 수정 가능" in nme._STATUS_EFFECT["SUBMITTED"])
check("상태 결과가 상세 머리에 실제로 렌더", "_STATUS_EFFECT.get(status" in _eval_mod_src)
check("개선조치: 단계 결과 표기(_STAGE_EFFECT)", hasattr(nmi, "_STAGE_EFFECT"))
check("확인됨 = 조치 수정 잠김 · 보고서 종결 가능",
      "종결 가능" in nmi._STAGE_EFFECT["확인됨"] and "잠김" in nmi._STAGE_EFFECT["확인됨"])

# §3.2·§4-3 — 비활성 사유를 툴팁에만 두지 않는다. 두 화면 모두 화면에 쓴다.
check("평가 관리: 비활성 사유를 화면에 표기(_gate_notes)", "_gate_notes(" in _eval_mod_src)
check("개선조치: 비활성 사유를 화면에 표기(_gate_notes)", "_gate_notes(" in _impr_mod_src)

# §7.4 P1 — 보완요청 활성 게이트를 **실행부와 같은 007 프로브**로 맞춘다.
# 종전: 활성 판정은 006(near_miss_schema_probe), 실행부 db.request_near_miss_revision 은
# 007(near_miss_improvement_schema_probe) fail-closed → 006 만 적용된 배포에서 버튼이
# 눌리고 실패했다.
_rev_ready_src = inspect.getsource(nme._revision_readiness)
check("보완요청 readiness 는 007 프로브(near_miss_improvement_schema_probe)",
      "near_miss_improvement_schema_probe" in _rev_ready_src)
check("보완요청 활성 판정이 006 이 아니라 007 를 쓴다",
      "revision_readiness.write_enabled" in detail_src
      and "not can_revise" in detail_src)
check("실행부도 같은 007 프로브로 차단(계약 일치)",
      "near_miss_improvement_schema_probe" in inspect.getsource(db.request_near_miss_revision))
check("보완요청 비활성 사유가 화면 문구로 존재", "보완요청 스키마(007)" in _eval_mod_src)

# §7.2-4 — 경과일은 접수일(created_at) 기준이며 incident_date 가 아니다.
from views.common import worklist as _wl  # noqa: E402

check("경과일 파생은 목록 행에서 created_at 을 읽는다",
      'elapsed_label(r.get("created_at"))' in _eval_mod_src
      and 'elapsed_label(r.get("created_at"))' in _impr_mod_src)
check("경과일에 incident_date 를 쓰지 않는다(집계 축과 별개)",
      "elapsed_label(r.get(\"incident_date\")" not in _eval_mod_src
      and "elapsed_days(r.get(\"incident_date\")" not in _eval_mod_src)
_today = date(2026, 8, 18)
check("경과일: 같은 날 접수 → 0(‘오늘’)",
      _wl.elapsed_days("2026-08-18T00:30:00+00:00", today=_today) == 0
      and _wl.elapsed_label("2026-08-18T00:30:00+00:00", today=_today) == "오늘")
# KST 경계: UTC 2026-08-17T23:00Z = KST 2026-08-18 08:00 → 접수일은 18일(경과 0일).
# UTC 로 세면 17일이 되어 하루 더 나온다.
check("경과일: KST 날짜 경계로 센다(UTC 23:00Z = 익일 KST)",
      _wl.elapsed_days("2026-08-17T23:00:00+00:00", today=_today) == 0
      and _wl.elapsed_days("2026-08-17T14:00:00+00:00", today=_today) == 1)
check("경과일: Z 접미 타임스탬프 허용",
      _wl.elapsed_days("2026-08-10T00:00:00Z", today=_today) == 8)
check("경과일: tz 없는 문자열은 UTC 로 해석",
      _wl.elapsed_days("2026-08-10T00:00:00", today=_today) == 8)
check("경과일: 값 없음/파싱 실패는 0 으로 위장하지 않고 None·'-'",
      _wl.elapsed_days(None, today=_today) is None
      and _wl.elapsed_days("", today=_today) is None
      and _wl.elapsed_days("not-a-date", today=_today) is None
      and _wl.elapsed_label(None, today=_today) == "-")
check("경과일: 미래 타임스탬프는 음수 대신 0 클램프",
      _wl.elapsed_days("2026-08-20T00:00:00+00:00", today=_today) == 0)
# §7.2-4-c 반송 누적 — 보완요청(IN_REVIEW→SUBMITTED)은 created_at 을 바꾸지 않으므로
# 경과일이 최초 접수부터 누적된다. 리셋 경로를 만들면 반송을 반복해 지연을 0 으로 되돌릴
# 수 있다. 파사드 원문에 created_at 재설정이 없음을 함께 고정한다.
_revision_src = inspect.getsource(db.request_near_miss_revision)
check("반송(보완요청)이 created_at 을 재설정하지 않는다(최초 접수부터 누적)",
      "created_at" not in _revision_src)
_created = "2026-08-01T00:00:00+00:00"
check("반송 전후로 경과일이 동일(누적)",
      _wl.elapsed_days(_created, today=_today) == 17
      and _wl.elapsed_days(_created, today=_today) == 17)
# §7.2-4-b — SLA 가 없으므로 경과일에 색을 칠하지 않는다(목록이 경과일 내림차순이라
# 순서가 이미 우선순위를 말한다). 파생 모듈은 색을 만들지 않고 라벨만 돌려준다.
_wl_src = inspect.getsource(_wl)
check("경과일 파생 모듈은 색을 만들지 않는다",
      "color" not in _wl_src and re.search(r"#[0-9a-fA-F]{6}\b", _wl_src) is None)
check("경과일 라벨은 순수 문자열(HTML·색 없음)",
      "<" not in _wl.elapsed_label("2026-08-10T00:00:00Z", today=_today))
# 정렬 — 오래 묵은 건이 위로. 경과일 미상은 맨 뒤(0 일로 위장하면 방금 접수 건과 섞인다).
_ordered = _wl.order_by_elapsed([
    ("new", "2026-08-18T00:00:00+00:00", "2026-08-01"),
    ("unknown", None, "2026-08-02"),
    ("old", "2026-08-01T00:00:00+00:00", "2026-08-03"),
])
check("정렬: 경과일 내림차순 + 미상 맨 뒤", _ordered == ["old", "new", "unknown"])


# ===== 목록 컨테이너 key 는 내부 select_list 위젯 key 와 달라야 한다 =====
# st.container(key=X) 와 erp.select_list(X, ...) 가 같은 이름이면 Streamlit 이
# StreamlitDuplicateElementKey 를 던져 화면 전체가 죽는다(2026-08-18 실제 발생).
# 정적 검사는 렌더를 타지 않아 못 잡으므로 소스에서 두 key 를 직접 뽑아 비교한다.
def _keys_of(src):
    ct, sl, want_sl = [], [], False
    for line in src.splitlines():
        s = line.strip()
        if 'st.container(' in s and 'key=' in s:
            seg = s.split('key=', 1)[1]
            if seg.startswith(chr(34)):
                ct.append(seg[1:].split(chr(34), 1)[0])
        if 'erp.select_list(' in s:
            want_sl = True
            continue
        if want_sl and s.startswith(chr(34)):
            sl.append(s[1:].split(chr(34), 1)[0])
            want_sl = False
    return ct, sl

for _mod, _tag in ((nme, 'near_miss_evaluate'), (nmi, 'near_miss_improvement')):
    _ct, _sl = _keys_of(inspect.getsource(_mod))
    check(_tag + ': 목록 컨테이너 key 와 select_list key 를 둘 다 찾음',
          len(_ct) >= 1 and len(_sl) >= 1)
    check(_tag + ': 컨테이너 key != select_list key (중복키 크래시 방지)',
          not (set(_ct) & set(_sl)))

print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
