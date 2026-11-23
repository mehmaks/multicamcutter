#!/usr/bin/env python3
"""Test: Mehrspur-Export als FCP7-XML (xmeml) mit deaktivierten Clips.

Jede Kamera bekommt eine eigene Videospur. An JEDEM Schnitt der finalen EDL wird auf
allen Spuren geschnitten; aktiv (enabled) ist nur der Clip der Kamera, die in diesem
Abschnitt im Schnitt ist. So kann der Cutter im NLE per Aktivieren/Deaktivieren
umentscheiden. AAF kann das nicht (kein „disabled"-Flag, siehe brain/TODOs.md).

Nur Video (Test der Deaktivierung). Quellbilder je Kamera: Videobild = tzvf + Timeline-
bild (dieselbe Abbildung wie die Engine, add_reactions_to_edl.calculate_reference_frames).

Aufruf: venv/bin/python3 analyse/xml_mehrspur_test.py FINAL.EDL OUT.xml VIDEO1 VIDEO2 … [--fps 29.97] [--max-min 10]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules/multicam_cutter"))
from add_reactions_to_edl import parse_resolve_edl, calculate_reference_frames  # noqa: E402
from add_reactions_to_edl import get_video_timecode_with_ffprobe  # noqa: E402


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,nb_frames,duration", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    s = json.loads(out)["streams"][0]
    return int(s["width"]), int(s["height"]), s.get("nb_frames"), float(s.get("duration", 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("edl")
    ap.add_argument("out")
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--fps", type=float, default=29.97)
    ap.add_argument("--max-min", type=float, default=0, help="nur die ersten N Minuten (0 = alles)")
    x = ap.parse_args()

    fps = x.fps
    nom = int(round(fps))
    ntsc = "TRUE" if abs(fps - nom) > 0.01 else "FALSE"
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        events = parse_resolve_edl(x.edl, fps)
        cams = [{"name": Path(v).name, "video": v} for v in x.videos]
        ref, tzvf = calculate_reference_frames(events, cams, fps)

    ende = max(e.record_out_frame for e in events)
    if x.max_min:
        ende = min(ende, int(x.max_min * 60 * fps))
    # Schnittpunkte und aktive Kamera je Abschnitt
    abschnitte = []
    for e in sorted(events, key=lambda e: e.record_in_frame):
        s, t = e.record_in_frame, min(e.record_out_frame, ende)
        if t > s:
            abschnitte.append((s, t, e.clip_name))

    info = {c["name"]: probe(c["video"]) for c in cams}
    rate = f"<rate><timebase>{nom}</timebase><ntsc>{ntsc}</ntsc></rate>"
    w0, h0 = info[cams[0]["name"]][:2]

    spuren = []
    zaehler = 0
    for ci, cam in enumerate(cams):
        name = cam["name"]
        w, h, nb, dur = info[name]
        file_dur = int(nb) if nb else int(dur * fps)
        url = "file://localhost" + quote(str(Path(cam["video"]).resolve()))
        file_id = f"file-{ci + 1}"
        # Start-Timecode der Datei: Resolve verknüpft XML-Clips über Dateiname + Timecode.
        # Fehlt er, nimmt Resolve 00:00:00:00 an und findet die Quellbilder nicht (Test 23.11.).
        tc = get_video_timecode_with_ffprobe(cam["video"]) or "00:00:00:00"
        df = "DF" if ";" in tc else "NDF"
        datei_voll = (f'<file id="{file_id}"><name>{escape(name)}</name><pathurl>{url}</pathurl>{rate}'
                      f'<duration>{file_dur}</duration>'
                      f'<timecode>{rate}<string>{tc}</string><frame>{ref.get(name, 0)}</frame>'
                      f'<displayformat>{df}</displayformat><reel><name>{escape(Path(name).stem)}</name></reel></timecode>'
                      f'<media><video><samplecharacteristics>{rate}'
                      f'<width>{w}</width><height>{h}</height></samplecharacteristics></video>'
                      f'<audio><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics>'
                      f'<channelcount>2</channelcount></audio></media></file>')
        items = []
        erste = True
        for s, t, aktiv in abschnitte:
            src_in = tzvf[name] + s
            src_out = tzvf[name] + t
            if src_in < 0 or src_out > file_dur:
                continue   # Kamera nimmt hier nicht auf → Lücke
            zaehler += 1
            items.append(
                f'<clipitem id="clip-{zaehler}"><name>{escape(name)}</name>'
                f'<enabled>{"TRUE" if aktiv == name else "FALSE"}</enabled>'
                f'<duration>{file_dur}</duration>{rate}<start>{s}</start><end>{t}</end>'
                f'<in>{src_in}</in><out>{src_out}</out>'
                + (datei_voll if erste else f'<file id="{file_id}"/>') + '</clipitem>')
            erste = False
        spuren.append("<track>" + "".join(items) + "</track>")
        aktiv_n = sum(1 for a in abschnitte if a[2] == name)
        print(f"  Spur V{ci + 1} {name}: {len(items)} Clips, davon {aktiv_n} aktiv")

    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
           f'<sequence id="sequence-1"><name>Mehrspur-Test</name><duration>{ende}</duration>{rate}'
           f'<timecode>{rate}<string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat></timecode>'
           f'<media><video><format><samplecharacteristics>{rate}<width>{w0}</width><height>{h0}</height>'
           f'</samplecharacteristics></format>' + "".join(spuren) + '</video></media></sequence></xmeml>\n')
    Path(x.out).write_text(xml, encoding="utf-8")
    print(f"{len(abschnitte)} Abschnitte, {ende / fps / 60:.1f} min → {x.out}")


if __name__ == "__main__":
    main()
