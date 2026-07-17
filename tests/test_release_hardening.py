import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseHardeningTests(unittest.TestCase):
    def test_public_windows_upload_requires_signing_and_matching_tag(self):
        workflow = (ROOT / ".github" / "workflows" / "build-windows.yml").read_text(encoding="utf-8")

        self.assertIn('tags:\n      - "v*"', workflow)
        self.assertIn("Verify release source tag", workflow)
        self.assertIn("does not match $env:RELEASE_TAG", workflow)
        self.assertIn("A trusted Windows signing certificate is required", workflow)
        self.assertIn("Verify public signatures", workflow)
        self.assertIn("release create $env:RELEASE_TAG --verify-tag --draft", workflow)
        self.assertNotIn("types:\n      - published", workflow)

    def test_release_build_runs_quality_and_frozen_smoke_tests(self):
        workflow = (ROOT / ".github" / "workflows" / "build-windows.yml").read_text(encoding="utf-8")

        self.assertIn("coverage run -m unittest discover -s tests", workflow)
        self.assertIn("coverage report --fail-under=70", workflow)
        self.assertIn("pip_audit -r requirements-windows.lock.txt", workflow)
        self.assertIn(r"& .\dist\windows\PaperMonitor\PaperMonitor.exe self-test", workflow)
        self.assertIn(r"& .\dist\windows\PaperMonitor.exe self-test", workflow)

    def test_release_hash_manifests_are_written_without_utf8_bom(self):
        script = (ROOT / "scripts" / "package_windows_release.ps1").read_text(encoding="utf-8")

        self.assertIn("function Write-Utf8NoBomLines", script)
        self.assertIn("[System.Text.UTF8Encoding]::new($false)", script)
        self.assertNotIn("$AssetHashes | Set-Content", script)
        self.assertNotIn("$PackageHashes | Set-Content", script)

    def test_native_tray_is_signed_before_it_is_embedded_in_frozen_apps(self):
        build_script = (ROOT / "scripts" / "build_windows_app.ps1").read_text(encoding="utf-8")
        package_script = (ROOT / "scripts" / "package_windows_release.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("[string]$PrebuiltNativeTrayPath", build_script)
        pre_sign = package_script.index("-Path $DistNativeTray")
        frozen_build = package_script.index("-PrebuiltNativeTrayPath $DistNativeTray")
        self.assertLess(pre_sign, frozen_build)

    def test_retired_python_tray_is_absent_from_source_and_frozen_runtime(self):
        build_script = (ROOT / "scripts" / "build_windows_app.ps1").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements-windows.txt").read_text(encoding="utf-8")
        launcher = (ROOT / "windows" / "PaperMonitor.pyw").read_text(encoding="utf-8")

        self.assertFalse((ROOT / "paper_monitor" / "windows_tray.py").exists())
        self.assertIn("from paper_monitor import windows_app", launcher)
        self.assertNotIn("pystray", requirements.casefold())
        self.assertNotIn('"pystray"', build_script)
        self.assertNotIn('"PIL.Image"', build_script)
        self.assertNotIn('"PIL.ImageDraw"', build_script)


if __name__ == "__main__":
    unittest.main()
