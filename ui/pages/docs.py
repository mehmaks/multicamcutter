"""
Dokumentations-Page — Erklärt die Logik hinter den Einstellungen
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pathlib import Path
import streamlit as st

st.title(":material/menu_book: Dokumentation")

_TOML_PATH_DOCS = Path(__file__).parent.parent.parent / ".streamlit" / "config.toml"
_is_dark_docs = 'mode = "dark"' in (
    _TOML_PATH_DOCS.read_text(encoding="utf-8") if _TOML_PATH_DOCS.exists() else ""
)

if _is_dark_docs:
    st.markdown(
        """
        <style>
        [data-testid="stImage"] img {
            filter: invert(1) hue-rotate(180deg);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

_REPO_ROOT  = Path(__file__).parent.parent.parent
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


tab_multicam, tab_takes, tab_silence, tab_vl = st.tabs(["Multicam Cutter", "Take Selector", "Silence Cutter", "Voice Leveler"])

with tab_multicam:
    st.header("Multicam Cutter")

    _anleitung_path = _REPO_ROOT / "modules" / "multicam_cutter" / "Multicam_Cutter_Anleitung.md"
    st.markdown(
        "Der Multicam Cutter erstellt automatisch einen Rohschnitt aus deiner "
        "Podcast-Aufnahme. Er erkennt, wer spricht, schneidet zwischen den Kameras "
        "— und fügt Reaktions-Cutaways ein, wenn die andere Person nickt oder etwas einwirft.\n\n"
        "Das Ergebnis ist ein Vorschlag, kein Fertigschnitt. Du kannst danach in "
        "deinem Schnittprogramm alles nachjustieren."
    )

    _workflow_img = _ASSETS_DIR / "multicam-cutter_diagram.png"
    if _workflow_img.exists():
        st.markdown("<div style='margin: 1.5rem 0;'>", unsafe_allow_html=True)
        _col_l, _col_img, _col_r = st.columns([0.15, 0.7, 0.15])
        with _col_img:
            st.image(str(_workflow_img), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Kurzanleitung", expanded=True):
        st.markdown(_anleitung_path.read_text(encoding="utf-8") if _anleitung_path.exists() else "_Datei nicht gefunden._")

    with st.expander("Sprecher-Erkennung"):
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
    st.markdown(
        "Der Take Selector analysiert geskriptete Aufnahmen — Clips, in denen ein Text "
        "mehrfach aufgenommen wurde — und wählt automatisch den besten Take pro Abschnitt aus.\n\n"
        "Er erkennt, wo neue Versuche beginnen, gruppiert zusammengehörige Takes und schlägt "
        "jeweils den letzten vollständigen Take vor. Die Auswahl kann manuell überschrieben werden."
    )

    _takes_img = _ASSETS_DIR / "takeselector_diagram.png"
    if _takes_img.exists():
        st.markdown("<div style='margin: 1.5rem 0;'>", unsafe_allow_html=True)
        _col_tl, _col_timg, _col_tr = st.columns([0.15, 0.7, 0.15])
        with _col_timg:
            st.image(str(_takes_img), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Whisper-Modell", expanded=True):
        _section("takes.md", "takeselector_erkennung.png")

    with st.expander("Inhaltlicher Vergleich"):
        _section("takes_vergleich.md")

with tab_vl:
    st.header("Voice Leveler")
    st.markdown(
        "Der Voice Leveler bringt Sprachaufnahmen auf einen konsistenten, sendefähigen Pegel "
        "— leise Passagen werden angehoben, laute kontrolliert, Rauschen zwischen Sätzen abgesenkt."
    )

    _vl_img = _ASSETS_DIR / "voiceleveler_diagram.png"
    if _vl_img.exists():
        st.markdown("<div style='margin: 1.5rem 0;'>", unsafe_allow_html=True)
        _col_vl, _col_vimg, _col_vr = st.columns([0.15, 0.7, 0.15])
        with _col_vimg:
            st.image(str(_vl_img), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Einstellungen (Einfachmodus)", expanded=True):
        _section("voice_leveler_easy.md")

    with st.expander("Einstellungen (Expertenmodus)"):
        _section("voice_leveler.md", "voiceleveler_settings.png")

with tab_silence:
    st.header("Silence Cutter")
    st.markdown(
        "Der Silence Cutter erkennt stille Passagen in Audioaufnahmen und entfernt sie automatisch "
        "aus der Timeline — ideal für Interviews, Podcasts oder Voice-Over, bei denen lange Pausen "
        "den Schnitt aufblähen."
    )

    _silence_img = _ASSETS_DIR / "silencecutter_diagram.png"
    if _silence_img.exists():
        st.markdown("<div style='margin: 1.5rem 0;'>", unsafe_allow_html=True)
        _col_sl, _col_simg, _col_sr = st.columns([0.15, 0.7, 0.15])
        with _col_simg:
            st.image(str(_silence_img), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Funktionsweise & Einstellungen", expanded=True):
        _section("silence.md", "silencecutter_settings.png")
