"""Run under a desktop or xvfb-run; probes are deterministic and offline."""

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from pingcheck import PingCheckApp
from pingcheck_core import DEFAULT_CONFIG, ProbeResult


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt", "Needs a display (use xvfb-run)")
class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cfg = deepcopy(DEFAULT_CONFIG)
        self.cfg.update(autohide_sec=0, animations=False)
        self.app = PingCheckApp(self.cfg, Path(self.temp.name) / "config.json", demo=True)
        self.app.root.update()

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def pump(self, until, timeout=3):
        end = time.monotonic() + timeout
        while not until() and time.monotonic() < end:
            self.app.root.update()
            time.sleep(0.01)
        self.assertTrue(until())

    def test_sequential_checks_and_recheck_clear_stale_average(self):
        calls = []
        active = 0
        peak = 0
        lock = threading.Lock()

        def probe(domain, timeout):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                calls.append(domain)
            time.sleep(0.02)
            with lock:
                active -= 1
            return ProbeResult(0, 200)

        self.app.demo = False
        with patch("pingcheck.check_site", side_effect=probe):
            self.app.start_checks()
            self.pump(lambda: not self.app.busy)
        self.assertEqual(peak, 1)
        self.assertEqual(calls, [site["domain"] for site in self.cfg["sites"]])
        self.assertTrue(all(r.ok for r in self.app.results))
        self.assertEqual(self.app.canvas.itemcget(self.app.avg_text, "text"), "0")
        with patch("pingcheck.check_site", return_value=ProbeResult(None, None, "Timed out")):
            self.app.start_checks()
            self.pump(lambda: not self.app.busy)
        self.assertEqual(self.app.canvas.itemcget(self.app.avg_text, "text"), "—")
        self.assertEqual(len(self.app.history[0]), 2)
        with patch("pingcheck.check_site", return_value=ProbeResult(50, 200)):
            self.app.start_checks([0])
            self.pump(lambda: not self.app.busy)
        self.assertEqual(len(self.app.history[0]), 3)
        self.assertEqual(len(self.app.history[1]), 2)

    def test_autohide_cancelled_during_recheck_and_stale_events_ignored(self):
        self.app.demo = False
        self.app.cfg["autohide_sec"] = 20
        self.app._schedule_autohide()
        self.assertIsNotNone(self.app._autohide_job)
        self.app.demo = True
        self.app.start_checks([0])
        self.assertIsNone(self.app._autohide_job)
        self.app._result(self.app.generation - 1, 0, ProbeResult(123, 200))
        self.assertIn(0, self.app.pending)
        self.pump(lambda: not self.app.busy)

    def test_hide_fallback_and_hotkey_cleanup(self):
        with patch.object(self.app.root, "iconify") as iconify, patch.object(self.app.root, "withdraw") as withdraw:
            self.app.hide()
            iconify.assert_called_once()
            withdraw.assert_not_called()
        self.app.hotkey_handle = "registered"
        with patch.object(self.app.root, "withdraw") as withdraw:
            self.app.hide()
            withdraw.assert_called_once()
        self.app.hotkey_handle = None

    def test_long_watchlist_scrolls_and_position_stays_on_screen(self):
        self.app.close()
        self.cfg["sites"] *= 4
        self.cfg["pos"] = [-9000, 9000]
        self.app = PingCheckApp(self.cfg, demo=True)
        self.app.root.update()
        self.assertEqual(len(self.app.rows), 20)
        self.assertLess(self.app.list_canvas.yview()[1], 1)
        self.assertGreaterEqual(self.app.root.winfo_x(), 0)
        self.assertLess(self.app.root.winfo_y(), self.app.root.winfo_screenheight())

    def test_animation_launches_one_request_only_after_arrival(self):
        self.app.cfg["animations"] = True

        def frame(elapsed):
            self.app.root.after_cancel(self.app._tick_job)
            with patch("pingcheck.time.monotonic", return_value=self.app.phase_started + elapsed):
                self.app._tick()

        with patch("pingcheck.threading.Thread") as worker:
            self.app.start_checks()
            frame(0.10)
            worker.assert_not_called()
            frame(0.25)
            self.assertEqual(worker.call_count, 1)
            self.assertEqual(self.app.active_index, 0)
            # Even after a long wait, later servers must not begin measuring.
            frame(5)
            self.assertEqual(worker.call_count, 1)
            self.app.q.put(("result", self.app.generation, 0, ProbeResult(20, 200)))
            frame(0.01)
            self.assertEqual(self.app.active_index, 1)
            self.assertEqual(worker.call_count, 1)
            frame(0.25)
            self.assertEqual(worker.call_count, 2)

    def test_stop_waits_for_current_request_and_never_starts_next(self):
        entered = threading.Event()
        release = threading.Event()

        def probe(*args):
            entered.set()
            release.wait(2)
            return ProbeResult(30, 200)

        self.app.demo = False
        try:
            with patch("pingcheck.check_site", side_effect=probe) as check:
                self.app.start_checks()
                self.pump(entered.is_set)
                self.app.stop_checks()
                self.app.start_checks()  # Cannot overlap the still-running request.
                self.assertTrue(self.app.busy)
                self.assertEqual(check.call_count, 1)
                release.set()
                self.pump(lambda: not self.app.busy)
                self.assertEqual(check.call_count, 1)
        finally:
            release.set()
        self.assertEqual(self.app.canvas.itemcget(self.app.summary, "text"), "Scan stopped")
        self.assertTrue(all(r is None for r in self.app.results[1:]))

    def test_stop_during_travel_sends_no_requests(self):
        self.app.cfg["animations"] = True
        with patch("pingcheck.threading.Thread") as worker:
            self.app.start_checks()
            self.app.stop_checks()
            self.assertFalse(self.app.busy)
            self.app.root.update()
            worker.assert_not_called()

    def test_settings_validate_and_apply_without_writing_in_demo(self):
        self.app.open_settings()
        dialog = self.app.settings
        dialog.sites.delete("1.0", "end")
        dialog.sites.insert("1.0", "https://example.com/health\nlocalhost:8080")
        dialog.timeout.set("0")
        self.assertFalse(dialog.save())
        self.assertEqual(len(self.app.sites), 5)
        dialog.timeout.set("2")
        self.assertTrue(dialog.save())
        self.assertEqual(len(self.app.rows), 2)
        self.assertEqual(self.app.cfg["timeout"], 2)
        self.assertIsNone(self.app.settings)
        self.assertFalse((Path(self.temp.name) / "config.json").exists())
        self.pump(lambda: not self.app.busy)

    def test_settings_write_failure_preserves_live_configuration(self):
        self.app.demo = False
        self.app.open_settings()
        dialog = self.app.settings
        original = deepcopy(self.app.cfg)
        dialog.timeout.set("7")
        with patch("pingcheck.save_config", side_effect=OSError("Read-only directory")):
            self.assertFalse(dialog.save())
        self.assertEqual(self.app.cfg, original)
        self.assertIs(self.app.settings, dialog)
        self.assertIn("Read-only", dialog.error.cget("text"))
        dialog.close()

    def test_response_highlights_settle_after_scan(self):
        self.app.cfg["animations"] = True
        self.app.start_checks([0])
        self.pump(lambda: not self.app.busy)
        self.pump(lambda: not self.app.flashes and all(color == "#0e141b" for color in self.app.row_colors))

    def test_worker_failure_completes_and_close_during_check(self):
        self.app.demo = False
        with patch("pingcheck.check_site", side_effect=RuntimeError("test")):
            self.app.start_checks([0])
            self.pump(lambda: not self.app.busy)
        self.assertEqual(self.app.results[0].error, "Unexpected error")
        self.app.demo = True
        self.app.start_checks()
        self.app.close()
        self.assertTrue(self.app.closed)
