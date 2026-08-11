"""신규 화면 프로토타입 전용 로컬 파일 저장소(라우팅·Supabase 미연결).

이 모듈은 **프로토타입 화면(숙소 예약·업무요청서)만** 사용한다. 기존 데이터 경로
(``modules/db.py`` 파사드 · ``modules/sample_data.py``)를 건드리지 않으며, 반대로 이
저장소가 기존 화면에 노출되지도 않는다 — 라우팅·DB 연결은 후속 통합 작업 소관이다.

계약
----
- **시드**: ``data/sample/<name>.csv`` (읽기 전용. 앱은 시드 CSV 를 수정하지 않는다)
- **런타임**: ``.orca/artifacts/new-screens/state/<name>.json``
  사용자가 화면에서 입력·처리한 데이터가 여기 쌓여 브라우저 새로고침·앱 재시작에도
  유지된다. ``.orca/artifacts/`` 는 ``.gitignore`` 대상이라 커밋되지 않는다.
- 모든 값은 **문자열**로 보관한다(sample CSV 로딩과 동일 — ``dtype=str``). 숫자/날짜
  해석은 도메인 계층(``lodging_data`` · ``work_request_data``)이 담당한다.
- 쓰기는 임시파일 + ``os.replace`` 로 원자 교체한다(중간 상태 파일 방지).

환경변수 ``DUTY_PROTO_STATE_DIR`` 로 상태 디렉터리를 바꿀 수 있다 — 테스트가 임시
디렉터리로 격리해 실제 작업 상태를 오염시키지 않기 위한 훅이다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = ROOT / "data" / "sample"
DEFAULT_STATE_DIR = ROOT / ".orca" / "artifacts" / "new-screens" / "state"

#: 상태 디렉터리 재지정 환경변수(테스트 격리용).
STATE_DIR_ENV = "DUTY_PROTO_STATE_DIR"


def state_dir() -> Path:
    """런타임 상태 JSON 이 저장되는 디렉터리(환경변수 우선)."""
    raw = os.getenv(STATE_DIR_ENV)
    return Path(raw) if raw else DEFAULT_STATE_DIR


def state_path(name: str) -> Path:
    return state_dir() / f"{name}.json"


def seed_path(name: str) -> Path:
    return SEED_DIR / f"{name}.csv"


def seed_rows(name: str) -> list[dict]:
    """시드 CSV 를 문자열 dict 목록으로 읽는다(없으면 빈 목록)."""
    path = seed_path(name)
    if not path.exists():
        return []
    frame = pd.read_csv(path, dtype=str).fillna("")
    return [{k: str(v) for k, v in row.items()} for row in frame.to_dict("records")]


def load_rows(name: str) -> list[dict]:
    """런타임 상태를 읽는다. 상태 파일이 없으면 시드 CSV 로 최초 1회 생성한다.

    상태 파일이 깨졌으면(JSON 파싱 실패·형식 불일치) 조용히 시드로 되돌리지 않고
    :class:`ValueError` 를 올린다 — 오류를 샘플 데이터로 숨기지 않는다는 프로젝트
    계약과 같은 태도다. 복구는 :func:`reset` (화면의 '샘플 데이터로 초기화')로 한다.
    """
    path = state_path(name)
    if not path.exists():
        rows = seed_rows(name)
        save_rows(name, rows)
        return rows
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"프로토타입 상태 파일이 손상됐습니다: {path.name} ({exc})") from exc
    if not isinstance(data, list):
        raise ValueError(f"프로토타입 상태 파일 형식이 올바르지 않습니다: {path.name}")
    return [{str(k): ("" if v is None else str(v)) for k, v in row.items()} for row in data]


def save_rows(name: str, rows: list[dict]) -> None:
    """상태를 원자적으로 교체 저장한다(임시파일 → ``os.replace``)."""
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = [{str(k): ("" if v is None else str(v)) for k, v in row.items()} for row in rows]
    target = state_path(name)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, target)


def reset(name: str) -> list[dict]:
    """상태를 시드 CSV 로 되돌린다. 되돌린 행 목록을 반환한다."""
    rows = seed_rows(name)
    save_rows(name, rows)
    return rows


def reset_all(names: list[str]) -> None:
    for name in names:
        reset(name)


def to_frame(rows: list[dict], columns: list[str] | None = None) -> pd.DataFrame:
    """행 목록을 문자열 DataFrame 으로 만든다(빈 목록도 컬럼을 유지)."""
    if not rows:
        return pd.DataFrame(columns=list(columns or []), dtype=str)
    frame = pd.DataFrame(rows).fillna("").astype(str)
    if columns:
        for col in columns:
            if col not in frame.columns:
                frame[col] = ""
        frame = frame[list(columns)]
    return frame


__all__ = [
    "SEED_DIR", "DEFAULT_STATE_DIR", "STATE_DIR_ENV",
    "state_dir", "state_path", "seed_path", "seed_rows",
    "load_rows", "save_rows", "reset", "reset_all", "to_frame",
]
