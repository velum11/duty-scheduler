# Duty Test Selection — evals

Document-based evals (no execution harness yet). Each case is judged by reading
the agent's plan, commands, and report against the checklist. Keep cases aligned
with `references/test-map.md`; if that map or the `scripts/test_*.py` inventory
changes, revisit the expected test names here.

---

## Case 1 — Minimal tests for a single-view change

### Scenario
A rendering-only edit to one screen (the near-miss view): a column label and
column order change in the near-miss list. No shared module, repository,
validator, route registration, or schema is touched.

### Input request (verbatim)
"I reordered the columns in the near-miss list view and renamed the 'Status'
header to 'Progress' in the near-miss screen. Nothing else changed. Which tests
should I run before I call this done?"

### Expected behavior checklist (observable)
- Consults `references/test-map.md` instead of guessing tests from filenames.
- Maps the change to the near-miss screen area and selects
  `scripts/test_near_miss_view.py` as the narrowest relevant test.
- Runs the narrowest test first; only escalates to
  `scripts/test_near_miss_data.py` if a data path is actually touched, and says
  so explicitly if it does not run it.
- Includes a Python syntax/compile check for the changed file and
  `git diff --check` for the source edit.
- Adds browser or `$pixel-qa` verification because the change is
  rendering-dependent, and states the viewport and mode.
- Does NOT run the full regression suite, nor unrelated master/schedule tests,
  nor the other near-miss tests (`pdf`, `photos`, `ui_gates`,
  `error_surfacing`, `improvement`) that the map does not list for this area.
- Report lists exact commands, pass/fail counts, skipped checks with reasons,
  and remaining risk.

### Failure criteria
Fails if it selects tests by filename guessing without consulting the map; runs
the full suite or unrelated areas for a single-view change; omits the
compile/`git diff --check` step; skips rendering verification for a visual
change; names a test that does not exist under `scripts/`; or weakens an
assertion to make the change pass.

---

## Case 2 — Expansion judgment for a shared-module change

### Scenario
A change to the shared screen scaffold/archetype module that several master
views build on. The change alters shared layout behavior, so it can affect every
consuming view.

### Input request (verbatim)
"I refactored the shared screen scaffold so the header actions render through a
new helper. The user master, org master, and work-type master screens all use
this scaffold. What's the right test scope — do I need to run everything?"

### Expected behavior checklist (observable)
- Consults `references/test-map.md` and identifies the scaffold row:
  `scripts/test_screen_scaffold.py` plus each affected view contract.
- Traces the actual importers/consumers of the changed module rather than
  assuming, per the map's shared-module note.
- Runs `scripts/test_screen_scaffold.py` and the focused contract of each
  traced consumer (e.g., `scripts/test_master_users_new.py`,
  `scripts/test_master_org_new.py`, `scripts/test_master_work_types_new.py`,
  and `scripts/test_master_unified.py` if the trace confirms them).
- Explicitly justifies the scope and any expansion before or while expanding,
  rather than running the full suite solely because a shared file changed.
- Includes the compile check and `git diff --check`; adds browser or `$pixel-qa`
  verification if the scaffold affects rendering, interaction, or AG Grid.
- Report lists exact commands, pass/fail counts, the import trace that justified
  scope, and remaining risk.

### Failure criteria
Fails if it runs the full regression suite solely because a shared file changed
(no import tracing); runs only `test_screen_scaffold.py` while ignoring affected
consumers; expands scope without justification; references tests absent from
`scripts/`; or weakens an assertion to make the change pass.
