import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor import windows_icon
from scripts.generate_windows_icon import APP_ICON_SOURCE, ICON_SIZES, icon_source_path


class WindowsIconTests(unittest.TestCase):
    def test_windows_generator_uses_the_windows_app_icon_source(self):
        self.assertEqual(
            APP_ICON_SOURCE,
            Path("windows/assets/AppIconSource.png").resolve(),
        )
        self.assertEqual(icon_source_path(), APP_ICON_SOURCE)

        source = APP_ICON_SOURCE.read_bytes()
        self.assertEqual(source[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", source[16:24])
        self.assertEqual(width, height)
        self.assertGreaterEqual(width, 1024)

    def test_checked_in_windows_icon_has_all_high_quality_png_frames(self):
        payload = Path("windows/assets/PaperMonitor.ico").read_bytes()
        reserved, image_type, image_count = struct.unpack("<HHH", payload[:6])
        self.assertEqual((reserved, image_type), (0, 1))
        self.assertEqual(image_count, len(ICON_SIZES))

        actual_sizes = []
        for index in range(image_count):
            entry_offset = 6 + (index * 16)
            (
                width_byte,
                height_byte,
                _color_count,
                _reserved,
                planes,
                bit_count,
                byte_count,
                image_offset,
            ) = struct.unpack("<BBBBHHII", payload[entry_offset : entry_offset + 16])
            width = width_byte or 256
            height = height_byte or 256
            actual_sizes.append(width)
            self.assertEqual(width, height)
            self.assertEqual((planes, bit_count), (1, 32))

            frame = payload[image_offset : image_offset + byte_count]
            self.assertEqual(frame[:8], b"\x89PNG\r\n\x1a\n")
            png_width, png_height = struct.unpack(">II", frame[16:24])
            self.assertEqual((png_width, png_height), (width, height))

        self.assertEqual(tuple(actual_sizes), ICON_SIZES)

    def test_frozen_icon_resolver_prefers_the_bundled_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle_root = Path(directory)
            icon_path = bundle_root / "windows" / "assets" / "PaperMonitor.ico"
            icon_path.parent.mkdir(parents=True)
            icon_path.write_bytes(b"icon")

            with patch.object(windows_icon.sys, "_MEIPASS", str(bundle_root), create=True):
                self.assertEqual(windows_icon.default_windows_icon_path(), icon_path)

    def test_build_order_and_consumers_use_the_same_windows_icon(self):
        build_script = Path("scripts/build_windows_app.ps1").read_text(encoding="utf-8")
        package_script = Path("scripts/package_windows_release.ps1").read_text(
            encoding="utf-8"
        )
        native_resource = Path("windows/native_tray/paper_monitor_tray.rc").read_text(
            encoding="utf-8"
        )
        installer = Path("windows/PaperMonitor.iss").read_text(encoding="utf-8")
        window_source = Path("paper_monitor/windows_app_window.py").read_text(
            encoding="utf-8"
        )

        generated = "Invoke-Python -Python $Python -Arguments @($IconScript)"
        tray_build = "& $NativeTrayBuildScript -OutputPath $NativeTrayExe"
        self.assertLess(build_script.index(generated), build_script.index(tray_build))
        self.assertLess(
            package_script.index("-GenerateIconOnly"),
            package_script.index(
                '"scripts\\build_windows_native_tray.ps1") -OutputPath $DistNativeTray'
            ),
        )
        self.assertIn('"--icon"', build_script)
        self.assertIn("($Icon + \";windows\\assets\")", build_script)
        self.assertIn(
            'Copy-Item -LiteralPath $Icon -Destination (Join-Path $OneDirRoot "PaperMonitor.ico")',
            build_script,
        )
        self.assertIn('1 ICON "../assets/PaperMonitor.ico"', native_resource)
        self.assertIn('#define IconFile "assets\\PaperMonitor.ico"', installer)
        self.assertIn('IconFilename: "{app}\\PaperMonitor.ico"', installer)
        self.assertIn("ChangesAssociations=yes", installer)
        self.assertIn('start_options["icon"] = str(icon_path)', window_source)


if __name__ == "__main__":
    unittest.main()
