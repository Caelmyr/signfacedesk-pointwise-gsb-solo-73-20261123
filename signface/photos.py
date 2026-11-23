import io
from dataclasses import dataclass
from pathlib import Path

import cv2 as cv
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from image_lab.codecs import png_bytes
from image_lab.geometry import warp
from image_lab.validation import Invalid

from .model import grid, points


@dataclass(frozen=True)
class Frame:
    rgb: np.ndarray
    support: np.ndarray
    step_mm: np.ndarray

    @property
    def luma(self):
        return self.rgb @ np.array([.2126, .7152, .0722], np.float32)


def decode(raw):
    if not 0 < len(raw) <= 18 * 1024 * 1024:
        raise Invalid("Select a PNG, JPEG or TIFF under 18 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as original:
            if original.format not in ("PNG", "JPEG", "TIFF") or original.width * original.height > 12_000_000:
                raise Invalid("Use PNG, JPEG or TIFF with at most 12 megapixels.")
            im = ImageOps.exif_transpose(original).convert("RGBA")
            if min(im.size) < 32:
                raise Invalid("Each side of the photograph must be at least 32 pixels.")
            return np.asarray(im)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise Invalid("This file is not a supported photograph.") from exc


def basename(name):
    return Path(name).name[:120] or "capture"


def registered_corners(raw):
    normalized = points(raw, 4, 4, "registration")
    quad = np.array(normalized, np.float32)
    if not cv.isContourConvex(quad) or cv.contourArea(quad, oriented=True) < 0.02:
        raise Invalid("Mark four clockwise corners of a sufficiently large convex rectangle.")
    return normalized


def photograph(data, part, corners=None):
    rgb = data[:, :, :3].astype(np.float32) / 255
    support = data[:, :, 3] == 255
    size, step = grid(part)
    w, h = size
    if corners is None:
        corners = [[0, 0], [1, 0], [1, 1], [0, 1]]
    input_pixels = np.asarray(corners, np.float32) * np.asarray([data.shape[1] - 1, data.shape[0] - 1], np.float32)
    output_pixels = np.asarray([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32)
    transform = cv.getPerspectiveTransform(input_pixels, output_pixels)
    # Full interpolating footprint must have been observed.
    view = warp(rgb, transform, size)
    valid = warp(support.astype(np.float32), transform, size) >= .999
    return Frame(view, valid, step)


def canvas(frame):
    image = frame.rgb.copy()
    yy, xx = np.indices(frame.support.shape)
    hatch = np.where((xx + yy) % 14 < 6, .39, .27)
    image[~frame.support] = np.column_stack([hatch[~frame.support]] * 3)
    return image


def draw_mark(image, mark, label=False):
    h, w = image.shape[:2]
    coords = np.rint(np.asarray(mark["points"]) * [w - 1, h - 1]).astype(np.int32)
    colors = {"reference": (.98, .88, .23), "dark": (.31, .77, 1.), "letter": (.45, .89, .64), "background": (.83, .63, .96), "ignore": (1., .42, .33)}
    color = colors.get(mark["purpose"], (.45, 1., .68))
    cv.polylines(image, [coords], True, color, 2, cv.LINE_AA)
    if label and len(coords):
        cv.putText(image, mark["name"][:32], tuple(coords[0] + [4, -4]), cv.FONT_HERSHEY_SIMPLEX, .47, color, 1, cv.LINE_AA)


def preview(image, marks=()):
    result = image.copy()
    for mark in marks:
        draw_mark(result, mark)
    return png_bytes(result)


def raw_preview(data):
    return preview(data[:, :, :3].astype(np.float32) / 255)
