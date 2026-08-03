"""아차사고 UI 게이트 회귀 — 능력 통일(nav)·평가 검토착수·stats 보고서 종결률.

007 스키마와 무관하게 즉시 구현된 UI 계약을 고정한다(비회귀 그물):
  1) nav 능력 게이트 — near_miss_improvement 는 '배정 기반' 접근 능력
     (CAP_ACCESS_NEAR_MISS_IMPROVEMENT)으로 노출하고, 평가 관리는 평가 능력
     (CAP_EVALUATE_NEAR_MISS)으로 노출한다(두 능력 분리 — Phase2). 정적 roles 없음.
     USER_MENU(평면)·route guard(nav.allowed)가 동일 caps 로 노출·차단 일치한다.
  2) 평가 관리(near_miss_evaluate) — 상세 scope 액션에 검토착수(SUBMITTED→IN_REVIEW) 배선,
     status=="SUBMITTED" 에서만 활성. EVALUATED 종결 버튼은 이 화면에 없음(개선조치 소관).
  3) stats(near_miss_stats) — _closure_rate_label 은 CLOSED/(CLOSED+EVALUATED), 0분모 방어('—'),
     명칭은 정확히 '보고서 종결률'('CAPA 종결률' 금지).

실행: PYTHONUTF8=1 C:\\dev\\duty-scheduler\\.venv\\Scripts\\python.exe scripts/test_near_miss_ui_gates.py
"""
from __future__ import annotations

import inspect
import os
import sys
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


# ===== 2) 평가 관리 검토착수 배선 =====
print("평가 관리 검토착수")
detail_src = inspect.getsource(nme._render_detail)
check("검토착수 scope 액션 라벨 존재", '"검토착수"' in detail_src or "'검토착수'" in detail_src)
check("검토착수 → update_near_miss_status(..., \"IN_REVIEW\", ...)",
      "IN_REVIEW" in detail_src and "update_near_miss_status" in detail_src)
check("검토착수 활성 게이트: status == 'SUBMITTED'",
      'status != "SUBMITTED"' in detail_src)
check("검토착수는 current_user=auth.get_current_user() 전달(신원 서버측 확정)",
      "current_user=auth.get_current_user()" in detail_src)
# 종결 버튼은 이 화면에 없다(개선조치 소관) — 회귀 방지. detail_actions 튜플에 종결 라벨 없음.
check("평가 화면에 종결 버튼 미도입(detail_actions 라벨 없음)",
      '("종결"' not in detail_src and "'종결'," not in detail_src)
# §1-A 액션 바 — 평가확정만 primary CTA, 검토착수는 보조(secondary) 버튼.
check("평가확정만 primary CTA(검토착수는 보조 secondary)",
      'st.button("평가확정"' in detail_src and 'type="primary"' in detail_src
      and 'st.button("검토착수"' in detail_src and 'type="secondary"' in detail_src)


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


# ===== 5) 개선조치 관리(near_miss_improvement) MASTER_DETAIL 폐루프 =====
print("개선조치 관리 CAPA 폐루프")
check("SCREEN_ARCHETYPE == 'MASTER_DETAIL'", nmi.SCREEN_ARCHETYPE == "MASTER_DETAIL")
render_src = inspect.getsource(nmi.render)
# Phase2: 진입가드는 배정 기반 접근 facade 로(평가 능력 단독이 아니라 담당자·확인자 포함).
check("진입가드: has_near_miss_improvement_access(배정 기반)",
      "has_near_miss_improvement_access" in render_src)
body_src = inspect.getsource(nmi._render_body)
# §1-A 큐 처리형: 좌우 분할(master_detail_frame) 제거 → 큐 칩 스트립 + 전체폭 상세.
check("§1-A 큐 칩 스트립(좌우분할 제거)",
      "_render_queue_chips" in body_src and "master_detail_frame" not in body_src)
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


# ===== 9) Medium 1 — 등록 체크리스트 실시간화(near_miss_submit, st.form 미사용) =====
print("등록 체크리스트 실시간화(st.form 미사용)")
sub_render = inspect.getsource(nmsub.render)
check("등록 폼은 st.form 을 쓰지 않는다(위젯 즉시 세션 반영)", "st.form(" not in sub_render)
check("제출은 st.button('제안서 제출')", 'st.button("제안서 제출"' in sub_render)
check("체크리스트는 세션 값을 읽어 실시간 파생", "st.session_state.get(key)" in inspect.getsource(nmsub._checklist_html))
check("제출 시 전체 재검증(_validate) 계약 유지", "_validate(" in sub_render)
check("사진 스테이징-후-첨부 유지(_render_photo_stage)", "_render_photo_stage" in sub_render)


# ===== 10) Medium 2 — 평가 확정등급 기본 미선택 + 미선택 시 평가확정 비활성 =====
print("평가 확정등급 기본 미선택 게이트")
eval_src = inspect.getsource(nme._render_detail)
check("확정등급 기본 미선택(S/grades[0] 자동선택 제거)",
      'cur_grade = ""' in eval_src and "grades[0]" not in eval_src)
check("평가확정은 등급 미선택 시 비활성(grade_selected 게이트)",
      "grade_selected" in eval_src and "not grade_selected" in eval_src)
check("미선택 안내 툴팁('등급을 선택하세요')", "등급을 선택하세요" in eval_src)
check("검토착수/보완요청/반려는 등급 무관(현행 게이트 유지)",
      'status != "SUBMITTED"' in eval_src and 'status != "IN_REVIEW"' in eval_src and "not opinion" in eval_src)
check("케이스 전환 시 이전 등급 선택 초기화(_EVAL_ACTIVE_KEY)",
      "_EVAL_ACTIVE_KEY" in eval_src and "grade_key, None" in eval_src)
check("등급 목록 db 파생(하드코딩 금지)", "list(db.NEAR_MISS_GRADES)" in eval_src)


# ===== 11) 수정 라운드 3 (U2·U3·U5·U8) =====
print("수정 라운드 3 — 등록 제출 위치·조회 seed·평가 사진 뷰어·제출취소 제거")
sub_src = inspect.getsource(nmsub.render)
# U2: [제안서 제출]은 본문(01→02→03 사진) 뒤 CHECKLIST 열 하단에 온다 — 소스상 사진 스테이징
# 렌더가 제출 버튼보다 먼저 온다(본문이 03 으로 자연 종결, 제출은 우측 패널 하단).
check("U2 제출 버튼이 사진 섹션(03) 뒤(소스 순서: _render_photo_stage < 제안서 제출 버튼)",
      sub_src.index("_render_photo_stage(") < sub_src.index('st.button("제안서 제출"'))
check("U2 체크리스트 뒤 제출(check_col 에 _checklist_html 후 제출 버튼)",
      sub_src.index("_checklist_html()") < sub_src.index('st.button("제안서 제출"'))
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


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
