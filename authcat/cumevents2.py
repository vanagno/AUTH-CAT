
import os

import matplotlib.pyplot as plt
import pandas as pd

from project import ask_file_name, open_project, shown

COLUMNS = ['Year', 'Stamp', 'Latitude', 'Longitude', 'Depth', 'Magnitude']


def read_sixcol(file_path):
    """Read a 6-column catalogue and return it in chronological order.

    The timestamp column is kept as text. Read as a number it loses any
    trailing zero in the centiseconds -- 0303082752.90 comes back as
    303082752.9 -- and padding that back to 13 characters shifts every
    field, so the month reads 00 and the row is lost.
    """
    df = pd.read_csv(file_path, sep=r"\s+", header=None, names=COLUMNS,
                     dtype={'Year': str, 'Stamp': str})

    df['Datetime'] = pd.to_datetime(df['Year'] + df['Stamp'],
                                    format='%Y%m%d%H%M%S.%f', errors='coerce')
    unreadable = int(df['Datetime'].isna().sum())
    if unreadable:
        print(f"{unreadable} of {len(df)} rows have a timestamp that could not "
              f"be read and are left out")
        df = df.dropna(subset=['Datetime'])

    out_of_order = int((df['Datetime'].diff() < pd.Timedelta(0)).sum())
    if out_of_order:
        print(f"{out_of_order} rows are out of chronological order; "
              f"sorting by time before counting")
        df = df.sort_values('Datetime', kind='stable')

    return df.reset_index(drop=True)


def calculate_cumulative_earthquakes(file_path, mc=None, figures_dir='Figures'):
    """Plot the cumulative count, whole catalogue and above Mc.

    Returns the full catalogue and the part of it at or above Mc, both with
    the Days and cumulative count columns the plot uses.
    """
    if mc is None:
        mc = prompt_for_mc()

    df = read_sixcol(file_path)
    df['Cumulative Count'] = range(1, len(df) + 1)
    df['Days'] = (df['Datetime'] - df['Datetime'].iloc[0]) / pd.Timedelta(days=1)

    filtered_df = df[df['Magnitude'] >= mc].copy()
    filtered_df['Cumulative Count Above Mc'] = range(1, len(filtered_df) + 1)
    print(f"{len(df)} events, {len(filtered_df)} at or above Mc {mc}, "
          f"over {df['Days'].iloc[-1]:.1f} days")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 5))    
    ax1.plot(df['Days'], df['Cumulative Count'], marker='o',linestyle='')
    ax1.set_title('Cumulative Number of Earthquakes Over Time')
    ax1.set_xlabel('Days Since Start of Catalog')
    ax1.set_ylabel('Cumulative Count')
    
    ax2.plot(filtered_df['Days'], filtered_df['Cumulative Count Above Mc'], marker='o',linestyle='', color='red')
    ax2.set_title(f'Cumulative Number of Earthquakes Above Mc ({mc}) Over Time')
    ax2.set_xlabel('Days Since Start of Catalog')
    ax2.set_ylabel(f'Cumulative Count Above Mc ({mc})')
    
    directory = figures_dir
    output_file = os.path.join(directory, 'cumulative_earthquakes.png')
    os.makedirs(directory, exist_ok=True)
    fig.savefig(output_file)
    plt.show()
    print(f"Cumulative earthquakes plot saved to {shown(output_file)}")

    return df, filtered_df


def prompt_for_mc():
    """Ask for Mc, and ask again rather than raising on a typo."""
    while True:
        answer = input("Give the Mc (Magnitude of Completeness): ").strip()
        try:
            return float(answer)
        except ValueError:
            print(f"'{answer}' is not a number; please try again")


def prompt_for_input(folder, default=None):
    """List the folder and ask for a file in it, re-asking until one exists."""
    if os.path.isdir(folder):
        print(f"\n{shown(folder)} folder:")
        for filename in sorted(os.listdir(folder)):
            print(f"    {filename}")
    else:
        print(f"The folder {shown(folder)} does not exist.")

    while True:
        name = ask_file_name("Please provide the name of the 6-column catalogue", default)
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
        print(f"{shown(path)} is not a file; please try again")


if __name__ == "__main__":
    proj = open_project()
    path = prompt_for_input(
        proj.results_dir,
        proj.recorded_name(proj.results_dir, "project", "catalogue_6col_file"))
    mc = prompt_for_mc()
    result, filtered_result = calculate_cumulative_earthquakes(
        path, mc, figures_dir=proj.figures_dir)
    proj.update("cumevents2.py",
                {"figures": {"cumulative_events": proj.rel(
                    os.path.join(proj.figures_dir, 'cumulative_earthquakes.png'))}},
                catalogue=proj.rel(path), mc=mc, events=len(result),
                events_above_mc=len(filtered_result))