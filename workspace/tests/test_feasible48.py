"""Group 18 -- the feasible 48-die configuration's D2D chain, pinned (O18).

Group 15 pins the D2D MECHANISM identities on a reference package; group 17
pins the on-die anchored findings on the v2 (co-residency) fixture. What was
still unpinned -- the upgrade-protocol gap O18 names -- are the published
NUMBERS of the feasible 48-die chain itself: the half-layer pipeline stages
(scenarios A and B), the busiest-wire integers of the 6x8 chain, the surplus
energies, the pipelined knees, and the offload dividend. This file pins them,
recomputing everything through the SAME committed functions the analysis
scripts call (llm_workload / crossbar_comm on mlx300_multidie48.yaml), with
per-op bases from the frozen v2 fixture.

It also pins the cross-script CONVENTION: analyze_d2d.py and
analyze_offload_contention.py must derive identical stages and busiest-wire
integers from the same inputs (the 24-vs-48 leftover in the offload script's
D2D table -- integers 6/23, whole-layer stages -- was found and fixed under
O18; this group is the regression guard).
"""
import os

from _util import approx, golden

from scripts import fabric, placement
from scripts import llm_workload as lw
import scripts.crossbar_comm as cc
from scripts.analyze_d2d import assignments, with_link, UNITS
from scripts.analyze_offload_contention import half_stages

MULTI48 = "/home/workspace/models/fabric/mlx300_multidie48.yaml"
CYC = 1.449e-6
S = 512
CFG = lw.GptConfig()
WORDS = S * CFG.d_model                      # one prefill boundary hand-off
UCFG = lw.GptConfig(d_model=CFG.d_model, n_heads=CFG.n_heads, d_ff=CFG.d_ff,
                    n_layers=UNITS, name="units48")

FIX = golden("stack_per_op_v2.json")
PER_PRE = FIX["phases"]["prefill"]["per_op"]["star (private links)"]
PER_DEC = FIX["phases"]["decode"]["per_op"]["star (private links)"]

# ---- the pinned published numbers (v2 basis, feasible 48-die config) ----
STAGE_A_S = 0.02349312          # slower half-layer, attention die (+K/V write)
STAGE_B_S = 0.01038336          # offloaded: both halves 2 ops = 10.38 ms
DIVIDEND = 2.2625739644970415   # stage_A / stage_B = +126% throughput
# full-duplex mesh (O22): the row wrap and the adversarial back-routes ride
# the opposite-direction wires -- sequential rows 2 -> 1, far pairs 8 -> 4
BUSIEST = {"snake": 1, "sequential rows": 1, "far pairs (adversarial)": 4}
BUSIEST_SHARED = {"snake": 1, "sequential rows": 2,      # pre-O22 accounting
                  "far pairs (adversarial)": 8}
BUS_BOUNDARIES = UNITS - 1      # 47: every hand-off shares the one medium
SURPLUS_UJ = {"snake": 0.0, "sequential rows": 183.5008,
              "far pairs (adversarial)": 1368.39168}
KNEES_A = {"snake": 32, "sequential rows": 32,
           "far pairs (adversarial)": 128, "bus": 1024}   # degrades below, w/c
HALVES_A = {"snake": 16, "sequential rows": 16,
            "far pairs (adversarial)": 64, "bus": 512}    # halves below, w/c


def _fab(bw=256.0, topology="mesh", params=None):
    base = fabric.from_yaml(MULTI48)
    return with_link(base, topology,
                     params if params is not None
                     else {"routing": "xy", "hub": "center"}, bw)


# ------------------------------------------------ 1. the two stages
def test_stage_A_is_the_attention_half_layer():
    """Scenario A stage = slower half of a layer. On the v2 basis all six
    computes are 5.192 ms, so the attention die (4 ops + the K/V write)
    dominates the FFN die (2 ops): 23.49312 ms exactly."""
    stage_A, _ = half_stages(PER_PRE)
    attn = sum(o["compute_s"] + o["write_s"] for o in PER_PRE
               if o["name"] in ("qkv_proj", "qk^t", "av", "out_proj"))
    approx(stage_A, attn, 1e-12)
    approx(stage_A, STAGE_A_S, 1e-12)


def test_stage_B_and_the_offload_dividend():
    """Scenario B: qk^t/av and the write leave; both halves hold two 5.192 ms
    ops -> 10.38336 ms, and the pipelined dividend is stage_A/stage_B =
    2.263 (+126%). NOT +53% (v1 exclusive-die basis) and NOT +13% (a
    briefly-published mix of the half-layer A stage with a whole-layer B
    stage -- the convention mismatch this group exists to prevent)."""
    stage_A, stage_B = half_stages(PER_PRE)
    approx(stage_B, STAGE_B_S, 1e-12)
    approx(stage_A / stage_B, DIVIDEND, 1e-9)


def test_decode_stage_B():
    """Decode under B: two ~10.14 us computes per die half -> 20.28 us; a
    sequential-rows boundary at 64 w/c beats at 46.4 us -> 2.29x, decode's
    D2D becomes touchable for the first time."""
    _, stage_dB = half_stages(PER_DEC)
    two_ops = sum(o["compute_s"] for o in PER_DEC
                  if o["name"] in ("ffn1", "ffn2"))
    approx(stage_dB, two_ops, 1e-12)
    beat = 2 * CFG.d_model / 64.0 * CYC
    approx(beat / stage_dB, 2.2864, 1e-3)


# ------------------------------------------------ 2. chain integers
def test_busiest_wire_integers_on_the_6x8_chain():
    """The 48-unit chain on the 6x8 package, full-duplex wires (O22): snake
    and sequential rows both keep every hand-off on a private wire (the
    row wrap walks back on the opposite-direction wires), the adversarial
    far-pairs order piles 4 onto one wire. On the pre-O22 shared-direction
    accounting the same chain reads 1 / 2 / 8 -- still reproducible on
    request, and pinned so the change stays auditable."""
    fab = _fab()
    pl = placement.sequential_fill(fab)
    for label, asg in assignments(fab):
        d = lw.die_to_die_activation(UCFG, S, "prefill", fabric=fab,
                                     assignment=asg)
        occ = cc.link_occupancy(d["flows"], fab, CYC, pl)
        assert occ["bottleneck"]["volume"] / WORDS == BUSIEST[label], label
        occ = cc.link_occupancy(d["flows"], fab, CYC, pl, duplex=False)
        assert occ["bottleneck"]["volume"] / WORDS == BUSIEST_SHARED[label], \
            label


def test_bus_carries_every_boundary():
    """On the shared interposer every one of the 47 hand-offs crosses the one
    medium -- the 47x beat multiplier in the network-bound regime."""
    fab = _fab(topology="bus", params={"driver": "center"})
    d = lw.die_to_die_activation(UCFG, S, "prefill", fabric=fab,
                                 assignment=list(range(UNITS)))
    occ = cc.link_occupancy(d["flows"], fab, CYC,
                            placement.sequential_fill(fab))
    assert occ["bottleneck"]["volume"] / WORDS == BUS_BOUNDARIES


def test_surplus_energy_per_assignment():
    """Replace-never-add: snake (all-adjacent) bills zero surplus; the other
    assignments bill exactly their extra hops at the flat per-word price."""
    fab = _fab()
    for label, asg in assignments(fab):
        d = lw.die_to_die_activation(UCFG, S, "prefill", fabric=fab,
                                     assignment=asg)
        if SURPLUS_UJ[label] == 0.0:
            assert d["energy_J"] == 0.0
        else:
            approx(d["energy_J"] * 1e6, SURPLUS_UJ[label], 1e-9)


# ------------------------------------------------ 3. knees (pipelined, A)
def _pipe_mult(bw, topology, params, asg, stage):
    fab = _fab(bw, topology, params)
    d = lw.die_pipeline_interval(UCFG, S, "prefill", stage, fabric=fab,
                                 assignment=asg, cycle_seconds=CYC)
    return d["interval_s"] / stage


def test_pipelined_knees_scenario_A():
    """The published integers: throughput leaves the compute-bound plateau
    below 32/32/128/1024 w/c (snake/sequential/far-pairs/bus) and halves
    below 16/16/64/512. Grid of powers of two -- exact, not approximate."""
    stage = STAGE_A_S
    fab0 = _fab()
    cases = [(lbl, "mesh", {"routing": "xy", "hub": "center"}, asg)
             for lbl, asg in assignments(fab0)]
    cases.append(("bus", "bus", {"driver": "center"}, list(range(UNITS))))
    sweep = [float(2 ** k) for k in range(0, 15)]
    for lbl, topo, params, asg in cases:
        ys = [_pipe_mult(bw, topo, params, asg, stage) for bw in sweep]
        k1 = max((bw for bw, y in zip(sweep, ys) if y >= 1.01), default=None)
        k2 = max((bw for bw, y in zip(sweep, ys) if y >= 2.0), default=None)
        assert k1 == KNEES_A[lbl], (lbl, "degrades", k1)
        assert k2 == HALVES_A[lbl], (lbl, "halves", k2)


def test_offload_doubles_every_knee():
    """Scenario B halves the stage (23.49 -> 10.38 ms is a factor 2.26; on
    the power-of-two grid every knee lands exactly one octave higher):
    64/64/256/2048 w/c. The offload script's B table must agree."""
    stage = STAGE_B_S
    fab0 = _fab()
    cases = [(lbl, "mesh", {"routing": "xy", "hub": "center"}, asg)
             for lbl, asg in assignments(fab0)]
    cases.append(("bus", "bus", {"driver": "center"}, list(range(UNITS))))
    sweep = [float(2 ** k) for k in range(0, 15)]
    for lbl, topo, params, asg in cases:
        ys = [_pipe_mult(bw, topo, params, asg, stage) for bw in sweep]
        k1 = max((bw for bw, y in zip(sweep, ys) if y >= 1.01), default=None)
        assert k1 == 2 * KNEES_A[lbl], (lbl, k1)


# ------------------------------------------------ 4. operating points
def test_single_pass_is_invisible_at_the_example_point():
    """At 256 w/c every assignment's hand-offs (2.97 ms each on snake) hide
    behind the stack's 747.6 ms of compute: single-pass total == stall-free
    for all three mesh assignments."""
    sf = FIX["phases"]["prefill"]["stall_free_s"]
    comp = sum(o["compute_s"] for o in PER_PRE) * CFG.n_layers
    fab = _fab(256.0)
    pl = placement.sequential_fill(fab)
    for label, asg in assignments(fab):
        d = lw.die_to_die_activation(UCFG, S, "prefill", fabric=fab,
                                     assignment=asg)
        occ = cc.link_occupancy(d["flows"], fab, CYC, pl)
        assert occ["serialization_s"] <= comp, label
    approx(sf, 0.813055104, 1e-9)


def test_pipelined_beats_at_64_wpc():
    """The example-input column of the published tables, both scenarios
    (full-duplex integers 1/1/4/47):
    A: snake 1.00, sequential 1.00, far pairs 2.02, bus 23.75;
    B: snake 1.14, sequential 1.14, far pairs 4.57, bus 53.73 -- the
    offload thins the compute margin, so every multiplier grows."""
    wire = WORDS / 64.0 * CYC                       # 11.87 ms per boundary
    for stage, expect in (
            (STAGE_A_S, {1: 1.0, 4: 2.0211, 47: 23.7474}),
            (STAGE_B_S, {1: 1.1432, 4: 4.5728, 47: 53.7302})):
        for b, m in expect.items():
            approx(max(stage, b * wire) / stage, m, 1e-3)


# -------------------------------------------------- O7 bracket, die level
def test_pipeline_interval_returns_both_bracket_ends():
    """die_pipeline_interval exposes the O7 bracket one level up:
    interval_s = max(stage, wire) is the perfect-overlap beat,
    interval_sum_s = stage + wire the zero-overlap beat. At 64 w/c on the
    far-pairs assignment (4 boundaries on the busiest full-duplex wire):
    [2.02, 3.02] x the compute-bound beat -- in the network-bound regime
    the bracket ends differ by exactly one stage."""
    fab = _fab(64.0)
    far = dict(assignments(fab))["far pairs (adversarial)"]
    d = lw.die_pipeline_interval(UCFG, S, "prefill", STAGE_A_S, fabric=fab,
                                 assignment=far, cycle_seconds=CYC)
    approx(d["interval_s"] / STAGE_A_S, 2.0211, 1e-3)
    approx(d["interval_sum_s"] / STAGE_A_S, 3.0211, 1e-3)
    approx(d["interval_sum_s"] - d["interval_s"], STAGE_A_S, 1e-9)


def test_bracket_collapses_when_network_free():
    """With no die bandwidth set both ends equal the compute stage -- the
    off-by-default discipline holds for the sum end too."""
    d = lw.die_pipeline_interval(UCFG, S, "prefill", STAGE_A_S,
                                 cycle_seconds=CYC)
    assert d["interval_s"] == STAGE_A_S
    assert d["interval_sum_s"] == STAGE_A_S
