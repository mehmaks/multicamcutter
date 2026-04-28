import streamlit as st
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_VERSION_FILE = _ROOT / "VERSION"
_CHANGELOG_FILE = _ROOT / "CHANGELOG.md"
_current_version = _VERSION_FILE.read_text().strip() if _VERSION_FILE.is_file() else ""

st.title("Roadmap & Changelog")

tab_roadmap, tab_changelog = st.tabs(["Roadmap", "Changelog"])

# ── Roadmap ──────────────────────────────────────────────────────────────────

with tab_roadmap:
    st.caption(
        "Geplante Features und offene Punkte — geordnet nach Modul bzw. Bereich."
    )

    st.subheader("Voice Leveler")
    st.markdown(
        """
- **Eigener Python DSP Prozessor** — Unabhängige Gain-Stufen wie MaxxVolume (Gate, LL Upward Comp, HL Comp) in numpy/scipy, um die strukturelle Einschränkung des ffmpeg-Compand aufzuheben.
"""
    )

    st.subheader("Take Selector")
    st.markdown(
        """
- **Suffix-Verknüpfung** — Sprecherin geht nach Skript (ABCD) und setzt bei einem mittleren Absatz neu an (CD). Die CD-Neueinsätze sollen den hinteren Teil des Basis-Takes ersetzen: `ABCD_bis_Schnitt + best_CD`.
"""
    )

    st.subheader("Silence Cutter")
    st.markdown(
        """
- **Dynamischer Schwellwert** — Quelldatei in X gleiche Abschnitte unterteilen und pro Abschnitt einen eigenen Schwellwert ermitteln (k-means oder Whisper). Passt sich automatisch an AGC-Pumpern und wechselnden Aufnahmebedingungen an. Offene Fragen: Mindest-Segmentlänge (≥ 60 s), Fallback bei unzuverlässigem Segment (Fisher-Score zu niedrig), UI-Konzept (Slider „Segmente" vs. automatisch). Alternative: gleitende RMS-Baseline.
"""
    )

    st.subheader("Multicam Cutter")
    st.markdown(
        """
- **Totale bei Max. Shotlänge — Toggle** — Wenn aktiv, wird nach Erreichen der Max. Shotlänge immer auf die Totale geschnitten statt auf eine zufällige Kamera.
- **Multi-Gäste-Schnittlogik bei >2 Mikrofonen** — Fallback-Logik für "alle reden gleichzeitig" und "niemand redet"-Segmente.
- **DeepFilterNet Audio-Enhancement** — MIC-WAVs vor der RMS-Analyse durch DeepFilterNet laufen lassen, um Rauschen und Hall zu reduzieren.
- **Speaker-Profil-basierter Crossbleed-Filter** — Persistentes Sprecher-Embedding für den Moderator zur Crossbleed-Erkennung auf dem Off-Mic.
- **LLM-basierte Custom Reaktionserkennung** — Nutzerdefinierte Trigger-Listen per optionaler LLM-Validierung zusätzlich zum bestehenden CLIP-Filter.
"""
    )

    st.subheader("Audio / Enhance")
    st.markdown(
        """
- **Audio-Spur-Auswahl im Enhance-Workflow** — Auswahl der Audiospur per Dropdown statt hardcoded Spur 0.
"""
    )

    st.subheader("Allgemein / UI")
    st.markdown(
        """
- **Projektabhängige Parameter-Saves** — Slider-Werte je Resolve-Projekt in einer JSON-Datei speichern.
- **Mehrsprachigkeit** — Zentrale String-Datei + Sprachauswahl in der Sidebar für englischsprachige Nutzer.
"""
    )

    st.subheader("Cloud-Analyse")
    st.markdown(
        """
- **Server-seitige Multicam-Analyse** — Lokale Proxy-Erstellung (640px H.264, ~300 MB/Kamera statt 120 GB), Upload zum Server, parallele Nodding-Analyse aller Kameras gleichzeitig, AAF-Download. Drastisch schnellere Analyse für Nutzer mit schwacher Hardware.
- **Freemium-Modell** — Lokale Nutzung kostenfrei oder einmalige Lizenz; Cloud-Computing als Abo oder nutzungsbasierte Abrechnung.
"""
    )

    st.subheader("Lizenzierung")
    st.markdown(
        """
- **Online-Validierung mit Backend** — FastAPI auf VPS oder Supabase mit Lizenz-DB, Stripe/Lemon Squeezy Zahlungsintegration, Gerätebindung per MAC-Adresse.
"""
    )

# ── Changelog ────────────────────────────────────────────────────────────────

def _parse_changelog(text: str) -> list[dict]:
    """Parst CHANGELOG.md in eine Liste von Release-Dicts."""
    releases = []
    # Spalte an "## vX.Y.Z" Headern
    parts = re.split(r'^## (v\S+.*)', text, flags=re.MULTILINE)
    # parts[0] = alles vor dem ersten Release (Titel etc.)
    # danach paarweise: [header, body, header, body, ...]
    for i in range(1, len(parts), 2):
        header = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ''
        # Tag und optionales Datum/Name aus Header extrahieren
        m = re.match(r'(v[\d.]+)(?:\s*[—–-]\s*(.+?))?\s*(?:\((\d{4}-\d{2}-\d{2})\))?$', header)
        if m:
            tag = m.group(1)
            name = m.group(2) or ''
            date = m.group(3) or ''
        else:
            tag = header.split()[0] if header else header
            name = ''
            date = ''
        # Body bereinigen: führendes "## Titel" entfernen (Duplikat aus Release Notes)
        body = re.sub(r'^## .+\n*', '', body, count=1).strip()
        # Trailing "---" entfernen
        body = re.sub(r'\n---\s*$', '', body).strip()
        releases.append({'tag': tag, 'name': name, 'date': date, 'body': body})
    return releases

with tab_changelog:
    st.caption("Release Notes — neueste zuerst.")

    if _CHANGELOG_FILE.is_file():
        releases = _parse_changelog(_CHANGELOG_FILE.read_text(encoding='utf-8'))
        if not releases:
            st.info("Keine Einträge in CHANGELOG.md gefunden.")
        else:
            for rel in releases:
                label = f"**{rel['tag']}**"
                if rel['name']:
                    label += f" — {rel['name']}"
                if rel['tag'] == _current_version:
                    label += "  `aktuell`"
                if rel['date']:
                    label += f"  ({rel['date']})"

                with st.expander(label, expanded=(rel['tag'] == _current_version)):
                    if rel['body']:
                        st.markdown(rel['body'])
                    else:
                        st.caption("Keine Release Notes vorhanden.")
    else:
        st.info("Keine CHANGELOG.md gefunden.")
