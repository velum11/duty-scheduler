# Supabase 실행과 운영

## 1. 데이터 모드

로컬 sample 모드:

```powershell
$env:DUTY_DATA_MODE = "sample"
streamlit run app.py
```

Supabase 모드는 ignored 파일 `.streamlit/secrets.toml`을 사용합니다.

```toml
[app]
data_mode = "supabase"

[supabase]
url = "https://PROJECT_REF.supabase.co"
service_role_key = "SERVER_ONLY_VALUE"
test_project = true
```

동일한 환경변수는 다음과 같습니다.

- `DUTY_DATA_MODE`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `DUTY_SUPABASE_TEST_PROJECT`

service role key는 서버 전용입니다. HTML, custom component, 브라우저 JavaScript, 로그, 문서, Git에 넣지 않습니다.

## 2. Migration

파일 순서는 다음과 같습니다.

1. `supabase/migrations/001_initial_schema.sql`
2. `supabase/migrations/002_schedule_assignments.sql`
3. `supabase/migrations/003_org_structure.sql`
4. `supabase/migrations/004_org_groups.sql`
5. `supabase/migrations/006_near_miss.sql`
6. `supabase/migrations/007_near_miss_improvement.sql`
7. `supabase/migrations/008_password_auth.sql`
8. `supabase/migrations/009_org_category_and_tenure.sql`
9. `supabase/migrations/010_capabilities_and_emails.sql`
10. `supabase/migrations/011_dept_attendance_target.sql`

**005는 결번입니다.** 파일이 존재하지 않으며 누락이 아닙니다.

적용 전에는 `docs/database.md`의 마지막 확인 상태와 대상 프로젝트의 live schema를 read-only로 비교합니다. 문서 기록만으로 적용 여부를 단정하지 않습니다.

주의사항:

- 001은 기본 테이블이 이미 존재할 때 호환성을 자동 보정하지 않습니다.
- 002는 기존 행을 백필하지 않는 DDL 전용 migration입니다.
- 003은 조직 확장 컬럼과 제한적 백필을 포함합니다.
- 004는 `organization_groups` 1급 테이블 신설 + `departments.group_id` FK + 무손실 백필이며, 003의 그룹 컬럼 모델을 대체합니다(상세는 `docs/database.md` §4).
- 006·007은 아차사고 도메인입니다. 앱이 런타임 probe로 적용 여부를 판정하며(`modules/db.py::near_miss_schema_probe` / `near_miss_improvement_schema_probe`), 미적용이면 쓰기를 fail-closed로 차단합니다. **006만 적용된 상태에서 007이 필요한 기능(보완요청)이 활성으로 보이는 결함이 있습니다** — `DESIGN.md` §7.4.
- 사용자 승인 없이 SQL을 실행하지 않습니다.
- 적용 후 앱 프로세스를 재시작하고 관련 readiness와 화면 저장을 확인합니다.

정적 감사는 DB 쓰기 없이 실행할 수 있습니다.

```powershell
python scripts/test_migration_002_audit.py
python scripts/test_migration_003_audit.py
python scripts/test_migration_004_audit.py
```

## 3. 테스트 프로젝트 보호

프로젝트 안전경계의 정본(SoT)은 `AGENTS.md`이며, 아래 §3·§4의 원격·쓰기 관련 규칙은 원격 테스트/migration/Supabase 운영에 필요한 도메인별 구체화입니다.

원격 seed와 CRUD 테스트는 전용 테스트 프로젝트에서만 실행합니다. 코드가 쓰기를 허용하려면 다음 두 조건이 모두 필요합니다.

- `[supabase].test_project = true` 또는 `DUTY_SUPABASE_TEST_PROJECT=true`
- 명령에 `--confirm-test-project`

Sample seed:

```powershell
python scripts/seed_supabase_sample.py --confirm-test-project
```

원격 CRUD 검증:

```powershell
python scripts/test_supabase_crud.py --confirm-test-project
```

CRUD 검증은 고유한 `TEST_*` 레코드만 생성하고 역순으로 정리합니다. 실행 전 대상 project ref와 기존 `TEST_*` 충돌 여부를 확인합니다. 실패 시 자동 정리가 완전했는지 다시 확인합니다.

## 4. 운영 원칙

- 실DB 쓰기, seed, 백필, 삭제는 사용자 승인 범위 안에서만 수행합니다.
- 쓰기 전 대상과 예상 행 수를 출력하고, 쓰기 후 같은 조건으로 검증합니다.
- 개인정보가 포함된 백업은 저장소 밖 또는 gitignore 대상에 보관합니다.
- repository 오류 메시지에서 URL과 key를 노출하지 않습니다.
- Supabase 연결 실패를 sample 성공처럼 표시하지 않습니다.
