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
import re
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple

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
    in_leaf: float             # unique input VALUES (8-bit words) received per active leaf
    out_leaf: float            # output VALUES (partial sums) produced per active leaf
    # Units (C25): Timeloop counts the Inputs dataspace in input bit slices
    # (X, e.g. 7 per 8-bit word) and the Outputs dataspace in output bits
    # (Z, 8 per word), and every physical cell column of a weight (Y at the
    # column level, 2 under differential encoding) converts on its own ADC;
    # "Total scalar accesses" further adds reads + fills (+ updates). The
    # leaf volumes above are VALUES: row-driver READS / X, ADC READS / Z / Y.
    x_slices: int = 1          # input bit slices per value (product of the X loops)
    z_bits: int = 1            # output bits per value (product of the Z loops)
    y_columns: int = 1         # cell columns per weight (Y factor at the column level)
    in_reads_total: int = 0    # row-driver scalar reads, all instances (counter units)
    out_reads_total: int = 0   # ADC scalar reads, all instances (counter units)
    tensor_in: Optional[int] = None    # P*C*N of the problem (values), when derivable
    tensor_out: Optional[int] = None   # P*M*N of the problem (values), when derivable

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

    # DIE level (spatial_multi_die, O10): a chip-level spatial split in the
    # mapping means the op spans dies. Same LevelSplit semantics one level up:
    # a C-split there is a cross-die partial-sum reduction, an M-split a
    # cross-die input multicast. Absent (meshX=1) nothing changes.
    die_loops = parsed.get("inter_chip_in_system_spatial", [])
    die_factors = {}
    for dim, factor, _axis in die_loops:
        if factor > 1:
            die_factors[dim] = die_factors.get(dim, 1) * factor
    if die_factors:
        die_lv = fab.level("die")
        die_split = LevelSplit("die", die_factors)
        if die_split.fanout > die_lv.per_parent:
            raise ValueError(f"mapping spans {die_split.fanout} dies but the "
                             f"fabric has {die_lv.per_parent}")
        splits.insert(0, die_split)

    # capacity guard: the mapper cannot use more instances than the fabric has
    tree_splits = splits[-3:]
    for s, lv in zip(tree_splits, tree):
        if s.fanout > lv.per_parent:
            raise ValueError(f"mapping uses {s.fanout} {lv.name} instances but "
                             f"the fabric has {lv.per_parent}")

    # Leaf counters in VALUE units (C25). Timeloop's Inputs dataspace is in
    # input bit slices (the X loops, 7 for 8-bit signed inputs) and its
    # Outputs dataspace in output bits (the Z loops, 8); every physical cell
    # column of a weight (Y at the column level) has its own ADC. The
    # counters therefore read X x (values) at the row drivers and
    # Z x Y_col x (values) at the ADCs -- and "Total scalar accesses" would
    # further add fills and updates on top of the reads. Take READS only and
    # divide the units out.
    in_reads = _component_reads(stats_text, "row_drivers")
    out_reads = _component_reads(stats_text, "adc")
    x_slices = _loop_product(mapping_text, "X")
    z_bits = _loop_product(mapping_text, "Z")
    y_columns = 1
    for lname, loops in parsed.items():
        if lname == "inter_column_spatial":
            for dim, factor, _axis in loops:
                if dim == "Y":
                    y_columns *= factor
    n_active = _prod(s.fanout for s in splits)

    # consistency guards: the leaf counters must split EVENLY over the active
    # instances the mapping declares AND over the unit factors. A remainder
    # means the parsed factors and Timeloop's own accounting disagree --
    # raise, don't smear it uniformly.
    for name, total, unit in (("row_drivers", in_reads, n_active * x_slices),
                              ("adc", out_reads, n_active * z_bits * y_columns)):
        if total % unit:
            raise ValueError(
                f"{name} reads {total} do not divide over {n_active} active "
                f"leaves x unit factor {unit // n_active} -- mapping factors and "
                "stats counters disagree")
    in_leaf = in_reads // (n_active * x_slices)
    out_leaf = out_reads // (n_active * z_bits * y_columns)

    # tensor guard: the union of the leaves' distinct slices must be the
    # operand ONCE (P x C x N in, P x M x N out) -- the check that catches a
    # unit mistake at the source. Skipped for problems with other dims.
    dims = _all_loop_products(mapping_text)
    tensor_in = tensor_out = None
    if set(dims) <= {"P", "C", "M", "N", "X", "Y", "Z"}:
        P, C, M, N = (dims.get(d, 1) for d in ("P", "C", "M", "N"))
        tensor_in, tensor_out = P * C * N, P * M * N
        union_in = in_leaf * _prod(s.in_distinct for s in splits)
        union_out = out_leaf * _prod(s.out_distinct for s in splits)
        if union_in != tensor_in or union_out != tensor_out:
            raise ValueError(
                f"leaf slices do not reassemble the operands once: inputs "
                f"{union_in} vs P*C*N {tensor_in}, outputs {union_out} vs "
                f"P*M*N {tensor_out} (x_slices {x_slices}, z_bits {z_bits}, "
                f"y_columns {y_columns})")

    return TrafficStructure(splits=splits, in_leaf=in_leaf, out_leaf=out_leaf,
                            x_slices=x_slices, z_bits=z_bits, y_columns=y_columns,
                            in_reads_total=in_reads, out_reads_total=out_reads,
                            tensor_in=tensor_in, tensor_out=tensor_out)


def _component_reads(stats_text: str, comp: str) -> int:
    """Scalar READS of one component over all utilized instances (the first
    dataspace block of the component's main section)."""
    m = re.search(rf"=== {comp} ===(.*?)(?=\n=== )", stats_text, re.S)
    if not m:
        return 0
    body = m.group(1)
    inst = re.search(r"Utilized instances \(max\)\s*:\s*(\d+)", body)
    reads = re.search(r"Scalar reads \(per-instance\)\s*:\s*(\d+)", body)
    if not inst or not reads:
        return 0
    return int(inst.group(1)) * int(reads.group(1))


def _loop_product(mapping_text: str, dim: str) -> int:
    prod = 1
    for m in re.finditer(rf"for {dim} in \[0:(\d+)\)", mapping_text):
        prod *= int(m.group(1))
    return prod


def _all_loop_products(mapping_text: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for m in re.finditer(r"for (\w+) in \[0:(\d+)\)", mapping_text):
        out[m.group(1)] = out.get(m.group(1), 1) * int(m.group(2))
    return out
