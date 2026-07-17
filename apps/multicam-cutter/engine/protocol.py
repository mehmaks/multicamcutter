"""JSON-Lines Kommunikationsprotokoll zwischen Engine und SwiftUI-App.

Jede Zeile auf stdout ist ein JSON-Objekt mit 'type'-Feld.
Regulaere print()-Ausgaben werden in {"type": "log"} gewrappt.
"""

import json
import sys
import io
from datetime import datetime


class JsonLineWriter:
    """Ersetzt sys.stdout und konvertiert alle Ausgaben in JSON-Lines.

    - Zeilen die bereits JSON sind (starten mit '{') werden durchgereicht
    - Alle anderen Zeilen werden als {"type": "log"} gewrappt
    - Gleichzeitig wird alles in eine JSONL-Logdatei geschrieben
    """

    def __init__(self, log_file=None, display_names=None):
        self._original = sys.__stdout__
        self._log_file = log_file
        self._log = log_file  # Kompatibilitaet mit run_from_bin.py hasattr-Check
        self._buffer = ""
        self._display_names = display_names or {}  # {filename: display_name}

    def write(self, text):
        self._buffer += text
        # __PROGRESS__ kommt oft ohne Newline (nach \r).
        # Auch \r als Zeilentrenner behandeln.
        while "\n" in self._buffer or "\r" in self._buffer:
            # Finde den naechsten Zeilentrenner (\n oder \r)
            idx_n = self._buffer.find("\n")
            idx_r = self._buffer.find("\r")
            if idx_n == -1:
                idx = idx_r
            elif idx_r == -1:
                idx = idx_n
            else:
                idx = min(idx_n, idx_r)
            line = self._buffer[:idx]
            self._buffer = self._buffer[idx + 1:]
            line = line.rstrip()
            if not line:
                continue
            # __PROGRESS__ und __REACTIONS__ koennen mitten in einer Zeile stecken
            # (weil \r im Pipe-Buffer nicht als Separator wirkt).
            # Alles vor __PROGRESS__ als Log emittieren, __PROGRESS__ separat parsen.
            if "__PROGRESS__" in line:
                before, _, after = line.partition("__PROGRESS__")
                # "before" ist die Analysiere-Zeile — als Log behalten
                before = before.strip()
                if before and "__REACTIONS__" not in before:
                    self._emit({"type": "log", "message": before})
                # Progress parsen
                self._parse_progress("__PROGRESS__" + after)
                continue
            if "__REACTIONS__" in line:
                # Nur den Teil vor __REACTIONS__ als Log behalten
                before = line.split("__REACTIONS__")[0].strip()
                if before:
                    self._emit({"type": "log", "message": before})
                continue
            # Analysiere-Zeilen filtern (Progress-Bar zeigt Fortschritt bereits)
            if "Analysiere" in line and "%" in line:
                continue
            # Bereits JSON? Durchreichen.
            if line.startswith("{"):
                try:
                    json.loads(line)
                    self._emit_raw(line)
                    continue
                except json.JSONDecodeError:
                    pass
            # Step-Beschreibungen erkennen (z.B. "  Base-EDL aus Audio...")
            stripped = line.strip()
            if stripped.endswith("...") and len(stripped) > 5:
                step_label = stripped.rstrip(".")
                # Display-Namen einsetzen (z.B. "C7804.MP4" -> "Cam Host")
                resolved_label = step_label
                for fname, dname in self._display_names.items():
                    if fname in resolved_label:
                        resolved_label = resolved_label.replace(fname, dname)
                if "Base-EDL" in step_label:
                    self._emit({"type": "step_start_sub", "label": "Diarization + Base-EDL"})
                elif "Nodding-Analyse" in step_label:
                    # Cam-Index aus "Nodding-Analyse CAM{N}" extrahieren
                    import re
                    cam_match = re.search(r'CAM(\d+)', step_label)
                    cam_num = cam_match.group(1) if cam_match else "1"
                    self._emit({
                        "type": "step_start_sub",
                        "label": resolved_label,
                        "preview_path": f"/tmp/multicam_preview_cam{cam_num}.jpg",
                    })
                elif "Cutaways" in step_label:
                    self._emit({"type": "step_start_sub", "label": "Cutaways einfügen"})
                self._emit({"type": "log", "message": line})
                continue
            # Normaler Text -> log-Nachricht
            self._emit({"type": "log", "message": line})

    def _parse_progress(self, line):
        """Parst '__PROGRESS__ 44.6 5:35' in step_progress JSON."""
        try:
            parts = line.split("__PROGRESS__")[1].strip().split()
            percent = float(parts[0])
            eta = parts[1] if len(parts) > 1 else ""
            self._emit({
                "type": "step_progress",
                "percent": round(percent, 1),
                "eta": eta,
            })
        except (IndexError, ValueError):
            pass

    def flush(self):
        try:
            self._original.flush()
        except (ValueError, OSError):
            pass
        if self._log_file:
            try:
                self._log_file.flush()
            except (ValueError, OSError):
                pass

    def fileno(self):
        return self._original.fileno()

    def isatty(self):
        return False

    def _emit(self, obj):
        obj.setdefault("ts", datetime.now().isoformat(timespec="milliseconds"))
        raw = json.dumps(obj, ensure_ascii=False)
        self._emit_raw(raw)

    def _emit_raw(self, line):
        self._original.write(line + "\n")
        self._original.flush()
        if self._log_file:
            self._log_file.write(line + "\n")
            self._log_file.flush()


def emit(msg_type, **kwargs):
    """Schreibt eine JSON-Line Nachricht auf stdout."""
    obj = {"type": msg_type, **kwargs}
    obj["ts"] = datetime.now().isoformat(timespec="milliseconds")
    line = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def progress(step, percent, message=""):
    emit("progress", step=step, percent=percent, message=message)


def warning(message):
    emit("warning", message=message)


def error(message):
    emit("error", message=message)


def result(**kwargs):
    emit("result", **kwargs)
