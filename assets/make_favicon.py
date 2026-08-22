"""Generate the browser-tab icon.

A favicon is read at 16px, so the mark has to survive being tiny: one bold
shape, high contrast against both light and dark tab bars, no fine detail.
The shape is a yield curve -- steep through the front end, flattening out the
back -- drawn in the app's own categorical blue on the app's surface navy, so
the tab matches the dashboard rather than looking bolted on.

Regenerate with:  uv run python assets/make_favicon.py
"""

from PIL import Image, ImageDraw

SURFACE = (20, 25, 34, 255)      # #141922, the app's card surface
BLUE = (57, 135, 229, 255)       # #3987e5, categorical slot 1
ORANGE = (217, 89, 38, 255)      # #d95926, categorical slot 2

S = 512                          # draw large, downsample for clean edges
PAD = 74
STROKE = 62


def curve_points() -> list[tuple[float, float]]:
    """A par-curve silhouette: rises fast, then flattens."""
    import math
    pts = []
    x0, x1 = PAD + 10, S - PAD - 10
    y_lo, y_hi = S - PAD - 24, PAD + 40
    for i in range(401):
        t = i / 400
        # saturating curve -- steep early, flat late
        k = 1 - math.exp(-3.1 * t)
        k /= 1 - math.exp(-3.1)
        pts.append((x0 + t * (x1 - x0), y_lo - k * (y_lo - y_hi)))
    return pts


def main() -> None:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded square so the mark holds its own on a light tab bar too.
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=112, fill=SURFACE)

    # Stamp overlapping discs along a dense path rather than using d.line().
    # PIL's polyline joints leave visible notches on a stroke this thick, and
    # at 16px those notches turn into a ragged edge.
    pts = curve_points()
    r = STROKE / 2
    for (cx, cy) in pts:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BLUE)

    # One accent dot at the front end: the policy anchor the curve hangs off.
    r = STROKE * 0.62
    cx, cy = pts[0]
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ORANGE)

    for size in (16, 32, 64, 180, 512):
        img.resize((size, size), Image.LANCZOS).save(
            f"assets/favicon_{size}.png")
    img.resize((256, 256), Image.LANCZOS).save("assets/favicon.png")
    print("wrote assets/favicon.png and size variants")


if __name__ == "__main__":
    main()
