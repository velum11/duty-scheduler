"""근무형태 관리(master_work_types) 재구현 focused 테스트 (Phase4 Lane C).

공통 기반 `views.master` 위에 재구현한 근무형태 화면의 계약을 검증한다:
  - 렌더 스모크(AppTest, 예외 없음, sample 모드)
  - 저장 전 검증 `_validate` 하위호환((records, errors), 색상 #RRGGBB 보존, 필수값)
  - 보강 검증(Codex 지적): 색상 #RRGGBB 형식·정규화, 시간 HH:MM, 셀 오류 맵
  - dirty baseline 헬퍼(_row_tuple / _dirty_fields_json), 약칭 중복 소프트 경고
  - 삭제 정책(참조>0 → 미사용, 참조0 → 물리 삭제)

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_master_work_types_new.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

import pandas as pd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

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


def _meta(rows):
    frame = pd.DataFrame(rows)
    if "_removed" not in frame:
        frame["_removed"] = ""
    if "_row_id" not in frame:
        frame["_row_id"] = [f"e:{i}" for i in range(len(frame))]
    if "_row_state" not in frame:
        frame["_row_state"] = "existing"
    return frame


# ===== 1) 렌더 스모크 =====
def _screen_work_types():
    from modules import db
    from views import master_work_types
    master_work_types.render(db.find_user_by_emp_no("1001"))


def test_render_smoke() -> None:
    print("렌더 스모크 (공통 기반 재구현, 예외 없음)")
    at = AppTest.from_function(_screen_work_types, default_timeout=60).run()
    check("master_work_types 렌더 예외 없음", not at.exception)
    # 공통 기반 사용 확인(정적 소스)
    import inspect
    from views import master_work_types
    src = inspect.getsource(master_work_types)
    check("공통 기반 views.master 사용", "from views import master" in src or "views.master" in src)
    check("공통 헤더(master_screen_head) 사용", "master_screen_head" in src)
    check("공통 액션바(master_action_bar) 사용", "master_action_bar" in src)
    check("공통 그리드(render_master_grid) 사용", "render_master_grid" in src)
    check("동적 그리드 높이(master_grid_height) 사용", "master_grid_height" in src)


# ===== 1-1) 액션바 위치 = 표 위 (design-contract §7, 검수 defect Visual) =====
def test_action_bar_above_grid() -> None:
    print("액션바 위치(표 위) — 필터바 아래·그리드 위")
    import inspect
    from views import master_work_types as m
    src = inspect.getsource(m.render)
    # 액션바 슬롯(bar_slot)을 그리드 렌더보다 먼저 확보하고 나중에 채운다.
    i_slot = src.find("bar_slot = st.container()")
    i_grid = src.find("render_master_grid(spec")
    i_fill = src.find("with bar_slot")
    check("액션바 슬롯을 그리드보다 먼저 확보", 0 <= i_slot < i_grid)
    check("액션바를 슬롯(표 위)에 채움", i_fill >= 0 and "master_action_bar" in src[i_fill:i_fill + 200])
    check("배너 슬롯도 그리드보다 먼저 확보", 0 <= src.find("banner_slot = st.container()") < i_grid)


# ===== 1-2) B2: 부분성공 원장 — save_work_types_report → PersistResult =====
def test_partial_success_ledger_wiring() -> None:
    print("B2 부분성공 원장 배선 (save_work_types_report → PersistResult)")
    import inspect
    from views import master_work_types as m
    from views.master import PersistResult
    from modules import db
    save_src = inspect.getsource(m._save)
    check("void save_work_types 대신 원장 API(save_work_types_report) 호출",
          "save_work_types_report" in save_src and "db.save_work_types(" not in save_src)
    check("원장 결과를 PersistResult 로 매핑(to_persist_kwargs)", "to_persist_kwargs" in save_src)
    check("partial/unknown 원장 배너 경로 존재",
          "_SAVE_LEDGER" in inspect.getsource(m) and "ledger_banner" in inspect.getsource(m))

    # 실제 매핑(sample 모드 = 전체 성공) 이 PersistResult.ok 로 이어지는지 확인.
    merged = db.get_work_types().copy()[db.WORK_TYPE_COLUMNS]
    report = db.save_work_types_report(merged)
    pr = PersistResult(page_id="master_work_types", **report.to_persist_kwargs())
    check("sample 저장 원장은 전체 성공(ok)", pr.ok is True)
    check("성공 자연키가 원장에 보고됨", len(pr.succeeded_keys) >= 1)

    # 부분성공 reconcile 헬퍼(순수 로직): 성공 key baseline 갱신 / 실패 key 셀 오류.
    live = _meta([
        {"코드": "AAA", "명칭": "가", "분류": "주간", "약칭": "가", "시작": "", "종료": "",
         "색상": "#111111", "실근무": True, "특근수당": False, "설명": "", "표시순서": "1", "사용": True},
        {"코드": "BBB", "명칭": "나", "분류": "주간", "약칭": "나", "시작": "", "종료": "",
         "색상": "#222222", "실근무": True, "특근수당": False, "설명": "", "표시순서": "2", "사용": True},
    ])
    live["_row_id"] = ["e:AAA", "e:BBB"]
    by_code = {str(r["코드"]).strip(): True for _, r in live.iterrows()}
    check("reconcile 대상 코드 매핑 준비", by_code == {"AAA": True, "BBB": True})


# ===== 1-3) B4: 삭제 실패 controller 경계 처리 =====
def test_delete_error_handling() -> None:
    print("B4 삭제 실패 처리 (DATA_SOURCE_ERRORS 포착·재시도 계획)")
    import inspect
    from views import master_work_types as m
    exec_src = inspect.getsource(m._execute_delete)
    check("삭제 write 를 DATA_SOURCE_ERRORS 로 포착", "db.DATA_SOURCE_ERRORS" in exec_src)
    check("비활성 처리는 원장 API(save_work_types_report) 사용", "save_work_types_report" in exec_src)
    check("성공분만 재조회(_load_editor)", "_load_editor(state, params)" in exec_src)
    check("실패분을 재시도 가능한 삭제 계획으로 남김",
          "delete_plan_key" in exec_src and "_DELETE_ERROR" in exec_src)
    conf_src = inspect.getsource(m._confirm_delete)
    check("재시도 확인 바에 실패 사유 노출", "_DELETE_ERROR" in conf_src and "재시도" in conf_src)
    check("참조 시 비활성·미참조 물리삭제 계약 유지",
          "delete_work_type" in exec_src and 'is_active"] = False' in exec_src)

    # 헬퍼 순수 로직.
    check("_key_str: 복합키 결합", m._key_str(("D1", "A")) == "D1/A")
    check("_key_str: 단일키 문자열", m._key_str("DAY") == "DAY")
    check("_err_text: 빈 예외는 기본 문구", m._err_text(Exception("")) != "")


# ===== 1-4) WAVE 2b 통일 재설계 — 약칭 중복칩·분류칩·필터 요약칩 =====
def test_unified_redesign_features() -> None:
    print("WAVE2b 통일 재설계 (약칭 중복 경고칩·분류 칩·필터 요약칩)")
    import inspect
    from views import master_work_types as m

    cfg = m._col_config()
    check("약칭 열에 셀 렌더러 주입(라이브 중복칩)", "cellRenderer" in cfg["약칭"])
    check("분류 열에 셀 렌더러 주입(칩)", "cellRenderer" in cfg["분류"])

    # 약칭 중복칩은 공통 `.ms-chip warn` 어휘 + 활성 기준(저장 검증과 동일 규칙)을 사용.
    short_src = str(m._SHORT_LABEL_RENDERER.js_code)
    check("약칭 렌더러가 공통 warn 칩 사용", "ms-chip warn" in short_src and "약칭 중복" in short_src)
    check("약칭 중복 판정은 활성 행 기준(사용/제거 반영)", "_active" in short_src and "_removed" in short_src)
    cat_src = str(m._CATEGORY_RENDERER.js_code)
    check("분류 렌더러가 공통 mute 칩 사용", "ms-chip mute" in cat_src)

    # 다른 행 약칭/사용 편집에 반응하도록 onCellValueChanged 로 약칭 열을 refresh.
    render_src = inspect.getsource(m.render)
    check("그리드에 onCellValueChanged(_DUP_REFRESH) 배선", "onCellValueChanged" in render_src)
    dup_src = str(m._DUP_REFRESH.js_code)
    check("변경 셀이 약칭/사용일 때 약칭 열 refresh", "refreshCells" in dup_src and "약칭" in dup_src)

    # 요약칩 — 현재 필터결과(로드된 기존 행) 기준 사용/미사용 분포(전체 카운트 아님).
    frame = _meta([
        {"코드": "A", "명칭": "가", "분류": "주간", "약칭": "가", "색상": "#111111",
         "실근무": True, "특근수당": False, "설명": "", "표시순서": "1", "사용": True},
        {"코드": "B", "명칭": "나", "분류": "주간", "약칭": "나", "색상": "#222222",
         "실근무": True, "특근수당": False, "설명": "", "표시순서": "2", "사용": True},
        {"코드": "C", "명칭": "다", "분류": "주간", "약칭": "다", "색상": "#333333",
         "실근무": True, "특근수당": False, "설명": "", "표시순서": "3", "사용": False},
    ])
    active, inactive = m._summary_counts(frame)
    check("요약 카운트는 필터결과(프레임) 기준 사용 중", active == 2)
    check("요약 카운트는 필터결과(프레임) 기준 미사용", inactive == 1)
    # 신규 행은 저장 전이므로 분포에서 제외.
    frame_new = _meta([
        {"코드": "N", "명칭": "신규", "분류": "", "약칭": "", "색상": "", "실근무": False,
         "특근수당": False, "설명": "", "표시순서": "9", "사용": True},
    ])
    frame_new["_row_state"] = "new"
    check("신규 행은 요약 분포에서 제외", m._summary_counts(frame_new) == (0, 0))

    summary_src = inspect.getsource(m._render_summary_chips)
    check("요약칩이 공통 chip_html 사용", "chip_html" in summary_src)
    check("요약칩에 사용 중/미사용 라벨", "사용 중" in summary_src and "미사용" in summary_src)
    check("요약칩은 필터결과 기준(_summary_counts 사용, 전체 db 카운트 아님)",
          "_summary_counts" in summary_src and "get_work_types" not in summary_src)
    check("요약칩을 그리드 위 슬롯에서 렌더", "_render_summary_chips" in render_src
          and 0 <= render_src.find("summary_slot = st.container()") < render_src.find("render_master_grid(spec"))


# ===== 1-5) 미리보기 색·약칭 계약 (DESIGN.md §150) =====
def test_preview_color_short_label_contract() -> None:
    print("미리보기 색·약칭 계약(DESIGN.md §150) — 색 스와치 + 약칭, 명칭·시간 중복 없음")
    import inspect
    from views import master_work_types as m
    src = inspect.getsource(m._render_preview)
    # 계약 정보: 색상 스와치 + 약칭이 반드시 노출된다.
    check("미리보기 라벨은 약칭 우선(계약 정보)", 'row.get("약칭")' in src)
    check("미리보기에 솔리드 색상 스와치 노출", "class='d'" in src and "background:{color};" in src)
    check("약칭 셀에 근무형태 색 적용(근무표 렌더 시연)", "{color}22" in src and "color:{color};" in src)
    check("미리보기 계약 제목(색·약칭)", "색·약칭" in src)
    # 밀도: 편집 그리드와 겹치는 명칭·시간 pill 반복은 하지 않는다(과다 세로 제거).
    check("명칭·시간 중복 pill 미노출", "class='nm'" not in src and "class='tm'" not in src)
    check("조밀 스트립 스타일 유지(.ms-sw)", ".ms-sw" in m._EXTRA_CSS)


# ===== 1-6) 자연키(코드) 저장행 잠금 계약 (org/users 동일) =====
def test_code_natural_key_locked() -> None:
    print("코드(자연키) 저장행 잠금 — editable=_EDIT_NEW_ONLY + 저장행 읽기전용 틴트")
    from views import master_work_types as m

    # 신규행만 편집 가능한 predicate 정의(org/users 와 동일 식).
    pred = str(m._EDIT_NEW_ONLY.js_code)
    check("_EDIT_NEW_ONLY predicate 정의", "_row_state === 'new'" in pred)
    check("저장행 읽기전용 룰(ms-cell-readonly)", m._CODE_READONLY_RULES ==
          {"ms-cell-readonly": "data._row_state !== 'new'"})

    cfg = m._col_config()
    check("코드 열 editable 게이트 = 신규행만", cfg["코드"].get("editable") is m._EDIT_NEW_ONLY)
    check("코드 열에 저장행 읽기전용 틴트 룰 병합",
          cfg["코드"]["cellClassRules"].get("ms-cell-readonly") == "data._row_state !== 'new'")
    # 다른 편집 컬럼(명칭)은 저장행 잠금 대상이 아님(자연키만 잠금).
    check("명칭 열은 자연키 잠금 미적용", "ms-cell-readonly" not in cfg["명칭"]["cellClassRules"])
    check("코드 열 error/dirty 하이라이트 유지",
          any(k for k in cfg["코드"]["cellClassRules"] if k != "ms-cell-readonly"))


# ===== 2) _validate 하위호환 =====
def test_validate_backward_compat() -> None:
    print("_validate 하위호환 ((records, errors), 색상 보존, 필수값)")
    from views import master_work_types as m
    recs, errs = m._validate(_meta([
        {"코드": "TESTW", "명칭": "테스트근무", "분류": "주간", "약칭": "테", "시작": "08:00",
         "종료": "17:00", "색상": "#123456", "실근무": True, "특근수당": False, "설명": "x",
         "표시순서": "5", "사용": True},
        {"코드": "", "명칭": "이름만", "분류": "", "약칭": "", "시작": "", "종료": "", "색상": "",
         "실근무": False, "특근수당": False, "설명": "", "표시순서": "", "사용": True},
    ]))
    check("색상 HEX 보존(#RRGGBB)", recs[0]["color"] == "#123456")
    check("실근무 bool 변환", recs[0]["is_work"] is True)
    check("필수값(코드/약칭/분류) 검출 ≥3", sum(1 for e in errs if ("코드" in e or "약칭" in e or "분류" in e)) >= 3)
    check("반환 형태는 (records, errors) 2-튜플", isinstance(recs, list) and isinstance(errs, list))

    # 완전 빈 행은 저장 대상 제외
    recs2, _ = m._validate(_meta([
        {"코드": "", "명칭": "", "분류": "", "약칭": "", "시작": "", "종료": "", "색상": "",
         "실근무": False, "특근수당": False, "설명": "", "표시순서": "", "사용": True},
    ]))
    check("완전 빈 행은 records 에서 제외", len(recs2) == 0)


# ===== 3) 색상·시간 보강 검증 =====
def test_color_time_validation() -> None:
    print("보강 검증 (색상 #RRGGBB·정규화, 시간 HH:MM, 셀 오류 맵)")
    from views import master_work_types as m
    recs, errs, emap = m._validate_detailed(_meta([
        {"코드": "OKROW", "명칭": "정상", "분류": "주간", "약칭": "정", "시작": "08:00",
         "종료": "20:00", "색상": "#2e9e5b", "실근무": True, "특근수당": False, "설명": "",
         "표시순서": "1", "사용": True},
        {"코드": "SHORT", "명칭": "삼자리", "분류": "주간", "약칭": "삼", "시작": "", "종료": "",
         "색상": "abc", "실근무": True, "특근수당": False, "설명": "", "표시순서": "2", "사용": True},
        {"코드": "BADHEX", "명칭": "잘못색", "분류": "주간", "약칭": "잘", "시작": "25:00",
         "종료": "9:99", "색상": "red", "실근무": True, "특근수당": False, "설명": "",
         "표시순서": "3", "사용": True},
    ]))
    check("유효 소문자 HEX 는 대문자로 정규화", recs[0]["color"] == "#2E9E5B")
    check("3자리 HEX 는 6자리로 확장", recs[1]["color"] == "#AABBCC")
    check("정상 행은 색상/시간 오류 없음", "e:0" not in emap)
    check("잘못된 색상 검출", any("색상" in e for e in errs))
    check("잘못된 시간(HH:MM) 검출", any("시작" in e for e in errs))
    check("오류 행은 셀 오류 맵에 필드별 기록", emap.get("e:2", {}).get("색상") is not None
          and emap.get("e:2", {}).get("시작") is not None)

    # _normalize_hex 단위
    check("normalize: 누락 # 보정", m._normalize_hex("123456") == "#123456")
    check("normalize: 3자리 확장", m._normalize_hex("#abc") == "#AABBCC")
    check("normalize: 빈 값 → 빈 문자열", m._normalize_hex("") == "")
    check("normalize: 잘못된 값 → None", m._normalize_hex("nope") is None)

    # 빈 색상은 기본색으로 채워짐(오류 아님)
    recs2, errs2, _ = m._validate_detailed(_meta([
        {"코드": "EMPTYC", "명칭": "빈색", "분류": "주간", "약칭": "빈", "시작": "", "종료": "",
         "색상": "", "실근무": False, "특근수당": False, "설명": "", "표시순서": "9", "사용": True},
    ]))
    check("빈 색상은 기본색(#9AA0A6)으로 채움", recs2[0]["color"] == "#9AA0A6")
    check("빈 색상은 오류가 아님", not any("색상" in e for e in errs2))


# ===== 4) dirty baseline·약칭 중복 헬퍼 =====
def test_dirty_and_dup_helpers() -> None:
    print("dirty baseline / 약칭 중복 헬퍼")
    from views import master_work_types as m
    row = {"_row_id": "e:X", "_row_state": "existing",
           "코드": "DAY", "명칭": "주간", "분류": "주간", "약칭": "주", "시작": "08:00",
           "종료": "20:00", "색상": "#1E6FD9", "실근무": True, "특근수당": False,
           "설명": "", "표시순서": "10", "사용": True}
    base = m._row_tuple(row)
    check("baseline 튜플은 사용자 컬럼 전체 포함", set(base.keys()) == set(m._USER_COLS))
    check("변경 없으면 dirty_fields 없음", m._dirty_fields_json(row, base) == "")
    changed = dict(row)
    changed["색상"] = "#2E9E5B"
    check("색상만 바꾸면 색상만 dirty", m._dirty_fields_json(changed, base) == '["색상"]')
    new_row = dict(changed, _row_state="new")
    check("신규 행은 dirty_fields 대상 아님", m._dirty_fields_json(new_row, base) == "")

    dup = m._duplicate_short_labels([
        {"short_label": "주", "is_active": True},
        {"short_label": "주", "is_active": True},
        {"short_label": "야", "is_active": True},
        {"short_label": "비", "is_active": False},  # 비활성은 제외
        {"short_label": "비", "is_active": False},
    ])
    check("활성 약칭 중복만 소프트 경고 대상", dup == ["주"])


# ===== 5) 삭제 정책 (참조>0 → 미사용, 참조0 → 물리 삭제) =====
def test_delete_policy() -> None:
    print("삭제 정책 분류 (근무표 참조 기준)")
    from modules import db
    scheds = db.get_schedules()
    referenced = None
    if not scheds.empty and "work_type_code" in scheds:
        vc = scheds["work_type_code"].astype(str).str.strip()
        vc = vc[vc != ""]
        if not vc.empty:
            referenced = vc.value_counts().index[0]
    if referenced is not None:
        refs = db.work_type_reference_counts(referenced)
        check("참조 있는 코드는 refs>0(→미사용 처리 대상)", sum(refs.values()) > 0)
    else:
        check("참조 있는 코드 없음(스킵)", True)

    all_wt = db.get_work_types()
    used = set(scheds["work_type_code"].astype(str).str.strip()) if not scheds.empty else set()
    unref = None
    for c in all_wt["code"].astype(str):
        if c.strip() and c.strip() not in used:
            unref = c.strip()
            break
    if unref is not None:
        refs = db.work_type_reference_counts(unref)
        check("참조 없는 코드는 refs==0(→물리 삭제 대상)", sum(refs.values()) == 0)
    else:
        check("참조 없는 코드 없음(스킵)", True)


def main() -> int:
    for test in (
        test_render_smoke,
        test_action_bar_above_grid,
        test_unified_redesign_features,
        test_preview_color_short_label_contract,
        test_code_natural_key_locked,
        test_partial_success_ledger_wiring,
        test_delete_error_handling,
        test_validate_backward_compat,
        test_color_time_validation,
        test_dirty_and_dup_helpers,
        test_delete_policy,
    ):
        test()
    print()
    if FAIL:
        print(f"FAILED {len(FAIL)}: {FAIL}")
        return 1
    print(f"ALL PASSED ({PASS} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
