# 작업 로그 (WORKLOG)

터미널 Claude Code와 데스크탑 Cowork가 번갈아 작업할 때 맥락을 공유하기 위한 로그입니다.
작업(= 사용자가 화면에서 확인할 수 있는 결과 하나)을 마칠 때마다 아래 **로그** 섹션 **맨 위**에 한 항목씩 추가합니다. 최신 항목이 맨 위에 오는 역순입니다.

## 형식

```text
## YYYY-MM-DD HH:MM · [터미널|데스크탑] · 한 줄 제목
- 요청: 사용자 요청 요약 (1~2줄)
- 변경: 무엇을 어떻게 바꿨는지 (1~3줄)
- 파일: 수정/생성한 파일 목록
- 비고: 미완료·후속 작업·주의사항 (없으면 생략)
```

- `[터미널]`은 Claude Code(터미널), `[데스크탑]`은 Cowork(데스크탑) 작업을 뜻합니다.
- 시각은 Asia/Seoul(KST) 기준입니다.
- 사실 기록만 남기고, 커밋은 사용자 요청이 있을 때만 합니다.

---

## 로그

## 2026-07-16 11:05 · [터미널] · [3차 미션 완료] migration 002 적용 확인 + A조→B조 편성 스냅샷 종단 검증
- 요청: 사용자가 SQL Editor 로 002 수동 실행("Success. No rows returned") 후, 스키마·무변경·편성 영속을 검증하고 테스트 데이터 정리. 재개 기준: 기준선 1147(2026-07=589 승인·ADMIN 31건 보존), live 는 일반 직원 A→B/C 만, NULL-조는 자동 테스트.
- **적용 확인**: shift_groups·schedule_assignments·work_schedules.schedule_assignment_id 3종 생성. 신규 테이블 0건·연결컬럼 NOT NULL 0건(자동 백필 없음). 컬럼 계약(OpenAPI): user/dept/month NOT NULL, team_id·shift_group_code nullable, schedule_month date. FK 5종(SA→users/departments/teams복합, WS→SA복합, SG→departments) PostgREST 임베딩으로 존재 증명. UNIQUE(user_id,schedule_month)는 앱 upsert(on_conflict) 성공으로 행동 증명. 사용자 주의사항: 클립보드 과정에서 한글 주석/COMMENT 문자열 일부 깨졌을 수 있음 — 기능 무관(코멘트만), DDL 정상.
- **기존 데이터 무변경**: work_schedules 1147(2026-07=589·2027-07=558)·users 21·departments 5·teams 6·work_types 6 전부 불변, 기존 컬럼 타입 불변.
- **종단 검증(테스트 월 2027-01, 고중수 2008110301·user_id 31)**: ⚠️ 편차 기록 — 계획상 2028-01 이었으나 편성 화면 연도 선택지가 `today±1`(2025~2027)라 UI 진입 불가 → 빈 월 재확인(0/0) 후 **2027-01 로 조정**(뷰 수정은 미션 금지). ADMIN 로그인 → 사번 입력(성명·부서·조 자동조회: A조) → 조를 **B조**로 수정 → 1일=주·2일=야 입력 → 저장. 메시지 "근무 2건 저장 · **편성 1명 저장**"(성공, 002 이전의 '적용 후 저장' 경고 없음 = assign_persisted). DB: SA 1건(user 31·2027-01-01·dept 17·**team_id 24=B조**·shift NULL), **users.team_id 23=A조 유지**, WS 2건(DAY/NIGHT)만 추가. **새로고침(재로그인 필요=완전 새 세션)·월 이동(2027-02 빈 월 격리 확인)→복귀·서버 프로세스 재시작+재로그인** 모두 B조·주/야 유지 — 세션 캐시 소멸 상태이므로 DB 영속 확정.
- **NULL-조 자동 테스트**: audit 테스트에 2건 보강(팀 미지정 '' 보존 = users 조 자동 대입/A조 fallback 저장 없음, 근무조 '' 보존) → 39건. 기존: NULL 허용 정합·조 없는 부서 저장 가능·타부서 조 선차단(복합 FK 방어) 커버.
- **정리**: 삭제 전 대상 출력(SA 1·WS 2) → repo delete_schedule(사번·일자 단건)×2 + SA user_id+월 정밀 삭제 → 기준선 완전 복구(1147/589/558·SA 총 0·기준정보 21/5/6/6·고중수 A조).
- 테스트: audit 39 · contracts 52 · save_units 15 통과, git diff --check clean. (참고) 테스트 WS 행의 schedule_assignment_id 는 NULL — 현 저장 경로는 연결컬럼을 채우지 않음(002 주석의 과도기 계약, 별도 migration/코드에서 승격 예정).
- 다음 미션 후보: (a) 월간·개인·CSV 의 assignment-우선 조회 보강(이번 미션 제외 항목 — 이것 없이는 조회 화면 조 표시가 users 기준), (b) 편성 화면 연도 범위 확장 검토, (c) work_schedules.schedule_assignment_id 연결 저장 경로.
- 파일: scripts/test_migration_002_audit.py(+2 체크), docs/WORKLOG.md. Supabase 는 002 적용(사용자 실행) + 테스트 왕복 후 원상. commit·push 없음.

## 2026-07-16 09:45 · [터미널] · [3차 미션 중단] migration 002 적용 전 기준선 불일치 — 적용 보류 (BLOCKED)
- 요청: 정리된 002를 테스트 프로젝트에 적용하고 A→B/C 스냅샷 영속을 종단 검증. 단, §3 사전 재확인이 예상과 다르면 적용 금지·중단 보고.
- **중단 사유(§3 명시 규칙 발동)**: 실DB 재조회 결과 work_schedules 총 **1147**(예상 1116), 2026-07 = **589**(예상 558). 초과 31건은 **2026-07-16(오늘) 생성**, user_id=21(emp_no=ADMIN, 관리자 계정)의 2026-07 한 달치(DAY 10·OFF 10·NIGHT 11) — 미션 사이에 편성 화면에서 수동 저장된 것으로 추정. users 분포도 변동: team_id=23(PET A조) **20명**+미지정 1명(예상 19+2), 활성 ADMIN(user_id=21)이 PET/A조 소속(§0·§7의 "ADMIN=관리자부서·조없음" 전제와 불일치 — 관리자부서 admin user_id=19는 비활성).
- 적용 전 통과 항목: 작업 트리 clean(e0ab9f8), 002=커밋본 동일, SHA-256 `0229b2110fa140f74673433df69021cd67c83f5144f18c1ea3def2c46e3652ea`, 정적 테스트 37+52+15·compile OK, 002 오브젝트 3종 미존재(부분 적용 흔적 없음), 2027-07=558 불변, 기준정보 21/5/6/6 불변, 2028-01 빈 월 확인(0건).
- 백업 근거 확보: `docs/backup_pre_migration_002.json` (UTC 2026-07-16T00:37, 프로젝트 ref icvizwmqdffwsifmnwuk, 전 테이블 + work_schedules 1147행 전체, 컬럼 목록, 002 해시 포함). **개인정보(사번·성명) 포함 — 커밋 금지, 로컬 보관용.**
- 추가 확인: DDL 실행 경로 미확보 — supabase CLI 없음, config.toml 없음, secrets에 직접 PostgreSQL 연결 정보 없음, PG 드라이버 없음. service_role REST 우회는 미션 금지. 재개 시 Dashboard SQL Editor(수동 또는 로그인된 브라우저 세션) 필요.
- **Supabase·스키마·데이터 무변경**(read-only SELECT만). migration 미적용 유지. commit·push 없음.
- 재개 조건(사용자 결정 필요): (a) ADMIN 2026-07 31건을 새 기준선(총 1147, 2026-07=589)으로 승인하고 재개, 또는 (b) 해당 31건 정리 지시 후 1116 기준으로 재개. + ADMIN NULL-조 검증 대상을 어느 계정으로 할지(현 활성 ADMIN은 PET/A조).

## 2026-07-16 09:20 · [터미널] · [2차 미션] migration 002 를 DDL 전용으로 정리 — 자동 백필 완전 제거
요청: 1차 감사 결론에 따라 002 에서 users 기반 자동 백필을 분리하고 안전한 DDL 전용 migration 으로 정리. migration 실행·Supabase 쓰기·commit 은 금지.

1. **migration 파일 처리 전략 — 전략 A(002 직접 수정) 채택.** 근거 3중 확인: (a) 실DB 프로브에서 schedule_assignments·shift_groups·schedule_assignment_id 전부 미존재(유일한 Supabase 테스트 프로젝트에도 미적용), (b) CLAUDE.md·AGENTS.md 가 "002 미적용" 명시·배포 이력 기록 없음, (c) git 상 002 는 3fef14a 단일 커밋 도입 후 무수정. 어느 환경에도 적용된 적 없으므로 migration 불변성 문제 없이 직접 수정 가능.
2. **자동 백필 제거 내용**: 002 의 114~134행 INSERT(users 현재 소속 기반 편성 생성) + UPDATE(schedule_assignment_id 연결) 블록 삭제. 이제 002 에는 실행 가능한 DML 이 0건 — diff 로 확인: 제거된 실행 구문은 해당 INSERT/UPDATE 뿐, 추가된 실행 구문 없음(주석만 추가). 제거 이유·기존 데이터 정책·선택적 백필 조건을 SQL 주석 블록("기존 데이터 정책: 자동 백필 없음")으로 파일 안에 기록.
3. **schedule_assignments 최종 계약(무변경 확정)**: 직원·월 1건 UNIQUE(user_id, schedule_month) · schedule_month=해당 월 1일 date(CHECK) · user_id/department_id FK(RESTRICT) · team_id NULL 허용 + 복합 FK(team_id,department_id)→teams · shift_group_code NULL 허용 text(FK 아님) · created/updated_at(트리거) · 인덱스 month/(dept,month). **ID 참조형 "월별 배정 스냅샷"임을 주석에 명시** — 부서명·조명 변경 시 과거 화면도 최신 명칭으로 표시되며, "당시 명칭 문자열 보존"이 아니다. 현재 요구사항(기준정보 §5: 명칭 변경으로 연결이 끊기지 않아야 함)에는 ID 참조형이 충분.
4. **teams vs shift_groups 역할 구분**: 화면의 A/B/C조 = **teams 기준정보(team_id/team_code)** 로 저장. shift_groups(근무조)는 별개 개념의 선택지·검증 전용 기준정보로 테이블은 유지하되(제거하려면 repo/db/validators 운영 코드 수정 필요 — 이번 미션 금지 범위), 저장 필수 조건이 아님: 편집기는 require_shift=False + shift_group_code='' 로 저장하고 shift_groups 를 조회하지 않음(정적 테스트로 고정).
5. **기존 1116건 처리 정책**: work_schedules(2026-07=558, 2027-07=558)는 그대로 유지, schedule_assignment_id 는 NULL 로 남음. DDL 적용만으로는 행 수·값·타입 전부 불변.
6. **과거 월 assignment 미존재 유지 이유**: 과거 실제 편성 조(A/B/C)를 알 수 있는 신뢰 가능한 원본이 DB 에 없음. users 현재값(재직자 대부분 A조)으로 채우면 오답이 영속 각인됨. 조회 화면의 users fallback 은 표시용일 뿐 저장하지 않는다.
7. **선택적 백필 필요 입력**: 명시적 (사번, 월, 부서, 조) 매핑 원본(예: 편성 원본 Excel). 실행 조건 — 002 와 자동 연동 금지, 기본 미실행, users 자동 source 금지, 매핑 명시 직원·월만, dry-run·존재/중복 검증·대상 사전 출력, 사용자 승인 필수. **신뢰 원본이 아직 없으므로 실행 스크립트는 만들지 않고 계약만 문서화**(002 주석 + 본 기록).
8. **적용 순서(승인 시)**: (a) 백업/스냅샷 확인 → (b) 002(DDL 전용) 적용 → (c) 조회 화면 assignment-우선 fallback 보강 배포(다음 미션) → (d) 편집기 시범 월 저장으로 스냅샷 영속 확인.
9. **검증 순서**: 세 오브젝트 존재 확인 → work_schedules 총 1116·월별 558/558 불변 → schedule_assignments 0건(자동 생성 없음 확인) → 편집기 A→B/C 편성 저장 후 get_month_assignments 가 B/C 반환 → 미편성 월 빈 편성+마스터 fallback → 근무 조회 정상.
10. **롤백 순서**(002 헤더 주석, FK 역순): work_schedules_assignment_date_key drop → work_schedules_assignment_user_fk drop → work_schedules_assignment_idx drop → schedule_assignment_id 컬럼 drop → schedule_assignments drop → shift_groups drop. 적용 후 신규 편성이 저장된 뒤 롤백하면 그 스냅샷은 유실됨(롤백 전 백업 필요).
11. **적용 후 운영 코드에서 수정할 부분(다음 미션)**: (a) 월간(views/workspace._build_month_grid)·개인(views/my_schedule)·CSV 가 get_month_assignments 를 우선 참조하고 미존재 시 users fallback 하도록 보강 — 이것 없이는 002 적용 후에도 화면 조 표시가 개선되지 않음. (b) 저장 원자성: work_schedules 와 assignments 순차 저장(트랜잭션 없음) — 현재 계약은 "근무 저장 성공 + 편성 실패 시 실패를 숨기지 않고 안내"(assign_persisted 분기)로 허용 가능하나, 장기적으로 RPC 검토.
12. **실제 migration 은 미실행 상태.** Supabase 스키마·데이터 무변경(이번 미션에서는 실DB 접속 자체 없음 — 정적/sample 만).

- 테스트: test_migration_002_audit **37건**(백필 부재·DML 0건·users 미참조·FK RESTRICT·001 정합·롤백 역순·teams/shift 분리·validators 정합) + 회귀 52+15+23+14 = **총 141건 통과**. compile OK, git diff --check clean.
- 파일: supabase/migrations/002_schedule_assignments.sql(백필 제거+정책 주석, 실행 구문 추가 0), scripts/test_migration_002_audit.py(계약 반전·확장), docs/WORKLOG.md(본 기록)
- 비고: 1차 미션 미커밋분(WORKLOG 감사 기록, 감사 테스트 초판)과 이번 변경이 같은 파일에 섞여 있음 — 커밋 시 함께 반영됨. commit·push 미실행.

## 2026-07-16 08:55 · [터미널] · [read-only 감사] migration 002 + 조 스냅샷 구조 적용 전 감사
요청: migration 002 실제 적용 전, schedule_assignments/shift_groups 구조와 조 스냅샷 계약을 코드·SQL·실DB(SELECT만) 기준으로 감사하고 적용 가능 여부·위험을 보고. 쓰기·실행·commit 전면 금지.

1. **migration 002 구조 요약**
   - `shift_groups`(근무조 기준정보): id PK, department_id FK(→departments, RESTRICT), shift_code/shift_name(NOT NULL·not-blank CHECK), sort_order, is_active, created/updated_at+by. UNIQUE(department_id, shift_code). 인덱스 department_id. updated_at 트리거. RLS enable(정책 없음).
   - `schedule_assignments`(직원별 월 편성 스냅샷): id PK, user_id FK(→users, RESTRICT), schedule_month date(CHECK 월1일), department_id FK(RESTRICT), team_id NULL, shift_group_code text NULL(FK 아님·스냅샷), created/updated. UNIQUE(user_id, schedule_month)=직원·월 1건, UNIQUE(id,user_id), 복합 FK(team_id,department_id)→teams(id,department_id) RESTRICT. 인덱스 month·(department,month). RLS enable(정책 없음).
   - `work_schedules` 확장: `ADD COLUMN IF NOT EXISTS schedule_assignment_id`(NULL), 복합 FK(schedule_assignment_id,user_id)→schedule_assignments(id,user_id) RESTRICT, UNIQUE(schedule_assignment_id, work_date), 인덱스. user_id 유지(과도기).
   - **백필 내장(114~134행)**: 기존 work_schedules에서 DISTINCT(user_id, 월)로 assignments를 INSERT하되 부서·팀을 **users 현재 소속(u.department_id/u.team_id)** 으로, shift_group_code는 NULL로 채우고 work_schedules.schedule_assignment_id를 UPDATE 연결. ON CONFLICT DO NOTHING + NULL 조건이라 재실행 안전.

2. **현재 코드와 migration 계약의 불일치**
   - 월간(workspace._build_month_grid)·개인(my_schedule)·CSV는 부서·조를 **users 마스터 현재값**으로만 표시하고 `schedule_assignments`를 **조회하지 않음** → 002를 적용해도 두 화면의 "전부 A조" 증상은 그대로. (편성 우선 표시는 편집기에서만 구현됨: schedule_edit `_assignment_snapshots`→세션캐시→마스터.)
   - `db.get_month_roster`(assignments 미try/except 조인)는 **어떤 뷰도 호출하지 않음**(테스트 전용) → 운영 read 경로는 assignments 부재로 깨지지 않음. 근무 조회(get_month_schedules/_schedule_rows)는 work_schedules 전용.
   - validators↔002 스키마는 정합(월1일, team/shift NULL 허용=require_shift False, 직원·월 UNIQUE). 편집기 저장은 require_shift=False(shift_group_code 항상 '' → NULL). "조" A/B/C는 **teams.team_code**(→team_id)로 저장, shift_groups는 편집기에서 미사용.

3. **적용 전 반드시 수정해야 하는 항목** (→ 모두 Fable High 소관)
   - (필수) 002의 **백필 블록**을 그대로 두면 실행 즉시 assignments 38±건이 "전부 A조" + shift NULL로 각인됨. "신규 저장 월부터만 스냅샷" 요구를 지키려면 백필을 분리/게이트하도록 **002 SQL을 수정**해야 함.
   - (권장, 별도 작업) 월간·개인·CSV가 `get_month_assignments`(실패 무시 폴백)를 우선 참조하도록 뷰 로직 보강 — 이걸 안 하면 002를 적용해도 화면 조 표시는 개선되지 않음.

4. **기존 데이터 영향** — *현재 값 재확인(이전 보고와 다름)*: work_schedules **총 1116건**(2026-07=558, 2027-07=558). users 21·departments 5·teams 6(dept17·18 각 A/B/C 활성)·work_types 6. **users 19명 전원 team=A조, 2명 조 없음**. 002 DDL 자체는 기존 컬럼/행을 훼손하지 않음(ADD COLUMN·신규 테이블뿐). 위험은 손상이 아니라 **백필이 1116행을 A조 편성에 연결**하는 의미 오류.

5. **백필 필요 여부** — **불필요/금지**. 과거 실제 조(월별 B/C 편성)는 소스가 없어 알 수 없고, users 현재값(A조)로 채우면 오답을 영속화. 과거 월은 assignments **미존재/NULL로 유지**하고 편집기 신규 저장분부터 스냅샷을 쌓는 편이 안전. (미션 금지사항과 일치.)

6. **안전한 적용 순서(권장, 승인 시)** — (a) 002에서 백필 INSERT/UPDATE 제거 또는 주석 게이트한 사본 준비(SQL 수정=Fable High), (b) 백업/스냅샷 확인, (c) DDL만 적용(테이블·컬럼·제약·인덱스·트리거·RLS), (d) 월간·개인·CSV의 assignments-우선 폴백 뷰 보강 후 배포, (e) 편집기에서 시범 월 저장→재조회로 스냅샷 영속 확인.

7. **롤백 순서** — 002 헤더 주석의 역순: work_schedules 제약(assignment_date_key, assignment_user_fk) drop → index drop → schedule_assignment_id 컬럼 drop → schedule_assignments drop → shift_groups drop. **주의**: 적용 후 편집기로 신규 편성이 저장된 뒤 롤백하면 그 스냅샷은 유실(→Fable High).

8. **적용 후 검증 시나리오** — schedule_assignments/shift_groups/schedule_assignment_id 존재; work_schedules 1116 불변; 특정 사번 월별 건수 불변; 편집기에서 A→B/C 편성 저장 후 get_month_assignments가 B/C 반환; 미편성 월은 빈 편성+마스터 폴백; 근무 조회는 편성 유무와 무관하게 성공.

9. **Fable High 검토 필요 항목** — 판정: **적용 불가(현 상태), Fable High 필요.** 트리거 다중 해당: (i) 002 SQL 자체 수정(백필 분리), (ii) 기존 1116건 백필/변환, (iii) 과거 부서·조 추정, (iv) 적용 후 신규 편성 저장 시 롤백 데이터 유실 가능. RLS 정책 부재는 001과 동일 패턴(service_role 접근)이라 신규 위험 아님.

10. **git status**: 브랜치 feature/supabase-crud, 미커밋 신규 파일 `scripts/test_migration_002_audit.py`(정적 감사 25건) 1개뿐. 운영 코드·migration SQL 무수정. 실DB 쓰기 0.

- 테스트: 신규 test_migration_002_audit 25 통과. 회귀 test_schedule_contracts 52·test_schedule_save_units 15·test_master_and_views 23·test_master_forms 14 통과(총 129). compile OK.
- 무변경 확인: git diff 비어 있음(추적 파일 무수정), 002/001 SQL·schedule_edit.py 무수정, Supabase INSERT/UPDATE/DELETE 0(SELECT·존재프로브만).
- 파일: scripts/test_migration_002_audit.py(신규), docs/WORKLOG.md(본 기록)

## 2026-07-15 18:05 · [터미널] · [무인작업 완료] Phase 5 브라우저 read-only 검증 + Phase 6 최종 감사
- Phase 5(브라우저 read-only, ADMIN 로그인, 저장/삭제 클릭 없음): 조 관리·근무형태 관리 신형 통일 그리드 렌더 확인. 근무형태 색상 열은 스와치(코드별 색)+HEX 표시, 셀 더블클릭 시 네이티브 컬러 피커가 현재 HEX(#1e6fd9)를 로드(Escape로 취소, 저장 안 함). [＋행추가]로 신규 −행+기본 색 스와치 생성 확인 후 −로 제거해 원상 복귀(Supabase 쓰기 없음).
- Phase 6 자체 감사: `git diff --check` 클린(LF/CRLF 경고만). schedule_edit.py·migrations·validators.py·db/ 무변경 확인. diff 추가라인의 유일한 Supabase 쓰기 표현은 delete_team/delete_work_type 함수 본문(기능 코드, 이번 세션 실행 안 함)과 on_click 상태 람다뿐. print는 테스트 스크립트에만. compileall OK.
- 테스트 전량 재확인: test_schedule_contracts 52 · test_schedule_save_units 15 · test_master_and_views 23 · test_master_forms 14 = 104 전부 통과. test_supabase_crud(라이브 쓰기 유발)는 규칙상 미실행.
- Supabase read-only 카운트 재검증(세션 전후 동일): users 21 · departments 5 · teams 6 · work_types 6 · work_schedules 2027-07 = 558 · 2026-07 = 0 · 총 558. 쓰기 전무 확인.
- 상태: 커밋/푸시 대기(사용자 지시 전까지 커밋 안 함). 미커밋 8개 수정 + 신규 scripts/test_master_and_views.py.

## 2026-07-15 17:50 · [터미널] · [무인작업 체크포인트] Phase 4·5 코드 완료 — 기준정보 통일 + 테스트
- Phase 4: `views/master_teams.py`·`views/master_work_types.py` 를 부서 관리와 동일한 `selectable_master_grid`(행 상태 계약, 상단 행추가/삭제/저장, 3상태 전체선택, 반응형 표, 신규 −행/기존 체크박스 분리)로 전면 통일. 조 관리: 부서 표시명↔dept_code 변환·부서내 조코드 중복 차단·소속 사용자 있는 조 미사용 처리/없으면 삭제. 근무형태: 색상 열을 **네이티브 컬러 피커(cellEditor)+스와치 렌더러**로 변경(저장 #RRGGBB 유지), 근무표 사용 중 코드 미사용 처리/없으면 삭제. db/repo에 delete_team·team_reference_counts·delete_work_type·work_type_reference_counts 추가(부서 패턴 미러링). validators.validate_assignment_records 는 이전 커밋에서 require_shift 옵션화됨(무관).
- Phase 5: 신규 `scripts/test_master_and_views.py`(23건: work_type_display·월간 필터/약칭/빈월/월분리·조/근무형태 validate·db 참조/삭제). `scripts/test_master_forms.py` 를 구형 폼 UI 테스트에서 신형 AG Grid 스모크(4화면 렌더 무예외)+신 시그니처 검증+라우팅(6페이지)으로 갱신(14건). 회귀: test_schedule_contracts 52, test_schedule_save_units 15 통과. 총 52+15+23+14 전부 통과. compile OK.
- 주의: test_master_forms 구버전은 4f9fe3b(부서 재설계, 승인됨)부터 이미 obsolete(제거된 폼 위젯 테스트)였고 이번 조 관리 재설계로 team 시그니처도 바뀜 → 신형에 맞게 재작성(실패 은폐 아님, UI 변경 반영).
- 미검증(진행 중): (a) 새 조/근무형태 화면 브라우저 read-only 렌더, (b) 월간 필터/개인 데이터 표시 — 단위/AppTest 로 결정적 검증했고 브라우저는 Supabase 쓰기 없는 read-only 렌더만 확인 예정. 실제 저장/삭제는 sample 모드/AppTest 로만(Supabase 쓰기 금지 준수).
- 다음: Phase 5 브라우저 read-only 렌더 → Phase 6 최종 감사(diff/write호출/스키마/schedule_edit 무변경/테이블 행수 재확인).

## 2026-07-15 17:34 · [터미널] · [무인작업 체크포인트] Phase 2·3 완료 — 월간/개인 약칭·색상 표시
- Phase 2(월간 근무표, views/workspace.py): `work_type_display()` 신설(코드→약칭 display_of, 약칭·코드 양쪽→색상 color_of, 약칭 비거나 모호하면 코드 표시). `_build_month_grid`가 셀을 약칭으로 표시, `_cell_style`는 color_of 기준, 집계표 열 머리글도 약칭, 범례를 `_label_legend_html`로 약칭 표시. 필터·연월 로직은 미변경.
- Phase 3(개인 근무표, views/my_schedule.py): `_calendar_html`이 셀을 약칭+색상으로 표시(work_type_display 재사용). 광범위 try/except 를 유지하되 repository 오류 메시지에 원인 노출(빈 월과 구분 명확화).
- 브라우저 검증: 월간 2027-07 재조회 → 셀이 주/야/OFF/연차(색상 포함)로 표시 확인(스크린샷). 개인: USER(2008082501) 로그인·전용 App Shell·달력 렌더 정상(2026-07 빈 달력, 오류 없음). **미완 검증**: (a) 월간 부서·조 필터, (b) 개인 2027-07 데이터 표시 — Streamlit 셀렉트박스/wheel picker 가 브라우저 자동화 커밋을 거부(제품 결함 아님). → Phase 5 에서 sample 모드 단위/AppTest 로 결정적 검증 예정.
- compile OK. schedule_edit.py 미변경. Supabase 쓰기 없음(read-only 조회만).
- 다음: Phase 4(master_teams·master_work_types 를 selectable_master_grid 로 통일, work_types 색상표) → Phase 5 테스트 → Phase 6 감사.

## 2026-07-15 17:11 · [터미널] · [무인작업 체크포인트] Phase 1 감사 완료 — 월간/개인 조회 원인 특정
- 기준: 커밋 5ecda99, 작업 트리 clean, sample 테스트 통과, compile OK. Supabase read-only 프로브 결과: work_schedules 558행(전부 2027-07)/users 21/dept 5/teams 6/work_types 6, schedule_assignments 없음.
- 연결도(read-only 코드 추적): 로그인 사번→auth.get_current_user→app.py dispatch→(schedule_view→workspace.schedule_screen / my_schedule.render)→db.get_month_schedules(emp_nos,y,m)→supabase_repository._user_maps(emp_no→user_id)+work_schedules 범위조회(work_date gte/lt)→SCHEDULE_COLUMNS(emp_no/duty_date/work_type_code/note)→표/달력. work_types는 code/short_label/color 보유.
- **핵심 진단: 저장·조회·연결은 정상. "안 보임"은 UI 계층 이슈**. repository 프로브에서 2027-07 전체 558행/18명, 개인(2008082501) 31행 정상 반환.
  1) 두 화면 모두 날짜 셀에 내부 코드(DAY/NIGHT..)를 그대로 표시 — 요구사항의 약칭(주/야/OFF..) 표시 위반. (월간 workspace._build_month_grid, 개인 my_schedule._calendar_html)
  2) 기본 연·월이 today(2026-07)라 첫 진입 시 빈 월 → 사용자가 "조회 안 됨"으로 오인 가능(정상 빈 월). 데이터는 2027-07 선택 시 표시.
  3) 월간 schedule_screen 은 상단에서 db.get_schedules()(전체 조회)를 매 렌더 호출 — 일시 소켓 오류 시 화면 전체가 예외로 죽을 수 있음(try/except 없음).
  4) 개인 my_schedule.render 는 전체를 광범위 try/except 로 감싸 모든 예외를 "불러오지 못했습니다"로 뭉갬 — repository 오류와 정상 빈 월 구분 불가(요구 Phase3 #12 위반).
- 기준정보 현황: master_departments=신형 그리드(selectable_master_grid). master_users=editable_aggrid(안정). master_teams=editable_aggrid+요약카드+신규 폼 버튼(구형). master_work_types=st.data_editor+요약카드+색상 텍스트+범례(구형). → Phase4 대상은 teams·work_types 를 부서 관리와 동일한 selectable_master_grid 로 통일 + work_types 색상 컬럼을 색상표로.
- schedule_edit.py 는 이번 무인작업에서 read-only 참조만(수정 금지 준수).
- 다음: Phase 2(월간 조회 약칭·색상·견고성) → Phase 3(개인 조회 약칭·오류 구분) → Phase 4(teams/work_types 통일) → Phase 5 테스트 → Phase 6 감사.
- 요청: ① 저장한 조가 유실되고 전원 A조로 조회되는 오류 수정 ② 통계 카드·하단 범례 제거, 날짜 셀 근무 색상, 표 중심 레이아웃 정리.
- 원인: 조 유실은 코드 fallback 이 아니라 저장처 부재 — 조 스냅샷의 설계 저장처(schedule_assignments, migration 002)가 Supabase 에 미적용이고, 재조회 표시가 users 마스터 조(전원 A조)로 대체되고 있었음.
- 변경: `validators.validate_assignment_records(require_shift=)` 옵션화(기본 True 계약 유지), `db/supabase_repository.upsert_month_assignments(require_shift=)` 전달(False 면 shift_groups 조회 생략·NULL 저장). `views/schedule_edit.py` — 저장 시 행별 부서·조 스냅샷을 upsert_month_assignments(require_shift=False)로 저장 시도(002 이전엔 실패 허용) + 세션 스냅샷 캐시(se_assign_cache), 재조회 표시 우선순위 영속 편성→세션 스냅샷→users 마스터. UI: 통계 카드/범례 제거, 메타 한 줄(대상 월·표시·신규·선택·입력·삭제 예정), 날짜 셀 색상은 work_types.color 를 코드·약칭에 매핑한 cellStyle(연한 배경+진한 글자, DESIGN.md §15 계열). 단위 테스트 15건(조 스냅샷 왕복·A조 fallback 부재·조 변경 유지·users 무변경·기본 계약 유지 포함).
- 파일: views/schedule_edit.py, modules/validators.py, modules/db.py, modules/supabase_repository.py, scripts/test_schedule_save_units.py, docs/WORKLOG.md
- 비고: 커밋 안 함. Supabase 종단(2027-07, 기존 데이터 무접촉): 박시우(2026060101) B조 저장→재조회·월 이동 후 재진입 모두 B조 유지, 셀 색상 일관, 임시 2건 정리 완료. **주의: 프롬프트의 '0행 사고 상태'와 달리 현재 work_schedules 에 558건이 존재하며 전부 2027-07** (2026-07 은 여전히 0). 직전 커밋 시점(총 0행) 이후 이 터미널 밖에서 유입 — 2026-07 복구 시도 중 연도가 2027 로 들어갔을 가능성. 사용자 확인 필요. Supabase 모드의 조 영속 저장은 migration 002 적용 시 자동 활성화(세션 내에서는 유지됨).

## 2026-07-15 15:15 · [터미널] · 근무표 편성 — 혼합 저장·삭제만 저장·전체 선택 수정
- 요청: ① 삭제 예정+동일 사번 재등록 시 저장 차단 해제(교체 처리) ② 삭제만 저장 시 users 조회 의존 제거(WinError 10035 표면적 축소) ③ 선택 헤더 3상태 전체 선택 ④ 필터 결과만 전체 선택.
- 변경: `views/schedule_edit.py` — `classify_save_targets`(delete_only/replace_after_delete)로 최종 사번별 상태 분류, 저장 파이프라인 재구성(검증 전체 통과 후 삭제→교체(replace_month_schedules)→변경분 upsert, 단계 실패 시 단계 보고+초안 유지), 삭제만 저장 경로는 users/근무형태/부서·조 조회 생략, users 매핑 세션 캐시(조회 시점 갱신·rerun 반복 조회 제거), `표시 M·신규 N·선택 K` 카운트 표시, 새로고침 버튼 on_click 플래그 전환(클릭 소실 경합 해결). `views/workspace.py` — `_SELECT_ALL_HEADER`(3상태, forEachNodeAfterFilter로 표시 중 기존 행만, 신규/제거 행 제외, refreshCells로 행 체크 표시 동기화), `selectable_master_grid(select_all_header=)` opt-in(부서 관리 무영향). `scripts/test_schedule_save_units.py` 신규(분류·약칭 계약 10건).
- 파일: views/schedule_edit.py, views/workspace.py, scripts/test_schedule_save_units.py, docs/WORKLOG.md
- 비고: 커밋 안 함. 브라우저 검증(2027-07 임시 데이터 한정, 종료 후 정리 완료): 전체 선택/indeterminate/신규 행 제외/조 변경 시 선택 해제/전체 삭제 예정+1명 재등록 저장(충돌 없음, "2명 삭제·1명 교체", DB stale 없음)/삭제만 저장(빈 월 복귀·dirty·선택 초기화) 모두 통과. 기준정보 무변경(users 21). 2026-07 소실 데이터는 복구 시도하지 않음(아래 사고 기록 유지, 승인 대기).

## 2026-07-15 14:55 · [터미널] · ⚠ 데이터 사고 기록 — Supabase work_schedules 전체 소실 (보존 중)
- 발견: 2026-07-15 14:20~14:40(KST) 사이, 근무표 편성 화면 진입 시 2026-07 기존 행 0명으로 확인 → DB 직접 조회로 확정.
- 현재 테이블 행 수(14:55 기준, read-only 조회): users 21 · departments 5 · teams 6 · work_types 6 · **work_schedules 0** (직전 558행).
- 데이터 존재 마지막 확인: 13:47(KST) 근무표 편성 화면에 2026-07 18명/558건 정상 로드(작업 보고 스크린샷).
- 이 저장소 코드의 근무표 쓰기 API 는 (사번×월) 범위 한정 replace/upsert 뿐이라 테이블 전체 삭제 경로 없음. 13:47 이후 터미널 세션에서 실행한 것은 sample 모드 강제 테스트와 코드 수정뿐(Supabase 쓰기 없음).
- 조치: Supabase 쓰기 중단·상태 보존. 시드 재실행·백업/PITR 복원 금지(사용자 승인 대기). 2026-07 복구 시도 금지. 종단 검증은 2027-07 테스트 월 한정 임시 데이터로만 진행(사용자 지시).

## 2026-07-15 13:49 · [터미널] · 근무표 편성 화면 1차 기능 기반 (사번 중심 입력)
- 요청: 전체 사용자 자동 나열 제거, 사번 중심 입력 + 성명·부서·조 자동 조회, 부서·조 편성값 수정, 근무형태 약칭 표시, 행 추가/삭제, 일괄 저장, dirty tracking + 화면 이탈 경고. 디자인 개편·wheel picker·migration 002 제외.
- 변경: `views/schedule_edit.py` 재작성 — selectable_master_grid(행 상태 계약) 기반: 저장된 직원 행만 표시(없으면 빈 행 1개), [행 추가], 신규 행 − 제거/기존 행 체크박스+[행 삭제]→삭제 예정 패널(취소 가능, 저장 시 replace 로 명시 삭제), 사번 paste→성명·부서·조 자동 채움, 날짜 셀 약칭 표시·입력(저장 시 내부 코드 변환, 미등록/모호 약칭·미등록/중복 사번·재직 아님 차단), 변경 셀만 upsert(빈 셀 자동 삭제 없음 — `db.upsert_month_schedules` 신설), dirty 스냅샷 비교 + 사이드바/로그아웃/조건 변경 이탈 확인(`ui.request_nav` 가드) + beforeunload(best effort). `workspace.selectable_master_grid` 에 col_config(폭·pinned·editable) 확장. `supabase_repository._execute` 일시 소켓 오류(10035 등) 1회 재시도.
- 파일: views/schedule_edit.py, views/workspace.py, modules/ui.py, modules/db.py, modules/supabase_repository.py, docs/WORKLOG.md
- 비고: 커밋 안 함(사용자 확인 대기). 부서·조 편성값 영구 저장은 migration 002 미적용 + 근무조 필수 계약으로 이번 단계 미지원(화면 편집·검증만, 저장 시 안내). 브라우저 검증 28항목 중 핵심 전부 통과, 테스트 데이터(2027-07) 정리 완료·2026-07 558건 무영향. 한계: 편집 직후 ~1초 내 즉시 이탈 시 가드가 한 박자 늦을 수 있음(컴포넌트 전송 경합).

## 2026-07-15 08:11 · [터미널] · App Shell 전면 교체 — 단일 다크 사이드바 (디자인 변경 승인 작업)
- 요청: 기존 "1차 아이콘 레일 + 2차 메뉴 패널" 폐기, 사용자 목업(레퍼런스 이미지) 기준 단일 다크 사이드바로 교체. 다크 차콜(#1B1B1D)+골드(#C9A26B) 톤, 크림 본문(#F1EEE9), 하단 사용자 카드, ▤ 숨김/열기. ADMIN 계정 사번은 ADMIN.
- 변경: `modules/ui.py` app_shell 재작성 — 브랜드 헤더(W 로고+생산 근무표/WORKFORCE), 단독 항목(홈→대시보드)+그룹 라벨(근무표·기준정보)+도트 하위 항목, 맨 아래 고정 사용자 카드(아바타+이름+사번+로그아웃), 본문은 브레드크럼(그룹명)만. 기존 상단 헤더(_header)와 «/» 토글 제거, 숨김은 `sb_hidden` session_state+▤ 버튼. CSS 는 `_SHELL_CSS`(--sb-* 토큰)로 분리해 app_shell 에서만 주입 → USER/로그인 화면 무영향. `nav.py` 홈 그룹 라벨 "대시보드"→"홈". `_ROLE_LABEL` 을 CLAUDE.md §6 표시명(조장/조원)으로 정정. DESIGN.md §2·§3·§4·§7.1·§9·§20, CLAUDE.md §7 App Shell 서술 갱신.
- 파일: modules/ui.py, modules/nav.py, DESIGN.md, CLAUDE.md, docs/WORKLOG.md
- 비고: 커밋 안 함(사용자 화면 확인 대기). 브라우저 검증 — ADMIN: 이동/활성/브레드크럼/숨김·열기·상태 유지 OK, MANAGER(2008110301): 기준정보 미노출 OK, USER(2008082501): 전용 화면 무변화 OK. 주의: 이전 세션에서 웹소켓 재접속이 잦을 때 메뉴가 저절로 이동하는 현상 1회 관찰(안정 세션에서는 재현 안 됨) — 재발 시 보고 요망. 대시보드 KPI 카드 등 본문 내부는 이번 범위에서 미변경(레퍼런스의 카드 스타일과 다름).
- 요청: 사이드바(1차 아이콘 레일 + 2차 메뉴 패널)를 SAP Fiori 계열의 절제된 스타일로 정리. "옅은 강조 + 좌측 3px 액센트 바" 문법으로 통일, 수치 스펙 지정.
- 변경: `modules/ui.py` 사이드바 CSS를 `:root`의 `--nav-*` 디자인 토큰 기반으로 재작성. 레일 72px/항목 64px/간격 4px/단색 `#1B2A4A`, 패널 240px/항목 40px/활성 `#EBF1FC`+`#1B4DBF`+액센트 `#4C7DFF`, 라운드 6px·전환 background-color 130ms 통일. DESIGN.md §3.1·§4.1·§7.1 을 구현 토큰 값으로 갱신.
- 파일: modules/ui.py, DESIGN.md, .claude/launch.json (브라우저 검증용 신규)
- 비고: 커밋 안 함(사용자 화면 확인 대기). 브라우저 검증: ADMIN(1001)으로 대시보드/근무표/기준정보 전환·활성 표시·수치(computed style) 확인 완료, 본문·헤더 변화 없음. 레일 상단은 Streamlit 사이드바 헤더(접기 버튼 영역) 높이만큼 내려온 뒤 4px 간격 시작.

## 2026-07-14 15:02 · [데스크탑] · AGENTS.md 신설 + 디자인 동결·도구 역할 분담 규칙 도입
- 요청: 코덱스·클로드 병행 작업 중 디자인 수정 때마다 화면 틀이 크게 바뀌는 문제 해결. 사용자가 정리한 진행 상황 요약(사용자 관리 검증 14/15 PASS, 로그인 수정 미확인, 조 관리 rerun 경합, 저장 메시지 N건 이슈, 다음 단계 후보 순서 등)도 반영.
- 변경: `AGENTS.md` 신설(Codex 규칙 — CLAUDE.md 원본 참조, UI 파일 수정 금지, 디자인 동결, WORKLOG 기록). `CLAUDE.md` §3에 확인 필요 항목·다음 단계 후보 순서 추가, §7에 디자인 동결 조항, §11에 도구 역할 분담(Claude=UI, Codex=로직·데이터) 추가.
- 파일: AGENTS.md (신규), CLAUDE.md, docs/WORKLOG.md
- 비고: 역할 분담은 필요 시 사용자 지시로 변경 가능. CLAUDE.md 규칙 변경 시 AGENTS.md 요약도 함께 갱신할 것.

## 2026-07-14 14:40 · [데스크탑] · 작업 로그(WORKLOG) 체계 도입
- 요청: 터미널/데스크탑을 오가며 작업할 때 서로의 요청·수정 내용을 이해할 수 있게 로그를 남기고 싶음.
- 변경: `docs/WORKLOG.md`를 신설(형식·규칙 정의). `CLAUDE.md` §12에 "재개 시 WORKLOG 확인 + 작업 후 WORKLOG 기록" 규칙 추가.
- 파일: docs/WORKLOG.md (신규), CLAUDE.md
- 비고: 앞으로 두 도구 모두 작업 완료 시 이 파일 맨 위에 항목을 추가한다.
