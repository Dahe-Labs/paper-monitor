#!/usr/bin/env python3
import struct
from io import BytesIO
from pathlib import Path

from generate_app_icons import draw_windows_icon, write_png

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "windows" / "assets"
ICON_PATH = ASSET_DIR / "PaperMonitor.ico"


def png_bytes(size: int) -> bytes:
    output = BytesIO()
    write_png(output, draw_windows_icon(size))
    return output.getvalue()


def build_ico(sizes=(16, 32, 48, 64, 128, 256)) -> bytes:
    images = [(size, png_bytes(size)) for size in sizes]
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
