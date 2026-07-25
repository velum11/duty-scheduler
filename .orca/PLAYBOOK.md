# Duty Scheduler ORCA Overlay

글로벌 `C:\Users\velum\.orca\lee-mode\PLAYBOOK.md`(`ORCA Lean Multi-Agent Playbook`, 2026-07-25판)에 추가되는 프로젝트 규칙이다. 위임 구조·실행 모드·Codex 감사 기준·모델 지정 규칙은 글로벌이 정본이며 여기에 반복하지 않는다. 사용자의 최신 지시가 최우선이다.

## 1. 기준 문서

- 기능·권한: `docs/requirements.md`
- 디자인 기준선: `DESIGN.md`
- DB·migration: `docs/database.md`
- Supabase 운영: `docs/supabase-setup.md`
- 안전 경계(정본): `AGENTS.md`
- 미결 추적: `docs/BACKLOG.md`
- 최근 인계: `docs/WORKLOG.md` — 비규범

과거 문서만 믿지 않고 실제 route, repository, schema와 테스트를 확인한다.

## 2. 에이전트 매핑

집행 SoT는 이 저장소의 `.claude/agents/` **특화판 6종**이다(동명 글로벌 범용판보다 우선 적용): `recon`·`ui-feature`·`data-contract`·`visual-qa`·`contract-qa`·`integrator`. 반복 실패 진단은 새 Owner를 만들지 말고 기존 Owner + Codex focused diagnosis로 한다(글로벌 §2 서킷브레이커).

## 3. 프로젝트 고유 규칙

- 이 프로젝트는 업무용 ERP다 — 정보 밀도·탐색 속도·편집 안전·화면 간 일관성 우선, hero·장식 카드·불필요 애니메이션 금지. 세부 기준과 완료 게이트는 `DESIGN.md`.
- **DLP가 적용되는 이유**: 회사 보안정책 환경이다(규칙 정본은 `AGENTS.md` 안전경계 — 여기서 재서술하지 않음). 그 제약 아래의 목업 실행 방법: 실제 Streamlit 코드의 sample/static 프로토타입 + 목표 viewport 실화면 확인. `.orca/artifacts/`의 정적 prototype은 DLP가 허용하는 환경에서만 사용한다.
- 목업 단계에서 Supabase 연결·저장·migration을 하지 않는 이유: 승인 전 실데이터 보호(정본은 `AGENTS.md`). 사용자 승인 전 merge·배포·완료 선언 금지.
- **push에 별도 승인이 필요한 이유**: 이 저장소의 push는 Streamlit Cloud 배포로 이어진다(금지 규칙 정본은 `AGENTS.md`).
- 실행: `$env:DUTY_DATA_MODE = "sample"; streamlit run app.py`. focused test 목록은 `CLAUDE.md` § 검증이 정본이며, 작은 변경마다 전체 회귀를 돌리지 않는다.
- 기존 `app-dev-preview` terminal과 ORCA browser tab을 재사용하고, 완료된 terminal·workspace는 `completed`로 정리한다.

## 4. 안전 경계

`AGENTS.md` 안전경계가 완결된 정본이며 전 항목이 그대로 적용된다. 이 문서는 금지 규칙을 추가·요약·재정의하지 않는다(§3의 항목들은 규칙이 아니라 "왜 적용되는지"의 프로젝트 맥락이다).

## 5. 현재 호환 사항

- ADMIN 기준정보 표시 메뉴는 사용자 관리, 조직 관리, 근무형태 관리다.
- 레거시 `master_departments`, `master_teams` route는 `master_org`로 위임한다.
- 조직 관계(그룹—부서—운영단위)는 기능 계약이지만 화면 표현은 사용자의 목업 승인으로 결정한다.
- 조직 그룹 정본은 `organization_groups` 테이블(migration 004로 도입)이다. 적용 여부는 문서 기록이 아니라 live schema를 read-only로 확인해 판단한다.
