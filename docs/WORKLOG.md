# 작업 로그 (WORKLOG)

터미널 Claude Code와 데스크탑 Cowork가 번갈아 작업할 때 맥락을 공유하기 위한 로그입니다.
작업(= 사용자가 화면에서 확인할 수 있는 결과 하나)을 마칠 때마다 아래 **로그** 섹션 **맨 위**에 한 항목씩 추가합니다. 최신 항목이 맨 위에 오는 역순입니다.

## 형식

```text
## YYYY-MM-DD HH:MM · [터미널|데스크탑] · 한 줄 제목
- 요청: 사용자 요청 요약 (1~2줄)
- 변경: 무엇을 어떻게 바꿨는지 (1~3줄)
- 파일: 수정/생성한 파일 목록
- 비고: 미완료·후속 작업·주의사항 (없으면 생략)
```

- `[터미널]`은 Claude Code(터미널), `[데스크탑]`은 Cowork(데스크탑) 작업을 뜻합니다.
- 시각은 Asia/Seoul(KST) 기준입니다.
- 사실 기록만 남기고, 커밋은 사용자 요청이 있을 때만 합니다.

---

## 로그

## 2026-07-15 18:05 · [터미널] · [무인작업 완료] Phase 5 브라우저 read-only 검증 + Phase 6 최종 감사
- Phase 5(브라우저 read-only, ADMIN 로그인, 저장/삭제 클릭 없음): 조 관리·근무형태 관리 신형 통일 그리드 렌더 확인. 근무형태 색상 열은 스와치(코드별 색)+HEX 표시, 셀 더블클릭 시 네이티브 컬러 피커가 현재 HEX(#1e6fd9)를 로드(Escape로 취소, 저장 안 함). [＋행추가]로 신규 −행+기본 색 스와치 생성 확인 후 −로 제거해 원상 복귀(Supabase 쓰기 없음).
- Phase 6 자체 감사: `git diff --check` 클린(LF/CRLF 경고만). schedule_edit.py·migrations·validators.py·db/ 무변경 확인. diff 추가라인의 유일한 Supabase 쓰기 표현은 delete_team/delete_work_type 함수 본문(기능 코드, 이번 세션 실행 안 함)과 on_click 상태 람다뿐. print는 테스트 스크립트에만. compileall OK.
- 테스트 전량 재확인: test_schedule_contracts 52 · test_schedule_save_units 15 · test_master_and_views 23 · test_master_forms 14 = 104 전부 통과. test_supabase_crud(라이브 쓰기 유발)는 규칙상 미실행.
- Supabase read-only 카운트 재검증(세션 전후 동일): users 21 · departments 5 · teams 6 · work_types 6 · work_schedules 2027-07 = 558 · 2026-07 = 0 · 총 558. 쓰기 전무 확인.
- 상태: 커밋/푸시 대기(사용자 지시 전까지 커밋 안 함). 미커밋 8개 수정 + 신규 scripts/test_master_and_views.py.

## 2026-07-15 17:50 · [터미널] · [무인작업 체크포인트] Phase 4·5 코드 완료 — 기준정보 통일 + 테스트
- Phase 4: `views/master_teams.py`·`views/master_work_types.py` 를 부서 관리와 동일한 `selectable_master_grid`(행 상태 계약, 상단 행추가/삭제/저장, 3상태 전체선택, 반응형 표, 신규 −행/기존 체크박스 분리)로 전면 통일. 조 관리: 부서 표시명↔dept_code 변환·부서내 조코드 중복 차단·소속 사용자 있는 조 미사용 처리/없으면 삭제. 근무형태: 색상 열을 **네이티브 컬러 피커(cellEditor)+스와치 렌더러**로 변경(저장 #RRGGBB 유지), 근무표 사용 중 코드 미사용 처리/없으면 삭제. db/repo에 delete_team·team_reference_counts·delete_work_type·work_type_reference_counts 추가(부서 패턴 미러링). validators.validate_assignment_records 는 이전 커밋에서 require_shift 옵션화됨(무관).
- Phase 5: 신규 `scripts/test_master_and_views.py`(23건: work_type_display·월간 필터/약칭/빈월/월분리·조/근무형태 validate·db 참조/삭제). `scripts/test_master_forms.py` 를 구형 폼 UI 테스트에서 신형 AG Grid 스모크(4화면 렌더 무예외)+신 시그니처 검증+라우팅(6페이지)으로 갱신(14건). 회귀: test_schedule_contracts 52, test_schedule_save_units 15 통과. 총 52+15+23+14 전부 통과. compile OK.
- 주의: test_master_forms 구버전은 4f9fe3b(부서 재설계, 승인됨)부터 이미 obsolete(제거된 폼 위젯 테스트)였고 이번 조 관리 재설계로 team 시그니처도 바뀜 → 신형에 맞게 재작성(실패 은폐 아님, UI 변경 반영).
- 미검증(진행 중): (a) 새 조/근무형태 화면 브라우저 read-only 렌더, (b) 월간 필터/개인 데이터 표시 — 단위/AppTest 로 결정적 검증했고 브라우저는 Supabase 쓰기 없는 read-only 렌더만 확인 예정. 실제 저장/삭제는 sample 모드/AppTest 로만(Supabase 쓰기 금지 준수).
- 다음: Phase 5 브라우저 read-only 렌더 → Phase 6 최종 감사(diff/write호출/스키마/schedule_edit 무변경/테이블 행수 재확인).

## 2026-07-15 17:34 · [터미널] · [무인작업 체크포인트] Phase 2·3 완료 — 월간/개인 약칭·색상 표시
- Phase 2(월간 근무표, views/workspace.py): `work_type_display()` 신설(코드→약칭 display_of, 약칭·코드 양쪽→색상 color_of, 약칭 비거나 모호하면 코드 표시). `_build_month_grid`가 셀을 약칭으로 표시, `_cell_style`는 color_of 기준, 집계표 열 머리글도 약칭, 범례를 `_label_legend_html`로 약칭 표시. 필터·연월 로직은 미변경.
- Phase 3(개인 근무표, views/my_schedule.py): `_calendar_html`이 셀을 약칭+색상으로 표시(work_type_display 재사용). 광범위 try/except 를 유지하되 repository 오류 메시지에 원인 노출(빈 월과 구분 명확화).
- 브라우저 검증: 월간 2027-07 재조회 → 셀이 주/야/OFF/연차(색상 포함)로 표시 확인(스크린샷). 개인: USER(2008082501) 로그인·전용 App Shell·달력 렌더 정상(2026-07 빈 달력, 오류 없음). **미완 검증**: (a) 월간 부서·조 필터, (b) 개인 2027-07 데이터 표시 — Streamlit 셀렉트박스/wheel picker 가 브라우저 자동화 커밋을 거부(제품 결함 아님). → Phase 5 에서 sample 모드 단위/AppTest 로 결정적 검증 예정.
- compile OK. schedule_edit.py 미변경. Supabase 쓰기 없음(read-only 조회만).
- 다음: Phase 4(master_teams·master_work_types 를 selectable_master_grid 로 통일, work_types 색상표) → Phase 5 테스트 → Phase 6 감사.

## 2026-07-15 17:11 · [터미널] · [무인작업 체크포인트] Phase 1 감사 완료 — 월간/개인 조회 원인 특정
- 기준: 커밋 5ecda99, 작업 트리 clean, sample 테스트 통과, compile OK. Supabase read-only 프로브 결과: work_schedules 558행(전부 2027-07)/users 21/dept 5/teams 6/work_types 6, schedule_assignments 없음.
- 연결도(read-only 코드 추적): 로그인 사번→auth.get_current_user→app.py dispatch→(schedule_view→workspace.schedule_screen / my_schedule.render)→db.get_month_schedules(emp_nos,y,m)→supabase_repository._user_maps(emp_no→user_id)+work_schedules 범위조회(work_date gte/lt)→SCHEDULE_COLUMNS(emp_no/duty_date/work_type_code/note)→표/달력. work_types는 code/short_label/color 보유.
- **핵심 진단: 저장·조회·연결은 정상. "안 보임"은 UI 계층 이슈**. repository 프로브에서 2027-07 전체 558행/18명, 개인(2008082501) 31행 정상 반환.
  1) 두 화면 모두 날짜 셀에 내부 코드(DAY/NIGHT..)를 그대로 표시 — 요구사항의 약칭(주/야/OFF..) 표시 위반. (월간 workspace._build_month_grid, 개인 my_schedule._calendar_html)
  2) 기본 연·월이 today(2026-07)라 첫 진입 시 빈 월 → 사용자가 "조회 안 됨"으로 오인 가능(정상 빈 월). 데이터는 2027-07 선택 시 표시.
  3) 월간 schedule_screen 은 상단에서 db.get_schedules()(전체 조회)를 매 렌더 호출 — 일시 소켓 오류 시 화면 전체가 예외로 죽을 수 있음(try/except 없음).
  4) 개인 my_schedule.render 는 전체를 광범위 try/except 로 감싸 모든 예외를 "불러오지 못했습니다"로 뭉갬 — repository 오류와 정상 빈 월 구분 불가(요구 Phase3 #12 위반).
- 기준정보 현황: master_departments=신형 그리드(selectable_master_grid). master_users=editable_aggrid(안정). master_teams=editable_aggrid+요약카드+신규 폼 버튼(구형). master_work_types=st.data_editor+요약카드+색상 텍스트+범례(구형). → Phase4 대상은 teams·work_types 를 부서 관리와 동일한 selectable_master_grid 로 통일 + work_types 색상 컬럼을 색상표로.
- schedule_edit.py 는 이번 무인작업에서 read-only 참조만(수정 금지 준수).
- 다음: Phase 2(월간 조회 약칭·색상·견고성) → Phase 3(개인 조회 약칭·오류 구분) → Phase 4(teams/work_types 통일) → Phase 5 테스트 → Phase 6 감사.
- 요청: ① 저장한 조가 유실되고 전원 A조로 조회되는 오류 수정 ② 통계 카드·하단 범례 제거, 날짜 셀 근무 색상, 표 중심 레이아웃 정리.
- 원인: 조 유실은 코드 fallback 이 아니라 저장처 부재 — 조 스냅샷의 설계 저장처(schedule_assignments, migration 002)가 Supabase 에 미적용이고, 재조회 표시가 users 마스터 조(전원 A조)로 대체되고 있었음.
- 변경: `validators.validate_assignment_records(require_shift=)` 옵션화(기본 True 계약 유지), `db/supabase_repository.upsert_month_assignments(require_shift=)` 전달(False 면 shift_groups 조회 생략·NULL 저장). `views/schedule_edit.py` — 저장 시 행별 부서·조 스냅샷을 upsert_month_assignments(require_shift=False)로 저장 시도(002 이전엔 실패 허용) + 세션 스냅샷 캐시(se_assign_cache), 재조회 표시 우선순위 영속 편성→세션 스냅샷→users 마스터. UI: 통계 카드/범례 제거, 메타 한 줄(대상 월·표시·신규·선택·입력·삭제 예정), 날짜 셀 색상은 work_types.color 를 코드·약칭에 매핑한 cellStyle(연한 배경+진한 글자, DESIGN.md §15 계열). 단위 테스트 15건(조 스냅샷 왕복·A조 fallback 부재·조 변경 유지·users 무변경·기본 계약 유지 포함).
- 파일: views/schedule_edit.py, modules/validators.py, modules/db.py, modules/supabase_repository.py, scripts/test_schedule_save_units.py, docs/WORKLOG.md
- 비고: 커밋 안 함. Supabase 종단(2027-07, 기존 데이터 무접촉): 박시우(2026060101) B조 저장→재조회·월 이동 후 재진입 모두 B조 유지, 셀 색상 일관, 임시 2건 정리 완료. **주의: 프롬프트의 '0행 사고 상태'와 달리 현재 work_schedules 에 558건이 존재하며 전부 2027-07** (2026-07 은 여전히 0). 직전 커밋 시점(총 0행) 이후 이 터미널 밖에서 유입 — 2026-07 복구 시도 중 연도가 2027 로 들어갔을 가능성. 사용자 확인 필요. Supabase 모드의 조 영속 저장은 migration 002 적용 시 자동 활성화(세션 내에서는 유지됨).

## 2026-07-15 15:15 · [터미널] · 근무표 편성 — 혼합 저장·삭제만 저장·전체 선택 수정
- 요청: ① 삭제 예정+동일 사번 재등록 시 저장 차단 해제(교체 처리) ② 삭제만 저장 시 users 조회 의존 제거(WinError 10035 표면적 축소) ③ 선택 헤더 3상태 전체 선택 ④ 필터 결과만 전체 선택.
- 변경: `views/schedule_edit.py` — `classify_save_targets`(delete_only/replace_after_delete)로 최종 사번별 상태 분류, 저장 파이프라인 재구성(검증 전체 통과 후 삭제→교체(replace_month_schedules)→변경분 upsert, 단계 실패 시 단계 보고+초안 유지), 삭제만 저장 경로는 users/근무형태/부서·조 조회 생략, users 매핑 세션 캐시(조회 시점 갱신·rerun 반복 조회 제거), `표시 M·신규 N·선택 K` 카운트 표시, 새로고침 버튼 on_click 플래그 전환(클릭 소실 경합 해결). `views/workspace.py` — `_SELECT_ALL_HEADER`(3상태, forEachNodeAfterFilter로 표시 중 기존 행만, 신규/제거 행 제외, refreshCells로 행 체크 표시 동기화), `selectable_master_grid(select_all_header=)` opt-in(부서 관리 무영향). `scripts/test_schedule_save_units.py` 신규(분류·약칭 계약 10건).
- 파일: views/schedule_edit.py, views/workspace.py, scripts/test_schedule_save_units.py, docs/WORKLOG.md
- 비고: 커밋 안 함. 브라우저 검증(2027-07 임시 데이터 한정, 종료 후 정리 완료): 전체 선택/indeterminate/신규 행 제외/조 변경 시 선택 해제/전체 삭제 예정+1명 재등록 저장(충돌 없음, "2명 삭제·1명 교체", DB stale 없음)/삭제만 저장(빈 월 복귀·dirty·선택 초기화) 모두 통과. 기준정보 무변경(users 21). 2026-07 소실 데이터는 복구 시도하지 않음(아래 사고 기록 유지, 승인 대기).

## 2026-07-15 14:55 · [터미널] · ⚠ 데이터 사고 기록 — Supabase work_schedules 전체 소실 (보존 중)
- 발견: 2026-07-15 14:20~14:40(KST) 사이, 근무표 편성 화면 진입 시 2026-07 기존 행 0명으로 확인 → DB 직접 조회로 확정.
- 현재 테이블 행 수(14:55 기준, read-only 조회): users 21 · departments 5 · teams 6 · work_types 6 · **work_schedules 0** (직전 558행).
- 데이터 존재 마지막 확인: 13:47(KST) 근무표 편성 화면에 2026-07 18명/558건 정상 로드(작업 보고 스크린샷).
- 이 저장소 코드의 근무표 쓰기 API 는 (사번×월) 범위 한정 replace/upsert 뿐이라 테이블 전체 삭제 경로 없음. 13:47 이후 터미널 세션에서 실행한 것은 sample 모드 강제 테스트와 코드 수정뿐(Supabase 쓰기 없음).
- 조치: Supabase 쓰기 중단·상태 보존. 시드 재실행·백업/PITR 복원 금지(사용자 승인 대기). 2026-07 복구 시도 금지. 종단 검증은 2027-07 테스트 월 한정 임시 데이터로만 진행(사용자 지시).

## 2026-07-15 13:49 · [터미널] · 근무표 편성 화면 1차 기능 기반 (사번 중심 입력)
- 요청: 전체 사용자 자동 나열 제거, 사번 중심 입력 + 성명·부서·조 자동 조회, 부서·조 편성값 수정, 근무형태 약칭 표시, 행 추가/삭제, 일괄 저장, dirty tracking + 화면 이탈 경고. 디자인 개편·wheel picker·migration 002 제외.
- 변경: `views/schedule_edit.py` 재작성 — selectable_master_grid(행 상태 계약) 기반: 저장된 직원 행만 표시(없으면 빈 행 1개), [행 추가], 신규 행 − 제거/기존 행 체크박스+[행 삭제]→삭제 예정 패널(취소 가능, 저장 시 replace 로 명시 삭제), 사번 paste→성명·부서·조 자동 채움, 날짜 셀 약칭 표시·입력(저장 시 내부 코드 변환, 미등록/모호 약칭·미등록/중복 사번·재직 아님 차단), 변경 셀만 upsert(빈 셀 자동 삭제 없음 — `db.upsert_month_schedules` 신설), dirty 스냅샷 비교 + 사이드바/로그아웃/조건 변경 이탈 확인(`ui.request_nav` 가드) + beforeunload(best effort). `workspace.selectable_master_grid` 에 col_config(폭·pinned·editable) 확장. `supabase_repository._execute` 일시 소켓 오류(10035 등) 1회 재시도.
- 파일: views/schedule_edit.py, views/workspace.py, modules/ui.py, modules/db.py, modules/supabase_repository.py, docs/WORKLOG.md
- 비고: 커밋 안 함(사용자 확인 대기). 부서·조 편성값 영구 저장은 migration 002 미적용 + 근무조 필수 계약으로 이번 단계 미지원(화면 편집·검증만, 저장 시 안내). 브라우저 검증 28항목 중 핵심 전부 통과, 테스트 데이터(2027-07) 정리 완료·2026-07 558건 무영향. 한계: 편집 직후 ~1초 내 즉시 이탈 시 가드가 한 박자 늦을 수 있음(컴포넌트 전송 경합).

## 2026-07-15 08:11 · [터미널] · App Shell 전면 교체 — 단일 다크 사이드바 (디자인 변경 승인 작업)
- 요청: 기존 "1차 아이콘 레일 + 2차 메뉴 패널" 폐기, 사용자 목업(레퍼런스 이미지) 기준 단일 다크 사이드바로 교체. 다크 차콜(#1B1B1D)+골드(#C9A26B) 톤, 크림 본문(#F1EEE9), 하단 사용자 카드, ▤ 숨김/열기. ADMIN 계정 사번은 ADMIN.
- 변경: `modules/ui.py` app_shell 재작성 — 브랜드 헤더(W 로고+생산 근무표/WORKFORCE), 단독 항목(홈→대시보드)+그룹 라벨(근무표·기준정보)+도트 하위 항목, 맨 아래 고정 사용자 카드(아바타+이름+사번+로그아웃), 본문은 브레드크럼(그룹명)만. 기존 상단 헤더(_header)와 «/» 토글 제거, 숨김은 `sb_hidden` session_state+▤ 버튼. CSS 는 `_SHELL_CSS`(--sb-* 토큰)로 분리해 app_shell 에서만 주입 → USER/로그인 화면 무영향. `nav.py` 홈 그룹 라벨 "대시보드"→"홈". `_ROLE_LABEL` 을 CLAUDE.md §6 표시명(조장/조원)으로 정정. DESIGN.md §2·§3·§4·§7.1·§9·§20, CLAUDE.md §7 App Shell 서술 갱신.
- 파일: modules/ui.py, modules/nav.py, DESIGN.md, CLAUDE.md, docs/WORKLOG.md
- 비고: 커밋 안 함(사용자 화면 확인 대기). 브라우저 검증 — ADMIN: 이동/활성/브레드크럼/숨김·열기·상태 유지 OK, MANAGER(2008110301): 기준정보 미노출 OK, USER(2008082501): 전용 화면 무변화 OK. 주의: 이전 세션에서 웹소켓 재접속이 잦을 때 메뉴가 저절로 이동하는 현상 1회 관찰(안정 세션에서는 재현 안 됨) — 재발 시 보고 요망. 대시보드 KPI 카드 등 본문 내부는 이번 범위에서 미변경(레퍼런스의 카드 스타일과 다름).
- 요청: 사이드바(1차 아이콘 레일 + 2차 메뉴 패널)를 SAP Fiori 계열의 절제된 스타일로 정리. "옅은 강조 + 좌측 3px 액센트 바" 문법으로 통일, 수치 스펙 지정.
- 변경: `modules/ui.py` 사이드바 CSS를 `:root`의 `--nav-*` 디자인 토큰 기반으로 재작성. 레일 72px/항목 64px/간격 4px/단색 `#1B2A4A`, 패널 240px/항목 40px/활성 `#EBF1FC`+`#1B4DBF`+액센트 `#4C7DFF`, 라운드 6px·전환 background-color 130ms 통일. DESIGN.md §3.1·§4.1·§7.1 을 구현 토큰 값으로 갱신.
- 파일: modules/ui.py, DESIGN.md, .claude/launch.json (브라우저 검증용 신규)
- 비고: 커밋 안 함(사용자 화면 확인 대기). 브라우저 검증: ADMIN(1001)으로 대시보드/근무표/기준정보 전환·활성 표시·수치(computed style) 확인 완료, 본문·헤더 변화 없음. 레일 상단은 Streamlit 사이드바 헤더(접기 버튼 영역) 높이만큼 내려온 뒤 4px 간격 시작.

## 2026-07-14 15:02 · [데스크탑] · AGENTS.md 신설 + 디자인 동결·도구 역할 분담 규칙 도입
- 요청: 코덱스·클로드 병행 작업 중 디자인 수정 때마다 화면 틀이 크게 바뀌는 문제 해결. 사용자가 정리한 진행 상황 요약(사용자 관리 검증 14/15 PASS, 로그인 수정 미확인, 조 관리 rerun 경합, 저장 메시지 N건 이슈, 다음 단계 후보 순서 등)도 반영.
- 변경: `AGENTS.md` 신설(Codex 규칙 — CLAUDE.md 원본 참조, UI 파일 수정 금지, 디자인 동결, WORKLOG 기록). `CLAUDE.md` §3에 확인 필요 항목·다음 단계 후보 순서 추가, §7에 디자인 동결 조항, §11에 도구 역할 분담(Claude=UI, Codex=로직·데이터) 추가.
- 파일: AGENTS.md (신규), CLAUDE.md, docs/WORKLOG.md
- 비고: 역할 분담은 필요 시 사용자 지시로 변경 가능. CLAUDE.md 규칙 변경 시 AGENTS.md 요약도 함께 갱신할 것.

## 2026-07-14 14:40 · [데스크탑] · 작업 로그(WORKLOG) 체계 도입
- 요청: 터미널/데스크탑을 오가며 작업할 때 서로의 요청·수정 내용을 이해할 수 있게 로그를 남기고 싶음.
- 변경: `docs/WORKLOG.md`를 신설(형식·규칙 정의). `CLAUDE.md` §12에 "재개 시 WORKLOG 확인 + 작업 후 WORKLOG 기록" 규칙 추가.
- 파일: docs/WORKLOG.md (신규), CLAUDE.md
- 비고: 앞으로 두 도구 모두 작업 완료 시 이 파일 맨 위에 항목을 추가한다.
