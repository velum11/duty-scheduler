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


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
