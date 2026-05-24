#!/usr/bin/env bash
#
# Daily edition build & publish — the openclaw-friendly scripted pipeline.
#
# This is the entrypoint to wire into cron / launchd / systemd. It runs
# the whole day in 6 steps. The LLM only does step 3 (writing
# edition.json from pre-fetched JSON); everything else is bash so a weak
# or cheap LLM cannot accidentally skip the work.
#
# Setup (one time):
#   1. Copy scripts/agent-invoke.sh.template to scripts/agent-invoke.sh
#   2. Edit it to invoke your LLM (openclaw, claude, aider, etc.)
#      with PROMPT.md as the system / user message.
#   3. chmod +x scripts/agent-invoke.sh
#
# Usage:
#   scripts/run_daily.sh                            # full pipeline
#   DRY_RUN=1 scripts/run_daily.sh                  # everything except git push
#   SKIP_PUBLISH=1 scripts/run_daily.sh             # commit but don't push pages
#
# Exit codes:
#   0  success (or no-changes-no-op)
#   1  agent invocation failed
#   2  validation failed (site not updated; will retry tomorrow)
#   3  rendering/commit/publish failed

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

AGENT_INVOKE="${AGENT_INVOKE:-${REPO_ROOT}/scripts/agent-invoke.sh}"
DRY_RUN="${DRY_RUN:-0}"
SKIP_PUBLISH="${SKIP_PUBLISH:-0}"

# Each step prints a header so a tail -f of the run.log is readable.
section() { echo; echo "======== $* ========"; }

# Useful for tracking how long the agent step takes (often the slowest part).
now() { date -u +%s; }
elapsed() { local s=$1; echo "$(($(now) - s))s"; }


# ---------------------------------------------------------------------------
section "1/6  git pull (sync with origin)"
# Don't fail the whole run if remote has diverged — local main is the source
# of truth for what we publish today.
git pull --ff-only origin main 2>&1 || echo "(local is ahead or detached; continuing)"


# ---------------------------------------------------------------------------
section "2/6  preflight (fetch, shortlist, backup old edition.json)"
T0=$(now)
python3 scripts/preflight.py
echo "preflight took $(elapsed $T0)"


# ---------------------------------------------------------------------------
section "3/6  invoke agent (only step that needs an LLM)"
if [ ! -x "$AGENT_INVOKE" ]; then
  cat >&2 <<EOF
ERROR: $AGENT_INVOKE not found or not executable.

The orchestrator needs a small wrapper script that invokes your LLM with
PROMPT.md as input. Copy the template and edit:

    cp scripts/agent-invoke.sh.template scripts/agent-invoke.sh
    chmod +x scripts/agent-invoke.sh
    \$EDITOR scripts/agent-invoke.sh   # tell it how to call your LLM
EOF
  exit 1
fi

T0=$(now)
if ! "$AGENT_INVOKE"; then
  echo "ERROR: agent invocation returned non-zero exit code." >&2
  echo "       site not updated; will retry tomorrow." >&2
  exit 1
fi
echo "agent took $(elapsed $T0)"


# ---------------------------------------------------------------------------
section "4/6  validate edition.json"
if ! python3 scripts/validate_edition.py; then
  echo "ERROR: edition.json failed validation. Aborting before render/publish." >&2
  echo "       The most common cause is the agent re-stamping yesterday's edition." >&2
  echo "       Inspect output/edition.json and /tmp/preflight/instructions.txt." >&2
  exit 2
fi


# ---------------------------------------------------------------------------
section "5/6  render + commit"
python3 scripts/build_page.py

git add output/
if git diff --staged --quiet; then
  echo "no diff in output/ — nothing to commit"
else
  git commit -m "edition $(date -u +%F)"
  if [ "$DRY_RUN" = "1" ]; then
    echo "(DRY_RUN=1: skipping git push)"
  else
    git push origin main || { echo "ERROR: git push failed" >&2; exit 3; }
  fi
fi


# ---------------------------------------------------------------------------
section "6/6  publish to gh-pages"
if [ "$DRY_RUN" = "1" ] || [ "$SKIP_PUBLISH" = "1" ]; then
  echo "(skip-publish set: not pushing gh-pages)"
else
  "$REPO_ROOT/scripts/publish_gh_pages.sh" main || { echo "ERROR: gh-pages publish failed" >&2; exit 3; }
fi

# Best-effort: derive and print the live URL.
REMOTE_URL=$(git remote get-url origin 2>/dev/null || true)
PAGES_URL=$(printf '%s' "$REMOTE_URL" |
    sed -nE 's|.*[:/]([^/:]+)/([^/]+)(\.git)?$|https://\1.github.io/\2/|p' |
    sed 's|\.git/$|/|' || true)

echo
echo "✓ daily run complete."
if [ -n "${PAGES_URL:-}" ]; then
  echo "  $PAGES_URL"
fi
