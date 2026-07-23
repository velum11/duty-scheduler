# Duty Scheduler ORCA Overlay

글로벌 `C:\Users\velum\.orca\lee-mode\PLAYBOOK.md`에 추가되는 프로젝트 규칙이다. 제품의 특정 레이아웃이나 디자인 결과를 강제하지 않는다.

## 기준 문서

- 기능·권한: `docs/requirements.md`
- 디자인 기준선: `DESIGN.md`
- DB·migration: `docs/database.md`
- Supabase 운영: `docs/supabase-setup.md`
- 최근 인계: `docs/WORKLOG.md` — 요구사항 원본 아님

사용자의 최신 지시가 우선한다. 실제 route, repository, 테스트를 확인하고 과거 WORKLOG를 현재 승인사항으로 해석하지 않는다.

## Feature Station

현재 active ORCA worktree를 기본 Feature Station으로 사용한다.

- 같은 화면·기능은 같은 Claude Feature Owner terminal을 유지한다.
- 분석, 목업, 사용자 피드백, 구현, 수정, focused test를 같은 Owner가 소유한다.
- Codex 검토가 다시 필요하면 같은 Reviewer terminal을 재사용한다.
- 살아 있는 `app-dev-preview` terminal과 ORCA browser tab을 재사용한다.
- 새 창·preview 요청 때문에 Feature Owner의 현재 작업을 중단하지 않는다.
- 의미 있는 상태 변화에만 workspace status와 한 줄 comment를 갱신한다.

현재 미커밋 변경에 의존하는 작업은 active worktree에서 수행한다. 사용자의 명시적 요청이나 실제 checkout 충돌 없이 새 worktree를 만들지 않는다.

## 화면 목업

레이아웃, 정보 구조, 시각 위계 또는 주요 상호작용을 바꾸는 화면 개발은 구현 전에 눈으로 확인할 수 있는 목업을 만든다.

Feature Owner는 `developing-with-streamlit`과 `frontend-design`을 함께 사용한다. 전자는 구현 가능성과 상태·데이터 동작을, 후자는 시각 완성도를 담당한다. 두 스킬이 충돌하면 사용자 요구, 기능 계약, 데이터 안전, 기존 제품 일관성, Streamlit 제약 순으로 우선한다.

이 프로젝트는 업무용 ERP 화면이다. hero, 마케팅형 구성, 장식적 카드, 불필요한 애니메이션과 개성을 위한 개성을 만들지 않는다. 표의 탐색성, 필터·행동 버튼의 위치 일관성, 편집·저장 상태의 명확성, 한 화면의 실용적 정보 밀도를 우선한다.

목업 workflow는 환경별 2-track이다.

이 프로젝트/DLP 환경(기본):

- 별도 HTML·PNG·리포트 파일을 만들지 않는다. 회사 DLP는 로컬 문서·이미지·리포트 파일 생성을 금지한다.
- 실제 Streamlit 코드의 미승인 프로토타입(sample 또는 static 데이터)으로 목업을 만든다.
- ORCA browser에서 목표 viewport로 사용자가 실화면을 확인한다.
- 사용자 sign-off 후 같은 Feature Owner가 그 프로토타입을 최종화한다.
- sign-off 전에는 merge·배포·완료 선언을 하지 않는다.
- Supabase 연결·쓰기·migration은 목업 단계에서 계속 금지한다.

artifact 허용 환경에서만: 정적 HTML/CSS prototype과 screenshot을 `.orca/artifacts/<feature>/`에 만들어 승인→구현 흐름을 쓸 수 있다.

작은 문구·메뉴·route·스타일 보정에는 목업을 강제하지 않는다. 대안 수와 특정 화면 배치는 미리 정하지 않는다.

## 실행과 테스트

```powershell
$env:DUTY_DATA_MODE = "sample"
streamlit run app.py
```

관련 변경에 필요한 focused test만 선택한다.

```powershell
python scripts/test_login_auth.py
python scripts/test_sidebar_ui.py
python scripts/test_master_org.py
python scripts/test_schedule_contracts.py
python -m compileall -q app.py modules views scripts
git diff --check
```

## 안전 경계

- 현재 미커밋 변경을 보존한다.
- 사용자 승인 없이 commit, push, migration, seed, 실DB 쓰기를 하지 않는다.
- `git reset`, `restore`, `clean`, `revert`를 사용하지 않는다.
- 원격 CRUD 테스트는 전용 테스트 프로젝트와 보호 플래그가 모두 있을 때만 실행한다.
- service role key, 개인정보, `.local_sessions.json`, 로컬 DB 백업을 출력하거나 커밋하지 않는다.
- 화면 디자인·목업 중 실제 사용자 입력 데이터와 Supabase 데이터를 변경하지 않는다.

## 현재 호환 사항

- ADMIN 기준정보 표시 메뉴는 사용자 관리, 조직 관리, 근무형태 관리다.
- 레거시 `master_departments`, `master_teams` route는 `master_org`로 위임한다.
- 조직 관계는 기능 계약이지만 화면 표현은 사용자의 목업 승인으로 결정한다.
- migration 003 적용 여부는 live schema를 read-only로 확인하고 문서 기록만으로 단정하지 않는다.
