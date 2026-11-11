"""The intra-die instance of Fig. 1(a): one transformer block of the
GPT-2-medium-class model (24 layers) run through CiMLoop per phase, each
operator confined to its co-residency share of the die (--shares, the
48-die seating) or given the whole die, with every operator's on-die flows
and latency terms kept; the whole stack is then re-scored analytically
for five on-die interconnect schemes (star, mesh with the global buffer at
the centre or a corner, H-tree, bus) over the macro-link bandwidth.

Per operator: latency = write + max(compute, serialization) + propagation
(perfect overlap; the zero-overlap sum is stored beside it). Per stack:
the sum over the operators times the layer count. Element-wise operators
(norms, activation, residual) enter as closed-form digital records that use
no network wire.

    python3 scripts/measure_intradie_instance.py --shares      (container; CiMLoop)
      -> results/reference/intradie_instance.json
"""
import dataclasses
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.crossbar_comm as cc
from scripts import fabric as fabric_mod
from scripts import llm_workload as lw
from scripts import paths
from scripts import placement as placement_mod

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
S = int(ARGS[0]) if ARGS else 512
# --shares: every operator confined to its co-residency array share (the
# 48-die seating of the GPT-2-medium-class block; the basis of Fig. 1(a)).
# Without the flag, every operator gets the whole die.
SHARES = "--shares" in sys.argv
OUT = paths.REFERENCE
BW_SWEEP = [float(2 ** k) for k in range(9, 24)]   # macro-link words per cycle; the top covers the zero-overlap knees
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


ELEMENTWISE = "--no-elementwise" not in sys.argv     # element-wise operators on by default


def run_phase(phase, base):
    """One block: keep each operator's flows and latency terms. The
    element-wise operators enter as closed-form records: their latency is
    digital time in series with the matrix operators, they use no network
    wire (serialization 0), and their energy is global-buffer passes plus
    digital arithmetic."""
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


def stack_latency(recs, n_layers, fab=None, duplex=None, psum_bytes=None):
    """Whole-stack latency and the per-op breakdown under one fabric.

    Returns (total_max, total_sum, per_op): total_max composes compute and
    network by max (perfect overlap), total_sum by sum (zero overlap).
    duplex / psum_bytes override the fabric's wire accounting (None = the
    fabric's own: direction-split links, 16-bit partial sums)."""
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

        # per scheme: the bandwidth below which the stack grows by 1% and by 2x,
        # at both overlap ends
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

        out["phases"][phase] = {
            "stall_free_s": stall_free, "compute_s": comp, "write_s": wr,
            "elementwise_s": elw,
            "rows": [{k: v for k, v in r.items() if k != "per_op"} for r in rows],
            "per_op": {r["label"]: r["per_op"] for r in rows},
            "curves": curves, "curves_sum": curves_sum, "thresholds": thr}
        print()

    out["basis"] = "co-residency shares (48-die seating)" if SHARES \
        else "exclusive die per op"
    out["wire_accounting"] = ("direction-split full-duplex links (bus shared); "
                              f"partial sums {base.psum_word_bytes:g} words")
    with open(os.path.join(paths.ensure(OUT), "intradie_instance.json"), "w") as f:
        out["fabric"] = fabric_mod.provenance(fabric_mod.default())
        json.dump(out, f, indent=1)
    print("JSON ->", os.path.join(OUT, "intradie_instance.json"))


if __name__ == "__main__":
    main()
