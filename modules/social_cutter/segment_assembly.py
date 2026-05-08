"""
Social Cutter — Segment-Montage.

Kombiniert Silence-Segmente, Phrasengrenzen und User-Auswahl
zu einer finalen Segment-Liste.
"""

from __future__ import annotations

from .types import FinalSegment, Sentence, SilenceSegment


def assemble_segments(
    kept_sentences: list[Sentence],
    silence_segments: list[SilenceSegment],
    target_duration_s: float = 30.0,
    tail_ms: float = 100.0,
) -> list[FinalSegment]:
    """Baut die finale Segment-Liste aus behaltenen Sätzen + Silence-Segmenten.

    1. Schneidet jeden Satz auf den Bereich zu, der innerhalb eines
       Silence-Segments (= behaltenes Audio) liegt.
    2. Fügt tail_ms nach dem letzten Wort als natürlichen Auslauf an.
    3. Merged angrenzende Segmente mit winzigen Lücken (<50ms).

    Returns:
        Liste von FinalSegment mit transcript_text, zoom/broll noch None.
    """
    tail_s = tail_ms / 1000.0

    # Pro Satz: Gesamtdauer aus allen überlappenden Keep-Segmenten berechnen.
    # Ein Satz kann über mehrere Keep-Segmente reichen (Stille mitten im Satz).
    # Die Fragmente werden zu EINEM Segment zusammengefasst, da die Stille
    # im Ergebnis-Timeline bereits entfernt ist.
    merged: list[tuple[float, float, float, str]] = []  # (start, end, duration, text)
    for sent in kept_sentences:
        total_dur = 0.0
        first_start = None
        last_end = None
        for seg in silence_segments:
            s = max(sent.start_s, seg.start_s)
            e = min(sent.end_s + tail_s, seg.end_s)
            if e - s > 0.05:
                if first_start is None:
                    first_start = s
                last_end = e
                total_dur += e - s
        if first_start is not None and total_dur > 0.05:
            merged.append((first_start, last_end, total_dur, sent.text))

    if not merged:
        return []

    # Nach Startzeit sortieren
    merged.sort(key=lambda x: x[0])

    return [
        FinalSegment(
            index=i,
            source_start_s=round(s, 3),
            source_end_s=round(e, 3),
            duration_s=round(dur, 3),
            transcript_text=text.strip(),
        )
        for i, (s, e, dur, text) in enumerate(merged)
    ]


def estimate_duration(segments: list[FinalSegment]) -> float:
    """Gesamtdauer aller Segmente in Sekunden."""
    return sum(seg.duration_s for seg in segments)
