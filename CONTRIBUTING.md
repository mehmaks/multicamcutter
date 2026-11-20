# Mitmachen / Contributing

Danke, dass du MultiCamCutter verbessern willst! *Thanks for helping – English is fine everywhere.*

## Fehler melden und Ideen

- Am einfachsten direkt aus der App: **Hilfe → Fehler melden** (hängt auf Wunsch das Log an).
- Oder als [Issue](../../issues) hier im Repo. Hilfreich sind: App-Version, was du erwartet
  hast, was passiert ist, und – bei Schnittfehlern – der Timecode der Stelle.
- Bitte keine Mediendateien oder Namen von Gästen anhängen.

## Code beitragen

1. Repo forken, einen Branch von **`beta`** anlegen (z. B. `fix/pausen-trimming`).
2. Änderung machen, App bauen (`swift build`) und an einer echten Aufnahme testen.
3. Pull Request gegen **`beta`** öffnen und kurz beschreiben: *was* ändert sich für Nutzer,
   und *wie* hast du es geprüft.

`main` bekommt nur fertige, veröffentlichte Stände (aus `beta` übernommen).

## Worauf wir achten

- **Schnitt-Ergebnisse:** Änderungen an der Schnittlogik bitte mit einem Vorher/Nachher an
  echtem Material belegen (Anzahl Cutaways, Timecodes von Problemstellen).
- **Ton und Bild bleiben synchron.** Der Engine-Log zeigt dazu am Ende `SYNC-CHECK … Diff=0`.
- **AAF-Struktur nicht ohne Grund umbauen** – Premiere und Resolve sind dort empfindlich
  (siehe `apps/multicam-cutter/brain/AAF-Struktur.md`).
- **Neue Abhängigkeiten** (Python-Pakete, Modelle, Frameworks) bitte vorher in einem Issue
  ansprechen.
- Texte in der App: einfach und ohne Fachjargon; neue Texte auf Englisch im Code und mit
  deutscher Übersetzung in `Localization/de.lproj/Localizable.strings`.
- Kommentare und Entwickler-Notizen sind überwiegend Deutsch – Englisch ist genauso willkommen.

## Lizenz

Mit einem Beitrag stimmst du zu, dass er unter der GPL-3.0 (siehe `LICENSE`) veröffentlicht wird.
