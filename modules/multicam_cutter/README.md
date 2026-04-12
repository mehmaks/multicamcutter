# multicam_cutter

Automated EDL generation for multi-camera podcast recordings, with speaker detection and reaction cutaway insertion.

## Workflow

Two entry points depending on how the project is set up in Resolve:

### Bin-Workflow (`run_from_bin.py`)
Fully automated: scans a Media Pool bin, syncs clips via waveform, runs analysis, builds the cut timeline.

```bash
python run_from_bin.py \
  --bin "30 - Ebra" \
  --output "Final Cut" \
  --fps 25.0 \
  --config config.ini \
  --mic-cam1 1 \
  --mic-cam2 0
```

### Timeline-Workflow (`run_from_resolve.py`)
Starts from a manually synced Sync-Timeline already open in Resolve.

```bash
python run_from_resolve.py \
  --output final_resolve.edl \
  --import-to-resolve
```

Both workflows are also accessible via the Streamlit UI (`ui/pages/multicam.py`).

## Pipeline steps

| Step | Script | Description |
|------|--------|-------------|
| 1 | `build_base_edl_from_audio.py` | RMS/Peak diarization → base EDL with speaker turns + speaking reactions |
| 2 | `video_reaction_analyzer_v2.4.py` | MediaPipe face landmark analysis → nodding/laughing/headshake JSON |
| 3 | `add_reactions_to_edl.py` | Inserts reaction cutaways into base EDL (multi-pass, cluster-based) |

## Configuration (`config.ini`)

### `[General]`
| Parameter | Default | Description |
|-----------|---------|-------------|
| `min_shot_duration` | 3.0s | Minimum duration before a cut is allowed |
| `max_shot_duration` | 14.0s | Forces a cutaway after this duration |
| `reaction_min_duration` | 1.8s | Minimum duration for a reaction cutaway |

### `[Detection]`
| Parameter | Default | Description |
|-----------|---------|-------------|
| `min_confidence` | 0.88 | Minimum face detection confidence for MediaPipe |
| `analysis_width` | 640 | Frame width for MediaPipe inference (ffmpeg decodes+scales to this before analysis). 0 = original resolution |
| `calibration_height` | 2160 | Reference height the nodding pixel thresholds were calibrated for. Thresholds auto-scale to actual video height |

### `[Nodding]`
| Parameter | Default | Description |
|-----------|---------|-------------|
| `threshold_low/medium/high` | 130/90/70px | Minimum nose Y-movement for a nod — calibrated for UHD (2160p), auto-scaled at runtime |
| `min_nod_duration` | 0.65s | Minimum duration of the nod arc |
| `cooldown_frames` | 35 | Frames to skip after a detected nod to prevent double-counting |

### `[SpeakingReaction]`
| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | true | Enable speaking-based cutaway detection |
| `mode` | rms | `rms` (default) or `peak` — measurement method per 50ms window |
| `rise_db` | 10.0 | dB rise above rolling baseline to trigger a speaking event |
| `min_duration` | 0.20s | Minimum burst duration |
| `attack_window` | 1.0s | Rolling baseline attack (rises quickly) |
| `release_window` | 20.0s | Rolling baseline release (falls slowly) |
| `warmup` | 3.0s | Seconds at start of segment used to seed the baseline |
| `min_confidence` | 0.90 | Minimum face detection confidence required for speaking cutaways |

### `[RMSDiarization]`
| Parameter | Default | Description |
|-----------|---------|-------------|
| `threshold_db` | 6.0 | dB difference between mics to determine who is speaking |
| `change_delay` | 0.3s | Delay before registering a speaker change |

### `[CutawayTiming]`
| Parameter | Default | Description |
|-----------|---------|-------------|
| `cluster_max_gap_frames` | 75 | Reaction events within this gap are merged into one cutaway |
| `pre_roll_frames` | 15 | Frame offset to compensate for detection latency |

## Notes

- MIC numbering is **reversed** relative to CAM: `--mic-cam1` selects the mic for Camera 1, which is typically the *other* speaker's mic
- Nodding thresholds are in absolute pixels **calibrated for UHD (2160p)**. At runtime they are automatically scaled by `actual_height / calibration_height` — no manual adjustment needed when switching between 4K and 1080p material
- Speaking detection uses a **per-segment asymmetric rolling baseline** (p75 warmup seed). Peak mode (`--speaking-mode peak`) is more sensitive to short transients like "Mhm"
- MediaPipe frames are delivered via an **ffmpeg pipe** (`scale=640:-2` by default), which is significantly faster than decoding via OpenCV for 4K material
