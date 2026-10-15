"""Follow-up P0 (section 4): the Gemma-7B final layout pair of the
confirmation record (prefill 512, central unit) exported with every term
the comparison needs: per-candidate totals, per-seed statistics, the
per-stage account of the strongest baseline and the representative
layout with the stage deltas, the resource loads, the mesh-bandwidth
equivalence by root finding with the port ratio held, the rule-wise
boundaries, and the energy breakdown.

    python3 scripts/v6_gemma_pair.py [--config <config_id>] [--unit e9_confirm]
      -> analysis/v6/gemma_*.csv, gemma_pair_layouts.json
"""
import argparse
import csv
import json
import math
import os
import statistics
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import search_space as ss                   # noqa: E402
from scripts import v6_common as C                       # noqa: E402

OUT = C.V6


def H_at(W, bs, bw):
    """H_full at mesh bandwidth bw (GB/s) from stored components: links and die ports scale with bw (the port ratio held), the hub port stays at C_hub."""
    off = W.offload
    Ch = off.unit["link_bandwidth_gbps"] * 1e9 if off is not None else None
    tot = 0.0
    for b in bs:
        t = max(b["link_words"], b["dport_words"]) / (bw * 1e9)
        if Ch and b.get("hub_words", 0) > 0:
            t = max(t, b["hub_words"] / Ch)
        tot += t + b["max_hops"] * C.se.NS_PER_HOP_D2D * 1e-9
    return tot


def solve_B(W, bs, target, lo=1e-3, hi=1e6):
    """inf{b >= lo : H(b) <= target}; None when H(inf) > target."""
    if H_at(W, bs, hi) > target:
        return None
    for _ in range(100):
        mid = math.sqrt(lo * hi)
        if H_at(W, bs, mid) > target:
            lo = mid
        else:
            hi = mid
    return hi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", default="e9_confirm")
    ap.add_argument("--config", default="gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1")
    ap.add_argument("--prefix", default="gemma")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    rec = C.find_record(args.unit, args.config)
    spec = rec["spec"]; phase, bw, kappa = spec["phase"], float(spec["bw"]), float(spec["kappa"])
    W = C.workload_from_record(rec)
    R = (rec["N_s"] + rec["F_s"])
    names = list(rec["candidates"])
    layouts = {}
    for n in names:
        layouts[n] = C.candidate_layout(W, n)
    for n, run in rec["search"]["runs"].items():
        layouts[n] = ss.Pi.from_json(run["best_pi"])
    rep = rec["search"]["headline"]; strongest = rec["strongest"]
    # ---- candidates: totals
    cand_rows, evals = [], {}
    for n, pi in layouts.items():
        sc, bs = C.evaluate(W, pi, phase, bw)
        d = sc.per_phase[phase]["decomp"]
        lb = W.layer_breakdown_s(phase); L = W.cfg.n_layers
        H_service = d["d2d_serial_s"]; P = d["propagation_s"]
        evals[n] = (sc, bs)
        kind = "search endpoint" if n.startswith("sa_") else ("rule" if not n.startswith("random_s") else "random fill")
        if n == "sequential":
            kind = "default fill"
        cand_rows.append({"layout": n, "kind": kind, "T_backbone_s": sc.t_opt_s, "R_s": R, "R_CIM_s": (lb["cim_compute_s"] + lb["cim_write_s"]) * L, "R_digital_s": lb["digital_elementwise_s"] * L + lb["unit_compute_s"] * L,
                          "R_KV_s": lb["unit_kv_s"] * L, "R_other_s": 0.0, "H_full_s": H_service + P, "H_service_s": H_service, "P_s": P,
                          "A_words_at_bw": d["d2d_busiest_words"], "payload_words": d["d2d_words"], "hub_words": d.get("hub_words_sum", 0.0), "E_total_J": sc.e_J,
                          "is_strongest": n == strongest, "is_representative": n == rep,
                          "recorded_T_s": rec["candidates"][n]["T_s"] if n in rec["candidates"] else rec["search"]["runs"][n]["T_s"]})
    for r in cand_rows:
        r["reproduces_record"] = abs(r["T_backbone_s"] - r["recorded_T_s"]) <= 1e-9 * max(1.0, r["recorded_T_s"])
    with open(os.path.join(OUT, f"{args.prefix}_candidates.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cand_rows[0].keys())); w.writeheader(); w.writerows(cand_rows)
    Tb = evals[strongest][0].t_opt_s; Hb = cand_rows[[r["layout"] for r in cand_rows].index(strongest)]["H_full_s"]
    # ---- seeds
    seed_rows = []
    runs = rec["search"]["runs"]
    for s in rec["search"]["seeds"]:
        rs = {n: r for n, r in runs.items() if r["sa_seed"] == s}
        best = min(rs, key=lambda n: rs[n]["T_s"])
        for n, r in rs.items():
            Hs = cand_rows[[x["layout"] for x in cand_rows].index(n)]["H_full_s"]
            seed_rows.append({"seed": s, "start": r["start"], "start_layout": r["start_layout"], "run": n, "T_s": r["T_s"], "H_full_s": Hs, "eta_comm": 1 - Hs / Hb, "G_backbone": 1 - r["T_s"] / Tb,
                              "best_of_seed": n == best, "is_representative": n == rep, "steps": r["steps"], "accepted": r["accepted"], "proposed": r["proposed"]})
    bests = [min((r["T_s"] for r in runs.values() if r["sa_seed"] == s)) for s in rec["search"]["seeds"]]
    gains = sorted([1 - t / Tb for t in bests])
    with open(os.path.join(OUT, f"{args.prefix}_seed_statistics.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(seed_rows[0].keys())); w.writeheader(); w.writerows(seed_rows)
        w2 = csv.writer(f); w2.writerow([]); w2.writerow(["summary", "G_median", statistics.median(gains), "G_min", min(gains), "G_max", max(gains), "representative", rep,
                                                           "rule", "per seed the best of three starts; the representative is the median seed's best run; even seed count: the lower middle"])
    # ---- stage breakdown and deltas (strongest vs representative), resource loads
    stage_rows, delta_rows = [], []
    for n in [strongest, rep]:
        for row in C.stage_rows(W, evals[n][1], bw, kappa):
            stage_rows.append({"layout": n, **row})
    sb_ = {r["into"]: r for r in stage_rows if r["layout"] == strongest}; sr_ = {r["into"]: r for r in stage_rows if r["layout"] == rep}
    by_stage = {}
    for k in sb_:
        d = (sr_[k]["service_s"] + sr_[k]["propagation_s"]) - (sb_[k]["service_s"] + sb_[k]["propagation_s"])
        delta_rows.append({"into": k, "layer": sb_[k]["layer"], "stage": sb_[k]["stage"], "H_baseline_s": sb_[k]["service_s"] + sb_[k]["propagation_s"], "H_representative_s": sr_[k]["service_s"] + sr_[k]["propagation_s"],
                           "delta_s": d, "binding_baseline": sb_[k]["binding"], "binding_representative": sr_[k]["binding"]})
        by_stage.setdefault(sb_[k]["stage"], [0.0, 0.0, 0.0]); by_stage[sb_[k]["stage"]][0] += sb_[k]["service_s"] + sb_[k]["propagation_s"]; by_stage[sb_[k]["stage"]][1] += sr_[k]["service_s"] + sr_[k]["propagation_s"]; by_stage[sb_[k]["stage"]][2] += d
    with open(os.path.join(OUT, f"{args.prefix}_stage_breakdown.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(stage_rows[0].keys())); w.writeheader(); w.writerows(stage_rows)
    with open(os.path.join(OUT, f"{args.prefix}_stage_delta.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(delta_rows[0].keys())); w.writeheader(); w.writerows(delta_rows)
        w2 = csv.writer(f); w2.writerow([]); w2.writerow(["stage", "H_baseline_s", "H_representative_s", "delta_s", "share_of_total_delta"])
        tot = sum(v[2] for v in by_stage.values())
        for k, v in by_stage.items():
            w2.writerow([k, v[0], v[1], v[2], v[2] / tot if tot else ""])
        w2.writerow(["sum", sum(v[0] for v in by_stage.values()), sum(v[1] for v in by_stage.values()), tot, "check: equals H_b - H_s"])
    # resource loads of the two layouts (flows re-derived)
    load_rows = []
    for n in [strongest, rep]:
        pi = layouts[n]
        from scripts import cimsim_cli as cli
        for into, fl in cli.handoff_flows(W, pi, phase):
            loads = C.se.resource_loads(fl, W.die_ic, ports=True, kappa=1.0)
            hubs = W.hub_nodes()
            link = max((v for k, v in loads.items() if k[0] != "port"), default=0.0)
            top_links = sorted(((v, k) for k, v in loads.items() if k[0] != "port"), reverse=True)[:3]
            load_rows.append({"layout": n, "into": into, "n_flows": len(fl), "payload_words": sum(f["volume"] * f["width"] for f in fl),
                              "busiest_link_words": link, "busiest_links": "; ".join(f"{k[0]}{k[1]}:{v:.0f}" for v, k in top_links),
                              "busiest_die_port_words": max((v for k, v in loads.items() if k[0] == "port" and k[1] not in hubs), default=0.0),
                              "hub_port_words": max((v for k, v in loads.items() if k[0] == "port" and k[1] in hubs), default=0.0),
                              "word_hops": sum(f["volume"] * f["width"] * W.die_ic.hops(*f["nodes"]) for f in fl), "max_hops": max((W.die_ic.hops(*f["nodes"]) for f in fl), default=0),
                              "sources": sorted({f["nodes"][0] for f in fl}), "destinations": sorted({f["nodes"][1] for f in fl})})
    with open(os.path.join(OUT, f"{args.prefix}_resource_loads.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(load_rows[0].keys())); w.writeheader(); w.writerows(load_rows)
    # ---- bandwidth equivalence and rule-wise boundaries
    Hs_rep = cand_rows[[x["layout"] for x in cand_rows].index(rep)]["H_full_s"]
    B_eq = solve_B(W, evals[strongest][1], Hs_rep, lo=bw)
    beq_rows = [{"baseline_layout": strongest, "search_layout": rep, "B_ref_gbps": bw, "H_search_at_B_ref_s": Hs_rep, "H_baseline_at_B_ref_s": Hb,
                 "B_eq_gbps": B_eq, "g_bw": (B_eq / bw - 1) if B_eq else "", "reachable": B_eq is not None, "H_baseline_at_B_eq_s": H_at(W, evals[strongest][1], B_eq) if B_eq else "",
                 "H_baseline_limit_s": H_at(W, evals[strongest][1], 1e9), "tolerance": "100 bisection steps on log B, |H - target| / target < 1e-12",
                 "held_fixed": "hub capacity, K/V and digital resources, the attention algorithm, the two layouts; die ports scale with the mesh bandwidth at the port ratio",
                 "dominant_resource_near_root": __import__("collections").Counter(r["binding"] for r in C.stage_rows(W, evals[strongest][1], B_eq or bw, kappa)).most_common(1)[0][0] if B_eq else ""}]
    for n in [x for x in names if not x.startswith("random_s")]:
        Bc = solve_B(W, evals[n][1], R, lo=1e-4)
        beq_rows.append({"baseline_layout": n, "search_layout": "", "B_ref_gbps": bw, "H_search_at_B_ref_s": "", "H_baseline_at_B_ref_s": cand_rows[[x["layout"] for x in cand_rows].index(n)]["H_full_s"],
                         "B_eq_gbps": Bc, "g_bw": "", "reachable": Bc is not None, "H_baseline_at_B_eq_s": R, "H_baseline_limit_s": H_at(W, evals[n][1], 1e9), "tolerance": "rule boundary B_c: H(B_c) = R",
                         "held_fixed": "same", "dominant_resource_near_root": ""})
    fin = [r["B_eq_gbps"] for r in beq_rows[1:] if r["B_eq_gbps"]]
    with open(os.path.join(OUT, f"{args.prefix}_bandwidth_equivalence.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(beq_rows[0].keys())); w.writeheader(); w.writerows(beq_rows)
        w2 = csv.writer(f); w2.writerow([]); w2.writerow(["rules band", "B_minus", min(fin) if fin else "", "B_plus", max(fin) if fin else "", "ratio", (max(fin) / min(fin)) if fin else "", "no finite boundary", sum(1 for r in beq_rows[1:] if not r["B_eq_gbps"])])
    # ---- energy
    en_rows = []
    for n in [ "sequential", strongest, rep] + [x for x in names if not x.startswith("random_s") and x != "sequential"]:
        if n not in evals:
            continue
        e = C.energy_breakdown(W, evals[n][0], phase)
        en_rows.append({"layout": n, **e, "E_comm_share": (e["E_interconnect_flat_J"] + e["E_interconnect_surplus_J"]) / e["E_total_J"],
                        "coefficients": "CIM: CiMLoop per-operator energy; digital: Horowitz table at 16 bit; unit: 1 pJ per counted op (digital compute subsystem, equivalent); K/V: 50 pJ per 8-bit word; interconnect: 10 pJ per word flat + 10 pJ per word per surplus hop"})
    with open(os.path.join(OUT, f"{args.prefix}_energy_breakdown.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(en_rows[0].keys())); w.writeheader(); w.writerows(en_rows)
    json.dump({"record": args.config, "unit": args.unit, "strongest": strongest, "representative": rep, "layouts": {strongest: layouts[strongest].to_json(), rep: layouts[rep].to_json()},
               "protocol": {"n_random": rec["n_random"], "seeds": rec["search"]["seeds"], "objective": rec["search"].get("objective"), "t0_norm": rec["search"]["t0_norm"], "alpha": rec["search"]["alpha"], "steps": rec["search"]["steps"]},
               "unit": rec["attention"].get("unit"), "hubs": rec["attention"].get("hubs")}, open(os.path.join(OUT, f"{args.prefix}_pair_layouts.json"), "w"), indent=1)
    rep_row = cand_rows[[x["layout"] for x in cand_rows].index(rep)]
    print(f"{args.config}: strongest {strongest} T {Tb*1e3:.2f} ms H_full {Hb*1e3:.2f} | representative {rep} T {rep_row['T_backbone_s']*1e3:.2f} H_full {rep_row['H_full_s']*1e3:.2f} | eta {1-rep_row['H_full_s']/Hb:.4f} r0 {Hb/Tb:.4f} G {1-rep_row['T_backbone_s']/Tb:.4f} | B_eq {B_eq} | reproduce {all(r['reproduces_record'] for r in cand_rows)}")
    print("stage deltas (ms):", {k: round(v[2] * 1e3, 2) for k, v in by_stage.items()}, "sum", round(tot * 1e3, 2), "H_b - H_s", round((Hb - rep_row["H_full_s"]) * 1e3, 2))


if __name__ == "__main__":
    main()
