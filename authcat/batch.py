#!/usr/bin/env python3
"""Run several steps of the workflow on a project in one go.

``authcat batch NAME`` runs the steps that need no expert judgement on the
project NAME, one after the other, without asking anything: each step gets
the answers it would ask for (the project's own files, and the parameters
given as options below), and its figures are saved without being shown. The
project must exist already; start it with ``authcat bul`` or
``authcat project``.

Usage
-----
    authcat batch Tyrnavos                          # the standard steps
    authcat batch Tyrnavos -s cat map hist mc       # only these steps
    authcat batch Tyrnavos --mc 2.5 --omori-start "2021-03-03 10:16:08"

Steps that need judgement are best run one by one: recomputing magnitudes
without some stations (authcat mags, then authcat rmag) and choosing the
stations whose phases to keep (authcat pse; in a batch it keeps the 20
stations with the most P phases unless --stations is given).
"""

from __future__ import annotations

import argparse
import codecs
import datetime as dt
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable

from authcat.project import PROJECTS_DIR, Project, list_projects

#: (step, script, what it does), in the order the steps run.
STEPS = [
    ("cat", "catalog", "catalogue in all formats"),
    ("map", "seismicity_map", "epicentral map"),
    ("hist", "histograms", "histograms"),
    ("mt", "M_time", "magnitudes over time"),
    ("mc", "Mc_analysis", "magnitude of completeness"),
    ("nt", "N_time", "cumulative number of events"),
    ("mct", "Mc_time", "Mc over time"),
    ("mags", "magnitudes", "station magnitude residuals (no recomputation)"),
    ("sta", "stations", "station map and phase counts"),
    ("pha", "phases", "phase lists"),
    ("pse", "sel_phases", "phase selection"),
    ("vpvs", "wadati", "Vp/Vs (Wadati)"),
    ("ou", "omori_utsu", "Omori-Utsu law"),
    ("rep", "report", "PDF report"),
]
#: Run when no --steps are given: all but the phase selection.
DEFAULT_STEPS = [name for name, _, _ in STEPS if name != "pse"]
MC_METHODS = ("maxc", "gft", "mbs")
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass
class Step:
    name: str
    script: str
    args: list[str]
    answers: list[str]


def _time(text: str) -> str:
    """Check a date and time the way omori_utsu.py reads them."""
    try:
        dt.datetime.strptime(text.strip(), TIME_FORMAT)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date and time {text!r}, expected "
                                         "YYYY-MM-DD HH:MM:SS") from None
    return text.strip()


def _mc(text: str) -> str:
    """An Mc: a number, or 'auto' for the one found by the mc step."""
    if text == "auto":
        return text
    try:
        float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid Mc {text!r}: a number or 'auto'") from None
    return text


def record(proj: Project) -> dict:
    with open(proj.json_path, encoding="utf-8") as fh:
        return json.load(fh)


def recorded_file(proj: Project, key: str) -> str | None:
    """The project file recorded under project/<key>, if it exists."""
    value = record(proj).get("project", {}).get(key)
    return value if value and (proj.root / value).is_file() else None


def found_mc(proj: Project, method: str) -> float | None:
    mc = record(proj).get("magnitude_of_completeness", {})
    if not mc.get("available"):
        return None
    return (mc.get(method) or {}).get("mc")


def resolve_mc(value: str, proj: Project, method: str) -> str:
    if value != "auto":
        return value
    mc = found_mc(proj, method)
    if mc is None:
        raise RuntimeError(f"no Mc ({method.upper()}) recorded yet: run the mc step first, "
                           "or give the Mc with --mc")
    return f"{mc:g}"


def plan(args: argparse.Namespace, proj: Project) -> dict[str, Callable[[], Step]]:
    """For each step, a function that builds it -- just before it runs, so it
    can use what the steps before it found (e.g. the Mc)."""

    def needs(key: str, what: str, step: str) -> None:
        if not recorded_file(proj, key):
            raise RuntimeError(f"the project has no {what} yet (run the {step} step first)")

    def bulletin_step(name: str, script: str, extra: list[str] | None = None) -> Callable[[], Step]:
        def build() -> Step:
            needs("bulletin_file", "bulletin", "authcat bul or authcat project")
            return Step(name, script, [], ["", *(extra or [])])
        return build

    def catalogue_step(name: str, script: str, key: str = "catalogue_file",
                       extra: Callable[[], list[str]] | None = None) -> Callable[[], Step]:
        def build() -> Step:
            needs(key, "catalogue", "cat")
            return Step(name, script, [], ["", *(extra() if extra else [])])
        return build

    def phases_selection() -> Step:
        fmt = "phase.dat" if args.phases == "hypodd" else "phases.txt"
        if not (proj.results_dir / fmt).is_file():
            raise RuntimeError(f"the project has no {fmt} yet (run the pha step first)")
        return Step("pse", "sel_phases", [], [fmt, args.stations])

    def omori_answers() -> list[str]:
        if args.omori_start == "catalogue":
            start = ["1"]
        elif args.omori_start == "largest":
            start = ["2"]
        else:
            start = ["3", args.omori_start]
        mc = "" if args.omori_mc == "all" else resolve_mc(args.omori_mc, proj, args.mc_method)
        return [*start, args.omori_end or "", mc]

    return {
        "cat": lambda: (needs("bulletin_file", "bulletin", "authcat bul or authcat project")
                        or Step("cat", "catalog", ["-p", proj.name, "-f", "all"], [])),
        "map": catalogue_step("map", "seismicity_map"),
        "hist": catalogue_step("hist", "histograms"),
        "mt": catalogue_step("mt", "M_time"),
        "mc": catalogue_step("mc", "Mc_analysis", "catalogue_6col_file"),
        "nt": catalogue_step("nt", "N_time", "catalogue_6col_file",
                             lambda: [resolve_mc(args.mc, proj, args.mc_method)]),
        "mct": catalogue_step("mct", "Mc_time",
                              extra=lambda: [str(args.mc_window), str(args.mc_filter)]),
        "mags": bulletin_step("mags", "magnitudes", ["no"]),
        "sta": bulletin_step("sta", "stations"),
        "pha": lambda: (needs("bulletin_file", "bulletin", "authcat bul or authcat project")
                        or Step("pha", "phases", ["-p", proj.name, "-f", args.phases], [""])),
        "pse": phases_selection,
        "vpvs": bulletin_step("vpvs", "wadati"),
        "ou": catalogue_step("ou", "omori_utsu", extra=omori_answers),
        "rep": lambda: Step("rep", "report", ["-p", proj.name], []),
    }


def run(step: Step) -> int:
    """Run one step as its own process, answers piped in, figures saved but
    not shown. Its output is passed on as it comes."""
    env = dict(os.environ, MPLBACKEND="Agg", PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", f"authcat.{step.script}", *step.args],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, env=env)
    proc.stdin.write("".join(a + "\n" for a in step.answers).encode())
    proc.stdin.close()
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    last = b"\n"
    while chunk := proc.stdout.read1(4096):
        sys.stdout.write(decoder.decode(chunk))
        sys.stdout.flush()
        last = chunk[-1:]
    if last != b"\n":  # the last line was a question answered from the pipe
        print()
    return proc.wait()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="authcat batch",
        description="Run several steps of the workflow on a project in one go, without "
        "questions; figures are saved, not shown. Steps: "
        + ", ".join(f"{name} ({text})" for name, _, text in STEPS) + ".",
    )
    ap.add_argument("project", help="the project to work on (it must exist already)")
    ap.add_argument("-s", "--steps", nargs="+", metavar="STEP",
                    choices=[name for name, _, _ in STEPS],
                    help="the steps to run, in the order above whatever the order given "
                         f"(default: {' '.join(DEFAULT_STEPS)})")
    ap.add_argument("--mc", type=_mc, default="auto",
                    help="Mc for the cumulative number of events (nt): a magnitude, or 'auto' "
                         "for the one found by the mc step (default)")
    ap.add_argument("--mc-method", choices=MC_METHODS, default="maxc",
                    help="which Mc of the mc step 'auto' takes (default: maxc)")
    ap.add_argument("--mc-window", type=int, default=100, metavar="N",
                    help="events in each window of the Mc over time (mct; default: 100)")
    ap.add_argument("--mc-filter", type=int, default=50, metavar="N",
                    help="events in the smoothing filter of the Mc over time (mct; default: 50)")
    ap.add_argument("--phases", choices=("hypo71", "hypodd", "both"), default="both",
                    help="phase list format(s) (pha; default: both); pse uses HypoDD only "
                         "when this is hypodd")
    ap.add_argument("--stations", default="", metavar="STA,STA,...",
                    help="stations whose phases to keep (pse; default: the 20 with the most "
                         "P phases)")
    ap.add_argument("--omori-start", default="largest", metavar="START",
                    help="start of the sequence (ou): 'largest' (the largest earthquake; "
                         "default), 'catalogue' (its first event) or 'YYYY-MM-DD HH:MM:SS'")
    ap.add_argument("--omori-end", type=_time, default=None, metavar="'YYYY-MM-DD HH:MM:SS'",
                    help="end of the sequence (ou; default: the end of the catalogue)")
    ap.add_argument("--omori-mc", type=lambda s: s if s == "all" else _mc(s), default="all",
                    help="magnitude threshold (ou): a magnitude, 'auto' for the Mc of the mc "
                         "step, or 'all' (default)")
    args = ap.parse_args(argv)
    if args.omori_start not in ("largest", "catalogue"):
        try:
            args.omori_start = _time(args.omori_start)
        except argparse.ArgumentTypeError as exc:
            ap.error(f"argument --omori-start: {exc}")
    if args.mc_window < 2 or args.mc_filter < 1:
        ap.error("--mc-window must be at least 2 and --mc-filter at least 1")

    if args.project not in list_projects():
        ap.error(f"there is no project {args.project!r} in {PROJECTS_DIR}/ -- "
                 "start it with 'authcat bul' or 'authcat project'")
    proj = Project(args.project)
    proj.make_current()  # the steps that ask for the project take the current one
    chosen = set(args.steps or DEFAULT_STEPS)
    order = [name for name, _, _ in STEPS if name in chosen]
    builders = plan(args, proj)
    texts = {name: text for name, _, text in STEPS}

    print(f"Batch on project {proj.name}: {' '.join(order)}\n")
    results = []
    for name in order:
        print(f"=== authcat {name}: {texts[name]} " + "=" * max(3, 50 - len(name) - len(texts[name])))
        started = time.monotonic()
        try:
            step = builders[name]()
        except RuntimeError as exc:
            print(f"skipped: {exc}\n")
            results.append((name, "skipped"))
            continue
        code = run(step)
        took = time.monotonic() - started
        results.append((name, "ok" if code == 0 else f"failed (exit {code})"))
        print(f"--- {name}: {'done' if code == 0 else 'FAILED'} in {took:.0f} s\n")

    failed = [f"{name} {status}" for name, status in results if status != "ok"]
    print(f"Batch finished: {len(results) - len(failed)} of {len(results)} steps done"
          + (f"; not done: {', '.join(failed)}" if failed else "."))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
