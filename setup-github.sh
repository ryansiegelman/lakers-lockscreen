#!/bin/bash
# Publishes this repo to GitHub and wires up the cloud renderer.
#
#   ./setup-github.sh [repo-name]
#
# Requires the GitHub CLI, authenticated:
#   brew install gh      (or https://cli.github.com)
#   gh auth login
#
# Everything after that is automatic: repo, push, Pages, DEVICE variable,
# first render, and the URL to paste into your Shortcut.
set -euo pipefail
cd "$(dirname "$0")"

REPO="${1:-lakers-lockscreen}"
DEVICE="${DEVICE:-iphone-17-pro}"

command -v gh >/dev/null || {
  echo "GitHub CLI not found. Install it, then run this again:"
  echo "  https://cli.github.com    (or: brew install gh)"
  exit 1
}
gh auth status >/dev/null 2>&1 || { echo "Run 'gh auth login' first, then re-run this."; exit 1; }

OWNER=$(gh api user --jq .login)
echo "==> Publishing as $OWNER/$REPO"

# Pages needs a public repo unless you're on a paid plan.
if gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  echo "    repo already exists, reusing it"
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$OWNER/$REPO.git"
  git branch -M main
  git push -u origin main
else
  gh repo create "$REPO" --public --source=. --remote=origin --push
fi

echo "==> Setting DEVICE=$DEVICE"
gh variable set DEVICE --body "$DEVICE" --repo "$OWNER/$REPO"

echo "==> Enabling Pages on main /docs"
gh api --method POST "repos/$OWNER/$REPO/pages" \
  -f "source[branch]=main" -f "source[path]=/docs" >/dev/null 2>&1 \
  || gh api --method PUT "repos/$OWNER/$REPO/pages" \
       -f "source[branch]=main" -f "source[path]=/docs" >/dev/null 2>&1 \
  || echo "    (Pages may already be on - check Settings > Pages)"

echo "==> Running the first render"
gh workflow run "render wallpaper" --repo "$OWNER/$REPO"
echo "    waiting for it to finish..."
sleep 25
gh run watch --repo "$OWNER/$REPO" "$(gh run list --repo "$OWNER/$REPO" --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status 2>/dev/null || true

URL="https://$OWNER.github.io/$REPO/wallpaper.png"
echo
echo "================================================================"
echo "  Wallpaper URL for your Shortcut:"
echo "    $URL"
echo
echo "  Pages can take a couple of minutes to go live the first time."
echo "  In your Shortcut, replace the Mac address with the URL above,"
echo "  keeping the '?v=' and Current Date on the end."
echo "================================================================"
