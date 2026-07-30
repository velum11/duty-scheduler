"""기준정보 3화면 공통 기반 패키지 (Phase4 Lane A).

사용자/조직/근무형태 관리 화면(B/C/D)이 공유하는 디자인·상태·그리드·저장 계약을
한 곳에서 제공한다. 화면별 controller/validator/renderer/삭제정책은 각 화면이 소유하고,
이 패키지는 그 위의 골격만 담당한다(공통화 대상만 — Phase2 §2·§3 경계 준수).

공개 API 요약 (B/C/D 가 쓰는 시그니처):

  상태 (state):
    DraftState(page_id)                        page-scoped key factory + dirty 정책
      .action_requester(name) / .take_action(name) / take/clear
      .get_rows/.set_rows/.nonce/.bump_nonce/.grid_key/.next_rid
      .resolve_reload(params, refresh=, dirty=) -> RELOAD|CONFIRM|KEEP
      .apply_pending_reload()/.cancel_pending_reload()
      .set_flash(kind, text)/.pop_flash()
    RELOAD, CONFIRM, KEEP

  그리드 (grid):
    MasterGridSpec(page_id, columns, order, col_config=, select_all=,
                   row_class_rules=, grid_options=, height=,
                   include_group_rows=, include_linked_rows=)
    render_master_grid(spec, frame, key=) -> DataFrame(메타 포함)
    live_rows(df) / grid_bool(v) / master_grid_height(n)
    CORE_META, VIEW_META, META_COLUMNS

  액션 (actions):
    master_action_bar(state, sel_count=, dirty_total=, can_save=, busy=, ...)
    take_actions(state) -> {add,delete,save,refresh: bool}
    count_strip(existing, new, changed, sel, groups=None)
    dirty_total(new, changed)
    discard_confirm_bar(state) -> 'discard'|'cancel'|None
    confirm_bar(state, title=, lines=, confirm_enabled=, scope=) -> 'confirm'|'cancel'|None
    상수: ADD, ADD_GROUP, DELETE, SAVE, REFRESH

  저장/lifecycle (lifecycle):
    run_save(state, validate=, build_candidate=, persist=) -> SaveOutcome
    PersistResult.success/failure/unresolved ; .ok/.partial
    ledger_banner(result)
    Readiness / ReadinessState(.ready/.not_ready/.probe_error/.from_ready_flag)
      .write_enabled/.show_ledger/.banner()/.badge_html()

  스타일 (style):
    inject_page_styles()
    master_screen_head(...)  # 아래 얇은 래퍼
    banner(kind, text, extra) / banner_html(...)
    chip_html(text, kind) / mode_badge_html(connected=, sample=)
    master_row_class_rules(...) / cell_error_rule(field) / cell_dirty_rule(field)
    SELECT_CELL_RULE / GRID_CSS / TOKENS / token(name)
"""
from __future__ import annotations

from html import escape

import streamlit as st

from views.master import actions, grid, lifecycle, paste, state, style
from views.master.actions import (
    ADD,
    ADD_GROUP,
    DELETE,
    REFRESH,
    SAVE,
    confirm_bar,
    count_strip,
    dirty_total,
    discard_confirm_bar,
    master_action_bar,
    page_action_specs,
    take_actions,
)
from views.master.grid import (
    CORE_META,
    META_COLUMNS,
    VIEW_META,
    MasterGridSpec,
    grid_bool,
    live_rows,
    master_grid_height,
    render_master_grid,
)
from views.master.lifecycle import (
    PersistResult,
    Readiness,
    ReadinessState,
    SaveOutcome,
    ledger_banner,
    run_save,
)
from views.master.state import CONFIRM, KEEP, RELOAD, DraftState
from views.master.style import (
    GRID_CSS,
    LIFECYCLE_BADGE,
    SELECT_CELL_RULE,
    TOKENS,
    TOOLBAR_GLYPHS,
    banner,
    banner_html,
    cell_dirty_rule,
    cell_error_rule,
    chip_html,
    lifecycle_badge_html,
    drilldown_context,
    drilldown_context_html,
    empty_state,
    empty_state_html,
    inject_page_styles,
    master_row_class_rules,
    mode_badge_html,
    readiness_badge_html,
    sheet_head,
    sheet_head_html,
    sheet_locked,
    sheet_locked_html,
    token,
)


# KPtech 타이틀 밴드 아이콘(프로토타입: 시각 전용, 흰 라인 아이콘 — currentColor=흰색).
# 리딩 아이콘 1 + 우측 툴바 5(정보·인쇄·저장·즐겨찾기·새로고침). 기능 없음(LOOK 재현).
_ICO_LEAD = (
    "<svg viewBox='0 0 24 24' width='20' height='20' fill='none' stroke='currentColor' "
    "stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'>"
    "<rect x='3' y='4' width='18' height='16' rx='1.5'/><line x1='3' y1='9' x2='21' y2='9'/>"
    "<line x1='9' y1='9' x2='9' y2='20'/></svg>"
)
# 장식 클러스터 아이콘(라벨→글리프). 글리프 path 는 단일 원천(style.TOOLBAR_GLYPHS)에서
# 가져와 기능 아이콘 툴바(mask-image)와 동일한 룩을 보장한다. 정보/인쇄/저장/즐겨찾기/새로고침.
_TOOLBAR = [
    ("정보", TOOLBAR_GLYPHS["info"]),
    ("인쇄", TOOLBAR_GLYPHS["print"]),
    ("저장", TOOLBAR_GLYPHS["save"]),
    ("즐겨찾기", TOOLBAR_GLYPHS["star"]),
    ("새로고침", TOOLBAR_GLYPHS["refresh"]),
]


def _toolbar_html(subset: list | None = None) -> str:
    """밴드 우측 툴바 아이콘 묶음 HTML — 프로토타입(시각 전용).

    ``subset`` 이 주어지면 그 (label, paths) 목록만 렌더한다(라이브 밴드에서 저장·
    새로고침이 실제 버튼으로 승격되면 정보·인쇄·즐겨찾기만 장식으로 남기는 용도).
    """
    spans = []
    for label, paths in (subset if subset is not None else _TOOLBAR):
        spans.append(
            f"<span class='ms-tool' title='{escape(label)}'>"
            "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.8' "
            f"stroke-linecap='round' stroke-linejoin='round'>{paths}</svg></span>"
        )
    return "".join(spans)


# 라이브 밴드의 장식(비기능) 아이콘 — 저장/새로고침은 실제 버튼으로 승격되므로 제외.
_DECOR_TOOLBAR = [t for t in _TOOLBAR if t[0] in ("정보", "인쇄", "즐겨찾기")]


class BandToolbar:
    """라이브 타이틀 밴드의 액션 버튼 슬롯 핸들(:func:`master_screen_head` toolbar 반환).

    밴드 컬럼(``st.columns``)에서 만든 role→슬롯 컨테이너를 들고 있다가, 화면이
    그리드 뒤에서 계산한 액션 스펙으로 실제 ``st.button`` 을 **지연 채움**한다
    (그리드 ``cellValueChanged`` rerun 이후 계산이라야 dirty/선택 건수가 정확하므로,
    밴드를 상단에서 즉시 그리지 않고 슬롯만 잡아 둔 뒤 나중에 채운다). 클릭은 항상
    on_click **플래그**로 남겨(편집 blur 경합에도 유실 없음) controller 가 소비한다.

    두 소비 경로를 모두 지원하는 **범용 툴바**다:
      - 기준정보(DraftState 모델): ``render(state, page_action_specs(...))`` — spec 에
        key/on_click 이 없으면 ``{state.page_id}__{role}`` 키와
        ``state.action_requester(role)`` 플래그를 자동 파생한다(기존 계약 유지).
      - 그 외 화면(자체 flag 패턴, 예: 근무표 편성): ``render(None, specs)`` — 각 spec
        이 고유 ``key`` 와 ``on_click`` 콜백(페이지 flag 세터)을 직접 지정한다.
        DraftState 를 쓰지 않는 화면도 밴드에 임의 flag 액션을 올릴 수 있다.
    """

    def __init__(self, slots: dict) -> None:
        self._slots = slots  # role -> DeltaGenerator(컨테이너)

    def render(self, state, specs: list[dict]) -> None:
        """``specs`` 로 밴드 버튼을 채운다. spec 키: role,label,icon,kind,disabled,help,
        (선택)key,on_click.

        ``key``/``on_click`` 이 spec 에 있으면 그대로 쓰고(화면 고유 flag 패턴), 없으면
        ``state`` 로부터 ``{page_id}__{role}`` 키 + ``action_requester(role)`` 플래그를
        파생한다(기준정보 page-scoped 계약·CSS role-key 선택자 유지). 밴드 버튼은
        ``width="content"`` 로 라벨에 맞는 **콤팩트 아이콘+라벨 툴** 형태로 렌더한다.
        """
        for sp in specs:
            role = sp["role"]
            slot = self._slots.get(role)
            if slot is None:
                continue
            key = sp.get("key")
            if key is None and state is not None:
                key = f"{state.page_id}__{role}"
            on_click = sp.get("on_click")
            if on_click is None and state is not None:
                on_click = state.action_requester(role)
            with slot:
                st.button(
                    sp["label"],
                    key=key,
                    icon=sp.get("icon"),
                    type=sp.get("kind", "secondary"),
                    width="content",
                    disabled=bool(sp.get("disabled", False)),
                    help=sp.get("help"),
                    on_click=on_click,
                )

    def render_icons(self, specs: list[dict]) -> None:
        """KPtech 아이콘 전용 툴바를 채운다(``toolbar="icons"`` 밴드 전용).

        spec 키: ``slot``(0..7 위치), ``type``('button'|'popover'), ``icon``, ``help``
        (tooltip=기능명 — 아이콘 전용이라 필수), ``key``, ``on_click``, ``disabled``,
        ``content``(popover 본문). 클릭 semantics(on_click 플래그)·위젯 key 는 인페이지/pill
        과 동일하게 화면이 지정하며, 여기서는 **렌더만** 한다(라벨 없는 정사각 아이콘 버튼).
        """
        for sp in specs:
            slot = self._slots.get(sp["slot"])
            if slot is None:
                continue
            with slot:
                if sp.get("type") == "popover":
                    pop = st.popover(
                        "", icon=sp.get("icon"), help=sp.get("help"),
                        use_container_width=False,
                    )
                    with pop:
                        st.markdown(sp.get("content", ""))
                else:
                    st.button(
                        "",  # 아이콘 전용 — 라벨 없음
                        key=sp.get("key"),
                        icon=sp.get("icon"),
                        help=sp.get("help"),
                        disabled=bool(sp.get("disabled", False)),
                        on_click=sp.get("on_click"),
                        width="content",
                    )


def icon_toolbar_specs(prefix: str, *, info_content, add, refresh, delete, save) -> list[dict]:
    """KPtech 8-슬롯 아이콘 툴바 스펙(좌→우, :meth:`BandToolbar.render_icons` 입력).

    슬롯: 0 정보(info, popover=화면 설명) · 1 globe(불필요, 항상 shaded) · 2 추가 · 3 조회/
    새로고침 · 4 삭제 · 5 인쇄(Phase2, shaded) · 6 저장 · 7 즐겨찾기(Phase2, shaded).
    기능 4개(``add``/``refresh``/``delete``/``save``)는 각각 ``{key,on_click,disabled,help}``
    dict — 클릭 플래그·비활성/툴팁은 화면이 소유(렌더 위치만 아이콘으로 이전). shaded
    아이콘은 ``{prefix}__{slug}`` 키로 항상 disabled. ``info_content`` 가 없으면 정보도 shaded.
    """
    def _shaded(slot, icon, slug, help_):
        return {"slot": slot, "type": "button", "icon": icon,
                "key": f"{prefix}__{slug}", "disabled": True, "help": help_, "on_click": None}

    def _act(slot, icon, spec, default_help):
        return {"slot": slot, "type": "button", "icon": icon, "key": spec["key"],
                "on_click": spec.get("on_click"), "disabled": bool(spec.get("disabled", False)),
                "help": spec.get("help") or default_help}

    if info_content:
        # 정보: 드롭다운 chevron(▾) 없는 '평범한 아이콘'. 화면 설명은 hover 툴팁(help)로
        # 노출해 장식 클러스터의 정보 아이콘과 동일하게 동작·외형을 맞춘다(popover 트리거의
        # ▾ 가 깨끗한 아이콘 룩을 해쳐 제거). 활성(흰색)이며 클릭은 no-op(on_click=None).
        info = {"slot": 0, "type": "button", "icon": ":material/info:",
                "key": f"{prefix}__info", "disabled": False, "on_click": None,
                "help": info_content}
    else:
        info = _shaded(0, ":material/info:", "info", "정보 (준비 중)")
    return [
        info,
        _shaded(1, ":material/language:", "globe", "불필요"),
        _act(2, ":material/add:", add, "행 추가"),
        _act(3, ":material/search:", refresh, "조회/새로고침"),
        _act(4, ":material/delete:", delete, "삭제"),
        _shaded(5, ":material/print:", "print", "인쇄 (준비 중)"),
        _act(6, ":material/save:", save, "저장"),
        _shaded(7, ":material/star:", "star", "즐겨찾기 (준비 중)"),
    ]


def master_screen_head(
    title: str,
    desc: str,
    *,
    breadcrumb: str | None = None,
    mode_badge: str | None = None,
    toolbar: bool = False,
) -> "BandToolbar | None":
    """§5 페이지 헤더 — KPtech 풀폭 블루 타이틀 밴드 클론(공용 CSS 주입).

    구성(위→아래): breadcrumb(크림 위) → 파랑 밴드[리딩 아이콘+흰 제목 / 모드배지+
    우측 툴바] → 설명(크림 위). ``mode_badge`` 는 ``style.mode_badge_html(...)`` 결과
    (신뢰된 HTML). 데이터 모드 신호 전용이며 readiness/health 를 섞지 않는다(§5).

    기본(``toolbar=False``): 우측 툴바 아이콘은 프로토타입(시각 전용, 기능 없음).
    단일 ``st.markdown`` 으로 그리며 ``None`` 을 반환한다(기존 화면 무변경).

    ``toolbar=True``: 밴드 우측에 **실제 액션 버튼**을 놓기 위해 밴드를
    ``st.container`` + ``st.columns`` 로 구성하고, 각 액션(추가·삭제·저장·새로고침)
    자리에 지연 채움용 슬롯을 만들어 :class:`BandToolbar` 로 반환한다. 화면은 그리드
    뒤 건수 계산 후 ``head.render(state, specs)`` 로 버튼을 채운다(사용자 관리 파일럿).
    """
    inject_page_styles()
    # 파랑 밴드 제거(ADOPTION_SPEC 항목5) — 제목 크롬은 25px/600 + 13.5 설명뿐. 브레드크럼은
    # 상단 52px 헤더(modules/ui.py)가, 연결 pill(=mode_badge 상당)도 상단 헤더가 소유하므로
    # 본문 크롬에서는 렌더하지 않는다(중복 표기 금지). breadcrumb/mode_badge 파라미터는
    # 호출부 호환을 위해 시그니처에 남기되 본문 표기에는 쓰지 않는다.
    _ = breadcrumb, mode_badge
    desc_html = f"<div class='ms-desc'>{escape(desc)}</div>" if desc else ""
    title_chrome = (
        f"<div class='ms-head'><div class='ms-title'>{escape(title)}</div>{desc_html}</div>"
    )

    if not toolbar:
        st.markdown(title_chrome, unsafe_allow_html=True)
        return None

    # 제목 크롬을 먼저 렌더하고, 그 아래에 '얇은 중립 액션 스트립'을 둔다(제목 중복 없음).
    st.markdown(title_chrome, unsafe_allow_html=True)

    # ── toolbar="icons": 중립 액션 스트립 우측에 8개 정사각 아이콘 슬롯(정보·globe·추가·
    # 조회·삭제·인쇄·저장·즐겨찾기). 라벨 없이 아이콘만, tooltip(help)로 기능명 노출. 지연
    # 채움 슬롯을 int(0..7) 키로 만들어 :meth:`BandToolbar.render_icons` 로 채운다.
    # NOTE(P1 이연): add/save/delete 의 '범위 소유 섹션' 재배치는 각 화면 스킨 페이즈(P2/P3)
    # 에서 처리한다(코디네이터 B-reskin-defer 결정). P1 은 파랑→중립 스킨 + 제목 분리만.
    if toolbar == "icons":
        band = st.container(key="ms_iconband")
        with band:
            left, right = st.columns([5.0, 3.0], vertical_alignment="center")
            left.markdown("<div class='ms-band-main'></div>", unsafe_allow_html=True)
            with right:
                with st.container(key="ms_iconbar"):
                    icols = st.columns([1] * 8, vertical_alignment="center")
                    slots = {i: icols[i].container() for i in range(8)}
        return BandToolbar(slots)

    # toolbar=True(legacy 액션 스트립): 우측에 콤팩트 액션 툴(추가·삭제·저장·새로고침).
    band = st.container(key="ms_band_live")
    with band:
        cols = st.columns([6.6, 1.05, 1.05, 1.25, 1.35], vertical_alignment="center")
        cols[0].markdown("<div class='ms-band-main'></div>", unsafe_allow_html=True)
        slots = {
            ADD: cols[1].container(),
            DELETE: cols[2].container(),
            SAVE: cols[3].container(),
            REFRESH: cols[4].container(),
        }
    return BandToolbar(slots)


def show_flash(state: DraftState) -> None:
    """§21 flash 를 배너로 1회 표시한다. kind: success|warning|error|info."""
    msg = state.pop_flash()
    if not msg:
        return
    kind, text = msg
    mapping = {"success": "success", "warning": "warn", "error": "danger", "info": "info"}
    banner(mapping.get(kind, "info"), text)


__all__ = [
    # submodules
    "actions", "grid", "lifecycle", "paste", "state", "style",
    # state
    "DraftState", "RELOAD", "CONFIRM", "KEEP",
    # grid
    "MasterGridSpec", "render_master_grid", "live_rows", "grid_bool",
    "master_grid_height", "CORE_META", "VIEW_META", "META_COLUMNS",
    # actions
    "master_action_bar", "page_action_specs", "BandToolbar", "icon_toolbar_specs",
    "take_actions", "count_strip", "dirty_total",
    "discard_confirm_bar", "confirm_bar",
    "ADD", "ADD_GROUP", "DELETE", "SAVE", "REFRESH",
    # lifecycle
    "run_save", "SaveOutcome", "PersistResult", "ledger_banner",
    "Readiness", "ReadinessState",
    # style
    "inject_page_styles", "master_screen_head", "show_flash",
    "banner", "banner_html", "chip_html", "mode_badge_html", "readiness_badge_html",
    "lifecycle_badge_html", "LIFECYCLE_BADGE",
    "master_row_class_rules", "cell_error_rule", "cell_dirty_rule",
    "SELECT_CELL_RULE", "GRID_CSS", "TOKENS", "token",
    # 조직 3시트 공유 컴포넌트 (Wave2a)
    "drilldown_context", "drilldown_context_html",
    "sheet_head", "sheet_head_html", "sheet_locked", "sheet_locked_html",
    "empty_state", "empty_state_html",
]
