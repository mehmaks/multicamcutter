"""Dev-Modus-Erkennung fuer Debug-Artefakte (decision_log.json,
speaking_debug.json, console.log).

Frueher hing das an `licensing.license.is_dev_mode()` (Lizenzmodus "dummy").
Seit die MultiCamCutter-App kostenlos ist (1.0.1), setzt sie keinen
Lizenzmodus mehr — die Kopplung haette jede ausgelieferte App in den
Dev-Modus geschaltet. Deshalb eigenes Signal:

- `MULTICAM_DEBUG=1`  → immer Dev-Modus (auch in der eingefrorenen Engine)
- eingefrorene Engine (PyInstaller, ausgelieferte App) → nie
- Quellcode-Lauf (Dev-App, Resolve-Toolkit) → wie bisher: Dev, solange
  `TOOLKIT_LICENSE_MODE` nicht gesetzt oder "dummy" ist
"""
import os
import sys


def is_dev_mode() -> bool:
    if os.environ.get("MULTICAM_DEBUG") == "1":
        return True
    if getattr(sys, "frozen", False):
        return False
    return os.environ.get("TOOLKIT_LICENSE_MODE", "dummy") == "dummy"
