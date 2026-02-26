#!/bin/bash
# start_bot.sh — Launch Agent wrapper for Brand Identity Bot
# Automatically uses the folder this script lives in as the project root.

# Resolve project directory (follow symlinks)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load .env variables
if [ -f "$DIR/.env" ]; then
    export $(grep -v '^#' "$DIR/.env" | xargs)
fi

# Use system python3, or virtualenv if present
if [ -f "$DIR/.venv/bin/python" ]; then
    PYTHON="$DIR/.venv/bin/python"
elif [ -f "$DIR/venv/bin/python" ]; then
    PYTHON="$DIR/venv/bin/python"
else
    PYTHON="$(which python3)"
fi

cd "$DIR"
exec "$PYTHON" run_bot.py
