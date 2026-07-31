#!/usr/bin/env bash
#
# Publish the rendered static site in output/ to Cloudflare Workers Static Assets.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

WORKER_URL="${CLOUDFLARE_WORKER_URL:-https://semi-daily.danielsgarden.work}"
WORKER_URL="${WORKER_URL%/}"
CLOUDFLARE_ZONE_ID="${CLOUDFLARE_ZONE_ID:-b1a3298200623292b7876187d33c2262}"
export WRANGLER_LOG_PATH="${WRANGLER_LOG_PATH:-$REPO_ROOT/.wrangler/logs}"

purge_site_cache() {
  local payload response

  payload="$(printf '{"files":["%s/","%s/index.html","%s/edition.json","%s/research.html","%s/archive.html"]}' \
    "$WORKER_URL" "$WORKER_URL" "$WORKER_URL" "$WORKER_URL" "$WORKER_URL")"

  if ! response="$(curl -fsS -X POST \
      "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/purge_cache" \
      -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
      -H "content-type: application/json" \
      -d "$payload")"; then
    echo "ERROR: Cloudflare cache purge request failed." >&2
    return 1
  fi

  if ! printf '%s' "$response" | python3 -c \
      'import json, sys; data = json.load(sys.stdin); sys.exit(0 if data.get("success") else 1)'; then
    echo "ERROR: Cloudflare rejected the cache purge request." >&2
    return 1
  fi
}

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

echo
echo "→ purging custom-domain cache"
purge_site_cache
echo "✓ custom-domain cache purged."

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
