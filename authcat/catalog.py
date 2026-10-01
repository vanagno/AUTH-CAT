#!/usr/bin/env python3
"""Bulletin to catalogue conversion.


The bulletin is read once into ``Event`` objects and three formats (full catalogue, 6-column and quakeml) are
written from that, so the outputs cannot disagree with each other -- the old
pair could, because ``transform.py`` re-parsed ``bul.py``'s text output and
rounded a second time.

QuakeML 1.2 (``write_quakeml``) carries the whole bulletin information, like
origins with their uncertainties, both network magnitudes, every phase pick 
with its residual and weight, and every station magnitude with its amplitude.


The outputs go in the project's Results folder, and the catalogue's extent
and largest event are recorded in the project record (see ``project.py``).

Usage
-----
    authcat cat                                        # interactive, as before
    authcat cat -p Arkal -f all                        # the project's own bulletin
    authcat cat -p Arkal -i other.bul -f quakeml --no-picks
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

from authcat.project import Project, ask_file_name, open_project, shown

#: Kilometres per degree of latitude on a sphere of radius 6371 km. The
#: bulletin gives horizontal uncertainties in km; QuakeML wants the
#: uncertainty on a coordinate in the coordinate's own unit, i.e. degrees.
KM_PER_DEG = 2 * math.pi * 6371.0 / 360.0

QUAKEML_NS = "http://quakeml.org/xmlns/quakeml/1.2"
BED_NS = "http://quakeml.org/xmlns/bed/1.2"

CLASSIC_HEADER = (
    "   Date        Time       Lat     Lon   Depth  M   RMS  AzGap  Nsta Msta    ID"
)


# --------------------------------------------------------------------------
# data model
# --------------------------------------------------------------------------


@dataclass
class Pick:
    """One row of a ``Phase arrivals`` table."""

    station: str
    network: str
    distance: float  # degrees
    azimuth: float  # degrees
    phase: str
    time: datetime
    residual: float | None  # "N/A" in the bulletin for some excluded picks
    mode: str  # "manual" or "automatic", from the M/A flag
    rejected: bool  # the X suffix on that flag
    weight: float


@dataclass
class StationMagnitude:
    """One row of a ``Station magnitudes`` table."""

    station: str
    network: str
    distance: float
    azimuth: float
    type: str
    value: float
    residual: float
    amplitude: float | None = None
    period: float | None = None


@dataclass
class NetworkMagnitude:
    """One row of a ``Network magnitudes`` table."""

    type: str
    value: float
    uncertainty: float | None = None
    station_count: int | None = None
    preferred: bool = False
    agency: str = ""


@dataclass
class Event:
    """One event block of the bulletin.

    ``date`` and ``time`` are kept as the bulletin's own strings because the
    11-column catalogue passes them through verbatim; ``origin_time`` is the
    same instant parsed, and is what the 6-column and QuakeML writers use.
    """

    pubid: str
    date: str
    time: str
    origin_time: datetime
    lat: float
    lon: float
    depth: float  # km
    lat_err: float | None = None  # km
    lon_err: float | None = None  # km
    depth_err: float | None = None  # km
    rms: float | None = None
    azgap: float | None = None
    n_phase: int = 0  # the N in "N Phase arrivals:"
    n_stamag: int = 0  # the N in "N Station magnitudes:"
    origin_id: str = ""
    magnitude_id: str = ""
    region: str = ""
    event_type: str = ""
    agency: str = ""
    author: str = ""
    mode: str = ""
    status: str = ""
    creation_time: str = ""
    origin_creation_time: str = ""
    magnitudes: list[NetworkMagnitude] = field(default_factory=list)
    picks: list[Pick] = field(default_factory=list)
    station_magnitudes: list[StationMagnitude] = field(default_factory=list)

    def magnitude(self, prefer: str = "MLh") -> NetworkMagnitude | None:
        """The magnitude the text catalogues report.

        ``bul.py`` took the ``MLh`` line specifically, so that is the default
        and keeps the output byte-identical. Where there is no MLh it falls
        back to whichever magnitude the bulletin marks preferred, then to the
        first one -- ``bul.py`` raised ``KeyError`` in that case.
        """
        for m in self.magnitudes:
            if m.type == prefer:
                return m
        for m in self.magnitudes:
            if m.preferred:
                return m
        return self.magnitudes[0] if self.magnitudes else None


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------


@dataclass
class ReadReport:
    events_read: int = 0
    picks_read: int = 0
    station_magnitudes_read: int = 0
    magnitudes_read: int = 0
    blocks_incomplete: list[str] = field(default_factory=list)
    picks_unparsed: int = 0
    phase_count_mismatch: list[str] = field(default_factory=list)
    events_multiple_origins: int = 0

    def summary(self) -> str:
        parts = [
            f"{self.events_read} events, {self.magnitudes_read} magnitudes, "
            f"{self.picks_read} phase arrivals, "
            f"{self.station_magnitudes_read} station magnitudes"
        ]
        if self.blocks_incomplete:
            shown = ", ".join(self.blocks_incomplete[:5])
            more = "" if len(self.blocks_incomplete) <= 5 else ", ..."
            parts.append(
                f"{len(self.blocks_incomplete)} events dropped for missing "
                f"origin fields ({shown}{more})"
            )
        if self.events_multiple_origins:
            parts.append(
                f"{self.events_multiple_origins} events with more than one origin, "
                f"read the preferred one"
            )
        if self.picks_unparsed:
            parts.append(f"{self.picks_unparsed} phase rows not understood")
        if self.phase_count_mismatch:
            parts.append(
                f"{len(self.phase_count_mismatch)} events where the "
                f"'N Phase arrivals' count disagrees with the rows listed"
            )
        return "; ".join(parts)


@dataclass
class WriteReport:
    path: str = ""
    events_written: int = 0
    events_skipped_no_magnitude: int = 0
    events_skipped_no_quality: int = 0
    picks_written: int = 0
    station_magnitudes_written: int = 0
    centiseconds_carried: int = 0
    centisecond_ties: int = 0

    def summary(self) -> str:
        parts = [f"{self.events_written} events"]
        if self.picks_written:
            parts.append(f"{self.picks_written} picks")
        if self.station_magnitudes_written:
            parts.append(f"{self.station_magnitudes_written} station magnitudes")
        if self.events_skipped_no_magnitude:
            parts.append(
                f"{self.events_skipped_no_magnitude} events skipped with no magnitude"
            )
        if self.events_skipped_no_quality:
            parts.append(
                f"{self.events_skipped_no_quality} events skipped with no RMS "
                f"or azimuthal gap"
            )
        if self.centiseconds_carried:
            parts.append(
                f"{self.centiseconds_carried} origin times carried into the next "
                f"second when rounded to 1/100 s"
            )
        if self.centisecond_ties:
            parts.append(
                f"{self.centisecond_ties} origin times exactly halfway between "
                f"centiseconds, rounded up"
            )
        return f"{shown(self.path)}: " + ", ".join(parts)


# --------------------------------------------------------------------------
# reading the bulletin
# --------------------------------------------------------------------------

_LABEL_RX = re.compile(
    r"^\s+(Public ID|Preferred Origin ID|Preferred Magnitude ID|Date|Time|"
    r"Agency|Author|Mode|Status|Type|Creation time)\s{2,}(.+?)\s*$"
)
_COORD_RX = re.compile(
    r"^\s+(Latitude|Longitude)\s+(-?\d+(?:\.\d+)?)\s*deg"
    r"(?:\s+\+/-\s+(\d+(?:\.\d+)?)\s*km)?"
)
_DEPTH_RX = re.compile(
    r"^\s+Depth\s+(-?\d+(?:\.\d+)?)\s*km(?:\s+\+/-\s+(\d+(?:\.\d+)?)\s*km)?"
)
_RMS_RX = re.compile(r"^\s+Residual RMS\s+(-?\d+(?:\.\d+)?)\s*s")
_AZGAP_RX = re.compile(r"^\s+Azimuthal gap\s+(-?\d+(?:\.\d+)?)\s*deg")
_REGION_RX = re.compile(r"^\s+region name:\s*(.+?)\s*$")
_SECTION_RX = re.compile(
    r"^\s*(\d+) (Network magnitudes|Phase arrivals|Station magnitudes):"
)
_COLHDR_RX = re.compile(r"^\s+sta\s+net\s")
_CLOCK_RX = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)$")


def _combine(date: str, clock: str) -> datetime:
    """``2021-03-03`` + ``08:00:37.674`` -> a datetime.

    Origins carry their own date, so they are combined directly. Only pick
    times, which carry no date, go through ``_resolve_clock``.
    """
    m = _CLOCK_RX.match(clock)
    if not m:
        raise ValueError(f"unrecognised clock time {clock!r}")
    h, mi, s = m.groups()
    return datetime.fromisoformat(date) + timedelta(
        hours=int(h), minutes=int(mi), seconds=float(s)
    )


def _resolve_clock(clock: str, origin: datetime) -> datetime:
    """Attach a date to a bulletin arrival time, which carries none.

    An arrival a few seconds after a 23:59 origin belongs to the next day.
    The candidate day is the one that puts the arrival closest to the origin,
    which is right for every interval shorter than twelve hours.
    """
    m = _CLOCK_RX.match(clock)
    if not m:
        raise ValueError(f"unrecognised clock time {clock!r}")
    h, mi, s = m.groups()
    midnight = origin.replace(hour=0, minute=0, second=0, microsecond=0)
    base = midnight + timedelta(hours=int(h), minutes=int(mi), seconds=float(s))
    return min(
        (base + timedelta(days=d) for d in (-1, 0, 1)),
        key=lambda c: abs((c - origin).total_seconds()),
    )


def _parse_netmag(line: str) -> NetworkMagnitude | None:
    """``MLh  1.72 +/- 0.31   5 preferred  AUTH`` or ``M  1.72  5  AUTH``."""
    t = line.split()
    if len(t) < 2:
        return None
    try:
        value = float(t[1])
    except ValueError:
        return None
    i, unc = 2, None
    if len(t) > i + 1 and t[i] == "+/-":
        try:
            unc = float(t[i + 1])
        except ValueError:
            unc = None
        i += 2
    count = None
    if len(t) > i and t[i].isdigit():
        count = int(t[i])
        i += 1
    agency = ""
    for tok in reversed(t[i:]):
        if tok != "preferred":
            agency = tok
            break
    return NetworkMagnitude(
        type=t[0],
        value=value,
        uncertainty=unc,
        station_count=count,
        preferred="preferred" in t,
        agency=agency,
    )


def _parse_pick(line: str, origin: datetime) -> Pick | None:
    """``TYRN  HT  0.03889  97.2  P  08:00:39.145  -0.029 M  1.2  TYRN``.

    The unnamed column between the residual and the weight is the pick's
    evaluation mode -- ``M`` manual or ``A`` automatic -- with ``X`` appended
    when the pick was not used in the solution. It is not always present, and
    the trailing repeat of the station code is not always present either, so
    the two optional fields are told apart by shape rather than by position:
    the flag is alphabetic, the weight is not.

    The residual is ``N/A`` on picks the locator never used, so it is
    optional; everything else on the row is required.
    """
    t = line.split()
    if len(t) < 8:
        return None
    try:
        dist, azi = float(t[2]), float(t[3])
        res = None if t[6] == "N/A" else float(t[6])
        if re.fullmatch(r"[A-Za-z]+", t[7]):
            flag, weight = t[7], float(t[8])
        else:
            flag, weight = "", float(t[7])
        time = _resolve_clock(t[5], origin)
    except (ValueError, IndexError):
        return None
    return Pick(
        station=t[0],
        network=t[1],
        distance=dist,
        azimuth=azi,
        phase=t[4],
        time=time,
        residual=res,
        mode="automatic" if flag.startswith("A") else "manual",
        rejected="X" in flag,
        weight=weight,
    )


def _parse_stamag(line: str) -> StationMagnitude | None:
    """``TYRN  HT  0.03889  97.2  MLh  1.51 -0.20  0.945977``."""
    t = line.split()
    if len(t) < 7:
        return None
    try:
        return StationMagnitude(
            station=t[0],
            network=t[1],
            distance=float(t[2]),
            azimuth=float(t[3]),
            type=t[4],
            value=float(t[5]),
            residual=float(t[6]),
            amplitude=float(t[7]) if len(t) > 7 else None,
            period=float(t[8]) if len(t) > 8 else None,
        )
    except ValueError:
        return None


def read_bulletin(path: str | os.PathLike) -> tuple[list[Event], ReadReport]:
    """Read a bulletin into ``Event`` objects.

    Parsing is driven by which section of the block the line falls in, rather
    than by testing every line against every label. That matters because
    ``Public ID`` and ``Creation time`` each appear twice per event -- once
    for the event, once for the origin -- and ``bul.py``'s flat chain of
    ``elif`` tests had to carry a one-shot flag to tell the two ``Public ID``
    lines apart.
    """
    rep = ReadReport()
    events: list[Event] = []
    text = Path(path).read_text(errors="replace")

    # An event block runs from one "Event:" line to the next.
    blocks: list[list[str]] = []
    for line in text.splitlines():
        if line.startswith("Event:"):
            blocks.append([])
        if blocks:
            blocks[-1].append(line)

    for blk in blocks:
        # Every event in the Tyrnavos bulletin has exactly one Origin block,
        # and it is always the one named by Preferred Origin ID. Should a
        # bulletin ever carry a second -- an original solution kept beside a
        # relocated one -- read the preferred one rather than letting the
        # later block overwrite the earlier. Single-origin blocks pass
        # through this untouched.
        starts = [i for i, l in enumerate(blk) if l.startswith("Origin:")]
        if len(starts) > 1:
            rep.events_multiple_origins += 1
            pref = next(
                (
                    m.group(2)
                    for l in blk[: starts[0]]
                    if (m := _LABEL_RX.match(l)) and m.group(1) == "Preferred Origin ID"
                ),
                None,
            )
            bounds = list(zip(starts, starts[1:] + [len(blk)]))
            chosen = bounds[0]
            for lo, hi in bounds:
                own = next(
                    (
                        m.group(2)
                        for l in blk[lo:hi]
                        if (m := _LABEL_RX.match(l)) and m.group(1) == "Public ID"
                    ),
                    None,
                )
                if pref and own == pref:
                    chosen = (lo, hi)
                    break
            blk = blk[: starts[0]] + blk[chosen[0] : chosen[1]]

        section = "event"
        cur: dict[str, str] = {}
        coords: dict[str, tuple[float, float | None]] = {}
        depth: tuple[float, float | None] | None = None
        rms = azgap = None
        region = ""
        origin_creation = ""
        counts = {"Phase arrivals": 0, "Station magnitudes": 0}
        mags: list[NetworkMagnitude] = []
        pick_rows: list[str] = []
        stamag_rows: list[str] = []

        for line in blk:
            if line.startswith("Event:"):
                section = "event"
                continue
            if line.startswith("Origin:"):
                section = "origin"
                continue
            m = _SECTION_RX.match(line)
            if m:
                section = m.group(2)
                counts[section] = int(m.group(1))
                continue
            if _COLHDR_RX.match(line) or not line.strip():
                continue

            if section == "Network magnitudes":
                nm = _parse_netmag(line)
                if nm:
                    mags.append(nm)
                continue
            if section == "Phase arrivals":
                pick_rows.append(line)
                continue
            if section == "Station magnitudes":
                stamag_rows.append(line)
                continue

            m = _REGION_RX.match(line)
            if m:
                region = m.group(1)
                continue
            m = _COORD_RX.match(line)
            if m:
                coords[m.group(1)] = (
                    float(m.group(2)),
                    float(m.group(3)) if m.group(3) else None,
                )
                continue
            m = _DEPTH_RX.match(line)
            if m:
                depth = (float(m.group(1)), float(m.group(2)) if m.group(2) else None)
                continue
            m = _RMS_RX.match(line)
            if m:
                rms = float(m.group(1))
                continue
            m = _AZGAP_RX.match(line)
            if m:
                azgap = float(m.group(1))
                continue
            m = _LABEL_RX.match(line)
            if m:
                key, value = m.group(1), m.group(2)
                if key == "Creation time" and section == "origin":
                    origin_creation = value
                elif key == "Public ID" and section == "origin":
                    pass  # the origin's own id; taken from Preferred Origin ID
                else:
                    cur.setdefault(f"{section}:{key}", value)

        pubid = cur.get("event:Public ID", "")
        date = cur.get("origin:Date", "")
        clock = cur.get("origin:Time", "")
        missing = [
            n
            for n, v in (
                ("Public ID", pubid),
                ("Date", date),
                ("Time", clock),
                ("Latitude", coords.get("Latitude")),
                ("Longitude", coords.get("Longitude")),
                ("Depth", depth),
            )
            if not v
        ]
        if missing:
            rep.blocks_incomplete.append(f"{pubid or '<no id>'} ({', '.join(missing)})")
            continue

        try:
            origin_time = _combine(date, clock)
        except ValueError:
            rep.blocks_incomplete.append(f"{pubid} (unparsable date or time)")
            continue

        ev = Event(
            pubid=pubid,
            date=date,
            time=clock,
            origin_time=origin_time,
            lat=coords["Latitude"][0],
            lon=coords["Longitude"][0],
            depth=depth[0],
            lat_err=coords["Latitude"][1],
            lon_err=coords["Longitude"][1],
            depth_err=depth[1],
            rms=rms,
            azgap=azgap,
            n_phase=counts["Phase arrivals"],
            n_stamag=counts["Station magnitudes"],
            origin_id=cur.get("event:Preferred Origin ID", ""),
            magnitude_id=cur.get("event:Preferred Magnitude ID", ""),
            region=region,
            event_type=cur.get("origin:Type", "") or cur.get("event:Type", ""),
            agency=cur.get("origin:Agency", ""),
            author=cur.get("origin:Author", ""),
            mode=cur.get("origin:Mode", ""),
            status=cur.get("origin:Status", ""),
            creation_time=cur.get("event:Creation time", ""),
            origin_creation_time=origin_creation,
            magnitudes=mags,
        )
        for row in pick_rows:
            pk = _parse_pick(row, origin_time)
            if pk is None:
                rep.picks_unparsed += 1
            else:
                ev.picks.append(pk)
        for row in stamag_rows:
            sm = _parse_stamag(row)
            if sm is not None:
                ev.station_magnitudes.append(sm)

        if ev.n_phase != len(pick_rows):
            rep.phase_count_mismatch.append(pubid)

        events.append(ev)
        rep.events_read += 1
        rep.picks_read += len(ev.picks)
        rep.station_magnitudes_read += len(ev.station_magnitudes)
        rep.magnitudes_read += len(ev.magnitudes)

    return events, rep


# --------------------------------------------------------------------------
# the 11-column catalogue
# --------------------------------------------------------------------------


def write_classic(
    events: Sequence[Event], path: str | os.PathLike
) -> WriteReport:
    """Write the 11-column catalogue, as ``bul.py`` did.

    Note on the column headed ``Nsta``: it holds the number of phase
    arrivals, not the number of stations. The two differ in all but 22 of the
    1752 Tyrnavos events. The header text is left as it is so the file stays
    byte-identical to catalogues already in circulation; QuakeML records the
    honest counts separately as ``usedPhaseCount`` and ``usedStationCount``.
    """
    rep = WriteReport(path=str(path))
    lines = [CLASSIC_HEADER]
    for ev in events:
        mag = ev.magnitude()
        if mag is None:
            rep.events_skipped_no_magnitude += 1
            continue
        if ev.rms is None or ev.azgap is None:
            rep.events_skipped_no_quality += 1
            continue
        lines.append(
            f"{ev.date} {ev.time} {ev.lat:6.4f} {ev.lon:6.4f} "
            f"{ev.depth:5.2f} {mag.value:4.2f} {ev.rms:4.2f} {ev.azgap:6.2f} "
            f"{ev.n_phase:3d} {ev.n_stamag:3d} {ev.pubid}"
        )
        rep.events_written += 1
    _write_lines(path, lines)
    return rep


# --------------------------------------------------------------------------
# the 6-column analyst file
# --------------------------------------------------------------------------


def _round_centiseconds(t: datetime) -> tuple[datetime, bool]:
    """Round to the nearest 1/100 s, carrying into the next second.

    Ties round up -- ``.575`` becomes ``.58`` -- which is the usual
    convention for times and is applied uniformly. Python's ``round`` would
    instead round a tie to the even centisecond, sending ``.575`` up and
    ``.565`` down, and ``transform.py`` inherited whichever way the binary
    double for the decimal fraction happened to fall.

    Returns the rounded time and whether a carry happened.
    """
    cs = (t.microsecond + 5000) // 10000
    if cs == 100:
        return t.replace(microsecond=0) + timedelta(seconds=1), True
    return t.replace(microsecond=cs * 10000), False


def write_sixcol(
    events: Sequence[Event], path: str | os.PathLike, legacy: bool = False
) -> WriteReport:
    """Write the 6-column analyst format.

    ``transform.py`` built the centiseconds as
    ``f"{int(round(float('0.' + ms) * 100)):02}"``, which cannot carry: an
    origin at ``12:02:36.996`` became ``120236.100``. That is wrong twice
    over -- the value should be ``120237.00``, and the field is one character
    wider than the fixed-width layout allows, so every column after it
    shifts. Six of the 1752 Tyrnavos events hit it.

    This writer rounds through ``datetime``, so a carry rolls the second, the
    minute and if need be the day. ``legacy=True`` reproduces the old output
    byte for byte, including those six lines, which is what the regression
    test compares against.

    The magnitude is also rounded once here, from the bulletin value, rather
    than twice as the old pair did (bulletin -> 2 decimals in the text
    catalogue -> 1 decimal here). ``legacy=True`` restores the double
    rounding too.
    """
    rep = WriteReport(path=str(path))
    lines = []
    for ev in events:
        mag = ev.magnitude()
        if mag is None:
            rep.events_skipped_no_magnitude += 1
            continue
        if legacy:
            frac = ev.time.split(".")[1] if "." in ev.time else "0"
            cs = f"{int(round(float('0.' + frac) * 100)):02}"
            hhmmss = ev.time.split(".")[0].replace(":", "")
            stamp = f"{ev.origin_time.year} {ev.origin_time:%m%d}{hhmmss}.{cs}"
            magtxt = f"{round(mag.value, 2):.1f}"
        else:
            rep.centisecond_ties += ev.origin_time.microsecond % 10000 == 5000
            t, carried = _round_centiseconds(ev.origin_time)
            rep.centiseconds_carried += carried
            stamp = f"{t.year} {t:%m%d%H%M%S}.{t.microsecond // 10000:02d}"
            magtxt = f"{mag.value:.1f}"
        lines.append(
            f"{stamp} {ev.lat:.4f} {ev.lon:.4f} {ev.depth:6.2f} {magtxt}"
        )
        rep.events_written += 1
    _write_lines(path, lines)
    return rep


# --------------------------------------------------------------------------
# QuakeML 1.2
# --------------------------------------------------------------------------


def _num(v: float) -> str:
    """Ten significant digits: enough for any bulletin field, and it keeps
    binary noise such as 0.022329170000000003 out of the file."""
    return f"{v:.10g}"


def _iso(t: datetime) -> str:
    s = t.strftime("%Y-%m-%dT%H:%M:%S")
    if t.microsecond:
        s += f".{t.microsecond:06d}".rstrip("0")
    return s + "Z"


def _iso_str(s: str) -> str | None:
    """The bulletin's ``Creation time`` strings, as QuakeML timestamps."""
    s = s.strip()
    if not s:
        return None
    try:
        return _iso(datetime.fromisoformat(s))
    except ValueError:
        return None


def _sub(parent, tag: str, text=None, **attrs):
    el = ET.SubElement(parent, f"{{{BED_NS}}}{tag}", {k: str(v) for k, v in attrs.items()})
    if text is not None:
        el.text = str(text)
    return el


def _quantity(parent, tag: str, value: float, uncertainty: float | None = None):
    el = _sub(parent, tag)
    _sub(el, "value", _num(value))
    if uncertainty is not None:
        _sub(el, "uncertainty", _num(uncertainty))
    return el


def _creation_info(parent, agency: str, author: str, when: str | None):
    if not (agency or author or when):
        return None
    el = _sub(parent, "creationInfo")
    if agency:
        _sub(el, "agencyID", agency)
    if author:
        _sub(el, "author", author)
    if when:
        _sub(el, "creationTime", when)
    return el


def write_quakeml(
    events: Sequence[Event],
    path: str | os.PathLike,
    picks: bool = True,
    authority: str | None = None,
) -> WriteReport:
    """Write QuakeML 1.2.

    What goes where, and the unit conversions the format requires:

    ==========================  ===================================================
    bulletin                    QuakeML
    ==========================  ===================================================
    ``Latitude ... +/- x km``   ``origin/latitude``, uncertainty converted to
                                degrees; longitude divided by cos(latitude) too
    ``Depth ... +/- x km``      ``origin/depth`` in **metres**, as the schema wants
    both horizontal errors      ``originUncertainty/horizontalUncertainty``,
                                sqrt(a^2+b^2) in metres, described as
                                "horizontal uncertainty"
    ``Residual RMS``            ``origin/quality/standardError``
    ``Azimuthal gap``           ``origin/quality/azimuthalGap``
    ``Mode`` / ``Status``       ``evaluationMode`` / ``evaluationStatus``
    ``region name:``            ``description`` of type "region name"
    ``MLh`` / ``M`` lines       one ``magnitude`` each, the preferred one named
                                by ``preferredMagnitudeID``
    phase row M/A flag          ``pick/evaluationMode``
    phase row ``X`` flag        ``pick/evaluationStatus`` = "rejected"
    phase row res / wt          ``arrival/timeResidual`` / ``timeWeight``
    phase row dist / azi        ``arrival/distance`` / ``azimuth``
    station magnitude row       ``stationMagnitude`` plus an ``amplitude`` for the
                                ``amp`` column, linked by ``amplitudeID``
    ==========================  ===================================================

    The ``X`` flag needs its own element rather than being inferred from the
    weight: in the Tyrnavos bulletin the lowest weight on an unflagged pick is
    0.1, which is also a weight X-flagged picks carry, so the flag is not
    recoverable from the weight alone.

    ``picks=False`` writes origins and network magnitudes only -- no picks,
    arrivals, station magnitudes or amplitudes. That is about a tenth of the
    size.

    Resource identifiers are ``smi:<authority>/<kind>/<id>``. The authority
    defaults to the bulletin's own agency, lowercased.
    """
    rep = WriteReport(path=str(path))
    auth = (authority or (events[0].agency if events else "") or "local").lower()
    auth = re.sub(r"[^a-z0-9.\-]", "", auth) or "local"

    ET.register_namespace("q", QUAKEML_NS)
    ET.register_namespace("", BED_NS)
    root = ET.Element(f"{{{QUAKEML_NS}}}quakeml")
    stem = Path(path).stem
    ep = _sub(root, "eventParameters", publicID=f"smi:{auth}/eventParameters/{stem}")

    def rid(kind: str, ident: str) -> str:
        return f"smi:{auth}/{kind}/{ident}"

    for ev in events:
        ev_el = _sub(ep, "event", publicID=rid("event", ev.pubid))
        if ev.region:
            d = _sub(ev_el, "description")
            _sub(d, "text", ev.region)
            _sub(d, "type", "region name")

        origin_id = rid("origin", ev.origin_id or ev.pubid)
        pick_ids: list[str] = []
        stamag_ids: list[tuple[str, StationMagnitude]] = []

        if picks:
            for i, sm in enumerate(ev.station_magnitudes, 1):
                amp_id = rid("amplitude", f"{ev.pubid}/{i}")
                if sm.amplitude is not None:
                    amp = _sub(ev_el, "amplitude", publicID=amp_id)
                    _quantity(amp, "genericAmplitude", sm.amplitude)
                    _sub(amp, "type", sm.type)
                    if sm.period is not None:
                        _quantity(amp, "period", sm.period)
                    _sub(amp, "magnitudeHint", sm.type)
                    _sub(
                        amp,
                        "waveformID",
                        networkCode=sm.network,
                        stationCode=sm.station,
                    )
                stamag_ids.append((amp_id if sm.amplitude is not None else "", sm))

        for m in ev.magnitudes:
            ident = (
                ev.magnitude_id
                if m.preferred and ev.magnitude_id
                else f"{ev.pubid}/{m.type}"
            )
            mag_el = _sub(ev_el, "magnitude", publicID=rid("magnitude", ident))
            if picks:
                for j, (amp_id, sm) in enumerate(stamag_ids, 1):
                    if sm.type != m.type:
                        continue
                    c = _sub(mag_el, "stationMagnitudeContribution")
                    _sub(
                        c,
                        "stationMagnitudeID",
                        rid("stationmagnitude", f"{ev.pubid}/{j}"),
                    )
                    _sub(c, "residual", _num(sm.residual))
            _quantity(mag_el, "mag", m.value, m.uncertainty)
            _sub(mag_el, "type", m.type)
            _sub(mag_el, "originID", origin_id)
            if m.station_count is not None:
                _sub(mag_el, "stationCount", m.station_count)
            if ev.mode in ("manual", "automatic"):
                _sub(mag_el, "evaluationMode", ev.mode)
            _creation_info(mag_el, m.agency or ev.agency, "", _iso_str(ev.origin_creation_time))

        if picks:
            for j, (amp_id, sm) in enumerate(stamag_ids, 1):
                sm_el = _sub(
                    ev_el,
                    "stationMagnitude",
                    publicID=rid("stationmagnitude", f"{ev.pubid}/{j}"),
                )
                _sub(sm_el, "originID", origin_id)
                _quantity(sm_el, "mag", sm.value)
                _sub(sm_el, "type", sm.type)
                if amp_id:
                    _sub(sm_el, "amplitudeID", amp_id)
                _sub(
                    sm_el,
                    "waveformID",
                    networkCode=sm.network,
                    stationCode=sm.station,
                )
                rep.station_magnitudes_written += 1

        # ---- origin, with its arrivals ----
        or_el = _sub(ev_el, "origin", publicID=origin_id)
        if ev.lat_err is not None or ev.lon_err is not None:
            unc = _sub(or_el, "originUncertainty")
            a = ev.lat_err or 0.0
            b = ev.lon_err or 0.0
            _sub(unc, "horizontalUncertainty", _num(math.hypot(a, b) * 1000.0))
            _sub(unc, "preferredDescription", "horizontal uncertainty")

        if picks:
            for i, pk in enumerate(ev.picks, 1):
                pick_id = rid("pick", f"{ev.pubid}/{i}")
                pick_ids.append(pick_id)
                ar = _sub(or_el, "arrival", publicID=rid("arrival", f"{ev.pubid}/{i}"))
                _sub(ar, "pickID", pick_id)
                _sub(ar, "phase", pk.phase)
                _sub(ar, "azimuth", _num(pk.azimuth))
                _sub(ar, "distance", _num(pk.distance))
                if pk.residual is not None:
                    _sub(ar, "timeResidual", _num(pk.residual))
                _sub(ar, "timeWeight", _num(pk.weight))

        t_el = _sub(or_el, "time")
        _sub(t_el, "value", _iso(ev.origin_time))
        lat_unc = ev.lat_err / KM_PER_DEG if ev.lat_err is not None else None
        coslat = max(math.cos(math.radians(ev.lat)), 1e-6)
        lon_unc = ev.lon_err / (KM_PER_DEG * coslat) if ev.lon_err is not None else None
        _quantity(or_el, "latitude", ev.lat, lat_unc)
        _quantity(or_el, "longitude", ev.lon, lon_unc)
        _quantity(
            or_el,
            "depth",
            ev.depth * 1000.0,
            ev.depth_err * 1000.0 if ev.depth_err is not None else None,
        )
        _sub(or_el, "depthType", "from location")

        q = _sub(or_el, "quality")
        used = [p for p in ev.picks if not p.rejected]
        _sub(q, "associatedPhaseCount", ev.n_phase or len(ev.picks))
        if ev.picks:
            _sub(q, "usedPhaseCount", len(used))
            _sub(q, "associatedStationCount", len({p.station for p in ev.picks}))
            _sub(q, "usedStationCount", len({p.station for p in used}))
        if ev.rms is not None:
            _sub(q, "standardError", _num(ev.rms))
        if ev.azgap is not None:
            _sub(q, "azimuthalGap", _num(ev.azgap))
        if ev.picks:
            d = sorted(p.distance for p in ev.picks)
            _sub(q, "maximumDistance", _num(d[-1]))
            _sub(q, "minimumDistance", _num(d[0]))
            _sub(q, "medianDistance", _num(d[len(d) // 2]))

        if ev.mode in ("manual", "automatic"):
            _sub(or_el, "evaluationMode", ev.mode)
        if ev.status in ("preliminary", "confirmed", "reviewed", "final", "rejected"):
            _sub(or_el, "evaluationStatus", ev.status)
        _creation_info(
            or_el, ev.agency, ev.author, _iso_str(ev.origin_creation_time)
        )

        # ---- picks ----
        if picks:
            for i, pk in enumerate(ev.picks, 1):
                p_el = _sub(ev_el, "pick", publicID=pick_ids[i - 1])
                pt = _sub(p_el, "time")
                _sub(pt, "value", _iso(pk.time))
                _sub(
                    p_el,
                    "waveformID",
                    networkCode=pk.network,
                    stationCode=pk.station,
                )
                _sub(p_el, "phaseHint", pk.phase)
                _sub(p_el, "evaluationMode", pk.mode)
                if pk.rejected:
                    _sub(p_el, "evaluationStatus", "rejected")
                rep.picks_written += 1

        if ev.origin_id:
            _sub(ev_el, "preferredOriginID", origin_id)
        pref = next((m for m in ev.magnitudes if m.preferred), None)
        if pref is not None:
            ident = ev.magnitude_id or f"{ev.pubid}/{pref.type}"
            _sub(ev_el, "preferredMagnitudeID", rid("magnitude", ident))
        if ev.event_type:
            _sub(ev_el, "type", ev.event_type)
        _creation_info(ev_el, ev.agency, ev.author, _iso_str(ev.creation_time))
        rep.events_written += 1

    ET.indent(root, space="  ")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)
    return rep


# --------------------------------------------------------------------------
# the project record
# --------------------------------------------------------------------------


def catalogue_summary(events: Sequence[Event]) -> dict:
    """The ``catalogue`` section of the project record.

    Covers the events that have a magnitude -- those in the 6-column file.
    """
    rows = [(ev, m) for ev in events if (m := ev.magnitude()) is not None]
    if not rows:
        return {"total_events": 0}
    big, big_mag = max(rows, key=lambda r: r[1].value)
    times = [ev.origin_time for ev, _ in rows]
    return {
        "total_events": len(rows),
        "start_time": min(times).isoformat(timespec="milliseconds"),
        "end_time": max(times).isoformat(timespec="milliseconds"),
        "latitude_min": min(ev.lat for ev, _ in rows),
        "latitude_max": max(ev.lat for ev, _ in rows),
        "longitude_min": min(ev.lon for ev, _ in rows),
        "longitude_max": max(ev.lon for ev, _ in rows),
        "depth_min_km": min(ev.depth for ev, _ in rows),
        "depth_max_km": max(ev.depth for ev, _ in rows),
        "magnitude_min": min(m.value for _, m in rows),
        "magnitude_max": big_mag.value,
        "largest_event": {
            "time": big.origin_time.isoformat(timespec="milliseconds"),
            "magnitude": big_mag.value,
            "latitude": big.lat,
            "longitude": big.lon,
            "depth_km": big.depth,
            "event_id": big.pubid,
        },
    }


def _project_bulletin(proj: Project) -> str | None:
    rel = proj.load()["project"]["bulletin_file"]
    return str(proj.root / rel) if rel else None


# --------------------------------------------------------------------------
# plumbing
# --------------------------------------------------------------------------


def _write_lines(path: str | os.PathLike, lines: Sequence[str]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n")


FORMATS = ("classic", "6col", "quakeml", "all")

_FORMAT_ANSWERS = {
    "classic": "classic",
    "cat": "classic",
    "c": "classic",
    "1": "classic",
    "6col": "6col",
    "6": "6col",
    "sixcol": "6col",
    "2": "6col",
    "quakeml": "quakeml",
    "qml": "quakeml",
    "xml": "quakeml",
    "q": "quakeml",
    "3": "quakeml",
    "all": "all",
    "a": "all",
    "4": "all",
    "": "all",
}


def _prompt_for_input(folder: str = "Input", default: str | None = None) -> str:
    if os.path.isdir(folder):
        print(f"{shown(folder)} folder:")
        for name in sorted(os.listdir(folder)):
            print(f"    {name}")
    else:
        print(f"The folder {shown(folder)} does not exist.")
    while True:
        name = ask_file_name("Enter the name of the earthquake bulletin file", default)
        path = os.path.join(folder, name) if name else ""
        if path and os.path.isfile(path):
            return path
        print(f"    {shown(path) if path else '(nothing entered)'} is not a file -- try again.")


def _prompt_for_format() -> str:
    print("\nOutput formats:")
    print("    1  classic  11-column catalogue        (_cat.txt)")
    print("    2  6col     6-column analyst format    (_cat_6col.txt)")
    print("    3  quakeml  QuakeML 1.2                (_cat.xml)")
    print("    4  all      all three  [default]")
    while True:
        answer = input("Which format? ").strip().lower()
        if answer in _FORMAT_ANSWERS:
            return _FORMAT_ANSWERS[answer]
        print("    Enter 1, 2, 3, 4 or a format name -- try again.")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Convert a bulletin to the 11-column catalogue, the "
        "6-column analyst format and QuakeML 1.2."
    )
    ap.add_argument(
        "-p", "--project", help="project to work in; prompts if omitted (Enter = last used)"
    )
    ap.add_argument(
        "-i",
        "--input",
        help="bulletin file; prompts if omitted, or takes the project's bulletin "
        "when there is no terminal to ask on",
    )
    ap.add_argument(
        "-f", "--format", choices=FORMATS, help="output format; prompts if omitted"
    )
    ap.add_argument(
        "-d", "--outdir", help="output folder (default: the project's Results folder)"
    )
    ap.add_argument(
        "--no-picks",
        dest="picks",
        action="store_false",
        help="QuakeML without picks, arrivals, station magnitudes or amplitudes",
    )
    ap.add_argument(
        "--legacy-6col",
        action="store_true",
        help="reproduce transform.py's centisecond and magnitude rounding exactly",
    )
    ap.add_argument("--authority", help="authority for QuakeML resource ids")
    args = ap.parse_args(argv)

    interactive = sys.stdin.isatty()
    proj = open_project(args.project)
    path = args.input
    if not path:
        if interactive:
            path = _prompt_for_input(
                proj.input_dir,
                proj.recorded_name(proj.input_dir, "project", "bulletin_file"),
            )
        else:
            path = _project_bulletin(proj)
            if not path:
                ap.error("no --input given, no terminal to ask on and no bulletin "
                         "in the project")
    if not os.path.isfile(path):
        print(f"The file {path} does not exist.", file=sys.stderr)
        return 1

    fmt = args.format
    if not fmt:
        fmt = _prompt_for_format() if interactive else "all"

    events, rr = read_bulletin(path)
    print(f"\nRead {rr.summary()} from {shown(path)}")
    if not events:
        print("Nothing to write.", file=sys.stderr)
        return 1

    stem = Path(path).stem
    outdir = Path(args.outdir) if args.outdir else proj.results_dir
    files = {}
    if fmt in ("classic", "all"):
        out = outdir / f"{stem}_cat.txt"
        print(write_classic(events, out).summary())
        files["catalogue_file"] = proj.rel(out)
    if fmt in ("6col", "all"):
        out = outdir / f"{stem}_cat_6col.txt"
        print(write_sixcol(events, out, legacy=args.legacy_6col).summary())
        files["catalogue_6col_file"] = proj.rel(out)
    if fmt in ("quakeml", "all"):
        out = outdir / f"{stem}_cat.xml"
        print(
            write_quakeml(
                events,
                out,
                picks=args.picks,
                authority=args.authority,
            ).summary()
        )
        files["catalogue_quakeml_file"] = proj.rel(out)
    proj.update(
        "catalog.py",
        {"project": files, "catalogue": catalogue_summary(events)},
        bulletin=proj.rel(path),
        format=fmt,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
