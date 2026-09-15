"""S4 review figure 2 (drawn now on the user's instruction; the
reviewer notes it may be RESEEDED when section 5 takes shape after S6
-- recorded in FIXLIST): the three-axis overview of where the
compact-vs-dispersed empirical rule survives a condition change.

Three slopegraph panels, one pair of seatings each, left condition ->
right condition: (1) the LOAD axis -- clustered vs snake on the
busiest wire, pure chain -> fan-out: the lines CROSS (rank
inversion, check-C / the ordering instance); (2) the CELL axis --
shipped-contiguous vs interleaved-optimum per-die joint cost on the
ffn die, 0.4 -> 2.0 GB/s: the lines CONVERGE to a tie (MASKING, the
magnitude -> 0; deliberately NOT drawn as an inversion, per the
settled scope wording); (3) the WEAVE axis -- clustered vs snake on
the surplus-traffic channel, mesh -> ring: the lines CROSS (F-L4).
Units differ per panel and are labeled per panel; the panel VERDICT
carries the comparison, not a shared scale.

    python3 scripts/fig_condition_axes.py -> analysis/condition_axes.png
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import search_eval as se
from scripts import search_withindie as sw

OUT = os.path.join(se.A, "condition_axes.png")

# panel 1: filed check-C / ordering-instance readings (M words)
P1 = {"clustered": (6.18, 30.00), "snake": (15.06, 28.00)}
# panel 3: the weave figure's computed surplus channel (G word-hops)
P3 = {"clustered": (2.67, 118.8), "snake": (4.25, 20.05)}


def panel2():
    J04 = sw.WithinDieJ("ffn", "prefill", 0.4)
    J20 = sw.WithinDieJ("ffn", "prefill", 2.0)
    shipped = sw.SHIPPED["ffn"]
    best = J04.exhaustive()[0][2]
    return {"shipped (contiguous)": (J04.cost_of(shipped) * 1e3,
                                     J20.cost_of(shipped) * 1e3),
            "interleaved optimum": (J04.cost_of(best) * 1e3,
                                    J20.cost_of(best) * 1e3)}


def main():
    P2 = panel2()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.0))
    panels = [
        (axes[0], P1, ("pure chain", "fan-out +2/+4/+8"),
         "busiest wire (M words)",
         "LOAD axis: INVERTS", ("clustered", "snake")),
        (axes[1], P2, ("0.4 GB/s cell", "2.0 GB/s cell"),
         "ffn-die joint cost (ms)",
         "CELL axis: MASKS (gap → 0)",
         ("shipped (contiguous)", "interleaved optimum")),
        (axes[2], P3, ("mesh", "ring"),
         "surplus traffic (G word-hops)",
         "WEAVE axis: 'compact' is weave-relative", ("clustered", "snake")),
    ]
    for ax, data, (lc, rc), ylab, title, names in panels:
        for name in names:
            a, b = data[name]
            color = "#c44" if "clustered" in name or "contiguous" in name \
                else "#37a"
            ax.plot([0, 1], [a, b], "-o", color=color, label=name)
            ax.annotate(f"{a:.2f}", (0, a), textcoords="offset points",
                        xytext=(-6, 4), ha="right", fontsize=7)
            ax.annotate(f"{b:.2f}", (1, b), textcoords="offset points",
                        xytext=(6, 4), ha="left", fontsize=7)
        ax.set_xticks([0, 1])
        ax.set_xticklabels([lc, rc], fontsize=8)
        ax.set_xlim(-0.35, 1.35)
        ax.set_ylabel(ylab, fontsize=8)
        ax.set_title(title, fontsize=9)
        ax.legend(fontsize=7)
    fig.suptitle("one mechanism, three failure modes: the load axis "
                 "INVERTS the rule, the cell axis MASKS it, the weave "
                 "axis REDEFINES what compact means -- a seating "
                 "optimized for one weave is wrong under another",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT, dpi=150)
    print(f"figure -> {OUT}")


if __name__ == "__main__":
    main()
