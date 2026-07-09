import argparse
import re
from pathlib import Path


def numeric_version(value: str):
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,63}", value.strip()):
        raise ValueError("Version must contain only letters, digits, dot, underscore, plus, or hyphen.")
    timestamp = re.fullmatch(r"(\d{4})(\d{2})(\d{2})-(\d{6})", value.strip())
    if timestamp:
        year, month, day, clock = timestamp.groups()
        return int(year), int(month), int(day), int(clock[:4])

    parts = [int(part) for part in re.findall(r"\d+", value)[:4]]
    parts.extend([0] * (4 - len(parts)))
    return tuple(min(65535, max(0, part)) for part in parts)


def render_version_info(version: str) -> str:
    version_tuple = numeric_version(version)
    tuple_text = ", ".join(str(part) for part in version_tuple)
    escaped_version = version.replace("\\", "\\\\").replace("'", "\\'")
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({tuple_text}),
    prodvers=({tuple_text}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'Paper Monitor'),
         StringStruct('FileDescription', 'Paper Monitor for Windows'),
         StringStruct('FileVersion', '{escaped_version}'),
         StringStruct('InternalName', 'PaperMonitor'),
         StringStruct('OriginalFilename', 'PaperMonitor.exe'),
         StringStruct('ProductName', 'Paper Monitor'),
         StringStruct('ProductVersion', '{escaped_version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="0.0.0")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_version_info(args.version), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
