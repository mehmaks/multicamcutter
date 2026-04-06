"""
Config Editor — config.ini direkt bearbeiten.

# TODO: Settings-Page bauen mit Slidern und Checkboxen für alle config.ini-Werte,
#       damit Parameter ohne Texteditor zugänglich sind (UX-Verbesserung).
"""

import streamlit as st
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent.parent / "modules" / "multicam_cutter" / "config.ini"

st.title("⚙️ Config Editor")
st.caption(f"`{CONFIG_PATH}`")

if not CONFIG_PATH.exists():
    st.error(f"config.ini nicht gefunden: {CONFIG_PATH}")
    st.stop()

# ── Load ──────────────────────────────────────────────────────────────────────

if "config_text" not in st.session_state:
    st.session_state.config_text = CONFIG_PATH.read_text()

col_save, col_reload = st.columns([1, 5])

with col_save:
    save = st.button("💾 Speichern", type="primary", use_container_width=True)
with col_reload:
    if st.button("↺ Neu laden", use_container_width=True):
        st.session_state.config_text = CONFIG_PATH.read_text(encoding='utf-8')
        st.rerun()

edited = st.text_area(
    label="config.ini",
    value=st.session_state.config_text,
    height=600,
    label_visibility="collapsed",
)

if save:
    CONFIG_PATH.write_text(edited, encoding='utf-8')
    st.session_state.config_text = edited
    st.success("Gespeichert.")
