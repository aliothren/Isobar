"""Group 22 -- the 2.7B block as a chain of die-sets (O13).

A spanning model's operators sit on die-SETS; every operator's input arrives
from the dies that own the previous operator's output, over the die grid,
and what crosses a die-to-die wire is the tensor once (the layer hand-off
convention). What can go wrong is the bookkeeping: the seating must be
disjoint, the volumes must conserve the tensors, the split kind must decide
the width, and the offloaded attention must route through the attach point.
"""
from _util import approx

from scripts import fabric, interconnect as ic, placement
from scripts import llm_workload as lw

FAB = fabric.from_yaml("/home/workspace/models/fabric/mlx300_multidie.yaml")
C27 = lw.GptConfig(d_model=2560, n_heads=32, d_ff=10240, n_layers=32,
                   name="gpt-2.7B-class")
STYLES = ("clustered", "row-fill", "spread")


def test_chain_order_dies_and_splits():
    """Data-flow order; the residency tiler's 4/2/5/5 dies plus one
    attention die; every 2.7B operator splits by output columns; the block
    fits the 24-die package."""
    ch = lw.block_chain(C27, 512, "prefill")
    assert [e["name"] for e in ch] == ["qkv_proj", "attention", "out_proj", "ffn1", "ffn2"]
    assert [e["n_dies"] for e in ch] == [4, 1, 2, 5, 5]
    assert all(e["split"] == "M" for e in ch if e["kind"] == "static")
    assert sum(e["n_dies"] for e in ch) == 17
    assert 17 <= len(placement.sequential_fill(FAB).slots["die"])


def test_seatings_are_disjoint_and_clustered_is_nearest():
    ch = lw.block_chain(C27, 512, "prefill")
    pl = placement.sequential_fill(FAB)
    slots, hub = pl.slots["die"], ic.build(FAB, "die", pl).hub_coord()
    means = {}
    for style in STYLES:
        st = lw.seat_block(FAB, ch, style)
        alld = [d for v in st.values() for d in v]
        assert len(alld) == 17 and len(set(alld)) == 17
        assert [len(st[e["name"]]) for e in ch] == [e["n_dies"] for e in ch]
        means[style] = sum(abs(slots[d][0] - hub[0]) + abs(slots[d][1] - hub[1])
                           for d in alld) / 17
    assert means["clustered"] <= means["row-fill"] <= means["spread"] + 1e-9 or \
        means["clustered"] <= min(means["row-fill"], means["spread"])


def test_flow_volumes_are_the_tensor_once():
    """Each consumer die receives exactly its whole input (P x C) as disjoint
    pieces of the producer's output; column split -> activation width."""
    ch = lw.block_chain(C27, 512, "prefill")
    st = lw.seat_block(FAB, ch, "row-fill")
    fl = lw.block_die_flows(ch, st, FAB)
    for i, e in enumerate(ch):
        p = ch[i - 1]
        for b in st[e["name"]]:
            inbound = sum(f["volume"] for f in fl[e["name"]] if f["nodes"][1] == b)
            assert inbound == e["in_words"] == p["out_words"]
        assert all(f["width"] == 1.0 for f in fl[e["name"]])
        assert len(fl[e["name"]]) == len(st[p["name"]]) * len(st[e["name"]])
    assert ch[3]["in_words"] == 512 * 2560 and ch[4]["in_words"] == 512 * 10240
    assert ch[1]["in_words"] == 512 * 3 * 2560          # Q, K and V to the attention die


def test_input_row_split_producer_sends_partial_sums():
    """An input-row split producer holds partial sums of the WHOLE output:
    every consumer die receives all of them, at partial-sum width."""
    ch = lw.block_chain(C27, 512, "prefill")
    st = lw.seat_block(FAB, ch, "row-fill")
    ch2 = [dict(e) for e in ch]
    ch2[3]["split"] = "C"                                 # pretend ffn1 split its input rows
    fl = lw.block_die_flows(ch2, st, FAB)
    psum = getattr(FAB, "psum_word_bytes", 2.0)
    for b in st["ffn2"]:
        inbound = [f for f in fl["ffn2"] if f["nodes"][1] == b]
        assert len(inbound) == 5
        assert all(f["volume"] == ch2[3]["out_words"] and f["width"] == psum for f in inbound)


def test_offloaded_attention_routes_through_the_attach_point():
    ch = lw.block_chain(C27, 512, "decode", on_chip=False)
    assert ch[1]["kind"] == "unit" and ch[1]["n_dies"] == 0
    assert sum(e["n_dies"] for e in ch) == 16
    st = lw.seat_block(FAB, ch, "clustered")
    fl = lw.block_die_flows(ch, st, FAB)
    assert len(fl["attention"]) == 4 and all(f["nodes"][1] == ic.HUB for f in fl["attention"])
    assert len(fl["out_proj"]) == 2 and all(f["nodes"][0] == ic.HUB for f in fl["out_proj"])
    assert sum(f["volume"] for f in fl["attention"]) == 3 * 2560
    assert all(f["volume"] == 2560 for f in fl["out_proj"])


def test_decode_is_prefill_over_S():
    a = lw.block_chain(C27, 512, "prefill")
    b = lw.block_chain(C27, 512, "decode")
    assert all(x["in_words"] == 512 * y["in_words"] and x["n_dies"] == y["n_dies"]
               for x, y in zip(a, b))


def test_surplus_energy_follows_hops_beyond_the_reference():
    ch = lw.block_chain(C27, 512, "prefill")
    st = lw.seat_block(FAB, ch, "spread")
    flows = [f for v in lw.block_die_flows(ch, st, FAB).values() for f in v]
    pl = placement.sequential_fill(FAB)
    m = ic.build(FAB, "die", pl)
    by_hand = sum(f["volume"] * max(m.hops(*f["nodes"]) - 1.0, 0.0) * 10e-12 for f in flows)
    assert by_hand > 0
    approx(lw.die_flow_surplus_energy(flows, FAB, pj_per_word=10.0), by_hand, 1e-9)
    assert lw.die_flow_surplus_energy(flows, FAB, pj_per_word=10.0, reference_hops=100) == 0.0
    assert lw.die_flow_surplus_energy(flows, FAB, pj_per_word=0.0) == 0.0


def test_tier_readouts_at_the_anchors():
    """The published 2.7B readouts (scale_tiers.json, analyze_scale_tiers.py,
    value units C25): tier M at the GRS anchor 1.00x at every seating
    (zero-overlap 1.03-1.06x), surplus 0 / 31 / 35 uJ; tier L prefill 1.00x
    at every NoC anchor and seating (zero-overlap 1.04-1.09x), D2D surplus
    27-31 mJ of 2297 (1.2-1.3%); offloaded decode 1.00-1.01x. The
    hub-routed comparison rows (tierL_v1 / hub_once) now read the same
    multipliers -- the routing moves only the energy (37/38 -> 27/30 mJ).
    Retired: 3.10-6.20x and 1.22-2.14x / 792-829 mJ (counter units)."""
    import json
    d = json.load(open("/home/workspace/analysis/scale_tiers.json"))
    comp = 0.64896e-3
    for t in d["tierM"]:
        approx(t["lat_s"], comp, 1e-3)                       # hidden behind compute
        assert 1.02 < t["lat_sum_s"] / comp < 1.07
    sur = {t["label"]: t["surplus_J"] for t in d["tierM"]}
    assert sur["clustered"] == 0.0 and 30e-6 < sur["row-fill"] < sur["spread"] < 40e-6
    pref = d["tierL"]["prefill, attention on chip"]
    for r in pref["rows"]:
        approx(r["mult"], 1.00, 1e-3)
        assert 1.03 < r["mult_sum"] < 1.10
        assert 0.010 < r["surplus_J"] / pref["energy_J"] < 0.015
    mid = {r["style"]: r for r in pref["rows"] if r["noc"] == "ESP 32"}
    assert mid["row-fill"]["surplus_J"] < mid["spread"]["surplus_J"] < mid["clustered"]["surplus_J"]
    h1 = {r["style"]: r for r in d["tierL_hub_once"]["prefill, attention on chip"]["rows"]
          if r["noc"] == "ESP 32"}
    assert h1["row-fill"]["surplus_J"] > mid["row-fill"]["surplus_J"]      # routing cuts the energy
    approx(h1["row-fill"]["mult"], mid["row-fill"]["mult"], 1e-3)          # and not the latency
    dec = d["tierL"]["decode, attention offloaded"]["rows"]
    assert all(r["mult"] < 1.02 for r in dec)
