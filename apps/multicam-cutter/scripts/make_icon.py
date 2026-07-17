"""Erzeugt ein macOS-App-Icon (1024px) für Multicam Cutter."""
from PIL import Image, ImageDraw, ImageFilter

SS = 2         # Supersampling
W = 1024 * SS

def lerp(a, b, t): return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))

img = Image.new("RGBA", (W, W), (0, 0, 0, 0))

# ── Squircle-Maske ────────────────────────────────────────────────────────────
margin = int(0.085 * W)
box = [margin, margin, W - margin, W - margin]
radius = int((box[2] - box[0]) * 0.235)

mask = Image.new("L", (W, W), 0)
ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)

# ── Vertikaler Verlauf (oben hell-blau → unten indigo) ───────────────────────
TOP = (86, 130, 255)     # #5682FF
BOT = (30, 41, 138)      # #1E298A
grad = Image.new("RGBA", (W, W), (0, 0, 0, 255))
gpx = grad.load()
for y in range(W):
    c = lerp(TOP, BOT, y / W)
    for x in range(W):
        gpx[x, y] = (c[0], c[1], c[2], 255)

# Sanftes Glanzlicht oben-links
glow = Image.new("L", (W, W), 0)
gd = ImageDraw.Draw(glow)
gd.ellipse([int(W*0.02), int(-W*0.28), int(W*0.85), int(W*0.55)], fill=90)
glow = glow.filter(ImageFilter.GaussianBlur(W * 0.10))
grad = Image.composite(Image.new("RGBA", (W, W), (255, 255, 255, 255)), grad, glow)

bg = Image.new("RGBA", (W, W), (0, 0, 0, 0))
bg.paste(grad, (0, 0), mask)

# ── Weiche Schlagschatten unter dem Squircle ─────────────────────────────────
shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
sd = Image.new("L", (W, W), 0)
ImageDraw.Draw(sd).rounded_rectangle(box, radius=radius, fill=110)
sd = sd.filter(ImageFilter.GaussianBlur(W * 0.02))
shadow.putalpha(sd)
shadow = Image.new("RGBA", (W, W), (10, 15, 40, 0))
shadow.putalpha(sd)
canvas = Image.new("RGBA", (W, W), (0, 0, 0, 0))
canvas.alpha_composite(shadow, (0, int(W * 0.012)))
canvas.alpha_composite(bg)

# ── Glyph: zwei gestapelte Video-Frames + Play ───────────────────────────────
def frame(size, center, fill, outline=None, ow=0):
    fw, fh = size
    cx, cy = center
    b = [cx - fw//2, cy - fh//2, cx + fw//2, cy + fh//2]
    r = int(fh * 0.16)
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(b, radius=r, fill=fill, outline=outline, width=ow)
    return layer, b

FW, FH = int(W*0.40), int(W*0.275)
cx, cy = int(W*0.545), int(W*0.560)

# hinterer Frame (halbtransparent, oben-links versetzt)
back, _ = frame((FW, FH), (int(W*0.455), int(W*0.435)), (255, 255, 255, 90))
canvas.alpha_composite(back)

# vorderer Frame (solide weiß)
front, fb = frame((FW, FH), (cx, cy), (255, 255, 255, 255))
canvas.alpha_composite(front)

# Play-Dreieck im vorderen Frame (Verlaufsblau)
tri = Image.new("RGBA", (W, W), (0, 0, 0, 0))
th = int(FH * 0.46)
tw = int(th * 0.86)
tcx, tcy = cx, cy
pts = [(tcx - tw//2, tcy - th//2), (tcx - tw//2, tcy + th//2), (tcx + tw//2 + int(tw*0.05), tcy)]
ImageDraw.Draw(tri).polygon(pts, fill=(46, 78, 200, 255))
canvas.alpha_composite(tri)

# ── Downscale + speichern ────────────────────────────────────────────────────
out = canvas.resize((1024, 1024), Image.LANCZOS)
out.save("/private/tmp/claude-501/-Users-maxmenge-Developer-resolve-toolkit/8473e4d1-0dbd-41ba-912f-2f801f43bdda/scratchpad/icon_1024.png")
print("icon_1024.png geschrieben")
