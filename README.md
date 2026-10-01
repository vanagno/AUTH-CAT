# AUTH-CAT

A Python toolkit for exploring and analysing earthquake bulletins from the
Seismological Station of the Aristotle University of Thessaloniki (AUTH-SS).

## Installation

```
pip install authcat                                          # from PyPI, once published
pip install git+https://github.com/vanagno/AUTH-CAT@working  # straight from GitHub
```

This installs the `authcat` command and everything it needs. For working on
AUTH-CAT itself, install your copy of the repository in editable mode, so code
changes take effect without reinstalling:

```
pip install -e .
```

## Commands

Each step of the workflow is a command: `authcat <command>`.
`authcat --help` lists them, and `authcat <command> -h` shows a command's own
options, where it has any.

| Command | Script | Description |
|---|---|---|
| `bul` | `bulletin.py` | Download the earthquake bulletin from AUTH-SS |
| `cat` | `catalog.py` | Create the earthquake catalogue from the bulletin; transform into 6-column & XML |
| `map` | `seismicity_map.py` | Plot the epicenters in the catalogue |
| `hist` | `histograms.py` | Plot histograms of focal depths, magnitudes, RMS and azimuthal gaps |
| `mt` | `M_time.py` | Plot the magnitudes over time |
| `nt` | `N_time.py` | Plot the cumulative number of earthquakes over time |
| `mct` | `Mc_time.py` | Plot the Mc variations over time |
| `mc` | `Mc_analysis.py` | Determine the Mc of the earthquake dataset |
| `mags` | `magnitudes.py` | Plot the median residual of magnitudes for each station |
| `rmag` | `repmags.py` | Replace the initial magnitude estimations |
| `sta` | `stations.py` | Visualize the seismic stations with the number of picked phases |
| `stup` | `update_stations.py` | Update the station list regd.sta from the FDSN station services |
| `pha` | `phases.py` | Extract seismic phases from the bulletin |
| `pse` | `sel_phases.py` | Select only the phases from certain seismic stations |
| `vpvs` | `wadati.py` | Vp/Vs estimation through the Wadati method |
| `ou` | `omori_utsu.py` | Estimation of the modified Omori law (MOL) parameters |
| `rep` | `report.py` | Generate the project report |
| `project` | `project.py` | List the projects, or start one from a bulletin you already have |

`python -m authcat <command>` works the same way, and the script names work as
commands too (e.g. `authcat histograms`).

## Projects

Every analysis session is kept in its own project folder, so runs never overwrite each
other. The project folders live in `Projects/` inside the folder you run `authcat`
from, so each working folder keeps its own projects; set the `AUTHCAT_PROJECTS`
environment variable to keep them in one folder elsewhere. The example projects
in this repository are found when `authcat` is run from its top folder.

```
Projects/<name>/
    <name>.json   project record: the results of every script, and a history of runs. Acts as a diary for the whole workflow
    Input/        where the bulletin is stored
    Results/      catalogues, phase lists, summaries all outputs from AUTH-CAT scripts
    Figures/      plots and maps
    Magnitudes/   station magnitude lists and their plots
    Reports/      the PDF report written by authcat rep
```

Reference files shared by every project, such as the station list
`regd.sta` and the report logo `LOGO.png`, are installed with AUTH-CAT
(`authcat/Utilities/`). `authcat stup` keeps the station list up to date: it
looks up the stations in the list and in your projects' bulletins in the FDSN
station services (every EIDA data centre, and IRIS) and rewrites
`Utilities/regd.sta`, keeping the previous one as `Utilities/regd.sta.bak`.
`authcat stup --dry-run` shows what would change. With an editable install
(`pip install -e .`) this updates the repository's own copy, ready to commit;
with a regular install, upgrading AUTH-CAT replaces it with the list of the new
release.

## Quickstart guide

1. Start a project by downloading the bulletin for your target period and study area:

   ```
   authcat bul                    # asks for the project name, date range and lat/lon boundaries. Direct input in the command line
   authcat bul -p Arkal --start 2021-06-01 --end 2022-12-31 --min-lat 35.0 --max-lat 35.3 --min-lon 25.1 --max-lon 25.4 # Without further command line interaction
   ```

   or from a bulletin you already have (currently supports only AUTOLOC3 format):

   ```
   authcat project Arkal --bulletin Arkal.bul
   ```

2. Run the desired commands. Each one first asks which project to work
   on (pressing Enter takes the last one used), reads its input from that project and
   writes its output there. When input is piped in by a batch script, the last
   project used is taken without asking. `authcat cat` and `authcat pha` also
   accept `-p/--project`. When a command asks for a bulletin, catalogue or
   phase list, pressing Enter takes the project's own file (e.g. `Tyrnavos.bul`, `Tyrnavos_cat.txt`).

3. Build the PDF report of everything recorded so far:

   ```
   authcat rep                    # asks which project
   authcat rep -p Arkal           # or name the project
   ```


The project record follows the layout in `project.py` (`TEMPLATE`). A section
reads `"available": false` until the script that fills it has run, paths are
relative to the project folder, and `history` lists each run with its inputs
and parameters, so the file can be used to build a report for the project.
