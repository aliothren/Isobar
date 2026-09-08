"""A5 day 5 (C58-c): the distance rankings become joules.

O1's purpose sentence: DR-1 (here: the C58-a derived prices standing in
for it) "turns the 3.69x/1.70x and 17.8% rankings into joules". This
script does that conversion and checks the STRENGTHENED ORDER PIN.

THE STRUCTURAL RESULT (checked, not assumed): under route (b) the price
of every level is proportional to its slot pitch, so all three on-die
levels share ONE per-leaf-slot price:
    2.9934 pJ / 8 leaf = 1.4967 / 4 = 0.3742 / 1 = 0.374177 pJ/word/leaf.
Every volume x distance ranking therefore converts to joules by a
SINGLE constant: orders and ratios are preserved EXACTLY, by
construction -- 1.70x stays 1.70x, 3.69x stays 3.69x.

PRE-REGISTERED (before the region stage ran):
  1. ORDER pin, maps: the per-crossbar orderings are unchanged (exact,
     see above). If the identity assert fails, that IS the finding.
  2. ORDER pin, region: the committed 17.8% metric adds macro-index and
     core-index steps ISOTROPICALLY; physically a macro step is 800 um
     and a core step 400 um, so the joules version re-scores with
     physical lengths. Expectation: dataflow order STAYS better than
     size order; the drop percentage is a NEW number (no prediction
     filed). If the order flips, that is a finding to record, never a
     parameter to adjust.
  3. THE SEARCH-SIDE SENTENCE (filed with the review's strengthening):
     these orders are robust to pricing ONLY BECAUSE price ~ length
     (route b). A DR-1 that returns prices NOT proportional to wire
     length can genuinely reorder the maps -- "the two levels' energy
     weights restructured the ranking" would then be a recorded
     finding. The search may treat distance rankings as energy rankings
     exactly as long as the proportionality stands.

CALIBER LABELS: the per-crossbar map prices all three levels (the macro
share sits inside the CiMLoop account; the overlay column charges only
core+crossbar) and the region readout prices inter-operator activation
transport (a traffic class outside both accounts until now) -- both are
ATTRIBUTION READOUTS at the uniform per-leaf price, not account
entries; no total moves.

Two stages (io_study lives on the host, numpy in the container):
    python3 scripts/analyze_ranking_joules.py region   # HOST
    python3 scripts/analyze_ranking_joules.py main     # CONTAINER
      -> analysis/ranking_joules.json + analysis/ranking_joules.md
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.join(HERE, "..")
sys.path.insert(0, os.path.abspath(WS))
A = os.path.join(WS, "analysis")
FX = os.path.join(WS, "tests", "fixtures")
REGION_TMP = os.path.join(A, "ranking_joules_region.json")

PER_LEAF_PJ = 0.374176923           # asserted against the fabric in main()
LEAF_UM = 100.0                     # crossbar pitch = the leaf slot
MACRO_STEP_LEAF = 8.0               # 800 um / 100 um
CORE_STEP_LEAF = 4.0                # 400 um / 100 um
N_LAYERS = 12


def _vw_allpair(a, b, sx=1.0, sy=1.0):
    ds = [abs(ma - mb) * sx + abs(ca - cb) * sy
          for (ma, ca) in a for (mb, cb) in b]
    return sum(ds) / len(ds)


def region():
    """HOST stage: committed metric reproduced + physical-length re-score."""
    sys.path.insert(0, os.path.join(WS, "..", "io_study", "scripts"))
    from die_locality import region_cells, DATAFLOW, SIZE_ORDER, DATAFLOW_ORDER
    out = {"edges": [f"{p}->{c}" for p, c, _ in DATAFLOW],
           "volumes_words": [v for _, _, v in DATAFLOW], "orders": {}}
    for order, name in ((SIZE_ORDER, "size order"),
                        (DATAFLOW_ORDER, "dataflow order")):
        cells = region_cells(order)
        idx = [_vw_allpair(cells[p], cells[c]) for p, c, _ in DATAFLOW]
        phys = [_vw_allpair(cells[p], cells[c],
                            sx=MACRO_STEP_LEAF, sy=CORE_STEP_LEAF)
                for p, c, _ in DATAFLOW]
        out["orders"][name] = {
            "vw_index_total": sum(d * v for d, (_, _, v) in zip(idx, DATAFLOW)),
            "vw_phys_leaf_total": sum(d * v
                                      for d, (_, _, v) in zip(phys, DATAFLOW))}
    s, d = out["orders"]["size order"], out["orders"]["dataflow order"]
    out["index_drop_pct"] = 100 * (1 - d["vw_index_total"] / s["vw_index_total"])
    out["phys_drop_pct"] = 100 * (1 - d["vw_phys_leaf_total"]
                                  / s["vw_phys_leaf_total"])
    with open(REGION_TMP, "w") as f:
        json.dump(out, f, indent=1)
    print(f"committed index metric drop {out['index_drop_pct']:.1f}% "
          f"(must read 17.8); physical-length drop {out['phys_drop_pct']:.1f}%")


def main():
    import numpy as np

    import scripts.crossbar_comm as cc
    from scripts import fabric as fabric_mod

    # the uniform per-leaf price, asserted from the fabric itself
    fab = fabric_mod.default()
    leaf = fab.level("crossbar").slot_pitch_um
    derived = json.load(open(os.path.join(A, "lower_link_prices.json")))
    prices = {"macro": derived["anchor"]["effective_pj_per_value_word"],
              "core": fab.level("core").link.pj_per_word,
              "crossbar": fab.level("crossbar").link.pj_per_word}
    per_leaf = {n: p / (fab.level(n).slot_pitch_um / leaf)
                for n, p in prices.items()}
    vals = list(per_leaf.values())
    assert max(vals) - min(vals) < 1e-9, per_leaf   # the structural identity
    k = vals[0]
    assert abs(k - PER_LEAF_PJ) < 1e-6

    td = tempfile.mkdtemp()
    try:
        shutil.copy(os.path.join(FX, "ffn1_prefill_map.txt"),
                    os.path.join(td, "timeloop-mapper.map.txt"))
        shutil.copy(os.path.join(FX, "ffn1_prefill_stats.txt"),
                    os.path.join(td, "timeloop-mapper.stats.txt"))
        maps = {}
        for tag, path in (("2x4_default", "models/fabric/mlx300.yaml"),
                          ("3x3_variant", "models/fabric/mlx300_3x3.yaml")):
            fv = fabric_mod.from_yaml(os.path.join(WS, path))
            _, per_xb, _, _ = cc.build_flows(td, fabric=fv, verbose=False)
            act = np.asarray(per_xb)[np.asarray(per_xb) > 0]
            maps[tag] = {
                "n_active": int(len(act)),
                "ratio_distance_ranking": float(act.max() / act.min()),
                "min_uJ": float(act.min() * k * 1e-6),
                "max_uJ": float(act.max() * k * 1e-6),
                "ratio_joules": float((act.max() * k) / (act.min() * k)),
                "caliber": ("attribution readout at the uniform per-leaf "
                            "price (all three levels; the macro share is "
                            "in-account, the overlay charges core+crossbar "
                            "only) -- not an account entry")}
    finally:
        shutil.rmtree(td, ignore_errors=True)

    reg = json.load(open(REGION_TMP))
    for name, o in reg["orders"].items():
        o["energy_uJ_per_layer"] = o["vw_phys_leaf_total"] * k * 1e-6
        o["energy_uJ_model_pass"] = o["energy_uJ_per_layer"] * N_LAYERS
    s, d = reg["orders"]["size order"], reg["orders"]["dataflow order"]
    reg["order_pin"] = ("PRESERVED" if d["vw_phys_leaf_total"]
                        < s["vw_phys_leaf_total"] else
                        "FLIPPED -- record as a finding, do not adjust")
    reg["gap_uJ_per_layer"] = (s["energy_uJ_per_layer"]
                               - d["energy_uJ_per_layer"])

    out = {"uniform_per_leaf_pj": k,
           "structural_sentence": (
               "route (b) prices every level proportionally to its pitch, "
               "so one constant converts volume x distance to joules: "
               "orders and ratios preserved EXACTLY by construction"),
           "search_side_sentence": (
               "distance rankings may be read as energy rankings exactly "
               "as long as price ~ length holds; a DR-1 with prices NOT "
               "proportional to wire length can genuinely reorder the "
               "maps -- that would be a recorded finding, never a "
               "parameter adjustment"),
           "per_crossbar_maps": maps,
           "region": reg}
    with open(os.path.join(A, "ranking_joules.json"), "w") as f:
        json.dump(out, f, indent=1)

    m24, m33 = maps["2x4_default"], maps["3x3_variant"]
    L = ["# Rankings -> joules (A5 day 5, C58-c; post-v6)", "",
         f"One constant does it: {k:.6f} pJ per word per leaf slot "
         f"(= 2.9934/8 = 1.4967/4 = 0.3742/1; route b, price ~ pitch).",
         out["structural_sentence"] + ".", "",
         "## Per-crossbar cost maps, now in energy",
         "",
         "| layout | busiest crossbar | lightest | ratio (was, distance) |",
         "|---|---|---|---|",
         f"| 2x4 default | {m24['max_uJ']:.3f} uJ | {m24['min_uJ']:.3f} uJ "
         f"| {m24['ratio_joules']:.2f}x ({m24['ratio_distance_ranking']:.2f}x) |",
         f"| 3x3 variant | {m33['max_uJ']:.3f} uJ | {m33['min_uJ']:.3f} uJ "
         f"| {m33['ratio_joules']:.2f}x ({m33['ratio_distance_ranking']:.2f}x) |",
         "", f"Caliber: {m24['caliber']}.", "",
         "## Region placement (the 17.8% ranking), now in energy",
         "",
         f"Committed index metric reproduced: {reg['index_drop_pct']:.1f}% "
         f"(untouched). Physical-length re-score (macro step 800 um, core "
         f"step 400 um): drop {reg['phys_drop_pct']:.1f}%, order "
         f"**{reg['order_pin']}**.",
         "",
         "| floorplan | uJ per layer | uJ per model pass (x12) |",
         "|---|---|---|"]
    for name in ("size order", "dataflow order"):
        o = reg["orders"][name]
        L.append(f"| {name} | {o['energy_uJ_per_layer']:.2f} "
                 f"| {o['energy_uJ_model_pass']:.2f} |")
    L += ["", f"Gap: {reg['gap_uJ_per_layer']:.2f} uJ per layer. Caliber: "
          "inter-operator activation transport priced at the same per-leaf "
          "constant -- an attribution readout (this traffic class sits in "
          "neither the CiMLoop account nor the overlay column).", "",
          "## The search-side sentence (pre-registered strengthening)",
          out["search_side_sentence"] + ".", ""]
    with open(os.path.join(A, "ranking_joules.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    print("maps:", {t: round(m["ratio_joules"], 3) for t, m in maps.items()},
          "| region committed", round(reg["index_drop_pct"], 1), "% phys",
          round(reg["phys_drop_pct"], 1), "% order", reg["order_pin"],
          "| gap", round(reg["gap_uJ_per_layer"], 2), "uJ/layer")


if __name__ == "__main__":
    {"region": region, "main": main}[sys.argv[1] if len(sys.argv) > 1 else "main"]()
