PingCheck

Compact site availability overlay. Hit Ctrl+Alt+P — a dark floating panelshows avg ping, per-site response times and HTTP statuses.

Features

    Global hotkey (configurable via config.json)
    Avg ping ring that fills up as checks complete
    Per-site ping + HTTP status (200 OK / 503 ERR / DOWN)
    Click a row to re-check, drag to move (position is saved)

Usage

pip install -r requirements.txtpython pingcheck.py

Config

config.json is auto-created on first run: sites, hotkey, timeout, autohide.
Build

pip install pyinstaller
pyinstaller --onefile --noconsole --name PingCheck pingcheck.py

Prebuilt Windows exe — see Actions artifacts.
License

MIT
