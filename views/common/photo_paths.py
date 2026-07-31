"""아차사고 사진 경로(photo_paths) 표시용 정규화 — views 공용 헬퍼(순수·프레임워크 비의존).

파사드가 돌려주는 ``photo_paths`` 셀은 저장 백엔드에 따라 형태가 다를 수 있다:
list(정상), 문자열화된 JSON 배열(일부 직렬화 경로), NaN/빈 값(미첨부). 조회 화면과 내
아차사고 화면이 각자 같은 정규화를 중복 구현하던 것을 이 한 곳으로 합친다.

이 모듈은 **modules 를 건드리지 않는다**(데이터 계약은 data-contract 소관) — 표시 계층의
방어적 정규화만 담당한다. pandas 는 NaN 판정에만 쓰고, 없어도 동작하도록 방어한다.
"""
from __future__ import annotations

import json


def normalize_photo_paths(value) -> list[str]:
    """photo_paths 셀(list / tuple / 문자열화 JSON / NaN / 빈 값)을 경로 문자열 리스트로 정규화한다.

    - list/tuple: 공백 제거 후 비어있지 않은 항목만.
    - None / NaN / '[]' / 'nan' / 빈 문자열: 빈 리스트(미첨부).
    - 문자열화된 JSON 배열: 파싱해서 항목 추출(실패 시 사진 없음으로 취급).
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(p) for p in value if str(p).strip()]
    # pandas NaN 방어(설치돼 있을 때만 — 표시 계층이 pandas 부재에도 죽지 않도록).
    try:
        import pandas as pd
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    except Exception:  # noqa: BLE001 — pandas 미설치 등은 문자열 경로로 진행.
        pass
    s = str(value).strip()
    if not s or s in ("[]", "nan"):
        return []
    try:
        arr = json.loads(s)
        if isinstance(arr, list):
            return [str(p) for p in arr if str(p).strip()]
    except Exception:  # noqa: BLE001 — 파싱 실패는 사진 없음으로 취급.
        pass
    return []
