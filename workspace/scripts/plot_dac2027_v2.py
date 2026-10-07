"""Paper figure set v2 (review notes v2, 2026-09-19).

Changes against v1: Fig. 5's mechanism instance is a CONTROLLED 4x4 die
mesh carrying the same 25-flow ffn hand-off (5 producer dies, 5 consumer
dies, 6 empty slots), re-placed, re-routed and re-scored in the evaluator's
own flow and load code; the objective ablation is a dot plot from zero;
Fig. 4's attributions and Fig. 6's statistics and wording are corrected;
Fig. 3's titles state what each panel validates and its rho is recomputed
from the candidate set drawn; Fig. 2 carries a real routing fragment from
the new instance. Formal captions go to captions.md, development notes to
figure_index.md, never into a figure.

Nothing outside the run directory is written; v1 is untouched.

    python3 scripts/plot_dac2027_v2.py --run-id 20260921_v2
"""
import argparse
import json
import math
import os
import random
import sys

os.environ.setdefault("ISOBAR_KAPPA", "2")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["svg.fonttype"] = "none"
matplotlib.rcParams["axes.linewidth"] = 0.7
matplotlib.rcParams["font.size"] = 8
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle

from scripts import plot_dac2027_v1 as V1          # utilities and the Fig. 1 panels
from scripts import search_eval as se

A = se.A
COL_WIDTH, PAGE_WIDTH = V1.COL_WIDTH, V1.PAGE_WIDTH
NAVY, SLATE, AMBER, GREEN, GREY, BRICK, CREAM, INK = (
    V1.NAVY, V1.SLATE, V1.AMBER, V1.GREEN, V1.GREY, V1.BRICK, V1.CREAM, V1.INK)
C_R, C_H = V1.C_R, V1.C_H
LOAD_CMAP = V1.LOAD_CMAP
FS = {"axis": 8, "tick": 7.5, "title": 9, "note": 7, "small": 6.5}
# every PDF / SVG / PNG is cropped to its content with no margin, so the
# LaTeX width is the figure's width
matplotlib.rcParams["savefig.pad_inches"] = 0.0

# method families: one colour semantics for every figure
FAM = {"stacked": NAVY, "heuristic": AMBER, "random": GREY, "search": GREEN}
FAM_LABEL = {"stacked": "Stacked fills (default, snake)",
             "heuristic": "Placement heuristics",
             "random": "Random fills", "search": "Search endpoints"}
NAME = {"default_A4": "Default (stacked fill)", "sequential": "Default (stacked fill)",
        "snake": "Snake", "clustered": "Clustered", "least_manhattan": "Least Manhattan",
        "nmap_greedy": "NMAP greedy", "heaviest_first": "Heaviest first",
        "random": "Random, seed 0", "random_s1": "Random, seed 1",
        "random_s2": "Random, seed 2", "random_s3": "Random, seed 3",
        "random_s4": "Random, seed 4", "sa_random_s1": "Search (representative)"}
COMPACT = ("clustered", "least_manhattan", "nmap_greedy")


def family(n):
    if n.startswith("sa_"):
        return "search"
    if n.startswith("random"):
        return "random"
    if n in ("default_A4", "sequential", "snake"):
        return "stacked"
    return "heuristic"


def marker(n):
    return {"stacked": "s", "heuristic": "^", "random": "o", "search": "*"}[family(n)]


def label(n):
    return NAME.get(n, n.replace("sa_", "Search, ").replace("_s", " seed "))


OUT, PRODUCTS = V1.OUT, V1.PRODUCTS
dump_json, dump_csv, load, tidy = V1.dump_json, V1.dump_csv, V1.load, V1.tidy


def _content_bbox(fig):
    """The union of everything actually drawn, in inches. An axes with its
    axis off (the inch-coordinate panels) contributes its artists, not its
    frame, so the crop reaches the ink and not the panel edge."""
    from matplotlib.transforms import Bbox
    r = fig.canvas.get_renderer()
    boxes = []
    axes = list(fig.axes)
    for ax in fig.axes:                               # inset axes (colour bars) too
        axes += list(ax.child_axes)
    for ax in axes:
        if ax.axison:
            boxes.append(ax.get_tightbbox(r))
            continue
        from matplotlib.spines import Spine
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
    for tx in fig.texts:
        boxes.append(tx.get_window_extent(r))
    if fig.legends:
        boxes += [lg.get_window_extent(r) for lg in fig.legends]
    return Bbox.union(boxes).transformed(fig.dpi_scale_trans.inverted())


def save(fig, name, composite=False, sources=(), note=""):
    """PDF + SVG next to each other, PNG preview, one manifest row; every
    file cropped to the drawn content with no margin."""
    kind = "composites" if composite else "panels"
    bb = _content_bbox(fig)
    for ext in ("pdf", "svg"):
        fig.savefig(V1._paths(kind, name, ext), bbox_inches=bb, pad_inches=0)
    fig.savefig(V1._paths("preview", name, "png"), dpi=200, bbox_inches=bb, pad_inches=0)
    plt.close(fig)
    PRODUCTS.append({"name": name, "kind": kind,
                     "files": [f"{kind}/{name}.pdf", f"{kind}/{name}.svg",
                               f"preview/{name}.png"],
                     "sources": list(sources), "note": note})
    print(f"   {kind}/{name}.pdf|svg  preview/{name}.png")
CAPTIONS = {}


# =====================================================================
# the controlled 4x4 instance for Fig. 5 (and the Fig. 2 fragment)
# =====================================================================
GRID = (4, 4)
KAPPA, BW = 2.0, 0.4
WPS = BW * 1e9


def _small_mesh():
    from scripts import interconnect as ic
    slots = [(float(x), float(y)) for y in range(GRID[1]) for x in range(GRID[0])]
    return ic.Mesh(slots, {"routing": "xy", "hub": "center"})


def _handoff():
    """The ffn1 -> ffn2 hand-off exactly as the 2.7B mapping produces it."""
    from scripts import llm_workload as lw
    W = se.Workload2p7B()
    base = lw.block_chain(W.cfg, W.S, "prefill", on_chip=True,
                          max_dies=W.fab.level("die").per_parent)
    names = [e["name"] for e in base]
    i = names.index("ffn2")
    return W.fab, base[i - 1], base[i]


def _flows(fab, prev_e, e, prod, cons):
    return se._one_boundary_flows(prev_e, e, list(prod), list(cons), fab)


def _score(mesh, fl):
    """Single-boundary version of the system latency term: busiest resource
    over links and ports (ports in link-time units, / kappa) plus the
    propagation of the longest path. Returns seconds and the pieces."""
    loads = se.resource_loads(fl, mesh, ports=True, kappa=KAPPA)
    links = {k: v for k, v in loads.items() if k[0] != "port"}
    ports = {k: v for k, v in loads.items() if k[0] == "port"}
    lmax, pmax = max(links.values()), max(ports.values())
    hops = [mesh.hops(*f["nodes"]) for f in fl]
    wh = sum(f["volume"] * f["width"] * h for f, h in zip(fl, hops))
    words = sum(f["volume"] * f["width"] for f in fl)
    busiest = max(lmax, pmax)
    t = busiest / WPS + max(hops) * 20e-9
    return {"t_s": t, "busiest_words": busiest, "max_link_words": lmax,
            "max_port_words_over_kappa": pmax,
            "binding": ("link" if lmax > pmax * (1 + 1e-9) else
                        "port" if pmax > lmax * (1 + 1e-9) else "tie"),
            "word_hops": wh, "words": words, "mean_hops": wh / words,
            "max_hops": max(hops), "loads": loads}


def _sa(mesh, fab, prev_e, e, start, seed, steps=1200, alpha=0.996, t0_frac=0.10):
    """Metropolis annealing over the 10 endpoints on the 16 slots: swap two
    endpoints or move one to an empty slot; the objective is the single-
    boundary latency term; schedule as the main search (1200 steps, 0.996)
    with t0 = 10% of the start's cost (declared)."""
    rng = random.Random(seed)
    prod, cons = list(start[0]), list(start[1])
    n = GRID[0] * GRID[1]

    def cost(p, c):
        return _score(mesh, _flows(fab, prev_e, e, p, c))["t_s"]
    cur = cost(prod, cons)
    best, best_pc = cur, (list(prod), list(cons))
    T = cur * t0_frac
    curve = []
    for step in range(1, steps + 1):
        p, c = list(prod), list(cons)
        used = set(p) | set(c)
        free = [s for s in range(n) if s not in used]
        if rng.random() < 0.5 or not free:          # swap two endpoints
            i, j = rng.sample(range(10), 2)
            arr = p + c
            arr[i], arr[j] = arr[j], arr[i]
            p, c = arr[:5], arr[5:]
        else:                                        # migrate to an empty slot
            i = rng.randrange(10)
            arr = p + c
            arr[i] = rng.choice(free)
            p, c = arr[:5], arr[5:]
        new = cost(p, c)
        if new <= cur or rng.random() < math.exp(-(new - cur) / max(T, 1e-12)):
            prod, cons, cur = p, c, new
            if cur < best - 1e-15:
                best, best_pc = cur, (list(prod), list(cons))
        T *= alpha
        if step % 100 == 0:
            curve.append((step, best))
    return best, best_pc, curve


def _small_instance():
    """Builds the three layouts and their loads; every number here is from
    the evaluator's own flow construction and load accumulation."""
    mesh = _small_mesh()
    fab, prev_e, e = _handoff()
    n = GRID[0] * GRID[1]
    layouts = {}
    # compact fill: the stacked default, stages in consecutive row-major slots
    compact = (list(range(0, 5)), list(range(5, 10)))
    layouts["compact_fill"] = {"prod": compact[0], "cons": compact[1],
                               "label": "Compact fill", "family": "stacked",
                               "rule": "stages in consecutive row-major slots"}
    # random fills, seeds 0-4, the best one is the representative
    rnd = {}
    for s in range(5):
        rng = random.Random(s)
        slots = rng.sample(range(n), 10)
        rnd[s] = (slots[:5], slots[5:])
        sc = _score(mesh, _flows(fab, prev_e, e, *rnd[s]))
        layouts[f"random_seed{s}"] = {"prod": rnd[s][0], "cons": rnd[s][1],
                                      "label": f"Random, seed {s}", "family": "random",
                                      "rule": "uniform choice of 10 of the 16 slots"}
    # the search: starts = compact fill and random seed 0; SA seeds 0-2
    runs = {}
    for seed in range(3):
        for sname, st in (("compact", compact), ("random0", rnd[0])):
            best, pc, curve = _sa(mesh, fab, prev_e, e, st, seed)
            runs[f"sa_{sname}_seed{seed}"] = {"t_s": best, "prod": pc[0], "cons": pc[1],
                                              "curve": curve, "start": sname, "seed": seed}
    per_seed = {}
    for k, r in runs.items():
        per_seed.setdefault(r["seed"], []).append((r["t_s"], k))
    best_over_starts = {s: min(v) for s, v in per_seed.items()}
    order = sorted(best_over_starts.items(), key=lambda kv: kv[1][0])
    med_seed, (med_t, med_key) = order[len(order) // 2]
    for s, (t, k) in best_over_starts.items():
        r = runs[k]
        layouts[f"search_seed{s}"] = {"prod": r["prod"], "cons": r["cons"],
                                      "label": f"Search, seed {s}", "family": "search",
                                      "rule": f"best of 2 starts ({r['start']})",
                                      "run": k}
    # score everything, record loads with coordinates
    for name, L in layouts.items():
        fl = _flows(fab, prev_e, e, L["prod"], L["cons"])
        sc = _score(mesh, fl)
        links, ports = [], []
        for k, v in sc["loads"].items():
            if k[0] == "port":
                x, y = mesh.coord(k[1])
                ports.append({"node": k[1], "x": x, "y": y, "side": k[2],
                              "words_over_kappa": v, "service_ms": v / WPS * 1e3})
            else:
                m = V1.SEG_RE.search(k[0]) if V1.SEG_RE else None
                import re
                m = re.search(r"seg\((\d+), (\d+)\)-\((\d+), (\d+)\)", k[0])
                x0, y0, x1, y1 = (int(g) for g in m.groups())
                links.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "dir": k[1],
                              "words": v, "flows": int(round(v / fl[0]["volume"])),
                              "service_ms": v / WPS * 1e3})
        L.update({k: v for k, v in sc.items() if k != "loads"})
        L["links"], L["ports"] = links, ports
        L["endpoints"] = ([{"id": f"P{i+1}", "node": p, "x": mesh.coord(p)[0],
                            "y": mesh.coord(p)[1], "role": "producer"}
                           for i, p in enumerate(L["prod"])] +
                          [{"id": f"C{i+1}", "node": c, "x": mesh.coord(c)[0],
                            "y": mesh.coord(c)[1], "role": "consumer"}
                           for i, c in enumerate(L["cons"])])
        L["busiest_service_ms"] = sc["busiest_words"] / WPS * 1e3
        L["max_link_service_ms"] = sc["max_link_words"] / WPS * 1e3
        L["max_port_service_ms"] = sc["max_port_words_over_kappa"] / WPS * 1e3
    best_random = min((k for k in layouts if k.startswith("random_seed")),
                      key=lambda k: layouts[k]["t_s"])
    fl0 = _flows(fab, prev_e, e, *compact)
    return {"grid": f"{GRID[0]}x{GRID[1]}", "kappa": KAPPA, "bw_gbps": BW,
            "handoff": {"from": prev_e["name"], "to": e["name"], "n_flows": len(fl0),
                        "words_per_flow": fl0[0]["volume"] * fl0[0]["width"],
                        "words_total": sum(f["volume"] * f["width"] for f in fl0),
                        "split_of_producer": prev_e["split"],
                        "port_floor_words_over_kappa": 5 * fl0[0]["volume"] / KAPPA},
            "search_protocol": {"steps": 1200, "alpha": 0.996, "t0": "10% of the start's cost",
                                "starts": ["compact fill", "random seed 0"],
                                "seeds": [0, 1, 2],
                                "statistic": "best over the 2 starts per seed; the "
                                             "representative is the median seed"},
            "representative": {"compact": "compact_fill", "random": best_random,
                               "search": f"search_seed{med_seed}"},
            "search_runs": {k: {kk: vv for kk, vv in r.items()} for k, r in runs.items()},
            "layouts": layouts}


# Fig. 5 colours: the card families of Figs. 3-4 (markers light, text darker)
F5 = dict(fam={"stacked": "#68b4ce", "random": GREY, "search": "#98b578",
               "links": "#80cdbb", "proxy": "#5868a0"},
          txt={"stacked": "#3f7f93", "random": "#7a7a7a", "search": "#6f8f52",
               "links": "#418b78", "proxy": "#3f4c7a"})
# the Fig. 5 ramp: sequential from the idle blue through peach to a vivid
# red, with no neutral stop in the middle (a grey lane would read as idle)
# blue runs to ~5 ms (a quarter of the ramp), from a deeper idle blue up to
# a pale one, then peach -> vivid red
LOAD_F5 = matplotlib.colors.LinearSegmentedColormap.from_list(
    "isobar_load_f5", [(p, (r / 255, g / 255, b / 255)) for p, (r, g, b) in
                       ((0.0, (104, 156, 200)), (0.125, (160, 196, 226)), (0.25, (210, 227, 240)),
                        (0.33, (247, 205, 180)), (0.55, (240, 150, 120)), (0.78, (215, 70, 70)),
                        (1.0, (185, 25, 42)))])
TITLE5 = {"compact_fill": "Compact", "random_seed3": "Random", "search_seed0": "Resource-aware"}


def _small_norm(inst, names):
    """One linear ramp for the three panels: zero to the busiest link of
    the set."""
    Ls = [inst["layouts"][n] for n in names]
    vmax = max(l["service_ms"] for L in Ls for l in L["links"])
    vport = max(L["max_port_service_ms"] for L in Ls)
    return Normalize(vmin=0.0, vmax=vmax), vmax, vport


def _draw_roads(ax, L, norm, ox, oy, s=0.29, r=0.085, off=0.04):
    """The 4x4 instance in the Fig. 2(b) idiom, in inches on an _inch_axes:
    every physical link is two lanes (one per direction) drawn as roads with
    a dark rim and filled by the service time they owe, idle lanes at the
    ramp's zero; small white nodes with black labels, producers as rounded
    squares, consumers as circles, empty slots thin; the busiest link is
    labelled with its flow count."""
    nx, ny = GRID
    EDGE = "#2b2f33"
    LANE, RIM = 3.2, 0.35
    NODE_LW, EMPTY_LW, FS_N = 0.7, 0.35, 4.8
    CM = LOAD_F5
    IDLE = CM(0.0)
    X = lambda i: ox + i * s
    Y = lambda j: oy + j * s
    used = {(l["x0"], l["y0"], l["x1"], l["y1"], l["dir"]): l for l in L["links"]}

    def road(p0, p1, fill):
        ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=EDGE, lw=LANE + 2 * RIM,
                solid_capstyle="butt", zorder=2)
        ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=fill, lw=LANE,
                solid_capstyle="butt", zorder=3)
    for x in range(nx):
        for y in range(ny):
            for (x1, y1) in ((x + 1, y), (x, y + 1)):
                if x1 >= nx or y1 >= ny:
                    continue
                horiz = y1 == y
                for d in ("+", "-"):
                    sg = 1 if d == "+" else -1
                    dx, dy = (0, sg * off) if horiz else (-sg * off, 0)
                    l = used.get((x, y, x1, y1, d))
                    road((X(x) + dx, Y(y) + dy), (X(x1) + dx, Y(y1) + dy),
                         IDLE if l is None else CM(norm(l["service_ms"])))
    ep = {e["node"]: e for e in L["endpoints"]}
    for n in range(nx * ny):
        x, y = n % nx, n // nx
        cx, cy = X(x), Y(y)
        if n not in ep:
            ax.add_patch(Circle((cx, cy), r, fc="white", ec=EDGE, lw=EMPTY_LW, zorder=6))
            continue
        e = ep[n]
        if e["role"] == "producer":
            rs = 0.92 * r
            ax.add_patch(FancyBboxPatch((cx - rs, cy - rs), 2 * rs, 2 * rs,
                                        boxstyle="round,pad=0,rounding_size=0.022",
                                        fc="white", ec=EDGE, lw=NODE_LW, zorder=6))
        else:
            ax.add_patch(Circle((cx, cy), r, fc="white", ec=EDGE, lw=NODE_LW, zorder=6))
        ax.text(cx, cy, e["id"], fontsize=FS_N, color="black", ha="center",
                va="center_baseline", zorder=7, fontweight="bold")
    # the busiest resource, labelled with its flow count
    top = L["busiest_words"]
    if L["binding"] in ("link", "tie"):
        hot = next(l for l in L["links"] if l["words"] >= top - 1e-6)
        horiz = hot["y0"] == hot["y1"]
        sg = 1 if hot["dir"] == "+" else -1
        dx, dy = (0, sg * off) if horiz else (-sg * off, 0)
        hx = (X(hot["x0"]) + X(hot["x1"])) / 2 + dx
        hy = (Y(hot["y0"]) + Y(hot["y1"])) / 2 + dy
        lab = "e*"
        kw = dict(fontsize=5.4, color=TXT, zorder=9)
        if horiz:
            ax.text(hx, hy + 0.045 * sg, lab, ha="center", va="bottom" if sg > 0 else "top", **kw)
        else:
            ax.text(hx - 0.045 * sg, hy, lab, ha="right" if sg > 0 else "left", va="center", **kw)
    else:
        hot = next(p for p in L["ports"] if p["words_over_kappa"] >= top - 1e-6)
        ax.add_patch(Circle((X(hot["x"]), Y(hot["y"])), r + 0.025, fc="none", ec=EDGE,
                            lw=0.7, ls=(0, (2, 1.5)), zorder=8))
    return hot


def _ramp_strip(ax, x, y, w, h, norm, label="Link service time (ms)"):
    """A horizontal hand-drawn colour bar (imshow strip) at (x, y) inches."""
    cbx = ax.inset_axes((x, y, w, h), transform=ax.transData)
    vals = np.linspace(0.0, norm.vmax, 512)
    cbx.imshow(LOAD_F5(norm(vals))[None, :, :], origin="lower", aspect="auto",
               extent=(0, norm.vmax, 0, 1), interpolation="nearest")
    cbx.set_xlim(0, norm.vmax); cbx.set_ylim(0, 1)
    cbx.set_yticks([])
    cbx.set_xticks([0, 10, 20])
    cbx.tick_params(labelsize=5.2, length=1.5, pad=1, width=0.5, colors=TXT)
    for sp in cbx.spines.values():
        sp.set_linewidth(0.4)
    cbx.set_xlabel(label, fontsize=5.6, color=TXT, labelpad=1)
    return cbx


def _mesh_block(ax, inst, names, norm, x0=0.0, y0=0.0, s=0.29, r=0.085, gap=0.24):
    """The three meshes side by side on one _inch_axes, close together, each
    with its title above and its two readings below (busiest-link service
    time first, then the routed traffic); the shared colour bar and the node
    key under them. Returns the block's width and height in inches."""
    mesh_w = 3 * s + 2 * r
    Ls = [inst["layouts"][n] for n in names]
    y_cb = y0 + 0.12                                  # colour bar and node key, one row
    y_read = y_cb + 0.22                              # readings (two lines)
    oy = y_read + 0.42 + r                            # mesh origin
    y_title = oy + 3 * s + r + 0.10
    for i, (n, L) in enumerate(zip(names, Ls)):
        ox = x0 + r + i * (mesh_w + gap)
        _draw_roads(ax, L, norm, ox, oy, s=s, r=r)
        cx = ox - r + mesh_w / 2
        ax.text(cx, y_title, f"({'abc'[i]}) {TITLE5.get(n, L['label'])}", fontsize=FS["axis"],
                color=TXT, ha="center", va="bottom")
        ax.text(cx, y_read + 0.22, f"{L['busiest_service_ms']:.1f} ms", fontsize=8.0,
                color=TXT, ha="center", va="bottom", fontweight="bold")
        ax.text(cx, y_read + 0.20, f"{L['word_hops'] / 1e6:.1f} M word-hops", fontsize=5.8,
                color="0.4", ha="center", va="top")
    # colour bar, left; node key, right
    _ramp_strip(ax, x0 + 0.05, y_cb + 0.08, 1.35, 0.09, norm)
    kx = x0 + 1.75
    ky = y_cb + 0.125
    rs = 0.92 * 0.07
    ax.add_patch(FancyBboxPatch((kx, ky - rs), 2 * rs, 2 * rs, boxstyle="round,pad=0,rounding_size=0.02",
                                fc="white", ec="#2b2f33", lw=0.7, zorder=6))
    ax.text(kx + 2 * rs + 0.05, ky, "producer die", fontsize=5.6, color=TXT, va="center")
    ax.add_patch(Circle((kx + 0.72 + 0.07, ky), 0.07, fc="white", ec="#2b2f33", lw=0.7, zorder=6))
    ax.text(kx + 0.72 + 0.14 + 0.05, ky, "consumer die", fontsize=5.6, color=TXT, va="center")
    ax.add_patch(Circle((kx + 1.50 + 0.07, ky), 0.07, fc="white", ec="#2b2f33", lw=0.35, zorder=6))
    ax.text(kx + 1.50 + 0.14 + 0.05, ky, "empty slot", fontsize=5.6, color=TXT, va="center")
    return 3 * mesh_w + 2 * gap, y_title


def _fig5_networks(inst, names, fname, composite=True):
    norm, vmax, vport = _small_norm(inst, names)
    W, H = 3.85, 2.13
    fig = plt.figure(figsize=(W, H))
    ax = _inch_axes(fig, [0, 0, 1, 1], W, H)
    _mesh_block(ax, inst, names, norm, x0=0.06, y0=0.02)
    save(fig, fname, composite=composite,
         sources=["scripts/search_eval.py (live: _one_boundary_flows, resource_loads)",
                  "scripts/interconnect.py (Mesh 4x4, xy)"],
         note="controlled instance; not the 544-die layouts")
    return norm


def _fig5_ablation(ax, ref_pos="below", narrow=False):
    """Same searcher, same start (random seed 0), same three annealer seeds
    and budget; only the objective changes. Every endpoint is re-scored
    under the system latency and shown as overhead over the full
    objective's best seed, so the panel answers: replacing the objective
    costs how much of the deployment's performance?"""
    ab = load("objective_ablation_k2.json")["cells"]["k2"]
    rows, po = ab["rows"], ab["per_objective"]
    names = ["ours", "wire_only", "word_hops", "max_hops"]
    labels = ["Full", "Links\nonly", "Word-\nhops", "Max\nhops"]
    fam = {"ours": "search", "wire_only": "links", "word_hops": "proxy", "max_hops": "proxy"}
    base = min(rows[e]["T_single_s"] for e in po["ours"]["endpoints"]) * 1e3
    out = []
    for i, n in enumerate(names):
        T = sorted(rows[e]["T_single_s"] * 1e3 for e in po[n]["endpoints"])
        ov = [100 * (t / base - 1) for t in T]
        c, ct = F5["fam"][fam[n]], F5["txt"][fam[n]]
        ax.plot([i] * len(ov), ov, marker="o", ms=3.8, mfc="white", mec=c, mew=1.0, ls="none",
                zorder=4)
        ax.plot([i], [ov[0]], marker="D", ms=4.8, color=c, mec=INK, mew=0.6, ls="none", zorder=6)
        if i == 0 and ref_pos == "below":
            ax.annotate("ref.", (i, ov[0]), textcoords="offset points", xytext=(0, -7),
                        ha="center", va="top", fontsize=FS["small"], color=ct)
        elif i == 0:
            ax.annotate("ref.", (i, ov[0]), textcoords="offset points", xytext=(5, 2),
                        ha="left", va="bottom", fontsize=FS["small"], color=ct)
        elif i == 1:
            ax.annotate(f"{ov[0]:+.1f}%", (i, ov[0]), textcoords="offset points", xytext=(5, 2),
                        ha="left", va="bottom", fontsize=FS["small"], color=ct)
        elif narrow and i == 2:                     # narrow panel: word-hops label to the left
            ax.annotate(f"{ov[0]:+.1f}%", (i, ov[0]), textcoords="offset points", xytext=(-5, 0),
                        ha="right", va="center", fontsize=FS["small"], color=ct)
        else:                                       # the two proxies: label under the diamond
            ax.annotate(f"{ov[0]:+.1f}%", (i, ov[0]), textcoords="offset points", xytext=(0, -6),
                        ha="center", va="top", fontsize=FS["small"], color=ct)
        out.append({"objective": n, "T_ms": T, "best_ms": T[0],
                    "overhead_vs_full_best_pct": ov, "best_overhead_pct": ov[0]})
    ax.axhline(0, color=F5["txt"]["search"], lw=0.7, ls=(0, (3, 2)), zorder=3)
    ax.set_xticks(range(4)); ax.set_xticklabels(labels, fontsize=FS["small"], linespacing=1.1)
    ax.set_xlim(-0.5, 3.5); ax.set_ylim(-2.2, 15.0)
    ax.set_yticks([0, 5, 10, 15])
    ax.set_ylabel("Latency overhead (%)", fontsize=FS["note"], labelpad=1)
    tidy(ax, grid="y")
    ax.tick_params(labelsize=FS["small"])
    return ab, base, out


def fig5():
    inst = _small_instance()
    rep = inst["representative"]
    names = [rep["compact"], rep["random"], rep["search"]]
    norm = _fig5_networks(inst, names, "fig5_small_mesh_triptych")
    for n in names:
        PW, PH = 1.6, 1.95
        f = plt.figure(figsize=(PW, PH)); a = _inch_axes(f, [0, 0, 1, 1], PW, PH)
        L = inst["layouts"][n]
        _draw_roads(a, L, norm, 0.30 + 0.085, 0.62 + 0.085)
        a.text(PW / 2, PH - 0.04, TITLE5.get(n, L["label"]), fontsize=FS["axis"],
               color=F5["txt"][L["family"]], ha="center", va="top")
        a.text(PW / 2, 0.52, f"{L['busiest_service_ms']:.1f} ms", fontsize=8.0, color=TXT,
               ha="center", va="top", fontweight="bold")
        a.text(PW / 2, 0.36, f"{L['word_hops'] / 1e6:.1f} M word-hops", fontsize=5.8,
               color="0.4", ha="center", va="top")
        _ramp_strip(a, 0.25, 0.12, 1.1, 0.07, norm)
        save(f, f"fig5_small_mesh_{n}", sources=["scripts/search_eval.py (live)"])
    # link-load profile candidate: loads in descending order for the three layouts
    f, a = plt.subplots(figsize=(COL_WIDTH * 1.1, COL_WIDTH * 0.85))
    for n in names:
        L = inst["layouts"][n]
        v = sorted((l["service_ms"] for l in L["links"]), reverse=True)
        a.step(range(1, len(v) + 1), v, where="mid", color=F5["fam"][L["family"]], lw=1.5,
               label=TITLE5.get(n, L["label"]))
    a.axhline(inst["layouts"][names[0]]["max_port_service_ms"], color=INK, lw=0.8,
              ls=(0, (2, 2)))
    a.text(0.98, inst["layouts"][names[0]]["max_port_service_ms"] + 0.3,
           "port floor (every consumer's ejection)", fontsize=FS["small"], ha="right",
           transform=a.get_yaxis_transform(), color=INK)
    a.set_xlabel("link directions, busiest first", fontsize=FS["axis"])
    a.set_ylabel("service time (ms)", fontsize=FS["axis"])
    a.set_title("Link-load profile of the three placements", fontsize=FS["title"])
    a.legend(fontsize=FS["small"], frameon=False)
    tidy(a)
    f.tight_layout()
    save(f, "fig5_small_mesh_load_profile", sources=["scripts/search_eval.py (live)"],
         note="candidate; the same instance as the triptych")
    f, a = plt.subplots(figsize=(1.7, 1.7))
    ab, base, abrows = _fig5_ablation(a)
    a.set_title("Objective ablation, 544-die system", fontsize=FS["axis"], color=TXT)
    f.tight_layout()
    save(f, "fig5d_objective_ablation", sources=["analysis/objective_ablation_k2.json"])
    # composite: one row, the mechanism example left and the system ablation right
    Wt, Ht = 5.95, 2.13
    fig = plt.figure(figsize=(Wt, Ht))
    axl = _inch_axes(fig, [0, 0, 4.15 / Wt, 1], 4.15, Ht)
    bw, y_title = _mesh_block(axl, inst, names, norm, x0=0.08, y0=0.04)
    y_bot = 0.36                                      # tick labels end on the colour bar's label line
    axd = fig.add_axes([4.30 / Wt, y_bot / Ht, 1.50 / Wt, (y_title - 0.14 - y_bot) / Ht])
    _fig5_ablation(axd)
    fig.text((4.30 + 0.75) / Wt, y_title / Ht, "(d) Ablation, 544-die system", fontsize=FS["axis"],
             color=TXT, ha="center", va="bottom")
    h = inst["handoff"]
    save(fig, "fig5_mechanism_and_ablation", composite=True,
         sources=["scripts/search_eval.py (live)", "analysis/objective_ablation_k2.json"])
    # tall variant for comparison: (a) (b) on the first row with the colour
    # bar and key to the right of (b); (c) (d) on the second, (d)'s x axis on
    # (c)'s mesh bottom and its right edge on the figure's right content edge
    s, r = 0.29, 0.085
    mesh_w = 3 * s + 2 * r
    W2, H2 = 3.05, 3.42
    xr = W2 - 0.08                                    # right content edge
    col = [0.08, 0.08 + mesh_w + 0.18]                # (a) and (b) close together
    row_h = 1.66
    y_rows = [H2 - 0.04 - row_h, H2 - 0.04 - 2 * row_h]
    fig = plt.figure(figsize=(W2, H2))
    ax = _inch_axes(fig, [0, 0, 1, 1], W2, H2)
    cells = [(0, 0, names[0], "a"), (0, 1, names[1], "b"), (1, 0, names[2], "c")]
    geo = {}
    for ri, ci, n, letter in cells:
        L = inst["layouts"][n]
        ox = col[ci] + r
        cx = col[ci] + mesh_w / 2
        y_read = y_rows[ri] + 0.02
        oy = y_read + 0.42 + r
        _draw_roads(ax, L, norm, ox, oy, s=s, r=r)
        y_title = oy + 3 * s + r + 0.10
        ax.text(cx, y_title, f"({letter}) {TITLE5.get(n, L['label'])}",
                fontsize=FS["note"], color=TXT, ha="center", va="bottom")
        ax.text(cx, y_read + 0.22, f"{L['busiest_service_ms']:.1f} ms", fontsize=8.0, color=TXT,
                ha="center", va="bottom", fontweight="bold")
        ax.text(cx, y_read + 0.20, f"{L['word_hops'] / 1e6:.1f} M word-hops", fontsize=5.8,
                color="0.4", ha="center", va="top")
        geo[letter] = dict(oy=oy, y_title=y_title)
    # a short vertical colour bar and a compact node key, right of (b)
    bx0 = col[1] + mesh_w + 0.16
    oy_b = geo["b"]["oy"]
    cbx = ax.inset_axes((bx0, oy_b + 1.2 * s, 0.06, 1.8 * s + r), transform=ax.transData)
    vals = np.linspace(0.0, norm.vmax, 512)
    cbx.imshow(LOAD_F5(norm(vals))[:, None, :], origin="lower", aspect="auto",
               extent=(0, 1, 0, norm.vmax), interpolation="nearest")
    cbx.set_xlim(0, 1); cbx.set_ylim(0, norm.vmax)
    cbx.set_xticks([]); cbx.yaxis.tick_right()
    cbx.set_yticks([0, 10, 20])
    cbx.tick_params(labelsize=5.0, length=1.5, pad=1, width=0.5, colors=TXT)
    for sp in cbx.spines.values():
        sp.set_linewidth(0.4)
    cbx.set_title("ms", fontsize=5.2, color=TXT, pad=2)
    key_txt = []
    for k, (kind, lab) in enumerate((("sq", "producer"), ("ci", "consumer"), ("em", "empty"))):
        ky = oy_b + 0.35 * s - k * 0.125
        if kind == "sq":
            rs = 0.92 * 0.04
            ax.add_patch(FancyBboxPatch((bx0 + 0.04 - rs, ky - rs), 2 * rs, 2 * rs,
                                        boxstyle="round,pad=0,rounding_size=0.012",
                                        fc="white", ec="#2b2f33", lw=0.55, zorder=6))
        else:
            ax.add_patch(Circle((bx0 + 0.04, ky), 0.04, fc="white", ec="#2b2f33",
                                lw=0.55 if kind == "ci" else 0.3, zorder=6))
        key_txt.append(ax.text(bx0 + 0.11, ky, lab, fontsize=4.6, color=TXT, va="center"))
    # the right content edge: the widest of the key texts and the bar's tick labels
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    ext = [tx.get_window_extent(rend).x1 for tx in key_txt]
    ext += [tl.get_window_extent(rend).x1 for tl in cbx.get_yticklabels()]
    xr = max(ext) / fig.dpi - 0.20                   # visually flush, not overhanging
    # (d): x axis on (c)'s mesh bottom, right edge on the content edge, title on (c)'s line
    y_axis = geo["c"]["oy"] - r
    y_top = geo["c"]["y_title"] - 0.14
    dx0 = col[0] + mesh_w + 0.40
    axd = fig.add_axes([dx0 / W2, y_axis / H2, (xr - dx0) / W2, (y_top - y_axis) / H2])
    _fig5_ablation(axd, ref_pos="right", narrow=True)
    axd.tick_params(labelsize=5.0)
    axd.yaxis.label.set_fontsize(5.6)
    for tx in axd.texts:
        tx.set_fontsize(5.2)
    fig.text((dx0 + xr) / 2 / W2, geo["c"]["y_title"] / H2, "(d) Ablation, 544-die system",
             fontsize=FS["note"], color=TXT, ha="center", va="bottom")
    save(fig, "fig5_mechanism_and_ablation_tall", composite=True,
         sources=["scripts/search_eval.py (live)", "analysis/objective_ablation_k2.json"],
         note="comparison variant: (a) (b) over (c) (d); the standing form is the one-row composite")
    # data
    slim = {k: v for k, v in inst.items() if k not in ("layouts", "search_runs")}
    slim["layouts"] = {n: {k: v for k, v in L.items() if k not in ("links", "ports")}
                       for n, L in inst["layouts"].items()}
    slim["search_runs"] = {k: {kk: vv for kk, vv in r.items() if kk != "curve"}
                           for k, r in inst["search_runs"].items()}
    slim["search_curves"] = {k: r["curve"] for k, r in inst["search_runs"].items()}
    dump_json("fig5_small_mesh_instance", slim, sources=["scripts/search_eval.py (live)"])
    for n, L in inst["layouts"].items():
        dump_csv(f"fig5_small_links_{n}", L["links"],
                 ["x0", "y0", "x1", "y1", "dir", "words", "flows", "service_ms"])
        dump_csv(f"fig5_small_ports_{n}", L["ports"],
                 ["node", "x", "y", "side", "words_over_kappa", "service_ms"])
        dump_csv(f"fig5_small_endpoints_{n}", L["endpoints"], ["id", "node", "x", "y", "role"])
    dump_json("fig5_ablation", {
        "protocol": "same feasible space, solver, budget, starts and seeds; only the "
                    "objective changes; every output re-scored under the system latency",
        "denominator": "the best endpoint of the resource-aware objective, "
                       f"{base:.2f} ms",
        "by_objective": abrows,
        "reference_full_objective_best_ms": base,
        "batch": "the ablation's own batch: one start (random fill, seed 0), three annealer "
                 "seeds, 1200 steps per objective; not the Fig. 4 search runs",
        "recorded_loss_avoided_pct": {n: ab["per_objective"][n]["loss_avoided_by_ours_pct"]
                                      for n in ("wire_only", "word_hops", "max_hops")}},
        sources=["analysis/objective_ablation_k2.json"])
    reps = {k: inst["layouts"][v] for k, v in rep.items()}
    ov = {r["objective"]: r["best_overhead_pct"] for r in abrows}
    for L in reps.values():
        L["busiest_flows"] = max(L["links"], key=lambda l: l["words"])["flows"]
    CAPTIONS["fig5"] = (
        "Fig. 5. Where link stacking comes from, and what the objective is worth. "
        "(a)-(c) A 4x4 mechanism example: one ffn hand-off of the 2.7B mapping, five "
        f"producer dies to five consumer dies, {h['n_flows']} flows of "
        f"{h['words_per_flow'] / 1e6:.2f} M words, placed on a 4x4 die mesh with XY routing, "
        "0.4 GB/s per link direction and ports at twice the link rate; six slots stay "
        "empty. Every panel carries the same flows; only the placement differs: the compact "
        "fill, the best of five random fills (seed 3), and the resource-aware search (the "
        "same annealer as the main configuration, 1200 steps, two starts, three seeds, best "
        "over starts per seed, median seed shown). Each physical link is two lanes, one per "
        "direction, coloured by the link service time it owes on one shared ramp (the port "
        f"bound, {reps['search']['max_port_service_ms']:.2f} ms, never binds here); e* marks the "
        f"busiest link ({reps['compact']['busiest_flows']}, {reps['random']['busiest_flows']} and "
        f"{reps['search']['busiest_flows']} flows). Under each mesh: the busiest link's service "
        f"time ({reps['compact']['busiest_service_ms']:.1f}, {reps['random']['busiest_service_ms']:.1f}, "
        f"{reps['search']['busiest_service_ms']:.1f} ms) and the routed traffic "
        f"({reps['compact']['word_hops'] / 1e6:.1f}, {reps['random']['word_hops'] / 1e6:.1f}, "
        f"{reps['search']['word_hops'] / 1e6:.1f} M word-hops): the random fill and the search "
        "route the same traffic, yet the busiest link differs by a third. Hand-off service "
        "costs on a controlled instance, not whole-model gains. (d) The 544-die system's "
        "objective ablation, its own batch: the same searcher from the same start (the "
        "random fill, seed 0) with the same three annealer seeds and budget (1200 steps), "
        "only the objective replaced; every endpoint re-scored under the system latency and "
        f"shown as overhead over the full objective's best seed ({base:.1f} ms); hollow circles "
        "are the three seeds, the diamond the best seed. Dropping the "
        f"port term costs {ov['wire_only']:.1f}%; the distance and hop proxies cost "
        f"{ov['word_hops']:.1f}% and {ov['max_hops']:.1f}%. These endpoints are not the Fig. 4 "
        "search runs, which start from three families and take the best start per seed.")
    return inst


# =====================================================================
# Fig. 2  the platform (left) and why per-resource accounting matters (right)
# =====================================================================
# Panel (a) is the author's draw.io drawing (fig2a.drawio, 2026-09-22),
# transcribed here so the matplotlib panel, the composite and the draw.io
# export all come from one layout. Coordinates are draw.io pixels (x right,
# y down); the renderer maps them onto the 5.02 x 2.90 in panel.
TITLE = "#2b3a4f"
TXT = "#24313c"
ARR = "#3c4650"


def _inch_axes(fig, rect, w, h):
    ax = fig.add_axes(rect)
    ax.set_xlim(0, w); ax.set_ylim(0, h); ax.set_aspect("equal"); ax.axis("off")
    return ax


def _fig2a_spec():
    """The platform figure as data, in draw.io pixels."""
    Z = [dict(id="dcfg", x=50, y=1010, w=290, h=160, fill="#ebf7f4", edge="#80cdbb",
              title="Deployment configuration"),
         dict(id="inputs", x=50, y=1200, w=290, h=410, fill="#f1f6eb", edge="#a5c582",
              title="User Configuration"),
         dict(id="core", x=370, y=1010, w=570, h=600, fill="#f5f9fd", edge="#5a96cc",
              title="Isobar evaluation core"),
         dict(id="phase", x=980, y=1010, w=290, h=270, fill="#f0f8fa", edge="#68b4ce",
              title="Phase analysis"),
         dict(id="search", x=980, y=1330, w=290, h=280, fill="#e9f5f1", edge="#489684",
              title="Deployment search")]
    CORE = dict(fill="#5a96cc", edge="#5a96cc", elw=1.2, text="white")
    INP = dict(fill="white", edge="#a5c582", elw=3.2, text=TXT)
    PH = dict(fill="#a4d2e2", edge="#a4d2e2", elw=1.2, text="black")
    SR = dict(fill="#489684", edge="#489684", elw=1.2, text="white")   # a deep teal of its own
    B = [dict(id="pp", x=70, y=1070, title="Partition & placement", sub=None,
              fill="#80cdbb", edge="#80cdbb", elw=1.2, text=TXT),
         dict(id="wl", x=70, y=1260, title="Workload", sub="Model, sequence length", **INP),
         dict(id="ot", x=70, y=1370, title="Operator tiling\n& dependencies", sub=None, **INP),
         dict(id="hw", x=70, y=1480, title="Hardware &\nexecution settings",
              sub="routing, device, execution mode", **INP),
         dict(id="ext", x=530, y=1070, title="Extract logical transfers",
              sub="Sources, destinations, volumes", **CORE),
         dict(id="rt", x=530, y=1180, title="Route & accumulate loads",
              sub="Fixed routing; link & port loads", **CORE),
         dict(id="cw", x=390, y=1290, title="Compute, write\n& digital costs", sub=None, **CORE),
         dict(id="cc", x=670, y=1290, title="Communication costs",
              sub="Service bounds & comm. energy", **CORE),
         dict(id="ag", x=530, y=1400, title="Aggregate execution costs",
              sub="Comp–comm overlap;\nserial hand-offs", **CORE),
         dict(id="lt", x=530, y=1510, title="Latency &\nDynamic energy", sub=None, bold=True,
              fill="white", edge="#5a96cc", elw=3.2, text=TXT),
         dict(id="sw", x=1000, y=1068.8, title="Sweep device rate\n& bandwidth", sub=None, **PH),
         dict(id="pb", x=1000, y=1178.8, title="Extract phase\nboundaries", sub=None, **PH),
         dict(id="dp", x=1000, y=1390, title="Partition &\ngroup sizing (DP)", sub=None, **SR),
         dict(id="sa", x=1000, y=1500, title="Die placement (SA) &\nMacro assignment", sub=None, **SR)]
    for b in B:
        b.setdefault("w", 250); b.setdefault("h", 80)
    E = [  # (points, colour, width px, label)
        dict(pts=[(655, 1150), (655, 1180)], col="#416c93", lw=2.5),
        dict(pts=[(655, 1260), (655, 1270), (795, 1270), (795, 1290)], col="#416c93", lw=2.5),
        dict(pts=[(515, 1370), (515, 1380), (655, 1380), (655, 1400)], col="#416c93", lw=2.5),
        dict(pts=[(795, 1370), (795, 1380), (655, 1380), (655, 1400)], col="#416c93", lw=2.5),
        dict(pts=[(655, 1480), (655, 1510)], col="#416c93", lw=2.5),
        dict(pts=[(340, 1100), (530, 1100)], col="#418b78", lw=3),
        dict(pts=[(340, 1230), (460, 1230), (460, 1130), (530, 1130)], col="#6e8d4e", lw=3),
        dict(pts=[(340, 1230), (460, 1230), (460, 1290)], col="#6e8d4e", lw=3),
        dict(pts=[(195, 1200), (195, 1170)], col="#6e8d4e", lw=3),
        dict(pts=[(195, 1610), (195, 1640), (1125, 1640), (1125, 1610)], col="#6e8d4e", lw=3),
        dict(pts=[(780, 1550), (980, 1550)], col="#416c93", lw=3,
             label=("Latency", 880, 1535)),
        dict(pts=[(940, 1109), (980, 1109)], col="#416c93", lw=3),
        dict(pts=[(980, 1080), (940, 1080)], col="#4b8294", lw=3),
        dict(pts=[(1125, 1148.8), (1125, 1178.8)], col="#4b8294", lw=2.5),
        dict(pts=[(1125, 1470), (1125, 1500)], col="#2f6b5c", lw=2.5),
        dict(pts=[(1270, 1470), (1290, 1470), (1290, 980), (200, 980), (200, 1010)],
             col="#2f6b5c", lw=3, label=("Updated deployment", 282.5, 965))]
    return dict(zones=Z, boxes=B, edges=E, x0=45, x1=1295, y0=948, y1=1645)


def _fig2a(ax, W=5.02, H=3.00):
    """(a) The platform, drawn from _fig2a_spec onto a W x H inch axes."""
    S = _fig2a_spec()
    sc = (S["x1"] - S["x0"]) / W                     # draw.io px per inch
    hin = (S["y1"] - S["y0"]) / sc
    yoff = 0.14 + (H - 0.14 - hin) / 2               # centred below the panel-letter row
    X = lambda x: (x - S["x0"]) / sc
    Y = lambda y: H - yoff - (y - S["y0"]) / sc
    L = lambda px: px / sc                            # px -> in
    PT = lambda px: px * 72 / sc                      # px -> pt
    FS, FS_SUB = PT(20), PT(16) * 1.02
    dash = (0, (PT(8), PT(4), PT(1), PT(4)))
    fig = ax.figure
    rend = fig.canvas.get_renderer()

    def fit(t, max_w):                                # shrink a text to its box
        for _ in range(14):
            if t.get_window_extent(renderer=rend).width / fig.dpi <= max_w:
                break
            t.set_fontsize(t.get_fontsize() * 0.95)

    for z in S["zones"]:
        ax.add_patch(Rectangle((X(z["x"]), Y(z["y"] + z["h"])), L(z["w"]), L(z["h"]),
                               fc=z["fill"], ec=z["edge"], lw=PT(2.5), ls=dash, zorder=1))
        t = ax.text(X(z["x"] + 22), Y(z["y"] + 25), z["title"], fontsize=FS, color=TITLE,
                    ha="left", va="center", fontweight="bold", zorder=5)
        fit(t, L(z["w"] - 34))
    for b in S["boxes"]:
        ax.add_patch(FancyBboxPatch((X(b["x"]), Y(b["y"] + b["h"])), L(b["w"]), L(b["h"]),
                                    boxstyle=f"round,pad=0,rounding_size={L(16)}",
                                    fc=b["fill"], ec=b["edge"], lw=PT(b["elw"]), zorder=3))
        xm, ym = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
        wt = "bold" if b.get("bold") else "normal"
        if b["sub"] is None:
            t = ax.text(X(xm), Y(ym), b["title"], fontsize=FS, color=b["text"], ha="center",
                        va="center", linespacing=1.2, fontweight=wt, zorder=4)
            fit(t, L(b["w"] - 12))
        else:
            nt, ns = b["title"].count("\n") + 1, b["sub"].count("\n") + 1
            lt, ls = nt * 24, ns * 19.2                       # px, line height 1.2
            top = ym - (lt + ls) / 2
            t = ax.text(X(xm), Y(top + lt / 2), b["title"], fontsize=FS, color=b["text"],
                        ha="center", va="center", linespacing=1.2, fontweight=wt, zorder=4)
            fit(t, L(b["w"] - 12))
            s = ax.text(X(xm), Y(top + lt + ls / 2), b["sub"], fontsize=FS_SUB, color=b["text"],
                        ha="center", va="center", linespacing=1.2, zorder=4)
            fit(s, L(b["w"] - 12))
    for e in S["edges"]:
        pts = [(X(x), Y(y)) for x, y in e["pts"]]
        lw = PT(e["lw"])
        if len(pts) > 2:
            xs, ys = zip(*pts[:-1])
            ax.plot(xs, ys, color=e["col"], lw=lw, zorder=5, solid_joinstyle="miter",
                    solid_capstyle="butt")
        ax.add_patch(FancyArrowPatch(pts[-2], pts[-1], arrowstyle="-|>", mutation_scale=lw * 6,
                                     color=e["col"], lw=lw, zorder=6, shrinkA=0, shrinkB=0))
        if "label" in e:
            s, lx, ly = e["label"]
            ax.text(X(lx), Y(ly), s, fontsize=FS_SUB, color=TXT, ha="center", va="center",
                    style="italic", zorder=7)
    return W, H


def _fig2a_drawio(path):
    """The same layout as an editable draw.io diagram (mxGraph XML, draw.io px)."""
    from xml.sax.saxutils import escape
    S = _fig2a_spec()
    q = lambda s: escape(s, {'"': "&quot;"})
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    def rect(cid, x, y, w, h, value, style):
        cells.append(f'<mxCell id="{cid}" value="{q(value)}" style="{style}" vertex="1" parent="1">'
                     f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    for z in S["zones"]:
        rect(z["id"], z["x"], z["y"], z["w"], z["h"], "",
             f"rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4 1 4;fillColor={z['fill']};"
             f"strokeColor={z['edge']};strokeWidth=2.5;")
        rect(z["id"] + "_t", z["x"] + 20, z["y"] + 10, z["w"] - 40, 30,
             f'<span style="font-size:20px;font-weight:700;color:{TITLE}">{q(z["title"])}</span>',
             "text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;")
    for b in S["boxes"]:
        title = q(b["title"]).replace("\n", "<br>")
        if b.get("bold"):
            title = f"<b>{title}</b>"
        value = f'<span style="font-size:20px">{title}</span>'
        if b["sub"] is not None:
            value += "<br>" + q(b["sub"]).replace("\n", "<br>")
        rect(b["id"], b["x"], b["y"], b["w"], b["h"], value,
             f"rounded=1;arcSize=20;whiteSpace=wrap;html=1;fillColor={b['fill']};"
             f"strokeColor={b['edge']};strokeWidth={b['elw']};fontSize=16;fontColor="
             f"{'#ffffff' if b['text'] == 'white' else ('#000000' if b['text'] == 'black' else b['text'])};")
    for i, e in enumerate(S["edges"]):
        (x0, y0), (x1, y1) = e["pts"][0], e["pts"][-1]
        way = "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in e["pts"][1:-1])
        cells.append(f'<mxCell id="e{i}" style="html=1;endArrow=block;endFill=1;rounded=0;'
                     f'strokeColor={e["col"]};strokeWidth={e["lw"]};" edge="1" parent="1">'
                     f'<mxGeometry relative="1" as="geometry"><mxPoint x="{x0}" y="{y0}" as="sourcePoint"/>'
                     f'<mxPoint x="{x1}" y="{y1}" as="targetPoint"/><Array as="points">{way}</Array>'
                     f'</mxGeometry></mxCell>')
        if "label" in e:
            s, lx, ly = e["label"]
            rect(f"e{i}l", lx - 90, ly - 15, 180, 30, f"<i>{q(s)}</i>",
                 "text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;fontSize=16;")
    xml = ('<mxfile host="isobar" version="2"><diagram id="fig2a" name="Fig. 2(a) platform">'
           '<mxGraphModel grid="1" gridSize="10" page="1" pageWidth="827" pageHeight="1169">'
           '<root>' + "".join(cells) + '</root></mxGraphModel></diagram></mxfile>')
    open(path, "w").write(xml)
    return path


def _fig2_instance():
    """One deployment of the Fig. 5 instance (the compact fill), evaluated
    live: the 25 ffn1 -> ffn2 flows, XY routes, per-direction link loads,
    port loads over kappa, word-hops. Also the routed path of every flow
    so that one producer's fan-out can be drawn."""
    import re
    mesh = _small_mesh()
    fab, prev_e, e = _handoff()
    prod, cons = list(range(0, 5)), list(range(5, 10))
    fl = _flows(fab, prev_e, e, prod, cons)
    sc = _score(mesh, fl)
    seg = re.compile(r"seg\((\d+), (\d+)\)-\((\d+), (\d+)\)")
    links, ports = {}, {}
    for k, v in sc["loads"].items():
        if k[0] == "port":
            ports[(k[1], k[2])] = v
        else:
            x0, y0, x1, y1 = (int(g) for g in seg.search(k[0]).groups())
            links[(x0, y0, x1, y1, k[1])] = v
    paths = {}
    for f in fl:
        a, b = f["nodes"]
        paths[(a, b)] = [(tuple(int(g) for g in seg.search(r).groups()), d)
                         for r, d in mesh.path_directed(a, b)]
    return {"mesh": mesh, "flows": fl, "score": sc, "links": links, "ports": ports,
            "paths": paths, "prod": prod, "cons": cons,
            "handoff": {"from": prev_e["name"], "to": e["name"], "n_flows": len(fl),
                        "words_per_flow": fl[0]["volume"] * fl[0]["width"]}}


LOAD_BR = matplotlib.colors.LinearSegmentedColormap.from_list(
    "isobar_load_br", [(r / 255, g / 255, b / 255) for r, g, b in
                       ((47, 120, 174), (49, 124, 183), (109, 173, 209), (182, 215, 232),
                        (233, 241, 244), (247, 203, 180), (246, 178, 147), (220, 109, 87),
                        (183, 34, 48), (109, 1, 31))])
# the RdBu ten-step ramp with the blue end lightened (it is the idle-lane
# colour) and the first peach stop deepened (the 7.9 ms lanes read as pink)


def _fig2b(ax, I):
    """(b) Resource accounting: the real ffn hand-off on the controlled
    instance, its link loads after routing, and the service-time profile
    the evaluator reads the binding cost from. Node boxes; each physical
    link is two lanes (one per direction) drawn as roads with a dark rim,
    filled by the load colour, idle lanes at the zero end of the ramp; lanes run
    centre to centre and the nodes cover their ends. Only the occupied rows
    are drawn: the XY routes never enter the idle top row (asserted), so
    every number is the 4x4 instance's."""
    W, H = 2.32, 3.00
    FS_T, FS_N, FS, FS_K = 6.2, 6.0, 5.6, 5.2      # title, node label, text, ticks
    TXT = "#24313c"
    EDGE = "#2b2f33"
    mesh, links, ports = I["mesh"], I["links"], I["ports"]
    sc, h = I["score"], I["handoff"]
    vpf = h["words_per_flow"]
    ms = lambda words: words / WPS * 1e3
    # ---- title block
    ax.text(0.245, H - 0.02, "RESOURCE ACCOUNTING", fontsize=FS_T, color=TITLE,
            ha="left", va="top", fontweight="bold")
    ax.text(0.23, H - 0.15, f"{h['from'].upper()} → {h['to'].upper()} · 5→5 dies · "
            f"{h['n_flows']} transfers", fontsize=FS, color=TXT, ha="left", va="top")
    # ---- the occupied rows of the instance
    occ = {int(mesh.coord(n)[1]) for n in I["prod"] + I["cons"]}
    ny = max(occ) + 1
    assert all(max(k[1], k[3]) < ny for k in links), "a route enters an idle row"
    nx = GRID[0]
    ox, oy, s = 0.384, 1.556, 0.47                  # mesh origin and pitch (in)
    r, off = 0.144, 0.06
    LANE, RIM = 4.9, 0.4                            # lane fill width, rim width (pt)
    NODE_LW, EMPTY_LW = 0.85, 0.4                    # node edge heavier than the rim
    CM = LOAD_BR
    IDLE_FILL = CM(0.0)                              # idle lanes: the ramp's zero colour
    X = lambda i: ox + i * s
    Y = lambda j: oy + j * s
    # the diverging ramp is centred on the port bound: blue lanes cannot bind,
    # red lanes exceed it, the hotspot is the deepest red
    vmax = max(links.values()); tport = max(ports.values())
    norm = matplotlib.colors.TwoSlopeNorm(vmin=0.0, vcenter=ms(tport), vmax=ms(vmax))

    def road(p0, p1, fill):
        ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=EDGE, lw=LANE + 2 * RIM,
                solid_capstyle="butt", zorder=2)
        ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=fill, lw=LANE,
                solid_capstyle="butt", zorder=3)
    for x in range(nx):
        for y in range(ny):
            for (x1, y1) in ((x + 1, y), (x, y + 1)):
                if x1 >= nx or y1 >= ny:
                    continue
                horiz = y1 == y
                for d in ("+", "-"):
                    sg = 1 if d == "+" else -1
                    dx, dy = (0, sg * off) if horiz else (-sg * off, 0)
                    v = links.get((x, y, x1, y1, d))
                    road((X(x) + dx, Y(y) + dy), (X(x1) + dx, Y(y1) + dy),
                         IDLE_FILL if v is None else CM(norm(ms(v))))
    ep = {}
    for i, p in enumerate(I["prod"]):
        ep[p] = (f"P{i + 1}", "producer")
    for i, c in enumerate(I["cons"]):
        ep[c] = (f"C{i + 1}", "consumer")
    for n in range(nx * GRID[1]):
        x, y = (int(v) for v in mesh.coord(n))
        if y >= ny:
            continue
        cx, cy = X(x), Y(y)
        if n not in ep:
            ax.add_patch(Circle((cx, cy), r, fc="white", ec=EDGE, lw=EMPTY_LW, zorder=6))
            continue
        lab, role = ep[n]
        if role == "producer":
            rs = 0.92 * r                            # a square reads larger than a circle
            ax.add_patch(FancyBboxPatch((cx - rs, cy - rs), 2 * rs, 2 * rs,
                                        boxstyle="round,pad=0,rounding_size=0.035",
                                        fc="white", ec=EDGE, lw=NODE_LW, zorder=6))
        else:
            ax.add_patch(Circle((cx, cy), r, fc="white", ec=EDGE, lw=NODE_LW, zorder=6))
        ax.text(cx, cy, lab, fontsize=FS_N, color="black", ha="center", va="center_baseline",
                zorder=7, fontweight="bold")
    # the hot link e*, labelled once
    hot_key = max(links, key=links.get)
    hx0, hy0, hx1, hy1, hd = hot_key
    horiz = hy0 == hy1
    sg = 1 if hd == "+" else -1
    dx, dy = (0, sg * off) if horiz else (-sg * off, 0)
    hx, hy = (X(hx0) + X(hx1)) / 2 + dx, (Y(hy0) + Y(hy1)) / 2 + dy
    nflows = int(round(links[hot_key] / vpf))
    ax.text(hx - 0.05, hy, "e*", fontsize=FS, color=TXT, ha="right", va="center", zorder=9)
    ax.text(X(0) - r, oy - r - 0.07, f"e*  {nflows} flows \u00b7 {links[hot_key] / 1e6:.1f} M words",
            fontsize=FS, color=TXT, ha="left", va="top", zorder=9)
    # a short colour bar, bottom-aligned with the mesh; drawn by hand as one
    # raster strip sampled through the same norm so the fill and the frame
    # coincide in PDF and SVG (matplotlib's colorbar mesh under a TwoSlopeNorm
    # did not)
    cb_x, cb_w = X(nx - 1) + r + 0.16, 0.076
    cbx = ax.inset_axes((cb_x, oy - r, cb_w, 0.64), transform=ax.transData)
    vals = np.linspace(0.0, ms(vmax), 512)
    cbx.imshow(CM(norm(vals))[:, None, :], origin="lower", aspect="auto",
               extent=(0, 1, 0, ms(vmax)), interpolation="nearest")
    cbx.set_xlim(0, 1); cbx.set_ylim(0, ms(vmax))
    cbx.set_xticks([]); cbx.yaxis.tick_right()
    cbx.set_yticks([0, ms(tport), ms(vmax)])
    cbx.set_yticklabels(["0", f"{ms(tport):.1f}", f"{ms(vmax):.0f}"])
    cbx.tick_params(labelsize=FS_K, length=1.5, pad=1, width=0.5, colors=TXT)
    for sp in cbx.spines.values():
        sp.set_linewidth(0.4)
    cbx.set_title("ms", fontsize=FS_K, color=TXT, pad=2)
    # ---- the service-time profile, aligned under the mesh
    used = sorted(links.values(), reverse=True)
    x_left, x_right = X(0) - r, cb_x + cb_w          # as wide as the mesh plus the colour bar
    # the profile's x axis sits on the flowchart's zone bottom line (0.17 in in the composite)
    bx = ax.inset_axes((x_left, 0.172, x_right - x_left, 1.03), transform=ax.transData)
    n = len(used)
    bx.bar(range(n), [ms(v) for v in used], color=[CM(norm(ms(v))) for v in used],
           width=0.74, zorder=3)
    bx.plot([-0.6, n - 0.4], [ms(tport)] * 2, color=EDGE, lw=0.6, ls=(0, (3, 2)), zorder=4)
    bx.text(n - 0.4, 12.2, f"Port bound {ms(tport):.1f} ms", fontsize=FS, color=TXT,
            ha="right", va="bottom")
    bx.text(0.55, ms(used[0]) + 1.2, f"e*\n{ms(used[0]):.1f} ms", fontsize=FS, color=TXT,
            ha="left", va="top", linespacing=1.25)
    bx.text(0.985, 0.97, f"Total routed traffic\n{sc['word_hops'] / 1e6:.1f} M word-hops",
            transform=bx.transAxes, fontsize=FS, color=TXT, ha="right", va="top", linespacing=1.25)
    bx.set_xlim(-0.6, n - 0.4)
    bx.set_ylim(0, ms(vmax) * 1.30)              # headroom for the e* reading
    bx.set_xticks([])
    bx.set_yticks([0, 10, 20])
    bx.tick_params(labelsize=FS_K, length=1.5, pad=1, width=0.5, colors=TXT)
    bx.set_ylabel("Lₑ / B  (ms)", fontsize=FS, labelpad=1, color=TXT)
    bx.set_xlabel("Directed links, sorted", fontsize=FS, labelpad=1.5, color=TXT)
    for sp in ("top", "right"):
        bx.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        bx.spines[sp].set_linewidth(0.5)
    bx.set_facecolor("none")
    return W, H


def _fig2b_data(I):
    """The numbers behind panel (b), from the same evaluation."""
    sc, links, ports = I["score"], I["links"], I["ports"]
    hot = max(links, key=links.get)
    return {"instance": "Fig. 5 controlled 4x4 die mesh, compact fill (the stacked default)",
            "grid": f"{GRID[0]}x{GRID[1]}", "routing": "xy", "kappa": KAPPA, "bw_gbps": BW,
            "drawn_rows": "y = 0..2; the idle top row is not drawn and no XY route enters it, "
                          "so every number is the 4x4 instance's",
            "handoff": I["handoff"], "prod_slots": I["prod"], "cons_slots": I["cons"],
            "busiest_link": {"from": [hot[0], hot[1]], "to": [hot[2], hot[3]], "dir": hot[4],
                             "flows": int(round(links[hot] / I["handoff"]["words_per_flow"])),
                             "words": links[hot], "service_ms": links[hot] / WPS * 1e3},
            "used_link_directions": len(links),
            "link_service_ms_sorted": sorted((v / WPS * 1e3 for v in links.values()), reverse=True),
            "port_bound_ms": max(ports.values()) / WPS * 1e3,
            "binding": sc["binding"], "word_hops": sc["word_hops"], "words": sc["words"],
            "mean_hops": sc["mean_hops"], "max_hops": sc["max_hops"],
            "fan_out_producer": max(I["prod"], key=lambda p: sum(len(I["paths"][(p, c)])
                                                                 for c in I["cons"]))}


def fig2(inst=None):
    I = _fig2_instance()
    Wt, Ht = 7.54, 3.00                              # (a) 5.02 + gap 0.20 + (b) 2.32
    fig = plt.figure(figsize=(Wt, Ht))
    axa = _inch_axes(fig, [0, 0, 5.02 / Wt, 1], 5.02, Ht); _fig2a(axa)
    axb = _inch_axes(fig, [5.22 / Wt, 0, 2.32 / Wt, 1], 2.32, Ht); _fig2b(axb, I)
    # panel letters clear of both panels' content, tops level with (b)'s title
    yl = (Ht - 0.02) / Ht
    fig.text(0.006, yl, "(a)", fontsize=7.5, fontweight="bold", va="top")
    fig.text(5.22 / Wt + 0.004, yl, "(b)", fontsize=7.5, fontweight="bold", va="top")
    save(fig, "fig2_platform_workflow", composite=True,
         sources=["schematic", "scripts/search_eval.py (live: _one_boundary_flows, resource_loads)",
                  "scripts/interconnect.py (Mesh 4x4, xy)"],
         note="(a) schematic; (b) the Fig. 5 instance's compact fill, evaluated live")
    f = plt.figure(figsize=(5.02, 3.00)); a = _inch_axes(f, [0, 0, 1, 1], 5.02, 3.00); _fig2a(a)
    save(f, "fig2a_platform", sources=["schematic"])
    dpath = os.path.join(OUT["panels"], "fig2a_platform.drawio")
    _fig2a_drawio(dpath)
    PRODUCTS.append({"name": "fig2a_platform_drawio", "kind": "panels",
                     "files": ["panels/fig2a_platform.drawio"], "sources": ["schematic"],
                     "note": "editable draw.io export of the same layout (192 px per inch)"})
    print("   panels/fig2a_platform.drawio")
    f = plt.figure(figsize=(2.32, 3.00)); a = _inch_axes(f, [0, 0, 1, 1], 2.32, 3.00); _fig2b(a, I)
    save(f, "fig2b_placement_to_costs", sources=["scripts/search_eval.py (live)"])
    D = _fig2b_data(I)
    dump_json("fig2b_placement_to_costs", D, sources=["scripts/search_eval.py (live)"])
    hot = D["busiest_link"]
    CAPTIONS["fig2"] = (
        "Fig. 2. The platform. (a) The inputs are the workload, the given operator tiling with its "
        "tensor dependencies, and the hardware and execution settings; the platform generates no "
        "mapping. The evaluation core scores one deployment configuration: it extracts the logical "
        "transfers, routes them under the fixed rule and accumulates link and port loads, prices "
        "the communication from those loads, and aggregates it with the compute, write and digital "
        "costs under the execution relation into latency and dynamic energy. The phase analysis "
        "calls the core over device rates, bandwidths and placement sets; the deployment "
        "search calls it on candidates and returns the updated deployment. (b) Resource accounting on the "
        f"controlled instance of Fig. 5: the {D['handoff']['from']} to {D['handoff']['to']} hand-off of the "
        f"2.7B mapping, five producer dies to five consumer dies, {D['handoff']['n_flows']} transfers of "
        f"{D['handoff']['words_per_flow'] / 1e6:.2f} M words each, placed by the compact fill on the 4x4 die "
        "mesh with XY routing, 0.4 GB/s per link direction and ports at twice the link rate; the idle top "
        "row is not drawn. Each physical link has one lane per direction, coloured by its cumulative "
        "load on a diverging scale whose white is the port bound: idle lanes sit at the zero end, blue "
        f"lanes cannot bind, red lanes exceed it. The busiest link e* carries {hot['flows']} transfers, "
        f"{hot['words'] / 1e6:.1f} M words. Below, the service time of every used link direction in "
        f"decreasing order on the same colour scale, against the port bound of {D['port_bound_ms']:.1f} ms: "
        "the load concentrates on a few links, the hand-off is link-bound, and the evaluator reads its "
        f"latency term from e*. The {D['word_hops'] / 1e6:.1f} M word-hops of the same evaluation are the "
        "cumulative traffic that sets the communication part of the dynamic energy.")


# =====================================================================
# Fig. 3  external references
# =====================================================================
def _spearman(x, y):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                rk[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return rk
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den


# Fig. 3 colours: the author's colour card, its light swatches each darkened
# by 8%: blue (104,180,206), green (165,197,130), yellow (243,222,103)
_F3 = dict(meas="#60a6be", bound="#98b578", est="#e0cc5f",
           fam={"stacked": "#60a6be", "heuristic": "#e0cc5f", "random": GREY,
                "search": "#98b578"})


def _seating_glyph(ax, rect, seating, side, caption):
    """A 6x6 chiplet grid with the four seated chiplets filled, as an
    inset in axes fraction `rect`; caption below."""
    g = ax.inset_axes(rect)
    n = 6
    for i in range(n):
        for j in range(n):
            g.add_patch(Rectangle((i, j), 1, 1, fc="white", ec="0.75", lw=0.35))
    for (i, j) in seating:
        g.add_patch(Rectangle((i + 0.08, j + 0.08), 0.84, 0.84, fc=_F3["meas"], ec="none"))
    g.set_xlim(0, n); g.set_ylim(0, n); g.set_aspect("equal"); g.axis("off")
    g.text(n / 2, n + 0.5, caption, fontsize=FS["small"], color=INK, ha="center", va="bottom",
           transform=g.transData, linespacing=1.15)
    return g


def _fig3a(ax):
    t1 = load("simba_t1.json")
    rows = t1["rows"]
    dist = [max(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a in r["seating"] for b in r["seating"])
            for r in rows]
    x = np.arange(len(rows))
    meas = [r["measured_norm"] for r in rows]
    lo = [r["ratio_max_end"] for r in rows]
    est = [r["ratio_pess"] for r in rows]
    ax.plot(x, meas, marker="s", ms=6, color=_F3["meas"], ls="none", label="Measured silicon",
            zorder=5)
    ax.plot(x, lo, marker="o", ms=4.5, lw=1.4, color=_F3["bound"], zorder=4,
            label="Resource-service bound")
    ax.plot(x, est, marker="D", ms=4.5, mew=1.6, lw=1.7, ls="--", color=_F3["est"], mfc="white",
            zorder=4, label="Isobar execution estimate")
    ax.annotate(f"{meas[-1]:.2f}× measured\n{est[-1]:.2f}× estimate",
                (x[-1], meas[-1]), textcoords="offset points", xytext=(-8, -2),
                ha="right", va="top", fontsize=FS["note"], color=INK, linespacing=1.25)
    # what changes between the seatings: the four chiplets spread from an
    # adjacent block to the corners of a 6x6 region (only the two ends drawn)
    _seating_glyph(ax, [0.59, 0.10, 0.15, 0.24], rows[0]["seating"], 6, f"adjacent\n{dist[0]} hops")
    _seating_glyph(ax, [0.83, 0.10, 0.15, 0.24], rows[-1]["seating"], 6, f"corners\n{dist[-1]} hops")
    ax.annotate("", xy=(0.825, 0.22), xytext=(0.745, 0.22), xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=0.8, mutation_scale=8))
    ax.text(0.985, 0.45, "Four-chiplet placements", transform=ax.transAxes,
            fontsize=FS["small"], color=INK, ha="right", va="bottom")
    ax.set_xticks(x); ax.set_xticklabels([f"{d:g}" for d in dist], fontsize=FS["tick"])
    ax.set_xlabel("Longest producer-consumer distance (hops)", fontsize=FS["axis"])
    ax.set_ylabel("Relative latency", fontsize=FS["axis"])
    ax.set_ylim(0.9, 2.72)
    ax.set_title("(a) SIMBA: placement sensitivity", fontsize=FS["title"])
    ax.legend(fontsize=FS["small"], loc="upper left", frameon=False, labelspacing=0.5,
              handlelength=2.2, borderaxespad=0.3)
    tidy(ax, grid="y")
    return t1, dist


def _fig3b(ax):
    fan = load("b_fanout_24x24_rerank.json")
    r = fan["rows"]
    ref = fan["summary"]["strongest_random_under_ours"]
    names = list(r)
    rho = _spearman([r[n]["ours_words"] for n in names], [r[n]["booksim_cycles"] for n in names])
    ends = fan["summary"]["endpoints"]
    gains = [v["gain_booksim_vs_booksim_best_random_pct"] for v in ends.values()]
    pts = {n: (r[n]["ours_words"] / r[ref]["ours_words"],
               r[n]["booksim_cycles"] / r[ref]["booksim_cycles"]) for n in names}

    def scatter(a, ms_scale=1.0):
        for n in names:
            fam = "search" if n.startswith("sa_") else family(n if n != "dispersed" else "x")
            mk = {"stacked": "s", "heuristic": "^", "random": "o", "search": "*"}[fam]
            a.plot([pts[n][0]], [pts[n][1]], marker=mk, color=_F3["fam"][fam], mec="white", mew=0.5,
                   ms={"*": 9, "^": 7, "s": 5.5, "o": 5.5}[mk] * ms_scale, ls="none", zorder=5)

    lim = [0.6, 5.0]
    scatter(ax)
    ax.plot(lim, lim, color="0.6", lw=0.8, ls=(0, (4, 3)), zorder=2)
    ax.text(2.5, 2.2, "y = x", fontsize=FS["small"], color="0.45", ha="left", va="top")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(*lim); ax.set_ylim(*lim)
    for a in (ax.xaxis, ax.yaxis):
        a.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
        a.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_xticks([0.6, 1, 2, 4]); ax.set_yticks([0.6, 1, 2, 4])
    ax.set_xlabel("Relative analytical cost", fontsize=FS["axis"])
    ax.set_ylabel("Relative BookSim batch time", fontsize=FS["axis"])
    ax.set_title("(b) BookSim: layout selection", fontsize=FS["title"])
    ax.text(0.98, 0.04, f"Spearman ρ = {rho:.3f}, n = {len(names)}", transform=ax.transAxes,
            fontsize=FS["note"], va="bottom", ha="right", color=INK)
    ax.legend(handles=[Line2D([], [], marker=m, color=_F3["fam"][f], ls="none",
                              ms={"*": 8, "^": 6.5, "s": 5.5, "o": 5.5}[m], mec="white", mew=0.5)
                       for f, m in (("stacked", "s"), ("heuristic", "^"),
                                    ("random", "o"), ("search", "*"))],
              labels=["stacked fills", "heuristics", "random fills", "search endpoints"],
              fontsize=FS["small"], loc="lower right", bbox_to_anchor=(1.0, 0.11), frameon=False)
    tidy(ax)
    # the region that matters for selection: the reference and the endpoints
    zx, zy = (0.66, 1.22), (0.62, 1.24)
    ins = ax.inset_axes([0.12, 0.52, 0.40, 0.45])
    scatter(ins, 1.1)
    ins.plot(zx, zx, color="0.6", lw=0.7, ls=(0, (4, 3)), zorder=2)
    ins.set_xlim(*zx); ins.set_ylim(*zy)
    ins.set_xticks([0.7, 1.0]); ins.set_yticks([0.7, 1.0])
    ins.tick_params(labelsize=FS["small"], length=2, pad=1.5)
    ins.grid(alpha=0.16, lw=0.5); ins.set_axisbelow(True)
    for s in ins.spines.values():
        s.set_linewidth(0.6); s.set_color("0.45")
    gx = max(pts[n][0] for n in ends); gy = np.mean([pts[n][1] for n in ends])
    ins.annotate(f"Search endpoints\n{min(gains):.0f}–{max(gains):.0f}% lower\nbatch time",
                 (gx + 0.015, gy), xytext=(0.87, 0.645), textcoords="data",
                 fontsize=FS["small"], color=INK, ha="left", va="bottom", linespacing=1.15,
                 arrowprops=dict(arrowstyle="-", color=_F3["fam"]["search"], lw=0.6, shrinkA=0,
                                 shrinkB=1, relpos=(0.0, 0.5)))
    ax.indicate_inset_zoom(ins, edgecolor="0.45", lw=0.6, alpha=0.9)
    return fan, ref, rho, names


def _same_box(axes, gap=0.50, bias=0.25):
    """After tight_layout, let the two panels fill the row: the left panel
    keeps its left edge, the right panel its right edge, `gap` inches
    between them (room for the right panel's y label), one height. The
    right panel is `bias` inches wider: its content sits in a cluster, the
    left panel's runs corner to corner, so equal boxes read as unequal."""
    fig = axes[0].figure
    W = fig.get_size_inches()[0]
    pa, pb = axes[0].get_position(), axes[1].get_position()
    h = min(pa.height, pb.height)
    avail = (pb.x1 - pa.x0) * W - gap
    wa, wb = (avail / 2 - bias) / W, (avail / 2 + bias) / W
    axes[0].set_position([pa.x0, pa.y0, wa, h])
    axes[1].set_position([pb.x1 - wb, pb.y0, wb, h])


def fig3():
    SRC = ["analysis/simba_t1.json", "analysis/b_fanout_24x24_rerank.json"]
    fig, axes = plt.subplots(1, 2, figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.42))
    t1, dist = _fig3a(axes[0])
    fan, ref, rho, names = _fig3b(axes[1])
    fig.tight_layout(); _same_box(axes)
    save(fig, "fig3_external_validation", composite=True, sources=SRC)
    for tag, fn in (("fig3a_simba_placement", _fig3a), ("fig3b_booksim_ranking", _fig3b)):
        f, a = plt.subplots(figsize=(COL_WIDTH * 1.2, COL_WIDTH * 1.0))
        fn(a); f.tight_layout(); save(f, tag, sources=SRC)
    r = fan["rows"]
    dump_csv("fig3_simba_t1", [
        {"longest_pair_hops": d, "measured_norm": x["measured_norm"],
         "bound_norm": x["ratio_max_end"], "round_serialized_norm": x["ratio_pess"]}
        for d, x in zip(dist, t1["rows"])],
        ["longest_pair_hops", "measured_norm", "bound_norm", "round_serialized_norm"], sources=SRC[:1])
    dump_csv("fig3_booksim_candidates", [
        {"candidate": n, "analytic_words": r[n]["ours_words"], "booksim_cycles": r[n]["booksim_cycles"],
         "analytic_rel": r[n]["ours_words"] / r[ref]["ours_words"],
         "booksim_rel": r[n]["booksim_cycles"] / r[ref]["booksim_cycles"],
         "packets_in_this_candidate_batch": r[n]["packets"], "binding": r[n]["busiest_is"]}
        for n in names],
        ["candidate", "analytic_words", "booksim_cycles", "analytic_rel", "booksim_rel",
         "packets_in_this_candidate_batch", "binding"], sources=SRC[1:])
    dump_json("fig3_booksim_rho", {
        "n_candidates": len(names), "candidates": names,
        "spearman_rho_average_ranks": rho,
        "recorded_rho_in_source": fan["summary"]["spearman"],
        "note": "the recorded 0.962 assigned ordinal ranks to the two tied analytic values; "
                "with average ranks (the standard Spearman with ties) the same 13 "
                "candidates give this value, and it is what the figure prints",
        "reference": ref, "packets_per_candidate_batch": r[ref]["packets"],
        "search_endpoint_gain_booksim_pct": {k: v["gain_booksim_vs_booksim_best_random_pct"]
                                            for k, v in fan["summary"]["endpoints"].items()}},
        sources=SRC[1:])
    ends = fan["summary"]["endpoints"]
    g = [v["gain_booksim_vs_booksim_best_random_pct"] for v in ends.values()]
    ea = [r[n]["ours_words"] for n in ends]; eb = [r[n]["booksim_cycles"] for n in ends]
    ends_spread_a = 100 * (max(ea) / min(ea) - 1); ends_spread_b = 100 * (max(eb) / min(eb) - 1)
    CAPTIONS["fig3"] = (
        "Fig. 3. External checks of the cost model. (a) SIMBA: placement sensitivity. "
        "The published Simba measurements (Shao et al., Fig. 9: one convolution layer, "
        "res4a_branch1, on four chiplets with a fixed tiling) for five seatings that spread the "
        "four chiplets from an adjacent block to the corners of a 6x6 region (insets), against "
        "two Isobar readings for the same seatings: the service bound, the busiest-link load of "
        "the communication-cost stage in Fig. 2(a), and the execution estimate, the aggregation "
        "stage's reading once the packet round trips of the Simba NoP protocol are added. Every "
        "series is normalized to its own adjacent seating, so the panel checks the relative "
        "change with distance, not absolute latency. The bound is flat because the busiest link "
        "carries the same load in every seating; the execution estimate follows the measured "
        f"ladder from below ({t1['rows'][-1]['ratio_pess']:.2f}x against {t1['rows'][-1]['measured_norm']:.2f}x "
        "at the farthest seating). (b) BookSim: layout selection. "
        f"{len(names)} candidate placements of a synthetic fan-out batch on a 24x24 die mesh "
        "(17 dies per stage, ports at the link rate), scored by the analytical communication "
        "cost and by the BookSim packet simulator, both relative to the same random fill. The "
        "inset enlarges the region around that reference: the four search endpoints are "
        f"{min(g):.0f} to {max(g):.0f}% below it under BookSim (27 to 29% analytically), so the "
        "improvement the model selects is confirmed by the independent simulator. Among the "
        f"endpoints the analytical scores lie within {ends_spread_a:.0f}% of each other while the BookSim "
        f"times spread over {ends_spread_b:.0f}%: the model finds better layouts, and ranks the best "
        "ones among themselves only coarsely. The rank "
        f"correlation (Spearman rho = {rho:.3f}) is supporting evidence and the dashed y = x a "
        "guide; these are network-batch times, not whole-model gains.")


# =====================================================================
# Fig. 4  system gain and dynamic energy
# =====================================================================
BAR_ORDER = ["default_A4", "snake", "clustered", "heaviest_first", "nmap_greedy",
             "least_manhattan", "random_s3", "sa_random_s1"]


# Fig. 4 colours: the author's card. Families as in Fig. 3 (blue / yellow /
# green, random fills grey); text in the same hues darkened for legibility.
# card swatches as they are: blue (104,180,206) in every panel, yellow
# (243,222,103) for the FFN die, green (152,181,120) for the search; the
# heuristics in the card's deep blue (70,96,173) desaturated to (88,104,160)
F4 = dict(fam={"stacked": "#68b4ce", "heuristic": "#5868a0", "random": GREY, "search": "#98b578"},
          txt={"stacked": "#3f7f93", "heuristic": "#3f4c7a", "random": "#7a7a7a", "search": "#6f8f52"},
          comm="#68b4ce", noncomm="#dfe4e8",                 # the shared grey of (c)
          attn="#68b4ce", ffn="#f3de67", other="#dfe4e8")

BAR_NAME = {"random_s3": "Best random (of 5)", "sa_random_s1": "Search (representative)"}


def _fig4a(ax, with_points=True):
    mc = load("main_config_results.json")["rows"]
    mt = {n: r["prefill"]["0.4"] for n, r in mc.items()}
    ys = np.arange(len(BAR_ORDER))[::-1]
    T = {n: mt[n]["T_s"] * 1e3 for n in mc}
    for y, n in zip(ys, BAR_ORDER):
        r = mt[n]
        R = (r["layers_s"] + r["propagation_s"]) * 1e3
        H = r["H_s"] * 1e3
        ax.barh(y, R, color=F4["noncomm"], ec="none", height=0.62, zorder=3)
        ax.barh(y, H, left=R, color=F4["comm"], ec="none", height=0.62, zorder=3)
        ax.text(R + H + 45, y, f"{R + H:.0f}", va="center", ha="left", fontsize=FS["note"],
                color=F4["txt"][family(n)], zorder=4)
    ax.set_yticks(ys)
    ax.set_yticklabels([BAR_NAME.get(n, label(n)) for n in BAR_ORDER], fontsize=FS["tick"])
    for tick, n in zip(ax.get_yticklabels(), BAR_ORDER):
        tick.set_color(F4["txt"][family(n)])
    ax.set_xlabel("Whole-model prefill latency (ms)", fontsize=FS["axis"])
    ax.set_xlim(0, 5000)
    ysr = ys[-1]
    yb = ysr - 0.95
    ax.annotate("", xy=(T["sa_random_s1"], yb), xytext=(T["default_A4"], yb),
                arrowprops=dict(arrowstyle="<|-|>", color=F4["txt"]["stacked"], lw=0.9, mutation_scale=7))
    ax.text((T["sa_random_s1"] + T["default_A4"]) / 2, yb + 0.14,
            f"{100 * (1 - T['sa_random_s1'] / T['default_A4']):.1f}% below the default fill",
            fontsize=FS["note"], color=F4["txt"]["stacked"], ha="center", va="bottom")
    ax.set_ylim(yb - 0.45, max(ys) + 0.6)
    ax.legend(handles=[Rectangle((0, 0), 1, 1, fc=F4["noncomm"], ec="none"),
                       Rectangle((0, 0), 1, 1, fc=F4["comm"], ec="none")],
              labels=["Non-communication", "Package communication"], fontsize=FS["note"],
              loc="upper right", bbox_to_anchor=(1.0, 0.79), frameon=False)
    ax.set_title("(a) Whole-model latency of the evaluated placements", fontsize=FS["title"])
    tidy(ax, grid="x")
    if with_points:
        # every sample on one short axis: the five random fills and the nine
        # search endpoints; the representative and the best random marked
        rnd = sorted(T[n] for n in mc if n.startswith("random"))
        sea = sorted(T[n] for n in mc if n.startswith("sa_"))
        ins = ax.inset_axes([0.585, 0.31, 0.40, 0.28])
        ins.plot(rnd, [1] * len(rnd), marker="o", ms=4.5, color=GREY, mec="white", mew=0.4,
                 ls="none", zorder=5)
        ins.plot([T["random_s3"]], [1], marker="o", ms=5.5, color=GREY, mec=INK, mew=0.7,
                 ls="none", zorder=6)
        ins.plot(sea, [0] * len(sea), marker="*", ms=7, color=F4["fam"]["search"], mec="white", mew=0.4,
                 ls="none", zorder=5)
        ins.plot([T["sa_random_s1"]], [0], marker="*", ms=9.5, color=F4["fam"]["search"], mec=INK, mew=0.7,
                 ls="none", zorder=6)
        ins.annotate("", xy=(T["sa_random_s1"], 0.5), xytext=(T["random_s3"], 0.5),
                     arrowprops=dict(arrowstyle="<|-|>", color=F4["txt"]["search"], lw=0.8, mutation_scale=6))
        ins.text((T["sa_random_s1"] + T["random_s3"]) / 2, 0.58,
                 f"{100 * (1 - T['sa_random_s1'] / T['random_s3']):.2f}%", ha="center",
                 va="bottom", fontsize=FS["small"], color=F4["txt"]["search"])
        ins.set_xlim(1880, 2180); ins.set_ylim(-0.55, 1.55)
        ins.set_yticks([])
        ins.text(1888, 1, "5 random fills", fontsize=FS["small"], color=F4["txt"]["random"], ha="left",
                 va="center")
        ins.text(2172, 0, "9 search endpoints", fontsize=FS["small"], color=F4["txt"]["search"], ha="right",
                 va="center")
        ins.set_xticks([1900, 2000, 2100])
        ins.tick_params(labelsize=FS["small"], length=2, pad=1.5)
        ins.set_xlabel("ms", fontsize=FS["small"], labelpad=1)
        ins.grid(axis="x", alpha=0.16, lw=0.5); ins.set_axisbelow(True)
        for s in ("top", "right"):
            ins.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ins.spines[s].set_linewidth(0.6)
    return mt, T


def _fig4b(ax):
    en = load("energy_export.json")["rows"]
    ref = "random_s3"
    Tr, Er = en[ref]["T_s"], en[ref]["E_total_J"]
    seen = set()
    for n, e in en.items():
        if n == "sequential":
            continue
        fam = family(n)
        big = n in ("random_s3", "sa_random_s1")
        ax.plot([e["T_s"] * 1e3], [e["E_total_J"]], marker=marker(n),
                ms=(11 if fam == "search" else 7) if big else {"search": 7, "heuristic": 6}.get(fam, 4.5),
                color=F4["fam"][fam], mec=INK if big else "white", mew=0.8 if big else 0.4,
                ls="none", zorder=6 if big else 5, label=None if fam in seen else FAM_LABEL[fam])
        seen.add(fam)
    dT = lambda n: 100 * (en[n]["T_s"] / Tr - 1)
    dE = lambda n: 100 * (en[n]["E_total_J"] / Er - 1)
    notes = (("default_A4", "Default (stacked fill)", (-10, 2), "right", "center"),
             ("snake", "Snake", (-8, 4), "right", "bottom"),
             ("heaviest_first", "Heaviest first", (8, 0), "left", "center"),
             ("least_manhattan", f"Least Manhattan\n{dE('least_manhattan'):+.1f}% energy, "
                                 f"{dT('least_manhattan'):+.1f}% latency", (-22, 20), "left", "bottom"),
             ("clustered", "Clustered", (10, 0), "left", "center"),
             ("random_s3", "Best random", (12, -4), "left", "top"),
             ("sa_random_s1", f"Search (representative)\n{dT('sa_random_s1'):+.2f}% latency, "
                              f"{dE('sa_random_s1'):+.2f}% energy", (-8, -16), "left", "top"))
    for n, lab, off, ha, va in notes:
        lead = (dict(arrowstyle="-", color=F4["txt"]["heuristic"], lw=0.6, shrinkA=0, shrinkB=3,
                     relpos=(0.25, 0.0)) if n == "least_manhattan" else None)
        ax.annotate(lab, (en[n]["T_s"] * 1e3, en[n]["E_total_J"]), textcoords="offset points",
                    xytext=off, fontsize=FS["small"], ha=ha, va=va, color=F4["txt"][family(n)],
                    linespacing=1.2, arrowprops=lead)
    ax.text(0.02, 0.975, "changes relative to best random", transform=ax.transAxes,
            fontsize=FS["small"], color="0.4", style="italic", ha="left", va="top")
    ax.set_xlim(1750, 4550); ax.set_ylim(2.315, 2.57)
    ax.set_xlabel("Whole-model prefill latency (ms)", fontsize=FS["axis"])
    ax.set_ylabel("System dynamic energy (J)", fontsize=FS["axis"])
    ax.set_title("(b) Latency and dynamic energy", fontsize=FS["title"])
    ax.legend(fontsize=FS["small"], loc="upper right", frameon=False)
    tidy(ax)
    return en, ref


def _fig4c(ax):
    it = load("intra_die_integration.json")
    a = it["per_anchor"]["0.4"]
    ship = a["T_layer_shipped_incl_pkg_s"] * 1e3
    best = a["T_layer_best_incl_pkg_s"] * 1e3
    rest = (a["fixed_rest_s"] + a["package_handoffs_per_layer_s_at_0.4"]) * 1e3
    b1 = [a["dies"]["attn"]["shipped_s"] * 1e3, a["dies"]["attn"]["best_s"] * 1e3]
    b2 = [a["dies"]["ffn"]["shipped_s"] * 1e3, a["dies"]["ffn"]["best_s"] * 1e3]
    xs = [0, 1]
    ax.bar(xs, b1, width=0.55, color=F4["attn"], ec="none", label="Attention die", zorder=3)
    ax.bar(xs, b2, bottom=b1, width=0.55, color=F4["ffn"], ec="none", label="FFN die", zorder=3)
    ax.bar(xs, [rest, rest], bottom=np.add(b1, b2), width=0.55, color=F4["other"], ec="none",
           label="Other costs incl. package transfers", zorder=3)
    for x, tot in zip(xs, (ship, best)):
        ax.text(x, tot + 0.8, f"{tot:.2f} ms", ha="center", va="bottom", fontsize=FS["note"], color=INK)
    ya = ship + 9.0
    ax.annotate("", xy=(1, ya), xytext=(0, ya),
                arrowprops=dict(arrowstyle="-|>", color="0.35", lw=0.9, mutation_scale=7))
    ax.text(0.5, ya + 0.8, f"−{100 * (1 - best / ship):.2f}%", ha="center", va="bottom",
            fontsize=FS["note"], color=INK, fontweight="bold")
    ax.set_xticks(xs); ax.set_xticklabels(["Contiguous", "Optimal"], fontsize=FS["tick"])
    ax.set_xlim(-0.55, 1.55)
    ax.set_ylabel("Layer latency (ms)", fontsize=FS["axis"])
    ax.set_ylim(0, 65); ax.set_yticks([0, 20, 40, 60])
    ax.set_title("(c) Whole-layer impact of\nintra-die assignment", fontsize=FS["title"], pad=32)
    ax.legend(fontsize=FS["small"], loc="lower left", bbox_to_anchor=(-0.04, 1.0), frameon=False,
              labelspacing=0.25, handlelength=1.2, borderaxespad=0.2)
    tidy(ax, grid="y")
    return it, ship, best, rest


def fig4():
    SRC = ["analysis/main_config_results.json", "analysis/energy_export.json",
           "analysis/intra_die_integration.json"]
    fig = plt.figure(figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.74))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.0, 0.95], width_ratios=[1.9, 1.75, 1.4],
                          hspace=0.45, wspace=0.42)
    mt, T = _fig4a(fig.add_subplot(gs[0, :]))
    en, ref = _fig4b(fig.add_subplot(gs[1, :2]))
    gc = gs[1, 2].subgridspec(2, 1, height_ratios=[0.22, 0.78], hspace=0)   # room for the legend
    it, ship, best, rest = _fig4c(fig.add_subplot(gc[1, 0]))
    save(fig, "fig4_deployment_gain", composite=True, sources=SRC)
    for tag, fn, size in (("fig4a_latency_breakdown", _fig4a, (PAGE_WIDTH * 0.66, 2.6)),
                          ("fig4b_latency_energy", _fig4b, (COL_WIDTH * 1.35, COL_WIDTH * 1.05)),
                          ("fig4c_intra_die_layer", _fig4c, (COL_WIDTH * 0.95, COL_WIDTH * 1.05))):
        f, a = plt.subplots(figsize=size); fn(a); f.tight_layout(); save(f, tag, sources=SRC)
    dump_csv("fig4_layouts", [
        {"layout_id": n, "name": label(n), "family": family(n),
         "T_prefill_ms": mt[n]["T_s"] * 1e3, "R_ms": (mt[n]["layers_s"] + mt[n]["propagation_s"]) * 1e3,
         "H_ms": mt[n]["H_s"] * 1e3, "E_dynamic_J": en[n]["E_total_J"],
         "dT_vs_random_s3_pct": 100 * (en[n]["T_s"] / en[ref]["T_s"] - 1),
         "dE_vs_random_s3_pct": 100 * (en[n]["E_total_J"] / en[ref]["E_total_J"] - 1)}
        for n in en if n != "sequential"],
        ["layout_id", "name", "family", "T_prefill_ms", "R_ms", "H_ms", "E_dynamic_J",
         "dT_vs_random_s3_pct", "dE_vs_random_s3_pct"], sources=SRC)
    st = load("main_config_results.json")["stats"]["prefill"]
    lm_vs_search = 100 * (en["least_manhattan"]["T_s"] / en["sa_random_s1"]["T_s"] - 1)
    search_vs_default_E = 100 * (en["sa_random_s1"]["E_total_J"] / en["default_A4"]["E_total_J"] - 1)
    s4 = st["0.4"]
    CAPTIONS["fig4"] = (
        "Fig. 4. What the deployment choice is worth, and what it costs. Main configuration: "
        "2.7B class, 512-token serial prefill, 544 of 576 dies on a 24x24 mesh, XY routing, "
        "0.4 GB/s per link direction, ports at twice the link rate. (a) Whole-model latency "
        "of the evaluated placements, split into the non-communication cost (compute, weight "
        "write, digital unit) and the package hand-offs. Main instance of (a) and (b): the 2.7B "
        "class on 544 dies. Best random is the strongest of the five random fills (seeds 0 to "
        "4). Search (representative) is one layout: per seed the best of three starts, then "
        "the median of the three seeds. The inset instead shows all nine endpoints (three "
        "starts x three seeds) and all five random fills on one axis: every endpoint is below "
        f"every random fill; the representative is {s4['G_headline_pct']:.2f}% below the best "
        f"random fill ({T['random_s3']:.2f} ms; {s4['G_min_pct']:.2f} to {s4['G_max_pct']:.2f}% "
        f"over the three seeds) and {s4['G_vs_default_pct']:.1f}% below the default stacked "
        f"fill ({T['default_A4']:.2f} ms). (b) The same layouts in latency and system dynamic "
        "energy (no static term); the percentages are changes relative to the best random "
        "fill. The search lowers latency by 9.91% and dynamic energy by 0.26%; Least Manhattan "
        "saves 7.3% of dynamic energy at +1.8% latency against the same reference, which is "
        f"{lm_vs_search:.1f}% slower than the representative search layout (NMAP greedy and "
        "Clustered save about as much energy at +4.0% and +20.4% latency). Against the default "
        f"fill the search's dynamic energy is {search_vs_default_E:+.1f}%, so the 54.5% of (a) "
        "and the -0.26% here are not the same comparison. (c) A separate two-die layer "
        "instance, the one Fig. 1(a) refers to, not the 544-die system of (a) and (b): one "
        "GPT-2-medium class layer over an attention die and an FFN die, each a 2x4 macro "
        "mesh, at 0.4 GB/s. Optimal is the best of a full enumeration of the 280 and 70 macro "
        "assignments, against the contiguous assignment, with the fixed rest "
        f"of the layer ({rest:.2f} ms incl. two package transfers) included, so the 9.02% is "
        "the whole-layer gain. Energy is not modelled at this level.")


# =====================================================================
# Fig. 6  conditions
# =====================================================================
# Fig. 6 colours: two hues from the card, green and light blue (darker tones
# of the same hues for text), r in neutral grey; the envelope in the card's
# yellow. One line width and one marker size in every panel, as in Fig. 3.
F6 = dict(green="#98b578", green_txt="#6f8f52", blue="#68b4ce", blue_txt="#3f7f93",
          deep="#5868a0", env="#f3de67", env_txt="#8a7a2a", bar="#99a3aa")
LEG6 = 5.5                                           # legend type size in every panel
LW6, MS6 = 1.4, 4.5
# a square or a diamond at the circle's nominal size reads larger (more area,
# wider extent), so they are drawn a little smaller to balance
MS6_S, MS6_D = 3.5, 3.7
MS6_BC, MS6_BC_S = 4.0, 3.5                          # dots in (b) and (c): circle, square
TITLE6 = dict(fontsize=8, loc="left", pad=6.5)       # one title style for (a), (b), (c)


def _fig6a(ax):
    """(a) Bandwidth response of the fixed pair: r, eta and G as three
    lines on one percent axis, G's value at three points; the crossover
    envelope of Fig. 1(b) shaded with B- and B+ at its edges."""
    sl = load("bw_slice_k2.json")
    pts = sorted(sl["points"].values(), key=lambda p: p["B_gbps"])
    B = [p["B_gbps"] for p in pts]
    G, eta, r = ([100 * p[k] for p in pts] for k in ("G", "eta", "r"))
    Bm, Bp = sl["B_minus_gbps"], sl["B_plus_gbps"]
    ax.axvspan(Bm, Bp, color=F6["env"], alpha=0.30, lw=0, zorder=1)
    # at the top of the band: B- and B+ in its corners, the name under them
    for x, s_, ha in ((Bm, "$B_-$", "left"), (Bp, "$B_+$", "right")):
        ax.text(x * (1.03 if ha == "left" else 1 / 1.03), 78.5, s_, fontsize=FS["small"], ha=ha,
                va="top", color=F6["env_txt"], zorder=2)
    ax.text(np.sqrt(Bm * Bp), 72, "Crossover\nenvelope", fontsize=6.0, ha="center",
            va="top", color=F6["env_txt"], linespacing=1.1, zorder=2)
    ax.plot(B, r, ls=(0, (4, 2)), lw=1.15, color=F6["deep"], marker="s", ms=MS6_S, zorder=3,
            label="r: Communication share")
    ax.plot(B, eta, ls=(0, (1.2, 1.6)), lw=LW6, color=F6["blue"], marker="D", ms=MS6_D, zorder=4,
            label="η: Communication reduction")
    ax.plot(B, G, lw=LW6, color=F6["green"], marker="o", ms=MS6, zorder=5,
            label="G: Whole-model latency reduction")
    for p in pts:                                    # G's value at three points, beside its dot
        b, g = p["B_gbps"], 100 * p["G"]
        if abs(b - 0.4) < 1e-6:                      # under its dot: the curve falls away there
            off, ha, va = (0, -4.5), "center", "top"
        elif 0.85 < b < 0.9:
            off, ha, va = (0, 4), "center", "bottom"
        elif b > 10:
            off, ha, va = (5, -1), "left", "bottom"
        else:
            continue
        ax.annotate(f"{g:.2f}%", (b, g), textcoords="offset points", xytext=off, ha=ha,
                    va=va, fontsize=FS["note"], color=F6["green_txt"])
    ax.set_xscale("log")
    ax.set_xlim(0.165, 32)                           # room right of 12.5 GB/s for its label
    ax.set_xticks([0.2, 0.4, 0.87, 2, 12.5])
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_xlabel("Link bandwidth per direction (GB/s)", fontsize=FS["axis"])
    ax.set_ylabel("Percent", fontsize=FS["axis"])
    ax.set_ylim(0, 80); ax.set_yticks([0, 20, 40, 60, 80])
    ax.set_title("(a) Bandwidth response of fixed placements", **TITLE6)
    # top right corner, small enough to clear the envelope and its labels
    ax.legend(fontsize=4.5, loc="upper right", frameon=False, handlelength=1.5,
              handletextpad=0.5, labelspacing=0.3, borderaxespad=0.2, borderpad=0.2,
              markerscale=0.7, title="G = \u03b7 \u00b7 r", title_fontsize=4.5,
              alignment="left")
    tidy(ax)
    return sl, pts


def _load_reuse():
    import csv
    rows = list(csv.DictReader(open(os.path.join(A, "workload_reuse", "summary.csv"))))
    for r in rows:
        for k, v in list(r.items()):
            try:
                r[k] = float(v)
            except (TypeError, ValueError):
                pass
        r["S"] = int(r["S"])
    return rows


def _port_stat(bw="0.4"):
    sw = load("kappa_geometry_sweep.json")
    stat = {}
    for cell_name, cell in sw["cells"].items():
        grid, k = cell_name.split("/")
        per_seed = {}
        for rn in cell["runs"]:
            per_seed.setdefault(rn.rsplit("_s", 1)[1], []).append(cell["rows"][rn]["T_s"][bw])
        bos = [min(v) for v in per_seed.values()]
        base = min(v["T_s"][bw] for n, v in cell["rows"].items() if not n.startswith("sa_"))
        gains = sorted(100 * (1 - t / base) for t in bos)
        binding = sorted({cell["rows"][rn]["binding"] for rn in cell["runs"]})
        stat[(grid, float(k[1:]))] = {"median": gains[len(gains) // 2], "lo": gains[0],
                                      "hi": gains[-1], "baseline_ms": base * 1e3,
                                      "endpoint_binding": binding}
    return stat


def _fig6b(ax, show_x=False):
    """(b) Paired dots: one row per port capacity, the two geometries
    offset a little, each at its median over three seeds."""
    stat = _port_stat()
    ks = [1.0, 2.0, 4.0]
    ys = [2, 1, 0]
    for grid, col, ct, mk, ms, dy, lab in (
            ("24x24", F6["green"], F6["green_txt"], "o", MS6_BC, 0.2, "24 × 24"),
            ("12x48", F6["blue"], F6["blue_txt"], "s", MS6_BC_S, -0.2, "12 × 48")):
        med = [stat[(grid, k)]["median"] for k in ks]
        ax.plot(med, [y + dy for y in ys], marker=mk, ms=ms, color=col, ls="none", zorder=4,
                label=lab)
        for m, y in zip(med, ys):
            ax.annotate(f"{m:.1f}", (m, y + dy), textcoords="offset points", xytext=(4.5, 0),
                        ha="left", va="center", fontsize=FS["note"], color=ct)
    ax.set_yticks(ys); ax.set_yticklabels([f"κ = {k:g}" for k in ks], fontsize=FS["tick"])
    ax.set_ylim(-0.5, 3.0); ax.set_xlim(0, 12.4); ax.set_xticks([0, 4, 8, 12])
    ax.set_title("(b) Ports and geometry", **TITLE6)
    ax.legend(fontsize=LEG6, loc="upper right", bbox_to_anchor=(1.0, 1.06), frameon=False,
              ncol=2, handlelength=1.0, handletextpad=0.3, columnspacing=0.8, borderaxespad=0,
              borderpad=0.2, markerscale=0.8)
    tidy(ax, grid="x")
    if not show_x:
        plt.setp(ax.get_xticklabels(), visible=False); ax.tick_params(axis="x", length=0)
    else:
        ax.set_xlabel("Latency reduction (%)", fontsize=FS["axis"])
    return stat


def _fig6c(ax):
    """(c) Dumbbells: one row per length, decode and prefill as two equal
    dots joined by a grey line, each value above its dot."""
    rows = _load_reuse()
    rp = {(r["phase"], r["S"]): r for r in rows}
    S = [128, 512, 1024]
    ys = [2, 1, 0]
    for s, y in zip(S, ys):
        d, pf = rp[("decode", s)]["reuse_gain_pct"], rp[("prefill", s)]["reuse_gain_pct"]
        ax.plot([d, pf], [y, y], color=F6["bar"], lw=0.8, solid_capstyle="butt", zorder=2)
        for v, c, ct, lab in ((d, F6["blue"], F6["blue_txt"], "Decode"),
                              (pf, F6["green"], F6["green_txt"], "Prefill")):
            ax.plot([v], [y], marker="o", ms=MS6_BC, color=c, ls="none", zorder=4,
                    label=lab if y == ys[0] else None)
            ax.annotate(f"{v:.2f}", (v, y), textcoords="offset points", xytext=(0, 3.5),
                        ha="center", va="bottom", fontsize=FS["note"], color=ct)
    ax.set_yticks(ys); ax.set_yticklabels([str(s) for s in S], fontsize=FS["tick"])
    ax.set_ylim(-0.5, 3.0); ax.set_xlim(0, 12.4); ax.set_xticks([0, 4, 8, 12])
    ax.set_xlabel("Latency reduction (%)", fontsize=FS["axis"])
    ax.set_title("(c) Workload reuse", **TITLE6)
    leg = ax.legend(fontsize=LEG6, loc="upper right", bbox_to_anchor=(1.0, 1.06), frameon=False,
                    ncol=2, handlelength=1.0, handletextpad=0.3, columnspacing=0.8,
                    borderaxespad=0, borderpad=0.2, markerscale=0.8)
    ax.annotate("Tokens", xy=(0, 1.0), xycoords="axes fraction", xytext=(-3.5, 0),
                textcoords="offset points", ha="right", va="center", fontsize=LEG6,
                color="0.45")
    tidy(ax, grid="x")
    return rows


def fig6():
    SRC = ["analysis/bw_slice_k2.json", "analysis/kappa_geometry_sweep.json",
           "analysis/workload_reuse/summary.csv", "analysis/workload_reuse/workload_reuse.json"]
    # inch layout: (a) left; (b) over (c) right; (a) and (b) share the top
    # edge, so their titles share one baseline; (a) and (c) share the bottom
    W, H = 4.78, 2.62
    R = lambda x0, y0, w, h: [x0 / W, y0 / H, w / W, h / H]
    bot, top = 0.36, 2.38
    xa, wa, xr, wr = 0.42, 2.52, 3.40, 1.25
    hb = (top - bot - 0.30) / 2                     # 0.30 in holds (c)'s title
    fig = plt.figure(figsize=(W, H))
    axa = fig.add_axes(R(xa, bot, wa, top - bot)); sl, pts = _fig6a(axa)
    axb = fig.add_axes(R(xr, top - hb, wr, hb)); stat = _fig6b(axb)
    axc = fig.add_axes(R(xr, bot, wr, hb)); rows = _fig6c(axc)
    save(fig, "fig6_conditions", composite=True, sources=SRC)
    f, a = plt.subplots(figsize=(COL_WIDTH * 1.25, COL_WIDTH * 0.95)); _fig6a(a); f.tight_layout()
    save(f, "fig6a_bandwidth_response", sources=SRC[:1])
    for tag, fn, kw, src in (("fig6b_port_geometry", _fig6b, {"show_x": True}, SRC[1:2]),
                             ("fig6c_placement_reuse", _fig6c, {}, SRC[2:])):
        fw, fh = 0.5 + wr + 0.1, 0.4 + hb + 0.3    # the same axes size as in the composite
        f = plt.figure(figsize=(fw, fh))
        fn(f.add_axes([0.5 / fw, 0.4 / fh, wr / fw, hb / fh]), **kw)
        save(f, tag, sources=src)
    dump_csv("fig6_placement_reuse", rows, list(rows[0].keys()), sources=SRC[2:])
    dump_csv("fig6_bandwidth_response", [
        {"point": k, "B_gbps": p["B_gbps"], "region": p["region"], "T_reference_ms": p["T_s_ref"] * 1e3,
         "T_selected_ms": p["T_s_sel"] * 1e3, "G_ratio": p["G"], "eta_ratio": p["eta"], "r_ratio": p["r"],
         "G_pct": 100 * p["G"], "eta_pct": 100 * p["eta"], "r_pct": 100 * p["r"]}
        for k, p in sl["points"].items()],
        ["point", "B_gbps", "region", "T_reference_ms", "T_selected_ms", "G_ratio", "eta_ratio",
         "r_ratio", "G_pct", "eta_pct", "r_pct"], sources=SRC[:1])
    dump_csv("fig6_port_geometry", [
        {"grid": g, "kappa": k, "gain_median_pct": v["median"], "gain_min_pct": v["lo"],
         "gain_max_pct": v["hi"], "strongest_baseline_ms": v["baseline_ms"],
         "endpoint_binding": "/".join(v["endpoint_binding"]),
         "statistic": "per seed the best of 3 starts, then median and min-max over 3 seeds; "
                      "denominator = the cell's strongest evaluated baseline"}
        for (g, k), v in sorted(stat.items())],
        ["grid", "kappa", "gain_median_pct", "gain_min_pct", "gain_max_pct", "strongest_baseline_ms",
         "endpoint_binding", "statistic"], sources=SRC[1:])
    rp = {(r["phase"], r["S"]): r for r in rows}
    CAPTIONS["fig6"] = (
        "Fig. 6. The conditions that set the value of placement. (a) One fixed pair of "
        "layouts, the best random fill (reference) and the representative search layout of "
        "Fig. 4, re-scored at each bandwidth without a new search: the whole-model latency "
        "reduction G, the pair's communication reduction \u03b7 (level, since the hand-off "
        "volumes do not change) and the reference's communication share r, "
        "with G = \u03b7 r. The shaded crossover envelope [B-, B+] = "
        f"[{sl['B_minus_gbps']:.3f}, {sl['B_plus_gbps']:.3f}] GB/s is Fig. 1(b)'s "
        "placement-decides band for the seven named rules at the NeuRRAM row rate, not a "
        "boundary of this pair; 0.87 GB/s is its geometric midpoint. (b) and (c) share one "
        "axis of latency reduction, each condition against its own strongest evaluated "
        "baseline. (b) A new search per cell at 0.4 GB/s over two package geometries and three "
        "port capacities: per seed the best of three starts, then the median over three seeds; "
        f"the three seeds lie within {max(v['hi'] - v['lo'] for v in stat.values()):.1f} points of "
        "each other in every cell (data/fig6_port_geometry.csv). (c) Placement reuse across workloads, main "
        "configuration (24x24, 0.4 GB/s, \u03ba = 2): the frozen layout selected at "
        "512-token prefill, re-scored at 128, 512 and 1024 prefill tokens and at decode over "
        "a 128-, 512- and 1024-token cache (2048 is infeasible under the same grouping: the "
        "attention die's K/V arrays would exceed its capacity). Every hand-off's volume "
        "scales with the token count, so the 21 evaluated layouts keep one ranking across "
        "the six workloads and the gain changes by dilution (the communication share moves "
        f"from {rp[('prefill', 128)]['comm_share_ref_pct']:.1f} to "
        f"{rp[('prefill', 1024)]['comm_share_ref_pct']:.1f}% over prefill, and is "
        f"{rp[('decode', 512)]['comm_share_ref_pct']:.1f}% at decode), not by placement "
        "mismatch; an appended search per workload (same annealer, objective normalized by "
        "the baseline latency) found nothing better than the frozen layout at this budget. "
        "The 128- and 1024-token per-operator accounts are derived from the measured "
        "512-token account.")


# =====================================================================
# Fig. 1
# =====================================================================
def fig1():
    """Fig. 1 is the standing phase diagram (the non-print generator, 12.8 x
    5.0 in, scaled to the column by the page layout), rendered with every
    type size one point larger; the two panels are cropped from it."""
    from scripts import fig_phase_isobar as P
    import matplotlib.axes as _ma
    import matplotlib.figure as _mf
    src = ["scripts/fig_phase_isobar.py", "analysis/phase_diagram_isobar_k2.json"]
    P.OUT_PNG = os.path.join(OUT["preview"], "fig1_phase_diagram.png")
    P.OUT_PDF = os.path.join(OUT["composites"], "fig1_phase_diagram.pdf")
    DELTA = 2.0

    def bumped(f):                                  # +1 pt on every explicit fontsize
        def g(*a, **kw):
            if "fontsize" in kw:
                kw["fontsize"] = kw["fontsize"] + DELTA
            return f(*a, **kw)
        return g
    saved = {(_ma.Axes, n): getattr(_ma.Axes, n) for n in ("text", "annotate", "set_title",
                                                             "set_xlabel", "set_ylabel")}
    saved[(_mf.Figure, "legend")] = _mf.Figure.legend
    rc0 = {k: matplotlib.rcParams[k] for k in ("font.size", "axes.labelsize", "axes.titlesize",
                                               "xtick.labelsize", "ytick.labelsize", "legend.fontsize")}
    try:
        for (cls, n), f in saved.items():
            setattr(cls, n, bumped(f))
        base = float(rc0["font.size"])              # the implicit sizes (ticks, axis labels)
        matplotlib.rcParams.update({"font.size": base + DELTA, "axes.labelsize": base + DELTA,
                                    "axes.titlesize": base + DELTA, "xtick.labelsize": base + DELTA,
                                    "ytick.labelsize": base + DELTA, "legend.fontsize": base + DELTA})
        P.main()
    finally:
        for (cls, n), f in saved.items():
            setattr(cls, n, f)
        matplotlib.rcParams.update(rc0)
    fig = plt.gcf()
    for ext, kind in (("pdf", "composites"), ("svg", "composites"), ("png", "preview")):
        fig.savefig(os.path.join(OUT[kind], f"fig1_phase_diagram.{ext}"), bbox_inches="tight",
                    pad_inches=0, dpi=200)                  # cropped like the rest of the set
    PRODUCTS.append({"name": "fig1_phase_diagram", "kind": "composites",
                     "files": ["composites/fig1_phase_diagram.pdf", "composites/fig1_phase_diagram.svg",
                               "preview/fig1_phase_diagram.png"], "sources": src,
                     "note": "analysis/phase_diagram_isobar_k2 (standing form) with every type size one point larger"})
    print("   composites/fig1_phase_diagram.pdf|svg  preview/fig1_phase_diagram.png")
    r = fig.canvas.get_renderer()
    for ax, tag in zip(fig.axes[:2], ("fig1a_intra_die_phase", "fig1b_inter_die_phase")):
        bb = ax.get_tightbbox(r).transformed(fig.dpi_scale_trans.inverted())
        for ext, kind in (("pdf", "panels"), ("svg", "panels"), ("png", "preview")):
            fig.savefig(os.path.join(OUT[kind], f"{tag}.{ext}"), bbox_inches=bb, pad_inches=0,
                        dpi=300)
        PRODUCTS.append({"name": tag, "kind": "panels",
                         "files": [f"panels/{tag}.pdf", f"panels/{tag}.svg", f"preview/{tag}.png"],
                         "sources": src, "note": "cropped from the composite; the legend is on the composite"})
        print(f"   panels/{tag}.pdf|svg  preview/{tag}.png")
    plt.close(fig)
    CAPTIONS["fig1"] = (
        "Fig. 1. The placement phase diagram. Both axes are rates: the device's row-processing "
        "rate and the link bandwidth per direction. (a) Intra-die placement: one die's two "
        "co-resident operators of the GPT-2-medium class layer over all 70 macro seatings, "
        "under the per-operator overlap model, so the regions say whether communication is "
        "exposed or masked; the envelope between the placement extrema is 2.67x. (b) Inter-die "
        "placement: the 2.7B stack on 544 of 576 dies over the seven named seating rules with "
        "ports at twice the link rate, under the serial sum, so the regions say which cost "
        "dominates; the envelope is 2.66x. The dotted contour is a 20% placement latency "
        "spread. Filled diamonds are published parameters projected onto this instance "
        "(HERMES 0.4 GB/s per core-to-core link; ISAAC 4.0 GB/s per inter-tile link and "
        "6.4 GB/s per off-chip link), not measured phase positions of those chips on this "
        "workload; hollow diamonds are derived or alternative-mode values projected the same "
        "way (HERMES's 4-phase MVM; the M1076's published 2 GB/s I/O capability matched to "
        "the model's port capacity, 1.0 GB/s at kappa = 2). The dashed lines are the two "
        "bandwidth tiers evaluated in this paper, and the circles joined by a vertical line "
        "are those two configurations at the NeuRRAM row rate.")


# =====================================================================
# captions, index, manifest, main
# =====================================================================
SECTION = {"fig1": "§2.2 (first pointer in the Introduction)", "fig2": "§3.1",
           "fig3": "§3.3", "fig4": "§4.3", "fig5": "§4.3 end / §4.4",
           "fig6": "§4.5"}


def write_docs(run_id, argv):
    root = OUT["root"]
    L = ["# Formal captions (v2)\n", "Written for the paper; no development notes.\n"]
    for k in ("fig1", "fig2", "fig3", "fig4", "fig5", "fig6"):
        L.append(f"\n## {k}\n\n{CAPTIONS.get(k, '(not generated in this run)')}\n")
    open(os.path.join(root, "captions.md"), "w").write("".join(L))
    idx = [f"# Figure set v2: `{run_id}`\n\n",
           "Generated by `scripts/plot_dac2027_v2.py` into this directory only; v1 and every\n"
           "pre-existing figure are untouched. Each panel exists as PDF, SVG (text kept as\n"
           "text) and PNG preview; the numbers behind it are in `data/`; the formal captions\n"
           "are in `captions.md`. Fonts: axis 8 pt, ticks 7.5 pt, titles 9 pt, notes 6.5 to\n"
           "7 pt at the drawn size (single column 3.4 in, double column 7.16 in).\n\n"
           "| figure | paper section | claim | instance | layout ids | statistic / denominator | sources |\n"
           "|---|---|---|---|---|---|---|\n",
           f"| fig1_phase_diagram | {SECTION['fig1']} | placement is a phase with computable boundaries | (a) GPT-2-medium class ffn die, 70 seatings; (b) 2.7B on 544/576 dies, 7 rules, kappa 2 | rules by name | envelopes max/min over the set; boundaries at the NeuRRAM rate | phase_diagram_isobar_k2.json |\n",
           f"| fig2_platform_workflow | {SECTION['fig2']} | what the platform computes; how one deployment becomes resource costs | (a) schematic; (b) the Fig. 5 instance's compact fill, evaluated live | compact_fill | (b) busiest link flows x words / B; port bound max L_p / (kappa B); word-hops | fig2b_placement_to_costs.json |\n",
           f"| fig3_external_validation | {SECTION['fig3']} | (a) does the cost model explain the measured placement effect; (b) does the independent simulator confirm the layouts it selects | (a) Simba T1, 4 chiplets, 5 seatings; (b) 24x24 fan-out batch, kappa 1, 13 candidates | (b) candidate ids in fig3_booksim_candidates.csv | (a) each series / its adjacent seating; (b) both axes / the reference random fill; rho with average ranks | simba_t1.json, b_fanout_24x24_rerank.json |\n",
           f"| fig4_deployment_gain | {SECTION['fig4']} | what the deployment choice is worth and costs | main configuration; (c) GPT-2-medium class layer | random_s3 (best random), sa_random_s1 (representative), default_A4 | 9.91% = median of 3 seeds of best-over-3-starts vs random_s3 2118.71 ms; 54.5% vs default 4192.54 ms; dE = E/E_ref - 1 | main_config_results.json, energy_export.json, intra_die_integration.json |\n",
           f"| fig5_mechanism_and_ablation | {SECTION['fig5']} | where stacking comes from; what the objective is worth | (a-c) controlled 4x4 die mesh, the ffn1->ffn2 hand-off, 25 flows; (d) main configuration | compact_fill, random_seed3 (best of 0-4), search_seed (median of 0-2) | (a-c) busiest resource in link-time, word-hops; (d) excess over the best resource-aware endpoint 1886.5 ms | fig5_small_mesh_instance.json, objective_ablation_k2.json |\n",
           f"| fig6_conditions | {SECTION['fig6']} | the conditions that set the value of placement | (a) frozen pair re-scored over bandwidth; (b) 6 cells of the kappa x geometry sweep; (c) the frozen layout re-scored at 6 workloads | random_s3 / sa_random_s1; per-cell runs | (a) G, eta, r as percentages, G = eta r; (b) per seed best of 3 starts, median over 3 seeds vs the cell's strongest baseline (seed range in the CSV); (c) reduction vs each workload's strongest evaluated baseline; (b)(c) one 0-12% axis | bw_slice_k2.json, kappa_geometry_sweep.json, workload_reuse/summary.csv |\n",
           "\n## Notes for the author (not for the paper)\n\n",
           "- Fig. 3(b): the source JSON records rho = 0.962 from ordinal ranks; two candidates tie on the analytic cost, and the standard Spearman with average ranks over the same 13 candidates is the value printed (see `data/fig3_booksim_rho.json`). The 154,037 packets are the size of ONE candidate's batch, not a total.\n",
           "- Fig. 5(a-c) is a new controlled instance: the 25 flows are the real ffn1->ffn2 hand-off of the 2.7B mapping, re-placed on a 4x4 mesh and re-scored by the evaluator's own flow and load code. Its numbers are hand-off service costs on that instance and are not the 24x24 stage readings of v1 (26.2 / 21.0 / 13.1 ms), which belong to the 544-die layouts.\n",
           "- Fig. 5(d) keeps the recorded denominator (the best resource-aware endpoint); the +11.4% / +11.2% labels are each proxy's best endpoint, the other seeds are drawn as points.\n",
           "- Fig. 6(b): the 128- and 1024-token per-operator accounts are derived from the measured 512-token account (compute per row, write per row, closed-form elementwise); the appended searches fall back to the frozen layout at all six workloads, their raw endpoints are in workload_reuse/per_run.csv. The appended searches are not drawn; their summary is in fig6_placement_reuse.csv.\n",
           "- Only the PDFs, the data, the captions and this index are committed; SVG and PNG come back from the command in the header.\n"]
    open(os.path.join(root, "figure_index.md"), "w").write("".join(idx))
    man = {"run_id": run_id, "generator": "scripts/plot_dac2027_v2.py", "command": " ".join(argv),
           "configuration": {"model": "2.7B class", "phase": "prefill", "S": 512, "dies": "544 of 576",
                             "grid": "24x24 mesh, XY", "row_time_s": 10.14e-6, "kappa": 2.0,
                             "link_gbps": 0.4, "small_instance": {"grid": "4x4", "handoff": "ffn1->ffn2",
                                                                  "flows": 25, "kappa": 2.0, "link_gbps": 0.4}},
           "preexisting_outputs_check": V1._preexisting_check(),
           "products": PRODUCTS}
    json.dump(man, open(os.path.join(root, "manifest.json"), "w"), indent=1)
    print("   captions.md, figure_index.md, manifest.json")


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
    wanted = [w.strip() for w in args.only.split(",") if w.strip()] or ["fig5", "fig2", "fig3", "fig4", "fig6", "fig1"]
    inst = None
    for w in wanted:
        print(f"[{w}]")
        if w == "fig5":
            inst = fig5()
        elif w == "fig2":
            fig2()
        else:
            {"fig1": fig1, "fig3": fig3, "fig4": fig4, "fig6": fig6}[w]()
    write_docs(args.run_id, sys.argv)
    print(f"\n-> {root}")


if __name__ == "__main__":
    main()
