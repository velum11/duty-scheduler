# 수정 라운드 3 — 조직 부분성공 reconcile (data-contract, 코디네이터 발행)

Codex 평가 M6 — 차기 1순위 지정 건. requirements §6 부분 성공 계약(성공 키만 반영·실패 키는 편집 상태 유지·unknown은 재조회 필요 분리)이 조직 관리에서 미완: master_org.py:693 부근이 partial 결과를 원장 배너로만 표시하고 화면 상태를 reconcile하지 않음.

## 범위 (views/master_org.py + 테스트만 — 다른 화면·modules 금지, ui-feature 워커가 다른 파일 작업 중)
Codex 확정 방침:
- 그룹·부서·운영단위 **3범위 각각 독립** reconcile: 성공 행만 baseline 갱신 + 신규행→기존행 전환(자연키: group_code / dept_code / (dept_code, team_code)), 실패 행은 draft·dirty·셀 오류 유지, **unknown(재조회 필요)은 일절 reconcile하지 않음**.
- users 패턴(신규행 e:{key} 전환+baseline 갱신)을 참조하되 단순 복사 금지 — work_types 패턴은 신규행 전환이 불완전하므로 참조만.
- _GRP/_OD/_OU 범위 간 재적재·dirty 해제가 새지 않는지(한 범위 저장이 다른 범위 상태를 건드리지 않는지) 필수 검증.
- 3독립 저장 계약·드릴다운 잠금·readiness 게이트 불변.

## 검증
scripts/test_master_org_new.py에 부분 성공 reconcile 계약 케이스 추가(범위별: 성공만/혼합/전실패/unknown — 신규행 전환·baseline·dirty·오류 유지 각각), 기존 org 134·unified 199 그린 + compileall + diff --check. sample Playwright로 그룹 부분 실패 시나리오 1회 유도 가능하면 확인(불가하면 계약 테스트로 충분 — 보고에 명시).

완료 시 커밋 해시를 마지막 메시지로(push 금지).
