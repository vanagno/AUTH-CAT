#!/usr/bin/env python3
"""
Download monthly earthquake bulletins from the Seismological Station of the
Aristotle University of Thessaloniki (AUTH), optionally filter individual events
by exact date and geographic bounds, and merge the matching event blocks into a
single .bul file.

Monthly source files live at:
    https://seismo.auth.gr/wp-content/uploads/CATALOGS/<YYYY>/<YYYY>_<MM>.bul

Filtering is based on the fields in each event's Origin section:
    Date, Time, Latitude, Longitude

Matching event blocks are copied as raw bytes (apart from normalising line
endings to \n), so the complete original event content is retained.

This is the first step of an analysis: it asks for a project name and creates
Projects/<name>/ (see project.py), puts the bulletin in its Input folder and
starts the project record, Projects/<name>/<name>.json. Every later script
works inside that project.

Standard library only (Python 3.8+).
"""

import argparse
import calendar
import datetime as dt
import os
import re
import sys
import time
import urllib.error
import urllib.request

from project import Project, shown

DEFAULT_BASE_URL = "https://seismo.auth.gr/wp-content/uploads/CATALOGS"
USER_AGENT = "auth-bulletin-downloader/2.0 (+python-urllib)"
FIRST_AVAILABLE = (1999, 1)

EVENT_START_RE = re.compile(br"(?m)^Event:\s*$")
DATE_RE = re.compile(br"(?m)^\s*Date\s+(\d{4}-\d{2}-\d{2})\s*$")
TIME_RE = re.compile(br"(?m)^\s*Time\s+([0-9:.]+)\s*$")
LAT_RE = re.compile(br"(?m)^\s*Latitude\s+([-+]?\d+(?:\.\d+)?)\s+deg\b")
LON_RE = re.compile(br"(?m)^\s*Longitude\s+([-+]?\d+(?:\.\d+)?)\s+deg\b")


def parse_date(text):
    """Parse a date. Accepted forms: YYYY-MM-DD, YYYY/MM/DD, YYYY_MM_DD."""
    cleaned = text.strip().replace("/", "-").replace("_", "-")
    try:
        return dt.datetime.strptime(cleaned, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            "invalid date %r, expected YYYY-MM-DD (e.g. 2025-03-17)" % text
        )


def ask_date(prompt, default=None):
    """Ask until a valid date is entered. Blank accepts default when provided."""
    while True:
        try:
            answer = input(prompt).strip()
        except EOFError:
            raise SystemExit("\nNo input available; pass --start/--end instead.")
        if not answer and default is not None:
            return default
        try:
            return parse_date(answer)
        except argparse.ArgumentTypeError as exc:
            print("  " + str(exc))


def ask_float(prompt):
    while True:
        try:
            answer = input(prompt).strip()
        except EOFError:
            raise SystemExit("\nNo input available; pass geographic limits as arguments.")
        try:
            return float(answer)
        except ValueError:
            print("  Please enter a number.")


def ask_yes_no(prompt, default=False):
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        try:
            answer = input(prompt + suffix).strip().lower()
        except EOFError:
            return default
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Please answer y or n.")


def month_range_for_dates(start_date, end_date):
    """Yield (year, month) covering the inclusive date range."""
    year, month = start_date.year, start_date.month
    end = (end_date.year, end_date.month)
    while (year, month) <= end:
        yield year, month
        month += 1
        if month > 12:
            year, month = year + 1, 1


def build_url(base_url, year, month, arrive=False):
    suffix = "arrive" if arrive else ""
    return "%s/%d/%d_%02d%s.bul" % (base_url.rstrip("/"), year, year, month, suffix)


def fetch(url, retries, timeout, backoff=2.0):
    """Return bytes, None when unavailable, or raise RuntimeError after retries."""
    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404, 410):
                return None
            last_error = "HTTP %d" % exc.code
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = str(getattr(exc, "reason", exc))
        if attempt < retries:
            time.sleep(backoff ** attempt)
    raise RuntimeError("%s (%s)" % (url, last_error))


def normalise(data):
    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if data and not data.endswith(b"\n"):
        data += b"\n"
    return data


def looks_like_html(data):
    head = data[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def split_event_blocks(data):
    """Return complete Event: blocks from one bulletin as byte strings."""
    matches = list(EVENT_START_RE.finditer(data))
    if not matches:
        return []
    blocks = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(data)
        block = data[start:end]
        if block and not block.endswith(b"\n"):
            block += b"\n"
        blocks.append(block)
    return blocks


def parse_event_metadata(block):
    """Extract event origin date/time/latitude/longitude from an Event block."""
    dm = DATE_RE.search(block)
    tm = TIME_RE.search(block)
    latm = LAT_RE.search(block)
    lonm = LON_RE.search(block)
    if not (dm and latm and lonm):
        return None

    try:
        event_date = dt.datetime.strptime(dm.group(1).decode("ascii"), "%Y-%m-%d").date()
        latitude = float(latm.group(1))
        longitude = float(lonm.group(1))
    except (ValueError, UnicodeDecodeError):
        return None

    event_time = tm.group(1).decode("ascii") if tm else None
    return {
        "date": event_date,
        "time": event_time,
        "latitude": latitude,
        "longitude": longitude,
    }


def event_matches(meta, start_date, end_date, bbox=None):
    if meta is None:
        return False
    if not (start_date <= meta["date"] <= end_date):
        return False
    if bbox is not None:
        min_lat, max_lat, min_lon, max_lon = bbox
        if not (min_lat <= meta["latitude"] <= max_lat):
            return False
        if not (min_lon <= meta["longitude"] <= max_lon):
            return False
    return True


def validate_bbox(parser, args):
    values = [args.min_lat, args.max_lat, args.min_lon, args.max_lon]
    supplied = [v is not None for v in values]
    if any(supplied) and not all(supplied):
        parser.error("geographic filtering requires all four: --min-lat --max-lat --min-lon --max-lon")
    if all(supplied):
        if not (-90 <= args.min_lat <= 90 and -90 <= args.max_lat <= 90):
            parser.error("latitude limits must be between -90 and 90")
        if not (-180 <= args.min_lon <= 180 and -180 <= args.max_lon <= 180):
            parser.error("longitude limits must be between -180 and 180")
        if args.min_lat > args.max_lat:
            parser.error("--min-lat must not exceed --max-lat")
        if args.min_lon > args.max_lon:
            parser.error("--min-lon must not exceed --max-lon")
        return (args.min_lat, args.max_lat, args.min_lon, args.max_lon)
    return None


def choose_project(parser, name, interactive):
    """Return the new project to download into, asking again at a terminal.

    A name already holding a bulletin is refused, so every download starts a
    distinct project. One left without a bulletin -- by a download that found
    nothing -- can be reused.
    """
    if name is None and not interactive:
        parser.error("--project is required when not run interactively")
    if name is None:
        print("Each analysis is kept in its own project folder, Projects/<name>/.")
    while True:
        if name is None:
            try:
                name = input("Project name: ").strip()
            except EOFError:
                raise SystemExit("\nNo input available; pass --project instead.")
        try:
            proj = Project(name)
            if proj.has_bulletin():
                raise ValueError("project %r already has a bulletin (%s); choose another name"
                                 % (proj.name, proj.root))
        except ValueError as exc:
            if not interactive:
                parser.error(str(exc))
            print("  " + str(exc))
            name = None
            continue
        return proj


def main(argv=None):
    today = dt.date.today()
    parser = argparse.ArgumentParser(
        description="Download AUTH earthquake bulletins, filter events by exact date and optional geographic bounds, and merge matching events.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--start", type=parse_date, default=None, metavar="YYYY-MM-DD",
                        help="first event date to include (inclusive)")
    parser.add_argument("--end", type=parse_date, default=None, metavar="YYYY-MM-DD",
                        help="last event date to include (inclusive)")
    parser.add_argument("-p", "--project", default=None,
                        help="project name: everything for this analysis goes in "
                             "Projects/<name>/ (asked interactively if omitted)")
    parser.add_argument("-o", "--output", default=None,
                        help="bulletin filename inside the project's Input folder "
                             "(asked interactively if omitted; default <project>.bul)")
    parser.add_argument("--min-lat", type=float, default=None)
    parser.add_argument("--max-lat", type=float, default=None)
    parser.add_argument("--min-lon", type=float, default=None)
    parser.add_argument("--max-lon", type=float, default=None)
    parser.add_argument("--cache-dir", metavar="DIR",
                        help="save each monthly source file here and reuse it later")
    parser.add_argument("--refresh", action="store_true",
                        help="with --cache-dir: re-download even if cached")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help="base URL of the AUTH CATALOGS directory")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="seconds to wait between requests")
    parser.add_argument("--retries", type=int, default=3,
                        help="retries per file on transient errors")
    parser.add_argument("--timeout", type=float, default=60.0,
                        help="per-request timeout in seconds")
    args = parser.parse_args(argv)

    interactive = sys.stdin.isatty()

    proj = choose_project(parser, args.project, interactive)

    if args.start is None:
        if not interactive:
            parser.error("--start is required when not run interactively")
        print("AUTH publishes monthly files, but individual events can be filtered by exact day.")
        print("Enter dates as YYYY-MM-DD.\n")
        args.start = ask_date("Start date: ")

    if args.end is None:
        if not interactive:
            parser.error("--end is required when not run interactively")
        while True:
            args.end = ask_date("End date [blank = %s]: " % today.isoformat(), default=today)
            if args.end >= args.start:
                break
            print("  End date must not be before the start date.")

    if args.start > args.end:
        parser.error("--start must not be later than --end")

    bbox = validate_bbox(parser, args)
    if bbox is None and interactive:
        if ask_yes_no("Apply geographic limits?", default=False):
            min_lat = ask_float("Minimum latitude: ")
            max_lat = ask_float("Maximum latitude: ")
            min_lon = ask_float("Minimum longitude: ")
            max_lon = ask_float("Maximum longitude: ")
            if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
                parser.error("latitude limits must be between -90 and 90")
            if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
                parser.error("longitude limits must be between -180 and 180")
            if min_lat > max_lat or min_lon > max_lon:
                parser.error("minimum geographic limits must not exceed maximum limits")
            bbox = (min_lat, max_lat, min_lon, max_lon)

    suggested = proj.name + ".bul"
    if args.output is None:
        if interactive:
            try:
                answer = input("Bulletin filename [blank = %s]: " % suggested).strip()
            except EOFError:
                answer = ""
            args.output = answer or suggested
        else:
            args.output = suggested

    if not os.path.splitext(args.output)[1]:
        args.output += ".bul"
    proj.create()
    args.output = str(proj.input_dir / os.path.basename(args.output))

    if (args.start.year, args.start.month) < FIRST_AVAILABLE:
        print("note: the site lists bulletins from %d-%02d onwards; earlier months will be reported as missing." % FIRST_AVAILABLE,
              file=sys.stderr)

    if args.cache_dir:
        os.makedirs(args.cache_dir, exist_ok=True)

    months = list(month_range_for_dates(args.start, args.end))
    total = len(months)
    downloaded = cached = 0
    missing, failed = [], []
    events_examined = 0
    events_in_date = 0
    events_written = 0
    malformed_events = 0
    out_tmp = args.output + ".part"
    n_bytes = 0

    with open(out_tmp, "wb") as out:
        for done, (year, month) in enumerate(months, start=1):
            url = build_url(args.base_url, year, month)
            name = url.rsplit("/", 1)[-1]
            label = "[%d/%d] %s" % (done, total, name)
            cache_path = os.path.join(args.cache_dir, name) if args.cache_dir else None
            data = None
            from_cache = False

            if cache_path and not args.refresh and os.path.exists(cache_path):
                with open(cache_path, "rb") as fh:
                    data = fh.read()
                from_cache = True

            if data is None:
                try:
                    data = fetch(url, args.retries, args.timeout)
                except RuntimeError as exc:
                    print("%s  FAILED: %s" % (label, exc), file=sys.stderr)
                    failed.append(name)
                    time.sleep(args.delay)
                    continue
                time.sleep(args.delay)

            if data is None or not data.strip():
                print("%s  not available (skipped)" % label)
                missing.append(name)
                continue
            if looks_like_html(data):
                print("%s  got an HTML page instead of a bulletin (skipped)" % label, file=sys.stderr)
                missing.append(name)
                continue

            if from_cache:
                cached += 1
            else:
                downloaded += 1
                if cache_path:
                    with open(cache_path, "wb") as fh:
                        fh.write(data)

            data = normalise(data)
            blocks = split_event_blocks(data)
            matched_this_file = 0

            if not blocks:
                print("%s  no Event blocks found (skipped)" % label, file=sys.stderr)
                continue

            for block in blocks:
                events_examined += 1
                meta = parse_event_metadata(block)
                if meta is None:
                    malformed_events += 1
                    continue
                if args.start <= meta["date"] <= args.end:
                    events_in_date += 1
                if event_matches(meta, args.start, args.end, bbox):
                    out.write(block)
                    if not block.endswith(b"\n"):
                        out.write(b"\n")
                    n_bytes += len(block)
                    events_written += 1
                    matched_this_file += 1

            source = "cache" if from_cache else "downloaded"
            print("%s  ok (%s; %d events matched)" % (label, source, matched_this_file))

    if n_bytes == 0:
        try:
            os.remove(out_tmp)
        except OSError:
            pass
        print("\nNo matching event data found; nothing written.", file=sys.stderr)
        print("  events examined: %d" % events_examined)
        print("  events in date range: %d" % events_in_date)
        if bbox is not None:
            print("  geographic bounds: lat %.5f..%.5f, lon %.5f..%.5f" % bbox)
        if malformed_events:
            print("  events skipped because metadata could not be parsed: %d" % malformed_events)
        return 1 if failed else 0

    os.replace(out_tmp, args.output)

    print("\nWrote %s (%d bytes)" % (shown(args.output), n_bytes))
    print("  monthly files: downloaded %d   from cache %d   missing %d   failed %d"
          % (downloaded, cached, len(missing), len(failed)))
    print("  events examined: %d" % events_examined)
    print("  events in date range: %d" % events_in_date)
    if bbox is not None:
        print("  geographic bounds: lat %.5f..%.5f, lon %.5f..%.5f" % bbox)
    print("  events written: %d" % events_written)
    if malformed_events:
        print("  warning: %d event(s) skipped because Date/Latitude/Longitude could not be parsed" % malformed_events,
              file=sys.stderr)
    if missing:
        print("  not available: " + ", ".join(missing))
    if failed:
        print("  FAILED (re-run to retry): " + ", ".join(failed), file=sys.stderr)

    bounds = None
    if bbox is not None:
        bounds = dict(zip(("latitude_min", "latitude_max", "longitude_min", "longitude_max"), bbox))
    proj.update(
        "bulletin.py",
        {
            "project": {"bulletin_file": proj.rel(args.output)},
            "bulletin": {
                "source": args.base_url,
                "start_date": args.start.isoformat(),
                "end_date": args.end.isoformat(),
                "bounds": bounds,
                "events_examined": events_examined,
                "events_written": events_written,
                "months_missing": missing,
                "months_failed": failed,
            },
        },
    )
    proj.make_current()

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())