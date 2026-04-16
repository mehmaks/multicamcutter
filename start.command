#!/bin/bash
# resolve-toolkit — Start
# Doppelklick auf diese Datei öffnet das Tool im Browser.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv"
PORT=8501

cd "$SCRIPT_DIR"

if [ ! -f "$VENV/bin/activate" ]; then
    echo "❌ Setup noch nicht ausgeführt."
    echo "   Bitte zuerst setup.sh ausführen:"
    echo "   bash setup.sh"
    echo ""
    read -p "Enter drücken zum Schließen..."
    exit 1
fi

# Bereits gestartet? Dann nur Browser öffnen.
if lsof -i ":$PORT" &>/dev/null; then
    echo "resolve-toolkit läuft bereits."
    open "http://localhost:$PORT"
    echo "Browser geöffnet — dieses Fenster kann geschlossen werden."
    exit 0
fi

source "$VENV/bin/activate"

# Lizenz-Modus: "local" für Betatester, "dummy" für Entwicklung
export TOOLKIT_LICENSE_MODE="${TOOLKIT_LICENSE_MODE:-local}"

echo "resolve-toolkit wird gestartet..."

nohup python3 -m streamlit run "$SCRIPT_DIR/ui/app.py" \
    --server.headless true \
    --browser.gatherUsageStats false \
    > "$SCRIPT_DIR/toolkit.log" 2>&1 &

# Warten bis der Server bereit ist (max. 15s)
for i in {1..15}; do
    if lsof -i ":$PORT" &>/dev/null; then
        break
    fi
    sleep 1
done

open "http://localhost:$PORT"

echo ""
echo "✓ resolve-toolkit läuft im Hintergrund."
echo "  Browser geöffnet: http://localhost:$PORT"
echo ""
echo "  Dieses Fenster kann jetzt geschlossen werden."
