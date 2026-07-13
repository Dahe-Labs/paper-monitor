import copy
import http.client
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from paper_monitor.config import DEFAULT_CONFIG
from paper_monitor.dashboard import _keyword_analysis_payload_json, _keyword_analysis_script, write_dashboard
from paper_monitor.journal_metrics import JournalMetrics
from paper_monitor.windows_dashboard_server import MAX_REQUEST_BODY_BYTES, WindowsDashboardServer


class UIServerHardeningTests(unittest.TestCase):
    def test_settings_endpoint_rolls_back_when_scheduler_sync_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(copy.deepcopy(DEFAULT_CONFIG)), encoding="utf-8")
            server = WindowsDashboardServer(config_path)

            with patch(
                "paper_monitor.windows_runtime_settings.sync_windows_runtime_settings",
                side_effect=[RuntimeError("registration failed"), None],
            ) as sync:
                status, response = server.handle_api_request(
                    "/api/settings",
                    {"app_settings": {"startup_enabled": True}},
                )

            saved = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(status, 500)
        self.assertIn("rolled back", response["error"])
        self.assertFalse(saved["app_settings"]["startup_enabled"])
        self.assertEqual(sync.call_count, 2)

    def test_keyword_analysis_rejects_active_urls_and_hardens_external_links(self):
        candidates = [
            {"title": "Unsafe", "url": "javascript:alert(1)", "matched": True},
            {"title": "Safe", "url": "https://example.org/paper", "matched": True},
        ]
        payload = json.loads(_keyword_analysis_payload_json(candidates, JournalMetrics([])))

        self.assertEqual(payload["papers"][0]["url"], "")
        self.assertEqual(payload["papers"][1]["url"], "https://example.org/paper")
        script = _keyword_analysis_script()
        self.assertIn("safeExternalHttpUrl(paper && paper.url)", script)
        self.assertIn('target="_blank" rel="noopener noreferrer"', script)

    def test_analysis_endpoint_enforces_work_limits_before_calling_runner(self):
        calls = []
        server = WindowsDashboardServer(Path("config.json"), keyword_analysis_runner=lambda *_a, **_k: calls.append(1))
        base = {
            "date_from": "2026-01-01",
            "date_to": "2026-01-31",
            "top_n": 30,
            "journals": ["Nature"],
        }

        cases = [
            ({**base, "top_n": 101}, "top_n"),
            ({**base, "journals": [f"Journal {index}" for index in range(101)]}, "at most 100 journals"),
            ({**base, "date_to": "2027-02-01"}, "must not exceed 366 days"),
            ({**base, "analysis_depth": "exhaustive", "date_to": "2026-04-04"}, "must not exceed 93 days"),
        ]
        for payload, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                status, response = server.handle_api_request("/api/analyze-keywords", payload)
                self.assertEqual(status, 400)
                self.assertIn(expected_error, response["error"])
        self.assertEqual(calls, [])

    def test_http_server_rejects_rebound_host_and_oversized_body_and_sets_security_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(copy.deepcopy(DEFAULT_CONFIG)), encoding="utf-8")
            server = WindowsDashboardServer(config_path, token="test-token")
            server.start()
            host, port = server._server.server_address[:2]
            try:
                connection = http.client.HTTPConnection(host, port, timeout=3)
                connection.request("GET", "/missing", headers={"Host": "attacker.example"})
                response = connection.getresponse()
                self.assertEqual(response.status, 400)
                self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
                response.read()
                connection.close()

                connection = http.client.HTTPConnection(host, port, timeout=3)
                connection.request(
                    "POST",
                    "/api/refresh-now",
                    body=b"",
                    headers={
                        "Host": f"{host}:{port}",
                        "X-Paper-Monitor-Token": "test-token",
                        "Content-Length": str(MAX_REQUEST_BODY_BYTES + 1),
                    },
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 413)
                self.assertEqual(response.getheader("Cache-Control"), "no-store, max-age=0")
                self.assertIn("frame-ancestors 'none'", response.getheader("Content-Security-Policy"))
                response.read()
                connection.close()

                connection = http.client.HTTPConnection(host, port, timeout=3)
                connection.request("GET", "/settings")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("X-Frame-Options"), "DENY")
                self.assertIn("'unsafe-inline'", response.getheader("Content-Security-Policy"))
                response.read()
                connection.close()
            finally:
                server.stop()

    def test_dashboard_writes_are_atomic_under_concurrency(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "dashboard.html"
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [
                    executor.submit(write_dashboard, path, {"id": index}, [], JournalMetrics([]))
                    for index in range(24)
                ]
                for future in futures:
                    future.result()

            html = path.read_text(encoding="utf-8")
            self.assertTrue(html.startswith("<!doctype html>"))
            self.assertTrue(html.endswith("</html>\n"))
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
