"""기준정보 — 근무형태 관리 (기준정보 3화면 공통 기반 `views.master` 재구현).

Phase4 Lane C. 기능 계약(조회/신규행/편집/선택삭제/저장/새로고침, 코드·이름·약칭·
색상·순서·사용여부 필드, 삭제 정책)을 보존하면서 UI·상태·저장 계약을 공통 기반
(`views/master/*`)과 `design-contract.md` 로 옮긴다.

이 화면만의 고유 요소(디자인 계약 §11·§25 근무형태 예외):
  - **색상 셀**: 스와치 + 대문자 HEX + 네이티브 컬러 피커. **양방향 편집**(피커/텍스트)
    으로 개선하고, 유효하지 않으면 스와치를 대각선 해치로 표시한다. 저장 형식은
    기존과 동일한 ``#RRGGBB`` 를 유지한다. ``work_types.color`` 단일 기준이 근무표
    (월간/전체/개인/대시보드)의 셀 배경·뱃지·범례 색을 구동하는 계약은 불변이다.
  - **저장 전 검증 보강**(Codex 지적): 코드·약칭 필수, HEX ``#RRGGBB`` 형식, 시작/종료
    ``HH:MM`` 형식, 코드 중복(저장 차단)·약칭 중복(소프트 경고)을 검증한다.
  - **삭제**: 근무표에서 참조 중인 코드는 미사용 처리(is_active=False), 참조 없는 코드는
    물리 삭제한다. 항상 2단계 확인.

``code`` 는 근무표 FK 안정키다(rename 주의 — 저장은 upsert 이므로 코드를 바꾸면 신규로
간주된다). 저장 실패 시 편집 draft 는 재적재/리마운트 없이 보존한다.
"""
from __future__ import annotations

# DESIGN.md §0 화면 유형 규약 — 기준정보 편집형.
SCREEN_ARCHETYPE = "EDIT_GRID"

import json
import re

import pandas as pd
import streamlit as st
from st_aggrid import JsCode

from modules import db
from views import master
from views.common import erp
from views.master import (
    ADD,
    CORE_META,
    DELETE,
    REFRESH,
    SAVE,
    MasterGridSpec,
    PersistResult,
    confirm_bar,
    count_strip,
    dirty_total,
    grid_bool,
    ledger_banner,
    live_rows,
    master_grid_height,
    render_master_grid,
    run_save,
    style,
)
from views.master.state import RELOAD, DraftState

PAGE_ID = "master_work_types"

_STATUS = ["사용 중", "사용 안 함", "전체"]
_USER_COLS = ["코드", "명칭", "분류", "약칭", "시작", "종료", "색상", "실근무", "특근수당", "설명", "표시순서", "사용"]
_BOOL_COLS = {"실근무", "특근수당", "사용"}
_ROW_COLS = [*CORE_META, *_USER_COLS]
_GRID_COLUMNS = {c: ("bool" if c in _BOOL_COLS else "text") for c in _USER_COLS}

# 화면 한글 컬럼 ↔ db.WORK_TYPE_COLUMNS 매핑.
_FIELD_BY_COL = {
    "코드": "code", "명칭": "name", "분류": "category", "약칭": "short_label",
    "시작": "start_time", "종료": "end_time", "색상": "color",
    "실근무": "is_work", "특근수당": "affects_allowance", "설명": "description",
    "표시순서": "sort_order", "사용": "is_active",
}

_DEFAULT_COLOR = "#9AA0A6"
_HEX_BODY_RE = re.compile(r"^[0-9a-fA-F]{6}$")
_HEX3_RE = re.compile(r"^[0-9a-fA-F]{3}$")
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")

# ---- 세션 보조 키(page-scoped, DraftState.key 로 스코프) ----
_BASELINE = "baseline"          # {row_id: {col: 정규화값}} — 기존 변경 감지 기준
_CELL_ERRORS = "cell_errors"    # {row_id: {col: msg}} — 셀 오류 metadata
_SAVE_ERRORS = "save_errors"    # {"errors": [...]} — 검증 실패 오류 배너
_SAVE_LEDGER = "save_ledger"    # PersistResult — 부분성공/결과불명 원장 배너(§22)
_DELETE_ERROR = "delete_error"  # str — 삭제 재시도 확인 바에 표시할 실패 사유(B4)
_LAST_COUNTS = "last_counts"    # (new, changed, sel) — 오류 배너 흡수 문구용


# ---------------------------------------------------------------------------
# 색상 셀 — 스와치 + 대문자 HEX(렌더러) / 네이티브 피커 + 텍스트 양방향(에디터).
# 저장은 #RRGGBB. 유효하지 않은 값은 대각선 해치로 표시(디자인 계약 §11).
# ---------------------------------------------------------------------------
_COLOR_RENDERER = JsCode(
    """
    (class {
      init(p) {
        const v = String(p.value == null ? '' : p.value).trim();
        const valid = /^#([0-9a-fA-F]{6})$/.test(v);
        const g = document.createElement('div');
        g.style.display='flex'; g.style.alignItems='center'; g.style.height='100%'; g.style.gap='8px'; g.style.paddingLeft='6px';
        const sw = document.createElement('span');
        sw.style.width='16px'; sw.style.height='16px'; sw.style.borderRadius='4px';
        sw.style.border='1px solid rgba(0,0,0,0.18)'; sw.style.flex='0 0 auto';
        if (valid) { sw.style.background = v; }
        else { sw.style.background = 'repeating-linear-gradient(45deg,#eee,#eee 3px,#ccc 3px,#ccc 6px)'; }
        g.appendChild(sw);
        const t = document.createElement('span');
        t.textContent = v || '—';
        t.style.fontSize='12px'; t.style.letterSpacing='.02em';
        t.style.color = valid ? '#24262B' : '#908C83';
        t.style.fontVariantNumeric='tabular-nums';
        g.appendChild(t);
        this.eGui = g;
      }
      getGui() { return this.eGui; }
      refresh() { return false; }
    })
    """
)
_COLOR_EDITOR = JsCode(
    """
    (class {
      init(p) {
        const raw = String(p.value == null ? '' : p.value).trim();
        this.value = /^#([0-9a-fA-F]{6})$/.test(raw) ? raw.toUpperCase() : '#9AA0A6';
        const g = document.createElement('div');
        g.style.display='flex'; g.style.alignItems='center'; g.style.height='100%'; g.style.gap='8px'; g.style.paddingLeft='6px';
        const pick = document.createElement('input');
        pick.type='color'; pick.value=this.value;
        pick.style.width='26px'; pick.style.height='22px'; pick.style.border='none';
        pick.style.background='transparent'; pick.style.cursor='pointer'; pick.style.padding='0';
        const hex = document.createElement('input');
        hex.type='text'; hex.value=this.value; hex.maxLength=7;
        hex.style.width='84px'; hex.style.fontSize='12px'; hex.style.padding='2px 4px';
        hex.style.border='1px solid #D4CEC3'; hex.style.borderRadius='4px';
        hex.style.fontVariantNumeric='tabular-nums'; hex.style.textTransform='uppercase';
        const sync = (val, from) => {
          const m = /^#?([0-9a-fA-F]{6})$/.exec(String(val).trim());
          if (m) { this.value = '#' + m[1].toUpperCase(); pick.value = this.value; if (from !== 'hex') hex.value = this.value; }
        };
        pick.addEventListener('input', () => { this.value = pick.value.toUpperCase(); hex.value = this.value; });
        hex.addEventListener('input', () => sync(hex.value, 'hex'));
        g.appendChild(pick); g.appendChild(hex);
        this.eGui = g; this.eHex = hex;
      }
      getGui() { return this.eGui; }
      afterGuiAttached() { this.eHex.focus(); this.eHex.select(); }
      getValue() {
        const m = /^#?([0-9a-fA-F]{6})$/.exec(String(this.eHex.value).trim());
        return m ? ('#' + m[1].toUpperCase()) : String(this.value || '').toUpperCase();
      }
      isPopup() { return false; }
    })
    """
)

# 불리언 셀(실근무·특근수당·사용) — 공통 native ``cellDataType='boolean'`` 로 표시·편집한다.
# ag-grid 자체 boolean 렌더러/에디터를 쓰므로 별도 JsCode 렌더러를 주입하지 않는다.
# (JsCode 셀 렌더러는 Streamlit Cloud Python 3.14 배포에서 실행되지 않아 체크박스가 사라지는
#  High 회귀가 있었다 — grid.py 의 [LEGACY] BOOL_DISPLAY_RENDERER 주석 참조.)

# ---------------------------------------------------------------------------
# 약칭 셀 — 값 + 라이브 중복 경고칩(공통 `.ms-chip warn`). 활성 행끼리 같은 약칭이
# 둘 이상이면 표시(근무표는 코드로 표시되므로 저장 차단이 아닌 소프트 경고 §11).
# 중복 판정은 저장 검증 `_duplicate_short_labels` 와 동일 규칙(활성·비어있지 않음).
# 다른 행/사용 편집에 반응하도록 grid `onCellValueChanged` 가 이 열을 refresh 한다.
# ---------------------------------------------------------------------------
_SHORT_LABEL_RENDERER = JsCode(
    """
    (class {
      init(p) { this.eGui = document.createElement('div'); this._render(p); }
      _active(d) {
        const removed = String(d._removed == null ? '' : d._removed).trim() === '1';
        const u = d['사용'];
        const use = (u === true || u === 'true' || u === 1 || u === '사용' || u === '재직');
        return !removed && use;
      }
      _textOn(hex) {
        const m = /^#([0-9a-fA-F]{6})$/.exec(hex); if (!m) { return '#1c1a17'; }
        const n = parseInt(m[1], 16);
        const f = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
        const L = 0.2126 * f((n >> 16) & 255) + 0.7152 * f((n >> 8) & 255) + 0.0722 * f(n & 255);
        return (1.05 / (L + 0.05)) >= ((L + 0.05) / 0.05) ? '#ffffff' : '#000000';
      }
      _render(p) {
        const g = this.eGui; g.innerHTML = '';
        g.style.display = 'flex'; g.style.alignItems = 'center'; g.style.gap = '6px'; g.style.height = '100%';
        const d = p.data || {};
        const val = String(p.value == null ? '' : p.value).trim();
        const hex = String(d['색상'] == null ? '' : d['색상']).trim();
        const valid = /^#([0-9a-fA-F]{6})$/.test(hex);
        // §1-E: 약칭 = 근무형태 색 chip(DB hex solid, dc t.chipStyle). 근무표/대시보드 배지와
        // 동일한 색 어휘로, 색이 없으면 평문 폴백. 색·약칭 SoT 는 DB(이 셀은 표시 전용).
        const t = document.createElement('span');
        t.textContent = val || '—';
        if (val && valid) {
          t.style.background = hex; t.style.color = this._textOn(hex);
          t.style.padding = '1px 9px'; t.style.borderRadius = '999px';
          t.style.fontSize = '12px'; t.style.fontWeight = '600'; t.style.letterSpacing = '.01em';
        } else if (!val) { t.style.color = '#908C83'; }
        g.appendChild(t);
        if (val && this._active(d) && p.api) {
          let count = 0;
          const self = this;
          p.api.forEachNode(function(node) {
            const nd = node.data || {};
            if (self._active(nd) && String(nd['약칭'] == null ? '' : nd['약칭']).trim() === val) { count += 1; }
          });
          if (count > 1) {
            const chip = document.createElement('span');
            chip.className = 'ms-chip warn'; chip.textContent = '약칭 중복';
            chip.title = '같은 약칭이 여러 근무형태에 사용 중입니다. 근무표에서는 코드로 표시됩니다.';
            g.appendChild(chip);
          }
        }
      }
      getGui() { return this.eGui; }
      refresh(p) { this._render(p); return true; }
    })
    """
)

# 분류 셀 — 값 그대로(평문). 종전 `.ms-chip mute` 칩은 회색 색면이 열을 차지해
# 표에서 읽어야 할 값(코드·명칭)보다 먼저 눈을 끌었다(2026-08-19 사용자 판단: 표 안
# 장식성 색 채움 폐지). 분류는 상태가 아니라 값이라 색으로 부호화할 대상이 아니다 —
# 오류·경고 등 **기능 신호**(ms-cell-error / ms-row-error / 약칭 중복칩)만 남긴다.

# 약칭 중복칩은 다른 행의 약칭/사용 변경에 반응해야 한다 — 해당 셀 변경 시 약칭 열만
# 강제 refresh 한다(paste 는 onGridReady/onCellEditingStopped 를 쓰므로 충돌 없음).
_DUP_REFRESH = JsCode(
    """
    function(e) {
      const col = (e.column && e.column.getColId) ? e.column.getColId()
                  : (e.colDef && e.colDef.field);
      if ((col === '약칭' || col === '사용' || col === '색상') && e.api) {
        e.api.refreshCells({ columns: ['약칭'], force: true });
      }
    }
    """
)


# 자연키(코드) 잠금 — org/users 와 동일 계약. 코드는 근무표 스케줄이 참조하는 FK 안정키라
# 저장행에서 편집을 막는다(저장은 upsert 라 코드 변경 = 신규 간주 → 참조 orphan 위험).
# 신규 행에서만 편집 가능하고, 저장행엔 읽기전용 틴트(공통 .ms-cell-readonly)를 켠다.
_EDIT_NEW_ONLY = JsCode("function(p){ return !!(p.data && p.data._row_state === 'new'); }")
_CODE_READONLY_RULES = {"ms-cell-readonly": "data._row_state !== 'new'"}


# 불리언 열(실근무·특근수당·사용)은 공용 native 체크박스(cellDataType='boolean')만 쓴다.
# 종전에는 사용=녹색·실근무=파란색 pill 렌더러를 덮어써 같은 성격의 세 열이 서로 다른
# 모양이었고(특근수당만 체크박스), 색면 두 개가 표 오른쪽을 채워 값보다 먼저 눈에 띄었다.
# 2026-08-19 사용자 판단(표 안 장식성 색 채움 폐지)에 따라 pill 을 걷고 세 열을 같은
# 체크박스로 통일한다. 값·저장 경로(is_work/is_active)는 pill 이 display-only 였으므로 불변.
# pill 이 쓰던 12.5px 도 DESIGN §1.2 네 단계(24·20·14·12) 밖이었다.

# §1-E 건수 행 CSS(좌: 근무형태 제목 + 건수 pill + 사용/미사용 · 우: 편집 상태 칩). §2 리터럴.
# `.edit` 는 종전 인페이지 액션 버튼이 있던 우측 자리를 그대로 쓴다(margin-left:auto).
# 칩 자체는 공용 `.ms-chip` 토큰(style.py)이라 새 색을 만들지 않는다. 미저장·선택이 0이면
# 빈 span 이라 폭 0(빈 상태 문구로 화면을 채우지 않는다 — §6).
_WT_CROW_CSS = """
<style>
.wt-crow { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.wt-crow .t { font-size:14px; font-weight:600; color:#1c1a17; white-space:nowrap; }
.wt-crow .pill { font-family:'IBM Plex Mono',monospace; font-size:12px; font-weight:600;
  padding:2px 9px; border-radius:999px; background:#f1eee8; color:#4a453d; }
.wt-crow .dist { font-size:12px; color:#6b665d; white-space:nowrap;
  font-variant-numeric:tabular-nums; }
.wt-crow .edit { margin-left:auto; display:inline-flex; align-items:center; gap:6px; }
/* 색·모양은 공용 .ms-chip 토큰 그대로 쓰고 **크기만** 사용처에서 올린다 — 공용 정의는
   .68rem 이고 이 앱의 root 는 14px 라 실측 9.52px 로 떨어진다(DESIGN §0-6 라벨 11px 이하
   금지). 헤더 아이콘의 활성 근거를 읽는 숫자이므로 기준정보 3화면 공통 상태 칩 크기
   (12px/600)로 맞추고, 값이 실시간으로 바뀌므로 tabular-nums 로 자릿수 흔들림을 없앤다.
   ※ 공용 정의 자체(views/master/style.py `.ms-chip`)의 9.52px 는 소유 밖이라 보고만 한다. */
.wt-crow .edit .ms-chip { font-size:12px; padding:2px 8px;
  font-variant-numeric:tabular-nums; }
</style>
"""


# ---- 컬럼 폭 = 12px Pretendard 기준 역산(2026-08-19 재산정) ----
# 종전 값은 셀 14.5px·헤더 12.5px(맑은고딕 폴백) 기준이라 표 전체가 과대했다. DESIGN §1.2
# 개정으로 표 셀·헤더가 모두 12px 이 되어 같은 값이 그대로 남으면 열마다 20~40px 씩 빈다.
#
# 역산 규칙(실렌더 계측 2026-08-19, 1440px sample):
#   필요폭 = max(값 실측 최대 잉크, 헤더 실측 잉크) + 16  → 4의 배수로 올림
#   16 = 셀 좌우 패딩 7+7 + 보더 2 (헤더는 8+8). 잉크는 iframe 안 hidden span 으로 쟀다.
#   측정값에 5% 여유를 얹는다 — 그리드 iframe 이 지금은 Pretendard 를 못 받아 sans-serif
#   폴백으로 그려지는데(실측 .ag-cell font-family = sans-serif), 폴백 한글 10.53px/자 <
#   Pretendard 11.04px/자 라 폴백 기준으로만 잡으면 글꼴이 정상화되는 순간 잘린다.
#
# **이 값은 고정폭이 아니라 비율이다.** 아래 grid_options 의 autoSizeStrategy=fitGridWidth 가
# 남는 폭을 각 열의 지정 폭에 비례해 나눈다. 그래서 flex 를 쓰지 않는다 — flex 는 남는 폭을
# 특정 열 하나에 몰아주고(종전 설명 열이 313px, 값 최대 잉크는 101.8px), 값이 없는 열이
# 화면에서 가장 넓어지는 원인이었다.
#
# maxWidth 는 **넓혀도 담을 것이 없는 열**에만 건다(체크박스·고정 서식·상한 있는 코드값).
# 그 외 자유 텍스트 열(코드·명칭·분류·설명)이 남는 폭을 비례로 흡수한다.
_COL_WIDTHS = {
    # minWidth = width: fitGridWidth 는 뷰포트가 좁으면 열을 **minWidth 까지 줄여서**
    # 맞춘다(실측 390px: 코드명 120→96 으로 눌려 값이 잘렸다). 역산한 필요폭이 곧
    # 하한이므로 둘을 같은 값으로 둔다 — 좁은 폭에서는 줄이지 말고 가로 스크롤한다.
    # 코드 64 = '출산휴가' 44.17×1.05 + 16. 자연키라 좌측 고정(좁은 폭에서 신원 유지).
    "코드": {"width": 64, "minWidth": 64, "pinned": "left", "cellClass": "md-c-left",
            "editable": _EDIT_NEW_ONLY},
    # 명칭 112 = '경조(자녀결혼)' 89.7×1.05 + 16. 행을 특정하는 열이라 상한을 두지 않는다.
    "명칭": {"width": 112, "minWidth": 112, "cellClass": "md-c-left"},
    # 분류 52 = '경조사' 33.13×1.05 + 16 (칩 패딩 18 제거분 반영).
    "분류": {"width": 52, "minWidth": 52, "cellClass": "md-c-left"},
    # 약칭 64 = 색 chip('OFF' 43.38)×1.05 + 16. 약칭은 근무표 셀에 들어가는 4자 이내 값이라
    # 더 넓혀도 담을 것이 없다 → maxWidth 로 고정한다.
    "약칭": {"width": 64, "minWidth": 64, "maxWidth": 64,
            "cellClass": "md-c-left", "cellRenderer": _SHORT_LABEL_RENDERER},
    # 시작·종료 48 = 'HH:MM' 30.03×1.05 + 16. 고정 서식 → maxWidth.
    "시작": {"width": 48, "minWidth": 48, "maxWidth": 48, "cellClass": "md-c-center ms-num"},
    "종료": {"width": 48, "minWidth": 48, "maxWidth": 48, "cellClass": "md-c-center ms-num"},
    # 색상 128 = 표시(스와치16+간격8+'#RRGGBB' 53 = 83.06)가 아니라 **편집기 하한**이 지배한다:
    # 좌패딩6 + 피커26 + 간격8 + hex input 84 + 보더2 = 126 → 128. 셀은 overflow hidden 이라
    # 이보다 좁으면 편집기가 잘린다(§17 편집 안전). 고정 서식이므로 maxWidth 로 묶는다.
    "색상": {"width": 128, "minWidth": 128, "maxWidth": 128, "cellClass": "md-c-left",
            "cellRenderer": _COLOR_RENDERER, "cellEditor": _COLOR_EDITOR},
    # 불리언 3열 = 체크박스(16px)라 헤더가 폭을 지배한다. 넓혀도 담을 것이 없어 maxWidth.
    #   실근무 52 = 헤더 '실근무' 33.13×1.05 + 16 / 특근수당·표시순서 64 = 헤더 44.17×1.05 + 16
    #   사용 40 = 헤더 '사용' 22.09×1.05 + 16
    "실근무": {"width": 52, "minWidth": 52, "maxWidth": 52, "cellClass": "md-c-center"},
    "특근수당": {"width": 64, "minWidth": 64, "maxWidth": 64, "cellClass": "md-c-center"},
    # 설명 124 = '야간 근무(4시간)' 101.8×1.05 + 16. 종전 flex:1 로 313px 였다(잉크의 3배).
    "설명": {"width": 124, "minWidth": 124, "cellClass": "md-c-left"},
    "표시순서": {"width": 64, "minWidth": 64, "maxWidth": 64, "cellClass": "md-c-center ms-num"},
    "사용": {"width": 40, "minWidth": 40, "maxWidth": 40, "cellClass": "md-c-center"},
}


def _summary_counts(frame: pd.DataFrame) -> tuple[int, int]:
    """현재 필터결과(표에 로드된 기존 행) 기준 (사용 중, 미사용) 건수.

    사용자관리와 동일하게 '지금 표에 보이는' 결과 기준 분포를 낸다(필터 무관 전체
    카운트가 아님). 신규 행은 아직 저장 전이므로 제외한다.
    """
    if frame is None or frame.empty:
        return 0, 0
    existing = frame[frame["_row_state"] == "existing"] if "_row_state" in frame else frame
    if existing.empty:
        return 0, 0
    active = int(existing["사용"].map(grid_bool).sum())
    return active, len(existing) - active


def _render_summary_chips(frame: pd.DataFrame, params: dict) -> None:
    """상단 요약 스트립 — 좌: 활성 필터 칩, 우: 현재 필터결과의 사용/미사용 분포.

    사용자관리(_render_summary_chips)와 동일한 어휘/배치. 필터가 모두 기본이면 좌측
    칩은 비운다. 결과 0건이어도 활성 필터 칩은 남겨 왜 비었는지 알린다.
    """
    if frame is None:
        return
    filt = ""
    if params.get("active") and params["active"] != "전체":
        filt += master.chip_html(f"사용 여부: {params['active']}", "lock")
    if params.get("search"):
        filt += master.chip_html(f"검색: {params['search']}", "lock")

    active, inactive = _summary_counts(frame)
    cnt = ""
    if active or inactive:
        cnt = master.chip_html(f"사용 중 {active}", "ok")
        if inactive:
            cnt += master.chip_html(f"미사용 {inactive}", "mute")

    if not filt and not cnt:
        return
    st.markdown(
        "<div style='display:flex;justify-content:space-between;align-items:center;"
        "gap:.5rem;margin:.1rem 0 .2rem'>"
        f"<div style='display:flex;gap:.3rem;flex-wrap:wrap'>{filt}</div>"
        f"<div style='display:flex;gap:.3rem;flex:0 0 auto'>{cnt}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def _col_config() -> dict:
    """컬럼별 폭 + 셀 오류/변경 하이라이트(cellClassRules) + 렌더러/에디터 주입."""
    cfg: dict = {}
    for col in _USER_COLS:
        entry = dict(_COL_WIDTHS.get(col, {"cellClass": "md-c-left"}))
        rules = {**style.cell_error_rule(col), **style.cell_dirty_rule(col)}
        if col == "코드":
            rules.update(_CODE_READONLY_RULES)  # 저장행 코드 읽기전용 어포던스(org/users 계약)
        entry["cellClassRules"] = rules
        cfg[col] = entry
    return cfg


# ---------------------------------------------------------------------------
# 헤더 아이콘 발행 — 상단 52px 헤더는 **화면 본문보다 먼저** 렌더된다. 따라서 본문 끝
# (그리드 건수 계산 뒤)에서 publish 한 음영/사유는 그 프레임의 헤더에 반영되지 못하고
# 다음 run 을 기다린다. 인페이지 버튼 바가 함께 있던 동안에는 버튼이 첫 프레임부터
# 정상이라 이 지연이 보이지 않았지만, 헤더 아이콘이 **유일한** 진입점이 된 뒤에는 그대로
# 기능 결함이 된다 — 실측(1440px, sample):
#   · 진입 직후 : 추가 아이콘 음영 유지 18s+ (사용자 조작 전까지 안 풀림)
#   · 행 선택 후 : "선택 1건" 칩은 떴는데 삭제 아이콘 음영 유지 55s+
#   · 행 추가 후 : "미저장 1건" 칩은 떴는데 저장 아이콘 음영 유지 25s+
# 본문발 상태 변화 뒤에 자동 rerun 이 보장되지 않기 때문이다.
#
# 그래서 발행값(4종의 disabled·사유)이 **직전 발행과 다를 때만** 한 번 rerun 해 헤더를
# 최신 상태로 다시 그린다. 같은 값이면 rerun 하지 않으므로 수렴한다(같은 입력 → 같은
# 서명 → 정지). 활성 규칙 계산은 여전히 page_action_specs 한 곳이며(두 벌 규칙 금지),
# 이 함수는 "언제 헤더를 다시 그리는가"만 정한다. modules/ui 는 건드리지 않는다.
#
# rerun 자체는 render 말미(액션 flag 소비 뒤)에서 실행한다 — 여기서 바로 rerun 하면
# 헤더 아이콘 클릭으로 세팅된 flag 가 소비되기 전에 프레임이 끝난다.
# ---------------------------------------------------------------------------
_HDR_SIG = "hdr_sig"  # 직전 발행 서명 — 값이 바뀐 프레임에서만 헤더를 다시 그린다


def _publish_header_actions(state: DraftState, specs: list[dict]) -> bool:
    """헤더 아이콘 음영/사유를 발행하고, 발행값이 바뀌었으면 True(=재렌더 필요)."""
    master.header_actions_from_specs(PAGE_ID, specs)
    sig = tuple((s["role"], bool(s["disabled"]), s.get("help")) for s in specs)
    key = state.key(_HDR_SIG)
    if st.session_state.get(key) == sig:
        return False
    st.session_state[key] = sig
    return True


# ===========================================================================
# 화면
# ===========================================================================
def render(user: dict) -> None:
    state = DraftState(PAGE_ID)

    # §1-E 표형(구조 교체) — 아이콘 밴드 제거(§0-3, 6단계와 동일). 실기능 액션(행 추가·삭제·
    # 저장·새로고침)의 진입점은 **상단 52px 헤더 아이콘 하나**다(2026-08-14 사용자 지시로
    # 인페이지 버튼 바 제거 — 종전에는 헤더 아이콘과 화면 안 버튼이 같은 flag 를 쏘는
    # 중복 진입점이었다). 색·약칭·시간/HEX 검증·참조 확인 후 비활성화 우선 계약은 전부 보존.
    _WT_DESC = "근무형태(코드·명칭·약칭·색상)를 표에서 직접 편집하고 [저장]으로 일괄 반영합니다."
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="근무형태 관리",
        desc=_WT_DESC,
        breadcrumb="기준정보 › 근무형태 관리",
    )
    # 페이지 CSS 는 **한 번에** 주입한다 — style 전용 markdown 도 블록 하나(≈9px)를 차지해
    # 두 번 나누면 조건 줄이 사용자·조직 화면보다 9px 내려앉는다(2026-08-14 실측: 조건 줄
    # y 183.4 vs 174.3). 내용은 종전 두 블록과 동일하다.
    st.markdown(_EXTRA_CSS + _WT_CROW_CSS, unsafe_allow_html=True)

    # ---- 조건 패널(우측 인라인 라벨, KP-standard) — 위젯 key 는 기존 DraftState 스코프
    #      키(state.key("f_active")/"f_search")를 widget_key 로 그대로 지정해 세션 상태를
    #      보존한다(구조만 이전, 조회/재적재 로직 불변). ----
    cond = erp.condition_panel(
        PAGE_ID,
        [
            erp.Field(key="active", label="사용 여부", kind="select", options=_STATUS,
                     widget_key=state.key("f_active"), width=150),
            erp.Field(key="search", label="검색", kind="text",
                     widget_key=state.key("f_search"), placeholder="코드·명칭·약칭 검색"),
        ],
        # §0.6 컨트롤 폭 내용 맞춤 — cols=2 등폭은 3지선다 select 를 580px(1440 기준)까지
        # 늘려 조건 줄이 화면 폭을 삼켰다. 짧은 코드값 select 는 내용 맞춤, 검색만 신축
        # (월간 근무표·근무표 편성과 동일 패턴).
        content_fit=True,
    )
    params = {"active": cond["active"], "search": str(cond["search"]).strip()}

    # ---- 재적재 결정(dirty 무경고 소실 금지, §17) ----
    decision = state.resolve_reload(params, refresh=False, dirty=state.is_dirty())
    if decision == RELOAD:
        _load_editor(state, params)
    # CONFIRM → banner_slot 폐기 확인 바에서 처리 / KEEP → 현재 draft 유지

    # §1-E: 필터 줄 → 헤어라인 → 건수 행 → 표 (사용자 관리와 동일 골격).
    # 별도 '근무표 색·약칭 미리보기' 스와치 줄은 제거했다(2026-08-07 사용자 요구 —
    # 같은 색·약칭이 스와치 줄·색상 열·약칭 열에 3중으로 반복돼 화면이 산만했다).
    # 색 미리보기 계약은 **셀 단위**로 유지된다: 색상 열(_COLOR_RENDERER)의 스와치+HEX,
    # 약칭 열(_SHORT_LABEL_RENDERER)의 근무형태 색 chip(근무표 배지와 동일 어휘·명도 기반
    # 텍스트색). 색 편집(피커/HEX 양방향)·검증(#RRGGBB·중복 경고) 계약은 불변이다.
    # 헤어라인은 조건 패널 자체가 하단 border 로 그린다(views/common/erp/kit.py
    # `[class*="st-key-erpcond_"]`) — 여기서 다시 그리면 22px 간격의 이중 괘선이 된다
    # (2026-08-14 실측 y264.4/287.0). 조직 관리와 같은 한 줄 구획으로 맞춘다.
    count_row_slot = st.container()  # 건수 행(근무형태 + 건수 pill + 사용/미사용 + 우측 편집 상태) — deferred
    banner_slot = st.container()  # 배너(삭제 확인/폐기 확인/원장/오류/flash 중 1개)

    # ---- 그리드 ----
    frame = _render_frame(state)
    spec = MasterGridSpec(
        page_id=PAGE_ID, columns=_GRID_COLUMNS, order=_USER_COLS,
        col_config=_col_config(), select_all=True,
        height=master_grid_height(len(frame)),
        # rowHeight 는 공용 기본값(views/master/grid.py `_GRID_ROW_PX`=40). 화면에서 42 로
        # 덮으면 조직 관리(40)와 행 높이가 어긋나고, 높이 계산(master_grid_height)이 40
        # 기준이라 행마다 2px 씩 모자라 불필요한 내부 스크롤이 생긴다(2026-08-14 재검수).
        # autoSizeStrategy: 지정 폭을 **비율**로 삼아 남는 가로 폭을 비례 분배한다.
        # 없으면 flex 를 뺀 순간 표가 뷰포트보다 훨씬 좁게 서서 "화면보다 작은 표"가 된다
        # (실측 1440: 열 폭 합 926 vs 그리드 뷰포트 1403 → 477px 여백). 공용
        # views/master/grid.py::_build_grid_options 에 두는 것이 옳지만 그 파일은 이번
        # 작업 범위 밖이라 화면별 grid_options 로 얹는다(3화면 동일 — 보고 대상).
        grid_options={"onCellValueChanged": _DUP_REFRESH,
                      "autoSizeStrategy": {"type": "fitGridWidth"}},
    )
    grid_df = render_master_grid(spec, frame, key=state.grid_key())

    # ---- 실시간 건수(§20) — dirty 단일 기준은 이 dtotal(헤더 저장 아이콘 활성 + 건수 행 칩) ----
    live = live_rows(grid_df)
    existing = live[live["_row_state"] == "existing"]
    new_rows = live[live["_row_state"] != "existing"]
    new_count = int(len(new_rows))
    changed_count = _changed_existing_count(state, existing)
    sel_count = int(existing["_sel"].map(grid_bool).sum()) if not existing.empty else 0
    dtotal = dirty_total(new_count, changed_count)
    state.set_dirty(dtotal > 0)
    st.session_state[state.key(_LAST_COUNTS)] = (new_count, changed_count, sel_count)

    # ---- §1-E 건수 행 채움(deferred) — 좌: 근무형태 + 건수 pill + 사용/미사용,
    #      우: 편집 상태(미저장·선택) 칩. **실행 컨트롤은 두지 않는다**(2026-08-14 사용자
    #      지시 — 행 추가·삭제·저장·새로고침의 진입점은 상단 52px 헤더 아이콘 하나뿐,
    #      DESIGN §0-3 "아이콘 툴바는 최상단 헤더 바 안에만"). 종전 인페이지 버튼 바가
    #      들고 있던 상태 신호(저장 badge "저장 · N", 삭제 활성 근거)는 같은 y 위치의
    #      이 칩으로 이어받는다 — 헤더 아이콘의 활성/음영 근거를 표 바로 위에서 읽는다.
    #      활성/사유/라벨 계산은 종전과 동일한 page_action_specs 한 곳이다. ----
    specs = master.page_action_specs(sel_count=sel_count, dirty_total=dtotal, can_save=True)
    active_ct, inactive_ct = _summary_counts(live)
    with count_row_slot:
        dist = (f"<span class='dist'>사용 중 {active_ct} · 미사용 {inactive_ct}</span>"
                if (active_ct or inactive_ct) else "")
        edit = ""
        if dtotal:
            edit += master.chip_html(f"미저장 {dtotal}건", "warn")
        if sel_count:
            edit += master.chip_html(f"선택 {sel_count}건", "mute")
        st.markdown(
            f"<div class='wt-crow'><span class='t'>근무형태</span>"
            f"<span class='pill'>{len(existing)}</span>{dist}"
            f"<span class='edit'>{edit}</span></div>",
            unsafe_allow_html=True,
        )

    # 상단 52px 헤더 아이콘(추가·삭제·저장·새로고침)에 활성 규칙을 발행한다 — 이제 이
    # 아이콘이 **유일한** 진입점이며, 클릭은 종전과 같은 page-scoped flag 를 쏘므로
    # 실행 경로·확인 게이트는 그대로 하나다(take_actions 소비 지점 무변경).
    # 발행값이 바뀌었으면 render 말미에서 한 번 다시 그린다(위 _publish_header_actions 주석).
    hdr_changed = _publish_header_actions(state, specs)

    # ---- 배너(표 위 슬롯, 단일 우선순위: 삭제확인 > 폐기확인 > 저장원장/오류 > flash) ----
    # §21 flash 는 "다음 rerun 1회 표시" 계약이라 렌더 시 세션에서 pop 된다. 헤더 재렌더로
    # 이 프레임이 버려지면 저장·삭제 완료 안내가 화면에 남지 않으므로(실측: 저장 성공 배너가
    # 한 프레임 만에 사라짐), 표시 예정이던 flash 를 붙잡아 두었다가 rerun 직전에 되돌린다.
    # 배너 렌더 자체는 순서를 바꾸지 않는다 — 확인 바 버튼 클릭이 유실되지 않도록 rerun 은
    # 종전대로 배너·액션 소비 뒤에 둔다.
    pending_flash = st.session_state.get(state.flash_key) if hdr_changed else None
    with banner_slot:
        _render_banners(state, params)

    # ---- 상태 스트립(§20, 표 하단) ----
    count_strip(int(len(existing)), new_count, changed_count, sel_count)

    # ---- 액션 소비(commit handshake: 최신 grid_df 수신 후에 flag 소비) ----
    actions = master.take_actions(state)
    if actions[SAVE]:
        _save(state, grid_df, params)
    if actions[DELETE]:
        _request_delete(state, grid_df)
    if actions[ADD]:
        _add_row(state, grid_df)
    if actions[REFRESH]:
        _refresh(state, params)

    # 구조 변경 반영 또는 헤더 아이콘 발행값 변경 → 한 번 다시 그린다.
    # (_normalize 는 부작용이 있으므로 short-circuit 되지 않도록 먼저 호출한다.)
    structural = _normalize(state, grid_df)
    if structural or hdr_changed:
        if pending_flash is not None:
            st.session_state[state.flash_key] = pending_flash  # 위 주석 — flash 유실 방지
        st.rerun()


# ---------------------------------------------------------------------------
# 표 위 배너 — 한 시점에 최대 1개(§17 우선순위). 슬롯 안에서 렌더한다.
# ---------------------------------------------------------------------------
def _render_banners(state: DraftState, params: dict) -> None:
    plan = st.session_state.get(state.delete_plan_key)
    if plan:
        _confirm_delete(state, plan, params)
        return
    if state.has_pending_reload():
        gate = master.discard_confirm_bar(state)
        if gate == "discard":
            new_params = state.apply_pending_reload()
            _load_editor(state, new_params if new_params is not None else params)
            st.rerun()
        elif gate == "cancel":
            state.cancel_pending_reload()
            st.rerun()
        return
    if _render_save_ledger(state):
        return
    master.show_flash(state)


# ---------------------------------------------------------------------------
# 렌더 프레임 — 세션 rows(CORE_META+user) 에 view-model 메타를 채워 그리드에 넘긴다.
# ---------------------------------------------------------------------------
def _render_frame(state: DraftState) -> pd.DataFrame:
    rows = state.get_rows()
    if rows is None:
        rows = pd.DataFrame(columns=_ROW_COLS)
    frame = rows.copy().reset_index(drop=True)
    for col in _ROW_COLS:
        if col not in frame:
            frame[col] = (col == "사용") if col in _BOOL_COLS else ""
    baseline = st.session_state.get(state.key(_BASELINE), {})
    cell_errors = st.session_state.get(state.key(_CELL_ERRORS), {})

    inactive, dirty_fields, error_meta = [], [], []
    for _, row in frame.iterrows():
        rid = str(row.get("_row_id") or "")
        is_existing = row.get("_row_state") == "existing"
        inactive.append("1" if (is_existing and not grid_bool(row.get("사용"))) else "")
        dirty_fields.append(_dirty_fields_json(row, baseline.get(rid)))
        errs = cell_errors.get(rid)
        error_meta.append(json.dumps(errs, ensure_ascii=False) if errs else "")
    frame["_inactive"] = inactive
    frame["_dirty_fields"] = dirty_fields
    frame["_error"] = error_meta
    return frame


def _dirty_fields_json(row, base) -> str:
    """기존 행이 baseline 대비 바뀐 필드명 JSON. 신규 행/미로드는 빈 문자열."""
    if row.get("_row_state") != "existing" or not base:
        return ""
    changed = [col for col in _USER_COLS if _norm_field(col, row.get(col)) != base.get(col)]
    return json.dumps(changed, ensure_ascii=False) if changed else ""


def _norm_field(col: str, value):
    if col in _BOOL_COLS:
        return bool(grid_bool(value))
    if col == "표시순서":
        return str(value if value is not None else "").strip()
    return str(value if value is not None else "").strip()


def _row_tuple(row) -> dict:
    return {col: _norm_field(col, row.get(col)) for col in _USER_COLS}


def _changed_existing_count(state: DraftState, existing: pd.DataFrame) -> int:
    baseline = st.session_state.get(state.key(_BASELINE), {})
    if existing.empty or not baseline:
        return 0
    n = 0
    for _, row in existing.iterrows():
        base = baseline.get(str(row.get("_row_id") or ""))
        if base is not None and _row_tuple(row) != base:
            n += 1
    return n


# ---------------------------------------------------------------------------
# 구조 변경(붙여넣기 신규 행 / − 제거) 권위 반영 — grid.py 대신 controller 몫.
# ---------------------------------------------------------------------------
def _normalize(state: DraftState, grid_df: pd.DataFrame) -> bool:
    if grid_df is None or grid_df.empty or "_row_id" not in grid_df.columns:
        return False
    removed = (grid_df["_removed"].fillna("").astype(str).str.strip() == "1"
               if "_removed" in grid_df else pd.Series(False, index=grid_df.index))
    live = grid_df[~removed].copy()
    rid = live["_row_id"].fillna("").astype(str).str.strip()
    needs_id = rid == ""
    if not (removed.any() or needs_id.any()):
        return False
    live["_row_id"] = rid
    for idx in live.index[needs_id]:
        live.at[idx, "_row_id"] = state.next_rid()
        live.at[idx, "_row_state"] = "new"
        live.at[idx, "_sel"] = False
    live["_row_state"] = live["_row_state"].fillna("").astype(str).replace("", "new")
    state.set_rows(live[_ROW_COLS].reset_index(drop=True))
    state.bump_nonce()
    return True


def _next_order(rows: pd.DataFrame) -> int:
    orders = pd.to_numeric(rows.get("표시순서"), errors="coerce").dropna()
    return int(orders.max()) + 1 if len(orders) else 1


def _new_row(state: DraftState, order_val: int) -> dict:
    row = {"_row_id": state.next_rid(), "_row_state": "new", "_sel": False, "_removed": ""}
    for c in _USER_COLS:
        row[c] = (c == "사용") if c in _BOOL_COLS else ""
    row["색상"] = _DEFAULT_COLOR
    row["표시순서"] = str(order_val)
    return row


def _add_row(state: DraftState, grid_df: pd.DataFrame) -> None:
    live = live_rows(grid_df)
    combined = pd.concat(
        [live[_ROW_COLS], pd.DataFrame([_new_row(state, _next_order(live))])],
        ignore_index=True,
    )[_ROW_COLS]
    state.set_rows(combined)
    state.bump_nonce()
    st.rerun()


def _refresh(state: DraftState, params: dict) -> None:
    # 캐시를 비워야 _load_editor 가 실제로 다시 읽는다(범위: 근무형태만).
    db.refresh_reference_data("work_types")
    if state.is_dirty():
        st.session_state[state.pending_query_key] = params
    else:
        _load_editor(state, params)
    st.rerun()


# ---------------------------------------------------------------------------
# 삭제 (기존 저장 행 전용) — 참조 있으면 미사용, 없으면 물리 삭제. 2단계 확인.
# ---------------------------------------------------------------------------
def _request_delete(state: DraftState, grid_df: pd.DataFrame) -> None:
    live = live_rows(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    codes = sorted({str(c).strip() for c in sel["코드"] if str(c).strip()})
    if not codes:
        state.set_flash("warning", "삭제할 기존 근무형태를 선택하세요.")
        st.rerun()
    plan = {"delete": [], "deactivate": []}
    for code in codes:
        refs = db.work_type_reference_counts(code)
        item = {"code": code, "refs": refs}
        (plan["deactivate"] if sum(refs.values()) > 0 else plan["delete"]).append(item)
    st.session_state[state.delete_plan_key] = plan
    st.rerun()


def _confirm_delete(state: DraftState, plan: dict, params: dict) -> None:
    retry_err = st.session_state.get(state.key(_DELETE_ERROR))
    lines = []
    if retry_err:
        lines.append("이전 시도 실패(재시도 가능): " + retry_err)
    if plan["delete"]:
        lines.append("완전 삭제: " + ", ".join(it["code"] for it in plan["delete"]))
    for it in plan["deactivate"]:
        lines.append(f"미사용 처리: {it['code']} — 근무표 {it['refs'].get('schedules', 0)}건 사용 중")
    result = confirm_bar(
        state,
        title="선택한 근무형태를 다음과 같이 처리합니다.",
        lines=lines, confirm_label="재시도" if retry_err else "실행", scope="del",
    )
    if result == "confirm":
        st.session_state.pop(state.key(_DELETE_ERROR), None)
        _execute_delete(state, plan, params)
    elif result == "cancel":
        st.session_state.pop(state.delete_plan_key, None)
        st.session_state.pop(state.key(_DELETE_ERROR), None)
        st.rerun()


def _execute_delete(state: DraftState, plan: dict, params: dict) -> None:
    """삭제/비활성 write 를 대상별로 실행하고 실패를 controller 경계에서 흡수한다(B4).

    - 물리 삭제(참조 0)와 미사용 처리(참조>0)를 각각 실행하고 성공/실패를 판정한다.
    - 성공분만 재조회(_load_editor)하고, 실패분은 재시도 가능한 삭제 계획으로 남긴다.
    - ``DATA_SOURCE_ERRORS``(supabase 통신/제약) 는 사용자용 배너 문구로 변환한다.
    2단계 확인·참조 시 비활성/미참조 시 물리삭제 계약은 유지한다.
    """
    done_del, done_deact, failed = [], [], []

    # 참조 없는 코드 — 물리 삭제(대상별로 실패 격리).
    for it in plan["delete"]:
        try:
            db.delete_work_type(it["code"])
            done_del.append(it["code"])
        except db.DATA_SOURCE_ERRORS as exc:
            failed.append({"item": it, "bucket": "delete", "reason": _err_text(exc)})

    # 참조 있는 코드 — is_active=False 소프트삭제. 원장 API 로 부분성공을 판정한다.
    deact = list(plan["deactivate"])
    if deact:
        codes = [it["code"] for it in deact]
        try:
            store = db.get_work_types().copy()
            mask = store["code"].astype(str).isin(codes)
            store.loc[mask, "is_active"] = False
            report = db.save_work_types_report(store[db.WORK_TYPE_COLUMNS])
        except db.DATA_SOURCE_ERRORS as exc:
            for it in deact:
                failed.append({"item": it, "bucket": "deactivate", "reason": _err_text(exc)})
        else:
            saved = {_key_str(k) for k in report.saved_keys}
            failed_k = {_key_str(k) for k in report.failed_keys}
            for it in deact:
                c = it["code"]
                if report.ok or c in saved:
                    done_deact.append(c)
                elif report.unknown:
                    failed.append({"item": it, "bucket": "deactivate",
                                   "reason": report.error or "결과 불명 · 재조회 필요"})
                elif c in failed_k:
                    failed.append({"item": it, "bucket": "deactivate",
                                   "reason": report.error or "저장 실패"})
                else:  # 보고에 없으면 보수적으로 실패로 남겨 재시도 대상에 둔다.
                    failed.append({"item": it, "bucket": "deactivate",
                                   "reason": report.error or "결과를 확인할 수 없습니다."})

    st.session_state.pop(state.delete_plan_key, None)

    if done_del or done_deact:
        _load_editor(state, params)  # 성공분만 반영(재조회)

    parts = []
    if done_del:
        parts.append(f"{len(done_del)}개 삭제")
    if done_deact:
        parts.append(f"{len(done_deact)}개 미사용 처리")

    if failed:
        # 실패분은 재시도 가능한 계획으로 남기고, 사유를 재시도 확인 바에 노출한다.
        st.session_state[state.delete_plan_key] = {
            "delete": [f["item"] for f in failed if f["bucket"] == "delete"],
            "deactivate": [f["item"] for f in failed if f["bucket"] == "deactivate"],
        }
        done_txt = ("처리 완료 " + ", ".join(parts) + "; ") if parts else ""
        reasons = " / ".join(f"{f['item']['code']}: {f['reason']}" for f in failed)
        st.session_state[state.key(_DELETE_ERROR)] = f"{done_txt}실패 {len(failed)}건 — {reasons}"
        st.rerun()

    msg = "근무형태를 " + ", ".join(parts) + "했습니다." if parts else "처리할 근무형태가 없습니다."
    state.set_flash("success" if parts else "warning", msg)
    st.rerun()


def _err_text(exc: Exception) -> str:
    text = str(exc).strip()
    return text or "데이터 저장 중 오류가 발생했습니다."


def _key_str(key) -> str:
    if isinstance(key, (tuple, list)):
        return "/".join(str(k) for k in key)
    return str(key)


# ---------------------------------------------------------------------------
# 적재 / 저장
# ---------------------------------------------------------------------------
def _load_editor(state: DraftState, q: dict) -> None:
    df = db.get_work_types().copy()
    if q["active"] == "사용 중":
        df = df[df["is_active"].astype(bool)]
    elif q["active"] == "사용 안 함":
        df = df[~df["is_active"].astype(bool)]
    term = str(q.get("search", "")).strip()
    if term:
        hit = (
            df["code"].astype(str).str.contains(term, case=False, na=False, regex=False)
            | df["name"].astype(str).str.contains(term, case=False, na=False, regex=False)
            | df["short_label"].astype(str).str.contains(term, case=False, na=False, regex=False)
        )
        df = df[hit]
    df = df.sort_values("sort_order").reset_index(drop=True)
    order = pd.to_numeric(df["sort_order"], errors="coerce").fillna(0).astype("int64")

    if df.empty:
        rows = pd.DataFrame(columns=_ROW_COLS)
    else:
        rows = pd.DataFrame({
            "_row_id": "e:" + df["code"].astype(str),
            "_row_state": "existing", "_sel": False, "_removed": "",
            "코드": df["code"].fillna("").astype("string"),
            "명칭": df["name"].fillna("").astype("string"),
            "분류": df["category"].fillna("").astype("string"),
            "약칭": df["short_label"].fillna("").astype("string"),
            "시작": df["start_time"].fillna("").astype("string"),
            "종료": df["end_time"].fillna("").astype("string"),
            "색상": df["color"].fillna("").astype("string"),
            "실근무": df["is_work"].fillna(False).astype(bool),
            "특근수당": df["affects_allowance"].fillna(False).astype(bool),
            "설명": df["description"].fillna("").astype("string"),
            "표시순서": order.astype(str).astype("string"),
            "사용": df["is_active"].fillna(True).astype(bool),
        })[_ROW_COLS]

    state.set_rows(rows)
    st.session_state[state.key(_BASELINE)] = {
        str(r["_row_id"]): _row_tuple(r) for _, r in rows.iterrows()
    }
    st.session_state.pop(state.key(_CELL_ERRORS), None)
    st.session_state.pop(state.key(_SAVE_ERRORS), None)
    st.session_state.pop(state.key(_SAVE_LEDGER), None)
    st.session_state.pop(state.key(_DELETE_ERROR), None)
    state.set_dirty(False)
    state.bump_nonce()


def _save(state: DraftState, grid_df: pd.DataFrame, q: dict) -> None:
    live = live_rows(grid_df)
    st.session_state.pop(state.key(_SAVE_ERRORS), None)
    st.session_state.pop(state.key(_SAVE_LEDGER), None)
    counts: dict = {}

    def validate():
        records, errors, emap = _validate_detailed(live)
        st.session_state[state.key(_CELL_ERRORS)] = emap
        return records, errors

    def build_candidate(records):
        store = db.get_work_types()
        merged, dup, n_c, n_u, _n_d = db.upsert_records(
            store, records, set(), ["code"], "is_active", db.WORK_TYPE_COLUMNS,
        )
        errs = []
        if dup:
            errs.append("근무형태 코드가 중복되었습니다: " + ", ".join(k[0] for k in dup))
        counts["c"], counts["u"], counts["records"] = n_c, n_u, records
        return merged, errs

    def persist(merged, records):
        # B2: void save_work_types 대신 원장 반환 API 를 호출해 batch 부분성공을
        # controller 까지 전달한다(PersistResult 로 그대로 매핑).
        report = db.save_work_types_report(merged)
        return PersistResult(page_id=state.page_id, **report.to_persist_kwargs())

    outcome = run_save(state, validate=validate, build_candidate=build_candidate, persist=persist)

    if outcome.status == "saved":
        _load_editor(state, q)
        state.set_flash(*_success_flash(counts))
        st.rerun()

    if outcome.status in ("partial", "unknown") and outcome.result is not None:
        # §22: 성공 자연키만 baseline 에 reconcile(더 이상 dirty 아님), 실패 key 의
        # draft·cell error·재시도 affordance 는 보존. 재적재/리마운트하지 않는다.
        _reconcile_partial(state, outcome.result, live)
        st.session_state[state.key(_SAVE_LEDGER)] = outcome.result
        st.rerun()

    # invalid / failed — draft 를 재적재/리마운트 없이 보존하고 표 위 오류 배너만 갱신.
    st.session_state[state.key(_SAVE_ERRORS)] = {"errors": list(outcome.errors) or _result_errors(outcome)}
    st.rerun()


def _reconcile_partial(state: DraftState, result, live: pd.DataFrame) -> None:
    """부분성공/결과불명: 성공 key 는 baseline 갱신(clean), 실패 key 는 셀 오류 표기."""
    by_code: dict = {}
    for _, row in live.iterrows():
        by_code.setdefault(str(row.get("코드") or "").strip(), []).append(row)
    baseline = dict(st.session_state.get(state.key(_BASELINE), {}))
    cell_errors = dict(st.session_state.get(state.key(_CELL_ERRORS), {}))
    for key in result.succeeded_keys:
        for row in by_code.get(_key_str(key), []):
            rid = str(row.get("_row_id") or "")
            if row.get("_row_state") == "existing":
                baseline[rid] = _row_tuple(row)  # 저장됨 → 더 이상 변경 아님
            cell_errors.pop(rid, None)
    for key in result.failed_keys:
        for row in by_code.get(_key_str(key), []):
            rid = str(row.get("_row_id") or "")
            cell_errors.setdefault(rid, {})["코드"] = result.error or "저장 실패"
    st.session_state[state.key(_BASELINE)] = baseline
    st.session_state[state.key(_CELL_ERRORS)] = cell_errors


def _success_flash(counts: dict):
    n_c, n_u = counts.get("c", 0), counts.get("u", 0)
    msg = f"근무형태를 저장했습니다. (신규 {n_c} · 수정 {n_u})"
    dup = _duplicate_short_labels(counts.get("records", []))
    if dup:
        return "warning", (msg + f" 다만 약칭 {', '.join(dup)} 이(가) 여러 코드에 걸려 "
                           "근무표에서 코드로 표시됩니다.")
    return "success", msg


def _result_errors(outcome) -> list:
    if outcome.result is not None and outcome.result.error:
        return [outcome.result.error]
    return ["저장하지 못했습니다."]


def _duplicate_short_labels(records) -> list:
    seen, dup = {}, set()
    for rec in records:
        if not rec.get("is_active"):
            continue
        label = str(rec.get("short_label") or "").strip()
        if not label:
            continue
        if label in seen:
            dup.add(label)
        seen[label] = True
    return sorted(dup)


def _render_save_ledger(state: DraftState) -> bool:
    """§22 저장 결과 원장(부분성공/결과불명) 또는 검증 실패 배너. 렌더 시 True."""
    ledger = st.session_state.get(state.key(_SAVE_LEDGER))
    if ledger is not None:
        ledger_banner(ledger)  # 성공/실패 키 칩 · 결과 불명 분리(재조회 필요)
        return True
    payload = st.session_state.get(state.key(_SAVE_ERRORS))
    if payload:
        errors = payload.get("errors", [])
        new_c, changed_c, _sel = st.session_state.get(state.key(_LAST_COUNTS), (0, 0, 0))
        items = "".join(f"<li>{style.escape(e)}</li>" for e in errors)
        absorb = ""
        if new_c or changed_c:
            absorb = (f"<div class='ms-absorb'>· 미저장 {new_c + changed_c}건"
                      f"(신규 {new_c} · 기존 변경 {changed_c})은 그대로 유지됩니다.</div>")
        style.banner(
            "danger", f"{len(errors)}개 항목에 오류가 있어 저장하지 못했습니다.",
            extra=f"<ul class='ms-errlist'>{items}</ul>{absorb}",
        )
        return True
    return False


# ---------------------------------------------------------------------------
# 저장 전 검증 — (records, errors) 는 기존 계약 유지. detailed 는 셀 오류 맵 추가.
# ---------------------------------------------------------------------------
def _validate(live: pd.DataFrame):
    """표시형 편집 프레임을 저장형 records 로 변환하고 행 오류를 수집한다.

    반환 ``(records, errors)`` — 기존 계약(scripts/test_master_and_views 등)과 동일.
    """
    records, errors, _emap = _validate_detailed(live)
    return records, errors


def _validate_detailed(live: pd.DataFrame):
    records, errors, emap = [], [], {}
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        rid = str(row.get("_row_id") or "")
        code = str(row.get("코드") or "").strip()
        name = str(row.get("명칭") or "").strip()
        category = str(row.get("분류") or "").strip()
        short_label = str(row.get("약칭") or "").strip()
        if not any([code, name, category, short_label]):
            continue  # 완전 빈 행은 저장 대상에서 제외

        tag = f"{i}행" + (f"({code})" if code else "")
        row_errs: dict = {}
        if not code:
            errors.append(f"{i}행: 근무형태 코드를 입력하세요.")
            row_errs["코드"] = "코드를 입력하세요."
        if not name:
            errors.append(f"{tag}: 근무형태명을 입력하세요.")
            row_errs["명칭"] = "명칭을 입력하세요."
        if not short_label:
            errors.append(f"{tag}: 약칭을 입력하세요.")
            row_errs["약칭"] = "약칭을 입력하세요."
        if not category:
            errors.append(f"{tag}: 분류를 입력하세요.")
            row_errs["분류"] = "분류를 입력하세요."

        # 표시순서 — 숫자.
        try:
            order_val = int(row.get("표시순서")) if str(row.get("표시순서")).strip() != "" else 0
        except (TypeError, ValueError):
            order_val = 0
            errors.append(f"{tag}: 표시순서는 숫자여야 합니다.")
            row_errs["표시순서"] = "숫자만 입력하세요."

        # 색상 — 빈 값은 기본색, 비어있지 않으면 #RRGGBB 검증(3자리/누락 # 보정).
        color_raw = str(row.get("색상") or "").strip()
        if color_raw == "":
            color = _DEFAULT_COLOR
        else:
            norm = _normalize_hex(color_raw)
            if norm is None:
                errors.append(f"{tag}: 색상 형식 오류 — #RRGGBB 6자리로 입력하세요 (예: #2E9E5B)")
                row_errs["색상"] = "올바른 #RRGGBB 형식이 아닙니다."
                color = color_raw
            else:
                color = norm

        # 시간 — 빈 값 허용, 있으면 HH:MM.
        start_time = _check_time(str(row.get("시작") or "").strip(), tag, "시작", errors, row_errs)
        end_time = _check_time(str(row.get("종료") or "").strip(), tag, "종료", errors, row_errs)

        if row_errs and rid:
            emap[rid] = row_errs

        records.append({
            "code": code, "name": name, "category": category, "short_label": short_label,
            "start_time": start_time, "end_time": end_time, "color": color,
            "is_work": grid_bool(row.get("실근무")),
            "affects_allowance": grid_bool(row.get("특근수당")),
            "description": str(row.get("설명") or "").strip(),
            "sort_order": order_val,
            "is_active": grid_bool(row.get("사용")),
        })
    return records, errors, emap


def _check_time(value: str, tag: str, label: str, errors: list, row_errs: dict) -> str:
    if value and not _TIME_RE.match(value):
        errors.append(f"{tag}: {label} 시간 형식 오류 — HH:MM 으로 입력하세요 (예: 08:00)")
        row_errs[label] = "HH:MM 형식으로 입력하세요."
    return value


def _normalize_hex(value: str):
    """``#RRGGBB`` 대문자로 정규화. 3자리 확장·누락 # 보정. 실패 시 None."""
    s = str(value or "").strip()
    if not s:
        return ""
    body = s[1:] if s.startswith("#") else s
    if _HEX3_RE.match(body):
        body = "".join(ch * 2 for ch in body)
    if _HEX_BODY_RE.match(body):
        return "#" + body.upper()
    return None


# ---------------------------------------------------------------------------
# 보조 스타일 — 저장 오류 목록/흡수 안내. (구 '근무표 색·약칭 미리보기' 스와치 줄과
# 그 CSS(.ms-preview/.ms-sw*)는 2026-08-07 제거 — 색 미리보기는 색상 열 스와치 +
# 약칭 열 색 chip 의 셀 단위로만 유지한다.)
# ---------------------------------------------------------------------------
_EXTRA_CSS = """
<style>
.ms-errlist { margin:.25rem 0 0; padding-left:1.1rem; font-size:.76rem; color:var(--ms-ink-2); }
.ms-absorb { color:var(--ms-ink-2); font-size:.72rem; margin-top:.3rem; }
</style>
"""
