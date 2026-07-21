# Duty Scheduler ORCA Overlay

글로벌 `C:\Users\velum\.orca\lee-mode\PLAYBOOK.md`에 추가되는 프로젝트 규칙입니다. 이 파일은 역할·안전·실행 정보만 제공하며 제품 화면의 구체적인 디자인을 강제하지 않습니다.

## 기준 문서

- 기능·권한: `docs/requirements.md`
- 디자인 기준선: `DESIGN.md`
- DB·migration: `docs/database.md`
- Supabase 운영: `docs/supabase-setup.md`
- 최근 인계: `docs/WORKLOG.md` — 요구사항 원본 아님

사용자의 최신 지시가 우선합니다. 코드와 문서가 다르면 실제 route, repository, 테스트를 확인하고 담당 문서를 함께 정리합니다.

## 기본 실행

```powershell
$env:DUTY_DATA_MODE = "sample"
streamlit run app.py
```

기본 focused test:

```powershell
python scripts/test_login_auth.py
python scripts/test_sidebar_ui.py
python scripts/test_master_org.py
python scripts/test_schedule_contracts.py
python -m compileall -q app.py modules views scripts
git diff --check
```

작업마다 전체 명령을 실행하지 않고 변경 범위에 맞는 것만 선택합니다.

## 프로젝트 안전 경계

- 현재 active worktree와 미커밋 변경을 보존합니다.
- 사용자 승인 없이 새 worktree, commit, push, migration, seed, 실DB 쓰기를 하지 않습니다.
- `git reset`, `restore`, `clean`, `revert`를 사용하지 않습니다.
- 원격 CRUD 테스트는 전용 테스트 프로젝트와 보호 플래그가 모두 있을 때만 실행합니다.
- service role key, 개인정보, `.local_sessions.json`, 로컬 DB 백업을 출력하거나 커밋하지 않습니다.

## 역할

- 일반 구현의 기본 Implementer는 Claude Code입니다.
- Codex는 반복 실패의 focused diagnosis, 위험 설계 감사, 범위가 고정된 diff 검수에 사용합니다.
- supervised 작업의 Coordinator는 구현하지 않습니다.
- 작은 변경은 DIRECT로 처리하고 별도 Architect·QA를 자동 생성하지 않습니다.
- 디자인 대안, 목업, 별도 디자인 Reviewer는 사용자가 요청하거나 디자인 선택이 실제로 열려 있을 때만 사용합니다.

## 현재 주의사항

- ADMIN 기준정보의 실제 표시 메뉴는 사용자 관리, 조직 관리, 근무형태 관리입니다.
- 레거시 `master_departments`, `master_teams` route는 `master_org`로 위임합니다.
- 조직 관계는 기능 계약이지만 화면 표현은 사용자 요구에 따라 결정합니다.
- migration 003 적용 여부는 새 작업마다 live schema를 read-only로 확인하며 문서 기록만 믿지 않습니다.

