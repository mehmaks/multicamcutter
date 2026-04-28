"""
Take Selector Backend — Text-Analyse, Diff-Rendering, AAF-Builder.

Extrahiert aus ui/pages/takes.py.
"""

from __future__ import annotations

import difflib
import html as html_mod
from pathlib import Path

import aaf2

from shared.aaf_builder import (
    probe_media,
    create_single_source_mobs,
    make_composition,
)
from shared.ffmpeg_utils import probe_fps  # noqa: F401 — re-export


# ── Text-Analyse ─────────────────────────────────────────────────────────────

def start_words(seg: list, n: int = 10) -> list[str]:
    """Extrahiert die ersten n clean-Wörter eines Segments."""
    return [w["clean"] for w in seg[:n]]


def text_similarity(a: list[str], b: list[str]) -> float:
    """Berechnet die Text-Ähnlichkeit zweier Wortlisten (0.0–1.0)."""
    return difflib.SequenceMatcher(None, a, b).ratio()


def build_diff_html(ref_words: list[str], take_words: list[str],
                    color: str, min_d: int) -> str:
    """Inline-Diff: Löschungen als grauer Strikethrough, Änderungen als farbige Markierung."""
    opcodes = difflib.SequenceMatcher(
        None, ref_words, take_words, autojunk=False).get_opcodes()
    parts = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            parts.append(html_mod.escape(" ".join(take_words[j1:j2])))
        else:
            block_len = max(i2 - i1, j2 - j1)
            if block_len < min_d:
                if j1 < j2:
                    parts.append(html_mod.escape(" ".join(take_words[j1:j2])))
            else:
                if tag in ("replace", "delete") and i1 < i2:
                    deleted = html_mod.escape(" ".join(ref_words[i1:i2]))
                    parts.append(
                        f"<del style='color:#9ca3af;text-decoration-color:#9ca3af'>"
                        f"{deleted}</del>"
                    )
                if tag in ("replace", "insert") and j1 < j2:
                    inserted = html_mod.escape(" ".join(take_words[j1:j2]))
                    parts.append(
                        f"<mark style='background:{color}28;border-bottom:2px solid {color};"
                        f"padding:0 2px;border-radius:2px;color:#3d3a2a'>{inserted}</mark>"
                    )
    return " ".join(parts)


# ── AAF-Builder ──────────────────────────────────────────────────────────────

def build_takes_aaf(source_path: str, takes: list, output_path: str,
                    fps: float, tl_name: str,
                    best_set: set | None = None) -> None:
    """Erstellt eine AAF-Timeline mit Takes als Segmenten.

    Args:
        source_path: Pfad zur Quelldatei
        takes: Liste von {"start": float_s, "end": float_s}
        output_path: Pfad für die AAF-Ausgabe
        fps: Timeline-Framerate
        tl_name: Name der Timeline
        best_set: Set von Indices (best takes) für V1/V2-Split.
                  None → Single V1 Track (Legacy).
    """
    fps_int = int(round(fps))
    info = probe_media(source_path, fps)

    total_fr = sum(
        max(1, int(round((t["end"] - t["start"]) * fps_int)))
        for t in takes
    )

    with aaf2.open(output_path, 'w') as f:
        master, m_v_slot, m_a_slots = create_single_source_mobs(
            f, info, fps_int, n_audio_tracks=2)

        comp = make_composition(f, tl_name, fps_int, total_fr)

        def _seq(media_kind, master_slot, skip_indices=None):
            """Sequence mit SourceClips; skip_indices werden als Filler eingefügt."""
            seq = f.create.Sequence(media_kind=media_kind, length=total_fr)
            for idx, take in enumerate(takes):
                sf = int(round(take["start"] * fps_int))
                lf = max(1, int(round((take["end"] - take["start"]) * fps_int)))
                if skip_indices is not None and idx in skip_indices:
                    fill = f.create.SourceClip(media_kind=media_kind, length=lf)
                    seq.components.append(fill)
                else:
                    sc = f.create.SourceClip(media_kind=media_kind, length=lf)
                    sc.mob = master
                    sc.slot = master_slot
                    sc.start = sf
                    seq.components.append(sc)
            return seq

        if best_set is None:
            comp_vid = comp.create_picture_slot(edit_rate=fps_int)
            comp_vid['PhysicalTrackNumber'].value = 1
            comp_vid.segment = _seq('picture', m_v_slot)
        else:
            non_best = set(range(len(takes))) - best_set
            comp_vid1 = comp.create_picture_slot(edit_rate=fps_int)
            comp_vid1['PhysicalTrackNumber'].value = 1
            comp_vid1.segment = _seq('picture', m_v_slot, skip_indices=best_set)

            comp_vid2 = comp.create_picture_slot(edit_rate=fps_int)
            comp_vid2['PhysicalTrackNumber'].value = 2
            comp_vid2.segment = _seq('picture', m_v_slot, skip_indices=non_best)

        for i, a_slot in enumerate(m_a_slots):
            comp_a = comp.create_sound_slot(edit_rate=fps_int)
            comp_a['PhysicalTrackNumber'].value = i + 1
            comp_a.segment = _seq('sound', a_slot)

        f.content.mobs.append(comp)
