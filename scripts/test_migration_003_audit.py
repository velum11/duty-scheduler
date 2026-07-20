"""migration 003 정적 안전 계약 감사 (DB 접속·SQL 실행 없음)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = ROOT / "supabase" / "migrations" / "003_org_structure.sql"
sql = SQL_PATH.read_text(encoding="utf-8")

# 실행 구문만 판정하도록 블록·줄 주석을 제거한다. 헤더 예시는 실행 대상이 아니다.
without_blocks = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
executable = "\n".join(line.split("--", 1)[0] for line in without_blocks.splitlines())
normalized = re.sub(r"\s+", " ", executable).strip().lower()

checks = {
    "migration 파일 존재": SQL_PATH.exists(),
    "컬럼 추가는 IF NOT EXISTS": normalized.count("add column if not exists") >= 4,
    "제약 추가는 catalog guard": "pg_constraint" in normalized and "teams_unit_type_check" in normalized,
    "DML은 departments 조건부 UPDATE만": normalized.count("update public.departments") == 2 and "update public.teams" not in normalized and "update public.users" not in normalized,
    "실행 DELETE 없음": " delete " not in f" {normalized} ",
    "실행 TRUNCATE 없음": " truncate " not in f" {normalized} ",
    "실행 DROP 없음": " drop " not in f" {normalized} ",
    "근무 데이터 테이블 비접촉": "work_schedules" not in normalized and "schedule_assignments" not in normalized,
    "운영단위 허용값 고정": "shift" in normalized and "general" in normalized,
    "display_order nullable 추가": "display_order integer" in normalized,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(("  ok - " if ok else "  FAIL - ") + name)
if failed:
    raise SystemExit(f"migration 003 audit failed: {', '.join(failed)}")
print(f"\nPASS {len(checks)}")
