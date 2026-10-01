#!/usr/bin/env python3
"""Update the station list regd.sta from the FDSN station web services.

``authcat stup`` looks up the coordinates of every station AUTH-CAT needs --
those already in regd.sta and those named in the bulletins of the projects
in Projects/ -- and writes an updated regd.sta into the folder it is run
from, where ``authcat sta`` uses it in place of the installed copy.

Coordinates come from the FDSN station services, the standard way seismic
networks publish their metadata:

* the EIDA federator (eida-federator.ethz.ch), which answers for every
  European data centre;
* NOA's EIDA node (eida.gein.noa.gr), which holds the Greek networks
  (HL, HT, HP, HA, HC, HI) itself, so they are found even when the federator
  cannot be reached;
* IRIS (service.iris.edu), for anything EIDA does not hold.

Each service is asked once for every station in the region the list covers;
the station codes are matched here. A code found in more than one network is
settled by the network the bulletins name it with, then by the position
already listed; a code that still cannot be settled keeps its old line and is
reported.

Usage
-----
    authcat stup                       # current positions
    authcat stup --date 2021-03-03     # positions valid on that date
    authcat stup --dry-run             # show what would change, write nothing
    authcat stup -b other.bul          # also the stations of another bulletin

Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import shutil
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from authcat.project import PROJECTS_DIR, UTILITIES_DIR, list_projects, shown

SERVICES = [
    ("EIDA", "https://eida-federator.ethz.ch/fdsnws/station/1/query"),
    ("NOA", "https://eida.gein.noa.gr/fdsnws/station/1/query"),
    ("IRIS", "https://service.iris.edu/fdsnws/station/1/query"),
]
USER_AGENT = "authcat-stup (+https://github.com/vanagno/AUTH-CAT)"
STATION_FILE = "regd.sta"

#: Degrees added around the stations already listed to make the query region.
MARGIN = 1.0
#: Region used when there is no station list to take it from: Greece and its
#: neighbours.
DEFAULT_REGION = (33.5, 43.5, 18.0, 31.0)
#: Positions further apart than this (km) are treated as different places.
MOVED_KM = 1.0


@dataclass
class Epoch:
    """One line of an FDSN text response: a station over one time span."""

    network: str
    station: str
    lat: float
    lon: float
    start: dt.datetime | None
    end: dt.datetime | None
    source: str


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------


def read_station_list(path: str | os.PathLike) -> dict[str, tuple[float, float]]:
    """``{code: (lat, lon)}`` from a regd.sta. A code listed twice keeps its
    last line."""
    stations = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 3 or parts[0].startswith("#"):
                continue
            try:
                stations[parts[0]] = (float(parts[1]), float(parts[2]))
            except ValueError:
                continue
    return stations


def project_bulletins() -> list[Path]:
    """The bulletins in the Input folder of every project in Projects/."""
    return sorted(
        path
        for name in list_projects()
        for path in (PROJECTS_DIR / name / "Input").glob("*.bul")
    )


def bulletin_stations(paths: list[Path]) -> dict[str, set[str]]:
    """``{station code: {networks}}`` named in the bulletins' phase and
    station-magnitude rows."""
    from authcat.catalog import read_bulletin

    found: dict[str, set[str]] = {}
    for path in paths:
        events, _ = read_bulletin(path)
        for ev in events:
            for row in (*ev.picks, *ev.station_magnitudes):
                found.setdefault(row.station, set()).add(row.network)
    return found


def region(positions, margin: float = MARGIN) -> tuple[float, float, float, float]:
    """``(minlat, maxlat, minlon, maxlon)`` around ``positions``, widened by
    ``margin`` degrees."""
    positions = list(positions)
    if not positions:
        return DEFAULT_REGION
    lats = [p[0] for p in positions]
    lons = [p[1] for p in positions]
    return (
        max(min(lats) - margin, -90.0),
        min(max(lats) + margin, 90.0),
        max(min(lons) - margin, -180.0),
        min(max(lons) + margin, 180.0),
    )


# --------------------------------------------------------------------------
# the FDSN station service
# --------------------------------------------------------------------------


def _time(text: str) -> dt.datetime | None:
    """An FDSN time, e.g. ``2015-01-01T00:00:00.0000``; None when empty."""
    text = text.strip().rstrip("Z")
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text[:19])
    except ValueError:
        return None


def parse_fdsn_text(text: str, source: str) -> list[Epoch]:
    """Read a ``format=text`` station-level response::

        #Network | Station | Latitude | Longitude | Elevation | SiteName | StartTime | EndTime
        HL|ATH|37.97248|23.71746|95.0|Athens|1997-01-01T00:00:00|
    """
    epochs = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = [f.strip() for f in line.split("|")]
        if len(fields) < 8:
            continue
        try:
            lat, lon = float(fields[2]), float(fields[3])
        except ValueError:
            continue
        epochs.append(
            Epoch(fields[0], fields[1], lat, lon, _time(fields[6]), _time(fields[7]), source)
        )
    return epochs


def _open(request: urllib.request.Request, timeout: float):
    """urlopen, retrying with certifi's certificate authorities when the
    system's own cannot verify the server.

    Python installed from python.org on macOS, and some Windows setups, have
    no usable list of certificate authorities until one is installed; certifi
    (installed with cartopy) carries an up-to-date one.
    """
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.URLError as exc:
        if not isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise
        try:
            import certifi
        except ImportError:
            raise exc from None
        context = ssl.create_default_context(cafile=certifi.where())
        return urllib.request.urlopen(request, timeout=timeout, context=context)


def fetch_epochs(url: str, box: tuple[float, float, float, float], source: str,
                 timeout: float) -> list[Epoch]:
    """Every station epoch the service holds inside ``box``.

    Raises RuntimeError when the service cannot be reached or answers with
    an error.
    """
    query = urllib.parse.urlencode({
        "level": "station",
        "format": "text",
        "minlatitude": f"{box[0]:.4f}",
        "maxlatitude": f"{box[1]:.4f}",
        "minlongitude": f"{box[2]:.4f}",
        "maxlongitude": f"{box[3]:.4f}",
    })
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": USER_AGENT})
    try:
        with _open(request, timeout) as resp:
            if resp.status == 204:  # FDSN: no data
                return []
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (204, 404):  # no data, by the service's choice of code
            return []
        raise RuntimeError(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, ssl.SSLCertVerificationError):
            raise RuntimeError("its security certificate could not be verified") from None
        raise RuntimeError(str(reason)) from None
    return parse_fdsn_text(text, source)


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in km between two (lat, lon) positions."""
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def pick_epoch(epochs: list[Epoch], when: dt.datetime | None) -> Epoch | None:
    """The epoch valid at ``when``; with no date, the one that started last."""
    if when is not None:
        epochs = [
            e for e in epochs
            if (e.start is None or e.start <= when) and (e.end is None or when < e.end)
        ]
    if not epochs:
        return None
    return max(epochs, key=lambda e: e.start or dt.datetime.min)


def resolve(by_network: dict[str, list[Epoch]], networks_named: set[str],
            old: tuple[float, float] | None,
            when: dt.datetime | None) -> tuple[Epoch | None, str]:
    """Choose the position for one station code.

    Returns the chosen epoch, or None, and a note for the report.
    """
    named = [n for n in by_network if n in networks_named]
    networks = named or sorted(by_network)
    picks = [p for n in networks if (p := pick_epoch(by_network[n], when))]
    if not picks:
        return None, "not operating on that date"
    if len(picks) == 1:
        return picks[0], ""
    spread = max(km((a.lat, a.lon), (b.lat, b.lon)) for a in picks for b in picks)
    if spread <= MOVED_KM:
        return picks[0], ""  # the same site under each network
    nets = ", ".join(p.network for p in picks)
    if old is not None:
        best = min(picks, key=lambda p: km((p.lat, p.lon), old))
        return best, f"also in {nets}; took {best.network}, nearest the listed position"
    return None, f"in {nets} at different places"


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------


def _date(text: str) -> dt.datetime:
    try:
        return dt.datetime.strptime(text.strip(), "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date {text!r}, expected YYYY-MM-DD")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Update the station list regd.sta from the FDSN station services "
        "(EIDA, NOA, IRIS). Writes regd.sta into this folder, where 'authcat sta' uses it."
    )
    ap.add_argument("--date", type=_date, metavar="YYYY-MM-DD",
                    help="use the positions valid on this date instead of the current ones")
    ap.add_argument("-b", "--bulletin", action="append", default=[], metavar="FILE",
                    help="also look up the stations of this bulletin (repeatable); those "
                         "of every project in Projects/ are always included")
    ap.add_argument("-o", "--output", default=STATION_FILE,
                    help="file to write (default: regd.sta in this folder)")
    ap.add_argument("--region", type=float, nargs=4,
                    metavar=("MINLAT", "MAXLAT", "MINLON", "MAXLON"),
                    help="region to ask for (default: the listed stations plus a "
                         f"{MARGIN:g} degree margin)")
    ap.add_argument("--service", action="append", metavar="URL",
                    help="FDSN station service to ask instead of EIDA, NOA and IRIS (repeatable)")
    ap.add_argument("--timeout", type=float, default=180.0,
                    help="seconds to wait for each service")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would change and write nothing")
    args = ap.parse_args(argv)

    # The list to update: this folder's own, else the installed one.
    local = Path(STATION_FILE)
    source = local if local.is_file() else UTILITIES_DIR / STATION_FILE
    old = read_station_list(source)
    label = "regd.sta (current folder)" if source == local else "Utilities/regd.sta"
    print(f"Station list: {len(old)} stations from {label}")

    bulletins = project_bulletins() + [Path(b) for b in args.bulletin]
    missing_files = [b for b in bulletins if not b.is_file()]
    if missing_files:
        ap.error(f"no such bulletin: {missing_files[0]}")
    named = bulletin_stations(bulletins)
    print(f"Bulletins: {len(bulletins)}, naming {len(named)} stations "
          f"({len(set(named) - set(old))} not in the list)")

    wanted = sorted(set(old) | set(named))
    box = tuple(args.region) if args.region else region(old.values())
    services = [(url, url) for url in args.service] if args.service else SERVICES

    # code -> network -> epochs; a (network, station, start) already given by
    # an earlier service is not taken again from a later one.
    candidates: dict[str, dict[str, list[Epoch]]] = {}
    seen = set()
    reached = 0
    certificate_failures = 0
    for name, url in services:
        print(f"Asking {name} for the stations in lat {box[0]:.1f} to {box[1]:.1f}, "
              f"lon {box[2]:.1f} to {box[3]:.1f} ... ", end="", flush=True)
        try:
            epochs = fetch_epochs(url, box, name, args.timeout)
        except RuntimeError as exc:
            print(f"failed ({exc})")
            certificate_failures += "certificate" in str(exc)
            continue
        reached += 1
        print(f"{len(epochs)} station epochs")
        for e in epochs:
            key = (e.network, e.station, e.start)
            if key in seen:
                continue
            seen.add(key)
            candidates.setdefault(e.station, {}).setdefault(e.network, []).append(e)
    if certificate_failures == len(services):
        print("  No service's certificate could be verified, so this Python has no usable "
              "list of certificate authorities.\n  With Python from python.org on macOS, run "
              "'Install Certificates.command' in the Python folder; elsewhere, "
              "'pip install --upgrade certifi'.")
    elif certificate_failures:
        print("  A service whose certificate cannot be verified usually sends an incomplete "
              "certificate chain; the stations come from the other services.")
    if not reached:
        print("error: no station service could be reached; nothing was written",
              file=sys.stderr)
        return 1

    final: dict[str, tuple[float, float]] = {}
    unchanged, moved, shifted, added, kept, lost, notes = [], [], [], [], [], [], []
    for code in wanted:
        before = old.get(code)
        epoch, note = (None, "not found")
        if code in candidates:
            epoch, note = resolve(candidates[code], named.get(code, set()), before, args.date)
        if note and epoch is not None:
            notes.append(f"{code}: {note}")
        if epoch is None:
            reason = "" if note == "not found" else f" ({note})"
            if before is not None:
                final[code] = before
                kept.append(f"{code}{reason}")
            else:
                lost.append(f"{'/'.join(sorted(named.get(code, ''))) or '?'}.{code}{reason}")
            continue
        after = (round(epoch.lat, 4), round(epoch.lon, 4))
        final[code] = after
        if before is None:
            added.append(f"{epoch.network}.{code}")
        elif after == (round(before[0], 4), round(before[1], 4)):
            unchanged.append(code)
        else:
            distance = km(before, after)
            if distance > MOVED_KM:
                moved.append(f"{code} {distance:.1f} km")
            else:
                shifted.append(code)

    print(f"\n{len(final)} stations: {len(unchanged)} unchanged, "
          f"{len(shifted) + len(moved)} updated, {len(added)} added, "
          f"{len(kept)} kept as listed")
    if moved:
        print(f"  moved more than {MOVED_KM:g} km: " + ", ".join(moved))
    if shifted:
        print(f"  adjusted by up to {MOVED_KM:g} km: {len(shifted)}")
    if added:
        print("  added: " + ", ".join(added))
    if kept:
        print("  kept as listed (not found unless noted): " + ", ".join(kept))
    if lost:
        print("  named in bulletins but not found (unless noted), so not listed: " + ", ".join(lost))
    if notes:
        print("  notes: " + "; ".join(notes))
    if lost and not args.region:
        print("  (a station outside the region asked for is not found; widen it with --region)")

    if args.dry_run:
        print("\nDry run: nothing written.")
        return 0

    output = Path(args.output)
    today = dt.date.today().isoformat()
    header = f"# Last updated {today} from FDSN station services by authcat stup"
    if args.date:
        header += f"; positions valid on {args.date:%Y-%m-%d}"
    lines = [header] + [f"{code:<4} {lat:.4f} {lon:.4f}" for code, (lat, lon) in sorted(final.items())]
    if output.is_file():
        shutil.copyfile(output, output.with_name(output.name + ".bak"))
        print(f"\nPrevious {output.name} kept as {output.name}.bak")
    tmp = output.with_name(output.name + ".part")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, output)
    print(f"Wrote {shown(output)} ({len(final)} stations)"
          + ("; 'authcat sta' now uses it" if output.resolve() == local.resolve() else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
