"""Capture the real Tk interface with deterministic demo data (no network)."""

from copy import deepcopy
from pathlib import Path
import sys
import time

from PIL import ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pingcheck import PingCheckApp  # noqa: E402
from pingcheck_core import DEFAULT_CONFIG  # noqa: E402


def main():
    output = Path(__file__).resolve().parents[1] / "docs"
    output.mkdir(exist_ok=True)
    cfg = deepcopy(DEFAULT_CONFIG)
    cfg.update(pos=[40, 40], autohide_sec=0)
    app = PingCheckApp(cfg, demo=True)
    app.root.update()
    app.start_checks()
    frames = []
    start = time.monotonic()
    for index in range(105):
        target = start + index * 0.05
        while time.monotonic() < target:
            app.root.update()
            time.sleep(0.003)
        app.root.update()
        x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
        frame = ImageGrab.grab(bbox=(x, y, x + app.w, y + app.h))
        frames.append(frame)
    frames[-1].save(output / "sitepulse.png")
    frames[0].save(
        output / "sitepulse.gif", save_all=True, append_images=frames[1:], duration=50, loop=0, optimize=False
    )
    # A contact sheet makes the actual transition easy to inspect in a static viewer.
    from PIL import Image

    sheet = Image.new("RGB", (app.w * 4, app.h))
    for column, index in enumerate((3, 22, 45, 90)):
        sheet.paste(frames[index], (app.w * column, 0))
    sheet.save(output / "animation-frames.png")
    app.open_settings()
    app.root.update()
    window = app.settings.window
    x, y = window.winfo_rootx(), window.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x + window.winfo_width(), y + window.winfo_height())).save(output / "settings.png")
    app.settings.close()
    app.close()
    print("Captured docs/sitepulse.png and docs/sitepulse.gif")


if __name__ == "__main__":
    main()
