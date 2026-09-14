<div align="center">

<img src="assets/sitepulse.svg" width="64" alt="SitePulse icon">

# SitePulse

**English** | [Русский](README.ru.md)

**The pulse of your websites, right on your desktop.**

A compact Python/Tkinter widget for website availability, HTTP response times, and an animated chain of checks.
Previously called **PingCheck**; the launch command remains `python pingcheck.py`.

**[Download for Windows](https://github.com/uclonfor/pingcheck/releases/latest/download/SitePulse.exe)** · [All releases](https://github.com/uclonfor/pingcheck/releases)

![Build and tests](https://github.com/uclonfor/pingcheck/actions/workflows/build.yml/badge.svg)

![SitePulse animation with demo data](docs/sitepulse.gif)

*The preview uses demo values, not live measurements of website availability.*

</div>

## Features

- Checks websites **one at a time**: each request starts only after the previous one finishes. The app's own measurements do not compete with one another.
- A light pulse travels to the next site before its request starts. The active row pulses while waiting, then briefly lights up when a response arrives and advances the progress ring. Animation time is excluded from the measurement.
- Shows average response time, HTTP codes, and distinct TLS, connection, timeout, and redirect errors.
- Keeps the last 18 checks for each site in memory. Each row's chart has its own scale.
- Rechecks a single site on click, or the entire list with `R` or `F5`. **Stop scan** stops the queue after the current request.
- Lets you edit sites, timeout, auto-hide, and animations in **Settings**, without editing JSON.
- Remembers the window position, supports up to 20 sites, and scrolls longer lists.
- Includes a smooth window entrance, row highlights, and an option to disable animations.
- Runs without administrator privileges. Windows supports a global hotkey; on Ubuntu, you can minimize and restore the window from the taskbar.

## Quick start

Requires **Python 3.10+**, Tk, and a graphical desktop session.

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install python3 python3-venv python3-tk
git clone https://github.com/uclonfor/pingcheck.git
cd pingcheck
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python pingcheck.py
```

Run the app as your normal user, without `sudo`: global keyboard interception is deliberately disabled on Linux. On Wayland, window placement and always-on-top behavior depend on the window manager.

### Windows (PowerShell)

```powershell
git clone https://github.com/uclonfor/pingcheck.git
cd pingcheck
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe pingcheck.py
```

You can also download a ready-to-run `SitePulse.exe` from the [latest release](https://github.com/uclonfor/pingcheck/releases/latest). It does not require a separate Python installation.

After a successful GitHub Actions build, the executable is also available under **Actions → Build and tests → select a run → Artifacts → SitePulse-windows**. Extract the archive and run `SitePulse.exe`. This is a CI artifact, not a signed installer.

## Controls

| Action | Control |
| --- | --- |
| Check all sites | **Check again**, `R`, or `F5` |
| Check one site | Click its row |
| Stop a scan | **Stop scan**; the current request finishes and the remaining requests do not start |
| Open settings | **Settings** or `Ctrl+,` after the scan finishes |
| Move the window | Drag the title bar or the top area of the widget |
| Hide / minimize | `Esc`, or automatically after a scan |
| Show / hide on Windows | `Ctrl+Alt+P`, if the hotkey was successfully registered |
| Restore without a global hotkey | Use the taskbar |
| Quit | The window's close button or `Ctrl+Q` |

Repeated start commands are ignored during a scan. After **Stop scan**, a new scan also waits for the current request to finish, so measurements cannot overlap. The auto-hide countdown starts when the current scan, including its transitions, finishes. The close button **exits the process**; `Esc` hides the window when a global hotkey is active, or minimizes it otherwise.

## Configuration

Open **Settings**, enter one site per line, adjust the timeout, and click **Save & check**. Changes take effect immediately. The line order determines the check order, and existing site icons are preserved. In `--demo` mode, **Apply demo** updates only the demo window without writing to disk.

![SitePulse settings window](docs/settings.png)

The first normal launch creates `config.json`:

- From source: next to `pingcheck_core.py`.
- Windows `.exe`: `%APPDATA%\SitePulse\config.json`, outside PyInstaller's temporary directory.
- Other packaged builds: `$XDG_CONFIG_HOME/SitePulse/config.json` or `~/.config/SitePulse/config.json`.

To use a custom configuration file:

```bash
python pingcheck.py --config /path/to/config.json
```

See [`config.example.json`](config.example.json):

```json
{
  "hotkey": "ctrl+alt+p",
  "timeout": 5,
  "autohide_sec": 20,
  "animations": true,
  "pos": null,
  "sites": [
    {"domain": "github.com", "icon": "GH"},
    {"domain": "https://example.com/health", "icon": "EX"},
    {"domain": "http://localhost:8080", "icon": "LC"}
  ]
}
```

| Field | Meaning |
| --- | --- |
| `hotkey` | Windows global hotkey; `""` disables it |
| `timeout` | Connection / read timeout in seconds: 0.1–120 |
| `autohide_sec` | Hide delay in seconds: 0–86400; `0` disables auto-hide |
| `animations` | `false` disables window entrance, pulsing, and transition animations; requests remain sequential |
| `pos` | `null` for automatic placement, or `[x, y]` |
| `sites` | 1–20 objects; `domain` is required, and `icon` contains 1–3 characters |

Missing fields use the defaults. Restart the app after editing the file manually. Invalid JSON or unsupported values produce an error with the file path; the original configuration is preserved so you can fix it. Position updates use a temporary file and atomic replacement.

## What the numbers mean

**This measures HTTP response time, not ICMP ping or internet speed.** The timer includes connection setup, TLS, redirects, and receiving response headers. The average includes all received HTTP responses, including `4xx/5xx`; network failures are excluded.

Timing starts immediately before the network request and ends when its headers arrive. The animated transition between rows is excluded. The sequential queue prevents SitePulse's own requests from running simultaneously, but background traffic, DNS/TLS work, and thread scheduling can still affect the results. This is not a tool for measuring microsecond latency.

Each check starts with `HEAD`. If the server returns `405` or `501`, the app falls back to a streamed `GET` without deliberately consuming the response body. Domains without a scheme use `https://`. An HTTPS failure never silently falls back to HTTP: specify `http://` explicitly for an HTTP server.

`2xx/3xx` count as successful HTTP responses; `4xx/5xx` count as HTTP errors. A `403` may indicate bot protection rather than a site being unavailable in a browser. A successful status code does not guarantee that every part of a service is healthy.

`timeout` is not a deadline for the entire check: redirects, DNS, and a fallback `GET` can increase its duration. See [Requests timeout behavior](https://requests.readthedocs.io/en/stable/user/quickstart/#timeouts). Responses are closed after reading their headers, following the [Requests streaming workflow](https://requests.readthedocs.io/en/stable/user/advanced/#body-content-workflow).

History lasts until the app closes. Automatic periodic monitoring and notifications are not currently implemented.

## Development and testing

`pingcheck_core.py` handles network checks and configuration; `pingcheck.py` contains the window, sequential scheduler, and animations; `sitepulse_settings.py` provides the settings editor. The single active network worker sends its result through a queue, while Tk updates run on the main thread, following the [Tkinter threading model](https://docs.python.org/3/library/tkinter.html#threading-model).

```bash
pip install -r requirements-dev.txt
ruff check .
python -m unittest discover -s tests -v
```

GUI tests are skipped when no display is available. To run the full suite on Linux:

```bash
sudo apt install xvfb xauth
xvfb-run -a python -m unittest discover -s tests -v
```

Tests use a local HTTP server and mocked responses; no public websites are required. They cover configuration, atomic writes, redirects, fallback `GET`, TLS errors, non-overlapping requests, stopping the queue, starting requests after animations, settings, and the window lifecycle. CI runs GUI tests on both Linux and Windows.

### Preview the animation offline

```bash
python pingcheck.py --demo
```

`--demo` uses clearly labeled sample results. It does not read or write the user's configuration or register a global hotkey. To regenerate the PNG/GIF previews from the actual interface:

```bash
xvfb-run -a -s '-screen 0 1280x900x24' python scripts/capture_preview.py
```

### Build a Windows `.exe`

On Windows, with the virtual environment activated:

```powershell
python -m pip install pyinstaller
python -m PyInstaller --onefile --noconsole --name SitePulse --icon assets/sitepulse.ico --add-data "assets:assets" pingcheck.py
```

Output: `dist/SitePulse.exe`. Run PyInstaller on the target operating system. CI runs tests and lint checks before building the Windows app and generating demo previews.

## Future ideas

- A system tray icon and native Linux global shortcuts.
- Periodic checks, status-change notifications, and history export.

## License

[MIT](LICENSE).
