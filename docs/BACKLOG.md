# 미결 백로그

해결되지 않은 결정·후속 작업의 추적 파일입니다. `docs/WORKLOG.md`는 순수 이력이며 미결 추적은 이 파일이 정본입니다. 항목이 해결되면 여기서 제거하고 WORKLOG에 결과를 기록합니다.

## 결정 대기 (사용자)

| 항목 | 내용 | 출처 |
|---|---|---|
| §98 비활성 직원 표시 | 비활성 직원의 과거 근무를 조회 화면에 표시할지 — 무결성 계약(참조 유지)은 데이터 계층이 이미 충족, 표시 여부는 제품 판단 | 2026-07-24 |

## 작업 대기

| 항목 | 내용 | 유형 |
|---|---|---|
| 대시보드 P3 | 비차단 개선 잔여분 | 코드 |
| 잔존 worktree 정리 | `.claude/worktrees/` 6개(등록 5+빈 고아 1) — integrator 검증 완료(07-25): **전건 feature 병합·미커밋 0·안전 제거 가능**, 병합 완료 branch 6개도 삭제 후보. 사용자 승인 대기 | 정리 |
| worktype-improve-2 확인 | ORCA workspace `C:/Users/velum/orca/workspaces/duty-scheduler/worktype-improve-2`에 미커밋 변경 존재(WORKLOG·test_master_work_types_new·master_work_types) — 과거 근무형태 작업 잔재로 추정, 보존/폐기 판단 필요 | 확인 |
| 화면 규약 Phase B | 기존 비-master 화면(대시보드·근무표 3종) 크롬을 `views/common/scaffold.py` 경유로 점진 이전 + Codex 가용 시 scaffold 사후 감사(감사 부채) | 코드 |

## 후보 (미채택 — 필요 시 재검토)

- 문서 정합 자동 점검 스크립트(`test_docs_consistency.py`): migration 목록 vs 문서 표 일치·참조 경로 실존 검사 (2026-07-25 인터뷰에서 미채택)
- `.orca/artifacts/` INDEX·archive 정책 (동일)
- 글로벌 PLAYBOOK·skill 참조 버전(날짜·해시) 오버레이 기록 (동일)
- 테스트 명령 중복(CLAUDE·README) 참조화 (안전경계만 정리하기로 결정)
