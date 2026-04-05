"""
Project and timeline operations in DaVinci Resolve.
"""

import os
from .connection import get_resolve


def get_project_info():
    """
    Returns info about the currently open Resolve project.
    """
    resolve = get_resolve()
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()

    if project is None:
        raise RuntimeError("Kein Projekt geöffnet in DaVinci Resolve.")

    timelines = []
    for i in range(1, project.GetTimelineCount() + 1):
        tl = project.GetTimelineByIndex(i)
        timelines.append(tl.GetName())

    current_tl = project.GetCurrentTimeline()

    return {
        "name": project.GetName(),
        "fps": project.GetSetting("timelineFrameRate"),
        "timeline_count": project.GetTimelineCount(),
        "timelines": timelines,
        "current_timeline": current_tl.GetName() if current_tl else None,
    }


def import_edl(edl_path: str, timeline_name: str = None):
    """
    Imports an EDL file into the current Resolve project as a new timeline.

    Args:
        edl_path: Absolute path to the .edl file
        timeline_name: Name for the new timeline (default: EDL filename)
    """
    if not timeline_name:
        timeline_name = os.path.splitext(os.path.basename(edl_path))[0]

    resolve = get_resolve()
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()

    if project is None:
        raise RuntimeError("Kein Projekt geöffnet in DaVinci Resolve.")

    media_pool = project.GetMediaPool()

    import_options = {
        "timelineName": timeline_name,
        "importSourceClips": False,
        "sourceClipsPath": "",
    }

    timeline = media_pool.ImportTimelineFromFile(edl_path, import_options)

    if timeline is None:
        raise RuntimeError(
            f"EDL konnte nicht importiert werden: {edl_path}\n"
            "Prüfe ob der Pfad korrekt ist und Resolve ein Projekt geöffnet hat."
        )

    return timeline.GetName()
