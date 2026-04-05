"""
Patches an FCP XML (xmeml) timeline by replacing its audio section
with the audio tracks from a sync timeline XML.

Usage:
    python patch_xml_audio.py --video video_cuts.xml --audio sync_timeline.xml --output final.xml
"""

import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def find_nested_tag(xml: str, tag: str, start: int = 0) -> tuple[int, int]:
    """
    Finds a <tag>...</tag> block starting from `start`, respecting nesting.
    Returns (start_pos, end_pos) of the full block, or (-1, -1) if not found.
    """
    open_tag  = f"<{tag}>"
    close_tag = f"</{tag}>"

    pos = xml.find(open_tag, start)
    if pos == -1:
        return -1, -1

    depth = 0
    i = pos
    while i < len(xml):
        if xml[i:i+len(open_tag)] == open_tag:
            depth += 1
            i += len(open_tag)
        elif xml[i:i+len(close_tag)] == close_tag:
            depth -= 1
            i += len(close_tag)
            if depth == 0:
                return pos, i
        else:
            i += 1
    return -1, -1


def extract_mic_audio_section(xml: str) -> str:
    """
    Extracts the sequence-level <audio>...</audio> block that contains MIC clips.
    Uses nesting-aware search to avoid stopping at inner <audio> tags.
    """
    pos = 0
    while True:
        start, end = find_nested_tag(xml, "audio", pos)
        if start == -1:
            break
        section = xml[start:end]
        if "MIC" in section or ("pathurl" in section and "channelcount" not in section[:100]):
            return section
        pos = end

    # Fallback: return the largest audio block
    pos = 0
    best = ""
    while True:
        start, end = find_nested_tag(xml, "audio", pos)
        if start == -1:
            break
        section = xml[start:end]
        if len(section) > len(best):
            best = section
        pos = end

    if not best:
        raise ValueError("Keine Audio-Sektion in der Sync-Timeline gefunden.")
    return best


def replace_audio_section(video_xml: str, mic_audio_section: str) -> str:
    """
    Replaces the largest sequence-level <audio> block in the video XML
    with the MIC audio section from the sync timeline.
    """
    pos = 0
    best_start, best_end, best_len = -1, -1, 0
    while True:
        start, end = find_nested_tag(video_xml, "audio", pos)
        if start == -1:
            break
        if (end - start) > best_len:
            best_start, best_end, best_len = start, end, end - start
        pos = end

    if best_start == -1:
        raise ValueError("Keine Audio-Sektion in der Video-XML gefunden.")

    return video_xml[:best_start] + mic_audio_section + video_xml[best_end:]


def patch_xml_audio(video_xml_path: str, sync_xml_path: str, output_path: str):
    with open(video_xml_path) as f:
        video_xml = f.read()
    with open(sync_xml_path) as f:
        sync_xml = f.read()

    print(f"Video XML:  {video_xml_path}")
    print(f"Sync XML:   {sync_xml_path}")

    mic_audio = extract_mic_audio_section(sync_xml)
    print(f"MIC-Audio-Sektion: {len(mic_audio)} chars — enthält: "
          + ", ".join(re.findall(r'<name>(MIC\d\.WAV)</name>', mic_audio)))

    patched = replace_audio_section(video_xml, mic_audio)

    with open(output_path, "w") as f:
        f.write(patched)

    print(f"Gespeichert: {output_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--video",  required=True, help="XML der geschnittenen Video-Timeline")
    parser.add_argument("--audio",  required=True, help="XML der Sync-Timeline (mit MIC-Spuren)")
    parser.add_argument("--output", required=True, help="Ausgabe-XML")
    args = parser.parse_args()
    patch_xml_audio(args.video, args.audio, args.output)
