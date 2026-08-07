-- 009: 부서 계층 텍스트 2단(대분류/중분류) + 사용자 재직기간(입사일/퇴사일).
--
-- 목적 (사용자 승인 2026-08-07):
--   (a) 조직 3계층을 "그룹(organization_groups) → 부서 → 운영단위(teams)" 관계 모델에서
--       "대분류 → 중분류 → 부서" 의 **사람이 직접 입력하는 텍스트 2단**으로 바꾼다.
--       현장 조직은 담당/부/팀/파트가 부서마다 깊이가 달라(예: 생산담당만 '생산부' 중간층이
--       있음) 고정 관계 모델로는 매번 재구성이 필요했다. 텍스트 2단은 깊이가 다른 조직을
--       같은 시트에서 표현할 수 있고, 편성 담당자가 화면에서 바로 고칠 수 있다.
--   (b) A/B/C 교대조를 teams(운영단위) 기준정보에서 빼고 근무편성표에서 직접 입력한다.
--       저장 자리는 이미 있다 — schedule_assignments.shift_group_code(002, 텍스트 스냅샷).
--       따라서 이 migration 은 teams 를 **건드리지 않는다**(아래 '하지 않는 것' 참조).
--   (c) 입사일·퇴사일을 users 에 둔다. 퇴사일이 지난 직원은 앱이 로그인을 차단하고
--       편성 명단에서 숨긴다(판정은 앱 계층 소관 — 아래 신뢰 경계).
--
-- 순차·의존:
--   001(users/departments) 이후면 언제든 적용 가능하다. 008(비밀번호)과 서로 독립이며
--   적용 순서에 제약이 없다. 004(organization_groups)가 적용돼 있으면 (4) 백필이
--   대분류를 기존 그룹명으로 채우고, 미적용이면 백필을 건너뛴다(빈 값으로 시작).
--
-- 하지 않는 것 (의도적):
--   * teams 테이블·users.team_id·schedule_assignments.team_id 를 drop 하지 않는다.
--     운영단위는 '화면에서 제거'이지 '데이터 파기'가 아니다. 컬럼을 남겨야 되돌릴 수 있고,
--     과거 편성 스냅샷의 team_id 도 보존된다. 화면 노출 중단은 앱 계층에서 한다.
--   * organization_groups 를 drop 하지 않는다. departments.group_id 는 nullable 이라
--     앱이 쓰지 않아도 무해하며, (4) 백필의 원본이라 최소 1회는 필요하다.
--   * 기존 행의 값을 덮어쓰지 않는다. (4) 백필은 major_category 가 빈 문자열인 행에만 쓴다.
--
-- 신뢰 경계 (007/008 과 같은 선긋기):
--   "퇴사일이 지났으므로 로그인 차단"의 판정은 DB 가 하지 않는다. DB 는 날짜의 저장 형태와
--   정합(퇴사일 < 입사일 금지)만 보장하고, 차단·숨김은 앱 계층(modules/auth.py·db.py)이 한다.
--   대분류/중분류도 마찬가지로 자유 텍스트이며 DB 는 계층의 의미를 검증하지 않는다 —
--   오타가 곧 새 분류가 되는 것은 이 설계가 감수한 대가다(사용자 결정: 기준정보화 대신 자유입력).
--
-- 안전 계약 (001/004/006/007/008 관행 준수):
--   * 재실행 안전: 모든 문장이 guarded (add column if not exists, do-block 제약 확인 후 추가).
--   * 어떤 테이블도 drop 하지 않고 기존 값을 삭제하지 않는다.
--   * (0) 전제 assertion 과 (3) 스키마 assertion 이 부분적용·전제부재를 조용히 넘기지 않는다.
--
-- live schema 재확인·적용은 사용자 승인 게이트(AGENTS.md)다.
--
-- 수동 롤백 (역순; 009 이전 데이터 유지):
--   alter table public.users drop constraint if exists users_tenure_order;
--   alter table public.users drop column if exists resign_date;
--   alter table public.users drop column if exists hire_date;
--   alter table public.departments drop constraint if exists departments_minor_requires_major;
--   alter table public.departments drop column if exists minor_category;
--   alter table public.departments drop column if exists major_category;

-- =========================================================================
-- 0) 전제 스키마 assertion — departments / users 부재를 조용히 넘기지 않는다.
-- =========================================================================
do $$
begin
    if to_regclass('public.departments') is null then
        raise exception '009 전제 위반: public.departments 테이블이 없습니다(001 미적용).';
    end if;
    if to_regclass('public.users') is null then
        raise exception '009 전제 위반: public.users 테이블이 없습니다(001 미적용).';
    end if;
    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.departments'::regclass
          and attname = 'dept_code' and not attisdropped
    ) then
        raise exception '009 전제 위반: departments.dept_code 가 없습니다.';
    end if;
end
$$;

-- =========================================================================
-- 1) departments — 대분류/중분류 텍스트 2단.
--    NOT NULL DEFAULT '' 로 두어 기존 행이 즉시 유효해진다(빈 값 = 미분류).
-- =========================================================================
alter table public.departments
    add column if not exists major_category text not null default '';

alter table public.departments
    add column if not exists minor_category text not null default '';

-- 중분류만 있고 대분류가 빈 상태는 계층이 성립하지 않는다(중간층만 떠 있는 트리).
-- 반대(대분류만 있고 중분류 없음)는 정상 — 깊이가 얕은 조직이 그렇다.
do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.departments'::regclass
          and conname = 'departments_minor_requires_major'
    ) then
        alter table public.departments
            add constraint departments_minor_requires_major
            check (btrim(minor_category) = '' or btrim(major_category) <> '');
    end if;
end
$$;

comment on column public.departments.major_category is
    '조직 대분류(자유 텍스트, 빈 값 = 미분류). 화면에서 사람이 직접 입력한다. 기준정보 FK 가 아니므로 표기 흔들림은 앱/운영 책임.';
comment on column public.departments.minor_category is
    '조직 중분류(자유 텍스트). 대분류가 비어 있으면 값을 가질 수 없다(departments_minor_requires_major).';

-- =========================================================================
-- 2) users — 입사일/퇴사일.
--    둘 다 nullable: 입사일 미상 이력자가 있고, 재직자는 퇴사일이 없다.
-- =========================================================================
alter table public.users
    add column if not exists hire_date date;

alter table public.users
    add column if not exists resign_date date;

-- 퇴사일이 입사일보다 앞설 수 없다. 한쪽만 있는 경우는 검사 대상이 아니다.
do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.users'::regclass
          and conname = 'users_tenure_order'
    ) then
        alter table public.users
            add constraint users_tenure_order
            check (hire_date is null or resign_date is null or resign_date >= hire_date);
    end if;
end
$$;

comment on column public.users.hire_date is
    '입사일(nullable — 미상 허용).';
comment on column public.users.resign_date is
    '퇴사일(nullable = 재직 중). 경과 시 로그인 차단·편성 명단 숨김은 앱 계층 판정이며 DB 는 강제하지 않는다.';

-- =========================================================================
-- 3) 스키마 assertion — 부분 적용을 묵인하지 않는다.
-- =========================================================================
do $$
begin
    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.departments'::regclass
          and attname in ('major_category', 'minor_category')
          and not attisdropped
        having count(*) = 2
    ) then
        raise exception '009 검증 실패: departments 대분류/중분류 컬럼이 완전하지 않습니다.';
    end if;
    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.users'::regclass
          and attname in ('hire_date', 'resign_date')
          and not attisdropped
        having count(*) = 2
    ) then
        raise exception '009 검증 실패: users 입사일/퇴사일 컬럼이 완전하지 않습니다.';
    end if;
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.users'::regclass and conname = 'users_tenure_order'
    ) then
        raise exception '009 검증 실패: users_tenure_order 제약이 없습니다.';
    end if;
end
$$;

-- =========================================================================
-- 4) 무손실 백필 — 대분류를 기존 그룹명으로 채운다.
--    004(organization_groups) 적용 환경에서만 동작하며, major_category 가 빈 행에만 쓴다.
--    목적: 그룹 시트를 폐지해도 이미 편성돼 있던 담당 구분이 화면에서 사라지지 않게 한다.
--    사용자는 이 값을 출발점으로 실제 대분류(예: 'PET생산부')로 고쳐 쓴다.
-- =========================================================================
do $$
begin
    if to_regclass('public.organization_groups') is not null
       and exists (
           select 1 from pg_attribute
           where attrelid = 'public.departments'::regclass
             and attname = 'group_id' and not attisdropped
       )
    then
        update public.departments d
           set major_category = g.group_name
          from public.organization_groups g
         where d.group_id = g.id
           and btrim(d.major_category) = ''
           and btrim(g.group_name) <> '';
    end if;
end
$$;
