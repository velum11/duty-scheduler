# 최근 작업 인계

이 파일은 다음 작업자가 현재 상태를 빠르게 확인하기 위한 짧은 기록입니다. 제품 요구사항, 디자인 승인, DB 적용 상태의 원본으로 사용하지 않습니다. 기능은 `docs/requirements.md`, 디자인은 `DESIGN.md`, DB는 live schema와 `docs/database.md`를 확인합니다.

새 항목은 맨 위에 1~3개 bullet로 작성하고 오래된 항목은 제거합니다. 상세 과정은 Git diff와 작업 보고서에서 확인합니다.

## 2026-07-23 · 기준정보 3화면 ERP 밀도·일관성 정리

- 데스크톱 ERP CRUD 원칙(개성보다 정보밀도·탐색속도·편집안전·화면간 일관성)으로 Wave B를 재점검. Codex 독립 디자인 리뷰(sol high)에서 실질 리스크는 장식이 아니라 밀도·일관성으로 판명 — 조직 3열 최소폭 1366px 초과, 액션바 위치 화면 불일치, 근무형태 미리보기 카드 중복·과대.
- 4-Owner 적용(lee-mode): 조직=액션바 표 위 통일·▸열림 중복칩 제거·필터결과 요약·열폭 축소·단계배지/커넥터 제거, 근무형태=미리보기 색·약칭 계약(DESIGN.md §150) 유지하며 조밀화·건수 필터결과 통일, 공통 grid 높이 행수 적응(132~460px), 사용자=요약칩 유지·통일 정합. 결정: 액션바=표 위, 건수=필터결과 기준.
- Codex 재검수 DESIGN_OK, 회귀 all-green·compileall OK. 커밋 `edc60c7` push. 미해결: 배포 navy 보호 배지는 Streamlit Cloud 자동 재배포 미전파(대시보드 수동 reboot 필요 정황).

## 2026-07-23 · 기준정보 Wave B 통일 디자인 검증·완료

- 중단된 ORCA 작업(미커밋 Wave B: ag-grid native bool 전환·조직 드릴다운/잠김 밀도·사용자 사번 읽기전용 완화+요약칩·근무형태 미리보기 재구성)을 복구하고, lee-mode 4-Owner 병렬 라이브 DOM 검증으로 결함 0·무수정 확인. Codex 사전/사후 read-only 검수 모두 clear(MERGE_OK).
- 회귀 all-green(login/sidebar/org/org_new/users_new/work_types/schedule)·compileall OK. `feature/supabase-crud`에 `4c3873f` 커밋·push, 백업 브랜치 `backup/wave-b-checkpoint-20260723` 이중 보관. `.orca/PLAYBOOK.md`는 미수정 보존.
- 남은 확인: 보호행 navy 배지(#1E3A6E)는 배포 반영 지연으로 prod 육안 미확정(재확인 폴링 중). sample(8502) 관리자 사번은 ADMIN 아닌 `1001`(ADMIN은 supabase 전용).

## 2026-07-21 · 기준정보 3화면 통합 재설계

- 사용자·조직·근무형태 관리를 하나의 공통 디자인·편집 모델로 통합하고 공통 기반을 `views/master/`(DraftState·MasterGridSpec·run_save·PersistResult·ReadinessState·master_action_bar)로 분리했습니다. 규범은 `DESIGN.md`, 기능 계약은 `docs/requirements.md`.
- 부분성공 저장 원장(성공/실패 키)·저장 실패 시 draft 보존·삭제 실패 분리·migration 003 준비 3-state(준비됨/미적용/확인 실패, UI+repository 쓰기 차단)를 보강하고, 상태를 색+형태/라벨 이중부호화로 표시합니다.
- 로컬 계약 테스트 all-green, 브라우저 재QA(1366×768·1024×768) pass. 커밋 예정.

## 2026-07-21 · 문서 기준 재정리

- 모든 프로젝트 MD를 현재 구현 기준으로 축소하고 문서별 책임을 분리했습니다.
- 특정 조직관리 레이아웃과 일률적인 디자인 절차를 요구사항·에이전트 지침에서 제거했습니다.

## 2026-07-21 · 로그인 안정화

- 사번 조회를 trim + 대소문자 무시로 통일하고, 대소문자만 다른 중복 사용자는 활성·정확 일치 순으로 선택하도록 수정했습니다.
- `scripts/test_login_auth.py`와 브라우저에서 로그인 경로를 검증했습니다. 비활성 소문자 `admin` 중복 행은 실DB에 남아 있을 수 있습니다.

## 2026-07-20 · 조직 관리와 메뉴 통합

- ADMIN 기준정보 메뉴는 사용자 관리, 조직 관리, 근무형태 관리로 표시되며 레거시 부서·조 route는 `views/master_org.py`로 위임합니다.
- 조직 확장 코드는 migration 003 적용 전 조회 fallback과 저장 차단을 지원합니다. 마지막 live 확인 당시 003은 미적용이었습니다.

## 2026-07-16 · 월 편성 스냅샷 연결

- migration 002 적용과 월 편성 저장을 확인했습니다. 신규 근무는 해당 월 편성이 있으면 `schedule_assignment_id`로 연결합니다.
- 기존 근무는 자동 백필하지 않으며 편성이 없으면 사용자 현재 소속을 표시용으로만 사용합니다.

## 2026-07-16 · App Shell과 기준정보 공용 UI

- ADMIN/MANAGER는 단일 다크 사이드바, USER는 별도 상단 메뉴 구조를 사용합니다.
- 기준정보 화면은 공용 AG Grid 행 상태와 작업 버튼을 사용합니다.
