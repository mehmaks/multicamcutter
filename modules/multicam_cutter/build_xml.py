"""Mehrspur-Export als FCP7-XML (xmeml) für Premiere Pro und DaVinci Resolve.

Gegenstück zu build_aaf.py mit ANDEREM Layout (User 23.11.): jede Kamera bekommt eine
eigene Videospur, an JEDEM Schnitt wird auf allen Spuren geschnitten, aktiv
(`<enabled>TRUE`) ist nur die Kamera, die der Automatik-Schnitt dort zeigt. Der Cutter
kann so im NLE per Aktivieren/Deaktivieren umentscheiden. AAF kann das nicht (kein
„disabled"-Flag) — siehe apps/multicam-cutter/brain/TODOs.md.

Quelle sind dieselben Schnitt-Events wie für die AAF (inkl. Pausen-Trimming). Die
build_aaf.py-Struktur bleibt unangetastet; hier werden nur ihre Hilfsfunktionen genutzt.

Abbildung (dieselbe wie build_aaf für den Ton):
    Sync-Bild A = source_in + offsets[CAMk]      (CAM1-Bezug, siehe offsets-Vertrag)
    Quelle einer anderen Kamera j  = A - offsets[CAMj]
    Quelle eines Mikros i          = A - offsets[MICi]
Ton wird aus den Video-Events abgeleitet (zusammenhängende Sync-Bereiche = ein Clip),
nie unabhängig davon (Guardrail „Audio-Keeps NIE unabhängig von Video-Events").

Resolve verknüpft XML-Clips über Dateiname + Start-Timecode: jede `<file>` trägt deshalb
ihren eingebetteten TC (`<timecode>` + `<reel>`). Ohne findet Resolve die Medien nicht
(Test 23.11.). Gesplittete Rekorder-Aufnahmen werden wie in build_aaf in die
Originalteile aufgelöst.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

try:   # als Paket (Engine: modules.multicam_cutter.build_xml) oder direkt aus dem Ordner
    from .build_aaf import (_parse_edl, _probe_embedded_tc_frames, _probe_duration_frames,
                            _probe_video_info, _probe_audio_info, _split_parts, _detect_dropframe,
                            _is_dropframe, _edit_rate)
except ImportError:
    from build_aaf import (_parse_edl, _probe_embedded_tc_frames, _probe_duration_frames,
                           _probe_video_info, _probe_audio_info, _split_parts, _detect_dropframe,
                           _is_dropframe, _edit_rate)


def _tc_string(frames: int, fps_int: int, df: bool) -> str:
    """Frame-Zahl → TC-String (Drop-Frame mit ';', sonst ':')."""
    if df:
        drop = round(fps_int * 0.066666)                 # 2 bei 30, 4 bei 60
        f10 = fps_int * 600 - drop * 9
        f1 = fps_int * 60 - drop
        d, m = divmod(frames, f10)
        frames += drop * 9 * d + (drop * ((m - drop) // f1) if m > drop else 0)
    ff = frames % fps_int
    s = frames // fps_int
    return f"{s // 3600 % 24:02d}:{s // 60 % 60:02d}:{s % 60:02d}{';' if df else ':'}{ff:02d}"


def _url(path) -> str:
    return "file://localhost" + quote(str(Path(path).resolve()))


def build_xml(cam_paths: list, mic_paths: list, offsets: dict, edl_path: Path, fps: float,
              output: Path, cam_types: list = None, wide_zoom: float = 1.0,
              trimmed_events: list = None, cam_person_names: list = None,
              titel: str = None) -> Path:
    events = trimmed_events if trimmed_events is not None else _parse_edl(Path(edl_path), cam_paths, fps)
    if not events:
        raise RuntimeError("Keine Cut-Events — XML-Export abgebrochen")

    fps_int = int(round(fps))
    ntsc = "TRUE" if abs(fps - fps_int) > 0.01 else "FALSE"
    rate = f"<rate><timebase>{fps_int}</timebase><ntsc>{ntsc}</ntsc></rate>"
    df = None
    for cp in cam_paths:
        df = _detect_dropframe(cp)
        if df is not None:
            break
    if df is None:
        df = _is_dropframe(fps)

    cam_offs = [offsets.get(f"CAM{i + 1}", 0) for i in range(len(cam_paths))]
    mic_offs = [offsets.get(f"MIC{i + 1}", 0) for i in range(len(mic_paths))]
    cam_durs = [_probe_duration_frames(p, fps) for p in cam_paths]
    wide = {i for i, t in enumerate(cam_types or []) if t == "wide"}
    zoom = abs(wide_zoom - 1.0) > 0.001

    ids = {"n": 0}

    def neue_id(prefix):
        ids["n"] += 1
        return f"{prefix}-{ids['n']}"

    # ── <file>-Definitionen (je Datei einmal voll, danach nur Verweis) ──────────
    dateien = {}

    def datei(path, art):
        """(file_id, volle Definition beim ersten Mal sonst Verweis, Dauer in Bildern)."""
        key = str(path)
        if key in dateien:
            fid, dur = dateien[key]
            return fid, f'<file id="{fid}"/>', dur
        fid = f"file-{len(dateien) + 1}"
        dur = _probe_duration_frames(key, fps)
        tc = _probe_embedded_tc_frames(key, fps, dropframe=df)
        name = Path(key).name
        try:
            ch, sr, bits = _probe_audio_info(key)
        except Exception:
            ch, sr, bits = 2, 48000, 16
        ton = (f"<audio><samplecharacteristics><depth>{bits or 16}</depth><samplerate>{sr or 48000}"
               f"</samplerate></samplecharacteristics><channelcount>{ch or 1}</channelcount></audio>")
        bild = ""
        if art == "video":
            w, h = _probe_video_info(key)
            bild = (f"<video><samplecharacteristics>{rate}<width>{w}</width><height>{h}</height>"
                    f"</samplecharacteristics></video>")
        voll = (f'<file id="{fid}"><name>{escape(name)}</name><pathurl>{_url(key)}</pathurl>{rate}'
                f"<duration>{dur}</duration><timecode>{rate}<string>{_tc_string(tc, fps_int, df)}</string>"
                f"<frame>{tc}</frame><displayformat>{'DF' if df else 'NDF'}</displayformat>"
                f"<reel><name>{escape(Path(key).stem)}</name></reel></timecode>"
                f"<media>{bild}{ton}</media></file>")
        dateien[key] = (fid, dur)
        return fid, voll, dur

    def kamera_name(j):
        stem = Path(cam_paths[j]).stem
        person = ((cam_person_names or [None] * len(cam_paths))[j] or "").strip() \
            if cam_person_names and j < len(cam_person_names) else ""
        return f"{person} – {stem}" if person else stem

    zoom_filter = ("<filter><effect><name>Basic Motion</name><effectid>basic</effectid>"
                   "<effectcategory>motion</effectcategory><effecttype>motion</effecttype>"
                   "<mediatype>video</mediatype><parameter><parameterid>scale</parameterid>"
                   f"<name>Scale</name><valuemin>0</valuemin><valuemax>1000</valuemax>"
                   f"<value>{wide_zoom * 100:.1f}</value></parameter></effect></filter>")

    # ── Video: eine Spur je Kamera ───────────────────────────────────────────
    v_spuren = [[] for _ in cam_paths]
    laeufe = []          # zusammenhängende Sync-Bereiche für den Ton: [rec, A, länge]
    rec = 0
    for ev in events:
        c = ev["cam_index"]
        dur = ev["source_out"] - ev["source_in"]
        if dur <= 0:
            continue
        a = ev["source_in"] + cam_offs[c]
        for j, cp in enumerate(cam_paths):
            s = a - cam_offs[j]
            if s < 0 or s + dur > cam_durs[j]:
                continue          # Kamera nimmt hier nicht auf → Lücke auf ihrer Spur
            _, fdef, fdur = datei(cp, "video")
            v_spuren[j].append(
                f'<clipitem id="{neue_id("clip")}"><name>{escape(kamera_name(j))}</name>'
                f'<enabled>{"TRUE" if j == c else "FALSE"}</enabled><duration>{fdur}</duration>{rate}'
                f"<start>{rec}</start><end>{rec + dur}</end><in>{s}</in><out>{s + dur}</out>{fdef}"
                + (zoom_filter if zoom and j in wide else "") + "</clipitem>")
        if laeufe and laeufe[-1][0] + laeufe[-1][2] == rec and laeufe[-1][1] + laeufe[-1][2] == a:
            laeufe[-1][2] += dur
        else:
            laeufe.append([rec, a, dur])
        rec += dur
    gesamt = rec

    # ── Ton: eine Spur je Mikro, Clips je zusammenhängendem Bereich ──────────
    def teile(mp):
        """[(pfad, start_bild_in_gesamtspur, länge_bilder)] — Split-Teile oder die Datei."""
        parts = _split_parts(mp)
        if not parts:
            return [(str(mp), 0, None)]
        out = []
        er = float(_edit_rate(fps))             # exakte Rate wie build_aaf (29,97 → 30000/1001)
        for p in parts:
            start = round(p["start_sample"] / p["sample_rate"] * er)
            out.append((p["path"], start, int(p["n_samples"] / p["sample_rate"] * er)))
        return out

    a_spuren = []
    for i, mp in enumerate(mic_paths):
        tl = teile(mp)
        items = []
        for rec0, a, laenge in laeufe:
            pos, rest, r = a - mic_offs[i], laenge, rec0
            if pos < 0:                         # Mikro startet später als dieser Bereich
                rest += pos; r -= pos; pos = 0
            while rest > 0:
                k = max((n for n, t in enumerate(tl) if t[1] <= pos), default=0)
                pfad, t_start, t_len = tl[k]
                _, fdef, fdur = datei(pfad, "audio")
                lokal = pos - t_start
                verfuegbar = (t_len if t_len is not None else fdur) - lokal
                naechster = tl[k + 1][1] - pos if k + 1 < len(tl) else rest
                nimm = min(rest, naechster)
                clip = max(0, min(nimm, verfuegbar))
                if clip > 0:
                    items.append(
                        f'<clipitem id="{neue_id("audio")}"><name>{escape(Path(pfad).stem)}</name>'
                        f"<enabled>TRUE</enabled><duration>{fdur}</duration>{rate}"
                        f"<start>{r}</start><end>{r + clip}</end><in>{lokal}</in><out>{lokal + clip}</out>"
                        f"{fdef}<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex>"
                        f"</sourcetrack></clipitem>")
                if nimm <= 0:
                    break
                pos += nimm; r += nimm; rest -= nimm
        a_spuren.append("<track>" + "".join(items) + "</track>")

    w0, h0 = _probe_video_info(cam_paths[0])
    titel = titel or Path(output).stem
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
           f'<sequence id="sequence-1"><name>{escape(titel)}</name><duration>{gesamt}</duration>{rate}'
           f"<timecode>{rate}<string>{_tc_string(0, fps_int, df)}</string><frame>0</frame>"
           f"<displayformat>{'DF' if df else 'NDF'}</displayformat></timecode>"
           f"<media><video><format><samplecharacteristics>{rate}<width>{w0}</width><height>{h0}</height>"
           "</samplecharacteristics></format>"
           + "".join("<track>" + "".join(s) + "</track>" for s in v_spuren)
           + "</video><audio><format><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate>"
           "</samplecharacteristics></format>" + "".join(a_spuren)
           + "</audio></media></sequence></xmeml>\n")
    Path(output).write_text(xml, encoding="utf-8")
    print(f"  → {Path(output).name}  ({len(events)} Cuts, {len(cam_paths)} Videospuren, "
          f"{len(mic_paths)} Tonspur(en))")
    return Path(output)
