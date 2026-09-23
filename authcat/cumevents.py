import pandas as pd
import matplotlib.pyplot as plt
import os

def calculate_cumulative_earthquakes(file_path):
    mc = float(input("Give the Mc (Magnitude of Completeness): "))
    df = pd.read_csv(file_path, delim_whitespace=True, header=None, 
                     names=['Year', 'MMDDhhmmss.ss', 'Latitude', 'Longitude', 'Depth', 'Magnitude'])
    
    df['Month'] = df['MMDDhhmmss.ss'].apply(lambda x: str(x).zfill(13)[:2])
    df['Day'] = df['MMDDhhmmss.ss'].apply(lambda x: str(x).zfill(13)[2:4])
    df['Hour'] = df['MMDDhhmmss.ss'].apply(lambda x: str(x).zfill(13)[4:6])
    df['Minute'] = df['MMDDhhmmss.ss'].apply(lambda x: str(x).zfill(13)[6:8])
    df['Second'] = df['MMDDhhmmss.ss'].apply(lambda x: str(x).zfill(13)[8:10])
    df['Microsecond'] = df['MMDDhhmmss.ss'].apply(lambda x: str(x).zfill(13)[10:]).astype(float) * 1e6

    df['Datetime'] = pd.to_datetime(df[['Year', 'Month', 'Day', 'Hour', 'Minute', 'Second', 'Microsecond']].astype(int).astype(str).agg('-'.join, axis=1),
                                    format='%Y-%m-%d-%H-%M-%S-%f', errors='coerce')
    
    df['Cumulative Count'] = range(1, len(df) + 1)
    df['Days'] = (df['Datetime'] - df['Datetime'].iloc[0]) / pd.Timedelta(days=1)
    
    filtered_df = df[df['Magnitude'] >= mc]
    filtered_df['Cumulative Count Above Mc'] = range(1, len(filtered_df) + 1)
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 5))    
    ax1.plot(df['Days'], df['Cumulative Count'], marker='o',linestyle='')
    ax1.set_title('Cumulative Number of Earthquakes Over Time')
    ax1.set_xlabel('Days Since Start of Catalog')
    ax1.set_ylabel('Cumulative Count')
    
    ax2.plot(filtered_df['Days'], filtered_df['Cumulative Count Above Mc'], marker='o',linestyle='', color='red')
    ax2.set_title(f'Cumulative Number of Earthquakes Above Mc ({mc}) Over Time')
    ax2.set_xlabel('Days Since Start of Catalog')
    ax2.set_ylabel(f'Cumulative Count Above Mc ({mc})')
    
    directory = 'Figures'
    output_file = os.path.join(directory,'cumulative_earthquakes.png')
    os.makedirs(directory, exist_ok=True)
    plt.savefig(output_file)
    plt.show()
    print(f"Cumulative earthquakes plot saved to Figures/cumulative_earthquakes.png")

if __name__ == "__main__":
    input_folder = "Results"
    if os.path.isdir(input_folder):
        print(f"{input_folder} folder:")
        for filename in os.listdir(input_folder):
            print(filename)
    else:
        print(f"The folder {input_folder} does not exist.")
    
    file_path = input("Please provide the name of the 6-column catalogue: ")
    input_file_path = os.path.join(input_folder, file_path)    
    result, filtered_result = calculate_cumulative_earthquakes(input_file_path)