"""GUARDED live bucket creation + one-shot storage smoke (test_project only).

Protection gates (ALL required, fail-closed):
  - env DUTY_SUPABASE_TEST_PROJECT truthy  (config.supabase_test_project_confirmed)
  - project ref must equal the approved test project
  - CLI flag --confirm-test-project

Does NOT touch the near_miss_reports table. Prints only non-secret data
(status codes / booleans / counts) — never the signed-URL token or keys.
"""
from __future__ import annotations

import io
import os
import sys
import urllib.request
import uuid

os.environ.setdefault("DUTY_DATA_MODE", "sample")
sys.path.insert(0, ".")

APPROVED_REF = "icvizwmqdffwsifmnwuk"
BUCKET = "near-miss-photos"
SMOKE_PREFIX = "near-miss/0"  # 정수 세그먼트(경로 스킴 정합) — DB 미접촉, 스토리지 전용

from modules import config  # noqa: E402
from modules import photo_storage as ps  # noqa: E402
from modules import supabase_repository as sr  # noqa: E402


def die(msg: str) -> None:
    print(f"ABORT: {msg}")
    raise SystemExit(2)


def main() -> int:
    if "--confirm-test-project" not in sys.argv:
        die("missing --confirm-test-project protection flag")
    if not config.supabase_test_project_confirmed():
        die("DUTY_SUPABASE_TEST_PROJECT not confirmed")
    url, _ = config.supabase_settings()
    ref = url.split("//", 1)[-1].split(".")[0]
    if ref != APPROVED_REF:
        die(f"project ref {ref!r} != approved test project")
    print(f"guards OK (ref={ref}, test_project=True, flag=True)")

    c = sr.client()

    # 1) create bucket (idempotent-ish: report if already exists).
    options = {"public": False, "allowed_mime_types": ["image/jpeg"],
               "file_size_limit": 2 * 1024 * 1024}
    try:
        res = c.storage.create_bucket(BUCKET, options=options)
        print(f"create_bucket: OK -> {res}")
    except Exception as exc:  # noqa: BLE001
        print(f"create_bucket raised (may already exist): {type(exc).__name__}: {str(exc)[:120]}")

    # verify bucket metadata (public flag).
    try:
        b = c.storage.get_bucket(BUCKET)
        pub = getattr(b, "public", None) if not isinstance(b, dict) else b.get("public")
        print(f"get_bucket: name-present, public={pub}")
    except Exception as exc:  # noqa: BLE001
        die(f"get_bucket failed: {type(exc).__name__}: {str(exc)[:120]}")

    # 2) 3-state probe -> READY (force re-probe, cache is per-process).
    sr.reset_near_miss_photo_bucket_readiness()
    probe = sr.near_miss_photo_bucket_probe(force=True)
    print(f"probe(after create): {probe}")
    if probe != sr.READINESS_READY:
        die(f"probe not READY: {probe}")

    # 3) guarded smoke: build a TEST marker JPEG, upload -> signed URL -> fetch 200 -> delete.
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (600, 400), (240, 240, 240))
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 590, 390], outline=(200, 60, 40), width=6)
    d.text((40, 180), "TEST SMOKE - DELETE ME", fill=(180, 40, 20))
    buf = io.BytesIO(); img.save(buf, format="PNG")
    data, ext, ctype = ps.validate_and_compress(buf.getvalue(), "smoke.png")
    print(f"marker compressed: ext={ext} ctype={ctype} bytes={len(data)} jpeg={ps.sniff_image_type(data)=='jpg'}")

    path = f"{SMOKE_PREFIX}/smoke-{uuid.uuid4().hex}.jpg"
    sr.upload_near_miss_photo_object(path, data, ctype)
    print("upload: OK")

    signed = sr.signed_near_miss_photo_url(path, expires_in=120)
    got_url = bool(signed and signed.startswith("http"))
    print(f"signed_url: obtained={got_url} (token redacted)")
    if not got_url:
        # cleanup before abort
        try: sr.remove_near_miss_photo_object(path)
        except Exception: pass
        die("failed to obtain signed URL")

    status = None; clen = None
    try:
        with urllib.request.urlopen(signed, timeout=20) as resp:
            status = resp.status
            body = resp.read()
            clen = len(body)
    except Exception as exc:  # noqa: BLE001
        print(f"fetch error: {type(exc).__name__}: {str(exc)[:120]}")
    print(f"fetch: status={status} bytes={clen} matches_upload={clen==len(data)}")

    # delete + verify empty restore.
    sr.remove_near_miss_photo_object(path)
    print("delete: OK")

    listing = c.storage.from_(BUCKET).list(SMOKE_PREFIX)
    remaining = [o.get("name") if isinstance(o, dict) else getattr(o, "name", None) for o in (listing or [])]
    # storage list may return a placeholder for empty folders; count real smoke objects.
    smoke_left = [n for n in remaining if n and str(n).startswith("smoke-")]
    print(f"post-delete list({SMOKE_PREFIX}): remaining_smoke_objects={len(smoke_left)}")

    ok = (status == 200 and clen == len(data) and not smoke_left)
    print(f"SMOKE_RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
