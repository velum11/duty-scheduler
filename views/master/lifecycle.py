"""저장 lifecycle 프로토콜 · persistence 결과 계약 · migration readiness 3-state.

Phase2 blocking 3·4·6 과 design-contract §22·§25 를 코드 계약으로 고정한다.

저장 프로토콜(§2 "validate → build merged candidate → domain validate → persist →
reload/flash")은 콜백 주입으로만 공유한다 — 화면별 validator/repository 를 하나의
범용 함수에 억지로 넣지 않는다. 핵심 불변식:
  - 저장 예외는 **controller 경계에서 처리**해 draft 를 보존하고 명시적 실패로 끝낸다.
  - 부분 성공은 ``PersistResult``(succeeded/failed keys)로만 표현한다. 성공 키만 store 에
    reconcile 하고 실패 키 draft/error 는 유지한다. **"전체 성공" 단정은 원자성 또는
    전 단계 확인 뒤에만.** 결과 불명(network/exception)은 별도 상태로 분리한다.
  - readiness 는 ``READY|NOT_READY|PROBE_ERROR`` 상호배타. NOT_READY 는 전 write 비활성.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

from views.master import style
from views.master.state import DraftState

# ---------------------------------------------------------------------------
# persistence 결과 계약 (§22) — repository/controller 가 반환, UI 는 이것만 읽는다.
# ---------------------------------------------------------------------------
@dataclass
class PersistResult:
    """단일 저장 명령의 결과. UI 는 결과를 추정하지 않고 이 값만 읽는다.

    - ``succeeded_keys``/``failed_keys``: 자연키(문자열/튜플) 목록.
    - ``error``: 실패/불명 사유(사용자 문구).
    - ``retryable``: 실패분 재시도 가능 여부.
    - ``unknown``: 결과 불명(succeeded/failed 를 알 수 없는 network/exception) — 전체
      성공으로 추정하지 않고 '재조회 필요'로 표기한다.
    """

    page_id: str
    succeeded_keys: list = field(default_factory=list)
    failed_keys: list = field(default_factory=list)
    error: str | None = None
    retryable: bool = False
    unknown: bool = False
    operation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def ok(self) -> bool:
        """모든 대상이 성공하고 실패/불명이 없을 때만 True(전체 성공 단정 조건)."""
        return not self.failed_keys and not self.unknown and self.error is None

    @property
    def partial(self) -> bool:
        return bool(self.succeeded_keys) and (bool(self.failed_keys) or self.unknown)

    @staticmethod
    def success(page_id: str, keys: list) -> "PersistResult":
        return PersistResult(page_id=page_id, succeeded_keys=list(keys))

    @staticmethod
    def failure(page_id: str, keys: list, error: str, *, retryable: bool = True) -> "PersistResult":
        return PersistResult(page_id=page_id, failed_keys=list(keys), error=error, retryable=retryable)

    @staticmethod
    def unresolved(page_id: str, error: str) -> "PersistResult":
        """결과 불명 — 전체 성공/실패 어느 쪽으로도 단정하지 않는다."""
        return PersistResult(page_id=page_id, error=error, unknown=True, retryable=True)


def _key_text(key) -> str:
    if isinstance(key, (tuple, list)):
        return "/".join(str(k) for k in key)
    return str(key)


def ledger_banner(result: PersistResult) -> None:
    """§22 저장 결과 원장 배너 — 성공/실패 키 칩 + 결과 불명 분리 표기.

    NOT_READY 화면에서는 write 자체가 차단되므로 호출하지 않는다(controller 책임).
    """
    if result.unknown:
        style.banner("danger", "결과 불명 · 재조회가 필요합니다.",
                     extra=f"<div class='keys'>{style.chip_html(result.error or '통신 오류', 'warn')}</div>")
        return
    if result.ok:
        n = len(result.succeeded_keys)
        style.banner("success", f"저장했습니다. (반영 {n}건)")
        return
    chips = []
    if result.succeeded_keys:
        chips.append(style.chip_html(f"저장 {len(result.succeeded_keys)}건", "ok"))
    for key in result.failed_keys:
        chips.append(style.chip_html(f"실패 {_key_text(key)}", "del"))
    extra = f"<div class='keys'>{''.join(chips)}</div>" if chips else ""
    msg = result.error or "일부 항목을 저장하지 못했습니다. 실패분은 유지됩니다."
    style.banner("danger" if not result.succeeded_keys else "warn", msg, extra=extra)


# ---------------------------------------------------------------------------
# 저장 프로토콜 — validate → build candidate → domain validate → persist → reconcile
# ---------------------------------------------------------------------------
@dataclass
class SaveOutcome:
    """run_save 반환. controller 가 reload/flash/원장 표시를 분기하는 데 쓴다."""

    status: str                       # "invalid" | "saved" | "partial" | "failed" | "unknown"
    errors: list = field(default_factory=list)
    result: PersistResult | None = None

    @property
    def should_reload(self) -> bool:
        """성공 재조회 대상 — 완전 성공일 때만 nonce 리마운트/재적재한다."""
        return self.status == "saved"


def run_save(
    state: DraftState,
    *,
    validate,          # () -> (records, errors) : 표시형→저장형 변환 + 행 검증
    build_candidate,   # (records) -> (merged, errors) : 자연키 병합 + 중복/구조 검증
    persist,           # (merged, records) -> PersistResult : 실제 write(예외 던져도 됨)
) -> SaveOutcome:
    """저장 단계를 순서대로 실행하고 실패를 controller 경계에서 흡수한다.

    - validate/build 단계 오류가 있으면 **persist 를 호출하지 않고** draft 를 유지한다
      (검증 실패는 재적재 없이 오류만 노출).
    - persist 예외는 여기서 잡아 ``PersistResult.unresolved`` 로 변환한다(draft 보존).
    - 반환 status 로 controller 가 reload(saved) / 원장(partial/unknown) / 오류(invalid/
      failed) 를 결정한다. 이 함수는 st.rerun / nonce 조작을 하지 않는다(부수효과 최소화).
    """
    records, errors = validate()
    if errors:
        return SaveOutcome(status="invalid", errors=list(errors))
    merged, build_errors = build_candidate(records)
    if build_errors:
        return SaveOutcome(status="invalid", errors=list(build_errors))
    try:
        result = persist(merged, records)
    except Exception as exc:  # noqa: BLE001 — controller 경계에서 draft 보존 목적
        return SaveOutcome(status="unknown",
                           result=PersistResult.unresolved(state.page_id, str(exc)))
    if result is None:  # 콜백이 결과를 안 주면 보수적으로 불명 처리
        return SaveOutcome(status="unknown",
                           result=PersistResult.unresolved(state.page_id, "저장 결과를 확인할 수 없습니다."))
    if result.ok:
        return SaveOutcome(status="saved", result=result)
    if result.unknown:
        return SaveOutcome(status="unknown", result=result)
    if result.partial:
        return SaveOutcome(status="partial", result=result)
    return SaveOutcome(status="failed", errors=[result.error or "저장에 실패했습니다."], result=result)


# ---------------------------------------------------------------------------
# migration readiness 3-state (§25, Codex B4)
# ---------------------------------------------------------------------------
class Readiness(str, Enum):
    READY = "READY"
    NOT_READY = "NOT_READY"
    PROBE_ERROR = "PROBE_ERROR"


@dataclass
class ReadinessState:
    """스키마 준비 상태(모드 배지와 분리). write control 활성/배너를 여기서 도출한다.

    현행 repository probe(``org_extensions_ready``)는 미적용과 probe 실패를 모두 False 로
    접는다(수정 금지 대상). 따라서 controller 가 probe 예외를 직접 잡을 수 있으면
    ``probe_error`` 를, 아니면 ``from_ready_flag`` 로 보수적 NOT_READY 를 만든다.
    """

    state: Readiness
    message: str = ""
    checked_at: float | None = None

    @staticmethod
    def ready() -> "ReadinessState":
        return ReadinessState(Readiness.READY)

    @staticmethod
    def not_ready(message: str = "migration 003 적용 전 — 조회만 가능합니다.") -> "ReadinessState":
        return ReadinessState(Readiness.NOT_READY, message)

    @staticmethod
    def probe_error(message: str = "스키마 상태 확인 실패 — 재확인이 필요합니다.") -> "ReadinessState":
        return ReadinessState(Readiness.PROBE_ERROR, message)

    @staticmethod
    def from_ready_flag(ready: bool, *, message: str | None = None) -> "ReadinessState":
        """boolean probe 결과를 3-state 로 승격한다(True→READY, False→NOT_READY).

        probe 실패(권한/네트워크)를 구분할 수 있는 controller 는 ``probe_error`` 를 직접
        쓴다 — 여기서 False 를 PROBE_ERROR 로 오표시하지 않는다.
        """
        if ready:
            return ReadinessState.ready()
        return ReadinessState.not_ready(message) if message else ReadinessState.not_ready()

    # ---- 파생 규칙 ----
    @property
    def write_enabled(self) -> bool:
        """add/edit/delete/save/retry 전체 활성 여부. READY 에서만 True."""
        return self.state is Readiness.READY

    @property
    def show_ledger(self) -> bool:
        """부분성공 원장 표시 허용 — NOT_READY/PROBE_ERROR 에서는 write 차단이라 금지."""
        return self.state is Readiness.READY

    def banner(self) -> None:
        """readiness 배너를 렌더한다(READY 는 배너 없음, 모드 배지만)."""
        if self.state is Readiness.NOT_READY:
            style.banner("warn", self.message)
        elif self.state is Readiness.PROBE_ERROR:
            style.banner("danger", self.message)

    def badge_html(self) -> str:
        return style.readiness_badge_html(self.state.value)
