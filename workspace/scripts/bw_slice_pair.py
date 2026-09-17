"""Item 6: the fixed-pair bandwidth slice.

Two FIXED seatings re-scored (never re-searched) across bandwidths:
the reference (random, seed 0 -- the strongest named baseline at both
cells) and the optimized (the weak-cell search winner); the GRS winner
rides along as a third column for cross-evaluation. Per bandwidth the
decomposition the phase diagram promises:

    G = 1 - T_opt/T_ref            whole-model latency reduction
    r = H_ref / T_ref              communication share at the reference
    eta = (H_ref - H_opt) / H_ref  communication improvement
    G = eta * r + residual         residual = the seat-dependent part of
                                   R (propagation), expected ~0

    python3 scripts/bw_slice_pair.py -> analysis/bw_slice_pair.json + .png
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_space as ss

OUT = os.path.join(se.A, "bw_slice_pair.json")
PNG = os.path.join(se.A, "bw_slice_pair.png")
BWS = (0.1, 0.2, 0.4, 1.0, 2.0, 4.0, 8.0, 12.5, 25.0)


def parts(pi, W, bw):
    sc = se.score(pi, W, caliber="single", d2d_gbps=bw)
    d = sc.per_phase["prefill"]["decomp"]
    return {"T_s": sc.t_opt_s, "H_s": d["d2d_serial_s"],
            "R_s": d["layers_s"] + d["propagation_s"],
            "prop_s": d["propagation_s"], "layers_s": d["layers_s"]}


def main():
    W = se.Workload2p7B()
    lk = json.load(open(os.path.join(se.A, "search_linkage.json")))
    seatings = {"random_ref": sb.generate("random", W, seed=0),
                "weak_winner": ss.Pi.from_json(lk["seating_mesh_weak"]["best_pi"]),
                "grs_winner": ss.Pi.from_json(lk["seating_mesh_grs"]["best_pi"])}
    out = {"note": "fixed seatings re-scored across bandwidths; single "
                   "caliber, prefill; H = d2d hand-off term (links+ports), "
                   "R = layers + propagation", "bandwidths_gbps": BWS,
           "rows": {}, "identity": {}}
    print(f"{'GB/s':>6} {'T_ref ms':>9} {'T_opt ms':>9} {'G %':>7} {'r %':>7} "
          f"{'eta %':>7} {'eta*r %':>8} {'resid %':>8}")
    for bw in BWS:
        p = {k: parts(pi, W, bw) for k, pi in seatings.items()}
        ref, opt = p["random_ref"], p["weak_winner"]
        G = 1 - opt["T_s"] / ref["T_s"]
        r = ref["H_s"] / ref["T_s"]
        eta = (ref["H_s"] - opt["H_s"]) / ref["H_s"]
        resid = (ref["R_s"] - opt["R_s"]) / ref["T_s"]
        out["rows"][str(bw)] = {**{k: v for k, v in p.items()},
                                "G": G, "r": r, "eta": eta,
                                "eta_times_r": eta * r, "residual": resid,
                                "HB_ref_words": ref["H_s"] * bw * 1e9,
                                "HB_opt_words": opt["H_s"] * bw * 1e9,
                                "grs_winner_G": 1 - p["grs_winner"]["T_s"] / ref["T_s"]}
        print(f"{bw:>6g} {ref['T_s']*1e3:>9.2f} {opt['T_s']*1e3:>9.2f} "
              f"{G*100:>7.3f} {r*100:>7.2f} {eta*100:>7.3f} {eta*r*100:>8.3f} "
              f"{resid*100:>8.5f}")
    rows = out["rows"]
    etas = [v["eta"] for v in rows.values()]
    out["identity"] = {
        "max_abs_G_minus_eta_r_minus_resid": max(
            abs(v["G"] - v["eta_times_r"] - v["residual"]) for v in rows.values()),
        "eta_min": min(etas), "eta_max": max(etas),
        "HB_ref_words_min": min(v["HB_ref_words"] for v in rows.values()),
        "HB_ref_words_max": max(v["HB_ref_words"] for v in rows.values()),
        "max_abs_residual": max(abs(v["residual"]) for v in rows.values())}
    print("identity |G - eta*r - resid| max:",
          f"{out['identity']['max_abs_G_minus_eta_r_minus_resid']:.2e};",
          f"eta range {min(etas)*100:.4f}..{max(etas)*100:.4f} %;",
          f"H*B ref {out['identity']['HB_ref_words_min']/1e6:.2f}.."
          f"{out['identity']['HB_ref_words_max']/1e6:.2f} M words;",
          f"max |residual| {out['identity']['max_abs_residual']*100:.5f} %")
    json.dump(out, open(OUT, "w"), indent=1)

    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    xs = list(BWS)
    ax.plot(xs, [rows[str(b)]["G"] * 100 for b in xs], "-o", color="#2e4a66",
            ms=4, label="whole-model gain G, weak winner vs random")
    ax.plot(xs, [rows[str(b)]["r"] * 100 for b in xs], "--", color="#7a5c00",
            label="communication share r at the reference")
    ax.plot(xs, [rows[str(b)]["eta"] * 100 for b in xs], ":", color="#2a7d4f",
            label="communication improvement η (fixed pair)")
    ax.plot(xs, [rows[str(b)]["grs_winner_G"] * 100 for b in xs], "-s",
            color="#8c8c8c", ms=3.5, lw=0.9, label="G, GRS winner vs random")
    for b in (0.4, 12.5):
        ax.axvline(b, color="0.75", lw=0.8, ls="-")
    ax.set_xscale("log")
    ax.set_xlabel("link bandwidth per direction (GB/s)")
    ax.set_ylabel("percent")
    ax.set_title("G = η · r on a fixed seating pair (re-scored, not re-searched)",
                 fontsize=9)
    ax.grid(alpha=0.2, which="both")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(PNG, dpi=150)
    print(f"-> {OUT}\n-> {PNG}")


if __name__ == "__main__":
    main()
