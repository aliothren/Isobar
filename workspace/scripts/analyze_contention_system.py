"""How much does contention move the SYSTEM number, not one op.

analyze_contention_impact / analyze_placement_tradeoff both measure ONE op
(ffn1). That answers "does the mechanism bite" but not "how big is it against
the denominator that gets quoted" -- the whole GPT-2 stack's prefill latency and
per-token decode latency. Those are the numbers in the report, so that is where
the effect has to be reported.

Method: run ONE transformer block per phase (the 24 blocks are structurally
identical, as in analyze_system_gpt2.py), keep every op's flows and latency
terms, then re-score the whole stack analytically under each scheme x bandwidth.
Per op:      latency = write + max(compute, serialization) + propagation
             (perfect-overlap end; the zero-overlap end write + compute +
             serialization + propagation is reported beside it -- the O7
             bracket. The truth lies between the two ends.)
Per stack:   sum over ops, x n_layers.

Two things this can show that a single op cannot:
  * the per-phase answer differs -- prefill is compute-dominated (contention can
    take over), decode is WRITE-dominated (a serial term contention cannot hide
    behind and cannot overlap with), so the same mechanism lands differently.
  * the system multiplier is diluted by the ops contention does NOT touch.

SCOPE: link bandwidth is a PLATFORM INPUT -- whoever runs the simulator supplies
their own chip's value, exactly like the fabric geometry and the interconnect
scheme. The shipped `mlx300.yaml` value is an example default, not a calibration
target. So the reported quantity is deliberately the system multiplier AS A
FUNCTION of bandwidth, plus the two thresholds a user can compare their own
number against: below which bandwidth does this move the stack by 1%, and by 2x.

Usage (container):
    python3 scripts/analyze_contention_system.py [S]
    python3 scripts/analyze_contention_system.py --replot   # figure only, from JSON
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

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
S = int(ARGS[0]) if ARGS else 512
# --shares: every op confined to its co-residency array share (O12, the
# feasible 48-die seating); this is the published 355M basis. Without the
# flag, ops get the whole die (exclusive-die reference basis).
SHARES = "--shares" in sys.argv
OUT = "/home/workspace/analysis"
BW_SWEEP = [float(2 ** k) for k in range(9, 24)]   # top covers the zero-overlap knees
BW_POINT = 16384.0

SCHEMES = [("star", {}, "star (private links)"),
           ("mesh", {"routing": "xy", "hub": "center"}, "mesh, glb centre"),
           ("mesh", {"routing": "xy", "hub": "corner"}, "mesh, glb corner"),
           ("h_tree", {"branching": 4}, "h-tree (k=4)"),
           ("bus", {"driver": "center"}, "bus (shared medium)")]


def variant(base, topology, params, bw):
    levels = []
    for lv in base.levels:
        if lv.name == "macro":
            lv = dataclasses.replace(
                lv, link=dataclasses.replace(lv.link, topology=topology,
                                             params=params,
                                             bandwidth_words_per_cycle=bw))
        levels.append(lv)
    return dataclasses.replace(base, name="variant", levels=levels).validate()


ELEMENTWISE = "--no-elementwise" not in sys.argv     # O24 terms on by default


def run_phase(phase, base):
    """One block: keep each op's flows + latency terms. The non-matmul
    operators (O24) enter as closed-form records: their latency is digital
    time in series with the matmuls, they use no network wire (serial 0),
    and their energy is glb passes + digital arithmetic."""
    cfg = lw.GptConfig()
    recs = []
    if ELEMENTWISE:
        for eo in lw.block_elementwise_ops(cfg, S=S, phase=phase):
            c = lw.elementwise_cost(eo, base.digital)
            print(f"  {phase:<7} {eo.name:<9} (elementwise, closed-form)", flush=True)
            recs.append({"name": eo.name, "kind": "elementwise", "flows": [],
                         "cycle_s": 1.0 / base.digital.clock_hz,
                         "compute_s": c["latency_s"], "write_s": 0.0,
                         "prop_s": 0.0, "energy_J": c["energy_J"]})
    for op in lw.block_ops(cfg, S=S, phase=phase):
        print(f"  {phase:<7} {op.name:<9} ({op.kind})", flush=True)
        r = lw.run_op(op, phase=phase,
                      share_plan=lw.SHARE_355M_48DIE[op.name] if SHARES
                      else None)
        flows, _, _, _ = cc.build_flows(r["output_dir"], verbose=False)
        recs.append({"name": op.name, "kind": op.kind, "flows": flows,
                     "cycle_s": r["result"].cycle_seconds,
                     "compute_s": r["compute_latency_s"],
                     "write_s": r["write_latency_s"],
                     "prop_s": r["dist_latency_s"]})
    return cfg.n_layers, recs


# wire-accounting variants (O22 direction split, O23 partial-sum width):
# (label, duplex, psum_bytes); None = the scheme's physical default
ACCOUNTING = [
    ("shared-direction, 8-bit partial sums (pre-O22/O23)", False, 1.0),
    ("direction-split only (O22)", None, 1.0),
    ("16-bit partial sums only (O23)", False, None),
    ("direction-split + 16-bit partial sums (current)", None, None),
]


def stack_latency(recs, n_layers, fab=None, duplex=None, psum_bytes=None):
    """Whole-stack latency and the per-op breakdown under one fabric.

    Returns (total_max, total_sum, per_op): total_max composes compute and
    network by max (perfect overlap -- the headline end), total_sum by sum
    (zero overlap). The O7 bracket: the truth lies between the two.
    duplex / psum_bytes select the wire accounting (None = current)."""
    per_op, total, total_sum = [], 0.0, 0.0
    for rec in recs:
        ser = 0.0
        if fab is not None:
            ser = cc.link_occupancy(rec["flows"], fab, rec["cycle_s"],
                                    placement_mod.sequential_fill(fab),
                                    duplex=duplex, psum_bytes=psum_bytes
                                    )["serialization_s"]
        lat = rec["write_s"] + max(rec["compute_s"], ser) + rec["prop_s"]
        lat_sum = rec["write_s"] + rec["compute_s"] + ser + rec["prop_s"]
        per_op.append({"name": rec["name"], "kind": rec["kind"],
                       "compute_s": rec["compute_s"], "write_s": rec["write_s"],
                       "serial_s": ser, "latency_s": lat,
                       "latency_sum_s": lat_sum,
                       "network_bound": ser > rec["compute_s"]})
        total += lat
        total_sum += lat_sum
    return total * n_layers, total_sum * n_layers, per_op


def main():
    base = fabric_mod.default()
    cfg = lw.GptConfig()
    print(f"GPT-2 ({cfg.name}, {cfg.n_layers} layers), S={S}: one block per "
          f"phase, then re-scored analytically\n")

    out = {"S": S, "n_layers": cfg.n_layers, "bw_sweep": BW_SWEEP,
           "operating_point_words_per_cycle": BW_POINT, "phases": {},
           "elementwise": ELEMENTWISE,
           "digital_unit": dataclasses.asdict(base.digital)}

    for phase in ("prefill", "decode"):
        n_layers, recs = run_phase(phase, base)
        stall_free, _, base_ops = stack_latency(recs, n_layers, None)
        print(f"\n=== {phase}: stack latency without contention = "
              f"{stall_free*1e3:.2f} ms ===")
        comp = sum(o["compute_s"] for o in base_ops if o["kind"] != "elementwise") * n_layers
        elw = sum(o["compute_s"] for o in base_ops if o["kind"] == "elementwise") * n_layers
        wr = sum(o["write_s"] for o in base_ops) * n_layers
        print(f"    compute {comp*1e3:8.2f} ms ({comp/stall_free:5.1%})   "
              f"write {wr*1e3:8.2f} ms ({wr/stall_free:5.1%})   "
              f"elementwise (digital) {elw*1e3:6.2f} ms ({elw/stall_free:5.1%})")

        rows, curves, curves_sum = [], {}, {}
        for topo, params, label in SCHEMES:
            tot, tot_sum, ops_at = stack_latency(
                recs, n_layers, variant(base, topo, params, BW_POINT))
            nb = [o["name"] for o in ops_at if o["network_bound"]]
            rows.append({"scheme": topo, "label": label, "latency_s": tot,
                         "mult": tot / stall_free,
                         "latency_sum_s": tot_sum,
                         "mult_sum": tot_sum / stall_free,
                         "network_bound_ops": nb, "per_op": ops_at})
            print(f"    {label:22} {tot*1e3:9.2f} ms  {tot/stall_free:6.2f}x"
                  f" .. {tot_sum/stall_free:5.2f}x"
                  f"   network-bound ops: {', '.join(nb) or 'none'}")
            pair = [stack_latency(recs, n_layers,
                                  variant(base, topo, params, bw))[:2]
                    for bw in BW_SWEEP]
            curves[label] = [a / stall_free for a, _ in pair]
            curves_sum[label] = [b / stall_free for _, b in pair]

        # the two bandwidths DR-2 has to be compared against, per scheme;
        # each with both bracket ends (max-end first -- the headline)
        def first_bw(ys, target):
            hits = [bw for bw, y in zip(BW_SWEEP, ys) if y >= target]
            return max(hits) if hits else None
        thr = {}
        for label, ys in curves.items():
            ys_sum = curves_sum[label]
            thr[label] = {"bw_1pct": first_bw(ys, 1.01),
                          "bw_2x": first_bw(ys, 2.0),
                          "bw_1pct_sum": first_bw(ys_sum, 1.01),
                          "bw_2x_sum": first_bw(ys_sum, 2.0)}
            fmt = lambda b: f"{b:,.0f}" if b else "never"
            t = thr[label]
            print(f"      {label:22} +1% of the stack below "
                  f"{fmt(t['bw_1pct']):>9} w/c (zero-overlap "
                  f"{fmt(t['bw_1pct_sum'])}) | 2x below "
                  f"{fmt(t['bw_2x']):>9} w/c (zero-overlap "
                  f"{fmt(t['bw_2x_sum'])})")

        # the four wire accountings side by side, at the operating point
        # (per-op serializations kept so the anchors can be re-read)
        acc = {}
        print("\n    wire accounting (O22/O23) at the operating point, "
              "perfect-overlap end:")
        for alabel, dup, psb in ACCOUNTING:
            acc[alabel] = {}
            cells = []
            for topo, params, label in SCHEMES:
                tot, tot_sum, ops_at = stack_latency(
                    recs, n_layers, variant(base, topo, params, BW_POINT),
                    duplex=dup, psum_bytes=psb)
                acc[alabel][label] = {
                    "mult": tot / stall_free, "mult_sum": tot_sum / stall_free,
                    "per_op_serial_s": {o["name"]: o["serial_s"] for o in ops_at}}
                cells.append(f"{tot/stall_free:5.2f}x")
            print(f"      {alabel:52} " + "  ".join(cells))
        print("      (columns: " + ", ".join(l for _, _, l in SCHEMES) + ")")

        out["phases"][phase] = {
            "stall_free_s": stall_free, "compute_s": comp, "write_s": wr,
            "elementwise_s": elw,
            "rows": [{k: v for k, v in r.items() if k != "per_op"} for r in rows],
            "per_op": {r["label"]: r["per_op"] for r in rows},
            "curves": curves, "curves_sum": curves_sum, "thresholds": thr,
            "accounting_variants": acc}
        print()

    make_figure(out, cfg.name, cfg.n_layers, S)

    out["basis"] = "co-residency shares (48-die seating)" if SHARES \
        else "exclusive die per op"
    out["wire_accounting"] = ("direction-split full-duplex links (bus shared); "
                              f"partial sums {base.psum_word_bytes:g} words")
    with open(os.path.join(OUT, "contention_system.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("JSON -> contention_system.json")


def make_figure(out, name, n_layers, S_):
    fig, axes = plt.subplots(1, 2, figsize=(12.2, 5.0), sharey=True)
    BW = out["bw_sweep"]
    for ax, phase in zip(axes, ("prefill", "decode")):
        d = out["phases"][phase]
        sums = d.get("curves_sum", {})
        for label, ys in d["curves"].items():
            line, = ax.plot(BW, ys, "o-", ms=3.5, lw=1.6, label=label)
            if label in sums:            # O7 bracket: max..sum overlap band
                ax.fill_between(BW, ys, sums[label],
                                color=line.get_color(), alpha=0.13, lw=0)
        ax.axvline(BW_POINT, color="0.55", ls=":", lw=1.2)
        ax.axhline(1.01, color="#b33f2b", ls="--", lw=1.0)
        ax.set_xscale("log", base=2); ax.set_yscale("log")
        ax.set_xlabel("macro link bandwidth (words / cycle)  --  platform input")
        dom = "compute" if d["compute_s"] > d["write_s"] else "write"
        ax.set_title(f"{phase}  --  stall-free {d['stall_free_s']*1e3:.1f} ms, "
                     f"{dom}-dominated", fontsize=10)
        ax.grid(alpha=0.3, which="both")
    axes[0].set_ylabel("WHOLE-STACK latency / stall-free")
    axes[0].legend(fontsize=8.5, loc="upper right")
    fig.suptitle("Contention at the system denominator, not one op\n"
                 f"GPT-2 {name} x{n_layers} blocks, S={S_}; "
                 "red line = +1% of the stack; dotted = 16,384 w/c; "
                 "shaded band = O7 overlap bracket (line = perfect overlap, "
                 "top = zero overlap)", fontsize=11)
    p = os.path.join(OUT, "contention_system.png")
    fig.tight_layout(rect=[0, 0, 1, 0.88]); fig.savefig(p, dpi=130); plt.close(fig)
    print(f"PNG -> {p}")


if __name__ == "__main__":
    if "--replot" in sys.argv:
        with open(os.path.join(OUT, "contention_system.json")) as f:
            saved = json.load(f)
        make_figure(saved, lw.GptConfig().name, saved["n_layers"], saved["S"])
    else:
        main()
