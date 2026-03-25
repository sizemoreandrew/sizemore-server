#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/.env"
  set +a
fi

JELLYFIN_URL="http://localhost:8096"
: "${JELLYFIN_API_KEY:?JELLYFIN_API_KEY is not set. Add it to dashboard/.env}"
WATCH_DIR="/srv/media"

inotifywait -m -r -e close_write,create,move,delete "$WATCH_DIR" --format '%w%f' | while read -r changed; do
  echo "Change detected: $changed"
  curl -s -X POST "$JELLYFIN_URL/Library/Refresh" \
    -H "X-Emby-Token: $JELLYFIN_API_KEY" >/dev/null || true
  sleep 10
done
