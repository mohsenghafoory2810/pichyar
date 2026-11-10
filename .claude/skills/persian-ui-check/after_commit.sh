#!/usr/bin/env bash
# Claude Code PostToolUse hook (Bash), registered in .claude/settings.json with asyncRewake:
# after a `git commit` it runs the Persian-UI checks in the background. Silent (exit 0) when all is
# well; on a problem it prints the report to stderr and exits 2, which wakes Claude to fix it
# following .claude/skills/persian-ui-check/SKILL.md.

input=$(cat)
case "$input" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../../..}" || exit 0

# Only right after a commit actually landed (not a failed or --dry-run commit).
committed=$(git log -1 --format=%ct 2>/dev/null) || exit 0
[ $(( $(date +%s) - committed )) -le 300 ] || exit 0

if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe
elif [ -x .venv/bin/python ]; then PY=.venv/bin/python
else echo "persian-ui-check: no .venv python found, check skipped" >&2; exit 0
fi
export PYTHONIOENCODING=utf-8

commit=$(git log -1 --format='%h %s')
report=""
status=0

tests=$(TEST_DB_NAME=test-persian-ui-hook.sqlite3 "$PY" manage.py test core.tests.test_translations --noinput 2>&1)
if [ $? -ne 0 ]; then
  status=1
  report+=$'\n## core.tests.test_translations failed\n'"$(printf '%s\n' "$tests" | tail -40)"$'\n'
fi

scan=$("$PY" .claude/skills/persian-ui-check/scan_english.py 2>&1)
if [ $? -ne 0 ]; then
  status=1
  report+=$'\n## English text scan\n'"$(printf '%s\n' "$scan" | head -80)"$'\n'
fi

if [ $status -ne 0 ]; then
  {
    echo "Persian UI check after commit $commit found problems."
    echo "Follow .claude/skills/persian-ui-check/SKILL.md to fix them, then commit the fix."
    printf '%s\n' "$report"
  } >&2
  exit 2
fi
exit 0
