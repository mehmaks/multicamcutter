"""
resolve-toolkit — License Signer
==================================
Erzeugt eine signierte license.json für einen Betatester.

Voraussetzung: license_private.key muss existieren (via keygen.py erzeugt).

Verwendung:
  python licensing/keysign.py

Das Ablaufdatum wird aus der eingegebenen Anzahl Tage ab heute berechnet.
Die fertige license_<name>.json landet in licensing/licenses/
und kann dem Betatester per Mail / Install-Script übergeben werden.
"""

import base64
import json
from datetime import date, timedelta
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_DIR = Path(__file__).parent
_KEY_FILE = _DIR / "license_private.key"
_LICENSES_DIR = _DIR / "licenses"

# ── Private Key laden ─────────────────────────────────────────────────────────

if not _KEY_FILE.exists():
    print(f"Fehler: {_KEY_FILE} nicht gefunden. Zuerst keygen.py ausführen.")
    exit(1)

_priv_key = Ed25519PrivateKey.from_private_bytes(
    base64.b64decode(_KEY_FILE.read_text().strip())
)

# ── Eingaben ──────────────────────────────────────────────────────────────────

ALL_MODULES = ["multicam", "enhance", "auphonic", "maxxvolume", "silence", "takes"]

_MODULE_LABELS = {
    "multicam":   "Multicam Cutter",
    "enhance":    "Audio Enhance",
    "auphonic":   "Auphonic",
    "maxxvolume": "Voice Leveler",
    "silence":    "Silence Cutter",
    "takes":      "Take Selector",
}

print("=== resolve-toolkit License Generator ===\n")

email = input("E-Mail des Betatesters: ").strip()

_days_raw = input("Gültigkeitsdauer in Tagen (Enter = 365): ").strip() or "365"
try:
    _days = int(_days_raw)
    if _days <= 0:
        raise ValueError
except ValueError:
    print(f"Fehler: Ungültige Anzahl Tage '{_days_raw}'. Bitte eine positive ganze Zahl eingeben.")
    exit(1)
expires = (date.today() + timedelta(days=_days)).isoformat()

_labels_str = ", ".join(f"{k} ({v})" for k, v in _MODULE_LABELS.items())
print(f"  Verfügbare Module: {_labels_str}")
modules_raw = input("Module (kommasepariert, Enter = alle): ").strip()
modules = [m.strip() for m in modules_raw.split(",")] if modules_raw else ALL_MODULES

major_version = input("Hauptversion (z.B. v0, v1; Enter = v0): ").strip() or "v0"

# ── Lizenz-Payload aufbauen und signieren ─────────────────────────────────────

payload = {
    "email":         email,
    "expires":       expires,
    "major_version": major_version,
    "modules":       modules,
    "valid":         True,
}

# Kanonische Nachricht: sortierte Felder als "key=value" mit "|" getrennt.
# Listen werden als kommaseparierter String kodiert.
def _canonical(data: dict) -> str:
    parts = []
    for k in sorted(data.keys()):
        v = data[k]
        if isinstance(v, list):
            v = ",".join(sorted(v))
        parts.append(f"{k}={v}")
    return "|".join(parts)

msg = _canonical(payload)
sig_bytes = _priv_key.sign(msg.encode())
payload["sig"] = base64.b64encode(sig_bytes).decode()

# ── Ausgabe ───────────────────────────────────────────────────────────────────

_LICENSES_DIR.mkdir(parents=True, exist_ok=True)
out_file = _LICENSES_DIR / f"license_{email.split('@')[0]}.json"
out_file.write_text(json.dumps(payload, indent=2))

print(f"\nLizenz erstellt: {out_file}")
print(f"  E-Mail:   {email}")
print(f"  Version:  {major_version}")
print(f"  Module:   {', '.join(modules)}")
print(f"  Läuft ab: {expires}")
print(f"\nDiese Datei kommt ins Install-Script → ~/.resolve-toolkit/license.json")
