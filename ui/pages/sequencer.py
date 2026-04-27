"""
Sequencer — Modulare Pipeline-Plattform

Zweispaltiges Layout:
  Links:  Aktive Pipeline (Rack) — Module sortieren, entfernen, Parameter einstellen
  Rechts: Modul-Katalog — alle verfügbaren Module, per Klick ins Rack einfügen
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import threading
import queue
import time
from pathlib import Path

import streamlit as st

from sequencer import Registry, PipelineContext, Pipeline, PipelineError

st.title(":material/view_list: Sequencer")
st.caption("Modulare Pipeline — baue Tools aus wiederverwendbaren Modulen.")

if "_pending_toast" in st.session_state:
    st.toast(st.session_state.pop("_pending_toast"))


# ═══════════════════════════════════════════════════════════════════════════
# Konstanten & Hilfs-Funktionen
# ═══════════════════════════════════════════════════════════════════════════

_CAT_COLORS = {
    "io":       "#3b82f6",
    "analysis": "#8b5cf6",
    "editing":  "#f59e0b",
    "resolve":  "#10b981",
}
_CAT_ICONS = {
    "io":       ":material/folder_open:",
    "analysis": ":material/analytics:",
    "editing":  ":material/content_cut:",
    "resolve":  ":material/smart_display:",
}
_CAT_LABELS = {
    "io":       "I/O",
    "analysis": "Analyse",
    "editing":  "Schnitt",
    "resolve":  "Resolve",
}

# ── Stream-Abstraktion ──────────────────────────────────────────────────────
# Technische Context-Keys → vereinfachte Streams für die UI.
# Der User denkt in Signalfluss (Video, Audio, Schnitt), nicht in Keys.
# Mehrere Keys können zum gleichen Stream gehören — z.B. audio.data und
# audio.gated sind beide "Audio", weil das Gate den Stream verarbeitet,
# nicht durch etwas anderes ersetzt.

_STREAMS = {
    # stream_id:  (Label, Icon, Farbe)
    "video":      ("Video",       ":material/videocam:",     "#3b82f6"),
    "audio":      ("Audio",       ":material/mic:",          "#8b5cf6"),
    "sync":       ("Sync",        ":material/sync:",         "#06b6d4"),
    "speech":     ("Sprache",     ":material/record_voice_over:", "#ec4899"),
    "edit":       ("Schnitt",     ":material/content_cut:",  "#f59e0b"),
    "reactions":  ("Reaktionen",  ":material/sentiment_satisfied:", "#ef4444"),
    "pauses":     ("Pausen",      ":material/pause_circle:", "#f97316"),
    "timing":     ("Timing",      ":material/timer:",        "#10b981"),
}

# Technischer Key → Stream-ID
_KEY_TO_STREAM = {
    "sources.cameras":          "video",
    "sources.mics":             "audio",
    "sources.mode":             "video",      # gehört zum Quell-Setup
    "sync.offsets":             "sync",
    "audio.data":               "audio",
    "audio.gated":              "audio",      # Gate verändert Audio, ersetzt es nicht
    "diarization.segments":     "speech",
    "simultaneous_speech":      "speech",
    "events.base":              "edit",
    "events.with_cutaways":     "edit",
    "events.with_pause_cutaways": "edit",
    "events.cleaned":           "edit",
    "events.split":             "edit",
    "events.filtered":          "edit",
    "frame_mapping":            "timing",
    "reactions.nodding":        "reactions",
    "reactions.speaking":       "reactions",
    "pauses.detected":          "pauses",
    "pauses.cutaway_candidates": "pauses",
    "off_sections":             "timing",
    "cameras_config":           "video",      # Kamera-Metadaten = Teil des Video-Streams
    "cut_events":               "edit",
    "audio_keeps":              "pauses",
}

_RUN_KEY = "seq_running"
_PROGRESS_KEY = "seq_progress"
_CURRENT_MOD_KEY = "seq_current_module"
_LOG_KEY = "seq_log"
_RACK_KEY = "seq_rack"  # List[str] — Modul-Namen in Reihenfolge


def _stream_badge(stream_id: str) -> str:
    """HTML-Badge für einen Stream."""
    label, icon_name, color = _STREAMS.get(stream_id, (stream_id, "", "#6b7280"))
    return (
        f"<span style='background:{color}18; color:{color}; border:1px solid {color}33; "
        f"padding:2px 10px; border-radius:12px; font-size:0.72rem; "
        f"font-weight:500; white-space:nowrap;'>"
        f"{label}</span>"
    )


def _keys_to_streams(keys: list[str]) -> list[str]:
    """Technische Keys → deduplizierte Stream-IDs in stabiler Reihenfolge."""
    seen = set()
    result = []
    # Stabile Reihenfolge nach Stream-Definition
    stream_order = list(_STREAMS.keys())
    streams_for_keys = set()
    for k in keys:
        sid = _KEY_TO_STREAM.get(k)
        if sid:
            streams_for_keys.add(sid)
    for sid in stream_order:
        if sid in streams_for_keys and sid not in seen:
            result.append(sid)
            seen.add(sid)
    return result


def _cat_badge(cat: str) -> str:
    """HTML-Badge für eine Modul-Kategorie."""
    color = _CAT_COLORS.get(cat, "#6b7280")
    label = _CAT_LABELS.get(cat, cat)
    return (
        f"<span style='background:{color}; color:#fff; padding:2px 8px; "
        f"border-radius:4px; font-size:0.7rem;'>{label}</span>"
    )


def _connector_html(keys: set) -> str:
    """HTML-Konnektor: zeigt die Streams die weitergereicht werden."""
    streams = _keys_to_streams(sorted(keys))
    if not streams:
        return ""
    badges = " ".join(_stream_badge(s) for s in streams)
    return (
        f"<div style='display:flex; align-items:center; gap:6px; "
        f"padding:3px 0 3px 24px; margin:-2px 0;'>"
        f"<span style='color:#d1d5db; font-size:1rem;'>&#x2502;</span>"
        f" {badges}"
        f"</div>"
    )


def _render_module_params(mod):
    """Rendert Parameter-Widgets für ein Modul basierend auf dessen Schema."""
    schema = mod.schema
    for exp in schema.get("expanders", []):
        for row in exp.get("rows", []):
            n_cols = row.get("columns", 1)
            params = row.get("params", [])
            cols = st.columns(n_cols) if n_cols > 1 else [st.container()]
            for p in params:
                col_idx = min(p.get("column", 0), len(cols) - 1)
                with cols[col_idx]:
                    key = f"seq_{mod.name}_{p['name']}"
                    label = p.get("label", p["name"])
                    default = p.get("default")
                    help_text = p.get("help", "")
                    widget = p.get("widget", "number_input")

                    if widget == "number_input":
                        st.number_input(label, value=default, key=key,
                                        help=help_text, **p.get("config", {}))
                    elif widget == "toggle":
                        st.toggle(label, value=default, key=key, help=help_text)
                    elif widget == "slider":
                        st.slider(label, value=default, key=key,
                                  help=help_text, **p.get("config", {}))
                    elif widget == "selectbox":
                        options = p.get("options", p.get("config", {}).get("options", []))
                        idx_sel = options.index(default) if default in options else 0
                        st.selectbox(label, options=options, index=idx_sel,
                                     key=key, help=help_text)


def _run_pipeline_thread(rack_names, source_mode, ingest_params, fps,
                         work_dir, progress_queue):
    """Pipeline in separatem Thread ausführen."""
    from sequencer.runner import run_sequencer

    def _cb(frac, mod_name, msg):
        progress_queue.put(("progress", frac, mod_name, msg))

    try:
        # Rack-Module instanziieren
        modules = [Registry.get(n)() for n in rack_names]
        ctx = PipelineContext(work_dir=work_dir or Path.cwd() / "analyse", fps=fps)
        (work_dir or Path.cwd() / "analyse").mkdir(parents=True, exist_ok=True)

        pipeline = Pipeline(modules, ctx)
        params = {"ingest": {"source_mode": source_mode, **ingest_params}}
        pipeline.run(params, progress_callback=_cb)
        progress_queue.put(("exit", 0))
    except PipelineError as e:
        progress_queue.put(("error", f"Modul '{e.module}' (Schritt {e.step}): {e.original_error}"))
    except Exception as e:
        progress_queue.put(("error", str(e)))


# ═══════════════════════════════════════════════════════════════════════════
# Registry initialisieren
# ═══════════════════════════════════════════════════════════════════════════

Registry.discover()
_all_modules = Registry.all_modules()  # {name: class}
_catalog = Registry.catalog()          # List[Dict]
_presets = Registry.list_presets()

# Katalog nach Kategorie gruppieren
_cat_groups: dict[str, list] = {}
for entry in sorted(_catalog, key=lambda e: (e["category"], e["name"])):
    _cat_groups.setdefault(entry["category"], []).append(entry)


# ═══════════════════════════════════════════════════════════════════════════
# Rack-State initialisieren
# ═══════════════════════════════════════════════════════════════════════════

if _RACK_KEY not in st.session_state:
    # Erstes Preset als Default laden
    if _presets:
        _default = Registry.load_preset(_presets[0]["name"])
        st.session_state[_RACK_KEY] = [m.name for m in _default]
    else:
        st.session_state[_RACK_KEY] = []


# ── Preset laden ────────────────────────────────────────────────────────────

_preset_col, _load_col = st.columns([4, 1])
with _preset_col:
    _preset_options = ["(Custom)"] + [f"{p['title']} ({p['steps']})" for p in _presets]
    _preset_sel = st.selectbox("Preset", _preset_options, key="seq_preset_sel",
                               label_visibility="collapsed")
with _load_col:
    if st.button("Laden", use_container_width=True, icon=":material/download:",
                 disabled=_preset_sel == "(Custom)"):
        idx = _preset_options.index(_preset_sel) - 1
        loaded = Registry.load_preset(_presets[idx]["name"])
        st.session_state[_RACK_KEY] = [m.name for m in loaded]
        st.rerun()

_rack: list[str] = st.session_state[_RACK_KEY]


# ═══════════════════════════════════════════════════════════════════════════
# Zweispaltiges Layout: Rack | Katalog
# ═══════════════════════════════════════════════════════════════════════════

_col_rack, _col_catalog = st.columns([3, 1.2])


# ── RECHTE SPALTE: Modul-Katalog ────────────────────────────────────────────

with _col_catalog:
    st.markdown("#### Katalog")

    for cat_key in ["io", "analysis", "editing", "resolve"]:
        entries = _cat_groups.get(cat_key, [])
        if not entries:
            continue

        color = _CAT_COLORS.get(cat_key, "#6b7280")
        label = _CAT_LABELS.get(cat_key, cat_key)
        icon = _CAT_ICONS.get(cat_key, "")
        st.markdown(
            f"<div style='font-size:0.75rem; font-weight:600; color:{color}; "
            f"margin:12px 0 4px 0; text-transform:uppercase; letter-spacing:0.05em;'>"
            f"{label}</div>",
            unsafe_allow_html=True,
        )

        for entry in entries:
            in_rack = entry["name"] in _rack
            _c1, _c2 = st.columns([4, 1])
            with _c1:
                style = "color:#9ca3af;" if in_rack else ""
                st.markdown(
                    f"<span style='font-size:0.8rem; {style}'>"
                    f"{'~~' if in_rack else ''}{entry['name']}{'~~' if in_rack else ''}"
                    f"</span>",
                    unsafe_allow_html=True,
                )
            with _c2:
                if st.button(
                    "+", key=f"cat_add_{entry['name']}",
                    use_container_width=True,
                    disabled=in_rack,
                ):
                    st.session_state[_RACK_KEY].append(entry["name"])
                    st.rerun()


# ── LINKE SPALTE: Rack (aktive Pipeline) ────────────────────────────────────

with _col_rack:
    st.markdown("#### Rack")

    if not _rack:
        st.info("Rack ist leer. Füge Module aus dem Katalog hinzu oder lade ein Preset.")

    # Verfügbare Keys berechnen (kumuliert)
    _available_keys: set[str] = set()
    _progress_data = st.session_state.get(_PROGRESS_KEY, {})

    # Instanzen für Rendering
    _rack_instances = []
    for name in _rack:
        try:
            _rack_instances.append(Registry.get(name)())
        except KeyError:
            pass  # Modul entfernt — wird unten bereinigt

    for i, mod in enumerate(_rack_instances):
        # ── Konnektor: kumulierter Datenfluss an dieser Stelle ──
        if i > 0:
            _available_keys.update(_rack_instances[i - 1].outputs)
            st.markdown(_connector_html(_available_keys), unsafe_allow_html=True)

        # ── Input-Validierung ──
        missing = [k for k in mod.inputs if k not in _available_keys]
        satisfied_opt = [k for k in mod.optional_inputs if k in _available_keys]

        # ── Modul-Status ──
        mod_status = _progress_data.get(mod.name, "pending")

        # ── Modul-Karte ──
        with st.container(border=True):
            # Zeile 1: Nummer, Name, Kategorie, Aktionen
            top = st.columns([0.4, 4.5, 1.5, 0.6, 0.6, 0.6])

            with top[0]:
                st.markdown(f"**{i+1}**")

            with top[1]:
                icon = _CAT_ICONS.get(mod.category, ":material/extension:")
                st.markdown(f"{icon} **{mod.name}**")
                if mod.description:
                    st.caption(mod.description)

            with top[2]:
                st.markdown(_cat_badge(mod.category), unsafe_allow_html=True)

            # Aktionen: hoch, runter, entfernen
            with top[3]:
                if st.button(":material/arrow_upward:", key=f"rack_up_{i}",
                             disabled=i == 0, use_container_width=True):
                    r = st.session_state[_RACK_KEY]
                    r[i], r[i-1] = r[i-1], r[i]
                    st.rerun()
            with top[4]:
                if st.button(":material/arrow_downward:", key=f"rack_down_{i}",
                             disabled=i == len(_rack) - 1, use_container_width=True):
                    r = st.session_state[_RACK_KEY]
                    r[i], r[i+1] = r[i+1], r[i]
                    st.rerun()
            with top[5]:
                if st.button(":material/close:", key=f"rack_rm_{i}",
                             use_container_width=True):
                    st.session_state[_RACK_KEY].pop(i)
                    st.rerun()

            # Zeile 2: I/O als Streams (vereinfacht)
            in_streams = _keys_to_streams(mod.inputs + mod.optional_inputs)
            out_streams = _keys_to_streams(mod.outputs)
            if in_streams or out_streams:
                io_html = "<div style='display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-top:2px;'>"
                if in_streams:
                    in_badges = " ".join(_stream_badge(s) for s in in_streams)
                    io_html += in_badges
                if in_streams and out_streams:
                    io_html += "<span style='color:#d1d5db; font-size:0.8rem; margin:0 2px;'>&#x2192;</span>"
                if out_streams:
                    out_badges = " ".join(_stream_badge(s) for s in out_streams)
                    io_html += out_badges
                io_html += "</div>"
                st.markdown(io_html, unsafe_allow_html=True)

            # Fehlende Inputs warnen (in Stream-Sprache)
            if missing:
                miss_streams = _keys_to_streams(missing)
                if miss_streams:
                    miss_str = ", ".join(
                        _STREAMS[s][0] for s in miss_streams
                    )
                    st.warning(f"Benötigt: {miss_str}", icon=":material/warning:")

            # Status / Progressbar
            if mod_status == "done":
                st.markdown(":material/check_circle: Fertig")
            elif mod_status == "running":
                mod_frac = _progress_data.get(f"{mod.name}_frac", 0.0)
                st.progress(mod_frac)
            elif mod_status == "error":
                st.markdown(":material/error: Fehler")

            # Parameter (expandierbar)
            if mod.schema and mod.schema.get("expanders"):
                with st.expander("Parameter", expanded=False):
                    _render_module_params(mod)

    # Letzter Konnektor: finale Outputs
    if _rack_instances:
        _available_keys.update(_rack_instances[-1].outputs)
        final_out = set(_rack_instances[-1].outputs)
        if final_out:
            st.markdown(_connector_html(final_out), unsafe_allow_html=True)

        all_streams = _keys_to_streams(sorted(_available_keys))
        badges = " ".join(_stream_badge(s) for s in all_streams)
        st.markdown(
            f"<div style='padding:4px 0 0 24px; font-size:0.75rem; color:#6b7280;'>"
            f"Ergebnis: {badges}</div>",
            unsafe_allow_html=True,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Validierung
# ═══════════════════════════════════════════════════════════════════════════

if _rack_instances:
    _ctx_dummy = PipelineContext(work_dir=Path("/tmp"), fps=25.0)
    _pipeline = Pipeline(_rack_instances, _ctx_dummy)
    _errors = _pipeline.validate()
else:
    _errors = []

if _errors:
    st.error(f"Pipeline-Validierung: {len(_errors)} Fehler")
    for err in _errors:
        st.markdown(f"- {err}")


# ═══════════════════════════════════════════════════════════════════════════
# Start-Bereich
# ═══════════════════════════════════════════════════════════════════════════

st.divider()

_resolve_ok = st.session_state.get("resolve_status", ("error",))[0] == "ok"

col_mode, col_source = st.columns(2)

with col_mode:
    _source_options = ["Ordner"]
    if _resolve_ok:
        _source_options.insert(0, "Resolve Bin")
    _source_mode = st.selectbox("Quelle", _source_options, key="seq_source_mode")

with col_source:
    if _source_mode == "Resolve Bin":
        st.text_input("Bin-Name", key="seq_bin_name",
                      placeholder="z.B. '30 - Ebra'")
    else:
        st.text_input("Ordner-Pfad", key="seq_folder_path",
                      placeholder="/pfad/zu/medien")

col_fps, col_output = st.columns(2)

with col_fps:
    _fps = st.number_input("FPS", value=25.0, step=0.01, key="seq_fps")

with col_output:
    st.text_input("Ausgabe-Name", key="seq_output_name",
                  placeholder="z.B. 'JU 30 Final'")


# ── Pipeline starten ────────────────────────────────────────────────────────

_is_running = st.session_state.get(_RUN_KEY, False)

if st.button(
    "Pipeline starten" if not _is_running else "Läuft...",
    type="primary",
    disabled=_is_running or bool(_errors) or not _rack,
    use_container_width=True,
    icon=":material/play_arrow:",
):
    ingest_params = {}
    if _source_mode == "Resolve Bin":
        source_mode = "resolve_bin"
        ingest_params["bin_name"] = st.session_state.get("seq_bin_name", "")
    else:
        source_mode = "folder"
        ingest_params["folder_path"] = st.session_state.get("seq_folder_path", "")

    _out = st.session_state.get("seq_output_name", "")
    if _out:
        ingest_params["output_name"] = _out

    st.session_state[_RUN_KEY] = True
    st.session_state[_PROGRESS_KEY] = {}
    st.session_state[_CURRENT_MOD_KEY] = ""
    st.session_state[_LOG_KEY] = []

    q = queue.Queue()
    st.session_state["seq_queue"] = q

    threading.Thread(
        target=_run_pipeline_thread,
        args=(list(_rack), source_mode, ingest_params, _fps, None, q),
        daemon=True,
    ).start()
    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# Live-Fortschritt
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state.get(_RUN_KEY) and "seq_queue" in st.session_state:
    _q = st.session_state["seq_queue"]
    _prog_ph = st.empty()
    _log_ph = st.empty()

    _prev_mod = ""
    _pd = st.session_state.get(_PROGRESS_KEY, {})

    while st.session_state.get(_RUN_KEY):
        try:
            msg = _q.get(timeout=0.1)
            if msg[0] == "progress":
                _, frac, mod_name, text = msg
                if mod_name != _prev_mod and _prev_mod:
                    _pd[_prev_mod] = "done"
                _pd[mod_name] = "running"
                _pd[f"{mod_name}_frac"] = frac
                _prev_mod = mod_name
                st.session_state[_CURRENT_MOD_KEY] = mod_name
                st.session_state[_LOG_KEY].append(f"[{frac*100:.0f}%] {text}")

                with _prog_ph.container():
                    st.progress(min(1.0, frac))
                    st.caption(f"**{mod_name}** — {text}")

                _log = st.session_state[_LOG_KEY]
                _log_ph.code("\n".join(_log[-15:]), language=None)

            elif msg[0] == "exit":
                code = msg[1]
                if _prev_mod:
                    _pd[_prev_mod] = "done"
                st.session_state[_RUN_KEY] = False
                st.session_state["_pending_toast"] = (
                    "Pipeline abgeschlossen!" if code == 0
                    else f"Pipeline fehlgeschlagen (Exit {code})"
                )

            elif msg[0] == "error":
                st.session_state[_RUN_KEY] = False
                if _prev_mod:
                    _pd[_prev_mod] = "error"
                st.session_state["_pending_toast"] = f"Fehler: {msg[1]}"

        except queue.Empty:
            pass

        st.session_state[_PROGRESS_KEY] = _pd
        time.sleep(0.05)

    st.rerun()


# ── Log (nach Abschluss) ───────────────────────────────────────────────────

_final_log = st.session_state.get(_LOG_KEY, [])
if _final_log and not st.session_state.get(_RUN_KEY, False):
    with st.expander("Log", expanded=False):
        st.code("\n".join(_final_log), language=None)
