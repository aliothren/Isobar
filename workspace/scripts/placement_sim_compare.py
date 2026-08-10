"""Simulated energy / I/O comparison of two crossbar placements (baseline vs optimized).

Timeloop's mapper does not model physical placement, so each die_solver.py placement is
encoded as its *average router hops per reduction merge* (from the solver's lambda-1
counts: intra-macro merge = 1 hop, cross-macro merge = 4 hops) and fed to the sim via
the distance_router's HOP_DISTANCE variable. The sim then re-measures energy and
main-memory I/O per matmul under each placement.

Caveat: HOP_DISTANCE scales ALL router traffic (inputs/weights/outputs alike), while
the hop averages are derived from partial-sum reduction merges only. It captures the
dominant hop-distance effect, not the (small) merge-count difference between placements.

Run inside the CiMLoop container:
    docker exec cimloop-tutorial-1 bash -lc \
        'cd /home/workspace/scripts && python3 placement_sim_compare.py'
"""
import os
import re

import pandas as pd
import pytimeloop.timeloopfe.v4 as tl
from utils import get_spec, get_run_dir

import die_solver as ds

pd.set_option("display.width", 200)

HIDDEN, INTER, SEQ = 768, 3072, 128

# accelerator matmuls only (qk/av attention -> CPU). (M, C, P, G)
SHAPES = {
    "ffn1":          dict(M=INTER, C=HIDDEN, P=SEQ, G=1),
    "ffn2":          dict(M=HIDDEN, C=INTER, P=SEQ, G=1),
    "qkv_proj":      dict(M=3 * HIDDEN, C=HIDDEN, P=SEQ, G=1),
    "attn_out_proj": dict(M=HIDDEN, C=HIDDEN, P=SEQ, G=1),
}

# Average hops per reduction merge, DERIVED from the die_solver placements rather
# than transcribed -- change the placer and these follow automatically.
#   avg = (intra_macro_merges * 1 + cross_macro_merges * 4) / total_merges
# On mlx300 today that is baseline ffn1 (4+2*4)/6=2.0, ffn2 (5+1*4)/6=1.5,
# qkv (3+1*4)/4=1.75, attn_out 2/2=1.0; optimized has no cross-macro merge -> 1.0.
HOPS = {
    "baseline":  ds.avg_hops_per_merge(ds.baseline_place(ds.ORDER)),
    "optimized": ds.avg_hops_per_merge(ds.optimizer_place(ds.ORDER)),
}

FJ_COMPONENTS = ("router", "glb", "main_memory", "Total")


def parse_stats(txt: str) -> dict:
    computes = int(re.search(r"Computes = (\d+)", txt).group(1))
    total_uj = float(re.search(r"Energy: ([\d.e+-]+) uJ", txt).group(1))
    fj_block = txt.split("fJ/Compute", 1)[1]
    out = dict(computes=computes, total_uJ=total_uj)
    for name in FJ_COMPONENTS:
        m = re.search(rf"^\s+{name}\s+= ([\d.e+-]+)\s*$", fj_block, re.M)
        out[f"{name}_uJ"] = float(m.group(1)) * computes / 1e9 if m else float("nan")
    # I/O: main_memory scalar accesses (word bits = 1, so accesses == bits)
    for comp in ("main_memory", "glb", "router"):
        m = re.search(rf"=== {comp} ===\s*\n\s*Total scalar accesses\s*:\s*(\d+)", txt)
        out[f"{comp}_access_bits"] = int(m.group(1)) if m else 0
    return out


def run(name: str, cfg: dict, hop_distance: float) -> dict:
    spec = get_spec(
        macro="wan_nature_2022", tile="mlx_core", chip="mlx_die",
        system="fetch_weights_hbm2_ws", dnn="msft_phi_1_5", layer="001",
    )
    spec.problem.instance.update(
        {"M": cfg["M"], "C": cfg["C"], "P": cfg["P"], "G": cfg["G"], "N": 1}
    )
    spec.variables["HOP_DISTANCE"] = hop_distance
    output_dir = get_run_dir()
    tl.call_mapper(specification=spec, output_dir=output_dir,
                   log_to=os.path.join(output_dir, "mapper.log"))
    with open(os.path.join(output_dir, "timeloop-mapper.stats.txt")) as f:
        stats = parse_stats(f.read())
    return stats


if __name__ == "__main__":
    rows = []
    for placement, hops in HOPS.items():
        for name, cfg in SHAPES.items():
            h = hops[name]
            print(f"[{placement:9}] {name:14} HOP_DISTANCE={h} ...", flush=True)
            try:
                stats = run(name, cfg, h)
            except Exception as e:
                print(f"  FAILED: {type(e).__name__}: {e}", flush=True)
                continue
            rows.append(dict(placement=placement, matmul=name, hop_distance=h, **stats))
            print(f"  total={stats['total_uJ']:,.1f} uJ  router={stats['router_uJ']:.2f} uJ  "
                  f"main_memory={stats['main_memory_access_bits']:,} bits", flush=True)

    df = pd.DataFrame(rows)
    out_csv = os.path.join(os.path.dirname(__file__), "..", "outputs",
                           "encoder_block_floorplan", "placement_sim_compare.csv")
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    df.to_csv(out_csv, index=False)

    print("\n================ SIMULATED COMPARISON ================")
    cols = ["matmul", "hop_distance", "router_uJ", "glb_uJ", "main_memory_uJ",
            "total_uJ", "main_memory_access_bits", "router_access_bits"]
    for placement in HOPS:
        sub = df[df.placement == placement]
        print(f"\n----- {placement.upper()} -----")
        print(sub[cols].to_string(index=False))
        print(f"router total: {sub.router_uJ.sum():.2f} uJ   "
              f"energy total: {sub.total_uJ.sum():,.1f} uJ   "
              f"main_memory I/O: {sub.main_memory_access_bits.sum():,} bits")

    if set(df.placement) == {"baseline", "optimized"}:
        b = df[df.placement == "baseline"].set_index("matmul")
        o = df[df.placement == "optimized"].set_index("matmul")
        print("\n----- DELTA (baseline -> optimized) -----")
        print(f"router energy : {b.router_uJ.sum():.2f} -> {o.router_uJ.sum():.2f} uJ "
              f"({100 * (b.router_uJ.sum() - o.router_uJ.sum()) / b.router_uJ.sum():.0f}% less)")
        print(f"total energy  : {b.total_uJ.sum():,.1f} -> {o.total_uJ.sum():,.1f} uJ "
              f"({100 * (b.total_uJ.sum() - o.total_uJ.sum()) / b.total_uJ.sum():.1f}% less)")
        io_same = (b.main_memory_access_bits == o.main_memory_access_bits).all()
        print(f"main-memory I/O identical across placements: {io_same} "
              f"(placement-invariant{'—as predicted' if io_same else ' EXPECTED but differs!'})")
    print(f"\nSaved -> {os.path.abspath(out_csv)}")
