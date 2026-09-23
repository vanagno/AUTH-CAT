import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter
from geopy.distance import geodesic
from obspy.core.utcdatetime import UTCDateTime as UTC
from scipy.optimize import minimize
import emcee
import corner

# Function to read earthquake catalog
def read_earthquake_catalog(filename):
    df = pd.read_csv(filename, delim_whitespace=True)
    df['Datetime'] = pd.to_datetime(df['Date'] + ' ' + df['Time'])
    return df

# Function to filter catalog based on the chosen start time
def filter_catalog(df, start_time):
    if start_time is not None:
        df = df[df['Datetime'] >= start_time]
    df = df.reset_index(drop=True)
    return df

# Function to process the catalog and extract required data
def process_catalog(df):
    evid = np.arange(len(df))
    obdt = df['Datetime'].apply(lambda x: UTC(x.isoformat())).values
    pydt = df['Datetime'].values
    relt = (df['Datetime'] - df['Datetime'].min()).dt.total_seconds() / 86400  # Convert to days
    lat = df['Lat'].values
    lon = df['Lon'].values
    dep = df['Depth'].values
    mag = df['M'].values
    
    t_start = obdt.min()
    t_termi = obdt.max()
    
    # Identify the event with the largest magnitude
    ms_id = np.argmax(mag)
    
    ms = {
        'id': evid[ms_id], 
        'obdt': obdt[ms_id], 
        'pydt': pydt[ms_id], 
        'tAMS': relt[ms_id],
        'lat': lat[ms_id], 
        'lon': lon[ms_id], 
        'dep': dep[ms_id], 
        'mag': mag[ms_id]
    }
    
    meta = {
        't_start': t_start,
        't_termi': t_termi,
        'Mcut': min(mag),
        'rmax': 10 ** (0.25 * ms['mag'] - .22), 
        'nbin': 100,
        'c_bound': [1e-3, 10],
        'K_bound': [1, 1e3],
        'p_bound': [.1, 2.5],
        'c0': 1,
        'K0': 100,
        'p0': 1.1,
        'ylim': [1e-3, 1e5],
        'xlim': [1e-3, 1e3],
    }
    
    return evid, obdt, pydt, relt, lat, lon, dep, mag, ms, meta

# Function to create the plot
def create_aftershocks_decay_plot(obdt, relt, ms, meta, save_dir, base_filename):
    relt = relt - ms['tAMS']
    otimes = np.array(sorted(relt))  # In days

    def omori(t, params):
        c, K, p = params
        with np.errstate(divide='ignore', invalid='ignore'):
            result = K / (t + c) ** p
            result[~np.isfinite(result)] = 0  # Replace invalid values with zero
        return result
    
    def dtimes(obdt):
        eqtimestamps = [UTC(eqt).timestamp for eqt in obdt]
        days_after_mainshock = (np.array(eqtimestamps) - eqtimestamps[0]) / 86400.0  # Convert to days
        max_days = days_after_mainshock.max()
        bins = np.arange(0, max_days + 1, 1)  # Bin by days
        event_counts, bin_edges = np.histogram(days_after_mainshock, bins=bins)
        bin_loc = (bin_edges[1:] + bin_edges[:-1]) / 2
        return event_counts, bin_loc

    occ_dens, bin_loc = dtimes(obdt)
    
    # Fit the Omori law parameters using maximum likelihood estimation
    def log_likelihood(params):
        c, K, p = params
        if c <= 0 or K <= 0 or p <= 0:
            return np.inf
        model = omori(otimes, params)
        if np.any(model <= 0):
            return np.inf
        return -np.sum(np.log(model))
    
    initial_params = [meta['c0'], meta['K0'], meta['p0']]
    bounds = [meta['c_bound'], meta['K_bound'], meta['p_bound']]
    
    # Ogata 1989: MLE
    ogata_fit = minimize(log_likelihood, initial_params, bounds=bounds, method='L-BFGS-B')
    ogata_params = ogata_fit.x
    print(f'Ogata MLE fit: c={ogata_params[0]:.2f}, K={ogata_params[1]:.2f}, p={ogata_params[2]:.2f}')
    
    # Holschneider et al., 2012: Bayesian
    def log_prior(theta):
        c, K, p = theta
        if meta['c_bound'][0] < c < meta['c_bound'][1] and meta['K_bound'][0] < K < meta['K_bound'][1] and meta['p_bound'][0] < p < meta['p_bound'][1]:
            return 0.0
        return -np.inf

    def log_probability(theta):
        lp = log_prior(theta)
        if not np.isfinite(lp):
            return -np.inf
        return lp - log_likelihood(theta)
    
    # Initialize walkers in gaussian ball around minimized result
    pos0 = ogata_params
    nwalkers = 32
    ndim = len(pos0)
    pos = pos0 + 1e-3 * np.random.randn(nwalkers, ndim)
    sampler = emcee.EnsembleSampler(nwalkers, ndim, log_probability)
    
    # Debug: check initial positions
    initial_log_probs = [log_probability(p) for p in pos]
    print(f"Initial log probabilities: {initial_log_probs}")
    
    if any(np.isnan(initial_log_probs)):
        raise ValueError("Initial position has non-finite log probability.")
    
    sampler.run_mcmc(pos, 5000, progress=True)
    
    # Check MCMC results
    flat_samples = sampler.get_chain(discard=100, thin=15, flat=True)
    sol_c, sol_K, sol_p = np.percentile(flat_samples, [50], axis=0)[0]
    print(f'Holschneider Bayesian fit: c={sol_c:.2f}, K={sol_K:.2f}, p={sol_p:.2f}')
    
    # Plotting results
    plt.figure(figsize=[10, 8])
    plt.bar(bin_loc, occ_dens, width=1, ec='k', fc='lightgrey', label='%d events' % len(otimes))
    
    # Plot the best fit Omori law
    t_fit = np.linspace(0, bin_loc[-1], 1000)
    plt.plot(t_fit, omori(t_fit, ogata_params), 'r-', lw=2, label=f'Ogata fit: c={ogata_params[0]:.2f}, K={ogata_params[1]:.2f}, p={ogata_params[2]:.2f}')
    plt.plot(t_fit, omori(t_fit, [sol_c, sol_K, sol_p]), 'b-', lw=2, label=f'Holschneider fit: c={sol_c:.2f}, K={sol_K:.2f}, p={sol_p:.2f}')
    
    plt.xlabel('Days after mainshock')
    plt.ylabel('# events/day')
    plt.title('Aftershocks decay')
    plt.legend()
    plt.tight_layout()
    plt.savefig(f'{save_dir}/{base_filename}_Plot6.png', dpi=100)
    plt.show()

# Main script to read the data and generate the plot
filename = 'Results/test_cat.txt'  # Replace with your actual file path
save_dir = 'Results'  # Replace with your actual directory
base_filename = 'test'  # Replace with your actual base filename

df = read_earthquake_catalog(filename)

# Prompt the user if they want to start from the beginning of the catalog
start_choice = input("Do you want to start from the beginning of the catalog? (yes/no): ").strip().lower()

if start_choice == 'yes':
    start_time = None
else:
    # Prompt the user if they want to start from the largest earthquake
    largest_eq_index = df['M'].idxmax()
    largest_eq_datetime = df.loc[largest_eq_index, 'Datetime']
    largest_eq_choice = input(f"The largest earthquake occurred on {largest_eq_datetime}. Do you want to start from this earthquake? (yes/no): ").strip().lower()
    
    if largest_eq_choice == 'yes':
        start_time = largest_eq_datetime
    else:
        # Ask the user for a specific date and time to start the fitting from there
        start_time = input("Please provide a specific start date and time in the format 'YYYY-MM-DD HH:MM:SS': ").strip()
        start_time = pd.to_datetime(start_time)

# Filter the catalog based on the chosen start time
filtered_df = filter_catalog(df, start_time)

evid, obdt, pydt, relt, lat, lon, dep, mag, ms, meta = process_catalog(filtered_df)
create_aftershocks_decay_plot(obdt, relt, ms, meta, save_dir, base_filename)
