# Feedback-API — Contract zwischen App und Backend (Bug-Reports)

Vertrag zwischen **App** (SwiftUI) und **Backend** (Website-Session). Zweck:
In-App „Feedback / Fehler melden" → Backend legt ein **GitHub Issue** an.

Bei Änderungen hier: **beide Sessions** müssen mitziehen.

## Rollen

| Ebene | Aufgabe | Secrets |
|-------|---------|---------|
| App | Formular, sammelt Kontext (Log, System-Infos), POST an den Endpoint | — (kein Secret!) |
| Backend | Request validieren → **GitHub Issue anlegen** (Titel/Body/Labels), großes Log als Gist | **GitHub-Token** (Env-Secret) |
| GitHub | Issue-Tracker (Repo vom Backend konfiguriert) | — |

Die App hält **kein** GitHub-Token (sie ist verteilt → wäre sofort geleakt). Der
Endpoint ist public → **rate-limiten** (per IP) gegen Spam. Optional ein
Turnstile/hCaptcha-Token oder ein obfuskierter Client-Header als niedrige Hürde
(Design-Entscheidung Backend; die App kann bei Bedarf einen statischen Header senden).

## Endpoint

`POST /api/feedback` — gleicher Host wie die Lizenz-API
(`https://multicamcutter.pantake.com`, Next.js/Vercel). Die App baut die URL aus
`LicenseConfig.apiBase + "/api/feedback"`.

### Request (JSON)
```json
{
  "summary":       "kurze Betreff-Zeile (Pflicht)",
  "description":   "Freitext: was ist passiert / erwartet",
  "email":         "optional@tester.de",
  "kind":          "bug",              // "bug" | "feedback"
  "source":        "manual",           // "manual" | "error"
  "error_message": "",                 // gesetzt wenn source=error
  "app_version":   "0.1.0 (1)",
  "os_version":    "macOS 26.5.1",
  "device_model":  "Mac14,14",
  "episode":       "49 - Vorname Nachname",
  "log":           "…stdout/JSONL der letzten Analyse, ggf. gekürzt…",
  "log_truncated": true                // true wenn App das Log gekappt hat
}
```
- **Pflicht**: mindestens `summary` ODER `description` nicht leer. Rest optional.
- `log` ist leer, wenn der Tester „Log anhängen" abgewählt hat. App kappt bei
  **~100 KB** (`log_truncated=true`). Das reicht i.d.R. für den relevanten Teil.

### Was das Backend daraus macht (GitHub Issue)
- **Titel**: `[bug] <summary> — <episode>` (bzw. `[feedback] …`).
- **Body** (Markdown):
  - `description`
  - Sektion **System**: `app_version`, `os_version`, `device_model`, `episode`,
    `email` (falls da), `source`.
  - Falls `source=error`: `error_message` in einem ```-Codeblock.
  - **Log**: in einem `<details><summary>Analyse-Log</summary>`-Block als Code.
    ⚠️ GitHub-Issue-Body max **65536 Zeichen** → ist das Log (oder gesamt) größer,
    Log als **Gist** anlegen und nur den Link ins Issue setzen.
- **Labels**: `bug` bzw. `feedback`, plus z.B. `from-app`.
- Repo: das vom Backend konfigurierte Issues-Repo (mit User abstimmen).

### Response
Erfolg (HTTP 200):
```json
{ "status": "ok", "issue_url": "https://github.com/OWNER/REPO/issues/123", "number": 123 }
```
Die App zeigt dann „Danke! Report #123 angelegt" + Link.

Fehler: non-2xx (mit `{ "status": "error", "message": "…" }`). Die App zeigt den
Fehler + Fallback „Details kopieren" (Tester kann den Report dann per Mail schicken).

## Datenschutz-Hinweis (App zeigt das dem Tester)
`log`, `episode` und ggf. `error_message` enthalten **Dateipfade/-namen** des Testers
(z.B. `/Volumes/Jardani/Projekte/…`). Das Log-Anhängen ist im Formular ein Toggle
(Default an) mit sichtbarem Hinweis. Kein Screenshot, keine `.multicam` (bewusst).

## App-Verhalten (Kurz)
| Ereignis | Reaktion |
|----------|----------|
| 200 + issue_url | „Report #NNN angelegt", Link zum Issue, Schließen |
| non-2xx / timeout | Fehlerhinweis + „Erneut senden" + „Details kopieren" (E-Mail-Fallback) |
| Aufruf aus Fehler-Screen | `source=error`, `error_message` + Log vorausgefüllt |

## Backend-Status (Website-Seite — implementiert & deployed)

`POST /api/feedback` ist live auf `https://multicamcutter.pantake.com`.

- **Issue-Repo:** `mehmaks/resolve-toolkit` (Env `FEEDBACK_GITHUB_REPO`). Labels:
  `bug`/`feedback` + `from-app` (werden bei Bedarf automatisch angelegt).
- **Token:** Env `FEEDBACK_GITHUB_TOKEN` — Fine-Grained-PAT, nur `Issues: read/write`
  auf dieses Repo (least privilege), NIE im Repo.
- **Großes Log:** Der Contract nannte einen **Gist**. Ich hänge das Log stattdessen als
  **Issue-Kommentar(e)** an (in 60k-Blöcken), wenn der Body die 65536-Zeichen-Grenze
  sprengt. Grund: bleibt im selben Repo → ein enger Fine-Grained-Token reicht (Gists
  bräuchten einen breiten Classic-Token mit `gist`-Scope). **Für die App ändert sich
  nichts** — die Response (`issue_url`/`number`) ist identisch. Nur diese Notiz zur Info.
- **Validierung:** mind. `summary` ODER `description` (sonst HTTP 400). Body-Cap 65536
  wird eingehalten (notfalls Truncation).
- **Rate-Limit:** best-effort in-memory per IP (8 / 10 min) → HTTP 429. Reicht als Spam-
  Hürde; für härteres Limit später ein KV-Store (Upstash) nachrüstbar.
- **Optionaler Client-Header:** `x-feedback-token` (Env `FEEDBACK_CLIENT_TOKEN`). **Aktuell
  AUS** (Env leer → kein Header nötig, App funktioniert sofort). Wenn wir das als niedrige
  Hürde einschalten wollen: Wert abstimmen, die App sendet dann `x-feedback-token: <wert>`.
- **Fehler-Responses:** 400 (Validierung), 401 (Header falsch, wenn aktiv), 429 (Rate-Limit),
  500 (Backend nicht konfiguriert), 502 (GitHub-Fehler) — je `{ "status":"error","message":… }`.
