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

## Schritt 1 — Homebrew installieren

Homebrew ist ein Programm, das andere Programme für den Mac installiert. Falls du es bereits hast, kannst du diesen Schritt überspringen.

Diesen Befehl ins Terminal kopieren und mit **Enter** bestätigen:

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Das Passwort deines Macs wird abgefragt (die Eingabe ist unsichtbar — einfach tippen und Enter drücken). Die Installation dauert einige Minuten.

> **Apple Silicon (M1/M2/M3/M4):** Nach der Installation erscheint ein Hinweis, zwei weitere Befehle auszuführen (`eval "$(/opt/homebrew/bin/brew shellenv)"`). Diese bitte ausführen, bevor du weitermachst.

---

## Schritt 2 — Python und Git installieren

```
brew install python@3.12 git
```

---

## Schritt 3 — Projekt herunterladen

```
git clone https://github.com/mehmaks/resolve-toolkit.git ~/resolve-toolkit
```

Der Projektordner landet in deinem Benutzerordner unter `resolve-toolkit`.

---

## Schritt 4 — Setup ausführen

```
bash ~/resolve-toolkit/setup.sh
```

Das Script läuft automatisch durch und installiert alles Nötige. Es dauert **10–20 Minuten**. Am Ende erscheint: `Setup abgeschlossen!`

---

## Schritt 5 — Lizenz eintragen

Du hast von uns eine Datei namens `license.json` erhalten.

1. Öffne den Finder
2. Drücke **Cmd + Shift + G** und gib ein: `~/.resolve-toolkit`
3. Lege die `license.json` in diesen Ordner (vorhandene Datei ersetzen)

---

## Schritt 6 — Tool starten

```
bash ~/resolve-toolkit/start.command
```

Der Browser öffnet sich automatisch mit der Oberfläche des Tools.

Alternativ: **Doppelklick** auf `start.command` im Ordner `~/resolve-toolkit`.
Falls ein Sicherheitshinweis erscheint: **Rechtsklick → „Öffnen" → „Öffnen"**.

> Das Terminal-Fenster offen lassen — es läuft im Hintergrund. Schließen beendet das Tool.

---

## Hinweise

**Tool erneut starten:** Immer über `bash ~/resolve-toolkit/start.command` oder Doppelklick auf `start.command`.

**Tool beenden:** Terminal-Fenster schließen oder `Ctrl + C` im Terminal drücken.

---

## Probleme?

Nutze den **Feedback-Button** direkt im Tool (linke Sidebar) — oder schreib uns eine E-Mail.
