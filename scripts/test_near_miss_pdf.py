"""아차사고 보고서 PDF 생성 단위 계약 — 생성 성공·%PDF·페이지 수·크기>0·다장 넘김.

DB 비의존(순수 함수). 실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_near_miss_pdf.py
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from views import near_miss_pdf  # noqa: E402

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


def _page_count(pdf: bytes) -> int:
    # /Type /Page (not /Pages) 오브젝트 수 — 간이 페이지 카운트(외부 의존 없이).
    return pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")


BASE = {
    "report_no": "202607-0001", "status": "SUBMITTED", "reporter_emp_no": "1001",
    "dept_code": "PET1", "incident_date": "2026-07-15",
    "confirmed_grade": "", "cause_code": "SLIP",
    "incident_content": "PET 원료실 계획서 수정 중 바닥의 기름막에 미끄러짐.",
    "work_content": "생산계획서 수정·부착", "site_description": "원료실 입구 통로",
    "countermeasure": "코일매트 설치·누유 제거", "cause_detail": "바닥 누유",
    "work_name": "계획서 부착", "photo_paths": ["dir/photo1.jpg", "photo2.png"],
}


def _data(report, **kw):
    # status_label 은 호출부(near_miss_view._STATUS_LABEL)가 넘기는 실제 표시 라벨을 쓴다 —
    # '제출'이 아니라 '제출됨'(2026-08-14 6화면 어휘 통일). _STATUS_RGB 키와 일치해야
    # 상태 색이 기본값으로 떨어지지 않는다.
    kw.setdefault("status_label", "제출됨")
    kw.setdefault("status_effect", "평가 착수 전 — 보고자 수정 가능")
    return near_miss_pdf.report_to_pdf_data(
        report, reporter="김관리", dept="PET생산부(본동)",
        cause_label="미끄러짐", **kw,
    )


print("PDF 생성 계약")
data = _data(BASE)
check("report_to_pdf_data: 보고번호 매핑", data["report_no"] == "202607-0001")
check("report_to_pdf_data: 사진 파일명만(경로 제거)", data["photo_names"] == ["photo1.jpg", "photo2.png"])
check("report_to_pdf_data: 본문 섹션(작업명+WHAT/TASK/SITE/CAUSE/ACTION)=6",
      len(data["sections"]) == 6 and data["sections"][1][0] == "WHAT")

# ── 2026-08-18 §7.2-1b 제안등급 폐기 · §3.6 어휘 · §3.3 상태의 결과 ──
check("제안등급을 PDF data 에 싣지 않는다(§7.2-1b)", "proposed_grade" not in data)
check("평가 등급은 confirmed_grade 에서만 온다(빈 값은 '미정')",
      data["confirmed_grade"] == "미정")
_build_src = inspect.getsource(near_miss_pdf.build_report_pdf)
check("메타 라벨이 정본 '평가 등급'(생성 소스)",
      '"평가 등급"' in _build_src
      and '"제안등급"' not in _build_src and '"확정등급"' not in _build_src)
check("메타 셀에서 제안등급 값을 읽지 않음",
      'data.get("proposed_grade")' not in _build_src)
check("§3.6 상태 색 키가 화면 표시 라벨과 동일(제출됨·평가중)",
      set(near_miss_pdf._STATUS_RGB) == {"제출됨", "평가중", "평가완료", "종결", "반려"})
check("호출부 status_label('제출됨')이 색 매핑에 적중", data["status"] in near_miss_pdf._STATUS_RGB)
check("§3.3 상태의 결과가 data 에 실린다",
      data["status_effect"] == "평가 착수 전 — 보고자 수정 가능")
check("status_effect 미지정이면 빈 문자열(기존 호출부 호환)",
      near_miss_pdf.report_to_pdf_data(
          BASE, reporter="-", dept="-", status_label="종결",
          cause_label="미끄러짐")["status_effect"] == "")

pdf = near_miss_pdf.build_report_pdf(data)
check("bytes 반환", isinstance(pdf, (bytes, bytearray)))
check("크기 > 0", len(pdf) > 0)
check("%PDF 헤더", bytes(pdf[:5]) == b"%PDF-")
check("최소 1페이지", _page_count(pdf) >= 1)

# 다장 넘김: 매우 긴 본문 → 2페이지 이상.
long_report = {**BASE, "incident_content": ("가나다라마바사아자차 " * 500)}
pdf_long = near_miss_pdf.build_report_pdf(_data(long_report))
check("긴 본문 → 다장 넘김(≥2페이지)", _page_count(pdf_long) >= 2)
check("긴 본문 PDF 도 %PDF", bytes(pdf_long[:5]) == b"%PDF-")

# 결측/빈 값 방어 — 예외 없이 생성.
try:
    pdf_min = near_miss_pdf.build_report_pdf(_data({"report_no": "X"}))
    check("결측 필드도 예외 없이 생성", len(pdf_min) > 0)
except Exception as exc:  # noqa: BLE001
    check(f"결측 필드도 예외 없이 생성 ({exc})", False)

# 폰트 해석 — 동봉 폰트 존재 시 그것을 우선.
fp = near_miss_pdf._resolve_font()
check("한글 폰트 경로 해석됨(동봉 또는 시스템)", fp is not None)
check("동봉 폰트 우선(fonts/NotoSansKR-Regular.ttf)",
      fp is None or fp.endswith("NotoSansKR-Regular.ttf"))  # 동봉 폰트 존재 시 그것을 우선(시스템보다)

print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
