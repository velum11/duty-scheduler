"""화면 유형 규약(DESIGN.md §0) 집행용 공용 스캐폴드 패키지.

신규 화면은 크롬을 손제작하지 않고 이 패키지(``views.common.scaffold``)로만
표준 페이지 크롬을 생성한다. 4유형(EDIT_GRID/READ_VIEW/MATRIX_EDIT/DASHBOARD)
중 하나를 ``SCREEN_ARCHETYPE`` 으로 선언하고, ``page_chrome`` 으로 크롬을 연다.
"""
from views.common.scaffold import ARCHETYPES, page_chrome

__all__ = ["ARCHETYPES", "page_chrome"]
