"""The look shared by AUTH-CAT's figures and PDF report.

* Font: Tw Cen MT, when it is installed (it comes with Microsoft Office; its
  licence does not allow shipping it with AUTH-CAT). Without it, the figures
  keep matplotlib's DejaVu Sans and the report Times. The AUTHCAT_FONT
  environment variable names another installed font to use instead.
* Figures: larger text (FONT_SIZE) and FIGURE_DPI when saved.
* MC: Mc with a subscript c, for figure text.

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
    """Set matplotlib up for AUTH-CAT's figures: the font, larger text, and
    FIGURE_DPI when saving."""
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
