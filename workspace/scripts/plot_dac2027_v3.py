"""DAC 2027 figure set v3: drawn from the exported plotting data of
analysis/v7 (and v6 / the v2 figure data where the plan says so), not from
the live model. Each figure writes PDF + SVG + PNG preview, its plotting
data and a metadata JSON into analysis/figures_dac2027/<run-id>/.

    python3 scripts/plot_dac2027_v3.py --run-id 20261019_v3 --only fig1
"""
import argparse
import csv
import hashlib
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.fig_phase_isobar import _angle_along          # label rotation along a curve

matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["savefig.pad_inches"] = 0.0
matplotlib.rcParams["hatch.linewidth"] = 0.22        # fine hatching (the digital unit in Fig. 2(b))
HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.join(HERE, "..")
V7 = os.path.join(WS, "analysis", "v7")
V6 = os.path.join(WS, "analysis", "v6")
OUT = {}
PRODUCTS = []
CODE_VERSION = "b9e5416+uncommitted-scripts"      # the exports' stamp (manifest)


def _run_dir(run_id):
    base = os.path.join(WS, "analysis", "figures_dac2027", run_id)
    for k in ("composites", "panels", "preview", "data", "meta"):
        OUT[k] = os.path.join(base, k)
        os.makedirs(OUT[k], exist_ok=True)
    return base


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def read_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def _content_bbox(fig):
    """Union of everything drawn, in inches (axes frames of axis-off axes
    excluded), so the files carry no margin."""
    from matplotlib.transforms import Bbox
    from matplotlib.spines import Spine
    dpi0 = fig.dpi                                    # measure at 600 dpi: at the default 100 dpi the
    fig.set_dpi(600)                                  # hinted glyph extents can be a pixel short and
    r = fig.canvas.get_renderer()                     # the crop would shave the tops of capitals
    boxes = []
    axes = list(fig.axes)
    for ax in fig.axes:
        axes += list(ax.child_axes)
    for ax in axes:
        if ax.axison:
            boxes.append(ax.get_tightbbox(r)); continue
        for art in ax.get_children():
            if (not art.get_visible() or art is ax.patch or art is ax.xaxis or art is ax.yaxis
                    or isinstance(art, Spine)):
                continue
            try:
                bb = art.get_window_extent(r)
            except Exception:
                continue
            if bb.width > 0 and bb.height > 0 and np.isfinite(bb.extents).all():
                boxes.append(bb)
    boxes += [t.get_window_extent(r) for t in fig.texts]
    boxes += [lg.get_window_extent(r) for lg in fig.legends]
    bb = Bbox.union(boxes).transformed(fig.dpi_scale_trans.inverted())
    fig.set_dpi(dpi0)
    # 1.5 pt of safety: the PDF backend sets bold capitals a little above the
    # box Agg measures, so a crop exactly on the box shaves their tops
    return bb.padded(1.5 / 72)


def save(fig, name, composite=False, sources=(), meta=None, note=""):
    kind = "composites" if composite else "panels"
    bb = _content_bbox(fig)
    paths = {}
    for ext, k in (("pdf", kind), ("svg", kind), ("png", "preview")):
        p = os.path.join(OUT[k], f"{name}.{ext}")
        fig.savefig(p, bbox_inches=bb, pad_inches=0, dpi=200)
        paths[ext] = os.path.relpath(p, os.path.dirname(OUT[kind]))
    plt.close(fig)
    m = {"figure": name, "files": paths, "size_in": [round(bb.width, 3), round(bb.height, 3)],
         "sources": [{"path": s, "sha256_16": _sha(s if os.path.isabs(s) else os.path.join(WS, s))} for s in sources],
         "code_version": CODE_VERSION, "note": note}
    if meta:
        m.update(meta)
    json.dump(m, open(os.path.join(OUT["meta"], f"{name}.json"), "w"), indent=1)
    PRODUCTS.append({"name": name, "kind": kind, "files": list(paths.values())})
    print(f"   {kind}/{name}.pdf|svg  preview/{name}.png  meta/{name}.json")


def dump_csv(name, rows, cols):
    p = os.path.join(OUT["data"], f"{name}.csv")
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    print(f"   data/{name}.csv")


# =====================================================================
# Fig. 1  the mapping phase diagram: intra-die (a) and package (b)
# =====================================================================
# the standing phase-diagram look, type two points larger than the
# generator's (the figure-set render of Fig. 1 since 2026-10-01)
SLATE, SLATE_TXT = "#6b7b8c", "#2b4a6f"
BRICK_TXT = "#1f2f3f"
FILL_TOP, FILL_MID, FILL_BOT = "#f2f5f9", "#f1e5bd", "#d3dbe4"
BAND_TXT = "#7a5c00"
CHIP, CHIP_TXT = "#2a7d4f", "#1b5233"
DIG, DIG_TXT = "#7a7f86", "#555a61"             # the digital reference (Simba)
CONTOUR = "#8c8c8c"
REF_LINE, REF_TXT = "#8d84a3", "#6f6684"
F1 = dict(title=11.5, region=10.0, band=8.6, ratio=9.6, chip=8.4, desc=8.0, legend=8.8,
          tick=10.0, axis=10.0, contour=8.0, tier=8.4)
S_LO, S_HI = 0.02, 40.0


def _phase_axes(ax, ss, lo, hi, cont, ylim, labels, zones, cont_frac=0.24):
    """Regions, boundaries and the 20% contour of one panel. zones:
    (top label xy in axes fraction, band label s, bottom label xy)."""
    ax.fill_between(ss, hi, 1e6, color=FILL_TOP, lw=0, zorder=0)
    ax.fill_between(ss, lo, hi, color=FILL_MID, lw=0, zorder=0)
    ax.fill_between(ss, 1e-6, lo, color=FILL_BOT, lw=0, zorder=0)
    ax.plot(ss, hi, "-", color=SLATE, lw=1.2, zorder=3)
    ax.plot(ss, lo, "-", color=SLATE, lw=1.2, zorder=3)
    ax.plot(ss, cont, ls=(0, (1.2, 2.2)), color=CONTOUR, lw=0.9, zorder=2)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(S_LO, S_HI); ax.set_ylim(*ylim)
    j = int(len(ss) * cont_frac)
    if ylim[0] < cont[j] < ylim[1]:
        on_band = lo[j] <= cont[j] <= hi[j]
        ax.text(ss[j], cont[j], "20%", fontsize=F1["contour"], color=CONTOUR, ha="center",
                va="center", rotation=_angle_along(ax, ss[j - 6], cont[j - 6], ss[j + 6], cont[j + 6]),
                rotation_mode="anchor", zorder=4,
                bbox=dict(fc=FILL_MID if on_band else FILL_TOP, ec="none", pad=0.6))
    (zc, zm, zk) = zones
    ax.text(*zc, labels[0], transform=ax.transAxes, fontsize=F1["region"], ha="center",
            va="center", color=SLATE_TXT, style="italic", zorder=6)
    m = int(np.searchsorted(ss, zm))
    ym = float(np.sqrt(lo[m] * hi[m]))
    ang = _angle_along(ax, ss[m - 8], float(np.sqrt(lo[m - 8] * hi[m - 8])),
                       ss[m + 8], float(np.sqrt(lo[m + 8] * hi[m + 8])))
    ax.text(zm, ym, labels[1], fontsize=F1["band"], ha="center", va="center", color=BAND_TXT,
            style="italic", rotation=ang, rotation_mode="anchor", zorder=6,
            bbox=dict(fc=FILL_MID, ec="none", alpha=0.9, pad=0.3))
    ax.text(*zk, labels[2], transform=ax.transAxes, fontsize=F1["region"], ha="right",
            va="bottom", color=BRICK_TXT, style="italic", zorder=6)
    ax.grid(alpha=0.09, which="both", lw=0.5, zorder=0)
    ax.tick_params(labelsize=F1["tick"])
    ax.set_xlabel("MVM row-processing rate $s = 1/t_{\\mathrm{row}}$ (Mrows/s)   "
                  "[faster silicon $\\rightarrow$]", fontsize=F1["axis"])
    ax.set_ylabel("link bandwidth, per direction (GB/s)", fontsize=F1["axis"])


def _envelope_arrow(ax, s, b_lo, b_hi, text, dx=1.18, ha="left", yfrac=0.5):
    ax.annotate("", xy=(s, b_hi), xytext=(s, b_lo),
                arrowprops=dict(arrowstyle="<|-|>", color=SLATE, lw=1.1, mutation_scale=9,
                                shrinkA=0, shrinkB=0), zorder=7)
    ax.text(s * dx, b_lo * (b_hi / b_lo) ** yfrac, text, fontsize=F1["ratio"], color=SLATE_TXT,
            ha=ha, va="center", zorder=8, linespacing=1.15)


def _desc(ax, text, xy=(0.015, 0.015)):
    ax.text(*xy, text, transform=ax.transAxes, fontsize=F1["desc"], va="bottom", ha="left",
            color="0.30", zorder=6, bbox=dict(fc="white", ec="0.82", lw=0.5, alpha=0.92, pad=1.6))


def fig1():
    SRC = ["analysis/v7/intradie_phase_curves.csv", "analysis/v7/phase_boundary_curves.csv",
           "analysis/v7/phase_projection_points.csv", "analysis/v7/phase_setup.json"]
    setup = json.load(open(os.path.join(V7, "phase_setup.json")))
    s_ref = setup["package"]["s_ref_mrows_per_s"]
    ic = read_csv(os.path.join(V7, "intradie_phase_curves.csv"))
    pb = read_csv(os.path.join(V7, "phase_boundary_curves.csv"))
    pts = read_csv(os.path.join(V7, "phase_projection_points.csv"))
    f = lambda rows, k: np.array([float(r[k]) for r in rows])
    ss_a, lo_a, hi_a, ct_a = (f(ic, k) for k in ("s_mrows_per_s", "B_minus_gbps", "B_plus_gbps",
                                                 "B_spread20_gbps"))
    ss_b, lo_b, hi_b, ct_b = (f(pb, k) for k in ("s_mrows_per_s", "B_minus_seven_rules_gbps",
                                                 "B_plus_seven_rules_gbps",
                                                 "B_spread20_seven_rules_gbps"))
    assert all(r["n_finite_seven_rules"] == "6" for r in pb), "a rate with a non-finite boundary"
    at = lambda ss, y: float(np.interp(s_ref, ss, y))
    env_a = (at(ss_a, lo_a), at(ss_a, hi_a)); env_b = (at(ss_b, lo_b), at(ss_b, hi_b))
    set_b = setup["package"]["candidate_set"]["seven_rules"]
    P = {(r["chip_key"], r["panel"], r["mode"], r["coordinate_kind"]): r for r in pts}

    def pt(key, panel, mode="", kind=None):
        for r in pts:
            if r["chip_key"] == key and r["panel"] == panel and r["mode"] == mode and \
                    (kind is None or kind in r["coordinate_kind"]):
                return float(r["s_mrows_per_s"]), float(r["B_gbps"])
        raise KeyError((key, panel, mode, kind))

    FIG_H = 4.6
    fig, axes = plt.subplots(1, 2, figsize=(12.8, FIG_H))
    fig.subplots_adjust(left=0.055, right=0.955, top=(FIG_H - 0.30) / FIG_H,
                        bottom=(5.0 * 0.275 - (5.0 - FIG_H)) / FIG_H, wspace=0.17)
    A, B = axes
    chip = dict(marker="D", ms=6.5, ls="none", zorder=8)
    pub = dict(mfc=CHIP, mec=CHIP_TXT, mew=0.9, **chip)
    der = dict(mfc="white", mec=CHIP, mew=1.2, **chip)
    dig = dict(marker="s", ms=6.0, mfc="white", mec=DIG, mew=1.2, ls="none", zorder=8)
    ev = dict(marker="o", ms=7, mfc="white", mec=CHIP, mew=1.5, ls="none", zorder=9)

    # ---------------- (a) intra-die
    _phase_axes(A, ss_a, lo_a, hi_a, ct_a, (1e-2, 1e3),
                ("communication masked", "mapping decides what is exposed",
                 "communication exposed\n(mapping sets how severe)"),
                ((0.20, 0.86), 3.5, (0.985, 0.05)))
    A.set_title("(a) Intra-die macro mapping", fontsize=F1["title"])
    s_arr = s_ref / 1.7
    _envelope_arrow(A, s_arr, float(np.interp(s_arr, ss_a, lo_a)), float(np.interp(s_arr, ss_a, hi_a)),
                    f"{env_a[1] / env_a[0]:.2f}\u00d7", dx=1 / 1.14, ha="right", yfrac=0.35)
    h4, h1 = pt("hermes", "a", "4-phase", "per-physical"), pt("hermes", "a", "1-phase", "per-physical")
    A.plot([h4[0], h1[0]], [0.4, 0.4], "-", color=CHIP, lw=1.0, zorder=7)
    A.plot([h1[0]], [h1[1]], **pub); A.plot([h4[0]], [h4[1]], **der)
    A.text(np.sqrt(h1[0] * h4[0]), 0.4 / 1.6, "HERMES, 0.4 GB/s\n4-phase (open) / 1-phase (filled)",
           fontsize=F1["chip"], color=CHIP_TXT, ha="center", va="top", zorder=8, linespacing=1.15)
    si = pt("isaac", "a"); A.plot([si[0]], [si[1]], **pub)
    A.text(si[0] * 1.14, si[1] / 1.35, f"ISAAC, {si[1]:.1f} GB/s", fontsize=F1["chip"],
           color=CHIP_TXT, ha="left", va="top", zorder=8)
    sb = pt("simba", "a"); A.plot([sb[0]], [sb[1]], **dig)
    A.text(sb[0] * 1.14, sb[1] / 1.3, f"Simba NoC (digital), {sb[1]:g} GB/s", fontsize=F1["chip"],
           color=DIG_TXT, ha="left", va="top", zorder=8)
    _desc(A, "latency object: one die's two co-resident operators\n"
             "(a sub-problem, not the whole model)\nP = all 70 joint macro seatings, enumerated")

    # ---------------- (b) package
    _phase_axes(B, ss_b, lo_b, hi_b, ct_b, (1e-2, 1e3),
                ("compute / fixed-cost\ndominated", "mapping decides which dominates",
                 "communication dominated\n(mapping sets how severe)"),
                ((0.22, 0.86), 3.0, (0.985, 0.05)), cont_frac=0.42)
    B.set_title("(b) Package-level die mapping", fontsize=F1["title"])
    # the two evaluated bandwidth tiers across device speeds, bracketed outside
    x_out = S_HI * 1.10
    for bw in (0.4, 12.5):
        B.plot([S_LO, S_HI * 1.16], [bw, bw], color=REF_LINE, lw=0.9, ls=(0, (4, 3)), alpha=0.75,
               zorder=6, clip_on=False)
        B.text(S_HI / 1.08, bw * 1.12, f"{bw:g} GB/s", fontsize=F1["tier"], color=REF_TXT,
               ha="right", va="bottom", zorder=9)
    B.annotate("", xy=(x_out, 12.5), xytext=(x_out, 0.4),
               arrowprops=dict(arrowstyle="<|-|>", color=SLATE, lw=1.1, mutation_scale=9,
                               shrinkA=0, shrinkB=0), zorder=6, annotation_clip=False)
    B.text(x_out * 1.11, np.sqrt(0.4 * 12.5), "Reference bandwidth span", fontsize=F1["band"],
           color=SLATE_TXT, ha="center", va="top", rotation=90, rotation_mode="anchor", zorder=9,
           clip_on=False)
    # the envelope at the reference rate, between the two NeuRRAM tiers
    s_arr = s_ref / 1.7
    _envelope_arrow(B, s_arr, float(np.interp(s_arr, ss_b, lo_b)), float(np.interp(s_arr, ss_b, hi_b)),
                    f"{env_b[1] / env_b[0]:.2f}\u00d7", dx=1 / 1.14, ha="right", yfrac=0.35)
    B.plot([s_ref, s_ref], [0.4, 12.5], "-", color=CHIP, lw=1.0, zorder=8)
    for bw, lab, up in ((0.4, "NeuRRAM, 0.4 GB/s", False), (12.5, "NeuRRAM, 12.5 GB/s", True)):
        B.plot([s_ref], [bw], **ev)
        B.text(s_ref, bw * 1.35 if up else bw / 1.35, lab, fontsize=F1["chip"],
               color=CHIP_TXT, ha="center", va="bottom" if up else "top", zorder=9)
    si = pt("isaac", "b"); B.plot([si[0]], [si[1]], **pub)
    B.text(si[0], si[1] / 1.8, f"ISAAC, {si[1]:g} GB/s", fontsize=F1["chip"],
           color=CHIP_TXT, ha="center", va="top", zorder=8)
    sm = pt("mythic_m1076", "b", kind="I/O-matched"); B.plot([sm[0]], [sm[1]], **der)
    B.text(sm[0] * 1.18, sm[1] / 1.45, f"M1076, {sm[1]:g} GB/s", fontsize=F1["chip"],
           color=CHIP_TXT, ha="left", va="center", zorder=8)
    sb1 = pt("simba", "b", kind="max mode"); sb2 = pt("simba", "b", kind="experiment mode")
    B.plot([sb1[0], sb2[0]], [sb1[1], sb2[1]], "-", color=DIG, lw=1.0, zorder=7)
    B.plot([sb1[0]], [sb1[1]], **dig); B.plot([sb2[0]], [sb2[1]], **dig)
    B.text(sb1[0] * 1.14, sb2[1] / 1.3, f"Simba (digital), {sb2[1]:g} / {sb1[1]:g} GB/s",
           fontsize=F1["chip"], color=DIG_TXT, ha="left", va="top", zorder=8)
    _desc(B, "latency object: whole-model serial prefill (Gemma-7B)\n"
             "P = five named rules + random_s0\nports at 2\u00d7 the link rate")

    # ---------------- legend: lines on the first row, markers on the second
    L = plt.Line2D
    keys = [L([], [], color=SLATE, lw=1.2), L([], [], ls=(0, (1.2, 2.2)), color=CONTOUR, lw=0.9),
            L([], [], ls=(0, (4, 3)), color=REF_LINE, lw=0.9, alpha=0.75),
            L([], [], **{k: v for k, v in pub.items() if k != "zorder"}),
            L([], [], **{k: v for k, v in der.items() if k != "zorder"}),
            L([], [], marker="o", ls="-", color=CHIP, mfc="white", mec=CHIP, mew=1.5, ms=7, lw=1.0),
            L([], [], **{k: v for k, v in dig.items() if k != "zorder"})]
    labs = ["boundaries B₋, B₊ over the mapping set", "mapping latency spread, 20%",
            "the two evaluated bandwidth tiers", "published parameter, projected",
            "derived or alternative-mode value", "configurations evaluated in this paper",
            "digital reference, projected the same way"]
    order = [0, 3, 1, 4, 2, 5, 6]
    fig.legend([keys[i] for i in order], [labs[i] for i in order], loc="lower center", ncol=4,
               fontsize=F1["legend"], frameon=False, bbox_to_anchor=(0.5, -0.012),
               labelspacing=0.45, columnspacing=2.0, handlelength=2.4, handletextpad=0.8)

    meta = {"panel_a": {"instance": setup["intra_die"]["instance"],
                        "B_minus_at_ref_gbps": env_a[0], "B_plus_at_ref_gbps": env_a[1],
                        "ratio": env_a[1] / env_a[0], "B_spread20_at_ref_gbps": at(ss_a, ct_a)},
            "panel_b": {"config_id": setup["package"]["config_id"],
                        "protocol_id": setup["package"]["protocol_id"],
                        "candidate_set_id": "seven_rules", "members": set_b["members"],
                        "failed": set_b["failed"], "B_minus_at_ref_gbps": env_b[0],
                        "B_plus_at_ref_gbps": env_b[1], "ratio": env_b[1] / env_b[0],
                        "B_spread20_at_ref_gbps": at(ss_b, ct_b),
                        "R_model": setup["package"]["R_model"], "N_s": setup["package"]["N_s"],
                        "F_s": setup["package"]["F_s"], "H_model": setup["package"]["H_model"],
                        "boundary_status_in_scan": "finite at all 122 rates for all 6 members"},
            "s_ref_mrows_per_s": s_ref,
            "projection_points_drawn": ["neurram a/b", "hermes a 1-phase/4-phase (per physical link)",
                                        "isaac a (c-mesh link) / b (off-chip link)",
                                        "mythic_m1076 b (I/O-matched projection)",
                                        "simba a (NoC link) / b (GRS max and experiment mode)"],
            "units": {"s": "Mrows/s (log)", "B": "GB/s per direction (log)"}}
    save(fig, "fig1_phase_diagram", composite=True, sources=SRC, meta=meta,
         note="(a) intra-die ffn die of the reference 2.7B account; (b) Gemma-7B package, "
              "six-layout set; type two points above the standing generator")
    dump_csv("fig1a_intradie_curves", ic, list(ic[0].keys()))
    dump_csv("fig1b_package_boundaries", [
        {k: r[k] for k in ("s_mrows_per_s", "t_row_us", "R_s", "B_minus_seven_rules_gbps",
                           "B_plus_seven_rules_gbps", "B_minus_seven_rules_rule",
                           "B_plus_seven_rules_rule", "B_spread20_seven_rules_gbps")} for r in pb],
        ["s_mrows_per_s", "t_row_us", "R_s", "B_minus_seven_rules_gbps", "B_plus_seven_rules_gbps",
         "B_minus_seven_rules_rule", "B_plus_seven_rules_rule", "B_spread20_seven_rules_gbps"])
    dump_csv("fig1_projection_points", [r for r in pts if r["s_mrows_per_s"]], list(pts[0].keys()))


# =====================================================================
# Fig. 2  the platform (a) and the resource-accounting example (b)
# =====================================================================
FIG2_TEXT = {
    # zones
    "Deployment configuration": "Topology-aware mapping",
    "User Configuration": "Inputs",
    "Deployment search": "Deployment exploration",
    # inputs
    ("Partition & placement", None): ("Layer groups, die &\nmacro mapping", "(\u03b3, \u03b1, \u03b2)"),
    ("Workload", "Model, sequence length"): ("Workload", "Model, phase, sequence length"),
    ("Operator tiling\n& dependencies", None): ("CIM capacity, encoding\n& legal tiling", "CiMLoop operator mapping"),
    ("Hardware &\nexecution settings", "routing, device, execution mode"):
        ("Digital units, KV,\ntopology & routing", "resources, workspace, execution"),
    # core
    ("Extract logical transfers", "Sources, destinations, volumes"):
        ("Extract logical transfers", "broadcast, reduction, hetero. hand-offs"),
    ("Route & accumulate loads", "Fixed routing; link & port loads"):
        ("Route & accumulate loads", "links, CIM ports, digital interfaces"),
    ("Compute, write\n& digital costs", None): ("CIM, digital attention\n& KV costs  (R)", None),
    ("Communication costs", "Service bounds & comm. energy"):
        ("Communication costs  (H)", "service times + propagation"),
    ("Aggregate execution costs", "Comp\u2013comm overlap;\nserial hand-offs"):
        ("Aggregate execution costs", "die: overlap; package: serial"),
    # phase analysis / search
    ("Extract phase\nboundaries", None): ("Boundaries, regions\n& envelopes", None),
    ("Partition &\ngroup sizing (DP)", None): ("Layer grouping &\nresources (DP)", None),
    ("Die placement (SA) &\nMacro assignment", None): ("Die mapping (SA) &\nmacro assignment", None),
}
FIG2_EDGE_TEXT = {"Updated deployment": "Updated mapping"}


def _fig2a_spec_v3():
    """The hand-drawn Fig. 2(a) layout of the v2 set with the wording of the
    v3 outline (mapping terminology, R / H branches, the inputs the platform
    takes, the three exploration levels)."""
    S = _FIG2A_SPEC_V2()
    for z in S["zones"]:
        z["title"] = FIG2_TEXT.get(z["title"], z["title"])
    for b in S["boxes"]:
        k = (b["title"], b["sub"])
        if k in FIG2_TEXT:
            b["title"], b["sub"] = FIG2_TEXT[k]
    for e in S["edges"]:
        if "label" in e:
            s_, x, y = e["label"]
            e["label"] = (FIG2_EDGE_TEXT.get(s_, s_), x, y)
    return S


_FIG2A_SPEC_V2 = None


def fig2():
    global _FIG2A_SPEC_V2
    from scripts import plot_dac2027_v2 as V2
    _FIG2A_SPEC_V2 = V2._fig2a_spec                 # the v2 layout, before the module is patched
    V2._fig2a_spec = _fig2a_spec_v3                 # the drawers read the spec through the module
    V2.LOAD_BR = LOAD_BR_V3                         # the (b) and (c) lanes and bars on the v3 ramp
    I = V2._fig2_instance()
    XC, WC = 5.22 + 2.32 + 0.16, 1.90                 # (c) right of (b)
    Wt, Ht = XC + WC, 3.00
    fig = plt.figure(figsize=(Wt, Ht))
    axa = V2._inch_axes(fig, [0, 0, 5.02 / Wt, 1], 5.02, Ht); V2._fig2a(axa)
    axb = V2._inch_axes(fig, [5.22 / Wt, 0, 2.32 / Wt, 1], 2.32, Ht); V2._fig2b(axb, I)
    for tx in axb.texts:                              # (b) and (c) titles in the other figures' style
        if tx.get_text() == "RESOURCE ACCOUNTING":
            tx.set_text(FIG2B_TITLE); tx.set_fontsize(FS2_TITLE); tx.set_fontweight("normal"); tx.set_x(0.02)
            tx.set_color("black")
        elif "transfers" in tx.get_text():            # the instance line: lower and a step larger
            tx.set_fontsize(FS2_SUB); tx.set_y(tx.get_position()[1] - 0.06)
        elif tx.get_fontweight() == "bold" and len(tx.get_text()) == 2:   # the node labels
            tx.set_fontsize(FS2_NODE)
        elif tx.get_fontsize() < FS2_TITLE:           # every other in-panel label at the instance line's size
            tx.set_fontsize(FS2_SUB)
    for ch in axb.child_axes:
        ch.tick_params(labelsize=FS2_SUB)
        ch.xaxis.label.set_fontsize(FS2_SUB); ch.yaxis.label.set_fontsize(FS2_SUB)
        ch.title.set_fontsize(FS2_SUB)
        for tx in ch.texts:
            tx.set_fontsize(FS2_SUB)
        if len(ch.patches) > 5:                       # the service-time profile: a shorter y axis, bars beneath the spines
            ch.set_ylim(0, 24.0)
            for pt in ch.patches:
                pt.set_zorder(2)
            bb = ch.get_position()                    # and flatter: 78 % of its height, the x axis where it was
            ch.set_axes_locator(None)                 # an inset axes re-applies its locator at draw time
            ch.set_position([bb.x0, bb.y0, bb.width, bb.height * 0.78])
    axc = V2._inch_axes(fig, [XC / Wt, 0, WC / Wt, 1], WC, Ht)
    _gemma_panel(axc, WC, Ht, FIG2C_TITLE, title_x=0.02, title_y=0.02, y_bars=0.172)   # as (b)'s
    rend = fig.canvas.get_renderer(); fig.canvas.draw()          # verify: the two bar charts' x axes on one line
    prof = next(ch for ch in axb.child_axes if len(ch.patches) > 5)
    bars = next(ch for ch in axc.child_axes if 0 < len(ch.patches) < 5)
    ax_y0 = lambda a_: a_.get_window_extent(rend).y0 / fig.dpi
    assert abs(ax_y0(bars) - ax_y0(prof)) < 0.005, (ax_y0(bars), ax_y0(prof))
    lab_y0 = lambda a_: a_.xaxis.label.get_window_extent(rend).y0 / fig.dpi
    prof.xaxis.labelpad += (lab_y0(prof) - lab_y0(bars)) * 72     # (b)'s title pad grown so its bottom meets (c)'s
    fig.canvas.draw()
    assert abs(lab_y0(bars) - lab_y0(prof)) < 0.005, (lab_y0(bars), lab_y0(prof))
    # both bar charts raised so their x titles' bottoms sit on panel (a)'s lowest ink
    a_bottom = min(art.get_window_extent(rend).y0 for art in axa.lines + axa.patches + axa.texts
                   if art.get_visible()) / fig.dpi
    dy = (a_bottom - lab_y0(prof)) / Ht
    for ch in (prof, bars):
        bb = ch.get_position(); ch.set_axes_locator(None)
        ch.set_position([bb.x0, bb.y0 + dy, bb.width, bb.height])
    for tx in axc.texts:                              # the summary line above (c)'s bars moves with them
        if tx.get_text().startswith("Stage communication"):
            tx.set_y(tx.get_position()[1] + dy * Ht)
    fig.canvas.draw()
    assert abs(lab_y0(prof) - a_bottom) < 0.005 and abs(lab_y0(bars) - a_bottom) < 0.005, (lab_y0(prof), lab_y0(bars), a_bottom)
    print(f"   bar-chart x axes: (b) {ax_y0(prof):.3f} in, (c) {ax_y0(bars):.3f} in; "
          f"x titles' bottoms: (b) {lab_y0(prof):.3f} in, (c) {lab_y0(bars):.3f} in; (a) bottom {a_bottom:.3f} in")
    yl = (Ht - 0.02) / Ht
    fig.text(0.006, yl, "(a) Platform", fontsize=FS2_TITLE, va="top")
    save(fig, "fig2_platform", composite=True,
         sources=["scripts/plot_dac2027_v2.py", "scripts/search_eval.py", "scripts/interconnect.py"],
         meta={"panel_a": "schematic, the v2 hand-drawn layout with the v3 wording",
               "panel_b": {"instance": "FFN1 -> FFN2 hand-off of the reference 2.7B mapping on a "
                                       "4x4 die mesh, compact fill; evaluated by search_eval",
                           "busiest_link_ms": I["score"]["busiest_service_ms"] if "busiest_service_ms"
                           in I["score"] else None}},
         note="(b) keeps the v2 FFN 4x4 example (the plan's default)")
    f = plt.figure(figsize=(5.02, 3.00)); a = V2._inch_axes(f, [0, 0, 1, 1], 5.02, 3.00); V2._fig2a(a)
    save(f, "fig2a_platform", sources=["scripts/plot_dac2027_v2.py"])
    V2._fig2a_drawio(os.path.join(OUT["panels"], "fig2a_platform.drawio"))
    print("   panels/fig2a_platform.drawio")


def _gemma_handoff():
    """One hand-off of the Gemma-7B main instance (layer 0, QKV -> attention
    unit) from the v7 pipeline example: flows, accumulated link loads and the
    stage's resource records."""
    import re
    ex = json.load(open(os.path.join(V7, "pipeline_example.json")))
    stage = next(s for s in ex["stages_layer"] if s["stage"] == "qkv->unit")
    flows = [r for r in read_csv(os.path.join(V7, "example_flows.csv")) if r["into"] == stage["into"]]
    loads = [r for r in read_csv(os.path.join(V7, "example_resource_loads.csv")) if r["into"] == stage["into"]]
    B = float(ex["resources"]["mesh link"].split()[0]) * 1e9
    wpf = float(flows[0]["payload_words"])
    seg_re = re.compile(r"mesh:seg\((\d+), (\d+)\)-\((\d+), (\d+)\)([+-])")
    link = {}
    for f in flows:
        for m in seg_re.finditer(f["route_xy"]):
            k = (int(m[1]), int(m[2]), int(m[3]), int(m[4]), m[5])
            link[k] = link.get(k, 0.0) + wpf
    # the merge structure read off the routes (checked against the record):
    # south column Q1 + Q2 + Q3 share (17,15)-(17,16)-(17,17) into U = e*;
    # north column: Q6 joins Q5's column at Q5, then Q4 joins; all three
    # share (17,21)...(17,17) into U (a tie with e* at 3 flows)
    hot_words = max(link.values())
    assert int(round(hot_words / wpf)) == 3 and sum(1 for w in link.values() if w == hot_words) >= 2
    kinds = ["mesh link", "die port", "hub port"]
    best = {k: max(float(x["service_s"]) for x in loads if x["resource_kind"] == k) * 1e3 for k in kinds}
    return dict(ex=ex, stage=stage, flows=flows, B=B, wpf=wpf, link=link, hot_words=hot_words,
                n_hot=int(round(hot_words / wpf)), best=best)


def _gemma_panel(ax, W, H, title, title_x=0.02, title_y=0.06, y_bars=None):
    """The hand-off as a routing schematic in the Fig. 2(b) idiom (roads
    with a dark rim filled by the load ramp, white nodes with black labels,
    the digital unit hatched), laid out horizontally: the unit in the
    middle, the QKV producers to its left and right, the busiest lane
    (e*) between the right junction and the unit; the stage's three
    resource classes as bars. y_bars: inch height of the bar chart's x axis
    (the composite aligns it with panel (b)'s profile axis)."""
    from scripts import plot_dac2027_v2 as V2
    from matplotlib.patches import Circle, FancyBboxPatch, Polygon
    from matplotlib.colors import Normalize
    G = _gemma_handoff()
    B, wpf, link, best, stage = G["B"], G["wpf"], G["link"], G["best"], G["stage"]
    TXT, EDGE = "#24313c", "#2b2f33"
    CM = V2.LOAD_BR; vmax = G["hot_words"] / B * 1e3; norm = Normalize(0, vmax)
    LANE, RIM, NODE_LW, FS_N = 4.9, 0.4, 0.85, FS2_NODE   # the lanes and node edges of panel (b)
    ax.text(title_x, H - title_y, title, fontsize=FS2_TITLE, color="black", ha="left", va="top")
    ax.text(title_x - 0.015, H - title_y - 0.19, f"Gemma-7B: QKV → attention unit · {len(G['flows'])} dies",
            fontsize=FS2_SUB, color=TXT, ha="left", va="top")
    # the vertical layout of the earlier version, turned a quarter turn counter-clockwise about the unit:
    # (dx, dy) -> (-dy, dx); L1 = one plain route, two for a shortened one
    L1, r = 0.30, 0.15                               # fills the panel width: Q6 / Q5 at the bars' left edge, Q1 at the right
    top = 1.556 + 2 * 0.47 + 0.144                   # (b)'s top node row (its mesh origin, pitch and node radius)
    U = (0.04 + 2 * L1 + r, top - L1 - r)
    R = lambda dx, dy: (U[0] - dy, U[1] + dx)
    Js, Jn = R(0, -L1), R(0, L1)                       # the junctions: right and left of the unit
    Q = {1: R(0, -3 * L1), 2: R(L1, -L1), 3: R(-2 * L1, -L1), 4: R(-L1, L1), 5: R(0, 2 * L1), 6: R(-2 * L1, 2 * L1)}
    hj = (LANE / 2 + RIM) / 72                        # half-size of a junction square, inches

    def road(p0, p1, n, brk=False, trim0=0.0, trim1=0.0):
        """A lane from p0 to p1 (trimmed by the junction half-size where it
        meets one); a shortened route carries a dotted ellipsis mid-way."""
        fill = CM(norm(n * wpf / B * 1e3))
        v = np.array(p1) - np.array(p0); u = v / np.hypot(*v)
        a = np.array(p0) + u * trim0; b = np.array(p1) - u * trim1
        ax.plot([a[0], b[0]], [a[1], b[1]], color=EDGE, lw=LANE + 2 * RIM, solid_capstyle="butt", zorder=2)
        ax.plot([a[0], b[0]], [a[1], b[1]], color=fill, lw=LANE, solid_capstyle="butt", zorder=3)
        if brk:
            m = (a + b) / 2
            g = 0.05
            ax.plot([m[0] - u[0] * g, m[0] + u[0] * g], [m[1] - u[1] * g, m[1] + u[1] * g],
                    color="white", lw=LANE + 2 * RIM + 0.8, solid_capstyle="butt", zorder=4)
            for d in (-0.024, 0.0, 0.024):
                ax.plot([m[0] + u[0] * d], [m[1] + u[1] * d], marker="o", ms=0.6, color=EDGE,
                        ls="none", zorder=5)

    def junction(J, arms):
        """Each side arm's colour fills its quadrant of the junction square
        (through lanes drawn untrimmed, so a T shows no seam); the arm names
        are those of the vertical layout, turned with it."""
        dirs = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}
        for name, n in arms.items():
            dx, dy = dirs[name]; px, py = -dy, dx
            c1 = (J[0] + hj * (dx + px), J[1] + hj * (dy + py))
            c2 = (J[0] + hj * (dx - px), J[1] + hj * (dy - py))
            ax.add_patch(Polygon([J, c1, c2], closed=True, fc=CM(norm(n * wpf / B * 1e3)), ec="none",
                                 zorder=3.5))
    road(Q[1], Js, 1, brk=True, trim1=hj); road(Q[2], Js, 1, trim1=hj); road(Q[3], Js, 1, brk=True, trim1=hj)
    road(Q[6], Q[5], 1, brk=True); road(Q[4], Jn, 1, trim1=hj)
    road(Q[5], Jn, 2)                                 # through lanes at the T: untrimmed
    road(Js, U, 3, trim0=hj); road(Jn, U, 3)
    junction(Js, {"down": 1, "right": 1, "left": 1, "up": 3})
    junction(Jn, {"left": 1})
    for k, (x, y) in Q.items():
        rs = 0.92 * r
        ax.add_patch(FancyBboxPatch((x - rs, y - rs), 2 * rs, 2 * rs, boxstyle="round,pad=0,rounding_size=0.035",
                                    fc="white", ec=EDGE, lw=NODE_LW, zorder=6))
        ax.text(x, y, f"Q{k}", fontsize=FS_N, color="black", ha="center", va="center_baseline",
                fontweight="bold", zorder=7)
    # the digital unit: white with a fine dense hatch (the hatch takes the patch's edge colour)
    ax.add_patch(Circle(U, r, fc="white", ec="#a3adb5", lw=0, hatch="//////////", zorder=6))
    ax.add_patch(Circle(U, r, fc="none", ec=EDGE, lw=NODE_LW, zorder=6.2))
    ax.text(U[0], U[1], "U", fontsize=FS_N, color="black", ha="center", va="center_baseline",
            fontweight="bold", zorder=7, bbox=dict(fc="white", ec="none", pad=0.4))
    ax.text(U[0] + 0.08, U[1] + r + 0.025, f"e* · {G['n_hot']} flows\n{G['hot_words'] / 1e6:.1f} M words",
            fontsize=FS2_SUB, color=TXT, ha="right", va="bottom", linespacing=1.15, zorder=9)
    # the ramp, horizontal beneath the schematic
    y_lo = min(y for _, y in Q.values()) - r
    cb_w, cb_h = 0.64, 0.076                          # (b)'s colour bar, turned
    cb_x = 0.04                                       # left-aligned with the schematic
    cbx = ax.inset_axes((cb_x, y_lo - 0.16 - cb_h, cb_w, cb_h), transform=ax.transData)
    vals = np.linspace(0, vmax, 512)
    cbx.imshow(CM(norm(vals))[None, :, :], origin="lower", aspect="auto", extent=(0, vmax, 0, 1),
               interpolation="nearest")
    cbx.set_xlim(0, vmax); cbx.set_ylim(0, 1); cbx.set_yticks([])
    cbx.set_xticks([0, vmax / 3, 2 * vmax / 3, vmax])
    cbx.set_xticklabels(["0", f"{vmax / 3:.1f}", f"{2 * vmax / 3:.1f}", f"{vmax:.1f}"])
    cbx.tick_params(labelsize=FS2_SUB, length=1.5, pad=1, width=0.5, colors=TXT)
    for sp in cbx.spines.values():
        sp.set_linewidth(0.4)
    ax.text(cb_x + cb_w + 0.05, y_lo - 0.16 - cb_h / 2, "ms", fontsize=FS2_SUB, color=TXT, ha="left", va="center")
    x_right = Q[1][0] + 0.92 * r                      # the bars' right edge: the schematic's
    # one summary line, then the stage's three resource classes on the same ramp
    kinds = ["mesh link", "die port", "hub port"]
    hb = 3 * 0.129                                    # three rows at (b)'s bar pitch
    y_b = y_bars if y_bars is not None else 0.172     # the x axis on (b)'s profile axis
    y_f = y_b + hb + 0.16
    ax.text(0.02, y_f, f"Stage communication: {stage['stage_H_s'] * 1e3:.2f} ms", fontsize=FS2_SUB,
            color=TXT, ha="left", va="top")
    bx = ax.inset_axes((0.68, y_b, x_right - 0.68 - 0.24, hb), transform=ax.transData)   # the value labels end at the schematic's right edge
    ys = [2, 1, 0]
    bx.barh(ys, [best[k] for k in kinds], color=[CM(norm(best[k])) for k in kinds], height=0.74, zorder=2)
    for y, k in zip(ys, kinds):
        bx.text(best[k] + 0.15, y, f"{best[k]:.2f} ms", fontsize=5.4, color=TXT, va="center")
    bx.set_yticks(ys); bx.set_yticklabels(["Busiest link", "CIM die port", "Digital interface"], fontsize=5.4)
    bx.set_xlim(0, 8.6); bx.set_xticks([0, 4, 8])
    bx.tick_params(labelsize=FS2_SUB, length=1.5, pad=1.5, width=0.5, colors=TXT)
    bx.tick_params(axis="y", labelsize=5.4)           # the row names a step smaller than the values
    bx.set_xlabel("Service time (ms)", fontsize=FS2_SUB, labelpad=1.5, color=TXT)
    for sp_ in ("top", "right"):
        bx.spines[sp_].set_visible(False)
    for sp_ in ("left", "bottom"):
        bx.spines[sp_].set_linewidth(0.5)
    bx.set_facecolor("none")
    return G


def fig2b_gemma():
    """Standalone export of the Gemma hand-off panel (Fig. 2(c) in the composite)."""
    from scripts import plot_dac2027_v2 as V2
    SRC = ["analysis/v7/pipeline_example.json", "analysis/v7/example_flows.csv",
           "analysis/v7/example_resource_loads.csv"]
    W, H = 2.32, 3.00
    fig = plt.figure(figsize=(W, H)); ax = V2._inch_axes(fig, [0, 0, 1, 1], W, H)
    G = _gemma_panel(ax, W, H, FIG2C_TITLE)
    save(fig, "fig2c_gemma_handoff", sources=SRC,
         meta={"config_id": G["ex"]["config_id"], "layer": G["ex"]["layer_shown"], "stage": G["stage"],
               "geometry": "schematic (merge structure from the recorded XY routes)",
               "busiest_links_3_flows": [list(k) for k, w in G["link"].items() if w == G["hot_words"]],
               "resource_max_ms": G["best"]},
         note="Fig. 2(c): one hand-off of the Gemma main instance, schematic routing")
    dump_csv("fig2c_gemma_links", [{"x0": k[0], "y0": k[1], "x1": k[2], "y1": k[3], "dir": k[4],
                                    "words": w, "service_ms": w / G["B"] * 1e3} for k, w in G["link"].items()],
             ["x0", "y0", "x1", "y1", "dir", "words", "service_ms"])


FIG2B_TITLE, FIG2C_TITLE = "(b) Link loads", "(c) Heterogeneous hand-off"
# the load ramp of Figs 2 and 4: the cold end midway between the card's deep (70,96,173) and light (104,180,206)
# blues, white at the port bound, the Fig. 4 hot end
LOAD_BR_V3 = matplotlib.colors.LinearSegmentedColormap.from_list(
    "isobar_load_br_v3", [(pos, (r_ / 255, g_ / 255, b_ / 255)) for pos, (r_, g_, b_) in
                          ((0.00, (87, 138, 190)), (0.20, (150, 198, 220)), (0.36, (200, 225, 236)),
                           (0.50, (233, 241, 244)),                             # white exactly at the centre
                           (0.62, (247, 203, 180)), (0.74, (246, 178, 147)), (0.86, (220, 109, 87)),
                           (0.94, (183, 34, 48)), (1.00, (150, 20, 40)))])
FS2_TITLE = 8.0                                        # the 9.56 in figure prints at x0.75: 6 pt, like the other figures
FS2_SUB = 6.4                                          # the instance lines under the (b) / (c) titles
FS2_NODE = 6.8                                         # the node labels of (b) and (c)


# =====================================================================
# Fig. 3  validation (top row) and evaluation / exploration cost (bottom
# row): a 2x2 grid inside one column
# =====================================================================
# the v2 Fig. 6 scale as printed (its 8 / 8 / 7.5 / 6.5 / 5.5 pt at 4.78 in, scaled to the 3.5 in column)
FS3 = {"title": 6.0, "axis": 6.0, "tick": 5.5, "small": 4.8, "tiny": 4.0}
INK = "#333333"
GREY = "#8c8c8c"
# the Fig. 3 card colours: light blue / green / yellow, each darkened 8%
F3 = dict(meas="#68b4ce", bound="#a5c582", est="#f3de67", search="#68b4ce",
          search_txt="#3f7f93", cand="#a5c582", full="#68b4ce", incr="#a5c582", rep="#f3de67", rep_txt="#a8963a")
MODEL3 = {"ref2p7b": "2.7B ref.", "opt6.7b": "OPT-6.7B", "gemma7b": "Gemma-7B", "opt13b": "OPT-13B"}
TRAJ3 = {"2.7B ref.": "#f3de67", "OPT-6.7B": "#68b4ce", "Gemma-7B": "#4660ad", "OPT-13B": "#a5c582"}
TRAJ3_TXT = {"2.7B ref.": "#a8963a", "OPT-6.7B": "#3f7f93", "Gemma-7B": "#34488a", "OPT-13B": "#6f8f52"}


def _tidy(ax, grid="both"):
    for s_ in ("top", "right"):
        ax.spines[s_].set_visible(False)
    for s_ in ("left", "bottom"):
        ax.spines[s_].set_linewidth(0.6)
    ax.tick_params(labelsize=FS3["tick"], length=2.0, pad=1.5, width=0.6)
    if grid:
        ax.grid(alpha=0.16, lw=0.5, axis=grid)
        ax.set_axisbelow(True)


def _title3(ax, s):
    ax.set_title(s, fontsize=FS3["title"], loc="left", pad=4.8)


def _seating_glyph(ax, rect, seating, caption):
    """A 6x6 chiplet grid with the four seated chiplets filled (axes-fraction rect)."""
    from matplotlib.patches import Rectangle
    g = ax.inset_axes(rect)
    n = 6
    for i in range(n):
        for j in range(n):
            g.add_patch(Rectangle((i, j), 1, 1, fc="white", ec="0.72", lw=0.3))
    for (i, j) in seating:
        g.add_patch(Rectangle((i + 0.1, j + 0.1), 0.8, 0.8, fc=F3["meas"], ec="none"))
    g.set_xlim(0, n); g.set_ylim(0, n); g.set_aspect("equal"); g.axis("off")
    g.text(n / 2, n + 0.4, caption, fontsize=FS3["tiny"], color=INK, ha="center", va="bottom",
           linespacing=1.1)
    return g


def _fig3a(ax):
    """(a) Simba T1: five seatings of four chiplets; each series relative to
    its own adjacent seating; the two end seatings drawn under the curves."""
    rows = read_csv(os.path.join(V7, "silicon_reference.csv"))
    x = np.arange(len(rows))
    hops = [float(r["longest_pair_hops"]) for r in rows]
    meas = [float(r["measured_norm"]) for r in rows]
    lo = [float(r["bound_series_norm"]) for r in rows]
    est = [float(r["protocol_series_norm"]) for r in rows]
    ax.plot(x, meas, marker="s", ms=3.2, color=F3["meas"], ls="none", label="Measured", zorder=5)
    ax.plot(x, lo, marker="o", ms=3.6, lw=1.1, color=F3["bound"], label="Resource bound", zorder=4)
    ax.plot(x, est, marker="D", ms=3.0, mew=1.0, lw=1.3, ls="--", color=F3["est"], mfc="white",
            label="Protocol est.", zorder=4)
    ax.annotate(f"{meas[-1]:.2f}×\n{est[-1]:.2f}×", (x[-1], meas[-1]), textcoords="offset points",
                xytext=(-5, 1), ha="right", va="top", fontsize=FS3["small"], color=INK, linespacing=1.15)
    ax.annotate(f"{lo[-1]:.3f}×", (x[-1], lo[-1]), textcoords="offset points", xytext=(-4, -4),
                ha="right", va="top", fontsize=FS3["small"], color=INK)
    seat = lambda r: json.loads(r["seating_chiplets_xy"])
    gw = 0.10; gh = gw * 1.27 / 1.00                   # one 6x6 glyph, axes fraction (square in inches)
    _seating_glyph(ax, [0.60, 0.175, gw, gh], seat(rows[0]), f"adjacent\n{hops[0]:g} hops")
    _seating_glyph(ax, [0.83, 0.175, gw, gh], seat(rows[-1]), f"corners\n{hops[-1]:g} hops")
    ax.annotate("", xy=(0.825, 0.175 + gh / 2), xytext=(0.705, 0.175 + gh / 2), xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=0.6, mutation_scale=6))
    ax.set_xticks(x); ax.set_xticklabels([f"{h:g}" for h in hops])
    ax.set_xlim(-0.35, len(x) - 0.65); ax.set_ylim(0.72, 2.75); ax.set_yticks([1.0, 1.5, 2.0, 2.5])
    ax.set_xlabel("Longest distance (hops)", fontsize=FS3["axis"], labelpad=1.5)
    ax.set_ylabel("Relative latency", fontsize=FS3["axis"], labelpad=2)
    _title3(ax, "(a) Silicon reference")
    ax.legend(fontsize=FS3["tiny"], loc="upper left", frameon=False, labelspacing=0.25,
              handlelength=1.8, handletextpad=0.4, borderaxespad=0.1, markerscale=0.8)
    _tidy(ax, grid="y")
    return rows


# workload colours (the card): light blue / yellow / green, one marker shape each
OFFLOAD_LIBS = [("offload6x6", "Prefill", "o", "#68b4ce"), ("offload_decode6x6", "Decode", "s", "#f3de67"),
                ("offload2_8x8", "2 layers", "^", "#a5c582")]


def _fig3b(ax):
    """(b) The three offload BookSim libraries: analytic cost against BookSim
    completion time, both relative to the library's default fill in each
    evaluator; full-objective search endpoints emphasised. Inset: BookSim
    completion time over the analytic lower bound, per candidate."""
    cand = read_csv(os.path.join(V7, "booksim_candidate_costs.csv"))
    summ = {r["scenario_id"]: r for r in read_csv(os.path.join(V7, "booksim_library_summary.csv"))}
    ms = {"o": 2.6, "s": 2.3, "^": 2.9}
    hs, ls_ = [], []
    lim = (0.28, 1.2)
    ax.plot(lim, lim, color="0.6", lw=0.7, ls=(0, (4, 3)), zorder=2)
    libs = {}
    for sid, name, mk, col in OFFLOAD_LIBS:
        rs = [r for r in cand if r["scenario_id"] == sid]
        assert len(rs) == int(summ[sid]["n_candidates"])
        libs[sid] = rs
        ends = [r for r in rs if r["candidate_class"] == "search endpoint (full)"]
        rest = [r for r in rs if r["candidate_class"] != "search endpoint (full)"]
        xa = lambda R: [float(r["analytic_normalized"]) for r in R]
        yb = lambda R: [float(r["booksim_normalized"]) for r in R]
        ax.plot(xa(rest), yb(rest), marker=mk, ms=ms[mk], ls="none", color=col, alpha=0.6, mec="none", zorder=3)
        ax.plot(xa(ends), yb(ends), marker=mk, ms=ms[mk] + 0.5, ls="none", mfc=col, mec=INK, mew=0.4, zorder=5)
        hs.append(plt.Line2D([], [], marker=mk, ms=ms[mk] + 0.9, ls="none", color=col, alpha=0.75, mec="none"))
        ls_.append(f"{name}  ρ = {float(summ[sid]['spearman_A_full_vs_booksim']):.3f}")
    hs.append(plt.Line2D([], [], marker="o", ms=3.6, ls="none", mfc="white", mec=INK, mew=0.4))
    ls_.append("Search endpoints (ringed)")
    ax.set_xlim(*lim); ax.set_ylim(*lim)
    ax.set_xticks([0.4, 0.8, 1.2]); ax.set_yticks([0.4, 0.8, 1.2])
    ax.set_xlabel("Analytic cost (rel.)", fontsize=FS3["axis"], labelpad=1.5)
    ax.set_ylabel("BookSim time (rel.)", fontsize=FS3["axis"], labelpad=2)
    _title3(ax, "(b) BookSim validation")
    ax.legend(hs, ls_, fontsize=FS3["tiny"], loc="upper left", frameon=False, labelspacing=0.25,
              handletextpad=0.3, borderaxespad=0.1, handlelength=1.0)
    _tidy(ax)
    # inset: how far above the analytic lower bound BookSim completes
    ins = ax.inset_axes([0.63, 0.10, 0.35, 0.24])
    allv = []
    for k, (sid, name, mk, col) in enumerate(OFFLOAD_LIBS):
        v = np.array([float(r["booksim_over_bound"]) for r in libs[sid]]); allv += list(v)
        y = 2 - k
        jit = (np.random.default_rng(k).random(len(v)) - 0.5) * 0.45
        ins.plot(v, y + jit, marker=mk, ms=1.7, ls="none", color=col, alpha=0.6, mew=0, zorder=3)
        ins.plot([np.median(v)] * 2, [y - 0.36, y + 0.36], color=INK, lw=0.8, zorder=4)
    ins.set_xlim(0.98, 1.52); ins.set_ylim(-0.6, 2.6)
    ins.set_xticks([1.0, 1.25, 1.5]); ins.set_xticklabels(["1", "1.25", "1.5"]); ins.set_yticks([])
    ins.tick_params(labelsize=FS3["tiny"], length=1.5, pad=1, width=0.5)
    for s_ in ("top", "right", "left"):
        ins.spines[s_].set_visible(False)
    ins.spines["bottom"].set_linewidth(0.5)
    ins.set_facecolor("none")
    ins.set_title("BookSim / bound", fontsize=FS3["tiny"],
                  color=INK, pad=1.5)
    return cand, summ


def _runtime3():
    rt = sorted(read_csv(os.path.join(V7, "runtime_summary.csv")), key=lambda r: int(r["n_dies"]))
    samp = read_csv(os.path.join(V7, "runtime_samples.csv"))
    for r in rt:
        r["model"] = MODEL3[r["config_id"].split("_")[0]]
        rep = [float(s["repricing_per_candidate_s"]) for s in samp
               if s["config_id"] == r["config_id"] and s["repricing_per_candidate_s"]]
        r["repricing_p10_s"], r["repricing_p90_s"] = np.percentile(rep, 10), np.percentile(rep, 90)
    return rt


def _fig3c(axm, axr, rt):
    """(c) Per-call cost, one row per configuration: full evaluation and
    incremental update as a connected pair on a log ms axis with the speed-up
    between them; fixed-layout repricing in its own narrow axis in us."""
    y = np.arange(len(rt))[::-1]                      # first configuration on top
    full = np.array([float(r["full_eval_median_s"]) * 1e3 for r in rt])
    inc = np.array([float(r["incremental_median_s"]) * 1e3 for r in rt])
    rep = np.array([float(r["repricing_per_candidate_median_s"]) * 1e6 for r in rt])
    axm.hlines(y, inc, full, color="0.72", lw=0.8, zorder=2)
    axm.plot(full, y, marker="o", ms=3.6, ls="none", color=F3["full"], label="Full", zorder=4)
    axm.plot(inc, y, marker="s", ms=3.2, ls="none", color=F3["incr"], label="Incremental", zorder=4)
    for y_, f_, i_, r in zip(y, full, inc, rt):
        axm.text(np.sqrt(f_ * i_), y_ + 0.17, f"{float(r['full_over_incremental_speedup']):.0f}×",
                 fontsize=FS3["small"], color=INK, ha="center", va="bottom")
    axm.set_xscale("log"); axm.set_xlim(0.5, 2000)
    axm.set_xticks([1, 10, 100, 1000]); axm.set_xticklabels(["1", "10", "100", ""])   # no "1000" against the us axis
    axm.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    axm.set_ylim(-0.75, len(rt) - 0.35)
    axm.set_yticks(y); axm.set_yticklabels([r["n_dies"] for r in rt], fontsize=FS3["small"])
    axm.set_xlabel("Time per call (ms)", fontsize=FS3["axis"], labelpad=1.5)
    axm.set_ylabel("Occupied CIM dies", fontsize=FS3["axis"], labelpad=2)
    _title3(axm, "(c) Evaluation cost")
    axm.legend(fontsize=FS3["tiny"], loc="lower left", frameon=False, labelspacing=0.2, handlelength=1.0,
               handletextpad=0.3, borderaxespad=0.1)
    _tidy(axm, grid="x")
    axm.tick_params(axis="y", labelsize=FS3["small"])   # die counts a size down
    # fixed-layout repricing: its own narrow axis, rows aligned
    axr.plot(rep, y, marker="D", ms=3.0, ls="none", color=F3["rep"], zorder=4)
    axr.set_xlim(0, 40); axr.set_xticks([0, 20, 40])
    axr.set_ylim(axm.get_ylim()); axr.set_yticks(y); axr.set_yticklabels([])
    axr.set_xlabel("μs", fontsize=FS3["axis"], labelpad=1.5)
    axr.text(20, len(rt) - 0.55, "Repricing", fontsize=FS3["tiny"], color=F3["rep_txt"], ha="center", va="center")
    _tidy(axr, grid="x")
    axr.tick_params(axis="y", length=0)
    axr.spines["left"].set_visible(False)


def _fig3d(ax):
    """(d) Best communication cost found so far, over the strongest evaluated
    baseline, against wall-clock time: one timed re-run of each
    configuration's headline search (its own budget); the end of each curve
    carries the run's total time."""
    tr = read_csv(os.path.join(V7, "search_trajectories.csv"))
    meta = json.load(open(os.path.join(V7, "search_trajectories.json")))["runs"]
    ax.axhline(1.0, color=INK, lw=0.7, ls=(0, (3, 2)), zorder=2)
    ax.text(380, 0.996, "baseline", fontsize=FS3["tiny"], color=INK, ha="right", va="top")
    YTOP = 1.25
    for cid, m in meta.items():
        rows = [r for r in tr if r["config_id"] == cid]
        t = np.array([float(r["t_s"]) for r in rows]); b = np.array([float(r["best_norm"]) for r in rows])
        col = TRAJ3[m["model"]]
        ax.step(t, np.minimum(b, YTOP + 0.05), where="post", color=col, lw=0.9, zorder=4,
                label=f"{m['model']} ({m['n_dies']})")
        ax.plot([t[-1]], [b[-1]], marker="o", ms=3.6, color=col, zorder=5)
        ax.annotate(f"{m['wall_s']:.1f} s", (t[-1], b[-1]), textcoords="offset points", xytext=(0, -3.5),
                    ha="center", va="top", fontsize=FS3["tiny"], color=INK)
        if b[0] > YTOP:                                # a rule start above the window
            ax.annotate(f"start {b[0]:.2f}", (t[0] if t[0] > 0.01 else 0.012, YTOP), textcoords="offset points",
                        xytext=(1, -2), ha="left", va="top", fontsize=FS3["tiny"], color=TRAJ3_TXT[m["model"]])
    ax.set_xscale("log"); ax.set_xlim(0.01, 400); ax.set_ylim(0.66, YTOP)
    ax.set_xticks([0.01, 0.1, 1, 10, 100]); ax.set_xticklabels(["0.01", "0.1", "1", "10", "100"])
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_yticks([0.8, 1.0, 1.2])
    ax.set_xlabel("Search time (s)", fontsize=FS3["axis"], labelpad=1.5)
    ax.set_ylabel("Best H / H$_\\mathrm{base}$", fontsize=FS3["axis"], labelpad=2)
    _title3(ax, "(d) Search progress")
    ax.legend(fontsize=FS3["tiny"], loc="upper right", frameon=False, labelspacing=0.2, handlelength=1.0,
              handletextpad=0.4, borderaxespad=0.1)
    _tidy(ax, grid="y")
    return meta


def fig3():
    SRC = ["analysis/v7/silicon_reference.csv", "analysis/v7/booksim_candidate_costs.csv",
           "analysis/v7/booksim_library_summary.csv", "analysis/v7/runtime_summary.csv",
           "analysis/v7/runtime_samples.csv", "analysis/v7/runtime_environment.json",
           "analysis/v7/validation_protocols.json", "analysis/v7/search_trajectories.csv",
           "analysis/v7/search_trajectories.json"]
    W = 3.4
    Lm, G, Rm = 0.40, 0.38, 0.04                      # left margin, column gap, right margin (in); the Fig. 7 gaps
    pw = (W - Lm - G - Rm) / 2
    top, ph_t, ph_b, rgap, bot = 0.17, 1.00, 0.80, 0.40, 0.30   # the bottom row flatter than the top
    H = top + ph_t + rgap + ph_b + bot
    fig = plt.figure(figsize=(W, H))
    yb_t = bot + ph_b + rgap
    P = lambda col, y0, h: fig.add_axes([(Lm + col * (pw + G)) / W, y0 / H, pw / W, h / H])
    axa = P(0, yb_t, ph_t); axb = P(1, yb_t, ph_t)
    rows = _fig3a(axa); cand, summ = _fig3b(axb)
    rt = _runtime3()
    wr, gr = 0.30, 0.07                               # (c)'s cell: a main axis and a narrow repricing axis
    axm = fig.add_axes([Lm / W, bot / H, (pw - wr - gr) / W, ph_b / H])
    axr = fig.add_axes([(Lm + pw - wr) / W, bot / H, wr / W, ph_b / H])
    axd = P(1, bot, ph_b)
    _fig3c(axm, axr, rt); traj = _fig3d(axd)
    for ax_ in (axa, axb, axm, axr, axd):              # axis type at the Fig. 6 / 7 size (measured below for the y titles)
        ax_.tick_params(axis="both", labelsize=4.8)
        ax_.xaxis.label.set_fontsize(4.8); ax_.yaxis.label.set_fontsize(4.8)
        ax_.title.set_fontsize(FS3["title"])
    # y titles of each column on one vertical line, just left of the column's widest tick labels
    # (align_ylabels needs a gridspec; these are plain axes): measured, then placed
    from matplotlib.transforms import blended_transform_factory as _bt
    rend = fig.canvas.get_renderer(); fig.canvas.draw()
    for col in ((axa, axm), (axb, axd)):
        tick_left = min(tl.get_window_extent(rend).x0 for ax_ in col for tl in ax_.get_yticklabels()
                        if tl.get_text()) / fig.dpi
        for ax_ in col:
            tr = _bt(fig.dpi_scale_trans, ax_.transAxes)
            ax_.yaxis.set_label_coords(tick_left, 0.5, transform=tr)
            fig.canvas.draw()
            right = ax_.yaxis.label.get_window_extent(rend).x1 / fig.dpi
            ax_.yaxis.set_label_coords(tick_left - 0.06 - (right - tick_left), 0.5, transform=tr)   # the PDF backend sets the digits a little wider than Agg measures
    meta = {"panel_a": {"layer": rows[0]["layer"], "normalisation": rows[0]["normalisation"],
                        "farthest": {k: rows[-1][k] for k in ("measured_norm", "bound_series_norm",
                                                              "protocol_series_norm")}},
            "panel_b": {sid: {k: summ[sid][k] for k in ("n_candidates", "baseline_id", "analytic_kappa",
                                                        "booksim_concentration", "spearman_A_full_vs_booksim",
                                                        "booksim_over_bound_min", "booksim_over_bound_median",
                                                        "booksim_over_bound_max")}
                        for sid, _, _, _ in OFFLOAD_LIBS},
            "normalisation_b": "each library: both axes / the library's default fill (sequential) in that evaluator",
            "panel_c": {r["config_id"]: {"model": r["model"], "n_dies": r["n_dies"],
                                         "full_eval_median_s": r["full_eval_median_s"],
                                         "incremental_median_s": r["incremental_median_s"],
                                         "repricing_per_candidate_median_s": r["repricing_per_candidate_median_s"],
                                         "full_over_incremental_speedup": r["full_over_incremental_speedup"]}
                        for r in rt},
            "panel_d": {cid: {k: m[k] for k in ("model", "n_dies", "run", "start_layout", "steps", "wall_s",
                                                "best_norm", "reproduction_rel_err", "annealer_revision")}
                        for cid, m in traj.items()},
            "note_d": "each configuration's headline search re-run with the annealer revision of the confirmation "
                      "batch; endpoints reproduce the record; times are this run's own wall clock; budgets differ"}
    save(fig, "fig3_validation", composite=True, sources=SRC, meta=meta,
         note="single column, 2x2: (a) Simba T1, (b) offload BookSim libraries + bound inset, "
              "(c) three operation costs, (d) best-so-far search progress against wall time")
    dump_csv("fig3b_offload_candidates", [r for r in cand if r["scenario_id"] in {s for s, _, _, _ in OFFLOAD_LIBS}],
             list(cand[0].keys()))
    dump_csv("fig3c_runtime", rt, list(rt[0].keys()))


# =====================================================================
# Fig. 4  what the coarse metric misses: a strict word-hops tie (a) and the
# choice it leads to in fixed candidate libraries (b); one column, side by side
# =====================================================================
F4 = dict(pre="#68b4ce", dec="#f3de67", two="#a5c582", A="#68b4ce", B="#a5c582", edge="#2b2f33")
SCEN4 = [("offload6x6", "1-layer prefill", F4["pre"]), ("offload_decode6x6", "1-layer decode", F4["dec"]),
         ("offload2_8x8", "2-layer prefill", F4["two"])]
# (b): dark to light across the four bars of a cluster
OBJ4 = [("booksim", "BookSim best", "#4660ad"), ("A_full", "Isobar", "#68b4ce"), ("word_hops", "Word-hops", "#a5c582"),
        ("max_hops", "Max-hops", "#f3de67")]
ROLE4 = {"qkv_proj": "Q", "attention": "A", "out_proj": "O", "ffn1": "1", "ffn2": "2"}
FS4_TITLE = 5.3                                    # the 2.7 in figure prints larger than the 3.4 in ones


def _fig4a_maps():
    """The two members of the strict equivalence group layer6x6:wh1 (equal
    integer word-hops, payload and flow count), re-routed under the fixed XY
    rule: per directed mesh link the peak stage load (max over the layer's
    four hand-offs, the quantity the evaluator reads), the die ports, and the
    binding resource of each hand-off."""
    import re
    from scripts import v3_discrim as D, cimsim_cli as cli, search_eval as se, search_space as ss
    g = [r for r in read_csv(os.path.join(V7, "equivalent_candidate_groups.csv")) if r["group_id"] == "layer6x6:wh1"]
    assert len(g) == 2 and g[0]["exact_word_hops"] == g[1]["exact_word_hops"]
    a, b = sorted(g, key=lambda r: float(r["booksim_cycles"]))
    lib = json.load(open(os.path.join(WS, "analysis", a["source"])))
    Wk = D.make_W((6, 6), 1, kappa=lib["kappa"], phase="prefill", offload=False)
    ic = Wk.die_ic
    out = {}
    for tag, r in (("A", a), ("B", b)):
        c = lib["candidates"][r["candidate_id"]]
        pi = ss.Pi.from_json(c["pi"])
        seats = {n: ROLE4[op.split("@")[0]] for op, ns in pi.seat.items() for n in ns}
        links, ports, stages = {}, {}, []
        for into, fl in cli.handoff_flows(Wk, pi, "prefill"):
            loads = se.resource_loads(fl, ic, ports=True, kappa=lib["kappa"])
            k, v = max(loads.items(), key=lambda kv: kv[1])
            stages.append({"into": into, "binding": " ".join(map(str, k)), "words": v})
            for kk, vv in loads.items():
                if kk[0] == "port":
                    ports[kk[1:]] = max(ports.get(kk[1:], 0.0), vv)
                else:
                    m = re.match(r"mesh:seg\((\d+), (\d+)\)-\((\d+), (\d+)\)", kk[0])
                    key = tuple(int(x) for x in m.groups()) + (kk[1],)
                    links[key] = max(links.get(key, 0.0), vv)
        A_full = sum(s["words"] for s in stages)
        assert abs(A_full - float(r["analytic_full_score_words"])) < 1e-6, (A_full, r["analytic_full_score_words"])
        out[tag] = dict(id=r["candidate_id"], cls=r["candidate_class"], seats=seats, links=links, ports=ports,
                        stages=stages, coords={n: tuple(int(v) for v in ic.coord(n)) for n in range(36)},
                        A_full=A_full, booksim=float(r["booksim_cycles"]), word_hops=int(r["exact_word_hops"]),
                        n_lanes=len(links), peak=max(links.values()))
    return out


def _mesh_map(ax, ox, oy, s, M, norm, CM, r=0.052):
    """A 6x6 mesh at origin (ox, oy) and pitch s (inches): each physical link
    two lanes, filled by the load ramp (idle lanes at the ramp's zero), the
    seated dies as white nodes with the operator letter, the busiest lane
    starred."""
    from matplotlib.patches import Circle
    EDGE = "#2b2f33"
    LANE, RIM, off = 1.5, 0.25, 0.021
    X = lambda i: ox + i * s
    Y = lambda j: oy + j * s
    for x in range(6):
        for y in range(6):
            for (x1, y1) in ((x + 1, y), (x, y + 1)):
                if x1 >= 6 or y1 >= 6:
                    continue
                horiz = y1 == y
                for d in ("+", "-"):
                    sg = 1 if d == "+" else -1
                    dx, dy = (0, sg * off) if horiz else (-sg * off, 0)
                    v = M["links"].get((x, y, x1, y1, d))
                    p0, p1 = (X(x) + dx, Y(y) + dy), (X(x1) + dx, Y(y1) + dy)
                    ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=EDGE, lw=LANE + 2 * RIM, solid_capstyle="butt",
                            zorder=2)
                    ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=CM(norm(0.0 if v is None else v / 1e6)), lw=LANE,
                            solid_capstyle="butt", zorder=3)
    for n, (x, y) in M["coords"].items():
        cx, cy = X(x), Y(y)
        if n in M["seats"]:
            ax.add_patch(Circle((cx, cy), r, fc="white", ec=EDGE, lw=0.55, zorder=6))
            ax.text(cx, cy, M["seats"][n], fontsize=3.9, color="black", ha="center", va="center_baseline", zorder=7,
                    fontweight="bold")
        else:
            ax.add_patch(Circle((cx, cy), 0.6 * r, fc="white", ec=EDGE, lw=0.3, zorder=6))
    return X(0) - r, X(5) + r, Y(0) - r, Y(5) + r


def _fig4a(ax, W, H):
    """(a) The strict word-hops tie on the 6x6 mesh: the link-load maps of A
    and B, one shared ramp, and B / A under the three metrics."""
    from scripts import plot_dac2027_v2 as V2
    from matplotlib.colors import TwoSlopeNorm
    TXT = INK
    maps = _fig4a_maps()
    CM = matplotlib.colors.LinearSegmentedColormap.from_list(
        "isobar_load_br_light", [(r_ / 255, g_ / 255, b_ / 255) for r_, g_, b_ in
                                 ((104, 180, 206), (160, 205, 222), (205, 228, 236), (233, 241, 244),
                                  (247, 203, 180), (246, 178, 147), (220, 109, 87), (183, 34, 48), (150, 20, 40))])
    vmax = max(m["peak"] for m in maps.values()) / 1e6
    tport = max(max(m["ports"].values()) for m in maps.values()) / 1e6   # the port bound (words / kappa)
    norm = TwoSlopeNorm(vmin=0.0, vcenter=tport, vmax=vmax)
    s, r = 0.142, 0.050
    oy = 0.21
    bounds = {}
    for tag, ox in (("A", 0.10), ("B", 0.98)):
        M = maps[tag]
        x0, x1, y0, y1 = _mesh_map(ax, ox, oy, s, M, norm, CM, r=r)
        bounds[tag] = (x0, x1, y0, y1)
        ax.text(x0 + 0.05, y0 - 0.045, tag, fontsize=4.8, color=TXT, ha="left", va="top", fontweight="bold")
        ax.text(x0 + 0.16, y0 - 0.045, f"peak {M['peak'] / 1e6:.1f} M · {M['n_lanes']} lanes",
                fontsize=4.8, color=TXT, ha="left", va="top")
    # the right block: a horizontal colour bar over the B / A bars, both as wide as the block
    x0, x1, y0, y1 = bounds["B"]
    A, B = maps["A"], maps["B"]
    ratios = [("Word-hops", B["word_hops"] / A["word_hops"]), ("Isobar cost", B["A_full"] / A["A_full"]),
              ("BookSim", B["booksim"] / A["booksim"])]
    xl = x1 + 0.17                                   # the block's plot area (the bars' y ticks to its left)
    wb = 0.72
    cb_h = 0.045
    cbx = ax.inset_axes((xl, y1 - 0.075 - cb_h, wb - 0.10, cb_h), transform=ax.transData)   # under the "M words" line; its last tick label ends at the bars' right edge
    vals = np.linspace(0.0, vmax, 512)
    cbx.imshow(CM(norm(vals))[None, :, :], origin="lower", aspect="auto", extent=(0, vmax, 0, 1),
               interpolation="nearest")
    cbx.set_xlim(0, vmax); cbx.set_ylim(0, 1); cbx.set_yticks([])
    cbx.set_xticks([0, tport, vmax]); cbx.set_xticklabels(["0", f"{tport:.1f}", f"{vmax:.1f}"])
    cbx.tick_params(labelsize=4.8, length=1.5, pad=1, width=0.5, colors=TXT)
    for sp in cbx.spines.values():
        sp.set_linewidth(0.4)
    ax.text(xl, y1, "M words", fontsize=4.8, color=TXT, ha="left", va="top")   # its top on the maps' top edge
    bx = ax.inset_axes((xl, y0, wb, y1 - y0 - cb_h - 0.38), transform=ax.transData)   # upright paired bars, on the maps' baseline
    xb = np.arange(len(ratios)); wb_ = 0.28
    bx.bar(xb - wb_ / 2, [1.0] * len(ratios), wb_, color=F4["A"], ec=F4["edge"], lw=0.25, zorder=2, label="A")
    bx.bar(xb + wb_ / 2, [v for _, v in ratios], wb_, color=F4["B"], ec=F4["edge"], lw=0.25, zorder=2, label="B")
    for x_, (nm, v) in zip(xb, ratios):
        bx.text(x_ + wb_ / 2, v + 0.05, f"{v:.2f}", fontsize=FS3["tiny"], color=TXT, ha="center", va="bottom",
                zorder=5)
    bx.set_xticks(xb); bx.set_xticklabels(["Word\nhops", "Isobar", "Book\nSim"], linespacing=1.0, fontsize=4.2)
    bx.set_xlim(-0.65, len(ratios) - 0.35)
    bx.set_ylim(0, 2.5); bx.set_yticks([0, 1, 2])
    bx.set_yticklabels(["0", "1×", "2×"])
    bx.tick_params(axis="y", labelsize=4.8, length=1.5, pad=1.5, width=0.5, colors=TXT)
    bx.tick_params(axis="x", length=0, labelsize=4.2, pad=1.5, colors=TXT)
    for sp in ("top", "right"):
        bx.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        bx.spines[sp].set_linewidth(0.5)
    bx.set_facecolor("none")
    bx.text(-0.04, 1.02, "B / A", transform=bx.transAxes, fontsize=4.4, color=TXT, ha="left", va="bottom")
    bx.legend(fontsize=FS3["tiny"], loc="lower right", bbox_to_anchor=(1.0, 1.0), frameon=False, ncol=2,
              handlelength=0.9, handletextpad=0.3, columnspacing=0.7, borderaxespad=0.0, borderpad=0.1)
    ax.set_title("(a) Equal word-hops, unequal load", fontsize=FS4_TITLE, loc="left", pad=1.5)
    return maps, ratios, xl + wb                    # the right edge of the panel's content (in)


def _fig4b(ax, w=0.15, pitch=0.15, legend_ncol=3, ymax=1.78, two_line=False, cstep=1.0, legend_fs=None):
    """(b) Selection from each of the three offload BookSim libraries, in the
    Fig. 6 idiom: per library (cluster) four thin bars, the BookSim-best
    candidate (1x) and the candidate each analytic metric picks (lowest
    score, exact ties broken by the sorted id), as BookSim time over the
    library's best; a T in the bar's centre spans the BookSim times of
    every exact-tie member (the range of tied optima)."""
    sel = read_csv(os.path.join(V7, "booksim_selection_by_objective.csv"))
    cyc = {(r["scenario_id"], r["candidate_id"]): int(r["booksim_cycles"])
           for r in read_csv(os.path.join(V7, "booksim_candidate_costs.csv"))}
    pick = {}
    for r in sel:                                      # the export repeats a row; one per (library, objective)
        pick.setdefault((r["scenario_id"], r["objective"]), r)
    x = np.arange(len(SCEN4)) * cstep                  # cluster centres
    dxs = np.linspace(-1.5 * pitch, 1.5 * pitch, len(OBJ4))
    ax.axhline(1.0, color="#8f949a", lw=0.7, ls=(0, (3, 2)), zorder=1.5)
    rows = []
    for j, (s, name, _) in enumerate(SCEN4):
        vals_prev = []                                  # (x, objective, selected, top of bar + range) per bar of the cluster
        for k, (obj, lab, col) in enumerate(OBJ4):
            r = pick[(s, "A_full" if obj == "booksim" else obj)]
            best = int(r["booksim_best_cycles"])
            if obj == "booksim":
                chosen, members, vsel, tie = r["booksim_best_id"], [r["booksim_best_id"]], 1.0, [1.0]
            else:
                chosen = r["selected_id_stable_rule"]; members = r["min_score_tie_members"].split(";")
                vsel = cyc[(s, chosen)] / best
                assert abs(vsel - 1 - float(r["regret_selected"])) < 1e-9
                tie = [cyc[(s, m)] / best for m in members]
            xx = x[j] + dxs[k]
            ax.bar(xx, vsel - 0.8, w, bottom=0.8, color=col, ec="#2b2f33", lw=0.25, zorder=2,
                   label=lab if j == 0 else None)   # bars rise from the axis floor at 0.8
            if max(tie) - min(tie) > 0.003:            # the range of tied optima: stem + a cap at the end(s) away from the bar top
                ax.plot([xx, xx], [min(tie), max(tie)], color=INK, lw=0.6, zorder=4, solid_capstyle="butt")
                for v in (min(tie), max(tie)):
                    if abs(v - vsel) > 0.003:
                        ax.plot([xx - 0.3 * w, xx + 0.3 * w], [v, v], color=INK, lw=0.6, zorder=4,
                                solid_capstyle="butt")
            vals_prev.append((xx, obj, vsel, max([vsel] + tie)))
            rows.append({"library": s, "objective": obj, "selected": chosen, "booksim_over_best": vsel,
                         "tie_set_size": len(members), "tie_members": ";".join(members),
                         "tie_min": min(tie), "tie_max": max(tie), "booksim_best": r["booksim_best_id"]})
        placed = []
        for k, (xx, obj, vsel, top) in enumerate(vals_prev):
            if obj == "booksim":
                continue
            yl = top + 0.035
            while any(abs(px - xx) < pitch + 0.02 and abs(py - yl) < 0.06 for px, py in placed):
                yl += 0.06                             # an equal-height neighbour: stack the label
            placed.append((xx, yl))
            left_taller = k > 0 and vals_prev[k - 1][3] > yl
            right_taller = k + 1 < len(vals_prev) and vals_prev[k + 1][3] > yl
            xlab = xx + (0.035 if left_taller and not right_taller else -0.035 if right_taller and not left_taller else 0.0)
            ax.text(xlab, yl, f"{vsel:.2f}", fontsize=FS3["tiny"], color=INK, ha="center", va="bottom", zorder=6)
    ax.set_xticks(x); ax.set_xticklabels([(n.replace(" ", "\n", 1) if two_line else n) for _, n, _ in SCEN4], linespacing=1.0)
    ax.set_xlim(-0.6 * cstep, x[-1] + 0.6 * cstep); ax.set_ylim(0.8, ymax); ax.set_yticks([1.0, 1.2, 1.4, 1.6])
    ax.set_yticklabels(["1.0×", "1.2×", "1.4×", "1.6×"])
    ax.set_ylabel("BookSim latency\n(norm. to best in pool)", fontsize=FS3["axis"], labelpad=2, linespacing=1.1)
    _title3(ax, "(b) BookSim performance of selected mappings")
    from matplotlib.lines import Line2D
    h, l = ax.get_legend_handles_labels()
    h.append(Line2D([], [], color=INK, lw=0.6, marker="_", ms=4, label="Range of tied optima"))
    ax.legend(handles=h, fontsize=legend_fs or FS3["tiny"], loc="upper right", frameon=False, ncol=legend_ncol,
              handlelength=0.8, handletextpad=0.3, labelspacing=0.2, columnspacing=0.5, borderaxespad=0.1,
              handleheight=0.7)
    _tidy(ax, grid="y")
    return rows


def fig4():
    from scripts import plot_dac2027_v2 as V2
    SRC = ["analysis/v7/equivalent_candidate_groups.csv", "analysis/v3/e3_k2/library_layer6x6.json",
           "analysis/v7/booksim_selection_by_objective.csv", "analysis/v7/booksim_candidate_costs.csv"]
    W = 3.4
    Lm, Rm = 0.46, 0.04
    top, ha, rgap, hb, bot = 0.17, 1.04, 0.16, 0.82, 0.36
    H = top + ha + rgap + hb + bot
    fig = plt.figure(figsize=(W, H))
    axa = V2._inch_axes(fig, [0, (bot + hb + rgap) / H, 1, ha / H], W, ha)
    maps, ratios, xr = _fig4a(axa, W, ha)
    axb = fig.add_axes([Lm / W, bot / H, (xr - Lm) / W, hb / H])   # as wide as panel (a)'s content
    rows = _fig4b(axb)
    axb.tick_params(axis="both", labelsize=4.8)       # axis type at the Fig. 6 / 7 size
    axb.xaxis.label.set_fontsize(4.8); axb.yaxis.label.set_fontsize(4.8)
    axb.set_title(axb.get_title(loc="left"), loc="left", fontsize=FS4_TITLE, pad=0,
                  x=-Lm / (xr - Lm), y=1.0 + 0.06 / hb)   # starts at the figure's left edge, like (a)'s
    meta = {"panel_a": {"group": "layer6x6:wh1",
                        **{t: {"id": m["id"], "class": m["cls"], "word_hops": m["word_hops"], "A_full": m["A_full"],
                               "booksim_cycles": m["booksim"], "peak_lane_words": m["peak"], "lanes_used": m["n_lanes"],
                               "stages": m["stages"]} for t, m in maps.items()},
                        "ratios_B_over_A": dict(ratios),
                        "lane_value": "peak stage load per directed link (max over the layer's four hand-offs)"},
            "panel_b": rows,
            "rule_b": "lowest analytic score; exact ties broken by the stable candidate id; bar = BookSim(selected) / "
                      "min_library BookSim (the BookSim-best bar = 1); the T spans the BookSim time of every exact-tie member"}
    save(fig, "fig4_discrimination", composite=True, sources=SRC, meta=meta,
         note="single column, two rows: (a) link-load maps of the strict word-hops tie A / B with B/A ratios, "
              "(b) four-objective selection in three offload libraries with tie members")
    dump_csv("fig4b_selection", rows, list(rows[0].keys()))


# =====================================================================
# Fig. 5  the Gemma main result: communication cost (a), where the saving
# comes from (b), what it is worth in mesh bandwidth (c); one column
# =====================================================================
F5C = dict(default="#c4c9ce", rule="#60a6be", base="#a5c582", search="#68b4ce", search_txt="#3f7f93",
           base_txt="#6f8f52")
STAGE5 = [("out_proj->ffn1", "out_proj→FFN1"), ("ffn1->ffn2", "FFN1→FFN2"),
          ("qkv->unit", "QKV→unit"), ("unit->out_proj", "unit→out_proj"),
          ("ffn2->next qkv", "FFN2→next QKV")]


FS5_NOTE = 4.6                                         # in-panel annotations, a step above the legend type
RULE5 = {"sequential": "Default (stacked fill)", "snake": "Snake", "least_manhattan": "Least Manhattan",
         "nmap_greedy": "NMAP greedy", "heaviest_first": "Heaviest first", "clustered": "Clustered"}
# families as in the v2 Fig. 4: stacked fills blue, heuristics deep blue, random grey, search green
F5A = dict(fam={"stacked": "#f3de67", "heuristic": "#4660ad", "random": "#a5c582", "search": "#68b4ce"},
           txt={"stacked": "#8a7a2a", "heuristic": "#34488a", "random": "#6f8f52", "search": "#3f7f93"},
           comm="#68b4ce", noncomm="#dfe4e8")



def _fig4_ratio_bars(ax, bx_rect, cb_rect, maps, vmax, tport, norm, CM, TXT):
    """The B / A paired bars with the horizontal load ramp above them, at
    the given inch rects of the inch axes (shared by the two Fig. 4 layouts)."""
    A, B = maps["A"], maps["B"]
    ratios = [("Word-hops", B["word_hops"] / A["word_hops"]), ("Isobar cost", B["A_full"] / A["A_full"]),
              ("BookSim", B["booksim"] / A["booksim"])]
    cbx = ax.inset_axes(cb_rect, transform=ax.transData)
    vals = np.linspace(0.0, vmax, 512)
    cbx.imshow(CM(norm(vals))[None, :, :], origin="lower", aspect="auto", extent=(0, vmax, 0, 1), interpolation="nearest")
    cbx.set_xlim(0, vmax); cbx.set_ylim(0, 1); cbx.set_yticks([])
    cbx.set_xticks([0, tport, vmax]); cbx.set_xticklabels(["0", f"{tport:.1f}", f"{vmax:.1f}"])
    cbx.tick_params(labelsize=4.8, length=1.5, pad=1, width=0.5, colors=TXT)
    for sp in cbx.spines.values():
        sp.set_linewidth(0.4)
    ax.text(cb_rect[0], cb_rect[1] + cb_rect[3] + 0.03, "M words", fontsize=4.8, color=TXT, ha="left", va="bottom")
    bx = ax.inset_axes(bx_rect, transform=ax.transData)
    xb = np.arange(len(ratios)); wb_ = 0.28
    bx.bar(xb - wb_ / 2, [1.0] * len(ratios), wb_, color=F4["A"], ec=F4["edge"], lw=0.25, zorder=2, label="A")
    bx.bar(xb + wb_ / 2, [v for _, v in ratios], wb_, color=F4["B"], ec=F4["edge"], lw=0.25, zorder=2, label="B")
    for x_, (nm, v) in zip(xb, ratios):
        bx.text(x_ + wb_ / 2, v + 0.05, f"{v:.2f}", fontsize=FS3["tiny"], color=TXT, ha="center", va="bottom", zorder=5)
    bx.set_xticks(xb); bx.set_xticklabels(["Word\nhops", "Isobar", "Book\nSim"], linespacing=1.0, fontsize=4.2)
    bx.set_xlim(-0.65, len(ratios) - 0.35); bx.set_ylim(0, 2.5); bx.set_yticks([0, 1, 2])
    bx.set_yticklabels(["0", "1×", "2×"])
    bx.tick_params(axis="y", labelsize=4.8, length=1.5, pad=1.5, width=0.5, colors=TXT)
    bx.tick_params(axis="x", length=0, labelsize=4.2, pad=1.5, colors=TXT)
    for sp in ("top", "right"):
        bx.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        bx.spines[sp].set_linewidth(0.5)
    bx.set_facecolor("none")
    bx.text(-0.04, 1.02, "B / A", transform=bx.transAxes, fontsize=4.4, color=TXT, ha="left", va="bottom")
    bx.legend(fontsize=FS3["tiny"], loc="lower right", bbox_to_anchor=(1.0, 1.0), frameon=False, ncol=2,
              handlelength=0.9, handletextpad=0.3, columnspacing=0.7, borderaxespad=0.0, borderpad=0.1)
    return ratios


def fig4_alt():
    """The alternative layout: the two link-load maps stacked at the left,
    the B / A bars (with the ramp) over panel (b) at the right."""
    from scripts import plot_dac2027_v2 as V2
    from matplotlib.colors import TwoSlopeNorm
    TXT = INK
    maps = _fig4a_maps()
    CM = matplotlib.colors.LinearSegmentedColormap.from_list(
        "isobar_load_br_light", [(r_ / 255, g_ / 255, b_ / 255) for r_, g_, b_ in
                                 ((104, 180, 206), (160, 205, 222), (205, 228, 236), (233, 241, 244),
                                  (247, 203, 180), (246, 178, 147), (220, 109, 87), (183, 34, 48), (150, 20, 40))])
    vmax = max(m["peak"] for m in maps.values()) / 1e6
    tport = max(max(m["ports"].values()) for m in maps.values()) / 1e6
    norm = TwoSlopeNorm(vmin=0.0, vcenter=tport, vmax=vmax)
    W, H = 3.0, 2.55
    s, r = 0.142, 0.050
    mh = 5 * s + 2 * r                                 # a map's height
    fig = plt.figure(figsize=(W, H))
    ax = V2._inch_axes(fig, [0, 0, 1, 1], W, H)
    oyA, oyB = H - 0.22 - mh + r, 0.30 + r             # map A above map B
    for tag, oy in (("A", oyA), ("B", oyB)):
        M = maps[tag]
        x0, x1, y0, y1 = _mesh_map(ax, 0.10, oy, s, M, norm, CM, r=r)
        ax.text(x0 + 0.05, y0 - 0.045, tag, fontsize=4.8, color=TXT, ha="left", va="top", fontweight="bold")
        ax.text(x0 + 0.16, y0 - 0.045, f"peak {M['peak'] / 1e6:.1f} M · {M['n_lanes']} lanes", fontsize=4.8,
                color=TXT, ha="left", va="top")
    ax.text(0.0, H - 0.02, "(a) Equal word-hops, unequal load", fontsize=FS4_TITLE, color="black", ha="left", va="top")
    # the right column: the ramp and the B / A bars at the top, panel (b) below
    xr0 = x1 + 0.62; wr = W - 0.04 - xr0
    cb_h = 0.045; wbar = 0.98                           # the ramp and the bars: as wide as (b), left-aligned with it
    cb_rect = (xr0, H - 0.22 - 0.075 - cb_h, wbar - 0.10, cb_h)
    bx_rect = (xr0, H - 0.22 - mh + 0.04, wbar, mh - cb_h - 0.42)
    ratios = _fig4_ratio_bars(ax, bx_rect, cb_rect, maps, vmax, tport, norm, CM, TXT)
    hb = 0.95; wb_axes = 0.98
    axb = fig.add_axes([xr0 / W, 0.32 / H, wb_axes / W, hb / H])
    rows = _fig4b(axb, w=0.11, pitch=0.11, legend_ncol=2, ymax=2.0, two_line=True, cstep=0.52, legend_fs=3.6)
    axb.tick_params(axis="both", labelsize=4.8)
    axb.xaxis.label.set_fontsize(4.8); axb.yaxis.label.set_fontsize(4.8)
    fig.canvas.draw()                                   # the title starts at the y title's left edge
    yl_x0 = axb.yaxis.label.get_window_extent(fig.canvas.get_renderer()).x0 / fig.dpi
    axb.set_title("(b) Selected mappings in BookSim", fontsize=FS4_TITLE, loc="left", pad=3,
                  x=(yl_x0 - xr0) / wb_axes)
    SRC = ["analysis/v7/equivalent_candidate_groups.csv", "analysis/v3/e3_k2/library_layer6x6.json",
           "analysis/v7/booksim_selection_by_objective.csv", "analysis/v7/booksim_candidate_costs.csv"]
    save(fig, "fig4_discrimination_alt", composite=True, sources=SRC,
         meta={"layout": "maps A over B at the left; B / A bars over panel (b) at the right", "ratios_B_over_A": dict(ratios)},
         note="alternative layout of Fig. 4; the data and statistics are those of fig4_discrimination")

def _fam5(layout):
    if layout in ("sequential", "snake"):
        return "stacked"
    if layout.startswith("random"):
        return "random"
    if layout.startswith("sa_"):
        return "search"
    return "heuristic"


def _fig5_candidates():
    c = read_csv(os.path.join(V6, "gemma_candidates.csv"))
    for r in c:
        r["T"] = float(r["T_backbone_s"]); r["H"] = float(r["H_full_s"]); r["E"] = float(r["E_total_J"])
    base = next(r for r in c if r["is_strongest"] == "True")
    rep = next(r for r in c if r["is_representative"] == "True")
    return c, base, rep


def _fig5a(ax, note=None, leg=None, bracket_dx=0.95, arrow_drop=0.95):
    """(a) Whole-model prefill latency of the evaluated Gemma layouts in the
    v2 Fig. 4(a) idiom: non-communication and package communication stacked,
    the default fill, the named rules, the best random fill (of 500) and the
    representative search layout; the inset shows all 500 random fills and
    the 30 search endpoints (ten seeds x three starts) on one axis."""
    c, base, rep = _fig5_candidates()
    note = note or FS5_NOTE; leg = leg or FS3["tiny"]
    order = [next(r for r in c if r["kind"] == "default fill")]
    order += sorted((r for r in c if r["kind"] == "rule"), key=lambda r: -r["T"])
    order += [base, rep]
    names = {base["layout"]: "Best random (of 500)", rep["layout"]: "Isobar search (rep.)"}
    ys = np.arange(len(order))[::-1]
    for y, r in zip(ys, order):
        R, H = r["T"] - r["H"], r["H"]
        ax.barh(y, R, color=F5A["noncomm"], ec="none", height=0.62, zorder=2)      # below the spine (2.5)
        ax.barh(y, H, left=R, color=F5A["comm"], ec="none", height=0.62, zorder=2)
        ax.text(r["T"] + 0.12, y, f"{r['T']:.2f}", va="center", ha="left", fontsize=FS5_NOTE,
                color=F5A["txt"][_fam5(r["layout"])], zorder=4)
    ax.set_yticks(ys); ax.set_yticklabels([names.get(r["layout"]) or RULE5[r["layout"]] for r in order],
                                          rotation=45, ha="right", va="center", rotation_mode="anchor")
    for tick, r in zip(ax.get_yticklabels(), order):
        tick.set_color(F5A["txt"][_fam5(r["layout"])])
    ax.set_xlabel("Whole-model prefill latency T (s)", fontsize=FS3["axis"], labelpad=1.5)
    ax.set_xlim(0, 13.2); ax.set_xticks([0, 4, 8, 12])
    yb = ys[-1] - arrow_drop
    d0 = order[0]
    ax.annotate("", xy=(rep["T"], yb), xytext=(d0["T"], yb),
                arrowprops=dict(arrowstyle="<|-|>", color="#3f7f93", lw=0.8, mutation_scale=6,
                                shrinkA=0, shrinkB=0))                       # the communication bars' hue
    ax.text((rep["T"] + d0["T"]) / 2, yb + 0.14, f"{100 * (1 - rep['T'] / d0['T']):.1f}% below the default fill",
            fontsize=note, color="#3f7f93", ha="center", va="bottom")
    ax.set_ylim(yb - 0.45, max(ys) + 0.6)
    from matplotlib.patches import Rectangle
    ax.legend(handles=[Rectangle((0, 0), 1, 1, fc=F5A["noncomm"], ec="none"),
                       Rectangle((0, 0), 1, 1, fc=F5A["comm"], ec="none")],
              labels=["Non-communication", "Package communication"], fontsize=leg,
              loc="upper right", bbox_to_anchor=(1.0, 0.66), frameon=False, ncol=1, handlelength=1.2,
              handletextpad=0.4, labelspacing=0.15, borderaxespad=0.0)
    ax.set_title("(a) Whole-model latency of the evaluated layouts", fontsize=FS3["title"], loc="left", pad=4.8)
    _tidy(ax, grid="x")
    ax.tick_params(axis="y", labelsize=FS3["tiny"], length=0)
    # the headline numbers, bracketing the best random and the search rows
    rnd = sorted(r["T"] for r in c if r["kind"] == "random fill")
    sea = sorted(r["T"] for r in c if r["kind"] == "search endpoint")
    assert len(rnd) == 500 and len(sea) == 30 and base["T"] == rnd[0]
    xb_ = base["T"] + bracket_dx
    ax.plot([xb_, xb_], [ys[-2] + 0.25, ys[-1] - 0.25], color=F5A["txt"]["search"], lw=0.7, zorder=4)
    ax.plot([xb_ - 0.08, xb_], [ys[-2] + 0.25] * 2, color=F5A["txt"]["search"], lw=0.7, zorder=4)
    ax.plot([xb_ - 0.08, xb_], [ys[-1] - 0.25] * 2, color=F5A["txt"]["search"], lw=0.7, zorder=4)
    ax.text(xb_ + 0.12, (ys[-1] + ys[-2]) / 2,
            f"−{100 * (1 - rep['H'] / base['H']):.1f}% communication\n−{100 * (1 - rep['T'] / base['T']):.1f}% total latency",
            fontsize=note + 0.4, color=F5A["txt"]["search"], ha="left", va="center", linespacing=1.25)
    return order, base, rep, {"random": rnd, "search": sea}


def _fig5d(ax, note=None, inset_note=None, title="(c) Latency and dynamic energy"):
    """(d) The same layouts in whole-model latency and system dynamic
    energy (no static term); the named rules, the 500 random fills and the
    30 search endpoints; the representative pair highlighted."""
    note = note or FS5_NOTE; inset_note = inset_note or FS5_NOTE
    c, base, rep = _fig5_candidates()
    MK = {"stacked": "s", "heuristic": "^", "random": "o", "search": "*"}
    LAB = {"stacked": "Stacked fills", "heuristic": "Placement heuristics",
           "random": "Random fills", "search": "Isobar search endpoints"}
    seen = set()
    for fam in ("random", "search", "heuristic", "stacked"):
        rs = [r for r in c if _fam5(r["layout"]) == fam and r not in (base, rep)]
        ms = {"random": 2.0, "search": 4.0, "heuristic": 5.8, "stacked": 5.0}[fam]
        ax.plot([r["T"] for r in rs], [r["E"] for r in rs], marker=MK[fam], ms=ms, color=F5A["fam"][fam],
                mec="none" if fam == "random" else "white", mew=0.3, ls="none", alpha=0.6 if fam == "random" else 1,
                zorder=4 if fam == "random" else 5, label=LAB[fam])
    ax.plot([base["T"]], [base["E"]], marker="o", ms=4.4, color=F5A["fam"]["random"], mec=INK, mew=0.6, ls="none",
            zorder=6)
    ax.plot([rep["T"]], [rep["E"]], marker="*", ms=7.5, color=F5A["fam"]["search"], mec=INK, mew=0.6, ls="none",
            zorder=7)
    # the two clouds enlarged on the same T-E axes: all 500 random fills and the 30 search endpoints
    rnd = [r for r in c if r["kind"] == "random fill"]; sea = [r for r in c if r["kind"] == "search endpoint"]
    ins = ax.inset_axes([0.40, 0.46, 0.31, 0.44])
    ins.plot([r["T"] for r in rnd], [r["E"] for r in rnd], marker="o", ms=1.8, color=F5A["fam"]["random"], mec="none",
             ls="none", alpha=0.6, zorder=4)
    ins.plot([base["T"]], [base["E"]], marker="o", ms=4.2, color=F5A["fam"]["random"], mec=INK, mew=0.6, ls="none",
             zorder=6)
    ins.plot([r["T"] for r in sea], [r["E"] for r in sea], marker="*", ms=4.0, color=F5A["fam"]["search"], mec="none",
             ls="none", alpha=0.7, zorder=5)
    ins.plot([rep["T"]], [rep["E"]], marker="*", ms=7.0, color=F5A["fam"]["search"], mec=INK, mew=0.6, ls="none",
             zorder=7)
    ins.annotate("", xy=(rep["T"], 7.165), xytext=(base["T"], 7.165),
                 arrowprops=dict(arrowstyle="<|-|>", color=F5A["txt"]["search"], lw=0.7, mutation_scale=5,
                                 shrinkA=0, shrinkB=0))
    ins.text((rep["T"] + base["T"]) / 2, 7.17, f"−{100 * (1 - rep['T'] / base['T']):.1f}% T", ha="center",
             va="bottom", fontsize=inset_note, color=F5A["txt"]["search"])
    ins.text(3.73, 7.075, "500 random fills", fontsize=inset_note, color=F5A["txt"]["random"], ha="right",
             va="top")
    ins.text(2.6, 6.965, "30 Isobar endpoints", fontsize=inset_note, color=F5A["txt"]["search"], ha="left",
             va="bottom")
    ins.set_xlim(2.55, 3.75); ins.set_ylim(6.955, 7.21)
    ins.set_xticks([3.0, 3.5]); ins.set_yticks([7.0, 7.1])
    ins.tick_params(labelsize=FS3["tiny"], length=1.5, pad=1.5, width=0.5)
    ins.grid(alpha=0.16, lw=0.5); ins.set_axisbelow(True)
    for s_ in ("top", "right"):
        ins.spines[s_].set_visible(False)
    for s_ in ("left", "bottom"):
        ins.spines[s_].set_linewidth(0.5)
    ins.set_facecolor("none")
    dT = lambda r: 100 * (r["T"] / base["T"] - 1)
    dE = lambda r: 100 * (r["E"] / base["E"] - 1)
    by = {r["layout"]: r for r in c}
    notes = (("sequential", "Default", (-5, 3), "right", "bottom"),
             ("snake", "Snake", (-5, -3), "right", "top"),
             ("heaviest_first", "Heaviest first", (5, 0), "left", "center"),
             ("least_manhattan", f"Least Manhattan\n{dE(by['least_manhattan']):+.1f}% E, "
                                 f"{dT(by['least_manhattan']):+.1f}% T", (7, -1), "left", "center"),
             ("nmap_greedy", "NMAP greedy", (4, 9), "left", "bottom"),
             (base["layout"], "Best random", (14, -1), "left", "center"),
             (rep["layout"], f"Isobar search (rep.)\n{dT(rep):+.1f}% T, {dE(rep):+.2f}% E",
              (8, 9), "left", "bottom"))
    for n, lab, off, ha, va in notes:
        r = by[n]
        ax.annotate(lab, (r["T"], r["E"]), textcoords="offset points", xytext=off, fontsize=FS3["small"], ha=ha,
                    va=va, color=F5A["txt"][_fam5(n)], linespacing=1.15)
    ax.text(0.99, 0.04, "% vs. best random fill", transform=ax.transAxes, fontsize=note,
            color="0.4", style="italic", ha="right", va="bottom")
    ax.set_xlim(2.2, 12.9); ax.set_ylim(5.78, 7.5)
    ax.set_xticks([4, 6, 8, 10, 12]); ax.set_yticks([6.0, 6.5, 7.0, 7.5])
    ax.set_xlabel("Whole-model prefill latency T (s)", fontsize=FS3["axis"], labelpad=1.5)
    ax.set_ylabel("Dynamic energy E (J)", fontsize=FS3["axis"], labelpad=2)
    ax.set_title(title, fontsize=FS3["title"], loc="left", pad=4.8)
    from matplotlib.lines import Line2D
    hl = [Line2D([], [], ls="none", marker=MK[f], ms=5.2 if f == "search" else 3.4, color=F5A["fam"][f], mew=0,
                 label=LAB[f]) for f in ("random", "search", "heuristic", "stacked")]   # no edge: the star keeps its points
    ax.legend(handles=hl, fontsize=FS3["tiny"], loc="upper right", frameon=False, handlelength=1.0,
              handletextpad=0.3, labelspacing=0.2, borderaxespad=0.1)
    _tidy(ax)
    return {"best_random": base["layout"], "representative": rep["layout"], "dT_pct": dT(rep), "dE_pct": dE(rep),
            "T_s": [base["T"], rep["T"]], "E_J": [base["E"], rep["E"]]}


def _fig5b(ax, note=None, pad_right=420, xmax=1500, label_drop=0.72, title="(b) By hand-off kind"):
    """(b) Per hand-off kind, the communication time of the best baseline
    (circle) and of the search layout (square) summed over all layers, the
    same layout pair as (a) and (c), joined by a grey line; the search value
    above its square, the baseline value below its circle."""
    note = note or FS5_NOTE
    sb = read_csv(os.path.join(V6, "gemma_stage_breakdown.csv"))
    tot = {}
    for r in sb:
        tot[(r["layout"], r["stage"])] = tot.get((r["layout"], r["stage"]), 0.0) + \
            (float(r["service_s"]) + float(r["propagation_s"])) * 1e3
    base_id, rep_id = "random_s209", "sa_random_best_s5"
    y = np.arange(len(STAGE5))[::-1]
    rows = []
    for y_, (k, name) in zip(y, STAGE5):
        b, s = tot[(base_id, k)], tot[(rep_id, k)]
        ax.plot([s, b], [y_, y_], color="#99a3aa", lw=0.8, solid_capstyle="butt", zorder=2)
        ax.plot([b], [y_], marker="o", ms=4.0, color=F5C["base"], ls="none", zorder=4)
        ax.plot([s], [y_], marker="s", ms=3.5, color=F5C["search"], ls="none", zorder=4)
        ax.annotate(f"(−{b - s:.0f})", (b, y_), textcoords="offset points", xytext=(4.5, 0), ha="left",
                    va="center", fontsize=note, color=F5C["search_txt"], zorder=5)
        rows.append({"kind": k, "baseline_ms": b, "search_ms": s, "saved_ms": b - s})
    tot_b = sum(r["baseline_ms"] for r in rows); tot_s = sum(r["search_ms"] for r in rows)
    ffn = sum(r["saved_ms"] for r in rows[:2]) / (tot_b - tot_s)
    from matplotlib.patches import Ellipse
    x0_, x1_ = min(rows[0]["search_ms"], rows[1]["search_ms"]) - 120, max(rows[0]["baseline_ms"], rows[1]["baseline_ms"]) + pad_right
    yc = (y[0] + y[1]) / 2
    ax.add_patch(Ellipse(((x0_ + x1_) / 2, yc), x1_ - x0_, (y[0] - y[1]) + 1.25, fc="none", ec=F5C["search_txt"],
                         lw=0.6, ls=(0, (3, 2)), zorder=2))
    ax.text(x1_ - 60, y[1] - label_drop, f"{100 * ffn:.1f}% of\ntotal savings", fontsize=note,
            color=F5C["search_txt"], ha="right", va="top", linespacing=1.15)
    ax.set_yticks(y); ax.set_yticklabels([n for _, n in STAGE5], fontsize=FS3["tiny"])
    ax.set_ylim(-0.6, len(STAGE5) - 0.3); ax.set_xlim(0, xmax); ax.set_xticks([0, 500, 1000])
    ax.set_xlabel("Communication time (ms)", fontsize=FS3["axis"], labelpad=1.5)
    ax.set_title(title, fontsize=FS3["title"], loc="left", pad=4.8)
    from matplotlib.lines import Line2D
    h = [Line2D([], [], ls="none", marker="o", ms=4.0, color=F5C["base"], label="Baseline"),
         Line2D([], [], ls="none", marker="s", ms=3.5, color=F5C["search"], label="Isobar search")]
    ax.legend(handles=h, fontsize=FS3["tiny"], loc="lower right", frameon=False,
              handlelength=1.0, handletextpad=0.3, labelspacing=0.2, borderaxespad=0.1, markerscale=0.8)
    _tidy(ax, grid="x")
    ax.tick_params(axis="y", labelsize=FS3["tiny"], length=0)
    return rows, tot_b, tot_s


def _fig5c(ax, title="(d) Bandwidth equivalent"):
    """(c) The baseline layout's communication time against the mesh
    bandwidth (hub, K/V and digital resources held; die ports scale with
    the mesh at kappa); the search layout's time at B0 as the target; their
    crossing is the equivalent mesh bandwidth."""
    cv = read_csv(os.path.join(V7, "gemma_bandwidth_curve.csv"))
    eq = next(r for r in read_csv(os.path.join(V6, "gemma_bandwidth_equivalence.csv"))
              if r["baseline_layout"] == "random_s209")
    B = np.array([float(r["B_mesh_gbps"]) for r in cv]); Hb = np.array([float(r["H_baseline_s"]) for r in cv]) * 1e3
    B0, Beq = float(eq["B_ref_gbps"]), float(eq["B_eq_gbps"])
    Ht = float(eq["H_search_at_B_ref_s"]) * 1e3; Hb0 = float(eq["H_baseline_at_B_ref_s"]) * 1e3
    Hs = np.array([float(r["H_search_s"]) for r in cv]) * 1e3
    ax.plot(B, Hb, color=F5C["base"], lw=1.2, zorder=3, label="Best baseline")
    ax.plot(B, Hs, color=F5C["search"], lw=1.2, zorder=3, label="Isobar search")
    ax.plot([B0], [Hb0], marker="o", ms=5.2, color=F5C["base"], ls="none", zorder=4)
    ax.plot([B0], [Ht], marker="s", ms=4.6, color=F5C["search"], ls="none", zorder=5)
    ax.plot([Beq], [Ht], marker="o", ms=5.2, mfc="white", mec=F5C["base"], mew=1.0, ls="none", zorder=5)
    # at B0: the vertical gap is the communication saving
    ax.annotate("", xy=(B0, Ht), xytext=(B0, Hb0),
                arrowprops=dict(arrowstyle="-|>", color=F5C["search_txt"], lw=0.8, mutation_scale=6, shrinkA=4,
                                shrinkB=4), zorder=4)
    ax.text(B0 + 0.012, Ht + 190, f"−{100 * (1 - Ht / Hb0):.1f}% H", fontsize=FS5_NOTE,
            color=F5C["search_txt"], ha="left", va="center")
    # at H_search: the horizontal gap is the equivalent bandwidth
    ax.annotate("", xy=(Beq, Ht), xytext=(B0, Ht),
                arrowprops=dict(arrowstyle="-|>", color=F5C["search_txt"], lw=0.8, ls=(0, (3, 2)),
                                mutation_scale=6, shrinkA=4, shrinkB=3), zorder=4)
    ax.text(Beq + 0.012, Ht + 25, f"+{100 * float(eq['g_bw']):.1f}% B\nat equal H", fontsize=FS5_NOTE,
            color=F5C["search_txt"], ha="left", va="bottom", linespacing=1.15)
    ax.plot([Beq, Beq], [1420, Ht], color=F5C["search_txt"], lw=0.6, ls=(0, (1.5, 1.5)), zorder=2)
    ax.plot([B0, B0], [1610, Ht], color="#99a3aa", lw=0.6, ls=(0, (1.5, 1.5)), zorder=2)
    ax.text(Beq + 0.008, 1560, f"B$_\\mathrm{{eq}}$ = {Beq:.2f}", fontsize=FS5_NOTE, color=F5C["search_txt"],
            ha="left", va="bottom")
    ax.text(B0, 1440, "B$_0$", fontsize=FS5_NOTE, color="#6f7378", ha="center", va="bottom")
    ax.set_xlim(0.3, 0.65); ax.set_ylim(1400, 3600)
    ax.set_xticks([0.3, 0.4, 0.5, 0.6]); ax.set_yticks([1500, 2000, 2500, 3000, 3500])
    ax.set_yticklabels(["1.5", "2.0", "2.5", "3.0", "3.5"])
    ax.set_xlabel("Mesh bandwidth (GB/s)", fontsize=FS3["axis"], labelpad=1.5)
    ax.set_ylabel("H (s)", fontsize=FS3["axis"], labelpad=2)
    ax.set_title(title, fontsize=FS3["title"], loc="left", pad=4.8)
    ax.legend(fontsize=FS3["tiny"], loc="upper right", frameon=False, handlelength=1.2, handletextpad=0.3,
              labelspacing=0.2, borderaxespad=0.1, markerscale=0.8)
    _tidy(ax)
    return eq


def _fig5_xtype(axes, size=4.8):
    """The x tick labels and x-axis titles at the Fig. 6 / 7 size; the y axes keep theirs."""
    for ax in axes:
        ax.tick_params(axis="x", labelsize=size)
        ax.xaxis.label.set_fontsize(size)


PANEL_ORDER = "(a) latency ladder, (b) by hand-off kind, (c) latency-energy with the clouds inset, (d) bandwidth equivalent"


def fig5():
    SRC = ["analysis/v7/gemma_panel_a.csv", "analysis/v6/gemma_candidates.csv", "analysis/v6/gemma_stage_breakdown.csv",
           "analysis/v7/gemma_bandwidth_curve.csv", "analysis/v6/gemma_bandwidth_equivalence.csv",
           "analysis/v7/gemma_checks.json"]
    # page width, like the v2 Fig. 4: (a) wide and short over (d); (b) over (c);
    # the left column's axes share their left and right edges, so do the right column's
    W = 6.3
    L1, R1 = 0.62, 4.02                              # (a) / (c)
    L2, R2 = 4.48, 5.78                              # (b) / (d)
    top, ha, rgap, hd, bot = 0.26, 1.10, 0.46, 1.05, 0.30
    H = top + ha + rgap + hd + bot
    fig = plt.figure(figsize=(W, H))
    ya = bot + hd + rgap
    axa = fig.add_axes([L1 / W, ya / H, (R1 - L1) / W, ha / H])
    axb = fig.add_axes([L2 / W, ya / H, (R2 - L2) / W, ha / H])
    axd = fig.add_axes([L1 / W, bot / H, (R1 - L1) / W, hd / H])
    axc = fig.add_axes([L2 / W, bot / H, (R2 - L2) / W, hd / H])
    order, base, rep, dist = _fig5a(axa); rows_b, tot_b, tot_s = _fig5b(axb); eq = _fig5c(axc); d = _fig5d(axd)
    eta = 1 - rep["H"] / base["H"]
    _fig5_xtype((axa, axb, axc, axd))
    pa = read_csv(os.path.join(V7, "gemma_panel_a.csv"))
    prow = next(r for r in pa if r["role"].startswith("search representative"))
    meta = {"config_id": prow["config_id"], "protocol_id": prow["protocol_id"],
            "panel_order": PANEL_ORDER,
            "panel_a": {"bars": {r["layout"]: {"T_s": r["T"], "H_s": r["H"], "non_comm_s": r["T"] - r["H"]}
                                 for r in order},
                        "random_fills": {"n": len(dist["random"]), "T_min_s": dist["random"][0],
                                         "T_median_s": float(np.median(dist["random"])), "T_max_s": dist["random"][-1]},
                        "search_endpoints": {"n": len(dist["search"]), "T_min_s": dist["search"][0],
                                             "T_max_s": dist["search"][-1]},
                        "best_random": base["layout"], "representative": rep["layout"],
                        "G_pair_pct": 100 * (1 - rep["T"] / base["T"]),
                        "below_default_pct": 100 * (1 - rep["T"] / order[0]["T"])},
            "panel_d": d,
            "eta_pair": eta,
            "seed_statistics": {k: prow[k] for k in ("seed_H_min_s", "seed_H_median_s", "seed_H_max_s", "n_seeds")},
            "panel_b": {"by_kind_ms": rows_b, "total_baseline_ms": tot_b, "total_search_ms": tot_s,
                        "total_saved_ms": tot_b - tot_s},
            "panel_c": {k: eq[k] for k in ("B_ref_gbps", "B_eq_gbps", "g_bw", "H_search_at_B_ref_s",
                                           "H_baseline_at_B_ref_s", "held_fixed", "dominant_resource_near_root")}}
    save(fig, "fig5_gemma_result", composite=True, sources=SRC, meta=meta,
         note="single column: (a) communication time of all evaluated layouts with the random / search "
              "distributions inset, (b) baseline -> search per hand-off kind, (c) equivalent mesh bandwidth, "
              "(d) latency vs dynamic energy of all candidates")
    dump_csv("fig5b_by_kind", rows_b, ["kind", "baseline_ms", "search_ms", "saved_ms"])


# =====================================================================
# Fig. 6  the fixed nine cells: three models x three resource
# configurations; per cell the best named rule, the 500 random fills and
# the ten search seeds against the default fill; one column
# =====================================================================
FAM6 = [("reference 8-macro central K=1", "(a) Reference: 8 macros/die, central unit"),
        ("capacity 16-macro central K=1", "(b) Capacity: 16 macros/die, central unit"),
        ("distributed K=4 fixed-total head groups", "(c) Distributed: 8 macros/die, 4 head-group units")]
MOD6 = [("opt1.3b", "OPT-1.3B"), ("opt6.7b", "OPT-6.7B"), ("gemma7b", "Gemma-7B"), ("opt13b", "OPT-13B")]
# OPT-1.3B per family: (unit, config id, summary row source); the e11 confirmation units, the nine cells' protocol
SMALL6 = {FAM6[0][0]: ("e11_small", "opt1.3b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1", "manifest"),
          FAM6[1][0]: ("e11_small_cap", "opt1.3b_prefill512_colrow_sq_mesh_xy_k2_b0.4_m16_offcenterK1", "manifest"),
          FAM6[2][0]: ("e11_small_head", "opt1.3b_prefill512_colrow_14x14_mesh_xy_k2_b0.4_offcenterK4TH", "record")}
# the card's four-bar example: deep blue (72,80,152), blue (90,150,204), green (165,197,130); thin dark edges
# yellow (249,239,124) / green (165,197,130) / blue (90,150,204) from the card's example, no edges
F6C = dict(rule="#f9ef7c", rule_txt="#8a7a2a", random="#a5c582", random_txt="#6f8f52", best="#3f7f93",
           search="#68b4ce", search_txt="#3f7f93", default="#8f949a", edge="#2b2f33")
MOD6_SHORT = {"opt1.3b": "OPT\n1.3B", "opt6.7b": "OPT\n6.7B", "gemma7b": "Gemma\n7B", "opt13b": "OPT\n13B"}
RAW6 = "/data/yuxinr/cimloop/analysis_v4"                 # the confirmation units' candidate tables


def _small6_from_record(unit, cid):
    """A nine-cell-style summary straight from a v4 deployment record: the
    deterministic quantities and the per-seed best-of-three runs (the
    speed-up, eta and G against the best baseline), as the v7 exporters
    compute them. None when the unit has not been run."""
    from scripts import v7_common as V
    from scripts import v6_common as C
    try:
        rec = C.find_record(unit, cid)
    except (KeyError, FileNotFoundError):
        return None, None
    if rec.get("status") not in (None, "done", "ok") and "candidates" not in rec:
        return None, None
    Hf = lambda r: r["H_s"] + r["prop_s"]
    lib, runs = rec["candidates"], rec["search"]["runs"]
    Hd, Hb = Hf(lib["sequential"]), Hf(lib[rec["strongest"]])
    R = rec["N_s"] + rec["F_s"]; Tb = R + Hb
    best = {}
    for n, r in runs.items():
        if r["sa_seed"] not in best or r["T_s"] < runs[best[r["sa_seed"]]]["T_s"]:
            best[r["sa_seed"]] = n
    sd = [{"config_id": cid, "seed": s, "best_run": n, "H_full_s": Hf(runs[n]), "T_s": runs[n]["T_s"],
           "comm_speedup_H_default_over_H": Hd / Hf(runs[n]), "eta_vs_best_baseline": 1 - Hf(runs[n]) / Hb,
           "G_vs_best_baseline": 1 - runs[n]["T_s"] / Tb} for s, n in sorted(best.items())]
    gx, gy = rec["grid"]
    row = {"n_cim_dies": rec["n_dies"], "grid": f"{gx}x{gy}", "n_units": len(rec["attention"]["hubs"]),
           "strongest_named_rule": rec["strongest_rule"], "best_baseline": rec["strongest"],
           "search_representative": rec["search"]["headline"], "protocol_id": V.protocol_id(rec),
           "H_default_s": Hd, "speedup_best": Hd / Hb}
    return row, sd


def _fig6_cells():
    """The nine main cells. Per cell: the default fill and the strongest
    named rule (deterministic), the 500 random fills of the pool (median,
    quartiles, best of 500) and the ten confirmation seeds (per seed the
    best of three starts; median, quartiles), all as H_default / H; eta of
    the search against the best random (seed median) for the label."""
    cfg = [r for r in read_csv(os.path.join(V7, "ninecell_configurations.csv")) if r["panel"] in ("a", "b", "c")]
    assert len(cfg) == 9                              # the nine cells; OPT-1.3B is appended below
    met = {}
    for r in read_csv(os.path.join(V7, "ninecell_metrics.csv")):
        met[(r["config_id"], r["quantity"], r["statistic"])] = float(r["value"])
    seeds = read_csv(os.path.join(V7, "ninecell_seed_statistics.csv"))
    # OPT-1.3B, reference configuration (8 macros / die, central K = 1, prefill 512): the small-model batch, same protocol
    sm_man = {r["config_id"]: r for r in read_csv(os.path.join(V7, "small_model_manifest.csv"))}
    sm_seeds = read_csv(os.path.join(V7, "small_model_seed_statistics.csv"))
    for fam, (unit, cid, source) in SMALL6.items():
        if source == "manifest":                      # exported by the small-model batch
            m = sm_man[cid]
            assert m["protocol_id"] == cfg[0]["protocol_id"], (m["protocol_id"], cfg[0]["protocol_id"])
            row = {"n_cim_dies": m["n_cim_dies"], "grid": m["grid"], "n_units": m["n_units"],
                   "strongest_named_rule": m["strongest_named_rule"], "best_baseline": m["best_baseline"],
                   "search_representative": m["search_representative"], "protocol_id": m["protocol_id"],
                   "H_default_s": float(m["H_default_s"]), "speedup_best": float(m["comm_speedup_default_over_best"])}
            sd = [r for r in sm_seeds if r["config_id"] == cid]
        else:                                         # straight from the deployment record (the K = 4 head-group run)
            row, sd = _small6_from_record(unit, cid)
            if row is None:
                continue
            assert row["protocol_id"] == cfg[0]["protocol_id"], (row["protocol_id"], cfg[0]["protocol_id"])
        cfg.append({"family": fam, "model": "opt1.3b", "config_id": cid, "record_unit": unit,
                    **{k: row[k] for k in ("n_cim_dies", "grid", "n_units", "strongest_named_rule", "best_baseline",
                                           "search_representative", "protocol_id")}})
        met[(cid, "H_default_s", "deterministic")] = row["H_default_s"]
        met[(cid, "comm_speedup_H_default_over_H_best_baseline", "deterministic")] = row["speedup_best"]
        for q in ("comm_speedup_H_default_over_H", "eta_vs_best_baseline", "G_vs_best_baseline"):
            met[(cid, q, "seed_median")] = float(np.median([float(r[q]) for r in sd]))
        seeds += sd
    cells = []
    for c in cfg:
        cid = c["config_id"]
        pool = [r for r in read_csv(os.path.join(RAW6, c["record_unit"], "candidates.csv")) if r["config_id"] == cid]
        H = {r["layout"]: float(r["H_ms"]) / 1e3 for r in pool}
        Hd = met[(cid, "H_default_s", "deterministic")]
        assert abs(H["sequential"] - Hd) < 2e-4 * Hd
        rnd = np.array(sorted(Hd / v for k, v in H.items() if k.startswith("random_s")))
        best = met[(cid, "comm_speedup_H_default_over_H_best_baseline", "deterministic")]
        assert len(rnd) == 500 and abs(rnd[-1] / best - 1) < 5e-4      # the pool table is rounded to microseconds
        rnd[-1] = best
        sea = np.array(sorted(float(r["comm_speedup_H_default_over_H"]) for r in seeds if r["config_id"] == cid))
        assert len(sea) == 10 and abs(np.median(sea) - met[(cid, "comm_speedup_H_default_over_H", "seed_median")]) < 1e-9
        cells.append({"family": c["family"], "model": c["model"], "config_id": cid, "record_unit": c["record_unit"],
                      "n_cim_dies": int(c["n_cim_dies"]), "grid": c["grid"], "n_units": int(c["n_units"]),
                      "best_rule": c["strongest_named_rule"], "best_rule_speedup": Hd / H[c["strongest_named_rule"]],
                      "rules": {k: Hd / v for k, v in H.items() if not k.startswith("random_s") and k != "sequential"},
                      "random_all": rnd.tolist(), "search_all": sea.tolist(),
                      "random_n": len(rnd), "random_median": float(np.median(rnd)),
                      "random_q25": float(np.percentile(rnd, 25)), "random_q75": float(np.percentile(rnd, 75)),
                      "random_min": float(rnd[0]), "random_best": float(rnd[-1]), "best_random_id": c["best_baseline"],
                      "search_n": len(sea), "search_median": float(np.median(sea)),
                      "search_q25": float(np.percentile(sea, 25)), "search_q75": float(np.percentile(sea, 75)),
                      "search_min": float(sea[0]), "search_max": float(sea[-1]),
                      "eta_vs_best_random_median": met[(cid, "eta_vs_best_baseline", "seed_median")],
                      "eta_vs_random_median": 1 - float(np.median(rnd)) / float(np.median(sea)),
                      "G_median": met[(cid, "G_vs_best_baseline", "seed_median")],
                      "H_default_s": Hd, "search_representative": c["search_representative"]})
    return cells


def _fig6_panel(ax, cells, title, bottom, short=False, ylabel_ticks=True):
    """Per model: the best heuristic, the random pool median and the search
    seed median as bars; a T from the median up to the best result of the
    pool / of the seeds. The models present in the family, in MOD6 order."""
    mods = [(m, n) for m, n in MOD6 if any(c["model"] == m for c in cells)]
    x = np.arange(len(mods)); w = 0.26
    ax.axhline(1.0, color=F6C["default"], lw=0.7, ls=(0, (3, 2)), zorder=1.5)      # beneath the bars
    for j, (mod, _) in enumerate(mods):
        c = next(c_ for c_ in cells if c_["model"] == mod)
        ax.bar(x[j] - w, c["best_rule_speedup"], w, color=F6C["rule"], ec=F6C["edge"], lw=0.25, zorder=2)   # below the spine
        ax.bar(x[j], c["random_median"], w, color=F6C["random"], ec=F6C["edge"], lw=0.25, zorder=2)
        ax.bar(x[j] + w, c["search_median"], w, color=F6C["search"], ec=F6C["edge"], lw=0.25, zorder=2)
        for xx, lo, hi in ((x[j], c["random_median"], c["random_best"]), (x[j] + w, c["search_median"], c["search_max"])):
            if hi - lo > 0.03:                           # the T from just above the bar top to the best value
                ax.plot([xx, xx], [lo + 0.02, hi], color=INK, lw=0.6, zorder=4)
                ax.plot([xx - 0.3 * w, xx + 0.3 * w], [hi, hi], color=INK, lw=0.6, zorder=4)
        v = 100 * c["eta_vs_random_median"]
        ax.text(x[j] + w, c["search_max"] + 0.12, (f"+{v:.1f}%" if v >= 0.05 else f"{abs(v):.1f}%"), fontsize=FS3["tiny"],
                color=F6C["search_txt"], ha="center", va="bottom", zorder=6)
    ax.set_xticks(x)
    ax.set_xticklabels([(MOD6_SHORT[m] if short else n) for m, n in mods] if bottom else [], linespacing=1.0)
    ax.set_xlim(-0.6, len(mods) - 0.4); ax.set_ylim(0, 7.15); ax.set_yticks([0, 2, 4, 6])
    ax.set_yticklabels(["0", "2×", "4×", "6×"] if ylabel_ticks else [])
    _title3(ax, title)
    _tidy(ax, grid="y")
    ax.tick_params(axis="x", length=0 if not bottom else 2.0, labelsize=FS3["tick"] - (0.8 if short else 0))


def _fig6_legend(fig, W, x0):
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    h = [Line2D([], [], color=F6C["default"], lw=0.7, ls=(0, (3, 2)), label="Default fill (1×)"),
         Patch(fc=F6C["rule"], ec=F6C["edge"], lw=0.25, label="Best heuristic"),
         Patch(fc=F6C["random"], ec=F6C["edge"], lw=0.25, label="Random (median; T: best of 500)"),
         Patch(fc=F6C["search"], ec=F6C["edge"], lw=0.25, label="Isobar search (median; T: best of 10 seeds)")]
    fig.legend(handles=h, fontsize=FS3["tiny"], loc="lower center", bbox_to_anchor=(0.5 + x0 / W, 0.0), ncol=2,
               frameon=False, handlelength=1.2, handletextpad=0.3, columnspacing=0.9, labelspacing=0.2,
               borderaxespad=0.0, handleheight=0.7)


def _fig6_meta(cells):
    return {"cells": cells,
            "statistics": "Default and Best heuristic deterministic; bars = medians (500 random fills of the pool; "
                          "ten confirmation seeds, per seed the best of three starts); the T reaches the best of "
                          "the 500 / of the ten seeds; the label is the saving of the Isobar median over the random "
                          "median (1 - median speed-up ratio); every cell normalised to its own default fill",
            "baseline_per_panel": "the nine cells from the e9/e10 confirmation units; OPT-1.3B from the e11_small "
                                  "(reference: 8 macros, central K = 1), e11_small_cap (capacity: 16 macros, K = 1) and "
                                  "e11_small_head (distributed: 8 macros, K = 4 fixed-total head groups, on the 14x14 grid "
                                  "since 168 dies + 4 unit nodes do not fit 13x13) confirmation units, prefill 512, the same "
                                  "pool500_seeds5-14_objh_norm protocol; every cell normalised to its own default fill",
            "eta_vs_best_random_range_pct": [100 * min(c["eta_vs_best_random_median"] for c in cells),
                                             100 * max(c["eta_vs_best_random_median"] for c in cells)],
            "eta_vs_random_median_range_pct": [100 * min(c["eta_vs_random_median"] for c in cells),
                                               100 * max(c["eta_vs_random_median"] for c in cells)]}


def _fig6_sources(cells):
    SRC = ["analysis/v7/ninecell_configurations.csv", "analysis/v7/ninecell_metrics.csv",
           "analysis/v7/ninecell_seed_statistics.csv"]
    return SRC + sorted({os.path.join(RAW6, c["record_unit"], "candidates.csv") for c in cells})


def fig6():
    """3 x 1: the three configurations stacked, one column."""
    cells = _fig6_cells()
    W = 3.4
    Lm, Rm = 0.38, 0.04
    top, ph, gap, bot = 0.17, 0.66, 0.24, 0.44                 # bot holds the x labels and the legend
    H = top + 3 * ph + 2 * gap + bot
    fig = plt.figure(figsize=(W, H))
    axes = []
    for i, (fam, title) in enumerate(FAM6):
        y = bot + (2 - i) * (ph + gap)
        ax = fig.add_axes([Lm / W, y / H, (W - Lm - Rm) / W, ph / H])
        _fig6_panel(ax, [c for c in cells if c["family"] == fam], title, bottom=(i == 2))
        axes.append(ax)
    axes[1].set_ylabel("Communication speed-up  H$_\\mathrm{default}$ / H", fontsize=FS3["axis"], labelpad=2)
    _fig6_legend(fig, W, 0.17)
    save(fig, "fig6_ninecell", composite=True, sources=_fig6_sources(cells), meta=_fig6_meta(cells),
         note="single column, 3 x 1: reference / capacity / distributed stacked; per model best heuristic, "
              "random median (T to best of 500), search median (T to best seed); H_default / H")
    flat = [{k: v for k, v in c.items() if k not in ("rules", "random_all", "search_all")} for c in cells]
    dump_csv("fig6_ninecell", flat, list(flat[0].keys()))


def fig6_row():
    """1 x 3: the three configurations side by side, narrow panels sharing the y scale."""
    cells = _fig6_cells()
    W = 3.4
    Lm, Rm, G = 0.38, 0.04, 0.10
    n_cl = [sum(1 for c in cells if c["family"] == fam) for fam, _ in FAM6]      # clusters per panel (4, 3, 3)
    pw = [(W - Lm - Rm - 2 * G) * n / sum(n_cl) for n in n_cl]
    top, ph, bot = 0.17, 0.945, 0.38                         # bot holds the two-line x labels and the legend
    H = top + ph + bot
    fig = plt.figure(figsize=(W, H))
    short = ["(a) Reference", "(b) Capacity", "(c) Distributed"]
    x0 = Lm
    for i, (fam, _) in enumerate(FAM6):
        ax = fig.add_axes([x0 / W, bot / H, pw[i] / W, ph / H]); x0 += pw[i] + G
        _fig6_panel(ax, [c for c in cells if c["family"] == fam], short[i], bottom=True, short=True,
                    ylabel_ticks=(i == 0))
        if i == 0:
            ax.set_ylabel("Comm. speed-up  H$_\\mathrm{default}$ / H", fontsize=FS3["axis"], labelpad=2)
    _fig6_legend(fig, W, 0.17)
    save(fig, "fig6_ninecell_row", composite=True, sources=_fig6_sources(cells), meta=_fig6_meta(cells),
         note="single column, 1 x 3: reference / capacity / distributed side by side, shared y scale")


# =====================================================================
# Fig. 7  why the gain moves with the configuration: capacity (a),
# resource organisation (b), execution share over the context length (c)
# =====================================================================
# the card: deep blue (70,96,173), light blue (104,180,206), green (165,197,130), yellow (243,222,103)
# (b): the non-communication base as the gradient (70,96,173) -> (90,150,204); the communication segment on
# top keeps the baseline green (165,197,130) / Isobar light blue (104,180,206) of the other figures
F7 = dict(nat="#4660ad", common="#a5c582", R="#aeb4ba", Rother="#dfe4e8", Hb="#a5c582", Hs="#68b4ce",
          eta="#68b4ce", eta_txt="#3f7f93", G="#a5c582", G_txt="#6f8f52", r0="#9a9a9a", env="#f3de67")
# the v2 Fig. 6 line / marker scale as printed (lw 1.4, circle 4.5, square 3.5, diamond 3.7 at 4.78 in -> x0.73)
LW7 = 1.0
FS7_NOTE = 4.8                                         # in-panel annotations of (c)
MS7 = {"o": 3.3, "s": 2.6, "^": 3.3, "v": 3.3, "D": 2.7}
EXPL = "exploration"                                  # one protocol for every point of the three panels


# light to dark with the model size (yellow, green, light blue, deep blue); drawn dark first so lighter lines lie on top
MODEL7 = [("opt1.3b", "OPT-1.3B", "#f3de67", "v"), ("opt6.7b", "OPT-6.7B", "#80cdbb", "o"),
          ("gemma7b", "Gemma-7B", "#68b4ce", "s"), ("opt13b", "OPT-13B", "#4660ad", "^")]
MACROS7 = {m: [4, 8, 16, 32] for m in ("opt1.3b", "opt6.7b", "gemma7b", "opt13b")}


def _fig7a(ax):
    """(a) prefill S=512, central unit: eta_comm against the macros per die
    for the three models on their natural grids (solid), and Gemma on the
    common 36x36 grid (dashed) as the control; exploration protocol
    throughout, each point against its own best baseline."""
    cap = [r for r in read_csv(os.path.join(V7, "offload_capacity.csv")) + read_csv(os.path.join(V7, "offload_capacity_small.csv"))
           if r["protocol_group"] == EXPL and r["status"] == "done"]
    com = [r for r in read_csv(os.path.join(V7, "offload_capacity_common_grid.csv"))
           if r["model"] == "gemma7b" and r["protocol_group"] == EXPL and r["grid_kind"] == "common 36x36"]
    com.sort(key=lambda r: int(r["die_macros"]))
    xm = lambda rows: [np.log2(int(r["die_macros"])) for r in rows]
    ye = lambda rows: [100 * float(r["eta_comm"]) for r in rows]
    nat = {}
    for z, (mod, name, col, mk) in enumerate(reversed(MODEL7)):
        rows = sorted((r for r in cap if r["model"] == mod), key=lambda r: int(r["die_macros"]))
        assert [int(r["die_macros"]) for r in rows] == MACROS7[mod], mod
        nat[mod] = rows
        ax.plot(xm(rows), ye(rows), color=col, lw=LW7, marker=mk, ms=MS7[mk], zorder=4 + z, label=name,
                clip_on=False)
    ax.plot(xm(com), ye(com), color=F7["common"], lw=LW7, marker="D", ms=MS7["D"], zorder=9,
            label="Gemma, 36×36")
    ax.set_xticks([2, 3, 4, 5]); ax.set_xticklabels(["4", "8", "16", "32"])
    ax.set_xlim(1.6, 5.4); ax.set_ylim(0, 42); ax.set_yticks([0, 10, 20, 30])
    ax.set_xlabel("Macros per die", fontsize=FS3["axis"], labelpad=1.5)
    ax.set_ylabel("Comm. saving η (%)", fontsize=FS3["axis"], labelpad=2)
    _title3(ax, "(a) CIM capacity")
    hl, ll = ax.get_legend_handles_labels()            # two right-aligned rows: the three OPT models, then Gemma and its control
    kw = dict(fontsize=3.6, frameon=False, handlelength=0.8, handletextpad=0.2, columnspacing=0.5, borderaxespad=0.0,
              markerscale=0.85, borderpad=0.0)
    r1 = ["OPT-1.3B", "OPT-6.7B", "OPT-13B"]; r2 = ["Gemma-7B", "Gemma, 36×36"]
    leg1 = ax.legend([hl[ll.index(n)] for n in r1], r1, loc="upper right", bbox_to_anchor=(1.0, 0.99), ncol=3, **kw)
    ax.add_artist(leg1)
    ax.legend([hl[ll.index(n)] for n in r2], r2, loc="upper right", bbox_to_anchor=(1.0, 0.90), ncol=2, **kw)
    _tidy(ax)
    return nat, com


def _fig7b(ax):
    """(b) Gemma prefill S=512, the same total digital resource organised as
    one central unit, four per-layer groups or four head groups: baseline
    and search backbone time, split into the fixed part R and the
    communication H (exploration protocol)."""
    rows = [r for r in read_csv(os.path.join(V7, "resource_organization_comparison.csv"))
            if r["model"] == "gemma7b" and r["phase"] == "prefill" and r["unit"] == "e9_head"
            and r["protocol_group"] == EXPL]
    pick = {"K=1 (fixed-total = per-unit)": "K=1\ncentral", "K=4 fixed-total layer groups": "K=4\nlayer",
            "K=4 fixed-total head groups": "K=4\nhead"}
    sel = [next(r for r in rows if r["organisation"] == k) for k in pick]
    x = np.arange(len(sel)); w = 0.255; seam = 0.03
    out = []
    for j, r in enumerate(sel):
        R = float(r["R_s"]) * 1e3; Hb = float(r["H_best_baseline_s"]) * 1e3; Hs = float(r["H_search_s"]) * 1e3
        Rcim = (float(r["R_cim_compute_s"]) + float(r["R_cim_write_s"])) * 1e3
        Rother = (float(r["R_digital_elementwise_s"]) + float(r["R_unit_compute_s"]) + float(r["R_unit_kv_s"])) * 1e3
        assert abs(Rcim + Rother - R) < 1e-6
        for dx, H, col in ((-(w + seam) / 2, Hb, F7["Hb"]), ((w + seam) / 2, Hs, F7["Hs"])):
            ax.bar(x[j] + dx, Rcim, w, color=F7["R"], lw=0, zorder=2)        # below the spine (2.5)
            ax.bar(x[j] + dx, Rother, w, bottom=Rcim, color=F7["Rother"], lw=0, zorder=2)
            ax.bar(x[j] + dx, H, w, bottom=R, color=col, lw=0, zorder=2)
            ax.text(x[j] + dx, R + H + 40, f"{(R + H) / 1e3:.2f}", fontsize=FS3["tiny"], color="#555b61",
                    ha="center", va="bottom")
        out.append({"organisation": r["organisation"], "R_ms": R, "R_cim_ms": Rcim, "R_other_ms": Rother,
                    "H_baseline_ms": Hb, "H_search_ms": Hs,
                    "T_baseline_ms": R + Hb, "T_search_ms": R + Hs, "eta_comm": float(r["eta_comm"]),
                    "G": float(r["G"]), "config_id": r["config_id"]})
    ax.set_xticks(x); ax.set_xticklabels(list(pick.values()), linespacing=1.0)
    ax.set_xlim(-0.6, len(sel) - 0.4); ax.set_ylim(0, 4700); ax.set_yticks([0, 1000, 2000, 3000, 4000])
    ax.set_yticklabels(["0", "1", "2", "3", "4"])
    ax.set_ylabel("Backbone time T (s)", fontsize=FS3["axis"], labelpad=2)
    _title3(ax, "(b) Resource organisation")
    from matplotlib.patches import Patch
    h = [Patch(fc=F7["Hs"], label="Comm., Isobar"), Patch(fc=F7["Hb"], label="Comm., baseline"),
         Patch(fc=F7["Rother"], label="Digital, K/V"), Patch(fc=F7["R"], label="CIM compute")]
    ax.legend(handles=h, fontsize=FS3["tiny"], loc="upper right", frameon=False, ncol=2, handlelength=1.0,
              handletextpad=0.4, labelspacing=0.2, columnspacing=0.8, borderaxespad=0.1, handleheight=0.7)
    _tidy(ax, grid="y")
    return out


def _fig7c(ax, legend=True):
    """(c) The frozen Gemma pair of Fig. 5 (random_s209 / sa_random_best_s5)
    re-priced over the mesh bandwidth (die ports at kappa B, hub / K/V /
    digital resources at the reference setting): the communication saving
    eta, the baseline communication share r0 and the backbone saving
    G = eta r0; the six-layout crossover envelope of Fig. 1 shaded, the
    0.4 GB/s working point marked."""
    rows = read_csv(os.path.join(V7, "gemma_bandwidth_response.csv"))
    meta = json.load(open(os.path.join(V7, "gemma_bandwidth_response.json")))
    B = np.array([float(r["B_mesh_gbps"]) for r in rows])
    eta = 100 * np.array([float(r["eta_comm"]) for r in rows]); G = 100 * np.array([float(r["G"]) for r in rows])
    r0 = 100 * np.array([float(r["r0"]) for r in rows])
    assert np.allclose(G, eta * r0 / 100, atol=1e-9)
    lo, hi = meta["envelope"]["B_minus_gbps"], meta["envelope"]["B_plus_gbps"]
    ax.axvspan(lo, hi, color=F7["env"], alpha=0.28, lw=0, zorder=1)
    ax.text(np.sqrt(lo * hi), 57, "crossover\nenvelope", fontsize=FS7_NOTE, color="#8a7a2a", ha="center",
            va="center", linespacing=1.1)
    ax.axvline(0.4, color="#9a9a9a", lw=0.6, ls=(0, (1.5, 1.5)), zorder=2)
    ax.text(0.4 / 1.08, 3, "B$_0$", fontsize=FS7_NOTE, color="#6f7378", ha="right", va="bottom")
    ax.plot(B, eta, color=F7["eta"], lw=LW7, zorder=4, label="Comm. saving η")
    ax.plot(B, G, color=F7["G"], lw=LW7, zorder=4, label="Backbone saving G")
    ax.plot(B, r0, color=F7["r0"], lw=LW7, ls=(0, (1.5, 1.5)), zorder=3, label="Baseline comm. share r₀")
    hub_b = [float(r["B_mesh_gbps"]) for r in rows if int(r["search_binding_hub_port"]) > 0]
    hub_s = [float(r["B_mesh_gbps"]) for r in rows if int(r["baseline_binding_hub_port"]) > 0]
    B_hub = min(hub_b + hub_s)                           # the first point with a hub-bound hand-off
    ax.axvline(B_hub, color="#9a9a9a", lw=0.6, ls=(0, (1.5, 1.5)), zorder=2)
    ax.text(B_hub * 1.08, 36, "fixed hub\nbinds", fontsize=FS7_NOTE, color="#6f7378", ha="left", va="center",
            linespacing=1.1)
    k = int(np.argmin(abs(B - 0.4)))
    for arr, col in ((eta, F7["eta"]), (G, F7["G"]), (r0, F7["r0"])):
        ax.plot([0.4], [arr[k]], marker="o", ms=MS7["o"], color=col, ls="none", zorder=5)
    for arr, col, off, ha in ((eta, F7["eta_txt"], (3, 3), "left"), (G, F7["G_txt"], (3, -3), "left"),
                              (r0, "#6f7378", (4, 3), "left")):
        ax.annotate(f"{arr[k]:.1f}", (0.4, arr[k]), textcoords="offset points", xytext=off, ha=ha,
                    va="bottom" if off[1] > 0 else "top", fontsize=FS7_NOTE, color=col)
    ax.set_xscale("log"); ax.set_xlim(0.2, 12.5); ax.set_xticks([0.2, 0.4, 1, 2, 4, 10])
    ax.set_xticklabels(["0.2", "0.4", "1", "2", "4", "10"])
    ax.set_ylim(0, 95); ax.set_yticks([0, 20, 40, 60, 80])
    ax.set_xlabel("Mesh bandwidth (GB/s)", fontsize=FS3["axis"], labelpad=1.5)
    ax.set_ylabel("Share / saving (%)", fontsize=FS3["axis"], labelpad=2)
    _title3(ax, "(c) Bandwidth response")
    if legend:
        ax.legend(fontsize=3.6, loc="upper right", frameon=False,
                  handlelength=1.6, handletextpad=0.4, labelspacing=0.2, borderaxespad=0.1)
    _tidy(ax)
    return {"n_points": len(rows), "B_range_gbps": [float(B[0]), float(B[-1])], "layout_pair": meta["layout_pair"],
            "bandwidth_scaling": meta["bandwidth_scaling"], "envelope": meta["envelope"],
            "at_B_ref": {"eta_pct": float(eta[k]), "r0_pct": float(r0[k]), "G_pct": float(G[k])},
            "hub_binding": {"first_B_search_gbps": min(hub_b), "first_B_baseline_gbps": min(hub_s),
                            "hub_bound_handoffs_at_12.5": {"baseline": int(rows[-1]["baseline_binding_hub_port"]),
                                                           "search": int(rows[-1]["search_binding_hub_port"])},
                            "note": "the 12.5 GB/s hub interface is held fixed; above B_hub the mesh no longer "
                                    "limits every hand-off, so the search layout's link advantage shrinks and eta "
                                    "falls"},
            "eta_range_pct": [float(eta.min()), float(eta.max())], "G_range_pct": [float(G.min()), float(G.max())],
            "r0_range_pct": [float(r0.min()), float(r0.max())]}


def _fig7d(ax, legend=True):
    """(d) Gemma on the central reference configuration, context length
    128-4096 (prefill: input length; decode: cache length, one new token):
    the communication saving eta and the backbone saving G of the actual
    search pair at each length, prefill solid and decode dashed; r0 is
    left to the text."""
    allr = [r for r in read_csv(os.path.join(V7, "workload_length_sweep.csv"))
            if r["model"] == "gemma7b" and r["status"] == "done" and r["protocol_group"] == EXPL]
    out = []
    for phase, ls, fill in (("prefill", "-", True), ("decode", (0, (1.8, 1.4)), False)):
        rows = sorted((r for r in allr if r["phase"] == phase), key=lambda r: int(r["S"]))
        S = [int(r["S"]) for r in rows]; xs = np.log2(S)
        eta = [100 * float(r["eta_comm"]) for r in rows]; G = [100 * float(r["G"]) for r in rows]
        r0 = [100 * float(r["r0"]) for r in rows]
        for arr, col, mk, lab in ((eta, F7["eta"], "o", "η"), (G, F7["G"], "s", "G")):
            ax.plot(xs, arr, color=col, lw=0.7, ls=ls, marker=mk, ms=MS7[mk] if fill else MS7[mk] + 0.5,
                    mfc=col if fill else "white", mew=0.8, zorder=4, label=f"{lab}, {phase}")
        ax.annotate(f"{G[-1]:.1f}", (xs[-1], G[-1]), textcoords="offset points", xytext=(4, 0), ha="left",
                    va="center", fontsize=FS3["tiny"], color=F7["G_txt"])
        out += [{"phase": phase, "S": s, "eta_comm_pct": e, "G_pct": g, "r0_pct": r, "R_ms": 1e3 * float(rw["R_s"]),
                 "H_best_baseline_ms": 1e3 * float(rw["H_best_baseline_s"]), "H_search_ms": 1e3 * float(rw["H_search_s"])}
                for s, e, g, r, rw in zip(S, eta, G, r0, rows)]
    ax.set_xticks(xs); ax.set_xticklabels(["128", "", "512", "", "2048", ""])
    ax.set_xlim(xs[0] - 0.75, xs[-1] + 0.75); ax.set_ylim(0, 34); ax.set_yticks([0, 10, 20, 30])
    ax.set_xlabel("Context length (tokens)", fontsize=FS3["axis"], labelpad=1.5)
    ax.set_ylabel("Saving (%)", fontsize=FS3["axis"], labelpad=2)
    _title3(ax, "(d) Context length")
    if legend:
        ax.legend(fontsize=FS3["tiny"], loc="upper right", frameon=False, ncol=2, handlelength=2.6,
                  handletextpad=0.4, labelspacing=0.2, columnspacing=0.8, borderaxespad=0.1)
    _tidy(ax)
    return out


def fig7():
    SRC = ["analysis/v7/offload_capacity.csv", "analysis/v7/offload_capacity_small.csv",
           "analysis/v7/offload_capacity_common_grid.csv",
           "analysis/v7/resource_organization_comparison.csv", "analysis/v7/gemma_bandwidth_response.csv",
           "analysis/v7/gemma_bandwidth_response.json", "analysis/v7/workload_length_sweep.csv"]
    W = 3.4
    L1, R1 = 0.40, 1.60                               # (a) / (c)   both columns 1.20 in wide
    L2, R2 = 1.98, 3.18                               # (b) / (d)
    top, h1, rgap, h2, bot = 0.17, 0.855, 0.40, 0.855, 0.30
    H = top + h1 + rgap + h2 + bot
    fig = plt.figure(figsize=(W, H))
    y1 = bot + h2 + rgap
    axa = fig.add_axes([L1 / W, y1 / H, (R1 - L1) / W, h1 / H])
    axb = fig.add_axes([L2 / W, y1 / H, (R2 - L2) / W, h1 / H])
    axc = fig.add_axes([L1 / W, bot / H, (R1 - L1) / W, h2 / H])
    axd = fig.add_axes([L2 / W, bot / H, (R2 - L2) / W, h2 / H])
    nat, com = _fig7a(axa); org = _fig7b(axb); bw = _fig7c(axc, legend=True); sweep = _fig7d(axd, legend=True)
    for ax in (axa, axb, axc, axd):                   # axis type as printed in the (wider) Fig. 6 row
        ax.tick_params(axis="both", labelsize=4.8)
        ax.xaxis.label.set_fontsize(4.8); ax.yaxis.label.set_fontsize(4.8)
    meta = {"protocol_ab_d": "exploration (pool100_seeds0-4_objt_norm) for every point of (a), (b), (d); the OPT-1.3B "
                             "points of (a) from the e11_small_expl / e11_small_cap_expl deployments under the same protocol "
                             "at 4 / 8 / 16 / 32 macros (accounts measured in the container, no extrapolation)",
            "panel_a": {"natural": {m: [{k: r.get(k, "") for k in ("config_id", "protocol_id", "die_macros", "grid", "n_cim_dies",
                                                                     "n_flows_total", "n_handoffs_total", "eta_comm", "G", "r0",
                                                                     "H_search_s", "T_search_s")}
                                        for r in rows] for m, rows in nat.items()},
                        "common_36x36": [{k: r[k] for k in ("config_id", "die_macros", "grid", "n_cim_dies", "eta_comm", "G")}
                                         for r in com]},
            "panel_b": org,
            "panel_c": {**bw, "protocol": "the confirmation pair of Fig. 5 (pool500_seeds5-14_objh_norm), frozen and "
                                          "re-priced; no search"},
            "panel_d": sweep}
    save(fig, "fig7_mechanisms", composite=True, sources=SRC, meta=meta,
         note="single column, 2 x 2: (a) eta vs macros/die for the three models (natural grids) and Gemma's common "
              "grid, (b) R + H stacked bars for "
              "K=1 / K=4 layer / K=4 head with R split into CIM compute and digital / K/V, (c) eta, G and r0 of the "
              "frozen Gemma pair over the mesh bandwidth with the six-layout envelope shaded and the hub-binding onset "
              "marked, (d) eta and G over the context length, prefill and decode")
    dump_csv("fig7c_bandwidth_response", [{k: r[k] for k in ("B_mesh_gbps", "R_s", "H_baseline_s", "H_search_s",
                                                              "eta_comm", "r0", "G", "in_envelope", "is_B_ref")}
                                          for r in read_csv(os.path.join(V7, "gemma_bandwidth_response.csv"))],
             ["B_mesh_gbps", "R_s", "H_baseline_s", "H_search_s", "eta_comm", "r0", "G", "in_envelope", "is_B_ref"])
    dump_csv("fig7d_length_sweep", sweep, list(sweep[0].keys()))
    dump_csv("fig7b_organisation", org, list(org[0].keys()))


def fig3b_alone():
    f = plt.figure(figsize=(1.9, 1.75))
    ax = f.add_axes([0.40 / 1.9, 0.30 / 1.75, 1.46 / 1.9, 1.25 / 1.75])
    _fig3b(ax)
    save(f, "fig3b_booksim_validation", composite=False, sources=["analysis/v7/booksim_candidate_costs.csv",
                                                                   "analysis/v7/booksim_library_summary.csv"],
         note="panel (b) of Fig. 3 alone, at the composite's panel size")


def fig5_stack():
    """The same four panels, one column: (a) over (c) over (b) | (d)."""
    SRC = ["analysis/v7/gemma_panel_a.csv", "analysis/v6/gemma_candidates.csv", "analysis/v6/gemma_stage_breakdown.csv",
           "analysis/v7/gemma_bandwidth_curve.csv", "analysis/v6/gemma_bandwidth_equivalence.csv",
           "analysis/v7/gemma_checks.json"]
    W = 3.4
    L1, R1 = 0.62, 3.36                              # (a), (c)
    Lb, Rb = 0.66, 1.83                              # (b)   (b) and (d): equal width and height
    Ld, Rd = 2.19, 3.36                              # (d)
    top, ha, g1, hc, g2, hbd, bot = 0.26, 1.05, 0.46, 0.95, 0.46, 0.85, 0.30
    H = top + ha + g1 + hc + g2 + hbd + bot
    fig = plt.figure(figsize=(W, H))
    ya = bot + hbd + g2 + hc + g1; yc = bot + hbd + g2
    axa = fig.add_axes([L1 / W, ya / H, (R1 - L1) / W, ha / H])
    axc = fig.add_axes([L1 / W, yc / H, (R1 - L1) / W, hc / H])
    axb = fig.add_axes([Lb / W, bot / H, (Rb - Lb) / W, hbd / H])
    axd = fig.add_axes([Ld / W, bot / H, (Rd - Ld) / W, hbd / H])
    # _fig5c draws the bandwidth panel (lettered (d)), _fig5d the latency-energy panel (lettered (c))
    order, base, rep, dist = _fig5a(axa, note=5.5, leg=5.0, bracket_dx=1.6, arrow_drop=1.25)
    rows_b, tot_b, tot_s = _fig5b(axb, note=5.2, pad_right=560, xmax=1700, label_drop=0.8, title="(c) By hand-off kind")
    eq = _fig5c(axd, title="(d) Bandwidth equivalent")
    d = _fig5d(axc, note=5.2, inset_note=4.4, title="(b) Latency and dynamic energy")
    _fig5_xtype((axa, axb, axc, axd))
    eta = 1 - rep["H"] / base["H"]
    pa = read_csv(os.path.join(V7, "gemma_panel_a.csv"))
    prow = next(r for r in pa if r["role"].startswith("search representative"))
    meta = {"config_id": prow["config_id"], "protocol_id": prow["protocol_id"],
            "panel_order": "(a) latency ladder, (b) latency-energy with the clouds inset, (c) by hand-off kind, (d) bandwidth equivalent",
            "panel_a": {"bars": {r["layout"]: {"T_s": r["T"], "H_s": r["H"], "non_comm_s": r["T"] - r["H"]}
                                 for r in order},
                        "random_fills": {"n": len(dist["random"]), "T_min_s": dist["random"][0],
                                         "T_median_s": float(np.median(dist["random"])), "T_max_s": dist["random"][-1]},
                        "search_endpoints": {"n": len(dist["search"]), "T_min_s": dist["search"][0],
                                             "T_max_s": dist["search"][-1]},
                        "best_random": base["layout"], "representative": rep["layout"],
                        "G_pair_pct": 100 * (1 - rep["T"] / base["T"]),
                        "below_default_pct": 100 * (1 - rep["T"] / order[0]["T"])},
            "panel_d": d,
            "eta_pair": eta,
            "seed_statistics": {k: prow[k] for k in ("seed_H_min_s", "seed_H_median_s", "seed_H_max_s", "n_seeds")},
            "panel_b": {"by_kind_ms": rows_b, "total_baseline_ms": tot_b, "total_search_ms": tot_s,
                        "total_saved_ms": tot_b - tot_s},
            "panel_c": {k: eq[k] for k in ("B_ref_gbps", "B_eq_gbps", "g_bw", "H_search_at_B_ref_s",
                                           "H_baseline_at_B_ref_s", "held_fixed", "dominant_resource_near_root")}}
    save(fig, "fig5_gemma_result_stack", composite=True, sources=SRC, meta=meta,
         note="single column: (a) communication time of all evaluated layouts with the random / search "
              "distributions inset, (b) baseline -> search per hand-off kind, (c) equivalent mesh bandwidth, "
              "(d) latency vs dynamic energy of all candidates")


FIGS = {"fig3b": fig3b_alone, "fig1": fig1, "fig2": fig2, "fig2c": fig2b_gemma, "fig3": fig3, "fig4": fig4, "fig4alt": fig4_alt, "fig5": fig5, "fig5stack": fig5_stack, "fig6": fig6, "fig6row": fig6_row, "fig7": fig7}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    base = _run_dir(args.run_id)
    wanted = [w.strip() for w in args.only.split(",") if w.strip()] or list(FIGS)
    for w in wanted:
        print(f"[{w}]"); FIGS[w]()
    json.dump({"run_id": args.run_id, "code_version": CODE_VERSION, "products": PRODUCTS},
              open(os.path.join(base, "manifest.json"), "w"), indent=1)
    print(f"-> {base}")


if __name__ == "__main__":
    main()
