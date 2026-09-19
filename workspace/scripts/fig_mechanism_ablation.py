"""Figure for the report: (left) path length vs bottleneck load per layout
at the main configuration, from mechanism_table.json; (right) the
same-budget objective ablation at kappa = 2, from objective_ablation_k2.json.

    python3 scripts/fig_mechanism_ablation.py -> analysis/mechanism_ablation.png
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import search_eval as se

PNG = os.path.join(se.A, "mechanism_ablation.png")
NAVY, AMBER, GREEN, GREY = "#2e4a66", "#7a5c00", "#2a7d4f", "#8c8c8c"


def main():
    mt = json.load(open(os.path.join(se.A, "mechanism_table.json")))["layouts"]
    ab = json.load(open(os.path.join(se.A, "objective_ablation_k2.json")))["cells"]["k2"]
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(11, 4.0))
    kinds = {"default_A4": ("default fill (= sequential)", NAVY, "s"),
             "clustered": ("clustered", AMBER, "^"), "nmap_greedy": ("nmap_greedy", AMBER, "v"),
             "least_manhattan": ("least_manhattan", AMBER, "<"), "heaviest_first": ("heaviest_first", AMBER, ">"),
             "random": ("random seed 0", GREY, "o"), "random_s3": ("strongest random (s3)", GREY, "D"),
             "sa_random_s1": ("search endpoint (headline)", GREEN, "*")}
    for n, (lab, col, mk) in kinds.items():
        if n == "sequential":
            continue
        r = mt[n]
        ax.scatter(r["word_hops_total"] / 1e9, r["A_words"] / 1e6, s=80 if mk == "*" else 45,
                   color=col, marker=mk, label=lab, zorder=5, edgecolor="white", linewidth=0.6)
        dy = {"random": 10, "random_s3": -10}.get(n, 4)
        ax.annotate(f"{r['T_s']*1e3:.0f} ms", (r["word_hops_total"] / 1e9, r["A_words"] / 1e6),
                    textcoords="offset points", xytext=(6, dy), fontsize=7, color=col)
    ax.set_xlabel("total routed traffic (G word-hops)")
    ax.set_ylabel("aggregate bottleneck load A (M words)")
    ax.set_title("Path length is not bottleneck load (κ = 2, 0.4 GB/s; label = latency)", fontsize=9)
    ax.grid(alpha=0.2)
    ax.legend(fontsize=7, loc="upper right")
    names = ["ours", "wire_only", "word_hops", "max_hops"]
    labels = ["resource-aware\n(links + ports)", "links only\n(ports unpriced)", "word-hops\n(distance proxy)", "max hops\n(propagation only)"]
    strongest = ab["strongest_baseline_single"]
    T_ref = ab["rows"][strongest]["T_single_s"]
    colors = [GREEN, "#5d7ea3", AMBER, GREY]
    w, gap = 0.22, 0.03                      # three seed bars per objective
    for i, n in enumerate(names):
        ends = ab["per_objective"][n]["endpoints"]
        vals = [(1 - ab["rows"][e]["T_single_s"] / T_ref) * 100 for e in ends]
        xs = [i + (k - 1) * (w + gap) for k in range(len(vals))]
        bx.bar(xs, vals, color=colors[i], width=w, zorder=3,
               alpha=1.0, edgecolor="white", linewidth=0.5)
        top = max(vals)
        bx.annotate(f"best {top:.2f}%", (i, top), textcoords="offset points",
                    xytext=(0, 4), ha="center", fontsize=7.5, color=colors[i])
    bx.axhline(0, color="0.3", lw=0.8)
    bx.set_xticks(range(4))
    bx.set_xticklabels(labels, fontsize=7.5)
    bx.set_ylabel(f"latency reduction vs {strongest} (%)")
    bx.set_ylim(top=13)
    bx.set_title("Same search, same budget, four objectives (three bars = three seeds)", fontsize=9)
    bx.grid(alpha=0.2, axis="y")
    fig.tight_layout()
    fig.savefig(PNG, dpi=150)
    print(f"-> {PNG}")


if __name__ == "__main__":
    main()
