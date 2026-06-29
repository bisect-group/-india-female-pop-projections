"""
diagnose_jump.py
----------------
Verifies that the Census 2011 → NCDIR 2012 boundary is smooth under the
two-sub-segment interpolation methodology (Census 2001 → NCDIR 2012).

Methodology note:
  The pipeline uses two sub-segments for the census period:
    1A: Census 1991 → Census 2001  (both hard census anchors)
    1B: Census 2001 → NCDIR 2012   (Census 2011 NOT used as anchor)
  This ensures the 2011→2012 step is a uniform continuation of the
  interpolation line — no source-change discontinuity.

Outputs:
  output/diagnostics/boundary_check.csv   — per state×band: steps at 2010→11, 2011→12, 2012→13
  output/diagnostics/boundary_heatmap.png — heatmap of 2011→2012 residual vs neighbors
  output/diagnostics/state_plots/<state>.png — time-series zoom around boundary
"""

import os
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.colors import TwoSlopeNorm

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT  = os.path.dirname(os.path.abspath(__file__))
CENSUS_XL  = os.path.join(REPO_ROOT, "data", "census", "Census_Master_AgeSex_1991_2001_2011.xlsx")
NCDIR_XL   = os.path.join(REPO_ROOT, "data", "ncdir",  "State_Female_Projections_2012_2036.xlsx")
DIAG_DIR   = os.path.join(REPO_ROOT, "output", "diagnostics")
PLOT_DIR   = os.path.join(DIAG_DIR, "state_plots")
os.makedirs(PLOT_DIR, exist_ok=True)

BANDS = ['00-04','05-09','10-14','15-19','20-24','25-29',
         '30-34','35-39','40-44','45-49','50-54','55-59',
         '60-64','65-69','70-74','75+']
CENSUS_YEARS = [1991, 2001, 2011]

# ── 1. Load NCDIR ─────────────────────────────────────────────────────────────
print("Loading NCDIR...")
ncdir_raw = pd.read_excel(NCDIR_XL, sheet_name="Female", header=0)
ncdir_raw.rename(columns={"Population": "State"}, inplace=True)
ncdir_raw["Year"] = ncdir_raw["Year"].astype(int)
STATES = sorted(ncdir_raw["State"].unique().tolist())
ncdir_2012_abs = ncdir_raw[ncdir_raw["Year"] == 2012].set_index("State")
ncdir_by_state = {s: ncdir_raw[ncdir_raw["State"] == s].set_index("Year") for s in STATES}
print(f"  {len(STATES)} states, years {ncdir_raw['Year'].min()}–{ncdir_raw['Year'].max()}")

# ── 2. Load Census ────────────────────────────────────────────────────────────
print("Loading Census...")
cen_raw = pd.read_excel(CENSUS_XL, sheet_name="Master_Long")
NAME_FIX = {
    "Andaman And Nicobar Islands": "Andaman & Nicobar",
    "Dadra And Nagar Haveli":      "Dadra & Nagar Haveli",
    "Daman And Diu":               "Daman & Diu",
    "NCT OF DELHI":                "Delhi",
}
cen_raw["State"] = cen_raw["State"].replace(NAME_FIX)

CEN_TO_NCDIR = {
    "0-4":"00-04",   "00-04":"00-04",
    "5-9":"05-09",   "05-09":"05-09",
    "10-14":"10-14", "15-19":"15-19",
    "20-24":"20-24", "25-29":"25-29", "30-34":"30-34", "35-39":"35-39",
    "40-44":"40-44", "45-49":"45-49", "50-54":"50-54", "55-59":"55-59",
    "60-64":"60-64", "65-69":"65-69", "70-74":"70-74",
    "75-79":"75+",   "80+":"75+",
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

# ── 3. Bifurcated states ──────────────────────────────────────────────────────
print("Handling bifurcated states...")

def split_ratio(child, parent):
    ratios = {}
    for b in BANDS:
        c_val = float(ncdir_2012_abs.loc[child,  b]) if child  in ncdir_2012_abs.index else 0.0
        p_val = float(ncdir_2012_abs.loc[parent, b]) if parent in ncdir_2012_abs.index else 0.0
        tot = c_val + p_val
        ratios[b] = c_val / tot if tot > 0 else 0.0
    return ratios

NEW_STATES_2000 = {"Jharkhand": "Bihar", "Chattisgarh": "Madhya Pradesh", "Uttarakhand": "Uttar Pradesh"}
for child, parent in NEW_STATES_2000.items():
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
        ap_val = census_bands["Andhra Pradesh"][yr][b]
        census_bands["Telangana"][yr][b]      = ap_val * r_tel[b]
        census_bands["Andhra Pradesh"][yr][b] = ap_val * (1 - r_tel[b])

r_lad = split_ratio("Ladakh", "Jammu & Kashmir")
census_bands["Ladakh"] = {}
for yr in [2001, 2011]:
    census_bands["Ladakh"][yr] = {}
    for b in BANDS:
        jk_val = census_bands["Jammu & Kashmir"][yr][b]
        census_bands["Ladakh"][yr][b]          = jk_val * r_lad[b]
        census_bands["Jammu & Kashmir"][yr][b] = jk_val * (1 - r_lad[b])

census_bands["Ladakh"][1991] = {}
census_bands["Jammu & Kashmir"][1991] = {}
for b in BANDS:
    lad_01  = census_bands["Ladakh"][2001][b]
    lad_11  = census_bands["Ladakh"][2011][b]
    rate    = (lad_11 / lad_01) ** (1/10) if lad_01 > 0 else 1.0
    census_bands["Ladakh"][1991][b] = lad_01 / (rate ** 10)
    jk_01   = census_bands["Jammu & Kashmir"][2001][b]
    jk_11   = census_bands["Jammu & Kashmir"][2011][b]
    rate_jk = (jk_11 / jk_01) ** (1/10) if jk_01 > 0 else 1.0
    census_bands["Jammu & Kashmir"][1991][b] = jk_01 / (rate_jk ** 10)

# ── 4. Build census annual series (new two-sub-segment methodology) ────────────
print("Building census annual series (two-sub-segment methodology)...")

def interp_two_anchors(b_start, b_end, y_start, y_end):
    """Interpolate b_start@y_start → b_end@y_end; returns years [y_start, y_end)."""
    out = {}
    span = y_end - y_start
    for yr in range(y_start, y_end):
        t = (yr - y_start) / span
        out[yr] = {b: b_start[b] + t * (b_end[b] - b_start[b]) for b in BANDS}
    return out

census_annual = {}
for state in STATES:
    if state not in census_bands:
        continue
    if 1991 not in census_bands[state] or 2001 not in census_bands[state]:
        continue
    if state not in ncdir_2012_abs.index:
        continue
    ncdir_end = {b: float(ncdir_2012_abs.loc[state, b]) for b in BANDS}
    seg1 = interp_two_anchors(census_bands[state][1991], census_bands[state][2001], 1991, 2001)
    seg2 = interp_two_anchors(census_bands[state][2001], ncdir_end, 2001, 2012)
    census_annual[state] = {**seg1, **seg2}

# ── 5. Compute steps at 2010→11, 2011→12, 2012→13 for each state × band ──────
print("\nComputing boundary steps...")

rows = []
for state in STATES:
    if state not in census_annual:
        continue
    for band in BANDS:
        v2010 = census_annual[state].get(2010, {}).get(band, np.nan)
        v2011 = census_annual[state].get(2011, {}).get(band, np.nan)
        v2012 = float(ncdir_by_state[state].loc[2012, band]) if 2012 in ncdir_by_state[state].index else np.nan
        v2013 = float(ncdir_by_state[state].loc[2013, band]) if 2013 in ncdir_by_state[state].index else np.nan

        step_before   = (v2011 - v2010) / v2010 * 100 if v2010 and v2010 > 0 else np.nan
        step_boundary = (v2012 - v2011) / v2011 * 100 if v2011 and v2011 > 0 else np.nan
        step_after    = (v2013 - v2012) / v2012 * 100 if v2012 and v2012 > 0 else np.nan
        residual      = step_boundary - step_before if not np.isnan(step_boundary) and not np.isnan(step_before) else np.nan

        rows.append({
            "State": state, "Band": band,
            "Step_2010_2011_%":  round(step_before,   2),
            "Step_2011_2012_%":  round(step_boundary, 2),
            "Step_2012_2013_%":  round(step_after,    2),
            "Residual_%":        round(residual,       2),
        })

df = pd.DataFrame(rows)
df.to_csv(os.path.join(DIAG_DIR, "boundary_check.csv"), index=False)
print(f"Saved: {os.path.join(DIAG_DIR, 'boundary_check.csv')}")

print("\nBoundary step summary (avg across all states):")
print(f"{'Band':<8} {'2010→2011':>12} {'2011→2012':>12} {'2012→2013':>12} {'Residual':>10}  Status")
print("-"*70)
all_ok = True
for band in BANDS:
    sub = df[df["Band"] == band]
    m_b  = sub["Step_2010_2011_%"].mean()
    m_bnd = sub["Step_2011_2012_%"].mean()
    m_a  = sub["Step_2012_2013_%"].mean()
    res  = sub["Residual_%"].abs().mean()
    ok = "OK ✓" if res < 2.0 else "SPIKE ✗"
    if res >= 2.0: all_ok = False
    print(f"{band:<8} {m_b:>+11.2f}% {m_bnd:>+11.2f}% {m_a:>+11.2f}% {res:>9.2f}%  {ok}")

print(f"\nOverall: {'All bands pass ✓' if all_ok else 'Some bands have residual spikes ✗'}")
print(f"Max residual across all state×band: {df['Residual_%'].abs().max():.2f}%")

# ── 6. Heatmap of residual (2011→12 minus 2010→11) ───────────────────────────
pivot = df.pivot(index="State", columns="Band", values="Residual_%")[BANDS]

fig, ax = plt.subplots(figsize=(16, 12))
vmax = max(abs(pivot.values[~np.isnan(pivot.values)]).max(), 0.1)
norm = TwoSlopeNorm(vcenter=0, vmin=-vmax, vmax=vmax)
im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn_r", norm=norm)
ax.set_xticks(range(len(BANDS)))
ax.set_xticklabels(BANDS, rotation=45, ha="right", fontsize=8)
ax.set_yticks(range(len(pivot.index)))
ax.set_yticklabels(pivot.index, fontsize=7)
ax.set_title("Residual at 2011→2012 boundary\n(Step_2011→12 minus Step_2010→11)\nSmall values confirm no discontinuity",
             fontsize=11, fontweight="bold")
plt.colorbar(im, ax=ax, label="Residual %", fraction=0.03, pad=0.02)
plt.tight_layout()
plt.savefig(os.path.join(DIAG_DIR, "boundary_heatmap.png"), dpi=150, bbox_inches="tight")
plt.close()
print(f"\nSaved: {os.path.join(DIAG_DIR, 'boundary_heatmap.png')}")

# ── 7. Per-state time-series plots ────────────────────────────────────────────
print("Generating per-state plots...")
WINDOW = list(range(2006, 2021))

for state in STATES:
    if state not in census_annual:
        continue
    fig, axes = plt.subplots(4, 4, figsize=(18, 14))
    fig.suptitle(f"{state} — Boundary verification: Census (1991-2011) vs NCDIR (2012-2036)\n"
                 f"2001-2011 segment anchored to NCDIR 2012 — zoom: 2006-2020",
                 fontsize=11, fontweight="bold", y=1.01)

    for i, band in enumerate(BANDS):
        ax = axes.flatten()[i]
        cen_yrs  = [y for y in WINDOW if y <= 2011]
        cen_vals = [census_annual[state][y][band] / 1e6 for y in cen_yrs]
        ncd_yrs  = [y for y in WINDOW if y >= 2012 and y in ncdir_by_state[state].index]
        ncd_vals = [float(ncdir_by_state[state].loc[y, band]) / 1e6 for y in ncd_yrs]

        ax.plot(cen_yrs, cen_vals, "o-",  color="#2166ac", lw=1.5, ms=3, label="Census segment")
        ax.plot(ncd_yrs, ncd_vals, "s--", color="#d73027", lw=1.5, ms=3, label="NCDIR")
        ax.axvline(2011.5, color="gray", lw=0.8, ls=":")

        row_mask = (df["State"] == state) & (df["Band"] == band)
        res = df.loc[row_mask, "Residual_%"].values
        if len(res) and not np.isnan(res[0]):
            color = "red" if abs(res[0]) > 2.0 else "black"
            ax.set_title(f"{band}  residual={res[0]:+.1f}%", fontsize=8, fontweight="bold", color=color)
        else:
            ax.set_title(band, fontsize=8)

        ax.xaxis.set_major_locator(mticker.MultipleLocator(4))
        ax.tick_params(labelsize=7)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.2f}M"))
        ax.spines[["top","right"]].set_visible(False)
        if i == 0:
            ax.legend(fontsize=7, loc="upper left")

    plt.tight_layout()
    safe = state.replace(" ", "_").replace("&", "and").replace("/", "-")
    plt.savefig(os.path.join(PLOT_DIR, f"{safe}.png"), dpi=120, bbox_inches="tight")
    plt.close()

print(f"Saved per-state plots to: {PLOT_DIR}")
print("\nDone. All outputs in:", DIAG_DIR)
