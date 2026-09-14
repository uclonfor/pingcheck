#!/usr/bin/env python3
"""SitePulse — a compact desktop panel for HTTP availability."""

import argparse
from collections import deque
import math
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont, messagebox

from pingcheck_core import (
    APP_NAME,
    APP_VERSION,
    ConfigError,
    ProbeResult,
    check_site,
    config_path,
    load_config,
    save_config,
)

BG = "#0e141b"
PANEL = "#17212b"
ACTIVE = "#16312e"
HOVER = "#1e2a35"
LINE = "#2a3945"
TEXT = "#e7edf2"
DIM = "#8e9ca9"
ACCENT = "#77e0c3"
RED = "#ff818b"
AMBER = "#edc17c"


class PingCheckApp:
    """All Tk calls stay on the main thread; workers only write queue events."""

    def __init__(self, cfg, path=None, demo=False):
        self.cfg, self.path, self.demo = cfg, path, demo
        self.sites = cfg["sites"]
        self.q = queue.Queue()
        self.results = [None] * len(self.sites)
        self.history = [deque(maxlen=18) for _ in self.sites]
        self.pending = set()
        self.generation = 0
        self.scan_queue = deque()
        self.active_index = None
        self.phase = None
        self.phase_started = 0.0
        self.stop_requested = False
        self.last_scan_stopped = False
        self.flashes = {}
        self.settings = None
        self.row_colors = []
        self.closed = False
        self.hotkey_handle = None
        self.keyboard = None
        self._autohide_job = None
        self._fade_job = None
        self._tick_job = None
        self.press = None
        self.dragged = False
        self.hover = None
        self.ring_cur = self.ring_target = 0.0
        self.last_frame = time.monotonic()
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        assets = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"
        if (assets / "sitepulse.png").exists():
            self._icon = tk.PhotoImage(file=str(assets / "sitepulse.png"))
            self.root.iconphoto(True, self._icon)
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        # Native frame keeps minimize/restore available even without a global hotkey.
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        families = tkfont.families(self.root)
        self.font = next((f for f in ("Segoe UI", "Inter", "DejaVu Sans") if f in families), "TkDefaultFont")
        self.w = 410
        self.row_h = 70
        self.list_top = 252
        self.h = min(self.list_top + len(self.sites) * self.row_h + 64, self.root.winfo_screenheight() - 100)
        self.root.geometry(f"{self.w}x{self.h}")
        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0, width=self.w, height=self.h)
        self.canvas.pack(fill="both", expand=True)
        self._build()
        self._bind()
        self._place(cfg["pos"])
        self._tick_job = self.root.after(16, self._tick)

    @property
    def busy(self):
        return bool(self.pending)

    def _text(self, x, y, text, size=10, color=TEXT, bold=False, **kw):
        return self.canvas.create_text(
            x, y, text=text, fill=color, anchor="w", font=(self.font, size, "bold" if bold else "normal"), **kw
        )

    def _pill(self, x1, y1, x2, y2, color, tags=(), canvas=None):
        r = 12
        return (canvas or self.canvas).create_polygon(
            x1 + r,
            y1,
            x2 - r,
            y1,
            x2,
            y1,
            x2,
            y1 + r,
            x2,
            y2 - r,
            x2,
            y2,
            x2 - r,
            y2,
            x1 + r,
            y2,
            x1,
            y2,
            x1,
            y2 - r,
            x1,
            y1 + r,
            x1,
            y1,
            smooth=True,
            fill=color,
            outline="",
            tags=tags,
        )

    def _fit(self, text, width, size=10, bold=False):
        font = tkfont.Font(family=self.font, size=size, weight="bold" if bold else "normal")
        if font.measure(text) <= width:
            return text
        while text and font.measure(text + "…") > width:
            text = text[:-1]
        return text + "…"

    def _build(self):
        c = self.canvas
        self._pill(24, 24, 58, 58, PANEL)
        c.create_line(
            30, 42, 36, 42, 39, 33, 44, 49, 48, 40, 53, 40, fill=ACCENT, width=2, capstyle="round", joinstyle="round"
        )
        self._text(70, 34, "SitePulse", 17, bold=True)
        self._text(71, 55, "A quiet pulse. A clearer connection.", 8, DIM)
        self._pill(317, 28, 386, 53, PANEL)
        self._text(330, 40, "DEMO" if self.demo else "HTTP", 9, ACCENT, True)
        c.create_line(24, 77, 386, 77, fill=LINE)

        self._pill(18, 91, 392, 222, PANEL)
        self.ring_box = (28, 102, 136, 210)
        c.create_oval(*self.ring_box, outline=LINE, width=5)
        self.ring = c.create_arc(*self.ring_box, start=90, extent=-0.1, style="arc", outline=ACCENT, width=5)
        self.avg_text = c.create_text(82, 148, text="—", fill=TEXT, font=(self.font, 23, "bold"))
        c.create_text(82, 176, text="AVG MS", fill=DIM, font=(self.font, 8))
        self._text(160, 110, "ONE SITE AT A TIME", 8, DIM, True)
        self.summary = self._text(160, 139, "Ready to check", 16, bold=True)
        self.detail = self._text(160, 165, "Your sites, at a glance.", 9, DIM)
        self.progress = self._text(160, 193, "HTTP response time · not ICMP", 8, DIM)
        self._text(24, 241, "YOUR SITES", 8, DIM, True)
        self._text(291, 241, "RECENT CHECKS", 8, DIM)

        list_height = self.h - self.list_top - 64
        self.list_canvas = tk.Canvas(c, bg=BG, highlightthickness=0, width=self.w, height=list_height)
        c.create_window(0, self.list_top, window=self.list_canvas, anchor="nw", width=self.w, height=list_height)
        self.list_canvas.configure(scrollregion=(0, 0, self.w, len(self.sites) * self.row_h))
        if len(self.sites) * self.row_h > list_height:
            scrollbar = tk.Scrollbar(self.root, orient="vertical", command=self.list_canvas.yview)
            self.list_canvas.configure(yscrollcommand=scrollbar.set)
            c.create_window(self.w - 12, self.list_top, window=scrollbar, anchor="nw", height=list_height)
        self.rows = []
        self.connectors = []
        self.row_colors = [BG] * len(self.sites)
        for i, site in enumerate(self.sites):
            y = i * self.row_h
            tag = f"row{i}"
            lc = self.list_canvas
            box = self._pill(16, y + 3, 394, y + 65, BG, (tag,), canvas=lc)
            # The connecting path leads into each server badge from the row above.
            line_top = y - 19 if i else y + 3
            lc.create_line(43, line_top, 43, y + 15, fill=LINE, width=2)
            connector = lc.create_line(43, line_top, 43, line_top, fill=ACCENT, width=3, capstyle="round")
            self.connectors.append((connector, line_top, y + 15))
            halo = lc.create_oval(23, y + 13, 63, y + 53, outline=BG, width=1, tags=(tag,))
            badge = lc.create_oval(26, y + 16, 60, y + 50, fill=PANEL, outline=LINE, width=2, tags=(tag,))
            lc.create_text(
                43,
                y + 33,
                text=site.get("icon", site["domain"][:2].upper()),
                fill=DIM,
                font=(self.font, 9, "bold"),
                tags=(tag,),
            )
            lc.create_text(
                74,
                y + 23,
                text=self._fit(site["domain"], 197, 10, True),
                anchor="w",
                fill=TEXT,
                font=(self.font, 10, "bold"),
                tags=(tag,),
            )
            status = lc.create_text(74, y + 45, text="Waiting", anchor="w", fill=DIM, font=(self.font, 8), tags=(tag,))
            latency = lc.create_text(
                379, y + 22, text="—", anchor="e", fill=TEXT, font=(self.font, 11, "bold"), tags=(tag,)
            )
            dot = lc.create_oval(267, y + 42, 273, y + 48, fill=LINE, outline="", tags=(tag,))
            bars = [
                lc.create_line(287 + j * 5, y + 50, 287 + j * 5, y + 48, fill=LINE, width=3, tags=(tag,))
                for j in range(18)
            ]
            lc.create_line(26, y + 69, 384, y + 69, fill=PANEL)
            self.rows.append(dict(box=box, badge=badge, halo=halo, status=status, latency=latency, dot=dot, bars=bars))
            lc.tag_bind(tag, "<Button-1>", lambda e, index=i: self.start_checks([index]))
            lc.tag_bind(tag, "<Enter>", lambda e, index=i: self._hover(index))
            lc.tag_bind(tag, "<Leave>", lambda e: self._hover(None))
        self.traveler = self.list_canvas.create_oval(0, 0, 0, 0, fill=TEXT, outline=ACCENT, width=2, state="hidden")
        self._pill(24, self.h - 49, 169, self.h - 15, ACCENT, ("refresh",))
        self.refresh_text = self._text(40, self.h - 32, "↻  Check again", 9, BG, True, tags=("refresh",))
        self.footer = self._text(184, self.h - 32, "Ready", 8, DIM)
        self._pill(294, self.h - 49, 386, self.h - 15, PANEL, ("settings",))
        self._text(310, self.h - 32, "Settings", 9, TEXT, tags=("settings",))
        c.tag_bind("refresh", "<Button-1>", lambda e: self.stop_checks() if self.busy else self.start_checks())
        c.tag_bind("settings", "<Button-1>", lambda e: self.open_settings())
        for tag in ("refresh", "settings"):
            c.tag_bind(tag, "<Enter>", lambda e: c.configure(cursor="hand2"))
            c.tag_bind(tag, "<Leave>", lambda e: c.configure(cursor=""))

    def _bind(self):
        self.root.bind("<Escape>", lambda e: self.hide())
        self.root.bind("<Control-q>", lambda e: self.close())
        self.root.bind("<r>", lambda e: self.start_checks())
        self.root.bind("<F5>", lambda e: self.start_checks())
        self.root.bind("<Control-comma>", lambda e: self.open_settings())
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.list_canvas.bind(
            "<MouseWheel>", lambda e: self.list_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        )
        self.list_canvas.bind("<Button-4>", lambda e: self.list_canvas.yview_scroll(-1, "units"))
        self.list_canvas.bind("<Button-5>", lambda e: self.list_canvas.yview_scroll(1, "units"))

    def _hover(self, index):
        self.hover = index
        self.list_canvas.configure(cursor="hand2" if index is not None else "")

    @staticmethod
    def _mix(first, second, fraction):
        fraction = min(1, max(0, fraction))
        channels = [
            round(int(first[i : i + 2], 16) * (1 - fraction) + int(second[i : i + 2], 16) * fraction) for i in (1, 3, 5)
        ]
        return "#" + "".join(f"{channel:02x}" for channel in channels)

    def _press(self, event):
        if event.y < 78:
            self._cancel_autohide()
            self.press = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())
            self.dragged = False

    def _drag(self, event):
        if self.press:
            self.dragged = True
            self.root.geometry(f"{event.x_root - self.press[0]:+d}{event.y_root - self.press[1]:+d}")

    def _release(self, event):
        if self.press and self.dragged:
            self._save_position()
        self.press = None
        self._schedule_autohide()

    def _place(self, pos):
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x, y = pos if pos is not None else (sw - self.w - 48, sh - self.h - 80)
        x, y = max(0, min(x, sw - self.w)), max(0, min(y, sh - self.h - 60))
        self.root.geometry(f"{x:+d}{y:+d}")

    def _save_position(self):
        if self.demo:
            return
        self.cfg["pos"] = [self.root.winfo_x(), self.root.winfo_y()]
        try:
            save_config(self.cfg, self.path)
        except OSError as exc:
            self.canvas.itemconfigure(self.footer, text="Could not save position", fill=AMBER)
            print(f"Could not save configuration: {exc}", file=sys.stderr)

    def start_checks(self, indices=None):
        if self.busy or self.closed or self.settings is not None:
            return
        self._cancel_autohide()
        indices = list(range(len(self.sites))) if indices is None else list(indices)
        self.pending = set(indices)
        self.scan_queue = deque(indices)
        self.generation += 1
        self.stop_requested = self.last_scan_stopped = False
        for i in indices:
            self.results[i] = None
            self.flashes.pop(i, None)
            row = self.rows[i]
            self.list_canvas.itemconfigure(row["status"], text="In queue", fill=DIM)
            self.list_canvas.itemconfigure(row["latency"], text="—")
            self.list_canvas.itemconfigure(row["badge"], outline=LINE)
            self.list_canvas.itemconfigure(row["dot"], fill=LINE)
            connector, top, bottom = self.connectors[i]
            self.list_canvas.coords(connector, 43, top, 43, top)
        self.canvas.itemconfigure(self.refresh_text, text="■  Stop scan")
        self._next_probe()

    def _next_probe(self):
        """Only the main thread advances the queue, after the previous response closed."""
        self.active_index = None
        self.phase = None
        if self.closed:
            return
        if not self.scan_queue:
            self.list_canvas.itemconfigure(self.traveler, state="hidden")
            self.canvas.itemconfigure(self.refresh_text, text="↻  Check again")
            self._overview()
            self._schedule_autohide()
            return
        self.active_index = self.scan_queue.popleft()
        self.phase = "travel"
        self.phase_started = time.monotonic()
        self._overview()

    def stop_checks(self):
        """Stop before the next request; wait for any in-flight request to return."""
        if not self.busy:
            return
        self.stop_requested = self.last_scan_stopped = True
        waiting = list(self.scan_queue)
        self.scan_queue.clear()
        if self.phase == "travel":
            waiting.append(self.active_index)
            self.active_index = None
            self.phase = None
        for index in waiting:
            self.pending.discard(index)
            self.list_canvas.itemconfigure(self.rows[index]["status"], text="Not checked", fill=DIM)
        self.list_canvas.itemconfigure(self.traveler, state="hidden")
        self.canvas.itemconfigure(self.refresh_text, text="Finishing…" if self.busy else "↻  Check again")
        self._overview()
        if not self.busy:
            self._schedule_autohide()

    def _probe(self, index, generation):
        try:
            if self.demo:
                time.sleep(0.24 + (index % 3) * 0.08)
                samples = [(42, 200), (87, 200), (64, 200), (24, 200), (182, 503)]
                result = ProbeResult(*samples[index % len(samples)])
            else:
                result = check_site(self.sites[index]["domain"], self.cfg["timeout"])
        except Exception:
            # Always finish the row even if an unexpected worker failure occurs.
            result = ProbeResult(None, None, "Unexpected error")
        self.q.put(("result", generation, index, result))

    def _result(self, generation, i, result):
        if generation != self.generation or i != self.active_index or self.phase != "checking":
            return
        self.pending.remove(i)
        self.results[i] = result
        self.history[i].append(result)
        self.flashes[i] = (time.monotonic(), ACCENT if result.ok else AMBER if result.code else RED)
        color = ACCENT if result.ok else (AMBER if result.code is not None else RED)
        row = self.rows[i]
        label = (
            f"HTTP {result.code} · {'Available' if result.ok else 'Error'}"
            if result.code is not None
            else result.error or "Unavailable"
        )
        self.list_canvas.itemconfigure(row["status"], text=label, fill=color)
        self.list_canvas.itemconfigure(row["latency"], text=f"{result.ms:.0f} ms" if result.ms is not None else "—")
        self.list_canvas.itemconfigure(row["dot"], fill=color)
        self.list_canvas.itemconfigure(row["badge"], outline=color)
        history = list(self.history[i])
        scale = max((r.ms or 0 for r in history), default=1) or 1
        y = i * self.row_h
        for j, bar in enumerate(row["bars"]):
            offset = j - (18 - len(history))
            if offset >= 0:
                sample = history[offset]
                height = max(3, 15 * (sample.ms or 0) / scale)
                self.list_canvas.coords(bar, 287 + j * 5, y + 51, 287 + j * 5, y + 51 - height)
                self.list_canvas.itemconfigure(bar, fill=ACCENT if sample.ok else RED)
        self._next_probe()

    def _overview(self):
        completed = [r for r in self.results if r is not None]
        values = [r.ms for r in completed if r.ms is not None]
        available = sum(r.ok for r in completed)
        self.ring_target = 359.9 * len(completed) / len(self.sites)
        self.canvas.itemconfigure(self.avg_text, text=f"{sum(values) / len(values):.0f}" if values else "—")
        if self.busy:
            self.canvas.itemconfigure(self.progress, text="HTTP response time · not ICMP")
            index = self.active_index
            title = "Finishing request" if self.stop_requested else "Checking sites"
            detail = self._fit(self.sites[index]["domain"], 222, 9) if index is not None else "Waiting"
            color = TEXT
            self.canvas.itemconfigure(self.footer, text=f"{len(completed)} / {len(self.sites)} done")
        elif self.last_scan_stopped:
            title, detail, color = "Scan stopped", f"{len(completed)} of {len(self.sites)} checked", DIM
        elif available == len(self.sites):
            title, detail, color = "All looking good", f"{available} of {len(self.sites)} sites available", ACCENT
        else:
            title, detail, color = "Needs attention", f"{available} of {len(self.sites)} sites available", AMBER
        self.canvas.itemconfigure(self.summary, text=title, fill=color)
        self.canvas.itemconfigure(self.detail, text=detail)
        self.canvas.itemconfigure(self.ring, outline=ACCENT if self.busy or available == len(self.sites) else AMBER)
        if not self.busy:
            self.canvas.itemconfigure(self.footer, text="Stopped" if self.last_scan_stopped else "Up to date")
            self.canvas.itemconfigure(self.progress, text="Updated " + time.strftime("%H:%M:%S") + " · HTTP response")

    def _tick(self):
        if self.closed:
            return
        for _ in range(100):
            try:
                event = self.q.get_nowait()
            except queue.Empty:
                break
            if event[0] == "toggle":
                self.toggle()
            elif event[0] == "result":
                self._result(*event[1:])
        now = time.monotonic()
        dt = min(now - self.last_frame, 0.1)
        self.last_frame = now
        if self.phase == "travel":
            index = self.active_index
            progress = min(1.0, (now - self.phase_started) / 0.24) if self.cfg["animations"] else 1.0
            eased = progress * progress * (3 - 2 * progress)
            connector, top, bottom = self.connectors[index]
            y = top + (bottom - top) * eased
            self.list_canvas.coords(connector, 43, top, 43, y)
            self.list_canvas.coords(self.traveler, 40, y - 3, 46, y + 3)
            self.list_canvas.itemconfigure(self.traveler, state="normal" if self.cfg["animations"] else "hidden")
            if progress >= 1:
                self.phase = "checking"
                self.phase_started = now
                self.list_canvas.itemconfigure(self.traveler, state="hidden")
                self.list_canvas.itemconfigure(self.rows[index]["status"], text="Measuring…")
                # There is exactly one active network worker. Animation time stays outside the probe timer.
                threading.Thread(target=self._probe, args=(index, self.generation), daemon=True).start()
        moving = False
        if self.visible():
            factor = 1 - math.exp(-dt * 11) if self.cfg["animations"] else 1
            self.ring_cur += (self.ring_target - self.ring_cur) * factor
            self.canvas.itemconfigure(self.ring, extent=-max(0.1, self.ring_cur))
            for i, row in enumerate(self.rows):
                target = ACTIVE if i == self.active_index else HOVER if i == self.hover else BG
                flash = self.flashes.get(i)
                if flash:
                    age = now - flash[0]
                    if age < 0.6 and self.cfg["animations"]:
                        target = self._mix(target, flash[1], 0.16 * (1 - age / 0.6))
                    else:
                        self.flashes.pop(i, None)
                current = self._mix(self.row_colors[i], target, factor)
                # Quantized RGB interpolation must eventually settle, so idle windows
                # return to the low-frequency event loop instead of animating forever.
                if all(abs(int(current[j : j + 2], 16) - int(target[j : j + 2], 16)) <= 3 for j in (1, 3, 5)):
                    current = target
                self.row_colors[i] = current
                self.list_canvas.itemconfigure(row["box"], fill=current)
                moving |= current != target
                if i == self.active_index and self.phase == "checking":
                    pulse = (math.sin((now - self.phase_started) * 5) + 1) / 2 if self.cfg["animations"] else 1
                    color = self._mix(LINE, ACCENT, 0.35 + 0.65 * pulse)
                    self.list_canvas.itemconfigure(row["badge"], outline=color)
                    self.list_canvas.itemconfigure(row["dot"], fill=color)
                    self.list_canvas.itemconfigure(row["halo"], outline=self._mix(BG, ACCENT, 0.1 + 0.22 * pulse))
                    elapsed = now - self.phase_started
                    if elapsed >= 1:
                        self.list_canvas.itemconfigure(row["status"], text=f"Waiting for response · {elapsed:.0f}s")
                else:
                    self.list_canvas.itemconfigure(row["halo"], outline=current)
        animate = (
            self.visible()
            and self.cfg["animations"]
            and (self.busy or moving or self.flashes or abs(self.ring_target - self.ring_cur) > 0.1)
        )
        self._tick_job = self.root.after(16 if animate else 30 if self.busy else 100, self._tick)

    def _cancel_autohide(self):
        if self._autohide_job is not None:
            self.root.after_cancel(self._autohide_job)
            self._autohide_job = None

    def _schedule_autohide(self):
        self._cancel_autohide()
        if (
            not self.busy
            and not self.demo
            and self.cfg["autohide_sec"] > 0
            and self.visible()
            and self.settings is None
        ):
            self._autohide_job = self.root.after(int(self.cfg["autohide_sec"] * 1000), self.hide)

    def _fade(self, start):
        self._fade_job = None
        if self.closed or not self.visible():
            return
        progress = min(1, (time.monotonic() - start) / 0.18)
        try:
            self.root.attributes("-alpha", 0.35 + 0.65 * (1 - (1 - progress) ** 3))
        except tk.TclError:
            return
        if progress < 1:
            self._fade_job = self.root.after(16, self._fade, start)

    def show(self):
        self._cancel_autohide()
        self.root.deiconify()
        self.root.lift()
        if self._fade_job is not None:
            self.root.after_cancel(self._fade_job)
        if self.cfg["animations"]:
            self._fade(time.monotonic())
        self.start_checks()

    def hide(self):
        self._cancel_autohide()
        if self._fade_job is not None:
            self.root.after_cancel(self._fade_job)
            self._fade_job = None
        try:
            self.root.attributes("-alpha", 1.0)
        except tk.TclError:
            pass
        if self.hotkey_handle is not None:
            self.root.withdraw()
        else:
            self.root.iconify()

    def visible(self):
        return self.root.state() == "normal"

    def toggle(self):
        if self.settings is not None:
            self.settings.window.lift()
            return
        self.hide() if self.visible() else self.show()

    def setup_hotkey(self):
        if self.demo or not self.cfg["hotkey"]:
            return
        # keyboard needs elevated input-device access on Linux; the panel never requires root.
        if sys.platform != "win32":
            return
        try:
            import keyboard

            self.keyboard = keyboard
            self.hotkey_handle = keyboard.add_hotkey(self.cfg["hotkey"], lambda: self.q.put(("toggle",)))

        except Exception as exc:
            print(f"Global hotkey unavailable: {exc}", file=sys.stderr)

    def _remove_hotkey(self):
        if self.keyboard is not None and self.hotkey_handle is not None:
            self.keyboard.remove_hotkey(self.hotkey_handle)
        self.hotkey_handle = None

    def open_settings(self):
        if self.settings is not None:
            self.settings.window.lift()
            return
        if self.busy:
            self.canvas.itemconfigure(self.footer, text="Stop scan first")
            return
        from sitepulse_settings import SettingsDialog

        self._cancel_autohide()
        self.settings = SettingsDialog(self)

    def apply_settings(self, cfg):
        if self.busy:
            raise ConfigError("Finish the current scan before changing settings.")
        if not self.demo:
            save_config(cfg, self.path)
        self._remove_hotkey()
        old_history = {site["domain"]: history for site, history in zip(self.sites, self.history)}
        self.cfg = cfg
        self.sites = cfg["sites"]
        self.history = [old_history.get(site["domain"], deque(maxlen=18)) for site in self.sites]
        self.results = [None] * len(self.sites)
        self.flashes.clear()
        self.hover = None
        self.ring_cur = self.ring_target = 0.0
        self.active_index = self.phase = None
        self.h = min(self.list_top + len(self.sites) * self.row_h + 64, self.root.winfo_screenheight() - 100)
        self.root.geometry(f"{self.w}x{self.h}")
        for child in self.root.winfo_children():
            if isinstance(child, tk.Scrollbar):
                child.destroy()
        self.list_canvas.destroy()
        self.canvas.delete("all")
        self.canvas.configure(height=self.h)
        self._build()
        self._bind()
        self._place([self.root.winfo_x(), self.root.winfo_y()])
        self.setup_hotkey()

    def close(self):
        if self.closed:
            return
        if self.visible():
            self._save_position()
        self.closed = True
        self._cancel_autohide()
        for job in (self._tick_job, self._fade_job):
            if job is not None:
                self.root.after_cancel(job)
        try:
            self._remove_hotkey()
        finally:
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="SitePulse — HTTP availability at a glance")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--config", type=str, help="Path to a JSON configuration file")
    parser.add_argument(
        "--demo", action="store_true", help="Show sample results without network requests or config writes"
    )
    args = parser.parse_args()
    path = args.config or config_path()
    try:
        if args.demo:
            from copy import deepcopy
            from pingcheck_core import DEFAULT_CONFIG

            cfg = deepcopy(DEFAULT_CONFIG)
        else:
            cfg = load_config(path)
    except (ConfigError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(APP_NAME + " · Configuration", str(exc), parent=root)
            root.destroy()
        except tk.TclError:
            pass
        return 1
    try:
        app = PingCheckApp(cfg, path=path, demo=args.demo)
    except tk.TclError as exc:
        print(f"SitePulse needs a desktop display and Tk: {exc}", file=sys.stderr)
        return 1
    app.setup_hotkey()
    app.show()
    app.root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
