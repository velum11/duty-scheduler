# 데이터베이스 설계서

이 문서는 `생산 근무표 관리` 시스템의 Supabase PostgreSQL 기준 데이터 구조를 정의한다.

데이터 모드는 `sample` 또는 `supabase`로 명시하며, 접속 정보는
`.streamlit/secrets.toml` 또는 환경변수에서 읽고 코드에 직접 작성하지 않는다.
Supabase 모드의 연결 실패는 sample 모드로 자동 전환하지 않는다. 설정과 검증 절차는
`docs/supabase-setup.md`를 기준으로 한다.

이 문서는 구조를 세 가지 상태로 구분해 기술한다.

| 상태 | 의미 | 근거 |
|---|---|---|
| 현재 구현 | 실제 Supabase에 반영된 구조 | `supabase/migrations/001_initial_schema.sql` |
| 이번 migration 목표 | 작성 완료, 적용 대기 중인 구조 | `supabase/migrations/002_schedule_assignments.sql` |
| 향후 계획 | 설계만 있고 migration이 없는 구조 | 본 문서 §8 |

---

## 1. 핵심 업무 개념

부서, 팀, 조는 서로 다른 개념이다.

| 개념 | 의미 | 저장 위치 |
|---|---|---|
| 부서 | 조직상의 부서 | `users.department_id`(현재 소속), `schedule_assignments.department_id`(월 편성 당시 값) |
| 팀 | 조직상의 팀 (부서 하위) | `users.team_id`(현재 소속), `schedule_assignments.team_id`(월 편성 당시 값) |
| 조 | 근무 편성 단위 (A조/B조/C조) | `schedule_assignments.shift_group_code`(월 편성 스냅샷) |

원칙:

- `users`의 부서·팀은 **현재 소속**이며, 근무표 등록 시 기본값으로만 사용한다.
- 조는 사용자 마스터에 저장하지 않는다. 직원별 **월 편성값**이다.
- 부서·팀·조는 직원별로 **한 달에 하나**를 적용한다. 월 중간 변경은 현재 범위에서 지원하지 않는다.
- 월 편성의 부서·팀·조는 **관리자용 근무표 등록/수정 화면에서만** 변경한다.
  전체 근무표 조회 · 내 근무표 · 대시보드 · CSV 다운로드는 읽기 전용이다.
- 근무표 등록 시 부서·팀을 변경해도 **사용자 마스터(users)는 변경하지 않는다**
  (타 부서 지원 근무 표현).
- 과거 근무표는 `users`의 현재 소속으로 **재계산하지 않는다**.
  조회·필터·표시는 `schedule_assignments`에 저장된 값을 기준으로 한다.
- 이름 문자열(부서명·팀명·조명)은 근무표에 저장하지 않는다.
  부서·팀은 관계값(id)을 저장하고 조회 시 이름을 표시한다.
  조 코드는 과거 이력 보존을 위한 **텍스트 스냅샷**으로 저장한다.

---

## 2. 테이블 구성

| 구분 | 테이블 | 설명 | 상태 |
|---|---|---|---|
| 기준정보 | `departments` | 부서 | 현재 구현 |
| 기준정보 | `teams` | 조직 팀 (부서 하위) | 현재 구현 (의미 재정의) |
| 기준정보 | `users` | 사용자 (현재 소속) | 현재 구현 |
| 기준정보 | `work_types` | 근무형태 | 현재 구현 |
| 기준정보 | `shift_groups` | 근무조 (선택지·검증 전용) | 이번 migration 목표 |
| 트랜잭션 | `schedule_assignments` | 직원별 월 편성 스냅샷 | 이번 migration 목표 |
| 트랜잭션 | `work_schedules` | 일별 근무 | 현재 구현 (관계 확장) |
| 트랜잭션 | `schedule_import_batches` | 근무표 저장 배치 이력 | 향후 계획 |
| 트랜잭션 | `schedule_change_logs` | 근무표 변경 이력 | 향후 계획 |
| 세션 | `login_sessions` | 로그인 유지 세션 | 향후 계획 (현재는 로컬 JSON 폴백) |

---

## 3. 공통 원칙

- 기준정보와 근무표 데이터를 분리한다.
- 기준정보는 물리 삭제보다 `is_active=false` 사용 해제를 우선한다.
- 직원별 월 편성은 1건만 존재한다: `UNIQUE(user_id, schedule_month)`.
- 근무표는 사용자 1명, 날짜 1일, 근무형태 1개를 1행으로 저장한다:
  `UNIQUE(user_id, work_date)`.
- 화면은 엑셀형 가로 구조, DB는 세로 구조로 관리한다.

화면 입력 형태:

```text
사번 | 성명 | 부서 | 팀 | 조 | 1(화) | 2(수) | 3(목) | ...
```

DB 저장 형태:

```text
schedule_assignments: user_id | schedule_month | department_id | team_id | shift_group_code
work_schedules:       user_id | work_date | work_type_code
```

---

## 4. 기준정보 테이블

### 4.1 departments — 현재 구현 (변경 없음)

부서 기준정보.

| 컬럼 | 설명 |
|---|---|
| id | 부서 ID |
| dept_code | 부서 코드 (UNIQUE) |
| dept_name | 부서명 |
| sort_order | 표시 순서 |
| is_active | 사용 여부 |
| created_at / updated_at | 생성/수정일시 |
| created_by / updated_by | 생성/수정자 사번 |

예:

```text
PET생산부(본동)
PET생산부(원료실)
생산관리팀
```

---

### 4.2 teams — 현재 구현 (의미 재정의)

**조직상의 팀** 기준정보. 근무조(A조/B조)는 이 테이블이 아니라 `shift_groups`에서 관리한다.

기존 컬럼 구조는 조직 팀 관리에 그대로 적합하므로 스키마 변경은 없다.
실제 운영 데이터가 0건인 시점에 의미를 재정의했으므로 데이터 이전도 없다.

| 컬럼 | 설명 |
|---|---|
| id | 팀 ID |
| department_id | 소속 부서 ID |
| team_code | 팀 코드 |
| team_name | 팀명 |
| sort_order | 표시 순서 |
| is_active | 사용 여부 |
| created_at / updated_at | 생성/수정일시 |
| created_by / updated_by | 생성/수정자 사번 |

제약:

```text
UNIQUE(department_id, team_code)
UNIQUE(id, department_id)   ← 사용자·편성의 복합 FK 대상
```

예:

```text
A팀
B팀
```

---

### 4.3 users — 현재 구현 (변경 없음)

사용자 기준정보. 부서·팀은 **현재 소속**이며 인사이동으로 변경될 수 있다.
과거 근무표는 이 값으로 재계산하지 않는다.

| 컬럼 | 설명 |
|---|---|
| id | 사용자 ID |
| emp_no | 사번 (UNIQUE) |
| name | 성명 |
| department_id | 현재 부서 ID (NOT NULL) |
| team_id | 현재 팀 ID (NULL 허용) |
| position | 직급/직책 |
| role | USER / MANAGER / ADMIN |
| is_active | 재직 여부 |
| created_at / updated_at | 생성/수정일시 |
| created_by / updated_by | 생성/수정자 사번 |

제약:

```text
FK (team_id, department_id) → teams(id, department_id)   ← 팀이 부서에 속함을 DB가 강제
```

권한:

| role | 설명 |
|---|---|
| USER | 본인 근무표 조회 |
| MANAGER | 소속 부서/조 근무표 조회 및 수정 |
| ADMIN | 전체 기준정보 및 근무표 관리 |

---

### 4.4 work_types — 현재 구현 (변경 없음)

근무형태 기준정보.

| 컬럼 | 설명 |
|---|---|
| id | 근무형태 ID |
| code | 근무코드 (UNIQUE) |
| name | 근무명 |
| category | 기본 분류 |
| short_label | 화면 표시 약칭 |
| start_time | 시작시간 |
| end_time | 종료시간 |
| color | 화면 표시 색상 |
| is_work | 실근무 여부 |
| affects_allowance | 특근/수당 구분 관련 여부 |
| description | 설명 |
| sort_order | 표시 순서 |
| is_active | 사용 여부 |

기본 분류:

```text
주간
야간
OFF
연차
경조사
훈련
기타
```

세부 코드(`주-6`, `특야`, `자녀결혼` 등)는 하드코딩하지 않고 기준정보에서 등록·수정한다.
숫자가 포함된 근무코드는 기준 근무시간 대비 앞/뒤 조정을 구분하는 현장 운영 코드다.

---

### 4.5 shift_groups — 이번 migration 목표 (신규)

근무조(A조/B조/C조) 기준정보. **선택지 제공과 저장 전 유효성 검사 전용**이다.

| 컬럼 | 설명 |
|---|---|
| id | 근무조 ID |
| department_id | 소속 부서 ID (NOT NULL) |
| shift_code | 근무조 코드 |
| shift_name | 근무조명 |
| sort_order | 표시 순서 |
| is_active | 사용 여부 |
| created_at / updated_at | 생성/수정일시 |
| created_by / updated_by | 생성/수정자 사번 |

제약:

```text
PK: id
FK: department_id → departments(id) restrict
UNIQUE(department_id, shift_code)
```

중요:

- `schedule_assignments.shift_group_code`는 이 테이블에 **FK로 연결하지 않는다**.
- 조 기준정보의 코드·명칭 변경, 사용 중지, 삭제가 과거 월 편성을 깨면 안 된다.
- 신규 편성 저장 시 `department_id + shift_group_code`가 활성 조에 존재하는지
  앱 저장 계층에서 검사한다.

---

## 5. 근무표 테이블

### 5.1 schedule_assignments — 이번 migration 목표 (신규)

직원별 **월 편성 스냅샷**. 해당 월에 이 직원이 어느 부서·팀·조로 근무했는지를
근무표 작성 당시 값으로 보존한다.

| 컬럼 | 설명 |
|---|---|
| id | 편성 ID |
| user_id | 대상 직원 ID (NOT NULL) |
| schedule_month | 대상 월 (해당 월 1일로 정규화, NOT NULL) |
| department_id | 해당 월 부서 ID (NOT NULL) |
| team_id | 해당 월 팀 ID (NULL 허용 — users 정책과 동일) |
| shift_group_code | 해당 월 조 코드 스냅샷 (텍스트) |
| created_at / updated_at | 생성/수정일시 |
| created_by / updated_by | 생성/수정자 사번 |

제약:

```text
UNIQUE(user_id, schedule_month)        ← 직원별 월 편성 1건
UNIQUE(id, user_id)                    ← work_schedules 복합 FK 대상
CHECK: schedule_month는 해당 월의 1일
FK: user_id → users(id) restrict
FK: department_id → departments(id) restrict
FK: (team_id, department_id) → teams(id, department_id) restrict   ← 팀이 부서에 속함
CHECK: shift_group_code는 NULL 또는 공백 아님
```

`shift_group_code`를 DB에서 NOT NULL로 강제하지 않는 이유:

- 기존 `work_schedules` 데이터를 backfill할 때 당시 조를 알 수 없다.
- 신규 저장 경로에서는 앱 검증이 조 코드를 필수로 요구한다.

원칙:

- 근무표 등록 시 `users`의 현재 부서·팀을 기본값으로 가져오되,
  관리자가 변경한 값은 이 테이블에만 저장하고 `users`는 변경하지 않는다.
- 인사이동으로 `users`가 바뀌어도 기존 편성 행은 그대로 유지된다.

---

### 5.2 work_schedules — 현재 구현 + 이번 migration 확장

일별 근무 저장 테이블. 사용자 1명, 날짜 1일, 근무형태 1개를 1행으로 저장한다.

| 컬럼 | 설명 | 상태 |
|---|---|---|
| id | 근무표 ID | 현재 구현 |
| user_id | 사용자 ID (NOT NULL) | 현재 구현 — **과도기 유지** |
| schedule_assignment_id | 월 편성 ID (NULL 허용) | 이번 migration 목표 |
| work_date | 근무일자 | 현재 구현 |
| work_type_code | 근무코드 | 현재 구현 |
| note | 비고 | 현재 구현 |
| created_at / updated_at | 생성/수정일시 | 현재 구현 |
| created_by / updated_by | 생성/수정자 사번 | 현재 구현 |

제약:

```text
UNIQUE(user_id, work_date)                          ← 하루 한 근무 (현재 구현)
UNIQUE(schedule_assignment_id, work_date)           ← 이번 migration 목표
FK: work_type_code → work_types(code) restrict (update도 restrict)
FK: (schedule_assignment_id, user_id)
    → schedule_assignments(id, user_id) restrict    ← 이번 migration 목표
```

`user_id` 중복 저장에 대한 판단 (과도기 vs 최종):

- **과도기(이번 migration)**: `user_id`를 유지하고 `schedule_assignment_id`를
  NULL 허용으로 추가한다. 기존 화면·Repository가 `user_id` 경로로 계속 동작한다.
  복합 FK `(schedule_assignment_id, user_id) → schedule_assignments(id, user_id)`가
  "근무 행의 사용자 ≠ 편성 행의 사용자" 불일치를 **DB 수준에서 차단**하므로
  중복 저장으로 인한 모순 데이터는 발생할 수 없다.
- **최종 목표(화면 전환 완료 후 별도 migration)**: `schedule_assignment_id`를
  NOT NULL로 올리고 `user_id` 컬럼과 `UNIQUE(user_id, work_date)`를 제거한다.
  사용자는 편성을 통해서만 식별한다. 단, `user_id` 제거 시
  "하루 한 근무" 제약은 `UNIQUE(schedule_assignment_id, work_date)` +
  `UNIQUE(user_id, schedule_month)` 조합으로 유지된다.

앱 저장 계층 필수 검증:

- `work_date`가 연결된 편성의 `schedule_month`와 같은 달인지 확인한다
  (DB CHECK로는 타 테이블 참조가 불가하므로 앱에서 강제).

---

## 6. 저장 로직

### 6.1 변환

입력은 가로형 그리드로 받고, 저장은 세로형으로 한다.

```text
가로형 입력
사번 | 성명 | 부서 | 팀 | 조 | 1일 | 2일 | 3일 ...

세로형 저장
schedule_assignments: user_id | schedule_month | department_id | team_id | shift_group_code
work_schedules:       user_id | work_date | work_type_code
```

조회 시에는 세로형 데이터를 다시 가로형 그리드로 pivot하여 표시하고,
부서·팀·조는 `schedule_assignments` 저장값으로 표시한다.

### 6.2 저장 전 검증

| 번호 | 검증 |
|---|---|
| 1 | 사번이 `users`에 존재하는지 확인 |
| 2 | 사번이 없으면 성명으로 사용자 매칭 |
| 3 | 사번과 성명이 불일치하면 오류 |
| 4 | 부서가 `departments`에 존재하는지 확인 |
| 5 | 팀이 `teams`에 존재하고 선택한 부서에 속하는지 확인 |
| 6 | 조 코드가 선택한 부서의 활성 `shift_groups`에 존재하는지 확인 |
| 7 | 근무코드가 활성 `work_types`에 존재하는지 확인 |
| 8 | 같은 직원·같은 월 편성이 중복되지 않는지 확인 |
| 9 | 같은 직원·같은 날짜 근무가 중복되지 않는지 확인 |
| 10 | 근무일자가 편성 대상 월에 속하는지 확인 |

검증 실패 시 행/셀 위치와 오류 내용을 표시하고 저장을 차단한다.
검증 순수 함수는 `modules/validators.py`에 둔다.

### 6.3 삭제 처리 원칙

그리드의 빈 셀 때문에 기존 근무를 자동 삭제하지 않는다.

```text
빈 셀 = 변경 없음
```

삭제 후보는 저장 전 미리보기에서 별도로 표시하고, 관리자가 명시적으로 확정한
경우에만 삭제한다.

> 참고: 현재 근무표 등록 화면(`replace_month_schedules`)은 빈 셀을 삭제로
> 처리하고 있으며 비원자적이다. 이는 다음 근무표 등록 화면 단계의
> **필수 개선사항**이다 (이번 데이터 구조 단계에서는 수정하지 않음).

---

## 7. 로컬 샘플 데이터

Supabase 설정이 없을 경우 아래 CSV 파일을 사용한다.

```text
data/sample/departments.csv
data/sample/teams.csv
data/sample/users.csv
data/sample/work_types.csv
data/sample/work_schedules.csv
data/sample/shift_groups.csv          (선택 — 없으면 빈 데이터로 동작)
data/sample/schedule_assignments.csv  (선택 — 없으면 빈 데이터로 동작)
```

필수 CSV 컬럼:

```text
departments.csv
id,dept_code,dept_name,sort_order,is_active

teams.csv
id,department_id,team_code,team_name,sort_order,is_active

users.csv
id,emp_no,name,department_id,team_id,position,role,is_active

work_types.csv
id,code,name,category,short_label,start_time,end_time,color,is_work,affects_allowance,description,sort_order,is_active

work_schedules.csv
id,user_id,work_date,work_type_code,note,batch_id

shift_groups.csv
id,department_id,shift_code,shift_name,sort_order,is_active

schedule_assignments.csv
id,user_id,schedule_month,department_id,team_id,shift_group_code
```

로컬 샘플 데이터는 Supabase 테이블 구조와 최대한 맞추고,
sample 모드와 supabase 모드는 동일한 DataFrame 반환 계약을 유지한다.

---

## 8. 향후 계획 (설계만, migration 없음)

### 8.1 schedule_import_batches

근무표 저장 1회를 기록하는 배치 이력. (`target_month`, 대상 부서/팀, 건수, 저장자)

### 8.2 schedule_change_logs

근무표 셀 단위 변경 이력. append-only. 실제로 달라진 셀만 기록.

### 8.3 login_sessions

사번 로그인 세션 테이블. 현재는 로컬 JSON 파일(`.local_sessions.json`) 폴백으로
동작하며 기본 만료 30일.

### 8.4 운영 단계 KEY 잠금

참조되는 코드 KEY(부서코드, 팀코드, 근무코드, 사번 등)의 수정·삭제 제한.
기초 데이터 입력 단계에는 적용하지 않는다.

### 8.5 work_schedules 최종 정규화

§5.2의 최종 목표 구조(`user_id` 제거, `schedule_assignment_id` NOT NULL) 전환.

---

## 9. 스키마 변경 원칙

DB 스키마 변경이 필요할 경우 다음 순서로 진행한다.

```text
1. docs/database.md 수정
2. 관련 요구사항 확인
3. DDL 또는 migration 작성
4. 로컬 샘플 CSV 구조 반영
5. 코드 반영
6. 테스트
```

코드를 먼저 바꾸고 문서를 나중에 맞추지 않는다.
