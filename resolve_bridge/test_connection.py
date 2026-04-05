"""
Quick test: connects to Resolve and prints current project info.
Run this while DaVinci Resolve is open with a project loaded.

Usage:
    python resolve_bridge/test_connection.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolve_bridge import get_project_info

try:
    info = get_project_info()
    print("Verbindung erfolgreich!")
    print(f"  Projekt:          {info['name']}")
    print(f"  Framerate:        {info['fps']} fps")
    print(f"  Timelines ({info['timeline_count']}):")
    for tl in info["timelines"]:
        marker = " ← aktiv" if tl == info["current_timeline"] else ""
        print(f"    - {tl}{marker}")
except RuntimeError as e:
    print(f"Fehler: {e}")
    sys.exit(1)
