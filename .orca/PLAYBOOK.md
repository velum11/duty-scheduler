# WorkOps (구 Duty Scheduler) ORCA Overlay

글로벌 `C:\Users\velum\.orca\lee-mode\PLAYBOOK.md`(`ORCA Lean Multi-Agent Playbook`)에 추가되는 프로젝트 규칙이다. 위임 구조·실행 모드·Codex 감사 기준·모델·effort 규칙은 글로벌이 정본이며 여기에 반복하지 않는다. `AGENTS.md` 안전경계 안에서 사용자의 최신 지시가 우선한다.

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

집행 SoT는 이 저장소의 `.claude/agents/` **특화판 8종**이다(동명 글로벌 범용판보다 우선 적용): `recon`·`ui-feature`·`data-contract`·`visual-qa`·`contract-qa`·`integrator`·`ux-architect`·`code-review`. 각 정의의 `model:`(글로벌 PLAYBOOK §3 티어링)과 `skills:`가 전문성을 강제한다.

`ux-architect`는 UI_CENTRIC **구조 변경의 구현 전 설계·UX 자가검토 advisor**다. 발동(하나라도 해당하면 발동, 포함이 제외에 우선): 영역 순서·아키타입·목록-상세 분할·주요 과업 흐름·내비게이션/IA·공용 구조 키트·핵심 액션 위계 변경. 제외(`ui-feature` 단독 연속): 문구·메뉴명·권한 불변 순수 route 배선·§0.6 수치와 액션 위치를 바꾸지 않는 토큰 내 소보정·단일 컨트롤 정렬. 산출은 **대화/task 내 설계 브리프(design brief) 7항**(대상 과업/유지 계약/구조 결정/거부 대안/UX finding/미검증 runtime/acceptance — 하위 필드는 에이전트 정의가 고정)뿐이며 **파일 편집·구현 금지**. 구 명칭 "handoff"는 Orca의 소유권 이전 용어와 충돌해 폐기했다. `ui-feature`가 처음부터 끝까지 화면 Owner이고 advisor 산출은 비구속 입력이다 — mockup 사용자 승인 이하 §7 흐름은 불변.

반복 실패 진단은 새 Owner를 만들지 말고 기존 Owner의 증거를 유지한 채 Codex focused diagnosis 또는 조건부 Fable 승격으로 전환한다.

## 3. 프로젝트 고유 규칙

- 이 프로젝트는 업무용 ERP다 — 정보 밀도·탐색 속도·편집 안전·화면 간 일관성 우선, hero·장식 카드·불필요 애니메이션 금지. 세부 기준과 완료 게이트는 `DESIGN.md`.
- **로컬 산출물(2026-07-29 개정)**: 종전 DLP 생성 금지가 해제되어 스크린샷·이미지·HTML·문서 산출물 생성이 가능하다(정본 규율은 `AGENTS.md` — 위치는 `.orca/artifacts/<작업명>/`·OS temp, 비밀·개인정보 포함 금지 불변). 목업은 실제 Streamlit sample/static 프로토타입을 기본으로 하되 이미지·정적 목업도 허용된다. 실렌더 검증·사용자 sign-off 게이트는 그대로다.
- 목업 단계에서 Supabase 연결·저장·migration을 하지 않는 이유: 승인 전 실데이터 보호(정본은 `AGENTS.md`). 사용자 승인 전 merge·배포·완료 선언 금지.
- **push에 별도 승인이 필요한 이유**: 이 저장소의 push는 Streamlit Cloud 배포로 이어진다(금지 규칙 정본은 `AGENTS.md`).
- 실행: `$env:DUTY_DATA_MODE = "sample"; streamlit run app.py`. focused test는 `test-selection` 스킬과 현재 테스트 목록에서 변경 범위에 맞게 선택하며, 작은 변경마다 전체 회귀를 돌리지 않는다.
- 기존 `app-dev-preview` terminal과 ORCA browser tab을 재사용하고, 완료된 terminal·workspace는 `completed`로 정리한다.

## 4. 안전 경계

`AGENTS.md` 안전경계가 완결된 정본이며 전 항목이 그대로 적용된다. 이 문서는 금지 규칙을 추가·요약·재정의하지 않는다(§3의 항목들은 규칙이 아니라 "왜 적용되는지"의 프로젝트 맥락이다).

## 5. 현재 호환 사항

- ADMIN 기준정보 표시 메뉴는 사용자 관리, 조직 관리, 근무형태 관리다.
- 레거시 `master_departments`, `master_teams` route는 `master_org`로 위임한다.
- 조직 관계(그룹—부서—운영단위)는 기능 계약이지만 화면 표현은 사용자의 목업 승인으로 결정한다.
- 조직 그룹 정본은 현재 데이터 모델의 `organization_groups` capability다. 도입 migration 번호는 DB 이력·진단에서만 사용하고, 적용 여부는 문서 기록이 아니라 live schema를 read-only로 확인해 판단한다.
