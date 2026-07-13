# Supabase data setup

## Safety boundary

Use a dedicated test project for the migration, seed, and CRUD test. The scripts refuse
remote writes unless both of these conditions are true:

- `[supabase].test_project = true` or `DUTY_SUPABASE_TEST_PROJECT=true`
- `--confirm-test-project` is passed on the command line

The service role key belongs only in server-side Streamlit secrets or server environment
variables. It must never be embedded in HTML, a custom component, or browser code.

## Configuration

Create the ignored file `.streamlit/secrets.toml`:

```toml
[app]
data_mode = "supabase"

[supabase]
url = "https://PROJECT_REF.supabase.co"
service_role_key = "SERVER_ONLY_VALUE"
test_project = true
```

Equivalent environment variables are `DUTY_DATA_MODE`, `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, and `DUTY_SUPABASE_TEST_PROJECT`.

For local CSV/session testing, explicitly select sample mode:

```powershell
$env:DUTY_DATA_MODE = "sample"
```

## Schema

Review and apply `supabase/migrations/001_initial_schema.sql` to a clean test project.
If any of the five table names already exist, inspect their columns, keys, foreign keys,
and data before applying the migration. `create table if not exists` does not reconcile an
incompatible existing table, and this repository intentionally does not drop or rewrite it.

The migration enables RLS but does not add browser-client policies. The current app uses a
server-side service role client because login is still employee-number based and is not
Supabase Auth. Production RLS and authentication are separate follow-up work.

## Sample seed

```powershell
python scripts/seed_supabase_sample.py --confirm-test-project
```

The seed uses natural-key upserts in dependency order and can be run more than once.

## CRUD verification

```powershell
python scripts/test_supabase_crud.py --confirm-test-project
```

The test creates unique `TEST_*` rows, verifies create/read/update/upsert/delete and a fresh
client read, then removes only those test rows in reverse dependency order.
