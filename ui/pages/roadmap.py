import streamlit as st

st.header("Roadmap")
st.markdown(
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
- **Stille-Trimming an Sprecherwechsel-Schnitten** — Stille am Ende des ausgehenden und am Anfang des eingehenden Segments automatisch herausschneiden.
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

st.subheader("KI-Pipeline")
st.markdown(
    """
- **Klappenerkennung** — Automatische Erkennung von Filmklappen: Audio-Transient (librosa) + visuelle Bestätigung (CLIP Zero-Shot) + Texterkennung (Claude Vision API).
- **KI-Metadaten-Pipeline** — Claude Vision + Whisper für automatische Clip-Analyse. Architektur entschieden, noch nichts gebaut.
"""
)

st.subheader("Allgemein / UI")
st.markdown(
    """
- **Zentrales App-Log für Bugreports** — Persistenter, modulübergreifender Rolling-File-Logger (`~/.resolve-toolkit/app.log`).
- **Log-Zeitstempel** — Jedem Log-Eintrag einen Zeitstempel voranstellen (z.B. `[10:14:32]`).
- **Log-Console UX** — Scrollbare Console mit fixer Höhe + optionaler "Konsole maximieren"-Button.
- **Projektabhängige Parameter-Saves** — Slider-Werte je Resolve-Projekt in einer JSON-Datei speichern.
- **Settings-Page** — Enhance, Silence und Auphonic haben noch keine eigene Settings-UI (nur Rohtexteditor).
- **Mehrsprachigkeit** — Zentrale String-Datei + Sprachauswahl in der Sidebar für englischsprachige Nutzer.
"""
)

st.subheader("Lizenzierung")
st.markdown(
    """
- **Online-Validierung mit Backend** — FastAPI auf VPS oder Supabase mit Lizenz-DB, Stripe/Lemon Squeezy Zahlungsintegration, Gerätebindung per MAC-Adresse.
"""
)
