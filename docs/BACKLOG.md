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

## 후보 (미채택 — 필요 시 재검토)

- 문서 정합 자동 점검 스크립트(`test_docs_consistency.py`): migration 목록 vs 문서 표 일치·참조 경로 실존 검사 (2026-07-25 인터뷰에서 미채택)
- `.orca/artifacts/` INDEX·archive 정책 (동일)
- 글로벌 PLAYBOOK·skill 참조 버전(날짜·해시) 오버레이 기록 (동일)
- 테스트 명령 중복(CLAUDE·README) 참조화 (안전경계만 정리하기로 결정)
