"""Rasterize the app's simple pulse mark for Tk and Windows packaging."""

from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
scale = 4
image = Image.new("RGBA", (256 * scale, 256 * scale))
draw = ImageDraw.Draw(image)


def box(coordinates):
    return tuple(value * scale for value in coordinates)


draw.rounded_rectangle(box((8, 8, 248, 248)), radius=58 * scale, fill="#0e141b")
draw.rounded_rectangle(box((31, 31, 225, 225)), radius=42 * scale, fill="#17212b")
points = [(48, 134), (91, 134), (110, 76), (143, 184), (167, 118), (178, 134), (208, 134)]
draw.line([(x * scale, y * scale) for x, y in points], fill="#77e0c3", width=13 * scale, joint="curve")
for x, y in points:
    draw.ellipse(box((x - 6.5, y - 6.5, x + 6.5, y + 6.5)), fill="#77e0c3")
image = image.resize((256, 256), Image.Resampling.LANCZOS)
image.save(root / "assets/sitepulse.png")
image.save(
    root / "assets/sitepulse.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
)
