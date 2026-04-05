#!/usr/bin/env python3
"""
Complete EDL Workflow Orchestrator
Führt alle Schritte nacheinander aus: Analyse → Base-EDL → Cutaways
"""

import subprocess
import argparse
import sys
from pathlib import Path

def run_command(cmd, description):
    """Führt Command aus und zeigt Fortschritt"""
    print(f"\n{'='*70}")
    print(f"🎬 {description}")
    print(f"{'='*70}")
    print(f"Command: {' '.join(cmd)}\n")
    
    result = subprocess.run(cmd, capture_output=False)
    
    if result.returncode != 0:
        print(f"\n✗ FEHLER in: {description}")
        print(f"Exit Code: {result.returncode}")
        return False
    
    print(f"\n✓ {description} - Erfolgreich!")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Complete EDL Workflow: Analyse → Base-EDL → Cutaways'
    )
    
    # Video Files
    parser.add_argument('--cam1-video', required=True,
                        help='Cam1 Video File (z.B. C7636.MP4)')
    parser.add_argument('--cam2-video', required=True,
                        help='Cam2 Video File (z.B. C4608.MP4)')
    
    # Embedded TCs (optional - wird mit ffprobe automatisch erkannt)
    parser.add_argument('--cam1-embedded-tc', required=False,
                        help='Cam1 Embedded TC (z.B. 00:32:36:11)')
    parser.add_argument('--cam2-embedded-tc', required=False,
                        help='Cam2 Embedded TC (z.B. 10:26:23:01)')
    
    # Clip Names
    parser.add_argument('--cam1-clip', default='C7636.MP4',
                        help='Cam1 Clip Name in EDL (default: C7636.MP4)')
    parser.add_argument('--cam2-clip', default='C4608.MP4',
                        help='Cam2 Clip Name in EDL (default: C4608.MP4)')
    
    # Output
    parser.add_argument('--output', '-o', required=True,
                        help='Finale EDL Output (z.B. final.edl)')
    
    # Config
    parser.add_argument('--config', default='config.ini',
                        help='Config file (default: config.ini)')
    
    # Optional: Zwischenschritte überspringen
    parser.add_argument('--skip-analysis', action='store_true',
                        help='Überspringe Analyse (wenn JSONs schon existieren)')
    parser.add_argument('--skip-base-edl', action='store_true',
                        help='Überspringe Base-EDL (wenn base.edl schon existiert)')
    
    args = parser.parse_args()
    
    print("="*70)
    print("🎬 COMPLETE EDL WORKFLOW")
    print("="*70)
    print(f"Cam1 Video: {args.cam1_video}")
    print(f"Cam2 Video: {args.cam2_video}")
    print(f"Output: {args.output}")
    print("="*70)
    
    # Pfade
    cam1_video = Path(args.cam1_video)
    cam2_video = Path(args.cam2_video)
    
    if not cam1_video.exists():
        print(f"✗ FEHLER: Cam1 Video nicht gefunden: {cam1_video}")
        return 1
    if not cam2_video.exists():
        print(f"✗ FEHLER: Cam2 Video nicht gefunden: {cam2_video}")
        return 1
    
    # JSON Pfade (automatisch generiert)
    cam1_json = cam1_video.stem + '_reactions.json'
    cam2_json = cam2_video.stem + '_reactions.json'
    
    base_edl = 'base.edl'
    
    # =================================================================
    # SCHRITT 1: Analyse mit Speaking
    # =================================================================
    
    if not args.skip_analysis:
        # Cam1 analysieren
        cmd1 = [
            'python', 'video_reaction_analyzer_v2.3_speaking.py',
            str(cam1_video)
        ]
        if not run_command(cmd1, f"Analysiere {cam1_video.name}"):
            return 1
        
        # Cam2 analysieren
        cmd2 = [
            'python', 'video_reaction_analyzer_v2.3_speaking.py',
            str(cam2_video)
        ]
        if not run_command(cmd2, f"Analysiere {cam2_video.name}"):
            return 1
    else:
        print(f"\n⏭️  Überspringe Analyse (--skip-analysis)")
        print(f"  Verwende: {cam1_json}, {cam2_json}")
    
    # =================================================================
    # SCHRITT 2: Base-EDL aus Speaking bauen
    # =================================================================
    
    if not args.skip_base_edl:
        cmd3 = [
            'python', 'build_base_edl_from_speaking.py',
            '--cam1-reactions', cam1_json,
            '--cam2-reactions', cam2_json,
            '--cam1-clip', args.cam1_clip,
            '--cam2-clip', args.cam2_clip,
            '--output', base_edl
        ]
        
        # Embedded TCs hinzufügen wenn gegeben
        if args.cam1_embedded_tc:
            cmd3.extend(['--cam1-embedded-tc', args.cam1_embedded_tc])
        else:
            cmd3.extend(['--cam1-video', str(cam1_video)])
        
        if args.cam2_embedded_tc:
            cmd3.extend(['--cam2-embedded-tc', args.cam2_embedded_tc])
        else:
            cmd3.extend(['--cam2-video', str(cam2_video)])
        
        if not run_command(cmd3, "Baue Base-EDL aus Speaking"):
            return 1
    else:
        print(f"\n⏭️  Überspringe Base-EDL (--skip-base-edl)")
        print(f"  Verwende: {base_edl}")
    
    # =================================================================
    # SCHRITT 3: Nodding-Cutaways hinzufügen
    # =================================================================
    
    cmd4 = [
        'python', 'add_reactions_to_edl_v3.6.py',
        '--resolve-edl', base_edl,
        '--cam1-clip', args.cam1_clip,
        '--cam1-reactions', cam1_json,
        '--cam2-clip', args.cam2_clip,
        '--cam2-reactions', cam2_json,
        '--output', args.output,
        '--config', args.config
    ]
    
    # Embedded TCs oder Video-Pfade
    if args.cam1_embedded_tc:
        cmd4.extend(['--cam1-embedded-tc', args.cam1_embedded_tc])
    else:
        cmd4.extend(['--cam1-video', str(cam1_video)])
    
    if args.cam2_embedded_tc:
        cmd4.extend(['--cam2-embedded-tc', args.cam2_embedded_tc])
    else:
        cmd4.extend(['--cam2-video', str(cam2_video)])
    
    if not run_command(cmd4, "Füge Nodding-Cutaways hinzu"):
        return 1
    
    # =================================================================
    # FERTIG!
    # =================================================================
    
    print("\n" + "="*70)
    print("✅ WORKFLOW ERFOLGREICH ABGESCHLOSSEN!")
    print("="*70)
    print(f"📁 Generierte Files:")
    print(f"  • {cam1_json}")
    print(f"  • {cam2_json}")
    print(f"  • {base_edl}")
    print(f"  • {args.output} ← FINALE EDL")
    print()
    print(f"Importiere in Resolve:")
    print(f"  File → Import → Timeline → EDL")
    print(f"  → {args.output}")
    print("="*70)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
