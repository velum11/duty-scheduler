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
