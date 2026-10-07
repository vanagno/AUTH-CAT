"""The look shared by AUTH-CAT's figures and PDF report.
Plotting scripts call :func:`use_figure_style` before they draw.
"""

from __future__ import annotations

import os
from functools import lru_cache

FONT_FAMILY = os.environ.get("AUTHCAT_FONT") or "Tw Cen MT"
FONT_SIZE = 13          # figure text, points (matplotlib's default is 10)
FIGURE_DPI = 300        # resolution of the saved figures
#: Mc with a subscript c, for figure labels (matplotlib mathtext).
MC = r"M$_\mathrm{c}$"


@lru_cache(maxsize=None)
def font_files() -> dict[str, str]:
    """Files of FONT_FAMILY, as {'regular', 'bold', 'italic', 'bolditalic':
    path}; empty when the font is not installed. A missing variant is left
    out."""
    from matplotlib import font_manager

    found = {}
    for key, weight, style in (("regular", "normal", "normal"), ("bold", "bold", "normal"),
                               ("italic", "normal", "italic"), ("bolditalic", "bold", "italic")):
        try:
            path = font_manager.findfont(
                font_manager.FontProperties(family=FONT_FAMILY, weight=weight, style=style),
                fallback_to_default=False)
        except ValueError:
            continue
        props = font_manager.FontProperties(fname=path)
        if props.get_name() != FONT_FAMILY or path in found.values():
            continue  # another font, or the same file standing in for a missing variant
        found[key] = path
    return found if "regular" in found else {}


def use_figure_style() -> None:

    import matplotlib as mpl

    rc = {
        "font.size": FONT_SIZE,
        "savefig.dpi": FIGURE_DPI,
    }
    if font_files():
        rc.update({
            "font.family": "sans-serif",
            # DejaVu Sans supplies any symbol the font lacks (e.g. ≤)
            "font.sans-serif": [FONT_FAMILY, "DejaVu Sans"],
            "mathtext.fontset": "custom",
            "mathtext.rm": FONT_FAMILY,
            "mathtext.it": f"{FONT_FAMILY}:italic",
            "mathtext.bf": f"{FONT_FAMILY}:bold",
        })
    mpl.rcParams.update(rc)
