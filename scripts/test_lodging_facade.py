"""숙소 예약 파사드 계약 테스트 — modules/db.py (sample 모드, 실DB 미접속·쓰기 없음).

무엇을 고정하는가
-----------------
- **승인권자 = 숙소관리 담당자만**(2026-08-20 결정). role 은 판정에 들어가지 않으며,
  세션 dict 의 담당 클레임을 위조해도 파사드가 사번으로 **권위 재조회**해 막는다.
- 신원(신청자·소속)·상태·예약번호는 payload 가 아니라 **서버측에서 확정**한다.
- 겹침(중복 예약)은 신청·수정 시점에 거부하고, 반개구간이라 같은 날 교대는 허용한다.
- 성명·사번 등 신원은 **담당자와 본인에게만** 내려간다(파사드 마스킹 — 화면이 가리는
  것이 아니라 파사드가 주지 않는다).
- sample 시드는 실제 sample 사용자(1001~)·부서(PET1/PET2)를 쓴다.

순수 도메인 함수(검증·전이·중복 판정) 자체는 scripts/test_new_screens.py 가 소유한다.

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_lodging_facade.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

from streamlit.testing.v1 import AppTest  # noqa: E402

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS
    if cond:
        PASS += 1
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name}" + (f" :: {detail}" if detail else ""))


def _probe():  # noqa: C901 - 계약 시나리오 한 벌(순서 의존)
    import re
    from datetime import date, timedelta

    import streamlit as st

    from modules import db
    from modules import lodging_data as ld

    out: dict = {}

    def day(offset: int) -> str:
        return (date.today() + timedelta(days=offset)).isoformat()

    # 담당 권한은 sample 시드(1001)로 부여돼 있고, 나머지는 담당이 없다.
    OFFICER = {"emp_no": "1001", "name": "김관리", "role": "ADMIN", "dept_code": "PET1",
               "capabilities": ["LODGING_OFFICER"]}
    MGR = {"emp_no": "1002", "name": "이책임", "role": "MANAGER", "dept_code": "PET1"}
    OWNER = {"emp_no": "1003", "name": "박근무", "role": "USER", "dept_code": "PET1"}
    OTHER = {"emp_no": "1004", "name": "최근무", "role": "USER", "dept_code": "PET1"}

    out["probe"] = db.lodging_schema_probe()
    out["ready"] = db.lodging_schema_ready()

    # ── 시드 ────────────────────────────────────────────────────────────────
    seed = db.get_lodging_reservations(current_user=OFFICER).to_dict("records")
    out["seed_count"] = len(seed)
    out["seed_emps"] = sorted({r["applicant_emp_no"] for r in seed})
    out["seed_depts"] = sorted({r["dept_code"] for r in seed})
    out["seed_names"] = sorted({r["applicant_name"] for r in seed if r["applicant_name"]})
    out["seed_no_format"] = all(
        re.fullmatch(r"LDG-\d{6}-\d{3}", r["request_no"]) for r in seed
    )
    out["seed_statuses"] = sorted({r["status"] for r in seed})
    out["lodging_codes"] = sorted(db.lodging_map())
    out["lodging_names"] = sorted(
        v["lodging_name"] for v in db.lodging_map().values()
    )

    # ── 서버측 마스킹 ───────────────────────────────────────────────────────
    as_third = db.get_lodging_reservations(current_user=MGR).to_dict("records")
    out["mask_third_party"] = all(
        not r["applicant_emp_no"] and not r["applicant_name"] and not r["dept_code"]
        and not r["decided_by"] and not r["decision_comment"]
        for r in as_third
    )
    out["mask_keeps_schedule"] = all(
        r["check_in"] and r["check_out"] and r["status"] and r["lodging_name"]
        for r in as_third
    )
    as_owner = db.get_lodging_reservations(current_user=OWNER).to_dict("records")
    own = [r for r in as_owner if r["request_no"] in
           {s["request_no"] for s in seed if s["applicant_emp_no"] == "1003"}]
    others = [r for r in as_owner if r not in own]
    out["mask_owner_sees_own"] = bool(own) and all(r["applicant_emp_no"] == "1003" for r in own)
    out["mask_owner_not_others"] = all(not r["applicant_name"] for r in others)
    out["mask_anonymous_view"] = all(
        not r["applicant_name"]
        for r in db.get_lodging_reservations().to_dict("records")
    )

    # ── 신청: 신원·상태·번호는 서버 확정 ───────────────────────────────────
    created = db.create_lodging_reservation(
        {"lodging_code": "TAEAN", "check_in": day(40), "check_out": day(42),
         # 아래 위조 필드는 전부 무시되어야 한다.
         "applicant_emp_no": "1001", "dept_code": "PET2", "status": "APPROVED",
         "request_no": "LDG-HACK-999", "decided_by": "1001"},
        current_user=OWNER,
    )
    out["create_identity"] = created["applicant_emp_no"]
    out["create_dept"] = created["dept_code"]
    out["create_status"] = created["status"]
    out["create_no_forged"] = created["request_no"] != "LDG-HACK-999"
    out["create_no_format"] = bool(re.fullmatch(r"LDG-\d{6}-\d{3}", created["request_no"]))
    out["create_name_joined"] = created["applicant_name"]
    created_no = created["request_no"]

    # ── 겹침 차단 / 반개구간 교대 허용 ─────────────────────────────────────
    try:
        db.create_lodging_reservation(
            {"lodging_code": "TAEAN", "check_in": day(41), "check_out": day(43)},
            current_user=OTHER,
        )
        out["overlap_blocked"] = "허용됨(결함)"
    except ld.ReservationConflict as exc:
        out["overlap_blocked"] = str(exc)
    handover = db.create_lodging_reservation(
        {"lodging_code": "TAEAN", "check_in": day(42), "check_out": day(44)},
        current_user=OTHER,
    )
    out["handover_allowed"] = handover["status"] == ld.REQUESTED
    handover_no = handover["request_no"]
    out["number_increments"] = handover_no != created_no

    # ── 수정: 본인·담당자만, 신청 상태만 ───────────────────────────────────
    try:
        db.update_lodging_reservation(
            created_no, {"check_in": day(40), "check_out": day(41)}, current_user=OTHER)
        out["update_other"] = "허용됨(결함)"
    except ValueError as exc:
        out["update_other"] = str(exc)
    try:
        db.update_lodging_reservation(
            created_no, {"check_in": day(40), "check_out": day(41)}, current_user=MGR)
        out["update_manager"] = "허용됨(결함)"
    except ValueError as exc:
        out["update_manager"] = str(exc)
    edited = db.update_lodging_reservation(
        created_no, {"check_in": day(40), "check_out": day(41)}, current_user=OWNER)
    out["update_owner"] = edited["check_out"]
    edited2 = db.update_lodging_reservation(
        created_no, {"check_in": day(40), "check_out": day(42)}, current_user=OFFICER)
    out["update_officer"] = edited2["check_out"]

    # ── 승인 인가: 담당자만(role 우회 없음, 클레임 위조 무시) ──────────────
    try:
        db.run_lodging_action(created_no, ld.ACT_APPROVE, current_user=MGR)
        out["approve_manager"] = "허용됨(결함)"
    except ValueError as exc:
        out["approve_manager"] = str(exc)
    forged = {**MGR, "capabilities": ["LODGING_OFFICER"]}   # 세션 dict 위조
    try:
        db.run_lodging_action(created_no, ld.ACT_APPROVE, current_user=forged)
        out["approve_forged_claim"] = "허용됨(결함)"
    except ValueError as exc:
        out["approve_forged_claim"] = str(exc)

    # ADMIN 이라도 담당 지정이 없으면 승인할 수 없다(담당 회수 후 확인 → 원복).
    db.set_user_capabilities("1001", [])
    try:
        db.run_lodging_action(created_no, ld.ACT_APPROVE, current_user=OFFICER)
        out["approve_admin_without_duty"] = "허용됨(결함)"
    except ValueError as exc:
        out["approve_admin_without_duty"] = str(exc)
    db.set_user_capabilities("1001", ["LODGING_OFFICER"])

    approved = db.run_lodging_action(created_no, ld.ACT_APPROVE, current_user=OFFICER)
    out["approve_officer"] = approved["status"]
    out["approve_decider"] = approved["decided_by"]
    out["approve_decider_name"] = approved["decided_by_name"]
    out["approve_decided_at"] = bool(approved["decided_at"])

    # 승인 후에는 수정 불가, 재승인 불가
    try:
        db.update_lodging_reservation(
            created_no, {"check_in": day(40), "check_out": day(41)}, current_user=OWNER)
        out["update_after_approve"] = "허용됨(결함)"
    except ValueError as exc:
        out["update_after_approve"] = str(exc)
    try:
        db.run_lodging_action(created_no, ld.ACT_APPROVE, current_user=OFFICER)
        out["reapprove"] = "허용됨(결함)"
    except ValueError as exc:
        out["reapprove"] = str(exc)

    # ── 반려 사유 필수 / 본인 취소 ─────────────────────────────────────────
    try:
        db.run_lodging_action(handover_no, ld.ACT_REJECT, current_user=OFFICER)
        out["reject_without_reason"] = "허용됨(결함)"
    except ValueError as exc:
        out["reject_without_reason"] = str(exc)
    rejected = db.run_lodging_action(
        handover_no, ld.ACT_REJECT, current_user=OFFICER, comment="업무 목적 아님")
    out["reject_status"] = rejected["status"]
    out["reject_comment"] = rejected["decision_comment"]

    mine = db.create_lodging_reservation(
        {"lodging_code": "TAEAN", "check_in": day(60), "check_out": day(61)},
        current_user=OWNER,
    )
    cancelled = db.run_lodging_action(
        mine["request_no"], ld.ACT_CANCEL, current_user=OWNER)
    out["owner_cancel"] = cancelled["status"]
    # 취소된 기간은 다시 신청할 수 있다(종결 상태는 점유가 아니다).
    reused = db.create_lodging_reservation(
        {"lodging_code": "TAEAN", "check_in": day(60), "check_out": day(61)},
        current_user=OTHER,
    )
    out["cancelled_period_reusable"] = reused["status"] == ld.REQUESTED

    # ── 조건부 저장(CAS): 읽은 상태가 바뀌었으면 덮어쓰지 않는다 ──────────
    try:
        db._sample_store_replace(created_no, {"decision_comment": "stale"},
                                 expected_status=ld.REQUESTED)   # 실제 상태는 APPROVED
        out["cas_stale"] = "허용됨(결함)"
    except ValueError as exc:
        out["cas_stale"] = str(exc)

    # ── 미인증/미상 사번은 쓰기 이전에 차단 ────────────────────────────────
    for label, actor in (("none", None), ("empty", {}), ("ghost", {"emp_no": "NOSUCH"})):
        try:
            db.create_lodging_reservation(
                {"lodging_code": "TAEAN", "check_in": day(80), "check_out": day(81)},
                current_user=actor)
            out[f"actor_{label}"] = "허용됨(결함)"
        except ValueError as exc:
            out[f"actor_{label}"] = str(exc)

    # 비활성 사용자는 행위할 수 없다(sample 사용자 2001 '퇴사자' 는 is_active=false).
    out["inactive_actor"] = ""
    try:
        db.create_lodging_reservation(
            {"lodging_code": "TAEAN", "check_in": day(85), "check_out": day(86)},
            current_user={"emp_no": "2001", "role": "USER"})
        out["inactive_actor"] = "허용됨(결함)"
    except ValueError as exc:
        out["inactive_actor"] = str(exc)

    st.session_state["_lodging_out"] = out


def main() -> None:
    at = AppTest.from_function(_probe, default_timeout=90).run()
    check("probe 예외 없음", not at.exception, str(at.exception))
    o = at.session_state["_lodging_out"] if "_lodging_out" in at.session_state else {}
    if not o:
        print("\nFAILED: probe 결과 없음")
        sys.exit(1)

    print("(a) 저장소 준비 상태·시드")
    check("sample 은 항상 READY", o.get("probe") == "READY" and o.get("ready") is True)
    check("시드는 실제 sample 사번(1003~1005)을 쓴다",
          o.get("seed_emps") == ["1003", "1004", "1005"], str(o.get("seed_emps")))
    check("시드 소속은 실제 sample 부서", set(o.get("seed_depts") or []) <= {"PET1", "PET2"},
          str(o.get("seed_depts")))
    check("성명은 저장이 아니라 조인으로 붙는다",
          o.get("seed_names") == ["박근무", "정근무", "최근무"], str(o.get("seed_names")))
    check("시드 예약번호는 채번 규칙(LDG-YYYYMM-NNN)", o.get("seed_no_format") is True)
    check("시드에 신청·승인·사용완료가 한 건씩 있다",
          o.get("seed_statuses") == ["APPROVED", "COMPLETED", "REQUESTED"],
          str(o.get("seed_statuses")))
    check("숙소 마스터는 대관령·태안 2곳",
          o.get("lodging_codes") == ["DAEGWALLYEONG", "TAEAN"]
          and o.get("lodging_names") == ["대관령", "태안"], str(o.get("lodging_codes")))

    print("(b) 신원 마스킹 · 담당자·본인에게만")
    check("제3자에게는 신청자 신원·처리 의견을 아예 내려보내지 않는다",
          o.get("mask_third_party") is True)
    check("마스킹해도 일정·상태·숙소는 보인다(캘린더 익명 표기)",
          o.get("mask_keeps_schedule") is True)
    check("본인 건은 본인에게 보인다", o.get("mask_owner_sees_own") is True)
    check("본인이라도 남의 건 신원은 안 보인다", o.get("mask_owner_not_others") is True)
    check("current_user 없는 조회는 가장 좁은 범위(fail-closed)",
          o.get("mask_anonymous_view") is True)

    print("(c) 신청 · 신원·상태·번호 서버 확정")
    check("신청자는 세션 사용자로 확정(payload 위조 무시)", o.get("create_identity") == "1003")
    check("소속도 권위 레코드에서 확정", o.get("create_dept") == "PET1")
    check("상태는 항상 REQUESTED", o.get("create_status") == "REQUESTED")
    check("예약번호는 서버 채번(위조 무시)",
          o.get("create_no_forged") is True and o.get("create_no_format") is True)
    check("성명은 읽기 시 조인", o.get("create_name_joined") == "박근무")
    check("번호는 건마다 새로 채번", o.get("number_increments") is True)

    print("(d) 중복 차단 · 신청 시점부터")
    check("겹치는 기간은 접수 거부(충돌 번호 노출)",
          "이미 예약" in str(o.get("overlap_blocked")), str(o.get("overlap_blocked")))
    check("체크아웃 당일 교대 체크인은 허용(반개구간)", o.get("handover_allowed") is True)
    check("종결(취소)된 기간은 다시 신청 가능", o.get("cancelled_period_reusable") is True)

    print("(e) 수정 · 본인·담당자, 신청 상태만")
    check("타인 수정 거부", "본인 신청 또는" in str(o.get("update_other")), str(o.get("update_other")))
    check("MANAGER 도 담당이 아니면 수정 거부",
          "본인 신청 또는" in str(o.get("update_manager")), str(o.get("update_manager")))
    check("본인 수정 반영", o.get("update_owner") is not None)
    check("담당자는 일정 정정 가능", o.get("update_officer") is not None)
    check("승인 후 수정 거부",
          "신청(REQUESTED) 상태" in str(o.get("update_after_approve")),
          str(o.get("update_after_approve")))

    print("(f) 승인 인가 · 담당자만(role 우회 없음)")
    check("MANAGER 승인 거부",
          "승인 권한이 없습니다" in str(o.get("approve_manager")), str(o.get("approve_manager")))
    check("세션 dict 담당 클레임 위조는 통하지 않는다(권위 재조회)",
          "승인 권한이 없습니다" in str(o.get("approve_forged_claim")),
          str(o.get("approve_forged_claim")))
    check("ADMIN 도 담당 지정이 없으면 승인 거부",
          "승인 권한이 없습니다" in str(o.get("approve_admin_without_duty")),
          str(o.get("approve_admin_without_duty")))
    check("담당자는 승인 가능", o.get("approve_officer") == "APPROVED")
    check("처리자·처리시각이 남는다",
          o.get("approve_decider") == "1001" and o.get("approve_decided_at") is True)
    check("처리자 성명도 조인으로 붙는다", o.get("approve_decider_name") == "김관리")
    check("재승인 거부", "허용됨" not in str(o.get("reapprove")), str(o.get("reapprove")))

    print("(g) 반려·취소·조건부 저장")
    check("반려는 사유 필수",
          "사유" in str(o.get("reject_without_reason")), str(o.get("reject_without_reason")))
    check("반려 사유가 보존된다",
          o.get("reject_status") == "REJECTED" and o.get("reject_comment") == "업무 목적 아님")
    check("본인 취소(체크인 전) 가능", o.get("owner_cancel") == "CANCELLED")
    check("읽은 상태가 바뀌었으면 덮어쓰지 않는다(CAS stale)",
          "다른 사용자가 먼저" in str(o.get("cas_stale")), str(o.get("cas_stale")))

    print("(h) 행위자 신원 · 쓰기 이전 차단")
    check("인증 정보 없으면 차단", "인증된 현재 사용자" in str(o.get("actor_none")))
    check("빈 사번이면 차단", "사번을 확인할 수 없습니다" in str(o.get("actor_empty")))
    check("존재하지 않는 사번이면 차단", "사번을 확인할 수 없습니다" in str(o.get("actor_ghost")))
    check("비활성 사용자는 행위 불가", "비활성" in str(o.get("inactive_actor")),
          str(o.get("inactive_actor")))

    print("(i) 메뉴·라우팅 게이트 · 능력 토큰 하나로 노출과 접근이 함께 결정된다")
    from modules import nav

    ready = {nav.CAP_ACCESS_LODGING}                       # 저장소 준비됨(migration 적용)
    caps = {nav.CAP_ACCESS_LODGING, nav.CAP_APPROVE_LODGING}  # 준비됨 + 담당자
    base = ("lodging_request", "lodging_my", "lodging_calendar")
    for role in ("USER", "MANAGER", "ADMIN"):
        # 저장소 미준비(migration 미적용) 배포 — 메뉴도 라우팅도 열리지 않는다.
        check(f"{role}: 저장소 미준비면 숙소 4화면 전부 접근 불가",
              not any(nav.allowed(page, role) for page in base + ("lodging_manage",)))
        check(f"{role}: 저장소 준비되면 신청·내 예약·캘린더는 전 역할 접근",
              all(nav.allowed(page, role, ready) for page in base))
        check(f"{role}: 준비돼도 승인 관리는 담당 능력 없이는 접근 불가",
              not nav.allowed("lodging_manage", role, ready))
        check(f"{role}: 준비 + 담당 능력이면 승인 관리 접근",
              nav.allowed("lodging_manage", role, caps))
    check("저장소 미준비면 USER 메뉴에 숙소 항목이 없다",
          not any(i["id"].startswith("lodging") for i in nav.user_menu()))
    user_menu_ids = [item["id"] for item in nav.user_menu(ready)]
    check("준비되면 USER 메뉴에 숙소 3개가 노출된다",
          all(pid in user_menu_ids for pid in base))
    check("USER 메뉴의 승인 관리는 담당 능력에만 노출",
          "lodging_manage" not in user_menu_ids
          and "lodging_manage" in [i["id"] for i in nav.user_menu(caps)])
    check("저장소 미준비면 숙소 그룹이 통째로 감춰진다",
          "lodging" not in [g["id"] for g in nav.visible_groups("USER")])
    group_ids = [g["id"] for g in nav.visible_groups("USER", ready)]
    check("준비되면 숙소 그룹이 메뉴에 등록된다", "lodging" in group_ids, str(group_ids))

    app_src = (ROOT / "app.py").read_text(encoding="utf-8")
    ui_src = (ROOT / "modules" / "ui.py").read_text(encoding="utf-8")
    check("app 라우팅 테이블에 4화면이 등록됐다",
          all(f'"{pid}": {pid}' in app_src for pid in
              ("lodging_request", "lodging_my", "lodging_manage", "lodging_calendar")))
    check("메뉴 능력 계산이 app·ui 두 곳에서 동일하게 이뤄진다(불일치 방지)",
          "auth.can_approve_lodging(user)" in app_src
          and "auth.can_approve_lodging(user)" in ui_src
          and "nav.CAP_APPROVE_LODGING" in app_src
          and "nav.CAP_APPROVE_LODGING" in ui_src)
    check("숙소 메뉴가 저장소 준비 상태에 연동된다(app·ui 양쪽)",
          "db.lodging_schema_ready()" in app_src
          and "db.lodging_schema_ready()" in ui_src
          and "nav.CAP_ACCESS_LODGING" in app_src
          and "nav.CAP_ACCESS_LODGING" in ui_src)

    print()
    if FAIL:
        print(f"FAILED {len(FAIL)}: {FAIL}")
        sys.exit(1)
    print(f"ALL PASSED ({PASS} checks)")


main()
