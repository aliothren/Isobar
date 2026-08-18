"""Reduction-clustered placement solver for weight-stationary crossbar mapping.

Implements the formulation in ../../formulation.md: each accelerator matmul is an
independent y=Wx (attention qk/av are offloaded to CPU, so there is NO on-die
inter-matmul communication). The only on-die cost is the intra-matmul partial-sum
reduction along C, modelled with the hierarchical hypergraph connectivity (lambda-1)
metric over the die's die/macro/core hierarchy.

Two placers are compared:
  * baseline  -- naive contiguous row-major fill (splits M-blocks across core/macro
                boundaries, incurring cross-core and expensive cross-macro reductions).
  * optimizer -- reduction-clustered "M-parallel": keep each M-block's C-tiles inside
                the smallest boundary they fit in (core < macro < die), padding forward
                rather than straddling the next boundary up.

Geometry comes from the fabric config (models/fabric/*.yaml) -- NOT from constants
here -- so `CIMSIM_FABRIC=<variant>` re-runs the solver on a fabric variant, and a
multi-die fabric (die.per_parent > 1) gains a die-crossing term for free. The
crossbar's own dimensions (rows/cols) are a device property the fabric schema does
not carry yet, so they stay local.

Outputs a side-by-side (macro x core) heatmap matching the existing die floorplan figure,
plus a per-matmul cost table (cores used, cross-core / cross-macro / cross-die
reductions, energy).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from math import ceil
from typing import Dict, List, NamedTuple, Optional, Tuple

try:                        # package import: `from scripts import die_solver`
    from . import fabric as _fabric
except ImportError:         # direct run: `python3 die_solver.py`
    import fabric as _fabric


# --------------------------------------------------------------------------- #
# Die geometry -- read from the fabric config, never hardcoded
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Geometry:
    """The instance counts this solver needs, projected out of a Fabric.

    Only counts are taken. The fabric's per-level 2-D meshes are deliberately NOT
    used: the lambda-1 metric asks "how many boundaries does this reduction cross",
    not "how far apart are those slots". Making the macro term a real mesh distance
    is the next step up in fidelity (and the one that makes 3x3-vs-2x4 visible here).
    """
    name: str
    dies: int
    macros_per_die: int
    cores_per_macro: int
    xbars_per_core: int
    die_pj_per_word: Optional[float]     # None => D2D is unpriced (DR-3)

    @classmethod
    def from_fabric(cls, f) -> "Geometry":
        die = f.level("die")
        return cls(name=f.name,
                   dies=die.per_parent,
                   macros_per_die=f.level("macro").per_parent,
                   cores_per_macro=f.level("core").per_parent,
                   xbars_per_core=f.level("crossbar").per_parent,
                   die_pj_per_word=(die.link.pj_per_word if die.link else None))

    @property
    def macro_slots(self) -> int:            # crossbars in one macro
        return self.cores_per_macro * self.xbars_per_core

    @property
    def die_slots(self) -> int:              # crossbars in one die
        return self.macros_per_die * self.macro_slots

    @property
    def xbars(self) -> int:
        return self.dies * self.die_slots

    @property
    def cores(self) -> int:
        return self.dies * self.macros_per_die * self.cores_per_macro


GEOM = Geometry.from_fabric(_fabric.default())

# Crossbar logical dimensions (device property; the fabric schema has no crossbar
# geometry yet, so these stay here -- same values as io_study/die_floorplan.py).
XBAR_ROWS = 256   # R: contraction (C) capacity per crossbar
XBAR_COLS = 128   # K: output (M) capacity per crossbar (W4A8 logical)

P_TOKENS = 128    # sequence length streamed
B_OUT = 8         # output activation bits

# Router energy from the Accelergy ERT (re-simulated on mlx_die, ffn2, with the
# distance_router component): read energy = 193.017 pJ per 128-bit word at
# HOP_DISTANCE=4, i.e. 48.254 pJ/word/hop (HOP_DISTANCE=1 reproduces the original
# flat isaac_router, 48.3 pJ).
ROUTER_PJ_PER_WORD = 48.254   # per hop (ERT 193.017 pJ / 4 hops)
WORD_BITS = 128

# lambda-1 boundary weights, in router hops.
#   FLAT: original single-energy isaac_router -- every traversal costs 1 hop.
#   DISTANCE-AWARE (measured): mlx_die now uses distance_router; a cross-macro merge
#     traverses HOP_DISTANCE=4 hops (ERT-verified), an intra-macro core merge 1 hop.
W_CORE = 1.0
W_MACRO_FLAT = 1.0     # legacy flat router (HOP_DISTANCE=1)
W_MACRO_DIST = 4.0     # measured: distance_router ERT @ HOP_DISTANCE=4
# There is deliberately NO default die weight: the fabric carries
# die.link.pj_per_word = null (DR-3, unmeasured), so a die crossing has no
# defensible price yet. cost() REFUSES to score a placement that crosses a die
# unless the caller passes an explicit w_die and thereby owns the assumption.

# Accelerator matmuls only (qk/av attention -> CPU). name -> (M, C).
MATMULS: Dict[str, Tuple[int, int]] = {
    "ffn1":          (3072, 768),
    "ffn2":          (768, 3072),
    "qkv_proj":      (2304, 768),
    "attn_out_proj": (768, 768),
}

ORDER = ["ffn1", "ffn2", "qkv_proj", "attn_out_proj"]   # size-ish order


@dataclass(frozen=True)
class Tile:
    matmul: str
    mblock: int   # output-block index i  (which K-slice of M)
    ctile: int    # contraction-tile index j (which R-slice of C)


def tiles_of(name: str) -> List[Tile]:
    m_blocks, n_c = grid(name)
    return [Tile(name, i, j) for i in range(m_blocks) for j in range(n_c)]


def grid(name: str) -> Tuple[int, int]:
    M, C = MATMULS[name]
    return ceil(M / XBAR_COLS), ceil(C / XBAR_ROWS)


# Placement = {global_xbar_index -> Tile}.  Slot layout is row-major through the
# hierarchy: crossbars fill a core, cores fill a macro, macros fill a die.
class Coord(NamedTuple):
    die: int
    gmacro: int    # GLOBAL macro id (unique across dies -- what the metric groups on)
    gcore: int     # GLOBAL core id
    xbar: int      # crossbar index within its core
    macro: int     # macro index within its die   (plotting)
    core: int      # core index within its macro  (plotting)


def slot_coords(idx: int, geom: Geometry = None) -> Coord:
    g = geom or GEOM
    xbar = idx % g.xbars_per_core
    gcore = idx // g.xbars_per_core
    core = gcore % g.cores_per_macro
    gmacro = gcore // g.cores_per_macro
    macro = gmacro % g.macros_per_die
    die = gmacro // g.macros_per_die
    return Coord(die=die, gmacro=gmacro, gcore=gcore, xbar=xbar, macro=macro, core=core)


# --------------------------------------------------------------------------- #
# Placers
# --------------------------------------------------------------------------- #
def baseline_place(order: List[str], geom: Geometry = None) -> Dict[int, Tile]:
    """Naive contiguous row-major: pour tiles into slots in (i, j) order, matmul after
    matmul, with no regard for core/macro/die boundaries."""
    g = geom or GEOM
    placement: Dict[int, Tile] = {}
    cursor = 0
    for name in order:
        for t in tiles_of(name):
            placement[cursor] = t
            cursor += 1
    if cursor > g.xbars:
        raise ValueError(f"baseline overflow: {cursor} tiles > {g.xbars} crossbars")
    return placement


def optimizer_place(order: List[str], geom: Geometry = None) -> Dict[int, Tile]:
    """Reduction-clustered placer: keep each M-block's C-tiles inside one boundary.

    An M-block's n_C tiles reduce into one output, so every boundary their span
    crosses costs a merge. We pad forward to the next boundary rather than straddle,
    choosing the SMALLEST boundary the block actually fits in:

        n_C <= macro capacity -> pad to a macro boundary (no macro or die crossing)
        n_C <= die capacity   -> pad to a die boundary   (intra-die macro merges only)
        otherwise             -> place contiguously; a die crossing is unavoidable

    On mlx300 the die is 84% full (216/256), so we cannot keep every M-block's
    reduction free (whole-M-block-per-core needs ~39 cores > 32). Targeting the
    expensive term instead drives cross-macro reductions to zero at negligible waste.
    """
    g = geom or GEOM
    placement: Dict[int, Tile] = {}
    cursor = 0
    for name in order:
        m_blocks, n_c = grid(name)
        for mb in range(m_blocks):
            if n_c <= g.macro_slots:
                span = g.macro_slots
            elif n_c <= g.die_slots:
                span = g.die_slots
            else:
                span = None          # cannot be contained at any level
            if span is not None and cursor // span != (cursor + n_c - 1) // span:
                cursor = ((cursor // span) + 1) * span
            for j in range(n_c):
                placement[cursor] = Tile(name, mb, j)
                cursor += 1
    if cursor > g.xbars:
        raise ValueError(
            f"optimizer overflow: {cursor} slots (incl. boundary padding) > "
            f"{g.xbars} crossbars on fabric '{g.name}'")
    return placement


# --------------------------------------------------------------------------- #
# lambda-1 reduction cost
# --------------------------------------------------------------------------- #
@dataclass
class MatmulCost:
    name: str
    cores_used: int
    cross_core: int    # sum over M-blocks of (distinct cores - 1)  == router traversals
    cross_macro: int   # subset of the above that also cross a macro boundary
    cross_die: int     # subset of cross_macro that also cross a die boundary
    energy_flat_pj: float   # legacy flat router: every traversal == 1 hop
    energy_dist_pj: float   # measured distance_router: macro merges = 4 hops


# bytes a single crossbar's partial-sum contributes per reduction merge, in router words
_PARTIAL_WORDS = (XBAR_COLS * P_TOKENS * B_OUT) / WORD_BITS   # = 128*128*8/128 = 1024


def _weights(pure_core: int, pure_macro: int, cross_die: int, w_macro: float,
             w_die: Optional[float]) -> float:
    """Hop-weighted merge count. Raises if a die is crossed with no stated price."""
    if cross_die and w_die is None:
        raise ValueError(
            "placement crosses a die boundary but die-to-die energy is unpriced "
            "(fabric die.link.pj_per_word is null, calibration DR-3). Pass an "
            "explicit w_die=<hops> to score it under a stated assumption.")
    return (W_CORE * pure_core + w_macro * pure_macro
            + (w_die or 0.0) * cross_die)


def cost(placement: Dict[int, Tile], geom: Geometry = None,
         w_die: Optional[float] = None) -> Tuple[List[MatmulCost], float, float]:
    """Score a placement. `w_die` is the die-crossing weight in router hops; it has
    no default because D2D is unmeasured (DR-3) -- see _weights()."""
    from collections import defaultdict
    g = geom or GEOM
    loc: Dict[str, Dict[int, List[Coord]]] = defaultdict(lambda: defaultdict(list))
    cores_by_matmul: Dict[str, set] = defaultdict(set)
    for idx, t in placement.items():
        c = slot_coords(idx, g)
        loc[t.matmul][t.mblock].append(c)
        cores_by_matmul[t.matmul].add(c.gcore)

    pj_per_merge = _PARTIAL_WORDS * ROUTER_PJ_PER_WORD  # one 1-hop merge
    rows: List[MatmulCost] = []
    tot_flat = tot_dist = 0.0
    for name in MATMULS:
        if name not in loc:
            continue
        xcore = xmacro = xdie = 0
        for mb, cells in loc[name].items():
            xcore += len({c.gcore for c in cells}) - 1    # total router traversals
            xmacro += len({c.gmacro for c in cells}) - 1  # of which cross a macro
            xdie += len({c.die for c in cells}) - 1       # of which cross a die
        # nested decomposition: each merge is charged at its OUTERMOST boundary
        pure_core = xcore - xmacro
        pure_macro = xmacro - xdie
        e_flat = _weights(pure_core, pure_macro, xdie, W_MACRO_FLAT, w_die) * pj_per_merge
        e_dist = _weights(pure_core, pure_macro, xdie, W_MACRO_DIST, w_die) * pj_per_merge
        rows.append(MatmulCost(name, len(cores_by_matmul[name]), xcore, xmacro, xdie,
                               e_flat, e_dist))
        tot_flat += e_flat
        tot_dist += e_dist
    return rows, tot_flat, tot_dist


def avg_hops_per_merge(placement: Dict[int, Tile], geom: Geometry = None,
                       w_die: Optional[float] = None) -> Dict[str, float]:
    """Per-matmul average router hops per reduction merge, under the DISTANCE weights.

    This is the encoding placement_sim_compare.py feeds to the simulator's
    HOP_DISTANCE, so it is derived here rather than transcribed by hand. A matmul
    with no cross-boundary merges maps to 1.0 (the neutral single-hop value).
    """
    rows, _, _ = cost(placement, geom, w_die)
    out = {}
    for r in rows:
        if r.cross_core == 0:
            out[r.name] = 1.0
            continue
        pure_core = r.cross_core - r.cross_macro
        pure_macro = r.cross_macro - r.cross_die
        out[r.name] = _weights(pure_core, pure_macro, r.cross_die,
                               W_MACRO_DIST, w_die) / r.cross_core
    return out


# --------------------------------------------------------------------------- #
# Plot (macro x core heatmap, matching Figure 2 style)
# --------------------------------------------------------------------------- #
def core_owner(placement: Dict[int, Tile],
               geom: Geometry = None) -> Dict[Tuple[int, int], str]:
    """(global macro, core within macro) -> dominant matmul in that core."""
    from collections import defaultdict, Counter
    g = geom or GEOM
    counts: Dict[Tuple[int, int], Counter] = defaultdict(Counter)
    for idx, t in placement.items():
        c = slot_coords(idx, g)
        counts[(c.gmacro, c.core)][t.matmul] += 1
    return {k: cnt.most_common(1)[0][0] for k, cnt in counts.items()}


def plot(base: Dict[int, Tile], opt: Dict[int, Tile], out_path: str,
         geom: Geometry = None, w_die: Optional[float] = None) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    g = geom or GEOM
    n_macro = g.dies * g.macros_per_die
    names = list(MATMULS)
    cmap = plt.get_cmap("tab10")
    color = {n: cmap(i) for i, n in enumerate(names)}

    def draw(ax, placement, title):
        owner = core_owner(placement, g)
        for m in range(n_macro):
            for c in range(g.cores_per_macro):
                n = owner.get((m, c))
                ax.add_patch(plt.Rectangle((m, c), 1, 1,
                             facecolor=color[n] if n else "white",
                             edgecolor="white", linewidth=2))
        for d in range(1, g.dies):          # die boundaries, when there are any
            ax.axvline(d * g.macros_per_die, color="0.15", linewidth=2.5)
        ax.set_xlim(0, n_macro); ax.set_ylim(0, g.cores_per_macro)
        ax.set_xticks([x + 0.5 for x in range(n_macro)])
        ax.set_xticklabels(range(n_macro))
        ax.set_yticks([y + 0.5 for y in range(g.cores_per_macro)])
        ax.set_yticklabels(range(g.cores_per_macro))
        ax.set_xlabel("Macro index"); ax.set_ylabel("Core index"); ax.set_title(title)
        ax.set_aspect("equal"); ax.invert_yaxis()

    fig, axes = plt.subplots(2, 1, figsize=(8, 5.5))
    _, base_flat, base_dist = cost(base, g, w_die)
    _, opt_flat, opt_dist = cost(opt, g, w_die)
    draw(axes[0], base, f"Baseline (contiguous)   router E: flat={base_flat/1e6:,.2f} uJ  dist={base_dist/1e6:,.2f} uJ")
    draw(axes[1], opt, f"Reduction-clustered optimizer   router E: flat={opt_flat/1e6:,.2f} uJ  dist={opt_dist/1e6:,.2f} uJ")
    fig.legend(handles=[Patch(color=color[n], label=n) for n in names],
               loc="lower center", ncol=4, fontsize=8, frameon=False)
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, dpi=140); plt.close(fig)
    return out_path


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    g = GEOM
    base = baseline_place(ORDER, g)
    opt = optimizer_place(ORDER, g)

    print(f"fabric '{g.name}' = {g.dies} die x {g.macros_per_die} macros x "
          f"{g.cores_per_macro} cores x {g.xbars_per_core} xbars "
          f"= {g.xbars} crossbars; crossbar {XBAR_ROWS}(C)x{XBAR_COLS}(M) W4A8")
    print(f"Accelerator matmuls (qk/av attention offloaded to CPU): {list(MATMULS)}\n")

    print(f"Router hop energy (Accelergy ERT, re-simulated on mlx_die w/ distance_router): "
          f"{ROUTER_PJ_PER_WORD} pJ / {WORD_BITS}-bit word / hop "
          f"(macro merge = {W_MACRO_DIST:.0f} hops = {W_MACRO_DIST*ROUTER_PJ_PER_WORD:.1f} pJ/word); "
          f"one 1-hop merge = {_PARTIAL_WORDS:.0f} words = "
          f"{_PARTIAL_WORDS*ROUTER_PJ_PER_WORD/1e3:.1f} nJ")
    if g.die_pj_per_word is None:
        print("  die-to-die: UNPRICED (fabric die.link.pj_per_word = null, DR-3) -- "
              "placements that cross a die are refused unless w_die is stated\n")
    else:
        print(f"  die-to-die: {g.die_pj_per_word} pJ/word (fabric)\n")

    summ = {}
    for label, pl in [("BASELINE (contiguous row-major)", base),
                      ("OPTIMIZER (reduction-clustered)", opt)]:
        rows, tflat, tdist = cost(pl, g)
        print(f"===== {label} =====")
        print(f"{'matmul':14}{'n_C':>4}{'cores':>6}{'xcore':>7}{'xmacro':>8}{'xdie':>6}"
              f"{'E_flat(uJ)':>12}{'E_dist(uJ)':>12}")
        print("-" * 69)
        for r in rows:
            _, n_c = grid(r.name)
            print(f"{r.name:14}{n_c:4}{r.cores_used:6}{r.cross_core:7}{r.cross_macro:8}"
                  f"{r.cross_die:6}{r.energy_flat_pj/1e6:12,.2f}{r.energy_dist_pj/1e6:12,.2f}")
        cores_used = len({idx // g.xbars_per_core for idx in pl})
        print("-" * 69)
        print(f"{'TOTAL':14}{'':4}{cores_used:6}"
              f"{sum(r.cross_core for r in rows):7}{sum(r.cross_macro for r in rows):8}"
              f"{sum(r.cross_die for r in rows):6}"
              f"{tflat/1e6:12,.2f}{tdist/1e6:12,.2f}\n")
        summ[label] = (tflat, tdist)

    (bf, bd), (of, od) = summ["BASELINE (contiguous row-major)"], summ["OPTIMIZER (reduction-clustered)"]
    print("================ IMPROVEMENT ================")
    print(f"  FLAT router (legacy isaac_router, HOP_DISTANCE=1): "
          f"{bf/1e6:,.2f} -> {of/1e6:,.2f} uJ  ({100*(bf-of)/bf:.0f}% less)")
    print(f"  DISTANCE-AWARE router (measured, distance_router @ HOP_DISTANCE=4): "
          f"{bd/1e6:,.2f} -> {od/1e6:,.2f} uJ  ({100*(bd-od)/bd:.0f}% less)")

    out = os.path.join(os.path.dirname(__file__), "..", "outputs",
                       "encoder_block_floorplan", "die_solver_placement.png")
    p = plot(base, opt, out, g)
    print(f"Saved comparison heatmap -> {os.path.abspath(p)}")
