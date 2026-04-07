#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv"

if [ ! -f "$VENV/bin/activate" ]; then
    echo "❌ venv nicht gefunden unter $VENV"
    echo "   Bitte zuerst: python3 -m venv venv && pip install -r requirements.txt"
    exit 1
fi

source "$VENV/bin/activate"
exec python3 -m streamlit run "$SCRIPT_DIR/ui/app.py" "$@"
