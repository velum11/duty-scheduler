"""아차사고 등록 — FORM_ENTRY(DESIGN.md §2) 단건 제출 폼.

§2 FORM_ENTRY 골격으로 구현한다(색 리스킨이 아니라 구조 교체):

    [신원]  신고자 · 사번 · 소속            ← 세션에서 확정, 편집 불가
    01 · 기본 정보 / 02 · 상황 기술 / 03 · 사진 첨부(선택)
      라벨(130px 고정 좌측 열)  |  값(한 열 · 컨트롤은 제 폭만)
    ────────────────────────────────────────
    필수 7/8 ▓▓▓▓░  예방대책이 남았습니다   [제출]   ← 하단 고정 바

- **라벨 열 + 값 열**(§3.1·§4-4) — 라벨을 좌측 130px 열로 전치하고 값을 한 열에 모은다.
  값 열이 둘 이상이면 길이가 다른 내용의 폭을 맞출 수 없어 반드시 어긋난다. 값 열은 하나로
  두고 **컨트롤 폭은 그 칸에 들어갈 값의 실측 길이에서 역산**한다(아래 `_KO_ADV_PX` 주석의
  계측 근거). 남는 가로 폭은 어느 칸에도 흡수시키지 않는다 — 남으면 남긴다.
- **라벨 열 폭·필드 순서는 읽기 화면과 일치**시킨다(§2). 기준은 평가 관리 상세
  (`near_miss_evaluate._detail_body_html` — 라벨 열 `flex:0 0 130px`)이며 순서도 같다:
  머리(작업명·발생일) → 사고내용 → 작업내용 → 현장 상황 → 원인(코드·상세) → 대책.
  같은 레코드를 등록에서 쓰고 평가에서 읽으므로 배치가 다르면 작성자는 자기 글이 어떻게
  보일지 예측할 수 없다.
- **필수 충족은 하단 고정 바 하나로만 표시**한다(§2) — 개수 + 남은 항목 이름. 종전의 우측
  CHECKLIST 패널은 폐기했다: 라벨 열 구조에서는 폼 자체가 세로 목록이라 빈 값이 이미 보이고,
  패널에 다시 나열하면 §4-2(같은 기능의 진입점 두 곳)에 걸리며 필드가 늘 때 두 곳을 고쳐야
  한다. 하단 바의 개수·남은 이름은 제출 검증과 **같은 함수**(`_validate`)에서 파생한다.
- **제출 버튼을 눌러야 뭐가 빠졌는지 알게 하지 않는다**(§2). 미충족이면 버튼을 비활성으로
  두되 사유(남은 항목 이름)를 화면에 쓴다(§3.2·§4-3 — 툴팁에만 두지 않는다).
- **제안등급 입력 경로 없음**(§7.2-1b) — 등급은 확정등급(평가 단계)만 쓴다. 이 화면은
  `proposed_grade` 를 위젯으로도 payload 로도 보내지 않는다. DB 컬럼·제약은 미사용으로
  남는다(컬럼 제거 판단은 data-contract 소관 — 이 화면에서 되살리지 말 것).
- **밀도 cozy · 모바일 우선**(§3.4 등급표 · §1.4) — 히트 영역 44px 이상. 브레이크포인트는
  §3.4 의 `<599 / 599–1023 / >1023` 을 쓰고, `<599px` 에서 라벨 열·값 열을 세로로 접는다
  (라벨 위 · 값 아래). 값 열이 하나라는 §3.1 성질은 접힌 뒤에도 유지된다.
  (§2 표는 FORM_ENTRY 밀도를 compact 로 적지만, §3.4 는 이 화면을 이름으로 지목해
  모바일 우선=cozy 로 둔다 — 화면별 등급이 유형 기본값보다 구체적이라 cozy 를 따른다.)

기능 계약(불변): 제출 검증·필수 8필드·저장 경로·성공 화면 흐름·사진 스테이징-후-첨부 전부 보존.
신원(신고자/사번/소속/created_by)은 위젯이 아니라 세션 사용자에서 서버측 확정(위조 방지).
03 · 사진 첨부는 **스테이징-후-첨부** 흐름이다 — db 사진 업로드 API 는 '이미 존재하는 SUBMITTED
소유 보고서'를 요구하는데 등록 폼에는 제출 전까지 report_id 가 없으므로, 선택 사진을 세션에
스테이징(선택 즉시 photo_storage 로 검증·압축)했다가 제출로 보고서가 생성된 뒤 각 사진을
db.upload_near_miss_photo(new_id,...) 로 첨부한다. 사진은 선택 항목이라 필수 8필드에 미포함이다.
진행 표시는 **실시간**이다 — st.form 을 쓰지 않고 일반 키드 위젯 + st.button 제출을 쓰므로 입력이
즉시 세션에 반영된다. 제출 시 전체를 재검증한다. modules/db.py 무수정(파사드 소비만).
"""
# DESIGN.md §2 FORM_ENTRY — 새 사실을 기록한다. 결정: 제출할 준비가 되었는가.
SCREEN_ARCHETYPE = "FORM_ENTRY"

import uuid
from datetime import date
from html import escape

import streamlit as st

from modules import auth, db, photo_storage, ui
from views.common import erp
from views.common import scaffold
from views.master import PersistResult, banner, ledger_banner

_PAGE_ID = "near_miss_submit"
_DONE_KEY = "nm_submit_done"

# ── 사진 스테이징(제출 전 세션 보관 → 제출 성공 후 db API 로 첨부) ──
_STAGE_KEY = "nm_photo_stage"        # list[{"id","name","bytes","size"}] — 압축 JPEG + 원본 크기
_STAGE_SEEN_KEY = "nm_photo_seen"    # 이미 처리한 업로더/카메라 file_id 집합(중복 스테이징 방지)
_UP_KEY = "nm_f_photo_uploader"
_CAM_KEY = "nm_f_photo_camera"

# 업로드 상한(계약: 원본 ≤10MB/장). photo_storage.MAX_UPLOAD_BYTES 를 단일 출처로 삼되(읽기만),
# 위젯 인자(max_upload_size, MB)와 서버 config(maxUploadSize) 로 다층 차단한다.
_MAX_UPLOAD_BYTES = photo_storage.MAX_UPLOAD_BYTES
_MAX_UPLOAD_MB = max(1, _MAX_UPLOAD_BYTES // (1024 * 1024))
# 다중 선택 누적 상한 — 스테이징 원본 총량. 3장×10MB 여유를 두되 과대 메모리 적재를 막는다.
_STAGE_TOTAL_CAP_BYTES = 30 * 1024 * 1024
_STAGE_TOTAL_CAP_MB = _STAGE_TOTAL_CAP_BYTES // (1024 * 1024)

# 발생원인 선택 라벨 — 6화면 단일 어휘(2026-08-14 통일). 등록에서 고른 문구가 내 아차사고·
# 조회·평가·개선조치·분석에서 **같은 문구**로 다시 보여야 한다(KOSHA 현행 단문 용어).
_CAUSE_LABELS = {
    "JAM": "끼임", "FALL": "추락", "DROP": "낙하물", "HIT": "부딪힘",
    "SLIP": "미끄러짐", "BURN": "화상", "PINCH": "협착", "ETC": "기타",
}

# ── 필수 8필드 = (표시 라벨, payload/위젯 자연키) 단일 출처 ──
# **순서가 곧 화면 필드 순서**이고, 하단 바의 "남은 항목" 순서이며, 제출 재검증(_validate)의
# 결과 순서다. §2 가 요구한 "두 곳을 고치지 않는다"를 이 튜플 하나로 만족시킨다.
# 순서 기준은 읽기 화면(평가 관리 상세)이다 — 머리(작업명·발생일) → 사고내용 → 작업내용 →
# 현장 상황 → 원인(코드·상세) → 대책.
_REQUIRED: tuple[tuple[str, str], ...] = (
    ("작업명", "work_name"),
    ("발생일", "incident_date"),
    ("사고내용", "incident_content"),
    ("작업내용", "work_content"),
    ("작업현장 상황설명", "site_description"),
    ("발생원인", "cause_code"),
    ("발생원인 상세", "cause_detail"),
    ("예방대책", "countermeasure"),
)
_WKEY = "nm_f_"                                            # 위젯 키 접두(세션 초안 보존 키)
_FORM_WIDGET_KEYS = [f"{_WKEY}{key}" for _, key in _REQUIRED]

# ── §1.3 팔레트 (토큰 밖 색 금지 §4-7) ──
_INK = "#1c1a17"
_INK2 = "#4a453d"
_WEAK = "#6b665d"   # 읽는 보조 텍스트 최저 대비(캔버스 위 5.1:1) — #8b857c 이하 금지(§4-6)
_CANVAS = "#f4f2ee"
_LINE = "#e6e2da"
_LINE_SEC = "#e0dbd2"
_LINE_HDR = "#cfc8bd"
_ACCENT = "#c2410c"
_ACCENT_TEXT = "#b4451a"
# 인라인 style 속성에 들어가도 안전하도록 **큰따옴표**로 감싼다(6화면 공통 규약, 2026-08-14).
# 모노는 **영문·숫자에만** 건다. IBM Plex Mono 에는 한글 글리프가 없어 한글이 글자마다
# 폴백 폰트로 떨어지고, 거기에 letter-spacing 이 더해지면 자간이 이중으로 벌어져 "신 원"
# 처럼 보인다(2026-08-18 병행 세션 발견). 한글이 섞인 라벨은 본문 sans 를 상속시키고
# 숫자 부분만 별도 span 으로 감싼다(§1.2 — 숫자·ID·코드·날짜는 IBM Plex Mono).
_MONO = '"Pretendard","Malgun Gothic",-apple-system,sans-serif'

# ── §3.1 폭 — **값의 실측 길이에서 역산한다** ──────────────────────────────────
# 라벨 열 130px 은 평가 관리 상세 `_detail_body_html` 의 라벨 열(`flex:0 0 130px`)과 **같은
# 값**이다(§2 요구). 두 화면 중 한쪽만 바꾸면 등록·읽기의 필드 정렬이 어긋나므로 함께 바꾼다.
# (2026-08-18 실렌더 확인: 등록 라벨 열 상자 = 130.0px, 평가 상세 라벨 span = 130px. 값 열
#  시작점이 라벨 시작점에서 146px 인 것은 130 + 열 간격 16 이며 라벨 열 폭 자체가 아니다.)
_LABEL_COL_PX = 130

# ── 글자 폭 계수 — **추정치가 아니라 실측치**(2026-08-18) ──────────────────────
# 계측: sample 모드 :8510 / Chromium 1440×900 / 등록 폼의 실제 컨트롤 computed font
# (`14px/19.6px "IBM Plex Sans KR", "Malgun Gothic", …`)를 그대로 써서 hidden span 100자
# 반복 폭을 재고 100으로 나눴다(단일 글자 측정의 반올림 오차 제거).
#   한글 '가'×100 = 1248.81px → 12.488px/자
#   라틴 'n'×100 =  795.20px →  7.952px/자
#   숫자 '0'×100 =  840.00px →  8.400px/자
# → **한글 1자 = 라틴 소문자 1.571자 폭**. 폭 역산은 전부 한글 기준(12.488)으로 한다.
_KO_ADV_PX = 12.488
_LAT_ADV_PX = 7.952          # 한글/라틴 계수 = 12.488 / 7.952 = 1.571

# ── 컨트롤 여백 실측(같은 계측 세션) ──
#   text_input  : 좌 10.5 / 우 7,   테두리 1px      textarea : 상하좌우 10.5, 테두리 1px
#   date_input  : 좌 11.25 / 우 7 + 래퍼 우 3.5,    selectbox: 좌우 7 + 셰브런 버튼 28
#
# ── 폭 3계단 — 각 계단은 "그 칸에 실제로 들어가는 값"에서 나온다 ──
# 실값 코퍼스는 이 도메인의 실제 문장이다(modules/db.py `_NEAR_MISS_SEED` = 가상 실사례,
# 그리고 이 화면의 placeholder 예시). 위 폰트로 실측한 렌더 폭:
#   사고내용 최장 "호이스트로 포대 인양 중 … 작업자 1m 옆 통과"  397.95px (한글 31.9자)
#   예방대책 최장 "결속 상태 2인 상호 확인 후 인양, …"          323.30px
#   현장 상황 최장 "원료 투입장 호이스트 하부"                  147.28px
#   작업내용 최장 "PET 원료 포대 투입 작업"                     137.78px
#   작업명   최장 "3라인 컨베이어 벨트 점검"(placeholder 예시)   143.20px (한글 11.5자)
#   원인 상세 최장 "시야 미확보"                                 65.75px (한글  5.3자)
#   원인 코드 최장 라벨 "미끄러짐 (SLIP)"                         91.88px
#   발생일   "2026-08-05"                                        78.38px
#
# (A) 고정 형식 짧은 값 — 발생일·원인 코드. 값 자체 폭 + 컨트롤 부속 폭.
#     코드: 91.88 + 좌우 패딩 14 + 셰브런 28 + 테두리 2 = 135.88
#     날짜: 78.38 + 11.25 + 7 + 래퍼 3.5 + 2          = 102.13
#     둘은 같은 "짧은 값" 부류라 **같은 폭**을 준다(종전 150/155 의 5px 어긋남이 이 자리에서
#     생겼다). 부류 최대값 135.88 을 4px 격자로 올리고 한 칸 여유 → 140.
_W_SHORT = 140
# (B) 한 줄로 끝나는 구 — 작업명·원인 상세. 용량 20자.
#     관찰 최장이 11.5자(작업명)·5.3자(원인 상세)라 20자는 1.7배 여유이고, 서술(40자)의
#     절반이라 **폭이 "한 줄이면 된다"고 말한다**.
#     20 × 12.488 + 좌 10.5 + 우 7 + 테두리 2 = 269.26 → 4px 격자 올림.
_W_LINE = 272
# (C) 서술 — 사고내용·작업내용·현장 상황·예방대책. 한 줄 용량 40자.
#     근거 둘: (1) 최장 실사례 31.9자가 한 줄에 들어가고 25% 여유가 남는다.
#     (2) 가독 상한 — 라틴 45~75자 권장을 위 실측 계수로 환산하면 40 × 1.571 = 62.8자로
#         권장 범위 안이다. 종전 1021px(=81.8자, 라틴 128자 상당)은 줄 끝에서 다음 줄 머리를
#         찾지 못하는 폭이었다.
#     40 × 12.488 + 좌우 패딩 21 + 테두리 2 = 522.55 → 4px 격자 올림.
_W_PROSE = 524

# ── 서술 상자 높이 — 줄 수 × 실측 줄 높이 ──
# textarea line-height 실측 23.8px(=14 × 1.7), 상하 패딩 10.5×2, 테두리 2.
#   3줄 = 3×23.8 + 21 = 92.4   /   4줄 = 4×23.8 + 21 = 116.2
# Streamlit 은 `height=` 에서 2px 을 뺀 값을 실제 상자 높이로 준다(실측) — 96/120 을 넘기면
# 렌더는 94/118 이고, 각각 3줄·4줄이 온전히 보인다(94-21=73 → 3.07줄 / 118-21=97 → 4.07줄).
# 반 줄이 잘려 보이지 않도록 줄 수로 못박는다(종전 90px 은 2.9줄이라 세 번째 줄이 잘렸다).
_H_PROSE_3 = 96
_H_PROSE_4 = 120

_HIT_PX = 44    # §1.4 cozy 히트 영역 하한 (§3.4 모바일 우선 화면)
# §1.1 간격 스케일에서 이 화면이 쓰는 값 — 행 사이 12 / 섹션 위 24(=12 gap + 12 margin).
_ROW_GAP = 12
_SEC_GAP = 12

_FORM_CSS = f"""
<style>
/* ── 신원 줄(§2 골격 첫 블록) — 카드 아님(헤어라인만). 세션에서 확정, 편집 불가. ── */
.nm-id {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 24px;
  padding:0 0 12px; border-bottom:1px solid {_LINE_SEC}; margin:0; }}
.nm-id .ov {{ font-size:12px; color:{_WEAK}; flex:0 0 auto; }}
.nm-id .it {{ display:flex; gap:8px; align-items:baseline; }}
.nm-id .k {{ font-size:12px; color:{_WEAK}; }}
.nm-id .v {{ font-size:14px; color:{_INK}; font-weight:600; }}
.nm-id .lock {{ margin-left:auto; font-size:12px; color:{_WEAK}; white-space:nowrap; }}
/* ── §1.1 세로 리듬 — 간격은 스케일(4·8·12·16·24·32·40) 값만 쓴다 ──
   Streamlit 세로 블록의 기본 gap 은 0.65rem = **9.1px 실측**으로 스케일 밖이다. 이 화면이
   쓰는 본문 블록(= 폼 행들을 직접 담는 블록)만 :has() 로 특정해 12px 로 못박는다. 다른
   화면의 블록은 이 선택자에 걸리지 않는다(행 컨테이너 st-key-nmrow_ 가 이 화면에만 있다). */
section[data-testid="stMain"] div[data-testid="stVerticalBlock"]:has(
  > div[data-testid="stLayoutWrapper"] > [class*="st-key-nmrow_"]) {{
  gap:{_ROW_GAP}px !important; }}
/* CSS 주입용 st.markdown 은 높이 0 이지만 **flex 아이템으로 남아 gap 을 한 번 더 만든다**
   (실측: 제목 밴드 ↔ 신원 줄 사이가 12 가 아니라 12×3 = 36 이었다). 이 화면이 만든 주입
   블록은 레이아웃에서 빼서 리듬 계산에 끼지 않게 한다. style 규칙은 display:none 이어도
   그대로 적용된다. 남은 한 겹은 공용 프레임(erp.screen_frame)이 만드는 주입 블록이다. */
section[data-testid="stMain"] div[data-testid="stLayoutWrapper"]:has(> [class*="st-key-nm_css"]) {{
  display:none !important; }}
/* 전역 markdown 컨테이너의 음수 여백(margin-bottom:-14px, 실측)은 이 화면의 커스텀 블록
   (섹션 머리·신원 줄·주석)에도 걸려 **컨테이너가 내용보다 14px 짧아진다** — 그만큼 다음
   블록이 위로 붙어 섹션 머리 글자가 바로 아래 입력과 2px 겹쳤다(실측). 이 화면의 블록에서만
   되돌린다(§1.1 리듬은 컨테이너 높이가 내용과 같아야 성립한다). */
section[data-testid="stMain"] [data-testid="stMarkdownContainer"]:has(.nm-sec),
section[data-testid="stMain"] [data-testid="stMarkdownContainer"]:has(.nm-id),
section[data-testid="stMain"] [data-testid="stMarkdownContainer"]:has(.nm-note),
section[data-testid="stMain"] [data-testid="stMarkdownContainer"]:has(.nm-req) {{
  margin-bottom:0 !important; }}
/* ── 섹션 오버라인(모노) + 헤어라인 ──
   위 12(블록 gap) + 12(margin) = 24, 아래는 블록 gap 12 그대로. 둘 다 스케일 값이다. */
.nm-sec {{ display:flex; align-items:center; gap:8px; margin:{_SEC_GAP}px 0 0; }}
.nm-sec .ov {{ font-size:12px; color:{_ACCENT_TEXT}; white-space:nowrap; }}
.nm-sec .ov .no {{ font-family:{_MONO}; letter-spacing:.08em; }}
.nm-sec .rule {{ flex:1; height:1px; background:{_LINE}; }}
.nm-sec .opt {{ font-size:12px; color:{_WEAK}; white-space:nowrap; }}
/* ── §3.1 라벨 열 + 값 열 ──
   라벨 130px 고정(평가 상세와 동일 값) / 값 열 하나. 값 열이 둘 이상이면 길이가 다른 내용의
   폭을 맞출 수 없어 반드시 어긋난다(§4-4). nowrap 으로 못박아 Streamlit 기본 컬럼 접힘이
   §3.4 브레이크포인트(<599)보다 먼저 일어나지 않게 한다. */
[class*="st-key-nmrow_"] div[data-testid="stHorizontalBlock"] {{
  flex-wrap:nowrap !important; gap:16px !important; }}
[class*="st-key-nmrow_"] div[data-testid="stColumn"]:first-child {{
  flex:0 0 {_LABEL_COL_PX}px !important; width:{_LABEL_COL_PX}px !important;
  min-width:{_LABEL_COL_PX}px !important; }}
[class*="st-key-nmrow_"] div[data-testid="stColumn"]:last-child {{
  flex:1 1 auto !important; width:auto !important; min-width:0 !important; }}
.nm-lb {{ font-size:12px; font-weight:600; color:{_INK2}; line-height:1.6; }}
/* 전역 markdown 컨테이너에 걸린 음수 여백(margin-bottom:-14px, 실측)이 라벨 상자를
   19px → 5px 로 접어 접힘(<599) 레이아웃에서 라벨 아랫부분이 컨트롤에 가려졌다. 공용
   키트가 필터 라벨에 쓰는 방식(st-key 스코프 + :has 로 여백 복원)과 같은 처방이다. */
[class*="st-key-nmrow_"] [data-testid="stMarkdownContainer"]:has(.nm-lb) {{
  margin-bottom:0 !important; }}
[class*="st-key-nmrow_"] div[data-testid="stElementContainer"]:has(.nm-lb) {{
  min-height:24px; }}
.nm-lb .req {{ color:{_ACCENT_TEXT}; font-style:normal; }}
/* 서술 입력(text_area) 행의 라벨 상단 정렬 — 값의 **첫 줄 글자**와 라벨 글자를 맞춘다.
   textarea 첫 줄 글자 상단 = 상자 top + 패딩 10.5 + 반행간 (23.8-14)/2 = 15.4px,
   라벨 글자 상단 = padding-top + 반행간 (19.2-12)/2 = padding-top + 3.6.
   → padding-top 12(스케일 값)이면 15.6 으로 0.2px 차이다(종전 8 은 3.8px 어긋났다). */
.nm-lb.top {{ padding-top:12px; }}
/* ── 밀도 cozy(§1.4 · §3.4) — 조작 대상 44px 이상. 이 화면 스코프에서만 적용한다. ──
   종전에는 **안쪽 input 에만** min-height:44 를 걸었다. 실측 결과 테두리 상자
   (stTextInputRootElement)는 Streamlit 기본 높이 35px 로 남고 input 만 44px 로 그려져
   상자 밖으로 위아래 4.5px 씩 삐져나왔다 — 그 삐져나온 만큼 다음 행이 밀려 5.6px 같은
   스케일 밖 간격이 생겼다.
   여기서 상자와 컨트롤을 **한 몸으로 만든다**: Streamlit 이 래퍼에 두는 1px 테두리는
   실측 색이 `#fbfaf8`(= 래퍼 배경과 같은 색)이라 보이지 않으면서 상자만 2px 키워, "보이는
   상자 44 / 재면 46"이라는 이중 수치를 만든다. 그 보이지 않는 테두리를 걷어내고 포커스·
   호버 표시는 레이아웃에 영향이 없는 outline 으로 되돌린다. 그 결과 **위젯 상자 = 안쪽
   컨트롤 = 44px** 이 되어 어느 쪽을 재도 같은 값이 나오고, 행 사이 간격도 순수 여백이 된다. */
[class*="st-key-nmrow_"] [data-testid="stTextInputRootElement"],
[class*="st-key-nmrow_"] [data-testid="stTextAreaRootElement"],
[class*="st-key-nmrow_"] div[data-testid="stDateInput"] div[data-baseweb="input"],
[class*="st-key-nmrow_"] div[data-testid="stSelectbox"] .react-aria-ComboBox > div,
[class*="st-key-nmrow_"] div[data-baseweb="select"] > div {{
  box-sizing:border-box !important; height:auto !important; border-width:0 !important;
  padding:0 !important; min-height:{_HIT_PX}px !important;
  display:flex; align-items:stretch; }}
[class*="st-key-nmrow_"] [data-testid="stTextAreaRootElement"] {{ height:100% !important; }}
[class*="st-key-nmrow_"] div[data-testid="stTextInput"] input,
[class*="st-key-nmrow_"] div[data-testid="stDateInput"] input,
[class*="st-key-nmrow_"] div[data-testid="stSelectbox"] input,
[class*="st-key-nmrow_"] div[data-testid="stDateInput"] div[data-baseweb="base-input"] {{
  box-sizing:border-box !important; flex:1 1 auto !important;
  min-height:{_HIT_PX}px !important; font-size:14px !important; }}
/* 테두리를 걷어낸 자리의 상태 표시(§ 상태는 선택이 아니다) — 레이아웃 불변인 outline 으로만
   그린다. 포커스는 §1.3 액센트, 호버는 §1.3 표 헤더 헤어라인. */
[class*="st-key-nmrow_"] [data-testid="stTextInputRootElement"]:hover,
[class*="st-key-nmrow_"] [data-testid="stTextAreaRootElement"]:hover,
[class*="st-key-nmrow_"] div[data-testid="stDateInput"] div[data-baseweb="input"]:hover,
[class*="st-key-nmrow_"] div[data-testid="stSelectbox"] .react-aria-ComboBox > div:hover {{
  outline:1px solid {_LINE_HDR}; outline-offset:0; }}
[class*="st-key-nmrow_"] [data-testid="stTextInputRootElement"]:focus-within,
[class*="st-key-nmrow_"] [data-testid="stTextAreaRootElement"]:focus-within,
[class*="st-key-nmrow_"] div[data-testid="stDateInput"] div[data-baseweb="input"]:focus-within,
[class*="st-key-nmrow_"] div[data-testid="stSelectbox"] .react-aria-ComboBox > div:focus-within {{
  outline:1px solid {_ACCENT} !important; outline-offset:0 !important; }}
/* Streamlit 1.59.1(현 .venv) 의 selectbox 는 baseweb 이 아니라 react-aria ComboBox 로
   렌더된다(실측). 그 안쪽 input 은 Streamlit 기본이 **12.25px/31.1px** 이라 §1.2 타이포
   5단계(28/20/16/14/12) 밖이고 §1.4 하한(44)에도 미달했다 — 위 규칙이 14px/44px 로
   되돌린다. 구 baseweb 형태도 함께 지정해 버전 전이에서 히트 영역이 유지되게 한다.
   셰브런 버튼도 같은 상자 높이를 채워 상자 어디를 눌러도 목록이 열리게 한다. */
[class*="st-key-nmrow_"] div[data-testid="stSelectbox"] .react-aria-ComboBox button {{
  min-height:{_HIT_PX}px !important; }}
[class*="st-key-nmrow_"] textarea {{ box-sizing:border-box !important;
  font-size:14px !important; line-height:1.7 !important; }}
/* ── 하단 고정 제출 바(§2 골격 마지막 블록) ──
   sticky 라 폼을 스크롤하는 동안에도 "필수 n/8 · 남은 항목 · [제출]"이 시야에서 사라지지
   않는다. 캔버스색 불투명 배경으로 본문이 밑으로 지나가게 한다. */
/* Streamlit 1.59.1(현 .venv) 은 키드 컨테이너를 stLayoutWrapper 로 한 겹 더 감싼다(실측). 안쪽
   `.st-key-` div 에 sticky 를 걸면 containing block 이 그 wrapper(높이 = 바 자신)로 잘려
   고정 구간이 0 이 된다 — wrapper 에 걸어야 본문 세로 블록 전체가 sticky 구간이 된다. */
section[data-testid="stMain"] div[data-testid="stLayoutWrapper"]:has(> [class*="st-key-nm_submitbar"]) {{
  position:sticky; bottom:0; z-index:6; background:{_CANVAS};
  border-top:1px solid {_LINE_SEC}; padding:12px 0 8px; margin-top:24px; }}
.st-key-nm_submitbar div[data-testid="stHorizontalBlock"] {{ gap:16px !important; }}
.st-key-nm_submitbar div[data-testid="stColumn"]:last-child
  div[data-testid="stVerticalBlock"] {{ align-items:flex-end; }}
.st-key-nm_submitbar .stButton > button {{ min-height:{_HIT_PX}px !important;
  padding:0 24px; font-size:14px !important; }}
/* 비활성 제출은 주 액션처럼 보이면 안 된다(§3.2 — 사유 없는/구분 없는 회색 버튼 금지의
   역방향 결함). 공용 ui.py 의 primary 규칙이 :disabled 를 예외로 두지 않아 비활성인데도
   액센트 채움으로 그려진다 — 이 화면 범위에서 §1.3 '종료·중립' 의미색으로 되돌린다. */
.st-key-nm_submitbar [class*="st-key-nm_submit_btn"] button:disabled {{
  background:#f2f0ec !important; border-color:#e4e0d8 !important; color:#5c564d !important; }}
.nm-req {{ display:flex; align-items:center; flex-wrap:wrap; gap:4px 12px; }}
.nm-req .cnt {{ font-size:12px; color:{_INK2}; white-space:nowrap; }}
.nm-req .cnt .n {{ font-family:{_MONO}; font-variant-numeric:tabular-nums; }}
.nm-req .cnt b {{ color:{_INK}; font-weight:600; }}
.nm-req .pb {{ flex:0 0 96px; height:4px; border-radius:999px; background:{_LINE};
  overflow:hidden; }}
.nm-req .pb > i {{ display:block; height:100%; background:{_ACCENT}; }}
.nm-req .rest {{ font-size:14px; color:{_INK2}; text-wrap:pretty; }}
.nm-req .rest b {{ color:{_INK}; font-weight:600; }}
/* ── 03 · 사진 첨부(선택) — 드롭존을 §1.3 헤어라인·점선으로 정돈(카드 아님). ── */
.st-key-nm_photo_zone [data-testid="stFileUploaderDropzone"] {{
  background:#fbfaf8 !important; border:1px dashed {_LINE_SEC} !important;
  border-radius:8px !important; }}
.st-key-nm_photo_zone [data-testid="stFileUploaderDropzone"]:hover {{
  border-color:{_LINE_HDR} !important; }}
.st-key-nm_photo_thumbs [data-testid="stImage"] img {{
  border:1px solid {_LINE} !important; border-radius:8px !important; }}
/* 사진 삭제·완료 화면 버튼, 업로더의 [Browse files], 카메라 expander 머리도 같은 화면의
   조작 대상이다 — cozy 하한(44)을 함께 따른다(§1.4 · §3.4 모바일 우선 화면). */
[class*="st-key-nm_photo_del_"] button,
[class*="st-key-nm_done_"] button,
.st-key-nm_photo_zone [data-testid="stFileUploaderDropzone"] button,
.st-key-nm_photo_zone [data-testid="stBaseButton-secondary"] {{
  min-height:{_HIT_PX}px !important;
  border-radius:8px !important; font-size:14px !important; }}
/* 카메라 expander 머리와 촬영 버튼도 조작 대상이다(실측 33px·34.9px → cozy 하한 미달). */
section[data-testid="stMain"] details summary,
button[data-testid="stCameraInputButton"] {{ min-height:{_HIT_PX}px !important; }}
section[data-testid="stMain"] details summary {{ display:flex; align-items:center; }}
.nm-note {{ font-size:12px; color:{_WEAK}; line-height:1.6; margin-top:8px; }}
.nm-note b {{ color:{_INK}; font-weight:600; }}
/* ── §3.4 `<599px`: 라벨 열 + 값 열을 세로로 접는다(라벨 위 · 값 아래) ──
   값 열이 하나라는 §3.1 성질은 접힌 뒤에도 유지된다(오히려 강해진다). 선택자 특정도를
   위 규칙과 같게 맞춰야(`:first-child`/`:last-child`) 미디어쿼리가 실제로 이긴다. */
@media (max-width:598px) {{
  [class*="st-key-nmrow_"] div[data-testid="stHorizontalBlock"] {{
    flex-wrap:wrap !important; gap:4px 16px !important; }}
  [class*="st-key-nmrow_"] div[data-testid="stColumn"]:first-child,
  [class*="st-key-nmrow_"] div[data-testid="stColumn"]:last-child {{
    flex:1 1 100% !important; width:100% !important; min-width:100% !important; }}
  /* 폭 3계단(140/272/524)은 데스크톱 값이다. 접힌 폭에서는 값 열 자체가 이미 좁으므로
     컨트롤을 열 폭에 맞춘다 — 그러지 않으면 375px 화면에서 서술 상자(524)가 넘쳐
     가로 스크롤이 생긴다. 값 열은 접힌 뒤에도 **하나**다(§3.1). */
  [class*="st-key-nmrow_"] div[data-testid="stElementContainer"] {{
    width:100% !important; max-width:100% !important; }}
  .nm-lb.top {{ padding-top:0; }}
  .nm-id .lock {{ margin-left:0; flex:1 1 100%; }}
  .st-key-nm_submitbar div[data-testid="stColumn"] {{
    flex:1 1 100% !important; width:100% !important; min-width:100% !important; }}
  .st-key-nm_submitbar div[data-testid="stColumn"]:last-child
    div[data-testid="stVerticalBlock"] {{ align-items:stretch; }}
  /* 제출은 접힌 폭에서 전폭 — 클래스명이 아니라 st-key 스코프로 잡는다(emotion 해시
     선택자 금지). width="content" 가 남기는 인라인 폭을 !important 로 덮는다. */
  .st-key-nm_submitbar [class*="st-key-nm_submit_btn"],
  .st-key-nm_submitbar [class*="st-key-nm_submit_btn"] > div,
  .st-key-nm_submitbar [class*="st-key-nm_submit_btn"] button {{ width:100% !important; }}
}}
</style>
"""


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _dept_display(dept_code: str) -> str:
    code = _clean(dept_code)
    if not code:
        return "미지정"
    try:
        depts = db.get_departments()
        hit = depts[depts["dept_code"].astype(str).str.strip() == code]
        if not hit.empty:
            name = _clean(hit.iloc[0].get("dept_name"))
            if name:
                return f"{name} ({code})"
    except Exception:  # noqa: BLE001 — 표시 폴백.
        pass
    return code


def _reset_form_state() -> None:
    for key in _FORM_WIDGET_KEYS:
        st.session_state.pop(key, None)
    _reset_photo_stage()


def _reset_photo_stage() -> None:
    """스테이징한 사진 bytes·처리 표식을 세션에서 정리한다(제출 성공·화면 이탈 시 메모리 잔류 방지)."""
    st.session_state.pop(_STAGE_KEY, None)
    st.session_state.pop(_STAGE_SEEN_KEY, None)


def _ingest_photo(upload, name: str) -> str | None:
    """업로드 1장을 선택 즉시 크기 사전검사→검증·압축해 스테이지에 추가한다. 오류 문구(없으면 None).

    ``upload`` 은 ``.size``/``.getvalue()`` 를 가진 UploadedFile. **getvalue() 로 전량 적재하기
    전에** ``.size`` 로 원본 상한(10MB/장)과 스테이징 누적 상한을 먼저 차단한다(대용량 메모리
    적재 방지). 그다음 photo_storage 순수 계약(확장자+매직바이트 jpg/png/webp·JPEG 정규화)으로
    검증·압축해 잘못된 파일을 제출 전에 즉시 거른다(modules 무수정 — API 소비만)."""
    stage = st.session_state.setdefault(_STAGE_KEY, [])
    if len(stage) >= photo_storage.MAX_PHOTOS:
        return f"사진은 최대 {photo_storage.MAX_PHOTOS}장까지 첨부할 수 있습니다. '{name}'은(는) 제외했습니다."
    # 원본 크기 사전 검사(getvalue 전 — 대용량은 메모리에 올리지 않고 차단).
    size = getattr(upload, "size", None)
    if isinstance(size, int) and size > _MAX_UPLOAD_BYTES:
        return f"{name}: 이미지 용량이 너무 큽니다. 최대 {_MAX_UPLOAD_MB}MB 까지 첨부할 수 있습니다."
    staged_total = sum(int(p.get("size") or 0) for p in stage)
    if isinstance(size, int) and staged_total + size > _STAGE_TOTAL_CAP_BYTES:
        return (f"{name}: 첨부 사진 총 용량이 한도({_STAGE_TOTAL_CAP_MB}MB)를 초과했습니다. "
                "큰 사진을 줄이거나 일부만 첨부하세요.")
    try:
        data = upload.getvalue()
    except Exception:  # noqa: BLE001 — 업로더 스트림 읽기 실패(원문 비노출).
        return f"{name}: 파일을 읽을 수 없습니다."
    try:
        out, _ext, _ctype = photo_storage.validate_and_compress(data, name)
    except photo_storage.PhotoValidationError as exc:
        return f"{name}: {exc}"
    except Exception:  # noqa: BLE001 — 손상/미지원 이미지(원문 비노출).
        return f"{name}: 이미지를 처리할 수 없습니다."
    stage.append({"id": uuid.uuid4().hex, "name": name, "bytes": out,
                  "size": int(size) if isinstance(size, int) else len(data)})
    return None


def _render_photo_stage() -> None:
    """03 · 사진 첨부(선택) — 업로더(다중)+카메라(expander) 스테이징 + 썸네일·개별 삭제.

    반응형 위젯으로 렌더한다(선택 즉시 썸네일·삭제 반영). 선택 즉시 검증·압축해 세션에 스테이징
    하고, 실제 저장은 제출 성공 후 _attach_staged_photos 가 db API 로 수행한다."""
    _section("03", "사진 첨부", opt="선택")
    stage = st.session_state.setdefault(_STAGE_KEY, [])
    seen = st.session_state.setdefault(_STAGE_SEEN_KEY, set())
    errors: list[str] = []

    with st.container(key="nm_photo_zone"):
        ups = st.file_uploader(
            "현장 사진 선택", type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True, key=_UP_KEY, label_visibility="collapsed",
            max_upload_size=_MAX_UPLOAD_MB,  # 위젯 단위 상한(MB) — 서버 config 와 병행 차단.
            help=f"JPG·PNG·WEBP · 최대 {photo_storage.MAX_PHOTOS}장 · 원본 {_MAX_UPLOAD_MB}MB 이하",
        )
    for f in (ups or []):
        fid = getattr(f, "file_id", None) or f.name
        if fid in seen:
            continue
        seen.add(fid)
        err = _ingest_photo(f, f.name or "사진.jpg")
        if err:
            errors.append(err)

    with st.expander("사진 촬영 (카메라)", expanded=False):
        cam = st.camera_input("사진 촬영", key=_CAM_KEY, label_visibility="collapsed")
    if cam is not None:
        fid = getattr(cam, "file_id", None)
        if fid and fid not in seen:
            seen.add(fid)
            err = _ingest_photo(cam, "촬영사진.jpg")
            if err:
                errors.append(err)

    for e in errors:
        banner("warn", e)

    if stage:
        with st.container(key="nm_photo_thumbs"):
            cols = st.columns(photo_storage.MAX_PHOTOS)
            for i, ph in enumerate(stage):
                with cols[i]:
                    st.image(ph["bytes"], width="stretch")
                    if st.button("삭제", key=f"nm_photo_del_{ph['id']}", width="stretch"):
                        st.session_state[_STAGE_KEY] = [p for p in stage if p["id"] != ph["id"]]
                        st.rerun()

    st.markdown(
        f"<div class='nm-note'>{len(stage)} / {photo_storage.MAX_PHOTOS}장 · 사진은 선택 "
        "항목입니다. 선택한 사진은 <b>제출</b> 시 함께 첨부됩니다.</div>",
        unsafe_allow_html=True,
    )


def _identity_row(user: dict) -> None:
    """신원 줄(§2) — 신고자·사번·소속을 세션 사용자에서 확정해 읽기 전용으로 표시한다."""
    name = _clean(user.get("name")) or "(이름 미확인)"
    emp_no = _clean(user.get("emp_no"))
    dept = _dept_display(user.get("dept_code"))
    st.markdown(
        "<div class='nm-id'><span class='ov'>신원</span>"
        f"<span class='it'><span class='k'>신고자</span><span class='v'>{escape(name)}</span></span>"
        f"<span class='it'><span class='k'>사번</span><span class='v'>{escape(emp_no)}</span></span>"
        f"<span class='it'><span class='k'>소속</span><span class='v'>{escape(dept)}</span></span>"
        "<span class='lock'>로그인 정보로 자동 지정 · 수정 불가</span></div>",
        unsafe_allow_html=True,
    )


def _section(num: str, label: str, opt: str = "") -> None:
    right = f"<span class='opt'>{escape(opt)}</span>" if opt else ""
    st.markdown(
        f"<div class='nm-sec'><span class='ov'><span class='no'>{escape(num)}</span> "
        f"· {escape(label)}</span>"
        f"<span class='rule'></span>{right}</div>",
        unsafe_allow_html=True,
    )


def _row(field_key: str, label: str, *, required: bool = True, top: bool = False):
    """라벨 열(130px) + 값 열 한 행을 열고 **값 열**을 반환한다(§3.1·§2).

    호출부는 ``with _row(...):`` 안에서 컨트롤 하나만 렌더한다 — 값 열은 하나다(§4-4).
    ``top`` 은 서술 입력(text_area)처럼 높이가 큰 컨트롤에서 라벨을 상단 정렬한다.
    """
    mark = "<span class='req'> *</span>" if required else ""
    cls = "nm-lb top" if top else "nm-lb"
    with st.container(key=f"nmrow_{field_key}"):
        label_col, value_col = st.columns(
            [1, 3], vertical_alignment=("top" if top else "center"), gap="small")
        with label_col:
            st.markdown(f"<div class='{cls}'>{escape(label)}{mark}</div>",
                        unsafe_allow_html=True)
    return value_col


def _validate(fields: dict) -> list[str]:
    """필수 항목 검증 — 비어 있는 항목의 한글 라벨 목록을 ``_REQUIRED`` 순서로 반환한다.

    **하단 고정 바의 개수·남은 항목 이름과 제출 시 재검증이 이 함수 하나를 공유한다**(§2 —
    필드가 늘 때 두 곳을 고쳐야 하는 구조를 만들지 않는다). 계약 불변: 라벨 집합과 "비어
    있으면 미충족" 판정은 종전과 같다.
    """
    missing: list[str] = []
    for label, key in _REQUIRED:
        value = fields.get(key)
        if value in (None, "") or (isinstance(value, str) and not value.strip()):
            missing.append(label)
    return missing


def _subject_particle(word: str) -> str:
    """받침 유무로 주격 조사 '이/가'를 고른다(§3.5 — '이(가)' 같은 군더더기 표기 회피)."""
    ch = (word or "").strip()[-1:]
    if ch and "가" <= ch <= "힣":
        return "이" if (ord(ch) - 0xAC00) % 28 else "가"
    return "가"


def _remaining_html(missing: list[str]) -> str:
    """남은 항목 **이름**을 문장으로 만든다(§2 — 개수만으로는 무엇이 빠졌는지 알 수 없다)."""
    if len(missing) <= 3:
        names, last = " · ".join(missing), missing[-1]
    else:
        names = " · ".join(missing[:2]) + f" 외 {len(missing) - 2}개"
        last = "개"
    return f"<b>{escape(names)}</b>{_subject_particle(last)} 남았습니다"


def _submit_bar(values: dict, schema_ready: bool) -> bool:
    """하단 고정 제출 바(§2) — 필수 개수 + 진행 바 + 남은 항목 이름 + [제출].

    미충족이면 제출을 비활성으로 두되 **사유를 화면에 쓴다**(§3.2·§4-3). 제출 버튼을 눌러야
    뭐가 빠졌는지 알게 하지 않는다(§2). 별도 체크리스트 패널은 두지 않는다 — 라벨 열 구조에서
    폼 자체가 이미 세로 목록이라 빈 값이 보이고, 다시 나열하면 §4-2 에 걸린다.
    """
    missing = _validate(values)
    total = len(_REQUIRED)
    done = total - len(missing)
    pct = round(done / total * 100) if total else 0
    if not schema_ready:
        rest = escape("아차사고 스키마가 준비되지 않아 저장할 수 없습니다")
    elif missing:
        rest = _remaining_html(missing)
    else:
        rest = "모든 필수 항목을 채웠습니다"
    status = (
        "<div class='nm-req'>"
        f"<span class='cnt'>필수 <span class='n'><b>{done}</b>/{total}</span></span>"
        f"<span class='pb'><i style='width:{pct}%'></i></span>"
        f"<span class='rest'>{rest}</span></div>"
    )
    with st.container(key="nm_submitbar"):
        status_col, action_col = st.columns([3, 1], vertical_alignment="center", gap="small")
        with status_col:
            st.markdown(status, unsafe_allow_html=True)
        with action_col:
            return st.button("제출", type="primary", key="nm_submit_btn",
                             disabled=not (schema_ready and not missing), width="content")


def _readiness_gate() -> bool:
    probe = db.near_miss_schema_probe()
    if probe == "READY":
        return True
    if probe == "NOT_READY":
        banner("warn", "아차사고 스키마가 아직 준비되지 않아 신청을 저장할 수 없습니다. "
                       "스키마 적용 후 다시 시도하세요.")
    else:  # PROBE_ERROR
        banner("danger", "아차사고 스키마 상태를 확인하지 못했습니다. 잠시 후 다시 시도하세요.")
    return False


def render(user: dict) -> None:
    _SUBMIT_DESC = "현장에서 발견한 아차사고(near-miss)를 접수 등록합니다. 접수 후 상태는 제출됨(SUBMITTED)입니다."
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="아차사고 등록",
        desc=_SUBMIT_DESC,
        breadcrumb="아차사고 › 아차사고 등록",
        badges=scaffold.mode_badge(),
    )
    # CSS 주입 블록은 키드 컨테이너에 넣어 레이아웃(gap 계산)에서 제외한다 — 위 _FORM_CSS 의
    # `st-key-nm_css` 규칙 참조. 주입 자체는 종전과 동일하다.
    with st.container(key="nm_css"):
        st.markdown(_FORM_CSS, unsafe_allow_html=True)

    done = st.session_state.get(_DONE_KEY)
    if done:
        _render_post_submit(done)
        return

    schema_ready = _readiness_gate()

    # ── 신원 줄(§2 골격 첫 블록) ──
    # st.form 을 쓰지 않는다: 폼 위젯은 제출 전까지 세션에 커밋되지 않아 하단 바의 필수 충족
    # 표시가 비실시간이 된다. 일반 키드 위젯 + st.button 제출로 입력이 즉시 반영되게 한다.
    # 제출 계약(제출 시 전체 재검증·필수 8필드·사진 스테이징-후-첨부)은 불변이고, 키드 위젯의
    # 세션 보존(이탈 후 재진입 시 초안 유지)도 st.form 때와 동일하다.
    _identity_row(user)

    # ── 01 · 기본 정보 ── (읽기 화면 상세 머리와 같은 순서: 작업명 → 발생일)
    _section("01", "기본 정보")
    with _row("work_name", "작업명"):
        # 폭 272 = 한 줄 구 20자(_W_LINE 주석의 역산). 작업명 실값은 "원료 투입"(5자)~
        # "3라인 컨베이어 벨트 점검"(11.5자 등가)이라 20자면 넘치지 않고, 값 열을 다 채우지
        # 않으므로 "한 줄짜리 답"이라는 것이 폭으로 보인다.
        work_name = st.text_input(
            "작업명", max_chars=120, key=f"{_WKEY}work_name", label_visibility="collapsed",
            placeholder="예: 3라인 컨베이어 벨트 점검", width=_W_LINE)
    with _row("incident_date", "발생일"):
        incident_date = st.date_input(
            "발생일", value=date.today(), format="YYYY-MM-DD",
            key=f"{_WKEY}incident_date", label_visibility="collapsed", width=_W_SHORT)

    # ── 02 · 상황 기술 ── (평가 상세 주요 내용 표와 같은 순서)
    _section("02", "상황 기술")
    # 서술 4칸은 같은 폭(524 = 한 줄 40자)을 쓴다 — 같은 부류의 칸이 서로 다른 폭이면
    # 우측 가장자리가 어긋나고, 어긋난 가장자리는 읽는 사람에게 아무 정보도 주지 않는다.
    # 높이만 내용의 분량 차이를 표현한다(사고내용 4줄, 나머지 3줄).
    with _row("incident_content", "사고내용", top=True):
        incident_content = st.text_area(
            "사고내용", height=_H_PROSE_4, key=f"{_WKEY}incident_content",
            label_visibility="collapsed", width=_W_PROSE,
            placeholder="무슨 일이 있었는지(아차사고 상황)를 구체적으로 적어 주세요")
    with _row("work_content", "작업내용", top=True):
        work_content = st.text_area(
            "작업내용", height=_H_PROSE_3, key=f"{_WKEY}work_content",
            label_visibility="collapsed", width=_W_PROSE,
            placeholder="어떤 작업을 하고 있었는지")
    with _row("site_description", "작업현장 상황설명", top=True):
        site_description = st.text_area(
            "작업현장 상황설명", height=_H_PROSE_3, key=f"{_WKEY}site_description",
            label_visibility="collapsed", width=_W_PROSE,
            placeholder="현장 상황 · 주변 환경")
    with _row("cause_code", "발생원인"):
        cause_code = st.selectbox(
            "발생원인", [""] + list(db.NEAR_MISS_CAUSE_CODES), index=0,
            key=f"{_WKEY}cause_code", label_visibility="collapsed", width=_W_SHORT,
            format_func=lambda c: "— 선택 —" if c == "" else f"{_CAUSE_LABELS.get(c, c)} ({c})")
    with _row("cause_detail", "발생원인 상세"):
        # 실값은 "결속 불량"·"시야 미확보"(5~6자)다. max_chars=200 은 저장 상한이지 기대
        # 답 길이가 아니므로 폭은 한 줄 구 계단(272)을 쓴다.
        cause_detail = st.text_input(
            "발생원인 상세", max_chars=200, key=f"{_WKEY}cause_detail",
            label_visibility="collapsed", placeholder="원인을 구체적으로", width=_W_LINE)
    with _row("countermeasure", "예방대책", top=True):
        countermeasure = st.text_area(
            "예방대책", height=_H_PROSE_3, key=f"{_WKEY}countermeasure",
            label_visibility="collapsed", width=_W_PROSE,
            placeholder="재발을 막기 위한 대책")

    # ── 03 · 사진 첨부(선택) ── 본문은 01→02→03 으로 자연 종결하고 제출은 하단 고정 바가 맡는다.
    _render_photo_stage()

    values = {
        "work_name": work_name,
        "incident_date": incident_date,
        "incident_content": incident_content,
        "work_content": work_content,
        "site_description": site_description,
        "cause_code": cause_code,
        "cause_detail": cause_detail,
        "countermeasure": countermeasure,
    }
    if not _submit_bar(values, schema_ready):
        return

    # 비활성 게이트를 통과한 뒤에도 제출 시 전체를 재검증한다(계약 불변 — 화면 게이트는
    # 편의이고 검증이 정본이다).
    missing = _validate(values)
    if missing:
        banner("danger", "필수 항목을 입력하세요: " + ", ".join(missing))
        return

    # 등급은 등록에서 보내지 않는다 — 제안등급 폐기(§7.2-1b)로 등급은 확정등급(평가 단계)만
    # 쓴다. payload 에 proposed_grade 를 되살리지 말 것(DB 컬럼은 미사용으로 남는다).
    # 사진은 생성 payload 에 싣지 않고 빈 배열로 시작한다 — 업로드 API 가 '이미 존재하는
    # SUBMITTED 보고서'를 요구하므로, 스테이징한 사진은 보고서 생성 성공 후
    # _attach_staged_photos 가 db.upload_near_miss_photo 로 append 한다(스테이징-후-첨부).
    # 즉 photo_paths=[] 는 미구현(GATED)이 아니라 '생성 시점엔 아직 비어 있음'이다.
    payload = {
        "work_name": _clean(work_name),
        "cause_code": cause_code,
        "cause_detail": _clean(cause_detail),
        "incident_date": incident_date.isoformat(),
        "work_content": _clean(work_content),
        "incident_content": _clean(incident_content),
        "countermeasure": _clean(countermeasure),
        "site_description": _clean(site_description),
        "photo_paths": [],
    }
    _persist_and_report(payload)


def _persist_and_report(payload: dict) -> None:
    """저장을 시도하고 lifecycle PersistResult/ledger_banner 패턴으로 결과를 표시한다.

    도메인 검증 오류(ValueError)는 그대로 노출하고, 그 외 예외는 원문을 감춰 '결과 불명'으로 접는다."""
    try:
        record = db.create_near_miss_report(payload, current_user=auth.get_current_user())
    except ValueError as exc:
        ledger_banner(PersistResult.failure(_PAGE_ID, [payload.get("work_name") or "신청"],
                                            str(exc), retryable=True))
        return
    except Exception:  # noqa: BLE001 — raw 예외 문구 비노출.
        ledger_banner(PersistResult.unresolved(
            _PAGE_ID, "저장 결과를 확인할 수 없습니다. 목록을 재조회한 뒤 다시 시도하세요."))
        return

    report_no = _clean((record or {}).get("report_no")) or "(채번 확인 필요)"
    # 보고서 생성 성공 → 스테이징한 사진을 db API 로 첨부(스테이징-후-첨부). 개별 실패는 경고로
    # 표면화하되 제출 자체는 성공 처리한다(사진은 선택 항목). 처리 후 세션 스테이지를 정리한다.
    photo_warnings = _attach_staged_photos((record or {}).get("id"))
    _reset_photo_stage()
    st.session_state[_DONE_KEY] = {"report_no": report_no, "photo_warnings": photo_warnings}
    st.rerun()


def _attach_staged_photos(report_id) -> list[str]:
    """제출 성공 후 스테이징 사진을 순차 첨부한다(소유자+SUBMITTED 게이트는 파사드가 재확인).

    신원은 위젯이 아니라 세션 사용자에서 서버측 확정한다(위조 방지). 개별 실패 문구 목록을
    반환한다(빈 목록이면 전부 성공)."""
    stage = st.session_state.get(_STAGE_KEY) or []
    if not report_id or not stage:
        return []
    current_user = auth.get_current_user()
    warnings: list[str] = []
    for ph in stage:
        try:
            db.upload_near_miss_photo(report_id, ph["bytes"], ph["name"], current_user=current_user)
        except ValueError as exc:
            warnings.append(f"{ph['name']}: {exc}")
        except Exception:  # noqa: BLE001 — 저장 백엔드 오류(원문 비노출).
            warnings.append(f"{ph['name']}: 첨부하지 못했습니다.")
    return warnings


def _render_post_submit(done: dict) -> None:
    """제출 완료 결과 배너 + 다음 작업 선택([내 아차사고에서 확인]·[새 아차사고 등록])."""
    report_no = _clean(done.get("report_no")) or "(채번 확인 필요)"
    ledger_banner(PersistResult.success(_PAGE_ID, [report_no]))
    banner("success",
           f"아차사고를 접수했습니다. 접수번호 {report_no} · 상태 제출됨(SUBMITTED)")

    # 사진 첨부 부분 실패 안내 — 보고서는 저장됐고 SUBMITTED 동안 '내 아차사고'에서 재첨부 가능.
    warns = done.get("photo_warnings") or []
    if warns:
        banner("warn",
               "일부 사진을 첨부하지 못했습니다: " + " / ".join(warns)
               + " — 제출됨(SUBMITTED) 상태 동안 '내 아차사고'에서 다시 첨부할 수 있습니다.")

    st.markdown(
        f"<div style='font-size:14px;color:{_INK2};margin:8px 0 4px;'>다음 작업을 선택하세요.</div>",
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("내 아차사고에서 확인", type="primary", width="stretch",
                     key="nm_done_go_my", icon=":material/inbox:"):
            _reset_form_state()
            st.session_state.pop(_DONE_KEY, None)
            ui.request_nav({"type": "page", "target": "near_miss_my"})
    with c2:
        if st.button("새 아차사고 등록", width="stretch",
                     key="nm_done_new", icon=":material/add:"):
            _reset_form_state()
            st.session_state.pop(_DONE_KEY, None)
            st.rerun()
