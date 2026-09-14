"""A small, keyboard-accessible settings window for SitePulse."""

from copy import deepcopy
import tkinter as tk
from urllib.parse import urlsplit

from pingcheck_core import ConfigError, normalize_url, validate_config

BG = "#0e141b"
PANEL = "#17212b"
TEXT = "#e7edf2"
DIM = "#8e9ca9"
ACCENT = "#77e0c3"


def configuration_from_fields(cfg, sites, timeout, autohide, animations, hotkey):
    updated = deepcopy(cfg)
    try:
        updated["timeout"] = float(timeout)
        updated["autohide_sec"] = float(autohide)
    except ValueError as exc:
        raise ConfigError("Timeout and auto-hide must be numbers.") from exc
    existing = {site["domain"]: site for site in cfg["sites"]}
    updated["sites"] = []
    for line in sites.splitlines():
        domain = line.strip()
        if not domain:
            continue
        hostname = urlsplit(normalize_url(domain)).hostname
        site = deepcopy(existing.get(domain, {"domain": domain, "icon": hostname[:2].upper()}))
        updated["sites"].append(site)
    updated.update(animations=animations, hotkey=hotkey.strip())
    return validate_config(updated)


class SettingsDialog:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title("SitePulse · Settings")
        self.window.configure(bg=BG)
        self.window.resizable(False, False)
        self.window.transient(app.root)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", lambda event: self.close())
        self.window.bind("<Control-Return>", lambda event: self.save())
        body = tk.Frame(self.window, bg=BG, padx=24, pady=20)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        self._label(body, "Make it yours", 17, True).grid(row=0, column=0, columnspan=2, sticky="w")
        self._label(body, "One site per line. Checks follow this order.", 9, color=DIM).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 14)
        )
        self.sites = tk.Text(
            body,
            width=45,
            height=8,
            bg=PANEL,
            fg=TEXT,
            insertbackground=ACCENT,
            selectbackground="#31574f",
            relief="flat",
            padx=10,
            pady=10,
            font=(app.font, 10),
            wrap="none",
            undo=True,
            highlightthickness=1,
            highlightbackground=PANEL,
            highlightcolor=ACCENT,
        )
        self.sites.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.sites.insert("1.0", "\n".join(site["domain"] for site in app.cfg["sites"]))
        self.sites.bind("<Tab>", lambda e: self._next_field())
        self._label(body, "Domains or http(s):// URLs · up to 20 sites", 8, color=DIM).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 16)
        )
        self.timeout = tk.StringVar(value=str(app.cfg["timeout"]))
        self.autohide = tk.StringVar(value=str(app.cfg["autohide_sec"]))
        self.hotkey = tk.StringVar(value=app.cfg["hotkey"])
        self.animations = tk.BooleanVar(value=app.cfg["animations"])
        self._label(body, "Request timeout (seconds)", 9).grid(row=4, column=0, sticky="w")
        self._label(body, "Auto-hide (0 = keep open)", 9).grid(row=4, column=1, sticky="w", padx=(14, 0))
        self.timeout_entry = self._entry(body, self.timeout)
        self.timeout_entry.grid(row=5, column=0, sticky="ew", pady=(6, 14))
        self._entry(body, self.autohide).grid(row=5, column=1, sticky="ew", padx=(14, 0), pady=(6, 14))
        self._label(body, "Global hotkey (Windows)", 9).grid(row=6, column=0, columnspan=2, sticky="w")
        self._entry(body, self.hotkey).grid(row=7, column=0, columnspan=2, sticky="ew", pady=(6, 12))
        tk.Checkbutton(
            body,
            text="Animate the path and response highlights",
            variable=self.animations,
            bg=BG,
            fg=TEXT,
            activebackground=BG,
            activeforeground=ACCENT,
            selectcolor=PANEL,
            font=(app.font, 9),
            anchor="w",
            highlightthickness=0,
        ).grid(row=8, column=0, columnspan=2, sticky="w")
        self.error = self._label(body, "", 9, color="#ff818b")
        self.error.configure(wraplength=410, justify="left")
        self.error.grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 6))
        buttons = tk.Frame(body, bg=BG)
        buttons.grid(row=10, column=0, columnspan=2, sticky="e")
        for text, command, color, foreground in (
            ("Cancel", self.close, PANEL, TEXT),
            ("Apply demo" if app.demo else "Save & check", self.save, ACCENT, BG),
        ):
            tk.Button(
                buttons,
                text=text,
                command=command,
                bg=color,
                fg=foreground,
                activebackground=color,
                activeforeground=foreground,
                relief="flat",
                padx=15,
                pady=9,
                font=(app.font, 9, "bold"),
                cursor="hand2",
            ).pack(side="left", padx=(8, 0))
        self.window.update_idletasks()
        x = max(0, min(app.root.winfo_x(), app.root.winfo_screenwidth() - self.window.winfo_width()))
        y = max(0, min(app.root.winfo_y(), app.root.winfo_screenheight() - self.window.winfo_height() - 60))
        self.window.geometry(f"{x:+d}{y:+d}")
        self.window.grab_set()
        self.sites.focus_set()

    def _label(self, parent, text, size, bold=False, color=TEXT):
        return tk.Label(parent, text=text, bg=BG, fg=color, font=(self.app.font, size, "bold" if bold else "normal"))

    def _entry(self, parent, variable):
        return tk.Entry(
            parent,
            textvariable=variable,
            bg=PANEL,
            fg=TEXT,
            insertbackground=ACCENT,
            relief="flat",
            font=(self.app.font, 10),
            width=20,
            highlightthickness=1,
            highlightbackground=PANEL,
            highlightcolor=ACCENT,
        )

    def _next_field(self):
        self.timeout_entry.focus_set()
        return "break"

    def save(self):
        try:
            cfg = configuration_from_fields(
                self.app.cfg,
                self.sites.get("1.0", "end"),
                self.timeout.get(),
                self.autohide.get(),
                self.animations.get(),
                self.hotkey.get(),
            )
            self.app.apply_settings(cfg)
        except (ConfigError, OSError) as exc:
            self.error.configure(text=str(exc))
            return False
        self.close()
        self.app.start_checks()
        return True

    def close(self):
        self.window.grab_release()
        self.window.destroy()
        self.app.settings = None
        self.app._schedule_autohide()
