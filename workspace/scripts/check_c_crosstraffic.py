"""S2 closeout item 2 (C64-c): check C reinforcement -- the MEASURED leg.

Check C filed the one-off: on the 2.7B pure pipeline chain the Gemini
congestion pathology does NOT appear (clustered busiest wire 10.49M vs
sequential/snake 26.21M) and the inspection closed it by REASONING: the
pathology's premise -- "dependencies between certain layers may have
particularly high data transfer requirements" competing many-to-many --
is absent from a pure chain. This script upgrades that closure to
MEASURED: it supplies the premise synthetically and reads the wires.

Synthetic pattern (declared): on the 2.7B host (24x24 grid, 32 layer
stages x 17 dies, the exact clustered geometry), every stage s sends an
equal V to stages s+2, s+4 and s+8 (no wrap) -- multi-target fan-out to
non-adjacent stages, so cross-flows COMPETE on shared wires. Flow
construction reuses the frozen R-split boundary convention verbatim
(producer splits V across its dies; every consumer die receives every
piece -- search_eval._one_boundary_flows); routing and per-wire
accumulation reuse crossbar_comm.link_occupancy unchanged. A uniform
per-boundary CHAIN pattern rides as control (exploratory, no hand: it
isolates the border-width effect from check C's real-words multicast
asymmetry).

PRE-REGISTERED HANDS (before any number was read):
  E+ (the directive's hand): with the premise supplied, clustered's
      busiest wire >= snake's and >= sequential's -- the pathology
      appears once its premise exists.
  E- (check C's mechanism hand): the wide-rectangle-border mechanism
      still disperses the demand and clustered stays better; then the
      non-flip is a FINDING -- on this host the pathology needs
      Gemini's own dispersed-placement competitor, not corridor
      baselines.

Bandwidth note: busiest-wire VOLUME (words) is the metric; a nominal
1 word/cycle die bandwidth is set only so link_occupancy routes the
flows (volume is bandwidth-independent).
"""
import dataclasses as dc
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.crossbar_comm as cc
from scripts import search_baselines as sb
from scripts import search_eval as se

V = 1e6                                   # words per synthetic flow
FANOUT = (2, 4, 8)                        # non-adjacent targets per stage
SEATINGS = ("sequential", "snake", "clustered", "least_manhattan",
            "nmap_greedy", "heaviest_first", "random")
OUT = os.path.join(se.A, "check_c_crosstraffic.png")


def host():
    W = se.Workload2p7B()
    levels = [dc.replace(l, link=dc.replace(l.link,
                                            bandwidth_words_per_cycle=1.0))
              if l.name == "die" else l for l in W.fab.levels]
    W.fab = dc.replace(W.fab, name="xtraffic", levels=levels).validate()
    return W


def stage_sets(pi):
    """Stage li -> the union of its ops' die seats (layer = the Gemini
    'layer assigned to a core group' granularity)."""
    by = {}
    for n, seats in pi.seat.items():
        by.setdefault(int(n.rsplit("@L", 1)[1]), []).append(seats)
    return {li: sorted(set(s for tup in v for s in tup))
            for li, v in by.items()}


def measure(W, pi, pairs):
    sets = stage_sets(pi)
    flows = []
    for s, t in pairs:
        prev_e = {"name": f"stage{s}", "out_words": V, "split": "R"}
        e = {"name": f"stage{t}", "in_words": V}
        flows += se._one_boundary_flows(prev_e, e, sets[s], sets[t], W.fab)
    occ = cc.link_occupancy(flows, W.fab, W.fab.device.cycle_seconds, W.pl)
    loaded = sorted(occ["per_link"], key=lambda r: -r["volume"])
    return {"busiest": loaded[0]["volume"], "witness": loaded[0],
            "total": sum(r["volume"] for r in loaded),
            "n_wires": len(loaded), "top": loaded[:5]}


def main():
    W = host()
    n = 32
    chain = [(s, s + 1) for s in range(n - 1)]
    fanout = [(s, s + k) for s in range(n) for k in FANOUT if s + k < n]
    rows = {}
    for name in SEATINGS:
        pi = sb.generate(name, W, seed=0)
        rows[name] = {"chain": measure(W, pi, chain),
                      "fanout": measure(W, pi, fanout)}
    print(f"synthetic cross-traffic, V={V:.0f} words/flow, "
          f"fan-out targets +{FANOUT}, {len(fanout)} stage pairs")
    print(f"{'seating':16} {'chain busiest(M)':>17} {'fanout busiest(M)':>18} "
          f"{'fanout total(M)':>16} {'loaded wires':>13}")
    for name in SEATINGS:
        r = rows[name]
        print(f"{name:16} {r['chain']['busiest']/1e6:17.2f} "
              f"{r['fanout']['busiest']/1e6:18.2f} "
              f"{r['fanout']['total']/1e6:16.1f} {r['fanout']['n_wires']:13d}")
    print("\nfanout bottleneck wires (top 5), clustered vs snake:")
    for name in ("clustered", "snake"):
        print(f"  {name}:")
        for t in rows[name]["fanout"]["top"]:
            print(f"    {t['resource']:36} {t['volume']/1e6:8.2f}M "
                  f"{t.get('direction', '')}")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=False)
    for ax, pat, title in ((axes[0], "chain", "uniform chain (control:\n"
                            "premise absent, border width only)"),
                           (axes[1], "fanout", "many-to-many fan-out "
                            "(+2,+4,+8):\nthe Gemini premise supplied")):
        vals = [rows[nm][pat]["busiest"] / 1e6 for nm in SEATINGS]
        colors = ["#c44" if nm == "clustered" else "#888" for nm in SEATINGS]
        ax.bar(range(len(SEATINGS)), vals, color=colors)
        ax.set_xticks(range(len(SEATINGS)))
        ax.set_xticklabels(SEATINGS, rotation=35, ha="right", fontsize=8)
        ax.set_title(title, fontsize=9)
        ax.set_ylabel("busiest wire volume (M words)")
        for i, v in enumerate(vals):
            ax.text(i, v, f"{v:.1f}", ha="center", va="bottom", fontsize=7)
    fig.suptitle("check C reinforcement: busiest die wire under synthetic "
                 "cross-traffic (2.7B host, 32 stages x 17 dies)", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT, dpi=150)
    print(f"\nfigure -> {OUT}")


if __name__ == "__main__":
    main()
