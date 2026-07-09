# 데이터베이스 설계서

이 문서는 `생산 근무표 관리` 시스템의 Supabase PostgreSQL 기준 데이터 구조를 정의한다.

Supabase 접속 정보는 `.streamlit/secrets.toml` 또는 `.env`에서 읽으며, 코드에 직접 작성하지 않는다.  
Supabase 설정이 없을 경우 앱은 `data/sample/` CSV를 사용해 로컬 샘플 모드로 실행한다.

---

## 1. 테이블 구성

| 구분 | 테이블 | 설명 |
|---|---|---|
| 기준정보 | `departments` | 부서 |
| 기준정보 | `teams` | 조/팀 |
| 기준정보 | `users` | 사용자 |
| 기준정보 | `work_types` | 근무형태 |
| 트랜잭션 | `work_schedules` | 근무표 |
| 트랜잭션 | `schedule_import_batches` | 근무표 저장 배치 이력 |
| 트랜잭션 | `schedule_change_logs` | 근무표 변경 이력 |
| 세션 | `login_sessions` | 로그인 유지 세션 |

---

## 2. 공통 원칙

- 기준정보와 근무표 데이터를 분리한다.
- 기준정보는 물리 삭제보다 `is_active=false` 사용 해제를 우선한다.
- 근무표는 사용자 1명, 날짜 1일, 근무형태 1개를 1행으로 저장한다.
- 같은 사용자와 같은 날짜는 중복될 수 없다.
- 근무표 변경은 이력으로 남긴다.
- 화면은 엑셀형 가로 구조, DB는 세로 구조로 관리한다.

화면 입력 형태:

```text
사번 | 성명 | 부서 | 조/팀 | 1(화) | 2(수) | 3(목) | ...
```

DB 저장 형태:

```text
user_id | work_date | work_type_code
```

---

## 3. 기준정보 테이블

### 3.1 departments

부서 기준정보.

| 컬럼 | 설명 |
|---|---|
| id | 부서 ID |
| dept_code | 부서 코드 |
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

### 3.2 teams

조/팀 기준정보.

| 컬럼 | 설명 |
|---|---|
| id | 조/팀 ID |
| department_id | 소속 부서 ID |
| team_code | 조/팀 코드 |
| team_name | 조/팀명 |
| sort_order | 표시 순서 |
| is_active | 사용 여부 |
| created_at / updated_at | 생성/수정일시 |
| created_by / updated_by | 생성/수정자 사번 |

제약:

```text
department_id + team_code 중복 불가
```

예:

```text
A조
B조
C조
A팀
B팀
```

---

### 3.3 users

사용자 기준정보.

| 컬럼 | 설명 |
|---|---|
| id | 사용자 ID |
| emp_no | 사번 |
| name | 성명 |
| department_id | 소속 부서 ID |
| team_id | 소속 조/팀 ID |
| position | 직급/직책 |
| role | USER / MANAGER / ADMIN |
| is_active | 재직 여부 |
| created_at / updated_at | 생성/수정일시 |
| created_by / updated_by | 생성/수정자 사번 |

권한:

| role | 설명 |
|---|---|
| USER | 본인 근무표 조회 |
| MANAGER | 소속 부서/조 근무표 조회 및 수정 |
| ADMIN | 전체 기준정보 및 근무표 관리 |

---

### 3.4 work_types

근무형태 기준정보.

| 컬럼 | 설명 |
|---|---|
| id | 근무형태 ID |
| code | 근무코드 |
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

기본 표시 코드 예:

```text
주
야
OFF
연차
```

세부 코드 예:

```text
주-6
6주
주2
야-4
야-6
특주
특야
자녀결혼
출산휴가
```

숫자가 포함된 근무코드는 기준 근무시간에서 앞/뒤 어느 시간에 덜 근무했는지 또는 추가 근무했는지를 구분하기 위한 현장 운영 코드다.

시스템은 세부 코드를 하드코딩하지 않고, `work_types` 기준정보에서 등록·수정할 수 있게 한다.

---

## 4. 근무표 테이블

### 4.1 work_schedules

근무표 저장 테이블.  
사용자 1명, 날짜 1일, 근무형태 1개를 1행으로 저장한다.

| 컬럼 | 설명 |
|---|---|
| id | 근무표 ID |
| user_id | 사용자 ID |
| work_date | 근무일자 |
| work_type_code | 근무코드 |
| note | 비고 |
| batch_id | 마지막 저장 배치 ID |
| created_at / updated_at | 생성/수정일시 |
| created_by / updated_by | 생성/수정자 사번 |

핵심 제약:

```text
user_id + work_date 중복 불가
```

주의:

- `work_type_code`는 `work_types.code`를 참조한다.
- 근무코드 변경은 기존 근무표와 이력에 영향을 줄 수 있으므로 신중히 처리한다.
- 운영 중인 코드는 수정 또는 삭제보다 비활성 처리 후 새 코드 추가를 우선한다.

---

### 4.2 schedule_import_batches

근무표 저장 1회를 기록하는 배치 이력.

| 컬럼 | 설명 |
|---|---|
| id | 배치 ID |
| target_month | 대상 월 |
| department_id | 대상 부서 |
| team_id | 대상 조/팀 |
| inserted_count | 신규 건수 |
| updated_count | 변경 건수 |
| deleted_count | 삭제 건수 |
| memo | 비고 |
| created_by | 저장자 사번 |
| created_at | 저장일시 |

`target_month` 형식:

```text
YYYY-MM
```

---

### 4.3 schedule_change_logs

근무표 셀 단위 변경 이력.

| 컬럼 | 설명 |
|---|---|
| id | 이력 ID |
| batch_id | 저장 배치 ID |
| user_id | 대상 사용자 ID |
| work_date | 대상 근무일자 |
| action | INSERT / UPDATE / DELETE |
| old_code | 변경 전 근무코드 |
| new_code | 변경 후 근무코드 |
| changed_by | 변경자 사번 |
| changed_at | 변경일시 |

기록 원칙:

- 실제로 달라진 셀만 기록한다.
- 같은 값을 다시 저장한 경우 이력을 남기지 않는다.
- 이력 테이블은 append-only로 관리한다.

---

## 5. 세션 테이블

### 5.1 login_sessions

사번 로그인 후 로그인 상태를 유지하기 위한 세션 테이블.

| 컬럼 | 설명 |
|---|---|
| token | 세션 토큰 |
| emp_no | 로그인 사번 |
| created_at | 생성일시 |
| expires_at | 만료일시 |

동작:

```text
로그인 성공
→ 세션 토큰 발급
→ login_sessions 저장
→ 브라우저 쿠키 기록
→ 페이지 로드 시 쿠키 토큰으로 자동 로그인
```

기본 만료 기간은 30일로 한다.

---

## 6. 저장 로직

### 6.1 변환

입력은 가로형 그리드로 받고, 저장은 세로형으로 한다.

```text
가로형 입력
사번 | 성명 | 부서 | 조/팀 | 1일 | 2일 | 3일 ...

세로형 저장
user_id | work_date | work_type_code
```

조회 시에는 세로형 데이터를 다시 가로형 그리드로 pivot하여 표시한다.

---

### 6.2 저장 전 검증

저장 전 다음을 검증한다.

| 번호 | 검증 |
|---|---|
| 1 | 사번이 `users`에 존재하는지 확인 |
| 2 | 사번이 없으면 성명으로 사용자 매칭 |
| 3 | 사번과 성명이 불일치하면 오류 |
| 4 | 부서가 `departments`에 존재하는지 확인 |
| 5 | 조/팀이 `teams`에 존재하는지 확인 |
| 6 | 조/팀이 해당 부서에 속하는지 확인 |
| 7 | 근무코드가 `work_types`에 존재하는지 확인 |
| 8 | 같은 사용자와 같은 날짜가 중복되지 않는지 확인 |

검증 실패 시 행/셀 위치와 오류 내용을 표시하고 저장을 차단한다.

---

### 6.3 저장 절차

```text
1. 가로형 그리드 입력 수집
2. 값 정규화
3. 세로형 레코드 변환
4. 기준정보 검증
5. 기존 월 데이터 조회
6. 신규/변경/삭제 후보 산출
7. 저장 전 미리보기 표시
8. 사용자 저장 확정
9. schedule_import_batches 생성
10. 신규/변경 레코드 upsert
11. 명시적으로 확정된 삭제만 delete
12. schedule_change_logs 기록
13. 저장 결과 표시
```

값 정규화:

```text
문자열 trim
영문 대문자 통일
전각 문자 정리
빈 문자열 정리
근무코드 대조 전 공백 제거
```

---

### 6.4 삭제 처리 원칙

그리드의 빈 셀 때문에 기존 근무를 자동 삭제하지 않는다.

기본 동작:

```text
빈 셀 = 변경 없음
```

삭제 후보는 저장 전 미리보기에서 별도로 표시한다.

```text
성명 | 날짜 | 기존 근무코드
김관리 | 2026-07-05 | 주
이책임 | 2026-07-06 | 야
```

관리자가 삭제 후보를 명시적으로 선택하거나 삭제 반영을 확정한 경우에만 삭제한다.

삭제가 확정된 경우:

```text
work_schedules에서 삭제
schedule_change_logs에 DELETE 기록
```

---

## 7. 로컬 샘플 데이터

Supabase 설정이 없을 경우 아래 CSV 파일을 사용한다.

```text
data/sample/departments.csv
data/sample/teams.csv
data/sample/users.csv
data/sample/work_types.csv
data/sample/work_schedules.csv
```

로컬 샘플 데이터는 Supabase 테이블 구조와 최대한 맞춘다.

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
```

---

## 8. 스키마 변경 원칙

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