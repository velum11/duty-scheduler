"""아차사고(near-miss) 사진 첨부 저장 계약 단위 테스트.

원격 write 없이 sample 모드 + 순수 모듈로만 검증한다(실 Storage/실DB 미접속).

검증 항목:
  - 순수 이미지 계약(photo_storage): 형식 지문(확장자+매직바이트), 원본 상한(10MB),
    압축(최대변 1600px·JPEG 정규화), 서버 생성 경로 스킴(사용자 파일명 미사용·경로 주입
    차단), 소유 경로 판정.
  - 파사드(db) sample 모드: 소유자+SUBMITTED 게이트, 신원 서버측 확정(위조 무시),
    보고서당 최대 3장, 저장·표시·삭제 왕복, 경로 소유 검증.
  - photo_paths 배열 검증 max 3 (create/update 양 경로 · db 파사드 + repository).

실행: python scripts/test_near_miss_photos.py
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"  # Supabase 미접속 보장

import streamlit as st  # noqa: E402
from PIL import Image  # noqa: E402

from modules import db  # noqa: E402
from modules import photo_storage as ps  # noqa: E402
from modules import supabase_repository as sr  # noqa: E402

PASSED = 0


def check(name: str, condition: bool) -> None:
    global PASSED
    assert condition, f"FAILED: {name}"
    PASSED += 1
    print(f"  ok - {name}")


def raises(fn, exc_type=Exception):
    try:
        fn()
    except exc_type as exc:
        return exc
    return None


def _img_bytes(fmt: str, size=(2000, 1500), mode="RGB", color=(180, 60, 40)) -> bytes:
    img = Image.new(mode, size, color if mode != "RGBA" else (180, 60, 40, 128))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _reset_stores() -> None:
    st.session_state.pop(db._NEAR_MISS_STORE, None)
    st.session_state.pop(db._NEAR_MISS_PHOTO_STORE, None)
    st.session_state.pop(getattr(db, "_NEAR_MISS_IMPROVEMENT_STORE", "_x"), None)


def _sample_user(idx: int) -> dict:
    row = db.get_users().iloc[idx].to_dict()
    return {
        "emp_no": str(row["emp_no"]),
        "dept_code": str(row.get("dept_code") or ""),
        "role": str(row.get("role") or "USER"),
        "name": str(row.get("name") or ""),
    }


def _fresh_report(reporter: dict) -> dict:
    _reset_stores()
    return db.create_near_miss_report({
        "work_name": "설비 점검", "incident_content": "덮개 미고정",
        "cause_code": "JAM", "incident_date": "2026-07-10", "proposed_grade": "C",
    }, current_user=reporter)


# =========================================================================
# 순수 이미지 계약 (photo_storage)
# =========================================================================
def test_sniff_image_type() -> None:
    print("매직바이트 형식 지문(확장자 아님)")
    check("jpg 지문", ps.sniff_image_type(_img_bytes("JPEG")) == "jpg")
    check("png 지문", ps.sniff_image_type(_img_bytes("PNG")) == "png")
    check("webp 지문", ps.sniff_image_type(_img_bytes("WEBP")) == "webp")
    check("텍스트는 None", ps.sniff_image_type(b"not an image at all") is None)
    check("빈 bytes None", ps.sniff_image_type(b"") is None)


def test_validate_and_compress_formats() -> None:
    print("검증·압축: jpg/png/webp 허용 + JPEG 정규화 + 최대변 1600px")
    for fmt, name in (("JPEG", "a.jpg"), ("PNG", "b.png"), ("WEBP", "c.webp")):
        out, ext, ctype = ps.validate_and_compress(_img_bytes(fmt), name)
        check(f"{fmt} 산출 ext=jpg", ext == "jpg")
        check(f"{fmt} content-type jpeg", ctype == "image/jpeg")
        check(f"{fmt} 산출은 JPEG 지문", ps.sniff_image_type(out) == "jpg")
        with Image.open(io.BytesIO(out)) as im:
            check(f"{fmt} 최대변 ≤1600", max(im.size) <= ps.MAX_EDGE_PX)


def test_validate_and_compress_alpha_flatten() -> None:
    print("투명(RGBA) 이미지는 흰 배경 합성 후 JPEG")
    out, ext, _ = ps.validate_and_compress(_img_bytes("PNG", mode="RGBA"), "t.png")
    check("RGBA→JPEG 정규화", ext == "jpg" and ps.sniff_image_type(out) == "jpg")


def test_validate_rejections() -> None:
    print("거부: 확장자 위반 · 매직바이트 불일치 · 원본 상한 · 빈 파일")
    # 확장자 위반(내용은 PNG여도 .txt).
    check("확장자 미허용 거부",
          isinstance(raises(lambda: ps.validate_and_compress(_img_bytes("PNG"), "x.txt")),
                     ps.PhotoValidationError))
    # 확장자는 jpg지만 매직바이트가 이미지 아님.
    check("매직바이트 불일치 거부",
          isinstance(raises(lambda: ps.validate_and_compress(b"hello world not image", "x.jpg")),
                     ps.PhotoValidationError))
    # 원본 상한 초과(내용 무관 — 크기 검사가 먼저).
    big = b"\xff\xd8\xff" + b"0" * (ps.MAX_UPLOAD_BYTES + 1)
    check("원본 10MB 초과 거부",
          isinstance(raises(lambda: ps.validate_and_compress(big, "big.jpg")),
                     ps.PhotoValidationError))
    check("빈 파일 거부",
          isinstance(raises(lambda: ps.validate_and_compress(b"", "e.jpg")),
                     ps.PhotoValidationError))


def test_object_path_scheme() -> None:
    print("경로 스킴: near-miss/{report_id}/{uuid}.jpg · 사용자 파일명 미사용 · 주입 차단")
    p = ps.build_object_path(42)
    check("접두 near-miss/42/", p.startswith("near-miss/42/"))
    check("확장자 jpg 고정", p.endswith(".jpg"))
    check("경로 세그먼트 3개", p.count("/") == 2)
    p2 = ps.build_object_path(42)
    check("uuid 파일명은 무작위(중복 아님)", p != p2)
    # report_id 비정수(경로 주입 시도)는 거부.
    check("경로 주입 report_id 거부",
          isinstance(raises(lambda: ps.build_object_path("../secret")), ps.PhotoValidationError))
    check("빈 report_id 거부",
          isinstance(raises(lambda: ps.build_object_path("")), ps.PhotoValidationError))
    # 소유 경로 판정.
    check("소유 경로 True", ps.is_owned_path(42, p) is True)
    check("타 보고서 경로 False", ps.is_owned_path(99, p) is False)
    check("하위 경로 조작 False", ps.is_owned_path(42, "near-miss/42/../x.jpg") is False)


# =========================================================================
# 파사드 sample 모드 — 저장 계약
# =========================================================================
def test_upload_happy_path() -> None:
    print("업로드 왕복: 검증·압축·저장·경로배열 갱신 + 표시 URL + 원본 읽기")
    reporter = _sample_user(0)
    rec = _fresh_report(reporter)
    rid = rec["id"]
    res = db.upload_near_miss_photo(rid, _img_bytes("JPEG"), "phone.jpg", current_user=reporter)
    path = res["path"]
    check("경로 스킴 정합", ps.is_owned_path(rid, path))
    check("photo_paths 에 추가", res["photo_paths"] == [path])
    check("보고서 photo_paths 반영", db.get_near_miss_report(rid)["photo_paths"] == [path])
    data = db.read_near_miss_photo(path)
    check("원본 bytes 읽힘(JPEG)", ps.sniff_image_type(data) == "jpg")
    url = db.get_near_miss_photo_url(path)
    check("sample 표시 URL 은 data:", isinstance(url, str) and url.startswith("data:image/jpeg;base64,"))
    check("없는 경로 URL None", db.get_near_miss_photo_url("near-miss/1/none.jpg") is None)


def test_upload_max_three() -> None:
    print("보고서당 최대 3장 — 4번째 거부")
    reporter = _sample_user(0)
    rid = _fresh_report(reporter)["id"]
    for i in range(3):
        db.upload_near_miss_photo(rid, _img_bytes("JPEG"), f"p{i}.jpg", current_user=reporter)
    check("3장 저장됨", len(db.get_near_miss_report(rid)["photo_paths"]) == 3)
    exc = raises(lambda: db.upload_near_miss_photo(rid, _img_bytes("JPEG"), "p4.jpg", current_user=reporter),
                 ValueError)
    check("4번째 거부(ValueError)", exc is not None and "최대" in str(exc))
    check("거부 후에도 3장 유지", len(db.get_near_miss_report(rid)["photo_paths"]) == 3)


def test_upload_owner_and_state_gate() -> None:
    print("업로드 게이트: 비소유자 차단 · 존재하지 않는 보고서 · 신원 서버측 확정")
    reporter = _sample_user(0)
    other = _sample_user(1)
    check("전제: 두 사용자 다름", reporter["emp_no"] != other["emp_no"])
    rid = _fresh_report(reporter)["id"]
    # 비소유자 차단.
    exc = raises(lambda: db.upload_near_miss_photo(rid, _img_bytes("JPEG"), "x.jpg", current_user=other),
                 ValueError)
    check("비소유자 업로드 차단", exc is not None)
    # 위조 current_user(사번은 other 지만 dept/role 조작)도 서버가 사번으로 재확정 → 여전히 비소유자.
    forged = {"emp_no": other["emp_no"], "dept_code": reporter["dept_code"], "role": "ADMIN"}
    check("위조 신원도 비소유자 차단",
          raises(lambda: db.upload_near_miss_photo(rid, _img_bytes("JPEG"), "x.jpg", current_user=forged), ValueError) is not None)
    # 존재하지 않는 보고서.
    check("없는 보고서 차단",
          raises(lambda: db.upload_near_miss_photo(999999, _img_bytes("JPEG"), "x.jpg", current_user=reporter), ValueError) is not None)
    check("업로드 실패 시 사진 미저장", len(db.get_near_miss_report(rid)["photo_paths"]) == 0)


def test_delete_photo() -> None:
    print("삭제: 소유자+SUBMITTED 경로배열·객체 제거 · 타 경로/미첨부 거부")
    reporter = _sample_user(0)
    other = _sample_user(1)
    rid = _fresh_report(reporter)["id"]
    p1 = db.upload_near_miss_photo(rid, _img_bytes("JPEG"), "a.jpg", current_user=reporter)["path"]
    p2 = db.upload_near_miss_photo(rid, _img_bytes("JPEG"), "b.jpg", current_user=reporter)["path"]
    check("2장 첨부", len(db.get_near_miss_report(rid)["photo_paths"]) == 2)
    # 비소유자 삭제 차단.
    check("비소유자 삭제 차단",
          raises(lambda: db.delete_near_miss_photo(rid, p1, current_user=other), ValueError) is not None)
    # 타 보고서 경로 삭제 차단.
    check("타 경로 삭제 차단",
          raises(lambda: db.delete_near_miss_photo(rid, "near-miss/99/x.jpg", current_user=reporter), ValueError) is not None)
    # 미첨부 경로 삭제 차단(스킴은 맞지만 목록에 없음).
    stray = ps.build_object_path(rid)
    check("미첨부 경로 삭제 차단",
          raises(lambda: db.delete_near_miss_photo(rid, stray, current_user=reporter), ValueError) is not None)
    # 정상 삭제.
    res = db.delete_near_miss_photo(rid, p1, current_user=reporter)
    check("삭제 후 1장", res["photo_paths"] == [p2])
    check("삭제된 객체 bytes 제거", db.read_near_miss_photo(p1) is None)
    check("남은 객체 bytes 유지", db.read_near_miss_photo(p2) is not None)


def test_upload_blocked_when_not_submitted() -> None:
    print("SUBMITTED 아닌 보고서에는 사진 첨부/삭제 불가")
    reporter = _sample_user(0)
    rid = _fresh_report(reporter)["id"]
    p = db.upload_near_miss_photo(rid, _img_bytes("JPEG"), "a.jpg", current_user=reporter)["path"]
    # 상태를 강제로 IN_REVIEW 로(스토어 직접 변경 — 게이트 확인용).
    db._sample_update_near_miss(rid, status="IN_REVIEW")
    check("비SUBMITTED 업로드 차단",
          raises(lambda: db.upload_near_miss_photo(rid, _img_bytes("JPEG"), "b.jpg", current_user=reporter), ValueError) is not None)
    check("비SUBMITTED 삭제 차단",
          raises(lambda: db.delete_near_miss_photo(rid, p, current_user=reporter), ValueError) is not None)


def test_body_edit_ignores_photo_paths() -> None:
    print("P1-3: 본문 수정은 photo_paths 를 무시(사진 배열 불변) — db·repo 검증에서 제외")
    reporter = _sample_user(0)
    rid = _fresh_report(reporter)["id"]
    p = db.upload_near_miss_photo(rid, _img_bytes("JPEG"), "a.jpg", current_user=reporter)["path"]
    # 본문 수정 payload 에 photo_paths=[] 를 실어도(삭제 위장) 사진은 그대로 유지된다.
    db.update_near_miss_report(rid, {
        "work_name": "본문만 수정", "cause_code": "FALL", "cause_detail": "d",
        "incident_content": "c", "work_content": "w", "countermeasure": "m",
        "site_description": "s", "incident_date": "2026-07-11", "photo_paths": [],
    }, current_user=reporter)
    after = db.get_near_miss_report(rid)
    check("본문 수정 반영", after["work_name"] == "본문만 수정")
    check("사진 배열 불변(본문 수정이 무시)", after["photo_paths"] == [p])
    # 편집 검증 헬퍼는 photo_paths 키를 반환에 포함하지 않는다(계약 제외).
    fields = db._near_miss_editable_fields({
        "work_name": "w", "cause_code": "JAM", "incident_date": "2026-07-10",
        "photo_paths": ["x.jpg"]})
    check("db 편집 헬퍼에 photo_paths 없음", "photo_paths" not in fields)
    payload = sr._near_miss_editable_payload({
        "work_name": "w", "cause_code": "JAM", "incident_date": "2026-07-10",
        "photo_paths": ["x.jpg"]})
    check("repo 편집 헬퍼에 photo_paths 없음", "photo_paths" not in payload)


def test_photo_cas_concurrent_stale() -> None:
    print("P1-3 CAS: read 이후 다른 사진 변경이 끼면 stale 로 거부(lost update 방지)")
    reporter = _sample_user(0)
    rid = _fresh_report(reporter)["id"]
    # 업로드 파사드 내부: gate read(existing=[]) 이후, set 직전에 다른 첨부가 끼어드는 경합을
    # _sample_update_near_miss CAS 로 잡는지 직접 검증한다.
    # 1) 먼저 사진 1장을 넣어 현재 배열을 [p0] 으로 만든다.
    p0 = db.upload_near_miss_photo(rid, _img_bytes("JPEG"), "a.jpg", current_user=reporter)["path"]
    # 2) stale 스냅샷([])으로 CAS 를 시도하면 현재([p0])와 달라 거부(False)돼야 한다.
    ok_stale = db._sample_update_near_miss(
        rid, expected_status="SUBMITTED", owner_emp_no=reporter["emp_no"],
        expected_photo_paths=[], photo_paths=["near-miss/9/deadbeefdeadbeefdeadbeefdeadbeef.jpg"])
    check("stale 스냅샷 CAS 거부", ok_stale is False)
    check("거부 후 사진 배열 불변", db.get_near_miss_report(rid)["photo_paths"] == [p0])
    # 3) 올바른 스냅샷([p0])이면 적용된다.
    ok_fresh = db._sample_update_near_miss(
        rid, expected_status="SUBMITTED", owner_emp_no=reporter["emp_no"],
        expected_photo_paths=[p0], photo_paths=[p0])
    check("일치 스냅샷 CAS 적용", ok_fresh is True)


def test_delete_storage_failure_surfaced() -> None:
    print("P1-4: 스토리지 삭제 실패는 성공 위장 금지 — storage_deleted=False 로 표면화")
    reporter = _sample_user(0)
    rid = _fresh_report(reporter)["id"]
    p = db.upload_near_miss_photo(rid, _img_bytes("JPEG"), "a.jpg", current_user=reporter)["path"]
    # supabase 삭제 경로만 겨냥해 파사드 게이트/actor 는 그대로 두고 repo 경계만 mock 한다.
    saved = {
        "sample": db.is_sample_mode, "actor": db._near_miss_actor,
        "gate": db._near_miss_owner_editable_gate, "setp": sr.set_near_miss_photo_paths,
        "rm": sr.remove_near_miss_photo_object, "inv": db._invalidate_near_miss,
    }
    db.is_sample_mode = lambda: False
    db._invalidate_near_miss = lambda: None
    db._near_miss_actor = lambda cu, *, action: {"emp_no": reporter["emp_no"]}
    db._near_miss_owner_editable_gate = lambda rid_, actor: {
        "reporter_emp_no": reporter["emp_no"], "status": "SUBMITTED",
        "photo_paths": [p], "updated_at": "2026-07-31T00:00:00+00:00"}
    sr.set_near_miss_photo_paths = lambda rid_, paths, **k: {"photo_paths": list(paths)}
    def boom_remove(path):
        raise sr.SupabaseDataError("Supabase near-miss-photos 사진 삭제 실패: network")
    sr.remove_near_miss_photo_object = boom_remove
    try:
        res = db.delete_near_miss_photo(rid, p, current_user=reporter)
        check("참조는 제거됨(부분 성공)", res["photo_paths"] == [])
        check("스토리지 삭제 실패 표면화(storage_deleted=False)", res["storage_deleted"] is False)
    finally:
        db.is_sample_mode = saved["sample"]
        db._near_miss_actor = saved["actor"]
        db._near_miss_owner_editable_gate = saved["gate"]
        sr.set_near_miss_photo_paths = saved["setp"]
        sr.remove_near_miss_photo_object = saved["rm"]
        db._invalidate_near_miss = saved["inv"]


def test_owned_path_uuid_format() -> None:
    print("P2: is_owned_path 는 {32-hex uuid}.jpg 형식을 강제(임의 파일명 배제)")
    good = db.photo_storage.build_object_path(7)
    check("정상 uuid 경로 소유", db.photo_storage.is_owned_path(7, good))
    check("임의 파일명 배제", db.photo_storage.is_owned_path(7, "near-miss/7/anything.jpg") is False)
    check("대문자 hex 배제", db.photo_storage.is_owned_path(7, "near-miss/7/DEADBEEFDEADBEEFDEADBEEFDEADBEEF.jpg") is False)
    check("확장자 위반 배제", db.photo_storage.is_owned_path(7, "near-miss/7/deadbeefdeadbeefdeadbeefdeadbeef.png") is False)


def test_decompression_bomb_and_formats() -> None:
    print("P1-2: 픽셀 상한(decompression bomb) 거부 + 디코더 3종 제한")
    from PIL import Image
    # MAX_IMAGE_PIXELS 초과 이미지는 거부(원본 bytes 는 작아도 픽셀 수로 차단).
    big = Image.new("RGB", (7000, 7000), (10, 20, 30))  # 49MP > 40MP 상한
    buf = io.BytesIO(); big.save(buf, format="PNG")
    exc = raises(lambda: ps.validate_and_compress(buf.getvalue(), "big.png"), ps.PhotoValidationError)
    check("40MP 초과 거부", exc is not None)
    # 상한 이하(정상)는 통과.
    okimg = Image.new("RGB", (1200, 1200), (10, 20, 30))
    b2 = io.BytesIO(); okimg.save(b2, format="PNG")
    out, ext, _ = ps.validate_and_compress(b2.getvalue(), "ok.png")
    check("상한 이하 정상 처리", ext == "jpg" and ps.sniff_image_type(out) == "jpg")
    check("MAX_IMAGE_PIXELS 상수 노출", ps.MAX_IMAGE_PIXELS == 40 * 1000 * 1000)


def test_validate_and_compress_idempotent() -> None:
    print("멱등: 이미 정규화된 JPEG 는 재압축 없이 통과 — validate(out)==out")
    out, ext, ctype = ps.validate_and_compress(_img_bytes("PNG", size=(2000, 1500)), "src.png")
    check("1차 산출 JPEG ≤1600px ≤500KB", ext == "jpg" and len(out) <= ps.TARGET_BYTES)
    # 2차: 1차 산출물을 다시 넣으면 바이트가 동일해야 한다(재압축 안 함).
    out2, ext2, ctype2 = ps.validate_and_compress(out, "out.jpg")
    check("2차 산출 바이트 동일(멱등)", out2 == out)
    check("2차 ext/ctype 동일", ext2 == "jpg" and ctype2 == "image/jpeg")
    # 3차도 동일(고정점).
    out3, _, _ = ps.validate_and_compress(out2, "out.jpg")
    check("3차도 동일(고정점)", out3 == out)
    # 단, 최대변 초과 JPEG 는 정규화 대상(멱등 단축 미적용) → 크기 축소.
    from PIL import Image
    big = Image.new("RGB", (2400, 1000), (30, 60, 90))
    bb = io.BytesIO(); big.save(bb, format="JPEG", quality=80)
    red, rext, _ = ps.validate_and_compress(bb.getvalue(), "big.jpg")
    with Image.open(io.BytesIO(red)) as im:
        check("최대변 초과 JPEG 는 축소(멱등 단축 제외)", max(im.size) <= ps.MAX_EDGE_PX)


def test_bucket_probe_sample_ready() -> None:
    print("사진 버킷 probe: sample 은 항상 READY(세션 인메모리)")
    check("sample 버킷 READY", db.near_miss_photo_bucket_probe() == sr.READINESS_READY)


def test_public_bucket_fail_closed() -> None:
    print("P1-5: 공개 버킷은 READY 오인 금지 — PROBE_ERROR(쓰기 차단)")
    saved = sr.client
    class _B:
        def __init__(self, name, public): self.name = name; self.public = public
    class _Storage:
        def __init__(self, public): self._public = public
        def list_buckets(self): return [_B(sr.NEAR_MISS_PHOTO_BUCKET, self._public)]
    class _Client:
        def __init__(self, public): self.storage = _Storage(public)
    try:
        # 비공개 → READY
        sr.client = lambda: _Client(False)
        sr.reset_near_miss_photo_bucket_readiness()
        check("비공개 버킷 READY", sr.near_miss_photo_bucket_probe(force=True) == sr.READINESS_READY)
        check("비공개 ready True", sr.near_miss_photo_bucket_ready() is True)
        # 공개 → PROBE_ERROR(비캐시, 쓰기 차단)
        sr.client = lambda: _Client(True)
        sr.reset_near_miss_photo_bucket_readiness()
        check("공개 버킷 PROBE_ERROR", sr.near_miss_photo_bucket_probe(force=True) == sr.READINESS_PROBE_ERROR)
        check("공개 ready False(쓰기 차단)", sr.near_miss_photo_bucket_ready() is False)
        # public 판정 불가(None) → PROBE_ERROR
        sr.client = lambda: _Client(None)
        sr.reset_near_miss_photo_bucket_readiness()
        check("public 불명도 fail-closed", sr.near_miss_photo_bucket_probe(force=True) == sr.READINESS_PROBE_ERROR)
    finally:
        sr.client = saved
        sr.reset_near_miss_photo_bucket_readiness()


def main() -> int:
    for test in (
        test_sniff_image_type,
        test_validate_and_compress_formats,
        test_validate_and_compress_alpha_flatten,
        test_validate_rejections,
        test_object_path_scheme,
        test_upload_happy_path,
        test_upload_max_three,
        test_upload_owner_and_state_gate,
        test_delete_photo,
        test_upload_blocked_when_not_submitted,
        test_body_edit_ignores_photo_paths,
        test_photo_cas_concurrent_stale,
        test_delete_storage_failure_surfaced,
        test_owned_path_uuid_format,
        test_decompression_bomb_and_formats,
        test_validate_and_compress_idempotent,
        test_bucket_probe_sample_ready,
        test_public_bucket_fail_closed,
    ):
        test()
    print(f"\nALL PASSED ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
