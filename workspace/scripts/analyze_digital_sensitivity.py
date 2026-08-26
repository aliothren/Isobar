"""How much of the model's latency (and energy) do the non-matmul operators
take, as a function of the digital vector unit? (O24, platform input DR-8)

softmax / GELU / LayerNorm / residual adds run on the die's digital unit,
in series with the matmuls. Their share of the whole-model time depends on
lanes x clock; their energy is dominated by glb passes and barely moves.
This script sweeps lanes x clock over the plausible range so the real
chip's values can be read off the curve, and marks the shipped generic
configuration (64 lanes @ 1 GHz) and the "keeps pace with the arrays"
sizing point (array output rate x ops per element).

Reads the matmul stack from analysis/contention_system.json (stall-free,
which already includes the elementwise terms at the shipped configuration;
those are subtracted back out here and re-added per sweep point).

Usage (container): python3 scripts/analyze_digital_sensitivity.py
"""
import dataclasses
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts import fabric as fabric_mod
from scripts import llm_workload as lw

OUT = "/home/workspace/analysis"
LANES = [8, 16, 32, 64, 128, 256]
CLOCKS = [0.5e9, 1.0e9, 2.0e9]
ARRAY_OUTPUT_RATE = 256 * 128 / 1.449e-6         # results/s: 256 arrays x 128 outputs per cycle


def main():
    with open(os.path.join(OUT, "contention_system.json")) as f:
        sysd = json.load(f)
    fab = fabric_mod.default()
    cfg = lw.GptConfig()
    S = sysd["S"]
    n = sysd["n_layers"]
    res = {"lanes": LANES, "clocks_hz": CLOCKS, "shipped": dataclasses.asdict(fab.digital),
           "array_output_rate_per_s": ARRAY_OUTPUT_RATE, "phases": {}}
    print(f"digital unit sweep; shipped {fab.digital.lanes} lanes @ {fab.digital.clock_hz/1e9:g} GHz; "
          f"array output rate {ARRAY_OUTPUT_RATE/1e9:.1f} G results/s\n")
    for phase in ("prefill", "decode"):
        ph = sysd["phases"][phase]
        matmul_s = ph["stall_free_s"] - ph.get("elementwise_s", 0.0)     # matmuls + writes only
        eops = lw.block_elementwise_ops(cfg, S=S, phase=phase)
        arith = sum(eo.arith_ops for eo in eops) * n
        res["phases"][phase] = {"matmul_stack_s": matmul_s, "arith_ops_model": arith,
                                "share": {}}
        print(f"=== {phase}: matmul stack {matmul_s*1e3:.2f} ms; non-matmul arithmetic "
              f"{arith/1e9:.2f} G ops per model ===")
        print(f"{'lanes':>6}" + "".join(f"{f'@{c/1e9:g} GHz':>14}" for c in CLOCKS))
        for L in LANES:
            row = []
            for c in CLOCKS:
                t = arith / (L * c)
                share = t / (matmul_s + t)
                res["phases"][phase]["share"][f"{L}@{c/1e9:g}GHz"] = share
                row.append(share)
            print(f"{L:>6}" + "".join(f"{s:>13.1%}" for s in row))
        print()

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    for ax, phase in zip(axes, ("prefill", "decode")):
        d = res["phases"][phase]
        for c in CLOCKS:
            ys = [d["share"][f"{L}@{c/1e9:g}GHz"] * 100 for L in LANES]
            ax.plot(LANES, ys, "o-", label=f"{c/1e9:g} GHz")
        ax.axvline(fab.digital.lanes, color="0.4", ls=":", lw=1.2)
        ax.text(fab.digital.lanes * 1.05, ax.get_ylim()[1] * 0.9, "shipped", fontsize=8, color="0.4")
        pace = ARRAY_OUTPUT_RATE * 3 / 1e9            # lanes @ 1 GHz that keep pace with 3-op softmax
        ax.axvline(pace, color="#d1495b", ls="--", lw=1.0)
        ax.text(pace * 1.05, ax.get_ylim()[1] * 0.75, "keeps pace with\nthe arrays (3 ops)",
                fontsize=8, color="#d1495b")
        ax.set_xscale("log", base=2)
        ax.set_xlabel("digital unit lanes (platform input)")
        ax.set_ylabel("non-matmul operators' share of model latency (%)")
        ax.set_title(f"{phase}: softmax + GELU + LayerNorm + residual", fontsize=10)
        ax.grid(alpha=0.3, which="both"); ax.legend(fontsize=8)
    fig.suptitle("How much of the model's time the digital vector unit takes -- read your chip's lanes x clock off the curve",
                 fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    p = os.path.join(OUT, "digital_sensitivity.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    print(f"PNG -> {p}")
    with open(os.path.join(OUT, "digital_sensitivity.json"), "w") as f:
        json.dump(res, f, indent=1)
    print("JSON -> digital_sensitivity.json")


if __name__ == "__main__":
    main()
