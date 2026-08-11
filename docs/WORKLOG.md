# 최근 작업 인계

이 파일은 다음 작업자가 현재 상태를 빠르게 확인하기 위한 짧은 기록입니다. 미결 추적은 `docs/BACKLOG.md`가 정본입니다.

## 2026-08-11 · [인계] 대시보드 SPEC 재구성 + 헤더 회귀 해결 + 근무표 3화면 개선(병렬) — 일괄 커밋·푸시

**대시보드 재구성(사용자 지시서 `DASHBOARD_SPEC.md` 이행):** 도달 경로 — 조직 현황 블록을 ①대분류 박스/컬럼 시안 2개(기각) ②부서별 집계 숫자(기각) ③부서별 근무자 **이름** 나열로 이터레이션한 끝에, 사용자가 8512 실데이터 미리보기를 보고 정식 지시서를 작성해 확정. §0 삭제 7개(담당별 명단 블록·이름 뱃지·멀티셀렉트·재적 표기·헤더 요약·미등록 행) → §1 골격 4블록(제목+헤더 날짜 스탬프 동기 / 세그먼트 날짜+부서 필터 칩 / KPI 스트립 / **부서(대분류)→조직(중분류) 2단 + 주간·야간·휴무 3열 피벗 명단**) → **§7 수용 기준 10/10 충족**(1366·1024 실측, 가로 오버플로 0). KPI와 명단이 같은 집계에서 파생돼 구조적으로 어긋날 수 없음. 스펙 이탈 1건 명시: 라벨 회색을 A-2 대비 하한 때문에 `#6b665d`로 상향(구조·크기는 스펙 그대로).

**헤더 회귀(편성 저장 불가) 해결:** 스탬프 슬롯 추가로 상단 52px 헤더 CSS의 **nth-child 순번이 어긋나** 스탬프가 빈 화면(편성 등)에서 브레드크럼·아이콘 8종이 시야 밖으로 밀림(DOM엔 존재 — 실측: 아이콘 래퍼가 전폭 1220px로 뻥튀기). 이 Streamlit 버전은 st-key 클래스를 직계 래퍼에 달지 않아 키 직접 지정도 불가 → **`:has(키)` 기반 선택자**로 교체(순번·빈 슬롯 무관). 실브라우저 검증: 대시보드·편성 양쪽 헤더 복구, 셀 편집→미저장 1건→**저장 아이콘 활성 전환** 확인(테스트 편집은 원상 복구, DB 무변경). 저장·삭제 아이콘 활성화는 설계상 1-rerun 지연.

**병렬 세션 트랙(같은 날, 별도 세션 산출 — 이 커밋에 동승):** ①근무표 3화면 개선 — 월간=해당 월 근무 보유자만 표시, 내 근무표=실제(약칭)/요약(4그룹) 전환, 편성=행 핸들 드래그 재정렬 + 저장 시 `users.display_order` 부서그룹 슬롯 재배정 영속 ②메일 알림 — 발송 수단 비즈메카 SMTP 확정(실검증)·지메일 한시 운영, `modules/mailer.py` + 업무요청·숙소예약 접수 훅 + `test_mailer`(26) ③프로토타입(숙소예약·업무요청서) 지속 개선. 상세·잔여는 `docs/BACKLOG.md` "근무표 3화면 개선"·"이메일 알림 트랙" 행이 정본.

**전/후 비교 종결:** 이번 푸시로 개선 라운드(`86e2446`)까지 공개 — **"후" 확정**. 8504 기준본·`.claude/worktrees/before-d5f4d26` worktree는 용도 종료(정리 가능). Cloud 배포본은 secrets(새 Supabase 키) 갱신 전까지 401 가능성 유지.

**남은 결정:** 캘린더 시안 A/B(8503) · PVC 미매칭 6명 사번 · 008 적용 시점(125명 로그인 개방) · MANAGER·ADMIN 명단 · 근태 실제코드 재적재 방식(BACKLOG ⓐ).

## 2026-08-07(심야) · [인계] 8단계 마무리 — 개선 라운드 + 전/후 비교 포트 (사용자 부재 완주)

**전/후 비교(사용자 결정 대기 — 다음 주):** "전" = 커밋 `d5f4d26`(푸시됨) 고정 worktree(`.claude/worktrees/before-d5f4d26`) → **8504**(sample). "후" = 개선 라운드 커밋(로컬, **미푸시**) → **8501**(supabase)·**8502**(sample). "전" 선택 시 마지막 커밋 1개만 되돌리면 된다. 8503 = 숙소예약·업무요청 프로토타입.

**개선 라운드(ui-feature Owner + code-review GO-WITH-FIX 반영):** ① 월간 조 필터 옵션을 월 스냅샷 근무조 기반으로 재구성 + **조 매칭을 부서 분기 밖으로**(P1 — 전체 부서에서도 적용) ② 다운로드 버튼 content-fit(≤880px 라벨 접힘 해결) ③ 편성 조 열 헤더 툴팁 안내(빈 셀 placeholder 는 복사 오염 위험으로 폐기 — P2) ④ **상단 52px 헤더 아이콘(추가·새로고침·삭제·저장)을 기준정보 3화면에 실배선**(additive — 인페이지 버튼과 같은 page-scoped flag, DESIGN §A-5 문구 정합화) ⑤ 자율 발견 7건: 조건 패널 content-fit(580px select→150px), 조직 버튼 폭/높이 정상화(315px→128px·25→32px 히트영역), 칩 겹침, `(전체)`→`전체 부서/조`, 미저장 0건 중립색 등. 헤더 기본값 전부 fail-closed 대칭화(P3).

**실근태 보강:** 근태표 원본의 조(A조/B조/C조·A팀/B팀) 정보로 **편성 스냅샷 272건** 적재 — 실DB에서 월간 조 필터·조 표시가 실제로 동작(검증 완료). 6월 중복 등재는 조 있는 행 우선으로 dedup.

**남은 확인(다음 세션):** ①전/후 선택 → "후" 채택 시 push(Cloud 배포), "전" 채택 시 revert ②헤더 저장·삭제 아이콘의 클릭 실행 실브라우저 확인(활성/음영은 실측 완료, 클릭→저장 발화는 미실측) ③placeholder 제거로 빈 조 셀 안내가 툴팁·힌트줄뿐 — 부족하면 CSS 의사요소 방식 재도입 ④PVC 미매칭 6명 사번 ⑤캘린더 시안 A/B ⑥Cloud 배포본 secrets 갱신 여부.

## 2026-08-07(오후) · [인계] 조직·사용자·편성 개편 3종 + migration 009 적용 + 신규 화면 병렬 트랙

**사용자 결정(이번 세션):** ① A/B/C조를 기준정보(teams)에서 빼고 **근무편성표에서 직접 입력**(한 글자 `A` → `A조` 자동 보정). ② 조직 관리는 그룹·운영단위 시트를 폐지하고 **부서 단일 시트 + 대분류/중분류 자유 텍스트 2단**(그룹 시트를 대체). ③ 사용자 관리에 **입사일·퇴사일** 추가, 퇴사일 경과 시 **로그인 차단 + 명단 숨김**(기록 보존, 퇴사일 삭제 시 복귀). ④ migration 009 즉시 적용 승인(테스트 프로젝트).

**적용 상태:**
- migration `009_org_category_and_tenure.sql` — 테스트 프로젝트 **적용·검증 완료**. 대분류를 기존 그룹명으로 백필(9종), 오전 정제분에서 입사일 125명 채움. teams·organization_groups 는 **휴면 보존**(drop 없음 — 부서 저장이 기존 group_id 귀속·team 배정을 지우지 않도록 스토어 백필 방어 포함, `master_org._save_depts`).
- 근무조 축 이동: 편성 저장 `shift_group_code`(자유 텍스트 스냅샷) ← 화면 `조` 열. `validators.validate_assignment_records` 는 require_shift=False 에서 **마스터 대조를 하지 않음**(shift_groups 0행이라 기존 대조는 전면 차단이었음). 조회(workspace·my_schedule)는 근무조 우선 표시 + 레거시 team명 폴백.
- 퇴사 판정 `db.is_resigned` — 당일=재직, 해석 불가=재직(fail-open 의도적). `auth.login`·쿠키 검증 양쪽에서 차단하고 기존 세션 폐기. 고정 비밀번호 예외(ADMIN)보다 **앞**에 배치.
- 테스트: 전 스위트 **29/30 통과**. 유일 실패 `test_supabase_crud` 는 `--confirm-test-project` 게이트의 설계상 차단(회귀 아님). 구계약을 고정하던 5개 파일(test_master_org·org_new·unified·users_new·migration_002_audit·org_hierarchy_data)을 신계약으로 개정 — org_hierarchy_data 의 live 검증은 seed 건수 고정 대신 **구조 불변식**으로 전환.
- 문서: requirements.md(§3 로그인·§5 근무표·§6 사용자/조직 관리), database.md(§4 migration 표 006~009 현행화 + 009 이후 조직 모델), master_org/master_users docstring.

**병렬 트랙(신규 화면):** ① 숙소 예약(신청→승인→캘린더, 시안 A/B 전환 탑재) ② 업무요청서 — ui-feature 백그라운드 Owner 가 **신규 파일 15개만으로 완성**(기존 파일 0건 편집, 자체 테스트 89 + 화면 규약 118 통과). 산출·미결질문 10건·붙이기 체크리스트: `.orca/artifacts/new-screens/`. 사용자 직접 세션 브리핑: 같은 폴더 `USER-SESSION-BRIEF.md`. migration 은 **020번대 예약**(초안은 `schema-draft.md`, supabase/migrations 미투입).

**code-review(§6 Codex 대체 경로) 실행 완료 — P1 4건 발견·즉시 수정:** ① 사용자 저장 시 전원 team_id 소거(그리드가 숨김 컬럼 제거 — 저장 직전 스토어 백필로 교체) ② 편성 부서 변경 시 옛 팀코드 잔존으로 저장 영구 차단(부서 변경 행 팀 해제) ③ `_clean_date` 2자리 연도를 서기 00xx 로 저장 → 즉시 계정 잠금(4자리 연도만 허용) ④ workspace 조회에서 퇴사자 과거 근무 소실(기록 있는 월 표시 + 퇴직 라벨로 복원). 수정 후 전 스위트 재검증 30/31(유일 실패 = supabase_crud 게이트 차단). 잔여 P2/P3 는 BACKLOG "2026-08-07 code-review 잔여" 항목.

**포트 배치(세션 종료 시점):** 8501=본 앱 supabase 연동 · 8502=본 앱 sample(아차사고 시드 3건 신설 — `db._NEAR_MISS_SEED`) · 8503=신규 화면 미리보기. 전부 health 200.

**실근태 적재(2026-08-07 오후, 사용자 승인 4건 반영):** PET 근태표 Excel(9개월·21명)을 서브 정제 → `work_schedules` **5,095행 적재**(테스트 프로젝트). 기존 코드 접기 4종(주/야/OFF/연차) + **근무형태 신규 14종**(기호 그대로 — 특주·야+1·근휴·자녀결혼 등, `근태표 반입 기호` description). 미매칭 1명은 후보 사번 2023070302 로 사용자 확정. 등록순서는 최신 월 시트 기준 `users.display_order` 21명 채움 + **편성·월간 화면 정렬을 display_order 반영으로 전환**(`sort_users_for_display` 배선 — schedule_edit / workspace). 정제에서 잡은 핵심: 원본 날짜 시리얼 6개 시트가 1년 어긋나 있어(2025 캐시·#REF!) 시트명+요일축으로 일자 확정 — 시리얼을 믿었으면 6개월치가 2025년으로 들어갈 뻔함. 재실행 스크립트 `.orca/artifacts/beta-migration/load_roster.py`. 시드 도입으로 드러난 sample 아차사고 NaN 승격은 `get_near_miss_report` 경계 정규화로 해소(260 checks 통과).

**순차 지시 8단계(2026-08-07 저녁, 사용자 부재 위임 — "질문은 코덱스 대체 경로로"):**
- [1] 원본 파트 11개 부서 승격(대분류=담당·중분류=상위 팀, 소속 11명 재배치) + 조직관리 전폭 컬럼 설정 신설(3분할 시절 초협폭이 원인이던 너비 이상 해소).
- [2·3·5] ui-feature 배치: **전 화면 셀 복사 가능화**(`CELL_COPY_OPTIONS` 단일 원천 → 4개 그리드 백엔드, 헤드리스 크로미움에서 Ctrl+C 클립보드 실측·붙여넣기/행선택 계약 보존 확인) · 근무형태 색 미리보기 스트립 제거(셀 단위 스와치만, −118줄) · 월간 조회 돋보기 아이콘+다운로드 버튼 상단 이전. 근무형태 액션바는 실측 결과 사용자 관리와 이미 동일해 무변경(진짜 중복은 상단 52px 헤더 아이콘 미배선 — §8 개선 후보).
- [4] **담당 권한(capability)+복수 알림 이메일**: recon 우수사례 조사(OWASP/Django/Supabase/Discourse — Codex 대체 경로) → migration **010 적용**(user_capabilities M:N + user_emails(scope, lower(email) 유니크)) → 파사드·`has_capability`·사용자관리 "담당 권한·알림 이메일" 편집기 · 수신자 API `db.notification_recipients(cap)`(mailer 연동 지점 — mailer.py 는 병렬 세션 소유라 미배선) · 계약 테스트 12건 · requirements §2/database.md 반영. 담당 신설은 이후 `config.CAPABILITIES` 등록만으로 확장.
- [6] ADMIN 전산팀 배속 + 2026-08 근무 31일 생성(평일 주간 21/주말 OFF 10).
- 조회 아이콘 통일 마감: near_miss_view 조회에도 `:material/search:`.
- 전 스위트 **33/34**(유일 실패 = 원격 CRUD 승인 게이트, 설계상 정상).

**PVC 근태대장도 적재 완료(같은 방식 사용자 승인):** 8개월(2026-01~08)·15명·**3,323행** + 근무형태 신규 29종(기타 계열 신설 — 재단·코팅 등). **미매칭 6명분 165행은 제외**(기준정보 무등재 — 퇴사/전출 추정, `퇴사`·`야-3`·`특야-7` 기호도 그들 전용이라 미등록). 사번 확정 시 같은 스크립트 재실행으로 추가 적재 가능(upsert 멱등). 합계: work_schedules **8,418행** / work_types 49종 / display_order 36명.

**남은 위험·미결:**
- 008 여전히 미적용 — 로그인은 `ADMIN`/`ADMIN`만(8501). 125명 진입은 008 적용 후.
- **미커밋** — 수정 21파일 + 신규 16파일(프로토타입 15 + migration 009). 커밋은 사용자 승인 대기.
- 사용자 결정 대기: 캘린더 시안 A/B, 프로토타입 미결질문 10건, MANAGER·ADMIN 사번 명단, 008 적용 시점, Streamlit Cloud secrets 갱신 여부.
- 개편 3화면(조직·사용자·편성)의 실브라우저 육안 확인은 미실행 — AppTest 렌더 검증까지만. 조 필터 옵션 재구성 등 잔여는 BACKLOG.

## 2026-08-07 · [인계] 실조직·실직원 125명 적재 (test 프로젝트, 전면 초기화 후 재적재)

**Supabase 키 사고 선행:** `.streamlit/secrets.toml`의 `service_role_key`가 폐기된 상태여서 앱 전체가 401 `Unregistered API key`였다. 프로젝트(`icvizwmqdffwsifmnwuk` = `duty-scheduler-test`)는 정상. 사용자가 새 키로 교체해 해소. **Streamlit Cloud 배포본 Secrets도 같은 키면 별도 갱신 필요 — 미확인.**

**사용자 결정(이번 세션):** 4계층(담당–부–팀–파트) → 앱 3계층 접기는 **C안(파트 폐기)**. 처음엔 A안(파트=운영단위)을 골랐으나, **실DB에서 운영단위가 이미 A/B/C 교대조로 쓰이고 그 위에 work_schedules 1,147행이 얹혀 있는 것**을 확인해 재질의 후 C로 변경. 팀 위 계층 직속 인원은 `<조직명> 직속` 부서 신설로 수용. 권한은 전원 USER. 기존 데이터는 **전면 초기화 후 재적재**.

**적재 결과:** 그룹 9(담당/실 7 + 대표이사 1 + 시스템 ADMIN) / 부서 32(팀·TF 22 + 기술연구소 + 직속 8 + 시스템 ADMIN) / **운영단위 0** / 사용자 127(실직원 125 + ADMIN·admin). 원본 125명 전건 대사 일치, 성명 불일치 0, 참조 유실 0.

- **`group_code='ADMIN'`·`dept_code='ADMIN'`·`ADMIN` 계정은 삭제 대상에서 제외**했다. `views/master_org.py::_SYSTEM_CODES`가 화면 보호 대상으로 삼고 `config.FIXED_PASSWORD_ACCOUNTS`가 로그인 예외로 의존한다. 지우면 앱이 잠긴다. 보존 계정이 삭제 대상 부서·운영단위를 참조해 FK 409가 났고, **ADMIN 부서로 이동 + team_id 해제 후 삭제**하는 순서로 해결.
- **삭제된 것: work_schedules 1,147행 · near_miss_reports 5건 · 기존 조직 15행.** 삭제 전 전체 10개 테이블 1,194행을 `.orca/artifacts/beta-migration/backup/*.json`에 덤프(gitignore 대상, 커밋 금지). 복구가 필요하면 여기서.
- 재실행 스크립트 `.orca/artifacts/beta-migration/load_beta_data.py` (dry-run 기본, `--apply`로 쓰기). **회사 Supabase 계정 이전 시 그대로 재사용 가능** — 이번 적재는 test 프로젝트 대상이라 이전 후 재실행이 전제다.
- 이상항목 처리: `본점`(1000, 4자리)·`자산관리담당` 7자리 중복(`3400000`)은 제외하고 정본 `34000000` 채택. `공란`(2026030302)은 원본대로 적재.

**남은 위험·미결:**
- **운영단위가 0개다.** C안은 이 슬롯을 교대조 전용으로 비워두는 안이고, 원본 조직 데이터에 교대조 정보가 없어 만들지 않았다. **A/B/C 교대조는 화면에서 새로 등록해야 근무표 편성이 가능**하다. 기존 6개(PET·PVC생산부 A/B/C)는 소속 부서가 신체계에 없어 소멸.
- 008 미적용이라 `users.password_hash`·`login_sessions` 없음 → **로그인은 `ADMIN`/`ADMIN`만 가능**. 125명은 008 적용 전까지 진입 불가.
- 권한 전원 USER — MANAGER 지정 미정, ADMIN 대상 사번 명단 미수령.
- `hire_date`(입사일)는 **users 테이블에 컬럼이 없어 적재하지 못했다.** 필요하면 스키마 추가가 선행.
- 인원 0명 부서 5개(데코코팅팀·데코영업팀·PET생산2팀·공정기술팀·MES TF) — 원본 그대로이며 비활성 처리는 하지 않았다.

## 2026-08-05 · [인계] 베타 준비 보안 1단계 — 비밀번호 인증 + 서버측 세션(008 DRAFT) + 계정 소유권 방향 확정

**사용자 결정(이번 세션):**
- **비밀번호 인증 도입.** 초기 비번=사번, 최초 로그인 시 변경 강제. 그 위에 내가 제안해 승인된 완충 2건: 초기비번 **유효기간 7일**(사번은 비밀이 아니라 방치 계정 선점 위험 — 특히 ADMIN), ADMIN 계정 우선 로그인.
- **계정 소유권**: Supabase·Streamlit → **회사 계정**, GitHub → **개인 유지**. 근거 정리 = Supabase는 실직원 개인정보 보유(이전비용이 아니라 처리자 문제, 팩트데이터 넣기 전이 가장 쌈) > Streamlit은 **service_role 키가 Secrets에 있어** 계정 보유자가 DB 마스터키를 읽음 > GitHub은 쌓이는 데이터·과금 없어 이전 불필요. 단 **개인 private repo + 회사 Streamlit 계정 = 회사 GitHub 사용자를 collaborator로 초대 필요**(운영상 1단계 추가). 나중에 옮길 땐 Settings→Transfer ownership이 issue/PR/리다이렉트까지 보존.
- **ADMIN 계정 비번을 당분간 `ADMIN`으로 고정**(사번 하나만, 아래 참조).

**구현(커밋됨):** `e116d8b`(에이전트 opus-5 고정 + recon 훅 + 시안3개 정합화) → `1e71d9b`(비번 인증). 둘 다 push, `88b5b3e`(미push였던 것) 동반 반영.
- `supabase/migrations/008_password_auth.sql` **DRAFT·미적용** — users 비번 컬럼 6개 + `login_sessions`. **기존 행의 값을 한 줄도 쓰지 않음**(컬럼 추가·기본값뿐). 007 규약 준수(guarded DDL·스키마 assertion·RLS enable/policy 없음).
- `modules/passwords.py` 신설 — **표준 라이브러리 `hashlib.scrypt`**(n=2^14). bcrypt/argon2를 안 써서 **requirements 무변경 = Streamlit Cloud 빌드 표면 안 늘어남**. 저장형식 자기서술적(`scrypt$n$r$p$salt$hash`)이라 파라미터 올려도 기존 해시 검증됨.
- `login_sessions`는 **원문 토큰이 아니라 sha256만 저장**(덤프 유출돼도 세션 재생 불가). 기존 `.local_sessions.json`은 sample 모드 폴백으로만 유지 — Cloud 컨테이너 FS가 휘발성이라 재배포마다 전원 로그아웃되던 문제 해소.
- **자격증명은 USER_COLUMNS/`get_users` 계약에서 분리**(화면으로 흘러가면 안 됨). 전용 경로 + 캐시 우회.
- 강제변경 게이트는 **`app_shell`(네비게이션) 앞**에 배치 — 사이드바 그린 뒤 막으면 그게 우회로. **쿠키 자동로그인도 동일 게이트**(`_must_change_for`, 판정 실패 시 True로 접음).
- 미등록 사번과 오답 비번을 **같은 문구**로 응답(사용자 열거 방지) — 기존 "등록되지 않은 사번" 문구가 이 때문에 바뀜, `test_login_auth` 계약도 갱신.
- 비번 변경·ADMIN 초기화 시 해당 사용자 **세션 전체 폐기**. ADMIN 초기화 UI는 사용자관리 화면 하단 expander(그리드 저장경로와 분리).
- 연속 5회 실패 → 10분 잠금. `views/password_change.py` 신설(§0 화면표준 제외목록에 `login`과 같은 범주로 사유 명시 등재).

**⚠️ 배포본 현재 상태 — 로그인 차단.** push=`kptech-workops.streamlit.app` 자동 재배포인데 **008 미적용**이라 supabase 모드 로그인이 fail-closed로 전부 막힘("비밀번호 인증 스키마(008)가 아직 적용되지 않아…"). **의도한 안전방향 실패**이고 데이터 위험 없음. 순서가 뒤집힌 것(원칙: 008 적용 → 코드 push). 복구하려면 008 적용 필요하나, **앞서 정한 순서대로면 회사 Supabase 프로젝트에 001~008을 한 번에 적용하는 게 맞고 개인 테스트 프로젝트에 지금 적용하는 건 배포본을 잠시 살리는 것 외 실익 없음** — 사용자 판단 대기.

**ADMIN 고정 비밀번호 예외 (미커밋, 한시적):** `config.FIXED_PASSWORD_ACCOUNTS = {"ADMIN": "ADMIN"}` **단일 SoT**. 등재 계정은 고정값으로만 로그인·강제변경 면제·**비번 변경 거부**(바꿔도 고정값이 통해 잘못된 안심만 남음). **매칭은 정확 일치**(trim만, casefold 아님) — 실DB에 `ADMIN`(활성)/`admin`(비활성)이 공존해 casefold면 의도 밖 계정까지 걸림. 실측: `admin` 입력은 비활성 계정이 아니라 **활성 `ADMIN`으로 정규화**되는 기존 계약 동작(버그 아님). **이 예외는 008 스키마 게이트보다 앞에서 판정**한다 — 008 미적용에서도 지정 관리자가 들어오게 하는 게 목적이라 자격증명 컬럼을 아예 안 읽음. **대가: 이 계정에 한해 fail-closed 가드가 뚫림.** dict를 비우면 예외·가드 모두 원복(테스트로 고정).
- 실DB 실측 확인: `password_auth_ready=False`, `ADMIN/ADMIN` 성공(강제변경 없음), `ADMIN/wrong` 거부.
- **베타 오픈 전 반드시 이 dict를 비울 것.**

**검증:** `test_password_auth` 신규 **51 PASS**, `test_login_auth` 30, `test_screen_scaffold` 100, `test_master_unified` 199, `test_sidebar_ui` 103, `test_master_and_views`/`test_erp_select_grid`/`test_cache_invalidation` 등 focused 전부 통과. compileall·`git diff --check` 통과. **브라우저 클릭 확인은 미수행**(헤드리스 auth 경로 실측으로 대체).

**미해결·다음 할 일 (우선순위):**
1. **GitHub Private 전환** — repo가 **아직 PUBLIC**(`velum11/workops`). 자격증명 유출은 없음(과거 revision 전수 스캔 확인) but 조직구조·화면·업무규칙·이제 인증구조까지 공개. 사용자 계정 권한.
2. **회사 Supabase 조직 확보 요청** — 리드타임 있음. 확보 후 001~008 적용 → 그다음 팩트데이터.
3. **008 적용 위치 결정**(개인 테스트 프로젝트 임시 적용 vs 회사 프로젝트 대기) — 배포본 로그인 복구와 직결.
4. **ADMIN 고정 예외 제거**(베타 전 필수) + 이번 미커밋분(`config.py`·`auth.py`·`test_password_auth.py`) 커밋 승인.
5. `docs/database.md`·`BACKLOG.md`에 008 미반영 — 적용 승인 단계에서 동반 갱신.
6. 엑셀 마이그레이션 템플릿(`.orca/artifacts/beta-migration/workops_마이그레이션_템플릿.xlsx`, 7시트) 사용자 작성 대기 → 받으면 **읽기전용 검증 후 "추가 N/수정 M" 보고, 승인 전 DB 무쓰기**.
7. `passwords.needs_rehash()` **의도적 미배선** — 로그인 시 조용히 재해싱하면 `set_user_password`가 `must_change_password`까지 꺼서 강제변경이 샘. scrypt 파라미터 올릴 때 전용 경로로 붙일 것.
8. 이전 세션 이월: prospect-research/AGENTS.md 커밋, Q5(QA/reviewer 절대경로 쓰기 갭), junction 전환.

**환경 메모**: 로컬 `localhost:8501` **supabase 모드** 실행 중. **사용자 선호(2026-08-05 확정): 포트 열어달라는 요청은 sample이 아니라 supabase 연동 모드가 기본.** supabase로 못 띄울 사유가 있으면 임의 sample 폴백 금지, 사유 보고 후 판단 요청. 미커밋 보존물(의도적): `.orca/temp/`·`govern.txt`(웹 아티클)·`secgap.txt`(웹 아티클)·`.venv_deploysim/`.

## 2026-08-04 · [인계] 개명 마무리 + KPI 2줄 카드 + venv 재생성 + Streamlit Cloud 배포 + 모바일 사이드바 수정

- **duty-scheduler→workops 잔여 정리(tracked)**: SKILL 5종 description/본문·`.claude/launch.json`·openai.yaml 3종·`THIRD_PARTY_NOTICES.md`·`001_initial_schema.sql` 주석·test_*.py 실행주석의 프로젝트명 통일. **내부 식별자(`duty-*` 스킬명·`DUTY_*` env·`duty_token` 쿠키)와 기능코드(`duty_date` 등)는 의도적 유지.** 로컬 폴더는 `C:\dev\workops`로 개명 완료. 남은 옛 경로는 **역사물뿐**: `docs/WORKLOG.md`(이 파일 과거기록)·`.orca/temp/*.log`·`.orca/artifacts/**`(비규범, 보존).
- **KPI 지표 타일 3줄→2줄**: near-miss 타일의 영문 오버라인(TOTAL/DONE 등, 3번째 줄) 제거 — `views/common/erp/kit.py::metric_strip` + `near_miss_evaluate.py`/`near_miss_improvement.py` 로컬 `_metric_strip_html` + `.erp-metric-note` CSS/docstring 정합. 호출부 튜플 `(label,value,unit,note,accent)`은 유지(note만 미렌더=`_note`). near-miss 4화면 일관 적용.
- **venv 재생성**: `.venv`가 옛 `duty-scheduler` 경로를 내부(activate·pyvenv·.exe 래퍼)에 박고 있어, 정확한 `pip freeze`(81pkg, playwright 1.61 등 requirements.txt에 없는 것 포함) 스냅샷으로 **최종 경로 `.venv`에 직접 재생성**(rename 아님 — 경로 재오염 회피). 검증 후 백업(`.venv_old_ds`·`.venv_new`) 삭제. **`.venv_deploysim`은 미변경**(전용 requirements 부재 → 옛 경로 잔존, gitignore·부차적, 필요시 동일방식 재생성). freeze 스냅샷은 세션 scratchpad에만 있음.
- **settings.local.json(gitignore)**: `--project-dir` 경로 workops로 갱신 + 죽은 옛세션 temp 스크래치패드 allowlist 5건 제거(`/update-config` 경로). service key 등 비밀은 안전(`.streamlit/secrets.toml`·`.env`·`settings.local.json` 전부 gitignore 확인).
- **모바일 사이드바 수정(`modules/ui.py`)**: ADMIN/MANAGER "PC 전용" 사이드바 셸이 모바일 비반응형 — 236px가 본문 상시 덮고 네이티브 접기(X) 전역숨김이라 닫기 불가였음(USER 셸은 상단+하단탭이라 무관). 수정=비-USER `initial_sidebar_state` `"expanded"→"auto"`(좁은 화면 자동 접힘) + `_SHELL_CSS`에 `@media(max-width:768px)`로 네이티브 접기 복원. **데스크톱 동작 불변**. 검증: playwright 390px(초기·이동·닫기 covers=false, »열기/X닫기 OK)·1440px 펼침 유지·`test_sidebar_ui` **103 PASS**.
- **커밋/푸시(사용자 승인)**: `0518efa`(개명정리+KPI+에이전트도구 스냅샷, 40파일) → push, `03dcb6b`(모바일 사이드바 fix, ui.py 단독) → push. 둘 다 `origin/redesign/claude-design-p1` 반영. 커밋엔 비밀·venv·`.orca/temp`·govern/secgap 미포함(선택 스테이징).
- **Streamlit Cloud 배포**: `kptech-workops.streamlit.app` (share.streamlit.io 웹UI — **CLI/API 배포 없음**, 웹 대시보드 전용, Codex 확인). **배포 브랜치=`redesign/claude-design-p1` → 이 브랜치 push 시 자동 재배포**(그래서 `03dcb6b`도 모바일 반영됨, 사용자 인지 후 선택). 앱은 **비공개(Streamlit 로그인 필요)** — URL 알아도 아무나 접근 불가. Secrets는 앱 **Settings→Secrets**에 TOML로 입력(로컬 `secrets.toml` 내용). **⚠️ supabase 모드로 배포 시 실데이터(사번·성명) → 반드시 Settings→Sharing 뷰어 제한**(개인정보). 배포 당시 data_mode 최종값은 사용자 입력이라 미확인(sample 권장했음).

**세션 종료 시점 열려있는 상태**: 로컬 `localhost:8501` Streamlit(supabase 모드) 백그라운드 실행 중 — 정리 권장. 미커밋 보존물(의도적): `.orca/temp/`·`govern.txt`·`secgap.txt`·`.venv_deploysim/`(gitignore 아님, 커밋에서 선택 제외)·gitignore 로컬(`.venv`·`secrets.toml`·`settings.local.json`).

## 2026-08-04 · [인계] 코디네이터 설계 확정 + 전 프로젝트 MD 감사 + opus 5 고정 + /lee-mode 바인딩

**agent-config 정본: 커밋 완료 + GitHub 푸시 완료** → `velum11/agent-config`(private, master). 이제 글로벌 lee-mode 룰이 버전관리·원격 백업됨. 라이브(`~/.claude`·`~/.orca/lee-mode`)와 내용 동기화 상태(junction은 아직 미적용 — 추후 글로벌 변경 시 수동 동기화 필요, `scripts/apply-junctions.cmd` 사용자 실행 대기).

**이 세션 반영 내역(agent-config 커밋됨/푸시됨):**
- **코디네이터 플레인 라우터(Codex#2 = c)**: lee-coordinator 본문에 `플레인 판정→확정→선택 플레인 스킬만 호출` 결정론 규칙. 기본 내장 Agent, Orca는 §5.2 조건일 때만, orchestration=조율/orca-cli=터미널·worktree·handoff. preload 금지. QD 가드: "never substitute"는 Orca 선택 후에만(내장 Agent는 정상 기본) — PLAYBOOK §5.1 + 코디네이터 양쪽.
- **Codex#1 감사 = "조건부 적절"** 반영: Q2(sonnet 강등 모호) → §3에 Opus 승격 트리거 4개 구체화. 드리프트 → lee-coordinator maxTurns:300·ux-architect 프로젝트 조건부 명시.
- **opus 티어 → `claude-opus-5` 고정**: bare `opus` 별칭이 4.8로 해석되는 문제. ui-feature·data-contract·integrator·code-review(+workops ux-architect) frontmatter model 명시. PLAYBOOK §1.2/§3도 갱신. sonnet·fable은 사용자 설정 유지.
- **`/lee-mode` → lee-coordinator 에이전트+Fable 바인딩(B→A)**: 명령 frontmatter에 `agent: lee-coordinator` + `model: fable` 추가. 이제 어느 프로젝트든 `/lee-mode`가 Fable 코디네이터로 실행(effort high=전역 settings 상속). **미검증**: `agent:` 필드가 세션 인라인 전환인지 fork인지 실측 안 함 — 다음에 `/lee-mode` 실제 호출로 (a)모델 Fable 여부 (b)감독 연속성 확인 필요. fork면 `model: fable`만 남기고 `agent:` 제거가 폴백.
- **디자인 변경 = 시안 3개 먼저→선택→1개 구현**(이전 세션 도입분 유지). 예외: 문구·토큰·정확지정.

**전 프로젝트 MD/스킬 감사(recon 4명 병렬 + Codex 메타검수 "신뢰도 높음"):**
- **R1/R2 (workops 스킬 정합화, 미커밋)**: duty-erp-ui·duty-ux SKILL/EVALS의 "handoff"→"design brief", 단일 목업 서술→시안 3개로 수정. `.claude/skills/duty-erp-ui/{SKILL.md,evals/EVALS.md}`·`duty-ux/SKILL.md`.
- **D1 (recon 관찰용 셸, 커밋됨 글로벌 / 미커밋 workops)**: Codex "recon Bash 전무=실제 능력 저해" → recon에 Bash + `recon-readonly.sh` PreToolUse hook(git read·버전 조회만 통과, 쓰기·설치·마이그레이션·업로드 차단, self-test 검증). 글로벌+workops 양쪽 hook 배치.
- **D2 (prospect-research/AGENTS.md, 미커밋)**: Codex "prospect만 ORCA 실사용이라 실이슈" → 최소 안전 어댑터 신설(정본 포인터 + 바이패스 모델 의존 승인게이트). raw-material·partner-vetting은 독립운영이라 무방(강제 생성 안 함).
- **R4 (agent-config, 커밋됨)**: README duty-scheduler→workops·특화 8종, defect schema role enum 현행화. **llm-wiki 경로는 사용자 지시로 원상 유지**(위키 재배치 별건). 위키(wikis/*) 전부 무접촉.
- 오탐 필터: agent-config에 WorkOps 0건(정상), wikis의 lee-mode 미준수/handoff(별개 도메인). F4(hook 집행) = integrator hook이 `git commit --dry-run` 차단하는 것 라이브 실측으로 확인 — 단 Codex 권고대로 회귀조건(런타임 버전 2.1.218·bypass 부모·subagent spawn·exit code 2 + read-only 대조군) 명시 필요, 범용 보장으로 확대 금지.

**과다제약 가설(사용자: 미검증) → Codex 판정**: 전체 과다제약 아님. recon만 국소 과다제약(D1로 해소). frontend-design 금지·code-review 노이즈 금지는 정당. read-only 산문 반복은 과다"서술"(D3 압축은 선택). 원칙: "비가역·외부 위험이나 관측된 오탐을 줄이는 최소 제약만 유지, 안전 이득 없이 증거수집 막는 제약은 푼다."

**미해결·다음 세션 할 일 (우선순위):**
1. **workops 대규모 미커밋 커밋+푸시 승인** — blueprint v2 전체 + WorkOps 개명 + R1/R2 + D1(recon) + opus-5 pin + 스킬 정합화가 전부 미커밋. push=Streamlit 배포이므로 사용자 명시 승인 필요. (`git status`로 범위 확인)
2. **prospect-research/AGENTS.md 커밋** (그 repo, 미커밋).
3. **`/lee-mode` agent 바인딩 실측** (fork vs 인라인 — 위 참조).
4. **Q5 (P1, 미해결)**: QA/reviewer의 절대경로 본 checkout 쓰기 갭 — Codex 권고 OS 파일시스템 샌드박스(전역 blast radius라 사용자 결정 대기). Q4(P2) 시안 격리 집행도 동반.
5. junction 전환(`agent-config\scripts\apply-junctions.cmd` 사용자 실행), IME 리포트 제출(`agent-config/docs/orca-hangul-ime-regression-20260803.md`), D3 산문압축/D4 eval backfill(낮음).

**환경 메모**: 한글 IME 잘림 = 오늘 Orca 업데이트 회귀(Claude 7/29 무변경). 긴 한글은 붙여넣기 권장. Codex 실행은 반드시 `codex exec ... < /dev/null`(stdin EOF, 안 그러면 hang). settings.json model=claude-opus-5·effortLevel=high·env depth=1.

## 2026-08-03 · [Codex 합의] blueprint v2 방향 감사 + 코디네이터 설계 (재부팅 후 재실행 완료)

재부팅 전 hang(원인: `codex exec`가 stdin EOF 대기 → `< /dev/null`로 해소, 검증됨)됐던 Codex 2건을 재실행해 판정 수신. 결과는 `agent-config` repo에 반영·커밋(`777de6b`).

**Codex#1 — blueprint v2 방향 = "조건부 적절"**
- Q1 Codex 비가역 전담 = **PASS**(code-review 일상/Codex 2단 분리로 공백 없음)
- Q2 sonnet 강등 = **CONCERN(P2)** → 반영: PLAYBOOK §3에 Opus 승격 트리거 4개 구체화(인증·권한·데이터·보안 증거 판독/상충 증거·교차 추론/표면 로그로 원인 불명/1회 오판). 강등 품질은 여전히 미실증(2~3건 관찰 권장).
- Q3 code-review 상시화 = **PASS**(클래스 한정+FP 필터로 중복/인플레이션 없음)
- Q4 시안 경쟁 = **CONCERN(P2)**: ui-feature의 "본 checkout 비공유"가 선언적 통제뿐(Edit/Write 보유·격리·훅 없음). **미해결 — 사용자 결정 대기.**
- Q5 = **BLOCKER(P1)**: QA/reviewer가 worktree 있어도 절대경로로 본 checkout 쓰기 가능(실측된 갭). Codex 권고=OS 파일시스템 샌드박스(본 checkout canonical read-only, worktree/tmp만 writable, junction/symlink 탈출 차단). **미해결 — 전역 blast radius라 사용자 결정 대기.**
- 드리프트 지적 → 반영: lee-coordinator에 `maxTurns` 추가(300), 글로벌 allowlist의 `ux-architect`는 프로젝트 조건부임을 본문에 명시.

**Codex#2 — lee-mode↔orchestration 겹침/코디네이터 설계 = "(c) 소규모 재설계"**
- 반영: lee-coordinator 본문에 결정론적 **플레인 라우터**(① 플레인 판정[기본=내장 Agent, §5.2 조건 충족 시만 Orca] → ② 확정 → ③ 선택 플레인의 스킬만 호출: Orca에서 orchestration=조율상태 / orca-cli=터미널·worktree·handoff). **preload 금지**(선택이 스킬을 결정, preload가 아님).
- QD 반영: "never substitute" 금지는 **Orca 플레인 선택 후에만** 적용, §5.1 내장 Agent는 substitution 아님 — PLAYBOOK §5.1 + 코디네이터 본문 양쪽에 가드.
- QC 반영: 스킬 when-to-use 트리거 — visual-qa(pixel-qa)·integrator(safe-integration) 본문에 추가, recon은 기존 본문("technical-research=증거판정 / agent-reach=채널")으로 충족. 과설계 경계(명령 복제·전수 결정표 금지) 준수.

**미해결(사용자 결정 필요)**: Q5 P1(파일시스템 격리 강제 수단) + Q4 P2(시안 경쟁/ui-feature 쓰기 격리). 둘 다 OS 샌드박스/훅 정책이라 전역 영향 → 승인 전 미적용. 이 갭이 닫히기 전까지 read-only 경계는 "역할 문구+worktree git 격리"까지만 강제됨(bypass 워커의 절대경로 쓰기는 여전히 가능).

## 2026-08-03 · [인계] 조직 개편(blueprint v2) 집행 + WorkOps 개명 — 재부팅 중단점

- **개편 집행 완료(전부 실측 검증, 미커밋)**: ①모델 티어링(recon·visual-qa·contract-qa=sonnet, 호출 시 opus 승격) ②`code-review` 신설(read-only+worktree, 실패클래스 병렬+Coordinator FP필터 — spawn·격리 실측 OK) ③Codex 재정의(비가역 구간 한정: schema/RLS/migration·인증권한·데이터손실·운영쓰기, DESIGN_DECISION+FINAL_INTEGRATED 2단; 일상 diff는 code-review로) ④목업 시안 경쟁(조건부) ⑤전원 maxTurns ⑥integrator/data-contract PreToolUse 차단 hook(**integrator hook이 `git commit --dry-run`까지 차단하는 것 실측**) ⑦QA `isolation: worktree`(HEAD checkout — 미커밋 변경 비가시, CHECKOUT_MISMATCH 규칙 명문화) ⑧depth=1 env. **선행 실측**: `permissionMode: default`는 bypass 부모 아래 프롬프트 복원 못 함(3회 대조실험) → isolation 경로 채택 근거.
- **공용 정본화**: `C:\dev\agent-config` repo에 글로벌 자산 수용·커밋(`4b6a877`·`28720b3`·`ee1c3bd`). 라이브(`~/.claude`·`~/.orca/lee-mode`)와 내용 동기화됨. **junction 전환 미수행** — classifier 차단으로 `agent-config\scripts\apply-junctions.cmd` 사용자 직접 실행 대기(실행 전까지 글로벌 변경 시 양쪽 동기화 필요).
- **스킬 정비(2 Owner 병렬)**: eval 6건 신설(erp-ui 2·visual-critique 1·test-selection 2·data-contract 1), 날짜 인라인 7건 제거+History 절, **`paths:` frontmatter는 미지원 판정**(두 Owner 독립 수렴: 공식 레퍼런스 미문서화·실사용 전례 0 — 세션 문서 §3.3 권고 정정). "handoff"→"설계 브리프(design brief)" 개명(C4), full handoff 판별 체크리스트(§5.2)·worktree comment 체크포인트(§8) 추가.
- **WorkOps 개명**: APP_NAME="WorkOps"·README·app.py docstring·`test_sidebar_ui.py` 명칭 계약 갱신(**ALL PASSED 103**)·에이전트 MD 8종·overlay 제목. **GitHub `velum11/workops` 개명 완료 + 로컬 remote 갱신·ls-remote 검증**. 내부 식별자(`DUTY_*` env·`duty-*` 스킬·쿠키)는 의도적 유지. **로컬 폴더 개명 미완**: 좀비 grep(구 세션 잔존)이 폴더 lock — 재부팅이 해소하므로 재부팅 후 `Rename-Item C:\dev\duty-scheduler workops` → 잔여 경로 참조 정리 순.
- **Codex 설계 자문(개편 방향 적정성, DESIGN_DECISION·read-only) — 판정 미수신**: 실행 중 재부팅으로 중단됨. **재실행 필요**(질문 5: Codex 축소의 검증체계 영향/sonnet 강등 위험/code-review 중복 원칙 충돌/시안 경쟁 안전성/잔여 갭 최우선). 판정 수신 후 합의 내용을 이 WORKLOG에 기록하기로 사용자와 약속됨.
- 기타: 8501 sample 서버는 폴더 개명 위해 정지함(직전 인계의 "8501 서빙 중"은 무효). Orca에서 구 프로젝트 등록 제거됨(개명 후 재등록 필요). llm-wiki 관련 지시는 사용자가 취소(해당 repo 무접촉). **이 저장소 미커밋 변경(개편+개명 전체) 커밋은 사용자 승인 대기.** 알려진 잔여 갭: bypass 워커의 절대경로 본체 쓰기(hooks 없는 QA류), sonnet 품질 미실측(2~3건 관찰 권장).

## 2026-08-03 · [인계] 플레이북 개편 대기 — 평가·수정 3라운드 완료 저장

- **화면별 3축 평가 완료**(Codex STATIC + visual-qa 실렌더, 양측 종합 7.7/10 수렴) → Codex 상의로 수정 선별 → 3라운드 반영 완료: H1 공용 그리드 14.5px(`506ffc5`)·H2 CAUSE 라벨(`4de2936`)·M6 조직 부분성공 reconcile(`ffaccd6`)·U1~U8(사이드바 상단 여백·제출 버튼→체크리스트 하단(사용자 지시)·조회/월간 진입 자동조회 seed·셀렉트 content-fit·평가 사진 뷰어·무음폴백 3곳 표면화·대시보드 KPI 제목 직후·제출취소 제거 — `ef29b3a`·`282c969`·`3be628a`). Medium 2건은 앞서 `a85ff8c`. 전 커밋 테스트 그린·push 완료.
- **대기 상태**: 사용자가 글로벌·프로젝트 PLAYBOOK 및 서브에이전트 역할 개편 중(작업 트리의 `.claude/agents/*` 7종 수정+`code-review.md` 신설·skills 3종·`.orca/PLAYBOOK.md`·CLAUDE.md(8종 체계)·hooks·settings — 전부 사용자 소유 미커밋, 미접촉 보존). **다음 지시까지 신규 dispatch 중단.**
- 재개 시: 새 PLAYBOOK 재독 → 역할 매핑 갱신(code-review 내장 리뷰 축 포함) → 잔여 결정(실브라우저 sign-off·`feature/supabase-crud` 병합·Codex DEFER 목록은 BACKLOG 참조). 8501=supabase 최종 상태 서빙 중.

## 2026-07-31 · 아차사고 사진 첨부 + A4 PDF 출력 기능 신설 (병렬 2워커 + Codex 통합감사)

- **사진 첨부**(사용자 요구: 폰 촬영/선택·PC 업로드·3장·압축): data-contract가 저장 계약 구현(`60e42eb` — modules/photo_storage.py 검증(확장자+매직바이트·≤10MB)/압축(최대변 1600·JPEG ≤500KB)/경로 near-miss/{report_id}/{uuid} 주입불가 + db 파사드 upload/get_url(signed URL)/delete 소유자+SUBMITTED 게이트, 테스트 58), **사용자 승인으로 live 버킷 `near-miss-photos`(비공개) 생성 + guarded 스모크 왕복 성공**(보호 플래그 3종, 기존 데이터 미접촉). ui-feature가 UI 연결(`fa69497` — 등록 폼 스테이징-후-첨부(결정게이트 승인)·즉시 검증·썸네일/삭제·3장 차단, 조회/내아차사고 상세 서명URL 썸네일·소유자 편집, 1366/390 왕복 실측).
- **A4 PDF 출력**(`c94ef14`): fpdf2+동봉 OFL 한글 TTF로 조회 상세 보고서를 A4 세로 PDF 생성·다운로드(헤더 인쇄 아이콘 활성=상세 선택 시, 파일명=보고번호.pdf), 신규 테스트 12. 사진 이미지 임베드는 후속(현재 파일명 나열).
- 편성표 피드백 반영(`4eed752`·`d510008` — 헤더 아이콘 실작동·본문 단추 제거·클릭순환 제거(더블클릭 편집 복원)·부서/조 전체 기본·필터 라벨 겹침 수정) + 지표 타일 표준화·조회 필터 §1-E(`228cedc`·`f367093`). 편성표 입력 검증은 사용자 결정으로 현행 유지(저장 시점 검증).
- **Codex FINAL_INTEGRATED → NO-GO(P1 5) → 전건 수정 → NARROW_RECHECK 4 FIXED+1 PARTIAL → 잔여 표면화 완료**: 업로드 상한 3중 방어(config 10MB·위젯·size 사전검사+30MB 누적캡, `9e108ac`)·decompression bomb(40MP·디코더 제한·Warning 승격)·photo_paths CAS(updated_at 스냅샷·0행 stale·본문 payload 제외)·삭제 실패 storage_deleted 표면화(데이터 `df5f454`+화면 `cadabf3`)·public 버킷 fail-closed. P2 동반: 멱등 압축·readiness 리셋·{32-hex}.jpg 강제·Pillow/fpdf2 버전 핀·OFL 전문(`5c7d0f1`). 잔여 P2/P3(BACKLOG행): migration 배열 제약·signed URL TTL 단축 검토·라이브 어댑터 테스트·PDF 자원 상한.
- **사용자 추가요청 3건(`cadabf3`)**: 조회 필터 간소화+기간 기본 전체 / 분석 년월 선택+누적·당월 KPI 2그룹(B-1: UI단 계산) / 내 아차사고 상태·기간 + 개선조치 조치단계·담당자·기간 필터(B-2: 뷰단). 워커 push 이탈 1회(승인 범위 내 결과·시정 통지 완료).
- **최종 QA(visual-qa, sample 실브라우저)**: 종단 시나리오 1~6 PASS(등록 사진 스테이징~제출·수정 재제출·평가 확정·CAPA 2단계 종결 도달·조회 PDF %PDF 검증·분석 누적/당월)+헤더 아이콘 상태표 정합, 편성표 셀 편집은 자동화 측정 한계로 미검증(4단계 실측 기완료). 부족점 6건 기록(`final-qa/REPORT.md`): **Medium 2**(등록 체크리스트 비실시간·평가 확정등급 기본 S 자동선택 — 수정 여부 사용자 결정 대기), Low/관찰 4(평가 상세 사진 뷰어 부재·인쇄 1-rerun 지연·상세 메타 스타일 불일치·자동화 부하 시 응답 지연). 스크린샷 30장+검증 PDF 보존.

## 2026-07-30 · ✅ 변곡점: Claude Design 신판 명세 전면 구현 완료 — 9화면 구조 교체 + 셸 §4 (redesign/claude-design-p1)

- Claude Design이 1차 리스킨(색만 변경)을 반려하고 신판 명세(zip: 루트 `DESIGN.md` 전면 교체·`HANDOFF_PROMPT.md`·`아차사고 관리.dc.html` 10화면)를 제공 → **화면 우선·셸 마지막** 순서로 9화면 전부 §1 유형별 구조 교체 완료: 평가·개선조치(§1-A 큐 칩+전체폭 상세), 내 아차사고(§1-B 아코디언), 근무표 편성(§1-C 클릭=근무 순환·숫자키·sticky 4열·붙여넣기 UI 제거/Ctrl+V 유지), 등록(§1-D 3섹션+체크리스트), 기준정보 3종(§1-E 표형·조직은 세로 헤어라인 3열 드릴), 분석(§1-F 지표 6+분포 4블록) + 셸 §4(폴더 아이콘 제거·6px 마크·5px 점·66px 접힘 레일·실기능 아이콘만). 커밋 `85e846a`~`87e4b52` 14개, ORCA orchestration 단일 ui-feature Owner + decision_gate 2회(코디 판정)·Codex 문의 1회.
- **Codex 검수 2회 반영**(채택 GO-WITH-CHANGES + 미결 5건 판정): `#6b665d` 접근 회색 공식화(2.5:1 라벨 전수 치환)·편성표 14.5px(§8-6>목업 픽셀)·삭제용 체크박스 유지(명세 범위 축소)·st.button 동등 대응 허용·아이콘 최대 8슬롯 실기능만 — 신판 DESIGN.md **부속서 A**(정정 8건)로 명문화. 기능 계약 위반 0(상태전이·CAPA 권한·3독립 저장·소프트 삭제·readiness·nav guard 전부 보존, 전 단계 focused 테스트 그린).
- **(07-31 완결)** 잔여 4화면도 전환 완료: 아차사고 조회(§1-E 표+행클릭 상세, 73e3f1a)·내 근무표(isMySched 달력, 262f351)·월간 근무표(§1-C 읽기 변형, cf539fb)·대시보드(§1-F 변형, e1bd603) — **M/A 전 화면 신판 명세 적용 완료**. 상단바 아이콘은 사용자 지시로 재정정(부속서 A-5): 8종 상시 노출+미사용 음영(8f271bf).
- 잔여(비차단): 폰트 self-host(CDN 임시)·레일 배지 데이터원 없음(구조만)·월간 2줄 일자 헤더(READ no-jscode 계약상 단일 줄 적응)·조회 표 상태 pill(색코딩 셀 적응) — 별도 결정 사항. **최종 게이트: 사용자 실브라우저 sign-off**. 종전 B안(redesign/near-miss-ui)은 이 브랜치의 base로 흡수됨.

## 2026-07-30 · ✅ 변곡점: Claude Design 전면 채택 — 앱 전체 리스킨 결정 (B안 sign-off 대체)

- 사용자가 claude.ai/design 목업(9화면, `아차사고 관리.dc.html`)을 **앱 전체(기존+신규 화면) 시각 기준으로 채택**. 다크 웜 사이드바·오렌지 액센트 `#c2410c`·IBM Plex Sans KR/Mono·카드 금지·글자 상향(표 14.5~15px)이 골자. 이로써 어제 B안 sign-off 게이트는 대체·생략(브랜치 구조 자산은 보존), 07-26 라이트 사이드바 확정과 §0.6 밀도 잠금(32–34px)은 사용자 결정으로 폐기 예정.
- 충돌 분석(A6·B12·C3) + Codex 검수 **GO-WITH-CHANGES** + 사용자 결정 4건(목업 밀도 그대로 / 붙여넣기 Ctrl+V만 유지·버튼 제거 / 상단바 실기능 아이콘만 / redesign/near-miss-ui base 계속) 완료. 구현 계약은 `.orca/artifacts/claude-design-adopt/ADOPTION_SPEC.md`(가이드 원본·분석·Codex 리뷰 동봉). 불변 유지: 히트영역 ≥32px·읽는 텍스트 ≥4.5:1(저대비 3색 장식 강등)·근무형태 색/순환=기준정보 SoT·범위 액션 소유·AG Grid 백엔드·MASTER_DETAIL 아키타입.
- 진행: P1 셸·크롬 → P2 그리드·기준정보·근무표 → P3 아차사고+USER variant → P4 동작 변경(각 별도 승인). 각 페이즈 sign-off 후 DESIGN.md 개정(선반영 금지 — 07-26 전례). DESIGN.md·기존 화면은 P1 sign-off 전까지 현행 유지.

## 2026-07-30 · [인계] 세션 종료(Claude 업데이트) — 아차사고 시각 재구성 완료·사용자 sign-off 대기

**한 줄 상태**: 아차사고 6화면 시각 재구성(B안)이 **구현·검증까지 전부 완료·push됨**. 남은 것은 사용자 실브라우저 최종 sign-off와 병합·배포 결정뿐.

### 완료 (Orca orchestration 파이프라인 — 신설 UI/UX 체계 첫 실전)
- 흐름: R1/R2 시각 레퍼런스 조사(63 refs, 표면 단차 1.03–1.12 실측 규칙) → **D1 `ux-architect` handoff**(신규 색 0·형식 분리·메타 스트립·예외 큐, 전역 결정 2건 에스컬레이션) → M1/M1b **A/B live 목업**(8531) → **사용자 B안 승인** → F1' 6화면 확산 → V1 visual-qa **PASS**(§8 게이트 전부 통과·High 0) → T1 E2E **22/22회 PASS·앱 결함 0**(근태 12회+아차사고 폐루프 10회, 반려·보완·재조치 분기·4계정 역할 전환) → F2 셰브런 보정.
- B안 = 전역 토큰 완화: `--canvas #F5F3EF`(흰 표면 대비 1.108)·`--line #EBE8E1`(≈1.22)·`--content-bg` 동기 + **DESIGN §2 개정**(크림→near-white 웜뉴트럴, 2026-07-29 사용자 결정 명기). 시각 언어: lifecycle=pill / 등급=셰브런 마크 / 분류=평문(형식 분리), 상세 metadata_strip 통일, 분석 attention_strip(예외 큐), pill 테두리 저채도.
- 커밋(전부 push, `redesign/near-miss-ui`=`374ad9f`=origin 동기): `c94188f`(kit primitive 3종) `dfb28e4`(B 토큰+DESIGN §2) `f439aae`(6화면 확산) `cc007d4`(셰브런 제거) `374ad9f`(BACKLOG). 배포브랜치 `feature/supabase-crud` **미병합·미배포**.
- 산출물: `.orca/artifacts/near-miss-restyle/` — `refs/`+분석 2건·`design-handoff.md`·`mockup/`(A/B·final 스크린샷)·`qa/QA_REPORT.md`(측정 json 포함)·`e2e/E2E_REPORT.md`(회차표).

### 실행 환경 (종료 시점)
- **8501 = supabase 실데이터·최종 상태** 서빙 중(로그인 `ADMIN`). 재기동 명령: `DUTY_DATA_MODE=supabase PYTHONUTF8=1 .venv/Scripts/python.exe -m streamlit run app.py --server.port 8501 --server.headless true` — **재기동 전 기존 8501 리스너 전부 kill+`__pycache__` 제거**(07-29 stale 이중 리스너 사고 재발 방지).
- 8531(sample 시연)·QA/E2E 서버들은 종료해도 무방. Orca 워커 터미널 `nm-*`는 idle — 닫아도 됨.

### 재개 시 다음 단계
1. **사용자 실브라우저 sign-off**(8501, 6화면) — 이것이 완료 확정 게이트.
2. sign-off 후: push는 완료 상태이므로 **병합(`feature/supabase-crud`)·Cloud 배포 여부만 사용자 지시**로.
3. BACKLOG 잔여(비차단): master EDIT 그리드 40/44px 선재 편차·near-miss 시각 Low 3종·E2E 관찰 2종·pixel-qa 셀렉터 갱신(Streamlit 1.59 ComboBox).

### 이번 세션의 룰 변경(모두 적용·커밋됨 — 상세는 아래 변곡점들)
워커 권한 바이패스(글로벌 PLAYBOOK §5.2)·DLP 산출물 해제·UI/UX 7종 체계(ux-architect+스킬 3종)·DESIGN §0.6 밀도 잠금·§2 near-white 개정.

## 2026-07-29 · ✅ 변곡점: DLP 로컬 산출물 생성 금지 해제 — 산출물 정책 개정

사용자가 회사 DLP 로컬 쓰기 제한을 해제. `AGENTS.md` 안전경계의 "DLP 하드 경계" 절을 **로컬 산출물 정책**으로 교체(생성 허용·위치 규율 `.orca/artifacts/<작업>/`·temp·**비밀/개인정보/실데이터 덤프 포함 금지는 불변**·산출물 무권위). 파생 정합: CLAUDE.md 권위계층 1번(비밀·개인정보 보호로 재정의), 오버레이 §3, visual-qa(스크린샷 캡처·보관 허용), ux-architect(handoff 사본·설계 노트 artifacts 허용), duty-visual-critique(vision 스크린샷 전면 허용 — 인메모리 제약 삭제), duty-ux·duty-erp-ui(이미지 목업·산출 사본 허용), 메모리 local-artifact-prohibition(해제 기록). 글로벌 문서들의 "when forbidden" 조건문은 조건부라 무수정(프로젝트가 더 이상 금지하지 않으므로 자동 해제). 실행형 live mockup·DOM 수치 1차, commit/push·실DB 게이트, 사용자 sign-off는 불변.

## 2026-07-29 · ✅ 변곡점: UI/UX 담당 체계 신설 — ux-architect(7종째)·스킬 3종(MIT 이식)·룰 정합

아차사고 재설계 혹평의 원인분석("설계 앞단 밀도·사용성 소유자 부재") 후속으로, 5갈래 조사 + Codex 3회 검증(1차 설계·2차 v2·3차 룰문구, 지적 전건 반영)을 거쳐 확정·적용:

- **`ux-architect` 신설**(프로젝트 7종째, `.claude/agents/ux-architect.md`): UI_CENTRIC 구조 변경의 **구현 전 설계·UX 자가검토 advisor**. 산출=대화/task handoff 7항(파일 금지), 비구속 — `ui-feature`가 처음부터 끝까지 화면 Owner(mockup 승인 이하 §7 흐름 불변). 발동=영역순서·아키타입·분할·과업흐름·IA·키트·액션위계(포함이 제외에 우선).
- **스킬**: `duty-ux`(Nielsen10+Krug4·심각도 0–4·폼 휴리스틱, wondelai+mastepanoski MIT 이식)·`duty-visual-critique`(jezweb 7축·H/M/L·squint test·반장식 교차원칙, visual-qa 장착 — 정성 갭 해소)·`duty-erp-ui` Stage 0 설계 절(interface-design MIT 절차 이식, 값은 DESIGN.md SoT). 저작권 고지=`THIRD_PARTY_NOTICES.md`. 서드파티 직설치 배제(보안·Windows·이중 SoT 근거).
- **룰 정합(신규 규칙 우선)**: 글로벌 PLAYBOOK(§1.2 baseline 조항·§3 표·§7 앞단)·프로젝트 오버레이 §2(7종)·CLAUDE.md·DESIGN.md §0.9 설계 게이트+§8 역참조·lee-coordinator allowlist·lee-mode 커맨드·ui-feature 정의·메모리 3건. 척도 분리(UX 0–4 ≠ visual H/M/L), Codex=설계문서/코드/계약 검수·시각검수=visual-qa+사용자 sign-off.
- 잔여: 인메모리 vision bytes 무저장 보장은 도구 실검증 후 사용(불가 시 DOM-only 강등 — 스킬에 조항).

## 2026-07-28-29 · [인계 대기] 아차사고 CAPA 기능 완결(적용·live검증) + 6화면 UI 재설계

**한 줄 상태**: 아차사고(near-miss) CAPA 폐루프 **기능 구현·007 적용·live 검증까지 완료**(feature/near-miss-capa, push됨) + 아차사고 **6화면 UI/UX 전면 재설계 완료**(redesign/near-miss-ui, **미push**). 프리뷰 http://localhost:8501(supabase·실데이터 3건) 가동 중. **사용자 실브라우저 sign-off·push/병합/배포는 대기.**

### 브랜치 상태 (전부 배포브랜치 `feature/supabase-crud`=`251e572`에 미병합·미배포)
- **feature/near-miss-capa** (`deb1665`, **origin push됨**): P1-a 서버측 인증·인가 강제 → 007 CAPA 스키마/하드게이트 RPC·trigger → 개선조치 화면 기능화 → 행단위 권한 재설계(담당자/확인자/평가자/배정) → 각 단계 Codex 감사. 커밋 18개.
- **redesign/near-miss-ui** (`6b2148f`, **미push**, base=deb1665): 6화면 UI 재설계 6커밋. 공통 `select_grid` SELECT 어댑터(불변식 whitelist·자연키·밀도 param·편집자산 구조차단·allow_unsafe_jscode=False)+표시 primitive(status_badge/meta_col/field_block)+단위테스트 47. 6화면(등록 폼위계/평가·개선 select_grid+상세 워크플로 상단·부차 접기/my 44px/조회 KPI중복제거/분석 §0.3 KPI-primary·컴팩트테이블). **기능/DB/상태/권한 불변**(계약계층 diff 0). FINAL_INTEGRATED Codex GO(NEW-01 ink-3→ink-2 수정 완료). 전체 테스트 26/26 GREEN.
- **redesign/master-users** (`ed1a8f4`, push됨): 아이콘 밴드 히트영역 32px(별건).

### 007 live (Supabase test_project `icvizwmqdffwsifmnwuk`)
- **006·007 둘 다 적용됨**(007은 이 세션에 사용자가 SQL editor로 적용). live-ENGINE 검증 16 PASS(트리거/CHECK/RPC 실발화·자기확인·report_id 불변·CLOSED후 보호·reopen 원자·all-or-none). **기존 near_miss_reports 3건(id1 SUBMITTED·id2 EVALUATED(B)·id3 SUBMITTED) 세션 내내 불변**, near_miss_improvements 0. TEST 마커 데이터는 검증 후 전량 정리.

### 재개 시 다음 후보 (사용자 결정)
1. redesign/near-miss-ui **실브라우저 sign-off**(8501, 6화면 실데이터) → 이상 없으면 push / feature/near-miss-capa에 병합 여부.
2. push·배포브랜치 병합·Cloud 배포는 **전부 미실행 — 지시 대기**.
3. **미커밋 거버넌스 문서**(`.claude/agents/*`·`.orca/PLAYBOOK.md`·`CLAUDE.md`·`DESIGN.md`·`docs/requirements.md`+untracked `.claude/skills/`·`.mcp.json`)는 세션 시작 전부터 사용자 소유 미커밋 — 세션 내내 미접촉 보존. 처리 방침 미정.
4. 남은 위험(BACKLOG): view @1024 9열 내부스크롤(기존)·stats overdue_count try밖 호출(기존)·CAPA CAS 동시성(UNVERIFIED_RUNTIME)·DESIGN §0.1 매니페스트 SELECT+상세 정합(DESIGN off-limits라 defer).
- 상세 결정·계약은 `docs/BACKLOG.md` 정본, 메모리 `codex-review-lessons-20260728` 참조.

## 2026-07-27 · [재시작 대기] 상단바 통일 + 아차사고 계약수정 병렬 진행 중

**중단 이유**: 이 세션 전체(Coordinator+서브에이전트)가 실제로는 의도한 Fable/Opus가 아니라 **Sonnet으로 실행 중**이었음을 사용자가 화면 라벨로 확인(원인 불명 — 프로젝트 `.claude/agents/*.md`의 `model: opus` frontmatter가 하네스에서 적용되지 않음). 사용자가 Claude Code 재시작으로 해결 예정(설정 화면 확인 결과 Fable 5는 Max 플랜에 이미 포함돼 있어 usage credit 불필요, 단순 재시작이 안내된 해결책). **작업은 끊지 않고 로그만 남기고 재시작.**

**git 상태(이 로그 시점)**: 20개 파일 변경, 281 insertions(+)/262 deletions(-), 전부 워킹트리에만 존재(미커밋). 변경 파일: `.claude/agents/*.md`(6개, 이전 라운드), `.orca/PLAYBOOK.md`·`CLAUDE.md`·`DESIGN.md`·`docs/requirements.md`(이전 라운드 문서 정합), `modules/db.py`·`scripts/test_near_miss_data.py`·`views/near_miss_evaluate.py`(아래 A), `views/master/__init__.py`·`views/master/style.py`·`views/master_org.py`·`views/master_work_types.py`·`views/near_miss_improvement.py`·`views/near_miss_submit.py`·`scripts/test_master_work_types_new.py`(아래 B).

### A. 아차사고 데이터 계약 (data-contract Owner) — **완료, 테스트 그린, 미커밋**
사용자 승인 3건:
1. 평가관리(near_miss_evaluate) 화면의 항상 비활성이던 "종결" 버튼 제거 — `modules/db.py`는 손대지 않고(EVALUATED→CLOSED 전이 능력은 향후 개선조치 구현 시 재설계 대상으로 보존) UI만 정리. `EVALUATED`="평가완료" 표시 유지.
2. `modules/db.py::update_near_miss_status`에서 동일상태 재전이(REJECTED→REJECTED, CLOSED→CLOSED 등) 차단 — 1873행 부근 `cur_status != target and` 단축조건 제거. 호출부 전수 추적으로 기존 정상 전이 비영향 확인.
3. `updated_by` 등 audit 값 전수 점검 — 누락 없음 확인, 코드 변경 없음(신규 컬럼·migration 없음).
검증: `scripts/test_near_miss_data.py` 168 checks(신규 케이스 포함) + `scripts/test_near_miss_view.py` 59 checks 전부 통과, compileall/git diff --check 클린. 데이터 변경 없음(sample 모드 세션 스토어만 사용).
**감사부채**: 이 변경은 인가/상태전이 가드라 원래 Codex 감사 대상(HIGH_RISK)이나, 세션 재시작 시간압박으로 **Codex 감사 미실행**. 재개 시 최우선 처리하거나 `docs/BACKLOG.md`에 정식 등록할 것.

### B. 상단바 아이콘 밴드 일관성 (ui-feature Owner) — **완료(이 로그 작성 직후 알림 수신), 테스트·visual-qa 그린, 미커밋 → 커밋 완료 예정**
사용자 승인 5건(요약): ①버튼 모양=모서리 살짝 둥근 사각형(사용자가 지목한 "Image #4" 참고 스타일) ②간격=기존 1.4px보다 뚜렷하게 확대 ③아이콘 세트는 전 화면 통일 유지, 화면별로 기능 없는 아이콘은 음영 처리(화면별 커스터마이즈는 차기 과제) ④근무형태관리(텍스트 pill)·조직관리/아차사고등록/개선조치(static 장식)를 전부 icons 포맷으로 전환, **대시보드는 전환 작업 대상에서 제외**(이미 icons 포맷이라 공유 CSS 변경만 자동 상속) ⑤모드배지("● 샘플 데이터")를 전 화면 **우측**으로 통일.
- 코디네이터가 사전에 leftover streamlit 인스턴스(8501/8502/8503/8513/8533/8599/8600/8603 + 조사용 스크래치패드 8799)를 전부 정리함. 다른 워크트리 소유 8630은 보존.
- 이 로그 작성 시점 기준 새 streamlit 인스턴스가 **포트 8611**(PID 32404)로 떠 있는 것 확인됨 — Owner가 자체 검증용으로 띄운 것으로 추정.
- **재시작 시 이 백그라운드 Agent 실행이 이어지는지 끊기는지 불명확** — 재개 시 최우선으로 확인할 것.

### 재개 시 순서
1. `git status --short` / `git diff --stat`로 위 상태와 동일한지 대조(달라졌으면 B가 재시작 전에 더 진행됐다는 뜻).
2. 8611(또는 새로 뜬 포트) 생존 여부·B의 self-verify/visual-qa 완료 여부 확인. 안 끝났으면 같은 ui-feature Owner 컨텍스트로 이어받거나(가능하면) 새 턴에 위 5개 결정을 그대로 재전달해 마무리.
3. A·B 변경 파일 겹침 없음 재확인(설계상 없음 — A는 `modules/db.py`/`near_miss_evaluate.py`/테스트, B는 `master/*`·`near_miss_submit.py`·`near_miss_improvement.py`).
4. **사용자 명시 요청**: 평가(near_miss_evaluate)·등록(near_miss_submit)·개선조치(near_miss_improvement) 3화면을 실브라우저에서 회귀 검증.
5. A의 Codex 감사부채 처리(실행하거나 BACKLOG 등록).
6. 문제 없으면 commit → (사용자 기승인된) push.
7. 재시작한 세션이 실제로 Fable(Coordinator)/Opus(서브에이전트)로 뜨는지 화면 라벨로 먼저 확인한 뒤 위 순서를 이어갈 것 — MD 문구만으로 모델이 바뀌지 않는다는 점을 다시 확인.

관련: `docs/BACKLOG.md`(감사부채 등록 대상), 메모리 `near-miss-topbar-wip-paused`(이전 라운드, 이번 항목으로 대체)·`subagent-role-system`·`localhost-preview-real-data`.

## 2026-07-26 · KP-standard 구조 통합 — 중립 키트 + 콘텐츠 8화면 이관 (사이드바 진행 중)

- 사용자 지적("화면마다 조잡·불일치")을 **라이브 KPtech ERP(dews-ui) 실조사** + recon/visual-qa/Codex로 진단: 본문 4계보·그리드 3엔진·§0 골격 미강제가 근본원인. DESIGN.md §0을 **화면 구조 표준(KP-standard)** 으로 재작성(화면×역할 매니페스트·중립 키트·영역 순서·실렌더 검증 목표). Codex+Sonnet+Fable 계획 교차검증(GO-WITH-CHANGES).
- **중립 구조 키트 `views/common/erp/` 신설**(도메인 lifecycle과 분리): `screen_frame·top_action_bar·condition_panel`(col-N 우측 인라인 라벨)·`read_grid`(AgGrid READ 어댑터 + 색 dedup + 행 오버레이 `row_rules` + 겹침 가드)·`status_region·form_submit·master_detail_frame/detail_actions/detail_empty`·`Field`(widget_key 정확 세션키·placeholder). `MASTER_DETAIL` 6번째 아키타입 등록.
- **콘텐츠 8화면 전부 이관·커밋·푸시**(`d11c3d3`~`fea4606`): near_miss_view(파일럿·sign-off)·schedule_view(31일 색매트릭스+퇴직 오버레이)·near_miss_submit(FORM_ENTRY)·near_miss_evaluate(EDIT_GRID→MASTER_DETAIL 재분류)·near_miss_stats·dashboard(ADMIN/MANAGER 경로)·schedule_edit(크롬만·편집 machinery 보존)·master 사용자/근무형태/조직(우측 인라인 라벨).
- 검증(위험 비례): 화면별 내 diff 리뷰 + 계약 테스트 그린 + **고위험(스코프 누수·TOCTOU·쓰기)엔 Codex 능동 감사** + visual-qa 실렌더. **Fable 내부감사가 DESIGN.md §0 드리프트 3건 실제 적발**(§0.2/0.8/0.9 정직성 정정). lee-mode PLAYBOOK/skill에 "품질 최우선·검증 위험비례·Codex 적극·중복만 강등" 반영(메모리 [[push-back-on-excess]]).
- 팀: Coordinator Opus→**Fable 승격**(사용자 지정). 실행 부장 Sonnet(inventory/구현/QA), 리뷰 Codex(외부)·Fable 내부감사·Sonnet 하위모델. **one-hop 위임 유지**.
- **사이드바: 라이트 KPtech 클론으로 확정(2026-07-26 사용자 실브라우저 sign-off).** 다크 프로토타입(direction C: 검색+트리+즐겨찾기)이 대비 붕괴·계층 혼란으로 실패 → 사용자 지시로 라이트 재설계 → **확정**(236px·밝은 컬럼 `#F5F5F5`/트리 `#F2F4FA`·각진 radius 0·폴더 그룹 + chevron ▸/▾·홈 단독 항목·리프 가이드선·활성 파랑 `#1466C4` 글자, 배경 강조 없음). 테마-ready: 색은 `--sb-*` 토큰 한 블록으로만 관리(다크/시스템은 그 블록만 오버라이드 — 구조만 준비, 미출하).

### ✅ 변곡점: 사이드바 확정 → DESIGN.md 반영 완료 (2026-07-26 APPLIED) — 이전엔 sign-off 게이트로 **미적용 보류**였음

이 메모는 사이드바 sign-off 전까지 미리 적용을 금지하고 알아보기 위해 보류하던 것이며(확정 디자인을 규약화해 유지하려는 목적), **2026-07-26 사용자 sign-off로 아래 반영을 실제 적용 완료**했다.

- **[APPLIED] DESIGN.md §1 (ADMIN/MANAGER)**: 사이드바 설명을 확정본(라이트 KPtech 클론)으로 교체 — 네이비/밝은 컬럼 분할·검색·폴더 그룹(폴더 아이콘 + chevron ▸/▾, 활성 경로 굵게)·홈 단독 항목·리프(가이드선 + 더 깊은 들여쓰기).
- **[APPLIED] DESIGN.md §2 (App Shell)**: 사이드바 토큰을 다크(`#1B1B1D`/`#C9C7C0`/골드 `#C9A26B`)에서 **출하된 라이트 `--sb-*` 토큰**(col-bg `#F5F5F5`·tree-bg `#F2F4FA`·text `#000000`·text-dim `#6E6E6E` 4.68:1·accent `#1466C4` 5.12:1 등)으로 교체 + **테마-ready 구조 명문화**(색은 `--sb-*` 블록으로만; 실 테마 스위치는 미출하·구조만 준비로 정직 표기).
- **[의도적 미적용] 상단 밴드 액션 도구 스타일**: 밴드 안 아이콘+라벨 버튼(크기·큰버튼 vs 아이콘)은 진행 중(별도 일관성 작업)이라 §2에서 "진행 중 — 확정 전"으로만 표기하고 스펙 미잠금.
- **memory `sidebar-design-protected`**: 확정 라이트 디자인 기록으로 갱신 대상(문서 반영과 별도 — 메모리 파일은 이 DOCS-ONLY 패스 범위 밖).

## 2026-07-25 · Phase 1 성능 — supabase 읽기 캐싱 + 로딩 스피너·잔상 클리어

- 증상(사용자): supabase 모드 전환 후 로컬 느림 + 화면 전환 시 이전 화면 잔상. recon 진단: supabase 읽기에 캐시 전무 → 매 rerun 네트워크 재조회(조직관리 첫 로드 8~10 왕복), nav가 `st.empty` 미사용이라 새 화면 느린 로드 동안 이전 DOM 잔류.
- 수정(위임): data-contract — `db.py` 읽기 13종 `st.cache_data(ttl=30, supabase 전용)` + 모든 write `finally` 무효화(부분저장 stale 방지), `supabase_repository.py` id↔코드 맵 4종 메모이즈. ui-feature — `app.py` dispatch를 `st.empty()`+공용 스피너("불러오는 중…")로 감싸 화면 전환 잔상 즉시 클리어.
- 검증: 계약 ALL GREEN(master_org 67·schedule 136·login 29·sidebar 42·scaffold 51). Codex 2회 감사 — 초기 P1(부분저장 시 무효화 누락) 지적 → `finally` 전환 수정 → 재검토 P1 Closed·신규결함 0·예외 전파 유지. 원격 쓰기·데이터 변경 없음.
- 미결: supabase 캐시/무효화는 코드리뷰+계약(테스트는 sample 경로)로 검증 — 라이브 fault-injection 스모크는 후속. 디자인 완성도 평가(전 항목 ≥8) 진행 중.

## 2026-07-25 · Codex+Opus 재감사(P2 반영분) — blocking 2건 정정·5시간 페이싱 조항 제거

- lee-mode 교차검증(독립 2계열: Opus `recon` + Codex read-only, 사실만 전달·선호결론 미주입). 1차 P2 5건 중 **worktree 승인·감사부채 흐름 종결 확인**. 재감사 신규 blocking 2건 정정(사용자 승인):
  - **① capability 누출**: `supabase_repository.py` `_ORG_NOT_READY_MESSAGE`가 사용자 문구에 "migration 004/파일명"을 노출 — 1차 "사용자 노출 5건 제거"가 놓친 repository 계층 경로. 문구 일반화, 번호는 코드 주석에만.
  - **② 안전경계 SoT 모순**: AGENTS.md "완결 단일 정본" 주장 vs `database.md §5`가 migration 안전 소유 + 승인 금지명령 중복. 결정=분할 유지+문구 정정 → AGENTS.md=상위 정본(승인 게이트), §5=실행 메커니즘, `database.md`의 승인 금지줄 참조화, CLAUDE.md 정합.
- 사용자 지시: **5시간 사용량 창 페이싱·자율 재개 조항 제거** — Coordinator가 실제로 못 하는 능력(사용량 관측·창 리셋 자율 재개)을 규범처럼 적었던 것. 글로벌 PLAYBOOK §9(→"시간·진행 페이싱")·skill step 9에서 삭제. 메모리 `no-capability-overclaim` 신설.
- 잔여 P3(비차단, BACKLOG): AST 렌더경로 미증명·`login` 암묵제외·`views/` 고정, QA 셸 내재 read-only 한계 명문화, `PowerShell`/`Skill` tool id 등록 확인, `.venv` 깨진 Python 3.13로 scaffold 테스트 독립 미실행(51 checks 자기보고). **커밋·push 없음.**

## 2026-07-25 · Codex 감사(P1 0/P2 5) 반영 — 안전경계 완결·승인 게이트·AST 집행·capability 일반화

- **P2-1**: AGENTS.md를 완결 단일 정본으로(DLP 하드경계 편입·"참조만" 명문화·`.local_sessions`/QA 데이터 보호 이관·merge commit/worktree 승인 포함). CLAUDE.md·오버레이는 규칙 재서술 제거, "왜"만 잔류. **P2-2**: 글로벌 PLAYBOOK §7.3 "worktree는 조건 불문 사용자 승인, commit 생성 merge도 승인 필수" + skill·integrator 2종 정합(승인 근거 없으면 실행 거부). **P2-3**: visual-qa Write 제거(probe는 heredoc→scratchpad만), contract-qa shell 실행 전용 경계, 12개 정의 Agent/Task 부재 재검사 통과. **P2-4**: 감사부채=BACKLOG 정본 등록·WORKLOG는 당시 이력·사후감사 후 이관 흐름으로 글로벌 §5 교체. **P2-5**(ui-feature Opus): test_screen_scaffold를 AST·route연결·재귀 스캔·실호출·EDIT_GRID 스택 검증으로 재설계(우회 4경로 차단, 음성 검증 내장, 51 checks), scaffold·DESIGN §0 보장 수준 정직화.
- **capability 일반화**(data-contract): 사용자 노출 5건 "조직 스키마" 안정 표현(migration 번호 제거 — 정본: "조직 스키마가 준비되지 않아 조회만 가능합니다"), 주석 20곳 "(도입: migration 004)" 병기, DESIGN·requirements·data-contract 정의 정합, 조직 무관 화면 readiness 비요구 명문화. P3 반영: "mig 003" placeholder 정리·skill wakeup "필요할 때만" 통일.
- 검증: 10개 스위트 ALL GREEN(scaffold 51·common·unified 195·org 67·org_new 133·users_new·work_types 84·schedule 136·sidebar 42·login 29) + compileall + diff-check. **커밋·push 없음(지시)** — Codex 재감사 대기(BACKLOG).

## 2026-07-25 · §98 제품 결정·구현 + ORCA worktree 폐기 + push

- **§98 확정(사용자)**: 퇴직 직원 과거 근무는 기록 있는 월에 한해 조회 표시 + 퇴직 구분(라벨+음영 이중부호화, 색 단독 금지) — requirements §5 반영. 구현(ui-feature): `workspace.py::_build_month_grid` 필터를 "기록 있는 비활성 포함"으로 확장, 성명 `(퇴직)` 라벨 + 메타 셀 음영(ms-row-inactive 동일 토큰), MANAGER fail-closed·스냅샷 우선 계약 불변. `test_schedule_contracts` 신규 12체크 포함 136 all-green.
- **ORCA worktree 폐기 실행**(integrator, 승인 게이트 후): brill·worktype-improve·worktype-improve-2 — git 등록 해제·브랜치 3개 `-d` 삭제 완전, 단 물리 디렉터리 2건은 프로세스 잠김으로 잔존(BACKLOG — 재부팅 후 수동 삭제). worktype-improve-2는 삭제 전 포팅(`cc5f6e4`) diff 일치를 에이전트가 독립 재검증. 미푸시 10커밋 push(`ff601c5..165c170`).

## 2026-07-25 · worktype-improve-2 잔재 회수 — 근무형태 배지 WCAG 대비 수정 포팅 (sign-off 대기)

- recon 분석으로 ORCA worktree 3개 판정: brill·worktype-improve=병합된 클린 스냅샷(폐기 권고), **worktype-improve-2=미반영 완결 작업 발견**(근무형태 미리보기 배지 저대비 틴트 2.18~4.09:1 → solid+`_text_on` 자동 텍스트색 4.85~7.95:1, DESIGN §2 계약 위반 보수). ui-feature가 본 브랜치로 포팅(SCREEN_ARCHETYPE 등 후속 변경 보존), 신규 대비 계약 테스트 포함 work_types 84 all-green.
- 부수 수정: unified의 "검정 저장버튼 색 금지" 검사가 `_text_on`의 정당한 `#000000` 리터럴에 오탐 → 검사 의도(버튼 스타일 금지)를 보존하며 `_text_on` 블록만 제외하도록 정밀화(#1B1B1D 전역 금지 유지). unified 195 all-green. 화면 수 비강제도 명문화(사용자 지시 — DESIGN §0·테스트 (a)절 존재 화면만 검증으로 완화).

## 2026-07-25 · 화면 규약 Phase B — ADMIN/MANAGER 3화면 크롬 표준화 (사용자 sign-off 대기)

- 대시보드·근무표 편성·월간 근무표의 손제작 헤더를 기준정보 표준 크롬(브레드크럼→제목·설명→모드 배지)으로 통일 — `scaffold.page_chrome_for()`가 `modules/nav.py` 라벨을 단일 출처로 도출(ui-feature Opus 구현). `my_schedule`(USER 모바일)은 의도적 제외. 이제 ADMIN/MANAGER 6화면 크롬 동일.
- 검증: 계약 테스트 all-green(scaffold 34·schedule 124·sidebar 42·unified 195) + ui-feature 자가측정 + **visual-qa 독립 QA 전 항목 PASS**(6화면×2 viewport: 크롬 3요소 일치, 페이지 가로스크롤 0, 잘림 0, AG Grid 셀 정렬 델타 0.0px, 제목 대비 13.08:1). 특이: 월간 근무표는 AG Grid가 아닌 `st.dataframe`(기존 구현) — 내부 위젯 스크롤은 기존 동작. **최종 게이트: 사용자 실브라우저 sign-off 대기.**

## 2026-07-25 · 잔존 worktree 정리 완료 (integrator 검증→사용자 승인→실행)

- `.claude/worktrees/` 등록 worktree 5개 `git worktree remove` + 병합 완료 `worktree-agent-*` 브랜치 6개 `-d` 안전 삭제(전건 feature 병합·미커밋 0 검증 후 사용자 승인 게이트 거침). 구버전 규범 문서 스냅샷 오염원 제거. 잔존: 빈 고아 폴더 1개(핸들 잠김 — 수동 삭제 필요, BACKLOG).
- 부수 발견: ORCA workspace `worktype-improve-2`에 미커밋 잔재(근무형태 화면·테스트·WORKLOG) — 보존/폐기 판단 대기(BACKLOG). `brill`·`worktype-improve` worktree도 잔존(범위 밖, 미접촉).

## 2026-07-25 · agent-reach 스킬 불채택 — recon에 네이티브 웹조사 부여

- 사용자 설치 agent-reach 스킬을 분석 후 **불채택**(CLI·백엔드 미설치로 미동작, 개발 조사 능력은 내장 WebSearch/WebFetch로 대체 가능, 고유 가치는 소셜·영상 등 개발 범위 밖, r.jina.ai 프록시·서드파티 CLI 등 DLP 감점). 스킬은 휴면 보존(참조 에이전트 없음=토큰 소모 0). 대신 recon 특화판에 WebSearch·WebFetch 부여(read-only 유지 — Bash 미부여), ui-feature는 라이브러리 결함 의심 시 recon 조사 요청을 보고하도록 규정.

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
