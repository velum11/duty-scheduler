"""근무표 관리 — 전체 근무표 조회 화면."""
# DESIGN.md §0 화면 유형 규약 — 조회형.
SCREEN_ARCHETYPE = "READ_VIEW"

from views import workspace
from views.common import scaffold


def render(user: dict) -> None:
    scaffold.page_chrome_for("schedule_view", SCREEN_ARCHETYPE, role=user.get("role"))
    workspace.schedule_screen(user, "schedule_view")
