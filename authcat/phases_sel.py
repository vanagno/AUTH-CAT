import os

def read_and_filter_data(input_filename):
    with open(input_filename, 'r') as file:
        lines = file.readlines()
    
    events = []
    current_event = []
    for line in lines:
        line = line.strip()
        if line == "10":
            if current_event:
                events.append(current_event)
                current_event = []
        else:
            current_event.append(line)
    if current_event:
        events.append(current_event)

    counts_filename = os.path.join("Results", "station_phases_counts.txt")
    if os.path.isfile(counts_filename):
        print(f"The station list according to {counts_filename}:")
        with open(counts_filename, 'r') as counts_file:
            print(counts_file.read())
    else:
        print(f"The file {counts_filename} does not exist. Run stations.py first or check your files")
    
    stations_input = input("Enter the station codes you want to keep (separated by commas): ")
    desired_stations = {station.strip().upper() for station in stations_input.split(",")}
    
    filtered_events = []
    for event in events:
        filtered_event = []
        for line in event:
            parts = line.split()
            station_name = parts[0].strip()
            if station_name.endswith('EP'):
                station_name = station_name[:-2].strip()
            if station_name.upper() in desired_stations:
                filtered_event.append(line)
        if filtered_event:
            filtered_events.append(filtered_event)
    
    return filtered_events

def write_filtered_data(output_filename, filtered_data):
    with open(output_filename, 'w') as file:
        for event in filtered_data:
            for line in event:
                file.write(f"{line}\n")
            file.write("                 10\n")

input_folder = "Results"
if os.path.isdir(input_folder):
    print(f"{input_folder} folder:")
    for filename in os.listdir(input_folder):
        print(filename)
else:
    print(f"The folder {input_folder} does not exist.")
file_path = input("Please provide the phases list (should be phases.txt if not renamed): ")
input_file_path = os.path.join(input_folder, file_path)    
phase_data = read_and_filter_data(input_file_path)
write_filtered_data('Results/phases_sel.txt', phase_data)
print("Phase list has been successfully updated to Results/phases_sel.txt")