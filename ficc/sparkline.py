"""Inline SVG sparklines and range bars for dense monitor tables.

A terminal-style monitor needs 25+ instruments visible at once. Twenty-five
Plotly figures would be slow and enormous; twenty-five inline SVGs are a few
kilobytes of markup and render instantly. These are deliberately crude -- no
axes, no labels, no interactivity -- because at 64x16px the only readable
signal is the shape of the line and where the last point sits.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import theme


def _clean(s: pd.Series, points: int) -> np.ndarray | None:
    v = pd.Series(s).dropna().astype(float)
    if len(v) < 3:
        return None
    if len(v) > points:                      # even sampling, keeps the last point
        idx = np.linspace(0, len(v) - 1, points).round().astype(int)
        v = v.iloc[idx]
    return v.to_numpy()


def spark(s: pd.Series, *, width: int = 72, height: int = 18,
          color: str | None = None, points: int = 60) -> str:
    """A bare sparkline with a dot on the latest observation."""
    arr = _clean(s, points)
    if arr is None:
        return f'<svg width="{width}" height="{height}"></svg>'
    lo, hi = float(arr.min()), float(arr.max())
    rng = hi - lo
    pad = 2.0
    if rng <= 0:
        ys = np.full(len(arr), height / 2)
    else:
        ys = height - pad - (arr - lo) / rng * (height - 2 * pad)
    xs = np.linspace(1, width - 4, len(arr))
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    # Rising reads red, falling reads blue -- the same directional convention
    # as the change columns beside it. Having a row show red changes next to a
    # blue sparkline states the same fact in two opposite hues.
    c = color or (theme.RED_RATE if arr[-1] >= arr[0] else theme.BLUE_RATE)
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="vertical-align:middle">'
        f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="1.3" '
        f'stroke-linejoin="round" stroke-linecap="round" opacity="0.95"/>'
        f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="1.9" fill="{c}"/>'
        f"</svg>"
    )


def range_bar(pct: float | None, *, width: int = 62, height: int = 12) -> str:
    """Where the latest print sits inside its own range, as a marker on a track.

    The track carries faint 25/50/75 ticks so a position can be read without
    a number beside it; the marker is colored by how extreme it is.
    """
    if pct is None or pct != pct:
        return f'<svg width="{width}" height="{height}"></svg>'
    p = max(0.0, min(100.0, float(pct)))
    x = 1 + p / 100.0 * (width - 4)
    if p >= 90 or p <= 10:
        c = theme.SERIOUS
    elif p >= 75 or p <= 25:
        c = theme.YELLOW
    else:
        c = theme.BLUE
    ticks = "".join(
        f'<line x1="{1 + t / 100 * (width - 4):.1f}" y1="{height/2 - 3}" '
        f'x2="{1 + t / 100 * (width - 4):.1f}" y2="{height/2 + 3}" '
        f'stroke="{theme.AXIS}" stroke-width="1"/>'
        for t in (25, 50, 75))
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="vertical-align:middle">'
        f'<line x1="1" y1="{height/2}" x2="{width-3}" y2="{height/2}" '
        f'stroke="{theme.GRID}" stroke-width="3" stroke-linecap="round"/>'
        f"{ticks}"
        f'<rect x="{x-1.6:.1f}" y="{height/2 - 5}" width="3.2" height="10" '
        f'rx="1.2" fill="{c}"/>'
        f"</svg>"
    )
