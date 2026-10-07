# Releasing AUTH-CAT

AUTH-CAT is published on PyPI as `authcat`. Publishing a release on GitHub
runs `.github/workflows/publish.yml`, which builds the package and uploads it
with PyPI's trusted publishing: PyPI trusts that one workflow of this
repository, so no password or API token is stored anywhere.

## One-time setup

1. **PyPI.** On pypi.org (an account with two-factor authentication), go to
   *Your account → Publishing → Add a new pending publisher → GitHub* and
   fill in:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `authcat` |
   | Owner | `vanagno` |
   | Repository name | `AUTH-CAT` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

   The first upload creates the project, and the publisher then appears under
   the project's *Settings → Publishing*. Renaming the repository, the
   workflow file or the environment stops uploads until the publisher there
   is changed to match.

2. **GitHub.** *Settings → Environments → New environment*, named `pypi`.
   Under *Deployment branches and tags*, choose *Selected branches and tags*
   and add a **Tag** rule `v*`, so that only runs started from a release tag
   can upload.

   Required reviewers (an approval click before each upload) are not offered
   for private repositories on GitHub's Free, Pro and Team plans; the option
   appears once the repository is public.

## Making a release

1. Bring the station list up to date, since it ships with the package: with
   an editable install (`pip install -e .`), run `authcat stup --dry-run`,
   then `authcat stup`, and commit `authcat/Utilities/regd.sta`.
2. Set the new version in `authcat/__init__.py`, e.g.
   `__version__ = "0.1.1"`; `pyproject.toml` takes it from there. In
   `CHANGELOG.md`, turn *Unreleased* into the new version with today's date,
   start an empty *Unreleased* above it, and update the comparison links at
   the bottom. In `CITATION.cff`, set `version` and `date-released`.
3. Check that the package builds and installs:

   ```
   pip install build
   python -m build
   ```

   then install the wheel from `dist/` into a fresh environment (e.g. a new
   conda environment) and run `authcat --version` and `authcat --help`.
   Delete `dist/` afterwards.
4. Merge the changes into `main`.
5. On GitHub, *Releases → Draft a new release*: tag `v` plus the version
   (`v0.1.1`, created on publish), target `main`, the same title, and
   optionally *Generate release notes*. Then *Publish release*.
6. Follow the *Publish to PyPI* run in the *Actions* tab. Once both of its
   jobs are green, the version is on https://pypi.org/p/authcat and
   `pip install --upgrade authcat` installs it.

## Good to know

- **A version can be uploaded only once.** PyPI refuses a version it has seen
  before, even after the release is deleted. If a release went out wrong, fix
  it and release the next version. A broken version can be *yanked* on PyPI
  (*Manage → Releases*), so pip no longer picks it unless asked for it by
  number.
- **The tag must match `__version__`.** The workflow uploads the version
  written in `authcat/__init__.py`, whatever the tag says.
- **Publishing makes the code public.** Whatever the repository's visibility,
  anyone can `pip install authcat` and read the source. The package holds
  `authcat/` with its station list and logo (and, in the source archive,
  `README.md`, `LICENSE` and `pyproject.toml`); `Projects/` and its bulletins
  are not included.
- **While the repository is private**, installing straight from GitHub
  (`pip install git+https://github.com/vanagno/AUTH-CAT`) and the
  *Repository* link on the PyPI page work only for its collaborators.
