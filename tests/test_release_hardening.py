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


if __name__ == "__main__":
    unittest.main()
