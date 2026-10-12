"""Measured per-operator accounts for the V3 model family (2026-10-08): one
mapper run per operator and phase for a (d, dh, d_ff, S) point, written to
analysis/v3/accounts/d{d}_dh{dh}_ff{d_ff}_S{S}.json in the frozen account's
format (plus a derivation field). Depth-independent: the block-level
account serves every L. scripts/v3_sweep.py prefers these files over its
derived accounts.

    python3 scripts/v3_measure_accounts.py "2560,80,10240,512" "1024,64,4096,512" ...
    python3 scripts/v3_measure_accounts.py --list e2_width      # the (d, dh, d_ff, S) points a sweep unit needs
"""
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
os.environ.setdefault("CIMSIM_FABRIC", os.path.join(WS, "models", "fabric", "mlx300_multidie.yaml"))

OUT = os.path.join(WS, "analysis", "v3", "accounts")


def points_for(unit):
    from scripts import v3_sweep as v
    pts = []
    for s in v.unit_specs(unit):
        pts.append((s["d"], s["dh"], s["d_ff"], s["S"]))
    return sorted(set(pts))


def measure(d, dh, d_ff, S, hist="opt_2p7b"):
    import scripts.crossbar_comm as cc
    from scripts import fabric as fabric_mod
    from scripts import llm_workload as lw
    from scripts import mlx_system as mlx
    from scripts import placement as pm
    from scripts.run_2p7b_block import REF_WC, with_macro_bw
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"d{d}_dh{dh}_ff{d_ff}_S{S}.json")
    if os.path.exists(path):
        print("exists", path); return
    cfg = lw.GptConfig(d_model=d, n_heads=d // dh, d_ff=d_ff, n_layers=32, name=f"w{d}_dh{dh}_ff{d_ff}")
    fab = mlx.FABRIC
    fab_bw = with_macro_bw(fab, REF_WC)
    pl, pl_bw = pm.sequential_fill(fab), pm.sequential_fill(fab_bw)
    out = {"config": {"d_model": d, "n_heads": d // dh, "d_ff": d_ff, "n_layers": 32, "S": S, "name": cfg.name},
           "ref_words_per_cycle": REF_WC, "phases": {}, "hist_source": hist,
           "derivation": "measured: one mapper run per operator at this (d, dh, d_ff, S); block-level, depth-independent"}
    for phase in ("prefill", "decode"):
        recs = []
        for op in lw.block_ops(cfg, S=S, phase=phase):
            pol = "spatial_multi_die" if op.kind == "static" else "reject"
            if op.kind == "dynamic" and lw.op_weight_cells(op) > lw.DIE_WEIGHT_CELLS:
                out["phases"][phase] = None
                out["infeasible"] = f"{phase}: {op.name} needs {lw.op_weight_cells(op)} cells > one die"
                print(out["infeasible"], flush=True)
                break
            print(f"[{cfg.name} {phase} S={S}] {op.name} P={op.P} C={op.C} M={op.M} N={op.N}", flush=True)
            r = lw.run_op(op, phase=phase, overcapacity=pol, save_comm=False, hist_source=hist,
                          strict_traffic=False)
            res = r["result"]
            serial = None; die_flows = []
            if r["traffic_guard_error"] is None:
                try:
                    flows, _, _, _ = cc.build_flows(res.output_dir, verbose=False, fabric=fab, placement=pl)
                    occ = cc.link_occupancy(flows, fab_bw, res.cycle_seconds, pl_bw)
                    serial = occ["serialization_s"]
                    die_flows = [f for f in flows if f["level_name"] == "die" and f["volume"] > 0]
                except ValueError as e:
                    r["traffic_guard_error"] = f"{type(e).__name__}: {e}"
            recs.append({"name": op.name, "kind": op.kind,
                         "dies": r["dies_for_op"] if op.kind == "static" else 1,
                         "energy_J": r["total_J"], "compute_s": r["compute_latency_s"],
                         "write_s": r["write_latency_s"], "cycle_s": res.cycle_seconds,
                         "ondie_serial_ref_s": serial,
                         "die_flow_words": [f["volume"] for f in die_flows],
                         "die_flow_down": [f.get("down", f["volume"]) for f in die_flows],
                         "die_flow_up": [f.get("up", 0.0) for f in die_flows],
                         "traffic_guard_error": r["traffic_guard_error"]})
            print(f"    compute {r['compute_latency_s']*1e3:.4f} ms | write {r['write_latency_s']*1e3:.4f} ms | "
                  f"E {r['total_J']*1e3:.4f} mJ | dies {recs[-1]['dies']}"
                  + (f" | traffic guard: {r['traffic_guard_error'][:80]}" if r["traffic_guard_error"] else ""), flush=True)
        else:
            out["phases"][phase] = recs
    out["fabric"] = fabric_mod.provenance(mlx.FABRIC)
    json.dump(out, open(path, "w"), indent=1)
    print("->", path, flush=True)


def main():
    if sys.argv[1] == "--list":
        for p in points_for(sys.argv[2]):
            print(",".join(map(str, p)))
        return
    for arg in sys.argv[1:]:
        d, dh, ff, S = (int(x) for x in arg.split(","))
        measure(d, dh, ff, S)


if __name__ == "__main__":
    main()
