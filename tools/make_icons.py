"""Dev tool: draw the Sabhalekh icon (1024 px source) and the tray icons (idle / recording).

    python tools/make_icons.py && cd app && npx tauri icon src-tauri/icons/source.png
"""
import os

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "app", "src-tauri", "icons")


def tile(size: int, rec: bool = False) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    grad = Image.new("RGBA", (s, s))
    top, bottom = (79, 142, 247), (139, 92, 246)
    for y in range(s):
        t = y / (s - 1)
        c = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)) + (255,)
        ImageDraw.Draw(grad).line([(0, y), (s, y)], fill=c)
    mask = Image.new("L", (s, s), 0)
    r = int(s * 0.23)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # waveform bars
    heights = [0.22, 0.42, 0.62, 0.38, 0.54, 0.30, 0.18]
    n = len(heights)
    bw = s * 0.07
    gap = s * 0.045
    total = n * bw + (n - 1) * gap
    x = (s - total) / 2
    cy = s * 0.5
    for h in heights:
        hh = s * h / 2
        d.rounded_rectangle([x, cy - hh, x + bw, cy + hh], radius=bw / 2, fill=(255, 255, 255, 245))
        x += bw + gap
    if rec:
        rr = s * 0.2
        cx, cy2 = s - rr * 1.05, rr * 1.05
        d.ellipse([cx - rr - s * 0.04, cy2 - rr - s * 0.04, cx + rr + s * 0.04, cy2 + rr + s * 0.04],
                  fill=(255, 255, 255, 255))
        d.ellipse([cx - rr, cy2 - rr, cx + rr, cy2 + rr], fill=(232, 17, 35, 255))
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    tile(1024).save(os.path.join(OUT, "source.png"))
    for name, rec in (("tray-idle.png", False), ("tray-recording.png", True)):
        big = tile(256, rec)
        big.resize((32, 32), Image.LANCZOS).filter(ImageFilter.SHARPEN).save(os.path.join(OUT, name))
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
