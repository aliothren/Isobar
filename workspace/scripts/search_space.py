"""The deployment search space: the mapping Pi = (gamma, alpha, beta), its
legality check and its JSON form.

  gamma  `cuts`: ascending segment END indices over the L-block chain,
         the last equal to L (e.g. L = 32, cuts = (2, 4, ..., 32) = 16
         segments of 2). Only the evaluator's "pipe" caliber reads it; the
         "single" caliber does not depend on it.
  alpha  `seat`: die-set name "op@L{i}" -> package die slots, injective
         across the whole package; plus `hub` (die-level hub spec) and
         `attach` (attach slot of an offloaded unit), which legal() checks
         and the evaluator does not read.
  beta   optional per-die macro permutation, checked structurally only;
         None = the default macro order. On a die that holds one operator
         every macro carries the same traffic, so every permutation scores
         the same; the co-resident within-die case is searched by
         search_withindie.py on its own seat map.

Legality follows the tiler: a die-set must seat exactly the die count the
tiler assigns it (llm_workload.block_chain, which consults plan_spatial).
Capacity arithmetic alone does not make a count legal, so the feasible
counts of an operator (feasible_die_counts) can be a sparse set.
"""
import json
import os
import sys
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import llm_workload as lw

@dataclass(frozen=True)
class Pi:
    n_blocks: int
    cuts: Tuple[int, ...]
    seat: Dict[str, Tuple[int, ...]]
    hub: Optional[str] = None            # None = the fabric config's own hub
    attach: Optional[int] = None         # None = the die-level hub position
    beta: Optional[Dict[int, Tuple[int, ...]]] = None

    # ------------------------------------------------------- serialization
    def to_json(self) -> str:
        return json.dumps({
            "n_blocks": self.n_blocks, "cuts": list(self.cuts),
            "seat": {k: list(v) for k, v in self.seat.items()},
            "hub": self.hub, "attach": self.attach,
            "beta": ({str(k): list(v) for k, v in self.beta.items()}
                     if self.beta is not None else None)}, indent=1)

    @staticmethod
    def from_json(text: str) -> "Pi":
        d = json.loads(text)
        return Pi(n_blocks=d["n_blocks"], cuts=tuple(d["cuts"]),
                  seat={k: tuple(v) for k, v in d["seat"].items()},
                  hub=d.get("hub"), attach=d.get("attach"),
                  beta=({int(k): tuple(v) for k, v in d["beta"].items()}
                        if d.get("beta") is not None else None))

    # ------------------------------------------------------- segment views
    def segments(self):
        """[(start, end)) block ranges, from the cut vector."""
        out, lo = [], 0
        for hi in self.cuts:
            out.append((lo, hi))
            lo = hi
        return out

    def stage_sets(self):
        """Per segment: the die-set names it contains (data-flow order)."""
        segs = []
        for lo, hi in self.segments():
            segs.append([k for k in self.seat
                         if lo <= int(k.rsplit("@L", 1)[1]) < hi])
        return segs


def chain_inventory(cfg, S: int, max_dies: int, dims=("M", "C"), on_chip: bool = True):
    """The die-set inventory of one block: [(name, n_dies)], n_dies being
    the tiler's answer (block_chain consults plan_spatial), not capacity
    arithmetic. With the attention offloaded (on_chip False) the attention
    entry takes no die and is not a seated set (its endpoint is the unit's
    node)."""
    return [(e["name"], e["n_dies"])
            for e in lw.block_chain(cfg, S, "prefill", on_chip=on_chip,
                                    max_dies=max_dies, dims=dims) if e["n_dies"] > 0]


# ---- inventories: the seating granularity is declared by the workload
# (one die-set per operator from block_chain, or one die per unit);
# legal() checks a Pi against the inventory and never re-derives it.
def inventory_from_block_chain(cfg, S: int, max_dies: int, dims=("M", "C"), on_chip: bool = True):
    """{'op@L{i}': n_dies} for the L blocks, one die-set per operator.
    `dims` is the tiler's split-dimension preference (the tiling variants
    of experiment.TILINGS); the default ("M", "C") splits columns first."""
    inv = chain_inventory(cfg, S, max_dies, dims, on_chip)
    return {f"{name}@L{li}": n
            for li in range(cfg.n_layers) for name, n in inv}


def inventory_units(n_units: int):
    """{'unit{u}': 1}: the unit-granularity inventory, one die per unit,
    for chains whose layers are split into units of co-resident operators
    (e.g. two per layer: the attention half and the FFN half)."""
    return {f"unit{u}": 1 for u in range(n_units)}


def feasible_die_counts(op, max_dies: int):
    """The tiler-feasible die counts of one operator: {n : plan_spatial
    with min_dies = n lands exactly on n}, the per-operator group-size
    axis of the layer-grouping DP (search_dp.py). Possibly sparse (the
    2.7B-class ffn1 has no 4)."""
    out = []
    for n in range(1, max_dies + 1):
        try:
            got, _, _ = lw.plan_spatial(op, max_dies=max_dies, min_dies=n)
        except ValueError:
            continue
        if got == n:
            out.append(n)
    return out


def legal(pi: Pi, fabric, inventory: Dict[str, int]) -> Tuple[bool, str]:
    """Check Pi against the package and the workload-declared inventory
    ({name: tiler n_dies}, never re-derived here): well-formed cuts, every
    die-set seated at exactly its tiler size on distinct in-package slots
    with no overlap, valid hub / attach specs, and beta maps that are
    permutations on seated dies. Returns (ok, reason)."""
    L, P = pi.n_blocks, fabric.level("die").per_parent
    # gamma
    if (not pi.cuts or list(pi.cuts) != sorted(set(pi.cuts))
            or pi.cuts[-1] != L or pi.cuts[0] < 1):
        return False, "gamma: cuts must be ascending, in [1, L], ending at L"
    # alpha: coverage at the workload's declared tiler sizes
    want = dict(inventory)
    if set(pi.seat) != set(want):
        missing = sorted(set(want) - set(pi.seat))[:3]
        extra = sorted(set(pi.seat) - set(want))[:3]
        return False, f"alpha: die-set keys diverge (missing {missing}, extra {extra})"
    used = []
    for k, slots in pi.seat.items():
        if len(slots) != want[k]:
            return False, (f"alpha: {k} seats {len(slots)} dies; the TILER "
                           f"requires exactly {want[k]} (capacity arithmetic "
                           f"is not legality)")
        if len(set(slots)) != len(slots):
            return False, f"alpha: {k} repeats a slot"
        used += list(slots)
    if len(set(used)) != len(used):
        return False, "alpha: die sets overlap"
    if used and (min(used) < 0 or max(used) >= P):
        return False, f"alpha: slot outside the {P}-die package"
    # small dimensions
    if pi.hub is not None:
        if not (pi.hub in ("center", "corner")
                or (pi.hub.startswith("node:")
                    and 0 <= int(pi.hub.split(":", 1)[1]) < P)):
            return False, f"alpha: bad hub spec '{pi.hub}'"
    if pi.attach is not None and not (0 <= pi.attach < P):
        return False, "alpha: attach slot outside the package"
    # beta: structural check only
    if pi.beta is not None:
        seated = set(used)
        for d, perm in pi.beta.items():
            if d not in seated:
                return False, f"beta: die {d} is not seated"
            if sorted(perm) != list(range(len(perm))):
                return False, f"beta: die {d} map is not a permutation"
    return True, "ok"
