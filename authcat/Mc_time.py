import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import convolve
from authcat.project import ask_file_name, open_project, shown, watermark
from authcat.style import MC, use_figure_style
use_figure_style()  # font, text size and 300 dpi shared by all figures

def read_catalog(file_path):
    df = pd.read_csv(file_path, sep=r"\s+", skiprows=1, 
                     names=['Date', 'Time', 'Lat', 'Lon', 'Depth', 'M', 'RMS', 'AzGap', 'Nsta', 'Msta', 'ID'])
    df['DateTime'] = pd.to_datetime(df['Date'] + ' ' + df['Time'])
    return df.set_index('DateTime')

def compute_mc(magnitudes, window_length, step=1):
    number_of_steps = len(magnitudes) - window_length + 1
    mc_values = np.zeros(number_of_steps)
    
    for i in range(number_of_steps):
        window = magnitudes[i:i + window_length]
        hist, bin_edges = np.histogram(window, bins=np.arange(window.min(), window.max(), 0.1), density=True)
        max_index = np.argmax(hist)
        mc_values[i] = bin_edges[max_index]
    
    return mc_values

def plot_mc(times, mc_values, filtered_mc_values, output_file):
    plt.figure(figsize=(12, 6))
    plt.plot(times, mc_values, color='gray', label='Raw ' + MC)
    plt.plot(times, filtered_mc_values, color='blue', linewidth=2, label='Filtered ' + MC)
    plt.title('Time Variation of Magnitude of Completeness')
    plt.xlabel('Date')
    plt.ylabel('Magnitude of Completeness (MAXC)')
    plt.legend()
    plt.grid(False)
    plt.gcf().autofmt_xdate()  # tilted dates, as in M_time.png, so they do not overlap
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    watermark()
    plt.savefig(output_file)     
    plt.show()
    print(f"Mc vs time plot saved to {shown(output_file)}")

proj = open_project()
input_folder = proj.results_dir
if os.path.isdir(input_folder):
    print(f"{shown(input_folder)} folder:")
    for filename in os.listdir(input_folder):
    	print(filename)
else:
    print(f"The folder {shown(input_folder)} does not exist.")
file_path = ask_file_name("Please enter the name of the earthquake catalogue", proj.recorded_name(input_folder, "project", "catalogue_file")) 
input_file_path = os.path.join(input_folder, file_path)    

df = read_catalog(input_file_path)

window_length = int(input("Enter the window length (no of events) for Mc computation: "))
filter_length = int(input("Enter the filter length (no of events) for smoothing: "))
mc_values = compute_mc(df['M'], window_length)

filter_kernel = np.ones(filter_length) / filter_length
filtered_mc_values = convolve(mc_values, filter_kernel, mode='valid')

times = df.index[window_length-1:-filter_length+1] 

output_file = os.path.join(proj.figures_dir, 'Mc_time.png')
plot_mc(times, mc_values[filter_length-1:], filtered_mc_values, output_file)
proj.update("Mc_time.py", {"figures": {"mc_time": proj.rel(output_file)}},
            catalogue=proj.rel(input_file_path), window_length=window_length,
            filter_length=filter_length)
