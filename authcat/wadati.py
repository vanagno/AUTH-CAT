import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
from scipy.odr import Model, ODR, RealData
import os
from project import open_project, shown

def parse_earthquake_data(bulletin_text):
    lines = bulletin_text.strip().split('\n')
    earthquakes = []
    current_earthquake = {}
    phase_arrivals = {}
    
    for line in lines:
        if line.startswith('Event:'):
            if current_earthquake:
                current_earthquake['phase_arrivals'] = phase_arrivals
                earthquakes.append(current_earthquake)
                phase_arrivals = {}
            current_earthquake = {'phase_arrivals': {}}
        elif line.strip().startswith('Time'):
            origin_time_str = line.split()[1]
            current_earthquake['origin_time'] = datetime.strptime(origin_time_str, '%H:%M:%S.%f')
        elif line.strip() and ('P' in line or 'S' in line):
            parts = line.split()
            if len(parts) > 6 and (parts[4] == 'P' or parts[4] == 'S'):
                station = parts[0]
                phase_type = parts[4]
                arrival_time_str = parts[5]
                try:
                    if station not in phase_arrivals:
                        phase_arrivals[station] = {}
                    phase_arrivals[station][phase_type] = datetime.strptime(arrival_time_str, '%H:%M:%S.%f')
                except ValueError:
                    print(f"Error parsing time: {arrival_time_str} in line: {line}")
            else:
                print(f"Unexpected format or missing data in line: {line}")
    
    if current_earthquake:
        current_earthquake['phase_arrivals'] = phase_arrivals
        earthquakes.append(current_earthquake)
        
    return earthquakes

def compute_travel_times(earthquakes):
    p_travel_times = []
    sp_diff_times = []
    header = 'ID    P-travel S-travel S-P Diff'
    for eq in earthquakes:
        origin_time = eq['origin_time']
        for station, times in eq['phase_arrivals'].items():
            if 'P' in times and 'S' in times:
                p_travel_time = (times['P'] - origin_time).total_seconds()
                s_travel_time = (times['S'] - origin_time).total_seconds()
                diff_time = s_travel_time - p_travel_time
                if diff_time >= 0: 
                    p_travel_times.append(p_travel_time)
                    sp_diff_times.append(diff_time)
    return p_travel_times, sp_diff_times, header

def linear_function(p, x):
    return p[0] * x + p[1]

def plot_travel_times(p_travel_times, sp_diff_times, output_file):
    """Plot the Wadati diagram, save it to `output_file` and return the Vp/Vs
    ratios from least squares and from orthogonal regression."""
    plt.figure(figsize=(10, 6))
    plt.scatter(p_travel_times, sp_diff_times, color='blue', edgecolor='k')
    
    #Least Squares
    coefficients = np.polyfit(p_travel_times, sp_diff_times, 1)
    slope, intercept = coefficients
    polynomial = np.poly1d(coefficients)
    x_fit = np.linspace(min(p_travel_times), max(p_travel_times), 100)
    y_fit = polynomial(x_fit)
    plt.plot(x_fit, y_fit, "r--", label=f'OLS: y = {slope:.3f}x + {intercept:.3f}')

    #Orthogonal Regression
    model = Model(linear_function)
    data = RealData(p_travel_times, sp_diff_times)
    odr = ODR(data, model, beta0=[0., 1.])
    output = odr.run()
    beta = output.beta
    y_odr = beta[0] * x_fit + beta[1]
    plt.plot(x_fit, y_odr, "g--", label=f'Orthogonal: y = {beta[0]:.3f}x + {beta[1]:.3f}')

    textstr = f'Vp/Vs (LS): {1+slope:.2f}\nVp/Vs (OR): {1+beta[0]:.2f}'
    plt.text(0.95, 0.05, textstr, fontsize=12, verticalalignment='bottom', horizontalalignment='right', transform=plt.gca().transAxes, bbox=dict(facecolor='white', alpha=0.5))

    plt.title('P Travel Times vs S-P Travel Times')
    plt.xlabel('P Travel Time (seconds)')
    plt.ylabel('S-P Travel Time (seconds)')
    plt.xlim(left=0)
    plt.ylim(bottom=0)
    plt.legend()
    plt.grid(True)
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    plt.savefig(output_file)
    plt.show()
    return 1 + slope, 1 + beta[0]

def main():
    proj = open_project()
    input_folder = proj.input_dir
    if os.path.isdir(input_folder):
        print(f"{shown(input_folder)} folder:")
        for filename in os.listdir(input_folder):
            print(filename)
    else:
        print(f"The folder {shown(input_folder)} does not exist.")    
    bulletin_path = input("Please enter the name of the earthquake bulletin file: ")
    input_file_path = os.path.join(input_folder, bulletin_path)    
    with open(input_file_path, 'r') as file:
        bulletin_text = file.read()
    p_travel_times, sp_diff_times, header = compute_travel_times(parse_earthquake_data(bulletin_text))
    output_file = os.path.join(proj.figures_dir, 'Wadati.png')
    vpvs_ls, vpvs_or = plot_travel_times(p_travel_times, sp_diff_times, output_file)
    print(f"Wadati diagram saved to {shown(output_file)}")
    proj.update("wadati.py", {"wadati": {
        "pairs": len(p_travel_times),
        "vp_vs": {"least_squares": round(float(vpvs_ls), 2),
                  "orthogonal_regression": round(float(vpvs_or), 2)},
        "figure": proj.rel(output_file),
    }}, bulletin=proj.rel(input_file_path))

main()
