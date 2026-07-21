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

적용 전에는 `docs/database.md`의 마지막 확인 상태와 대상 프로젝트의 live schema를 read-only로 비교합니다. 문서 기록만으로 적용 여부를 단정하지 않습니다.

주의사항:

- 001은 기본 테이블이 이미 존재할 때 호환성을 자동 보정하지 않습니다.
- 002는 기존 행을 백필하지 않는 DDL 전용 migration입니다.
- 003은 조직 확장 컬럼과 제한적 백필을 포함합니다.
- 사용자 승인 없이 SQL을 실행하지 않습니다.
- 적용 후 앱 프로세스를 재시작하고 관련 readiness와 화면 저장을 확인합니다.

정적 감사는 DB 쓰기 없이 실행할 수 있습니다.

```powershell
python scripts/test_migration_002_audit.py
python scripts/test_migration_003_audit.py
```

## 3. 테스트 프로젝트 보호

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
