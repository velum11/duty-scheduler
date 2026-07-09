"""근무표 관리 — 전체 근무표 조회 화면."""
from modules import ui
from views import workspace


def render(user: dict) -> None:
    ui.page_header("schedule_view")
    workspace.schedule_screen(user, "schedule_view")
