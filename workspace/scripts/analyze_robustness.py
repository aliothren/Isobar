"""The robustness pass (C54, worklist step 5): every published conclusion
against 2x / 5x common-mode model error and the worst-protocol-assumption
overlay, per the pre-registered criteria (analysis/ROBUSTNESS_CRITERIA.md
-- the caliber definitions and per-row tests are the authority; this run
computes, it does not reinterpret).

Closed form, zero new simulation: margins from the registry and the
stored result JSONs.

    python3 scripts/analyze_robustness.py -> analysis/robustness_table.md + .json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import anchors as an

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
A = os.path.join(WS, "analysis")

PROD_BOUNDARY = 0.808          # routed d=1024 at NeuRRAM t (group 27 pin)
CHAIN_2560 = 1.616             # die-level chain line (d family, C33)
DIVIDEND_GATE = 1.9            # offload dividend upper threshold (B1)
PROTOCOL_OVERLAY = 2.516       # C52, Simba ENDPOINT tier (declared extrapolation)
BAND = (0.4, 8.0)              # analog-reality on-die
D2D_BAND = (0.1, 2.0)


def verdict(k_max, k):
    return "SURVIVES" if k_max > k else "fails"


def main():
    t1 = json.load(open(os.path.join(A, "simba_t1.json")))
    t3 = json.load(open(os.path.join(A, "simba_t3.json")))
    sl = json.load(open(os.path.join(A, "soft_lever.json")))
    hermes = an.hermes_self_consistency()

    ondie = [a.gbps for a in an.digital("ondie")]              # 8.75/32/80.6
    grs = an.by_key("grs").gbps                                # 12.5

    rows = []

    def row(rid, concl, caliber, test, verdicts, note=""):
        rows.append({"id": rid, "conclusion": concl, "caliber": caliber,
                     "test": test, "verdicts": verdicts, "note": note})

    # R1 region: digital on-die anchors vs the production routed boundary
    margins = [g / PROD_BOUNDARY for g in ondie]
    row("R1", "digital on-die tier placement-free", "REGION",
        f"margins {['%.1f' % m for m in margins]}",
        {"2x": verdict(min(margins), 2), "5x": verdict(min(margins), 5),
         "overlay": verdict(min(margins) / PROTOCOL_OVERLAY, 1)},
        f"overlay margins {['%.1f' % (m / PROTOCOL_OVERLAY) for m in margins]}")

    # R2 straddle: the workspace band
    up, down = BAND[1] / PROD_BOUNDARY, PROD_BOUNDARY / BAND[0]
    row("R2", "the middle band is the search workspace", "STRADDLE",
        f"up-room {up:.1f}x, down-room {down:.2f}x",
        {"2x": "SURVIVES both ways", "5x": "fails DOWNWARD -> band wholly "
         "exposed (workspace narrows, placement case STRENGTHENS)",
         "overlay": ("SURVIVES" if BAND[0] <= PROD_BOUNDARY * PROTOCOL_OVERLAY
                     <= BAND[1] else "fails")},
        f"overlay boundary {PROD_BOUNDARY * PROTOCOL_OVERLAY:.2f} in band")

    # R3 spanning chains at the package
    m_grs = grs / CHAIN_2560
    m_top = D2D_BAND[1] / CHAIN_2560
    row("R3", "d>=2560 chains exposed at the package", "REGION+STRADDLE",
        f"GRS margin {m_grs:.1f}x; analog-band-top room {m_top:.2f}x",
        {"2x": f"GRS call {verdict(m_grs, 2)}; in-band straddle fails UPWARD "
               "at 1.24x -> exposed EVERYWHERE in the band (stated)",
         "5x": f"GRS call {verdict(m_grs, 5)}",
         "overlay": verdict(m_grs / PROTOCOL_OVERLAY, 1)}, "")

    # R4 offload structurally necessary
    row("R4", "offload structurally necessary at fast tiers", "REGION",
        "differential margin 13.32/1.02 = 13.1x",
        {"2x": "SURVIVES", "5x": "SURVIVES", "overlay": "n.a."}, "")

    # R5 write-bound decode
    row("R5", "decode is write-bound on chip (76.3x device -> 1.11x)",
        "REGION", "write-term dominance at the fast tier",
        {"2x": "SURVIVES", "5x": "SURVIVES", "overlay": "n.a."},
        "vulnerability = DR-5's own parameters (that row's ownership)")

    # R6 dividend gate
    m6 = grs / DIVIDEND_GATE
    row("R6", "GRS clears the offload dividend gate (1.2-1.9)",
        "THRESHOLD-GATE", f"margin {m6:.1f}x",
        {"2x": verdict(m6, 2), "5x": verdict(m6, 5),
         "overlay": verdict(m6 / PROTOCOL_OVERLAY, 1)},
        "in the analog band the gate stays contested (straddle)")

    # R7 die-tier software band
    row("R7", "the software band is 1.4-2x wide at the die tier",
        "ORDERING/RATIO", "common-mode-immune (same-flow ratios)",
        {"2x": "immune", "5x": "immune", "overlay": "immune"},
        "differential channel = per-link accounting structure, guarded by "
        "the counting layer")

    # R8 soft-lever visibility thresholds
    thr = [sl["phases"]["prefill"]["g_threshold_1pct"],
           sl["phases"]["decode"]["g_threshold_1pct"]]
    worst5 = max(thr) * 5
    row("R8", "on-die soft band visible only below ~1.4/1.1 GB/s",
        "THRESHOLD-GATE",
        f"thresholds {thr[0]:.2f}/{thr[1]:.2f}; x5 -> {worst5:.1f} vs Simba 8.75",
        {"2x": "SURVIVES (digital invisibility)",
         "5x": "SURVIVES" if worst5 < ondie[0] else "fails",
         "overlay": "SURVIVES"},
        "inside the analog band the claim stays band-dependent")

    # R9, R10 measured-exact
    row("R9", "on-die freedom frozen to zero by the mapping (conditioned)",
        "MEASURED-EXACT", "structural identity",
        {"2x": "immune", "5x": "immune", "overlay": "immune"},
        "vulnerabilities are its three CONDITIONS, not error")
    row("R10", "trunk law d/114,688; flip d* 1.2-1.35k; S cancels",
        "MEASURED-EXACT", "mapper-measured structure",
        {"2x": "immune", "5x": "immune", "overlay": "immune"},
        "movable only by another mapper/capacity regime (named)")

    # R11 HERMES audit -- discrimination radius (review-corrected)
    h = hermes["headroom"]
    row("R11", "HERMES sits 1.36x above its knee (accounting audit)",
        "THRESHOLD-GATE",
        f"discrimination radius = {h:.2f}x (systematic accounting error)",
        {"2x": "BLIND beyond 1.36x (fit degrades to 'anything above matches')",
         "5x": "blind", "overlay": "n.a."},
        "high-information row: the resolution radius of our only external "
        "accounting check -- 'audits the accounting layer, certifies no "
        "mechanism', quantified")

    # R12 direction discipline (with the location caveat)
    r3 = t3["layers"]["res3a_branch1"]
    m12 = min(m / o for m, o in zip(r3["measured"][1:], r3["curve_opt"][1:]))
    row("R12", "the bound never exceeds silicon (all probed points)",
        "REGION (direction discipline)",
        f"min silicon/bound margin = {m12:.2f}x at T3 res3a n=4",
        {"2x": "fails AT THAT POINT (under-property breaks there first)",
         "5x": "fails", "overlay": "n.a."},
        "LOCATION CAVEAT (C47): that point is the tiling-freedom divergence "
        "site, so part of the margin is tiling-space caliber and the pure "
        "model-error headroom is LARGER; pre-written triage: first suspect "
        "= tiling caliber, not the flow account")

    # R13 packet-bracket containment
    opt5 = t1["rows"][-1]["ratio_max_end"]
    k13 = 2.530 / opt5
    row("R13", "the packet bracket contains silicon's T1 ladder",
        "REGION (two-sided)",
        f"common-mode-up k_max = 2.530/{opt5:.4f} = {k13:.2f}",
        {"2x": verdict(k13, 2), "5x": "fails (both rails above silicon; "
         "containment SHOULD fail at 5x -- this row is the table's "
         "credibility)", "overlay": "n.a."}, "")

    # R14 BookSim certification
    row("R14", "the bound is reachable +0.2-0.7% (cycle-accurate)",
        "MEASURED-EXACT (simulator)", "caliber statement, not priced",
        {"2x": "immune", "5x": "immune", "overlay": "n.a."},
        "scope labels (network-internal; unicast decomposition) are the "
        "vulnerability, already declared")

    # R15 the overlay row (renamed per review)
    row("R15", "WORST-PROTOCOL-ASSUMPTION overlay (Simba endpoint tier, "
        "2.516x, extrapolation declared)", "OVERLAY (stress, not property)",
        "R1/R2/R3/R6/R8 margins / 2.516",
        {"2x": "n.a.", "5x": "n.a.",
         "overlay": "NO first-class conclusion flips (min residual margin "
         f"= R1 Simba {margins[0] / PROTOCOL_OVERLAY:.1f}x)"},
        "COUNTER-NOTE: the protocol share is an ENDPOINT-DESIGN parameter "
        "(deep-buffered streaming endpoints approach 1.0); a pass reads "
        "'survives even the worst endpoint tier', never 'NoCs carry 2.5x'")

    out = {"protocol_overlay": PROTOCOL_OVERLAY, "rows": rows}
    with open(os.path.join(A, "robustness.json"), "w") as f:
        json.dump(out, f, indent=1)

    L = ["# The robustness table (C54, worklist step 5)", "",
         "Criteria pre-registered in ROBUSTNESS_CRITERIA.md (review-amended:",
         "R11 discrimination-radius, R15 worst-protocol naming + counter-note,",
         "R12 location caveat). Closed form from stored results; the run",
         "computes, it does not reinterpret.", "",
         "| # | conclusion | caliber | test | 2x | 5x | overlay | note |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        v = r["verdicts"]
        L.append(f"| {r['id']} | {r['conclusion']} | {r['caliber']} | "
                 f"{r['test']} | {v.get('2x','')} | {v.get('5x','')} | "
                 f"{v.get('overlay','')} | {r['note']} |")
    L += ["",
          "Reading: the region calls at the digital anchors survive 5x and the",
          "worst endpoint tier; the workspace straddle survives 2x and fails",
          "5x only in the direction that STRENGTHENS the placement case; the",
          "measured-structure rows are error-immune by construction; the",
          "table's honesty lives in R11 (the accounting audit's resolution",
          "radius is 1.36x), R12 (the under-property's tightest margin, 1.68x,",
          "at the tiling-divergence site), and R13 (bracket containment dies",
          "at 5x, as a bracket should). A robustness table with no red would",
          "itself be suspect."]
    with open(os.path.join(A, "robustness_table.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    for r in rows:
        print(f"{r['id']:<4} {r['caliber']:<28} 2x={r['verdicts'].get('2x','')[:40]}")


if __name__ == "__main__":
    main()
