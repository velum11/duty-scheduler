"""views/near_miss_view.py 순수 함수 회귀 테스트(구조적 UI 이관 전 보존 목록).

대상: `_scope_for`(fail-closed 접근 범위) · `_to_display`(8열 표시 변환) ·
`_has_filters` · `_facade_filters`. 그리드 엔진/필터 레이아웃을 구조적으로
바꾸기 전, 이 네 함수의 현재 계약을 고정한다(비회귀 그물).

2026-08-18 DESIGN §7.2-1b/§3.6 반영: 제안등급 열 폐기(9열→8열) · 확정등급 헤더는 축약형
'등급' · IN_REVIEW 라벨 '검토중'→'평가중' · §3.3 상태의 결과 표기. 되돌림 방지로 폐기된
표시의 **부재**를 명시 검증한다.

로컬 sample 모드에서만 동작하며 Supabase 에 접속하지 않는다. `db.get_departments`/
`db.get_users` 는 통제된 DataFrame 으로 monkeypatch 한다(scripts/test_login_auth.py
의 `db.get_users = lambda *a, **k: fake` 관행을 따름 — near_miss_view 는
`from modules import db` 로 같은 모듈 객체를 참조하므로 monkeypatch 가 그대로 반영된다).

실행: C:\\dev\\workops\\.venv\\Scripts\\python.exe scripts/test_near_miss_view.py
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"  # Supabase 미접속 보장

import pandas as pd  # noqa: E402

from modules import db  # noqa: E402
from views import near_miss_view as nmv  # noqa: E402
from views import workspace  # noqa: E402

PASSED = 0


def check(name: str, condition: bool) -> None:
    global PASSED
    assert condition, f"FAILED: {name}"
    PASSED += 1
    print(f"  ok - {name}")


# ---------- 통제된 부서/사용자 DataFrame (test_schedule_contracts.py 의
# PET1/PET2 dept 설정 관행을 mirror) ----------
_DEPTS_DF = pd.DataFrame([
    {"dept_code": "PET1", "dept_name": "PET1부"},
    {"dept_code": "PET2", "dept_name": "PET2부"},
    {"dept_code": "MGT", "dept_name": "경영지원"},
])
_USERS_DF = pd.DataFrame([
    {"emp_no": "1001", "name": "김철수"},
    {"emp_no": "1002", "name": "이영희"},
])


def test_scope_for() -> None:
    print("_scope_for (fail-closed 접근 범위)")
    orig_get_departments = db.get_departments
    db.get_departments = lambda *a, **k: _DEPTS_DF  # type: ignore[assignment]
    try:
        # MANAGER + 유효 dept_code → scoped
        scope, dept, names = nmv._scope_for({"role": "MANAGER", "dept_code": "PET1"})
        check("MANAGER 유효 dept → scoped", scope == "scoped")
        check("MANAGER 유효 dept → manager_dept == 'PET1'", dept == "PET1")
        check("MANAGER 유효 dept → dept_names 채워짐", names == {
            "PET1": "PET1부", "PET2": "PET2부", "MGT": "경영지원",
        })

        # MANAGER + 빈 dept_code("") → blocked
        r = nmv._scope_for({"role": "MANAGER", "dept_code": ""})
        check("MANAGER 빈 dept('') → blocked", r == ("blocked", None, {}))

        # MANAGER + None dept_code → blocked
        r = nmv._scope_for({"role": "MANAGER", "dept_code": None})
        check("MANAGER dept=None → blocked", r == ("blocked", None, {}))

        # MANAGER + 존재하지 않는(삭제/오래된) dept_code → blocked, "all" 로 새지 않음
        r = nmv._scope_for({"role": "MANAGER", "dept_code": "NOPE"})
        check("MANAGER 미존재 dept('NOPE') → blocked(전체조회로 새지 않음)",
              r == ("blocked", None, {}))

        # ADMIN → all + 전체 부서맵
        scope, dept, names = nmv._scope_for({"role": "ADMIN"})
        check("ADMIN → scope == 'all'", scope == "all")
        check("ADMIN → manager_dept is None", dept is None)
        check("ADMIN → dept_names 전체", names == {
            "PET1": "PET1부", "PET2": "PET2부", "MGT": "경영지원",
        })

        # role == "USER" 且 안전담당자 → all (역할 무관 — 코드 주석 의도)
        # 주의(플래그): _scope_for 자체는 is_safety_officer 를 읽지 않는다.
        # role != "MANAGER" 이면 무조건 "all" 을 반환하므로, 안전담당자 여부와
        # 무관하게 동일 결과가 나온다 — 실제 게이트는 상위 auth.can_evaluate_near_miss
        # (render 진입 시점)에 있다. 이 테스트는 그 상위 계약을 전제로, 안전담당자
        # user-dict 모양을 그대로 사용해 _scope_for 반환값만 고정한다.
        scope, dept, names = nmv._scope_for(
            {"role": "USER", "dept_code": "", "is_safety_officer": True}
        )
        check("USER+안전담당자 → scope == 'all'(역할 무관)", scope == "all")
        check("USER+안전담당자 → manager_dept is None", dept is None)
        check("USER+안전담당자 → dept_names 전체", names == {
            "PET1": "PET1부", "PET2": "PET2부", "MGT": "경영지원",
        })
    finally:
        db.get_departments = orig_get_departments  # type: ignore[assignment]


def test_to_display() -> None:
    print("_to_display (9열 표시 변환)")
    orig_get_users = db.get_users
    orig_get_departments = db.get_departments
    db.get_users = lambda *a, **k: _USERS_DF  # type: ignore[assignment]
    db.get_departments = lambda *a, **k: _DEPTS_DF  # type: ignore[assignment]
    try:
        raw = pd.DataFrame([
            # 1) 정상 매핑(사번→이름, 부서코드→부서명, 상태/원인 라벨화)
            {
                "report_no": "NM-2026-001", "work_name": "배관 청소",
                "reporter_emp_no": "1001", "dept_code": "PET1",
                "incident_date": "2026-07-01", "proposed_grade": "B",
                "confirmed_grade": "A", "status": "EVALUATED", "cause_code": "SLIP",
            },
            # 2) 빈 값 전부 → "-" 폴백(신고자/소속/발생일/등급/원인),
            #    보고번호/작업명은 폴백 없이 그대로(빈 문자열), 상태는 값이
            #    있으므로("SUBMITTED") "-" 폴백 대상 아님.
            {
                "report_no": "NM-2026-002", "work_name": "",
                "reporter_emp_no": "", "dept_code": "",
                "incident_date": "", "proposed_grade": "", "confirmed_grade": "",
                "status": "SUBMITTED", "cause_code": "",
            },
            # 3) 매핑에 없는 코드(사번/부서/상태/원인) → 원문 그대로 폴백(빈 값
            #    아니므로 "-" 아님).
            {
                "report_no": "NM-2026-003", "work_name": "지게차 이동",
                "reporter_emp_no": "9999", "dept_code": "ZZZ",
                "incident_date": "2026-07-15", "proposed_grade": "S",
                "confirmed_grade": "S", "status": "WEIRD_STATUS",
                "cause_code": "WEIRD_CAUSE",
            },
            # 4) None/NaN → 정리(clean) 후 "-" 폴백
            {
                "report_no": "NM-2026-004", "work_name": "안전모 미착용",
                "reporter_emp_no": None, "dept_code": None,
                "incident_date": None, "proposed_grade": None,
                "confirmed_grade": None, "status": "CLOSED", "cause_code": None,
            },
        ])

        out = nmv._to_display(raw)

        # 2026-08-18 사용자 확정 순서: 문서번호 · 발생일 · 원인 · 작업명 · 소속 · 신고자 ·
        # 등급 · **상태(제일 우측)**. 헤더 낱말은 '보고번호' 유지(어휘 단일화는 §3.6 별건).
        check(
            "출력 열 집합·순서 고정(확정 지시 순서 — 상태가 제일 우측)",
            list(out.columns) == [
                "보고번호", "발생일", "원인", "작업명", "사고내용", "소속", "신고자",
                "등급", "상태",
            ],
        )
        check("상태는 마지막 열", list(out.columns)[-1] == "상태")
        check("원인은 발생일 바로 뒤(마지막 열 아님)",
              list(out.columns).index("원인") == list(out.columns).index("발생일") + 1)
        check("표시에 '제안등급' 열 없음(§7.2-1b — 되돌림 방지)",
              "제안등급" not in out.columns)
        check("등급 열은 confirmed_grade 만 싣는다(제안 값이 새지 않음)",
              out.iloc[0]["등급"] == "A")
        check("표시 열 목록도 9열(_DISPLAY_COLUMNS)", nmv._DISPLAY_COLUMNS == list(out.columns))
        # 2026-08-19: 사고내용 추가 — 행을 특정하는 서술 값이 없어 목록이 읽히지 않았다.
        check("사고내용 열 존재(작업명 바로 뒤)",
              list(out.columns).index("사고내용") == list(out.columns).index("작업명") + 1)
        check("모든 표시 열에 폭 지정(_COL_CONFIG)",
              all(c in nmv._COL_CONFIG for c in nmv._DISPLAY_COLUMNS))
        check("폐기 열의 폭 설정도 제거(빈 자리 없음)",
              "제안등급" not in nmv._COL_CONFIG and "확정등급" not in nmv._COL_CONFIG)
        # ── 폭 계약 ── 2026-08-18 "flex 로 한 열에 몰아주지 마라"는 유효하다.
        # 2026-08-19 추가: 지정 폭은 고정폭이 아니라 **비율**이다 — kit 의
        # autoSizeStrategy fitGridWidth 가 남는 폭을 각 열의 지정 폭에 비례해
        # 나눠 주므로 열 사이 비중(내용에서 나온 비중)이 유지된다. flex 지정은
        # 여전히 금지다(한 열만 커지는 원인).
        check("잔여 폭 흡수(flex) 열 없음",
              not any("flex" in cfg for cfg in nmv._COL_CONFIG.values()))
        check("모든 열이 명시 width 보유",
              all("width" in cfg for cfg in nmv._COL_CONFIG.values()))
        # 값/헤더 실폭(2026-08-19 실렌더 계측, 셀·헤더 12px Pretendard: 한글 11.04 /
        # 숫자 7.2 px per 자)에 셀 크롬 16px(패딩 7+7 및 좌우 1px 보더)을 더해 4의
        # 배수로 올린 값. §1.2 개정으로 표가 14.5px→12px 이 되어 전면 재역산했다.
        check("열 폭 = 값 최대 길이 역산값",
              {c: cfg["width"] for c, cfg in nmv._COL_CONFIG.items()} == {
                  "보고번호": 88,    # 70.4(YYYYMM-NNNN 11자) + 16
                  "발생일": 80,     # 61.6(ISO 10자) + 16
                  "원인": 64,       # 44.2('미끄러짐' 4자) + 16
                  "작업명": 144,    # 12자분(132) + 16 · 자유 입력이라 가정
                  "사고내용": 400,  # 자유 서술 — 비중 최대(2026-08-19 상향), 넘치면 말줄임
                  "소속": 116,      # 96.2('PET생산부(원료실)') + 16
                  "신고자": 64,     # 성명 4자 여유
                  "등급": 40,       # 값 1자라 헤더('등급' 22.1) + 16 이 폭을 정한다
                  "상태": 64,       # 44.2('평가완료' 4자) + 16
              })
        check("폭 비율 합 1060(fitGridWidth 가 이 비율로 남는 폭을 나눈다)",
              sum(cfg["width"] for cfg in nmv._COL_CONFIG.values()) == 1060)
        check("등급만 maxWidth 로 묶음(값 1자라 비례 확대 무의미)",
              nmv._COL_CONFIG["등급"].get("maxWidth") == 64
              and not any("maxWidth" in c for k, c in nmv._COL_CONFIG.items() if k != "등급"))
        check("4행 유지(입력 행수 보존)", len(out) == 4)

        row1 = out.iloc[0]
        check("정상행 보고번호", row1["보고번호"] == "NM-2026-001")
        check("정상행 작업명", row1["작업명"] == "배관 청소")
        check("정상행 신고자: 사번→이름 매핑", row1["신고자"] == "김철수")
        check("정상행 소속: 코드→부서명 매핑", row1["소속"] == "PET1부")
        check("정상행 발생일", row1["발생일"] == "2026-07-01")
        check("정상행 등급(확정 등급 값)", row1["등급"] == "A")
        check("정상행 상태: EVALUATED→평가완료", row1["상태"] == "평가완료")
        check("정상행 원인: SLIP→미끄러짐", row1["원인"] == "미끄러짐")

        row2 = out.iloc[1]
        check("빈값행 보고번호 유지(폴백 없음)", row2["보고번호"] == "NM-2026-002")
        check("빈값행 작업명 빈 문자열 유지(폴백 없음)", row2["작업명"] == "")
        check("빈값행 신고자 '-' 폴백", row2["신고자"] == "-")
        check("빈값행 소속 '-' 폴백", row2["소속"] == "-")
        check("빈값행 발생일 '-' 폴백", row2["발생일"] == "-")
        check("빈값행 등급 '-' 폴백", row2["등급"] == "-")
        # 2026-08-14 6화면 상태 어휘 통일: SUBMITTED 표기는 '제출'이 아니라 '제출됨'
        # (DESIGN §2 상태 배지 표기 = 평가·개선조치·내 아차사고와 동일).
        check("빈값행 상태(SUBMITTED→제출됨, '-' 아님)", row2["상태"] == "제출됨")
        check("빈값행 원인 '-' 폴백(빈 cause_code)", row2["원인"] == "-")

        row3 = out.iloc[2]
        check("미매핑 사번 → 원문 그대로", row3["신고자"] == "9999")
        check("미매핑 부서코드 → 원문 그대로", row3["소속"] == "ZZZ")
        check("미매핑 상태코드 → 원문 그대로", row3["상태"] == "WEIRD_STATUS")
        check("미매핑 원인코드 → 원문 그대로", row3["원인"] == "WEIRD_CAUSE")

        row4 = out.iloc[3]
        check("None 신고자 → 정리 후 '-' 폴백", row4["신고자"] == "-")
        check("None 소속 → 정리 후 '-' 폴백", row4["소속"] == "-")
        check("None 발생일 → 정리 후 '-' 폴백", row4["발생일"] == "-")
        check("None 등급 → 정리 후 '-' 폴백", row4["등급"] == "-")
        check("None 원인 → 정리 후 '-' 폴백", row4["원인"] == "-")
        check("None 아닌 상태(CLOSED→종결) 정상 매핑", row4["상태"] == "종결")

        # 빈 원본(0행): 예외는 없으나 현재 구현은 rows=[] 인 채 pd.DataFrame(rows) 를
        # 만들므로 0행뿐 아니라 0열(스키마 소실)이 된다 — 인벤토리에 명시되지 않은
        # 발견 사항(플래그): 구조 이관 시 "빈 결과도 9열 스키마 유지"를 새 기대로
        # 삼는다면 이건 현재 동작 대비 개선이지 회귀가 아니다. 이 테스트는 회귀
        # 방지가 목적이므로 현재의 실제 동작(0행·0열)을 그대로 고정한다.
        empty_out = nmv._to_display(pd.DataFrame(columns=list(raw.columns)))
        check(
            "빈 입력 → 예외 없이 0행(현재 구현은 열 스키마도 소실 — 플래그, 조회 시 df.empty"
            " 로 먼저 걸러지므로 render 경로에선 이 경우가 실도달하지 않음)",
            len(empty_out) == 0 and len(empty_out.columns) == 0,
        )
    finally:
        db.get_users = orig_get_users  # type: ignore[assignment]
        db.get_departments = orig_get_departments  # type: ignore[assignment]


def test_vocabulary_and_status_effect() -> None:
    """§3.6 어휘 통일 · §7.2-1b 제안등급 폐기 · §3.3 상태의 결과 표기 · §2 영역 순서."""
    print("어휘(§3.6) · 제안등급 폐기(§7.2-1b) · 상태의 결과(§3.3) · 골격(§2)")
    # ── §3.6: IN_REVIEW 한글 라벨은 '평가중'(코드값 IN_REVIEW 는 불변) ──
    check("IN_REVIEW 라벨 = '평가중'", nmv._STATUS_LABEL["IN_REVIEW"] == "평가중")
    check("'검토중' 라벨 폐기", "검토중" not in set(nmv._STATUS_LABEL.values()))
    check("영문 코드값 불변(IN_REVIEW 키 유지)", "IN_REVIEW" in nmv._STATUS_LABEL)
    check("상태 5종 전부 색 보유", set(nmv._STATUS_COLOR) == set(nmv._STATUS_LABEL))

    # ── §3.3: 상태마다 '무엇이 막히고 열리는지' 한 줄이 있고, 상세 배지 옆에 렌더된다 ──
    check("모든 상태에 결과 표기 존재(_STATUS_EFFECT)",
          set(nmv._STATUS_EFFECT) == set(nmv._STATUS_LABEL)
          and all(str(v).strip() for v in nmv._STATUS_EFFECT.values()))
    detail_src = inspect.getsource(nmv._render_result_detail)
    check("상세 상태 배지 옆에 결과 표기 렌더(§3.3)",
          "_STATUS_EFFECT" in detail_src and "status_badge" in detail_src)
    check("PDF 출력에도 같은 결과 표기 전달", "status_effect=" in detail_src)

    # ── §7.2-1b: 제안등급은 표시·변환 어디에도 남지 않는다 ──
    check("표시 변환에 proposed_grade 미참조",
          "proposed_grade" not in inspect.getsource(nmv._to_display))
    check("상세 렌더에 proposed_grade 미참조", "proposed_grade" not in detail_src)
    check("상세 메타 라벨은 정본 '평가 등급'",
          '"평가 등급"' in detail_src and '"확정등급"' not in detail_src)

    # 한글 라벨에 모노·자간 금지 — IBM Plex Mono 에 한글 글리프가 없어 글자마다 폴백으로
    # 떨어지고 letter-spacing 이 이중으로 적용돼 '신 고 자'처럼 벌어진다(2026-08-18 실렌더).
    meta_html = nmv._meta_cell("신고자", "1001")
    check("한글 메타 라벨에 모노 미적용", "monospace" not in meta_html)
    check("한글 메타 라벨에 letter-spacing 미적용", "letter-spacing" not in meta_html)
    check("라벨 크기·색은 불변(10.5px / #6b665d)",
          "font-size:10.5px" in meta_html and nmv._META_FAINT in meta_html)
    check("사진 오버라인도 모노·자간 제거(한글 '사진')",
          "monospace" not in inspect.getsource(nmv._photo_overline).split('"""')[-1]
          and "letter-spacing" not in inspect.getsource(nmv._photo_overline).split('"""')[-1])
    # §1.2(2026-08-19): 모노 서체 폐지 — 글꼴은 Pretendard 하나다. 자릿수 정렬은
    # tabular-nums 가 담당하므로 보고번호에 별도 서식을 두지 않는다.
    check("보고번호 셀에 모노 서식 없음(§1.2 모노 폐지)",
          "Mono" not in str(nmv._COL_CONFIG["보고번호"].get("cellStyle", {})))

    # ── §3.6: 조회 조건 라벨도 정본(폭 140 — 축약 불필요) ──
    cond_src = inspect.getsource(nmv._collect_conditions)
    check("등급 필터 라벨 = '평가 등급'", 'label="평가 등급"' in cond_src)
    check("'확정등급' 라벨 폐기", "확정등급" not in cond_src)
    ALL = workspace.ALL
    check("필터 key·파사드 필드(코드값)는 불변",
          'key="grade"' in cond_src
          and nmv._facade_filters({"dept": ALL, "grade": "A", "status": ALL, "cause": ALL})
          == {"confirmed_grade": "A"})

    # ── §2 READ_VIEW 골격: 제목 → 조회 조건 → (지표) → 표 ──
    render_src = inspect.getsource(nmv.render)
    check("영역 순서: screen_frame → condition_panel → metric_strip → select_grid",
          render_src.index("erp.screen_frame")
          < render_src.index("_collect_conditions")
          < render_src.index("erp.metric_strip")
          < render_src.index("erp.select_grid"))
    check("제목 직후 지표 슬롯(deferred container) 제거", "metric_slot" not in render_src)


def test_has_filters() -> None:
    print("_has_filters")
    ALL = workspace.ALL
    default_q = {
        "dept": ALL, "grade": ALL, "status": ALL, "cause": ALL,
        "period_on": False, "date_from": "", "date_to": "",
    }
    check("전부 기본값 → False", nmv._has_filters(default_q) is False)
    check("dept 만 지정 → True", nmv._has_filters({**default_q, "dept": "PET1"}) is True)
    check("grade 만 지정 → True", nmv._has_filters({**default_q, "grade": "A"}) is True)
    check("status 만 지정 → True", nmv._has_filters({**default_q, "status": "SUBMITTED"}) is True)
    check("cause 만 지정 → True", nmv._has_filters({**default_q, "cause": "JAM"}) is True)
    check("period_on 만 True → True", nmv._has_filters({**default_q, "period_on": True}) is True)
    check(
        "모두 지정 → True",
        nmv._has_filters({
            "dept": "PET1", "grade": "A", "status": "SUBMITTED", "cause": "JAM",
            "period_on": True, "date_from": "2026-01-01", "date_to": "2026-01-31",
        }) is True,
    )


def test_facade_filters() -> None:
    print("_facade_filters")
    ALL = workspace.ALL
    default_q = {
        "dept": ALL, "grade": ALL, "status": ALL, "cause": ALL,
        "period_on": False, "date_from": "", "date_to": "",
    }
    check("전부 기본값 → 빈 dict", nmv._facade_filters(default_q) == {})

    check(
        "dept → dept_code",
        nmv._facade_filters({**default_q, "dept": "PET1"}) == {"dept_code": "PET1"},
    )
    check(
        "grade → confirmed_grade",
        nmv._facade_filters({**default_q, "grade": "A"}) == {"confirmed_grade": "A"},
    )
    check(
        "status → status(코드 그대로)",
        nmv._facade_filters({**default_q, "status": "SUBMITTED"}) == {"status": "SUBMITTED"},
    )
    check(
        "cause → cause_code",
        nmv._facade_filters({**default_q, "cause": "JAM"}) == {"cause_code": "JAM"},
    )
    check(
        "date_from/date_to → 그대로 통과",
        nmv._facade_filters({**default_q, "date_from": "2026-01-01", "date_to": "2026-01-31"})
        == {"date_from": "2026-01-01", "date_to": "2026-01-31"},
    )
    check(
        "빈 date_from/date_to는 제외",
        "date_from" not in nmv._facade_filters(default_q)
        and "date_to" not in nmv._facade_filters(default_q),
    )
    check(
        "복합: dept+grade+status+cause+기간 전부 결합",
        nmv._facade_filters({
            "dept": "PET1", "grade": "A", "status": "SUBMITTED", "cause": "JAM",
            "period_on": True, "date_from": "2026-01-01", "date_to": "2026-01-31",
        }) == {
            "dept_code": "PET1", "confirmed_grade": "A", "status": "SUBMITTED",
            "cause_code": "JAM", "date_from": "2026-01-01", "date_to": "2026-01-31",
        },
    )


def main() -> int:
    for test in (
        test_scope_for,
        test_to_display,
        test_vocabulary_and_status_effect,
        test_has_filters,
        test_facade_filters,
    ):
        test()
    print(f"\nALL PASSED ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
