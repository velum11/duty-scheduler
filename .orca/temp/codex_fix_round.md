# Codex 합의 수정 라운드 — H1·H2 (코디네이터 발행)

완료 시 커밋 해시를 마지막 메시지로. push 금지(코디네이터가 수행).

## H2 — 개선조치 CAUSE 원시코드 노출 (소형 선행)
`near_miss_improvement.py:577` 부근: 평가/조회와 동일한 `_CAUSE_LABEL`을 추가하고 `cause_val = _CAUSE_LABEL.get(cause, cause)`로 표기(JAM→협착, 미등록 코드는 원문 fallback). 공용 라벨 모듈 추출은 이번에 하지 않음(후속 L11). 표시 전용 — DB 코드·필터·저장 payload 불변.
검증: `scripts/test_near_miss_improvement.py`에 계약 3케이스 추가(JAM→협착·상세설명 보존·미등록 fallback) + 화면 실확인.

## H1 — 공용 편집 그리드 본문 14.5px (기준정보 3화면)
`views/master/style.py:458` 부근 GRID_CSS:
- `.ag-cell` 13px → 14.5px
- 편집기·팝업 정렬: `.ag-text-field-input` · `.ag-picker-field-display` · `.ag-select-list-item` 도 14.5px
- `.ag-header-cell-label` 은 12.5px 그대로 유지
- 행 높이·vertical padding 은 건드리지 말 것(공용 40px·users/work_types 42px — Codex 확인: 충돌 없음. 편성표 MATRIX 30px은 별도 CSS라 무관)
- `master_users.py:1036` 부근의 'ID 13.5px 유지' 류 낡은 주석 정리

검증: `test_master_unified`에 정적 assertion 추가(본문 14.5·헤더 12.5·input/picker/popup 14.5) + master_users_new·master_org_new·master_work_types_new 4스위트 + compileall + diff --check.
회귀 확인(Playwright, sample 새 포트): 사용자·조직·근무형태 1366×768 — 말줄임 과다·편집 input 수직 어긋남·select popup 13px 잔존·조직 3열 밀도, 1200/900 잘림·중첩 스팟체크. 캡처 3장 `.orca/artifacts/claude-design-adopt/codex-fix/`.

순서: H2 → H1 → 테스트 → 시각 확인 → 커밋 1~2건. DESIGN.md 등 미커밋 보존.
