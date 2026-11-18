"""Mund-Aktivitaet — Pruef-Timeline als AAF.

Sprecher-Schnitt aus base.edl, aber an jeder Marker-Stelle wird auf die
Person geschnitten, die der Marker betrifft (den Zuhoerer) — sonst saehe man
genau dort den Sprecher statt des Mundes, um den es geht. Die Marker selbst
kommen separat als Marker-EDL (Resolve: Timeline-Marker aus EDL importieren).

Aufruf: venv/bin/python3 analyse/mund_aktivitaet/pruef_timeline.py KONFIG.json MARKER.json AUSGABE.aaf
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "modules" / "multicam_cutter"))
from shared.frame_utils import frames_to_timecode  # noqa: E402
from build_aaf import build_aaf, _probe_embedded_tc_frames  # noqa: E402
sys.path.insert(0, str(Path(__file__).parent))
from auswerten import parse_edl  # noqa: E402

PAD_S = 0.5          # Vorlauf/Nachlauf um jeden Marker, damit man ihn im Kontext sieht


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    markers = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    out = Path(sys.argv[3])
    fps = float(cfg["fps"])
    offs = cfg["offsets"]
    people = cfg["people"]
    names = [Path(p["cam"]).name for p in people]
    cam_tc = [_probe_embedded_tc_frames(p["cam"], fps) for p in people]

    edl = parse_edl(cfg["edl"], fps)
    T = max(e["rec_out"] for e in edl)
    ev0 = edl[0]
    k0 = names.index(ev0["clip"])
    abs0 = ev0["src_in"] - cam_tc[k0] + offs[people[k0]["cam_key"]] - ev0["rec_in"]

    cam = np.full(T, -1, np.int16)
    for e in edl:
        cam[e["rec_in"]:e["rec_out"]] = names.index(e["clip"])
    # Wo hat welche Kamera ueberhaupt Bild? (Kamera kann spaeter starten / frueher enden)
    import subprocess
    t = np.arange(T)
    has_pic = []
    for k, p in enumerate(people):
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "csv=p=0", p["cam"]], capture_output=True, text=True).stdout)
        cf = abs0 + t - offs[p["cam_key"]]
        has_pic.append((cf >= 0) & (cf < int(dur * fps) - 1))
    pad = int(PAD_S * fps)
    for m in markers:
        k = names.index(m["cam"])
        sl = slice(max(0, m["start"] - pad), min(T, m["end"] + pad))
        # Nur dort auf den Zuhoerer schneiden, wo seine Kamera Bild hat — sonst verwirft
        # build_aaf den Clip und die ganze Bildspur rutscht gegen den Ton (Folge 62, 18.11.:
        # 38 Bilder Versatz, weil CAM2 erst 5 s nach CAM1 startete).
        seg = cam[sl]
        seg[has_pic[k][sl]] = k
        cam[sl] = seg

    # Strecken → CMX-EDL (Source-TC = Tageszeit-TC wie in base.edl)
    lines = ["TITLE: Mund-Aktivitaet Pruef-Timeline", "FCM: NON-DROP FRAME", ""]
    i, n = 0, 0
    first = int(np.argmax(cam >= 0))
    i = first
    while i < T:
        k = cam[i]
        j = i
        while j < T and cam[j] == k:
            j += 1
        if k >= 0:
            n += 1
            src_in = abs0 + i - offs[people[k]["cam_key"]] + cam_tc[k]
            if src_in < cam_tc[k]:
                raise RuntimeError(f"Event {n} liegt vor dem Start von {names[k]} — "
                                   f"wuerde in build_aaf verworfen und den Sync verschieben")
            src_out = src_in + (j - i)
            lines.append(f"{n:03d}  AX       V     C        "
                         f"{frames_to_timecode(src_in, fps)} {frames_to_timecode(src_out, fps)} "
                         f"{frames_to_timecode(i, fps)} {frames_to_timecode(j, fps)}")
            lines.append(f"* FROM CLIP NAME: {names[k]}")
            lines.append("")
        i = j
    # Schnitt-EDL ist nur Zwischenschritt fuer build_aaf → NICHT neben die AAF legen,
    # sonst wird sie in Resolve mit der Marker-EDL verwechselt (passiert 18.11.).
    import tempfile
    edl_out = Path(tempfile.gettempdir()) / f"{out.stem}_schnitt.edl"
    edl_out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Pruef-EDL: {n} Events → {edl_out}")

    build_aaf(
        cam_paths=[p["cam"] for p in people],
        mic_paths=[p["mic"] for p in people],
        offsets=offs, edl_path=edl_out, fps=fps, output=out,
        cam_types=["close"] * len(people),
        cam_person_names=[p["name"] for p in people],
    )
    print(f"AAF: {out}")


if __name__ == "__main__":
    main()
