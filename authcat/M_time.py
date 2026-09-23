import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


def read_catalog(file_path):
    df = pd.read_csv(
        file_path,
        sep=r'\s+',
        skiprows=1,
        names=[
            'Date',
            'Time',
            'Lat',
            'Lon',
            'Depth',
            'Magnitude',
            'RMS',
            'AzGap',
            'Nsta',
            'Msta',
            'ID'
        ]
    )

    # Combine Date and Time into a proper datetime column
    df['DateTime'] = pd.to_datetime(
        df['Date'] + ' ' + df['Time'],
        format='%Y-%m-%d %H:%M:%S.%f'
    )

    return df.set_index('DateTime')


def plot_magnitudes(df):
    plt.figure(figsize=(12, 6))

    sizes = df['Magnitude'] ** 2 * 10

    plt.scatter(
        df.index,
        df['Magnitude'],
        s=sizes,
        alpha=0.5,
        edgecolors='none',
        color='blue'
    )

    plt.title('Magnitudes Over Time')
    plt.xlabel('Time')
    plt.ylabel('Magnitude')

    plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.gca().xaxis.set_major_formatter(
        mdates.DateFormatter('%Y-%m-%d')
    )

    plt.gcf().autofmt_xdate()
    plt.grid(False)

    directory = 'Figures'
    output_file = os.path.join(directory, 'M_time.png')

    os.makedirs(directory, exist_ok=True)

    plt.savefig(output_file)
    plt.show()


# Folder containing earthquake catalogues
input_folder = "Results"

if os.path.isdir(input_folder):
    print(f"{input_folder} folder:")

    for filename in os.listdir(input_folder):
        print(filename)
else:
    print(f"The folder {input_folder} does not exist.")


# Ask user which catalogue to process
file_path = input(
    "Please enter the name of the earthquake catalogue: "
)

input_file_path = os.path.join(input_folder, file_path)


# Read catalogue
df = read_catalog(input_file_path)


# Create plot
plot_magnitudes(df)


print("Magnitudes vs time plot saved to Figures/M_time.png")