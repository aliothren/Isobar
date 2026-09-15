"""S6 day 12 (C64-f): the five-arm experiment -- argmin per arm, E0
re-scoring, regret, the COMPLETE 5x5 cross-scoring matrix, the chain
BENIGN-LOAD control leg, and the mu = {0.3, 0.7} weight-sensitivity
line.

Everything here follows the day-11 pre-registration verbatim: same
Omega / algorithm / seeds; budget rule Schedule(t0 = (max seed J -
min seed J)/20 in the arm's own units, alpha 0.996, steps 2000),
7 named starts, base seed 0. Verdict standards (fixed before the
runs): a defective arm is "definitely wrong" only when its E0-regret
exceeds S3's measured multi-start noise band of 1.8%; within the
band only "possibly wrong".

    python3 scripts/search_s6.py   -> analysis/search_s6.json + png
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import check_c_crosstraffic as cx
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_referee as sr
from scripts import search_sa as sa
from scripts import search_space as ss

NOISE_BAND = 0.018
OUT_JSON = os.path.join(se.A, "search_s6.json")
OUT_PNG = os.path.join(se.A, "search_s6.png")


def run_arm(J, seeds, label):
    rungs = {n: J(pi) for n, pi in seeds.items()}
    t0 = (max(rungs.values()) - min(rungs.values())) / 20.0
    sched = sa.Schedule(t0=t0, alpha=0.996, steps=2000)
    best_name, results = sa.multistart(J, seeds, 576, sched, seed=0)
    r = results[best_name]
    print(f"  [{label}] self-best {r.best_j:.6g} (start {best_name}, "
          f"t0 {t0:.3g})")
    return {"label": label, "t0": t0, "self_best": r.best_j,
            "best_start": best_name, "pi": r.best_pi,
            "rungs": rungs,
            "per_start_best": {n: x.best_j for n, x in results.items()}}


def main():
    W = cx.host()
    seeds = {n: sb.generate(n, W, seed=0) for n in sb.NAMES}
    out = {"noise_band": NOISE_BAND, "mu_active": dict(sr.MU),
           "quantifier": "observed",
           "evaluation_set": "7 named seeds x 5 arms, fixed budget"}

    print("ACTIVE CELL (the declared mix)")
    arms = {name: run_arm(sr.make_arm(name), seeds, name)
            for name in sr.ARMS}

    # the complete 5x5 cross-scoring matrix (fresh judges per row scan)
    judges = {name: sr.make_arm(name) for name in sr.ARMS}
    matrix = {ai: {ei: judges[ei](arms[ai]["pi"]) for ei in sr.ARMS}
              for ai in sr.ARMS}
    e0_opt = matrix["E0"]["E0"]
    regrets = {ai: matrix[ai]["E0"] / e0_opt for ai in sr.ARMS}
    # the IN-TARGET noise band (day-12 review): E0's own seven-start
    # scatter, the correct scale for mix-target verdicts; the S3 1.8%
    # was measured on the pure fan-out target and stays as context
    psb = list(arms["E0"]["per_start_best"].values())
    e0_band = max(psb) / min(psb) - 1.0
    # NOTE: this field is the mechanical 0.5/0.5 read; the FINAL verdict
    # additionally applies the pre-registered weight-robustness clause
    # (a "definitely wrong" must survive the mu = {0.3, 0.7} re-scoring
    # below) -- the FIXLIST record carries the final verdicts.
    verdicts = {ai: ("definitely wrong" if regrets[ai] > 1 + NOISE_BAND
                     else ("possibly wrong" if regrets[ai] > 1.0 + 1e-12
                           else "at optimum"))
                for ai in sr.ARMS if ai != "E0"}
    out["active"] = {
        "e0_own_band": e0_band,
        "e0_per_start_best": arms["E0"]["per_start_best"],
        "matrix": matrix, "regrets": regrets, "verdicts": verdicts,
        "arm_solutions": {ai: arms[ai]["pi"].to_json() for ai in sr.ARMS},
        "self_best": {ai: arms[ai]["self_best"] for ai in sr.ARMS},
        "best_start": {ai: arms[ai]["best_start"] for ai in sr.ARMS},
        "e0_rungs": arms["E0"]["rungs"]}
    print("regrets vs E0 optimum "
          + ", ".join(f"{a}={regrets[a]:.4f}" for a in sr.ARMS))

    # BENIGN-LOAD CONTROL LEG: condition = chain one-hot; truth there =
    # the chain leg. Terminology ruling (day-12 review): this is NOT a
    # "safe cell" -- that term is reserved for masked cells where every
    # seating ties (the within-die g = 2.0 kind); under the chain load
    # seatings still matter, it is merely benign.
    print("BENIGN-LOAD CONTROL LEG (chain one-hot condition)")
    truth_c = sr.make_E2(cx.host())
    safe_arms = {
        "truth_chain": run_arm(sr.make_E2(cx.host()), seeds,
                               "truth_chain"),
        "E1_chain": run_arm(sr.DistanceProxyJ(cx.host(), {"chain": 1.0}),
                            seeds, "E1_chain"),
        "E3_chain": run_arm(sr.MixJ(sr.host_ring(), {"chain": 1.0}),
                            seeds, "E3_chain")}
    safe_scores = {n: truth_c(a["pi"]) for n, a in safe_arms.items()}
    safe_scores["E2b_fanout_argmin"] = truth_c(arms["E2b"]["pi"])
    s_opt = safe_scores["truth_chain"]
    out["benign_control"] = out["safe"] = {"scores": safe_scores,
                   "regrets": {n: v / s_opt
                               for n, v in safe_scores.items()}}
    print("control-leg regrets "
          + ", ".join(f"{n}={v/s_opt:.4f}" for n, v in safe_scores.items()))

    # WEIGHT SENSITIVITY: mu = {0.3, 0.7}
    print("WEIGHT SENSITIVITY mu = {chain 0.3, fanout 0.7}")
    mu2 = {"chain": 0.3, "fanout": 0.7}
    E0p = sr.MixJ(cx.host(), mu2)
    e0p_arm = run_arm(sr.MixJ(cx.host(), mu2), seeds, "E0'(0.3/0.7)")
    e0p_opt = min(e0p_arm["self_best"], *(E0p(arms[a]["pi"])
                                          for a in sr.ARMS))
    regrets2 = {a: E0p(arms[a]["pi"]) / e0p_opt for a in sr.ARMS}
    out["weights_0307"] = {"regrets": regrets2,
                           "e0p_self_best": e0p_arm["self_best"]}
    print("regrets under mu'=0.3/0.7: "
          + ", ".join(f"{a}={regrets2[a]:.4f}" for a in sr.ARMS))

    out["active"]["arm_solutions"] = {ai: arms[ai]["pi"].to_json()
                                      for ai in sr.ARMS}
    ser = dict(out)
    json.dump(ser, open(OUT_JSON, "w"), indent=1, default=str)
    print(f"results -> {OUT_JSON}")

    # figure: the matrix as a normalized heatmap + the regret bar
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    ax = axes[0]
    names = list(sr.ARMS)
    norm = [[matrix[ai][ei] / min(matrix[x][ei] for x in names)
             for ei in names] for ai in names]
    im = ax.imshow(norm, cmap="YlOrRd", vmin=1.0,
                   vmax=max(max(r) for r in norm))
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([f"judge {n}" for n in names], rotation=30,
                       ha="right", fontsize=8)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels([f"argmin {n}" for n in names], fontsize=8)
    for i in range(len(names)):
        for j in range(len(names)):
            ax.text(j, i, f"{norm[i][j]:.2f}", ha="center", va="center",
                    fontsize=7,
                    color="white" if norm[i][j] > 1.5 else "black")
    ax.set_title("cross-scoring, column-normalized\n(1.00 = that judge's"
                 " best row)", fontsize=9)
    fig.colorbar(im, ax=ax, shrink=0.8)
    ax2 = axes[1]
    arms_x = [a for a in sr.ARMS if a != "E0"]
    vals = [(regrets[a] - 1) * 100 for a in arms_x]
    ax2.bar(range(len(arms_x)), vals,
            color=["#c44" if v > NOISE_BAND * 100 else "#e9b"
                   for v in vals])
    ax2.axhline(NOISE_BAND * 100, color="#444", ls="--", lw=1,
                label="S3 noise band 1.8%")
    ax2.set_xticks(range(len(arms_x)))
    ax2.set_xticklabels(arms_x)
    ax2.set_ylabel("E0 regret above optimum (%)")
    ax2.set_title("the truth's verdict on each arm's argmin", fontsize=9)
    ax2.legend(fontsize=8)
    for i, v in enumerate(vals):
        ax2.text(i, v, f"{v:.1f}%", ha="center", va="bottom", fontsize=8)
    fig.suptitle("S6 referee family: each arm searches, E0 judges "
                 "(active mix cell)", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=150)
    print(f"figure -> {OUT_PNG}")


if __name__ == "__main__":
    main()
