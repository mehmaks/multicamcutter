# Lizenz-API — Contract zwischen App und Backend

Vertrag zwischen **App** (Swift + Python-Engine) und **Backend** (Website-Session).
Zahlungsanbieter: **LemonSqueezy** (Merchant of Record + Lizenzschlüssel-API).
Modell: Abo + selbst-erneuernde, signierte **Lease** (siehe Entscheidungen.md).

Bei Änderungen hier: **beide Sessions** müssen mitziehen.

## Rollen

| Ebene | Aufgabe | Secrets |
|-------|---------|---------|
| LemonSqueezy | Abrechnung, Abo-Lifecycle, Key-Ausgabe, Aktivierungslimit, VAT | — |
| Backend | Key gegen LS prüfen → **signierte Lease** ausstellen | Lizenz-**Private-Key** (Ed25519), optional LS-API-Key für Webhooks |
| App | Key-Eingabe, Lease cachen + offline verifizieren, Refresh, Free-Tier | — (kein Client-Secret!) |

Die App hält **kein** Server-Secret (sie ist verteilt). Der Lizenzschlüssel
selbst ist das Credential. Endpoints daher public + rate-limited (per IP/Key).

## Endpoints

Live-Backend: `https://multicamcutter.pantake.com` (Next.js/Vercel).
Pfade unter `/api/` (NICHT der ursprüngliche Spec-Pfad `/v1/`). In `license.py`
via `_ACTIVATE_URL`/`_VALIDATE_URL`, Host über `TOOLKIT_LICENSE_API`.
Beide Endpoints teilen sich das Response-Schema. **E2E verifiziert** (Testkauf →
Key → activate → signierte Lease → App-Verifikation → validate + Offline-Grace).

### POST /api/license/activate  (Erststart, verbraucht einen Aktivierungs-Slot)

Request:
```json
{ "key": "XXXX-XXXX-XXXX-XXXX", "device_id": "<uuid>", "device_name": "MacBook Pro von Max" }
```
Backend → LS `POST /v1/licenses/activate` `{license_key, instance_name: device_id}`.
LS liefert `instance.id` (= unsere `activation_id`), `license_key.status`, `meta` (Email, Variant).

### POST /api/license/validate  (jeder Refresh, kein neuer Slot)

Request:
```json
{ "key": "XXXX-XXXX-XXXX-XXXX", "device_id": "<uuid>", "activation_id": "<ls-instance-id>" }
```
Backend → LS `POST /v1/licenses/validate` `{license_key, instance_id: activation_id}`.

### POST /api/license/deactivate  (Geräte-Wechsel — Slot freigeben)

**Backend deployt + App-Seite implementiert.** Self-Leave (Deaktivieren-Button →
`clear_license` → `deactivate {key, device_id, activation_id}`) und Takeover-Umzug
(`activation_limit` → „Auf dieses Gerät umziehen" → `migrate_license_key` →
`deactivate {key, device_id}` → `activate`) sind verdrahtet.
Der neue Mac kennt die alte `activation_id` nicht → Takeover per `device_id`.

Request (mind. eines von `activation_id` / `device_id`):
```json
{ "key": "XXXX-XXXX-XXXX-XXXX", "device_id": "<uuid>", "activation_id": "<optional>" }
```
- `activation_id` gesetzt → genau diese Aktivierung deaktivieren (Self-Leave).
- nur `device_id` → **Takeover**: alle ANDEREN Geräte-Aktivierungen (name != device_id)
  werden freigegeben.

Response (HTTP 200): `{ "status": "deactivated", "freed": <n> }` (freed = Anzahl
freigegebener Slots, 0 möglich). Negativ: `{ "status": "invalid"|"inactive"|
"device_mismatch", "message": "…" }`.

**Umzugs-Flow (App-Button „Auf dieses Gerät umziehen"):** `activate` →
`activation_limit` → `deactivate {key, device_id}` → `activate` (jetzt frei).

## Response (beide Endpoints, IMMER HTTP 200 bei Geschäftsergebnis)

Nur echte Infra-/Transportfehler → non-2xx. Damit unterscheidet die App sauber
"Server sagt Nein" von "Server nicht erreichbar" (→ Offline-Grace).

Aktiv:
```json
{
  "status": "active",
  "activation_id": "<ls-instance-id>",
  "lease": {
    "device_id": "<uuid>",
    "email": "max@example.com",
    "expires": "2026-08-01",
    "modules": ["multicam"],
    "valid": true,
    "sig": "<base64-ed25519>"
  },
  "subscription": {
    "status": "active",
    "renews_at": "2026-08-16",
    "ends_at": null,
    "card_last_four": "4242",
    "activation_usage": 2,
    "activation_limit": 3
  }
}
```

**`subscription`** (optional, INFORMATIV — nur Anzeige, NICHT signiert): Backend
holt das aus LemonSqueezys **Subscriptions-API** (`GET /v1/subscriptions/{id}`,
braucht LS-API-Key). Die App zeigt daraus das echte Abo-Datum an. Ohne diesen
Block zeigt die App kein Datum (das Lease-`expires` ist NUR das rollende Prüf-
Fenster, KEIN Abo-Ende — nie als „gültig bis" anzeigen).

| Feld | Bedeutung | App-Anzeige |
|------|-----------|-------------|
| `status` | active / on_trial / cancelled / past_due | — |
| `renews_at` | nächste Verlängerung (ISO date, null bei Kündigung) | „Verlängert sich am …" |
| `ends_at` | Zugriffsende bei Kündigung (ISO date, sonst null) | „Gekündigt — endet am …" (orange) |
| `card_last_four` | optional | (noch ungenutzt) |
| `activation_usage` | belegte Arbeitsplätze (int) | „Arbeitsplätze: 2 von 3 belegt" |
| `activation_limit` | Arbeitsplätze gesamt (int) | (Zeile nur bei Limit > 1) |

**NEU (24.07.) — Arbeitsplätze bei Mehrplatz-Lizenzen.** Backend reicht
`activation_usage` + `activation_limit` aus LemonSqueezys **`license_key`-Objekt**
durch — das steckt bereits in JEDER validate/activate-Antwort, es braucht also
**keinen zusätzlichen API-Call** (anders als die Subscriptions-Felder). Die
App-Seite ist fertig und zeigt die Zeile automatisch, sobald die Felder
ankommen; fehlen sie (älteres Backend), ändert sich nichts. Beide Felder sind
optional und unsigniert (nur Anzeige).

**Backend: umgesetzt & deployed (24.07.).** activate + validate liefern die
Seat-Felder im `subscription`-Block (Passthrough, auch auf den Reuse-Pfaden);
der Block kommt jetzt auch, wenn nur die Seats verfügbar sind (Datums-Felder
dann fehlend — App liest defensiv). `activation_limit`-Message mit Zahlen:
„Alle 3 Plätze dieser Lizenz sind belegt." bzw. bei Limit 1 „Der einzige Platz
dieser Lizenz ist bereits belegt." Bitte einmal mit eurem Test-Key gegenprüfen
(Mehrplatz-E2E braucht einen Key mit Limit > 1 bzw. Testkauf mit Menge > 1).

Negativ (kein `lease`):
```json
{ "status": "inactive" | "invalid" | "activation_limit" | "device_mismatch",
  "message": "Menschlich lesbarer Grund (Deutsch)" }
```
Beim Status `activation_limit` bitte die Zahlen in die `message` schreiben
(z. B. „Alle 3 Plätze dieser Lizenz sind belegt.") — die App zeigt die
`message` verbatim an, so wird auch der Fehlerfall konkret.

| status | Bedeutung | LS-Ursprung |
|--------|-----------|-------------|
| `active` | Abo läuft, Lease ausgestellt | `license_key.status == "active"` |
| `inactive` | gekündigt / fällig / abgelaufen | `expired` / `disabled` |
| `invalid` | Key unbekannt/falsch | LS 404 |
| `activation_limit` | zu viele Geräte | LS `activation_limit` erreicht |
| `device_mismatch` | activation_id passt nicht zum Key | — |

## Lease-Payload — Regeln

- **Reuse des bestehenden Formats** (`_canonical` in `license.py`/`keysign.py`),
  damit `_verify_signature` in der App unverändert bleibt.
- **`expires`** = `min(LS-Ablauf falls gesetzt, heute + LEASE_DAYS)`. Empfehlung
  **LEASE_DAYS = 7–14**. ISO-Datum (Tag-Granularität reicht). Das ist zugleich
  die Offline-Grace-Grenze — keine separate Grace-Logik nötig.
- **`device_id`** ist Teil des **signierten** Payloads → die App prüft zusätzlich
  `lease.device_id == _device_id()`. Bindet die Offline-Lease ans Gerät
  (kopierte Cache-Datei auf anderem Mac ist wertlos).
- **`modules`**: für diese App `["multicam"]`. Backend mappt LS-Variant → Module.
- **`valid`**: immer `true`.
- **KEIN `major_version`** in der Abo-Lease → `_check_major_version` gated dann
  nicht (Abo gilt versionsübergreifend). Erst wieder aufnehmen, wenn Major-
  Upgrades an Tarife gekoppelt werden sollen.

## Signaturformat (KRITISCH — byte-genau App↔Backend)

Ed25519 über einen **kanonischen String**. App: Python `str()`. Backend muss
diese Serialisierung exakt nachbauen — sonst schlägt die Verifikation fehl.

Algorithmus (`_canonical`):
1. `sig`-Feld entfernen.
2. Keys **alphabetisch** sortieren.
3. Pro Key `key=value`; Werte serialisieren:
   - String → wie-ist
   - Liste → **sortiert**, mit `,` gejoint (`["b","a"]` → `a,b`)
   - Bool → **`True` / `False`** (Python-Schreibweise, großes T/F!) ⚠️
   - Int → Dezimalstring
4. Alle mit `|` verketten.
5. `sig = base64( Ed25519_sign(private_key, canonical.encode("utf-8")) )`

⚠️ **Bool-Gotcha**: Python `str(True)` = `"True"`, JS `String(true)` = `"true"`.
Das Backend MUSS `valid=True` (großes T) in den kanonischen String schreiben.

### Test-Vektor (Backend gegen diesen String unit-testen)

Payload:
```json
{ "device_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
  "email": "max@example.com", "expires": "2026-08-01",
  "modules": ["multicam"], "valid": true }
```
Kanonischer String (exakt):
```
device_id=3f2504e0-4f89-11d3-9a0c-0305e82c3301|email=max@example.com|expires=2026-08-01|modules=multicam|valid=True
```

### Keys (Backend)

- **Private Key** (Ed25519, 32 Byte raw, base64) = `licensing/license_private.key`.
  Als Secret/Env-Var ins Backend, NIE ins Repo. In JS am einfachsten mit
  `@noble/ed25519` (`ed.sign(msgBytes, seedBytes)`), oder für Node-`crypto` den
  Raw-Seed als PKCS8 wrappen.
- **Public Key** liegt bereits in `license.py` (`_PUBLIC_KEY_B64`) — Server und
  App passen zusammen, sobald das Backend mit dem passenden Private Key signiert.

## Backend ↔ LemonSqueezy

- `activate`/`validate` (License-API) brauchen **keinen** LS-API-Key (Client-
  Endpoints, nur der Lizenzschlüssel).
- Für Abo-Status genügt `license_key.status`. Robuster: Webhooks
  (`subscription_updated`/`_cancelled`/`_expired`) → kleine DB synchron halten +
  Willkommens-/Kündigungs-Mails. Optional fürs MVP.
- Reinstall ohne gespeicherte `activation_id` würde einen neuen LS-Slot
  verbrauchen → Backend sollte per device_id bestehende Instance wiederverwenden
  ODER Aktivierungslimit großzügig setzen / alte deaktivieren.

## App-Verhalten (Kurz)

| Ergebnis | Reaktion |
|----------|----------|
| `active` | Lease speichern (`~/.resolve-toolkit/license.json`), `activation_id` sichern, unlock |
| `inactive` | Cached Lease bis `expires` weiter nutzen; danach "Abo abgelaufen — verlängern" |
| `invalid` | Key neu eingeben lassen |
| `activation_limit` | Hinweis + Link zur Geräteverwaltung |
| non-2xx / timeout | Cached Lease bis `expires` weiter (Offline-Grace) |
| kein Key hinterlegt | **Free-Tier** (längste Quelldatei ≤ 30 Min), kein Fehler |

Refresh-Trigger: bei App-Start; wenn `expires` < ~3 Tage entfernt, still erneuern.
Storage: `license.key` (Key), `activation.json` (activation_id), `license.json` (Lease).
Shipped-App: `TOOLKIT_LICENSE_MODE=remote`.
