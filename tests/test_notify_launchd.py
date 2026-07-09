import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor.launchd import build_launch_agent_plist
from paper_monitor.models import Article
from paper_monitor.notify import (
    article_open_target,
    build_osascript_command,
    build_terminal_notifier_command,
    find_terminal_notifier,
    notify_article,
    run_notification_command,
)


class NotificationAndLaunchdTests(unittest.TestCase):
    def test_builds_safe_osascript_notification_command(self):
        article = Article(
            title='Solid electrolyte "breakthrough"',
            journal="Nature Energy",
            url="https://example.org/article",
            doi="10.1000/example",
            published="2026-06-20",
            abstract="",
            source="fixture",
        )

        command = build_osascript_command(article)

        self.assertEqual(command[0], "osascript")
        joined = " ".join(command)
        self.assertIn("display notification", joined)
        self.assertIn("Nature Energy", joined)
        self.assertIn("Solid electrolyte", joined)

    def test_osascript_notification_passes_text_as_arguments(self):
        article = Article(
            title='Cation–Anion "Redox" for H 2 O scavenging',
            journal="ACS Energy Letters",
            url="https://example.org/article",
            doi="10.1021/example",
            published="2026-06-20",
            abstract="",
            source="fixture",
        )

        command = build_osascript_command(article)

        self.assertIn("on run argv", command)
        self.assertEqual(command[-3:], ["10.1021/example", article.title, "ACS Energy Letters"])

    def test_builds_terminal_notifier_command_that_opens_article_site_on_click(self):
        article = Article(
            title="Solid electrolyte breakthrough",
            journal="Nature Energy",
            url="https://example.org/article",
            doi="10.1000/example",
            published="2026-06-20",
            abstract="",
            source="fixture",
        )

        command = build_terminal_notifier_command(
            terminal_notifier_path=Path("/opt/homebrew/bin/terminal-notifier"),
            article=article,
            dashboard_path=Path("/tmp/solid-monitor/latest.html"),
        )

        self.assertEqual(command[0], "/opt/homebrew/bin/terminal-notifier")
        self.assertNotIn("-open", command)
        self.assertIn("-sound", command)
        self.assertIn("default", command)
        self.assertIn("-ignoreDnD", command)
        self.assertIn("-execute", command)
        click_command = command[command.index("-execute") + 1]
        self.assertEqual(click_command, "/usr/bin/open https://example.org/article")
        self.assertIn("Solid electrolyte breakthrough", command)

    def test_terminal_notifier_click_command_quotes_article_url(self):
        article = Article(
            title="Solid electrolyte breakthrough",
            journal="Nature Energy",
            url="https://example.org/article?title=solid electrolyte&x='quoted'",
            doi="10.1000/example",
            published="2026-06-20",
            abstract="",
            source="fixture",
        )

        command = build_terminal_notifier_command(
            terminal_notifier_path=Path("/opt/homebrew/bin/terminal-notifier"),
            article=article,
            dashboard_path=Path("/tmp/solid-monitor/latest.html"),
        )

        click_command = command[command.index("-execute") + 1]
        self.assertEqual(
            click_command,
            """/usr/bin/open 'https://example.org/article?title=solid electrolyte&x='"'"'quoted'"'"''""",
        )

    def test_article_open_target_falls_back_to_doi_then_dashboard(self):
        dashboard_path = Path("/tmp/solid-monitor/latest.html")
        doi_only = Article(
            title="Solid electrolyte breakthrough",
            journal="Nature Energy",
            url="",
            doi="10.1000/example",
            published="2026-06-20",
            abstract="",
            source="fixture",
        )
        no_article_link = Article(
            title="Solid electrolyte breakthrough",
            journal="Nature Energy",
            url="",
            doi="",
            published="2026-06-20",
            abstract="",
            source="fixture",
        )

        self.assertEqual(article_open_target(doi_only, dashboard_path), "https://doi.org/10.1000/example")
        self.assertTrue(article_open_target(no_article_link, dashboard_path).startswith("file://"))

    def test_finds_terminal_notifier_outside_launchd_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Path(temp_dir) / "terminal-notifier"
            candidate.write_text("#!/bin/sh\n", encoding="utf-8")

            with patch("paper_monitor.notify.shutil.which", return_value=None):
                found = find_terminal_notifier(candidates=[candidate])

        self.assertEqual(found, candidate)

    def test_notification_command_failure_returns_false_without_raising(self):
        with patch("paper_monitor.notify.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "notification denied"

            delivered = run_notification_command(["osascript", "-e", "display notification \"x\""])

        self.assertFalse(delivered)
        self.assertEqual(run.call_args.kwargs["timeout"], 5)
        self.assertTrue(run.call_args.kwargs["capture_output"])

    def test_notification_command_timeout_returns_false_without_raising(self):
        with patch(
            "paper_monitor.notify.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["osascript"], timeout=5),
        ):
            delivered = run_notification_command(["osascript", "-e", "display notification \"x\""])

        self.assertFalse(delivered)

    def test_notify_article_is_best_effort_when_helpers_fail(self):
        article = Article(
            title="Solid electrolyte breakthrough",
            journal="Nature Energy",
            url="https://example.org/article",
            doi="10.1000/example",
            published="2026-06-20",
            abstract="",
            source="fixture",
        )

        with patch("paper_monitor.notify.sys.platform", "darwin"):
            with patch("paper_monitor.notify.find_terminal_notifier", return_value=None):
                with patch("paper_monitor.notify.run_notification_command", return_value=False):
                    delivered = notify_article(article, None, dashboard_path=Path("/tmp/paper-monitor/latest.html"))

        self.assertFalse(delivered)

    def test_builds_launch_agent_plist_for_periodic_runs(self):
        plist_bytes = build_launch_agent_plist(
            label="com.example.paper-monitor",
            python_path=Path("/usr/bin/python3"),
            module_name="paper_monitor.cli",
            working_directory=Path("/tmp/solid-monitor"),
            config_path=Path("/tmp/solid-monitor/config.json"),
            interval_seconds=7200,
        )

        payload = plistlib.loads(plist_bytes)

        self.assertEqual(payload["Label"], "com.example.paper-monitor")
        self.assertEqual(payload["StartInterval"], 7200)
        self.assertIn("-c", payload["ProgramArguments"])
        launch_code = payload["ProgramArguments"][2]
        self.assertIn("sys.path.insert(0, '/tmp/solid-monitor')", launch_code)
        self.assertIn("paper_monitor.cli", launch_code)
        self.assertIn("run", payload["ProgramArguments"])
        self.assertEqual(payload["WorkingDirectory"], "/tmp/solid-monitor")
        self.assertEqual(payload["EnvironmentVariables"]["PYTHONPATH"], "/tmp/solid-monitor")
        self.assertEqual(
            payload["StandardOutPath"],
            "/tmp/solid-monitor/work/paper-monitor/logs/paper-monitor.out.log",
        )


if __name__ == "__main__":
    unittest.main()
