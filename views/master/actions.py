"""page-scoped 액션바 · dirty 폐기 게이트 · 2단계 확인 바 프리미티브.

계약(Phase2 §2, design-contract §7·§8·§17):
  - 액션바는 **버튼 렌더 + 이벤트 기록만** 담당한다. 저장/삭제 실행 순서·확인은
    controller(lifecycle.py + 화면)가 맡는다.
  - 모든 세션 flag 는 ``DraftState.action_key`` 로 page-scoped(공용 ``ms_*`` 폐기).
  - 저장 버튼은 dirty(미저장 변경)일 때만 활성, 변경 건수를 badge 로 노출한다.
  - 삭제는 선택 0이면 비활성(사유 tooltip). busy 시 저장 비활성.
  - 아이콘은 Streamlit Material(단색) 사용 — 컬러 이모지 금지(§8).
"""
from __future__ import annotations

import streamlit as st

from views.master import style
from views.master.state import DraftState

# 액션 이름 상수(오타 방지) — action_key 접미사와 CSS role suffix 양쪽에 쓴다.
ADD = "add"
ADD_GROUP = "addg"
DELETE = "delete"
SAVE = "save"
REFRESH = "refresh"


def _css_role_key(state: DraftState, role: str) -> str:
    """CSS-safe 버튼 위젯 key: `{page_id}__{role}` (style.py 부분일치 선택자 대상)."""
    return f"{state.page_id}__{role}"


_WRITE_DISABLED_DEFAULT = "지금은 편집할 수 없습니다"


def master_action_bar(
    state: DraftState,
    *,
    sel_count: int,
    dirty_total: int = 0,
    can_save: bool = True,
    can_write: bool = True,
    busy: bool = False,
    ratios: tuple = (1.5, 1.3, 1.4, 3.2, 1.6),
    save_disabled_reason: str | None = None,
    write_disabled_reason: str | None = None,
) -> None:
    """좌 [＋ 행 추가][삭제][저장] · 우 [새로고침]. 클릭은 page-scoped flag 로 남긴다.

    - ``dirty_total``: §20 공식 ``신규(미삭제)+기존변경``. 저장 badge/활성 판단에 쓴다.
    - ``can_save``: 저장 **하나만** 막을 화면 사유(예: 저장 대상 없음/특정 검증). add/delete
      는 살려둔다.
    - ``can_write``: **모든 write control(행 추가·삭제·저장)** 을 함께 막는다. readiness
      NOT_READY/PROBE_ERROR 또는 권한상 쓰기 불가일 때 ``readiness.write_enabled`` 를 그대로
      넘긴다(design-contract §25 "all write controls disabled"). 기본 True 라 기존 호출부는
      영향 없다(후방호환). **새로고침(조회)은 계속 활성** — NOT_READY 도 조회만은 허용(§25).
    - ``busy``: 저장 진행 중(스피너 대체) — write control 비활성.
    - ``save_disabled_reason``: 저장만 막힐 때 tooltip.
    - ``write_disabled_reason``: 쓰기 전체가 막힐 때 tooltip(동일 readiness 메시지 권장).
      add/delete/save 세 버튼의 사유로 함께 쓰인다.
    controller 는 렌더 뒤 ``state.take_action(SAVE/DELETE/ADD/REFRESH)`` 로 소비한다.
    """
    write_reason = write_disabled_reason or _WRITE_DISABLED_DEFAULT
    write_ok = can_write and not busy  # 쓰기 가능 여부(add/delete 공통 게이트)
    save_enabled = bool(dirty_total) and can_save and write_ok

    # 행 추가
    add_help = write_reason if not can_write else ("처리 중입니다" if busy else None)
    # 삭제 — 쓰기 차단 > busy > 선택 0 순으로 사유 결정
    if not can_write:
        del_help = write_reason
    elif busy:
        del_help = "처리 중입니다"
    elif int(sel_count) == 0:
        del_help = "삭제할 행을 먼저 선택"
    else:
        del_help = None
    # 저장 — 쓰기 차단 > busy > can_save > dirty 없음 순
    save_help = None
    if not save_enabled:
        if not can_write:
            save_help = write_reason
        elif busy:
            save_help = "저장 처리 중입니다"
        elif not can_save:
            save_help = save_disabled_reason or "지금은 저장할 수 없습니다"
        elif not dirty_total:
            save_help = "저장할 변경이 없습니다"
    save_label = f"저장 · {dirty_total}" if dirty_total else "저장"

    a, d, s, _sp, r = st.columns(list(ratios), vertical_alignment="center")
    a.button("행 추가", key=_css_role_key(state, ADD), icon=":material/add:", width="stretch",
             disabled=not write_ok, help=add_help, on_click=state.action_requester(ADD))
    d.button("삭제", key=_css_role_key(state, DELETE), icon=":material/delete:", width="stretch",
             disabled=(int(sel_count) == 0) or not write_ok, help=del_help,
             on_click=state.action_requester(DELETE))
    s.button(save_label, key=_css_role_key(state, SAVE), type="primary", width="stretch",
             disabled=not save_enabled, help=save_help,
             on_click=state.action_requester(SAVE))
    # 새로고침은 조회 동작 — NOT_READY/PROBE_ERROR 에서도 활성(busy 시에만 비활성).
    r.button("새로고침", key=_css_role_key(state, REFRESH), icon=":material/refresh:", width="stretch",
             disabled=busy, on_click=state.action_requester(REFRESH))


def page_action_specs(
    *,
    sel_count: int,
    dirty_total: int = 0,
    can_save: bool = True,
    can_write: bool = True,
    busy: bool = False,
    save_disabled_reason: str | None = None,
    write_disabled_reason: str | None = None,
) -> list[dict]:
    """액션 버튼(추가·삭제·저장·새로고침)의 활성/사유/라벨을 순수 계산해 스펙 목록으로 반환.

    :func:`master_action_bar` 와 **동일한 규칙**(§8·§20)을 그대로 옮긴 것으로, 라이브
    타이틀 밴드(:class:`~views.master.BandToolbar`)가 인페이지 액션바와 동일한 활성/
    비활성·건수 배지·툴팁 사유를 갖도록 한다. 클릭 플래그(on_click)는 밴드 렌더러가
    ``state.action_requester(role)`` 로 붙이므로 여기서는 표현 스펙만 만든다(순수 함수).

    반환: ``[{role,label,icon,kind,disabled,help}]`` 순서 = ADD, DELETE, SAVE, REFRESH.
    """
    write_reason = write_disabled_reason or _WRITE_DISABLED_DEFAULT
    write_ok = can_write and not busy
    save_enabled = bool(dirty_total) and can_save and write_ok

    add_help = write_reason if not can_write else ("처리 중입니다" if busy else None)
    if not can_write:
        del_help = write_reason
    elif busy:
        del_help = "처리 중입니다"
    elif int(sel_count) == 0:
        del_help = "삭제할 행을 먼저 선택"
    else:
        del_help = None
    save_help = None
    if not save_enabled:
        if not can_write:
            save_help = write_reason
        elif busy:
            save_help = "저장 처리 중입니다"
        elif not can_save:
            save_help = save_disabled_reason or "지금은 저장할 수 없습니다"
        elif not dirty_total:
            save_help = "저장할 변경이 없습니다"
    save_label = f"저장 · {dirty_total}" if dirty_total else "저장"

    return [
        {"role": ADD, "label": "추가", "icon": ":material/add:", "kind": "secondary",
         "disabled": not write_ok, "help": add_help},
        {"role": DELETE, "label": "삭제", "icon": ":material/delete:", "kind": "secondary",
         "disabled": (int(sel_count) == 0) or not write_ok, "help": del_help},
        {"role": SAVE, "label": save_label, "icon": ":material/save:", "kind": "primary",
         "disabled": not save_enabled, "help": save_help},
        {"role": REFRESH, "label": "새로고침", "icon": ":material/refresh:", "kind": "secondary",
         "disabled": busy, "help": None},
    ]


def take_actions(state: DraftState) -> dict[str, bool]:
    """표준 4액션 flag 를 한 번에 소비해 dict 로 반환한다(controller 편의)."""
    return {
        ADD: state.take_action(ADD),
        DELETE: state.take_action(DELETE),
        SAVE: state.take_action(SAVE),
        REFRESH: state.take_action(REFRESH),
    }


def count_strip(existing: int, new: int, changed: int, sel: int, *, groups: int | None = None) -> None:
    """§20 상태 스트립 — 총/신규/기존 변경/선택(0은 생략). 신규·기존 변경 분리 표기.

    dirty_total 은 액션바 badge 한 곳으로 단일화하므로 여기서는 분해값만 보인다.
    """
    parts = [f"총 <b>{int(existing)}</b>건"]
    if groups is not None:
        parts.append(f"그룹 <b>{int(groups)}</b>개")
    if new:
        parts.append(f"신규 <b>{int(new)}</b>건")
    if changed:
        parts.append(f"기존 변경 <b>{int(changed)}</b>건")
    if sel:
        parts.append(f"선택 <b>{int(sel)}</b>건")
    st.markdown(f"<div class='ms-count'>{' · '.join(parts)}</div>", unsafe_allow_html=True)


def dirty_total(new_count: int, changed_count: int) -> int:
    """§20 단일 공식: dirty_total = 신규(미삭제) + 기존 변경."""
    return int(new_count) + int(changed_count)


# ---------------------------------------------------------------------------
# dirty 폐기 게이트 (§17) — filter/refresh/navigation 시 무경고 소실 금지.
# ---------------------------------------------------------------------------
def discard_confirm_bar(state: DraftState) -> str | None:
    """미저장 draft 가 있는데 재적재가 요청됐을 때의 확인 바.

    반환: 'discard'(폐기하고 이동) | 'cancel'(현재 draft 유지) | None(대기).
    controller 는 'discard' 시 ``state.apply_pending_reload()`` 후 재적재, 'cancel' 시
    ``state.cancel_pending_reload()`` 로 draft 를 유지한다.
    """
    if not state.has_pending_reload():
        return None
    st.markdown(
        "<div class='ms-banner warn'><span class='glyph'>⚠</span>"
        "<div>저장되지 않은 변경이 있습니다. 폐기하고 이동할까요?</div></div>",
        unsafe_allow_html=True,
    )
    c1, c2, _sp = st.columns([1.6, 1.2, 5], vertical_alignment="center")
    if c1.button("폐기하고 이동", key=f"{state.page_id}__discard_ok", width="stretch"):
        return "discard"
    if c2.button("취소", key=f"{state.page_id}__discard_cancel", type="primary", width="stretch"):
        return "cancel"
    return None


# ---------------------------------------------------------------------------
# 2단계 확인 바 (§13) — 삭제류. 문구/대상은 domain(controller)이 만든다.
# ---------------------------------------------------------------------------
def confirm_bar(
    state: DraftState,
    *,
    title: str,
    lines: list[str] | None = None,
    confirm_label: str = "삭제 실행",
    cancel_label: str = "취소",
    confirm_enabled: bool = True,
    danger: bool = True,
    scope: str = "del",
) -> str | None:
    """대상 요약 + [취소][실행] 2단계 확인. 'confirm' | 'cancel' | None 반환.

    ``scope`` 로 한 화면에 여러 확인 바(좌/우 패널)를 둘 때 위젯 key 를 격리한다.
    실제 삭제 판정·실행은 controller 가 'confirm' 반환 후 수행한다(여기서는 UI 만).
    """
    kind = "danger" if danger else "warn"
    body = "".join(f"<div>· {line}</div>" for line in (lines or []))
    st.markdown(
        style.banner_html(kind, title, extra=(f"<div class='keys'>{body}</div>" if body else "")),
        unsafe_allow_html=True,
    )
    c1, c2, _sp = st.columns([1.2, 1.4, 4], vertical_alignment="center")
    if c1.button(cancel_label, key=f"{state.page_id}__{scope}_cancel", width="stretch"):
        return "cancel"
    btn_type = "primary" if not danger else "secondary"
    if c2.button(confirm_label, key=f"{state.page_id}__{scope}_ok", width="stretch",
                 type=btn_type, disabled=not confirm_enabled):
        return "confirm"
    return None
