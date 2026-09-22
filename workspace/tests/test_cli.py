"""Group 56 -- the command-line entry (scripts/cimsim_cli.py) and the
fabric's port-ratio declaration. The CLI only wraps the platform, so its
readings must equal the frozen ones: clustered seed 0 at kappa 2 and
0.4 GB/s is 2550.35 ms, the package band at the NeuRRAM rate is 0.535
to 1.421 GB/s."""
import json
import os
import sys
import tempfile

from _util import approx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from scripts import cimsim_cli as cli
from scripts import fabric

TMP = tempfile.mkdtemp(prefix="cimsim_cli_")


def test_port_ratio_declared_in_fabric():
    f = fabric.from_yaml(cli.DEFAULT_FABRIC)
    assert f.level("die").port_ratio == 2.0
    assert fabric.default().level("die").port_ratio is None     # the single-die default declares none
    try:
        fabric.Level("die", per_parent=4, mesh=(2, 2), port_ratio=0.5)
        fabric.Fabric("bad", levels=[fabric.Level("package"),
                                     fabric.Level("die", per_parent=4, mesh=(2, 2), port_ratio=0.5)]).validate()
        assert False, "ports.ratio < 1 must not validate"
    except ValueError as e:
        assert "ports.ratio" in str(e)


def test_baseline_then_evaluate_reproduces_frozen_reading():
    pi_path = os.path.join(TMP, "clustered.json")
    cli.main(["baseline", "--rule", "clustered", "--out", pi_path])
    out_path = os.path.join(TMP, "eval.json")
    cli.main(["evaluate", "--deployment", pi_path, "--bandwidth", "0.4",
              "--phases", "prefill,decode", "--loads", "3", "--out", out_path])
    r = json.load(open(out_path))
    assert r["setting"]["kappa"] == 2.0                       # from the fabric's ports.ratio
    approx(r["per_phase"]["prefill"]["t_opt_s"], 2.550352, 1e-5)
    approx(r["per_phase"]["decode"]["t_opt_s"], 0.02731, 1e-3)
    assert len(r["handoffs"]["prefill"]) == 159
    assert {h["binding"] for h in r["handoffs"]["prefill"]} <= {"link", "port", "port=link", "mixed"}


def test_kappa_override_and_constants():
    pi_path = os.path.join(TMP, "seq.json")
    cli.main(["baseline", "--rule", "sequential", "--out", pi_path])
    out1 = os.path.join(TMP, "e1.json")
    cli.main(["evaluate", "--deployment", pi_path, "--kappa", "1", "--bandwidth", "12.5",
              "--phases", "prefill", "--loads", "0", "--out", out1])
    r1 = json.load(open(out1))
    assert r1["setting"]["kappa"] == 1.0
    approx(r1["per_phase"]["prefill"]["t_opt_s"], 1.026325, 1e-5)  # kappa 1: 65 of 159 hand-offs port-bound (1025.83 ms at kappa 2)
    out2 = os.path.join(TMP, "e2.json")
    cli.main(["evaluate", "--deployment", pi_path, "--kappa", "1", "--bandwidth", "12.5",
              "--phases", "prefill", "--loads", "0", "--d2d-ns-per-hop", "40", "--out", out2])
    r2 = json.load(open(out2))
    d1, d2 = r1["per_phase"]["prefill"]["decomp"], r2["per_phase"]["prefill"]["decomp"]
    approx(d2["propagation_s"], 2 * d1["propagation_s"], 1e-9)
    from scripts import search_eval as se
    se.NS_PER_HOP_D2D = 20.0                                   # restore the module constant


def test_search_small_budget_improves_and_writes_products():
    d = os.path.join(TMP, "search")
    cli.main(["search", "--starts", "random", "--seeds", "0", "--steps", "40",
              "--bandwidth", "0.4", "--no-baselines", "--out-dir", d])
    s = json.load(open(os.path.join(d, "search.json")))
    run = s["runs"]["sa_random_s0"]
    assert run["best_j"] <= run["start_j"]
    assert run["proposed"] == 40
    assert os.path.exists(os.path.join(d, "best_pi.json"))
    assert s["summary"]["headline"]["run"] == "sa_random_s0"


def test_phase_band_matches_frozen():
    out = os.path.join(TMP, "phase.json")
    cli.main(["phase", "--bandwidths", "0.4,12.5", "--out", out])
    r = json.load(open(out))
    approx(r["B_minus_gbps"], 0.535, 3e-3)
    approx(r["B_plus_gbps"], 1.421, 3e-3)
    assert r["bandwidths"]["0.4"].startswith("communication dominated")
    assert r["bandwidths"]["12.5"].startswith("communication masked")
