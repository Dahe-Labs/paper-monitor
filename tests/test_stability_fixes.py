import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from paper_monitor import (
    sources,
    windows_app,
    windows_app_window,
    windows_window_control,
)
from paper_monitor.article_lifecycle import (
    ArticleDetection,
    ArticleLifecycle,
    RefreshCommit,
    RefreshRunStatus,
)
from paper_monitor.config import DEFAULT_CONFIG, load_app_config
from paper_monitor.config_store import update_config_atomic
from paper_monitor.dashboard import render_dashboard
from paper_monitor.filtering import FilterConfig, match_article
from paper_monitor.journal_metrics import JournalMetrics
from paper_monitor.models import Article
from paper_monitor.refresh_execution import RefreshIntent, RefreshOutcome
from paper_monitor.sources import fetch_all_sources
from paper_monitor.windows_dashboard_server import (
    WindowsDashboardServer,
    add_include_term,
)
from paper_monitor.windows_settings import (
    default_settings_payload,
    render_settings_page,
    save_settings,
    settings_payload,
)
from scripts.generate_windows_version_info import numeric_version, render_version_info


class StabilityFixTests(unittest.TestCase):
    def test_install_script_configures_scheduler_without_starting_tray(self):
        script = Path("scripts/install_windows_app.ps1").read_text(encoding="utf-8")
        release_script = Path("windows/Install-PaperMonitor.ps1").read_text(encoding="utf-8")

        self.assertIn("[switch]$EnableStartup", script)
        self.assertIn("[switch]$LaunchAfterInstall", script)
        self.assertIn("[switch]$EnableStartup", release_script)
        self.assertIn("[switch]$LaunchAfterInstall", release_script)
        self.assertIn("if ($EnableStartup)", script)
        self.assertIn("if ($EnableStartup)", release_script)
        self.assertIn("if ($LaunchAfterInstall)", script)
        self.assertIn("if ($LaunchAfterInstall)", release_script)
        self.assertNotIn('Start-Process -FilePath $InstalledExe -ArgumentList "tray --quiet"', script)
        self.assertNotIn('Start-Process -FilePath $InstalledExe -ArgumentList @("tray", "--quiet")', release_script)
        self.assertIn('Invoke-Native -FilePath $InstalledExe -Arguments @("install-startup", "--config", $Config)', script)
        self.assertIn("& $InstalledExe install-startup", release_script)
        self.assertIn("function Stop-InstalledPaperMonitor", script)
        self.assertIn("function Stop-InstalledPaperMonitor", release_script)
        self.assertIn("Stop-InstalledPaperMonitor -ExecutablePath $InstalledExe", script)
        self.assertIn("Stop-InstalledPaperMonitor -ExecutablePath $InstalledExe", release_script)

    def test_config_readers_accept_utf8_bom_without_preserving_it_on_save(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8-sig")

            app_config = load_app_config(config_path)
            update_config_atomic(config_path, lambda payload: payload)
            saved = config_path.read_bytes()

        self.assertEqual(app_config.interval_seconds, DEFAULT_CONFIG["interval_seconds"])
        self.assertFalse(saved.startswith(b"\xef\xbb\xbf"))

    def test_dashboard_window_uses_private_webview_storage_for_prompt_cleanup(self):
        class FakeWindow:
            def __init__(self):
                self.events = types.SimpleNamespace()

        class FakeWebview:
            def __init__(self):
                self.window = FakeWindow()
                self.start_kwargs = None

            def create_window(self, *_args, **_kwargs):
                return self.window

            def start(self, **kwargs):
                self.start_kwargs = kwargs

        class FakeServer:
            def __init__(self):
                self.stop_count = 0

            def start(self):
                return "http://127.0.0.1:12345/"

            def stop(self):
                self.stop_count += 1

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            fake_webview = FakeWebview()
            fake_server = FakeServer()
            with patch.dict(os.environ, {"LOCALAPPDATA": directory}):
                with patch("paper_monitor.windows_app_window._load_webview", return_value=fake_webview):
                    with patch(
                        "paper_monitor.windows_app_window._release_webview2_resources"
                    ) as release_webview:
                        status = windows_app_window.open_dashboard_window(
                            config_path,
                            dashboard_server_factory=lambda _path: fake_server,
                        )

                        self.assertEqual(release_webview.call_count, 1)

            self.assertEqual(status, 0)
            self.assertEqual(fake_webview.start_kwargs, {"private_mode": True})
            self.assertEqual(fake_server.stop_count, 1)
            self.assertEqual(fake_server.stop_count, 1)

    def test_dashboard_window_registers_local_control_endpoint(self):
        class FakeServer:
            token = "secret-token"

            def __init__(self):
                self.controller = None

            def set_window_controller(self, controller):
                self.controller = controller

        class FakeWindow:
            def __init__(self):
                self.urls = []
                self.destroyed = False
                self.restored = False
                self.shown = False

            def load_url(self, url):
                self.urls.append(url)

            def restore(self):
                self.restored = True

            def show(self):
                self.shown = True

            def destroy(self):
                self.destroyed = True

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            server = FakeServer()
            window = FakeWindow()
            close_requested = threading.Event()

            windows_app_window._register_window_control(
                config_path,
                server,
                "http://127.0.0.1:12345/",
                window,
                close_requested,
            )
            state = windows_window_control.read_window_control(config_path)
            self.assertIsNotNone(state)
            self.assertEqual(state.base_url, "http://127.0.0.1:12345")
            self.assertEqual(state.token, "secret-token")
            self.assertEqual(list(config_path.parent.glob(".window-control.json.*.tmp")), [])

            self.assertEqual(server.controller({"action": "ping"}), {"ok": True})
            self.assertEqual(server.controller({"action": "show", "route": "/settings"}), {"ok": True})
            self.assertEqual(server.controller({"action": "close"}), {"ok": True})
            self.assertEqual(
                server.controller({"action": "show", "route": "/"}),
                {"ok": False, "error": "window_closing"},
            )
            time.sleep(0.2)

            windows_window_control.clear_window_control(config_path)

        self.assertEqual(window.urls, ["http://127.0.0.1:12345/settings"])
        self.assertTrue(window.restored)
        self.assertTrue(window.shown)
        self.assertTrue(window.destroyed)

    def test_dashboard_close_button_allows_process_to_exit(self):
        close_requested = threading.Event()
        callback = windows_app_window._close_window_process(close_requested)

        with patch("paper_monitor.windows_app_window._release_webview2_resources") as release_webview:
            self.assertTrue(callback())

        self.assertTrue(close_requested.is_set())
        release_webview.assert_not_called()

    def test_control_close_destroys_before_post_close_webview_cleanup(self):
        window = types.SimpleNamespace(destroy=Mock())
        close_requested = threading.Event()

        def run_deferred(callback, on_error=None):
            callback()
            return True

        with patch(
            "paper_monitor.windows_app_window._defer_window_call",
            side_effect=run_deferred,
        ):
            with patch("paper_monitor.windows_app_window._release_webview2_resources") as release_webview:
                result = windows_app_window._destroy_window(window, close_requested)

        self.assertEqual(result, {"ok": True})
        window.destroy.assert_called_once_with()
        release_webview.assert_not_called()

    def test_dashboard_window_returns_when_window_mutex_already_exists(self):
        class FakeServer:
            def start(self):
                raise AssertionError("server must not start when a dashboard window is already open")

            def stop(self):
                raise AssertionError("server must not stop when it never started")

        with patch("paper_monitor.windows_app_window._acquire_window_mutex", return_value=None):
            with patch("paper_monitor.windows_app_window.send_window_control") as send_control:
                with patch("paper_monitor.windows_app_window._load_webview") as load_webview:
                    status = windows_app_window.open_dashboard_window(
                        Path("config.json"),
                        dashboard_server_factory=lambda _path: FakeServer(),
                        path="/settings",
                    )

        self.assertEqual(status, 0)
        send_control.assert_called_once_with(Path("config.json"), "show", route="/settings")
        load_webview.assert_not_called()

    def test_dashboard_window_releases_mutex_when_webview_load_fails(self):
        handle = object()

        with patch("paper_monitor.windows_app_window._acquire_window_mutex", return_value=handle):
            with patch("paper_monitor.windows_app_window._load_webview", side_effect=RuntimeError("missing webview")):
                with patch("paper_monitor.windows_app_window.clear_window_control") as clear_control:
                    with patch("paper_monitor.windows_app_window.close_handle") as close_handle:
                        with self.assertRaises(RuntimeError):
                            windows_app_window.open_dashboard_window(Path("config.json"))

        clear_control.assert_called_once_with(Path("config.json"))
        close_handle.assert_called_once_with(handle)

    def test_no_console_stderr_fallback_never_raises(self):
        with patch.object(sys, "stderr", None):
            windows_app._write_stderr("background error")

    def test_windows_app_module_has_no_browser_dashboard_launcher(self):
        source = Path("paper_monitor/windows_app.py").read_text(encoding="utf-8")

        self.assertNotIn("open-dashboard", source)
        self.assertNotIn("webbrowser.open", source)
        self.assertNotIn("os.startfile", source)

    def test_settings_save_and_add_search_term_share_atomic_update(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")

            def save():
                return save_settings(config_path, {"max_notifications": 9})

            def add_term():
                add_include_term(config_path, "stack pressure")

            with ThreadPoolExecutor(max_workers=2) as executor:
                save_future = executor.submit(save)
                add_future = executor.submit(add_term)

            self.assertEqual(save_future.result(), {"ok": True})
            add_future.result()

            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["max_notifications"], 9)
            self.assertIn("stack pressure", payload["include_terms"])
            self.assertTrue(config_path.with_name("config.json.bak").exists())

    def test_keyword_analysis_requests_are_single_flight(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")
            started = threading.Event()
            release = threading.Event()
            run_count = 0
            run_lock = threading.Lock()

            def runner(*_args, **_kwargs):
                nonlocal run_count
                with run_lock:
                    run_count += 1
                started.set()
                release.wait(timeout=5)
                return {"ok": True, "papers": []}

            server = WindowsDashboardServer(config_path, keyword_analysis_runner=runner)
            payload = {
                "date_from": "2026-06-01",
                "date_to": "2026-06-02",
                "sort_mode": "time",
                "analysis_depth": "fast",
                "top_n": 10,
                "journals": ["Nature Energy"],
            }

            first_status = {}

            def first_request():
                first_status["value"] = server.handle_api_request("/api/analyze-keywords", payload)

            thread = threading.Thread(target=first_request)
            thread.start()
            self.assertTrue(started.wait(timeout=2))

            status, body = server.handle_api_request("/api/analyze-keywords", payload)

            release.set()
            thread.join(timeout=5)
            self.assertEqual(status, 409)
            self.assertEqual(body, {"ok": False, "error": "analysis_already_running"})
            self.assertEqual(first_status["value"][0], 200)
            self.assertEqual(run_count, 1)

    def test_dashboard_manual_refresh_button_and_endpoint(self):
        html = render_dashboard({}, [], JournalMetrics([]))
        self.assertIn('id="paper-monitor-refresh-button"', html)
        self.assertNotIn('id="paper-monitor-refresh-button" class="header-action-button" hidden', html)
        self.assertIn("Refresh Now", html)
        self.assertIn('type: "refreshNow"', html)

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")
            app_config = load_app_config(config_path)
            lifecycle = ArticleLifecycle(app_config.database_path)
            started = threading.Event()
            release = threading.Event()
            run_count = 0

            def refresh_runner(_config_path):
                nonlocal run_count
                run_count += 1
                started.set()
                release.wait(timeout=5)
                commit = lifecycle.commit_refresh(
                    RefreshCommit(
                        run_id="visible-run",
                        status=RefreshRunStatus.SUCCEEDED,
                        detections=(
                            ArticleDetection(
                                title="Canonical dashboard paper",
                                authors=("Ada Lovelace",),
                                journal="Nature Energy",
                                impact_reference=49.1,
                                url="https://example.org/canonical-paper",
                            ),
                        ),
                        fetched=1,
                        matched=1,
                    )
                )
                return RefreshOutcome(
                    run_id="visible-run",
                    intent=RefreshIntent.VISIBLE,
                    status=RefreshRunStatus.SUCCEEDED,
                    fetched=1,
                    matched=1,
                    new_matches=commit.new_count,
                    skipped=0,
                    source_statuses=(),
                    commit=commit,
                    snapshot=lifecycle.dashboard_snapshot(),
                )

            server = WindowsDashboardServer(config_path, refresh_runner=refresh_runner)
            app_config = DEFAULT_CONFIG.copy()
            stale_dashboard = Path(directory) / app_config["dashboard_path"]
            stale_dashboard.parent.mkdir(parents=True, exist_ok=True)
            stale_dashboard.write_text("<html><body>Old dashboard</body></html>", encoding="utf-8")
            dashboard_html = server.dashboard_html()
            self.assertIn("/api/refresh-now", dashboard_html)
            self.assertIn("/api/refresh-status", dashboard_html)
            self.assertNotIn("paperMonitorAppInfo", dashboard_html)
            self.assertNotIn("paper-monitor-build-badge", dashboard_html)
            self.assertEqual(stale_dashboard.read_text(encoding="utf-8"), "<html><body>Old dashboard</body></html>")
            first_status, first_body = server.handle_api_request("/api/refresh-now", {})
            self.assertTrue(started.wait(timeout=2))

            status, body = server.handle_api_request("/api/refresh-now", {})

            release.set()
            deadline = time.monotonic() + 5
            refresh_state = server.refresh_status()
            while refresh_state["status"] == "running" and time.monotonic() < deadline:
                time.sleep(0.01)
                refresh_state = server.refresh_status()
            self.assertEqual(status, 202)
            self.assertEqual(body["status"], "running")
            self.assertEqual(first_status, 202)
            self.assertEqual(first_body["request_id"], body["request_id"])
            self.assertEqual(refresh_state["status"], "succeeded")
            self.assertEqual(run_count, 1)

            refreshed_html = server.dashboard_html()
            self.assertIn("Canonical dashboard paper", refreshed_html)
            self.assertIn("Ada Lovelace", refreshed_html)
            self.assertIn("Impact factor: 49.1", refreshed_html)
            marker = "window.paperMonitorPresentationToken = "
            token_json = refreshed_html.split(marker, 1)[1].split(";", 1)[0]
            confirm_status, confirmed = server.handle_api_request(
                "/api/confirm-presentation",
                {"presentation_token": json.loads(token_json)},
            )
            self.assertEqual(confirm_status, 200)
            self.assertEqual(confirmed, {"ok": True, "confirmed": 1})

    def test_dashboard_maps_shared_refresh_guard_to_running_state(self):
        server = WindowsDashboardServer(Path("config.json"))
        with patch("paper_monitor.windows_dashboard_server.is_mutex_running", return_value=True):
            status, body = server.handle_api_request("/api/refresh-now", {})

        self.assertEqual(status, 202)
        self.assertEqual(body["status"], "running")
        self.assertTrue(body["request_id"].startswith("external-"))

    def test_external_dashboard_refresh_reloads_canonical_state_when_mutex_clears(self):
        server = WindowsDashboardServer(Path("config.json"))
        with patch(
            "paper_monitor.windows_dashboard_server.is_mutex_running",
            side_effect=[True, False],
        ):
            status, running = server.handle_api_request("/api/refresh-now", {})
            completed = server.refresh_status()

        self.assertEqual(status, 202)
        self.assertEqual(running["status"], "running")
        self.assertEqual(completed["status"], "completed")
        self.assertTrue(completed["ok"])
        self.assertEqual(completed["request_id"], running["request_id"])
        self.assertEqual(completed["error"], "")
        self.assertIsNone(completed["result"])

    def test_dashboard_refresh_thread_start_failure_rolls_back_state(self):
        server = WindowsDashboardServer(Path("config.json"))

        with patch("paper_monitor.windows_dashboard_server.is_mutex_running", return_value=False):
            with patch("paper_monitor.windows_dashboard_server.threading.Thread") as thread_class:
                thread_class.return_value.start.side_effect = RuntimeError("thread unavailable")
                status, body = server.handle_api_request("/api/refresh-now", {})

        self.assertEqual(status, 500)
        self.assertFalse(body["ok"])
        self.assertEqual(body["status"], "failed")
        self.assertIn("thread unavailable", body["error"])
        self.assertIsNone(server._refresh_thread)
        with patch("paper_monitor.windows_dashboard_server.is_mutex_running", return_value=False):
            self.assertEqual(server.refresh_status()["status"], "failed")

    def test_settings_page_uses_top_left_back_link_and_restore_defaults(self):
        html = render_settings_page(Path("config.json"), "http://127.0.0.1:1", "token")

        self.assertIn('class="back-link" id="dashboard-link"', html)
        self.assertIn("&larr; Main Window", html)
        self.assertIn('data-testid="tab-app-settings"', html)
        self.assertIn('data-testid="journal-picker"', html)
        self.assertIn('data-testid="selected-journal-list"', html)
        self.assertIn('data-testid="candidate-journal-list"', html)
        self.assertIn('data-testid="journal-sort-mode"', html)
        self.assertIn('data-testid="manual-journal-name"', html)
        self.assertIn('id="openalex_max_pages"', html)
        self.assertIn("Background Monitoring", html)
        self.assertIn("Run short scheduled refresh tasks", html)
        self.assertIn("Start at Windows Sign-in", html)
        self.assertIn("without opening the app window", html)
        self.assertIn("Tray Icon", html)
        self.assertIn("Keep the lightweight native tray available", html)
        self.assertIn("Notifications", html)
        self.assertNotIn("Quiet Startup", html)
        self.assertNotIn("Open Refresh", html)
        self.assertNotIn('data-testid="build-identity"', html)
        self.assertIn('id="defaults-button"', html)
        self.assertIn("Restore Defaults", html)
        self.assertNotIn('id="reload-button"', html)
        self.assertIn("/api/settings/defaults", html)

        defaults = default_settings_payload()
        self.assertNotIn("app_info", defaults)
        self.assertEqual(defaults["refresh_start_time"], DEFAULT_CONFIG["refresh_start_time"])
        self.assertEqual(defaults["search_direction"]["preset"], DEFAULT_CONFIG["search_direction"]["preset"])
        self.assertEqual(
            defaults["app_settings"],
            {
                key: DEFAULT_CONFIG["app_settings"][key]
                for key in (
                    "startup_enabled",
                    "launch_at_login",
                    "show_tray_icon",
                    "notifications_enabled",
                )
            },
        )
        formal_candidates = [
            entry for entry in defaults["journal_catalog"]
            if str(entry["journal"]).casefold() != "arxiv"
        ]
        self.assertEqual(len(formal_candidates), 300)
        self.assertTrue(all(entry["category"] for entry in formal_candidates))
        self.assertEqual(
            float(defaults["journal_catalog"][0]["impact_factor"]),
            max(float(entry["impact_factor"]) for entry in formal_candidates),
        )
        self.assertGreaterEqual(
            float(defaults["journal_catalog"][0]["impact_factor"]),
            float(defaults["journal_catalog"][1]["impact_factor"]),
        )

    def test_settings_page_resources_do_not_depend_on_current_working_directory(self):
        current = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                import os

                os.chdir(directory)
                html = render_settings_page(Path("config.json"), "http://127.0.0.1:1", "token")
            finally:
                os.chdir(current)

        self.assertNotIn("__SETTINGS_CONTEXT__", html)
        self.assertNotIn("__SETTINGS_CSS__", html)
        self.assertNotIn("__SETTINGS_JS__", html)
        self.assertIn("/api/settings/defaults", html)
        self.assertIn("X-Paper-Monitor-Token", html)
        self.assertIn('data-testid="journal-picker"', html)

    def test_settings_payload_falls_back_to_legacy_root_journals(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            payload = json.loads(json.dumps(DEFAULT_CONFIG))
            payload.pop("journal_scope")
            payload["journals"] = ["Nature Energy", "Advanced Materials"]
            config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            settings = settings_payload(config_path)

            self.assertEqual(
                settings["journal_scope"]["selected_journals"],
                ["Nature Energy", "Advanced Materials"],
            )

    def test_app_settings_are_saved_to_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")

            response = save_settings(
                config_path,
                {
                    "app_settings": {
                        "startup_enabled": True,
                        "show_tray_icon": False,
                        "notifications_enabled": False,
                    }
                },
            )

            self.assertEqual(response, {"ok": True})
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["app_settings"],
                {
                    "startup_enabled": True,
                    "launch_at_login": False,
                    "show_tray_icon": False,
                    "notifications_enabled": False,
                    "silent_startup_notifications": True,
                    "refresh_on_launch": True,
                },
            )

    def test_app_settings_save_preserves_unknown_future_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            payload = json.loads(json.dumps(DEFAULT_CONFIG))
            payload["app_settings"]["future_app_option"] = "keep me"
            config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            response = save_settings(config_path, {"app_settings": {"startup_enabled": True}})

            self.assertEqual(response, {"ok": True})
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["app_settings"]["future_app_option"], "keep me")
            self.assertTrue(saved["app_settings"]["startup_enabled"])

    def test_settings_save_preserves_unknown_source_limit_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            payload = json.loads(json.dumps(DEFAULT_CONFIG))
            payload["sources"]["crossref"]["min_request_interval_seconds"] = 0.5
            payload["sources"]["crossref"]["future_crossref_option"] = "keep me"
            config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            response = save_settings(config_path, {"max_notifications": 8})

            self.assertEqual(response, {"ok": True})
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["max_notifications"], 8)
            self.assertEqual(saved["sources"]["crossref"]["min_request_interval_seconds"], 0.5)
            self.assertEqual(saved["sources"]["crossref"]["future_crossref_option"], "keep me")

    def test_settings_save_requires_openalex_api_key_when_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")
            payload = default_settings_payload(config_path)
            payload["sources"]["openalex"]["enabled"] = True
            payload["sources"]["openalex"]["api_key"] = ""

            response = save_settings(config_path, payload)

        self.assertIn("error", response)
        self.assertIn("sources.openalex.api_key", response["error"])

    def test_openalex_settings_roundtrip_preserves_api_options(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")
            payload = default_settings_payload(config_path)
            payload["sources"]["openalex"].update(
                {
                    "enabled": True,
                    "days_back": 21,
                    "per_page": 50,
                    "max_pages": 4,
                    "api_key": "openalex-key",
                }
            )

            response = save_settings(config_path, payload)
            saved = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(response, {"ok": True})
        self.assertEqual(saved["sources"]["openalex"]["days_back"], 21)
        self.assertEqual(saved["sources"]["openalex"]["per_page"], 50)
        self.assertEqual(saved["sources"]["openalex"]["max_pages"], 4)
        self.assertEqual(saved["sources"]["openalex"]["api_key"], "openalex-key")

    def test_custom_crossref_direction_can_leave_openalex_query_empty_when_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False), encoding="utf-8")
            payload = default_settings_payload(config_path)
            payload["search_direction"] = {
                "preset": "custom",
                "label": "Crossref only",
                "crossref_query": "solid electrolyte",
                "openalex_query": "",
                "query_manually_edited": True,
            }
            payload["sources"]["openalex"]["enabled"] = False
            payload["sources"]["openalex"]["query"] = ""

            response = save_settings(config_path, payload)
            saved = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(response, {"ok": True})
        self.assertEqual(saved["search_direction"]["openalex_query"], "")
        self.assertEqual(saved["sources"]["openalex"]["query"], "")

    def test_crossref_pool_limits_follow_mailto_configuration(self):
        public_config = {"max_workers": 3, "mailto": ""}
        polite_config = {"max_workers": 6, "mailto": "alerts@example.org"}

        self.assertEqual(sources._crossref_effective_max_workers(public_config, 3), 1)
        self.assertEqual(sources._crossref_effective_max_workers(polite_config, 6), 3)
        self.assertEqual(sources._crossref_min_request_interval_seconds({"mailto": "", "min_request_interval_seconds": 0}), 0.0)
        self.assertGreaterEqual(sources._crossref_min_request_interval_seconds(public_config), 1.0)
        self.assertLess(sources._crossref_min_request_interval_seconds(polite_config), 1.0)

    def test_config_example_tracks_crossref_rate_limit_contract(self):
        example = json.loads(Path("config.example.json").read_text(encoding="utf-8"))

        self.assertIn("retry_count", DEFAULT_CONFIG["sources"]["crossref"])
        self.assertIn("retry_count", example["sources"]["crossref"])
        self.assertIn("min_request_interval_seconds", DEFAULT_CONFIG["sources"]["crossref"])
        self.assertIn("min_request_interval_seconds", example["sources"]["crossref"])
        self.assertIn("max_pages", DEFAULT_CONFIG["sources"]["openalex"])
        self.assertIn("max_pages", example["sources"]["openalex"])

    def test_config_schema_covers_crossref_rate_limit_contract(self):
        schema = json.loads(Path("docs/config.schema.json").read_text(encoding="utf-8"))
        crossref = schema["properties"]["sources"]["properties"]["crossref"]["properties"]
        openalex = schema["properties"]["sources"]["properties"]["openalex"]["properties"]

        self.assertIn("retry_count", crossref)
        self.assertIn("min_request_interval_seconds", crossref)
        self.assertEqual(crossref["retry_count"]["minimum"], 0)
        self.assertEqual(crossref["min_request_interval_seconds"]["minimum"], 0)
        self.assertIn("max_pages", openalex)
        self.assertEqual(openalex["max_pages"]["maximum"], 50)

    def test_windows_packaging_includes_runtime_resource_directories(self):
        script = Path("scripts/build_windows_app.ps1").read_text(encoding="utf-8")

        for resource in ("paper_monitor\\templates", "paper_monitor\\static", "paper_monitor\\resources"):
            self.assertIn(resource, script)

        self.assertIn('"_sqlite3"', script)
        self.assertIn('"unicodedata"', script)
        self.assertIn('"--collect-data"', script)
        self.assertIn('"--collect-binaries"', script)
        self.assertIn('"--collect-submodules"', script)
        self.assertIn('($WebViewLib + ";webview\\lib")', script)
        self.assertIn("Test-OnedirWebViewRuntime", script)
        self.assertIn("Test-OnefileWebViewRuntime", script)
        self.assertIn("win-arm64\\native\\WebView2Loader.dll", script)
        self.assertIn("win-x64\\native\\WebView2Loader.dll", script)
        self.assertIn("win-x86\\native\\WebView2Loader.dll", script)
        self.assertIn("generate_windows_version_info.py", script)
        self.assertIn('"--version-file"', script)
        self.assertIn('".venv\\Scripts\\python.exe"', script)
        self.assertLess(script.index('@("python")'), script.index('@("py", "-3")'))

    def test_windows_version_info_supports_timestamp_release_versions(self):
        self.assertEqual(numeric_version("20260710-055055"), (2026, 7, 10, 550))
        with self.assertRaises(ValueError):
            numeric_version("../unsafe-version")
        rendered = render_version_info("20260710-055055")
        self.assertIn("filevers=(2026, 7, 10, 550)", rendered)
        self.assertIn("ProductVersion', '20260710-055055'", rendered)
        self.assertIn("OriginalFilename', 'PaperMonitor.exe'", rendered)

    def test_arxiv_days_back_filters_old_entries_with_clear_dates(self):
        new_date = (date.today() - timedelta(days=1)).isoformat()
        old_date = (date.today() - timedelta(days=30)).isoformat()
        feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>New solid electrolyte paper</title>
    <id>https://arxiv.org/abs/2607.00001</id>
    <link href="https://arxiv.org/abs/2607.00001" />
    <published>{new_date}T00:00:00Z</published>
    <updated>{new_date}T00:00:00Z</updated>
    <summary>Fresh result.</summary>
    <author><name>A. Researcher</name></author>
  </entry>
  <entry>
    <title>Old solid electrolyte paper</title>
    <id>https://arxiv.org/abs/2606.00001</id>
    <link href="https://arxiv.org/abs/2606.00001" />
    <published>{old_date}T00:00:00Z</published>
    <updated>{old_date}T00:00:00Z</updated>
    <summary>Old result.</summary>
    <author><name>B. Researcher</name></author>
  </entry>
</feed>"""

        articles = sources.fetch_arxiv(
            {"query": "solid electrolyte", "days_back": 7, "max_results": 10},
            fetch=lambda _url: feed.encode("utf-8"),
        )

        self.assertEqual([article.title for article in articles], ["New solid electrolyte paper"])

    def test_openalex_enabled_without_api_key_is_skipped_before_request(self):
        config = {
            "rss": [],
            "crossref": {"enabled": False},
            "openalex": {
                "enabled": True,
                "days_back": 1,
                "per_page": 1,
                "query": "solid electrolyte",
                "api_key": "",
            },
            "arxiv": {"enabled": False},
        }

        with patch("paper_monitor.sources.fetch_url") as fetch_url, patch("paper_monitor.sources._warn") as warn:
            self.assertEqual(fetch_all_sources(config), [])

        fetch_url.assert_not_called()
        self.assertIn("sources.openalex.api_key", warn.call_args[0][0])

    def test_openalex_url_caps_per_page_and_supports_date_to(self):
        url = sources.build_openalex_url(
            {
                "query": "solid electrolyte",
                "date_from": "2026-06-01",
                "date_to": "2026-06-30",
                "per_page": 999,
                "api_key": "openalex-test-key",
            }
        )

        self.assertIn("per_page=200", url)
        self.assertIn("from_publication_date%3A2026-06-01", url)
        self.assertIn("to_publication_date%3A2026-06-30", url)
        self.assertIn("api_key=openalex-test-key", url)
        self.assertIn("select=id%2Cdisplay_name", url)
        self.assertIn("authorships", url)

    def test_openalex_fetch_supports_cursor_pages(self):
        seen_urls = []
        responses = [
            {
                "meta": {"next_cursor": "cursor-2"},
                "results": [{"id": "https://openalex.org/W1", "display_name": "First paper"}],
            },
            {
                "meta": {"next_cursor": None},
                "results": [{"id": "https://openalex.org/W2", "display_name": "Second paper"}],
            },
        ]

        def fake_fetch(url):
            seen_urls.append(url)
            return json.dumps(responses.pop(0)).encode("utf-8")

        articles = sources.fetch_openalex(
            {
                "query": "solid electrolyte OR LLZO",
                "api_key": "openalex-key",
                "per_page": 1,
                "max_pages": 2,
            },
            fetch=fake_fetch,
        )

        self.assertEqual([article.title for article in articles], ["First paper", "Second paper"])
        self.assertIn("cursor=%2A", seen_urls[0])
        self.assertIn("cursor=cursor-2", seen_urls[1])

    def test_openalex_parser_maps_authors_and_abstract(self):
        payload = {
            "results": [
                {
                    "display_name": "Solid electrolyte interfaces",
                    "doi": "https://doi.org/10.1234/example",
                    "publication_date": "2026-07-01",
                    "primary_location": {
                        "landing_page_url": "https://example.org/paper",
                        "source": {"display_name": "Nature Energy"},
                    },
                    "abstract_inverted_index": {"Solid": [0], "electrolyte": [1], "interfaces": [2]},
                    "authorships": [
                        {"author": {"display_name": "Ada Lovelace"}},
                        {"author": {"display_name": "Ada Lovelace"}},
                        {"author": {"display_name": "Grace Hopper"}},
                    ],
                },
                {
                    "id": "https://openalex.org/W123",
                    "display_name": "OpenAlex-only paper",
                    "publication_date": "2026-07-02",
                }
            ]
        }

        articles = sources.parse_openalex_response(json.dumps(payload).encode("utf-8"))

        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0].journal, "Nature Energy")
        self.assertEqual(articles[0].doi, "10.1234/example")
        self.assertEqual(articles[0].abstract, "Solid electrolyte interfaces")
        self.assertEqual(articles[0].authors, ("Ada Lovelace", "Grace Hopper"))
        self.assertEqual(articles[1].url, "https://openalex.org/W123")

    def test_date_window_prefers_explicit_dates(self):
        window = sources._date_window_from_config(
            {"days_back": 30, "date_from": "2026-06-01", "date_to": "2026-06-10"},
            default_days_back=3,
            today=date(2026, 7, 8),
        )
        fallback = sources._date_window_from_config({}, default_days_back=7, today=date(2026, 7, 8))

        self.assertEqual(window.date_from, "2026-06-01")
        self.assertEqual(window.date_to, "2026-06-10")
        self.assertEqual(fallback.date_from, "2026-07-01")
        self.assertEqual(fallback.date_to, "")

    def test_journal_alias_and_keyword_boundaries(self):
        config = FilterConfig(
            include_terms=["solid electrolyte"],
            exclude_terms=[],
            journals=["Nature Energy"],
            journal_aliases={"Nature Energy": ["Nat Energy"]},
        )
        article = Article(
            title="A solid electrolyte paper",
            journal="Nat Energy",
            url="https://example.org",
            doi="",
            published="2026-06-01",
            abstract="",
            source="Crossref",
        )

        self.assertTrue(match_article(article, config).matched)

        short_term_config = FilterConfig(include_terms=["ion"], exclude_terms=[], journals=[])
        false_positive = Article(
            title="Interfacial polarization in batteries",
            journal="Nature Energy",
            url="https://example.org/2",
            doi="",
            published="2026-06-01",
            abstract="",
            source="Crossref",
        )
        phrase_match = Article(
            title="Solid electrolyte enables fast cycling",
            journal="Nature Energy",
            url="https://example.org/3",
            doi="",
            published="2026-06-01",
            abstract="",
            source="Crossref",
        )

        self.assertFalse(match_article(false_positive, short_term_config).matched)
        self.assertTrue(match_article(phrase_match, FilterConfig(["solid electrolyte"], [], [])).matched)


if __name__ == "__main__":
    unittest.main()
