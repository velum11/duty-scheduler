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
# 인라인 style 속성 안에 그대로 보간되므로 내부는 **큰따옴표**여야 한다 —
# style='font-family:{MONO};…' 에 작은따옴표가 들어가면 속성이 첫 내부 따옴표에서
# 끊겨 style 전체가 소실된다(2026-08-14 아차사고 6화면 실측, 2026-08-15 이 상수에서 재발 확인:
# 숙소 예약 관리·내 숙소 예약·업무요청 처리 상세의 신청번호가 모노 18px 을 잃고 있었다).
MONO = '"IBM Plex Mono", monospace'

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
.stApp [data-testid="stMarkdownContainer"]:has(> .pr-cal),
.stApp [data-testid="stMarkdownContainer"]:has(> .pr-dow),
.stApp [data-testid="stMarkdownContainer"]:has(> .pr-flabel),
.stApp [data-testid="stMarkdownContainer"]:has(> .pr-substat),
.stApp [data-testid="stMarkdownContainer"]:has(> .pr-mini-wrap),
.stApp [data-testid="stMarkdownContainer"]:has(> .pr-legend),
.stApp [data-testid="stMarkdownContainer"]:has(> .pr-calttl) {{ margin-bottom: 0 !important; }}
/* 블록(지표 스트립 등) 아래 붙는 한 줄 캡션 — 다음 영역(조건 줄)과 붙지 않게 여백 확보.
   폰트는 전부 DESIGN §1.2 5단(28/20/16/14/12)만 쓴다 — 2026-08-18 신판 토큰 정합. */
.pr-cap {{ font-size:12px; color:{MUT}; line-height:1.5; margin:0 0 2px; }}
/* 제출 버튼 위 안내 한 줄 — 헤어라인 위, 카드 아님 */
.pr-hint {{ padding:16px 0 0; margin-top:12px; border-top:1px solid {LINE_SEC};
  font-size:12px; color:{MUT}; line-height:1.5; }}
.pr-hint b {{ color:{INK}; font-weight:600; }}
/* 섹션 오버라인(모노) + 헤어라인 — FORM_ENTRY 섹션 구획(§2) */
.pr-sec {{ display:flex; align-items:center; gap:12px; margin:16px 0 2px; }}
.pr-sec .ov {{ font-family:{MONO}; font-size:12px; letter-spacing:.14em; color:{ACCENT_TEXT};
  white-space:nowrap; }}
.pr-sec .rule {{ flex:1; height:1px; background:{LINE}; }}
.pr-sec .opt {{ font-size:12px; color:{MUT}; white-space:nowrap; }}
/* 신원 줄 — 카드 아님(헤어라인만) */
.pr-idrow {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:.4rem 1.4rem;
  padding:0 0 12px; border-bottom:1px solid {LINE_SEC}; margin:2px 0 4px; }}
.pr-idrow .ov {{ font-family:{MONO}; font-size:12px; letter-spacing:.14em; color:{MUT};
  flex:0 0 auto; }}
.pr-idrow .it {{ display:flex; gap:.4rem; align-items:baseline; font-size:14px; }}
.pr-idrow .k {{ color:{MUT}; }}
.pr-idrow .v {{ color:{INK}; font-weight:600; }}
.pr-idrow .lock {{ margin-left:auto; font-size:12px; color:{MUT}; white-space:nowrap; }}
/* 우측 aside(체크리스트·가용 현황) — 좌측 헤어라인, 카드 아님 */
.pr-aside {{ display:flex; flex-direction:column; gap:10px; padding-left:20px;
  border-left:1px solid {LINE_SEC}; }}
.pr-aside .hd {{ display:flex; align-items:center; justify-content:space-between; gap:8px; }}
.pr-aside .hd .ov {{ font-family:{MONO}; font-size:12px; letter-spacing:.14em; color:{MUT}; }}
.pr-aside .hd .cnt {{ font-family:{MONO}; font-size:12px; font-weight:600; color:{ACCENT_TEXT}; }}
.pr-aside .bar {{ height:3px; border-radius:999px; background:{LINE}; overflow:hidden; }}
.pr-aside .bar > i {{ display:block; height:100%; background:{ACCENT}; }}
.pr-aside .items {{ display:flex; flex-wrap:wrap; gap:9px 16px; margin-top:2px; }}
.pr-aside .ci {{ flex:1 1 130px; min-width:0; display:flex; align-items:center; gap:8px;
  font-size:14px; color:{INK2}; }}
.pr-aside .ci .box {{ width:14px; height:14px; border-radius:4px; border:1px solid {LINE_HDR};
  flex:0 0 14px; display:inline-flex; align-items:center; justify-content:center; }}
.pr-aside .ci.on .box {{ background:{ACCENT}; border-color:{ACCENT}; color:#fff; font-size:10px; }}
.pr-aside .ci.on {{ color:{INK}; }}
.pr-aside .note {{ margin:8px 0 0; padding-top:12px; border-top:1px solid {LINE};
  font-size:12px; line-height:1.6; color:{MUT}; text-wrap:pretty; }}
.pr-aside .kv {{ display:flex; justify-content:space-between; gap:12px; font-size:12px;
  color:{INK2}; line-height:1.5; }}
.pr-aside .kv b {{ color:{INK}; font-weight:600; font-variant-numeric:tabular-nums; }}
/* 상세 메타 셀(라벨 모노 오버라인 / 값) — 박스 없음 */
.pr-meta {{ display:flex; flex-wrap:wrap; gap:12px 26px; }}
.pr-meta .c {{ display:flex; flex-direction:column; gap:3px; min-width:0; }}
/* 라벨은 한글이라 모노·자간을 걸지 않는다 — 모노 폴백이 한글을 벌려 놓는다("신 청 자",
   실측 2026-08-18). 영문 오버라인(REQUESTER 등)만 모노 자간을 유지한다. */
.pr-meta .l {{ font-size:12px; color:{MUT}; }}
.pr-meta .v {{ font-size:14px; color:{INK}; line-height:1.35; }}
/* 본문 블록 — 좌측 2px 보더 + 모노 태그 + 라벨 + 본문 14.5/1.7 */
.pr-blocks {{ display:flex; flex-wrap:wrap; gap:20px 32px; }}
.pr-blocks .b {{ min-width:0; border-left:2px solid {LINE_SEC}; padding-left:14px;
  display:flex; flex-direction:column; gap:6px; }}
.pr-blocks .t {{ font-size:12px; letter-spacing:.1em; color:{MUT}; font-family:{MONO}; }}
.pr-blocks .l {{ font-size:12px; font-weight:600; color:{INK2}; }}
.pr-blocks p {{ margin:0; font-size:14px; line-height:1.7; color:{INK};
  text-wrap:pretty; white-space:pre-wrap; }}
/* 진행 단계 pill */
.pr-steps {{ display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin:12px 0 16px; }}
/* 큐 헤더 */
.pr-qhead {{ display:flex; align-items:center; gap:8px; margin:2px 0 6px; }}
.pr-qhead .t {{ font-size:14px; font-weight:600; color:{INK}; }}
.pr-qhead .c {{ font-family:{MONO}; font-size:12px; font-weight:600; padding:2px 8px;
  border-radius:999px; background:{ACCENT_TINT}; color:{ACCENT_TEXT}; }}
.pr-qpos {{ font-family:{MONO}; font-size:12px; color:{MUT}; white-space:nowrap; }}
/* 큐 칩(선택=primary 오렌지) — pill, 히트영역 §1.4 compact 하한 34px */
[class*="st-key-prq_"] button {{
  border-radius:999px !important; min-height:34px !important; height:auto !important;
  padding:5px 14px !important; font-size:12px !important; font-weight:600 !important;
  white-space:nowrap !important; line-height:1.2 !important; }}
/* 이전/다음 나브 — 34x34 정사각(§1.4 compact 34~38). '이번 달'은 라벨 폭이 필요하므로
   높이만 맞춘다. */
.st-key-pr_prev button, .st-key-pr_next button {{
  min-width:34px !important; width:34px !important; min-height:34px !important;
  height:34px !important; padding:0 !important; border-radius:7px !important;
  font-size:14px !important; }}
.st-key-lc_today button {{
  min-height:34px !important; height:34px !important;
  border-radius:7px !important; font-size:12px !important; padding:0 12px !important;
  white-space:nowrap !important; }}
/* 액션 버튼 — 히트영역 34px(§1.4 compact). 폼형 제출 앵커(lr_submit_btn)도 같은 높이
   계약을 쓴다. 화면 로컬 CSS 를 만들지 않기 위해 여기서 소유. */
[class*="st-key-pract_"] button {{
  min-height:34px !important; border-radius:8px !important; font-size:14px !important;
  font-weight:600 !important; white-space:nowrap !important; }}
[class*="st-key-lr_submit_btn"] button {{
  min-height:40px !important; border-radius:8px !important; font-size:14px !important;
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
  border-radius:0 !important; padding:12px !important; min-height:52px !important;
  font-size:14px !important; font-weight:500 !important; color:{INK} !important;
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
[class*="__shut"] button::after {{ content:"\\203A"; margin-left:auto; padding-left:12px;
  color:#8b857c; font-size:16px; }}
[class*="__open"] button::after {{ content:"\\02C5"; margin-left:auto; padding-left:12px;
  color:{ACCENT}; font-size:16px; }}
[class*="__open"] button {{ background:{ACCENT_TINT} !important; }}
[class*="__open"] button:hover {{ background:#fbe9dc !important; }}
/* 월 캘린더 — 구글 캘린더식 주(week) 행 + 기간 전체가 이어지는 예약 막대 */
.pr-cal {{ border:1px solid {LINE_HDR}; border-radius:8px; overflow:hidden;
  background:#ffffff; }}
.pr-cal-hd {{ display:grid; grid-template-columns:repeat(7,1fr);
  border-bottom:1px solid {LINE_HDR}; }}
.pr-cal-hd span {{ padding:8px; font-size:12px; font-weight:600; color:{INK2};
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
  font-size:12px; font-weight:600; padding:0 8px; white-space:nowrap;
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
/* 신청 화면 인라인 달력 선택기(2026-08-18) — date_input 쌍 대신 달력에서 체크인→
   체크아웃을 직접 클릭해 고른다(체크리스트 제거와 같은 결정). 점유일 틴트는 예약
   캘린더의 숙소 고정 틴트(D4)와 같은 값이고 셀 클래스 인덱스(occ0=대관령·occ1=태안)도
   같은 기준정보 순서 축이다. 날짜 셀 상태는 위젯 key 접두(lrqd_{{state}}_)로 나른다 —
   렌더마다 바뀌는 화면 로컬 CSS 없이 정적 규칙만으로 상태를 표현하기 위해서다. */
.st-key-lrq_cal {{ max-width:none; }}
.st-key-lrq_cal [data-testid="stVerticalBlock"] {{ gap:4px !important; }}
.st-key-lrq_cal [data-testid="stHorizontalBlock"] {{ gap:4px !important; }}
.st-key-lrq_cal [data-testid="stColumn"] {{ min-width:0 !important; flex:1 1 0 !important; }}
.st-key-lrq_toprow {{ gap:8px !important; margin-bottom:12px; }}
.st-key-lrq_toprow .pr-flabel {{ width:44px; flex:0 0 44px; padding-top:0; }}
.st-key-lrq_toprow [data-testid="stElementContainer"]:has(.pr-spacer) {{
  flex:1 1 auto; }}
.pr-spacer {{ flex:1 1 auto; }}
.pr-calttl {{ font-size:16px; font-weight:600; color:{INK}; white-space:nowrap;
  min-width:96px; text-align:center; }}
.pr-dow {{ display:grid; grid-template-columns:repeat(7,1fr); gap:4px; margin:2px 0 0; }}
.pr-dow span {{ text-align:center; font-size:12px; font-weight:600; color:{INK2};
  padding:3px 0 1px; }}
.pr-dow span:first-child {{ color:#9c3232; }}
.pr-dow span:last-child {{ color:#2f4d99; }}
[class*="st-key-lrqd_"] button {{
  width:100% !important; min-height:42px !important; height:42px !important;
  padding:0 !important; border-radius:7px !important; box-shadow:none !important;
  font-family:{MONO} !important; font-size:12px !important; font-weight:600 !important;
  background:#ffffff !important; border:1px solid {LINE} !important; color:{INK2} !important; }}
/* 클릭 피드백 — 틴트·선택색과 충돌하지 않는 밝기 변화 + 빈 날짜엔 액센트 테두리. */
[class*="st-key-lrqd_"] button:hover:not(:disabled) {{ filter:brightness(.96); }}
[class*="st-key-lrqd_day_"] button:hover:not(:disabled),
[class*="st-key-lrqd_tdy_"] button:hover:not(:disabled) {{ filter:none;
  border-color:{ACCENT} !important; color:{ACCENT_TEXT} !important; }}
[class*="st-key-lrqd_"] button:focus-visible {{ outline:2px solid {ACCENT} !important;
  outline-offset:1px; }}
[class*="st-key-lrqd_tdy_"] button {{ border-color:{ACCENT} !important;
  color:{ACCENT_TEXT} !important; }}
[class*="st-key-lrqd_occ0_"] button {{ background:#eef5f0 !important; color:#2f6b45 !important;
  border-color:#eef5f0 !important; }}
[class*="st-key-lrqd_occ1_"] button {{ background:#fdf3e3 !important; color:#8a6212 !important;
  border-color:#fdf3e3 !important; }}
[class*="st-key-lrqd_occx_"] button {{ background:#f2f0ec !important; color:#5c564d !important;
  border-color:#f2f0ec !important; }}
/* 선택 기간 — 날짜마다 끊긴 칸이 아니라 **이어진 하나의 막대**로 읽히게 한다
   (2026-08-19 사용자 시안). 열 사이 gap(4px)을 음수 마진으로 덮고, 이어지는 쪽의
   모서리 반경을 없앤다. 주(week) 경계에서는 자연히 끊어져 다음 줄로 이어진다. */
[class*="st-key-lrqd_sel"] button {{ background:{ACCENT} !important; color:#ffffff !important;
  border-color:{ACCENT} !important; }}
[class*="st-key-lrqd_selL"] button, [class*="st-key-lrqd_selLR"] button {{
  border-top-left-radius:0 !important; border-bottom-left-radius:0 !important;
  margin-left:-5px !important; }}
[class*="st-key-lrqd_selR"] button, [class*="st-key-lrqd_selLR"] button {{
  border-top-right-radius:0 !important; border-bottom-right-radius:0 !important;
  margin-right:-5px !important; }}
/* 지난 날짜·바깥 달 — :disabled 가 상태 틴트보다 특이도·순서 모두에서 이긴다. */
[class*="st-key-lrqd_"] button:disabled {{ background:{SURFACE_2} !important;
  color:#c3bdb3 !important; border-color:{LINE} !important; }}
[class*="st-key-lrqd_out_"] button:disabled {{ background:transparent !important;
  border-color:transparent !important; color:#d6d1c8 !important; }}
/* FORM_ENTRY 라벨 열(130px 고정) + 값 열(DESIGN §2·§3.1) — 라벨은 좌측 고정 열,
   컨트롤은 값 열에서 제 폭만 쓴다. 읽기 화면과 같은 라벨 폭 계약. */
[class*="st-key-lrq_f_"] {{ gap:16px !important; }}
.pr-flabel {{ width:130px; flex:0 0 130px; font-size:12px; color:{INK2};
  padding-top:8px; line-height:1.4; }}
/* 액션 바의 라벨은 컨트롤과 세로 중앙 정렬이라 위 여백을 뺀다(정의 목록과 같은 130px). */
/* 처리 판 헤더 — 좌 식별자, 우 실행 버튼(버튼 묶음을 우측으로 민다) */
[class*="st-key-prhead_"] {{ gap:8px !important; margin-bottom:16px; }}
[class*="st-key-prhead_"] [data-testid="stElementContainer"]:has(.pr-panelhd) {{
  flex:1 1 auto; min-width:0; }}
.pr-flabel .req {{ color:{ACCENT}; }}
/* FORM_ENTRY 하단 고정 제출 바(§2) — 필수 충족 상태 + 제출 버튼. 카드 아님(상단
   헤어라인). 캔버스색으로 아래 내용을 가리며 스크롤을 따라온다. */
.st-key-lrq_submitbar {{ position:sticky; bottom:0; z-index:6; background:#f4f2ee;
  border-top:1px solid {LINE_SEC}; padding:12px 0 8px; margin-top:8px; }}
.st-key-lrq_submitbar [data-testid="stElementContainer"]:has(.pr-substat) {{
  flex:1 1 auto; min-width:0; }}
.pr-substat {{ display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px;
  font-size:12px; color:{MUT}; line-height:1.5; min-height:34px; }}
.pr-substat b {{ color:{INK}; font-weight:600; }}
.pr-substat .bar {{ width:64px; height:4px; border-radius:999px; background:{LINE};
  overflow:hidden; flex:0 0 auto; }}
.pr-substat .bar i {{ display:block; height:100%; background:{ACCENT}; }}
.pr-substat .warn {{ color:#9c3232; }}
/* 부정적 액션(반려·취소) — §3.2 부정 의미 색(§1.3 부정 세트 재사용, 새 색 없음).
   같은 크기·같은 색 버튼 4개 나열 금지(§3.2)의 색 축 분리를 담당한다. */
[class*="st-key-prneg_"] button {{
  background:#fbeeee !important; border:1px solid #f0d9d9 !important;
  color:#9c3232 !important; min-height:34px !important; border-radius:8px !important;
  font-size:14px !important; font-weight:600 !important; white-space:nowrap !important; }}
[class*="st-key-prneg_"] button:hover:not(:disabled) {{ filter:brightness(.97); }}
[class*="st-key-prneg_"] button:disabled {{ background:transparent !important;
  border:1px solid {LINE_SEC} !important; color:{MUT} !important; }}
/* 가용 미니 달력(승인 판단 근거, §2 WORKLIST "근거 → 결정 컨트롤") — 신청 화면 달력
   선택기와 **같은 부호**를 쓴다: 점유일 = 숙소 틴트, 이 신청 = 액센트. 읽기 전용이라
   버튼이 아니라 정적 격자다(클릭 대상 아님 — 결정은 아래 액션 바가 소유). */
.pr-mini-wrap {{ display:flex; flex-wrap:wrap; align-items:flex-start; gap:16px 32px;
  margin:4px 0 12px; }}
.pr-mini {{ flex:0 0 auto; }}
.pr-mini-h {{ font-size:12px; font-weight:600; color:{INK2}; margin:0 0 6px;
  white-space:nowrap; }}
.pr-mini-g {{ display:grid; grid-template-columns:repeat(7,32px); gap:2px; }}
.pr-mini-g span {{ height:30px; display:flex; align-items:center; justify-content:center;
  font-family:{MONO}; font-size:12px; color:{INK2}; border-radius:5px;
  border:1px solid transparent; }}
/* 화면 우측 상단 신원 칩 — 신원 줄(pr-idrow) 대신 한 덩어리로(2026-08-19 시안). */
.pr-idchip {{ display:flex; justify-content:flex-end; margin:0 0 12px; }}
.pr-idchip > span {{ display:inline-flex; align-items:center; gap:12px;
  border:1px solid {LINE}; border-radius:8px; background:#ffffff;
  padding:7px 14px; font-size:12px; color:{INK2}; }}
.pr-idchip b {{ color:{INK}; font-weight:600; }}
.pr-idchip i {{ width:1px; height:12px; background:{LINE}; display:inline-block; }}
/* 신청 요약 — 라벨(64px) + 값. 값 열은 하나다(§3.1). */
.pr-sum {{ display:grid; grid-template-columns:64px minmax(0,1fr); gap:12px;
  align-items:baseline; margin:0 0 16px; }}
.pr-sum .k {{ font-size:12px; color:{MUT}; }}
.pr-sum .v {{ font-size:14px; font-weight:600; color:{INK}; }}
.pr-sum .v.off {{ color:{MUT}; font-weight:400; }}
/* 필수 충족 — 요약 아래, 제출 버튼 바로 위(§2 제출 상태 표시) */
.pr-req {{ display:flex; align-items:center; gap:10px; padding-top:12px;
  border-top:1px solid {LINE}; margin:0 0 10px; font-size:12px; color:{MUT}; }}
.pr-req b {{ color:{INK}; font-weight:600; }}
.pr-req .bar {{ flex:1 1 auto; height:4px; border-radius:999px; background:{LINE};
  overflow:hidden; }}
.pr-req .bar i {{ display:block; height:100%; background:{ACCENT}; }}
/* 패널 카드(2026-08-19 사용자 참고 배치) — 목록·처리 판을 각각 흰 카드로 묶는다.
   신판 §4 금지 7개에 카드 금지가 없다(구판 §0-5 는 폐기) — 색·radius 는 §1 토큰이다. */
[class*="st-key-prcard_"] {{
  background:#ffffff; border:1px solid {LINE}; border-radius:8px;
  padding:16px 20px; margin-bottom:16px; }}
/* 패널 헤더 — 좌 제목 / 우 보조 설명(정렬 기준·건수) */
.pr-panelhd {{ display:flex; flex-wrap:wrap; align-items:center; gap:12px;
  margin:0 0 12px; }}
.pr-panelhd .t {{ font-size:14px; font-weight:600; color:{INK}; }}
.pr-panelhd .r {{ margin-left:auto; font-size:12px; color:{MUT}; white-space:nowrap; }}
/* 속성 스택 — 라벨(12/약함) 위, 값(14/진함) 아래. 값 열은 하나다(§3.1). */
.pr-stack {{ display:flex; flex-direction:column; gap:16px; }}
/* 가로 변형 — 상세 폭이 넓고 값이 짧을 때(내 예약처럼 3~4칸) */
.pr-stack.row {{ flex-direction:row; flex-wrap:wrap; gap:16px 40px; }}
.pr-stack.row > div {{ min-width:0; }}
.pr-stack .k {{ font-size:12px; color:{MUT}; line-height:1.4; margin:0 0 4px; }}
.pr-stack .v {{ font-size:14px; font-weight:600; color:{INK}; line-height:1.5; }}
.pr-stack .s {{ font-size:12px; font-weight:400; color:{MUT}; line-height:1.5;
  margin-top:4px; }}
.pr-stack .ok {{ color:#2f6b45; }}
.pr-stack .bad {{ color:#9c3232; }}
/* 처리 판 3열 구획 — 2·3열 좌측 헤어라인(§4 구획은 선과 여백으로) */
[class*="st-key-prcols_"] [data-testid="stColumn"]:not(:first-child) {{
  border-left:1px solid {LINE}; padding-left:24px; }}
@media (max-width:900px) {{
  [class*="st-key-prcols_"] [data-testid="stColumn"] {{ border-left:0 !important;
    padding-left:0 !important; }}
}}
/* 달력 옆 세로 칸 — 요약 한 줄과 범례를 달력 오른쪽에 세워 세로 길이를 줄인다.
   값 열 **안쪽** 배치라 §3.1 의 "값 열은 하나" 계약은 그대로다. */
.pr-mini-side {{ flex:0 1 300px; min-width:200px; display:flex; flex-direction:column;
  gap:8px; padding-top:24px; }}
.pr-mini-side .pr-sumline {{ margin:0; }}
.pr-mini-side .pr-legend {{ margin:0; }}
/* 달력 아래 한 줄 요약 — 달력이 답하지 못하는 수치(겹침·여유일·점유율)만 잇는다.
   세로 kv 블록으로 두면 값 열이 둘이 되어 정렬 축이 갈라진다(§3.1 위반). */
.pr-sumline {{ font-size:12px; color:{INK2}; line-height:1.6; margin:10px 0 0;
  word-break:keep-all; }}   /* 한글은 단어 단위로 끊는다 — '점유/율' 분리 방지 */
.pr-sumline b {{ color:{INK}; font-weight:600; font-variant-numeric:tabular-nums; }}
.pr-sumline .bad {{ color:#9c3232; font-weight:600; }}
/* 상세 정의 목록 — **라벨 130px 좌측 열 + 값 열 하나**(§3.1). 폼(라벨 열)과 같은 폭이라
   같은 레코드를 쓰는 입력·읽기 화면의 라벨 축이 일치한다(§3.1 "라벨 열 폭 일치"). */
.pr-dl {{ display:grid; grid-template-columns:130px minmax(0,1fr); gap:16px;
  align-items:start; margin:4px 0 8px; }}
.pr-dl .k {{ font-size:12px; color:{MUT}; line-height:1.5; }}
.pr-dl .v {{ font-size:14px; color:{INK}; line-height:1.5; min-width:0; }}
.pr-mini-g .hd {{ height:18px; font-family:inherit; font-size:12px; font-weight:600;
  color:{MUT}; }}
.pr-mini-g .hd.sun {{ color:#9c3232; }}
.pr-mini-g .hd.sat {{ color:#2f4d99; }}
.pr-mini-g .out {{ color:#cfc8bd; }}
/* 주말 날짜 — 헤더와 같은 축(일=반려색·토=정보색, §1.3 의미색 재사용) */
.pr-mini-g .sun {{ color:#9c3232; }}
.pr-mini-g .sat {{ color:#2f4d99; }}
.pr-mini-g .today {{ border-color:{ACCENT}; color:{ACCENT_TEXT}; }}
/* 점유 틴트는 호출부가 인라인 색으로 준다(숙소 고정 색축 재사용). */
.pr-mini-g .focus {{ background:{ACCENT}; color:#ffffff; border-color:{ACCENT};
  font-weight:600; }}
/* 체크아웃 당일 — 점유하지는 않지만 **신청 기간의 끝**이라 숙박일과 **같은 색**으로
   칠한다(2026-08-19 사용자 지시: 사용기간은 한 색). 1박2일이면 두 칸이 같은 주황이다.
   반개구간 계약은 그대로이며 겹침 판정은 숙박일에만 적용한다(체크아웃일이 다음 사람의
   체크인일인 것은 정상이라 충돌로 칠하지 않는다). */
.pr-mini-g .edge {{ background:{ACCENT}; color:#ffffff; border-color:{ACCENT};
  font-weight:600; }}
.pr-mini-g .conflict {{ background:#fbeeee; color:#9c3232; border-color:#9c3232;
  font-weight:600; }}
/* 좁은 폭(≤900px): 달력 옆 가용 요약이 아래로 내려간다(좌측 헤어라인 → 상단으로) */
@media (max-width:900px) {{
  .pr-mini-side {{ flex:1 1 100%; padding-top:4px; }}
}}
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
    """범례를 그 자리에 렌더한다 — 문자열이 필요하면 :func:`legend_html`.

    ``(라벨, 배경색, 테두리/텍스트색)`` 또는 ``(라벨, 배경색, 테두리색, 종류)``.

    ``종류`` 는 :data:`LEGEND_KINDS` 중 하나이며 생략하면 ``"solid"`` 다. 캘린더 막대가
    채움색 외에 점선 테두리(승인대기)·좌측 액센트 캡(본인 예약)으로도 의미를 싣기
    때문에, 범례 견본이 그 표현을 그대로 축소 재현할 수 있어야 한다(§4 이중부호화의
    범례 대응). 알 수 없는 종류는 ``solid`` 로 떨어뜨린다.
    """
    st.markdown(legend_html(items), unsafe_allow_html=True)


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
        f"<div style='font-size:12px;color:{MUT};line-height:1.6;margin:6px 0 2px;'>"
        f"{escape(text)}</div>",
        unsafe_allow_html=True,
    )


#: 숙소별 고정 틴트 ``(배경, 전경)`` — **기준정보 순서 축**. 캘린더·신청 달력·승인
#: 미니 달력이 같은 배열을 공유해야 같은 숙소가 어느 화면에서나 같은 색이다(D4).
LODGING_TINTS = (
    ("#eef5f0", "#2f6b45"),   # 1번째 숙소(대관령) — 완료·정상 세트
    ("#fdf3e3", "#8a6212"),   # 2번째 숙소(태안) — 대기·주의 세트
    ("#f2f0ec", "#5c564d"),   # 그 밖 — 종료·중립 세트
)

_MINI_WEEKDAYS = ("일", "월", "화", "수", "목", "금", "토")


def mini_month_html(year: int, month: int, *, title: str = "",
                    occupied=(), focus=(), edge=(),
                    tint: tuple[str, str] | None = None, today=None) -> str:
    """가용 판단용 읽기 전용 월 격자 HTML(승인 관리 상세).

    ``occupied`` 는 다른 예약이 점유한 날, ``focus`` 는 지금 판단 중인 신청의 숙박 밤,
    ``edge`` 는 그 신청의 **체크아웃 당일**이다(점유하지 않지만 기간의 끝이라 옅게
    칠한다 — 1박2일이면 두 칸이 보인다). ``focus`` 와 ``occupied`` 가 겹치는 날은
    **충돌**로 따로 칠한다 — 승인 불가 사유가 달력 위에서 바로 읽힌다.
    ``tint`` 는 그 숙소의 고정 색(:data:`LODGING_TINTS` 원소)이다.
    """
    from calendar import monthrange
    from datetime import date as _date

    occupied, focus, edge = set(occupied or ()), set(focus or ()), set(edge or ())
    bg, fg = tint or LODGING_TINTS[-1]
    first = _date(year, month, 1)
    lead = (first.weekday() + 1) % 7          # 일요일 시작(캘린더 화면과 동일 축)
    ndays = monthrange(year, month)[1]

    cells = [f"<span class='hd{' sun' if i == 0 else ' sat' if i == 6 else ''}'>{w}</span>"
             for i, w in enumerate(_MINI_WEEKDAYS)]
    cells += ["<span class='out'></span>"] * lead
    for day in range(1, ndays + 1):
        d = _date(year, month, day)
        if d in focus and d in occupied:
            cells.append(f"<span class='conflict'>{day}</span>")
        elif d in focus:
            cells.append(f"<span class='focus'>{day}</span>")
        elif d in edge:
            cells.append(f"<span class='edge'>{day}</span>")
        elif d in occupied:
            cells.append(f"<span style='background:{bg};color:{fg};'>{day}</span>")
        elif today is not None and d == today:
            cells.append(f"<span class='today'>{day}</span>")
        else:
            wk = (d.weekday() + 1) % 7
            cls = " class='sun'" if wk == 0 else " class='sat'" if wk == 6 else ""
            cells.append(f"<span{cls}>{day}</span>")
    head = f"<div class='pr-mini-h'>{escape(title or f'{year}년 {month}월')}</div>"
    return f"<div class='pr-mini'>{head}<div class='pr-mini-g'>{''.join(cells)}</div></div>"


def def_rows(rows: list[tuple]) -> str:
    """상세 정의 목록 HTML — ``(라벨, 값)`` 또는 ``(라벨, html, "html")``.

    **값 열은 하나**이고 라벨은 좌측 130px 열로 전치한다(§3.1). 상세의 모든 값이 같은
    x 축에서 시작하므로 블록마다 정렬이 갈라지지 않는다 — 종전에는 메타 셀·요약 kv·
    범례가 각자 다른 축을 써서 화면이 산만했다(2026-08-19 사용자 지적).
    """
    cells = []
    for row in rows:
        label, value = row[0], row[1]
        is_html = len(row) > 2 and row[2] == "html"
        v = value if is_html else escape(str(value if value not in (None, "") else "-"))
        cells.append(f"<div class='k'>{escape(str(label))}</div><div class='v'>{v}</div>")
    return f"<div class='pr-dl'>{''.join(cells)}</div>"


def legend_html(items: list[tuple]) -> str:
    """:func:`legend` 와 같은 범례를 **HTML 문자열로** 돌려준다(다른 블록 안에 embed 용)."""
    parts = []
    for item in items:
        label, bg, fg = item[0], item[1], item[2]
        kind = item[3] if len(item) > 3 else "solid"
        cls = f" class='{kind}'" if kind in LEGEND_KINDS and kind != "solid" else ""
        parts.append(
            f"<span><i{cls} style='background:{bg};border-color:{fg};'></i>"
            f"{escape(str(label))}</span>"
        )
    return f"<div class='pr-legend'>{''.join(parts)}</div>"


def field_label(label: str, *, required: bool = False) -> None:
    """FORM_ENTRY 라벨 열의 필드 라벨(§2 — 라벨 130px 고정 열 + 값 열).

    가로 컨테이너의 첫 자식으로 호출한다 — 폭·정렬은 ``.pr-flabel`` CSS 가 소유한다.
    """
    req = " <span class='req'>*</span>" if required else ""
    st.markdown(f"<div class='pr-flabel'>{escape(label)}{req}</div>",
                unsafe_allow_html=True)


__all__ = [
    "INK", "INK2", "MUT", "LINE", "LINE_SEC", "LINE_HDR", "ACCENT", "ACCENT_TEXT",
    "ACCENT_TINT", "SURFACE_2", "MONO", "PROTO_CSS",
    "BADGE_SUBMITTED", "BADGE_IN_REVIEW", "BADGE_EVALUATED", "BADGE_REJECTED",
    "BADGE_CLOSED", "LEGEND_KINDS", "LODGING_TINTS", "mini_month_html",
    "inject", "hairline", "section", "identity_row", "badge", "meta_cells",
    "body_blocks", "steps_html", "checklist_html", "aside_kv", "queue_head",
    "legend", "legend_html", "def_rows", "caption_line", "note_line", "submit_hint", "field_label",
]
