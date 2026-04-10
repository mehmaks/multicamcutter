"""
Config — Tab-Sichtbarkeit und config.ini Editor.
"""

import streamlit as st
import configparser
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent.parent / "modules" / "multicam_cutter" / "config.ini"

st.title("⚙️ Config")

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

# ── Tab-Sichtbarkeit ──────────────────────────────────────────────────────────

st.subheader("Tabs")
st.caption("Deaktivierte Tabs werden in der Sidebar nicht angezeigt.")

_TABS = [
    ("show_multicam", "✂️  Multicam Cutter"),
    ("show_enhance",  "🎙️  Audio Enhance"),
    ("show_auphonic",    "☁️  Auphonic"),
    ("show_maxxvolume", "📢  MaxxVolume"),
    ("show_silence",    "🔇  Silence Cutter"),
    ("show_resolve",  "🔗  Resolve Bridge"),
    ("show_takes",    "🎬  Take Selector"),
]

cfg = _load_cfg()
if not cfg.has_section("UI"):
    cfg.add_section("UI")

changed = False
for key, label in _TABS:
    current = cfg.getboolean("UI", key, fallback=True)
    new_val = st.checkbox(label, value=current, key=f"tabvis_{key}")
    if new_val != current:
        cfg.set("UI", key, "true" if new_val else "false")
        changed = True

if changed:
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
    save = st.button("💾 Speichern", type="primary", use_container_width=True)
with col_reload:
    if st.button("↺ Neu laden", use_container_width=True):
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
