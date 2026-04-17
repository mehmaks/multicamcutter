"""
Zentrales Error-Logging für resolve-toolkit.
Log-File: ~/.resolve-toolkit/app.log (session-übergreifend, max 500 KB × 3 Dateien)

Verwendung in Pages:
    import logging
    _log = logging.getLogger("rtk")
    ...
    except Exception as e:
        _log.exception("Kurzbeschreibung was schiefgelaufen ist")
        st.error(...)
"""

import logging
import logging.handlers
from pathlib import Path

_LOG_DIR  = Path.home() / ".resolve-toolkit"
_LOG_FILE = _LOG_DIR / "app.log"

_MAX_BYTES    = 500_000  # 500 KB pro Datei
_BACKUP_COUNT = 2        # app.log  +  app.log.1  +  app.log.2


def setup() -> logging.Logger:
    """Logger einmalig konfigurieren. Mehrfachaufrufe sind sicher (idempotent)."""
    _LOG_DIR.mkdir(exist_ok=True)
    logger = logging.getLogger("rtk")
    if logger.handlers:
        return logger
    logger.setLevel(logging.ERROR)
    handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(module)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(handler)
    return logger


def tail(n: int = 50) -> str:
    """Letzte n Zeilen aus dem aktuellen Log-File als String."""
    if not _LOG_FILE.exists():
        return ""
    text = _LOG_FILE.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def log_path() -> Path:
    return _LOG_FILE
