import os
import re
import matplotlib.pyplot as plt
import numpy as np

def parse_earthquake_data_from_file(file_path):
    import re

    try:
        with open(file_path, 'r') as file:
            bulletin_text = file.read()
    except Exception as e:
        print(f"Failed to read file: {e}")
        return []

    event_blocks = bulletin_text.split("Event:\n")[1:]
    earthquake_data = []
    
    for event in event_blocks:
        try:
            event_dict = {}
            lines = event.split('\n')
            public_id_line = next((line for line in lines if "Public ID" in line and "Preferred" not in line), None)
            if public_id_line:
                event_dict['Public ID'] = public_id_line.split()[-1]

            network_magnitudes_pattern = re.compile(r"\d+ Network magnitudes:")
            network_magnitudes_line = next((line for line in lines if network_magnitudes_pattern.match(line)), None)
            if network_magnitudes_line:
                network_magnitudes_index = lines.index(network_magnitudes_line)
                event_magnitude_line = lines[network_magnitudes_index + 1]
                event_dict['Event Magnitude'] = event_magnitude_line.split()[1]

            station_magnitudes_pattern = re.compile(r"\d+ Station magnitudes:")
            station_magnitudes_line = next((line for line in lines if station_magnitudes_pattern.match(line)), None)
            station_magnitudes = []
            if station_magnitudes_line:
                station_magnitudes_index = lines.index(station_magnitudes_line)
                station_magnitude_lines = lines[station_magnitudes_index + 1:]
                for line in station_magnitude_lines:
                    if line.strip() and "sta" not in line:
                        parts = line.split()
                        station_magnitudes.append((parts[0], parts[5])) 
            event_dict['Station Magnitudes'] = station_magnitudes
            earthquake_data.append(event_dict)
        except Exception as e:
            print(f"Error processing an event: {e}")

    return earthquake_data



def write_earthquake_data_to_file(earthquake_data, directory, filename):
    if not os.path.exists(directory):
        os.makedirs(directory)
    full_path = os.path.join(directory, filename)
    try:
        with open(full_path, 'w') as file:
            for event in earthquake_data:
                file.write(f'{event["Public ID"]}    {event["Event Magnitude"]}\n')
                for station in event['Station Magnitudes']:
                    file.write(f'{station[0].ljust(4)} {station[1]}\n')
                file.write('\n')
    except Exception as e:
        print(f"Failed to write to file: {e}")
        
def count_observations_per_station(earthquake_data):
    station_counts = {}
    for event in earthquake_data:
        for station, _ in event['Station Magnitudes']:
            if station in station_counts:
                station_counts[station] += 1
            else:
                station_counts[station] = 1
    return station_counts

def calculate_median_residuals(earthquake_data):
    residuals = {}
    for event in earthquake_data:
        eq_magnitude = float(event['Event Magnitude'])
        for station, mag in event['Station Magnitudes']:
            station_magnitude = float(mag)
            residual = eq_magnitude - station_magnitude
            if station in residuals:
                residuals[station].append(residual)
            else:
                residuals[station] = [residual]

    median_residuals = {station: np.median(vals) for station, vals in residuals.items()}
    return median_residuals


def plot_station_data(station_counts, median_residuals):
    max_observations = max(station_counts.values())
    threshold = 0.05 * max_observations

    filtered_stations = {station: count for station, count in station_counts.items() if count > threshold and station in median_residuals}

    sorted_stations = sorted(filtered_stations.items(), key=lambda item: item[1], reverse=True)
    stations = [station for station, count in sorted_stations]
    counts = [filtered_stations[station] for station in stations]
    medians = [median_residuals[station] for station in stations if station in median_residuals]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    ax1.bar(stations, medians, color='violet', edgecolor='black')
    ax1.set_title('Median Residual (Event Mag - Station Mag)')
    ax1.set_ylabel('Median Residual')
    ax1.axhline(0, color='black', linewidth=1, linestyle='-')
    ax2.bar(stations, counts, color='royalblue', edgecolor='black')
    ax2.set_ylabel('Number of Observations')
    plt.xticks(rotation=45)
    plt.tight_layout()
    directory = 'Magnitudes'
    output_file = os.path.join(directory,'magnitudes.png')
    os.makedirs(directory, exist_ok=True)
    plt.savefig(output_file, dpi=400) 
    plt.show()
    print(f"Median residual magnitudes plot saved to Magnitudes/magnitudes.png")


def modify_output_file(directory, original_filename, modified_filename, stations_to_eliminate):
    original_path = os.path.join(directory, original_filename)
    modified_path = os.path.join(directory, modified_filename)

    if not os.path.exists(original_path):
        print("The original file does not exist.")
        return

    with open(original_path, 'r') as file:
        lines = file.readlines()

    with open(modified_path, 'w') as file:
        for line in lines:
            if line.strip():  
                parts = line.split()
                if parts:  
                    station_name = parts[0].strip()
                    if not any(station == station_name for station in stations_to_eliminate):
                        file.write(line)
            else:
                file.write(line) 

    print("Created a modified output file with specified stations removed.")


def compute_and_append_mean_magnitudes(directory, filename):
    full_path = os.path.join(directory, filename)
    if not os.path.exists(full_path):
        print("The file does not exist.")
        return

    try:
        with open(full_path, 'r') as file:
            lines = file.readlines()

        new_lines = []
        temp_magnitudes = []
        current_event_id = None
        current_event_magnitude = None
        event_line_index = None

        for i, line in enumerate(lines):
            if line.strip(): 
                parts = line.split()
                if len(parts) == 2 and parts[0].startswith('auth'): 
                    if current_event_id is not None:
                        mean_magnitude = np.mean(temp_magnitudes)
                        new_lines[event_line_index] = f"{current_event_id}    {current_event_magnitude}    {mean_magnitude:.2f}\n"
                        temp_magnitudes = []  
                    current_event_id = parts[0]
                    current_event_magnitude = parts[1]
                    event_line_index = len(new_lines) 
                    new_lines.append(line)  
                else:
                    if len(parts) == 2 and parts[1].replace('.', '', 1).isdigit():
                        temp_magnitudes.append(float(parts[1]))
                    new_lines.append(line) 

        if current_event_id is not None and temp_magnitudes:
            mean_magnitude = np.mean(temp_magnitudes)
            new_lines[event_line_index] = f"{current_event_id}    {current_event_magnitude}    {mean_magnitude:.2f}\n"

        with open(full_path, 'w') as file:
            file.writelines(new_lines)

        print("Mean magnitudes computed and appended to the file.")
    except Exception as e:
        print(f"Failed to process the file: {e}")


def user_interaction(directory):
    response = input("Do you want to recompute magnitudes? (yes/no): ").lower()
    if response == 'yes':
        stations_input = input("Which station magnitudes do you want to eliminate? (with commas): ")
        stations_to_eliminate = [station.strip() for station in stations_input.split(',')]
        modify_output_file(directory, "magnitudes.txt", "modified_magnitudes.txt", stations_to_eliminate)
        print("Updated the output file by removing specified stations.")

        if input("Do you want to compute mean magnitudes for each event? (yes/no): ").lower() == 'yes':
            compute_and_append_mean_magnitudes(directory, "modified_magnitudes.txt")
            print("New mean magnidutes were computed and written to Magnitudes/modified_magnitudes.txt")

def main():
    directory = "Magnitudes"
    input_folder = "Input"
    if os.path.isdir(input_folder):
        print(f"{input_folder} folder:")
        for filename in os.listdir(input_folder):
             print(filename)
    else:
    	print(f"The folder {input_folder} does not exist.")
    file_path = input("Enter the path to the earthquake bulletin file: ")
    input_file_path = os.path.join(input_folder, file_path)    
    output_file = 'magnitudes.txt'

    parsed_data = parse_earthquake_data_from_file(input_file_path)
    write_earthquake_data_to_file(parsed_data, directory, output_file)
    station_counts = count_observations_per_station(parsed_data)
    median_residuals = calculate_median_residuals(parsed_data)
    plot_station_data(station_counts, median_residuals)

    user_interaction(directory)

if __name__ == "__main__":
    main()