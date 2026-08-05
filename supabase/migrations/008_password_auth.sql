-- 008: 비밀번호 인증 + 서버측 로그인 세션 — users 비번 컬럼 + login_sessions 테이블.
--
-- 목적 (사용자 승인 전 DRAFT — 실행/원격 write 금지, 사용자 승인 게이트):
--   베타 배포를 앞두고 "사번만 입력하면 그 사람으로 로그인" 하던 MVP 인증을 비밀번호
--   인증으로 올린다. 동시에 토큰-세션 매핑을 컨테이너 로컬 파일(.local_sessions.json)에서
--   서버 테이블로 옮긴다 — Streamlit Cloud 파일시스템은 휘발성이라 재배포·재시작마다
--   전원 로그아웃되며, 비번이 생기는 순간 이 마찰이 "재배포마다 전원 비번 재입력"이 된다.
--   modules/auth.py 의 "Phase 5 에서는 login_sessions 테이블로 교체한다" 예고를 이행한다.
--
-- 순차·의존 (007 뒤):
--   public.users 와 public.set_updated_at() 이 이미 존재한다고 가정한다(001 이후 항상 참).
--   아래 (0) 스키마 assertion 이 전제 부재를 조용히 넘기지 않고 명확히 실패시킨다.
--
-- 인증 정책 (사용자 승인 2026-08-05):
--   * 초기 비밀번호 = 사번. 최초 로그인 시 변경 강제.
--   * 초기 비밀번호에는 유효기간을 둔다(기본 7일) — 방치된 계정을 남이 먼저 선점해
--     비번을 설정하고 본인을 잠가버리는 창을 닫는다. 특히 ADMIN 계정에서 치명적이다.
--   * 새 비밀번호 최소 8자, 사번과 동일한 값 금지. 특수문자 강제 없음(현장 마찰 대비 실익 낮음).
--   * 분실 시 ADMIN 이 사번으로 재초기화 → 다시 최초변경 강제.
--
-- 초기 상태의 표현 (password_hash IS NULL):
--   기존 사용자에게 hash(사번) 을 미리 채우려면 pgcrypto + 앱측 bcrypt 의존성이 필요해진다.
--   대신 password_hash IS NULL 을 "아직 비번 미설정 = 사번이 곧 비밀번호" 상태로 정의한다.
--   그 결과 이 migration 은 기존 행의 값을 단 한 줄도 쓰지 않는다(컬럼 추가와 기본값뿐).
--   해시 알고리즘은 앱이 소유하며(파이썬 표준 hashlib.scrypt), 저장 문자열 자체에
--   알고리즘·파라미터가 들어가므로(scrypt$n$r$p$salt$hash) DB 는 알고리즘을 알 필요가 없다.
--
-- 세션 토큰은 원문을 저장하지 않는다:
--   login_sessions.token_hash 는 토큰의 sha256 이다. DB 덤프가 유출되어도 그 값으로는
--   세션을 재생할 수 없다(원문 토큰은 브라우저 쿠키에만 존재). 이는 비번 해시와 같은 이유다.
--
-- 안전 계약 (001/004/006/007 관행 준수):
--   * 어떤 테이블도 drop 하지 않고 기존 행·값을 삭제·덮어쓰지 않는다.
--   * 재실행 안전: 모든 문장이 guarded (add column if not exists, create table if not exists,
--     create index if not exists, do-block 제약 확인 후 추가).
--   * RLS 는 enable 하되 policy 는 두지 않는다(service role 서버 접근만 — 001/004/006/007 관행).
--   * CREATE TABLE IF NOT EXISTS 만으로 "부분적으로 다른 기존 구조"를 묵인하지 않는다:
--     (3) 스키마 assertion 이 핵심 컬럼·제약 존재를 확인하고, 없으면 RAISE 한다.
--
-- 신뢰 경계 (007 과 동일한 선긋기 — 과장 금지):
--   이 migration 은 비밀번호 **검증**을 DB 로 옮기지 않는다. 해시 계산·비교·잠금 판정은
--   전부 앱 계층(modules/auth.py)이 수행하며, DB 는 자격증명의 저장 형태와 상태 정합
--   (해시 없는데 설정시각만 있는 반쪽 상태 금지 등)만 보장한다. 앱이 service_role 로
--   접근하는 현재 구조에서 "누가 실제로 호출했는가"의 인증은 여전히 앱 계층 소관이다.
--
-- live schema 재확인·적용은 사용자 승인 게이트(AGENTS.md)다 — 이 파일은 작성까지만이며
-- 실제 실행/원격 write 는 하지 않는다.
--
-- 수동 롤백 (역순; 008 이전 데이터 유지):
--   drop trigger if exists login_sessions_set_updated_at on public.login_sessions;
--   drop table if exists public.login_sessions;
--   alter table public.users drop constraint if exists users_password_state_consistency;
--   alter table public.users drop constraint if exists users_password_hash_nonblank;
--   alter table public.users drop constraint if exists users_failed_login_count_nonneg;
--   alter table public.users drop column if exists locked_until;
--   alter table public.users drop column if exists failed_login_count;
--   alter table public.users drop column if exists initial_password_expires_at;
--   alter table public.users drop column if exists must_change_password;
--   alter table public.users drop column if exists password_set_at;
--   alter table public.users drop column if exists password_hash;

-- =========================================================================
-- 0) 전제 스키마 assertion — users / set_updated_at() 부재를 조용히 넘기지 않는다.
-- =========================================================================
do $$
begin
    if to_regclass('public.users') is null then
        raise exception '008 전제 위반: public.users 테이블이 없습니다(001 미적용).';
    end if;
    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.users'::regclass
          and attname in ('id', 'emp_no', 'is_active')
          and not attisdropped
        having count(*) = 3
    ) then
        raise exception '008 전제 위반: users 에 필요한 컬럼(id/emp_no/is_active)이 없습니다(001 구조 불일치).';
    end if;
    if not exists (
        select 1 from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public' and p.proname = 'set_updated_at'
    ) then
        raise exception '008 전제 위반: public.set_updated_at() 함수가 없습니다(001 미적용).';
    end if;
end $$;

-- =========================================================================
-- 1) users: 비밀번호 자격증명 컬럼
--    password_hash IS NULL = 아직 비번 미설정(사번이 곧 비밀번호). 앱이 이 상태를 읽어
--    초기 비번 경로로 분기하고, 성공 시 즉시 변경을 강제한다.
-- =========================================================================
alter table public.users add column if not exists password_hash text;
alter table public.users add column if not exists password_set_at timestamptz;
alter table public.users add column if not exists must_change_password boolean not null default true;
alter table public.users add column if not exists initial_password_expires_at timestamptz;
alter table public.users add column if not exists failed_login_count integer not null default 0;
alter table public.users add column if not exists locked_until timestamptz;

comment on column public.users.password_hash is
    'Password hash in self-describing form "scrypt$n$r$p$salt_b64$hash_b64". NULL means the password has never been set: the initial password is the employee number itself (must_change_password enforces immediate change). The algorithm lives in the app (stdlib hashlib.scrypt), not in the DB.';
comment on column public.users.password_set_at is
    'When the user last set their own password. NULL while password_hash is NULL.';
comment on column public.users.must_change_password is
    'True forces a password change before any other screen is reachable. Set on creation and on ADMIN reset; cleared only when the user sets their own password.';
comment on column public.users.initial_password_expires_at is
    'Deadline for using the initial (employee-number) password. NULL = no expiry. Past due, the app refuses the initial password and requires an ADMIN reset — closes the window where an unclaimed account (especially ADMIN) can be seized by anyone who knows the employee number.';
comment on column public.users.failed_login_count is
    'Consecutive failed password attempts; reset to 0 on success. Drives locked_until.';
comment on column public.users.locked_until is
    'Login is refused until this instant. NULL = not locked. Set by the app after repeated failures.';

-- 해시가 있다면 공백일 수 없다(빈 문자열 해시로 인증을 우회하는 반쪽 상태 차단).
do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'users_password_hash_nonblank'
          and conrelid = 'public.users'::regclass
    ) then
        alter table public.users
            add constraint users_password_hash_nonblank check (
                password_hash is null or btrim(password_hash) <> ''
            );
    end if;
end $$;

-- 비번 상태 정합: 해시가 없는데 "설정 시각"만 남은 반쪽 상태를 금지한다.
--   password_hash IS NULL  ⇒ password_set_at IS NULL
--   (역은 강제하지 않는다 — 향후 해시만 이관하는 경로를 막지 않기 위해.)
do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'users_password_state_consistency'
          and conrelid = 'public.users'::regclass
    ) then
        alter table public.users
            add constraint users_password_state_consistency check (
                password_hash is not null or password_set_at is null
            );
    end if;
end $$;

-- 실패 카운트는 음수가 될 수 없다(감소 경로 버그가 잠금 로직을 무력화하는 것 차단).
do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'users_failed_login_count_nonneg'
          and conrelid = 'public.users'::regclass
    ) then
        alter table public.users
            add constraint users_failed_login_count_nonneg check (failed_login_count >= 0);
    end if;
end $$;

-- =========================================================================
-- 2) login_sessions — 서버측 로그인 세션. .local_sessions.json 을 대체한다.
--    원문 토큰은 저장하지 않는다(token_hash = sha256(token)). 원문은 브라우저 쿠키에만 있다.
-- =========================================================================
create table if not exists public.login_sessions (
    id bigint generated by default as identity primary key,

    -- 세션 조회 키. 원문 토큰의 sha256 hex. UNIQUE 가 조회 인덱스를 겸한다.
    token_hash text not null,

    -- 세션 주체. 세션은 업무 이력이 아니라 파생 상태이므로 사용자 삭제 시 함께 정리한다
    --   (프로젝트 기본 관행인 on delete restrict 를 여기서만 벗어나는 의도된 예외 —
    --    restrict 로 두면 사용자 삭제가 죽은 세션 때문에 막힌다. 실제 운영에서 사용자는
    --    is_active 소프트 삭제가 원칙이라 이 경로는 드물다).
    user_id bigint not null references public.users(id) on delete cascade,

    -- 조회·감사 편의를 위한 사번 스냅샷. 권위 값은 user_id 이며, 이 컬럼으로 조인하지 않는다.
    emp_no text not null,

    issued_at timestamptz not null default now(),
    expires_at timestamptz not null,
    last_seen_at timestamptz,

    -- 명시적 로그아웃·비번 변경·ADMIN 초기화 시 채운다. NULL 이 아니면 만료 여부와 무관하게 무효.
    revoked_at timestamptz,
    revoked_reason text,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint login_sessions_token_hash_uniq unique (token_hash),
    constraint login_sessions_token_hash_nonblank check (btrim(token_hash) <> ''),
    constraint login_sessions_emp_no_nonblank check (btrim(emp_no) <> ''),
    constraint login_sessions_expiry_after_issue check (expires_at > issued_at),
    -- 폐기 사유는 폐기 시각과 함께만 존재한다(사유만 남은 반쪽 상태 금지).
    constraint login_sessions_revoke_consistency check (
        revoked_at is not null or revoked_reason is null
    )
);

drop trigger if exists login_sessions_set_updated_at on public.login_sessions;
create trigger login_sessions_set_updated_at
before update on public.login_sessions
for each row execute function public.set_updated_at();

alter table public.login_sessions enable row level security;

comment on table public.login_sessions is
    'Server-side login sessions, replacing the ephemeral .local_sessions.json fallback (container filesystems are wiped on every redeploy). Stores sha256(token), never the token itself. Server-side service role access only until production RLS policies are defined.';
comment on column public.login_sessions.token_hash is
    'sha256 hex of the session token. The plaintext token exists only in the browser cookie, so a DB dump cannot be replayed as a session.';
comment on column public.login_sessions.emp_no is
    'Employee-number snapshot for lookup/audit convenience. user_id is authoritative; do not join on this column.';
comment on column public.login_sessions.revoked_at is
    'Explicit invalidation (logout, password change, ADMIN reset). A revoked session is invalid regardless of expires_at.';

-- =========================================================================
-- 3) 스키마 assertion — 부분 기존구조 묵인 방지(007 2b 관행).
--    기존에 다른 형태의 login_sessions / users 비번 컬럼이 있으면 위 guarded DDL 이
--    조용히 no-op 되므로, 핵심 컬럼·제약이 실제로 존재하는지 확인하고 없으면 실패시킨다.
-- =========================================================================
do $$
declare
    v_missing text;
begin
    -- users 비번 컬럼 존재 확인.
    select string_agg(c, ', ') into v_missing
    from unnest(array[
        'password_hash', 'password_set_at', 'must_change_password',
        'initial_password_expires_at', 'failed_login_count', 'locked_until'
    ]) as c
    where not exists (
        select 1 from pg_attribute
        where attrelid = 'public.users'::regclass
          and attname = c
          and not attisdropped
    );
    if v_missing is not null then
        raise exception '008 스키마 불일치: users 에 비번 컬럼 누락(%). 기존 부분 구조를 수동 정합화하세요.', v_missing;
    end if;

    -- must_change_password 는 NOT NULL + default 여야 한다(NULL 이면 강제변경 판정이 통째로 새어나간다).
    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.users'::regclass
          and attname = 'must_change_password'
          and atttypid = 'boolean'::regtype and attnotnull and not attisdropped
    ) then
        raise exception '008 스키마 불일치: users.must_change_password 는 boolean NOT NULL 이어야 합니다.';
    end if;
    if not exists (
        select 1 from pg_attribute a
        join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
        where a.attrelid = 'public.users'::regclass and a.attname = 'must_change_password'
    ) then
        raise exception '008 스키마 불일치: users.must_change_password 의 기본값(default)이 없습니다.';
    end if;
    if not exists (
        select 1 from pg_attribute
        where attrelid = 'public.users'::regclass
          and attname = 'failed_login_count'
          and atttypid = 'integer'::regtype and attnotnull and not attisdropped
    ) then
        raise exception '008 스키마 불일치: users.failed_login_count 는 integer NOT NULL 이어야 합니다.';
    end if;

    -- users 비번 제약 존재 확인.
    select string_agg(c, ', ') into v_missing
    from unnest(array[
        'users_password_hash_nonblank',
        'users_password_state_consistency',
        'users_failed_login_count_nonneg'
    ]) as c
    where not exists (
        select 1 from pg_constraint
        where conname = c
          and conrelid = 'public.users'::regclass
    );
    if v_missing is not null then
        raise exception '008 스키마 불일치: users 비번 제약 누락(%).', v_missing;
    end if;

    -- login_sessions 핵심 컬럼 존재 확인.
    if to_regclass('public.login_sessions') is null then
        raise exception '008 스키마 불일치: public.login_sessions 테이블이 생성되지 않았습니다.';
    end if;
    select string_agg(c, ', ') into v_missing
    from unnest(array[
        'token_hash', 'user_id', 'emp_no', 'issued_at', 'expires_at',
        'last_seen_at', 'revoked_at', 'revoked_reason'
    ]) as c
    where not exists (
        select 1 from pg_attribute
        where attrelid = 'public.login_sessions'::regclass
          and attname = c
          and not attisdropped
    );
    if v_missing is not null then
        raise exception '008 스키마 불일치: login_sessions 에 컬럼 누락(%). 기존 부분 구조를 수동 정합화하세요.', v_missing;
    end if;

    -- login_sessions 핵심 제약 존재 확인.
    select string_agg(c, ', ') into v_missing
    from unnest(array[
        'login_sessions_token_hash_uniq',
        'login_sessions_token_hash_nonblank',
        'login_sessions_expiry_after_issue',
        'login_sessions_revoke_consistency'
    ]) as c
    where not exists (
        select 1 from pg_constraint
        where conname = c
          and conrelid = 'public.login_sessions'::regclass
    );
    if v_missing is not null then
        raise exception '008 스키마 불일치: login_sessions 제약 누락(%).', v_missing;
    end if;

    -- users 로의 FK 존재 확인(이름 미지정 인라인 FK 포함).
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.login_sessions'::regclass
          and contype = 'f' and confrelid = 'public.users'::regclass
    ) then
        raise exception '008 스키마 불일치: login_sessions 에서 users 로의 FK(user_id)가 없습니다.';
    end if;
end $$;

-- =========================================================================
-- 4) 인덱스
--    token_hash UNIQUE 는 login_sessions_token_hash_uniq 제약이 인덱스를 겸한다(조회 주경로).
-- =========================================================================
-- 사용자별 활성 세션 조회 + 비번 변경/초기화 시 일괄 폐기.
create index if not exists login_sessions_user_active_idx
    on public.login_sessions(user_id) where revoked_at is null;
-- 만료 세션 정리(주기적 lazy cleanup).
create index if not exists login_sessions_expires_idx
    on public.login_sessions(expires_at) where revoked_at is null;

-- 검증용(선택, read-only):
--   -- 활성 세션 수: select count(*) from public.login_sessions
--   --                where revoked_at is null and expires_at > now();
--   -- 비번 미설정 사용자: select emp_no from public.users where password_hash is null and is_active;
