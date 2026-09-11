"""Group 49 -- S1 (C64-a): the search space.

Day-1 gates: hand-built legal/illegal cases INCLUDING an O10-type
counterexample (capacity fits, the tiler says no), the tiler-feasible
size set (sparse where O10 bites), JSON round-trip, and the A4
544-seat + 16x2-seam payload parsing to a LEGAL standard Pi."""
import dataclasses
import json
import os

from scripts import fabric, llm_workload as lw
from scripts import search_space as ss

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
F576 = fabric.from_yaml(os.path.join(WS, "models", "fabric",
                                     "mlx300_multidie576.yaml"))
CFG = lw.GptConfig(d_model=2560, n_heads=32, d_ff=10240, n_layers=32,
                   name="gpt-2.7B-class")
INV = ss.inventory_from_block_chain(CFG, 512, max_dies=576)


def _std():
    return ss.pi_from_a4_payload(os.path.join(WS, "analysis",
                                              "a4_full_model.json"))


def test_a4_payload_is_the_legal_standard_case():
    pi = _std()
    ok, why = ss.legal(pi, F576, INV)
    assert ok, why
    assert pi.n_blocks == 32 and pi.cuts == tuple(range(2, 33, 2))
    assert len(pi.segments()) == 16
    assert all(len(s) == 2 * 5 for s in pi.stage_sets())  # 2 blocks x 5 sets


def test_json_round_trip():
    pi = _std()
    back = ss.Pi.from_json(pi.to_json())
    assert back == pi


def test_gamma_illegal_cases():
    pi = _std()
    for cuts in ((), (2, 2, 32), (2, 31), (0, 32)):
        ok, why = ss.legal(dataclasses.replace(pi, cuts=cuts), F576, INV)
        assert not ok and why.startswith("gamma")


def test_alpha_o10_counterexample_and_overlap():
    """THE O10-TYPE CASE (amendment 1's teeth): 2.7B ffn1's capacity
    arithmetic says 4 dies; the tiler says 5 -- a 4-slot seat must be
    REJECTED with the O10 message, not accepted by ceil(vol/cap)."""
    pi = _std()
    seat = dict(pi.seat)
    seat["ffn1@L0"] = seat["ffn1@L0"][:4]                 # capacity-sized
    ok, why = ss.legal(dataclasses.replace(pi, seat=seat), F576, INV)
    assert not ok and "TILER" in why and "O10" in why
    seat = dict(pi.seat)
    seat["ffn2@L1"] = pi.seat["ffn1@L0"][:5]              # overlap
    ok, why = ss.legal(dataclasses.replace(pi, seat=seat), F576, INV)
    assert not ok and "overlap" in why


def test_small_dimensions_and_beta_structure():
    pi = _std()
    ok, _ = ss.legal(dataclasses.replace(pi, hub="node:12", attach=100),
                     F576, INV)
    assert ok
    ok, why = ss.legal(dataclasses.replace(pi, hub="node:576"), F576, INV)
    assert not ok and "hub" in why
    ok, why = ss.legal(dataclasses.replace(pi, attach=600), F576, INV)
    assert not ok and "attach" in why
    ok, _ = ss.legal(dataclasses.replace(pi, beta={0: (1, 0, 2)}),
                     F576, INV)
    assert ok                                              # structural pass
    ok, why = ss.legal(dataclasses.replace(pi, beta={0: (1, 1)}),
                       F576, INV)
    assert not ok and "permutation" in why
    ok, why = ss.legal(dataclasses.replace(pi, beta={555: (0,)}),
                       F576, INV)
    assert not ok and "not seated" in why


def test_feasible_die_counts_is_sparse_where_o10_bites():
    """The oracle's group-size axis: 2.7B ffn1 -- 4 is NOT feasible
    (capacity arithmetic's answer), 5 is; the set is the tiler's, and
    sparse."""
    ops = {o.name: o for o in lw.block_ops(CFG, S=512, phase="prefill")}
    ns = ss.feasible_die_counts(ops["ffn1"], max_dies=12)
    assert 4 not in ns and 5 in ns
    assert ns == sorted(set(ns))
    inv = dict(ss.chain_inventory(CFG, 512, max_dies=576))
    assert inv["ffn1"] == 5 and inv["qkv_proj"] == 4      # the standing rule
