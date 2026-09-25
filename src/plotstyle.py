"""Minimal plotting style used when `sciplotstyle` is not installed.

Provides the small subset of the sciplotstyle API the notebooks use: the five-colour palette,
use(), lock_ticks() and save(). Install sciplotstyle for the full house style (Fira Sans, tick thinning).
"""
import os

import matplotlib.pyplot as plt

L1 = "#341651"      # indigo
L2 = "#1C7293"      # turquoise
OUTC = "#800000"    # maroon
ACC = "#B8860B"     # amber
GREY = "#6E6E6E"    # neutral
CYCLE = [L1, L2, OUTC, ACC, GREY]
CAT = "plasma"
SEQ = "viridis"


def use(scale=1.0, **_):
    plt.rcParams.update({
        "font.size": 12 * scale, "axes.titlesize": 13 * scale, "axes.labelsize": 12.5 * scale,
        "xtick.labelsize": 11 * scale, "ytick.labelsize": 11 * scale, "legend.fontsize": 10.5 * scale,
        "lines.linewidth": 2.0, "axes.spines.top": True, "axes.spines.right": True,
        "xtick.direction": "in", "ytick.direction": "in", "savefig.dpi": 200, "savefig.bbox": "tight",
        "pdf.fonttype": 42, "ps.fonttype": 42,
    })
    plt.rcParams["axes.prop_cycle"] = plt.cycler(color=CYCLE)


def lock_ticks(ax, axis="both"):
    return ax


def save(fig, name, outdir="figs", formats=("pdf",), close=True, verbose=True, **_):
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for ext in formats:
        p = os.path.join(outdir, f"{name}.{ext}")
        fig.savefig(p, bbox_inches="tight")
        paths.append(p)
        if verbose:
            print("wrote", p)
    if close:
        plt.close(fig)
    return paths
