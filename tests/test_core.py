from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import requests

from pingcheck_core import (
    ConfigError,
    DEFAULT_CONFIG,
    check_site,
    config_path,
    load_config,
    normalize_url,
    save_config,
    validate_config,
)


class ConfigTests(unittest.TestCase):
    def test_defaults_are_independent_and_partial_config_merges(self):
        cfg = validate_config({"timeout": 2})
        cfg["sites"][0]["domain"] = "changed.test"
        self.assertEqual(DEFAULT_CONFIG["sites"][0]["domain"], "google.com")
        self.assertEqual(cfg["autohide_sec"], 20)

    def test_bad_config_values(self):
        for value in (
            [],
            {"sites": []},
            {"timeout": 0},
            {"timeout": float("nan")},
            {"timeout": True},
            {"sites": ["example.com"]},
            {"sites": [{"domain": "ftp://example.com"}]},
            {"autohide_sec": -1},
            {"pos": [1, "x"]},
            {"animations": "false"},
            {"hotkey": None},
            {"sites": [{"domain": "example.com", "icon": 4}]},
        ):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                validate_config(value)

    def test_urls(self):
        self.assertEqual(normalize_url("example.com"), "https://example.com")
        self.assertEqual(normalize_url(" http://localhost:8080/health "), "http://localhost:8080/health")
        for url in ("https://", "a b", "http://host:bad", "https://user:pass@host", "ftp://host"):
            with self.subTest(url=url), self.assertRaises(ConfigError):
                normalize_url(url)

    def test_roundtrip_and_corrupt_file_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested/config.json"
            cfg = load_config(path)
            cfg["pos"] = [-50, 42]
            save_config(cfg, path)
            self.assertEqual(load_config(path)["pos"], [-50, 42])
            path.write_text("{broken")
            with self.assertRaises(ConfigError):
                load_config(path)
            self.assertEqual(path.read_text(), "{broken")

    def test_failed_replace_preserves_original_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            save_config(DEFAULT_CONFIG, path)
            original = path.read_bytes()
            with patch("pingcheck_core.os.replace", side_effect=OSError("disk unavailable")):
                with self.assertRaises(OSError):
                    save_config({"timeout": 7}, path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_frozen_config_is_outside_bundle(self):
        with (
            patch("pingcheck_core.sys.frozen", True, create=True),
            patch("pingcheck_core.sys.platform", "win32"),
            patch.dict("os.environ", {"APPDATA": "/tmp/example-appdata"}),
        ):
            self.assertEqual(config_path(), Path("/tmp/example-appdata/SitePulse/config.json"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_HEAD(self):
        code = {"/fallback": 405, "/unimplemented": 501, "/bad": 503, "/redirect": 302, "/loop": 302}.get(
            self.path, 200
        )
        self.send_response(code)
        if code == 302:
            self.send_header("Location", "/loop" if self.path == "/loop" else "/ok")
        self.end_headers()

    def do_GET(self):
        self.send_response(204)
        self.end_headers()


class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_real_http_success_redirect_fallback_and_error(self):
        for route, code in (
            ("/ok", 200),
            ("/redirect", 200),
            ("/fallback", 204),
            ("/unimplemented", 204),
            ("/bad", 503),
        ):
            with self.subTest(route=route):
                result = check_site(self.url + route, 1)
                self.assertEqual(result.code, code)
                self.assertGreaterEqual(result.ms, 0)
                self.assertEqual(result.ok, code < 400)

    def test_redirect_loop(self):
        self.assertEqual(check_site(self.url + "/loop", 1).error, "Redirect loop")

    def test_network_errors_do_not_downgrade_https(self):
        for exc, label in (
            (requests.exceptions.SSLError, "TLS error"),
            (requests.exceptions.Timeout, "Timed out"),
            (requests.exceptions.ConnectionError, "Connection failed"),
        ):
            with self.subTest(exc=exc), patch("pingcheck_core.requests.head", side_effect=exc) as head:
                result = check_site("example.com", 1)
                self.assertEqual(result.error, label)
                self.assertIsNone(result.ms)
                head.assert_called_once_with("https://example.com", timeout=1, allow_redirects=True)

    def test_responses_close_including_fallback(self):
        with patch("pingcheck_core.requests.head") as head, patch("pingcheck_core.requests.get") as get:
            head.return_value.__enter__.return_value.status_code = 405
            get.return_value.__enter__.return_value.status_code = 200
            self.assertEqual(check_site("example.com", 1).code, 200)
            head.return_value.__exit__.assert_called_once()
            get.return_value.__exit__.assert_called_once()
            self.assertTrue(get.call_args.kwargs["stream"])
