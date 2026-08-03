# Duty ERP UI — Evals

Document-based evaluation cases for the `duty-erp-ui` skill. No execution harness:
a reviewer reads the agent transcript for a case and scores it against the observable
checklist. Each case has four parts — Scenario, Input (verbatim user request), Expected
behavior (observable items only), Fail criteria. Keep cases small; add more only when a
real gap appears.

---

## Case 1 — Structural decision for a new screen (Stage 0 gate)

**Scenario**
A new workops screen is requested that has no existing view file. This is
UI_CENTRIC structural work (area order, archetype, list-detail split), so the Stage 0
page-composition design must precede any implementation.

**Input (verbatim user request)**
> "결재 대기 목록과 상세를 한 화면에서 처리하는 새 결재함 화면을 만들어줘. 심사자가
> 여러 건을 빠르게 훑고 반려/승인하는 흐름이야."

**Expected behavior (observable)**
- [ ] Reads required context before proposing structure: `AGENTS.md`, `CLAUDE.md`,
      relevant `DESIGN.md` sections, and `views/common/scaffold.py::ARCHETYPES`.
- [ ] Produces a Stage 0 handoff in conversation/task text covering all six steps: intent
      (3 questions), single focal point, declared §0.6 density targets, reuse of existing
      widgets/kit, per-component checkpoint, and interactive states.
- [ ] Names one focal point for the view (the primary review verb), not several.
- [ ] Cites §0.6 locked density values as numeric targets (e.g. detail ≥600px, condition
      panel ≤96px) rather than vague adjectives like "clean" or "modern".
- [ ] Proposes reusing the neutral scaffold / `views/common/erp/` kit before any one-off
      widget or local CSS; if the kit lacks a capability, proposes a kit extension.
- [ ] Obtains user approval (or a runnable/static mockup) before editing a production view.
- [ ] Does not touch product code, run migrations, or use live writes.

**Fail criteria**
- Edits or creates a production view before completing Stage 0 or getting approval.
- Skips the focal-point / density-target steps, or justifies layout only with
  decorative-marketing language.
- Introduces hero blocks, promotional cards, gradients, or oversized typography.
- Invents design values from outside `DESIGN.md`/`ARCHETYPES` instead of citing them.

---

## Case 2 — Density improvement on an existing screen

**Scenario**
An existing, approved screen works but feels loose. The user wants a density/scanability
improvement without changing data, filters, actions, or navigation.

**Input (verbatim user request)**
> "이 근무표 화면이 너무 헐렁해. 스크롤 없이 한눈에 더 많이 보이게 밀도를 올려줘.
> 기능이나 저장 동작은 그대로 두고."

**Expected behavior (observable)**
- [ ] Inspects the target view, its route, shared modules, tests, and a current rendered
      baseline before editing.
- [ ] Treats scope as visual density only; preserves existing data, filters, actions,
      save semantics, and navigation.
- [ ] Reuses existing tokens/kit spacing rather than adding fragile CSS selectors or
      one-off widgets.
- [ ] Keeps action hierarchy intact (page actions, grid actions, save state, destructive
      actions remain distinct).
- [ ] Verifies AG Grid / iframe / rerun-managed surfaces by their actual rendered
      geometry, not assumed values.
- [ ] Runs the focused screen contracts / `$duty-test-selection` tests and uses
      `$pixel-qa` for rendered geometry, overflow, clipping, and state checks.
- [ ] Reports preserved behavior, changed behavior, visual checks, and anything not
      verified.

**Fail criteria**
- Alters data, filters, actions, save behavior, or navigation not in scope.
- Increases density via fragile selectors or hard-coded pixel hacks instead of tokens/kit.
- Claims a visual result without inspecting actual rendered geometry.
- Skips focused tests, or reports "done" with no statement of what was and was not verified.
