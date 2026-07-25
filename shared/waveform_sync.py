"""
Waveform-based audio synchronization.

Calculates frame offsets between audio sources using cross-correlation.
No Resolve required — works purely on audio files and embedded camera audio.

Typical use:
    offsets = sync_sources([cam1_video, cam2_video], [mic1_wav, mic2_wav])
    # Returns frame offsets relative to CAM1 for all sources.
"""

import subprocess
import tempfile
import os
import numpy as np
from pathlib import Path
from dataclasses import dataclass


SAMPLE_RATE   = 8000    # Hz — low enough for fast correlation, high enough for speech
CHUNK_SECONDS = 180     # Initial analysis window: 3 minutes
CHUNK_STEP    = 180     # Expand by 3 minutes if confidence too low
MIN_CONFIDENCE = 5.0    # Peak must be MIN_CONFIDENCE × median of correlation


# ── Audio extraction ──────────────────────────────────────────────────────────

def extract_audio(source_path: str, duration_s: float = None) -> np.ndarray:
    """
    Extracts mono audio from a video or audio file via ffmpeg.
    Returns a float32 numpy array at SAMPLE_RATE.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", source_path,
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "-vn",
    ]
    if duration_s:
        cmd += ["-t", str(duration_s)]

    cmd += ["-f", "f32le", "-"]

    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg fehlgeschlagen für {source_path}:\n"
            + result.stderr.decode(errors="replace")[-500:]
        )

    audio = np.frombuffer(result.stdout, dtype=np.float32)
    return audio


# ── Cross-correlation ─────────────────────────────────────────────────────────

def _correlate_offset(ref: np.ndarray, target: np.ndarray) -> tuple[int, float]:
    """
    Computes the sample offset of `target` relative to `ref` via FFT cross-correlation.
    Returns (offset_samples, confidence).
    Positive offset = target starts later than ref.
    """
    from scipy.signal import correlate

    # Normalize both signals to avoid amplitude bias
    ref    = ref    / (np.std(ref)    + 1e-9)
    target = target / (np.std(target) + 1e-9)

    corr = correlate(ref, target, method="fft")
    peak_idx    = int(np.argmax(corr))
    peak_val    = corr[peak_idx]
    confidence  = float(peak_val / (np.median(np.abs(corr)) + 1e-9))

    # Convert peak index to signed sample offset
    # correlate() output: index len(target)-1 = zero-lag
    offset_samples = peak_idx - (len(target) - 1)

    return offset_samples, confidence


def _samples_to_frames(samples: int, fps: float) -> int:
    return round(samples / SAMPLE_RATE * fps)


# ── Public API ────────────────────────────────────────────────────────────────

@dataclass
class SyncResult:
    ref_label: str           # e.g. "CAM1"
    target_label: str        # e.g. "CAM2"
    offset_frames: int       # positive = target starts this many frames AFTER ref
    offset_seconds: float
    confidence: float
    analyzed_seconds: float  # how much audio was used


@dataclass
class UnsyncableSource:
    """Eine Quelle, die sich nicht verlaesslich automatisch einordnen liess.
    Nur relevant im collect_unsyncable-Modus (Baustein 2): dann sammelt
    sync_sources diese statt abzubrechen, damit die App pro Quelle manuell
    setzen / ausschliessen / abbrechen anbieten kann."""
    label: str                    # internes Label, z.B. "MIC3"
    filename: str                 # Datei, wie der Nutzer sie kennt
    reason: str                   # menschenlesbar: warum unsicher
    best_confidence: float        # wie schwach die beste Messung war
    candidate_offset_frames: int  # bester Schaetzwert (auf CAM1=0 normiert), fuers manuelle Vorbelegen


class SyncError(Exception):
    pass


def _sync_pair(
    ref_path: str,
    target_path: str,
    ref_label: str,
    target_label: str,
    fps: float,
    cache: dict = None,
    start_duration: float = None,
) -> SyncResult:
    """
    Synchronisiert eine Quelle gegen eine Referenz.

    ASYMMETRISCHE FENSTER: Das ZIEL liefert den Inhalt zum Wiedererkennen —
    3 Minuten reichen dafuer. Die REFERENZ bestimmt den durchsuchbaren
    Versatzbereich, denn correlate(mode="full") findet nur Lags bis zu ihrer
    Laenge. Beide gleich kurz zu halten war der Fehler: ein Kamera-Fragment,
    das 30 min in die Aufnahme hinein beginnt, ist mit einer 3-Minuten-Referenz
    nicht auffindbar — die Fenster haben nicht einmal gemeinsamen Inhalt.

    ZIEL-FENSTER AB DER LAUTESTEN STELLE (Fallback): Das Ziel-Chunk kommt zuerst
    vom Anfang (schnell, deckt den Normalfall). Bleibt die Confidence dort flach
    unter TRUST, liegt das oft daran, dass der Traeger im ersten Fenster kaum
    spricht — ein inhaltsleeres Chunk findet keinen Gipfel, egal wie gross die
    Referenz wird. Dann wird das Chunk aus der ENERGIEREICHSTEN Region des Ziels
    genommen und der Versatz um diese Verschiebung korrigiert.

    Erweitert wird bis TRUST_CONFIDENCE, nicht bis MIN_CONFIDENCE: 14x ist
    Rauschen, das die 5.0 muehelos passiert. Ist das Referenzmaterial
    erschoepft, wird das BESTE gefundene Ergebnis zurueckgegeben (sofern
    ueberhaupt ueber MIN_CONFIDENCE) — die Gegenpruefung in sync_sources
    entscheidet dann, ob es tragfaehig ist.
    """
    target_duration = start_duration or CHUNK_SECONDS
    max_ref         = _probe_duration(ref_path) or target_duration * 8

    def _measure(target_audio, chunk_start_samples, note=""):
        """Referenzfenster wachsen lassen, das FESTE Ziel-Chunk korrelieren.
        Gibt (bestes SyncResult, ob TRUST erreicht) zurueck. Der Versatz ist um
        chunk_start_samples korrigiert (das Chunk begann erst spaeter im Ziel)."""
        ref_duration = target_duration
        best = None
        while True:
            print(f"  {ref_label} ↔ {target_label}: {target_duration:.0f}s{note} gegen "
                  f"{ref_duration:.0f}s Referenz ...", end=" ", flush=True)
            if cache is not None and (ref_path, ref_duration) in cache:
                ref_audio = cache[(ref_path, ref_duration)]
            else:
                ref_audio = extract_audio(ref_path, duration_s=ref_duration)
                if cache is not None:
                    cache[(ref_path, ref_duration)] = ref_audio

            offset_samples, confidence = _correlate_offset(ref_audio, target_audio)
            offset_samples -= chunk_start_samples   # Chunk-Verschiebung herausrechnen
            result = SyncResult(
                ref_label=ref_label,
                target_label=target_label,
                offset_frames=_samples_to_frames(offset_samples, fps),
                offset_seconds=offset_samples / SAMPLE_RATE,
                confidence=confidence,
                analyzed_seconds=ref_duration,
            )
            if best is None or confidence > best.confidence:
                best = result

            if confidence >= TRUST_CONFIDENCE:
                print(f"Confidence: {confidence:.1f}x ✓ → Offset: "
                      f"{result.offset_frames:+d} frames ({result.offset_seconds:+.3f}s)")
                return result, True
            if ref_duration >= max_ref:
                print(f"Confidence: {confidence:.1f}x (bestes: {best.confidence:.1f}x)")
                return best, False
            print(f"Confidence: {confidence:.1f}x — erweitere Referenzfenster")
            # Verdoppeln statt linear: der gesuchte Versatz kann Stunden betragen.
            ref_duration = min(ref_duration * 2, max_ref)

    # 1) Ziel-Auftakt (schnell, unveraenderter Normalfall).
    result, trusted = _measure(extract_audio(target_path, duration_s=target_duration), 0)

    # 2) Fallback: schwacher Auftakt → Chunk aus der lautesten Region des Ziels.
    #    Nur wenn dahinter ueberhaupt mehr Material liegt. Der ganze Ziel-Ton wird
    #    dafuer einmal dekodiert; das passiert nur im Ausnahmefall.
    if not trusted:
        full = extract_audio(target_path)
        win = int(round(target_duration * SAMPLE_RATE))
        if len(full) > win + SAMPLE_RATE:
            start = _loudest_window_start(full, win)
            if start > 0:
                alt, alt_trusted = _measure(full[start:start + win], start,
                                            note=f" ab {start / SAMPLE_RATE:.0f}s")
                if alt.confidence > result.confidence:
                    result, trusted = alt, alt_trusted

    if result.confidence < MIN_CONFIDENCE:
        raise SyncError(
            f"Kein verlaesslicher Sync fuer {ref_label} ↔ {target_label} "
            f"(beste Confidence {result.confidence:.1f}x bei {max_ref:.0f}s "
            f"Referenzmaterial). Bitte manuell synchronisieren."
        )
    if not trusted:
        print(f"  {ref_label} ↔ {target_label}: bestes Ergebnis "
              f"{result.offset_frames:+d} frames ({result.confidence:.1f}x) — wird gegengeprueft")
    return result


def _loudest_window_start(audio: np.ndarray, win_samples: int) -> int:
    """Startindex (Samples) des energiereichsten Fensters der Laenge win_samples.
    Grobes 1-Sekunden-Raster — reicht, um die sprechreiche Region zu finden, und
    ist auch fuer stundenlange Dateien schnell."""
    n = len(audio)
    if n <= win_samples:
        return 0
    block = SAMPLE_RATE  # 1s-Raster
    nblocks = n // block
    win_blocks = max(1, win_samples // block)
    if nblocks <= win_blocks:
        return 0
    energy = (audio[:nblocks * block].reshape(nblocks, block) ** 2).sum(axis=1)
    csum = np.concatenate([[0.0], np.cumsum(energy.astype(np.float64))])
    window_energy = csum[win_blocks:] - csum[:-win_blocks]   # Energie je Startblock
    return int(np.argmax(window_energy)) * block


def _probe_duration(path: str) -> float:
    """Laenge in Sekunden, 0.0 wenn nicht ermittelbar."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True
    )
    try:
        return float(probe.stdout.strip())
    except ValueError:
        return 0.0


# Toleranz der Kreuzprobe. 2 Frames decken Rundung auf Frame-Raster ab
# (jede Messung rundet einmal), alles darueber ist ein echter Widerspruch.
CROSSCHECK_TOLERANCE_FRAMES = 2

# Faktor fuers Nachmessen der schwaechsten Quelle bei uneiniger Kreuzprobe.
# 4x180s = 12 min deckt auch lange Vorlaeufe ab, ohne den Normalfall zu bremsen
# (es greift nur nach einem Widerspruch).
RETRY_WINDOW_FACTOR = 4

# Untergrenze fuer eine sinnvolle Korrelation. Bewusst niedrig: eine kurze
# Quelle laesst sich seit dem Wegfall der min_len-Kuerzung sauber einordnen,
# solange die REFERENZ lang genug ist. Kuerzer als das ist es Rauschen.
MIN_SOURCE_SECONDS = 10.0

# Ab dieser Confidence gilt eine EINZELMESSUNG als belastbar. Darunter wird die
# Quelle ueber einen zweiten Weg gegengeprueft.
#
# MIN_CONFIDENCE (5.0) ist die Schwelle zum Weitersuchen, nicht zum Vertrauen:
# gemessen wurde eine Totale, die bei JEDEM Fenster ~12x lieferte und dabei
# Offsets zwischen -478 und +111 Frames -- reines Rauschen, das die 5.0 muehelos
# passiert. Eine gleichbleibend niedrige Confidence bei wachsendem Fenster ist
# das Erkennungsmerkmal: es gibt keinen echten Korrelationsgipfel.
TRUST_CONFIDENCE = 50.0


def sync_sources(
    cam_paths: list[str],
    mic_paths: list[str],
    fps: float = 25.0,
    reference: str = None,
    mics_same_recorder: bool = False,
    collect_unsyncable: bool = False,
    manual_offsets: dict = None,
) -> "dict[str, int] | tuple[dict[str, int], list[UnsyncableSource]]":
    """
    Ermittelt Sync-Offsets fuer BELIEBIG VIELE Kameras und Mikrofone.

    Rueckgabe: {label: offset_frames}, label = CAM1..CAMn / MIC1..MICm.
      CAM1 ist immer 0 (Normalisierung), positiv = startet spaeter als CAM1.

    Jede Quelle wird EINZELN gegen eine Referenz gemessen. Vorher galt:
    CAM1<->CAM2 und CAM1<->MIC1 gemessen, alle weiteren Mikrofone bekamen
    ungeprueft MIC1s Offset und Kameras ab Nr. 3 gar keinen (blieben still
    auf 0). Beides erzeugte lautlos asynchrones Material.

    Referenz ist standardmaessig das LAENGSTE MIKROFON, nicht CAM1: Mikrofone
    laufen meist durch, waehrend Kameras zwischendurch stoppen oder splitten —
    eine Quelle, die alle anderen zeitlich ueberlappt, ist die verlaesslichere
    Bezugsgroesse. Am Ende wird auf CAM1 = 0 normalisiert, damit EDL, AAF und
    `_cam_shift` unveraendert weiterrechnen.

    mics_same_recorder: Bestaetigt der Nutzer (Wizard-Checkbox), dass ALLE
    Mikrofone aus EINEM Mehrspur-Recorder stammen, teilen sie sich zwangslaeufig
    eine Clock und damit denselben Offset. Eine still aufgenommene Spur (der
    Traeger schweigt im Analysefenster) korreliert dann nicht — statt daran den
    ganzen Lauf abzubrechen, erbt sie den Offset der Referenz. Gut korrelierte
    Mikrofone behalten ihre Messung; weicht eine deutlich ab, kommt eine Warnung.

    collect_unsyncable (Baustein 2): Statt bei nicht verlaesslich einordenbaren
    Quellen den ganzen Lauf mit SyncError abzubrechen, werden diese gesammelt und
    die Funktion gibt (offsets, [UnsyncableSource, ...]) zurueck. offsets enthaelt
    fuer JEDE Quelle einen Best-Effort-Wert, die Liste nennt die unsicheren — die
    App laesst den Nutzer dann pro Problemquelle manuell setzen / ausschliessen /
    abbrechen. Graceful werden die beiden KREUZVALIDIERUNGS-Abbrueche
    (CAM1<->CAM2-Kreuzprobe und die Zwei-Wege-Gegenpruefung). Reine Eingabefehler
    (Datei zu kurz, gar keine Korrelation < MIN_CONFIDENCE) bleiben auch hier
    HARTE Fehler mit klarer, dateibenennender Meldung. Ohne das Flag ist alles
    unveraendert (raise + Rueckgabe dict).

    manual_offsets (Baustein 3): {Pfad: Frames}. Diese Quellen werden NICHT
    korreliert — der Wert (Frames relativ zu CAM1) wird direkt uebernommen und die
    Quelle aus Referenzwahl, Kreuzprobe und Gegenpruefung herausgehalten. Pfad-
    basiert, weil interne Labels (CAM2/MIC3) bei Re-Runs mit Ausschluessen
    verrutschen.
    """
    sources: dict[str, str] = {}
    for i, path in enumerate(cam_paths, start=1):
        sources[f"CAM{i}"] = path
    for i, path in enumerate(mic_paths, start=1):
        sources[f"MIC{i}"] = path

    if "CAM1" not in sources:
        raise SyncError("Mindestens eine Kamera wird benoetigt (CAM1 fehlt).")

    # Manuell gesetzte Offsets (Baustein 3), pfadbasiert -> Label. Diese Quellen
    # werden weder gemessen noch gegengeprueft; ihr Offset wird am Ende direkt
    # eingesetzt (CAM1 = Null-Anker bleibt ausgenommen).
    manual = manual_offsets or {}
    manual_by_label = {label: int(manual[path])
                       for label, path in sources.items() if path in manual}

    # ── Quellen auf plausible Laenge pruefen ──
    # Die Korrelation braucht ein Fenster von CHUNK_SECONDS. Ist eine Quelle
    # kuerzer, wird intern auf ihre Laenge gekappt (min_len in _sync_pair) und
    # das Ergebnis ist bestenfalls Glueckssache — mehr Material anzufordern hilft
    # dann nicht, weil es keines gibt.
    #
    # Aufgefallen an einer abgebrochenen FPS-Konvertierung, die als 94-Sekunden-
    # Fragment liegen blieb (Original: 99 min) und beim Scan als vollwertige
    # Kamera uebernommen wurde. Der Konverter prueft seine Ausgabe inzwischen
    # selbst, aber eine unvollstaendige Datei kann auch anders entstehen —
    # abgebrochener Kopiervorgang, halb geladene Cloud-Datei, Altbestand.
    durations = {label: _probe_duration(path) for label, path in sources.items()}
    longest = max(durations.values()) if durations else 0.0
    # Hart abbrechen nur, wenn eine Korrelation sinnlos waere. Alles darueber
    # kann die Korrelation seit dem Wegfall der min_len-Kuerzung selbst
    # bewaeltigen — und eine Kamera, die nur zeitweise lief, ist legitim.
    unusable = {l: d for l, d in durations.items()
                if 0 < d < MIN_SOURCE_SECONDS and l not in manual_by_label}
    if unusable:
        lines = "\n".join(
            f"    {l}: {d:.1f} s  ({Path(sources[l]).name})"
            for l, d in sorted(unusable.items())
        )
        raise SyncError(
            f"Quelle(n) zu kurz fuer eine Korrelation (unter {MIN_SOURCE_SECONDS:.0f} s):\n{lines}\n"
            f"    laengste Quelle: {longest / 60:.1f} min"
        )
    # Deutlich kuerzer als der Rest ist verdaechtig, kann aber stimmen (Kamera
    # lief nur zeitweise). Deshalb nur ein Hinweis, kein Abbruch.
    for label, d in sorted(durations.items()):
        if longest and d < longest * 0.5:
            print(f"  ⚠ {label} ist mit {d / 60:.1f} min deutlich kuerzer als die "
                  f"laengste Quelle ({longest / 60:.1f} min). Der Sync kommt damit "
                  f"zurecht — falls die Datei aber unvollstaendig ist (abgebrochene "
                  f"Konvertierung o. ae.), fehlt sie spaeter im Schnitt.")

    # ── Referenz waehlen ──
    if reference is not None:
        if reference not in sources:
            raise SyncError(f"Referenz '{reference}' ist keine der Quellen: "
                            f"{', '.join(sources)}")
        ref_label = reference
    else:
        mic_labels = [l for l in sources if l.startswith("MIC")
                      and l not in manual_by_label]
        if mic_labels:
            ref_label = max(mic_labels, key=lambda l: _probe_duration(sources[l]))
        else:
            ref_label = "CAM1"
    ref_path = sources[ref_label]

    def _name(label: str) -> str:
        return Path(sources[label]).name

    print("Waveform-Sync gestartet")
    print(f"  Referenz: {ref_label} ({_name(ref_label)})")
    print(f"  Quellen ({len(sources)}) — welche Datei welches Label ist:")
    for _label in sources:
        print(f"    {_label} = {_name(_label)}")
    print(f"  FPS: {fps}")
    if mics_same_recorder:
        print("  Mehrspur-Recorder bestaetigt: alle Mikrofone teilen sich eine "
              "Clock (stille Spuren werden nicht einzeln korreliert).")
    print()

    # ── Jede Quelle einzeln gegen die Referenz ──
    rel: dict[str, int] = {ref_label: 0}
    confidences: dict[str, float] = {}
    sibling_assigned: set[str] = set()
    unsyncable: dict[str, UnsyncableSource] = {}   # collect_unsyncable-Modus, per Label dedupliziert
    ref_cache: dict = {}
    for label, path in sources.items():
        if label == ref_label:
            continue
        if label in manual_by_label:
            continue   # manuell gesetzt — nicht korrelieren
        result = _sync_pair(ref_path, path, ref_label, label, fps, cache=ref_cache)
        rel[label] = result.offset_frames
        confidences[label] = result.confidence

    # ── Mehrspur-Geschwister: gemeinsamer Offset statt Einzelkorrelation ──
    # Bei bestaetigtem Ein-Recorder-Setup teilen sich alle Mikrofone eine Clock.
    # Ein still aufgenommenes Mikro korreliert nicht — es erbt dann den Offset der
    # Referenz (die selbst ein Mikro ist), statt den Lauf zum Absturz zu bringen.
    # Gut korrelierte Mikros behalten ihre Messung; weicht eine trotz "ein
    # Recorder" deutlich von der Referenz ab, ist die Angabe fuer dieses Mikro
    # vermutlich falsch → Warnung, aber Messung wird respektiert. Kameras bleiben
    # unberuehrt (eigene Geraete, echte Korrelation).
    if mics_same_recorder and ref_label.startswith("MIC"):
        mic_labels = [l for l in sources if l.startswith("MIC")
                      and l not in manual_by_label]
        if len(mic_labels) >= 2:
            for label in mic_labels:
                if label == ref_label:
                    continue
                if confidences.get(label, 0.0) >= TRUST_CONFIDENCE:
                    drift = rel[label] - rel[ref_label]
                    if abs(drift) > CROSSCHECK_TOLERANCE_FRAMES:
                        print(f"  ⚠ {label} ({_name(label)}) misst {drift:+d} Frames gegen "
                              f"die Referenz, obwohl als Recorder-Geschwister erklaert "
                              f"(erwartet 0). Nutze die Messung — stammt {label} aus einem "
                              f"anderen Geraet, Checkbox pruefen.")
                else:
                    rel[label] = rel[ref_label]
                    sibling_assigned.add(label)
                    print(f"  {label} ({_name(label)}) = Recorder-Geschwister → Offset der "
                          f"Referenz {ref_label} uebernommen (nicht einzeln korreliert)")

    # ── Baustein 1: schwache Quellen gegen ALLE sicheren Partner retten ──
    # Bisher wurde jede Quelle nur gegen die eine Referenz gemessen. Eine
    # Close-Mic teilt mit einem fernen Referenz-Mikro aber oft wenig gemeinsamen
    # Klang — dafuer viel mit der KAMERA ihrer Person. Korreliert eine Quelle
    # schwach gegen die Referenz (< TRUST), wird sie darum gegen jede bereits
    # sichere Quelle (Confidence >= TRUST, Kameras eingeschlossen) gemessen.
    # Findet eine davon einen echten Gipfel (>= TRUST), wird deren Offset — in
    # die Referenz umgerechnet (rel[partner] + Messung) — uebernommen; die
    # sicherste Bezugsquelle zuerst.
    #
    # Laeuft NUR fuer schwache Quellen: sind alle >= TRUST (Normalfall), ist
    # dieser Block ein No-op und der Sync bleibt Bit fuer Bit unveraendert.
    # Nur ein echter Gipfel rettet — bleibt jede Gegenmessung unter TRUST, wird
    # die Quelle NICHT angefasst und faellt in die Gegenpruefung unten (die den
    # Lauf heute noch abbricht; Baustein 2 macht daraus eine „nicht syncbar"-Liste).
    weak_labels = [l for l, c in confidences.items()
                   if c < TRUST_CONFIDENCE and l not in sibling_assigned]
    for label in weak_labels:
        orig_conf = confidences[label]
        partners = sorted(
            (l for l, c in confidences.items()
             if c >= TRUST_CONFIDENCE and l != label),
            key=lambda l: confidences[l], reverse=True,
        )
        for partner in partners:
            probe = _sync_pair(sources[partner], sources[label], partner, label, fps)
            if probe.confidence >= TRUST_CONFIDENCE:
                rel[label] = rel[partner] + probe.offset_frames
                confidences[label] = probe.confidence
                print(f"  {label} ({_name(label)}) korreliert mit Referenz "
                      f"{ref_label} nur {orig_conf:.1f}x → ueber {partner} "
                      f"({_name(partner)}) gerettet: {probe.confidence:.1f}x, "
                      f"Offset {rel[label]:+d} Frames (gegen {ref_label})")
                break

    # ── Auf CAM1 = 0 normalisieren ──
    cam1_rel = rel["CAM1"]
    offsets = {label: value - cam1_rel for label, value in rel.items()}

    # ── Kreuzprobe: CAM1<->CAM2 unabhaengig nachmessen ──
    # Beide Kameras wurden gegen die Referenz gemessen; ihre Differenz muss zu
    # einer DIREKTEN Messung passen. Weicht sie ab, hat mindestens eine der
    # Korrelationen auf ein falsches Maximum gezeigt — das faellt sonst erst
    # im schon geschnittenen Material auf.
    if ("CAM2" in sources and ref_label not in ("CAM1", "CAM2")
            and "CAM2" not in manual_by_label):
        direct = _sync_pair(sources["CAM1"], sources["CAM2"], "CAM1", "CAM2", fps)
        ref_cache.clear()   # ab hier nicht mehr gebraucht
        drift = abs(direct.offset_frames - offsets["CAM2"])

        if drift > CROSSCHECK_TOLERANCE_FRAMES:
            # Nicht sofort aufgeben. Die Confidence zeigt, WELCHE Messung
            # verdaechtig ist — die schwaechste. Ursache ist fast immer zu wenig
            # ueberlappendes Material (Rekorder liefen vor den Kameras), und
            # dagegen hilft schlicht ein groesseres Fenster.
            suspect = min(confidences, key=confidences.get)
            print(f"  ⚠ Kreuzprobe uneinig ({drift} Frames Abweichung).")
            print(f"    Schwaechste Messung: {ref_label} ↔ {suspect} "
                  f"({confidences[suspect]:.1f}x) — messe mit mehr Material nach...")
            retry = _sync_pair(ref_path, sources[suspect], ref_label, suspect, fps,
                               cache=ref_cache,
                               start_duration=CHUNK_SECONDS * RETRY_WINDOW_FACTOR)
            if retry.confidence > confidences[suspect]:
                rel[suspect] = retry.offset_frames
                confidences[suspect] = retry.confidence
                cam1_rel = rel["CAM1"]
                offsets = {l: v - cam1_rel for l, v in rel.items()}
                drift = abs(direct.offset_frames - offsets["CAM2"])
                if drift <= CROSSCHECK_TOLERANCE_FRAMES:
                    print(f"    ✓ behoben — {suspect} jetzt {retry.offset_frames:+d} "
                          f"Frames bei {retry.confidence:.1f}x")

        if drift > CROSSCHECK_TOLERANCE_FRAMES:
            if collect_unsyncable:
                # CAM2s Platzierung widerspricht der direkten Messung. CAM1 ist der
                # Null-Anker, darum wird CAM2 als unsicher gemeldet; als Best-Effort
                # dient die DIREKTE (unabhaengige) Messung CAM1<->CAM2.
                unsyncable["CAM2"] = UnsyncableSource(
                    label="CAM2", filename=_name("CAM2"),
                    reason=(f"Kreuzprobe CAM1↔CAM2 uneinig: ueber {ref_label} "
                            f"{offsets['CAM2']:+d} Frames, direkt gemessen "
                            f"{direct.offset_frames:+d} Frames (Abweichung {drift}). "
                            f"Meist ein langer Vorlauf ohne gemeinsames Material."),
                    best_confidence=confidences.get("CAM2", 0.0),
                    candidate_offset_frames=direct.offset_frames,
                )
            else:
                raise SyncError(
                    f"Kreuzprobe fehlgeschlagen: ueber {ref_label} ({_name(ref_label)}) "
                    f"ergibt CAM2 ({_name('CAM2')}) {offsets['CAM2']:+d} Frames, direkt "
                    f"gemessen {direct.offset_frames:+d} Frames "
                    f"(Abweichung {drift} Frames, erlaubt {CROSSCHECK_TOLERANCE_FRAMES}).\n"
                    f"Mindestens eine Korrelation hat ein falsches Maximum getroffen; "
                    f"Nachmessen mit mehr Material hat es nicht aufgeloest.\n"
                    f"Haeufigste Ursache: eine Quelle hat einen langen Vorlauf, sodass "
                    f"die Analysefenster kaum gemeinsames Material enthalten."
                )
        else:
            print(f"  Kreuzprobe CAM1 ↔ CAM2: ✓ (Abweichung {drift} Frames)")

    # ── Schwache Messungen ueber einen zweiten Weg gegenpruefen ──
    # Die Kreuzprobe oben deckt nur CAM2 ab. Jede andere Quelle koennte mit
    # duerftiger Confidence einen Zufallswert liefern, ohne dass es auffaellt —
    # und Offsets sind genau die Sorte Zahl, die man dem fertigen Schnitt nicht
    # mehr ansieht.
    unreliable = []
    for label, conf in sorted(confidences.items(), key=lambda kv: kv[1]):
        if conf >= TRUST_CONFIDENCE:
            continue
        if label in sibling_assigned:
            continue  # bewusst der Referenz-Offset zugewiesen, keine echte Messung
        # Als Pruefer die sicherste ANDERE Quelle nehmen.
        others = [l for l in confidences if l != label]
        if not others:
            continue
        verifier = max(others, key=lambda l: confidences[l])
        check = _sync_pair(sources[verifier], sources[label], verifier, label, fps)
        via_verifier = rel[verifier] + check.offset_frames
        spread = abs(via_verifier - rel[label])
        if spread > CROSSCHECK_TOLERANCE_FRAMES:
            unreliable.append((label, conf, rel[label] - rel["CAM1"],
                               via_verifier - rel["CAM1"], verifier, spread))
        else:
            print(f"  {label} gegengeprueft ueber {verifier}: ✓ "
                  f"(Abweichung {spread} Frames)")

    if unreliable:
        if collect_unsyncable:
            for l, c, a, b, v, sp in unreliable:
                if l in unsyncable:
                    continue  # bereits durch die Kreuzprobe erfasst
                unsyncable[l] = UnsyncableSource(
                    label=l, filename=_name(l),
                    reason=(f"Zwei Wege uneinig: ueber {ref_label} {a:+d} Frames, "
                            f"ueber {v} {b:+d} Frames (Abweichung {sp}). Confidence "
                            f"nur {c:.1f}x — kein echter Korrelationsgipfel."),
                    best_confidence=c,
                    candidate_offset_frames=a,   # ref-basierter Best-Effort (auf CAM1 normiert)
                )
        else:
            lines = "\n".join(
                f"    {l} ({_name(l)}): ueber {ref_label} {a:+d} Frames, "
                f"ueber {v} {b:+d} Frames (Abweichung {sp}, Confidence nur {c:.1f}x)"
                for l, c, a, b, v, sp in unreliable
            )
            # Die betroffenen DATEIEN klar benennen: der Nutzer kennt nur seine
            # Dateinamen, nicht die internen Labels (MIC3). Ohne das weiss er nicht,
            # welches seiner Files gemeint ist.
            files = ", ".join(f'„{_name(l)}"' for l, *_ in unreliable)
            raise SyncError(
                f"Diese Quelle(n) lassen sich nicht verlaesslich einordnen:\n{lines}\n"
                f"Zwei unabhaengige Wege kommen zu verschiedenen Ergebnissen, und die "
                f"Confidence liegt unter {TRUST_CONFIDENCE:.0f}x — die Korrelation findet "
                f"keinen echten Gipfel, sondern Rauschen.\n"
                f"Wenn die Confidence bei WACHSENDEM Referenzfenster flach bleibt, lag der "
                f"wahre Versatz bisher ausserhalb des durchsuchten Bereichs — das faengt die "
                f"Fenster-Erweiterung inzwischen ab. Bleibt es auch danach uneinig, stammt "
                f"der Ton der Quelle vermutlich aus einer ganz anderen Position (weit "
                f"entfernte Totale, Wind).\n"
                f"Betroffene Datei(en): {files}. Diese Datei manuell synchronisieren "
                f"oder im Schritt Personen/Kameras abwaehlen."
            )

    # Manuell gesetzte Offsets einsetzen (auf CAM1=0 gemeint). NACH allen
    # (Re-)Normalisierungen, damit die Kreuzproben-Neurechnung sie nicht ueberschreibt.
    for label, off in manual_by_label.items():
        if label == "CAM1":
            continue   # CAM1 ist der Null-Anker
        offsets[label] = off

    print()
    print("Sync abgeschlossen:")
    for label, offset in offsets.items():
        seconds = offset / fps
        conf = confidences.get(label)
        if label in sibling_assigned:
            conf_txt = "  [Recorder-Geschwister → Referenz-Offset]"
        elif label in manual_by_label:
            conf_txt = "  [manuell gesetzt]"
        elif conf is not None:
            conf_txt = f"  [Confidence {conf:.1f}x]"
        else:
            conf_txt = "  [Referenz]"
        print(f"  {label} ({_name(label)}): {offset:+d} frames ({seconds:+.3f}s){conf_txt}")

    if collect_unsyncable:
        if unsyncable:
            print()
            print("Nicht verlaesslich einordbar (Best-Effort-Offset oben — bitte pruefen):")
            for u in unsyncable.values():
                print(f"  {u.label} ({u.filename}): {u.reason}")
        return offsets, list(unsyncable.values())
    return offsets


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, json

    parser = argparse.ArgumentParser(description="Waveform-basierter Audio-Sync")
    parser.add_argument("--cams", nargs="+", required=True, help="Video-Dateien, CAM1 zuerst")
    parser.add_argument("--mics", nargs="+", required=True, help="Audio-Dateien, MIC1 zuerst")
    parser.add_argument("--reference", help="Label der Referenzquelle, z.B. MIC1 (Default: laengstes Mic)")
    parser.add_argument("--fps",   type=float, default=25.0)
    parser.add_argument("--json",  action="store_true", help="Ausgabe als JSON")
    args = parser.parse_args()

    try:
        offsets = sync_sources(args.cams, args.mics, args.fps, args.reference)
        if args.json:
            print(json.dumps(offsets))
    except SyncError as e:
        print(f"\nFEHLER: {e}")
        raise SystemExit(1)
