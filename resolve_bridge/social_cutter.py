"""
Resolve-Bridge für den Social Cutter.

Operationen auf der DaVinci Resolve Timeline:
- Marker setzen an Phrasengrenzen
- Zoom/Pan/Tilt pro Clip setzen
- B-Roll auf V2 platzieren
- Redundante Segmente entfernen
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .connection import get_resolve
from .markers import add_marker, delete_markers_by_color
from shared.frame_utils import timecode_to_frames, frames_to_timecode

if TYPE_CHECKING:
    from modules.social_cutter.types import (
        BRollCategory,
        FinalSegment,
        PhraseBoundary,
    )

_log = logging.getLogger("rtk.social_cutter")

_VIDEO_EXT = {".mp4", ".mov", ".mxf", ".avi", ".mkv", ".r3d", ".braw", ".mts", ".m2ts"}


# ── B-Roll Keyword-Scan ───────────────────────────────────────────────────

def scan_broll_keywords(marker_keyword: str = "b-roll") -> list[BRollCategory]:
    """Scannt den Media Pool nach Clips mit Keyword-Tag.

    Clips, deren ``Keyword``-Feld den ``marker_keyword`` enthält, gelten
    als B-Roll.  Alle weiteren Keywords des Clips werden als Kategorien
    interpretiert.  Ein Clip kann in mehreren Kategorien auftauchen.

    Args:
        marker_keyword: Pflicht-Keyword, das einen Clip als B-Roll markiert.

    Returns:
        Liste von ``BRollCategory`` — eine pro gefundener Kategorie.
        Jede Kategorie enthält die Dateipfade der zugehörigen Clips.
    """
    from pathlib import Path
    from modules.social_cutter.types import BRollCategory

    resolve = get_resolve()
    project = resolve.GetProjectManager().GetCurrentProject()
    mp = project.GetMediaPool()
    root = mp.GetRootFolder()

    # {kategorie_name: [clip_path, ...]}
    cat_clips: dict[str, list[str]] = {}

    def _scan(folder):
        for item in (folder.GetClipList() or []):
            raw_kw = item.GetClipProperty("Keyword") or ""
            if not raw_kw:
                continue
            keywords = [k.strip().lower() for k in raw_kw.split(",") if k.strip()]
            if marker_keyword.lower() not in keywords:
                continue

            fp = item.GetClipProperty("File Path") or ""
            if not fp or Path(fp).suffix.lower() not in _VIDEO_EXT:
                continue

            # Alle Keywords außer dem Marker sind Kategorien
            cats = [k for k in keywords if k != marker_keyword.lower()]
            if not cats:
                # Kein Kategorie-Keyword → "uncategorized"
                cats = ["uncategorized"]

            for cat in cats:
                cat_clips.setdefault(cat, []).append(fp)

        for sf in (folder.GetSubFolderList() or []):
            _scan(sf)

    _scan(root)

    result = [
        BRollCategory(name=name, clip_paths=sorted(set(paths)))
        for name, paths in sorted(cat_clips.items())
    ]

    _log.info("B-Roll Keyword-Scan: %d Kategorien, %d Clips total",
              len(result), sum(len(c.clip_paths) for c in result))
    return result


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_current_timeline():
    """Gibt die aktuelle Resolve-Timeline zurück."""
    resolve = get_resolve()
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError("Keine aktive Timeline in DaVinci Resolve.")
    return timeline


def _seconds_to_frame(seconds: float, fps: float) -> int:
    """Konvertiert Sekunden → Frame-Nummer."""
    return int(round(seconds * fps))


# ── Marker ─────────────────────────────────────────────────────────────────

def set_markers_at_boundaries(
    boundaries: list[PhraseBoundary],
    fps: float,
    tl_start_frame: int,
) -> int:
    """Setzt farbkodierte Marker an Phrasengrenzen.

    Farben:
    - Grün:  Satzende (falling pitch)
    - Gelb:  Halbsatz (rising pitch)
    - Blau:  Pause
    - Lemon: Sonstige

    Args:
        boundaries: Erkannte Phrasengrenzen.
        fps: Timeline-Framerate.
        tl_start_frame: Absoluter Timeline-Start-Frame.

    Returns:
        Anzahl gesetzter Marker.
    """
    color_map = {
        "falling": "green",
        "rising": "yellow",
        "flat": "blue",
    }

    count = 0
    for b in boundaries:
        frame = tl_start_frame + _seconds_to_frame(b.time_s, fps)
        color = color_map.get(b.pitch_trend, "lemon")
        name = f"{b.boundary_type.value} ({b.confidence:.0%})"
        note = f"{b.word_before} | {b.word_after}"

        try:
            success = add_marker(frame, color=color, name=name, note=note)
            if success:
                count += 1
        except Exception as e:
            _log.warning("Marker bei Frame %d fehlgeschlagen: %s", frame, e)

    _log.info("Markers: %d / %d gesetzt", count, len(boundaries))
    return count


def clear_boundary_markers():
    """Entfernt alle Phrasengrenz-Marker (grün, gelb, blau, lemon)."""
    for color in ("green", "yellow", "blue", "lemon"):
        try:
            delete_markers_by_color(color)
        except Exception:
            pass


# ── Zoom/Pan/Tilt ─────────────────────────────────────────────────────────

def apply_zoom_params(
    segments: list[FinalSegment],
    fps: float,
) -> int:
    """Setzt ZoomX, ZoomY, Pan, Tilt pro Clip auf V1.

    Resolve Clip Properties:
    - ZoomX / ZoomY: Scale-Faktor (1.0 = 100%)
    - Pan: Horizontale Verschiebung in Pixel
    - Tilt: Vertikale Verschiebung in Pixel

    Returns:
        Anzahl erfolgreich gesetzter Clips.
    """
    timeline = _get_current_timeline()
    tl_start = timeline.GetStartFrame()

    # V1-Clips holen
    items = timeline.GetItemListInTrack("video", 1)
    if not items:
        _log.warning("Keine Clips auf V1 gefunden")
        return 0

    count = 0
    for seg in segments:
        if seg.zoom is None:
            continue

        seg_frame = tl_start + _seconds_to_frame(seg.source_start_s, fps)

        # Clip finden, der diesen Frame enthält
        target_item = None
        for item in items:
            if item.GetStart() <= seg_frame < item.GetEnd():
                target_item = item
                break

        if target_item is None:
            _log.debug("Kein Clip bei Frame %d für Segment %d", seg_frame, seg.index)
            continue

        z = seg.zoom
        try:
            target_item.SetProperty("ZoomX", z.scale)
            target_item.SetProperty("ZoomY", z.scale)
            if z.pan != 0:
                target_item.SetProperty("Pan", z.pan)
            if z.tilt != 0:
                target_item.SetProperty("Tilt", z.tilt)
            count += 1
        except Exception as e:
            _log.warning("Zoom setzen fehlgeschlagen für Segment %d: %s", seg.index, e)

    _log.info("Zoom: %d / %d Segmente gesetzt", count, len(segments))
    return count


# ── B-Roll auf V2 ─────────────────────────────────────────────────────────

def place_broll(
    segments: list[FinalSegment],
    fps: float,
) -> int:
    """Platziert B-Roll-Clips auf V2.

    Für jedes Segment mit broll-Zuweisung wird der Clip aus dem
    Media Pool geladen und auf V2 an der entsprechenden Position platziert.

    Returns:
        Anzahl platzierter B-Roll-Clips.
    """
    timeline = _get_current_timeline()
    tl_start = timeline.GetStartFrame()

    resolve = get_resolve()
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    media_pool = project.GetMediaPool()

    # V2 sicherstellen
    track_count = timeline.GetTrackCount("video")
    if track_count < 2:
        timeline.AddTrack("video")
        _log.info("Video Track 2 hinzugefügt")

    count = 0
    for seg in segments:
        if seg.broll is None:
            continue

        b = seg.broll
        target_frame = tl_start + _seconds_to_frame(seg.source_start_s, fps)

        # Clip im Media Pool finden oder importieren
        clip = _find_or_import_clip(media_pool, b.clip_path)
        if clip is None:
            _log.warning("B-Roll-Clip nicht gefunden: %s", b.clip_path)
            continue

        # Source In/Out in Frames
        src_in = _seconds_to_frame(b.source_in_s, fps)
        src_out = _seconds_to_frame(b.source_out_s, fps)

        try:
            # Clip auf V2 platzieren
            success = media_pool.AppendToTimeline([{
                "mediaPoolItem": clip,
                "startFrame": src_in,
                "endFrame": src_out,
                "trackIndex": 2,
                "recordFrame": target_frame,
            }])
            if success:
                count += 1
        except Exception as e:
            _log.warning("B-Roll platzieren fehlgeschlagen: %s — %s", b.clip_path, e)

    _log.info("B-Roll: %d / %d Clips platziert", count,
              sum(1 for s in segments if s.broll is not None))
    return count


def _find_or_import_clip(media_pool, clip_path: str):
    """Sucht einen Clip im Media Pool oder importiert ihn."""
    from pathlib import Path

    # Im Root-Folder suchen
    root_folder = media_pool.GetRootFolder()
    clip = _search_folder(root_folder, clip_path)
    if clip:
        return clip

    # Subfolders durchsuchen
    for subfolder in root_folder.GetSubFolderList() or []:
        clip = _search_folder(subfolder, clip_path)
        if clip:
            return clip

    # Nicht gefunden → importieren
    p = Path(clip_path)
    if not p.exists():
        return None

    imported = media_pool.ImportMedia([str(p)])
    if imported and len(imported) > 0:
        return imported[0]

    return None


def _search_folder(folder, clip_path: str):
    """Durchsucht einen Media Pool Folder nach einem Clip-Pfad."""
    from pathlib import Path

    target = Path(clip_path).name
    for item in folder.GetClipList() or []:
        if item.GetClipProperty("File Path", "").endswith(target):
            return item
    return None


# ── Segmente entfernen ─────────────────────────────────────────────────────

def remove_segments_from_timeline(
    segments_to_remove: list[FinalSegment],
    fps: float,
) -> int:
    """Entfernt abgewählte Segmente aus der Timeline.

    Arbeitet rückwärts (von hinten nach vorne), damit sich die
    Frame-Positionen der noch zu entfernenden Segmente nicht verschieben.

    Returns:
        Anzahl entfernter Segmente.
    """
    timeline = _get_current_timeline()
    tl_start = timeline.GetStartFrame()

    # Rückwärts sortieren (späteste Segmente zuerst)
    sorted_segs = sorted(segments_to_remove, key=lambda s: s.source_start_s, reverse=True)

    items = timeline.GetItemListInTrack("video", 1)
    if not items:
        return 0

    count = 0
    for seg in sorted_segs:
        seg_start = tl_start + _seconds_to_frame(seg.source_start_s, fps)
        seg_end = tl_start + _seconds_to_frame(seg.source_end_s, fps)

        # Clip(s) finden die in diesem Bereich liegen
        to_delete = []
        for item in items:
            item_start = item.GetStart()
            item_end = item.GetEnd()
            # Clip liegt (teilweise) im Segment-Bereich
            if item_start < seg_end and item_end > seg_start:
                to_delete.append(item)

        for item in to_delete:
            try:
                timeline.DeleteTimelineItem(item)
                count += 1
            except Exception as e:
                _log.warning("Segment %d löschen fehlgeschlagen: %s", seg.index, e)

        # Items-Liste nach Löschung aktualisieren
        items = timeline.GetItemListInTrack("video", 1) or []

    _log.info("Segmente entfernt: %d / %d", count, len(segments_to_remove))
    return count
