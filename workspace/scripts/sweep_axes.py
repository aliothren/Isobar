"""Per-axis bandwidth sweeps (O25): the data base of the phase diagram.

Every axis is a closed-form re-scoring of STORED per-operator components
(compute, K/V write, busiest-wire serialization at the reference bandwidth;
serialization scales exactly as 1/bandwidth) -- no mapper runs. Each axis is
swept from far below to far above every published anchor on a log grid
(8 points per decade, plus the exact anchor values and the 2^k words/cycle
points so every pinned number stays reproducible), at BOTH ends of the O7
overlap bracket, and read out at both paradigms' columns (the digital
anchors and the two ends of the analog-reality band, scripts/anchors.py).

Serialization is scored in GB/s form (C31): the stored busiest-wire seconds
were computed at REF_WC = 16,384 words/cycle = REF_GBPS = 11.310 GB/s of the
NeuRRAM device, and scale as ser_ref * REF_GBPS / g -- the seconds on a link
of a fixed GB/s are a GB/s property, independent of the device (group 26),
which is what lets the device axis cross the bandwidth axes with no mapper
rerun.

Axes (A-H at the NeuRRAM tier; the plane sweeps the device):
  A   on-die link bandwidth (T2, macro level, per direction); 5 schemes x 4
      conditions. Every condition reports WHICH OPERATOR sets the knee.
  B1  die-to-die link bandwidth, 355M on the feasible 48-die chain:
      single-pass and pipelined x snake / sequential / adversarial (mesh) +
      the shared bus interposer x attention on chip / offloaded.
  B2  die-to-die link bandwidth, the 2.7B-class block as a chain of die-sets
      (O13): 3 seatings x 2 conditions, CROSSED with axis A (the only case
      where both networks are live) -> the on-die x D2D map.
  B3  die-to-die link bandwidth, the 4-die probe operator (tier M).
  C   the die<->unit link of the offloaded attention (end-to-end chain).
  H   partial-sum width on the on-die wires (1 vs 2 words, from the stored
      wire accountings; DR-7).
  plane  the (t_MVM x bandwidth) plane (O17b): device grid 0.05-100 us +
      the silicon marks (anchors.device_marks(); four since C36), crossed with A, B1,
      B3 and C (B2 at the marks only). The metric is the BUSIEST OPERATOR's
      network / compute ratio r(g, t) -- the whole-stack multiplier is NOT
      the plane's metric because the K/V write and the digital unit do not
      scale with the device (the fixed-term decomposition figure). r = 1 is
      the closed form g = REF_GBPS * (ser_ref / mm_ref) * (t_ref / t), a
      slope -1 line in log-log; the swept thresholds must land on it.

Fixed in every sweep (printed in the header): S = 512, batch 1, 24 / 32
layers, co-residency basis, v5 value units, direction-split full-duplex wires,
bus as a shared medium, 16-bit partial sums (except H), the NeuRRAM write
model, the digital unit (64 lanes @ 1 GHz), the generic attention unit, xy
routing with the hub centred; energies are not swept.

Outputs: analysis/phase_sweep.json, one figure per axis
(analysis/sweep_axis_*.png) and the plane's three
(analysis/device_plane.png, device_plane_collapse.png,
device_fixed_terms.png).

Usage (container): python3 scripts/sweep_axes.py [ondie d2d_355m d2d_2p7b d2d_probe unit_link psum plane]
"""
import dataclasses
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
import numpy as np

from scripts import anchors as an
from scripts import figstyle as fs
from scripts import fabric as fabric_mod
from scripts import llm_workload as lw
from scripts import placement as pm
import scripts.crossbar_comm as cc
from scripts.analyze_d2d import MULTI, UNITS, UCFG, S as S355, WORDS, assignments, with_link
from scripts.analyze_scale_tiers import die_bw, die_styles, occupancy_on, probe_flows

OUT = "/home/workspace/analysis"
MULTI24 = "/home/workspace/models/fabric/mlx300_multidie.yaml"
CYC = an.CYCLE_S
REF_WC = 16384.0                 # words/cycle the stored serializations used
REF_GBPS = an.gbps_of(REF_WC)    # = 11.310 GB/s: the same reference in the device-free unit
T_REF = an.T_MVM_S               # 10.14 us: the device the stored compute was scored at
N_LAYERS = 24
STAYS = lw.stays_on_chip_under_offload
ORDER = ["star (private links)", "mesh, glb centre", "mesh, glb corner",
         "h-tree (k=4)", "bus (shared medium)"]
SHORT = {"star (private links)": "star", "mesh, glb centre": "mesh centre",
         "mesh, glb corner": "mesh corner", "h-tree (k=4)": "h-tree",
         "bus (shared medium)": "bus"}
COLOR = {"star (private links)": "#2a9d8f", "mesh, glb centre": "#8fa8bf",
         "mesh, glb corner": "#d1495b", "h-tree (k=4)": "#e8a13c",
         "bus (shared medium)": "#7b2d8b",
         "snake": "#2a9d8f", "sequential rows": "#8fa8bf",
         "far pairs (adversarial)": "#d1495b", "bus (shared interposer)": "#7b2d8b",
         "clustered": "#2a9d8f", "row-fill": "#8fa8bf", "spread": "#d1495b"}
PER_DECADE = 8
FIXED = {"S": 512, "batch": 1, "layers": "24 (355M) / 32 (2.7B-class)",
         "basis": "co-residency (C14), value units v5 (C25)",
         "wires": "direction-split full-duplex point-to-point schemes; bus = one shared medium (C17)",
         "partial_sums": "16 bits (2 words) except axis H",
         "write_model": "NeuRRAM-class SET pulses, row-serial (DR-5)",
         "digital_unit": "64 lanes @ 1 GHz (DR-8)",
         "attention_unit": "generic public figures (DR-9)",
         "routing": "xy, hub centred",
         "device": "NeuRRAM tier (10.14 us per MVM row) for axes A-H; the plane sweeps t_MVM 0.05-100 us (O17b)",
         "device_axis_fixed": "t_MVM scales the MVM read path ONLY -- the K/V write (SET pulses, DR-5), "
                              "the digital unit (1 GHz, DR-8), the attention unit (DR-9) and every link's "
                              "GB/s stay fixed; a faster real device may also write faster, but that is "
                              "another device parameter, not this axis",
         "energy": "not swept", "cycle_s": CYC, "ref_words_per_cycle": REF_WC,
         "ref_gbps": REF_GBPS, "t_ref_s": T_REF}


# ----------------------------------------------------------------- helpers
def ser_at(ser_ref_s, g, ref_gbps=REF_GBPS):
    """Busiest-wire seconds at bandwidth g GB/s, from the seconds stored at
    ref_gbps. A GB/s property, independent of the device (group 26): this is
    the device-free scoring every axis and the plane share (C31)."""
    return ser_ref_s * ref_gbps / g


def log_grid(lo, hi, level=None, per_decade=PER_DECADE):
    """Log-uniform grid in GB/s plus the level's anchor values and the 2^k
    words/cycle points inside [lo, hi]."""
    n = int(round(np.log10(hi / lo) * per_decade)) + 1
    pts = {round(float(x), 12) for x in np.geomspace(lo, hi, n)}
    if level:
        for a in an.ANCHORS:
            if a.level == level:
                pts |= {round(v, 12) for v in a.values if lo <= v <= hi}
    k = 0
    while True:
        g = an.gbps_of(2.0 ** k)
        if g > hi:
            break
        if g >= lo:
            pts.add(round(g, 12))
        k += 1
    return sorted(pts)


def threshold(f, level, lo, hi, iters=60):
    """Largest bandwidth (GB/s) at which the non-increasing f(bw) >= level.
    None = never inside [lo, hi]; hi = still above `level` at the top."""
    if f(lo) < level:
        return None
    if f(hi) >= level:
        return hi
    a, b = np.log10(lo), np.log10(hi)
    for _ in range(iters):
        m = 0.5 * (a + b)
        if f(10.0 ** m) >= level:
            a = m
        else:
            b = m
    return float(10.0 ** a)


def fmt_thr(x, hi=None):
    if x is None:
        return "never"
    if hi is not None and x >= hi:
        return f">={hi:g}"
    return f"{x:.3g}"


def mark(ax, level, band_text=True):
    """Digital anchors as vertical lines, the analog-reality band shaded."""
    for a in an.digital(level):
        ax.axvline(a.gbps, color="0.25", ls=":", lw=1.0)
        ax.text(a.gbps, 0.98, a.label.split()[0], rotation=90, fontsize=7,
                ha="right", va="top", transform=ax.get_xaxis_transform(), color="0.25")
    b = an.band(level)
    ax.axvspan(b.band[0], b.band[1], color="#c9a227", alpha=0.16, lw=0)
    if band_text:
        ax.text(np.sqrt(b.band[0] * b.band[1]), 0.03, "analog-reality\ntier (estimated)",
                fontsize=7, ha="center", va="bottom", transform=ax.get_xaxis_transform(),
                color="#7a5c00")
    try:
        sec = ax.secondary_xaxis("top", functions=(an.words_per_cycle, an.gbps_of))
        sec.set_xlabel("words per device cycle", fontsize=7.5)
        sec.tick_params(labelsize=7)
    except Exception:
        pass


def col_readout(fn, level, **kw):
    """fn(gbps) -> value at every readout column of the level."""
    return {key: fn(gb) for key, _, gb, _, _ in an.columns(level)}


def print_columns(level, rows, title, unit="x"):
    cols = an.columns(level)
    print(f"\n  {title}")
    print(f"  {'':28}" + "".join(f"{lab:>20}" for _, lab, _, _, _ in cols))
    for name, cells in rows:
        print(f"  {name:28}" + "".join(f"{c:>20}" for c in cells))


# ----------------------------------------------------------------- axis A
def axis_ondie(sysd):
    grid = log_grid(1e-3, 1e4, an.ONDIE)
    lo, hi = grid[0], grid[-1]
    conds = [("prefill, attention on chip", "prefill", True),
             ("prefill, attention offloaded", "prefill", False),
             ("decode, attention on chip", "decode", True),
             ("decode, attention offloaded", "decode", False)]
    res = {"grid_gbps": grid, "grid_wc": [an.words_per_cycle(g) for g in grid],
           "conditions": {}}
    print("\n=== axis A: on-die link bandwidth (T2, macro level, per direction) ===")
    for title, phase, on_chip in conds:
        per_all = sysd["phases"][phase]["per_op"]

        def ops(label):
            return [o for o in per_all[label] if on_chip or STAYS(o["name"])]

        def stack(label, g, overlap="max"):
            tot = 0.0
            for o in ops(label):
                ser = ser_at(o["serial_s"], g)
                wr = o["write_s"] if on_chip else 0.0
                tot += wr + (max(o["compute_s"], ser) if overlap == "max"
                             else o["compute_s"] + ser)
            return tot * N_LAYERS

        def ratio(label, g):
            return max((ser_at(o["serial_s"], g) / o["compute_s"]
                        for o in ops(label) if o["serial_s"] > 0 and o["compute_s"] > 0),
                       default=0.0)

        base = sum((o["write_s"] if on_chip else 0.0) + o["compute_s"]
                   for o in ops(ORDER[0])) * N_LAYERS
        schemes = {}
        print(f"\n  -- {title}: no-network stack {base*1e3:.2f} ms")
        print(f"  {'scheme':22} {'knee operator':14} {'ratio@ref':>10} {'1% (max)':>10} "
              f"{'2x (max)':>10} {'1% (sum)':>10} {'net=comp':>10}")
        for label in ORDER:
            knee = max((o for o in ops(label) if o["compute_s"] > 0),
                       key=lambda o: o["serial_s"] / o["compute_s"])
            thr = {"max_1pct": threshold(lambda g: stack(label, g) / base, 1.01, lo, hi),
                   "max_2x": threshold(lambda g: stack(label, g) / base, 2.0, lo, hi),
                   "sum_1pct": threshold(lambda g: stack(label, g, "sum") / base, 1.01, lo, hi),
                   "sum_2x": threshold(lambda g: stack(label, g, "sum") / base, 2.0, lo, hi),
                   "busiest_op_net_eq_comp": threshold(lambda g: ratio(label, g), 1.0, lo, hi)}
            schemes[label] = {
                "mult_max": [stack(label, g) / base for g in grid],
                "mult_sum": [stack(label, g, "sum") / base for g in grid],
                "busiest_ratio": [ratio(label, g) for g in grid],
                "knee_op": knee["name"],
                "knee_ratio_at_ref": knee["serial_s"] / knee["compute_s"],
                "thresholds_gbps": thr,
                "columns": {key: {"max": stack(label, gb) / base, "sum": stack(label, gb, "sum") / base,
                                  "busiest_ratio": ratio(label, gb)}
                            for key, _, gb, _, _ in an.columns(an.ONDIE)}}
            print(f"  {SHORT[label]:22} {knee['name']:14} {knee['serial_s']/knee['compute_s']:>10.3f} "
                  f"{fmt_thr(thr['max_1pct'], hi):>10} {fmt_thr(thr['max_2x'], hi):>10} "
                  f"{fmt_thr(thr['sum_1pct'], hi):>10} {fmt_thr(thr['busiest_op_net_eq_comp'], hi):>10}")
        print_columns(an.ONDIE, [(SHORT[l], [f"{schemes[l]['columns'][k]['max']:.2f}..{schemes[l]['columns'][k]['sum']:.2f}x"
                                            for k, *_ in an.columns(an.ONDIE)]) for l in ORDER],
                      "whole-stack multiplier at the columns (perfect-overlap .. zero-overlap):")
        res["conditions"][title] = {"base_s": base, "schemes": schemes}
    return res


def fig_ondie(res):
    fig, axes = plt.subplots(2, 2, figsize=(13.2, 8.6))
    grid = res["grid_gbps"]
    for ax, (title, cond) in zip(axes.flat, res["conditions"].items()):
        sch = cond["schemes"]
        # identical series are merged, never stacked silently (figstyle rule)
        for labels, ys in fs.group_identical([(l, sch[l]["mult_max"]) for l in ORDER]):
            lab = " = ".join(SHORT[l] for l in labels) + (f" ({fs.TIE_NOTE})" if len(labels) > 1 else "")
            line, = ax.plot(grid, ys, "-", color=COLOR[labels[0]], lw=1.7,
                            label=f"{lab}; knee: {sch[labels[0]]['knee_op']}")
            ax.plot(grid, sch[labels[0]]["mult_sum"], "--", color=COLOR[labels[0]], lw=0.9, alpha=0.8)
            if len(labels) > 1:
                k = len(grid) // 6
                ax.annotate(f"{len(labels)} curves identical", (grid[k], ys[k]), textcoords="offset points",
                            xytext=(6, 7), fontsize=6.5, color=line.get_color())
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlim(grid[0], grid[-1])
        ax.set_ylim(0.95, max(3.0, max(cond["schemes"][l]["mult_sum"][0] for l in ORDER) * 1.2))
        mark(ax, an.ONDIE)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("per-link bandwidth (GB/s)")
        ax.set_ylabel("whole-stack latency / no-network stack")
        ax.grid(alpha=0.3, which="both")
        ax.legend(fontsize=7.5, loc="upper right")
    fig.suptitle("Axis A -- on-die link bandwidth, 355M, NeuRRAM tier\n"
                 "solid = perfect-overlap end, dashed = zero-overlap end; dotted = digital anchors "
                 "(upper bound), shaded = analog-reality band (estimated)", fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    p = os.path.join(OUT, "sweep_axis_ondie.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    print(f"PNG -> {p}")


# ----------------------------------------------------------------- axis B1
def axis_d2d_355m(sysd):
    grid = log_grid(5e-4, 1e3, an.D2D)
    lo, hi = grid[0], grid[-1]
    base = fabric_mod.from_yaml(MULTI)
    pre = sysd["phases"]["prefill"]
    per_star = next(iter(pre["per_op"].values()))
    stage_A, stage_B = lw.half_layer_stages(per_star)
    sf_A, comp_A = pre["stall_free_s"], pre["compute_s"]
    sf_B = N_LAYERS * sum(o["compute_s"] for o in per_star if STAYS(o["name"]))
    cfg = lw.GptConfig()
    REF = 256.0
    variants = [(lbl, "mesh", {"routing": "xy", "hub": "center"}, asg)
                for lbl, asg in assignments(base)]
    variants.append(("bus (shared interposer)", "bus", {"driver": "center"}, list(range(UNITS))))
    conds = [("prefill, attention on chip", sf_A, comp_A, stage_A, False),
             ("prefill, attention offloaded", sf_B, sf_B, stage_B, True)]
    res = {"grid_gbps": grid, "grid_wc": [an.words_per_cycle(g) for g in grid],
           "n_units": UNITS, "conditions": {}}
    print("\n=== axis B1: die-to-die link bandwidth, 355M on the 48-die chain ===")
    for title, sf, comp, stage, offl in conds:
        out = {}
        print(f"\n  -- {title}: stall-free stack {sf*1e3:.2f} ms, stage {stage*1e3:.2f} ms")
        print(f"  {'assignment':26} {'busiest (boundaries)':>22} {'pipe 1%':>9} {'pipe 2x':>9} "
              f"{'single 1%':>10} {'single 2x':>10}")
        for lbl, topo, params, asg in variants:
            fab = with_link(base, topo, params, REF)
            pl = pm.sequential_fill(fab)
            d = lw.die_to_die_activation(UCFG, S355, "prefill", fabric=fab, assignment=asg)
            flows = list(d["flows"])
            if offl:
                flows += lw.offload_flows(cfg, S355, "prefill",
                                          lw.attention_dies_of_chain(cfg.n_layers, asg))
            note = ""
            try:
                occ = cc.link_occupancy(flows, fab, CYC, pl)
                ser_ref, busiest = occ["serialization_s"], occ["bottleneck"]["volume"] / WORDS
            except Exception as e:                      # the bus scheme and hub-bound streams
                busiest = (UNITS - 1) + (4 * cfg.n_layers if offl else 0)
                ser_ref = busiest * WORDS / REF * CYC
                note = f"analytic ({type(e).__name__})"

            def ser(g, ser_ref=ser_ref):
                return ser_at(ser_ref, g, an.gbps_of(REF))

            single = lambda g, ov="max": ((sf + max(0.0, ser(g) - comp)) if ov == "max" else sf + ser(g)) / sf
            pipe = lambda g, ov="max": (max(stage, ser(g)) if ov == "max" else stage + ser(g)) / stage
            thr = {"pipe_1pct": threshold(pipe, 1.01, lo, hi), "pipe_2x": threshold(pipe, 2.0, lo, hi),
                   "pipe_1pct_sum": threshold(lambda g: pipe(g, "sum"), 1.01, lo, hi),
                   "single_1pct": threshold(single, 1.01, lo, hi), "single_2x": threshold(single, 2.0, lo, hi)}
            out[lbl] = {"busiest_boundaries": busiest, "serial_ref_s": ser_ref, "ref_wc": REF, "note": note,
                        "single_max": [single(g) for g in grid], "single_sum": [single(g, "sum") for g in grid],
                        "pipe_max": [pipe(g) for g in grid], "pipe_sum": [pipe(g, "sum") for g in grid],
                        "thresholds_gbps": thr,
                        "columns": {key: {"single": single(gb), "single_sum": single(gb, "sum"),
                                          "pipe": pipe(gb), "pipe_sum": pipe(gb, "sum")}
                                    for key, _, gb, _, _ in an.columns(an.D2D)}}
            print(f"  {lbl:26} {busiest:>22.1f} {fmt_thr(thr['pipe_1pct'], hi):>9} {fmt_thr(thr['pipe_2x'], hi):>9} "
                  f"{fmt_thr(thr['single_1pct'], hi):>10} {fmt_thr(thr['single_2x'], hi):>10}  {note}")
        print_columns(an.D2D, [(lbl, [f"{out[lbl]['columns'][k]['pipe']:.2f}..{out[lbl]['columns'][k]['pipe_sum']:.2f}x"
                                     for k, *_ in an.columns(an.D2D)]) for lbl, *_ in variants],
                      "pipelined beat / compute-bound beat at the columns:")
        print_columns(an.D2D, [(lbl, [f"{out[lbl]['columns'][k]['single']:.2f}..{out[lbl]['columns'][k]['single_sum']:.2f}x"
                                     for k, *_ in an.columns(an.D2D)]) for lbl, *_ in variants],
                      "single-pass stack multiplier at the columns:")
        res["conditions"][title] = {"stall_free_s": sf, "compute_s": comp, "stage_s": stage,
                                    "variants": out}
    return res


def fig_d2d_355m(res):
    grid = res["grid_gbps"]
    fig, axes = plt.subplots(2, 2, figsize=(13.2, 8.6))
    for r, (title, cond) in enumerate(res["conditions"].items()):
        for c, (mode, key) in enumerate((("single pass", "single"), ("pipelined", "pipe"))):
            ax = axes[r, c]
            var = cond["variants"]
            for labels, ys in fs.group_identical([(l, var[l][key + "_max"]) for l in var]):
                line, = ax.plot(grid, ys, "-", color=COLOR[labels[0]], lw=1.7, label=fs.merged_label(labels))
                ax.plot(grid, var[labels[0]][key + "_sum"], "--", color=COLOR[labels[0]], lw=0.9, alpha=0.8)
                if len(labels) > 1:
                    k = len(grid) // 6
                    ax.annotate(f"{len(labels)} curves identical", (grid[k], ys[k]), textcoords="offset points",
                                xytext=(6, 7), fontsize=6.5, color=line.get_color())
            ax.set_xscale("log"); ax.set_yscale("log")
            ax.set_xlim(grid[0], grid[-1])
            mark(ax, an.D2D)
            ax.set_title(f"{title} -- {mode}", fontsize=9.5)
            ax.set_xlabel("die-to-die link bandwidth per direction (GB/s)")
            ax.set_ylabel("stack / stall-free" if key == "single" else "beat / compute-bound beat")
            ax.grid(alpha=0.3, which="both")
            ax.legend(fontsize=7.5, loc="upper right")
    fig.suptitle("Axis B1 -- die-to-die link bandwidth, 355M on the feasible 48-die chain, NeuRRAM tier\n"
                 "solid = perfect-overlap, dashed = zero-overlap; dotted = GRS (digital), "
                 "shaded = analog-reality band (estimated)", fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    p = os.path.join(OUT, "sweep_axis_d2d_355m.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    print(f"PNG -> {p}")


# ----------------------------------------------------------------- axis B2
def axis_d2d_2p7b(full):
    fab = fabric_mod.from_yaml(MULTI24)
    grid = log_grid(5e-4, 1e3, an.D2D)
    ngrid = log_grid(1e-3, 1e4, an.ONDIE)
    lo, hi = grid[0], grid[-1]
    n_layers = full["config"]["n_layers"]
    S27 = full["config"].get("S", 512)
    c27 = lw.GptConfig(d_model=full["config"]["d_model"], n_heads=full["config"]["n_heads"],
                       d_ff=full["config"]["d_ff"], n_layers=n_layers, name=full["config"]["name"])
    conds = [("prefill, attention on chip", "prefill", True),
             ("decode, attention offloaded", "decode", False)]
    STYLES = ["clustered", "row-fill", "spread"]
    ondie_cols = [("unlimited", None)] + [(key, gb) for key, _, gb, _, _ in an.columns(an.ONDIE)]
    res = {"grid_gbps": grid, "grid_wc": [an.words_per_cycle(g) for g in grid],
           "ondie_columns": [k for k, _ in ondie_cols], "conditions": {}}
    print(f"\n=== axis B2: die-to-die link bandwidth, {full['config']['name']} block chain (O13) ===")
    pl0 = pm.sequential_fill(fab)
    fref = die_bw(fab, REF_WC)
    for title, phase, on_chip in conds:
        recs = [dict(r) for r in full["phases"][phase] if on_chip or STAYS(r["name"])]
        for eo in lw.block_elementwise_ops(c27, S=S27, phase=phase):
            if not on_chip and not STAYS(eo.name):
                continue
            c = lw.elementwise_cost(eo, fab.digital)
            recs.append({"name": eo.name, "compute_s": c["latency_s"], "write_s": 0.0,
                         "ondie_serial_ref_s": 0.0})
        wr = (lambda r: r["write_s"]) if on_chip else (lambda r: 0.0)
        base = sum(wr(r) + r["compute_s"] for r in recs) * n_layers
        chain = lw.block_chain(c27, S27, phase, on_chip=on_chip)
        entry_of = {o: e["name"] for e in chain for o in e["ops"]}
        pays = {e["name"]: e["ops"][0] for e in chain}
        per_style = {}
        print(f"\n  -- {title}: no-network stack {base*1e3:.2f} ms ({n_layers} layers)")
        print(f"  {'seating':10} {'busiest entry':14} {'D2D/layer@ref':>14} {'1% (max)':>10} {'2x (max)':>10} {'1% (sum)':>10}")
        for style in STYLES:
            seating = lw.seat_block(fab, chain, style)
            flows = lw.block_die_flows(chain, seating, fab)
            d2d_ref = {nm: cc.link_occupancy(fl, fref, CYC, pl0)["serialization_s"]
                       for nm, fl in flows.items()}
            unit_in_ref = d2d_ref.get(lw.ATTENTION_DIE, 0.0) if not on_chip else 0.0

            def layer(noc_g, d2d_g, overlap="max", d2d_ref=d2d_ref, unit_in_ref=unit_in_ref):
                tot = 0.0
                for r in recs:
                    ondie = ser_at(r["ondie_serial_ref_s"], noc_g) if noc_g else 0.0
                    ent = entry_of.get(r["name"])
                    d2d = 0.0
                    if ent is not None and pays[ent] == r["name"] and \
                            not (ent == lw.ATTENTION_DIE and not on_chip):
                        d2d = ser_at(d2d_ref.get(ent, 0.0), d2d_g)
                    tot += wr(r) + (max(r["compute_s"], ondie, d2d) if overlap == "max"
                                    else r["compute_s"] + ondie + d2d)
                tot += ser_at(unit_in_ref, d2d_g)
                return tot * n_layers

            curves = {ck: {"mult_max": [layer(cg, g) / base for g in grid],
                           "mult_sum": [layer(cg, g, "sum") / base for g in grid]}
                      for ck, cg in ondie_cols}
            thr = {"d2d_1pct": threshold(lambda g: layer(None, g) / base, 1.01, lo, hi),
                   "d2d_2x": threshold(lambda g: layer(None, g) / base, 2.0, lo, hi),
                   "d2d_1pct_sum": threshold(lambda g: layer(None, g, "sum") / base, 1.01, lo, hi)}
            knee_entry = max(d2d_ref, key=d2d_ref.get)
            cols = {}
            for dk, _, dg, _, _ in an.columns(an.D2D):
                for ck, cg in ondie_cols:
                    cols[f"{ck}|{dk}"] = {"max": layer(cg, dg) / base, "sum": layer(cg, dg, "sum") / base}
            per_style[style] = {"seating": seating, "d2d_ref_s": d2d_ref,
                                "d2d_layer_ref_s": sum(d2d_ref.values()),
                                "knee_entry": knee_entry, "curves": curves,
                                "thresholds_gbps": thr, "columns": cols}
            print(f"  {style:10} {knee_entry:14} {sum(d2d_ref.values())*1e3:>11.3f} ms "
                  f"{fmt_thr(thr['d2d_1pct'], hi):>10} {fmt_thr(thr['d2d_2x'], hi):>10} "
                  f"{fmt_thr(thr['d2d_1pct_sum'], hi):>10}")
            if style == "clustered" and on_chip:
                res["map_prefill_clustered"] = {
                    "ondie_gbps": ngrid, "d2d_gbps": grid,
                    "mult_max": [[layer(ng, dg) / base for dg in grid] for ng in ngrid],
                    "mult_sum": [[layer(ng, dg, "sum") / base for dg in grid] for ng in ngrid]}
        for style in STYLES:
            print_columns(an.D2D, [(f"{style} | on-die {ck}",
                                    [f"{per_style[style]['columns'][f'{ck}|{dk}']['max']:.2f}.."
                                     f"{per_style[style]['columns'][f'{ck}|{dk}']['sum']:.2f}x"
                                     for dk, *_ in an.columns(an.D2D)])
                                   for ck, _ in ondie_cols],
                          f"{style}: stack multiplier, on-die column x D2D column:")
        res["conditions"][title] = {"base_s": base, "styles": per_style,
                                    "chain": [{k: v for k, v in e.items()} for e in chain]}
    return res


def fig_d2d_2p7b(res):
    grid = res["grid_gbps"]
    fig, axes = plt.subplots(1, 3, figsize=(16.5, 5.0))
    for ax, (title, cond) in zip(axes[:2], res["conditions"].items()):
        sty = cond["styles"]
        for labels, ys in fs.group_identical([(s, sty[s]["curves"]["unlimited"]["mult_max"]) for s in sty]):
            line, = ax.plot(grid, ys, "-", color=COLOR[labels[0]], lw=1.7,
                            label=f"{fs.merged_label(labels)} (on-die unlimited)")
            ax.plot(grid, sty[labels[0]]["curves"]["unlimited"]["mult_sum"], "--", color=COLOR[labels[0]], lw=0.9, alpha=0.8)
            if len(labels) > 1:
                k = len(grid) // 6
                ax.annotate(f"{len(labels)} curves identical", (grid[k], ys[k]), textcoords="offset points",
                            xytext=(6, 7), fontsize=6.5, color=line.get_color())
        for labels, ys in fs.group_identical([(s, sty[s]["curves"]["analog_ondie_low"]["mult_max"]) for s in sty]):
            ax.plot(grid, ys, ":", color=COLOR[labels[0]], lw=1.4,
                    label=f"{fs.merged_label(labels)} (on-die 0.4 GB/s)")
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlim(grid[0], grid[-1])
        mark(ax, an.D2D)
        ax.set_title(f"{title} -- {cond['styles']['clustered']['knee_entry']} entry sets the busiest die link",
                     fontsize=9)
        ax.set_xlabel("die-to-die link bandwidth per direction (GB/s)")
        ax.set_ylabel("stack / no-network stack")
        ax.grid(alpha=0.3, which="both")
        ax.legend(fontsize=7, loc="upper right")
    m = res["map_prefill_clustered"]
    ax = axes[2]
    X, Y = np.meshgrid(m["d2d_gbps"], m["ondie_gbps"])
    Z = np.array(m["mult_max"])
    pc = ax.pcolormesh(X, Y, Z, norm=LogNorm(vmin=1.0, vmax=max(2.0, Z.max())), cmap="YlOrRd", shading="auto")
    cs = ax.contour(X, Y, Z, levels=[1.01, 2.0], colors=["0.2", "0.2"], linestyles=["-", "--"], linewidths=1.0)
    ax.clabel(cs, fmt={1.01: "1%", 2.0: "2x"}, fontsize=7)
    ax.set_xscale("log"); ax.set_yscale("log")
    for a in an.digital(an.D2D):
        ax.axvline(a.gbps, color="0.25", ls=":", lw=1.0)
    for a in an.digital(an.ONDIE):
        ax.axhline(a.gbps, color="0.25", ls=":", lw=1.0)
    bd, bo = an.band(an.D2D).band, an.band(an.ONDIE).band
    ax.add_patch(plt.Rectangle((bd[0], bo[0]), bd[1] - bd[0], bo[1] - bo[0], fill=False,
                               ec="#7a5c00", lw=1.4, ls="-"))
    ax.text(bd[0], bo[1] * 1.3, "analog-reality (est.)", fontsize=7, color="#7a5c00")
    ax.text(an.by_key("grs").gbps * 1.1, an.by_key("esp").gbps * 1.1, "GRS x ESP\n(digital)", fontsize=7, color="0.25")
    ax.set_xlabel("die-to-die link bandwidth (GB/s)")
    ax.set_ylabel("on-die link bandwidth (GB/s)")
    ax.set_title("prefill on chip, clustered: stack multiplier (perfect-overlap end)\n"
                 "over both networks; contours 1% and 2x", fontsize=9)
    fig.colorbar(pc, ax=ax, shrink=0.85, label="stack / no-network stack")
    fig.suptitle("Axis B2 -- die-to-die link bandwidth, 2.7B-class block chain (O13), NeuRRAM tier\n"
                 "solid = perfect-overlap, dashed = zero-overlap; dotted = GRS, shaded = analog-reality band (estimated)",
                 fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    p = os.path.join(OUT, "sweep_axis_d2d_2p7b.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    print(f"PNG -> {p}")


# ----------------------------------------------------------------- axis B3
def axis_d2d_probe(probe):
    fab = fabric_mod.from_yaml(MULTI24)
    grid = log_grid(5e-4, 1e3, an.D2D)
    lo, hi = grid[0], grid[-1]
    comp = probe["compute_s"]
    n = probe["op"]["dies"]
    P, C, M = probe["op"].get("P", 64), probe["op"]["C"], probe["op"]["M"]
    res = {"grid_gbps": grid, "compute_s": comp, "op": dict(probe["op"], P=P), "styles": {}}
    print(f"\n=== axis B3: die-to-die link bandwidth, the {n}-die probe operator "
          f"(P={P}, C={C}, M={M}; compute {comp*1e3:.3f} ms) ===")
    print(f"  {'seating':10} {'busiest wire words':>18} {'1% (max)':>10} {'2x (max)':>10} {'1% (sum)':>10}")
    for label, slots_n in die_styles(fab, n):
        fl = probe_flows(fab, n, P, C, M)
        ser_ref, _, _ = occupancy_on(fab, slots_n, fl, REF_WC)
        ser = lambda g, s=ser_ref: ser_at(s, g)
        mult = lambda g, ov="max": (max(comp, ser(g)) if ov == "max" else comp + ser(g)) / comp
        thr = {"d2d_1pct": threshold(mult, 1.01, lo, hi), "d2d_2x": threshold(mult, 2.0, lo, hi),
               "d2d_1pct_sum": threshold(lambda g: mult(g, "sum"), 1.01, lo, hi)}
        res["styles"][label] = {"serial_ref_s": ser_ref, "busiest_words": ser_ref / CYC * REF_WC,
                                "mult_max": [mult(g) for g in grid], "mult_sum": [mult(g, "sum") for g in grid],
                                "thresholds_gbps": thr,
                                "columns": {key: {"max": mult(gb), "sum": mult(gb, "sum")}
                                            for key, _, gb, _, _ in an.columns(an.D2D)}}
        print(f"  {label:10} {ser_ref/CYC*REF_WC:>18,.0f} {fmt_thr(thr['d2d_1pct'], hi):>10} "
              f"{fmt_thr(thr['d2d_2x'], hi):>10} {fmt_thr(thr['d2d_1pct_sum'], hi):>10}")
    print_columns(an.D2D, [(l, [f"{v['columns'][k]['max']:.2f}..{v['columns'][k]['sum']:.2f}x"
                                for k, *_ in an.columns(an.D2D)]) for l, v in res["styles"].items()],
                  "operator latency / compute at the columns:")
    return res


def fig_d2d_probe(res):
    grid = res["grid_gbps"]
    fig, ax = plt.subplots(figsize=(7.4, 4.8))
    sty = res["styles"]
    for labels, ys in fs.group_identical([(l, sty[l]["mult_max"]) for l in sty]):
        line, = ax.plot(grid, ys, "-", color=COLOR[labels[0]], lw=1.7, label=fs.merged_label(labels))
        ax.plot(grid, sty[labels[0]]["mult_sum"], "--", color=COLOR[labels[0]], lw=0.9, alpha=0.8)
        if len(labels) > 1:
            k = len(grid) // 6
            ax.annotate(f"{len(labels)} curves identical", (grid[k], ys[k]), textcoords="offset points",
                        xytext=(6, 7), fontsize=6.5, color=line.get_color())
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(grid[0], grid[-1])
    mark(ax, an.D2D)
    op = res["op"]
    ax.set_title(f"Axis B3 -- the {op['dies']}-die probe operator (C={op['C']}, M={op['M']}), "
                 f"tensor once, routed producer -> consumer", fontsize=9.5)
    ax.set_xlabel("die-to-die link bandwidth per direction (GB/s)")
    ax.set_ylabel("operator latency / compute")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    p = os.path.join(OUT, "sweep_axis_d2d_probe.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    print(f"PNG -> {p}")


# ----------------------------------------------------------------- axis C
def axis_unit_link(sysd):
    grid = log_grid(1e-3, 1e3, an.D2D)
    lo, hi = grid[0], grid[-1]
    fab = fabric_mod.default()
    unit0 = fab.attention_unit
    hops = lw.unit_link_hops()
    cfg = lw.GptConfig()
    res = {"grid_gbps": grid, "unit": dataclasses.asdict(unit0), "link_hops": hops, "conditions": {}}
    print("\n=== axis C: the die<->unit link of the offloaded attention (end to end, single pass) ===")
    for phase in ("prefill", "decode"):
        per = next(iter(sysd["phases"][phase]["per_op"].values()))
        sf_B = N_LAYERS * sum(o["compute_s"] for o in per if STAYS(o["name"]))

        def cost(g):
            u = dataclasses.replace(unit0, link_bandwidth_words_per_cycle=an.words_per_cycle(g))
            return lw.attention_unit_cost(cfg, S355, phase, u, hops=hops)

        c_inf = lw.attention_unit_cost(cfg, S355, phase,
                                       dataclasses.replace(unit0, link_bandwidth_words_per_cycle=1e30), hops=hops)
        e2e_inf = sf_B + N_LAYERS * c_inf["chain_s"]
        e2e = lambda g: sf_B + N_LAYERS * cost(g)["chain_s"]
        mult = lambda g: e2e(g) / e2e_inf
        thr = {"e2e_1pct": threshold(mult, 1.01, lo, hi), "e2e_2x": threshold(mult, 2.0, lo, hi)}
        title = f"{phase}, attention offloaded (end to end)"
        res["conditions"][title] = {
            "die_side_s": sf_B, "unit_chain_inf_s": N_LAYERS * c_inf["chain_s"], "e2e_inf_s": e2e_inf,
            "e2e_s": [e2e(g) for g in grid], "mult": [mult(g) for g in grid], "thresholds_gbps": thr,
            "columns": {key: {"mult": mult(gb), "e2e_s": e2e(gb)} for key, _, gb, _, _ in an.columns(an.D2D)}}
        print(f"  {title}: die side {sf_B*1e3:.3f} ms + unit chain {N_LAYERS*c_inf['chain_s']*1e3:.3f} ms "
              f"(link unlimited) -> 1% at {fmt_thr(thr['e2e_1pct'], hi)} GB/s, 2x at {fmt_thr(thr['e2e_2x'], hi)} GB/s")
    print_columns(an.D2D, [(t, [f"{v['columns'][k]['mult']:.2f}x ({v['columns'][k]['e2e_s']*1e3:.1f} ms)"
                                for k, *_ in an.columns(an.D2D)]) for t, v in res["conditions"].items()],
                  "end-to-end latency / (link unlimited) at the columns:")
    return res


def fig_unit_link(res):
    grid = res["grid_gbps"]
    fig, ax = plt.subplots(figsize=(7.4, 4.8))
    for (title, v), c in zip(res["conditions"].items(), ["#2a9d8f", "#d1495b"]):
        ax.plot(grid, v["mult"], "-", color=c, lw=1.7, label=title)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(grid[0], grid[-1])
    mark(ax, an.D2D)
    ax.set_title("Axis C -- the die<->unit link (per direction) of the offloaded attention:\n"
                 "end-to-end single-pass latency vs an unlimited link (generic unit, DR-9)", fontsize=9.5)
    ax.set_xlabel("die<->unit link bandwidth (GB/s)")
    ax.set_ylabel("end-to-end latency / (link unlimited)")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    p = os.path.join(OUT, "sweep_axis_unit_link.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    print(f"PNG -> {p}")


# ----------------------------------------------------------------- axis H
def axis_psum(sysd):
    pre = sysd["phases"]["prefill"]
    acc = pre.get("accounting_variants", {})
    names = {"1 word (direction-split only, O22)": "direction-split only (O22)",
             "2 words (current)": "direction-split + 16-bit partial sums (current)"}
    grid = log_grid(1e-3, 1e4, an.ONDIE)
    lo, hi = grid[0], grid[-1]
    per_all = pre["per_op"]
    base = sum(o["write_s"] + o["compute_s"] for o in per_all[ORDER[0]]) * N_LAYERS
    res = {"note": "prefill, attention on chip; 4 words would need re-scoring the traffic structure (not in this run)",
           "variants": {}}
    print("\n=== axis H: partial-sum width on the on-die wires (prefill on chip) ===")
    print(f"  {'width':36} {'scheme':14} {'1% (max)':>10} {'2x (max)':>10}")
    for label_w, aname in names.items():
        if aname not in acc:
            continue
        out = {}
        for label in ORDER:
            ser_of = acc[aname][label]["per_op_serial_s"]

            def stack(g, ov="max"):
                return sum(o["write_s"] + (max(o["compute_s"], ser_at(ser_of[o["name"]], g)) if ov == "max"
                                           else o["compute_s"] + ser_at(ser_of[o["name"]], g))
                           for o in per_all[label]) * N_LAYERS

            thr = {"max_1pct": threshold(lambda g: stack(g) / base, 1.01, lo, hi),
                   "max_2x": threshold(lambda g: stack(g) / base, 2.0, lo, hi)}
            out[label] = {"thresholds_gbps": thr,
                          "columns": {key: stack(gb) / base for key, _, gb, _, _ in an.columns(an.ONDIE)}}
            print(f"  {label_w:36} {SHORT[label]:14} {fmt_thr(thr['max_1pct'], hi):>10} {fmt_thr(thr['max_2x'], hi):>10}")
        res["variants"][label_w] = out
    return res


# ----------------------------------------------------------------- axis T1
def axis_t1_hub(sysd):
    """O28 (C34): the die-buffer (T1) bandwidth axis, ANALYTIC in value
    units. The hub is ONE shared port -- exactly the MX100-class medium
    (DMA engine + shared SRAM): per matmul op its occupancy is the T2 bus
    words (every macro's down stream and 16-bit up stream cross the same
    medium) plus the op's input tensor arriving INTO the buffer once
    (P x C x N values), so the T1 boundary is the T2 bus boundary shifted
    by the in-fill share -- the equivalence the registry's mapping rule
    promised, now an identity on stored components. Timeloop's native
    throttling is NOT this axis: it charges the glb in COUNTER units
    (input fills x7 bit slices + output fills and updates x8 bit groups;
    the write port binds -- ffn1: 37,224,448 units against 8.9M value
    words), which is why the old T1 sweep read 160x at "64 w/c". The unit
    audit is pinned in group 29 and printed by analyze_bandwidth_sweep.py;
    elementwise ops' glb passes stay energy-priced, not timed (as on every
    other axis)."""
    grid = log_grid(1e-3, 1e4, an.ONDIE)
    lo, hi = grid[0], grid[-1]
    cfg = lw.GptConfig()
    conds = [("prefill, attention on chip", "prefill", True),
             ("prefill, attention offloaded", "prefill", False),
             ("decode, attention on chip", "decode", True),
             ("decode, attention offloaded", "decode", False)]
    res = {"grid_gbps": grid,
           "port_model": "one shared port (MX100-class DMA + shared SRAM); "
                         "hub words = T2 bus words + the op's input tensor once",
           "timeloop_note": "Timeloop's glb throttling charges counter units "
                            "(inputs x7, outputs x8x2 on the write port), not value "
                            "words -- validation only, audited in group 29",
           "conditions": {}}
    print("\n=== axis T1: the die-buffer hub bandwidth (value units, analytic; O28/C34) ===")
    for title, phase, on_chip in conds:
        per_bus = sysd["phases"][phase]["per_op"]["bus (shared medium)"]
        shapes = {o.name: o.P * o.C * o.N for o in lw.block_ops(cfg, 512, phase)}
        ops = [o for o in per_bus if on_chip or STAYS(o["name"])]
        per = {}
        for o in ops:
            infill_s = shapes.get(o["name"], 0) * CYC / REF_WC   # seconds at REF_GBPS
            hub_s = o["serial_s"] + infill_s if o["kind"] != "elementwise" else 0.0
            per[o["name"]] = {"bus_serial_ref_s": o["serial_s"], "infill_ref_s": infill_s,
                              "hub_serial_ref_s": hub_s, "compute_s": o["compute_s"],
                              "write_s": o["write_s"], "kind": o["kind"]}
        base = sum((o["write_s"] if on_chip else 0.0) + o["compute_s"]
                   for o in ops) * N_LAYERS

        def stack(g, ov="max"):
            tot = 0.0
            for o in ops:
                ser = ser_at(per[o["name"]]["hub_serial_ref_s"], g)
                wr = o["write_s"] if on_chip else 0.0
                tot += wr + (max(o["compute_s"], ser) if ov == "max"
                             else o["compute_s"] + ser)
            return tot * N_LAYERS

        def ratio(g):
            return max((ser_at(v["hub_serial_ref_s"], g) / v["compute_s"]
                        for v in per.values()
                        if v["hub_serial_ref_s"] > 0 and v["compute_s"] > 0),
                       default=0.0)

        knee = max((n for n, v in per.items() if v["compute_s"] > 0 and v["hub_serial_ref_s"] > 0),
                   key=lambda n: per[n]["hub_serial_ref_s"] / per[n]["compute_s"])
        thr = {"max_1pct": threshold(lambda g: stack(g) / base, 1.01, lo, hi),
               "max_2x": threshold(lambda g: stack(g) / base, 2.0, lo, hi),
               "sum_1pct": threshold(lambda g: stack(g, "sum") / base, 1.01, lo, hi),
               "busiest_op_net_eq_comp": threshold(ratio, 1.0, lo, hi)}
        res["conditions"][title] = {
            "base_s": base, "per_op": per, "knee_op": knee,
            "mult_max": [stack(g) / base for g in grid],
            "mult_sum": [stack(g, "sum") / base for g in grid],
            "busiest_ratio": [ratio(g) for g in grid],
            "thresholds_gbps": thr,
            "columns": {key: {"max": stack(gb) / base, "sum": stack(gb, "sum") / base,
                              "busiest_ratio": ratio(gb)}
                        for key, _, gb, _, _ in an.columns(an.ONDIE)}}
        print(f"  {title:32} knee {knee:9} 1% {fmt_thr(thr['max_1pct'], hi):>7} GB/s  "
              f"2x {fmt_thr(thr['max_2x'], hi):>7}  net=comp {fmt_thr(thr['busiest_op_net_eq_comp'], hi):>7}")
    print_columns(an.ONDIE, [(t, [f"{c['columns'][k]['max']:.2f}..{c['columns'][k]['sum']:.2f}x"
                                  for k, *_ in an.columns(an.ONDIE)])
                             for t, c in res["conditions"].items()],
                  "T1 hub stack multiplier at the on-die columns (the digital anchors are "
                  "NoC links -- scale reference only; the band is the MX100-class estimate):")
    return res


def fig_t1_hub(res, sysd):
    grid = res["grid_gbps"]
    fig, ax = plt.subplots(figsize=(8.2, 5.0))
    for title, col in (("prefill, attention on chip", "#2a9d8f"),
                       ("prefill, attention offloaded", "#d1495b")):
        c = res["conditions"][title]
        ax.plot(grid, c["mult_max"], "-", color=col, lw=1.7,
                label=f"T1 hub, {title} (knee {c['knee_op']})")
        ax.plot(grid, c["mult_sum"], "--", color=col, lw=0.9, alpha=0.8)
        # the bus twin: the same stored components without the in-fill
        per_bus = sysd["phases"]["prefill"]["per_op"]["bus (shared medium)"]
        on_chip = "on chip" in title
        ops = [o for o in per_bus if on_chip or STAYS(o["name"])]
        base = sum((o["write_s"] if on_chip else 0.0) + o["compute_s"] for o in ops) * N_LAYERS
        bus = [sum((o["write_s"] if on_chip else 0.0)
                   + max(o["compute_s"], ser_at(o["serial_s"], g)) for o in ops) * N_LAYERS / base
               for g in grid]
        ax.plot(grid, bus, ":", color=col, lw=1.2, alpha=0.9,
                label=f"T2 bus twin (no in-fill), {title}")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(grid[0], grid[-1])
    mark(ax, an.ONDIE)
    ax.set_title("Axis T1 -- the die-buffer hub (one shared port, value units; O28/C34):\n"
                 "the T1 boundary = the T2 bus boundary + the input's in-fill (the identity, group 29);\n"
                 "MX100-class chips (DMA + shared SRAM) are read on THIS axis, at the estimated band",
                 fontsize=9)
    ax.set_xlabel("die-buffer hub bandwidth (GB/s, value units)")
    ax.set_ylabel("whole-stack latency / no-network stack")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=7, loc="upper right")
    fig.tight_layout()
    p = os.path.join(OUT, "sweep_axis_t1_hub.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    print(f"PNG -> {p}")


# ----------------------------------------------------------------- the plane (O17b)
MAIN_COND = "prefill, attention offloaded"       # the main-figure condition
MM_KINDS = ("static", "dynamic")                 # the ops whose compute scales with t_MVM


def _mm_ops(per_op_list, on_chip=True):
    return [o for o in per_op_list if o["kind"] in MM_KINDS and (on_chip or STAYS(o["name"]))]


def _case(net_gb, mm_ref_s, t_grid, g_grid, surface=False, scan=False):
    """One plane case from its two device-free numbers: net_gb GB on the
    busiest resource (seconds x GB/s, a bandwidth property) and mm_ref_s of
    matmul compute at t_ref. r(g, t) = (net_gb / g) / (mm_ref_s * t / t_ref);
    the r = 1 boundary is the closed form g1(t) = b_ref * t_ref / t."""
    b_ref = net_gb / mm_ref_s                     # GB/s where net = compute at t_ref
    out = {"net_gb": net_gb, "mm_ref_s": mm_ref_s, "boundary_gbps_at_tref": b_ref,
           "marks": {c.key: {"t_mvm_s": c.t_mvm_s, "status": c.t_mvm_status,
                             "boundary_gbps": b_ref * T_REF / c.t_mvm_s}
                     for c in an.device_marks()}}
    if surface:
        out["r"] = [[(net_gb / g) / (mm_ref_s * t / T_REF) for g in g_grid] for t in t_grid]
    if scan:
        lo, hi = g_grid[0], g_grid[-1]
        out["scan_thresholds_gbps"] = [
            threshold(lambda g, t=t: (net_gb / g) / (mm_ref_s * t / T_REF), 1.0, lo, hi)
            for t in t_grid]
    return out


def axis_device_plane(sysd):
    marks = an.device_marks()
    t_lo, t_hi = 0.05e-6, 100e-6
    n = int(round(np.log10(t_hi / t_lo) * PER_DECADE)) + 1
    t_grid = sorted({round(float(x), 15) for x in np.geomspace(t_lo, t_hi, n)} |
                    {round(c.t_mvm_s, 15) for c in marks})
    g_ondie = log_grid(1e-3, 1e4, an.ONDIE)
    g_d2d = log_grid(5e-4, 1e3, an.D2D)
    res = {"t_grid_s": t_grid, "t_ref_s": T_REF, "ref_gbps": REF_GBPS,
           "metric": "busiest operator's network / compute ratio r(g, t); r = 1 <=> "
                     "g = ref_gbps * (ser_ref / mm_ref) * (t_ref / t), slope -1 in log-log",
           "marks": [{"key": c.key, "label": c.label, "t_mvm_s": c.t_mvm_s,
                      "status": c.t_mvm_status} for c in marks],
           "what_does_not_scale": FIXED["device_axis_fixed"]}
    print("\n=== the (t_MVM x bandwidth) plane (O17b): busiest-operator net / compute ===")
    print("  silicon marks (registry): " + ", ".join(
        f"{c.label} {c.t_mvm_s*1e6:.3g} us [{c.t_mvm_status}]" for c in marks))

    # ---- on-die (axis A): every condition's coefficients, surfaces on the main condition
    res["ondie"] = {"g_grid_gbps": g_ondie, "main_condition": MAIN_COND, "conditions": {}}
    conds = [("prefill, attention on chip", "prefill", True),
             ("prefill, attention offloaded", "prefill", False),
             ("decode, attention on chip", "decode", True),
             ("decode, attention offloaded", "decode", False)]
    for title, phase, on_chip in conds:
        per_all = sysd["phases"][phase]["per_op"]
        schemes = {}
        for label in ORDER:
            mm = _mm_ops(per_all[label], on_chip)
            knee = max(mm, key=lambda o: o["serial_s"] / o["compute_s"])
            c = _case(knee["serial_s"] * REF_GBPS, knee["compute_s"], t_grid, g_ondie,
                      surface=(title == MAIN_COND), scan=(title == MAIN_COND))
            c["knee_op"] = knee["name"]
            schemes[label] = c
        res["ondie"]["conditions"][title] = schemes
    main = res["ondie"]["conditions"][MAIN_COND]
    print(f"\n  -- on-die (axis A), {MAIN_COND}: r = 1 at t_ref / at HERMES (GB/s)")
    for label in ORDER:
        c = main[label]
        print(f"  {SHORT[label]:14} knee {c['knee_op']:6} {c['boundary_gbps_at_tref']:8.3f} "
              f"/ {c['marks']['hermes']['boundary_gbps']:8.2f}")

    # ---- die level (axes B1, B3, C): one r line per case
    d2d = {}
    pre = sysd["phases"]["prefill"]
    per_star = next(iter(pre["per_op"].values()))
    mm_on = pre["compute_s"]
    mm_off = N_LAYERS * sum(o["compute_s"] for o in _mm_ops(per_star, on_chip=False))
    base = fabric_mod.from_yaml(MULTI)
    cfg = lw.GptConfig()
    REF = 256.0
    variants = [(lbl, "mesh", {"routing": "xy", "hub": "center"}, asg)
                for lbl, asg in assignments(base)]
    variants.append(("bus (shared interposer)", "bus", {"driver": "center"}, list(range(UNITS))))
    for title, offl, mm_ref in (("prefill, attention on chip", False, mm_on),
                                ("prefill, attention offloaded", True, mm_off)):
        for lbl, topo, params, asg in variants:
            fab = with_link(base, topo, params, REF)
            pl = pm.sequential_fill(fab)
            d = lw.die_to_die_activation(UCFG, S355, "prefill", fabric=fab, assignment=asg)
            flows = list(d["flows"])
            if offl:
                flows += lw.offload_flows(cfg, S355, "prefill",
                                          lw.attention_dies_of_chain(cfg.n_layers, asg))
            try:
                ser_ref = cc.link_occupancy(flows, fab, CYC, pl)["serialization_s"]
            except Exception:
                busiest = (UNITS - 1) + (4 * cfg.n_layers if offl else 0)
                ser_ref = busiest * WORDS / REF * CYC
            d2d[f"B1 {title} | {lbl}"] = _case(ser_ref * an.gbps_of(REF), mm_ref, t_grid, g_d2d)
    fab24 = fabric_mod.from_yaml(MULTI24)
    probe = json.load(open(os.path.join(OUT, "multidie_placement.json")))
    P, C, M = probe["op"].get("P", 64), probe["op"]["C"], probe["op"]["M"]
    for label, slots_n in die_styles(fab24, probe["op"]["dies"]):
        fl = probe_flows(fab24, probe["op"]["dies"], P, C, M)
        ser_ref, _, _ = occupancy_on(fab24, slots_n, fl, REF_WC)
        d2d[f"B3 probe | {label}"] = _case(ser_ref * REF_GBPS, probe["compute_s"], t_grid, g_d2d)
    for phase, mm_ref in (("prefill", mm_off),
                          ("decode", N_LAYERS * sum(o["compute_s"] for o in _mm_ops(
                              next(iter(sysd["phases"]["decode"]["per_op"].values())), on_chip=False)))):
        st = lw.offload_streams(cfg, S355, phase)
        net = N_LAYERS * (st["q_out"] + st["kv_out"] + st["attn_back"]) / 1e9
        d2d[f"C unit link | {phase}"] = _case(net, mm_ref, t_grid, g_d2d)
    res["d2d"] = {"g_grid_gbps": g_d2d, "cases": d2d}
    print(f"\n  -- die level: r = 1 at t_ref / at HERMES (GB/s)")
    for k, c in d2d.items():
        print(f"  {k:46} {c['boundary_gbps_at_tref']:8.3f} / {c['marks']['hermes']['boundary_gbps']:8.2f}")

    # ---- B2 (2.7B chain): already crossed with axis A -- the plane reads the marks only
    full = json.load(open(os.path.join(OUT, "scale_2p7b_per_op.json")))
    n27 = full["config"]["n_layers"]
    S27 = full["config"].get("S", 512)
    c27 = lw.GptConfig(d_model=full["config"]["d_model"], n_heads=full["config"]["n_heads"],
                       d_ff=full["config"]["d_ff"], n_layers=n27, name=full["config"]["name"])
    recs = {r["name"]: r for r in full["phases"]["prefill"]}
    chain = lw.block_chain(c27, S27, "prefill", on_chip=True)
    pays = {e["name"]: e["ops"][0] for e in chain}
    pl0 = pm.sequential_fill(fab24)
    fref = die_bw(fab24, REF_WC)
    res["b2_marks"] = {}
    for style in ("clustered", "row-fill", "spread"):
        seating = lw.seat_block(fab24, chain, style)
        flows = lw.block_die_flows(chain, seating, fab24)
        d2d_ref = {nm: cc.link_occupancy(fl, fref, CYC, pl0)["serialization_s"]
                   for nm, fl in flows.items()}
        knee_entry = max(d2d_ref, key=d2d_ref.get)
        c = _case(d2d_ref[knee_entry] * REF_GBPS, recs[pays[knee_entry]]["compute_s"], t_grid, g_d2d)
        c["knee_entry"] = knee_entry
        c["condition"] = "prefill, attention on chip (per layer: busiest entry vs its paying op)"
        res["b2_marks"][style] = c
        print(f"  B2 2.7B chain | {style:10} knee {knee_entry:6} "
              f"{c['boundary_gbps_at_tref']:8.3f} / {c['marks']['hermes']['boundary_gbps']:8.2f}")

    # ---- the d family (C33; the O29 boundary family): trunk closed form,
    #      verified against the probes' re-scored flows; d = 1024 is the
    #      PRODUCTION base (co-residency C14), whose knee ffn2 sits x2 above
    #      the trunk line -- same mechanism as ffn2's step (the C split).
    TRUNK = REF_WC * an.SLICES_PER_MVM              # 114,688: star trunk ratio = d / TRUNK
    D_FAMILY = [(1024, "355M (GPT-2 medium), production base"),
                (2560, "2.7B-class (OPT-2.7B)"),
                (4096, "7B-class (Llama-7B width)"),
                (8192, "70B-class (Llama-2-70B width)")]
    law_path = os.path.join(OUT, "scaling_law_summary.json")
    law = json.load(open(law_path)) if os.path.exists(law_path) else None
    fam = {"labels": {str(d): l for d, l in D_FAMILY}, "trunk_denominator": TRUNK,
           "ondie_scheme": "mesh, glb centre; x4.00 vs star, measured d-independent (C33)",
           "ffn2_step": "ffn2 (C = 4d) sits x2 above its on-die d line at d <= 4096 and ON it "
                        "from d >= 5120 (the tiler's macro C split flips 2 -> 4) -- an "
                        "annotation, not a kinked line",
           "d2d_form": "tiler closed form, zero mapper. d = 1024: the PURE hand-off "
                       "stream (ops fit their die; only the hidden state S x d crosses, "
                       "C13 half-layer split, payer ffn1). d >= 2560: BLOCK CHAINS "
                       "INCLUDING their spanning operators (column split, tensor once: "
                       "each receiving die takes the full input) -- the binding entry is "
                       "ffn2's S x 4d, so these lines already carry the flood and sit "
                       "above the single-operator probe (C35)",
           "ondie": {}, "d2d": {}}
    print("\n  -- the d family (routed on die / die level), r = 1 at t_ref in GB/s:")
    for d, label in D_FAMILY:
        if d == 1024:
            b_on = main["mesh, glb centre"]["boundary_gbps_at_tref"]
            note_on = "production base (co-residency C14): knee ffn2 x2 above the trunk line"
            b_d2d = 1024.0 * S355 / (S355 * T_REF * 1e9)
            note_d2d = "C13 half-layer split: hidden state S x d, payer ffn1"
        else:
            r_mesh = 4.0 * d / TRUNK
            if law is not None:                     # the x4 and the trunk position are measured
                got = law["scheme_check"]["ffn1"][str(d)]["mesh, glb centre"]
                assert abs(got / r_mesh - 1) < 1e-6, (d, got, r_mesh)
            b_on = REF_GBPS * r_mesh
            note_on = "trunk law x4 (re-scored probe flows)"
            cfg_d = lw.GptConfig(d_model=d, n_heads=d // 64, d_ff=4 * d, n_layers=24,
                                 name=f"family-d{d}")
            chain_d = lw.block_chain(cfg_d, S355, "prefill", on_chip=True,
                                     max_dies=48, dims=("M",))
            entry = max((e for e in chain_d if e["kind"] == "static"),
                        key=lambda e: e["in_words"])
            assert entry["name"] == "ffn2" and entry["in_words"] == S355 * 4 * d
            b_d2d = entry["in_words"] / (S355 * T_REF * 1e9)
            note_d2d = f"ffn2 entry, {entry['n_dies']} dies (tiler), tensor once"
        fam["ondie"][str(d)] = {"boundary_gbps_at_tref": b_on, "note": note_on}
        fam["d2d"][str(d)] = {"boundary_gbps_at_tref": b_d2d, "note": note_d2d}
        print(f"  d={d:5} {label:36} on-die {b_on:6.3f} | D2D {b_d2d:6.3f}")
    assert abs(fam["d2d"]["2560"]["boundary_gbps_at_tref"] /
               res["b2_marks"]["clustered"]["boundary_gbps_at_tref"] - 1) < 1e-3, \
        "the closed-form d = 2560 line must pass through the measured B2 mark"
    res["d_family"] = fam

    # ---- the collapse: matrix-part multiplier is a function of g x t_MVM; the stack is not
    ops_pre = sysd["phases"]["prefill"]["per_op"]["bus (shared medium)"]
    mm = _mm_ops(ops_pre)
    fix_w = sum(o["write_s"] for o in ops_pre)
    fix_d = sum(o["compute_s"] for o in ops_pre if o["kind"] == "elementwise")
    gt_grid = sorted(np.geomspace(1e-9, 1e-4, 41))          # GB per MVM-row time = g[GB/s] x t[s]
    coll = {"scheme": "bus (shared medium)", "condition": "prefill, attention on chip",
            "gt_grid_gb": list(gt_grid), "per_mark": {}}
    for c in marks:
        t = c.t_mvm_s
        scale = t / T_REF
        mat, whole = [], []
        for gt in gt_grid:
            g = gt / t
            m_num = sum(max(o["compute_s"] * scale, ser_at(o["serial_s"], g)) for o in mm)
            m_den = sum(o["compute_s"] * scale for o in mm)
            mat.append(m_num / m_den)
            whole.append((m_num + fix_w + fix_d) / (m_den + fix_w + fix_d))
        coll["per_mark"][c.key] = {"t_mvm_s": t, "matrix_mult": mat, "whole_mult": whole}
    res["collapse"] = coll

    # ---- the fixed terms: what a 76x faster device does NOT speed up
    ft = {}
    for phase in ("prefill", "decode"):
        ph = sysd["phases"][phase]
        mm_s, w_s, d_s = ph["compute_s"], ph["write_s"], ph["elementwise_s"]
        base_s = mm_s + w_s + d_s
        ft[phase] = {"mm_s": mm_s, "write_s": w_s, "digital_s": d_s, "base_s": base_s,
                     "stack_s": [mm_s * t / T_REF + w_s + d_s for t in t_grid],
                     "at_marks": {c.key: {"stack_s": mm_s * c.t_mvm_s / T_REF + w_s + d_s,
                                          "speedup": base_s / (mm_s * c.t_mvm_s / T_REF + w_s + d_s)}
                                  for c in marks}}
        h = ft[phase]["at_marks"]["hermes"]
        print(f"  fixed terms, {phase:7}: {base_s*1e3:8.2f} ms -> {h['stack_s']*1e3:8.2f} ms at HERMES "
              f"({h['speedup']:.2f}x for a {T_REF/an.chip('hermes').t_mvm_s:.1f}x faster device)")
    res["fixed_terms"] = ft

    # ---- the offloaded twin (C39): the same decomposition with the attention
    #      (qk^t, av, softmax) AND the whole K/V write moved to the external
    #      digital unit (DR-9 generic values; the die<->unit link at its
    #      declared GB/s). The die keeps the projections + FFN (scale with
    #      t_MVM) and its small digital remainder; the unit chain (link
    #      transfer + unit compute + K/V memory) is the NEW fixed floor.
    #      Mechanism note (C39): ON CHIP the dynamic attention ops are
    #      WRITE-RATE-BOUND -- each decode token must SET its K/V row before
    #      qk^t/av can read it, so a device 76x faster at reading with
    #      unchanged writes keeps its on-chip attention walled (DR-5); the
    #      two exits are faster writes (DR-5) or this offload (DR-9).
    unit = fabric_mod.default().attention_unit
    hops = lw.unit_link_hops()
    fto = {}
    relay = {}
    for phase in ("prefill", "decode"):
        c = lw.attention_unit_cost(cfg, S355, phase, unit, hops=hops)
        ops_ph = sysd["phases"][phase]["per_op"]["star (private links)"]
        mm_off = N_LAYERS * sum(o["compute_s"] for o in ops_ph
                                if o["kind"] != "elementwise" and STAYS(o["name"]))
        dg_off = N_LAYERS * sum(o["compute_s"] for o in ops_ph
                                if o["kind"] == "elementwise" and STAYS(o["name"]))
        link_s = N_LAYERS * (c["link_out_s"] + c["link_back_s"])
        unit_s = N_LAYERS * (c["compute_s"] + c["kv_s"])
        base_off = mm_off + dg_off + link_s + unit_s
        fto[phase] = {"mm_s": mm_off, "digital_s": dg_off, "link_s": link_s,
                      "unit_s": unit_s, "base_s": base_off,
                      "stack_s": [mm_off * t / T_REF + dg_off + link_s + unit_s
                                  for t in t_grid],
                      "at_marks": {m.key: {"stack_s": mm_off * m.t_mvm_s / T_REF + dg_off + link_s + unit_s,
                                           "speedup": base_off / (mm_off * m.t_mvm_s / T_REF + dg_off + link_s + unit_s)}
                                   for m in marks}}
        ph = sysd["phases"][phase]
        f_on = ph["write_s"] + ph["elementwise_s"]
        f_off = dg_off + link_s + unit_s
        # crossing t*: offloaded < on-chip <=> r (mm_on - mm_off) > f_off - f_on;
        # with f_off < f_on (the generic DR-9 unit beats the write wall) there is
        # NO crossing: offload wins single-pass latency at EVERY device tier.
        t_star = (T_REF * (f_off - f_on) / (ph["compute_s"] - mm_off)
                  if f_off > f_on else None)
        relay[phase] = {
            "onchip_floor_s": f_on, "offloaded_floor_s": f_off,
            "crossing_t_s": t_star,
            "ratio_at_marks": {m.key: ft[phase]["at_marks"][m.key]["stack_s"] /
                               fto[phase]["at_marks"][m.key]["stack_s"] for m in marks}}
        print(f"  offloaded,   {phase:7}: {base_off*1e3:8.2f} ms -> "
              f"{fto[phase]['at_marks']['hermes']['stack_s']*1e3:8.2f} ms at HERMES "
              f"({fto[phase]['at_marks']['hermes']['speedup']:.2f}x); floor {f_off*1e3:.2f} ms "
              f"(unit {unit_s*1e3:.2f} + link {link_s*1e3:.2f} + digital {dg_off*1e3:.2f}) "
              f"vs on-chip floor {f_on*1e3:.2f} ms; crossing: "
              f"{'none -- offload wins at every tier' if t_star is None else f'{t_star*1e6:.2f} us'}")
    res["fixed_terms_offloaded"] = fto
    res["offload_relay"] = dict(relay,
        verdict="the fixed-terms RELAY: every configuration has its own floor -- on chip the "
                "K/V write + digital unit (DR-5/DR-8), offloaded the attention unit + die<->unit "
                "link (DR-9). Under the generic DR-9 values the offloaded floor beats the write "
                "wall in both phases, so offload wins single-pass latency at EVERY device tier "
                "(no crossing -- the expected 1-3 us threshold does not exist); but the unit "
                "floor caps the offloaded config itself: a 76.3x device buys decode only 1.93x "
                "offloaded (vs 1.11x on chip) -- near-full decode scaling needs offload AND a "
                "faster unit. DR-5 and DR-9 are the two ends of the same decision.")
    return res


MARK_STYLE = {"neurram": ("o", "#1d3557"), "mythic_m1076": ("v", "#3d7a4f"),
              "isaac": ("s", "#7b2d8b"), "hermes": ("D", "#d1495b")}


def _plane_marks(ax, res):
    for m in res["marks"]:
        mk, col = MARK_STYLE[m["key"]]
        ax.axvline(m["t_mvm_s"] * 1e6, color=col, ls="--", lw=1.0, alpha=0.75)
        ax.text(m["t_mvm_s"] * 1e6, 0.02, f"{m['label'].split(' (')[0]} ({m['status']})",
                rotation=90, fontsize=6.5, ha="right", va="bottom",
                transform=ax.get_xaxis_transform(), color=col)


def _plane_anchors(ax, level):
    for a in an.digital(level):
        ax.axhline(a.gbps, color="0.25", ls=":", lw=1.0)
        ax.text(0.99, a.gbps * 1.12, a.label, fontsize=6.5, ha="right", va="bottom",
                transform=ax.get_yaxis_transform(), color="0.25")
    b = an.band(level)
    ax.axhspan(b.band[0], b.band[1], color="#c9a227", alpha=0.16, lw=0)
    ax.text(0.01, np.sqrt(b.band[0] * b.band[1]), "analog-reality tier (estimated)",
            fontsize=6.5, ha="left", va="center", transform=ax.get_yaxis_transform(),
            color="#7a5c00")


def fig_plane(res):
    t_us = [t * 1e6 for t in res["t_grid_s"]]
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.4))
    # on-die panel: r surface of the routed mesh + every scheme's closed-form r = 1 line
    ax = axes[0]
    g = res["ondie"]["g_grid_gbps"]
    main = res["ondie"]["conditions"][MAIN_COND]
    Z = np.array(main["mesh, glb centre"]["r"])
    pc = ax.pcolormesh(t_us, g, Z.T, norm=LogNorm(vmin=1e-3, vmax=1e3), cmap="RdBu_r", shading="auto")
    cs = ax.contour(t_us, g, Z.T, levels=[0.1, 1.0, 10.0], colors="0.2",
                    linestyles=[":", "-", ":"], linewidths=[0.8, 1.4, 0.8])
    ax.clabel(cs, fmt={0.1: "r=0.1", 1.0: "r=1", 10.0: "r=10"}, fontsize=7)
    for labels, _ in fs.group_identical([(l, [main[l]["boundary_gbps_at_tref"]]) for l in ORDER]):
        b = main[labels[0]]["boundary_gbps_at_tref"]
        ys = [b * res["t_ref_s"] / t for t in res["t_grid_s"]]
        lab = f"r=1: {' = '.join(SHORT[l] for l in labels)} (knee {main[labels[0]]['knee_op']})"
        if labels[0] == "mesh, glb centre":
            lab = "r=1: routed x3, tied (knee ffn2); = d family 1024, production base"
        ax.plot(t_us, ys, "-", color=COLOR[labels[0]], lw=1.6, label=lab)
    fam = res["d_family"]
    for dk, col in (("2560", "#6b8cae"), ("4096", "#3d6491"), ("8192", "#12365e")):
        b = fam["ondie"][dk]["boundary_gbps_at_tref"]
        ys = [b * res["t_ref_s"] / t for t in res["t_grid_s"]]
        short = {"2560": "d=2560 (OPT-2.7B)", "4096": "d=4096 (7B width)",
                 "8192": "d=8192 (70B width)"}[dk]
        ax.plot(t_us, ys, "-.", color=col, lw=1.4, label=f"r=1 routed, {short}")
    ax.text(0.30, 0.02, "d family (routed, C33): trunk law x4, verified on the re-scored probe flows.\n"
                        "ffn2 (C = 4d) sits x2 above its d line at d <= 4096 and ON it from d >= 5120\n"
                        "(the tiler's macro C split flips 2 -> 4) -- annotated, not drawn.",
            transform=ax.transAxes, fontsize=6.3, va="bottom", ha="left", color="0.25",
            bbox=dict(fc="white", ec="0.8", alpha=0.85, pad=2))
    _plane_anchors(ax, an.ONDIE)
    _plane_marks(ax, res)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(t_us[0], t_us[-1]); ax.set_ylim(g[0], g[-1])
    ax.set_xlabel("t_MVM per row (us)"); ax.set_ylabel("on-die link bandwidth (GB/s)")
    ax.set_title(f"on-die (axis A), {MAIN_COND}\nsurface: routed mesh; lines: closed-form r=1, slope -1",
                 fontsize=9)
    fig.colorbar(pc, ax=ax, shrink=0.85, label="r = busiest-op network / compute (mesh centre)")
    ax.legend(fontsize=6, loc="upper right")
    # die-level panel: closed-form r = 1 lines of B1 / B3 / C (+ B2 marks)
    ax = axes[1]
    gd = res["d2d"]["g_grid_gbps"]
    show = [("B1 prefill, attention offloaded | snake", "#2a9d8f", "B1 48-die offloaded, snake"),
            ("B1 prefill, attention offloaded | bus (shared interposer)", "#7b2d8b", "B1 offloaded, interposer bus"),
            ("B3 probe | clustered", "#e8a13c", "B3 4-die probe, clustered"),
            ("C unit link | prefill", "#d1495b", "C die<->unit link, prefill")]
    for key, col, lab in show:
        c = res["d2d"]["cases"][key]
        ys = [c["boundary_gbps_at_tref"] * res["t_ref_s"] / t for t in res["t_grid_s"]]
        ax.plot(t_us, ys, "-", color=col, lw=1.1, alpha=0.55, label=f"r=1: {lab}")
    fam = res["d_family"]
    for dk, col in (("1024", "#9db4c8"), ("2560", "#6b8cae"),
                    ("4096", "#3d6491"), ("8192", "#12365e")):
        b = fam["d2d"][dk]["boundary_gbps_at_tref"]
        ys = [b * res["t_ref_s"] / t for t in res["t_grid_s"]]
        ax.plot(t_us, ys, "-.", color=col, lw=1.5,
                label=f"r=1 d family, d={dk}: {fam['labels'][dk]}")
    b2 = res["b2_marks"]["clustered"]
    for mkey, mv in b2["marks"].items():
        mk, col = MARK_STYLE[mkey]
        ax.plot(mv["t_mvm_s"] * 1e6, mv["boundary_gbps"], mk, color="0.2", ms=5,
                label="B2 2.7B chain measured (sits on the d=2560 line)" if mkey == "neurram" else None)
    _plane_anchors(ax, an.D2D)
    _plane_marks(ax, res)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(t_us[0], t_us[-1]); ax.set_ylim(gd[0], gd[-1])
    ax.set_xlabel("t_MVM per row (us)"); ax.set_ylabel("die-level link bandwidth (GB/s)")
    ax.set_title("die level: the d family (tiler closed form, tensor once) + the B1/B3/C cases\n"
                 "above a line the network is hidden; below it, exposed", fontsize=9)
    ax.legend(fontsize=6, loc="upper right")
    fig.suptitle("The (t_MVM x bandwidth) plane (O17b) -- busiest-operator network / compute; "
                 "silicon marks from the registry, the surface between them is closed-form\n"
                 "fixed across the plane: K/V write (DR-5), digital unit (DR-8), attention unit (DR-9), link GB/s",
                 fontsize=9.5)
    fig.tight_layout(rect=[0, 0, 1, 0.90])
    p = os.path.join(OUT, "device_plane.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    print(f"PNG -> {p}")


def fig_collapse(res):
    coll = res["collapse"]
    gt = [x * 1e9 for x in coll["gt_grid_gb"]]           # bytes per MVM-row time
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.4), sharey=True)
    for c in res["marks"]:
        mk, col = MARK_STYLE[c["key"]]
        pm_ = coll["per_mark"][c["key"]]
        lab = f"{c['label'].split(' (')[0]} {c['t_mvm_s']*1e6:.3g} us ({c['status']})"
        lab = lab.replace("Mythic AMP M1076", "Mythic M1076")
        axes[0].plot(gt, pm_["matrix_mult"], mk + "-", color=col, ms=3, lw=1.1,
                     markevery=4, label=lab)
        axes[1].plot(gt, pm_["whole_mult"], mk + "-", color=col, ms=3, lw=1.1,
                     markevery=4, label=lab)
    axes[0].set_title("matrix part: the silicon marks land on ONE curve\n(the collapse variable g x t_MVM)", fontsize=9)
    axes[1].set_title("whole stack: K/V write + digital unit do not scale,\nso the collapse fails -- the finding, not a bug", fontsize=9)
    for ax in axes:
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlabel("bandwidth x t_MVM (bytes per MVM-row time)")
        ax.grid(alpha=0.3, which="both")
        ax.legend(fontsize=7)
    axes[0].set_ylabel("latency / compute-bound latency")
    fig.suptitle(f"The collapse (O17b): {coll['condition']}, {coll['scheme']} -- "
                 "words/cycle is this unit only at the NeuRRAM slice count", fontsize=9.5)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    p = os.path.join(OUT, "device_plane_collapse.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    print(f"PNG -> {p}")


def fig_fixed_terms(res):
    t_us = [t * 1e6 for t in res["t_grid_s"]]
    fig, axes = plt.subplots(2, 2, figsize=(11.6, 8.2), sharex=True)

    def marks_on(ax, ft):
        for c in res["marks"]:
            am = ft["at_marks"][c["key"]]
            _, col = MARK_STYLE[c["key"]]
            ax.axvline(c["t_mvm_s"] * 1e6, color=col, ls="--", lw=0.9, alpha=0.6)
            if c["key"] not in ("neurram", "hermes"):   # annotate the endpoints only
                continue
            dx = 4 if c["key"] == "neurram" else -4
            ha = "left" if c["key"] == "neurram" else "right"
            ax.annotate(f"{c['label'].split(' (')[0]}\n{am['stack_s']*1e3:.2f} ms ({am['speedup']:.2f}x)",
                        (c["t_mvm_s"] * 1e6, am["stack_s"] * 1e3), textcoords="offset points",
                        xytext=(dx, -22), fontsize=6.2, color=col, ha=ha,
                        bbox=dict(fc="white", ec="none", alpha=0.75, pad=0.5))

    for r, phase in enumerate(("prefill", "decode")):
        ft = res["fixed_terms"][phase]
        fo = res["fixed_terms_offloaded"][phase]
        rl = res["offload_relay"][phase]
        ax = axes[r, 0]
        mm = [ft["mm_s"] * t / res["t_ref_s"] * 1e3 for t in res["t_grid_s"]]
        w, dg = ft["write_s"] * 1e3, ft["digital_s"] * 1e3
        ax.stackplot(t_us, mm, [w] * len(t_us), [dg] * len(t_us),
                     labels=["matmul compute, ALL of it incl. qk^t/av (scales with t_MVM)",
                             f"K/V write {w:.2f} ms (fixed: SET pulses, DR-5)",
                             f"digital unit {dg:.2f} ms (fixed, DR-8)"],
                     colors=["#8fa8bf", "#d1495b", "#e8a13c"], alpha=0.85)
        marks_on(ax, ft)
        ax.set_title(f"{phase}, attention ON CHIP (fully simulated analog path): "
                     f"{ft['base_s']*1e3:.2f} ms at NeuRRAM\n"
                     f"floor = write + digital {rl['onchip_floor_s']*1e3:.2f} ms "
                     f"(76.3x device buys {ft['at_marks']['hermes']['speedup']:.2f}x)", fontsize=8.2)
        ax = axes[r, 1]
        mmo = [fo["mm_s"] * t / res["t_ref_s"] * 1e3 for t in res["t_grid_s"]]
        dgo, lk, un = fo["digital_s"] * 1e3, fo["link_s"] * 1e3, fo["unit_s"] * 1e3
        ax.stackplot(t_us, mmo, [dgo] * len(t_us), [lk] * len(t_us), [un] * len(t_us),
                     labels=["die matmuls: projections + FFN (scale with t_MVM)",
                             f"die digital remainder {dgo:.2f} ms (fixed, DR-8)",
                             f"die<->unit link {lk:.2f} ms (fixed at the declared GB/s)",
                             f"attention unit: compute + K/V memory {un:.2f} ms (fixed, DR-9 "
                             "generic -- awaiting the real unit's numbers)"],
                     colors=["#8fa8bf", "#e8a13c", "#2a9d8f", "#7b2d8b"], alpha=0.85)
        marks_on(ax, fo)
        ax.set_title(f"{phase}, attention OFFLOADED (unit = DR-9 black box): "
                     f"{fo['base_s']*1e3:.2f} ms at NeuRRAM\n"
                     f"floor = unit + link + digital {rl['offloaded_floor_s']*1e3:.2f} ms "
                     f"(76.3x device buys {fo['at_marks']['hermes']['speedup']:.2f}x)", fontsize=8.2)
    for ax in axes.flat:
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlim(t_us[0], t_us[-1])
        ax.grid(alpha=0.3, which="both")
        ax.legend(fontsize=6.2, loc="lower right")
    for ax in axes[1, :]:
        ax.set_xlabel("t_MVM per row (us)")
    for ax in axes[:, 0]:
        ax.set_ylabel("no-network stack (ms)")
    fig.suptitle("The fixed-terms RELAY (O17b / C39): every configuration has its own non-scaling floor --\n"
                 "on chip the K/V write (DR-5), offloaded the attention unit + link (DR-9); under the generic DR-9 values the "
                 "offloaded floor beats the write wall in BOTH phases,\nso offload wins single-pass latency at EVERY device "
                 "tier (no crossing) -- yet the unit floor then caps the offloaded config itself", fontsize=9)
    fig.text(0.5, 0.005,
             "Mechanism (C39): ON CHIP the dynamic attention ops are WRITE-RATE-BOUND -- each decode token must SET its K/V "
             "row before qk^t/av can read it, so a device 76x faster at reading\nwith unchanged writes keeps its on-chip "
             "attention walled: fast device + attention on chip is a self-contradictory configuration; the two exits are "
             "faster writes (DR-5) or this offload (DR-9).",
             ha="center", fontsize=6.4, color="0.25")
    fig.tight_layout(rect=[0, 0.035, 1, 0.90])
    p = os.path.join(OUT, "device_fixed_terms.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    print(f"PNG -> {p}")


# ----------------------------------------------------------------- main
def main():
    want = sys.argv[1:] or ["ondie", "d2d_355m", "d2d_2p7b", "d2d_probe", "unit_link", "psum",
                            "t1_hub", "plane"]
    sysd = json.load(open(os.path.join(OUT, "contention_system.json")))
    print("fixed settings:")
    for k, v in FIXED.items():
        print(f"  {k:22} {v}")
    print(f"\nanchor columns, on die: " + ", ".join(f"{lab} [{st}]" for _, lab, _, _, st in an.columns(an.ONDIE)))
    print(f"anchor columns, D2D:    " + ", ".join(f"{lab} [{st}]" for _, lab, _, _, st in an.columns(an.D2D)))
    FIXED["schedule_slack"] = (sysd.get("fabric") or {}).get("schedule_slack", 1.0)   # O26: the stored serials carry it
    out = {"fixed": FIXED, "per_decade": PER_DECADE, "anchors": an.as_json(),
           "fabric_ondie": sysd.get("fabric"),
           "fabric_d2d": fabric_mod.provenance(fabric_mod.from_yaml(MULTI))}
    if "ondie" in want:
        out["ondie"] = axis_ondie(sysd); fig_ondie(out["ondie"])
    if "d2d_355m" in want:
        out["d2d_355m"] = axis_d2d_355m(sysd); fig_d2d_355m(out["d2d_355m"])
    if "d2d_2p7b" in want:
        full = json.load(open(os.path.join(OUT, "scale_2p7b_per_op.json")))
        out["d2d_2p7b"] = axis_d2d_2p7b(full); fig_d2d_2p7b(out["d2d_2p7b"])
    if "d2d_probe" in want:
        probe = json.load(open(os.path.join(OUT, "multidie_placement.json")))
        out["d2d_probe"] = axis_d2d_probe(probe); fig_d2d_probe(out["d2d_probe"])
    if "unit_link" in want:
        out["unit_link"] = axis_unit_link(sysd); fig_unit_link(out["unit_link"])
    if "psum" in want:
        out["psum"] = axis_psum(sysd)
    if "t1_hub" in want:
        out["t1_hub"] = axis_t1_hub(sysd); fig_t1_hub(out["t1_hub"], sysd)
    if "plane" in want:
        out["plane"] = axis_device_plane(sysd)
        fig_plane(out["plane"]); fig_collapse(out["plane"]); fig_fixed_terms(out["plane"])
    path = os.path.join(OUT, "phase_sweep.json")
    if len(want) < 8 and os.path.exists(path):        # partial run: merge into the stored file
        old = json.load(open(path)); old.update(out); out = old
    with open(path, "w") as f:
        json.dump(out, f, indent=1, default=float)
    print(f"\nJSON -> {path}")


if __name__ == "__main__":
    main()
