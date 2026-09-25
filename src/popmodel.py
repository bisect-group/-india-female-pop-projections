"""popmodel - age-structured population ODE: data loading, experiments, fitting, diagnostics, plots.

Model (16 five-year bands, i = 1..16):
    dP_1/dt  = Lambda(t) - (k_1 + mu_1) P_1
    dP_i/dt  = k_{i-1} P_{i-1} - (k_i + mu_i) P_i        i = 2..15
    dP_16/dt = k_15 P_15 - mu_16 P_16                     (75+ is open-ended)

Each experiment chooses how Lambda, mu and k are represented:
    Lambda : "const" (one fitted value)  | "time" (p x a data-driven driver Lambda*(t), p fitted)
    mu     : "scalar" (one fitted rate)  | "vector" (16 fitted rates) | "fixed" (life table, not fitted)
    k      : "fit" (15 fitted rates)     | "fixed" (k_i = 1 / band width = 1/5 per year)
"""
import os
import json

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.integrate import odeint
from scipy.optimize import least_squares

import popproj as px
from popproj import sp

BANDS = px.BANDS
NB = len(BANDS)
BAND_WIDTH = 5.0
K_FIXED = 1.0 / BAND_WIDTH

OUT_DIR = px.OUT_DIR                      # where the pre-built track files live (outputs/ in the repository)
MU_FILE = os.environ.get("POPMODEL_MU_FILE", os.path.join(
    px.RAW, "life_table", "India_Female_LifeTable_MeanQ_1950_2100.xlsx"))

# ---- Experiments -------------------------------------------------------------------
EXPERIMENTS = {
    # Part I - k calibrated
    "E1":  dict(lam="const", mu="scalar", k="fit"),
    "E2":  dict(lam="const", mu="vector", k="fit"),
    "E3":  dict(lam="const", mu="fixed",  k="fit"),
    "E4":  dict(lam="time",  mu="scalar", k="fit"),
    "E5":  dict(lam="time",  mu="vector", k="fit"),
    "E6":  dict(lam="time",  mu="fixed",  k="fit"),
    # Part II - k fixed at 1 / band width
    "E7":  dict(lam="const", mu="scalar", k="fixed"),
    "E8":  dict(lam="const", mu="vector", k="fixed"),
    "E9":  dict(lam="const", mu="fixed",  k="fixed"),
    "E10": dict(lam="time",  mu="scalar", k="fixed"),
    "E11": dict(lam="time",  mu="vector", k="fixed"),
    "E12": dict(lam="time",  mu="fixed",  k="fixed"),
}
TWIN = {e: f"E{int(e[1:]) + 6}" for e in ["E1", "E2", "E3", "E4", "E5", "E6"]}
_LAM_TXT = {"const": "constant Λ", "time": "time-varying Λ(t) = p·Λ*(t)"}
_MU_TXT = {"scalar": "one calibrated μ", "vector": "16 calibrated μ_i", "fixed": "life-table μ_i (fixed)"}
_K_TXT = {"fit": "15 calibrated k_i", "fixed": "k_i = 1/5 (fixed)"}


def describe(name):
    s = EXPERIMENTS[name]
    return f"{name}: {_LAM_TXT[s['lam']]}, {_MU_TXT[s['mu']]}, {_K_TXT[s['k']]}"


def experiment_table():
    rows = []
    for e, s in EXPERIMENTS.items():
        n = (1) + {"scalar": 1, "vector": NB, "fixed": 0}[s["mu"]] + {"fit": NB - 1, "fixed": 0}[s["k"]]
        rows.append({"experiment": e, "recruitment Λ": _LAM_TXT[s["lam"]], "mortality μ": _MU_TXT[s["mu"]],
                     "maturation k": _K_TXT[s["k"]], "fitted parameters": n})
    return pd.DataFrame(rows).set_index("experiment")


# ---- Data ------------------------------------------------------------------------------
DEFAULT_VARIANT = {"A": "A1", "B": "B-taper", "C": "B-taper_hold_A1-blend"}
DEFAULT_STATE_VARIANT = {"A": "A1", "B": "B-hold_hold", "C": "B-taper_hold_A1-blend"}


def load_track(track, variant=None, unit="India", out_dir=None):
    """Female population (year x 16 bands, persons) for a track built by the population notebook.

    India: A -> trackA_india.xlsx sheet (A1, A1-blend, A2, A2-blend); B -> trackB_india.xlsx sheet
    (B-hold, B-taper, B-smooth); C -> trackC_india_<tag>.xlsx. States: the long parquet files.
    """
    d = out_dir or OUT_DIR
    if unit == "India":
        v = variant or DEFAULT_VARIANT[track]
        if track in ("A", "B"):
            df = pd.read_excel(os.path.join(d, f"track{track}", f"track{track}_india.xlsx"), sheet_name=v)
        else:
            df = pd.read_excel(os.path.join(d, "trackC", f"trackC_india_{v}.xlsx"))
        return df.set_index("Year")[BANDS].astype(float)
    v = variant or DEFAULT_STATE_VARIANT[track]
    long = pd.read_parquet(os.path.join(d, f"track{track}", f"track{track}_states_{v}.parquet"))
    long = long[long.state == unit]
    if long.empty:
        raise KeyError(f"{unit} not found in track {track} ({v})")
    return long.pivot(index="year", columns="band", values="females")[BANDS].astype(float)


def life_table_mu(path=None):
    """Annual mortality hazard by band from a 22-row life table of q values (column Mean_q_1950_2100)."""
    q = pd.read_excel(path or MU_FILE)["Mean_q_1950_2100"].values.astype(float)
    mu = np.zeros(NB)
    mu[0] = -np.log(max((1 - q[0]) * (1 - q[1]), 1e-12)) / 5            # age 0 and 1-4 combined
    for b in range(1, 15):                                               # 05-09 ... 70-74
        mu[b] = -np.log(max(1 - q[b + 1], 1e-12)) / 5
    sub_q = q[16:22]                                                     # 75-79 ... 100+
    l = np.ones(7)
    for j in range(6):
        l[j + 1] = l[j] * max(1 - sub_q[j], 0.0)
    L = np.array([5 * (l[j] + l[j + 1]) / 2 for j in range(6)])
    mu_sub = np.array([-np.log(max(1 - sub_q[j], 1e-12)) / 5 for j in range(5)] + [1.0])
    mu[15] = (mu_sub * L).sum() / L.sum()
    return pd.Series(mu, index=BANDS)


def lambda_driver(P, kind="w20_29_lead10"):
    """Shape of recruitment Lambda*(t) taken from the same population series.

    w20_29_lead10 : women aged 20-29, ten years ahead (clamped at the last year)
    w15_49        : women aged 15-49 in the same year (women of reproductive age)
    """
    if kind == "w20_29_lead10":
        w = P[["20-24", "25-29"]].sum(axis=1)
        yrs = P.index.values
        return pd.Series(np.interp(yrs + 10, yrs, w.values), index=P.index)
    if kind == "w15_49":
        return P[BANDS[3:10]].sum(axis=1)
    raise ValueError(kind)


# ---- Model -------------------------------------------------------------------------------
def rhs(P, t, lam_t, lam_v, mu, k):
    flow = k * P[:-1]                              # maturation out of bands 1..15
    dP = -mu * P
    dP[:-1] -= flow
    dP[1:] += flow
    dP[0] += np.interp(t, lam_t, lam_v)
    return dP


def simulate(P0, years, lam_t, lam_v, mu, k):
    return odeint(rhs, P0, years, args=(lam_t, lam_v, mu, k), rtol=1e-8, atol=1e-2)


# ---- Fitting -----------------------------------------------------------------------------
def _setup(spec, data, mu_lt, driver):
    """Initial guesses, bounds and an unpack function for the chosen experiment."""
    obs0 = data["00-04"].values
    inflow = np.mean(obs0 * (K_FIXED + mu_lt.iloc[0]))            # rough recruitment scale
    blocks = []                                                   # (name, x0, lb, ub, scale)
    if spec["lam"] == "const":
        blocks.append(("Lambda", np.array([1.0]), [0.0], [50.0], inflow))
    else:
        blocks.append(("p", np.array([1.0]), [0.0], [50.0], inflow / driver.mean()))
    if spec["mu"] == "scalar":
        blocks.append(("mu", np.array([0.01]), [0.0], [1.0], 1.0))
    elif spec["mu"] == "vector":
        blocks.append(("mu", np.clip(mu_lt.values, 1e-4, None), [0.0] * NB, [1.0] * NB, 1.0))
    if spec["k"] == "fit":
        blocks.append(("k", np.full(NB - 1, K_FIXED), [0.01] * (NB - 1), [1.5] * (NB - 1), 1.0))
    x0 = np.concatenate([b[1] for b in blocks])
    lb = np.concatenate([b[2] for b in blocks]); ub = np.concatenate([b[3] for b in blocks])

    def unpack(x):
        out, i = {}, 0
        for name, v0, _, _, scale in blocks:
            n = len(v0); out[name] = x[i:i + n] * scale; i += n
        lam = out["Lambda"][0] * np.ones(len(data)) if "Lambda" in out else out["p"][0] * driver.values
        mu = (np.full(NB, out["mu"][0]) if spec["mu"] == "scalar" else
              out["mu"] if spec["mu"] == "vector" else mu_lt.values)
        k = out["k"] if spec["k"] == "fit" else np.full(NB - 1, K_FIXED)
        return lam, mu, k, out
    return x0, lb, ub, unpack


def fit(name, data, mu_lt, driver, max_nfev=4000, loss="linear", restarts=1, verbose=0):
    """Fit experiment `name` to `data` (year x 16 bands) by weighted least squares.

    Residuals are (simulated - observed) / sd_over_time for every band and year. Uses tight ODE
    tolerances and an explicit finite-difference step (ODE-solver noise otherwise stops the
    optimiser early), then restarts from the solution `restarts` times.
    """
    spec = EXPERIMENTS[name]
    years = data.index.values.astype(float)
    obs = data.values
    w = 1.0 / (obs.std(axis=0) + 1e-9)                               # per-band weight 1/sd over time
    x0, lb, ub, unpack = _setup(spec, data, mu_lt, driver)
    P0 = obs[0]

    def resid(x):
        lam, mu, k, _ = unpack(x)
        sol = simulate(P0, years, years, lam, mu, k)
        return ((sol - obs) * w).ravel()

    kw = dict(bounds=(lb, ub), method="trf", loss=loss, x_scale=1.0, diff_step=1e-3,
              ftol=1e-12, xtol=1e-12, gtol=1e-12, max_nfev=max_nfev, verbose=verbose)
    r = least_squares(resid, x0, **kw)
    for _ in range(restarts):
        r2 = least_squares(resid, r.x, **kw)
        if r2.cost <= r.cost:
            r = r2
    lam, mu, k, raw = unpack(r.x)
    span = ub - lb
    at_bound = int(np.sum((r.x - lb < 1e-6 * span) | (ub - r.x < 1e-6 * span)))
    sol = pd.DataFrame(simulate(P0, years, years, lam, mu, k), index=data.index, columns=BANDS)
    return dict(name=name, spec=spec, success=bool(r.success), nfev=int(r.nfev), cost=float(r.cost),
                n_params=len(x0), at_bound=at_bound, lam=pd.Series(lam, index=data.index), mu=pd.Series(mu, index=BANDS),
                k=pd.Series(k, index=BANDS[:-1]), raw={kk: v.tolist() for kk, v in raw.items()},
                sim=sol, metrics=metrics(sol, data), message=r.message)


def metrics(sim, data):
    ape = (sim - data).abs() / data * 100
    tot = (sim.sum(axis=1) - data.sum(axis=1)).abs() / data.sum(axis=1) * 100
    band_mape = ape.mean()
    return dict(band_mape=band_mape, mape=float(band_mape.mean()), max_ape=float(ape.max().max()),
                worst_band=str(band_mape.idxmax()), total_mape=float(tot.mean()), total_max=float(tot.max()))


def summary_table(results):
    rows = []
    for e, r in results.items():
        m = r["metrics"]
        rows.append({"experiment": e, "Λ": r["spec"]["lam"], "μ": r["spec"]["mu"], "k": r["spec"]["k"],
                     "params": r["n_params"], "at bound": r.get("at_bound", np.nan), "mean band MAPE %": m["mape"], "worst band": m["worst_band"],
                     "worst band MAPE %": m["band_mape"].max(), "max APE %": m["max_ape"],
                     "total MAPE %": m["total_mape"], "cost": r["cost"], "converged": r["success"]})
    return pd.DataFrame(rows).set_index("experiment")


def save_results(results, folder):
    os.makedirs(folder, exist_ok=True)
    summary_table(results).to_csv(os.path.join(folder, "experiment_summary.csv"))
    pd.DataFrame({e: r["metrics"]["band_mape"] for e, r in results.items()}).to_csv(os.path.join(folder, "band_mape.csv"))
    json.dump({e: dict(spec=r["spec"], raw=r["raw"], mu=r["mu"].tolist(), k=r["k"].tolist(), cost=r["cost"])
               for e, r in results.items()}, open(os.path.join(folder, "parameters.json"), "w"), indent=1)
    with pd.ExcelWriter(os.path.join(folder, "simulations.xlsx")) as xw:
        for e, r in results.items():
            s = r["sim"].copy(); s.index.name = "Year"; s["Total"] = s.sum(axis=1); s.to_excel(xw, sheet_name=e)
    return sorted(os.listdir(folder))


# ---- Plots -------------------------------------------------------------------------------
SIM_LINE = dict(color=sp.OUTC, lw=1.6, zorder=3)
OBS_DOT = dict(marker="o", s=10, color=sp.L1, linewidths=0, zorder=4)
ANCHOR_DOT = dict(marker="o", s=45, color=sp.OUTC, edgecolors="white", linewidths=1.0, zorder=5)
ANCHOR_STRIDE = 10


def _panel(ax, years, sim, obs, title, ylabel="Female pop. [millions]"):
    ax.plot(years, sim, label="Simulation", **SIM_LINE)
    ax.scatter(years, obs, label="Observed", **OBS_DOT)
    a = np.arange(years.min(), years.max() + 1, ANCHOR_STRIDE)
    ax.scatter(a, np.interp(a, years, sim), label=f"Sim @ every {ANCHOR_STRIDE} yr", **ANCHOR_DOT)
    px.style_pop_axis(ax, title, ylabel=ylabel, ymax=max(np.max(sim), np.max(obs)))


def plot_fit(res, data, title_prefix, fig_name=None):
    """4x4 grid of band fits + a row with the total, fitted mu and fitted k."""
    yrs = data.index.values
    fig, axs = plt.subplots(4, 4, figsize=(14, 11))
    for ax, b in zip(axs.flat, BANDS):
        _panel(ax, yrs, res["sim"][b].values, data[b].values, f"Age band {b}")
    h, l = axs[0, 0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=3, bbox_to_anchor=(0.5, -0.02), frameon=False)
    m = res["metrics"]
    fig.suptitle(f"{title_prefix} — {describe(res['name'])}\nmean band MAPE {m['mape']:.2f} %, worst {m['worst_band']} "
                 f"{m['band_mape'].max():.2f} %, total MAPE {m['total_mape']:.2f} %", y=1.02)
    plt.tight_layout()
    if fig_name:
        px.save(fig, fig_name + "_bands")
    plt.show()

    fig, axs = plt.subplots(1, 4, figsize=(19, 4.3))
    _panel(axs[0], yrs, res["sim"].sum(axis=1).values, data.sum(axis=1).values, "Total female population")
    axs[1].plot(yrs, res["lam"].values / 1e6, color=sp.OUTC, lw=1.6)
    axs[1].set_title("Recruitment Λ(t) into 00-04"); axs[1].set_xlabel("Year"); axs[1].set_ylabel("Λ [millions / yr]"); axs[1].grid(alpha=0.25)
    x = np.arange(NB)
    axs[2].plot(x, res["mu"].values * 1000, color=sp.OUTC, marker="o", ms=3, label="model μ")
    axs[2].plot(x, LT_REF.values * 1000 if LT_REF is not None else np.nan * x, color=sp.GREY, ls=":", marker="s", ms=3, label="life table")
    axs[2].set_yscale("log"); axs[2].set_xticks(x); axs[2].set_xticklabels(BANDS, rotation=60, ha="right", fontsize=7)
    axs[2].set_ylabel("μ [per 1000 per yr]"); axs[2].set_title("Mortality by band"); axs[2].grid(alpha=0.25); axs[2].legend(frameon=False, fontsize=8)
    x2 = np.arange(NB - 1)
    axs[3].plot(x2, res["k"].values, color=sp.OUTC, marker="o", ms=3, label="model k")
    axs[3].axhline(K_FIXED, color=sp.GREY, ls=":", label="1 / band width = 0.2")
    axs[3].set_xticks(x2); axs[3].set_xticklabels([f"{a}→{b}" for a, b in zip(BANDS[:-1], BANDS[1:])], rotation=70, ha="right", fontsize=6)
    axs[3].set_ylabel("k [per yr]"); axs[3].set_title("Maturation rate"); axs[3].grid(alpha=0.25); axs[3].legend(frameon=False, fontsize=8)
    for ax in axs[1:]:
        sp.lock_ticks(ax, "x")
    plt.tight_layout()
    if fig_name:
        px.save(fig, fig_name + "_params")
    plt.show()


LT_REF = None      # set by the notebook to the life-table mu for reference in plots


def plot_comparison(results, data, title, fig_name=None):
    tab = summary_table(results)
    base = [e for e in ["E1", "E2", "E3", "E4", "E5", "E6"] if e in results]
    fig, axs = plt.subplots(1, 2, figsize=(17, 5))
    xi = np.arange(len(base))
    for col, ax, lab in [("mean band MAPE %", axs[0], "Mean band MAPE [%]"), ("total MAPE %", axs[1], "Total MAPE [%]")]:
        ax.bar(xi - 0.2, tab.loc[base, col], width=0.4, color=sp.L2, label="k calibrated (E1–E6)")
        twins = [TWIN[e] for e in base if TWIN[e] in results]
        ax.bar(xi[:len(twins)] + 0.2, tab.loc[twins, col], width=0.4, color=sp.OUTC, label="k = 1/5 (E7–E12)")
        ax.set_xticks(xi); ax.set_xticklabels([f"{e} / {TWIN[e]}\n{_LAM_TXT[EXPERIMENTS[e]['lam']].split(' =')[0]}\n{_MU_TXT[EXPERIMENTS[e]['mu']]}" for e in base], fontsize=7)
        sp.lock_ticks(ax, "x"); ax.set_ylabel(lab); ax.set_yscale("log"); ax.grid(alpha=0.25, axis="y"); ax.legend(frameon=False)
    fig.suptitle(f"{title}: fit error by experiment (log scale)", y=1.02)
    plt.tight_layout()
    if fig_name:
        px.save(fig, fig_name + "_errors")
    plt.show()

    M = pd.DataFrame({e: r["metrics"]["band_mape"] for e, r in results.items()})
    fig, ax = plt.subplots(figsize=(14, 6))
    im = ax.imshow(np.log10(M.values.clip(1e-3)), aspect="auto", cmap="magma_r")
    ax.set_xticks(range(M.shape[1])); ax.set_xticklabels(M.columns); ax.set_yticks(range(NB)); ax.set_yticklabels(BANDS)
    sp.lock_ticks(ax, "both")
    for i in range(NB):
        for j in range(M.shape[1]):
            ax.text(j, i, f"{M.values[i, j]:.1f}", ha="center", va="center", fontsize=6,
                    color="white" if np.log10(max(M.values[i, j], 1e-3)) > np.log10(M.values.max()) - 1 else "black")
    ax.set_xlabel("Experiment"); ax.set_ylabel("Age band"); ax.set_title(f"{title}: MAPE by band and experiment [%]")
    fig.colorbar(im, ax=ax, label="log10 MAPE [%]")
    plt.tight_layout()
    if fig_name:
        px.save(fig, fig_name + "_band_heatmap")
    plt.show()

    fig, axs = plt.subplots(1, 2, figsize=(17, 4.8))
    x2 = np.arange(NB - 1)
    for e in [e for e in base]:
        axs[0].plot(x2, results[e]["k"].values, marker="o", ms=3, lw=1.3, label=e)
    axs[0].axhline(K_FIXED, color="black", ls=":", label="1/5")
    axs[0].set_xticks(x2); axs[0].set_xticklabels([f"{a}→{b}" for a, b in zip(BANDS[:-1], BANDS[1:])], rotation=70, ha="right", fontsize=7)
    axs[0].set_ylabel("k [per yr]"); axs[0].set_title("Calibrated maturation rates (E1–E6) vs 1/5"); axs[0].grid(alpha=0.25)
    axs[0].legend(frameon=False, fontsize=8, ncol=2)
    x = np.arange(NB)
    for e, r in results.items():
        if r["spec"]["mu"] != "fixed":
            axs[1].plot(x, r["mu"].values * 1000, marker="o", ms=3, lw=1.2, label=e,
                        ls="-" if r["spec"]["k"] == "fit" else "--")
    if LT_REF is not None:
        axs[1].plot(x, LT_REF.values * 1000, color="black", ls=":", lw=2, label="life table")
    axs[1].set_yscale("log"); axs[1].set_xticks(x); axs[1].set_xticklabels(BANDS, rotation=60, ha="right", fontsize=7)
    axs[1].set_ylabel("μ [per 1000 per yr]"); axs[1].set_title("Calibrated mortality vs life table"); axs[1].grid(alpha=0.25)
    axs[1].legend(frameon=False, fontsize=7, ncol=3)
    for ax in axs:
        sp.lock_ticks(ax, "x")
    plt.tight_layout()
    if fig_name:
        px.save(fig, fig_name + "_parameters")
    plt.show()
    return tab
