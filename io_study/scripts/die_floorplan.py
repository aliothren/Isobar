"""Die floorplanner — Phase 1 of fused/pipelined mapping: WEIGHT PLACEMENT.

Places all of an encoder block's matmul weights across a fixed CiM die *in parallel*
(disjoint regions, weight-stationary, written once), producing a die-level placement
map that is later fed to the pipelined-execution model.

The die is a fixed hierarchy: MACROS x CORES_PER_MACRO x XBARS_PER_CORE crossbars.
Each crossbar holds one weight block of one matmul (block = XBAR_ROWS x XBAR_COLS of
the weight matrix). Each matmul needs `m_blocks x c_blocks x G` crossbars; the packer
lays each matmul's footprint into a contiguous run of cores so producer->consumer
regions stay routing-adjacent for the later pipeline.

Pure arithmetic (no Timeloop) — crossbar logical dims come from the mapped block sizes
(for wan_nature W4A8: 256 rows (C) x 128 cols (M)).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import Dict, List, Tuple

# --------------------------------------------------------------------------- #
# Die geometry (MLX default: mlx_die x mlx_core x wan_nature_2022, W4A8)
# --------------------------------------------------------------------------- #
MACROS = 8            # macro_in_die
CORES_PER_MACRO = 4   # core_in_macro
XBARS_PER_CORE = 8    # crossbar_in_core
XBAR_ROWS = 256       # C (input channels) per crossbar  (array_row)
XBAR_COLS = 128       # M (output channels) per crossbar (array_col, W4A8 logical)


@dataclass
class Footprint:
    name: str
    M: int
    C: int
    G: int
    stationary: bool
    m_blocks: int
    c_blocks: int
    crossbars: int


def footprint(name, M, C, G=1, stationary=True,
              xbar_rows=XBAR_ROWS, xbar_cols=XBAR_COLS) -> Footprint:
    mb = ceil(M / xbar_cols)
    cb = ceil(C / xbar_rows)
    return Footprint(name, M, C, G, stationary, mb, cb, mb * cb * G)


@dataclass
class Region:
    name: str
    core_start: int              # global core index [0, total_cores)
    n_cores: int
    crossbars_used: int
    crossbars_alloc: int         # n_cores * XBARS_PER_CORE
    waste: int
    cores: List[Tuple[int, int]] = field(default_factory=list)  # (macro, core)


def floorplan(matmuls: Dict[str, tuple],
              macros=MACROS, cores_per_macro=CORES_PER_MACRO,
              xbars_per_core=XBARS_PER_CORE,
              xbar_rows=XBAR_ROWS, xbar_cols=XBAR_COLS):
    """matmuls: name -> (M, C, G, stationary). Returns (footprints, regions, meta)."""
    fps = [footprint(n, *cfg, xbar_rows=xbar_rows, xbar_cols=xbar_cols)
           for n, cfg in matmuls.items()]
    total_cores = macros * cores_per_macro
    regions, cursor = [], 0
    for fp in fps:
        n_cores = ceil(fp.crossbars / xbars_per_core)
        cores = [divmod(cursor + i, cores_per_macro) for i in range(n_cores)]
        regions.append(Region(fp.name, cursor, n_cores, fp.crossbars,
                               n_cores * xbars_per_core,
                               n_cores * xbars_per_core - fp.crossbars, cores))
        cursor += n_cores
    meta = dict(cores_used=cursor, total_cores=total_cores,
                xbars_used=sum(f.crossbars for f in fps),
                total_xbars=total_cores * xbars_per_core,
                fits=cursor <= total_cores)
    return fps, regions, meta


def verify(regions: List[Region], meta: dict) -> List[str]:
    """Return a list of problems (empty == valid placement)."""
    problems = []
    occupied = {}
    for r in regions:
        for c in r.cores:
            if c in occupied:
                problems.append(f"core {c} shared by {occupied[c]} and {r.name}")
            occupied[c] = r.name
    if not meta["fits"]:
        problems.append(f"needs {meta['cores_used']} cores > {meta['total_cores']} available")
    return problems


def die_map(regions: List[Region], macros=MACROS, cores_per_macro=CORES_PER_MACRO) -> str:
    """ASCII map: one row per macro, one cell per core, labeled by matmul."""
    owner = {}
    for r in regions:
        for c in r.cores:
            owner[c] = r.name
    lines = []
    for m in range(macros):
        cells = [f"{owner.get((m, c), '·')[:11]:<11}" for c in range(cores_per_macro)]
        lines.append(f"Macro {m}: | " + " | ".join(cells) + " |")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Step 3-4: per-crossbar weight-block assignment + unified die placement map
# --------------------------------------------------------------------------- #


@dataclass
class Placement:
    macro: int
    core: int
    xbar: int          # crossbar within its core (0..XBARS_PER_CORE-1)
    matmul: str
    head: int          # G index
    m_block: int
    c_block: int
    M_lo: int
    M_hi: int
    C_lo: int
    C_hi: int


def place_blocks(fps: List[Footprint], regions: List[Region],
                 xbars_per_core=XBARS_PER_CORE,
                 xbar_rows=XBAR_ROWS, xbar_cols=XBAR_COLS) -> List[Placement]:
    """Assign each occupied crossbar the exact (matmul, head, M/C block) it holds.
    Waste crossbars (partial cores) are left unassigned / omitted."""
    fp_by_name = {f.name: f for f in fps}
    placements: List[Placement] = []
    for r in regions:
        fp = fp_by_name[r.name]
        # physical crossbars in this region, in order (macro, core, xbar)
        slots = [(m, c, x) for (m, c) in r.cores for x in range(xbars_per_core)]
        # weight tiles for this matmul, in order (head, m_block, c_block)
        tiles = [(g, mb, cb) for g in range(fp.G)
                 for mb in range(fp.m_blocks) for cb in range(fp.c_blocks)]
        for (m, c, x), (g, mb, cb) in zip(slots, tiles):
            placements.append(Placement(
                macro=m, core=c, xbar=x, matmul=fp.name, head=g,
                m_block=mb, c_block=cb,
                M_lo=mb * xbar_cols, M_hi=min((mb + 1) * xbar_cols, fp.M),
                C_lo=cb * xbar_rows, C_hi=min((cb + 1) * xbar_rows, fp.C)))
    return placements


def export(placements: List[Placement], out_dir: str) -> int:
    """Write the unified die placement map to CSV + JSON. Returns row count."""
    import os
    import csv
    import json
    os.makedirs(out_dir, exist_ok=True)
    fields = ["macro", "core", "xbar", "matmul", "head",
              "m_block", "c_block", "M_lo", "M_hi", "C_lo", "C_hi"]
    rows = [{f: getattr(p, f) for f in fields} for p in placements]
    with open(os.path.join(out_dir, "die_placement.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(out_dir, "die_placement.json"), "w") as fh:
        json.dump(rows, fh, indent=2)
    return len(rows)


# --------------------------------------------------------------------------- #
# Demo: BERT-100M encoder block on one MLX die (W4A8)
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    H, I, HEADS, HD, S = 768, 3072, 12, 64, 128
    # name -> (M, C, G, stationary)
    BLOCK = {
        "ffn1":          (I, H, 1, True),
        "ffn2":          (H, I, 1, True),
        "qkv_proj":      (3 * H, H, 1, True),
        "attn_out_proj": (H, H, 1, True),
        "qk":            (S, HD, HEADS, False),   # dynamic (attention activations)
        "av":            (HD, S, HEADS, False),
    }

    fps, regions, meta = floorplan(BLOCK)

    print(f"MLX die = {MACROS}x{CORES_PER_MACRO}x{XBARS_PER_CORE} = "
          f"{meta['total_xbars']} crossbars ({meta['total_cores']} cores); "
          f"crossbar logical {XBAR_ROWS}(C)x{XBAR_COLS}(M) W4A8\n")

    print(f"{'matmul':14}{'M':>6}{'C':>6}{'G':>3}{'Mblk':>6}{'Cblk':>6}"
          f"{'xbars':>7}{'cores':>6}{'alloc':>6}{'waste':>6}  type")
    print("-" * 78)
    for fp, r in zip(fps, regions):
        print(f"{fp.name:14}{fp.M:6}{fp.C:6}{fp.G:3}{fp.m_blocks:6}{fp.c_blocks:6}"
              f"{fp.crossbars:7}{r.n_cores:6}{r.crossbars_alloc:6}{r.waste:6}  "
              f"{'stationary' if fp.stationary else 'dynamic'}")

    stat = sum(f.crossbars for f in fps if f.stationary)
    print("-" * 78)
    print(f"stationary weights: {stat} crossbars | all matmuls: {meta['xbars_used']} | "
          f"cores used: {meta['cores_used']}/{meta['total_cores']} | "
          f"die util: {100*meta['cores_used']*XBARS_PER_CORE/meta['total_xbars']:.0f}%")

    print("\nDie floorplan (core granularity, contiguous):")
    print(die_map(regions))

    problems = verify(regions, meta)
    print("\nVERIFY:", "OK — all matmuls placed, disjoint, fits die ✓"
          if not problems else "PROBLEMS: " + "; ".join(problems))

    # ---- Step 3: per-crossbar weight-block assignment ----
    placements = place_blocks(fps, regions)
    expected = sum(f.crossbars for f in fps)
    print(f"\nStep 3 — per-crossbar weight blocks: {len(placements)} tiles placed "
          f"(expected {expected}) {'✓' if len(placements) == expected else '✗'}")
    print(f"  {'macro':>5}{'core':>5}{'xbar':>5}  {'matmul':14}{'head':>5}"
          f"{'m_blk':>6}{'c_blk':>6}  M[lo:hi]      C[lo:hi]")
    for p in placements[:4] + placements[-2:]:
        print(f"  {p.macro:5}{p.core:5}{p.xbar:5}  {p.matmul:14}{p.head:5}"
              f"{p.m_block:6}{p.c_block:6}  [{p.M_lo}:{p.M_hi}]   [{p.C_lo}:{p.C_hi}]")

    # ---- Step 4: export the unified die placement map ----
    import os
    out = os.path.join(os.path.dirname(__file__), "..", "outputs", "encoder_block_floorplan")
    n = export(placements, out)
    print(f"\nStep 4 — exported {n} crossbar placements to "
          f"{os.path.abspath(out)}/die_placement.{{csv,json}}")
