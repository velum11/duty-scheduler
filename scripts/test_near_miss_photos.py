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


def test_photo_paths_max_three_validators() -> None:
    print("photo_paths 배열 max 3 — create/update 검증(db 파사드 + repository)")
    four = ["near-miss/1/a.jpg", "near-miss/1/b.jpg", "near-miss/1/c.jpg", "near-miss/1/d.jpg"]
    # db 파사드 편집 검증.
    check("db _near_miss_editable_fields 4장 거부",
          isinstance(raises(lambda: db._near_miss_editable_fields({
              "work_name": "w", "cause_code": "JAM", "incident_date": "2026-07-10",
              "photo_paths": four}), ValueError), ValueError))
    check("db 3장 허용", db._near_miss_editable_fields({
        "work_name": "w", "cause_code": "JAM", "incident_date": "2026-07-10",
        "photo_paths": four[:3]})["photo_paths"] == four[:3])
    # repository 편집 검증.
    check("repo _near_miss_editable_payload 4장 거부",
          isinstance(raises(lambda: sr._near_miss_editable_payload({
              "work_name": "w", "cause_code": "JAM", "incident_date": "2026-07-10",
              "photo_paths": four}), sr.SupabaseDataError), sr.SupabaseDataError))


def test_bucket_probe_sample_ready() -> None:
    print("사진 버킷 probe: sample 은 항상 READY(세션 인메모리)")
    check("sample 버킷 READY", db.near_miss_photo_bucket_probe() == sr.READINESS_READY)


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
        test_photo_paths_max_three_validators,
        test_bucket_probe_sample_ready,
    ):
        test()
    print(f"\nALL PASSED ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
