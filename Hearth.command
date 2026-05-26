#!/bin/bash
#
# Hearth launcher — starts everything with one double-click.
#
# What it does:
#   1. Checks Ollama is running (starts it if installed but not running)
#   2. Starts the Python backend (uvicorn) in the background
#   3. Waits until the backend is actually answering
#   4. Opens the Hearth desktop app
#   5. When you quit, shuts the backend down cleanly (no orphan processes)
#
# Put this file in the local-chatbot folder (next to backend/, frontend/, desktop/).
# First time: right-click -> Open -> confirm. After that, double-click works.

set -e

# Resolve the folder this script lives in, so it works no matter where it's run from.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$HERE/backend"
DESKTOP="$HERE/desktop"

echo "Starting Hearth…"

# --- 1. Ollama check ---
if ! pgrep -x "ollama" > /dev/null 2>&1; then
  echo "Ollama isn't running — trying to start it…"
  open -a Ollama 2>/dev/null || {
    echo "⚠️  Couldn't start Ollama. Open the Ollama app manually, then re-run Hearth."
    read -p "Press Enter to exit."
    exit 1
  }
  sleep 3
fi

# --- 2. Start the backend ---
cd "$BACKEND"
source .venv/bin/activate
echo "Starting backend…"
uvicorn server:app --port 8000 > /tmp/hearth-backend.log 2>&1 &
BACKEND_PID=$!

# Make sure we kill the backend when this script exits (quit / window closed).
cleanup() {
  echo "Shutting down backend…"
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT

# --- 3. Wait for the backend to actually answer ---
echo "Waiting for backend to be ready…"
for i in {1..30}; do
  if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "Backend is up."
    break
  fi
  sleep 0.5
  if [ "$i" -eq 30 ]; then
    echo "⚠️  Backend didn't start. Check /tmp/hearth-backend.log for errors."
    read -p "Press Enter to exit."
    exit 1
  fi
done

# --- 4. Open the app ---
# If a built Hearth.app exists, open it. Otherwise fall back to dev mode.
APP="$DESKTOP/src-tauri/target/release/bundle/macos/Hearth.app"
if [ -d "$APP" ]; then
  echo "Opening Hearth…"
  open "$APP"
  # Keep this script alive (and the backend with it) while the app is open.
  # When you quit Hearth, this waits then the trap cleans up.
  echo "Hearth is running. Close this window to stop the backend."
  wait "$BACKEND_PID"
else
  echo "No built app found — launching in dev mode."
  cd "$DESKTOP"
  npm run tauri dev
fi
