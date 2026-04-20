import streamlit as st

st.title("Roadmap")
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
- **Easy/Advanced-Mode** — Easy-Mode zeigt nur die 4–5 wichtigsten Parameter; Advanced-Mode alle aktuellen Einstellungen, per Button umschaltbar.
- **DeepFilterNet Audio-Enhancement** — MIC-WAVs vor der RMS-Analyse durch DeepFilterNet laufen lassen, um Rauschen und Hall zu reduzieren.
- **Speaker-Profil-basierter Crossbleed-Filter** — Persistentes Sprecher-Embedding für den Moderator zur Crossbleed-Erkennung auf dem Off-Mic.
- **CLIP/LLM-basierte Custom Reaktionserkennung** — Nutzerdefinierte Trigger- und Ignore-Listen, erkannt per CLIP und optionaler LLM-Validierung.
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
