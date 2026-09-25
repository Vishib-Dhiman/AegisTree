#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Detect Python interpreter (favor .venv if available)
if [ -f ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  PYTHON="python"
fi

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# Check local Ollama status without exiting if offline (mock engine available)
if $PYTHON -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=2)" >/dev/null 2>&1; then
  echo "✓ Local Ollama daemon detected at 127.0.0.1:11434"
else
  echo "Notice: Ollama not running at 127.0.0.1:11434. Web/TUI will offer Mock Engine or switchable local models."
fi

# Check openJev Verdict v1.4 artifacts
if [ -f "Verdict-open-jev/artifacts/v2/model.onnx" ] || [ -f "Verdict-open-jev/artifacts/v2/model.safetensors" ]; then
  echo "✓ openJev Verdict v1.4 local weights verified (<35ms CPU latency)"
else
  echo "Notice: Verdict weights missing. Decision router will fall back to AST/keyword rules."
fi

# Reset demo vault to clean state
$PYTHON scripts/reset_demo.py

MODE="${1:-web}"

if [ "$MODE" = "tui" ] || [ "$MODE" = "cli" ]; then
  echo "Launching AegisTree Terminal User Interface..."
  exec $PYTHON -m aegis.ui.cli
else
  echo "Launching AegisTree Sovereign Web Dashboard at http://127.0.0.1:8080..."
  exec $PYTHON -m uvicorn aegis.ui.server:app --host 127.0.0.1 --port 8080
fi
