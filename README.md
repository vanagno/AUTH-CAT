# AUTH-CAT

## Projects

Every analysis session is kept in its own project folder, so runs never overwrite each
other. The project folders live in `Projects/` at the top of the repository, next to
`authcat/`, and the scripts find them from any folder they are run from.

```
Projects/<name>/
    <name>.json   project record: the results of every script, and a history of runs. Acts as a diary for the whole workflow
    Input/        where the bulletin is stored
    Results/      catalogues, phase lists, summaries all outputs from AUTH-CAT scripts
    Figures/      plots and maps
    Magnitudes/   station magnitude lists and their plots
    Reports/      the PDF report written by report.py
```

Reference files shared by every project, such as the station list
`regd.sta` and the report logo `LOGO.png`, live in `authcat/Utilities/`.
## Quickstart guide
1. Start a project by downloading the bulletin for your target period and study area:

   ```
   python getbul.py                    # asks for the project name, date range and lat/lon boundaries. Direct input in the command line
   python getbul.py -p Arkal --start 2021-06-01 --end 2022-12-31 --min-lat 35.0 --max-lat 35.3 --min-lon 25.1 --max-lon 25.4 # Without further command line interaction
   ```

   or from a bulletin you already have (currently supports only AUTOLOC3 format):

   ```
   python project.py Arkal --bulletin Input/Arkal.bul
   ```

2. Run the desired scripts. Each one first asks which project to work
   on (pressing Enter takes the last one used), reads its input from that project and
   writes its output there. When input is piped in by a batch script, the last
   project used is taken without asking. `catalog.py` and `phases2.py` also
   accept `-p/--project`.

3. Build the PDF report of everything recorded so far :

   ```
   python report.py                                # asks which project
   python report.py -p Arkal                       # or name the project
   ```


The project record follows the layout in `project.py` (`TEMPLATE`). A section
reads `"available": false` until the script that fills it has run, paths are
relative to the project folder, and `history` lists each run with its inputs
and parameters, so the file can be used to build a report for the project.
