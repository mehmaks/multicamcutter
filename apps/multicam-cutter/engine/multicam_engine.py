#!/usr/bin/env python3
"""
multicam-engine — CLI-Backend fuer die Multicam Cutter Mac App.

Fuehrt die komplette Analyse-Pipeline aus (Folder -> AAF) und kommuniziert
ueber JSON-Lines auf stdout. Wird von der SwiftUI-App als Subprocess gestartet.

Usage:
    python multicam_engine.py \
        --folder /path/to/episode \
        --fps 25 \
        --params '{"max_shot": 14, "cleanup_dur": 1.6}' \
        --output /path/to/final.aaf
"""

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

# Resolve-Toolkit Root (3 Ebenen hoch: engine/ -> multicam-cutter/ -> apps/ -> root/)
ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONUNBUFFERED", "1")

# Protocol-Modul: im gleichen Verzeichnis oder im PyInstaller-Bundle
ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
# PyInstaller packt Daten nach _MEIPASS
if hasattr(sys, '_MEIPASS'):
    sys.path.insert(0, os.path.join(sys._MEIPASS, 'engine'))
from protocol import JsonLineWriter, emit, progress, warning, error, result


# ── Progress-Mapping: Pipeline-Schritt -> Prozentbereich ─────────────────────

STEP_RANGES = {
    "scan":          (0,   1),
    "sync":          (1,   6),
    "base_edl":      (6,  16),
    "nodding":       (16, 80),   # dynamisch auf N Kameras aufgeteilt
    "cutaways":      (80, 95),
    "pause_trim":    (95, 97),
    "aaf_export":    (97, 99),
    "done":          (99, 100),
}


def _step_percent(step, frac):
    """Berechnet Gesamtprozent aus Step-ID und Fortschritt innerhalb des Steps."""
    lo, hi = STEP_RANGES.get(step, (0, 100))
    return int(lo + frac * (hi - lo))


# ── Ordner-Scanner ───────────────────────────────────────────────────────────

VIDEO_EXT = {".mp4", ".mov", ".mxf", ".r3d", ".ari"}
AUDIO_EXT = {".wav", ".aif", ".aiff"}


def scan_folder(folder):
    all_files = sorted(f for f in folder.iterdir() if f.is_file())
    cams = [f for f in all_files if f.suffix.lower() in VIDEO_EXT]
    mics = [f for f in all_files if f.suffix.lower() in AUDIO_EXT]
    return cams, mics


# ── CLIP Person-Check fuer Thumbnails ─────────────────────────────────────────

def _find_person_frame(video_path, preview_dir, cam_index, duration_s):
    """Sucht einen Frame in dem eine Person zu sehen ist.

    Probiert Frames bei 10s, 20s, 30s, 60s, 90s, 120s.
    Gibt den Pfad zum besten Thumbnail zurueck.
    """
    import subprocess

    candidates_s = [10, 20, 30, 60, 90, 120]
    candidates_s = [t for t in candidates_s if t < duration_s]
    if not candidates_s:
        candidates_s = [min(5, duration_s / 2)]

    thumb_path = preview_dir / f"cam{cam_index}_{Path(video_path).stem}.jpg"

    # Versuche CLIP zu laden
    try:
        import torch
        from transformers import CLIPModel, CLIPProcessor
        from PIL import Image as PILImage

        device = "cpu"
        if torch.backends.mps.is_available():
            device = "mps"

        _model_id = "openai/clip-vit-base-patch32"
        try:
            model = CLIPModel.from_pretrained(_model_id, local_files_only=True).to(device)
            processor = CLIPProcessor.from_pretrained(_model_id, local_files_only=True)
        except (OSError, ValueError):
            model = CLIPModel.from_pretrained(_model_id).to(device)
            processor = CLIPProcessor.from_pretrained(_model_id)

        prompts = ["a person sitting at a microphone", "an empty room or wall"]
        text_inputs = processor(text=prompts, return_tensors="pt", padding=True).to(device)

        best_score = -1
        best_path = None

        for t in candidates_s:
            tmp_path = preview_dir / f"cam{cam_index}_candidate_{int(t)}.jpg"
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-ss", str(t), "-i", str(video_path),
                     "-frames:v", "1", "-q:v", "3", "-vf", "scale=320:-1",
                     str(tmp_path)],
                    capture_output=True, timeout=15,
                )
                if not tmp_path.exists():
                    continue

                image = PILImage.open(str(tmp_path))
                image_inputs = processor(images=image, return_tensors="pt").to(device)

                with torch.no_grad():
                    outputs = model(**text_inputs, **image_inputs)
                    probs = outputs.logits_per_image.softmax(dim=1)[0]
                    person_score = probs[0].item()  # "a person sitting at a microphone"

                if person_score > best_score:
                    best_score = person_score
                    best_path = tmp_path

            except Exception:
                continue

        # Bestes Candidate-Bild als finales Thumbnail uebernehmen
        if best_path and best_path != thumb_path:
            import shutil
            shutil.copy2(str(best_path), str(thumb_path))

        # Candidate-Dateien aufraeumen
        for t in candidates_s:
            tmp = preview_dir / f"cam{cam_index}_candidate_{int(t)}.jpg"
            tmp.unlink(missing_ok=True)

        if best_path:
            return str(thumb_path)

    except ImportError:
        # CLIP nicht verfuegbar — Fallback auf einfachen Frame bei 10s
        pass

    # Fallback: einfacher Frame bei 10s
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", "10", "-i", str(video_path),
             "-frames:v", "1", "-q:v", "3", "-vf", "scale=320:-1",
             str(thumb_path)],
            capture_output=True, timeout=15,
        )
        if thumb_path.exists():
            return str(thumb_path)
    except Exception:
        pass

    return None


# ── Audio-Dominanz-Analyse fuer Preview-Stellen ──────────────────────────────

def _find_dominant_mic_positions(mics, analysis_duration=120, window_s=1.0):
    """Findet fuer jedes Mic eine Stelle wo es dominant lauter ist als die anderen.

    Analysiert die ersten `analysis_duration` Sekunden (ab Sekunde 20, um
    Aufnahme-Rauschen/Stille am Anfang zu vermeiden). Berechnet RMS pro
    Fenster fuer jedes Mic und sucht das Fenster wo die Differenz zum
    zweitlautesten Mic am groessten ist.

    Returns: {mic_index: offset_seconds}
    """
    import subprocess
    import struct
    import math

    if len(mics) < 2:
        return {0: 30}

    sr = 8000  # Niedrige Sample-Rate genuegt fuer RMS
    start_s = 20
    n_samples = int(analysis_duration * sr)
    window_samples = int(window_s * sr)

    # Audio aller Mics laden (raw PCM via ffmpeg)
    mic_data = []
    for mic in mics:
        try:
            proc = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", str(start_s),
                 "-i", str(mic), "-t", str(analysis_duration),
                 "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                capture_output=True, timeout=30,
            )
            raw = proc.stdout
            samples = struct.unpack(f"<{len(raw)//2}h", raw)
            mic_data.append(samples)
        except Exception:
            mic_data.append(())

    if not all(mic_data):
        return {i: 30 for i in range(len(mics))}

    # Minimale Laenge
    min_len = min(len(d) for d in mic_data)
    n_windows = min_len // window_samples
    if n_windows < 5:
        return {i: 30 for i in range(len(mics))}

    # RMS pro Fenster pro Mic
    def rms(samples, start, length):
        chunk = samples[start:start + length]
        if not chunk:
            return 0.0
        return math.sqrt(sum(s * s for s in chunk) / len(chunk))

    rms_matrix = []  # [window][mic]
    for w in range(n_windows):
        offset = w * window_samples
        row = [rms(mic_data[m], offset, window_samples) for m in range(len(mics))]
        rms_matrix.append(row)

    # Fuer jedes Mic: Fenster mit groesster Dominanz finden
    result = {}
    for mic_idx in range(len(mics)):
        best_window = 0
        best_dominance = -1
        for w, row in enumerate(rms_matrix):
            my_rms = row[mic_idx]
            if my_rms < 100:  # zu leise, wahrscheinlich Stille
                continue
            others_max = max(row[j] for j in range(len(mics)) if j != mic_idx)
            dominance = my_rms - others_max
            if dominance > best_dominance:
                best_dominance = dominance
                best_window = w

        result[mic_idx] = start_s + best_window * window_s

    return result


# ── Scan-Modus: Thumbnails + Audio-Previews ──────────────────────────────────

def run_scan(folder, fps=25.0):
    """Scannt Ordner, extrahiert Thumbnails und Audio-Previews.

    Gibt ein Dict zurueck das als JSON an die SwiftUI-App geht.
    Thumbnails werden als JPEG in einen temp-Ordner geschrieben.
    Audio-Previews als kurze WAV-Schnipsel an dominanter Stelle.
    Emittiert scan_progress-Nachrichten fuer die UI.
    """
    import subprocess

    cams, mics = scan_folder(folder)
    if not cams:
        raise RuntimeError("Keine Kamera-Dateien gefunden")

    preview_dir = Path("/tmp/multicam-cutter-previews")
    preview_dir.mkdir(parents=True, exist_ok=True)

    # Fortschritt: Schritte = Cams (Dauer + Thumbnail) + Audio-Analyse + Mic-Previews
    total_scan_steps = len(cams) + 1 + len(mics)
    scan_step = 0

    def scan_progress(label):
        nonlocal scan_step
        scan_step += 1
        pct = round(scan_step / total_scan_steps * 100, 1)
        emit("scan_progress", percent=pct, step=scan_step,
             total_steps=total_scan_steps, label=label)

    cam_infos = []
    for i, cam in enumerate(cams):
        scan_progress(f"Thumbnail: {cam.name}")

        # Dauer + FPS in EINEM ffprobe-Aufruf (spart einen Prozess pro Datei).
        # fps = 0.0 bedeutet "nicht lesbar" — die App wertet das als Mismatch.
        duration_s = 0.0
        fps_val = 0.0
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error",
                 "-select_streams", "v:0",
                 "-show_entries", "format=duration:stream=r_frame_rate",
                 "-of", "default=noprint_wrappers=1:nokey=1",
                 str(cam)],
                capture_output=True, text=True, timeout=10,
            )
            lines = [l.strip() for l in probe.stdout.splitlines() if l.strip()]
            for line in lines:
                if "/" in line:                      # r_frame_rate, z.B. "30000/1001"
                    num, _, den = line.partition("/")
                    if float(den) != 0:
                        fps_val = float(num) / float(den)
                else:
                    try:
                        duration_s = float(line)     # format=duration
                    except ValueError:
                        pass
        except Exception:
            pass

        # Thumbnail: bei ~10s versuchen, Fallback auf Frame 0
        thumb_path = preview_dir / f"cam{i}_{cam.stem}.jpg"
        seek = min(10, duration_s * 0.5) if duration_s > 0 else 0
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(seek), "-i", str(cam),
                 "-frames:v", "1", "-q:v", "3", "-vf", "scale=320:-1",
                 str(thumb_path)],
                capture_output=True, timeout=15,
            )
            if not thumb_path.exists():
                # Fallback: Frame 0
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(cam),
                     "-frames:v", "1", "-q:v", "3", "-vf", "scale=320:-1",
                     str(thumb_path)],
                    capture_output=True, timeout=15,
                )
        except Exception:
            thumb_path = None
        thumb_result = str(thumb_path) if thumb_path and thumb_path.exists() else None

        cam_infos.append({
            "index": i,
            "filename": cam.name,
            "path": str(cam),
            "thumbnail": thumb_result,
            "duration_s": round(duration_s, 1),
            "fps": round(fps_val, 3),   # 0.0 = nicht lesbar
        })

    # ── Intelligente Audio-Preview-Stellen finden ──────────────────────────
    scan_progress("Audio-Analyse: dominante Stellen suchen")
    mic_preview_offsets = _find_dominant_mic_positions(mics)

    mic_infos = []
    for i, mic in enumerate(mics):
        scan_progress(f"Audio-Preview: {mic.name}")
        preview_path = preview_dir / f"mic{i}_{mic.stem}.wav"
        offset_s = mic_preview_offsets.get(i, 30)

        # 5s Audio-Preview ab der dominanten Stelle extrahieren
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(offset_s), "-i", str(mic),
                 "-t", "5", "-ac", "1", "-ar", "22050",
                 str(preview_path)],
                capture_output=True, timeout=15,
            )
        except Exception:
            preview_path = None

        # Dauer ermitteln
        duration_s = 0.0
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error",
                 "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1",
                 str(mic)],
                capture_output=True, text=True, timeout=10,
            )
            duration_s = float(probe.stdout.strip())
        except Exception:
            pass

        mic_infos.append({
            "index": i,
            "filename": mic.name,
            "path": str(mic),
            "preview": str(preview_path) if preview_path and preview_path.exists() else None,
            "duration_s": round(duration_s, 1),
        })

    # Default-Zuordnung: MIC1->CAM2, MIC2->CAM1 (wie bisheriger Workflow)
    default_mapping = {}
    if len(cams) >= 2 and len(mics) >= 2:
        default_mapping = {"0": [1], "1": [0]}  # cam_index -> [mic_indices]
    elif len(cams) >= 1 and len(mics) >= 1:
        default_mapping = {"0": [0]}

    return {
        "cameras": cam_infos,
        "mics": mic_infos,
        "default_mapping": default_mapping,
    }


# ── Hauptpipeline ───────────────────────────────────────────────────────────

# Free-Tier: ohne aktives Abo darf die laengste Quelldatei max. so lang sein.
FREE_TIER_MAX_S = 30 * 60


# ── CLIP-Modell (optionaler Download) ────────────────────────────────────────
# Das Modell ist NICHT im Bundle (waere +577 MB in der DMG). Es wird auf
# ausdruecklichen Wunsch des Users einmalig in den HF-Cache geladen
# (~/.cache/huggingface/hub) und ueberlebt dort App-Updates und Neuinstallation.
CLIP_REPO = "openai/clip-vit-base-patch32"
# Ausschluss statt Whitelist: Das Repo fuehrt dasselbe Modell in DREI Formaten
# (pytorch_model.bin, tf_model.h5, flax_model.msgpack — je ~605 MB). Wir brauchen
# nur das PyTorch-Format. Eine Whitelist auf "model.safetensors" waere ein Fehler:
# die Datei existiert in diesem Repo gar nicht → es wuerden NULL Gewichte geladen.
CLIP_IGNORE = ["*.h5", "*.msgpack", "*.md", ".gitattributes"]


def _clip_model_installed():
    """Liegt das CLIP-Modell vollstaendig im lokalen HF-Cache?"""
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(CLIP_REPO, ignore_patterns=CLIP_IGNORE,
                          local_files_only=True)
        return True
    except Exception:
        return False


def _clip_download_size():
    """Gesamtgroesse der zu ladenden Dateien in Bytes (fuer echte Prozent).

    Braucht Netz. Unsere Offline-Sperre muss dafuer weichen — sonst liefert die
    Abfrage still 0 und die UI koennte keine echte Groesse anzeigen. Wird nur
    aufgerufen, wenn das Modell fehlt (also vor einem moeglichen Download).
    Offline → Exception → Aufrufer faellt auf eine Schaetzung zurueck.
    """
    from fnmatch import fnmatch
    saved = {v: os.environ.pop(v, None) for v in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")}
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(CLIP_REPO, files_metadata=True)
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    total = 0
    for f in info.siblings:
        # Spiegelt CLIP_IGNORE — muss zum Download passen, sonst zeigt die UI
        # eine Groesse an, die nichts mit dem echten Download zu tun hat.
        if not any(fnmatch(f.rfilename, p) for p in CLIP_IGNORE):
            total += f.size or 0
    return total


def download_clip_model():
    """Laedt das CLIP-Modell und meldet echten Fortschritt via __PROGRESS__.

    Der Fortschritt kommt aus dem Wachstum des Cache-Ordners — das ist robuster,
    als sich in die tqdm-Interna von huggingface_hub zu haengen.
    """
    import threading
    # Unsere Offline-Sperre gilt hier NICHT — der User hat den Download angefordert.
    for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        os.environ.pop(var, None)

    from huggingface_hub import snapshot_download

    total = _clip_download_size()
    emit("clip_download_start", total_bytes=total)

    # NICHT hartkodieren: huggingface_hub respektiert HF_HOME/HF_HUB_CACHE.
    # Mit einem festen ~/.cache/huggingface/hub misst man sonst ins Leere und der
    # Fortschritt bleibt stur bei 0.
    from huggingface_hub.constants import HF_HUB_CACHE
    cache_root = Path(HF_HUB_CACHE)
    stop = threading.Event()

    def _measure():
        # Nur der Ordner dieses Modells, sonst zaehlen fremde Modelle mit.
        d = cache_root / f"models--{CLIP_REPO.replace('/', '--')}"
        size = 0
        for p in d.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    size += p.stat().st_size
            except OSError:
                pass
        return size

    start_size = _measure()

    def _poll():
        # emit() statt print("__PROGRESS__ …"): Der JsonLineWriter, der __PROGRESS__
        # in JSON uebersetzt, wird erst im Pipeline-Pfad installiert — hier laeuft
        # noch rohes stdout, die Zeilen kaemen also nie als JSON bei Swift an.
        while not stop.is_set():
            done = max(0, _measure() - start_size)
            emit("clip_progress", done=done, total=total)
            stop.wait(0.5)

    t = threading.Thread(target=_poll, daemon=True)
    t.start()
    try:
        snapshot_download(CLIP_REPO, ignore_patterns=CLIP_IGNORE)
    finally:
        stop.set()
        t.join(timeout=2)
    emit("clip_progress", done=total, total=total)


def _ensure_ffmpeg_on_path():
    """Sorgt dafuer, dass ffmpeg/ffprobe ueber den PATH auffindbar sind.

    Die Engine soll sich NICHT darauf verlassen, dass der Aufrufer den PATH
    korrekt setzt (die App tut es via EngineController.engineEnvironment, aber
    ein Terminal-Aufruf oder ein anderer Host evtl. nicht). Wir wissen, wo wir
    liegen: im .app-Bundle steht ffmpeg eine Ebene ueber dem multicam-engine-
    Ordner, also in Contents/Resources/.

    Gibt eine Diagnose-Zeile zurueck (oder None), damit Fehlermeldungen sie
    anhaengen koennen.
    """
    import shutil
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return None

    exe_dir = Path(sys.executable).resolve().parent
    candidates = [exe_dir, exe_dir.parent]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass))
        candidates.append(Path(meipass).parent)

    for d in candidates:
        try:
            if (d / "ffmpeg").exists():
                os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
                return f"ffmpeg via Fallback gefunden: {d}"
        except Exception:
            continue
    return "ffmpeg NICHT gefunden — weder im PATH noch neben der Engine."


def _ffmpeg_diagnostics():
    """Fakten fuer Fehlermeldungen: warum wurde ffmpeg nicht gefunden?"""
    import shutil
    return (f"PATH={os.environ.get('PATH', '(leer)')} | "
            f"which(ffmpeg)={shutil.which('ffmpeg')} | "
            f"which(ffprobe)={shutil.which('ffprobe')} | "
            f"frozen={getattr(sys, 'frozen', False)} | "
            f"executable={sys.executable}")


def _probe_timecode(path):
    """Embedded Timecode einer Datei (Container- oder Stream-Tag). None wenn keiner.

    Bei .mov steckt der TC ueblicherweise NICHT in format.tags, sondern in den
    Stream-Tags (Video-Stream und/oder der tmcd-Datenspur) — daher beides pruefen.
    """
    import subprocess
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        meta = json.loads(probe.stdout)
        tc = meta.get("format", {}).get("tags", {}).get("timecode")
        if tc:
            return tc
        for stream in meta.get("streams", []):
            tc = (stream.get("tags") or {}).get("timecode")
            if tc:
                return tc
    except Exception:
        pass
    return None


def convert_fps_files(files, target_fps):
    """Kodiert Videos auf target_fps um. Gibt die Liste der neuen Pfade zurueck.

    Rezept aus dem Web-Modul (ui/pages/multicam.py -> _run_ffmpeg_conversions):
    H.264 4:2:2 10-bit, CRF 14 — praktisch verlustfrei, behaelt die Pro-Color-
    Reserve der Quelle.

    KRITISCH: Der Embedded-Timecode des Originals muss erhalten bleiben, sonst
    verrutscht spaeter die Source-Frame-Berechnung der EDL-Pipeline (bekannter
    Bug "Cam-Cutaways verschoben bei fehlendem embedded TC").
    """
    import subprocess
    import re
    import signal
    outputs = []
    total = len(files)
    time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")

    # Abbrechen: Die App schickt SIGTERM. Dann das LAUFENDE ffmpeg beenden (sonst
    # laeuft der Child verwaist weiter) UND die halbfertige Ausgabedatei loeschen —
    # sonst bleibt eine korrupte _NNfps.mp4 liegen, die spaeter als „fertig" gilt.
    active = {"proc": None, "out": None}

    def _on_term(_signum, _frame):
        p = active["proc"]
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=3)
            except Exception:
                p.kill()
        out = active["out"]
        if out is not None and Path(out).exists():
            try:
                Path(out).unlink()
            except Exception:
                pass
        os._exit(0)

    signal.signal(signal.SIGTERM, _on_term)

    for i, src in enumerate(files):
        src_p = Path(src)
        out_p = src_p.with_name(f"{src_p.stem}_{int(round(target_fps))}fps{src_p.suffix}")
        emit("step_start", step_num=i + 1, total_steps=total,
             label=f"Konvertiere {src_p.name}")

        src_tc = _probe_timecode(src_p)
        dur = _probe_duration(src_p)
        # Balken sofort auf 0 setzen (Modal zeigt „wird vorbereitet", bis dur da ist).
        emit("convert_progress", file_index=i + 1, file_count=total,
             label=src_p.name, done=0.0, total=dur)
        emit("log", message=f"Quelle: {src_p.name}  (Dauer {dur:.1f}s)")
        emit("log", message=f"Ziel:   {out_p.name}")
        emit("log", message=f"Embedded TC im Original: {src_tc or '(keiner)'}")

        cmd = [
            "ffmpeg", "-y", "-i", str(src_p),
            "-vf", f"fps={target_fps}",
            "-c:v", "libx264", "-pix_fmt", "yuv422p10le",
            "-profile:v", "high422", "-crf", "14", "-preset", "medium",
            "-c:a", "aac", "-b:a", "192k",
        ]
        if src_tc:
            cmd += ["-metadata", f"timecode={src_tc}",
                    "-metadata:s:v:0", f"timecode={src_tc}"]
        cmd += ["-stats", "-loglevel", "info", str(out_p)]

        # Ab jetzt ist out_p die aufraeumbare Teildatei (fuer den SIGTERM-Handler).
        active["out"] = out_p
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", bufsize=1)
        active["proc"] = proc
        # ffmpeg schreibt Fortschritt als `... time=HH:MM:SS.ss ...` (via -stats).
        # Daraus die Sekunden ziehen → echter Balken statt Roh-Log im Modal.
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            emit("log", message=line)
            m = time_re.search(line)
            if m and dur > 0:
                done = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                emit("convert_progress", file_index=i + 1, file_count=total,
                     label=src_p.name, done=min(done, dur), total=dur)
        proc.wait()

        if proc.returncode != 0 or not out_p.exists():
            raise RuntimeError(f"Konvertierung von {src_p.name} fehlgeschlagen "
                               f"(ffmpeg exit {proc.returncode}).")
        # Fertig & verifiziert → nicht mehr als Teildatei behandeln (sonst wuerde
        # ein SIGTERM zwischen den Dateien die fertige Ausgabe loeschen).
        active["proc"] = None
        active["out"] = None

        # Gegenprobe: hat die neue Datei wirklich die Ziel-FPS?
        try:
            check = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=r_frame_rate",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(out_p)],
                capture_output=True, text=True, timeout=10,
            )
            rate = check.stdout.strip()
            emit("log", message=f"Ergebnis-FPS: {rate}")
        except Exception:
            pass

        # Gegenprobe: ist die Ausgabe wirklich VOLLSTÄNDIG? Eine abgebrochene oder
        # unterbrochene Konvertierung erzeugt sonst eine gültig aussehende, aber
        # ABGESCHNITTENE Datei — die später die AAF (source-TC out of range → „timecode
        # extents do not match") UND den Sync (verkürzte CAM1-Referenz → falsche Offsets)
        # zerlegt. Die Ausgabe-Dauer muss ~der Quelle entsprechen.
        if dur > 0:
            out_dur = _probe_duration(out_p)
            if out_dur < dur * 0.98:
                try:
                    out_p.unlink()
                except Exception:
                    pass
                raise RuntimeError(
                    f"Konvertierung von {src_p.name} UNVOLLSTÄNDIG: Ausgabe {out_dur:.1f}s "
                    f"statt {dur:.1f}s. Die abgeschnittene Datei wurde entfernt — bitte "
                    f"erneut konvertieren und den Vorgang diesmal nicht abbrechen."
                )

        # Balken der fertigen Datei sicher auf 100 %.
        emit("convert_progress", file_index=i + 1, file_count=total,
             label=src_p.name, done=dur, total=dur)
        outputs.append(str(out_p))

    return outputs


def _probe_duration(path):
    """Dauer einer Mediendatei in Sekunden (ffprobe). 0.0 bei Fehler."""
    try:
        import subprocess
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(probe.stdout.strip())
    except Exception:
        return 0.0


def _enforce_free_tier(cam_paths, mic_paths):
    """Ohne gueltige Lizenz: laengste Quelldatei <= 30 Min, sonst RuntimeError.
    Mit Lizenz (oder Dummy-Modus) keine Beschraenkung."""
    try:
        from licensing.license import validate
        if validate().valid:
            return  # lizenziert → keine Grenze
    except Exception:
        pass  # Lizenzpruefung nicht moeglich → als Free-Tier behandeln

    longest, longest_name = 0.0, ""
    for p in cam_paths + mic_paths:
        d = _probe_duration(p)
        if d > longest:
            longest, longest_name = d, os.path.basename(p)

    if longest > FREE_TIER_MAX_S:
        raise RuntimeError(
            f"Free-Tier-Grenze: Die laengste Quelldatei ({longest_name}, "
            f"{int(longest // 60)} Min) ueberschreitet das 30-Minuten-Limit. "
            f"Fuer unbegrenzte Laenge bitte ein Abo aktivieren "
            f"(Einstellungen → Lizenz)."
        )


def run_pipeline(folder, fps, params, output_path,
                 cam_mics=None, cam_types_arg=None, cam_nodding_arg=None,
                 skip_analysis=False, skip_base_edl=False,
                 speaking_mode=None, lut=None,
                 cams_arg=None, mics_arg=None):
    """Fuehrt die komplette Pipeline aus. Gibt (aaf_path, stats) zurueck.

    cams_arg/mics_arg: explizite Dateilisten (nur die in der App aktivierten
    Quellen). Sind sie gesetzt, scannt die Engine den Ordner NICHT selbst.
    Das ist wichtig, weil `--cam-mics`/`--cam-types`/`--display-names`
    positionsbasiert sind: die Reihenfolge muss exakt der der App entsprechen.
    Ohne die Listen bleibt das alte Verhalten (Selbst-Scan) erhalten.
    """

    from shared.waveform_sync import sync_sources, SyncError
    from modules.multicam_cutter.run_from_bin import (
        run_analysis, _parse_cam_mics, _parse_cam_list, _parse_cam_nodding,
    )
    from modules.multicam_cutter.build_aaf import build_aaf

    # ── Schritt-Zaehler ────────────────────────────────────────────────────
    # Steps: Scan, Sync, Base-EDL, Nodding×N, Cutaways, Pause-Trim, AAF
    n_cams_expected = len(cams_arg) if cams_arg else len(list(scan_folder(folder)[0]))
    total_steps = 4 + n_cams_expected + 2  # scan, sync, base_edl, N×nodding, cutaways, pause_trim, aaf
    step_num = 0

    def next_step(label):
        nonlocal step_num
        step_num += 1
        emit("step_start", step_num=step_num, total_steps=total_steps, label=label)

    # ── 1. Scan ──────────────────────────────────────────────────────────────
    next_step("Ordner scannen")
    if cams_arg or mics_arg:
        # Die App hat die aktivierten Quellen explizit uebergeben — NICHT scannen,
        # sonst waeren deaktivierte Dateien wieder dabei und die positionsbasierten
        # Zuordnungen (--cam-mics u.a.) wuerden verrutschen.
        cams = [Path(p) for p in (cams_arg or [])]
        mics = [Path(p) for p in (mics_arg or [])]
    else:
        cams, mics = scan_folder(folder)

    if len(cams) < 2:
        raise RuntimeError(
            f"Mindestens 2 Kamera-Clips erwartet, {len(cams)} gefunden."
        )
    if not mics:
        raise RuntimeError("Keine Mikrofon-Dateien gefunden (.wav / .aif).")

    # Korrektur total_steps falls Cam-Anzahl anders als erwartet
    total_steps = 4 + len(cams) + 2

    cam_paths = [str(c) for c in cams]
    mic_paths = [str(m) for m in mics]

    # Free-Tier-Grenze prüfen, bevor die schwere Arbeit (Sync) beginnt
    _enforce_free_tier(cam_paths, mic_paths)

    emit("scan_result",
         cameras=[c.name for c in cams],
         mics=[m.name for m in mics])

    # ── 2. Waveform-Sync ─────────────────────────────────────────────────────
    next_step("Waveform-Sync")
    try:
        offsets = sync_sources(
            cam_paths[0], cam_paths[1], mic_paths[0],
            fps=fps,
            additional_mics=mic_paths[1:],
        )
    except SyncError as e:
        raise RuntimeError(f"Waveform-Sync fehlgeschlagen: {e}")

    emit("sync_result", offsets={k: v for k, v in offsets.items()})

    # ── 3. Analyse-Pipeline ──────────────────────────────────────────────────
    n_cams = len(cams)
    cam_mic_map = _parse_cam_mics(cam_mics, n_cams, len(mics))
    cam_types = _parse_cam_list(cam_types_arg, n_cams, "close")
    cam_nodding = _parse_cam_nodding(cam_nodding_arg, n_cams)

    src_hash = hashlib.md5(str(folder).encode()).hexdigest()[:12]
    work_dir = Path(f"/tmp/resolve-toolkit/{src_hash}")
    work_dir.mkdir(parents=True, exist_ok=True)

    # run_analysis startet intern Subprocesses die ihre eigenen Logs schreiben.
    # Die Step-Beschreibungen (z.B. "Base-EDL aus Audio...") werden vom
    # JsonLineWriter als log-Zeilen emittiert. Wir emittieren hier die
    # step_start-Nachrichten VOR dem Aufruf fuer die bekannten Schritte.
    next_step("Diarization + Base-EDL")
    try:
        final_edl = run_analysis(
            cam_paths, mic_paths, offsets,
            fps, work_dir, params,
            skip_analysis=skip_analysis,
            skip_base_edl=skip_base_edl,
            cam_mic_map=cam_mic_map,
            cam_types=cam_types,
            cam_nodding=cam_nodding,
            speaking_mode_override=speaking_mode,
            auto_accuracy=False,
            lut_path=lut,
        )
    except RuntimeError as e:
        raise RuntimeError(f"Analyse-Pipeline: {e}")

    # ── 4. Pause-Trimming ────────────────────────────────────────────────────
    next_step("Pause-Trimming")
    audio_trims_path = work_dir / "audio_trims.json"
    audio_keeps = None
    trimmed_events = None

    if audio_trims_path.exists():
        try:
            from pause_trim_edl import load_pauses, apply_pauses_to_cut_events
            from modules.multicam_cutter.build_aaf import _parse_edl

            raw = json.loads(audio_trims_path.read_text())
            pauses = raw if isinstance(raw, list) and raw and isinstance(raw[0], dict) else None

            if pauses:
                trim_events = _parse_edl(final_edl, cam_paths, fps)
                if trim_events:
                    cam_sentinels = [object() for _ in cam_paths]
                    cursor = 0
                    for ev in trim_events:
                        ev["clip"] = cam_sentinels[ev["cam_index"]]
                        dur = ev["source_out"] - ev["source_in"]
                        ev["record_in"] = cursor
                        ev["record_out"] = cursor + dur
                        ev.setdefault("reason", "speaker")
                        cursor += dur

                    trim_events, audio_keeps = apply_pauses_to_cut_events(
                        trim_events, pauses, fps,
                        max_pause_s=float(params.get("max_pause", 1.0)),
                        cut_mode=params.get("pause_cut_mode", "middle"),
                        min_event_s=float(params.get("cleanup_dur", 1.5)),
                    )
                    if audio_keeps:
                        trimmed_events = trim_events
        except Exception as e:
            warning(f"Pause-Trim Fehler: {e}")
            audio_keeps = None

    # ── 5. AAF-Export ────────────────────────────────────────────────────────
    next_step("AAF-Export")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Default 1.0 = kein Zoom. Frueher 1.5: jede Totale wurde still auf 150%
    # skaliert. Die Cams sind ordentlich eingerichtet — der Zoom war unnoetig.
    wide_zoom = float(params.get("wide_zoom", 1.0))

    aaf_path = build_aaf(
        cam_paths=cam_paths,
        mic_paths=mic_paths,
        offsets=offsets,
        edl_path=final_edl,
        fps=fps,
        output=output_path,
        cam_types=cam_types,
        wide_zoom=wide_zoom,
        audio_keeps=audio_keeps,
        trimmed_events=trimmed_events,
    )

    emit("step_progress", percent=100, eta="")

    # ── Statistiken sammeln ──────────────────────────────────────────────────
    stats = {
        "cameras": len(cams),
        "mics": len(mics),
        "aaf": str(aaf_path),
        "edl": str(final_edl),
        "work_dir": str(work_dir),
    }

    # Event-Statistiken aus colors.json lesen
    colors_path = final_edl.with_suffix(".colors.json")
    if colors_path.exists():
        try:
            colors = json.loads(colors_path.read_text())
            reason_counts = {}
            for c in colors:
                r = c.get("reason", "speaker")
                reason_counts[r] = reason_counts.get(r, 0) + 1
            stats["events_total"] = len(colors)
            stats["events_by_type"] = reason_counts
        except Exception:
            pass

    return aaf_path, stats


# ── CLI Entry Point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Multicam Engine — Pipeline CLI mit JSON-Lines-Output"
    )
    parser.add_argument("--folder", default=None)
    parser.add_argument("--fps", type=float, default=25.0)
    parser.add_argument("--scan", action="store_true",
                        help="Nur Ordner scannen + Previews generieren, keine Analyse")
    parser.add_argument("--check-license", action="store_true",
                        help="Lizenzstatus prüfen und als JSON ausgeben")
    parser.add_argument("--install-license", default=None,
                        help="Lizenzdatei installieren (Pfad zur .json)")
    parser.add_argument("--set-key", default=None,
                        help="Lizenzschlüssel hinterlegen + aktivieren (Abo-Modus)")
    parser.add_argument("--clear-license", action="store_true",
                        help="Lokale Lizenz entfernen (deaktivieren)")
    parser.add_argument("--migrate-key", default=None,
                        help="Lizenz auf dieses Gerät umziehen (Takeover + aktivieren)")
    parser.add_argument("--params", default="{}", help="JSON-String oder Pfad zu .json")
    parser.add_argument("--output", default=None, help="AAF-Ausgabepfad")
    parser.add_argument("--check-clip-model", action="store_true",
                        help="Prueft, ob das CLIP-Modell lokal vorliegt (JSON-Ausgabe)")
    parser.add_argument("--download-clip-model", action="store_true",
                        help="Laedt das CLIP-Modell einmalig in den HF-Cache")
    parser.add_argument("--get-clip-prompts", action="store_true",
                        help="Gibt die aktiven CLIP-Ignore/Neutral-Prompts als JSON aus "
                             "(user-editierte Datei bevorzugt, sonst gebuendelte Defaults)")
    parser.add_argument("--get-nodding-patterns", action="store_true",
                        help="Gibt die aktive nodding_patterns.json als JSON aus "
                             "(roher Inhalt + source/user_path)")
    parser.add_argument("--convert-fps", action="store_true",
                        help="Video-Dateien aus --files auf --fps umkodieren "
                             "(behebt FPS-Mismatch, erhaelt den Embedded-TC)")
    parser.add_argument("--files", nargs="+", default=None,
                        help="Dateien fuer --convert-fps")
    parser.add_argument("--cams", nargs="+", default=None,
                        help="Explizite Kamera-Pfade (nur aktivierte Quellen). "
                             "Ohne diese Angabe scannt die Engine den Ordner selbst.")
    parser.add_argument("--mics", nargs="+", default=None,
                        help="Explizite Mic-Pfade (nur aktivierte Quellen).")
    parser.add_argument("--cam-mics", nargs="+", default=None)
    parser.add_argument("--cam-types", nargs="+", default=None)
    parser.add_argument("--cam-nodding", nargs="+", default=None)
    parser.add_argument("--skip-analysis", action="store_true")
    parser.add_argument("--skip-base-edl", action="store_true")
    parser.add_argument("--speaking-mode", choices=["rms", "peak"], default=None)
    parser.add_argument("--lut", default=None)
    parser.add_argument("--display-names", default=None,
                        help="JSON-Array mit Display-Namen fuer Kameras")
    args = parser.parse_args()

    # ── Lizenz-Operationen ──────────────────────────────────────────────────
    if args.check_license:
        try:
            from licensing.license import validate
            info = validate()
            result_json = json.dumps({
                "valid": info.valid,
                "email": info.email or "",
                "expires": info.expires or "",
                "modules": info.modules,
                "grace": info.grace,
                "status": info.status or "",
                "sub_status": info.sub_status or "",
                "renews_at": info.renews_at or "",
                "ends_at": info.ends_at or "",
                "error": info.error or "",
            })
            sys.__stdout__.write(result_json + "\n")
        except Exception as e:
            sys.__stdout__.write(json.dumps({"valid": False, "error": str(e)}) + "\n")
        return 0

    if args.install_license:
        try:
            from licensing.license import install_license
            info = install_license(args.install_license)
            result_json = json.dumps({
                "valid": info.valid,
                "email": info.email or "",
                "expires": info.expires or "",
                "modules": info.modules,
                "error": info.error or "",
            })
            sys.__stdout__.write(result_json + "\n")
        except Exception as e:
            sys.__stdout__.write(json.dumps({"valid": False, "error": str(e)}) + "\n")
        return 0

    if args.set_key:
        try:
            from licensing.license import set_license_key
            info = set_license_key(args.set_key)
            result_json = json.dumps({
                "valid": info.valid,
                "email": info.email or "",
                "expires": info.expires or "",
                "modules": info.modules,
                "grace": info.grace,
                "status": info.status or "",
                "sub_status": info.sub_status or "",
                "renews_at": info.renews_at or "",
                "ends_at": info.ends_at or "",
                "error": info.error or "",
            })
            sys.__stdout__.write(result_json + "\n")
        except Exception as e:
            sys.__stdout__.write(json.dumps({"valid": False, "error": str(e)}) + "\n")
        return 0

    if args.migrate_key:
        try:
            from licensing.license import migrate_license_key
            info = migrate_license_key(args.migrate_key)
            sys.__stdout__.write(json.dumps({
                "valid": info.valid,
                "email": info.email or "",
                "expires": info.expires or "",
                "modules": info.modules,
                "grace": info.grace,
                "status": info.status or "",
                "sub_status": info.sub_status or "",
                "renews_at": info.renews_at or "",
                "ends_at": info.ends_at or "",
                "error": info.error or "",
            }) + "\n")
        except Exception as e:
            sys.__stdout__.write(json.dumps({"valid": False, "error": str(e)}) + "\n")
        return 0

    if args.clear_license:
        try:
            from licensing.license import clear_license
            info = clear_license()
            sys.__stdout__.write(json.dumps({
                "valid": info.valid,
                "email": "",
                "expires": "",
                "modules": [],
                "error": info.error or "",
            }) + "\n")
        except Exception as e:
            sys.__stdout__.write(json.dumps({"valid": False, "error": str(e)}) + "\n")
        return 0

    # ── CLIP-Prompts lesen (leichtgewichtig, kein ffmpeg/torch nötig) ─────────
    if args.get_clip_prompts:
        from shared.paths import effective_clip_prompts_path, USER_CLIP_PROMPTS, CLIP_IGNORE
        path = effective_clip_prompts_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        print(json.dumps({
            "ignore": data.get("ignore", []),
            "neutral": data.get("neutral", []),
            "source": "user" if path == USER_CLIP_PROMPTS else "default",
            "user_path": str(USER_CLIP_PROMPTS),
            "default_path": str(CLIP_IGNORE),
        }, ensure_ascii=False))
        return 0

    if args.get_nodding_patterns:
        from shared.paths import effective_nodding_patterns_path, USER_NODDING_PATTERNS
        path = effective_nodding_patterns_path()
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            content = ""
        print(json.dumps({
            "content": content,
            "source": "user" if path == USER_NODDING_PATTERNS else "default",
            "user_path": str(USER_NODDING_PATTERNS),
        }, ensure_ascii=False))
        return 0

    # ── Scan-Modus (schnell, keine Analyse) ──────────────────────────────────
    # ffmpeg/ffprobe absichern, bevor irgendwas sie braucht (Scan, Convert, Pipeline).
    # Lizenz-Operationen oben brauchen sie nicht, deshalb erst hier.
    _ffmpeg_note = _ensure_ffmpeg_on_path()


    if args.check_clip_model:
        installed = _clip_model_installed()
        size = 0
        if not installed:
            try:
                size = _clip_download_size()
            except Exception:
                size = 0     # offline → Groesse unbekannt, UI zeigt dann Schaetzung
        print(json.dumps({"installed": installed, "download_bytes": size}))
        return 0

    if args.download_clip_model:
        try:
            download_clip_model()
            emit("clip_download_complete")
            return 0
        except Exception as e:
            emit("error", message=f"Download fehlgeschlagen: {e}")
            return 1

    # Ab hier: kein Hub-Kontakt mehr. transformers wuerde sonst beim Modell-Laden
    # nachfragen ("You are sending unauthenticated requests to the HF Hub") — das
    # widerspricht dem Versprechen "100 % lokal & offline" und macht uns von Netz/
    # HF-Verfuegbarkeit abhaengig.
    # ⚠️ MUSS nach --check-clip-model/--download-clip-model stehen: huggingface_hub
    # liest HF_HUB_OFFLINE beim IMPORT in eine Konstante. Steht die Sperre vorher,
    # blockiert sie den vom User angeforderten Download — und ein spaeteres
    # os.environ.pop() wirkt nicht mehr.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    if args.convert_fps:
        if not args.files:
            emit("error", message="--files ist erforderlich für --convert-fps")
            return 1
        try:
            outputs = convert_fps_files(args.files, args.fps)
            emit("convert_complete", outputs=outputs)
            return 0
        except Exception as e:
            emit("error", message=str(e))
            return 1

    if args.scan:
        if not args.folder:
            emit("error", message="--folder ist erforderlich für --scan")
            return 1
        folder = Path(args.folder).resolve()
        try:
            scan_result = run_scan(folder, args.fps)
            # Scan-Ergebnis als einzelnes JSON-Objekt ausgeben
            emit("scan_complete", **scan_result)
            return 0
        except Exception as e:
            emit("error", message=str(e))
            return 1

    if not args.folder:
        emit("error", message="--folder ist erforderlich")
        return 1
    folder = Path(args.folder).resolve()

    # Params: JSON-String oder Dateipfad
    if args.params.startswith("{"):
        params = json.loads(args.params)
    else:
        params = json.loads(Path(args.params).read_text())

    # Output-Pfad: Default = folder/final.aaf
    output_path = Path(args.output) if args.output else folder / "final.aaf"

    # ── Logging Setup ────────────────────────────────────────────────────────
    log_dir = Path.home() / "Library" / "Logs" / "MulticamCutter"
    log_dir.mkdir(parents=True, exist_ok=True)

    safe_name = folder.name.replace("/", "_").replace(" ", "_")
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = log_dir / f"{timestamp}_{safe_name}.jsonl"
    log_file = open(log_path, "w", encoding="utf-8")

    # Display-Namen parsen (fuer Progress-Labels)
    display_names_map = {}
    if args.display_names:
        try:
            names_list = json.loads(args.display_names)
            # Ordner scannen um Dateinamen den Display-Namen zuzuordnen
            cams_scan, _ = scan_folder(folder)
            for i, cam in enumerate(cams_scan):
                if i < len(names_list):
                    display_names_map[cam.name] = names_list[i]
        except Exception:
            pass

    # stdout durch JsonLineWriter ersetzen
    sys.stdout = JsonLineWriter(log_file=log_file, display_names=display_names_map)
    sys.stderr = sys.stdout  # stderr auch abfangen

    # ── Session-Start loggen ─────────────────────────────────────────────────
    if _ffmpeg_note:
        emit("log", message=_ffmpeg_note)

    emit("session_start",
         version="0.1.0",
         folder=str(folder),
         fps=args.fps,
         params=params,
         output=str(output_path),
         system={
             "os": platform.platform(),
             "python": platform.python_version(),
             "chip": platform.machine(),
         },
         log_file=str(log_path))

    # ── Pipeline ausfuehren ──────────────────────────────────────────────────
    t_start = time.time()
    try:
        aaf_path, stats = run_pipeline(
            folder=folder,
            fps=args.fps,
            params=params,
            output_path=output_path,
            cams_arg=args.cams,
            mics_arg=args.mics,
            cam_mics=args.cam_mics,
            cam_types_arg=args.cam_types,
            cam_nodding_arg=args.cam_nodding,
            skip_analysis=args.skip_analysis,
            skip_base_edl=args.skip_base_edl,
            speaking_mode=args.speaking_mode,
            lut=args.lut,
        )
        elapsed = time.time() - t_start
        stats["elapsed_s"] = round(elapsed, 1)
        stats["log_file"] = str(log_path)
        progress("done", 100, "Fertig")
        result(**stats)

    except Exception as e:
        elapsed = time.time() - t_start
        msg = str(e)
        # Bei ffmpeg/ffprobe-Fehlern die Fakten mitgeben statt raten zu muessen
        # (siehe brain/Bekannte-Bugs.md → "ffmpeg nicht gefunden in PASS 5").
        if "ffmpeg" in msg or "ffprobe" in msg:
            msg += "  ||  " + _ffmpeg_diagnostics()
        error(message=msg)
        emit("session_end", success=False, elapsed_s=round(elapsed, 1))
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        log_file.close()
        return 1

    emit("session_end", success=True, elapsed_s=round(elapsed, 1))
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    log_file.close()
    return 0


if __name__ == "__main__":
    # MUSS als Allererstes kommen — vor jedem argparse/Import-Nebeneffekt.
    # Torch/CLIP starten Kindprozesse (z.B. multiprocessing.resource_tracker).
    # Im Frozen-Bundle ist sys.executable DIESE Engine, das Kind wird also mit
    # `-B -S -I -c "from multiprocessing.resource_tracker import main;main(13)"`
    # neu gestartet → unser argparse warf "unrecognized arguments".
    # freeze_support() faengt genau diesen Re-Exec ab und fuehrt das Kind korrekt aus.
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
