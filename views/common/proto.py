"""신규 화면 프로토타입 공용 표현 조각(숙소 예약 · 업무요청서).

``views/common/erp`` (중립 구조 키트)와 ``views/master`` (헤더 크롬·배지·배너)를 그대로
쓰되, 아차사고 6화면이 **각 파일에 복제해 두고 있는** 표현 관용구(모노 오버라인 섹션 ·
헤어라인 · 진행 단계 pill · 상세 메타 셀 · 본문 블록 · 필수 체크리스트)를 한 곳에 모은
프로토타입 스코프 헬퍼다. 새 시각 언어를 만들지 않는다 — 색·크기·간격은 전부
``DESIGN.md`` §2~§4 값이며 팔레트 밖 색을 도입하지 않는다.

이 모듈은 ``views/common`` (인프라 패키지)에 있어 화면 유형 계약 스캔 대상이 아니다
(``scripts/test_screen_scaffold.py::INFRA_DIRS``). 프로토타입이 채택되면 이 조각들은
``views/common/erp/kit.py`` 로 승격하거나 아차사고 화면과 함께 정합화하는 것이 자연스럽다.
"""
from __future__ import annotations

from html import escape

import streamlit as st

from views.master import lifecycle_badge_html

# ── §2 팔레트(리터럴 고정 — 팔레트 밖 색 금지 §0-8) ─────────────────────────
INK = "#1c1a17"
INK2 = "#4a453d"
MUT = "#6b665d"        # 읽는 작은 텍스트 하한(부속서 A-2: 캔버스 위 5.1:1)
LINE = "#e6e2da"       # 행 헤어라인
LINE_SEC = "#e0dbd2"   # 섹션 헤어라인
LINE_HDR = "#cfc8bd"   # 표 헤더 헤어라인
ACCENT = "#c2410c"
ACCENT_TEXT = "#b4451a"
ACCENT_TINT = "#fdf3ec"
SURFACE_2 = "#fbfaf8"
MONO = "'IBM Plex Mono', monospace"

# 상태 색(§2 배지 팔레트 재사용) — 각 화면은 도메인 상태를 이 5개 코드에 매핑해 넘긴다.
BADGE_SUBMITTED = "SUBMITTED"
BADGE_IN_REVIEW = "IN_REVIEW"
BADGE_EVALUATED = "EVALUATED"
BADGE_REJECTED = "REJECTED"
BADGE_CLOSED = "CLOSED"

PROTO_CSS = f"""
<style>
/* Streamlit 은 마크다운 컨테이너에 margin-bottom:-1rem(= -14px, 앱 루트 14px)을 걸어
   다음 요소를 끌어올린다. 아래 블록들은 바로 뒤에 버튼·범례가 오므로 그 음수 여백이
   **겹침**으로 나타난다(실측: aside 253px 콘텐츠가 239px 박스를 14px 넘어 제출 버튼을 덮음).
   erp 키트가 .erp-lbl 에 쓰는 :has() 선례와 같은 방식으로 해당 컨테이너만 무력화한다
   — 다른 화면(아차사고 등)의 간격 계약은 건드리지 않는다. */
.stApp [data-testid="stMarkdownContainer"]:has(> .pr-aside),
.stApp [data-testid="stMarkdownContainer"]:has(> .pr-hint),
.stApp [data-testid="stMarkdownContainer"]:has(> .pr-meta),
.stApp [data-testid="stMarkdownContainer"]:has(> .pr-blocks),
.stApp [data-testid="stMarkdownContainer"]:has(> .pr-steps),
.stApp [data-testid="stMarkdownContainer"]:has(> .pr-cap),
.stApp [data-testid="stMarkdownContainer"]:has(> .pr-cal) {{ margin-bottom: 0 !important; }}
/* 블록(지표 스트립 등) 아래 붙는 한 줄 캡션 — 다음 영역(조건 줄)과 붙지 않게 여백 확보. */
.pr-cap {{ font-size:12.5px; color:{MUT}; line-height:1.5; margin:0 0 2px; }}
/* 제출 버튼 위 안내 한 줄 — 헤어라인 위, 카드 아님 */
.pr-hint {{ padding:16px 0 0; margin-top:12px; border-top:1px solid {LINE_SEC};
  font-size:12.5px; color:{MUT}; line-height:1.5; }}
.pr-hint b {{ color:{INK}; font-weight:600; }}
/* 섹션 오버라인(모노) + 헤어라인 — 폼형 §1-D */
.pr-sec {{ display:flex; align-items:center; gap:10px; margin:18px 0 2px; }}
.pr-sec .ov {{ font-family:{MONO}; font-size:11px; letter-spacing:.14em; color:{ACCENT_TEXT};
  white-space:nowrap; }}
.pr-sec .rule {{ flex:1; height:1px; background:{LINE}; }}
.pr-sec .opt {{ font-size:12px; color:{MUT}; white-space:nowrap; }}
/* 신원 줄 — 카드 아님(헤어라인만) */
.pr-idrow {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:.4rem 1.4rem;
  padding:0 0 12px; border-bottom:1px solid {LINE_SEC}; margin:2px 0 4px; }}
.pr-idrow .ov {{ font-family:{MONO}; font-size:10px; letter-spacing:.14em; color:{MUT};
  flex:0 0 auto; }}
.pr-idrow .it {{ display:flex; gap:.4rem; align-items:baseline; font-size:13.5px; }}
.pr-idrow .k {{ color:{MUT}; }}
.pr-idrow .v {{ color:{INK}; font-weight:600; }}
.pr-idrow .lock {{ margin-left:auto; font-size:12px; color:{MUT}; white-space:nowrap; }}
/* 우측 aside(체크리스트·가용 현황) — 좌측 헤어라인, 카드 아님 */
.pr-aside {{ display:flex; flex-direction:column; gap:10px; padding-left:20px;
  border-left:1px solid {LINE_SEC}; }}
.pr-aside .hd {{ display:flex; align-items:center; justify-content:space-between; gap:8px; }}
.pr-aside .hd .ov {{ font-family:{MONO}; font-size:10px; letter-spacing:.14em; color:{MUT}; }}
.pr-aside .hd .cnt {{ font-family:{MONO}; font-size:11.5px; font-weight:600; color:{ACCENT_TEXT}; }}
.pr-aside .bar {{ height:3px; border-radius:999px; background:{LINE}; overflow:hidden; }}
.pr-aside .bar > i {{ display:block; height:100%; background:{ACCENT}; }}
.pr-aside .items {{ display:flex; flex-wrap:wrap; gap:9px 16px; margin-top:2px; }}
.pr-aside .ci {{ flex:1 1 130px; min-width:0; display:flex; align-items:center; gap:9px;
  font-size:13px; color:{INK2}; }}
.pr-aside .ci .box {{ width:14px; height:14px; border-radius:4px; border:1px solid {LINE_HDR};
  flex:0 0 14px; display:inline-flex; align-items:center; justify-content:center; }}
.pr-aside .ci.on .box {{ background:{ACCENT}; border-color:{ACCENT}; color:#fff; font-size:10px; }}
.pr-aside .ci.on {{ color:{INK}; }}
.pr-aside .note {{ margin:8px 0 0; padding-top:12px; border-top:1px solid {LINE};
  font-size:12px; line-height:1.6; color:{MUT}; text-wrap:pretty; }}
.pr-aside .kv {{ display:flex; justify-content:space-between; gap:10px; font-size:12.5px;
  color:{INK2}; line-height:1.5; }}
.pr-aside .kv b {{ color:{INK}; font-weight:600; font-variant-numeric:tabular-nums; }}
/* 상세 메타 셀(라벨 모노 오버라인 / 값) — 박스 없음 */
.pr-meta {{ display:flex; flex-wrap:wrap; gap:12px 26px; }}
.pr-meta .c {{ display:flex; flex-direction:column; gap:3px; min-width:0; }}
.pr-meta .l {{ font-size:10.5px; letter-spacing:.08em; color:{MUT}; font-family:{MONO}; }}
.pr-meta .v {{ font-size:13.5px; color:{INK}; line-height:1.35; }}
/* 본문 블록 — 좌측 2px 보더 + 모노 태그 + 라벨 + 본문 14.5/1.7 */
.pr-blocks {{ display:flex; flex-wrap:wrap; gap:20px 32px; }}
.pr-blocks .b {{ min-width:0; border-left:2px solid {LINE_SEC}; padding-left:14px;
  display:flex; flex-direction:column; gap:6px; }}
.pr-blocks .t {{ font-size:11px; letter-spacing:.1em; color:{MUT}; font-family:{MONO}; }}
.pr-blocks .l {{ font-size:12.5px; font-weight:600; color:{INK2}; }}
.pr-blocks p {{ margin:0; font-size:14.5px; line-height:1.7; color:{INK};
  text-wrap:pretty; white-space:pre-wrap; }}
/* 진행 단계 pill */
.pr-steps {{ display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin:12px 0 16px; }}
/* 큐 헤더 */
.pr-qhead {{ display:flex; align-items:center; gap:8px; margin:2px 0 6px; }}
.pr-qhead .t {{ font-size:14px; font-weight:600; color:{INK}; }}
.pr-qhead .c {{ font-family:{MONO}; font-size:11px; font-weight:600; padding:2px 8px;
  border-radius:999px; background:{ACCENT_TINT}; color:{ACCENT_TEXT}; }}
.pr-qpos {{ font-family:{MONO}; font-size:11.5px; color:{MUT}; white-space:nowrap; }}
/* 큐 칩(선택=primary 오렌지) — pill, 히트영역 32px */
[class*="st-key-prq_"] button {{
  border-radius:999px !important; min-height:32px !important; height:auto !important;
  padding:5px 14px !important; font-size:12.5px !important; font-weight:600 !important;
  white-space:nowrap !important; line-height:1.2 !important; }}
/* 이전/다음 나브 — 32x32 정사각. '이번 달'은 라벨 폭이 필요하므로 높이만 맞춘다
   (§0.6·§4 데스크톱 히트영역 ≥32px — Streamlit 기본 30px 보정). */
.st-key-pr_prev button, .st-key-pr_next button {{
  min-width:32px !important; width:32px !important; min-height:32px !important;
  height:32px !important; padding:0 !important; border-radius:7px !important;
  font-size:14px !important; }}
.st-key-lc_today button {{ min-height:32px !important; height:32px !important;
  border-radius:7px !important; font-size:12.5px !important; padding:0 12px !important;
  white-space:nowrap !important; }}
/* 액션 버튼 — 히트영역 34px. 폼형 제출 앵커(lr_submit_btn)도 같은 높이 계약을 쓴다
   (LRQ-4 실측: Streamlit 기본 30px → 34px). 화면 로컬 CSS 를 만들지 않기 위해 여기서 소유. */
[class*="st-key-pract_"] button,
[class*="st-key-lr_submit_btn"] button {{
  min-height:34px !important; border-radius:8px !important; font-size:13px !important;
  font-weight:600 !important; white-space:nowrap !important; }}
/* primary 제출 앵커의 비활성 상태 — 앱 전역 CSS 가 primary 배경을 !important 로 고정해
   비활성이 활성과 구분되지 않았다(실측: 동일 오렌지·opacity 1). 채움을 빼고 §2 라인·
   보조 텍스트 색으로 떨어뜨려 "지금은 누를 수 없다"를 형태와 색으로 함께 알린다
   (help 툴팁 래퍼 유무와 무관하게 같은 결과가 나오도록 명시 지정). */
[class*="st-key-lr_submit_btn"] button:disabled {{
  background:transparent !important; border:1px solid {LINE_SEC} !important;
  color:{MUT} !important; }}
/* 파괴적 확인(예약 취소 확정) — 확인 팝업 안에서만 쓰는 danger 버튼. 색은 §2 반려색
   재사용(새 색 없음)이며 [돌아가기]는 secondary 로 남겨 되돌릴 수 있음을 표시한다. */
[class*="st-key-prdanger_"] button {{
  background:#9c3232 !important; border-color:#9c3232 !important; color:#ffffff !important;
  min-height:34px !important; border-radius:8px !important; font-weight:600 !important; }}
[class*="st-key-prdanger_"] button:hover {{ opacity:.92; }}
[class*="st-key-prdanger_"] button:focus-visible {{ outline:2px solid {ACCENT} !important;
  outline-offset:2px; }}
/* 목록형 아코디언 행 = 전체폭 클릭 버튼(카드 금지 — 헤어라인 + 좌측 상태 색바) */
[class*="st-key-prrow_"] button {{
  width:100%; text-align:left; justify-content:flex-start;
  background:transparent !important; border:none !important;
  border-bottom:1px solid {LINE} !important; border-left:3px solid transparent !important;
  border-radius:0 !important; padding:13px 12px !important; min-height:52px !important;
  font-size:14.5px !important; font-weight:500 !important; color:{INK} !important;
  box-shadow:none !important; white-space:normal !important; line-height:1.4 !important; }}
[class*="st-key-prrow_"] button > div {{ justify-content:flex-start; text-align:left;
  flex:1 1 auto; min-width:0; }}
[class*="st-key-prrow_"] button:hover {{ background:#faf8f4 !important; }}
[class*="st-key-prrow_"] button:focus-visible {{ outline:2px solid {ACCENT} !important;
  outline-offset:-2px; }}
[class*="__b_SUBMITTED__"] button {{ border-left-color:#8a6212 !important; }}
[class*="__b_IN_REVIEW__"] button {{ border-left-color:#2f4d99 !important; }}
[class*="__b_EVALUATED__"] button {{ border-left-color:#2f6b45 !important; }}
[class*="__b_REJECTED__"] button {{ border-left-color:#9c3232 !important; }}
[class*="__b_CLOSED__"] button {{ border-left-color:#5c564d !important; }}
[class*="__shut"] button::after {{ content:"\\203A"; margin-left:auto; padding-left:10px;
  color:#8b857c; font-size:17px; }}
[class*="__open"] button::after {{ content:"\\02C5"; margin-left:auto; padding-left:10px;
  color:{ACCENT}; font-size:17px; }}
[class*="__open"] button {{ background:{ACCENT_TINT} !important; }}
[class*="__open"] button:hover {{ background:#fbe9dc !important; }}
/* 월 캘린더 — 구글 캘린더식 주(week) 행 + 기간 전체가 이어지는 예약 막대 */
.pr-cal {{ border:1px solid {LINE_HDR}; border-radius:8px; overflow:hidden;
  background:#ffffff; }}
.pr-cal-hd {{ display:grid; grid-template-columns:repeat(7,1fr);
  border-bottom:1px solid {LINE_HDR}; }}
.pr-cal-hd span {{ padding:7px 8px; font-size:12.5px; font-weight:600; color:{INK2};
  text-align:center; border-left:1px solid {LINE}; }}
.pr-cal-hd span:first-child {{ border-left:0; color:#9c3232; }}
.pr-cal-hd span:last-child {{ color:#2f4d99; }}
.pr-cw {{ position:relative; border-top:1px solid {LINE}; }}
.pr-cal-hd + .pr-cw {{ border-top:0; }}
.pr-cw-days {{ display:grid; grid-template-columns:repeat(7,1fr); height:100%; }}
.pr-cw-d {{ border-left:1px solid {LINE}; padding:4px 8px 2px; min-width:0; }}
.pr-cw-d:first-child {{ border-left:0; }}
.pr-cw-d.out {{ background:{SURFACE_2}; }}
.pr-cw-d.today {{ background:{ACCENT_TINT}; }}
.pr-cw-d .n {{ font-family:{MONO}; font-size:12px; font-weight:600; color:{INK2};
  white-space:nowrap; }}
.pr-cw-d.out .n {{ color:#a09a90; }}
.pr-cw-d.today .n {{ color:{ACCENT_TEXT}; }}
/* 막대 레이어 — 날짜 칸 위에 절대배치. 주 경계를 넘는 예약은 끊긴 모서리(radius 0)로
   이어짐을 표현한다(구글 캘린더 관용구). */
.pr-cw-bars {{ position:absolute; left:0; right:0; top:26px; bottom:4px;
  pointer-events:none; }}
.pr-gbar {{ position:absolute; height:20px; display:flex; align-items:center;
  font-size:11.5px; font-weight:600; padding:0 8px; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; pointer-events:auto; }}
/* 본인 예약 — 채움색은 숙소색 그대로 두고 좌측 3px 액센트 캡으로 소유권만 덧입힌다
   (시작 세그먼트에만. 이어지는 주에는 캡이 없어 '시작'이 어디인지도 함께 읽힌다). */
.pr-gbar.mine {{ box-shadow:inset 3px 0 {ACCENT}; }}
/* 범례 */
.pr-legend {{ display:flex; flex-wrap:wrap; align-items:center; gap:6px 16px;
  margin:8px 0 2px; font-size:12px; color:{INK2}; }}
.pr-legend i {{ display:inline-block; width:11px; height:11px; border-radius:3px;
  margin-right:6px; vertical-align:-1px; border:1px solid; }}
/* 범례 견본 변형 — 막대의 실제 표현(점선 테두리 · 좌측 액센트 캡)을 그대로 축소 재현. */
.pr-legend i.dashed {{ border-style:dashed; }}
/* 캡 견본은 호출부 인라인 border-color 를 좌측만 덮어써야 하므로 !important 가 필요하다. */
.pr-legend i.cap {{ border-left-width:3px !important;
  border-left-color:{ACCENT} !important; }}
/* 캘린더 조회 조건 + 월 이동 병합 줄(LCAL-3) — 조건 셀렉트 줄과 ‹·이번 달·› 나브를 한
   줄에 둔다. 안쪽 erpcond 스트립의 하단 헤어라인/여백을 이 래퍼로 올려 헤어라인이 줄
   전체를 가로지르게 한다(§1-E 필터 줄 표현 유지 — 카드 아님). 다른 화면 무영향. */
.st-key-lc_condrow {{ border-bottom:1px solid {LINE_SEC}; padding-bottom:10px;
  margin-bottom:10px; }}
.st-key-lc_condrow [class*="st-key-erpcond_"] {{ border-bottom:0 !important;
  padding-bottom:0 !important; margin-bottom:0 !important; }}
/* 좁은 폭(≤900px): 우측 aside 가 본문 아래로 내려간다 */
@media (max-width:900px) {{
  .st-key-pr_formwrap div[data-testid="stHorizontalBlock"] {{ flex-direction:column; }}
  .st-key-pr_formwrap div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {{
    width:100% !important; flex:1 1 100% !important; }}
  .pr-aside {{ padding-left:0; border-left:0; border-top:1px solid {LINE_SEC};
    padding-top:14px; }}
}}
</style>
"""


def inject() -> None:
    """프로토타입 화면 공용 CSS 주입(화면 render 시작에서 1회)."""
    st.markdown(PROTO_CSS, unsafe_allow_html=True)


def hairline(top: str = "2px", bottom: str = "10px") -> None:
    st.markdown(
        f"<div style='border-top:1px solid {LINE_SEC};margin:{top} 0 {bottom};'></div>",
        unsafe_allow_html=True,
    )


def section(num: str, label: str, opt: str = "") -> None:
    """폼형 섹션 헤더(§1-D) — ``01 · 기본 정보`` 모노 오버라인 + 헤어라인."""
    right = f"<span class='opt'>{escape(opt)}</span>" if opt else ""
    st.markdown(
        f"<div class='pr-sec'><span class='ov'>{escape(num)} · {escape(label)}</span>"
        f"<span class='rule'></span>{right}</div>",
        unsafe_allow_html=True,
    )


def identity_row(overline: str, pairs: list[tuple[str, str]], lock: str = "") -> None:
    """신원 읽기 전용 줄 — 세션에서 확정된 신청자/요청자 정보(수정 불가)."""
    items = "".join(
        f"<span class='it'><span class='k'>{escape(k)}</span>"
        f"<span class='v'>{escape(v or '-')}</span></span>"
        for k, v in pairs
    )
    lock_html = f"<span class='lock'>{escape(lock)}</span>" if lock else ""
    st.markdown(
        f"<div class='pr-idrow'><span class='ov'>{escape(overline)}</span>{items}{lock_html}</div>",
        unsafe_allow_html=True,
    )


def badge(badge_code: str, label: str) -> str:
    """상태 배지 HTML — ``views/master`` 라이프사이클 팔레트를 그대로 쓴다(새 색 없음)."""
    return lifecycle_badge_html(badge_code, label)


def meta_cells(cells: list[tuple]) -> str:
    """상세 메타 셀 묶음 HTML. ``(label, value)`` 또는 ``(label, html, "html")``."""
    parts = []
    for cell in cells:
        label, value = cell[0], cell[1]
        is_html = len(cell) > 2 and cell[2] == "html"
        v = value if is_html else escape(str(value if value not in (None, "") else "-"))
        parts.append(
            f"<div class='c'><span class='l'>{escape(str(label))}</span>"
            f"<span class='v'>{v}</span></div>"
        )
    return f"<div class='pr-meta'>{''.join(parts)}</div>"


def body_blocks(blocks: list[tuple]) -> str:
    """본문 블록 묶음 HTML. ``(TAG, 라벨, 값, 긴항목여부)``."""
    cells = []
    for tag, label, value, long in blocks:
        flex = "2 1 420px" if long else "1 1 260px"
        body = escape(str(value or "")).strip() or "-"
        cells.append(
            f"<div class='b' style='flex:{flex};'><span class='t'>{escape(tag)}</span>"
            f"<span class='l'>{escape(label)}</span><p>{body}</p></div>"
        )
    return f"<div class='pr-blocks'>{''.join(cells)}</div>"


def _step_pill(dot: str, txt: str, bg: str, bd: str, label: str) -> str:
    return (
        f"<span style='display:inline-flex;align-items:center;gap:6px;padding:4px 11px;"
        f"border-radius:999px;border:1px solid {bd};background:{bg};font-size:12px;"
        f"font-weight:600;color:{txt};white-space:nowrap;'>"
        f"<span style='width:7px;height:7px;border-radius:50%;background:{dot};"
        f"flex:0 0 auto;'></span>{escape(label)}</span>"
    )


def steps_html(order: list[tuple[str, str]], status: str,
               branch: tuple[str, str] | None = None) -> str:
    """진행 단계 pill. ``order``=[(코드, 라벨)], ``status``=현재 코드.

    ``branch``=(분기코드, 라벨) 이면 현재 상태가 그 분기일 때 첫 단계만 도달로 두고
    끝에 danger pill 을 덧붙인다(반려·취소 같은 종결 분기)."""
    codes = [c for c, _ in order]
    on_branch = bool(branch) and status == branch[0]
    cur = codes.index(status) if status in codes else 0
    pills = []
    for i, (_code, label) in enumerate(order):
        reached = (i == 0) if on_branch else (i <= cur)
        if reached:
            pills.append(_step_pill(ACCENT, INK, ACCENT_TINT, "#f0dfd0", label))
        else:
            pills.append(_step_pill(LINE_HDR, MUT, "transparent", LINE, label))
    if on_branch:
        pills.append(_step_pill("#9c3232", "#9c3232", "#fbeeee", "#f0d9d9", branch[1]))
    return f"<div class='pr-steps'>{''.join(pills)}</div>"


def checklist_html(items: list[tuple[str, bool]], note: str = "",
                   overline: str = "CHECKLIST") -> str:
    """필수 항목 체크리스트 + 진행 바(§1-D 우측 aside). ``items``=[(라벨, 충족여부)]."""
    done = sum(1 for _, ok in items if ok)
    total = len(items) or 1
    pct = round(done / total * 100)
    cells = "".join(
        f"<div class='{'ci on' if ok else 'ci'}'><span class='box'>{'✓' if ok else ''}</span>"
        f"<span>{escape(label)}</span></div>"
        for label, ok in items
    )
    note_html = f"<p class='note'>{escape(note)}</p>" if note else ""
    return (
        f"<div class='pr-aside'><div class='hd'><span class='ov'>{escape(overline)}</span>"
        f"<span class='cnt'>{done} / {len(items)}</span></div>"
        f"<div class='bar'><i style='width:{pct}%'></i></div>"
        f"<div class='items'>{cells}</div>{note_html}</div>"
    )


def aside_kv(overline: str, rows: list[tuple[str, str]], note: str = "") -> str:
    """우측 aside 의 간단한 key/value 패널(가용 현황 등). 카드 아님(좌측 헤어라인)."""
    body = "".join(
        f"<div class='kv'><span>{escape(str(k))}</span><b>{escape(str(v))}</b></div>"
        for k, v in rows
    )
    note_html = f"<p class='note'>{escape(note)}</p>" if note else ""
    return (
        f"<div class='pr-aside'><div class='hd'><span class='ov'>{escape(overline)}</span></div>"
        f"{body}{note_html}</div>"
    )


def queue_head(title: str, count: int) -> None:
    st.markdown(
        f"<div class='pr-qhead'><span class='t'>{escape(title)}</span>"
        f"<span class='c'>{int(count)}</span></div>",
        unsafe_allow_html=True,
    )


#: 범례 견본 표현 종류 — 막대의 실제 표현과 1:1(solid=채움, dashed=점선 테두리,
#: cap=좌측 액센트 캡). 색은 호출부가 §2 팔레트 값으로 넘긴다(여기서 새 색을 만들지 않음).
LEGEND_KINDS = ("solid", "dashed", "cap")


def legend(items: list[tuple]) -> None:
    """범례 — ``(라벨, 배경색, 테두리/텍스트색)`` 또는 ``(라벨, 배경색, 테두리색, 종류)``.

    ``종류`` 는 :data:`LEGEND_KINDS` 중 하나이며 생략하면 ``"solid"`` 다. 캘린더 막대가
    채움색 외에 점선 테두리(승인대기)·좌측 액센트 캡(본인 예약)으로도 의미를 싣기
    때문에, 범례 견본이 그 표현을 그대로 축소 재현할 수 있어야 한다(§4 이중부호화의
    범례 대응). 알 수 없는 종류는 ``solid`` 로 떨어뜨린다.
    """
    parts = []
    for item in items:
        label, bg, fg = item[0], item[1], item[2]
        kind = item[3] if len(item) > 3 else "solid"
        cls = f" class='{kind}'" if kind in LEGEND_KINDS and kind != "solid" else ""
        parts.append(
            f"<span><i{cls} style='background:{bg};border-color:{fg};'></i>"
            f"{escape(str(label))}</span>"
        )
    st.markdown(f"<div class='pr-legend'>{''.join(parts)}</div>", unsafe_allow_html=True)


def submit_hint(text: str, strong: str = "", tail: str = "") -> None:
    """제출 컨트롤 바로 위의 한 줄 안내(헤어라인 위). 값은 전부 escape 한다."""
    body = escape(text)
    if strong:
        body += f"<b>{escape(strong)}</b>"
    if tail:
        body += escape(tail)
    st.markdown(f"<div class='pr-hint'>{body}</div>", unsafe_allow_html=True)


def caption_line(text: str) -> None:
    """앞 블록에 딸린 한 줄 캡션(지표 스트립의 집계 범위 등).

    :func:`note_line` 과 달리 마크다운 컨테이너의 음수 여백을 무력화해 **다음 영역과
    붙지 않는다** — 조건 줄 바로 위처럼 두 영역 사이에 놓일 때 쓴다.
    """
    st.markdown(f"<div class='pr-cap'>{escape(text)}</div>", unsafe_allow_html=True)


def note_line(text: str) -> None:
    st.markdown(
        f"<div style='font-size:12.5px;color:{MUT};line-height:1.6;margin:6px 0 2px;'>"
        f"{escape(text)}</div>",
        unsafe_allow_html=True,
    )


__all__ = [
    "INK", "INK2", "MUT", "LINE", "LINE_SEC", "LINE_HDR", "ACCENT", "ACCENT_TEXT",
    "ACCENT_TINT", "SURFACE_2", "MONO", "PROTO_CSS",
    "BADGE_SUBMITTED", "BADGE_IN_REVIEW", "BADGE_EVALUATED", "BADGE_REJECTED",
    "BADGE_CLOSED", "LEGEND_KINDS",
    "inject", "hairline", "section", "identity_row", "badge", "meta_cells",
    "body_blocks", "steps_html", "checklist_html", "aside_kv", "queue_head",
    "legend", "caption_line", "note_line", "submit_hint",
]
