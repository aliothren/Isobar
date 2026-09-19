"""Does the optimal buffer position FLIP inside the published bandwidth band?

Two observations that look contradictory but are both real:
  * decode with attention on chip, at the reference input: buffer at the
    CORNER slightly beats the centre (partial occupancy -- some flows ride no
    shared wire at all);
  * offloaded decode at the anchors: corner is slightly WORSE.
The survival check asked WHERE along the bandwidth axis the sign flips --
hoping it lands inside the published range. MEASURED ANSWER: it never flips
along bandwidth within any condition. The static ops' serialization sums are
EXACTLY equal for both hub positions (57.852 us -- corner trades qkv 2x
worse against av/out_proj free), so offloaded decode's two curves share both
asymptotes and corner is only transiently worse mid-band; on-chip decode's
corner advantage exists at every bandwidth where the network matters at all,
but sits under the write shield at ~0.5%. The flip is BETWEEN CONDITIONS,
not along bandwidth: prefill prefers centre by up to 1.65x while on-chip
decode prefers corner by ~0.5%, at every point of the published band. No
bandwidth measurement resolves that tension -- but its magnitudes are so
asymmetric that centre wins any joint objective; the heuristics-fail
argument must rest on the metric disagreement and the 1.65x lever, NOT on
this reversal. (A survival check that killed an overreach before it entered
the docs.)

Closed-form over the frozen per-op fixture; no mapper run.
Usage (container): python3 scripts/analyze_corner_flip.py
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
from scripts import anchors as an
FIX = json.load(open("/home/workspace/tests/fixtures/stack_per_op_v6.json"))   # value units (C25), 2x4 default (C27)
REF = FIX["ref_words_per_cycle"]
CYC = an.CYCLE_S
WC_PER_GBPS = an.WC_PER_GBPS
BAND = (an.digital(an.ONDIE)[0].gbps, an.digital(an.ONDIE)[-1].gbps)   # the digital anchors' range
STATIC = {"qkv_proj", "out_proj", "ffn1", "ffn2"}


def stack(phase, label, gbps, on_chip):
    per = FIX["phases"][phase]["per_op"][label]
    wc = gbps * WC_PER_GBPS
    tot = 0.0
    for o in per:
        if not on_chip and o["name"] not in STATIC:
            continue
        wr = o["write_s"] if on_chip else 0.0
        tot += wr + max(o["compute_s"], o["serial_s"] * REF / wc)
    return tot


def main():
    conds = [("decode, attention on chip", "decode", True),
             ("decode, attention offloaded", "decode", False),
             ("prefill, attention on chip", "prefill", True)]
    g = np.geomspace(0.01, 300, 600)
    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    flips = {}
    for title, phase, on_chip in conds:
        ratio = np.array([stack(phase, "mesh, glb corner", x, on_chip)
                          / stack(phase, "mesh, glb centre", x, on_chip)
                          for x in g])
        ax.plot(g, ratio, lw=1.8, label=title)
        sign = np.sign(ratio - 1.0)
        idx = np.where(np.diff(sign[sign != 0]) != 0)[0]
        xs = []
        nz = np.where(sign != 0)[0]
        for k in range(len(nz) - 1):
            i, j = nz[k], nz[k + 1]
            if sign[i] != sign[j]:
                xs.append(float(np.sqrt(g[i] * g[j])))
        flips[title] = xs
        for x in xs:
            ax.axvline(x, color="0.6", ls="--", lw=0.9)
        inside = [x for x in xs if BAND[0] <= x <= BAND[1]]
        inb = (g >= BAND[0]) & (g <= BAND[1])
        print(f"{title:32} flips: "
              f"{', '.join(f'{x:.1f} GB/s' for x in xs) or 'never'}"
              f"{'  << INSIDE published band' if inside else ''}"
              f" | in-band corner/centre {ratio[inb].min():.3f}"
              f"..{ratio[inb].max():.3f}")

    ax.axhline(1.0, color="0.3", lw=1)
    ax.axvspan(*BAND, color="#2a9d8f", alpha=0.12)
    ax.text(np.sqrt(BAND[0] * BAND[1]), ax.get_ylim()[0] * 1.001,
            "digital anchors (upper bound)", fontsize=8.5, color="#1c6b60",
            ha="center", va="bottom")
    ab = an.band(an.ONDIE)
    ax.axvspan(*ab.band, color="#c9a227", alpha=0.16, lw=0)
    ax.text(np.sqrt(ab.band[0] * ab.band[1]), ax.get_ylim()[0] * 1.001,
            "analog-reality (est.)", fontsize=8.5, color="#7a5c00", ha="center", va="bottom")
    ax.set_xscale("log")
    ax.set_xlabel("per-link bandwidth (GB/s)")
    ax.set_ylabel("stack latency: corner / centre  (<1 = corner WINS)")
    ax.set_title("The buffer position never flips along the bandwidth axis:\n"
                 "the centre always wins, and the penalty vanishes above ~1 GB/s\n"
                 "(green: digital anchors, gold: analog-reality band)",
                 fontsize=10.5)
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=9)
    # WITHDRAWN 2026-09-18 (figure audit): under the current model the three
    # curves are flat at exactly 1.00 (corner_flip.json records no flip in
    # any condition), so the figure carried no information. The measurement
    # stays in the JSON; the PNG is no longer written.
    plt.close()

    with open(os.path.join(OUT, "corner_flip.json"), "w") as f:
        json.dump({"band_gbps": BAND, "flips_gbps": flips}, f, indent=1)
    print("JSON -> corner_flip.json")


if __name__ == "__main__":
    main()
