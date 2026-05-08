"""
Social Cutter — Redundanz-Erkennung.

Findet semantisch ähnliche Sätze im Transkript mittels
sentence-transformers Embeddings und Cosine-Similarity.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import numpy as np

from .types import RedundancyGroup, Sentence

_log = logging.getLogger("rtk.social_cutter")


def detect_redundancy(
    sentences: list[Sentence],
    similarity_threshold: float = 0.75,
    model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> list[RedundancyGroup]:
    """Findet Gruppen semantisch ähnlicher Sätze.

    Args:
        sentences: Liste von Sentence-Objekten mit Text.
        similarity_threshold: Ab welcher Cosine-Similarity Sätze als
            Wiederholung gelten (0–1).
        model_name: sentence-transformers Modell.
        progress_cb: Callback(progress_0_1, status_text).

    Returns:
        Liste von RedundancyGroup. Nicht-redundante Sätze werden nicht
        zurückgegeben — nur Gruppen mit 2+ ähnlichen Sätzen.
    """
    if len(sentences) < 2:
        return []

    if progress_cb:
        progress_cb(0.1, "Sentence-Transformer laden …")

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)

    if progress_cb:
        progress_cb(0.3, "Sätze embedden …")

    texts = [s.text for s in sentences]
    embeddings = model.encode(texts, show_progress_bar=False)

    # Embeddings in Sentence-Objekte speichern
    for sent, emb in zip(sentences, embeddings):
        sent.embedding = emb.tolist()

    if progress_cb:
        progress_cb(0.7, "Ähnlichkeiten berechnen …")

    # Pairwise Cosine Similarity
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-10, norms)
    normalized = embeddings / norms
    sim_matrix = normalized @ normalized.T

    # Gruppen finden (Union-Find-ähnlich)
    n = len(sentences)
    assigned = set()
    groups: list[RedundancyGroup] = []

    for i in range(n):
        if i in assigned:
            continue
        group_indices = [i]
        for j in range(i + 1, n):
            if j in assigned:
                continue
            if sim_matrix[i, j] >= similarity_threshold:
                group_indices.append(j)

        if len(group_indices) >= 2:
            group_sents = [sentences[idx] for idx in group_indices]
            # Durchschnittliche Similarity innerhalb der Gruppe
            sims = []
            for a in range(len(group_indices)):
                for b in range(a + 1, len(group_indices)):
                    sims.append(float(sim_matrix[group_indices[a], group_indices[b]]))
            avg_sim = sum(sims) / len(sims) if sims else 0.0

            groups.append(RedundancyGroup(
                sentences=group_sents,
                similarity=round(avg_sim, 3),
                selected_index=0,  # Default: ersten Satz behalten
            ))
            assigned.update(group_indices)

    if progress_cb:
        progress_cb(1.0, f"{len(groups)} Redundanz-Gruppen gefunden.")

    _log.info("Redundancy: %d groups from %d sentences (threshold=%.2f)",
              len(groups), n, similarity_threshold)
    return groups


def apply_selections(
    sentences: list[Sentence],
    groups: list[RedundancyGroup],
) -> list[Sentence]:
    """Entfernt redundante Sätze basierend auf User-Auswahl.

    Für jede RedundancyGroup wird nur der Satz am selected_index behalten.
    Nicht-gruppierte Sätze bleiben immer erhalten.

    Returns:
        Bereinigte Liste von Sentence-Objekten, sortiert nach Startzeit.
    """
    # Indices der zu entfernenden Sätze sammeln
    remove_indices: set[int] = set()
    for group in groups:
        selected = group.selected_index if group.selected_index is not None else 0
        for i, sent in enumerate(group.sentences):
            if i != selected:
                remove_indices.add(sent.index)

    kept = [s for s in sentences if s.index not in remove_indices]
    kept.sort(key=lambda s: s.start_s)
    return kept
