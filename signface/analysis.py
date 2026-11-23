"""Plane measurements that preserve the source's observed support."""
import math

import cv2 as cv
import numpy as np

from image_lab.validation import Invalid

from .model import number, points
from .photos import canvas


COLORS = {
    "good": (0.29, 0.92, 0.68),
    "alert": (1, 0.58, 0.23),
    "other": (0.40, 0.69, 1),
    "unknown": (0.68, 0.56, 0.79),
}


def plane_points(frame, coords):
    h, w = frame.support.shape
    return np.asarray(coords) * [w - 1, h - 1]


def mask_for(frame, region):
    if region is None:
        return np.ones(frame.support.shape, dtype=bool)
    polygon = np.rint(plane_points(frame, region["points"])).astype(np.int32)
    mask = np.zeros(frame.support.shape, np.uint8)
    cv.fillPoly(mask, [polygon], 1)
    return mask.astype(bool)


def domain_for(frame, region, exclusions):
    selected = mask_for(frame, region)
    for ignored in exclusions:
        selected &= ~mask_for(frame, ignored)
    if not selected.any():
        raise Invalid("The selected region has no positions after exclusions.")
    return selected


def exposure_masks(frame):
    """Channel clipping is distinguished from the image having no evidence."""
    high = (frame.rgb >= 0.995).any(axis=2) & frame.support
    low = (frame.rgb <= 0.012).all(axis=2) & frame.support
    return frame.support & ~(low | high), low, high


def observed(frame, domain):
    return exposure_masks(frame)[0] & domain


def tone(frame):
    # Relative camera-based linear brightness, never units of road brightness.
    rgb = frame.rgb
    linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    return linear @ np.array([.2126, .7152, .0722], np.float32)


def render(frame, layers):
    image = canvas(frame)
    for mask, color in layers:
        image[mask] = .38 * image[mask] + .62 * np.asarray(COLORS[color])
    return image


def area_rows(frame, labels):
    mm2_per_pixel = float(np.prod(frame.step_mm))
    return [{"class": name, "positions": int(mask.sum()),
             "area_mm2": round(float(mask.sum()) * mm2_per_pixel, 2)} for name, mask in labels]


def read_control(frame, signal, mark, label):
    values = signal[mask_for(frame, mark) & exposure_masks(frame)[0]]
    if values.size < 24:
        raise Invalid(f"{label} needs at least 24 visible, unclipped positions.")
    return float(np.median(values))


def region_levels(frame, reference, dark):
    signal = tone(frame)
    lo = read_control(frame, signal, dark, "Dark reference")
    hi = read_control(frame, signal, reference, "Sound return reference")
    if hi - lo < .06:
        raise Invalid("The two return controls do not have sufficient brightness separation.")
    return (signal - lo) / (hi - lo), lo, hi


def connected(frame, detected, support, minimum):
    """Record observed footprints. Flag components that touch unknown pixels."""
    count, labels, stats, centers = cv.connectedComponentsWithStats(detected.astype(np.uint8), connectivity=8)
    uncertain = cv.dilate((~support).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    uncertain[[0, -1], :] = True
    uncertain[:, [0, -1]] = True
    edge_ids = set(labels[uncertain])
    area_factor = float(np.prod(frame.step_mm))
    rows = []
    h, w = labels.shape
    for label in range(1, count):
        x, y, width, height, population = [int(value) for value in stats[label]]
        if population * area_factor < minimum:
            continue
        box = labels[y:y + height, x:x + width] == label
        contours, _ = cv.findContours(box.astype(np.uint8), cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
        points = max(contours, key=cv.contourArea).reshape(-1, 2)
        stride = max(1, math.ceil(len(points) / 80))
        contour = ((points[::stride] + [x, y]) / [max(1, w - 1), max(1, h - 1)]).round(5)
        rows.append({
            "label": label, "area_mm2": round(population * area_factor, 2),
            "center_mm": (centers[label] * frame.step_mm).round(2).tolist(),
            "bounded": label not in edge_ids, "outline": contour.tolist(),
        })
    return labels, sorted(rows, key=lambda row: (-row["area_mm2"], row["label"]))


def islands_overlay(frame, found, support, options):
    minimum = number(options.get("minimum_mm2", 30), "minimum marked area", 1, 100_000)
    labels, rows = connected(frame, found, support, minimum)
    visible = np.array([row["label"] for row in rows], dtype=np.int32)
    return rows, render(frame, [(np.isin(labels, visible), "alert")])


def outline(frame, domain, options):
    cut = number(options.get("threshold", .32), "face threshold", .02, .95)
    support = observed(frame, domain)
    regions, rows = connected(frame, support & (tone(frame) >= cut), support, 25)
    image = render(frame, [(regions > 0, "good"), (domain & ~support, "unknown")])
    return {"connected_faces": len(rows), "closed_faces": sum(row["bounded"] for row in rows)}, rows, image


def holes(frame, domain, options):
    support = observed(frame, domain)
    lab = cv.cvtColor(frame.rgb, cv.COLOR_RGB2Lab)
    chroma = np.linalg.norm(lab[:, :, 1:], axis=2)
    chroma_limit = number(options.get("threshold", 14), "chroma limit", 1, 100)
    candidate = support & (chroma < chroma_limit) & (lab[:, :, 0] > 30)
    rows, image = islands_overlay(frame, candidate, support, options)
    return {"candidate_finish_patches": len(rows)}, rows, image


def relative_return(frame, domain, options, reference, dark):
    scaled, lo, hi = region_levels(frame, reference, dark)
    support = observed(frame, domain)
    signal = scaled[support]
    if not signal.size:
        raise Invalid("The region contains no visible, unclipped reading positions.")
    threshold = number(options.get("threshold", .62), "return threshold", .05, 1.5)
    good = support & (scaled >= threshold)
    weak = support & ~good
    unknown = domain & ~support
    metrics = area_rows(frame, [("at or above threshold", good), ("below threshold", weak), ("unresolved", unknown)])
    quantiles = np.percentile(signal, [10, 50, 90]).round(4).tolist()
    return {"p10_p50_p90": quantiles, "dark_level": round(lo, 5), "reference_level": round(hi, 5)}, metrics, render(
        frame, [(good, "good"), (weak, "alert"), (unknown, "unknown")]
    )


def weak_patches(frame, domain, options, reference, dark):
    scaled, lo, hi = region_levels(frame, reference, dark)
    support = observed(frame, domain)
    threshold = number(options.get("threshold", .62), "return threshold", .05, 1.5)
    weak = support & (scaled < threshold)
    rows, image = islands_overlay(frame, weak, support, options)
    return {"weak_patches": len(rows), "observed_positions": int(support.sum()),
            "dark_level": round(lo, 5), "reference_level": round(hi, 5)}, rows, image


def contrast(frame, domain, options, letter, background):
    signal = tone(frame)
    left = read_control(frame, signal, letter, "Letter face")
    right = read_control(frame, signal, background, "Letter background")
    ratio = abs(left - right) / max(left, right, 1e-6)
    support = observed(frame, domain)
    foreground = support & mask_for(frame, letter)
    ground = support & mask_for(frame, background)
    summary = {"letter_luminance": round(left, 5), "background_luminance": round(right, 5),
               "relative_contrast": round(ratio, 5), "polarity": "lighter lettering" if left > right else "darker lettering"}
    return summary, area_rows(frame, [("letter", foreground), ("background", ground)]), render(
        frame, [(foreground, "good"), (ground, "other")]
    )


def surface(frame, domain, options):
    support = observed(frame, domain)
    if support.sum() < 12:
        raise Invalid("Choose an observed surface with at least 12 usable pixels.")
    planes = cv.cvtColor(frame.rgb, cv.COLOR_RGB2Lab)[support]
    means = np.median(planes, axis=0)
    variation = np.median(np.linalg.norm(planes - means, axis=1))
    row = {"lightness": round(float(means[0]), 3), "a": round(float(means[1]), 3), "b": round(float(means[2]), 3),
           "positions": int(planes.shape[0])}
    return {"median_color_distance": round(float(variation), 3)}, [row], render(frame, [(support, "good")])


def glare(frame, domain, options):
    valid, low, high = exposure_masks(frame)
    unseen = domain & ~frame.support
    labels = [
        ("usable", valid & domain), ("black clipped", low & domain),
        ("white clipped", high & domain), ("unseen", unseen),
    ]
    colors = ["good", "other", "alert", "unknown"]
    return {"usable_pct": round(100 * (valid & domain).sum() / domain.sum(), 2)}, area_rows(frame, labels), render(
        frame, [(mask, color) for (_, mask), color in zip(labels, colors)]
    )


def coverage(frame, second, domain, options):
    first = observed(frame, domain)
    other = observed(second, domain)
    both = first & other
    labels = [
        ("both", both), ("first only", first & ~other),
        ("second only", other & ~first), ("neither", domain & ~(first | other)),
    ]
    colors = ["good", "other", "alert", "unknown"]
    return {"common_visible_pct": round(100 * both.sum() / domain.sum(), 2)}, area_rows(frame, labels), render(
        frame, [(mask, color) for (_, mask), color in zip(labels, colors)]
    )


def profile(frame, domain, options):
    ends = plane_points(frame, points(options.get("points"), 2, 2, "the transect"))
    vector = ends[1] - ends[0]
    size = np.linalg.norm(vector)
    if size < 8:
        raise Invalid("Put the line endpoints at least eight plane pixels apart.")
    length = float(np.linalg.norm(vector * frame.step_mm))
    count = min(420, int(math.ceil(size)) + 1)
    grid = np.linspace(*ends, count)
    x, y = np.rint(grid).astype(int).T
    support = observed(frame, domain)[y, x]
    signal = tone(frame)[y, x]
    rows = [{"distance_mm": round(length * index / (count - 1), 3), "observed": bool(valid),
             "linear_luminance": round(float(level), 5) if valid else None}
            for index, (valid, level) in enumerate(zip(support, signal))]
    image = canvas(frame)
    for index in range(count - 1):
        style = COLORS["good"] if support[index] and support[index + 1] else COLORS["unknown"]
        cv.line(image, (x[index], y[index]), (x[index + 1], y[index + 1]), style, 3, cv.LINE_AA)
    return {"line_length_mm": round(length, 3), "usable_stations": int(support.sum())}, rows, image


def scuffs(frame, domain, options):
    support = observed(frame, domain)
    signal = tone(frame)
    radius_mm = number(options.get("radius_mm", 14), "background radius", 1, 100)
    radius = max(1, radius_mm / float(np.mean(frame.step_mm)))
    weights = cv.GaussianBlur(support.astype(np.float32), (0, 0), radius)
    local = cv.GaussianBlur(np.where(support, signal, 0), (0, 0), radius) / np.maximum(weights, 1e-4)
    threshold = number(options.get("threshold", .14), "local contrast threshold", .02, .80)
    where = support & (weights > .8)
    rows, image = islands_overlay(frame, where & (local - signal > threshold), where, options)
    return {"scuff_footprints": len(rows)}, rows, image
