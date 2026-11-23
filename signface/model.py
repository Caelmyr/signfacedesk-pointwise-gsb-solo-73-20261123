import math
import re

import numpy as np

from image_lab.validation import Invalid

IDENTITY = re.compile(r"^[0-9a-f]{20}$")
ROLES = {"day": "Daylight", "night": "Night return", "raking": "Raking light", "detail": "Detail"}
MARKS = {
    "inspect": "Inspection region", "ignore": "Exclude from readings",
    "reference": "Sound return reference", "dark": "Dark reference",
    "check": "Known-good check film",
    "letter": "Letter face", "background": "Letter background",
}
TOOLS = {
    "outline": ("Panel outline", "Find the visible light-toned sign face against its backing."),
    "holes": ("Missing finish", "Read visible low-chroma patches against a colored field."),
    "profile": ("Luminance transect", "Read supported brightness along a marked line."),
    "return": ("Relative return", "Build and freeze a return scale from marked controls; known-good check film validates it without becoming a control."),
    "weak": ("Weak return patches", "Reopen a frozen return scale inside a small window and keep the measured weak footprints."),
    "contrast": ("Legibility contrast", "Compare marked letter and background luminance."),
    "surface": ("Surface color", "Measure calibrated-plane Lab color on current observed pixels."),
    "glare": ("Exposure support", "Distinguish usable, clipped and unseen positions."),
    "coverage": ("Paired visibility", "Compare usable positions in two registered views."),
    "scuffs": ("Surface marks", "Inspect high-contrast scuffs on the registered view."),
}


def identifier(value):
    if not isinstance(value, str) or not IDENTITY.fullmatch(value):
        raise Invalid("Invalid identifier.")
    return value


def text(value, label, limit=96, optional=False):
    if not isinstance(value, str) or len(value.strip()) > limit or (not optional and not value.strip()):
        raise Invalid(f"Enter {label} with at most {limit} characters.")
    return value.strip()


def number(value, label, low, high):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise Invalid(f"Enter a number for {label}.") from None
    if isinstance(value, bool) or not math.isfinite(result) or not low <= result <= high:
        raise Invalid(f"{label} must be between {low:g} and {high:g}.")
    return result


def opts(data):
    if not isinstance(data, dict):
        raise Invalid("Send an object with the form values.")
    return data


def points(raw, minimum, maximum, label):
    if not isinstance(raw, list) or not minimum <= len(raw) <= maximum:
        raise Invalid(f"{label} needs {minimum} to {maximum} marked points.")
    result = []
    for pair in raw:
        if not isinstance(pair, list) or len(pair) != 2:
            raise Invalid(f"Use pairs of coordinates for {label}.")
        result.append([number(item, label, 0, 1) for item in pair])
    return result


def choice(value, choices, label):
    if value not in choices:
        raise Invalid(f"Choose a {label}.")
    return value


def polygon(raw):
    marks = opts(raw)
    return points(marks.get("points"), 3, 40, "region")


def part_fields(raw):
    data = opts(raw)
    return {
        "name": text(data.get("name"), "a panel name"),
        "lot": text(data.get("lot", ""), "a site reference", 60, optional=True),
        "width_mm": number(data.get("width_mm"), "panel width (mm)", 25, 10000),
        "height_mm": number(data.get("height_mm"), "panel height (mm)", 25, 10000),
    }


def mark_fields(raw):
    data = opts(raw)
    purpose = choice(data.get("purpose"), MARKS, "mark purpose")
    return {"name": text(data.get("name"), "a mark name"), "purpose": purpose, "points": polygon(data)}


def locate(items, requested, label):
    requested = identifier(requested)
    for item in items:
        if item["id"] == requested:
            return item
    raise Invalid(f"{label} is no longer available.")


def grid(part):
    longest = max(part["width_mm"], part["height_mm"])
    samples = min(4.0, 1450 / longest)
    w = max(16, round(part["width_mm"] * samples))
    h = max(16, round(part["height_mm"] * samples))
    return (w, h), np.array([part["width_mm"] / w, part["height_mm"] / h])
