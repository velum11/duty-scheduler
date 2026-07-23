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
```

삭제 동작은 기본적으로 `RESTRICT`입니다. 과거 근무와 편성을 보존해야 하는 기준정보는 비활성화를 우선합니다.

## 4. Migration

| 파일 | 내용 | 저장소 상태 | 마지막 확인된 테스트 환경 상태 |
|---|---|---|---|
| `001_initial_schema.sql` | 기본 5개 테이블·제약·인덱스·트리거 | 기준 migration | 적용됨 |
| `002_schedule_assignments.sql` | `shift_groups`, `schedule_assignments`, 근무 연결 컬럼 | DDL 전용, 자동 백필 없음 | 2026-07-16 적용·종단 확인 |
| `003_org_structure.sql` | 조직 그룹(→004로 대체됨)·운영단위 유형·사용자 표시순서 | guarded DDL + 제한적 안전 백필 | 2026-07-20 기준 미적용 — 그룹 컬럼(`department_group`/`group_sort_order`)은 004가 대체. `unit_type`/`display_order`는 004가 호환용으로 재추가하므로 003 미적용 상태에서도 앱은 정상 동작 |
| `004_org_groups.sql` | `organization_groups` 1급 테이블 신설 + `departments.group_id` FK + 무손실 백필(경로 B) | guarded DDL + 무손실 백필, 003의 그룹 컬럼 모델 대체 | 2026-07-22 테스트 프로젝트 read-only probe 확인. 앱 코드(`modules/db.py`·`supabase_repository.py`·조직/사용자/근무형태/대시보드 화면)는 004를 권위로 전면 전환 완료 — 프로덕션 live schema 적용 여부는 세션별 read-only 확인 필요 |

위의 환경 상태는 마지막 검증 기록입니다. 새로운 세션에서 적용 또는 미적용을 단정하기 전에 반드시 live schema를 다시 확인합니다.

## 5. Migration 안전 규칙

- 파일명 순서대로 적용합니다.
- 이미 적용된 migration은 적용 이력과 실제 schema 확인 없이 수정하지 않습니다.
- `create table if not exists`가 기존의 비호환 테이블을 보정해 주지는 않습니다.
- 적용 전 대상 프로젝트, 현재 컬럼·제약·행 수, 백업 가능성을 확인합니다.
- 사용자 승인 없이 migration을 실행하지 않습니다.
- 부분 적용이 의심되면 DROP으로 맞추지 않고 read-only probe 후 forward completion 가능성을 먼저 판단합니다.
- 002는 기존 근무를 현재 사용자 소속으로 자동 백필하지 않습니다.
- 004 적용 뒤에는 앱 프로세스를 재시작하거나 화면의 "스키마 재확인" 동작으로 조직 그룹 확장(`organization_groups` + `departments.group_id`) readiness cache를 다시 확인합니다.

## 6. Sample 데이터

`data/sample/*.csv`는 로컬 개발용입니다. sample 모드의 수정은 Streamlit 세션 상태에 저장되며 Supabase에 반영되지 않습니다. sample 데이터와 실DB 데이터의 행 수나 ID가 같다고 가정하지 않습니다.

## 7. 아직 확정되지 않은 변경

다음은 현재 schema 요구사항이 아닙니다.

- `work_schedules.schedule_assignment_id`의 NOT NULL 승격
- `work_schedules.user_id` 제거
- 운영용 RLS 정책과 Supabase Auth
- 자동 백필·과거 데이터 추정
- 별도 변경 이력·import batch 테이블

별도 사용자 요구와 migration 설계·승인 없이 선행 구현하지 않습니다.
