"""
resolve-toolkit — License validation
=====================================
Modes (set via env var TOOLKIT_LICENSE_MODE):
  dummy   — Dev/testing: always valid, all modules unlocked (default)
  local   — Beta: reads ~/.resolve-toolkit/license.json directly
  remote  — Production: validates key against server, caches with grace period
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, field
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
    "resolve",
    "takes",
]

_DATA_DIR    = os.path.expanduser("~/.resolve-toolkit")
_KEY_FILE    = os.path.join(_DATA_DIR, "license.key")
_CACHE_FILE  = os.path.join(_DATA_DIR, "license_cache.json")
_LOCAL_FILE  = os.path.join(_DATA_DIR, "license.json")
GRACE_DAYS   = 7

# Remote endpoint — replace with real URL before going to production
_VALIDATE_URL = "https://api.resolve-toolkit.com/v1/license/validate"


# ── Data ──────────────────────────────────────────────────────────────────────

@dataclass
class LicenseInfo:
    valid: bool
    modules: List[str] = field(default_factory=list)
    expires: Optional[str] = None   # ISO date, e.g. "2026-12-31"
    email: Optional[str] = None
    grace: bool = False             # True if running on cached/offline grace period
    error: Optional[str] = None     # Human-readable reason when not valid

    def has_module(self, module: str) -> bool:
        """Return True if this license grants access to the given module."""
        return self.valid and module in self.modules


# ── Internal helpers ──────────────────────────────────────────────────────────

def _device_id() -> str:
    """Stable, anonymous hardware identifier based on MAC address."""
    return str(uuid.UUID(int=uuid.getnode()))


def _write_cache(info: LicenseInfo) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_CACHE_FILE, "w") as f:
        json.dump({
            "valid":      info.valid,
            "modules":    info.modules,
            "expires":    info.expires,
            "email":      info.email,
            "cached_at":  time.time(),
        }, f, indent=2)


def _read_cache_with_grace() -> LicenseInfo:
    try:
        with open(_CACHE_FILE) as f:
            data = json.load(f)
        age_days = (time.time() - data.get("cached_at", 0)) / 86400
        if age_days <= GRACE_DAYS:
            return LicenseInfo(
                valid=data.get("valid", False),
                modules=data.get("modules", []),
                expires=data.get("expires"),
                email=data.get("email"),
                grace=True,
            )
        return LicenseInfo(
            valid=False,
            error=f"Keine Verbindung zum Lizenzserver. Grace Period ({GRACE_DAYS} Tage) abgelaufen.",
        )
    except FileNotFoundError:
        return LicenseInfo(valid=False, error="Kein Lizenzschlüssel gefunden.")
    except Exception as e:
        return LicenseInfo(valid=False, error=f"Lizenz-Cache fehlerhaft: {e}")


# ── Validation modes ──────────────────────────────────────────────────────────

def _validate_dummy() -> LicenseInfo:
    """Dev mode — always returns a fully unlocked license."""
    return LicenseInfo(
        valid=True,
        modules=ALL_MODULES,
        expires="2099-12-31",
        email="dev@local",
    )


def _validate_local() -> LicenseInfo:
    """
    Beta mode — reads ~/.resolve-toolkit/license.json directly.
    Example file:
      {
        "valid": true,
        "modules": ["multicam", "enhance"],
        "expires": "2026-12-31",
        "email": "beta@example.com"
      }
    """
    try:
        with open(_LOCAL_FILE) as f:
            data = json.load(f)
        return LicenseInfo(
            valid=bool(data.get("valid", False)),
            modules=data.get("modules", []),
            expires=data.get("expires"),
            email=data.get("email"),
        )
    except FileNotFoundError:
        return LicenseInfo(
            valid=False,
            error=f"Keine Lizenzdatei gefunden ({_LOCAL_FILE}).",
        )
    except json.JSONDecodeError:
        return LicenseInfo(valid=False, error="Lizenzdatei ist kein gültiges JSON.")
    except Exception as e:
        return LicenseInfo(valid=False, error=f"Lizenzfehler: {e}")


def _validate_remote() -> LicenseInfo:
    """
    Production mode — validates key against remote server.
    Falls back to local cache with grace period on network errors.
    """
    import requests  # optional dependency — only needed in remote mode

    try:
        with open(_KEY_FILE) as f:
            key = f.read().strip()
    except FileNotFoundError:
        return LicenseInfo(
            valid=False,
            error=f"Kein Lizenzschlüssel gefunden. Bitte Schlüssel in {_KEY_FILE} ablegen.",
        )

    try:
        resp = requests.post(
            _VALIDATE_URL,
            json={"key": key, "device_id": _device_id()},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        info = LicenseInfo(
            valid=bool(data.get("valid", False)),
            modules=data.get("modules", []),
            expires=data.get("expires"),
            email=data.get("email"),
            error=data.get("error"),
        )
        _write_cache(info)
        return info

    except Exception:
        # Network error — fall back to cached result with grace period
        return _read_cache_with_grace()


# ── Public API ────────────────────────────────────────────────────────────────

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
