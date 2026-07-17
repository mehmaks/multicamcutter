# Distribution-Setup

Wie aus der gebauten App eine verteilbare Datei wird — von der jetzigen
ad-hoc-DMG bis zur signierten/notarisierten Auslieferung.

## Versionierung (build_app.sh)

| Feld | Herkunft | Regel |
|------|----------|-------|
| `CFBundleShortVersionString` | Variable `MARKETING_VERSION` in build_app.sh | **Per Hand** hochziehen — wann 0.2.0 → 0.3.0 wird, ist eine Produktentscheidung |
| `CFBundleVersion` | `date -u +%Y%m%d%H%M` | Automatisch. **Sparkle vergleicht DIESE** (nicht die Marketing-Version) → muss monoton steigen. Zeitstempel macht ausserdem **jeden Build unterscheidbar** (eine Commit-Zaehlung aendert sich zwischen Rebuilds nicht) |
| `GitCommit` (custom key) | `git rev-parse --short HEAD` + `-dirty` | Sagt, aus welchem Quellstand gebaut wurde |

Der Ueber-Dialog und **jeder Bug-Report** zeigen `AppVersion.display` =
`Version 0.2.0 (202607170939) · 95130e5-dirty`.

⚠️ **Warum das wichtig ist**: Vorher war alles hart `0.1.0 (1)`. Damit haette
Sparkle **nie** ein Update ausgeliefert (Build-Nummer stieg nie), und Bug-Reports
waren keinem Stand zuzuordnen — Issue #3 hat genau daran eine Stunde gekostet.

**Release-Ablauf**: `MARKETING_VERSION` bumpen → `build_app.sh` → `make_dmg.sh`.
Den Rest macht der Build.

## Aktueller Stand (Test-Verteilung, ad-hoc)

1. `scripts/build_app.sh` → `release/MultiCamCutter.app` (ad-hoc signiert)
2. `scripts/make_dmg.sh` → `release/MultiCamCutter.dmg`
   - enthält App + „Programme"-Symlink + Erste-Start-Anleitung (Gatekeeper-Umgehung)
   - ad-hoc = **nicht notarisiert** → Tester müssen Quarantäne entfernen:
     `xattr -dr com.apple.quarantine "/Applications/MultiCamCutter.app"`

**Wichtig für lokalen Test:** Eine selbst gebaute DMG hat KEIN Quarantäne-Flag —
auf dem eigenen Mac startet die App also ohne Warnung. Die Gatekeeper-Warnung
sehen erst Tester, die die DMG **herunterladen**. Zum Testen des echten
Tester-Erlebnisses das Flag manuell setzen:
`xattr -w com.apple.quarantine "0083;0;Safari;" release/MultiCamCutter.dmg`

## Ziel-Stand (signiert + notarisiert)

Blockiert durch: **Apple Developer Program Enrollment (99 €/Jahr)** — Backlog.

### 1. Enrollment (einmalig, User-Action)
- developer.apple.com → „Enroll"
- Account-Typ **Individual** genügt (Name als Entwickler). **Organization** nur
  mit Firma + D-U-N-S-Nummer (dauert länger, nur nötig wenn Firmenname erscheinen soll).
- Nicht App-Store-spezifisch — Developer ID gilt für Direktvertrieb per DMG.

### 2. Developer-ID-Zertifikat
- Xcode → Settings → Accounts → Apple-ID hinzufügen → „Manage Certificates"
  → „+" → **Developer ID Application**
- (ohne Xcode: `security`/`certutil` via developer.apple.com CSR — umständlicher)

### 3. Notarisierungs-Credentials hinterlegen (einmalig)
```
xcrun notarytool store-credentials multicam-notary \
  --apple-id "DEINE_APPLE_ID" \
  --team-id "DEINE_TEAM_ID" \
  --password "APP-SPEZIFISCHES-PASSWORT"   # appleid.apple.com → Anmeldung & Sicherheit
```

### 4. Signieren → Notarisieren → Stapeln (pro Release)
```
# a) Mit Developer ID signieren (Sparkle inside-out, mit Hardened Runtime)
codesign --force --options runtime --timestamp \
  --sign "Developer ID Application: DEIN NAME (TEAMID)" \
  --deep release/MultiCamCutter.app
#   Hinweis: Sparkle-Framework braucht ggf. eigene Signierung der XPC-Services
#   ZUERST, dann die App außen. Sparkle-Doku „Signing" beachten.

# b) DMG bauen (scripts/make_dmg.sh) und die DMG notarisieren
xcrun notarytool submit release/MultiCamCutter.dmg \
  --keychain-profile multicam-notary --wait

# c) Notarisierungs-Ticket an die DMG heften (offline-Gatekeeper)
xcrun stapler staple release/MultiCamCutter.dmg
```
Danach startet die App auf fremden Macs **ohne** Warnung, ohne xattr.

## Auto-Update (Sparkle)

### Keys — Zustand
- **Public Key** `kcPVTCojTVp36MscXhRzKlgyNAa/fkekxnoVfsxfRDY=` steckt in `SUPublicEDKey`.
- **Private Key** liegt im Login-Keychain („Private key for signing Sparkle updates",
  Account `ed25519`). Verifiziert via `generate_keys -p` — Public passt zum Bundle.
- Backup: `MulticamCutter/.build/artifacts/sparkle/Sparkle/bin/generate_keys -x <datei>`
  → Inhalt in Passwort-Manager, Datei löschen. **Verlust = nie wieder Auto-Updates.**

### Feed-URL
- **SUFeedURL** = `https://multicamcutter.pantake.com/appcast.xml` (eigene Domain).
  In `build_app.sh` als einzige Stelle (Info.plist-Heredoc).
- Bei kuenftigem Domainwechsel: von der alten Domain einen 301-Redirect auf den neuen
  Appcast legen — bestehende Installs fragen weiter die in ihrer Info.plist gebrannte
  SUFeedURL ab.

### Appcast hosten (Website-Session)
Pro Release mit Sparkles `bin/generate_appcast <ordner>` erzeugen — signiert jede
Update-Datei automatisch mit dem Keychain-Key und schreibt `appcast.xml`:
1. Neue Version bauen → DMG/ZIP in einen `updates/`-Ordner legen
2. `generate_appcast updates/ --download-url-prefix https://<host>/downloads/`
3. `appcast.xml` (klein) → Vercel `public/appcast.xml`
4. ⚠️ Die Update-DMGs (~500 MB) NICHT in Vercel/Git — Objekt-Storage nutzen
   (Cloudflare R2 / S3 / B2) und Enclosure-URL dorthin zeigen lassen.
5. Testen: Über-Dialog → „Auf Update prüfen" muss die neue Version anbieten.
