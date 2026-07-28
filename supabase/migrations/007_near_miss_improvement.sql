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
--   종결/재개 RPC 는 SECURITY DEFINER 로 (facade 가 지목한 행위자의) 활성·능력 검증과
--   상태 게이트를 원자 트랜잭션에서 강제하되, PUBLIC/anon/authenticated 의 EXECUTE 를
--   회수하고 service_role 에만 부여한다. search_path 를 고정하고 모든 객체를
--   schema-qualified 로 참조해 권한 상승 경로를 막는다.
--
-- 신뢰 경계 (Codex P2-3 — 종합감사 P2 정정):
--   RPC 인자 p_actor_emp_no 는 신뢰된 service-role 호출자(facade)가 전달한 권위 사번이며,
--   RPC 는 이 값을 "행위자의 신원"으로 신뢰한다(신원 자체의 인증은 앱 계층의 신뢰경계이지
--   DB 가 하는 일이 아니다 — 과장 금지). RPC 가 검증하는 것은 그 신원이 아니라 그 사용자의
--   is_active·능력(ADMIN/MANAGER 또는 안전담당자)이며, users 에서 재조회해 확인한다(전달된
--   role/능력 주장은 신뢰하지 않는다). 즉 DB 는 구조·상태 불변식과 "지목된 행위자가 능력이
--   있는가"만 보장하고, "누가 실제로 호출했는가"의 인증은 앱 계층 소관이다. 클라이언트
--   역할(anon/authenticated)은 EXECUTE 가 회수되어 RPC 를 직접 호출할 수 없다.
--
-- 적용 시 확인(환경 의존 — 마이그레이션에서 강제하기 어려움, Codex P2-3):
--   * SECURITY DEFINER 함수의 owner 가 최소권한 역할인지(과도한 소유자 권한 상속 방지).
--   * public 스키마에 대한 임의 CREATE 통제(필요 시 REVOKE CREATE ON SCHEMA public FROM public
--     검토) — 정의자 search_path 선행 스키마에 악성 동명 객체가 심어지지 않도록.
--   위 두 항목은 프로젝트 DB 역할 구성에 의존하므로 적용 게이트에서 확인한다.
--
-- live schema 재확인·적용은 사용자 승인 게이트(AGENTS.md)다 — 이 파일은 작성까지만이며
-- 실제 실행/원격 write 는 하지 않는다.
--
-- 수동 롤백 (역순; 007 이전 데이터 유지):
--   drop trigger if exists near_miss_close_requires_confirmed_capa on public.near_miss_reports;
--   drop trigger if exists near_miss_improvement_guard_closed_parent on public.near_miss_improvements;
--   drop trigger if exists near_miss_improvement_report_id_immutable on public.near_miss_improvements;
--   drop function if exists public.reopen_near_miss_report(bigint, text);
--   drop function if exists public.close_near_miss_report(bigint, text);
--   drop function if exists public.near_miss_close_requires_confirmed_capa();
--   drop function if exists public.near_miss_improvement_guard_closed_parent();
--   drop function if exists public.near_miss_improvement_report_id_immutable();
--   drop table if exists public.near_miss_improvements;
--   alter table public.near_miss_reports drop constraint if exists near_miss_reports_revision_request_all_or_none;
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

-- 보완요청 3필드 전부-아니면-전무 정합(P2-2): 세 필드는 함께 채워지거나 함께 비어야 한다
--   (부분 기록으로 "누가/언제 없이 사유만" 같은 반쪽 상태를 막는다). 반려사유(reason)는
--   nonblank 까지 강제한다.
do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'near_miss_reports_revision_request_all_or_none'
          and conrelid = 'public.near_miss_reports'::regclass
    ) then
        alter table public.near_miss_reports
            add constraint near_miss_reports_revision_request_all_or_none check (
                (revision_request_reason is null
                    and revision_requested_by_user_id is null
                    and revision_requested_at is null)
                or (btrim(coalesce(revision_request_reason, '')) <> ''
                    and revision_requested_by_user_id is not null
                    and revision_requested_at is not null)
            );
    end if;
end $$;

-- 배선 유예(의도된 defer, P2-2): 위 보완요청 3필드를 기록하는 facade/UI 경로(평가화면의
--   "보완요청")는 다음 UI 단계에서 배선한다. 지금은 컬럼·FK·정합 CHECK 만 두고 write 경로는
--   두지 않는다(스키마 계약 선확정, 미배선 = 의도된 유예).
comment on column public.near_miss_reports.revision_request_reason is
    'Reason a report was sent back for improvement rework (IN_REVIEW→SUBMITTED). Distinct from rejection_reason. Write path deferred to a later UI step (P2-2).';
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
                              and btrim(coalesce(revision_note, '')) <> ''  -- 반려는 사유 필수(P2-2)
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

    -- 핵심 컬럼 타입·NOT NULL 검증(동명 컬럼이 다른 타입/nullable 로 존재하는 부분구조 차단, P2-1).
    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.near_miss_improvements'::regclass
          and attname = 'report_id' and atttypid = 'bigint'::regtype and attnotnull and not attisdropped
    ) then
        raise exception '007 스키마 불일치: report_id 는 bigint NOT NULL 이어야 합니다.';
    end if;
    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.near_miss_improvements'::regclass
          and attname = 'submit_status' and atttypid = 'text'::regtype and attnotnull and not attisdropped
    ) then
        raise exception '007 스키마 불일치: submit_status 는 text NOT NULL 이어야 합니다.';
    end if;
    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.near_miss_improvements'::regclass
          and attname = 'confirm_status' and atttypid = 'text'::regtype and attnotnull and not attisdropped
    ) then
        raise exception '007 스키마 불일치: confirm_status 는 text NOT NULL 이어야 합니다.';
    end if;
    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.near_miss_improvements'::regclass
          and attname = 'is_active' and atttypid = 'boolean'::regtype and attnotnull and not attisdropped
    ) then
        raise exception '007 스키마 불일치: is_active 는 boolean NOT NULL 이어야 합니다.';
    end if;

    -- 핵심 컬럼 default 존재 검증(통제코드/활성 기본값 부재 차단, P2-1).
    for v_missing in
        select c from unnest(array['submit_status', 'confirm_status', 'is_active']) as c
        where not exists (
            select 1 from pg_attribute a
            join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
            where a.attrelid = 'public.near_miss_improvements'::regclass and a.attname = c
        )
    loop
        raise exception '007 스키마 불일치: 컬럼 % 의 기본값(default)이 없습니다.', v_missing;
    end loop;

    -- report/user FK 존재 검증(1:1 부모·행위자 참조 무결성; 이름 미지정 인라인 FK 포함, P2-1).
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.near_miss_improvements'::regclass
          and contype = 'f' and confrelid = 'public.near_miss_reports'::regclass
    ) then
        raise exception '007 스키마 불일치: near_miss_reports 로의 FK(report_id)가 없습니다.';
    end if;
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.near_miss_improvements'::regclass
          and contype = 'f' and confrelid = 'public.users'::regclass
    ) then
        raise exception '007 스키마 불일치: users 로의 FK(assignee/confirmer 등)가 없습니다.';
    end if;

    -- 핵심 CHECK 정의 내용 검증(동명 오제약 차단 — 이름만 같고 조건이 다른 제약 방지, P2-1).
    if not exists (
        select 1 from pg_constraint
        where conname = 'near_miss_improvement_no_self_confirm'
          and conrelid = 'public.near_miss_improvements'::regclass
          and pg_get_constraintdef(oid) ilike '%confirmed_by_user_id%<>%assignee_user_id%'
    ) then
        raise exception '007 스키마 불일치: 자기확인 방지 CHECK 정의가 기대와 다릅니다.';
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'near_miss_improvement_submit_consistency'
          and conrelid = 'public.near_miss_improvements'::regclass
          and pg_get_constraintdef(oid) ilike '%submit_status%'
    ) then
        raise exception '007 스키마 불일치: submit 정합 CHECK 정의가 기대와 다릅니다.';
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'near_miss_improvement_confirm_consistency'
          and conrelid = 'public.near_miss_improvements'::regclass
          and pg_get_constraintdef(oid) ilike '%confirm_status%'
    ) then
        raise exception '007 스키마 불일치: confirm 정합 CHECK 정의가 기대와 다릅니다.';
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
    -- 이 트리거는 구조 불변식만 담당한다: 행위자 능력·인가(누가 종결하는가)는 close RPC/
    -- facade 계층 소관이고, 여기서는 "CLOSED 는 오직 EVALUATED 에서, 그리고 확인된 활성
    -- 개선조치가 있을 때만" 이라는 상태·데이터 불변식을 어느 UPDATE 경로로도 강제한다.
    if new.status = 'CLOSED' and old.status is distinct from 'CLOSED' then
        -- 유일 허용 소스: EVALUATED. 직접 SQL 로 IN_REVIEW/SUBMITTED 등에서 곧장 CLOSED 로
        -- 넘기는 것을 차단한다(Codex P1-3 — 확인 CAPA 만 있으면 통과하던 구멍 봉합).
        if old.status is distinct from 'EVALUATED' then
            raise exception '아차사고 보고서 % 는 EVALUATED 상태에서만 종결할 수 있습니다(현재 상태: %).', new.id, old.status;
        end if;
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
-- 4b) report_id 불변 trigger — 개선조치의 report_id 는 부모 보고서와의 identity 결속이라
--     어떤 UPDATE 로도 변경할 수 없다(확정 불변식 ③ "개선조치 report_id 불변").
--     report_id UNIQUE·FK 는 삽입 무결성만 보장하고 UPDATE 이동(다른 report 로 재귀속)은
--     막지 못한다. 강등방어 trigger(아래 5)의 report_id 검사는 부모 CLOSED + 대상 행이
--     확인된 활성 개선조치인 분기 안에서만 동작하므로, 조기반환되는 DRAFT/PENDING/REJECTED
--     행이나 부모가 EVALUATED 인 CONFIRMED CAPA 는 다른 report 로 옮겨질 수 있었다(종합감사
--     P1-B). 이 trigger 는 상태·조기반환·분기와 무관하게 report_id 이동을 무조건 거부한다.
--     대상 행의 NEW/OLD 만 비교하고 다른 객체를 참조하지 않으므로 SECURITY DEFINER·별도
--     search_path 가 필요없다(최소권한 — SECURITY INVOKER 기본).
-- =========================================================================
create or replace function public.near_miss_improvement_report_id_immutable()
returns trigger
language plpgsql
as $$
begin
    if new.report_id is distinct from old.report_id then
        raise exception '개선조치의 report_id 는 변경할 수 없습니다(부모 보고서 결속 불변): % -> %.',
            old.report_id, new.report_id;
    end if;
    return new;
end;
$$;

drop trigger if exists near_miss_improvement_report_id_immutable on public.near_miss_improvements;
create trigger near_miss_improvement_report_id_immutable
before update on public.near_miss_improvements
for each row execute function public.near_miss_improvement_report_id_immutable();

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
    -- 부모 report 를 잠근 뒤 상태를 확인한다(종결 트랜잭션과 직렬화 — Codex P1-2). 이 트리거는
    -- 이미 대상 개선조치 행에 락을 쥔 채 진입하므로, 여기서 부모를 잠그면 락 순서가
    -- improvement→report 로 일관된다(close/reopen RPC 도 동일 순서 — 데드락 회피). FOR UPDATE
    -- 없이는 종결(부모 CLOSED 전이)과 강등/삭제가 서로의 전이 전 상태를 각각 읽어
    -- "CLOSED + 비확인/비활성/삭제 CAPA" 를 동시에 커밋할 수 있었다.
    select status into v_parent_status
    from public.near_miss_reports
    where id = old.report_id
    for update;

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

    -- 강등(confirm_status)·비활성화(is_active)뿐 아니라 report_id 이동(부모 재지정)도 종결
    -- 근거 제거의 일종이므로 거부한다(Codex P1-1 — report_id 를 다른 보고서로 옮겨 CLOSED
    -- 보고서의 확인 CAPA 를 빼돌리는 우회 봉합). CLOSED 부모의 확정 CAPA 는 불변이다.
    if new.confirm_status is distinct from 'CONFIRMED'
       or new.is_active is distinct from true
       or new.report_id is distinct from old.report_id then
        raise exception '종결(CLOSED)된 보고서 % 의 확인된 개선조치는 강등·비활성화·이동(report_id 변경)할 수 없습니다.', old.report_id;
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
--    단일 트랜잭션에서 (1) 행위자 활성·검토 권한 검증 (2) 확인된 활성 개선조치 존재 (3) 조건부
--    CLOSED 전이(stale 차단)를 수행한다. 인자(actor 사번)는 facade 가 확정한 행위자 신원으로
--    신뢰하되, 그 사용자의 활성·권한은 users/개선조치에서 재조회해 검증한다(전달된 능력 주장은
--    신뢰 안 함). (4)의 트리거가 동일 상태 불변식을 이중 방어한다.
--
--    CAPA 행단위 인가(의도 업무흐름 정합): 종결 주체는 **지정 확인자(designated_confirmer)
--    또는 평가자(ADMIN/MANAGER/안전담당자)** 이다. 일반 USER 라도 이 개선조치의 지정 확인자면
--    종결할 수 있고(폐루프 확인→종결의 자연 흐름), 그 밖의 일반 USER 는 종결할 수 없다. 자기
--    확인 금지(담당자 본인 confirm 차단)는 confirm 단계 CHECK 가 이미 강제하므로, 확인된 활성
--    개선조치의 존재만으로 담당자 자가종결은 발생하지 않는다.
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
    v_can_evaluate boolean;
    v_is_confirmer boolean;
begin
    -- (1) 행위자 권한 검증 — 인자 사번을 신원으로 신뢰하되 그 사용자의 활성 + 검토 권한은
    --     users/개선조치에서 재조회해 확인한다(전달된 능력 주장 불신). 사번 비교는 trim+대소
    --     문자 무시(원본은 변환하지 않고 저장값 그대로 사용).
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
    -- 평가 능력(ADMIN/MANAGER 또는 안전담당자) 또는 이 개선조치의 지정 확인자면 종결 가능.
    v_can_evaluate := (upper(coalesce(v_actor.role, '')) in ('ADMIN', 'MANAGER')
                       or coalesce(v_actor.is_safety_officer, false));
    v_is_confirmer := exists (
        select 1 from public.near_miss_improvements
        where report_id = p_report_id
          and designated_confirmer_user_id = v_actor.id
    );
    if not (v_can_evaluate or v_is_confirmer) then
        raise exception '아차사고 종결 권한이 없습니다(지정 확인자·관리자·매니저·안전담당자만 가능): %', p_actor_emp_no;
    end if;

    -- (2) 자식 개선조치 행을 먼저 잠근다(Codex P1-2 — 강등/삭제 트랜잭션과 직렬화). report 는
    --     1:1(report_id UNIQUE)이므로 최대 1행이다. 락 순서 improvement→report 로 일관되게
    --     자식(잠금 후) → 부모(아래 UPDATE) 순으로 잠가 강등방어 트리거와 데드락을 피한다.
    perform 1 from public.near_miss_improvements
    where report_id = p_report_id
    for update;

    -- (3) 확인된 활성 개선조치 존재 확인(없으면 종결 불가). 위 FOR UPDATE 로 잠근 뒤 검사하므로
    --     검사~전이 사이에 CAPA 가 강등/삭제되는 경합이 없다.
    if not exists (
        select 1 from public.near_miss_improvements
        where report_id = p_report_id
          and is_active
          and confirm_status = 'CONFIRMED'
    ) then
        raise exception '보고서 % 는 확인(CONFIRMED)된 활성 개선조치가 없어 종결할 수 없습니다.', p_report_id;
    end if;

    -- (4) 조건부 CLOSED 전이 — EVALUATED 에서만(다른 상태/동시전이는 0행=stale 로 거부).
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
    'Atomic near-miss closure hard-gate (SECURITY DEFINER). Trusts the passed emp_no as the actor identity (identity authN is the app-layer trust boundary) but re-derives that user''s is_active + review authority from users/improvement (does not trust any passed role/capability claim). Authorized closer = the improvement''s designated_confirmer OR an evaluator (ADMIN/MANAGER/safety officer); a plain USER who is the designated confirmer may close, other plain USERs may not. Requires a CONFIRMED active improvement, and conditionally transitions the report EVALUATED->CLOSED (stale-safe). EXECUTE restricted to service_role.';

-- 검증용(선택, read-only): 확인된 활성 개선조치가 없는 CLOSED 보고서가 없어야 한다(계약 위반 탐지).
--   select r.id from public.near_miss_reports r
--    where r.status = 'CLOSED'
--      and not exists (select 1 from public.near_miss_improvements i
--                       where i.report_id = r.id and i.is_active and i.confirm_status = 'CONFIRMED');

-- =========================================================================
-- 7) 재개(EVALUATED→IN_REVIEW) 원자 RPC — reopen_near_miss_report (Codex P1-4).
--    report 재개와 확인된 개선조치 초기화를 단일 트랜잭션으로 묶는다. 과거처럼 report 전이 →
--    별도 요청으로 CAPA 리셋 하는 2단계는, 중간 재종결·2차 실패·readiness 오류 시 stale
--    CONFIRMED 가 재사용되는 창을 남겼다. 이 RPC 는:
--      (1) actor 재조회·인가(close RPC 와 동일 하드닝: 활성 + 평가 능력).
--      (2) 자식 개선조치 잠금(락 순서 improvement→report 로 close/guard 와 일관, 데드락 회피).
--      (3) 조건부 report EVALUATED→IN_REVIEW + 평가필드 초기화(stale 차단).
--      (4) 활성 확인 개선조치 CONFIRMED→PENDING(confirmer/confirmed_at 초기화; result/submit/
--          due 는 보존 — 재제출 가능 상태로 되돌린다).
--    행위자 능력·인가는 RPC/facade 계층 소관, 상태 불변식은 CHECK/트리거가 이중 방어한다.
-- =========================================================================
create or replace function public.reopen_near_miss_report(p_report_id bigint, p_actor_emp_no text)
returns public.near_miss_reports
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_actor public.users%rowtype;
    v_report public.near_miss_reports%rowtype;
begin
    -- (1) 행위자 능력 검증 — 인자 사번을 신원으로 신뢰하되 그 사용자의 활성 + 평가 능력
    --     (ADMIN/MANAGER 또는 안전담당자)은 users 에서 재조회해 확인한다(전달된 능력 주장 불신).
    select * into v_actor
    from public.users
    where btrim(lower(emp_no)) = btrim(lower(coalesce(p_actor_emp_no, '')))
    order by (emp_no = p_actor_emp_no) desc, is_active desc
    limit 1;
    if not found then
        raise exception '재개 행위자 사번을 확인할 수 없습니다: %', p_actor_emp_no;
    end if;
    if not coalesce(v_actor.is_active, false) then
        raise exception '재개 권한이 없습니다: 비활성 사용자입니다(%).', p_actor_emp_no;
    end if;
    if not (upper(coalesce(v_actor.role, '')) in ('ADMIN', 'MANAGER')
            or coalesce(v_actor.is_safety_officer, false)) then
        raise exception '아차사고 재개 권한이 없습니다(관리자·매니저·안전담당자만 가능): %', p_actor_emp_no;
    end if;

    -- (2) 자식 개선조치 먼저 잠금(락 순서 improvement→report 로 close/guard 와 일관, 데드락 회피).
    --     report 는 1:1 이므로 최대 1행.
    perform 1 from public.near_miss_improvements
    where report_id = p_report_id
    for update;

    -- (3) 조건부 report EVALUATED→IN_REVIEW + 평가필드 초기화(near_miss_eval_consistency 충족,
    --     stale 차단 — EVALUATED 아니면 0행=거부).
    update public.near_miss_reports
    set status = 'IN_REVIEW',
        confirmed_grade = null,
        evaluator_user_id = null,
        evaluated_at = null,
        updated_by = v_actor.emp_no
    where id = p_report_id
      and status = 'EVALUATED'
    returning * into v_report;
    if not found then
        raise exception '보고서 % 를 재개할 수 없습니다(EVALUATED 상태가 아니거나 이미 변경됨).', p_report_id;
    end if;

    -- (4) 활성 확인 개선조치 CONFIRMED→PENDING(확인 근거가 재개 후 남지 않게). result_body/
    --     submit_status/due_date 는 보존한다(재제출 가능한 PENDING+SUBMITTED 상태). 부모는
    --     이미 IN_REVIEW 로 전이됐으므로 강등방어 트리거가 이 초기화를 막지 않는다.
    update public.near_miss_improvements
    set confirm_status = 'PENDING',
        confirmed_by_user_id = null,
        confirmed_at = null,
        updated_by = v_actor.emp_no
    where report_id = p_report_id
      and is_active
      and confirm_status = 'CONFIRMED';

    return v_report;
end;
$$;

-- SECURITY DEFINER 하드닝(close RPC 와 동일): 기본 EXECUTE 회수 + service_role 만 부여.
revoke execute on function public.reopen_near_miss_report(bigint, text) from public;
revoke execute on function public.reopen_near_miss_report(bigint, text) from anon;
revoke execute on function public.reopen_near_miss_report(bigint, text) from authenticated;
grant execute on function public.reopen_near_miss_report(bigint, text) to service_role;

comment on function public.reopen_near_miss_report(bigint, text) is
    'Atomic near-miss reopen (SECURITY DEFINER). Trusts the passed emp_no as the actor identity (identity authN is the app-layer trust boundary) but re-derives that user''s is_active + evaluation capability from users (does not trust any passed role/capability claim), and in one transaction transitions the report EVALUATED->IN_REVIEW (clearing evaluation fields) and resets the active CONFIRMED improvement to PENDING (clearing confirmer/confirmed_at, preserving result/submit/due). EXECUTE restricted to service_role.';
