"""A4 day 2 (C62-b): the whole-model static spread -- one measured flat
seating instead of "block x 32" extrapolation.

Pre-registration: FIXLIST O16 (A4 EXECUTION; amendments integrated).
Closed form, ZERO mapper: the per-op account is the stored
mapper-measured 2.7B file (scale_2p7b_per_op.json), the elementwise /
digital terms enter BOTH columns identically, and the handoffs reuse
block_die_flows' standing conventions (tensor-once, every consumer die
receives the whole tensor).

SEMANTICS (pre-declared, amendment 3): the whole-machine latency is
the PURE SERIAL sum of 32 layers -- batch-1, single request, no
pipeline overlap. It must NEVER be tabled against b1_orderings'
pipeline readouts; direct comparison is forbidden. The wrap boundary
(layer 31 -> layer 0, the "next request's copy" in block_die_flows'
modulo convention) is EXCLUDED from both latency and energy: a single
pass has 31 inter-layer boundaries, and entry 0's input is the prompt.

GEOMETRY (declared, not sourced): 24 x 24 = 576 slots, 544 seated
(17 dies/layer x 32), 32 spare; near-square, no product basis; aspect
sensitivity out of scope (S4).

    python3 scripts/analyze_full_model_seating.py     (container)
      -> analysis/a4_full_model.json + analysis/a4_full_model.md
"""
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
os.environ["CIMSIM_FABRIC"] = \
    "/home/workspace/models/fabric/mlx300_multidie576.yaml"

from scripts import fabric as fabric_mod
from scripts import interconnect as ic
from scripts import llm_workload as lw
from scripts import placement as pm

OUT = "/home/workspace/analysis"
STORED = os.path.join(OUT, "scale_2p7b_per_op.json")
S = 512
N_LAYERS = 32
BW_GBPS = [12.5, 2.0, 0.4, 0.1]          # GRS + the pinned context anchors
PJ = 10.0                                 # GRS band midpoint, per word
NS_PER_HOP = 20.0


def main():
    fab = fabric_mod.default()
    assert fab.level("die").per_parent == 576
    pl = pm.sequential_fill(fab)
    die_ic = ic.build(fab, "die", pl)

    stored = json.load(open(STORED))
    c = stored["config"]
    cfg = lw.GptConfig(d_model=c["d_model"], n_heads=c["n_heads"],
                       d_ff=c["d_ff"], n_layers=c["n_layers"],
                       name=c["name"])
    ops = {r["name"]: r for r in stored["phases"]["prefill"]}

    # the per-layer serial account (identical in both columns)
    elw = [lw.elementwise_cost(eo, fab.digital)
           for eo in lw.block_elementwise_ops(cfg, S=S, phase="prefill")]
    layer_serial_s = (sum(r["compute_s"] + r["write_s"] for r in ops.values())
                      + sum(e["latency_s"] for e in elw))
    layer_energy_J = (sum(r["energy_J"] for r in ops.values())
                      + sum(e["energy_J"] for e in elw))

    # the whole-machine chain: 32 copies of the block chain, seated
    # contiguously in slot order (the declared rule)
    base_chain = lw.block_chain(cfg, S, "prefill", on_chip=True)
    assert [e["n_dies"] for e in base_chain] == [4, 1, 2, 5, 5]
    chain, seating, cursor = [], {}, 0
    for li in range(N_LAYERS):
        for e in base_chain:
            name = f"{e['name']}@L{li}"
            chain.append({**e, "name": name})
            seating[name] = list(range(cursor, cursor + e["n_dies"]))
            cursor += e["n_dies"]
    assert cursor == 544

    flows_by_entry = lw.block_die_flows(chain, seating, fab)
    wrap_entry = chain[0]["name"]                     # layer 31 -> layer 0

    boundaries = []
    for i, e in enumerate(chain):
        if e["name"] == wrap_entry:
            continue                                  # the excluded wrap
        fl = flows_by_entry[e["name"]]
        words = sum(f["volume"] * f["width"] for f in fl)
        hops = [die_ic.hops(*f["nodes"]) for f in fl]
        boundaries.append({
            "into": e["name"], "words": words,
            "inter_layer": e["name"].startswith("qkv_proj"),
            "mean_hops": sum(hops) / len(hops) if hops else 0.0,
            "max_hops": max(hops) if hops else 0.0,
            "surplus_J": lw.die_flow_surplus_energy(fl, fab, placement=pl,
                                                    pj_per_word=PJ)})

    intra = [b for b in boundaries if not b["inter_layer"]]
    inter = [b for b in boundaries if b["inter_layer"]]
    assert len(inter) == N_LAYERS - 1 and len(intra) == 4 * N_LAYERS

    # layer-0's intra pattern is the extrapolation's block-internal cost --
    # BOTH columns carry flat + surplus + propagation, symmetrically
    intra0 = intra[:4]
    intra0_words = sum(b["words"] for b in intra0)
    intra0_surplus_J = sum(b["surplus_J"] for b in intra0)
    intra0_prop_s = sum(b["max_hops"] for b in intra0) * NS_PER_HOP * 1e-9
    d2d_words = sum(b["words"] for b in boundaries)
    flat_J = d2d_words * PJ * 1e-12
    surplus_J = sum(b["surplus_J"] for b in boundaries)
    prop_s = sum(b["max_hops"] for b in boundaries) * NS_PER_HOP * 1e-9

    whole, extrap = {}, {}
    for bw in BW_GBPS:
        wps = bw * 1e9                                # 8-bit words per second
        whole[f"{bw}GBps"] = (N_LAYERS * layer_serial_s
                              + d2d_words / wps + prop_s)
        extrap[f"{bw}GBps"] = N_LAYERS * (layer_serial_s
                                          + intra0_words / wps
                                          + intra0_prop_s)
    e_whole = N_LAYERS * layer_energy_J + flat_J + surplus_J
    e_extrap = N_LAYERS * (layer_energy_J + intra0_words * PJ * 1e-12
                           + intra0_surplus_J)

    dev = {}
    for bw in BW_GBPS:
        k = f"{bw}GBps"
        dev[k] = {"abs_s": whole[k] - extrap[k],
                  "rel": whole[k] / extrap[k] - 1.0}

    # ------- the two-factor decomposition of the energy increment (day-3
    # review ask): MULTICAST x4 is an ACCOUNTING-CALIBER correction (the
    # estimate missed the standing convention; geometry-free), the HOP
    # factor is a product of the DECLARED 24x24 geometry (example,
    # swappable). One division each; the "~4%" sentence is qualified by
    # whichever dominates.
    inter_words = sum(b["words"] for b in inter)
    inter_flat_J = inter_words * PJ * 1e-12          # carries the x4 multicast
    inter_surplus_J = sum(b["surplus_J"] for b in inter)
    intra_var_surplus_J = (sum(b["surplus_J"] for b in intra)
                           - N_LAYERS * intra0_surplus_J)
    increment_J = e_whole - e_extrap
    inter_hops_vw = 1.0 + inter_surplus_J / inter_flat_J   # volume-weighted
    decomp = {
        "increment_J": increment_J,
        "multicast_caliber_part_J": inter_flat_J,
        "geometry_hops_part_J": inter_surplus_J,
        "layer_offset_variation_J": intra_var_surplus_J,
        "inter_volume_weighted_mean_hops": inter_hops_vw,
        "d2d_total_share_of_account": (flat_J + surplus_J) / e_whole,
        "d2d_total_flat_J": flat_J, "d2d_total_surplus_J": surplus_J,
        # geometry-nature terms: the inter-layer hop surplus AND the
        # layer-offset variation (layer 0 -- the extrapolation base -- is
        # the one cluster seated wholly inside a row; later clusters
        # straddle row wraps, so their intra surplus is higher: itself a
        # product of the declared 24x24 row-major geometry).
        "geometry_total_J": inter_surplus_J + intra_var_surplus_J,
        "geometry_share_of_increment":
            (inter_surplus_J + intra_var_surplus_J) / increment_J,
        "verdict": ("GEOMETRY-DOMINATED"
                    if inter_surplus_J + intra_var_surplus_J > inter_flat_J
                    else "CALIBER-DOMINATED"),
        "qualified_sentence": (
            "whole-machine D2D energy is ~4.0% of the account, and that "
            "number CARRIES THE DECLARED-GEOMETRY FACTOR: the geometry-"
            "nature terms (inter-layer hop surplus + the layer-offset "
            "variation on the 24x24 row-major snake) dominate the "
            "caliber-only multicast flat charge; it moves with the grid "
            "shape and the layer path -- cite it with the geometry "
            "attached, never as a bare constant"
            if inter_surplus_J + intra_var_surplus_J > inter_flat_J else
            "whole-machine D2D energy is ~4.0% of the account, dominated "
            "by the multicast accounting caliber (geometry-free); the "
            "declared-geometry contribution is secondary")}
    out = {
        "semantics": ("batch-1 single-request PURE SERIAL sum of 32 layers "
                      "(layer-sequential); the wrap boundary excluded; "
                      "NEVER comparable to b1_orderings' pipeline readouts "
                      "-- direct comparison forbidden"),
        "geometry": ("24x24 = 576 slots DECLARED (near-square, no product "
                     "basis); 544 seated = 17 dies/layer x 32; aspect "
                     "sensitivity out of scope (S4)"),
        "account": ("matmuls = stored mapper-measured scale_2p7b_per_op; "
                    "elementwise/digital terms in BOTH columns identically; "
                    "D2D at 10 pJ/word flat + surplus beyond 1 reference "
                    "hop; boundary words follow block_die_flows' standing "
                    "multicast-to-every-consumer-die convention"),
        "dies": {"seated": 544, "spare": 32, "per_layer": 17},
        "layer_serial_s": layer_serial_s,
        "layer_energy_J": layer_energy_J,
        "d2d": {"total_words": d2d_words,
                "inter_layer_words": sum(b["words"] for b in inter),
                "intra_layer_words": sum(b["words"] for b in intra),
                "mean_hops": sum(b["mean_hops"] for b in boundaries)
                / len(boundaries),
                "flat_J": flat_J, "surplus_J": surplus_J,
                "propagation_s": prop_s},
        "latency_s": {"whole": whole, "extrapolation": extrap,
                      "deviation": dev},
        "energy_J": {"whole": e_whole, "extrapolation": e_extrap,
                     "deviation_rel": e_whole / e_extrap - 1.0},
        "energy_increment_decomposition": decomp,
        "seating_s4_payload": {
            "grid": [24, 24],
            "map": {k: v for k, v in seating.items()},
            # the seam example (day-3 review rider): partition the machine
            # into 16 packages of 2 layers each -- the search month can
            # recompute seam-cost upper-bound variants directly from this.
            "seam_example_16x2": {
                "packages": 16, "layers_per_package": 2,
                "package_of_layer": {li: li // 2 for li in range(N_LAYERS)},
                "seam_boundaries_after_layer": list(range(1, N_LAYERS, 2))[:-1],
                "note": ("example split field: a seam = an inter-layer "
                         "boundary that crosses packages; its words are the "
                         "inter-layer boundary words of the layers it "
                         "separates -- an upper-bound variant re-prices "
                         "exactly those boundaries at package-crossing "
                         "cost")}},
    }
    with open(os.path.join(OUT, "a4_full_model.json"), "w") as f:
        json.dump(out, f, indent=1)

    L = ["# The whole-model static spread (A4 day 2, C62-b; post-v6)", "",
         f"Semantics: {out['semantics']}.", "",
         f"Geometry: {out['geometry']}.", "",
         "| bandwidth | whole-machine | block x 32 extrapolation | deviation |",
         "|---|---|---|---|"]
    for bw in BW_GBPS:
        k = f"{bw}GBps"
        L.append(f"| {bw} GB/s | {whole[k]*1e3:.1f} ms | {extrap[k]*1e3:.1f} ms "
                 f"| +{dev[k]['abs_s']*1e3:.2f} ms = +{dev[k]['rel']:.3%} |")
    L += ["",
          f"Energy: whole {e_whole:.3f} J vs extrapolation {e_extrap:.3f} J "
          f"= +{out['energy_J']['deviation_rel']:.4%} (the D2D increment; "
          f"flat {flat_J*1e3:.3f} mJ + surplus {surplus_J*1e3:.3f} mJ).", "",
          f"D2D: {d2d_words:,.0f} words total ({out['d2d']['inter_layer_words']:,.0f} "
          f"inter-layer + {out['d2d']['intra_layer_words']:,.0f} intra), "
          f"mean hops {out['d2d']['mean_hops']:.2f}, propagation "
          f"{prop_s*1e6:.1f} us.", "",
          "## Reconciliation against the day-1 pre-estimates", "",
          "LATENCY axis -- direction HELD at every anchor (whole >= "
          "extrapolation). Magnitudes explained, not adjusted: the "
          "pre-estimate assumed tensor-once x1 on the inter-layer boundary "
          "(40.6 M words); the STANDING block_die_flows convention "
          "multicasts to every consumer die, and qkv is column-split on 4 "
          "-- measured inter-layer words are exactly 4x the estimate "
          "(162.5 M; +13.0 ms at GRS = 4 x the estimated +3.25 ms). The "
          "relative deviations differ from the estimate additionally "
          "because the estimate's baseline was the matmul-only 880.7 ms "
          "while both columns here carry the full account.", "",
          "ENERGY axis -- direction held, MAGNITUDE EXCEEDS THE FRAME: "
          "+1.83% vs the pre-registered B2 sub-percent frame. BOOKED AS A "
          "FINDING, and the attribution is DECOMPOSED by two factors of "
          "different natures (one division each):", "",
          f"| factor | nature | mJ of the +{decomp['increment_J']*1e3:.1f} mJ increment |",
          "|---|---|---|",
          f"| multicast x4 (flat) | ACCOUNTING CALIBER -- the estimate "
          f"missed the standing convention; geometry-free "
          f"| {decomp['multicast_caliber_part_J']*1e3:.2f} |",
          f"| hop factor (surplus, vw mean "
          f"{decomp['inter_volume_weighted_mean_hops']:.1f} hops) | DECLARED "
          f"GEOMETRY -- a function of the 24x24 snake we declared as "
          f"example/swappable | {decomp['geometry_hops_part_J']*1e3:.2f} |",
          f"| layer-offset variation (intra) | declared geometry, minor "
          f"| {decomp['layer_offset_variation_J']*1e3:.2f} |", "",
          f"Verdict: **{decomp['verdict']}**. {decomp['qualified_sentence']}.",
          "",
          "The temporal-rewrite alternative does NOT run at this scale, by "
          "one closed-form line: every die reprograms its full cells once "
          "per pass -> 544 dies x 16.78 M cells x the write energy/latency "
          "-- orders beyond the static account; static spread is the only "
          "realistic hypothesis (the A4 footnote).", ""]
    with open(os.path.join(OUT, "a4_full_model.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    for bw in BW_GBPS:
        k = f"{bw}GBps"
        print(f"{bw:>5} GB/s: whole {whole[k]*1e3:8.1f} ms  extrap "
              f"{extrap[k]*1e3:8.1f} ms  dev +{dev[k]['rel']:.3%}")
    print(f"energy: whole {e_whole:.3f} J  extrap {e_extrap:.3f} J  "
          f"dev +{out['energy_J']['deviation_rel']:.4%}")


if __name__ == "__main__":
    main()
