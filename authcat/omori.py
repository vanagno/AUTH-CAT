#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AUTH-CAT Modified Omori Law analysis.

Workflow
--------
1. Read a standard AUTH-CAT 11-column earthquake catalogue.
2. Choose the beginning of the aftershock sequence:
      1 - start of catalogue
      2 - largest earthquake
      3 - specific date/time
3. Optionally filter events using a magnitude threshold (Mc).
4. Convert event times to days relative to the selected start.
5. Estimate Modified Omori parameters with the Bayesian fitting routine
   provided by omori_utils.
6. Run MCMC to estimate parameter uncertainty.
7. Save:
      Figures/Omori.png
      Figures/Omori_MCMC.png
      Results/Omori_fit_data.txt

Required additional packages:
    emcee
    corner

The script expects omori_utils to provide:
    bayes_logL(otimes, [c, p])
    bayes_getK(otimes, [c, p])
    omori(times, [c, K, p])
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import minimize

try:
    import emcee
except ImportError as exc:
    raise SystemExit(
        "Missing dependency 'emcee'. Install it with: pip install emcee"
    ) from exc

try:
    import corner
except ImportError as exc:
    raise SystemExit(
        "Missing dependency 'corner'. Install it with: pip install corner"
    ) from exc

try:
    import src.omori_utils as omori
except ModuleNotFoundError:
    try:
        import omori_utils as omori
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Could not import omori_utils. Expected either "
            "'src/omori_utils.py' or 'omori_utils.py'."
        ) from exc


RESULTS_DIR = Path("Results")
FIGURES_DIR = Path("Figures")

META = {
    "nbin": 60,
    "c_bound": [0.0001, 8.0],
    "K_bound": [2.0, 10000.0],
    "p_bound": [0.3, 2.0],
    "c0": 0.2,
    "p0": 0.8,
    "nwalkers": 32,
    "mcmc_steps": 5000,
    "burn_in": 100,
    "thin": 15,
    "random_seed": 42,
}


def list_catalogues() -> None:
    """Print text files currently available in Results/."""
    print("Results folder:")
    if not RESULTS_DIR.exists():
        print("  <Results folder not found>")
        return

    files = sorted(p.name for p in RESULTS_DIR.glob("*.txt"))
    if not files:
        print("  <no .txt files found>")
        return

    for name in files:
        print(f"  {name}")


def resolve_catalogue_path(user_input: str) -> Path:
    """Resolve either a direct path or a filename inside Results/."""
    supplied = Path(user_input.strip())

    if supplied.exists():
        return supplied

    candidate = RESULTS_DIR / supplied
    if candidate.exists():
        return candidate

    raise FileNotFoundError(
        f"Catalogue not found: '{user_input}'. "
        f"Checked both '{supplied}' and '{candidate}'."
    )


def read_authcat_catalogue(path: Path) -> pd.DataFrame:
    """
    Read the standard AUTH-CAT 11-column catalogue.

    Expected logical columns:
        Date Time Lat Lon Depth M RMS AzGap Nsta Msta ID

    Accepts either a catalogue with a header or a headerless catalogue in
    the standard AUTH-CAT column order.
    """
    expected_names = [
        "Date", "Time", "Lat", "Lon", "Depth", "M",
        "RMS", "AzGap", "Nsta", "Msta", "ID",
    ]

    try:
        df = pd.read_csv(path, sep=r"\s+", comment="#", engine="python")
    except Exception as exc:
        raise ValueError(f"Could not read catalogue '{path}': {exc}") from exc

    normalized = {str(col).strip().lower(): col for col in df.columns}

    def find_column(candidates: list[str]) -> str | None:
        for candidate in candidates:
            if candidate in normalized:
                return normalized[candidate]
        return None

    date_col = find_column(["date"])
    time_col = find_column(["time"])
    mag_col = find_column(["m", "mag", "magnitude"])

    if date_col is None or time_col is None or mag_col is None:
        df = pd.read_csv(
            path,
            sep=r"\s+",
            comment="#",
            header=None,
            engine="python",
        )

        if df.shape[1] < 11:
            raise ValueError(
                f"Catalogue '{path}' has {df.shape[1]} columns. "
                "The standard AUTH-CAT catalogue requires 11 columns."
            )

        df = df.iloc[:, :11].copy()
        df.columns = expected_names
        date_col = "Date"
        time_col = "Time"
        mag_col = "M"

    parsed = pd.DataFrame()
    parsed["datetime"] = pd.to_datetime(
        df[date_col].astype(str).str.strip()
        + " "
        + df[time_col].astype(str).str.strip(),
        errors="coerce",
    )
    parsed["mag"] = pd.to_numeric(df[mag_col], errors="coerce")

    lower_map = {str(col).strip().lower(): col for col in df.columns}

    for target, candidates in {
        "lat": ["lat", "latitude"],
        "lon": ["lon", "longitude"],
        "depth": ["depth"],
        "id": ["id"],
    }.items():
        source = next((lower_map[x] for x in candidates if x in lower_map), None)
        if source is not None:
            if target == "id":
                parsed[target] = df[source].astype(str)
            else:
                parsed[target] = pd.to_numeric(df[source], errors="coerce")

    parsed = parsed.dropna(subset=["datetime", "mag"]).copy()
    parsed = parsed.sort_values("datetime").reset_index(drop=True)

    if parsed.empty:
        raise ValueError("No valid earthquake records were found in the catalogue.")

    return parsed


def choose_start_time(catalogue: pd.DataFrame) -> tuple[pd.Timestamp, str]:
    """Interactively select the beginning of the aftershock sequence."""
    first_time = catalogue["datetime"].iloc[0]

    largest_idx = catalogue["mag"].idxmax()
    largest = catalogue.loc[largest_idx]
    largest_time = largest["datetime"]
    largest_mag = largest["mag"]

    print("\nSelect the starting point of the aftershock sequence:")
    print("  1 - Start of catalogue")
    print("  2 - Largest earthquake")
    print("  3 - Specific date/time")

    while True:
        choice = input("Choice [1/2/3]: ").strip()

        if choice == "1":
            print(f"Starting from catalogue beginning: {first_time}")
            return first_time, "catalogue_start"

        if choice == "2":
            print(
                "\nLargest earthquake:\n"
                f"  Time:      {largest_time}\n"
                f"  Magnitude: {largest_mag:.2f}"
            )

            if "id" in catalogue.columns:
                event_id = str(largest.get("id", "")).strip()
                if event_id and event_id.lower() != "nan":
                    print(f"  Event ID:  {event_id}")

            return largest_time, "largest_event"

        if choice == "3":
            while True:
                text = input(
                    "Enter start date/time [YYYY-MM-DD HH:MM:SS]: "
                ).strip()
                try:
                    start_time = pd.to_datetime(text, errors="raise")
                except Exception:
                    print("Invalid date/time. Example: 2024-03-04 17:11:12")
                    continue

                print(f"Starting from specified time: {start_time}")
                return start_time, "specific_datetime"

        print("Please enter 1, 2, or 3.")


def choose_magnitude_threshold() -> float | None:
    """Return an optional lower magnitude threshold."""
    while True:
        text = input(
            "\nEnter magnitude threshold Mc "
            "(press Enter to use all events): "
        ).strip()

        if text == "":
            return None

        try:
            return float(text)
        except ValueError:
            print("Please enter a numeric magnitude or press Enter.")


def prepare_aftershock_times(
    catalogue: pd.DataFrame,
    start_time: pd.Timestamp,
    magnitude_threshold: float | None,
) -> tuple[np.ndarray, pd.DataFrame]:
    """Select events and return positive relative times in days."""
    selected = catalogue[catalogue["datetime"] >= start_time].copy()

    if magnitude_threshold is not None:
        selected = selected[selected["mag"] >= magnitude_threshold].copy()

    selected["relative_days"] = (
        selected["datetime"] - start_time
    ).dt.total_seconds() / 86400.0

    selected = selected[
        np.isfinite(selected["relative_days"])
        & (selected["relative_days"] > 0)
    ].copy()

    selected = selected.sort_values("relative_days").reset_index(drop=True)
    otimes = selected["relative_days"].to_numpy(dtype=float)

    if len(otimes) < 3:
        raise ValueError(
            "Fewer than 3 aftershocks remain after the selected start time "
            "and magnitude filtering."
        )

    if len(otimes) < 20:
        print(
            "Warning: fewer than 20 aftershocks are being used. "
            "Parameter estimates may be poorly constrained."
        )

    return np.sort(otimes), selected


def fit_bayesian(otimes: np.ndarray) -> np.ndarray:
    """Estimate [c, K, p] using the Bayesian routines in omori_utils."""
    objective = lambda x: omori.bayes_logL(otimes, x)

    fit = minimize(
        objective,
        np.array([META["c0"], META["p0"]], dtype=float),
        bounds=np.array([META["c_bound"], META["p_bound"]], dtype=float),
        tol=1e-4,
        method="SLSQP",
        options={"disp": False, "maxiter": 500},
    )

    if not fit.success:
        raise RuntimeError(
            "Bayesian Modified Omori optimization failed: "
            f"{fit.message}"
        )

    _, K = omori.bayes_getK(otimes, fit.x)
    c, p = fit.x
    params = np.array([c, K, p], dtype=float)

    c1, c2 = META["c_bound"]
    K1, K2 = META["K_bound"]
    p1, p2 = META["p_bound"]

    if not (c1 < c < c2 and K1 < K < K2 and p1 < p < p2):
        print(
            "Warning: fitted parameters lie on or outside the MCMC prior "
            "bounds. Consider adjusting META."
        )

    return params


def log_prior(theta: np.ndarray, otimes: np.ndarray) -> float:
    """Uniform prior on c and p, with K constrained after derivation."""
    c, p = theta
    c1, c2 = META["c_bound"]
    p1, p2 = META["p_bound"]
    K1, K2 = META["K_bound"]

    if not (c1 < c < c2 and p1 < p < p2):
        return -np.inf

    try:
        _, K = omori.bayes_getK(otimes, np.array([c, p], dtype=float))
    except Exception:
        return -np.inf

    if not np.isfinite(K) or not (K1 < K < K2):
        return -np.inf

    return 0.0


def log_probability(theta: np.ndarray, otimes: np.ndarray) -> float:
    """Posterior probability using the same Bayesian objective as the fit."""
    prior = log_prior(theta, otimes)
    if not np.isfinite(prior):
        return -np.inf

    objective = omori.bayes_logL(otimes, theta)
    if not np.isfinite(objective):
        return -np.inf

    # bayes_logL is minimized by scipy, so negate it for emcee.
    return prior - float(objective)


def initialize_walkers(
    center: np.ndarray,
    nwalkers: int,
    rng: np.random.Generator,
    otimes: np.ndarray,
) -> np.ndarray:
    """Initialize c,p walkers close to the Bayesian solution."""
    bounds = np.array(
        [META["c_bound"], META["p_bound"]],
        dtype=float,
    )
    spans = bounds[:, 1] - bounds[:, 0]
    scales = 0.005 * spans

    walkers = []
    attempts = 0
    max_attempts = nwalkers * 1000

    while len(walkers) < nwalkers and attempts < max_attempts:
        proposal = center + rng.normal(0.0, scales)
        attempts += 1

        if np.isfinite(log_prior(proposal, otimes)):
            walkers.append(proposal)

    if len(walkers) < nwalkers:
        raise RuntimeError(
            "Could not initialize MCMC walkers inside the parameter bounds. "
            "Check the Bayesian fit and META bounds."
        )

    return np.asarray(walkers, dtype=float)


def run_mcmc(
    otimes: np.ndarray,
    initial_params: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Run MCMC on c and p using the Bayesian objective.

    K is derived for every retained c,p sample with bayes_getK so the returned
    samples and percentiles are ordered [c, K, p].
    """
    ndim = 2
    nwalkers = int(META["nwalkers"])

    if nwalkers < 2 * ndim:
        raise ValueError(
            f"nwalkers must be at least {2 * ndim} for {ndim} parameters."
        )

    rng = np.random.default_rng(META["random_seed"])
    center = np.array([initial_params[0], initial_params[2]], dtype=float)
    positions = initialize_walkers(center, nwalkers, rng, otimes)

    sampler = emcee.EnsembleSampler(
        nwalkers,
        ndim,
        log_probability,
        args=(otimes,),
    )
    sampler.run_mcmc(
        positions,
        int(META["mcmc_steps"]),
        progress=True,
    )

    burn_in = int(META["burn_in"])
    thin = int(META["thin"])

    if burn_in >= META["mcmc_steps"]:
        raise ValueError("burn_in must be smaller than mcmc_steps.")

    cp_samples = sampler.get_chain(
        discard=burn_in,
        thin=thin,
        flat=True,
    )

    if cp_samples.size == 0:
        raise RuntimeError("MCMC produced no retained samples.")

    derived_samples = []
    for c, p in cp_samples:
        try:
            _, K = omori.bayes_getK(
                otimes,
                np.array([c, p], dtype=float),
            )
        except Exception:
            continue

        if np.isfinite(K):
            derived_samples.append([c, K, p])

    flat_samples = np.asarray(derived_samples, dtype=float)

    if flat_samples.size == 0:
        raise RuntimeError("Could not derive K for the retained MCMC samples.")

    percentiles = np.percentile(flat_samples, [16, 50, 84], axis=0)
    return flat_samples, percentiles


def make_decay_plot(
    otimes: np.ndarray,
    bayes_params: np.ndarray,
    output_path: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create the decay plot and return the exported bin data."""
    tmin = float(np.min(otimes))
    tmax = float(np.max(otimes))

    if tmin <= 0:
        raise ValueError("Relative aftershock times must be strictly positive.")
    if tmax <= tmin:
        raise ValueError(
            "The selected events do not span enough time for logarithmic binning."
        )

    bins = np.logspace(
        np.log10(tmin),
        np.log10(tmax),
        int(META["nbin"]),
    )

    count, edges = np.histogram(otimes, bins=bins)
    bin_loc = (edges[1:] + edges[:-1]) / 2.0
    occ_dens = count / np.diff(edges)
    fit_values = omori.omori(bin_loc, bayes_params)

    fig, ax = plt.subplots(figsize=(10, 8))

    positive = occ_dens > 0
    ax.scatter(
        bin_loc[positive],
        occ_dens[positive],
        s=80,
        edgecolors="k",
        facecolors="lightgrey",
        label=f"{len(otimes)} events",
    )
    ax.plot(
        bin_loc,
        fit_values,
        color="b",
        linewidth=2,
        label="Bayesian fit",
    )

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Days after sequence start")
    ax.set_ylabel("# events/day")
    ax.set_title("Aftershock Decay")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

    return bin_loc, occ_dens, fit_values


def make_corner_plot(flat_samples: np.ndarray, output_path: Path) -> None:
    """Create the MCMC corner plot."""
    fig = corner.corner(
        flat_samples,
        labels=["c", "K", "p"],
        quantiles=[0.16, 0.5, 0.84],
        show_titles=True,
    )
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_fit_data(
    output_path: Path,
    bin_loc: np.ndarray,
    occ_dens: np.ndarray,
    fit_values: np.ndarray,
) -> None:
    """Save binned observed rates and Bayesian fit values."""
    with output_path.open("w", encoding="utf-8") as f:
        f.write("# Bin_Location_Days Occurrence_Density Bayesian_Fit\n")
        for x, y, b in zip(bin_loc, occ_dens, fit_values):
            f.write(f"{x:.6f} {y:.6f} {b:.6f}\n")


def print_mcmc_summary(percentiles: np.ndarray) -> None:
    """Print median and 16th/84th percentile uncertainty."""
    q16, q50, q84 = percentiles
    labels = ["c", "K", "p"]

    print("\nMCMC parameter estimates (median, 16th-84th percentile):")
    for i, label in enumerate(labels):
        lower = q50[i] - q16[i]
        upper = q84[i] - q50[i]
        print(
            f"  {label} = {q50[i]:.6g} "
            f"(+{upper:.3g} / -{lower:.3g})"
        )


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    list_catalogues()

    catalogue_name = input(
        "\nPlease enter the earthquake catalogue: "
    ).strip()

    if not catalogue_name:
        raise SystemExit("No catalogue was provided.")

    try:
        catalogue_path = resolve_catalogue_path(catalogue_name)
        catalogue = read_authcat_catalogue(catalogue_path)
    except Exception as exc:
        raise SystemExit(f"Error: {exc}") from exc

    print(
        f"\nLoaded {len(catalogue)} events from "
        f"{catalogue_path.as_posix()}."
    )
    print(
        f"Catalogue time span: "
        f"{catalogue['datetime'].iloc[0]} to "
        f"{catalogue['datetime'].iloc[-1]}"
    )

    start_time, start_mode = choose_start_time(catalogue)
    magnitude_threshold = choose_magnitude_threshold()

    try:
        otimes, _ = prepare_aftershock_times(
            catalogue,
            start_time,
            magnitude_threshold,
        )
    except Exception as exc:
        raise SystemExit(f"Error: {exc}") from exc

    print("\nModified Omori analysis selection:")
    print(f"  Start mode:   {start_mode}")
    print(f"  Start time:   {start_time}")
    if magnitude_threshold is None:
        print("  Magnitude:    all events")
    else:
        print(f"  Magnitude:    M >= {magnitude_threshold:g}")
    print(f"  Events used:  {len(otimes)}")
    print(
        f"  Time span:    {otimes[0]:.6g} to "
        f"{otimes[-1]:.6g} days"
    )

    print("\nEstimating Bayesian Modified Omori parameters...")

    try:
        bayes_params = fit_bayesian(otimes)
    except Exception as exc:
        raise SystemExit(f"Error: {exc}") from exc

    c_fit, K_fit, p_fit = bayes_params

    print("\nBayesian Modified Omori parameters:")
    print(f"  K = {K_fit:.6g}")
    print(f"  c = {c_fit:.6g}")
    print(f"  p = {p_fit:.6g}")

    omori_figure = FIGURES_DIR / "Omori.png"
    mcmc_figure = FIGURES_DIR / "Omori_MCMC.png"
    fit_data_file = RESULTS_DIR / "Omori_fit_data.txt"

    try:
        bin_loc, occ_dens, fit_values = make_decay_plot(
            otimes,
            bayes_params,
            omori_figure,
        )
    except Exception as exc:
        raise SystemExit(f"Error creating Omori plot: {exc}") from exc

    print("\nRunning MCMC uncertainty analysis...")

    try:
        flat_samples, percentiles = run_mcmc(
            otimes,
            bayes_params,
        )
    except Exception as exc:
        raise SystemExit(f"Error during MCMC: {exc}") from exc

    try:
        make_corner_plot(flat_samples, mcmc_figure)
        save_fit_data(
            fit_data_file,
            bin_loc,
            occ_dens,
            fit_values,
        )
    except Exception as exc:
        raise SystemExit(f"Error saving outputs: {exc}") from exc

    print_mcmc_summary(percentiles)

    print("\nOutputs:")
    print(f"  Modified Omori plot: {omori_figure.as_posix()}")
    print(f"  MCMC corner plot:    {mcmc_figure.as_posix()}")
    print(f"  Fit data:            {fit_data_file.as_posix()}")


if __name__ == "__main__":
    main()
