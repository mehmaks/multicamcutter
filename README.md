# resolve-toolkit

A collection of tools to automate and streamline video editing workflows in DaVinci Resolve.

Built for podcast and interview productions with multi-camera setups.

## Modules

### `multicam_cutter`
Automatically generates EDL (Edit Decision List) files for multi-camera podcast recordings.

- Detects speaker turns via RMS audio analysis
- Detects nodding reactions via computer vision (MediaPipe)
- Outputs a ready-to-import EDL for DaVinci Resolve

**[→ Module README](modules/multicam_cutter/README.md)**

## Planned Modules

- `resolve_bridge` — Direct DaVinci Resolve API integration
- `ui` — Streamlit-based control dashboard

## Requirements

See [requirements.txt](requirements.txt) for dependencies.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Production Setup

- Cameras: 4K (3840×2160) @ 25fps
- Audio: Separate WAV per speaker (Zoom recorder)
- NLE: DaVinci Resolve
