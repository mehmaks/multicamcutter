# Telemetrie-API — Contract zwischen App und Backend (anonyme Nutzungsdaten)

Status: **ENTWURF (25.07.)** — Contract steht, App-Seite + Backend noch nicht gebaut.
Zweck der Telemetrie (User): Wie umfangreich sind die Projekte da draußen (eher
2-Cam-Setups oder komplexe Podcasts mit mehreren Cams/Gästen)? Und als Benchmark:
Wie lange dauert ein Durchlauf bei X Quellen à Y Länge — auf welcher Hardware?

## Rollen

- **App (native, wir):** erzeugt/hält eine anonyme `analytics_id`, zeigt den Opt-in-
  Prompt, sammelt NUR Zahlen/Enums, sendet **fire-and-forget** nach erfolgreichem Lauf.
- **Backend (Website-Session):** `POST /api/telemetry` annehmen + speichern/aggregieren.
  Frei, das intern mit einem fertigen Dienst (PostHog/Plausible) zu backen — der
  App-seitige Contract bleibt gleich.

## 🔒 Datenschutz — die drei harten Regeln (nicht verhandelbar)

1. **NIEMALS die `_device_id()` der Lizenz wiederverwenden.** Das würde Telemetrie mit
   Lizenz/E-Mail verknüpfbar machen → pseudonym statt anonym. Stattdessen eine eigene,
   rein zufällige `analytics_id` (UUID v4), nur lokal erzeugt, ohne jeden Lizenzbezug.
   Liegt in `@AppStorage("analyticsId")`. Getrennt vom Lizenz-Keychain.
2. **KEINE Namen, KEINE Pfade, KEINE Strings aus dem Projekt.** Episodenname
   („49 – Dr. …") und Pfade („/Volumes/…/2025 – Jena United/…") enthalten Kundennamen
   → DSGVO-Verstoß. Es werden AUSSCHLIESSLICH Zahlen und feste Enums gesendet.
3. **Widerruf jederzeit möglich.** Settings-Toggle (nicht nur der Erst-Prompt) + ein
   Datenschutz-Hinweis auf der Website. Aus = es wird nichts mehr gesendet.

## Endpoint

`POST {LicenseConfig.apiBase}/api/telemetry`  (Base wie Lizenz/Feedback:
`https://multicamcutter.pantake.com`). Kein Auth-Header nötig (anonym). Content-Type
`application/json`.

## Request (JSON) — NUR Zahlen/Enums

```json
{
  "analytics_id": "e3b0c442-…",        // zufällige UUID, KEIN Lizenz-/Geräte-ID-Bezug
  "app_version": "0.6.8",
  "event": "analysis_completed",         // nur nach erfolgreichem Lauf

  "sources": {
    "n_cams": 3,
    "n_mics": 3,
    "n_speakers": 3,                     // Personen (diarisiert) = zugeordnete Mics
    "total_source_s": 5280,              // Summe aller Quell-Dauern (Sekunden)
    "duration_min_s": 1600,              // kürzeste / mittlere / längste Quelle
    "duration_median_s": 1760,
    "duration_max_s": 1820
  },

  "runtime": {
    "elapsed_s": 1234,                   // Gesamtdauer (aus resultStats)
    "per_step_s": {                      // optional, aus step_start-Timestamps
      "nodding": 980, "cutaways": 140, "sync": 22, "base_edl": 8, "aaf": 3
    }
  },

  "preset": "Talk (entspannt)",          // NUR Built-in-Name; eigene Presets → "custom"
  "settings": {                          // KOMPLETTES Settings-Abbild = PipelineParams
    "min_shot": 2.3, "reaction_dur": 1.7, "max_shot": 14.0, "threshold_db": 6.0,
    "nodding_enabled": true, "speaking_enabled": true,
    "clip_filter_enabled": false, "crossbleed_gate_enabled": false,
    "totale_mode": "round_robin"
    // … die VOLLSTÄNDIGE PipelineParams-Menge (alles Zahlen/Enums). KEIN Freitext:
    //     Episodenname, Clipnamen-Muster und Pfade sind NICHT Teil davon.
  },

  "device": {
    "model": "Mac14,14",                 // ProcessInfo / sysctl hw.model
    "chip": "Apple M2 Ultra",            // voller Chip-Name (mit Leerzeichen) — wortgetreu gespeichert
    "cores": 24,
    "ram_gb": 64,
    "os": "macOS 15.1"
  }
}
```

⚠️ **Kontext ist Pflicht, sonst ist der Benchmark wertlos:** ohne `device` +
`settings` sind die `runtime`-Zahlen Rauschen (20 min auf M1 Air ≠ auf M3 Max; CLIP/
Nodding ändern die Laufzeit massiv). `preset` nur bei Built-ins (eigene → `"custom"`),
damit kein selbstvergebener Preset-Name (potenziell PII) durchrutscht.

## Feld-Regeln (Backend-Validierung — beantwortet App-Fragen, 26.07., E2E verifiziert)

Der PII-Backstop behandelt **`device.*`** und **`settings.*`** unterschiedlich:

- **`device.*` (chip, os, model): WORTGETREU gespeichert, Leerzeichen erlaubt.** `chip` =
  voller Name „Apple M2 Ultra", `os` = „macOS 15.1" bleiben unverändert (getestet). Der
  Token-/Whitespace-Filter gilt **NICHT** für `device.*` — nur Pfad-/Steuerzeichen (`/`,
  `\`, Zeilenumbrüche) und Überlänge werden abgewiesen. Caps: chip/os ≤ 48, model ≤ 64
  Zeichen (klar über realen Werten); `cores` 0–1024, `ram_gb` 0–4096. → **Benchmark ist
  sicher.**
- **`settings.*`-String-WERTE: Einzel-Token (KEIN Whitespace, ≤ 32 Zeichen, kein `/`/`\`).**
  Enums wie `round_robin` oder `16:9` bleiben; ein mehrwortiger Freitext (z. B. ein
  Episodenname „49 – Dr. …") wird als PII **verworfen**. Zahlen/Bools bleiben (Zahlen nur
  Range-gecappt). Falls ein legitimer Settings-Enum je ein Leerzeichen enthielte, würde er
  gedroppt — bei euren snake_case-Enums kein Problem.
- **`settings` darf verschachtelt sein:** Arrays (≤ 64 Elemente) und Objekte (Slug-Keys,
  ≤ 200 Keys) bis **Tiefe 2** werden übernommen; Elemente/Werte nach denselben Regeln
  bereinigt. `nodding_patterns` und `transition_cutaway_back` (auch als Array von Objekten)
  sind ok — **E2E getestet, kein Abflachen nötig.** Nur einzelne unpassende Werte (zu tief
  verschachtelt / Whitespace-String) fallen still weg, nie das ganze Objekt.
- **`preset`:** wie ein Label (Leerzeichen erlaubt, ≤ 64, kein Pfad). `analytics_id` muss
  UUID sein, sonst `null`. `app_version` = `[0-9A-Za-z.+-]`, ≤ 32.

**Datenschutz-URL (Consent-Prompt):** next-intl läuft mit **Always-Prefix** → die deutsche
Seite ist `https://multicamcutter.pantake.com/de/privacy` (EN: `/en/privacy`). `/privacy`
ohne Locale leitet per 307 auf den Default (EN) um. Der App-Link `…/de/privacy` ist **korrekt**.

## Response

`204 No Content` (oder `200 {}`). Die App wertet die Response **nicht** aus — der Call
ist fire-and-forget und darf den Lauf NIE blockieren oder scheitern lassen.

## Consent-UX (App)

- `@AppStorage("analyticsConsent")` — Typ `Bool?`: **nil = noch nie gefragt** → Opt-in-
  Prompt beim ersten Start (nach dem Erst-Start-Hinweis, eigener Dialog). Klar, was
  gesendet wird (Zahlen, keine Namen/Pfade) + Link zum Datenschutz-Hinweis.
- `true` = senden, `false` = nicht senden. Settings → Allgemein: Toggle „Anonyme
  Nutzungsdaten senden" (spiegelt denselben Key) → **Widerruf**.
- Default bei Ablehnung/nil: **nichts senden**. Kein heimliches Sammeln.

## App-Verhalten (Kurz)

1. Nach `result` (erfolgreicher Lauf) **und** `analyticsConsent == true`: Payload aus
   `resultStats["elapsed_s"]`, `cameraInfos`/`micInfos` (Dauern), `params` (Flags),
   `SystemInfo` (device) bauen — **nur Zahlen**, keine Dateinamen.
2. `URLSession`-POST (Muster: `Feedback.swift`), fire-and-forget, Fehler ignorieren.
3. `analytics_id` einmalig lokal erzeugen, nie an Lizenz koppeln.

## Backend-Status (Website-Seite)

**GEBAUT (26.07., Web-Session) — lokal E2E verifiziert, Deploy steht noch aus.**

- **Storage:** eigene **Neon-Postgres** (Vercel-Marketplace-Integration `neon`,
  Ressource `neon-celeste-compass`), Region **eu-central-1 / Frankfurt** (Data
  Residency für ein DE/EU-Produkt — bewusst KEIN us-east-1, kein Dritt-Tracker wie
  PostHog). `DATABASE_URL` von der Integration ins Vercel-Projekt injiziert. Tabelle
  `telemetry_events` (Schema: `scripts/telemetry-schema.sql` im Web-Repo). **KEINE
  IP** gespeichert (Regel 1+2).
- **Endpoint:** `POST /api/telemetry` (`src/app/api/telemetry/route.ts`) → antwortet
  wie vereinbart **204**, fire-and-forget, wirft nie zum Caller. Schutz (offener
  Endpoint): In-Memory-Rate-Limit pro IP (30/10 min), harte Body-Größen-Grenze (64 KB),
  strikte Validierung.
- **PII-Backstop (Regel 2), serverseitig, unabhängig von der App:** nur
  Zahlen/Bools/kurze Enums werden gespeichert. `settings`-String-Werte müssen
  Einzel-Token sein (KEIN Whitespace, ≤32 Zeichen) → ein Episodenname („49 – Dr. …")
  wird verworfen; alles mit `/` oder `\` (Pfade) fliegt raus; `preset` mit Pfad → null.
  Zahlen außerhalb sinnvoller Ranges → null. Verifiziert: ein Testpayload mit
  Episodenname + Pfaden landete bereinigt in der DB.
- **Optionaler Client-Token:** env `TELEMETRY_CLIENT_TOKEN` (standardmäßig AUS → bleibt
  anonym/ohne Auth, wie im Contract). Falls später aktiviert, muss die App den Header
  **`x-telemetry-token: <token>`** mitsenden — bis dahin keine App-Änderung nötig.
- **Auswertung:** fertige SQL-Queries (Projekt-Komplexität + Runtime-Benchmark pro
  Hardware) in `scripts/telemetry-queries.sql` (Web-Repo), für die Neon-SQL-Konsole.
- **Datenschutz-Hinweis (Regel 3):** neue Seite `/{locale}/privacy` (DE/EN) auf der
  Website beschreibt Telemetrie (freiwillig, abschaltbar, anonym, EU-Storage, kein
  Dritt-Tracker) + lokale Verarbeitung, Lizenz/LemonSqueezy, Feedback/GitHub. Footer-
  Link „Datenschutz/Privacy" verdrahtet. Kontakt-Mail auf der Seite ist noch ein
  Platzhalter (`datenschutz@pantake.com`); Impressum (DE-Pflicht) + anwaltliche Prüfung
  stehen noch aus.

**Offen:** commit + deploy; ggf. eine kleine token-geschützte Stats-Seite statt SQL-
Konsole.
