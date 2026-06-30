"""
GPT-2 case study: CIM-friendly static compute vs offloaded dynamic attention.

Motivation: a ReRAM crossbar is weight-stationary -- great for STATIC-weight
matmuls (FFN / projections = the Conv1D/Linear ops), but attention's QK^T and AV
are activation x activation, so one operand must be RE-written into the array
every step (expensive + endurance). The natural design is to OFFLOAD attention
elsewhere and run only the static ops on the CIM crossbars.

This script runs a representative slice of GPT-2 on the MLX die hierarchy,
classifies each layer (Conv1D/Linear = static; GPT2Attention = dynamic), and
compares:
    * FULL    : everything on CIM (attention modeled as weight-stationary -- see
                CAVEAT below; this UNDER-counts attention's true ReRAM cost),
    * STATIC  : only Conv1D/Linear on CIM (attention offloaded).

CAVEAT (a known limitation of the current pipeline): the GPT2Attention layers are
generic matmuls in the workload, so CiMLoop charges them like static-weight
layers (no activation re-write penalty). So "attention on CIM" here is OPTIMISTIC;
the real ReRAM cost would be higher, making offload even more favorable.

Usage: python3 scripts/analyze_gpt2_offload.py [n_layers]
"""
import sys, os, re
sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import mlx_system as mlx
from scripts import placement_aware as pa

N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
OUT = "/home/workspace/analysis"
os.makedirs(OUT, exist_ok=True)

STATIC_NAMES = {"Conv1D", "Linear"}        # weight-stationary -> CIM-friendly
DYNAMIC_NAMES = {"GPT2Attention"}          # activation x activation -> offload


def layer_type(path):
    txt = open(path).read()
    m = re.search(r"name:\s*(\w+)", txt)
    nm = m.group(1) if m else "?"
    if nm in DYNAMIC_NAMES:
        return "dynamic", nm
    return "static", nm


# NOTE: mlx.list_layers() filters out "From einsum" layers, which for GPT-2 are
# exactly the GPT2Attention ops. We want them here, so list directly.
_dnn_dir = mlx.utl.path_from_model_dir("workloads/gpt2_medium")
layers = sorted(os.path.join(_dnn_dir, f) for f in os.listdir(_dnn_dir)
                if f.endswith(".yaml") and f != "index.yaml")[:N]
print(f"GPT-2: running first {len(layers)} layers on the MLX die hierarchy "
      "(sequential, 1 core)\n")

rows = []
for i, lp in enumerate(layers):
    kind, nm = layer_type(lp)
    print(f"[{i+1}/{len(layers)}] {os.path.basename(lp)}  ({nm}, {kind})", flush=True)
    try:
        r = mlx.run_mlx_layer(lp, config=mlx.MLX_DIE_CONFIG,
                              callfunc=mlx.mlx_die_callfunc)
        an = r["analysis"]
        rows.append({
            "layer": os.path.basename(lp), "name": nm, "kind": kind,
            "total": r["result"].energy,
            "comm_blind": an["baseline"],
            "comm_posaware": an["position_aware"],
        })
    except Exception as e:
        print(f"    SKIP ({type(e).__name__}: {e})")

# ----------------------------------------------------------- aggregate
def agg(key, kind=None):
    return sum(r[key] for r in rows if kind is None or r["kind"] == kind)

full_total = agg("total")
static_total = agg("total", "static")
dyn_total = agg("total", "dynamic")
full_comm = agg("comm_posaware")
static_comm = agg("comm_posaware", "static")
dyn_comm = agg("comm_posaware", "dynamic")
n_static = sum(1 for r in rows if r["kind"] == "static")
n_dyn = sum(1 for r in rows if r["kind"] == "dynamic")

print("\n================ GPT-2 static-vs-dynamic (sampled) ================")
print(f"layers: {n_static} static (Conv1D/Linear), {n_dyn} dynamic (Attention)\n")
print(f"{'metric':<26}{'FULL (all on CIM)':>20}{'STATIC only (offload attn)':>30}")
print(f"{'total energy (J)':<26}{full_total:>20.3e}"
      f"{static_total:>30.3e}")
print(f"{'  -> dynamic share':<26}{100*dyn_total/full_total:>19.1f}%{'':>30}")
print(f"{'comm energy, pos-aware (J)':<26}{full_comm:>20.3e}{static_comm:>30.3e}")
print(f"{'  -> dynamic share':<26}{100*dyn_comm/max(full_comm,1e-30):>19.1f}%{'':>30}")
print(f"\nOffloading attention removes {100*dyn_total/full_total:.0f}% of CIM compute "
      f"energy and {100*dyn_comm/max(full_comm,1e-30):.0f}% of CIM communication\n"
      "(both OPTIMISTIC -- attention's true ReRAM write cost is not modeled yet).")

# ----------------------------------------------------------- chart
fig, ax = plt.subplots(1, 2, figsize=(13, 5))
x = range(len(rows))
colors = ["tab:blue" if r["kind"] == "static" else "tab:red" for r in rows]
ax[0].bar(x, [r["total"] for r in rows], color=colors)
ax[0].set_xticks(x); ax[0].set_xticklabels([r["layer"].replace(".yaml", "") for r in rows], rotation=90)
ax[0].set_ylabel("total energy / layer (J)")
ax[0].set_title("per-layer energy (blue=static/CIM, red=dynamic/attention)")

ax[1].bar(["FULL\n(all on CIM)", "STATIC only\n(attn offloaded)"],
          [full_total, static_total], color=["gray", "tab:blue"])
ax[1].bar(["FULL\n(all on CIM)", "STATIC only\n(attn offloaded)"],
          [dyn_total, 0], bottom=[static_total, 0], color="tab:red", label="dynamic (attn)")
ax[1].set_ylabel("total energy (J)")
ax[1].set_title("offloading attention: what stays on CIM")
ax[1].legend()
plt.tight_layout()
p = os.path.join(OUT, "gpt2_static_vs_dynamic.png")
plt.savefig(p, dpi=120); plt.close()
print(f"PNG  -> {p}")
