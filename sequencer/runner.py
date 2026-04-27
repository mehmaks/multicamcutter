"""Sequencer Runner — CLI-Einstiegspunkt für Pipeline-Ausführung.

Lädt ein Preset, baut den PipelineContext auf, sammelt Parameter
und führt die Pipeline aus. Progress-Output kompatibel mit der UI.

Usage:
    python -m sequencer.runner --preset multicam_cutter --bin "30 - Ebra" \
        --output "JU 30 Final" --fps 25

    python -m sequencer.runner --preset multicam_cutter --folder /path/to/media \
        --fps 25
"""

from __future__ import annotations

import argparse
import configparser
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Resolve-Toolkit Root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sequencer.context import PipelineContext
from sequencer.pipeline import Pipeline, PipelineError
from sequencer.registry import Registry


def _build_params_from_config(
    config_path: Path,
    cli_overrides: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Baut per-Modul Parameter aus config.ini + CLI-Overrides.

    Mapping von config.ini-Sections auf Modul-Parameter:
        [Crossbleed]     → crossbleed_gate
        [RMSGate]        → crossbleed_gate (Legacy-Alias)
        [Diarization]    → rms_diarize
        [SpeakingReactions] → speaking_reactions
        [PauseTrim]      → pause_trim
        [Nodding]        → nodding_analysis
        [Cutaways]       → cutaway_insertion
        [CleanupShort]   → cleanup_short_events
        [SplitLong]      → split_long_shots
        [ClipFilter]     → clip_filter
    """
    params: Dict[str, Dict[str, Any]] = {}

    if config_path and config_path.exists():
        cfg = configparser.ConfigParser()
        cfg.read(str(config_path), encoding="utf-8")

        # Config-Section → Modul-Name + Parameter-Mapping
        SECTION_MAP = {
            "Crossbleed": "crossbleed_gate",
            "RMSGate": "crossbleed_gate",
            "Diarization": "rms_diarize",
            "SpeakingReactions": "speaking_reactions",
            "PauseTrim": "pause_trim",
            "Nodding": "nodding_analysis",
            "Cutaways": "cutaway_insertion",
            "CleanupShort": "cleanup_short_events",
            "SplitLong": "split_long_shots",
            "ClipFilter": "clip_filter",
        }

        for section_name, module_name in SECTION_MAP.items():
            if section_name in cfg:
                mod_params = params.setdefault(module_name, {})
                for key, val in cfg[section_name].items():
                    # Typen konvertieren
                    mod_params[key] = _auto_type(val)

    # CLI-Overrides einmischen
    for key, val in cli_overrides.items():
        if "." in key:
            mod_name, param_name = key.split(".", 1)
            params.setdefault(mod_name, {})[param_name] = val
        else:
            # Global-Params gehen an alle Module
            for mod_params in params.values():
                mod_params.setdefault(key, val)

    return params


def _auto_type(val: str) -> Any:
    """Konvertiert config.ini String-Werte in passende Python-Typen."""
    if val.lower() in ("true", "yes", "on"):
        return True
    if val.lower() in ("false", "no", "off"):
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _progress_callback(fraction: float, module_name: str, message: str) -> None:
    """Gibt Fortschritt in einem Format aus, das die UI parsen kann."""
    pct = fraction * 100
    # Modul-Start/Ende
    if message:
        print(f"[{pct:5.1f}%] [{module_name}] {message}", flush=True)


def run_sequencer(
    preset_name: str,
    source_mode: str,
    fps: float = 25.0,
    work_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
    ingest_params: Optional[Dict[str, Any]] = None,
    cli_overrides: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    progress_callback: Optional[Any] = None,
) -> int:
    """Führt eine Sequencer-Pipeline aus.

    Args:
        preset_name: Name des Presets (z.B. "multicam_cutter")
        source_mode: "resolve_bin", "folder" oder "file"
        fps: Framerate
        work_dir: Arbeitsverzeichnis (für Zwischendateien)
        config_path: Pfad zur config.ini
        ingest_params: Parameter für das Ingest-Modul
        cli_overrides: Zusätzliche Parameter-Overrides
        dry_run: Nur validieren, nicht ausführen
        progress_callback: (fraction, module_name, message) -> None
            Wenn None, wird auf stdout geschrieben.

    Returns:
        Exit-Code (0 = Erfolg)
    """
    print(f"\n{'='*60}")
    print(f"Sequencer: {preset_name}")
    print(f"{'='*60}")

    # 1. Module laden
    try:
        modules = Registry.load_preset(preset_name)
    except (FileNotFoundError, KeyError) as e:
        print(f"FEHLER: {e}")
        return 1

    print(f"  {len(modules)} Module geladen")
    for i, mod in enumerate(modules, 1):
        print(f"    {i:2d}. {mod.name:<30s} [{mod.category}]")

    # 2. Context aufbauen
    if work_dir is None:
        work_dir = Path.cwd() / "analyse"
    work_dir.mkdir(parents=True, exist_ok=True)

    ctx = PipelineContext(work_dir=work_dir, fps=fps)

    # 3. Parameter sammeln
    params = _build_params_from_config(
        config_path or Path(),
        cli_overrides or {},
    )

    # Ingest-Params setzen
    ingest_p = params.setdefault("ingest", {})
    ingest_p["source_mode"] = source_mode
    if ingest_params:
        ingest_p.update(ingest_params)

    # 4. Pipeline bauen + validieren
    pipeline = Pipeline(modules, ctx)
    errors = pipeline.validate()
    if errors:
        print(f"\nValidierungs-Fehler:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"\n  Validierung OK")

    if dry_run:
        print("\n  Dry-Run — keine Ausführung")
        return 0

    # 5. Pipeline ausführen
    print(f"\n{'─'*60}")
    t_start = time.time()
    cb = progress_callback or _progress_callback

    try:
        pipeline.run(params, progress_callback=cb)
    except PipelineError as e:
        print(f"\n{'─'*60}")
        print(f"FEHLER in Modul '{e.module}' (Schritt {e.step}):")
        print(f"  {e.original_error}")
        print(f"  Context-Keys: {e.context_keys}")
        return 1

    elapsed = time.time() - t_start
    print(f"\n{'─'*60}")
    print(f"Pipeline abgeschlossen in {elapsed:.1f}s")
    print(f"  Context-Keys: {sorted(ctx.keys())}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Sequencer Runner — Modulare Pipeline ausführen"
    )
    parser.add_argument(
        "--preset", default=None,
        help="Name des Presets (z.B. 'multicam_cutter')"
    )
    parser.add_argument("--fps", type=float, default=25.0)
    parser.add_argument(
        "--config", default=None,
        help="Pfad zur config.ini"
    )
    parser.add_argument(
        "--work-dir", default=None,
        help="Arbeitsverzeichnis für Zwischendateien"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Nur validieren, nicht ausführen")
    parser.add_argument("--list-presets", action="store_true",
                        help="Verfügbare Presets auflisten")

    # Ingest-Optionen
    ingest_group = parser.add_argument_group("Ingest (Quellen)")
    ingest_group.add_argument(
        "--bin", default=None,
        help="Resolve Media Pool Bin-Name"
    )
    ingest_group.add_argument(
        "--folder", default=None,
        help="Ordner-Pfad für Folder-Modus"
    )
    ingest_group.add_argument(
        "--file", default=None,
        help="Einzeldatei-Pfad"
    )
    ingest_group.add_argument("--output", default=None,
                              help="Name der Ausgabe-Timeline")

    # Kamera-Optionen
    cam_group = parser.add_argument_group("Kamera-Zuordnung")
    cam_group.add_argument(
        "--cam-mics", nargs="+", default=None,
        help='MIC-Zuordnung pro CAM als "INDEX[,INDEX]"'
    )
    cam_group.add_argument("--cam-types", nargs="+", default=None)
    cam_group.add_argument("--cam-nodding", nargs="+", default=None)

    # Nodding-Optionen
    cam_group.add_argument("--auto-accuracy", action="store_true")
    cam_group.add_argument("--lut", default=None)

    # Legacy
    cam_group.add_argument("--mic-cam1", type=int, default=None)
    cam_group.add_argument("--mic-cam2", type=int, default=None)

    # Zusätzliche Parameter als key=value
    parser.add_argument(
        "--param", nargs="*", metavar="MODULE.KEY=VALUE",
        help="Zusätzliche Parameter als modul.key=value"
    )

    args = parser.parse_args()

    # List presets
    if args.list_presets:
        Registry.discover()
        for p in Registry.list_presets():
            print(f"  {p['name']:<25s} {p['title']} ({p['steps']} Schritte)")
        return 0

    if not args.preset:
        print("FEHLER: Bitte --preset angeben (z.B. --preset multicam_cutter)")
        return 1

    # Quell-Modus bestimmen
    ingest_params = {}
    if args.bin:
        source_mode = "resolve_bin"
        ingest_params["bin_name"] = args.bin
    elif args.folder:
        source_mode = "folder"
        ingest_params["folder_path"] = args.folder
    elif args.file:
        source_mode = "file"
        ingest_params["file_path"] = args.file
    else:
        print("FEHLER: Bitte --bin, --folder oder --file angeben.")
        return 1

    if args.output:
        ingest_params["output_name"] = args.output

    # CLI-Overrides
    cli_overrides = {}
    if args.param:
        for p in args.param:
            if "=" not in p:
                print(f"FEHLER: Parameter '{p}' hat kein '=' (erwartet: module.key=value)")
                return 1
            key, val = p.split("=", 1)
            cli_overrides[key] = _auto_type(val)

    # Kamera-Optionen in Overrides
    if args.cam_mics:
        cli_overrides["ingest.cam_mics"] = args.cam_mics
    if args.cam_types:
        cli_overrides["ingest.cam_types"] = args.cam_types
    if args.cam_nodding:
        cli_overrides["ingest.cam_nodding"] = args.cam_nodding
    if args.auto_accuracy:
        cli_overrides["nodding_analysis.auto_accuracy"] = True
    if args.lut:
        cli_overrides["nodding_analysis.lut_path"] = args.lut
    if args.mic_cam1 is not None:
        cli_overrides["audio_load.mic_cam1"] = args.mic_cam1
    if args.mic_cam2 is not None:
        cli_overrides["audio_load.mic_cam2"] = args.mic_cam2

    # Work-Dir
    work_dir = Path(args.work_dir) if args.work_dir else None

    config_path = Path(args.config) if args.config else None

    return run_sequencer(
        preset_name=args.preset,
        source_mode=source_mode,
        fps=args.fps,
        work_dir=work_dir,
        config_path=config_path,
        ingest_params=ingest_params,
        cli_overrides=cli_overrides,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
