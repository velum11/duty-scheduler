---
name: duty-erp-ui
description: Build, refine, or review duty-scheduler Streamlit ERP screens while preserving domain behavior, dense data-entry usability, and the repository's current screen contracts. Use for any visual, layout, interaction, component, or styling change in views.
---

# Duty ERP UI

Treat UI work as product behavior, not decoration. Preserve existing data and write semantics unless the user explicitly requests a functional change.

## Required context

Before changing a screen:

1. Read `AGENTS.md`, `CLAUDE.md`, and the relevant sections of `DESIGN.md`.
2. Inspect the target view, its route, shared UI modules, tests, and a current rendered baseline.
3. Read `views/common/scaffold.py::ARCHETYPES` and the current screen manifest. If documentation and executable contracts disagree, report the mismatch rather than choosing silently.
4. Load `developing-with-streamlit` for Streamlit implementation guidance.
5. Load `frontend-design` only for explicit visual exploration or a substantial redesign, not for routine ERP maintenance.

## Stage 0 — page-composition design (before implementing a structural change)

For UI_CENTRIC structural work (area order, archetype, list-detail split, task flow,
navigation, shared kit, primary-action hierarchy), design the page composition first.
Procedure adapted from Dammyjay93/interface-design (MIT, Copyright (c) 2026 Damola
Akinleye; full notice in repository-root `THIRD_PARTY_NOTICES.md`) — procedure only; all
values come from `DESIGN.md` §0/§0.6 and `views/common/scaffold.py::ARCHETYPES`, never
from this skill or any external system file.

1. **Intent (3 questions)**: who is this specific user (role, situation)? what verb must
   they accomplish here? what should it feel like, in words that mean something for a
   dense work tool (not "clean and modern")?
2. **One focal point per view**: name the single thing the user came to do; it must
   dominate through size, position, or surrounding space (§0.3 area order).
3. **Density declared up front**: pick the §0.6 locked values (condition panel ≤2 rows/
   ≤96px, detail ≥600px, strip ≤72px, empty state one line, box cap) as design targets
   before drawing anything. Content-fit control widths; no full-width controls for short
   coded values.
4. **Use what exists**: native Streamlit widgets and the neutral kit
   (`views/common/erp/`) before any one-off widget or local CSS; if the kit lacks a
   capability, propose the kit extension rather than a screen-local workaround.
5. **Component checkpoint**: for each major component state why this component, how the
   hierarchy wins, and which existing token/pattern it reuses.
6. **States are not optional**: default/hover/active/focus/disabled for every
   interactive element; tabular-nums for dynamic numbers; hit targets — USER/touch 44px,
   desktop ERP interaction targets ≥32×32px (§0.6·§4).

Design output is a structured handoff in conversation/task text (an optional copy may be
saved under `.orca/artifacts/<task>/` — 2026-07-29 policy; artifacts are reference only,
never normative). Small copy/menu/CSS-within-token fixes skip Stage 0 entirely.

## Design and implementation rules

- Optimize for information density, scanability, edit safety, selection clarity, keyboard and mouse predictability, and consistency across related screens.
- Reuse the repository's neutral scaffold, ERP components, tokens, and lifecycle modules before adding local CSS or one-off widgets.
- Preserve approved navigation, data, filters, actions, and responsive behavior unless they are in scope.
- Avoid landing-page patterns such as hero blocks, promotional cards, gradients, oversized typography, decorative animation, or excess whitespace.
- Keep action hierarchy stable: page actions, grid actions, save state, and destructive actions must remain visually and behaviorally distinct.
- Do not use fragile CSS selectors when a shared component, theme token, or explicit hook can express the same rule.
- Treat AG Grid cells, Streamlit iframes, canvas-rendered widgets, and rerun state as framework-managed surfaces. Verify their actual rendered geometry.
- Never change production data, run migrations, or use live writes for visual verification.

## Visual-change workflow

For a structural redesign or when the user cannot judge a text-only proposal:

1. Capture the current rendered behavior and constraints.
2. Produce a small runnable mockup with representative sample data. Image/static concept mockups are also allowed (2026-07-29 artifact policy — store under `.orca/artifacts/<task>/`); a runnable live mockup remains preferred because the user judges the real render.
3. Obtain user approval before editing the production view.
4. Implement only the approved direction.
5. Compare the real rendered screen with the approved concept at the project's baseline viewport and relevant responsive sizes.

Skip the mockup gate for narrow fixes whose expected result is already unambiguous.

## Verification

- Run focused screen contracts and the tests selected by `$duty-test-selection`.
- Use `$pixel-qa` for rendered geometry, overflow, clipping, contrast, and state checks.
- Confirm sample/mock mode first. Use real backends only under explicit user authorization and with writes disabled unless separately approved.
- Report preserved behavior, changed behavior, visual checks, and anything not verified.
