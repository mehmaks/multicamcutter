"""
Auphonic – Timeline-Audio-Extraktion.

Extrahiert Audio von einer gewählten Spur zwischen In/Out-Markern
der aktiven Resolve-Timeline als eine durchgehende WAV-Datei.
Gaps zwischen Clips werden als Stille gerendert.
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path

_log = logging.getLogger("rtk.auphonic")


def _probe_source_fps(path: str) -> float:
    """Returns the video stream's frame rate from ffprobe, or 0.0."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        for stream in json.loads(r.stdout).get("streams", []):
            if stream.get("codec_type") == "video":
                rfr = stream.get("r_frame_rate", "")
                if "/" in rfr:
                    num, den = rfr.split("/")
                    if int(den) > 0:
                        return int(num) / int(den)
    except Exception:
        pass
    return 0.0


def _probe_audio_sample_rate(path: str) -> int:
    """Returns sample rate of first audio stream, or 48000 as fallback."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        for stream in json.loads(r.stdout).get("streams", []):
            if stream.get("codec_type") == "audio":
                return int(stream.get("sample_rate", 48000))
    except Exception:
        pass
    return 48000


def extract_timeline_audio(
    timeline,
    media_pool,
    audio_track: int,
    output_dir: str,
    progress_cb=None,
) -> tuple[str, int, int]:
    """
    Extrahiert Audio von *audio_track* zwischen In/Out-Markern als WAV.

    Returns:
        (output_path, mark_in_frame, mark_out_frame)
    Raises:
        RuntimeError bei Fehlern.
    """

    def _log_progress(msg: str):
        _log.info(msg)
        if progress_cb:
            progress_cb(msg)

    # ── In/Out Marker lesen ──────────────────────────────────────────────────
    marks = timeline.GetMarkInOut()
    if not marks:
        raise RuntimeError("Keine In/Out-Marker auf der Timeline gesetzt.")

    mark_in = marks["video"]["in"]
    mark_out = marks["video"]["out"]
    if mark_in < 0 or mark_out < 0 or mark_out <= mark_in:
        raise RuntimeError(
            f"Ungültige In/Out-Marker: In={mark_in}, Out={mark_out}"
        )

    fps = float(timeline.GetSetting("timelineFrameRate"))
    tl_name = timeline.GetName()
    total_dur_s = (mark_out - mark_in) / fps

    _log_progress(
        f"Timeline: {tl_name} | In: {mark_in} Out: {mark_out} "
        f"({total_dur_s:.1f}s) | FPS: {fps} | Track: A{audio_track}"
    )

    # ── Clips auf der gewählten Spur sammeln ─────────────────────────────────
    all_clips = timeline.GetItemListInTrack("audio", audio_track) or []
    clips = []
    for c in sorted(all_clips, key=lambda x: x.GetStart()):
        tl_start = c.GetStart()
        tl_end = c.GetEnd()
        if tl_end <= mark_in or tl_start >= mark_out:
            continue

        eff_start = max(tl_start, mark_in)
        eff_end = min(tl_end, mark_out)

        # LeftOffset ist die tatsächliche Trim-Position, die Resolve
        # für die Wiedergabe nutzt. GetSourceStartFrame() weicht bei
        # einigen Clips um 1 Frame davon ab.
        left_off = c.GetLeftOffset()
        offset_in = eff_start - tl_start
        offset_out = eff_end - tl_start
        src_eff_start = left_off + offset_in
        src_eff_end = left_off + offset_out

        mp_item = c.GetMediaPoolItem()
        if not mp_item:
            continue
        path = mp_item.GetClipProperty("File Path")
        if not path:
            continue

        # Audio-Kanal aus Channel-Mapping
        ch_mapping = c.GetSourceAudioChannelMapping()
        audio_stream_idx = 0  # default: erster Audio-Stream
        if isinstance(ch_mapping, str):
            ch_mapping = json.loads(ch_mapping)
        if isinstance(ch_mapping, dict):
            track_map = ch_mapping.get("track_mapping", {})
            # Track "1" enthält channel_idx für diese Spur
            t1 = track_map.get("1") or track_map.get(str(audio_track))
            if t1 and "channel_idx" in t1:
                # Resolve channel_idx ist 1-basiert, ffmpeg -map ist 0-basiert
                audio_stream_idx = t1["channel_idx"][0] - 1

        clips.append({
            "name": c.GetName(),
            "path": path,
            "src_start": src_eff_start,
            "src_end": src_eff_end,
            "tl_start": eff_start,
            "tl_end": eff_end,
            "audio_stream_idx": audio_stream_idx,
        })

    if not clips:
        raise RuntimeError(
            f"Keine Clips auf A{audio_track} im In/Out-Bereich gefunden."
        )

    _log_progress(f"{len(clips)} Clips gefunden")

    # ── Sample Rate ermitteln ────────────────────────────────────────────────
    sample_rate = _probe_audio_sample_rate(clips[0]["path"])
    spf = sample_rate / fps  # samples per frame (48000/25 = 1920)
    total_samples = int((mark_out - mark_in) * spf)

    # ── Filtergraph: alle Clips in einem Durchlauf positionieren ─────────────
    # Jeder Clip wird per atrim sample-genau geschnitten und per adelay
    # an seine absolute Position im Output gelegt. amix kombiniert alles
    # ohne Normalisierung. Kein Concat → kein kumulativer Fehler.

    inputs = []
    filter_parts = []

    for i, clip in enumerate(clips):
        source_fps = _probe_source_fps(clip["path"]) or fps
        src_spf = sample_rate / source_fps

        n_frames = clip["src_end"] - clip["src_start"]
        start_sample = int(clip["src_start"] * src_spf)
        end_sample = start_sample + int(n_frames * src_spf)

        # Delay = Position dieses Clips im Output (in Samples ab Output-Start)
        delay_samples = int((clip["tl_start"] - mark_in) * spf)

        inputs += ["-i", clip["path"]]
        filter_parts.append(
            f"[{i}:a:{clip['audio_stream_idx']}]"
            f"atrim=start_sample={start_sample}:end_sample={end_sample},"
            f"asetpts=N/SR/TB,"
            f"adelay={delay_samples}S|{delay_samples}S"
            f"[a{i}]"
        )

        dur_s = n_frames / source_fps
        _log_progress(
            f"  {clip['name']}: {dur_s:.1f}s / {n_frames} fr "
            f"(Stream a:{clip['audio_stream_idx']}, "
            f"Samples {start_sample}–{end_sample}, "
            f"Delay {delay_samples}S)"
        )

    # amix ohne Normalisierung + auf exakte Gesamtlänge trimmen
    mix_inputs = "".join(f"[a{i}]" for i in range(len(clips)))
    filter_parts.append(
        f"{mix_inputs}amix=inputs={len(clips)}:duration=longest:normalize=0,"
        f"atrim=end_sample={total_samples},"
        f"asetpts=N/SR/TB[out]"
    )

    filter_complex = ";\n".join(filter_parts)

    out_name = f"{tl_name}_A{audio_track}_auphonic.wav"
    out_path = Path(output_dir) / out_name

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + [
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-acodec", "pcm_s24le",
            "-ar", str(sample_rate),
            "-ac", "1",
            str(out_path),
        ]
    )

    _log_progress("Rendere WAV …")
    r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg Render fehlgeschlagen:\n{r.stderr[-500:]}")

    _log_progress(f"WAV erstellt: {out_path} ({total_dur_s:.1f}s)")

    return str(out_path), mark_in, mark_out


def _find_bin_for_item(root_folder, target_mi):
    """Sucht den Media-Pool-Bin, in dem ein MediaPoolItem liegt."""
    target_path = target_mi.GetClipProperty("File Path")
    target_name = target_mi.GetName()
    for c in (root_folder.GetClipList() or []):
        if c.GetName() == target_name:
            if c.GetClipProperty("File Path") == target_path:
                return root_folder
    for sf in (root_folder.GetSubFolderList() or []):
        found = _find_bin_for_item(sf, target_mi)
        if found:
            return found
    return None


def import_and_place_on_track(
    timeline,
    media_pool,
    wav_path: str,
    mark_in: int,
    mark_out: int = 0,
    replace_track: int = 0,
    source_track: int = 0,
    progress_cb=None,
) -> int:
    """
    Importiert die WAV in den Media Pool und platziert sie auf einer
    Audiospur, synchron zum In-Marker.

    Args:
        replace_track: Wenn > 0, werden die Clips auf dieser Spur im
                       In/Out-Bereich gelöscht und die WAV dort platziert.
                       Wenn 0, wird eine neue Spur angelegt.
    Returns:
        Index der Audiospur, auf der die WAV platziert wurde.
    """

    def _log_progress(msg: str):
        _log.info(msg)
        if progress_cb:
            progress_cb(msg)

    # Quell-Bin finden: Bin des ersten Clips auf der Quellspur
    _target_bin = None
    if source_track > 0:
        _src_clips = timeline.GetItemListInTrack("audio", source_track) or []
        for _sc in _src_clips:
            _sc_mi = _sc.GetMediaPoolItem()
            if _sc_mi:
                _target_bin = _find_bin_for_item(
                    media_pool.GetRootFolder(), _sc_mi
                )
                break

    if _target_bin:
        media_pool.SetCurrentFolder(_target_bin)

    imported = media_pool.ImportMedia([wav_path])
    if not imported:
        raise RuntimeError(f"Import fehlgeschlagen: {wav_path}")
    mi = imported[0]
    _bin_name = _target_bin.GetName() if _target_bin else "aktueller Bin"
    _log_progress(f"Importiert: {Path(wav_path).name} → {_bin_name}")

    # Frame-Anzahl ermitteln (Audio-only Clips liefern "Frames" oft leer)
    frames_str = mi.GetClipProperty("Frames")
    if not frames_str:
        fps = float(timeline.GetSetting("timelineFrameRate"))
        dur_str = mi.GetClipProperty("Duration")
        if dur_str:
            import re
            m = re.match(r"(\d+):(\d+):(\d+):(\d+)", dur_str)
            if m:
                h, mn, s, f = (int(x) for x in m.groups())
                end_frame = int((h * 3600 + mn * 60 + s) * fps + f)
            else:
                end_frame = 0
        else:
            end_frame = 0
    else:
        end_frame = int(frames_str)

    # Zielspur bestimmen
    if replace_track > 0:
        target_track = replace_track
        # Originalclips im In/Out-Bereich auf der Spur löschen
        clips = timeline.GetItemListInTrack("audio", target_track) or []
        to_delete = [
            c for c in clips
            if c.GetEnd() > mark_in and c.GetStart() < mark_out
        ]
        if to_delete:
            ok = timeline.DeleteClips(to_delete)
            _log_progress(
                f"A{target_track}: {len(to_delete)} Originalclips entfernt"
                f" (DeleteClips → {ok})"
            )
        else:
            _log_progress(f"A{target_track}: keine Clips zum Löschen gefunden")
    else:
        track_count = timeline.GetTrackCount("audio")
        timeline.AddTrack("audio", "mono")
        target_track = track_count + 1

    # Clip platzieren, synchron zum In-Marker
    clip_info = {
        "mediaPoolItem": mi,
        "startFrame": 0,
        "endFrame": end_frame,
        "trackIndex": target_track,
        "mediaType": 2,  # audio
        "recordFrame": mark_in,
    }
    _log_progress(
        f"AppendToTimeline: track={target_track}, "
        f"recordFrame={mark_in}, endFrame={end_frame}"
    )
    result = media_pool.AppendToTimeline([clip_info])
    _log_progress(
        f"Platziert auf A{target_track} ab Frame {mark_in} "
        f"(AppendToTimeline → {result})"
    )

    return target_track
