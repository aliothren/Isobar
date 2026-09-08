"""O27 main body (C57): static energy + peak concurrency, closed form.

LAYERED CALIBER (the filed discipline, FIXLIST step 8):
1. STRUCTURAL layer, parameter-free: E_static = P_chip x makespan, so the
   static term inherits the latency ordering by construction -- proved on
   the stored scenarios, plus the pairwise CROSSOVER powers P* at which
   the combined (dynamic + static) energy verdict between two scenarios
   flips to the latency verdict: P* = (E1 - E2) / (T2 - T1). These
   crossovers are real results available WITHOUT knowing any idle power.
2. SHARE layer: requires real idle-power inputs (DR values or literature
   anchors under the provenance discipline -- being retrieved; never
   estimated here). Until they land, the share is published as a FUNCTION
   share(P) = P x T / (E_dyn + P x T) over a labeled input grid.
3. PEAK CONCURRENCY, schedule-level ONLY: max simultaneously-active
   instances per operating mode x the calibrated per-instance dynamic
   rate. Boundary sentence, verbatim and shipped with every output:
   "circuit-level peaks (di/dt, IR-drop) are OUT of scope; this platform
   outputs schedule-level concurrency for the power team as an input."

    python3 scripts/analyze_static_energy.py
      -> analysis/static_energy.json + analysis/static_energy.md
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import fabric as fabric_mod

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
A = os.path.join(WS, "analysis")
BOUNDARY = ("circuit-level peaks (di/dt, IR-drop) are OUT of scope; this "
            "platform outputs schedule-level concurrency for the power team "
            "as an input.")
P_GRID_W = [0.1, 0.3, 1.0, 3.0, 10.0, 30.0]

# Literature power anchors (DERIVED, analysis/papers/power_extracts.md):
# neither chip publishes a numeric standby power, so these anchor the
# ACTIVE-CLASS scale of a 256x256 analog array, never a static value.
ACTIVE_W_PER_CORE = {"neurram_130nm": (0.0196, 0.0248),   # 39.1/2 .. 49.7/2 mW
                     "hermes_14nm": (0.101, 0.101)}       # 6.47 W / 64 cores


def main():
    fab = fabric_mod.default()
    out = {"boundary_sentence": BOUNDARY, "phases": {}, "counts": {}}

    for phase in ("prefill", "decode"):
        g = json.load(open(os.path.join(A, f"gpt2_system_totals_{phase}.json")))
        sc = g["scenarios"]
        scen = {k: {"E_dyn_J": sc[f"{k}_E"], "T_s": sc[f"{k}_L"]}
                for k in ("A", "B", "C")}
        # structural: the static term's ordering == the latency ordering
        by_T = sorted(scen, key=lambda k: scen[k]["T_s"])
        # pairwise crossover powers (combined-energy verdict flips)
        crossovers = {}
        keys = list(scen)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                dT = scen[b]["T_s"] - scen[a]["T_s"]
                dE = scen[a]["E_dyn_J"] - scen[b]["E_dyn_J"]
                if abs(dT) < 1e-15:
                    continue
                p = dE / dT
                crossovers[f"{a}vs{b}"] = {
                    "P_star_W": p,
                    "meaning": (f"above this chip static power the combined "
                                f"energy verdict between {a} and {b} follows "
                                f"the latency verdict") if p > 0 else
                               ("energy and latency verdicts already agree "
                                "at every static power (no flip)")}
        share = {k: {f"{p}W": p * scen[k]["T_s"]
                     / (scen[k]["E_dyn_J"] + p * scen[k]["T_s"])
                     for p in P_GRID_W} for k in scen}
        out["phases"][phase] = {"scenarios": scen,
                                "latency_order": by_T,
                                "crossovers_W": crossovers,
                                "static_share_of_total": share}

    # peak concurrency (schedule-level counts on the production fabrics)
    per_die = {"macros": fab.count_below("macro"),
               "cores": fab.count_below("core"),
               "crossbars": fab.count_below("crossbar")}
    g = json.load(open(os.path.join(A, "gpt2_system_totals_prefill.json")))
    p_die_avg = g["scenarios"]["A_E"] / g["scenarios"]["A_L"]   # W, one die working
    out["counts"] = {
        "single_die_single_pass": {"dies": 1, **per_die,
                                   "note": "one operator at a time; all of "
                                           "its die's arrays active"},
        "chain48_single_pass": {"dies": 2, "note": "two dies per layer "
                                "(attention half + FFN half); one layer live"},
        "chain48_pipelined": {"dies": 48,
                              "macros": 48 * per_die["macros"],
                              "crossbars": 48 * per_die["crossbars"],
                              "note": "steady state: every stage live"},
        "per_die_avg_dynamic_W": p_die_avg,
        "pipelined_peak_dynamic_W_estimate": 48 * p_die_avg,
        "estimate_caliber": ("average-rate estimate: per-die dynamic rate = "
                            "scenario-A energy / scenario-A latency on the "
                            "calibrated account, x concurrent dies; a "
                            "schedule-level number per the boundary sentence"),
    }

    # anchored bracket: the decode flip threshold vs the active-class
    # scale of the production die (256 arrays x per-core active power)
    n_arrays = per_die["crossbars"]
    lo = ACTIVE_W_PER_CORE["neurram_130nm"][0] * n_arrays
    hi = ACTIVE_W_PER_CORE["hermes_14nm"][1] * n_arrays
    p_star = out["phases"]["decode"]["crossovers_W"]["AvsB"]["P_star_W"]
    out["anchored_bracket"] = {
        "active_class_scale_W": [lo, hi],
        "scale_provenance": ("cross-technology extrapolation (the third, "
                             "must-be-declared provenance class -- neither "
                             "measured nor single-source derived): the two "
                             "ends come from different technology nodes AND "
                             "device classes (NeuRRAM 130 nm RRAM vs HERMES "
                             "14 nm PCM); the interval is for ORDER-OF-"
                             "MAGNITUDE scaling only, never for point "
                             "conclusions. The production die is the Wan "
                             "device -- a geometric scale-up of the NeuRRAM "
                             "chip -- so prose cites the NeuRRAM end "
                             "(~5.0 W) as primary and the HERMES end as a "
                             "cross-technology reference"),
        "decode_flip_threshold_W": p_star,
        "threshold_as_share_of_active_scale": [p_star / hi, p_star / lo],
        "share_denominator_caliber": ("denominator = FULL-STREAM peak "
                                      "active power (all arrays driven); "
                                      "decode is the lowest-utilization "
                                      "regime, so against decode's OWN "
                                      "active power the ratio grows by an "
                                      "order of magnitude or more -- the "
                                      "precise value is the DR static "
                                      "point item"),
        "statement": ("with the full-stream peak active power as the "
                      "denominator, the decode flip threshold is 0.33-1.7% "
                      "of the active-class scale (against decode's own "
                      "active power the percentage is an order of magnitude "
                      "higher; exact value awaits the DR static point). "
                      "The structural conclusion is denominator-free: the "
                      "flip sits at an absolute 0.085 W, and NeuRRAM's "
                      "power gating is the one published mechanism that "
                      "could dip under it"),
        "caliber": ("both actives are DERIVED (TOPS / TOPS-per-W, "
                    "corroborated), the interval itself is a cross-"
                    "technology extrapolation labeled above -- no published "
                    "static point value exists; the point value stays a DR "
                    "item")}
    with open(os.path.join(A, "static_energy.json"), "w") as f:
        json.dump(out, f, indent=1)

    L = ["# Static energy + peak concurrency (O27, C57; post-v6)", "",
         f"**Boundary (verbatim, ships with every readout):** {BOUNDARY}", "",
         "## 1. Structural layer (parameter-free)",
         "E_static = P_chip x makespan -> the static term inherits the",
         "latency ordering by construction. Crossover powers (real results",
         "needing NO idle-power value): the combined energy verdict between",
         "two scenarios flips to the latency verdict above P*:", ""]
    for phase in ("prefill", "decode"):
        ph = out["phases"][phase]
        L.append(f"### {phase} (latency order: {' < '.join(ph['latency_order'])})")
        for pair, c in ph["crossovers_W"].items():
            if c["P_star_W"] > 0:
                L.append(f"- {pair}: P* = {c['P_star_W']:.2f} W")
            else:
                L.append(f"- {pair}: verdicts already agree (no flip)")
        L.append("")
    L += ["## 2. Share layer (a FUNCTION of the platform input; values",
          "await DR / literature anchors -- never estimated here)", "",
          "| scenario x phase | " + " | ".join(f"{p} W" for p in P_GRID_W) + " |",
          "|---|" + "---|" * len(P_GRID_W)]
    for phase in ("prefill", "decode"):
        for k, row in out["phases"][phase]["static_share_of_total"].items():
            L.append(f"| {k} {phase} | " +
                     " | ".join(f"{row[f'{p}W']:.1%}" for p in P_GRID_W) + " |")
    ab = out["anchored_bracket"]
    L += ["", "## 2b. The anchored bracket (literature actives; DERIVED,",
          "interval = cross-technology extrapolation)", "",
          f"active-class scale of the production die: NeuRRAM end "
          f"{ab['active_class_scale_W'][0]:.1f} W (PRIMARY -- the production "
          f"die is the Wan device, a geometric scale-up of the NeuRRAM "
          f"chip; 130 nm RRAM) .. HERMES end "
          f"{ab['active_class_scale_W'][1]:.1f} W (cross-technology "
          f"reference; 14 nm PCM). 256 arrays x 20-101 mW/core.",
          f"Interval provenance: {ab['scale_provenance']}.",
          f"Decode flip threshold {ab['decode_flip_threshold_W']:.3f} W = "
          f"{ab['threshold_as_share_of_active_scale'][0]:.2%}-"
          f"{ab['threshold_as_share_of_active_scale'][1]:.2%} of that scale "
          f"({ab['share_denominator_caliber']}).",
          f"{ab['statement']}.", f"Caliber: {ab['caliber']}.", ""]
    L += ["", "## 3. Peak concurrency (schedule-level counts)", "",
          "Answers a different question than energy or average power: not",
          "'how much does the run cost' but 'how much must the supply",
          "network deliver in the worst instant'. Three uses: (a) the",
          "power-delivery design input (max concurrent active instances x",
          "calibrated per-instance rate -- our schedule already knows which",
          "instances are live each tick, so this is a zero-cost readout);",
          "(b) a FUNCTION of placement and schedule -- pile the load up and",
          "the peak rises, spread it and it falls -- i.e. a candidate",
          "constraint dimension for the search ('latency-optimal but over",
          "power budget' solutions get pruned); (c) the reviewer's",
          "power-density question gets a column instead of a shrug.", ""]
    for k, v in out["counts"].items():
        L.append(f"- {k}: {v}")
    with open(os.path.join(A, "static_energy.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    for phase in ("prefill", "decode"):
        ph = out["phases"][phase]
        print(phase, "latency order", ph["latency_order"],
              {k: round(v["P_star_W"], 2) for k, v in ph["crossovers_W"].items()})
    print("per-die avg dynamic W:", round(out["counts"]["per_die_avg_dynamic_W"], 3),
          "pipelined peak est W:", round(out["counts"]["pipelined_peak_dynamic_W_estimate"], 1))


if __name__ == "__main__":
    main()
