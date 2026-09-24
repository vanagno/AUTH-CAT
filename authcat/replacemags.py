import numpy as np
import os
from project import open_project

def update_catalog_with_modified_magnitudes(catalog_path, modified_magnitudes_path, output_path):
    """Write the catalogue with the recomputed magnitudes; return how many
    events were changed, or None on failure."""
    modified_magnitudes = {}
    try:
        with open(modified_magnitudes_path, 'r') as file:
            for line in file:
                parts = line.split()
                if len(parts) >= 3 and parts[0].startswith('auth'):
                    modified_magnitudes[parts[0]] = float(parts[2])
    except Exception as e:
        print(f"Error reading modified magnitudes file: {e}")
        return

    try:
        with open(catalog_path, 'r') as file:
            catalog_lines = file.readlines()

        new_catalog = []
        updated = 0
        for line in catalog_lines:
            parts = line.split()
            if len(parts) == 11 and parts[10].startswith('auth'):
                event_id = parts[10]
                if event_id in modified_magnitudes:
                    parts[5] = f"{modified_magnitudes[event_id]:4.2f}"
                    updated += 1
                formatted_line = f"{parts[0]} {parts[1]} "
                formatted_line += f"{float(parts[2]):6.4f} {float(parts[3]):6.4f} "
                formatted_line += f"{float(parts[4]):5.2f} {parts[5]:>5s} "
                formatted_line += f"{float(parts[6]):4.2f} {float(parts[7]):6.2f} "
                formatted_line += f"{int(parts[8]):3d} {int(parts[9]):3d} "
                formatted_line += f"{parts[10]}\n"
                new_catalog.append(formatted_line)
            else:
                new_catalog.append(line)

        with open(output_path, 'w') as file:
            file.writelines(new_catalog)

        print("Catalog has been updated with modified magnitudes and saved to", output_path)
#        print ("You can now run transform.py if you prefer the 6-column format")
        return updated
    except Exception as e:
        print(f"Error processing the catalog file: {e}")

def main():
    proj = open_project()
    input_folder = proj.results_dir
    if os.path.isdir(input_folder):
        print(f"{input_folder} folder:")
        for filename in os.listdir(input_folder):
            print(filename)
    else:
        print(f"The folder {input_folder} does not exist.")
        
    catalog_path = input("Please provide the name of the initial catalogue: ")
    input_file_path = os.path.join(input_folder, catalog_path)
    
    mag_folder = proj.magnitudes_dir
    if os.path.isdir(mag_folder):
        print(f"{mag_folder} folder:")
        for filename in os.listdir(mag_folder):
            print(filename)
    else:
        print(f"The folder {mag_folder} does not exist.")
        
    modified_magnitudes_path = input("Great! Now provide the modified mean magnitudes file\n(should be modified_magnitudes.txt if not renamed): ")
    mag_file_path = os.path.join(mag_folder, modified_magnitudes_path)
    
    base_name = os.path.basename(input_file_path)
    stem_name = os.path.splitext(base_name)[0]
    output_path = os.path.join(input_folder, f"{stem_name}_mod.txt")

    if not os.path.exists(input_file_path) or not os.path.exists(mag_file_path):
        print("One or more input files do not exist.")
        return

    updated = update_catalog_with_modified_magnitudes(input_file_path, mag_file_path, output_path)
    if updated is not None:
        proj.update("replacemags.py", {"magnitude_regularization": {
            "modified_catalogue_file": proj.rel(output_path),
        }}, catalogue=proj.rel(input_file_path), modified_magnitudes=proj.rel(mag_file_path),
            events_updated=updated)

if __name__ == "__main__":
    main()
