#!/bin/bash
# Auto-save uncommitted pidog_lab changes
# Called by cron (every 15 min) and systemd shutdown hook

cd /home/pidog/pidog_lab || exit 1

# Check if there are any changes to save
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
    exit 0  # Nothing to save
fi

# Stage all tracked file changes (not untracked files — those might be temp)
git add -u

# Also add any new .py, .md, .json files (but not .pyc, logs, etc.)
git add -- '*.py' '*.md' '*.json' '*.csv' '*.sh' 2>/dev/null

# Commit with timestamp
git commit -m "auto-save: $(date '+%Y-%m-%d %H:%M')" --no-verify 2>/dev/null

# Sync to disk (important for SD card)
sync
