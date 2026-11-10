#!/usr/bin/env bash
set -e

# 1. Lint and format Python code with Ruff
if command -v uv >/dev/null 2>&1; then
  echo "🐍 Linting and formatting Python code (uv run ruff)..."
  uv run ruff check --fix .
  uv run ruff format .
elif command -v ruff >/dev/null 2>&1; then
  echo "🐍 Linting and formatting Python code (ruff)..."
  ruff check --fix .
  ruff format .
else
  echo "⚠️  Neither 'uv' nor 'ruff' found, skipping Python linting/formatting."
fi

# 2. Format Shell scripts (prefers native shfmt from brew, falls back to uvx)
if command -v shfmt >/dev/null 2>&1; then
  echo "📜 Formatting shell scripts (shfmt)..."
  shopt -s globstar 2>/dev/null || true
  if shopt -q globstar 2>/dev/null; then
    shfmt -i 2 -w **/*.sh
  else
    find . -name "*.sh" -not -path "*/.*" -exec shfmt -i 2 -w {} +
  fi
elif command -v uvx >/dev/null 2>&1; then
  echo "📜 Formatting shell scripts (uvx shfmt-py)..."
  shopt -s globstar 2>/dev/null || true
  if shopt -q globstar 2>/dev/null; then
    uvx --from shfmt-py shfmt -i 2 -w **/*.sh
  else
    find . -name "*.sh" -not -path "*/.*" -exec uvx --from shfmt-py shfmt -i 2 -w {} +
  fi
else
  echo "⚠️  Neither 'shfmt' nor 'uvx' found. Install with: brew install shfmt"
fi

echo "✅ Done!"
