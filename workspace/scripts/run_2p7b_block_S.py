"""The 2.7B per-operator account at a chosen sequence length (the workload
reuse study, 2026-10-02): the same run as run_2p7b_block.py (same fabric,
policies, histogram source) with S as an argument, writing
analysis/scale_2p7b_per_op_S{S}.json. prefill uses S input tokens; decode
is one token over an S-token K/V cache. Replaces the derived accounts that
scripts/workload_reuse.py builds from the S = 512 measurement when the
mapper is available.

    python3 scripts/run_2p7b_block_S.py 128
    python3 scripts/run_2p7b_block_S.py 1024 [hist_source]
"""
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
os.environ.setdefault("CIMSIM_FABRIC", os.path.join(WS, "models", "fabric", "mlx300_multidie.yaml"))

import scripts.crossbar_comm as cc                      # noqa: E402
from scripts import fabric as fabric_mod               # noqa: E402
from scripts import llm_workload as lw                 # noqa: E402
from scripts import mlx_system as mlx                  # noqa: E402
from scripts import placement as pm                    # noqa: E402
from scripts.run_2p7b_block import CFG, REF_WC, with_macro_bw   # noqa: E402

OUT = os.path.join(WS, "analysis")


def main():
    S = int(sys.argv[1])
    hist = sys.argv[2] if len(sys.argv) > 2 else "opt_2p7b"
    fab = mlx.FABRIC
    fab_bw = with_macro_bw(fab, REF_WC)
    pl, pl_bw = pm.sequential_fill(fab), pm.sequential_fill(fab_bw)
    out = {"config": {"d_model": CFG.d_model, "n_heads": CFG.n_heads, "d_ff": CFG.d_ff,
                      "n_layers": CFG.n_layers, "S": S, "name": CFG.name},
           "ref_words_per_cycle": REF_WC, "phases": {}, "hist_source": hist,
           "derivation": "measured: one mapper run per operator at this S"}
    for phase in ("prefill", "decode"):
        recs = []
        for op in lw.block_ops(CFG, S=S, phase=phase):
            pol = "spatial_multi_die" if op.kind == "static" else "reject"
            print(f"[{phase} S={S}] {op.name} P={op.P} C={op.C} M={op.M} N={op.N}", flush=True)
            r = lw.run_op(op, phase=phase, overcapacity=pol, save_comm=False, hist_source=hist)
            res = r["result"]
            flows, _, _, _ = cc.build_flows(res.output_dir, verbose=False, fabric=fab, placement=pl)
            occ = cc.link_occupancy(flows, fab_bw, res.cycle_seconds, pl_bw)
            die_flows = [f for f in flows if f["level_name"] == "die" and f["volume"] > 0]
            recs.append({"name": op.name, "kind": op.kind,
                         "dies": r["dies_for_op"] if op.kind == "static" else 1,
                         "energy_J": r["total_J"], "compute_s": r["compute_latency_s"],
                         "write_s": r["write_latency_s"], "cycle_s": res.cycle_seconds,
                         "ondie_serial_ref_s": occ["serialization_s"],
                         "die_flow_words": [f["volume"] for f in die_flows],
                         "die_flow_down": [f.get("down", f["volume"]) for f in die_flows],
                         "die_flow_up": [f.get("up", 0.0) for f in die_flows]})
        out["phases"][phase] = recs
    out["fabric"] = fabric_mod.provenance(mlx.FABRIC)
    path = os.path.join(OUT, f"scale_2p7b_per_op_S{S}.json")
    json.dump(out, open(path, "w"), indent=1)
    print("->", path)


if __name__ == "__main__":
    main()
