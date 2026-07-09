"""근무표 관리 — 근무표 등록/수정 화면."""
from modules import ui
from views import workspace


def render(user: dict) -> None:
    ui.page_header("schedule_edit")
    workspace.schedule_screen(user, "schedule_edit")
