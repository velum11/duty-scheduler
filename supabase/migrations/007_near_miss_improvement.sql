-- 007: 아차사고 개선조치(CAPA) 폐루프 — near_miss_improvements 테이블 +
--      near_miss_reports 보완요청 컬럼 + 확인·종결 하드게이트(RPC/trigger).
--
-- 목적 (사용자 승인 전 DRAFT — 실행/원격 write 금지, Codex 감사 + 사용자 승인 게이트):
--   아차사고 보고서의 "개선조치 등록 → 제출 → 확인/반려 → 종결(CLOSED)" 폐루프를
--   데이터 계층에서 강제한다. 보고서는 확인(CONFIRMED)된 활성 개선조치가 있어야만
--   종결할 수 있으며(하드 계약), 이 계약은 UI/facade/RPC 어느 경로로도 우회할 수 없다.
--
-- 순차·의존 (006 뒤):
--   006(near_miss_reports + users.is_safety_officer)이 문서상 DRAFT·미적용이므로 007 은
--   006 을 전제로 하는 순차 후속이다(006 적용 → 007 적용). 이 파일은 near_miss_reports
--   테이블과 users.is_safety_officer 가 이미 존재한다고 가정하며, 아래 (0) 스키마
--   assertion 이 전제 부재를 조용히 넘기지 않고 명확히 실패시킨다.
--
-- 안전 계약 (001/004/006 관행 준수):
--   * 어떤 테이블도 drop 하지 않고 기존 행/값을 삭제·덮어쓰지 않는다.
--   * 재실행 안전: 모든 문장이 guarded (create table/index if not exists,
--     add column if not exists, create or replace function, do-block 제약 확인 후 추가).
--   * RLS 는 enable 하되 policy 는 두지 않는다(service role 서버 접근만 — 001/004/006 관행).
--   * CREATE TABLE IF NOT EXISTS 만으로 "부분적으로 다른 기존 구조"를 묵인하지 않는다:
--     (0)/(2b) 스키마 assertion 이 핵심 컬럼·제약 존재를 확인하고, 없으면 RAISE 한다
--     (기존에 다른 형태로 near_miss_improvements 가 있으면 조용히 no-op 되는 함정을 차단).
--
-- SECURITY DEFINER 하드닝 (Codex 필수):
--   종결 RPC 는 SECURITY DEFINER 로 서버측 인가·게이트를 원자 트랜잭션에서 강제하되,
--   PUBLIC/anon/authenticated 의 EXECUTE 를 회수하고 service_role 에만 부여한다.
--   search_path 를 고정하고 모든 객체를 schema-qualified 로 참조해 권한 상승 경로를 막는다.
--
-- live schema 재확인·적용은 사용자 승인 게이트(AGENTS.md)다 — 이 파일은 작성까지만이며
-- 실제 실행/원격 write 는 하지 않는다.
--
-- 수동 롤백 (역순; 007 이전 데이터 유지):
--   drop trigger if exists near_miss_close_requires_confirmed_capa on public.near_miss_reports;
--   drop trigger if exists near_miss_improvement_guard_closed_parent on public.near_miss_improvements;
--   drop function if exists public.close_near_miss_report(bigint, text);
--   drop function if exists public.near_miss_close_requires_confirmed_capa();
--   drop function if exists public.near_miss_improvement_guard_closed_parent();
--   drop table if exists public.near_miss_improvements;
--   alter table public.near_miss_reports drop column if exists revision_request_reason;
--   alter table public.near_miss_reports drop column if exists revision_requested_by_user_id;
--   alter table public.near_miss_reports drop column if exists revision_requested_at;

-- =========================================================================
-- 0) 전제(006) 스키마 assertion — near_miss_reports / users.is_safety_officer 부재를
--    조용히 넘기지 않고 명확히 실패시킨다(006 미적용 상태에서 007 을 적용하는 사고 방지).
-- =========================================================================
do $$
begin
    if to_regclass('public.near_miss_reports') is null then
        raise exception '007 전제 위반: public.near_miss_reports 테이블이 없습니다(006 미적용). 006 을 먼저 적용하세요.';
    end if;
    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.near_miss_reports'::regclass
          and attname in ('id', 'status', 'updated_by', 'updated_at')
          and not attisdropped
        having count(*) = 4
    ) then
        raise exception '007 전제 위반: near_miss_reports 에 필요한 컬럼(id/status/updated_by/updated_at)이 없습니다(006 구조 불일치).';
    end if;
    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.users'::regclass
          and attname = 'is_safety_officer'
          and not attisdropped
    ) then
        raise exception '007 전제 위반: users.is_safety_officer 컬럼이 없습니다(006 미적용).';
    end if;
end $$;

-- =========================================================================
-- 1) near_miss_reports: 보완요청(개선조치 반송) 컬럼 (P1-4)
--    IN_REVIEW→SUBMITTED 반송 사유·요청자·시각. rejection_reason(반려 사유)과 별개다.
-- =========================================================================
alter table public.near_miss_reports add column if not exists revision_request_reason text;
alter table public.near_miss_reports add column if not exists revision_requested_by_user_id bigint;
alter table public.near_miss_reports add column if not exists revision_requested_at timestamptz;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'near_miss_reports_revision_requester_fk'
          and conrelid = 'public.near_miss_reports'::regclass
    ) then
        alter table public.near_miss_reports
            add constraint near_miss_reports_revision_requester_fk
            foreign key (revision_requested_by_user_id) references public.users(id)
            on delete restrict;
    end if;
end $$;

comment on column public.near_miss_reports.revision_request_reason is
    'Reason a report was sent back for improvement rework (IN_REVIEW→SUBMITTED). Distinct from rejection_reason.';
comment on column public.near_miss_reports.revision_requested_by_user_id is
    'FK to users(id): who requested the improvement rework (반송 요청자).';

-- =========================================================================
-- 2) near_miss_improvements — 개선조치(CAPA). report 와 엄격 1:1(report_id UNIQUE).
-- =========================================================================
create table if not exists public.near_miss_improvements (
    id bigint generated by default as identity primary key,

    -- 1:1 확정: report 당 개선조치는 한 건(UNIQUE). 부모 report 삭제는 restrict.
    report_id bigint not null references public.near_miss_reports(id) on delete restrict,

    -- 조치 담당자(assignee) / 사전 지정 확인자 / 실제 확인 행위자.
    --   designated_confirmer_user_id(사전 지정) 와 confirmed_by_user_id(실제 확인)는
    --   분리한다 — "누구로 지정했는가"와 "누가 실제로 확인했는가"를 혼동하지 않는다(Codex ④).
    assignee_user_id bigint references public.users(id) on delete restrict,
    designated_confirmer_user_id bigint references public.users(id) on delete restrict,
    confirmed_by_user_id bigint references public.users(id) on delete restrict,

    action_body text not null default '',                 -- 조치 내용
    result_body text not null default '',                 -- 조치 결과
    due_date date,                                        -- 조치 기한

    -- 통제 코드(자유문자 금지). submit=제출 라이프사이클, confirm=확인 라이프사이클.
    submit_status text not null default 'DRAFT',
    confirm_status text not null default 'PENDING',

    submitted_at timestamptz,                             -- 제출 시각(SUBMITTED)
    confirmed_at timestamptz,                             -- 실제 확인 시각(CONFIRMED)
    rejected_by_user_id bigint references public.users(id) on delete restrict,
    rejected_at timestamptz,                              -- 반려 시각(REJECTED)
    revision_note text,                                   -- 조치 반려 사유

    is_active boolean not null default true,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    created_by text,
    updated_by text,

    -- report 1:1.
    constraint near_miss_improvement_report_uniq unique (report_id),

    -- 통제 코드 도메인(자유문자 금지).
    constraint near_miss_improvement_submit_status_check
        check (submit_status in ('DRAFT', 'SUBMITTED')),
    constraint near_miss_improvement_confirm_status_check
        check (confirm_status in ('PENDING', 'CONFIRMED', 'REJECTED')),

    -- 제출 라이프사이클 정합:
    --   DRAFT     ⇒ submitted_at IS NULL AND confirm_status='PENDING'
    --   SUBMITTED ⇒ submitted_at IS NOT NULL AND assignee IS NOT NULL AND result_body 비어있지 않음
    constraint near_miss_improvement_submit_consistency check (
        case submit_status
            when 'DRAFT' then submitted_at is null and confirm_status = 'PENDING'
            when 'SUBMITTED' then submitted_at is not null
                                 and assignee_user_id is not null
                                 and btrim(result_body) <> ''
            else false
        end
    ),

    -- 확인 라이프사이클 정합(부분 확인/반려 방지 — report near_miss_eval_consistency 미러):
    --   CONFIRMED/REJECTED ⇒ submit_status='SUBMITTED'
    --   PENDING   ⇒ 확인/반려 행위자·시각 모두 NULL
    --   CONFIRMED ⇒ confirmed_by/confirmed_at NOT NULL AND rejected_* NULL
    --   REJECTED  ⇒ rejected_by/rejected_at NOT NULL AND confirmed_* NULL
    constraint near_miss_improvement_confirm_consistency check (
        case confirm_status
            when 'PENDING' then confirmed_by_user_id is null and confirmed_at is null
                              and rejected_by_user_id is null and rejected_at is null
            when 'CONFIRMED' then submit_status = 'SUBMITTED'
                               and confirmed_by_user_id is not null and confirmed_at is not null
                               and rejected_by_user_id is null and rejected_at is null
            when 'REJECTED' then submit_status = 'SUBMITTED'
                              and rejected_by_user_id is not null and rejected_at is not null
                              and confirmed_by_user_id is null and confirmed_at is null
            else false
        end
    ),

    -- 자기확인 방지: 실제 확인 행위자는 조치 담당자와 같을 수 없다(DB 하드 계약; facade 이중).
    constraint near_miss_improvement_no_self_confirm
        check (confirmed_by_user_id is null or confirmed_by_user_id <> assignee_user_id)
);

drop trigger if exists near_miss_improvements_set_updated_at on public.near_miss_improvements;
create trigger near_miss_improvements_set_updated_at
before update on public.near_miss_improvements
for each row execute function public.set_updated_at();

alter table public.near_miss_improvements enable row level security;

comment on table public.near_miss_improvements is
    'Near-miss improvement action (CAPA), strictly 1:1 with a near_miss_report (report_id UNIQUE). Closure of the parent report requires a CONFIRMED active row here (hard contract). Server-side service role access only until production RLS.';
comment on column public.near_miss_improvements.designated_confirmer_user_id is
    'Pre-designated confirmer (사전 지정 확인자). Not authoritative — the actual confirming actor is confirmed_by_user_id (server-derived).';
comment on column public.near_miss_improvements.confirmed_by_user_id is
    'The actor who actually confirmed (실제 확인 행위자, server-derived). Must differ from assignee (no self-confirmation).';

-- =========================================================================
-- 2b) near_miss_improvements 스키마 assertion — 부분 기존구조 묵인 방지(Codex P2).
--     기존에 다른 형태의 near_miss_improvements 가 있으면 위 create if not exists 가
--     no-op 되므로, 핵심 컬럼·제약이 실제로 존재하는지 확인하고 없으면 명확히 실패한다.
-- =========================================================================
do $$
declare
    v_missing text;
begin
    -- 핵심 컬럼 존재 확인.
    select string_agg(c, ', ') into v_missing
    from unnest(array[
        'report_id', 'assignee_user_id', 'designated_confirmer_user_id',
        'confirmed_by_user_id', 'action_body', 'result_body', 'due_date',
        'submit_status', 'confirm_status', 'submitted_at', 'confirmed_at',
        'rejected_by_user_id', 'rejected_at', 'revision_note', 'is_active'
    ]) as c
    where not exists (
        select 1 from pg_attribute
        where attrelid = 'public.near_miss_improvements'::regclass
          and attname = c
          and not attisdropped
    );
    if v_missing is not null then
        raise exception '007 스키마 불일치: near_miss_improvements 에 컬럼 누락(%). 기존 부분 구조를 수동 정합화하세요.', v_missing;
    end if;

    -- 핵심 제약 존재 확인.
    select string_agg(c, ', ') into v_missing
    from unnest(array[
        'near_miss_improvement_report_uniq',
        'near_miss_improvement_submit_status_check',
        'near_miss_improvement_confirm_status_check',
        'near_miss_improvement_submit_consistency',
        'near_miss_improvement_confirm_consistency',
        'near_miss_improvement_no_self_confirm'
    ]) as c
    where not exists (
        select 1 from pg_constraint
        where conname = c
          and conrelid = 'public.near_miss_improvements'::regclass
    );
    if v_missing is not null then
        raise exception '007 스키마 불일치: near_miss_improvements 에 제약 누락(%). 기존 부분 구조를 수동 정합화하세요.', v_missing;
    end if;
end $$;

-- =========================================================================
-- 3) 인덱스
-- =========================================================================
-- report_id UNIQUE 는 near_miss_improvement_report_uniq 제약이 인덱스를 겸한다.
-- 종결 대기 큐: 활성 개선조치의 확인 상태별 조회.
create index if not exists near_miss_improvement_confirm_active_idx
    on public.near_miss_improvements(confirm_status) where is_active;
-- overdue: 미확인 활성 개선조치의 기한.
create index if not exists near_miss_improvement_overdue_idx
    on public.near_miss_improvements(due_date)
    where is_active and confirm_status <> 'CONFIRMED';

-- =========================================================================
-- 4) BEFORE UPDATE trigger — 확인된 활성 개선조치 없이는 report 를 CLOSED 로 만들 수 없다.
--    UI/facade/RPC 어느 경로로 UPDATE 하더라도 이 트리거가 최종 하드 계약을 강제한다.
--    security definer + search_path 고정 + schema-qualified 참조로 하드닝한다.
-- =========================================================================
create or replace function public.near_miss_close_requires_confirmed_capa()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if new.status = 'CLOSED' and old.status is distinct from 'CLOSED' then
        if not exists (
            select 1 from public.near_miss_improvements
            where report_id = new.id
              and is_active
              and confirm_status = 'CONFIRMED'
        ) then
            raise exception '아차사고 보고서 % 는 확인(CONFIRMED)된 활성 개선조치가 있어야 종결할 수 있습니다.', new.id;
        end if;
    end if;
    return new;
end;
$$;

drop trigger if exists near_miss_close_requires_confirmed_capa on public.near_miss_reports;
create trigger near_miss_close_requires_confirmed_capa
before update on public.near_miss_reports
for each row execute function public.near_miss_close_requires_confirmed_capa();

-- =========================================================================
-- 5) 강등 방어 trigger — CLOSED 된 보고서의 확인된 활성 개선조치는 사후에 무를 수 없다.
--    (confirm_status 강등·is_active=false·삭제 시도를 거부해 하드 계약이 사후에 깨지지
--     않게 한다 — Codex P2 "거부" 권고안.)
-- =========================================================================
create or replace function public.near_miss_improvement_guard_closed_parent()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_parent_status text;
begin
    select status into v_parent_status
    from public.near_miss_reports
    where id = old.report_id;

    -- 부모가 CLOSED 이고, 대상 행이 종결의 근거였던 "확인된 활성 개선조치"인 경우만 보호한다.
    if v_parent_status is distinct from 'CLOSED'
       or not (old.is_active and old.confirm_status = 'CONFIRMED') then
        if tg_op = 'DELETE' then
            return old;
        end if;
        return new;
    end if;

    if tg_op = 'DELETE' then
        raise exception '종결(CLOSED)된 보고서 % 의 확인된 개선조치는 삭제할 수 없습니다.', old.report_id;
    end if;

    if new.confirm_status is distinct from 'CONFIRMED' or new.is_active is distinct from true then
        raise exception '종결(CLOSED)된 보고서 % 의 확인된 개선조치는 강등·비활성화할 수 없습니다.', old.report_id;
    end if;

    return new;
end;
$$;

drop trigger if exists near_miss_improvement_guard_closed_parent on public.near_miss_improvements;
create trigger near_miss_improvement_guard_closed_parent
before update or delete on public.near_miss_improvements
for each row execute function public.near_miss_improvement_guard_closed_parent();

-- =========================================================================
-- 6) 확인+종결 하드게이트 원자 RPC — close_near_miss_report.
--    단일 트랜잭션에서 (1) actor 재조회·인가 (2) 확인된 활성 개선조치 존재 (3) 조건부
--    CLOSED 전이(stale 차단)를 수행한다. 인자(actor 사번)는 신뢰하지 않고 재조회한다.
--    (4)의 트리거가 동일 계약을 이중 방어한다.
-- =========================================================================
create or replace function public.close_near_miss_report(p_report_id bigint, p_actor_emp_no text)
returns public.near_miss_reports
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_actor public.users%rowtype;
    v_report public.near_miss_reports%rowtype;
begin
    -- (1) actor 재조회(인자 신뢰 금지) — 활성 + 평가 능력(ADMIN/MANAGER 또는 안전담당자).
    --     사번 비교는 trim+대소문자 무시(원본은 변환하지 않고 저장값 그대로 사용).
    select * into v_actor
    from public.users
    where btrim(lower(emp_no)) = btrim(lower(coalesce(p_actor_emp_no, '')))
    order by (emp_no = p_actor_emp_no) desc, is_active desc
    limit 1;
    if not found then
        raise exception '종결 행위자 사번을 확인할 수 없습니다: %', p_actor_emp_no;
    end if;
    if not coalesce(v_actor.is_active, false) then
        raise exception '종결 권한이 없습니다: 비활성 사용자입니다(%).', p_actor_emp_no;
    end if;
    if not (upper(coalesce(v_actor.role, '')) in ('ADMIN', 'MANAGER')
            or coalesce(v_actor.is_safety_officer, false)) then
        raise exception '아차사고 종결 권한이 없습니다(관리자·매니저·안전담당자만 가능): %', p_actor_emp_no;
    end if;

    -- (2) 확인된 활성 개선조치 존재 확인(없으면 종결 불가).
    if not exists (
        select 1 from public.near_miss_improvements
        where report_id = p_report_id
          and is_active
          and confirm_status = 'CONFIRMED'
    ) then
        raise exception '보고서 % 는 확인(CONFIRMED)된 활성 개선조치가 없어 종결할 수 없습니다.', p_report_id;
    end if;

    -- (3) 조건부 CLOSED 전이 — EVALUATED 에서만(다른 상태/동시전이는 0행=stale 로 거부).
    update public.near_miss_reports
    set status = 'CLOSED',
        updated_by = v_actor.emp_no
    where id = p_report_id
      and status = 'EVALUATED'
    returning * into v_report;
    if not found then
        raise exception '보고서 % 를 종결할 수 없습니다(EVALUATED 상태가 아니거나 이미 변경됨).', p_report_id;
    end if;

    return v_report;
end;
$$;

-- SECURITY DEFINER 하드닝: 기본 EXECUTE 권한을 회수하고 service_role 에만 부여한다.
--   (클라이언트 역할 anon/authenticated 가 정의자 권한으로 종결 RPC 를 호출하는 경로 차단.)
revoke execute on function public.close_near_miss_report(bigint, text) from public;
revoke execute on function public.close_near_miss_report(bigint, text) from anon;
revoke execute on function public.close_near_miss_report(bigint, text) from authenticated;
grant execute on function public.close_near_miss_report(bigint, text) to service_role;

comment on function public.close_near_miss_report(bigint, text) is
    'Atomic near-miss closure hard-gate (SECURITY DEFINER). Re-derives the actor from users (does not trust the argument), requires evaluation capability + active, requires a CONFIRMED active improvement, and conditionally transitions the report EVALUATED->CLOSED (stale-safe). EXECUTE restricted to service_role.';

-- 검증용(선택, read-only): 확인된 활성 개선조치가 없는 CLOSED 보고서가 없어야 한다(계약 위반 탐지).
--   select r.id from public.near_miss_reports r
--    where r.status = 'CLOSED'
--      and not exists (select 1 from public.near_miss_improvements i
--                       where i.report_id = r.id and i.is_active and i.confirm_status = 'CONFIRMED');
