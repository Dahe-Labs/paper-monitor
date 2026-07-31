#!/usr/bin/env python3
import struct
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "windows" / "assets"
ICON_PATH = ASSET_DIR / "PaperMonitor.ico"
APP_ICON_SOURCE = ASSET_DIR / "AppIconSource.png"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def icon_source_path() -> Path:
    if not APP_ICON_SOURCE.is_file():
        raise FileNotFoundError(f"Missing Windows app icon source: {APP_ICON_SOURCE}")
    return APP_ICON_SOURCE


def _load_pillow():
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to generate the Windows icon") from exc
    return Image


def resize_app_icon(size: int, source_path: Path = APP_ICON_SOURCE):
    if size <= 0:
        raise ValueError("Icon size must be positive")
    if not source_path.is_file():
        raise FileNotFoundError(f"Missing Windows app icon source: {source_path}")

    Image = _load_pillow()
    with Image.open(source_path) as source:
        if source.width != source.height:
            raise ValueError("Paper Monitor app icon source must be square")
        image = source.convert("RGBA")
    resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    return image.resize((size, size), resampling)


def write_png(destination, image) -> None:
    if isinstance(destination, (str, Path)):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG")


def png_bytes(size: int, source_path: Path) -> bytes:
    output = BytesIO()
    write_png(output, resize_app_icon(size, source_path))
    return output.getvalue()


def build_ico(sizes=ICON_SIZES) -> bytes:
    source_path = icon_source_path()
    images = [(size, png_bytes(size, source_path)) for size in sizes]
    header_size = 6 + 16 * len(images)
    offset = header_size
    entries = []
    payloads = []
    for size, payload in images:
        width = 0 if size == 256 else size
        entries.append(
            struct.pack(
                "<BBBBHHII",
                width,
                width,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        payloads.append(payload)
        offset += len(payload)

    return b"".join([struct.pack("<HHH", 0, 1, len(images)), *entries, *payloads])


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    ICON_PATH.write_bytes(build_ico())
    print(ICON_PATH)


if __name__ == "__main__":
    main()
