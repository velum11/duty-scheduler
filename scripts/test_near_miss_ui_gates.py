"""아차사고 UI 게이트 회귀 — 능력 통일(nav)·평가 검토착수·stats 보고서 종결률.

007 스키마와 무관하게 즉시 구현된 UI 계약을 고정한다(비회귀 그물):
  1) nav 능력 게이트 통일 — near_miss_improvement 가 평가 관리와 동일하게 CAP_EVALUATE_NEAR_MISS
     로만 노출(구 roles=("ADMIN",) 제거). ADMIN/MANAGER/안전담당자 caps 노출, 능력 없으면 차단.
     USER_MENU(평면) 에 개선조치 항목이 caps 로만 포함 — USER route guard(nav.allowed) 정합.
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


CAPS = {nav.CAP_EVALUATE_NEAR_MISS}


# ===== 1) nav 능력 게이트 통일 =====
print("nav 능력 게이트 통일")
# 그룹 자식(near_miss_improvement)이 capability 로 전환됐고 static ADMIN roles 는 제거됐다.
_child = next(c for g in nav.MENU_GROUPS if g["id"] == "near_miss"
              for c in g["children"] if c["id"] == "near_miss_improvement")
check("개선조치 child capability=CAP_EVALUATE_NEAR_MISS",
      _child.get("capability") == nav.CAP_EVALUATE_NEAR_MISS)
check("개선조치 child 에 static ADMIN roles 제거", tuple(_child.get("roles", ())) == ())

# route guard 정합 — 능력 보유 role 은 그룹 경로로 개선조치 접근, 능력 없으면 차단.
check("ADMIN(caps) 개선조치 allowed", nav.allowed("near_miss_improvement", "ADMIN", CAPS))
check("MANAGER(caps) 개선조치 allowed", nav.allowed("near_miss_improvement", "MANAGER", CAPS))
check("caps 없는 role 은 개선조치 차단(ADMIN caps=None)",
      not nav.allowed("near_miss_improvement", "ADMIN", None))

# USER_MENU(평면) — 개선조치·평가 관리는 caps 로만 노출.
user_ids_no_caps = {i["id"] for i in nav.user_menu(None)}
user_ids_caps = {i["id"] for i in nav.user_menu(CAPS)}
check("USER_MENU 에 개선조치 정의 존재",
      any(i["id"] == "near_miss_improvement" for i in nav.USER_MENU))
check("무능력 USER 는 개선조치·평가 관리 미노출",
      not ({"near_miss_improvement", "near_miss_evaluate"} & user_ids_no_caps))
check("능력 USER 는 개선조치·평가 관리 노출",
      {"near_miss_improvement", "near_miss_evaluate"} <= user_ids_caps)
check("안전담당자 USER route guard: 개선조치 allowed",
      nav.allowed("near_miss_improvement", "USER", CAPS))
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
# 순수 UI 계약 — detail_actions 는 여전히 라벨/kind/disabled/help 튜플만 넘긴다.
check("검토착수 default 버튼(primary 아님)", '("검토착수", "default"' in detail_src)


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
overdue_src = inspect.getsource(nms._overdue_count)
check("overdue 는 007 readiness 게이트(미준비 None)",
      "near_miss_improvement_schema_probe" in overdue_src and "READINESS_READY" in overdue_src)
check("overdue 조건: 미확인(CONFIRMED 제외) + due_date 과거",
      "CONFIRMED" in overdue_src and "due" in overdue_src)


# ===== 5) 개선조치 관리(near_miss_improvement) MASTER_DETAIL 폐루프 =====
print("개선조치 관리 CAPA 폐루프")
check("SCREEN_ARCHETYPE == 'MASTER_DETAIL'", nmi.SCREEN_ARCHETYPE == "MASTER_DETAIL")
render_src = inspect.getsource(nmi.render)
check("진입가드: can_evaluate_near_miss", "can_evaluate_near_miss" in render_src)
body_src = inspect.getsource(nmi._render_body)
check("MASTER_DETAIL split 사용(master_detail_frame)", "master_detail_frame" in body_src)
act_src = inspect.getsource(nmi._render_actions)
for label in ("조치 저장", "제출", "확인", "재조치 요청"):
    check(f"scope 액션 라벨 '{label}'", f'"{label}"' in act_src)
check("자기확인 차단 게이트(self_confirm)", "self_confirm" in act_src and "자기확인" in act_src)
check("신원 서버측 확정(current_user=auth.get_current_user())",
      "current_user=auth.get_current_user()" in act_src)
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
check("보완요청 전용 사유 필드(반려 사유와 별개)", "nm_revreason_" in detail_src)
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
