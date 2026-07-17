"""
System-level run of the whole GPT-2 transformer stack on the MLX die hierarchy,
with a three-way comparison:

  (C) BASELINE   -- raw CiMLoop, all ops on chip, NO overlays
                    (what the unmodified tool reports).
  (A) FULL+OVL   -- all ops on chip WITH our overlays
                    (position-aware comm energy + distance latency + ReRAM
                     attention write energy & latency).
  (B) OFFLOAD    -- only the STATIC ops (FFN / projections) on chip, the dynamic
                    attention (QK^T, AV) offloaded; overlays applied.

For each distinct op we capture the Timeloop-searched MAPPING, the per-level
communication traffic (NoC / SRAM / DRAM), energy and latency. GPT-2's 24 blocks
are structurally identical, so we run ONE block (6 ops) and scale x n_layers
(exact for the transformer stack; embeddings / final LM head are excluded).

SCOPE / HONESTY:
  * Timeloop searches each op's mapping INDEPENDENTLY -- no cross-layer fusion /
    global schedule. "System-level mapping" = each op optimally mapped on the
    full die hierarchy, aggregated.
  * One die (256 crossbars) is modeled; weights are RESIDENT (ws_chip2chip_link,
    no weight DRAM); the multi-die package/topology is not modeled.
  * Ops within a block and blocks across the stack run serially (data dependent),
    so latency is summed; energy is summed.

Usage (inside the container):
    python3 scripts/analyze_system_gpt2.py [S] [phase]
        S      sequence length (default 512)
        phase  prefill | decode  (default prefill)
Writes analysis/gpt2_system_comparison.png and analysis/gpt2_system_mappings.txt.
"""
import sys, os
sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import llm_workload as lw
from scripts import crossbar_stats as cbs
from scripts import placement_aware as pa

S = int(sys.argv[1]) if len(sys.argv) > 1 else 512
PHASE = sys.argv[2] if len(sys.argv) > 2 else "prefill"
OUT = "/home/workspace/analysis"
os.makedirs(OUT, exist_ok=True)

cfg = lw.GptConfig()
NL = cfg.n_layers
ops = lw.block_ops(cfg, S=S, phase=PHASE)

print(f"GPT-2 ({cfg.name}, {NL} layers) system-level run on the MLX die hierarchy")
print(f"  S={S}  phase={PHASE}  | one block (6 ops) searched, scaled x{NL}\n")

records = []          # per distinct op
mapping_dump = []     # the searched mappings
CHIP2CHIP_PJ = [None] # per-word die-to-die energy, filled from the chip2chip model
for op in ops:
    print(f"  searching mapping: {op.name:<9} ({op.kind}) "
          f"P={op.P} C={op.C} M={op.M} N={op.N}", flush=True)
    r = lw.run_op(op, phase=PHASE)
    out_dir = r["output_dir"]
    # capture the searched mapping + per-level comm BEFORE the next run overwrites
    map_path = os.path.join(out_dir, "timeloop-mapper.map.txt")
    mapping = open(map_path).read() if os.path.exists(map_path) else "(no map.txt)"
    stats_path = os.path.join(out_dir, "timeloop-mapper.stats.txt")
    txt = open(stats_path).read()
    comm = {c: cbs._per_tensor_volume(txt, c)
            for c in ["router", "glb", "chip2chip_link"]}
    # per-word die-to-die energy (resident package): from the chip2chip_link model
    c2c_pJ = r["levels"].get("chip2chip_link", {}).get("unit_pJ")
    if c2c_pJ:
        CHIP2CHIP_PJ[0] = c2c_pJ

    an = r["analysis"]
    records.append({
        "op": op,
        "raw_E":  r["result"].energy,                       # CiMLoop baseline energy
        "dist_extra_E": an["position_aware"] - an["baseline"],  # overlay comm energy
        "write_E": r["write_J"],
        "raw_L":  r["compute_latency_s"],                   # CiMLoop baseline latency
        "dist_L": r["dist_latency_s"],
        "write_L": r["write_latency_s"],
        "comm": comm,
    })
    mapping_dump.append(f"{'='*70}\n{op.name}  ({op.kind})  "
                        f"P={op.P} C={op.C} M={op.M} N={op.N}\n{'='*70}\n{mapping}\n")

# ---------------------------------------------------------------- aggregate x NL
def total(records, key, kinds):
    return NL * sum(r[key] for r in records if r["op"].kind in kinds)

ALL = ("static", "dynamic")
ST = ("static",)

# die-to-die activation is NATIVE now: switching the top level to ws_chip2chip_link
# makes activations flow die-to-die through `chip2chip_link` (weights resident),
# and that energy/cycles are ALREADY in raw_E / raw_L. So we do NOT add a separate
# overlay (that would double-count); we only REPORT the logical inter-layer volume.
d2d = lw.die_to_die_activation(cfg, S, PHASE, chip2chip_pJ=CHIP2CHIP_PJ[0])

scen = {
    # energy (J)
    "C_E": total(records, "raw_E", ALL),
    "A_E": total(records, "raw_E", ALL) + total(records, "dist_extra_E", ALL)
           + total(records, "write_E", ALL),
    "B_E": total(records, "raw_E", ST) + total(records, "dist_extra_E", ST),
    # latency (s)
    "C_L": total(records, "raw_L", ALL),
    "A_L": total(records, "raw_L", ALL) + total(records, "dist_L", ALL)
           + total(records, "write_L", ALL),
    "B_L": total(records, "raw_L", ST) + total(records, "dist_L", ST),
}

# ---------------------------------------------------------------- comm stats
def comm_total(comp, kinds):
    return NL * sum(r["comm"][comp] for r in records if r["op"].kind in kinds)

print("\n================ per-op detail (one block) ================")
print(f"{'op':<10}{'kind':<9}{'energy(J)':>12}{'latency(s)':>12}"
      f"{'router':>14}{'chip2chip':>14}")
for r in records:
    o = r["op"]
    print(f"{o.name:<10}{o.kind:<9}{r['raw_E']:>12.3e}{r['raw_L']:>12.3e}"
          f"{r['comm']['router']:>14,}{r['comm']['chip2chip_link']:>14,}")

print(f"\n================ MODEL TOTALS (x{NL} layers, S={S}, {PHASE}) ================")
hdr = f"{'scenario':<34}{'energy(J)':>14}{'latency(s)':>14}"
print(hdr); print("-" * len(hdr))
print(f"{'(C) baseline CiMLoop, all on chip':<34}{scen['C_E']:>14.3e}{scen['C_L']:>14.3e}")
print(f"{'(A) full + overlays, all on chip':<34}{scen['A_E']:>14.3e}{scen['A_L']:>14.3e}")
print(f"{'(B) offload attn, static-only+ovl':<34}{scen['B_E']:>14.3e}{scen['B_L']:>14.3e}")

print(f"\n  die-to-die activation (resident package, {d2d['n_dies']} dies, "
      f"1 layer/die): logical inter-layer hidden state = {d2d['words']:,} words "
      f"over {d2d['n_boundaries']} boundaries (avg {d2d['avg_die_hops']:.1f} die-hops)."
      f"\n    NATIVE via chip2chip_link (already in the energy above); not a bottleneck.")

print(f"\n-- what the overlays reveal (A vs C) --")
print(f"  energy : A/C = {scen['A_E']/scen['C_E']:.2f}x   "
      f"(+{scen['A_E']-scen['C_E']:.2e} J from write + distance)")
print(f"  latency: A/C = {scen['A_L']/scen['C_L']:.2f}x   "
      f"(+{scen['A_L']-scen['C_L']:.2e} s, ReRAM write dominates)")
print(f"-- offloading attention (B vs A) --")
print(f"  energy : B/A = {scen['B_E']/scen['A_E']:.2f}x   saves "
      f"{100*(1-scen['B_E']/scen['A_E']):.0f}%")
print(f"  latency: B/A = {scen['B_L']/scen['A_L']:.2f}x   saves "
      f"{100*(1-scen['B_L']/scen['A_L']):.0f}%")

print(f"\n================ communication statistics (model total) ================")
print(f"{'level':<30}{'all ops':>18}{'static only':>18}")
for comp, tag in [("router", "inter-macro NoC"), ("glb", "on-die SRAM"),
                  ("chip2chip_link", "die<->die (per-op)")]:
    print(f"  {comp+' ('+tag+')':<28}{comm_total(comp, ALL):>18,}"
          f"{comm_total(comp, ST):>18,}")
print(f"  {'die-to-die activation (model)':<28}{d2d['words']:>18,}"
      f"{d2d['words']:>18,}")

# ---------------------------------------------------------------- dump mappings
mp = os.path.join(OUT, f"gpt2_system_mappings_{PHASE}.txt")
with open(mp, "w") as f:
    f.write(f"GPT-2 {cfg.name} system-level searched mappings  (S={S}, {PHASE})\n"
            f"resident package: {d2d['n_dies']} dies (1 layer/die, weights resident),\n"
            f"per die: 8 macro x 4 core x 8 crossbar = 256 crossbars\n\n")
    f.write("\n".join(mapping_dump))
print(f"\nmappings -> {mp}")

# ---------------------------------------------------------------- chart
# One 1x2 row per phase; the report stacks the prefill and decode rows into a
# 2x2 grid at full text width (~0.5x shrink), so use large fonts.
plt.rcParams.update({"font.size": 15, "axes.titlesize": 16, "axes.labelsize": 15,
                     "xtick.labelsize": 14, "ytick.labelsize": 13})
fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
labels = ["(C) baseline\nCiMLoop", "(A) full\n+overlays", "(B) offload\nattn"]

# energy stacked: static_compute, attn_compute, attn_write, dist_extra
e_static_c = NL * sum(r["raw_E"] for r in records if r["op"].kind == "static")
e_attn_c   = NL * sum(r["raw_E"] for r in records if r["op"].kind == "dynamic")
e_write    = NL * sum(r["write_E"] for r in records)
e_dist_all = NL * sum(r["dist_extra_E"] for r in records)
e_dist_st  = NL * sum(r["dist_extra_E"] for r in records if r["op"].kind == "static")
E = {
    "static compute": [e_static_c, e_static_c, e_static_c],
    "attn compute":   [e_attn_c,   e_attn_c,   0],
    "attn WRITE":     [0,          e_write,    0],
    "distance comm":  [0,          e_dist_all, e_dist_st],
}
l_static_c = NL * sum(r["raw_L"] for r in records if r["op"].kind == "static")
l_attn_c   = NL * sum(r["raw_L"] for r in records if r["op"].kind == "dynamic")
l_write    = NL * sum(r["write_L"] for r in records)
l_dist_all = NL * sum(r["dist_L"] for r in records)
l_dist_st  = NL * sum(r["dist_L"] for r in records if r["op"].kind == "static")
L = {
    "static compute": [l_static_c, l_static_c, l_static_c],
    "attn compute":   [l_attn_c,   l_attn_c,   0],
    "attn WRITE":     [0,          l_write,    0],
    "distance comm":  [0,          l_dist_all, l_dist_st],
}
COLORS = ["tab:blue", "tab:orange", "tab:red", "tab:green"]
for ax, data, unit, title in [(axes[0], E, "energy (J)", "Energy"),
                              (axes[1], L, "latency (s)", "Latency")]:
    x = range(3)
    bottom = [0, 0, 0]
    for (lbl, vals), c in zip(data.items(), COLORS):
        ax.bar(x, vals, bottom=bottom, color=c, label=lbl)
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.set_xticks(list(x)); ax.set_xticklabels(labels)
    ax.set_ylabel(unit); ax.set_title(f"{title}  (whole GPT-2, S={S}, {PHASE})")
axes[1].legend(loc="upper right", fontsize=13)
fig.suptitle(f"GPT-2 system-level on ReRAM CIM die: baseline vs +overlays vs "
             f"offload  ({NL} layers, S={S}, {PHASE})", fontsize=17)
plt.tight_layout(rect=[0, 0, 1, 0.96])
p = os.path.join(OUT, f"gpt2_system_comparison_{PHASE}.png")
plt.savefig(p, dpi=120); plt.close()
print(f"chart    -> {p}")
