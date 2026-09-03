"""The Simba-reproduction validation figure (C48, step 1, day 8):
measured placement effects vs the model's bracket, one panel per target.

Everything drawn here is read live from the closed-form runs (t1/t2/t3),
which are themselves pinned by groups 34-36 -- the figure can never
drift from the graded record. House rules: measured silicon = gray bars;
our optimistic rail (busiest-wire bound) = filled circles, solid; our
pessimistic rail (round-serialized end, A3) = open diamonds, dashed;
identity is carried by marker shape and line style, not color alone.

    python3 analyze_simba_validation.py       -> analysis/simba_validation.png
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.simba_targets import (FIG9_MEASURED, T3_COUNTS, T3_MEASURED,
                                   t1_run, t2_run, t3_run)

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(WS, "analysis", "simba_validation.png")

MEAS = dict(color="0.82", edgecolor="0.45", linewidth=0.8)
OPT = dict(color="0.1", marker="o", ms=5, lw=1.6, ls="-")
PESS = dict(color="0.1", marker="D", ms=5, mfc="white", lw=1.4, ls="--")


def main():
    r1, r2, r3 = t1_run(), t2_run(), t3_run()
    fig, axes = plt.subplots(1, 3, figsize=(13.4, 4.4))

    # ---- T1: the Fig 9 seating ladder
    ax = axes[0]
    x = np.arange(1, 6)
    ax.bar(x, FIG9_MEASURED, width=0.62, label="measured (Fig 9, pixel-read)", **MEAS)
    ax.plot(x, [r["ratio_max_end"] for r in r1["rows"]],
            label="optimistic rail (busiest-wire bound)", **OPT)
    ax.plot(x, [r["ratio_pess"] for r in r1["rows"]],
            label="pessimistic rail (round-serialized, A3)", **PESS)
    ax.set_xticks(x)
    ax.set_xticklabels(["adjacent\n(2)", "4", "6", "8", "corners\n(10)"], fontsize=7)
    ax.set_xlabel("seating: longest-pair distance (hops)", fontsize=8)
    ax.set_ylabel("latency, normalized to adjacent seating", fontsize=8)
    ax.set_title("T1  res4a_branch1 on 4 chiplets: seating spread\n"
                 "pessimistic rail tracks the ladder from below\n"
                 "(residual 0.7-5.2%, distance-linear -> BookSim)", fontsize=8)
    ax.legend(fontsize=6.4, loc="upper left")
    ax.text(0.97, 0.04, "T1b band [1.265, 5.06]:\nbar-5 rails 1.007 / 2.399\n"
                        "pessimistic end IN band;\nboth rails below silicon everywhere",
            transform=ax.transAxes, fontsize=6.4, ha="right", va="bottom", color="0.25")

    # ---- T2: per-layer data-placement speedups
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
    for xi, (o, p) in enumerate(zip(opt, pes)):        # the bracket whisker
        ax.plot([xi, xi], [min(o, p), max(o, p)], color="0.1", lw=1.0, zorder=1)
    ax.axhline(1.0, color="0.6", lw=0.8, zorder=0)
    ax.set_xticks(x)
    ax.set_xticklabels(short, fontsize=6.2)
    ax.set_ylabel("speedup: optimized / baseline placement", fontsize=8)
    ax.set_title("T2  data placement at 32 chiplets (Fig 15) + sub-case\n"
                 "the lever reproduces; best-gaining layer coincides\n"
                 "(res3a_branch1 here and in silicon)", fontsize=8)
    ax.set_ylim(0, 2.45)
    ax.text(0.52, 0.97,
            "whisker = our [optimistic, pessimistic] bracket\n"
            "sub-case: bracket [1.004, 1.622] contains measured ~1.05\n"
            "res2c tie = self-aligned baseline (tiling-freedom divergence)\n"
            "overshoots on res3a / res4b2a: missing placement-\n"
            "insensitive constants (sync) -> T2b tier-2 record",
            transform=ax.transAxes, fontsize=6.2, ha="center", va="top",
            color="0.25")

    # ---- T3: scaling shapes
    ax = axes[2]
    xs = np.arange(len(T3_COUNTS))
    tone = {"res2[a-c]_branch2b": "0.15", "res3a_branch1": "0.45",
            "res5[a-c]_branch2b": "0.68"}
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
    ax.set_xlabel("chiplets (Fig 7's data points)", fontsize=8)
    ax.set_ylabel("latency, normalized to 1 chiplet (log)", fontsize=8)
    ax.set_title("T3  scaling shape: measured class bracketed 3/3\n"
                 "by [optimistic (dotted), pessimistic (dashed)] rails;\n"
                 "graded (pess) rail alone: 1/3 -- A4-3 falsified, logged", fontsize=8)
    from matplotlib.lines import Line2D
    handles, labels = ax.get_legend_handles_labels()
    handles += [Line2D([], [], color="0.35", ls=":", marker="o", ms=3.5),
                Line2D([], [], color="0.35", ls="--", marker="D", ms=3.5,
                       mfc="white")]
    labels += ["optimistic rail (never above silicon)", "pessimistic rail"]
    ax.legend(handles, labels, fontsize=6.0, loc="lower left")

    for ax in axes:
        ax.tick_params(labelsize=7)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    fig.suptitle("Simba reproduction (worklist step 1): measured placement effects vs the model's bracket "
                 "[busiest-wire bound, round-serialized end] -- SIMBA_PREREG §8-§11",
                 fontsize=9.5)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(OUT, dpi=170)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
