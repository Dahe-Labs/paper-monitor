#!/usr/bin/env python3
import struct
import subprocess
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "macos" / "PaperMonitorApp" / "Assets"
ICONSET_DIR = ASSET_DIR / "AppIcon.iconset"
APP_ICON_SOURCE = ASSET_DIR / "AppIconSource.png"


def rgba(width, height, fill=(0, 0, 0, 0)):
    return [[list(fill) for _ in range(width)] for _ in range(height)]


def blend(dst, src):
    sr, sg, sb, sa = src
    if sa == 255:
        dst[:] = [sr, sg, sb, 255]
        return
    alpha = sa / 255.0
    inv = 1.0 - alpha
    dst[0] = int(sr * alpha + dst[0] * inv)
    dst[1] = int(sg * alpha + dst[1] * inv)
    dst[2] = int(sb * alpha + dst[2] * inv)
    dst[3] = int(255 * alpha + dst[3] * inv)


def line(img, x0, y0, x1, y1, width, color):
    h = len(img)
    w = len(img[0])
    steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
    radius = max(1, width // 2)
    for i in range(steps + 1):
        t = i / max(1, steps)
        x = x0 + (x1 - x0) * t
        y = y0 + (y1 - y0) * t
        for yy in range(int(y - radius), int(y + radius) + 1):
            for xx in range(int(x - radius), int(x + radius) + 1):
                if 0 <= xx < w and 0 <= yy < h and (xx - x) ** 2 + (yy - y) ** 2 <= radius * radius:
                    blend(img[yy][xx], color)


def circle_outline(img, cx, cy, radius, width, color):
    h = len(img)
    w = len(img[0])
    inner = (radius - width / 2.0) ** 2
    outer = (radius + width / 2.0) ** 2
    for y in range(max(0, int(cy - radius - width)), min(h, int(cy + radius + width) + 1)):
        for x in range(max(0, int(cx - radius - width)), min(w, int(cx + radius + width) + 1)):
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            if inner <= d2 <= outer:
                blend(img[y][x], color)


def circle_fill(img, cx, cy, radius, color):
    h = len(img)
    w = len(img[0])
    r2 = radius * radius
    for y in range(max(0, int(cy - radius)), min(h, int(cy + radius) + 1)):
        for x in range(max(0, int(cx - radius)), min(w, int(cx + radius) + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r2:
                blend(img[y][x], color)


def write_png(path, img):
    height = len(img)
    width = len(img[0])
    raw = b"".join(b"\x00" + b"".join(bytes(px) for px in row) for row in img)

    def chunk(kind, data):
        payload = kind + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def generate_app_iconset():
    if not APP_ICON_SOURCE.exists():
        raise FileNotFoundError(f"Missing app icon source: {APP_ICON_SOURCE}")

    ICONSET_DIR.mkdir(parents=True, exist_ok=True)
    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    for size, name in sizes:
        subprocess.run(
            ["sips", "-s", "format", "png", "-z", str(size), str(size), str(APP_ICON_SOURCE), "--out", str(ICONSET_DIR / name)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def draw_menu_icon(size=64):
    img = rgba(size, size)
    s = size / 64.0
    template_black = (0, 0, 0, 255)

    circle_outline(img, 32 * s, 32 * s, 26 * s, max(3, int(5 * s)), template_black)

    stroke = max(4, int(6 * s))
    line(img, 22 * s, 18 * s, 43 * s, 18 * s, stroke, template_black)
    line(img, 22 * s, 18 * s, 22 * s, 30 * s, stroke, template_black)
    line(img, 22 * s, 30 * s, 42 * s, 30 * s, stroke, template_black)
    line(img, 42 * s, 30 * s, 42 * s, 44 * s, stroke, template_black)
    line(img, 21 * s, 44 * s, 42 * s, 44 * s, stroke, template_black)
    return img


def main():
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    generate_app_iconset()
    write_png(ASSET_DIR / "MenuBarIcon.png", draw_menu_icon(64))


if __name__ == "__main__":
    main()
