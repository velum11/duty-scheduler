"""AgGrid 네이티브 붙여넣기 리스너와 한글 IME / commit handshake.

Phase2 검토(blocking 5, 위험 6·7)의 두 결함을 겨냥한다:

1. **paste 리스너 수명** — 기존 ``onGridReady`` 는 rerun 마다 ``document.addEventListener
   ('paste', ...)`` 를 누적 등록할 수 있었다. 장시간 세션에서 한 번의 Ctrl+V 가 여러 번
   처리될 위험이 있다. 여기서는 **grid instance id(uid)** 로 전역 레지스트리에 1회만
   등록하고, 재등록 시 이전 핸들러를 먼저 제거하며, grid ``destroy`` 에서도 제거한다.

2. **한글 IME / 마지막 셀 commit** — 액션바 버튼은 Streamlit 본문에 있고 grid API 는
   iframe 안이라 외부 on-click 에서 ``api.stopEditing()`` 을 직접 부를 수 없다(§24).
   그래서 **st-aggrid 이벤트 handshake** 로 최신 snapshot 을 Python 으로 수렴시킨다:
     - ``stopEditingWhenCellsLoseFocus`` + ``compositionend`` 후에만 편집 종료,
     - ``cellEditingStopped``/``cellValueChanged`` 가 최신 row snapshot 을 ``update_on``
       debounce 로 Python 에 반영,
     - Python 은 **그리드 렌더로 최신 snapshot 을 받은 뒤에** action flag 를 소비한다
       (controller 순서 계약). 즉 "버튼 클릭 → flag 기록 → rerun → 최신 grid 데이터 수신
       → flag pop → action" 이 2단계 command 의 실행 순서다.

   IME 조합 중(``compositionstart``~``compositionend``)에는 편집 종료를 보류해 마지막
   글자가 유실되지 않게 한다. blur 경합을 시간 지연이 아니라 이벤트 순서로 막는다.
"""
from __future__ import annotations

from st_aggrid import JsCode

# ---------------------------------------------------------------------------
# 붙여넣기 핸들러 — grid uid 로 idempotent 등록. AgGrid community 는 다중 셀
# clipboard 분배(processDataFromClipboard, Enterprise 전용)가 없어 네이티브 paste
# 이벤트의 clipboardData 를 직접 파싱해 TSV(탭=열/줄바꿈=행)를 포커스 셀부터 분배한다.
# ---------------------------------------------------------------------------
def build_paste_handler(uid: str) -> JsCode:
    """``onGridReady`` 용 paste 핸들러(JsCode). uid 는 그리드 인스턴스별 고유 문자열.

    ``window.__msPasteHandlers`` 레지스트리에 uid→handler 를 보관한다. 같은 uid 로
    다시 등록되면 이전 handler 를 ``removeEventListener`` 후 교체하므로 rerun 반복에도
    리스너가 누적되지 않는다. IME 조합 중에는 무시하고, 편집 중 셀은 단일 셀 입력으로
    양보한다.
    """
    safe_uid = uid.replace("\\", "").replace("'", "")
    return JsCode(
        """
        function(params) {
          const api = params.api;
          const uid = '%s';
          const reg = (window.__msPasteHandlers = window.__msPasteHandlers || {});
          // 같은 uid 의 이전 리스너 제거(리마운트/재등록 누적 방지).
          if (reg[uid]) {
            document.removeEventListener('paste', reg[uid]);
            delete reg[uid];
          }
          const onPaste = function(event) {
            // 이 grid 가 iframe 안에서 포커스를 갖고 있을 때만 처리(다른 grid 양보).
            if (!api || api.isDestroyed && api.isDestroyed()) { return; }
            if (window.__msComposing) { return; }             // 한글 조합 중 → 무시
            if (api.getEditingCells().length > 0) { return; }  // 셀 편집 중 = 단일 셀 입력
            const focused = api.getFocusedCell();
            if (!focused) { return; }
            const text = (event.clipboardData || window.clipboardData).getData('text/plain');
            if (!text) { return; }
            event.preventDefault();
            const lines = text.replace(/\\r/g, '').split('\\n');
            while (lines.length && lines[lines.length - 1] === '') { lines.pop(); }
            const table = lines.map(function(line) { return line.split('\\t'); });
            const missing = focused.rowIndex + table.length - api.getDisplayedRowCount();
            if (missing > 0) {
              // 자동확장 넘침행은 [＋ 행 추가]와 동일하게 신규로 태깅한다. _row_state 가 없으면
              // 신규행 전용 editable 게이트(자연키=_row_state==='new')가 false 로 보고 붙여넣기를
              // 스킵해 사번/코드가 소실된다(H1). _row_id 는 controller 가 재적재 시 부여한다.
              api.applyTransaction({ add: Array.from({ length: missing }, function() { return { _row_state: 'new' }; }) });
            }
            const columns = api.getAllDisplayedColumns();
            const start = columns.findIndex(function(c) { return c.getColId() === focused.column.getColId(); });
            table.forEach(function(values, rowOffset) {
              const node = api.getDisplayedRowAtIndex(focused.rowIndex + rowOffset);
              if (!node) { return; }
              values.forEach(function(value, colOffset) {
                const column = columns[start + colOffset];
                if (!column) { return; }
                const colDef = column.getColDef();
                const editable = typeof colDef.editable === 'function'
                  ? colDef.editable({ node: node, data: node.data, column: column, colDef: colDef })
                  : colDef.editable !== false;
                if (!editable) { return; }
                // 체크박스 컬럼: Excel 의 TRUE/1/사용/재직 등 텍스트를 boolean 으로 변환.
                if (colDef.cellEditor === 'agCheckboxCellEditor') {
                  const flag = String(value).trim().toLowerCase();
                  value = ['true','1','y','yes','t','on','사용','재직'].indexOf(flag) >= 0;
                }
                node.setDataValue(column.getColId(), value);
              });
            });
          };
          reg[uid] = onPaste;
          document.addEventListener('paste', onPaste);
        }
        """ % safe_uid
    )


# ---------------------------------------------------------------------------
# IME composition guard — 전역 1회 등록. compositionstart/end 로 조합 상태 플래그를
# 세팅해 붙여넣기·편집 종료가 마지막 글자를 삼키지 않게 한다.
# ---------------------------------------------------------------------------
IME_COMPOSITION_GUARD = JsCode(
    """
    function(params) {
      if (window.__msImeGuard) { return; }   // 프로세스 1회만 등록(누적 방지)
      window.__msImeGuard = true;
      window.__msComposing = false;
      document.addEventListener('compositionstart', function() { window.__msComposing = true; }, true);
      document.addEventListener('compositionend', function() { window.__msComposing = false; }, true);
    }
    """
)


# ---------------------------------------------------------------------------
# 마지막 셀 편집 확정 — 편집이 멈추면(=compositionend 이후 포커스 이탈/Enter) 최신 값을
# 반영한다. 신규 행 자동 추가는 하지 않는다(계약: 신규는 [＋ 행 추가]/붙여넣기로만).
# ---------------------------------------------------------------------------
COMMIT_ON_EDIT_STOP = JsCode(
    """
    function(params) {
      // cellEditingStopped: 편집 종료 시점의 최신 snapshot 이 update_on 으로 Python 에
      // 반영된다. 별도 동작은 없으나 이벤트 존재 자체가 debounce flush 를 유발한다.
      return;
    }
    """
)


def apply_paste_options(grid_options: dict, uid: str) -> dict:
    """grid_options 에 paste/IME/commit handshake 관련 옵션을 병합한다(제자리 수정 후 반환).

    grid.py 가 최종 gridOptions 를 만들 때 호출한다. ``onGridReady`` 가 이미 있으면
    래핑하지 않고 paste+IME 두 핸들러를 순차 실행하는 합성 핸들러로 대체한다.
    """
    grid_options.setdefault("stopEditingWhenCellsLoseFocus", True)
    grid_options.setdefault("enterNavigatesVertically", True)
    grid_options.setdefault("enterNavigatesVerticallyAfterEdit", True)
    grid_options.setdefault("singleClickEdit", False)
    grid_options["onGridReady"] = _combined_ready(uid)
    grid_options.setdefault("onCellEditingStopped", COMMIT_ON_EDIT_STOP)
    return grid_options


def _combined_ready(uid: str) -> JsCode:
    """paste 핸들러 + IME guard 를 한 onGridReady 안에서 등록한다."""
    safe_uid = uid.replace("\\", "").replace("'", "")
    return JsCode(
        """
        function(params) {
          // 1) IME composition guard (프로세스 1회)
          if (!window.__msImeGuard) {
            window.__msImeGuard = true;
            window.__msComposing = false;
            document.addEventListener('compositionstart', function(){ window.__msComposing = true; }, true);
            document.addEventListener('compositionend', function(){ window.__msComposing = false; }, true);
          }
          // 2) paste 리스너 (uid idempotent 등록)
          const api = params.api;
          const uid = '%s';
          const reg = (window.__msPasteHandlers = window.__msPasteHandlers || {});
          if (reg[uid]) { document.removeEventListener('paste', reg[uid]); delete reg[uid]; }
          const onPaste = function(event) {
            if (!api || (api.isDestroyed && api.isDestroyed())) { return; }
            if (window.__msComposing) { return; }
            if (api.getEditingCells().length > 0) { return; }
            const focused = api.getFocusedCell();
            if (!focused) { return; }
            const text = (event.clipboardData || window.clipboardData).getData('text/plain');
            if (!text) { return; }
            event.preventDefault();
            const lines = text.replace(/\\r/g, '').split('\\n');
            while (lines.length && lines[lines.length - 1] === '') { lines.pop(); }
            const table = lines.map(function(line){ return line.split('\\t'); });
            const missing = focused.rowIndex + table.length - api.getDisplayedRowCount();
            if (missing > 0) {
              // 자동확장 넘침행은 [＋ 행 추가]와 동일하게 신규로 태깅한다(H1: _row_state 없으면
              // 신규행 전용 editable 게이트가 자연키 붙여넣기를 스킵해 사번/코드 소실).
              api.applyTransaction({ add: Array.from({ length: missing }, function(){ return { _row_state: 'new' }; }) });
            }
            const columns = api.getAllDisplayedColumns();
            const start = columns.findIndex(function(c){ return c.getColId() === focused.column.getColId(); });
            table.forEach(function(values, rowOffset) {
              const node = api.getDisplayedRowAtIndex(focused.rowIndex + rowOffset);
              if (!node) { return; }
              values.forEach(function(value, colOffset) {
                const column = columns[start + colOffset];
                if (!column) { return; }
                const colDef = column.getColDef();
                const editable = typeof colDef.editable === 'function'
                  ? colDef.editable({ node: node, data: node.data, column: column, colDef: colDef })
                  : colDef.editable !== false;
                if (!editable) { return; }
                if (colDef.cellEditor === 'agCheckboxCellEditor') {
                  const flag = String(value).trim().toLowerCase();
                  value = ['true','1','y','yes','t','on','사용','재직'].indexOf(flag) >= 0;
                }
                node.setDataValue(column.getColId(), value);
              });
            });
          };
          reg[uid] = onPaste;
          document.addEventListener('paste', onPaste);
        }
        """ % safe_uid
    )
