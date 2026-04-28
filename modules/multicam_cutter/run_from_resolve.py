#!/usr/bin/env python3
"""
Resolve-integrated multicam EDL workflow.

Reads the current DaVinci Resolve timeline directly — no manual file paths
or sync offsets needed. Resolve must be open with a synced timeline active.

Expected timeline layout:
  Video Track 1  →  CAM1 (main speaker / Seb)
  Video Track 2  →  CAM2 (guest / reaction cam)
  Audio Track 1  →  MIC for CAM2  (NOTE: MIC numbering is inverted vs CAM)
  Audio Track 2  →  MIC for CAM1

Usage:
    python run_from_resolve.py --output final.edl
    python run_from_resolve.py --output final.edl --skip-analysis
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path

# Resolve-toolkit root
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from resolve_bridge.timeline_reader import read_timeline, get_primary_wav_clip
from resolve_bridge.project import import_edl


SCRIPT_DIR = Path(__file__).parent


def run_command(cmd: list, description: str) -> bool:
    print(f"\n{'='*70}")
    print(f"  {description}")
    print(f"{'='*70}")
    result = subprocess.run([sys.executable] + cmd)
    if result.returncode != 0:
        print(f"\nFEHLER in: {description} (exit {result.returncode})")
        return False
    print(f"\nErfolgreich: {description}")
    return True


def confirm_or_abort(message: str) -> bool:
    """Prints a warning and asks the user to continue or abort."""
    print(f"\n{'!'*70}")
    print(f"  WARNUNG")
    print(f"{'!'*70}")
    print(message)
    print()
    answer = input("Trotzdem fortfahren? [j/N] ").strip().lower()
    return answer in ("j", "ja", "y", "yes")


def main():
    parser = argparse.ArgumentParser(
        description="Multicam EDL Workflow — liest direkt aus Resolve"
    )
    parser.add_argument("--output", "-o", default="final_resolve.edl",
                        help="Ausgabe-EDL (default: final_resolve.edl)")
    parser.add_argument("--config", default=str(ROOT / "config" / "config.ini"),
                        help="Pfad zur config.ini")
    parser.add_argument("--skip-analysis", action="store_true",
                        help="Nodding-Analyse überspringen (JSONs müssen existieren)")
    parser.add_argument("--skip-base-edl", action="store_true",
                        help="Base-EDL-Schritt überspringen (base.edl muss existieren)")
    parser.add_argument("--import-to-resolve", action="store_true",
                        help="Fertige EDL direkt in Resolve importieren")
    parser.add_argument("--output-dir", default=None,
                        help="Ausgabe-Verzeichnis (default: Verzeichnis von CAM1)")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # 1. Timeline aus Resolve lesen
    # ------------------------------------------------------------------
    print("\n" + "="*70)
    print("  MULTICAM EDL WORKFLOW — RESOLVE INTEGRATION")
    print("="*70)
    print("Lese Timeline aus DaVinci Resolve...")

    try:
        tl = read_timeline()
    except RuntimeError as e:
        print(f"\nFEHLER: {e}")
        return 1

    print(f"  Timeline:  {tl.timeline_name}")
    print(f"  FPS:       {tl.fps}")
    print(f"  Dauer:     {(tl.timeline_end - tl.timeline_start) / tl.fps:.1f}s "
          f"({tl.timeline_end - tl.timeline_start} Frames)")

    # ------------------------------------------------------------------
    # 2. Warnings prüfen — bei Problemen Abbruch anbieten
    # ------------------------------------------------------------------
    if tl.warnings:
        warning_text = "\n".join(f"  - {w}" for w in tl.warnings)
        if not confirm_or_abort(warning_text):
            print("Abgebrochen.")
            return 0

    # ------------------------------------------------------------------
    # 3. Spuren zuordnen
    # ------------------------------------------------------------------
    if 1 not in tl.video_tracks or 2 not in tl.video_tracks:
        print("\nFEHLER: Mindestens 2 Videospuren mit je einem Clip erwartet.")
        return 1
    if 1 not in tl.audio_tracks or 2 not in tl.audio_tracks:
        print("\nFEHLER: Mindestens 2 Audiospuren mit WAV-Clips erwartet.")
        return 1

    cam1_clip = tl.video_tracks[1][0]   # V1 = CAM1
    cam2_clip = tl.video_tracks[2][0]   # V2 = CAM2

    # MIC-Nummerierung ist invertiert: MIC1 (A1) gehört zu CAM2, MIC2 (A2) zu CAM1
    mic_cam2 = get_primary_wav_clip(tl.audio_tracks[1])  # A1 = MIC1 → CAM2
    mic_cam1 = get_primary_wav_clip(tl.audio_tracks[2])  # A2 = MIC2 → CAM1

    if mic_cam1 is None or mic_cam2 is None:
        print("\nFEHLER: Keine WAV-Dateien auf den Audiospuren 1/2 gefunden.")
        return 1

    print(f"\n  Spuren erkannt:")
    print(f"    CAM1 (V1): {cam1_clip.clip_name}  [offset: {cam1_clip.sync_offset_frames} frames]")
    print(f"    CAM2 (V2): {cam2_clip.clip_name}  [offset: {cam2_clip.sync_offset_frames} frames]")
    print(f"    MIC→CAM1:  {mic_cam1.clip_name}  [offset: {mic_cam1.sync_offset_frames} frames]")
    print(f"    MIC→CAM2:  {mic_cam2.clip_name}  [offset: {mic_cam2.sync_offset_frames} frames]")

    # Dateizugriff prüfen
    for label, path in [
        ("CAM1", cam1_clip.file_path), ("CAM2", cam2_clip.file_path),
        ("MIC→CAM1", mic_cam1.file_path), ("MIC→CAM2", mic_cam2.file_path),
    ]:
        if not os.path.exists(path):
            print(f"\nFEHLER: Datei nicht erreichbar ({label}): {path}")
            return 1

    # ------------------------------------------------------------------
    # 4. Ausgabe-Verzeichnis
    # ------------------------------------------------------------------
    out_dir = Path(args.output_dir) if args.output_dir else Path(cam1_clip.file_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    base_edl      = str(out_dir / "base.edl")
    cam1_json     = str(out_dir / (Path(cam1_clip.file_path).stem + "_reactions.json"))
    cam2_json     = str(out_dir / (Path(cam2_clip.file_path).stem + "_reactions.json"))
    output_edl    = str(out_dir / args.output)

    # ------------------------------------------------------------------
    # 5. Nodding-Analyse
    # ------------------------------------------------------------------
    if not args.skip_analysis:
        analyzer = str(SCRIPT_DIR / "video_reaction_analyzer_v2.4.py")
        for label, video_path, json_path in [
            ("CAM1", cam1_clip.file_path, cam1_json),
            ("CAM2", cam2_clip.file_path, cam2_json),
        ]:
            if not run_command(
                [analyzer, video_path, "--output", json_path, "--config", args.config],
                f"Nodding-Analyse {label}"
            ):
                return 1
    else:
        print("\nNodding-Analyse übersprungen (--skip-analysis).")

    # ------------------------------------------------------------------
    # 6. Base-EDL aus Audio
    # ------------------------------------------------------------------
    if not args.skip_base_edl:
        builder = str(SCRIPT_DIR / "build_base_edl_from_audio.py")
        cmd = [
            builder,
            "--mic-cam1",      mic_cam1.file_path,
            "--mic-cam2",      mic_cam2.file_path,
            "--cam1-video",    cam1_clip.file_path,
            "--cam2-video",    cam2_clip.file_path,
            "--cam1-clip",     cam1_clip.clip_name,
            "--cam2-clip",     cam2_clip.clip_name,
            "--wav-edl-frame",  str(mic_cam1.sync_offset_frames),
            "--cam1-edl-frame", str(cam1_clip.sync_offset_frames),
            "--cam2-edl-frame", str(cam2_clip.sync_offset_frames),
            "--fps",            str(tl.fps),
            "--output",         base_edl,
        ]
        if not run_command(cmd, "Base-EDL aus Audio"):
            return 1
    else:
        print("\nBase-EDL übersprungen (--skip-base-edl).")

    # ------------------------------------------------------------------
    # 7. Nodding-Cutaways hinzufügen
    # ------------------------------------------------------------------
    adder = str(SCRIPT_DIR / "add_reactions_to_edl.py")
    cmd = [
        adder,
        "--resolve-edl",    base_edl,
        "--cam1-clip",      cam1_clip.clip_name,
        "--cam1-reactions", cam1_json,
        "--cam2-clip",      cam2_clip.clip_name,
        "--cam2-reactions", cam2_json,
        "--cam1-video",     cam1_clip.file_path,
        "--cam2-video",     cam2_clip.file_path,
        "--output",         output_edl,
        "--config",         args.config,
    ]
    if not run_command(cmd, "Nodding-Cutaways einfügen"):
        return 1

    # ------------------------------------------------------------------
    # 8. EDL direkt in Resolve importieren (optional)
    # ------------------------------------------------------------------
    if args.import_to_resolve:
        print(f"\nImportiere EDL in Resolve...")
        try:
            timeline_name = Path(output_edl).stem
            imported = import_edl(output_edl, timeline_name)
            print(f"Timeline '{imported}' in Resolve angelegt.")
        except RuntimeError as e:
            print(f"Resolve-Import fehlgeschlagen: {e}")
            print(f"EDL liegt unter: {output_edl}")

    # ------------------------------------------------------------------
    print("\n" + "="*70)
    print("  WORKFLOW ABGESCHLOSSEN")
    print("="*70)
    print(f"  base.edl:     {base_edl}")
    print(f"  finale EDL:   {output_edl}")
    if not args.import_to_resolve:
        print(f"\n  Tipp: Mit --import-to-resolve wird die EDL direkt in Resolve geladen.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
