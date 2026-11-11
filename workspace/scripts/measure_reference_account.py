"""The reference account: one transformer block of the 2.7B-class model
(d = 2560, d_ff = 10240, 32 heads, 32 layers, S = 512) run through CiMLoop on
the multi-die fabric, prefill and decode. Static operators use the spatial
multi-die policy (weights resident; 4 / 2 / 5 / 5 dies by the power-of-two
tiling planner); attention operators fit one die. Per operator the account
keeps compute and write latency, energy, the dies used, the on-die
serialization at the 16,384 words-per-cycle reference input and the
die-level flows. The BookSim libraries, the reference deployment and the
derived accounts are priced from it.

The activation and weight value distributions default to the ones extracted
from facebook/opt-2.7b (extract_value_histograms.py); another histogram
source can be named as the first argument.

    python3 scripts/measure_reference_account.py [hist_source]      (container; CiMLoop)
      -> results/reference/reference_2p7b_S512.json  (or reference_2p7b_S512_<hist_source>.json)
"""
import dataclasses
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
os.environ.setdefault("CIMSIM_FABRIC", os.path.join(WS, "models", "fabric", "mlx300_multidie.yaml"))

import scripts.crossbar_comm as cc
from scripts import fabric as fabric_mod
from scripts import llm_workload as lw
from scripts import mlx_system as mlx
from scripts import paths
from scripts import placement as pm

OUT = paths.REFERENCE
REF_WC = 16384.0
CFG = lw.GptConfig(d_model=2560, n_heads=32, d_ff=10240, n_layers=32,
                   name="gpt-2.7B-class")


def with_macro_bw(fab, bw):
    return dataclasses.replace(fab, levels=[
        dataclasses.replace(l, link=dataclasses.replace(
            l.link, bandwidth_words_per_cycle=bw)) if l.name == "macro" else l
        for l in fab.levels]).validate()


def main():
    hist = sys.argv[1] if len(sys.argv) > 1 else "opt_2p7b"        # value-distribution source
    out_json = os.path.basename(paths.REFERENCE_ACCOUNT) if hist == "opt_2p7b" \
        else f"reference_2p7b_S512_{hist}.json"
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
                          save_comm=False, hist_source=hist)
            res = r["result"]
            flows, _, _, _ = cc.build_flows(res.output_dir, verbose=False,
                                            fabric=fab, placement=pl)
            occ = cc.link_occupancy(flows, fab_bw, res.cycle_seconds, pl_bw)
            die_flows = [{"nodes": None, "node": f.get("node"),
                          "volume": f["volume"],
                          "down": f.get("down", f["volume"]),
                          "up": f.get("up", 0.0)}
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
                "die_flow_down": [f["down"] for f in die_flows],
                "die_flow_up": [f["up"] for f in die_flows],
            })
            print(f"    E {r['total_J']*1e3:.3f} mJ | compute "
                  f"{r['compute_latency_s']*1e3:.3f} ms | on-die serial@ref "
                  f"{occ['serialization_s']*1e3:.3f} ms | die edges "
                  f"{[round(v/1e6,2) for v in recs[-1]['die_flow_words']]} Mw",
                  flush=True)
        out["phases"][phase] = recs
    out["hist_source"] = hist
    with open(os.path.join(paths.ensure(OUT), out_json), "w") as f:
        out["fabric"] = fabric_mod.provenance(mlx.FABRIC)
        json.dump(out, f, indent=1)
    print(f"JSON -> {os.path.join(OUT, out_json)}")


if __name__ == "__main__":
    main()
