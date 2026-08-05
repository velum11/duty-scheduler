#!/bin/sh
# PreToolUse hook (recon): enforce observation-only shell.
# recon may run git-read and version/dependency queries; it must never mutate the
# filesystem, git history, packages, or remote state. Use Read/Glob/Grep for files.
input=$(cat)
if printf '%s' "$input" | grep -qiE 'git[^&|;"]*\b(push|commit|merge|rebase|cherry-pick|reset|revert|clean|checkout|switch|stash|apply|am|mv|rm|tag[[:space:]]+-[df]|branch[[:space:]]+-[dDmM]|worktree|config[[:space:]]+(--global|--local)?[[:space:]]*[a-z])\b|>>|>[[:space:]]*[A-Za-z0-9._/~-]|(^|[^A-Za-z])(rm|mv|cp|mkdir|rmdir|touch|tee|dd|truncate|chmod|chown|ln|sed[[:space:]]+-i)([^A-Za-z]|$)|\b(pip3?|npm|npx|apt|apt-get|yum|brew|winget|choco|cargo|gem)\b[^|;"]*\b(install|uninstall|add|remove|update|upgrade|init|publish)\b|\b(apply_migration|supabase[^|;"]*db[^|;"]*push|migrate)\b|\bsudo\b|\bcurl\b[^|;"]*[[:space:]]-(o|O|d|T)|--data|--upload-file|\bwget\b[^|;"]*[[:space:]]-(O|o)'; then
  echo 'BLOCKED (recon read-only hook): recon shell is observation-only — git read (status/diff/log/show/branch/rev-parse) and version/dependency queries. File writes, git-history changes, installs, migrations, uploads, and destructive fs ops are not permitted. Use Read/Glob/Grep for files; report instead of mutating.' >&2
  exit 2
fi
exit 0
