"""
Social Cutter — Datentypen für den Pipeline-State.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

_log = logging.getLogger("rtk.social_cutter")

_STATE_FILE = Path("/tmp/social_cutter_state.json")
_CLIP_AUDIO_FILE = Path("/tmp/social_cutter_clip.wav")


# ── Input ────────────────────────────────────────────────────────────────────

@dataclass
class BRollCategory:
    """Eine B-Roll-Kategorie (aus Resolve-Keywords oder Ordnern).

    Resolve-Workflow: Clips mit Keyword 'b-roll' + Kategorie-Keyword.
    Datei-Workflow: Ordner mit thematisch sortiertem Material.
    """
    name: str
    clip_paths: list[str] = field(default_factory=list)


@dataclass
class SocialCutterInput:
    """Alles was der User in Schritt 0 bereitstellt."""
    talking_head_path: str
    fps: float
    target_duration_s: float = 30.0
    broll_categories: list[BRollCategory] = field(default_factory=list)


# ── Silence Cut ──────────────────────────────────────────────────────────────

@dataclass
class SilenceSegment:
    """Ein behaltenes (nicht-stilles) Segment."""
    start_s: float
    end_s: float


# ── Whisper Transkription ────────────────────────────────────────────────────

@dataclass
class Word:
    """Einzelnes Wort mit Timing aus Whisper."""
    text: str
    start_s: float
    end_s: float
    confidence: float


@dataclass
class TranscriptResult:
    """Whisper-Transkription mit word-level Timestamps."""
    words: list[Word]
    full_text: str
    language: str
    segments: list[dict] = field(default_factory=list)


# ── Phrasengrenzen ───────────────────────────────────────────────────────────

class BoundaryType(Enum):
    SENTENCE_END = "sentence_end"
    CLAUSE_END = "clause_end"
    PAUSE = "pause"
    PITCH_FALL = "pitch_fall"


@dataclass
class PhraseBoundary:
    """Ein Schnittmarken-Kandidat zwischen Phrasen."""
    time_s: float
    boundary_type: BoundaryType
    confidence: float
    pitch_trend: str
    word_before: str
    word_after: str


# ── Sätze + Redundanz ───────────────────────────────────────────────────────

@dataclass
class Sentence:
    """Ein aus Phrasengrenzen extrahierter Satz."""
    index: int
    text: str
    start_s: float
    end_s: float
    word_count: int
    embedding: Optional[list[float]] = None


@dataclass
class RedundancyGroup:
    """Gruppe semantisch ähnlicher Sätze."""
    sentences: list[Sentence]
    similarity: float
    selected_index: Optional[int] = None


# ── Zoom ─────────────────────────────────────────────────────────────────────

class ZoomTier(Enum):
    WIDE = "wide"
    MEDIUM = "medium"
    CLOSE = "close"
    TIGHT = "tight"


@dataclass
class FacePosition:
    """MediaPipe Face-Detection Ergebnis, normalisiert 0–1."""
    center_x: float
    center_y: float
    face_height: float


@dataclass
class ZoomParams:
    """Zoom + Pan/Tilt für ein Segment."""
    tier: ZoomTier
    scale: float
    pan: float
    tilt: float
    face_pos: Optional[FacePosition] = None


# ── B-Roll ───────────────────────────────────────────────────────────────────

@dataclass
class BRollPlacement:
    """Ein B-Roll-Clip der einem Segment zugeordnet wurde."""
    category_name: str
    clip_path: str
    source_in_s: float
    source_out_s: float
    match_score: float
    is_splitscreen: bool = False


# ── Finale Segmente ─────────────────────────────────────────────────────────

@dataclass
class FinalSegment:
    """Ein Segment im finalen Edit."""
    index: int
    source_start_s: float
    source_end_s: float
    duration_s: float
    transcript_text: str
    zoom: Optional[ZoomParams] = None
    broll: Optional[BRollPlacement] = None


# ── Pipeline-State ───────────────────────────────────────────────────────────

@dataclass
class SocialCutterState:
    """Kompletter Pipeline-State.  Wird als JSON in /tmp/ persistiert."""
    src_path: str = ""
    src_start_s: float = 0.0          # Clip Source-In  (Sekunden im Quellfile)
    src_end_s: float = 0.0            # Clip Source-Out (0 = volle Datei)
    broll_categories: list[BRollCategory] = field(default_factory=list)
    silence_segments: list[SilenceSegment] = field(default_factory=list)
    transcript: Optional[TranscriptResult] = None
    phrase_boundaries: list[PhraseBoundary] = field(default_factory=list)
    sentences: list[Sentence] = field(default_factory=list)
    redundancy_groups: list[RedundancyGroup] = field(default_factory=list)
    final_segments: list[FinalSegment] = field(default_factory=list)
    leveled_audio_path: Optional[str] = None

    # ── Clip-Audio ─────────────────────────────────────────────────────

    @property
    def has_clip_range(self) -> bool:
        """True wenn ein Sub-Range der Quelldatei definiert ist."""
        return self.src_end_s > self.src_start_s > 0 or self.src_end_s > 0

    @property
    def clip_audio_path(self) -> str:
        """Pfad zur extrahierten Clip-Audio (WAV).

        Wenn kein Clip-Range definiert ist, wird der Quellpfad direkt
        zurückgegeben (Whisper/Praat können Video-Dateien lesen).
        """
        if not self.has_clip_range:
            return self.src_path
        return str(_CLIP_AUDIO_FILE)

    def extract_clip_audio(self) -> str:
        """Extrahiert den Clip-Bereich als WAV nach /tmp/.

        Wird nur ausgeführt wenn ein Clip-Range definiert ist und die
        Datei noch nicht (oder veraltet) existiert.

        Returns:
            Pfad zur WAV-Datei.
        """
        if not self.has_clip_range:
            return self.src_path

        # Schon vorhanden und aktuell?
        if _CLIP_AUDIO_FILE.exists():
            return str(_CLIP_AUDIO_FILE)

        import subprocess
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(self.src_start_s),
            "-to", str(self.src_end_s),
            "-i", self.src_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(_CLIP_AUDIO_FILE),
        ]
        _log.info("Clip-Audio extrahieren: %.1f–%.1fs → %s",
                  self.src_start_s, self.src_end_s, _CLIP_AUDIO_FILE)
        subprocess.run(cmd, capture_output=True, check=True)
        return str(_CLIP_AUDIO_FILE)

    # ── Serialisierung ────────────────────────────────────────────────────

    def save(self) -> None:
        """Persistiert den State als JSON nach /tmp/."""
        try:
            data = self._to_dict()
            _STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        except Exception as e:
            _log.warning("State speichern fehlgeschlagen: %s", e)

    @classmethod
    def load(cls) -> "SocialCutterState":
        """Lädt den State aus /tmp/, oder gibt einen leeren State zurück."""
        if not _STATE_FILE.exists():
            return cls()
        try:
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            return cls._from_dict(data)
        except Exception as e:
            _log.warning("State laden fehlgeschlagen: %s", e)
            return cls()

    @staticmethod
    def clear() -> None:
        """Löscht State- und Clip-Audio-Datei."""
        for f in (_STATE_FILE, _CLIP_AUDIO_FILE):
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass

    def _to_dict(self) -> dict:
        """Konvertiert den State in ein JSON-serialisierbares Dict."""
        d = {}
        d["src_path"] = self.src_path
        d["src_start_s"] = self.src_start_s
        d["src_end_s"] = self.src_end_s
        d["broll_categories"] = [asdict(c) for c in self.broll_categories]
        d["silence_segments"] = [asdict(s) for s in self.silence_segments]
        d["transcript"] = self._transcript_to_dict(self.transcript) if self.transcript else None
        d["phrase_boundaries"] = [self._boundary_to_dict(b) for b in self.phrase_boundaries]
        d["sentences"] = [asdict(s) for s in self.sentences]
        d["redundancy_groups"] = [self._rgroup_to_dict(g) for g in self.redundancy_groups]
        d["final_segments"] = [self._fseg_to_dict(s) for s in self.final_segments]
        d["leveled_audio_path"] = self.leveled_audio_path
        return d

    @classmethod
    def _from_dict(cls, d: dict) -> "SocialCutterState":
        """Baut den State aus einem Dict auf."""
        state = cls()
        state.src_path = d.get("src_path", "")
        state.src_start_s = d.get("src_start_s", 0.0)
        state.src_end_s = d.get("src_end_s", 0.0)
        state.broll_categories = [
            BRollCategory(**c) for c in d.get("broll_categories", [])
        ]
        state.silence_segments = [
            SilenceSegment(**s) for s in d.get("silence_segments", [])
        ]
        tr = d.get("transcript")
        state.transcript = cls._transcript_from_dict(tr) if tr else None
        state.phrase_boundaries = [
            cls._boundary_from_dict(b) for b in d.get("phrase_boundaries", [])
        ]
        state.sentences = [
            Sentence(**s) for s in d.get("sentences", [])
        ]
        state.redundancy_groups = [
            cls._rgroup_from_dict(g) for g in d.get("redundancy_groups", [])
        ]
        state.final_segments = [
            cls._fseg_from_dict(s) for s in d.get("final_segments", [])
        ]
        state.leveled_audio_path = d.get("leveled_audio_path")
        return state

    # ── Nested-Object Helpers ─────────────────────────────────────────────

    @staticmethod
    def _transcript_to_dict(t: TranscriptResult) -> dict:
        return {
            "words": [asdict(w) for w in t.words],
            "full_text": t.full_text,
            "language": t.language,
            "segments": t.segments,
        }

    @staticmethod
    def _transcript_from_dict(d: dict) -> TranscriptResult:
        return TranscriptResult(
            words=[Word(**w) for w in d.get("words", [])],
            full_text=d.get("full_text", ""),
            language=d.get("language", ""),
            segments=d.get("segments", []),
        )

    @staticmethod
    def _boundary_to_dict(b: PhraseBoundary) -> dict:
        return {
            "time_s": b.time_s,
            "boundary_type": b.boundary_type.value,
            "confidence": b.confidence,
            "pitch_trend": b.pitch_trend,
            "word_before": b.word_before,
            "word_after": b.word_after,
        }

    @staticmethod
    def _boundary_from_dict(d: dict) -> PhraseBoundary:
        return PhraseBoundary(
            time_s=d["time_s"],
            boundary_type=BoundaryType(d["boundary_type"]),
            confidence=d["confidence"],
            pitch_trend=d["pitch_trend"],
            word_before=d["word_before"],
            word_after=d["word_after"],
        )

    @staticmethod
    def _rgroup_to_dict(g: RedundancyGroup) -> dict:
        return {
            "sentences": [asdict(s) for s in g.sentences],
            "similarity": g.similarity,
            "selected_index": g.selected_index,
        }

    @staticmethod
    def _rgroup_from_dict(d: dict) -> RedundancyGroup:
        return RedundancyGroup(
            sentences=[Sentence(**s) for s in d["sentences"]],
            similarity=d["similarity"],
            selected_index=d.get("selected_index"),
        )

    @staticmethod
    def _fseg_to_dict(s: FinalSegment) -> dict:
        d = asdict(s)
        if s.zoom:
            d["zoom"]["tier"] = s.zoom.tier.value
        return d

    @staticmethod
    def _fseg_from_dict(d: dict) -> FinalSegment:
        zoom = None
        if d.get("zoom"):
            zd = d["zoom"]
            face = FacePosition(**zd["face_pos"]) if zd.get("face_pos") else None
            zoom = ZoomParams(
                tier=ZoomTier(zd["tier"]),
                scale=zd["scale"],
                pan=zd["pan"],
                tilt=zd["tilt"],
                face_pos=face,
            )
        broll = BRollPlacement(**d["broll"]) if d.get("broll") else None
        return FinalSegment(
            index=d["index"],
            source_start_s=d["source_start_s"],
            source_end_s=d["source_end_s"],
            duration_s=d["duration_s"],
            transcript_text=d["transcript_text"],
            zoom=zoom,
            broll=broll,
        )
