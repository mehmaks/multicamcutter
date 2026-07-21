# Distribution-Setup

Wie aus der gebauten App eine verteilbare Datei wird — von der ad-hoc-DMG bis zur
signierten/notarisierten Auslieferung inkl. Auto-Update.


## ✅ Update-Kette einmal vollständig verifiziert (21.07., 0.4.0 → 0.5.0)

Erste nachweislich durchgelaufene Auto-Update-Installation. Bewiesen sind damit
in einem Zug: Developer-ID-Signatur + Hardened Runtime, Notarisierung + Stapling,
Gatekeeper-Akzeptanz, Sparkle-EdDSA-Signatur des Feeds, R2-Auslieferung über die
`/downloads`-Weiterleitung und die `CFBundleVersion`-Vergleichslogik
(`202607190827` → `202607210731`).

Die Quelle war **0.4.0 vom 19.07., also ein Build VOR den Gatekeeper-Fixes** —
der Migrationspfad von den fehlerhaft gepackten Ständen auf einen korrekten ist
damit ebenfalls bestätigt.

⚠️ Beim Testen darauf achten, welche App läuft: `release/MultiCamCutter.app`, die
Dev-App aus `swift run` und `/Applications/MultiCamCutter.app` heißen gleich.
Finder sortiert nicht nach Ort. Sicher ist `open /Applications/MultiCamCutter.app`.

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

## DMG-Gestaltung (Hintergrund, Fenster, Icon-Positionen)

`make_dmg.sh` baut ein gestaltetes Installations-Fenster: UDRW erzeugen →
mounten → Finder via AppleScript einstellen → auswerfen → UDZO komprimieren.
Direkt UDZO ginge nicht — ein schreibgeschütztes Volume nimmt keine `.DS_Store`
mit Ansichtsoptionen an.

### Eigene Hintergrundgrafik einsetzen
Datei als **`scripts/dmg-background.tiff`** (oder `.png`) ablegen — sie hat
Vorrang. Fehlt sie, erzeugt `make_dmg_background.py` eine generische.

⚠️ **Format: 640 × 400 Pixel.** Finder legt den Hintergrund in **Pixeln =
Punkten** an, verankert ihn oben links und **skaliert nicht**. Eine
1280 × 800-Datei erscheint deshalb als 1280 × 800 Punkte — sichtbar ist nur das
linke obere Viertel (genau so passiert, 21.07.).

| Element | Position im 640×400-Raster (Ursprung oben links) |
|---|---|
| App-Icon, Mitte | **170, 186** → belegt x 106–234, y 122–250 |
| `Programme`-Icon, Mitte | **470, 186** → belegt x 406–534, y 122–250 |
| Icon-Beschriftungen | zeichnet **Finder selbst** → y 250–278 freihalten, keine eigenen Labels |
| freier Mittelbereich | x 240–400 zwischen den Icons |
| unterer Rand | letzte ~20 px nicht mit Wichtigem belegen (Titelleistenhöhe variiert) |

**Retina — einfachster Weg:** Grafik **nur in 1280 × 800** anlegen, den Rest
erledigt das Skript:
```
bash scripts/dmg_background_tiff.sh ~/Desktop/hintergrund@2x.png
```
Es rechnet die 640×400-Fassung herunter (Pillow/Lanczos, sips als Rückfall),
verbindet beide per `tiffutil -cathidpicheck` und legt
`scripts/dmg-background.tiff` ab. Ab dann nimmt `make_dmg.sh` sie automatisch.

Im 1280 × 800-Raster verdoppeln sich alle Positionen:
App-Icon Mitte **340, 372** · `Programme` Mitte **940, 372** ·
Finder-Labels **y 500–556 freihalten**.

⚠️ Ändern sich Icon-Positionen, müssen **beide** Stellen mit: die AppleScript-
Werte in `make_dmg.sh` und `APP_XY`/`DEST_XY` in `make_dmg_background.py`.

### ⛔ Label-Textfarbe ist NICHT steuerbar — nicht nochmal untersuchen
Bei dunklem Hintergrund sind die von Finder gezeichneten Dateinamen
(„MultiCamCutter.app", „Programme") **schwarz und kaum lesbar**. Das ist eine
Plattformgrenze, kein Konfigurationsfehler:

> „Sobald ein eigenes Hintergrundbild gesetzt ist, behandelt Finder das Fenster
> immer so, als wäre es im Light Mode." — Michael Tsai (DropDMG)

Belegt und mehrfach geprüft (21.07.):
- `icon view options` kennt nur `text size`, `label position`, `color` —
  **keine** Label-Farbe. (Eigenschaften abgefragt, vollständige Liste.)
- `background color` **ersetzt** das Bild, statt daneben zu bestehen. Reihenfolge
  ist dabei egal: Farbe→Bild = Bild sichtbar, Farbe wirkungslos; Bild→Farbe =
  Bild weg.
- Das kurze **weiße Aufblitzen** beim Öffnen ist ein Ladezustand, bevor das Bild
  greift — nicht persistierbar.
- Bei `create-dmg` (Issue #197) und `electron-builder` (#2297) offener
  Feature-Request ohne Lösung. Auch kommerzielle Werkzeuge können es nicht.

**Einziger Ausweg:** Helligkeit in der Grafik. Gemessen an der aktuellen Grafik
liegt die Label-Zone bei 16–39 (0–255); dunkler Text braucht ~110. Ein weicher
Verlauf im Bereich **y 500–556** (2x) unter beiden Icons genügt — kein weißer
Kasten nötig. Icons zu verschieben hilft nicht: bei allen geprüften Höhen
(y 240–372) bleibt die Zone unter 40.

Die dokumentierte Alternative — **ganz auf das Hintergrundbild verzichten**,
dann folgen Hintergrund und Text der Systemeinstellung — scheidet aus, wenn eine
gestaltete DMG gewünscht ist.

### Fallstricke (alle erlebt)
- `hdiutil create -size` braucht viel Reserve — +120 MB reichten nicht
  („kein Platz verfügbar" trotz 400 GB frei; gemeint ist das **Image**).
  Jetzt +25 % +200 MB.
- `background picture` per Doppelpunkt-Notation scheitert bei versteckten
  Ordnern mit **-10006**. POSIX-Pfad funktioniert.
- Das AppleScript **muss das Fenster schließen**, sonst hält der Finder das
  Volume und `hdiutil convert` scheitert mit „Ressource zeitweilig nicht
  verfügbar". Auswerfen zusätzlich mit Wiederholung.
- Läuft nur in einer GUI-Sitzung (Finder-Automatisierung), nicht headless.

## Release-Checkliste (Update ausliefern)

Kompletter Weg von „neue Version" bis „Nutzer bekommt das Update". Zum Aufzählen
gedacht — wenn du danach fragst, ist das die Liste.

**Vorher — Changelog schreiben (meine Aufgabe, nicht die des Users):**

0. **Alle Commits seit dem letzten Release in Nutzertext übersetzen.**
   ```
   git log --oneline <letzter-release-tag-oder-commit>..HEAD
   ```
   Daraus einen Changelog-Abschnitt formulieren und dem User zur Freigabe
   vorlegen, **bevor** `release.sh` läuft.

   **Warum übersetzen und nicht übernehmen:** Unsere Commit-Botschaften sind
   bewusst entwicklungsnah — sie nennen Ursachen, Dateinamen, Zeilennummern
   („min_len-Kürzung war der eigentliche Fehler"). Als Nutzertext sind sie
   unbrauchbar bis verunsichernd. Ein Changelog beantwortet **eine** Frage:
   *Was ändert sich für mich?*

   **Regeln:**
   - Nach **Wirkung** gruppieren, nicht nach Commit: „Behoben", „Neu",
     „Verbessert". Fünf Commits an einem Thema werden **eine** Zeile.
   - Aus der Nutzersicht schreiben: nicht „`sync_sources` misst jede Quelle
     einzeln", sondern „Mehr als zwei Kameras und zusätzliche Mikrofone werden
     jetzt korrekt synchronisiert."
   - **Interna weglassen**: Dateinamen, Funktionsnamen, Zeilennummern, Commit-Hashes.
   - **Stillschweigend behobene Fehler benennen**, wenn sie Ergebnisse betrafen.
     Wer eine fehlerhafte Fassung im Einsatz hatte, muss wissen, ob alte
     Ergebnisse betroffen sind — das ist der wichtigste Teil des Changelogs.
   - Rein Internes (Build-Skripte, Doku, Refactorings) gehört **nicht** hinein.
   - Deutsch, ganze Sätze, keine Emoji-Wüste.

   **Beispiel** (aus den Commits vom 21.07.):
   > **Behoben:** Bei mehr als zwei Kameras oder mehreren Mikrofonen konnten
   > Tonspuren um mehrere Sekunden verschoben im Schnitt landen, ohne dass eine
   > Fehlermeldung erschien. Alle Quellen werden jetzt einzeln vermessen und
   > gegengeprüft; unsichere Ergebnisse führen zu einem klaren Abbruch statt zu
   > einem stillen Fehler.

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

## Was im Bucket liegen muss (und was weg darf)

**Der Appcast ist die Wahrheit.** Alles, was er referenziert — volle DMGs **und
Delta-Dateien** — muss unter `downloads/` abrufbar sein. Fehlt etwas, laeuft das
Update ins 404; bei Deltas faellt Sparkle dabei *still* auf die volle DMG zurueck,
der Fehler bleibt also unsichtbar (siehe `Bekannte-Bugs.md`).

- `release.sh` erzeugt den Feed mit **`--maximum-versions 5`**. Aeltere Eintraege
  fallen heraus und ihre Dateien werden damit gefahrlos loeschbar.
- **Lokal** bleibt alles liegen: `generate_appcast` braucht die alten DMGs, um
  kuenftige Deltas dagegen zu rechnen. Deshalb **kein** `--auto-prune-update-files`.
- `publish.sh` laedt alles hoch, was der Feed referenziert und lokal vorliegt,
  prueft **jede** beworbene URL und listet am Ende die **verwaisten** Objekte im
  Bucket samt fertigem `rclone delete`-Befehl. Geloescht wird **von Hand** —
  unwiderruflich, und laufende Downloads koennten noch daran haengen.

Faustregel: erst veroeffentlichen, dann die gemeldeten Waisen loeschen. Nie umgekehrt.
