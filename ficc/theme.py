"""Design tokens and the shared Plotly template.

Every chart in the app draws from this one module, so fifteen panels read as
one system instead of fifteen default color cycles. The categorical ramp is the
validated eight-hue order; it clears the lightness band, chroma floor, adjacent
CVD separation, normal-vision floor, and 3:1 contrast against this app's dark
surface (#141922). Do not add a ninth hue -- a ninth series folds into "Other"
or becomes a small multiple.

Ink and chrome are cool-tinted relative to the reference warm-black, because
this app's surface is navy rather than warm charcoal; luminances are matched.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# -- surfaces ------------------------------------------------------------
PAGE = "#0B0E14"
SURFACE = "#141922"
SURFACE_2 = "#1B2230"
BORDER = "rgba(255,255,255,0.10)"

# -- ink -----------------------------------------------------------------
INK = "#EEF1F7"
INK_2 = "#A9B2C4"
MUTED = "#78839A"
GRID = "#232B39"
AXIS = "#333D4F"

# -- categorical: validated dark ramp, fixed order, never cycled ---------
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500",
          "#d55181", "#008300", "#9085e9", "#e66767"]
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = SERIES

# -- sequential (magnitude): single blue hue, light -> dark --------------
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

# -- diverging (polarity): blue <-> red, neutral gray midpoint -----------
# Rates convention: red = yields/spreads higher (selloff), blue = lower (rally).
DIVERGING = [
    [0.0, "#0d366b"], [0.15, "#256abf"], [0.35, "#86b6ef"],
    [0.5, "#2E3644"],
    [0.65, "#e88b8b"], [0.85, "#d03b3b"], [1.0, "#7d1f1f"],
]

# -- status: reserved, never reused as a series color --------------------
GOOD = "#0ca30c"
WARNING = "#fab219"
SERIOUS = "#ec835a"
CRITICAL = "#d03b3b"

# Rates-desk convention for yield moves: red = selloff, blue = rally.
RED_RATE = "#e06a6a"
BLUE_RATE = "#5598e7"

STATUS_COLORS = {"ok": GOOD, "cached": INK_2, "stale": WARNING, "failed": CRITICAL}
STATUS_ICONS = {"ok": "●", "cached": "◐", "stale": "▲", "failed": "✕"}

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def register() -> None:
    """Install 'ficc' as the default Plotly template."""
    t = go.layout.Template()
    t.layout = go.Layout(
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT, size=12, color=INK_2),
        # Title is pinned to the top of the *container* (the whole figure box),
        # while the legend is anchored to the top of the *plot area*. Anchoring
        # them to different references is what keeps them from colliding when
        # the chart is resized -- the top margin between the two is set in
        # apply(), sized to how many legend rows are actually expected.
        title=dict(font=dict(size=14, color=INK), x=0, xanchor="left",
                   y=1.0, yanchor="top", yref="container", pad=dict(t=12, b=0)),
        colorway=SERIES,
        margin=dict(l=54, r=18, t=78, b=40),
        xaxis=dict(gridcolor=GRID, zerolinecolor=AXIS, linecolor=AXIS,
                   tickfont=dict(color=MUTED, size=11), showline=False,
                   ticks="outside", tickcolor=AXIS, ticklen=4, automargin=True),
        yaxis=dict(gridcolor=GRID, zerolinecolor=AXIS, linecolor=AXIS,
                   tickfont=dict(color=MUTED, size=11), showline=False,
                   ticks="outside", tickcolor=AXIS, ticklen=4, automargin=True),
        legend=dict(orientation="h", yanchor="bottom", y=1.03, xanchor="left", x=0,
                    font=dict(size=11, color=INK_2), bgcolor="rgba(0,0,0,0)",
                    itemsizing="constant", itemwidth=30,
                    tracegroupgap=6),
        hoverlabel=dict(bgcolor=SURFACE_2, bordercolor=BORDER, font_size=12,
                        font_family=FONT, font_color=INK),
        hovermode="x unified",
        colorscale=dict(sequential=SEQ_BLUE, diverging=DIVERGING),
        dragmode="pan",
    )
    # Thin marks: 2px lines, >=8px markers.
    t.data.scatter = [go.Scatter(line=dict(width=2), marker=dict(size=8))]
    pio.templates["ficc"] = t
    pio.templates.default = "ficc"


# Vertical budget, in px, for the band above the plot area.
_TITLE_BAND = 34        # title text plus its padding
_LEGEND_ROW = 20        # one row of horizontal legend
_LEGEND_GAP = 12        # breathing room between title and legend
_NO_LEGEND_PAD = 16     # slack above the plot when there is no legend


def _legend_rows(fig: go.Figure, chars_per_row: int = 78) -> int:
    """Estimate how many rows a horizontal legend will wrap onto.

    Plotly gives no way to measure this before render, and a legend that wraps
    to a second row is exactly the case that collides with the title. Counting
    characters is crude, but it errs toward more headroom, which is the
    forgiving direction -- a little extra whitespace beats overlapping text.
    """
    names = [t.name for t in fig.data
             if getattr(t, "name", None) and getattr(t, "showlegend", None) is not False]
    if not names:
        return 0
    # ~6.2px per char at 11px, plus the swatch and gap per entry.
    width = sum(len(n) + 7 for n in names)
    return max(1, -(-width // chars_per_row))       # ceil division


def apply(fig: go.Figure, *, height: int = 300, legend: bool = True,
          unified: bool = True, compact: bool = False) -> go.Figure:
    """Final pass every figure goes through before st.plotly_chart.

    Sizes the top margin to the content: the title always needs its band, and
    each wrapped legend row needs another. A fixed margin either wastes space
    on single-series charts or lets a two-row legend run into the title.
    """
    # Compact mode: terminal density. Smaller title and ticks, tighter margins,
    # and the legend folded onto the title row where it fits, so a small
    # multiple spends its pixels on data rather than on chrome.
    rows = _legend_rows(fig, chars_per_row=52 if compact else 78) if legend else 0
    if compact:
        # 30px, not 22: the title sits at the container top with its own pad,
        # so too small a band lets the legend ride back up into it -- the exact
        # collision the standard mode was fixed for.
        title_band, legend_row, gap, slack = 30, 15, 7, 8
    else:
        title_band, legend_row, gap, slack = (
            _TITLE_BAND, _LEGEND_ROW, _LEGEND_GAP, _NO_LEGEND_PAD)
    top = title_band + (gap + rows * legend_row if rows else slack)

    if compact:
        fig.update_layout(
            title_font_size=11.5,
            font_size=10,
            title=dict(pad=dict(t=7, b=0)),
            legend=dict(font=dict(size=9.5), y=1.04),
            xaxis=dict(tickfont=dict(size=9)),
            yaxis=dict(tickfont=dict(size=9)),
            margin=dict(l=40, r=10, t=top, b=26),
        )
    else:
        fig.update_layout(margin=dict(l=54, r=18, t=top, b=40))

    fig.update_layout(
        height=height + max(0, top - (36 if compact else 50)),
        showlegend=legend and rows > 0,
        hovermode="x unified" if unified else "closest",
    )
    return fig


def delta_color(v: float | None, invert: bool = False, mode: str = "perf") -> str:
    """Ink color for a change value.

    Three conventions, because one size does not fit FICC:

      "perf"    up is good  -- prices, total returns. Green/red.
      "risk"    up is bad   -- spreads, vol. Green/red, inverted.
      "rates"   neither     -- a yield rising is not "good" or "bad", it is a
                              selloff. Uses the rates-desk convention: red for
                              higher yields, blue for lower.

    `invert=True` is kept as a shorthand for mode="risk".
    """
    if v is None or v != v or abs(v) < 1e-9:
        return INK_2
    if mode == "rates":
        return RED_RATE if v > 0 else BLUE_RATE
    up = v > 0
    if invert or mode == "risk":
        up = not up
    return GOOD if up else CRITICAL


def status_of(series) -> str:
    """Map a Series' freshness onto a status token."""
    return series.freshness.value
