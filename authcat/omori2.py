import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import minimize
import scipy.integrate as integrate
import emcee
import corner
from obspy.core.utcdatetime import UTCDateTime as UTC
from project import open_project, shown

# Read the catalog
def read_catalog(filename):
    df = pd.read_csv(filename, sep=r"\s+")
    df['Datetime'] = pd.to_datetime(df['Date'] + ' ' + df['Time'], errors='coerce')
    return df


# Keep the events between the start and end times
def filter_catalog(df, start_time=None, end_time=None):
    if start_time is not None:
        df = df[df['Datetime'] >= start_time]
    if end_time is not None:
        df = df[df['Datetime'] <= end_time]
    df = df.reset_index(drop=True)
    return df

# Omori function
def omori(t, c, K, p):
    return K / (t + c) ** p

# Bin event times into histogram
def compute_histogram(times, bin_width=1.0):
    max_day = times.max()
    bins = np.arange(0, max_day + bin_width, bin_width)
    counts, edges = np.histogram(times, bins=bins)
    bin_centers = (edges[:-1] + edges[1:]) / 2
    return counts, edges, bin_centers

# Log-likelihood: Poisson between observed and expected
def log_likelihood(params, edges, observed_counts):
    c, K, p = params
    if c <= 0 or K <= 0 or p <= 0:
        return -np.inf
    expected = np.array([
        integrate.quad(lambda t: omori(t, c, K, p), edges[i], edges[i + 1])[0]
        for i in range(len(edges) - 1)
    ])
    expected[expected <= 0] = 1e-10  # prevent log(0)
    return -np.sum(expected - observed_counts * np.log(expected))

# Log-prior and log-prob for MCMC
def log_prior(theta, bounds):
    for val, (low, high) in zip(theta, bounds):
        if not (low < val < high):
            return -np.inf
    return 0.0

def log_prob(theta, edges, observed_counts, bounds):
    lp = log_prior(theta, bounds)
    if not np.isfinite(lp):
        return -np.inf
    return lp + log_likelihood(theta, edges, observed_counts)

# Main processing and plotting
def fit_and_plot(df, save_dir, base_filename, start_time=None, end_time=None):
    """Fit the modified Omori law, plot it and return the fit for the project record."""
    df = filter_catalog(df, start_time, end_time)
    mags = df['M'].values
    times = (df['Datetime'] - df['Datetime'].min()).dt.total_seconds() / 86400  # in days

    # Histogram
    counts, edges, centers = compute_histogram(times)

    # Initial params
    initial = [0.5, 100, 1.0]
    bounds = [(1e-3, 10), (1, 1e4), (0.1, 2.5)]

    # Ogata MLE
    mle_result = minimize(lambda x: -log_likelihood(x, edges, counts), initial, bounds=bounds)
    c_mle, K_mle, p_mle = mle_result.x
    print(f"Ogata MLE fit: c={c_mle:.2f}, K={K_mle:.0f}, p={p_mle:.2f}")

    # MCMC
    ndim, nwalkers = 3, 32
    pos = mle_result.x + 1e-3 * np.random.randn(nwalkers, ndim)
    sampler = emcee.EnsembleSampler(nwalkers, ndim, log_prob, args=(edges, counts, bounds))
    sampler.run_mcmc(pos, 3000, progress=True)
    flat_samples = sampler.get_chain(discard=500, thin=10, flat=True)
    c_bayes, K_bayes, p_bayes = np.percentile(flat_samples, 50, axis=0)
    print(f"Bayesian fit: c={c_bayes:.2f}, K={K_bayes:.0f}, p={p_bayes:.2f}")

    # Plotting
    t_fit = np.linspace(centers[0], centers[-1], 500)
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.bar(centers, counts, width=edges[1] - edges[0], color='lightgray', edgecolor='k',)# label=f'{sum(counts)} events')

    # --- Scaling for visual match with first histogram bin ---
    if counts[0] > 0:
        mle_scale = counts[0] / omori(centers[0], c_mle, K_mle, p_mle)
        bayes_scale = counts[0] / omori(centers[0], c_bayes, K_bayes, p_bayes)
    else:
        mle_scale = bayes_scale = 1  # fallback

    # Plot scaled Omori fits
    ax.plot(t_fit, omori(t_fit, c_mle, K_mle, p_mle) * mle_scale, 'r-', label=f'Ogata MLE  c={c_mle:.2f},  p={p_mle:.2f}, K={K_mle:.0f}'),
    #ax.plot(t_fit, omori(t_fit, c_bayes, K_bayes, p_bayes) * bayes_scale, 'b-', label=f'Bayesian (scaled): c={c_bayes:.2f}, K={K_bayes:.0f}, p={p_bayes:.2f}')

    start_str = start_time.strftime("%Y-%m-%d %H:%M:%S") if start_time else df['Datetime'].min().strftime("%Y-%m-%d %H:%M:%S")
    ax.set_xlabel(f'Days after {start_str}')
    ax.set_ylabel('# events/day')
    ax.set_title('Modified Omori fit')
    ax.legend()
    plt.tight_layout()
    figure = os.path.join(save_dir, f'{base_filename}_omori_fit.png')
    os.makedirs(save_dir, exist_ok=True)
    plt.savefig(figure, dpi=100)
    plt.show()
    print(f"Modified Omori fit saved to {shown(figure)}")
    return {
        "start_time": df['Datetime'].min().isoformat(),
        "end_time": df['Datetime'].max().isoformat(),
        "events": len(df),
        "K": round(float(K_mle), 2), "c": round(float(c_mle), 2), "p": round(float(p_mle), 2),
        "bayesian": {"K": round(float(K_bayes), 2), "c": round(float(c_bayes), 2),
                     "p": round(float(p_bayes), 2)},
        "figure": figure,
    }

proj = open_project()
input_folder = proj.results_dir
if os.path.isdir(input_folder):
    print(f"{shown(input_folder)} folder:")
    for name in os.listdir(input_folder):
        print(name)
else:
    print(f"The folder {shown(input_folder)} does not exist.")
filename = os.path.join(input_folder, input("Please enter the name of the earthquake catalogue: ").strip())
df = read_catalog(filename)

# # Ask user
# start_choice = input("Start from largest EQ? (yes/no): ").strip().lower()
# if start_choice == 'yes':
#     largest_eq = df.loc[df['M'].idxmax()]
#     start_time = largest_eq['Datetime']
# else:
#     start_time = None



print("\nHow would you like to set the start time?")
print("1 - Start from largest earthquake (max magnitude)")
print("2 - Enter a specific date and time (format: YYYY-MM-DD HH:MM:SS)")
print("3 - Use entire catalog from beginning")
choice = input("Enter your choice (1/2/3): ").strip()

if choice == '1':
    largest_eq = df.loc[df['M'].idxmax()]
    start_time = largest_eq['Datetime']
    fit_start = "largest_event"
    print(f"Starting from largest EQ at {start_time}, M={largest_eq['M']:.1f}")

elif choice == '2':
    custom_str = input("Enter start date and time (YYYY-MM-DD HH:MM:SS): ").strip()
    try:
        start_time = pd.to_datetime(custom_str)
        fit_start = start_time.isoformat()
        print(f"Using custom start time: {start_time}")
    except Exception as e:
        print("Invalid format. Please use YYYY-MM-DD HH:MM:SS. Exiting.")
        exit()

elif choice == '3':
    start_time = None
    fit_start = "catalogue_start"
    print("Using entire catalog from beginning.")
else:
    print("Invalid choice. Exiting.")
    exit()

# The end time is asked whichever start was chosen
first = start_time if start_time is not None else df['Datetime'].min()
while True:
    try:
        end_str = input("Enter end date and time (YYYY-MM-DD HH:MM:SS, blank = end of catalog): ").strip()
    except EOFError:
        end_str = ""
    if not end_str:
        end_time = None
        fit_end = "catalogue_end"
        print("Using the catalog up to its last event.")
        break
    try:
        end_time = pd.to_datetime(end_str)
    except (ValueError, TypeError):
        print("Invalid format. Please use YYYY-MM-DD HH:MM:SS.")
        continue
    n_events = ((df['Datetime'] >= first) & (df['Datetime'] <= end_time)).sum()
    if n_events < 2:
        print(f"Only {n_events} events between {first} and {end_time}; please give a later end time.")
        continue
    fit_end = end_time.isoformat()
    print(f"Using custom end time: {end_time}")
    break

fit = fit_and_plot(df, proj.figures_dir, 'aftershock_decay', start_time, end_time)
fit["figure"] = proj.rel(fit["figure"])
proj.update("omori2.py", {"modified_omori": {"fit_start": fit_start, "fit_end": fit_end, **fit}},
            catalogue=proj.rel(filename))
