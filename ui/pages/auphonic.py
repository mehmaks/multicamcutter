"""
Auphonic — Audio-Processing via Auphonic API (Cloud).
Extrahiert Audio aus Video- oder Audio-Dateien und schickt es zur Verarbeitung an Auphonic.
Ergebnis wird automatisch in den Resolve Media Pool importiert.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import threading
import queue
import tempfile
import subprocess
import configparser
import shutil
import urllib.request
import json
from pathlib import Path

st.title(":material/cloud: Auphonic")
st.caption("Cloud-Processing via Auphonic API · Voice Isolation · Leveling · De-Noise · De-Reverb")

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent.parent.parent / "modules" / "multicam_cutter" / "config.ini"

def _load_config():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")
    return cfg

def _get_auphonic_cfg():
    cfg = _load_config()
    return {
        "api_key": cfg.get("Auphonic", "api_key", fallback="").strip(),
        "cli_path": cfg.get("Auphonic", "cli_path", fallback="").strip(),
    }

def _find_auphonic_bin(cli_path: str) -> str | None:
    if cli_path and Path(cli_path).is_file():
        return cli_path
    candidates = [
        Path.home() / "bin" / "auphonic",
        Path("/usr/local/bin/auphonic"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return shutil.which("auphonic")

def _api_get(endpoint: str, api_key: str):
    req = urllib.request.Request(
        f"https://auphonic.com/api/{endpoint}",
        headers={"Authorization": f"bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read())

# ── Session state ─────────────────────────────────────────────────────────────

for _k, _v in {
    "auphonic_running": False,
    "auphonic_log": [],
    "auphonic_queue": None,
    "auphonic_credits": None,       # None = not yet fetched, False = error
    "auphonic_presets": None,       # None = not yet fetched, False = error
    "auphonic_preset_details": {},  # uuid → detail dict
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Load API key & binary ─────────────────────────────────────────────────────

auphonic_cfg = _get_auphonic_cfg()
api_key = auphonic_cfg["api_key"]
auphonic_bin = _find_auphonic_bin(auphonic_cfg["cli_path"])

if not auphonic_bin:
    st.error("Auphonic CLI nicht gefunden.")
    st.caption("Installation: `curl -sSL https://auphonic.com/cli/install.sh | sh` oder manuell in `~/bin/auphonic` ablegen.")
    st.stop()

# ── Auto-fetch credits & presets on first load ────────────────────────────────

if api_key:
    if st.session_state.auphonic_credits is None:
        try:
            data = _api_get("user.json", api_key)["data"]
            st.session_state.auphonic_credits = {
                "total":     float(data.get("credits", 0)),
                "recurring": float(data.get("recurring_credits", 0)),
                "onetime":   float(data.get("onetime_credits", 0)),
                "recharge":  data.get("recharge_date", "")[:10],
            }
        except Exception as e:
            st.session_state.auphonic_credits = {"error": str(e)}

    if st.session_state.auphonic_presets is None:
        try:
            data = _api_get("presets.json", api_key)
            # API returns either {"data": [...]} or a list directly
            items = data.get("data", data) if isinstance(data, dict) else data
            st.session_state.auphonic_presets = [
                {"uuid": p.get("uuid", ""), "name": p.get("preset_name", p.get("name", ""))}
                for p in (items if isinstance(items, list) else [])
            ]
        except Exception as e:
            st.session_state.auphonic_presets = {"error": str(e)}

# ── Credits display ───────────────────────────────────────────────────────────

col_key, col_credits = st.columns([3, 2])

with col_key:
    if not api_key:
        st.warning("Kein API Key in `config.ini`. Trage ihn unter `[Auphonic] api_key =` ein.")
    else:
        st.success(f"API Key hinterlegt (`{api_key[:6]}…`)")

with col_credits:
    c = st.session_state.auphonic_credits
    if c is None:
        st.caption("Credits werden geladen…")
    elif "error" in c:
        st.warning(f"Credits: {c['error']}")
    else:
        st.info(
            f"**{c['total']:.2f} h** verfügbar  \n"
            f"Monatlich: {c['recurring']:.2f} h · Einmalig: {c['onetime']:.2f} h  \n"
            f"Erneuerung: {c['recharge']}"
        )
    if st.button("", icon=":material/refresh:", help="Credits neu laden", key="refresh_credits"):
        st.session_state.auphonic_credits = None
        st.rerun()

st.divider()

# ── Preset selection ──────────────────────────────────────────────────────────

st.subheader("Preset")

presets = st.session_state.auphonic_presets
preset_error = isinstance(presets, dict) and "error" in presets
preset_list = presets if isinstance(presets, list) else []

_preset_options = ["– Kein Preset –"] + [p["name"] for p in preset_list]

col_preset, col_preset_refresh = st.columns([5, 1])
with col_preset:
    preset_label = st.selectbox(
        "Preset",
        options=_preset_options,
        index=0,
        label_visibility="collapsed",
        help="Gespeichertes Auphonic-Preset. Wenn ausgewählt, zeigen die Felder unten die Preset-Werte (schreibgeschützt).",
    )
with col_preset_refresh:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("", icon=":material/refresh:", help="Presets neu laden", key="refresh_presets"):
        st.session_state.auphonic_presets = None
        st.session_state.auphonic_preset_details = {}
        st.rerun()

if preset_error:
    st.caption(f"⚠ Presets konnten nicht geladen werden: {presets['error']}")

preset_active = preset_label != "– Kein Preset –"
preset_name = ""
preset_uuid = ""
preset_vals = {}   # populated from API when a preset is selected

if preset_active:
    # Find UUID for selected preset
    match = next((p for p in preset_list if p["name"] == preset_label), None)
    if match:
        preset_name = match["name"]
        preset_uuid = match["uuid"]
        # Fetch details if not cached
        if preset_uuid and preset_uuid not in st.session_state.auphonic_preset_details:
            try:
                detail = _api_get(f"preset/{preset_uuid}.json", api_key)
                st.session_state.auphonic_preset_details[preset_uuid] = detail.get("data", detail)
            except Exception as e:
                st.session_state.auphonic_preset_details[preset_uuid] = {"_error": str(e)}
        preset_vals = st.session_state.auphonic_preset_details.get(preset_uuid, {})

    if "_error" in preset_vals:
        st.warning(f"Preset-Details konnten nicht geladen werden: {preset_vals['_error']}")
    elif preset_vals:
        st.info(f"Preset **{preset_name}** aktiv — Werte unten zeigen die Preset-Einstellungen (schreibgeschützt). In der CLI wird nur der Preset-Name übergeben.")
    else:
        st.info(f"Preset **{preset_name}** aktiv — Einstellungen unten werden ignoriert.")

_ro = preset_active  # read-only flag: show preset values but disable inputs

st.divider()

# ── Helper to resolve preset values ──────────────────────────────────────────

def _pv(key, default):
    """Return preset value for key, falling back to default."""
    return preset_vals.get(key, default) if preset_vals and "_error" not in preset_vals else default

# ── Denoising Method ──────────────────────────────────────────────────────────

st.subheader("Denoising Method")

_DENOISE_OPTIONS = {
    "Dynamic":          "dynamic",
    "Classic":          "classic",
    "Speech Isolation": "speech_isolation",
    "Static":           "static",
    "Aus":              "off",
}
_DENOISE_LABELS = {v: k for k, v in _DENOISE_OPTIONS.items()}

_preset_denoise = _pv("denoise_type", "dynamic") if _ro else "dynamic"
_preset_denoise_label = _DENOISE_LABELS.get(_preset_denoise, "Dynamic")

denoise_method_label = st.selectbox(
    "Methode",
    options=list(_DENOISE_OPTIONS.keys()),
    index=list(_DENOISE_OPTIONS.keys()).index(_preset_denoise_label),
    disabled=_ro,
    help=(
        "**Dynamic** — KI-basiert, erkennt Rauschen adaptiv. Empfohlen.  \n"
        "**Classic** — Klassische spektrale Subtraktion.  \n"
        "**Speech Isolation** — Maximale Sprachreinigung (ähnlich DaVinci Voice Isolation).  \n"
        "**Static** — Für gleichbleibendes Hintergrundrauschen.  \n"
        "**Aus** — Kein De-Noising."
    ),
)
denoise_method = _DENOISE_OPTIONS[denoise_method_label]

_DB_VALUES = [-1, 0, 3, 6, 9, 12, 15, 18, 24, 30, 36, 100]
_DB_LABELS = {
    -1: "Aus", 0: "Auto",
    3: "3 dB", 6: "6 dB", 9: "9 dB", 12: "12 dB", 15: "15 dB",
    18: "18 dB", 24: "24 dB", 30: "30 dB", 36: "36 dB", 100: "100 dB (Max)",
}

if denoise_method != "off":
    _preset_da = _pv("noise_reduction_amount", 0) if _ro else 0
    _preset_da = _preset_da if _preset_da in _DB_VALUES else 0
    denoise_amount = st.select_slider(
        "De-Noise Stärke",
        options=_DB_VALUES,
        value=_preset_da,
        format_func=lambda v: _DB_LABELS[v],
        disabled=_ro,
        help="**Auto** = Auphonic wählt automatisch. **Aus** = deaktiviert.",
    )
else:
    denoise_amount = -1

# ── De-Reverb ─────────────────────────────────────────────────────────────────

st.divider()
st.subheader("De-Reverb")

_DEVERB_METHODS = {"dynamic", "static", "speech_isolation"}
deverb_available = denoise_method in _DEVERB_METHODS

if not deverb_available:
    st.caption("De-Reverb ist nur mit **Dynamic**, **Speech Isolation** oder **Static** verfügbar.")
    deverb_amount = -1
else:
    _preset_dv = _pv("reverb_reduction_amount", -1) if _ro else -1
    _preset_dv = _preset_dv if _preset_dv in _DB_VALUES else -1
    deverb_amount = st.select_slider(
        "De-Reverb Stärke",
        options=_DB_VALUES,
        value=_preset_dv,
        format_func=lambda v: _DB_LABELS[v],
        disabled=_ro,
        help="**Auto** = automatische Stärke. **Aus** = deaktiviert.",
    )

# ── De-Breath ─────────────────────────────────────────────────────────────────

st.divider()
st.subheader("Remove Breaths")

_DEBREATH_METHODS = {"dynamic", "speech_isolation"}
debreath_available = denoise_method in _DEBREATH_METHODS

_DB_NOAUTO = [-1, 3, 6, 9, 12, 15, 18, 24, 30, 36, 100]

if not debreath_available:
    st.caption("Remove Breaths ist nur mit **Dynamic** oder **Speech Isolation** verfügbar.")
    debreath_amount = -1
else:
    _preset_db = _pv("breath_reduction_amount", -1) if _ro else -1
    _preset_db = _preset_db if _preset_db in _DB_NOAUTO else -1
    debreath_amount = st.select_slider(
        "Atem-Reduktion Stärke",
        options=_DB_NOAUTO,
        value=_preset_db,
        format_func=lambda v: _DB_LABELS[v],
        disabled=_ro,
        help="Unterdrückt Atemgeräusche. **Aus** = deaktiviert.",
    )

# ── Adaptive Leveler ──────────────────────────────────────────────────────────

st.divider()
st.subheader("Adaptive Leveler")

_preset_lev = bool(_pv("leveling", True)) if _ro else True
leveler_enabled = st.checkbox("Adaptive Leveler aktivieren", value=_preset_lev, disabled=_ro)

if leveler_enabled:
    col_lev1, col_lev2 = st.columns(2)
    with col_lev1:
        _preset_ls = _pv("leveler_strength", 100) if _ro else 100
        leveler_strength = st.slider(
            "Leveler Stärke",
            min_value=0, max_value=120, value=int(_preset_ls), step=5,
            disabled=_ro,
            help="0 = kein Leveling, 100 = Standard, 120 = Maximum.",
        )
    with col_lev2:
        _COMP_OPTIONS = ["auto", "soft", "medium", "hard", "off"]
        _COMP_LABELS  = {"auto": "Auto", "soft": "Soft", "medium": "Medium", "hard": "Hard", "off": "Aus"}
        _preset_comp = _pv("compressor", "auto") if _ro else "auto"
        _preset_comp = _preset_comp if _preset_comp in _COMP_OPTIONS else "auto"
        compressor = st.selectbox(
            "Compressor",
            options=_COMP_OPTIONS,
            index=_COMP_OPTIONS.index(_preset_comp),
            format_func=lambda v: _COMP_LABELS[v],
            disabled=_ro,
            help=(
                "**Auto** — Auphonic wählt passend zur Lautheitsdifferenz.  \n"
                "**Soft / Medium / Hard** — Zunehmende Kompression.  \n"
                "**Aus** — Kein Compressor."
            ),
        )
else:
    leveler_strength = None
    compressor = None

# ── Filtering ─────────────────────────────────────────────────────────────────

st.divider()
st.subheader("Filtering")

_preset_filt = bool(_pv("filtering", True)) if _ro else True
filtering_enabled = st.checkbox(
    "Filtering aktivieren", value=_preset_filt, disabled=_ro,
    help="Anpassung des Frequenzgangs (Auto-EQ, Hochpassfilter oder Bandbreitenerweiterung).",
)

_FILTER_OPTIONS = {"autoeq": "Auto EQ", "hipfilter": "Highpass Filter", "bwe": "Bandwidth Extension"}

if filtering_enabled:
    _preset_fm = _pv("filter_method", "autoeq") if _ro else "autoeq"
    _preset_fm = _preset_fm if _preset_fm in _FILTER_OPTIONS else "autoeq"
    filter_method = st.selectbox(
        "Filter-Methode",
        options=list(_FILTER_OPTIONS.keys()),
        index=list(_FILTER_OPTIONS.keys()).index(_preset_fm),
        format_func=lambda v: _FILTER_OPTIONS[v],
        disabled=_ro,
        help=(
            "**Auto EQ** — Automatische Frequenzkorrektur.  \n"
            "**Highpass Filter** — Entfernt tiefe Frequenzen.  \n"
            "**Bandwidth Extension** — Erweitert die Bandbreite."
        ),
    )
else:
    filter_method = None

# ── Loudness Normalization ────────────────────────────────────────────────────

st.divider()
st.subheader("Loudness Normalization")

_preset_loud = bool(_pv("loudness_normalization", True)) if _ro else True
loudness_enabled = st.checkbox("Loudness Normalization aktivieren", value=_preset_loud, disabled=_ro)

if loudness_enabled:
    col_l1, col_l2, col_l3 = st.columns(3)

    _LOUD_OPTIONS = [-13, -16, -18, -23, -24, -31]
    with col_l1:
        _preset_lt = _pv("loudness_target", -16) if _ro else -16
        _preset_lt = _preset_lt if _preset_lt in _LOUD_OPTIONS else -16
        loudness_target = st.selectbox(
            "Ziel-Lautheit (LUFS)",
            options=_LOUD_OPTIONS,
            index=_LOUD_OPTIONS.index(_preset_lt),
            format_func=lambda v: f"{v} LUFS",
            disabled=_ro,
            help="-16 LUFS = Podcasts · -23/-24 = EBU R128 / TV · -13 = YouTube",
        )

    _LOUD_METHOD = ["program", "dialog", "rms"]
    with col_l2:
        _preset_lm = _pv("loudness_method", "program") if _ro else "program"
        _preset_lm = _preset_lm if _preset_lm in _LOUD_METHOD else "program"
        loudness_method = st.selectbox(
            "Mess-Methode",
            options=_LOUD_METHOD,
            index=_LOUD_METHOD.index(_preset_lm),
            format_func=lambda v: {"program": "Program", "dialog": "Dialog", "rms": "RMS"}[v],
            disabled=_ro,
        )

    _PEAK_OPTIONS = [0, -0.5, -1.0, -1.5, -2.0, -3.0, -4.0, -5.0, -6.0]
    with col_l3:
        _preset_mp = _pv("max_peak", 0) if _ro else 0
        _preset_mp = _preset_mp if _preset_mp in _PEAK_OPTIONS else 0
        max_peak = st.selectbox(
            "Max True Peak",
            options=_PEAK_OPTIONS,
            index=_PEAK_OPTIONS.index(_preset_mp),
            format_func=lambda v: "Auto" if v == 0 else f"{v} dBTP",
            disabled=_ro,
            help="-1 dBTP empfohlen für Streaming.",
        )
else:
    loudness_target = None
    loudness_method = None
    max_peak = None

# ── Output Format ─────────────────────────────────────────────────────────────

st.divider()
st.subheader("Output")

output_fmt = st.selectbox(
    "Output-Format",
    options=["wav", "mp3", "flac", "m4a"],
    index=0,
    help="wav = verlustfrei, empfohlen für Weiterverarbeitung in Resolve.",
)

st.divider()

# ── File selection ─────────────────────────────────────────────────────────────

AUDIO_EXTENSIONS = {".wav", ".mp3", ".aif", ".aiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".r3d", ".braw", ".avi", ".mkv"}

st.subheader("Dateien auswählen")
source_mode = st.radio("Quelle", ["Resolve Media Pool", "Ordner / Dateien"], horizontal=True)

selected_path_files: list = []
resolve_import_target = None

if source_mode == "Resolve Media Pool":

    def _collect_bins(folder, depth=0):
        bins = []
        if depth > 0:
            bins.append("  " * (depth - 1) + folder.GetName())
        for sf in (folder.GetSubFolderList() or []):
            bins.extend(_collect_bins(sf, depth + 1))
        return bins

    def _find_folder(folder, name):
        if folder.GetName() == name:
            return folder
        for sf in (folder.GetSubFolderList() or []):
            found = _find_folder(sf, name)
            if found:
                return found
        return None

    try:
        from resolve_bridge.connection import get_resolve
        resolve = get_resolve()
        project = resolve.GetProjectManager().GetCurrentProject()
        mp = project.GetMediaPool()
        root = mp.GetRootFolder()

        all_bins = _collect_bins(root)
        if not all_bins:
            st.warning("Keine Bins im Media Pool gefunden.")
        else:
            selected_display = st.selectbox("Media Pool Bin", options=all_bins)
            bin_name = selected_display.strip() if selected_display else None
            if bin_name:
                folder = _find_folder(root, bin_name)
                if folder:
                    clips = folder.GetClipList() or []
                    _all_ext = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
                    audio_clips = [
                        (c.GetName(), c.GetClipProperty("File Path"))
                        for c in clips
                        if c.GetClipProperty("File Path")
                        and Path(c.GetClipProperty("File Path")).suffix.lower() in _all_ext
                    ]
                    if audio_clips:
                        chosen = st.multiselect(
                            f"Clips in '{bin_name}'",
                            options=[n for n, _ in audio_clips],
                            default=[n for n, _ in audio_clips],
                        )
                        selected_path_files = [(n, p) for n, p in audio_clips if n in chosen]
                        resolve_import_target = (mp, folder)
                        _n_video = sum(
                            1 for _, p in selected_path_files
                            if Path(p).suffix.lower() in VIDEO_EXTENSIONS
                        )
                        if _n_video:
                            st.caption(f"ℹ {_n_video} Videodatei(en) — Audio (Spur 1) wird via ffmpeg extrahiert.")
                    else:
                        st.info("Keine Audio- oder Videodateien in diesem Bin gefunden.")
    except Exception as e:
        st.error("Resolve nicht verbunden")
        st.caption(str(e))

else:
    col_path, col_btn = st.columns([4, 1])
    with col_path:
        folder_path_str = st.text_input("Ordner-Pfad", placeholder="/Volumes/Media/Recording", key="auphonic_folder_path")
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Scannen", use_container_width=True):
            p = Path(folder_path_str) if folder_path_str else None
            if p and p.is_dir():
                found = sorted(
                    (f for f in p.iterdir() if f.suffix.lower() in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS),
                    key=lambda f: f.name,
                )
                st.session_state.auphonic_scanned = [(f.name, str(f)) for f in found]
            else:
                st.error("Ordner nicht gefunden.")
                st.session_state.auphonic_scanned = []

    if "auphonic_scanned" not in st.session_state:
        st.session_state.auphonic_scanned = []

    if st.session_state.auphonic_scanned:
        chosen = st.multiselect(
            "Dateien auswählen",
            options=[n for n, _ in st.session_state.auphonic_scanned],
            default=[n for n, _ in st.session_state.auphonic_scanned],
            key="auphonic_folder_select",
        )
        selected_path_files = [(n, p) for n, p in st.session_state.auphonic_scanned if n in chosen]

# ── Processing ────────────────────────────────────────────────────────────────

def _run_auphonic(files: list, settings: dict, q: queue.Queue,
                  resolve_import: tuple = None):
    try:
        q.put("Starte Auphonic-Verarbeitung …\n")
        for name, src_path in files:
            q.put(f"► {name}")
            src = Path(src_path)

            current = str(src)
            _video_tmp = None
            if src.suffix.lower() in VIDEO_EXTENSIONS:
                q.put("  Audio-Extraktion via ffmpeg …")
                _video_tmp = tempfile.mktemp(suffix=".wav")
                r = subprocess.run(
                    ["ffmpeg", "-y", "-i", str(src), "-map", "0:a:0",
                     "-acodec", "pcm_s24le", _video_tmp],
                    capture_output=True, encoding="utf-8", errors="replace",
                )
                if r.returncode != 0:
                    raise RuntimeError(f"ffmpeg fehlgeschlagen:\n{r.stderr[-300:]}")
                current = _video_tmp

            out_dir = src.parent
            cmd = [settings["bin"], "process", current,
                   "--api-key", settings["api_key"],
                   "--output", f"format={settings['output_fmt']}",
                   "--output-dir", str(out_dir),
                   "--wait", "--download"]

            if settings["preset"]:
                cmd += ["--preset", settings["preset"]]
            else:
                # Denoising
                if settings["denoise_method"] == "off":
                    cmd += ["--no-denoise"]
                else:
                    cmd += ["--denoise-method", settings["denoise_method"]]
                    if settings["denoise_amount"] != 0:
                        cmd += ["--denoise-amount", str(settings["denoise_amount"])]

                if settings["deverb_amount"] >= 0:
                    cmd += ["--deverb-amount", str(settings["deverb_amount"])]

                if settings["debreath_amount"] > 0:
                    cmd += ["--debreath-amount", str(settings["debreath_amount"])]

                # Leveler
                if not settings["leveler_enabled"]:
                    cmd += ["--no-leveler"]
                else:
                    if settings["leveler_strength"] is not None and settings["leveler_strength"] != 100:
                        cmd += ["--leveler-strength", str(settings["leveler_strength"])]
                    if settings["compressor"] and settings["compressor"] != "auto":
                        cmd += ["--compressor", settings["compressor"]]

                # Filtering
                if not settings["filtering_enabled"]:
                    cmd += ["--no-filtering"]
                elif settings["filter_method"]:
                    cmd += ["--filter-method", settings["filter_method"]]

                # Loudness
                if not settings["loudness_enabled"]:
                    cmd += ["--no-loudness"]
                else:
                    if settings["loudness_target"] is not None:
                        cmd += ["--loudness", str(settings["loudness_target"])]
                    if settings["loudness_method"]:
                        cmd += ["--loudness-method", settings["loudness_method"]]
                    if settings["max_peak"] and settings["max_peak"] != 0:
                        cmd += ["--max-peak", str(settings["max_peak"])]

            q.put("  Sende an Auphonic …")
            proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")

            if _video_tmp and Path(_video_tmp).exists():
                Path(_video_tmp).unlink()

            if proc.returncode != 0:
                raise RuntimeError(f"Auphonic fehlgeschlagen:\n{proc.stderr[-500:]}")

            _out_ext = "." + settings["output_fmt"]
            _candidates = sorted(
                out_dir.glob(f"{src.stem}*{_out_ext}"),
                key=lambda f: f.stat().st_mtime, reverse=True,
            )
            _out_file = _candidates[0] if _candidates else None

            if _out_file:
                q.put(f"  ✓ gespeichert: {_out_file.name}")
            else:
                q.put("  ✓ Verarbeitung abgeschlossen (Datei im Ausgabeordner)")

            if resolve_import and _out_file:
                try:
                    _mp, _folder = resolve_import
                    _mp.SetCurrentFolder(_folder)
                    _mp.ImportMedia([str(_out_file)])
                    q.put("  ✓ in Resolve importiert\n")
                except Exception as _e:
                    q.put(f"  ⚠ Resolve-Import fehlgeschlagen: {_e}\n")
            else:
                q.put("")

        q.put("__DONE__0")
    except Exception as e:
        q.put(f"Fehler: {e}")
        q.put("__DONE__1")


# ── Run Button ────────────────────────────────────────────────────────────────

st.divider()

can_start = (
    bool(selected_path_files)
    and bool(api_key)
    and bool(auphonic_bin)
    and not st.session_state.auphonic_running
)

start = st.button(
    "☁️ Auphonic starten",
    type="primary",
    disabled=not can_start,
    use_container_width=True,
)

if not api_key:
    st.caption("⚠ API Key fehlt — in `config.ini` unter `[Auphonic] api_key =` eintragen.")

if start:
    settings = {
        "bin":              auphonic_bin,
        "api_key":          api_key,
        "preset":           preset_name,
        "output_fmt":       output_fmt,
        "denoise_method":   denoise_method,
        "denoise_amount":   denoise_amount,
        "deverb_amount":    deverb_amount,
        "debreath_amount":  debreath_amount,
        "leveler_enabled":  leveler_enabled,
        "leveler_strength": leveler_strength,
        "compressor":       compressor if leveler_enabled else None,
        "filtering_enabled": filtering_enabled,
        "filter_method":    filter_method,
        "loudness_enabled": loudness_enabled,
        "loudness_target":  loudness_target,
        "loudness_method":  loudness_method,
        "max_peak":         max_peak,
    }
    st.session_state.auphonic_running = True
    st.session_state.auphonic_log = []
    q = queue.Queue()
    st.session_state.auphonic_queue = q
    threading.Thread(
        target=_run_auphonic,
        args=(
            selected_path_files, settings, q,
            resolve_import_target if source_mode == "Resolve Media Pool" else None,
        ),
        daemon=True,
    ).start()
    st.rerun()

# ── Log ───────────────────────────────────────────────────────────────────────

if st.session_state.auphonic_running or st.session_state.auphonic_log:
    st.divider()
    st.subheader("Log")

    if st.session_state.auphonic_running and st.session_state.auphonic_queue:
        q = st.session_state.auphonic_queue
        while not q.empty():
            msg = q.get_nowait()
            if msg.startswith("__DONE__"):
                st.session_state.auphonic_running = False
                break
            st.session_state.auphonic_log.append(msg)

    log_text = "\n".join(st.session_state.auphonic_log)
    st.code(log_text, language=None)

    if st.session_state.auphonic_running:
        st.spinner("Verarbeitung läuft …")
        import time; time.sleep(2); st.rerun()
