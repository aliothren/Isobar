"""Data-locality analysis for the die floorplan.

Locates each matmul's region on the die and scores how far activations travel between
producer->consumer regions using **nearest-neighbour (NN) distance** (min Manhattan
hop between any core of the producer and any core of the consumer). Compares the
size-order floorplan against a dataflow-order floorplan and (if matplotlib is present)
saves plots.

Coordinate model: the die is a 2-D grid of cores, x = macro (0..MACROS-1),
y = core (0..CORES_PER_MACRO-1). NN distance = min |dx| + |dy| over region cell pairs
(0 = adjacent/same cell, larger = farther apart).

The floorplan is DETERMINISTIC — same matmuls give the same placement every run.
"""
import os
from math import inf

from die_floorplan import floorplan, place_blocks, MACROS, CORES_PER_MACRO

H, I, HEADS, HD, S = 768, 3072, 12, 64, 128

# name -> (M, C, G, stationary)
BLOCK = {
    "qkv_proj":      (3 * H, H, 1, True),
    "attn_out_proj": (H, H, 1, True),
    "ffn1":          (I, H, 1, True),
    "ffn2":          (H, I, 1, True),
    "qk":            (S, HD, HEADS, False),
    "av":            (HD, S, HEADS, False),
}

# dataflow producer -> consumer with activation volume (bytes, 8-bit activations)
DATAFLOW = [
    ("qkv_proj", "qk", 2 * H * S),          # Q, K
    ("qkv_proj", "av", H * S),              # V
    ("qk", "av", S * S * HEADS),            # attention scores
    ("av", "attn_out_proj", HD * S * HEADS),# head outputs
    ("attn_out_proj", "ffn1", H * S),       # hidden
    ("ffn1", "ffn2", I * S),                # intermediate
]

# two orderings to compare
SIZE_ORDER = ["ffn1", "ffn2", "qkv_proj", "attn_out_proj", "qk", "av"]
DATAFLOW_ORDER = ["qkv_proj", "qk", "av", "attn_out_proj", "ffn1", "ffn2"]


def region_cells(order):
    """Run the floorplan for a given matmul order -> {matmul: set((macro, core))}."""
    matmuls = {n: BLOCK[n] for n in order}
    fps, regions, meta = floorplan(matmuls)
    placements = place_blocks(fps, regions)
    cells = {}
    for p in placements:
        cells.setdefault(p.matmul, set()).add((p.macro, p.core))
    return cells


def nn_distance(a, b):
    """Nearest-neighbour Manhattan distance between two regions' cell sets."""
    return min(abs(ma - mb) + abs(ca - cb) for (ma, ca) in a for (mb, cb) in b)


def locality_report(cells):
    """Per-edge NN distance, volume, cost; plus totals."""
    rows, total_cost, total_hops = [], 0, 0
    for prod, cons, vol in DATAFLOW:
        d = nn_distance(cells[prod], cells[cons])
        cost = d * vol
        rows.append((prod, cons, d, vol, cost))
        total_cost += cost
        total_hops += d
    return rows, total_cost, total_hops


def print_report(name, cells):
    rows, total_cost, total_hops = locality_report(cells)
    print(f"\n===== {name} =====")
    print(f"{'edge':28}{'NN dist':>9}{'act bytes':>12}{'cost (d×B)':>14}")
    print("-" * 63)
    for prod, cons, d, vol, cost in rows:
        print(f"{prod+'→'+cons:28}{d:>9}{vol:>12,}{cost:>14,}")
    print("-" * 63)
    print(f"{'TOTAL':28}{total_hops:>9}{'':>12}{total_cost:>14,}")
    return total_cost


def plot(cells_size, cells_df, out_dir):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Patch
    except Exception as e:
        print(f"\n[plots skipped: matplotlib unavailable — {e}]")
        return None

    os.makedirs(out_dir, exist_ok=True)
    names = list(BLOCK)
    cmap = plt.get_cmap("tab10")
    color = {n: cmap(i) for i, n in enumerate(names)}

    def draw_grid(ax, cells, title):
        owner = {cell: n for n, cs in cells.items() for cell in cs}
        for m in range(MACROS):
            for c in range(CORES_PER_MACRO):
                n = owner.get((m, c))
                ax.add_patch(plt.Rectangle((m, c), 1, 1,
                             facecolor=color[n] if n else "white",
                             edgecolor="0.7"))
        ax.set_xlim(0, MACROS); ax.set_ylim(0, CORES_PER_MACRO)
        ax.set_xticks(range(MACROS)); ax.set_yticks(range(CORES_PER_MACRO))
        ax.set_xlabel("macro"); ax.set_ylabel("core"); ax.set_title(title)
        ax.set_aspect("equal"); ax.invert_yaxis()

    # 1) side-by-side die maps
    fig, axes = plt.subplots(2, 1, figsize=(9, 6))
    draw_grid(axes[0], cells_size, "Size-order floorplan")
    draw_grid(axes[1], cells_df, "Dataflow-order floorplan")
    fig.legend(handles=[Patch(color=color[n], label=n) for n in names],
               loc="center right", fontsize=8)
    fig.tight_layout(rect=[0, 0, 0.82, 1])
    p1 = os.path.join(out_dir, "die_floorplan_maps.png")
    fig.savefig(p1, dpi=130); plt.close(fig)

    # 2) per-edge NN distance comparison
    rows_s, cost_s, _ = locality_report(cells_size)
    rows_d, cost_d, _ = locality_report(cells_df)
    labels = [f"{p}→{c}" for p, c, *_ in rows_s]
    import numpy as np
    x = np.arange(len(labels)); w = 0.38
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(x - w/2, [r[2] for r in rows_s], w, label=f"size-order (Σcost={cost_s:,})")
    ax.bar(x + w/2, [r[2] for r in rows_d], w, label=f"dataflow-order (Σcost={cost_d:,})")
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("NN distance (hops)"); ax.set_title("Producer→consumer locality")
    ax.legend(fontsize=8); fig.tight_layout()
    p2 = os.path.join(out_dir, "die_locality_edges.png")
    fig.savefig(p2, dpi=130); plt.close(fig)
    return p1, p2


if __name__ == "__main__":
    cells_size = region_cells(SIZE_ORDER)
    cells_df = region_cells(DATAFLOW_ORDER)

    # locate regions
    print("Region locations (macro range, #cores) — dataflow-order floorplan:")
    for n in DATAFLOW_ORDER:
        cs = cells_df[n]
        macros = sorted({m for m, c in cs})
        print(f"  {n:16} macros {macros[0]}–{macros[-1]}, {len(cs)} cores")

    c_size = print_report("SIZE-order floorplan (current)", cells_size)
    c_df = print_report("DATAFLOW-order floorplan", cells_df)
    print(f"\nLocality cost: size-order {c_size:,}  vs  dataflow-order {c_df:,}  "
          f"→ {100*(c_size-c_df)/c_size:.0f}% reduction")

    out = os.path.join(os.path.dirname(__file__), "..", "outputs", "encoder_block_floorplan")
    paths = plot(cells_size, cells_df, out)
    if paths:
        print("\nSaved plots:")
        for p in paths:
            print("  " + os.path.abspath(p))
