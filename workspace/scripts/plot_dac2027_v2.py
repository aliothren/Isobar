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
save, dump_json, dump_csv, load, tidy = V1.save, V1.dump_json, V1.dump_csv, V1.load, V1.tidy
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


def _draw_small(ax, L, vmax, vmin, show_key=False):
    """The 4x4 instance as a node graph: labelled endpoints, both link
    directions as parallel offset lines coloured and widened by the service
    time they owe, unused links faint, the busiest resource ringed."""
    nx, ny = GRID
    norm = Normalize(vmin, vmax)
    off = 0.09
    node_r = 0.24
    used = {}
    for l in L["links"]:
        used[(l["x0"], l["y0"], l["x1"], l["y1"], l["dir"])] = l
    for x in range(nx):
        for y in range(ny):
            for (x1, y1) in ((x + 1, y), (x, y + 1)):
                if x1 >= nx or y1 >= ny:
                    continue
                horiz = y1 == y
                for d in ("+", "-"):
                    s = 1 if d == "+" else -1
                    dx, dy = (0, s * off) if horiz else (-s * off, 0)
                    l = used.get((x, y, x1, y1, d))
                    x0e, x1e = x + node_r * (1 if horiz else 0), x1 - node_r * (1 if horiz else 0)
                    y0e, y1e = y + node_r * (0 if horiz else 1), y1 - node_r * (0 if horiz else 1)
                    if l is None:
                        ax.plot([x0e + dx, x1e + dx], [y0e + dy, y1e + dy], color="#e4e8eb",
                                lw=0.7, solid_capstyle="butt", zorder=1)
                        continue
                    frac = norm(l["service_ms"])
                    ax.plot([x0e + dx, x1e + dx], [y0e + dy, y1e + dy],
                            color=LOAD_CMAP(frac), lw=1.6 + 3.2 * frac,
                            solid_capstyle="butt", zorder=2 + frac)
                    # a small arrowhead for the direction
                    mx, my = (x0e + x1e) / 2 + dx, (y0e + y1e) / 2 + dy
                    ux, uy = ((1, 0) if horiz else (0, 1))
                    if d == "-":
                        ux, uy = -ux, -uy
                    ax.annotate("", xy=(mx + 0.06 * ux, my + 0.06 * uy),
                                xytext=(mx - 0.06 * ux, my - 0.06 * uy),
                                arrowprops=dict(arrowstyle="-|>", color="white", lw=0.4,
                                                mutation_scale=5), zorder=4)
    # nodes
    for x in range(nx):
        for y in range(ny):
            ax.add_patch(Circle((x, y), node_r, fc="#f6f8fa", ec="#c9d2d9", lw=0.6, zorder=5))
    for ep in L["endpoints"]:
        fc = SLATE if ep["role"] == "producer" else BRICK
        if ep["role"] == "producer":
            ax.add_patch(Rectangle((ep["x"] - node_r, ep["y"] - node_r), 2 * node_r,
                                   2 * node_r, fc=fc, ec="#1d2f3d", lw=0.6, zorder=6))
        else:
            ax.add_patch(Circle((ep["x"], ep["y"]), node_r, fc=fc, ec="#4a2412",
                                lw=0.6, zorder=6))
        ax.text(ep["x"], ep["y"], ep["id"], ha="center", va="center", fontsize=6.4,
                color="white", fontweight="bold", zorder=7)
    # the busiest resource: ring a link, or a port node
    top = L["busiest_words"]
    if L["binding"] in ("link", "tie"):
        for l in L["links"]:
            if l["words"] >= top - 1e-6:
                horiz = l["y0"] == l["y1"]
                s = 1 if l["dir"] == "+" else -1
                dx, dy = (0, s * off) if horiz else (-s * off, 0)
                mx, my = (l["x0"] + l["x1"]) / 2 + dx, (l["y0"] + l["y1"]) / 2 + dy
                ax.add_patch(Circle((mx, my), 0.16, fc="none", ec="#08131c", lw=1.1,
                                    zorder=8))
                # put the label where it is farthest from every node centre
                cands = [((0.0, 0.50), "center", "bottom"), ((0.0, -0.50), "center", "top"),
                         ((0.40, 0.0), "left", "center"), ((-0.40, 0.0), "right", "center")]
                nodes = [(x, y) for x in range(nx) for y in range(ny)]
                def clearance(c):
                    (ox_, oy_), ha_, va_ = c
                    tx, ty = mx + ox_, my + oy_
                    # the text box: ~0.78 wide, ~0.42 tall, anchored by ha/va
                    x0 = tx - {"center": 0.39, "left": 0.0, "right": 0.78}[ha_]
                    y0 = ty - {"center": 0.21, "bottom": 0.0, "top": 0.42}[va_]
                    x1, y1 = x0 + 0.78, y0 + 0.42
                    if x0 < -0.65 or x1 > nx - 0.35 or y0 < -0.7 or y1 > ny - 0.3:
                        return -1
                    def gap(a, b):
                        ddx = max(x0 - a, a - x1, 0.0)
                        ddy = max(y0 - b, b - y1, 0.0)
                        return math.hypot(ddx, ddy) - node_r
                    return min(gap(a, b) for a, b in nodes)
                (ox, oy), ha, va = max(cands, key=clearance)
                ax.text(mx + ox, my + oy, f"{l['flows']} flows\n{l['service_ms']:.1f} ms",
                        ha=ha, va=va, fontsize=6.2, color="#08131c", zorder=9,
                        linespacing=1.15, bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.0))
                break
    if L["binding"] in ("port", "tie"):
        for p in L["ports"]:
            if p["words_over_kappa"] >= top - 1e-6:
                ax.add_patch(Circle((p["x"], p["y"]), node_r + 0.10, fc="none",
                                    ec="#08131c", lw=1.1, ls=(0, (2, 1.5)), zorder=8))
                ax.annotate(f"port {p['side']}\n{p['service_ms']:.1f} ms",
                            (p["x"], p["y"]), textcoords="offset points",
                            xytext=(0, -16), ha="center", va="top", fontsize=6.2,
                            color="#08131c", zorder=9, linespacing=1.15)
                break
    ax.set_xlim(-0.7, nx - 0.3); ax.set_ylim(-0.75, ny - 0.3)
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def _small_readings(L):
    return (f"busiest resource {L['busiest_service_ms']:.1f} ms ({L['binding']})\n"
            f"{L['word_hops'] / 1e6:.1f} M word-hops")


# =====================================================================
# Fig. 5  the mechanism on a controlled 4x4 instance + the main-config ablation
# =====================================================================
def _fig5_networks(inst, names, fname, composite=True, width=PAGE_WIDTH):
    Ls = [inst["layouts"][n] for n in names]
    vmax = max(l["service_ms"] for L in Ls for l in L["links"])
    vmin = min(l["service_ms"] for L in Ls for l in L["links"]) * 0.9
    fig = plt.figure(figsize=(width, width * 0.42))
    gs = fig.add_gridspec(1, len(names) + 1, width_ratios=[1] * len(names) + [0.05],
                          wspace=0.05, left=0.01, right=0.93, top=0.86, bottom=0.14)
    for i, (n, L) in enumerate(zip(names, Ls)):
        ax = fig.add_subplot(gs[0, i])
        _draw_small(ax, L, vmax, vmin)
        ax.set_title(f"({'abc'[i]}) {L['label']}", fontsize=FS["title"],
                     color=FAM[L["family"]], pad=2)
        ax.text(0.5, -0.02, _small_readings(L), transform=ax.transAxes, fontsize=FS["note"],
                ha="center", va="top", linespacing=1.3, color=INK)
    cax = fig.add_subplot(gs[0, -1])
    sm = matplotlib.cm.ScalarMappable(norm=Normalize(vmin, vmax), cmap=LOAD_CMAP)
    cb = fig.colorbar(sm, cax=cax)
    cb.set_label("link service time (ms)", fontsize=FS["note"])
    cb.ax.tick_params(labelsize=FS["small"])
    cb.outline.set_linewidth(0.5)
    h = inst["handoff"]
    fig.text(0.47, 0.965, f"{len(Ls[0]['prod'])} producers → {len(Ls[0]['cons'])} consumers; "
             f"{h['n_flows']} flows, {h['words_total'] / 1e6:.1f} M words",
             ha="center", va="top", fontsize=FS["note"], color=INK)
    save(fig, fname, composite=composite,
         sources=["scripts/search_eval.py (live: _one_boundary_flows, resource_loads)",
                  "scripts/interconnect.py (Mesh 4x4, xy)"],
         note="controlled instance; not the 544-die layouts")
    return vmax, vmin


def _fig5_ablation(ax):
    """Same space, solver, budget, starts and seeds; only the objective
    changes. Every endpoint is re-scored under the system latency and shown
    as excess over the best resource-aware endpoint, from zero."""
    ab = load("objective_ablation_k2.json")["cells"]["k2"]
    names = ["ours", "word_hops", "max_hops"]
    labels = ["Resource-aware\n(links + ports)", "Word-hops\n(distance proxy)",
              "Max hops\n(propagation proxy)"]
    cols = [GREEN, AMBER, GREY]
    base = ab["per_objective"]["ours"]["T_best_s"]
    rows = []
    for i, n in enumerate(names):
        ends = ab["per_objective"][n]["endpoints"]
        ex = sorted(100 * (ab["rows"][e]["T_single_s"] / base - 1) for e in ends)
        rows.append({"objective": n, "excess_pct": ex})
        ax.plot([i] * len(ex), ex, marker="o", ms=5, mfc="white", mec=cols[i], mew=1.2,
                ls="none", zorder=4)
        ax.plot([i], [ex[0]], marker="_", ms=16, mew=2.0, color=cols[i], zorder=5)
        if n != "ours":
            ax.annotate(f"best proxy: +{ex[0]:.1f}%", (i, ex[0]), textcoords="offset points",
                        xytext=(0, -11), ha="center", va="top", fontsize=FS["note"],
                        color=cols[i])
        else:
            ax.annotate("reference", (i, ex[-1]), textcoords="offset points",
                        xytext=(0, 9), ha="center", va="bottom", fontsize=FS["note"],
                        color=cols[i])
    ax.axhline(0, color=GREEN, lw=0.9, ls=(0, (3, 2)), zorder=3)
    ax.set_xticks(range(3)); ax.set_xticklabels(labels, fontsize=FS["tick"])
    ax.set_xlim(-0.5, 2.5); ax.set_ylim(-2.5, 16)
    ax.set_ylabel("Excess latency vs best\nresource-aware result (%)", fontsize=FS["axis"])
    ax.set_title("(d) Objective ablation, main configuration", fontsize=FS["title"])
    ax.legend(handles=[Line2D([], [], marker="o", mfc="white", mec=INK, ls="none", ms=5),
                       Line2D([], [], marker="_", ms=14, mew=2, color=INK, ls="none")],
              labels=["one seed", "best of the three seeds"], fontsize=FS["small"],
              loc="upper left", frameon=False)
    tidy(ax, grid="y")
    return ab, base, rows


def fig5():
    inst = _small_instance()
    rep = inst["representative"]
    names = [rep["compact"], rep["random"], rep["search"]]
    vmax, vmin = _fig5_networks(inst, names, "fig5_small_mesh_triptych")
    for n in names:
        f, a = plt.subplots(figsize=(COL_WIDTH * 0.62, COL_WIDTH * 0.66))
        _draw_small(a, inst["layouts"][n], vmax, vmin)
        a.set_title(inst["layouts"][n]["label"], fontsize=FS["title"],
                    color=FAM[inst["layouts"][n]["family"]])
        a.text(0.5, -0.02, _small_readings(inst["layouts"][n]), transform=a.transAxes,
               fontsize=FS["note"], ha="center", va="top", linespacing=1.3)
        f.tight_layout()
        save(f, f"fig5_small_mesh_{n}", sources=["scripts/search_eval.py (live)"])
    # link-load profile candidate: loads in descending order for the three layouts
    f, a = plt.subplots(figsize=(COL_WIDTH * 1.1, COL_WIDTH * 0.85))
    for n in names:
        L = inst["layouts"][n]
        v = sorted((l["service_ms"] for l in L["links"]), reverse=True)
        a.step(range(1, len(v) + 1), v, where="mid", color=FAM[L["family"]], lw=1.5,
               label=L["label"])
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
    f, a = plt.subplots(figsize=(COL_WIDTH * 1.05, COL_WIDTH * 0.9))
    ab, base, abrows = _fig5_ablation(a)
    f.tight_layout()
    save(f, "fig5d_objective_ablation", sources=["analysis/objective_ablation_k2.json"])
    # composite: three small-mesh panels over the ablation dot plot
    fig = plt.figure(figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.74))
    gs = fig.add_gridspec(2, 4, height_ratios=[1.0, 0.78], width_ratios=[1, 1, 1, 0.05],
                          wspace=0.05, hspace=0.42, left=0.01, right=0.93, top=0.92,
                          bottom=0.10)
    for i, n in enumerate(names):
        ax = fig.add_subplot(gs[0, i])
        L = inst["layouts"][n]
        _draw_small(ax, L, vmax, vmin)
        ax.set_title(f"({'abc'[i]}) {L['label']}", fontsize=FS["title"], color=FAM[L["family"]], pad=2)
        ax.text(0.5, -0.02, _small_readings(L), transform=ax.transAxes, fontsize=FS["note"],
                ha="center", va="top", linespacing=1.3, color=INK)
    cax = fig.add_subplot(gs[0, 3])
    sm = matplotlib.cm.ScalarMappable(norm=Normalize(vmin, vmax), cmap=LOAD_CMAP)
    cb = fig.colorbar(sm, cax=cax)
    cb.set_label("link service time (ms)", fontsize=FS["note"])
    cb.ax.tick_params(labelsize=FS["small"])
    h = inst["handoff"]
    fig.text(0.47, 0.975, f"5 producers → 5 consumers; {h['n_flows']} flows, "
             f"{h['words_total'] / 1e6:.1f} M words", ha="center", va="top",
             fontsize=FS["note"], color=INK)
    axd = fig.add_subplot(gs[1, :])
    _fig5_ablation(axd)
    axd.set_position([0.20, 0.09, 0.58, 0.30])
    save(fig, "fig5_mechanism_and_ablation", composite=True,
         sources=["scripts/search_eval.py (live)", "analysis/objective_ablation_k2.json"])
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
                       f"{base * 1e3:.2f} ms",
        "excess_pct_by_objective": abrows,
        "recorded_loss_avoided_pct": {n: ab["per_objective"][n]["loss_avoided_by_ours_pct"]
                                      for n in ("word_hops", "max_hops")}},
        sources=["analysis/objective_ablation_k2.json"])
    reps = {k: inst["layouts"][v] for k, v in rep.items()}
    CAPTIONS["fig5"] = (
        "Fig. 5. Where link stacking comes from, and what the objective is worth. "
        "(a)-(c) One ffn hand-off of the 2.7B mapping, five producer dies to five consumer "
        f"dies, {h['n_flows']} flows of {h['words_per_flow'] / 1e6:.2f} M words, placed on a "
        "4x4 die mesh with XY routing, 0.4 GB/s per link direction and ports at twice "
        "the link rate; six slots stay empty. Every panel carries the same flows; only the "
        "placement differs. Each link direction is a line coloured and widened by the "
        "service time it owes; the busiest resource is ringed with its flow count. "
        f"The compact fill stacks {reps['compact']['busiest_service_ms']:.1f} ms on one link, "
        f"the best of five random fills {reps['random']['busiest_service_ms']:.1f} ms, and "
        f"the search {reps['search']['busiest_service_ms']:.1f} ms; the port floor is "
        f"{reps['search']['max_port_service_ms']:.2f} ms and never binds here. The search "
        "is the same annealer as the main configuration (1200 steps, two starts, three "
        "seeds, best over starts per seed, median seed shown). These are hand-off service "
        "costs on a controlled instance, not whole-model gains. (d) The main configuration's "
        "objective ablation: the same search with only the objective replaced, every "
        "endpoint re-scored under the system latency and shown as excess over the best "
        "resource-aware endpoint; the distance and hop proxies select layouts 11.4% and "
        "11.2% slower at their best seed.")
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
         dict(id="core", x=370, y=1010, w=570, h=600, fill="#eef4fa", edge="#5a96cc",
              title="Isobar evaluation core"),
         dict(id="phase", x=980, y=1010, w=290, h=270, fill="#f0f8fa", edge="#68b4ce",
              title="Phase analysis"),
         dict(id="search", x=980, y=1330, w=290, h=280, fill="#f8f6e4", edge="#d6cf67",
              title="Deployment search")]
    CORE = dict(fill="#5a96cc", edge="#5a96cc", elw=1.2, text="white")
    INP = dict(fill="white", edge="#a5c582", elw=3.2, text=TXT)
    PH = dict(fill="#a4d2e2", edge="#a4d2e2", elw=1.2, text="black")
    SR = dict(fill="#d6cf67", edge="#d6cf67", elw=1.2, text=TXT)
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
        dict(pts=[(1125, 1470), (1125, 1500)], col="#8d8944", lw=2.5),
        dict(pts=[(1270, 1470), (1290, 1470), (1290, 980), (200, 980), (200, 1010)],
             col="#8d8944", lw=3, label=("Updated deployment", 282.5, 965))]
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
    W, H = 2.24, 3.00
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
    ox, oy, s = 0.376, 1.618, 0.443                 # mesh origin and pitch (in)
    r, off = 0.136, 0.057
    LANE, RIM = 4.6, 0.4                            # lane fill width, rim width (pt)
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
    cb_x, cb_w = X(nx - 1) + r + 0.15, 0.072
    cbx = ax.inset_axes((cb_x, oy - r, cb_w, 0.60), transform=ax.transData)
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
    bx = ax.inset_axes((x_left, 0.28, x_right - x_left, 0.98), transform=ax.transData)
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
    Wt, Ht = 7.46, 3.00                              # (a) 5.02 + gap 0.20 + (b) 2.24
    fig = plt.figure(figsize=(Wt, Ht))
    axa = _inch_axes(fig, [0, 0, 5.02 / Wt, 1], 5.02, Ht); _fig2a(axa)
    axb = _inch_axes(fig, [5.22 / Wt, 0, 2.24 / Wt, 1], 2.24, Ht); _fig2b(axb, I)
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
    f = plt.figure(figsize=(2.24, 3.00)); a = _inch_axes(f, [0, 0, 1, 1], 2.24, 3.00); _fig2b(a, I)
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
    ax.set_ylim(0.85, 2.85)
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

    lim = [0.55, 5.2]
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
    ins = ax.inset_axes([0.07, 0.50, 0.44, 0.47])
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


def _same_box(axes):
    """After tight_layout, give the two panels one axes width and height
    (the left panel keeps its left edge, the right panel its right edge)."""
    pa, pb = axes[0].get_position(), axes[1].get_position()
    w, h = min(pa.width, pb.width), min(pa.height, pb.height)
    axes[0].set_position([pa.x0, pa.y0, w, h])
    axes[1].set_position([pb.x1 - w, pb.y0, w, h])


def fig3():
    SRC = ["analysis/simba_t1.json", "analysis/b_fanout_24x24_rerank.json"]
    fig, axes = plt.subplots(1, 2, figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.44))
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
        ax.barh(y, R, color=C_R, ec="white", lw=0.5, height=0.62, zorder=3)
        ax.barh(y, H, left=R, color=C_H, ec="white", lw=0.5, height=0.62, zorder=3)
        ax.text(R + H + 45, y, f"{R + H:.0f}", va="center", ha="left", fontsize=FS["note"],
                color=FAM[family(n)], zorder=4)
    ax.set_yticks(ys)
    ax.set_yticklabels([BAR_NAME.get(n, label(n)) for n in BAR_ORDER], fontsize=FS["tick"])
    for tick, n in zip(ax.get_yticklabels(), BAR_ORDER):
        tick.set_color(FAM[family(n)])
    ax.set_xlabel("Whole-model prefill latency (ms)", fontsize=FS["axis"])
    ax.set_xlim(0, 5000)
    ysr = ys[-1]
    yb = ysr - 0.95
    ax.annotate("", xy=(T["sa_random_s1"], yb), xytext=(T["default_A4"], yb),
                arrowprops=dict(arrowstyle="<|-|>", color=NAVY, lw=0.9, mutation_scale=7))
    ax.text((T["sa_random_s1"] + T["default_A4"]) / 2, yb - 0.20,
            f"{100 * (1 - T['sa_random_s1'] / T['default_A4']):.1f}% below the default fill",
            fontsize=FS["note"], color=NAVY, ha="center", va="top")
    ax.set_ylim(yb - 0.95, max(ys) + 0.6)
    ax.legend(handles=[Rectangle((0, 0), 1, 1, fc=C_R, ec="none"),
                       Rectangle((0, 0), 1, 1, fc=C_H, ec="none")],
              labels=["Non-communication", "Package communication"], fontsize=FS["note"],
              loc="upper right", bbox_to_anchor=(1.0, 0.79), frameon=False)
    ax.set_title("(a) Whole-model latency of the evaluated placements", fontsize=FS["title"])
    tidy(ax, grid="x")
    if with_points:
        # every sample on one short axis: the five random fills and the nine
        # search endpoints; the representative and the best random marked
        rnd = sorted(T[n] for n in mc if n.startswith("random"))
        sea = sorted(T[n] for n in mc if n.startswith("sa_"))
        ins = ax.inset_axes([0.585, 0.23, 0.40, 0.30])
        ins.plot(rnd, [1] * len(rnd), marker="o", ms=4.5, color=GREY, mec="white", mew=0.4,
                 ls="none", zorder=5)
        ins.plot([T["random_s3"]], [1], marker="o", ms=5.5, color=GREY, mec=INK, mew=0.7,
                 ls="none", zorder=6)
        ins.plot(sea, [0] * len(sea), marker="*", ms=7, color=GREEN, mec="white", mew=0.4,
                 ls="none", zorder=5)
        ins.plot([T["sa_random_s1"]], [0], marker="*", ms=9.5, color=GREEN, mec=INK, mew=0.7,
                 ls="none", zorder=6)
        ins.annotate("", xy=(T["sa_random_s1"], 0.5), xytext=(T["random_s3"], 0.5),
                     arrowprops=dict(arrowstyle="<|-|>", color=GREEN, lw=0.8, mutation_scale=6))
        ins.text((T["sa_random_s1"] + T["random_s3"]) / 2, 0.58,
                 f"{100 * (1 - T['sa_random_s1'] / T['random_s3']):.2f}%", ha="center",
                 va="bottom", fontsize=FS["small"], color=GREEN)
        ins.set_xlim(1880, 2180); ins.set_ylim(-0.55, 1.55)
        ins.set_yticks([])
        ins.text(1888, 1, "5 random fills", fontsize=FS["small"], color=GREY, ha="left",
                 va="center")
        ins.text(2172, 0, "9 search endpoints", fontsize=FS["small"], color=GREEN, ha="right",
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
                ms=(11 if fam == "search" else 7) if big else (7 if fam == "search" else 4.5),
                color=FAM[fam], mec=INK if big else "white", mew=0.8 if big else 0.4,
                ls="none", zorder=6 if big else 5, label=None if fam in seen else FAM_LABEL[fam])
        seen.add(fam)
    dT = lambda n: 100 * (en[n]["T_s"] / Tr - 1)
    dE = lambda n: 100 * (en[n]["E_total_J"] / Er - 1)
    notes = (("default_A4", "Default (stacked fill)", (-10, 2), "right", "center"),
             ("snake", "Snake", (-8, 4), "right", "bottom"),
             ("heaviest_first", "Heaviest first", (8, 0), "left", "center"),
             ("least_manhattan", f"Least Manhattan\n{dE('least_manhattan'):+.1f}% energy, "
                                 f"{dT('least_manhattan'):+.1f}% latency", (0, 12), "center", "bottom"),
             ("clustered", "Clustered", (10, 0), "left", "center"),
             ("random_s3", "Best random", (12, -4), "left", "top"),
             ("sa_random_s1", f"Search (representative)\n{dT('sa_random_s1'):+.2f}% latency, "
                              f"{dE('sa_random_s1'):+.2f}% energy", (-22, -12), "left", "top"))
    for n, lab, off, ha, va in notes:
        ax.annotate(lab, (en[n]["T_s"] * 1e3, en[n]["E_total_J"]), textcoords="offset points",
                    xytext=off, fontsize=FS["small"], ha=ha, va=va, color=FAM[family(n)],
                    linespacing=1.2)
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
    ax.bar(xs, b1, width=0.55, color="#9db8c9", ec="white", lw=0.6, label="Attention die", zorder=3)
    ax.bar(xs, b2, bottom=b1, width=0.55, color="#c9a86a", ec="white", lw=0.6, label="FFN die", zorder=3)
    ax.bar(xs, [rest, rest], bottom=np.add(b1, b2), width=0.55, color="#dfe4e8", ec="white", lw=0.6,
           label="Other costs incl.\npackage transfers", zorder=3)
    for x, tot in zip(xs, (ship, best)):
        ax.text(x, tot + 0.8, f"{tot:.2f} ms", ha="center", va="bottom", fontsize=FS["note"], color=INK)
    ya = ship + 7.5
    ax.annotate("", xy=(1, ya), xytext=(0, ya),
                arrowprops=dict(arrowstyle="-|>", color=GREEN, lw=0.9, mutation_scale=7))
    ax.text(0.5, ya + 1.0, f"−{100 * (1 - best / ship):.2f}%", ha="center", va="bottom",
            fontsize=FS["note"], color=GREEN, fontweight="bold")
    ax.set_xticks(xs); ax.set_xticklabels(["Contiguous", "Enumerated\noptimum"], fontsize=FS["tick"])
    ax.set_xlim(-0.55, 1.55)
    ax.set_ylabel("Layer latency (ms)", fontsize=FS["axis"])
    ax.set_ylim(0, ship * 2.0); ax.set_yticks([0, 20, 40, 60, 80])
    ax.set_title("(c) Whole-layer impact of\nintra-die assignment", fontsize=FS["title"])
    ax.legend(fontsize=FS["small"], loc="upper left", frameon=False, labelspacing=0.3)
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
    it, ship, best, rest = _fig4c(fig.add_subplot(gs[1, 2]))
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
        "write, digital unit) and the package hand-offs. Best random is the strongest of the "
        "five random fills (seeds 0 to 4); Search (representative) is the median of three "
        "seeds after taking the best of three starts per seed. The inset places all five "
        "random fills and all nine search endpoints on one axis: every endpoint is below "
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
        "and the -0.26% here are not the same comparison. (c) An independent intra-die "
        "instance, the one Fig. 1(a) refers to: one GPT-2-medium class layer over an attention "
        "die and an FFN die, each a 2x4 macro mesh, at 0.4 GB/s; the enumerated optimum over "
        "280 and 70 macro assignments against the contiguous assignment, with the fixed rest "
        f"of the layer ({rest:.2f} ms incl. two package transfers) included, so the 9.02% is "
        "the whole-layer gain. Not the 2.7B system of (a) and (b); energy is not modelled at "
        "this level.")


# =====================================================================
# Fig. 6  conditions
# =====================================================================
def _fig6a(ax):
    sl = load("bw_slice_k2.json")
    pts = sorted(sl["points"].values(), key=lambda p: p["B_gbps"])
    B = [p["B_gbps"] for p in pts]
    G, eta, r = ([100 * p[k] for p in pts] for k in ("G", "eta", "r"))
    ax.axvspan(sl["B_minus_gbps"], sl["B_plus_gbps"], color=CREAM, alpha=0.55, lw=0, zorder=1)
    ax.text(np.sqrt(sl["B_minus_gbps"] * sl["B_plus_gbps"]), 74, "placement-\ndependent band",
            fontsize=FS["small"], ha="center", va="top", color="#6b5a2a", linespacing=1.2)
    ax.plot(B, r, ls="--", lw=1.2, color=AMBER, marker="s", ms=3.5, zorder=3,
            label="r: communication share of the reference")
    ax.plot(B, eta, ls=(0, (1.5, 1.8)), lw=1.3, color=SLATE, marker="D", ms=3.5, zorder=4,
            label="\u03b7: communication improvement of the pair")
    ax.plot(B, G, marker="o", ms=4.5, lw=1.7, color=GREEN, zorder=5, label="G: whole-model gain")
    for p in pts:
        if abs(p["B_gbps"] - 0.4) < 1e-6:
            ax.annotate(f"{100 * p['G']:.2f}%", (p["B_gbps"], 100 * p["G"]),
                        textcoords="offset points", xytext=(0, -8), ha="center", va="top",
                        fontsize=FS["note"], color=GREEN)
        elif 0.85 < p["B_gbps"] < 0.9:
            ax.annotate(f"{100 * p['G']:.2f}%", (p["B_gbps"], 100 * p["G"]),
                        textcoords="offset points", xytext=(0, 7), ha="center", va="bottom",
                        fontsize=FS["note"], color=GREEN)
        elif p["B_gbps"] > 10:
            ax.annotate(f"{100 * p['G']:.2f}%", (p["B_gbps"], 100 * p["G"]),
                        textcoords="offset points", xytext=(-6, 8), ha="right", va="bottom",
                        fontsize=FS["note"], color=GREEN)
    ax.set_xscale("log")
    ax.set_xticks([0.2, 0.4, 0.872, 2, 12.5])
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_xlabel("Link bandwidth per direction (GB/s)", fontsize=FS["axis"])
    ax.set_ylabel("Percent", fontsize=FS["axis"])
    ax.set_ylim(0, 80)
    ax.text(0.97, 0.94, "G = η · r at every point", transform=ax.transAxes,
            fontsize=FS["note"], ha="right", va="top", color=INK)
    ax.set_title("(a) Bandwidth response of fixed placements", fontsize=FS["title"])
    ax.legend(fontsize=FS["small"], loc="upper center", bbox_to_anchor=(0.5, -0.20), ncol=1,
              frameon=False, handlelength=2.2)
    tidy(ax)
    return sl, pts


def _fig6b(ax, bw="0.4"):
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
    for grid, col, mk in (("24x24", GREEN, "o"), ("12x48", SLATE, "s")):
        ks = sorted(k for (g, k) in stat if g == grid)
        med = [stat[(grid, k)]["median"] for k in ks]
        lo = [stat[(grid, k)]["median"] - stat[(grid, k)]["lo"] for k in ks]
        hi = [stat[(grid, k)]["hi"] - stat[(grid, k)]["median"] for k in ks]
        ax.errorbar(ks, med, yerr=[lo, hi], marker=mk, ms=5, lw=1.5, color=col, capsize=2.5,
                    elinewidth=0.9, label=f"{grid} package", zorder=4)
    ax.set_xticks([1, 2, 4]); ax.set_xlim(0.7, 4.4); ax.set_ylim(0, 12)
    ax.set_xlabel("Port capacity / link capacity, κ", fontsize=FS["axis"])
    ax.set_ylabel("Gain over the strongest baseline\nof the same cell (%)", fontsize=FS["axis"])
    ax.set_title("(b) Port capacity and mesh geometry", fontsize=FS["title"])
    ax.text(1.12, 3.9, "port capacity limits\nthe remaining gain", fontsize=FS["small"], ha="left",
            va="bottom", color=INK, linespacing=1.25)
    ax.text(3.0, 11.3, "ports no longer bind", fontsize=FS["small"], ha="center", va="top", color=INK)
    leg = ax.legend(fontsize=FS["small"], loc="lower right", frameon=False,
                    title="median of three seeds; bars: range")
    leg.get_title().set_fontsize(FS["small"])
    tidy(ax)
    return stat


def fig6():
    SRC = ["analysis/bw_slice_k2.json", "analysis/kappa_geometry_sweep.json"]
    fig, axes = plt.subplots(1, 2, figsize=(PAGE_WIDTH, PAGE_WIDTH * 0.40))
    sl, pts = _fig6a(axes[0]); stat = _fig6b(axes[1])
    fig.tight_layout()
    save(fig, "fig6_conditions", composite=True, sources=SRC)
    for tag, fn in (("fig6a_bandwidth_response", _fig6a), ("fig6b_port_geometry", _fig6b)):
        f, a = plt.subplots(figsize=(COL_WIDTH * 1.25, COL_WIDTH * 1.0)); fn(a); f.tight_layout()
        save(f, tag, sources=SRC)
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
    CAPTIONS["fig6"] = (
        "Fig. 6. The conditions that set the value of placement. (a) One fixed pair of "
        "layouts, the best random fill and the representative search layout of Fig. 4, "
        "re-scored at each bandwidth without a new search. The communication share r of the "
        "reference, the communication improvement η of the pair and the whole-model gain "
        "G are all percentages, and G = η r holds at every point; the shaded band is the "
        "placement-dependent band of Fig. 1(b) for the seven named rules at the NeuRRAM row "
        f"rate ({sl['B_minus_gbps']:.3f} to {sl['B_plus_gbps']:.3f} GB/s). (b) The search gain "
        "against the strongest evaluated baseline of each cell for two package geometries and "
        "three port capacities at 0.4 GB/s: per seed the best of three starts, then the "
        "median and the range over three seeds. At κ = 1 the port capacity limits the "
        "remaining gain; at κ = 2 and 4 the endpoints are link-bound and the two "
        "geometries agree within the seed range.")


# =====================================================================
# Fig. 1
# =====================================================================
def fig1():
    """Fig. 1 is the print version of the standing phase diagram, rendered by
    its own generator with the outputs redirected into this run; the two
    panels are cropped from the same rendering."""
    from scripts import fig_phase_isobar_print as P
    src = ["scripts/fig_phase_isobar_print.py", "scripts/fig_phase_isobar.py",
           "analysis/phase_diagram_isobar_k2.json"]
    P.OUT_PNG = os.path.join(OUT["preview"], "fig1_phase_diagram.png")
    P.OUT_PDF = os.path.join(OUT["composites"], "fig1_phase_diagram.pdf")
    P.main()
    fig = plt.gcf()
    fig.savefig(os.path.join(OUT["composites"], "fig1_phase_diagram.svg"))
    PRODUCTS.append({"name": "fig1_phase_diagram", "kind": "composites",
                     "files": ["composites/fig1_phase_diagram.pdf", "composites/fig1_phase_diagram.svg",
                               "preview/fig1_phase_diagram.png"], "sources": src,
                     "note": "identical to analysis/phase_diagram_isobar_print_k2 (final form)"})
    print("   composites/fig1_phase_diagram.pdf|svg  preview/fig1_phase_diagram.png")
    r = fig.canvas.get_renderer()
    for ax, tag in zip(fig.axes[:2], ("fig1a_intra_die_phase", "fig1b_inter_die_phase")):
        bb = ax.get_tightbbox(r).transformed(fig.dpi_scale_trans.inverted()).expanded(1.04, 1.06)
        for ext, kind in (("pdf", "panels"), ("svg", "panels"), ("png", "preview")):
            fig.savefig(os.path.join(OUT[kind], f"{tag}.{ext}"), bbox_inches=bb, dpi=300)
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
           f"| fig6_conditions | {SECTION['fig6']} | the conditions that set the value of placement | (a) frozen pair re-scored; (b) 6 cells of the kappa x geometry sweep | random_s3 / sa_random_s1; per-cell runs | (a) G, eta, r as percentages, G = eta r; (b) per seed best of 3 starts, median and range over 3 seeds vs the cell's strongest baseline | bw_slice_k2.json, kappa_geometry_sweep.json |\n",
           "\n## Notes for the author (not for the paper)\n\n",
           "- Fig. 3(b): the source JSON records rho = 0.962 from ordinal ranks; two candidates tie on the analytic cost, and the standard Spearman with average ranks over the same 13 candidates is the value printed (see `data/fig3_booksim_rho.json`). The 154,037 packets are the size of ONE candidate's batch, not a total.\n",
           "- Fig. 5(a-c) is a new controlled instance: the 25 flows are the real ffn1->ffn2 hand-off of the 2.7B mapping, re-placed on a 4x4 mesh and re-scored by the evaluator's own flow and load code. Its numbers are hand-off service costs on that instance and are not the 24x24 stage readings of v1 (26.2 / 21.0 / 13.1 ms), which belong to the 544-die layouts.\n",
           "- Fig. 5(d) keeps the recorded denominator (the best resource-aware endpoint); the +11.4% / +11.2% labels are each proxy's best endpoint, the other seeds are drawn as points.\n",
           "- Fig. 6(b): every cell uses the same statistic, recomputed from the per-run records; the sensitivity table in main_config_results.md mixes best-of-nine values and is not the source here.\n",
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
