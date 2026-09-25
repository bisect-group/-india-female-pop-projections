"""popproj - loaders, constants and plot helpers for the India population projection notebook.

Builds female population by state/UT x 16 five-year age bands x year (1950-2100) from:
  * ICMR-NCDIR state population projections, 2012-2036
  * UN World Population Prospects (WPP) 2024, India, single ages, 1950-2100
  * Census of India 1991, 2001, 2011 (age-sex tables)
  * SRS Statistical Report 2022 (optional, used only for validation)

Set the file locations with ``configure(...)`` (or the POPPROJ_* environment variables)
before loading data. All populations are absolute persons.
"""
import os

import numpy as np
import pandas as pd
import matplotlib.ticker as mticker

try:                                     # full house style if installed, otherwise a built-in fallback
    import sciplotstyle as sp
except ImportError:
    import plotstyle as sp

# ---- File locations (override with configure() or environment variables) -------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
RAW = os.path.join(REPO_ROOT, "data", "raw")
PATHS = {
    "icmr_ncdir": os.environ.get("POPPROJ_ICMR_NCDIR", os.path.join(
        RAW, "icmr_ncdir", "ICMR_NCDIR_State_Female_Projections_2012_2036.xlsx")),
    "wpp":        os.environ.get("POPPROJ_WPP", os.path.join(
        RAW, "wpp", "WPP2024_India_Female_Population_SingleAge_1950_2100.csv")),
    "census":     os.environ.get("POPPROJ_CENSUS", os.path.join(
        RAW, "census", "Census_Master_AgeSex_1991_2001_2011.xlsx")),
    "srs2022":    os.environ.get("POPPROJ_SRS2022", os.path.join(
        RAW, "srs", "SRS_Statistical_Report_2022_extracted.xlsx")),
}
FIG_DIR = os.environ.get("POPPROJ_FIG_DIR", os.path.join(REPO_ROOT, "figures"))
OUT_DIR = os.environ.get("POPPROJ_OUT_DIR", os.path.join(REPO_ROOT, "outputs"))


def configure(fig_dir=None, out_dir=None, **paths):
    """Set input file paths (keys: icmr_ncdir, wpp, census, srs2022) and output folders."""
    global FIG_DIR, OUT_DIR
    unknown = set(paths) - set(PATHS)
    if unknown:
        raise KeyError(f"Unknown path keys: {sorted(unknown)}; expected {sorted(PATHS)}")
    PATHS.update(paths)
    if fig_dir:
        FIG_DIR = fig_dir
    if out_dir:
        OUT_DIR = out_dir


def check_paths():
    for k, p in PATHS.items():
        print(f"  [{'OK' if os.path.exists(p) else 'MISSING'}] {k:<11s} {p}")


# ---- Age bands and years ----------------------------------------------------------
BANDS = ["00-04", "05-09", "10-14", "15-19", "20-24", "25-29", "30-34", "35-39",
         "40-44", "45-49", "50-54", "55-59", "60-64", "65-69", "70-74", "75+"]
_BAND_AGES = {b: (list(range(int(b[:2]), int(b[:2]) + 5)) if b != "75+" else list(range(75, 101)))
              for b in BANDS}
_CENSUS_TO_BAND = {"0-4": "00-04", "5-9": "05-09", "75-79": "75+", "80+": "75+"}

YEARS = np.arange(1950, 2101)
ICMR_START, ICMR_END = 2012, 2036          # years covered by the ICMR-NCDIR projections


# ---- Loaders ----------------------------------------------------------------------
def load_icmr_ncdir():
    """ICMR-NCDIR female population projections: 37 state/UT series x 2012-2036 x 16 bands.

    Returns a DataFrame indexed by (state, year) with the 16 band columns (persons).
    India is not included; build it as the sum of the states.
    """
    d = pd.read_excel(PATHS["icmr_ncdir"], sheet_name="Female").rename(columns={"Population": "state",
                                                                                "Year": "year"})
    d["year"] = d["year"].astype(int)
    return d.set_index(["state", "year"])[BANDS].sort_index().astype(float)


def load_wpp_bands():
    """WPP 2024 India female population aggregated to the 16 bands, 1950-2100 (persons)."""
    w = pd.read_csv(PATHS["wpp"]).set_index("Time")
    out = pd.DataFrame(index=w.index)
    for b, ages in _BAND_AGES.items():
        cols = [f"Age{a}" if a < 100 else "Age100+" for a in ages]
        out[b] = w[cols].sum(axis=1) * 1e3          # WPP file is in thousands
    out.index.name = "year"
    return out.loc[1950:2100]


_CENSUS_STATE_NAMES = {"NCT OF DELHI": "Delhi", "Odisha": "Orissa", "Chhattisgarh": "Chattisgarh",
                       "Puducherry": "Puduchery",
                       "Andaman And Nicobar Islands": "Andaman & Nicobar",
                       "Dadra And Nagar Haveli": "Dadra & Nagar Haveli",
                       "Daman And Diu": "Daman & Diu"}
# Units that did not exist at Census 2011 take their parent's age distribution
# (today's boundaries are assumed to hold in the past).
_CENSUS_PARENT = {"Telangana": "Andhra Pradesh", "Ladakh": "Jammu & Kashmir"}


def _census_long():
    c = pd.read_excel(PATHS["census"], sheet_name="Master_Long")
    c["band"] = c["AgeGroup"].astype(str).str.strip().map(lambda a: _CENSUS_TO_BAND.get(a, a))
    c["state"] = c["State"].astype(str).str.strip().replace(_CENSUS_STATE_NAMES)
    return c


def _census_bands(c, state, year, redistribute_not_stated=True):
    g = c[(c.state == state) & (c.Year == year)]
    s = g[g.band.isin(BANDS)].groupby("band")["TotalFemales"].sum().reindex(BANDS).astype(float)
    if redistribute_not_stated:
        ns = g[g.band == "Age not stated"]["TotalFemales"].sum()
        s = s * (1 + ns / s.sum())
    return s


def load_census_india(redistribute_not_stated=True, adjust_1991_jk=False):
    """India female Census counts 1991, 2001, 2011 by band (persons).

    Census 1991 excludes J&K; with adjust_1991_jk=True each 1991 band is scaled by
    India_2001 / (India_2001 - J&K_2001). Age-not-stated is redistributed pro rata.
    """
    c = _census_long()
    rows = {1991: _census_bands(c, "India (Excluding J&K)", 1991, redistribute_not_stated),
            2001: _census_bands(c, "India", 2001, redistribute_not_stated),
            2011: _census_bands(c, "India", 2011, redistribute_not_stated)}
    if adjust_1991_jk:
        jk01 = _census_bands(c, "Jammu & Kashmir", 2001, redistribute_not_stated)
        rows[1991] = rows[1991] * rows[2001] / (rows[2001] - jk01)
    out = pd.DataFrame(rows).T
    out.index.name = "year"
    return out


def load_census_state_shares(states, year=2011, redistribute_not_stated=True):
    """Census female age shares (rows sum to 1) for the given state names."""
    c = _census_long()
    rows = {}
    for s in states:
        src = _CENSUS_PARENT.get(s, s)
        v = _census_bands(c, src, year, redistribute_not_stated)
        if v.isna().all() or v.sum() == 0:
            raise KeyError(f"No Census {year} row for {s} (looked up as {src})")
        rows[s] = v / v.sum()
    return pd.DataFrame(rows).T


_SRS_NAMES = {"Odisha": "Orissa", "Chhattisgarh": "Chattisgarh"}


def load_srs2022_female_shares():
    """SRS Statistical Report 2022, Table 1: female % age distribution (all areas),
    India + 22 bigger states, 16 bands (75-79, 80-84, 85+ -> 75+), rows sum to 1.

    Fixes a known issue in the extracted table: Telangana's 18 rows follow Tamil Nadu's
    without a state label (that block has 36 rows); the second 18 are relabelled.
    """
    a = pd.read_excel(PATHS["srs2022"], sheet_name="Age_Sex_Dist_2022", header=None).iloc[3:]
    a.columns = ["state", "age", "T_T", "T_M", "T_F", "R_T", "R_M", "R_F", "U_T", "U_M", "U_F"]
    a["state"] = a["state"].ffill()
    a = a[a["age"].astype(str) != "Total"].copy()
    tn = a.index[a["state"] == "Tamil Nadu"]
    if len(tn) == 36:
        a.loc[tn[18:], "state"] = "Telangana"
    a["band"] = a["age"].astype(str).replace({"0-4": "00-04", "5-9": "05-09",
                                               "75-79": "75+", "80-84": "75+", "85+": "75+"})
    a["T_F"] = pd.to_numeric(a["T_F"], errors="coerce")
    out = a.groupby(["state", "band"])["T_F"].sum().unstack()[BANDS]
    out.index = [_SRS_NAMES.get(s, s) for s in out.index]
    return out.div(out.sum(axis=1), axis=0)


# ---- Plot helpers -----------------------------------------------------------------
def setup_style(scale=0.75):
    sp.use(scale=scale)
    os.makedirs(FIG_DIR, exist_ok=True)


def persons_formatter(max_value):
    """Millions for large series, thousands for small ones."""
    if max_value >= 5e6:
        return mticker.FuncFormatter(lambda v, _: f"{v / 1e6:.0f}M")
    if max_value >= 1e6:
        return mticker.FuncFormatter(lambda v, _: f"{v / 1e6:.1f}M")
    return mticker.FuncFormatter(lambda v, _: f"{v / 1e3:.0f}k")


def shade_icmr_window(ax, label=True):
    """Light band marking the years covered by the ICMR-NCDIR projections (2012-2036)."""
    ax.axvspan(ICMR_START, ICMR_END, color=sp.GREY, alpha=0.10, lw=0,
               label="ICMR-NCDIR window" if label else None, zorder=0)


def style_pop_axis(ax, title=None, ylabel="Female pop. [millions]", ymax=None):
    if ymax is not None:
        ax.yaxis.set_major_formatter(persons_formatter(ymax))
    ax.set_xlabel("Year")
    ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)
    ax.grid(alpha=0.25)
    return ax


def save(fig, name):
    """Save PDF + PNG into FIG_DIR and keep the figure open for display."""
    os.makedirs(FIG_DIR, exist_ok=True)
    sp.save(fig, name, outdir=FIG_DIR, formats=("pdf", "png"), close=False, verbose=False)


def growth_pct(df):
    """Annual growth in % along the year axis (row t is growth t-1 -> t)."""
    return (df / df.shift(1) - 1) * 100
