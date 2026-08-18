"""Bandwidth sensitivity sweep (workstream W1 / DR-2's landing pad).

Two tiers, swept separately and plotted together -- they model the same
serialization phenomenon at different places and compose by MAX:

  T2 (analytic per-link, ours):  the worst network link's occupancy
      volume/bandwidth from the STRUCTURED flows -- knows which link is hot.
      Swept in-process (no extra simulation).
  T1 (Timeloop native, storage): the die glb's read/write bandwidth pushed into
      the spec; Timeloop stretches the cycle count itself. Each point is a real
      mapper run in a subprocess with CIMSIM_FABRIC pointing at a temp variant.

REGIME NOTE (per review): activating stalls is a DIFFERENT accounting regime
from the stall-free numbers; sweep results are placeholder-bandwidth
sensitivities, not findings, until DR-2 calibrates the axis.

Usage: python3 analyze_bandwidth_sweep.py [--t2-only]
Writes analysis/bandwidth_sweep.png + a printed table.
"""
import dataclasses
import json
import os
import subprocess
import sys

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import scripts.crossbar_comm as cc
from scripts import fabric as fabric_mod
from scripts import llm_workload as lw

OUT = "/home/workspace/analysis"
# NOTE the unit: this device's cycle is ~1.45 us (analog bit-serial), so one
# word/cycle is a very SLOW link. The knee (serialization == compute) for ffn1
# sits near 3e4 w/c; sweep across it.
T2_BW = [131072.0, 32768.0, 8192.0, 2048.0, 512.0, 128.0, 32.0, 8.0]
T1_BW = [64.0, 16.0, 4.0, 1.0]                      # words/cycle, glb hub

OP = lw.Op("ffn1", "static", P=512, C=1024, M=4096)


def t2_sweep():
    """One base run; occupancy re-evaluated per bandwidth on fabric variants."""
    r = lw.run_op(OP, phase="prefill")
    flows, _, _, _ = cc.build_flows(r["output_dir"], verbose=False)
    cyc_s = r["result"].cycle_seconds
    compute = r["compute_latency_s"]
    rows = []
    base = fabric_mod.default()
    for bw in T2_BW:
        levels = [dataclasses.replace(
            lv, link=dataclasses.replace(lv.link, bandwidth_words_per_cycle=bw))
            if lv.link is not None and lv.link.cimloop_component else lv
            for lv in base.levels]                    # limit the ROUTER link only
        fab = dataclasses.replace(base, levels=levels)
        occ = cc.link_occupancy(flows, fab, cyc_s)
        rows.append({"bw": bw, "serialization_s": occ["serialization_s"],
                     "multiplier": max(compute, occ["serialization_s"]) / compute,
                     "bottleneck": occ["bottleneck"]["dst"]
                     if occ["bottleneck"] else None})
    return compute, rows


def t1_sweep():
    """One subprocess mapper run per glb-bandwidth point. Points are cached
    (each costs ~8 min of mapper); delete the cache to force re-measurement."""
    cache = os.path.join(OUT, "bandwidth_sweep_t1.json")
    if os.path.exists(cache):
        with open(cache) as f:
            rows = json.load(f)
        if [r["bw"] for r in rows] == T1_BW:
            print("  T1: using cached points", flush=True)
            return rows
    base_yaml = os.path.join("/home/workspace/models/fabric/mlx300.yaml")
    rows = []
    for bw in T1_BW:
        text = open(base_yaml).read().replace(
            "    - name: die\n      per_parent: 1",
            f"    - name: die\n      per_parent: 1\n"
            f"      hub_bandwidth_words_per_cycle: {bw}")
        tmp = os.path.join(OUT, f"_sweep_glb{bw:g}.yaml")
        with open(tmp, "w") as f:
            f.write(text)
        code = ("import sys, json; sys.path.insert(0, '/home/workspace')\n"
                "from scripts import llm_workload as lw\n"
                "r = lw.run_op(lw.Op('ffn1','static',P=512,C=1024,M=4096),"
                " phase='prefill')\n"
                "print('@@RESULT', json.dumps({'compute_s':"
                " r['compute_latency_s']}))\n")
        env = dict(os.environ, CIMSIM_FABRIC=tmp)
        out = subprocess.run([sys.executable, "-c", code], env=env,
                             capture_output=True, text=True, check=True).stdout
        val = json.loads(out.split("@@RESULT", 1)[1].strip())
        rows.append({"bw": bw, "compute_s": val["compute_s"]})
        os.remove(tmp)
        print(f"  T1 glb bw={bw:g} w/c -> compute {val['compute_s']:.4e} s",
              flush=True)
    with open(cache, "w") as f:
        json.dump(rows, f, indent=1)
    return rows


def main():
    compute, t2 = t2_sweep()
    print(f"\nT2 (router link, analytic; ffn1 compute = {compute:.4e} s):")
    print(f"{'bw (w/c)':>10}{'serialization (s)':>20}{'latency mult':>14}")
    for r in t2:
        print(f"{r['bw']:>10g}{r['serialization_s']:>20.4e}"
              f"{r['multiplier']:>14.2f}")

    t1 = [] if "--t2-only" in sys.argv else t1_sweep()

    plt.figure(figsize=(7.5, 5))
    plt.plot([r["bw"] for r in t2], [r["multiplier"] for r in t2], "o-",
             label="T2: router link (analytic per-link occupancy)")
    if t1:
        # normalize by the UNLIMITED-bandwidth compute time, same as T2 --
        # every plotted point is "times slower than stall-free".
        plt.plot([r["bw"] for r in t1], [r["compute_s"] / compute for r in t1],
                 "s--", label="T1: glb hub (Timeloop native throttling)")
    plt.xscale("log", base=2)
    plt.xlabel("bandwidth (words / cycle)")
    plt.ylabel("latency multiplier vs unlimited")
    plt.yscale("log")
    plt.title("ffn1 latency vs link/hub bandwidth (PLACEHOLDER axes, DR-2)\n"
              "cycle = ~1.45 us on this device, so 1 word/cycle is a slow link;\n"
              "stall-free baseline = 1.0; not comparable to stall-free numbers\n"
              "until DR-2 calibrates", fontsize=10)
    plt.grid(alpha=0.3, which="both")
    plt.legend()
    p = os.path.join(OUT, "bandwidth_sweep.png")
    plt.tight_layout()
    plt.savefig(p, dpi=120)
    print(f"PNG -> {p}")


if __name__ == "__main__":
    main()
