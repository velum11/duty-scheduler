---
name: screen-design
description: Build, refine, or review workops Streamlit ERP screens while preserving domain behavior, dense data-entry usability, and the repository's current screen contracts. Use for any visual, layout, interaction, component, or styling change in views.
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
values come from `DESIGN.md` §1(토큰)/§2(화면 유형) and `views/common/scaffold.py::ARCHETYPES`,
never from this skill or any external system file.

1. **Intent (3 questions)**: who is this specific user (role, situation)? what verb must
   they accomplish here? what should it feel like, in words that mean something for a
   dense work tool (not "clean and modern")?
2. **One focal point per view**: name the single thing the user came to do; it must
   dominate through size, position, or surrounding space (the archetype's 골격 in §2 fixes
   the area order — do not invent a different one).
3. **Density declared up front**: pick the §1.4 density tier (cozy 44px+ / compact 34–38px /
   condensed 24–28px) that the archetype in §2 declares, before drawing anything. cozy and
   condensed never mix in one screen, and condensed is grid-tables only. Spacing values come
   from the §1.1 scale (4·8·12·16·24·32·40); the only sanctioned exception is data-density
   geometry (matrix cell, sticky identity column), which must carry a code comment saying why.
   Content-fit control widths; no full-width controls for short coded values.
4. **Use what exists**: native Streamlit widgets and the neutral kit
   (`views/common/erp/`) before any one-off widget or local CSS; if the kit lacks a
   capability, propose the kit extension rather than a screen-local workaround.
5. **Component checkpoint**: for each major component state why this component, how the
   hierarchy wins, and which existing token/pattern it reuses.
6. **States are not optional**: default/hover/active/focus/disabled for every
   interactive element; tabular-nums for dynamic numbers; hit targets follow the §1.4 tier —
   touch/cozy ≥44px, compact 34–38px, condensed 24–28px (grid tables only, not touch-operable).

Design output is a structured design brief in conversation/task text (an optional copy may be
saved under `.orca/artifacts/<task>/`; artifacts are reference only, never normative). Never
call this deliverable a "handoff" — in Orca, handoff means ownership transfer.
Small copy/menu/CSS-within-token fixes skip Stage 0 entirely.

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

For a design change to an existing screen's visuals, layout, or structure:

1. Capture the current rendered behavior and constraints.
2. Produce **3 side-by-side mockup variants** with representative sample data — data, approved elements, and functional contracts stay byte-for-byte fixed; diverge form only. Each variant is an isolated artifact (`.orca/artifacts/<task>/variant-N/` or a sample-mode render) that never share-edits the main checkout. Runnable live mockups are preferred; image/static concept mockups are allowed.
3. Present the variants and obtain the user's selection before editing the production view.
4. Implement only the selected variant, as a single Owner.
5. Compare the real rendered screen with the selected concept at the project's baseline viewport and relevant responsive sizes.

Use 2 variants for smaller changes that still leave a direction choice. Skip variants entirely and act directly for copy/menu wording, single color/token fixes that stay inside the §1 tokens, permission-unchanged route wiring, single-control alignment, or when the user already specified the exact result.

## Verification

- Run focused screen contracts and the tests selected by `$test-selection`.
- Use `$pixel-qa` for rendered geometry, overflow, clipping, contrast, and state checks.
- Confirm sample/mock mode first. Use real backends only under explicit user authorization and with writes disabled unless separately approved.
- Report preserved behavior, changed behavior, visual checks, and anything not verified.

## History

<details>
<summary>Policy provenance</summary>

- Artifact policy: optional copies of design briefs and concept mockups may be stored under `.orca/artifacts/<task>/` (or OS temp) as reference-only material; the authoritative output is always the conversation/task design-brief text.
</details>
