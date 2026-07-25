"""기준정보 — 부서 관리 메뉴: 조직 관리 통합 화면(views/master_org)으로 연결한다.

부서 관리·조 관리는 하나의 조직 관리 화면(그룹·부서 + 운영단위)으로 통합되었다.
사이드바 메뉴 구조는 그대로 두고, 두 메뉴가 같은 화면을 연다.
"""
# DESIGN.md §0 화면 유형 규약 — 기준정보 편집형(위임 대상 master_org 와 동일).
SCREEN_ARCHETYPE = "EDIT_GRID"

from views import master_org


def render(user: dict) -> None:
    master_org.render(user)
