"""개선조치 관리 — 셸(shell) 화면.

DESIGN.md §0 화면 유형: ``READ_VIEW`` — 현재는 안내(notice)만 렌더하는 셸이다.
개선조치 저장 기능은 현재 데이터 구조상 준비되지 않았으므로, **가짜 저장·임시
데이터·write 를 절대 만들지 않는다**. 이 화면은 준비 상태 고지 + 향후 필요한 데이터
구조 요약만 보여준다.

권한: ADMIN 전용. 경계는 nav.py 의 자식 항목 ``roles=("ADMIN",)`` 로 route guard
(``app.py``)와 메뉴 노출이 이미 집행한다 — 화면 본문에 role 하드코딩을 두지 않는다
(중복 게이트 제거, Codex 지적 반영).

향후 필요한 데이터 구조(요약 — 스키마 확정 시 migration 으로 도입)
------------------------------------------------------------------
개선조치(near_miss_improvement) 레코드는 아래를 담아야 한다:
  - report_fk        : 대상 아차사고 보고서 FK(near_miss_reports.id) — 어떤 건의 조치인지.
  - assignee         : 조치 담당자(사번/사용자 FK) — 개선을 수행할 사람.
  - confirmer        : 조치 확인자(사번/사용자 FK) — 완료를 승인·확인할 사람.
  - result_body      : 조치 결과 본문(무엇을·어떻게 개선했는지 서술).
  - submit_status    : 담당자 제출 상태(예: 작성중/제출됨).
  - confirm_status   : 확인자 확인 상태(예: 확인대기/확인됨/반려).
이 화면은 위 구조가 승인·도입되기 전까지 저장 UI 를 노출하지 않는다.
"""
from __future__ import annotations

# DESIGN.md §0 화면 유형 규약 — 조회/안내형 셸.
SCREEN_ARCHETYPE = "READ_VIEW"

import streamlit as st

from modules import db  # noqa: F401 — 모드 배지 등 공용 경로와의 일관성(향후 조회 연결 지점).
from views.common import erp, scaffold
from views.master import TOKENS, banner, icon_toolbar_specs

_IMPROVEMENT_DESC = "아차사고 개선조치를 관리합니다."


def render(user: dict) -> None:
    # 접근 경계는 nav route guard(ADMIN)가 이미 집행한다 — 화면 본문에 role 게이트를 두지 않는다.
    # toolbar="icons": 상단 파랑 밴드를 타 화면과 동일한 KPtech 아이콘 툴바 포맷으로 통일한다
    # (2026-07-27, 구 정적 장식 5아이콘 대체). 저장 기능이 준비되지 않은 안내 셸이라 밴드의
    # 4개 액션 아이콘은 전부 shaded, 정보 아이콘만 활성으로 둔다.
    band = erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="개선조치 관리",
        desc=_IMPROVEMENT_DESC,
        breadcrumb="아차사고 › 개선조치 관리",
        badges=scaffold.mode_badge(),
        toolbar="icons",
    )
    if band is not None:
        _na = "개선조치 저장 기능은 아직 준비되지 않았습니다"
        band.render_icons(icon_toolbar_specs(
            "near_miss_improvement", info_content=_IMPROVEMENT_DESC,
            add={"key": "nm_impr__add_na", "disabled": True, "help": _na},
            refresh={"key": "nm_impr__refresh_na", "disabled": True, "help": _na},
            delete={"key": "nm_impr__del_na", "disabled": True, "help": _na},
            save={"key": "nm_impr__save_na", "disabled": True, "help": _na},
        ))

    banner("info",
           "개선조치 저장 기능은 현재 구조상 준비되지 않았습니다. "
           "데이터 구조가 확정·도입되면 이 화면에서 개선조치를 등록·확인할 수 있습니다.")

    st.markdown(
        f"""
<div style="border:1px solid {TOKENS['line-strong']};border-radius:8px;
     background:{TOKENS['surface-2']};padding:14px 16px;margin-top:8px;">
  <div style="font-weight:700;color:{TOKENS['ink']};margin-bottom:8px;">
    향후 필요한 데이터 구조(요약)
  </div>
  <ul style="margin:0;padding-left:18px;color:{TOKENS['ink-2']};font-size:13px;line-height:1.7;">
    <li><b>대상 보고서(report FK)</b> — 어떤 아차사고에 대한 개선조치인지</li>
    <li><b>담당자(assignee)</b> — 개선을 수행할 사람</li>
    <li><b>확인자(confirmer)</b> — 완료를 확인·승인할 사람</li>
    <li><b>조치 결과 본문(result body)</b> — 무엇을 어떻게 개선했는지</li>
    <li><b>제출 상태(submit status)</b> — 담당자 작성/제출 진행</li>
    <li><b>확인 상태(confirm status)</b> — 확인자 확인/반려 진행</li>
  </ul>
  <div style="margin-top:10px;color:{TOKENS['ink-3']};font-size:12px;">
    ※ 준비 전까지 저장 기능을 제공하지 않습니다(임시 저장·가짜 데이터 없음).
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
