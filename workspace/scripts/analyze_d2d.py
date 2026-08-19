"""D2D (W3) results: where the die-level placement actually shows.

Two operating modes of the same 24-die package, and the mode decides what the
layout can touch:

  SINGLE PASS (one request walks the 24 dies in series): each boundary
  transfer hides behind the WHOLE stack's compute (249 ms), so at any sane
  link speed the total never moves -- the honest statement is "invisible in
  this mode", and pretending otherwise would be the dishonest chart.

  PIPELINED (the real serving mode: different microbatches on different dies,
  every boundary transferring concurrently each beat): the transfer races ONE
  stage's compute (stall-free/24 = 13.1 ms), and the busiest die wire sets the
  beat. Here the assignment is a direct throughput multiplier.

Three figures, designed around that split:
  1 d2d_assignment_impact.png -- the quantities the layout changes REGARDLESS
    of bandwidth (busiest wire, surplus energy, total wire time).
  2 d2d_regimes.png           -- when those quantities reach the totals:
    single-pass (left) vs pipelined (right) over the bandwidth axis.
  3 d2d_segment_map.png       -- which package wire carries how many
    boundaries, per assignment.

System denominators come from analysis/contention_system.json (real mapper
runs); everything else is closed-form. Die bandwidth / energy are platform
inputs (example defaults); multipliers, orderings, thresholds are the result.

Usage (container): python3 scripts/analyze_d2d.py
"""
import dataclasses
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import scripts.crossbar_comm as cc
from scripts import fabric as fabric_mod
from scripts import llm_workload as lw
from scripts import placement as placement_mod

OUT = "/home/workspace/analysis"
MULTI = "/home/workspace/models/fabric/mlx300_multidie.yaml"
CYC = 1.449e-6
S = 512
BW_SWEEP = [float(2 ** k) for k in range(0, 15)]
BW_POINT = 256.0
CFG = lw.GptConfig()
WORDS = S * CFG.d_model


def assignments(fab):
    mx, _ = fab.level("die").mesh
    n = CFG.n_layers
    snake = []
    for L in range(n):
        row, col = divmod(L, mx)
        snake.append(row * mx + (mx - 1 - col if row % 2 else col))
    adv = [L // 2 if L % 2 == 0 else 23 - L // 2 for L in range(n)]
    return [("snake", snake), ("sequential rows", list(range(n))),
            ("far pairs (adversarial)", adv)]


def with_link(fab, topology, params, bw):
    levels = []
    for lv in fab.levels:
        if lv.name == "die":
            lv = dataclasses.replace(
                lv, link=dataclasses.replace(lv.link, topology=topology,
                                             params=params,
                                             bandwidth_words_per_cycle=bw))
        levels.append(lv)
    return dataclasses.replace(fab, name="d2d-variant", levels=levels).validate()


def main():
    sysfile = os.path.join(OUT, "contention_system.json")
    if not os.path.exists(sysfile):
        raise SystemExit(f"run analyze_contention_system.py first ({sysfile})")
    with open(sysfile) as f:
        sysdata = json.load(f)
    sf = sysdata["phases"]["prefill"]["stall_free_s"]
    comp = sysdata["phases"]["prefill"]["compute_s"]
    stage = sf / CFG.n_layers
    base = fabric_mod.from_yaml(MULTI)
    print(f"{base.level('die').per_parent} dies on {base.level('die').mesh}; "
          f"prefill stall-free {sf*1e3:.2f} ms, one stage {stage*1e3:.2f} ms\n")

    # ---------------- the bandwidth-free quantities per assignment
    print("=== what the assignment changes, at ANY bandwidth (mesh) ===")
    rows = []
    fabM = with_link(base, "mesh", {"routing": "xy", "hub": "center"}, BW_POINT)
    pl = placement_mod.sequential_fill(fabM)
    for label, asg in assignments(fabM):
        d = lw.die_to_die_activation(CFG, S, "prefill", fabric=fabM,
                                     assignment=asg)
        occ = cc.link_occupancy(d["flows"], fabM, CYC, pl)
        busiest = occ["bottleneck"]["volume"] / WORDS if occ["bottleneck"] else 0
        rows.append({"assignment": label, "asg": asg,
                     "avg_hops": d["avg_die_hops"],
                     "busiest_x": busiest,
                     "surplus_uJ": d["energy_J"] * 1e6,
                     "wire_ms_at_point": occ["serialization_s"] * 1e3})
        print(f"  {label:24} avg hops {d['avg_die_hops']:5.2f} | busiest wire "
              f"{busiest:3.0f} boundaries | surplus E {d['energy_J']*1e6:8.2f} uJ")

    # ---------------- two modes over bandwidth
    def single_pass_mult(fab, asg):
        d = lw.die_to_die_activation(CFG, S, "prefill", fabric=fab,
                                     assignment=asg)
        occ = cc.link_occupancy(d["flows"], fab, CYC,
                                placement_mod.sequential_fill(fab))
        wr = sysdata["phases"]["prefill"]["write_s"]
        return (wr + max(comp, occ["serialization_s"]) + (sf - wr - comp)) / sf

    def pipe_mult(fab, asg):
        d = lw.die_pipeline_interval(CFG, S, "prefill", stage, fabric=fab,
                                     assignment=asg, cycle_seconds=CYC)
        return d["interval_s"] / stage

    VARIANTS = [(lbl, "mesh", {"routing": "xy", "hub": "center"}, asg)
                for lbl, asg in assignments(base)]
    VARIANTS.append(("bus (shared interposer)", "bus", {"driver": "center"},
                     list(range(CFG.n_layers))))

    single, pipe = {}, {}
    for lbl, topo, params, asg in VARIANTS:
        single[lbl] = [single_pass_mult(with_link(base, topo, params, bw), asg)
                       for bw in BW_SWEEP]
        pipe[lbl] = [pipe_mult(with_link(base, topo, params, bw), asg)
                     for bw in BW_SWEEP]

    print(f"\n=== the two operating modes at the example point "
          f"({BW_POINT:,.0f} w/c) and at 64 w/c ===")
    print(f"{'':26}{'single-pass':>14}{'pipelined':>12}"
          f"{'single-pass':>14}{'pipelined':>12}")
    print(f"{'':26}{'@256':>14}{'@256':>12}{'@64':>14}{'@64':>12}")
    i256, i64 = BW_SWEEP.index(256.0), BW_SWEEP.index(64.0)
    for lbl, _, _, _ in VARIANTS:
        print(f"  {lbl:24}{single[lbl][i256]:>13.2f}x{pipe[lbl][i256]:>11.2f}x"
              f"{single[lbl][i64]:>13.2f}x{pipe[lbl][i64]:>11.2f}x")

    # knees (pipelined): bandwidth below which throughput degrades / halves
    print("\n  pipelined knees (throughput leaves the compute-bound plateau):")
    knees = {}
    for lbl, ys in pipe.items():
        k1 = max((bw for bw, y in zip(BW_SWEEP, ys) if y >= 1.01), default=None)
        k2 = max((bw for bw, y in zip(BW_SWEEP, ys) if y >= 2.0), default=None)
        knees[lbl] = {"degrades_below": k1, "halves_below": k2}
        print(f"    {lbl:24} degrades below {k1 and f'{k1:,.0f}' or '-':>7} w/c"
              f" | halves below {k2 and f'{k2:,.0f}' or '-':>7} w/c")

    # ---------------- figure 1: bandwidth-free quantities
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.9))
    labels = [r["assignment"] for r in rows]
    colors = ["#2a9d8f", "#8fa8bf", "#d1495b"]
    for ax, key, title, fmt in (
            (axes[0], "busiest_x", "busiest die wire\n(boundaries crossing it)", "{:.0f}"),
            (axes[1], "surplus_uJ", "surplus D2D energy\n(uJ beyond the flat charge)", "{:.1f}"),
            (axes[2], "avg_hops", "average boundary hops\n(propagation + energy driver)", "{:.2f}")):
        vals = [r[key] for r in rows]
        ax.barh(range(len(rows))[::-1], vals, color=colors, height=0.62)
        for i, v in enumerate(vals):
            ax.text(v, len(rows) - 1 - i, " " + fmt.format(v), va="center",
                    fontsize=10, fontweight="bold")
        ax.set_yticks(range(len(rows))[::-1])
        ax.set_yticklabels(labels if ax is axes[0] else [""] * len(rows),
                           fontsize=10)
        ax.set_title(title, fontsize=10)
        ax.set_xlim(0, max(vals) * 1.3)
        ax.grid(alpha=0.25, axis="x")
    fig.suptitle("What the layer-to-die assignment changes -- at ANY bandwidth\n"
                 "(same 24 dies, same mesh, same traffic; only the assignment "
                 "differs)", fontsize=11)
    p1 = os.path.join(OUT, "d2d_assignment_impact.png")
    fig.tight_layout(rect=[0, 0, 1, 0.86]); fig.savefig(p1, dpi=130)
    plt.close(fig)
    print(f"\nPNG -> {p1}")

    # ---------------- figure 2: the two regimes
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 5.0), sharex=True)
    styles = {"snake": ("#2a9d8f", "-"), "sequential rows": ("#8fa8bf", "-"),
              "far pairs (adversarial)": ("#d1495b", "-"),
              "bus (shared interposer)": ("#7b2d8b", "--")}
    for ax, data, title, ylab in (
            (axes[0], single, "SINGLE PASS: one request in flight\n"
             "transfer hides behind the whole stack's compute -> flat at 1.0",
             "stack latency / stall-free"),
            (axes[1], pipe, "PIPELINED: the real serving mode\n"
             "transfer races ONE stage -> the assignment is a throughput lever",
             "beat interval / compute-bound beat")):
        for lbl, ys in data.items():
            c, ls = styles[lbl]
            ax.plot(BW_SWEEP, ys, "o" + ls, color=c, ms=3.5, lw=1.7, label=lbl)
        ax.axvline(BW_POINT, color="0.5", ls=":", lw=1.2)
        ax.text(BW_POINT * 1.15, ax.get_ylim()[1], "", fontsize=8)
        ax.set_xscale("log", base=2); ax.set_yscale("log")
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("die link bandwidth (words/cycle) -- platform input")
        ax.set_ylabel(ylab)
        ax.grid(alpha=0.3, which="both")
    axes[1].legend(fontsize=8.5, loc="upper right")
    axes[1].annotate("bus already 5.2x at the\nexample point (dotted)",
                     xy=(BW_POINT, pipe["bus (shared interposer)"][i256]),
                     xytext=(BW_POINT * 6, 8), fontsize=9, color="#7b2d8b",
                     arrowprops=dict(arrowstyle="->", color="#7b2d8b"))
    fig.suptitle("The operating mode decides whether the die layout can reach "
                 "the totals", fontsize=12)
    p2 = os.path.join(OUT, "d2d_regimes.png")
    fig.tight_layout(rect=[0, 0, 1, 0.9]); fig.savefig(p2, dpi=130)
    plt.close(fig)
    print(f"PNG -> {p2}")

    # ---------------- figure 3: segment maps per assignment
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.2))
    for ax, (label, asg) in zip(axes, assignments(fabM)):
        d = lw.die_to_die_activation(CFG, S, "prefill", fabric=fabM,
                                     assignment=asg)
        occ = cc.link_occupancy(d["flows"], fabM, CYC, pl)
        loads = {e["resource"]: e["volume"] for e in occ["per_link"]}
        peak = max(loads.values())
        for res, v in loads.items():
            a, b = res.split("seg", 1)[1].split(")-(")
            pp = tuple(float(z) for z in a.strip("()").split(","))
            qq = tuple(float(z) for z in b.strip("()").split(","))
            ax.plot([pp[0], qq[0]], [pp[1], qq[1]], "-",
                    lw=1.5 + 6 * v / peak,
                    color=plt.cm.YlOrRd(0.25 + 0.7 * v / peak),
                    solid_capstyle="round", zorder=1)
            ax.text((pp[0] + qq[0]) / 2, (pp[1] + qq[1]) / 2,
                    f"{v/WORDS:.0f}", fontsize=7.5, ha="center", va="center",
                    zorder=3, bbox=dict(fc="white", ec="none", alpha=0.85,
                                        pad=0.1))
        for i, sl in enumerate(pl.slots["die"]):
            ax.plot(sl[0], sl[1], "s", ms=15, mfc="#dfe6ee", mec="k", zorder=2)
            ax.text(sl[0], sl[1], f"{asg.index(i)}", fontsize=6.5, ha="center",
                    va="center", zorder=4)
        busiest = peak / WORDS
        ax.set_title(f"{label}\nbusiest wire: {busiest:.0f} boundaries "
                     f"-> pipelined beat {busiest:.0f}x words/bw", fontsize=9.5)
        xs = [sl[0] for sl in pl.slots["die"]]
        ys_ = [sl[1] for sl in pl.slots["die"]]
        ax.set_xlim(min(xs) - 0.6, max(xs) + 0.6)
        ax.set_ylim(min(ys_) - 0.6, max(ys_) + 0.6)
        ax.set_aspect("equal"); ax.invert_yaxis(); ax.axis("off")
    fig.suptitle("Which package wire carries how many boundaries -- squares = "
                 "dies (number = layer), the busiest wire sets the pipelined "
                 "beat", fontsize=11)
    p3 = os.path.join(OUT, "d2d_segment_map.png")
    fig.tight_layout(rect=[0, 0, 1, 0.88]); fig.savefig(p3, dpi=130)
    plt.close(fig)
    print(f"PNG -> {p3}")

    with open(os.path.join(OUT, "d2d_impact.json"), "w") as f:
        json.dump({"S": S, "n_dies": base.level("die").per_parent,
                   "stage_s": stage, "stall_free_s": sf,
                   "example_bw": BW_POINT, "bw_sweep": BW_SWEEP,
                   "assignments": [{k: v for k, v in r.items() if k != "asg"}
                                   for r in rows],
                   "single_pass": single, "pipelined": pipe,
                   "pipelined_knees": knees}, f, indent=1)
    print("JSON -> d2d_impact.json")


if __name__ == "__main__":
    main()
