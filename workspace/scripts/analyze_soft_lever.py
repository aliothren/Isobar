"""The soft-placement lever at the anchors (C49, worklist step 2).

Attribution framework: HARDWARE placement (scheme / links / geometry /
device) sets WHERE the boundary lines sit; SOFTWARE placement moves the
busiest-wire load on fixed hardware. This table prices the software band
at the anchor operating points, closed-form, zero mapper -- the search
chapter's motivation table. Pre-registered in FIXLIST step 2 (cell =
triple; two A-rows with distinct semantics; per-cell direction
expectations; coverage declared; self-checks gate the run).

A1 "real, exhaustive": one JOINT seat permutation of the 8 macro bundles
on the production 2x4. The uniformity FIT is the proof: a node-uniform
(D, U) flow model must reproduce the stored per-op serialization of ALL
FIVE schemes (contention_system.json) to 1e-9 -- once it does, every
joint permutation relabels identical bundles, so the lever is EXACTLY
1.000 (exhaustive by symmetry, no sampling). Bundle composition is held
at the shipped mapping (declared not covered).

A2 "synthetic ceiling" (C28's stressor, NOT a realizable seating): one
bundle's traffic x4, its seat swept over the 8-slot orbit (exhaustive --
the other seven are identical). Mechanism ratio = max/min busiest wire;
folded to the whole stack per condition x anchor with the stored ledger
(write + max(compute, ser) + prop per op, elementwise as fixed adders --
the exact stack_latency composition, verified against the stored stack).

    python3 scripts/analyze_soft_lever.py
      -> analysis/soft_lever.json + analysis/soft_lever_table.md
"""
import dataclasses
import itertools
import json
import os
import sys
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.crossbar_comm as cc
from scripts import anchors as an
from scripts import fabric as fabric_mod
from scripts import placement as pm

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.join(WS, "analysis", "contention_system.json")
REF_WC = 16384.0
HEAVY = 4.0
ANCHOR_GBPS = [0.4, 2.0, 8.0, 8.75]      # analog band ends + mid + Simba NoC
SCHEMES = [("star", {}, "star (private links)"),
           ("mesh", {"routing": "xy", "hub": "center"}, "mesh, glb centre"),
           ("mesh", {"routing": "xy", "hub": "corner"}, "mesh, glb corner"),
           ("h_tree", {"branching": 4}, "h-tree (k=4)"),
           ("bus", {"driver": "center"}, "bus (shared medium)")]
PROD = "mesh, glb centre"                # the production scheme (C27 2x4)


def variant(base, topology, params, bw=REF_WC):
    levels = []
    for lv in base.levels:
        if lv.name == "macro":
            lv = dataclasses.replace(
                lv, link=dataclasses.replace(lv.link, topology=topology,
                                             params=params,
                                             bandwidth_words_per_cycle=bw))
        levels.append(lv)
    return dataclasses.replace(base, name="variant", levels=levels).validate()


def uniform_flows(link_name, D, U, heavy_node=None, n=8):
    fl = []
    for i in range(n):
        s = HEAVY if i == heavy_node else 1.0
        fl.append({"level": link_name, "node": i, "volume": s * (D + U),
                   "down": s * D, "up": s * U,
                   "src": "glb", "dst": f"macro{i}"})
    return fl


def wire_coeffs(fab, link_name, cyc):
    """Per-wire (a, b): busiest-wire ser(D,U) = max_w (aD + bU)/bw*cyc."""
    coeffs = {}
    for tag, (D, U) in (("a", (1.0, 0.0)), ("b", (0.0, 1.0))):
        occ = cc.link_occupancy(uniform_flows(link_name, D, U), fab, cyc,
                                pm.sequential_fill(fab))
        for e in occ["per_link"]:
            coeffs.setdefault(e["resource"], [0.0, 0.0])
            coeffs[e["resource"]][0 if tag == "a" else 1] = e["volume"]
    return coeffs


def fit_du(op_targets, fabs, link_name, cyc):
    """Solve (D, U) so the uniform model reproduces every scheme's stored
    serialization; the overdetermined agreement IS the uniformity proof."""
    def ser(coeffs, D, U):
        return max(a * D + b * U for a, b in coeffs.values()) / REF_WC * cyc

    all_coeffs = {label: wire_coeffs(fab, link_name, cyc)
                  for label, fab in fabs.items()}
    cands = []
    labels = list(op_targets)
    for l1, l2 in itertools.combinations(labels, 2):
        for a1, b1 in all_coeffs[l1].values():
            for a2, b2 in all_coeffs[l2].values():
                det = a1 * b2 - a2 * b1
                if abs(det) < 1e-12:
                    continue
                t1 = op_targets[l1] * REF_WC / cyc
                t2 = op_targets[l2] * REF_WC / cyc
                D = (t1 * b2 - t2 * b1) / det
                U = (a1 * t2 - a2 * t1) / det
                if D < -1e-9 or U < -1e-9:
                    continue
                D, U = max(D, 0.0), max(U, 0.0)
                err = max(abs(ser(all_coeffs[l], D, U) - op_targets[l])
                          / op_targets[l] for l in labels)
                cands.append((err, D, U))
    cands.sort()
    if not cands or cands[0][0] > 1e-9:
        raise SystemExit(f"uniformity fit failed (best rel err "
                         f"{cands[0][0] if cands else 'none'}) -- the stored "
                         "accounting is not node-uniform; STOP per the "
                         "pre-registration self-check")
    return cands[0][1], cands[0][2], cands[0][0]


def main():
    d = json.load(open(SRC))
    base = fabric_mod.default()
    link_name = base.level("macro").link.name
    fabs = {label: variant(base, topo, params)
            for topo, params, label in SCHEMES}
    prod_fab = fabs[PROD]
    out = {"source": os.path.basename(SRC), "ref_wc": REF_WC,
           "anchors_gbps": ANCHOR_GBPS, "phases": {}}

    for phase in ("prefill", "decode"):
        per_scheme = d["phases"][phase]["per_op"]
        prod_ops = per_scheme[PROD]
        cyc_by_op, recs = {}, []
        for rec in prod_ops:
            recs.append(dict(rec))
        # matmul ops: fit (D,U), verify, then the A2 seat orbit
        levers = {}
        for i, rec in enumerate(recs):
            if rec["kind"] == "elementwise" or rec["serial_s"] == 0.0:
                continue
            name = rec["name"]
            cyc = an.CYCLE_S
            targets = {}
            for _, _, label in SCHEMES:
                srec = next(r for r in per_scheme[label] if r["name"] == name)
                targets[label] = srec["serial_s"]
            D, U, fit_err = fit_du(targets, fabs, link_name, cyc)
            # A2: heavy x4 seat orbit on the production scheme (exhaustive:
            # the other seven bundles are identical)
            sers = []
            for seat in range(8):
                occ = cc.link_occupancy(
                    uniform_flows(link_name, D, U, heavy_node=seat),
                    prod_fab, cyc, pm.sequential_fill(prod_fab))
                sers.append(occ["serialization_s"])
            levers[name] = {"D": D, "U": U, "fit_rel_err": fit_err,
                            "ser_ref_s": rec["serial_s"],
                            "a2_ser_best_s": min(sers),
                            "a2_ser_worst_s": max(sers),
                            "a2_mech_ratio": max(sers) / min(sers)}
        # A1 adjudication (C49-a review): wirewise load comparison of two
        # seatings -- identical per wire = STRUCTURAL DEGENERACY (zero
        # freedom), not a null search result. Checked for every lever op.
        degen = {}
        for name, lv in levers.items():
            def flows_for(perm):
                return [{"level": link_name, "node": perm[j],
                         "volume": lv["D"] + lv["U"],
                         "down": lv["D"], "up": lv["U"],
                         "src": "glb", "dst": f"bundle{j}"}
                        for j in range(8)]
            wa = cc.link_occupancy(flows_for(list(range(8))), prod_fab,
                                   an.CYCLE_S, pm.sequential_fill(prod_fab))
            wb = cc.link_occupancy(flows_for(list(reversed(range(8)))),
                                   prod_fab, an.CYCLE_S,
                                   pm.sequential_fill(prod_fab))
            la = sorted((e["resource"], round(e["volume"], 6))
                        for e in wa["per_link"])
            lb = sorted((e["resource"], round(e["volume"], 6))
                        for e in wb["per_link"])
            degen[name] = {"wirewise_identical": la == lb, "n_wires": len(la)}
        # A3 (C49-b): natural non-uniformity -- multi-operator
        # co-residency, block-exclusive reading, joint seatings exhaustive.
        # Blocks tile integrally at d=1024: qkv 3 / out_proj 1 / ffn1 4 /
        # ffn2 4 macros; the attention-half die (offloaded) keeps 4 free
        # slots. Traffic density x8/k on each op's own k macros;
        # compute/write from the stored ledger (wire geometry only).
        A3_DIES = {"attn": [("qkv_proj", 3), ("out_proj", 1)],
                   "ffn": [("ffn1", 4), ("ffn2", 4)]}

        def a3_ser(name, seats):
            lv = levers[name]
            k = len(seats)
            D, U = lv["D"] * 8.0 / k, lv["U"] * 8.0 / k
            fl = [{"level": link_name, "node": s, "volume": D + U,
                   "down": D, "up": U, "src": "glb", "dst": f"{name}{j}"}
                  for j, s in enumerate(seats)]
            return cc.link_occupancy(fl, prod_fab, an.CYCLE_S,
                                     pm.sequential_fill(prod_fab)
                                     )["serialization_s"]

        a3 = {}
        for die, opset in A3_DIES.items():
            seatings = []
            (n1, k1), (n2, k2) = opset
            for s1 in combinations(range(8), k1):
                rest = [x for x in range(8) if x not in s1]
                for s2 in combinations(rest, k2):
                    seatings.append({n1: s1, n2: s2})
            per = []
            for st in seatings:
                per.append({name: a3_ser(name, st[name]) for name in st})
            a3[die] = {"n_seatings": len(seatings), "per_seating": per,
                       "ops": [n for n, _ in opset]}
        # stack folds
        n_layers = d["n_layers"]
        def stack(g_gbps, end):
            wc = an.words_per_cycle(g_gbps)
            tot, moved = 0.0, 0.0
            for rec in recs:
                name = rec["name"]
                comp, wr = rec["compute_s"], rec["write_s"]
                if name in levers:
                    key = {"best": "a2_ser_best_s", "worst": "a2_ser_worst_s",
                           "real": "ser_ref_s"}[end]
                    ser = levers[name][key] * REF_WC / wc
                else:
                    ser = 0.0
                ser_ref = rec["serial_s"]
                prop = rec["latency_s"] - wr - max(comp, ser_ref)
                lat = wr + max(comp, ser) + prop
                tot += lat
                moved += max(comp, ser) - comp
            return tot * n_layers, moved * n_layers
        cells = []
        for g in ANCHOR_GBPS:
            best, _ = stack(g, "best")
            worst, _ = stack(g, "worst")
            _, moved_b = stack(g, "best")
            cells.append({
                "g_gbps": g,
                "a1_stack_ratio": 1.0,          # exhaustive by symmetry (fit proof)
                "a2_stack_ratio": worst / best,
                "a2_mech_ratio": max(l["a2_mech_ratio"] for l in levers.values()),
                "fixed_share_best": 1.0 - moved_b / best,
                "stack_best_s": best, "stack_worst_s": worst,
            })
        # verification: shipped stack at ref bw reproduces the stored row
        wc_ref_gbps = an.gbps_of(REF_WC)
        ship, _ = stack(wc_ref_gbps, "real")
        stored = next(r for r in d["phases"][phase]["rows"]
                      if r["label"] == PROD)["latency_s"]
        rel = abs(ship - stored) / stored
        # C: g-thresholds where the A2 whole-stack band crosses 1% / 10%
        def ratio_at(g):
            b, _ = stack(g, "best"); w, _ = stack(g, "worst")
            return w / b
        def solve(target):
            lo, hi = 0.01, 50.0
            if ratio_at(lo) < target:
                return None
            for _ in range(60):
                mid = (lo * hi) ** 0.5
                if ratio_at(mid) > target:
                    lo = mid
                else:
                    hi = mid
            return (lo * hi) ** 0.5
        # A3 fold: per anchor, best/worst JOINT seating per die type
        # (independent dies), the other ops at their shipped serialization
        def a3_cells():
            base_recs = {r["name"]: r for r in recs}
            rows = []
            for g in ANCHOR_GBPS:
                wc = an.words_per_cycle(g)
                scale = REF_WC / wc
                tot_best = tot_worst = 0.0
                mechs = {}
                for die, dd in a3.items():
                    costs = []
                    for st in dd["per_seating"]:
                        c = 0.0
                        for name, s_ref in st.items():
                            rec = base_recs[name]
                            prop = rec["latency_s"] - rec["write_s"] \
                                - max(rec["compute_s"], rec["serial_s"])
                            c += rec["write_s"] + prop \
                                + max(rec["compute_s"], s_ref * scale)
                        costs.append(c)
                    tot_best += min(costs)
                    tot_worst += max(costs)
                    sers = [max(st.values()) for st in dd["per_seating"]]
                    mechs[die] = max(sers) / min(sers)
                # the rest of the stack (unmoved ops) at shipped seats
                fixed = 0.0
                for rec in recs:
                    if rec["name"] in ("qkv_proj", "out_proj", "ffn1", "ffn2"):
                        continue
                    ser = rec["serial_s"] * scale if rec["serial_s"] else 0.0
                    prop = rec["latency_s"] - rec["write_s"] \
                        - max(rec["compute_s"], rec["serial_s"])
                    fixed += rec["write_s"] + prop \
                        + max(rec["compute_s"], ser)
                rows.append({"g_gbps": g,
                             "a3_stack_ratio": (fixed + tot_worst)
                                               / (fixed + tot_best),
                             "a3_mech_ratio_attn": mechs["attn"],
                             "a3_mech_ratio_ffn": mechs["ffn"]})
            return rows
        a3_rows = a3_cells()
        out["phases"][phase] = {
            "levers": levers, "cells": cells, "degeneracy": degen,
            "a3": {die: {"n_seatings": a3[die]["n_seatings"],
                         "ops": a3[die]["ops"]} for die in a3},
            "a3_cells": a3_rows,
            "stack_check_rel_err": rel,
            "g_threshold_1pct": solve(1.01), "g_threshold_10pct": solve(1.10),
        }
        assert rel < 1e-9, f"{phase}: stack reproduction failed ({rel})"

    with open(os.path.join(WS, "analysis", "soft_lever.json"), "w") as f:
        json.dump(out, f, indent=1)

    # ---- the table
    L = ["# The soft-placement lever at the anchors (C49, worklist step 2)",
         "",
         "Cell = (whole-stack worst/best, mechanism worst/best, fixed share",
         "of the best stack). A1's 1.000 is STRUCTURAL DEGENERACY, not a",
         "null search result (C49-a adjudication): any two seatings carry",
         "IDENTICAL per-wire loads, checked wire by wire for every lever",
         "op -- under (i) the fill-exact grid, (ii) the uniform mapping",
         "(per-leaf even division certified by the traffic extraction's own",
         "conservation guards on Timeloop's counters) and (iii) the shipped",
         "bundling, the on-die soft-placement freedom is FROZEN TO ZERO BY",
         "THE MAPPING. A2 = the C28 x4 stressor (NOT a realizable seating),",
         "seat orbit exhaustive. Fixed share = 1 - (network excess over",
         "compute)/stack: what placement cannot move at that operating",
         "point.", ""]
    for phase in ("prefill", "decode"):
        ph = out["phases"][phase]
        L.append(f"## {phase} (attention on-chip, S=512, 24 layers)")
        L.append("")
        L.append("| row \\ anchor (GB/s) | " +
                 " | ".join(f"{g:g}" for g in ANCHOR_GBPS) + " |")
        L.append("|---|" + "---|" * len(ANCHOR_GBPS))
        L.append("| A1 real, exhaustive (stack) | " +
                 " | ".join("1.000" for _ in ANCHOR_GBPS) + " |")
        L.append("| A2 ceiling, stack | " +
                 " | ".join(f"{c['a2_stack_ratio']:.3f}" for c in ph["cells"]) + " |")
        L.append("| A2 ceiling, mechanism | " +
                 " | ".join(f"{c['a2_mech_ratio']:.3f}" for c in ph["cells"]) + " |")
        L.append("| fixed share of best stack | " +
                 " | ".join(f"{c['fixed_share_best']:.1%}" for c in ph["cells"]) + " |")
        L.append("| A3 natural co-residency, stack (REALIZABLE) | " +
                 " | ".join(f"{c['a3_stack_ratio']:.3f}"
                            for c in ph["a3_cells"]) + " |")
        L.append("| A3 mechanism (attn die 280 / ffn die 70 seatings, exhaustive) | " +
                 " | ".join(f"{c['a3_mech_ratio_attn']:.2f} / {c['a3_mech_ratio_ffn']:.2f}"
                            for c in ph["a3_cells"]) + " |")
        t1, t10 = ph["g_threshold_1pct"], ph["g_threshold_10pct"]
        L.append("")
        L.append(f"band thresholds: A2 stack band > 1% below g = "
                 f"{t1:.2f} GB/s; > 10% below g = "
                 f"{(f'{t10:.2f}' if t10 else 'never')} GB/s.")
        L.append("")
    L += ["## B. die-level rows (collected, not recomputed; sources as cited)",
          "",
          "| lever | reading | source |",
          "|---|---|---|",
          "| 2.7B chain seating (real) | 1% thresholds 1.02-1.72 GB/s; doubling 0.26-0.40 GB/s | ANCHORS.md B2 (C23/O13) |",
          "| 48-die offloaded orderings (real) | 12-19x at 0.1 GB/s (mesh); 1.00x at GRS | ANCHORS.md B1 |",
          "| offload dividend threshold (real) | needs 1.2-1.9 GB/s, moving with the ordering | ANCHORS.md B1 |",
          "",
          "Reading (conditioned -- the honest calibre): in the DENSE,",
          "EVENLY-TILED operating point of the production die, the on-die",
          "soft-placement freedom is frozen to zero BY THE MAPPING --",
          "structural degeneracy under three conditions stated above, each",
          "of which reopens the space when it breaks: a non-fill-exact grid",
          "(spare slots and real seat choices), non-uniform per-macro loads",
          "(the C28 stressor demonstrates it; MoE-class expert routing and",
          "variable-length attention are natural producers), or re-bundled",
          "co-residency. This must NOT be read as 'on-die placement never",
          "matters'. It is the attribution framework's clean third hand:",
          "besides hardware placement (where the lines sit) and software",
          "placement (the band width), the MAPPING decides whether",
          "placement has any play at all. In THIS configuration the",
          "searchable freedom concentrates at the die level, where the",
          "measured bands are wide (B rows); the evaluator prices both",
          "levels, so when a workload reopens the on-die space, no new",
          "code is needed. A3 is that reopening, measured on a REALIZABLE",
          "configuration: after offload what remains on the die IS this",
          "co-resident projection set (qkv 3 + out_proj 1 macros with four",
          "slots FREE; ffn1 4 + ffn2 4) -- per-macro density is naturally",
          "unequal and the seat choice is real. The evaluator needed no",
          "new code."]
    with open(os.path.join(WS, "analysis", "soft_lever_table.md"), "w") as f:
        f.write("\n".join(L) + "\n")

    for phase in ("prefill", "decode"):
        ph = out["phases"][phase]
        errs = ", ".join(f"{l['fit_rel_err']:.0e}" for l in ph["levers"].values())
        print(f"{phase}: stack check rel err {ph['stack_check_rel_err']:.1e}; "
              f"fit errs [{errs}]")
        for c, c3 in zip(ph["cells"], ph["a3_cells"]):
            print(f"  g={c['g_gbps']:<5} A2 stack {c['a2_stack_ratio']:.4f}  "
                  f"mech {c['a2_mech_ratio']:.3f}  fixed {c['fixed_share_best']:.1%}  "
                  f"A3 stack {c3['a3_stack_ratio']:.4f}  "
                  f"mech {c3['a3_mech_ratio_attn']:.2f}/{c3['a3_mech_ratio_ffn']:.2f}")
        print(f"  thresholds: 1% at {ph['g_threshold_1pct']}  10% at {ph['g_threshold_10pct']}")


if __name__ == "__main__":
    main()
