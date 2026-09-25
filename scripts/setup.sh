#!/usr/bin/env bash
# AegisTree — One-Step Teammate Onboarding Script
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Setting up AegisTree Sovereign Second Brain ==="

# 1. Virtual environment setup
if [ ! -d ".venv" ]; then
  echo "[1/4] Creating virtual environment (.venv)..."
  if command -v uv >/dev/null 2>&1; then
    uv venv .venv
  else
    python3 -m venv .venv
  fi
fi

# Detect Python inside venv
if [ -f ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python3"
fi

# 2. Clone Verdict-open-jev weights if missing
if [ ! -d "Verdict-open-jev" ] || [ ! -f "Verdict-open-jev/artifacts/v2/model.safetensors" ]; then
  echo "[2/4] Downloading local openJev Verdict v1.4 weights..."
  if [ ! -d "Verdict-open-jev" ]; then
    git clone https://github.com/Heman10x-NGU/Verdict-open-jev.git Verdict-open-jev
  else
    echo "Verdict-open-jev directory exists. Pulling latest weights..."
    git -C Verdict-open-jev pull || true
  fi
else
  echo "[2/4] openJev Verdict v1.4 weights already present."
fi

# 3. Install dependencies
echo "[3/4] Installing Python dependencies..."
if command -v uv >/dev/null 2>&1; then
  uv pip install -r requirements.txt
else
  $PYTHON -m pip install --upgrade pip
  $PYTHON -m pip install -r requirements.txt
fi

# 4. Initialize demo vault and verify test suite
echo "[4/4] Seeding demo vault and running verification tests..."
$PYTHON scripts/reset_demo.py
$PYTHON -m pytest tests/ -q

echo ""
echo "=== Setup complete! ==="
echo "To launch the Web Dashboard:   ./scripts/demo.sh"
echo "To launch the Terminal TUI:     ./scripts/demo.sh tui"
