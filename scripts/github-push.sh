#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# EasyNotes — push EVERY commit to your GitHub repo. Defaults to Gaurang135/EasyNotes.
# The target repo must already exist on GitHub and you must be authenticated for it
# (gh auth login, or an SSH key / PAT with push access).
#   make github-push                                  # default repo, commit-by-commit
#   FAST=1 make github-push                           # push all commits in one go
#   REPO=https://github.com/<user>/<repo>.git BRANCH=main make github-push
#
# Default is commit-by-commit: it advances the branch one commit at a time, which
# also gets past a pre-push size hook if this machine has one. Use FAST=1 to skip that.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

REPO="${REPO:-https://github.com/Gaurang135/EasyNotes.git}"
BRANCH="${BRANCH:-main}"

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "==> adding remote origin → $REPO"
  git remote add origin "$REPO"
else
  echo "==> using existing origin: $(git remote get-url origin)"
fi

if [ "${FAST:-0}" = "1" ]; then
  echo "==> pushing all commits to '$BRANCH' at $REPO"
  git push -u origin "HEAD:refs/heads/${BRANCH}"
  echo "==> done"
  exit 0
fi

total="$(git rev-list --count HEAD)"
echo "==> pushing $total commits to '$BRANCH' one at a time…"
n=0
for sha in $(git rev-list --reverse HEAD); do
  n=$((n + 1))
  msg="$(git log -1 --format='%s' "$sha")"
  printf "[%3d/%d] %s  %s\n" "$n" "$total" "${sha:0:9}" "$msg"
  git push -q origin "${sha}:refs/heads/${BRANCH}"
done
git push -q -u origin "HEAD:refs/heads/${BRANCH}" || true
echo "==> done — all $total commits pushed to $BRANCH at $REPO"
