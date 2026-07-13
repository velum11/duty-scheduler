"""Destructive CRUD verification limited to unique TEST_* records."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules import config, db  # noqa: E402


def _one(frame, column: str, value: str):
    rows = frame[frame[column].astype(str) == value]
    assert len(rows) == 1, f"expected one {column}={value}, got {len(rows)}"
    return rows.iloc[0]


def _cleanup(ids: dict, duty_date: str) -> list[str]:
    errors = []
    actions = [
        ("schedule", lambda: db.delete_schedule(ids["emp_no"], duty_date)),
        ("user", lambda: db.hard_delete_test_user(ids["emp_no"])),
        ("work_type_b", lambda: db.hard_delete_test_work_type(ids["work_b"])),
        ("work_type_a", lambda: db.hard_delete_test_work_type(ids["work_a"])),
        ("team", lambda: db.hard_delete_test_team(ids["dept"], ids["team"])),
        ("department", lambda: db.hard_delete_test_department(ids["dept"])),
    ]
    for label, action in actions:
        try:
            action()
        except Exception as exc:
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
    if errors:
        return errors
    users = db.get_users()
    work_types = db.get_work_types()
    teams = db.get_teams()
    departments = db.get_departments()
    checks = [
        ("user", users[users["emp_no"].astype(str) == ids["emp_no"]].shape[0] > 0),
        ("work_type_a", work_types[work_types["code"].astype(str) == ids["work_a"]].shape[0] > 0),
        ("work_type_b", work_types[work_types["code"].astype(str) == ids["work_b"]].shape[0] > 0),
        ("team", teams[teams["team_code"].astype(str) == ids["team"]].shape[0] > 0),
        ("department", departments[departments["dept_code"].astype(str) == ids["dept"]].shape[0] > 0),
    ]
    errors.extend(f"{label}: TEST record still exists" for label, remains in checks if remains)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-test-project", action="store_true")
    args = parser.parse_args()

    if db.datasource() != "supabase":
        raise SystemExit("DUTY_DATA_MODE must be supabase before CRUD testing.")
    if not args.confirm_test_project or not config.supabase_test_project_confirmed():
        raise SystemExit(
            "CRUD test blocked: pass --confirm-test-project and set "
            "DUTY_SUPABASE_TEST_PROJECT=true (or [supabase].test_project=true)."
        )

    suffix = uuid4().hex[:10].upper()
    ids = {
        "dept": f"TEST_DEPT_{suffix}",
        "team": f"TEST_TEAM_{suffix}",
        "emp_no": f"TEST_EMP_{suffix}",
        "work_a": f"TEST_WORK_{suffix}_A",
        "work_b": f"TEST_WORK_{suffix}_B",
    }
    duty_date = date.today().replace(day=15).isoformat()
    stage = "connection"
    results = []
    cleanup_errors: list[str] = []

    try:
        counts = db.test_connection()
        assert set(counts) == {"departments", "teams", "users", "work_types", "work_schedules"}
        results.append("connection")

        stage = "department create/read/update"
        db.upsert_department({
            "dept_code": ids["dept"], "dept_name": "TEST department",
            "sort_order": 9900, "is_active": True,
        })
        _one(db.get_departments(), "dept_code", ids["dept"])
        db.upsert_department({
            "dept_code": ids["dept"], "dept_name": "TEST department updated",
            "sort_order": 9901, "is_active": True,
        })
        assert _one(db.get_departments(), "dept_code", ids["dept"])["dept_name"] == "TEST department updated"
        results.append("department CRUD")

        stage = "team create/read/update"
        db.upsert_team({
            "dept_code": ids["dept"], "team_code": ids["team"],
            "team_name": "TEST team", "sort_order": 9900, "is_active": True,
        })
        _one(db.get_teams(dept_code=ids["dept"]), "team_code", ids["team"])
        db.upsert_team({
            "dept_code": ids["dept"], "team_code": ids["team"],
            "team_name": "TEST team updated", "sort_order": 9901, "is_active": True,
        })
        assert _one(db.get_teams(dept_code=ids["dept"]), "team_code", ids["team"])["team_name"] == "TEST team updated"
        results.append("team CRUD")

        stage = "user create/read/update"
        user = {
            "emp_no": ids["emp_no"], "name": "TEST employee",
            "dept_code": ids["dept"], "team_code": ids["team"],
            "position": "TEST", "role": "MANAGER", "is_active": True,
        }
        db.upsert_user(user)
        assert _one(db.get_users(), "emp_no", ids["emp_no"])["role"] == "MANAGER"
        user.update({"position": "TEST updated", "role": "USER"})
        db.upsert_user(user)
        assert _one(db.get_users(dept_code=ids["dept"], team_code=ids["team"]), "emp_no", ids["emp_no"])["role"] == "USER"
        results.append("user CRUD")

        stage = "work type create/read/update"
        base_work = {
            "name": "TEST duty", "category": "주간", "short_label": "T",
            "start_time": "07:00", "end_time": "15:00", "color": "#123456",
            "is_work": True, "affects_allowance": False, "description": "TEST",
            "sort_order": 9900, "is_active": True,
        }
        db.upsert_work_type({"code": ids["work_a"], **base_work})
        db.upsert_work_type({"code": ids["work_b"], **{**base_work, "short_label": "T2"}})
        updated_work = {"code": ids["work_a"], **base_work, "name": "TEST duty updated", "color": "#654321"}
        db.upsert_work_type(updated_work)
        row = _one(db.get_work_types(), "code", ids["work_a"])
        assert row["name"] == "TEST duty updated" and row["color"] == "#654321"
        results.append("work type CRUD")

        stage = "schedule create/month read"
        schedule = {
            "emp_no": ids["emp_no"], "duty_date": duty_date,
            "work_type_code": ids["work_a"], "note": "TEST schedule",
        }
        db.upsert_schedule(schedule)
        month = db.get_month_schedules([ids["emp_no"]], date.today().year, date.today().month)
        assert len(month) == 1 and month.iloc[0]["work_type_code"] == ids["work_a"]

        stage = "schedule same-day upsert"
        schedule["work_type_code"] = ids["work_b"]
        db.upsert_schedule(schedule)
        month = db.get_month_schedules([ids["emp_no"]], date.today().year, date.today().month)
        assert len(month) == 1 and month.iloc[0]["work_type_code"] == ids["work_b"]
        results.append("schedule CRUD/upsert")

        stage = "fresh client persistence read"
        db.reset_supabase_client()
        persisted = db.get_month_schedules(ids["emp_no"], date.today().year, date.today().month)
        assert len(persisted) == 1 and persisted.iloc[0]["work_type_code"] == ids["work_b"]
        results.append("fresh-client persistence")

        stage = "schedule delete"
        db.delete_schedule(ids["emp_no"], duty_date)
        assert db.get_month_schedules(ids["emp_no"], date.today().year, date.today().month).empty
        results.append("schedule delete")

        stage = "soft delete verification"
        db.deactivate_user(ids["emp_no"])
        db.deactivate_work_type(ids["work_a"])
        db.deactivate_team(ids["dept"], ids["team"])
        db.deactivate_department(ids["dept"])
        assert not bool(_one(db.get_users(), "emp_no", ids["emp_no"])["is_active"])
        assert not bool(_one(db.get_work_types(), "code", ids["work_a"])["is_active"])
        assert not bool(_one(db.get_teams(), "team_code", ids["team"])["is_active"])
        assert not bool(_one(db.get_departments(), "dept_code", ids["dept"])["is_active"])
        results.append("soft delete")
    except Exception as exc:
        print(f"FAIL stage={stage}", file=sys.stderr)
        print(f"identifiers={ids}", file=sys.stderr)
        print(f"error={type(exc).__name__}: {exc}", file=sys.stderr)
        return_code = 1
    else:
        return_code = 0
        for result in results:
            print(f"PASS {result}")
    finally:
        cleanup_errors = _cleanup(ids, duty_date)
        if cleanup_errors:
            print("CLEANUP FAIL", file=sys.stderr)
            for error in cleanup_errors:
                print(f"- {error}", file=sys.stderr)
        else:
            print("PASS cleanup: TEST_* records removed")

    return 1 if cleanup_errors else return_code


if __name__ == "__main__":
    raise SystemExit(main())
