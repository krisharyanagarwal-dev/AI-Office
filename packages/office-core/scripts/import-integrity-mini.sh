#!/bin/bash
# Mini: refresh the read-only AI-Office checkout, then run the dost import
# integrity check. The mini is the always-on box, so this is where the check
# belongs -- the laptop sleeps.
#
# The checkout is READ-ONLY: hard reset to origin, never commits, never
# pushes. git-autopush skips it because a reset clone is never ahead.
set -u
export PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
export GIT_TERMINAL_PROMPT=0
REPO=$HOME/ai-office-src
BRANCH=dost-subpackages

cd "$REPO" 2>/dev/null || { echo "import-integrity: no checkout at $REPO"; exit 2; }
if ! git fetch -q --depth 1 origin "$BRANCH" 2>&1; then
  echo "import-integrity: fetch failed, checking the stale copy anyway"
else
  git reset -q --hard "origin/$BRANCH" && git clean -qfd
fi
echo "import-integrity: at $(git log --oneline -1)"
exec /usr/bin/python3 -u "$REPO/packages/office-core/scripts/import_integrity.py"
