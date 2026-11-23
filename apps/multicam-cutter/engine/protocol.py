"""JSON-Lines Kommunikationsprotokoll zwischen Engine und SwiftUI-App.

Jede Zeile auf stdout ist ein JSON-Objekt mit 'type'-Feld.
Regulaere print()-Ausgaben werden in {"type": "log"} gewrappt.
"""

import json
import re
import sys
import io
from datetime import datetime

# Zusatzfelder von __PROGRESS__ nach Form unterscheiden (siehe _parse_progress).
_TIME_RE = re.compile(r"^(?:\d+:\d{2}|--:--)$")
_COUNT_RE = re.compile(r"^\d+/\d+$")

# Die Pass-Banner aus add_reactions_to_edl.py. Der Schritt heisst nach aussen
# pauschal "Cutaways einfügen" und laeuft minutenlang -- ohne diese Aufloesung
# ist nicht erkennbar, welcher Pass gerade rechnet und wo die Zeit bleibt.
# Die Benennung folgt bewusst den SCHALTERN in den Einstellungen (nicht den
# internen Pass-Namen), damit ersichtlich ist, welcher Parameter die Laufzeit
# verursacht. PASS 5 (CLIP) ist der mit Abstand teuerste.
_PASS_RE = re.compile(r"PASS\s+(\d+[a-z]?)\s*:")
_PASS_LABELS = {
    "1":  "Read edit list",
    "2":  "Insert head-nod cutaways",
    "2b": "Insert pause cutaways",
    "3":  "Clean up short shots",
    "4":  "Split long shots",
    "5":  "Move unsuitable cutaways",
}


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
            # Pass-Banner ZUERST: sie enden nicht auf "..." und fielen sonst
            # durch die Erkennung unten hindurch (nur Log). step_detail statt
            # step_start_sub, weil letzteres den Schrittzaehler hochzaehlt --
            # sechs Paesse machten aus "Schritt 6 von 8" ein "Schritt 11 von 8".
            pass_match = _PASS_RE.search(stripped)
            if pass_match:
                label = _PASS_LABELS.get(pass_match.group(1))
                if label:
                    self._emit({"type": "step_detail", "label": label})
                self._emit({"type": "log", "message": line})
                continue
            if stripped.endswith("...") and len(stripped) > 5:
                step_label = stripped.rstrip(".")
                # Display-Namen einsetzen (z.B. "C7804.MP4" -> "Cam Host")
                resolved_label = step_label
                for fname, dname in self._display_names.items():
                    if fname in resolved_label:
                        resolved_label = resolved_label.replace(fname, dname)
                if "Base-EDL" in step_label:
                    self._emit({"type": "step_start_sub", "label": "Speaker detection + base EDL", "key": "base_edl"})
                elif "Reaktionsanalyse" in step_label:
                    # "Reaktionsanalyse CAM{N} (<datei>)": Sammelbegriff, weil dort
                    # Nicken UND Mundbewegung gemessen werden. Die App baut den
                    # Anzeigenamen selbst (Person + Einstellungsgroesse + Datei) —
                    # nur sie kennt Mic-Namen und Kamerarollen. Deshalb Datei separat.
                    import re
                    file_match = re.search(r'\(([^()]+)\)\s*$', step_label)
                    cam_file = file_match.group(1) if file_match else ""
                    self._emit({
                        "type": "step_start_sub",
                        "label": f"Reaction analysis ({cam_file})" if cam_file else "Reaction analysis",
                        "cam_file": cam_file,
                        "key": "nodding",
                    })
                elif "Cutaways" in step_label:
                    self._emit({"type": "step_start_sub", "label": "Insert cutaways", "key": "cutaways"})
                self._emit({"type": "log", "message": line})
                continue
            # Normaler Text -> log-Nachricht
            self._emit({"type": "log", "message": line})

    def _parse_progress(self, line):
        """Parst '__PROGRESS__ <pct> [<M:SS>] [<done>/<total>]' in step_progress.

        Die Zusatzfelder werden nach ihrer FORM erkannt, nicht nach ihrer
        Position. Vorher wurde `parts[1]` blind als ETA uebernommen -- der
        CLIP-Pass sendet dort aber einen Zaehler, sodass in der UI
        "ETA: 341/384" stand. Formunterscheidung statt Positionsvertrauen
        haelt das auch dann heil, wenn ein Schritt nur eines von beiden liefert.
        """
        try:
            parts = line.split("__PROGRESS__")[1].strip().split()
            percent = float(parts[0])
            eta, counter = "", ""
            for field in parts[1:3]:
                if _TIME_RE.match(field):
                    eta = field
                elif _COUNT_RE.match(field):
                    counter = field
            msg = {
                "type": "step_progress",
                "percent": round(percent, 1),
                "eta": eta,
            }
            if counter:
                msg["counter"] = counter
            self._emit(msg)
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
