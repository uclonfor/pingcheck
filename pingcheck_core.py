"""Configuration and HTTP probes for SitePulse; no GUI dependencies."""

from copy import deepcopy
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
from urllib.parse import urlsplit

import requests

APP_NAME = "SitePulse"
APP_VERSION = "1.1.0"
DEFAULT_CONFIG = {
    "hotkey": "ctrl+alt+p",
    "timeout": 5,
    "autohide_sec": 20,
    "animations": True,
    "pos": None,
    "sites": [
        {"domain": "google.com", "icon": "G"},
        {"domain": "github.com", "icon": "GH"},
        {"domain": "apple.com", "icon": "A"},
        {"domain": "cloudflare.com", "icon": "CF"},
        {"domain": "youtube.com", "icon": "YT"},
    ],
}


class ConfigError(ValueError):
    """A configuration problem that can be shown directly to the user."""


def config_path():
    """Keep source installs compatible; frozen apps use persistent user storage."""
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().with_name("config.json")
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME / "config.json"


def normalize_url(value):
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("Each site needs a non-empty domain or HTTP(S) URL.")
    value = value.strip()
    if any(c.isspace() for c in value):
        raise ConfigError("Site URLs cannot contain whitespace.")
    url = value if "://" in value else "https://" + value
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError
        if parts.username is not None or parts.password is not None:
            raise ValueError
        _ = parts.port
    except ValueError as exc:
        raise ConfigError("Use a valid HTTP(S) URL without embedded credentials.") from exc
    return url


def validate_config(raw):
    if not isinstance(raw, dict):
        raise ConfigError("The configuration must be a JSON object.")
    cfg = deepcopy(DEFAULT_CONFIG)
    cfg.update(raw)
    for key, minimum, maximum in (("timeout", 0.1, 120), ("autohide_sec", 0, 86400)):
        value = cfg[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not minimum <= value <= maximum
        ):
            raise ConfigError(f"{key} must be a number between {minimum} and {maximum}.")
    if not isinstance(cfg["animations"], bool):
        raise ConfigError("animations must be true or false.")
    if not isinstance(cfg["hotkey"], str):
        raise ConfigError("hotkey must be a string (empty disables it).")
    pos = cfg["pos"]
    if pos is not None and (not isinstance(pos, list) or len(pos) != 2 or any(type(v) is not int for v in pos)):
        raise ConfigError("pos must be null or two integer coordinates.")
    sites = cfg["sites"]
    if not isinstance(sites, list) or not 1 <= len(sites) <= 20:
        raise ConfigError("sites must contain between 1 and 20 entries.")
    for site in sites:
        if not isinstance(site, dict):
            raise ConfigError("Each site must be an object with a domain.")
        normalize_url(site.get("domain"))
        if "icon" in site and (not isinstance(site["icon"], str) or not 1 <= len(site["icon"]) <= 3):
            raise ConfigError("Site icons must contain 1 to 3 characters.")
    return cfg


def load_config(path=None):
    path = Path(path) if path is not None else config_path()
    if not path.exists():
        cfg = deepcopy(DEFAULT_CONFIG)
        save_config(cfg, path)
        return cfg
    try:
        return validate_config(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"Cannot load {path}: {exc}") from exc


def save_config(cfg, path=None):
    """Atomic replacement prevents a partial JSON file after an interrupted write."""
    path = Path(path) if path is not None else config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(cfg, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class ProbeResult:
    ms: float | None
    code: int | None
    error: str | None = None

    @property
    def ok(self):
        return self.code is not None and 200 <= self.code < 400


def check_site(domain, timeout):
    """Measure request-to-headers latency, including redirects and HEAD fallback."""
    try:
        url = normalize_url(domain)
        start = time.perf_counter()
        with requests.head(url, timeout=timeout, allow_redirects=True) as response:
            code = response.status_code
            elapsed = (time.perf_counter() - start) * 1000
        if code in (405, 501):
            with requests.get(url, timeout=timeout, stream=True, allow_redirects=True) as response:
                code = response.status_code
                elapsed = (time.perf_counter() - start) * 1000
        return ProbeResult(elapsed, code)
    except requests.exceptions.SSLError:
        return ProbeResult(None, None, "TLS error")
    except requests.exceptions.Timeout:
        return ProbeResult(None, None, "Timed out")
    except requests.exceptions.TooManyRedirects:
        return ProbeResult(None, None, "Redirect loop")
    except requests.exceptions.ConnectionError:
        return ProbeResult(None, None, "Connection failed")
    except (requests.RequestException, ConfigError):
        return ProbeResult(None, None, "Request failed")
