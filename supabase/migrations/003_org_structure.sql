-- 003: 조직 관리 통합 — 부서그룹 컬럼 + 운영단위 유형 + 사용자 표시순서.
-- DDL + 안전 백필만 수행한다. 어떤 테이블도 drop 하지 않고, 기존 행을 삭제하거나
-- 기존 컬럼 값을 덮어쓰지 않는다 (백필은 신규 컬럼의 기본값 상태 행에만 UPDATE).
-- 재실행 안전: 모든 문장이 guarded (if not exists / 조건부 UPDATE / do-block).
-- work_schedules / schedule_assignments 는 참조하지 않는다 (근무 데이터 무변경).
--
-- 적용 전후 예상 행 수 (2026-07 기준 테스트 프로젝트):
--   departments 5 · teams 6 · users 21 — 행 수 불변 (컬럼만 추가).
--   실행 DML: departments UPDATE 2건(빈 그룹 백필·순서 백필)뿐, INSERT/DELETE 없음.
--
-- 구조 (CLAUDE.md §5 · 조직 관리 미션):
--   그룹 → 부서 → 운영단위(기존 teams)
--   * 부서그룹은 별도 테이블이 아니라 departments 의 컬럼으로 관리한다.
--   * departments.sort_order 는 "같은 그룹 안에서의 부서 보조 표시 순서"다
--     (컬럼명 유지 — 기존 코드·정렬 호환. 중복 허용, 같으면 dept_code 보조 정렬).
--   * teams 는 "운영단위"로 의미를 확장한다: 교대조(A/B/C)뿐 아니라
--     일반근무(나인투식스·상근 등)도 담는다. 유형은 unit_type 으로 구분한다.
--   * users.display_order 는 "부서그룹 안에서의 직원 표시순서"다. 그룹 내 활성
--     사용자끼리 중복 금지는 앱 저장 계층에서 검증한다 (그룹이 departments 컬럼
--     경유 간접 관계라 DB unique 제약으로 표현하지 않는다).
--
-- 그룹순서(group_sort_order) 유일성:
--   같은 그룹에 속한 부서 행들은 같은 group_sort_order 를 공유하므로 단순 unique
--   제약으로는 "그룹 간 순서 중복 금지"를 표현할 수 없다. 이 규칙(그룹명이 다르면
--   group_sort_order 도 달라야 함 + 같은 그룹은 하나의 순서만 가짐)은 앱 저장
--   계층(views/master_org 검증)에서 저장 전 차단한다.
--
-- 수동 롤백 (역순; 003 이전 데이터는 그대로 유지):
--   alter table public.users drop column if exists display_order;
--   alter table public.teams drop constraint if exists teams_unit_type_check;
--   alter table public.teams drop column if exists unit_type;
--   alter table public.departments drop column if exists group_sort_order;
--   alter table public.departments drop column if exists department_group;

-- 1) departments: 그룹명 + 그룹 표시 순서
alter table public.departments
    add column if not exists department_group text not null default '';
alter table public.departments
    add column if not exists group_sort_order integer not null default 0;

-- 2) teams: 운영단위 유형 (SHIFT=교대 / GENERAL=일반)
alter table public.teams
    add column if not exists unit_type text not null default 'SHIFT';

-- 2-1) users: 부서그룹 안에서의 직원 표시순서.
--      기존 사용자는 NULL 유지(사번순 임의 백필 금지 — 사용자가 화면에서 직접 입력).
--      NULL 은 지정된 사용자 뒤에 사번순으로 정렬한다.
alter table public.users
    add column if not exists display_order integer;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'teams_unit_type_check'
          and conrelid = 'public.teams'::regclass
    ) then
        alter table public.teams
            add constraint teams_unit_type_check
            check (unit_type in ('SHIFT', 'GENERAL'));
    end if;
end $$;

-- 3) 백필 — 기본값 상태(신규 컬럼이 비어 있는) 행에만 적용한다.
--    * department_group: 부서 자기 자신(부서명)을 그룹으로 채운다. 실제 그룹
--      (PET/PVC/DECO/관리 등)은 사용자가 조직 관리 화면에서 수동 보정한다.
--    * group_sort_order: 기존 sort_order → dept_code 순으로 1..N 을 부여해
--      전역 중복 없이 시작한다 (부서 1개 = 그룹 1개 상태이므로 유일성 성립).
--    * unit_type: default 'SHIFT' 로 이미 채워짐 — 기존 조는 전부 교대조.
--      일반근무(나인투식스·상근 등)는 이후 화면에서 등록·수정한다.
update public.departments
   set department_group = dept_name
 where btrim(department_group) = '';

with ranked as (
    select id, row_number() over (order by sort_order, dept_code) as rn
      from public.departments
)
update public.departments d
   set group_sort_order = ranked.rn
  from ranked
 where d.id = ranked.id
   and d.group_sort_order = 0;

comment on column public.departments.department_group is
    'Department group label (e.g. PET/PVC/DECO/관리). Managed as a column, not a separate table.';
comment on column public.departments.group_sort_order is
    'Global display order of the group. Uniqueness across distinct groups is enforced by the app save layer.';
comment on column public.departments.sort_order is
    'Department display order within its department_group (redefined by 003).';
comment on column public.teams.unit_type is
    'Operating unit type: SHIFT(교대조 A/B/C) or GENERAL(일반근무 — 나인투식스/상근 등).';
comment on column public.users.display_order is
    'Employee display order within the department group. NULL = unassigned (sorted after assigned, by emp_no). Uniqueness among active users per group is enforced by the app layer.';
