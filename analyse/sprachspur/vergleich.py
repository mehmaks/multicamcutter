"""Sprachspur — Einwurf-Erkennung: Original-Mikros vs. Analysespuren.

Referenz „echte Einwürfe" = „Mund + Mikro"-Einwürfe aus dem Referenzlauf auf den
Originalen (Einträge mit source="mund" oder mund_bestaetigt; in der Sichtung von
Folge 61/62 außerhalb des Deadbands 45/45 echt). Gezählt wird pro Kamera, wie viele
davon die TON-Erkennung (Einträge ohne source) jeweils findet (±1 s) — und wie viele
Ton-Erkennungen insgesamt entstehen (mehr ohne Mund-Bestätigung = mögliche Fehlalarme
ODER „Mhm" mit geschlossenem Mund; ohne Sichtung nicht unterscheidbar).

Alle Positionen sind Bildnummern der Kamera der reagierenden Person — in beiden
Läufen dieselben Kameras, daher direkt vergleichbar.

Aufruf: venv/bin/python3 analyse/sprachspur/vergleich.py ORDNER_ORIGINAL ORDNER_ANALYSE
"""
import json
import sys
from pathlib import Path


def load(d, cam):
    p = Path(d) / f"{cam}_speaking.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("fps", 29.97), data.get("reactions", [])


def main():
    d_orig, d_ana = sys.argv[1], sys.argv[2]
    cams = sorted(p.name.replace("_speaking.json", "") for p in Path(d_orig).glob("*_speaking.json"))
    tot = {"ref": 0, "orig_hit": 0, "ana_hit": 0, "orig_n": 0, "ana_n": 0, "orig_nomouth": 0, "ana_nomouth": 0}
    for cam in cams:
        fps, ro = load(d_orig, cam)
        _, ra = load(d_ana, cam)
        tol = int(round(fps))
        ref = [r["frame"] for r in ro if r.get("source") == "mund" or r.get("mund_bestaetigt")]
        audio_o = [r["frame"] for r in ro if r.get("source") != "mund"]
        audio_a = [r["frame"] for r in ra if r.get("source") != "mund"]

        def hits(audio):
            return sum(1 for f in ref if any(abs(f - a) <= tol for a in audio))

        def nomouth(audio):
            return sum(1 for a in audio if not any(abs(f - a) <= tol for f in ref))

        ho, ha = hits(audio_o), hits(audio_a)
        print(f"{cam}: echte Einwürfe (Referenz) {len(ref)} | Ton-Erkennung findet: "
              f"Original {ho} ({ho / max(1, len(ref)):.0%}) → Analysespur {ha} ({ha / max(1, len(ref)):.0%}) | "
              f"Ton-Erkennungen gesamt {len(audio_o)} → {len(audio_a)}, davon ohne Mund-Bestätigung "
              f"{nomouth(audio_o)} → {nomouth(audio_a)}")
        for k, v in (("ref", len(ref)), ("orig_hit", ho), ("ana_hit", ha), ("orig_n", len(audio_o)),
                     ("ana_n", len(audio_a)), ("orig_nomouth", nomouth(audio_o)), ("ana_nomouth", nomouth(audio_a))):
            tot[k] += v
    print(f"GESAMT: Referenz {tot['ref']} | gefunden Original {tot['orig_hit']} "
          f"({tot['orig_hit'] / max(1, tot['ref']):.0%}) → Analysespur {tot['ana_hit']} "
          f"({tot['ana_hit'] / max(1, tot['ref']):.0%}) | Ton-Erkennungen {tot['orig_n']} → {tot['ana_n']}, "
          f"ohne Mund-Bestätigung {tot['orig_nomouth']} → {tot['ana_nomouth']}")


if __name__ == "__main__":
    main()
