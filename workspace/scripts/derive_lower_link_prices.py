"""A5 day 2 (C58-a): derive the lower-level link unit prices -- route (b).

DAY-1 ROUTE RULING (user, 2026-09-08; full record in FIXLIST O1): the
OVERLAY route -- the CiMLoop account keeps its inherited silicon
calibration; core/crossbar traffic is priced as a DECLARED supplement
outside it (D2D-surplus convention: words x pJ/word x hops). These
prices feed that overlay, never the calibrated account.

DAY-2 PROVENANCE RULING (user): route (b), geometric scaling from the
calibrated macro anchor -- NOT (a) the 1 pJ/word example default, which
was a safety sentinel built to prove the C25 ceiling, not an estimate.
The chain, every step with a named source:

  1. ANCHOR   the macro-level link IS silicon-calibrated (the wan
              CiMLoop account's `router` component): E_router on the
              frozen ffn1 fixture.
  2. CALIBER  divide by the C25 VALUE-word volume through the
              glb<->macro boundary (crossbar_comm.build_flows) ->
              effective pJ per value-word at reference_hops = 1.
  3. GEOMETRY energy ~ wire capacitance ~ length (the promise filed on
              slot_pitch_um at C38); hop length = the level's declared
              slot pitch, so price scales by the pitch ratio
              (macro 800 um -> core 400 um -> crossbar 100 um).

Steps 1-2 inherit the silicon calibration; step 3 uses the C38
platform-declared geometry (example defaults until the company fills
real pitches) -- so the result is DERIVED with both dependencies named.

FALLBACK (pre-registered, day 2): (a) 1 pJ/word EXAMPLE DEFAULT is used
ONLY if the geometry chain breaks (a level without slot_pitch_um), and
carries the label "EXAMPLE DEFAULT" -- a DIFFERENT provenance class,
never silently mixed with (b). DR-1's arrival replaces the constants
outright; under the overlay route that is a value swap, not a model
change.

ACCEPTANCE GATE (the one number pre-registered before this script ran):
charging the ffn1 value volumes at the derived prices must land inside
the C25 ceiling arithmetic (~2% of the operator at 2 hops) -- two
independent arithmetics agreeing, or STOP and triage.

    python3 scripts/derive_lower_link_prices.py
      -> analysis/lower_link_prices.json + analysis/lower_link_prices.md
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

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
A = os.path.join(WS, "analysis")
FX = os.path.join(WS, "tests", "fixtures")

FALLBACK_PJ_PER_WORD = 1.0            # route (a): EXAMPLE DEFAULT sentinel
ANCHOR_LEVEL = "macro"                # the silicon-calibrated link level
LOWER_LEVELS = ("core", "crossbar")   # the two unpriced levels (O1)
CEILING_HOPS = 2.0                    # the C25 ceiling arithmetic's hop count
CEILING_SHARE = 0.025                 # ~2%: the pre-registered gate


def derive(fab=None):
    """The (b)-route derivation; falls back to (a) per the filed rule."""
    fab = fab or fabric_mod.default()

    # steps 1-2: the calibrated anchor in value-word caliber
    lv = pa.perceive(os.path.join(FX, "ffn1_prefill_stats.txt"))
    e_router = lv["router"]["energy_J"]
    td = tempfile.mkdtemp()
    try:
        shutil.copy(os.path.join(FX, "ffn1_prefill_map.txt"),
                    os.path.join(td, "timeloop-mapper.map.txt"))
        shutil.copy(os.path.join(FX, "ffn1_prefill_stats.txt"),
                    os.path.join(td, "timeloop-mapper.stats.txt"))
        flows, _, _, _ = cc.build_flows(td, verbose=False)
    finally:
        shutil.rmtree(td, ignore_errors=True)
    vols = {}
    for f in flows:
        vols[f["level"]] = vols.get(f["level"], 0.0) + f["volume"]
    v_macro = vols["glb<->macro"]
    macro_pj = e_router * 1e12 / v_macro

    # step 3: geometric scaling by the declared slot pitches
    pitch = {name: fab.level(name).slot_pitch_um
             for name in (ANCHOR_LEVEL,) + LOWER_LEVELS}
    out = {"anchor": {"level": ANCHOR_LEVEL,
                      "router_energy_J_ffn1": e_router,
                      "value_words_glb_macro_ffn1": v_macro,
                      "effective_pj_per_value_word": macro_pj,
                      "reference_hops": 1.0},
           "value_volumes_ffn1": vols,
           "slot_pitch_um": pitch,
           "prices": {}}
    for name in LOWER_LEVELS:
        if pitch[name] is None or pitch[ANCHOR_LEVEL] is None:
            out["prices"][name] = {
                "pj_per_word": FALLBACK_PJ_PER_WORD,
                "route": "a",
                "provenance": ("EXAMPLE DEFAULT -- the geometry chain is "
                               "broken (missing slot_pitch_um); the C25 "
                               "sentinel value, NOT an estimate")}
        else:
            ratio = pitch[name] / pitch[ANCHOR_LEVEL]
            out["prices"][name] = {
                "pj_per_word": macro_pj * ratio,
                "pitch_ratio_to_anchor": ratio,
                "route": "b",
                "provenance": ("DERIVED: silicon-calibrated macro anchor "
                               "(router energy / C25 value words, "
                               "reference_hops 1) x C38 declared pitch "
                               "ratio (energy ~ wire capacitance ~ "
                               "length); geometry side is platform-"
                               "declared example defaults until real "
                               "pitches arrive; DR-1 replaces outright")}

    # the pre-registered acceptance gate: reproduce the C25 ceiling
    op_energy = sum(v.get("energy_J", 0.0) for v in lv.values())
    charged = {"core": vols["macro<->core"]
               * out["prices"]["core"]["pj_per_word"] * 1e-12,
               "crossbar": vols["core<->crossbar"]
               * out["prices"]["crossbar"]["pj_per_word"] * 1e-12}
    total_2hop = sum(charged.values()) * CEILING_HOPS
    out["ceiling_gate"] = {
        "operator_energy_J_ffn1": op_energy,
        "charged_1hop_J": charged,
        "total_at_2hops_J": total_2hop,
        "share_of_operator": total_2hop / op_energy,
        "c25_ceiling": CEILING_SHARE,
        "verdict": "PASS" if total_2hop / op_energy <= CEILING_SHARE
                   else "FAIL -- STOP AND TRIAGE, do not touch the ceiling"}
    return out


def main():
    out = derive()
    with open(os.path.join(A, "lower_link_prices.json"), "w") as f:
        json.dump(out, f, indent=1)
    an, pr, cg = out["anchor"], out["prices"], out["ceiling_gate"]
    L = ["# Lower-level link unit prices (A5 day 2, C58-a; post-v6)", "",
         "Route (b) -- geometric scaling from the calibrated macro anchor;",
         "these prices feed the OVERLAY (day-1 ruling), never the CiMLoop",
         "account. DR-1's arrival replaces the constants outright.", "",
         "## The chain",
         f"1. anchor: router (macro link, silicon-calibrated) on ffn1 = "
         f"{an['router_energy_J_ffn1'] * 1e6:.2f} uJ",
         f"2. caliber: / {an['value_words_glb_macro_ffn1']:,.0f} C25 "
         f"value-words (glb<->macro) = "
         f"{an['effective_pj_per_value_word']:.3f} pJ/word @ 1 hop",
         "3. geometry (C38 declared pitches, example defaults): "
         + ", ".join(f"{k} {v:.0f} um" for k, v in out["slot_pitch_um"].items()),
         ""]
    for name in LOWER_LEVELS:
        p = pr[name]
        L.append(f"- **{name}**: {p['pj_per_word']:.3f} pJ/word "
                 f"(route {p['route']}, x{p.get('pitch_ratio_to_anchor', '-')} "
                 f"of anchor). {p['provenance']}")
    L += ["", "## Acceptance gate (pre-registered): the C25 ceiling",
          f"charging ffn1's value volumes at these prices, 2 hops: "
          f"{cg['total_at_2hops_J'] * 1e6:.1f} uJ = "
          f"{cg['share_of_operator']:.2%} of the "
          f"{cg['operator_energy_J_ffn1'] * 1e3:.2f} mJ operator "
          f"(ceiling ~{CEILING_SHARE:.1%}) -> **{cg['verdict']}**",
          "",
          "Fallback rule (pre-registered): route (a) 1 pJ/word EXAMPLE",
          "DEFAULT only if a slot_pitch_um is missing, labeled as its own",
          "provenance class -- never silently mixed with (b).", ""]
    with open(os.path.join(A, "lower_link_prices.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    print("macro anchor", round(an["effective_pj_per_value_word"], 3), "pJ/word;",
          {k: round(v["pj_per_word"], 3) for k, v in pr.items()},
          "| ceiling gate:", cg["verdict"],
          f"({cg['share_of_operator']:.2%})")


if __name__ == "__main__":
    main()
