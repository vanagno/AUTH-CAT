"""High-resolution coastlines for the AUTH-CAT maps.

The maps draw the full-resolution shorelines of GSHHG (about 100 m; Wessel &
Smith, 1996) with :class:`Coastline`, a cartopy feature:

* for maps within Greece and its neighbours (EXTRACT_REGION), from the
  extract that ships with AUTH-CAT in Utilities/ -- fast, and needs no
  internet;
* elsewhere, from GSHHG itself, which cartopy downloads once (about 150 MB);
* when neither is available, from Natural Earth 1:10m, as before.

GSHHG level 1 polygons are land (their outline is the coastline), level 2
lakes. GSHHG is distributed under the GNU LGPL.

    Wessel, P., Smith, W. H. F. (1996). A global, self-consistent,
    hierarchical, high-resolution shoreline database. J. Geophys. Res.,
    101(B4), 8741-8743. https://doi.org/10.1029/96JB00104

``python -m authcat.coastlines`` rebuilds the extract from GSHHG.
"""

from __future__ import annotations

import gzip
import sys
from functools import lru_cache

import cartopy.crs as ccrs
import cartopy.feature as cfeature
from shapely import wkb
from shapely.geometry import MultiPolygon, box as make_box

from authcat.project import UTILITIES_DIR

#: (min lon, min lat, max lon, max lat) of the extract: authcat stup's
#: default area.
EXTRACT_REGION = (18.0, 33.5, 31.0, 43.5)
EXTRACT_FILES = {1: "gshhg_f_L1_greece.wkb.gz", 2: "gshhg_f_L2_greece.wkb.gz"}
_NATURAL_EARTH = {1: "land", 2: "lakes"}
_warned = set()


@lru_cache(maxsize=None)
def _extract(level: int) -> tuple:
    data = gzip.decompress((UTILITIES_DIR / EXTRACT_FILES[level]).read_bytes())
    return tuple(wkb.loads(data).geoms)


@lru_cache(maxsize=None)
def _gshhg(level: int, bbox: tuple) -> tuple:
    """GSHHG polygons of ``level`` touching ``bbox``; cartopy downloads GSHHG
    the first time."""
    from cartopy.io import shapereader
    return tuple(shapereader.Reader(shapereader.gshhs("f", level), bbox=bbox).geometries())


def _natural_earth(level: int) -> tuple:
    return tuple(cfeature.NaturalEarthFeature("physical", _NATURAL_EARTH[level], "10m").geometries())


def _note_once(key: str, text: str) -> None:
    if key not in _warned:
        _warned.add(key)
        print(text)


class Coastline(cfeature.Feature):
    """Full-resolution land (level 1) or lake (level 2) polygons, for
    ``ax.add_feature``. Their outline is the coastline: give ``facecolor``
    to fill them, ``edgecolor``/``linewidth`` for the line."""

    def __init__(self, level: int = 1, **kwargs):
        kwargs.setdefault("facecolor", "none")
        kwargs.setdefault("edgecolor", "black")
        super().__init__(ccrs.PlateCarree(), **kwargs)
        self.level = level

    def geometries(self):
        return self.intersecting_geometries(None)

    def intersecting_geometries(self, extent):
        geoms = self._source(extent)
        if extent is None:
            yield from geoms
            return
        box = make_box(extent[0], extent[2], extent[1], extent[3])
        for geom in geoms:
            if box.intersects(geom):
                yield geom

    def _source(self, extent) -> tuple:
        if extent is not None:
            x0, x1, y0, y1 = extent
            r = EXTRACT_REGION
            if r[0] <= x0 and x1 <= r[2] and r[1] <= y0 and y1 <= r[3]:
                return _extract(self.level)
            bbox = (round(x0, 2) - 0.01, round(y0, 2) - 0.01, round(x1, 2) + 0.01, round(y1, 2) + 0.01)
        else:
            bbox = None
        try:
            _note_once("gshhg", "The map reaches beyond Greece: using the full GSHHG coastlines "
                       "(downloaded once, about 150 MB, the first time)")
            return _gshhg(self.level, bbox)
        except Exception as exc:  # no internet, or the download was refused
            _note_once("fallback", f"High-resolution coastlines unavailable ({exc}); "
                       "using Natural Earth 1:10m")
            return _natural_earth(self.level)


def build_extract() -> None:
    """Cut EXTRACT_REGION out of GSHHG into Utilities/ (downloads GSHHG)."""
    from cartopy.io import shapereader
    box = make_box(*EXTRACT_REGION)
    for level, name in EXTRACT_FILES.items():
        reader = shapereader.Reader(shapereader.gshhs("f", level), bbox=EXTRACT_REGION)
        parts = [geom.intersection(box) for geom in reader.geometries()]
        polygons = []
        for part in parts:
            polygons += [g for g in getattr(part, "geoms", [part])
                         if g.geom_type == "Polygon" and not g.is_empty]
        data = gzip.compress(wkb.dumps(MultiPolygon(polygons)), mtime=0)
        (UTILITIES_DIR / name).write_bytes(data)
        print(f"Utilities/{name}: {len(polygons)} polygons, {len(data) / 1e6:.2f} MB")


if __name__ == "__main__":
    build_extract()
    sys.exit(0)
