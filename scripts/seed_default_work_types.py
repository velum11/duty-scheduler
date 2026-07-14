"""Create or update the standard work types without deleting other records."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules import db, supabase_repository  # noqa: E402


DEFAULT_WORK_TYPES = [
    {
        "code": "DAY", "name": "주간", "category": "주간", "short_label": "주",
        "start_time": "08:00", "end_time": "20:00", "color": "#1E6FD9",
        "is_work": True, "affects_allowance": False, "description": "주간 정규 근무",
        "sort_order": 10, "is_active": True,
    },
    {
        "code": "NIGHT", "name": "야간", "category": "야간", "short_label": "야",
        "start_time": "20:00", "end_time": "08:00", "color": "#7B4FD8",
        "is_work": True, "affects_allowance": False, "description": "야간 정규 근무",
        "sort_order": 20, "is_active": True,
    },
    {
        "code": "OFF", "name": "OFF", "category": "OFF", "short_label": "OFF",
        "start_time": "", "end_time": "", "color": "#9AA0A6",
        "is_work": False, "affects_allowance": False, "description": "휴무",
        "sort_order": 30, "is_active": True,
    },
    {
        "code": "ANNUAL", "name": "연차", "category": "휴가", "short_label": "연차",
        "start_time": "", "end_time": "", "color": "#2E9E5B",
        "is_work": False, "affects_allowance": False, "description": "연차 휴가",
        "sort_order": 40, "is_active": True,
    },
    {
        "code": "MATERNITY", "name": "출산휴가", "category": "휴가", "short_label": "출산",
        "start_time": "", "end_time": "", "color": "#D64596",
        "is_work": False, "affects_allowance": False, "description": "출산휴가",
        "sort_order": 50, "is_active": True,
    },
    {
        "code": "TRAINING", "name": "훈련", "category": "교육", "short_label": "훈련",
        "start_time": "", "end_time": "", "color": "#12A5A5",
        "is_work": False, "affects_allowance": False, "description": "교육 및 훈련",
        "sort_order": 60, "is_active": True,
    },
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm-supabase",
        action="store_true",
        help="Confirm the configured Supabase target before writing default work types.",
    )
    args = parser.parse_args()

    if db.datasource() != "supabase":
        raise SystemExit("DUTY_DATA_MODE must be supabase before seeding.")
    if not args.confirm_supabase:
        raise SystemExit("Seed blocked: pass --confirm-supabase.")

    supabase_repository.upsert_work_types(DEFAULT_WORK_TYPES)
    db.reset_supabase_client()
    actual = db.get_work_types()
    expected_codes = [row["code"] for row in DEFAULT_WORK_TYPES]
    seeded = actual[actual["code"].isin(expected_codes)].sort_values("sort_order")
    if seeded["code"].tolist() != expected_codes:
        raise SystemExit("Default work type verification failed after upsert.")

    print(f"Default work types upserted: {len(DEFAULT_WORK_TYPES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
