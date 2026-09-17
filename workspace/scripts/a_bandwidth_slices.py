"""S7 / instance A: the whole-model bandwidth slices, RE-SCORING ONLY.

Candidates: the seven named rules (seed 0), random seeds 1-4, the nine
item-4 endpoints (seating_seeds.json). P for the boundaries = the seven
rules; B- = A_min/R, B+ = A_max/R. Points: 2B+, sqrt(B-B+), B-/2, 0.4,
12.5. Per point and per named reference: r_ref, eta_achieved,
eta_ceiling, G, and the identity G = r_ref * eta_achieved checked.

    python3 scripts/a_bandwidth_slices.py -> analysis/a_bandwidth_slices.json + .png
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import llm_workload as lw
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_space as ss

OUT = os.path.join(se.A, "a_bandwidth_slices.json")
PNG = os.path.join(se.A, "a_bandwidth_slices.png")
RULES = ("sequential", "clustered", "snake", "random", "least_manhattan",
         "nmap_greedy", "heaviest_first")


def port_floor_words(W, pi, phase="prefill"):
    """sum_b V_b: the largest per-die port load of each boundary."""
    base = lw.block_chain(W.cfg, W.S, phase, on_chip=True,
                          max_dies=W.fab.level("die").per_parent)
    chain, seating = [], {}
    for li in range(W.cfg.n_layers):
        for e in base:
            n = f"{e['name']}@L{li}"
            chain.append({**e, "name": n})
            seating[n] = list(pi.seat[n])
    fb = lw.block_die_flows(chain, seating, W.fab)
    tot = 0.0
    for e in chain[1:]:
        inj, ej = {}, {}
        for f in fb[e["name"]]:
            w = f["volume"] * f["width"]
            inj[f["nodes"][0]] = inj.get(f["nodes"][0], 0.0) + w
            ej[f["nodes"][1]] = ej.get(f["nodes"][1], 0.0) + w
        tot += max(max(inj.values()), max(ej.values()))
    return tot


def main():
    W = se.Workload2p7B()
    cands = {n: sb.generate(n, W, seed=0) for n in RULES}
    for s in (1, 2, 3, 4):
        cands[f"random_s{s}"] = sb.generate("random", W, seed=s)
    seeds = json.load(open(os.path.join(se.A, "seating_seeds.json")))
    for cell in ("grs", "weak"):
        for k, v in seeds["cells"][cell]["runs"].items():
            cands[f"endpoint_{cell}_{k.replace('/', '_')}"] = ss.Pi.from_json(v["best_pi"])
    # A(p), R, floor from one scoring at a reference bandwidth (A is B-free)
    A, R = {}, {}
    for n, pi in cands.items():
        sc = se.score(pi, W, caliber="single", d2d_gbps=1.0)
        d = sc.per_phase["prefill"]["decomp"]
        A[n] = d["d2d_busiest_words"]
        R[n] = d["layers_s"] + d["propagation_s"]
    floor = port_floor_words(W, cands["random"])
    R0 = R["random"]
    a_min = min(A[n] for n in RULES)
    a_max = max(A[n] for n in RULES)
    b_minus, b_plus = a_min / R0 / 1e9, a_max / R0 / 1e9
    points = {"high_2Bplus": 2 * b_plus, "mid_sqrt": math.sqrt(b_minus * b_plus),
              "low_Bminus_half": b_minus / 2, "legacy_0.4": 0.4,
              "legacy_12.5": 12.5}
    rnd = [n for n in cands if n == "random" or n.startswith("random_s")]
    refs = {"random_seed0": "random",
            "strongest_random": min(rnd, key=lambda n: A[n]),
            "best_named_rule": min(RULES, key=lambda n: A[n])}
    ends = [n for n in cands if n.startswith("endpoint_")]
    best_end = min(ends, key=lambda n: A[n])
    out = {"note": __doc__.strip(), "P": list(RULES), "R_s": R0,
           "floor_words": floor, "A_words": A, "R_by_candidate_s": R,
           "boundaries_gbps": {"B_minus": b_minus, "B_plus": b_plus,
                               "A_min_rule": min(RULES, key=lambda n: A[n]),
                               "A_max_rule": max(RULES, key=lambda n: A[n])},
           "points_gbps": points, "refs": refs, "best_endpoint": best_end,
           "A_over_floor": {n: A[n] / floor for n in cands}, "slices": {}}
    print(f"P = 7 rules: A_min {a_min/1e6:.1f}M ({out['boundaries_gbps']['A_min_rule']}), "
          f"A_max {a_max/1e6:.1f}M; R {R0*1e3:.2f} ms; floor {floor/1e6:.1f}M; "
          f"B- {b_minus:.3f} B+ {b_plus:.3f} GB/s")
    print(f"refs: {refs}; best endpoint {best_end} A/floor {A[best_end]/floor:.4f}")
    print(f"{'point':16} {'B GB/s':>7} | {'ref':17} {'r_ref':>6} {'eta_ach':>7} "
          f"{'eta_ceil':>8} {'G':>7} {'G direct':>9}")
    for pname, B in points.items():
        out["slices"][pname] = {"B_gbps": B, "per_ref": {}, "T_s": {}}
        for n in cands:
            out["slices"][pname]["T_s"][n] = se.score(
                cands[n], W, caliber="single", d2d_gbps=B).t_opt_s
        T = out["slices"][pname]["T_s"]
        for rname, rc in refs.items():
            r_ref = (A[rc] / (B * 1e9)) / (R[rc] + A[rc] / (B * 1e9))
            eta = 1 - A[best_end] / A[rc]
            ceil = 1 - floor / A[rc]
            G_id = r_ref * eta
            G_dir = 1 - T[best_end] / T[rc]
            out["slices"][pname]["per_ref"][rname] = {
                "r_ref": r_ref, "eta_achieved": eta, "eta_ceiling": ceil,
                "G_identity": G_id, "G_direct": G_dir,
                "identity_gap": G_dir - G_id}
            print(f"{pname:16} {B:7.3f} | {rname:17} {r_ref*100:5.1f}% "
                  f"{eta*100:6.3f}% {ceil*100:7.2f}% {G_id*100:6.3f}% "
                  f"{G_dir*100:8.3f}%")
    json.dump(out, open(OUT, "w"), indent=1)

    fig, ax = plt.subplots(figsize=(6.6, 3.8))
    order = sorted(points, key=lambda k: points[k])
    Bs = [points[k] for k in order]
    col = {"random_seed0": "#2e4a66", "strongest_random": "#2a7d4f",
           "best_named_rule": "#7a5c00"}
    drawn = {}
    for rname, rc in refs.items():
        if rc in drawn:                       # the same seating: one curve, both names
            drawn[rc].append(rname)
            continue
        drawn[rc] = [rname]
    for rc, names in drawn.items():
        rname = names[0]
        label = " = ".join(names) + f" ({rc})"
        G = [out["slices"][p]["per_ref"][rname]["G_direct"] * 100 for p in order]
        C = [out["slices"][p]["per_ref"][rname]["eta_ceiling"]
             * out["slices"][p]["per_ref"][rname]["r_ref"] * 100 for p in order]
        ax.plot(Bs, C, ls="none", marker="o", ms=9, mfc="none", mec=col[rname],
                mew=1.2, label=f"port-floor ceiling vs {label}")
        ax.plot(Bs, G, "-o", ms=4, color=col[rname], label=f"G achieved vs {label}")
    for pname, B in points.items():
        ax.axvline(B, color="0.85", lw=0.8)
    ax.axvspan(b_minus, b_plus, color="#c9a227", alpha=0.18, lw=0,
               label="placement-dependent band [B-, B+]")
    ax.set_xscale("log")
    ax.set_xlabel("link bandwidth per direction (GB/s)")
    ax.set_ylabel("whole-model latency reduction (%)")
    ax.set_title("Instance A across bandwidth: achieved gain = the port-floor "
                 "ceiling at every point", fontsize=9)
    ax.grid(alpha=0.2, which="both")
    ax.legend(fontsize=6.5)
    fig.tight_layout()
    fig.savefig(PNG, dpi=150)
    print(f"-> {OUT}\n-> {PNG}")


if __name__ == "__main__":
    main()
