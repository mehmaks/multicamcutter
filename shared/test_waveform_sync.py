"""
Tests fuer sync_sources — Fokus: Baustein 1 (schwache Quellen ueber sichere
Partner retten, statt nur gegen die eine Referenz zu messen).

DETERMINISTISCH: _sync_pair und _probe_duration werden gemockt — keine echten
Audiodateien / kein ffmpeg noetig. Getestet wird die Auswahl- und Offset-
Kompositionslogik (Partner waehlen, rel[partner] + Messung in die Referenz
umrechnen, nur echte Gipfel >= TRUST uebernehmen). Genau dort sitzen die Bugs.

Offset-Konvention (wie im Modul): _sync_pair(ref, target).offset_frames =
  target_true - ref_true  (positiv = target startet spaeter als ref).
Am Ende normalisiert sync_sources auf CAM1 = 0.

Aufruf:  python3 shared/test_waveform_sync.py
oder:    pytest shared/test_waveform_sync.py
"""

import contextlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import shared.waveform_sync as ws  # noqa: E402
from shared.waveform_sync import (  # noqa: E402
    sync_sources, SyncError, SyncResult, UnsyncableSource,
)


# Vier Quellen, feste Labels: CAM1=c1, CAM2=c2, MIC1=m1, MIC2=m2.
# MIC1 ist das laengste Mikro → wird zur Referenz gewaehlt.
DURATIONS = {"c1": 550.0, "c2": 550.0, "m1": 600.0, "m2": 500.0}
CAMS = ["c1", "c2"]
MICS = ["m1", "m2"]


@contextlib.contextmanager
def patched(pairs, durations=DURATIONS, call_log=None):
    """Ersetzt _probe_duration + _sync_pair im Modul; stellt sie danach zurueck.
    pairs: {(ref_label, target_label): (offset_frames, confidence)}."""
    orig_probe, orig_pair = ws._probe_duration, ws._sync_pair
    ws._probe_duration = lambda path: durations[path]

    def _fake_pair(ref_path, target_path, ref_label, target_label, fps,
                   cache=None, start_duration=None, raise_on_fail=True):
        if call_log is not None:
            call_log.append((ref_label, target_label))
        off, conf = pairs[(ref_label, target_label)]
        # Reales _sync_pair wirft bei < MIN_CONFIDENCE nur, wenn raise_on_fail True ist.
        if conf < ws.MIN_CONFIDENCE and raise_on_fail:
            raise SyncError(f"stub: {ref_label}<->{target_label} conf {conf} < MIN")
        return SyncResult(ref_label, target_label, off, off / fps, conf, 180.0)

    ws._sync_pair = _fake_pair
    try:
        yield
    finally:
        ws._probe_duration, ws._sync_pair = orig_probe, orig_pair


def test_rescue_weak_source_via_camera():
    """MIC2 korreliert schwach gegen die Referenz (MIC1), aber stark gegen ihre
    Kamera CAM1 → wird gerettet statt den Lauf mit SyncError zu killen."""
    pairs = {
        ("MIC1", "CAM1"): (-100, 80.0),   # sichere Anker
        ("MIC1", "CAM2"): (50, 70.0),
        ("MIC1", "MIC2"): (999, 12.0),    # Rauschen: falscher Offset, < TRUST
        ("CAM1", "MIC2"): (130, 90.0),    # echter Gipfel ueber die Person-Kamera
        ("CAM1", "CAM2"): (150, 95.0),    # Kreuzprobe CAM1↔CAM2
    }
    with patched(pairs):
        offsets = sync_sources(CAMS, MICS, fps=25.0)

    # rel[MIC2] = rel[CAM1] + 130 = -100 + 130 = 30 (Referenzrahmen),
    # normalisiert auf CAM1=0 (cam1_rel = -100): 30 - (-100) = 130.
    assert offsets == {"MIC1": 100, "CAM1": 0, "CAM2": 150, "MIC2": 130}, offsets


def test_happy_path_unchanged_and_no_rescue_calls():
    """Sind alle Quellen >= TRUST, darf der Rescue-Block NICHT laufen — es fallen
    exakt die alten Messungen an (Hauptschleife + CAM1↔CAM2-Kreuzprobe)."""
    pairs = {
        ("MIC1", "CAM1"): (-100, 80.0),
        ("MIC1", "CAM2"): (50, 70.0),
        ("MIC1", "MIC2"): (30, 75.0),
        ("CAM1", "CAM2"): (150, 95.0),
    }
    calls = []
    with patched(pairs, call_log=calls):
        offsets = sync_sources(CAMS, MICS, fps=25.0)

    assert offsets == {"MIC1": 100, "CAM1": 0, "CAM2": 150, "MIC2": 130}, offsets
    # Nur die vorbestehenden Messungen — keine Partner-Rettungsmessung.
    assert calls == [("MIC1", "CAM1"), ("MIC1", "CAM2"),
                     ("MIC1", "MIC2"), ("CAM1", "CAM2")], calls


def test_genuinely_unsyncable_still_raises():
    """Rettet KEIN Partner (alle Gegenmessungen < TRUST), bleibt die Quelle
    unangetastet und die Gegenpruefung bricht wie bisher ab — der Rescue darf
    einen echten Fehlsync nicht uebertuenchen (Baustein 2/3 macht daraus spaeter
    eine Auswahl-Liste)."""
    pairs = {
        ("MIC1", "CAM1"): (-100, 80.0),
        ("MIC1", "CAM2"): (50, 70.0),
        ("MIC1", "MIC2"): (999, 12.0),   # schwach + falsch
        ("CAM1", "MIC2"): (0, 20.0),     # Rettungsversuche bleiben < TRUST
        ("CAM2", "MIC2"): (0, 15.0),
        ("CAM1", "CAM2"): (150, 95.0),   # Kreuzprobe ok → Fehler kommt aus Gegenpruefung
    }
    with patched(pairs):
        try:
            sync_sources(CAMS, MICS, fps=25.0)
        except SyncError:
            return
        raise AssertionError("Erwartet: SyncError fuer nicht rettbare Quelle")


# ── Baustein 2: collect_unsyncable — melden statt abbrechen ─────────────────────

def test_collect_mode_reports_instead_of_raising():
    """Dieselbe nicht rettbare Quelle wie oben, aber mit collect_unsyncable=True:
    kein SyncError — die guten Quellen werden platziert, MIC2 kommt als
    UnsyncableSource mit Best-Effort-Offset zurueck."""
    pairs = {
        ("MIC1", "CAM1"): (-100, 80.0),
        ("MIC1", "CAM2"): (50, 70.0),
        ("MIC1", "MIC2"): (999, 12.0),
        ("CAM1", "MIC2"): (0, 20.0),
        ("CAM2", "MIC2"): (0, 15.0),
        ("CAM1", "CAM2"): (150, 95.0),
    }
    with patched(pairs):
        offsets, unsyncable = sync_sources(CAMS, MICS, fps=25.0,
                                           collect_unsyncable=True)
    # Gute Quellen normal platziert (Best-Effort auch fuer MIC2 vorhanden):
    assert offsets == {"MIC1": 100, "CAM1": 0, "CAM2": 150, "MIC2": 1099}, offsets
    assert [type(u) for u in unsyncable] == [UnsyncableSource]
    u = unsyncable[0]
    assert u.label == "MIC2" and u.filename == "m2", (u.label, u.filename)
    assert u.best_confidence == 12.0
    # Kandidat = ref-basierter Best-Effort (auf CAM1 normiert) = offsets["MIC2"]
    assert u.candidate_offset_frames == offsets["MIC2"], u.candidate_offset_frames


def test_collect_mode_happy_path_empty_list():
    """Sind alle Quellen sauber, gibt der collect-Modus (offsets, []) zurueck —
    identische Offsets wie ohne Flag."""
    pairs = {
        ("MIC1", "CAM1"): (-100, 80.0),
        ("MIC1", "CAM2"): (50, 70.0),
        ("MIC1", "MIC2"): (30, 75.0),
        ("CAM1", "CAM2"): (150, 95.0),
    }
    with patched(pairs):
        offsets, unsyncable = sync_sources(CAMS, MICS, fps=25.0,
                                           collect_unsyncable=True)
    assert unsyncable == [], unsyncable
    assert offsets == {"MIC1": 100, "CAM1": 0, "CAM2": 150, "MIC2": 130}, offsets


def test_collect_mode_crosscheck_failure_flags_cam2():
    """Scheitert die CAM1↔CAM2-Kreuzprobe (Direktmessung widerspricht der
    Referenz-Kette), wird im collect-Modus CAM2 gemeldet — mit der direkten
    Messung als Kandidat — statt abzubrechen."""
    pairs = {
        ("MIC1", "CAM1"): (-100, 80.0),
        ("MIC1", "CAM2"): (50, 70.0),    # → offsets[CAM2] = 150 (ref-Kette)
        ("MIC1", "MIC2"): (30, 75.0),
        ("CAM1", "CAM2"): (999, 95.0),   # direkte Messung widerspricht → drift 849
    }
    with patched(pairs):
        offsets, unsyncable = sync_sources(CAMS, MICS, fps=25.0,
                                           collect_unsyncable=True)
    assert {u.label for u in unsyncable} == {"CAM2"}, unsyncable
    assert unsyncable[0].candidate_offset_frames == 999, unsyncable[0]


# ── Baustein 3: manueller Offset (pfadbasiert, keine Korrelation) ───────────────

def test_manual_offset_bypasses_correlation():
    """Eine pfadbasiert manuell gesetzte Quelle (m2 → 250) wird nicht korreliert,
    ihr Offset direkt uebernommen, und sie loest keine Gegenpruefung aus — obwohl
    sie ohne das manuelle Setzen unsyncbar waere."""
    pairs = {
        ("MIC1", "CAM1"): (-100, 80.0),
        ("MIC1", "CAM2"): (50, 70.0),
        ("CAM1", "CAM2"): (150, 95.0),
        # (MIC1,MIC2) fehlt bewusst — MIC2 darf gar nicht korreliert werden.
    }
    calls = []
    with patched(pairs, call_log=calls):
        offsets, unsyncable = sync_sources(
            CAMS, MICS, fps=25.0, collect_unsyncable=True,
            manual_offsets={"m2": 250},
        )
    assert unsyncable == [], unsyncable
    assert offsets == {"MIC1": 100, "CAM1": 0, "CAM2": 150, "MIC2": 250}, offsets
    # MIC2 (=m2) wurde nirgends als Ziel korreliert:
    assert all(target != "MIC2" for (_ref, target) in calls), calls


def test_collect_mode_reports_below_min_confidence_source():
    """Fremdes Material bleibt selbst gegen die beste Quelle unter MIN_CONFIDENCE.
    Im collect-Modus bricht das NICHT hart ab (kein SyncError aus _sync_pair),
    sondern landet im Sheet — der klarste Fall fuer Ausschliessen/manuell."""
    pairs = {
        ("MIC1", "CAM1"): (-100, 80.0),
        ("MIC1", "CAM2"): (50, 70.0),
        ("MIC1", "MIC2"): (12345, 3.0),   # unter MIN (5.0) — voellig fremd
        ("CAM1", "MIC2"): (777, 2.5),     # auch gegen die Kameras: Rauschen
        ("CAM2", "MIC2"): (888, 2.8),
        ("CAM1", "CAM2"): (150, 95.0),
    }
    with patched(pairs):
        offsets, unsyncable = sync_sources(CAMS, MICS, fps=25.0,
                                           collect_unsyncable=True)
    assert {u.label for u in unsyncable} == {"MIC2"}, unsyncable


def test_default_mode_below_min_still_raises():
    """Ohne collect-Modus bleibt eine Quelle unter MIN_CONFIDENCE ein HARTER
    Fehler (raise_on_fail=True) — das Verhalten aendert sich nur im collect-Modus."""
    pairs = {
        ("MIC1", "CAM1"): (-100, 80.0),
        ("MIC1", "CAM2"): (50, 70.0),
        ("MIC1", "MIC2"): (12345, 3.0),   # < MIN → _sync_pair wirft
        ("CAM1", "CAM2"): (150, 95.0),
    }
    with patched(pairs):
        try:
            sync_sources(CAMS, MICS, fps=25.0)
        except SyncError:
            return
        raise AssertionError("Erwartet: SyncError bei < MIN_CONFIDENCE (Default-Modus)")


def test_reanchor_when_reference_is_outlier():
    """Ist die (laengste Mic-)Referenz selbst eine fremde Spur, die mit NICHTS
    korreliert, darf nicht alles als unsyncbar gelten. Die Engine ankert auf die
    laengste Kamera um und meldet dann nur den echten Ausreisser (MIC1)."""
    pairs = {
        # Runde 1: gegen die fremde Referenz MIC1 korreliert nichts (alle < TRUST).
        ("MIC1", "CAM1"): (500, 12.0),
        ("MIC1", "CAM2"): (600, 14.0),
        ("MIC1", "MIC2"): (700, 13.0),
        # Runde 2: Re-Anchor auf CAM1 (laengste Kamera) — die guten Quellen syncen.
        ("CAM1", "CAM2"): (150, 90.0),
        ("CAM1", "MIC2"): (200, 85.0),
        ("CAM1", "MIC1"): (999, 10.0),   # die fremde Spur bleibt schwach
        # Rescue/Gegenpruefung von MIC1 gegen die sicheren Partner:
        ("CAM2", "MIC1"): (888, 8.0),
        ("MIC2", "MIC1"): (777, 9.0),
    }
    with patched(pairs):
        offsets, unsyncable = sync_sources(CAMS, MICS, fps=25.0,
                                           collect_unsyncable=True)
    # Nur die fremde Spur MIC1 faellt durch — Kameras + gutes Mic sind synchron.
    assert {u.label for u in unsyncable} == {"MIC1"}, unsyncable
    assert offsets["CAM1"] == 0 and "CAM2" in offsets and "MIC2" in offsets, offsets


if __name__ == "__main__":
    tests = [
        test_rescue_weak_source_via_camera,
        test_happy_path_unchanged_and_no_rescue_calls,
        test_genuinely_unsyncable_still_raises,
        test_collect_mode_reports_instead_of_raising,
        test_collect_mode_happy_path_empty_list,
        test_collect_mode_crosscheck_failure_flags_cam2,
        test_manual_offset_bypasses_correlation,
        test_collect_mode_reports_below_min_confidence_source,
        test_default_mode_below_min_still_raises,
        test_reanchor_when_reference_is_outlier,
    ]
    for t in tests:
        t()
        print(f"  ✓ {t.__name__}")
    print(f"\n{len(tests)} Tests grün.")
