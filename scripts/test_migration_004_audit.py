"""migration 004 정적 안전 계약 감사 (DB 접속·SQL 실행 없음).

004 = organization_groups 신설 + departments.group_id FK + 무손실 백필(경로 B).
002/003 audit 와 동일하게 실행 구문만 정규화해 파괴적 연산 부재·재실행 안전·
근무데이터 비접촉을 정적으로 검증한다. 실제 적용/롤백은 사용자 승인 후 SQL editor.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = ROOT / "supabase" / "migrations" / "004_org_groups.sql"
sql = SQL_PATH.read_text(encoding="utf-8")

# 실행 구문만 판정하도록 블록·줄 주석을 제거한다. 헤더 예시/롤백절(-- 주석)은
# 실행 대상이 아니다. do-block 내부 dollar-quote($$, $q$) 는 주석이 없어 보존된다.
without_blocks = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
executable = "\n".join(line.split("--", 1)[0] for line in without_blocks.splitlines())
normalized = re.sub(r"\s+", " ", executable).strip().lower()
padded = f" {normalized} "

checks = {
    "migration 파일 존재": SQL_PATH.exists(),
    "organization_groups 테이블 생성(if not exists)":
        "create table if not exists public.organization_groups" in normalized,
    "그룹 컬럼 계약 존재(code/name/sort/desc/active)": all(
        tok in normalized for tok in
        ("group_code", "group_name", "sort_order", "description", "is_active")
    ),
    "컬럼 추가는 IF NOT EXISTS(>=5)":
        normalized.count("add column if not exists") >= 5,
    "departments.group_id FK → organization_groups":
        "departments_group_fk" in normalized
        and "references public.organization_groups" in normalized,
    "FK guard 는 pg_constraint catalog":
        "pg_constraint" in normalized and "on delete restrict" in normalized,
    "CASCADE 삭제 없음": "on delete cascade" not in normalized,
    "백필 INSERT 는 재실행안전(on conflict do nothing)":
        "on conflict (group_code) do nothing" in normalized,
    "백필 UPDATE 는 신규컬럼 가드(group_id is null)":
        "group_id is null" in normalized,
    "승인된 4그룹만 INSERT(PET/PVC/DECO/ADMIN·관리·999)":
        all(tok in normalized for tok in
            ("'pet'", "'pvc'", "'deco'", "'admin'", "'관리'", "999")),
    "MTRL 은 그룹 아닌 PET그룹 소속부서(dept→group 매핑에만 등장)":
        normalized.count("'mtrl'") == 1,
    "DML 은 departments.group_id UPDATE 1건만(teams/users UPDATE 없음)":
        normalized.count("update public.departments") == 1
        and "update public.teams" not in normalized
        and "update public.users" not in normalized,
    # "on delete restrict/cascade" 는 FK 절이므로 파괴적 DML 인 "delete from" 만 본다.
    "실행 DELETE 없음": "delete from" not in normalized,
    "실행 TRUNCATE 없음": " truncate " not in padded,
    "DROP TABLE 없음": "drop table" not in normalized,
    "DROP COLUMN 없음": "drop column" not in normalized,
    "DROP CONSTRAINT 없음(실행)": "drop constraint" not in normalized,
    "근무 데이터 테이블 비접촉":
        "work_schedules" not in normalized
        and "schedule_assignments" not in normalized
        and "shift_groups" not in normalized,
    "운영단위 허용값 고정(SHIFT/GENERAL)":
        "'shift'" in normalized and "'general'" in normalized,
    "display_order nullable 유지(003 소유)": "display_order integer" in normalized,
    "RLS 활성화": "enable row level security" in normalized,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(("  ok - " if ok else "  FAIL - ") + name)
if failed:
    raise SystemExit(f"migration 004 audit failed: {', '.join(failed)}")
print(f"\nPASS {len(checks)}")
