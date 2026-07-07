"""
2x2 comparison of per-crossbar value-dependent energy across DEVICE x WORKLOAD,
from the real per-tile pipeline (crossbar_value_real.py). Each panel shows the
per-crossbar energy on the tile grid, normalized to that panel's mean (so the
color is RELATIVE variation), with a shared color scale so panels are comparable.

Rows   = device  : wan (bit-serial, value-insensitive) vs raella (value-sensitive)
Cols   = workload: GPT-2 ffn1 (LayerNorm, homogeneous inputs) vs resnet18 conv
                   (no LN, ReLU-sparse, heterogeneous inputs)
"""
import os, json, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = "/home/workspace/analysis"
CELLS = {
    ("wan_nature_2022", "ffn1"):   f"{OUT}/tile_hists_ffn1_wan_nature_2022_energy.json",
    ("wan_nature_2022", "cnn"):    f"{OUT}/tile_hists_cnn_wan_nature_2022_energy.json",
    ("raella_isca_2023", "ffn1"):  f"{OUT}/tile_hists_ffn1_raella_isca_2023_energy.json",
    ("raella_isca_2023", "cnn"):   f"{OUT}/tile_hists_cnn_raella_isca_2023_energy.json",
}
DEV_LABEL = {"wan_nature_2022": "wan (bit-serial)",
             "raella_isca_2023": "raella (value-sensitive)"}
WL_LABEL = {"ffn1": "GPT-2 ffn1 (LayerNorm)",
            "cnn": "resnet18 conv (ReLU-sparse)"}

grids = {}
for key, path in CELLS.items():
    d = json.load(open(path))
    g = np.array(d["per_crossbar"], dtype=float).reshape(d["nr"], d["nc"])
    grids[key] = (g / g.mean(), d.get("ratio", g.max() / g.min()))

# shared color scale from the widest-spread panel
allnorm = np.concatenate([g.ravel() for g, _ in grids.values()])
vmin, vmax = allnorm.min(), allnorm.max()

fig, axes = plt.subplots(2, 2, figsize=(12, 8.5))
for i, dev in enumerate(["wan_nature_2022", "raella_isca_2023"]):
    for j, wl in enumerate(["ffn1", "cnn"]):
        ax = axes[i, j]
        g, ratio = grids[(dev, wl)]
        im = ax.imshow(g, cmap="viridis", vmin=vmin, vmax=vmax,
                       origin="lower", aspect="auto")
        ax.set_title(f"{DEV_LABEL[dev]}  x  {WL_LABEL[wl]}\n"
                     f"per-crossbar spread = {ratio:.3f}x", fontsize=10)
        ax.set_xlabel("crossbar col"); ax.set_ylabel("crossbar row")

fig.suptitle("Per-crossbar value-dependent energy (real weights + activations, per-tile "
             "re-simulation)\ncolor = energy / panel-mean; only a value-sensitive device "
             "+ heterogeneous inputs shows real spread", fontsize=12)
# reserve the right margin for panels, put the colorbar in its own axes further
# right so it never overlaps the top-right panel.
fig.subplots_adjust(top=0.86, bottom=0.08, left=0.07, right=0.86,
                    hspace=0.55, wspace=0.18)
cax = fig.add_axes([0.90, 0.12, 0.02, 0.68])
cbar = fig.colorbar(im, cax=cax)
cbar.set_label("per-crossbar energy / panel mean")
p = os.path.join(OUT, "crossbar_value_device_compare.png")
plt.savefig(p, dpi=120); plt.close()
print("saved", p)
for (dev, wl), (g, ratio) in grids.items():
    print(f"  {DEV_LABEL[dev]:<26} {WL_LABEL[wl]:<30} spread {ratio:.3f}x")
