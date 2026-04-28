"""
Gemeinsame AAF-Bausteine für alle Timeline-Builder.

Konsolidiert die Mob-Erstellung aus:
- modules/multicam_cutter/build_aaf.py (Multicam)
- ui/pages/silence.py (Silence Cutter)
- ui/pages/takes.py (Take Selector)

Jeder Builder nutzt diese Funktionen für das Scaffolding und
implementiert nur noch die modulspezifische Composition-Logik.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import aaf2
import aaf2.rational

from shared.ffmpeg_utils import (
    probe_audio_channels,
    probe_audio_info,
    probe_duration,
    probe_embedded_tc_frames,
    probe_video_info,
)


# ── MediaInfo ────────────────────────────────────────────────────────────────

@dataclass
class MediaInfo:
    """Gesammelte Medien-Infos einer Quelldatei."""
    dur_s: float
    dur_vid: int          # Duration in Video-Frames
    dur_aud: int          # Duration in Audio-Samples
    width: int
    height: int
    aspect: Fraction
    channels: int
    sample_rate: int
    bit_depth: int
    tc_frames: int        # Embedded Start-Timecode in Frames
    uri: str              # file:///... URI


def probe_media(path: str, fps: float, audio_sr: int = 48000,
                full_audio_info: bool = False) -> MediaInfo:
    """Sammelt alle Medien-Infos in einem Aufruf.

    Args:
        path: Pfad zur Mediendatei
        fps: Timeline-Framerate
        audio_sr: Audio-Samplerate für dur_aud (Default 48kHz)
        full_audio_info: True → channels/sr/bits dynamisch per ffprobe
                         False → channels dynamisch, sr/bits aus Defaults
    """
    fps_int = int(round(fps))
    dur_s = probe_duration(path)
    dur_vid = int(round(dur_s * fps_int))
    dur_aud = int(round(dur_s * audio_sr))

    vinfo = probe_video_info(path)
    width = int(vinfo.get('width', 1920))
    height = int(vinfo.get('height', 1080))
    dar_str = vinfo.get('display_aspect_ratio', '16:9')
    try:
        dar_n, dar_d = dar_str.split(':')
        aspect = Fraction(int(dar_n), int(dar_d))
    except Exception:
        aspect = Fraction(width, height)

    if full_audio_info:
        channels, sample_rate, bit_depth = probe_audio_info(path)
    else:
        channels = probe_audio_channels(path)
        sample_rate = audio_sr
        bit_depth = 16

    tc_frames = probe_embedded_tc_frames(path, fps)
    uri = Path(path).resolve().as_uri()

    return MediaInfo(
        dur_s=dur_s, dur_vid=dur_vid, dur_aud=dur_aud,
        width=width, height=height, aspect=aspect,
        channels=channels, sample_rate=sample_rate, bit_depth=bit_depth,
        tc_frames=tc_frames, uri=uri,
    )


# ── Timecode-Slot ────────────────────────────────────────────────────────────

def make_timecode_slot(f, mob, fps_int: int, start: int, length: int):
    """Fügt einen Timecode-Slot zu einem Mob hinzu."""
    slot = mob.create_timeline_slot(edit_rate=fps_int)
    tc = f.create.from_name('Timecode')
    tc['Start'].value = start
    tc['FPS'].value = fps_int
    tc['Drop'].value = False
    tc['Length'].value = length
    slot.segment = tc
    return slot


# ── TapeMob ──────────────────────────────────────────────────────────────────

def make_tape_mob(f, media_kind: str, phys_track: int,
                  tc_frames: int, dur: int, fps_int: int,
                  name: str = ''):
    """Erstellt TapeMob mit TC-Slot + Media-Slot.

    Manuelles Layout (wie Silence/Takes):
    - Slot 1: Timecode
    - Slot 2: Media (picture oder sound)

    Returns: (tape_mob, media_slot)
    """
    tape = f.create.SourceMob()
    tape.name = name
    tape.descriptor = f.create.TapeDescriptor()

    tc_seg = f.create.Timecode()
    tc_seg['FPS'].value = fps_int
    tc_seg['Drop'].value = False
    tc_seg['Start'].value = tc_frames
    tc_seg['Length'].value = dur
    tc_slot = tape.create_timeline_slot(edit_rate=fps_int)
    tc_slot.segment = tc_seg
    tc_slot['PhysicalTrackNumber'].value = 1

    if media_kind == 'picture':
        ms = tape.create_picture_slot(edit_rate=fps_int)
    else:
        ms = tape.create_sound_slot(edit_rate=fps_int)
    ms['PhysicalTrackNumber'].value = phys_track
    end_sc = f.create.SourceClip(media_kind=media_kind, length=dur)
    ms.segment = end_sc  # mob=None → Ende der Kette

    return tape, ms


def make_tape_mob_via_api(f, name: str, media_kind: str,
                          dur: int, fps_int: int, tc_frames: int):
    """Erstellt TapeMob über die pyaaf2 create_tape_slots() API.

    Variante wie im Multicam-Builder — nutzt das eingebaute API.
    Returns: (tape_mob, media_slot, tc_slot)
    """
    tape = f.create.SourceMob()
    tape.name = name
    tape.descriptor = f.create.TapeDescriptor()
    media_slot, tc_slot = tape.create_tape_slots(
        name, edit_rate=fps_int, timecode_fps=fps_int,
        media_kind=media_kind, length=dur,
    )
    tc_slot.segment['Start'].value = tc_frames
    return tape, media_slot, tc_slot


# ── Video SourceMob ──────────────────────────────────────────────────────────

def make_video_source_mob_cdci(f, name: str, info: MediaInfo, fps_int: int,
                               tape, tape_slot):
    """CDCIDescriptor-Variante (Silence + Takes).

    Erstellt SourceMob mit Codec-Properties und Locator.
    Returns: (mob, picture_slot)
    """
    mob = f.create.SourceMob()
    mob.name = name

    cdci = f.create.CDCIDescriptor()
    cdci['StoredWidth'].value = info.width
    cdci['StoredHeight'].value = info.height
    cdci['ImageAspectRatio'].value = info.aspect
    cdci['FrameLayout'].value = 'FullFrame'
    cdci['HorizontalSubsampling'].value = 2
    cdci['ComponentWidth'].value = 8
    cdci['VideoLineMap'].value = [0, 1]
    cdci['SampleRate'].value = Fraction(fps_int, 1)
    cdci['Length'].value = info.dur_vid
    loc = f.create.NetworkLocator()
    loc['URLString'].value = info.uri
    cdci['Locator'].value = [loc]
    mob.descriptor = cdci

    slot = mob.create_picture_slot(edit_rate=fps_int)
    slot['PhysicalTrackNumber'].value = 1
    sc = f.create.SourceClip(media_kind='picture', length=info.dur_vid)
    sc.mob = tape
    sc.slot = tape_slot
    sc.start = 0
    slot.segment = sc

    return mob, slot


def make_video_file_mob(f, name: str, uri: str, dur: int, fps_int: int,
                        tape, tape_slot):
    """ImportDescriptor-Variante (Multicam — offline, kein Codec).

    Erstellt FileMob mit offline Marker und Locator.
    Returns: (mob, picture_slot)
    """
    mob = f.create.SourceMob()
    mob.name = name
    _, fm_slot = mob.create_essence(
        edit_rate=fps_int, media_kind='picture', offline=True)
    sc = f.create.SourceClip(media_kind='picture')
    sc.mob = tape
    sc.slot = tape_slot
    sc.start = 0
    sc.length = dur
    fm_slot.segment = sc

    desc = f.create.ImportDescriptor()
    loc = f.create.NetworkLocator()
    loc['URLString'].value = uri
    desc.locator.append(loc)
    mob.descriptor = desc

    return mob, fm_slot


# ── Audio SourceMob ──────────────────────────────────────────────────────────

def make_audio_source_mob(f, name: str, info: MediaInfo, fps_int: int,
                          tape_slots: list):
    """PCMDescriptor-SourceMob mit N Audio-Slots.

    Args:
        tape_slots: [(tape_mob, tape_media_slot, phys_track), ...]

    Returns: (mob, [audio_slots])
    """
    mob = f.create.SourceMob()
    mob.name = name

    block_align = info.channels * (info.bit_depth // 8)
    pcm = f.create.PCMDescriptor()
    pcm['AudioSamplingRate'].value = aaf2.rational.AAFRational(info.sample_rate, 1)
    pcm['SampleRate'].value = aaf2.rational.AAFRational(info.sample_rate, 1)
    pcm['Channels'].value = info.channels
    pcm['QuantizationBits'].value = info.bit_depth
    pcm['BlockAlign'].value = block_align
    pcm['AverageBPS'].value = info.sample_rate * block_align
    pcm['Length'].value = info.dur_aud
    loc = f.create.NetworkLocator()
    loc['URLString'].value = info.uri
    pcm['Locator'].value = [loc]
    mob.descriptor = pcm

    slots = []
    for tape, tape_media_slot, phys in tape_slots:
        slot = mob.create_sound_slot(edit_rate=fps_int)
        slot['PhysicalTrackNumber'].value = phys
        sc = f.create.SourceClip(media_kind='sound', length=info.dur_vid)
        sc.mob = tape
        sc.slot = tape_media_slot
        sc.start = 0
        slot.segment = sc
        slots.append(slot)

    return mob, slots


# ── MasterMob ────────────────────────────────────────────────────────────────

def make_master_mob(f, name: str,
                    video_mob, video_slot, dur_vid: int, fps_int: int,
                    audio_mob=None, audio_slots: list | None = None):
    """Erstellt MasterMob mit Video + optional N Audio-Slots.

    Returns: (master, v_slot, [a_slots])
    """
    master = f.create.MasterMob()
    master.name = name

    v_slot = master.create_picture_slot(edit_rate=fps_int)
    v_slot['PhysicalTrackNumber'].value = 1
    sc_v = f.create.SourceClip(media_kind='picture', length=dur_vid)
    sc_v.mob = video_mob
    sc_v.slot = video_slot
    sc_v.start = 0
    v_slot.segment = sc_v

    a_slots_out = []
    if audio_mob and audio_slots:
        for i, a_slot_src in enumerate(audio_slots):
            a_slot = master.create_sound_slot(edit_rate=fps_int)
            a_slot['PhysicalTrackNumber'].value = i + 1
            sc_a = f.create.SourceClip(media_kind='sound', length=dur_vid)
            sc_a.mob = audio_mob
            sc_a.slot = a_slot_src
            sc_a.start = 0
            a_slot.segment = sc_a
            a_slots_out.append(a_slot)

    return master, v_slot, a_slots_out


# ── CompositionMob ───────────────────────────────────────────────────────────

def make_composition(f, name: str, fps_int: int, total_frames: int,
                     start_tc: int = 0):
    """CompositionMob mit TC-Slot.

    Returns: comp
    """
    comp = f.create.CompositionMob(name)
    make_timecode_slot(f, comp, fps_int, start=start_tc, length=total_frames)
    return comp


# ── Convenience: Single-Source Mob-Kette ─────────────────────────────────────

def create_single_source_mobs(f, info: MediaInfo, fps_int: int,
                              n_audio_tracks: int = 2):
    """Erstellt die komplette Mob-Kette für eine einzelne Quelldatei.

    Dies ist das Muster von Silence/Takes: eine Datei mit Video + Audio.
    Erstellt TapeMobs, CDCIDescriptor-Video-SourceMob, PCM-Audio-SourceMob,
    und MasterMob.

    Args:
        f: aaf2 file handle
        info: MediaInfo der Quelldatei
        fps_int: Timeline-FPS (ganzzahlig)
        n_audio_tracks: Anzahl Audio-Spuren (Default 2 für Stereo)

    Returns: (master, v_slot, [a_slots])
        master: MasterMob
        v_slot: Video-Slot auf dem MasterMob
        a_slots: Liste von Audio-Slots auf dem MasterMob
    """
    name = Path(info.uri.replace('file://', '')).stem

    # TapeMobs
    tape_v, tape_v_slot = make_tape_mob(
        f, 'picture', 1, info.tc_frames, info.dur_vid, fps_int)
    f.content.mobs.append(tape_v)

    audio_tapes = []
    for i in range(n_audio_tracks):
        tape_a, tape_a_slot = make_tape_mob(
            f, 'sound', i + 1, info.tc_frames, info.dur_vid, fps_int)
        f.content.mobs.append(tape_a)
        audio_tapes.append((tape_a, tape_a_slot, i + 1))

    # Video SourceMob (CDCIDescriptor)
    mob_vid, vid_slot = make_video_source_mob_cdci(
        f, name, info, fps_int, tape_v, tape_v_slot)
    f.content.mobs.append(mob_vid)

    # Audio SourceMob (PCMDescriptor)
    mob_aud, aud_slots = make_audio_source_mob(
        f, name, info, fps_int, audio_tapes)
    f.content.mobs.append(mob_aud)

    # MasterMob
    master, m_v_slot, m_a_slots = make_master_mob(
        f, name, mob_vid, vid_slot, info.dur_vid, fps_int,
        mob_aud, aud_slots)
    f.content.mobs.append(master)

    return master, m_v_slot, m_a_slots
