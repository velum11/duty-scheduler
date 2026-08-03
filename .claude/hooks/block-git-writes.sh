#!/bin/sh
# PreToolUse hook (integrator): block history-writing git commands pending explicit user authorization.
input=$(cat)
if printf '%s' "$input" | grep -qiE 'git[^&|;"]*\b(push|commit|merge|rebase|cherry-pick|filter-branch)\b|git[^&|;"]*reset[^&|;"]*--hard|git[^&|;"]*\bclean\b|git[^&|;"]*worktree[^&|;"]*\b(add|remove|prune)\b'; then
  echo 'BLOCKED (integrator hook): commit/push/merge/rebase/cherry-pick/hard-reset/clean/history-rewrite/worktree changes require explicit user authorization (project AGENTS.md). Stop and report; do not retry or work around this block.' >&2
  exit 2
fi
exit 0
