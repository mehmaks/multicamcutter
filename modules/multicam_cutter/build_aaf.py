#!/usr/bin/env python3
"""
Generiert eine AAF-Timeline aus final.edl + synchronisierten Mediendateien.

Ausgabe:
  V1   — Videoschnitte (CAM1 / CAM2)
  A1   — MIC1 kontinuierlich, synchronisiert
  A2   — MIC2 kontinuierlich, synchronisiert (wenn vorhanden)

Mob-Kette (vollständig, für Resolve und Premiere):
  TapeMob (reel name + TC-Slot)
    → FileMob (offline, NetworkLocator)
      → MasterMob (Bin-Clip)
        → CompositionMob (Timeline mit TC-Slot für korrektes FPS-Erkennung)

Importierbar in DaVinci Resolve und Premiere Pro.
Benötigt: pip install pyaaf2
"""

import json
import re
import subprocess
from pathlib import Path

import aaf2
import aaf2.rational
from aaf2.auid import AUID

# ── Premiere "Video Scale" OperationGroup AUIDs ───────────────────────────────
# Reverse-engineered aus Premiere Pro AAF-Export.
_SCALE_OP_AUID = AUID("2e0a119d-e6f7-4bee-b5dc-6dd42988687e")
_SCALEX_AUID   = AUID("8d568129-847e-11d5-935a-50f857c10000")
_SCALEY_AUID   = AUID("8d56812a-847e-11d5-935a-50f857c10000")
_SCALE_DENOM   = 100_000_000   # Premiere speichert Skalierung ×10^8


# ── Framerate → AAF-Edit-Rate ─────────────────────────────────────────────────
# Krumme NTSC-Raten (29,97 …) MÜSSEN als exakter Bruch in Edit-Rate/SampleRate.
# Sonst stempelt das AAF eine ganzzahlige Timeline (30 statt 29,97) → die NLE
# macht Speed-Adaption → A/V-Drift + Standbild am Ende (am Realmaterial bestätigt,
# 15.08.). Ganzzahlige fps bleiben ein plain int → der getestete 25er/30er-Pfad
# ist byte-identisch. Timecode bleibt Non-Drop (nominale Ganzzahl-Rate), passend
# zur Non-Drop-Zählung in shared/frame_utils.
_NTSC_RATIONALS = {
    23.976: (24000, 1001),
    29.97:  (30000, 1001),
    59.94:  (60000, 1001),
}


def _edit_rate(fps: float):
    """Edit-Rate für AAF-Slots: int bei ganzzahliger fps (byte-identisch zum
    bisherigen fps_int), exakter AAFRational bei krummer NTSC-Rate. Unbekannte
    krumme Raten → 1/1000-Näherung."""
    for nominal, (num, den) in _NTSC_RATIONALS.items():
        if abs(fps - nominal) < 0.01:
            return aaf2.rational.AAFRational(num, den)
    rounded = int(round(fps))
    if abs(fps - rounded) < 0.001:
        return rounded
    return aaf2.rational.AAFRational(int(round(fps * 1000)), 1000)


def _is_dropframe(fps: float) -> bool:
    """29,97/59,94 sind per NTSC-Konvention **Drop-Frame** — der Standardfall für
    Kameramaterial dieser Raten (Broadcast-Erbe). 23,976 und Ganzzahl-Raten sind
    Non-Drop. Nur **Fallback**, wenn `_detect_dropframe` das Flag nicht auslesen kann.
    Ohne Drop-Frame-Reel-TC linkt Resolve DF-Medien um den akkumulierten Drop-Frame-
    Versatz falsch (pro Kamera unterschiedlich → Kameras desynchron)."""
    return any(abs(fps - r) < 0.01 for r in (29.97, 59.94))


def _detect_dropframe(video_path: str):
    """Liest das Drop-Frame-Flag AUS DER DATEI (nicht geraten) — dieselbe Quelle,
    die auch DaVinci Resolve anzeigt.

    Sony XDCAM/XAVC legt in der Top-Level-`meta`-Box eine `NonRealTimeMeta`-XML ab
    mit `<LtcChange frameCount="0" value="HHHHHHHH">`. `value` ist der SMPTE-12M-
    gepackte Start-TC als Hex; im **Frames-Byte** (höchstes Byte) ist **Bit 6 (0x40)
    das Drop-Frame-Flag** (Bit 7 = Color-Frame). Beispiel `0x60375823` → 23:58:37:20,
    DF=1.

    Rückgabe: True/False bei sicherem Fund, sonst **None** (Aufrufer nimmt dann die
    NTSC-Annahme `_is_dropframe`). Nur Metadaten gelesen — kein Decode, schnell auch
    bei 100-GB-Dateien. tmcd-Track-Kameras (kein Sony-Meta) → None → Fallback.
    """
    try:
        import struct
        with open(video_path, 'rb') as f:
            f.seek(0, 2); fs = f.tell(); f.seek(0)
            data = b''
            while f.tell() < fs:
                pos = f.tell()
                b = f.read(8)
                if len(b) < 8:
                    break
                size, typ = struct.unpack('>I4s', b)
                if size == 1:
                    size = struct.unpack('>Q', f.read(8))[0]
                if typ == b'meta':
                    f.seek(pos); data = f.read(min(size, 20000)); break
                if size < 8:
                    break
                f.seek(pos + size)
        m = re.search(rb'<LtcChange frameCount="0" value="([0-9A-Fa-f]+)"', data)
        if m:
            frames_byte = (int(m.group(1), 16) >> 24) & 0xFF
            return bool(frames_byte & 0x40)     # Bit 6 = Drop-Frame
    except Exception:
        pass
    return None


def _dropframe_count(tc: str, fps: float) -> int:
    """TC-String → Frame-Index in **Drop-Frame**-Zählung (für den Reel-TC bei
    DF-Material). Drop-Frame lässt pro Minute Frame-Nummern aus (2 bei 29,97,
    4 bei 59,94), außer in jeder 10. Minute — so bleibt der TC ~ Echtzeit."""
    parts = tc.replace(';', ':').split(':')
    h, m, s, f = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    nominal = int(round(fps))                       # 30 bzw. 60
    drop = 4 if nominal >= 59 else 2                # Frames/Minute
    total_min = 60 * h + m
    return (h * 3600 + m * 60 + s) * nominal + f - drop * (total_min - total_min // 10)


# ── ffprobe helpers ───────────────────────────────────────────────────────────

def _probe(path: str, *args) -> str:
    r = subprocess.run(
        ['ffprobe', '-v', 'error'] + list(args) + [str(path)],
        capture_output=True, text=True,
    )
    return r.stdout.strip()


def _probe_duration_frames(path: str, fps: float) -> int:
    out = _probe(path, '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1')
    try:
        return int(float(out) * fps)
    except (ValueError, ZeroDivisionError):
        return 0


def _probe_audio_info(path: str):
    """Gibt (channels, sample_rate, bit_depth) zurück."""
    out = _probe(path, '-select_streams', 'a:0',
                 '-show_entries', 'stream=channels,sample_rate,bits_per_sample',
                 '-of', 'default=noprint_wrappers=1')
    info = {}
    for line in out.splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            info[k] = v
    channels    = int(info.get('channels',    '1') or '1')
    sample_rate = int(info.get('sample_rate', '48000') or '48000')
    bit_depth   = int(info.get('bits_per_sample', '24') or '24') or 24
    return channels, sample_rate, bit_depth


def _probe_video_info(path: str):
    """Gibt (width, height) der Videospur zurueck. Fuer den CDCIDescriptor —
    Premiere linkt zwar ueber die URL, verlangt aber einen echten File-Descriptor
    mit Maßen (ein ImportDescriptor ohne Maße wird nicht als linkbare Datei
    erkannt → Offline, s. brain/AAF-Struktur.md). Fallback 1920x1080."""
    out = _probe(path, '-select_streams', 'v:0',
                 '-show_entries', 'stream=width,height',
                 '-of', 'default=noprint_wrappers=1')
    info = {}
    for line in out.splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            info[k] = v
    try:
        w = int(info.get('width') or 0) or 1920
        h = int(info.get('height') or 0) or 1080
    except ValueError:
        w, h = 1920, 1080
    return w, h


def _probe_embedded_tc_frames(path: str, fps: float, dropframe: bool = False) -> int:
    """
    Liest embedded TC aus Video- oder Audiodateien:
    - Video: timecode-Tag in format- oder stream-Tags
    - Audio: timecode-Tag (falls vorhanden) oder BWF BEXT time_reference (Samples ab Mitternacht)

    dropframe=True: TC-String → Frame-Index in Drop-Frame-Zählung (für den
    Reel-TC bei DF-Material). Der BWF-BEXT-Zweig ist schon Echtzeit-basiert
    (Samples ab Mitternacht) und damit ~Drop-Frame-äquivalent — unverändert.
    """
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json',
         '-show_format', '-show_streams', str(path)],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return 0

    fmt_tags    = data.get('format', {}).get('tags', {})
    stream_tags = {}
    sample_rate = None
    for stream in data.get('streams', []):
        if stream.get('codec_type') == 'audio' and sample_rate is None:
            try:
                sample_rate = int(stream.get('sample_rate', 0))
            except ValueError:
                pass
        t = stream.get('tags', {})
        if t:
            stream_tags = t

    # 1) Standard timecode-Tag (Video und manche Audio-Formate)
    tc = fmt_tags.get('timecode') or stream_tags.get('timecode')
    if tc:
        try:
            # DF-Material: Reel-TC in Drop-Frame-Zählung, sonst nominal/Non-Drop.
            # Nominal passt exakt zur EDL-Rechnung (get_reference_frame); für
            # Drop-Frame-Medien MUSS der Reel-TC aber DF sein, sonst linkt Resolve
            # um den akkumulierten DF-Versatz falsch (pro Kamera unterschiedlich →
            # Kameras desynchron). _tc_to_frames/_dropframe_count verkraften ':'
            # UND ';'-Notation.
            return _dropframe_count(tc, fps) if dropframe else _tc_to_frames(tc, fps)
        except Exception:
            pass

    # 2) BWF BEXT time_reference: Sample-Offset ab Mitternacht (in Datei-Samplerate)
    time_ref = fmt_tags.get('time_reference')
    if time_ref and sample_rate:
        try:
            return round(int(time_ref) / sample_rate * fps)
        except (ValueError, ZeroDivisionError):
            pass

    return 0


from frame_utils import timecode_to_frames as _tc_to_frames


# ── AAF helpers ───────────────────────────────────────────────────────────────

def _register_scale_op(f):
    """Registriert Premiere-kompatible 'Video Scale' OperationDef + ParameterDefs."""
    d = f.dictionary
    sx = f.create.ParameterDef(_SCALEX_AUID, 'ScaleX', 'Horizontal Scale', 'Rational')
    sy = f.create.ParameterDef(_SCALEY_AUID, 'ScaleY', 'Vertical Scale',   'Rational')
    d.register_def(sx)
    d.register_def(sy)
    op = f.create.OperationDef(_SCALE_OP_AUID, 'Video Scale', 'Premiere Video Scale')
    op.media_kind          = 'picture'
    op['IsTimeWarp'].value = False
    op.number_inputs       = 1
    op.parameters.append(sx)
    op.parameters.append(sy)
    d.register_def(op)


def _wrap_scale(f, clip, length: int, zoom: float):
    """Verpackt einen SourceClip in einen Premiere-kompatiblen Video-Scale OperationGroup."""
    op_group = f.create.OperationGroup(_SCALE_OP_AUID, length=length, media_kind='picture')
    op_group.segments.append(clip)
    val = aaf2.rational.AAFRational(int(round(zoom * _SCALE_DENOM)), _SCALE_DENOM)
    op_group.parameters.append(f.create.ConstantValue(_SCALEX_AUID, val))
    op_group.parameters.append(f.create.ConstantValue(_SCALEY_AUID, val))
    return op_group


def _make_timecode_slot(f, mob, edit_rate, fps: int, start: int, length: int,
                        drop: bool = False):
    """Fügt einen Timecode-Slot zu einem Mob hinzu (für korrekte FPS-Erkennung in Resolve).

    edit_rate: int (Ganzzahl-fps) oder AAFRational (krumme NTSC-Rate). `fps` ist die
    nominale Ganzzahl-Rate (round(fps)); `drop` = Drop-Frame-Flag (True bei 29,97/59,94-
    DF-Material). `start` muss zum Drop-Modus passen (Drop-Frame-Zählung, wenn drop=True)."""
    slot = mob.create_timeline_slot(edit_rate=edit_rate)
    tc   = f.create.from_name('Timecode')
    tc['Start'].value  = start
    tc['FPS'].value    = fps
    tc['Drop'].value   = drop
    tc['Length'].value = length
    slot.segment = tc
    return slot


# ── EDL parser ────────────────────────────────────────────────────────────────

def _load_cut_reasons(edl_path: Path, edl_text: str) -> list:
    """Liest <edl>.colors.json — die Schnittgruende, die add_reactions_to_edl
    index-parallel zu den EDL-Events schreibt.

    Bei Laengen-Mismatch lieber GAR KEINE Gruende als falsch zugeordnete:
    ein falsches Label im Schnitt ist schlimmer als kein Label.
    """
    path = Path(edl_path).with_suffix('.colors.json')
    if not path.exists():
        return []
    try:
        reasons = [e.get('reason') for e in json.loads(path.read_text(encoding='utf-8'))]
    except Exception as e:
        print(f"  ⚠️  {path.name} nicht lesbar ({e}) — Clips ohne Grund-Benennung")
        return []
    n_events = len(re.findall(r'^\d+\s+\S+\s+\S+\s+C\s+', edl_text, re.MULTILINE))
    if len(reasons) != n_events:
        print(f"  ⚠️  {path.name} passt nicht zur EDL ({len(reasons)} Gruende vs. "
              f"{n_events} Events) — Grund-Benennung deaktiviert")
        return []
    return reasons


def _parse_edl(edl_path: Path, cam_paths: list, fps: float) -> list:
    text = edl_path.read_text()
    # Nur fuer die Clip-Benennung im AAF. Bewusst als 'cut_reason' und NICHT als
    # 'reason': pause_trim_edl verzweigt auf 'reason' (:256, :363), das Setzen
    # wuerde also still den Schnitt aendern.
    reasons = _load_cut_reasons(edl_path, text)
    cam_tc    = [_probe_embedded_tc_frames(p, fps) for p in cam_paths]
    cam_stems = [Path(p).stem.lower() for p in cam_paths]
    cam_names = [Path(p).name.lower() for p in cam_paths]

    event_re = re.compile(
        r'^\d+\s+\S+\s+\S+\s+C\s+'
        r'(\d{2}:\d{2}:\d{2}:\d{2})\s+'
        r'(\d{2}:\d{2}:\d{2}:\d{2})\s+'
        r'(\d{2}:\d{2}:\d{2}:\d{2})\s+'
        r'(\d{2}:\d{2}:\d{2}:\d{2})',
        re.MULTILINE,
    )
    clip_re = re.compile(r'^\*\s*FROM CLIP NAME:\s*(.+)', re.MULTILINE)

    result = []
    skipped = 0
    for i, (ev, cn) in enumerate(zip(event_re.finditer(text), clip_re.finditer(text))):
        clip_name = cn.group(1).strip()
        clip_stem = Path(clip_name).stem.lower()
        clip_lo   = clip_name.lower()

        cam_idx = None
        for j, (stem, name) in enumerate(zip(cam_stems, cam_names)):
            if clip_lo == name or clip_stem == stem:
                cam_idx = j
                break
        if cam_idx is None:
            continue

        ref     = cam_tc[cam_idx]
        src_in  = _tc_to_frames(ev.group(1), fps) - ref
        src_out = _tc_to_frames(ev.group(2), fps) - ref
        if src_in < 0 or src_out <= src_in:
            rec_in  = ev.group(3)
            rec_out = ev.group(4)
            gap = _tc_to_frames(rec_out, fps) - _tc_to_frames(rec_in, fps)
            print(f"  ⚠️  ÜBERSPRUNGEN: '{clip_name}' Source-Frames {src_in}–{src_out} "
                  f"(Record {rec_in}–{rec_out}, {gap} Frames)")
            skipped += 1
            continue

        # Record-Positionen MITFUEHREN, nicht rekonstruieren. run_from_folder hat
        # sie frueher aus den Source-Dauern ab 0 nachgerechnet — die EDL beginnt
        # aber bei einem Offset (WAV-Vorlauf), wodurch alle Positionen konstant
        # verschoben waren und der Pause-Trim ins Leere lief.
        result.append({'cam_index': cam_idx, 'source_in': src_in, 'source_out': src_out,
                       'record_in':  _tc_to_frames(ev.group(3), fps),
                       'record_out': _tc_to_frames(ev.group(4), fps),
                       'cut_reason': reasons[i] if i < len(reasons) else None})

    if skipped:
        print(f"  ⚠️  {skipped} Events übersprungen — Audio/Video-Sync kann abweichen!")
    return result


# ── Haupt-Generator ───────────────────────────────────────────────────────────

def build_aaf(
    cam_paths: list,
    mic_paths: list,
    offsets: dict,
    edl_path: Path,
    fps: float,
    output: Path,
    cam_types: list = None,
    wide_zoom: float = 1.0,
    audio_keeps: list = None,
    trimmed_events: list = None,
    cam_person_names: list = None,
    clip_name_pattern: str = None,
) -> Path:
    """
    Erzeugt eine AAF-Timeline aus final.edl + synchronisierten Medien.

    V1:  Videoschnitte aus edl_path (Wide-Cam-Cutaways optional mit Zoom)
    A1:  mic_paths[0] kontinuierlich, synchronisiert
    A2:  mic_paths[1] kontinuierlich, synchronisiert (wenn vorhanden)

    offsets:   {'CAM1': 0, 'CAM2': N, ..., 'MIC1': N, 'MIC2': N, ...}
    cam_types: ['close', 'close', 'wide', ...] — Wide-Cams bekommen wide_zoom
    wide_zoom: Skalierungsfaktor für Wide-Cam-Cutaways (Default 1.0 = kein Zoom)
    """
    print("\nErstelle AAF...")

    if trimmed_events is not None:
        events = trimmed_events
        print(f"  {len(events)} Cut-Events (pause-trimmed)")
    else:
        events = _parse_edl(edl_path, cam_paths, fps)
    if not events:
        raise RuntimeError("Keine Cut-Events in EDL — AAF-Generierung abgebrochen")
    if trimmed_events is None:
        print(f"  {len(events)} Cut-Events")

    fps_int  = int(round(fps))               # nominale Ganzzahl-Rate (Non-Drop-TC)
    edit_rate = _edit_rate(fps)              # int (Ganzzahl) oder AAFRational (29,97 → 30000/1001)
    sample_rate_rat = (edit_rate if isinstance(edit_rate, aaf2.rational.AAFRational)
                       else aaf2.rational.AAFRational(fps_int, 1))
    # Drop-Frame AUS DER DATEI lesen (wie Resolve), nicht raten. Erste Kamera mit
    # sicherem Fund gewinnt; ohne Fund (kein Sony-Meta) → NTSC-Annahme als Fallback.
    dropframe = None
    for _cp in cam_paths:
        _det = _detect_dropframe(_cp)
        if _det is not None:
            dropframe = _det
            break
    if dropframe is None:
        dropframe = _is_dropframe(fps)
        print(f"  TC-Modus: {'Drop-Frame' if dropframe else 'Non-Drop'} (angenommen aus fps={fps})")
    else:
        print(f"  TC-Modus: {'Drop-Frame' if dropframe else 'Non-Drop'} (aus Datei-Metadaten gelesen)")

    # N Kameras — offsets-Keys: CAM1, CAM2, CAM3, ...
    cam_tc   = [_probe_embedded_tc_frames(p, fps, dropframe=dropframe) for p in cam_paths]
    cam_durs = [_probe_duration_frames(p, fps)     for p in cam_paths]
    cam_dims = [_probe_video_info(p)               for p in cam_paths]
    cam_offs = [offsets.get(f'CAM{i + 1}', 0)     for i in range(len(cam_paths))]

    # M Mikrofone — alle mic_paths
    mics        = mic_paths
    mic_durs    = [_probe_duration_frames(str(p), fps) for p in mics]
    mic_infos   = [_probe_audio_info(str(p))           for p in mics]
    mic_offsets = [offsets.get(f'MIC{i + 1}', 0)      for i in range(len(mics))]

    total_frames = sum(e['source_out'] - e['source_in'] for e in events)
    ev0          = events[0]
    abs_start0   = ev0['source_in'] + cam_offs[ev0['cam_index']]

    with aaf2.open(str(output), 'w') as f:

        # ── Video: TapeMob + FileMob + MasterMob (alle Kameras) ──────────────
        cam_masters = []
        cam_files   = []   # (file_mob, fm_slot) je Kamera — Basis fuer benannte Mobs
        for idx, (cp, dur, tc, (vid_w, vid_h)) in enumerate(
                zip(cam_paths, cam_durs, cam_tc, cam_dims)):
            stem = Path(cp).stem

            # TapeMob — Reel-Name + embedded TC (damit Resolve die Datei zuordnen kann)
            tape = f.create.SourceMob()
            tape.name = stem
            tape.descriptor = f.create.TapeDescriptor()
            tape_media_slot, tape_tc_slot = tape.create_tape_slots(
                stem, edit_rate=edit_rate, timecode_fps=fps_int, drop_frame=dropframe,
                media_kind='picture', length=dur,
            )
            tape_tc_slot.segment['Start'].value = tc   # embedded TC als TC-Start
            f.content.mobs.append(tape)

            # FileMob — offline, verweist auf TapeMob für TC-Kontext
            file_mob = f.create.SourceMob()
            file_mob.name = Path(cp).name
            _, fm_slot = file_mob.create_essence(
                edit_rate=edit_rate, media_kind='picture', offline=True)
            sc_tape = f.create.SourceClip(media_kind='picture')
            sc_tape.mob   = tape
            sc_tape.slot  = tape_media_slot
            sc_tape.start  = 0   # TapeMob[0] = embedded TC; kein doppelter Offset
            sc_tape.length = dur
            fm_slot.segment = sc_tape

            # CDCIDescriptor (NICHT ImportDescriptor!): Premiere linkt Video nur
            # ueber einen echten File-Descriptor mit Maßen. Mit ImportDescriptor
            # blieb das Video offline (Audio/PCMDescriptor linkte schon) — bestaetigt
            # 25.07. Siehe brain/AAF-Struktur.md.
            from math import gcd as _gcd
            _g = _gcd(vid_w, vid_h) or 1
            desc = f.create.CDCIDescriptor()
            desc['StoredWidth'].value  = vid_w
            desc['StoredHeight'].value = vid_h
            desc['ImageAspectRatio'].value = aaf2.rational.AAFRational(vid_w // _g, vid_h // _g)
            desc['FrameLayout'].value = 'FullFrame'
            desc['HorizontalSubsampling'].value = 2
            desc['ComponentWidth'].value = 8
            desc['VideoLineMap'].value = [0, 1]
            desc['SampleRate'].value = sample_rate_rat
            desc['Length'].value = dur
            loc  = f.create.NetworkLocator()
            loc['URLString'].value = Path(cp).resolve().as_uri()
            # NICHT desc.locator.append(loc): pyaaf2 gibt eine List-KOPIE zurueck,
            # der Locator wird NICHT gespeichert (Video + Audio, s. AAF-Struktur.md).
            desc['Locator'].value = [loc]
            file_mob.descriptor = desc
            f.content.mobs.append(file_mob)

            # MasterMob — Bin-Clip
            master = f.create.MasterMob()
            master.name = stem
            m_slot = master.create_picture_slot(edit_rate=edit_rate)
            sc_file = f.create.SourceClip(media_kind='picture')
            sc_file.mob    = file_mob
            sc_file.slot   = fm_slot
            sc_file.start  = 0
            sc_file.length = dur
            m_slot.segment.components.append(sc_file)
            f.content.mobs.append(master)

            cam_masters.append((master, m_slot))
            cam_files.append((file_mob, fm_slot))

        # ── Audio: TapeMob + SourceMob + MasterMob ───────────────────────────
        mic_tc      = [_probe_embedded_tc_frames(str(p), fps, dropframe=dropframe) for p in mics]
        mic_masters = []
        for idx, (mp, dur, tc, (channels, sr, bits)) in enumerate(
                zip(mics, mic_durs, mic_tc, mic_infos)):
            block_align = channels * (bits // 8)
            dur_samples = int(dur / fps * sr)
            stem = Path(mp).stem

            # TapeMob — Reel-Name + embedded TC (BWF time_reference oder timecode-Tag)
            tape_a = f.create.SourceMob()
            tape_a.name = stem
            tape_a.descriptor = f.create.TapeDescriptor()
            tape_media_slot_a, tape_tc_slot_a = tape_a.create_tape_slots(
                stem, edit_rate=edit_rate, timecode_fps=fps_int, drop_frame=dropframe,
                media_kind='sound', length=dur,
            )
            tape_tc_slot_a.segment['Start'].value = tc   # embedded TC (z.B. 14:14:59:00)
            f.content.mobs.append(tape_a)

            # SourceMob — offline, verweist auf TapeMob für TC-Kontext
            src = f.create.SourceMob()
            src.name = stem
            _, slot = src.create_essence(edit_rate=edit_rate, media_kind='sound', offline=True)
            sc_tape_a = f.create.SourceClip(media_kind='sound')
            sc_tape_a.mob   = tape_a
            sc_tape_a.slot  = tape_media_slot_a
            sc_tape_a.start  = 0   # TapeMob[0] = embedded TC; kein doppelter Offset
            sc_tape_a.length = dur
            slot.segment = sc_tape_a

            desc = f.create.PCMDescriptor()
            desc['AudioSamplingRate'].value = aaf2.rational.AAFRational(sr, 1)
            desc['SampleRate'].value        = aaf2.rational.AAFRational(sr, 1)
            desc['Channels'].value          = channels
            desc['QuantizationBits'].value  = bits
            desc['BlockAlign'].value        = block_align
            desc['AverageBPS'].value        = sr * block_align
            desc['Length'].value            = dur_samples
            loc = f.create.NetworkLocator()
            loc['URLString'].value = Path(mp).resolve().as_uri()
            desc['Locator'].value = [loc]   # NICHT .append (s. Video-Kommentar)
            src.descriptor = desc
            f.content.mobs.append(src)

            # MasterMob
            master = f.create.MasterMob()
            master.name = stem
            m_slot = master.create_sound_slot(edit_rate=edit_rate)
            sc = f.create.SourceClip(media_kind='sound')
            sc.mob = src; sc.slot = slot; sc.start = 0; sc.length = dur
            m_slot.segment.components.append(sc)
            f.content.mobs.append(master)
            mic_masters.append((master, m_slot))

        # ── CompositionMob (Timeline) ──────────────────────────────────────────
        comp = f.create.CompositionMob()
        comp.name = output.stem
        comp.usage = 'Usage_TopLevel'
        f.content.mobs.append(comp)

        # Metadaten
        from datetime import datetime as _dt
        comp.comments["_AUTHOR"] = "Multicam Cutter"
        comp.comments["_DESCRIPTION"] = f"Automatischer Multicam-Schnitt — {len(events)} Cuts"
        comp.comments["_CREATION_DATE"] = _dt.now().isoformat(timespec="seconds")
        comp.comments["_APP_VERSION"] = "0.1.0"

        # TC-Slot — gibt Resolve die korrekte FPS der Timeline
        _make_timecode_slot(f, comp, edit_rate=edit_rate, fps=fps_int,
                            start=0, length=total_frames, drop=dropframe)

        # V1 — Videoschnitte (ggf. Wide-Cam-Cutaways mit Zoom)
        # Zoom nur, wenn explizit ein Faktor != 1.0 gewuenscht ist. Default ist 1.0
        # (= aus): Die Cams sind sauber eingerichtet, und ob eine Totale herangeholt
        # wird, entscheidet der Editor im Feinschnitt — das gehoert nicht vorgegeben.
        wide_indices = {i for i, t in enumerate(cam_types or []) if t == 'wide'}
        has_zoom     = bool(wide_indices) and abs(wide_zoom - 1.0) > 0.001
        if has_zoom:
            _register_scale_op(f)

        # Benannte MasterMobs pro (Kamera, Schnittgrund) — ersetzt die Clip-Farben
        # aus dem Resolve-Workflow, die es im AAF nicht gibt. Bewusst NICHT eine
        # Mob pro Schnitt: das waeren hunderte Bin-Clips. So bleiben es ~10, und
        # das Timeline-Segment zeigt den Grund trotzdem an (Segmentname = Mob-Name).
        _REASON_LABEL = {
            'speaker':                    'Sprecher',
            'reaction_nodding':           'Nicken',
            'reaction_speaking_reaction': 'Sprachreaktion',
            'pause_cutaway':              'Stille',
            'max_time':                   'Max-Zeit',
            'transition':                 'Übergang',
        }
        reason_masters = {}

        def _label(cam_idx: int, reason: str) -> str:
            """Bei 'speaker' die sprechende Person statt des generischen Wortes:
            'Sprecher' steht sonst auf jedem zweiten Clip und sagt nichts, was der
            Schnitt nicht schon zeigt. Bei Cutaways bleibt der Grund stehen — dort
            IST er die Information.

            Die Wide-Varianten (`reaction_*_wide`) entstehen NUR, wenn mehrere
            Personen gleichzeitig reagiert haben (`add_reactions_to_edl.py:266`).
            Der Clipname soll sagen, WESWEGEN umgeschnitten wurde — nicht, wer
            alles im Bild ist. Deshalb Suffix statt Namensliste.
            """
            if reason == 'speaker' and cam_person_names:
                if cam_idx < len(cam_person_names):
                    person = (cam_person_names[cam_idx] or '').strip()
                    if person:
                        return person
            if reason.endswith('_wide'):
                base = reason[:-len('_wide')]
                return f"{_REASON_LABEL.get(base, base)} (mehrere)"
            return _REASON_LABEL.get(reason, reason)

        # ── Clipname aus Wildcard-Muster (User-Feature 0.6.7) ──
        # Tokens: %S Quellname · %R Grund-Wort · %P Person auf der Cam ·
        # %L „smartes" Label (Person bei Sprecher, sonst Grund — wie bisher).
        # Ist kein Muster gesetzt (CLI ohne Flag), bleibt das ALTE Verhalten
        # („%S - %L") byte-genau erhalten — die App reicht ihren Default „%L - %S".
        def _reason_word(reason: str) -> str:
            """%R: reines Grund-Wort, OHNE Person-Ersetzung (anders als _label)."""
            if reason and reason.endswith('_wide'):
                base = reason[:-len('_wide')]
                return f"{_REASON_LABEL.get(base, base)} (mehrere)"
            return _REASON_LABEL.get(reason, reason or '')

        def _person_of(cam_idx: int) -> str:
            if cam_person_names and cam_idx < len(cam_person_names):
                return (cam_person_names[cam_idx] or '').strip()
            return ''

        _SEP = r'[-–—·|/•:]'

        def _tidy(s: str) -> str:
            """Raeumt Artefakte leerer Tokens weg: baumelnde/doppelte Trenner,
            Mehrfach-Leerzeichen. `%R - %P` mit leerer Person → `%R`."""
            s = re.sub(r'\s+', ' ', s)
            s = re.sub(rf'({_SEP})\s*(?:{_SEP}\s*)+', r'\1 ', s)  # doppelte Trenner
            s = re.sub(rf'^\s*{_SEP}\s*', '', s)                  # Trenner vorn
            s = re.sub(rf'\s*{_SEP}\s*$', '', s)                  # Trenner hinten
            return s.strip()

        _TOKEN_RE = re.compile(r'%([SRPL])')

        def _name_for(cam_idx: int, reason) -> str:
            src = Path(cam_paths[cam_idx]).stem
            if not clip_name_pattern:
                return f"{src} - {_label(cam_idx, reason)}"   # wie bisher
            values = {'S': src, 'R': _reason_word(reason),
                      'P': _person_of(cam_idx), 'L': _label(cam_idx, reason)}
            name = _tidy(_TOKEN_RE.sub(lambda m: values[m.group(1)], clip_name_pattern))
            return name or src                                # nie leer

        def _master_for(cam_idx: int, reason):
            """MasterMob fuer Kamera+Grund, bei Bedarf angelegt.

            OHNE `clip_name_pattern` (Toggle „Schnittgruende in Clipnamen" aus):
            immer der EINE Basis-MasterMob je Kamera. Das ist die Premiere-sichere
            Struktur — mehrere MasterMobs pro Kamera legt Premiere je als eigenes
            (Offline-)Medium an (bestaetigt 25.07.). Nur mit Muster (Resolve-Modus)
            entstehen die grund-benannten MasterMobs."""
            if not reason or not clip_name_pattern:
                return cam_masters[cam_idx]
            key = (cam_idx, reason)
            if key not in reason_masters:
                file_mob, fm_slot = cam_files[cam_idx]
                m = f.create.MasterMob()
                m.name = _name_for(cam_idx, reason)
                sl = m.create_picture_slot(edit_rate=edit_rate)
                sc_f = f.create.SourceClip(media_kind='picture')
                sc_f.mob    = file_mob
                sc_f.slot   = fm_slot
                sc_f.start  = 0
                sc_f.length = cam_durs[cam_idx]
                sl.segment.components.append(sc_f)
                f.content.mobs.append(m)
                reason_masters[key] = (m, sl)
            return reason_masters[key]

        v_seq = f.create.Sequence(media_kind='picture')
        for ev in events:
            cam_idx = ev['cam_index']
            src_in  = ev['source_in']
            dur     = ev['source_out'] - ev['source_in']
            master, m_slot = _master_for(cam_idx, ev.get('cut_reason'))
            sc = master.create_source_clip(
                slot_id=m_slot.slot_id, start=src_in, length=dur)
            if has_zoom and cam_idx in wide_indices:
                sc = _wrap_scale(f, sc, dur, wide_zoom)
            v_seq.components.append(sc)

        v_slot = comp.create_timeline_slot(edit_rate=edit_rate)
        v_slot['PhysicalTrackNumber'].value = 1
        v_slot.name = 'V1'
        if has_zoom:
            # NestedScope erforderlich für Premiere-Zoom-Kompatibilität
            nested = f.create.NestedScope(media_kind='picture', length=total_frames)
            nested['Slots'].append(v_seq)
            v_slot.segment = nested
        else:
            v_slot.segment = v_seq

        # A1 / A2 — MIC-Clips (segmentiert bei Pause-Trim, sonst kontinuierlich)
        for i, (mic_data, mic_off, mic_dur) in enumerate(
                zip(mic_masters, mic_offsets, mic_durs)):
            master, m_slot = mic_data
            mic_start  = max(0, abs_start0 - mic_off)

            a_slot = comp.create_sound_slot(edit_rate=edit_rate)
            a_slot['PhysicalTrackNumber'].value = i + 1
            a_slot.name = f'A{i + 1}'

            if audio_keeps:
                # Segmentierte Platzierung: Keep-Regionen mit Fillern dazwischen
                first_orig = audio_keeps[0][0]
                cursor = 0
                for orig_s, orig_e, rec_frame in audio_keeps:
                    # Filler vor dem Segment (Luecke durch Pause-Trim)
                    if rec_frame > cursor:
                        gap = rec_frame - cursor
                        filler = f.create.Filler(media_kind='sound', length=gap)
                        a_slot.segment.components.append(filler)
                        cursor += gap
                    seg_src_start = mic_start + (orig_s - first_orig)
                    seg_dur = orig_e - orig_s
                    if seg_src_start < 0:
                        seg_dur += seg_src_start
                        seg_src_start = 0
                    if seg_dur > 0:
                        sc = master.create_source_clip(
                            slot_id=m_slot.slot_id, start=seg_src_start, length=seg_dur)
                        a_slot.segment.components.append(sc)
                        cursor += seg_dur
            else:
                actual_dur = min(total_frames, max(0, mic_dur - mic_start))
                if actual_dur <= 0:
                    continue
                sc = master.create_source_clip(
                    slot_id=m_slot.slot_id, start=mic_start, length=actual_dur)
                a_slot.segment.components.append(sc)

                tail = total_frames - actual_dur
                if tail > 0:
                    filler = f.create.Filler(media_kind='sound', length=tail)
                    a_slot.segment.components.append(filler)

    print(f"  → {output.name}  ({len(events)} Cuts, {len(mic_masters)} MIC-Spur(en))")
    return output
