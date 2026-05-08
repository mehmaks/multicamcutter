"""
Social Cutter — B-Roll Matching.

Hybrid-Workflow:
1. sentence-transformers: Segment-Text → Kategorie-Zuordnung
2. CLIP: Visuelles Ranking innerhalb der zugeordneten Kategorie
3. User bestätigt Vorschläge
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .types import BRollCategory, BRollPlacement, FinalSegment

_log = logging.getLogger("rtk.social_cutter")


# ── Kategorie-Embeddings ───────────────────────────────────────────────────

def embed_categories(
    categories: list[BRollCategory],
    model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
) -> dict[str, np.ndarray]:
    """Erstellt sentence-transformers Embeddings für Kategorie-Namen.

    Returns:
        Dict: {category_name: embedding_vector}
    """
    if not categories:
        return {}

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    names = [c.name for c in categories]
    embeddings = model.encode(names, show_progress_bar=False)

    return {name: emb for name, emb in zip(names, embeddings)}


# ── Segment → Kategorie Matching ──────────────────────────────────────────

def match_segments_to_categories(
    segments: list[FinalSegment],
    category_embeddings: dict[str, np.ndarray],
    model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
    top_k: int = 2,
) -> list[list[tuple[str, float]]]:
    """Ordnet jedem Segment die passendsten B-Roll-Kategorien zu.

    Args:
        segments: Finale Segmente mit transcript_text.
        category_embeddings: {name: embedding} aus embed_categories().
        top_k: Wie viele Kategorien pro Segment vorgeschlagen werden.

    Returns:
        Liste (eine pro Segment) von [(category_name, score), ...],
        sortiert nach Score absteigend.
    """
    if not segments or not category_embeddings:
        return [[] for _ in segments]

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)

    # Segment-Texte embedden
    texts = [seg.transcript_text for seg in segments]
    seg_embeddings = model.encode(texts, show_progress_bar=False)

    # Kategorie-Embeddings als Matrix
    cat_names = list(category_embeddings.keys())
    cat_matrix = np.array([category_embeddings[n] for n in cat_names])

    # Normalisieren
    seg_norms = np.linalg.norm(seg_embeddings, axis=1, keepdims=True)
    seg_norms = np.where(seg_norms == 0, 1e-10, seg_norms)
    seg_normalized = seg_embeddings / seg_norms

    cat_norms = np.linalg.norm(cat_matrix, axis=1, keepdims=True)
    cat_norms = np.where(cat_norms == 0, 1e-10, cat_norms)
    cat_normalized = cat_matrix / cat_norms

    # Cosine Similarity: (n_segments, n_categories)
    sim_matrix = seg_normalized @ cat_normalized.T

    results = []
    for i in range(len(segments)):
        scores = [(cat_names[j], float(sim_matrix[i, j])) for j in range(len(cat_names))]
        scores.sort(key=lambda x: x[1], reverse=True)
        results.append(scores[:top_k])

    return results


# ── CLIP-Ranking innerhalb einer Kategorie ────────────────────────────────

def _extract_thumbnail(video_path: str, time_s: float, size: int = 224) -> Optional[np.ndarray]:
    """Extrahiert ein Thumbnail-Frame aus einem Video via ffmpeg."""
    cmd = [
        "ffmpeg", "-ss", str(time_s), "-i", str(video_path),
        "-vframes", "1", "-vf", f"scale={size}:{size}:force_original_aspect_ratio=decrease,pad={size}:{size}:(ow-iw)/2:(oh-ih)/2",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-v", "error", "-"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode != 0 or len(result.stdout) == 0:
            return None
        frame = np.frombuffer(result.stdout, dtype=np.uint8).reshape(size, size, 3)
        return frame
    except Exception:
        return None


def _get_clip_duration(clip_path: str) -> float:
    """Ermittelt die Dauer eines Clips in Sekunden via ffprobe."""
    from shared.ffmpeg_utils import probe_duration
    try:
        return probe_duration(clip_path)
    except Exception:
        return 0.0


def rank_clips_in_category(
    category: BRollCategory,
    segment_text: str,
    max_clips: int = 5,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> list[tuple[str, float]]:
    """Rankt B-Roll-Clips einer Kategorie per CLIP gegen den Segment-Text.

    Extrahiert ein Thumbnail pro Clip (Mittelpunkt) und berechnet
    CLIP Text-Image Similarity.

    Args:
        category: B-Roll-Kategorie mit clip_paths.
        segment_text: Transkript-Text des Segments.
        max_clips: Maximale Anzahl Ergebnisse.

    Returns:
        [(clip_path, score), ...] sortiert nach Score absteigend.
    """
    if not category.clip_paths:
        return []

    try:
        import torch
        from transformers import CLIPProcessor, CLIPModel
    except ImportError:
        _log.warning("transformers/torch nicht installiert, CLIP-Ranking übersprungen")
        return [(p, 0.0) for p in category.clip_paths[:max_clips]]

    # Device auswählen (Pattern aus add_reactions_to_edl.py)
    device = "cpu"
    if torch.backends.mps.is_available():
        device = "mps"
    elif torch.cuda.is_available():
        device = "cuda"

    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(device)
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

    # Thumbnails extrahieren
    clips_with_frames: list[tuple[str, np.ndarray]] = []
    for i, clip_path in enumerate(category.clip_paths):
        if progress_cb:
            progress_cb(i / len(category.clip_paths), f"Thumbnail {i + 1}/{len(category.clip_paths)} …")

        dur = _get_clip_duration(clip_path)
        mid_s = dur / 2 if dur > 0 else 1.0
        frame = _extract_thumbnail(clip_path, mid_s)
        if frame is not None:
            clips_with_frames.append((clip_path, frame))

    if not clips_with_frames:
        return []

    # CLIP-Scoring
    from PIL import Image

    images = [Image.fromarray(f) for _, f in clips_with_frames]
    inputs = processor(
        text=[segment_text],
        images=images,
        return_tensors="pt",
        padding=True,
        truncation=True,
    ).to(device)

    with torch.no_grad():
        outputs = model(**inputs)
        # logits_per_text: (1, n_images)
        scores = outputs.logits_per_text.softmax(dim=-1)[0].cpu().numpy()

    results = [
        (clips_with_frames[i][0], float(scores[i]))
        for i in range(len(clips_with_frames))
    ]
    results.sort(key=lambda x: x[1], reverse=True)

    return results[:max_clips]


# ── B-Roll-Platzierung ────────────────────────────────────────────────────

def suggest_broll_placements(
    segments: list[FinalSegment],
    categories: list[BRollCategory],
    max_broll_density: float = 0.4,
    min_segment_duration_s: float = 2.0,
    enable_splitscreen: bool = False,
    splitscreen_threshold_s: float = 3.0,
    model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> list[FinalSegment]:
    """Schlägt B-Roll-Platzierungen für Segmente vor.

    Algorithmus:
    1. Kategorie-Embeddings erstellen
    2. Jedes Segment → beste Kategorie matchen
    3. Innerhalb der Kategorie → CLIP-Ranking
    4. Density-Limit beachten (max_broll_density)
    5. Kurze Segmente (< min_segment_duration_s) überspringen

    Modifiziert segments in-place (setzt seg.broll).

    Returns:
        Die (modifizierten) Segmente.
    """
    if not segments or not categories:
        return segments

    if progress_cb:
        progress_cb(0.05, "Kategorie-Embeddings …")

    cat_embeddings = embed_categories(categories, model_name)

    if progress_cb:
        progress_cb(0.2, "Segment-Kategorie-Matching …")

    seg_matches = match_segments_to_categories(segments, cat_embeddings, model_name)

    # Kategorie-Lookup
    cat_by_name = {c.name: c for c in categories}

    # Density-Budget berechnen
    total_duration = sum(s.duration_s for s in segments)
    max_broll_s = total_duration * max_broll_density
    used_broll_s = 0.0

    # Pro Segment: beste Kategorie → CLIP-Ranking → Platzierung
    for i, (seg, matches) in enumerate(zip(segments, seg_matches)):
        if progress_cb:
            progress_cb(0.2 + 0.7 * i / len(segments),
                        f"B-Roll {i + 1}/{len(segments)} …")

        # Zu kurz für B-Roll?
        if seg.duration_s < min_segment_duration_s:
            continue

        # Density-Limit erreicht?
        if used_broll_s >= max_broll_s:
            _log.info("B-Roll density limit erreicht (%.1fs / %.1fs)",
                      used_broll_s, max_broll_s)
            break

        if not matches:
            continue

        # Beste Kategorie nehmen
        best_cat_name, cat_score = matches[0]
        category = cat_by_name.get(best_cat_name)
        if not category or not category.clip_paths:
            continue

        # CLIP-Ranking
        ranked = rank_clips_in_category(category, seg.transcript_text, max_clips=1)
        if not ranked:
            continue

        clip_path, clip_score = ranked[0]
        clip_dur = _get_clip_duration(clip_path)
        if clip_dur <= 0:
            continue

        # B-Roll-Dauer: Segment-Dauer, aber max. Clip-Dauer
        broll_dur = min(seg.duration_s, clip_dur)
        source_in = 0.0
        source_out = broll_dur

        is_split = enable_splitscreen and seg.duration_s >= splitscreen_threshold_s

        seg.broll = BRollPlacement(
            category_name=best_cat_name,
            clip_path=clip_path,
            source_in_s=round(source_in, 3),
            source_out_s=round(source_out, 3),
            match_score=round(cat_score * clip_score, 4),
            is_splitscreen=is_split,
        )
        used_broll_s += broll_dur

    if progress_cb:
        n_placed = sum(1 for s in segments if s.broll is not None)
        progress_cb(1.0, f"{n_placed} B-Roll-Vorschläge erstellt.")

    _log.info("B-Roll: %d/%d Segmente mit Vorschlag, %.1fs / %.1fs Budget",
              sum(1 for s in segments if s.broll), len(segments),
              used_broll_s, max_broll_s)

    return segments
