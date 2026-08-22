#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PingCheck — компактный виджет доступности сайтов.

Ctrl+Alt+P      — показать / скрыть (меняется в config.json)
Esc или ✕       — скрыть
Клик по строке  — перепроверить конкретный сервер
Перетаскивание  — переместить окно (позиция запоминается)
"""

import json
import os
import queue
import threading
import time
import tkinter as tk

import requests

try:
    import keyboard  # глобальный хоткей
except ImportError:
    keyboard = None

APP_NAME = "PingCheck"
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

# ------------------------------ палитра (тёмно-синяя тема)
C_BG     = "#0d1526"   # фон окна
C_PANEL  = "#182342"   # заливка кружков серверов
C_LINE   = "#24335c"   # пустые линии / кольцо
C_ACCENT = "#e9efff"   # заполнение (почти белый)
C_TEXT   = "#d9e2f7"   # основной текст
C_DIM    = "#75859f"   # «полупрозрачный» текст (пинг и т.п.)
C_GREEN  = "#41d67f"
C_RED    = "#ff5f5f"
TRANS    = "#010203"   # цвет прозрачности для скругления углов

FONT = "Segoe UI"

DEFAULT_CONFIG = {
    "hotkey": "ctrl+alt+p",
    "timeout": 5,
    "autohide_sec": 20,   # скрыть окно через N секунд после проверки (0 = никогда)
    "pos": None,
    "sites": [
        {"domain": "google.com",     "icon": "G"},
        {"domain": "github.com",     "icon": "GH"},
        {"domain": "apple.com",      "icon": "A"},
        {"domain": "cloudflare.com", "icon": "CF"},
        {"domain": "youtube.com",    "icon": "YT"}
    ],
}


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _check(domain, timeout):
    """HEAD-запрос: время ответа = «пинг», код ответа = статус."""
    for scheme in ("https", "http"):
        t0 = time.perf_counter()
        try:
            r = requests.head(f"{scheme}://{domain}",
                              timeout=timeout, allow_redirects=True)
            if r.status_code == 405:  # некоторые сайты не любят HEAD
                with requests.get(f"{scheme}://{domain}", timeout=timeout,
                                  stream=True, allow_redirects=True) as g:
                    code = g.status_code
                return (time.perf_counter() - t0) * 1000, code
            return (time.perf_counter() - t0) * 1000, r.status_code
        except requests.RequestException:
            continue
    return None, None


class PingCheckApp:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sites = cfg.get("sites") or DEFAULT_CONFIG["sites"]
        self.timeout = float(cfg.get("timeout", 5))
        self.autohide = int(cfg.get("autohide_sec", 20))

        self.q = queue.Queue()      # события из потока проверок
        self.busy = False
        self.results = []
        self.press = None
        self.moved = False
        self.row_hit = None
        self._autohide_job = None

        # ---------------- геометрия
        self.pad, self.ax, self.avg_r = 26, 64, 38
        self.row_h, self.sr = 64, 16
	self.hdr = 36   # шапка под заголовок, чтобы кольцо не наезжало
        self.ay = self.hdr + self.avg_r + 6
        top0 = self.ay + self.avg_r + 26
        self.cys = [top0 + i * self.row_h + self.sr + 4
                    for i in range(len(self.sites))]
        self.w = 340
        self.h = (self.cys[-1] + self.sr + self.pad + 8
                  if self.cys else self.ay * 2 + self.pad)

        # ---------------- окно
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)        # без системной рамки
        self.root.attributes("-topmost", True)  # поверх всех окон

        self.canvas = tk.Canvas(self.root, width=self.w, height=self.h,
                                bg=TRANS, highlightthickness=0, bd=0)
        self.canvas.pack()

        self.rounded = False
        try:  # скругление через прозрачный цвет (Windows)
            self.root.attributes("-transparentcolor", TRANS)
            self.rounded = True
        except tk.TclError:
            self.canvas.configure(bg=C_BG)

        self._build()
        self._bind()
        self._place(cfg.get("pos"))
        self.root.after(16, self._tick)

    # ------------------------------------------------------------ отрисовка
    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r,
               x2, y2, x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r,
               x1, y1 + r, x1, y1]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def _build(self):
        c = self.canvas
        if self.rounded:
            self._round_rect(8, 8, self.w - 8, self.h - 8, 20,
                             fill=C_BG, outline="")

        c.create_text(24, 26, text="PINGCHECK", anchor="w",
                      font=(FONT, 9, "bold"), fill=C_DIM)
        self.close_btn = c.create_text(self.w - 24, 26, text="✕", anchor="e",
                                       font=(FONT, 11, "bold"), fill=C_DIM,
                                       tags=("close",))

        # --- кольцо среднего пинга (заполняется по мере проверок)
        ax, ay, r = self.ax, self.ay, self.avg_r
        c.create_arc(ax - r, ay - r, ax + r, ay + r, start=90, extent=359.9,
                     style="arc", outline=C_LINE, width=5)
        self.ring = c.create_arc(ax - r, ay - r, ax + r, ay + r,
                                 start=90, extent=0.1,
                                 style="arc", outline=C_ACCENT, width=5)
        self.avg_text = c.create_text(ax, ay - 3, text="—",
                                      font=(FONT, 16, "bold"), fill=C_TEXT)
        c.create_text(ax, ay + 18, text="avg ms",
                      font=(FONT, 8), fill=C_DIM)

        # --- цепочка серверов
        self.segs, self.rows = [], []
        prev_bottom = ay + r
        for i, s in enumerate(self.sites):
            cy = self.cys[i]
            y1, y2 = prev_bottom + 6, cy - self.sr - 6
            c.create_line(self.ax, y1, self.ax, y2,
                          fill=C_LINE, width=3, capstyle="round")
            act = c.create_line(self.ax, y1, self.ax, y1,
                                fill=C_ACCENT, width=3, capstyle="round")
            self.segs.append({"y1": y1, "y2": y2, "cur": 0.0, "tgt": 0.0,
                              "act": act})
            prev_bottom = cy + self.sr

            tag = f"row{i}"
            circ = c.create_oval(self.ax - self.sr, cy - self.sr,
                                 self.ax + self.sr, cy + self.sr,
                                 fill=C_PANEL, outline=C_LINE, width=2,
                                 tags=(tag,))
            icon = c.create_text(self.ax, cy, text=s.get("icon", "?"),
                                 font=(FONT, 10, "bold"), fill=C_DIM,
                                 tags=(tag,))
            dom = c.create_text(self.ax + 30, cy - 8, text=s["domain"],
                                anchor="w", font=(FONT, 11, "bold"),
                                fill=C_TEXT, tags=(tag,))
            ping = c.create_text(self.ax + 30, cy + 10, text="…",
                                 anchor="w", font=(FONT, 9), fill=C_DIM,
                                 tags=(tag,))
            stat = c.create_text(self.w - 22, cy, text="", anchor="e",
                                 font=(FONT, 10, "bold"), fill=C_DIM,
                                 tags=(tag,))
            self.rows.append({"circ": circ, "icon": icon, "dom": dom,
                              "ping": ping, "stat": stat})

    # ------------------------------------------------------------ события
    def _bind(self):
        self.root.bind("<Escape>", lambda e: self.hide())
        self.canvas.tag_bind("close", "<Button-1>",
                             lambda e: self.hide())
        self.canvas.tag_bind("close", "<Enter>",
                             lambda e: self.canvas.itemconfig(self.close_btn,
                                                              fill=C_RED))
        self.canvas.tag_bind("close", "<Leave>",
                             lambda e: self.canvas.itemconfig(self.close_btn,
                                                              fill=C_DIM))
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

    def _on_press(self, e):
        self.press = (e.x_root - self.root.winfo_x(),
                      e.y_root - self.root.winfo_y())
        self.moved, self.row_hit = False, None
        for item in self.canvas.find_overlapping(e.x - 3, e.y - 3,
                                                 e.x + 3, e.y + 3):
            for t in self.canvas.gettags(item):
                if t.startswith("row"):
                    self.row_hit = int(t[3:])

    def _on_motion(self, e):
        if not self.press:
            return
        dx = e.x_root - self.root.winfo_x() - self.press[0]
        dy = e.y_root - self.root.winfo_y() - self.press[1]
        if abs(dx) > 3 or abs(dy) > 3:
            self.moved = True
        if self.moved:
            self.root.geometry(f"+{e.x_root - self.press[0]}"
                               f"+{e.y_root - self.press[1]}")

    def _on_release(self, e):
        if self.press and not self.moved and self.row_hit is not None:
            self._recheck(self.row_hit)
        elif self.press and self.moved:  # запомнить новую позицию
            self.cfg["pos"] = [self.root.winfo_x(), self.root.winfo_y()]
            save_config(self.cfg)
        self.press = None

    # ------------------------------------------------------------ главный цикл
    def _tick(self):
        try:
            while True:
                self._handle(self.q.get_nowait())
        except queue.Empty:
            pass

        # плавное заполнение кольца
        if self.ring_cur < self.ring_tgt:
            self.ring_cur = min(self.ring_tgt, self.ring_cur + 7)
            self.canvas.itemconfig(self.ring, extent=self.ring_cur)

        # плавное заполнение линий (полоска сверху вниз)
        for s in self.segs:
            if s["cur"] < s["tgt"]:
                s["cur"] = min(s["tgt"], s["cur"] + 0.08)
                y = s["y1"] + (s["y2"] - s["y1"]) * s["cur"]
                self.canvas.coords(s["act"], self.ax, s["y1"], self.ax, y)

        self.root.after(16, self._tick)

    def _handle(self, ev):
        if ev[0] == "toggle":
            self.toggle()
        elif ev[0] == "seg":
            i = ev[1]
            self.segs[i]["tgt"] = 1.0
            self.canvas.itemconfig(self.rows[i]["circ"], outline=C_ACCENT)
            self.canvas.itemconfig(self.rows[i]["ping"], text="pinging…")
        elif ev[0] == "result":
            self._show_result(ev[1], ev[2], ev[3])
        elif ev[0] == "done":
            self._finish()

    def _show_result(self, i, ms, code):
        self.results[i] = (ms, code)
        row = self.rows[i]
        ok = code is not None and 200 <= code < 400
        color = C_GREEN if ok else C_RED
        self.canvas.itemconfig(row["circ"], outline=color)
        self.canvas.itemconfig(row["icon"], fill=C_ACCENT)
        self.canvas.itemconfig(row["ping"],
                               text=f"{ms:.0f} ms" if ms else "timeout")
        if code is not None:
            self.canvas.itemconfig(row["stat"], text=f"{code} "
                                     f"{'OK' if ok else 'ERR'}", fill=color)
        else:
            self.canvas.itemconfig(row["stat"], text="DOWN", fill=C_RED)

        # кольцо и средний пинг
        done = sum(1 for r in self.results if r)
        self.ring_tgt = 360.0 * done / len(self.sites)
        vals = [r[0] for r in self.results if r and r[0] is not None]
        if vals:
            self.canvas.itemconfig(self.avg_text,
                                   text=f"{sum(vals) / len(vals):.0f}")

    def _finish(self):
        self.busy = False
        self.ring_tgt = 360.0
        if self.autohide > 0 and self.visible():
            self._cancel_autohide()
            self._autohide_job = self.root.after(self.autohide * 1000,
                                                 self._autohide_now)

    def _autohide_now(self):
        if self.visible():
            self.hide()

    def _cancel_autohide(self):
        if self._autohide_job:
            self.root.after_cancel(self._autohide_job)
            self._autohide_job = None

    # ------------------------------------------------------------ проверки
    def _reset_scene(self):
        self.results = [None] * len(self.sites)
        self.ring_cur = self.ring_tgt = 0.0
        self.canvas.itemconfig(self.ring, extent=0.1)
        self.canvas.itemconfig(self.avg_text, text="—")
        for row in self.rows:
            self.canvas.itemconfig(row["circ"], outline=C_LINE)
            self.canvas.itemconfig(row["icon"], fill=C_DIM)
            self.canvas.itemconfig(row["ping"], text="…")
            self.canvas.itemconfig(row["stat"], text="", fill=C_DIM)
        for s in self.segs:
            s["cur"] = s["tgt"] = 0.0
            self.canvas.coords(s["act"], self.ax, s["y1"], self.ax, s["y1"])

    def start_checks(self):
        if self.busy:
            return
        self.busy = True
        self._reset_scene()
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        for i, s in enumerate(self.sites):
            self.q.put(("seg", i))       # полоска доходит до сервера…
            time.sleep(0.35)             # …и он пингуется
            ms, code = _check(s["domain"], self.timeout)
            self.q.put(("result", i, ms, code))
        self.q.put(("done",))

    def _recheck(self, i):
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._recheck_worker, args=(i,),
                         daemon=True).start()

    def _recheck_worker(self, i):
        self.q.put(("seg", i))
        ms, code = _check(self.sites[i]["domain"], self.timeout)
        self.q.put(("result", i, ms, code))
        self.q.put(("done",))

    # ------------------------------------------------------------ показ/скрытие
    def _place(self, pos):
        if pos and isinstance(pos, (list, tuple)) and len(pos) == 2:
            try:
                self.root.geometry(f"+{int(pos[0])}+{int(pos[1])}")
                return
            except Exception:
                pass
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"+{sw - self.w - 48}+{sh - self.h - 64}")

    def show(self):
        self._cancel_autohide()
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        try:
            self.root.focus_force()
        except tk.TclError:
            pass
        self.start_checks()

    def hide(self):
        self._cancel_autohide()
        self.root.withdraw()

    def toggle(self):
        self.hide() if self.visible() else self.show()

    def visible(self):
        return self.root.state() == "normal"


def main():
    app = PingCheckApp(load_config())
    if keyboard:
        try:
            hotkey = app.cfg.get("hotkey", "ctrl+alt+p")
            keyboard.add_hotkey(hotkey, lambda: app.q.put(("toggle",)))
            print(f"{APP_NAME}: хоткей [{hotkey}] активен")
        except Exception as e:
            print(f"Хоткей не заработал: {e}")
    else:
        print("pip install keyboard — чтобы работал глобальный хоткей")
    app.show()
    app.root.mainloop()


if __name__ == "__main__":
    main()
