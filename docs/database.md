# 데이터베이스 기준

현재 애플리케이션의 데이터 관계와 migration 계약을 설명합니다. 실제 환경의 적용 상태는 live schema를 read-only로 확인한 결과가 최종 기준입니다.

## 1. 데이터 접근

프로젝트 안전경계의 정본(SoT)은 `AGENTS.md`이며, 아래 데이터 접근·보안·삭제 관련 규칙은 migration/Supabase 운영에 필요한 도메인별 구체화입니다.

- 앱은 브라우저가 아니라 Streamlit 서버에서 Supabase에 접근합니다.
- 현재 인증은 Supabase Auth가 아닌 사번 기반 앱 세션입니다.
- service role key는 서버 환경변수 또는 `.streamlit/secrets.toml`에만 둡니다.
- `modules/db.py`가 sample/Supabase 공통 파사드이고 `modules/supabase_repository.py`가 원격 구현입니다.
- 데이터 소스 오류를 sample 모드로 자동 전환하지 않습니다.

## 2. 현재 테이블

### `organization_groups`

조직 그룹 기준정보입니다(migration 004). 그룹은 부서 데이터에서 파생되는 값이 아니라 이 테이블이 SoT인 1급 레코드이며, 귀속 부서가 없어도 존속할 수 있습니다.

- 자연키: `group_code`
- 기본 정보: `group_name`, `sort_order`, `description`, `is_active`
- 003의 `departments.department_group`/`group_sort_order` 컬럼 모델은 이 테이블로 대체되었습니다.

### `departments`

부서 기준정보입니다.

- 자연키: `dept_code`
- 기본 정보: `dept_name`, `sort_order`, `is_active`
- 조직 확장(004): `group_id`(FK → `organization_groups.id`, `on delete restrict`), `description`
- 003의 `department_group`/`group_sort_order` 컬럼 서술은 004로 대체되었습니다(위 `organization_groups` 참고).

### `teams`

부서에 속하는 운영단위입니다. 기존 A/B/C조와 일반근무 단위를 함께 저장합니다.

- 자연키: `(department_id, team_code)`
- 기본 정보: `team_name`, `sort_order`, `is_active`
- 조직 확장: `unit_type` = `SHIFT | GENERAL`
- `(id, department_id)` 복합 고유키로 타 부서 운영단위 연결을 차단합니다.

### `users`

직원 기준정보이며 Supabase Auth 사용자가 아닙니다.

- 자연키: `emp_no`
- 소속: `department_id`, 선택적 `team_id`
- 권한: `ADMIN | MANAGER | USER`
- 상태: `is_active`
- 조직 확장: 선택적 `display_order`
- 안전(006): `is_safety_officer`(기본 `false`) — 아차사고 평가 능력의 원천입니다.
- `(team_id, department_id)` 복합 FK로 소속 불일치를 차단합니다.

### `work_types`

근무형태 기준정보입니다.

- 자연키: `code`
- 명칭·표시: `name`, `short_label`, `color`, `sort_order`
- 분류·시간: `category`, `start_time`, `end_time`
- 속성: `is_work`, `affects_allowance`, `description`, `is_active`

### `work_schedules`

직원별 일자 근무입니다.

- 고유키: `(user_id, work_date)`
- 근무형태: `work_type_code`
- 선택적 월 편성 연결: `schedule_assignment_id`
- 편성 연결이 없어도 legacy 근무 행은 유효합니다.

### `schedule_assignments`

직원별 월 편성 스냅샷입니다.

- 고유키: `(user_id, schedule_month)`
- `schedule_month`는 해당 월의 1일입니다.
- `department_id`는 필수, `team_id`와 `shift_group_code`는 선택입니다.
- `team_id`는 departments/teams 관계값이며 당시 명칭 문자열을 보존하는 구조는 아닙니다.
- `shift_group_code`는 과거 기준정보 변경에 영향을 받지 않는 텍스트 스냅샷입니다.

### `shift_groups`

부서별 근무조 선택지와 검증용 기준정보입니다. 현재 화면의 A/B/C 운영단위(`teams`)와 별개의 개념이며 편성 저장의 필수값이 아닙니다.

### `near_miss_reports`

아차사고(near-miss) 보고서입니다(migration 006, DRAFT). 보고자가 등급을 제안하고 평가자(관리자·안전담당자)가 확정하는 2단계 모델입니다.

- 자연키: `report_no`(연월 `YYYYMM` + 월순번, 예 `202607-0007`). 채번은 애플리케이션이 대상 연월의 최대 순번+1로 계산하고, `unique` 제약을 충돌 최종 방어선으로 삼아 재시도합니다.
- 본문: `work_name`(필수), `work_content`, `incident_content`, `countermeasure`, `site_description`
- 등급: `proposed_grade`(보고자 제안, nullable), `confirmed_grade`(평가자 확정) — 각각 `S|A|B|C|D`
- 사람·조직 관계값(ID/FK): `reporter_user_id`(필수, `on delete restrict`), `evaluator_user_id`(평가 후), `department_id`(보고 시점 부서 귀속 — 그룹은 저장하지 않고 부서→그룹은 004 `group_id`로 read-time 파생)
- 원인: `cause_code`(통제 코드 `JAM|FALL|DROP|HIT|SLIP|BURN|PINCH|ETC`) + `cause_detail`
- 기간: `incident_date`(사고 발생일). 기간 통계는 `created_at`이 아니라 이 컬럼을 씁니다.
- 사진: `photo_paths`(jsonb 배열, Supabase Storage 경로 문자열만 — 바이너리 미저장). `jsonb_typeof = 'array'` 제약.
- 상태: `status` = `SUBMITTED|IN_REVIEW|EVALUATED|CLOSED|REJECTED`, `rejection_reason`(반려 시 필수), `evaluated_at`
- 무결성 제약: 평가 필드 3종(`confirmed_grade`/`evaluator_user_id`/`evaluated_at`)은 상태가 `EVALUATED|CLOSED`일 때만 모두 존재합니다(`near_miss_eval_consistency`).
- 보존: `is_active`는 archival 전용입니다. 철회·반려는 **상태**로 표현하며 이 플래그로 표현하지 않습니다.
- 인덱스: `(status) where is_active`(대기열), `(incident_date)`, `(department_id, incident_date)`, `(confirmed_grade)`, `(cause_code)`, `(reporter_user_id)`

## 3. 관계

```text
organization_groups
└─ departments (group_id FK, on delete restrict)
   ├─ teams
   ├─ users
   ├─ shift_groups
   └─ schedule_assignments
      └─ work_schedules (선택적 연결)

users ── work_schedules
work_types ── work_schedules
users ─< user_capabilities (on delete cascade — 담당 부여는 계정 종속 파생)
users ─< user_emails (on delete cascade — 수신처는 계정 종속 파생)

near_miss_reports
├─ reporter_user_id  → users (on delete restrict)
├─ evaluator_user_id → users (on delete restrict)
└─ department_id     → departments (보고 시점 귀속)
```

삭제 동작은 기본적으로 `RESTRICT`입니다. 과거 근무와 편성을 보존해야 하는 기준정보는 비활성화를 우선합니다.

## 4. Migration

| 파일 | 내용 | 저장소 상태 | 마지막 확인된 테스트 환경 상태 |
|---|---|---|---|
| `001_initial_schema.sql` | 기본 5개 테이블·제약·인덱스·트리거 | 기준 migration | 적용됨 |
| `002_schedule_assignments.sql` | `shift_groups`, `schedule_assignments`, 근무 연결 컬럼 | DDL 전용, 자동 백필 없음 | 2026-07-16 적용·종단 확인 |
| `003_org_structure.sql` | 조직 그룹(→004로 대체됨)·운영단위 유형·사용자 표시순서 | guarded DDL + 제한적 안전 백필 | 2026-07-20 기준 미적용 — 그룹 컬럼(`department_group`/`group_sort_order`)은 004가 대체. `unit_type`/`display_order`는 004가 호환용으로 재추가하므로 003 미적용 상태에서도 앱은 정상 동작 |
| `004_org_groups.sql` | `organization_groups` 1급 테이블 신설 + `departments.group_id` FK + 무손실 백필(경로 B) | guarded DDL + 무손실 백필, 003의 그룹 컬럼 모델 대체 | 2026-07-22 테스트 프로젝트 read-only probe 확인. 앱 코드(`modules/db.py`·`supabase_repository.py`·조직/사용자/근무형태/대시보드 화면)는 004를 권위로 전면 전환 완료 — 프로덕션 live schema 적용 여부는 세션별 read-only 확인 필요 |
| `006_near_miss.sql` | `near_miss_reports` 테이블 신설 + `users.is_safety_officer` 컬럼 | guarded DDL, no-drop, RLS enable(policyless) | 2026-08-07 테스트 프로젝트 live 확인 — `near_miss_reports` 존재(적용됨). 005는 004 후속 정리(§7)로 예약되어 있어 번호를 건너뜀 |
| `007_near_miss_improvement.sql` | `near_miss_improvements`(CAPA, report 1:1) | guarded DDL, no-drop | 2026-08-07 테스트 프로젝트 live 확인 — 테이블 존재(적용됨) |
| `008_password_auth.sql` | `users` 비밀번호 컬럼 6개 + `login_sessions` | guarded DDL, 기존 행 값 무기록, RLS enable(policyless) | DRAFT — **미적용**(2026-08-07 live 확인: `users.password_hash` 없음·`login_sessions` 없음). 적용 전까지 로그인은 고정 예외 계정만 가능 |
| `009_org_category_and_tenure.sql` | `departments.major_category/minor_category` + `users.hire_date/resign_date` + 대분류 그룹명 백필 | guarded DDL, no-drop(teams·organization_groups 보존), 빈 값에만 백필 | 2026-08-07 테스트 프로젝트 **적용·검증**(컬럼 존재 + 백필 결과 확인). 회사 계정 이전 시 새 프로젝트에 재적용 필요 |
| `010_capabilities_and_emails.sql` | `user_capabilities`(담당 권한 M:N) + `user_emails`(복수 수신 이메일, 업무 scope, `lower(email)` 유니크) | guarded DDL, no-drop, 행 무기록, RLS enable(policyless). 담당 신설은 migration 없이 앱 코드(`config.CAPABILITIES`) 등록만으로 확장 | 2026-08-07 테스트 프로젝트 **적용·왕복 검증**(부여/회수·대소문자 중복 차단·수신자 계산). recon 우수사례 조사(OWASP·Django·Discourse 선례) 반영 설계 |

위의 환경 상태는 마지막 검증 기록입니다. 새로운 세션에서 적용 또는 미적용을 단정하기 전에 반드시 live schema를 다시 확인합니다.

**009 이후의 조직 모델(2026-08-07 제품 결정)**: 화면 계층의 정본은 부서의 `major_category`/`minor_category` 자유 텍스트 2단이다. `organization_groups`·`departments.group_id`·`teams`는 **휴면 보존**된다 — drop 하지 않았고 앱 저장 경로는 기존 귀속 값을 지우지 않지만, 화면 편집 경로가 없다. A/B/C 근무조는 `teams`(운영단위)가 아니라 `schedule_assignments.shift_group_code`(자유 텍스트 스냅샷)에 저장된다.

## 5. Migration 안전 규칙

- 파일명 순서대로 적용합니다.
- 이미 적용된 migration은 적용 이력과 실제 schema 확인 없이 수정하지 않습니다.
- `create table if not exists`가 기존의 비호환 테이블을 보정해 주지는 않습니다.
- 적용 전 대상 프로젝트, 현재 컬럼·제약·행 수, 백업 가능성을 확인합니다.
- migration 실행·운영 DB 쓰기의 **승인 게이트는 `AGENTS.md` 안전경계 정본**을 따릅니다(여기서 재서술하지 않음). 이 절은 그 아래 적용 메커니즘만 정의합니다.
- 부분 적용이 의심되면 DROP으로 맞추지 않고 read-only probe 후 forward completion 가능성을 먼저 판단합니다.
- 002는 기존 근무를 현재 사용자 소속으로 자동 백필하지 않습니다.
- 004 적용 뒤에는 앱 프로세스를 재시작하거나 화면의 "스키마 재확인" 동작으로 조직 그룹 확장(`organization_groups` + `departments.group_id`) readiness cache를 다시 확인합니다.

## 6. Sample 데이터

`data/sample/*.csv`는 로컬 개발용입니다. sample 모드의 수정은 Streamlit 세션 상태에 저장되며 Supabase에 반영되지 않습니다. sample 데이터와 실DB 데이터의 행 수나 ID가 같다고 가정하지 않습니다.

## 7. 아직 확정되지 않은 변경

다음은 현재 schema 요구사항이 아닙니다.

- migration 005(가칭) — 004 후속 정리: `departments.group_id`의 NOT NULL 승격, 003 잔여 그룹 컬럼(`department_group`/`group_sort_order`) 제거. 별도 설계·사용자 승인 전 구현하지 않습니다.
- `work_schedules.schedule_assignment_id`의 NOT NULL 승격
- `work_schedules.user_id` 제거
- 운영용 RLS 정책과 Supabase Auth
- 자동 백필·과거 데이터 추정
- 별도 변경 이력·import batch 테이블

별도 사용자 요구와 migration 설계·승인 없이 선행 구현하지 않습니다.

## 8. 아차사고 상태 전이 계약 (migration 006)

상태는 `SUBMITTED → IN_REVIEW → EVALUATED → CLOSED` 진행을 기본으로 하며 `REJECTED`는 분기 상태입니다. 전이 규칙은 `modules/db.py::NEAR_MISS_TRANSITIONS`가 집행하고, DB `near_miss_eval_consistency` 제약이 평가 필드 정합을 강제합니다.

| 현재 | 허용 전이 | 행위자 | 의미 |
|---|---|---|---|
| `SUBMITTED` | `IN_REVIEW`, `EVALUATED`, `REJECTED` | 평가자(ADMIN/MANAGER/안전담당자) | 검토 착수 / 즉시 확정 / 반려 |
| `IN_REVIEW` | `EVALUATED`, `REJECTED`, `SUBMITTED` | 평가자 | 확정 / 반려 / 보고자에게 반송 |
| `EVALUATED` | `CLOSED`, `IN_REVIEW` | 평가자 | 종결 / 재개(평가 필드 초기화) |
| `REJECTED` | `SUBMITTED` | 평가자·보고자 | 재제출을 위한 재개 |
| `CLOSED` | (없음) | — | 종결 상태 |

- **보고자 수정 컷오프**: 보고자는 자신의 보고서를 `SUBMITTED` 상태에서만 수정할 수 있습니다. 검토가 착수(`IN_REVIEW`)된 뒤에는 수정할 수 없습니다.
- **보존(is_active)은 archival 전용, 철회 아님**: `is_active`는 위 "보존" 항목(§2 `near_miss_reports`)대로 **archival 전용 관리 플래그**이며 상태(status)와 직교합니다. `is_active=false`는 목록에서 감추는 관리 조작(예: 오등록 정리)일 뿐 "철회"의 의미가 아닙니다(상태는 그대로 보존, 이력 미삭제). 006에는 별도의 `WITHDRAWN` 상태가 없으므로 **보고자 자기철회는 006 범위 밖**이며(보고자에게 철회 권한을 부여하지 않음), 필요하면 별도 설계·승인으로 다룹니다.
- **행위자 신원(server-side)**: 보고자(`reporter_user_id`)·평가자(`evaluator_user_id`)·`evaluated_at`·보고 시점 부서(`department_id`)는 화면 위젯 값이 아니라 인증된 세션 사용자(`auth.get_current_user()`)에서 파사드가 서버측으로 확정합니다. 특히 부서는 세션 dict 의 값이 아니라 그 사번으로 조회한 **DB 권위 사용자 레코드**에서 다시 도출합니다(위조된 `current_user`로 타 부서 귀속 불가). 화면은 `modules/db.py::create_near_miss_report(..., current_user=...)`·`evaluate_near_miss(..., current_user=...)`에 세션 사용자를 넘겨야 하며, payload 의 신원·`created_by`/`updated_by` 필드는 무시됩니다(위조 방지·서버 확정).
- **평가(confirm) 의미**: `evaluate_near_miss`는 **평가 이전 상태(`SUBMITTED`/`IN_REVIEW`)**에서만 `EVALUATED`로 전이하며 `confirmed_grade`·`evaluator_user_id`·`evaluated_at`을 함께 설정합니다. 이미 `EVALUATED`/`CLOSED`인 보고서를 재평가로 덮어쓸 수 없습니다(두 번째 평가자는 "상태가 이미 변경됨"을 받습니다 — 조건부 UPDATE 로 lost update 차단). 평가상태(`EVALUATED`/`CLOSED`)를 벗어나는 전이는 이 세 필드를 함께 초기화해 제약을 충족합니다.
- **반려(reject) 의미**: `REJECTED`는 사유(`rejection_reason`)를 필수로 요구합니다(DB 제약). 반려는 삭제가 아니라 상태이며 이력을 보존합니다.
- **종결(close) 의미**: `CLOSED`는 평가가 끝난 보고서의 최종 상태로, 이후 전이가 없습니다(재개가 필요하면 별도 승인 절차로 다룹니다).
