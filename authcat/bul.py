import re
import os

def extract_earthquake_details(file_path):
    event_pattern = re.compile(r'^Event:')
    public_id_pattern = re.compile(r'Public ID\s+(?P<public_id>\S+)')
    date_pattern = re.compile(r'Date\s+(?P<date>\d{4}-\d{2}-\d{2})')
    time_pattern = re.compile(r'Time\s+(?P<time>\d{2}:\d{2}:\d{2}\.\d+)')
    latitude_pattern = re.compile(r'Latitude\s+(?P<latitude>\d+\.\d+)')
    longitude_pattern = re.compile(r'Longitude\s+(?P<longitude>\d+\.\d+)')
    depth_pattern = re.compile(r'Depth\s+(?P<depth>\d+\.\d+)')
    rms_pattern = re.compile(r'Residual RMS\s+(?P<rms>\d+\.\d+)')
    azimuthal_gap_pattern = re.compile(r'Azimuthal gap\s+(?P<gap>\d+\.\d+)')
    magnitude_pattern = re.compile(r'^\s*MLh\s+(?P<magnitude>\d+\.\d+)')
    phase_arrivals_pattern = re.compile(r'(\d+) Phase arrivals:')
    station_magnitudes_pattern = re.compile(r'(\d+) Station magnitudes:')

    earthquakes = []
    current_data = {}
    earthquake_count = 0
    capture_public_id_next = False

    with open(file_path, 'r') as file:
        for line in file:
            if event_pattern.match(line):
                if current_data:
                    earthquakes.append(current_data)
                    earthquake_count += 1
                current_data = {}
                capture_public_id_next = True
            elif capture_public_id_next and (public_id_match := public_id_pattern.search(line)):
                current_data['public_id'] = public_id_match.group('public_id')
                capture_public_id_next = False
            elif date_match := date_pattern.search(line):
                current_data['date'] = date_match.group('date')
            elif time_match := time_pattern.search(line):
                current_data['time'] = time_match.group('time')
            elif latitude_match := latitude_pattern.search(line):
                current_data['latitude'] = latitude_match.group('latitude')
            elif longitude_match := longitude_pattern.search(line):
                current_data['longitude'] = longitude_match.group('longitude')
            elif depth_match := depth_pattern.search(line):
                current_data['depth'] = depth_match.group('depth')
            elif rms_match := rms_pattern.search(line):
                current_data['rms'] = rms_match.group('rms')
            elif azimuthal_gap_match := azimuthal_gap_pattern.search(line):
                current_data['azimuthal_gap'] = azimuthal_gap_match.group('gap')
            elif magnitude_match := magnitude_pattern.search(line):
                current_data['magnitude'] = magnitude_match.group('magnitude')
            elif phase_arrivals_match := phase_arrivals_pattern.search(line):
                current_data['phase_arrivals'] = int(phase_arrivals_match.group(1))
            elif station_magnitudes_match := station_magnitudes_pattern.search(line):
                current_data['station_magnitudes_count'] = int(station_magnitudes_match.group(1))

    if current_data:
        earthquakes.append(current_data)
        earthquake_count += 1

    return earthquakes, earthquake_count

def main():
    input_folder = "Input"
    if os.path.isdir(input_folder):
        print(f"{input_folder} folder:")
        for filename in os.listdir(input_folder):
            print(filename)
    else:
    	print(f"The folder {input_folder} does not exist.")
    
    input_file_name = input("Enter the name of the earthquake bulletin file: ")
    input_file_path = os.path.join(input_folder, input_file_name)
    earthquakes, earthquake_count = extract_earthquake_details(input_file_path)
    
    filename = os.path.basename(input_file_path)
    filename_main = filename.rsplit('.', 1)[0]
    directory = 'Results'
    output_file_path = os.path.join(directory, filename_main + "_cat.txt")
    os.makedirs(directory, exist_ok=True)
    with open(output_file_path, 'w') as output_file:
        header_line = "   Date        Time       Lat     Lon   Depth  M   RMS  AzGap  Nsta Msta    ID\n"
        output_file.write(header_line)
        
        for eq in earthquakes:
            output_line = f"{eq['date']} {eq['time']} "
            output_line += f"{float(eq['latitude']):6.4f} {float(eq['longitude']):6.4f} "
            output_line += f"{float(eq['depth']):5.2f} {float(eq['magnitude']):4.2f} "
            output_line += f"{float(eq['rms']):4.2f} {float(eq['azimuthal_gap']):6.2f} "
            output_line += f"{eq['phase_arrivals']:3.0f} {eq['station_magnitudes_count']:3.0f} "
            output_line += f"{eq['public_id']}\n"
            
            output_file.write(output_line)


    print(f"Earthquake catalogue has been written to {output_file_path}")
    print(f"Total earthquakes in the bulletin: {earthquake_count}")

if __name__ == "__main__":
    main()
