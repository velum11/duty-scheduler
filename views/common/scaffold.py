"""화면 유형 규약(DESIGN.md §0)의 공용 스캐폴드.

모든 신규 화면·구조 변경 화면은 4유형 중 하나를 ``SCREEN_ARCHETYPE`` 상수로
선언하고, 페이지 크롬은 크롬 손제작 없이 이 모듈의 :func:`page_chrome` 로만
생성한다(§0 집행 장치). 이 모듈은 ``views/master`` 공통 기반의 기존 공개 API
(:func:`~views.master.master_screen_head`, :func:`~views.master.inject_page_styles`
등)를 호출해 표준 크롬(공용 CSS 주입 + 브레드크럼 + 제목/설명 + 배지 슬롯)을
렌더할 뿐, 새 시각 요소를 만들지 않는다 — 표준 원본은 사용자 sign-off 를 받은
기준정보 3화면 스타일이다.

이 모듈은 신규 화면이 표준 크롬만으로 시작하도록 하는 게 목적이며, 기존 화면을
이 함수로 이전하는 것은 별도 작업(Phase B)이다. 기존 렌더 경로를 여기서 바꾸지
않는다.
"""
from __future__ import annotations

from views import master as _master

#: 강제되는 4개 화면 유형 코드(DESIGN.md §0 표와 1:1 대응).
ARCHETYPES: tuple[str, ...] = ("EDIT_GRID", "READ_VIEW", "MATRIX_EDIT", "DASHBOARD")


def _validate_archetype(archetype: str) -> str:
    """``archetype`` 이 허용 유형인지 검증하고 그대로 반환한다.

    허용 외 값이면 :class:`ValueError` 를 던진다(규약 밖 유형·임의 새 유형 차단 —
    DESIGN.md §0: "유형 밖 레이아웃·새 유형 추가는 사용자 명시 승인 + 규약
    개정으로만").
    """
    if archetype not in ARCHETYPES:
        raise ValueError(
            f"알 수 없는 화면 유형 {archetype!r} — 허용 유형: {', '.join(ARCHETYPES)}"
        )
    return archetype


def page_chrome(
    archetype: str,
    *,
    title: str,
    desc: str = "",
    breadcrumb: str | None = None,
    badges: str = "",
) -> str:
    """선언한 ``archetype`` 의 표준 페이지 크롬을 렌더하고 그 코드를 반환한다.

    공용 CSS 주입 + 브레드크럼 + 제목/설명 + 배지 슬롯까지의 표준 헤더를
    ``views/master`` 공개 API 로 렌더한다. 유형별 나머지 크롬(필터/조회 조건바·
    액션바·그리드·상태 스트립·지표 카드 등 — DESIGN.md §0 표의 "크롬 구성")은
    각 화면이 유형 규약 순서대로 이어서 구성한다.

    ``EDIT_GRID`` 화면은 이 헤더뿐 아니라 ``views/master`` 전체 스택
    (``DraftState`` · ``MasterGridSpec`` · ``run_save`` · ``master_action_bar``)을
    사용하는 것이 필수다 — 기준정보 3화면이 표준 원본이다.

    Parameters
    ----------
    archetype:
        :data:`ARCHETYPES` 중 하나. 허용 외 값이면 :class:`ValueError`.
    title:
        페이지 제목.
    desc:
        제목 하단 설명(선택).
    breadcrumb:
        브레드크럼 텍스트(선택). ``None`` 이면 브레드크럼을 렌더하지 않는다.
    badges:
        제목 우측 배지 슬롯에 넣을 신뢰된 HTML(예: ``mode_badge_html(...)`` 결과).
        데이터 모드 신호 전용이며 readiness/health 를 섞지 않는다(§5).

    Returns
    -------
    str
        검증을 통과한 ``archetype`` 코드.
    """
    _validate_archetype(archetype)
    _master.master_screen_head(
        title,
        desc,
        breadcrumb=breadcrumb,
        mode_badge=badges or None,
    )
    return archetype


__all__ = ["ARCHETYPES", "page_chrome"]
