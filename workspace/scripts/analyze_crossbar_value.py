"""
Demo: per-crossbar value-dependent energy MODE (uniform vs per_crossbar).

Runs one op both ways:
  uniform      -> one histogram, every crossbar identical (current behavior).
  per_crossbar -> each crossbar's value-dependent energy scaled by its own
                  distribution activity; total conserved, but a per-crossbar spread.

Prints the split (fixed floor vs value-dependent part) and the spread, and draws a
per-crossbar ENERGY heatmap on the floorplan (the value-side analogue of the
per-crossbar COMMUNICATION heatmap). NOTE: the per-crossbar activities are a
PLACEHOLDER synthetic spread until real weight tiles are available — the machinery
is what matters; swap the source for `weights` when the checkpoint is loaded.

Usage: python3 scripts/analyze_crossbar_value.py [op] [spread]
"""
import sys, os
sys.path.insert(0, "/home/workspace")
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import llm_workload as lw
from scripts import mlx_system as mlx
from scripts import crossbar_comm as cc

OP = sys.argv[1] if len(sys.argv) > 1 else "ffn1"
SPREAD = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
OUT = "/home/workspace/analysis"
os.makedirs(OUT, exist_ok=True)

cfg = lw.GptConfig()
op = {o.name: o for o in lw.block_ops(cfg, S=512, phase="prefill")}[OP]

u = lw.run_op(op, value_mode="uniform", save_comm=False)
p = lw.run_op(op, value_mode="per_crossbar", value_spread=SPREAD, save_comm=False)
cv = p["crossbar_value"]

print(f"\n==== per-crossbar value-dependent energy: {OP} (S=512, prefill) ====")
print(f"  uniform  total : {u['compute_J']:.3e} J  (every crossbar identical)")
print(f"  per_xbar total : {cv['total']:.3e} J  (conserved)")
print(f"  energy split   : floor {cv['E_floor']:.3e} J (fixed) + value "
      f"{cv['E_value']:.3e} J ({100*cv['value_frac']:.0f}% value-dependent)")
print(f"  per-crossbar   : min {cv['min']:.3e}  max {cv['max']:.3e}  "
      f"max/min {cv['ratio']:.2f}x  (synthetic spread={SPREAD}, PLACEHOLDER)")

# ---- heatmap: per-crossbar energy on the nested floorplan ----
per = np.array(cv["per_crossbar"])
xb_coord, _, _, _, (gx, gy) = cc.nested_floorplan(
    mlx.N_MACROS_PER_DIE, mlx.N_CORES_PER_MACRO, mlx.CROSSBARS_PER_CORE)
grid = np.full((gy, gx), np.nan)
for gid, (x, y) in xb_coord.items():
    if gid < len(per):
        grid[int(y), int(x)] = per[gid]

plt.figure(figsize=(10, 4))
im = plt.imshow(grid, cmap="viridis", origin="lower", aspect="auto")
plt.colorbar(im, label="per-crossbar energy (J)")
plt.title(f"{OP}: per-crossbar value-dependent energy on the floorplan\n"
          f"(mode=per_crossbar, {100*cv['value_frac']:.0f}% value part, "
          f"{cv['ratio']:.2f}x spread — synthetic placeholder distribution)")
plt.xlabel("crossbar x"); plt.ylabel("crossbar y")
plt.tight_layout()
png = os.path.join(OUT, "crossbar_value_heatmap.png")
plt.savefig(png, dpi=120); plt.close()
print(f"  heatmap -> {png}")
