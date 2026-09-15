"""S4 review figure 1: the WEAVE-AXIS rank inversion (EX2 material,
graphed for section 5 / the search chapter).

Two panels, ring | torus, all SEVEN named baselines each, one shared
y-axis (the review's craft note: a different scale per panel would
mask the inversion). Y unit = the D2D SURPLUS TRAFFIC in G word-hops
-- exactly the measured E-column channel divided by the energy price
(E = seat-invariant floor + PJ_D2D x word-hops), i.e. the
communication volume the weave condition acts on. Grey markers carry
the mesh reference so "wholesale shift" (torus) vs "reordering"
(ring) reads directly. X order is fixed to the mesh E ladder in both
panels.

    python3 scripts/fig_weave_inversion.py
      -> analysis/weave_inversion.png + analysis/weave_inversion.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import search_baselines as sb
from scripts import search_eval as se

PJ = se.PJ_D2D * 1e-12
OUT_PNG = os.path.join(se.A, "weave_inversion.png")
OUT_JSON = os.path.join(se.A, "weave_inversion.json")
WEAVES = {"mesh": None, "ring": ("ring", {}), "torus": ("torus", {})}


def surplus_gwh(W, pi):
    sc = se.score(pi, W, d2d_gbps=12.5)
    d = sc.per_phase["prefill"]["decomp"]
    return d["d2d_surplus_J"] / PJ / 1e9, sc.e_J


def main():
    data = {}
    for wname, weave in WEAVES.items():
        W = se.Workload2p7B(die_weave=weave)
        rows = {}
        for name in sb.NAMES:
            pi = sb.generate(name, W, seed=0)
            gwh, e = surplus_gwh(W, pi)
            rows[name] = {"surplus_gwordhops": gwh, "e_J": e}
        data[wname] = rows
        print(wname, {n: round(r["surplus_gwordhops"], 2)
                      for n, r in sorted(rows.items(),
                                         key=lambda kv:
                                         kv[1]["surplus_gwordhops"])})
    json.dump(data, open(OUT_JSON, "w"), indent=1)

    order = sorted(sb.NAMES,
                   key=lambda n: data["mesh"][n]["surplus_gwordhops"])
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ymax = 1.08 * max(data[w][n]["surplus_gwordhops"]
                      for w in ("ring", "torus") for n in sb.NAMES)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True)
    for ax, wname, verdict in ((axes[0], "ring",
                                "REORDERS: snake < clustered"),
                               (axes[1], "torus",
                                "order kept, wholesale shift up")):
        x = range(len(order))
        vals = [data[wname][n]["surplus_gwordhops"] for n in order]
        ref = [data["mesh"][n]["surplus_gwordhops"] for n in order]
        colors = ["#c44" if n in ("snake", "clustered") else "#888"
                  for n in order]
        ax.bar(x, vals, color=colors)
        ax.plot(x, ref, "o", color="#444", ms=4, label="mesh reference")
        for i, v in enumerate(vals):
            ax.text(i, v, f"{v:.1f}", ha="center", va="bottom", fontsize=7)
        ax.set_xticks(x)
        ax.set_xticklabels(order, rotation=35, ha="right", fontsize=8)
        ax.set_title(f"{wname}: {verdict}", fontsize=9)
        ax.set_ylim(0, ymax)
        ax.legend(fontsize=7, loc="upper left")
    axes[0].set_ylabel("D2D surplus traffic (G word-hops)\n"
                       "= the E column's seat-dependent channel / 10 pJ")
    fig.suptitle("the weave axis: same seven seatings, one shared scale --"
                 " ring reorders them, torus only shifts them", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=150)
    print(f"figure -> {OUT_PNG}")


if __name__ == "__main__":
    main()
