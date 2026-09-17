"""S9 task B: the fixed-pair bandwidth slice at the main configuration
(kappa = 2). Pair = the strongest baseline and the headline-selected
endpoint from main_config_results.json; re-scored (never re-searched)
at 0.2, B-/2, 0.4, sqrt(B-B+), 2.0, 2B+, 12.5 GB/s with the kappa = 2
boundaries; ports scale with the links (kappa fixed). Per point: T, H,
G = 1 - T_sel/T_ref, r = H_ref/T_ref, eta = 1 - H_sel/H_ref, and the
identity G = eta r checked directly.

    python3 scripts/bw_slice_k2.py -> analysis/bw_slice_k2.json + .png
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import kappa_geometry_sweep as kg
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_space as ss

OUT = os.path.join(se.A, "bw_slice_k2.json")
PNG = os.path.join(se.A, "bw_slice_k2.png")
KAPPA = 2.0


def main():
    W = kg.workload((24, 24))
    W.port_ratio = KAPPA
    mc = json.load(open(os.path.join(se.A, "main_config_results.json")))
    st = mc["stats"]["prefill"]["0.4"]
    ref_name, sel_name = st["strongest_baseline"], st["headline_selected"]
    sweep = json.load(open(os.path.join(se.A, "kappa_geometry_sweep.json")))
    cell = sweep["cells"]["24x24/k2"]
    ref = sb.generate("random", W, seed=int(ref_name.split("_s")[1])) if ref_name.startswith("random_s") \
        else sb.generate(ref_name, W, seed=0)
    sel = ss.Pi.from_json(cell["runs"][sel_name]["best_pi"])
    pd = json.load(open(os.path.join(se.A, "phase_diagram_isobar_k2.json")))["package"]
    bm, bp = pd["B_minus_at_ref_gbps"], pd["B_plus_at_ref_gbps"]
    points = {"0.2": 0.2, "B-/2": bm / 2, "0.4": 0.4, "sqrt(B-B+)": math.sqrt(bm * bp),
              "2.0": 2.0, "2B+": 2 * bp, "12.5": 12.5}
    out = {"note": __doc__.strip(), "kappa": KAPPA, "reference": ref_name, "selected": sel_name,
           "B_minus_gbps": bm, "B_plus_gbps": bp, "points": {}}
    print(f"pair: reference {ref_name}, selected {sel_name}; B- {bm:.3f} B+ {bp:.3f} GB/s (kappa 2)")
    print(f"{'point':11} {'B':>7} {'T_ref ms':>9} {'T_sel ms':>9} {'H_ref ms':>9} {'H_sel ms':>9} {'r':>6} {'eta':>6} {'G':>7} {'eta*r':>7} {'region':>10}")
    for name, B in sorted(points.items(), key=lambda kv: kv[1]):
        r_ = {}
        for tag, pi in (("ref", ref), ("sel", sel)):
            sc = se.score(pi, W, caliber="single", d2d_gbps=B)
            d = sc.per_phase["prefill"]["decomp"]
            r_[tag] = {"T_s": sc.t_opt_s, "H_s": d["d2d_serial_s"],
                       "R_s": d["layers_s"] + d["propagation_s"]}
        G = 1 - r_["sel"]["T_s"] / r_["ref"]["T_s"]
        r = r_["ref"]["H_s"] / r_["ref"]["T_s"]
        eta = 1 - r_["sel"]["H_s"] / r_["ref"]["H_s"]
        region = "below B-" if B < bm else ("above B+" if B > bp else "in band")
        out["points"][name] = {"B_gbps": B, **{f"{k}_{t}": v[k] for t, v in r_.items() for k in v},
                               "G": G, "r": r, "eta": eta, "eta_r": eta * r,
                               "identity_gap": G - eta * r
                               - (r_["ref"]["R_s"] - r_["sel"]["R_s"]) / r_["ref"]["T_s"],
                               "region": region}
        print(f"{name:11} {B:7.3f} {r_['ref']['T_s']*1e3:9.2f} {r_['sel']['T_s']*1e3:9.2f} "
              f"{r_['ref']['H_s']*1e3:9.2f} {r_['sel']['H_s']*1e3:9.2f} {r*100:5.1f}% {eta*100:5.2f}% "
              f"{G*100:6.2f}% {eta*r*100:6.2f}% {region:>10}")
    out["max_identity_gap"] = max(abs(v["identity_gap"]) for v in out["points"].values())
    print(f"max |G - eta r - residual|: {out['max_identity_gap']:.2e}")
    json.dump(out, open(OUT, "w"), indent=1)
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    pts = sorted(out["points"].values(), key=lambda v: v["B_gbps"])
    Bs = [v["B_gbps"] for v in pts]
    ax.plot(Bs, [v["G"] * 100 for v in pts], "-o", color="#2e4a66", ms=4,
            label=f"G: {sel_name} vs {ref_name}")
    ax.plot(Bs, [v["r"] * 100 for v in pts], "--", color="#7a5c00", label="r: communication share at the reference")
    ax.plot(Bs, [v["eta"] * 100 for v in pts], ":", color="#2a7d4f", label="η: communication improvement (fixed pair)")
    ax.axvspan(bm, bp, color="#c9a227", alpha=0.18, lw=0, label="placement-dependent band [B−, B+], κ = 2")
    for B in (0.4, 12.5):
        ax.axvline(B, color="0.8", lw=0.8)
    ax.set_xscale("log")
    ax.set_xlabel("link bandwidth per direction (GB/s); ports at 2× the link rate")
    ax.set_ylabel("percent")
    ax.set_title("Main configuration (κ = 2): G = η · r on the frozen pair, re-scored", fontsize=9)
    ax.grid(alpha=0.2, which="both")
    ax.legend(fontsize=6.5)
    fig.tight_layout()
    fig.savefig(PNG, dpi=150)
    print(f"-> {OUT}\n-> {PNG}")


if __name__ == "__main__":
    main()
