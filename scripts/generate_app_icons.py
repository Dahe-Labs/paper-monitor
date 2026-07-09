#!/usr/bin/env python3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "macos" / "PaperMonitorApp" / "Assets"
ICONSET_DIR = ASSET_DIR / "AppIcon.iconset"
APP_ICON_SOURCE = ASSET_DIR / "AppIconSource.png"


def _load_pillow():
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("Pillow is required to generate PaperMonitor icons") from exc

    return Image, ImageDraw


def draw_windows_icon(size: int):
    if size <= 0:
        raise ValueError("Icon size must be positive")

    Image, ImageDraw = _load_pillow()
    scale = 4
    canvas_size = size * scale
    image = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    factor = canvas_size / 64

    def points(*values):
        return tuple(round(value * factor) for value in values)

    draw.ellipse(points(4, 4, 60, 60), fill=(21, 101, 192, 255))
    draw.line(
        points(22, 19, 43, 19, 22, 30, 42, 30, 42, 43, 21, 43),
        fill=(255, 255, 255, 255),
        width=max(1, round(7 * factor)),
    )

    resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    return image.resize((size, size), resampling)


def write_png(destination, image) -> None:
    if isinstance(destination, (str, Path)):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)

    image.save(destination, format="PNG")


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

def main():
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    generate_app_iconset()


if __name__ == "__main__":
    main()
