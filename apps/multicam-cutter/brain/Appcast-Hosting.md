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

## Sparkle-Keys (Referenz)

- **Public-Key** (in der App, `SUPublicEDKey`): `kcPVTCojTVp36MscXhRzKlgyNAa/fkekxnoVfsxfRDY=`
- **Private-Key**: nur in meinem Login-Keychain, gesichert im Passwort-Manager.
  Kommt **nicht** an den Server (anders als der Lizenz-Private-Key).
- ⚠️ Sparkle-Keypair und Lizenz-Keypair NICHT verwechseln — zwei verschiedene Paare.

## Release-Notes / Changelog (eingebettet)

Die Update-Notizen kommen aus `CHANGELOG.md` und werden **in den Appcast
eingebettet**, nicht extern verlinkt:

- `scripts/changelog_to_html.py <version>` extrahiert den `## <version>`-Abschnitt
  und gibt ein HTML-Fragment aus (kein DOCTYPE/body).
- `release.sh` schreibt es als `release/updates/MultiCamCutter-<version>.html` —
  **gleicher Name wie das Archiv**. `generate_appcast --embed-release-notes`
  bettet es dann automatisch als `<description>` (CDATA) ins `<item>` ein.
- **Sparkle** zeigt die `<description>` im „Nach Update suchen"-Dialog.
- **Die Website** rendert dieselbe `<description>` automatisch ab dem nächsten
  Feed-Update (Contract der Web-Session, 22.07.) — keine weitere Absprache nötig.
- Die `.html` wird NICHT separat hochgeladen (sie steckt im Appcast) und nicht
  committet (`updates/` ist gitignored).
- **Fehlt der Abschnitt** in `CHANGELOG.md`, bricht `release.sh` ab (Exit 2 des
  Konverters) — kein stillschweigendes Release ohne Notizen.
