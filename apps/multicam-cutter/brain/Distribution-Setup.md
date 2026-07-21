# Distribution-Setup

Wie aus der gebauten App eine verteilbare Datei wird — von der ad-hoc-DMG bis zur
signierten/notarisierten Auslieferung inkl. Auto-Update.


## ⚠️ Gatekeeper-Prüfung nach dem Release IMMER lesen

`release.sh` meldet am Ende `spctl`-Ergebnisse. **„rejected" dort heißt NICHT,
dass Apple abgelehnt hat** — die Notarisierung steht separat im Log
(`status: Accepted`). Zwei Fehler, die 0.5.0 gezeigt hat und die beide gefixt
sind (21.07.):

| Meldung | Ursache | Fix |
|---|---|---|
| `the code is valid but does not seem to be an app` | Im Plist-Template stand `CFBundlePackagetype` — **kleines „t"**. macOS-Keys sind case-sensitiv, der Eintrag wurde ignoriert und spctl erkannte das Bundle nicht als Programm. | `build_app.sh`, Key korrigiert |
| `rejected — source=no usable signature` (DMG) | `make_dmg.sh` hat das DMG nur erzeugt, nie signiert. Notarisieren + Stapeln allein genügt Gatekeeper nicht. | `make_dmg.sh` signiert jetzt mit `SIGN_IDENTITY`, **vor** der Einreichung |

Dazu wurde `SIGN_IDENTITY` durch die ganze Kette gereicht
(`release.sh` → `notarize.sh` → `make_dmg.sh`); vorher endete es bei
`build_app.sh` und die Subprozesse sahen es nicht.

**So prüfst du einen Release von Hand:**
```
spctl -a -vv -t exec    release/MultiCamCutter.app     # -> accepted, Notarized Developer ID
spctl -a -vv -t install release/MultiCamCutter.dmg     # -> accepted
xcrun stapler validate  release/MultiCamCutter.dmg     # -> The validate action worked!
```
Alle drei müssen grün sein. `stapler validate` allein reicht **nicht** — es
bestätigt nur, dass ein Ticket angeheftet ist, nicht dass Gatekeeper das Paket
akzeptiert.

## Release-Checkliste (Update ausliefern)

Kompletter Weg von „neue Version" bis „Nutzer bekommt das Update". Zum Aufzählen
gedacht — wenn du danach fragst, ist das die Liste.

**Auf meinem Mac (ein Befehl):**
1. **Version festlegen** — höher als die letzte. Anzeige-Version (`0.5.0`) wählst
   du; die für Sparkle entscheidende `CFBundleVersion` (Zeitstempel) setzt der
   Build automatisch, steigt also immer.
2. **Im eigenen Terminal** (nicht headless!): `bash scripts/release.sh 0.5.0`
   → baut Developer-ID-signiert (Hardened Runtime) → notarisiert + stapelt →
   erzeugt den signierten `appcast.xml`. Beim allerersten Mal je einmal „Immer
   erlauben" für codesign und generate_appcast. Dauer ~10–15 min (Build + ~1 GB
   Upload zu Apple).

**Publish — `bash scripts/publish.sh 0.5.0`** (bewusst separat, „geht nach außen"):

Das Skript nimmt die Tipparbeit ab, **nicht die Entscheidung**: Es zeigt zuerst
vollständig, was es tun wird, und fragt einmal. Braucht `R2_BUCKET` (z. B. `multicamcutter-downloads`) und **rclone**.

⚠️ **wrangler scheidet aus**: harte Grenze von **300 MiB** pro Upload, kein
Multipart (`Wrangler only supports uploading files up to 300 MiB in size`,
getestet mit 4.112.0). Unsere DMGs liegen bei ~500 MiB. `rclone` spricht R2 über
die S3-API und lädt automatisch in Teilen. Einmalig:
```
brew install rclone
rclone config     # n) new remote · Name: r2 · Typ: s3 · Provider: Cloudflare
                  # Access Key + Secret: Cloudflare → R2 → API-Token erstellen
                  # Endpoint: https://<account-id>.r2.cloudflarestorage.com
```
Die Zugangsdaten liegen in der rclone-Config, **nicht** im Repo. Das Skript
erkennt das Werkzeug **vor** der Rückfrage — kein Bestätigen und dann scheitern.

**Zwei Stolpersteine bei der R2-Einrichtung (beide erlebt, 21.07.):**
- **401 Unauthorized** bei *jeder* Operation → Zugangsdaten falsch. Ursache war
  ein `¢` in der Access Key ID, entstanden beim Abtippen aus einem **Screenshot
  per Texterkennung**. ⚠️ Credentials nie per OCR übernehmen: Bei Hex-Werten
  bleiben Verwechslungen wie `8`↔`B` oder `6`↔`b` **gültiges Hex** und rutschen
  durch jeden Formatcheck. Access Key ID = 32 Hex, Secret = 64 Hex.
- **403 AccessDenied auf `CreateBucket`** → rclone prüft vorab, ob der Bucket
  existiert, und will ihn sonst anlegen. Ein auf einen Bucket beschränktes Token
  darf das nicht. Lösung: **`--s3-no-check-bucket`** (steht im Skript).
  `ListBuckets` mit 403 ist bei so einem Token **normal**, kein Fehler — zum
  Testen deshalb `rclone ls r2:<bucket> --s3-no-check-bucket` statt `rclone lsd r2:`.

**Von Hand hochgeladen?** `bash scripts/publish.sh 0.5.0 --skip-upload`
Überspringt nur den Upload, **nicht die Prüfung**. Die ist beim manuellen Weg
sogar wichtiger, weil dort genau die Fehler passieren, die sie abfängt: Objekt-Key
mit Tippfehler, falscher Content-Type, abgebrochener Transfer. `R2_BUCKET` ist
dann nicht nötig.

⚠️ **Reihenfolge ist sicherheitsrelevant** — erst DMG, dann Feed. Ginge der
Appcast zuerst live, böte Sparkle allen Nutzern ein Update an, dessen Datei noch
nicht existiert: kaputte Installation statt keiner. Das Skript prüft den Upload
per `HEAD` (Status 200 **und** exakte `Content-Length` aus dem signierten Feed)
und bricht **vor** dem Appcast-Push ab, wenn etwas fehlt. Häufigster Fall:
`wrangler` hat ein Größenlimit und der ~500-MB-Upload läuft nicht durch — dann
bleibt der Feed unangetastet.

Was es prüft, bevor überhaupt etwas rausgeht: DMG existiert · Dateigröße ==
`length` im Feed · Feed-Version == Argument · Enclosure-Dateiname == erwarteter
Objekt-Key. Danach: HEAD auf die Enclosure-URL, dann Appcast committen/pushen,
dann bis zu 90 s auf den Vercel-Deploy warten und den Live-Feed gegenprüfen.

**Nicht automatisierbar bleibt Schritt 3** (echter Sparkle-Update-Test aus einer
älteren Installation) — das braucht eine real installierte Vorversion.

<details><summary>Die Schritte einzeln, falls von Hand nötig</summary>

3. **DMG → Cloudflare R2**: `release/updates/MultiCamCutter-<version>.dmg` hochladen.
   · Objekt-Key **exakt** = Dateiname (muss zur Enclosure-URL im Feed passen).
   · Content-Type `application/octet-stream`.
4. **appcast.xml → Website**: `release/updates/appcast.xml` ins Website-Repo unter
   `public/appcast.xml`, Vercel deployen.
5. **Testen**: eine ältere installierte Version → „Über MultiCamCutter" → „Auf
   Update prüfen" muss die neue Version anbieten, laden, verifizieren, installieren.

</details>

Kurzform: **release.sh → publish.sh → aus alter Installation testen.**

Einmalige Voraussetzungen (alle erledigt): Developer-ID-Zertifikat + Notary-Profil
`MulticamNotary` + Sparkle-Private-Key im Keychain + R2-Storage & `/downloads`-Route
live. Detail-Referenzen: Signieren/Notarisieren unten, Hosting-Contract in
`brain/Appcast-Hosting.md`.

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

**Ein Befehl** (`scripts/release.sh`):
```
bash scripts/release.sh 0.5.0
```
Macht: Version setzen (an build_app.sh durchgereicht) → Developer-ID-signiert bauen
→ notarisieren (notarize.sh) → Appcast erzeugen (nur wenn `DOWNLOAD_URL_PREFIX`
gesetzt). Die Identität wird aus dem Schlüsselbund **auto-erkannt** (oder via Env
`SIGN_IDENTITY` gesetzt). Das Hochladen (DMG → Objekt-Storage, appcast.xml →
Website) bleibt bewusst ein separater, bestätigter Schritt — release.sh zeigt am
Ende genau, was zu tun ist.

Mit Appcast in einem Rutsch (sobald der Storage-Host steht):
```
DOWNLOAD_URL_PREFIX=https://<host>/downloads/ bash scripts/release.sh 0.5.0
```

**Einzelschritte** (falls man nur bauen/notarisieren will):
```
SIGN_IDENTITY="Developer ID Application: Maximilian Menge (6F5UGR7V25)" \
  bash scripts/build_app.sh      # nur signiert bauen
bash scripts/notarize.sh         # nur notarisieren
```
`notarize.sh` baut die DMG (mit schlanker LIESMICH statt Gatekeeper-Umgehung, via
`NOTARIZED=1 make_dmg.sh`), reicht sie via `notarytool submit --wait` ein, staplet
den Ticket an App **und** DMG und prüft mit `stapler validate` + `spctl`. Bei
Ablehnung zieht es automatisch das Apple-Log (`notarytool log <id>`).

### ⚠️ Muss im eigenen Terminal laufen (nicht headless)
Beim ersten `codesign` mit dem privaten Schlüssel zeigt macOS einen
Schlüsselbund-Dialog („codesign möchte den Schlüssel verwenden"). **Einmal
„Immer erlauben"** klicken — danach laufen alle ~650 Signaturen ohne weitere
Prompts. Dasselbe gilt einmalig für `generate_appcast` (greift auf den privaten
Sparkle-Schlüssel zu). In einer headless-Shell (CI, Agent) hängen beide an genau
diesem Dialog. Alternative ohne Klick (einmalig, braucht Login-Passwort):
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
