"""
Dokumentations-Page — Erklärt die Logik hinter den Einstellungen
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pathlib import Path
import streamlit as st

st.title(":material/menu_book: Dokumentation")

_DOCS_DIR   = Path(__file__).parent.parent / "docs"
_ASSETS_DIR = _DOCS_DIR / "assets"


def _section(md_file: str, img_file: str | None = None) -> None:
    """Zeigt optionales Screenshot-Bild, dann den Markdown-Inhalt."""
    if img_file:
        img_path = _ASSETS_DIR / img_file
        if img_path.exists():
            st.image(str(img_path), use_container_width=True)
    md_path = _DOCS_DIR / md_file
    st.markdown(md_path.read_text(encoding="utf-8") if md_path.exists() else "_Datei nicht gefunden._")


tab_multicam, tab_takes, tab_silence = st.tabs(["Multicam Cutter", "Take Selector", "Silence Cutter"])

with tab_multicam:
    st.header("Multicam Cutter")
    st.caption(
        "Erklärt die Logik hinter den Einstellungen des Multicam Cutters — "
        "warum es die Parameter gibt und welches Problem sie lösen."
    )

    with st.expander("Sprecher-Erkennung", expanded=True):
        _section("multicam_sprecher.md", "sprecher-erkennung.png")

    with st.expander("Generelle Schnittregeln"):
        _section("multicam_schnittregeln.md", "schnittregeln.png")

    with st.expander("Cutaway-Regeln (Kopfnicken & Sprachreaktionen)"):
        _section("multicam_cutaways.md", "cutaways.png")

    with st.expander("Totale-Cam Schnittlogik"):
        _section("multicam_totale.md", "totale.png")

    with st.expander("Andere Einstellungen"):
        _section("multicam_andere.md", "andere-einstellungen.png")

with tab_takes:
    st.header("Take Selector")
    st.caption(
        "Erklärt die Erkennungsparameter des Take Selectors — "
        "wie Takes und Sektionen erkannt werden und welche Filter es gibt."
    )
    with st.expander("Whisper-Modell", expanded=True):
        _section("takes.md")

    with st.expander("Inhaltlicher Vergleich"):
        _section("takes_vergleich.md")

with tab_silence:
    st.header("Silence Cutter")
    st.caption(
        "Erklärt wie die Stille-Erkennung funktioniert und was die einzelnen "
        "Parameter bewirken."
    )

    with st.expander("Funktionsweise & Einstellungen", expanded=True):
        _section("silence.md")
