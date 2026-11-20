#!/bin/bash
# resolve-toolkit — Bootstrap
# Installiert Homebrew, Python 3.12, Git und klont das Repo.
# Danach: bash ~/resolve-toolkit/setup.sh

set -e

GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
BOLD="\033[1m"
RESET="\033[0m"

ok()   { echo -e "${GREEN}✓${RESET} $*"; }
info() { echo -e "${YELLOW}→${RESET} $*"; }
err()  { echo -e "${RED}✗ $*${RESET}"; exit 1; }
step() { echo -e "\n${BOLD}$*${RESET}"; }

echo ""
echo "  resolve-toolkit — Bootstrap"
echo "  ═══════════════════════════════════════════"
echo "  Dieses Script installiert alle Voraussetzungen"
echo "  und lädt das resolve-toolkit herunter."
echo "  ═══════════════════════════════════════════"
echo ""

# ── Schritt 1 — Homebrew ──────────────────────────────────────────────────────

step "Schritt 1/3 — Homebrew"

if command -v brew &>/dev/null; then
    ok "Homebrew bereits installiert ($(brew --version | head -1))"
else
    info "Homebrew wird installiert..."
    echo ""
    echo "  Das Passwort deines Macs wird abgefragt (Eingabe ist unsichtbar)."
    echo "  Falls ein Dialog 'Xcode Command Line Tools installieren' erscheint:"
    echo "  → Auf 'Installieren' klicken und warten bis es abgeschlossen ist."
    echo "  → Danach läuft dieses Script automatisch weiter."
    echo ""
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    ok "Homebrew installiert"

    # Apple Silicon: PATH für aktuelle Session setzen
    if [ -x "/opt/homebrew/bin/brew" ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
        # Dauerhaft in .zprofile eintragen falls noch nicht vorhanden
        if ! grep -q "homebrew/bin/brew shellenv" "$HOME/.zprofile" 2>/dev/null; then
            echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "$HOME/.zprofile"
            ok "Homebrew PATH in ~/.zprofile eingetragen"
        fi
    fi
fi

# ── Schritt 2 — Python 3.12 + Git ────────────────────────────────────────────

step "Schritt 2/3 — Python 3.12 & Git"

if brew list python@3.12 &>/dev/null; then
    ok "Python 3.12 bereits installiert"
else
    info "Python 3.12 wird installiert..."
    brew install python@3.12
    ok "Python 3.12 installiert"
fi

if command -v git &>/dev/null; then
    ok "Git bereits installiert ($(git --version))"
else
    info "Git wird installiert..."
    brew install git
    ok "Git installiert"
fi

# Python 3.12 PATH für aktuelle Session + dauerhaft
PY312_PATH="/opt/homebrew/opt/python@3.12/bin"
if [ -d "$PY312_PATH" ]; then
    export PATH="$PY312_PATH:$PATH"
    if ! grep -q "python@3.12/bin" "$HOME/.zprofile" 2>/dev/null; then
        echo "export PATH=\"$PY312_PATH:\$PATH\"" >> "$HOME/.zprofile"
        ok "Python 3.12 PATH in ~/.zprofile eingetragen"
    fi
fi

# Version prüfen
PY_VERSION=$(python3 --version 2>&1)
ok "$PY_VERSION aktiv"

# ── Schritt 3 — Repo klonen ───────────────────────────────────────────────────

step "Schritt 3/3 — resolve-toolkit herunterladen"

REPO_URL="https://github.com/mehmaks/resolve-toolkit.git"   # öffentlich, kein Token nötig
TARGET="$HOME/resolve-toolkit"

if [ -d "$TARGET/.git" ]; then
    ok "resolve-toolkit bereits vorhanden — übersprungen"
    echo "   (Um zu aktualisieren: im Tool auf 'Updates prüfen' klicken)"
else
    info "resolve-toolkit wird heruntergeladen..."
    git clone "$REPO_URL" "$TARGET"
    ok "resolve-toolkit heruntergeladen nach ~/resolve-toolkit"
fi

chmod +x "$TARGET/setup.sh" "$TARGET/start.command" 2>/dev/null || true

# ── Fertig ────────────────────────────────────────────────────────────────────

echo ""
echo "  ═══════════════════════════════════════════"
echo "  Bootstrap abgeschlossen!"
echo ""
echo "  Jetzt diesen Befehl hier ins Terminal kopieren,"
echo "  mit Enter bestätigen und warten bis es fertig ist"
echo "  (dauert ca. 10–20 Minuten, läuft automatisch durch):"
echo ""
echo "      bash ~/resolve-toolkit/setup.sh"
echo ""
echo "  ═══════════════════════════════════════════"
echo ""
