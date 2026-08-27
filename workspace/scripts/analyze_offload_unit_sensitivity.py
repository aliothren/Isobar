"""The external attention unit as an interface (O9): how the end-to-end offload
numbers depend on the unit's compute rate, its K/V memory bandwidth and the
number of units -- so the real unit can be read off the curves.

Three readouts:
  1 prefill pipelined throughput dividend vs unit compute rate, per unit count
    (the unit is a pipeline stage serving 24/n_units layers per beat);
  2 decode ms per token vs context length, per K/V memory bandwidth
    (the unit reads the whole K/V every token);
  3 decode energy per token vs context length (K/V reads dominate).
Die-side stages come from analysis/contention_system.json via the same
half-layer rule as everywhere else.

Usage (container): python3 scripts/analyze_offload_unit_sensitivity.py
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
RATES = [0.25e12, 0.5e12, 1e12, 2e12, 4e12, 8e12, 16e12]     # MAC/s
UNITS = [1, 2, 4, 8]
KV_BW = [12.8e9, 25.6e9, 51.2e9, 102.4e9]                     # words/s (bytes/s)
CONTEXTS = [512, 1024, 2048, 4096, 8192]


def main():
    with open(os.path.join(OUT, "contention_system.json")) as f:
        sysd = json.load(f)
    fab = fabric_mod.default()
    base_unit = fab.attention_unit
    hops = lw.unit_link_hops(fab)        # die placement -> mean hops to the attach point (O9)
    cfg = lw.GptConfig()
    per = next(iter(sysd["phases"]["prefill"]["per_op"].values()))
    stage_A, stage_B = lw.half_layer_stages(per)
    dec_per = next(iter(sysd["phases"]["decode"]["per_op"].values()))
    die_decode_B = sysd["n_layers"] * sum(o["compute_s"] + o["write_s"] for o in dec_per
                                          if lw.stays_on_chip_under_offload(o["name"]))
    res = {"shipped": dataclasses.asdict(base_unit), "link_hops": hops, "stage_A_s": stage_A, "stage_B_die_s": stage_B,
           "prefill_dividend": {}, "decode_ms_per_token": {}, "decode_mJ_per_token": {}}
    print(f"die stages: A {stage_A*1e3:.2f} ms, B {stage_B*1e3:.2f} ms; shipped unit "
          f"{base_unit.mac_per_second/1e12:g} T MAC/s, K/V {base_unit.kv_words_per_second/1e9:g} GB/s\n")
    print("=== prefill pipelined dividend (end-to-end) vs unit rate, per unit count ===")
    print(f"{'rate (T MAC/s)':>16}" + "".join(f"{f'{u} unit(s)':>12}" for u in UNITS))
    for r in RATES:
        row = []
        for u in UNITS:
            unit = dataclasses.replace(base_unit, mac_per_second=r, n_units=u)
            c = lw.attention_unit_cost(cfg, 512, "prefill", unit, hops=hops)
            beat = max(stage_B, c["unit_s"] * cfg.n_layers / u)
            div = stage_A / beat - 1
            res["prefill_dividend"][f"{r/1e12:g}T@{u}"] = div
            row.append(div)
        print(f"{r/1e12:>16g}" + "".join(f"{d*100:>+11.0f}%" for d in row))
    print("\n=== decode ms per token (end-to-end) vs context, per K/V bandwidth ===")
    print(f"{'context':>10}" + "".join(f"{bw/1e9:>10.1f} GB/s" for bw in KV_BW) + f"{'on chip':>12}")
    for ctx in CONTEXTS:
        row = []
        for bw in KV_BW:
            unit = dataclasses.replace(base_unit, kv_words_per_second=bw)
            c = lw.attention_unit_cost(cfg, 512, "decode", unit, context=ctx, hops=hops)
            t = die_decode_B + cfg.n_layers * c["chain_s"]
            res["decode_ms_per_token"][f"{ctx}@{bw/1e9:g}"] = t * 1e3
            row.append(t * 1e3)
        # on-chip decode at this context: the K write does not depend on context; compute does (S rows)
        print(f"{ctx:>10}" + "".join(f"{v:>15.2f}" for v in row) + f"{sysd['phases']['decode']['stall_free_s']*1e3:>12.2f}*")
    print("  (* on-chip value at context 512; on chip the token time is write-bound and context-insensitive)")
    print("\n=== decode energy per token (end-to-end, mJ) vs context ===")
    for ctx in CONTEXTS:
        c = lw.attention_unit_cost(cfg, 512, "decode", base_unit, context=ctx, hops=hops)
        e = cfg.n_layers * c["energy_J"]
        res["decode_mJ_per_token"][str(ctx)] = e * 1e3
        print(f"  context {ctx:>5}: unit {e*1e3:.3f} mJ (K/V reads {cfg.n_layers*c['kv_J']*1e3:.3f} mJ)")

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6))
    ax = axes[0]
    for u in UNITS:
        ys = [res["prefill_dividend"][f"{r/1e12:g}T@{u}"] * 100 for r in RATES]
        ax.plot([r / 1e12 for r in RATES], ys, "o-", label=f"{u} unit(s)")
    ax.axhline((stage_A / stage_B - 1) * 100, color="0.4", ls=":", lw=1.2)
    ax.text(RATES[0] / 1e12 * 1.1, (stage_A / stage_B - 1) * 100 * 0.93, "die-side limit", fontsize=8, color="0.4")
    ax.axvline(base_unit.mac_per_second / 1e12, color="0.4", ls="--", lw=1.0)
    ax.set_xscale("log", base=2); ax.set_xlabel("unit compute rate (T MAC/s)")
    ax.set_ylabel("prefill pipelined throughput gain of offload (%)")
    ax.set_title("offload dividend, end-to-end: the unit is a pipeline stage", fontsize=10)
    ax.grid(alpha=0.3, which="both"); ax.legend(fontsize=8)
    ax = axes[1]
    for bw in KV_BW:
        ys = [res["decode_ms_per_token"][f"{ctx}@{bw/1e9:g}"] for ctx in CONTEXTS]
        ax.plot(CONTEXTS, ys, "o-", label=f"K/V memory {bw/1e9:g} GB/s")
    ax.axhline(sysd["phases"]["decode"]["stall_free_s"] * 1e3, color="#d1495b", ls="--", lw=1.0)
    ax.text(CONTEXTS[0] * 1.05, sysd["phases"]["decode"]["stall_free_s"] * 1e3 * 1.03,
            "attention on chip (write-bound)", fontsize=8, color="#d1495b")
    ax.set_xscale("log", base=2); ax.set_xlabel("context length (tokens)")
    ax.set_ylabel("decode, ms per token (end-to-end)")
    ax.set_title("decode: the unit reads the whole K/V every token", fontsize=10)
    ax.grid(alpha=0.3, which="both"); ax.legend(fontsize=8)
    fig.suptitle("The external attention unit as an interface (O9) -- read your unit off the curves", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    p = os.path.join(OUT, "offload_unit_sensitivity.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    print(f"\nPNG -> {p}")
    with open(os.path.join(OUT, "offload_unit_sensitivity.json"), "w") as f:
        json.dump(res, f, indent=1)
    print("JSON -> offload_unit_sensitivity.json")


if __name__ == "__main__":
    main()
