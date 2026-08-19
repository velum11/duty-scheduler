"""아차사고 보고서 A4 세로 PDF 생성 (fpdf2).

순수 생성 함수 ``build_report_pdf(data) -> bytes`` 는 도메인·DB 를 모른다(단위 테스트 대상).
호출부(near_miss_view)가 report dict + 표시맵으로 ``report_to_pdf_data`` 를 만들어 넘긴다.
상태 라벨·등급 어휘·상태의 결과 표기(§3.3)는 화면과 같은 값을 호출부에서 받는다 — 이
모듈이 코드값에서 한글 표기를 파생하지 않는다(§3.6 어휘 단일화).
DB(modules/db.py·supabase_repository.py)는 건드리지 않는다(writeScope 분리 — 사진 데이터는
별도 워커). 한글은 동봉 폰트(fonts/NotoSansKR-Regular.ttf, SIL OFL) 우선, 없으면 시스템
한글 폰트(맑은고딕/Noto/Nanum) 폴백. 사진 이미지 임베드는 사진 기능 완성 후 후속(현재는
photo_paths 파일명 나열만).
"""
from __future__ import annotations

import os

from fpdf import FPDF

# §2 팔레트(RGB) — 명세 타이포 색.
_INK = (28, 26, 23)        # #1c1a17
_INK2 = (74, 69, 61)       # #4a453d
_MUT = (107, 102, 93)      # #6b665d (오버라인·캡션)
_ACCENT = (194, 65, 12)    # #c2410c (좌측 보더·강조)
_LINE = (207, 200, 189)    # #cfc8bd (헤어라인)
_WARN = (156, 50, 50)      # #9c3232 (반려)

# 상태 라벨(한글)→색. **키는 호출부가 넘기는 표시 라벨 그대로**여야 한다 — 종전 '제출'은
# 화면(_STATUS_LABEL)의 '제출됨'과 달라 매칭에 실패해 색이 기본값(_INK2)으로 떨어졌다.
# 2026-08-18 §3.6 어휘 통일: 제출됨 · 평가중(구 '검토중') · 평가완료 · 종결 · 반려.
_STATUS_RGB = {
    "제출됨": (138, 98, 18), "평가중": (47, 77, 153), "평가완료": (47, 107, 69),
    "종결": (92, 86, 77), "반려": (156, 50, 50),
}

_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
_BUNDLED = os.path.join(_FONT_DIR, "NotoSansKR-Regular.ttf")
# 시스템 폴백 후보(윈도우·리눅스). 동봉 폰트가 있으면 그걸 우선한다(배포 이식성).
_SYSTEM_CANDIDATES = [
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/NotoSansCJKkr-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]


def _resolve_font() -> str | None:
    if os.path.exists(_BUNDLED):
        return _BUNDLED
    for path in _SYSTEM_CANDIDATES:
        if os.path.exists(path):
            return path
    return None  # 한글 폰트 없음 — 코어 라틴 폰트로 폴백(한글은 깨질 수 있음, 방어적으로만).


_MARGIN = 18.0   # mm (A4 여백)
_FONT = "krsans"


class _ReportPDF(FPDF):
    def __init__(self, has_kr_font: bool):
        super().__init__(orientation="P", unit="mm", format="A4")
        self._has_kr = has_kr_font
        self._family = _FONT if has_kr_font else "helvetica"

    def _f(self, size: float):
        self.set_font(self._family, "", size)

    def footer(self):  # noqa: D401 — fpdf2 훅
        self.set_y(-14)
        self._f(8)
        self.set_text_color(*_MUT)
        self.cell(0, 6, f"{self.page_no()} / {{nb}}", align="C")


def build_report_pdf(data: dict) -> bytes:
    """구조화된 보고서 dict → A4 세로 PDF bytes. 도메인·DB 비의존(순수).

    ``data`` 키: report_no·status·status_effect·reporter·dept·incident_date·confirmed_grade·
    cause·rejection_reason·sections([(tag,label,value)])·photo_names([str]).
    """
    font_path = _resolve_font()
    pdf = _ReportPDF(has_kr_font=font_path is not None)
    pdf.set_auto_page_break(True, margin=_MARGIN + 4)
    pdf.set_margins(_MARGIN, _MARGIN, _MARGIN)
    if font_path is not None:
        pdf.add_font(_FONT, "", font_path)
    pdf.alias_nb_pages()
    pdf.add_page()
    w = pdf.w - 2 * _MARGIN

    # ── 제목: 오버라인 + 보고번호 + 상태 ──
    pdf._f(9)
    pdf.set_text_color(*_MUT)
    pdf.cell(0, 5, "아차사고 보고서 · NEAR-MISS REPORT", new_x="LMARGIN", new_y="NEXT")
    pdf._f(22)
    pdf.set_text_color(*_INK)
    no = str(data.get("report_no") or "(번호 미상)")
    status = str(data.get("status") or "")
    pdf.cell(0, 11, no, new_x="LMARGIN", new_y="NEXT")
    if status:
        pdf._f(11)
        pdf.set_text_color(*_STATUS_RGB.get(status, _INK2))
        pdf.cell(0, 6, f"상태: {status}", new_x="LMARGIN", new_y="NEXT")
        # §3.3 — 상태 이름 밑에 그 상태의 결과(무엇이 막히고 열리는지)를 한 줄로.
        effect = str(data.get("status_effect") or "").strip()
        if effect:
            pdf._f(9)
            pdf.set_text_color(*_MUT)
            pdf.cell(0, 5, effect, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    _hairline(pdf, w)

    # ── 메타(신고자·소속·발생일·평가 등급·발생원인) — 3열 그리드 ──
    # 2026-08-18: 제안등급 셀 폐기(§7.2-1b, 항상 비는 값) → 6칸 2줄에서 5칸으로 줄었다.
    # 마지막 셀이 남은 열을 모두 차지하게 해 빈 칸을 남기지 않는다(열 시작 x 는 그대로라
    # 위·아래 줄의 열 정렬은 유지된다).
    meta = [
        ("신고자", data.get("reporter")), ("소속", data.get("dept")),
        ("발생일", data.get("incident_date")),
        ("평가 등급", data.get("confirmed_grade")), ("발생원인", data.get("cause")),
    ]
    col_w = w / 3.0
    for i in range(0, len(meta), 3):
        row = meta[i:i + 3]
        y0 = pdf.get_y()
        for j, (label, value) in enumerate(row):
            x = _MARGIN + j * col_w
            cell_w = col_w * (3 - j) if j == len(row) - 1 else col_w
            pdf.set_xy(x, y0)
            pdf._f(8); pdf.set_text_color(*_MUT)
            pdf.cell(cell_w, 4.5, str(label), new_x="LEFT", new_y="NEXT")
            pdf.set_x(x)
            pdf._f(11); pdf.set_text_color(*_INK)
            pdf.cell(cell_w, 5.5, str(value or "-"))
        pdf.set_y(y0 + 12)
    pdf.ln(1)
    _hairline(pdf, w)
    pdf.ln(2)

    # ── 반려 사유(있을 때) ──
    if data.get("rejection_reason"):
        pdf._f(10); pdf.set_text_color(*_WARN)
        pdf.multi_cell(0, 5.5, f"반려 사유: {data['rejection_reason']}",
                       new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    # ── 본문 블록(작업명·WHAT/TASK/SITE/CAUSE/ACTION) — 좌측 2px 보더 + 오버라인 라벨 + 본문 ──
    for tag, label, value in data.get("sections", []):
        _section_block(pdf, tag, label, str(value or "-"), w)

    # ── 사진(파일명만 — 임베드는 사진 기능 완성 후 후속) ──
    photos = data.get("photo_names") or []
    if photos:
        pdf.ln(1)
        pdf._f(8); pdf.set_text_color(*_MUT)
        pdf.cell(0, 5, f"첨부 사진 {len(photos)}건 (파일명 — 이미지 임베드는 후속)",
                 new_x="LMARGIN", new_y="NEXT")
        pdf._f(10); pdf.set_text_color(*_INK2)
        for fn in photos:
            pdf.multi_cell(0, 5, f"· {fn}", new_x="LMARGIN", new_y="NEXT")

    out = pdf.output()
    return bytes(out)


def _hairline(pdf: FPDF, w: float) -> None:
    pdf.set_draw_color(*_LINE)
    pdf.set_line_width(0.2)
    y = pdf.get_y()
    pdf.line(_MARGIN, y, _MARGIN + w, y)


def _section_block(pdf: FPDF, tag: str, label: str, value: str, w: float) -> None:
    # 페이지 넘김 여유(오버라인+라벨+최소 한 줄)를 확보한 뒤 좌측 보더를 그린다.
    pdf.ln(2)
    if pdf.get_y() > pdf.h - _MARGIN - 20:
        pdf.add_page()
    top = pdf.get_y()
    inset = 4.0
    # 태그(오버라인)가 라벨과 같은 낱말이면 생략한다 — '작업명/작업명'처럼 같은 말이
    # 두 줄로 반복되던 출력 중복 제거(태그는 WHAT/TASK 처럼 라벨과 다를 때만 정보다).
    if str(tag).strip() and str(tag).strip() != str(label).strip():
        pdf.set_x(_MARGIN + inset)
        pdf._f(8); pdf.set_text_color(*_MUT)
        pdf.cell(0, 4.5, tag, new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(_MARGIN + inset)
    pdf._f(10.5); pdf.set_text_color(*_INK2)
    pdf.cell(0, 5, label, new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(_MARGIN + inset)
    pdf._f(11); pdf.set_text_color(*_INK)
    pdf.set_left_margin(_MARGIN + inset)
    pdf.multi_cell(w - inset, 5.6, value, new_x="LMARGIN", new_y="NEXT")
    pdf.set_left_margin(_MARGIN)
    bottom = pdf.get_y()
    # 좌측 2px(≈0.7mm) 오렌지 보더.
    pdf.set_draw_color(*_ACCENT)
    pdf.set_line_width(0.7)
    pdf.line(_MARGIN + 0.35, top, _MARGIN + 0.35, bottom)


# ── report dict → build_report_pdf 입력 data (표시맵은 호출부가 넘긴다) ──
def report_to_pdf_data(report: dict, *, reporter: str, dept: str,
                       status_label: str, cause_label: str,
                       status_effect: str = "") -> dict:
    """도메인 report dict + 해석된 표시값 → PDF data. 사진은 photo_paths 파일명만 싣는다.

    ``status_effect``(§3.3 상태의 결과)는 호출부가 화면과 **같은 어휘**로 계산해 넘긴다 —
    이 모듈은 도메인을 모르므로 상태 코드에서 스스로 파생하지 않는다. 미지정이면 출력하지
    않는다(기존 호출부 호환)."""
    def _c(v) -> str:
        return "" if v is None else str(v).strip()

    cause_detail = _c(report.get("cause_detail"))
    cause_val = cause_label + (f" · {cause_detail}" if cause_detail else "")
    sections = [
        ("WHAT", "사고내용", _c(report.get("incident_content"))),
        ("TASK", "작업내용", _c(report.get("work_content"))),
        ("SITE", "작업현장 상황설명", _c(report.get("site_description"))),
        ("CAUSE", "발생원인", cause_val),
        ("ACTION", "예방대책", _c(report.get("countermeasure"))),
    ]
    photo_paths = report.get("photo_paths") or []
    photo_names = [os.path.basename(str(p)) for p in photo_paths if str(p).strip()]
    return {
        "report_no": _c(report.get("report_no")) or "(번호 미상)",
        "status": status_label,
        "status_effect": _c(status_effect),
        "reporter": reporter or "-",
        "dept": dept or "-",
        "incident_date": _c(report.get("incident_date")) or "-",
        # 제안등급(proposed_grade)은 싣지 않는다(§7.2-1b 폐기 — 입력 경로가 없어 항상 빈다).
        "confirmed_grade": _c(report.get("confirmed_grade")) or "미정",
        "cause": cause_label or "-",
        "rejection_reason": _c(report.get("rejection_reason")),
        "work_name": _c(report.get("work_name")),
        "sections": [("작업명", "작업명", _c(report.get("work_name")))] + sections,
        "photo_names": photo_names,
    }
