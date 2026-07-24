#!/usr/bin/env bash
#
# Publish the rendered static site in output/ to Cloudflare Workers Static Assets.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

WORKER_URL="${CLOUDFLARE_WORKER_URL:-https://daily-semi.danielsgardenatbabylon.workers.dev}"
export WRANGLER_LOG_PATH="${WRANGLER_LOG_PATH:-$REPO_ROOT/.wrangler/logs}"

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
