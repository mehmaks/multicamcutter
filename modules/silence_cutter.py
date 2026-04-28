"""
Silence Cutter Backend — Schwellwert-Analyse, Waveform-Rendering, AAF-Builder.

Extrahiert aus ui/pages/silence.py.
"""

from __future__ import annotations

import io
from pathlib import Path

import aaf2

from shared.ffmpeg_utils import load_audio_numpy, probe_fps, probe_duration
from shared.aaf_builder import (
    probe_media,
    create_single_source_mobs,
    make_composition,
)


# ── RMS-Analyse ──────────────────────────────────────────────────────────────

# ── Schwellwert-Vorschlag: Fast (K-Means) ───────────────────────────────────

def suggest_threshold_fast(src_path: str, progress_cb=None) -> dict:
    """Schwellwert-Vorschlag via k-means 2-Cluster auf RMS-Werten."""
    from shared.audio_analysis import suggest_threshold_kmeans

    if progress_cb:
        progress_cb(0.1, "Audio laden …")
    data, sr = load_audio_numpy(src_path, max_sec=300)

    if progress_cb:
        progress_cb(0.5, "RMS-Analyse / Cluster …")
    result = suggest_threshold_kmeans(data, sr)

    if progress_cb:
        progress_cb(1.0, "Fertig")
    return result


# ── Schwellwert-Vorschlag: Whisper ──────────────────────────────────────────

def suggest_threshold_whisper(src_path: str, progress_cb=None) -> dict:
    """Schwellwert-Vorschlag via Whisper-Segmentgrenzen + RMS-Messung."""
    import numpy as np

    if progress_cb:
        progress_cb(0.05, "Audio laden …")
    data, sr = load_audio_numpy(src_path)

    if progress_cb:
        progress_cb(0.15, "Whisper-Modell laden …")
    import whisper as _whisper
    model = _whisper.load_model("tiny")

    if progress_cb:
        progress_cb(0.3, "Transkription läuft …")
    result = model.transcribe(src_path, task="transcribe",
                              word_timestamps=False, verbose=False)
    segments = result.get("segments", [])

    if progress_cb:
        progress_cb(0.85, "Pegel messen …")

    def _seg_db(t0, t1):
        chunk = data[int(t0 * sr): int(t1 * sr)]
        if len(chunk) < sr * 0.05:
            return None
        rms_val = float(np.sqrt(np.mean(chunk ** 2)))
        return 20 * np.log10(rms_val) if rms_val > 1e-7 else None

    duration = len(data) / sr
    speech_rms, gap_rms = [], []
    prev = 0.0
    for i, seg in enumerate(segments):
        if seg["start"] - prev > 0.25 and i > 0:
            v = _seg_db(prev + 0.05, seg["start"] - 0.05)
            if v is not None:
                gap_rms.append(v)
        v = _seg_db(seg["start"], seg["end"])
        if v is not None:
            speech_rms.append(v)
        prev = seg["end"]

    if not speech_rms:
        raise RuntimeError("Whisper erkannte keine Sprache")

    covered_s = sum(seg["end"] - seg["start"] for seg in segments)
    coverage = covered_s / duration if duration > 0 else 0.0
    low_coverage = coverage < 0.30

    noise_floor = float(np.median(gap_rms)) if gap_rms else float(np.percentile(speech_rms, 5))
    quiet_speech = float(np.percentile(speech_rms, 10))
    threshold = int(round((noise_floor + quiet_speech) / 2))
    threshold = max(-60, min(-10, threshold))

    out = {
        "threshold": threshold,
        "noise_floor": round(noise_floor, 1),
        "quiet_speech": round(quiet_speech, 1),
        "coverage": round(coverage * 100, 0),
    }
    if low_coverage:
        out["coverage_warning"] = (
            f"Whisper hat nur {coverage*100:.0f} % der Datei als Sprache erkannt — "
            "möglicherweise unvollständige Transkription (lange Pausen, Fremdsprache). "
            "Schwellwert manuell prüfen."
        )
    return out


# ── Waveform-Rendering ──────────────────────────────────────────────────────

def render_waveform_png(src_path: str, dur_s: float,
                        silence_segs: list, fps: float) -> bytes | None:
    """Rendert Waveform + rote Stille-Bereiche als PNG-Bytes."""
    import subprocess
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    r = subprocess.run(
        ['ffmpeg', '-y', '-i', src_path, '-ac', '1', '-ar', '200',
         '-f', 'f32le', '-'],
        capture_output=True,
    )
    data = np.frombuffer(r.stdout, dtype=np.float32).copy()
    if len(data) < 10:
        return None

    DISPLAY_W = 1200
    n = len(data)
    step = max(1, n // DISPLAY_W)
    clipped = data[: (n // step) * step].reshape(-1, step)
    lo = clipped.min(axis=1)
    hi = clipped.max(axis=1)
    t = np.linspace(0, dur_s, len(lo))

    peak = max(abs(lo.min()), abs(hi.max()))
    if peak > 0:
        lo /= peak
        hi /= peak

    fig, ax = plt.subplots(figsize=(12, 1.8), facecolor='#111111')
    ax.set_facecolor('#111111')
    ax.fill_between(t, lo, hi, color='#5b9bd5', alpha=0.9, linewidth=0)
    ax.axhline(0, color='#333333', linewidth=0.5)

    for s_start, s_dur in silence_segs:
        t0 = s_start / fps
        t1 = (s_start + s_dur) / fps
        ax.axvspan(t0, t1, color='#e03131', alpha=0.45, linewidth=0)

    ax.set_xlim(0, dur_s)
    ax.set_ylim(-1, 1)
    ax.tick_params(axis='x', colors='#888888', labelsize=7)
    ax.tick_params(axis='y', left=False, labelleft=False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xlabel('Zeit (s)', color='#888888', fontsize=7)
    plt.tight_layout(pad=0.3)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=130, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── AAF-Builder ──────────────────────────────────────────────────────────────

def build_silence_aaf(source_path: str, keep_segs: list,
                      output_path: str, fps: float, tl_name: str) -> None:
    """Erstellt eine AAF-Timeline mit den behaltenen (nicht-stillen) Segmenten.

    Args:
        source_path: Pfad zur Quelldatei
        keep_segs: Liste von {"start": float_s, "end": float_s}
        output_path: Pfad für die AAF-Ausgabe
        fps: Timeline-Framerate
        tl_name: Name der Timeline
    """
    fps_int = int(round(fps))
    info = probe_media(source_path, fps)

    total_fr = sum(
        max(1, int(round((s["end"] - s["start"]) * fps_int)))
        for s in keep_segs
    )

    with aaf2.open(output_path, 'w') as f:
        master, m_v_slot, m_a_slots = create_single_source_mobs(
            f, info, fps_int, n_audio_tracks=2)

        comp = make_composition(f, tl_name, fps_int, total_fr)

        def _seq(media_kind, master_slot):
            seq = f.create.Sequence(media_kind=media_kind, length=total_fr)
            for seg in keep_segs:
                sf = int(round(seg["start"] * fps_int))
                lf = max(1, int(round((seg["end"] - seg["start"]) * fps_int)))
                sc = f.create.SourceClip(media_kind=media_kind, length=lf)
                sc.mob = master
                sc.slot = master_slot
                sc.start = sf
                seq.components.append(sc)
            return seq

        comp_vid = comp.create_picture_slot(edit_rate=fps_int)
        comp_vid['PhysicalTrackNumber'].value = 1
        comp_vid.segment = _seq('picture', m_v_slot)

        for i, a_slot in enumerate(m_a_slots):
            comp_a = comp.create_sound_slot(edit_rate=fps_int)
            comp_a['PhysicalTrackNumber'].value = i + 1
            comp_a.segment = _seq('sound', a_slot)

        f.content.mobs.append(comp)
