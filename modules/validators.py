"""근무표 편성/일별 근무 저장 전 검증 (순수 함수).

Repository(저장 계층)와 화면이 공통으로 사용한다. DataFrame·DB·Streamlit에
의존하지 않고 dict/집합 입력만 받으므로 단위 테스트가 쉽다.

검증 규칙 (docs/database.md §6.2):
- 직원별 월 편성 1건, 팀은 선택 부서 소속, 조 코드는 선택 부서의 활성 조에 존재
- 근무코드는 활성 근무형태에 존재, 근무일자는 편성 대상 월에 속함
- 하루 한 근무 (같은 사번·같은 날짜 중복 금지)
"""
from datetime import date


def normalize_schedule_month(value) -> str:
    """연-월 입력을 해당 월 1일 ISO 문자열('YYYY-MM-01')로 정규화한다.

    허용 입력: 'YYYY-MM', 'YYYY-MM-DD', date, (year, month) 튜플.
    해석할 수 없으면 ValueError.
    """
    if isinstance(value, date):
        return value.replace(day=1).isoformat()
    if isinstance(value, (tuple, list)) and len(value) == 2:
        year, month = int(value[0]), int(value[1])
        return date(year, month, 1).isoformat()
    text = str(value or "").strip()
    parts = text.split("-")
    if len(parts) in (2, 3):
        try:
            year, month = int(parts[0]), int(parts[1])
            return date(year, month, 1).isoformat()
        except ValueError:
            pass
    raise ValueError(f"대상 월 형식이 유효하지 않습니다: {value!r}")


def month_matches(duty_date: str, schedule_month: str) -> bool:
    """근무일자가 편성 대상 월(1일 정규화 값)과 같은 달인지 확인한다."""
    try:
        duty = date.fromisoformat(str(duty_date).strip())
        month = date.fromisoformat(str(schedule_month).strip())
    except ValueError:
        return False
    return (duty.year, duty.month) == (month.year, month.month)


def validate_assignment_records(
    records,
    emp_nos: set,
    dept_codes: set,
    team_keys: set,
    shift_keys: set,
):
    """월 편성 레코드 목록을 검증·정규화한다. (normalized, errors) 반환.

    records 각 항목: {emp_no, schedule_month, dept_code, team_code, shift_group_code}
    - emp_nos: 유효한 사번 집합
    - dept_codes: 유효한 부서코드 집합
    - team_keys: (dept_code, team_code) 유효 조합 집합
    - shift_keys: (dept_code, shift_code) 활성 조 조합 집합

    팀은 users 정책과 동일하게 미지정('')을 허용하고, 조 코드는 신규 저장 시
    필수다 (DB는 backfill 호환을 위해 NULL 허용 — docs/database.md §5.1).
    """
    normalized, errors = [], []
    seen = set()
    for i, record in enumerate(records, start=1):
        emp_no = str(record.get("emp_no") or "").strip()
        dept_code = str(record.get("dept_code") or "").strip()
        team_code = str(record.get("team_code") or "").strip()
        shift_code = str(record.get("shift_group_code") or "").strip()
        tag = f"{i}행" + (f"({emp_no})" if emp_no else "")

        try:
            schedule_month = normalize_schedule_month(record.get("schedule_month"))
        except ValueError:
            schedule_month = ""
            errors.append(f"{tag}: 대상 월 형식이 유효하지 않습니다: {record.get('schedule_month')!r}")

        if not emp_no:
            errors.append(f"{i}행: 사번을 입력하세요.")
        elif emp_no not in emp_nos:
            errors.append(f"{tag}: 등록되지 않은 사번입니다.")
        if dept_code not in dept_codes:
            errors.append(f"{tag}: 부서코드를 찾을 수 없습니다: {dept_code or '(빈 값)'}")
        elif team_code and (dept_code, team_code) not in team_keys:
            errors.append(f"{tag}: 선택한 부서에 없는 팀입니다: {team_code}")
        if not shift_code:
            errors.append(f"{tag}: 조 코드를 입력하세요.")
        elif dept_code in dept_codes and (dept_code, shift_code) not in shift_keys:
            errors.append(f"{tag}: 선택한 부서의 활성 조가 아닙니다: {shift_code}")

        key = (emp_no, schedule_month)
        if emp_no and schedule_month:
            if key in seen:
                errors.append(f"{tag}: 같은 직원의 같은 달 편성이 중복되었습니다: {schedule_month[:7]}")
            seen.add(key)

        normalized.append({
            "emp_no": emp_no,
            "schedule_month": schedule_month,
            "dept_code": dept_code,
            "team_code": team_code,
            "shift_group_code": shift_code,
        })
    return normalized, errors


def validate_schedule_records(records, emp_nos: set, work_codes: set, schedule_month: str | None = None):
    """일별 근무 레코드 목록을 검증한다. errors 목록 반환.

    records 각 항목: {emp_no, duty_date, work_type_code}
    - work_codes: 활성 근무코드 집합
    - schedule_month: 지정 시 근무일자가 해당 월에 속하는지 검사
    """
    errors = []
    seen = set()
    for i, record in enumerate(records, start=1):
        emp_no = str(record.get("emp_no") or "").strip()
        duty_date = str(record.get("duty_date") or "").strip()
        work_code = str(record.get("work_type_code") or "").strip()
        tag = f"{i}행" + (f"({emp_no})" if emp_no else "")

        if not emp_no:
            errors.append(f"{i}행: 사번을 입력하세요.")
        elif emp_no not in emp_nos:
            errors.append(f"{tag}: 등록되지 않은 사번입니다.")
        try:
            date.fromisoformat(duty_date)
        except ValueError:
            errors.append(f"{tag}: 근무일자 형식이 유효하지 않습니다: {duty_date or '(빈 값)'}")
            duty_date = ""
        if work_code not in work_codes:
            errors.append(f"{tag}: 활성 근무형태가 아닙니다: {work_code or '(빈 값)'}")
        if duty_date and schedule_month and not month_matches(duty_date, schedule_month):
            errors.append(f"{tag}: 근무일자가 편성 대상 월({schedule_month[:7]})에 속하지 않습니다: {duty_date}")

        key = (emp_no, duty_date)
        if emp_no and duty_date:
            if key in seen:
                errors.append(f"{tag}: 같은 직원의 같은 날짜 근무가 중복되었습니다: {duty_date}")
            seen.add(key)
    return errors
