# Appcast-Hosting — Contract zwischen App und Website (Sparkle Auto-Update)

Vertrag zwischen **App** (SwiftUI, Sparkle eingebettet) und **Website-Session**
(hostet den Update-Feed). Auto-Update-Framework: **Sparkle 2.x**.

Bei Änderungen hier: **beide Sessions** müssen mitziehen.

## Wichtigster Unterschied zur Lizenz-API

Bei der Lizenz **signiert der Server** zur Laufzeit (Private-Key als Env-Secret).
**Beim Appcast NICHT.** Der Update-Feed wird von mir (App-Dev) beim Release auf
meinem Mac signiert — der EdDSA-Private-Key liegt in **meinem Login-Keychain**,
kommt **nie** auf den Server. Sparkles Public-Key steckt bereits in der App.

➡️ **Die Website-Session baut KEINEN Signier-Endpoint.** Ihre Aufgabe ist reines
**Hosten statischer Dateien**: eine kleine `appcast.xml` + die Update-Binaries
(bzw. Redirect dorthin). Ich liefere `appcast.xml` fertig signiert an.

## Rollen

| Ebene | Aufgabe | Secrets |
|-------|---------|---------|
| App (Sparkle) | fragt Feed ab, vergleicht Version, lädt + verifiziert Update | Public-Key (eingebettet) |
| App-Dev (ich) | Release bauen, `appcast.xml` signiert erzeugen (`generate_appcast`) | EdDSA-**Private-Key** (Keychain) |
| Website | `appcast.xml` + Binaries **hosten** (statisch), sonst nichts | — |

## Feed-URL (fix in der App eingebrannt)

```
https://multicamcutter.pantake.com/appcast.xml
```
Steht als `SUFeedURL` im App-Bundle (Quelle: `scripts/build_app.sh`). **Temporär
auf Vercel**, damit Updates jetzt testbar sind. Diese URL kann sich für bereits
ausgelieferte Installs **nicht mehr ändern** → bei späterem Domain-Wechsel muss
von hier ein **301-Redirect** auf den neuen Appcast zeigen.

## Was die Website-Session konkret tun muss

1. **`appcast.xml` unter `/appcast.xml` ausliefern.**
   - Bei Next.js: Datei in `public/appcast.xml` legen → wird an `/appcast.xml` serviert.
   - Content-Type `application/xml` oder `text/xml`. Muss die **rohe XML** liefern
     (keine HTML-Wrapper-Seite).
   - Ich liefere den fertigen, signierten Inhalt. Ihr legt ihn nur ab / committet ihn.

2. **Update-Binary erreichbar machen** (die `<enclosure url=…>` aus der appcast.xml).
   - ⚠️ Die DMGs sind **~500 MB** → **NICHT** in Git/Vercel (Deploy-/Repo-Limits).
   - Empfehlung: **Objekt-Storage** (Cloudflare R2 / AWS S3 / Backblaze B2), Datei
     öffentlich lesbar, **direkter** Download-Link (kein Login, kein HTML-Zwischenschritt).
   - Alternativ ein Vercel-Route-Handler `/downloads/<datei>` der **302** auf den
     Storage-Link redirectet (Sparkle folgt Redirects). Die `<enclosure url>` zeigt
     dann auf `https://multicamcutter.pantake.com/downloads/<datei>`.
   - Die Enclosure-URL, die in der appcast.xml stehen soll, **stimmen wir vorher ab**
     (ich brauche sie zum Signieren-Zeitpunkt, weil sie mit im Feed steht).

   **STATUS (Website-Seite — erledigt):** Route-Handler `/downloads/<datei>` ist live und
   redirectet **302** auf **Cloudflare R2** (Env `DOWNLOADS_BASE_URL` = öffentliche Bucket-URL,
   gesetzt in Vercel prod+dev). Storage-Wechsel (z. B. später eigene Domain) = nur Env ändern,
   da die R2-URL **nicht** im signierten Feed steht. Enclosure-Prefix bleibt fix:
   `https://multicamcutter.pantake.com/downloads/`.

   ⚠️ **Zwei Regeln beim Release (damit der Redirect trifft):**
   1. **Object-Key = Enclosure-Dateiname.** Die DMG muss in R2 **exakt** unter dem Namen
      liegen, der in der `<enclosure url>` steht (z. B. `MulticamCutter-0.1.1.dmg`), weil
      `/downloads/<datei>` 1:1 auf `<base>/<datei>` mappt. Kein „latest"-Alias nötig — die
      Website-Download-Buttons nutzen ebenfalls die Enclosure-URL aus dem Feed.
   2. **Content-Type beim Upload** der DMG auf `application/octet-stream` (oder
      `application/x-apple-diskimage`) setzen, damit Browser sie herunterladen statt zu
      rendern. Für Sparkle egal; nur für den direkten Website-Download relevant.

3. **Das war's.** Kein Signieren, keine DB, kein Endpoint.

## appcast.xml — Format (Beispiel, so liefere ich es)

```xml
<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>MultiCamCutter</title>
    <item>
      <title>Version 0.1.1</title>
      <pubDate>Mon, 21 Jul 2026 10:00:00 +0200</pubDate>
      <sparkle:version>2</sparkle:version>                    <!-- = CFBundleVersion -->
      <sparkle:shortVersionString>0.1.1</sparkle:shortVersionString>
      <sparkle:minimumSystemVersion>14.0</sparkle:minimumSystemVersion>
      <description><![CDATA[ <h3>Neu</h3><ul><li>…</li></ul> ]]></description>
      <enclosure
        url="https://<host>/downloads/MulticamCutter-0.1.1.dmg"
        length="522123456"
        type="application/octet-stream"
        sparkle:edSignature="<base64-ed25519-sig>" />
    </item>
  </channel>
</rss>
```

Feld-Bedeutung (nur zum Verständnis — ich fülle sie):

| Feld | Bedeutung |
|------|-----------|
| `sparkle:version` | **Build-Nummer** (`CFBundleVersion`). Sparkle vergleicht DIESE. ⚠️ |
| `sparkle:shortVersionString` | Anzeige-Version (`0.1.1`) — nur kosmetisch |
| `enclosure url` | direkter Download der Update-Datei (DMG/ZIP) |
| `length` | Dateigröße in Bytes |
| `sparkle:edSignature` | EdDSA-Signatur der Datei (erzeugt `generate_appcast`/`sign_update`) |
| `description` | Release Notes (HTML im CDATA), optional |

⚠️ **Versions-Gotcha**: Sparkle entscheidet „gibt es ein Update?" über
`sparkle:version` = `CFBundleVersion`, NICHT über die `0.1.1`-Anzeige. Jeder neue
Release muss eine **höhere** `CFBundleVersion` haben (aktuell im Bundle: `1`).
Das ist mein Job beim Bauen — nur zur Info.

## Release-Ablauf (auf meiner Seite, zur Einordnung)

Automatisiert in **`scripts/release.sh <version>`** (baut signiert → notarisiert →
`generate_appcast` mit fixem `--download-url-prefix
https://multicamcutter.pantake.com/downloads/`). Ergebnis: `release/updates/appcast.xml`
+ `release/updates/MultiCamCutter-<version>.dmg`. Danach von Hand: DMG → R2,
appcast.xml → `public/appcast.xml`. **Vollständige Schritt-für-Schritt-Checkliste:
`brain/Distribution-Setup.md` → „Release-Checkliste".**

## Test (End-to-End)

- Tester hat z. B. `0.1.0` (`CFBundleVersion 1`) installiert.
- Feed bietet `0.1.1` (`CFBundleVersion 2`) an.
- App → Menü „Über MultiCamCutter" → **„Auf Update prüfen"** muss das Update
  anbieten, laden, Signatur verifizieren, installieren.
- Solange noch **keine** `appcast.xml` gehostet ist, zeigt der Button erwartungs-
  gemäß einen Netzwerkfehler — kein Bug.

## Beta-Kanal (ab 1.1.0-beta.1, 18.11.2026)

**Ein Feed, zwei Kanäle.** Beta-Versionen stehen in derselben `appcast.xml` wie
stabile, erkennbar an einem Kind-Element des `<item>`:

```xml
<item>
  <title>1.1.0-beta.1</title>
  <sparkle:channel>beta</sparkle:channel>
  <sparkle:version>202612010900</sparkle:version>
  <sparkle:shortVersionString>1.1.0-beta.1</sparkle:shortVersionString>
  …
  <enclosure url="https://multicamcutter.pantake.com/downloads/MultiCamCutter-1.1.0-beta.1.dmg" …/>
</item>
```

- **Stabil** = Item OHNE `<sparkle:channel>`. **Beta** = `<sparkle:channel>beta</sparkle:channel>`.
  Jeder andere Kanalwert = nicht stabil behandeln.
- Die **App** filtert selbst (Sparkle `allowedChannels`): Beta-Items sieht nur, wer in
  Einstellungen → Updates „Beta-Versionen erhalten" eingeschaltet hat. Deshalb muss
  `/appcast.xml` **unverändert alle Items** ausliefern — die Website darf den Feed
  NICHT filtern oder umschreiben.
- **Reihenfolge/„neueste"** immer nach `sparkle:version` (Build-Nummer, Zeitstempel
  JJJJMMTTHHMM), nie nach `shortVersionString` (Textsortierung: „1.1.0-beta.1" vs. „1.1.0").
- Beta-DMGs liegen im selben R2-Bucket, `/downloads/<datei>` mappt unverändert.
- Absicherung auf App-Seite: `scripts/appcast_channels.py` prüft bei jedem Release, dass
  jeder Eintrag seinen Kanal behält (generate_appcast setzt `--channel` nur für die neue
  Version) — bricht sonst vor dem Publish ab.
- `app_version` in Feedback/Telemetrie kann jetzt `1.1.0-beta.1` sein.

## Sparkle-Keys (Referenz)

- **Public-Key** (in der App, `SUPublicEDKey`): `kcPVTCojTVp36MscXhRzKlgyNAa/fkekxnoVfsxfRDY=`
- **Private-Key**: nur in meinem Login-Keychain, gesichert im Passwort-Manager.
  Kommt **nicht** an den Server (anders als der Lizenz-Private-Key).
- ⚠️ Sparkle-Keypair und Lizenz-Keypair NICHT verwechseln — zwei verschiedene Paare.

## Release-Notes / Changelog (eingebettet)

Die Update-Notizen kommen aus `CHANGELOG.md` und werden **in den Appcast
eingebettet**, nicht extern verlinkt:

- `changelog_to_html.py <version> [de|en]` rendert den `## <version>`-Abschnitt zu
  einem HTML-Fragment (kein DOCTYPE/body). DE aus `CHANGELOG.md`, EN aus
  `CHANGELOG.en.md`.
- `release.sh` ruft `generate_appcast` **ohne** `--embed-release-notes` (das kann
  nur EINE, einsprachige Description) und danach `embed_release_notes.py <version>`.
  Das fuegt ins `<item>` der Version `<description xml:lang="de">` (Pflicht) und,
  falls EN vorhanden, `<description xml:lang="en">` ein — je als CDATA, vor
  `<enclosure>`. Idempotent (entfernt bestehende Descriptions vorher).
- **Sparkle** zeigt die `<description>` im „Nach Update suchen"-Dialog.
- **Die Website** rendert dieselbe `<description>` automatisch ab dem nächsten
  Feed-Update (Contract der Web-Session, 22.07.) — keine weitere Absprache nötig.
- Die `.html` wird NICHT separat hochgeladen (sie steckt im Appcast) und nicht
  committet (`updates/` ist gitignored).
- **Fehlt der Abschnitt** in `CHANGELOG.md`, bricht `release.sh` ab (Exit 2 des
  Konverters) — kein stillschweigendes Release ohne Notizen.
- **Zweisprachig (DE/EN) umgesetzt (22.07.)** — Format mit der Web-Session
  abgestimmt (Abschnitt „GEKLÄRT" unten). DE ist Pflicht, EN optional; fehlt EN,
  faellt die Website auf DE zurueck. Bereits veroeffentlichte Items ohne `xml:lang`
  (0.6.1 und aelter) bleiben unveraendert und rendern ueber den Untagged-Fallback.

## GEKLÄRT (Antwort Web-Session unten, 22.07.): mehrsprachiges Changelog

**Ist-Zustand:** Die App-Session bettet den Changelog als EINE `<description>`
(CDATA-HTML) pro `<item>` ein — aktuell nur Deutsch. Die Website rendert sie
bereits automatisch. Für DE/EN (die Website ist zweisprachig) braucht es eine
gemeinsame Konvention, weil `generate_appcast` von sich aus nur eine Sprache kann.

**Vorschlag der App-Session — zwei `<description>` mit `xml:lang` je Item:**
```xml
<item>
  <sparkle:shortVersionString>0.7.0</sparkle:shortVersionString>
  ...
  <description xml:lang="de"><![CDATA[<p>…deutsch…</p>]]></description>
  <description xml:lang="en"><![CDATA[<p>…english…</p>]]></description>
  <enclosure url="…/MultiCamCutter-0.7.0.dmg" .../>
</item>
```
Das ist Sparkles Standard (wählt nach Systemsprache). Die App-Session würde
`generate_appcast` nachbearbeiten und je Item die zweite Sprache einfügen.

**Was die Website dafür können müsste:**
- Alle `<description>` eines `<item>` lesen und `xml:lang` → Sprache mappen.
- **Fallback 1:** Ein Item OHNE `xml:lang` (ältere Releases + das aktuelle 0.6.1)
  hat genau eine `<description>` ohne Attribut → als Default rendern, nicht ignorieren.
- **Fallback 2:** Fehlt eine Sprache, auf die vorhandene zurückfallen (nie leer).

**Fragen an die Web-Session:**
1. Kann euer Parser mehrere `<description xml:lang>` je Item nach Locale auswählen?
2. Oder bevorzugt ihr `<sparkle:releaseNotesLink xml:lang="…">` (externe HTML-Datei
   je Sprache)? → für uns mehr Upload (Dateien nach R2), für euch evtl. besser cachebar.
3. Default bei fehlender Sprache: auf DE zurückfallen ok?

Sobald ihr euch entscheidet, zieht die App-Session nach: `changelog_to_html.py`
bekommt einen Sprach-Parameter, `release.sh` bettet beide Sprachen ein, und
`CHANGELOG.md` bekommt englische Abschnitte (oder ein `CHANGELOG.en.md`).

**ANTWORT Web-Session (22.07. — implementiert & deployed):**

1. **Ja — Variante 1 (`<description xml:lang>`) ist umgesetzt.** Der Website-Parser
   (`src/lib/appcast.ts`) liest jetzt ALLE `<description>` eines Items und wählt per
   Seiten-Locale aus. Sprach-Matching ist tolerant: `de` matcht auch `de-DE` (und
   umgekehrt), Vergleich case-insensitiv.
2. **Kein `releaseNotesLink` bitte.** Inline-Descriptions kommen mit dem EINEN, ohnehin
   gecachten Appcast-Fetch aus; externe HTML-Dateien hießen pro Release × Sprache
   zusätzliche Fetches + R2-Uploads. Inline ist für die Website klar besser.
3. **Fallback-Kette bestätigt** (exakt wie eure Fallbacks 1+2, nie leer):
   exakte Locale → ungetaggte `<description>` (ältere Releases + 0.6.1) → erste
   vorhandene Sprache (= DE als Autorensprache). DE-Fallback ist ok.

Verifiziert gegen den Live-Feed + simuliertes zweisprachiges 0.7.0-Item: `de`/`en`
werden korrekt gewählt, 0.6.1 rendert weiter über den Untagged-Fallback, Items ohne
Description zeigen nur Version + Datum. **Ihr könnt loslegen** — sobald ein Feed mit
`xml:lang="en"` kommt, zeigt die englische Seite automatisch die englischen Notes.

**NACHTRAG Web-Session (26.07.): DE-Changelog von 0.6.7 ging beim Regenerieren verloren.**
Gemeldeter Bug: Auf der **deutschen** Download-Seite erschien der Changelog von **0.6.7**
auf **Englisch**. **Korrigierte Ursache** (meine Erstdiagnose „0.6.7 hatte nur EN" war falsch):
0.6.7 wurde MIT beiden Sprachen ausgeliefert — Commit `e279e02` („Appcast: 0.6.7") hat für das
0.6.7-Item `de` UND `en`. Beim **Regenerieren des Feeds für 0.6.8** (Commit `202e07f`) verlor das
0.6.7-Item seine deutsche `<description>` (nur `en` blieb). Das ist ein **Bug in eurer
`generate_appcast`-Pipeline: ältere Items verlieren beim Regenerieren zusätzliche Sprachen.**
- **Daten-Fix (Web):** Die **authentische** deutsche 0.6.7-Beschreibung aus `e279e02` wurde in
  `public/appcast.xml` **wiederhergestellt** (kein Nach-Übersetzen). Achtung: Beim nächsten
  `generate_appcast`-Lauf geht sie erneut verloren, solange die Pipeline nicht gefixt ist.
- **Web-Fix (Defense-in-Depth):** `notesFor` fällt NICHT mehr auf eine *fremdsprachige* getaggte
  Description zurück. Neue Kette: **exakte Locale → ungetaggte `<description>` → nichts** (dann nur
  Version + Datum). Fällt künftig wieder eine Sprache weg, zeigt die lokalisierte Seite lieber nur
  Version + Datum, statt die andere Sprache zu leaken. Ungetaggte Descriptions (0.6.1 & älter)
  rendern unverändert für beide Sprachen.
- **Bitte an die App-Session:** `generate_appcast` so fixen, dass beim Regenerieren **alle Sprachen
  aller älteren Items erhalten bleiben** (DE Pflicht, EN erwünscht).
