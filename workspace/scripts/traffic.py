"""TrafficExtraction (workstream B): the real communication structure, derived
from the mapping instead of divided uniformly.

Stage 1 of the two-stage split agreed in the review: this module is
placement-free volume algebra. Geometry (who sits where, how far) stays in
crossbar_comm, which consumes the numbers computed here.

Semantics (tensor algebra for C[p,m,n] += A[p,c,n] * B[c,m,n], nothing else):
    a spatial split on M   -> inputs SHARED across the instances (multicast 1->N),
                              outputs distinct;
    a spatial split on C   -> inputs distinct, outputs are PARTIAL SUMS
                              (reduction N->1, merged at the parent hub);
    a spatial split on P/N -> both distinct (pure partition).
Weights are resident (programmed once) and have no per-inference flow.

Volumes come from the run's stats (leaf receptions/productions:
row_drivers / adc totals) and are DE-MULTIPLIED into unique slices using the
mapping's spatial factors; a conservation guard ties everything back to the
stats counters, so a disagreement between our derivation and Timeloop's own
accounting raises instead of passing silently.
"""
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

from scripts import crossbar_stats as cbs

# which dims partition each tensor when split spatially
IN_DISTINCT = {"P", "C", "N", "Q", "R", "S", "G"}   # input slices differ
OUT_DISTINCT = {"P", "M", "N", "Q", "G"}            # output slices differ
OUT_REDUCED = {"C", "R", "S"}                       # outputs merge (partial sums)


def _prod(xs):
    out = 1
    for x in xs:
        out *= x
    return out


@dataclass(frozen=True)
class LevelSplit:
    """Spatial factors the mapping assigns at one on-die tree level."""
    level: str                 # fabric level name (macro / core / crossbar)
    factors: Dict[str, int]    # dim -> factor (absent dim == 1)

    @property
    def fanout(self) -> int:
        return _prod(self.factors.values())

    @property
    def in_distinct(self) -> int:
        return _prod(f for d, f in self.factors.items() if d in IN_DISTINCT)

    @property
    def out_distinct(self) -> int:
        return _prod(f for d, f in self.factors.items() if d in OUT_DISTINCT)


@dataclass(frozen=True)
class TrafficStructure:
    splits: List[LevelSplit]   # ordered top (macro) -> bottom (crossbar)
    in_leaf: float             # unique input words RECEIVED per active leaf
    out_leaf: float            # output words PRODUCED per active leaf

    @property
    def n_active(self) -> int:
        return _prod(s.fanout for s in self.splits)

    def active_fanouts(self) -> List[int]:
        return [s.fanout for s in self.splits]

    def edge_volumes(self) -> Dict[str, Dict[str, float]]:
        """Per-level hub<->instance edge volumes.

        Going DOWN one level-k instance's edge, the input is that subtree's
        UNIQUE slice: leaf volume times the distinct-input factors below k
        (multicast factors below k drop out -- that is the whole correction).
        Going UP, the edge carries the subtree's outputs: distinct-output
        factors below k (partial sums have not merged yet -- they merge at the
        hub above, so reduction does NOT shrink the edge below it).
        """
        out = {}
        for k, s in enumerate(self.splits):
            below = self.splits[k + 1:]
            out[s.level] = {
                "in": self.in_leaf * _prod(b.in_distinct for b in below),
                "out": self.out_leaf * _prod(b.out_distinct for b in below),
            }
        return out

    def reduction_hyperedges(self, level: str) -> List[List[int]]:
        """Instance indices at `level` grouped into REDUCTION hyperedges.

        A reduction hyperedge is the set of instances whose partial sums must
        merge into one output: they differ only in the reduction dims (C/R/S)
        and agree on every other spatial coordinate. This is the structure a
        placement search moves around, and the input the lambda-1 / h_tree cost
        model needs -- until now traffic.py only produced per-level AGGREGATE
        volumes, which cannot express "these particular tiles must merge".

        Counts are convention-free: with factors {C:4, P:2} there are always
        2 hyperedges of size 4. MEMBERSHIP additionally needs an index
        convention, and we use the mapping's own loop order with the FIRST
        listed dim varying slowest. That convention should be confirmed against
        Timeloop's spatial index order before per-instance results are trusted;
        the counts and sizes do not depend on it.
        """
        split = next((s for s in self.splits if s.level == level), None)
        if split is None:
            raise KeyError(f"no split for level '{level}'")
        dims = list(split.factors.items())
        groups: Dict[tuple, List[int]] = {}
        for i in range(split.fanout):
            rem, coord = i, []
            for name, f in reversed(dims):          # last listed varies fastest
                coord.append((name, rem % f))
                rem //= f
            key = tuple(v for name, v in coord if name not in OUT_REDUCED)
            groups.setdefault(key, []).append(i)
        return [sorted(g) for g in groups.values()]

    def hyperedge_shape(self, level: str) -> Tuple[int, int]:
        """(number of reduction hyperedges, size of each) -- convention-free."""
        split = next((s for s in self.splits if s.level == level), None)
        if split is None:
            raise KeyError(f"no split for level '{level}'")
        red = _prod(f for d, f in split.factors.items() if d in OUT_REDUCED)
        return split.fanout // red, red

    def leaf_shares(self) -> Dict[str, float]:
        """One active leaf's attributable volume on each level's edge (shared
        multicast volume split among the leaves it serves) -- the per-crossbar
        heatmap weights."""
        shares = {}
        ev = self.edge_volumes()
        for k, s in enumerate(self.splits):
            leaves_under = _prod(b.fanout for b in self.splits[k + 1:])
            shares[s.level] = (ev[s.level]["in"] + ev[s.level]["out"]) / leaves_under
        return shares


def extract(output_dir=None, fabric=None, mapping_text=None, stats_text=None):
    """Build the TrafficStructure for one run.

    Reads timeloop-mapper.{map,stats}.txt from output_dir unless the texts are
    passed directly (tests use frozen fixtures).
    """
    from scripts import fabric as fabric_mod
    fab = fabric or fabric_mod.default()
    if mapping_text is None:
        with open(os.path.join(output_dir, "timeloop-mapper.map.txt")) as f:
            mapping_text = f.read()
    if stats_text is None:
        with open(os.path.join(output_dir, "timeloop-mapper.stats.txt")) as f:
            stats_text = f.read()

    # the on-die tree levels and their inter_<child>_in_<parent>_spatial names
    meshed = [lv for lv in fab.levels if lv.mesh is not None]
    tree = meshed[-3:]
    parents = [meshed[-4].name if len(meshed) >= 4 else "die"] \
        + [lv.name for lv in tree[:-1]]
    wanted = {f"inter_{lv.name}_in_{par}_spatial": lv.name
              for lv, par in zip(tree, parents)}

    parsed = dict(cbs.parse_mapping_levels(mapping_text))
    splits = []
    for mapping_name, level_name in wanted.items():
        loops = parsed.get(mapping_name, [])
        factors = {}
        for dim, factor, _axis in loops:
            factors[dim] = factors.get(dim, 1) * factor
        splits.append(LevelSplit(level_name, factors))

    # capacity guard: the mapper cannot use more instances than the fabric has
    for s, lv in zip(splits, tree):
        if s.fanout > lv.per_parent:
            raise ValueError(f"mapping uses {s.fanout} {lv.name} instances but "
                             f"the fabric has {lv.per_parent}")

    in_total = cbs._per_tensor_volume(stats_text, "row_drivers")
    out_total = cbs._per_tensor_volume(stats_text, "adc")
    n_active = _prod(s.fanout for s in splits)

    # consistency guard: the leaf counters must split EVENLY over the active
    # instances the mapping declares. A remainder means the parsed factors and
    # Timeloop's own accounting disagree -- raise, don't smear it uniformly.
    for name, total in (("row_drivers", in_total), ("adc", out_total)):
        if total % n_active:
            raise ValueError(
                f"{name} total {total} does not divide over {n_active} active "
                "leaves -- mapping factors and stats counters disagree")

    return TrafficStructure(splits=splits, in_leaf=in_total // n_active,
                            out_leaf=out_total // n_active)
