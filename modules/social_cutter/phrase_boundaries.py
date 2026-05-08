"""
Social Cutter — Phrasengrenzen-Erkennung.

Kombiniert Whisper-Interpunktion mit Praat-Pitch-Analyse
um natürliche Schnittmarken zu finden.

Portiert aus sandbox/pitch_vs_whisper.py (validierte Logik).
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import numpy as np

from .types import (
    BoundaryType,
    PhraseBoundary,
    Sentence,
    SilenceSegment,
    TranscriptResult,
    Word,
)

_log = logging.getLogger("rtk.social_cutter")


# ── Pitch-Analyse (Praat) ───────────────────────────────────────────────────
# 1:1 aus sandbox/pitch_vs_whisper.py

def _run_pitch(audio_path: str) -> tuple[np.ndarray, np.ndarray]:
    """Praat Pitch-Tracking bei 5ms Auflösung.

    Returns:
        (times, f0) — Arrays mit Zeitpunkten und F0-Werten (NaN = unvoiced).
    """
    import parselmouth

    snd = parselmouth.Sound(str(audio_path))
    pitch = snd.to_pitch(time_step=0.005)
    times = pitch.xs()
    f0 = np.array([pitch.get_value_at_time(t) for t in times])
    return times, f0


def _analyze_pitch_window(
    times: np.ndarray,
    f0: np.ndarray,
    center_s: float,
    window_before: float = 0.6,
    window_after: float = 0.2,
) -> dict:
    """Misst die F0-Kontur in einem Fenster um einen Zeitpunkt.

    1:1 aus sandbox/pitch_vs_whisper.py:analyze_pitch_window().
    """
    mask_before = (times >= center_s - window_before) & (times <= center_s)

    f0_before = f0[mask_before]
    voiced_before = f0_before[~np.isnan(f0_before)]

    result = {"voiced_count": len(voiced_before)}

    if len(voiced_before) >= 5:
        x = np.arange(len(voiced_before))
        slope = np.polyfit(x, voiced_before, 1)[0]
        time_span = window_before
        slope_per_sec = slope * (len(voiced_before) / time_span) if time_span > 0 else 0

        result["slope_hz_per_sec"] = round(float(slope_per_sec), 1)
        result["f0_drop_hz"] = round(float(voiced_before[0] - voiced_before[-1]), 1)

        # Letzte 200ms speziell
        mask_last200 = (times >= center_s - 0.2) & (times <= center_s)
        f0_last200 = f0[mask_last200]
        voiced_last200 = f0_last200[~np.isnan(f0_last200)]
        if len(voiced_last200) >= 3:
            result["f0_last200ms_drop"] = round(
                float(voiced_last200[0] - voiced_last200[-1]), 1
            )

    return result


def _classify_pitch_trend(pitch_info: dict) -> str:
    """Klassifiziert den Pitch-Trend.

    1:1 aus sandbox/pitch_vs_whisper.py:classify_pitch_trend().
    """
    drop_last200 = pitch_info.get("f0_last200ms_drop", 0)
    slope = pitch_info.get("slope_hz_per_sec", 0)

    if drop_last200 > 15:
        return "falling"
    elif drop_last200 > 5:
        return "falling"
    elif drop_last200 < -15:
        return "rising"
    elif drop_last200 < -5:
        return "rising"
    else:
        if slope < -30:
            return "falling"
        elif slope < -10:
            return "falling"
        elif slope > 30:
            return "rising"
        elif slope > 10:
            return "rising"
        else:
            return "flat"


# ── Konfidenz-Berechnung ────────────────────────────────────────────────────

def _compute_confidence(
    punct: str,
    pitch_trend: str,
    gap_s: float,
    prefer_falls: bool,
) -> float:
    """Berechnet einen Konfidenz-Score (0–1) für eine Phrasengrenze.

    Kombiniert:
    - Interpunktions-Typ (Punkt > Komma > nichts)
    - Pitch-Trend (fallend = Satzende, steigend = Halbsatz)
    - Wortlücke (länger = stärker)
    """
    score = 0.0

    # Interpunktion
    if punct in (".", "!", "?"):
        score += 0.5
    elif punct == ",":
        score += 0.3

    # Pitch
    if pitch_trend == "falling":
        score += 0.3 if prefer_falls else 0.15
    elif pitch_trend == "rising":
        score += 0.15 if prefer_falls else 0.3
    elif pitch_trend == "flat":
        score += 0.1

    # Wortlücke
    if gap_s > 0.5:
        score += 0.2
    elif gap_s > 0.3:
        score += 0.1

    return min(score, 1.0)


# ── Hauptfunktion ────────────────────────────────────────────────────────────

def detect_phrase_boundaries(
    transcript: TranscriptResult,
    audio_path: str,
    silence_segments: list[SilenceSegment],
    prefer_falls: bool = True,
    min_gap_ms: float = 300.0,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> list[PhraseBoundary]:
    """Erkennt Phrasengrenzen aus Whisper-Interpunktion + Praat-Pitch.

    Args:
        transcript: Whisper-Transkription mit Word-Timestamps.
        audio_path: Pfad zur Audio-Datei für Pitch-Analyse.
        silence_segments: Behaltene Segmente (für Filterung).
        prefer_falls: Fallende Pitch an Grenzen höher gewichten.
        min_gap_ms: Wortlücken ab dieser Dauer als Grenze werten.
        progress_cb: Callback(progress_0_1, status_text).

    Returns:
        Liste von PhraseBoundary, sortiert nach Zeit.
    """
    words = transcript.words
    if len(words) < 2:
        return []

    if progress_cb:
        progress_cb(0.1, "Pitch-Analyse (Praat) …")

    pitch_times, pitch_f0 = _run_pitch(audio_path)

    if progress_cb:
        progress_cb(0.5, "Phrasengrenzen berechnen …")

    min_gap_s = min_gap_ms / 1000.0
    boundaries: list[PhraseBoundary] = []

    for i, word in enumerate(words):
        if i >= len(words) - 1:
            continue

        next_word = words[i + 1]
        text = word.text
        gap_s = next_word.start_s - word.end_s

        # Interpunktion am Wortende erkennen
        punct = ""
        if text.endswith("."):
            punct = "."
        elif text.endswith(","):
            punct = ","
        elif text.endswith("?"):
            punct = "?"
        elif text.endswith("!"):
            punct = "!"

        # Wortlücke als Grenze?
        is_gap_boundary = gap_s >= min_gap_s

        # Nur Grenzen an Interpunktion oder Wortlücken
        if not punct and not is_gap_boundary:
            continue

        # Boundary-Typ bestimmen
        if punct in (".", "?", "!"):
            btype = BoundaryType.SENTENCE_END
        elif punct == ",":
            btype = BoundaryType.CLAUSE_END
        elif is_gap_boundary:
            btype = BoundaryType.PAUSE
        else:
            continue

        # Pitch analysieren
        pitch_info = _analyze_pitch_window(pitch_times, pitch_f0, word.end_s)
        pitch_trend = _classify_pitch_trend(pitch_info)

        # Konfidenz
        confidence = _compute_confidence(punct, pitch_trend, gap_s, prefer_falls)

        boundaries.append(PhraseBoundary(
            time_s=round(word.end_s, 3),
            boundary_type=btype,
            confidence=round(confidence, 2),
            pitch_trend=pitch_trend,
            word_before=text,
            word_after=next_word.text,
        ))

    # Nur Grenzen innerhalb von Silence-Segmenten behalten
    if silence_segments:
        filtered = []
        for b in boundaries:
            for seg in silence_segments:
                if seg.start_s <= b.time_s <= seg.end_s:
                    filtered.append(b)
                    break
        boundaries = filtered

    boundaries.sort(key=lambda b: b.time_s)

    if progress_cb:
        progress_cb(1.0, f"{len(boundaries)} Phrasengrenzen erkannt.")

    _log.info("Phrase boundaries: %d (prefer_falls=%s)", len(boundaries), prefer_falls)
    return boundaries


def split_into_sentences(
    transcript: TranscriptResult,
    boundaries: list[PhraseBoundary],
    min_confidence: float = 0.5,
) -> list[Sentence]:
    """Teilt das Transkript an Phrasengrenzen in Sätze auf.

    Args:
        transcript: Whisper-Transkription.
        boundaries: Erkannte Phrasengrenzen.
        min_confidence: Grenzen unter diesem Wert ignorieren.

    Returns:
        Liste von Sentence-Objekten.
    """
    if not transcript.words:
        return []

    # Nur Grenzen über Konfidenz-Schwelle
    cuts = sorted(
        [b.time_s for b in boundaries if b.confidence >= min_confidence]
    )

    # Satzgrenzen: Anfang → erster Cut → ... → letzter Cut → Ende
    start_times = [transcript.words[0].start_s] + [t for t in cuts]
    end_times = [t for t in cuts] + [transcript.words[-1].end_s]

    sentences: list[Sentence] = []
    for i, (s, e) in enumerate(zip(start_times, end_times)):
        # Wörter in diesem Bereich sammeln
        sent_words = [
            w for w in transcript.words
            if s <= (w.start_s + w.end_s) / 2 < e
        ]
        if not sent_words:
            continue

        text = " ".join(w.text for w in sent_words)
        sentences.append(Sentence(
            index=i,
            text=text,
            start_s=round(sent_words[0].start_s, 3),
            end_s=round(sent_words[-1].end_s, 3),
            word_count=len(sent_words),
        ))

    return sentences
