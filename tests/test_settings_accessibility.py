import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SettingsAccessibilityTests(unittest.TestCase):
    def test_settings_fields_tabs_and_status_have_accessible_names_and_state(self):
        html = (ROOT / "paper_monitor" / "templates" / "windows" / "settings.html").read_text(encoding="utf-8")

        self.assertNotIn('<div class="field"><span>', html)
        self.assertIn('for="openalex_api_key"', html)
        self.assertIn('id="refresh_start_time" type="text" inputmode="numeric"', html)
        self.assertIn('<label for="refresh_start_time">Start Time</label>', html)
        self.assertIn('aria-label="Start time in 24-hour HH:MM format"', html)
        self.assertIn('pattern="(?:[01]\\d|2[0-3]):[0-5]\\d" required', html)
        self.assertNotIn("Preferred Start Time", html)
        self.assertNotIn('id="refresh_start_time" type="time"', html)
        self.assertIn('aria-label="Search candidate journals"', html)
        self.assertIn('aria-label="Sort candidate journals"', html)
        self.assertIn('role="status" aria-live="polite"', html)
        self.assertEqual(html.count('aria-controls="panel-'), 4)
        self.assertEqual(html.count('role="tabpanel"'), 4)

    def test_settings_tabs_support_keyboard_navigation_and_invalid_field_reveal(self):
        script = (ROOT / "paper_monitor" / "static" / "windows" / "settings.js").read_text(encoding="utf-8")

        self.assertIn('event.key === "ArrowRight"', script)
        self.assertIn('event.key === "Home"', script)
        self.assertIn('panel.hidden = !active', script)
        self.assertIn('addEventListener("invalid"', script)
        self.assertIn('apiKey.required = enabled', script)
        self.assertIn("syncBackgroundMonitoringState", script)
        self.assertIn("syncTrayStartupState", script)
        self.assertIn("syncJournalSourceAvailability", script)

    def test_settings_controls_use_accessible_contrast_tokens(self):
        css = (ROOT / "paper_monitor" / "static" / "windows" / "settings.css").read_text(encoding="utf-8")

        self.assertIn("--control-border: #9ca3af", css)
        self.assertIn("--blue: #0067c0", css)


if __name__ == "__main__":
    unittest.main()
