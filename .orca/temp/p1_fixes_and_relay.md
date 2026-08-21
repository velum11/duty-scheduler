# Codex P1/P2 사진 계약 수정 완료 + 사용자 추가요청 릴레이 (data-contract Owner)

## A. 완료한 P1/P2 (커밋 df5f454, 5c7d0f1 — push 완료)

| 항목 | 처리 |
|---|---|
| **P1-2** decompression bomb | `Image.open(formats=JPEG/PNG/WEBP)` 제한 + `MAX_IMAGE_PIXELS=40MP` 명시 + `DecompressionBombWarning`→오류 승격 + 디코드(EXIF/RGB) 전 `w*h` 사전검사 |
| **P1-3** photo_paths 원자성 | 첨부/삭제를 CAS 로: supabase=`updated_at` 스냅샷 `.eq`, sample=배열 스냅샷 비교. 경합 시 0행→stale 표면화. **본문 수정 payload 에서 photo_paths 완전 제외**(db `_near_miss_editable_fields`·repo `_near_miss_editable_payload` 에서 제거, 무시). create 는 photo_paths=[] 명시 |
| **P1-4** 삭제 실패 은폐 | delete 반환에 `storage_deleted: bool` — 스토리지 삭제 실패를 부분성공으로 표면화(성공 위장 금지). 업로드 보상삭제 실패 포함 **보고서 id·객체경로만** 로그(서명 URL·키 금지) |
| **P1-5** public 버킷 READY 오인 | probe 가 `public is False` 까지 확인. 공개/판정불가 → PROBE_ERROR(비캐시, 쓰기 차단) + 경고 로그 |
| **P2** reset_client | near-miss 스키마 + 사진 버킷 readiness 도 초기화(연결 교체 후 stale READY 방지) |
| **P2** is_owned_path | `{32-hex uuid}.jpg` 정규식 강제(임의 파일명 배제) |
| **P2** requirements 핀 | `Pillow>=10,<13` · `fpdf2>=2.8,<3` |
| **P2** OFL 전문 | `fonts/OFL.txt` 원문 동봉 + NOTICE 참조 |
| 추가 | `validate_and_compress` **멱등**: 이미 정규화된 JPEG(≤1600px·≤500KB·JPEG·회전EXIF 없음)는 재압축 없이 통과(고정점) |

**검증**: photos 81 checks / data 260 / improvement 299 / view 59 / ui_gates 73 / error_surfacing 19 / pdf 12 — 전부 그린. compileall·diff --check OK. 원격 write/migration 미실행.

**뷰 조정 필요(ui-feature 코디)**: 본문 수정이 photo_paths 를 무시하므로 `near_miss_my.py` 의 "기존 첨부 보존" payload 는 이제 자동 보존(무해). `delete_near_miss_photo` 반환에 `storage_deleted` 추가됨 — UI 가 부분성공 안내 가능.

## B. 사용자 추가요청 릴레이 (내 dispatch/역할 밖 — 코디 라우팅 필요)

사용자가 턴 중 4건을 추가 지시함. 대부분 **뷰(ui-feature)** + **기능검증(contract-qa/Codex)** 영역이라 data-contract 단독 처리 범위를 넘음. 데이터 계층 관점만 첨부:

1. **아차사고 조회 필터 간소화 + 기간 미지정=전체** (스샷3·4·5)
   - 데이터: `get_near_miss_reports(filters)` 는 이미 date_from/date_to **선택**(미지정=전 기간) + status/dept/cause/grade/reporter 지원. → **facade 변경 불필요**, UI 배치·기간위젯(전체/기간지정) 재작업만.
2. **아차사고 분석: 년월 지정 + 해당월까지 누적 + 당월 실적** (스샷6)
   - 데이터: incident_date 기준 필터로 누적(date_to=월말)·당월(date_from=월초,date_to=월말) 산출 가능. 원하면 `near_miss_analytics(year_month)` facade 헬퍼(누적/당월 집계) 신설 제안 — **결정 필요(B-1)**.
3. **내 아차사고 필터링(대량 대비)** (스샷7) + **개선조치 동일**
   - 데이터: 내 아차사고는 reporter_emp_no+status+기간 facade 지원. 개선조치(`get_near_miss_improvements`) 필터 파라미터는 **확인 필요** — 없으면 신설 제안(B-2).
4. **기능 종단 검증(인쇄/PDF·촬영·테이블 연결·등록/평가/요약) + 화면 부족점 탐색 + Codex 리뷰**
   - contract-qa(read-only 종단) + ui-feature(화면) + Codex(리뷰) 오케스트레이션 권장. data-contract 는 계약/facade 질문에 응답 대기.

## C. 사용자 의사결정 필요 항목
- **B-1**: 분석 누적/당월을 facade 헬퍼로 신설할지, UI 단 2회 조회로 처리할지.
- **B-2**: 개선조치 목록 필터를 어느 축(상태/기간/담당자)으로 열지.
- **버킷/원격**: 추가 live 스모크나 write 테스트가 필요하면 전용 테스트프로젝트+보호플래그로만(현재 near-miss-photos 버킷 생성·검증 완료).
