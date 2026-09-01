"""O17c: the mapper-measured V(d, S) -- the scaling-law probes.

Runs the block's matmul operators through the real mapper at d in {1024,
2560, 4096, 5120, 6144, 8192} (S = 512) and S in {128, 256, 512, 1024,
2048} (d = 1024), and records, per (d, S, op): the busiest on-die wire's
volume and DIRECTION (down = input, up = partial sums), the serialization
at the 16,384 w/c reference, the compute, and the die split. These are the
INDEPENDENT validation points of the phase diagram (O29): the boundary
lines are closed-form from the 355M V, the coloured points come from here.

Grid design:
  - d = 5120 and 6144 pin the V-shape's valley: the busiest wire is the
    partial-sum UP traffic (~ S x M_share x 2, M_share = die capacity / d
    under the column split) until the input side (~ S x d) takes over; on
    ideal capacity the crossing is d* = 1024 x sqrt(32) ~ 5,793, and the
    four round tiers {1024, 2560, 4096, 8192} straddle it without pinning
    it. d* is a paper number; two runs buy it.
  - The S sweep stays small (3 ops): it only VALIDATES S-independence --
    the projections' ratio cancels S exactly, the attention ops follow S
    (recorded, but excepted from the d law).

Regime: the residency tiler, COLUMN SPLIT ONLY (`spatial_dims=("M",)`;
each die receives the full input S x d). The row split is the O15 branch
and stays unexercised. dh = 64 fixed (n_heads = d / 64); d_ff = 4d;
prefill; hist source = the borrowed gpt2_medium set (values move energy
only, not traffic or latency). Fabric: the 48-die package (d = 8192 needs
32 dies). One mapper at a time; ~48 runs, resumable: finished (d, S, op)
entries in the JSON are skipped on restart.

Usage (container): python3 scripts/run_scaling_probes.py [--plan]
Output: analysis/scaling_probes.json (figures: analyze_scaling_law.py)
"""
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
os.environ.setdefault("CIMSIM_FABRIC",
                      "/home/workspace/models/fabric/mlx300_multidie48.yaml")

import scripts.crossbar_comm as cc
from scripts import fabric as fabric_mod
from scripts import llm_workload as lw
from scripts import mlx_system as mlx
from scripts import placement as pm

OUT = "/home/workspace/analysis"
OUT_JSON = os.path.join(OUT, "scaling_probes.json")
REF_WC = 16384.0
DH = 64                                       # head dim fixed across the family
D_GRID = [1024, 2560, 4096, 5120, 6144, 8192]
S_GRID = [128, 256, 512, 1024, 2048]          # d = 1024; K/V ceiling ~2.5k (O21)
S_OPS = ("qkv_proj", "ffn2", "qk^t")          # strict cancel / knee op / the S exception
MATMUL = ("qkv_proj", "qk^t", "av", "out_proj", "ffn1", "ffn2")


def cfg_of(d):
    return lw.GptConfig(d_model=d, n_heads=d // DH, d_ff=4 * d, n_layers=24,
                        name=f"probe-d{d}")


def points():
    """The run matrix: (d, S, [op names])."""
    pts = [(d, 512, list(MATMUL)) for d in D_GRID]
    pts += [(1024, S, list(S_OPS)) for S in S_GRID if S != 512]
    return pts


def run_one(op, fab, fab_bw, pl, pl_bw, max_dies):
    pol = "spatial_multi_die" if op.kind == "static" else "reject"
    plan = (lw.plan_spatial(op, max_dies=max_dies, dims=("M",))
            if op.kind == "static" else None)
    r = lw.run_op(op, phase="prefill", overcapacity=pol, save_comm=False,
                  spatial_dims=("M",), spatial_max_dies=max_dies)
    res = r["result"]
    flows, _, _, _ = cc.build_flows(res.output_dir, verbose=False,
                                    fabric=fab, placement=pl)
    occ = cc.link_occupancy(flows, fab_bw, res.cycle_seconds, pl_bw)
    bo = occ["bottleneck"] or {}
    edges = [{"node": f.get("node"), "down": f.get("down", f["volume"]),
              "up": f.get("up", 0.0), "volume": f["volume"]}
             for f in flows if f["level_name"] == "macro" and f["volume"] > 0]
    n_dies, split, piece_c, piece_m = 1, None, op.C, op.M
    if plan is not None:
        n_dies, split, _ = plan
        piece_c = op.C // n_dies if split == "C" else op.C
        piece_m = op.M // n_dies if split == "M" else op.M
    return {
        "name": op.name, "kind": op.kind, "policy": pol,
        "P": op.P, "C": op.C, "M": op.M, "N": op.N,
        "dies": n_dies, "split": split, "piece_C": piece_c, "piece_M": piece_m,
        "compute_s": r["compute_latency_s"], "write_s": r["write_latency_s"],
        "cycle_s": res.cycle_seconds,
        "ondie_serial_ref_s": occ["serialization_s"],
        "serial_over_compute": (occ["serialization_s"] / r["compute_latency_s"]
                                if r["compute_latency_s"] > 0 else None),
        "bottleneck": {"resource": bo.get("resource"),
                       "direction": bo.get("direction"),
                       "volume": bo.get("volume"),
                       "seconds": bo.get("seconds")},
        "macro_edges": edges,
    }


def main():
    plan_only = "--plan" in sys.argv
    fab = mlx.FABRIC
    max_dies = fab.level("die").per_parent
    done = {}
    if os.path.exists(OUT_JSON) and not plan_only:
        old = json.load(open(OUT_JSON))
        done = {(p["d"], p["S"]): p for p in old.get("points", [])}
        if done:
            print(f"resuming: {sum(len(p['ops']) for p in done.values())} "
                  f"finished op runs found in {OUT_JSON}", flush=True)
    out = {"ref_words_per_cycle": REF_WC, "dh": DH,
           "regime": "residency tiler, column split only (O15 row split excluded); "
                     "prefill; full die per op (no co-residency share)",
           "d_grid": D_GRID, "s_grid": S_GRID, "s_ops": list(S_OPS),
           "fabric": fabric_mod.provenance(fab), "points": []}
    total = sum(len(ops) for _, _, ops in points())
    print(f"scaling probes: {total} mapper runs "
          f"({'plan only' if plan_only else 'sequential, one mapper at a time'})",
          flush=True)
    n_run = 0
    fab_bw = pl = pl_bw = None
    if not plan_only:
        import dataclasses
        fab_bw = dataclasses.replace(fab, levels=[
            dataclasses.replace(l, link=dataclasses.replace(
                l.link, bandwidth_words_per_cycle=REF_WC))
            if l.name == "macro" else l for l in fab.levels]).validate()
        pl = pm.sequential_fill(fab)
        pl_bw = pm.sequential_fill(fab_bw)
    for d, S, op_names in points():
        cfg = cfg_of(d)
        ops = {o.name: o for o in lw.block_ops(cfg, S=S, phase="prefill")}
        prev = done.get((d, S), {"d": d, "S": S, "n_heads": cfg.n_heads,
                                 "ops": []})
        have = {o["name"] for o in prev["ops"]}
        for name in op_names:
            op = ops[name]
            n_run += 1
            if name in have:
                print(f"[{n_run}/{total}] d={d} S={S} {name}: already done, skip",
                      flush=True)
                continue
            tag = (f"[{n_run}/{total}] d={d} S={S} {name} ({op.kind}) "
                   f"P={op.P} C={op.C} M={op.M} N={op.N}")
            if op.kind == "static":
                n, dim, _ = lw.plan_spatial(op, max_dies=max_dies, dims=("M",))
                tag += f" -> {n} die(s), split={dim}"
            print(tag, flush=True)
            if plan_only:
                continue
            rec = run_one(op, fab, fab_bw, pl, pl_bw, max_dies)
            prev["ops"].append(rec)
            print(f"    compute {rec['compute_s']*1e3:8.3f} ms | serial@ref "
                  f"{rec['ondie_serial_ref_s']*1e3:8.4f} ms | ratio "
                  f"{rec['serial_over_compute']:.4f} | busiest "
                  f"{rec['bottleneck']['direction']} "
                  f"{(rec['bottleneck']['volume'] or 0)/1e6:.2f} Mw", flush=True)
            done[(d, S)] = prev
            out["points"] = [done[k] for k in sorted(done)]
            with open(OUT_JSON, "w") as f:      # crash-safe: rewrite per run
                json.dump(out, f, indent=1)
    if not plan_only:
        print(f"JSON -> {OUT_JSON}")


if __name__ == "__main__":
    main()
