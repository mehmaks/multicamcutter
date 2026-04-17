# resolve-toolkit — Installation

Geschätzte Zeit: **15–25 Minuten** (davon ~10–20 Min. automatischer Download)

Alle Schritte laufen im **Terminal**. Du findest das Terminal über Spotlight: **Cmd + Leertaste**, dann „Terminal" eintippen und Enter drücken.

---

## Was du brauchst

- Einen Mac (Apple Silicon empfohlen — M1/M2/M3/M4)
- macOS 13 oder neuer
- Eine Internetverbindung
- Ca. 5 GB freier Speicherplatz

---

## Schritt 1 — Bootstrap ausführen

Das Bootstrap-Script installiert automatisch alle Voraussetzungen (Homebrew, Python 3.12, Git) und lädt das resolve-toolkit herunter.

Diesen Befehl ins Terminal kopieren und mit **Enter** bestätigen:

```
bash <(curl -fsSL "https://tinyurl.com/22hf2vgx")
```

Was während des Scripts passiert:

1. **Homebrew** wird installiert — dein Mac-Passwort wird abgefragt (Eingabe unsichtbar)
2. Falls ein Systemdialog **„Xcode Command Line Tools installieren"** erscheint: auf „Installieren" klicken und warten — das Script läuft danach automatisch weiter
3. **Python 3.12** und **Git** werden installiert
4. Das **resolve-toolkit** wird heruntergeladen

Am Ende erscheint eine Zusammenfassung mit dem nächsten Schritt.

---

## Schritt 2 — Setup ausführen

```
bash ~/resolve-toolkit/setup.sh
```

Das Script läuft automatisch durch und installiert alle weiteren Abhängigkeiten (KI-Modelle, Python-Pakete, Fonts). Es dauert **10–20 Minuten**. Am Ende erscheint: `Setup abgeschlossen!`

---

## Schritt 3 — Tool starten

```
bash ~/resolve-toolkit/start.command
```

Der Browser öffnet sich automatisch mit der Oberfläche des Tools.

Alternativ: **Doppelklick** auf `start.command` im Ordner `~/resolve-toolkit`.  
Falls ein Sicherheitshinweis erscheint: **Rechtsklick → „Öffnen" → „Öffnen"**.

> Das Terminal-Fenster offen lassen — es läuft im Hintergrund. Schließen beendet das Tool.

---

## Schritt 4 — Lizenz aktivieren

Nach dem ersten Start öffnet sich die **Lizenz-Seite** automatisch, da noch keine Lizenz vorhanden ist.

1. Klicke auf **„Lizenzdatei auswählen …"**
2. Wähle die `license.json` aus, die du von uns erhalten hast
3. Die Lizenz wird sofort aktiviert und das Tool ist einsatzbereit

---

## Hinweise

**Tool erneut starten:** Immer über `bash ~/resolve-toolkit/start.command` oder Doppelklick auf `start.command`.

**Tool beenden:** Terminal-Fenster schließen oder `Ctrl + C` im Terminal drücken.

---

## Probleme?

Nutze den **Feedback-Button** direkt im Tool (linke Sidebar) — oder schreib uns eine E-Mail.
