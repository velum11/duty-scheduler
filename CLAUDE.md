# CLAUDE.md

Claude Code가 이 저장소에서 작업할 때 사용하는 프로젝트 지침입니다. 이 파일은 제품 사양이나 화면 설계 원본이 아닙니다.

## 프로젝트

- Python 3.11+ / Streamlit / pandas / Supabase / streamlit-aggrid
- 진입점: `app.py`
- 데이터 모드: `sample` 또는 `supabase`를 명시적으로 선택
- 공식 앱 이름: `modules/config.py::APP_NAME`
- 핵심 목적: 사내 월별 근무표 편성·조회와 관련 기준정보 관리

## 기준 문서

| 영역 | 기준 |
|---|---|
| 기능·권한·저장 계약 | `docs/requirements.md` |
| UI 기준선 | `DESIGN.md` |
| 데이터 모델·migration | `docs/database.md` |
| 실행·Supabase 운영 | `docs/supabase-setup.md` |
| 최근 인계 메모 | `docs/WORKLOG.md` — 비규범 |

사용자의 최신 지시가 가장 우선합니다. 코드와 문서가 충돌하면 실제 호출 경로와 테스트를 확인하고, 작업 범위 안에서 담당 문서를 함께 갱신합니다. 과거 계획이나 WORKLOG를 현재 승인사항으로 해석하지 않습니다.

## 작업 전 확인

```powershell
git status --short
git diff --stat
```

그다음 관련 route, view, repository, 테스트를 확인합니다. 이름이 비슷한 파일을 추정해서 고치지 않습니다. 현재 조직 관리 route는 `app.py`, `modules/nav.py`, `modules/ui.py`, `views/master_org.py`를 함께 추적해야 합니다.

## 안정적인 계약

- 권한 코드는 `ADMIN`, `MANAGER`, `USER`입니다.
- 사번 로그인 비교는 trim과 대소문자 무시를 사용하되 DB 원본 사번을 임의 변환하지 않습니다.
- 데이터 모드 누락이나 Supabase 오류를 sample 데이터로 숨기지 않습니다.
- 부서·운영단위·사용자·근무형태 참조 무결성을 유지합니다.
- 직원·일자별 근무는 한 건이며, 직원·월별 편성 스냅샷은 한 건입니다.
- 과거 월 편성이 없을 때 현재 사용자 소속을 표시용 fallback으로 사용할 수 있지만 자동 저장하지 않습니다.
- 기준정보 삭제는 참조 관계를 확인하고 가능한 경우 비활성화를 우선합니다.
- 조직 데이터는 그룹, 부서, 운영단위 관계를 가지지만 화면 배치나 표현 방식은 이 관계만으로 결정하지 않습니다.

## UI 작업

- 명시적인 디자인 변경이 아니면 기존 공용 UI와 주변 화면을 보존합니다.
- 디자인 변경이면 `DESIGN.md`와 사용자의 현재 요구를 확인합니다.
- 특정 레이아웃, 트리 여부, 패널 수, 화면 방향을 이 문서가 강제하지 않습니다.
- 작은 문구·메뉴·route 수정에 별도 디자인 설계 단계를 자동 추가하지 않습니다.
- 시각 결과가 완료 조건이면 실제 화면을 확인하고, 기능 결과가 완료 조건이면 관련 계약 테스트를 우선합니다.

## DB와 보안

사용자 승인 없이 migration, seed, 백필, 실DB 쓰기, 운영 데이터 삭제를 실행하지 않습니다. service role key는 서버 전용이며 브라우저 코드, HTML, 로그, 문서에 노출하지 않습니다.

migration 파일은 적용 이력을 확인하기 전 수정하지 않습니다. 적용 여부가 불명확하면 `docs/database.md`에 추정 상태를 쓰지 않고 read-only 확인이 필요하다고 기록합니다.

## Git과 파일

- 미커밋 변경을 보존합니다.
- 관련 없는 리팩터링이나 일괄 포맷을 하지 않습니다.
- 사용자 지시 없이 `git reset`, `restore`, `clean`, `revert`, commit, push를 하지 않습니다.
- 새 worktree는 사용자가 요청하거나 실제 checkout 충돌이 있을 때만 사용합니다.

## 검증

작업 범위에 맞는 스크립트를 먼저 실행합니다.

```powershell
python scripts/test_login_auth.py
python scripts/test_sidebar_ui.py
python scripts/test_master_org.py
python scripts/test_schedule_contracts.py
python -m compileall -q app.py modules views scripts
git diff --check
```

모든 명령을 매 작업마다 실행하지 않습니다. 원격 CRUD 테스트는 전용 테스트 프로젝트와 명시적 승인 없이는 실행하지 않습니다.

## ORCA 사용

`/lee-mode`의 역할 분리, worker 상한, 중단 조건은 글로벌 `C:\Users\velum\.orca\lee-mode\PLAYBOOK.md`와 프로젝트 `.orca/PLAYBOOK.md`를 따릅니다. supervised 작업의 Coordinator는 구현하지 않고 결과를 취합합니다. DIRECT 작업은 현재 Agent가 끝낼 수 있습니다.

같은 증상에서 10분 이상 진전이 없거나 가설이 두 번 틀리면 반복을 멈추고 증상, 성공 지점, 실패 지점, 실행한 확인을 정리해 독립 진단으로 전환합니다.

## 완료 보고

다음만 간결하게 보고합니다.

1. 변경 결과
2. 수정 파일
3. 실행한 검증과 결과
4. 남은 위험 또는 확인이 필요한 외부 상태
5. `git diff --stat`과 `git status`
