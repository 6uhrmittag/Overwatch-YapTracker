#!/usr/bin/env bash
# PostToolUse hook (Edit|Write): lint + format-check only the edited .py file.
# Never modifies files. On findings, exit 2 so Claude sees them and fixes them now
# instead of in CI. F401/F841 are skipped: mid-edit an import is often added before its use.
f=$(jq -r '.tool_input.file_path // empty')
[[ "$f" == *.py && -f "$f" ]] || exit 0
ruff="$CLAUDE_PROJECT_DIR/.venv/bin/ruff"
[[ -x "$ruff" ]] || ruff=$(command -v ruff) || exit 0
lint=$("$ruff" check --quiet --ignore F401,F841 "$f" 2>&1); l=$?
fmt=$("$ruff" format --check --quiet "$f" 2>&1); r=$?
(( l == 0 && r == 0 )) && exit 0
echo "ruff found problems in $f (formatting: run 'ruff format $f'):" >&2
printf '%s\n%s\n' "$lint" "$fmt" >&2
exit 2
