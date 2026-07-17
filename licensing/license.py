"""
resolve-toolkit — License validation
=====================================
Modes (set via env var TOOLKIT_LICENSE_MODE):
  dummy   — Dev/testing: always valid, all modules unlocked (default)
  local   — reads ~/.resolve-toolkit/license.json, verifies Ed25519 signature
  remote  — Abo: Lizenzschlüssel gegen Backend prüfen, das eine kurze signierte
            Lease ausstellt. Offline greift die gecachte Lease bis zu ihrem
            Ablauf (Grace). Siehe apps/multicam-cutter/brain/Lizenz-API.md.
"""

import base64
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


# ── Config ────────────────────────────────────────────────────────────────────

MODE = os.environ.get("TOOLKIT_LICENSE_MODE", "dummy")

# All known module identifiers (maps to tabs in the UI)
ALL_MODULES = [
    "multicam",
    "enhance",
    "auphonic",
    "maxxvolume",
    "silence",
    "takes",
    "sequencer",
    "social",
]

# Module, die noch nicht für Beta freigegeben sind.
# Hier gelistete Module werden in der UI ausgeblendet,
# auch wenn die Lizenz sie enthält.
BETA_BLOCKED: set[str] = {"auphonic", "sequencer", "social"}
# Beispiel: BETA_BLOCKED = {"takes", "silence"}

_DATA_DIR          = os.path.expanduser("~/.resolve-toolkit")
_KEY_FILE          = os.path.join(_DATA_DIR, "license.key")       # eingegebener Lizenzschlüssel
_ACTIVATION_FILE   = os.path.join(_DATA_DIR, "activation.json")   # LS instance_id (activation_id)
_LOCAL_FILE        = os.path.join(_DATA_DIR, "license.json")      # signierte Lease (Cache)
_SUBSCRIPTION_FILE = os.path.join(_DATA_DIR, "subscription.json") # Abo-Anzeigedaten (unsigniert)

# Backend-API (Abo-Validierung). Über TOOLKIT_LICENSE_API überschreibbar
# (Staging/Test ohne Code-Änderung). Pfade: Next.js-Routen unter /api/.
_API_BASE       = os.environ.get("TOOLKIT_LICENSE_API", "https://multicamcutter-web.vercel.app")
_ACTIVATE_URL   = _API_BASE + "/api/license/activate"
_VALIDATE_URL   = _API_BASE + "/api/license/validate"
_DEACTIVATE_URL = _API_BASE + "/api/license/deactivate"

# Ed25519 Public Key — generated via keygen.py (private key never in repo)
_PUBLIC_KEY_B64 = "S2CGURNQQPlj2HUCo6hB+kZ/8eRU9VBkQ46TVhcTgcY="


# ── Data ──────────────────────────────────────────────────────────────────────

@dataclass
class LicenseInfo:
    valid: bool
    modules: List[str] = field(default_factory=list)
    expires: Optional[str] = None   # ISO date der LEASE (rollendes Fenster, NICHT Abo-Ende)
    email: Optional[str] = None
    major_version: Optional[str] = None  # e.g. "v0"
    grace: bool = False             # True if running on cached lease (offline/abgelaufenes Abo)
    error: Optional[str] = None     # Human-readable reason when not valid
    status: Optional[str] = None    # Server-Status: active|inactive|invalid|activation_limit
    # Informative Abo-Daten aus LemonSqueezy (nur Anzeige, unsigniert):
    sub_status: Optional[str] = None  # active | on_trial | cancelled | past_due
    renews_at: Optional[str] = None   # nächste Verlängerung (ISO date)
    ends_at: Optional[str] = None     # Zugriffsende bei Kündigung (ISO date)

    def has_module(self, module: str) -> bool:
        """Return True if this license grants access to the given module."""
        return self.valid and module in self.modules and module not in BETA_BLOCKED


# ── Internal helpers ──────────────────────────────────────────────────────────

def _device_id() -> str:
    """Stable, anonymous hardware identifier based on MAC address."""
    return str(uuid.UUID(int=uuid.getnode()))


def _device_name() -> str:
    """Menschlich lesbarer Gerätename für die LemonSqueezy-Instance."""
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return "Unbekanntes Gerät"


def _canonical(data: dict) -> str:
    """Kanonische Darstellung des Payloads zum Signieren/Prüfen."""
    parts = []
    for k in sorted(data.keys()):
        v = data[k]
        if isinstance(v, list):
            v = ",".join(sorted(v))
        parts.append(f"{k}={v}")
    return "|".join(parts)


def _verify_signature(data: dict) -> bool:
    """Prüft die Ed25519-Signatur der Lizenzdaten. Gibt False bei ungültiger Signatur."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        return False  # cryptography-Paket fehlt

    sig_b64 = data.get("sig", "")
    if not sig_b64:
        return False

    payload = {k: v for k, v in data.items() if k != "sig"}
    msg = _canonical(payload)

    try:
        pub_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(_PUBLIC_KEY_B64))
        pub_key.verify(base64.b64decode(sig_b64), msg.encode())
        return True
    except (InvalidSignature, Exception):
        return False


def _check_expiry(expires: Optional[str]) -> Optional[str]:
    """Gibt eine Fehlermeldung zurück wenn die Lizenz abgelaufen ist, sonst None."""
    if not expires:
        return None
    try:
        exp_date = date.fromisoformat(expires)
        if date.today() > exp_date:
            return f"Lizenz abgelaufen am {expires}."
    except ValueError:
        return "Ungültiges Ablaufdatum in Lizenzdatei."
    return None


def _get_major_version() -> str:
    """Liest die Hauptversion aus der VERSION-Datei (z.B. 'v0' aus 'v0.5.0')."""
    try:
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(_root, "VERSION")) as f:
            ver = f.read().strip()
            return ver.split(".")[0]
    except Exception:
        return "v0"


def _check_major_version(data: dict) -> Optional[str]:
    """Prüft ob die lizenzierte Hauptversion zur App passt.
    Abo-Leases enthalten kein major_version-Feld → kein Gating (versionsübergreifend)."""
    licensed = data.get("major_version")
    if not licensed:
        return None  # Leases/alte Lizenzen ohne Feld → kein Check
    app_major = _get_major_version()
    if licensed != app_major:
        return (f"Diese Lizenz gilt für Version {licensed}.x — "
                f"installiert ist {app_major}.x.")
    return None


def _check_device(data: dict) -> Optional[str]:
    """Prüft Gerätebindung — nur wenn die Lizenz ein device_id-Feld trägt
    (Abo-Leases). Alte Lizenzen ohne Feld werden nicht geräte-gebunden."""
    bound = data.get("device_id")
    if bound and bound != _device_id():
        return "Diese Lizenz ist an ein anderes Gerät gebunden."
    return None


def _lease_to_info(data: dict, grace: bool = False) -> LicenseInfo:
    """Verifiziert eine signierte Lizenz/Lease (Signatur → Gerät → Ablauf →
    Hauptversion) und baut daraus eine LicenseInfo. valid=False mit Grund beim
    ersten fehlgeschlagenen Check."""
    if not _verify_signature(data):
        return LicenseInfo(valid=False, error="Lizenz ungültig oder manipuliert.")
    for problem in (_check_device(data),
                    _check_expiry(data.get("expires")),
                    _check_major_version(data)):
        if problem:
            return LicenseInfo(valid=False, error=problem)
    return LicenseInfo(
        valid=True,
        modules=data.get("modules", []),
        expires=data.get("expires"),
        email=data.get("email"),
        major_version=data.get("major_version"),
        grace=grace,
    )


def _read_activation_id() -> Optional[str]:
    try:
        with open(_ACTIVATION_FILE) as f:
            return json.load(f).get("activation_id")
    except Exception:
        return None


def _write_activation_id(activation_id: str) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_ACTIVATION_FILE, "w") as f:
        json.dump({"activation_id": activation_id}, f)


def _persist_lease(lease: dict) -> None:
    """Signierte Lease als Cache ablegen (für spätere Offline-Verifikation)."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_LOCAL_FILE, "w") as f:
        json.dump(lease, f, indent=2)


def _write_subscription(sub: dict) -> None:
    """Abo-Anzeigedaten cachen (für Offline-Anzeige). Unsigniert — reine Info."""
    if not sub:
        return
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_SUBSCRIPTION_FILE, "w") as f:
        json.dump(sub, f)


def _read_subscription() -> dict:
    try:
        with open(_SUBSCRIPTION_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _apply_subscription(info: LicenseInfo, sub: dict) -> None:
    """Überträgt die informativen Abo-Felder in die LicenseInfo."""
    if not sub:
        return
    info.sub_status = sub.get("status")
    info.renews_at = sub.get("renews_at")
    info.ends_at = sub.get("ends_at")


def _validate_cached_lease(grace: bool = True) -> LicenseInfo:
    """Verifiziert die zwischengespeicherte Lease (Offline-Grace bis zu ihrem
    Ablauf). expires der Lease ist die Grace-Grenze — keine separate Frist."""
    try:
        with open(_LOCAL_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        return LicenseInfo(valid=False, error="Keine zwischengespeicherte Lizenz.")
    except json.JSONDecodeError:
        return LicenseInfo(valid=False, error="Zwischengespeicherte Lizenz beschädigt.")
    info = _lease_to_info(data, grace=grace)
    if info.valid:
        _apply_subscription(info, _read_subscription())  # letzte bekannte Abo-Daten
    return info


def _status_message(status: Optional[str]) -> str:
    return {
        "inactive":         "Abo abgelaufen oder gekündigt. Bitte verlängern.",
        "invalid":          "Lizenzschlüssel ungültig.",
        "activation_limit": "Lizenz auf zu vielen Geräten aktiv.",
        "device_mismatch":  "Aktivierung passt nicht zu diesem Gerät.",
    }.get(status, "Lizenz konnte nicht validiert werden.")


# ── Validation modes ──────────────────────────────────────────────────────────

def _validate_dummy() -> LicenseInfo:
    """Dev mode — always returns a fully unlocked license."""
    return LicenseInfo(
        valid=True,
        modules=ALL_MODULES,
        expires="2099-12-31",
        email="dev@local",
        major_version=_get_major_version(),
    )


def _validate_local() -> LicenseInfo:
    """
    Liest ~/.resolve-toolkit/license.json und verifiziert sie (Signatur, Gerät,
    Ablauf, Hauptversion). Nützlich für Offline-Tests mit einer signierten Datei.
    """
    try:
        with open(_LOCAL_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        return LicenseInfo(valid=False, error=f"Keine Lizenzdatei gefunden ({_LOCAL_FILE}).")
    except json.JSONDecodeError:
        return LicenseInfo(valid=False, error="Lizenzdatei ist kein gültiges JSON.")
    except Exception as e:
        return LicenseInfo(valid=False, error=f"Lizenzfehler: {e}")
    return _lease_to_info(data, grace=False)


def _validate_remote() -> LicenseInfo:
    """
    Abo-Modus — Lizenzschlüssel gegen das Backend prüfen, das eine kurze
    signierte Lease ausstellt (siehe brain/Lizenz-API.md). Erststart aktiviert
    (verbraucht einen Slot), danach wird validiert. Offline oder bei negativem
    Status greift die gecachte Lease bis zu ihrem Ablauf.
    """
    import requests  # optional dependency — nur im Remote-Modus

    try:
        with open(_KEY_FILE) as f:
            key = f.read().strip()
    except FileNotFoundError:
        return LicenseInfo(valid=False, error="Kein Lizenzschlüssel hinterlegt.")

    activation_id = _read_activation_id()
    payload = {"key": key, "device_id": _device_id()}
    if activation_id:
        payload["activation_id"] = activation_id
        url = _VALIDATE_URL
    else:
        payload["device_name"] = _device_name()
        url = _ACTIVATE_URL

    try:
        resp = requests.post(url, json=payload, timeout=8)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        # Server nicht erreichbar → Offline-Grace über die gecachte Lease
        return _validate_cached_lease(grace=True)

    if data.get("status") == "active":
        lease = data.get("lease") or {}
        info = _lease_to_info(lease, grace=False)
        if info.valid:
            _persist_lease(lease)
            if data.get("activation_id"):
                _write_activation_id(data["activation_id"])
            sub = data.get("subscription") or {}
            _write_subscription(sub)
            _apply_subscription(info, sub)
            info.status = "active"
            return info
        # Frische Lease unbrauchbar (Signatur/Gerät) → wenigstens gecachte weiter
        cached = _validate_cached_lease(grace=True)
        return cached if cached.valid else info

    # Negativ (inactive/invalid/activation_limit): gecachte Lease bis Ablauf ehren
    cached = _validate_cached_lease(grace=True)
    if cached.valid:
        return cached
    status = data.get("status")
    return LicenseInfo(valid=False, status=status,
                       error=data.get("message") or _status_message(status))


# ── Public API ────────────────────────────────────────────────────────────────

def set_license_key(key: str) -> LicenseInfo:
    """
    Speichert den Lizenzschlüssel und validiert sofort (erzwingt Neu-Aktivierung).
    Von der App bei der Key-Eingabe aufgerufen.
    """
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_KEY_FILE, "w") as f:
        f.write(key.strip())
    # Alte Aktivierung verwerfen → nächster validate() aktiviert neu
    try:
        os.remove(_ACTIVATION_FILE)
    except FileNotFoundError:
        pass
    return validate()


def migrate_license_key(key: str) -> LicenseInfo:
    """
    Zieht die Lizenz auf DIESES Gerät um: gibt zuerst alle anderen Geräte-
    Aktivierungen frei (Takeover via device_id), dann aktiviert neu. Für den Fall
    `activation_limit` bei set_license_key (Lizenz noch auf altem Gerät aktiv).
    """
    key = key.strip()
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_KEY_FILE, "w") as f:
        f.write(key)
    _server_takeover(key)              # andere Geräte freigeben
    try:
        os.remove(_ACTIVATION_FILE)    # eigene Aktivierung erzwingen
    except FileNotFoundError:
        pass
    return validate()


def _server_deactivate() -> None:
    """Best-effort: gibt die Aktivierung serverseitig frei (LemonSqueezy-Slot,
    Self-Leave via activation_id). Fehler/Offline werden ignoriert — die lokale
    Deaktivierung passiert trotzdem."""
    try:
        import requests
        with open(_KEY_FILE) as f:
            key = f.read().strip()
        if not key:
            return
        payload = {"key": key, "device_id": _device_id()}
        activation_id = _read_activation_id()
        if activation_id:
            payload["activation_id"] = activation_id
        requests.post(_DEACTIVATE_URL, json=payload, timeout=8)
    except Exception:
        pass


def _server_takeover(key: str) -> None:
    """Best-effort Takeover: gibt alle ANDEREN Geräte-Aktivierungen frei
    (deactivate NUR mit device_id → Instanzen mit name != device_id werden
    freigegeben). Für den Umzug auf dieses Gerät."""
    try:
        import requests
        requests.post(_DEACTIVATE_URL,
                      json={"key": key, "device_id": _device_id()}, timeout=8)
    except Exception:
        pass


def clear_license() -> LicenseInfo:
    """
    Deaktiviert die Lizenz: gibt best-effort den Server-Slot frei (Self-Leave)
    und entfernt die lokale Lizenz (Key, Aktivierung, Lease, Abo-Cache) → App
    wird unlizenziert. Lokale Löschung passiert auch bei Server-Fehler/Offline.
    """
    _server_deactivate()
    for path in (_KEY_FILE, _ACTIVATION_FILE, _LOCAL_FILE, _SUBSCRIPTION_FILE):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except Exception:
            pass
    return LicenseInfo(valid=False)


def install_license(src_path: str) -> LicenseInfo:
    """
    Kopiert eine signierte license.json von src_path nach
    ~/.resolve-toolkit/license.json und validiert sie sofort. Datei wird NICHT
    kopiert wenn ungültig. (Manueller Datei-Import; Abo läuft über set_license_key.)
    """
    import shutil

    try:
        with open(src_path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return LicenseInfo(valid=False, error="Ausgewählte Datei nicht gefunden.")
    except json.JSONDecodeError:
        return LicenseInfo(valid=False, error="Ausgewählte Datei ist kein gültiges JSON.")
    except Exception as e:
        return LicenseInfo(valid=False, error=f"Datei konnte nicht gelesen werden: {e}")

    info = _lease_to_info(data, grace=False)
    if not info.valid:
        return info

    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        shutil.copy2(src_path, _LOCAL_FILE)
    except Exception as e:
        return LicenseInfo(valid=False, error=f"Lizenzdatei konnte nicht installiert werden: {e}")
    return info


def is_dev_mode() -> bool:
    """True when running with dummy/dev license (TOOLKIT_LICENSE_MODE=dummy)."""
    return MODE == "dummy"


def validate() -> LicenseInfo:
    """
    Validate the current license and return a LicenseInfo.
    Result should be cached in session state by the caller.
    """
    if MODE == "dummy":
        return _validate_dummy()
    elif MODE == "local":
        return _validate_local()
    else:
        return _validate_remote()
