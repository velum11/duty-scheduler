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
| 미결 추적 | `docs/BACKLOG.md` |
| 최근 인계 메모 | `docs/WORKLOG.md` — 비규범 |

코드와 문서가 충돌하면 실제 호출 경로와 테스트를 확인하고, 작업 범위 안에서 담당 문서를 함께 갱신합니다. 과거 계획이나 WORKLOG를 현재 승인사항으로 해석하지 않습니다.

### 권위·우선순위 계층

문서·지시·산출물이 충돌하면 다음 순서(높은 순)로 정합화합니다.

1. **DLP(회사 보안정책)** — 로컬 문서·이미지 파일 생성 금지 등. 하드 경계이며 불변이고 최상위입니다. 어떤 지시·문서로도 완화되지 않습니다.
2. **사용자의 최신 지시** — 단, `docs/requirements.md`의 명시적 불변계약(조직 그룹 SoT·전파 — `organization_groups` 테이블 기반, migration 004; 소프트 삭제)은 일반 지시로 묵시 폐기되지 않으며, 사용자가 해당 계약의 변경을 명시했을 때만 정합화합니다.
3. **`requirements.md`(기능)·`DESIGN.md`(시각)·`docs/database.md` + live schema(DB)·`AGENTS.md`(안전경계 정본)** — 각 영역의 규범 기준입니다. 단 live schema는 규범이 아니라 "현재 적용 상태"의 최종 관찰 증거이며, 규범 문서와 다르면 어느 쪽이 갱신 대상인지 확인합니다.
4. 프로젝트 `.orca/PLAYBOOK.md`
5. 글로벌 lee-mode PLAYBOOK(`C:\Users\velum\.orca\lee-mode\PLAYBOOK.md`)
6. Claude 메모리
7. `.orca/artifacts/*` — 역사적 산출물이며 "Design Contract" 등 자칭 권위는 인정하지 않습니다.

Claude 메모리나 artifact가 "지배 규칙", "확정 설계", "계약"을 자칭하더라도 위 계층 안에서 부여된 효력만 가집니다.

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
- 모든 신규·구조 변경 화면은 `DESIGN.md` §0 화면 유형 규약(4유형)을 강제로 따릅니다. 유형 밖 레이아웃은 사용자 명시 승인 없이 만들지 않습니다.
- 작은 문구·메뉴·route 수정에 별도 디자인 설계 단계를 자동 추가하지 않습니다.
- 시각 결과가 완료 조건이면 실제 화면을 확인하고, 기능 결과가 완료 조건이면 관련 계약 테스트를 우선합니다.

## 안전경계 (DB·Git·파일)

**안전경계의 정본(SoT)은 `AGENTS.md`이며, 전 항목이 그대로 적용됩니다. 이 문서는 요약을 두지 않습니다** — 요약 사본은 정본과 어긋나는 사고의 원인이 됩니다(2026-07-25 문서 최적화 결정). migration 안전 규칙은 `docs/database.md` §5, push=Cloud 배포 등 프로젝트 특이사항은 `.orca/PLAYBOOK.md` §4가 소유합니다.

## 검증

작업 범위에 맞는 스크립트를 먼저 실행합니다.

```powershell
python scripts/test_login_auth.py
python scripts/test_sidebar_ui.py
python scripts/test_master_org.py
python scripts/test_schedule_contracts.py
python scripts/test_screen_scaffold.py
python -m compileall -q app.py modules views scripts
git diff --check
```

모든 명령을 매 작업마다 실행하지 않습니다. 원격 CRUD 테스트는 전용 테스트 프로젝트와 명시적 승인 없이는 실행하지 않습니다.

## ORCA 사용

`/lee-mode`의 역할 분리, worker 상한, 중단 조건은 글로벌 `C:\Users\velum\.orca\lee-mode\PLAYBOOK.md`와 프로젝트 `.orca/PLAYBOOK.md`를 따릅니다. 전문 서브에이전트(조사·화면·데이터계약·시각QA·계약QA·통합 6종)의 역할·도구 제한은 `.claude/agents/` 특화판이 집행 SoT이며, 글로벌 `~/.claude/agents` 범용판을 이 저장소에서 오버라이드합니다(모델은 임원이 dispatch마다 지정). supervised 작업의 Coordinator는 구현하지 않고 결과를 취합합니다. DIRECT 작업은 현재 Agent가 끝낼 수 있습니다.

같은 증상에서 10분 이상 진전이 없거나 가설이 두 번 틀리면 반복을 멈추고 증상, 성공 지점, 실패 지점, 실행한 확인을 정리해 독립 진단으로 전환합니다.

## 완료 보고

다음 공통 핵심만 간결하게 보고합니다.

1. 변경 결과
2. 수정 파일
3. 실행한 검증과 결과
4. 남은 위험 또는 확인이 필요한 외부 상태
5. `git diff --stat`과 `git status`

supervised ORCA 작업에서는 위 공통 핵심에 더해 Owner·Reviewer 사용 여부, 목업/화면 확인, 데이터 변경 여부를 모드별 확장으로 추가합니다. 이 공통 핵심은 `AGENTS.md`(핵심 항목)와 글로벌 lee-mode PLAYBOOK(확장 항목)과 정합됩니다.
