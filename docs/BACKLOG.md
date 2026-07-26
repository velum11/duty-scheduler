# 미결 백로그

해결되지 않은 결정·후속 작업의 추적 파일입니다. `docs/WORKLOG.md`는 순수 이력이며 미결 추적은 이 파일이 정본입니다. 항목이 해결되면 여기서 제거하고 WORKLOG에 결과를 기록합니다.

## 결정 대기 (사용자)

| 항목 | 내용 | 출처 |
|---|---|---|

## 작업 대기

| 항목 | 내용 | 유형 |
|---|---|---|
| 대시보드 P3 | 비차단 개선 잔여분 | 코드 |
| 사용자 실브라우저 sign-off | 3화면 크롬 표준화(`14d5963`)·근무형태 배지 대비 보수(`cc5f6e4`)·퇴직자 과거근무 표시(§98 구현) — 8502에서 확인 대기 | 게이트 |
| 고아 빈 폴더 1개 | `.claude/worktrees/agent-a7f86db30e9513843` — 내용 없는 빈 폴더인데 타 프로세스 핸들 잠김으로 삭제 실패(07-25 정리 때 유일 잔존). 재부팅 후 또는 탐색기에서 수동 삭제 | 정리 |
| worktree 물리 잔재 2개 | ORCA worktree 폐기 완료(git 등록·브랜치 3개 삭제)했으나 `worktype-improve`·`worktype-improve-2` 디렉터리가 프로세스 잠김으로 물리 삭제 실패 — 재부팅 후 또는 잠근 프로세스 종료 후 폴더 수동 삭제(`.claude/worktrees/agent-a7f8...` 빈 폴더와 동일 처리) | 정리 |
| §0 규약 AST 집행 강건화 | 07-25 재감사 P3: `test_screen_scaffold.py`가 크롬 호출을 렌더 경로로 증명하지 않고(모듈 내 임의 위치 수집), `login`을 암묵 제외(my_schedule는 명시 allowlist), 화면 발견이 `views/`에 고정. false-negative 위주라 비차단이나 강건화 여지 | 코드 |
| QA 셸 read-only 내재 한계 명문화 | 07-25 재감사(Codex P2→P3 재분류): `visual-qa`·`contract-qa`는 테스트·probe 실행에 셸이 필요해 소스 편집이 도구가 아닌 문구로만 차단(recon은 셸 없음=하드). "내재적 한계"로 정의 문서에 명문화 | 문서 |
| 에이전트 tool id 검증 | 07-25 재감사 P3: 정의 파일 `tools:`의 `PowerShell`/`Skill`가 하네스 tool registry에 실제 등록되는지 확인(미등록이면 no-op, 셸은 `Bash`로 라이딩) | 확인 |
| 아차사고 데이터 저심각 잔여 | 07-26 Codex 3라운드 후 잔여(치명 안전은 닫힘): ①종말상태 반복전이 미차단(`REJECTED→REJECTED` 사유 덮어씀·`CLOSED→CLOSED` 무효) ②상태전이 경로 audit 필드(`updated_by`) 주입 여지(current_user 서버세션이라 실위험 낮음) ③probe/문서 detail. Phase B 화면 구현 중/후 빠른 후속 | 코드 |
| 아차사고 평가 죽은 종결 버튼(제품 결정) | 07-26 near_miss_evaluate: `종결` 버튼이 **항상 비활성**(코드상 증명) — `CLOSED`는 `EVALUATED`에서만 허용인데 평가 큐는 `SUBMITTED/IN_REVIEW`만 표시. 구조 마이그레이션에서 as-is 보존함. 제품 결정 필요: (a)유지 (b)제거(종결은 평가 후 뷰 소관) (c)큐 스코프에 EVALUATED 추가. 사용자 판단 | 결정 대기 |
| schedule_edit 필터/액션바/MATRIX 지연분 | 07-26 근무표 편성은 크롬(screen_frame)만 이관. 지연: ①필터 condition_panel 이관 — `condition_panel` 키 스킴(`{page_id}_{key}`)이 load-bearing 키 `se_y/se_m/se_d/se_t`(revert 로직 67-80이 이름 직접 참조)와 충돌 → `Field` 명시 key 오버라이드 kit 기능 선행 필요 ②상단 액션바 — `top_action_bar`(반환값 버튼)는 편집 AgGrid `cellValueChanged` 경합 클릭소실 재도입 위험 → on_click 플래그 유지, kit이 플래그형 액션 지원해야 이관 가능 ③MATRIX 어댑터 추출(workspace 편집 AgGrid→kit) | 코드 |
| kit SELECT 그리드 어댑터 추출 | 07-26 MASTER_DETAIL(near_miss_evaluate) 리스트가 아직 `views/master.render_master_grid`(편집 스택)를 읽기+행클릭 선택 용도로 사용 — `read_grid`에 클릭/선택 훅 신설해 kit SELECT 어댑터로 추출하고 죽은 `_sel` 열 제거(단일 그리드 백엔드 완성). 이관 시 의도적 defer | 코드 |
| KP-standard 퇴직행 오버레이 육안 확인 | 07-26 schedule_view 이관에서 `read_grid` 행-오버레이(row_rules) 첫 실사용. 메커니즘 4중 검증(whitebox 테스트·Codex in-memory probe·Fable ag-grid 디컴파일·색 규칙과 동일 cellClassRules 경로)됐으나, 현재 supabase 테스트 DB에 근무기록 보유 퇴직자가 0명이라 **렌더 픽셀 미확인**. 다음 실데이터 시(또는 비프로덕션에 퇴직+근무 시드) 육안 확인 | 게이트 |
| KP-standard 구조 통합(진행 중) | 07-26 DESIGN.md §0 재작성(화면×역할 매니페스트·중립 구조 키트·영역 순서·MASTER_DETAIL 신규·실렌더 region 검증) 확정, Codex+Sonnet GO-WITH-CHANGES. **진행: near_miss_view(조회)·schedule_view(월간) 이관 완료(sign-off).** 구현 P1: ①중립 키트 `views/common/erp/`를 `views/master`(lifecycle)와 분리 ②AgGrid 단일 렌더러 + `READ/SELECT/EDIT/MATRIX` capability 분리(READ에 action열·paste JS·unsafe_jscode 금지) ③`workspace.py` 중복 grid는 UI 렌더러만 분리(scope·snapshot·dirty 로직 보존) ④`test_screen_scaffold`를 AppTest 역할별 실렌더 region 순서 검증으로 전환(분기 맹점) ⑤조직 3저장범위·FORM_ENTRY form 제약 계약 보존 ⑥`AppTest.dataframe` 검사는 뷰모델 검사로 전환(삭제 금지). 순서: 매니페스트/키트 → near_miss_view(파일럿) → schedule_view → near_miss_submit → evaluate → dashboard/stats → schedule_edit → master 3종(조직 마지막) → 사이드바 정리 → 전역 sign-off | 코드 |

## 후보 (미채택 — 필요 시 재검토)

- 문서 정합 자동 점검 스크립트(`test_docs_consistency.py`): migration 목록 vs 문서 표 일치·참조 경로 실존 검사 (2026-07-25 인터뷰에서 미채택)
- `.orca/artifacts/` INDEX·archive 정책 (동일)
- 글로벌 PLAYBOOK·skill 참조 버전(날짜·해시) 오버레이 기록 (동일)
- 테스트 명령 중복(CLAUDE·README) 참조화 (안전경계만 정리하기로 결정)
