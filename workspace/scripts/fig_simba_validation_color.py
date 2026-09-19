"""Report version of the Simba-reproduction validation figure, in colour.

Same data as analyze_simba_validation.py (read live from the closed-form
runs t1/t2/t3, pinned by groups 34-36); only the styling differs: the
repository palette instead of greyscale, and the titles and annotations
stripped of the internal record references. The greyscale figure is not
touched.

    python3 scripts/fig_simba_validation_color.py -> analysis/simba_validation_color.png
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.simba_targets import (FIG9_MEASURED, T3_COUNTS, T3_MEASURED,
                                   t1_run, t2_run, t3_run)

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(WS, "analysis", "simba_validation_color.png")

NAVY, SLATE, GREEN, BRICK, AMBER = "#2e4a66", "#5d7ea3", "#2a7d4f", "#a0522d", "#7a5c00"
MEAS = dict(color="#cdd7e3", edgecolor=SLATE, linewidth=0.9)
OPT = dict(color=GREEN, marker="o", ms=5, lw=1.7, ls="-")
PESS = dict(color=BRICK, marker="D", ms=5, mfc="white", lw=1.4, ls="--")


def main():
    r1, r2, r3 = t1_run(), t2_run(), t3_run()
    fig, axes = plt.subplots(1, 3, figsize=(13.4, 4.4))

    # T1: the seating ladder
    ax = axes[0]
    x = np.arange(1, 6)
    ax.bar(x, FIG9_MEASURED, width=0.62, label="measured silicon", **MEAS)
    ax.plot(x, [r["ratio_max_end"] for r in r1["rows"]],
            label="optimistic rail (busiest-wire bound)", **OPT)
    ax.plot(x, [r["ratio_pess"] for r in r1["rows"]],
            label="pessimistic rail (round-serialized end)", **PESS)
    ax.set_xticks(x)
    ax.set_xticklabels(["adjacent\n(2)", "4", "6", "8", "corners\n(10)"], fontsize=7)
    ax.set_xlabel("seating: longest-pair distance (hops)", fontsize=8)
    ax.set_ylabel("latency, normalized to adjacent seating", fontsize=8)
    ax.set_title("T1  one operator on 4 chiplets: seating spread\n"
                 "both rails track the measured ladder from below", fontsize=8.5)
    ax.legend(fontsize=6.6, loc="upper left")

    # T2: per-layer data-placement speedups
    ax = axes[1]
    names = list(r2["layers"])
    short = [n.replace("_branch", "\nbranch") for n in names] + ["res4a\ncorner/ctr"]
    meas = [r2["measured"][n] for n in names] + [r2["measured"]["res4a_corner_vs_center"]]
    opt = [r2["layers"][n]["speedup_max_end"] for n in names] \
        + [r2["res4a_corner_vs_center"]["corner_over_center"]]
    pes = [r2["layers"][n]["speedup_pess"] for n in names] \
        + [r2["res4a_corner_vs_center"]["corner_over_center_pess"]]
    x = np.arange(len(short))
    ax.bar(x, meas, width=0.62, **MEAS)
    ax.plot(x, opt, ls="none", **{k: v for k, v in OPT.items() if k != "ls"})
    ax.plot(x, pes, ls="none", **{k: v for k, v in PESS.items() if k != "ls"})
    for xi, (o, p) in enumerate(zip(opt, pes)):
        ax.plot([xi, xi], [min(o, p), max(o, p)], color=NAVY, lw=1.0, zorder=1)
    ax.axhline(1.0, color="0.6", lw=0.8, zorder=0)
    ax.set_xticks(x)
    ax.set_xticklabels(short, fontsize=6.2)
    ax.set_ylabel("speedup: optimized / baseline placement", fontsize=8)
    ax.set_title("T2  data placement at 32 chiplets, per layer\n"
                 "the lever reproduces; the best-gaining layer coincides", fontsize=8.5)
    ax.set_ylim(0, 2.45)
    ax.text(0.5, 0.97, "whisker = the model's [optimistic, pessimistic] bracket",
            transform=ax.transAxes, fontsize=6.6, ha="center", va="top", color="0.25")

    # T3: scaling shapes
    ax = axes[2]
    xs = np.arange(len(T3_COUNTS))
    tone = {"res2[a-c]_branch2b": NAVY, "res3a_branch1": AMBER,
            "res5[a-c]_branch2b": GREEN}
    for name, d in r3["layers"].items():
        c = tone[name]
        ax.plot(xs, d["measured"], color=c, lw=2.4, ls="-", marker="s", ms=4,
                label=f"{name}: measured ({d['measured_class']})")
        ax.plot(xs, d["curve_opt"], color=c, lw=1.1, ls=":", marker="o", ms=3.5)
        ax.plot(xs, d["curve_pess"], color=c, lw=1.1, ls="--", marker="D",
                ms=3.5, mfc="white")
    ax.set_yscale("log")
    ax.set_xticks(xs)
    ax.set_xticklabels([str(n) for n in T3_COUNTS], fontsize=8)
    ax.set_xlabel("chiplets", fontsize=8)
    ax.set_ylabel("latency, normalized to 1 chiplet (log)", fontsize=8)
    ax.set_title("T3  scaling shape over the chiplet count\n"
                 "each measured class lies between the two rails", fontsize=8.5)
    handles, labels = ax.get_legend_handles_labels()
    handles += [Line2D([], [], color="0.35", ls=":", marker="o", ms=3.5),
                Line2D([], [], color="0.35", ls="--", marker="D", ms=3.5, mfc="white")]
    labels += ["optimistic rail", "pessimistic rail"]
    ax.legend(handles, labels, fontsize=6.0, loc="lower left")

    for ax in axes:
        ax.tick_params(labelsize=7)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    fig.suptitle("Simba reproduction: measured placement effects against the model's bracket "
                 "[busiest-wire bound, round-serialized end]", fontsize=9.5)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(OUT, dpi=170)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
