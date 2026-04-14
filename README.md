# resolve-toolkit

A collection of tools to automate and streamline video editing workflows — for podcast, interview, and multi-camera productions.

## Modules

### `multicam_cutter`
Automatically generates a first-cut timeline from multi-camera recordings.

**How it works:**
1. **Waveform sync** — aligns all cameras and mics by audio fingerprint (no clapperboard needed)
2. **Speaker detection** — determines who is talking using RMS diarization of lavalier mic tracks
3. **Reaction detection** — finds nodding and short verbal reactions on the off-camera using MediaPipe face analysis
4. **Cut assembly** — builds a finished timeline with color-coded clips and reaction cutaways

**Supports:**
- N cameras (close + wide roles), M lavalier mics — flexible N:M mic-to-camera assignment
- Multi-person face tracking (up to 4 faces per camera)
- Wide-cam cutaways with automatic zoom (Premiere Pro-compatible via AAF Video Scale)
- Camera-level nodding analysis toggle (skip analysis for wide/overhead cameras)

**Two workflows:**

| | Bin Workflow | Folder Workflow |
|---|---|---|
| **Requires** | DaVinci Resolve running | FFmpeg + Python only |
| **Input** | Resolve Media Pool bin | Folder with media files |
| **Output** | Timeline directly in Resolve | `final.aaf` (Resolve, Premiere Pro, Avid) |
| **NLE** | Resolve | Any |

**[→ Full module documentation](modules/multicam_cutter/README.md)**

---

### `resolve_bridge`
Python bridge to the DaVinci Resolve scripting API.

- `connection.py` — connect to a running Resolve instance
- `timeline_reader.py` — read clip metadata, sync offsets, and track layout
- `markers.py` — read and write timeline markers
- `silence_cutter.py` — silence-based rough cut helper

---

### `ui`
Streamlit control dashboard. Launch with:

```bash
streamlit run ui/app.py
```

Then open [http://localhost:8501](http://localhost:8501).

**Pages:**
- **Multicam Cutter** — Bin and Folder workflows with live progress bar and log
- **Audio Enhance** — Auphonic / MaxxVolume integration
- **Silence Cutter** — rough cut based on silence detection
- **Take Selector** — multi-take selection helper
- **Config** — edit all analysis parameters with presets

**Sidebar:**
- Resolve connection status
- Live workflow log (last 30 lines)
- 💬 Feedback / bug report — submits a GitHub Issue directly, no account required

---

## Setup

```bash
pip install -r requirements.txt
```

> **Note on the Bin Workflow:** The Resolve scripting bridge requires the system Python (3.9) that ships with DaVinci Resolve. Do not run the Bin Workflow inside a venv — `fusionscript.so` must be importable from the system Python.

The Folder Workflow runs entirely in any Python 3.10+ environment.

---

## Requirements

- Python 3.10+
- FFmpeg (system-wide)
- DaVinci Resolve 18+ *(Bin Workflow only)*

See [requirements.txt](requirements.txt) for Python dependencies.

---

## Production reference setup

- Cameras: 4K UHD @ 25 fps (Sony, Canon, Blackmagic)
- Audio: Separate WAV per speaker via Zoom field recorder (lav mics)
- NLE: DaVinci Resolve 19 / Adobe Premiere Pro 2025
- Analysis: MediaPipe Face Landmarker, ffmpeg for frame decoding
