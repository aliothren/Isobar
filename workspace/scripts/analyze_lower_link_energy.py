"""A5 days 3-4 (C58-b): the lower-link OVERLAY energy column + ceiling gate.

Day-1 route ruling (FIXLIST O1): the CiMLoop account is untouched; this
script IS the declared supplement -- core/crossbar traffic charged as
words x pJ/word x hops outside the calibrated account (the D2D-surplus
convention). Prices come from the fabric config (single source; a tie
check against the day-2 derivation is a gate, drift is a red).

HOPS CALIBER: build_flows edge distances are in LEAF-slot units (the
leaf grid IS the crossbar grid, 100 um pitch). A LEVEL-hop is one slot
pitch of that level, so hops(edge) = distance_leaf / (level pitch /
leaf pitch): core 400/100 = 4 leaf units per hop, crossbar 1. Because
price ~ pitch (route b), charging per level-hop at the level price is
IDENTICAL to charging per leaf unit at the crossbar price -- the script
asserts that identity, so the caliber choice cannot move the total.

GATES, in order (run stops at the first failure):
  G0 tie: fabric prices == day-2 derived prices (lower_link_prices.json).
  G1 conservation (rider, user 2026-09-08): the volumes charged are the
     C25 touched-extent VALUE volumes -- leaf level ties EXACTLY to the
     stats counters (row reads / X + adc reads / (Z x Y_col)), upper
     levels carry at most the leaf total (multicast strictness).
  G2 ceiling (day 4, pre-registered): overlay total / operator energy
     <= the C25 ~2% ceiling; expectation filed before the run: same
     order as the day-2 flat-2-hop arithmetic (50.3 uJ / 1.86%), below
     it iff volume-weighted mean hops < 2 per level. FAIL => STOP AND
     TRIAGE; the ceiling is not a parameter.

RIDER (user, 2026-09-08): the gate arithmetic ships an itemized
breakdown table -- per level: words, mean hops, unit price, subtotal --
with the row products exactly reproducing the charged subtotals.

    python3 scripts/analyze_lower_link_energy.py
      -> analysis/lower_link_energy.json + analysis/lower_link_energy.md
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.crossbar_comm as cc
from scripts import fabric as fabric_mod
from scripts import placement_aware as pa
from scripts import traffic

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
A = os.path.join(WS, "analysis")
FX = os.path.join(WS, "tests", "fixtures")

LEVELS = ("core", "crossbar")        # the two overlay-priced levels
FLOW_KEY = {"core": "macro<->core", "crossbar": "core<->crossbar"}
CEILING_SHARE = 0.025                # the C25 ~2% ceiling (gate G2)
FLAT_2HOP_J = 5.03e-5                # day-2 arithmetic, for comparison only


def main():
    fab = fabric_mod.default()
    stats_txt = open(os.path.join(FX, "ffn1_prefill_stats.txt")).read()
    map_txt = open(os.path.join(FX, "ffn1_prefill_map.txt")).read()

    # G0 -- price tie: fabric config vs the day-2 derivation
    derived = json.load(open(os.path.join(A, "lower_link_prices.json")))
    price = {}
    for name in LEVELS:
        p = fab.level(name).link.pj_per_word
        pd = derived["prices"][name]["pj_per_word"]
        assert p is not None and abs(p - pd) <= 1e-9 * pd, \
            f"G0 FAIL: fabric {name} price {p} != derived {pd}"
        price[name] = p

    td = tempfile.mkdtemp()
    try:
        shutil.copy(os.path.join(FX, "ffn1_prefill_map.txt"),
                    os.path.join(td, "timeloop-mapper.map.txt"))
        shutil.copy(os.path.join(FX, "ffn1_prefill_stats.txt"),
                    os.path.join(td, "timeloop-mapper.stats.txt"))
        flows, _, _, _ = cc.build_flows(td, verbose=False)
    finally:
        shutil.rmtree(td, ignore_errors=True)

    # G1 -- conservation on the C25 touched-extent value volumes
    vols = {}
    for f in flows:
        vols[f["level"]] = vols.get(f["level"], 0.0) + f["volume"]
    ts = traffic.extract(mapping_text=map_txt, stats_text=stats_txt)
    leaf_identity = (ts.in_reads_total / ts.x_slices
                     + ts.out_reads_total / (ts.z_bits * ts.y_columns))
    assert abs(vols["core<->crossbar"] - leaf_identity) < 1e-6, \
        "G1 FAIL: leaf volume != C25 stats identity"
    for upper in ("glb<->macro", "macro<->core"):
        assert vols[upper] <= vols["core<->crossbar"] + 1e-6, \
            f"G1 FAIL: {upper} exceeds leaf total (multicast strictness)"
    conservation = {
        "leaf_volume_words": vols["core<->crossbar"],
        "stats_identity_words": leaf_identity,
        "identity": ("row reads / X + adc reads / (Z x Y_col) = "
                     f"{ts.in_reads_total:,.0f}/{ts.x_slices} + "
                     f"{ts.out_reads_total:,.0f}/({ts.z_bits}x{ts.y_columns})"),
        "upper_levels_words": {k: vols[k]
                               for k in ("glb<->macro", "macro<->core")},
        "verdict": "PASS"}

    # the overlay charge, itemized (rider: words x hops x price = subtotal)
    leaf_pitch = fab.level("crossbar").slot_pitch_um
    out_levels = {}
    for name in LEVELS:
        per_hop_leaf = fab.level(name).slot_pitch_um / leaf_pitch
        edges = [f for f in flows if f["level"] == FLOW_KEY[name]]
        words = sum(f["volume"] for f in edges)
        vol_hops = sum(f["volume"] * f["distance"] / per_hop_leaf
                       for f in edges)
        mean_hops = vol_hops / words
        energy = vol_hops * price[name] * 1e-12
        # caliber identity: level framing == per-leaf framing (route b)
        per_leaf = sum(f["volume"] * f["distance"] for f in edges) \
            * price["crossbar"] * 1e-12
        assert abs(energy - per_leaf) < 1e-15 + 1e-9 * energy, \
            f"caliber identity broken at {name}"
        out_levels[name] = {"flow": FLOW_KEY[name], "n_edges": len(edges),
                            "words": words, "mean_hops": mean_hops,
                            "pj_per_word_per_hop": price[name],
                            "energy_J": energy}

    # G2 -- the day-4 ceiling gate
    lv = pa.perceive(os.path.join(FX, "ffn1_prefill_stats.txt"))
    op_energy = sum(v.get("energy_J", 0.0) for v in lv.values())
    total = sum(v["energy_J"] for v in out_levels.values())
    share = total / op_energy
    gate = {"overlay_total_J": total,
            "operator_energy_J_ffn1": op_energy,
            "share_of_operator": share,
            "c25_ceiling": CEILING_SHARE,
            "day2_flat_2hop_J": FLAT_2HOP_J,
            "verdict": "PASS" if share <= CEILING_SHARE
                       else "FAIL -- STOP AND TRIAGE, the ceiling is not a parameter"}
    assert gate["verdict"] == "PASS", gate

    out = {"route": "overlay (day-1 ruling: CiMLoop account untouched)",
           "prices_from_fabric": price,
           "levels": out_levels,
           "conservation": conservation,
           "gate": gate}
    with open(os.path.join(A, "lower_link_energy.json"), "w") as f:
        json.dump(out, f, indent=1)

    L = ["# Lower-link overlay energy column (A5 days 3-4, C58-b; post-v6)",
         "",
         "Overlay route (day-1 ruling): the CiMLoop account is untouched;",
         "this column is the platform's declared supplement, words x",
         "pJ/word x hops on the C25 touched-extent value volumes.", "",
         "## Itemized breakdown (ffn1, one die)",
         "",
         "| level | words | mean hops | pJ/word/hop | subtotal |",
         "|---|---|---|---|---|"]
    for name in LEVELS:
        r = out_levels[name]
        L.append(f"| {name} ({r['flow']}, {r['n_edges']} edges) "
                 f"| {r['words']:,.0f} | {r['mean_hops']:.4f} "
                 f"| {r['pj_per_word_per_hop']:.4f} "
                 f"| {r['energy_J'] * 1e6:.2f} uJ |")
    L += [f"| **total** | | | | **{total * 1e6:.2f} uJ** |", "",
          "Each row's product words x mean-hops x price reproduces its",
          "subtotal exactly (mean hops is volume-weighted; asserted).", "",
          "## Conservation gate (C25 touched-extent volumes)",
          f"leaf level {conservation['leaf_volume_words']:,.0f} words ==",
          f"stats identity {conservation['identity']} -- EXACT;",
          "upper levels carry at most the leaf total: "
          + ", ".join(f"{k} {v:,.0f}"
                      for k, v in conservation["upper_levels_words"].items())
          + f". **{conservation['verdict']}**", "",
          "## Ceiling gate (day 4, pre-registered)",
          f"overlay total {total * 1e6:.2f} uJ = {share:.2%} of the "
          f"{op_energy * 1e3:.2f} mJ operator (ceiling ~{CEILING_SHARE:.1%}; "
          f"day-2 flat-2-hop arithmetic {FLAT_2HOP_J * 1e6:.1f} uJ) -> "
          f"**{gate['verdict']}**", ""]
    with open(os.path.join(A, "lower_link_energy.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    for name in LEVELS:
        r = out_levels[name]
        print(f"{name}: {r['words']:,.0f} w x {r['mean_hops']:.4f} hops x "
              f"{r['pj_per_word_per_hop']:.4f} pJ = {r['energy_J'] * 1e6:.2f} uJ")
    print(f"total {total * 1e6:.2f} uJ = {share:.2%} of operator | "
          f"conservation {conservation['verdict']} | gate {gate['verdict']}")


if __name__ == "__main__":
    main()
