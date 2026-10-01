# Changelog

All notable changes to AUTH-CAT are listed here, newest first. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and version
numbers follow [Semantic Versioning](https://semver.org/).

Add a line under **Unreleased** with each change; at a release, that section
becomes the new version (see `RELEASING.md`).

## [Unreleased]

### Added
- This changelog. The release steps in `RELEASING.md` now include moving its
  *Unreleased* entries under the new version and updating `CITATION.cff`.

### Fixed
- `CITATION.cff` gives the version released, 0.1.1, and its date.

## [0.1.1] - 2026-10-01

### Changed
- `authcat map`: the legend reads ≤ 2.0 and > 5.0 instead of <= 2.0 and
  >= 5.0 (magnitude 5.0 itself is drawn in the 4.0 - 5.0 colour).
- `authcat rep`: latitude and longitude limits, the depth range and the
  modified Omori c and p values are shown with 2 decimals, rounded to the
  nearest (halves up); magnitudes use the same rounding.
- `authcat vpvs`: P-S pairs whose P arrives before the origin time (a wrong
  pick or origin time) are left out, and their number is reported.

### Fixed
- `authcat vpvs`: only the phase tables of the bulletin are read, so lines
  such as *Public ID*, *Status* or station magnitudes are no longer reported
  as unexpected.
- `authcat vpvs`: an arrival after midnight of an event before midnight is
  timed on the next day; before, its P-S pair was dropped or its P travel
  time came out near -86400 s and distorted the fit.
- `authcat ou`: the modified Omori and MCMC figures are shown, not only
  saved.

## [0.1.0] - 2026-10-01

First release on PyPI (`pip install authcat`).

### Added
- The `authcat` command, with a short name for each step of the workflow:
  `bul`, `cat`, `map`, `hist`, `mt`, `nt`, `mct`, `mc`, `mags`, `rmag`,
  `sta`, `stup`, `pha`, `pse`, `vpvs`, `ou`, `rep` and `project`.
- Projects: each analysis has its own folder, `Projects/<name>/` (`Input`,
  `Results`, `Figures`, `Magnitudes`, `Reports`), with a JSON record of every
  result and a history of the runs. Projects are kept in the folder
  `authcat` is run from, or where `AUTHCAT_PROJECTS` points.
- `authcat bul` starts a project by downloading its bulletin;
  `authcat project` starts one from a bulletin already on disk.
- `authcat rep`: a PDF report of a project, built from its JSON record.
- `authcat stup`: updates the station list `regd.sta` from the FDSN station
  services (every EIDA data centre, and IRIS).
- `authcat mags`: a residual threshold; stations beyond it are drawn in
  another colour and can be left out when the magnitudes are recomputed.
  A Bland-Altman plot compares the original and recomputed magnitudes.
- `authcat ou`: the modified Omori law fitted with a Bayesian method, with
  MCMC uncertainties, a chosen start and an end time.
- `authcat pse`: pressing Enter keeps the 20 stations with the most P phases.
- Pressing Enter at a file prompt takes the project's own file.
- A small "made with AUTH-CAT" mark on every figure.

### Changed
- Scripts renamed: `getbul` → `bulletin`, `map` → `seismicity_map`,
  `hist` → `histograms`, `cumevents2` → `N_time`, `replacemags` →
  `repmags`, `phases2` → `phases`, `phases_sel2` → `sel_phases`, and
  `omori2` replaced by `omori_utsu`.
- Maps are drawn with cartopy instead of basemap.
- The station list moved to `authcat/Utilities/regd.sta`, installed with
  the package.

### Fixed
- `authcat pha`: the HYPO71 phase file no longer requires both P and S; a
  station with only a P gets a P-only card.
- `authcat mc`: `Mc_summary.txt` reported the MBS result under all three
  methods, and the GFT method failed when neither the 95% nor the 90% level
  was reached. Its figures no longer overlap when run without a display.
- `authcat vpvs`: the Wadati diagram is saved, as reported.
- Compatibility with pandas 3.

[Unreleased]: https://github.com/vanagno/AUTH-CAT/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/vanagno/AUTH-CAT/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/vanagno/AUTH-CAT/releases/tag/v0.1.0
