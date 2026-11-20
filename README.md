# MultiCamCutter

**Automatischer Multicam-Schnitt für Podcasts und Interviews auf dem Mac.**
MultiCamCutter hört, wer gerade spricht, schneidet auf die passende Kamera und setzt
Zwischenschnitte auf die zuhörende Person – bei Kopfnicken, kurzen Einwürfen wie „mhm“
oder in Pausen. Das Ergebnis ist eine AAF-Timeline für Premiere Pro oder DaVinci Resolve.
Alles läuft lokal auf dem Mac, nichts wird hochgeladen.

Download und mehr: <https://multicamcutter.pantake.com>

*English: MultiCamCutter automatically cuts multi-camera podcasts and interviews on the Mac.
It detects who is speaking, cuts to the matching camera and adds cutaways to the listener
(head nods, short interjections, pauses). Output is an AAF timeline for Premiere Pro or
DaVinci Resolve. Everything runs locally. Contributions in English are welcome.*

## Aufbau

| Ordner | Inhalt |
|---|---|
| `apps/multicam-cutter/MulticamCutter/` | Mac-App (SwiftUI, Swift Package) |
| `apps/multicam-cutter/engine/` | Engine-Einstieg (Python), spricht mit der App über JSON-Zeilen auf stdout |
| `modules/multicam_cutter/` | Schnittlogik: Sprechererkennung, Analysespur, Reaktionen, Pausen, AAF-Export |
| `apps/multicam-cutter/brain/` | Entwickler-Notizen (Deutsch): Architektur, Pipeline, Entscheidungen, bekannte Fehler |
| `apps/multicam-cutter/scripts/` | Build, Signieren, Release |
| `analyse/` | Werkzeuge zum Auswerten und Sichten von Erkennungen |
| `sequencer/`, `ui/`, `resolve_bridge/` | Ältere bzw. pausierte Teile (Weboberfläche, Resolve-Anbindung) |

Einstieg ins Verständnis: `apps/multicam-cutter/brain/Pipeline-Schritte.md` und
`apps/multicam-cutter/brain/Architektur.md`.

## Entwickeln

Voraussetzungen: macOS 14+, Apple Silicon, Xcode-Kommandozeilenwerkzeuge, Python 3.12,
`ffmpeg`/`ffprobe` (z. B. über Homebrew).

```bash
# Python-Umgebung für die Engine
python3.12 -m venv venv
venv/bin/pip install -r apps/multicam-cutter/engine/requirements.txt

# App bauen
cd apps/multicam-cutter/MulticamCutter
swift build
```

Aus dem Quellcode gestartet, nutzt die App die Engine im `venv` dieses Repos. Ein
vollständiges `.app`-Bundle (mit eingefrorener Engine) baut
`apps/multicam-cutter/scripts/build_app.sh`.

## Das übrige Toolkit (resolve-toolkit)

Das Repo ist ursprünglich als Sammlung von Schnitt-Werkzeugen rund um DaVinci Resolve
entstanden. Diese Teile gibt es weiterhin; die Beschreibung von damals (Englisch):

A collection of tools to automate and streamline video editing workflows — for podcast, interview, and multi-camera productions.

### Modules

#### `multicam_cutter`
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

#### `resolve_bridge`
Python bridge to the DaVinci Resolve scripting API.

- `connection.py` — connect to a running Resolve instance
- `timeline_reader.py` — read clip metadata, sync offsets, and track layout
- `markers.py` — read and write timeline markers
- `silence_cutter.py` — silence-based rough cut helper

---

#### `ui`
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

### Setup

```bash
pip install -r requirements.txt
```

> **Note on the Bin Workflow:** The Resolve scripting bridge requires the system Python (3.9) that ships with DaVinci Resolve. Do not run the Bin Workflow inside a venv — `fusionscript.so` must be importable from the system Python.

The Folder Workflow runs entirely in any Python 3.10+ environment.

---

### Requirements

- Python 3.10+
- FFmpeg (system-wide)
- DaVinci Resolve 18+ *(Bin Workflow only)*

See [requirements.txt](requirements.txt) for Python dependencies.

---

### Production reference setup

- Cameras: 4K UHD @ 25 fps (Sony, Canon, Blackmagic)
- Audio: Separate WAV per speaker via Zoom field recorder (lav mics)
- NLE: DaVinci Resolve 19 / Adobe Premiere Pro 2025
- Analysis: MediaPipe Face Landmarker, ffmpeg for frame decoding

## Branches

- **`main`** – der Stand der zuletzt veröffentlichten stabilen Version.
- **`beta`** – der Stand der aktuellen Beta. Neue Arbeit landet hier zuerst.
- Eigene Änderungen bitte in einem eigenen Branch und als Pull Request gegen **`beta`**.

Mehr dazu in [CONTRIBUTING.md](CONTRIBUTING.md).

## Lizenz

GNU General Public License v3.0 – siehe [LICENSE](LICENSE). Wer MultiCamCutter verändert
und weitergibt, muss den Quellcode der veränderten Fassung ebenfalls unter der GPL
offenlegen. Verwendete Bibliotheken und ihre Lizenzen stehen in
`apps/multicam-cutter/scripts/acknowledgements.json`.
