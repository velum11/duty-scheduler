"""아차사고(near-miss) 분석 — DESIGN.md §1-F 분석형(지표 6 + 분포 4블록).

DESIGN.md §1-F: 지표 6개(좌측 2px 보더 + 26px 모노 숫자, 제목 바로 아래 1행) →
분포 4블록(등급별·상태별·발생원인별·월별 추이). 각 블록 = 제목 + `76px 라벨 / 8px 바 /
52px 수치` 그리드, 카테고리 단색(등급 오렌지·상태 초록·원인 황토·추이 파랑). 저장/평가
액션은 이 화면의 책임이 아니다 — 순수 집계 조회다.

파사드 계약: ``modules/db.py`` 의 ``near_miss_stats(by=..., filters=...)`` 만 호출하고
repository(``_aggregate_near_miss`` 등)를 직접 부르지 않는다. by 축(grade/status/period/
cause)마다 각각 호출한다 — 화면이 자체 집계 로직을 재구현하지 않는다. 표시 계층만 §1-F 로
재구성했고 집계 원본·계산 로직·조회 스코프(전 사용자·회사 전체)는 불변이다.
"""
from __future__ import annotations

# DESIGN.md §0 화면 유형 규약 — 대시보드형(§1-F 분석형은 DASHBOARD 아키타입의 분석 변형).
SCREEN_ARCHETYPE = "DASHBOARD"

from html import escape

import streamlit as st

from modules import db, ui
from views.common import erp
from views.common import scaffold
from views.master.lifecycle import Readiness, ReadinessState

_PAGE_ID = "near_miss_stats"

_STATUS_LABEL = {
    "SUBMITTED": "제출", "IN_REVIEW": "검토중", "EVALUATED": "평가완료",
    "CLOSED": "종결", "REJECTED": "반려",
}
_CAUSE_LABEL = {
    "JAM": "협착", "FALL": "추락", "DROP": "낙하", "HIT": "충돌",
    "SLIP": "미끄러짐", "BURN": "화상", "PINCH": "끼임", "ETC": "기타",
}

# ── §2 팔레트 리터럴(§1-F 분석 계층은 정확 색 규정 — 도메인 legacy 토큰 대신 §2 직접 사용) ──
_INK = "#1c1a17"          # 본문 텍스트
_INK2 = "#4a453d"         # 보조 텍스트(라벨)
_LINE = "#e6e2da"         # 행 헤어라인 / 바 트랙
_LINE_STRONG = "#cfc8bd"  # 블록 상단 구분선
_LINE_SEC = "#e0dbd2"     # 지표 좌측 보더(기본)
_ACCENT = "#c2410c"       # 액센트 보더(강조 지표)
_ACCENT_TEXT = "#b4451a"  # 액센트 값 텍스트
# Codex P1: 작은 의미 텍스트(축 라벨·캡션·오버라인)는 #a09a90 금지 — #6b665d(5.1:1) 이상.
_MUT = "#6b665d"          # 지표 라벨·단위·note·차트 meta·비중 캡션
# 모노 폰트는 인라인으로 못박는다 — 전역 `.stApp [data-testid=stMarkdownContainer] *`(특이도
# 0,2,0)가 클래스 규칙(0,1,0)을 덮어 숫자가 sans 로 떨어지므로, 인라인(최상위)으로 강제한다.
_MONO = "font-family:'IBM Plex Mono',monospace;"
# 분포 카테고리 단색(§1-F): 등급 오렌지·상태 초록·원인 황토·추이 파랑.
_C_GRADE = "#c2410c"
_C_STATUS = "#2f6b45"
_C_CAUSE = "#8a6212"
_C_TREND = "#2f4d99"


def render(user: dict) -> None:
    # §1-F: 헤더 중립 프레임만(아이콘 밴드 제거 — §0-3 본문 아이콘 띠 금지). badges 는
    # screen_frame 기본(scaffold.mode_badge — 헤더 우측 연결 pill, DESIGN §4). 조회조건이
    # 없는 회사 전체 집계라 인페이지 필터 줄·새로고침 위젯을 두지 않는다(모든 상호작용이
    # rerun → 집계 재호출).
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="아차사고 분석",
        desc="아차사고 등급·상태·발생원인·월별 추이를 분석합니다.",
        breadcrumb="아차사고 › 아차사고 분석",
    )
    _inject_style()

    # 접근 범위(제품 결정): 아차사고 분석은 전 사용자에게 열려 있고 회사 전체 범위다
    # (filters 비움 — 스코프 불변).
    _readiness().banner()
    filters: dict = {}

    try:
        status_counts = db.near_miss_stats(by="status", filters=filters)
        grade_counts = db.near_miss_stats(by="grade", filters=filters)
        period_counts = db.near_miss_stats(by="period", filters=filters)
        cause_counts = db.near_miss_stats(by="cause", filters=filters)
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"아차사고 집계 데이터를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("아차사고 집계 데이터를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    total = sum(status_counts.values())
    if total == 0:
        ui.empty_state("집계할 아차사고 보고서가 없습니다.", head="아차사고 집계")
        return

    # ① 지표 6개(제목 바로 아래 첫 블록 — §8 수용기준 4). CAPA 기한초과는 역할 기반 접근이라
    #    파사드가 평가자/ADMIN 만 집계를 돌려주고 일반 USER 에게는 None('—')을 준다(leak 방지).
    overdue = db.near_miss_overdue_count(current_user=user)
    _kpi_cards(status_counts, total, overdue)

    # ② 분포 4블록(등급·상태·원인·월별 추이) — 카테고리 단색 76/1fr/52 그리드.
    _render_charts(grade_counts, status_counts, cause_counts, period_counts, total)


# ---------- readiness (migration 006 3-state) ----------
def _readiness() -> ReadinessState:
    if db.is_sample_mode():
        return ReadinessState.ready()
    probe = db.near_miss_schema_probe()
    if probe == Readiness.PROBE_ERROR.value:
        return ReadinessState.probe_error(
            "아차사고 스키마 상태 확인에 실패했습니다 — 재확인이 필요합니다."
        )
    if probe == Readiness.NOT_READY.value:
        return ReadinessState.not_ready(
            "아차사고 스키마가 아직 적용되지 않아 집계할 데이터가 없습니다."
        )
    return ReadinessState.ready()


# ---------- 지표 6개(§1-F 좌측 보더 스트립) ----------
def _kpi_cards(status_counts: dict, total: int, overdue: int | None) -> None:
    """지표 6개를 제목 바로 아래 1행 스트립으로 렌더한다(§1-F: 좌측 2px 보더 + 26px 모노).

    좌상단 우선: 규모·백로그·긴급(총 건수·평가 대기·검토중)을 앞에, 완료·파생 지표(평가완료·
    기한초과·보고서 종결률)를 뒤에 둔다. dc §1-F 6지표와 동일 구성이며 기존 status_counts
    파생만 사용한다(집계 재계산 없음). '평가 대기'는 제출됨(검토 착수 전) 백로그, '검토중'은
    IN_REVIEW 로 분리 표기한다(dc 정본). 강조(오렌지 보더)는 지금 조치가 필요한 값>0 항목만."""
    submitted = status_counts.get("SUBMITTED", 0)
    in_review = status_counts.get("IN_REVIEW", 0)
    evaluated = status_counts.get("EVALUATED", 0)
    closed = status_counts.get("CLOSED", 0)
    # (label, value, unit, note, accent)
    kpis = [
        ("총 건수", str(total), "건", "ALL", False),
        ("평가 대기", str(submitted), "건", "PENDING", submitted > 0),
        ("검토중", str(in_review), "건", "IN REVIEW", False),
        ("평가완료", str(evaluated), "건", "DONE", False),
        ("기한초과", _overdue_label(overdue), "", "OVERDUE", bool(overdue)),
        ("보고서 종결률", _closure_rate_label(closed, evaluated), "", "CLOSED", False),
    ]
    cells = []
    for label, value, unit, note, accent in kpis:
        border = _ACCENT if accent else _LINE_SEC
        vcolor = _ACCENT_TEXT if accent else _INK
        unit_html = f"<span class='nmf-kunit'>{escape(unit)}</span>" if unit else ""
        cells.append(
            f"<div class='nmf-kpi' style='border-left:2px solid {border};'>"
            f"<span class='nmf-klabel'>{escape(label)}</span>"
            f"<div class='nmf-kval-row'>"
            f"<span class='nmf-kval' style='color:{vcolor};{_MONO}'>{escape(value)}</span>{unit_html}"
            f"</div>"
            f"<span class='nmf-knote' style='{_MONO}'>{escape(note)}</span>"
            f"</div>"
        )
    st.markdown(f"<div class='nmf-kpis'>{''.join(cells)}</div>", unsafe_allow_html=True)


def _overdue_label(overdue: int | None) -> str:
    """기한초과 지표 표시값. 007 미준비·비권한자·조회미상(None)이면 '—'(가짜 0 금지).

    집계·권한 판정은 파사드 ``db.near_miss_overdue_count(current_user=)`` 가 소유한다 —
    CAPA 는 역할 기반 접근이라 일반 USER 에게는 이 지표가 None('—')으로 게이트된다."""
    return "—" if overdue is None else f"{overdue}건"


def _closure_rate_label(closed: int, evaluated: int) -> str:
    """보고서 종결률 = CLOSED / (CLOSED + EVALUATED). 평가 이후 파이프라인에서 종결까지
    도달한 보고서의 비율이다.

    ※ 명칭은 정확히 '보고서 종결률' — 'CAPA 종결률'이 아니다. 007 개선조치 하드게이트
    (담당자/확인자 승인)가 적용·검증되기 전에는 status=CLOSED 가 CAPA 완료를 보증하지
    않으므로, 미확인 종결을 CAPA 완료로 오표기하지 않는다(Codex 확정).

    분모(CLOSED+EVALUATED)가 0이면 산정 불가 — '—'로 방어한다(0% 오표기 금지)."""
    denom = closed + evaluated
    if denom == 0:
        return "—"
    return f"{round(closed / denom * 100)}%"


# ---------- 분포 4블록(§1-F 76/1fr/52 그리드) ----------
def _render_charts(grade_counts: dict, status_counts: dict, cause_counts: dict,
                   period_counts: dict, total: int) -> None:
    """분포 4블록을 flex-wrap 그리드(각 블록 flex:1 1 340px)로 렌더한다.

    카테고리 단색 막대(등급 오렌지·상태 초록·원인 황토·추이 파랑). 라벨은 평문 우측정렬,
    막대 8px, 수치는 건수+비중(전체 대비). 실집계만 표시하며 빈 분포는 방어 문구로 대체한다.
    부서·분기 축은 §1-F 4블록 규격에서 제외했다(집계 파사드·계산 로직은 불변)."""
    grade_rows = [
        (grade, grade_counts.get(grade, 0))
        for grade in list(db.NEAR_MISS_GRADES) + ["미확정"]
    ]
    status_rows = [
        (_STATUS_LABEL.get(code, code), status_counts.get(code, 0))
        for code in db.NEAR_MISS_STATUSES
    ]
    cause_rows = [
        (_CAUSE_LABEL.get(code, code), count)
        for code, count in sorted(cause_counts.items(), key=lambda kv: -kv[1])
    ]
    trend_rows = sorted(
        ((k if k else "(미상)", v) for k, v in period_counts.items()),
        key=lambda kv: (kv[0] == "(미상)", kv[0]),
    )

    blocks = "".join([
        _chart_block("등급별 분포", "제안·확정 미평가는 미확정", grade_rows, total, _C_GRADE),
        _chart_block("상태별 분포", None, status_rows, total, _C_STATUS),
        _chart_block("발생원인별 분포", None, cause_rows, total, _C_CAUSE),
        _chart_block("월별 발생 추이", None, trend_rows, total, _C_TREND),
    ])
    st.markdown(f"<div class='nmf-charts'>{blocks}</div>", unsafe_allow_html=True)


def _chart_block(title: str, note: str | None, rows: list[tuple[str, int]],
                 total: int, color: str) -> str:
    meta = escape(note) if note else f"총 {total}건"
    body = []
    for label, count in rows:
        share = round(count / total * 100) if total else 0  # 전체 대비(0분모 방어)
        body.append(
            "<div class='nmf-row'>"
            f"<span class='nmf-rlabel'>{escape(str(label))}</span>"
            "<div class='nmf-track'>"
            f"<div class='nmf-fill' style='width:{share}%;background:{color};'></div>"
            "</div>"
            "<div class='nmf-rval'>"
            f"<span class='nmf-rcount' style='{_MONO}'>{count}</span>"
            f"<span class='nmf-rpct' style='{_MONO}'>{share}%</span>"
            "</div></div>"
        )
    if not body:
        body.append("<div class='nmf-empty'>표시할 분포가 없습니다</div>")
    return (
        "<section class='nmf-block'>"
        "<div class='nmf-bhead'>"
        f"<span class='nmf-btitle'>{escape(title)}</span>"
        f"<span class='nmf-bmeta' style='{_MONO}'>{meta}</span>"
        "</div>"
        f"<div class='nmf-rows'>{''.join(body)}</div>"
        "</section>"
    )


def _inject_style() -> None:
    st.markdown(
        f"""
<style>
/* §1-F 분석형 — 지표 스트립(좌측 보더) + 분포 4블록(카드 없음, 상단 헤어라인 구획). */
.nmf-kpis {{ display:flex; flex-wrap:wrap; gap:12px; margin:.1rem 0 1.1rem; }}
.nmf-kpi {{ flex:1 1 130px; min-width:0; display:flex; flex-direction:column; gap:5px;
  padding:2px 18px; }}
.nmf-klabel {{ font-size:12px; color:{_MUT}; }}
.nmf-kval-row {{ display:flex; align-items:baseline; gap:4px; }}
.nmf-kval {{ font-family:'IBM Plex Mono',monospace; font-size:26px; font-weight:600;
  letter-spacing:-0.03em; font-variant-numeric:tabular-nums; }}
.nmf-kunit {{ font-size:11.5px; color:{_MUT}; }}
.nmf-knote {{ font-size:11px; color:{_MUT}; font-family:'IBM Plex Mono',monospace;
  letter-spacing:.08em; }}

.nmf-charts {{ display:flex; flex-wrap:wrap; gap:16px 28px; }}
.nmf-block {{ flex:1 1 340px; min-width:0; padding:16px 0 8px;
  border-top:1px solid {_LINE_STRONG}; display:flex; flex-direction:column; gap:12px; }}
.nmf-bhead {{ display:flex; align-items:baseline; justify-content:space-between; gap:12px; }}
.nmf-btitle {{ font-size:13.5px; font-weight:600; color:{_INK}; }}
.nmf-bmeta {{ font-family:'IBM Plex Mono',monospace; font-size:10.5px; letter-spacing:.08em;
  color:{_MUT}; white-space:nowrap; }}
.nmf-rows {{ display:flex; flex-direction:column; gap:10px; }}
.nmf-row {{ display:grid; grid-template-columns:76px minmax(0,1fr) 52px; gap:10px;
  align-items:center; }}
.nmf-rlabel {{ font-size:12.5px; color:{_INK2}; text-align:right; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }}
.nmf-track {{ height:8px; border-radius:999px; background:{_LINE}; overflow:hidden; }}
.nmf-fill {{ height:100%; border-radius:999px; }}
.nmf-rval {{ display:flex; align-items:baseline; gap:5px; justify-content:flex-end; }}
.nmf-rcount {{ font-family:'IBM Plex Mono',monospace; font-size:12px; font-weight:600;
  color:{_INK}; font-variant-numeric:tabular-nums; }}
.nmf-rpct {{ font-family:'IBM Plex Mono',monospace; font-size:10.5px; color:{_MUT};
  font-variant-numeric:tabular-nums; }}
.nmf-empty {{ font-size:12.5px; color:{_MUT}; padding:4px 0; }}
/* 모노 강제 — 전역 `.stApp [data-testid=stMarkdownContainer] *`(특이도 0,2,0)를 이기려면
   0,3,0 이상이어야 한다(숫자·오버라인이 sans 로 떨어지는 것 방지). 인라인과 병행 못박음. */
.stApp [data-testid="stMarkdownContainer"] .nmf-kval,
.stApp [data-testid="stMarkdownContainer"] .nmf-knote,
.stApp [data-testid="stMarkdownContainer"] .nmf-bmeta,
.stApp [data-testid="stMarkdownContainer"] .nmf-rcount,
.stApp [data-testid="stMarkdownContainer"] .nmf-rpct {{
  font-family:'IBM Plex Mono','Consolas','Menlo',monospace;
}}
@media (max-width:768px) {{
  .nmf-row {{ grid-template-columns:64px minmax(0,1fr) 48px; }}
}}
</style>
""",
        unsafe_allow_html=True,
    )
