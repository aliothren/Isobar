"""Simba workload: ResNet-50 conv layers as closed-form operators on the
Simba fabric (models/fabric/simba.yaml), for the seating reference of
Fig. 3(a).

Design: Simba's cross-chip splits are K (output
channels) and C (input channels) -- structurally the matmul M-split /
C-split our traffic algebra already models -- plus P (output rows) in some
configurations [JSSC'20 §III-B: "each package operates on four segments of
P in parallel"]. The conv dims R,S,P,Q enter the VOLUME numbers, not the
edge structure. So a conv layer is expressed directly as a
traffic.TrafficStructure built in closed form: no mapper, no Timeloop
counters (those are ReRAM-macro components), config + assignment only.

Volume semantics -- the im2col trap: expanding
inputs im2col-style would count each input value up to R*S times (~9x for
3x3 layers), an OVERcount violating the declared underestimate direction.
Input volumes here are TOUCHED-extent volumes: the unique input values a
tile's receptive fields actually cover.
    touched rows = min((P-1)*stride + R, P*R) - 2*pad
(contiguous span when stride <= R, disjoint strips when stride > R; the
pad term removes phantom padding rows, which are never transmitted). For
every 1x1 layer this equals P*Q*C exactly (im2col and touched coincide);
for 3x3 pad-1 unsplit-in-P it equals the real feature map exactly.
Spatial (P/Q) splitting is supported only where it stays exact -- R=S=1,
pad=0 tiles are disjoint; a halo-carrying combination (R>1 with a P/Q
split) raises, since its per-tile volume convention is not defined.

Layer shapes are the standard ResNet-50 architecture (He et al.,
arXiv:1512.03385, Table 1) -- the Simba papers name the layers but do not
restate their dimensions. Weights are preloaded and resident (MICRO'19
§4.1); conv has no dynamic-write terms.
"""
import os
from dataclasses import dataclass
from typing import Dict, Optional

from scripts.traffic import LevelSplit, TrafficStructure, _prod

_SIMBA_YAML = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "models", "fabric", "simba.yaml")


def simba_fabric():
    """The Simba fabric (models/fabric/simba.yaml)."""
    from scripts import fabric as fabric_mod
    return fabric_mod.from_yaml(_SIMBA_YAML)


def _touched(extent_out: int, stride: int, r: int, pad: int) -> int:
    """Unique input rows (or cols) covered by `extent_out` output positions.

    Known edge: for stride > 1 WITH padding the formula is off by one
    against the real map (3x3 s2 pad1 on a 28-row map gives 27 for the true
    28), so that combination raises like the halo case does; no layer used
    here needs it."""
    if stride > 1 and pad > 0:
        raise NotImplementedError(
            "touched-extent for stride>1 with pad>0 is off-by-one against "
            "the real map; such a layer is not supported")
    return min((extent_out - 1) * stride + r, extent_out * r) - 2 * pad


@dataclass(frozen=True)
class ConvOp:
    """One conv layer, batch 1. P, Q = output spatial dims."""
    name: str
    K: int          # output channels
    C: int          # input channels
    R: int = 1      # filter height
    S: int = 1      # filter width
    P: int = 1      # output height
    Q: int = 1      # output width
    stride: int = 1
    pad: int = 0    # symmetric spatial padding (3x3 layers use 1)

    @property
    def macs(self) -> int:
        return self.K * self.C * self.R * self.S * self.P * self.Q

    @property
    def input_words(self) -> int:
        """Unique IA values the whole layer needs delivered (8-bit words)."""
        return (_touched(self.P, self.stride, self.R, self.pad)
                * _touched(self.Q, self.stride, self.S, self.pad) * self.C)

    @property
    def output_words(self) -> int:
        return self.P * self.Q * self.K

    @property
    def weight_words(self) -> int:      # resident, no per-inference flow
        return self.K * self.C * self.R * self.S

    def im2col_input_words(self) -> int:
        """What im2col expansion WOULD count (equals input_words exactly iff
        R = S = 1); for comparison, never used as a volume."""
        return self.P * self.Q * self.C * self.R * self.S


def _r50(name, K, C, R, S, P, Q, stride=1):
    return ConvOp(name, K=K, C=C, R=R, S=S, P=P, Q=Q, stride=stride,
                  pad=R // 2)


# The layers the three targets and the JSSC reference table name.
# Stages (He et al. Table 1): conv2_x at 56x56, conv3_x 28x28, conv4_x
# 14x14, conv5_x 7x7; branch1 = the stage-entry projection shortcut
# (1x1, stride 2 from res3 on); branch2a/2b/2c = the bottleneck 1x1 /
# 3x3 / 1x1.
RESNET50 = {
    # -- target 1 (Fig 9) and JSSC Fig 18: conv4's projection shortcut
    "res4a_branch1":        _r50("res4a_branch1", K=1024, C=512, R=1, S=1, P=14, Q=14, stride=2),
    # -- target 3 (Fig 7) three classes + target 2 (Fig 15) top bars
    "res2[a-c]_branch2b":   _r50("res2[a-c]_branch2b", K=64, C=64, R=3, S=3, P=56, Q=56),
    "res3a_branch1":        _r50("res3a_branch1", K=512, C=256, R=1, S=1, P=28, Q=28, stride=2),
    "res5[a-c]_branch2b":   _r50("res5[a-c]_branch2b", K=512, C=512, R=3, S=3, P=7, Q=7),
    "res2[a-c]_branch2c":   _r50("res2[a-c]_branch2c", K=256, C=64, R=1, S=1, P=56, Q=56),
    # -- Fig 6 (mapping sensitivity) uses conv4's branch2a
    "res4[b-f]_branch2a":   _r50("res4[b-f]_branch2a", K=256, C=1024, R=1, S=1, P=14, Q=14),
}

# JSSC'20 §V-E reconciliation note (recorded, not forced): the text calls
# res4a_branch1 "128-million MACs", Fig 18's one-chip compute bar is
# 114,688 PE cycles x 1,024 MACs/cycle = 117.4M, and the He-Table-1 shape
# gives 14*14*512*1024 = 102.8M. Same layer, three tellings within ~15% --
# the gaps come from edge / padding conventions and prose rounding. The
# volumes here follow the He-Table-1 shapes; the deltas are recorded, not
# patched over.
RES4A_BRANCH1_MACS = RESNET50["res4a_branch1"].macs        # 102,760,448


# ---------------------------------------------------------------- structure
def conv_structure(op: ConvOp, die_split: Dict[str, int],
                   pe_split: Optional[Dict[str, int]] = None,
                   fabric=None) -> TrafficStructure:
    """The closed-form TrafficStructure for `op` under an explicit spatial
    split -- the reproduction never asks a mapper for these.

    die_split / pe_split: dim -> factor, dims in {K, C, P, Q}. K maps to
    the structure's M role (input multicast), C to reduction, P/Q to pure
    partition -- traffic.py's own classification tables, unchanged.

    in_leaf is the touched-extent input tile per leaf (module docstring);
    out_leaf the leaf's output values (partial sums when C is split --
    width handled downstream by psum_word_bytes = 3 on this fabric).
    """
    fab = fabric or simba_fabric()
    pe_split = {d: f for d, f in dict(pe_split or {}).items() if f > 1}
    die_split = {d: f for d, f in dict(die_split).items() if f > 1}
    for where, split, level in (("die", die_split, "die"),
                                ("pe", pe_split, "macro")):
        bad = set(split) - {"K", "C", "P", "Q"}
        if bad:
            raise ValueError(f"{where} split has unsupported dims {sorted(bad)}")
        n = _prod(split.values()) if split else 1
        if n > fab.level(level).per_parent:
            raise ValueError(f"{where} split spans {n} instances; the fabric "
                             f"level '{level}' has {fab.level(level).per_parent}")
        for d, f in split.items():
            size = {"K": op.K, "C": op.C, "P": op.P, "Q": op.Q}[d]
            if size % f:
                raise ValueError(f"{where} split: {d}={size} does not divide "
                                 f"by factor {f}")
    total = {d: 1 for d in ("K", "C", "P", "Q")}
    for split in (die_split, pe_split):
        for d, f in split.items():
            total[d] *= f
    if (total["P"] > 1 or total["Q"] > 1) and (op.R > 1 or op.S > 1):
        raise NotImplementedError(
            "P/Q spatial split on an R>1/S>1 layer carries halos; its "
            "per-tile volume convention is not defined")

    def as_level(name, split):
        # rename K->M so traffic.py's dim tables classify it (M = multicast)
        return LevelSplit(name, {("M" if d == "K" else d): f
                                 for d, f in split.items()})

    splits = ([as_level("die", die_split)] if die_split else []) \
        + ([as_level("macro", pe_split)] if pe_split else [])

    p_tile, q_tile = op.P // total["P"], op.Q // total["Q"]
    in_leaf = (_touched(p_tile, op.stride, op.R, op.pad if total["P"] == 1 else 0)
               * _touched(q_tile, op.stride, op.S, op.pad if total["Q"] == 1 else 0)
               * (op.C // total["C"]))
    out_leaf = p_tile * q_tile * (op.K // total["K"])
    return TrafficStructure(splits=splits, in_leaf=in_leaf, out_leaf=out_leaf,
                            tensor_in=op.input_words, tensor_out=op.output_words)


def compute_seconds(op: ConvOp, n_chiplets: int, fabric=None,
                    macs_per_chiplet_cycle: int = None) -> float:
    """Compute time of the split layer: assigned MACs at the equivalent
    throughput, utilization 1.0 -- part of the declared optimistic lower
    bound (Simba's own 1-chip run measured 63% utilization, JSSC'20 §V-E)."""
    from scripts import reference_hardware as anchors
    if macs_per_chiplet_cycle is None:
        macs_per_chiplet_cycle = anchors.SIMBA_MACS_PER_CHIPLET_CYCLE
    fab = fabric or simba_fabric()
    cycles = op.macs / (n_chiplets * macs_per_chiplet_cycle)
    return cycles * fab.device.cycle_seconds
