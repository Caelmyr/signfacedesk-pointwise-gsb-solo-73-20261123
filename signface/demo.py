"""Deterministic practice photographs of an invented wayfinding panel."""
import io

import cv2 as cv
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .model import part_fields
from .store import key, now


PLANE = (760, 440)


def font(size):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def panel(role):
    noise = np.random.default_rng(12 if role == "day" else 31)
    backing = np.empty((440, 760, 3), np.float32)
    color = [17, 95, 125] if role == "day" else [27, 138, 159]
    backing[:] = color
    backing += noise.normal(0, 2.25, size=backing.shape[:2])[:, :, None]
    base = Image.fromarray(np.clip(backing, 0, 255).astype(np.uint8)).convert("RGBA")
    draw = ImageDraw.Draw(base)
    edge = "#eee5c6" if role == "day" else "#f2e6ae"
    draw.rounded_rectangle((9, 9, 750, 430), radius=22, outline=edge, width=7)
    draw.text((92, 90), "NORTH", fill=edge, font=font(83))
    draw.text((90, 190), "ARCADE", fill=edge, font=font(72))
    draw.polygon([(570, 90), (696, 185), (570, 280), (570, 228), (516, 228), (516, 139), (570, 139)],
                 fill=edge, outline=None)
    draw.line((91, 307, 696, 307), fill=edge, width=5)
    draw.rectangle((101, 355, 191, 407), fill=(*color, 255))
    draw.rectangle((218, 355, 294, 407), fill=(30, 40, 47, 255))
    draw.rectangle((434, 359, 531, 404), fill=(102, 139, 151, 255))
    for center in ((40, 34), (720, 37), (39, 408), (723, 408)):
        x, y = center
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill="#494946", outline="#a9a9a0", width=2)
    for x, y, w, h in ((168, 287, 26, 7), (303, 292, 45, 5), (626, 316, 34, 9)):
        draw.rounded_rectangle((x, y, x + w, y + h), radius=2, fill=(137, 151, 137, 255))
    if role == "night":
        draw.rounded_rectangle((312, 325, 411, 390), radius=14, fill=(19, 66, 91, 255))
        draw.rounded_rectangle((575, 319, 632, 381), radius=16, fill=(23, 88, 105, 255))
        draw.rectangle((676, 331, 711, 394), fill=(253, 255, 251, 255))
        draw.rectangle((641, 353, 663, 398), fill=(0, 0, 0, 0))
    return np.asarray(base)


def capture(library, role):
    h, w = 540, 920
    rng = np.random.default_rng(444)
    wall = np.empty((h, w, 4), np.uint8)
    ambient = rng.normal(0, 2, size=(h, w, 1))
    wall[:, :, :3] = np.clip(np.array([87, 84, 74]) + ambient, 0, 255)
    wall[:, :, 3] = 255
    corners = ([(74, 61), (842, 33), (857, 490), (75, 487)] if role == "day" else
               [(111, 55), (866, 69), (836, 483), (92, 496)])
    pw, ph = PLANE
    back_to_photo = cv.getPerspectiveTransform(
        np.array([(0, 0), (pw - 1, 0), (pw - 1, ph - 1), (0, ph - 1)], np.float32),
        np.asarray(corners, np.float32),
    )
    face = cv.warpPerspective(panel(role), back_to_photo, (w, h), flags=cv.INTER_LINEAR)
    field = cv.warpPerspective(np.ones((ph, pw), np.uint8), back_to_photo, (w, h), flags=cv.INTER_NEAREST) > 0
    wall[field] = face[field]
    buf = io.BytesIO()
    Image.fromarray(wall, "RGBA").save(buf, "PNG")
    return {"name": f"north-arcade-{role}.png", "role": role, "id": key(), "digest": library.put(buf.getvalue()),
            "corners": [[x / (w - 1), y / (h - 1)] for x, y in corners], "synthetic": True, "created_at": now()}


def rectangle(label, purpose, box):
    l, t, r, b = box
    w, h = PLANE
    return {"id": key(), "name": label, "purpose": purpose,
            "points": [[x / (w - 1), y / (h - 1)] for x, y in [(l, t), (r, t), (r, b), (l, b)]]}


def training(library):
    original = part_fields({"name": "North Arcade", "lot": "Synthetic wayfinding sign",
                            "width_mm": 760, "height_mm": 440})
    regions = [
        rectangle("Bottom film field", "inspect", (307, 316, 709, 405)),
        rectangle("Sound blue film", "reference", (111, 366, 181, 396)),
        rectangle("Dark return sample", "dark", (227, 367, 284, 396)),
        rectangle("Light arrow", "letter", (525, 143, 567, 197)),
        rectangle("Blue background", "background", (571, 284, 683, 300)),
    ]
    doc = library.create(original, [capture(library, "day"), capture(library, "night")], regions)
    return library.update(doc["id"], doc["revision"], lambda value: value.update(synthetic=True))
