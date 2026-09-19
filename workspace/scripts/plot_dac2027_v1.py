"""Paper figure set v1: six candidate figure groups and their standalone
panels, drawn from the frozen experiment records into a NEW output tree.

Nothing here overwrites an existing figure: the output directory is passed
in (default analysis/figures_dac2027/<run_id>/) and must not already hold
a different run. Every panel is written as PDF (vector), SVG (editable)
and PNG (preview); the numbers behind each panel are written as JSON/CSV
next to it. The old generators and their outputs are untouched.

    python3 scripts/plot_dac2027_v1.py --run-id 20260918_v1
    python3 scripts/plot_dac2027_v1.py --run-id 20260918_v1 --only fig5,fig4

Main configuration throughout (unless a panel says otherwise): 2.7B class,
S = 512 serial prefill, 544 of 576 dies on a 24x24 mesh, XY routing,
NeuRRAM-derived row time 10.14 us, kappa = 2, 0.4 GB/s per link direction.
"""
import argparse
import csv
import json
import os
import sys

os.environ.setdefault("ISOBAR_KAPPA", "2")     # before importing the isobar module

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["pdf.fonttype"] = 42       # embedded TrueType, text stays text
matplotlib.rcParams["svg.fonttype"] = "none"   # SVG text stays editable text
matplotlib.rcParams["axes.linewidth"] = 0.7
matplotlib.rcParams["font.size"] = 8
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

from scripts import search_eval as se

A = se.A                                        # analysis/
WS = os.path.dirname(A)

# ---------------------------------------------------------------- style
COL_WIDTH, PAGE_WIDTH = 3.4, 7.16               # inches, single / double column
NAVY, SLATE, AMBER, GREEN, GREY = "#2e4a66", "#5d7ea3", "#7a5c00", "#2a7d4f", "#8c8c8c"
BRICK, CREAM, INK = "#a0522d", "#e8d9a0", "#333333"
# method families, kept identical across every figure
FAM = {"default": NAVY, "rule": AMBER, "random": GREY, "search": GREEN}
# cost decomposition
C_R, C_H = "#b6c4d2", BRICK
# one sequential ramp for network load; category colours never come from it
LOAD_CMAP = LinearSegmentedColormap.from_list(
    "isobar_load", ["#c9dceb", "#93bdd8", "#5f9cc2", "#3576a3", "#1c5280", "#0b3457"])

LAYOUT_STYLE = {                                # label, family, marker
    "default_A4": ("default fill (= sequential)", "default", "s"),
    "sequential": ("sequential", "default", "s"),
    "snake": ("snake", "default", "P"),
    "clustered": ("clustered", "rule", "^"),
    "nmap_greedy": ("nmap_greedy", "rule", "v"),
    "least_manhattan": ("least_manhattan", "rule", "<"),
    "heaviest_first": ("heaviest_first", "rule", ">"),
    "random": ("random seed 0", "random", "o"),
    "random_s1": ("random seed 1", "random", "o"),
    "random_s2": ("random seed 2", "random", "o"),
    "random_s3": ("random seed 3 (strongest)", "random", "D"),
    "random_s4": ("random seed 4", "random", "o"),
}
for _s in ("clustered", "random", "snake"):
    for _i in range(3):
        LAYOUT_STYLE[f"sa_{_s}_s{_i}"] = (f"search, {_s} start, seed {_i}", "search", "*")

OUT = {}            # filled by main(): keys panels, composites, data, preview
PRODUCTS = []       # manifest rows


def _paths(kind, name, ext):
    return os.path.join(OUT[kind], f"{name}.{ext}")


def save(fig, name, composite=False, sources=(), note=""):
    """PDF + SVG next to each other, PNG preview, one manifest row."""
    kind = "composites" if composite else "panels"
    for ext in ("pdf", "svg"):
        fig.savefig(_paths(kind, name, ext), bbox_inches="tight")
    fig.savefig(_paths("preview", name, "png"), dpi=200, bbox_inches="tight")
    plt.close(fig)
    PRODUCTS.append({"name": name, "kind": kind,
                     "files": [f"{kind}/{name}.pdf", f"{kind}/{name}.svg",
                               f"preview/{name}.png"],
                     "sources": list(sources), "note": note})
    print(f"   {kind}/{name}.pdf|svg  preview/{name}.png")


def dump_json(name, obj, sources=()):
    p = _paths("data", name, "json")
    json.dump(obj, open(p, "w"), indent=1)
    PRODUCTS.append({"name": name, "kind": "data", "files": [f"data/{name}.json"],
                     "sources": list(sources), "note": "plotting data"})
    print(f"   data/{name}.json")


def dump_csv(name, rows, fields, sources=()):
    p = _paths("data", name, "csv")
    with open(p, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    PRODUCTS.append({"name": name, "kind": "data", "files": [f"data/{name}.csv"],
                     "sources": list(sources), "note": "plotting data"})
    print(f"   data/{name}.csv")


def load(fname):
    return json.load(open(os.path.join(A, fname)))


def tidy(ax, grid="both"):
    """grid: "both" | "x" | "y" | None -- which axis gets grid lines."""
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(labelsize=7, length=2.5, pad=2)
    if grid:
        ax.grid(alpha=0.16, lw=0.5, axis=grid)
        ax.set_axisbelow(True)


# =====================================================================
# Fig. 1  the two-level placement phase diagram
# =====================================================================
def _isobar_inputs():
    from scripts import fig_phase_isobar as F
    from scripts import search_eval as _se
    W = _se.Workload2p7B()
    comp, wr, elw = W.layer_terms_s("prefill")
    L = W.cfg.n_layers
    Apkg = F.package_A(W, F.KAPPA)
    im = F.intra_die_model()
    return F, {
        "pkg": dict(a_min=min(Apkg.values()), a_max=max(Apkg.values()),
                    n_s=comp * L, f_s=(wr + elw) * L, A=Apkg),
        "die": dict(a_min=min(im["A"]), a_max=max(im["A"]),
                    n_s=max(im["compute_ref_s"].values()), f_s=im["fixed_s"]),
        "curves": F.intra_die_curves(F.SPREADS[0])}


def _panel_intra(F, d, ax, chips=True, compact=False):
    lo, hi = F.draw_panel(
        ax, d["die"]["a_min"], d["die"]["a_max"], d["die"]["n_s"], d["die"]["f_s"],
        (1e-2, 1e3), "exhaustive over P; this instance & model",
        "P = all 70 joint macro seatings, enumerated"
        if compact else
        "latency object: one die's two co-resident operators\n"
        "(a sub-problem, not the whole model)\n"
        "P = all 70 joint macro seatings, enumerated",
        ((0.20, 0.86), 1.5, (0.80, 0.13), (0.74, 0.86), (0.015, 0.015)),
        6.0, curves=d["curves"], labels=F.LABELS_MAX)
    if chips:
        from scripts import anchors as an
        h1, h4 = 1.0 / 133e-9 / 1e6, 1.0 / 520e-9 / 1e6
        ax.plot([h1], [0.4], marker="D", mfc=F.CHIP, mec=F.CHIP_TXT, ms=6, mew=0.9, ls="none", zorder=8)
        ax.plot([h4], [0.4], marker="D", mfc="white", mec=F.CHIP, ms=6, mew=1.1, ls="none", zorder=8)
        ax.text(np.sqrt(h1 * h4), 0.4 / 1.7, "HERMES, published link rate\n"
                "4-phase (open) / 1-phase (filled) MVM", fontsize=6.2,
                color=F.CHIP_TXT, ha="center", va="top", zorder=8, linespacing=1.15)
        isaac = an.chip("isaac")
        s_is = 1.0 / isaac.t_mvm_s / 1e6
        ax.plot([s_is], [isaac.ondie_gbps_per_link], marker="D", mfc=F.CHIP,
                mec=F.CHIP_TXT, ms=6, mew=0.9, ls="none", zorder=8)
        ax.text(s_is * 1.14, isaac.ondie_gbps_per_link / 1.35,
                f"ISAAC, inter-tile link\n{isaac.ondie_gbps_per_link:.1f} GB/s",
                fontsize=6.2, color=F.CHIP_TXT, ha="left", va="top", zorder=8,
                linespacing=1.15)
    ax.set_xlabel(r"MVM row rate $s = 1/t_{\mathrm{row}}$ (Mrows/s)", fontsize=8)
    ax.set_ylabel("link bandwidth, per direction (GB/s)", fontsize=8)
    ax.set_title("(a) Intra-die placement", fontsize=9)
    return lo, hi


def _panel_inter(F, d, ax, chips=True, compact=False):
    lo, hi = F.draw_panel(
        ax, d["pkg"]["a_min"], d["pkg"]["a_max"], d["pkg"]["n_s"], d["pkg"]["f_s"],
        (1e-2, 1e3), "observed over P: 7 named rules",
        "P = the seven named die-seating rules"
        if compact else
        "latency object: whole-model serial prefill (2.7B)\n"
        "P = the seven named die-seating rules\n"
        f"ports at {F.KAPPA:g}x the link rate",
        ((0.22, 0.86), 3.2, (0.80, 0.13), (0.98, 0.66), (0.015, 0.015)), 14.0)
    if chips:
        from scripts import anchors as an
        c = an.chip("mythic_m1076")
        sx = 1.0 / c.t_mvm_s / 1e6
        b0, b1 = c.ondie_band
        ax.plot([sx, sx], [b0, b1], "-", color=F.CHIP, lw=1.0, zorder=7)
        ax.plot([sx, sx], [b0, b1], marker="D", mfc="white", mec=F.CHIP, ms=6,
                mew=1.1, ls="none", zorder=8)
        ax.text(sx, b0 * 0.70, "M1076", fontsize=6.2, color=F.CHIP_TXT,
                va="top", ha="center", zorder=8)
        isaac = an.chip("isaac")
        s_is = 1.0 / isaac.t_mvm_s / 1e6
        ax.plot([s_is], [isaac.d2d_gbps], marker="D", mfc=F.CHIP, mec=F.CHIP_TXT,
                ms=6, mew=0.9, ls="none", zorder=8)
        ax.text(s_is / 1.14, isaac.d2d_gbps * 1.30,
                f"ISAAC, off-chip link\n{isaac.d2d_gbps:g} GB/s", fontsize=6.2,
                color=F.CHIP_TXT, ha="right", va="bottom", zorder=8, linespacing=1.15)
        for bw in (0.4, 12.5):
            ax.plot([F.S_REF], [bw], marker="o", mfc="white", mec=F.CHIP, ms=6.5,
                    mew=1.4, ls="none", zorder=9)
            ax.text(F.S_REF / 1.22, bw if bw > 1 else bw / 1.45,
                    f"evaluated here\n{bw:g} GB/s", fontsize=6.2, color=F.CHIP_TXT,
                    ha="right", va="center", zorder=9, linespacing=1.15)
    ax.set_xlabel(r"MVM row rate $s = 1/t_{\mathrm{row}}$ (Mrows/s)", fontsize=8)
    ax.set_ylabel("link bandwidth, per direction (GB/s)", fontsize=8)
    ax.set_title("(b) Inter-die placement", fontsize=9)
    return lo, hi


def fig1():
    F, d = _isobar_inputs()
    src = ["scripts/fig_phase_isobar.py", "analysis/phase_diagram_isobar_k2.json"]
    for tag, fn in (("fig1a_intra_die_phase", _panel_intra),
                    ("fig1b_inter_die_phase", _panel_inter)):
        fig, ax = plt.subplots(figsize=(COL_WIDTH * 1.35, COL_WIDTH * 1.20))
        fn(F, d, ax, compact=True)
        save(fig, tag, sources=src)
    fig, axes = plt.subplots(1, 2, figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.46))
    _panel_intra(F, d, axes[0], compact=True)
    _panel_inter(F, d, axes[1], compact=True)
    axes[1].set_ylabel("")
    handles = [Line2D([], [], color=F.SLATE, lw=1.2),
               Line2D([], [], color=F.BRICK, lw=1.2),
               Line2D([], [], ls=(0, (1.2, 2.2)), color=F.CONTOUR, lw=0.9),
               Line2D([], [], marker="D", mfc=F.CHIP, mec=F.CHIP_TXT, ls="none", ms=6),
               Line2D([], [], marker="D", mfc="white", mec=F.CHIP, ls="none", ms=6),
               Line2D([], [], marker="o", mfc="white", mec=F.CHIP, ls="none", ms=6.5)]
    labels = [r"$B_+ = \max_{p} B_c(p)$", r"$B_- = \min_{p} B_c(p)$",
              "placement latency spread, 20%", "published link rate",
              "assumed range / second MVM mode", "configurations evaluated here"]
    fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False,
               fontsize=6.6, bbox_to_anchor=(0.5, -0.10))
    fig.tight_layout()
    save(fig, "fig1_phase_diagram", composite=True, sources=src)
    lo_d, hi_d = F.boundaries(d["die"]["a_min"], d["die"]["a_max"],
                              d["die"]["n_s"], d["die"]["f_s"])
    lo_p, hi_p = F.boundaries(d["pkg"]["a_min"], d["pkg"]["a_max"],
                              d["pkg"]["n_s"], d["pkg"]["f_s"])
    j = int(np.searchsorted(F.SS, F.S_REF))
    dump_json("fig1_boundaries", {
        "kappa": F.KAPPA, "reference_row_time_s": 10.14e-6,
        "intra_die": {"A_min_words": d["die"]["a_min"], "A_max_words": d["die"]["a_max"],
                      "envelope": d["die"]["a_max"] / d["die"]["a_min"],
                      "B_minus_gbps_at_ref": lo_d[j], "B_plus_gbps_at_ref": hi_d[j],
                      "per_op_compute_s": d["die"]["n_s"], "n_placements": 70},
        "inter_die": {"A_min_words": d["pkg"]["a_min"], "A_max_words": d["pkg"]["a_max"],
                      "envelope": d["pkg"]["a_max"] / d["pkg"]["a_min"],
                      "B_minus_gbps_at_ref": lo_p[j], "B_plus_gbps_at_ref": hi_p[j],
                      "A_by_rule_words": d["pkg"]["A"]}}, sources=src)


# =====================================================================
# Fig. 2  platform workflow and the modelling example
# =====================================================================
def _box(ax, xy, w, h, text, fc="#eef2f6", ec=NAVY, fs=7.0, lw=0.8):
    ax.add_patch(FancyBboxPatch(xy, w, h, boxstyle="round,pad=0.010,rounding_size=0.015",
                                fc=fc, ec=ec, lw=lw, zorder=3))
    ax.text(xy[0] + w / 2, xy[1] + h / 2, text, ha="center", va="center",
            fontsize=fs, zorder=4, linespacing=1.25)


def _arrow(ax, p0, p1, ec=NAVY, lw=1.0, ls="-", rad=0.0):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=8,
                                 color=ec, lw=lw, ls=ls, zorder=2,
                                 connectionstyle=f"arc3,rad={rad}",
                                 shrinkA=1, shrinkB=1))


def fig2():
    fig, ax = plt.subplots(figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.46))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    y1, h1 = 0.70, 0.17
    row = [(0.030, 0.150, "workload and\nhardware\nconfiguration"),
           (0.212, 0.150, "mapping and\npartition\n(tiling, splits)"),
           (0.394, 0.170, "logical traffic\nbroadcast, reduce,\nhand-off"),
           (0.596, 0.170, "placement and\nrouting: loads on\nlinks and ports"),
           (0.798, 0.165, "resource\nservice cost\nper boundary")]
    for x, w, txt in row:
        _box(ax, (x, y1), w, h1, txt, fs=6.4)
    for i in range(len(row) - 1):
        x0 = row[i][0] + row[i][1]
        _arrow(ax, (x0 + 0.004, y1 + h1 / 2), (row[i + 1][0] - 0.004, y1 + h1 / 2))
    y2, h2 = 0.42, 0.15
    _box(ax, (0.700, y2), 0.125, h2, "latency\nexecution\noverlap", fc="#f6efe2", ec=AMBER, fs=6.4)
    _box(ax, (0.845, y2), 0.125, h2, "dynamic energy\nrouted\ntraffic", fc="#f6efe2", ec=AMBER, fs=6.4)
    _arrow(ax, (0.855, y1), (0.770, y2 + h2 + 0.004), ec=AMBER, rad=0.12)
    _arrow(ax, (0.905, y1), (0.905, y2 + h2 + 0.004), ec=AMBER)
    ax.text(0.905, y2 - 0.018, "two aggregations of one description",
            fontsize=6.0, color=AMBER, ha="center", va="top")
    _box(ax, (0.394, y2), 0.170, h2, "phase sweep over\nbandwidth and\ndevice rate", fs=6.4)
    _arrow(ax, (0.700, y2 + h2 / 2), (0.568, y2 + h2 / 2), ec=SLATE, ls=(0, (3, 2)))
    y3, h3 = 0.10, 0.17
    _box(ax, (0.100, y3), 0.560, h3,
         "deployment search\n"
         "DP over the block cuts, simulated annealing over the die placement,\n"
         "enumeration inside a die; only the touched boundaries are re-scored",
         fc="#eaf3ed", ec=GREEN, fs=6.4)
    _arrow(ax, (0.250, y3 + h3), (0.250, y1 - 0.004), ec=GREEN)
    _arrow(ax, (0.560, y3 + h3), (0.640, y1 - 0.004), ec=GREEN, rad=-0.10)
    ax.text(0.258, y1 - 0.055, "revised\npartition", fontsize=6.0, color=GREEN,
            ha="left", va="top", linespacing=1.25)
    ax.text(0.648, y1 - 0.055, "revised\nplacement", fontsize=6.0, color=GREEN,
            ha="left", va="top", linespacing=1.25)
    _arrow(ax, (0.700, y2 + 0.02), (0.664, y3 + h3 - 0.01), ec=GREEN, rad=0.15)
    ax.text(0.712, y3 + h3 + 0.035, "cost of a candidate", fontsize=6.0, color=GREEN,
            ha="left", va="bottom")
    ax.text(0.100, y3 - 0.030, "the search optimises latency; energy is reported beside it",
            fontsize=6.0, color=INK, ha="left", va="top")
    # worked example, lower right: logical endpoints, routing, one shared link
    ex = fig.add_axes([0.760, 0.055, 0.215, 0.295])
    ex.set_xlim(-0.7, 3.7); ex.set_ylim(-0.9, 2.7); ex.axis("off")
    for gx in range(4):
        for gy in range(3):
            ex.add_patch(Rectangle((gx - 0.30, gy - 0.30), 0.60, 0.60, fc="#f4f6f8",
                                   ec="#dde3e8", lw=0.5, zorder=1))
    prod, cons = [(0, 2), (0, 0)], [(3, 2), (3, 0)]
    for (px, py) in prod:
        for (cx, cy) in cons:
            ex.plot([px, px, cx], [py, 1, 1], color=BRICK, lw=0.9, alpha=0.55, zorder=3)
    ex.plot([1.0, 2.0], [1, 1], color=BRICK, lw=3.0, solid_capstyle="butt", zorder=4)
    for (px, py) in prod:
        ex.plot([px], [py], marker="s", ms=5, mfc=SLATE, mec="white", mew=0.6,
                ls="none", zorder=6)
    for (cx, cy) in cons:
        ex.plot([cx], [cy], marker="o", ms=5, mfc="white", mec=BRICK, mew=1.2,
                ls="none", zorder=6)
    ex.text(1.5, 1.28, "one link carries\nall four flows", fontsize=5.8, ha="center",
            va="bottom", color=BRICK, linespacing=1.2)
    ex.text(1.5, -0.95, "two producer dies to two consumer dies:\n"
            "the logical traffic is fixed, the routed cost is not",
            fontsize=5.8, ha="center", va="top", linespacing=1.25, color=INK)
    save(fig, "fig2_platform_workflow", sources=["schematic"],
         note="schematic; carries no experimental numbers")


# =====================================================================
# Fig. 3  external references
# =====================================================================
def _fig3a(ax):
    """Published placement measurements against the model's two estimates."""
    t1 = load("simba_t1.json")
    rows = t1["rows"]
    dist = [max(abs(a[0] - b[0]) + abs(a[1] - b[1])
                for a in r["seating"] for b in r["seating"]) for r in rows]
    x = np.arange(len(rows))
    ax.bar(x, [r["measured_norm"] for r in rows], width=0.6, color="#cdd7e3",
           ec=SLATE, lw=0.8, label="measured silicon", zorder=3)
    ax.plot(x, [r["ratio_max_end"] for r in rows], marker="o", ms=4.5, lw=1.5,
            color=GREEN, label="busiest-resource bound", zorder=4)
    ax.plot(x, [r["ratio_pess"] for r in rows], marker="D", ms=4.5, lw=1.3, ls="--",
            color=BRICK, mfc="white", label="round-serialized estimate", zorder=4)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{d:g}" for d in dist], fontsize=7)
    ax.set_xlabel("seating: longest-pair distance (hops)", fontsize=7.5)
    ax.set_ylabel("latency, normalized to the\nadjacent seating", fontsize=7.5)
    ax.set_title("(a) Published placement measurements, 4-chiplet package", fontsize=8)
    ax.legend(fontsize=6.2, loc="upper left", frameon=False)
    tidy(ax, grid="y")
    return t1, dist


def _fig3b(ax):
    """The same candidate set under a cycle-level packet simulator."""
    fan = load("b_fanout_24x24_rerank.json")
    r = fan["rows"]
    ref = fan["summary"]["strongest_random_under_ours"]
    for n, e in r.items():
        fam = ("search" if n.startswith("sa_") else
               "random" if n.startswith("random") else
               "default" if n in ("sequential", "snake") else "rule")
        mk = {"search": "*", "random": "o", "default": "s", "rule": "^"}[fam]
        ax.plot([e["ours_words"] / r[ref]["ours_words"]],
                [e["booksim_cycles"] / r[ref]["booksim_cycles"]],
                marker=mk, ms=9 if mk == "*" else 5.5, color=FAM[fam],
                mec="white", mew=0.5, ls="none", zorder=5)
    lim = [0.55, 4.2]
    ax.plot(lim, lim, color="0.6", lw=0.8, ls=(0, (4, 3)), zorder=2)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(*lim); ax.set_ylim(*lim)
    for a in (ax.xaxis, ax.yaxis):
        a.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
        a.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_xticks([0.6, 1, 2, 4]); ax.set_yticks([0.6, 1, 2, 4])
    ax.set_xlabel("analytic bottleneck cost, relative to the\nstrongest random layout",
                  fontsize=7.5)
    ax.set_ylabel("packet-simulator batch time,\nsame reference", fontsize=7.5)
    ax.set_title("(b) Same candidates under a cycle-level router simulator", fontsize=8)
    ax.text(0.04, 0.96, f"Spearman $\\rho$ = {fan['summary']['spearman']:.3f}\n"
                        f"{len(r)} candidates, {r[ref]['packets']/1000:.0f}k packets\n"
                        r"$\kappa = 1$ fan-out instance, 17 dies per stage",
            transform=ax.transAxes, fontsize=6.3, va="top", ha="left", linespacing=1.3)
    ax.legend(handles=[Line2D([], [], marker=m, color=FAM[f], ls="none",
                              ms=8 if m == "*" else 5.5, mec="white", mew=0.5)
                       for f, m in (("default", "s"), ("rule", "^"),
                                    ("random", "o"), ("search", "*"))],
              labels=["stacked fills", "compact rules", "random fills", "search endpoints"],
              fontsize=6.2, loc="lower right", frameon=False)
    tidy(ax)
    return fan, ref


def fig3():
    SRC = ["analysis/simba_t1.json", "analysis/b_fanout_24x24_rerank.json"]
    fig, axes = plt.subplots(1, 2, figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.40))
    t1, dist = _fig3a(axes[0])
    fan, ref = _fig3b(axes[1])
    fig.tight_layout()
    save(fig, "fig3_external_validation", composite=True, sources=SRC)
    for tag, fn in (("fig3a_silicon_placement", _fig3a),
                    ("fig3b_packet_ranking", _fig3b)):
        f, a = plt.subplots(figsize=(COL_WIDTH * 1.25, COL_WIDTH * 1.05))
        fn(a)
        f.tight_layout()
        save(f, tag, sources=SRC)
    dump_csv("fig3_silicon_t1", [
        {"longest_pair_hops": d, "measured_norm": r["measured_norm"],
         "bound_norm": r["ratio_max_end"], "round_serialized_norm": r["ratio_pess"]}
        for d, r in zip(dist, t1["rows"])],
        ["longest_pair_hops", "measured_norm", "bound_norm", "round_serialized_norm"],
        sources=SRC[:1])
    dump_csv("fig3_packet_ranking", [
        {"layout": n, "analytic_words": e["ours_words"], "booksim_cycles": e["booksim_cycles"],
         "analytic_rel": e["ours_words"] / fan["rows"][ref]["ours_words"],
         "booksim_rel": e["booksim_cycles"] / fan["rows"][ref]["booksim_cycles"],
         "binding": e["busiest_is"], "packets": e["packets"]}
        for n, e in fan["rows"].items()],
        ["layout", "analytic_words", "booksim_cycles", "analytic_rel", "booksim_rel",
         "binding", "packets"], sources=SRC[1:])
    dump_json("fig3_efficiency", {
        "note": "platform timing on the main instance, single thread, as recorded",
        "incremental_score_median_ms": 1.34, "incremental_score_min_ms": 0.52,
        "full_score_ms": 37.0, "one_1200_step_run_s": 2.6,
        "workload_construction_ms": 10.0,
        "source": "analysis/FIXLIST.en.md (timing_probe), kappa_geometry_sweep wall times"},
        sources=["analysis/FIXLIST.en.md"])


# =====================================================================
# Fig. 4  deployment gain, the latency-energy trade-off, the intra-die layer
# =====================================================================
BAR_ORDER = ["default_A4", "snake", "clustered", "heaviest_first", "nmap_greedy",
             "least_manhattan", "random_s3", "sa_random_s1"]
BAR_LABEL = {"default_A4": "default fill\n(= sequential)", "snake": "snake",
             "clustered": "clustered", "heaviest_first": "heaviest_first",
             "nmap_greedy": "nmap_greedy", "least_manhattan": "least_manhattan",
             "random_s3": "best random fill", "sa_random_s1": "search (this work)"}


def _fig4a(ax):
    """Whole-model latency split into non-communication and hand-off cost."""
    mc = load("main_config_results.json")["rows"]
    mt = {n: r["prefill"]["0.4"] for n, r in mc.items()}
    ys = np.arange(len(BAR_ORDER))[::-1]
    T = {n: mt[n]["T_s"] * 1e3 for n in BAR_ORDER}
    for y, n in zip(ys, BAR_ORDER):
        r = mt[n]
        R = (r["layers_s"] + r["propagation_s"]) * 1e3
        H = r["H_s"] * 1e3
        ax.barh(y, R, color=C_R, ec="white", lw=0.5, height=0.62, zorder=3)
        ax.barh(y, H, left=R, color=C_H, ec="white", lw=0.5, height=0.62, zorder=3)
        ax.text(R + H + 55, y, f"{R + H:.0f}", va="center", ha="left",
                fontsize=6.6, color=FAM[LAYOUT_STYLE[n][1]], zorder=4)
    ax.set_yticks(ys)
    ax.set_yticklabels([BAR_LABEL[n] for n in BAR_ORDER], fontsize=7)
    for tick, n in zip(ax.get_yticklabels(), BAR_ORDER):
        tick.set_color(FAM[LAYOUT_STYLE[n][1]])
    ax.set_xlabel("whole-model prefill latency (ms) at 0.4 GB/s; "
                  "the number beside each bar is that total", fontsize=7.5)
    ax.set_xlim(0, 5000)
    y_sea, y_base = ys[-1], ys[BAR_ORDER.index("random_s3")]
    for n, y0, y1 in (("random_s3", y_base, y_sea), ("sa_random_s1", y_base, y_sea)):
        ax.plot([T[n], T[n]], [y1 - 0.45, y0 + 0.45], color=GREEN, lw=0.7,
                ls=(0, (2, 2)), zorder=5)
    ymid = (y_base + y_sea) / 2
    ax.annotate("", xy=(T["sa_random_s1"], ymid), xytext=(T["random_s3"], ymid),
                arrowprops=dict(arrowstyle="<|-|>", color=GREEN, lw=0.9, mutation_scale=7))
    ax.text(T["random_s3"] + 480, ymid,
            f"{100 * (1 - T['sa_random_s1'] / T['random_s3']):.2f}% below the\n"
            "strongest baseline", fontsize=6.6, color=GREEN, ha="left", va="center",
            linespacing=1.25)
    yb = y_sea - 0.75
    ax.annotate("", xy=(T["sa_random_s1"], yb), xytext=(T["default_A4"], yb),
                arrowprops=dict(arrowstyle="<|-|>", color=NAVY, lw=0.9, mutation_scale=7))
    ax.text((T["sa_random_s1"] + T["default_A4"]) / 2, yb - 0.22,
            f"{100 * (1 - T['sa_random_s1'] / T['default_A4']):.1f}% below the default fill",
            fontsize=6.6, color=NAVY, ha="center", va="top")
    ax.set_ylim(yb - 0.95, max(ys) + 0.6)
    ax.legend(handles=[Rectangle((0, 0), 1, 1, fc=C_R, ec="none"),
                       Rectangle((0, 0), 1, 1, fc=C_H, ec="none")],
              labels=["compute, weight write, digital unit",
                      "hand-off over links and ports"],
              fontsize=6.4, loc="center right", bbox_to_anchor=(1.0, 0.46), frameon=False)
    ax.set_title("(a) Where the deployment choice shows up", fontsize=8)
    tidy(ax, grid="x")
    return mt, T


def _fig4b(ax, annotate=True):
    """Latency against dynamic energy for every frozen layout."""
    en = load("energy_export.json")["rows"]
    ref = "random_s3"
    Tr, Er = en[ref]["T_s"], en[ref]["E_total_J"]
    seen = set()
    for n, e in en.items():
        if n == "sequential":                       # identical to default_A4
            continue
        lab, fam, mk = LAYOUT_STYLE.get(n, (n, "search", "*"))
        ax.plot([e["T_s"] * 1e3], [e["E_total_J"]], marker=mk,
                ms=10 if mk == "*" else 5.5, color=FAM[fam], mec="white", mew=0.5,
                ls="none", zorder=5,
                label=None if fam in seen else
                {"default": "default fill", "rule": "compact rules",
                 "random": "random fills", "search": "search endpoints"}[fam])
        seen.add(fam)
    notes = (("default_A4", "default fill", (-12, -1), "right", "center"),
             ("clustered", "clustered", (0, -11), "center", "top"),
             ("least_manhattan", "least_manhattan,\nnmap_greedy", (0, 10), "center", "bottom"),
             ("heaviest_first", "heaviest_first", (10, 0), "left", "center"),
             ("random_s3", "random fills", (16, -7), "left", "top"),
             ("sa_random_s1", "search endpoints", (0, -12), "center", "top"))
    for n, lab, off, ha, va in notes:
        e = en[n]
        ax.annotate(lab, (e["T_s"] * 1e3, e["E_total_J"]), textcoords="offset points",
                    xytext=off, fontsize=6.3, ha=ha, va=va,
                    color=FAM[LAYOUT_STYLE.get(n, (n, "search", "*"))[1]])
    if annotate:
        ax.annotate("", xy=(en["sa_random_s1"]["T_s"] * 1e3, en["sa_random_s1"]["E_total_J"]),
                    xytext=(Tr * 1e3, Er),
                    arrowprops=dict(arrowstyle="-|>", color=GREEN, lw=1.0,
                                    mutation_scale=8, ls=(0, (3, 2))))
        ax.text(1830, 2.562,
                f"search vs the strongest baseline:\n"
                f"latency {100 * (en['sa_random_s1']['T_s'] / Tr - 1):+.2f}%, "
                f"energy {100 * (en['sa_random_s1']['E_total_J'] / Er - 1):+.2f}%",
                fontsize=6.3, color=GREEN, ha="left", va="top", linespacing=1.3)
        ax.text(2700, 2.334, "the compact rules buy energy with latency:\n"
                f"{100 * (en['clustered']['E_total_J'] / Er - 1):+.1f}% energy for "
                f"{100 * (en['clustered']['T_s'] / Tr - 1):+.1f}% latency",
                fontsize=6.3, color=AMBER, ha="left", va="center", linespacing=1.3)
    ax.set_xlim(1750, 4550)
    ax.set_ylim(2.315, 2.565)
    ax.set_xlabel("whole-model prefill latency (ms), 0.4 GB/s", fontsize=7.5)
    ax.set_ylabel("system dynamic energy (J)", fontsize=7.5)
    ax.set_title("(b) Two costs of the same choice", fontsize=8)
    ax.legend(fontsize=6.3, loc="upper right", ncol=1, frameon=False,
              bbox_to_anchor=(1.0, 0.99))
    tidy(ax)
    return en, ref


def _fig4c(ax):
    """The intra-die layer objective: shipped assignment against the optimum."""
    it = load("intra_die_integration.json")
    a = it["per_anchor"]["0.4"]
    ship = a["T_layer_shipped_incl_pkg_s"] * 1e3
    best = a["T_layer_best_incl_pkg_s"] * 1e3
    parts = []
    for tag, key in (("shipped", "shipped"), ("optimized", "best")):
        attn = a["dies"]["attn"][f"{key}_s"] * 1e3
        ffn = a["dies"]["ffn"][f"{key}_s"] * 1e3
        rest = (a["fixed_rest_s"] + a["package_handoffs_per_layer_s_at_0.4"]) * 1e3
        parts.append((tag, attn, ffn, rest))
    xs = [0, 1]
    b1 = [p[1] for p in parts]
    b2 = [p[2] for p in parts]
    b3 = [p[3] for p in parts]
    ax.bar(xs, b1, width=0.5, color="#9db8c9", ec="white", lw=0.6, label="attention die", zorder=3)
    ax.bar(xs, b2, bottom=b1, width=0.5, color="#c9a86a", ec="white", lw=0.6,
           label="ffn die", zorder=3)
    ax.bar(xs, b3, bottom=np.add(b1, b2), width=0.5, color="#dfe4e8", ec="white",
           lw=0.6, label="rest of the layer", zorder=3)
    for x, tot in zip(xs, (ship, best)):
        ax.text(x, tot + 0.7, f"{tot:.2f} ms", ha="center", va="bottom", fontsize=6.8,
                color=INK)
    ax.annotate("", xy=(1, best + 4.2), xytext=(0, best + 4.2),
                arrowprops=dict(arrowstyle="<|-|>", color=GREEN, lw=0.9, mutation_scale=7))
    ax.text(0.5, best + 5.0, f"{100 * (1 - best / ship):.2f}% of the layer",
            ha="center", va="bottom", fontsize=6.6, color=GREEN)
    ax.set_xticks(xs)
    ax.set_xticklabels(["shipped\nassignment", "exhaustive\noptimum"], fontsize=7)
    ax.set_ylabel("layer latency (ms)", fontsize=7.5)
    ax.set_ylim(0, ship * 1.30)
    ax.set_title("(c) Inside a die, same platform, 0.4 GB/s", fontsize=8)
    ax.legend(fontsize=6.2, loc="lower right", frameon=False)
    tidy(ax, grid="y")
    return it, ship, best


def fig4():
    SRC = ["analysis/mechanism_table.json", "analysis/energy_export.json",
           "analysis/intra_die_integration.json", "analysis/main_config_results.json"]
    fig = plt.figure(figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.72))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 0.92], hspace=0.45, wspace=0.28)
    ax_a = fig.add_subplot(gs[0, :])
    mt, T = _fig4a(ax_a)
    en, ref = _fig4b(fig.add_subplot(gs[1, 0]))
    it, ship, best = _fig4c(fig.add_subplot(gs[1, 1]))
    save(fig, "fig4_deployment_gain", composite=True, sources=SRC)
    for tag, fn, size in (("fig4a_latency_breakdown", _fig4a, (PAGE_WIDTH * 0.62, 2.5)),
                          ("fig4b_latency_energy", _fig4b, (COL_WIDTH * 1.25, COL_WIDTH * 1.05)),
                          ("fig4c_intra_die_layer", _fig4c, (COL_WIDTH * 0.95, COL_WIDTH * 1.05))):
        f, a = plt.subplots(figsize=size)
        fn(a)
        f.tight_layout()
        save(f, tag, sources=SRC)
    stats = load("main_config_results.json")
    dump_csv("fig4_layouts", [
        {"layout": n,
         "kind": LAYOUT_STYLE.get(n, (n, "search", "*"))[1],
         "T_prefill_0p4_ms": mt[n]["T_s"] * 1e3,
         "R_ms": (mt[n]["layers_s"] + mt[n]["propagation_s"]) * 1e3,
         "H_ms": mt[n]["H_s"] * 1e3,
         "E_dynamic_J": en[n]["E_total_J"], "E_comm_J": en[n]["E_comm_J"],
         "word_hops_G": en[n]["word_hops_route"] / 1e9,
         "dT_vs_random_s3_pct": 100 * (en[n]["T_s"] / en[ref]["T_s"] - 1),
         "dE_vs_random_s3_pct": 100 * (en[n]["E_total_J"] / en[ref]["E_total_J"] - 1)}
        for n in en if n != "sequential"],
        ["layout", "kind", "T_prefill_0p4_ms", "R_ms", "H_ms", "E_dynamic_J",
         "E_comm_J", "word_hops_G", "dT_vs_random_s3_pct", "dE_vs_random_s3_pct"],
        sources=SRC)
    dump_json("fig4_readings", {
        "reference_for_deltas": "random_s3 (strongest evaluated latency baseline)",
        "delta_convention": "change = (value/reference - 1) x 100%, negative = lower",
        "headline_layout": "sa_random_s1 (median seed of best-over-starts)",
        "gain_vs_strongest_pct": 100 * (1 - T["sa_random_s1"] / T["random_s3"]),
        "gain_vs_default_pct": 100 * (1 - T["sa_random_s1"] / T["default_A4"]),
        "energy_change_vs_strongest_pct": 100 * (en["sa_random_s1"]["E_total_J"] / en[ref]["E_total_J"] - 1),
        "intra_die_layer_ms": {"shipped": ship, "optimized": best,
                               "gain_pct": 100 * (1 - best / ship),
                               "energy": "not modelled at this level"},
        "search_statistic": stats["stats"], }, sources=SRC)


# =====================================================================
# Fig. 5  the real layouts and their link loads, and what the objective buys
# =====================================================================
STAGE = "ffn2@L2"          # one illustrative hand-off, the SAME for every layout
NET_LAYOUTS = [("clustered", "compact rule"),
               ("random_s3", "strongest random baseline"),
               ("sa_random_s1", "search (this work)")]
EXTRA_LAYOUTS = [("least_manhattan", "distance rule")]
SEG_RE = None


def _stage_data(kappa=2.0, bw=0.4, grid=(24, 24)):
    """Directed link loads, port loads and endpoints of ONE hand-off stage,
    for each layout, read from the evaluator itself."""
    import re
    from scripts import kappa_geometry_sweep as kg
    from scripts import llm_workload as lw
    from scripts import search_baselines as sb
    from scripts import search_space as ss
    global SEG_RE
    SEG_RE = re.compile(r"seg\((\d+), (\d+)\)-\((\d+), (\d+)\)")
    W = kg.workload(grid)
    W.port_ratio = kappa
    icl = W.die_ic
    cell = load("kappa_geometry_sweep.json")["cells"]["24x24/k2"]
    pis = {}
    for n, _ in NET_LAYOUTS + EXTRA_LAYOUTS:
        if n.startswith("sa_"):
            pis[n] = ss.Pi.from_json(cell["runs"][n]["best_pi"])
        elif n.startswith("random_s"):
            pis[n] = sb.generate("random", W, seed=int(n.split("_s")[1]))
        else:
            pis[n] = sb.generate(n, W, seed=0)
    base = lw.block_chain(W.cfg, W.S, "prefill", on_chip=True,
                          max_dies=W.fab.level("die").per_parent)
    out = {"stage": STAGE, "kappa": kappa, "bw_gbps": bw, "grid": f"{grid[0]}x{grid[1]}",
           "words_per_second": bw * 1e9, "layouts": {}}
    for n, pi in pis.items():
        chain, seating = [], {}
        for li in range(W.cfg.n_layers):
            for e in base:
                nm = f"{e['name']}@L{li}"
                chain.append({**e, "name": nm})
                seating[nm] = list(pi.seat[nm])
        fl = lw.block_die_flows(chain, seating, W.fab)[STAGE]
        loads = se.resource_loads(fl, icl, ports=True, kappa=kappa)
        links, ports = [], []
        for k, v in loads.items():
            if k[0] == "port":
                ports.append({"node": k[1], "x": icl.coord(k[1])[0], "y": icl.coord(k[1])[1],
                              "side": k[2], "words_over_kappa": v,
                              "service_ms": v / (bw * 1e9) * 1e3})
            else:
                m = SEG_RE.search(k[0])
                x0, y0, x1, y1 = (int(g) for g in m.groups())
                ports_dir = k[1]
                links.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "dir": ports_dir,
                              "words": v, "service_ms": v / (bw * 1e9) * 1e3})
        prod = sorted({f["nodes"][0] for f in fl})
        cons = sorted({f["nodes"][1] for f in fl})
        occupied = sorted({s for seats in pi.seat.values() for s in seats})
        wl = [l["words"] for l in links]
        pl = [p["words_over_kappa"] for p in ports]
        words = sum(f["volume"] * f["width"] for f in fl)
        wh = sum(f["volume"] * f["width"] * icl.hops(*f["nodes"]) for f in fl)
        out["layouts"][n] = {
            "links": links, "ports": ports,
            "producers": [{"node": p, "x": icl.coord(p)[0], "y": icl.coord(p)[1]} for p in prod],
            "consumers": [{"node": c, "x": icl.coord(c)[0], "y": icl.coord(c)[1]} for c in cons],
            "occupied": occupied,
            "n_flows": len(fl), "words_delivered": words, "word_hops": wh,
            "mean_hops": wh / words, "max_link_words": max(wl), "max_port_words_over_kappa": max(pl),
            "max_link_service_ms": max(wl) / (bw * 1e9) * 1e3,
            "max_port_service_ms": max(pl) / (bw * 1e9) * 1e3,
            "binding": "link" if max(wl) > max(pl) * (1 + 1e-9) else
                       ("port" if max(pl) > max(wl) * (1 + 1e-9) else "tie"),
            "n_loaded_links": len(links)}
    return out, grid


def _seg_loads(d, directed=False):
    """Segment -> load. Without `directed`, the two directions of one adjacency
    are reduced to their maximum, which is what the per-boundary cost takes;
    the full directed table is always in the CSV beside the figure."""
    m = {}
    for l in d["links"]:
        k = (l["x0"], l["y0"], l["x1"], l["y1"])
        if directed:
            m[(k, l["dir"])] = l["service_ms"]
        else:
            m[k] = max(m.get(k, 0.0), l["service_ms"])
    return m


NODE, BARGAP = 0.42, 0.06          # die box side and the gap it leaves for a link
UNLOADED = "#e9ebec"


def _draw_network(ax, d, grid, vmax, lw=2.9, node_lw=0.3, vmin=None, directed=False):
    """The die grid drawn the way a package heatmap is read: every die a box,
    every mesh link a bar between two boxes, coloured by the service time that
    link owes for this one hand-off. Unloaded links keep their light tone, so
    the fabric stays visible and the loaded path stands out."""
    nx, ny = grid
    loads = _seg_loads(d)
    dloads = _seg_loads(d, directed=True) if directed else None
    top = max(loads.values())
    off = 0.11 if directed else 0.0
    # the colour scale starts at one flow, so a single-flow link is already
    # visible; links this hand-off does not touch are drawn in flat grey
    norm = Normalize(vmin if vmin is not None else min(loads.values()) * 0.9, vmax)
    half = NODE / 2 + BARGAP
    thin = lw * 0.48
    for x in range(nx):
        for y in range(ny):
            for k, (xs, ys, perp) in (
                    ((x, y, x + 1, y), ([x + half, x + 1 - half], [y, y], "y")),
                    ((x, y, x, y + 1), ([x, x], [y + half, y + 1 - half], "x"))):
                if (perp == "y" and x + 1 >= nx) or (perp == "x" and y + 1 >= ny):
                    continue
                pairs = ([(dloads.get((k, s), 0.0), s) for s in ("+", "-")]
                         if directed else [(loads.get(k, 0.0), None)])
                for v, s in pairs:
                    dx = (0, off if s == "+" else -off) if perp == "y" else \
                         (-off if s == "+" else off, 0)
                    px = [c + dx[0] for c in xs]
                    py = [c + dx[1] for c in ys]
                    c_, w_ = ((LOAD_CMAP(norm(v)), lw if not directed else lw * 0.55)
                              if v > 0 else (UNLOADED, thin))
                    if v >= top - 1e-9:
                        ax.plot(px, py, color="#08131c",
                                lw=(lw + 1.2) if not directed else lw * 0.95,
                                solid_capstyle="butt", zorder=1.9)
                    ax.plot(px, py, color=c_, lw=w_, solid_capstyle="butt",
                            zorder=2 + (norm(v) if v > 0 else 0))
    occ = set(d.get("occupied", []))
    prod = {(p["x"], p["y"]) for p in d["producers"]}
    cons = {(c["x"], c["y"]) for c in d["consumers"]}
    for x in range(nx):
        for y in range(ny):
            n = y * nx + x
            if (x, y) in prod:
                fc, ec, z = SLATE, "#1d2f3d", 6
            elif (x, y) in cons:
                fc, ec, z = BRICK, "#4a2412", 6
            elif n in occ or not occ:
                fc, ec, z = "white", "#b9c4cc", 5
            else:
                fc, ec, z = "#f4f6f8", "#dfe5ea", 5
            ax.add_patch(Rectangle((x - NODE / 2, y - NODE / 2), NODE, NODE, fc=fc,
                                   ec=ec, lw=node_lw if z == 5 else 0.4, zorder=z))
    ax.set_xlim(-0.75, nx - 0.25)
    ax.set_ylim(-0.75, ny - 0.25)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ("top", "right", "bottom", "left"):
        ax.spines[s].set_color("#c9d2d9")
        ax.spines[s].set_linewidth(0.6)
    d["n_links_at_max"] = sum(1 for v in loads.values() if v >= top - 1e-9)


def _net_key(ax):
    """Marker key in its own small axes, so it never covers a panel."""
    ax.axis("off")
    h = [Rectangle((0, 0), 1, 1, fc=SLATE, ec="#1d2f3d", lw=0.4),
         Rectangle((0, 0), 1, 1, fc=BRICK, ec="#4a2412", lw=0.4),
         Rectangle((0, 0), 1, 1, fc="white", ec="#aab6be", lw=0.5),
         Line2D([], [], color="#08131c", lw=2.8),
         Line2D([], [], color=UNLOADED, lw=1.6)]
    ax.legend(h, ["producer die", "consumer die", "other die", "busiest link",
                  "link this hand-off does not use"],
              fontsize=5.7, loc="upper left", bbox_to_anchor=(0.0, 1.0),
              frameon=False, ncol=2, handlelength=1.2, handleheight=0.9,
              columnspacing=0.8, labelspacing=0.35, borderpad=0.0)


def _readings_text(d):
    n = d.get("n_links_at_max", 1)
    return (f"busiest link {d['max_link_service_ms']:.1f} ms"
            f"{'' if n == 1 else f', {n} tie'}\n"
            f"busiest port {d['max_port_service_ms']:.1f} ms, {d['binding']}-bound\n"
            f"{d['word_hops'] / 1e6:.0f} M word-hops, {d['mean_hops']:.1f} hops")


def _logical_sketch(ax, n_prod, n_cons, words_M):
    """The logical hand-off above the panels: the traffic every panel shares."""
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    x0, x1 = 0.055, 0.215
    for i in range(n_prod):
        ax.add_patch(Rectangle((x0 - 0.010, 0.18 + 0.60 * i / max(n_prod - 1, 1) - 0.06),
                               0.020, 0.12, fc=SLATE, ec="#1d2f3d", lw=0.4))
    for i in range(n_cons):
        ax.add_patch(Rectangle((x1 - 0.010, 0.18 + 0.60 * i / max(n_cons - 1, 1) - 0.06),
                               0.020, 0.12, fc=BRICK, ec="#4a2412", lw=0.4))
    ax.add_patch(FancyArrowPatch((x0 + 0.022, 0.48), (x1 - 0.022, 0.48),
                                 arrowstyle="-|>", mutation_scale=8, color="#7f8c94",
                                 lw=1.0))
    ax.text(x1 + 0.030, 0.48,
            f"one hand-off of the chain: {n_prod} producer dies ship to "
            f"{n_cons} consumer dies,\n{n_prod * n_cons} flows and {words_M:.1f} M words "
            "in every panel below; only the placement differs",
            fontsize=6.2, ha="left", va="center", linespacing=1.35, color=INK)


def _fig5_networks(data, grid, names, fname, composite=True, width=PAGE_WIDTH,
                   directed=False):
    vmax = max(max(l["service_ms"] for l in data["layouts"][n]["links"]) for n, _ in names)
    fig = plt.figure(figsize=(width, width * 0.56))
    gs = fig.add_gridspec(2, len(names), height_ratios=[0.20, 1.0],
                          wspace=0.06, hspace=0.06, left=0.015, right=0.985,
                          top=0.97, bottom=0.115)
    vmin = min(min(l["service_ms"] for l in data["layouts"][n]["links"])
               for n, _ in names) * 0.9
    cax = fig.add_axes([0.045, 0.905, 0.185, 0.020])
    sm = matplotlib.cm.ScalarMappable(norm=Normalize(vmin, vmax), cmap=LOAD_CMAP)
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal")
    cax.set_title("required link service time (ms)\nat 0.4 GB/s per direction",
                  fontsize=6.0, pad=3, linespacing=1.25)
    cb.ax.tick_params(labelsize=5.8, length=2, pad=1)
    cb.outline.set_linewidth(0.4)
    _net_key(fig.add_axes([0.035, 0.795, 0.200, 0.075]))
    d0 = data["layouts"][names[0][0]]
    sk = fig.add_axes([0.255, 0.845, 0.72, 0.115])
    _logical_sketch(sk, len(d0["producers"]), len(d0["consumers"]),
                    d0["words_delivered"] / 1e6)
    for i, (n, _sub) in enumerate(names):
        ax = fig.add_subplot(gs[1, i])
        d = data["layouts"][n]
        _draw_network(ax, d, grid, vmax, vmin=vmin, directed=directed)
        fam = LAYOUT_STYLE.get(n, (n, "search", "*"))[1]
        ax.set_title(f"({'abc'[i]}) {BAR_LABEL.get(n, n).replace(chr(10), ' ')}",
                     fontsize=8, color=FAM[fam], pad=3)
        ax.text(0.5, -0.012, _readings_text(d), transform=ax.transAxes, fontsize=5.8,
                ha="center", va="top", linespacing=1.35, color=INK)
    save(fig, fname, composite=composite,
         sources=["scripts/search_eval.py (live)", "analysis/kappa_geometry_sweep.json"],
         note=f"stage {STAGE}; illustrative hand-off, not an average stage; "
              + ("both directions of every adjacency drawn as two offset bars"
                 if directed else
                 "each bar is the busier of the adjacency's two directions"))
    return vmax


def _fig5_ablation(ax):
    """Same space, same solver, same budget, same starts: only the objective
    changes. Every output layout is re-scored under the system latency and
    compared with the best layout the resource-aware objective found, which is
    the denominator the project record uses."""
    ab = load("objective_ablation_k2.json")["cells"]["k2"]
    names = ["ours", "word_hops", "max_hops"]
    labels = ["resource-aware\n(links + ports)", "word-hops\n(distance proxy)",
              "max hops\n(propagation only)"]
    cols = [GREEN, AMBER, GREY]
    base = ab["per_objective"]["ours"]["T_best_s"]
    for i, n in enumerate(names):
        vals = sorted(ab["rows"][e]["T_single_s"] / base
                      for e in ab["per_objective"][n]["endpoints"])
        w = 0.20
        xs = [i + (k - 1) * (w + 0.03) for k in range(len(vals))]
        ax.bar(xs, vals, width=w, color=cols[i], ec="white", lw=0.5, zorder=3)
        ax.text(i, max(vals) + 0.006,
                "reference" if n == "ours" else
                f"best: {100 * (vals[0] - 1):+.1f}%",
                ha="center", va="bottom", fontsize=6.6, color=cols[i])
    ax.axhline(1.0, color=GREEN, lw=0.9, ls=(0, (3, 2)), zorder=4)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(labels, fontsize=7)
    ax.set_ylim(0.97, 1.17)
    ax.set_ylabel("selected layout's latency, divided by\n"
                  "the best resource-aware result", fontsize=7.0)
    ax.set_title("(d) What the physical objective is worth", fontsize=8)
    ax.text(0.02, 0.96, "three bars = three seeds, same budget\n"
            "vertical axis starts at 0.97",
            transform=ax.transAxes, fontsize=6.2, va="top", color=INK, linespacing=1.3)
    tidy(ax, grid="y")
    return ab, base


def fig5():
    data, grid = _stage_data()
    data["n_flows_note"] = (f"{data['layouts']['clustered']['n_flows']} flows, "
                            f"{data['layouts']['clustered']['words_delivered'] / 1e6:.1f} M words, "
                            "seat-invariant")
    _fig5_networks(data, grid, NET_LAYOUTS, "fig5_network_triptych")
    _fig5_networks(data, grid, [NET_LAYOUTS[0], EXTRA_LAYOUTS[0], NET_LAYOUTS[2]],
                   "fig5_network_triptych_least_manhattan")
    _fig5_networks(data, grid, NET_LAYOUTS, "fig5_network_triptych_directed",
                   directed=True)
    vmax = max(max(l["service_ms"] for l in data["layouts"][n]["links"])
               for n, _ in NET_LAYOUTS)
    vmin = min(min(l["service_ms"] for l in data["layouts"][n]["links"])
               for n, _ in NET_LAYOUTS) * 0.9
    for n, _sub in NET_LAYOUTS + EXTRA_LAYOUTS:
        f, a = plt.subplots(figsize=(COL_WIDTH * 0.95, COL_WIDTH * 1.02))
        _draw_network(a, data["layouts"][n], grid, vmax, vmin=vmin)
        a.set_title(BAR_LABEL.get(n, n).replace("\n", " "), fontsize=8,
                    color=FAM[LAYOUT_STYLE.get(n, (n, "search", "*"))[1]])
        a.text(0.5, -0.03, _readings_text(data["layouts"][n]), transform=a.transAxes,
               fontsize=6.0, ha="center", va="top", linespacing=1.35)
        f.tight_layout()
        save(f, f"fig5_network_{n}", sources=["scripts/search_eval.py (live)"])
    for n, _sub in NET_LAYOUTS:                 # optional zooms, full grid kept above
        d = data["layouts"][n]
        xs = [v for l in d["links"] for v in (l["x0"], l["x1"])]
        ys = [v for l in d["links"] for v in (l["y0"], l["y1"])]
        f, a = plt.subplots(figsize=(COL_WIDTH * 0.95, COL_WIDTH * 1.02))
        _draw_network(a, d, grid, vmax, lw=5.0, node_lw=0.5, vmin=vmin)
        m = 1.5
        a.set_xlim(min(xs) - m, max(xs) + m)
        a.set_ylim(min(ys) - m, max(ys) + m)
        a.set_title(f"{BAR_LABEL.get(n, n)} (detail)".replace("\n", " "), fontsize=8,
                    color=FAM[LAYOUT_STYLE.get(n, (n, "search", "*"))[1]])
        a.text(0.5, -0.03, f"zoom on the loaded region; the full {data['grid']} grid is "
               "in the triptych", transform=a.transAxes, fontsize=5.8, ha="center",
               va="top", color=INK)
        f.tight_layout()
        save(f, f"fig5_network_{n}_zoom", sources=["scripts/search_eval.py (live)"],
             note="detail view; distances are not comparable across panels without the full grid")
    f, a = plt.subplots(figsize=(COL_WIDTH * 1.05, COL_WIDTH * 0.95))
    ab, base = _fig5_ablation(a)
    f.tight_layout()
    save(f, "fig5d_objective_ablation", sources=["analysis/objective_ablation_k2.json"])
    # composite: three networks over the ablation
    fig = plt.figure(figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.78))
    gs = fig.add_gridspec(2, 4, height_ratios=[1.0, 0.72],
                          width_ratios=[1, 1, 1, 0.06], wspace=0.10, hspace=0.42,
                          left=0.03, right=0.94, top=0.93, bottom=0.08)
    for i, (n, _sub) in enumerate(NET_LAYOUTS):
        ax = fig.add_subplot(gs[0, i])
        _draw_network(ax, data["layouts"][n], grid, vmax, vmin=vmin)
        ax.set_title(f"({'abc'[i]}) {BAR_LABEL.get(n, n).replace(chr(10), ' ')}",
                     fontsize=8, color=FAM[LAYOUT_STYLE.get(n, (n, 'search', '*'))[1]], pad=3)
        ax.text(0.5, -0.04, _readings_text(data["layouts"][n]), transform=ax.transAxes,
                fontsize=5.9, ha="center", va="top", linespacing=1.35)
    cax = fig.add_subplot(gs[0, 3])
    sm = matplotlib.cm.ScalarMappable(norm=Normalize(vmin, vmax), cmap=LOAD_CMAP)
    cb = fig.colorbar(sm, cax=cax)
    cb.set_label("required link service time (ms) at 0.4 GB/s", fontsize=6.4)
    cb.ax.tick_params(labelsize=6)
    cb.outline.set_linewidth(0.5)
    _fig5_ablation(fig.add_subplot(gs[1, :2]))
    axl = fig.add_subplot(gs[1, 2:])
    axl.axis("off")
    axl.text(0.0, 0.95, "Reading the panels", fontsize=7.4, va="top", fontweight="bold")
    axl.text(0.0, 0.80,
             "Every box is a die of the package and every bar a mesh link, on\n"
             "one shared colour scale: the service time that link owes for this\n"
             "one hand-off at 0.4 GB/s. A bar takes the busier of the link's two\n"
             "directions; the full directed table is in the data files, and a\n"
             "two-bar variant is exported beside this figure. The same 25 flows\n"
             "and 26.2 M words are placed in all three panels, so only the\n"
             "placement differs. A compact placement funnels the flows through a\n"
             "few links, a dispersed one spreads them, and the search keeps the\n"
             "dispersion while removing the remaining stacking. Filled boxes are\n"
             "the hand-off's producer dies (slate) and consumer dies (brick); a\n"
             "dark outline marks the link directions at the maximum.",
             fontsize=6.3, va="top", linespacing=1.45)
    save(fig, "fig5_network_and_ablation", composite=True,
         sources=["scripts/search_eval.py (live)", "analysis/objective_ablation_k2.json"])
    # data exports
    slim = {"stage": data["stage"], "kappa": data["kappa"], "bw_gbps": data["bw_gbps"],
            "grid": data["grid"],
            "stage_choice": "ffn2 hand-off of layer 2: a 5-die to 5-die R-split "
                            "multicast, the same stage for every layout; illustrative, "
                            "not an average stage",
            "layouts": {n: {k: v for k, v in d.items() if k not in ("links", "ports")}
                        for n, d in data["layouts"].items()}}
    dump_json("fig5_stage_readings", slim, sources=["scripts/search_eval.py (live)"])
    for n, d in data["layouts"].items():
        dump_csv(f"fig5_links_{n}", d["links"],
                 ["x0", "y0", "x1", "y1", "dir", "words", "service_ms"])
        dump_csv(f"fig5_ports_{n}", d["ports"],
                 ["node", "x", "y", "side", "words_over_kappa", "service_ms"])
        dump_csv(f"fig5_endpoints_{n}",
                 [{**p, "role": "producer"} for p in d["producers"]] +
                 [{**c, "role": "consumer"} for c in d["consumers"]],
                 ["node", "x", "y", "role"])
    dump_json("fig5_ablation", {
        "protocol": "same feasible space, solver, budget, starts and seeds; only the "
                    "objective changes; every output re-scored under the system latency",
        "reference": "median of the resource-aware objective's three endpoints",
        "cells": {n: {"endpoints_T_s": [ab["rows"][e]["T_single_s"]
                                        for e in ab["per_objective"][n]["endpoints"]],
                      "loss_avoided_by_ours_pct": ab["per_objective"][n]["loss_avoided_by_ours_pct"],
                      "gain_vs_strongest_pct": ab["per_objective"][n]["gain_vs_strongest_pct"]}
                  for n in ("ours", "wire_only", "word_hops", "max_hops")},
        "strongest_baseline": ab["strongest_baseline_single"]},
        sources=["analysis/objective_ablation_k2.json"])


# =====================================================================
# Fig. 6  the conditions: bandwidth, port ratio, geometry, phase
# =====================================================================
def _fig6a(ax, with_r=False):
    """The frozen pair re-scored across bandwidth; no new search."""
    sl = load("bw_slice_k2.json")
    pts = sorted(sl["points"].values(), key=lambda p: p["B_gbps"])
    B = [p["B_gbps"] for p in pts]
    G = [100 * p["G"] for p in pts]
    eta = [100 * p["eta"] for p in pts]
    r = [100 * p["r"] for p in pts]
    ax.axvspan(sl["B_minus_gbps"], sl["B_plus_gbps"], color=CREAM, alpha=0.55, zorder=1,
               lw=0)
    ax.text(np.sqrt(sl["B_minus_gbps"] * sl["B_plus_gbps"]), 1.2,
            "placement-dependent\nband", fontsize=6.0, ha="center", va="bottom",
            color="#6b5a2a", linespacing=1.2, zorder=4)
    ax.plot(B, G, marker="o", ms=4.5, lw=1.6, color=GREEN, zorder=5,
            label="whole-model gain $G$")
    ax.plot(B, eta, ls=(0, (1.5, 1.8)), lw=1.3, color=SLATE, zorder=4,
            label=r"communication improvement $\eta$")
    if with_r:
        ax.plot(B, r, ls="--", lw=1.1, color=AMBER, zorder=3,
                label="communication share $r$")
    ax.set_xscale("log")
    ax.set_xlabel("link bandwidth per direction (GB/s); ports at twice the link rate",
                  fontsize=7.5)
    ax.set_ylabel("percent", fontsize=7.5)
    ax.set_ylim(0, (75 if with_r else 26))
    for p, lab in ((pts[2], "main point\n0.4 GB/s"), (pts[-1], "contrast\n12.5 GB/s")):
        ax.annotate(lab, (p["B_gbps"], 100 * p["G"]), textcoords="offset points",
                    xytext=(6, 10), fontsize=6.2, color=GREEN, linespacing=1.2)
    ax.text(0.97, 0.93, r"$G = \eta\,r$ at every point", transform=ax.transAxes,
            fontsize=6.6, ha="right", va="top", color=INK)
    ax.set_title("(a) One search, every bandwidth: the gain follows the share",
                 fontsize=8)
    ax.legend(fontsize=6.3, loc="upper right", bbox_to_anchor=(0.98, 0.86), frameon=False)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    tidy(ax)
    return sl, pts


def _fig6b(ax, bw="0.4"):
    """Port ratio and package geometry, each cell against its own strongest
    evaluated baseline, one statistic everywhere."""
    sw = load("kappa_geometry_sweep.json")
    stat = {}
    for cell_name, cell in sw["cells"].items():
        grid, k = cell_name.split("/")
        runs = cell["runs"]
        per_seed = {}
        for rn, r in runs.items():
            seed = rn.rsplit("_s", 1)[1]
            T = cell["rows"][rn]["T_s"][bw]
            per_seed.setdefault(seed, []).append(T)
        best_over_starts = [min(v) for v in per_seed.values()]
        base = min(v["T_s"][bw] for n, v in cell["rows"].items() if not n.startswith("sa_"))
        gains = sorted(100 * (1 - t / base) for t in best_over_starts)
        stat[(grid, float(k[1:]))] = {"median": gains[len(gains) // 2], "lo": gains[0],
                                      "hi": gains[-1], "baseline_ms": base * 1e3}
    for grid, col, mk in (("24x24", GREEN, "o"), ("12x48", SLATE, "s")):
        ks = sorted(k for (g, k) in stat if g == grid)
        med = [stat[(grid, k)]["median"] for k in ks]
        lo = [stat[(grid, k)]["median"] - stat[(grid, k)]["lo"] for k in ks]
        hi = [stat[(grid, k)]["hi"] - stat[(grid, k)]["median"] for k in ks]
        ax.errorbar(ks, med, yerr=[lo, hi], marker=mk, ms=5, lw=1.5, color=col,
                    capsize=2.5, elinewidth=0.9, label=f"{grid} package", zorder=4)
    ax.set_xticks([1, 2, 4])
    ax.set_xlabel(r"port capacity / link capacity, $\kappa$", fontsize=7.5)
    ax.set_ylabel("whole-model gain over the strongest\nbaseline of that cell (%)",
                  fontsize=7.5)
    ax.set_title(f"(b) When ports stop binding, placement can act ({bw} GB/s)",
                 fontsize=8)
    ax.text(0.03, 0.55, "ports bind:\nevery good layout\nsits on the port floor",
            transform=ax.transAxes, fontsize=6.2, va="top", color=INK, linespacing=1.3)
    leg = ax.legend(fontsize=6.4, loc="lower right", frameon=False,
                    title="median of three seeds, range over seeds")
    leg.get_title().set_fontsize(6.0)
    leg.get_title().set_color(INK)
    tidy(ax)
    return stat


def _fig6c(ax):
    """Prefill and decode read the same placement cost."""
    mc = load("main_config_results.json")
    rows = {r["layout"]: r for r in mc["rows"]} if isinstance(mc["rows"], list) else mc["rows"]
    pref, dec, fams = [], [], []
    for n, r in rows.items():
        if n == "sequential":
            continue
        pref.append(r["prefill"]["0.4"]["T_s"] * 1e3)
        dec.append(r["decode"]["0.4"]["T_s"] * 1e3)
        fams.append(LAYOUT_STYLE.get(n, (n, "search", "*"))[1])
    for f in ("default", "rule", "random", "search"):
        xs = [p for p, ff in zip(pref, fams) if ff == f]
        ys = [d for d, ff in zip(dec, fams) if ff == f]
        mk = {"default": "s", "rule": "^", "random": "o", "search": "*"}[f]
        ax.plot(xs, ys, marker=mk, ms=9 if mk == "*" else 5, color=FAM[f], ls="none",
                mec="white", mew=0.5, zorder=4,
                label={"default": "default fill", "rule": "compact rules",
                       "random": "random fills", "search": "search endpoints"}[f])
    ax.set_xlabel("prefill latency (ms)", fontsize=7.5)
    ax.set_ylabel("decode latency (ms)", fontsize=7.5)
    ax.set_title("(c) The two phases rank placements alike", fontsize=8)
    ax.text(0.04, 0.94, f"Spearman $\\rho$ = {mc['stats']['rank_prefill_vs_decode_0.4']:.3f}\n"
                        "no separate decode search", transform=ax.transAxes,
            fontsize=6.3, va="top", linespacing=1.3)
    ax.legend(fontsize=6.2, loc="lower right", frameon=False)
    tidy(ax)
    return rows


def fig6():
    SRC = ["analysis/bw_slice_k2.json", "analysis/kappa_geometry_sweep.json",
           "analysis/main_config_results.json"]
    fig, axes = plt.subplots(1, 2, figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.40))
    sl, pts = _fig6a(axes[0])
    stat = _fig6b(axes[1])
    fig.tight_layout()
    save(fig, "fig6_conditions", composite=True, sources=SRC)
    for tag, fn, kw in (("fig6a_bandwidth_slice", _fig6a, {}),
                        ("fig6a_bandwidth_slice_with_share", _fig6a, {"with_r": True}),
                        ("fig6b_kappa_geometry", _fig6b, {}),
                        ("fig6b_kappa_geometry_12p5", _fig6b, {"bw": "12.5"}),
                        ("fig6c_prefill_decode", _fig6c, {})):
        f, a = plt.subplots(figsize=(COL_WIDTH * 1.25, COL_WIDTH * 1.0))
        fn(a, **kw)
        f.tight_layout()
        save(f, tag, sources=SRC)
    dump_csv("fig6_bandwidth_slice", [
        {"point": k, "B_gbps": p["B_gbps"], "region": p["region"],
         "T_reference_ms": p["T_s_ref"] * 1e3, "T_selected_ms": p["T_s_sel"] * 1e3,
         "G_pct": 100 * p["G"], "eta_pct": 100 * p["eta"], "r_pct": 100 * p["r"]}
        for k, p in sl["points"].items()],
        ["point", "B_gbps", "region", "T_reference_ms", "T_selected_ms", "G_pct",
         "eta_pct", "r_pct"], sources=SRC[:1])
    dump_csv("fig6_kappa_geometry", [
        {"grid": g, "kappa": k, "gain_median_pct": v["median"], "gain_min_pct": v["lo"],
         "gain_max_pct": v["hi"], "strongest_baseline_ms": v["baseline_ms"],
         "statistic": "median over 3 seeds of best-over-3-starts, vs that cell's "
                      "strongest evaluated baseline"}
        for (g, k), v in sorted(stat.items())],
        ["grid", "kappa", "gain_median_pct", "gain_min_pct", "gain_max_pct",
         "strongest_baseline_ms", "statistic"], sources=SRC[1:2])


# =====================================================================
# index and manifest
# =====================================================================
INDEX_HEAD = """# Figure set v1: candidates for the paper

Run `{run_id}`, generated by `scripts/plot_dac2027_v1.py` from the frozen
records. Nothing outside this directory was written. Every panel exists as
`panels/<name>.pdf` (vector), `.svg` (editable) and `preview/<name>.png`;
combined candidates are in `composites/`; the numbers behind each panel are
in `data/`.

Main configuration unless a panel says otherwise: 2.7B class model, 512-token
serial prefill, 544 of 576 dies on a 24x24 mesh with XY routing, NeuRRAM
derived row time 10.14 us, kappa = 2, 0.4 GB/s per link direction. Deltas are
written as `change = (value / reference - 1) x 100%`, so a negative number is
a reduction; the reference is named in every panel's data file.

Rebuild everything with:

    python3 scripts/plot_dac2027_v1.py --run-id {run_id}

Only the PDFs, the plotting data and this index are committed; the SVG
sources and the PNG previews are left out of the repository and come back
from the command above.

"""


def write_index(run_id, missing):
    groups = [
        ("Fig. 1", "fig1_phase_diagram",
         ["fig1a_intra_die_phase", "fig1b_inter_die_phase"],
         "Placement is a phase: where it decides the cost, at two levels.",
         "Both axes are rates. Panel (a) is one die's two co-resident operators over all "
         "70 enumerated macro seatings, under the per-operator overlap model, so its regions "
         "say whether communication is exposed or masked. Panel (b) is the whole-model serial "
         "prefill over the seven named seating rules, so its regions say which cost dominates. "
         "Reference points project published parameters onto this instance.",
         "analysis/phase_diagram_isobar_k2.json, scripts/fig_phase_isobar.py"),
        ("Fig. 2", "fig2_platform_workflow", [],
         "What the platform computes, and where the search sits in it.",
         "Schematic. Mapping and partition generate the logical traffic; placement and routing "
         "turn it into link and port loads; latency and dynamic energy are two different "
         "aggregations of the same description. The search changes placement and partition and "
         "re-scores only the boundaries it touched. It optimises latency; energy is reported "
         "alongside. Carries no experimental numbers.",
         "schematic"),
        ("Fig. 3", "fig3_external_validation",
         ["fig3a_silicon_placement", "fig3b_packet_ranking"],
         "What the cost model is checked against.",
         "(a) Published placement measurements on a 4-chiplet package against the platform's "
         "two execution estimates; the round-serialized estimate tracks the measured ladder from "
         "below, with a residual of up to about 5%. The two estimates are model variants, not a "
         "confidence interval. (b) The same 13 candidate placements of a synthetic fan-out task "
         "scored by the analytic cost and by a cycle-level packet simulator, each relative to the "
         "strongest random layout; the identity line means equal relative change, not equal "
         "absolute time.",
         "analysis/simba_t1.json, analysis/b_fanout_24x24_rerank.json"),
        ("Fig. 4", "fig4_deployment_gain",
         ["fig4a_latency_breakdown", "fig4b_latency_energy", "fig4c_intra_die_layer"],
         "What the deployment choice is worth, and what it costs.",
         "(a) Whole-model prefill latency of every evaluated layout, split into the "
         "non-communication cost and the hand-off cost. (b) The same layouts in latency and "
         "system dynamic energy: the compact rules buy energy with latency, while the search "
         "moves latency at no energy cost. (c) The same platform one level down, on the instance "
         "that has within-die freedom; that level carries no modelled energy.",
         "analysis/mechanism_table.json, analysis/energy_export.json, "
         "analysis/intra_die_integration.json"),
        ("Fig. 5", "fig5_network_and_ablation",
         ["fig5_network_triptych", "fig5_network_clustered", "fig5_network_random_s3",
          "fig5_network_sa_random_s1", "fig5_network_least_manhattan",
          "fig5d_objective_ablation", "fig5_network_triptych_least_manhattan"],
         "The mechanism, on the real fabric.",
         "One hand-off stage, the same 25 flows and 26.2 M words in every panel, drawn on the "
         "real 24x24 die grid with the evaluator's own routing. Colour is the service time each "
         "link direction owes at 0.4 GB/s, on one shared scale. A compact placement funnels the "
         "flows through few links, a dispersed one spreads them, and the search keeps the "
         "dispersion while removing the remaining stacking. The last panel replaces the objective "
         "and keeps everything else fixed.",
         "scripts/search_eval.py (live), analysis/kappa_geometry_sweep.json, "
         "analysis/objective_ablation_k2.json"),
        ("Fig. 6", "fig6_conditions",
         ["fig6a_bandwidth_slice", "fig6a_bandwidth_slice_with_share",
          "fig6b_kappa_geometry", "fig6b_kappa_geometry_12p5", "fig6c_prefill_decode"],
         "The conditions that decide how much placement is worth.",
         "(a) One frozen pair of layouts re-scored across bandwidth, never re-searched: the "
         "communication improvement is constant and the whole-model gain follows the "
         "communication share. (b) Port capacity and package geometry, each cell against its own "
         "strongest evaluated baseline under one statistic. (c) Prefill and decode rank the same "
         "placements alike, which is why there is no separate decode search.",
         "analysis/bw_slice_k2.json, analysis/kappa_geometry_sweep.json, "
         "analysis/main_config_results.json"),
    ]
    L = [INDEX_HEAD.format(run_id=run_id)]
    for tag, comp, panels, claim, cap, src in groups:
        L.append(f"## {tag}  `{comp}`\n\n")
        L.append(f"**Supports:** {claim}\n\n")
        L.append(f"**Caption draft.** {cap}\n\n")
        L.append(f"**Sources:** {src}\n\n")
        if panels:
            L.append("**Standalone panels / alternates:** " +
                     ", ".join(f"`{p}`" for p in panels) + "\n\n")
    L.append("""## Statistics and denominators, once

| quantity | value | denominator | statistic |
|---|---|---|---|
| headline gain, prefill, 0.4 GB/s | 9.91% | strongest evaluated baseline `random_s3`, 2118.71 ms | median over 3 seeds of best-over-3-starts |
| same, range over seeds | 9.66 to 10.12% | same | three seeds |
| gain over the default fill | 54.47% | `default_A4` = `sequential`, 4192.54 ms | same selected layout |
| gain at 12.5 GB/s | 0.70% | `random_s3` at that bandwidth | same protocol |
| decode gain, 0.4 GB/s | 1.57% | `random_s3` | re-scored, no decode search |
| objective ablation | +11.4% / +11.2% | the best layout the resource-aware objective found, 1886.5 ms | best endpoint of each arm, same budget |
| intra-die layer gain | 9.02% | the shipped contiguous assignment, 49.597 ms | exhaustive optimum, includes the package hand-offs |
| dynamic energy of the headline layout | +0.26% | `random_s3`, 2.5229 J | same layouts as the headline gain |

The nine search endpoints, the three-seed median and the best of nine are
different statistics and are never interchanged. `default_A4` and
`sequential` are the same layout and appear once.

## Known gaps, stated rather than filled

""")
    for m in missing:
        L.append(f"- {m}\n")
    open(os.path.join(OUT["root"], "figure_index.md"), "w").write("".join(L))
    print("   figure_index.md")


def _preexisting_check():
    """A fingerprint of every figure that already existed in analysis/ when this
    run started, so a reader can verify that this run wrote only into its own
    directory. Compare two runs' lists to see that nothing outside changed."""
    import hashlib
    rows = []
    for fn in sorted(os.listdir(A)):
        if not fn.lower().endswith((".png", ".pdf", ".svg")):
            continue
        fp = os.path.join(A, fn)
        if not os.path.isfile(fp):
            continue
        h = hashlib.sha256(open(fp, "rb").read()).hexdigest()
        rows.append({"file": f"analysis/{fn}", "bytes": os.path.getsize(fp),
                     "sha256": h[:16]})
    return {"note": "figures that already existed in analysis/ at the start of this "
                    "run; this generator writes only inside its own run directory, "
                    "so every one of these is expected to be byte-identical after it",
            "count": len(rows), "files": rows}


def write_manifest(run_id, argv):
    man = {"run_id": run_id, "generator": "scripts/plot_dac2027_v1.py",
           "preexisting_outputs_check": _preexisting_check(),
           "command": " ".join(argv),
           "configuration": {
               "model": "2.7B class (d 2560, d_ff 10240, 32 layers)", "phase": "prefill",
               "sequence_length": 512, "dies": "544 of 576", "grid": "24x24 mesh, XY",
               "row_time_s": 10.14e-6, "kappa": 2.0, "link_gbps": 0.4,
               "contrast_link_gbps": 12.5},
           "delta_convention": "change = (value / reference - 1) x 100%",
           "products": PRODUCTS}
    json.dump(man, open(os.path.join(OUT["root"], "manifest.json"), "w"), indent=1)
    print("   manifest.json")


FIGS = {"fig1": fig1, "fig2": fig2, "fig3": fig3, "fig4": fig4, "fig5": fig5, "fig6": fig6}

MISSING = [
    "Fig. 3(a): the published T2 and T3 comparisons have recorded magnitude and shape "
    "disagreements and are not redrawn here; only T1 is. The older full comparison figure "
    "is unchanged in analysis/.",
    "Fig. 3(b): the packet simulator gives each node one terminal channel, so it cannot "
    "express kappa = 2; this panel is the kappa = 1 fan-out instance and is a communication "
    "batch, not the whole model.",
    "Fig. 4(c): the intra-die level has no energy coefficient on the macro link and no "
    "per-operator energy record for that instance, so its energy is not modelled, not zero.",
    "Fig. 5: one illustrative hand-off stage is drawn (ffn2 of layer 2), the same stage in "
    "every panel; the whole-model aggregate is in Fig. 4 and the mechanism table.",
    "Fig. 6(b): the two geometries are searched independently, so the same kappa can give "
    "slightly different endpoints; the cells are not forced to agree.",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--root", default=os.path.join(A, "figures_dac2027"))
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    root = os.path.join(args.root, args.run_id)
    OUT["root"] = root
    for k in ("panels", "composites", "data", "preview"):
        OUT[k] = os.path.join(root, k)
        os.makedirs(OUT[k], exist_ok=True)
    wanted = [w.strip() for w in args.only.split(",") if w.strip()] or list(FIGS)
    for w in wanted:
        print(f"[{w}]")
        FIGS[w]()
    if len(wanted) == len(FIGS):
        write_index(args.run_id, MISSING)
        write_manifest(args.run_id, sys.argv)
    print(f"\n-> {root}")


if __name__ == "__main__":
    main()
