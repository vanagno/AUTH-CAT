# AUTH-CAT

## Projects

Every analysis session is kept in its own project folder, so runs never overwrite each
other. Run the scripts from the `authcat/` folder.

```
Projects/<name>/
    <name>.json   project record: the results of every script, and a history of runs. Acts as a diary for the whole workflow
    Input/        where the bulletin is stored
    Results/      catalogues, phase lists, summaries all outputs from AUTH-CAT scripts
    Figures/      plots and maps
    Magnitudes/   station magnitude lists and their plots
```
Quickstart
1. Start a project by downloading its bulletin:

   ```
   python getbul.py                    # asks for the project name, dates and area
   python getbul.py -p Arkal --start 2021-06-01 --end 2022-12-31
   ```

   or from a bulletin you already have:

   ```
   python project.py Arkal --bulletin Input/Arkal.bul
   ```

2. Run the other scripts as before. Each one first asks which project to work
   on (Enter takes the last one used), reads its input from that project and
   writes its output there. When input is piped in by a batch script, the last
   project used is taken without asking. `catalog.py` and `phases2.py` also
   accept `-p/--project`.

`python project.py` with no arguments lists the projects.

The project record follows the layout in `project.py` (`TEMPLATE`). A section
reads `"available": false` until the script that fills it has run, paths are
relative to the project folder, and `history` lists each run with its inputs
and parameters, so the file can be used to build a report for the project.
