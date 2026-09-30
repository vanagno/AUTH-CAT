#!/usr/bin/env python3
"""Project folders and the project record for AUTH-CAT.

Each analysis lives in its own folder, so two runs never overwrite each other.
The folders are kept in Projects/ at the top of the repository, next to
authcat/, whatever folder the scripts are run from:

    Projects/<name>/
        <name>.json   the project record -- what every script found
        Input/        the bulletin
        Results/      catalogues, phase lists, summaries
        Figures/      plots
        Magnitudes/   station magnitude lists and their plot

``getbul.py`` creates the project when it downloads the bulletin. Every later
script asks which project to work on -- Enter picks the last one used -- reads
its input from that project's folders, writes its output there, and records
what it found in ``<name>.json``.

The record keeps the layout of ``TEMPLATE``. A section reads
``"available": false`` until the script that fills it has run, and
``history`` lists every run in order with its inputs, so the file is both the
project's diary and the input for a report. Paths in it are relative to the
project folder.

To start a project from a bulletin you already have rather than downloading
one::

    python project.py Arkal --bulletin Input/Arkal.bul

With no arguments it lists the projects. Standard library only.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

#: The scripts' own folder, authcat/. Projects and shared files are found
#: from here rather than from the working directory, so the scripts can be
#: run from any folder.
_SCRIPTS_DIR = Path(__file__).resolve().parent

PROJECTS_DIR = _SCRIPTS_DIR.parent / "Projects"
SUBDIRS = ("Input", "Results", "Figures", "Magnitudes")

#: Reference files shared by every project, such as the station list
#: regd.sta and the report logo.
UTILITIES_DIR = _SCRIPTS_DIR / "Utilities"

#: Holds the name of the last project used, which the prompt offers as default.
_CURRENT_FILE = ".current"
_NAME_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

TEMPLATE = {
    "schema_version": "1.1",
    "project": {
        "name": None,
        "created": None,
        "bulletin_file": None,
        "catalogue_file": None,
        "catalogue_6col_file": None,
        "catalogue_quakeml_file": None,
    },
    "bulletin": {
        "available": False,
        "source": None,
        "start_date": None,
        "end_date": None,
        "bounds": None,
        "events_examined": None,
        "events_written": None,
        "months_missing": [],
        "months_failed": [],
    },
    "catalogue": {
        "available": False,
        "total_events": None,
        "start_time": None,
        "end_time": None,
        "latitude_min": None,
        "latitude_max": None,
        "longitude_min": None,
        "longitude_max": None,
        "depth_min_km": None,
        "depth_max_km": None,
        "magnitude_min": None,
        "magnitude_max": None,
        "largest_event": {
            "time": None,
            "magnitude": None,
            "latitude": None,
            "longitude": None,
            "depth_km": None,
            "event_id": None,
        },
    },
    "magnitude_of_completeness": {
        "available": False,
        "maxc": {"mc": None, "b_value": None, "b_value_uncertainty": None},
        "gft": {
            "mc": None,
            "b_value": None,
            "b_value_uncertainty": None,
            "goodness_of_fit_percent": None,
        },
        "mbs": {"mc": None, "b_value": None, "b_value_uncertainty": None},
        "summary_file": None,
        "figures": {
            "fmd": None,
            "maxc": None,
            "gft_residuals": None,
            "gft": None,
            "mbs_stability": None,
            "mbs": None,
        },
    },
    "magnitude_regularization": {
        "available": False,
        "residual_threshold": None,
        "flagged_stations": [],
        "excluded_stations": [],
        "magnitudes_file": None,
        "modified_magnitudes_file": None,
        "modified_catalogue_file": None,
        "figure": None,
        "bland_altman": {
            "figure": None,
            "events": None,
            "mean_difference": None,
            "lower_limit": None,
            "upper_limit": None,
        },
    },
    "station_phases": {
        "available": False,
        "station_count": None,
        "missing_coordinate_station_count": None,
        "missing_coordinate_stations": [],
        "counts_file": None,
        "map_figure": None,
    },
    "phases": {
        "available": False,
        "hypodd": {"file": None, "events": None, "phases": None},
        "hypo71": {"file": None, "events": None, "phases": None},
        "selection": {"stations": [], "file": None, "events": None},
    },
    "wadati": {
        "available": False,
        "pairs": None,
        "vp_vs": {"least_squares": None, "orthogonal_regression": None},
        "figure": None,
    },
    "modified_omori": {
        "available": False,
        "fit_start": None,
        "fit_end": None,
        "start_time": None,
        "end_time": None,
        "magnitude_threshold": None,
        "events": None,
        "K": None,
        "c": None,
        "p": None,
        "mcmc": {
            "K": {"median": None, "p16": None, "p84": None},
            "c": {"median": None, "p16": None, "p84": None},
            "p": {"median": None, "p16": None, "p84": None},
        },
        "figure": None,
        "mcmc_figure": None,
        "fit_data_file": None,
    },
    "figures": {
        "epicentral_map": None,
        "histograms": None,
        "magnitude_time": None,
        "cumulative_events": None,
        "mc_time": None,
    },
    "history": [],
}


def _merge(base: dict, over: dict) -> dict:
    """``over`` laid onto ``base``, recursing into dicts that both have."""
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _plain(value):
    """Make ``value`` JSON-safe.

    numpy scalars become Python numbers, NaN and infinity become null (JSON
    has no spelling for them), sets become sorted lists and paths become text.
    """
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, set):
        return sorted(_plain(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, Path):
        return value.as_posix()
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()  # numpy scalar
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Project:
    """One project folder and its record."""

    def __init__(self, name: str, base: str | os.PathLike = PROJECTS_DIR):
        name = str(name).strip()
        if not _NAME_RX.match(name):
            raise ValueError(
                f"{name!r} is not a usable project name: use letters, digits, "
                f"'.', '_' or '-', starting with a letter or digit"
            )
        self.name = name
        self.base = Path(base)
        self.root = self.base / name

    @property
    def input_dir(self) -> Path:
        return self.root / "Input"

    @property
    def results_dir(self) -> Path:
        return self.root / "Results"

    @property
    def figures_dir(self) -> Path:
        return self.root / "Figures"

    @property
    def magnitudes_dir(self) -> Path:
        return self.root / "Magnitudes"

    @property
    def json_path(self) -> Path:
        return self.root / f"{self.name}.json"

    def create(self) -> "Project":
        """Make the folders, and the record if there is none yet."""
        for sub in SUBDIRS:
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        if not self.json_path.exists():
            record = copy.deepcopy(TEMPLATE)
            record["project"]["name"] = self.name
            record["project"]["created"] = _now()
            self._write(record)
        return self

    def load(self) -> dict:
        """The record, with any section it lacks filled in from ``TEMPLATE``."""
        record = copy.deepcopy(TEMPLATE)
        if self.json_path.exists():
            record = _merge(record, json.loads(self.json_path.read_text(encoding="utf-8")))
        return record

    def _write(self, record: dict) -> None:
        tmp = self.json_path.with_name(self.json_path.name + ".part")
        tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.json_path)

    def has_bulletin(self) -> bool:
        return self.json_path.exists() and bool(self.load()["project"]["bulletin_file"])

    def rel(self, path: str | os.PathLike) -> str:
        """``path`` as the record stores it: relative to the project folder
        when it is inside it, absolute otherwise."""
        full = Path(path).resolve()
        try:
            return full.relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return full.as_posix()

    def recorded_name(self, folder: str | os.PathLike, *keys: str) -> str | None:
        """Name of the file the record holds under ``keys``, e.g.
        ``("project", "catalogue_file")``, when that file is in ``folder`` and
        still exists. Scripts offer it as the default at their file prompts.
        """
        value = self.load()
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        if not value:
            return None
        path = (self.root / value).resolve()
        if path.parent != Path(folder).resolve() or not path.is_file():
            return None
        return path.name

    def update(self, script: str, sections: dict, **details) -> None:
        """Merge ``sections`` into the record and add a line to its history.

        ``sections`` maps a section name to the fields a script found, e.g.
        ``{"wadati": {"vp_vs": {...}, "figure": "Figures/Wadati.png"}}``.
        Sections that carry an ``available`` flag have it set. ``details``
        -- the input files and parameters of the run -- go in the history
        entry only.
        """
        record = self.load()
        for name, values in sections.items():
            values = _plain(values)
            current = record.get(name)
            if isinstance(current, dict) and isinstance(values, dict):
                if "available" in current:
                    values = {**values, "available": True}
                record[name] = _merge(current, values)
            else:
                record[name] = values
        entry = {"time": _now(), "script": script, "sections": list(sections)}
        if details:
            entry["details"] = _plain(details)
        record["history"].append(entry)
        self._write(record)
        # print(f"Results recorded in {shown(self.json_path)}")

    def make_current(self) -> None:
        """Offer this project as the default the next time a script asks."""
        self.base.mkdir(parents=True, exist_ok=True)
        (self.base / _CURRENT_FILE).write_text(self.name + "\n", encoding="utf-8")


def shown(path: str | os.PathLike) -> str:
    """``path`` as messages show it: from its project folder down, e.g.
    ``Figures/Wadati.png``. Paths outside every project are shown as given."""
    full = Path(path).resolve()
    try:
        parts = full.relative_to(PROJECTS_DIR.resolve()).parts
    except ValueError:
        return str(path)
    if len(parts) < 2:
        return f"{PROJECTS_DIR.name}/{'/'.join(parts)}"
    return Path(*parts[1:]).as_posix()


def ask_file_name(prompt: str, default: str | None) -> str:
    """Ask for a file name; Enter takes ``default`` when there is one.

    ``prompt`` is the question without its closing colon. Returns "" when
    nothing is entered and there is no default.
    """
    try:
        answer = input(f"{prompt} [blank = {default}]: " if default else f"{prompt}: ").strip()
    except EOFError:
        if default:
            return default
        raise SystemExit("\nerror: no file name given") from None
    return answer or (default or "")


def list_projects(base: str | os.PathLike = PROJECTS_DIR) -> list[str]:
    base = Path(base)
    if not base.is_dir():
        return []
    return sorted(
        p.name for p in base.iterdir() if p.is_dir() and (p / f"{p.name}.json").is_file()
    )


def current_project(base: str | os.PathLike = PROJECTS_DIR) -> str | None:
    """The last project used, if it still exists."""
    try:
        name = (Path(base) / _CURRENT_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return name if name in list_projects(base) else None


def _ask_project(base: Path) -> str:
    names = list_projects(base)
    if not names:
        raise SystemExit(f"error: no projects in {base}/ yet -- run getbul.py or project.py first")
    default = current_project(base) or (names[0] if len(names) == 1 else None)
    print("Projects:")
    for name in names:
        print(f"    {name}" + ("   (last used)" if name == default else ""))
    while True:
        prompt = f"Which project? [blank = {default}]: " if default else "Which project? "
        try:
            answer = input(prompt).strip()
        except EOFError:
            if default:
                return default
            raise SystemExit("\nerror: no project given") from None
        if not answer and default:
            return default
        if answer in names:
            return answer
        print(f"    there is no project called {answer!r} -- try again.")


def open_project(name: str | None = None, base: str | os.PathLike = PROJECTS_DIR) -> Project:
    """The existing project a script should work on.

    ``name`` -- from a ``--project`` option -- wins. Otherwise, at a terminal,
    the projects are listed and the user picks one, Enter taking the last one
    used. With no terminal, as when a batch script pipes in the answers, the
    last one used is taken without asking, so the piped answers still line up
    with the script's own questions.
    """
    base = Path(base)
    if name is None:
        name = _ask_project(base) if sys.stdin.isatty() else current_project(base)
        if name is None:
            raise SystemExit(
                "error: no project given and none used before -- run getbul.py or project.py first"
            )
    try:
        proj = Project(name, base)
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from None
    if not proj.json_path.is_file():
        raise SystemExit(
            f"error: there is no project {proj.name!r} in {base}/ -- "
            f"run getbul.py or project.py to create it"
        )
    proj.create()  # restores any subfolder deleted by hand
    proj.make_current()
    print(f"Project: {proj.name}  ({PROJECTS_DIR.name}/{proj.name}/)\n")
    return proj


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="List the AUTH-CAT projects, or start one from a bulletin you "
        "already have (getbul.py starts one by downloading the bulletin)."
    )
    ap.add_argument("name", nargs="?", help="name of the project to create")
    ap.add_argument("-b", "--bulletin", help="bulletin file to copy into the new project")
    args = ap.parse_args(argv)

    if args.name is None:
        names = list_projects()
        if not names:
            print(f"No projects in {PROJECTS_DIR}/ yet.")
            return 0
        last = current_project()
        for name in names:
            print(name + ("   (last used)" if name == last else ""))
        return 0

    if not args.bulletin:
        ap.error("pass --bulletin FILE to start a project from a bulletin you have, "
                 "or run getbul.py to download one")
    try:
        proj = Project(args.name)
    except ValueError as exc:
        ap.error(str(exc))
    if proj.has_bulletin():
        ap.error(f"project {proj.name} already has a bulletin ({proj.root}); choose another name")
    src = Path(args.bulletin)
    if not src.is_file():
        ap.error(f"{src} is not a file")

    proj.create()
    dest = proj.input_dir / src.name
    shutil.copyfile(src, dest)
    with open(dest, encoding="utf-8", errors="replace") as fh:
        n_events = sum(1 for line in fh if line.startswith("Event:"))
    print(f"Copied {src} ({n_events} events) to {shown(dest)}")
    proj.update(
        "project.py",
        {
            "project": {"bulletin_file": proj.rel(dest)},
            "bulletin": {"source": src.resolve().as_posix(), "events_written": n_events},
        },
    )
    proj.make_current()
    return 0


if __name__ == "__main__":
    sys.exit(main())
