#!/bin/bash
# resolve-toolkit — Setup Script
# Läuft einmalig nach dem ersten Klonen des Repos.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv"
# Homebrew-Python bevorzugen (aktueller als macOS-System-Python)
if [ -x "/opt/homebrew/bin/python3" ]; then
    PYTHON="/opt/homebrew/bin/python3"
elif [ -x "/usr/local/bin/python3" ]; then
    PYTHON="/usr/local/bin/python3"
else
    PYTHON="python3"
fi

# ── Farben ────────────────────────────────────────────────────────────────────

GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
RESET="\033[0m"

ok()   { echo -e "${GREEN}✓${RESET} $*"; }
info() { echo -e "${YELLOW}→${RESET} $*"; }
err()  { echo -e "${RED}✗${RESET} $*"; exit 1; }

echo ""
echo "  resolve-toolkit — Setup"
echo "  ═══════════════════════════"
echo ""

# ── Python-Version prüfen ─────────────────────────────────────────────────────

info "Python-Version prüfen..."
PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null) || \
    err "Python nicht gefunden. Bitte Python 3.10 oder neuer installieren."

PY_MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    err "Python $PY_VERSION gefunden — mindestens 3.10 benötigt.\nBitte von https://python.org herunterladen."
fi
ok "Python $PY_VERSION"

# ── Virtuelles Environment ────────────────────────────────────────────────────

if [ ! -f "$VENV/bin/activate" ]; then
    info "Virtuelles Environment erstellen..."
    $PYTHON -m venv "$VENV"
    ok "venv erstellt"
else
    ok "venv bereits vorhanden"
fi

source "$VENV/bin/activate"

# ── Dependencies installieren ─────────────────────────────────────────────────

info "Dependencies installieren (kann einige Minuten dauern)..."
pip install --quiet --upgrade pip
pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
ok "Dependencies installiert"

# ── Resemble Enhance (von GitHub, nicht auf PyPI) ─────────────────────────────

if ! python -c "import resemble_enhance" 2>/dev/null; then
    info "Resemble Enhance installieren..."
    pip install --quiet "git+https://github.com/resemble-ai/resemble-enhance.git@8e978149bfe8abab3eb77d965d579a111afdb0ff"
    ok "Resemble Enhance installiert"
else
    ok "Resemble Enhance bereits vorhanden"
fi

# ── Patches anwenden ──────────────────────────────────────────────────────────

SITE="$VENV/lib/$(python -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')/site-packages"

info "Kompatibilitäts-Patches anwenden..."

# Patch 1: df/io.py — torchaudio 2.x Kompatibilität
DF_IO="$SITE/df/io.py"
if [ -f "$DF_IO" ]; then
    patch --forward --silent "$DF_IO" "$SCRIPT_DIR/patches/df_io.patch" 2>/dev/null && \
        ok "df/io.py gepatcht" || ok "df/io.py bereits gepatcht"
else
    echo "  (df/io.py nicht gefunden — übersprungen)"
fi

# Patch 2: resemble_enhance cfm.py — scipy fsolve Fix
CFM="$SITE/resemble_enhance/enhancer/lcfm/cfm.py"
if [ -f "$CFM" ]; then
    patch --forward --silent "$CFM" "$SCRIPT_DIR/patches/resemble_cfm.patch" 2>/dev/null && \
        ok "resemble_enhance/cfm.py gepatcht" || ok "resemble_enhance/cfm.py bereits gepatcht"
else
    echo "  (cfm.py nicht gefunden — übersprungen)"
fi

# ── Config anlegen ────────────────────────────────────────────────────────────

CONFIG="$SCRIPT_DIR/modules/multicam_cutter/config.ini"
CONFIG_TEMPLATE="$SCRIPT_DIR/modules/multicam_cutter/config.template.ini"

if [ ! -f "$CONFIG" ] && [ -f "$CONFIG_TEMPLATE" ]; then
    info "config.ini aus Template erstellen..."
    cp "$CONFIG_TEMPLATE" "$CONFIG"
    ok "config.ini erstellt"
elif [ -f "$CONFIG" ]; then
    ok "config.ini bereits vorhanden"
fi

# ── Lizenz-Verzeichnis ────────────────────────────────────────────────────────

mkdir -p "$HOME/.resolve-toolkit"
if [ ! -f "$HOME/.resolve-toolkit/license.json" ]; then
    info "Lizenz-Platzhalter anlegen..."
    cat > "$HOME/.resolve-toolkit/license.json" << 'EOF'
{
  "valid": false,
  "modules": [],
  "expires": "",
  "email": ""
}
EOF
    ok "~/.resolve-toolkit/license.json angelegt (Lizenz bitte eintragen)"
else
    ok "Lizenzdatei bereits vorhanden"
fi

# ── KI-Modelle vorab herunterladen ───────────────────────────────────────────

# MediaPipe face_landmarker.task (~4 MB) — benötigt vom Multicam Cutter
LANDMARK_MODEL="$SCRIPT_DIR/modules/multicam_cutter/face_landmarker.task"
if [ ! -f "$LANDMARK_MODEL" ]; then
    info "face_landmarker.task herunterladen (~4 MB)..."
    curl --silent --show-error --location \
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task" \
        -o "$LANDMARK_MODEL" && ok "face_landmarker.task" || echo "  (Download fehlgeschlagen — wird beim ersten Start nachgeladen)"
else
    ok "face_landmarker.task bereits vorhanden"
fi

# ── start.command ausführbar machen ───────────────────────────────────────────

chmod +x "$SCRIPT_DIR/start.command" 2>/dev/null || true

# ── Fertig ────────────────────────────────────────────────────────────────────

echo ""
echo "  ═══════════════════════════════════════════"
echo "  Setup abgeschlossen!"
echo ""
echo "  Nächste Schritte:"
echo "  1. Lizenz eintragen in: ~/.resolve-toolkit/license.json"
echo "  2. Tool starten: Doppelklick auf start.command"
echo "     (oder: bash start.command)"
echo "  ═══════════════════════════════════════════"
echo ""
