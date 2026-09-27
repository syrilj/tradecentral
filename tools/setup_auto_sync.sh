#!/usr/bin/env bash
# Install launchd service on macOS for automated daily data sync at 16:15 ET.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_NAME="com.tradecentral.datasync.plist"
SRC_PLIST="$ROOT/tools/$PLIST_NAME"
DEST_DIR="$HOME/Library/LaunchAgents"
DEST_PLIST="$DEST_DIR/$PLIST_NAME"

mkdir -p "$DEST_DIR"
mkdir -p "$ROOT/runs"

echo "Installing launchd job to $DEST_PLIST..."
cp "$SRC_PLIST" "$DEST_PLIST"

# Unload if already loaded, then load fresh
launchctl unload "$DEST_PLIST" 2>/dev/null || true
launchctl load "$DEST_PLIST"

echo "✅ Automated daily market data sync is registered with launchd!"
echo "   Schedule: Mon-Fri at 16:15 local time (after market close)."
echo "   Runs: tools/update_all_data.sh"
echo "   Logs: runs/auto_sync.log and runs/auto_sync.err"
