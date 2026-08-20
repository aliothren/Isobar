"""The scale study: does layout leverage grow with model size?

Three tiers, one question each, one combined answer:

  tier S -- GPT-2 medium (355M): every operator fits one die. Layout acts
            through the ON-DIE network only (anchored_sweep.json).
  tier M -- one spanning operator (2.7B-class FFN, 4 dies): the intra-op
            flood crosses the package (multidie_placement.json).
  tier L -- the FULL 2.7B-class model (32 layers; static ops span 2-5 dies
            each by the residency tiler): both effects compose
            (scale_2p7b_per_op.json).

All die-level readouts are stated at the one silicon-measured D2D anchor we
have (Simba GRS, 12.5 GB/s per link direction); on-die readouts at the three
NoC anchors (ANCHORS.md). Figures: one per tier + one combined.

Usage (container): python3 scripts/analyze_scale_tiers.py
"""
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts import fabric as fabric_mod
from scripts import interconnect as ic
from scripts import placement as pm
import dataclasses

OUT = "/home/workspace/analysis"
CYC = 1.4485714285714284e-06
WC_PER_GBPS = 1e9 * CYC
GRS = 12.5                        # GB/s, Simba package mesh (measured)
NOC = [("Simba 8.75", 8.75), ("ESP 32", 32.0), ("FlooNoC 80.6", 80.6)]
REF_WC = 16384.0
PJ = 10.0e-12
TEAL, SLATE, RED, GOLD = "#2a9d8f", "#8fa8bf", "#d1495b", "#e8a13c"


def die_styles(fab, n):
    """Three deterministic ways to place an op's n dies on the package grid."""
    slots = pm.sequential_fill(fab).slots["die"]
    hub = ic.build(fab, "die", pm.sequential_fill(fab)).hub_coord()
    clustered = sorted(slots, key=lambda s: abs(s[0]-hub[0])+abs(s[1]-hub[1]))[:n]
    rowfill = slots[:n]
    spread = [slots[0]]
    rest = [s for s in slots if s != slots[0]]
    while len(spread) < n:
        s = max(rest, key=lambda x: min(abs(x[0]-t[0])+abs(x[1]-t[1])
                                        for t in spread))
        spread.append(s); rest.remove(s)
    return [("clustered", clustered), ("row-fill", rowfill),
            ("spread", spread)]


def die_serial(fab, slots_n, edge_words, wc):
    """Busiest package wire's serialization for hub->die flows of the given
    per-edge volumes, dies placed on slots_n."""
    seq = pm.sequential_fill(fab)
    rest = [s for s in seq.slots["die"] if s not in slots_n]
    pl = dataclasses.replace(seq, slots={**seq.slots,
                                         "die": list(slots_n) + rest}).verify(fab)
    m = ic.build(fab, "die", pl)
    load = {}
    for i, v in enumerate(edge_words):
        for r in m.path(ic.HUB, i):
            load[r] = load.get(r, 0.0) + v
    return (max(load.values()) / wc * CYC if load else 0.0), m, pl


def die_surplus_energy(m, edge_words):
    return sum(v * max(m.hops(ic.HUB, i) - 1.0, 0.0) * PJ
               for i, v in enumerate(edge_words))


def main():
    fab = fabric_mod.from_yaml("/home/workspace/models/fabric/mlx300_multidie.yaml")
    anch = json.load(open(os.path.join(OUT, "anchored_sweep.json")))
    probe = json.load(open(os.path.join(OUT, "multidie_placement.json")))
    full = json.load(open(os.path.join(OUT, "scale_2p7b_per_op.json")))
    wc_grs = GRS * WC_PER_GBPS

    # ================= tier M: probe op at the GRS anchor =================
    comp, vol, cyc = probe["compute_s"], probe["die_edge_words"], probe["cycle_s"]
    n = probe["op"]["dies"]
    print(f"=== tier M: one {n}-die operator at the measured D2D anchor "
          f"({GRS} GB/s) ===")
    tierM = []
    for label, slots_n in die_styles(fab, n):
        ser, m, _ = die_serial(fab, slots_n, [vol] * n, wc_grs)
        lat = max(comp, ser)
        e_sur = die_surplus_energy(m, [vol] * n)
        tierM.append({"label": label, "lat_s": lat, "surplus_J": e_sur})
        print(f"  {label:10} op latency {lat*1e3:8.2f} ms "
              f"({lat/comp:5.2f}x compute) | surplus energy {e_sur*1e3:.2f} mJ")

    # ================= tier L: full model =================
    n_layers = full["config"]["n_layers"]
    print(f"\n=== tier L: full {full['config']['name']} "
          f"({n_layers} layers) ===")
    STATIC = {"qkv_proj", "out_proj", "ffn1", "ffn2"}
    # The two conditions match the anchored sweep: with attention on chip the
    # K/V write (append-only programming, NOT a rewrite -- the rewrite
    # mechanism fires zero times in these runs) is charged; offloaded drops
    # the attention ops and their write entirely, on-chip side only.
    CONDS = [("prefill, attention on chip", "prefill", True),
             ("decode, attention offloaded", "decode", False)]
    tierL = {}
    for title, phase, on_chip in CONDS:
        recs = [r for r in full["phases"][phase]
                if on_chip or r["name"] in STATIC]
        wr = (lambda r: r["write_s"]) if on_chip else (lambda r: 0.0)
        base = sum(wr(r) + r["compute_s"] for r in recs) * n_layers
        e_tot = sum(r["energy_J"] for r in recs) * n_layers
        rows = []
        for noc_name, noc_g in NOC:
            for style, _ in die_styles(fab, 2):
                tot = 0.0
                e_sur = 0.0
                for r in recs:
                    ondie = r["ondie_serial_ref_s"] * REF_WC / (noc_g * WC_PER_GBPS)
                    d2d = 0.0
                    if r["die_flow_words"]:
                        nd = len(r["die_flow_words"])
                        slots_n = dict(die_styles(fab, nd))[style]
                        d2d, m, _ = die_serial(fab, slots_n,
                                               r["die_flow_words"], wc_grs)
                        e_sur += die_surplus_energy(m, r["die_flow_words"])
                    tot += wr(r) + max(r["compute_s"], ondie, d2d)
                rows.append({"noc": noc_name, "style": style,
                             "lat_s": tot * n_layers, "mult": tot * n_layers / base,
                             "surplus_J": e_sur * n_layers})
        tierL[title] = {"base_s": base, "energy_J": e_tot, "rows": rows}
        print(f"  {title}: no-network stack {base*1e3:.2f} ms, "
              f"energy {e_tot*1e3:.1f} mJ")
        for r in rows:
            print(f"    NoC {r['noc']:12} die-placement {r['style']:9} "
                  f"-> {r['lat_s']*1e3:9.2f} ms ({r['mult']:5.2f}x)"
                  f"  D2D surplus {r['surplus_J']*1e3:7.2f} mJ")

    # ================= figures =================
    # tier M figure
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4))
    g = np.geomspace(1, 200, 200)
    for label, slots_n in die_styles(fab, n):
        ser0, m, _ = die_serial(fab, slots_n, [vol] * n, WC_PER_GBPS)  # @1GB/s
        ys = [max(comp, ser0 / x) * 1e3 for x in g]
        axes[0].plot(g, ys, lw=1.7, label=label)
    axes[0].axvline(GRS, color="0.35", ls="--", lw=1.2)
    axes[0].text(GRS * 1.1, axes[0].get_ylim()[1] * 0.5,
                 "Simba GRS 12.5 GB/s\n(measured)", fontsize=8.5)
    axes[0].set_xscale("log"); axes[0].set_yscale("log")
    axes[0].set_xlabel("die-to-die link bandwidth (GB/s)")
    axes[0].set_ylabel("operator latency (ms)")
    axes[0].set_title(f"one {n}-die operator: latency vs D2D bandwidth",
                      fontsize=10)
    axes[0].grid(alpha=0.3, which="both"); axes[0].legend(fontsize=8.5)
    xs = np.arange(len(tierM))
    axes[1].bar(xs - 0.17, [t["lat_s"] * 1e3 for t in tierM], 0.32,
                color=TEAL, label="latency (ms)")
    ax2 = axes[1].twinx()
    ax2.bar(xs + 0.17, [t["surplus_J"] * 1e3 for t in tierM], 0.32,
            color=GOLD, label="extra D2D energy (mJ)")
    axes[1].set_xticks(xs)
    axes[1].set_xticklabels([t["label"] for t in tierM], fontsize=9)
    axes[1].set_ylabel("operator latency (ms) @ GRS anchor")
    ax2.set_ylabel("extra D2D energy (mJ)", color="#9a6b1a")
    axes[1].set_title("at the measured anchor: placement of the op's dies",
                      fontsize=10)
    axes[1].grid(alpha=0.25, axis="y")
    fig.suptitle("Tier M — a single operator that spans dies "
                 "(2.7B-class FFN probe)", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.9])
    p1 = os.path.join(OUT, "scale_tier_probe.png")
    fig.savefig(p1, dpi=130); plt.close(fig)
    print(f"PNG -> {p1}")

    # tier L figure
    fig, axes = plt.subplots(1, 2, figsize=(12.6, 4.6))
    styles = ["clustered", "row-fill", "spread"]
    colors = {"clustered": TEAL, "row-fill": SLATE, "spread": RED}
    for ax, (title, phase, on_chip) in zip(axes, CONDS):
        rows = tierL[title]["rows"]
        xs = np.arange(len(NOC))
        for k, st in enumerate(styles):
            vals = [next(r["mult"] for r in rows
                         if r["noc"] == nm and r["style"] == st)
                    for nm, _ in NOC]
            ax.bar(xs + (k - 1) * 0.26, vals, 0.24, color=colors[st], label=st)
            for i, v in enumerate(vals):
                if v > 1.02:
                    ax.text(i + (k - 1) * 0.26, v + 0.03, f"{v:.2f}",
                            ha="center", fontsize=7.5)
        ax.axhline(1.0, color="0.4", lw=1)
        ax.set_xticks(xs)
        ax.set_xticklabels([nm + " GB/s" for nm, _ in NOC], fontsize=9)
        ax.set_ylabel("stack latency / no-network stack")
        ax.set_title(f"{title} (D2D @ GRS anchor)", fontsize=10)
        ax.grid(alpha=0.25, axis="y")
        ax.set_ylim(0, max(r["mult"] for r in rows) * 1.22)
        ax.legend(fontsize=8, title="die placement", loc="lower right")
    fig.suptitle("Tier L — full 2.7B-class model: on-die anchor × die "
                 "placement", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.9])
    p2 = os.path.join(OUT, "scale_tier_2p7b.png")
    fig.savefig(p2, dpi=130); plt.close(fig)
    print(f"PNG -> {p2}")

    # ================= combined figure =================
    sA = anch["results"]["prefill, attention on chip"]["mult"]
    tS_lat = sA["mesh, glb corner"][0] / sA["mesh, glb centre"][0]   # Simba anchor
    d2 = json.load(open(os.path.join(OUT, "d2d_impact.json")))
    tot355 = json.load(open(os.path.join(OUT, "gpt2_system_totals_prefill.json")))
    tS_e = (max(r["surplus_uJ"] for r in d2["assignments"]) * 1e-6
            / tot355["scenarios"]["A_E"])
    tM_lat = max(t["lat_s"] for t in tierM) / min(t["lat_s"] for t in tierM)
    probe_E = 2.239e-3
    tM_e = max(t["surplus_J"] for t in tierM) / probe_E
    pref = tierL["prefill, attention on chip"]["rows"]
    mid = [r for r in pref if r["noc"] == "ESP 32"]
    tL_lat = max(r["lat_s"] for r in mid) / min(r["lat_s"] for r in mid)
    tL_e = (max(r["surplus_J"] for r in mid)
            / tierL["prefill, attention on chip"]["energy_J"])
    tiers = ["355M\n(every op fits\none die)", "2.7B-class\nsingle operator\n(4 dies)",
             "2.7B-class\nfull model\n(2-5 dies/op)"]
    lat = [tS_lat, tM_lat, tL_lat]
    en = [tS_e * 100, tM_e * 100, tL_e * 100]

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4))
    axes[0].bar(tiers, lat, 0.5, color=[SLATE, GOLD, RED])
    for i, v in enumerate(lat):
        axes[0].text(i, v * 1.02, f"{v:.2f}x", ha="center", fontsize=10,
                     fontweight="bold")
    axes[0].set_ylabel("worst / best layout latency (at the anchors)")
    axes[0].set_title("latency leverage of layout", fontsize=10)
    axes[0].grid(alpha=0.25, axis="y")
    axes[1].bar(tiers, en, 0.5, color=[SLATE, GOLD, RED])
    for i, v in enumerate(en):
        axes[1].text(i, v * 1.05, f"{v:.2f}%", ha="center", fontsize=10,
                     fontweight="bold")
    axes[1].set_yscale("log")
    axes[1].set_ylabel("worst-layout extra D2D energy\n(% of the TIER's OWN total: model / op / model; log)")
    axes[1].set_title("energy leverage of layout", fontsize=10)
    axes[1].grid(alpha=0.25, axis="y", which="both")
    fig.suptitle("Layout leverage grows with model scale — because operators "
                 "start to span dies", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.89])
    p3 = os.path.join(OUT, "scale_combined.png")
    fig.savefig(p3, dpi=130); plt.close(fig)
    print(f"PNG -> {p3}")

    with open(os.path.join(OUT, "scale_tiers.json"), "w") as f:
        json.dump({"tierM": tierM, "tierL": tierL,
                   "combined": {"tiers": tiers, "lat": lat, "energy_pct": en}},
                  f, indent=1, default=float)
    print("JSON -> scale_tiers.json")


if __name__ == "__main__":
    main()
