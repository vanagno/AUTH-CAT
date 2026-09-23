"""Filter a phase list down to a chosen set of stations.

Reads either format written by ``phases.py`` and writes the same format back:

* **HypoDD** phase input (``phase.dat``) -- ``#`` event headers followed by
  fixed-column ``STA  TT  WGHT  PHA`` rows. Headers are carried through with
  their events.
* **HYPO71** phase list (``phases.txt``) -- events closed by a ``10`` terminator
  line.

The format is detected from the file, so the same answer to the same prompt
works for both. Phase counts per station are computed from the file being
filtered, which is what makes them consistent with the cut you are about to
make; coordinates are extracted from ``Results/station_phases_counts.txt``
(written by ``stations.py``) when it is present.
"""

from __future__ import annotations

import os
import re

HYPO71_TERMINATOR = "                 10"

#: A HypoDD phase row: station in the first 8 columns, phase label last.
_HYPODD_STA_WIDTH = 8

#: Matches the S remark at the end of a HYPO71 card, e.g. '... 16.53 S 2'.
_HYPO71_HAS_S = re.compile(r"\sS\s*\d*\s*$")


def detect_format(lines):
    """Return 'hypodd' or 'hypo71'.

    A ``#`` in the first column is unambiguous -- HYPO71 cards start with a
    station code. Absent that, a bare ``10`` terminator means HYPO71.
    """
    for line in lines:
        if line.startswith("#"):
            return "hypodd"
        if line.strip() == "10":
            return "hypo71"
    raise SystemExit(
        "error: cannot tell whether this is a HypoDD or HYPO71 phase list -- "
        "expected either '#' event headers or '10' event terminators"
    )


def split_events(lines, fmt):
    """Split into ``[(header_or_None, [phase_line, ...]), ...]``."""
    events = []
    header, phases = None, []

    if fmt == "hypodd":
        for line in lines:
            if line.startswith("#"):
                if phases or header is not None:
                    events.append((header, phases))
                header, phases = line, []
            elif line.strip():
                phases.append(line)
        if phases or header is not None:
            events.append((header, phases))
    else:
        for line in lines:
            if line.strip() == "10":
                if phases:
                    events.append((None, phases))
                phases = []
            elif line.strip():
                # Blank lines are dropped rather than carried into the filter,
                # where line.split()[0] on an empty line raises IndexError.
                phases.append(line)
        if phases:
            events.append((None, phases))
    return events


def station_of(line, fmt):
    """Station code for a phase line, upper-cased."""
    if fmt == "hypodd":
        return line[:_HYPODD_STA_WIDTH].strip().upper()
    # HYPO71 packs the code and the P remark into 6 columns: 'FSK EP', 'NYDREP'.
    code = line.split()[0].strip()
    if code.endswith("EP"):
        code = code[:-2].strip()
    return code.upper()


def count_phases(events, fmt):
    """Return ``{station: {'P': n, 'S': n}}`` counted from the phase lines."""
    counts = {}
    for _, phases in events:
        for line in phases:
            sta = station_of(line, fmt)
            row = counts.setdefault(sta, {"P": 0, "S": 0})
            if fmt == "hypodd":
                label = line.split()[-1].upper()
                row["S" if label.startswith("S") else "P"] += 1
            else:
                # One HYPO71 card carries a P and, when the S remark is present,
                # an S as well.
                row["P"] += 1
                if _HYPO71_HAS_S.search(line):
                    row["S"] += 1
    return counts


def read_station_coordinates(path):
    """Read ``{station: (lat, lon)}`` from stations.py's counts file.

    Layout is ``{station:5} {lat} {lon} {P:5} {S:5}``. Missing or unreadable is
    not an error -- the coordinates are decoration on the table.
    """
    coords = {}
    if not os.path.isfile(path):
        return coords
    with open(path) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 3:
                try:
                    coords[parts[0].upper()] = (float(parts[1]), float(parts[2]))
                except ValueError:
                    continue
    return coords


def print_counts_table(counts, coords, source):
    """Print phase counts per station under a column header.

    Sorted by P descending, matching the order stations.py writes.
    """
    order = sorted(counts.items(), key=lambda kv: (-kv[1]["P"], kv[0]))
    show_coords = any(sta in coords for sta in counts)

    print(f"\nPhases per station in {source}:\n")
    if show_coords:
        head = f"  {'STA':<6} {'LAT':>9} {'LON':>9} {'P':>7} {'S':>7} {'TOTAL':>8}"
        rule = f"  {'-' * 6} {'-' * 9} {'-' * 9} {'-' * 7} {'-' * 7} {'-' * 8}"
    else:
        head = f"  {'STA':<6} {'P':>7} {'S':>7} {'TOTAL':>8}"
        rule = f"  {'-' * 6} {'-' * 7} {'-' * 7} {'-' * 8}"
    print(head)
    print(rule)

    tot_p = tot_s = 0
    for sta, row in order:
        tot_p += row["P"]
        tot_s += row["S"]
        total = row["P"] + row["S"]
        if show_coords:
            lat, lon = coords.get(sta, (None, None))
            lat_s = f"{lat:9.4f}" if lat is not None else f"{'--':>9}"
            lon_s = f"{lon:9.4f}" if lon is not None else f"{'--':>9}"
            print(f"  {sta:<6} {lat_s} {lon_s} {row['P']:>7d} {row['S']:>7d} {total:>8d}")
        else:
            print(f"  {sta:<6} {row['P']:>7d} {row['S']:>7d} {total:>8d}")
    print(rule)

    # 'ALL' rather than '16 stations' so the totals stay under their columns.
    if show_coords:
        print(f"  {'ALL':<6} {'':>9} {'':>9} {tot_p:>7d} {tot_s:>7d} {tot_p + tot_s:>8d}")
    else:
        print(f"  {'ALL':<6} {tot_p:>7d} {tot_s:>7d} {tot_p + tot_s:>8d}")
    if show_coords and any(sta not in coords for sta in counts):
        missing = sorted(sta for sta in counts if sta not in coords)
        print(f"\n  no coordinates in station_phases_counts.txt for: {', '.join(missing)}")
    print()


def filter_events(events, keep, fmt):
    """Keep only phase lines from `keep`; drop events left with nothing."""
    out = []
    for header, phases in events:
        kept = [l for l in phases if station_of(l, fmt) in keep]
        if kept:
            out.append((header, kept))
    return out


def write_filtered_data(output_filename, filtered_data, fmt):
    os.makedirs(os.path.dirname(output_filename) or ".", exist_ok=True)
    with open(output_filename, "w") as file:
        for header, phases in filtered_data:
            if fmt == "hypodd" and header is not None:
                file.write(f"{header}\n")
            for line in phases:
                file.write(f"{line}\n")
            if fmt == "hypo71":
                file.write(f"{HYPO71_TERMINATOR}\n")


def read_and_filter_data(input_filename):
    with open(input_filename, "r") as file:
        lines = [l.rstrip("\r\n") for l in file]

    fmt = detect_format(lines)
    events = split_events(lines, fmt)
    counts = count_phases(events, fmt)
    n_lines = sum(len(p) for _, p in events)
    n_phases = sum(v["P"] + v["S"] for v in counts.values())
    if fmt == "hypodd":
        unit = "phase lines"
        print(f"\nRead {len(events)} events and {n_lines} phase lines from "
              f"{len(counts)} stations (HypoDD format)")
    else:
        # One HYPO71 card carries two phases, so the table totals more than the
        # line count it was derived from.
        unit = "cards"
        print(f"\nRead {len(events)} events and {n_lines} cards "
              f"({n_phases} P and S phases) from {len(counts)} stations "
              f"(HYPO71 format)")

    coords = read_station_coordinates(os.path.join("Results", "station_phases_counts.txt"))
    print_counts_table(counts, coords, input_filename)

    stations_input = input("Enter the station codes you want to keep (separated by commas): ")
    desired_stations = {station.strip().upper() for station in stations_input.split(",")}
    desired_stations.discard("")
    if not desired_stations:
        raise SystemExit("error: no station codes given")

    unknown = sorted(desired_stations - set(counts))
    if unknown:
        
        print(f"warning: not present in {input_filename}: {', '.join(unknown)}")

    filtered = filter_events(events, desired_stations, fmt)
    kept_lines = sum(len(p) for _, p in filtered)
    print(f"Kept {kept_lines} of {n_lines} {unit} in {len(filtered)} of "
          f"{len(events)} events")
    return filtered, fmt


def main():
    input_folder = "Results"
    if os.path.isdir(input_folder):
        print(f"{input_folder} folder:")
        for filename in os.listdir(input_folder):
            print(filename)
    else:
        print(f"The folder {input_folder} does not exist.")
    file_path = input("Please provide the phases list (should be phases.txt for HYPO71 or phase.dat for HYPODD formats if not renamed): ")
    input_file_path = os.path.join(input_folder, file_path)
    if not os.path.isfile(input_file_path):
        raise SystemExit(f"error: {input_file_path} not found")

    phase_data, fmt = read_and_filter_data(input_file_path)
    output = os.path.join("Results",
                          "phase_sel.dat" if fmt == "hypodd" else "phases_sel.txt")
    write_filtered_data(output, phase_data, fmt)
    print(f"Phase list has been successfully updated to {output}")


if __name__ == "__main__":
    main()
