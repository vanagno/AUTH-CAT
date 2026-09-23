import re
import os

def reformat_earthquake_line(line):
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2}\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)", line)
    if match:
        year, month, day, hour, minute, second, latitude, longitude, depth, magnitude = match.groups()
        second, millisecond = second.split('.')
        millisecond = f"{int(round(float('0.'+millisecond) * 100)):02}"
        new_datetime = f"{year} {month}{day}{hour}{minute}{second}.{millisecond}"
        
        depth = f"{float(depth):6.2f}"
        magnitude = f"{float(magnitude):.1f}"
 
        reformatted_line = f"{new_datetime} {latitude} {longitude} {depth} {magnitude}"
        return reformatted_line
    else:
        return None

def transform_earthquake_catalog(file_path, output_file_path):
    try:
        with open(file_path, 'r') as file:
            lines = file.readlines()

        with open(output_file_path, 'w') as output_file:
            for line in lines:
                reformatted_line = reformat_earthquake_line(line)
                if reformatted_line:
                    output_file.write(reformatted_line + '\n')
    except Exception as e:
        print(f"Error processing file: {e}")

input_folder = "Results"
if os.path.isdir(input_folder):
    print(f"{input_folder} folder:")
    for filename in os.listdir(input_folder):
        print(filename)
else:
    print(f"The folder {input_folder} does not exist.")

input_file_name = input("Please enter the name of the catalogue you want to transform: ")
input_file_path = os.path.join(input_folder, input_file_name)

if not os.path.isfile(input_file_path):
    print(f"The file {input_file_path} does not exist. Please check the file name and try again.")
else:
    base_name = os.path.basename(input_file_path)
    stem_name = os.path.splitext(base_name)[0]
    
    output_file_path = f'Results/{stem_name}_6col.txt'
    transform_earthquake_catalog(input_file_path, output_file_path)
    print(f"Transformed 6-column catalog saved to {output_file_path}")