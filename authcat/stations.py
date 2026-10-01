
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
from authcat.project import ask_file_name, open_project, shown, UTILITIES_DIR, watermark

def generate_stations_map(counts, station_coordinates, output_map_path):
    p_phase_counts = [phases['P'] for phases in counts.values()]
    threshold = np.percentile(p_phase_counts, 80)
    
    fig = plt.figure(figsize=(10, 5))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    ax.add_feature(cfeature.COASTLINE.with_scale('10m'))
    ax.add_feature(cfeature.BORDERS, linestyle=':')
    
    p_counts = np.array([phases['P'] for station, phases in counts.items() if phases['P'] >= threshold])
    norm = plt.Normalize(vmin=p_counts.min(), vmax=p_counts.max())
    cmap = plt.colormaps['viridis']
    
    # One scatter call, coloured by the number of P phases
    shown_stations = [(station, phases['P']) for station, phases in counts.items()
                      if phases['P'] >= threshold and station in station_coordinates]
    lons = [float(station_coordinates[station][1]) for station, _ in shown_stations]
    lats = [float(station_coordinates[station][0]) for station, _ in shown_stations]
    ax.scatter(lons, lats, s=100, c=[p for _, p in shown_stations], cmap=cmap, norm=norm, marker='^', edgecolor='k', linewidth=0.5, transform=ccrs.Geodetic())
    for (station, _), lon, lat in zip(shown_stations, lons, lats):
        ax.text(lon, lat + 0.03, station, transform=ccrs.Geodetic(), fontsize=6, ha='center', va='bottom')

    plt.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax, orientation='vertical', label='Number of P Phases')
    plt.title('Seismic stations used')
    watermark()
    plt.savefig(output_map_path, dpi=400)
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
