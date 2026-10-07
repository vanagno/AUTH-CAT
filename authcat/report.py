#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Image,
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.lib.utils import ImageReader
except ImportError as exc:
    raise SystemExit(
        "report.py requires ReportLab. Install it with: pip install reportlab"
    ) from exc

from authcat.project import UTILITIES_DIR, open_project, shown
from authcat.style import font_files

# The report's fonts: the figures' font (Tw Cen MT, see style.py) when it is
# installed, Times otherwise.
FALLBACK_FONTS = {"regular": "Times-Roman", "bold": "Times-Bold", "italic": "Times-Italic",
                  "bolditalic": "Times-BoldItalic"}


def register_fonts() -> dict[str, str]:
    """Register the installed font's files with ReportLab and return their
    names, or FALLBACK_FONTS when it is not installed or cannot be read."""
    files = font_files()
    if not files:
        return dict(FALLBACK_FONTS)
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    names = {}
    try:
        for key, path in files.items():
            names[key] = f"AuthcatFont-{key}"
            pdfmetrics.registerFont(TTFont(names[key], path))
    except Exception:  # e.g. a font file ReportLab cannot read
        return dict(FALLBACK_FONTS)
    names.setdefault("bold", names["regular"])
    names.setdefault("italic", names["regular"])
    names.setdefault("bolditalic", names["bold"])
    # so that <b> and <i> in a paragraph take the font's own bold and italic
    pdfmetrics.registerFontFamily(names["regular"], normal=names["regular"], bold=names["bold"],
                                  italic=names["italic"], boldItalic=names["bolditalic"])
    return names


FONTS = register_fonts()
FONT, FONT_BOLD, FONT_ITALIC = FONTS["regular"], FONTS["bold"], FONTS["italic"]


def fallback_glyphs(text: str) -> str:
    """Draw in Times the characters the report's font lacks (e.g. ≤), so
    they do not come out as empty boxes."""
    if FONT == FALLBACK_FONTS["regular"]:
        return text
    from reportlab.pdfbase import pdfmetrics
    known = pdfmetrics.getFont(FONT).face.charToGlyph
    return "".join(f'<font name="{FALLBACK_FONTS["regular"]}">{ch}</font>'
                   if ord(ch) > 127 and ord(ch) not in known else ch for ch in text)


_MC = re.compile(r"\bMc\b")


def mc_subscript(text: str) -> str:
    """Mc with a subscript c, in paragraph markup."""
    return _MC.sub("M<sub>c</sub>", text)


def markup(value: Any) -> str:
    """Plain text made ready for a Paragraph: escaped, Mc with a subscript c,
    and any character the font lacks drawn in Times."""
    return fallback_glyphs(mc_subscript(escape(str(value))))


DEFAULT_REPORT_DIR = Path("Reports")

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = 1.8 * cm
RIGHT_MARGIN = 1.8 * cm
TOP_MARGIN = 1.8 * cm
BOTTOM_MARGIN = 1.8 * cm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN
MAX_IMAGE_HEIGHT = 17.0 * cm


# -----------------------------------------------------------------------------
# Data helpers
# -----------------------------------------------------------------------------


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Analysis summary not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("The analysis summary JSON must contain a top-level object.")

    return data


def safe_get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def last_run_details(data: dict[str, Any], script: str) -> dict[str, Any]:
    """The inputs and parameters of the latest run of ``script`` in the
    record's history, e.g. the window and filter lengths of Mc_time.py."""
    for entry in reversed(data.get("history") or []):
        if isinstance(entry, dict) and entry.get("script") == script:
            details = entry.get("details")
            return details if isinstance(details, dict) else {}
    return {}


def is_available(section: Any) -> bool:
    return isinstance(section, dict) and section.get("available", False) is True


def fmt(value: Any, decimals: int | None = None) -> str:
    if value is None:
        return "-"

    if (decimals is not None and isinstance(value, (int, float))
            and not isinstance(value, bool) and math.isfinite(value)):
        # Rounded to the nearest, halves up, as by hand: 2.675 -> 2.68
        # (the float itself, 2.67499..., would give 2.67).
        step = Decimal(1).scaleb(-decimals)
        return str(Decimal(str(value)).quantize(step, rounding=ROUND_HALF_UP))

    return str(value)


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_datetime(value: Any) -> str:
    """A date and time as YYYY/MM/DD HH:MM:SS(.fff)."""
    if not value:
        return "-"

    dt = parse_datetime(value)
    if dt is None:
        return str(value)
    if dt.microsecond:
        return dt.strftime("%Y/%m/%d %H:%M:%S.%f").rstrip("0").rstrip(".")
    return dt.strftime("%Y/%m/%d %H:%M:%S")


def fmt_date(value: Any) -> str:
    """A date as YYYY/MM/DD."""
    if not value:
        return "-"
    dt = parse_datetime(value)
    return dt.strftime("%Y/%m/%d") if dt else str(value)


def date_range(start: Any, end: Any) -> str:
    """Two dates as YYYY/MM/DD - YYYY/MM/DD."""
    if not start and not end:
        return "-"
    return f"{fmt_date(start)} - {fmt_date(end)}"


def range_text(
    minimum: Any,
    maximum: Any,
    suffix: str = "",
    decimals: int | None = None,
) -> str:
    if minimum is None and maximum is None:
        return "-"
    if minimum is None:
        return f"≤ {fmt(maximum, decimals)}{suffix}"
    if maximum is None:
        return f"≥ {fmt(minimum, decimals)}{suffix}"
    return f"{fmt(minimum, decimals)} - {fmt(maximum, decimals)}{suffix}"


def magnitude_range_text(minimum: Any, maximum: Any) -> str:
    """Format catalogue magnitude limits compactly, e.g. 0.5-3.8."""
    if minimum is None and maximum is None:
        return "-"
    if minimum is None:
        return f"≤ {fmt(maximum, 1)}"
    if maximum is None:
        return f"≥ {fmt(minimum, 1)}"
    return f"{fmt(minimum, 1)}-{fmt(maximum, 1)}"


def unit_text(value: Any, suffix: str) -> str:
    if value is None:
        return "-"
    return f"{fmt(value)}{suffix}"


def download_rows(bulletin: Any) -> list[list[Any]]:
    """Rows for the period and area requested from bulletin.py.

    None for a bulletin imported with project.py, which records neither.
    """
    if not is_available(bulletin) or not bulletin.get("start_date"):
        return []
    bounds = bulletin.get("bounds")
    if isinstance(bounds, dict):
        area = (
            f"Lat: {range_text(bounds.get('latitude_min'),  bounds.get('latitude_max'), ' °', 3)}; "
            f"Lon: {range_text(bounds.get('longitude_min'), bounds.get('longitude_max'), ' °', 3)}"
        )
    else:
        area = "No geographic limits"
    return [
        ["Download period", date_range(bulletin.get("start_date"), bulletin.get("end_date"))],
        ["Download area", area],
    ]


def resolve_project_path(project_root: Path, path_value: Any) -> Path | None:
    if not path_value:
        return None

    path = Path(str(path_value))
    if path.is_absolute():
        return path
    return project_root / path


# -----------------------------------------------------------------------------
# PDF styles and layout helpers
# -----------------------------------------------------------------------------


def build_styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()

    return {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=sample["Title"],
            fontName=FONT_BOLD,
            fontSize=25,
            leading=26,
            alignment=TA_CENTER,
            spaceAfter=10,
            textColor=colors.HexColor("#263238"),
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            parent=sample["Normal"],
            fontName=FONT,
            fontSize=14.5,
            leading=15,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#616161"),
            spaceAfter=18,
        ),
        "section": ParagraphStyle(
            "SectionHeading",
            parent=sample["Heading2"],
            fontName=FONT_BOLD,
            fontSize=15,
            leading=18,
            textColor=colors.HexColor("#2F4858"),
            spaceBefore=12,
            spaceAfter=10,
            keepWithNext=True,
        ),
        "subsection": ParagraphStyle(
            "SubsectionHeading",
            parent=sample["Heading3"],
            fontName=FONT_BOLD,
            fontSize=11.5,
            leading=14,
            textColor=colors.HexColor("#37474F"),
            spaceBefore=8,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "BodyTextCustom",
            parent=sample["BodyText"],
            fontName=FONT,
            fontSize=9.6,
            leading=14,
            textColor=colors.HexColor("#202124"),
            spaceAfter=8,
        ),
        "caption": ParagraphStyle(
            "FigureCaption",
            parent=sample["Normal"],
            fontName=FONT_ITALIC,
            fontSize=8.4,
            leading=11,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#616161"),
            spaceBefore=4,
            spaceAfter=10,
        ),
        "small": ParagraphStyle(
            "SmallText",
            parent=sample["Normal"],
            fontName=FONT,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#616161"),
        ),
    }


def make_table(rows: list[list[Any]], widths: list[float] | None = None) -> Table:
    body_style = ParagraphStyle(
        "TableBody",
        fontName=FONT,
        fontSize=8.8,
        leading=11,
        textColor=colors.HexColor("#202124"),
    )
    label_style = ParagraphStyle(
        "TableLabel",
        parent=body_style,
        fontName=FONT_BOLD,
    )

    formatted_rows = []
    for row in rows:
        formatted = []
        for col_index, cell in enumerate(row):
            if hasattr(cell, "wrap"):
                formatted.append(cell)
            else:
                style = label_style if col_index == 0 else body_style
                formatted.append(Paragraph(markup(cell), style))
        formatted_rows.append(formatted)

    table = Table(formatted_rows, colWidths=widths, hAlign="LEFT", repeatRows=0)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D0D0D0")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F5F6")),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def make_header_table(rows: list[list[Any]], widths: list[float] | None = None) -> Table:
    header_style = ParagraphStyle("TableHeader", fontName=FONT_BOLD, fontSize=8.5, leading=10.5)
    cell_style = ParagraphStyle("TableCell", fontName=FONT, fontSize=8.5, leading=10.5)
    rows = [[cell if hasattr(cell, "wrap") else Paragraph(markup(cell), header_style if i == 0 else cell_style)
             for cell in row] for i, row in enumerate(rows)]
    table = Table(rows, colWidths=widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("LEADING", (0, 0), (-1, -1), 10.5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D0D0D0")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8ECEF")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def scaled_image_to_fit(path: Path, max_width: float, max_height: float) -> Image:
    reader = ImageReader(str(path))
    width_px, height_px = reader.getSize()

    if width_px <= 0 or height_px <= 0:
        raise ValueError(f"Invalid image dimensions: {path}")

    scale = min(max_width / width_px, max_height / height_px)
    width = width_px * scale
    height = height_px * scale

    return Image(str(path), width=width, height=height)


def scaled_image(path: Path) -> Image:
    return scaled_image_to_fit(path, CONTENT_WIDTH, MAX_IMAGE_HEIGHT)


def add_image(
    story: list[Any],
    project_root: Path,
    path_value: Any,
    caption: str,
    styles: dict[str, ParagraphStyle],
) -> bool:
    path = resolve_project_path(project_root, path_value)
    if path is None or not path.exists() or not path.is_file():
        return False

    try:
        image = scaled_image(path)
    except Exception as exc:
        print(f"Warning: could not include figure {path}: {exc}")
        return False

    story.append(Spacer(1, 5))
    story.append(image)
    story.append(Paragraph(caption, styles["caption"]))
    return True


def add_section_heading(
    story: list[Any], title: str, styles: dict[str, ParagraphStyle]
) -> None:
    if story and not isinstance(story[-1], PageBreak):
        story.append(PageBreak())

    story.append(Paragraph(title, styles["section"]))


# -----------------------------------------------------------------------------
# Dynamic report sections
# -----------------------------------------------------------------------------


def add_dataset_overview(
    story: list[Any], data: dict[str, Any], styles: dict[str, ParagraphStyle]
) -> None:
    cat = data.get("catalogue", {})
    project = data.get("project", {})

    if not isinstance(cat, dict):
        return
    if not isinstance(project, dict):
        project = {}

    add_section_heading(story, "Dataset overview", styles)

    time_period = date_range(cat.get("start_time"), cat.get("end_time"))
    start, end = parse_datetime(cat.get("start_time")), parse_datetime(cat.get("end_time"))
    days = (end - start).total_seconds() / 86400 if start and end and end > start else None
    duration = rate = "-"
    if days:
        duration = f"{fmt(days, 1)} days"
        if isinstance(cat.get("total_events"), int):
            per_day = cat["total_events"] / days
            rate = f"{fmt(per_day, 2 if per_day < 10 else 1)} events/day"
    largest = cat.get("largest_event") or {}
    if largest.get("magnitude") is not None:
        largest_text = f"M {fmt(largest['magnitude'], 2)} on {fmt_datetime(largest.get('time'))}"
    else:
        largest_text = "-"

    # The introduction, with this catalogue's own numbers; a sentence whose
    # values are not recorded is left out.
    name = project.get("name")
    record = f"Projects/{escape(str(name))}/{escape(str(name))}.json" if name else "the project folder"
    intro = (
        "This section summarizes the catalogue information stored in the "
        f"AUTH-CAT project record ({record}). The project record contains "
        "the main metadata and analysis results generated during the AUTH-CAT workflow and is used to create this report."
    )
    if isinstance(cat.get("total_events"), int) and days:
        intro += (f" The analyzed catalogue contains {cat['total_events']} earthquakes spanning "
                  f"{fmt(days, 1)} days, from {fmt_date(start)} to {fmt_date(end)}.")
    limits = [cat.get(key) for key in ("magnitude_min", "magnitude_max", "depth_min_km", "depth_max_km")]
    if all(value is not None for value in limits):
        intro += (f" Event magnitudes range from {fmt(limits[0], 1)} to {fmt(limits[1], 1)}, while "
                  f"focal depths range from approximately {fmt(limits[2], 1)} to {fmt(limits[3], 1)} km.")
    story.append(Paragraph(intro, styles["body"]))

    latitude_range = range_text(
        cat.get("latitude_min"),  cat.get("latitude_max"), "°", 3
    )
    longitude_range = range_text(
        cat.get("longitude_min"), cat.get("longitude_max"), "°", 3
    )
    if latitude_range == "-" and longitude_range == "-":
        coordinates = "-"
    else:
        coordinates = f"Lat: {latitude_range}; Lon: {longitude_range}"

    overview_rows = [
        ["Project", fmt(project.get("name"))],
        ["Catalogue", fmt(project.get("catalogue_file"))],
        *download_rows(data.get("bulletin")),
        ["Number of events", fmt(cat.get("total_events"))],
    #    ["Time period", time_period],
        ["Catalogue duration", duration],
        ["Average event rate", rate],
        ["Largest event", largest_text],
#        ["Study area", coordinates],
        ["Depth range", range_text(cat.get("depth_min_km"), cat.get("depth_max_km"), " km", 1)],
        ["Magnitude range", magnitude_range_text(cat.get("magnitude_min"), cat.get("magnitude_max"))],
    ]
    story.append(make_table(overview_rows, [5.2 * cm, CONTENT_WIDTH - 5.2 * cm]))


def add_spatial_distribution(
    story: list[Any],
    data: dict[str, Any],
    project_root: Path,
    styles: dict[str, ParagraphStyle],
) -> None:
    path_value = safe_get(data, "figures", "epicentral_map")
    path = resolve_project_path(project_root, path_value)
    if path is None or not path.exists():
        return

    add_section_heading(story, "Spatial distribution", styles)
    story.append(
        Paragraph(
            "This section presents the epicentral distribution "
            "of the earthquakes included in the catalogue. Epicenters are shown according"
            " to their geographical coordinates, with symbol size and color representing "
            "their magnitude. This map provides a first-order view of the spatial extent of "
            "seismicity and possible clustering of events.",
            styles["body"],
        )
    )
    add_image(
        story,
        project_root,
        path_value,
        "Epicentral distribution of earthquakes.",
        styles,
    )


def add_catalogue_characteristics(
    story: list[Any],
    data: dict[str, Any],
    project_root: Path,
    styles: dict[str, ParagraphStyle],
) -> None:
    path_value = safe_get(data, "figures", "histograms")
    path = resolve_project_path(project_root, path_value)
    if path is None or not path.exists():
        return

    add_section_heading(story, "Catalogue characteristics", styles)
    story.append(
        Paragraph(
            "This section summarizes the main characteristics of the earthquake catalogue "
            "through the histograms of focal depth, magnitude, RMS residual and azimuthal gap. These parameters "
            "provide an initial description of the dataset and help assess the quality and "
            "consistency of the earthquake locations. Mean and median values are "
            "reported for each parameter, allowing the typical values and variability of the distributions to be assessed.",
            styles["body"],
        )
    )
    add_image(
        story,
        project_root,
        path_value,
        "Catalogue parameter histograms.",
        styles,
    )


def add_temporal_evolution(
    story: list[Any],
    data: dict[str, Any],
    project_root: Path,
    styles: dict[str, ParagraphStyle],
) -> None:
    figures = [
        (safe_get(data, "figures", "magnitude_time"), "Magnitude versus time."),
        (
            safe_get(data, "figures", "cumulative_events"),
            "Cumulative number of earthquakes over time.",
        ),
    ]

    existing = []
    for path_value, caption in figures:
        path = resolve_project_path(project_root, path_value)
        if path is not None and path.exists():
            existing.append((path_value, caption))

    if not existing:
        return

    add_section_heading(story, "Temporal evolution", styles)
    story.append(
        Paragraph(
            "This section summarizes the temporal evolution of the analyzed seismicity. The magnitude-time plot shows how earthquake "
            "magnitudes vary throughout the analyzed period, while the cumulative number - time plots highlight changes in the rate of seismic activity.",
            styles["body"],
        )
    )

    for path_value, caption in existing:
        add_image(story, project_root, path_value, caption, styles)


def add_mc(
    story: list[Any],
    data: dict[str, Any],
    project_root: Path,
    styles: dict[str, ParagraphStyle],
) -> None:
    mc = data.get("magnitude_of_completeness", {})
    if not is_available(mc):
        return

    add_section_heading(story, "Magnitude of completeness", styles)
    mc_time = last_run_details(data, "Mc_time.py")
    mc_time_text = ""
    if mc_time.get("window_length") and mc_time.get("filter_length"):
        mc_time_text = (" The temporal variation of Mc was evaluated using a moving window of "
                        f"{mc_time['window_length']} events and a smoothing filter of "
                        f"{mc_time['filter_length']} events.")
    story.append(
        Paragraph(
            mc_subscript("Magnitude of completeness (Mc) represents the lowest magnitude above which the earthquake catalogue is considered reliably complete. "
            "AUTH-CAT estimates Mc using the MAXC, GFT and MBS methods and reports the corresponding Gutenberg-Richter b-values and their uncertainties."
            + mc_time_text +
            " Further information on the implemented methods is provided in Section 3.5 of the manual."),
            styles["body"],
        )
    )

    rows = [["Method", "Mc", "b-value", "b-value uncertainty"]]
    for label, key in [("MAXC", "maxc"), ("GFT", "gft"), ("MBS", "mbs")]:
        values = mc.get(key, {})
        if not isinstance(values, dict):
            values = {}
        rows.append(
            [
                label,
                fmt(values.get("mc")),
                fmt(values.get("b_value")),
                fmt(values.get("b_value_uncertainty")),
            ]
        )

    story.append(
        make_header_table(
            rows,
            [4.6 * cm, 3.5 * cm, 4.3 * cm, 5.0 * cm],
        )
    )
    story.append(Spacer(1, 8))

    goodness = safe_get(mc, "gft", "goodness_of_fit_percent")
    if goodness is not None:
        story.append(
            Paragraph(
                f"<b>GFT goodness of fit:</b> {fmt(goodness)}%",
                styles["body"],
            )
        )

    figures = mc.get("figures", {})
    if not isinstance(figures, dict):
        figures = {}

    figure_items = [
        (safe_get(data, "figures", "mc_time"), "Magnitude of completeness through time."),
        (figures.get("fmd"), "Frequency-magnitude distribution."),
        (figures.get("maxc"), "MAXC magnitude of completeness analysis."),
        (figures.get("gft_residuals"), "Goodness-of-Fit residuals."),
        (figures.get("gft"), "Goodness-of-Fit magnitude of completeness analysis."),
        (figures.get("mbs_stability"), "b-value stability analysis."),
        (figures.get("mbs"), "MBS magnitude of completeness analysis."),
    ]

    for path_value, caption in figure_items:
        add_image(story, project_root, path_value, caption, styles)


def add_magnitude_analysis(
    story: list[Any],
    data: dict[str, Any],
    project_root: Path,
    styles: dict[str, ParagraphStyle],
) -> None:
    mag = data.get("magnitude_regularization", {})
    if not is_available(mag):
        return

    add_section_heading(story, "Magnitude analysis", styles)

    stations = mag.get("excluded_stations", [])
    if not isinstance(stations, list):
        stations = []
    stations_text = ", ".join(str(s) for s in stations) if stations else "-"

    threshold = mag.get("residual_threshold")
    flagged = mag.get("flagged_stations", [])
    if not isinstance(flagged, list):
        flagged = []
    if threshold is None:
        flagged_text = "-"
    else:
        flagged_text = ", ".join(str(s) for s in flagged) if flagged else "None"
    
    story.append(
        Paragraph(
            "Magnitude analysis evaluates the consistency of station-based magnitude estimates by comparing the median residual" 
            " of each seismic station with the corresponding event magnitudes. Stations exceeding the selected absolute residual" 
            " threshold are flagged and may be excluded from the magnitude recomputation. The effect of the exclusion is then assessed" 
            " by comparing the original and recomputed event magnitudes. ",
            styles["body"],
        )
    )
    story.append(
        make_table(
            [
                ["Residual threshold (abs median residual)", fmt(threshold)],
                ["Stations above the threshold", flagged_text],
                ["Stations excluded from magnitude recomputation", stations_text],
            ],
            [7.2 * cm, CONTENT_WIDTH - 7.2 * cm],
        )
    )
    story.append(Spacer(1, 7))

    add_image(
        story,
        project_root,
        mag.get("figure"),
        "Magnitude residual analysis by seismic station.",
        styles,
    )

    bland_altman = mag.get("bland_altman", {})
    if isinstance(bland_altman, dict) and bland_altman.get("figure"):
        story.append(Paragraph("Original versus recomputed magnitudes", styles["subsection"]))
        story.append(
            make_table(
                [
                    ["Events compared", fmt(bland_altman.get("events"))],
                    ["Mean difference (recomputed - original)", fmt(bland_altman.get("mean_difference"))],
                    [
                        "95% limits of agreement",
                        f"{fmt(bland_altman.get('lower_limit'))} to {fmt(bland_altman.get('upper_limit'))}",
                    ],
                ],
                [7.2 * cm, CONTENT_WIDTH - 7.2 * cm],
            )
        )
        add_image(
            story,
            project_root,
            bland_altman.get("figure"),
            "Bland-Altman plot of original and recomputed event magnitudes.",
            styles,
        )


def add_station_phases(
    story: list[Any],
    data: dict[str, Any],
    project_root: Path,
    styles: dict[str, ParagraphStyle],
) -> None:
    phases = data.get("station_phases", {})
    if not is_available(phases):
        return

    add_section_heading(story, "Seismic network and phases", styles)

    station_count = phases.get("station_count")
    missing_count = phases.get("missing_coordinate_station_count")
    counts_file = phases.get("counts_file")

    statements = []
    if station_count is not None:
        statements.append(
            f"The seismic network analysis includes <b>{escape(str(station_count))}</b> "
            f"seismic stations."
        )
    if missing_count is not None:
        station_word = "station" if missing_count == 1 else "stations"
        statements.append(
            f"Coordinates were unavailable for <b>{escape(str(missing_count))}</b> "
            f"{station_word}."
        )
    if counts_file:
        statements.append(
            "The P- and S-phase counts for each station are stored in "
            f"<b>{escape(str(counts_file))}</b>."
        )

    if statements:
        story.append(Paragraph(" ".join(statements), styles["body"]))
        story.append(Spacer(1, 7))

    add_image(
        story,
        project_root,
        phases.get("map_figure"),
        "Seismic stations contributing phase picks.",
        styles,
    )


def add_phase_files(
    story: list[Any], data: dict[str, Any], styles: dict[str, ParagraphStyle]
) -> None:
    phases = data.get("phases", {})
    if not is_available(phases):
        return

    add_section_heading(story, "Phase files", styles)

    rows = [["Format", "File", "Events", "Phases"]]
    for label, key in [("HypoDD", "hypodd"), ("HYPO71", "hypo71")]:
        values = phases.get(key, {})
        if isinstance(values, dict) and values.get("file"):
            rows.append(
                [
                    label,
                    fmt(values.get("file")),
                    fmt(values.get("events")),
                    fmt(values.get("phases")),
                ]
            )
    if len(rows) > 1:
        story.append(
            make_header_table(rows, [3.4 * cm, 8.0 * cm, 3.0 * cm, 3.0 * cm])
        )
        story.append(Spacer(1, 8))

    selection = phases.get("selection", {})
    if isinstance(selection, dict) and selection.get("file"):
        stations = selection.get("stations", [])
        if not isinstance(stations, list):
            stations = []
        story.append(Paragraph("Station selection", styles["subsection"]))
        story.append(
            make_table(
                [
                    ["Stations kept", ", ".join(str(s) for s in stations) if stations else "-"],
                    ["File", fmt(selection.get("file"))],
                    ["Events", fmt(selection.get("events"))],
                ],
                [5.0 * cm, CONTENT_WIDTH - 5.0 * cm],
            )
        )


def add_wadati(
    story: list[Any],
    data: dict[str, Any],
    project_root: Path,
    styles: dict[str, ParagraphStyle],
) -> None:
    wadati = data.get("wadati", {})
    if not is_available(wadati):
        return

    add_section_heading(story, "Vp/Vs estimation", styles)

    vpvs = wadati.get("vp_vs", {})
    if not isinstance(vpvs, dict):
        vpvs = {}
    story.append(
        Paragraph(
            "The Vp/Vs ratio is estimated from P- and S-wave travel times using the Wadati method. " 
            "AUTH-CAT applies both least-squares fitting and orthogonal regression, allowing the resulting estimates to be compared." ,
            styles["body"],
        )
    )
    rows = [
        ["Vp/Vs - least squares", fmt(vpvs.get("least_squares"))],
        ["Vp/Vs - orthogonal regression", fmt(vpvs.get("orthogonal_regression"))],
    ]
    story.append(make_table(rows, [7.0 * cm, CONTENT_WIDTH - 7.0 * cm]))
    story.append(Spacer(1, 7))

    add_image(
        story,
        project_root,
        wadati.get("figure"),
        "Wadati diagram and Vp/Vs estimation.",
        styles,
    )


#: How omori_utsu.py chose each end of the sequence.
OMORI_BOUND_LABELS = {
    "catalogue_start": "start of catalogue",
    "largest_event": "largest earthquake",
    "specific_datetime": "chosen time",
    "catalogue_end": "end of catalogue",
}


def sequence_bound(time_value: Any, mode: Any) -> str:
    """A sequence start or end, e.g. '2021/03/03 10:16:08.367 (largest earthquake)'."""
    text = fmt_datetime(time_value)
    if mode in OMORI_BOUND_LABELS:
        return f"{text} ({OMORI_BOUND_LABELS[mode]})" if text != "-" else OMORI_BOUND_LABELS[mode]
    return text if text != "-" else fmt(mode)


def add_omori(
    story: list[Any],
    data: dict[str, Any],
    project_root: Path,
    styles: dict[str, ParagraphStyle],
) -> None:
    omori = data.get("modified_omori", {})
    if not is_available(omori):
        return

    add_section_heading(story, "Omori-Utsu Law", styles)

    threshold = omori.get("magnitude_threshold")
    rows = [
        ["Sequence start", sequence_bound(omori.get("start_time"), omori.get("fit_start"))],
        ["Sequence end", sequence_bound(omori.get("end_time"), omori.get("fit_end"))],
        ["Magnitude threshold (Mc)", f" {fmt(threshold)}" if threshold is not None else "All events"],
        ["Events used", fmt(omori.get("events"))],
    ]
    story.append(make_table(rows, [5.0 * cm, CONTENT_WIDTH - 5.0 * cm]))
    story.append(Spacer(1, 8))

    params = [["Parameter", "Bayesian fit", "MCMC median", "16th-84th percentile"]]
    for name in ("K", "c", "p"):
        decimals = 2 if name in ("c", "p") else None
        median = safe_get(omori, "mcmc", name, "median")
        p16 = safe_get(omori, "mcmc", name, "p16")
        p84 = safe_get(omori, "mcmc", name, "p84")
        spread = (f"{fmt(p16, decimals)} to {fmt(p84, decimals)}"
                  if p16 is not None and p84 is not None else "-")
        params.append([name, fmt(omori.get(name), decimals), fmt(median, decimals), spread])
    story.append(make_header_table(params, [3.4 * cm, 4.3 * cm, 4.3 * cm, 5.4 * cm]))
    story.append(Spacer(1, 7))

    add_image(
        story,
        project_root,
        omori.get("figure"),
        "Omori-Utsu law fit.",
        styles,
    )
    add_image(
        story,
        project_root,
        omori.get("mcmc_figure"),
        "MCMC posterior distributions of the Omori-Utsu parameters "
        "(16th, 50th and 84th percentiles marked).",
        styles,
    )


def add_summary(
    story: list[Any], data: dict[str, Any], styles: dict[str, ParagraphStyle]
) -> None:
    completed = []

    mapping = [
        ("Magnitude of completeness", "magnitude_of_completeness"),
        ("Magnitude analysis", "magnitude_regularization"),
        ("Seismic network and phases", "station_phases"),
        ("Phase files", "phases"),
        ("Vp/Vs estimation", "wadati"),
        ("Omori-Utsu Law", "modified_omori"),
    ]

    for label, key in mapping:
        if is_available(data.get(key, {})):
            completed.append(label)

    if completed:
        add_section_heading(story, "Summary", styles)
        story.append(
            Paragraph(
                "The following optional analysis results were marked as available "
                "in the analysis summary:",
                styles["body"],
            )
        )
        bullet_text = "<br/>".join(f"- {item}" for item in completed)
        story.append(Paragraph(bullet_text, styles["body"]))


# -----------------------------------------------------------------------------
# PDF construction
# -----------------------------------------------------------------------------




def draw_cover_page(canvas, doc) -> None:
    """Keep the title page clean: no footer and no page number."""
    return None

def draw_page_decor(canvas, doc, project_name: str) -> None:
    canvas.saveState()

    canvas.setStrokeColor(colors.HexColor("#D4D8DA"))
    canvas.setLineWidth(0.4)
    canvas.line(LEFT_MARGIN, 1.25 * cm, PAGE_WIDTH - RIGHT_MARGIN, 1.25 * cm)

    canvas.setFont(FONT, 7.5)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(LEFT_MARGIN, 0.85 * cm, f"AUTH-CAT - {project_name}")
    canvas.drawRightString(
        PAGE_WIDTH - RIGHT_MARGIN,
        0.85 * cm,
        f"Page {doc.page}",
    )

    canvas.restoreState()


def build_pdf(data: dict[str, Any], project_root: Path, output_path: Path) -> None:
    styles = build_styles()
    project_name = safe_get(data, "project", "name", default="AUTH-CAT") or "AUTH-CAT"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title=f"AUTH-CAT Analysis Report - {project_name}",
        author="AUTH-CAT",
        subject="Earthquake bulletin and catalogue analysis report",
    )

    story: list[Any] = []

    # Dedicated cover page.
    # LOGO.png is expected in the Utilities folder next to report.py.
    story.append(Spacer(1, 2.0 * cm))
    story.append(Paragraph("Analysis Report", styles["title"]))
    story.append(Spacer(1, 1.0 * cm))

    logo_path = UTILITIES_DIR / "LOGO.png"
    if logo_path.exists() and logo_path.is_file():
        try:
            logo = scaled_image_to_fit(logo_path, 13.0 * cm, 8.5 * cm)
            logo.hAlign = "CENTER"
            story.append(logo)
            story.append(Spacer(1, 1.0 * cm))
        except Exception as exc:
            print(f"Warning: could not include logo {logo_path}: {exc}")
    else:
        print(f"Warning: logo not found: {logo_path}")

    
    story.append(
        Paragraph(
            f"Project: {project_name}<br/>"
            f"Generated: {datetime.now().strftime('%Y/%m/%d %H:%M')}",
            styles["subtitle"],
        )
    )

    # All report sections start on a new page.
    story.append(PageBreak())

    add_dataset_overview(story, data, styles)
    add_spatial_distribution(story, data, project_root, styles)
    add_catalogue_characteristics(story, data, project_root, styles)
    add_temporal_evolution(story, data, project_root, styles)
    add_mc(story, data, project_root, styles)
    add_magnitude_analysis(story, data, project_root, styles)
    add_station_phases(story, data, project_root, styles)
    add_phase_files(story, data, styles)
    add_wadati(story, data, project_root, styles)
    add_omori(story, data, project_root, styles)
    add_summary(story, data, styles)

    doc.build(
        story,
        onFirstPage=draw_cover_page,
        onLaterPages=lambda c, d: draw_page_decor(c, d, str(project_name)),
    )


# -----------------------------------------------------------------------------
# Command-line interface
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an AUTH-CAT PDF report from a project record."
    )
    parser.add_argument(
        "json_file",
        nargs="?",
        default=None,
        help="Path to the project record, Projects/<name>/<name>.json "
        "(default: the record of the project given with -p, or asks)",
    )
    parser.add_argument(
        "-p",
        "--project",
        help="Project to report on (default: asks, Enter = last used)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_REPORT_DIR),
        help=f"Report output directory (default: {DEFAULT_REPORT_DIR})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.json_file:
        json_path = Path(args.json_file).resolve()
    else:
        json_path = open_project(args.project).json_path.resolve()
    data = load_json(json_path)

    # The project record sits at the top of its project folder,
    # Projects/<name>/<name>.json, and the paths inside it are relative to
    # that folder. Older records were kept inside Results/.
    if json_path.parent.name.lower() == "results":
        project_root = json_path.parent.parent
    else:
        project_root = json_path.parent

    project_name = safe_get(data, "project", "name", default="AUTH-CAT") or "AUTH-CAT"
    safe_name = "".join(
        c if c.isalnum() or c in ("-", "_") else "_"
        for c in str(project_name)
    )

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = project_root / output_dir

    output_path = output_dir / f"{safe_name}_report.pdf"
    build_pdf(data, project_root, output_path)

    print(f"AUTH-CAT PDF report written to: {shown(output_path)}")


if __name__ == "__main__":
    main()
