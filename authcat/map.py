import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from mpl_toolkits.basemap import Basemap
import numpy as np
import os
from project import ask_file_name, open_project, shown

def read_earthquake_catalog(file_path):
    """
    Reads earthquake data from a given file and returns lists of latitudes, longitudes, and magnitudes.
    """
    latitudes, longitudes, magnitudes = [], [], []
    with open(file_path, 'r') as file:
        next(file)
        for line in file:
            parts = line.split()
            latitudes.append(float(parts[2]))
            longitudes.append(float(parts[3]))
            magnitudes.append(float(parts[5]))
    return latitudes, longitudes, magnitudes

def plot_earthquakes_final_rounded_ticks(latitudes, longitudes, magnitudes, output_file):
    """
    Plots earthquakes on a map with meridians and parallels drawn every 0.2 degrees.
    Adjusts the start and end points for ticks to be rounded to the second decimal place.
    """
    plt.figure(figsize=(10, 8))
    earth_map = Basemap(projection='merc', llcrnrlat=min(latitudes)-0.2, urcrnrlat=max(latitudes)+0.2,
                        llcrnrlon=min(longitudes)-0.2, urcrnrlon=max(longitudes)+0.2, resolution='h')
    earth_map.drawcoastlines()
    earth_map.drawcountries()
    earth_map.fillcontinents(color='lightgray', lake_color='powderblue')
    earth_map.drawmapboundary(fill_color='powderblue')
    
    earthquakes = sorted(zip(latitudes, longitudes, magnitudes), key=lambda x: x[2])
    
    for latitude, longitude, magnitude in earthquakes:
        if magnitude <= 2.0:
            color = 'black'
        elif 2.0 < magnitude <= 3.0:
            color = 'lightyellow'
        elif 3.0 < magnitude <= 4.0:
            color = 'orange'
        elif 4.0 < magnitude <= 5.0:
            color = 'darkorange'
        else:
            color = 'red'
        
        x, y = earth_map(longitude, latitude)
        earth_map.scatter(x, y, s=(magnitude**2) * 5, marker='o', color=color, edgecolors='black', alpha=0.75, zorder=magnitude)
    
    legend_patches = [
        Patch(facecolor='black', edgecolor='black', label='<= 2.0'),
        Patch(facecolor='lightyellow', edgecolor='black', label='2.0 - 3.0'),
        Patch(facecolor='orange', edgecolor='black', label='3.0 - 4.0'),
        Patch(facecolor='darkorange', edgecolor='black', label='4.0 - 5.0'),
        Patch(facecolor='red', edgecolor='black', label='>= 5.0')
    ]
    
    lon_start = np.floor(min(longitudes) * 100) / 100
    lon_end = np.ceil(max(longitudes) * 100) / 100
    lat_start = np.floor(min(latitudes) * 100) / 100
    lat_end = np.ceil(max(latitudes) * 100) / 100

    meridian_interval = 0.2
    parallel_interval = 0.2

    meridians = earth_map.drawmeridians(np.arange(lon_start, lon_end + meridian_interval, meridian_interval), labels=[True, False, False, True], linewidth=0.3)
    parallels = earth_map.drawparallels(np.arange(lat_start, lat_end + parallel_interval, parallel_interval), labels=[True, False, False, True], linewidth=0.3)
    
    plt.legend(handles=legend_patches, loc='upper left', title='Magnitudes')
    plt.title('Earthquake Locations')
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    plt.savefig(output_file)
    plt.show()

if __name__ == "__main__":
    proj = open_project()
    input_folder = proj.results_dir
    if os.path.isdir(input_folder):
        print(f"{shown(input_folder)} folder:")
        for filename in os.listdir(input_folder):
            print(filename)
    else:
    	print(f"The folder {shown(input_folder)} does not exist.")
    catalog_path = ask_file_name("Please enter the name of the earthquake catalogue", proj.recorded_name(input_folder, "project", "catalogue_file"))
    input_file_path = os.path.join(input_folder, catalog_path)    
    latitudes, longitudes, magnitudes = read_earthquake_catalog(input_file_path)
    output_file = os.path.join(proj.figures_dir, 'Map_epic.png')
    plot_earthquakes_final_rounded_ticks(latitudes, longitudes, magnitudes, output_file)
    print(f"Epicentral map saved to {shown(output_file)}")
    proj.update("map.py", {"figures": {"epicentral_map": proj.rel(output_file)}},
                catalogue=proj.rel(input_file_path))
