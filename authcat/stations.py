
def parse_station_coordinates(file_path):
    station_coordinates = {}
    with open(file_path, 'r') as file:
        for line in file:
            parts = line.strip().split()
            station, latitude, longitude = parts[0], parts[1], parts[2]
            station_coordinates[station] = (latitude, longitude)
    return station_coordinates

def parse_phase_arrivals_v2(file_path):
    phase_arrivals = []
    with open(file_path, 'r') as file:
        in_phase_arrivals_section = False
        for line in file:
            if "Phase arrivals:" in line:
                in_phase_arrivals_section = True
            elif in_phase_arrivals_section and line.strip() == "":
                in_phase_arrivals_section = False
            elif in_phase_arrivals_section:
                parts = line.strip().split(maxsplit=9)
                if len(parts) == 10:
                    station, phase = parts[0], parts[4]
                    phase_arrivals.append({'station': station, 'phase': phase})
    return phase_arrivals

def count_phases(phase_arrivals):
    phase_counts = {}
    for arrival in phase_arrivals:
        station, phase = arrival['station'], arrival['phase']
        if station not in phase_counts:
            phase_counts[station] = {'P': 0, 'S': 0}
        if phase in ['P', 'S']:
            phase_counts[station][phase] += 1
    return phase_counts

def write_output_file(counts, station_coordinates, output_file_path):
    sorted_stations = sorted(counts.items(), key=lambda item: item[1]['P'], reverse=True)
    
    with open(output_file_path, 'w') as file:
        for station, phases in sorted_stations:
            if station in station_coordinates:
                latitude, longitude = station_coordinates[station]
                station_formatted = f"{station:5}"
                p_phases_formatted = f"{phases['P']:5}"
                s_phases_formatted = f"{phases['S']:5}"
                file.write(f"{station_formatted} {latitude} {longitude} {p_phases_formatted} {s_phases_formatted}\n")
            else:
                print(f"Warning: Coordinates for station {station} not found.")

import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import numpy as np
import os
from authcat.coastlines import Coastline
from authcat.project import ask_file_name, open_project, shown, UTILITIES_DIR, watermark
from authcat.style import use_figure_style
use_figure_style()  # font, text size and 300 dpi shared by all figures

MARKER_SIZE = 100       # triangle area, points^2
LABEL_SIZE = 8          # station names, points
LABEL_STEP = 7          # distance of a name from its triangle, points; tried at 1 to LABEL_RINGS steps
LABEL_COLOUR = '0.1'    # names in near-black ink; the triangles carry the colour
#: The light, slightly transparent box behind each name, which keeps it
#: readable over coastlines and leader lines.
LABEL_BOX = dict(boxstyle='round,pad=0.2', facecolor='white', edgecolor='0.6',
                 linewidth=0.3, alpha=0.75)


#: Directions tried around a triangle, in order of preference (degrees,
#: anticlockwise from east): above, the diagonals, the sides, below, then
#: the directions in between.
LABEL_DIRECTIONS = (90, 45, 135, 0, 180, 315, 225, 270,
                    67.5, 112.5, 22.5, 157.5, 337.5, 202.5, 292.5, 247.5)
LABEL_RINGS = 6


def _overlap(a, b):
    """Overlapping area of two (x0, y0, x1, y1) boxes."""
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def place_labels(ax, stations):
    """Write each station name next to its triangle, in dark ink on a light
    box (LABEL_COLOUR, LABEL_BOX).

    ``stations`` is a list of (name, lon, lat), the most important first.
    Each name takes the first spot around its triangle -- see
    LABEL_DIRECTIONS, one to LABEL_RINGS steps away -- where its box stays on
    the map and overlaps no triangle and no name already placed; when there
    is none, the spot that overlaps least. A name placed away from its
    triangle gets a thin leader line to it.
    """
    fig = ax.figure
    fig.canvas.draw()  # fixes the map extent and the colourbar layout
    renderer = fig.canvas.get_renderer()
    frame = ax.get_window_extent(renderer)
    half = np.sqrt(MARKER_SIZE) / 2 * fig.dpi / 72
    occupied = []
    for _, lon, lat in stations:
        x, y = ax.transData.transform((lon, lat))
        occupied.append((x - half, y - half, x + half, y + half))

    spots = [(ring * LABEL_STEP * np.cos(np.radians(angle)),
              ring * LABEL_STEP * np.sin(np.radians(angle)), ring)
             for ring in range(1, LABEL_RINGS + 1) for angle in LABEL_DIRECTIONS]

    def label(name, lon, lat, dx, dy, ring):
        ha = 'center' if abs(dx) < 0.01 else ('left' if dx > 0 else 'right')
        va = 'center' if abs(dy) < 0.01 else ('bottom' if dy > 0 else 'top')
        leader = (dict(arrowstyle='-', color='0.3', linewidth=0.4, shrinkA=0, shrinkB=half * 72 / fig.dpi)
                  if ring > 1 else None)
        text = ax.annotate(name, (lon, lat), xytext=(dx, dy), textcoords='offset points',
                           ha=ha, va=va, fontsize=LABEL_SIZE, color=LABEL_COLOUR, zorder=7,
                           bbox=LABEL_BOX, arrowprops=leader)
        text.update_positions(renderer)
        text.update_bbox_position_size(renderer)
        box = text.get_bbox_patch().get_window_extent(renderer)  # the name's box, not its leader line
        return text, (box.x0, box.y0, box.x1, box.y1)

    for name, lon, lat in stations:
        best = None  # (overlap, spot) of the least crowded spot on the map
        for spot in spots:
            text, box = label(name, lon, lat, *spot)
            text.remove()
            if not (frame.x0 <= box[0] and box[2] <= frame.x1
                    and frame.y0 <= box[1] and box[3] <= frame.y1):
                continue
            crowding = sum(_overlap(box, other) for other in occupied)
            if best is None or crowding < best[0]:
                best = (crowding, spot)
            if crowding == 0:
                break
        text, box = label(name, lon, lat, *(best[1] if best else spots[0]))
        occupied.append(box)


def generate_stations_map(counts, station_coordinates, output_map_path):
    p_phase_counts = [phases['P'] for phases in counts.values()]
    threshold = np.percentile(p_phase_counts, 80)

    fig = plt.figure(figsize=(10, 5))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    ax.add_feature(Coastline(1))  # full-resolution GSHHG coastlines, see coastlines.py
    ax.add_feature(cfeature.BORDERS.with_scale('10m'), linestyle=':')

    p_counts = np.array([phases['P'] for station, phases in counts.items() if phases['P'] >= threshold])
    norm = plt.Normalize(vmin=p_counts.min(), vmax=p_counts.max())
    cmap = plt.colormaps['viridis']

    # One scatter call, coloured by the number of P phases and drawn above the
    # coastlines, the stations with the most P phases on top
    shown_stations = sorted(((station, phases['P']) for station, phases in counts.items()
                             if phases['P'] >= threshold and station in station_coordinates),
                            key=lambda item: item[1])
    lons = [float(station_coordinates[station][1]) for station, _ in shown_stations]
    lats = [float(station_coordinates[station][0]) for station, _ in shown_stations]
    ax.scatter(lons, lats, s=MARKER_SIZE, c=[p for _, p in shown_stations], cmap=cmap, norm=norm,
               marker='^', edgecolor='k', linewidth=0.5, zorder=5, transform=ccrs.PlateCarree())

    colorbar = plt.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax, orientation='vertical')
    colorbar.set_label('Number of P Phases')
    colorbar.ax.yaxis.set_label_position('left')  # between the map and the bar
    plt.title('Seismic stations used')

    place_labels(ax, [(station, lon, lat)
                      for (station, _), lon, lat in sorted(zip(shown_stations, lons, lats),
                                                           key=lambda item: -item[0][1])])
    watermark()
    plt.savefig(output_map_path)
    plt.show()
    print(f"Map of the seismic stations used is saved to {shown(output_map_path)}")

# The station list; 'authcat stup' keeps it up to date.
regd_sta_file_path = os.path.join(UTILITIES_DIR, 'regd.sta')
station_file = 'Utilities/regd.sta'
proj = open_project()
input_folder = proj.input_dir
if os.path.isdir(input_folder):
    print(f"{shown(input_folder)} folder:")
    for filename in os.listdir(input_folder):
        print(filename)
else:
    print(f"The folder {shown(input_folder)} does not exist.")

file_path = ask_file_name("Please provide the name of the earthquake bulletin", proj.recorded_name(input_folder, "project", "bulletin_file"))
input_file_path = os.path.join(input_folder, file_path)    

output_file_path = os.path.join(proj.results_dir, 'station_phases_counts.txt')
output_map_path = os.path.join(proj.figures_dir, 'Map_Stations.png')

os.makedirs(proj.figures_dir, exist_ok=True)

station_coordinates = parse_station_coordinates(regd_sta_file_path)
phase_arrivals = parse_phase_arrivals_v2(input_file_path)
counts = count_phases(phase_arrivals)

write_output_file(counts, station_coordinates, output_file_path)
print(f"List of the number of P- and S-phases recorded for each station is saved to {shown(output_file_path)}")

generate_stations_map(counts, station_coordinates, output_map_path)

missing = sorted(station for station in counts if station not in station_coordinates)
if missing:
    print(f"{len(missing)} stations have no coordinates in {station_file}; "
          "'authcat stup' can look them up")
proj.update("stations.py", {"station_phases": {
    "station_count": len(counts),
    "missing_coordinate_station_count": len(missing),
    "missing_coordinate_stations": missing,
    "counts_file": proj.rel(output_file_path),
    "map_figure": proj.rel(output_map_path),
}}, bulletin=proj.rel(input_file_path), station_file=station_file)
