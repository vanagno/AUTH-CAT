import pandas as pd
import matplotlib.pyplot as plt
import os
from authcat.project import ask_file_name, open_project, shown, watermark

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

df = pd.read_csv(input_file_path, sep=r"\s+")

fig, axs = plt.subplots(2, 2, figsize=(10, 8))  # Creating 2x2 subplot structure

def add_stats_annotation(ax, data, color):
    mean_val = data.mean()
    median_val = data.median()
    textstr = f'Mean: {mean_val:.2f}\nMedian: {median_val:.2f}'
    # Place text in the top right corner
    ax.text(0.95, 0.95, textstr, transform=ax.transAxes, fontsize=9,
            verticalalignment='top', horizontalalignment='right',
            color=color, bbox=dict(facecolor='white', alpha=0.5))

#----- Histogram for Depth ------------#
axs[0, 0].hist(df['Depth'], bins=20, color='skyblue', edgecolor='black')
axs[0, 0].set_title('Depths (km)')
add_stats_annotation(axs[0, 0], df['Depth'], 'black')
#----- Histogram for Magnitudes -------#
axs[0, 1].hist(df['M'], bins=20, color='orange', edgecolor='black')
axs[0, 1].set_title('$M_{L}$')
add_stats_annotation(axs[0, 1], df['M'], 'black')
#----- Histogram for RMS --------------#
axs[1, 0].hist(df['RMS'], bins=20, color='green', edgecolor='black')
axs[1, 0].set_title('RMS (sec)')
add_stats_annotation(axs[1, 0], df['RMS'], 'black')
#----- Histogram for Azimuthal Gap ----#
axs[1, 1].hist(df['AzGap'], bins=20, color='red', edgecolor='black')
axs[1, 1].set_title('Azimuthal Gaps (°)')
add_stats_annotation(axs[1, 1], df['AzGap'], 'black')

for ax in axs.flat:
    ax.set_ylabel('Counts')
    ax.set_xlim(left=0)
plt.tight_layout()
directory = proj.figures_dir
output_file = os.path.join(directory,'Histograms.png')
os.makedirs(directory, exist_ok=True)
watermark()
plt.savefig(output_file)
plt.show()
print(f"Histograms saved to {shown(output_file)}")
proj.update("histograms.py", {"figures": {"histograms": proj.rel(output_file)}},
            catalogue=proj.rel(input_file_path))
