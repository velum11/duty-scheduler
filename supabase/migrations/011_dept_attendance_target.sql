-- 011: 부서별 "근태(근무표) 등록 대상" 지정 플래그 — departments.tracks_attendance.
--
-- 목적 (사용자 지시 2026-08-13, 승인 2026-08-14):
--   "조직 관리에 근태 등록하는 부서만 지정할 수 있게" + "근태에서는 해당 조직만 목록·조회".
--   현재 부서 기준정보에는 근무표를 실제로 편성·등록하는 조직과 그렇지 않은 조직
--   (지원·관리 계열, 코드 접미 'D' 계열 상위 조직 등)을 구분할 자리가 없다. 그래서
--   편성·월간 근무표·대시보드가 근무를 등록하지 않는 부서까지 전부 나열한다.
--   이 컬럼은 그 구분을 **부서 기준정보의 1급 속성**으로 둔다 — 근무 데이터 유무로
--   매번 추론하지 않고 운영자가 조직 관리 화면에서 명시적으로 지정한다.
--
-- 컬럼명·타입 결정 근거:
--   * `tracks_attendance` — 기존 boolean 명명 2계열 중 "행이 무엇을 하는가"를 서술하는
--     동사구 계열(work_types.affects_allowance)을 따른다. `is_*` 계열(is_active/
--     is_work/is_safety_officer)은 상태·신분 서술에 쓰고 있어, "이 부서가 근태를
--     관리(등록)한다"는 행위 서술에는 동사구가 정확하다. `is_attendance_target` 은
--     '무엇의 대상인지'가 이름에 없어 모호해 채택하지 않았다.
--   * boolean not null default false — 3-값(NULL=미지정) 을 두지 않는다. 미지정과
--     '대상 아님'을 구분할 업무 의미가 없고, NULL 은 앱 필터에서 조용한 누락을 만든다.
--     009 의 `not null default ''` 와 같은 선긋기다.
--   * **default false 선택 이유**: 컬럼 추가 시 기존 43개 부서가 조용히 true 로 채워지면
--     이 기능이 도입 직후 무의미해진다(전 부서 노출 = 현재와 동일). 초기값의 정본은
--     아래 (4) 백필이며, DDL default 는 "지정되지 않음 = 대상 아님"의 안전한 바닥이다.
--     신규 부서도 default false 로 생겨 운영자가 명시적으로 켜야 한다(명시 지정 원칙).
--
-- 순차·의존:
--   001(departments) 이후면 언제든 적용 가능하다. 002(schedule_assignments)·004·008·
--   009·010 과 독립이며 적용 순서 제약이 없다. (4) 백필은 002 적용 여부에 따라
--   근거 집합이 달라지되 미적용 환경에서도 실패하지 않는다(guarded).
--
-- 하지 않는 것 (의도적):
--   * 어떤 테이블·컬럼도 drop 하지 않는다.
--   * 기존 행의 tracks_attendance 이외 컬럼 값을 건드리지 않는다.
--   * 근무 데이터(work_schedules/schedule_assignments)를 읽기만 하고 쓰지 않는다.
--   * departments 의 RLS 상태를 바꾸지 않는다 — 001 에서 이미 enable(policy 없음,
--     service role 서버 접근 전용)이므로 컬럼 추가에 추가 조치가 필요 없다.
--   * 인덱스를 만들지 않는다. departments 는 수십 행 규모의 기준정보라 seq scan 이
--     인덱스보다 싸다(필요해지면 가산적으로 추가).
--
-- 신뢰 경계 (009/010 과 같은 선긋기):
--   DB 는 이 플래그의 저장과 정합(not null boolean)만 보장한다. "대상 부서만 편성·
--   조회에 노출"의 집행은 앱 계층(modules/db.py::attendance_dept_codes 와 화면 필터)
--   소관이며, DB 는 비대상 부서에 근무 행이 생기는 것을 막지 않는다 — 과거 근무 데이터와
--   운영 예외를 파기하지 않기 위한 의도적 선택이다.
--
-- 안전 계약 (001~010 관행 준수):
--   * 재실행 안전: add column if not exists + do-block 가드. 재적용해도 값이 뒤집히지 않는다.
--   * no-drop, 기존 값 무기록(아래 (4) 의 1회성 조건 참조).
--   * (0) 전제 assertion 과 (3) 스키마 assertion 이 부분적용·전제부재를 조용히 넘기지 않는다.
--
-- live schema 재확인·적용은 사용자 승인 게이트(AGENTS.md)다.
--
-- 수동 롤백 (011 이전 데이터 유지):
--   alter table public.departments drop column if exists tracks_attendance;

-- =========================================================================
-- 0) 전제 스키마 assertion — departments 부재를 조용히 넘기지 않는다.
-- =========================================================================
do $$
begin
    if to_regclass('public.departments') is null then
        raise exception '011 전제 위반: public.departments 테이블이 없습니다(001 미적용).';
    end if;
    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.departments'::regclass
          and attname = 'dept_code' and not attisdropped
    ) then
        raise exception '011 전제 위반: departments.dept_code 가 없습니다.';
    end if;
    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.departments'::regclass
          and attname = 'id' and not attisdropped
    ) then
        raise exception '011 전제 위반: departments.id 가 없습니다(백필 조인 불가).';
    end if;
end
$$;

-- =========================================================================
-- 1) departments — 근태 등록 대상 플래그.
-- =========================================================================
alter table public.departments
    add column if not exists tracks_attendance boolean not null default false;

comment on column public.departments.tracks_attendance is
    '근태(근무표) 등록 대상 부서 여부. true 인 부서만 편성·월간 근무표·대시보드의 조직 목록에 노출된다(집행은 앱 계층). 기본 false = 미지정은 대상 아님. 운영자가 조직 관리 화면에서 지정한다.';

-- =========================================================================
-- 2) (예약) 제약 없음.
--    boolean not null 자체가 유일한 정합 요구다. "최소 1개 부서는 true" 같은
--    테이블 수준 요구는 두지 않는다 — 초기 도입·조직 개편 중 일시적으로 0개가 되는
--    상태를 DB 가 막으면 정상 운영이 잠긴다(빈 목록 처리는 앱 계층 폴백 소관).
-- =========================================================================

-- =========================================================================
-- 3) 스키마 assertion — 부분 적용을 묵인하지 않는다.
-- =========================================================================
do $$
declare
    v_type text;
    v_notnull boolean;
begin
    select format_type(a.atttypid, a.atttypmod), a.attnotnull
      into v_type, v_notnull
      from pg_attribute a
     where a.attrelid = 'public.departments'::regclass
       and a.attname = 'tracks_attendance'
       and not a.attisdropped;
    if v_type is null then
        raise exception '011 검증 실패: departments.tracks_attendance 컬럼이 없습니다.';
    end if;
    if v_type <> 'boolean' then
        raise exception '011 검증 실패: tracks_attendance 타입이 boolean 이 아닙니다(현재 %).', v_type;
    end if;
    if not v_notnull then
        raise exception '011 검증 실패: tracks_attendance 가 NOT NULL 이 아닙니다.';
    end if;
end
$$;

-- =========================================================================
-- 4) 초기 지정 백필 — "근무 기록이 있는 부서만 true" (사용자 승인 2026-08-14).
--
--    대상 집합(합집합):
--      (a) schedule_assignments.department_id 로 참조된 부서
--          = 월 편성 스냅샷이 그 부서로 저장된 이력이 있는 부서
--      (b) work_schedules 행을 가진 사용자의 소속 부서(users.department_id)
--          = 일별 근무 행이 실제로 존재하는 부서
--    (b) 를 포함하는 이유: work_schedules 에는 부서 컬럼이 없고(귀속은 user 경유),
--    002 이전 legacy 근무 행은 편성 스냅샷 없이도 유효하다(docs/database.md §2).
--    (a) 만 쓰면 편성 없이 근무만 등록해 온 부서가 도입 즉시 근무표에서 사라진다.
--
--    **1회성 가드**: 이미 true 인 부서가 하나라도 있으면 백필을 통째로 건너뛴다.
--    재적용 시 운영자가 손으로 끈 부서를 근무 이력만 보고 되살리지 않기 위함이다
--    (009 의 '빈 값에만 백필' 과 같은 원칙을 boolean 에 맞게 테이블 수준으로 적용).
--    어떤 경우에도 true → false 로 내리지 않는다.
--
--    구현 주의: plpgsql 은 SQL 문을 **실행 시점에** 파싱한다. 없는 테이블을 텍스트로
--    참조하는 문장은 조건이 false 여도 실행되면 파싱에서 실패하므로, 두 근거를 하나의
--    UPDATE 에 or 로 묶지 않고 **가드별 UPDATE 2개**로 나눈다(009 가 update 전체를
--    if 블록으로 감싼 것과 같은 이유). 두 번째 UPDATE 는 아직 false 인 행만 보므로
--    결과는 합집합과 같다.
-- =========================================================================
do $$
declare
    v_already integer;
    v_updated integer := 0;
    v_step integer := 0;
    v_has_assignments boolean;
    v_has_work boolean;
begin
    select count(*) into v_already from public.departments where tracks_attendance;
    if v_already > 0 then
        raise notice '011 백필 생략: 이미 근태 대상으로 지정된 부서 % 건이 있습니다(운영자 지정 보존).', v_already;
        return;
    end if;

    v_has_assignments := (
        to_regclass('public.schedule_assignments') is not null
        and exists (
            select 1 from pg_attribute
            where attrelid = 'public.schedule_assignments'::regclass
              and attname = 'department_id' and not attisdropped
        )
    );
    v_has_work := (
        to_regclass('public.work_schedules') is not null
        and to_regclass('public.users') is not null
        and exists (
            select 1 from pg_attribute
            where attrelid = 'public.work_schedules'::regclass
              and attname = 'user_id' and not attisdropped
        )
    );

    if not v_has_assignments and not v_has_work then
        raise notice '011 백필 생략: 근무 기록 테이블이 없어 판정 근거가 없습니다(전 부서 false 로 시작).';
        return;
    end if;

    -- (a) 월 편성 스냅샷의 귀속 부서
    if v_has_assignments then
        update public.departments d
           set tracks_attendance = true
         where d.tracks_attendance is distinct from true
           and exists (
               select 1 from public.schedule_assignments sa
                where sa.department_id = d.id
           );
        get diagnostics v_step = row_count;
        v_updated := v_updated + v_step;
        raise notice '011 백필 (a) 편성 스냅샷 근거: % 건 지정.', v_step;
    end if;

    -- (b) 일별 근무 행 보유 직원의 소속 부서 (편성 없이 근무만 있는 legacy 포함)
    if v_has_work then
        update public.departments d
           set tracks_attendance = true
         where d.tracks_attendance is distinct from true
           and exists (
               select 1
                 from public.work_schedules ws
                 join public.users u on u.id = ws.user_id
                where u.department_id = d.id
           );
        get diagnostics v_step = row_count;
        v_updated := v_updated + v_step;
        raise notice '011 백필 (b) 일별 근무 근거: % 건 추가 지정.', v_step;
    end if;

    raise notice '011 백필 완료: 근무 기록 보유 부서 % 건을 근태 대상으로 지정했습니다.', v_updated;
end
$$;
