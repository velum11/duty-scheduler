---
name: duty-data-contract
description: Analyze or change workops domain models, repositories, validators, authentication, Supabase readiness, and persistence behavior. Use whenever work can affect stored data, identities, relationships, lifecycle states, or sample-versus-live behavior.
---

# Duty Data Contract

Protect business data before optimizing implementation convenience.

## Required context

1. Read `AGENTS.md` as the safety source of truth.
2. Read the relevant current requirements and database documentation.
3. Trace the complete path: UI or API entry point, validation, data facade, repository, schema capability, and focused tests.
4. Describe capabilities by business meaning. Mention migration numbers only as evidence of the current repository state, never as the durable requirement.

## Contract checklist

- Identify authoritative IDs, natural keys, foreign keys, tenant or organization boundaries, and server-derived identity.
- Validate required fields, uniqueness, references, and state transitions before writes.
- Preserve fail-closed behavior when schema capability, authorization, or reference integrity is unknown.
- Handle partial, stale, missing, and unresolved records explicitly.
- Respect soft-delete and active/inactive semantics. Do not silently revive, merge, or discard records.
- Keep sample/mock mode and Supabase mode behaviorally aligned where the project promises parity.
- Do not infer readiness from a migration filename alone. Inspect the actual schema or capability probe through read-only paths.
- Protect write-enabled tests behind the repository's explicit test flags and isolation rules.

## Change rules

- Do not run or modify migrations, write to a live database, alter authentication state, or mutate reference data without explicit user approval.
- Do not fix a UI symptom by weakening repository validation or bypassing authorization.
- Prefer narrow compatibility adapters when old routes or callers must continue to work.
- Preserve unrelated uncommitted data and code changes.

## Verification and report

Use `$duty-test-selection` to choose focused tests. Report:

1. Contract being protected or changed
2. Evidence and affected call path
3. Validation and authorization behavior
4. Sample/live parity
5. Tests run and write-safety conditions
6. Unverified schema or production assumptions
