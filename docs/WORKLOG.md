# 최근 작업 인계

이 파일은 다음 작업자가 현재 상태를 빠르게 확인하기 위한 짧은 기록입니다. 미결 추적은 `docs/BACKLOG.md`가 정본입니다.

## 2026-07-25 · 화면 유형 규약(§0) 확정 — 디자인 발산 원천 차단 (문서+스캐폴드+테스트 3중 강제)

- 사용자 결정(인터뷰 4문항): 종전 "레이아웃 미강제" 원칙 **폐지** → 모든 신규·구조 변경 화면은 4유형(`EDIT_GRID`/`READ_VIEW`/`MATRIX_EDIT`/`DASHBOARD`) 중 하나를 선언하고 그 크롬만 사용(표준 원본=기준정보 3화면, 유형 밖은 사용자 승인+규약 개정 필수). DESIGN.md §0 신설, CLAUDE.md·requirements.md 미강제 조항 교체, ui-feature 특화판에 하드 규칙.
- 집행 장치(ui-feature 부장 Opus 위임, 첫 실전 — 셀프 검증 포함 완료 보고): `views/common/scaffold.py`(`page_chrome`+archetype 검증), 9개 화면 `SCREEN_ARCHETYPE` 선언(렌더 무변경), `scripts/test_screen_scaffold.py`(34 checks — 선언 검사+미등록 신규 화면 강제+스캐폴드 단위). 회귀 unified 195·sidebar 42·users_new all-green, compileall OK.
- **감사 부채**: 공용 모듈 신설이라 글로벌 §5 기준 Codex 감사 대상이나 Codex 불가 → 폴백(사용자 게이트)으로 대체. 추가 무해(렌더 0 변경·additive)이며 기존 화면 크롬의 scaffold 이전은 Phase B(BACKLOG).

## 2026-07-25 · 부장(전문 에이전트) 역할 강화 — 셀프 검증 의무 + 도메인 지식 내장

- 인터뷰(4차 3문항) 확정 적용(프로젝트 특화판 6종만, 도구 확장 없음): **① 셀프 검증 의무** — ui-feature(focused test+compileall+UI 변경 시 Playwright headless 자가측정: 셀 정렬·잘림 스모크·서버 신선도 확인), data-contract(계약 테스트 해당분), integrator(통합 후 직접 재검증). 독립 QA(visual-qa·contract-qa)·Codex 감사는 대체하지 않음. **② 도메인 지식 내장** — ui-feature 화면 오너십 맵(공통 기반 `views/master/`=3화면 영향 명시)·조직 3시트 확정 설계·1366×768, data-contract 파사드 구조·자연키·004 probe 대상·display_order 게이트, recon 구조 지식, integrator 기본 브랜치·worktree 구버전 스냅샷 주의, visual-qa 공통 기반 변경 시 3화면 전수 측정.
- 완료판정 체크리스트·에스컬레이션 프로토콜·인앱 브라우저 도구 부여·글로벌 범용판 적용은 미채택(후보로 기록 안 함 — 필요 시 재인터뷰). 직전 push로 `cc9ca70..ff601c5` 4커밋 origin 반영, BACKLOG 미푸시 항목 정리. 제품 요구사항, 디자인 승인, DB 적용 상태의 원본으로 사용하지 않습니다. 기능은 `docs/requirements.md`, 디자인은 `DESIGN.md`, DB는 live schema와 `docs/database.md`를 확인합니다.

새 항목은 맨 위에 1~3개 bullet로 작성하고 오래된 항목은 제거합니다. 상세 과정은 Git diff와 작업 보고서에서 확인합니다.

## 2026-07-25 · md 최적화 — 에이전트 2계층 범용화·안전경계 참조화·오버레이 델타화·BACKLOG 신설

- 인터뷰(3차 4문항)로 확정 적용: **① 2계층 범용화** — 글로벌 `~/.claude/agents/` 범용판 6종 신설(프로그램 개발 한정, 이미지·홈페이지류 제외 — 별도 체계 예정), 프로젝트 특화판은 유지(동명 우선 적용). **② 안전경계 참조화** — CLAUDE.md의 DB·Git 요약 2개 절을 "AGENTS.md 전 항목 적용" 참조로 축소(요약 사본 drift 차단). **③ 오버레이 델타 재작성** — 07-24 부서 구조 확장본(미커밋)을 6종 체계 델타로 대체(원본은 `~/.orca/lee-mode/duty-overlay.bak-20260725.md` 백업), 글로벌 중복(감사기준·위임규칙) 제거. **④ `docs/BACKLOG.md` 신설** — WORKLOG에만 있던 미결(§98·005 목록화·P3·worktree 정리)을 이관, 미채택 후보(정합 스크립트·artifacts INDEX·글로벌 버전기록)도 보관.
- 모순 수정: supabase-setup.md migration 목록에 004 추가(003까지만 나열되던 낡은 기록 — 중복 서술 drift의 실증 사례), 004 audit 스크립트 명령 추가. 오버레이 호환사항의 003 서술을 004 정본으로 정정.
- 프로세스 교훈(메모리 저장): **사용자가 문제를 던지면 분석·인터뷰까지만 — 편집은 명시 승인 후.** 선택지 제시는 장단점 포함 상세 설명.
- 잔존 모순 후속 해소: readiness(조직 확장 스키마) 라벨의 "migration 003" 표기를 004 정본으로 정정 — requirements§91·DESIGN§140(배너 문구)·`lifecycle.py` 기본 문구·repository 오류 문구·게이트 서술 주석 일괄(probe 실검사 대상은 `organization_groups`+`group_id`=004임을 코드로 확인). master 5종 테스트 all-green(common·unified 195·users_new·org 67·work_types_new 81)·compileall·diff-check OK.

## 2026-07-25 · 서브에이전트 전문화 체계 확정 — PLAYBOOK·skill 재작성 + .claude/agents 6종

- 사용자 인터뷰(8문항+2차 3문항)로 위임 거버넌스 재설계 확정: **직무 6종 전문 에이전트(`.claude/agents/` = 집행 SoT: recon·ui-feature·data-contract·visual-qa·contract-qa·integrator, 도구 하드 제한) · 1단 위임(재spawn 차단, ORCA 포함 — 부장 하위계층 폐기) · 혼합 발동(DIRECT 직접/STANDARD+ 위임) · 모델은 임원(Fable)이 매 dispatch 필수 지정(정의 파일 기본값 없음, Fable 할당 자유 허용) · 하이브리드 플레인(일상=내장, 밤샘급=ORCA)**. 글로벌 PLAYBOOK(헤딩 `ORCA Lean Multi-Agent Playbook`, §1.3 거버넌스·§7.2 조건부 Enter 앵커)과 lee-mode skill을 정합 재작성해 skill-PLAYBOOK 불일치(헤딩 검증 실패로 /lee-mode 중단되는 상태) 해소. 구버전은 `.bak-20260725` 백업. Codex 불가 시 폴백(사용자 게이트+감사부채 기록) 신설.
- 프로젝트 오버레이(§2 부서→에이전트 매핑, 1단 위임 정합)·CLAUDE.md(agents SoT 1줄) 최소 수정. visual-qa 정의에 픽셀 지오메트리 필수화(오늘 CSS 사고 교훈) 반영.

## 2026-07-25 · 기준정보 그리드 "값 누락" 실체 규명 — CSS 1속성 레이아웃 붕괴 수정

- 사용자 관리 그리드의 "조/직급/권한/재직 값 누락·타행 값 표시" 원인 확정: `views/master/style.py`의 `.ms-cell-select { position: relative }`(07-21 `90a3450` 도입)가 AG Grid의 absolute 셀 배치를 깨서 부서 이후 컬럼이 39~118px 아래 행으로 밀려 그려진 것. **데이터·정렬 로직은 정상, DOM에는 값이 전부 존재** → innerText 기반 DOM QA·계약 테스트가 전부 green으로 통과해 수차례 수정 시도가 표적을 빗나감(07-23 QA 실패와 동일 실패 모드). 해당 속성 제거로 수정(▾ 표식은 `::after` absolute가 positioned인 `.ag-cell`에 그대로 앵커됨), `streamlit-aggrid<1.3` 상한 추가(`>=` float로 구버전 검증이 무효화되는 재발 방지).
- 검증: 신규 서버(8510, sample)에서 3화면 전행 셀 bounding-box 정렬 ALL-ALIGNED + 값=CSV 일치, ▾ 유지 확인, users_new·org·work_types_new 계약 테스트 all-green, compileall·diff-check OK. **교훈: 그리드 QA는 innerText가 아니라 셀 y좌표=행 y좌표(픽셀 지오메트리) 검사 필수. 장수 streamlit 프로세스는 모듈 캐시로 수정 미반영 가능 — 수정 후 서버 재시작·서빙 코드 확인 필수**(8502/8503 구코드 서빙 실증).

## 2026-07-24 · 아침 "다 돌리자" 마무리 — 미결 3건 해소 + feature push

- 아침 "다 돌리자" 처리 완료(Codex 교차검증 게이트): ①그룹모델 문서충돌 → **사용자 결정 "migration 004(organization_groups) 정본화"** → requirements§104·database.md·CLAUDE.md 불변계약 참조를 004 모델로 정합(문서만). ②P1-2: schedule_view MANAGER 잔존 조회조건 **fail-closed 재적용 + auth.logout q_* 삭제 + 부서 유효성 ALL센티널·미존재 차단 하드닝**(Codex 승인). ③dept_group_map 조직조회 오류 전파(int(NaN) 크래시 부수 해소, Codex 승인). 회귀 all-green(schedule 124·login 29·unified 195 등), feature push.
- §98(비활성 직원 과거근무): **무결성 계약(참조 유지)이며 데이터 계층이 이미 충족** — 조회화면 표시 변경은 별도 제품 판단이라 미변경(follow-up). .venv 깨진 참조는 이 머신에선 정상 확인(수정 안 함).
- 남은 follow-up(비차단): §98 조회화면 표시 여부 제품 결정 · database.md §7에 004 후속(005 group_id NOT NULL·003 컬럼 제거) 목록화 · 대시보드 비차단 P3.

## 2026-07-24 · 밤샘 lee-mode 마무리 — 대시보드·조회 스냅샷 계약수정 + 거버넌스 SoT

- 밤샘 lee-mode 운영을 Codex 교차검증 게이트로 마무리: 대시보드 재설계(MANAGER 부서범위 fail-closed·과거소속 월편성 스냅샷 우선·그룹 004 유지·P2 견고화, Codex 승인)와 `schedule_view` 월그리드(스냅샷 소속 우선 표시·필터 + repository 오류 전파로 빈 월 위장 제거·NA-safe, Codex 승인) 모두 반영. 회귀 all-green, feature push(Cloud=deploy 구조라 prod 미영향).
- 거버넌스: 위임·조직 룰을 lee-mode §1.3 단일 SoT로 통합(직급체계 4부장+Codex 거래처이사+운영기능·재귀 계층·순수위임+예외·모델 티어 haiku/sonnet/opus·Codex verify-not-veto·이의제기 의무·재개 안전), skill 항목7 조건부 Enter 정합.
- 미결(아침 사용자 결정): ①그룹모델 문서충돌 — `requirements.md`§104/`docs/database.md`의 003 파생 표현 vs 적용된 migration 004(organization_groups 1급 테이블, 앱 전체 사용): 004 정본화 권장 vs 롤백, 파생 불변계약 변경이라 사용자 결정 필요. ②P1-2: schedule_view MANAGER `q_schedule_view` 잔존 + logout 미삭제 권한누출(`auth.py`, HIGH_RISK). ③전체 sign-off. follow-up: 대시보드 P2(render-skip spy·미지역할·dept_group_map 이중조회)·비활성 직원 과거근무 미표시(§98)·`.venv` 깨진 Python313 참조 정리.

## 2026-07-23 · 밤샘 루프 — 대시보드 재설계 + 화면수정 통합 (feature 스테이징)

- 조직형 위임(임원→부장→과장)으로 병렬 진행: 대시보드 부장(당일 그룹별 주간/야간/휴무 버킷 보드·‹전일/익일›+date_input·`get_day_schedules` SELECT-only, `2e8c24e`)·화면 대비수정 3건(선택대비 2.89→5.76·조직버튼 잘림0·사용자 인라인 3.35→6.67)·근무형태 부장(측정 결과 게이트 충족으로 무변경 결정). 모두 feature에 순차 merge(`c7132a5`, 8커밋 ahead·**미push**). 통합 회귀 all-green(schedule 61·sidebar 42·org 67·users·work_types 81·login 22)·compileall OK.
- 워크스테이션 진단 확정: ORCA 네이티브 `worktree create`가 `runtime_unavailable`("Restart Orca") — 읽기(list)는 되나 생성 실패 = **Orca 앱 재시작(사용자 조치) 필요**. 해결안은 md·skill(lee-mode §4.6·§7.2·§3.1 조직형 위임, 프로젝트 PLAYBOOK, skill 파일)에 반영 완료, 실발동은 내장 isolation으로 폴백.
- 열린 확인: 대시보드 supabase 분기(private `_schedule_rows`) 미측정, sample 데이터 07-01~12만 존재(오늘=빈 상태 정상). 최종 확정·deploy 승격은 **아침 사용자 실브라우저 sign-off** 후. 사용량 5시간 창 절약 페이싱 중(opus 서브 아껴 씀).

## 2026-07-23 · 디자인 QA 실패 → 거버넌스·프로세스 정비

- 배포된 사용자·조직 관리 화면에서 명백한 시각 결함(행 선택 시 글씨=음영 대비 붕괴로 판독 불가, 조직 3열 액션바의 `새로고침` 버튼 잘림, 빈칸 과다)이 발견됨. 이 결함이 회귀 green + Codex 코드 점수 + DOM 구조 마커로 "5/5 DESIGN_GOOD"로 통과한 근본 원인 = **실렌더 시각 검증을 코드·DOM 구조 확인으로 대체하고 사용자 시각 승인 게이트를 생략**한 것.
- md 전수 감사(분석 서브에이전트 4 + Codex 교차검증 2회 합의)로 규명·정비(모두 미커밋): CLAUDE.md 권위·우선순위 계층 신설·안전경계 SoT를 AGENTS.md로·완료보고 통일 / DESIGN.md 조직 2패널→3시트 갱신·§8 시각 완료게이트(1366×768 필수+보조 매트릭스·대비율·scrollWidth 잘림·**사용자 실브라우저 최종 sign-off**) / design-contract 역사 산출물 강등 / requirements §6 시각·패널 용어 제거(독립 저장 계약 유지) / 메모리 교정(codex-gate=실렌더 증거 없는 시각 점수화 금지·local-artifact 강화·로그인 색인 모드별) / 글로벌 lee-mode §1.1a(Coordinator 똑똑한 위임)·§4.1b(조사 에이전트가 개발까지 전담).
- 보류: 목업 workflow 정합(글로벌·미커밋 PLAYBOOK 수정은 사용자 결정), 실제 디자인 버그 수정은 교정된 게이트(측정+사용자 시각 승인)로 별도 진행.

## 2026-07-23 · 기준정보 Codex 게이트 디자인 개선 (P1/P2/P3)

- 개발 게이트 규칙 확립: 디자인 변경은 Codex 디자인 검수로 4축(밀도·일관성·편집안전·정보구조) 전부 ≥4/5 且 P1=0 합의 후에만 구현. 점수는 Codex(sol high, 서브에이전트 Reviewer 터미널)가 채점.
- Codex 종합 검수 → P1(근무형태 코드 자연키 미잠금 = 편집안전 3/5) 수정: 코드 컬럼에 editable=_EDIT_NEW_ONLY(신규행만) + 저장행 읽기전용, org/users와 동일 계약 → 재검수 GOOD. 이어 P2(조직 액션바 keyed __bar·렌더순서 통일, 조직·사용자 요약칩 어휘·0건 처리 통일)·P3(근무형태 미리보기 40+ '외 N개' 안내, 사용자 캡션 업무용어화, 공통 미사용 .ms-chip.link 정리·grid 높이 상수 통합) 반영.
- 최종 Codex 재검수 DESIGN_GOOD — 밀도 4/5·일관성 5/5·편집안전 5/5·정보구조 5/5, P1 0. 회귀 all-green. 커밋 `42270d0`(P1)·`65aaf0d`(P2·P3) push.

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
