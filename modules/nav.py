"""메뉴 정의 (데이터 기반) + 권한별 필터링 (DESIGN.md §6).

메뉴는 MENU_GROUPS 데이터로만 정의한다 — 새 업무 모듈(예: 원료 관리)을 추가할 때는
App Shell 코드를 바꾸지 않고 이 목록에 그룹/하위 메뉴 dict 만 추가한다.
렌더링(1차 아이콘 바, 2차 메뉴 패널, 헤더)은 modules/ui.py 의 app_shell 이 담당한다.

권한별 표시 (DESIGN.md §6.2):
- USER    대시보드 / 월간 근무표 / 내 근무표 + 아차사고(등록·내 아차사고·조회·분석) (전용 App Shell)
- MANAGER 대시보드 / 근무표 / 아차사고
- ADMIN   대시보드 / 근무표 / 아차사고 / 기준정보

능력(capability) 게이트 — DEPENDENCY-FREE 계약(중요)
---------------------------------------------------
일부 메뉴 항목은 role 문자열만으로 판정할 수 없고 '행위 능력'으로 노출된다(예:
아차사고 '평가 관리'는 ADMIN|MANAGER|안전담당자, 즉 auth.can_evaluate_near_miss).
이 모듈은 auth 를 import 하지 않는다(순환·결합 방지) — **호출부(app.py·modules/ui.py)가**
능력 집합(caps: set[str])을 계산해 넘긴다. 항목은 ``role in roles`` **또는**
``item["capability"] in caps`` 일 때 admit 된다. caps 미전달(None)이면 role 기준만
적용된다(하위호환 — 테스트가 role 만으로 호출하는 경로 보존).
"""

#: 능력 토큰(호출부가 auth.can_evaluate_near_miss(user) 결과를 이 토큰으로 담아 넘긴다).
#: 문자열 상수를 한곳에 두어 화면·shell·route guard 가 같은 이름을 쓰게 한다.
CAP_EVALUATE_NEAR_MISS = "evaluate_near_miss"

_MY_SCHEDULE = {
    "id": "my_schedule",
    "label": "내 근무표",
    "desc": "본인 근무를 월 단위로 확인합니다.",
}

# USER 전용 App Shell(반응형 상단 메뉴)의 평면 항목. 능력 게이트가 붙은 항목
# (평가 관리·개선조치 관리)은 caps 로만 노출된다 — user_menu(caps) 가 필터링한다.
# 안전담당자 USER 는 이 caps 항목들이 USER route guard(nav.allowed)로도 라우팅되게 한다.
USER_MENU = [
    {"id": "dashboard", "label": "대시보드", "icon": ":material/home:"},
    {"id": "schedule_view", "label": "월간 근무표", "icon": ":material/calendar_month:"},
    {"id": "my_schedule", "label": "내 근무표", "icon": ":material/person:"},
    {"id": "near_miss_submit", "label": "아차사고 등록", "icon": ":material/report:"},
    {"id": "near_miss_my", "label": "내 아차사고", "icon": ":material/inbox:"},
    {"id": "near_miss_evaluate", "label": "평가 관리", "icon": ":material/fact_check:",
     "capability": CAP_EVALUATE_NEAR_MISS},
    {"id": "near_miss_improvement", "label": "개선조치 관리", "icon": ":material/build:",
     "capability": CAP_EVALUATE_NEAR_MISS},
    {"id": "near_miss_view", "label": "아차사고 조회", "icon": ":material/search:"},
    {"id": "near_miss_stats", "label": "아차사고 분석", "icon": ":material/analytics:"},
]

# 아차사고 6개 항목은 근무표·기준정보처럼 **그룹**('아차사고 관리') 아래 자식으로 묶는다
# (그룹 헤더 + 자식 — 평면 아님, 사용자 정정). 노출은 **자식 단위**로 다르므로(base 4 는
# 전원, 평가 관리·개선조치는 능력) 각 자식에 자체 roles/capability 를 둔다.
# 그룹은 보이는 자식이 하나라도 있으면 노출된다(visible_groups 가 자식을 필터링한다).
_ALL_ROLES = ("USER", "MANAGER", "ADMIN")
_NEAR_MISS_GROUP = {
    "id": "near_miss",
    "label": "아차사고 관리",
    "icon": ":material/report:",
    # 그룹 roles 는 자식 union(전 역할) — 자식이 자체 규칙을 가지므로 실제 노출은 자식 단위.
    "roles": _ALL_ROLES,
    "children": [
        {
            "id": "near_miss_submit", "label": "아차사고 등록",
            "desc": "현장에서 발견한 아차사고를 접수 등록합니다.",
            "roles": _ALL_ROLES,
        },
        {
            "id": "near_miss_my", "label": "내 아차사고",
            "desc": "본인이 등록한 아차사고와 처리 상태를 확인합니다.",
            "roles": _ALL_ROLES,
        },
        {
            # 평가 관리 — 능력 게이트(평가자만). role 하드코딩 없이 capability 로만 노출한다.
            "id": "near_miss_evaluate", "label": "평가 관리",
            "desc": "등록된 아차사고를 검토하고 등급을 확정합니다.",
            "roles": (), "capability": CAP_EVALUATE_NEAR_MISS,
        },
        {
            # 개선조치 관리 — 평가 관리와 동일한 능력 게이트(평가자만). role 하드코딩 없이
            # capability 로만 노출한다(구 ADMIN 전용 → 안전담당자 USER 도 포함하도록 통일).
            "id": "near_miss_improvement", "label": "개선조치 관리",
            "desc": "아차사고 개선조치를 관리합니다.",
            "roles": (), "capability": CAP_EVALUATE_NEAR_MISS,
        },
        {
            "id": "near_miss_view", "label": "아차사고 조회",
            "desc": "아차사고 보고서를 조건별로 조회합니다.",
            "roles": _ALL_ROLES,
        },
        {
            "id": "near_miss_stats", "label": "아차사고 분석",
            "desc": "아차사고 분포와 추이를 분석합니다.",
            "roles": _ALL_ROLES,
        },
    ],
}

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
    _NEAR_MISS_GROUP,
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


def _as_caps(caps) -> set:
    """caps 인자를 집합으로 정규화한다(None → 빈 집합)."""
    return set(caps) if caps else set()


def _admits(spec: dict, role: str, caps) -> bool:
    """그룹/항목 spec 이 role 또는 능력으로 노출 대상인지.

    ``role in spec["roles"]`` **또는** ``spec["capability"] in caps`` 이면 True.
    """
    if role in spec.get("roles", ()):
        return True
    capability = spec.get("capability")
    return bool(capability and capability in _as_caps(caps))


def _child_admits(child: dict, group: dict, role: str, caps) -> bool:
    """자식 항목 노출 판정. 자식이 자체 규칙(roles/capability)을 가지면 그것으로,
    없으면 그룹 규칙을 상속한다 — 그룹 하나 안에서 항목별로 노출을 달리한다
    (예: '아차사고 관리' 아래 base 4=전원, 평가 관리·개선조치=능력)."""
    if "roles" in child or "capability" in child:
        return _admits(child, role, caps)
    return _admits(group, role, caps)


def _visible_children(group: dict, role: str, caps) -> list:
    return [c for c in group["children"] if _child_admits(c, group, role, caps)]


def visible_groups(role: str, caps=None) -> list:
    """role/능력으로 접근 가능한 메뉴 그룹 목록(자식은 노출 대상만 남겨 반환).

    그룹은 보이는 자식이 하나라도 있으면 노출된다. 자식 필터로 형태가 바뀐 그룹만
    새 dict 로 복제하고, 변형이 없으면 원본 그대로 반환한다(불필요한 사본 방지).
    caps(선택): 호출부가 계산한 능력 집합(예: {CAP_EVALUATE_NEAR_MISS}). 미전달 시
    role 기준만 적용한다(하위호환).
    """
    out = []
    for g in MENU_GROUPS:
        children = _visible_children(g, role, caps)
        if not children:
            continue
        out.append(g if children == g["children"] else {**g, "children": children})
    return out


def default_page(role: str, caps=None) -> str:
    """role 의 첫 화면 page id."""
    if role == "USER":
        return "my_schedule"
    groups = visible_groups(role, caps)
    return groups[0]["children"][0]["id"]


def user_menu(caps=None) -> list:
    """USER 전용 App Shell의 평면 메뉴 목록(능력 게이트 항목은 caps 로만 노출)."""
    caps = _as_caps(caps)
    return [
        item for item in USER_MENU
        if "capability" not in item or item["capability"] in caps
    ]


def group_of(page_id: str, role: str = None, caps=None) -> dict:
    """page id 가 속한 메뉴 그룹 dict. 중복 page는 role/능력 기준으로 찾는다.

    role 이 주어졌지만 능력 게이트로 caps 에 못 들어온 그룹(예: 평가 관리)이라도,
    브레드크럼 라벨은 필요하므로 마지막에 _PAGES 정적 매핑으로 폴백한다.
    """
    if role:
        for group in visible_groups(role, caps):
            if any(child["id"] == page_id for child in group["children"]):
                return group
    return _PAGES[page_id][0]


def page_label(page_id: str) -> str:
    return _PAGES[page_id][1]["label"] if page_id in _PAGES else page_id


def page_desc(page_id: str) -> str:
    return _PAGES[page_id][1].get("desc", "") if page_id in _PAGES else ""


def allowed(page_id: str, role: str, caps=None) -> bool:
    """role/능력이 해당 화면에 접근 가능한지 (앱 레벨 차단용).

    caps 를 넘기면 능력 게이트 화면(예: near_miss_evaluate)도 능력 보유 시 허용된다.
    메뉴 렌더와 route guard 가 동일 판정을 쓰도록, 두 곳 모두 같은 caps 를 넘겨야 한다.
    """
    if role == "USER":
        return any(item["id"] == page_id for item in user_menu(caps))
    return any(
        child["id"] == page_id
        for group in visible_groups(role, caps)
        for child in group["children"]
    )
