import os

def parse_and_format_earthquake_bulletin_robust(file_content):
    lines = file_content.split('\n')
    earthquake_phases = []
    current_date = None
    p_time = {}
    in_phase_section = False

    def format_date_time(date, time):
        formatted_date = date.replace('-', '')[2:]
        formatted_time = time.replace(':', '')[:6]
        milliseconds = time.split('.')[-1][:2]  # Take first two digits of milliseconds
        return f"{formatted_date}{formatted_time}.{milliseconds}"

    def adjust_seconds_only(time_str, seconds_to_add):
        seconds = int(time_str[10:12])
        milliseconds = time_str[13:15]
        total_seconds = seconds + seconds_to_add
        return f"{total_seconds:02d}.{milliseconds}"

    for i, line in enumerate(lines):
        if 'Date' in line:
            current_date = line.split()[-1].strip()
        elif 'Time' in line:
            current_time = line.split()[-1].strip()
        elif 'Phase arrivals:' in line:
            if in_phase_section:
                earthquake_phases.append("                 10")
            in_phase_section = True
        elif line.strip() == '' and in_phase_section:
            if i + 1 < len(lines) and lines[i + 1].strip() == '':
                in_phase_section = False
            continue
        elif in_phase_section:
            parts = line.split()
            if len(parts) >= 9:
                station = parts[0]
                if len(station) == 3:
                    station = station + " EP"
                elif len(station) == 4:
                    station = station + "EP"
                phase_type = parts[4]
                phase_time = parts[5]
                full_time = format_date_time(current_date, phase_time)
                if phase_type == 'P':
                    p_time[station] = full_time
                elif phase_type == 'S' and station in p_time:
                    s_time = full_time
                    p_minutes = int(p_time[station][8:10])
                    s_minutes = int(s_time[8:10])
                    if p_minutes != s_minutes:
                        s_time_formatted = adjust_seconds_only(s_time, 60)
                    else:
                        s_time_formatted = adjust_seconds_only(s_time, 0)
                    earthquake_phases.append(f"{station}   {p_time[station]}       {s_time_formatted} S 2")

    return earthquake_phases



def write_phases_to_file(phase_data, output_filename):
    try:
        with open(output_filename, 'w') as file:
            for line in phase_data:
                file.write(line + '\n')
            file.write(f"                 10")
        print("List of phases in HYPO71 format is written to Results/phases.txt")
    except Exception as e:
        print(f"Failed to write file: {str(e)}")

def read_file_and_debug(file_path):
    try:
        with open(file_path, 'r') as file:
            file_content = file.read()
        phase_data = parse_and_format_earthquake_bulletin_robust(file_content)
        return phase_data
    except Exception as e:
        print(f"Failed to read file: {str(e)}")
        return []

input_folder = "Input"
if os.path.isdir(input_folder):
    print(f"{input_folder} folder:")
    for filename in os.listdir(input_folder):
        print(filename)
else:
    print(f"The folder {input_folder} does not exist.")
file_path = input("Please provide the name of the earthquake bulletin: ")
input_file_path = os.path.join(input_folder, file_path)    
output_filename = 'Results/phases.txt'
os.makedirs('Results', exist_ok=True)
phase_data = read_file_and_debug(input_file_path)
if phase_data:
    write_phases_to_file(phase_data, output_filename)
