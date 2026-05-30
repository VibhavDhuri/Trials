#!/usr/bin/env bash
# Options Signals — quick launcher for Linux / macOS.
# Run: ./launch.sh            (web UI on port 8501)
# Run: ./launch.sh terminal   (terminal dashboard)
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Activate virtualenv if one exists alongside the project
for VENV in "$DIR/../.venv" "$DIR/../venv" "$DIR/.venv" "$DIR/venv"; do
    if [ -f "$VENV/bin/activate" ]; then
        # shellcheck disable=SC1090
        source "$VENV/bin/activate"
        break
    fi
done

if [ "${1:-}" = "terminal" ]; then
    python terminal_app.py "${@:2}"
else
    echo "Starting Options Signals at http://localhost:8501 ..."
    streamlit run app.py --server.port 8501 --server.headless false
fi
