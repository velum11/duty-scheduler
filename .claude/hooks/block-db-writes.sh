#!/bin/sh
# PreToolUse hook (data-contract): block migration/live-DB write commands pending explicit user authorization.
input=$(cat)
if printf '%s' "$input" | grep -qiE 'supabase[^&|;"]*\bdb\b[^&|;"]*\bpush\b|apply_migration|test_supabase_crud|--confirm-test-project|psql[^&|;"]*(insert|update|delete|drop|alter|truncate)'; then
  echo 'BLOCKED (data-contract hook): migration execution and live-DB writes require explicit user authorization and project isolation flags (project AGENTS.md). Stop and report; do not retry or work around this block.' >&2
  exit 2
fi
exit 0
