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

## Zwei Build-Modi

`build_app.sh` signiert je nach Env `SIGN_IDENTITY`:

| Modus | Aufruf | Ergebnis |
|-------|--------|----------|
| **Ad-hoc (Dev, Default)** | `bash scripts/build_app.sh` | Läuft nur lokal, nicht notarisierbar |
| **Developer ID (Verteilung)** | `SIGN_IDENTITY="Developer ID Application: … (TEAMID)" bash scripts/build_app.sh` | Hardened Runtime + Entitlements, inside-out signiert → bereit für `notarize.sh` |

**Release-Ablauf (Dev-DMG)**: `MARKETING_VERSION` bumpen → `build_app.sh` →
`make_dmg.sh`. **Release-Ablauf (notarisiert)**: siehe unten.

### Ad-hoc-DMG testen
Eine selbst gebaute DMG hat KEIN Quarantäne-Flag — auf dem eigenen Mac startet die
App ohne Warnung. Die Gatekeeper-Warnung sehen erst Tester, die die DMG
**herunterladen**. Echtes Tester-Erlebnis simulieren:
`xattr -w com.apple.quarantine "0083;0;Safari;" release/MultiCamCutter.dmg`
Entfernen (falls doch nötig):
`xattr -dr com.apple.quarantine "/Applications/MultiCamCutter.app"`

## Signiert + notarisiert (eingerichtet)

Alle Voraussetzungen sind **vorhanden** (Stand: eingerichtet):
- **Developer Program**: enrolled, Team-ID `6F5UGR7V25` (Individual, „Maximilian Menge").
- **Zertifikat**: `Developer ID Application: Maximilian Menge (6F5UGR7V25)` im
  Login-Schlüsselbund (`security find-identity -v -p codesigning`).
- **Notary-Profil**: `MulticamNotary` im Schlüsselbund (via
  `notarytool store-credentials`, mit App-spezifischem Passwort von appleid.apple.com).
  Verifiziert mit `xcrun notarytool history --keychain-profile MulticamNotary`.

### Entitlements
`scripts/MulticamCutter.entitlements` — drei Hardened-Runtime-Ausnahmen für den
PyInstaller/torch-Prozess: `disable-library-validation`,
`allow-unsigned-executable-memory`, `allow-dyld-environment-variables`. Ohne sie
startet die Engine unter Hardened Runtime nicht. Bewusst **kein** App-Sandbox
(freier Ordnerzugriff nötig).

### Signier-Reihenfolge (in build_app.sh, inside-out)
Zwingend von innen nach außen — signiert man die App zuerst, invalidiert jedes
Innen-Signieren die äußere Signatur:
1. Alle Mach-O im Engine-Bundle (~650 .dylib/.so, Mach-O-erkannt per `file`) — ohne Entitlements
2. Engine-Executable — **mit** Entitlements
3. ffmpeg/ffprobe
4. Sparkle.framework: XPC-Services + Autoupdate → Updater.app → Framework
5. App-Bundle außen — **mit** Entitlements, **kein** `--deep`

### Release-Ablauf (pro notarisiertem Release)
```
# 1) Mit Developer ID signieren (baut komplett neu, Hardened Runtime)
SIGN_IDENTITY="Developer ID Application: Maximilian Menge (6F5UGR7V25)" \
  bash scripts/build_app.sh

# 2) DMG bauen + notarisieren + stapeln + verifizieren (eine Aktion)
bash scripts/notarize.sh
```
`notarize.sh` baut die DMG (mit schlanker LIESMICH statt Gatekeeper-Umgehung, via
`NOTARIZED=1 make_dmg.sh`), reicht sie via `notarytool submit --wait` ein, staplet
den Ticket an App **und** DMG und prüft mit `stapler validate` + `spctl`. Bei
Ablehnung zieht es automatisch das Apple-Log (`notarytool log <id>`).

### ⚠️ Muss im eigenen Terminal laufen (nicht headless)
Beim ersten `codesign` mit dem privaten Schlüssel zeigt macOS einen
Schlüsselbund-Dialog („codesign möchte den Schlüssel verwenden"). **Einmal
„Immer erlauben"** klicken — danach laufen alle ~650 Signaturen ohne weitere
Prompts. In einer headless-Shell (CI, Agent) hängt codesign an genau diesem
Dialog. Alternative ohne Klick (einmalig, braucht Login-Passwort):
`security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k <pw> ~/Library/Keychains/login.keychain-db`
(`notarytool` und `stapler` prompten NICHT — deren Schlüsselbund-Zugriff ist über
das gespeicherte Profil autorisiert.)

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
