#!/bin/bash
# setup_launch_agent.sh
# Run this ONCE on your Mac to install the bot as a Launch Agent.
# After that, bot starts automatically every time you log in.
#
# Usage:
#   chmod +x setup_launch_agent.sh
#   ./setup_launch_agent.sh

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_NAME="com.brandidentity.bot"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
LOG_DIR="$HOME/Library/Logs/BrandBot"

echo "📁 Project path: $DIR"
echo "📋 Installing Launch Agent: $PLIST_DEST"
echo ""

# Create log directory
mkdir -p "$LOG_DIR"

# Make start_bot.sh executable
chmod +x "$DIR/start_bot.sh"

# Write the plist
cat > "$PLIST_DEST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>

    <key>ProgramArguments</key>
    <array>
        <string>$DIR/start_bot.sh</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$DIR</string>

    <!-- Auto-start on login -->
    <key>RunAtLoad</key>
    <true/>

    <!-- Restart automatically if it crashes -->
    <key>KeepAlive</key>
    <true/>

    <!-- Wait 5s before restarting after a crash -->
    <key>ThrottleInterval</key>
    <integer>5</integer>

    <!-- Log output -->
    <key>StandardOutPath</key>
    <string>$LOG_DIR/bot.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/bot-error.log</string>
</dict>
</plist>
PLIST

echo "✅ Plist written to: $PLIST_DEST"
echo ""

# Load it immediately (no need to log out/in)
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo "🚀 Bot loaded and running!"
echo ""
echo "Useful commands:"
echo "  Check status : launchctl list | grep brandidentity"
echo "  View logs    : tail -f $LOG_DIR/bot.log"
echo "  Stop bot     : launchctl unload $PLIST_DEST"
echo "  Start bot    : launchctl load $PLIST_DEST"
echo "  Uninstall    : launchctl unload $PLIST_DEST && rm $PLIST_DEST"
