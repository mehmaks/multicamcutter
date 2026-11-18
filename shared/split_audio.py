"""
Gesplittete Audioaufnahmen erkennen und fuer die Analyse zusammenfuegen.

Rekorder wie der Zoom H6essential beginnen nach einer festen Dateigroesse/
Laufzeit automatisch eine neue Datei (z. B. 1 GB → neue WAV). Die Teile gehoeren
zu EINER Spur/Person. Fuer die Analyse wird jede Gruppe zu einer temporaeren WAV
zusammengefuegt (samplegenau, ohne Neuberechnung); die Pipeline sieht dann eine
durchgehende Datei. Der AAF-Export loest die temporaere WAV ueber die Manifest-
Datei (`<joined>.parts.json`) wieder in die Originalteile auf — die temporaere
WAV landet nie im Schnittprojekt.

Erkennung OHNE Dateinamen:
  1. Zeit: Broadcast-WAV `bext.time_reference` (Samples ab Mitternacht). Teil B
     folgt auf A, wenn B exakt dort beginnt, wo A endet (gleiches Format, gleicher
     Rekorder laut `bext.originator`).
  2. Spur: Bei Mehrspur-Rekordern beginnen mehrere Folgeteile zur selben Zeit.
     Welcher zu welcher Spur gehoert, entscheidet der Uebergang im Signal: der
     richtige Folgeteil setzt die Wellenform nahtlos fort (Praediktionsfehler am
     Uebergang ~1–3x normal), ein falscher springt (~70x, gemessen an Folge 59).
  3. Nur wenn das Signal nichts entscheidet (digitale Stille), dient die
     Namensaehnlichkeit als Tie-Break.
"""

import hashlib
import json
import os
import shutil
import re
import struct
import tempfile
from itertools import permutations
from pathlib import Path

import numpy as np

# Toleranz fuer "beginnt exakt am Ende des Vorgaengers" (Samples).
_TIME_TOLERANCE = 2
# Vorhersagefehler am Uebergang relativ zum typischen Fehler (seam_score). Ein
# nahtloser Uebergang liegt statistisch bei ~1 (Folge 59: 1,06/1,10; falsche
# Paare 16–18). Ab _SEAM_MAX gilt ein Paar bei MEHREREN Kandidaten nicht mehr
# als nahtlos; gibt es nur EINEN zeitlich passenden Kandidaten, reicht die
# Zeitgleichheit, und nur ein klarer Sprung (_SEAM_SINGLE_MAX) verhindert ihn.
_SEAM_MAX = 3.0
_SEAM_SINGLE_MAX = 10.0
# Mindestabstand zwischen gewaehlter und naechstbester Alternative (Faktor),
# damit die Signal-Entscheidung als eindeutig gilt.
_SEAM_MARGIN = 2.0
_SEAM_WINDOW = 4096          # Samples je Seite fuer die Uebergangspruefung

_WAVE_FORMAT_PCM = 1
_WAVE_FORMAT_FLOAT = 3
_WAVE_FORMAT_EXTENSIBLE = 0xFFFE

MANIFEST_SUFFIX = ".parts.json"


# ── Temp-Ordner ──────────────────────────────────────────────────────────────

def join_dir() -> Path:
    """Ordner fuer die temporaeren WAVs. Die App setzt `MCC_JOIN_DIR` und loescht
    den Ordner beim Beenden (und beim naechsten Start, falls sie abstuerzte)."""
    d = os.environ.get("MCC_JOIN_DIR")
    p = Path(d) if d else Path(tempfile.gettempdir()) / "MultiCamCutter-joined"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── WAV/BWF-Header lesen ─────────────────────────────────────────────────────

def read_wav_info(path):
    """Liest die Chunk-Struktur einer WAV/RF64. Gibt None zurueck, wenn die Datei
    keine lesbare WAV ist. `time_ref` ist None ohne bext-Chunk."""
    try:
        f = open(path, "rb")
    except OSError:
        return None
    with f:
        head = f.read(12)
        if len(head) < 12:
            return None
        riff, _, wave = struct.unpack("<4sI4s", head)
        if riff not in (b"RIFF", b"RF64") or wave != b"WAVE":
            return None
        chunks = []          # (id, bytes) aller Nicht-data-Chunks in Dateireihenfolge
        ds64_data_len = None
        data_off = data_len = None
        while True:
            h = f.read(8)
            if len(h) < 8:
                break
            cid, size = struct.unpack("<4sI", h)
            if cid == b"data":
                data_off = f.tell()
                data_len = size
                if riff == b"RF64" and size == 0xFFFFFFFF and ds64_data_len is not None:
                    data_len = ds64_data_len
                break
            body = f.read(size + (size & 1))
            if cid == b"ds64" and len(body) >= 16:
                ds64_data_len = struct.unpack("<Q", body[8:16])[0]
            chunks.append((cid, body[:size]))
    cmap = dict(chunks)
    fmt = cmap.get(b"fmt ")
    if fmt is None or data_off is None or len(fmt) < 16:
        return None
    tag, channels, sr, _, block_align, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == _WAVE_FORMAT_EXTENSIBLE and len(fmt) >= 26:
        tag = struct.unpack("<H", fmt[24:26])[0]   # SubFormat-GUID, erste 2 Bytes
    if block_align <= 0:
        return None
    size_on_disk = os.path.getsize(path)
    data_len = min(data_len, max(0, size_on_disk - data_off))
    info = {
        "path": str(path),
        "format": tag, "channels": channels, "sample_rate": sr,
        "bits": bits, "block_align": block_align,
        "data_off": data_off, "data_len": data_len,
        "n_samples": data_len // block_align,
        "time_ref": None, "originator": "", "description": "",
        "coding_history": "", "ixml": "",
        "chunks": chunks,
    }
    bext = cmap.get(b"bext")
    if bext is not None and len(bext) >= 346:
        lo, hi = struct.unpack("<II", bext[338:346])
        info["time_ref"] = lo + (hi << 32)
        info["originator"] = bext[256:288].split(b"\0")[0].decode("latin1").strip()
        info["description"] = bext[0:256].split(b"\0")[0].decode("latin1")
        info["coding_history"] = bext[602:].split(b"\0")[0].decode("latin1")
    ixml = cmap.get(b"iXML")
    if ixml:
        info["ixml"] = ixml.split(b"\0")[0].decode("utf-8", "replace")
    info["recorder"] = _identify_recorder(info)
    info["profile"] = match_recorder_profile(info)
    info["rec_track"] = _extract_track_id(info, info["profile"])
    return info


# ── Rekorder-Erkennung + Regeldatenbank ─────────────────────────────────────
# Welche Regeln je Geraet gelten, steht in config/recorder_profiles.json (Doku:
# config/recorder_profiles.md). Fehlt/defekt → _BUILTIN_DEFAULT (= Verhalten ohne
# Profil: Zeit + Nahtsignal + Namen).

_PROFILE_SOURCES = ("originator", "coding_history", "description", "ixml")
_STEPS = ("track", "signal", "name")
_BUILTIN_DEFAULT = {"id": "generic", "name": "Unbekannter Rekorder",
                    "split_detection": {"steps": ["signal", "name"]}}
_profiles_cache = None


def _load_profiles():
    """(profiles, default) aus der Regeldatenbank; einmal je Prozess."""
    global _profiles_cache
    if _profiles_cache is not None:
        return _profiles_cache
    profiles, default = [], _BUILTIN_DEFAULT
    try:
        from shared.paths import effective_recorder_profiles_path
        data = json.loads(effective_recorder_profiles_path().read_text(encoding="utf-8"))
        for p in data.get("profiles", []):
            if _valid_profile(p):
                profiles.append(p)
        if _valid_profile(data.get("default", {}), need_match=False):
            default = data["default"]
    except Exception:
        pass                                   # defekt/fehlend → eingebaute Regeln
    _profiles_cache = (profiles, default)
    return _profiles_cache


def _valid_profile(p, need_match=True) -> bool:
    if not isinstance(p, dict) or not p.get("id"):
        return False
    steps = p.get("split_detection", {}).get("steps")
    if not isinstance(steps, list) or any(s not in _STEPS for s in steps):
        return False
    try:
        if need_match:
            m = p.get("match")
            if not isinstance(m, dict) or not m or any(k not in _PROFILE_SOURCES for k in m):
                return False
            for rx in m.values():
                re.compile(rx)
        t = p.get("track_id")
        if t is not None:
            if t.get("source") not in _PROFILE_SOURCES:
                return False
            if re.compile(t["pattern"]).groups < 1:
                return False
    except (re.error, KeyError, TypeError, AttributeError):
        return False
    return True


def _identify_recorder(info) -> dict:
    """Geraet aus den Metadaten: Originator (bext) + Modell/Firmware aus der
    Coding History (`T=…`, `VERSION=…`, so bei Zoom)."""
    ch = info.get("coding_history", "")
    model = re.search(r"(?:^|[;,\s])T=([^;,\r\n]+)", ch)
    fw = re.search(r"(?:^|[;,\s])VERSION=([^;,\r\n]+)", ch)
    return {"originator": info.get("originator", ""),
            "model": model.group(1).strip() if model else "",
            "firmware": fw.group(1).strip() if fw else ""}


def match_recorder_profile(info) -> dict:
    """Erstes Profil, dessen `match`-Regex alle passen; sonst das Default-Profil."""
    profiles, default = _load_profiles()
    for p in profiles:
        if all(re.search(rx, info.get(src, "") or "") for src, rx in p["match"].items()):
            return p
    return default


def _extract_track_id(info, profile):
    t = profile.get("track_id")
    if not t:
        return None
    m = re.search(t["pattern"], info.get(t["source"], "") or "")
    return m.group(1) if m else None


def describe_recorder(path) -> dict:
    """Diagnose: erkanntes Geraet, Profil und Spur-Kennung einer Datei."""
    i = read_wav_info(path)
    if not i:
        return {"path": str(path), "error": "keine lesbare WAV"}
    return {"path": str(path), "recorder": i["recorder"],
            "profile": i["profile"]["id"], "track_id": i["rec_track"],
            "steps": i["profile"]["split_detection"]["steps"],
            "has_bext": i["time_ref"] is not None, "has_ixml": bool(i["ixml"])}


def _same_format(a, b) -> bool:
    return all(a[k] == b[k] for k in
               ("format", "channels", "sample_rate", "bits", "block_align"))


def _read_frames(info, start, n):
    """Liest n Frames ab `start` als float64-Array (frames × channels)."""
    ba, ch, bits = info["block_align"], info["channels"], info["bits"]
    with open(info["path"], "rb") as f:
        f.seek(info["data_off"] + start * ba)
        raw = f.read(n * ba)
    n = len(raw) // ba
    raw = raw[:n * ba]
    bps = ba // ch if ch else 0
    if info["format"] == _WAVE_FORMAT_FLOAT and bps in (4, 8):
        x = np.frombuffer(raw, dtype="<f4" if bps == 4 else "<f8").astype(np.float64)
    elif bps == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    elif bps == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = np.where(v & 0x800000, v - 0x1000000, v).astype(np.float64)
    elif bps == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float64)
    elif bps == 1:
        x = np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0
    else:
        return None
    return x.reshape(n, ch)


_LPC_ORDER = 32


def _lpc_cross_error(ctx, cont, order=_LPC_ORDER):
    """Lineare Vorhersage (Ordnung `order`), angepasst auf `ctx`. Gibt das
    Verhaeltnis RMS(Vorhersagefehler der ersten `order` Samples von `cont`, mit
    der echten Vorgeschichte ueber die Naht hinweg) / RMS(Restfehler in `ctx`)
    zurueck. None, wenn nicht berechenbar."""
    n = len(ctx)
    if n <= 4 * order or len(cont) < order:
        return None
    # Regressionsmatrix: x[t] ~ Σ c_k · x[t-k]
    rows = np.lib.stride_tricks.sliding_window_view(ctx[:-1], order)[:, ::-1]
    target = ctx[order:]
    coef, *_ = np.linalg.lstsq(rows, target, rcond=None)
    resid = target - rows @ coef
    base = np.sqrt(np.mean(resid ** 2))
    if base <= 0:
        return None
    x = np.concatenate([ctx[-order:], cont[:order]])
    hist = np.lib.stride_tricks.sliding_window_view(x[:-1], order)[:, ::-1]
    err = x[order:] - hist @ coef
    return float(np.sqrt(np.mean(err ** 2)) / base)


def seam_score(a, b):
    """Wie nahtlos setzt b das Signal von a fort? Lineare Vorhersage, auf dem Ende
    von a angepasst, sagt den Anfang von b voraus (und rueckwaerts: Anfang von b
    → Ende von a). Verhaeltnis zum typischen Vorhersagefehler, gemittelt ueber
    beide Richtungen, Median ueber die Kanaele. ~1 = nahtlos, ein Sprung ergibt
    ein Vielfaches. None, wenn nicht entscheidbar (digitale Stille, unlesbar)."""
    w = _SEAM_WINDOW
    tail = _read_frames(a, max(0, a["n_samples"] - w), w)
    head = _read_frames(b, 0, w)
    if tail is None or head is None or len(tail) < 8 or len(head) < 8:
        return None
    ratios = []
    for c in range(tail.shape[1]):
        t, h = tail[:, c], head[:, c]
        fwd = _lpc_cross_error(t, h)
        bwd = _lpc_cross_error(h[::-1], t[::-1])
        vals = [v for v in (fwd, bwd) if v is not None]
        if vals:
            ratios.append(float(np.mean(vals)))
    if not ratios:
        return None
    return float(np.median(ratios))


def _name_similarity(a: str, b: str) -> int:
    """Laenge des gemeinsamen Endes zweier Dateinamen (ohne Endung) — nur als
    Tie-Break, z. B. '…_Tr1' ↔ '…_Tr1'."""
    a, b = Path(a).stem.lower(), Path(b).stem.lower()
    n = 0
    while n < min(len(a), len(b)) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


def _match_by_track(preds, succs):
    """Zuordnung ueber den Rekorder-Eingang (`rec_track`, z. B. Zoom TRK=3).
    Nur wenn ALLE Kandidaten einen haben und er je Seite eindeutig ist — sonst
    None (→ Signal/Namen). Paare nur bei gleichem Eingang."""
    tp = [p["rec_track"] for p in preds]
    ts = [s["rec_track"] for s in succs]
    if None in tp or None in ts or len(set(tp)) != len(tp) or len(set(ts)) != len(ts):
        return None
    by_track = {s["rec_track"]: s for s in succs}
    return [(p, by_track[p["rec_track"]]) for p in preds if p["rec_track"] in by_track]


def _match_seam(preds, succs):
    """Ordnet Vorgaenger ↔ Nachfolger an EINER Nahtstelle zu. Gibt [(pred, succ)]
    zurueck — nur eindeutige Paare. Welche Schritte in welcher Reihenfolge gelten,
    legt das Rekorder-Profil fest (alle Kandidaten haben denselben Originator,
    siehe _fmt_key → dasselbe Profil)."""
    steps = preds[0]["profile"]["split_detection"]["steps"]

    # track: Spur-Kennung aus den Metadaten — eindeutig, wenn vorhanden. Das
    # Signal dient nur noch als Sicherung gegen einen klaren Sprung.
    if "track" in steps:
        by_track = _match_by_track(preds, succs)
        if by_track is not None:
            out = []
            for p, s in by_track:
                sc = seam_score(p, s) if "signal" in steps else None
                if sc is None or sc <= _SEAM_SINGLE_MAX:
                    out.append((p, s))
            return out

    if len(preds) == 1 and len(succs) == 1:
        if "signal" in steps:
            s = seam_score(preds[0], succs[0])
            if s is not None and s > _SEAM_SINGLE_MAX:
                return []                      # Zeit passt, Signal springt → lieber nicht
        return [(preds[0], succs[0])]

    use_name = "name" in steps
    if "signal" in steps:
        result = _match_by_signal(preds, succs, use_name)
        if result is not None:
            return result
    # Signal nicht entscheidbar / nicht vorgesehen → Namen, nur eindeutig
    if use_name:
        return [(preds[i], succs[j]) for i, j in _match_by_name(preds, succs)]
    return []


def _match_by_signal(preds, succs, use_name):
    """Nahtpruefung im Audio. None = nicht entscheidbar (digitale Stille o. ae.)."""
    scores = [[seam_score(p, s) for s in succs] for p in preds]
    decidable = all(v is not None for row in scores for v in row)
    if not decidable or len(preds) > 7 or len(succs) > 7:
        return None

    # Beste Gesamtzuordnung (kleine N → alle Permutationen)
    n = min(len(preds), len(succs))
    best, best_cost = None, float("inf")
    if len(preds) <= len(succs):
        for perm in permutations(range(len(succs)), n):
            cost = sum(np.log1p(scores[i][j]) for i, j in enumerate(perm))
            if cost < best_cost:
                best, best_cost = [(i, j) for i, j in enumerate(perm)], cost
    else:
        for perm in permutations(range(len(preds)), n):
            cost = sum(np.log1p(scores[i][j]) for j, i in enumerate(perm))
            if cost < best_cost:
                best, best_cost = [(i, j) for j, i in enumerate(perm)], cost
    pairs = [(i, j) for i, j in best if scores[i][j] <= _SEAM_MAX]
    # Eindeutig: jede gewaehlte Paarung klar besser als jede Alternative in
    # ihrer Zeile. Sonst lieber gar nicht verbinden (→ manuelle Zuordnung).
    ok = []
    for i, j in pairs:
        others = [scores[i][k] for k in range(len(succs)) if k != j]
        if not others or min(others) >= scores[i][j] * _SEAM_MARGIN:
            ok.append((preds[i], succs[j]))
    if len(ok) == len(pairs):
        return ok
    if not use_name:
        return []
    # Signal nicht eindeutig (z. B. Raumrauschen an der Naht: alle Paare ~1,
    # Folge 61). Dann entscheiden die Namen — aber nur, wo das Signal ihnen
    # nicht widerspricht: Namenspaar == Paar der besten Gesamtzuordnung und
    # als nahtlos bewertet. Sonst lieber nicht verbinden (→ manuell).
    best_set = set(best)
    return [(preds[i], succs[j]) for i, j in _match_by_name(preds, succs)
            if (i, j) in best_set and scores[i][j] <= _SEAM_MAX]


def _match_by_name(preds, succs):
    """Eindeutige Zuordnung ueber das gemeinsame Namensende ('…_Tr1' ↔ '…_Tr1').
    Gibt [(pred_idx, succ_idx)] zurueck."""
    out, used = [], set()
    for i, p in enumerate(preds):
        sims = [(_name_similarity(p["path"], s["path"]), idx) for idx, s in enumerate(succs)]
        sims.sort(reverse=True)
        if sims and sims[0][0] > 0 and (len(sims) == 1 or sims[0][0] > sims[1][0]) \
                and sims[0][1] not in used:
            used.add(sims[0][1])
            out.append((i, sims[0][1]))
    return out


def detect_split_groups(paths):
    """Gruppiert Audiodateien zu Ketten zusammengehoeriger Teile.

    Gibt eine Liste von Gruppen zurueck (je Gruppe die Pfade in Aufnahme-
    reihenfolge). Einzeldateien bilden eine Gruppe der Laenge 1. Die Reihenfolge
    der Gruppen folgt dem ersten Teil in der Eingabereihenfolge."""
    paths = [str(p) for p in paths]
    infos = {p: read_wav_info(p) for p in paths}
    timed = [i for i in infos.values() if i and i["time_ref"] is not None and i["n_samples"] > 0]

    # Nahtstellen sammeln: Endzeit → Vorgaenger, Startzeit → Nachfolger
    succ_of = {}
    by_end = {}
    for a in timed:
        by_end.setdefault(a["time_ref"] + a["n_samples"], []).append(a)
    for end, preds in by_end.items():
        succs = [b for b in timed
                 if abs(b["time_ref"] - end) <= _TIME_TOLERANCE
                 and all(b["path"] != p["path"] for p in preds)]
        if not succs:
            continue
        # Format + Rekorder muessen passen; je Format getrennt zuordnen
        for p_fmt in {(_fmt_key(p)) for p in preds}:
            ps = [p for p in preds if _fmt_key(p) == p_fmt]
            ss = [s for s in succs if _fmt_key(s) == p_fmt]
            if ps and ss:
                for p, s in _match_seam(ps, ss):
                    if s["path"] not in succ_of.values():
                        succ_of[p["path"]] = s["path"]

    has_pred = set(succ_of.values())
    groups = []
    for p in paths:
        if p in has_pred:
            continue
        chain, cur, seen = [p], p, {p}
        while cur in succ_of and succ_of[cur] not in seen:
            cur = succ_of[cur]
            chain.append(cur)
            seen.add(cur)
        groups.append(chain)
    return groups


def _fmt_key(i):
    return (i["format"], i["channels"], i["sample_rate"], i["bits"],
            i["block_align"], i["originator"])


def order_manual_group(paths):
    """Vom Nutzer zusammengefasste Teile ("gehoert zu ...") pruefen und ordnen.

    Anders als bei der Erkennung gibt es keine Zeit-/Nahtpruefung — der Nutzer
    entscheidet. Pflicht ist nur gleiches Audioformat, sonst waere die Gesamt-WAV
    Datenmuell. Reihenfolge: nach bext-Zeitstempel, wenn ALLE Teile einen haben,
    sonst wie uebergeben. Wirft ValueError mit lesbarer Begruendung."""
    paths = [str(p) for p in paths]
    infos = [read_wav_info(p) for p in paths]
    for p, i in zip(paths, infos):
        if i is None:
            raise ValueError(f"{Path(p).name} ist keine WAV-Datei")
    fmt = lambda i: (i["format"], i["channels"], i["sample_rate"], i["bits"], i["block_align"])
    desc = lambda i: f"{i['sample_rate']} Hz / {i['bits']} bit / {i['channels']} ch"
    for p, i in zip(paths[1:], infos[1:]):
        if fmt(i) != fmt(infos[0]):
            raise ValueError(f"{Path(p).name} passt nicht zu {Path(paths[0]).name}: "
                             f"anderes Audioformat ({desc(i)} statt {desc(infos[0])})")
    if all(i["time_ref"] is not None for i in infos):
        order = sorted(range(len(paths)), key=lambda k: infos[k]["time_ref"])
        return [paths[k] for k in order]
    return paths


# ── Zusammenfuegen ───────────────────────────────────────────────────────────

def _group_key(parts) -> str:
    raw = []
    for p in parts:
        st = os.stat(p)
        raw.append(f"{p}|{st.st_size}|{st.st_mtime}")
    return hashlib.sha256("\n".join(raw).encode()).hexdigest()[:16]


def manifest_path(joined) -> Path:
    return Path(str(joined) + MANIFEST_SUFFIX)


def load_parts(path):
    """Teile einer zusammengefuegten WAV laut Manifest, sonst None.
    Je Teil: {"path", "start_sample", "n_samples", "sample_rate"}."""
    m = manifest_path(path)
    if not m.exists():
        return None
    try:
        data = json.loads(m.read_text(encoding="utf-8"))
        parts = data.get("parts") or []
        return parts if len(parts) > 1 else None
    except Exception:
        return None


def join_group(parts, out_dir=None, progress_cb=None):
    """Fuegt die Teile zu EINER WAV zusammen (Header des ersten Teils, Daten aller
    Teile hintereinander). Ergebnis wird nach Datei-Identitaet gecacht.
    Gibt den Pfad der zusammengefuegten WAV zurueck."""
    parts = [str(p) for p in parts]
    infos = [read_wav_info(p) for p in parts]
    if any(i is None for i in infos):
        raise RuntimeError("Teil einer gesplitteten Aufnahme ist keine lesbare WAV")
    first = infos[0]

    target_dir = Path(out_dir or join_dir()) / _group_key(parts)
    target_dir.mkdir(parents=True, exist_ok=True)
    joined = target_dir / Path(parts[0]).name
    total_data = sum(i["data_len"] for i in infos)

    manifest = {
        "parts": [],
        "sample_rate": first["sample_rate"],
        "recorder": first.get("recorder", {}),
        "profile": first.get("profile", {}).get("id", ""),
    }
    cursor = 0
    for i in infos:
        manifest["parts"].append({
            "path": i["path"], "start_sample": cursor,
            "n_samples": i["n_samples"], "sample_rate": i["sample_rate"],
        })
        cursor += i["n_samples"]

    mpath = manifest_path(joined)
    if joined.exists() and mpath.exists():
        try:
            info = read_wav_info(joined)
            if info and info["data_len"] == total_data:
                return str(joined)
        except Exception:
            pass

    # Header: alle Chunks des ersten Teils ausser Fuell-Chunks; 'fact' (Sample-
    # Anzahl, bei Float-WAVs) auf die Gesamtlaenge setzen.
    keep = []
    for cid, body in first["chunks"]:
        if cid in (b"JUNK", b"PAD ", b"ds64", b"FLLR", b"junk"):
            continue
        if cid == b"fact" and len(body) >= 4:
            body = struct.pack("<I", min(cursor, 0xFFFFFFFF)) + body[4:]
        keep.append((cid, body))

    def _chunk_bytes(cid, body):
        return struct.pack("<4sI", cid, len(body)) + body + (b"\0" if len(body) & 1 else b"")

    header_body = b"".join(_chunk_bytes(c, b) for c, b in keep)
    rf64 = 12 + 36 + len(header_body) + 8 + total_data > 0xFFFFFFFF
    tmp = joined.with_suffix(joined.suffix + ".part")
    with open(tmp, "wb") as out:
        if rf64:
            riff_size = 4 + 36 + len(header_body) + 8 + total_data
            ds64 = struct.pack("<QQQI", riff_size, total_data, cursor, 0)
            out.write(struct.pack("<4sI4s", b"RF64", 0xFFFFFFFF, b"WAVE"))
            out.write(_chunk_bytes(b"ds64", ds64))
            out.write(header_body)
            out.write(struct.pack("<4sI", b"data", 0xFFFFFFFF))
        else:
            riff_size = 4 + len(header_body) + 8 + total_data
            out.write(struct.pack("<4sI4s", b"RIFF", riff_size, b"WAVE"))
            out.write(header_body)
            out.write(struct.pack("<4sI", b"data", total_data))
        done = 0
        for i in infos:
            with open(i["path"], "rb") as src:
                src.seek(i["data_off"])
                remaining = i["data_len"]
                while remaining > 0:
                    buf = src.read(min(64 << 20, remaining))
                    if not buf:
                        break
                    out.write(buf)
                    remaining -= len(buf)
                    done += len(buf)
                    if progress_cb:
                        progress_cb(done / total_data if total_data else 1.0)
        if total_data & 1:
            out.write(b"\0")
    os.replace(tmp, joined)
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(joined)


def resolve_split_audio(paths, progress_cb=None):
    """Erkennt Split-Gruppen und ersetzt jede Gruppe durch ihre zusammengefuegte
    WAV. Gibt (neue_pfadliste, {joined_pfad: [teil_pfade]}) zurueck.
    `progress_cb(label, frac)` meldet den Fortschritt beim Zusammenfuegen."""
    groups = detect_split_groups(paths)
    out, joined_map = [], {}
    for g in groups:
        if len(g) == 1:
            out.append(g[0])
            continue
        name = Path(g[0]).name
        cb = (lambda frac, _n=name: progress_cb(_n, frac)) if progress_cb else None
        j = join_group(g, progress_cb=cb)
        out.append(j)
        joined_map[j] = g
    return out, joined_map


def cleanup_join_dir():
    """Loescht alle temporaeren WAVs (fuer Tests/CLI; die App macht das selbst)."""
    shutil.rmtree(join_dir(), ignore_errors=True)
