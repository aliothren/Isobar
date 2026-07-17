"""
Real-DNN case study: compare communication cost across PLACEMENTS x PATTERNS.

IMPORTANT (honest framing): CiMLoop's interconnect (router) cost is
`volume x fixed_per_word_energy` with NO distance term -- it is position-blind.
The overlay scales it by `hops / reference_hops`. We do NOT know what the router
energy was calibrated to, so the ABSOLUTE multipliers are NOT real values
(reference_hops is an explicit, unconfirmed assumption). What IS robust is the
RELATIVE comparison between placements/patterns, so this script focuses on that
(everything normalized to a reference setting).

Two phases, decoupled so re-analysis is free:
  1. RUN+PERCEIVE (expensive, once): run the DNN layer-by-layer (sequential,
     1 core) and cache each layer's perceived interconnect data to JSON.
  2. ANALYZE (cheap, many times): load the cache and evaluate any grid of
     (placement, pattern, reference_hops) settings -- no mapper re-run.

Usage:
    python3 scripts/analyze_position_aware.py [dnn_name] [n_layers]
"""
import sys, os, json
sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import mlx_system as mlx
from scripts import placement_aware as pa

DNN = sys.argv[1] if len(sys.argv) > 1 else "resnet18"
N_LAYERS = int(sys.argv[2]) if len(sys.argv) > 2 else None
OUT = "/home/workspace/analysis"
os.makedirs(OUT, exist_ok=True)
CACHE = os.path.join(OUT, f"{DNN}_levels.json")

# Settings to sweep.
PLACEMENTS = {"grid": pa.place_grid, "linear": pa.place_linear}
PATTERNS = ["neighbor", "tree", "to_center", "all_to_all"]
REFERENCE_HOPS = 1.0   # explicit assumption: baseline per-word energy == 1 hop
REF_SETTING = ("grid", "to_center")  # normalize everything to this layout

def _cache_is_current(entries) -> bool:
    """A cache written by an older perceive() lacks `energy_J`, which would silently
    zero every base and make the whole sweep 0 (then divide-by-zero on the ref).
    Re-run rather than trust it."""
    return all("energy_J" in lv
               for e in entries for lv in e.get("levels", {}).values())


# ----------------------------------------------------- phase 1: run + cache
cached = None
if os.path.exists(CACHE):
    with open(CACHE) as f:
        cached = json.load(f)
    if _cache_is_current(cached):
        print(f"Loading cached perceived levels: {CACHE}")
    else:
        print(f"Cache {CACHE} predates the energy_J fix -- discarding and re-running.")
        cached = None
if cached is None:
    layers = mlx.list_layers(DNN)
    if N_LAYERS:
        layers = layers[:N_LAYERS]
    print(f"Running {DNN}: {len(layers)} layers (sequential, 1 core)\n")
    cached = []
    for i, lp in enumerate(layers):
        print(f"[{i+1}/{len(layers)}] {os.path.basename(lp)}", flush=True)
        res = mlx.run_mlx_layer(lp)
        cached.append({
            "layer": os.path.basename(lp),
            "total": res["result"].energy,
            "levels": res["levels"],
        })
    with open(CACHE, "w") as f:
        json.dump(cached, f)
    print(f"\nCached -> {CACHE}")

# ----------------------------------------------------- phase 2: analyze
def comm_energy(levels, place_fn, pattern):
    """Total position-aware communication energy for one layer under a setting."""
    layout = {n: {"pattern": pattern, "reference_hops": REFERENCE_HOPS}
              for n in levels}
    return pa.position_aware_cost(levels, layout, place_fn)["position_aware"]

# sum over layers for each (placement, pattern)
grid_energy = {}  # (placement, pattern) -> whole-DNN comm energy
for pname, pfn in PLACEMENTS.items():
    for pat in PATTERNS:
        grid_energy[(pname, pat)] = sum(
            comm_energy(L["levels"], pfn, pat) for L in cached)

ref = grid_energy[REF_SETTING]

print("\n========= whole-DNN communication cost (RELATIVE, reference = "
      f"{REF_SETTING[0]}+{REF_SETTING[1]} = 1.00) =========")
print("(absolute J shown too, but NOT a true value -- depends on reference_hops)\n")
print(f"{'placement':<10}{'pattern':<12}{'comm energy (J)':>18}{'relative':>12}")
for pname in PLACEMENTS:
    for pat in PATTERNS:
        e = grid_energy[(pname, pat)]
        print(f"{pname:<10}{pat:<12}{e:>18.3e}{e/ref:>11.2f}x")

# ----------------------------------------------------- CSV
import csv
with open(os.path.join(OUT, f"{DNN}_settings_compare.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["placement", "pattern", "comm_energy_J", "relative_to_ref"])
    for pname in PLACEMENTS:
        for pat in PATTERNS:
            e = grid_energy[(pname, pat)]
            w.writerow([pname, pat, e, e / ref])

# ----------------------------------------------------- chart: matrix of settings
import numpy as np
fig, ax = plt.subplots(figsize=(9, 5))
width = 0.8 / len(PLACEMENTS)
xs = np.arange(len(PATTERNS))
for k, pname in enumerate(PLACEMENTS):
    vals = [grid_energy[(pname, pat)] / ref for pat in PATTERNS]
    ax.bar(xs + k * width, vals, width, label=f"placement: {pname}")
ax.axhline(1.0, color="gray", ls="--", lw=1, label=f"reference ({REF_SETTING[0]}+{REF_SETTING[1]})")
ax.set_xticks(xs + width * (len(PLACEMENTS) - 1) / 2)
ax.set_xticklabels(PATTERNS)
ax.set_ylabel(f"Whole-DNN comm energy\n(relative to {REF_SETTING[0]}+{REF_SETTING[1]})")
ax.set_xlabel("communication pattern")
ax.set_title(f"{DNN}: relative communication cost across placements x patterns\n"
             "(relative comparison is robust; absolute value depends on reference_hops)")
ax.legend()
plt.tight_layout()
p = os.path.join(OUT, f"{DNN}_settings_compare.png")
plt.savefig(p, dpi=120); plt.close()
print(f"\nCSV  -> {OUT}/{DNN}_settings_compare.csv")
print(f"PNG  -> {p}")
print("\nDone.")
