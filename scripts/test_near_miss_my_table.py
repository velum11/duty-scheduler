"""내 아차사고 컬럼형 표 계약 회귀 (2026-08-13 "컬럼 나눠줘 — 조회 테이블 참조").

한 줄 요약 아코디언 → **컬럼형 표 + 전체폭 상세** 전환의 표시·선택 계약을 고정한다.
표시 라벨/색은 아차사고 조회(``views/near_miss_view``)와 같은 계열이어야 하고, 선택은
자연키(보고서 id)로 오가며 상세 진입 경로(행 클릭 → ``_render_detail``)가 보존돼야 한다.

  1) 컬럼 구성 — 조회 8열에서 신고자·소속만 뺀 6열, 순서 동일(2026-08-18 확정 순서:
     번호 → 발생일 → 원인 → 작업명 → 등급 → 상태, 상태가 제일 우측).
  2) 표시 서식 — 보고번호 모노, 발생일 ISO 원문, 빈 등급 '-', 상태·원인 한글 라벨.
  3) 색 규칙 — 상태·등급 색이 조회 화면과 **같은 값**(같은 상태가 화면마다 다른 색 금지).
  4) 선택 계약 — hidden 자연키(_report_id), 상세 여는 체크박스 없음(§0-1),
     compact 행 피치 38px(§1.4 34~38), 자연키 유일·비표시.
  5) 상세 진입 보존 — 선택된 자연키의 건이 _render_detail 로 전달되고, 앵커에 보고번호가
     노출된다. 목록에서 사라진 stale 선택은 조용히 해제된다.
  7) 2026-08-18 어휘·표시 정합 — 제안등급 폐기(§7.2-1b) · '검토중'→'평가중'(§3.6) ·
     상태의 결과 표기(§3.3) · 조회 화면과 같은 지표 라벨.

실행: PYTHONUTF8=1 C:\\dev\\workops\\.venv\\Scripts\\python.exe scripts/test_near_miss_my_table.py
"""
from __future__ import annotations

import inspect
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from views import near_miss_my as nmy  # noqa: E402
from views import near_miss_view as nmv  # noqa: E402
from views.common.erp import kit  # noqa: E402

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


REPORTS = pd.DataFrame([
    {"id": "NM-1", "report_no": "202608-0004", "status": "SUBMITTED",
     "work_name": "전동밸브 점검", "incident_date": "2026-08-11",
     "proposed_grade": "C", "confirmed_grade": None, "cause_code": "BURN"},
    {"id": "NM-2", "report_no": "202607-0002", "status": "EVALUATED",
     "work_name": "설비 청소", "incident_date": "2026-07-21",
     "proposed_grade": "C", "confirmed_grade": "B", "cause_code": "SLIP"},
    {"id": "NM-3", "report_no": "202606-0001", "status": "CLOSED",
     "work_name": "", "incident_date": "2026-06-02",
     "proposed_grade": None, "confirmed_grade": "D", "cause_code": "DROP"},
])


# ===== 1) 컬럼 구성 — 조회 8열 − (신고자·소속) =====
print("컬럼 구성(조회 참조)")
# 2026-08-19 사고내용 추가 → 7열(조회 9열 − 소속·신고자).
check("표시 7열", len(nmy._DISPLAY_COLUMNS) == 7)
check("사고내용 열 존재(작업명 바로 뒤)",
      nmy._DISPLAY_COLUMNS.index("사고내용") == nmy._DISPLAY_COLUMNS.index("작업명") + 1)
check("제안등급 열 폐기(§7.2-1b — 되돌림 방지)",
      "제안등급" not in nmy._DISPLAY_COLUMNS and "제안등급" not in nmy._COL_CONFIG)
check("등급 열은 §3.6 축약형 '등급' 하나만",
      [c for c in nmy._DISPLAY_COLUMNS if "등급" in c] == ["등급"])
check("신고자 열 없음(본인 전용 화면)", "신고자" not in nmy._DISPLAY_COLUMNS)
check("소속 열 없음(본인 전용 화면)", "소속" not in nmy._DISPLAY_COLUMNS)
# 2026-08-18 사용자 확정 순서(조회와 **같은 값**): 문서번호 · 발생일 · 원인 · 작업명 ·
# 소속 · 신고자 · 등급 · 상태(제일 우측). 이 화면은 소속·신고자가 빠져 6열이 된다.
# 종전의 "상태를 발생일 뒤로 당긴다(2026-08-13)"는 이번 지시가 뒤이므로 폐기됐다.
# 2026-08-19: 조회에 '개선조치' 열이 추가됐다(사용자 지시). 내 아차사고에 같은 열을 넣을지는
# 별도 판단 대상이라 이번에는 넣지 않았다(보고자는 개선조치 담당자가 아닌 경우가 많고,
# 평가완료 이전 건에는 값이 아예 없다). 따라서 제외 집합에 '개선조치'가 함께 들어간다 —
# "조회 열 순서를 그대로 따르되 이 화면에 의미 없는 열만 뺀다"는 계약 자체는 불변이다.
check("확정 순서 그대로(조회에서 소속·신고자·개선조치만 제거)",
      nmy._DISPLAY_COLUMNS == [c for c in nmv._DISPLAY_COLUMNS
                               if c not in ("소속", "신고자", "개선조치")])
check("상태가 제일 우측", nmy._DISPLAY_COLUMNS[-1] == "상태")
check("모든 표시 열이 조회 화면 열의 부분집합",
      set(nmy._DISPLAY_COLUMNS) <= set(nmv._DISPLAY_COLUMNS))
check("모든 표시 열에 폭 지정(_COL_CONFIG)",
      all(c in nmy._COL_CONFIG for c in nmy._DISPLAY_COLUMNS))
# §1.2(2026-08-19): 모노 서체 폐지 — 글꼴은 Pretendard 하나이고 자릿수 정렬은
# tabular-nums 가 담당한다. 보고번호에 별도 서식을 두지 않는다(조회와 동일).
check("보고번호에 모노 서식 없음(§1.2 모노 폐지)",
      "Mono" not in str(nmy._COL_CONFIG["보고번호"].get("cellStyle", {})))
# "남는 가로 폭을 flex 로 아무 열에나 흡수시키지 마라. 남으면 남긴다."(2026-08-18 확정)
check("잔여 폭 흡수(flex) 열 없음 — 전부 고정폭",
      not any("flex" in cfg for cfg in nmy._COL_CONFIG.values()))


# ===== 2) 표시 서식(_to_display) =====
print("표시 서식")
disp = nmy._to_display(REPORTS)
check("행 수 보존", len(disp) == 3)
check("컬럼 = 자연키 + 표시 6열",
      list(disp.columns) == [nmy._KEY_FIELD] + nmy._DISPLAY_COLUMNS)
r0 = disp.iloc[0].to_dict()
check("보고번호 원문", r0["보고번호"] == "202608-0004")
check("발생일 ISO 원문(YYYY-MM-DD)", r0["발생일"] == "2026-08-11")
check("상태 한글 라벨", r0["상태"] == nmy._STATUS_LABEL["SUBMITTED"])
check("원인 한글 라벨", r0["원인"] == nmy._CAUSE_LABEL["BURN"])
check("빈 등급은 '-'(코드 노출·빈칸 금지)", r0["등급"] == "-")
check("등급 열 값은 confirmed_grade(제안 값이 새지 않음)", disp.iloc[1]["등급"] == "B")
check("표시 변환에 proposed_grade 미참조",
      "proposed_grade" not in inspect.getsource(nmy._to_display))
check("작업명 빈값 폴백", disp.iloc[2]["작업명"] == "(제목 없음)")
check("자연키는 보고서 id 문자열", list(disp[nmy._KEY_FIELD]) == ["NM-1", "NM-2", "NM-3"])
check("원시 상태코드 미노출", "EVALUATED" not in set(disp["상태"]))
check("원시 원인코드 미노출", "SLIP" not in set(disp["원인"]))


# ===== 3) 색 규칙 — 조회 화면과 같은 값 =====
print("상태·등급 색(조회와 동일 값)")
for code in ("SUBMITTED", "IN_REVIEW", "EVALUATED", "CLOSED", "REJECTED"):
    check(f"상태색 {code} 조회와 동일",
          nmy._STATUS_COLOR[code] == nmv._STATUS_COLOR[code])
check("상태 5종 전부 색 보유", set(nmy._STATUS_COLOR) == set(nmy._STATUS_LABEL))
check("등급색 매핑이 조회와 동일", nmy._GRADE_COLOR == nmv._GRADE_COLOR)


# ===== 4) 선택 계약(select_grid 옵션 실제 빌드) =====
print("선택 계약")
list_src = inspect.getsource(nmy._render_list)
check("목록은 공용 select_grid 어휘 사용", "erp.select_grid(" in list_src)
check("상세 여는 체크박스 없음(§0-1)", "checkbox_marker=False" in list_src)
# 목록 표는 compact(§1.4 34~38px, 2026-08-18 확정 지시). 종전 cozy 44px 폐기 —
# §3.4 모바일 우선 3화면에 이 화면은 없고 READ_VIEW 밀도도 compact 다.
check("행 피치 = compact 밴드 상단 38px", "row_height=38" in list_src)
check("cozy 44px 되돌림 방지", "row_height=44" not in list_src)
check("자연키는 표시 컬럼이 아님", nmy._KEY_FIELD not in nmy._DISPLAY_COLUMNS)

view, options, _css = kit._build_select_gridoptions(
    disp, key_field=nmy._KEY_FIELD, columns=nmy._DISPLAY_COLUMNS,
    selected_key="NM-2", color_rules={
        "등급": nmy._GRADE_COLOR,
        "상태": {lab: nmy._STATUS_COLOR[c] for c, lab in nmy._STATUS_LABEL.items()},
    },
    col_config=nmy._COL_CONFIG, row_rules=None, hidden_fields=None,
    row_height=38, checkbox_marker=False,
)
check("grid 옵션 rowHeight=38(compact 34~38)", options["rowHeight"] == 38)
check("단일 선택(rowSelection=single)", options["rowSelection"] == "single")
check("행 클릭이 선택(suppressRowClickSelection=False)",
      options["suppressRowClickSelection"] is False)
check("첫 열에 checkboxSelection 미주입",
      "checkboxSelection" not in options["columnDefs"][0])
check("자연키 컬럼은 hidden", any(cd["field"] == nmy._KEY_FIELD and cd.get("hide")
                              for cd in options["columnDefs"]))
check("표시 컬럼 순서 그대로 colDef",
      [cd["field"] for cd in options["columnDefs"] if not cd.get("hide")]
      == nmy._DISPLAY_COLUMNS)
check("선택 자연키 pre-select(위치 비의존, NM-2 → index 1)",
      options.get("initialState", {}).get("rowSelection") == ["1"])
# 좁은 폭 계약: 고정폭 합이 390px 를 넘으므로 AgGrid 가 **표 안에서** 가로 스크롤한다
# (§5 "표는 overflow-x:auto"). 페이지 가로 스크롤은 실측(Playwright)이 담당.
min_total = sum(cfg["width"] for cfg in nmy._COL_CONFIG.values())
check("표 최소 폭 > 390(좁은 폭에서 표 내부 가로 스크롤)", min_total > 390)
# 2026-08-19 §1.2 재역산(표 12px · Pretendard) + 사고내용 400: 88+80+64+144+400+40+64 = 880.
# 고정폭이 아니라 비율이다 — fitGridWidth 가 이 비율로 남는 폭을 나눈다.
check("폭 비율 합 = 880", min_total == 880)
# 같은 성격 열은 두 화면이 **같은 값**(기존 계약 유지).
for _c in nmy._DISPLAY_COLUMNS:
    check(f"{_c} 열 폭이 조회 화면과 동일",
          nmy._COL_CONFIG[_c]["width"] == nmv._COL_CONFIG[_c]["width"])


# ===== 5) 상세 진입 보존 =====
print("상세 진입 보존")
check("선택 시 _render_detail 호출", "_render_detail(" in list_src)
check("선택은 자연키로 행 복원(id 매칭)", 'frame["id"].astype(str) == selected' in list_src)
check("stale 선택은 세션에서 해제(pop)", "_SEL_KEY, None" in list_src)
check("빈 안내 패널을 그리지 않는다(§8-2 — empty_state/detail_empty 미호출)",
      "empty_state(" not in list_src and "detail_empty(" not in list_src)
check("미선택이면 상세 미렌더(빈 패널 금지 §8-2)", "if not selected:" in list_src)

anchor = nmy._detail_anchor_html(REPORTS.iloc[1].to_dict(), "EVALUATED")
check("상세 앵커에 보고번호 노출", "202607-0002" in anchor)
check("상세 앵커에 상태 배지(라벨) 노출", nmy._STATUS_LABEL["EVALUATED"] in anchor)
check("앵커 배지는 공용 kit primitive(status_badge_html) 사용",
      "status_badge_html" in inspect.getsource(nmy._detail_anchor_html))
detail_src = inspect.getsource(nmy._render_detail)
check("상세 첫 블록이 앵커", detail_src.index("_detail_anchor_html")
      < detail_src.index("_steps_html"))
# 워크플로 계약 불변(표현만 교체) — 수정 진입·사진·배너 경로 보존.
check("SUBMITTED 자기수정 진입 보존", "_render_edit_entry" in detail_src)
check("사진 섹션 보존", "_render_my_photos" in detail_src)
check("보완요청 배너 보존", "_render_revision_banner" in detail_src)

# 구 아코디언 잔재 제거(행 버튼 CSS·토글 키) — 회귀 방지.
check("구 행 버튼(myrow_) 잔재 없음", "myrow_" not in inspect.getsource(nmy))
check("아코디언 토글 rerun 잔재 없음", "st.rerun()" not in list_src)


# ===== 6) 행위: 선택 자연키가 세션에 남고 stale 은 해제 =====
print("선택 상태(세션) 행위")
st.session_state[nmy._SEL_KEY] = "NM-없는건"
_orig = nmy.erp.select_grid
_seen = {}
try:
    def _fake_grid(df, **kw):
        _seen["selected_key"] = kw.get("selected_key")
        _seen["columns"] = kw.get("columns")
        return None
    nmy.erp.select_grid = _fake_grid
    nmy._render_detail = lambda *a, **k: _seen.setdefault("detail", a)  # type: ignore
    nmy._render_list({"emp_no": "1003"}, REPORTS)
    check("목록에 없는 stale 선택은 세션에서 제거",
          nmy._SEL_KEY not in st.session_state)
    check("stale 선택은 grid 에 pre-select 로 넘기지 않음",
          _seen.get("selected_key") is None)
    check("stale 선택이면 상세 미렌더", "detail" not in _seen)
    check("grid 에 표시 6열 전달", _seen.get("columns") == nmy._DISPLAY_COLUMNS)
finally:
    nmy.erp.select_grid = _orig
    st.session_state.pop(nmy._SEL_KEY, None)


# ===== 7) 어휘(§3.6) · 상태의 결과(§3.3) · 조회 화면과 목록 어휘 정합 =====
print("어휘·상태의 결과·조회 화면 정합")
check("IN_REVIEW 라벨 = '평가중'", nmy._STATUS_LABEL["IN_REVIEW"] == "평가중")
check("'검토중' 라벨 폐기", "검토중" not in set(nmy._STATUS_LABEL.values()))
check("상태 라벨이 조회 화면과 동일(같은 상태·같은 말)",
      nmy._STATUS_LABEL == nmv._STATUS_LABEL)
check("진행 단계 pill 도 '평가중'",
      "평가중" in inspect.getsource(nmy._steps_html)
      and "검토중" not in inspect.getsource(nmy._steps_html))
# §3.3 — 배지 옆 한 줄로 그 상태가 무엇을 막고 여는지 적는다.
check("모든 상태에 결과 표기 존재(_STATUS_EFFECT)",
      set(nmy._STATUS_EFFECT) == set(nmy._STATUS_LABEL)
      and all(str(v).strip() for v in nmy._STATUS_EFFECT.values()))
_anchor_effect = nmy._detail_anchor_html(REPORTS.iloc[0].to_dict(), "IN_REVIEW")
check("상세 앵커에 상태의 결과 노출(§3.3)",
      nmy._STATUS_EFFECT["IN_REVIEW"] in _anchor_effect)
check("잠김 어휘는 평가 관리·조회와 동일('보고자 수정 잠김')",
      nmy._STATUS_EFFECT["IN_REVIEW"] == nmv._STATUS_EFFECT["IN_REVIEW"] == "보고자 수정 잠김")
# 상세 등급 메타는 정본 '평가 등급'(표 헤더만 폭 때문에 '등급'으로 줄인다).
_blocks_src = inspect.getsource(nmy._detail_blocks_html)
check("상세 등급 메타 라벨 = '평가 등급'",
      '"평가 등급"' in _blocks_src and "확정등급" not in _blocks_src)
check("상세 메타에 제안등급 미참조", "proposed_grade" not in _blocks_src)
# 한글 라벨은 모노·자간 없이 본문 sans 를 상속한다(한글 글리프 부재 → 글자별 폴백).
_meta_html = nmy._detail_blocks_html(REPORTS.iloc[1].to_dict())
_meta_head = _meta_html.split("gap:20px 32px")[0]   # 본문 블록 앞까지(= 메타 영역)
check("한글 등급 라벨에 모노 미적용", "monospace" not in _meta_head)
check("한글 등급 라벨에 letter-spacing 미적용", "letter-spacing" not in _meta_head)
check("라벨 크기·색 불변(10.5px / #6b665d)",
      "font-size:10.5px" in _meta_head and nmy._MUT in _meta_head)
# §1.2(2026-08-19): 모노 서체 폐지 — 글꼴은 Pretendard 하나이고 자릿수 정렬은
# tabular-nums 가 담당한다. 영숫자라도 별도 서체를 쓰지 않는다.
check("영문 태그에 모노 없음(§1.2 모노 폐지)", "monospace" not in _meta_html)
check("보고번호 앵커에 모노 없음(§1.2 모노 폐지)",
      "monospace" not in nmy._detail_anchor_html(REPORTS.iloc[1].to_dict(), "EVALUATED"))
# 결측(NaN) 등급은 'NAN' 이 아니라 빈 값 라벨('미정')로 렌더된다(2026-08-18 실렌더 버그).
_nan_grade = REPORTS.iloc[0].to_dict()["confirmed_grade"]
check("None 등급 → '미정'", "미정" in nmy._grade_mark(_nan_grade, empty="미정"))
check("pandas 결측(NaN) 등급 → 'NAN' 미노출",
      "NAN" not in nmy._grade_mark(float("nan"), empty="미정")
      and "미정" in nmy._grade_mark(float("nan"), empty="미정"))
check("조회 화면도 같은 방어(NaN → '미정')",
      "NAN" not in nmv._grade_mark(float("nan"), empty="미정"))
check("정상 등급은 그대로(B)", "B" in nmy._grade_mark("b", empty="미정"))
# 자기 정정(본문 수정) 폼에 제안등급 입력 위젯이 없다 — 저장 payload 의 보존 pass-through는
# 파사드가 None 을 그대로 써 기존 값을 지우기 때문이며(데이터 처분은 data-contract 소관),
# 화면 입력·표시로는 어디에도 노출되지 않는다.
_form_src = inspect.getsource(nmy._render_edit_form)
_form_widget_labels = re.findall(
    r'st\.(?:text_input|text_area|selectbox|date_input|number_input|radio|'
    r'segmented_control|multiselect)\(\s*"([^"]+)"', _form_src)
check("자기 정정 폼에 등급 입력 위젯 없음(입력 경로 부재)",
      _form_widget_labels and not any("등급" in lab for lab in _form_widget_labels))
check("자기 정정 폼이 등급 목록을 읽지 않음", "NEAR_MISS_GRADES" not in _form_src)
# 지표 스트립 라벨 — 같은 계산은 두 화면이 같은 낱말을 쓴다(§3.6).
_my_labels = [t[0] for t in nmy._my_metrics(REPORTS)]
_view_labels = [t[0] for t in nmv._view_metrics(REPORTS)]
check("지표 라벨이 조회 화면과 동일", _my_labels == _view_labels)
check("SUBMITTED+IN_REVIEW 타일 이름 = '미평가'", _my_labels[1] == "미평가")
# §2 READ_VIEW 영역 순서: 제목 → 조회 조건 → (지표) → 표.
_render_src = inspect.getsource(nmy.render)
check("영역 순서: screen_frame → 조건 → metric_strip → 목록",
      _render_src.index("erp.screen_frame")
      < _render_src.index("_collect_my_filters")
      < _render_src.index("erp.metric_strip")
      < _render_src.index("_render_list"))


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
