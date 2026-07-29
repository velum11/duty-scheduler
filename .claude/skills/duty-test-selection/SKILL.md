---
name: duty-test-selection
description: Select and run proportionate verification for duty-scheduler changes. Use after implementation, during review, or when planning tests so focused contracts cover the affected behavior without unnecessary full regression or unsafe external writes.
---

# Duty Test Selection

Choose tests from changed behavior and call paths, not from filenames alone.

## Workflow

1. Inspect the diff and identify affected routes, views, shared components, repositories, validation, schema capability, and user roles.
2. Read `references/test-map.md`, then confirm candidate tests still exist and cover the changed behavior.
3. Run the narrowest relevant test first. Expand only when a shared dependency or failure indicates wider risk.
4. Always include syntax or compile checks for changed Python and `git diff --check` for source edits.
5. Add browser or `$pixel-qa` verification when behavior depends on rendering, interaction, responsive layout, or AG Grid.
6. Distinguish a product defect from a stale test. Never weaken an assertion merely to make a change pass.

## Safety

- Do not run real database writes, migrations, deployment, commit, push, or destructive cleanup as part of testing.
- Respect repository test flags and mock/sample modes.
- Do not run the full regression suite when the user limited the scope. Explain any justified expansion before or while doing it.
- Treat Streamlit bare-mode warnings as framework context unless the test demonstrates functional failure.

## Report

List exact commands, pass/fail counts, skipped checks and reasons, browser viewport and mode, and remaining risk. A test not run is not a pass.
