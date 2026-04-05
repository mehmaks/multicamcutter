"""
Exploration script: prints everything Resolve exposes about the current timeline.
Run this to understand the data structure before building the full integration.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolve_bridge.connection import get_resolve

resolve = get_resolve()
pm = resolve.GetProjectManager()
project = pm.GetCurrentProject()
timeline = project.GetCurrentTimeline()

print(f"Timeline: {timeline.GetName()}")
print(f"Start frame: {timeline.GetStartFrame()}")
print(f"End frame:   {timeline.GetEndFrame()}")
print(f"FPS:         {timeline.GetSetting('timelineFrameRate')}")
print()

for track_type in ("video", "audio"):
    count = timeline.GetTrackCount(track_type)
    print(f"=== {track_type.upper()} TRACKS ({count}) ===")
    for i in range(1, count + 1):
        name = timeline.GetTrackName(track_type, i)
        items = timeline.GetItemListInTrack(track_type, i)
        print(f"\n  Track {i} — '{name}' ({len(items) if items else 0} clips)")
        if not items:
            continue
        for clip in items:
            mi = clip.GetMediaPoolItem()
            props = {}
            if mi:
                for key in ("File Path", "Clip Name", "FPS", "Start TC", "End TC"):
                    props[key] = mi.GetClipProperty(key)

            print(f"    Clip: {clip.GetName()}")
            print(f"      Timeline start:       {clip.GetStart()}")
            print(f"      Timeline end:         {clip.GetEnd()}")
            print(f"      Source start frame:   {clip.GetSourceStartFrame()}")
            print(f"      Source end frame:     {clip.GetSourceEndFrame()}")
            print(f"      Left offset:          {clip.GetLeftOffset()}")
            print(f"      Right offset:         {clip.GetRightOffset()}")
            if mi:
                print(f"      File path:            {props.get('File Path', 'N/A')}")
                print(f"      Start TC:             {props.get('Start TC', 'N/A')}")
