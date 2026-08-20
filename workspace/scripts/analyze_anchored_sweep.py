"""Anchored sweep: the contention results at PUBLISHED NoC bandwidths.

Everything so far quoted multipliers at an example operating point. This
script replaces that with the three sourced anchors from analysis/ANCHORS.md
(Simba on-die 8.75 GB/s, ESP 32 GB/s, FlooNoC 80.6 GB/s -- all per link, one
direction) and reads the whole scheme x hub-position grid at each, for the
two conditions where the network can matter:

  * prefill, attention on chip  (compute-dominated -- the network races 249ms)
  * decode, attention offloaded (the serial K/V write left with the attention,
    so the network races ~1ms of compute -- the most exposed condition)

Method: per-op compute/write/serialization at the reference input come from
analysis/contention_system.json (real mapper runs); serialization scales
exactly as 1/bandwidth, so every anchor readout is closed-form. Note the
core-level ("region") allocation cannot enter this sweep honestly: those
links carry no bandwidth or price yet (FIXLIST O1) -- it stays a ranking.

Usage (container): python3 scripts/analyze_anchored_sweep.py
"""
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = "/home/workspace/analysis"
REF_WC = 16384.0                 # words/cycle the stored serializations used
CYC = 1.4485714285714284e-06
WC_PER_GBPS = 1e9 * CYC          # words/cycle per GB/s (word = 1 byte)

ANCHORS = [("Simba on-die\n8.75 GB/s (silicon)", 8.75),
           ("ESP\n32 GB/s", 32.0),
           ("FlooNoC\n80.6 GB/s", 80.6)]
STATIC = {"qkv_proj", "out_proj", "ffn1", "ffn2"}
N_LAYERS = 24
ORDER = ["star (private links)", "mesh, glb centre", "mesh, glb corner",
         "h-tree (k=4)", "bus (shared medium)"]
SHORT = ["star", "mesh\ncentre", "mesh\ncorner", "h-tree", "bus"]


def load():
    with open(os.path.join(OUT, "contention_system.json")) as f:
        return json.load(f)


def stack(per_op, wc, prefill_A):
    """Whole-stack latency at bandwidth `wc` words/cycle."""
    tot = 0.0
    for o in per_op:
        if not prefill_A and o["name"] not in STATIC:
            continue
        ser = o["serial_s"] * REF_WC / wc
        wr = o["write_s"] if prefill_A else 0.0
        tot += wr + max(o["compute_s"], ser)
    return tot * N_LAYERS


def main():
    d = load()
    conds = [("prefill, attention on chip", "prefill", True),
             ("decode, attention offloaded", "decode", False)]
    results = {}
    for title, phase, is_A in conds:
        per = d["phases"][phase]["per_op"]
        base = stack(next(iter(per.values())), 1e18, is_A)   # no-queue stack
        print(f"=== {title}: no-queue stack {base*1e3:.3f} ms ===")
        hdr = f"{'scheme / hub position':24}" + "".join(
            f"{a.splitlines()[0]:>18}" for a, _ in ANCHORS)
        print(hdr)
        rows = {}
        for label in ORDER:
            cells = []
            for _, gbps in ANCHORS:
                tot = stack(per[label], gbps * WC_PER_GBPS, is_A)
                cells.append(tot / base)
            rows[label] = cells
            print(f"  {label:22}" + "".join(f"{c:>17.2f}x" for c in cells))
        results[title] = {"base_s": base, "mult": rows}
        print()

    # ---------------- figure 1: anchored readouts, grouped bars
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 4.8))
    colors = ["#d1495b", "#e8a13c", "#2a9d8f"]        # low, mid, high
    for ax, (title, phase, is_A) in zip(axes, conds):
        rows = results[title]["mult"]
        x = np.arange(len(ORDER))
        for k, ((aname, _), c) in enumerate(zip(ANCHORS, colors)):
            vals = [rows[l][k] for l in ORDER]
            ax.bar(x + (k - 1) * 0.26, vals, 0.24, color=c,
                   label=aname.replace("\n", " "))
            for i, v in enumerate(vals):
                if v > 1.004:
                    ax.text(i + (k - 1) * 0.26, v + 0.03, f"{v:.2f}",
                            ha="center", fontsize=7.5)
        ax.axhline(1.0, color="0.4", lw=1)
        ax.set_xticks(x); ax.set_xticklabels(SHORT, fontsize=9)
        ax.set_ylabel("whole-stack latency / no-queue stack")
        ax.set_title(title, fontsize=10.5)
        ax.grid(alpha=0.25, axis="y")
        ax.legend(fontsize=7.5)
    fig.suptitle("The contention results at PUBLISHED link bandwidths "
                 "(anchors sourced in ANCHORS.md)", fontsize=12)
    p1 = os.path.join(OUT, "anchored_sweep.png")
    fig.tight_layout(rect=[0, 0, 1, 0.9]); fig.savefig(p1, dpi=130)
    plt.close(fig)
    print(f"PNG -> {p1}")

    # ---------------- figure 2: sweep curves in GB/s with the anchor band
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.0))
    bw_wc = np.array([2.0 ** k for k in range(9, 22)])
    bw_gbps = bw_wc / WC_PER_GBPS
    for ax, (title, phase, is_A) in zip(axes, conds):
        per = d["phases"][phase]["per_op"]
        base = results[title]["base_s"]
        for label, short in zip(ORDER, [s.replace("\n", " ") for s in SHORT]):
            ys = [stack(per[label], wc, is_A) / base for wc in bw_wc]
            ax.plot(bw_gbps, ys, "o-", ms=3, lw=1.5, label=short)
        lo, hi = ANCHORS[0][1], ANCHORS[-1][1]
        ax.axvspan(lo, hi, color="#2a9d8f", alpha=0.12)
        for aname, g in ANCHORS:
            ax.axvline(g, color="#1c6b60", ls=":", lw=1.0)
        ax.text(np.sqrt(lo * hi), ax.get_ylim()[1], "", fontsize=8)
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlabel("per-link bandwidth (GB/s) -- shaded: published NoC range")
        ax.set_ylabel("whole-stack latency / no-queue stack")
        ax.set_title(title, fontsize=10.5)
        ax.grid(alpha=0.3, which="both")
        ax.legend(fontsize=8)
    fig.suptitle("Where published chips land on our threshold curves",
                 fontsize=12)
    p2 = os.path.join(OUT, "anchored_band.png")
    fig.tight_layout(rect=[0, 0, 1, 0.9]); fig.savefig(p2, dpi=130)
    plt.close(fig)
    print(f"PNG -> {p2}")

    with open(os.path.join(OUT, "anchored_sweep.json"), "w") as f:
        json.dump({"anchors_gbps": {a: g for a, g in ANCHORS},
                   "wc_per_gbps": WC_PER_GBPS,
                   "results": {t: {"base_s": r["base_s"], "mult": r["mult"]}
                               for t, r in results.items()}}, f, indent=1)
    print("JSON -> anchored_sweep.json")


if __name__ == "__main__":
    main()
