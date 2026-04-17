"""
Config — Tab-Sichtbarkeit und config.ini Editor.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import configparser
import license as _lic
from pathlib import Path
from streamlit_sortables import sort_items

CONFIG_PATH = Path(__file__).parent.parent.parent / "modules" / "multicam_cutter" / "config.ini"

st.title(":material/settings: Config")

if not CONFIG_PATH.exists():
    st.error(f"config.ini nicht gefunden: {CONFIG_PATH}")
    st.stop()

def _load_cfg() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")
    return cfg

def _save_cfg(cfg: configparser.ConfigParser):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        cfg.write(f)

_license: _lic.LicenseInfo = st.session_state.get("license_info") or _lic.validate()

# ── Tab-Sichtbarkeit ──────────────────────────────────────────────────────────

st.subheader("Tabs")
st.caption("Reihenfolge per Drag & Drop ändern. In **Aktiviert** = in der Sidebar sichtbar.")

# Nur lizenzierte Module anzeigen
_ALL_MODULES_DEFS = [
    ("show_multicam",   "Multicam Cutter", "multicam"),
    ("show_enhance",    "Audio Enhance",   "enhance"),
    ("show_auphonic",   "Auphonic",        "auphonic"),
    ("show_maxxvolume", "Voice Leveler",   "maxxvolume"),
    ("show_silence",    "Silence Cutter",  "silence"),
    ("show_takes",      "Take Selector",   "takes"),
]
_ALL_MODULES = [(k, label) for k, label, mod in _ALL_MODULES_DEFS if _license.has_module(mod)]
_KEY_TO_LABEL = dict(_ALL_MODULES)
_LABEL_TO_KEY = {v: k for k, v in _ALL_MODULES}
_DEFAULT_ORDER = [k for k, _ in _ALL_MODULES]

cfg = _load_cfg()
if not cfg.has_section("UI"):
    cfg.add_section("UI")

# Gespeicherte Reihenfolge laden (alle Module, aktiv + inaktiv)
_order_raw = cfg.get("UI", "module_order", fallback="")
if _order_raw:
    _saved_order = [k.strip() for k in _order_raw.split(",") if k.strip() in _KEY_TO_LABEL]
    for k in _DEFAULT_ORDER:
        if k not in _saved_order:
            _saved_order.append(k)
else:
    _saved_order = list(_DEFAULT_ORDER)

_enabled_labels  = [_KEY_TO_LABEL[k] for k in _saved_order
                    if cfg.getboolean("UI", k, fallback=True)]
_disabled_labels = [_KEY_TO_LABEL[k] for k in _saved_order
                    if not cfg.getboolean("UI", k, fallback=True)]

_result = sort_items(
    [
        {"header": "Aktiviert",   "items": _enabled_labels},
        {"header": "Deaktiviert", "items": _disabled_labels},
    ],
    multi_containers=True,
)

_new_enabled_labels  = _result[0]["items"]
_new_disabled_labels = _result[1]["items"]
_new_enabled_keys    = {_LABEL_TO_KEY[l] for l in _new_enabled_labels}
_new_order           = [_LABEL_TO_KEY[l] for l in _new_enabled_labels + _new_disabled_labels]

_changed = False

if _new_order != _saved_order:
    cfg.set("UI", "module_order", ",".join(_new_order))
    _changed = True

for k in _DEFAULT_ORDER:
    _old = cfg.getboolean("UI", k, fallback=True)
    _new = k in _new_enabled_keys
    if _old != _new:
        cfg.set("UI", k, "true" if _new else "false")
        _changed = True

if _changed:
    _save_cfg(cfg)
    st.rerun()

st.divider()

# ── Config.ini Editor ─────────────────────────────────────────────────────────

st.subheader("config.ini")
st.caption(f"`{CONFIG_PATH}`")

if "config_text" not in st.session_state:
    st.session_state.config_text = CONFIG_PATH.read_text(encoding="utf-8")

col_save, col_reload = st.columns([1, 5])

with col_save:
    save = st.button("Speichern", icon=":material/save:", type="primary", use_container_width=True)
with col_reload:
    if st.button("Neu laden", icon=":material/refresh:", use_container_width=True):
        st.session_state.config_text = CONFIG_PATH.read_text(encoding="utf-8")
        st.rerun()

edited = st.text_area(
    label="config.ini",
    value=st.session_state.config_text,
    height=600,
    label_visibility="collapsed",
)

if save:
    CONFIG_PATH.write_text(edited, encoding="utf-8")
    st.session_state.config_text = edited
    st.success("Gespeichert.")
