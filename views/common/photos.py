"""아차사고 사진 썸네일 렌더 — views 공용 UI 헬퍼(U5).

조회·내 아차사고·평가 상세가 각자 복제하던 '서명 URL 썸네일 그리드'를 한 곳으로 합친다.
표시 URL 은 파사드(``db.get_near_miss_photo_url``)가 소유한다 — sample 은 data:URL, supabase
는 단기 서명 URL. 클릭 확대는 ``st.image`` 기본 전체화면 버튼을 쓴다(추가 배선 없음).

경로 정규화는 순수 모듈 ``views.common.photo_paths`` 가, 실제 저장/URL 은 ``modules.db`` 가
소유한다 — 이 모듈은 표시(렌더)만 담당하며 modules 를 건드리지 않는다(읽기 전용).
"""
from __future__ import annotations

from typing import Callable

import streamlit as st

from modules import db
from views.common.photo_paths import normalize_photo_paths


def render_photo_thumbs(
    photo_paths,
    *,
    cols: int = 3,
    key_prefix: str = "nm_thumb",
    delete_cb: Callable[[str], None] | None = None,
) -> int:
    """첨부 사진을 서명 URL 썸네일 그리드로 렌더하고 표시한 장수를 반환한다(없으면 0·무렌더).

    - 읽기 전용(조회·평가): ``delete_cb=None``.
    - 소유자 편집(내 아차사고): ``delete_cb`` 를 주면 각 셀 하단에 '삭제' 버튼을 그려 클릭 시
      ``delete_cb(path)`` 를 호출한다(권한·게이트·rerun 은 호출부 소관).
    """
    paths = normalize_photo_paths(photo_paths)
    if not paths:
        return 0
    columns = st.columns(cols)
    for i, path in enumerate(paths):
        with columns[i % cols]:
            url = db.get_near_miss_photo_url(path)
            if url:
                st.image(url, width="stretch")
            else:
                st.caption("사진을 불러올 수 없습니다.")
            if delete_cb is not None and st.button(
                "삭제", key=f"{key_prefix}_del_{i}", width="stretch"
            ):
                delete_cb(path)
    return len(paths)
