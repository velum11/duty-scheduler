"""화면 유형 규약(DESIGN.md §0)의 공용 스캐폴드.

모든 신규 화면·구조 변경 화면은 4유형 중 하나를 ``SCREEN_ARCHETYPE`` 상수로
선언하고, 페이지 크롬은 크롬 손제작 없이 이 모듈의 :func:`page_chrome` 로만
생성한다(§0 집행 장치). 이 모듈은 ``views/master`` 공통 기반의 기존 공개 API
(:func:`~views.master.master_screen_head`, :func:`~views.master.inject_page_styles`
등)를 호출해 **헤더 크롬**(공용 CSS 주입 + 브레드크럼 + 제목/설명 + 배지 슬롯)만
렌더하며, 새 시각 요소를 만들지 않는다 — 표준 원본은 사용자 sign-off 를 받은
기준정보 3화면 스타일이다.

보장 범위(정직한 한계)
----------------------
이 모듈이 코드로 생성하는 것은 **헤더 크롬까지**다. 유형별 나머지 크롬(필터/조회
조건바·액션바·그리드·상태 스트립·지표 카드 등 §0 표의 "크롬 구성")의 **전체
순서·간격·대비**는 이 모듈이 코드로 강제하지 않는다. 그 전체 크롬 규약은 다음
3중 게이트로 지켜진다:

  1. 계약 테스트(``scripts/test_screen_scaffold.py``) — 유형 선언(AST)·크롬 실호출
     (Call 노드)·EDIT_GRID 전체 스택(헤더+그리드+액션/저장)의 존재를 우회 불가로
     검증한다. 단 "존재"까지이며 배치 순서·시각 품질은 판정하지 않는다.
  2. visual-qa 측정 — 실렌더 DOM/픽셀 지오메트리(정렬·잘림·대비율)를 수치로 측정.
  3. 사용자 실브라우저 sign-off — 최종 게이트.

따라서 이 스캐폴드가 "유형별 전체 크롬을 강제한다"고 주장하지 않는다. 헤더 크롬을
생성하고 유형 코드를 검증할 뿐이며, 나머지는 위 게이트로 보증된다.

이 모듈은 신규 화면이 표준 헤더 크롬만으로 시작하도록 하는 게 목적이며, 기존
화면을 이 함수로 이전하는 것은 별도 작업(Phase B)이다. 기존 렌더 경로를 여기서
바꾸지 않는다.
"""
from __future__ import annotations

from modules import db as _db
from modules import nav as _nav
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


def mode_badge() -> str:
    """현재 데이터 모드 배지 HTML(기준정보 화면과 동일한 샘플/연결 배지).

    ``master_users`` 등 기준정보 화면의 헤더 배지와 동일 계약을 재사용한다: sample
    모드면 '샘플 데이터', 아니면 'Supabase 연결'. readiness/health 신호는 섞지
    않는다(§5) — 이 배지는 데이터 모드(persistence 연결) 전용이다.
    """
    sample = _db.is_sample_mode()
    return _master.mode_badge_html(connected=(None if sample else True), sample=sample)


def page_chrome_for(page_id: str, archetype: str, *, role: str | None = None) -> str:
    """``page_id`` 의 표준 페이지 크롬(브레드크럼·제목·설명·모드 배지)을 렌더한다.

    브레드크럼·제목·설명은 ``modules/nav.py`` 의 실제 메뉴 그룹·라벨·설명에서
    도출해(예: ``근무표 › 근무표 편성``) 화면 간 표기를 단일 출처로 통일한다. 우측
    배지는 :func:`mode_badge` 로 기준정보 화면과 동일하게 노출한다. 유형별 나머지
    크롬(조회 조건바·액션바·그리드·지표 카드 등)은 각 화면이 §0 순서대로 이어서
    구성한다.

    Parameters
    ----------
    page_id:
        ``modules/nav.py`` 의 화면 id(예: ``"schedule_edit"``).
    archetype:
        :data:`ARCHETYPES` 중 하나. 허용 외 값이면 :class:`ValueError`.
    role:
        중복 page(그룹 여러 곳 소속)를 role 기준으로 해소한다(``nav.group_of``).
    """
    group = _nav.group_of(page_id, role)
    breadcrumb = f"{group['label']} › {_nav.page_label(page_id)}"
    return page_chrome(
        archetype,
        title=_nav.page_label(page_id),
        desc=_nav.page_desc(page_id),
        breadcrumb=breadcrumb,
        badges=mode_badge(),
    )


__all__ = ["ARCHETYPES", "page_chrome", "page_chrome_for", "mode_badge"]
