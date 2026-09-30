#!/usr/bin/env bash
# One-time download of the local speech-to-text model (Whisper "base", ~145 MB).
# After this, the mic button works with no internet connection.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON=".venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"
MODEL="${1:-base}"
$PYTHON - "$MODEL" <<'EOF'
import sys
from huggingface_hub import snapshot_download
from clearsky.speech import MODEL_REPOS
repo = MODEL_REPOS.get(sys.argv[1], sys.argv[1])
print("Downloading", repo, "...")
print("Saved to", snapshot_download(repo))
EOF
