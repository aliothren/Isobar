"""Anchored sweep: the contention results at PUBLISHED NoC bandwidths.

Everything so far quoted multipliers at an example operating point. This
script replaces that with the three sourced anchors from analysis/ANCHORS.md
(Simba on-die 8.75 GB/s, ESP 32 GB/s, FlooNoC 80.6 GB/s -- all per link, one
direction) and reads the whole scheme x hub-position grid at each, for the
two conditions where the network can matter:

  * prefill, attention on chip  (compute-dominated -- the network races 249ms)
  * decode, attention offloaded (the serial K/V write left with the attention,
    so the network races ~1ms of compute -- the most exposed condition)

Method: per-op compute/write/serialization at the reference input come from
analysis/contention_system.json (real mapper runs); serialization scales
exactly as 1/bandwidth, so every anchor readout is closed-form. Note the
core-level ("region") allocation cannot enter this sweep honestly: those
links carry no bandwidth or price yet (FIXLIST O1) -- it stays a ranking.

Usage (container): python3 scripts/analyze_anchored_sweep.py
"""
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = "/home/workspace/analysis"
from scripts import anchors as an
from scripts import figstyle as fs
REF_WC = 16384.0                 # words/cycle the stored serializations used
CYC = an.CYCLE_S
WC_PER_GBPS = an.WC_PER_GBPS     # words/cycle per GB/s (word = 1 byte)

# Readout columns (O25): the digital-ecosystem anchors (index 0 = Simba, the
# low one -- consumers rely on that) and the two ends of the analog-reality
# band (estimated). Both paradigms, always; the registry is the only source.
COLS = an.columns(an.ONDIE)
ANCHORS = [(f"{lab}\n[{st}]" if p == an.DIGITAL else f"{lab}", g) for _, lab, g, p, st in COLS]
DIGITAL = an.digital(an.ONDIE)
from scripts import llm_workload as lw
STAYS = lw.stays_on_chip_under_offload     # scenario B: what remains on chip
N_LAYERS = 24
ORDER = ["star (private links)", "mesh, glb centre", "mesh, glb corner",
         "h-tree (k=4)", "bus (shared medium)"]
SHORT = ["star", "mesh\ncentre", "mesh\ncorner", "h-tree", "bus"]


def load():
    with open(os.path.join(OUT, "contention_system.json")) as f:
        return json.load(f)


def stack(per_op, wc, prefill_A, overlap="max", serial_of=None):
    """Whole-stack latency at bandwidth `wc` words/cycle.

    overlap="max": perfect compute/network overlap (the headline end);
    overlap="sum": zero overlap. The O7 bracket -- truth in between.
    serial_of: optional {op: serial_s at REF_WC} overriding the per-op
    serializations (used to re-read the anchors under another wire
    accounting, O22/O23)."""
    tot = 0.0
    for o in per_op:
        if not prefill_A and not STAYS(o["name"]):
            continue
        ser0 = o["serial_s"] if serial_of is None else serial_of[o["name"]]
        ser = ser0 * REF_WC / wc
        wr = o["write_s"] if prefill_A else 0.0
        core = max(o["compute_s"], ser) if overlap == "max" \
            else o["compute_s"] + ser
        tot += wr + core
    return tot * N_LAYERS


def main():
    d = load()
    conds = [("prefill, attention on chip", "prefill", True),
             ("decode, attention offloaded", "decode", False)]
    results = {}
    for title, phase, is_A in conds:
        per = d["phases"][phase]["per_op"]
        base = stack(next(iter(per.values())), 1e18, is_A)   # no-queue stack
        print(f"=== {title}: no-queue stack {base*1e3:.3f} ms ===")
        hdr = f"{'scheme / hub position':24}" + "".join(
            f"{a.splitlines()[0]:>18}" for a, _ in ANCHORS)
        print(hdr)
        rows, rows_sum = {}, {}
        for label in ORDER:
            cells, cells_sum = [], []
            for _, gbps in ANCHORS:
                wc = gbps * WC_PER_GBPS
                cells.append(stack(per[label], wc, is_A) / base)
                cells_sum.append(stack(per[label], wc, is_A, "sum") / base)
            rows[label] = cells
            rows_sum[label] = cells_sum
            print(f"  {label:22}" + "".join(
                f"  {c:>7.2f}..{cs:<5.2f}x" for c, cs in zip(cells, cells_sum)))
        results[title] = {"base_s": base, "mult": rows, "mult_sum": rows_sum}
        if not is_A:
            # O9: end-to-end -- the external unit's per-token chain (link out,
            # unit compute + K/V read of the whole context, link back) added as
            # a constant to every scheme; multipliers ease, absolutes grow
            from scripts import fabric as fabric_mod
            unit = fabric_mod.default().attention_unit
            c = lw.attention_unit_cost(lw.GptConfig(), 512, phase, unit,
                                       hops=lw.unit_link_hops())   # die placement -> hops to the attach point
            add = N_LAYERS * c["chain_s"]
            rows_e2e = {label: [(stack(per[label], g * WC_PER_GBPS, is_A) + add) / (base + add)
                                for _, g in ANCHORS] for label in ORDER}
            results[title]["mult_e2e"] = rows_e2e
            results[title]["base_e2e_s"] = base + add
            print(f"  -- end-to-end with the external unit (+{add*1e3:.3f} ms per token):")
            for label in ORDER:
                print(f"     {label:22}" + "".join(f"{c_:>9.2f}x" for c_ in rows_e2e[label]))
        # the same table under every wire accounting (O22/O23), if the
        # system JSON carries them -- the published comparison table
        acc = d["phases"][phase].get("accounting_variants", {})
        if acc:
            results[title]["by_accounting"] = {}
            print("  -- by wire accounting (perfect-overlap end):")
            for aname, arows in acc.items():
                tab = {}
                for label in ORDER:
                    ser = arows[label]["per_op_serial_s"]
                    tab[label] = [stack(per[label], g * WC_PER_GBPS, is_A,
                                        serial_of=ser) / base
                                  for _, g in ANCHORS]
                results[title]["by_accounting"][aname] = tab
                print(f"     {aname}")
                for label in ORDER:
                    print(f"       {label:22}" + "".join(
                        f"{c:>9.2f}x" for c in tab[label]))
        print()

    # ---------------- figure 1: anchored readouts, grouped bars
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 4.8))
    colors = ["#d1495b", "#e8a13c", "#2a9d8f", "#c9a227", "#7a5c00"]   # digital low/mid/high, analog band low/high
    for ax, (title, phase, is_A) in zip(axes, conds):
        rows = results[title]["mult"]
        x = np.arange(len(ORDER))
        rows_sum = results[title]["mult_sum"]
        for k, ((aname, _), c) in enumerate(zip(ANCHORS, colors)):
            vals = [rows[l][k] for l in ORDER]
            highs = [rows_sum[l][k] for l in ORDER]
            ax.bar(x + (k - 2) * 0.16, vals, 0.15, color=c,
                   label=aname.replace("\n", " "),
                   yerr=[[0.0] * len(vals),
                         [h - v for h, v in zip(highs, vals)]],
                   error_kw={"elinewidth": 1.0, "ecolor": "0.35",
                             "capsize": 2.0})
            for i, v in enumerate(vals):
                if v > 1.004:
                    ax.text(i + (k - 2) * 0.16, v + 0.03, f"{v:.2f}",
                            ha="center", fontsize=7.5)
            # tied bars across schemes are bracketed, never left to look alike by accident
            fs.annotate_bar_ties(ax, x + (k - 2) * 0.16, vals, skip_value=1.0, dy=0.06)
        ax.axhline(1.0, color="0.4", lw=1)
        ax.set_xticks(x); ax.set_xticklabels(SHORT, fontsize=9)
        ax.set_ylabel("whole-stack latency / no-queue stack")
        ax.set_title(title, fontsize=10.5)
        ax.grid(alpha=0.25, axis="y")
        ax.legend(fontsize=7.5)
    fig.suptitle("Contention at the anchor columns: digital anchors (upper bound) and the analog-reality band (estimated)\n"
                 "bar = perfect-overlap end, whisker = zero-overlap end of the O7 bracket; registry: scripts/anchors.py", fontsize=11)
    p1 = os.path.join(OUT, "anchored_sweep.png")
    fig.tight_layout(rect=[0, 0, 1, 0.9]); fig.savefig(p1, dpi=130)
    plt.close(fig)
    print(f"PNG -> {p1}")

    # ---------------- figure 2: sweep curves in GB/s with the anchor band
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.0))
    bw_wc = np.array([2.0 ** k for k in range(4, 22)])
    bw_gbps = bw_wc / WC_PER_GBPS
    for ax, (title, phase, is_A) in zip(axes, conds):
        per = d["phases"][phase]["per_op"]
        base = results[title]["base_s"]
        short_of = dict(zip(ORDER, [s.replace("\n", " ") for s in SHORT]))
        curves = [(label, [stack(per[label], wc, is_A) / base for wc in bw_wc]) for label in ORDER]
        for labels, ys in fs.group_identical(curves):
            ys_sum = [stack(per[labels[0]], wc, is_A, "sum") / base for wc in bw_wc]
            line, = ax.plot(bw_gbps, ys, "o-", ms=3, lw=1.5,
                            label=fs.merged_label([short_of[l] for l in labels]))
            ax.fill_between(bw_gbps, ys, ys_sum, color=line.get_color(),
                            alpha=0.12, lw=0)
            if len(labels) > 1:
                k = len(bw_gbps) // 3
                ax.annotate(f"{len(labels)} curves identical", (bw_gbps[k], ys[k]), textcoords="offset points",
                            xytext=(6, 7), fontsize=6.5, color=line.get_color())
        lo, hi = DIGITAL[0].gbps, DIGITAL[-1].gbps
        ax.axvspan(lo, hi, color="#2a9d8f", alpha=0.12)
        for a in DIGITAL:
            ax.axvline(a.gbps, color="#1c6b60", ls=":", lw=1.0)
        b = an.band(an.ONDIE)
        ax.axvspan(b.band[0], b.band[1], color="#c9a227", alpha=0.16, lw=0)
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlabel("per-link bandwidth (GB/s)")
        ax.set_ylabel("whole-stack latency / no-queue stack")
        ax.set_title(title, fontsize=10.5)
        ax.grid(alpha=0.3, which="both")
        ax.legend(fontsize=8)
    fig.suptitle("Where published chips land on our threshold curves -- green: digital anchors (upper bound); "
                 "gold: analog-reality band (estimated)", fontsize=11)
    p2 = os.path.join(OUT, "anchored_band.png")
    fig.tight_layout(rect=[0, 0, 1, 0.9]); fig.savefig(p2, dpi=130)
    plt.close(fig)
    print(f"PNG -> {p2}")

    with open(os.path.join(OUT, "anchored_sweep.json"), "w") as f:
        json.dump({"fabric": d.get("fabric"),
                   "anchors": [{"key": k, "label": lab, "gbps": g, "paradigm": p, "status": st}
                               for k, lab, g, p, st in COLS],
                   "anchors_gbps": {k: g for k, _, g, _, _ in COLS},
                   "wc_per_gbps": WC_PER_GBPS,
                   "results": {t: {"base_s": r["base_s"], "mult": r["mult"],
                                   "mult_sum": r["mult_sum"],
                                   "by_accounting": r.get("by_accounting", {}),
                                   "mult_e2e": r.get("mult_e2e", {}),
                                   "base_e2e_s": r.get("base_e2e_s")}
                               for t, r in results.items()}}, f, indent=1)
    print("JSON -> anchored_sweep.json")


if __name__ == "__main__":
    main()
