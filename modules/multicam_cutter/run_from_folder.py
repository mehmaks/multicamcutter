#!/usr/bin/env python3
"""
Resolve-freier Multicam-Workflow: Ordner → AAF

Analysiert einen Ordner mit Kamera- und Mikrofon-Dateien komplett ohne
DaVinci Resolve. Unterstützt beliebig viele Kameras (N) und Mikrofone (M).
Ausgabe: final.aaf (importierbar in Resolve, Premiere Pro, Avid).

Voraussetzungen im Ordner:
  - Mindestens 2 Video-Dateien (.mp4 / .mov / .mxf), alphabetisch sortiert
    → Erste Datei = CAM1, zweite Datei = CAM2 (Hauptsprecher-Erkennung)
    → Weitere Dateien = CAM3+ (nur als Cutaway-Quelle)
  - Mindestens 1 Audio-Datei (.wav / .aif)
    → Zuordnung zu CAM1/CAM2 via --mic-cam1 / --mic-cam2

Verwendung:
    python run_from_folder.py --folder /Pfad/zur/Episode
    python run_from_folder.py --folder /Pfad/zur/Episode --mic-cam1 1 --mic-cam2 0
"""

import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from shared.waveform_sync import sync_sources, SyncError
from modules.multicam_cutter.run_from_bin import (
    run_analysis, _parse_cam_mics, _parse_cam_list, _parse_cam_nodding
)
from modules.multicam_cutter.build_aaf import build_aaf

SCRIPT_DIR = Path(__file__).parent

VIDEO_EXT = {'.mp4', '.mov', '.mxf', '.r3d', '.ari'}
AUDIO_EXT = {'.wav', '.aif', '.aiff'}


def scan_folder(folder: Path) -> dict:
    """Scannt einen Ordner nach CAM- und MIC-Dateien (alphabetisch sortiert)."""
    all_files = sorted(f for f in folder.iterdir() if f.is_file())
    cams = [f for f in all_files if f.suffix.lower() in VIDEO_EXT]
    mics = [f for f in all_files if f.suffix.lower() in AUDIO_EXT]
    return {'cam': cams, 'mic': mics}


def main():
    parser = argparse.ArgumentParser(
        description='Multicam Workflow ohne Resolve: Ordner → final.edl'
    )
    parser.add_argument('--folder',   required=True, help='Ordner mit CAM- und MIC-Dateien')
    parser.add_argument('--fps',      type=float, default=25.0)
    parser.add_argument('--config',   default=str(ROOT / 'config' / 'config.ini'))
    parser.add_argument('--skip-analysis',  action='store_true',
                        help='Nodding-Analyse überspringen (JSONs müssen bereits existieren)')
    parser.add_argument('--skip-base-edl',  action='store_true',
                        help='Base-EDL überspringen (base.edl muss bereits existieren)')
    parser.add_argument('--cam-mics', nargs='+', default=None,
                        help='MIC-Zuordnung pro Kamera als "INDEX[,INDEX]" je CAM. '
                             'Reihenfolge = CAM1, CAM2, ... '
                             'Beispiele: "1 0" (Default) oder "0,1 2" (CAM1→MIC1+MIC2, CAM2→MIC3)')
    parser.add_argument('--cam-types', nargs='+', default=None,
                        help='Kamera-Typ je CAM: "close" (default) oder "wide". '
                             'Beispiel: "close close wide"')
    parser.add_argument('--cam-nodding', nargs='+', default=None,
                        help='Nodding-Analyse je CAM: "true" (default) oder "false". '
                             'Beispiel: "true true false"')
    parser.add_argument('--speaking-mode', choices=['rms', 'peak'], default=None,
                        help='Überschreibt speaking_mode aus config.ini')
    parser.add_argument('--auto-accuracy', action='store_true',
                        help='Nodding-Threshold dynamisch an erkannte Gesichtsgröße anpassen')
    parser.add_argument('--lut', default=None,
                        help='Pfad zu einer .cube LUT-Datei für die Mediapipe-Analyse')
    args = parser.parse_args()

    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        print(f"FEHLER: Ordner nicht gefunden: {folder}")
        return 1

    # ── 1. Ordner scannen ─────────────────────────────────────────────────────
    print(f"\nScanne Ordner: '{folder.name}'")
    media = scan_folder(folder)
    cams, mics = media['cam'], media['mic']

    if len(cams) < 2:
        print(f"FEHLER: Mindestens 2 Kamera-Clips erwartet, {len(cams)} gefunden.")
        if cams:
            print(f"  Gefunden: {[f.name for f in cams]}")
        return 1
    if not mics:
        print("FEHLER: Keine Mikrofon-Dateien gefunden (.wav / .aif).")
        return 1

    cam_paths = [str(c) for c in cams]
    mic_paths = [str(m) for m in mics]

    for i, c in enumerate(cams):
        label = f"CAM{i + 1}" + (" (Sprecher-Erkennung)" if i < 2 else " (Cutaway)")
        print(f"  {label}: {c.name}")
    for i, m in enumerate(mics):
        print(f"  MIC{i+1}: {m.name}")

    # ── 2. Waveform-Sync ──────────────────────────────────────────────────────
    print()
    try:
        offsets = sync_sources(
            cam_paths[0], cam_paths[1], mic_paths[0],
            fps=args.fps,
            additional_mics=mic_paths[1:],
        )
    except SyncError as e:
        print(f"\nFEHLER beim Waveform-Sync: {e}")
        return 1

    print(f"\nSync-Offsets (relativ zu CAM1):")
    for label, frames in offsets.items():
        sign = '+' if frames >= 0 else ''
        print(f"  {label}: {sign}{frames} frames ({sign}{frames / args.fps:.2f}s)")

    # ── 3. Analyse-Pipeline → final.edl ──────────────────────────────────────
    import configparser
    _cfg = configparser.ConfigParser()
    _cfg.read(args.config)
    wide_zoom = _cfg.getfloat('General', 'wide_zoom', fallback=1.5)

    n_cams      = len(cams)
    cam_mic_map = _parse_cam_mics(args.cam_mics,    n_cams, len(mics))
    cam_types   = _parse_cam_list(args.cam_types,   n_cams, 'close')
    cam_nodding = _parse_cam_nodding(args.cam_nodding, n_cams)
    import hashlib
    _src_hash = hashlib.md5(str(folder).encode()).hexdigest()[:12]
    work_dir = Path(f'/tmp/resolve-toolkit/{_src_hash}')
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        final_edl = run_analysis(
            cam_paths, mic_paths, offsets,
            args.fps, work_dir, Path(args.config),
            skip_analysis=args.skip_analysis,
            skip_base_edl=args.skip_base_edl,
            cam_mic_map=cam_mic_map,
            cam_types=cam_types,
            cam_nodding=cam_nodding,
            speaking_mode_override=args.speaking_mode,
            auto_accuracy=args.auto_accuracy,
            lut_path=args.lut,
        )
    except RuntimeError as e:
        print(f"\nFEHLER in Analyse-Pipeline: {e}")
        return 1

    # ── 4. AAF generieren ────────────────────────────────────────────────────
    final_aaf = None
    try:
        final_aaf = build_aaf(
            cam_paths=cam_paths,
            mic_paths=mic_paths,
            offsets=offsets,
            edl_path=final_edl,
            fps=args.fps,
            output=folder / 'final.aaf',
            cam_types=cam_types,
            wide_zoom=wide_zoom,
        )
    except Exception as e:
        print(f"\nWarnung: AAF-Generierung fehlgeschlagen: {e}")

    # ── 5. Ergebnis ───────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"✅ Workflow abgeschlossen — kein Resolve benötigt.")
    print(f"{'=' * 60}")
    print(f"\n  Ausgabe-AAF:   {final_aaf or '(fehlgeschlagen)'}")
    print(f"  Ausgabe-EDL:   {final_edl}  (Fallback, nur Video)")
    print(f"\n  Import: Datei → Import → final.aaf")
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
