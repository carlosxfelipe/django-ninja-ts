#!/usr/bin/env bash
set -e

PORT="${PORT:-8000}"

# If the first argument specifies a port (e.g. "8080" or "0.0.0.0:8080"), extract it
if [ $# -gt 0 ]; then
  case "$1" in
  *:*) PORT="${1##*:}" ;;
  *[!0-9]*) ;;
  *) PORT="$1" ;;
  esac
fi

# 1. Free the port if a process is already listening on it
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    echo "⚠️  Port $PORT is in use (PID: $(echo "$PIDS" | tr '\n' ' ')). Freeing port..."
    kill -TERM $PIDS 2>/dev/null || true
    sleep 0.5
    REMAINING=$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true)
    if [ -n "$REMAINING" ]; then
      kill -KILL $REMAINING 2>/dev/null || true
      sleep 0.2
    fi
  fi
fi

# 2. Start the Django development server
echo "🚀 Starting Django Ninja server on port $PORT..."
if command -v uv >/dev/null 2>&1; then
  if [ $# -gt 0 ]; then
    exec uv run python manage.py runserver "$@"
  else
    exec uv run python manage.py runserver "$PORT"
  fi
else
  echo "⚠️  'uv' not found, falling back to 'python'."
  if [ $# -gt 0 ]; then
    exec python manage.py runserver "$@"
  else
    exec python manage.py runserver "$PORT"
  fi
fi
