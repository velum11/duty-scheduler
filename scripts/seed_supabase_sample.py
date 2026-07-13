"""Idempotently seed data/sample into an explicitly confirmed test project."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules import config, db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm-test-project",
        action="store_true",
        help="Confirm that the configured Supabase target is a disposable test project.",
    )
    args = parser.parse_args()

    if db.datasource() != "supabase":
        raise SystemExit("DUTY_DATA_MODE must be supabase before seeding.")
    if not args.confirm_test_project or not config.supabase_test_project_confirmed():
        raise SystemExit(
            "Seed blocked: pass --confirm-test-project and set "
            "DUTY_SUPABASE_TEST_PROJECT=true (or [supabase].test_project=true)."
        )

    counts = db.test_connection()
    print("Supabase test project connection verified; credentials are not displayed.")
    print("Accessible tables: " + ", ".join(sorted(counts)))

    frames = db.sample_seed_frames()
    db.save_departments(frames["departments"])
    db.save_teams(frames["teams"])
    db.save_work_types(frames["work_types"])
    db.save_users(frames["users"])
    db.save_schedules(frames["work_schedules"])

    print("Sample seed completed (idempotent natural-key upsert):")
    for name, frame in frames.items():
        print(f"- {name}: {len(frame)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
