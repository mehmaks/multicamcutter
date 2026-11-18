"""Mund-Aktivitaet — Stufe 2: Rohdaten je Kamerabild aufzeichnen (KEINE Schwellen).

Versuch (18.11.2026, Folge 61): Kann MediaPipe am Mund erkennen, wann eine gerade
NICHT sprechende Person etwas sagt? Dieses Skript misst nur. Bewertet wird erst in
auswerten.py, damit Schwellen beliebig variiert werden koennen, ohne das Video
erneut zu analysieren.

Aufruf:
    venv/bin/python3 analyse/mund_aktivitaet/aufzeichnen.py VIDEO AUSGABE.npz [--width 1280]

Je Bild (Index = Bildnummer der Quelldatei):
    face        1 = Gesicht gefunden
    face_h      Gesichtshoehe (Stirn 10 → Kinn 152), Anteil der Bildhoehe
    gap_inner   Lippenabstand innen (13 ↔ 14) / Gesichtshoehe
    gap_outer   Lippenabstand aussen (0 ↔ 17) / Gesichtshoehe
    mouth_w     Mundbreite (61 ↔ 291) / Gesichtshoehe
    yaw         Nasenruecken relativ zur Augenmitte (−1 … 1, 0 = frontal)
    pitch       Nase relativ zu Stirn/Kinn (0,5 ≈ geradeaus)
    bs          alle 52 Blendshapes von MediaPipe (jawOpen, mouthClose, …)
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "modules" / "multicam_cutter" / "face_landmarker.task"


def probe(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate:format=duration",
         "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True).stdout.split()
    w, h, rate = out[0].split(",")[:3]
    num, den = rate.split("/")
    fps = float(num) / float(den)
    dur = float(out[1].strip(","))
    # Bildzahl aus Dauer (kein -count_packets: das liest 100 GB einmal komplett)
    return int(w), int(h), fps, int(round(dur * fps))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--max-seconds", type=float, default=None,
                    help="nur die ersten N Sekunden aufzeichnen")
    a = ap.parse_args()

    w0, h0, fps, n_frames = probe(a.video)
    if a.max_seconds:
        n_frames = min(n_frames, int(a.max_seconds * fps))
    fw = a.width
    fh = int(h0 * fw / w0)
    fh += fh % 2
    print(f"{Path(a.video).name}: {w0}×{h0} → {fw}×{fh}, {fps:.3f} fps, {n_frames} Bilder", flush=True)

    opts = mp_vision.FaceLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=str(MODEL)),
        running_mode=mp_vision.RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
        output_face_blendshapes=True,
    )
    lm = mp_vision.FaceLandmarker.create_from_options(opts)

    n = n_frames + 10                       # Puffer, falls nb_read_packets knapp ist
    face = np.zeros(n, np.uint8)
    cols = {k: np.full(n, np.nan, np.float32)
            for k in ("face_h", "gap_inner", "gap_outer", "mouth_w", "yaw", "pitch")}
    bs = np.full((n, 52), np.nan, np.float32)
    bs_names = None

    cmd = ["ffmpeg", "-v", "error", "-hwaccel", "videotoolbox", "-i", str(a.video),
           "-vf", f"scale={fw}:{fh}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=fw * fh * 3 * 4)
    frame_bytes = fw * fh * 3
    i, t0 = 0, time.time()
    while True:
        buf = proc.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        if i >= n or (a.max_seconds and i >= n_frames):
            break
        img = np.frombuffer(buf, np.uint8).reshape(fh, fw, 3)
        res = lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=img),
                                  int(i * 1000 / fps))
        if res.face_landmarks:
            L = res.face_landmarks[0]
            fhgt = abs(L[152].y - L[10].y)
            if fhgt > 0:
                face[i] = 1
                cols["face_h"][i] = fhgt
                cols["gap_inner"][i] = abs(L[14].y - L[13].y) / fhgt
                cols["gap_outer"][i] = abs(L[17].y - L[0].y) / fhgt
                # Breite im Pixelraum (x und y haben verschiedene Skalen)
                dx = (L[291].x - L[61].x) * fw
                dy = (L[291].y - L[61].y) * fh
                cols["mouth_w"][i] = float(np.hypot(dx, dy)) / (fhgt * fh)
                eye_mid = (L[33].x + L[263].x) / 2
                eye_span = abs(L[263].x - L[33].x) or 1e-6
                cols["yaw"][i] = (L[6].x - eye_mid) / eye_span * 2
                cols["pitch"][i] = (L[1].y - L[10].y) / fhgt
            if res.face_blendshapes:
                cats = res.face_blendshapes[0]
                if bs_names is None:
                    bs_names = [c.category_name for c in cats]
                bs[i, :len(cats)] = [c.score for c in cats]
        i += 1
        if i % 5000 == 0:
            el = time.time() - t0
            print(f"  {i}/{n_frames} ({i / n_frames:.0%}) — {i / el:.0f} Bilder/s, "
                  f"Rest ~{(n_frames - i) / (i / el) / 60:.0f} min", flush=True)
    proc.stdout.close()
    proc.wait()

    np.savez_compressed(
        a.out, fps=fps, n=i, face=face[:i], bs=bs[:i],
        bs_names=np.array(bs_names or [], dtype=object),
        **{k: v[:i] for k, v in cols.items()})
    print(f"fertig: {i} Bilder in {(time.time() - t0) / 60:.1f} min, "
          f"Gesicht in {face[:i].mean():.1%} → {a.out}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
