"""Group 30 -- the phase diagram (O29 / C35).

Pins the data relationships the figure draws (analyze_phase_diagram.py; all
inputs are stored JSONs + the registry, zero mapper): (1) the layer edges
-- on die the star and bus production boundaries, at the die level the PURE
hand-off line and the single-operator probe -- and the ORDERING the
corrected right-panel semantics claim: pure hand-off < single 4-die
operator < the block chains INCLUDING their spanning operators (each
receiving die takes the full input under the column split, so the d >= 2560
lines carry the flood and sit ABOVE the probe); (2) the validation-point
classes: the trunk probes (qkv / ffn1, d >= 2560) agree with the closed
form to 1e-9 (on-line class), ffn2 at d <= 4096 is EXACTLY x2 off (the
known tiler step, its own marker -- expected, not a failure) and back on
the line from d >= 5120; (3) the measured B2 block-chain marks sit on the
closed-form d = 2560 line at every silicon speed; (4) the outputs exist
(figure + grayscale check copy + the grid -> ratio table with pinned rows).
"""
import json
import os

from _util import approx

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
SWEEP = json.load(open(os.path.join(WS, "analysis", "phase_sweep.json")))
LAW = json.load(open(os.path.join(WS, "analysis", "scaling_law_summary.json")))
PLANE = SWEEP["plane"]
FAM = PLANE["d_family"]
MAIN = PLANE["ondie"]["conditions"][PLANE["ondie"]["main_condition"]]
T_REF = PLANE["t_ref_s"]


def test_layer_edges_and_the_corrected_ordering():
    """Left layers: star .. bus (production). Right layers: pure hand-off ..
    the single-operator probe; and the semantic ordering: hand-off < probe
    < every block-chain-with-spanning line."""
    star = MAIN["star (private links)"]["boundary_gbps_at_tref"]
    bus = MAIN["bus (shared medium)"]["boundary_gbps_at_tref"]
    assert star < bus
    approx(star, 0.202, 1e-2); approx(bus, 2.02, 1e-2)
    handoff = FAM["d2d"]["1024"]["boundary_gbps_at_tref"]
    probe = PLANE["d2d"]["cases"]["B3 probe | clustered"]["boundary_gbps_at_tref"]
    approx(handoff, 0.101, 1e-2); approx(probe, 0.404, 1e-2)
    assert handoff < probe
    for dk in ("2560", "4096", "8192"):
        assert FAM["d2d"][dk]["boundary_gbps_at_tref"] > probe, dk
    assert "INCLUDING" in FAM["d2d_form"] and "PURE hand-off" in FAM["d2d_form"]


def test_validation_point_classes():
    """The trunk probes land on the closed form exactly; ffn2's step is
    exactly x2 at d <= 4096 (its own marker class) and gone from 5120."""
    trunk = LAW["trunk_denominator"]
    for name in ("qkv_proj", "ffn1"):
        for dstr, row in LAW["scheme_check"][name].items():
            if int(dstr) < 2560:
                continue
            agree = row["mesh, glb centre"] / (4.0 * int(dstr) / trunk)
            approx(agree, 1.0, 1e-9), (name, dstr)
    for dstr, want in (("2560", 2.0), ("4096", 2.0), ("5120", 1.0),
                       ("6144", 1.0), ("8192", 1.0)):
        agree = LAW["scheme_check"]["ffn2"][dstr]["mesh, glb centre"] / \
            (4.0 * int(dstr) / trunk)
        approx(agree, want, 1e-9), dstr


def test_b2_marks_sit_on_the_d2560_line_at_every_silicon_speed():
    pred = FAM["d2d"]["2560"]["boundary_gbps_at_tref"]
    marks = PLANE["b2_marks"]["clustered"]["marks"]
    assert set(marks) == {"neurram", "mythic_m1076", "isaac", "hermes"}
    for mv in marks.values():
        approx(mv["boundary_gbps"], pred * T_REF / mv["t_mvm_s"], 1e-3)


def test_outputs_exist_with_pinned_table_rows():
    for f, minsize in (("phase_diagram.png", 100000),
                       ("phase_diagram_gray.png", 30000)):
        p = os.path.join(WS, "analysis", f)
        assert os.path.exists(p) and os.path.getsize(p) > minsize, f
    table = open(os.path.join(WS, "analysis", "phase_diagram_table.md")).read()
    for want in ("| on-die, star (production d=1024) | 0.202 | 0.321 | 1.28 | 15.4 |",
                 "| on-die, bus (production d=1024) | 2.02 | 3.21 | 12.8 | 154 |",
                 "| D2D pure hand-off stream, d=1024 (production) | 0.101 | 0.161 | 0.64 | 7.7 |",
                 "| D2D single 4-die operator (probe) | 0.404 | 0.642 | 2.56 | 30.8 |",
                 "block chain incl. spanning ops, d=8192 | 3.23 | 5.14 | 20.5 | 246 |"):
        assert want in table, want
