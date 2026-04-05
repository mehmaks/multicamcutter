"""
Tests different EDL import strategies into the current Resolve timeline.
Run with DaVinci Resolve open and a test timeline active.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolve_bridge.connection import get_resolve

EDL_PATH = "/Users/maxmenge/Library/CloudStorage/Dropbox/_CLAUDE/multicam-auto-cutter/final_v24.edl"

resolve = get_resolve()
pm = resolve.GetProjectManager()
project = pm.GetCurrentProject()
tl = project.GetCurrentTimeline()
mp = project.GetMediaPool()

print(f"Timeline: {tl.GetName()}")
print(f"EDL: {EDL_PATH}")
print()

# --- Finde den "30 - Ebra" Bin im Media Pool ---
def find_bin(folder, name):
    if folder.GetName() == name:
        return folder
    for sf in (folder.GetSubFolderList() or []):
        result = find_bin(sf, name)
        if result:
            return result
    return None

root = mp.GetRootFolder()
ebra_bin = find_bin(root, "30 - Ebra")
print(f"Bin gefunden: {ebra_bin.GetName() if ebra_bin else 'NICHT GEFUNDEN'}")
print()

# --- Versuch 1: ImportIntoTimeline mit sourceClipsFolders ---
print("=== Test 1: ImportIntoTimeline mit Bin-Referenz ===")
opts = {}
if ebra_bin:
    opts["sourceClipsFolders"] = [ebra_bin]
result1 = tl.ImportIntoTimeline(EDL_PATH, opts)
print(f"Ergebnis: {result1}")
print()

# --- Versuch 2: ImportTimelineFromFile (neue Timeline) mit Bin ---
print("=== Test 2: ImportTimelineFromFile (neue Timeline) ===")
opts2 = {
    "timelineName": "EDL Import Test",
    "importSourceClips": False,
}
if ebra_bin:
    opts2["sourceClipsFolders"] = [ebra_bin]
result2 = mp.ImportTimelineFromFile(EDL_PATH, opts2)
print(f"Ergebnis: {result2}")
if result2:
    print(f"Neue Timeline: {result2.GetName()}")
    print(f"  Video Tracks: {result2.GetTrackCount('video')}")
    for i in range(1, result2.GetTrackCount('video') + 1):
        items = result2.GetItemListInTrack('video', i)
        print(f"  V{i}: {len(items) if items else 0} Clips")
        if items:
            for item in items[:3]:
                mi = item.GetMediaPoolItem()
                linked = mi.GetClipProperty('File Path') if mi else 'nicht verknüpft'
                print(f"    {item.GetName()} → {linked[:60] if linked else 'kein MediaPoolItem'}...")
