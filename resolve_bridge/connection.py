"""
DaVinci Resolve connection handler.
Resolve must be running for this to work.
"""

import sys
import os

RESOLVE_SCRIPT_PATH = (
    "/Library/Application Support/Blackmagic Design/"
    "DaVinci Resolve/Developer/Scripting/Modules/"
)


def get_resolve():
    """
    Connect to a running DaVinci Resolve instance.
    Returns the Resolve object, or raises RuntimeError if not available.
    """
    if RESOLVE_SCRIPT_PATH not in sys.path:
        sys.path.append(RESOLVE_SCRIPT_PATH)

    try:
        import DaVinciResolveScript as dvr
    except ImportError as e:
        raise RuntimeError(
            "DaVinciResolveScript konnte nicht geladen werden. "
            "Ist DaVinci Resolve installiert?"
        ) from e

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError(
            "Keine Verbindung zu DaVinci Resolve. "
            "Bitte Resolve öffnen und erneut versuchen."
        )

    return resolve
