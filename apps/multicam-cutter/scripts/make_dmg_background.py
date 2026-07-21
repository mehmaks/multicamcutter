#!/usr/bin/env python3
"""
Erzeugt die Hintergrundgrafik fuer das Installations-DMG.

Bewusst als Skript statt als Binaerdatei im Repo: so ist die Grafik
versionierbar, an das Design-System gekoppelt und ohne Bildbearbeitung
anpassbar. Wird von make_dmg.sh aufgerufen.

Ausgabe: 2x-PNG (1280x800) fuer ein 640x400-Punkte-Fenster. Finder skaliert
den Hintergrund auf die Fenstergroesse in Punkten, deshalb ist die doppelte
Pixelzahl der Retina-Trick — kein Multi-Representation-TIFF noetig.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── Design-System (brain/Design-System.md) ────────────────────────────────
BG        = (14, 16, 12)        # identisch mit dem App-Fenster
LIME      = (198, 242, 78)      # Marken-Akzent #C6F24E
LILAC     = (203, 166, 247)     # Zweitfarbe #CBA6F7
TEXT      = (236, 240, 232)
MUTED     = (128, 136, 122)

# 1x! Finder legt den Hintergrund in PIXELN = PUNKTEN an und skaliert NICHT.
# Ein 1280x800-Bild wuerde als 1280x800 Punkte behandelt -> nur das linke obere
# Viertel waere sichtbar. Fuer Retina stattdessen eine Multi-Representation-TIFF
# (siehe make_dmg.sh).
SCALE     = 1
W, H      = 640 * SCALE, 400 * SCALE

# Icon-Mittelpunkte in Punkten — muessen zu den Werten in make_dmg.sh passen!
APP_XY    = (170, 186)
DEST_XY   = (470, 186)
ICON_SIZE = 128


def _font(size, weight="Regular"):
    for path in ("/System/Library/Fonts/SFNS.ttf",
                 "/System/Library/Fonts/Helvetica.ttc"):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size * SCALE)
            except OSError:
                continue
    return ImageFont.load_default()


def _centered(draw, xy, text, font, fill):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    draw.text((xy[0] * SCALE - (r - l) / 2, xy[1] * SCALE - (b - t) / 2),
              text, font=font, fill=fill)


def main(out_path):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Dezenter Verlauf nach unten — verhindert, dass die Flaeche flach wirkt,
    # ohne von den Icons abzulenken.
    for y in range(H):
        f = y / H
        d.line([(0, y), (W, y)],
               fill=(int(BG[0] + 6 * f), int(BG[1] + 7 * f), int(BG[2] + 5 * f)))

    # Kopfzeile
    _centered(d, (320, 56), "MultiCamCutter", _font(30), TEXT)
    _centered(d, (320, 90), "Automatischer Multicam-Schnitt für Podcasts",
              _font(13), MUTED)

    # Pfeil zwischen den beiden Icon-Positionen. Endet vor den Icons, damit er
    # sie nicht beruehrt (Icons sind 128 pt breit, also 64 pt Radius).
    y   = APP_XY[1] * SCALE
    x1  = (APP_XY[0] + ICON_SIZE // 2 + 26) * SCALE
    x2  = (DEST_XY[0] - ICON_SIZE // 2 - 26) * SCALE
    d.line([(x1, y), (x2 - 14 * SCALE, y)], fill=LIME, width=3 * SCALE)
    d.polygon([(x2, y), (x2 - 16 * SCALE, y - 9 * SCALE),
               (x2 - 16 * SCALE, y + 9 * SCALE)], fill=LIME)

    # KEINE eigenen Icon-Beschriftungen: Finder zeichnet die Dateinamen
    # ("MultiCamCutter" bzw. "Programme") selbst unter die Icons. Eigene Labels
    # wuerden sich damit doppeln.

    # Handlungsaufforderung
    _centered(d, (320, 306), "Zum Installieren nach rechts ziehen",
              _font(17), LIME)
    _centered(d, (320, 336),
              "Danach das Volume auswerfen und die App aus „Programme\" öffnen.",
              _font(12), MUTED)
    _centered(d, (320, 362), "Arbeitet vollständig lokal — nichts wird hochgeladen.",
              _font(11), LILAC)
    _centered(d, (320, 384), "Fragen / Feedback: max@pantake.com", _font(10), MUTED)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    print(f"  Hintergrund: {out_path} ({W}x{H}, entspricht {W//SCALE}x{H//SCALE} Punkten)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dmg-background.png")
