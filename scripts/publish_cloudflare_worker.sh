#!/usr/bin/env bash
#
# Publish the rendered static site in output/ to Cloudflare Workers Static Assets.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

WORKER_URL="${CLOUDFLARE_WORKER_URL:-https://semi-daily.danielsgarden.work}"
export WRANGLER_LOG_PATH="${WRANGLER_LOG_PATH:-$REPO_ROOT/.wrangler/logs}"

if [ -f .dev.vars ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.dev.vars
  set +a
fi

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  echo "ERROR: CLOUDFLARE_API_TOKEN is missing from $REPO_ROOT/.dev.vars." >&2
  echo "       Scheduled deployments require a persistent API token." >&2
  exit 1
fi

if [ ! -f output/index.html ]; then
  echo "ERROR: output/index.html not found; run scripts/build_page.py first." >&2
  exit 1
fi

if [ ! -f package-lock.json ] && [ ! -x node_modules/.bin/wrangler ]; then
  echo "ERROR: wrangler is not installed. Run npm install once in this repo." >&2
  exit 1
fi

if [ ! -x node_modules/.bin/wrangler ]; then
  npm ci
fi

node_modules/.bin/wrangler deploy

echo
echo "✓ Cloudflare Worker deployed."
echo "  $WORKER_URL"

if [ -n "${NEWSLETTER_SEND_SECRET:-}" ]; then
  echo
  echo "→ triggering newsletter send"
  if curl -fsS -X POST "$WORKER_URL/api/send-daily" \
      -H "x-send-secret: $NEWSLETTER_SEND_SECRET" \
      -H "content-type: application/json" \
      -d '{}' ; then
    echo
    echo "✓ newsletter trigger complete."
  else
    echo
    echo "WARNING: newsletter trigger failed; site deployment remains successful." >&2
  fi
else
  echo
  echo "(NEWSLETTER_SEND_SECRET not set: skipping newsletter send trigger)"
fi
