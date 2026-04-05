# multicam_cutter

Automated EDL generation for multi-camera podcast recordings.

## Workflow

1. **`rms_diarize_to_edl.py`** — Compares RMS audio levels of two WAV tracks to detect speaker turns
2. **`build_base_edl_from_audio.py`** — Converts diarization output to a base EDL with timecode
3. **`video_reaction_analyzer_v2.4.py`** — Detects nodding reactions via MediaPipe face landmarks
4. **`add_reactions_to_edl.py`** — Inserts reaction cutaways into the base EDL (multi-pass)
5. **`run_complete_workflow.py`** — Runs the full pipeline end-to-end

## Configuration

All parameters are in `config.ini`. Key settings:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `threshold_medium` | 100px | Nodding sensitivity (scaled from 720p) |
| `min_shot_duration` | 3.0s | Minimum time between cuts |
| `max_shot_duration` | 14.0s | Forces cutaway after this duration |
| `pre_roll_frames` | 15 | Frame offset to compensate detection latency |

## Usage

```bash
python run_complete_workflow.py \
  --cam1 /path/to/cam1.mp4 \
  --cam2 /path/to/cam2.mp4 \
  --mic1 /path/to/mic1.wav \
  --mic2 /path/to/mic2.wav
```

## Notes

- MIC numbering is **reversed** relative to CAM numbering (MIC1=CAM2, MIC2=CAM1)
- Timecode conversion logic is critical — do not modify without understanding the TC offset calculation
