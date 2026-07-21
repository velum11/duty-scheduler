# 생산 근무표 관리

Streamlit과 Supabase로 만든 사내 근무표 관리 애플리케이션입니다. 관리자는 기준정보와 월별 근무표를 관리하고, 조장은 담당 범위의 근무표를 편성·조회하며, 일반 사용자는 본인 근무표를 확인합니다.

이 저장소의 문서는 현재 구현과 안전한 개발에 필요한 내용만 유지합니다. 과거 계획이나 작업 기록은 제품 요구사항으로 사용하지 않습니다.

## 현재 기능

- 사번 기반 로그인과 30일 세션 유지
- `ADMIN`, `MANAGER`, `USER` 권한별 메뉴와 접근 차단
- 월별 근무표 편성·조회 및 개인 근무표 조회
- 사용자, 조직, 근무형태 기준정보 관리
- 월별 부서·운영단위 편성 스냅샷
- `sample`과 `supabase` 데이터 모드
- 기준정보 AG Grid 편집, 여러 셀 붙여넣기, 저장 전 검증

앱의 공식 이름은 `modules/config.py`의 `APP_NAME`을 기준으로 합니다. ADMIN/MANAGER 사이드바에는 짧은 표시명인 `교대 근무표`가 사용됩니다.

## 빠른 실행

PowerShell 기준입니다.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DUTY_DATA_MODE = "sample"
streamlit run app.py
```

데이터 모드는 반드시 명시합니다. 설정이 없거나 Supabase 연결이 실패해도 sample 모드로 자동 전환하지 않습니다.

Supabase 설정과 원격 테스트 절차는 `docs/supabase-setup.md`를 참고합니다.

## 권한별 화면

| 권한 | 화면 |
|---|---|
| ADMIN | 대시보드, 근무표 편성, 월간 근무표, 내 근무표, 사용자 관리, 조직 관리, 근무형태 관리 |
| MANAGER | 대시보드, 근무표 편성, 월간 근무표, 내 근무표 |
| USER | 대시보드, 월간 근무표, 내 근무표 |

`부서 관리`와 `조 관리`의 레거시 route는 호환을 위해 남아 있지만 실제 화면은 `views/master_org.py`로 위임합니다.

## 테스트

일반적인 변경은 수정 범위에 맞는 스크립트만 실행합니다.

```powershell
python scripts/test_login_auth.py
python scripts/test_sidebar_ui.py
python scripts/test_master_org.py
python scripts/test_schedule_contracts.py
python -m compileall -q app.py modules views scripts
git diff --check
```

모든 로컬 계약 테스트를 실행해야 할 때만 다음을 사용합니다.

```powershell
Get-ChildItem scripts\test_*.py |
  Where-Object { $_.Name -ne "test_supabase_crud.py" } |
  ForEach-Object { python $_.FullName; if ($LASTEXITCODE -ne 0) { break } }
```

`scripts/test_supabase_crud.py`는 원격 테스트 프로젝트에 쓰기 작업을 하므로 명시적인 승인과 보호 플래그 없이는 실행하지 않습니다.

## 주요 구조

```text
app.py                         로그인 게이트와 route dispatch
modules/
  auth.py                      사번 로그인과 세션
  config.py                    데이터 모드와 서버 설정
  db.py                        sample/Supabase 데이터 파사드
  nav.py                       권한별 메뉴 데이터
  supabase_repository.py       Supabase 읽기·쓰기
  ui.py                        App Shell과 공용 UI
  validators.py                저장 계약 검증
views/
  dashboard.py                 대시보드
  schedule_edit.py             근무표 편성
  schedule_view.py             월간 근무표
  my_schedule.py               개인 근무표
  master_users.py              사용자 관리
  master_org.py                조직 관리
  master_work_types.py         근무형태 관리
  workspace.py                 공용 그리드·조회 UI
supabase/migrations/           순서가 있는 스키마 변경
scripts/                       로컬 계약 테스트와 승인형 원격 도구
docs/                          제품·데이터·운영 문서
```

## 문서 책임

| 문서 | 책임 |
|---|---|
| `docs/requirements.md` | 기능, 권한, 저장 계약 |
| `DESIGN.md` | 현재 디자인 시스템과 공용 UI 기준 |
| `docs/database.md` | 테이블 관계와 migration 상태 |
| `docs/supabase-setup.md` | 실행 환경과 Supabase 운영 절차 |
| `CLAUDE.md` | Claude용 저장소 작업 지침 |
| `AGENTS.md` | Codex 등 범용 코딩 에이전트 지침 |
| `docs/WORKLOG.md` | 최근 작업 인계 메모. 요구사항 원본이 아님 |

충돌 시 사용자의 최신 지시와 실제 코드·테스트를 먼저 확인하고, 각 영역의 담당 문서를 수정합니다.
