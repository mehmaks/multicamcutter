"""Sprachspur — eine Mikrospur so aufbereiten, dass NUR die eigene Sprache bleibt.

Versuch (User-Idee, 18.11.2026): Für die Analyse muss die Spur nicht schön
klingen. Ziel ist eine „Analysespur", in der auch leise „Mhm"/„Ja" klar über dem
Rauschen liegen und Übersprechen der anderen Person verschwindet — so, wie man es
in der Resolve-Waveform mit dem Auge erkennt.

Stufen (je Mikro, das andere Mikro dient als Referenz für das Übersprechen):
  1. Sprachband 120–5000 Hz
  2. ÜBERSPRECHEN DÄMPFEN: Pro Frequenz wird gelernt, wie stark die andere Stimme
     in diesem Mikro ankommt (|H(f)|², aus Momenten, in denen das andere Mikro klar
     dominiert). In jedem Moment wird die Energie gedämpft, die sich dadurch erklären
     lässt. Leistungs- statt Wellenform-Abzug, weil Raumhall die Spuren nur schwach
     kohärent macht (gemessen 0,2–0,5).            → Datei  *_ohne_uebersprechen.wav
  3. RAUSCHEN ABZIEHEN: Rauschboden je Frequenz (leise Momente) wird spektral
     abgezogen (Übersubtraktion), Reste darunter werden stumm.
                                                     → Datei  *_analysespur.wav

Ausgabe als WAV mit demselben BWF-Zeitstempel wie das Original (time_reference),
damit Resolve sie exakt unter das Original legt.

Aufruf:
  venv/bin/python3 analyse/sprachspur/sprachspur.py EIGEN.wav ANDERES.wav AUSGABE_PRÄFIX
      [--start 600] [--seconds 180]
"""
import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.signal import stft, istft, butter, sosfiltfilt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from shared.split_audio import read_wav_info  # noqa: E402

SR = 16000
NFFT = 1024            # 64 ms Fenster: umfasst die Laufzeit zwischen den Mikros sicher
HOP = 256


def load(path, start, seconds):
    cmd = ["ffmpeg", "-v", "error"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(path)]
    if seconds:
        cmd += ["-t", str(seconds)]
    cmd += ["-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32)


def write(path, x, src_wav, start):
    """WAV (48 kHz, 24 bit) mit BWF-time_reference des Originals (+ Startversatz)."""
    info = read_wav_info(src_wav)
    tref = 0
    if info and info["time_ref"] is not None:
        tref = int(info["time_ref"] + round(start * info["sample_rate"]))
        tref = int(round(tref * 48000 / info["sample_rate"]))
    # Fürs Anschauen normalisieren: NICHT auf die lauteste Spitze (einzelne Ausreißer
    # drückten sonst alles andere nach unten), sondern das 99,9. Perzentil auf −3 dBFS;
    # seltene Spitzen darüber werden weich begrenzt (tanh). Für die Analyse ist der
    # Pegel egal — dort zählen nur Verhältnisse.
    ref = float(np.percentile(np.abs(x), 99.9)) or 1.0
    y = np.tanh(x / ref * 0.71).astype(np.float32)
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1",
                        "-i", "-", "-ar", "48000", "-c:a", "pcm_s24le",
                        "-write_bext", "1", "-metadata", f"time_reference={tref}",
                        "-metadata", "originator=MCC Sprachspur", str(path)],
                       input=y.tobytes(), capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("own")
    ap.add_argument("other")
    ap.add_argument("prefix")
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--seconds", type=float, default=None)
    a = ap.parse_args()

    own, other = load(a.own, a.start, a.seconds), load(a.other, a.start, a.seconds)
    n = min(len(own), len(other))
    own, other = own[:n], other[:n]
    print(f"{n / SR / 60:.1f} min geladen")

    sos = butter(4, [120, 5000], btype="band", fs=SR, output="sos")
    own_b, other_b = sosfiltfilt(sos, own), sosfiltfilt(sos, other)

    _, _, O = stft(own_b, SR, nperseg=NFFT, noverlap=NFFT - HOP)
    _, _, R = stft(other_b, SR, nperseg=NFFT, noverlap=NFFT - HOP)
    eo, er = np.sum(np.abs(O) ** 2, 0), np.sum(np.abs(R) ** 2, 0)

    # 2) Übersprechen: nicht die Wellenform abziehen (Raumhall macht die Spuren nur
    #    schwach kohärent: 0,2–0,5 bei 64 ms), sondern pro Frequenz die LEISTUNG, die
    #    sich durch die andere Stimme erklären lässt. Übertragung |H(f)|² = Median von
    #    |eigen|²/|anders|² in Momenten, in denen das andere Mikro klar dominiert.
    Po, Pr = np.abs(O) ** 2, np.abs(R) ** 2
    dom = (er >= 4 * eo) & (er >= np.percentile(er, 70))
    H2 = np.median(Po[:, dom] / (Pr[:, dom] + 1e-20), axis=1)
    bleed = H2[:, None] * Pr                              # vorhergesagtes Übersprechen
    beta = 2.0                                            # Übersubtraktion
    g_bleed = np.clip(1 - beta * bleed / (Po + 1e-20), 0, 1)
    S = O * g_bleed
    print(f"Übersprechen gelernt aus {dom.mean():.0%} der Zeit")

    _, s_clean = istft(S, SR, nperseg=NFFT, noverlap=NFFT - HOP)

    # 3) Rauschboden je Frequenz aus dem ORIGINAL in Momenten, in denen beide Mikros
    #    leise sind (untere 10 %). Früher aus der Spur NACH Schritt 2 geschätzt — dort
    #    sind leise Momente schon auf ~0 gedrückt, der Rauschboden lag bei null und es
    #    wurde nichts abgezogen (Analysespur = „ohne Übersprechen").
    P = np.abs(S) ** 2
    quiet = (eo + er) <= np.percentile(eo + er, 10)
    noise = np.median(Po[:, quiet], axis=1)
    alpha = 3.0
    g_noise = np.clip(1 - alpha * noise[:, None] / (P + 1e-20), 0, 1)
    A = S * g_noise
    _, s_ana = istft(A, SR, nperseg=NFFT, noverlap=NFFT - HOP)

    # Kennzahl: Abstand eigene Sprache ↔ Übersprechen (Median-Energie je Moment)
    own_dom = (eo >= 4 * er) & (eo >= np.percentile(eo, 70))
    def gap_db(X):
        e = np.sum(np.abs(X) ** 2, 0) + 1e-20
        return 10 * np.log10(np.median(e[own_dom]) / np.median(e[dom]))
    print(f"Abstand eigene Sprache ↔ Übersprechen: Original {gap_db(O):.1f} dB → "
          f"ohne Übersprechen {gap_db(S):.1f} dB → Analysespur {gap_db(A):.1f} dB")
    def floor_db(X):
        e = np.sum(np.abs(X) ** 2, 0) + 1e-20
        return 10 * np.log10(np.median(e[own_dom]) / np.median(e[quiet]))
    print(f"Abstand eigene Sprache ↔ Grundrauschen: Original {floor_db(O):.1f} dB → "
          f"ohne Übersprechen {floor_db(S):.1f} dB → Analysespur {floor_db(A):.1f} dB")

    pre = Path(a.prefix)
    write(f"{pre}_ohne_uebersprechen.wav", s_clean[:n], a.own, a.start)
    write(f"{pre}_analysespur.wav", s_ana[:n], a.own, a.start)
    print(f"→ {pre}_ohne_uebersprechen.wav / _analysespur.wav")


if __name__ == "__main__":
    main()
