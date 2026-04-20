#!/usr/bin/env python3
"""
Visualisiert die Rolling-Baseline der Speaking-Detection auf einer WAV-Datei.

Nutzt direkt den Produktions-Code (_bursts_rolling) aus build_base_edl_from_audio.py,
damit der Plot exakt das zeigt, was die Analyse tatsächlich sieht.

Zeigt:
  - Pegel (dBFS) pro Fenster
  - Rolling-Baseline (mit no_burst_decay_factor)
  - Rise-Werte (Baseline-Anstieg über Lookback)
  - Erkannte Bursts (grüne Bereiche)
  - Optional: Diarization-Sections (wer spricht wann)

Verwendung:
    python tools/visualize_baseline.py MIC1.WAV --start 60 --end 180
    python tools/visualize_baseline.py MIC1.WAV --mic2 MIC2.WAV --start 60 --end 180
    python tools/visualize_baseline.py MIC1.WAV --rise-db 8 --release 30
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.multicam_cutter.build_base_edl_from_audio import (
    load_audio, rms_diarize, _bursts_rolling,
)


def main():
    parser = argparse.ArgumentParser(
        description='Rolling-Baseline Visualisierung (Produktions-Code)'
    )
    parser.add_argument('wav', help='WAV-Datei (MIC1 / Off-Mic)')
    parser.add_argument('--mic2', default=None,
                        help='Zweite WAV-Datei (MIC2). Wenn angegeben, wird die '
                             'Diarization berechnet und als Sections angezeigt.')
    parser.add_argument('--start', type=float, default=0, help='Startzeit in Sekunden')
    parser.add_argument('--end', type=float, default=None, help='Endzeit in Sekunden')
    parser.add_argument('--window', type=float, default=0.05, help='Analyse-Fenster (s)')
    parser.add_argument('--rise-db', type=float, default=6.0, help='Rise-Schwelle (dB)')
    parser.add_argument('--attack', type=float, default=1.0, help='Attack-Fenster (s)')
    parser.add_argument('--release', type=float, default=20.0, help='Release-Fenster (s)')
    parser.add_argument('--warmup', type=float, default=3.0, help='Warmup-Phase (s)')
    parser.add_argument('--decay-hold', type=float, default=3.0,
                        help='S-Kurve Decay-Hold in Sekunden (default: 3.0)')
    parser.add_argument('--no-burst-decay', type=float, default=3.0,
                        help='Decay-Faktor wenn kein Burst aktiv (default: 3.0)')
    parser.add_argument('--min-dur', type=float, default=0.20, help='Min Burst-Dauer (s)')
    parser.add_argument('--max-dur', type=float, default=2.5, help='Max Burst-Dauer (s)')
    parser.add_argument('--hold', type=float, default=0.0, help='Hold-Zeit (s)')
    parser.add_argument('--mode', choices=['rms', 'peak'], default='peak')
    parser.add_argument('--lookback', type=float, default=1.0,
                        help='Lookback fuer Rise-Erkennung (s)')
    parser.add_argument('--sustain-margin', type=float, default=1.5,
                        help='Sustain-Margin unter Peak (dB)')
    parser.add_argument('--threshold-db', type=float, default=3.0,
                        help='Diarization-Schwelle in dB (nur mit --mic2)')
    parser.add_argument('--change-delay', type=float, default=1.0,
                        help='Diarization Change-Delay in s (nur mit --mic2)')
    parser.add_argument('--min-edit', type=float, default=2.0,
                        help='Diarization Min-Edit-Duration in s (nur mit --mic2)')
    parser.add_argument('--linear', action='store_true',
                        help='Waveform linear statt logarithmisch (dB) anzeigen')
    parser.add_argument('--compare-attack', type=float, nargs='+', default=None,
                        help='Mehrere Attack-Werte vergleichen (z.B. --compare-attack 0.2 0.25 0.3)')
    parser.add_argument('--save', default=None, help='Plot als PNG speichern statt anzeigen')
    args = parser.parse_args()

    # ── Audio laden ─────────────────────────────────────────────────────────
    print(f"Lade {args.wav} ...")
    audio1_full, sr = load_audio(args.wav)

    audio2_full = None
    segments = None
    if args.mic2:
        print(f"Lade {args.mic2} ...")
        audio2_full, sr2 = load_audio(args.mic2)
        assert sr == sr2, f"Sample-Rates unterschiedlich: {sr} vs {sr2}"
        n = min(len(audio1_full), len(audio2_full))
        audio1_full, audio2_full = audio1_full[:n], audio2_full[:n]

        print("Diarization ...")
        segments = rms_diarize(
            audio1_full, audio2_full, sr,
            window_s=args.window,
            threshold_db=args.threshold_db,
            change_delay_s=args.change_delay,
            min_edit_s=args.min_edit,
        )
        print(f"  {len(segments)} Segmente")

    # Zeitbereich einschränken
    start_sa = int(args.start * sr)
    end_sa = int(args.end * sr) if args.end else len(audio1_full)
    audio1 = audio1_full[start_sa:end_sa]
    duration_s = len(audio1) / sr
    print(f"  Bereich: {args.start:.0f}s - {args.start + duration_s:.0f}s ({duration_s:.1f}s)")

    # ── Produktions-Code: _bursts_rolling mit return_debug ──────────────────
    fps = 25.0  # nur für tl_frame-Berechnung, irrelevant für Plot

    def run_detection(audio_seg, attack_override=None):
        attack = attack_override if attack_override is not None else args.attack
        bursts, db, baseline, rise = _bursts_rolling(
            audio_seg, sr, fps, args.window,
            attack, args.release, args.warmup,
            args.rise_db, args.min_dur, args.max_dur, args.hold,
            timeline_start_frame=0,
            mode=args.mode,
            decay_hold_s=args.decay_hold,
            lookback_s=args.lookback,
            sustain_margin_db=args.sustain_margin,
            no_burst_decay_factor=args.no_burst_decay,
            return_debug=True,
        )
        return bursts, db, baseline, rise

    # ── Compare-Attack Modus ────────────────────────────────────────────────
    if args.compare_attack:
        _, db_ref, _, _ = run_detection(audio1)
        time_axis = np.arange(len(db_ref)) * args.window + args.start

        def to_display(db_vals):
            if args.linear:
                return 10 ** (db_vals / 20.0)
            return db_vals

        colors = ['#22cc22', '#ccaa00', '#8833cc', '#cc3333', '#3388cc', '#cc6600']
        fig, ax = plt.subplots(1, 1, figsize=(18, 5))

        # Waveform
        ax.plot(time_axis[:len(db_ref)], to_display(db_ref), color='#5588cc',
                linewidth=0.5, alpha=0.5)

        handles = [plt.Line2D([0], [0], color='#5588cc', lw=1, alpha=0.5,
                              label=f'{args.mode.upper()}-Pegel')]

        # Bursts je Attack-Wert als farbige Regionen (versetzt in der Höhe)
        for i, atk in enumerate(args.compare_attack):
            c = colors[i % len(colors)]
            bursts_atk, _, _, _ = run_detection(audio1, attack_override=atk)
            for burst in bursts_atk:
                t0 = burst['start_s'] + args.start
                t1 = burst['end_s'] + args.start
                ax.axvspan(t0, t1, color=c, alpha=0.25, zorder=2 + i)
            handles.append(mpatches.Patch(color=c, alpha=0.35,
                                          label=f'attack={atk}s ({len(bursts_atk)} Bursts)'))
            print(f"  attack={atk}s: {len(bursts_atk)} Bursts")

        ax.set_ylabel('Amplitude' if args.linear else 'dBFS')
        ax.set_xlabel('Zeit (s)')
        ax.set_title(f'Burst-Vergleich nach Attack-Wert — {Path(args.wav).name}')
        ax.grid(True, alpha=0.2)
        ax.legend(handles=handles, loc='lower right', fontsize=9)
        plt.tight_layout()

        if args.save:
            fig.savefig(args.save, dpi=150, bbox_inches='tight')
            print(f"\n  Gespeichert: {args.save}")
        else:
            plt.show()
        return

    bursts1, db1, baseline1, rise1 = run_detection(audio1)
    time_axis = np.arange(len(db1)) * args.window + args.start

    bursts2, db2, baseline2, rise2 = None, None, None, None
    if audio2_full is not None:
        audio2 = audio2_full[start_sa:end_sa]
        bursts2, db2, baseline2, rise2 = run_detection(audio2)

    # ── Burst-Klassifikation (wenn Diarization vorhanden) ───────────────────
    def classify_burst(burst_start_s, mic_label):
        if not segments:
            return 'unknown'
        for seg in segments:
            if seg['start_s'] <= burst_start_s < seg['end_s']:
                if seg['speaker'] == 'CAM1' and mic_label == 'MIC2':
                    return 'speaking_reaction'
                elif seg['speaker'] == 'CAM2' and mic_label == 'MIC1':
                    return 'speaking_reaction'
                else:
                    return 'on_mic'
        return 'outside'

    # ── Plot ────────────────────────────────────────────────────────────────
    n_panels = 2 if db2 is not None else 1
    fig, axes = plt.subplots(n_panels, 1, figsize=(18, 4.5 * n_panels), sharex=True)
    if n_panels == 1:
        axes = [axes]

    mic_data = [('MIC1', db1, baseline1, rise1, bursts1)]
    if db2 is not None:
        mic_data.append(('MIC2', db2, baseline2, rise2, bursts2))

    for ax, (mic_label, db, baseline, rise, bursts) in zip(axes, mic_data):
        # Diarization-Sections als Hintergrund
        if segments:
            for seg in segments:
                s0 = max(seg['start_s'], args.start)
                s1 = min(seg['end_s'], args.start + duration_s)
                if s1 <= s0:
                    continue
                is_on_mic = (
                    (seg['speaker'] == 'CAM1' and mic_label == 'MIC1') or
                    (seg['speaker'] == 'CAM2' and mic_label == 'MIC2')
                )
                color = '#ffcccc' if is_on_mic else '#ccddff'
                ax.axvspan(s0, s1, color=color, alpha=0.3, zorder=0)

        # Pegel + Baseline (optional linear)
        def to_display(db_vals):
            if args.linear:
                return 10 ** (db_vals / 20.0)  # dB → lineare Amplitude
            return db_vals

        ax.plot(time_axis[:len(db)], to_display(db), color='#5588cc', linewidth=0.5,
                alpha=0.8, label=f'{args.mode.upper()}-Pegel')
        ax.plot(time_axis[:len(baseline)], to_display(baseline), color='#cc4444',
                linewidth=1.5, label='Baseline')

        # Rise-Trigger-Linie: baseline[k-lookback] + rise_db
        lookback_n = max(1, int(args.lookback / args.window))
        trigger_line = np.copy(baseline)
        for k in range(len(baseline)):
            lo = max(0, k - lookback_n)
            trigger_line[k] = baseline[lo] + args.rise_db
        ax.plot(time_axis[:len(trigger_line)], to_display(trigger_line), color='#cc4444',
                linewidth=1.0, linestyle='--', alpha=0.5,
                label=f'Trigger (lookback + {args.rise_db} dB)')

        # Bursts
        n_reaction, n_onmic, n_other = 0, 0, 0
        for burst in bursts:
            t0 = burst['start_s'] + args.start
            t1 = burst['end_s'] + args.start
            cls = classify_burst(t0, mic_label)
            if cls == 'speaking_reaction':
                ax.axvspan(t0, t1, color='#22cc22', alpha=0.35, zorder=2)
                n_reaction += 1
            elif cls == 'on_mic':
                ax.axvspan(t0, t1, color='#cccc22', alpha=0.25, zorder=2)
                n_onmic += 1
            else:
                ax.axvspan(t0, t1, color='#22cc22', alpha=0.25, zorder=2)
                n_other += 1

        ax.set_ylabel('Amplitude' if args.linear else 'dBFS')
        ax.set_title(f'{mic_label} — {Path(args.wav if mic_label == "MIC1" else args.mic2).name}')
        ax.grid(True, alpha=0.2)
        ax.set_xlim(time_axis[0], time_axis[-1])

        # Legende
        handles = [
            plt.Line2D([0], [0], color='#5588cc', lw=1,
                       label=f'{args.mode.upper()}-Pegel'),
            plt.Line2D([0], [0], color='#cc4444', lw=1.5, label='Baseline'),
            plt.Line2D([0], [0], color='#cc4444', lw=1, ls='--', alpha=0.5,
                       label=f'Trigger (+{args.rise_db} dB)'),
        ]
        if segments:
            handles.extend([
                mpatches.Patch(color='#ccddff', alpha=0.3,
                               label='Off-Mic (Reactions zaehlen)'),
                mpatches.Patch(color='#ffcccc', alpha=0.3,
                               label='On-Mic (eigener Sprecher)'),
                mpatches.Patch(color='#22cc22', alpha=0.35,
                               label=f'Speaking-Reaction ({n_reaction})'),
                mpatches.Patch(color='#cccc22', alpha=0.25,
                               label=f'On-Mic Burst ({n_onmic})'),
            ])
        else:
            handles.append(
                mpatches.Patch(color='#22cc22', alpha=0.25,
                               label=f'Burst ({len(bursts)})'),
            )
        ax.legend(handles=handles, loc='lower right', fontsize=8)

    axes[-1].set_xlabel('Zeit (s)')

    fig.suptitle(
        f'Speaking-Detection (Produktion)  '
        f'attack={args.attack}s, release={args.release}s, rise={args.rise_db}dB, '
        f'mode={args.mode}, decay_factor={args.no_burst_decay}x',
        fontsize=11, y=1.01,
    )
    plt.tight_layout()

    # Statistik
    total_bursts = len(bursts1) + (len(bursts2) if bursts2 else 0)
    print(f"\n  MIC1: {len(bursts1)} Bursts")
    if bursts2 is not None:
        print(f"  MIC2: {len(bursts2)} Bursts")
    if segments and db2 is not None:
        total_reactions = sum(
            1 for b in bursts1
            if classify_burst(b['start_s'] + args.start, 'MIC1') == 'speaking_reaction'
        ) + sum(
            1 for b in bursts2
            if classify_burst(b['start_s'] + args.start, 'MIC2') == 'speaking_reaction'
        )
        print(f"  Speaking-Reactions: {total_reactions}")
        print(f"  Gesamt Bursts: {total_bursts}")

    if args.save:
        fig.savefig(args.save, dpi=150, bbox_inches='tight')
        print(f"\n  Gespeichert: {args.save}")
    else:
        plt.show()


if __name__ == '__main__':
    main()
