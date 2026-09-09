"""A2 day 1 (C61): the hand gate -- a forced C split through the MAIN path.

The row-split mechanism had one closed-form endorsement on the Simba
path (res4b C:4, psum x3 in Simba's 24-bit caliber); what it never had
is the MAIN path: mapper -> traffic extraction -> flow structure. This
gate runs ONE hand-computable operator with a FORCED die-level C split
and locks every readout against hand integers written below BEFORE the
run. Extraction wrong => stop here and fix extraction; no scans.

THE HAND OPERATOR (chosen so every number is exact):
    Op(P=128, C=16384, M=1024), static.
    weight cells = C x M x 2 slices = 33,554,432 = EXACTLY 2 dies
    (DIE_WEIGHT_CELLS = 256 crossbars x 256 x 256 = 16,777,216); C:2 ->
    per-die piece 8192 x 1024 = exactly one full die, all powers of two
    (no O10 utilisation loss).

HAND INTEGERS (C25 value caliber):
    die split           C:2 (planner AND the mapping's chip level)
    per-die DOWN edge   P x C/2 = 128 x 8192 = 1,048,576 words -- the die's
                        DISJOINT input slice (a row split multicasts
                        nothing: 2 x 1,048,576 = 2,097,152 = P x C, the
                        full input exactly once -- conservation)
    per-die UP edge     P x M = 128 x 1024 = 131,072 words -- the FULL
                        output as unmerged partial sums (reduction does
                        not shrink an edge below its merge point)
    reduction shape     die level: ONE hyperedge of size 2 (both dies
                        merge into every output element)
    psum width          OUR caliber is DR-7 16-bit = x2 words when
                        priced (the review note said "3 bytes" -- that
                        was the SIMBA round's 24-bit wire caliber, not
                        this platform's; recorded here so the two are
                        never mixed)

Usage (container): python3 scripts/a2_hand_gate.py
Output: analysis/a2_hand_gate.json (verdict + every checked integer)
"""
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
os.environ.setdefault("CIMSIM_FABRIC",
                      "/home/workspace/models/fabric/mlx300_multidie48.yaml")

import scripts.crossbar_comm as cc
from scripts import llm_workload as lw
from scripts import traffic

OUT_JSON = "/home/workspace/analysis/a2_hand_gate.json"

P, C, M = 128, 16384, 1024
HAND = {"dies": 2, "split": "C", "piece_C": 8192, "piece_M": 1024,
        "down_per_die": 128 * 8192,          # 1,048,576
        "up_per_die": 128 * 1024,            # 131,072
        "full_input": 128 * 16384,           # 2,097,152
        "hyperedges": 1, "hyperedge_size": 2}


def main():
    op = lw.Op("a2gate", "static", P=P, C=C, M=M)
    checks = []

    def check(name, got, want):
        ok = got == want
        ser = lambda v: sorted(v) if isinstance(v, set) else v
        checks.append({"check": name, "got": ser(got), "want": ser(want),
                       "ok": ok})
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: got {got}, want {want}",
              flush=True)
        return ok

    # planner first (closed form, no mapper yet)
    n, dim, _tiles = lw.plan_spatial(op, max_dies=48, dims=("C",))
    check("planner dies", n, HAND["dies"])
    check("planner split dim", dim, HAND["split"])

    # the MAIN path: mapper -> stats -> extraction
    print("mapper (forced C split)...", flush=True)
    r = lw.run_op(op, phase="prefill", overcapacity="spatial_multi_die",
                  spatial_dims=("C",), save_comm=False)
    res = r["result"]
    ts = traffic.extract(res.output_dir)

    die_split = next((s for s in ts.splits if s.level == "die"), None)
    check("mapping die-level split present", die_split is not None, True)
    if die_split is not None:
        check("mapping die factors", dict(die_split.factors), {"C": 2})
    ev = ts.edge_volumes()
    check("per-die DOWN words (disjoint slice)",
          ev["die"]["in"], float(HAND["down_per_die"]))
    check("per-die UP words (full-M partial sums)",
          ev["die"]["out"], float(HAND["up_per_die"]))
    check("conservation: 2 x down == full input, multicast-free",
          2 * ev["die"]["in"], float(HAND["full_input"]))
    n_edges, size = ts.hyperedge_shape("die")
    check("die reduction hyperedges", n_edges, HAND["hyperedges"])
    check("hyperedge size", size, HAND["hyperedge_size"])
    check("hyperedge membership", ts.reduction_hyperedges("die"), [[0, 1]])

    # the flow structure the contention/energy machinery consumes
    flows, _, _, _ = cc.build_flows(res.output_dir, verbose=False)
    die_flows = [f for f in flows if f["level_name"] == "die"
                 and f["volume"] > 0]
    check("active die edges in flows", len(die_flows), 2)
    if len(die_flows) == 2:
        check("flow down per die", {f["down"] for f in die_flows},
              {float(HAND["down_per_die"])})
        check("flow up per die", {f["up"] for f in die_flows},
              {float(HAND["up_per_die"])})

    verdict = "PASS" if all(c["ok"] for c in checks) else \
        "FAIL -- STOP AT THE GATE, fix extraction only"
    out = {"operator": {"P": P, "C": C, "M": M}, "hand": HAND,
           "checks": checks, "verdict": verdict,
           "psum_width_note": ("pricing caliber here is DR-7 16-bit (x2 "
                               "words); the '3-byte' figure was the Simba "
                               "round's 24-bit wire caliber")}
    with open(OUT_JSON, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\nday-1 gate verdict: {verdict}")


if __name__ == "__main__":
    main()
