"""multicam_cutter package — stellt sicher, dass der Modul-Ordner in sys.path liegt."""

import sys
from pathlib import Path

# Multicam-Skripte nutzen `from frame_utils import ...` (Standalone mit cwd=multicam_cutter).
# Beim Package-Import muss der Ordner daher in sys.path sein.
_PKG_DIR = str(Path(__file__).resolve().parent)
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)
