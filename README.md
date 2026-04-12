# resolve-toolkit

A collection of tools to automate and streamline video editing workflows in DaVinci Resolve.

Built for podcast and interview productions with multi-camera setups.

## Modules

### `multicam_cutter`
Automatically generates cut timelines for multi-camera podcast recordings.

- Detects speaker turns via RMS diarization of separate lav mic tracks
- Detects speaking reactions (short backchannel utterances) via rolling-baseline audio analysis
- Detects nodding reactions via computer vision (MediaPipe Face Landmarker)
- Outputs a finished cut timeline directly in DaVinci Resolve

Two workflows: **Bin-Workflow** (fully automated from a Media Pool bin) and **Timeline-Workflow** (starts from a manually synced timeline in Resolve).

**[→ Module README](modules/multicam_cutter/README.md)**

### `resolve_bridge`
Python bridge to the DaVinci Resolve scripting API.

- `connection.py` — connect to the running Resolve instance
- `timeline_reader.py` — read clip metadata, sync offsets, and track layout from the active timeline
- `markers.py` — read and write timeline markers
- `silence_cutter.py` — silence-based rough cut helper

### `ui`
Streamlit-based control dashboard. Start with:

```bash
cd ~/Developer/resolve-toolkit
python3 -m streamlit run ui/app.py
```

Then open http://localhost:8501. DaVinci Resolve must be running.

Pages:
- **Multicam Cutter** — Bin-Workflow and Timeline-Workflow with live log output
- **Silence Cutter** — Rough cut based on silence detection
- **Auphonic / MaxxVolume** — Audio processing helpers
- **Takes** — Take selector for multi-take recordings

## Requirements

See [requirements.txt](requirements.txt) for dependencies.

## Setup

```bash
pip3 install -r requirements.txt
```

> **Note:** Do not use a venv for the DaVinci Resolve bridge — `fusionscript.so` is compiled against the system Python (3.9) and must be importable from there.

## Production Setup

- Cameras: 4K UHD (3840×2160) @ 25fps
- Audio: Separate WAV per speaker (lav mics via Zoom recorder)
- NLE: DaVinci Resolve 19
- Analysis: MediaPipe Face Landmarker, ffmpeg for frame decode
