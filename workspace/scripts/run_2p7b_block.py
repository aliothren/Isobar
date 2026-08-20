"""Run one full transformer block of a 2.7B-class model (d=2560, ff=10240,
32 heads, 32 layers) through the platform -- the tier-L point of the scale
study. Static ops use the spatial multi-die policy (residency preserved;
4/2/5/5 dies per the power-of-two tiling planner); attention ops fit one die.

Captures per op: compute/write latency, energy, dies used, on-die (macro
link) serialization at the 16,384 w/c reference input, and the intra-op
die-level flows. One JSON out; figures come from analyze_scale_tiers.py.

Usage (container): python3 scripts/run_2p7b_block.py
"""
import dataclasses
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
os.environ.setdefault("CIMSIM_FABRIC",
                      "/home/workspace/models/fabric/mlx300_multidie.yaml")

import scripts.crossbar_comm as cc
from scripts import llm_workload as lw
from scripts import mlx_system as mlx
from scripts import placement as pm

OUT = "/home/workspace/analysis"
REF_WC = 16384.0
CFG = lw.GptConfig(d_model=2560, n_heads=32, d_ff=10240, n_layers=32,
                   name="gpt-2.7B-class")
# value-distribution source: 'opt_2p7b' = REAL distributions extracted from
# facebook/opt-2.7b (extract_opt2p7b_hists.py); fall back to the borrowed
# gpt2_medium set via argv for the comparison run.
HIST = sys.argv[1] if len(sys.argv) > 1 else "opt_2p7b"
OUT_JSON = "scale_2p7b_per_op.json" if HIST == "opt_2p7b" \
    else f"scale_2p7b_per_op_{HIST}.json" 


def with_macro_bw(fab, bw):
    return dataclasses.replace(fab, levels=[
        dataclasses.replace(l, link=dataclasses.replace(
            l.link, bandwidth_words_per_cycle=bw)) if l.name == "macro" else l
        for l in fab.levels]).validate()


def main():
    fab = mlx.FABRIC
    fab_bw = with_macro_bw(fab, REF_WC)
    pl = pm.sequential_fill(fab)
    pl_bw = pm.sequential_fill(fab_bw)
    out = {"config": {"d_model": CFG.d_model, "n_heads": CFG.n_heads,
                      "d_ff": CFG.d_ff, "n_layers": CFG.n_layers,
                      "S": 512, "name": CFG.name},
           "ref_words_per_cycle": REF_WC, "phases": {}}
    for phase in ("prefill", "decode"):
        recs = []
        for op in lw.block_ops(CFG, S=512, phase=phase):
            pol = "spatial_multi_die" if op.kind == "static" else "reject"
            print(f"[{phase}] {op.name} ({op.kind}) "
                  f"P={op.P} C={op.C} M={op.M} N={op.N} policy={pol}",
                  flush=True)
            r = lw.run_op(op, phase=phase, overcapacity=pol,
                          save_comm=False, hist_source=HIST)
            res = r["result"]
            flows, _, _, _ = cc.build_flows(res.output_dir, verbose=False,
                                            fabric=fab, placement=pl)
            occ = cc.link_occupancy(flows, fab_bw, res.cycle_seconds, pl_bw)
            die_flows = [{"nodes": None, "node": f.get("node"),
                          "volume": f["volume"]}
                         for f in flows
                         if f["level_name"] == "die" and f["volume"] > 0]
            recs.append({
                "name": op.name, "kind": op.kind,
                "dies": r["dies_for_op"] if op.kind == "static" else 1,
                "energy_J": r["total_J"],
                "compute_s": r["compute_latency_s"],
                "write_s": r["write_latency_s"],
                "cycle_s": res.cycle_seconds,
                "ondie_serial_ref_s": occ["serialization_s"],
                "die_flow_words": [f["volume"] for f in die_flows],
            })
            print(f"    E {r['total_J']*1e3:.3f} mJ | compute "
                  f"{r['compute_latency_s']*1e3:.3f} ms | on-die serial@ref "
                  f"{occ['serialization_s']*1e3:.3f} ms | die edges "
                  f"{[round(v/1e6,2) for v in recs[-1]['die_flow_words']]} Mw",
                  flush=True)
        out["phases"][phase] = recs
    out["hist_source"] = HIST
    with open(os.path.join(OUT, OUT_JSON), "w") as f:
        json.dump(out, f, indent=1)
    print(f"JSON -> {OUT_JSON}")


if __name__ == "__main__":
    main()
