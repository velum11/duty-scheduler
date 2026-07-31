"""아차사고(near-miss) 사진 첨부의 **검증·압축·경로 계약** (프레임워크·DB 비의존).

이 모듈은 순수(pure) 함수만 담는다 — streamlit·supabase·db 를 import 하지 않으므로
단위 테스트가 실DB/세션 없이 가능하다. 실제 저장 백엔드(supabase Storage / sample
세션 인메모리)는 ``modules/db.py`` 파사드와 ``modules/supabase_repository.py`` 가
소유하며, 여기서는 "무엇을 허용하고 어떻게 정규화하는가"의 계약만 정의한다.

계약(불변):
  - 보고서당 최대 ``MAX_PHOTOS`` 장.
  - 원본 업로드 ≤ ``MAX_UPLOAD_BYTES`` (대용량 거부).
  - 허용 형식은 **확장자 + 매직바이트**를 모두 확인한다(jpg/png/webp). 확장자만
    믿지 않는다(위조 방지).
  - 압축 산출물은 항상 JPEG 로 정규화한다(최대 변 ``MAX_EDGE_PX`` 축소, 품질
    하향으로 ``TARGET_BYTES`` 목표). 형식 지문을 하나로 좁혀 저장/표시를 단순화한다.
  - 저장 경로는 서버가 만든다: ``near-miss/{report_id}/{uuid}.jpg``. **사용자 입력
    파일명을 경로에 쓰지 않는다**(경로 주입 불가). report_id 는 정수 세그먼트로만
    허용한다.
"""
from __future__ import annotations

import io
import uuid

# --- 계약 상수 ---------------------------------------------------------------
MAX_PHOTOS = 3                       # 보고서당 최대 첨부 장수
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 원본 업로드 상한(10MB)
MAX_EDGE_PX = 1600                   # 압축 후 최대 변(px)
JPEG_QUALITY = 80                    # 1차 JPEG 품질
_MIN_QUALITY = 40                    # 목표 용량 접근을 위한 품질 하한(과열화 방지)
TARGET_BYTES = 500 * 1024            # 압축 목표(≤500KB, best-effort)

# 정규화 산출물은 항상 JPEG.
OUTPUT_EXT = "jpg"
OUTPUT_CONTENT_TYPE = "image/jpeg"

# 허용 입력 형식(확장자 + 매직바이트 지문). 저장은 JPEG 로 정규화하지만 입력은 세 형식.
_ALLOWED_EXTS = {"jpg", "jpeg", "png", "webp"}


class PhotoValidationError(ValueError):
    """사진 검증 실패(사용자에게 그대로 노출 가능한 도메인 오류).

    ``ValueError`` 하위형이므로 파사드/화면의 기존 ``except ValueError`` 경로가
    그대로 사용자 안전 문구로 표시한다(원문 비노출 계약과 정합)."""


def sniff_image_type(data: bytes) -> str | None:
    """매직바이트로 이미지 형식을 판정한다: ``'jpg'|'png'|'webp'`` 또는 None.

    확장자를 신뢰하지 않고 실제 바이트 지문으로만 판정한다(위조 방지)."""
    if not data or len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _ext_of(filename: str) -> str:
    name = str(filename or "").strip().lower()
    _, _, ext = name.rpartition(".")
    return ext if ext and ext != name else ""


def validate_and_compress(file_bytes: bytes, filename: str) -> tuple[bytes, str, str]:
    """업로드 1장을 검증·압축해 ``(정규화_bytes, ext, content_type)`` 를 반환한다.

    검증: 원본 ≤ ``MAX_UPLOAD_BYTES``, 확장자 ∈ {jpg,jpeg,png,webp}, **그리고**
    매직바이트가 jpg/png/webp 중 하나. 압축: EXIF 방향 보정 → RGB(투명은 흰 배경
    합성) → 최대 변 ``MAX_EDGE_PX`` 로 축소 → JPEG(품질 ``JPEG_QUALITY``, 목표
    ``TARGET_BYTES`` 초과 시 품질을 ``_MIN_QUALITY`` 까지 단계 하향). 산출물은 항상
    JPEG(``OUTPUT_EXT``/``OUTPUT_CONTENT_TYPE``).

    실패는 ``PhotoValidationError``(=ValueError). Pillow(PIL) 필요."""
    if not isinstance(file_bytes, (bytes, bytearray)):
        raise PhotoValidationError("이미지 데이터가 올바르지 않습니다.")
    data = bytes(file_bytes)
    if len(data) == 0:
        raise PhotoValidationError("빈 파일은 첨부할 수 없습니다.")
    if len(data) > MAX_UPLOAD_BYTES:
        mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise PhotoValidationError(f"이미지 용량이 너무 큽니다. 최대 {mb}MB 까지 첨부할 수 있습니다.")

    ext = _ext_of(filename)
    if ext not in _ALLOWED_EXTS:
        raise PhotoValidationError("JPG·PNG·WEBP 형식의 이미지만 첨부할 수 있습니다.")
    sniffed = sniff_image_type(data)
    if sniffed is None:
        raise PhotoValidationError(
            "이미지 형식을 확인할 수 없습니다. JPG·PNG·WEBP 파일인지 확인하세요."
        )

    try:
        from PIL import Image, ImageOps
    except Exception as exc:  # noqa: BLE001 — 배포 의존성 누락을 명확히 알린다.
        raise PhotoValidationError(
            "이미지 처리 구성요소(Pillow)를 사용할 수 없어 사진을 저장할 수 없습니다."
        ) from exc

    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)  # 폰 촬영 회전 보정
            if img.mode in ("RGBA", "LA", "P"):
                # 투명/팔레트 → 흰 배경 합성 후 RGB(JPEG 는 알파 미지원).
                img = img.convert("RGBA")
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
            img.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), Image.LANCZOS)
            out = _encode_jpeg(img)
    except PhotoValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 — 손상/미지원 이미지.
        raise PhotoValidationError(
            "이미지를 열 수 없습니다. 손상되지 않은 JPG·PNG·WEBP 파일인지 확인하세요."
        ) from exc

    return out, OUTPUT_EXT, OUTPUT_CONTENT_TYPE


def _encode_jpeg(img) -> bytes:
    """JPEG 로 인코딩하되 ``TARGET_BYTES`` 초과 시 품질을 단계 하향한다(best-effort)."""
    from PIL import Image  # noqa: F401 — 지연 import(순수 모듈 유지)

    quality = JPEG_QUALITY
    best: bytes | None = None
    while quality >= _MIN_QUALITY:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
        best = buf.getvalue()
        if len(best) <= TARGET_BYTES:
            return best
        quality -= 10
    # 하한까지 낮춰도 목표 미달이면 마지막(가장 작은) 결과를 쓴다 — 하드 실패는 아니다
    # (상한 MAX_UPLOAD_BYTES 는 이미 통과했고, 목표는 권고치다).
    return best or b""


def _report_segment(report_id) -> str:
    """report_id 를 경로 세그먼트로 안전화한다(정수만 허용, 경로 주입 차단).

    report_id 는 서버가 조회한 보고서 식별자다. 그래도 방어적으로 정수 문자열만
    허용해 ``../`` 등 경로 조작 여지를 원천 차단한다."""
    s = str(report_id).strip()
    if not s or not s.isdigit():
        raise PhotoValidationError("보고서 식별자가 올바르지 않습니다.")
    return s


def build_object_path(report_id) -> str:
    """저장 경로를 서버가 생성한다: ``near-miss/{report_id}/{uuid}.jpg``.

    사용자 입력 파일명은 **경로에 쓰지 않는다**(경로 주입 불가). 파일명은 무작위
    uuid 로 대체하고 확장자는 정규화 산출물(JPEG)로 고정한다."""
    seg = _report_segment(report_id)
    return f"near-miss/{seg}/{uuid.uuid4().hex}.{OUTPUT_EXT}"


def is_owned_path(report_id, path: str) -> bool:
    """``path`` 가 해당 report_id 의 사진 경로 스킴에 속하는지 확인한다.

    삭제 시 다른 보고서/임의 경로의 객체를 지우지 못하게 하는 방어선이다."""
    try:
        seg = _report_segment(report_id)
    except PhotoValidationError:
        return False
    prefix = f"near-miss/{seg}/"
    p = str(path or "")
    return p.startswith(prefix) and "/" not in p[len(prefix):] and p.endswith(f".{OUTPUT_EXT}")
