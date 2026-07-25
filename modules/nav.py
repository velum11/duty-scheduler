"""메뉴 정의 (데이터 기반) + 권한별 필터링 (DESIGN.md §6).

메뉴는 MENU_GROUPS 데이터로만 정의한다 — 새 업무 모듈(예: 원료 관리)을 추가할 때는
App Shell 코드를 바꾸지 않고 이 목록에 그룹/하위 메뉴 dict 만 추가한다.
렌더링(1차 아이콘 바, 2차 메뉴 패널, 헤더)은 modules/ui.py 의 app_shell 이 담당한다.

권한별 표시 (DESIGN.md §6.2):
- USER    대시보드 / 월간 근무표 / 내 근무표 (전용 App Shell)
- MANAGER 대시보드 / 근무표
- ADMIN   대시보드 / 근무표 / 기준정보
"""

_MY_SCHEDULE = {
    "id": "my_schedule",
    "label": "내 근무표",
    "desc": "본인 근무를 월 단위로 확인합니다.",
}

USER_MENU = [
    {
        "id": "dashboard",
        "label": "대시보드",
        "icon": ":material/home:",
    },
    {
        "id": "schedule_view",
        "label": "월간 근무표",
        "icon": ":material/calendar_month:",
    },
    {
        "id": "my_schedule",
        "label": "내 근무표",
        "icon": ":material/person:",
    },
    {
        "id": "near_miss_submit",
        "label": "아차사고",
        "icon": ":material/report:",
    },
]

MENU_GROUPS = [
    {
        "id": "home",
        "label": "홈",
        "icon": ":material/home:",
        "roles": ("MANAGER", "ADMIN"),
        "children": [
            {
                "id": "dashboard",
                "label": "대시보드",
                "desc": "오늘 근무 현황과 근무표 등록 현황을 확인합니다.",
            },
        ],
    },
    {
        "id": "schedule",
        "label": "근무표",
        "icon": ":material/calendar_month:",
        "roles": ("MANAGER", "ADMIN"),
        "children": [
            {
                "id": "schedule_edit",
                "label": "근무표 편성",
                "desc": "부서와 조를 선택하여 월별 근무표를 관리합니다.",
            },
            {
                "id": "schedule_view",
                "label": "월간 근무표",
                "desc": "부서와 조를 선택하여 월별 근무표를 조회합니다.",
            },
            _MY_SCHEDULE,
        ],
    },
    {
        "id": "near_miss",
        "label": "아차사고",
        "icon": ":material/report:",
        "roles": ("MANAGER", "ADMIN"),
        "children": [
            {
                "id": "near_miss_submit",
                "label": "신청",
                "desc": "현장에서 발견한 아차사고를 접수 신청합니다.",
            },
            {
                "id": "near_miss_evaluate",
                "label": "평가",
                "desc": "접수된 아차사고를 검토하고 등급을 확정합니다.",
            },
            {
                "id": "near_miss_view",
                "label": "조회",
                "desc": "아차사고 보고서를 조건별로 조회합니다.",
            },
            {
                "id": "near_miss_stats",
                "label": "집계",
                "desc": "등급·부서·기간·원인별 아차사고 분포를 집계합니다.",
            },
        ],
    },
    {
        "id": "master",
        "label": "기준정보",
        "icon": ":material/settings:",
        "roles": ("ADMIN",),
        "children": [
            {
                "id": "master_users",
                "label": "사용자 관리",
                "desc": "직원의 사번, 소속, 권한 정보를 관리합니다.",
            },
            {
                "id": "master_departments",
                "label": "부서 관리",
                "desc": "부서 코드와 명칭을 관리합니다.",
            },
            {
                "id": "master_teams",
                "label": "조 관리",
                "desc": "부서별 근무 조를 관리합니다.",
            },
            {
                "id": "master_work_types",
                "label": "근무형태 관리",
                "desc": "근무 코드와 표시 색상을 관리합니다.",
            },
        ],
    },
    {
        "id": "my",
        "label": "내 근무표",
        "icon": ":material/person:",
        "roles": ("USER",),
        "children": [_MY_SCHEDULE],
    },
]

# page id -> (group dict, page dict)
_PAGES = {c["id"]: (g, c) for g in MENU_GROUPS for c in g["children"]}


def visible_groups(role: str) -> list:
    """role 이 접근 가능한 메뉴 그룹 목록."""
    return [g for g in MENU_GROUPS if role in g["roles"]]


def default_page(role: str) -> str:
    """role 의 첫 화면 page id."""
    if role == "USER":
        return "my_schedule"
    groups = visible_groups(role)
    return groups[0]["children"][0]["id"]


def user_menu() -> list:
    """USER 전용 App Shell의 평면 메뉴 목록."""
    return USER_MENU


def group_of(page_id: str, role: str = None) -> dict:
    """page id 가 속한 메뉴 그룹 dict. 중복 page는 role 기준으로 찾는다."""
    if role:
        for group in visible_groups(role):
            if any(child["id"] == page_id for child in group["children"]):
                return group
    return _PAGES[page_id][0]


def page_label(page_id: str) -> str:
    return _PAGES[page_id][1]["label"] if page_id in _PAGES else page_id


def page_desc(page_id: str) -> str:
    return _PAGES[page_id][1].get("desc", "") if page_id in _PAGES else ""


def allowed(page_id: str, role: str) -> bool:
    """role 이 해당 화면에 접근 가능한지 (앱 레벨 차단용)."""
    if role == "USER":
        return any(item["id"] == page_id for item in USER_MENU)
    return any(
        child["id"] == page_id
        for group in visible_groups(role)
        for child in group["children"]
    )
