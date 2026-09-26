#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from datetime import datetime
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

from project import UTILITIES_DIR, open_project, shown


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


def is_available(section: Any) -> bool:
    return isinstance(section, dict) and section.get("available", False) is True


def fmt(value: Any, decimals: int | None = None) -> str:
    if value is None:
        return "-"

    if isinstance(value, float) and decimals is not None:
        return f"{value:.{decimals}f}"

    return str(value)


def fmt_datetime(value: Any) -> str:
    if not value:
        return "-"

    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.microsecond:
            return dt.strftime("%Y-%m-%d %H:%M:%S.%f").rstrip("0").rstrip(".")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text


def range_text(
    minimum: Any,
    maximum: Any,
    suffix: str = "",
    decimals: int | None = None,
) -> str:
    if minimum is None and maximum is None:
        return "-"
    if minimum is None:
        return f"<= {fmt(maximum, decimals)}{suffix}"
    if maximum is None:
        return f">= {fmt(minimum, decimals)}{suffix}"
    return f"{fmt(minimum, decimals)} - {fmt(maximum, decimals)}{suffix}"


def magnitude_range_text(minimum: Any, maximum: Any) -> str:
    """Format catalogue magnitude limits compactly, e.g. 0.5-3.8."""
    if minimum is None and maximum is None:
        return "-"
    if minimum is None:
        return f"<= {fmt(maximum, 1)}"
    if maximum is None:
        return f">= {fmt(minimum, 1)}"
    return f"{fmt(minimum, 1)}-{fmt(maximum, 1)}"


def unit_text(value: Any, suffix: str) -> str:
    if value is None:
        return "-"
    return f"{fmt(value)}{suffix}"


def download_rows(bulletin: Any) -> list[list[Any]]:
    """Rows for the period and area requested from getbul.py.

    None for a bulletin imported with project.py, which records neither.
    """
    if not is_available(bulletin) or not bulletin.get("start_date"):
        return []
    bounds = bulletin.get("bounds")
    if isinstance(bounds, dict):
        area = (
            f"Lat: {range_text(bounds.get('latitude_min'), bounds.get('latitude_max'), ' deg')}; "
            f"Lon: {range_text(bounds.get('longitude_min'), bounds.get('longitude_max'), ' deg')}"
        )
    else:
        area = "No geographic limits"
    return [
        ["Download period", range_text(bulletin.get("start_date"), bulletin.get("end_date"))],
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
            fontName="Times-Bold",
            fontSize=22,
            leading=26,
            alignment=TA_CENTER,
            spaceAfter=10,
            textColor=colors.HexColor("#263238"),
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            parent=sample["Normal"],
            fontName="Times-Roman",
            fontSize=10.5,
            leading=15,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#616161"),
            spaceAfter=18,
        ),
        "section": ParagraphStyle(
            "SectionHeading",
            parent=sample["Heading2"],
            fontName="Times-Bold",
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
            fontName="Times-Bold",
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
            fontName="Times-Roman",
            fontSize=9.6,
            leading=14,
            textColor=colors.HexColor("#202124"),
            spaceAfter=8,
        ),
        "caption": ParagraphStyle(
            "FigureCaption",
            parent=sample["Normal"],
            fontName="Times-Italic",
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
            fontName="Times-Roman",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#616161"),
        ),
    }


def make_table(rows: list[list[Any]], widths: list[float] | None = None) -> Table:
    body_style = ParagraphStyle(
        "TableBody",
        fontName="Times-Roman",
        fontSize=8.8,
        leading=11,
        textColor=colors.HexColor("#202124"),
    )
    label_style = ParagraphStyle(
        "TableLabel",
        parent=body_style,
        fontName="Times-Bold",
    )

    formatted_rows = []
    for row in rows:
        formatted = []
        for col_index, cell in enumerate(row):
            if hasattr(cell, "wrap"):
                formatted.append(cell)
            else:
                style = label_style if col_index == 0 else body_style
                formatted.append(Paragraph(escape(str(cell)), style))
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
    table = Table(rows, colWidths=widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Times-Roman"),
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
    story.append(
        Paragraph(
            "This section summarizes the catalogue information stored in the "
            "AUTH-CAT analysis summary. Missing values are shown as '-'.",
            styles["body"],
        )
    )

    start_time = fmt_datetime(cat.get("start_time"))
    end_time = fmt_datetime(cat.get("end_time"))
    if start_time == "-" and end_time == "-":
        time_period = "-"
    else:
        time_period = f"{start_time} - {end_time}"

    latitude_range = range_text(
        cat.get("latitude_min"), cat.get("latitude_max"), " deg"
    )
    longitude_range = range_text(
        cat.get("longitude_min"), cat.get("longitude_max"), " deg"
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
        ["Time period", time_period],
        ["Study area", coordinates],
        ["Depth range", range_text(cat.get("depth_min_km"), cat.get("depth_max_km"), " km")],
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
            "The epicentral map shows the spatial distribution of the events "
            "included in the catalogue.",
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
            "The catalogue histograms summarize parameters such as magnitude, "
            "focal depth, RMS and azimuthal gap, depending on the generated figure.",
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
            "These figures summarize the temporal development of the earthquake "
            "sequence using the outputs generated by AUTH-CAT.",
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
    story.append(
        Paragraph(
            "Magnitude of completeness (Mc) and Gutenberg-Richter b-values are "
            "reported for the methods stored in the analysis summary.",
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


def add_omori(
    story: list[Any],
    data: dict[str, Any],
    project_root: Path,
    styles: dict[str, ParagraphStyle],
) -> None:
    omori = data.get("modified_omori", {})
    if not is_available(omori):
        return

    add_section_heading(story, "Modified Omori Law", styles)

    rows = [
        ["Fit start", fmt(omori.get("fit_start"))],
        ["Fit end", fmt(omori.get("fit_end"))],
        ["K", fmt(omori.get("K"))],
        ["c", fmt(omori.get("c"))],
        ["p", fmt(omori.get("p"))],
    ]
    story.append(make_table(rows, [5.0 * cm, CONTENT_WIDTH - 5.0 * cm]))
    story.append(Spacer(1, 7))

    add_image(
        story,
        project_root,
        omori.get("figure"),
        "Modified Omori Law fit.",
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
        ("Modified Omori Law", "modified_omori"),
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

    canvas.setFont("Times-Roman", 7.5)
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

    logo_path = UTILITIES_DIR / "LOGO.png"
    if logo_path.exists() and logo_path.is_file():
        try:
            logo = scaled_image_to_fit(logo_path, 9.0 * cm, 6.5 * cm)
            logo.hAlign = "CENTER"
            story.append(logo)
            story.append(Spacer(1, 1.0 * cm))
        except Exception as exc:
            print(f"Warning: could not include logo {logo_path}: {exc}")
    else:
        print(f"Warning: logo not found: {logo_path}")

    story.append(Paragraph("AUTH-CAT Analysis Report", styles["title"]))
    story.append(
        Paragraph(
            f"Project: {project_name}<br/>"
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
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
