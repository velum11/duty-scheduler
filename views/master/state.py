"""기준정보 화면의 page-scoped 편집 상태 · key factory · dirty draft 정책.

Phase2 검토(blocking 1·2)의 두 결함을 제거하기 위한 단일 계약이다:
  - **공용 ``ms_*`` action key 누수**: 세 화면이 ``ms_add_req`` 등을 공유해 route 이동
    후 stale flag 가 다른 화면에서 소비될 수 있었다. ``DraftState`` 는 모든 세션 key 를
    ``{page_id}:...`` 로 스코프해 화면을 고립시킨다.
  - **dirty draft 무경고 소실**: filter/refresh/navigation/delete 시 무조건 재적재해
    미저장 편집을 폐기했다. ``resolve_reload`` 는 dirty 일 때 폐기 대신 확인을 요구한다.

이 모듈은 순수 세션/문자열 로직만 담는다(그리드·DB 없음) — scripts 단위 테스트 대상.
"""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

# resolve_reload 결정값 — controller 가 이 값으로 재적재/확인/보존을 분기한다.
RELOAD = "reload"   # 안전하게 재적재해도 됨(dirty 아님)
CONFIRM = "confirm"  # dirty — 폐기 확인 바를 먼저 통과해야 함
KEEP = "keep"       # 변경 없음 — 현재 draft 유지


@dataclass(frozen=True)
class DraftState:
    """한 화면(또는 조직 좌/우 패널)의 세션 key 를 발급·조작하는 얇은 어댑터.

    page_id 예: ``master_users``, ``master_work_types``, ``org_dept``, ``org_unit``.
    같은 page_id 를 공유하는 화면은 없으므로 key 충돌이 원천 차단된다.
    """

    page_id: str

    # ---- key factory (계약: {page_id}:query/:rows/:nonce/:rid/:delete_plan/:dirty) ----
    def key(self, suffix: str) -> str:
        return f"{self.page_id}:{suffix}"

    @property
    def query_key(self) -> str:
        return self.key("query")

    @property
    def rows_key(self) -> str:
        return self.key("rows")

    @property
    def nonce_key(self) -> str:
        return self.key("nonce")

    @property
    def rid_key(self) -> str:
        return self.key("rid")

    @property
    def delete_plan_key(self) -> str:
        return self.key("delete_plan")

    @property
    def dirty_key(self) -> str:
        return self.key("dirty")

    @property
    def flash_key(self) -> str:
        # 계약: flash:{page_id} (다른 key 와 접두사 네임스페이스 구분)
        return f"flash:{self.page_id}"

    @property
    def pending_query_key(self) -> str:
        return self.key("pending_query")

    def action_key(self, name: str) -> str:
        """action:{add|delete|save|refresh|...} 세션 flag key."""
        return self.key(f"action:{name}")

    # ---- action flag (액션바 on_click → controller pop) ----
    def request_action(self, name: str) -> None:
        """on_click 콜백에서 액션 의도를 기록한다(셀 blur 와 경합해도 다음 rerun 처리)."""
        st.session_state[self.action_key(name)] = True

    def action_requester(self, name: str):
        """Streamlit 버튼 ``on_click`` 에 넘길 콜백을 만든다."""
        key = self.action_key(name)
        return lambda: st.session_state.update({key: True})

    def take_action(self, name: str) -> bool:
        """액션 flag 를 소비(pop)한다 — 이 화면 scope 라 stale 누수가 없다."""
        return bool(st.session_state.pop(self.action_key(name), False))

    def clear_actions(self, *names: str) -> None:
        for name in names:
            st.session_state.pop(self.action_key(name), None)

    # ---- rows / nonce / rid ----
    def get_rows(self, default=None):
        return st.session_state.get(self.rows_key, default)

    def has_rows(self) -> bool:
        return self.rows_key in st.session_state

    def set_rows(self, frame) -> None:
        st.session_state[self.rows_key] = frame

    def nonce(self) -> int:
        return int(st.session_state.setdefault(self.nonce_key, 0))

    def bump_nonce(self) -> int:
        """그리드 key 를 바꿔 리마운트 — **성공 재조회·구조 변경 때만** 호출한다.

        오류/실패 후에는 호출하지 않는다(§25: nonce 리마운트로 draft 를 재적재하지 않음).
        """
        n = int(st.session_state.get(self.nonce_key, 0)) + 1
        st.session_state[self.nonce_key] = n
        return n

    def grid_key(self, suffix: str = "") -> str:
        """nonce 를 포함한 그리드 위젯 key. suffix 로 부서별 격리(조직 우패널) 가능."""
        base = f"{self.page_id}_grid"
        mid = f"_{suffix}" if suffix else ""
        return f"{base}{mid}_{self.nonce()}"

    def next_rid(self) -> str:
        """신규 행의 단조 증가 임시 id (``n:{k}``)."""
        n = int(st.session_state.get(self.rid_key, 0)) + 1
        st.session_state[self.rid_key] = n
        return f"n:{n}"

    # ---- dirty draft 정책 ----
    def set_dirty(self, value: bool) -> None:
        st.session_state[self.dirty_key] = bool(value)

    def is_dirty(self) -> bool:
        return bool(st.session_state.get(self.dirty_key, False))

    def query(self):
        return st.session_state.get(self.query_key)

    def query_changed(self, params) -> bool:
        return st.session_state.get(self.query_key) != params

    def commit_query(self, params) -> None:
        st.session_state[self.query_key] = params

    def resolve_reload(self, params, *, refresh: bool, dirty: bool) -> str:
        """filter/refresh/최초진입에서 재적재 여부를 결정한다(무경고 소실 금지).

        - 최초 진입(rows 없음) 또는 변경 없음(dirty=False)에서 조건 변화/refresh → ``RELOAD``.
        - **dirty 인데 조건 변화/refresh** → ``CONFIRM``: pending_query 를 보관하고 controller
          가 폐기 확인 바를 표시한다. 사용자가 폐기하면 ``apply_pending_reload`` 로 진행.
        - 그 외(조건 동일·dirty 아님·이미 로드됨) → ``KEEP``.
        """
        first_load = not self.has_rows()
        wants_reload = refresh or self.query_changed(params)
        if first_load:
            self.commit_query(params)
            return RELOAD
        if not wants_reload:
            return KEEP
        if not dirty:
            self.commit_query(params)
            return RELOAD
        # dirty + 재적재 요구 → 확인 게이트로 넘긴다(현재 draft 유지).
        st.session_state[self.pending_query_key] = params
        return CONFIRM

    def has_pending_reload(self) -> bool:
        return self.pending_query_key in st.session_state

    def apply_pending_reload(self):
        """폐기 확인 후: 보관한 pending_query 를 확정하고 반환한다."""
        params = st.session_state.pop(self.pending_query_key, None)
        if params is not None:
            self.commit_query(params)
        self.set_dirty(False)
        return params

    def cancel_pending_reload(self) -> None:
        """확인 취소: pending_query 를 버리고 현재 draft 를 유지한다."""
        st.session_state.pop(self.pending_query_key, None)

    # ---- flash (다음 rerun 1회 표시) ----
    def set_flash(self, kind: str, text: str) -> None:
        """kind: success|warning|error|info — style.banner 매핑으로 렌더한다."""
        st.session_state[self.flash_key] = (kind, text)

    def pop_flash(self):
        return st.session_state.pop(self.flash_key, None)

    # ---- 정리 ----
    def reset(self) -> None:
        """이 화면의 편집·조회·flag 세션 상태를 모두 제거한다(테스트/이탈 정리용)."""
        prefix = f"{self.page_id}:"
        for key in [k for k in st.session_state.keys()
                    if k.startswith(prefix) or k == self.flash_key]:
            st.session_state.pop(key, None)
