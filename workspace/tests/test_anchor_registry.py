"""Group 23 -- the anchor registry and the per-axis sweeps (O25).

Pins: (1) the registry's identity -- the digital anchors keep their published
values and statuses, the analog-reality tier is a BAND marked `estimated`
with a derivation, every chip point carries a status per coordinate;
(2) one bandwidth constant -- no anchor-printing script defines its own
anchors or device cycle; (3) the GB/s <-> words/cycle conversion;
(4) the per-axis sweep readouts (analysis/phase_sweep.json, sweep_axes.py)
at both paradigms' columns: the digital columns reproduce the v5 pins
(group 17), the analog-reality columns are the new readouts, and the
thresholds are the exact crossings (bisection) rather than 2^k grid points.
"""
import json
import os
import re

from _util import approx

from scripts import anchors as an

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
SWEEP = json.load(open(os.path.join(WS, "analysis", "phase_sweep.json")))
SCHEMES = ["star (private links)", "mesh, glb centre", "mesh, glb corner",
           "h-tree (k=4)", "bus (shared medium)"]


# ------------------------------------------------------------- the registry
def test_digital_anchors_keep_their_published_values():
    assert an.by_key("simba_ondie").gbps == 8.75 and an.by_key("simba_ondie").status == "measured"
    # C36: the ESP anchor is primary-sourced (Jia et al., ESSCIRC 2022): 5 data
    # planes x 64 bit at a measured 800 MHz = 32 GB/s tile-to-tile; the paper's
    # own headline (281 Gb/s) adds the 32-bit control plane; a single plane is
    # 6.4 GB/s -- the multi-plane aggregate is stated in the derivation
    assert an.by_key("esp").gbps == 32.0 and an.by_key("esp").status == "measured"
    assert "ESSCIRC" in an.by_key("esp").source and "6.4 GB/s" in an.by_key("esp").derivation
    assert an.by_key("floonoc").gbps == 80.6 and an.by_key("floonoc").status == "post-layout"
    assert an.by_key("grs").gbps == 12.5 and an.by_key("grs").status == "measured"
    # C40: the UCIe-S anchor is a SPEC ceiling (an interconnect standard, not a
    # measured chip) -- its own status class, stated in the source
    assert an.by_key("ucie").gbps == 64.0 and an.by_key("ucie").status == "spec"
    assert "STANDARD" in an.by_key("ucie").source and "32 GT/s" in an.by_key("ucie").derivation
    for a in an.ANCHORS:
        if a.paradigm == an.DIGITAL:
            assert a.gbps is not None and a.band is None and a.source


def test_analog_reality_tier_is_an_estimated_band_with_a_derivation():
    for level, lo, hi in ((an.ONDIE, 0.4, 8.0), (an.D2D, 0.1, 2.0)):
        b = an.band(level)
        assert b.paradigm == an.ANALOG and b.status == "estimated"
        assert b.band == (lo, hi) and b.gbps is None and b.derivation
    # every readout column set = the digital anchors first, then the band ends
    cols = an.columns(an.ONDIE)
    assert [c[0] for c in cols] == ["simba_ondie", "esp", "floonoc", "analog_ondie_low", "analog_ondie_high"]
    assert [c[2] for c in an.columns(an.D2D)] == [12.5, 64.0, 0.1, 2.0]   # UCIe since C40


def test_chip_points_carry_a_status_per_coordinate():
    keys = {c.key for c in an.CHIPS}
    assert {"neurram", "hermes", "isaac", "mx100", "mythic_m1076", "tsinghua_multichip"} <= keys
    approx(an.chip("neurram").t_mvm_s, 10.14e-6, 1e-9)
    assert an.chip("neurram").t_mvm_status == "measured"
    approx(an.chip("hermes").t_mvm_s, 63.1e12 ** -1 * 64 * 2 * 256 * 256, 1e-9)
    assert an.chip("hermes").t_mvm_status == "derived" and an.chip("hermes").t_mvm_derivation
    approx(an.chip("isaac").t_mvm_s, 1.6e-6, 1e-9)
    # C36: Mythic derived (25 TOPS / 76 tiles / 2*1024*1024 = 6.375 us) -- a
    # TOPS-derived per-TOKEN row time is tile-shape invariant, so no
    # array-height folding (the C37 adjudication). C37: HERMES's PUBLISHED
    # 0.4 GB/s is per PHYSICAL link (the analog band's low end); the
    # COORDINATE aggregates to our per-macro-link granularity (32 arrays):
    # (418/64) x 0.4 x 32 ~= 83.6 GB/s. MX100 stays pending, blocked on the
    # source (no published rate as of 2026-09-01).
    approx(an.chip("mythic_m1076").t_mvm_s, 25e12 ** -1 * 76 * 2 * 1024 * 1024, 1e-9)
    assert an.chip("mythic_m1076").t_mvm_status == "derived"
    approx(an.chip("hermes").ondie_gbps_per_link, 0.4, 1e-12)
    approx(an.chip("hermes").ondie_gbps_per_link, an.band(an.ONDIE).band[0], 1e-12)
    approx(an.chip("hermes").ondie_gbps, 32 * (418.0 / 64) * 0.4, 1e-12)
    assert an.chip("hermes").ondie_status.startswith("derived (C37 normalization)")
    assert "granularity mismatch" in an.ChipPoint.__doc__
    assert an.chip("mx100").t_mvm_s is None
    for c in an.CHIPS:
        assert c.tier in ("hub-io", "bus-T1", "star", "mesh")
        assert c.t_mvm_status in ("measured", "derived", "design-point") or c.t_mvm_status.startswith("pending")
        if c.t_mvm_s is None:
            assert c.t_mvm_status.startswith("pending")
        if c.ondie_band is not None:
            assert c.ondie_status.startswith("estimated")


def test_hermes_self_consistency_audit():
    """V0 (C37): from published numbers only -- need per core per token
    (256 INT8 inputs / 133 ns ~= 1.93 GB/s) vs aggregate supply per core
    ((418 links / 64 cores) x 0.4 GB/s ~= 2.61 GB/s). Supply exceeds need
    by ~1.36x: a fabricated analog chip provisioned its fabric just ABOVE
    its own knee -- the first external silicon point validating the knee
    formula, and the refutation of the C36 mis-reading (a fabric 38x under
    its knee could not sustain the measured 63.1 TOPS)."""
    sc = an.hermes_self_consistency()
    approx(sc["need_gbps_per_core"], 1.926, 1e-3)
    approx(sc["supply_gbps_per_core"], 2.6125, 1e-9)
    assert sc["supply_gbps_per_core"] > sc["need_gbps_per_core"]
    approx(sc["headroom"], 1.357, 1e-3)


def test_one_bandwidth_constant():
    """Nothing that prints an anchor defines its own anchors or device cycle."""
    scripts = os.path.join(WS, "scripts")
    consumers = ["analyze_anchored_sweep.py", "analyze_scale_tiers.py", "analyze_corner_flip.py",
                 "analyze_d2d.py", "analyze_offload_contention.py", "sweep_axes.py"]
    for f in consumers:
        src = open(os.path.join(scripts, f)).read()
        assert "from scripts import anchors as an" in src, f
        # the anchor / cycle assignments carry no literal of their own
        assert not re.search(r"^\s*(ANCHORS|NOC|GRS|BAND|CYC|WC_PER_GBPS)\s*=.*\b(8\.75|80\.6|12\.5|32\.0|1\.449|1e9)\b", src, re.M), f
        assert "1.449e-6" not in src and "1.4485714" not in src, f


def test_conversion_identities():
    approx(an.words_per_cycle(1.0), 1e9 * an.CYCLE_S, 1e-12)
    approx(an.gbps_of(an.words_per_cycle(12.5)), 12.5, 1e-12)
    approx(an.CYCLE_S * an.SLICES_PER_MVM, an.T_MVM_S, 1e-12)
    approx(an.gbps_of(16384.0), 11.31, 2e-3)            # the reference input, 16,384 words/cycle
    approx(an.by_key("grs").words_per_cycle()[0], 18107.1, 1e-4)


# ------------------------------------------------------------- the sweeps
def test_sweep_header_and_grids():
    assert set(SWEEP) >= {"fixed", "anchors", "ondie", "d2d_355m", "d2d_2p7b", "d2d_probe",
                          "unit_link", "psum", "t1_hub", "plane"}
    assert SWEEP["fixed"]["S"] == 512 and SWEEP["fixed"]["energy"] == "not swept"
    approx(SWEEP["fixed"]["cycle_s"], an.CYCLE_S, 1e-12)
    g = SWEEP["ondie"]["grid_gbps"]
    assert g[0] == 1e-3 and g[-1] == 1e4 and g == sorted(g) and len(g) >= 57
    for a in an.digital(an.ONDIE):
        assert any(abs(x - a.gbps) < 1e-9 for x in g), a.key          # the anchors are grid points
    assert any(abs(x - an.gbps_of(2 ** 14)) < 1e-9 for x in g)        # so are the 2^k words/cycle points


def test_ondie_digital_columns_reproduce_the_v6_pins():
    """Group 17's v6 anchored table (the 2x4 default, C27), read from the
    sweep's columns: the three routed schemes tie at 1.05x (zero-overlap end,
    Simba) -- on the fill-exact grid centre, corner and tree all put 4
    macros' traffic on the busiest wire."""
    conds = SWEEP["ondie"]["conditions"]
    for title, cond in conds.items():
        for label in SCHEMES:
            for key in ("simba_ondie", "esp", "floonoc"):
                approx(cond["schemes"][label]["columns"][key]["max"], 1.00, 1e-3), (title, label, key)
    pre = conds["prefill, attention on chip"]["schemes"]
    want = {"star (private links)": 1.01, "mesh, glb centre": 1.05, "mesh, glb corner": 1.05,
            "h-tree (k=4)": 1.05, "bus (shared medium)": 1.15}
    for label, v in want.items():
        approx(pre[label]["columns"]["simba_ondie"]["sum"], v, 1e-2)
    approx(conds["decode, attention offloaded"]["schemes"]["bus (shared medium)"]["columns"]["simba_ondie"]["sum"], 1.17, 1e-2)
    approx(pre["bus (shared medium)"]["columns"]["esp"]["sum"], 1.04, 1e-2)
    approx(pre["bus (shared medium)"]["columns"]["floonoc"]["sum"], 1.02, 1e-2)


def test_ondie_analog_reality_column_readouts():
    """The new column: at the low end of the analog-reality band (0.4 GB/s,
    estimated) the bus is 3.3x and the routed schemes 1.31x (all three tie
    on the 2x4 grid) at the perfect-overlap end (prefill on chip); at the
    high end (8 GB/s) every scheme is back to 1.00x."""
    pre = SWEEP["ondie"]["conditions"]["prefill, attention on chip"]["schemes"]
    low = {"star (private links)": 1.00, "mesh, glb centre": 1.31, "mesh, glb corner": 1.31,
           "h-tree (k=4)": 1.31, "bus (shared medium)": 3.33}
    for label, v in low.items():
        approx(pre[label]["columns"]["analog_ondie_low"]["max"], v, 1.5e-2)
        approx(pre[label]["columns"]["analog_ondie_high"]["max"], 1.00, 5e-3)
    order = ["star (private links)", "mesh, glb centre", "h-tree (k=4)", "mesh, glb corner", "bus (shared medium)"]
    vals = [pre[l]["columns"]["analog_ondie_low"]["max"] for l in order]
    assert vals == sorted(vals)                                       # star < centre = h-tree = corner < bus
    approx(vals[1], vals[2], 1e-9) and approx(vals[2], vals[3], 1e-9)   # the 2x4 tie


def test_ondie_thresholds_are_exact_crossings():
    """Bisection thresholds (prefill on chip, perfect-overlap end, 2x4
    default): the 1% crossings 0.195 / 0.782 / 0.782 / 0.782 / 1.89 GB/s and
    the doubling crossings 0.061 / 0.243 / 0.243 / 0.243 / 0.68 GB/s --
    consistent with the 2^k-grid pins of group 17 (routed schemes 1% between
    1,024 and 2,048 w/c, bus between 2,048 and 4,096 w/c)."""
    pre = SWEEP["ondie"]["conditions"]["prefill, attention on chip"]["schemes"]
    one = {"star (private links)": 0.195, "mesh, glb centre": 0.782, "mesh, glb corner": 0.782,
           "h-tree (k=4)": 0.782, "bus (shared medium)": 1.89}
    two = {"star (private links)": 0.0608, "mesh, glb centre": 0.243, "mesh, glb corner": 0.243,
           "h-tree (k=4)": 0.243, "bus (shared medium)": 0.68}
    for label in SCHEMES:
        t = pre[label]["thresholds_gbps"]
        approx(t["max_1pct"], one[label], 2e-2)
        approx(t["max_2x"], two[label], 2e-2)
    assert 2048 < an.words_per_cycle(one["bus (shared medium)"]) < 4096
    assert 1024 < an.words_per_cycle(one["mesh, glb centre"]) < 2048


def test_knee_operator_is_reported_per_condition():
    """prefill on chip: qk^T sets the knee on every point-to-point scheme
    (ffn2 on the bus); with the attention offloaded ffn2 sets it everywhere
    -- the S-independence of the on-die knee holds for the projections only."""
    conds = SWEEP["ondie"]["conditions"]
    pre = conds["prefill, attention on chip"]["schemes"]
    for label in SCHEMES[:4]:
        assert pre[label]["knee_op"] == "qk^t", label
    assert pre["bus (shared medium)"]["knee_op"] == "ffn2"
    for label in SCHEMES:
        assert conds["prefill, attention offloaded"]["schemes"][label]["knee_op"] == "ffn2"
        assert conds["decode, attention offloaded"]["schemes"][label]["knee_op"] == "ffn2"


def test_d2d_355m_readouts_and_ordering():
    d = SWEEP["d2d_355m"]["conditions"]
    on, off = d["prefill, attention on chip"]["variants"], d["prefill, attention offloaded"]["variants"]
    approx(on["snake"]["busiest_boundaries"], 1.0, 1e-9)
    approx(on["far pairs (adversarial)"]["busiest_boundaries"], 4.0, 1e-9)
    approx(on["bus (shared interposer)"]["busiest_boundaries"], 47.0, 1e-9)
    for v in list(on.values()) + list(off.values()):
        approx(v["columns"]["grs"]["pipe"], 1.00, 1e-3)               # GRS: hidden, both conditions
        approx(v["columns"]["grs"]["single"], 1.00, 1e-3)
    approx(on["bus (shared interposer)"]["columns"]["analog_d2d_low"]["pipe"], 10.35, 1e-2)
    approx(off["snake"]["columns"]["analog_d2d_low"]["pipe"], 17.76, 1e-2)
    approx(off["bus (shared interposer)"]["columns"]["analog_d2d_high"]["pipe"], 3.53, 1e-2)
    for cond in (on, off):
        for key in ("analog_d2d_low", "analog_d2d_high"):
            s, q, a, b = (cond[l]["columns"][key]["pipe"] for l in
                          ("snake", "sequential rows", "far pairs (adversarial)", "bus (shared interposer)"))
            assert s <= a + 1e-9 and a <= b + 1e-9 and q <= b + 1e-9, key
    approx(on["bus (shared interposer)"]["thresholds_gbps"]["pipe_1pct"], 1.02, 2e-2)


def test_d2d_355m_scaling_identity():
    """The harness scales one occupancy as 1/bandwidth; recompute one point
    directly through link_occupancy at another bandwidth."""
    from scripts import fabric as fabric_mod, llm_workload as lw, placement as pm
    import scripts.crossbar_comm as cc
    from scripts.analyze_d2d import MULTI, UCFG, S, assignments, with_link
    base = fabric_mod.from_yaml(MULTI)
    v = SWEEP["d2d_355m"]["conditions"]["prefill, attention on chip"]["variants"]["far pairs (adversarial)"]
    asg = dict(assignments(base))["far pairs (adversarial)"]
    wc = 4096.0
    fab = with_link(base, "mesh", {"routing": "xy", "hub": "center"}, wc)
    d = lw.die_to_die_activation(UCFG, S, "prefill", fabric=fab, assignment=asg)
    occ = cc.link_occupancy(d["flows"], fab, an.CYCLE_S, pm.sequential_fill(fab))
    approx(occ["serialization_s"], v["serial_ref_s"] * v["ref_wc"] / wc, 1e-9)


def test_d2d_2p7b_chain_thresholds_and_columns():
    """The 2.7B chain (O13) on the D2D axis, on-die unlimited: at GRS 1.00x
    for every seating; in the analog-reality D2D tier 4.9-7.0x at 0.1 GB/s
    and 1.00x at 2 GB/s (perfect-overlap end); the 1% crossings 1.0-1.7 GB/s
    and the doubling crossings 0.26-0.40 GB/s. ffn2's entry sets the busiest
    die link. Replaces the [est] reading 'compute met near 0.5 GB/s'."""
    c = SWEEP["d2d_2p7b"]["conditions"]["prefill, attention on chip"]["styles"]
    for style, v in c.items():
        assert v["knee_entry"] == "ffn2"
        approx(v["columns"]["unlimited|grs"]["max"], 1.00, 1e-3)
        approx(v["columns"]["unlimited|analog_d2d_high"]["max"], 1.00, 5e-3)
        assert 4.8 < v["columns"]["unlimited|analog_d2d_low"]["max"] < 7.1
        assert 1.0 < v["thresholds_gbps"]["d2d_1pct"] < 1.8
        assert 0.25 < v["thresholds_gbps"]["d2d_2x"] < 0.41
    approx(c["clustered"]["thresholds_gbps"]["d2d_1pct"], 1.36, 3e-2)
    approx(c["clustered"]["thresholds_gbps"]["d2d_2x"], 0.267, 3e-2)
    approx(c["clustered"]["columns"]["unlimited|analog_d2d_low"]["max"], 4.88, 1e-2)
    assert c["row-fill"]["columns"]["unlimited|analog_d2d_low"]["max"] > c["clustered"]["columns"]["unlimited|analog_d2d_low"]["max"]
    # both networks live: the on-die low end adds on top of the D2D reading
    approx(c["clustered"]["columns"]["analog_ondie_low|grs"]["max"], 1.19, 1e-2)
    m = SWEEP["d2d_2p7b"]["map_prefill_clustered"]
    assert len(m["mult_max"]) == len(m["ondie_gbps"]) and len(m["mult_max"][0]) == len(m["d2d_gbps"])


def test_d2d_probe_and_unit_link():
    p = SWEEP["d2d_probe"]["styles"]
    approx(p["clustered"]["thresholds_gbps"]["d2d_2x"], 0.202, 2e-2)
    approx(p["row-fill"]["thresholds_gbps"]["d2d_2x"], 0.404, 2e-2)
    approx(p["clustered"]["columns"]["grs"]["max"], 1.00, 1e-3)
    u = SWEEP["unit_link"]["conditions"]
    pre = u["prefill, attention offloaded (end to end)"]
    approx(pre["columns"]["grs"]["e2e_s"], 518.1e-3, 2e-3)             # = the ledger's offloaded end-to-end prefill
    approx(pre["thresholds_gbps"]["e2e_1pct"], 9.79, 2e-2)
    approx(pre["thresholds_gbps"]["e2e_2x"], 0.0979, 2e-2)
    dec = u["decode, attention offloaded (end to end)"]
    approx(dec["columns"]["analog_d2d_low"]["mult"], 1.50, 1e-2)


def test_partial_sum_width_thresholds_order():
    v = SWEEP["psum"]["variants"]
    one, two = v["1 word (direction-split only, O22)"], v["2 words (current)"]
    for label in SCHEMES:
        assert one[label]["thresholds_gbps"]["max_1pct"] < two[label]["thresholds_gbps"]["max_1pct"]
        assert one[label]["thresholds_gbps"]["max_2x"] < two[label]["thresholds_gbps"]["max_2x"]
    approx(two["bus (shared medium)"]["thresholds_gbps"]["max_1pct"], 1.89, 2e-2)
