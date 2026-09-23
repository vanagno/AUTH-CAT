"""Extract seismic phase arrivals from an AUTOLOC3 / SeisComp bulletin.

Writes either format:

* ``hypodd``  -- HypoDD/ph2dt phase input (``phase.dat``). Free-format ``#`` event
  header plus fixed-column phase lines carrying **travel times** relative to the
  origin, per the HypoDD v2.1 manual::

      # YR MO DY HR MN SC LAT LON DEP MAG EH EZ RMS ID
      STA        TT     WGHT  PHA

* ``hypo71`` -- 

Run with no ``--format`` at a terminal and the script asks which format(s) to
write. With stdin piped, or with ``--format`` given, it does not ask -- so
existing batch scripts keep working unchanged and get both formats, meaning
``Results/phases.txt`` as before plus ``Results/phase.dat`` alongside it.

Usage
-----
    python phases.py                                       # asks for both questions
    python phases.py -i Input/Kef24.bul                    # asks for the format only
    python phases.py -i Input/Kef24.bul -f both            # asks nothing
    python phases.py -i Input/Kef24.bul -f both -d out      # both, elsewhere
    python phases.py -i Input/Kef24.bul -f hypodd -o p.dat # one format, named


"""

from __future__ import annotations

import argparse
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

__all__ = [
    "Arrival",
    "Event",
    "WriteReport",
    "read_bulletin",
    "read_hypodd",
    "write_hypo71",
    "write_hypodd",
]


HYPODD_PHASE_FMT = "{sta:<8s}{tt:>9.3f}{wgt:>8.3f}{pha:>4s}"
HYPODD_STA_WIDTH = 7  # HypoDD reads the station code as a7
_HYPODD_HDR_RX = re.compile(
    r"^#\s+(\d{4})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+([\d.]+)\s+"
    r"([-+]?[\d.]+)\s+([-+]?[\d.]+)\s+([-+]?[\d.]+)\s+([-+]?[\d.]+)\s+"
    r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\S+)\s*$"
)

# --------------------------------------------------------------------------- #
# Bulletin grammar. 
# --------------------------------------------------------------------------- #
_NUM = r"([-+]?\d+(?:\.\d+)?)"
_ERR = r"(?:\s*(?:deg|km)?\s*(?:\+/-|±)\s*([\d.]+))?"
_BULLETIN_RX = {
    "date": re.compile(r"^\s*Date\s+(\d{4}-\d{2}-\d{2})\s*$"),
    "time": re.compile(r"^\s*Time\s+(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)"),
    "lat": re.compile(rf"^\s*Latitude\s+{_NUM}{_ERR}"),
    "lon": re.compile(rf"^\s*Longitude\s+{_NUM}{_ERR}"),
    "depth": re.compile(rf"^\s*Depth\s+{_NUM}{_ERR}"),
    "rms": re.compile(rf"^\s*Residual RMS\s+{_NUM}"),
    "evid": re.compile(r"^\s*(?:Public ID|Event ID|Origin ID)\s+(\S+)"),
}
# Network magnitude lines, in preference order. The review flagged that the old
# code took whichever magnitude line appeared last; here the first match wins.
_MAG_RX = re.compile(rf"^\s*(MLh|ML|Mw|mb|Ms|M)\s+{_NUM}")
_MAG_PRIORITY = ("MLh", "ML", "Mw", "mb", "Ms", "M")

_CLOCK_RX = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)$")
_PHASE_RX = re.compile(r"^(P|S|Pg|Sg|Pn|Sn|Pb|Sb|P1|S1)$", re.IGNORECASE)


@dataclass
class Arrival:
    """One phase pick."""

    station: str
    phase: str  # normalised to 'P' or 'S'
    time: datetime
    weight: float = 1.0


@dataclass
class Event:
    """One located event and its picks."""

    origin: datetime
    lat: float
    lon: float
    depth: float
    mag: float = 0.0
    eh: float = 0.0
    ez: float = 0.0
    rms: float = 0.0
    evid: int = 0
    pubid: str = ""  # original bulletin ID, kept so HypoDD output can be joined back
    arrivals: list[Arrival] = field(default_factory=list)

    def travel_times(self) -> list[tuple[Arrival, float]]:
        return [(a, (a.time - self.origin).total_seconds()) for a in self.arrivals]


@dataclass
class WriteReport:
    """What was written and what was rejected.

    Nothing is discarded silently: every counter here is reported by the CLI.
    """

    events_written: int = 0
    phases_written: int = 0
    events_skipped_few_phases: int = 0
    events_skipped_no_origin: int = 0
    phases_nonpositive_tt: int = 0
    phases_beyond_max_tt: int = 0
    phases_unrepresentable: int = 0
    phases_unpaired: int = 0
    events_skipped_no_pairs: int = 0
    stations_truncated: set[str] = field(default_factory=set)

    def summary(self) -> str:
        parts = [f"{self.events_written} events, {self.phases_written} phases written"]
        if self.events_skipped_no_origin:
            parts.append(f"{self.events_skipped_no_origin} events without a usable origin")
        if self.events_skipped_few_phases:
            parts.append(f"{self.events_skipped_few_phases} events below the phase minimum")
        if self.phases_nonpositive_tt:
            parts.append(f"{self.phases_nonpositive_tt} phases with travel time <= 0")
        if self.phases_beyond_max_tt:
            parts.append(f"{self.phases_beyond_max_tt} phases beyond the travel-time limit")
        if self.phases_unrepresentable:
            parts.append(
                f"{self.phases_unrepresentable} S picks too late to fit the HYPO71 "
                "seconds field (>= 100 s after P)"
            )
        if self.phases_unpaired:
            parts.append(
                f"{self.phases_unpaired} picks with no P/S counterpart at the same "
                "station (a HYPO71 card needs both)"
            )
        if self.events_skipped_no_pairs:
            parts.append(
                f"{self.events_skipped_no_pairs} events with no P/S pair at any station"
            )
        if self.stations_truncated:
            parts.append(
                f"station codes truncated to {HYPODD_STA_WIDTH} chars: "
                + ",".join(sorted(self.stations_truncated))
            )
        return "; ".join(parts)


# --------------------------------------------------------------------------- #
# Reading the bulletin
# --------------------------------------------------------------------------- #
def _arrival_datetime(origin: datetime, clock: str) -> datetime:
    """Attach a bulletin clock time to the right calendar day.

    A pick printed as ``00:00:04.1`` for an origin at ``23:59:58`` belongs to the
    following day. Resolved by taking whichever of the three candidate days puts
    the arrival closest to the origin.
    """
    h, m, s = _CLOCK_RX.match(clock).groups()
    midnight = datetime.combine(origin.date(), datetime.min.time())
    t = midnight + timedelta(hours=int(h), minutes=int(m), seconds=float(s))
    return min(
        (t + timedelta(days=d) for d in (-1, 0, 1)),
        key=lambda c: abs((c - origin).total_seconds()),
    )


def _parse_origin(date: str, time: str) -> datetime:
    """Combine the bulletin's ``Date`` and ``Time`` fields into one datetime."""
    h, m, s = _CLOCK_RX.match(time).groups()
    return datetime.strptime(date, "%Y-%m-%d") + timedelta(
        hours=int(h), minutes=int(m), seconds=float(s)
    )


def read_bulletin(path: str | Path, *, weight_col: int | None = None) -> list[Event]:
    """Parse an AUTOLOC3 / SeisComp bulletin into :class:`Event` records.

    Parameters
    ----------
    path
        Bulletin file (``*.bul``).
    weight_col
        Zero-based column index of the pick weight in the phase table, if your
        bulletin prints one. Left as ``None`` every pick is given weight 1.000

    Phase rows are recognised by *content* -- a phase label in column 5 and a
    ``HH:MM:SS.sss`` clock time in column 6 -- rather than by counting columns, so
    the column-header row is skipped without a special case and a bulletin with 9
    or 10 columns both work.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    events: list[Event] = []
    cur: dict[str, object] = {}
    arrivals: list[Arrival] = []
    mags: dict[str, float] = {}
    in_phases = False

    def flush() -> None:
        nonlocal cur, arrivals, mags
        if cur.get("date") and cur.get("time"):
            origin = _parse_origin(str(cur["date"]), str(cur["time"]))
            mag = next((mags[k] for k in _MAG_PRIORITY if k in mags), 0.0)
            events.append(
                Event(
                    origin=origin,
                    lat=float(cur.get("lat", 0.0)),
                    lon=float(cur.get("lon", 0.0)),
                    depth=float(cur.get("depth", 0.0)),
                    mag=mag,
                    eh=math.hypot(float(cur.get("err_lat", 0.0)), float(cur.get("err_lon", 0.0))),
                    ez=float(cur.get("err_depth", 0.0)),
                    rms=float(cur.get("rms", 0.0)),
                    # HypoDD's ID field is an integer. A numeric bulletin ID is kept
                    # as-is; a public ID like 'auth2024abcd' cannot be, so the event
                    # is numbered sequentially and the original kept in `pubid`.
                    evid=int(str(cur["evid"]))
                    if str(cur.get("evid", "")).lstrip("-").isdigit()
                    else len(events) + 1,
                    pubid=str(cur.get("evid", "")),
                    arrivals=list(arrivals),
                )
            )
        cur, arrivals, mags = {}, [], {}

    for line in text.splitlines():
        for key in ("date", "time", "lat", "lon", "depth", "rms", "evid"):
            m = _BULLETIN_RX[key].match(line)
            if m:

                if key in cur:
                    flush()
                    in_phases = False
                cur[key] = m.group(1)
                if key in ("lat", "lon", "depth") and m.lastindex >= 2 and m.group(2):
                    cur["err_" + key] = m.group(2)
                break

        mm = _MAG_RX.match(line)
        if mm and mm.group(1) not in mags:
            mags[mm.group(1)] = float(mm.group(2))

        if "Phase arrivals:" in line:
            in_phases = True
            continue
        if in_phases:
            if not line.strip():
                in_phases = False
                continue
            parts = line.split()
            if (
                len(parts) >= 6
                and cur.get("date")
                and cur.get("time")
                and _PHASE_RX.match(parts[4])
                and _CLOCK_RX.match(parts[5])
            ):
                wgt = 1.0
                if weight_col is not None and len(parts) > weight_col:
                    try:
                        wgt = float(parts[weight_col])
                    except ValueError:
                        wgt = 1.0
                origin = _parse_origin(str(cur["date"]), str(cur["time"]))
                arrivals.append(
                    Arrival(
                        station=parts[0],
                        phase=parts[4][0].upper(),
                        time=_arrival_datetime(origin, parts[5]),
                        weight=wgt,
                    )
                )
    flush()
    return events


# --------------------------------------------------------------------------- #
# Writing HypoDD phase input
# --------------------------------------------------------------------------- #
def write_hypodd(
    events: list[Event],
    path: str | Path,
    *,
    min_phases: int = 4,
    max_tt: float | None = None,
    renumber: bool = False,
    pad_time: bool = True,
) -> WriteReport:
    """Write ``phase.dat`` in HypoDD/ph2dt format.

    Parameters
    ----------
    min_phases
        Events with fewer surviving picks are skipped and counted. ``ph2dt``
        applies its own ``MINOBS``; this is only to keep unusable events out.
    max_tt
        Optional travel-time ceiling in seconds, for dropping picks at
        implausible distance.
    renumber
        ``False`` (default) keeps the bulletin event ID, so the HypoDD output can
        be joined back to the catalogue. The reference file does this -- its IDs
        run to 11 737 across 11 699 events. ``True`` renumbers from 1.
    pad_time
        ``True`` (default) writes hour and minute zero-padded to two digits, so
        midnight reads ``00 00``. ``False`` writes them bare (``0 0``), which is
        what homeros_catalog_ionio24.txt does -- pass it to reproduce that file
        byte for byte. The header is read list-directed by ``ph2dt``, so both
        parse identically; this only affects how the file looks.
    """
    path = Path(path)
    rep = WriteReport()
    out: list[str] = []

    for n, ev in enumerate(events, start=1):
        if ev.origin is None:
            rep.events_skipped_no_origin += 1
            continue
        rows: list[str] = []
        for arr, tt in ev.travel_times():
            if tt <= 0:
                rep.phases_nonpositive_tt += 1
                continue
            if max_tt is not None and tt > max_tt:
                rep.phases_beyond_max_tt += 1
                continue
            sta = arr.station
            if len(sta) > HYPODD_STA_WIDTH:
                rep.stations_truncated.add(sta)
                sta = sta[:HYPODD_STA_WIDTH]
            rows.append(
                HYPODD_PHASE_FMT.format(sta=sta, tt=tt, wgt=arr.weight, pha=arr.phase)
            )
        if len(rows) < min_phases:
            rep.events_skipped_few_phases += 1
            continue

        o = ev.origin
        secs = o.second + o.microsecond / 1e6
        evid = n if renumber else ev.evid
        w = 2 if pad_time else 1  # field width for hour and minute
        out.append(
            f"# {o.year} {o.month:02d} {o.day:02d} {o.hour:0{w}d} {o.minute:0{w}d} {secs:.2f} "
            f"{ev.lat:.4f} {ev.lon:.4f} {ev.depth:.2f} {ev.mag:.2f} "
            f"{ev.eh:.2f} {ev.ez:.2f} {ev.rms:.2f} {evid}"
        )
        out.extend(rows)
        rep.events_written += 1
        rep.phases_written += len(rows)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return rep


def read_hypodd(path: str | Path) -> list[Event]:
    """Read a HypoDD ``phase.dat`` back into :class:`Event` records.

    
    
    """
    events: list[Event] = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        if line.startswith("#"):
            m = _HYPODD_HDR_RX.match(line)
            if not m:
                raise ValueError(f"malformed HypoDD event header: {line!r}")
            yr, mo, dy, hr, mn = (int(m.group(i)) for i in range(1, 6))
            sc = float(m.group(6))
            origin = datetime(yr, mo, dy) + timedelta(
                hours=hr, minutes=mn, seconds=sc
            )
            events.append(
                Event(
                    origin=origin,
                    lat=float(m.group(7)),
                    lon=float(m.group(8)),
                    depth=float(m.group(9)),
                    mag=float(m.group(10)),
                    eh=float(m.group(11)),
                    ez=float(m.group(12)),
                    rms=float(m.group(13)),
                    evid=int(m.group(14)),
                )
            )
        else:
            sta, tt, wgt, pha = line.split()
            events[-1].arrivals.append(
                Arrival(
                    station=sta,
                    phase=pha,
                    time=events[-1].origin + timedelta(seconds=float(tt)),
                    weight=float(wgt),
                )
            )
    return events


# --------------------------------------------------------------------------- #
# Writing the original HYPO71-style output
# --------------------------------------------------------------------------- #
def write_hypo71(events: list[Event], path: str | Path) -> WriteReport:

    path = Path(path)
    rep = WriteReport()
    out: list[str] = []
    for ev in events:
        picks: dict[str, dict[str, datetime]] = {}
        for a in ev.arrivals:  # per event, so a stale P cannot pair with a later S
            picks.setdefault(a.station, {})[a.phase] = a.time
        rows: list[str] = []
        for sta in sorted(picks):
            p, s = picks[sta].get("P"), picks[sta].get("S")
            if p is None or s is None:
                # A HYPO71 card carries a P and an S for one station, so a lone
                # pick cannot be expressed. Counted rather than dropped in
                # silence -- the HypoDD output keeps these.
                rep.phases_unpaired += 1
                continue

            code = (sta + " EP") if len(sta) == 3 else (sta[:4] + "EP")
            p_secs = p.second + p.microsecond / 1e6
            s_secs = p_secs + (s - p).total_seconds()
            if s_secs >= 100:
                # The HYPO71 S field is F5.2, so it cannot carry an S arriving 100 s
                # or more after P. Writing it  overflows the column and
                # corrupts every field to its right, so the pick is dropped here and
                # counted. Such pairs are fine in the HypoDD output, which uses
                # travel times rather than a seconds-within-the-minute field.
                rep.phases_unrepresentable += 1
                continue
            rows.append(
                f"{code}   {p:%y%m%d%H%M}{p_secs:05.2f}       {s_secs:05.2f} S 2"
            )
        if not rows:
            # Emitting a bare terminator here would leave two in a row, which
            # reads back as one event, so the file would silently hold fewer
            # events than this report claims.
            rep.events_skipped_no_pairs += 1
            continue
        out.extend(rows)
        out.append("                 10")
        rep.phases_written += 2 * len(rows)
        rep.events_written += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return rep


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _prompt_for_input(folder: str = "Input") -> Path:
    """Ask for a bulletin, re-asking on a typo when a human is at the keyboard.

    A bare filename is looked up inside `folder`; anything that looks like a
    path is also tried as given, so both answers work.
    """
    d = Path(folder)
    if d.is_dir():
        print(f"{folder} folder:")
        for f in sorted(d.iterdir()):
            print("   ", f.name)
    else:
        print(f"The folder {folder} does not exist.")

    while True:
        try:
            name = input("Please provide the name of the earthquake bulletin: ").strip()
        except EOFError:
            raise SystemExit("error: no bulletin name given") from None
        if not name:
            raise SystemExit("error: no bulletin name given")
        for cand in (d / name, Path(name)):
            if cand.is_file():
                return cand

        if not sys.stdin.isatty():
            raise SystemExit(f"error: {name} not found")
        print(f"   '{name}' is not in {folder}/ and is not a readable path -- try again.")


#: Accepted answers to the format question, all lower-case.
_FORMAT_ANSWERS = {
    "1": "hypodd", "d": "hypodd", "dd": "hypodd", "hypodd": "hypodd",
    "2": "hypo71", "7": "hypo71", "71": "hypo71", "hypo71": "hypo71",
    "3": "both", "b": "both", "both": "both",
}


def _prompt_for_format(default: str = "both") -> str:
    """Ask which phase format(s) to write. Re-asks until the answer is valid."""
    print("\nWhich phase format(s) should be written?")
    print("   1) hypodd   -> phase.dat    HypoDD / ph2dt phase input")
    print("   2) hypo71   -> phases.txt   HYPO71 phase list")
    print("   3) both")
    while True:
        try:
            reply = input(f"Please choose 1, 2 or 3 [default {default}]: ").strip().lower()
        except EOFError:
            print(f"   no answer available -- writing {default}")
            return default
        if not reply:
            return default
        if reply in _FORMAT_ANSWERS:
            return _FORMAT_ANSWERS[reply]
        print(f"   '{reply}' is not one of 1, 2, 3, hypodd, hypo71, both -- try again.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-i", "--input", help="bulletin file; prompts if omitted")
    ap.add_argument("-d", "--outdir", default="Results",
                    help="output directory (default: Results)")
    ap.add_argument("-o", "--output",
                    help="override the output filename; only valid with a single --format")

    ap.add_argument("-f", "--format", choices=("hypodd", "hypo71", "both"), default=None,
                    help="output format; asked interactively if omitted (fallback: both)")
    ap.add_argument("--min-phases", type=int, default=4)
    ap.add_argument("--max-tt", type=float, default=None, help="drop picks beyond N seconds")
    ap.add_argument("--weight-col", type=int, default=None,
                    help="zero-based column of the pick weight in the phase table")
    ap.add_argument("--no-pad-time", dest="pad_time", action="store_false",
                    help="write bare hour/minute ('0 0') instead of zero-padded "
                         "('00 00'), matching homeros_catalog_ionio24.txt")
    ap.add_argument("--renumber", action="store_true",
                    help="renumber events 1..N instead of keeping bulletin IDs")
    args = ap.parse_args(argv)

    if args.output and args.format not in ("hypodd", "hypo71"):

        ap.error("--output names a single file; pass --format hypodd or --format "
                 "hypo71, or use --outdir to redirect both")

    src = Path(args.input) if args.input else _prompt_for_input()
    if not src.is_file():
        print(f"error: {src} not found", file=sys.stderr)
        return 1

    events = read_bulletin(src, weight_col=args.weight_col)
    n_pha = sum(len(e.arrivals) for e in events)
    print(f"Read {len(events)} events and {n_pha} picks from {src}")
    if not events:
        print("error: no events parsed -- check that the bulletin uses the expected "
              "'Date'/'Time'/'Latitude'/'Phase arrivals:' labels", file=sys.stderr)
        return 1

    # Asked only now, so a failed parse never costs the user a question, and
     # only when a terminal is there to answer: with stdin piped (as
    # batch_AUTHCAT.sh does for the filename) an input() call would consume a
    # line meant for something else, so fall back to writing both.
    fmt = args.format
    if fmt is None:
        fmt = _prompt_for_format() if sys.stdin.isatty() else "both"

    outdir = Path(args.outdir)
    if fmt in ("hypodd", "both"):
        out = Path(args.output) if args.output else outdir / "phase.dat"
        rep = write_hypodd(events, out, min_phases=args.min_phases,
                           max_tt=args.max_tt, renumber=args.renumber,
                           pad_time=args.pad_time)
        print(f"HypoDD phase input -> {out}: {rep.summary()}")
    if fmt in ("hypo71", "both"):
        out = Path(args.output) if args.output else outdir / "phases.txt"
        rep = write_hypo71(events, out)
        print(f"HYPO71 phase list  -> {out}: {rep.summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
