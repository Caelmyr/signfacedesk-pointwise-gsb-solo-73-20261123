"""Frozen return scales built from marked controls and validated by check film.

A scale is built once on the Relative return tool and stored inside its reading.
Known-good check film only validates the scale: it never contributes to the
control levels. Weak return readings later reopen that frozen scale, so later
threshold changes or new measurements cannot alter the reference geometry.
"""
import math

import numpy as np

from image_lab.validation import Invalid

from .analysis import area_rows, islands_overlay, mask_for, observed, read_control, render, tone
from .model import number

SCHEMES = ("auto", "common", "split")
EXPECTED_RETURN = 1.0


def _pair(frame, signal, reference, dark):
    lo = read_control(frame, signal, dark, "Dark reference")
    hi = read_control(frame, signal, reference, "Sound return reference")
    if hi - lo < .06:
        raise Invalid("The two return controls do not have sufficient brightness separation.")
    return lo, hi


def _span(frame, mark):
    """Normalized horizontal extent of a mark; marks live on the registered plane."""
    h, w = frame.support.shape
    xs = np.asarray(mark["points"])[:, 0] * (w - 1)
    return float(xs.min()), float(xs.max())


def _zones_common(lo, hi):
    # x0/x1 are pixel extents on the registered plane; a common scale covers all columns.
    return [{"key": "common", "side": "common", "lo": round(float(lo), 6),
             "hi": round(float(hi), 6), "x0": 0, "x1": None}]


def _apply_zones(signal, zones, shape):
    """Piecewise normalized return; the split middle band is not assigned.

    Zone x0/x1 are pixel column extents; ``None`` means the full plane width.
    """
    scaled = np.full(shape, np.nan, np.float32)
    width = shape[1]
    for zone in zones:
        x0 = 0 if zone["x0"] is None else max(0, int(math.floor(zone["x0"])))
        x1 = width if zone["x1"] is None else min(width, int(math.ceil(zone["x1"])) + 1)
        if x1 > x0:
            scaled[:, x0:x1] = (signal[:, x0:x1] - zone["lo"]) / (zone["hi"] - zone["lo"])
    return scaled


def _check_rows(frame, scaled, checks):
    """Each (mark, tolerance) pair is known-good film that should read 1.0."""
    rows = []
    for mark, tol in checks:
        domain = mask_for(frame, mark)
        support = observed(frame, domain)
        if support.sum() < 24:
            raise Invalid(f"Check film {mark['name']} needs at least 24 visible, unclipped positions.")
        value = float(np.nanmedian(scaled[support]))
        if not math.isfinite(value):
            raise Invalid(f"Check film {mark['name']} falls outside the scale's assigned bands.")
        deviation = abs(value - EXPECTED_RETURN)
        rows.append({"name": mark["name"], "mark": mark["id"], "tolerance": round(float(tol), 4),
                     "observed_return": round(value, 4), "deviation": round(deviation, 4),
                     "passes": deviation <= tol + 1e-9})
    return rows


def _candidate_common(frame, signal, reference, dark, checks):
    lo, hi = _pair(frame, signal, reference, dark)
    zones = _zones_common(lo, hi)
    scaled = _apply_zones(signal, zones, frame.support.shape)
    check_rows = _check_rows(frame, scaled, checks) if checks else []
    return {"scheme": "common", "zones": zones, "checks": check_rows,
            "worst_deviation": max((row["deviation"] for row in check_rows), default=0.0)}


def _candidate_split(frame, signal, pairs, checks):
    (left_ref, left_dark), (right_ref, right_dark) = pairs
    left_lo, left_hi = _pair(frame, signal, left_ref, left_dark)
    right_lo, right_hi = _pair(frame, signal, right_ref, right_dark)
    left_spans = [_span(frame, mark) for mark in (left_ref, left_dark)]
    right_spans = [_span(frame, mark) for mark in (right_ref, right_dark)]
    left_end = max(span[1] for span in left_spans)
    right_start = min(span[0] for span in right_spans)
    if right_start <= left_end:
        raise Invalid("The left and right control pairs overlap horizontally; a side-specific scale needs a middle gap.")
    width_px = frame.support.shape[1] - 1
    gap0, gap1 = left_end / width_px, right_start / width_px
    zones = [
        {"key": "left", "side": "left", "lo": round(float(left_lo), 6), "hi": round(float(left_hi), 6),
         "x0": 0, "x1": int(math.floor(left_end))},
        {"key": "right", "side": "right", "lo": round(float(right_lo), 6), "hi": round(float(right_hi), 6),
         "x0": int(math.ceil(right_start)), "x1": None},
    ]
    scaled = _apply_zones(signal, zones, frame.support.shape)
    check_rows = _check_rows(frame, scaled, checks) if checks else []
    return {"scheme": "split", "zones": zones, "gap": [round(gap0, 6), round(gap1, 6)],
            "checks": check_rows, "worst_deviation": max((row["deviation"] for row in check_rows), default=0.0)}


def _check_in_zone(mark, zone, frame, label):
    """A side-specific check must sit inside the band its controls serve."""
    if zone is None:
        return
    x0, x1 = _span(frame, mark)
    if x0 < zone["x0"] or x1 > (frame.support.shape[1] if zone["x1"] is None else zone["x1"]):
        raise Invalid(f"{label} lies outside its side of the scale; mark it on the matching half.")


def build_scale(frame, options, marks):
    """Evaluate the candidate scale(s), validate check film and freeze one scale."""
    scheme = options.get("scale_scheme", "common")
    if scheme not in SCHEMES:
        raise Invalid("Choose a scale scheme: auto, common or split.")
    signal = tone(frame)
    left_ref, left_dark = marks["reference"], marks["dark"]
    right_ref = marks.get("reference_right")
    right_dark = marks.get("dark_right")
    check_left, check_right = marks.get("check_left"), marks.get("check_right")
    tol_left = number(options.get("tolerance_left", .15), "left check film tolerance", .001, 1.0)
    tol_right = number(options.get("tolerance_right", .15), "right check film tolerance", .001, 1.0)
    checks = [(mark, tol) for mark, tol in
              ((check_left, tol_left), (check_right, tol_right)) if mark]
    if scheme in ("auto", "split") and not (right_ref and right_dark):
        if scheme == "split":
            raise Invalid("A side-specific scale needs sound and dark controls on both sides.")
        scheme = "common"
    candidates = [_candidate_common(frame, signal, left_ref, left_dark, checks)]
    if right_ref and right_dark:
        try:
            split_candidate = _candidate_split(
                frame, signal, ((left_ref, left_dark), (right_ref, right_dark)), checks)
        except Invalid:
            if scheme == "split":
                raise
        else:
            candidates.append(split_candidate)
            left_zone = next(zone for zone in split_candidate["zones"] if zone["key"] == "left")
            right_zone = next(zone for zone in split_candidate["zones"] if zone["key"] == "right")
            if check_left is not None:
                _check_in_zone(check_left, left_zone, frame, "The left check film")
            if check_right is not None:
                _check_in_zone(check_right, right_zone, frame, "The right check film")
    for candidate in candidates:
        if checks and not all(row["passes"] for row in candidate["checks"]):
            candidate["accepted"] = False
        else:
            candidate["accepted"] = True
    if scheme == "common":
        chosen = candidates[0]
        if checks and not chosen["accepted"]:
            raise Invalid("The common reference scale fails one or both check film tolerances.")
        evaluated = candidates
    elif scheme == "split":
        chosen = next(candidate for candidate in candidates if candidate["scheme"] == "split")
        if checks and not chosen["accepted"]:
            raise Invalid("The side-specific scale fails one or both check film tolerances.")
        evaluated = [candidates[0], chosen]
    else:
        passing = [candidate for candidate in candidates if candidate["accepted"]]
        if not passing:
            raise Invalid("Neither scale scheme keeps both check film regions within tolerance.")
        split = next((candidate for candidate in passing if candidate["scheme"] == "split"), None)
        common = next((candidate for candidate in passing if candidate["scheme"] == "common"), None)
        if split is None:
            chosen = common
        elif common is None:
            chosen = split
        else:
            # Both schemes pass: prefer the better-aligned normal film; tie keeps
            # the common scale because it also covers the middle band.
            chosen = split if split["worst_deviation"] < common["worst_deviation"] - 1e-9 else common
        evaluated = candidates
    return {
        "scheme": chosen["scheme"],
        "requested_scheme": options.get("scale_scheme", "common"),
        "zones": chosen["zones"],
        "gap": chosen.get("gap"),
        "checks": chosen["checks"],
        "candidates": [
            {"scheme": candidate["scheme"], "accepted": candidate["accepted"],
             "worst_deviation": candidate["worst_deviation"],
             "checks": candidate["checks"]}
            for candidate in evaluated
        ],
        "observed_range": None,
        "controls": {key: mark["id"] for key, mark in marks.items()
                     if key in ("reference", "dark", "reference_right", "dark_right")},
        "normal_expected_return": EXPECTED_RETURN,
    }


def observed_scale_range(frame, domain, scaled):
    """The range actually seen inside the inspected domain; stored for later window reading."""
    support = observed(frame, domain)
    values = scaled[support]
    values = values[np.isfinite(values)]
    if not values.size:
        raise Invalid("The region contains no visible, unclipped reading positions.")
    return {"min": round(float(values.min()), 4), "p01": round(float(np.percentile(values, 1)), 4),
            "p50": round(float(np.median(values)), 4), "p99": round(float(np.percentile(values, 99)), 4),
            "max": round(float(values.max()), 4)}


def return_reading(frame, domain, options, marks, scale):
    signal = tone(frame)
    scaled = _apply_zones(signal, scale["zones"], frame.support.shape)
    scale["observed_range"] = observed_scale_range(frame, domain, scaled)
    support = observed(frame, domain)
    in_scale = support & np.isfinite(scaled)
    if not in_scale.any():
        raise Invalid("The region contains no visible positions covered by the frozen scale.")
    threshold = number(options.get("threshold", .62), "return threshold", .05, 1.5)
    good = in_scale & (scaled >= threshold)
    weak = in_scale & (scaled < threshold)
    unscaled = support & ~np.isfinite(scaled)
    unknown = domain & ~support
    labels = [("at or above threshold", good), ("below threshold", weak)]
    if unscaled.any():
        labels.append(("outside scale (middle band)", unscaled))
    labels.append(("unresolved", unknown))
    values = scaled[in_scale]
    quantiles = np.percentile(values, [10, 50, 90]).round(4).tolist()
    summary = {"p10_p50_p90": quantiles, "threshold": round(threshold, 4),
               "scale_scheme": scale["scheme"],
               "observed_positions": int(in_scale.sum())}
    if unscaled.any():
        summary["outside_scale_positions"] = int(unscaled.sum())
    return summary, area_rows(frame, labels), render(
        frame, [(good, "good"), (weak, "alert"), (unscaled, "unknown"), (unknown, "unknown")])


def reopen_scale(frame, frozen):
    """Recompute normalized return purely from the frozen controls of a saved scale."""
    signal = tone(frame)
    zones = []
    for zone in frozen["zones"]:
        lo = number(zone["lo"], "frozen dark level", 0.0, 1.0)
        hi = number(zone["hi"], "frozen reference level", 0.0, 1.0)
        if hi <= lo:
            raise Invalid("The frozen scale has invalid control levels.")
        zones.append({**zone, "lo": lo, "hi": hi})
    return _apply_zones(signal, zones, frame.support.shape)


def weak_reading(frame, domain, options, frozen, minimum):
    """Weak patches inside a window using a previously frozen scale, never a new one."""
    scaled = reopen_scale(frame, frozen)
    support = observed(frame, domain)
    in_scale = support & np.isfinite(scaled)
    threshold = number(options.get("threshold", .62), "return threshold", .05, 1.5)
    weak = in_scale & (scaled < threshold)
    rows, image = islands_overlay(frame, weak, support, {"minimum_mm2": minimum})
    unscaled = support & ~np.isfinite(scaled)
    summary = {"weak_patches": len(rows), "observed_positions": int(in_scale.sum()),
               "threshold": round(threshold, 4), "scale_scheme": frozen["scheme"],
               "scale_id": frozen["id"], "scale_source": frozen["reading_id"]}
    if unscaled.any():
        summary["outside_scale_positions"] = int(unscaled.sum())
        image[unscaled] = .38 * image[unscaled] + .62 * np.array((.68, .56, .79), np.float32)
    return summary, rows, image
