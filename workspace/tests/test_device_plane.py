"""Group 27 -- the (t_MVM x bandwidth) plane (O17b / C31).

Pins: (1) the swept r = 1 thresholds (bisection on the numeric r surface)
land EXACTLY on the closed-form line g1(t) = ref_gbps * (ser_ref / mm_ref) *
(t_ref / t) -- slope -1 in log-log, the plane's strongest self-check;
(2) the matrix-part multiplier is a single-variable function of the collapse
variable g x t_MVM (the three silicon devices land on one curve) and the
whole-stack multiplier is NOT -- the K/V write and the digital unit do not
scale with the device, which is the finding, not a bug; (3) the three
silicon marks are the registry's chip points with their statuses (measured /
design-point / derived) -- the surface between them has no silicon behind
it; (4) the fixed-term decomposition: the HERMES-class device is 76.3x
faster and speeds decode by only 1.11x (the corrected number -- FIXLIST
carried 1.3x) and prefill by 9.3x; (5) the network seconds at a fixed GB/s
are device-independent (the group 26 identity, restated on the plane's own
data: r scales exactly as 1/t at every bandwidth).
"""
import json
import os

from _util import approx

from scripts import anchors as an

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
SWEEP = json.load(open(os.path.join(WS, "analysis", "phase_sweep.json")))
PLANE = SWEEP["plane"]
T_REF = PLANE["t_ref_s"]
MAIN = PLANE["ondie"]["conditions"][PLANE["ondie"]["main_condition"]]
SCHEMES = ["star (private links)", "mesh, glb centre", "mesh, glb corner",
           "h-tree (k=4)", "bus (shared medium)"]


def test_scanned_thresholds_equal_the_closed_form_line():
    """The r = 1 crossing scanned by bisection at every device-grid point
    equals ref_gbps * (ser_ref / mm_ref) * (t_ref / t); the numeric r
    surface is the same closed form pointwise."""
    t_grid = PLANE["t_grid_s"]
    g_grid = PLANE["ondie"]["g_grid_gbps"]
    for label in SCHEMES:
        c = MAIN[label]
        b_ref = c["net_gb"] / c["mm_ref_s"]
        approx(c["boundary_gbps_at_tref"], b_ref, 1e-12)
        for t, scanned in zip(t_grid, c["scan_thresholds_gbps"]):
            approx(scanned, b_ref * T_REF / t, 1e-9), (label, t)
        for i in (0, len(t_grid) // 2, -1):
            for j in (0, len(g_grid) // 2, -1):
                approx(c["r"][i][j],
                       (c["net_gb"] / g_grid[j]) / (c["mm_ref_s"] * t_grid[i] / T_REF), 1e-12)
    # the boundary readouts themselves (prefill offloaded, knee ffn2 everywhere):
    # star 0.202 / routed 0.808 x3 / bus 2.02 GB/s at NeuRRAM -> 15.4 / 61.6 / 154 at HERMES
    approx(MAIN["star (private links)"]["boundary_gbps_at_tref"], 0.202, 1e-2)
    approx(MAIN["mesh, glb centre"]["boundary_gbps_at_tref"], 0.808, 1e-2)
    approx(MAIN["bus (shared medium)"]["boundary_gbps_at_tref"], 2.02, 1e-2)
    approx(MAIN["mesh, glb centre"]["marks"]["hermes"]["boundary_gbps"], 61.6, 1e-2)
    for label in SCHEMES:
        assert MAIN[label]["knee_op"] == "ffn2", label
    # net_gb and mm_ref are the stored components in the device-free unit
    sysd = json.load(open(os.path.join(WS, "analysis", "contention_system.json")))
    ops = {o["name"]: o for o in sysd["phases"]["prefill"]["per_op"]["mesh, glb centre"]}
    approx(MAIN["mesh, glb centre"]["net_gb"],
           ops["ffn2"]["serial_s"] * SWEEP["fixed"]["ref_gbps"], 1e-12)
    approx(MAIN["mesh, glb centre"]["mm_ref_s"], ops["ffn2"]["compute_s"], 1e-12)


def test_matrix_part_collapses_and_the_whole_stack_does_not():
    """The matrix-part multiplier depends on (g, t) only through g x t_MVM:
    the three device curves coincide to machine precision. The whole-stack
    multiplier does not -- the fixed terms break the collapse."""
    coll = PLANE["collapse"]
    marks = [m["key"] for m in PLANE["marks"]]
    ref = coll["per_mark"][marks[0]]
    for key in marks[1:]:
        cur = coll["per_mark"][key]
        for a, b in zip(ref["matrix_mult"], cur["matrix_mult"]):
            approx(a, b, 1e-12)
    slow, fast = coll["per_mark"]["neurram"]["whole_mult"], coll["per_mark"]["hermes"]["whole_mult"]
    assert max(s / f for s, f in zip(slow, fast)) > 2.0     # same g x t, different stacks
    assert all(s >= f - 1e-12 for s, f in zip(slow, fast))  # fixed terms shelter the fast device


def test_the_marks_are_the_registry_chip_points():
    marks = {m["key"]: m for m in PLANE["marks"]}
    regs = an.device_marks()
    assert [m["key"] for m in PLANE["marks"]] == [c.key for c in regs]  # descending t_MVM
    for c in regs:
        assert marks[c.key]["t_mvm_s"] == c.t_mvm_s
        assert marks[c.key]["status"] == c.t_mvm_status
    assert set(marks) == {"neurram", "mythic_m1076", "isaac", "hermes"}   # four since C36
    approx(marks["neurram"]["t_mvm_s"], 10.14e-6, 1e-9)
    assert marks["neurram"]["status"] == "measured"
    approx(marks["mythic_m1076"]["t_mvm_s"], 6.375e-6, 1e-3)
    assert marks["mythic_m1076"]["status"] == "derived"
    approx(marks["isaac"]["t_mvm_s"], 1.6e-6, 1e-9)
    assert marks["isaac"]["status"] == "design-point"
    approx(marks["hermes"]["t_mvm_s"], 1.329e-7, 1e-2)
    assert marks["hermes"]["status"] == "derived"
    for c in regs:                                    # every mark is a grid point
        assert any(abs(t - c.t_mvm_s) < 1e-15 for t in PLANE["t_grid_s"]), c.key


def test_fixed_term_decomposition_at_the_hermes_mark():
    """A 76.3x faster device: prefill 826.4 -> 88.6 ms (9.33x), decode 14.78
    -> 13.34 ms (1.11x -- corrects the 1.3x once claimed): the decode stack
    is almost entirely the K/V write, which does not scale with t_MVM."""
    ft = PLANE["fixed_terms"]
    ratio = T_REF / an.chip("hermes").t_mvm_s
    approx(ratio, 76.3, 1e-2)
    sysd = json.load(open(os.path.join(WS, "analysis", "contention_system.json")))
    for phase in ("prefill", "decode"):
        ph = sysd["phases"][phase]
        approx(ft[phase]["mm_s"], ph["compute_s"], 1e-12)
        approx(ft[phase]["write_s"], ph["write_s"], 1e-12)
        approx(ft[phase]["digital_s"], ph["elementwise_s"], 1e-12)
        h = ft[phase]["at_marks"]["hermes"]
        approx(h["stack_s"], ph["compute_s"] / ratio + ph["write_s"] + ph["elementwise_s"], 1e-9)
    approx(ft["prefill"]["base_s"], 826.4e-3, 1e-3)
    approx(ft["prefill"]["at_marks"]["hermes"]["stack_s"], 88.6e-3, 1e-2)
    approx(ft["prefill"]["at_marks"]["hermes"]["speedup"], 9.33, 1e-2)
    approx(ft["decode"]["base_s"], 14.78e-3, 1e-2)
    approx(ft["decode"]["at_marks"]["hermes"]["stack_s"], 13.34e-3, 1e-2)
    approx(ft["decode"]["at_marks"]["hermes"]["speedup"], 1.11, 1e-2)


def test_the_d_family_is_measured_and_closed_form():
    """C33: the plane's d family. On die (routed): d = 1024 is the
    PRODUCTION base (its knee ffn2 sits x2 above the trunk line -- the
    same C-split mechanism as ffn2's step), d >= 2560 is the trunk law
    x4 = REF_GBPS x 4d / 114,688. Die level (tiler closed form, tensor
    once): d = 1024 the C13 half-layer hand-off (S x d, payer ffn1),
    d >= 2560 the ffn2 entry (S x 4d) -- and the d = 2560 line passes
    exactly through the measured B2 mark. The two levels coincide for
    d >= 2560: mesh's x4 multicast equals ffn2's 4d-wide tensor."""
    fam = PLANE["d_family"]
    assert set(fam["ondie"]) == {"1024", "2560", "4096", "8192"}
    approx(fam["ondie"]["1024"]["boundary_gbps_at_tref"],
           MAIN["mesh, glb centre"]["boundary_gbps_at_tref"], 1e-12)
    ref_gbps = SWEEP["fixed"]["ref_gbps"]
    for d in (2560, 4096, 8192):
        want = ref_gbps * 4.0 * d / 114688.0
        approx(fam["ondie"][str(d)]["boundary_gbps_at_tref"], want, 1e-9)
        approx(fam["d2d"][str(d)]["boundary_gbps_at_tref"],
               4.0 * d / (T_REF * 1e9), 1e-9)
    approx(fam["d2d"]["1024"]["boundary_gbps_at_tref"], 1024.0 / (T_REF * 1e9), 1e-9)
    approx(fam["d2d"]["2560"]["boundary_gbps_at_tref"],
           SWEEP["plane"]["b2_marks"]["clustered"]["boundary_gbps_at_tref"], 1e-3)
    for d, model in (("1024", "GPT-2"), ("2560", "OPT-2.7B"),
                     ("4096", "Llama-7B"), ("8192", "Llama-2-70B")):
        assert model in fam["labels"][d], d
    assert "production base" in fam["labels"]["1024"]
    assert "annotation" in fam["ffn2_step"] or "annotated" in fam["ffn2_step"]


def test_network_seconds_are_device_free_at_fixed_gbps():
    """The group 26 identity on the plane's data: at every bandwidth column
    r scales exactly as 1/t -- the network seconds (net_gb / g) carry no
    device; and the GB/s form equals the words-per-cycle form at ANY cycle."""
    t_grid = PLANE["t_grid_s"]
    for label in ("star (private links)", "bus (shared medium)"):
        c = MAIN[label]
        for j in (0, 5, -1):
            prods = [c["r"][i][j] * t_grid[i] for i in range(len(t_grid))]
            for p in prods[1:]:
                approx(p, prods[0], 1e-12)
    c = MAIN["mesh, glb centre"]
    ser_ref = c["net_gb"] / SWEEP["fixed"]["ref_gbps"]         # seconds at the reference GB/s
    for cyc in (an.CYCLE_S, an.CYCLE_S / 10, an.CYCLE_S * 3):
        wc_ref = SWEEP["fixed"]["ref_gbps"] * 1e9 * cyc
        approx(ser_ref * wc_ref / an.words_per_cycle(3.3, cycle_s=cyc),
               c["net_gb"] / 3.3, 1e-12)


def test_the_fixed_terms_relay_under_offload():
    """C39: the offloaded twin of the decomposition. The die keeps the
    projections + FFN (scaling) and the unit chain (DR-9 generic) is the
    NEW floor: it beats the write wall in BOTH phases (prefill 19.7 vs
    78.8 ms, decode 1.02 vs 13.32 ms), so offload wins single-pass latency
    at EVERY device tier -- no crossing (the expected 1-3 us threshold
    does not exist) -- while the unit floor then caps the offloaded config
    itself: a 76.3x device buys decode only 1.93x offloaded (vs 1.11x on
    chip). The NeuRRAM totals tie the ledger exactly: offloaded prefill
    518.1 ms, decode 1.99 ms per token (the C21 end-to-end numbers)."""
    fo = PLANE["fixed_terms_offloaded"]
    rl = PLANE["offload_relay"]
    approx(fo["prefill"]["base_s"], 518.1e-3, 1e-3)
    approx(fo["decode"]["base_s"], 1.99e-3, 5e-3)
    approx(rl["prefill"]["offloaded_floor_s"], 19.7e-3, 1e-2)
    approx(rl["decode"]["offloaded_floor_s"], 1.02e-3, 1e-2)
    for phase in ("prefill", "decode"):
        assert rl[phase]["crossing_t_s"] is None
        assert rl[phase]["offloaded_floor_s"] < rl[phase]["onchip_floor_s"]
        ft = PLANE["fixed_terms"][phase]
        for a, b in zip(fo[phase]["stack_s"], ft["stack_s"]):
            assert a < b, phase                       # offload wins at every grid t
        for key, v in rl[phase]["ratio_at_marks"].items():
            assert v > 1.0, (phase, key)
    approx(fo["decode"]["at_marks"]["hermes"]["speedup"], 1.93, 1e-2)
    approx(fo["prefill"]["at_marks"]["hermes"]["speedup"], 19.74, 1e-2)
    approx(rl["decode"]["ratio_at_marks"]["neurram"], 14.78 / 1.99, 2e-2)
    assert "RELAY" in rl["verdict"] and "DR-5" in rl["verdict"] and "DR-9" in rl["verdict"]
