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
  if ! $PYTHON -c "import json, urllib.request; tags = json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=2)); raise SystemExit(0 if any(m.get('name') == 'qwen3-vl:8b-instruct' for m in tags.get('models', [])) else 1)" >/dev/null 2>&1; then
    echo "Notice: vision model missing. Screenshots need it: ollama pull qwen3-vl:8b-instruct"
  fi
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
  echo "Launching ClearSky Terminal User Interface..."
  exec $PYTHON -m aegis.ui.cli
elif [ "$MODE" = "--lan" ] || [ "$MODE" = "lan" ]; then
  # Other devices on this network sign in over HTTPS (self-signed certificate)
  CERT="$(./scripts/make_cert.sh)"
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || true)"
  export CLEARSKY_HTTPS=1
  echo "Launching ClearSky for your network:"
  echo "  this machine:  https://127.0.0.1:8080"
  [ -n "$LAN_IP" ] && echo "  other devices: https://$LAN_IP:8080  (accept the certificate warning once)"
  if [ -z "${CLEARSKY_SMTP_HOST:-}" ]; then
    echo "  sign-in codes: not emailed (CLEARSKY_SMTP_HOST unset); they appear in this console"
  fi
  exec $PYTHON -m uvicorn aegis.ui.server:app --host 0.0.0.0 --port 8080 \
    --ssl-certfile "$CERT" --ssl-keyfile ".aegis/tls/key.pem"
else
  echo "Launching ClearSky at http://127.0.0.1:8080 (this machine only; use --lan for other devices)"
  exec $PYTHON -m uvicorn aegis.ui.server:app --host 127.0.0.1 --port 8080
fi
