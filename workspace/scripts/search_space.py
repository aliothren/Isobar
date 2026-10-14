"""S1 day 1 (C64-a): the search space -- Pi, legality, serialization.

Semantic authority: SYNC_search_v1 (sections 3-4); the accepted
implementation amendments are pre-registered in FIXLIST (search v1
block). The decision variable Pi = (gamma, alpha, beta):

  gamma  `cuts`: ascending segment END indices over the L-block chain,
         last == L (e.g. L=32, cuts=(2,4,...,32) = 16 stages of 2).
         Consumed by the PIPE caliber only (single is gamma-blind).
  alpha  `seat`: die-set name "op@L{i}" -> package die slots, injective
         across the whole machine; plus the small dimensions `hub`
         (die-level hub spec) and `attach` (offload-unit attach slot).
  beta   optional per-die within-die permutation (v1: structurally
         validated, semantically consumed only by the S3 die-level
         co-residency instance; None = the standing frozen-mapping
         rule -- the A1 degeneracy makes it zero-dimensional wherever
         co-residency is off).

TILER FEASIBILITY (amendment 1, the O10 lesson): the per-die-set seat
size must equal the STANDING RULE's tiler answer (block_chain, which
consults plan_spatial) -- capacity arithmetic is not legality; and the
oracle's group-size axis is the TILER-FEASIBLE SIZE SET
(feasible_die_counts below), possibly sparse.
"""
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import llm_workload as lw

A4_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "analysis", "a4_full_model.json")


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
    """The STANDING RULE's die-set inventory for one block: [(name,
    n_dies)] -- n_dies is the TILER's answer (block_chain consults
    plan_spatial), never capacity arithmetic (amendment 1 / O10). With
    the attention offloaded (on_chip False) the attention entry takes no
    die and is not a seated set (its endpoint is the unit's node)."""
    return [(e["name"], e["n_dies"])
            for e in lw.block_chain(cfg, S, "prefill", on_chip=on_chip,
                                    max_dies=max_dies, dims=dims) if e["n_dies"] > 0]


# ---- inventories: the die-set granularity is DECLARED BY THE WORKLOAD
# (day-2 interface amendment, recorded in FIXLIST: the frozen tiling T of
# the condition layer owns the seating granularity -- the 2.7B class
# seats per-op sets [block_chain], the 355M class seats per-UNIT under
# the C13 two-dies-per-layer co-residency rule; legal() consumes the
# inventory, never re-derives it).
def inventory_from_block_chain(cfg, S: int, max_dies: int, dims=("M", "C"), on_chip: bool = True):
    """{'op@L{i}': n_dies} for L blocks under the per-op standing rule.
    `dims` = the tiler's split-dimension preference (the V3 tiling variants);
    the default is the standing column-first rule."""
    inv = chain_inventory(cfg, S, max_dies, dims, on_chip)
    return {f"{name}@L{li}": n
            for li in range(cfg.n_layers) for name, n in inv}


def inventory_units(n_units: int):
    """{'unit{u}': 1} -- the 355M C13 granularity (two units per layer:
    the attention half and the FFN half, one die each, co-residency
    inside the unit is part of the frozen tiling)."""
    return {f"unit{u}": 1 for u in range(n_units)}


def feasible_die_counts(op, max_dies: int):
    """The ORACLE's group-size axis (amendment 1): the tiler-feasible
    size set for one op -- {n : plan_spatial with min_dies=n lands
    EXACTLY on n}. Possibly sparse (the O10 counterexamples: 2.7B ffn1
    has no 4)."""
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
    """The formalisation of Placement.verify + the tiler fold-in.
    `inventory` is the workload-declared die-set granularity ({name:
    tiler n_dies}); legal() never re-derives it. Returns (ok, reason)."""
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
                           f"is not legality -- O10)")
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
    # beta (v1: structural only; semantics land with the S3 instance)
    if pi.beta is not None:
        seated = set(used)
        for d, perm in pi.beta.items():
            if d not in seated:
                return False, f"beta: die {d} is not seated"
            if sorted(perm) != list(range(len(perm))):
                return False, f"beta: die {d} map is not a permutation"
    return True, "ok"


def pi_from_a4_payload(path: str = A4_JSON, use_seam: bool = True) -> Pi:
    """The standard test case: A4's 544-seat map (+ the 16x2 seam example
    as gamma when use_seam)."""
    d = json.load(open(path))
    p = d["seating_s4_payload"]
    seat = {k: tuple(v) for k, v in p["map"].items()}
    L = 1 + max(int(k.rsplit("@L", 1)[1]) for k in seat)
    if use_seam:
        per = p["seam_example_16x2"]["layers_per_package"]
        cuts = tuple(range(per, L + 1, per))
    else:
        cuts = (L,)
    return Pi(n_blocks=L, cuts=cuts, seat=seat)
