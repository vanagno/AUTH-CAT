import numpy as np
import pandas as pd
import math
import matplotlib.pyplot as plt
import os
from authcat.project import ask_file_name, open_project, shown, watermark

plt.rcParams["figure.figsize"] = (8, 5)

proj = open_project()
input_folder = proj.results_dir
if os.path.isdir(input_folder):
    print(f"{shown(input_folder)} folder:")
    for filename in os.listdir(input_folder):
        print(filename)
else:
    print(f"The folder {shown(input_folder)} does not exist.")
file_path = ask_file_name("Please enter the file path of the 6-column earthquake catalogue", proj.recorded_name(input_folder, "project", "catalogue_6col_file")) 
input_file_path = os.path.join(input_folder, file_path)    
catalog = pd.read_csv(input_file_path, sep=r"\s+", header=None, usecols=[5])
catalog.columns = ['mw']

#------------------- Frequency-magnitude distribution --------------------#
def fmd(mag, mbin):
    minmag = math.floor(min(mag) / mbin) * mbin
    maxmag = math.ceil(max(mag) / mbin) * mbin
    mi = np.arange(minmag, maxmag + mbin, mbin)
    nbm = len(mi)
    cumnbmag = np.zeros(nbm)

    for i in range(nbm):
        cumnbmag[i] = np.where(mag > mi[i] - mbin/2)[0].shape[0]
    
    nbmag = abs(np.diff(np.append(cumnbmag, 0)))    
    return mi, nbmag, cumnbmag

cat_mi, cat_nbmag, cat_cumnbmag = fmd(mag=catalog['mw'], mbin=0.1)

plt.figure()
plt.plot(cat_mi, cat_cumnbmag, marker='o', markersize=8, markerfacecolor='red', linestyle='None', color='black', label="Cumulative")
plt.plot(cat_mi, cat_nbmag, marker='s', markersize=8, markerfacecolor='white', linestyle='None', color='black', label="Incremental")
plt.yscale('log')
plt.xlabel('Magnitude')
plt.ylabel('Frequency')
plt.title('FMD plot')
plt.legend(loc="upper right")
directory = proj.figures_dir
output_file = os.path.join(directory,'FMD_plot.png')
os.makedirs(directory, exist_ok=True)
watermark()
plt.savefig(output_file)
plt.show()
print(f"Frequency-Magnitude distribution plot saved to {shown(output_file)}")


#---------- b-value estimation with the maximum likelihood method  -------#

def b_est(mag, mbin, mc):
    
    mag_above_mc = mag[np.where(mag > round(mc,1)-mbin/2)[0]].values
    n = mag_above_mc.shape[0]
    if n < 2:
        a = np.nan
        b = np.nan
        aki_unc = np.nan
        shibolt_unc = np.nan
    else:
        mbar = np.mean(mag_above_mc)
        b = math.log10(math.exp(1)) / (mbar - (mc - mbin/2))
        a = math.log10(n) + b * mc
        aki_unc = b / math.sqrt(n)
        shibolt_unc = 2.3 * b**2 * math.sqrt(sum((mag_above_mc - mbar)**2) / (n * (n-1)))

    return a, b, aki_unc, shibolt_unc


def method_result(mc, b, unc, **extra):
    """One method's entry in the summary and the project record."""
    return {"mc": round(float(mc), 1), "b_value": round(float(b), 2),
            "b_value_uncertainty": round(float(unc), 2), **extra}

#------------- Mc estimation with the MAXC method ------------------------#

def get_maxc(mag, mbin):
    this_fmd = fmd(mag, mbin)
    maxc = this_fmd[0][np.argmax(this_fmd[1])]
    return round(maxc, 1)
    
cat_mc = get_maxc(mag = catalog['mw'], mbin = 0.1)
cat_a, cat_b, cat_aki_unc, cat_shibolt_unc = b_est(mag = catalog['mw'], mbin = 0.1, mc = cat_mc)
maxc_result = method_result(cat_mc, cat_b, cat_shibolt_unc)

plt.figure()
plt.plot(cat_mi, cat_cumnbmag, marker='o', markersize=8, markerfacecolor='red', linestyle='None', color='black')
plt.plot(cat_mi, cat_nbmag, marker='s', markersize=8, markerfacecolor='white', linestyle='None', color='black')
plt.plot(cat_mi, (10**(cat_a - (cat_b * cat_mi))), linewidth=3, color='black')

plt.vlines(cat_mc, ymin=1, ymax=10**math.ceil(math.log10(catalog.shape[0])), linestyles='dashed')

plt.yscale('log')
plt.ylim(1, 10**math.ceil(math.log10(catalog.shape[0])))
plt.xlabel('Magnitude')
plt.ylabel('Frequency')
plt.title('MAXC')
plt.text(x=cat_mc+0.07, y=2, s="Mc=" + str(round(cat_mc, 1)))
plt.text(x=cat_mc+0.07, y=1.2, s="b-value = " + str(round(cat_b, 2)) + " +/- " + str(round(cat_shibolt_unc, 2)))
output_file = os.path.join(directory,'MAXC.png')
os.makedirs(directory, exist_ok=True)
watermark()
plt.savefig(output_file)
plt.show()
print(f"MAXC plot saved to {shown(output_file)}")

#---------------- Mc estimation with the GFT method ----------------------#

def get_gft(mag, mbin):
    this_fmd = fmd(mag, mbin)
    this_maxc = get_maxc(mag, mbin)

    a = np.zeros(this_fmd[0].shape[0])
    b = np.zeros(this_fmd[0].shape[0])
    R = np.zeros(this_fmd[0].shape[0])

    for i in range(this_fmd[0].shape[0]):
        mi = round(this_fmd[0][i], 1)
        try:
            a[i], b[i], tmp1, tmp2 = b_est(mag, mbin, mi)
        except:
            continue
        synthetic_gr = 10**(a[i] - b[i]*this_fmd[0])
        Bi = this_fmd[2][i:]
        Si = synthetic_gr[i:]
        R[i] = (sum(abs(Bi - Si)) / sum(Bi)) * 100

    R_to_test = [95, 90]

    GFT_test = [np.where(R <= (100 - conf_level)) for conf_level in R_to_test]
    # The confidence level reached, or None when neither was and MAXC stands in
    mc, conf = this_maxc, None
    for conf_level, test in zip(R_to_test, GFT_test):
        if len(test[0]) > 0:
            mc = round(this_fmd[0][test[0][0]], 1)
            conf = conf_level
            break
    else:
        print("No fits within confidence levels, using MAXC estimate")
    
    return mc, this_fmd[0], R, conf

cat_gft = get_gft(mag = catalog['mw'], mbin = 0.1) # GFT completeness magnitude

plt.figure()
plt.plot(cat_gft[1], cat_gft[2], color="red")
plt.plot(cat_gft[1], cat_gft[2], 'D', color="darkred", markersize=6, label="GFT for each cut-off mag")
plt.vlines(cat_gft[0], ymin=0, ymax=100, linestyles='dashed', label="GFT Mc = " + str(round(cat_gft[0], 1)))
plt.hlines(5, xmin=-3, xmax=5, linestyles='dashed', colors='k')
plt.hlines(10, xmin=-3, xmax=5, linestyles='dashed', colors='k')
plt.text(x=4.4, y=10.7, s="GFT90%")
plt.text(x=4.4, y=5.7, s="GFT95%")
plt.ylim(0, 25)
plt.xlim(0, 5)
plt.xlabel('Cut-off magnitude')
plt.ylabel('Residuals')
plt.title('GFT plot')
plt.legend(loc='upper right')
output_file = os.path.join(directory,'GFT_plot.png')
os.makedirs(directory, exist_ok=True)
watermark()
plt.savefig(output_file)
plt.show()
print(f"Goodness-of-Fit residual plot saved to {shown(output_file)}")

cat_mc = cat_gft[0] # GFT completeness magnitude
cat_a, cat_b, cat_aki_unc, cat_shibolt_unc = b_est(mag = catalog['mw'], mbin = 0.1, mc = cat_mc)
gft_result = method_result(cat_mc, cat_b, cat_shibolt_unc, goodness_of_fit_percent=cat_gft[3])

plt.figure()
plt.plot(cat_mi, cat_cumnbmag, marker='o', markersize=8, markerfacecolor='red', linestyle='None', color='black')
plt.plot(cat_mi, cat_nbmag, marker='s', markersize=8, markerfacecolor='white', linestyle='None', color='black')
plt.plot(cat_mi, (10**(cat_a - (cat_b * cat_mi))), linewidth=3, color='black')
plt.vlines(cat_mc, ymin=1, ymax=10**math.ceil(math.log10(catalog.shape[0])), linestyles='dashed')
plt.yscale('log')
plt.ylim(1, 10**math.ceil(math.log10(catalog.shape[0])))
plt.xlabel('Magnitude')
plt.ylabel('Frequency')
plt.title('GFT')
plt.text(x=cat_mc+0.07, y=2, s="Mc = " + str(round(cat_mc, 1)))
plt.text(x=cat_mc+0.07, y=1.2, s="b-value = " + str(round(cat_b, 2)) + " +/- " + str(round(cat_shibolt_unc, 2)))
output_file = os.path.join(directory,'GFT.png')
os.makedirs(directory, exist_ok=True)
watermark()
plt.savefig(output_file)
plt.show()
print(f"Goodness-of-Fit plot saved to {shown(output_file)}")

#---------------- Mc estimation with the MBS method ----------------------#

def get_mbs(mag, mbin, dM = 0.4, min_mc = -3):

    this_fmd = fmd(mag, mbin)
    this_maxc = get_maxc(mag, mbin)

    a = np.zeros(this_fmd[0].shape[0])
    b = np.zeros(this_fmd[0].shape[0])
    b_avg = np.zeros(this_fmd[0].shape[0])
    shibolt_unc = np.zeros(this_fmd[0].shape[0])

    for i in range(this_fmd[0].shape[0]):
        mi = round(this_fmd[0][i], 1)
        if this_fmd[2][i] > 1:
            a[i], b[i], tmp1, shibolt_unc[i] = b_est(mag, mbin, mi)
        else:
            a[i] = np.nan
            b[i] = np.nan
            shibolt_unc[i] = np.nan

    no_bins = round(dM/mbin)
    check_bval_stability = []
    for i in range(this_fmd[0].shape[0]):
        if i >= this_fmd[0].shape[0] - (no_bins + 1):
            b_avg[i] = np.nan
            next
        if any(np.isnan(b[i:(i+no_bins+1)])):
            b_avg[i] = np.nan
            check_bval_stability.append(False)
        else:
            b_avg[i] = np.mean(b[i:(i+no_bins+1)])
            check_bval_stability.append(abs(b_avg[i] - b[i]) <= shibolt_unc[i])

    if any(check_bval_stability):
        bval_stable_points = this_fmd[0][np.array(check_bval_stability)]
        mc = round(min(bval_stable_points[np.where(bval_stable_points > min_mc)[0]]), 1)
    else:
        mc = this_maxc

    return mc, this_fmd[0], b, b_avg, shibolt_unc
    
cat_mbs = get_mbs(mag = catalog['mw'], mbin = 0.1)

plt.figure()
plt.plot(cat_mbs[1], cat_mbs[2], '.', color='k', label="b-value at cut-off magnitude")
plt.errorbar(cat_mbs[1], cat_mbs[2], yerr=cat_mbs[4], fmt='.', color='k')
plt.plot(cat_mbs[1], cat_mbs[3], '.', color="c", label="avg b between cut-off mag and cut-off mag + dM")
plt.vlines(cat_mbs[0], ymin=0, ymax=3, linestyles='dashed', label="MBS Mc = " + str(round(cat_mbs[0], 1)))
plt.legend(loc='upper left')
plt.ylim(0, 5)
plt.xlabel('Cut-off magnitude')
plt.ylabel('b-value estimate')
plt.title('MBS plot')
output_file = os.path.join(directory,'MBS_plot.png')
os.makedirs(directory, exist_ok=True)
watermark()
plt.savefig(output_file)
plt.show()
print(f"b-value stability plot saved to {shown(output_file)}")

cat_mc = cat_mbs[0]
cat_a, cat_b, cat_aki_unc, cat_shibolt_unc = b_est(mag = catalog['mw'], mbin = 0.1, mc = cat_mc)
mbs_result = method_result(cat_mc, cat_b, cat_shibolt_unc)

plt.figure()
plt.plot(cat_mi, cat_cumnbmag, marker='o', markersize=8, markerfacecolor='red', linestyle='None', color='black')
plt.plot(cat_mi, cat_nbmag, marker='s', markersize=8, markerfacecolor='white', linestyle='None', color='black')
plt.plot(cat_mi, (10**(cat_a - (cat_b * cat_mi))), linewidth=3, color='black')

plt.vlines(cat_mc, ymin=1, ymax=10**math.ceil(math.log10(catalog.shape[0])), linestyles='dashed')

plt.yscale('log')
plt.ylim(1, 10**math.ceil(math.log10(catalog.shape[0])))
plt.xlabel('Magnitude')
plt.ylabel('Frequency')
plt.title('MBS')
plt.text(x=cat_mc+0.07, y=2, s="Mc = " + str(round(cat_mc, 1)))
plt.text(x=cat_mc+0.07, y=1.2, s="b-value = " + str(round(cat_b, 2)) + " +/- " + str(round(cat_shibolt_unc, 2)))
output_file = os.path.join(directory,'MBS.png')
os.makedirs(directory, exist_ok=True)
watermark()
plt.savefig(output_file)
plt.show()
print(f"MBS plot saved to {shown(output_file)}")

summary_text = f"""
Summary of Mc analysis and b-values

MAXC Method:
- Mc: {maxc_result['mc']}
- b-value: {maxc_result['b_value']} +/- {maxc_result['b_value_uncertainty']}

GFT Method:
- Mc: {gft_result['mc']}
- b-value: {gft_result['b_value']} +/- {gft_result['b_value_uncertainty']}

MBS Method:
- Mc: {mbs_result['mc']}
- b-value: {mbs_result['b_value']} +/- {mbs_result['b_value_uncertainty']}
"""

summary_file_path = os.path.join(input_folder, "Mc_summary.txt")
with open(summary_file_path, 'w') as summary_file:
    summary_file.write(summary_text)

print(f"Summary of Mc analysis saved to {shown(summary_file_path)}")

figure_names = {"fmd": "FMD_plot.png", "maxc": "MAXC.png", "gft_residuals": "GFT_plot.png",
                "gft": "GFT.png", "mbs_stability": "MBS_plot.png", "mbs": "MBS.png"}
proj.update("Mc_analysis.py", {"magnitude_of_completeness": {
    "maxc": maxc_result,
    "gft": gft_result,
    "mbs": mbs_result,
    "summary_file": proj.rel(summary_file_path),
    "figures": {key: proj.rel(os.path.join(directory, name)) for key, name in figure_names.items()},
}}, catalogue=proj.rel(input_file_path))