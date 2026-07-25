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
    "chip": "arm64",
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

**OFFEN.** Zu bauen: `POST /api/telemetry` + Storage/Auswertung. Empfehlung: hinter dem
Endpoint einen fertigen Dienst (PostHog/Plausible/eigene DB) — Entscheidung liegt bei
der Web-Session; der App-Contract oben bleibt davon unberührt. Datenschutz-Hinweis auf
der Website ergänzen (Regel 3).
