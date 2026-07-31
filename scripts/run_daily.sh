#!/usr/bin/env bash
#
# Daily edition build & publish — the openclaw-friendly scripted pipeline.
#
# This is the entrypoint to wire into cron / launchd / systemd. It runs
# the whole day in 7 steps. The LLM only does step 3 (writing
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
#   SKIP_PUBLISH=1 scripts/run_daily.sh             # commit but don't publish anywhere
#   SKIP_CLOUDFLARE=1 scripts/run_daily.sh          # publish GitHub Pages only
#
# Exit codes:
#   0  success (or no-changes-no-op)
#   1  agent invocation failed
#   2  validation failed (site not updated; will retry tomorrow)
#   3  rendering/commit/publish failed

set -euo pipefail

export TZ="${TZ:-Asia/Shanghai}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [ -f .dev.vars ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.dev.vars
  set +a
fi

AGENT_INVOKE="${AGENT_INVOKE:-${REPO_ROOT}/scripts/agent-invoke.sh}"
DRY_RUN="${DRY_RUN:-0}"
SKIP_PUBLISH="${SKIP_PUBLISH:-0}"
SKIP_CLOUDFLARE="${SKIP_CLOUDFLARE:-0}"
CLOUDFLARE_WORKER_URL="${CLOUDFLARE_WORKER_URL:-https://semi-daily.danielsgarden.work}"
FAILED_EDITIONS_DIR="${REPO_ROOT}/.failed-editions"

# Each step prints a header so a tail -f of the run.log is readable.
section() { echo; echo "======== $* ========"; }

# Useful for tracking how long the agent step takes (often the slowest part).
now() { date +%s; }
elapsed() { local s=$1; echo "$(($(now) - s))s"; }

preserve_failed_edition() {
  local reason="$1"
  local edition="${REPO_ROOT}/output/edition.json"
  local stamp

  [ -f "$edition" ] || return 0
  stamp="$(date +%Y%m%dT%H%M%S)"
  mkdir -p "$FAILED_EDITIONS_DIR"
  cp "$edition" "${FAILED_EDITIONS_DIR}/${stamp}-${reason}.json"
  echo "  → saved failed draft to .failed-editions/${stamp}-${reason}.json"
}

restore_previous_edition() {
  local previous="${REPO_ROOT}/output/edition.json.previous"

  if [ -f "$previous" ]; then
    cp "$previous" "${REPO_ROOT}/output/edition.json"
  else
    git restore --worktree -- output/edition.json
  fi
}

check_cloudflare_auth() {
  if [ "$DRY_RUN" = "1" ] || [ "$SKIP_PUBLISH" = "1" ] || [ "$SKIP_CLOUDFLARE" = "1" ]; then
    return 0
  fi

  if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
    echo "ERROR: CLOUDFLARE_API_TOKEN is missing from ${REPO_ROOT}/.dev.vars." >&2
    echo "       Scheduled Wrangler deploys cannot rely on an interactive OAuth session." >&2
    return 1
  fi

  if [ ! -x node_modules/.bin/wrangler ]; then
    npm ci
  fi

  if ! node_modules/.bin/wrangler whoami >/dev/null 2>&1; then
    echo "ERROR: CLOUDFLARE_API_TOKEN is invalid, expired, or lacks Worker access." >&2
    return 1
  fi
}

# ---------------------------------------------------------------------------
section "1/6  git pull (sync with origin)"
if ! git diff --quiet -- output/edition.json; then
  echo "  → recovering stale edition.json from an earlier failed run"
  preserve_failed_edition "stale"
  git restore --worktree -- output/edition.json
fi

if ! git pull --ff-only origin main; then
  echo "ERROR: local main cannot fast-forward to origin/main." >&2
  echo "       Aborting before generation to avoid creating a divergent edition commit." >&2
  exit 3
fi

if ! check_cloudflare_auth; then
  echo "       Aborting before preflight so no edition commit is left unpublished." >&2
  exit 3
fi


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
  preserve_failed_edition "agent"
  restore_previous_edition
  echo "       site not updated; will retry tomorrow." >&2
  exit 1
fi
echo "agent took $(elapsed $T0)"


# ---------------------------------------------------------------------------
section "4/6  validate edition.json"
if ! python3 scripts/validate_edition.py; then
  echo "ERROR: edition.json failed validation. Aborting before render/publish." >&2
  preserve_failed_edition "validation"
  restore_previous_edition
  echo "       The most common cause is the agent re-stamping yesterday's edition." >&2
  echo "       Inspect .failed-editions/ and /tmp/preflight/instructions.txt." >&2
  exit 2
fi


# ---------------------------------------------------------------------------
section "5/6  render + commit"
python3 scripts/build_page.py

git add output/
if git diff --staged --quiet; then
  echo "no diff in output/ — nothing to commit"
else
  git commit -m "edition $(date +%F)"
  if [ "$DRY_RUN" = "1" ]; then
    echo "(DRY_RUN=1: skipping git push)"
  else
    git push origin main || { echo "ERROR: git push failed" >&2; exit 3; }
  fi
fi


# ---------------------------------------------------------------------------
section "6/7  publish to gh-pages"
if [ "$DRY_RUN" = "1" ] || [ "$SKIP_PUBLISH" = "1" ]; then
  echo "(skip-publish set: not pushing gh-pages)"
else
  "$REPO_ROOT/scripts/publish_gh_pages.sh" main || { echo "ERROR: gh-pages publish failed" >&2; exit 3; }
fi


# ---------------------------------------------------------------------------
section "7/7  publish to Cloudflare Workers"
if [ "$DRY_RUN" = "1" ] || [ "$SKIP_PUBLISH" = "1" ] || [ "$SKIP_CLOUDFLARE" = "1" ]; then
  echo "(skip-cloudflare set: not deploying Worker)"
else
  "$REPO_ROOT/scripts/publish_cloudflare_worker.sh" || { echo "ERROR: Cloudflare Worker deploy failed" >&2; exit 3; }
fi

# Best-effort: derive and print the live URL.
REMOTE_URL=$(git remote get-url origin 2>/dev/null || true)
PAGES_URL=$(printf '%s' "$REMOTE_URL" |
    sed -nE 's|.*[:/]([^/:]+)/([^/]+)(\.git)?$|https://\1.github.io/\2/|p' |
    sed 's|\.git/$|/|' || true)

echo
echo "✓ daily run complete."
if [ -n "${PAGES_URL:-}" ]; then
  echo "  GitHub Pages: $PAGES_URL"
fi
echo "  Cloudflare:   $CLOUDFLARE_WORKER_URL"
