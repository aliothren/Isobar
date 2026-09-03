"""Group 31 -- the Simba reproduction preset (C41, worklist step 1, day 2).

The preset expresses NVIDIA's 36-chiplet MCM prototype in our fabric schema
at the papers' EXPERIMENT operating point (MICRO'19 §4.1: 0.72 V, 1.03 GHz,
GRS 11 Gb/s mode). Everything pinned here is verbatim-sourced in
analysis/papers/simba_extracts.md and frozen by analysis/SIMBA_PREREG.md --
these tests are the freeze: a drift in any parameter is a red suite, and
fixing it by editing the pin requires a changelog entry, never a quiet edit.

Also pinned: the C41 device-class contract -- the verify_cycle bypass is
keyed on the EXPLICIT device_class field only, the default fabric keeps the
hard reconciliation, and a typo'd class refuses to load.
"""
import os

from _util import approx

from scripts import anchors, fabric

HERE = os.path.dirname(os.path.abspath(__file__))
SIMBA_YAML = os.path.join(HERE, "..", "models", "fabric", "simba.yaml")


def _simba():
    return fabric.from_yaml(SIMBA_YAML)


# ------------------------------------------------------------ geometry pins
def test_simba_geometry():
    f = _simba()
    assert f.name == "simba-repro"
    die = f.level("die")
    assert die.per_parent == 36 and die.mesh == (6, 6)          # MICRO'19 Tab 2
    pe = f.level("macro")                                        # PE <-> macro
    assert pe.per_parent == 16 and pe.mesh == (4, 5)             # 16 PEs on 4x5 NoC
    # 4 spare NoC slots = Global PE's 3 router stops + RISC-V = 20 endpoints
    assert pe.mesh[0] * pe.mesh[1] - pe.per_parent == 4          # JSSC'20 §II-C
    assert f.count_below("die") == 36
    assert f.count_below("macro") == 36 * 16                     # 576 PEs
    assert f.grid_shape() == (6 * 4, 6 * 5)                      # 24 x 30 leaf grid


def test_simba_link_pins():
    f = _simba()
    nop, noc = f.level("die").link, f.level("macro").link
    assert nop.topology == "mesh" and nop.params["routing"] == "xy"  # §4.1 X-Y
    assert noc.topology == "mesh" and noc.params["routing"] == "xy"
    approx(nop.ns_per_hop, 20.0, 1e-12)                          # Tab 2
    approx(noc.ns_per_hop, 10.0, 1e-12)                          # Tab 2
    # bandwidths at the EXPERIMENT point, converted at the 1.03 GHz cycle:
    # NoP 5.5 GB/s (11 Gb/s mode), NoC 8.75 GB/s (70 Gb/s @ 0.72 V)
    approx(nop.bandwidth_words_per_cycle,
           anchors.SIMBA_EXPERIMENT_GRS_GBPS * 1e9 / anchors.SIMBA_EXPERIMENT_PE_HZ, 1e-9)
    approx(noc.bandwidth_words_per_cycle,
           anchors.SIMBA_EXPERIMENT_NOC_GBPS * 1e9 / anchors.SIMBA_EXPERIMENT_PE_HZ, 1e-9)
    approx(nop.bandwidth_words_per_cycle, 5.33980582524, 1e-9)
    approx(noc.bandwidth_words_per_cycle, 8.49514563107, 1e-9)
    # GRS energy convention: 10 pJ/word midpoint of 0.82-1.75 pJ/bit (JSSC §V-B)
    approx(nop.pj_per_word, 10.0, 1e-12)
    assert noc.pj_per_word == 0.0                                # honestly uncharged


def test_simba_device_and_throughput():
    f = _simba()
    assert f.device.device_class == "digital_throughput"
    approx(f.device.cycle_seconds, 1.0 / anchors.SIMBA_EXPERIMENT_PE_HZ, 1e-12)
    assert f.device.input_slices_per_mvm == 1
    # closed-form peak at the experiment point: 1,024 MACs/chiplet/cycle
    # x 1.03 GHz x 2 ops = 2.11 TOPS/chiplet [Tab 2 / JSSC Tab I derivation]
    tops = (anchors.SIMBA_MACS_PER_CHIPLET_CYCLE / f.device.cycle_seconds) * 2 / 1e12
    approx(tops, 2.10944, 1e-4)
    # ... and 4 TOPS/chiplet at the 2 GHz max point [MICRO'19 §3.2], the
    # published headline the derivation must be consistent with
    approx(anchors.SIMBA_MACS_PER_CHIPLET_CYCLE * 2.0e9 * 2 / 1e12, 4.096, 1e-3)
    # partial sums are 24-bit on Simba wires = 3 words (Tab 2, O23 convention)
    approx(f.psum_word_bytes, 3.0, 1e-12)
    assert f.schedule_slack == 1.0


# ------------------------------------------------------ C41 bypass contract
def test_verify_cycle_bypassed_only_for_digital_class():
    f = _simba()
    # digital_throughput: no macro to reconcile -- any run cycle is accepted
    f.verify_cycle(123.456)  # must not raise
    # the default (ReRAM) fabric keeps the hard check
    g = fabric.default()
    assert g.device.device_class == "reram_macro"
    try:
        g.verify_cycle(g.device.cycle_seconds * 1.5)
    except ValueError:
        pass
    else:
        raise AssertionError("reram_macro fabric accepted a diverged cycle")
    g.verify_cycle(g.device.cycle_seconds)  # exact value still passes


def test_device_class_typo_refuses_to_load():
    from scripts.fabric import Device, Fabric, Level
    bad = Fabric(name="typo", levels=[Level(name="die")],
                 device=Device(device_class="digital"))  # not in the whitelist
    try:
        bad.validate()
    except ValueError as e:
        assert "device_class" in str(e)
    else:
        raise AssertionError("typo'd device_class validated")


def test_provenance_carries_device_class():
    p = fabric.provenance(_simba())
    assert p["device"]["device_class"] == "digital_throughput"
    assert fabric.provenance(fabric.default())["device"]["device_class"] == "reram_macro"


# ------------------------------------------------- registry constants (C41)
def test_operating_point_constants_are_not_anchor_columns():
    """5.5 is an operating point, not a capability anchor: the D2D readout
    columns must stay exactly the pinned set (12.5 / 64 / 0.1 / 2.0)."""
    approx(anchors.SIMBA_EXPERIMENT_GRS_GBPS, 5.5, 1e-12)
    approx(anchors.SIMBA_EXPERIMENT_NOC_GBPS, 8.75, 1e-12)
    vals = [c[2] for c in anchors.columns("d2d")]
    assert vals == [12.5, 64.0, 0.1, 2.0], vals


# ------------------------------------------------------ chip point (C47)
def test_simba_chip_point_and_mark_exclusion():
    """C47: Simba is the first DIGITAL chip point -- t derived from the
    C41 equivalent-throughput device (497 ns per input row through a
    PE's resident 32 KiB), on-die coordinate 560 GB/s per the C37
    aggregation (2 PEs = one 256x256-array equivalent), D2D 12.5 max.
    It must NOT join device_marks(): the r=1 machinery stays the four
    analog marks."""
    sb = anchors.chip("simba")
    assert sb.paradigm == "digital" and sb.tier == "mesh"
    approx(sb.t_mvm_s, 2 * 32768 / (128 * 1.03e9), 1e-12)
    approx(sb.t_mvm_s, 497.09e-9, 1e-3)
    approx(sb.ondie_gbps, 560.0, 1e-12)
    approx(sb.ondie_gbps_per_link, 8.75, 1e-12)
    approx(sb.d2d_gbps, 12.5, 1e-12)
    marks = {c.key for c in anchors.device_marks()}
    assert marks == {"neurram", "mythic_m1076", "isaac", "hermes"}
