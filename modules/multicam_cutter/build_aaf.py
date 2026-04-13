#!/usr/bin/env python3
"""
Generiert eine AAF-Timeline aus final.edl + synchronisierten Mediendateien.

Ausgabe:
  V1   — Videoschnitte (CAM1 / CAM2), offline-verlinkt
  A1   — MIC1 kontinuierlich, synchronisiert
  A2   — MIC2 kontinuierlich, synchronisiert (wenn vorhanden)

Importierbar in Premiere Pro und Avid Media Composer.
Benötigt: pip install pyaaf2
"""

import json
import re
import subprocess
from pathlib import Path

import aaf2
import aaf2.rational


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


def _probe_embedded_tc_frames(path: str, fps: float) -> int:
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json',
         '-show_format', '-show_streams', str(path)],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return 0
    tc = data.get('format', {}).get('tags', {}).get('timecode')
    if not tc:
        for stream in data.get('streams', []):
            tc = stream.get('tags', {}).get('timecode')
            if tc:
                break
    if tc:
        try:
            h, m, s, f = (int(x) for x in tc.split(':'))
            return int((h * 3600 + m * 60 + s) * fps + f)
        except Exception:
            pass
    return 0


def _tc_to_frames(tc: str, fps: float) -> int:
    h, m, s, f = (int(x) for x in tc.split(':'))
    return int((h * 3600 + m * 60 + s) * fps + f)


# ── EDL parser ────────────────────────────────────────────────────────────────

def _parse_edl(edl_path: Path, cam_paths: list, fps: float) -> list:
    text = edl_path.read_text()
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
    for ev, cn in zip(event_re.finditer(text), clip_re.finditer(text)):
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
            continue

        result.append({'cam_index': cam_idx, 'source_in': src_in, 'source_out': src_out})

    return result


# ── Haupt-Generator ───────────────────────────────────────────────────────────

def build_aaf(
    cam_paths: list,
    mic_paths: list,
    offsets: dict,
    edl_path: Path,
    fps: float,
    output: Path,
) -> Path:
    """
    Erzeugt eine AAF-Timeline aus final.edl + synchronisierten Medien.

    V1:  Videoschnitte aus edl_path
    A1:  mic_paths[0] kontinuierlich, synchronisiert
    A2:  mic_paths[1] kontinuierlich, synchronisiert (wenn vorhanden)

    offsets: {'CAM1': 0, 'CAM2': N, 'MIC1': N, 'MIC2': N}
    """
    print("\nErstelle AAF...")

    events = _parse_edl(edl_path, cam_paths, fps)
    if not events:
        raise RuntimeError("Keine Cut-Events in EDL — AAF-Generierung abgebrochen")
    print(f"  {len(events)} Cut-Events")

    fps_int     = int(round(fps))
    edit_rate   = aaf2.rational.AAFRational(fps_int, 1)

    cam_durs    = [_probe_duration_frames(p, fps) for p in cam_paths[:2]]
    cam_offs    = [offsets.get('CAM1', 0), offsets.get('CAM2', 0)]

    mics        = mic_paths[:2]
    mic_durs    = [_probe_duration_frames(str(p), fps) for p in mics]
    mic_infos   = [_probe_audio_info(str(p))           for p in mics]
    mic_offsets = [offsets.get(f'MIC{i + 1}', 0)      for i in range(len(mics))]

    total_frames = sum(e['source_out'] - e['source_in'] for e in events)
    ev0          = events[0]
    abs_start0   = ev0['source_in'] + cam_offs[ev0['cam_index']]

    with aaf2.open(str(output), 'w') as f:

        # ── Video-SourceMobs + MasterMobs ─────────────────────────────────────
        cam_masters = []
        for idx, (cp, dur) in enumerate(zip(cam_paths[:2], cam_durs)):
            src = f.create.SourceMob()
            src.name = Path(cp).name
            _, slot = src.create_essence(edit_rate=fps_int, media_kind='picture', offline=True)
            slot.segment.length = dur
            desc = f.create.ImportDescriptor()
            loc  = f.create.NetworkLocator()
            loc['URLString'].value = Path(cp).resolve().as_uri()
            desc.locator.append(loc)
            src.descriptor = desc
            f.content.mobs.append(src)

            master = f.create.MasterMob()
            master.name = Path(cp).stem
            m_slot = master.create_picture_slot(edit_rate=fps_int)
            sc = f.create.SourceClip(media_kind='picture')
            sc.mob = src; sc.slot = slot; sc.start = 0; sc.length = dur
            m_slot.segment.components.append(sc)
            f.content.mobs.append(master)
            cam_masters.append((master, m_slot))

        # ── Audio-SourceMobs + MasterMobs ─────────────────────────────────────
        mic_masters = []
        for idx, (mp, dur, (channels, sr, bits)) in enumerate(
                zip(mics, mic_durs, mic_infos)):
            block_align = channels * (bits // 8)
            dur_samples = int(dur / fps * sr)

            src = f.create.SourceMob()
            src.name = Path(mp).name
            _, slot = src.create_essence(edit_rate=fps_int, media_kind='sound', offline=True)
            slot.segment.length = dur

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
            desc.locator.append(loc)
            src.descriptor = desc
            f.content.mobs.append(src)

            master = f.create.MasterMob()
            master.name = Path(mp).stem
            m_slot = master.create_sound_slot(edit_rate=fps_int)
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

        # V1 — Videoschnitte
        v_slot = comp.create_picture_slot(edit_rate=fps_int)
        v_slot['PhysicalTrackNumber'].value = 1
        v_slot.name = 'V1'

        for ev in events:
            cam_idx = ev['cam_index']
            src_in  = ev['source_in']
            dur     = ev['source_out'] - ev['source_in']
            master, m_slot = cam_masters[cam_idx]
            sc = master.create_source_clip(
                slot_id=m_slot.slot_id, start=src_in, length=dur)
            v_slot.segment.components.append(sc)

        # A1 / A2 — kontinuierliche MIC-Clips
        for i, (mic_data, mic_off, mic_dur) in enumerate(
                zip(mic_masters, mic_offsets, mic_durs)):
            master, m_slot = mic_data
            mic_start  = max(0, abs_start0 - mic_off)
            actual_dur = min(total_frames, max(0, mic_dur - mic_start))
            if actual_dur <= 0:
                continue

            a_slot = comp.create_sound_slot(edit_rate=fps_int)
            a_slot['PhysicalTrackNumber'].value = i + 1
            a_slot.name = f'A{i + 1}'

            sc = master.create_source_clip(
                slot_id=m_slot.slot_id, start=mic_start, length=actual_dur)
            a_slot.segment.components.append(sc)

            # Filler bis Timeline-Ende
            tail = total_frames - actual_dur
            if tail > 0:
                filler = f.create.Filler(media_kind='sound', length=tail)
                a_slot.segment.components.append(filler)

    print(f"  → {output.name}  ({len(events)} Cuts, {len(mic_masters)} MIC-Spur(en))")
    return output
