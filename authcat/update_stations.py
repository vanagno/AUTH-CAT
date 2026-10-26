#!/usr/bin/env python3
"""Update the station list regd.sta from the FDSN station web services.

``authcat stup`` brings Utilities/regd.sta, the station list every project
uses (``authcat sta`` reads it), up to date with what the station services
publish, and keeps the previous list as Utilities/regd.sta.bak:

* every station in the list takes its most recent position;
* every station the services hold in the area -- Greece and its neighbours,
  lat 33.5 to 43.5, lon 18 to 31, unless --region gives another -- that is
  missing from the list is added.



Coordinates come from the FDSN station services
* every EIDA data centre -- NOA for the Greek networks (HL, HT, HP, HA, HC,
  HI), KOERI for the Turkish, RESIF, GFZ, INGV and the rest -- found through
  the EIDA routing service (ORFEUS, or GFZ as a backup);
* IRIS (service.iris.edu), for anything EIDA does not hold.

When no routing service answers, the EIDA federator (eida-federator.ethz.ch)
and NOA are asked instead.

The list holds station codes only, while the services name each station by
network and code, and the same code can be used by more than one network.
Permanent networks are preferred to temporary ones. among stations of the
same code at different places, a listed station takes the one nearest its
listed position, and a new one the most recent. A position more than FAR_KM
from the listed one is more likely another station with the same code than
a move, so it is reported and the listed line kept, unless --accept-far is
given.

Usage
-----
    authcat stup                            # update the list
    authcat stup --dry-run                  # show what would change, write nothing
    authcat stup --region 34 42 19 30       # add the missing stations of another area


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

from authcat.project import UTILITIES_DIR, shown

#: EIDA routing services: they say which data centre holds which network, so
#: each data centre can be asked directly.
ROUTING = [
    "https://www.orfeus-eu.org/eidaws/routing/1/query",
    "https://geofon.gfz-potsdam.de/eidaws/routing/1/query",
]
IRIS = ("IRIS", "https://service.iris.edu/fdsnws/station/1/query")
#: Asked when no routing service answers.
FALLBACK_SERVICES = [
    ("EIDA federator", "https://eida-federator.ethz.ch/fdsnws/station/1/query"),
    ("NOA", "https://eida.gein.noa.gr/fdsnws/station/1/query"),
    IRIS,
]
USER_AGENT = "authcat-stup (+https://github.com/vanagno/AUTH-CAT)"
STATION_FILE = "regd.sta"

#: The area whose missing stations are added, (minlat, maxlat, minlon,
#: maxlon): Greece and its neighbours.
DEFAULT_REGION = (33.5, 43.5, 18.0, 31.0)
#: Degrees added around the listed stations when asking for them, so that a
#: listed station outside the area is still looked up.
MARGIN = 0.1
#: IRIS's network of synthetic seismograms: never a real station.
SYNTHETIC_NETWORKS = {"SY"}

#: Positions further apart than this (km) are treated as different places.
MOVED_KM = 1.0
#: A service position further than this (km) from the listed one is kept out
#: unless --accept-far is given (see the module docstring).
FAR_KM = 10.0


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
# the station list and the area
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


def covering(area: tuple[float, float, float, float], positions,
             margin: float = MARGIN) -> tuple[float, float, float, float]:
    """The smallest ``(minlat, maxlat, minlon, maxlon)`` holding ``area`` and
    ``positions``, these widened by ``margin`` degrees."""
    lats = [area[0], area[1]] + [p[0] + d for p in positions for d in (-margin, margin)]
    lons = [area[2], area[3]] + [p[1] + d for p in positions for d in (-margin, margin)]
    return (max(min(lats), -90.0), min(max(lats), 90.0),
            max(min(lons), -180.0), min(max(lons), 180.0))


def inside(epoch: Epoch, area: tuple[float, float, float, float]) -> bool:
    return area[0] <= epoch.lat <= area[1] and area[2] <= epoch.lon <= area[3]


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


def eida_nodes(routing: list[str], timeout: float) -> list[tuple[str, str]]:
    """The station service of every EIDA data centre, as ``(label, url)``,
    from the first routing service that answers; [] when none does.

    The routing service's ``format=post`` answer lists each data centre's
    service URL on a line of its own, followed by the networks it holds.
    """
    for url in routing:
        request = urllib.request.Request(
            f"{url}?service=station&format=post", headers={"User-Agent": USER_AGENT}
        )
        try:
            with _open(request, timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            continue
        nodes = sorted({
            line.strip().split("?")[0]
            for line in text.splitlines()
            if line.strip().startswith(("http://", "https://"))
        })
        if nodes:
            return [(f"EIDA {urllib.parse.urlparse(n).hostname}", n) for n in nodes]
    return []


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


def _started(epoch: Epoch) -> dt.datetime:
    return epoch.start or dt.datetime.min


def is_temporary(network: str) -> bool:
    """FDSN temporary network codes start with a digit or X, Y or Z."""
    return network[:1].isdigit() or network[:1] in "XYZ"


def choose(by_network: dict[str, list[Epoch]],
           listed: tuple[float, float] | None) -> tuple[Epoch, str]:
    """Choose the position for one station code from its epochs in each
    network; ``listed`` is its position in the list, if it has one.

    Returns the chosen epoch and a note for the report ("" when the choice
    was plain).
    """
    permanent = [n for n in sorted(by_network) if not is_temporary(n)]
    networks = permanent or sorted(by_network)
    # each network's most recent epoch, the most recent first
    picks = sorted((max(by_network[n], key=_started) for n in networks),
                   key=_started, reverse=True)
    if len(picks) == 1:
        return picks[0], ""
    spread = max(km((a.lat, a.lon), (b.lat, b.lon)) for a in picks for b in picks)
    if spread <= MOVED_KM:
        return picks[0], ""  # the same site under each network
    nets = ", ".join(sorted(p.network for p in picks))
    if listed is not None:
        best = min(picks, key=lambda p: km((p.lat, p.lon), listed))
        return best, f"in {nets} at different places; took {best.network}, nearest the listed position"
    return picks[0], f"in {nets} at different places; took {picks[0].network}, the most recent"


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Update the station list Utilities/regd.sta, which every project "
        "uses, from the FDSN station services (the EIDA data centres and IRIS): the "
        "listed stations take their most recent positions, and the stations of the "
        "area missing from the list are added."
    )
    ap.add_argument("-o", "--output", default=None,
                    help="file to write instead of Utilities/regd.sta (which authcat sta uses)")
    ap.add_argument("--region", type=float, nargs=4,
                    metavar=("MINLAT", "MAXLAT", "MINLON", "MAXLON"),
                    help="area whose missing stations are added (default: Greece and its "
                         "neighbours, lat {:g} to {:g}, lon {:g} to {:g})".format(*DEFAULT_REGION))
    ap.add_argument("--accept-far", action="store_true",
                    help=f"take service positions more than {FAR_KM:g} km from the listed ones")
    ap.add_argument("--service", action="append", metavar="URL",
                    help="FDSN station service to ask instead of the EIDA data centres "
                         "and IRIS (repeatable)")
    ap.add_argument("--routing", action="append", metavar="URL",
                    help="EIDA routing service to find the data centres with "
                         "(repeatable; default: ORFEUS, then GFZ)")
    ap.add_argument("--timeout", type=float, default=180.0,
                    help="seconds to wait for each service")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would change and write nothing")
    args = ap.parse_args(argv)

    station_list = UTILITIES_DIR / STATION_FILE
    old = read_station_list(station_list)
    print(f"Station list: {len(old)} stations from Utilities/{STATION_FILE}")

    area = tuple(args.region) if args.region else DEFAULT_REGION
    box = covering(area, old.values())
    if args.service:
        services = [(url, url) for url in args.service]
    else:
        print("Asking the EIDA routing service for the data centres ... ", end="", flush=True)
        nodes = eida_nodes(args.routing or ROUTING, args.timeout)
        if nodes:
            print(f"{len(nodes)} found")
            services = nodes + [IRIS]
        else:
            print("no answer; asking the federator, NOA and IRIS instead")
            services = FALLBACK_SERVICES

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
            if e.network not in SYNTHETIC_NETWORKS:
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

    final: dict[str, tuple[float, float]] = dict(old)
    unchanged, moved, shifted, far, kept, notes = [], [], [], [], [], []
    added: dict[str, int] = {}  # network -> stations added
    small = unsure = 0
    for code in sorted(set(old) | set(candidates)):
        before = old.get(code)
        by_network = candidates.get(code, {})
        if before is None:
            # a new station: added when it lies in the area
            by_network = {n: in_area for n, epochs in by_network.items()
                          if (in_area := [e for e in epochs if inside(e, area)])}
            if not by_network:
                continue
            epoch, note = choose(by_network, None)
            final[code] = (round(epoch.lat, 4), round(epoch.lon, 4))
            added[epoch.network] = added.get(epoch.network, 0) + 1
            unsure += bool(note)
            continue
        if not by_network:
            kept.append(code)
            continue
        epoch, note = choose(by_network, before)
        if note:
            notes.append(f"{code}: {note}")
        after = (round(epoch.lat, 4), round(epoch.lon, 4))
        if after == (round(before[0], 4), round(before[1], 4)):
            unchanged.append(code)
            continue
        distance = km(before, after)
        if distance > FAR_KM and not args.accept_far:
            far.append(f"{epoch.network}.{code} {distance:.1f} km")
            continue
        final[code] = after
        if distance > MOVED_KM:
            moved.append(f"{epoch.network}.{code} {distance:.1f} km")
        else:
            shifted.append(code)
            small += distance < 0.1

    print(f"\n{len(final)} stations: {len(unchanged)} unchanged, "
          f"{len(shifted) + len(moved)} updated, {sum(added.values())} added, "
          f"{len(kept) + len(far)} kept as listed")
    if moved:
        print(f"  moved more than {MOVED_KM:g} km: " + ", ".join(moved))
    if shifted:
        print(f"  adjusted by up to {MOVED_KM:g} km: {len(shifted)} "
              f"({small} of them by less than 100 m)")
    if far:
        print(f"  more than {FAR_KM:g} km from the listed position, so probably another "
              "station with the same code -- kept as listed; check them, and use "
              "--accept-far to take them: " + ", ".join(far))
    if added:
        by_count = sorted(added.items(), key=lambda item: (-item[1], item[0]))
        print("  added, by network: " + ", ".join(f"{n} {count}" for n, count in by_count))
        if unsure:
            print(f"  the most recent station was taken for {unsure} added "
                  f"code{'s' if unsure != 1 else ''} used by more than one network "
                  "at different places")
    if kept:
        print("  not held by the services, so kept as listed: " + ", ".join(kept))
    if notes:
        print("  notes: " + "; ".join(notes))

    if args.dry_run:
        print("\nDry run: nothing written.")
        return 0

    output = Path(args.output) if args.output else station_list
    in_utilities = output.resolve() == station_list.resolve()
    label = f"Utilities/{STATION_FILE}" if in_utilities else shown(output)
    today = dt.date.today().isoformat()
    header = f"# Last updated {today} from FDSN station services by authcat stup"
    lines = [header] + [f"{code:<4} {lat:.4f} {lon:.4f}" for code, (lat, lon) in sorted(final.items())]
    backed_up = False
    try:
        if output.is_file():
            shutil.copyfile(output, output.with_name(output.name + ".bak"))
            backed_up = True
        tmp = output.with_name(output.name + ".part")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, output)
    except OSError as exc:
        print(f"error: cannot write {label} ({exc.strerror or exc}); "
              "use -o FILE to write the list elsewhere", file=sys.stderr)
        return 1
    if backed_up:
        print(f"\nPrevious list kept as {label}.bak")
    print(f"Wrote {label} ({len(final)} stations)"
          + ("; 'authcat sta' uses it" if in_utilities else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
