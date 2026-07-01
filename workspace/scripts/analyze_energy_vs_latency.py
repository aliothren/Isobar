"""
Energy-view vs Latency-view of one transformer block on the MLX die hierarchy.

The point: CiMLoop scores attention by ENERGY, which understates it. Once the
ReRAM write (SET pulse) LATENCY is modeled, attention's share of the critical
path jumps -- so "should we offload attention?" looks very different through the
two lenses. This draws a normalized stacked bar (static / attention-compute /
attention-write) for ENERGY vs LATENCY, in both prefill and decode.

Usage (inside the container):
    python3 scripts/analyze_energy_vs_latency.py
Writes analysis/energy_vs_latency.png.
"""
import sys, os
sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import llm_workload as lw

OUT = "/home/workspace/analysis"
os.makedirs(OUT, exist_ok=True)
cfg = lw.GptConfig()
S = 512


def breakdown(results):
    """Return energy and latency split into (static, attn_compute, attn_write)."""
    def E(kind, key):
        return sum(r[key] for r in results if r["op"].kind == kind)
    energy = (
        E("static", "total_J"),                               # static
        sum(r["compute_J"] for r in results if r["op"].kind == "dynamic"),  # attn compute
        sum(r["write_J"] for r in results if r["op"].kind == "dynamic"),    # attn write
    )
    latency = (
        E("static", "total_latency_s"),
        sum(r["compute_latency_s"] + r["dist_latency_s"]
            for r in results if r["op"].kind == "dynamic"),
        sum(r["write_latency_s"] for r in results if r["op"].kind == "dynamic"),
    )
    return energy, latency


phases = ["prefill", "decode"]
data = {}
for ph in phases:
    print(f"running {ph} block (S={S})...", flush=True)
    res = lw.run_block(cfg, S=S, phase=ph, verbose=False)
    data[ph] = breakdown(res)

# ----------------------------------------------------------------- plot
LABELS = ["static (FFN/proj)", "attention compute", "attention WRITE (ReRAM SET)"]
COLORS = ["tab:blue", "tab:orange", "tab:red"]
fig, axes = plt.subplots(1, 2, figsize=(12, 5.5), sharey=True)

for ax, ph in zip(axes, phases):
    energy, latency = data[ph]
    cols = {"ENERGY": energy, "LATENCY": latency}
    x = list(range(len(cols)))
    for xi, (name, comp) in zip(x, cols.items()):
        tot = sum(comp) or 1.0
        bottom = 0.0
        for val, c, lbl in zip(comp, COLORS, LABELS):
            frac = 100 * val / tot
            ax.bar(xi, frac, bottom=bottom, color=c,
                   label=lbl if (xi == 0 and ph == "prefill") else None)
            if frac > 4:
                ax.text(xi, bottom + frac / 2, f"{frac:.0f}%",
                        ha="center", va="center", fontsize=9, color="white")
            bottom += frac
        attn = 100 * (comp[1] + comp[2]) / tot
        ax.text(xi, 102, f"attn {attn:.0f}%", ha="center", fontsize=10,
                fontweight="bold")
    ax.set_xticks(x); ax.set_xticklabels(list(cols.keys()))
    ax.set_title(f"{ph}  (S={S})")
    ax.set_ylim(0, 112)
    if ph == "prefill":
        ax.set_ylabel("share of one transformer block (%)")

fig.suptitle("Energy view vs Latency view of a transformer block on ReRAM CIM\n"
             "(attention -- especially the ReRAM WRITE -- is far larger on the "
             "critical path than in energy)", fontsize=12)
handles, labels = axes[0].get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False)
plt.tight_layout(rect=[0, 0.06, 1, 1])
p = os.path.join(OUT, "energy_vs_latency.png")
plt.savefig(p, dpi=120); plt.close()
print(f"PNG -> {p}")
for ph in phases:
    e, l = data[ph]
    print(f"{ph}: energy attn={100*(e[1]+e[2])/sum(e):.1f}%  "
          f"latency attn={100*(l[1]+l[2])/sum(l):.1f}%  "
          f"(write {100*l[2]/sum(l):.0f}% of latency)")
