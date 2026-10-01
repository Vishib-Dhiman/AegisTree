#!/usr/bin/env bash
# ClearSky: one-step setup on a fresh clone.
# Needs git, Python 3.11+ (uv optional), and internet access once; after this
# everything runs offline except optional web search and emailed sign-in codes.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Setting up ClearSky ==="

# 1. Virtual environment
if [ ! -d ".venv" ]; then
  echo "[1/6] Creating virtual environment (.venv)..."
  if command -v uv >/dev/null 2>&1; then uv venv .venv; else python3 -m venv .venv; fi
fi
PYTHON=".venv/bin/python"

# 2. System 1 decision model (openJev Verdict, ~1.4 GB of weights)
if [ ! -f "Verdict-open-jev/artifacts/v2/model.safetensors" ]; then
  echo "[2/6] Downloading openJev Verdict..."
  if [ ! -d "Verdict-open-jev" ]; then
    git clone https://github.com/Heman10x-NGU/Verdict-open-jev.git Verdict-open-jev
  else
    git -C Verdict-open-jev pull || true
  fi
else
  echo "[2/6] openJev Verdict already present."
fi

# 3. Python dependencies
echo "[3/6] Installing Python dependencies..."
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$PYTHON" -r requirements.txt
else
  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install -r requirements.txt
fi

# 4. Demo repositories, pinned to the commits the demo ADRs were written for
echo "[4/6] Fetching demo repositories..."
fetch_repo() {  # name url commit
  local dir="repos/$1"
  if [ -d "$dir/.git" ] && [ "$(git -C "$dir" rev-parse HEAD 2>/dev/null)" = "$3" ]; then
    echo "  $1 already at ${3:0:8}"
    return
  fi
  rm -rf "$dir"
  mkdir -p "$dir"
  git -C "$dir" init -q
  git -C "$dir" remote add origin "$2"
  git -C "$dir" fetch -q --depth 1 origin "$3"
  git -C "$dir" checkout -q FETCH_HEAD
  echo "  $1 at ${3:0:8}"
}
fetch_repo sqlalchemy   https://github.com/sqlalchemy/sqlalchemy 65ea6bee82149495a57ea821e0934a9a5d0ded51
fetch_repo pydantic     https://github.com/pydantic/pydantic     bb6da4cfbb1f559885ea2fa207ec93853bfeac64
fetch_repo cryptography https://github.com/pyca/cryptography     6a312bff6f5d8712a6ca85639c4de4db15015a00
fetch_repo eyecite      https://github.com/freelawproject/eyecite 0513e7fec46db49d86d9c8f6a854feba231b50a3
# Add ClearSky's demo ADRs and helper files to each workspace (never overwrites edits)
"$PYTHON" -c "from aegis.demo import seed_vault; seed_vault.write_missing('.')"

# 5. Voice input model (Whisper base, ~145 MB)
echo "[5/6] Downloading the speech model..."
./scripts/get_speech_model.sh || echo "  (skipped: the mic button will explain how to fetch it later)"

# 6. Reset the demo vault and verify
echo "[6/6] Seeding the demo vault and running the tests..."
"$PYTHON" scripts/reset_demo.py
"$PYTHON" -m pytest tests/ -q

echo ""
echo "=== Setup complete ==="
echo "Local models run through Ollama (https://ollama.com). Pull at least one, e.g.:"
echo "  ollama pull qwen2.5-coder:7b        # code and chat"
echo "  ollama pull qwen3-vl:8b-instruct    # screenshots and scanned PDFs"
echo "Start ClearSky:"
echo "  ./scripts/demo.sh         # this machine only: http://127.0.0.1:8080"
echo "  ./scripts/demo.sh --lan   # other devices on your network, over HTTPS"
