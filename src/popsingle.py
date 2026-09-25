"""popsingle - split 16 five-year age bands into single ages (0 ... 99, 100+) and regroup into custom bands.

Methods (all reproduce the band totals exactly):
    uniform     M1  each age gets an equal share of its band (75+ spread equally over 75 ... 100+)
    wpp         M2  each age gets WPP's share of its band in the same year
    cumspline   M3  monotone cubic (PCHIP) through cumulative population at the band edges; uses no WPP information
    wpp_smooth  M4  WPP single ages x a correction that is continuous and piecewise linear in age, solved so every
                    band total is matched exactly (the single-age analogue of the band-wise ratio method)
"""
import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator

import popproj as px

BANDS = px.BANDS
NB = len(BANDS)
AGES = np.arange(101)                                     # 100 means 100+
AGE_LABELS = [str(a) for a in range(100)] + ["100+"]
BAND_RANGE = [(int(b[:2]), int(b[:2]) + 4) for b in BANDS[:-1]] + [(75, 100)]
METHODS = ["uniform", "wpp", "cumspline", "wpp_smooth"]
METHOD_LABEL = {"uniform": "M1 uniform", "wpp": "M2 WPP proportions", "cumspline": "M3 cumulative spline",
                "wpp_smooth": "M4 WPP-guided smooth"}

MEMBER = np.zeros((NB, len(AGES)))                        # band x age membership
for i, (lo, hi) in enumerate(BAND_RANGE):
    MEMBER[i, lo:hi + 1] = 1.0


# ---- WPP single ages -------------------------------------------------------------------
def wpp_single():
    """WPP 2024 India female population by single age 0 ... 99, 100+ (persons), 1950-2100."""
    w = pd.read_csv(px.PATHS["wpp"]).set_index("Time").loc[1950:2100]
    cols = [f"Age{a}" for a in range(100)] + ["Age100+"]
    out = w[cols].astype(float) * 1e3
    out.columns = AGES
    out.index.name = "year"
    return out


# ---- Splitting ---------------------------------------------------------------------------
def _uniform(P):
    widths = MEMBER.sum(axis=1)
    return (P / widths) @ MEMBER


def _wpp(P, W):
    band_w = W @ MEMBER.T                                 # (T, 16)
    return (P / band_w) @ MEMBER * W


_EDGES = np.array([lo for lo, _ in BAND_RANGE] + [101], dtype=float)


def _cumspline(P):
    out = np.zeros((P.shape[0], len(AGES)))
    for t in range(P.shape[0]):
        cum = np.concatenate([[0.0], np.cumsum(P[t])])
        f = PchipInterpolator(_EDGES, cum)
        out[t] = np.diff(f(np.arange(102, dtype=float)))
    return np.clip(out, 0, None)


_KNOTS = np.array([lo + 2.0 for lo, _ in BAND_RANGE[:-1]] + [80.0])


def _hat_basis():
    B = np.zeros((len(AGES), NB))                         # continuous piecewise-linear, flat beyond the end knots
    for a in AGES:
        if a <= _KNOTS[0]:
            B[a, 0] = 1.0
        elif a >= _KNOTS[-1]:
            B[a, -1] = 1.0
        else:
            j = np.searchsorted(_KNOTS, a) - 1
            u = (a - _KNOTS[j]) / (_KNOTS[j + 1] - _KNOTS[j])
            B[a, j], B[a, j + 1] = 1 - u, u
    return B


HAT = _hat_basis()


def _wpp_smooth(P, W):
    out = np.zeros((P.shape[0], len(AGES)))
    for t in range(P.shape[0]):
        A = (MEMBER * W[t]) @ HAT                         # A[b, j] = sum_{a in b} W_a B_j(a)
        v = np.linalg.solve(A, P[t])
        rho = HAT @ v
        if np.any(rho < 0):                               # safeguard: fall back to WPP proportions
            out[t] = _wpp(P[t:t + 1], W[t:t + 1])[0]
        else:
            out[t] = W[t] * rho
    return out


def split(bands, method, W=None):
    """bands: DataFrame (years x 16 bands). W: WPP single ages (years x 101), needed for wpp / wpp_smooth.
    Returns DataFrame (years x 101 single ages)."""
    P = bands[BANDS].values.astype(float)
    if method in ("wpp", "wpp_smooth"):
        Wv = W.loc[bands.index].values
        out = _wpp(P, Wv) if method == "wpp" else _wpp_smooth(P, Wv)
    elif method == "uniform":
        out = _uniform(P)
    elif method == "cumspline":
        out = _cumspline(P)
    else:
        raise ValueError(method)
    return pd.DataFrame(out, index=bands.index, columns=AGES)


# ---- Custom bands ------------------------------------------------------------------------
SCHEMES = {
    "S0 original 5-year bands": [(b, lo, hi) for b, (lo, hi) in zip(BANDS, BAND_RANGE)],
    "S1 0-8, 9-14, 15-19, then 5-year": [("0-8", 0, 8), ("9-14", 9, 14)] +
        [(b, lo, hi) for b, (lo, hi) in zip(BANDS[3:], BAND_RANGE[3:])],
    "S2 0-17, 18-29, 30-65, 66+": [("0-17", 0, 17), ("18-29", 18, 29), ("30-65", 30, 65), ("66+", 66, 100)],
    "S3 0-8, 9-14, 15-26, 27-45, 46-65, 66+": [("0-8", 0, 8), ("9-14", 9, 14), ("15-26", 15, 26),
                                               ("27-45", 27, 45), ("46-65", 46, 65), ("66+", 66, 100)],
}


def regroup(single, scheme):
    """single: DataFrame (years x 101). scheme: list of (label, first_age, last_age); last_age 100 means 100+."""
    return pd.DataFrame({lab: single.loc[:, lo:hi].sum(axis=1) for lab, lo, hi in scheme}, index=single.index)


# ---- Diagnostics -------------------------------------------------------------------------
EDGE_PAIRS = [(hi, hi + 1) for _, hi in BAND_RANGE[:-1]]  # (4,5), (9,10), ..., (74,75)


def edge_steps(single):
    """How much the age profile bends at each age, split into band edges vs inside bands (ages 1-73), per year.

    For each age a, dev(a) = |g(a) - (g(a-1) + g(a+1)) / 2| with g(a) = log(P_{a+1} / P_a).
    A smooth profile has similar values at band edges and inside bands; a step at an edge shows up as a much larger edge value.
    """
    lr = np.log(single.loc[:, 1:75].values / single.loc[:, 0:74].values)       # g(a), a = 0..74
    dev = np.abs(lr[:, 1:74] - 0.5 * (lr[:, 0:73] + lr[:, 2:75]))              # a = 1..73
    ages = np.arange(1, 74)
    edge = np.isin(ages, [hi for _, hi in BAND_RANGE[:-2]])                     # 4, 9, ..., 69
    return pd.DataFrame({"at band edges": dev[:, edge].mean(axis=1), "inside bands": dev[:, ~edge].mean(axis=1)},
                        index=single.index)


def cohort_1y(single):
    """One-year cohort survival P_{a+1}(t+1) / P_a(t), ages 0-98 (years x ages). > 1 means the cohort grew."""
    v = single.values
    return pd.DataFrame(v[1:, 1:100] / v[:-1, 0:99], index=single.index[1:], columns=AGES[:99])


def time_kink(series_df):
    """Largest year-to-year change in annual growth (percentage points) for each column."""
    g = (series_df / series_df.shift(1) - 1) * 100
    return (g.diff()).abs().max()


def benchmark(W, shifts=(0, 10, -10, 20, -20), years=range(1960, 2081)):
    """Split WPP bands of year t using WPP's single-age shape from year t+shift; compare with WPP's true single ages."""
    rows = []
    for dt in shifts:
        yrs = [t for t in years if 1950 <= t + dt <= 2100]
        truth = W.loc[yrs]
        bands = pd.DataFrame(truth.values @ MEMBER.T, index=yrs, columns=BANDS)
        shape = pd.DataFrame(W.loc[[t + dt for t in yrs]].values, index=yrs, columns=AGES)
        for m in METHODS:
            est = split(bands, m, shape)
            ape = (est - truth).abs() / truth * 100
            rows.append({"shape shift (yr)": dt, "method": METHOD_LABEL[m],
                         "MAPE ages 0-74 %": ape.loc[:, 0:74].values.mean(),
                         "MAPE ages 75-99 %": ape.loc[:, 75:99].values.mean(),
                         "APE 100+ %": ape[100].mean(),
                         "max APE 0-99 %": ape.loc[:, 0:99].values.max()})
    return pd.DataFrame(rows)
