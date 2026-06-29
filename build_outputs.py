#!/usr/bin/env python
"""
build_outputs.py
----------------
Standalone pipeline: generates pre-built population outputs for all 37 States/UTs.
No Jupyter required. Run once after cloning.

Outputs written to output/
  Custom_AgeBands_All_States.xlsx  -- all 37 states + India, 1991-2100
                                      columns: State, Year, 18-29, 30-65, 66+, Total, Source
  Custom_AgeBands_India.xlsx       -- India total only, same columns
  Lambda_18_29.csv                 -- India 18-29 lambda (Direct + Shifted_N10, in thousands)

Usage
-----
  pip install -r requirements.txt
  python build_outputs.py
"""

import os
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy.optimize import minimize

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
WPP_CSV   = os.path.join(REPO_ROOT, "data", "wpp",    "India_Population_TimeSeries_Female.csv")
CENSUS_XL = os.path.join(REPO_ROOT, "data", "census", "Census_Master_AgeSex_1991_2001_2011.xlsx")
NCDIR_XL  = os.path.join(REPO_ROOT, "data", "ncdir",  "State_Female_Projections_2012_2036.xlsx")
OUT_DIR   = os.path.join(REPO_ROOT, "output")
os.makedirs(OUT_DIR, exist_ok=True)

# ── Constants ─────────────────────────────────────────────────────────────────
BANDS = ['00-04','05-09','10-14','15-19','20-24','25-29',
         '30-34','35-39','40-44','45-49','50-54','55-59',
         '60-64','65-69','70-74','75+']

BAND_RANGES = {
    "00-04":(0,4),   "05-09":(5,9),   "10-14":(10,14), "15-19":(15,19),
    "20-24":(20,24), "25-29":(25,29), "30-34":(30,34), "35-39":(35,39),
    "40-44":(40,44), "45-49":(45,49), "50-54":(50,54), "55-59":(55,59),
    "60-64":(60,64), "65-69":(65,69), "70-74":(70,74), "75+":(75,120),
}

# 3 model compartment bands
USER_BANDS = [
    ("18-29", 18,  29),   # S18: HPV-susceptible young adults
    ("30-65", 30,  65),   # S30: working-age adults (splits 65-69 at age 65)
    ("66+",   66, None),  # S61: older adults (splits 65-69 at age 66)
]

CENSUS_YEARS  = [1991, 2001, 2011]
NCDIR_YEARS   = list(range(2012, 2037))
PROJ_YEARS    = list(range(2037, 2101))
T_BLEND       = 10
N_SHIFT       = 10
LAMBDA_YEARS  = list(range(2002, 2071))

# 12 states with V-shape artefact: replaced by NCDIR 2012-2017 CAGR back-projection
PROBLEM_STATES = [
    "Andaman & Nicobar", "Andhra Pradesh", "Goa", "Himachal Pradesh",
    "Karnataka", "Kerala", "Lakshadweep", "Nagaland",
    "Puduchery", "Punjab", "Tamil Nadu", "Telangana",
]

# ── 1. Load data ───────────────────────────────────────────────────────────────
print("Loading data ...")

wpp_raw = pd.read_csv(WPP_CSV).rename(columns={"Time": "Year"})
wpp_raw = wpp_raw[wpp_raw["Year"].between(1991, 2100)].set_index("Year")

BAND_AGES = {
    "00-04":range(0,5),   "05-09":range(5,10),  "10-14":range(10,15),
    "15-19":range(15,20), "20-24":range(20,25),  "25-29":range(25,30),
    "30-34":range(30,35), "35-39":range(35,40),  "40-44":range(40,45),
    "45-49":range(45,50), "50-54":range(50,55),  "55-59":range(55,60),
    "60-64":range(60,65), "65-69":range(65,70),  "70-74":range(70,75),
    "75+":  range(75,101),
}
wpp_bands = pd.DataFrame(index=wpp_raw.index)
for band, ages in BAND_AGES.items():
    cols = [f"Age{a}" if a < 100 else "Age100+" for a in ages]
    cols = [c for c in cols if c in wpp_raw.columns]
    wpp_bands[band] = wpp_raw[cols].sum(axis=1) / 1e3
wpp_sf = wpp_bands.div(wpp_bands.loc[2036])

ncdir_raw = pd.read_excel(NCDIR_XL, sheet_name="Female")
ncdir_raw.rename(columns={"Population": "State"}, inplace=True)
ncdir_raw["Year"] = ncdir_raw["Year"].astype(int)
STATES = sorted(ncdir_raw["State"].unique().tolist())
ncdir_india = ncdir_raw.groupby("Year")[BANDS].sum() / 1e6

cen_raw = pd.read_excel(CENSUS_XL, sheet_name="Master_Long")
cen_raw["State"] = cen_raw["State"].replace({
    "Andaman And Nicobar Islands": "Andaman & Nicobar",
    "Dadra And Nagar Haveli":      "Dadra & Nagar Haveli",
    "Daman And Diu":               "Daman & Diu",
    "NCT OF DELHI":                "Delhi",
})

print(f"  WPP: {wpp_raw.index.min()}-{wpp_raw.index.max()} | "
      f"NCDIR: {len(STATES)} states | Census loaded")

# ── 2. Build census bands ──────────────────────────────────────────────────────
CEN_TO_NCDIR = {
    "0-4":"00-04","00-04":"00-04","5-9":"05-09","05-09":"05-09",
    "10-14":"10-14","15-19":"15-19","20-24":"20-24","25-29":"25-29",
    "30-34":"30-34","35-39":"35-39","40-44":"40-44","45-49":"45-49",
    "50-54":"50-54","55-59":"55-59","60-64":"60-64","65-69":"65-69",
    "70-74":"70-74","75-79":"75+","80+":"75+",
}

def build_state_census(df_state):
    out = {b: 0.0 for b in BANDS}
    for _, row in df_state.iterrows():
        nb = CEN_TO_NCDIR.get(str(row.get("AgeGroup", "")).strip())
        if nb:
            out[nb] += float(row.get("TotalFemales", 0) or 0)
    return out

census_bands = {}
for (state, year), grp in cen_raw.groupby(["State", "Year"]):
    if "India" in str(state):
        continue
    census_bands.setdefault(state, {})[year] = build_state_census(grp)

census_bands["India"] = {}
for yr, lbl in [(1991, "India (Excluding J&K)"), (2001, "India"), (2011, "India")]:
    grp = cen_raw[(cen_raw["State"] == lbl) & (cen_raw["Year"] == yr)]
    census_bands["India"][yr] = build_state_census(grp)

# ── 3. Bifurcated states ───────────────────────────────────────────────────────
ncdir_2012_raw = ncdir_raw[ncdir_raw["Year"] == 2012].set_index("State")

def split_ratio(child, parent):
    r = {}
    for b in BANDS:
        c = float(ncdir_2012_raw.loc[child,  b]) if child  in ncdir_2012_raw.index else 0.0
        p = float(ncdir_2012_raw.loc[parent, b]) if parent in ncdir_2012_raw.index else 0.0
        r[b] = c / (c + p) if (c + p) > 0 else 0.0
    return r

for child, parent in {"Jharkhand": "Bihar",
                      "Chattisgarh": "Madhya Pradesh",
                      "Uttarakhand": "Uttar Pradesh"}.items():
    r = split_ratio(child, parent)
    census_bands[child][1991] = {}
    for b in BANDS:
        p91 = census_bands[parent][1991][b]
        census_bands[child][1991][b]  = p91 * r[b]
        census_bands[parent][1991][b] = p91 * (1 - r[b])

r_tel = split_ratio("Telangana", "Andhra Pradesh")
census_bands["Telangana"] = {}
for yr in CENSUS_YEARS:
    census_bands["Telangana"][yr] = {}
    for b in BANDS:
        ap = census_bands["Andhra Pradesh"][yr][b]
        census_bands["Telangana"][yr][b]      = ap * r_tel[b]
        census_bands["Andhra Pradesh"][yr][b] = ap * (1 - r_tel[b])

r_lad = split_ratio("Ladakh", "Jammu & Kashmir")
census_bands["Ladakh"] = {}
for yr in [2001, 2011]:
    census_bands["Ladakh"][yr] = {}
    for b in BANDS:
        jk = census_bands["Jammu & Kashmir"][yr][b]
        census_bands["Ladakh"][yr][b]          = jk * r_lad[b]
        census_bands["Jammu & Kashmir"][yr][b] = jk * (1 - r_lad[b])
census_bands["Ladakh"][1991] = {}
census_bands["Jammu & Kashmir"][1991] = {}
for b in BANDS:
    l01 = census_bands["Ladakh"][2001][b];              l11 = census_bands["Ladakh"][2011][b]
    rl  = (l11 / l01) ** (1/10) if l01 > 0 else 1.0;  census_bands["Ladakh"][1991][b] = l01 / (rl ** 10)
    j01 = census_bands["Jammu & Kashmir"][2001][b];     j11 = census_bands["Jammu & Kashmir"][2011][b]
    rj  = (j11 / j01) ** (1/10) if j01 > 0 else 1.0;  census_bands["Jammu & Kashmir"][1991][b] = j01 / (rj ** 10)

# ── 4. Census annual interpolation ────────────────────────────────────────────
print("Building census annual series ...")

ncdir_2012_abs = ncdir_raw[ncdir_raw["Year"] == 2012].set_index("State")
ncdir_2012_india_abs = {b: float(ncdir_raw.groupby("Year")[BANDS].sum().loc[2012, b])
                        for b in BANDS}

def interp_two_anchors(b_start, b_end, y_start, y_end):
    out = {}
    span = y_end - y_start
    for yr in range(y_start, y_end):
        t = (yr - y_start) / span
        out[yr] = {b: b_start[b] + t * (b_end[b] - b_start[b]) for b in BANDS}
    return out

census_annual = {}
for state in census_bands:
    if state == "India":
        continue
    if 1991 not in census_bands[state] or 2001 not in census_bands[state]:
        continue
    if state not in ncdir_2012_abs.index:
        continue
    ne = {b: float(ncdir_2012_abs.loc[state, b]) for b in BANDS}
    s1 = interp_two_anchors(census_bands[state][1991], census_bands[state][2001], 1991, 2001)
    s2 = interp_two_anchors(census_bands[state][2001], ne, 2001, 2012)
    census_annual[state] = {**s1, **s2}

s1i = interp_two_anchors(census_bands["India"][1991], census_bands["India"][2001], 1991, 2001)
s2i = interp_two_anchors(census_bands["India"][2001], ncdir_2012_india_abs, 2001, 2012)
census_annual["India"] = {**s1i, **s2i}

# ── 5. Back-projection correction for 12 problematic states ───────────────────
ncdir_2017_abs = ncdir_raw[ncdir_raw["Year"] == 2017].set_index("State")

def backproject_ncdir_annual(state):
    out = {}
    for yr in range(1991, 2012):
        out[yr] = {}
        for b in BANDS:
            v12  = float(ncdir_2012_abs.loc[state, b])
            v17  = float(ncdir_2017_abs.loc[state, b])
            cagr = (v17 / v12) ** (1/5) - 1 if v12 > 0 else 0.0
            out[yr][b] = v12 / ((1 + cagr) ** (2012 - yr))
    return out

n_corr = 0
for state in PROBLEM_STATES:
    if state in census_annual:
        census_annual[state] = backproject_ncdir_annual(state)
        n_corr += 1
print(f"  Back-projection applied to {n_corr} problematic states.")

# ── 6. Gompertz TFR fit ───────────────────────────────────────────────────────
census_yrs = np.array([2013., 2018., 2023., 2028., 2033.])
census_tfr = np.array([2.34,  2.13,  1.94,  1.81,  1.73])
L_TFR, U_TFR = 1.667, 2.50

def gompertz_tfr(year, a, b):
    return L_TFR + (U_TFR - L_TFR) * (a ** (b ** (year - 2010)))

res = minimize(
    lambda p: 1e10 if not (0 < p[0] < 1 and 0 < p[1] < 1)
              else np.sum((gompertz_tfr(census_yrs, *p) - census_tfr) ** 2),
    [0.65, 0.85], method="Nelder-Mead", options={"xatol": 1e-9, "fatol": 1e-11}
)
A_OPT, B_OPT = res.x
TFR_2036 = gompertz_tfr(2036, A_OPT, B_OPT)
tfr_proj = lambda yr: gompertz_tfr(yr, A_OPT, B_OPT)
print(f"  Gompertz TFR: a={A_OPT:.5f}, b={B_OPT:.5f}")

# ── 7. WPP-scaled India projections 2037-2100 ─────────────────────────────────
print("Building WPP-scaled projections ...")

r_ncdir = {}
for band in BANDS:
    v36 = ncdir_india.loc[2036, band]; v31 = ncdir_india.loc[2031, band]
    r_ncdir[band] = (v36 / v31) ** (1/5) - 1 if v31 > 0 else 0.0

wpp_proj = {}
for band in BANDS:
    nc36 = ncdir_india.loc[2036, band]
    s = {yr: nc36 * (wpp_sf.loc[yr, band] if yr in wpp_sf.index else 1.0)
              * (tfr_proj(yr) / TFR_2036) ** 0.3
         for yr in PROJ_YEARS}
    wpp_proj[band] = pd.Series(s)

blended_proj = {}
for band in BANDS:
    series = dict(ncdir_india[band].to_dict())
    for yr in range(2037, 2047):
        alpha = (yr - 2036) / T_BLEND
        p_mom = series[yr - 1] * (1 + r_ncdir[band])
        series[yr] = (1 - alpha) * p_mom + alpha * wpp_proj[band].loc[yr]
    sc = series[2046] / wpp_proj[band].loc[2046] if wpp_proj[band].loc[2046] > 0 else 1.0
    for yr in range(2047, 2101):
        series[yr] = wpp_proj[band].loc[yr] * sc
    blended_proj[band] = pd.Series(series)

# ── 8. State-wise projections 2037-2100 ───────────────────────────────────────
ncdir_states = {s: ncdir_raw[ncdir_raw["State"] == s].set_index("Year")[BANDS] / 1e6
                for s in STATES}

b_scale = {band: {yr: blended_proj[band].loc[yr] / blended_proj[band].loc[2036]
                  for yr in PROJ_YEARS}
           for band in BANDS}

r_state = {}
for state in STATES:
    r_state[state] = {}
    for band in BANDS:
        v36 = ncdir_states[state].loc[2036, band]; v31 = ncdir_states[state].loc[2031, band]
        r_state[state][band] = (v36 / v31) ** (1/5) - 1 if v31 > 0 else 0.0

state_proj = {}
for state in STATES:
    ser = {yr: dict(ncdir_states[state].loc[yr]) for yr in NCDIR_YEARS}
    for yr in range(2037, 2047):
        alpha = (yr - 2036) / T_BLEND
        ser[yr] = {}
        for band in BANDS:
            p_mom = ser[yr-1][band] * (1 + r_state[state][band])
            p_b   = ncdir_states[state].loc[2036, band] * b_scale[band][yr]
            ser[yr][band] = (1 - alpha) * p_mom + alpha * p_b
    cont_sc = {}
    for band in BANDS:
        vb = ser[2046][band]; vp = ncdir_states[state].loc[2036, band] * b_scale[band][2046]
        cont_sc[band] = vb / vp if vp > 0 else 1.0
    for yr in range(2047, 2101):
        ser[yr] = {band: ncdir_states[state].loc[2036, band] * b_scale[band][yr] * cont_sc[band]
                   for band in BANDS}
    state_proj[state] = ser

# ── 9. Assemble full series per state ─────────────────────────────────────────
print("Assembling full series ...")

final_pop = {}
for state in STATES + ["India"]:
    series = {}
    for yr in range(1991, 2012):
        if yr in census_annual.get(state, {}):
            series[yr] = {b: census_annual[state][yr][b] for b in BANDS}
    if state == "India":
        for yr in NCDIR_YEARS:
            series[yr] = {b: ncdir_india.loc[yr, b] * 1e6 for b in BANDS}
        for yr in PROJ_YEARS:
            series[yr] = {b: blended_proj[b].loc[yr] * 1e6 for b in BANDS}
    else:
        for yr in NCDIR_YEARS:
            if yr in ncdir_states.get(state, pd.DataFrame()).index:
                series[yr] = {b: ncdir_states[state].loc[yr, b] * 1e6 for b in BANDS}
        for yr in PROJ_YEARS:
            series[yr] = {b: state_proj[state][yr][b] * 1e6 for b in BANDS}
    final_pop[state] = series

def to_df(state):
    rows = []
    for yr in sorted(final_pop[state].keys()):
        row = {"State": state, "Year": yr}
        row.update(final_pop[state][yr])
        row["Total"] = sum(final_pop[state][yr][b] for b in BANDS)
        row["Source"] = (
            "NCDIR-Backprojected" if yr <= 2011 and state in PROBLEM_STATES else
            "Census-Interpolated" if yr <= 2011 else
            "NCDIR-Actual"        if yr <= 2036 else
            "WPP-Projection"
        )
        rows.append(row)
    return pd.DataFrame(rows)

# ── 10. WPP within-band fraction helper ───────────────────────────────────────
def wpp_band_fraction(band, req_start, req_end, year):
    band_start, band_end = BAND_RANGES[band]
    ov_start = max(req_start, band_start)
    ov_end   = min(req_end, band_end)
    if ov_start > ov_end:
        return 0.0
    if ov_start == band_start and ov_end == band_end:
        return 1.0
    yr = min(max(int(year), 1991), 2100)
    def wpp_age(a):
        col = "Age100+" if a >= 100 else f"Age{a}"
        return float(wpp_raw.loc[yr, col]) if col in wpp_raw.columns else 0.0
    num = sum(wpp_age(a) for a in range(ov_start, ov_end + 1))
    den = sum(wpp_age(a) for a in range(band_start, band_end + 1))
    return num / den if den > 0 else 0.0

def compute_custom_bands(df_state):
    rows = []
    for _, row in df_state.iterrows():
        yr = int(row["Year"])
        out = {"State": row["State"], "Year": yr, "Source": row["Source"]}
        for label, start, end in USER_BANDS:
            end_eff = end if end is not None else 120
            out[label] = sum(row[band] * wpp_band_fraction(band, start, end_eff, yr)
                             for band in BANDS)
        rows.append(out)
    return pd.DataFrame(rows)

# ── 11. Export ─────────────────────────────────────────────────────────────────
print("Computing custom bands and exporting ...")

df_india        = to_df("India")
df_india_custom = compute_custom_bands(df_india)
df_india_custom.to_excel(os.path.join(OUT_DIR, "Custom_AgeBands_India.xlsx"), index=False)
print(f"  Saved: Custom_AgeBands_India.xlsx  ({len(df_india_custom)} rows)")

all_dfs = [df_india_custom]
for state in STATES:
    df_s = to_df(state)
    all_dfs.append(compute_custom_bands(df_s))

df_all = pd.concat(all_dfs, ignore_index=True)
df_all.to_excel(os.path.join(OUT_DIR, "Custom_AgeBands_All_States.xlsx"), index=False)
print(f"  Saved: Custom_AgeBands_All_States.xlsx  "
      f"({len(df_all):,} rows, {df_all['State'].nunique()} entities)")

# Lambda 18-29 — India, in thousands
lambda_lookup  = dict(zip(df_india_custom["Year"].astype(int),
                          df_india_custom["18-29"] / 1e3))
lambda_direct  = np.array([lambda_lookup.get(t,          np.nan) for t in LAMBDA_YEARS])
lambda_shifted = np.array([lambda_lookup.get(t + N_SHIFT, np.nan) for t in LAMBDA_YEARS])
df_lambda = pd.DataFrame({
    "Year":                      LAMBDA_YEARS,
    "Lambda_Direct":             lambda_direct,
    f"Lambda_Shifted_N{N_SHIFT}": lambda_shifted,
})
df_lambda.to_csv(os.path.join(OUT_DIR, "Lambda_18_29.csv"), index=False)
print(f"  Saved: Lambda_18_29.csv  ({len(df_lambda)} rows, N_SHIFT={N_SHIFT})")

# ── 12. Sanity-check ──────────────────────────────────────────────────────────
print("\nSample at 2012 (absolute persons):")
print(f"  {'State':<26} {'18-29':>12}  {'30-65':>12}  {'66+':>10}  Source")
for state in ["Andaman & Nicobar", "Kerala", "Uttar Pradesh"]:
    row = df_all[(df_all["State"] == state) & (df_all["Year"] == 2012)].iloc[0]
    print(f"  {state:<26} {int(row['18-29']):>12,}  {int(row['30-65']):>12,}  "
          f"{int(row['66+']):>10,}  {row['Source']}")

print("\nAll outputs ready in:", OUT_DIR)
