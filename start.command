#!/bin/bash
# resolve-toolkit — Start
# Doppelklick auf diese Datei öffnet das Tool im Browser.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv"

# Terminal-Fenster im Repo-Verzeichnis öffnen
cd "$SCRIPT_DIR"

if [ ! -f "$VENV/bin/activate" ]; then
    echo "❌ Setup noch nicht ausgeführt."
    echo "   Bitte zuerst setup.sh ausführen:"
    echo "   bash setup.sh"
    echo ""
    read -p "Enter drücken zum Schließen..."
    exit 1
fi

source "$VENV/bin/activate"

# Lizenz-Modus: "local" für Betatester, "dummy" für Entwicklung
export TOOLKIT_LICENSE_MODE="${TOOLKIT_LICENSE_MODE:-local}"

echo "resolve-toolkit wird gestartet..."
echo "Browser öffnet sich automatisch."
echo "(Dieses Fenster offen lassen — Schließen beendet das Tool)"
echo ""

exec python3 -m streamlit run "$SCRIPT_DIR/ui/app.py" \
    --server.headless false \
    --browser.gatherUsageStats false
