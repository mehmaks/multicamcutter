"""
Voice Leveler — Voice Dynamics Processing via ffmpeg
Leveler (AGC) → Gate → Upward Compressor → HL Compressor → Limiter

Compand-Kurve (MaxxVolume-Modell):
  (-90, floor) | (llt, llt) | (hlt, hlt) | (0, hl_gain)

  LLT = Unity-Decke des Upward Compressors.
  Unterhalb LLT: Boost bis zu ll_gain (maximaler Boost an -90 dBFS).
  Gate: Downward Expansion (2:1) — wirkt auf den LL-geboosteten Pegel bei -90 dBFS.
  LLT → HLT: Passthrough (kein Gain-Eingriff).
  Oberhalb HLT: HL-Kompression bis hl_gain bei 0 dBFS.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import logging
import streamlit as st
import threading
import queue
import tempfile
import subprocess

_log = logging.getLogger("rtk")
import time
import json
from pathlib import Path

# ── Preset constants ──────────────────────────────────────────────────────────

_VL_BUILTIN_DIR = Path(__file__).parent / "presets" / "voice_leveler"
_VL_PRESETS_DIR = Path.home() / ".resolve-toolkit" / "voiceleveler_presets"

_VL_DEFAULTS: dict = {
    "gate_threshold": -39.1,
    "gate_enabled":   True,
    "llt":            -31.5,
    "low_level_gain": 17.0,
    "ll_enabled":     True,
    "hlt":            -20.0,
    "high_level_gain": -4.5,
    "hl_enabled":     True,
    "leveler_target": -20.7,
    "leveler_enabled": True,
    "loud_soft":      False,   # False = Soft, True = Loud
    "output_ceiling": -1.5,
}

_VL_PARAM_NAMES: dict = {
    "gate_threshold":  "Gate Threshold",
    "gate_enabled":    "Gate aktiv",
    "llt":             "Low Level Threshold",
    "low_level_gain":  "Low Level Gain",
    "ll_enabled":      "Upward Compressor aktiv",
    "hlt":             "High Level Threshold",
    "high_level_gain": "High Level Gain",
    "hl_enabled":      "HL Compressor aktiv",
    "leveler_target":  "Leveler Target",
    "leveler_enabled": "Leveler aktiv",
    "loud_soft":       "ARC Modus (Loud)",
    "output_ceiling":  "Output Ceiling",
}

# ── Preset helpers ────────────────────────────────────────────────────────────

def _vl_all_presets() -> list[tuple[str, Path, bool]]:
    entries: dict[str, tuple[Path, bool]] = {}
    for d, builtin in [(_VL_BUILTIN_DIR, True), (_VL_PRESETS_DIR, False)]:
        if not d.exists():
            continue
        for f in d.glob("*.json"):
            try:
                data = json.loads(f.read_text())
            except Exception:
                continue
            name = f.stem
            if builtin and not data.get("builtin"):
                continue
            if name not in entries:
                entries[name] = (f, builtin)
    user    = sorted([(n, p, bi) for n, (p, bi) in entries.items() if not bi],
                     key=lambda x: x[0].lower())
    builtin = sorted([(n, p, bi) for n, (p, bi) in entries.items() if bi],
                     key=lambda x: x[0].lower())
    return user + builtin


def _vl_on_preset_change():
    presets = _vl_all_presets()
    if not presets:
        return
    sel_idx = st.session_state.get("vl_preset_selectbox", 0)
    if sel_idx >= len(presets):
        sel_idx = 0
    _, path, _ = presets[sel_idx]
    try:
        data = json.loads(path.read_text())
    except Exception:
        return
    vals = {k: data.get(k, _VL_DEFAULTS[k]) for k in _VL_DEFAULTS}
    st.session_state["_vl_loaded"] = vals
    # Löscht Widget-Keys damit alle Widgets beim nächsten Run mit dem Preset-Wert
    # als value= neu initialisiert werden (statt min_value / False zu zeigen)
    for key in _VL_DEFAULTS:
        st.session_state.pop(f"vl_{key}", None)


# ── Preset dialogs ────────────────────────────────────────────────────────────

@st.dialog("Preset \xfcberschreiben?")
def _vl_confirm_overwrite_preset_dialog():
    name = st.session_state.get("_vl_overwrite_name", "")
    st.write(f"Das Preset **{name}** existiert bereits. Soll es mit den aktuellen Einstellungen \xfcberschrieben werden?")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("\xdcberschreiben", type="primary", use_container_width=True, icon=":material/save:"):
            path = st.session_state.get("_vl_overwrite_path")
            vals = st.session_state.get("_vl_overwrite_values", {})
            if path and vals:
                _VL_PRESETS_DIR.mkdir(parents=True, exist_ok=True)
                Path(path).write_text(json.dumps(vals, indent=2, ensure_ascii=False))
            st.session_state["_pending_toast"] = f'Preset "{name}" gespeichert.'
            st.session_state["_vl_clear_preset_name"] = True
            st.rerun()
    with col2:
        if st.button("Abbrechen", use_container_width=True, icon=":material/close:"):
            st.rerun()


@st.dialog("Preset l\xf6schen")
def _vl_confirm_delete_preset_dialog():
    name = st.session_state.get("_vl_delete_name", "")
    st.write(f"Soll das Preset **{name}** wirklich gel\xf6scht werden?")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("L\xf6schen", type="primary", use_container_width=True, icon=":material/delete:"):
            path = st.session_state.get("_vl_delete_path")
            if path and Path(path).exists():
                Path(path).unlink()
            st.session_state["_pending_toast"] = f'Preset "{name}" gel\xf6scht.'
            st.rerun()
    with col2:
        if st.button("Abbrechen", use_container_width=True, icon=":material/close:"):
            st.rerun()


# ── Preset UI components ──────────────────────────────────────────────────────

def _render_vl_preset_row():
    presets = _vl_all_presets()
    if not presets:
        return
    names = [n for n, _, _ in presets]

    def _fmt(idx):
        _, _, is_builtin = presets[idx]
        return f"{names[idx]} \u25c6" if is_builtin else names[idx]

    col_sel, col_del = st.columns([5, 1])
    with col_sel:
        st.selectbox(
            "Preset", options=list(range(len(presets))),
            format_func=_fmt, key="vl_preset_selectbox",
            on_change=_vl_on_preset_change, label_visibility="collapsed",
        )
        st.caption("\u25c6 = mitgeliefertes Vorlage-Preset (nicht l\xf6schbar)")
        sel_idx_desc = st.session_state.get("vl_preset_selectbox", 0)
        _, _desc_path, _desc_builtin = presets[sel_idx_desc]
        if _desc_builtin:
            try:
                _desc = json.loads(_desc_path.read_text()).get("description", "")
                if _desc:
                    st.caption(_desc)
            except Exception:
                pass
    with col_del:
        st.write("")
        sel_idx = st.session_state.get("vl_preset_selectbox", 0)
        _, del_path, del_builtin = presets[sel_idx]
        if st.button("", icon=":material/delete:", use_container_width=True,
                     key="vl_delete_preset_btn", disabled=del_builtin, help="Preset l\xf6schen"):
            st.session_state["_vl_delete_name"] = names[sel_idx]
            st.session_state["_vl_delete_path"] = str(del_path)
            st.session_state["_vl_delete_active"] = True
    if st.session_state.pop("_vl_delete_active", False):
        _vl_confirm_delete_preset_dialog()


def _render_vl_preset_expander():
    if st.session_state.get("_vl_clear_preset_name"):
        st.session_state.pop("_vl_clear_preset_name")
        st.session_state["vl_preset_name_input"] = ""

    with st.expander("Preset speichern"):
        preset_name = st.text_input("Preset-Name", key="vl_preset_name_input",
                                    placeholder="Mein Preset")
        if st.button("Speichern", icon=":material/save:", type="primary",
                     key="vl_save_preset_btn", disabled=not preset_name.strip()):
            name = preset_name.strip()
            existing = {n.lower(): (p, bi) for n, p, bi in _vl_all_presets()}
            values = {k: st.session_state.get(f"vl_{k}", v) for k, v in _VL_DEFAULTS.items()}
            if name.lower() in existing:
                _, is_bi = existing[name.lower()]
                if is_bi:
                    st.toast(f'"{name}" ist ein eingebautes Preset und kann nicht \xfcberschrieben werden.')
                else:
                    _, ex_path = existing[name.lower()]
                    st.session_state["_vl_overwrite_name"]   = name
                    st.session_state["_vl_overwrite_path"]   = str(ex_path)
                    st.session_state["_vl_overwrite_values"] = values
                    st.session_state["_vl_overwrite_active"] = True
            else:
                _VL_PRESETS_DIR.mkdir(parents=True, exist_ok=True)
                out = _VL_PRESETS_DIR / f"{name}.json"
                out.write_text(json.dumps(values, indent=2, ensure_ascii=False))
                st.session_state["_pending_toast"]         = f'Preset "{name}" gespeichert.'
                st.session_state["_vl_clear_preset_name"] = True
                st.rerun()

    if st.session_state.pop("_vl_overwrite_active", False):
        _vl_confirm_overwrite_preset_dialog()


# ── Page ──────────────────────────────────────────────────────────────────────

st.title(":material/graphic_eq: Voice Leveler")
st.caption("Macht Sprachaufnahmen gleichm\xe4\xdfig laut \u2014 leise Passagen werden angehoben, laute begrenzt.")

if "_pending_toast" in st.session_state:
    st.toast(st.session_state.pop("_pending_toast"))

AUDIO_EXTENSIONS = {".wav", ".mp3", ".aif", ".aiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".r3d", ".braw", ".avi", ".mkv"}

# ── Session state ─────────────────────────────────────────────────────────────

for _k, _v in {"mv_running": False, "mv_log": [], "mv_queue": None}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Signal chain visual ───────────────────────────────────────────────────────

st.caption("**Signal-Kette:** `INPUT` \u2192 `Leveler (AGC)` \u2192 `Compand\u00a0[Gate\u00a0\u00b7\u00a0Upward\u00a0Comp\u00a0\u00b7\u00a0HL\u00a0Comp]` \u2192 `Limiter` \u2192 `OUTPUT`")
st.divider()

# ── Preset row ────────────────────────────────────────────────────────────────

_render_vl_preset_row()

# Beim ersten Seitenaufruf Preset laden
if "_vl_loaded" not in st.session_state:
    _vl_on_preset_change()

_loaded: dict = st.session_state.get("_vl_loaded", _VL_DEFAULTS)

# ── Parameters ────────────────────────────────────────────────────────────────

if "vl_expert_mode" not in st.session_state:
    st.session_state["vl_expert_mode"] = False

_expert = st.session_state["vl_expert_mode"]

# Gate-Konfigurationen für den Einfachmodus (vor Button-Check definiert,
# damit der Handler beim Moduswechsel die Werte übertragen kann)
_GATE_EASY = {
    "Studio":      {"threshold": -39.1, "enabled": True},
    "Lavalier":    {"threshold": -55.0, "enabled": True},
    "Kameramikro": {"threshold": -39.1, "enabled": False},
}

_ph1, _ph2 = st.columns([5, 1])
with _ph1:
    st.subheader("Parameter")
with _ph2:
    st.write("")
    if st.button(
        "Expertenmodus" if not _expert else "Einfachmodus",
        icon=":material/tune:" if not _expert else ":material/close:",
        use_container_width=True,
        key="vl_toggle_expert",
    ):
        if not _expert:
            # Easy → Expert: Radio-Wahl in session_state schreiben, bevor st.rerun()
            # den Easy-Mode-Block überspringt (der diese Werte sonst schreiben würde).
            # Außerdem in Non-Widget-Key sichern, damit der Radio-Button beim
            # Rückwechsel zu Easy korrekt wiederhergestellt werden kann.
            _cur_radio = st.session_state.get("vl_gate_preset", "Studio")
            st.session_state["_vl_gate_preset_saved"] = _cur_radio
            _cur_gp = _GATE_EASY.get(_cur_radio, _GATE_EASY["Studio"])
            st.session_state["vl_gate_threshold"] = _cur_gp["threshold"]
            st.session_state["vl_gate_enabled"]   = _cur_gp["enabled"]
        st.session_state["vl_expert_mode"] = not _expert
        st.rerun()

if not _expert:
    # ── Einfachmodus ──────────────────────────────────────────────────────────
    _ec1, _ec2 = st.columns(2)
    with _ec1:
        leveler_target = st.slider(
            "Leveler Target",
            min_value=-30.0, max_value=-10.0, step=0.5, format="%.1f LUFS",
            value=float(st.session_state.get("vl_leveler_target", _loaded["leveler_target"])),
            help=(
                "Ziel-Lautheit der Ausgabe (EBU R128 Integrated Loudness). "
                "**Podcast / YouTube:** \u221216 LUFS \u00b7 "
                "**Broadcast:** \u221223 LUFS \u00b7 "
                "**Mix-Vorbereitung:** \u221220 LUFS"
            ),
            key="vl_leveler_target",
        )
        leveler_enabled = True
    with _ec2:
        output_ceiling = st.slider(
            "Output Ceiling",
            min_value=-6.0, max_value=-0.5, step=0.5, format="%.1f dBFS",
            value=float(st.session_state.get("vl_output_ceiling", _loaded["output_ceiling"])),
            help=(
                "Maximaler True-Peak-Pegel am Ausgang. "
                "**Direktlieferung:** \u22121.5 dBFS \u00b7 "
                "**Mix-Vorbereitung:** \u22123.0 dBFS"
            ),
            key="vl_output_ceiling",
        )

    if "vl_gate_preset" not in st.session_state:
        # Gespeicherte Auswahl wiederherstellen (falls Streamlit den Widget-State
        # während des Expert-Mode bereinigt hat), sonst "Studio" als Default
        st.session_state["vl_gate_preset"] = st.session_state.get(
            "_vl_gate_preset_saved", "Studio"
        )

    _gate_sel = st.radio(
        "Aufnahmesituation",
        options=list(_GATE_EASY.keys()),
        horizontal=True,
        key="vl_gate_preset",
        help=(
            "**Studio:** Nahbesprechung, niedriges Grundrauschen — Gate bei \u221239 dB. "
            "**Lavalier:** Lavaliermikrofon, moderate Umgebungsgeräusche — Gate bei \u221255 dB. "
            "**Kameramikro:** Integriertes oder weit entferntes Mikrofon — Gate deaktiviert."
        ),
    )
    _gp = _GATE_EASY[_gate_sel]
    gate_threshold = _gp["threshold"]
    gate_enabled   = _gp["enabled"]

    # Restliche Parameter aus _loaded (Preset) oder vorherigem Widget-Wert lesen
    # und in session_state schreiben, damit Expert-Mode-Widgets sie als value= nutzen können
    llt             = st.session_state.get("vl_llt",             _loaded["llt"])
    low_level_gain  = st.session_state.get("vl_low_level_gain",  _loaded["low_level_gain"])
    ll_enabled      = st.session_state.get("vl_ll_enabled",      _loaded["ll_enabled"])
    hlt             = st.session_state.get("vl_hlt",             _loaded["hlt"])
    high_level_gain = st.session_state.get("vl_high_level_gain", _loaded["high_level_gain"])
    hl_enabled      = st.session_state.get("vl_hl_enabled",      _loaded["hl_enabled"])
    loud_soft       = st.session_state.get("vl_loud_soft",       _loaded["loud_soft"])
    # Schreibe alle Werte in session_state damit Expert-Mode-Widgets sie beim ersten Rendern finden
    st.session_state["vl_gate_threshold"]  = gate_threshold
    st.session_state["vl_gate_enabled"]    = gate_enabled
    st.session_state["vl_llt"]             = llt
    st.session_state["vl_low_level_gain"]  = low_level_gain
    st.session_state["vl_ll_enabled"]      = ll_enabled
    st.session_state["vl_hlt"]             = hlt
    st.session_state["vl_high_level_gain"] = high_level_gain
    st.session_state["vl_hl_enabled"]      = hl_enabled
    st.session_state["vl_leveler_enabled"] = leveler_enabled
    st.session_state["vl_loud_soft"]       = loud_soft

else:
    # ── Expertenmodus ─────────────────────────────────────────────────────────
    _col_ll, _col_lev, _col_hl = st.columns(3)

    with _col_ll:
        with st.container(border=True):
            _hc1, _hc2 = st.columns([3, 1])
            with _hc1:
                st.markdown("**Low Level**")
            with _hc2:
                ll_enabled = st.toggle("", key="vl_ll_enabled", label_visibility="collapsed",
                                       value=bool(st.session_state.get("vl_ll_enabled", _loaded["ll_enabled"])),
                                       help="Upward Compressor aktivieren")
            _gc1, _gc2 = st.columns([3, 1])
            with _gc1:
                st.caption("Gate")
            with _gc2:
                gate_enabled = st.toggle("", key="vl_gate_enabled", label_visibility="collapsed",
                                         value=bool(st.session_state.get("vl_gate_enabled", _loaded["gate_enabled"])),
                                         help="Gate aktivieren")
            gate_threshold = st.slider(
                "Gate",
                min_value=-90.0, max_value=-10.0, step=0.5, format="%.1f dB",
                value=float(st.session_state.get("vl_gate_threshold", _loaded["gate_threshold"])),
                help=(
                    "Pegel, unterhalb dem das Gate (Downward Expansion 2:1) einsetzt. "
                    "Signale, die auch nach dem Upward-Boost noch unterhalb dieses Pegels liegen, "
                    "werden abgesenkt. **Default:** \u221239.1 dB"
                ),
                key="vl_gate_threshold", disabled=not gate_enabled,
            )
            llt = st.slider(
                "Low Level Threshold",
                min_value=-50.0, max_value=-10.0, step=0.5, format="%.1f dB",
                value=float(st.session_state.get("vl_llt", _loaded["llt"])),
                help=(
                    "Unity-Decke des Upward Compressors. Bei LLT ist kein Boost aktiv. "
                    "Unterhalb LLT steigt der Boost sanft auf bis zu Low Level Gain an. "
                    "**Default:** \u221231.5 dB"
                ),
                key="vl_llt", disabled=not ll_enabled,
            )
            low_level_gain = st.slider(
                "Low Level Gain",
                min_value=0.0, max_value=48.0, step=0.5, format="+%.1f dB",
                value=float(st.session_state.get("vl_low_level_gain", _loaded["low_level_gain"])),
                help=(
                    "Maximaler Boost, der an der Rauschgrenze (\u221290 dBFS) angewendet wird. "
                    "Je lauter das Signal (Richtung LLT), desto weniger Boost. "
                    "**Default:** +17.0 dB"
                ),
                key="vl_low_level_gain", disabled=not ll_enabled,
            )

    with _col_lev:
        with st.container(border=True):
            _hc1, _hc2 = st.columns([3, 1])
            with _hc1:
                st.markdown("**Leveler (AGC)**")
            with _hc2:
                leveler_enabled = st.toggle("", key="vl_leveler_enabled", label_visibility="collapsed",
                                            value=bool(st.session_state.get("vl_leveler_enabled", _loaded["leveler_enabled"])),
                                            help="Leveler aktivieren")
            leveler_target = st.slider(
                "Target",
                min_value=-30.0, max_value=-10.0, step=0.5, format="%.1f LUFS",
                value=float(st.session_state.get("vl_leveler_target", _loaded["leveler_target"])),
                help=(
                    "Ziel-Integrated-Loudness des AGC-Levelers (EBU R128). "
                    "Wirkt gleichzeitig als Threshold und Target. "
                    "**Default:** \u221220.7 LUFS"
                ),
                key="vl_leveler_target", disabled=not leveler_enabled,
            )
            loud_soft = st.toggle("Loud", key="vl_loud_soft",
                                  value=bool(st.session_state.get("vl_loud_soft", _loaded["loud_soft"])),
                                  help="Loud: kurzes Release (aggressiver). Soft: langes Release (transparenter).")

    with _col_hl:
        with st.container(border=True):
            _hc1, _hc2 = st.columns([3, 1])
            with _hc1:
                st.markdown("**High Level**")
            with _hc2:
                hl_enabled = st.toggle("", key="vl_hl_enabled", label_visibility="collapsed",
                                       value=bool(st.session_state.get("vl_hl_enabled", _loaded["hl_enabled"])),
                                       help="High Level Compressor aktivieren")
            hlt = st.slider(
                "High Level Threshold",
                min_value=-50.0, max_value=-0.5, step=0.5, format="%.1f dB",
                value=float(st.session_state.get("vl_hlt", _loaded["hlt"])),
                help=(
                    "Oberhalb dieses Pegels setzt der Downward Compressor ein. "
                    "Zwischen LLT und HLT: Passthrough (kein Gain-Eingriff). "
                    "**Default:** \u221220.0 dB"
                ),
                key="vl_hlt", disabled=not hl_enabled,
            )
            high_level_gain = st.slider(
                "High Level Gain",
                min_value=-48.0, max_value=0.0, step=0.5, format="%.1f dB",
                value=float(st.session_state.get("vl_high_level_gain", _loaded["high_level_gain"])),
                help=(
                    "Maximale Absenkung bei 0 dBFS (Peak-Ausgang). "
                    "Muss \u2265 HLT sein, sonst invertiert der Kompressor. "
                    "**Default:** \u22124.5 dB"
                ),
                key="vl_high_level_gain", disabled=not hl_enabled,
            )
            output_ceiling = st.slider(
                "Output Ceiling",
                min_value=-6.0, max_value=-0.5, step=0.5, format="%.1f dBFS",
                value=float(st.session_state.get("vl_output_ceiling", _loaded["output_ceiling"])),
                help="True Peak Ceiling f\xfcr Loudnorm und Brickwall-Limiter. **Default:** \u22121.5 dBFS",
                key="vl_output_ceiling",
            )

    # ── Kurven-Warnungen (nur Expertenmodus) ──────────────────────────────────

    if ll_enabled and hl_enabled and llt >= hlt:
        st.warning(
            f":material/warning: **Kurven-Warnung:** LLT ({llt:.1f} dB) muss "
            f"< HLT ({hlt:.1f} dB) sein \u2014 sonst gibt es keine Passthrough-Zone.",
            icon=None,
        )
    if hl_enabled and high_level_gain < hlt:
        st.warning(
            f":material/warning: **Kurven-Warnung:** High Level Gain ({high_level_gain:.1f} dB) "
            f"muss \u2265 HLT ({hlt:.1f} dB) sein \u2014 sonst invertiert der HL-Kompressor.",
            icon=None,
        )
    if ll_enabled and low_level_gain > abs(llt):
        st.info(
            f":material/info: Low Level Gain ({low_level_gain:+.1f} dB) ist gr\xf6\xdfer als "
            f"|LLT| ({abs(llt):.1f} dB) \u2014 Signale nahe LLT k\xf6nnen 0 dBFS \xfcberschreiten. "
            "Der Brickwall-Limiter f\xe4ngt das auf.",
            icon=None,
        )

_render_vl_preset_expander()

# ── Filter chain builder ──────────────────────────────────────────────────────

def _build_filterchain(
    gate_db, gate_on,
    llt_db, ll_gain, ll_on,
    hlt_db, hl_gain_db, hl_on,
    leveler_lufs, leveler_on,
    ceiling_dbfs,
    loud,
):
    """
    Baut die Dynamics-Kette (ohne Loudnorm) und gibt ein Tupel zurück:
      (dynamics_chain, leveler_lufs_or_None, ceiling_dbfs)

    Loudnorm wird als Zwei-Pass in _run_ffmpeg_maxxvolume behandelt —
    dynamics_chain enthält nur compand + alimiter.
    """
    limit_linear = round(min(max(10 ** (ceiling_dbfs / 20), 0.001), 1.0), 6)

    # Build compand points (input_dB/output_dB)
    pts = []

    if ll_on:
        ll_out_at_90 = -90.0 + ll_gain  # LL comp output at -90 dBFS (max boost point)
        if gate_on and ll_out_at_90 < gate_db and gate_db < llt_db:
            # Normal 3-point curve: gate_db is strictly between -90 and llt_db,
            # so input values stay monotone.
            t = (gate_db - (-90.0)) / (llt_db - (-90.0))
            gate_ll_out = round(ll_out_at_90 + t * (llt_db - ll_out_at_90), 1)
            floor_out = round(gate_ll_out + 2.0 * (-90.0 - gate_db), 1)
            pts.append(f"-90/{floor_out}")
            pts.append(f"{gate_db}/{gate_ll_out}")
        elif gate_on and gate_db >= llt_db:
            # Gate threshold is at or above LLT — gate covers the entire LL range.
            # Use 2:1 expansion from llt_db down to -90 (no LL boost possible).
            floor_out = round(llt_db + 2.0 * (-90.0 - llt_db), 1)
            pts.append(f"-90/{floor_out}")
        else:
            # No gate, or LL boost already exceeds gate threshold at -90.
            pts.append(f"-90/{round(ll_out_at_90, 1)}")
        pts.append(f"{llt_db}/{llt_db}")
    elif gate_on:
        # Gate only (no LL comp): 2:1 downward expansion below gate threshold.
        gate_floor = round(gate_db - 2.0 * (gate_db + 90.0), 1)
        pts.append(f"-90/{gate_floor}")
        pts.append(f"{gate_db}/{gate_db}")
    else:
        pts.append("-90/-90")

    if hl_on:
        # Only insert the HLT anchor if it is strictly above LLT — otherwise
        # the input sequence would not be monotone and compand would reject it.
        if hlt_db > llt_db:
            pts.append(f"{hlt_db}/{hlt_db}")
        pts.append(f"0/{hl_gain_db}")
    else:
        pts.append("0/0")

    compand_pts = "|".join(pts)

    # Loud/Soft: affects compand release (decays) time constant
    attacks = 0.02
    decays  = 0.15 if loud else 0.8

    dynamics = ", ".join([
        f"compand=attacks={attacks}:decays={decays}:points={compand_pts}:soft-knee=4",
        f"alimiter=level_in=1:level_out=1:limit={limit_linear}:attack=5:release=50:level=disabled",
    ])

    return dynamics, (leveler_lufs if leveler_on else None), ceiling_dbfs

st.divider()

# ── Source selection ──────────────────────────────────────────────────────────

st.subheader("Quelle")

selected_path_files: list = []
resolve_ctx: dict = {}

_resolve_obj   = None
_resolve_error = None

try:
    from resolve_bridge.connection import get_resolve
    _resolve_obj = get_resolve()
    _project = _resolve_obj.GetProjectManager().GetCurrentProject()
    _mp      = _project.GetMediaPool()
    _root    = _mp.GetRootFolder()
    resolve_ctx["resolve"] = _resolve_obj
    resolve_ctx["project"] = _project
    resolve_ctx["mp"]      = _mp
    resolve_ctx["root"]    = _root
except Exception as e:
    _log.exception("Voice Leveler: Resolve-Initialisierung fehlgeschlagen")
    _resolve_error = str(e)

_resolve_ok = _resolve_obj is not None

_source_opts = (["Resolve Media Pool"] if _resolve_ok else []) + ["Einzeldatei", "Ordner abarbeiten"]

if st.session_state.get("mv_source_mode") not in _source_opts:
    st.session_state["mv_source_mode"] = _source_opts[0]

source_mode = st.radio(
    "Quelle", _source_opts,
    horizontal=True, key="mv_source_mode", label_visibility="collapsed",
)

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

if source_mode == "Resolve Media Pool":
    all_bins = _collect_bins(resolve_ctx["root"])
    if not all_bins:
        st.warning("Keine Bins im Media Pool gefunden.")
    else:
        selected_display = st.selectbox("Media Pool Bin", options=all_bins, key="mv_bin")
        bin_name = selected_display.strip() if selected_display else None
        if bin_name:
            folder = _find_folder(resolve_ctx["root"], bin_name)
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
                        key="mv_clip_select",
                    )
                    selected_path_files = [(n, p) for n, p in audio_clips if n in chosen]
                    resolve_ctx["import_folder"] = folder
                    _n_video = sum(1 for _, p in selected_path_files
                                   if Path(p).suffix.lower() in VIDEO_EXTENSIONS)
                    if _n_video:
                        st.caption(f"\u2139 {_n_video} Videodatei(en) \u2014 Audio (Spur 1) wird via ffmpeg extrahiert.")
                else:
                    st.info("Keine Audio- oder Videodateien in diesem Bin.")

elif source_mode == "Einzeldatei":
    col_fp1, col_fp2 = st.columns([4, 1])
    with col_fp2:
        st.write("")
        if st.button("Durchsuchen", icon=":material/folder_open:", use_container_width=True, key="mv_browse"):
            import subprocess as _sp_dlg
            try:
                _r = _sp_dlg.run(
                    ["osascript", "-e",
                     'POSIX path of (choose file with prompt "Audio- oder Videodatei ausw\xe4hlen")'],
                    capture_output=True, text=True, timeout=60,
                )
                if _r.returncode == 0 and _r.stdout.strip():
                    st.session_state["mv_file_path"] = _r.stdout.strip()
            except Exception:
                pass
    with col_fp1:
        _fp = st.text_input("Dateipfad", key="mv_file_path",
                            placeholder="/Volumes/Media/Interview.mp4")
    if _fp:
        _fp_path = Path(_fp)
        if not _fp_path.exists():
            st.error("Datei nicht gefunden.")
        elif _fp_path.suffix.lower() not in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS:
            st.error(f"Nicht unterst\xfctztes Format: {_fp_path.suffix}")
        else:
            selected_path_files = [(_fp_path.name, str(_fp_path))]
            st.caption(f"1 Datei ausgew\xe4hlt: `{_fp_path.name}`")

elif source_mode == "Ordner abarbeiten":
    col_path, col_browse, col_scan = st.columns([4, 1, 1])
    with col_path:
        folder_path_str = st.text_input("Ordner-Pfad",
                                        placeholder="/Volumes/Media/Recording",
                                        key="mv_folder_path")
    with col_browse:
        st.write("")
        if st.button("W\xe4hlen", icon=":material/folder_open:",
                     use_container_width=True, key="mv_folder_browse"):
            import subprocess as _sp_dlg
            try:
                _r = _sp_dlg.run(
                    ["osascript", "-e",
                     'POSIX path of (choose folder with prompt "Ordner ausw\xe4hlen")'],
                    capture_output=True, text=True, timeout=60,
                )
                if _r.returncode == 0 and _r.stdout.strip():
                    st.session_state["mv_folder_path"] = _r.stdout.strip()
                    st.rerun()
            except Exception:
                pass
    with col_scan:
        st.write("")
        if st.button("Scannen", use_container_width=True, key="mv_scan"):
            p = Path(st.session_state.get("mv_folder_path", "")) \
                if st.session_state.get("mv_folder_path") else None
            if p and p.is_dir():
                found = sorted(
                    (f for f in p.iterdir()
                     if f.suffix.lower() in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS),
                    key=lambda f: f.name,
                )
                st.session_state.mv_scanned = [(f.name, str(f)) for f in found]
            elif p:
                st.error("Ordner nicht gefunden.")
                st.session_state.mv_scanned = []
            else:
                st.warning("Bitte zuerst einen Ordner ausw\xe4hlen.")

    if "mv_scanned" not in st.session_state:
        st.session_state.mv_scanned = []
    if st.session_state.mv_scanned:
        chosen = st.multiselect(
            "Dateien ausw\xe4hlen",
            options=[n for n, _ in st.session_state.mv_scanned],
            default=[n for n, _ in st.session_state.mv_scanned],
            key="mv_folder_select",
        )
        selected_path_files = [(n, p) for n, p in st.session_state.mv_scanned if n in chosen]
        st.caption(f"{len(selected_path_files)} Datei(en) ausgew\xe4hlt")

# ── Processing functions ──────────────────────────────────────────────────────

def _measure_loudness(src_path, leveler_lufs, ceiling_dbfs):
    """
    Erster Pass: Integrierte Lautheit der Quelldatei messen (EBU R128).
    Gibt einen fertigen loudnorm-Filterstring mit gemessenen Werten zurück
    (Zwei-Pass-Modus), oder einen Single-Pass-Fallback bei Fehler.
    """
    _fallback = f"loudnorm=I={leveler_lufs}:TP={ceiling_dbfs}:LRA=9:linear=true"
    try:
        _r = subprocess.run(
            ["ffmpeg", "-i", src_path,
             "-af", f"loudnorm=I={leveler_lufs}:TP={ceiling_dbfs}:LRA=9:print_format=json",
             "-f", "null", "-"],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        # loudnorm schreibt JSON ans Ende von stderr
        _m = None
        for _line in reversed(_r.stderr.splitlines()):
            if _line.strip() == "}":
                # Suche rückwärts nach dem öffnenden {
                _stderr = _r.stderr
                _end = _stderr.rfind("}")
                _start = _stderr.rfind("{", 0, _end)
                if _start >= 0:
                    _m = json.loads(_stderr[_start:_end + 1])
                break
        if not _m:
            return _fallback
        return (
            f"loudnorm=I={leveler_lufs}:TP={ceiling_dbfs}:LRA=9"
            f":measured_I={_m['input_i']}"
            f":measured_TP={_m['input_tp']}"
            f":measured_LRA={_m['input_lra']}"
            f":measured_thresh={_m['input_thresh']}"
            f":linear=true"
        )
    except Exception:
        return _fallback


def _run_ffmpeg_maxxvolume(src_path, out_path, dynamics_chain, leveler_lufs, ceiling_dbfs, q):
    _warmup = 3
    _proc_tmp = tempfile.mktemp(suffix=".wav")
    try:
        # Probe channel count so anullsrc matches the source audio layout.
        _channels = 2
        try:
            _pr = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_streams", src_path],
                capture_output=True, encoding="utf-8", errors="replace",
            )
            for _s in json.loads(_pr.stdout).get("streams", []):
                if _s.get("codec_type") == "audio":
                    _channels = int(_s.get("channels", 2))
                    break
        except Exception:
            pass
        _cl = "mono" if _channels == 1 else "stereo"

        # Zwei-Pass Loudnorm: erst messen, dann mit gemessenen Werten verarbeiten.
        if leveler_lufs is not None:
            q.put("  Lautheit messen (Pass 1) \u2026")
            _loudnorm = _measure_loudness(src_path, leveler_lufs, ceiling_dbfs)
            _filterchain = f"{_loudnorm}, {dynamics_chain}"
        else:
            _filterchain = dynamics_chain

        # Pass 2: filter_complex mit Warmup-Stille + vollständiger Kette.
        # Beide Eingänge werden auf fltp+48kHz+Layout normalisiert vor concat.
        _fc = (
            "[0:a]aformat=sample_fmts=fltp[sil];"
            f"[1:a]aformat=sample_fmts=fltp:sample_rates=48000"
            f":channel_layouts={_cl}[aud];"
            "[sil][aud]concat=n=2:v=0:a=1[cat];"
            f"[cat]{_filterchain}[out]"
        )
        _r1 = subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-t", str(_warmup),
            "-i", f"anullsrc=r=48000:cl={_cl}",
            "-i", src_path,
            "-filter_complex", _fc,
            "-map", "[out]",
            "-ar", "48000", "-acodec", "pcm_s24le", _proc_tmp,
        ], capture_output=True, encoding="utf-8", errors="replace")
        if _r1.returncode != 0:
            raise RuntimeError(_r1.stderr[-300:])

        # Warmup-Stille aus dem Ergebnis herausschneiden.
        _r2 = subprocess.run(
            ["ffmpeg", "-y", "-ss", str(_warmup), "-i", _proc_tmp,
             "-acodec", "copy", out_path],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        if _r2.returncode != 0:
            raise RuntimeError(_r2.stderr[-200:])

        return True

    except RuntimeError as _e:
        q.put(f"  Fehler (ffmpeg): {_e}")
        return False
    finally:
        Path(_proc_tmp).unlink(missing_ok=True)


def _get_audio_frames(wav_path, fps):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", wav_path],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        data = json.loads(r.stdout)
        duration = float(data["streams"][0]["duration"])
        return max(1, int(duration * fps) - 1)
    except Exception:
        return 0


def _process_files(files, dynamics_chain, leveler_lufs, ceiling_dbfs, q, resolve_import=None):
    for name, src_path in files:
        q.put(f"\u25ba {name}")
        src = Path(src_path)
        current = str(src)
        _video_tmp = None
        if src.suffix.lower() in VIDEO_EXTENSIONS:
            q.put("  Audio-Extraktion via ffmpeg \u2026")
            _video_tmp = tempfile.mktemp(suffix=".wav")
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", str(src), "-map", "0:a:0",
                 "-acodec", "pcm_s24le", _video_tmp],
                capture_output=True, encoding="utf-8", errors="replace",
            )
            if r.returncode != 0:
                q.put(f"  Fehler (ffmpeg extract): {r.stderr[-200:]}")
                continue
            current = _video_tmp

        _base = src.parent / f"{src.stem}_vl.wav"
        out_path = _base
        _n = 2
        while out_path.exists():
            out_path = src.parent / f"{src.stem}_vl_{_n}.wav"
            _n += 1
        q.put("  Verarbeite \u2026")
        ok = _run_ffmpeg_maxxvolume(current, str(out_path), dynamics_chain, leveler_lufs, ceiling_dbfs, q)

        if _video_tmp and Path(_video_tmp).exists():
            Path(_video_tmp).unlink()
        if not ok:
            continue

        q.put(f"  \u2713 gespeichert: {out_path.name}")
        if resolve_import and out_path.exists():
            try:
                _mp, _folder = resolve_import
                _mp.SetCurrentFolder(_folder)
                _mp.ImportMedia([str(out_path)])
                q.put("  \u2713 in Resolve importiert")
            except Exception as _e:
                q.put(f"  \u26a0 Resolve-Import fehlgeschlagen: {_e}")
        q.put("")


def _run_all(source_mode, selected_path_files, ctx, dynamics_chain, leveler_lufs, ceiling_dbfs, q):
    try:
        q.put("Starte MaxxVolume-Verarbeitung \u2026\n")
        imp = (ctx["mp"], ctx.get("import_folder")) if ctx.get("import_folder") else None
        _process_files(selected_path_files, dynamics_chain, leveler_lufs, ceiling_dbfs, q, resolve_import=imp)
        q.put("__DONE__0")
    except Exception as e:
        _log.exception("Voice Leveler: Worker-Fehler")
        q.put(f"Fehler: {e}")
        q.put("__DONE__1")

# ── Run ───────────────────────────────────────────────────────────────────────

can_start = bool(selected_path_files) and not st.session_state.mv_running

st.divider()

if st.button("Voice Leveler starten", icon=":material/play_arrow:", type="primary",
             disabled=not can_start, use_container_width=True, key="mv_start"):
    _dynamics, _leveler_lufs, _ceiling = _build_filterchain(
        gate_threshold, gate_enabled,
        llt, low_level_gain, ll_enabled,
        hlt, high_level_gain, hl_enabled,
        leveler_target, leveler_enabled,
        output_ceiling,
        loud_soft,
    )
    st.session_state.mv_running = True
    st.session_state.mv_log     = []
    q = queue.Queue()
    st.session_state.mv_queue = q

    _ctx_snap   = dict(resolve_ctx)
    _mode_snap  = source_mode
    _files_snap = list(selected_path_files)

    threading.Thread(
        target=_run_all,
        args=(_mode_snap, _files_snap, _ctx_snap, _dynamics, _leveler_lufs, _ceiling, q),
        daemon=True,
    ).start()
    st.rerun()

