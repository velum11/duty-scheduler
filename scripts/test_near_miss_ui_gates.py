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

from modules import nav  # noqa: E402
from views import near_miss_evaluate as nme  # noqa: E402
from views import near_miss_improvement as nmi  # noqa: E402
from views import near_miss_my as nmy  # noqa: E402
from views import near_miss_stats as nms  # noqa: E402

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
kpi_src = inspect.getsource(nms._kpi_cards)
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
check("배정필드는 can_assign 읽기전용", "disabled=not can_assign" in form_src)
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


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
