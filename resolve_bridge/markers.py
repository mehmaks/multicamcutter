"""
Marker operations in DaVinci Resolve timelines.
"""

from .connection import get_resolve

MARKER_COLORS = {
    "blue", "cyan", "green", "yellow",
    "red", "pink", "purple", "fuchsia",
    "rose", "lavender", "sky", "mint",
    "lemon", "sand", "cocoa", "cream",
}


def _get_timeline():
    resolve = get_resolve()
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError("Keine aktive Timeline in DaVinci Resolve.")
    return timeline


def add_marker(frame: int, color: str = "blue", name: str = "",
               note: str = "", duration: int = 1):
    """
    Adds a marker to the current timeline.

    Args:
        frame:    Timeline frame number
        color:    Marker color (see MARKER_COLORS)
        name:     Short marker name
        note:     Longer description
        duration: Marker duration in frames (1 = point marker, >1 = range marker)
    """
    if color not in MARKER_COLORS:
        raise ValueError(f"Ungültige Farbe '{color}'. Erlaubt: {sorted(MARKER_COLORS)}")
    timeline = _get_timeline()
    tl_start = timeline.GetStartFrame()
    return timeline.AddMarker(frame - tl_start, color.capitalize(), name, note, duration)


def add_markers_from_events(events: list, color: str = "blue"):
    """
    Adds multiple markers from a list of event dicts.
    Each event: {"frame": int, "duration": int, "name": str, "note": str}
    Returns count of successfully added markers.
    """
    count = 0
    for event in events:
        frame = event.get("frame")
        if frame is None:
            continue
        success = add_marker(
            frame=frame,
            color=color,
            name=event.get("name", ""),
            note=event.get("note", ""),
            duration=event.get("duration", 1),
        )
        if success:
            count += 1
    return count


def delete_markers_by_color(color: str):
    """Deletes all markers of the given color from the current timeline."""
    if color not in MARKER_COLORS:
        raise ValueError(f"Ungültige Farbe '{color}'. Erlaubt: {sorted(MARKER_COLORS)}")
    timeline = _get_timeline()
    timeline.DeleteMarkersByColor(color.capitalize())
