# resolve-toolkit — Installation

Geschätzte Zeit: **15–30 Minuten** (davon ~10–20 Min. automatischer Download)

---

## Was du brauchst

- Einen Mac (Apple Silicon empfohlen — M1/M2/M3/M4)
- macOS 13 oder neuer
- Eine Internetverbindung für die Installation
- Ca. 5 GB freier Speicherplatz

---

## Schritt 1 — Python installieren

1. Gehe auf **https://www.python.org/downloads/**
2. Klicke auf den großen gelben „Download Python"-Button
3. Öffne die heruntergeladene Datei und folge dem Installationsassistenten

> Falls du dir nicht sicher bist ob Python bereits installiert ist: Terminal öffnen (Spotlight → „Terminal"), `python3 --version` eintippen und Enter drücken. Erscheint eine Versionsnummer ≥ 3.10, kannst du diesen Schritt überspringen.

---

## Schritt 2 — Repo herunterladen

1. Gehe auf die GitHub-Seite des Projekts
2. Klicke auf den grünen **„Code"**-Button → **„Download ZIP"**
3. Entpacke die ZIP-Datei (Doppelklick)
4. Verschiebe den entpackten Ordner an einen festen Ort, z.B. in deinen **Dokumente**-Ordner

> Den Ordner danach **nicht mehr verschieben** — die Installation ist an diesen Pfad gebunden.

---

## Schritt 3 — Setup ausführen

1. Öffne den Projektordner
2. Mache einen **Rechtsklick** auf die Datei `setup.sh` → **„Öffnen mit" → „Terminal"**
   - Falls ein Sicherheitshinweis erscheint: **„Trotzdem öffnen"** klicken
3. Das Terminal öffnet sich und läuft automatisch durch — das dauert **10–20 Minuten**
4. Am Ende erscheint: `Setup abgeschlossen!`

Das Script installiert alle nötigen Bibliotheken und lädt die KI-Modelle herunter.

---

## Schritt 4 — Lizenz eintragen

Du hast von uns eine Datei namens `license.json` erhalten.

1. Öffne den Finder
2. Drücke **Cmd + Shift + G** und gib ein: `~/.resolve-toolkit`
3. Lege die `license.json` in diesen Ordner (vorhandene Datei ersetzen)

---

## Schritt 5 — Tool starten

1. Mache einen **Doppelklick** auf `start.command` im Projektordner
   - Falls ein Sicherheitshinweis erscheint: **Rechtsklick → „Öffnen" → „Öffnen"**
2. Ein Terminal-Fenster öffnet sich, der Browser startet automatisch
3. Das Tool ist bereit

> Das Terminal-Fenster offen lassen — es läuft im Hintergrund. Schließen beendet das Tool.

---

## Hinweise

**Beim ersten Audio-Enhance-Lauf** lädt das Tool einmalig ein ~500 MB großes KI-Modell von Hugging Face herunter. Das passiert nur einmal und dauert je nach Internetverbindung einige Minuten.

**Tool beenden:** Terminal-Fenster schließen oder `Ctrl + C` im Terminal drücken.

**Tool erneut starten:** Immer per Doppelklick auf `start.command`.

---

## Probleme?

Nutze den **Feedback-Button** direkt im Tool (linke Sidebar) — oder schreib uns eine E-Mail.
