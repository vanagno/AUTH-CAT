"""The ``authcat`` command.

    authcat <command> [options]

Each command runs one step of the workflow -- one script of this package --
exactly as ``python -m authcat.<script>`` would. ``authcat`` on its own, or
``authcat --help``, lists the commands.
"""

from __future__ import annotations

import difflib
import runpy
import sys

from authcat import __version__

#: (names, script, has options of its own, description). The first name is
#: the one listed; any others are aliases. The script's own name works too.
COMMANDS = [
    (("bul",), "bulletin", True, "Download the earthquake bulletin from AUTH-SS"),
    (("cat",), "catalog", True,
     "Create the earthquake catalogue from the bulletin; transform into 6-column & XML"),
    (("map",), "seismicity_map", False, "Plot the epicenters in the catalogue"),
    (("hist",), "histograms", False,
     "Plot histograms of focal depths, magnitudes, RMS and azimuthal gaps"),
    (("mt",), "M_time", False, "Plot the magnitudes over time"),
    (("cum", "nt"), "N_time", False, "Plot the cumulative number of earthquakes over time"),
    (("mct",), "Mc_time", False, "Plot the Mc variations over time"),
    (("mc",), "Mc_analysis", False, "Determine the Mc of the earthquake dataset"),
    (("mags",), "magnitudes", False, "Plot the median residual of magnitudes for each station"),
    (("rmag",), "repmags", False, "Replace the initial magnitude estimations"),
    (("sta",), "stations", False,
     "Visualize the seismic stations with the number of picked phases"),
    (("pha",), "phases", True, "Extract seismic phases from the bulletin"),
    (("pse",), "sel_phases", False, "Select only the phases from certain seismic stations"),
    (("vpvs", "wad"), "wadati", False, "Vp/Vs estimation through the Wadati method"),
    (("ou",), "omori_utsu", False, "Estimation of the modified Omori law (MOL) parameters"),
    (("rep",), "report", True, "Generate the project report"),
    (("project",), "project", True,
     "List the projects, or start one from a bulletin you already have"),
]


def _usage() -> str:
    labels = [", ".join(names) for names, *_ in COMMANDS]
    width = max(map(len, labels)) + 3
    lines = [
        "usage: authcat <command> [options]",
        "",
        f"AUTH-CAT {__version__} -- each command runs one step of the workflow.",
        "Projects are kept in Projects/ in the folder you run authcat from.",
        "",
        "commands:",
    ]
    lines += [f"  {label:<{width}}{text}" for label, (*_, text) in zip(labels, COMMANDS)]
    lines += [
        "",
        'Run "authcat <command> -h" for a command\'s own options, where it has any.',
    ]
    return "\n".join(lines)


def _lookup() -> dict[str, tuple]:
    table = {}
    for names, script, options, text in COMMANDS:
        for name in (*names, script, script.lower()):
            table[name] = (names[0], script, options, text)
    return table


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if not args:
        print(_usage())
        return 2
    if args[0] in ("-h", "--help", "help"):
        print(_usage())
        return 0
    if args[0] in ("-V", "--version"):
        print(f"authcat {__version__}")
        return 0

    table = _lookup()
    name, rest = args[0], args[1:]
    entry = table.get(name) or table.get(name.lower())
    if entry is None:
        close = difflib.get_close_matches(name, list(table), n=3)
        hint = f" -- did you mean {' or '.join(close)}?" if close else ""
        print(f"authcat: unknown command {name!r}{hint}", file=sys.stderr)
        print('Run "authcat --help" for the list of commands.', file=sys.stderr)
        return 2

    shown, script, options, text = entry
    if not options and rest:
        # These scripts ask their questions as they go and read no options.
        if rest[0] in ("-h", "--help"):
            print(f"usage: authcat {shown}\n\n{text}.\n"
                  "It takes no options: it asks its questions as it goes.")
            return 0
        print(f"authcat {shown}: takes no options (it asks its questions as it goes)",
              file=sys.stderr)
        return 2

    # The script sees itself as "authcat <command>", e.g. in its usage text.
    sys.argv = [f"authcat {shown}", *rest]
    try:
        runpy.run_module(f"authcat.{script}", run_name="__main__")
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
