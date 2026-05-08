"""
Social Cutter — Whisper Transkription mit Word-Level Timestamps.

Nutzt mlx-whisper auf Apple Silicon (80x schneller als OpenAI Whisper auf CPU).
Fällt auf OpenAI Whisper zurück wenn mlx-whisper nicht verfügbar ist.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Optional

from .types import TranscriptResult, Word

_log = logging.getLogger("rtk.social_cutter")

# HuggingFace Repo-IDs für mlx-whisper Modelle
_MLX_MODELS = {
    "tiny":   "mlx-community/whisper-tiny-mlx",
    "small":  "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large":  "mlx-community/whisper-large-v3-mlx",
}

# OpenAI Whisper Cache
_WHISPER_CACHE = Path(os.path.expanduser("~")) / ".cache" / "whisper"


def _model_cached(model_name: str) -> bool:
    """Prüft ob das OpenAI-Whisper-Modell bereits heruntergeladen ist."""
    if not _WHISPER_CACHE.exists():
        return False
    return (_WHISPER_CACHE / f"{model_name}.pt").exists()


def _has_mlx_whisper() -> bool:
    """Prüft ob mlx-whisper verfügbar ist (Apple Silicon)."""
    try:
        import mlx_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _transcribe_mlx(
    audio_path: str,
    language: str,
    model_name: str,
    progress_cb: Optional[Callable],
) -> dict:
    """Transkription via mlx-whisper (Apple Silicon, ~80x schneller)."""
    import mlx_whisper

    repo = _MLX_MODELS.get(model_name, _MLX_MODELS["medium"])

    if progress_cb:
        progress_cb(0.1, f"mlx-whisper '{model_name}' laden …")

    result = mlx_whisper.transcribe(
        str(audio_path),
        language=language,
        word_timestamps=True,
        path_or_hf_repo=repo,
    )
    return result


def _transcribe_openai(
    audio_path: str,
    language: str,
    model_name: str,
    progress_cb: Optional[Callable],
) -> dict:
    """Transkription via OpenAI Whisper (CPU-Fallback)."""
    import whisper

    cached = _model_cached(model_name)
    if progress_cb:
        if cached:
            progress_cb(0.05, f"Whisper '{model_name}' laden (cached) …")
        else:
            progress_cb(0.05, f"Whisper '{model_name}' herunterladen …")

    model = whisper.load_model(model_name)

    if progress_cb:
        progress_cb(0.2, "Transkription läuft (CPU — kann mehrere Minuten dauern) …")

    result = model.transcribe(
        str(audio_path),
        language=language,
        word_timestamps=True,
        verbose=False,
    )
    return result


def transcribe(
    audio_path: str,
    language: str = "de",
    model_name: str = "medium",
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> TranscriptResult:
    """Word-level Whisper-Transkription.

    Nutzt mlx-whisper auf Apple Silicon (bevorzugt) oder
    OpenAI Whisper auf CPU als Fallback.

    Args:
        audio_path: Pfad zur Audio-Datei (WAV, MP3, etc.)
        language: Sprache für Whisper.
        model_name: Whisper-Modellgröße ("tiny", "small", "medium", "large").
        progress_cb: Callback(progress_0_1, status_text).

    Returns:
        TranscriptResult mit allen Wörtern und Timestamps.
    """
    use_mlx = _has_mlx_whisper()

    if use_mlx:
        _log.info("Nutze mlx-whisper (%s) auf Apple Silicon", model_name)
        result = _transcribe_mlx(audio_path, language, model_name, progress_cb)
    else:
        _log.info("Nutze OpenAI Whisper (%s) auf CPU", model_name)
        result = _transcribe_openai(audio_path, language, model_name, progress_cb)

    if progress_cb:
        progress_cb(0.9, "Wörter extrahieren …")

    words: list[Word] = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            words.append(Word(
                text=w["word"].strip(),
                start_s=round(w["start"], 3),
                end_s=round(w["end"], 3),
                confidence=round(w.get("probability", 0.0), 3),
            ))

    full_text = result.get("text", "").strip()
    language_detected = result.get("language", language)

    if progress_cb:
        backend = "mlx" if use_mlx else "cpu"
        progress_cb(1.0, f"{len(words)} Wörter transkribiert ({backend}).")

    _log.info("Whisper (%s/%s): %d Wörter, Sprache=%s",
              "mlx" if use_mlx else "cpu", model_name, len(words), language_detected)

    return TranscriptResult(
        words=words,
        full_text=full_text,
        language=language_detected,
        segments=result.get("segments", []),
    )


def words_in_range(
    transcript: TranscriptResult,
    start_s: float,
    end_s: float,
) -> list[Word]:
    """Wörter deren Mittelpunkt im Zeitbereich [start_s, end_s] liegt."""
    return [
        w for w in transcript.words
        if start_s <= (w.start_s + w.end_s) / 2 <= end_s
    ]


def text_in_range(
    transcript: TranscriptResult,
    start_s: float,
    end_s: float,
) -> str:
    """Konkatenierter Text aller Wörter im Zeitbereich."""
    return " ".join(w.text for w in words_in_range(transcript, start_s, end_s))
