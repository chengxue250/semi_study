#!/usr/bin/env bash
#
# Safely publish output/ to the gh-pages branch.
#
# WHY THIS EXISTS
# ---------------
# The "naïve" pattern for publishing a subdirectory to gh-pages is:
#
#     git checkout --orphan gh-pages-new
#     git rm -rf .
#     cp -r output/* .
#     git add -A && git commit && git push --force origin gh-pages-new:gh-pages
#
# That pattern silently leaks any untracked file that happens to live in the
# project directory — including .gitignored secrets (notify.yaml, .env,
# .claude/) — because `git add -A` on an orphan branch *does not consult the
# branch's .gitignore* (there isn't one yet), and `git rm -rf .` only
# removes tracked files.
#
# We hit this exact bug twice on 2026-05-23, leaking the ntfy topic both
# times.
#
# This script avoids the bug by structure: it clones the repo into a fresh
# temp directory and does all gh-pages work there. The local project tree
# is never touched after the clone, so it cannot contaminate the publish.
#
# USAGE
# -----
#   scripts/publish_gh_pages.sh [source-ref]
#
#     source-ref    git ref whose output/ directory you want to publish.
#                   Defaults to "main".
#
# ENV VARS (optional)
# -------------------
#   PUBLISH_REMOTE  remote name in the local repo (default: origin)
#   PUBLISH_BRANCH  branch on the remote to push to (default: gh-pages)
#
# EXIT CODES
# ----------
#   0  pushed successfully
#   2  bad input (missing ref, missing output/, no remote)
#   3  push failed
#

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_REF="${1:-main}"
REMOTE_NAME="${PUBLISH_REMOTE:-origin}"
PAGES_BRANCH="${PUBLISH_BRANCH:-gh-pages}"

# ---------------------------------------------------------------------------
# Resolve the source ref and remote URL up front so we fail fast on misuse.
# ---------------------------------------------------------------------------
cd "$REPO_ROOT"

if ! git rev-parse --verify "$SOURCE_REF" >/dev/null 2>&1; then
  echo "error: ref '$SOURCE_REF' not found locally" >&2
  exit 2
fi
LOCAL_SHA=$(git rev-parse "$SOURCE_REF")

if ! REMOTE_URL=$(git remote get-url "$REMOTE_NAME" 2>/dev/null); then
  echo "error: remote '$REMOTE_NAME' not configured" >&2
  exit 2
fi

# Soft warning if local source is ahead/behind remote — the publish uses the
# local copy, which may not match what's on the remote yet.
REMOTE_SHA=$(git ls-remote "$REMOTE_URL" "refs/heads/$SOURCE_REF" 2>/dev/null | cut -f1 || true)
if [ -n "$REMOTE_SHA" ] && [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
  echo "warning: local $SOURCE_REF (${LOCAL_SHA:0:7}) differs from remote (${REMOTE_SHA:0:7})"
  echo "         this script publishes the LOCAL copy; push $SOURCE_REF first if you want"
  echo "         the repo and Pages to stay in sync"
fi

# ---------------------------------------------------------------------------
# Clone the repo into a fresh temp dir. From this point on we never read or
# write anything in $REPO_ROOT — that's the entire security guarantee.
# ---------------------------------------------------------------------------
TMPDIR=$(mktemp -d -t semi-news-publish.XXXXXX)
trap 'rm -rf "$TMPDIR"' EXIT

echo "==> cloning to $TMPDIR (isolated from your working tree)"
# --no-local forces a real fetch rather than file-system hardlinks, so the
# temp clone is fully independent.
git clone --quiet --no-local --branch "$SOURCE_REF" "$REPO_ROOT" "$TMPDIR/clone"

cd "$TMPDIR/clone"

if [ ! -d output ]; then
  echo "error: ref '$SOURCE_REF' has no output/ directory at root; nothing to publish" >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# Build a single-commit branch whose root is the contents of output/.
# ---------------------------------------------------------------------------
echo "==> staging output/ contents at branch root"
mv output "$TMPDIR/staging"

git checkout --orphan publish-tmp >/dev/null 2>&1
# Remove tracked files first, then any leftover untracked.
git rm -rf . >/dev/null 2>&1 || true
find . -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +

# Restore output/ contents at the new root, plus .nojekyll so Pages doesn't
# Jekyll-process the files.
cp -R "$TMPDIR/staging/." .
touch .nojekyll

# ---------------------------------------------------------------------------
# Commit + push.
#
# We set committer identity inline (rather than `git config`) to avoid
# touching any persistent git config — keeps the script side-effect-free
# beyond the push itself.
# ---------------------------------------------------------------------------
echo "==> committing"
git -c user.name="semi-news-publish" -c user.email="publish@local" \
    add -A
TODAY=$(TZ=Asia/Shanghai date +%F)
git -c user.name="semi-news-publish" -c user.email="publish@local" \
    commit -m "pages: edition $TODAY (from $SOURCE_REF@${LOCAL_SHA:0:7})" \
    --allow-empty >/dev/null

echo "==> pushing to $REMOTE_URL ($PAGES_BRANCH)"
# Point origin at the real remote (clone's origin was the local path).
git remote set-url origin "$REMOTE_URL"
if ! git push --quiet --force origin "HEAD:$PAGES_BRANCH"; then
  echo "error: push to $PAGES_BRANCH failed" >&2
  exit 3
fi

# ---------------------------------------------------------------------------
# Try to derive the Pages URL from the remote, just to print a friendly
# pointer. This is best-effort — failure is harmless.
# ---------------------------------------------------------------------------
PAGES_URL=$(printf '%s' "$REMOTE_URL" |
    sed -nE 's|.*[:/]([^/:]+)/([^/]+)(\.git)?$|https://\1.github.io/\2/|p' |
    sed 's|\.git/$|/|')

echo "✓ done. GitHub Pages will rebuild within ~30 seconds."
if [ -n "$PAGES_URL" ]; then
  echo "   $PAGES_URL"
fi
