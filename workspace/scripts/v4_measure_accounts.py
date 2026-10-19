"""Measured per-operator accounts for the real models (next-round item 2):
one mapper run per operator and phase for (model, S), written to
analysis/v4/accounts/<model>_S{S}.json in the frozen account's format,
with the model's full configuration (including the real-model fields) and
its sources carried in the record. Container only (the mapper).

    python3 scripts/v4_measure_accounts.py opt6.7b 512 [256 1024 ...]
    python3 scripts/v4_measure_accounts.py gemma7b 512 --phases prefill
    python3 scripts/v4_measure_accounts.py --die-macros 16 opt6.7b 512          # item 3: the 16-macro die (2x), every operator
    python3 scripts/v4_measure_accounts.py --attention-die-macros 16 opt6.7b 2048  # item 2.2: attention die assumed 2x, static operators derived
"""
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
OUT = os.environ.get("CIMSIM_ACCOUNTS_OUT") or os.path.join(WS, "analysis", "v4", "accounts")   # inside the container analysis/v4 (a symlink to /data) is not mounted: write under outputs/ and copy on the host
BASE_MACROS = 8


def _fabric_for(macros):
    if macros in (None, BASE_MACROS):
        return os.path.join(WS, "models", "fabric", "mlx300_multidie.yaml")
    return os.path.join(WS, "models", "fabric", "variants", f"mlx300_multidie_m{macros}.yaml")


def _argv_int(flag):
    if flag in sys.argv:
        i = sys.argv.index(flag); v = int(sys.argv[i + 1]); del sys.argv[i:i + 2]; return v
    return None


# the fabric must be chosen before any scripts module is imported (the mapper's die hierarchy and the tiler's capacity derive from it at import)
def _argv_str(flag):
    if flag in sys.argv:
        i = sys.argv.index(flag); v = sys.argv[i + 1]; del sys.argv[i:i + 2]; return v
    return None


TILING = _argv_str("--tiling")                                # item 4.1: row / mixed / mixed2 (the split preference per operator; suffix _tl{name})
DIE_MACROS = _argv_int("--die-macros")                       # item 3: the whole die scaled; every operator measured on it; suffix _m{N}
ATTN_MACROS = _argv_int("--attention-die-macros")           # item 2.2: only the attention die assumed larger; suffix _attn{N}
os.environ["CIMSIM_FABRIC"] = _fabric_for(DIE_MACROS or ATTN_MACROS)


def measure(name, S, phases=("prefill", "decode"), hist="opt_2p7b"):
    import scripts.crossbar_comm as cc
    from scripts import fabric as fabric_mod
    from scripts import llm_workload as lw
    from scripts import mlx_system as mlx
    from scripts import placement as pm
    from scripts import v4_models as vm
    from scripts.run_2p7b_block import REF_WC, with_macro_bw
    os.makedirs(OUT, exist_ok=True)
    suffix = f"_m{DIE_MACROS}" if DIE_MACROS else (f"_attn{ATTN_MACROS}" if ATTN_MACROS else "")
    if TILING:
        from scripts import v3_sweep as v3s
        suffix += f"_tl{TILING}"; tiling_dims = v3s.TILINGS[TILING]
    path = os.path.join(OUT, f"{name}_S{S}{suffix}.json")
    out = json.load(open(path)) if os.path.exists(path) else None
    cfg = vm.cfg_of(name)
    m = vm.MODELS[name]
    static_src = None
    if ATTN_MACROS:      # static operators from the standard-die account at the largest measured S, scaled exactly with P
        cands = sorted(int(f.split("_S")[1].split(".")[0]) for f in os.listdir(OUT) if f.startswith(f"{name}_S") and f.endswith(".json") and "_m" not in f and "_attn" not in f)
        if not cands:
            raise SystemExit(f"no standard-die account for {name} to derive the static operators from")
        static_src = {}
        for ph in ("prefill", "decode"):
            ok = [s for s in cands if json.load(open(os.path.join(OUT, f"{name}_S{s}.json"))).get("phases", {}).get(ph)]
            if ok:
                static_src[ph] = (max(ok), json.load(open(os.path.join(OUT, f"{name}_S{max(ok)}.json"))))
    fab = mlx.FABRIC
    fab_bw = with_macro_bw(fab, REF_WC)
    pl, pl_bw = pm.sequential_fill(fab), pm.sequential_fill(fab_bw)
    if out is None:
        out = {"config": {"d_model": cfg.d_model, "n_heads": cfg.n_heads, "d_ff": cfg.d_ff, "n_layers": cfg.n_layers, "S": S, "name": cfg.name,
                          "vocab": cfg.vocab, **cfg.extra_fields()},
               "model": name, "model_revision": m["sources"], "max_positions": m["max_positions"],
               "ref_words_per_cycle": REF_WC, "phases": {}, "hist_source": hist,
               "derivation": "measured: one mapper run per operator at this (model, S); block-level, depth-independent",
               "scope": "transformer block; embedding / LM head / final norm / positions outside"}
        if DIE_MACROS:
            out["die_capacity"] = {"macros": DIE_MACROS, "factor": DIE_MACROS / BASE_MACROS, "cells": DIE_MACROS * 32 * 256 * 256, "fabric": os.environ["CIMSIM_FABRIC"],
                                   "declared": "capacity variant: every operator measured and tiled on this die"}
            out["derivation"] = f"measured on the {DIE_MACROS}-macro die ({DIE_MACROS / BASE_MACROS:g} x the base capacity): one mapper run per operator"
        if TILING:
            out["tiling"] = {"name": TILING, "dims": {k: list(v) for k, v in (tiling_dims.items() if isinstance(tiling_dims, dict) else {"*": tiling_dims}.items())},
                             "declared": "split preference per operator passed to the tiler and the mapper (spatial_dims); a row split produces partial sums reduced at the consumer"}
        if ATTN_MACROS:
            out["attention_die_capacity"] = {"macros": ATTN_MACROS, "factor": ATTN_MACROS / BASE_MACROS, "cells": ATTN_MACROS * 32 * 256 * 256, "fabric": os.environ["CIMSIM_FABRIC"],
                                             "declared": "ASSUMED: the standard die cannot hold K and V at this length; the attention die is taken to be this large, the static operators stay on the standard die"}
            out["derivation"] = (f"attention operators measured on the {ATTN_MACROS}-macro die (assumed capacity); static operators derived exactly from the measured "
                                 f"standard-die account at the largest S measured for the phase (compute, energy, on-die serialization and die flows scale with P; write 0)")
    for phase in phases:
        if out["phases"].get(phase):
            print("exists", name, S, phase); continue
        recs = []
        for op in lw.block_ops(cfg, S=S, phase=phase):
            pol = "spatial_multi_die" if op.kind == "static" else "reject"
            if ATTN_MACROS and op.kind == "static":
                S_ref, src = static_src[phase]
                r0 = [x for x in src["phases"][phase] if x["name"] == op.name][0]
                k = (S / S_ref) if phase == "prefill" else 1.0
                recs.append({**r0, "P": op.P, "compute_s": r0["compute_s"] * k, "energy_J": r0["energy_J"] * k, "write_s": 0.0,
                             "ondie_serial_ref_s": (r0["ondie_serial_ref_s"] * k if r0.get("ondie_serial_ref_s") else None),
                             "die_flow_words": [v * k for v in r0["die_flow_words"]], "die_flow_down": [v * k for v in r0["die_flow_down"]], "die_flow_up": [v * k for v in r0["die_flow_up"]],
                             "derived_from": f"{name}_S{S_ref}.json x {k:g}"})
                print(f"[{name} {phase} S={S}] {op.name}: static, derived from S {S_ref} x {k:g}", flush=True)
                continue
            if op.kind == "dynamic" and lw.op_weight_cells(op) > lw.DIE_WEIGHT_CELLS:
                out["phases"][phase] = None
                out.setdefault("infeasible", {})[phase] = f"{op.name} needs {lw.op_weight_cells(op)} cells > one die ({lw.DIE_WEIGHT_CELLS})"
                print(out["infeasible"][phase], flush=True)
                break
            print(f"[{name} {phase} S={S}] {op.name} P={op.P} C={op.C} M={op.M} N={op.N}", flush=True)
            sd = lw.dims_for(tiling_dims, op.name) if TILING else ("M", "C")
            r = lw.run_op(op, phase=phase, overcapacity=pol, save_comm=False, hist_source=hist, strict_traffic=False, spatial_dims=sd,
                          spatial_max_dies=10 ** 6)     # the tiler's search is unbounded, as in the deployments (a small die may need > 24 dies per operator)
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
                         "P": op.P, "C": op.C, "M": op.M, "N": op.N, "out_M": op.out_M, "resident_N": op.resident_N,
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
    args = [a for a in sys.argv[1:]]
    phases = ("prefill", "decode")
    if "--phases" in args:
        i = args.index("--phases"); phases = tuple(args[i + 1].split(",")); del args[i:i + 2]
    name, lengths = args[0], [int(x) for x in args[1:]]
    for S in lengths:
        measure(name, S, phases)


if __name__ == "__main__":
    main()
