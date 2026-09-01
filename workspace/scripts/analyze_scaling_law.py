"""O17c: read the scaling probes (analysis/scaling_probes.json) into the
measured V(d, S), and draw analysis/scaling_law_vds.png; the derived
numbers go to analysis/scaling_law_summary.json (pinned by group 28).

What the 48 runs measured (and the prediction they falsify):

  - INPUT-TRUNK REGIME (d >= 2560, every static op): the busiest on-die
    wire is the input DOWN trunk -- per macro edge exactly S x C_op /
    (macro C split) words -- so serial / compute = d / (16,384 x 7) =
    d / 114,688: "knee ~ d" with slope exactly 1. ffn2 (C = 4d) rides the
    tiler's macro C split (2 at d <= 4096, 4 above), which is the
    quantisation wiggle in its row: the law is mapper-dependent exactly
    where the tiler changes shape.
  - THE FLIP d*: the partial-sum UP regime exists only below d* ~ 1,220-
    1,350 (log-interpolated per op; ffn2 is down-dominated everywhere).
    The ideal-capacity prediction d* = 1024 x sqrt(32) ~ 5,793 (FIXLIST
    O17c) is FALSIFIED, off by ~4.3x: it ignored the macro fanout (up
    traffic divides by the 8 macro edges) and that multi-die pieces fill
    their die exactly. Below d* the dies are underfull and the mapper
    replicates weights to split P (compute halves at d = 1024), so the
    left branch is mapper-shaped, not a clean 1/d.
  - S-INDEPENDENCE holds for every probed ratio, attention included: the
    statics cancel S exactly, and qk^t's volume follows S^2 but so does
    its compute -- ratio pinned at 0.0714 over S = 128..2048. The "qk^T
    follows S" exception is about absolute volume, not the knee ratio.

Usage (container): python3 scripts/analyze_scaling_law.py
"""
import dataclasses
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import scripts.crossbar_comm as cc
from scripts import anchors as an
from scripts import fabric as fabric_mod
from scripts import figstyle as fs
from scripts import placement as pm

OUT = "/home/workspace/analysis"
PROBES = json.load(open(os.path.join(OUT, "scaling_probes.json")))
REF_WC = PROBES["ref_words_per_cycle"]
REF_GBPS = an.gbps_of(REF_WC)
PSUM = 2.0                                  # 16-bit partial sums (DR-7)
TRUNK = REF_WC * an.SLICES_PER_MVM          # 114,688: ratio = d / TRUNK on the input trunk
STATICS = ["qkv_proj", "out_proj", "ffn1", "ffn2"]
COLOR = {"qkv_proj": "#2a9d8f", "out_proj": "#8fa8bf", "ffn1": "#e8a13c",
         "ffn2": "#d1495b", "qk^t": "#7b2d8b", "av": "#5c4d7d"}
IDEAL_DSTAR = 1024 * np.sqrt(32)            # the falsified prediction


def by_point():
    return {(p["d"], p["S"]): {o["name"]: o for o in p["ops"]}
            for p in PROBES["points"]}


def updown(rec):
    """Busiest-edge occupancy per direction, in width-weighted words."""
    down = max(e["down"] for e in rec["macro_edges"])
    up = max(e["up"] for e in rec["macro_edges"]) * PSUM
    return down, up


SCHEMES = {"star (private links)": ("star", {}),
           "mesh, glb centre": ("mesh", {"routing": "xy", "hub": "center"}),
           "bus (shared medium)": ("bus", {"driver": "center"})}


def rescore_schemes(pts, d_grid, ops=("qkv_proj", "ffn1", "ffn2")):
    """C33: the probes stored every macro edge's down/up, so any scheme is a
    closed-form re-scoring (zero mapper) -- the check that the scheme
    multiplier is d-independent in the trunk regime. Star must reproduce the
    stored serialization exactly (the probes' fabric is the star)."""
    fab0 = fabric_mod.default()
    cyc = fab0.device.cycle_seconds
    fabs = {}
    for label, (topo, params) in SCHEMES.items():
        levels = [dataclasses.replace(l, link=dataclasses.replace(
                      l.link, topology=topo, params=params,
                      bandwidth_words_per_cycle=REF_WC))
                  if l.name == "macro" else l for l in fab0.levels]
        fabs[label] = dataclasses.replace(fab0, name="t", levels=levels).validate()
    out = {}
    for name in ops:
        out[name] = {}
        for d in d_grid:
            r = pts[(d, 512)][name]
            flows = [{"level": "glb<->macro", "level_name": "macro",
                      "node": e["node"], "src": "glb", "dst": f"m{e['node']}",
                      "volume": e["volume"], "down": e["down"], "up": e["up"],
                      "distance": 0.0} for e in r["macro_edges"]]
            row = {}
            for label, f in fabs.items():
                occ = cc.link_occupancy(flows, f, cyc, pm.sequential_fill(f))
                row[label] = occ["serialization_s"] / r["compute_s"]
            assert abs(row["star (private links)"] / r["serial_over_compute"] - 1) < 1e-9
            out[name][d] = row
    return out


def crossing_d(ds, ups, downs):
    """log-interpolated d where up occupancy = down occupancy."""
    y = np.log(np.array(ups) / np.array(downs))
    for i in range(len(ds) - 1):
        if y[i] > 0 >= y[i + 1] or y[i] >= 0 > y[i + 1]:
            f = y[i] / (y[i] - y[i + 1])
            return float(np.exp(np.log(ds[i]) + f * (np.log(ds[i + 1]) - np.log(ds[i]))))
    return None


def main():
    pts = by_point()
    d_grid = list(PROBES["d_grid"])
    s_grid = list(PROBES["s_grid"])
    summary = {"ref_words_per_cycle": REF_WC, "ref_gbps": REF_GBPS,
               "trunk_denominator": TRUNK, "ideal_dstar": float(IDEAL_DSTAR),
               "d_grid": d_grid, "s_grid": s_grid,
               "d_law": {}, "s_check": {}, "dstar": {}}
    print("=== O17c: the measured V(d, S) (star basis, busiest macro edge; "
          f"knee GB/s = {REF_GBPS:.3f} x ratio) ===")
    print(f"\n-- the d law (S = 512, column split, full input per die):")
    print(f"{'op':9} " + "".join(f"{d:>10}" for d in d_grid))
    for name in STATICS:
        row, dirs, ups, downs = [], [], [], []
        for d in d_grid:
            r = pts[(d, 512)][name]
            row.append(r["serial_over_compute"])
            dn, up = updown(r)
            ups.append(up); downs.append(dn)
            dirs.append("up" if up > dn else "down")
        print(f"{name:9} " + "".join(f"{v:>10.4f}" for v in row))
        print(f"{'':9} " + "".join(f"{s:>10}" for s in dirs))
        ds = crossing_d(d_grid, ups, downs)
        summary["d_law"][name] = {"ratio": row, "busiest": dirs}
        if ds:
            summary["dstar"][name] = ds
            print(f"{'':9} measured flip d* (up = down on the busiest edge): {ds:,.0f}")
    print(f"\n   the ideal-capacity prediction d* = 1024 x sqrt(32) = {IDEAL_DSTAR:,.0f} "
          "is FALSIFIED: the flip sits at ~1.3k (macro fanout + exact die fill)")
    print(f"   input-trunk closed form (d >= 2560, macro C split 1): "
          f"ratio = d / {TRUNK:,.0f}")
    for name in ("qk^t", "av"):
        summary["d_law"][name] = {
            "ratio": [pts[(d, 512)][name]["serial_over_compute"] for d in d_grid],
            "busiest": ["up" if (lambda du: du[1] > du[0])(updown(pts[(d, 512)][name]))
                        else "down" for d in d_grid]}
    print(f"\n-- the S check (d = 1024): serial/compute per op -- flat everywhere, "
          "attention included (its volume follows S^2, but so does its compute)")
    print(f"{'op':9} " + "".join(f"{S:>10}" for S in s_grid))
    for name in PROBES["s_ops"]:
        row = [pts[(1024, S)][name]["serial_over_compute"] for S in s_grid]
        summary["s_check"][name] = row
        print(f"{name:9} " + "".join(f"{v:>10.4f}" for v in row))

    sch = rescore_schemes(pts, d_grid)
    summary["scheme_check"] = {op: {str(d): row for d, row in per.items()}
                               for op, per in sch.items()}
    print("\n-- scheme re-scoring from the stored edges (closed form, zero mapper):")
    print("   the routed multiplier is x4.00 EXACTLY at every d (the 2x4 grid puts 4")
    print("   macros' traffic on the busiest wire, d-independent); the bus multiplier")
    print("   drifts 8.25-12 with the up share and settles at 8.25 in the deep trunk")
    print(f"   {'op':9} {'d':>6} {'star':>9} {'mesh x':>8} {'bus x':>8}")
    for name, per in sch.items():
        for d, row in per.items():
            s = row["star (private links)"]
            print(f"   {name:9} {d:>6} {s:>9.4f} "
                  f"{row['mesh, glb centre']/s:>8.2f} {row['bus (shared medium)']/s:>8.2f}")

    fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.6))
    ax = axes[0]
    dd = np.geomspace(d_grid[0], d_grid[-1], 64)
    ax.plot(dd, dd / TRUNK, "--", color="0.4", lw=1.1,
            label=f"input trunk: d / {TRUNK:,.0f} (closed form)")
    series = [(name, [pts[(d, 512)][name]["serial_over_compute"] for d in d_grid])
              for name in STATICS]
    for labels, ys in fs.group_identical(series):     # out_proj = ffn1: merged, never stacked silently (C28)
        name = labels[0]
        line, = ax.plot(d_grid, ys, "-", color=COLOR[name], lw=1.5,
                        label=fs.merged_label(labels))
        for d, y in zip(d_grid, ys):
            dn, up = updown(pts[(d, 512)][name])
            ax.plot(d, y, "^" if up > dn else "v", color=COLOR[name], ms=6)
        if len(labels) > 1:
            k = len(d_grid) // 3
            ax.annotate(f"{len(labels)} series identical", (d_grid[k], float(ys[k])),
                        textcoords="offset points", xytext=(6, 7), fontsize=6.5,
                        color=line.get_color())
    if summary["dstar"]:
        lo, hi = min(summary["dstar"].values()), max(summary["dstar"].values())
        ax.axvspan(lo, hi, color="#2a9d8f", alpha=0.15, lw=0)
        ax.text(np.sqrt(lo * hi), 0.97, f"measured flip d* = {lo:,.0f}-{hi:,.0f}",
                rotation=90, fontsize=7, ha="center", va="top",
                transform=ax.get_xaxis_transform(), color="#1b6d63")
    ax.axvline(IDEAL_DSTAR, color="#7a5c00", ls=":", lw=1.1)
    ax.text(IDEAL_DSTAR, 0.03, "predicted d* = 5,793 (falsified)", rotation=90,
            fontsize=7, ha="right", va="bottom",
            transform=ax.get_xaxis_transform(), color="#7a5c00")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xticks(d_grid); ax.set_xticklabels([str(d) for d in d_grid], fontsize=7)
    ax.minorticks_off()
    ax.set_xlabel("d_model (S = 512)")
    ax.set_ylabel("busiest-wire serial / compute (star basis)")
    ax.set_title("the measured d law: input trunk ~ d above the flip (v = down busiest);\n"
                 "up regime (^) only in underfull dies; ffn2's step = the tiler's C split",
                 fontsize=8.5)
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=7)
    ax = axes[1]
    for name in PROBES["s_ops"]:
        ys = [pts[(1024, S)][name]["serial_over_compute"] for S in s_grid]
        ax.plot(s_grid, ys, "o-", color=COLOR[name], lw=1.5, ms=4, label=name)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_ylim(5e-3, 2e-1)
    ax.set_xticks(s_grid); ax.set_xticklabels([str(S) for S in s_grid], fontsize=7)
    ax.minorticks_off()
    ax.set_xlabel("S (d = 1024)")
    ax.set_ylabel("busiest-wire serial / compute")
    ax.set_title("the S check: every probed ratio cancels S -- the statics exactly,\n"
                 "and qk^t too (volume ~ S^2, compute ~ S^2)", fontsize=8.5)
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=7.5)
    fig.suptitle("O17c -- mapper-measured V(d, S): 48 runs, residency tiler, column split only; "
                 "the d family is measured, and the predicted valley at 5,793 is not there",
                 fontsize=9.5)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    p = os.path.join(OUT, "scaling_law_vds.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    print(f"\nPNG -> {p}")
    sp = os.path.join(OUT, "scaling_law_summary.json")
    with open(sp, "w") as f:
        json.dump(summary, f, indent=1)
    print(f"JSON -> {sp}")


if __name__ == "__main__":
    main()
