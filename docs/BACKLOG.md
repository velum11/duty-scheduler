# 미결 백로그

해결되지 않은 결정·후속 작업의 추적 파일입니다. `docs/WORKLOG.md`는 순수 이력이며 미결 추적은 이 파일이 정본입니다. 항목이 해결되면 여기서 제거하고 WORKLOG에 결과를 기록합니다.

## 결정 대기 (사용자)

- (현재 없음) — 사이드바 디자인 확정(sign-off) 게이트는 **2026-07-26 사용자 sign-off로 해소**. DESIGN.md §1(라이트 KPtech 클론 사이드바 구조)·§2(App Shell `--sb-*` 라이트 토큰 + 테마-ready 명문화) 반영 완료. 결과는 `docs/WORKLOG.md` 2026-07-26 "✅ 변곡점: 사이드바 확정 → DESIGN.md 반영 완료" 참조. (memory `sidebar-design-protected` 갱신은 별도.)

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
| 아차사고 데이터 저심각 잔여 — probe/문서 detail | 07-26 Codex 3라운드 후 잔여 중 ①종말상태 반복전이 차단, ②audit(`updated_by`) 전수 점검은 **07-27 해소**(`docs/WORKLOG.md` 2026-07-27 항목, `modules/db.py::update_near_miss_status` 수정 + 신규 계약 테스트). ③probe/문서 detail만 잔존 | 코드 |
| 아차사고 EVALUATED→CLOSED 종결 경로 부재 (Codex P3) | 07-27 상태전이 가드 변경(`251e572`)의 Codex 포커스 감사 **완료 — P1/P2 0(감사부채 해소)**: 허용표에 자기 전이 없어 정상 전이 유지·동일상태만 차단, 호출부 전수 `cur==target` 의존 없음, 인가/TOCTOU/영속화 회귀 없음. **잔여 P3(비차단)**: 평가관리 화면의 종결 버튼 제거 후 앱에 `EVALUATED→CLOSED` 호출 경로가 없어 보고서가 EVALUATED 에 고립됨(DB 계약은 CLOSED 진행을 여전히 규정). **아차사고 개선조치(CAPA) 실작동 구현 트랙에서 폐루프로 해소 예정** | 코드 |
| schedule_edit 필터/액션바/MATRIX 지연분 | 07-26 근무표 편성은 크롬(screen_frame)만 이관. 지연: ①필터 condition_panel 이관 — `condition_panel` 키 스킴(`{page_id}_{key}`)이 load-bearing 키 `se_y/se_m/se_d/se_t`(revert 로직 67-80이 이름 직접 참조)와 충돌 → `Field` 명시 key 오버라이드 kit 기능 선행 필요 ②상단 액션바 — `top_action_bar`(반환값 버튼)는 편집 AgGrid `cellValueChanged` 경합 클릭소실 재도입 위험 → on_click 플래그 유지, kit이 플래그형 액션 지원해야 이관 가능 ③MATRIX 어댑터 추출(workspace 편집 AgGrid→kit) | 코드 |
| kit SELECT 그리드 어댑터 추출 | 07-26 MASTER_DETAIL(near_miss_evaluate) 리스트가 아직 `views/master.render_master_grid`(편집 스택)를 읽기+행클릭 선택 용도로 사용 — `read_grid`에 클릭/선택 훅 신설해 kit SELECT 어댑터로 추출하고 죽은 `_sel` 열 제거(단일 그리드 백엔드 완성). 이관 시 의도적 defer | 코드 |
| 신뢰경계: service-role 직접 SQL 행위자 인가 우회 | 앱이 service-role 클라이언트라 DB 직접 SQL 은 앱계층 인가·감사귀속을 우회한다(near-miss 뿐 아닌 전 테이블 공통). 07-28 확정: 007 은 **데이터 무결성 6불변식**(①EVALUATED에서만 CLOSED ②확인된 활성 개선조치 있어야 CLOSED ③개선조치 report_id 불변 ④자기확인 금지 ⑤재개+개선조치 초기화 원자 ⑥종결↔자식변경 경합 차단)만 DB 하드게이트(trigger/CHECK/FOR UPDATE)로 보장한다. 행위자 인가는 과장도 축소도 없이: **DB(RPC/trigger)는 구조·상태 불변식과 전달된(지목된) 행위자의 is_active·능력을 검증**한다(reopen/close RPC 가 users 재조회로 확인). 다만 그 사번이 실제 인증 세션에서 왔는지의 **신원 인증은 앱 계층 신뢰경계**다(service-role 직접 SQL 은 임의 사번을 지목할 수 있음). 완전한 DB 신원 인증은 RLS + 인증 role 전환이 필요 → 별도 대형 과제 | 아키텍처 |
| 게이트: 006/007 live 적용·통합검증 | 006/007 DRAFT·미적용. 실제 Supabase 적용 + live PostgreSQL trigger/CHECK/FOR UPDATE 동시성·SECURITY DEFINER owner/public 권한·데드락 부재 검증은 **전용 테스트 프로젝트 + 명시 승인 게이트**. 현재 정적(SQL 계약)·sample 검증만 완료 | 게이트 |
| 게이트: CAPA upsert 동시편집 CAS(UNVERIFIED_RUNTIME 후속) | 개선조치 upsert 를 **무변경 필드 UPDATE payload 제외 + 전무변경 no-op**(리포지토리 UPDATE 미호출)으로 바꿔 값비교~UPDATE 사이의 phantom-rewrite TOCTOU 를 완화했다(#1, sample/live 동형). 그러나 이는 완화이지 방지가 아니다 — 진짜 동시편집(A/B 가 서로 다른 값으로 동시에 UPDATE)까지 완전 차단하려면 `updated_at` 기반 CAS(조건부 UPDATE `WHERE updated_at = 조회시각`)가 필요하며 **이번 범위 밖**. CAS 도입과 **실제 Supabase 동시성 회귀 검증**(현재는 mock/sample 만)은 007 live 적용·통합검증 단계의 UNVERIFIED_RUNTIME 후속(전용 테스트 프로젝트 + 명시 승인 게이트) | 게이트 |
| defer: status_events 이력 테이블 | 이번 미채택. 다회 보완요청 전체 이력 등 상태전이 감사 이력은 현재 범위 완료 후 후속 과제(현재는 마지막 보완요청 3필드만 report 행에 보존) | 코드 |
| defer: DESIGN.md §0.1 매니페스트 정합 | near_miss_my·near_miss_improvement 행 추가, evaluate 행에서 종결 제거·검토착수/보완요청 추가 필요. DESIGN.md 에 사용자 미커밋 거버넌스 변경이 있어 이번 미접촉(§0.9 강제 테스트 미구현이라 현재 통과). 거버넌스 문서 커밋 시 함께 정합 | 문서 |
| 확정: 아차사고 조회범위 = 전사 공개 | 전 사용자가 신고자 이름·상세 포함 전체 아차사고 조회(기존 결정 유지). `near_miss_view.py` 현행 동작이 이미 이 계약. requirements.md 정식 명문화는 거버넌스 문서 정리 시 반영 | 문서 |
| KP-standard 퇴직행 오버레이 육안 확인 | 07-26 schedule_view 이관에서 `read_grid` 행-오버레이(row_rules) 첫 실사용. 메커니즘 4중 검증(whitebox 테스트·Codex in-memory probe·Fable ag-grid 디컴파일·색 규칙과 동일 cellClassRules 경로)됐으나, 현재 supabase 테스트 DB에 근무기록 보유 퇴직자가 0명이라 **렌더 픽셀 미확인**. 다음 실데이터 시(또는 비프로덕션에 퇴직+근무 시드) 육안 확인 | 게이트 |
| ACCEPTED: 개선조치 화면 역할표시 vs facade 권위 (세션 role) | 개선조치 화면의 역할 variant(큐 범위·버튼 판정)는 세션 `user` dict(role·안전담당)로 표시하고, 인가 집행은 facade/route 가 `_near_miss_actor` 권위로 재조회한다. 세션 중 역할이 바뀌면 화면 표시와 데이터층 판정이 잠깐 어긋날 수 있으나(재로그인으로 UI 갱신), **facade 가 최종 차단하므로 권한상승은 없다**. 이는 앱 전역 패턴(모든 화면이 세션 role 로 UI 표시, facade/route 가 권위 집행)과 일치하며 CAPA 고유 결함이 아니다 → 수정 없이 ACCEPTED. 후속(선택): 화면도 권위 판정 캐시를 공유하도록 통일 가능(이번 범위 밖) | 아키텍처 |
| KNOWN: 개선조치 nav 게이트의 오류-미배정 병합 | `has_near_miss_improvement_access` 는 매 렌더 nav/route boolean 게이트라 배너를 띄울 수 없다. actor 권위 조회(`_near_miss_actor`)의 일시 데이터소스 오류를 False(접근불가)로 접어 앱 전체 크래시를 막는다(P2). 트레이드오프: 장애 동안 담당자 메뉴가 잠깐 사라짐(장애 해소 시 복귀, 기능 손실 없음). 개선조치 화면에 도달한 평가자에겐 개별 조회의 load_failed 배너가 여전히 오류를 표면화하므로 "오류 은폐 금지" 원칙과 정합. nav boolean 게이트 특성상 오류≈미배정 병합은 불가피 | 코드 |
| KP-standard 구조 통합(진행 중) | 07-26 DESIGN.md §0 재작성(화면×역할 매니페스트·중립 구조 키트·영역 순서·MASTER_DETAIL 신규·실렌더 region 검증) 확정, Codex+Sonnet GO-WITH-CHANGES. **진행: near_miss_view(조회)·schedule_view(월간) 이관 완료(sign-off).** 구현 P1: ①중립 키트 `views/common/erp/`를 `views/master`(lifecycle)와 분리 ②AgGrid 단일 렌더러 + `READ/SELECT/EDIT/MATRIX` capability 분리(READ에 action열·paste JS·unsafe_jscode 금지) ③`workspace.py` 중복 grid는 UI 렌더러만 분리(scope·snapshot·dirty 로직 보존) ④`test_screen_scaffold`를 AppTest 역할별 실렌더 region 순서 검증으로 전환(분기 맹점) ⑤조직 3저장범위·FORM_ENTRY form 제약 계약 보존 ⑥`AppTest.dataframe` 검사는 뷰모델 검사로 전환(삭제 금지). 순서: 매니페스트/키트 → near_miss_view(파일럿) → schedule_view → near_miss_submit → evaluate → dashboard/stats → schedule_edit → master 3종(조직 마지막) → 사이드바 정리 → 전역 sign-off | 코드 |

## 후보 (미채택 — 필요 시 재검토)

- 문서 정합 자동 점검 스크립트(`test_docs_consistency.py`): migration 목록 vs 문서 표 일치·참조 경로 실존 검사 (2026-07-25 인터뷰에서 미채택)
- `.orca/artifacts/` INDEX·archive 정책 (동일)
- 글로벌 PLAYBOOK·skill 참조 버전(날짜·해시) 오버레이 기록 (동일)
- 테스트 명령 중복(CLAUDE·README) 참조화 (안전경계만 정리하기로 결정)
