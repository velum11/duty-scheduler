# 아차사고 사진 저장 계약 — 설계·구현 요약 (data-contract Owner)

## 1. Live probe (read-only, test_project 승인됨)
- `client().storage.list_buckets()` → **버킷 0개**. 사진 버킷 없음 → **하드게이트 필요**(생성 미실행).
- `near_miss_reports` 테이블 → **EXISTS**(006 적용됨, live schema 증거). *쓰기는 미실행.*

## 2. 경로 스킴
- `near-miss/{report_id}/{uuid4hex}.jpg` — 서버 생성. **사용자 파일명 경로 미사용**(경로 주입 불가).
- report_id 는 정수 세그먼트만 허용(`_report_segment`), `is_owned_path()` 로 삭제 시 타 경로 차단.

## 3. 압축 파라미터 (`modules/photo_storage.py`, 순수·PIL)
- EXIF 회전 보정 → RGB(투명은 흰 배경 합성) → 최대 변 **1600px** thumbnail → JPEG **품질 80**, 목표 **≤500KB**(품질 40까지 단계 하향, best-effort). 산출물 항상 JPEG.

## 4. 검증 규칙
- 확장자 ∈ {jpg,jpeg,png,webp} **AND** 매직바이트 지문(jpg/png/webp) — 둘 다 확인.
- 원본 ≤ **10MB**. 빈 파일 거부. 실패는 `PhotoValidationError(ValueError)`.
- 보고서당 **최대 3장**: 업로드 게이트 + `photo_paths` 배열 검증(db `_near_miss_editable_fields` + repo `_near_miss_editable_payload`) 이중.

## 5. API (모드 동일 계약, sample/live parity)
- `db.upload_near_miss_photo(report_id, bytes, filename, *, current_user) -> {path, photo_paths}`
  - 게이트: 보고자 본인 + SUBMITTED(신원 서버측 확정, 위조 무시) + 현재 <3.
  - 검증·압축 → 저장 → photo_paths 원자적 조건부(소유자+SUBMITTED) 추가.
  - live: 버킷 미준비면 fail-closed. 경로배열 갱신 실패 시 방금 올린 객체 best-effort 정리(고아 방지).
- `db.get_near_miss_photo_url(path)` — live: 단기 **signed URL**(service key 서버 전용, 공개 버킷 금지). sample: data: URL.
- `db.read_near_miss_photo(path) -> bytes|None`.
- `db.delete_near_miss_photo(report_id, path, *, current_user)` — 소유자+SUBMITTED, 경로배열 먼저 제거(원자) 후 객체 삭제(dangling 참조 방지).
- `db.near_miss_photo_bucket_probe()` — 3-state(sample 항상 READY).
- sample 저장: 세션 인메모리 `st.session_state["store_near_miss_photos"]`(요구사항 §4 계약).

## 6. 하드게이트 — 버킷 생성 승인 요청(미실행)
- 제안 버킷명: **`near-miss-photos`**
- 정책: **비공개(public=false)**. service role 서버 전용 접근, 표시는 signed URL(TTL 3600s).
- 권장 제한: allowed MIME `image/jpeg`(정규화 산출물), 객체 크기 상한 ~2MB(압축 후 여유).
- RLS/policy: service key 접근만(프로덕션 RLS 는 006 주석대로 후속). **생성은 승인 후 별도 task**(본 task 는 생성 안 함).

## 7. 검증 결과
- `scripts/test_near_miss_photos.py` (신규) 58 checks PASS.
- `scripts/test_near_miss_data.py` 260 PASS, improvement 299 / view 59 / ui_gates 73 / error_surfacing 19 / pdf 12 PASS. compileall·git diff --check OK.
- 원격 write/ migration 미실행. requirements.txt 에 `Pillow>=10.0` 추가.

## 8. 미확인/후속
- UI(폰 촬영·PC 업로드·뷰어)는 ui-feature 후속.
- live 업로드/삭제/서명URL 실경로는 버킷 생성 전까지 fail-closed(원격 write 테스트 미실행 — 보호 플래그 필요).
